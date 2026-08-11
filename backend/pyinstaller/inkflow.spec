# -*- mode: python ; coding: utf-8 -*-
# InkFlow 内核 PyInstaller 打包配置（Issue #48，spec f19-packaging §4.2）
#
# 运行（backend 目录下）：
#   uv sync --frozen --extra packaging
#   uv run pyinstaller pyinstaller/inkflow.spec
# 产物：backend/dist/inkflow/inkflow.exe + backend/dist/inkflow/_internal/（onedir）

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

# PyInstaller 以 spec 文件所在目录为基准解析相对路径——spec 在 pyinstaller/ 子目录，
# 必须用绝对路径锚定 backend 根（实测 pyinstaller/src/... not found）。
# 注：spec 命名空间无 __file__，用 PyInstaller 提供的 SPECPATH（spec 所在目录）。
ROOT = Path(SPECPATH).resolve().parent  # backend/

# collect_all('inkflow')：带上包内全部子模块 + 数据文件（LLM 模板 yaml 等），
# 替代手写 datas 的多数条目。
datas, binaries, hiddenimports = collect_all("inkflow")

# ⚠️ copy_metadata（评审 🔴2）：INKFLOW_READY.version / /health 版本字段经
# importlib.metadata.version("inkflow") 读取，依赖 dist-info；
# PyInstaller 不自动收集 .dist-info，缺失则冻结 exe 抛 PackageNotFoundError。
datas += copy_metadata("inkflow")

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
    datas=datas,
    binaries=binaries,
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
