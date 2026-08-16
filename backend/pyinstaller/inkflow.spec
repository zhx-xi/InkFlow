# -*- mode: python ; coding: utf-8 -*-
# InkFlow 内核 PyInstaller 打包配置（Issue #48，spec f19-packaging §4.2）
#
# 运行（backend 目录下）：
#   uv sync --frozen --extra packaging
#   uv run pyinstaller pyinstaller/inkflow.spec
# 产物：backend/dist/inkflow/inkflow.exe + backend/dist/inkflow-mcp/inkflow-mcp.exe（onedir，各含 _internal/）

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# PyInstaller 以 spec 文件所在目录为基准解析相对路径——spec 在 pyinstaller/ 子目录，
# 必须用绝对路径锚定 backend 根（实测 pyinstaller/src/... not found）。
# 注：spec 命名空间无 __file__，用 PyInstaller 提供的 SPECPATH（spec 所在目录）。
ROOT = Path(SPECPATH).resolve().parent  # backend/

# collect_all('inkflow')：带上包内全部子模块 + 数据文件（LLM 模板 yaml 等），
# 替代手写 datas 的多数条目。
datas, binaries, hiddenimports = collect_all("inkflow")

# #421: 过滤 collect_all 收集的旧版 inkflow dist-info（uv 缓存残留），避免与当前版本 dist-info 并存导致版本注入失效
datas = [d for d in datas if not ("inkflow-" in d[1] and ".dist-info" in d[1])]

# #421 复发（rc2 实证）：PyInstaller 6.x metadata_required() 自动收集 dist-info（扫描到
# __init__.py 的 importlib.metadata.version 调用 → 内部自动 copy_metadata），uv 缓存
# 恢复旧 site-packages 残留 → 双 dist-info 进包 → importlib.metadata.version 取排序第一个
# （旧版）。修复：Analysis 前清理 site-packages 中非当前版本的 inkflow-*.dist-info
# （uv 缓存恢复的旧版残留），使 copy_metadata 与 metadata_required 都只能收集当前版本。
import re
import shutil
import site as _site
import tomllib

with open(ROOT / "pyproject.toml", "rb") as _f:
    _proj_ver = tomllib.load(_f)["project"]["version"]   # 例 "0.9.0-rc2"
_norm_ver = re.sub(r"[^0-9a-zA-Z.]+", "", _proj_ver)     # PEP 440 规范化 → "0.9.0rc2"
_target_dist = f"inkflow-{_norm_ver}.dist-info"
for _sp in _site.getsitepackages():
    for _old in Path(_sp).glob("inkflow-*.dist-info"):
        if _old.name != _target_dist:
            shutil.rmtree(_old, ignore_errors=True)
            print(f"#421: removed stale dist-info {_old}")

# ⚠️ copy_metadata（评审 🔴2）：INKFLOW_READY.version / /health 版本字段经
# importlib.metadata.version("inkflow") 读取，依赖 dist-info；
# PyInstaller 不自动收集 .dist-info，缺失则冻结 exe 抛 PackageNotFoundError。
from PyInstaller.utils.hooks import copy_metadata
datas += copy_metadata("inkflow")

# tiktoken Rust 扩展二进制（#253 rc6 补充）：tiktoken 0.13 编码数据内嵌在
# tiktoken/_tiktoken.cp3xx-win_amd64.pyd（Rust 编译扩展），PyInstaller 静态分析不可见；
# 此前 collect_data_files("tiktoken") 返回 0 文件（#256 无效）；改为 collect_all
# 一次性收集 datas/binaries/hiddenimports 三件套，缺失则冻结版 vector reindex
# 抛 ValueError: Unknown encoding cl100k_base。
_tiktoken_datas, _tiktoken_binaries, _tiktoken_hidden = collect_all("tiktoken")

# tiktoken_ext 顶层包（含 openai_public 插件）：随 tiktoken 一并收集 datas/binaries/
# hiddenimports 三件套，防止 frozen 版 tiktoken_ext 模块缺失。
_tiktoken_ext_datas, _tiktoken_ext_binaries, _tiktoken_ext_hidden = collect_all("tiktoken_ext")

# chromadb 全家桶（#253 rc5 补充）：chromadb 1.x Rust 后端子包（chromadb.api.rust）
# 由 importlib 动态导入，PyInstaller 静态分析不可见；此前逐层补 posthog/tiktoken 仍漏
# Rust 子包，改为 collect_all("chromadb") 一次性收集 datas/binaries/hiddenimports。
# 重依赖（onnxruntime/tokenizers/torch 等）仍由下方 excludes 挡住，体积可接受。
_chromadb_datas, _chromadb_binaries, _chromadb_hiddenimports = collect_all("chromadb")
datas += _chromadb_datas
binaries += _chromadb_binaries
hiddenimports += _chromadb_hiddenimports

# 运行时钩子（冒烟 2 实测）：冻结版 PyInstaller 引导器在 Windows 上重定向
# stdout/stderr 时忽略 PYTHONUTF8/PYTHONIOENCODING，退化为区域编码（本机 cp936），
# serve 打印 emoji 等字符直接 UnicodeEncodeError（Electron 内核以管道捕获 stdout
# 时同样触发）。构建期生成钩子文件（写入 %TEMP%，非仓库文件），启动时将 stdout/stderr
# 的 errors 改为 replace 优雅降级，不改动编码本身。
_runtime_hook = Path(os.environ.get("TEMP", ".")) / "inkflow_runtime_encoding_hook.py"
_runtime_hook.write_text(
    "# -*- coding: utf-8 -*-\n"
    "import sys\n"
    "for _stream in (sys.stdout, sys.stderr):\n"
    "    try:\n"
    "        _stream.reconfigure(errors=\"replace\")\n"
    "    except (AttributeError, ValueError, OSError):\n"
    "        pass\n",
    encoding="utf-8",
)

a = Analysis(
    [str(ROOT / "src" / "inkflow" / "__main__.py")],
    pathex=[str(ROOT), str(ROOT / "src")],
    runtime_hooks=[str(_runtime_hook)],
    # uvicorn 动态导入族：loop/protocol/http/lifespan 各层均运行时按需 import，
    # 静态分析不可见，必须显式列出。
    # chromadb 子模块（RAG 进包）：首次打包冒烟（--help / serve / RAG 检索）后按缺模块逐项补充。
    hiddenimports=hiddenimports
    + _tiktoken_hidden
    + _tiktoken_ext_hidden
    + [
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "sqlalchemy.dialects.sqlite.aiosqlite",  # SQLAlchemy async 引擎动态导入（实测缺失）
        "aiosqlite",  # aiosqlite dialect import_dbapi 运行时 import（实测缺失）
        "chromadb.telemetry.product.posthog",  # #253 rc3 vector reindex 打包缺模块（RAG 进包补充）
        # ⚠️ 不收集 langchain_community.embeddings（评审 🔴4）：B+ 后源码 0 引用；
        #    其 PEP 562 懒加载 + TYPE_CHECKING import 会被静态分析跟进，
        #    拖回 torch/transformers/sentence_transformers 全家，T0 瘦身全废。
    ],
    # T0 排除清单（spike 2026-08-06 定稿，spec §3.3/§4.4）：
    # chromadb 云组件（onnxruntime/kubernetes/tokenizers——API embedding 路径不可达）
    # + ADR-005v2 残留（litellm）+ torch 族兜底（静态分析误跟时强制不进包）。
    excludes=[
        "onnxruntime",
        "kubernetes",
        "tokenizers",
        "litellm",
        "torch",
        "transformers",
        "sentence_transformers",
    ],
    datas=datas + _tiktoken_datas + _tiktoken_ext_datas,
    binaries=binaries + _tiktoken_binaries + _tiktoken_ext_binaries,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir：程序主体与依赖二进制交由 COLLECT 收集
    name="inkflow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    console=True,
    disable_windowed_traceback=False,
    # icon：backend 无 .ico 资产，省略（spec §4.2「图标可选」）
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    name="inkflow",
)

# #424: 打包产物缺 inkflow-mcp.exe（0.9.0-rc3 实证）。F20 spec §1.2 要求打包产物含
# inkflow-mcp.exe（PyInstaller 随 CLI 产物，发布验证四件套），但旧 spec 只有单个 EXE。
# dev venv 有 Scripts/inkflow-mcp.exe 且 MCP 握手 15 工具正常，纯打包缺口。
# 修复：新增独立 onedir 产物 inkflow-mcp——入口为 src/inkflow/mcp/__main__.py
# （stdio 薄客户端经 HTTP 连本地内核，不启动 uvicorn；勿用根 __main__.py 的 serve）。
# #424 v3（rc5 实测）：MCP 薄客户端 import 链（inkflow.http -> config -> db -> aiosqlite）
# 在打包版冷启动 tools/call 报 No module named 'aiosqlite'。独立 Analysis 的 hiddenimports
# 漏了主内核关键动态模块，需与主 Analysis 显式列表同源补齐，防止再次复发。
# 独立 Analysis 保证 a_mcp.scripts 只含 mcp 入口；datas/binaries 复用主 Analysis
# 结果（MCP 薄客户端与主内核共享依赖）。
a_mcp = Analysis(
    [str(ROOT / "src" / "inkflow" / "mcp" / "__main__.py")],
    pathex=[str(ROOT), str(ROOT / "src")],  # pathex 含 src：mcp 入口解析 inkflow.mcp.server 的前提
    runtime_hooks=[str(_runtime_hook)],
    hiddenimports=hiddenimports
    + _tiktoken_hidden
    + _tiktoken_ext_hidden
    + [
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "sqlalchemy.dialects.sqlite.aiosqlite",  # SQLAlchemy async 引擎动态导入（实测缺失）
        "aiosqlite",  # aiosqlite dialect import_dbapi 运行时 import（实测缺失）
        "chromadb.telemetry.product.posthog",  # #253 rc3 vector reindex 打包缺模块（RAG 进包补充）
        "inkflow.mcp.server",  # #424: MCP stdio 入口显式依赖，防未来收窄 collect_all 时漏收集
        "inkflow.mcp.tools",
    ],
    excludes=[
        "onnxruntime",
        "kubernetes",
        "tokenizers",
        "litellm",
        "torch",
        "transformers",
        "sentence_transformers",
    ],
    datas=datas + _tiktoken_datas + _tiktoken_ext_datas,
    binaries=binaries + _tiktoken_binaries + _tiktoken_ext_binaries,
    noarchive=False,
    optimize=0,
)

mcp_pyz = PYZ(a_mcp.pure)

mcp_exe = EXE(
    mcp_pyz,
    a_mcp.scripts,
    [],
    exclude_binaries=True,  # onedir：与主 inkflow 同模式，依赖二进制交由 COLLECT
    name="inkflow-mcp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    console=True,
    disable_windowed_traceback=False,
)

mcp_coll = COLLECT(
    mcp_exe,
    a.binaries,  # 复用主 Analysis 收集结果：MCP 薄客户端与主内核共享依赖
    a.datas,
    strip=False,
    name="inkflow-mcp",
)
