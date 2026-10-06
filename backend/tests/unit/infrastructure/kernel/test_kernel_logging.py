"""#1477：内核日志自管理 —— 分片路径 + 运行期轮转 + uvicorn 桥接。

背景（issue #1477 实测）：`%TEMP%\\inkflow-kernel.log` 由存活内核以**继承句柄**持有
（Python `open()` 不带 `FILE_SHARE_DELETE`）⇒ Windows `MoveFileEx` / `os.replace` 必然
`WinError 32` ⇒ **任何进程（含内核自己）都无法重命名该文件** ⇒ #1380 的「启动期归档」
在长驻内核场景永远不触发（实测 246.2MB 且目录下无任何归档）。

修复（ADR-064 / spec f30-kernel §6.2·§6.3）：
  - 日志文件按 kind + data_dir **分片**，由**内核自己持有句柄**；
  - 落点由 `core.log.setup_logging` 的**内核分支**装配（`serve` 只设
    `INKFLOW_KERNEL_LOG_FILE` 标记路径）——`setup_logging` 开头 `logger.remove()`
    会清空一切 handler，提前装 sink 会被清掉（实测分片文件只记到 uvicorn 前两行）；
  - 内核分支**不加 stderr sink**：stderr 已被 `_spawn_kernel` 重定向到引导日志，
    全量日志再灌进去正是 #1477 的膨胀根因；
  - uvicorn（stdlib logging，`propagate=False` 不走 root 拦截桥）经
    `uvicorn_log_config` 换 handler 到 `LoguruHandler`。

RED 契约：
1. **运行期轮转**：不重启进程，写超阈即产生归档且主文件被裁剪到阈值附近；
2. 保留策略：`retention` 表达「超出 10 份 **或** 超过 30 天即清」（含纯逻辑边界）；
3. uvicorn 的 default（error）/ access handler 都指向 Loguru 桥；
4. 日志基建失败**不得阻塞内核启动**（静默降级）。

⚠️ 全部走 ``tmp_path``，绝不碰真实 %TEMP% / backend/logs。
⚠️ 阈值用 monkeypatch 压到字节级（常量须在**调用时**读取）——避免测试写 10MB。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from loguru import logger

from inkflow.core.log import setup_logging
from inkflow.infrastructure.kernel import kernel_logging

KERNEL_LOG_FILE_ENV = "INKFLOW_KERNEL_LOG_FILE"


def _log_file(tmp_path: Path) -> Path:
    """模拟分片后的内核日志路径（spec §6.2：inkflow-kernel-<kind>-<hash>.log）。"""
    return tmp_path / "inkflow-kernel-dev-abc12345.log"


def _archives(tmp_path: Path, log_file: Path) -> list[Path]:
    return [p for p in tmp_path.iterdir() if p.is_file() and p != log_file]


@pytest.fixture(autouse=True)
def _isolate_loguru():
    """隔离全局 Loguru：`setup_logging` 会 `logger.remove()` 清空全部 handler。"""
    yield
    logger.remove()
    logger.add(sys.stderr)  # 还原默认 sink，避免污染后续测试


def test_kernel_branch_rotates_at_runtime_without_restart(tmp_path, monkeypatch):
    """核心契约：**运行期**（不重启）写超阈 → 产生归档 + 主文件被裁剪。"""
    monkeypatch.setattr(kernel_logging, "KERNEL_LOG_ROTATION", 4000)
    log_file = _log_file(tmp_path)
    monkeypatch.setenv(KERNEL_LOG_FILE_ENV, str(log_file))

    setup_logging(log_dir=tmp_path / "app-logs")
    for _ in range(200):
        logger.info("x" * 200)

    assert log_file.exists(), "轮转 = 归档 + 重开，主文件必须仍在"
    assert log_file.stat().st_size < 4000 * 2, f"主文件未被裁剪：{log_file.stat().st_size} 字节"
    assert _archives(tmp_path, log_file), "运行期必须已产生归档文件（无需重启）"


def test_kernel_branch_retention_keeps_recent_files_or_recent_days(tmp_path, monkeypatch):
    """保留策略：超出 N 份 **或** 超过 M 天即清（总量有界）。"""
    monkeypatch.setattr(kernel_logging, "KERNEL_LOG_ROTATION", 2000)
    monkeypatch.setattr(kernel_logging, "KERNEL_LOG_RETENTION_FILES", 3)
    log_file = _log_file(tmp_path)
    monkeypatch.setenv(KERNEL_LOG_FILE_ENV, str(log_file))

    setup_logging(log_dir=tmp_path / "app-logs")
    for _ in range(400):
        logger.info("y" * 200)

    files = [p for p in tmp_path.iterdir() if p.is_file()]
    assert len(files) <= kernel_logging.KERNEL_LOG_RETENTION_FILES + 1, (
        f"保留份数超限：{len(files)} 个文件 —— 归档未被 retention 清理"
    )


def test_paths_to_delete_applies_both_limits(tmp_path):
    """纯逻辑：份数上限 **或** 天数上限，先到先清。

    ⚠️ Loguru 的 callable retention 忽略返回值（回调自行删除）——故「哪些该删」这层
    逻辑必须能**独立**断言，否则误删 / 漏删只能靠端到端文件数间接观察。
    """
    import os
    import time

    now = time.time()
    paths: list[str] = []
    for index in range(15):  # 15 份、跨度 60 天
        path = tmp_path / f"k.{index:02d}.log"
        path.write_text("x", encoding="utf-8")
        age_days = 60 - index * 4  # index=0 → 60 天前（最老）；index=14 → 4 天前
        stamp = now - age_days * 86400
        os.utime(path, (stamp, stamp))
        paths.append(str(path))

    to_delete = {Path(p).name for p in kernel_logging.paths_to_delete(paths)}

    # 超出最近 10 份的是 k.00..k.04（5 个）
    assert {"k.00.log", "k.01.log", "k.02.log", "k.03.log", "k.04.log"} <= to_delete
    # 最近 10 份里超过 30 天的是 k.05/k.06/k.07（40/36/32 天）
    assert {"k.05.log", "k.06.log", "k.07.log"} <= to_delete
    # 30 天内且在前 10 份的必须留下
    assert "k.14.log" not in to_delete
    assert "k.10.log" not in to_delete


def test_stdlib_logging_bridge_routes_into_log_file(tmp_path):
    """stdlib logging（uvicorn 的 access/error）必须能桥接进日志文件。

    不桥接的话它们走 stderr ⇒ 被 `_spawn_kernel` 重定向进**引导日志**、绕过轮转（#1477 白修）。
    """
    log_file = _log_file(tmp_path)
    handler_id = logger.add(str(log_file), encoding="utf-8")
    stdlib_logger = logging.getLogger("uvicorn.access")
    saved_handlers, saved_propagate = stdlib_logger.handlers, stdlib_logger.propagate
    stdlib_logger.handlers, stdlib_logger.propagate = [kernel_logging.LoguruHandler()], False
    try:
        stdlib_logger.warning("uvicorn-access-1477")
    finally:
        stdlib_logger.handlers, stdlib_logger.propagate = saved_handlers, saved_propagate
        logger.remove(handler_id)

    assert "uvicorn-access-1477" in log_file.read_text(encoding="utf-8")


def test_uvicorn_log_config_routes_both_handlers_to_bridge():
    """uvicorn 的 default（error）与 access handler 都必须指向 Loguru 桥，且级别随参数。"""
    config = kernel_logging.uvicorn_log_config(level="debug")
    bridge = "inkflow.infrastructure.kernel.kernel_logging.LoguruHandler"

    assert config["handlers"]["default"]["class"] == bridge
    assert config["handlers"]["access"]["class"] == bridge
    assert config["loggers"]["uvicorn"]["level"] == "DEBUG"
    assert config["loggers"]["uvicorn.access"]["level"] == "DEBUG"
    assert config["loggers"]["uvicorn.access"]["propagate"] is False


def test_kernel_branch_sink_failure_does_not_block_kernel(tmp_path, monkeypatch):
    """日志基建失败**不得阻塞内核启动**（spec §7 行 13）：装配失败 → 静默、不抛。"""
    log_file = _log_file(tmp_path)
    monkeypatch.setenv(KERNEL_LOG_FILE_ENV, str(log_file))

    real_add = logger.add
    calls = {"count": 0}

    def _flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:  # 内核 sink 是 setup_logging 内核分支的第一次 add
            raise OSError("日志目录不可写")
        return real_add(*args, **kwargs)

    monkeypatch.setattr(logger, "add", _flaky)

    setup_logging(log_dir=tmp_path / "app-logs")  # 不抛即通过

    logger.info("内核照常运行")  # 其余 sink 仍可用
