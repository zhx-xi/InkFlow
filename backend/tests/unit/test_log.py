"""Issue #11 — 日志文件路径基于相对 cwd 的 bug 回归测试.

bug 表现：``setup_logging`` 用相对路径 ``logs/inkflow_...`` 添加 loguru 文件
sink，日志落点随进程 cwd 漂移（可能在 backend/logs/ 或 backend/src/logs/）。
修复后：文件 sink 使用基于包根解析的绝对路径，稳定落在 backend/logs/。
"""

import sys
from pathlib import Path

import pytest
from loguru import logger

from inkflow.core import log as log_module

# 测试文件 backend/tests/unit/test_log.py → parents[2] = backend 根目录
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_EXPECTED_LOG_DIR = _BACKEND_ROOT / "logs"


@pytest.fixture(autouse=True)
def _isolate_loguru():
    """每个测试后移除 loguru 全部 handler 并恢复默认 stderr handler，避免污染其他测试。"""
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")


def _created_log_files(directory: Path) -> set[Path]:
    """directory 下现有的 inkflow 日志文件集合。"""
    if not directory.exists():
        return set()
    return {p for p in directory.glob("inkflow_*.log")}


def test_resolve_log_dir_is_absolute_and_package_based(monkeypatch, tmp_path):
    """解析出的日志目录是绝对路径且基于包根（backend/logs），与 cwd 无关。"""
    monkeypatch.chdir(tmp_path)  # 模拟从任意 cwd 启动

    log_dir = log_module.resolve_log_dir()

    assert isinstance(log_dir, Path)
    assert log_dir.is_absolute()
    assert log_dir == _EXPECTED_LOG_DIR


def test_setup_logging_creates_log_in_resolved_dir_from_other_cwd(monkeypatch, tmp_path):
    """从非 backend 的 cwd 调用 setup_logging，文件落在解析出的日志目录（与 cwd 无关）。

    隔离说明（Phase 1 Gate 评审 2026-08-01）：不触碰真实 backend/logs——
    真实环境跑过 serve 后该目录已有当日日志文件，`after - before` 恒为空导致
    测试误报。此处 monkeypatch resolve_log_dir 指向 tmp_path，保留
    "cwd 无关 + 使用解析路径"的测试意图。
    """
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(log_module, "resolve_log_dir", lambda: log_dir)
    before = _created_log_files(log_dir)

    monkeypatch.chdir(tmp_path)
    log_module.setup_logging()
    logger.info("issue-11-trigger")  # 强制文件 sink 落盘

    created = _created_log_files(log_dir) - before
    try:
        assert created, f"解析出的日志目录下未创建日志文件（log_dir={log_dir}）"
    finally:
        logger.remove()  # 先关闭文件句柄，Windows 下才能删除文件
        for p in created:
            p.unlink(missing_ok=True)


def test_setup_logging_accepts_custom_log_dir(monkeypatch, tmp_path):
    """setup_logging(log_dir=...) 将日志写入指定的绝对目录（与 cwd 无关）。"""
    custom_dir = tmp_path / "custom-logs"
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    log_module.setup_logging(log_dir=custom_dir)
    logger.info("issue-11-custom-dir")

    created = _created_log_files(custom_dir)
    try:
        assert created, f"自定义日志目录下未创建日志文件（log_dir={custom_dir}）"
    finally:
        logger.remove()
        for p in created:
            p.unlink(missing_ok=True)


# ---- F51 debug-mode：日志目录 frozen 分支 + console 级别 debug 提升 ----
def test_resolve_log_dir_frozen_uses_config_data_dir(monkeypatch, tmp_path):
    """F51-frozen：打包模式（sys.frozen=True）→ 日志目录 = config.data_dir/logs。

    RED 阶段 resolve_log_dir 无 frozen 分支 → 仍返回 backend/logs → 断言 FAIL
    （GREEN 义务：`if getattr(sys, "frozen", False): return config.data_dir / "logs"`）。
    """
    import importlib

    # config 是模块级单例：import inkflow.core.config as cfg_mod 会绑定到实例
    # （memory 已知坑），须 importlib 取真模块再 patch 单例实例属性
    cfg_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg_mod.config, "data_dir", tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    result = log_module.resolve_log_dir()

    assert result == tmp_path / "logs"


def test_resolve_log_dir_dev_keeps_backend_logs(monkeypatch):
    """F51-dev 守护：非 frozen → 保持 backend/logs 不变（防 frozen 分支破坏 dev 行为）。"""
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    result = log_module.resolve_log_dir()

    assert result == _EXPECTED_LOG_DIR


def test_setup_logging_debug_forces_console_debug(monkeypatch, tmp_path):
    """F51-debug：config.debug=True → console/stderr sink 提升为 DEBUG（levelno=10）。

    RED 阶段 config 单例无 debug 字段 → monkeypatch.setattr 抛 AttributeError
    （字段缺失信号；GREEN 义务：新增 debug 字段 + console sink level 改
    "DEBUG" if config.debug else config.log_level）。
    """
    import importlib

    cfg_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg_mod.config, "debug", True)  # RED 字段缺失即 AttributeError
    monkeypatch.setattr(cfg_mod.config, "log_level", "INFO")
    monkeypatch.setattr(log_module, "resolve_log_dir", lambda: tmp_path / "logs")

    log_module.setup_logging()

    handlers = list(logger._core.handlers.values())
    assert handlers[0].levelno == 10  # loguru DEBUG = 10


# ---- S3f-T1（#869，contract-s3f-t1.md §2.4）：frozen + APPDATA 端到端组合链 ----
def test_resolve_log_dir_frozen_appdata_chain(monkeypatch, tmp_path):
    """S3f-T1-端到端：frozen + APPDATA + 空 instance.env 锚点 → 真重建 InkFlowConfig()
    实例 data_dir == <APPDATA>/InkFlow → resolve_log_dir == <APPDATA>/InkFlow/logs。

    contract §2.4 #1：frozen 分支已实现（§1.4 无实现改动），本用例补「frozen +
    APPDATA → %APPDATA%/InkFlow/logs」端到端组合链——逐段真走 config 解析
    （env INKFLOW_DATA_DIR 清空 + instance.env 锚点指向不存在路径 + sys.frozen=True +
    APPDATA=tmp_path），非 setattr data_dir 捷径。resolve_log_dir 读 log 模块级
    config 绑定（log.py `from inkflow.core.config import config`）→ 须 patch
    log_module.config 为重建实例（端到端语义）。
    """
    import importlib

    from inkflow.core.config import InkFlowConfig

    cfg_mod = importlib.import_module("inkflow.core.config")
    # instance.env 锚点指向不存在路径（复用 test_config_instance_env _patch_anchor 手法）
    monkeypatch.setattr(
        cfg_mod,
        "get_instance_env_path",
        lambda: tmp_path / "InkFlow" / "instance.env",
        raising=False,
    )
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    monkeypatch.delenv("INKFLOW_DEBUG", raising=False)

    rebuilt = InkFlowConfig()  # 端到端链：真重建实例（走 _default_data_dir 解析）
    monkeypatch.setattr(log_module, "config", rebuilt)

    assert rebuilt.data_dir == tmp_path / "InkFlow"
    assert log_module.resolve_log_dir() == tmp_path / "InkFlow" / "logs"


def test_setup_logging_frozen_writes_under_appdata_logs(monkeypatch, tmp_path):
    """S3f-T1-端到端写盘：同上前提 + setup_logging()（不传 log_dir）→ 日志落在
    <APPDATA>/InkFlow/logs 且文件内容含该条（contract §2.4 #2）。

    frozen 分支 resolve_log_dir → config.data_dir/logs；log_module.config patch 为
    重建实例后，setup_logging 的文件 sink 才落到 tmp_path 下（防写真实 backend/logs）。
    """
    import importlib

    from inkflow.core.config import InkFlowConfig

    cfg_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(
        cfg_mod,
        "get_instance_env_path",
        lambda: tmp_path / "InkFlow" / "instance.env",
        raising=False,
    )
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    monkeypatch.delenv("INKFLOW_DEBUG", raising=False)

    rebuilt = InkFlowConfig()
    monkeypatch.setattr(log_module, "config", rebuilt)

    marker = "s3f-t1-frozen-appdata-chain"
    log_module.setup_logging()
    logger.info(marker)

    log_dir = tmp_path / "InkFlow" / "logs"
    files = list(log_dir.glob("inkflow_*.log"))
    assert files, f"frozen+APPDATA 组合链下日志未落在 {log_dir}"
    contents = "\n".join(p.read_text(encoding="utf-8") for p in files)
    assert marker in contents, f"日志文件内容缺少 marker（{files}）"
