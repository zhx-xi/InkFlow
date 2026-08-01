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


def test_setup_logging_creates_log_in_backend_logs_from_other_cwd(monkeypatch, tmp_path):
    """从非 backend 的 cwd 调用 setup_logging，日志文件稳定落在 backend/logs/ 下。"""
    before = _created_log_files(_EXPECTED_LOG_DIR)

    monkeypatch.chdir(tmp_path)
    log_module.setup_logging()
    logger.info("issue-11-trigger")  # 强制文件 sink 落盘

    created = _created_log_files(_EXPECTED_LOG_DIR) - before
    try:
        assert created, f"backend/logs 下未创建日志文件（cwd={tmp_path}）"
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
