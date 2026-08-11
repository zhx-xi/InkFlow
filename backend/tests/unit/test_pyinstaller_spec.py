"""inkflow.spec 打包收集清单契约测试（#253 五轮教训固化，2026-08-12）。

背景：rc3→rc7 连续 5 轮打包缺模块（chromadb.telemetry.product.posthog →
tiktoken 编码 → chromadb.api.rust → tiktoken Rust .pyd）——全部是 PyInstaller
收集问题，源码环境（venv 完整依赖）的单元/集成/E2E 全部测不出。本测试把
「关键动态模块必须在 spec 收集清单中」固化为静态契约——收集被误删/回退 → CI 红。

收集语义（2026-08-12 现状）：
- collect_all("chromadb") → datas/binaries/hiddenimports 合并（覆盖 api.rust 等）
- collect_all("tiktoken") + collect_all("tiktoken_ext") → 三件套合并（覆盖 _tiktoken.pyd）
- hiddenimports 显式条目：chromadb.telemetry.product.posthog（#255 补）
"""

import ast
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parents[2] / "pyinstaller" / "inkflow.spec"


def _spec_source() -> str:
    assert SPEC_PATH.exists(), f"spec 不存在: {SPEC_PATH}"
    return SPEC_PATH.read_text(encoding="utf-8")


def test_spec_syntax_ok():
    """spec 必须是合法 Python（构建期执行）。"""
    ast.parse(_spec_source())


def test_spec_collects_chromadb_family():
    """collect_all('chromadb') 必须存在（#253 rc5：api.rust 等动态子包全家桶收集）。"""
    src = _spec_source()
    assert 'collect_all("chromadb")' in src, "缺少 collect_all('chromadb') 全家桶收集（#253）"


def test_spec_collects_tiktoken_family():
    """collect_all('tiktoken') + collect_all('tiktoken_ext') 必须存在（#253 rc6：
    cl100k_base 编码内嵌 _tiktoken.cp3xx.pyd Rust 扩展——collect_data_files 返回 0 文件无效）。"""
    src = _spec_source()
    assert 'collect_all("tiktoken")' in src, "缺少 collect_all('tiktoken')（#253 rc6）"
    assert 'collect_all("tiktoken_ext")' in src, "缺少 collect_all('tiktoken_ext')（#253 rc6）"


def test_spec_hiddenimport_posthog():
    """chromadb.telemetry.product.posthog 显式 hiddenimport（#255：rc3 首个打包缺模块）。"""
    src = _spec_source()
    assert "chromadb.telemetry.product.posthog" in src, "缺少 posthog hiddenimport（#255）"


def test_spec_excludes_not_blocking_chromadb():
    """excludes 不得排除 chromadb 本体（onnxruntime 等云组件排除允许）。"""
    src = _spec_source()
    excludes_block = src.split("excludes=[", 1)[1].split("]", 1)[0] if "excludes=[" in src else ""
    assert '"chromadb"' not in excludes_block, "excludes 排除了 chromadb 本体"
