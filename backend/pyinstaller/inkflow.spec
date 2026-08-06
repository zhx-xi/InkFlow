# -*- mode: python ; coding: utf-8 -*-
# InkFlow 内核 PyInstaller 打包配置（Issue #48，spec f19-packaging §4.2）
#
# 运行（backend 目录下）：
#   uv sync --frozen --extra packaging
#   uv run pyinstaller pyinstaller/inkflow.spec
# 产物：backend/dist/inkflow/inkflow.exe + backend/dist/inkflow/_internal/（onedir）

from PyInstaller.utils.hooks import collect_all, copy_metadata

# collect_all('inkflow')：带上包内全部子模块 + 数据文件（LLM 模板 yaml 等），
# 替代手写 datas 的多数条目。
datas, binaries, hiddenimports = collect_all("inkflow")

# ⚠️ copy_metadata（评审 🔴2）：INKFLOW_READY.version / /health 版本字段经
# importlib.metadata.version("inkflow") 读取，依赖 dist-info；
# PyInstaller 不自动收集 .dist-info，缺失则冻结 exe 抛 PackageNotFoundError。
datas += copy_metadata("inkflow")

a = Analysis(
    ["src/inkflow/__main__.py"],
    pathex=["src"],
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
