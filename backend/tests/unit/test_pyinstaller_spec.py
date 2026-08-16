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


def test_spec_filters_stale_dist_info():
    """spec 必须在 Analysis 前清理 site-packages 中非当前版本的 inkflow-*.dist-info
    （#421 复发实证 2026-08-16 rc2：collect_all 过滤是空操作——editable 模式 datas
    不含 dist-info，真凶 = PyInstaller 6.x metadata_required() 自动收集 + uv 缓存
    恢复旧 site-packages 残留 → 双 dist-info → importlib.metadata.version 取排序第一个
    = 旧版本）。

    修复方向（#421 补充）：按 pyproject.toml 当前版本清理 site-packages 残留旧版
    dist-info（不依赖 importlib.metadata 字母序），使 copy_metadata 与
    metadata_required 都只能收集当前版本。"""
    src = _spec_source()
    # ① 必须读 pyproject.toml 版本（白名单基准）
    assert "pyproject.toml" in src, "spec 缺少 pyproject.toml 版本读取（#421 复发）"
    # ② 必须按版本规范化构造目标 dist-info 名（PEP 440：0.9.0-rc2 → 0.9.0rc2）
    assert "inkflow-" in src, "spec 缺少 inkflow dist-info 名构造（#421 复发）"
    # ③ 必须遍历 site-packages glob inkflow-*.dist-info 并删除非当前版本
    assert 'glob("inkflow-*.dist-info")' in src, "spec 缺少 dist-info glob（#421 复发）"
    assert "rmtree" in src, "spec 缺少 dist-info 清理（#421 复发）"
    assert "_target_dist" in src, "spec 缺少当前版本 dist-info 白名单（#421 复发）"
    # ④ 清理必须发生在 Analysis() 之前（Analysis 内部 metadata_required 会自动收集）
    cleanup_pos = src.find("rmtree")
    analysis_pos = src.find("= Analysis(")
    assert cleanup_pos != -1 and analysis_pos != -1, "spec 缺少清理/Analysis（#421 复发）"
    assert cleanup_pos < analysis_pos, "dist-info 清理必须在 Analysis 之前（#421 复发）"
