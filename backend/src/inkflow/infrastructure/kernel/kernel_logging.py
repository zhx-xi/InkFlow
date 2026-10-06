"""内核日志自管理 sink（#1477 / ADR-064 / spec f30-kernel §6.3）。

🔴 为什么必须由**内核自己**持有日志文件句柄：

Windows `MoveFileEx` / `os.replace` 要求目标文件**所有**句柄都带 `FILE_SHARE_DELETE`，
而 `Popen(stdout=…)` 继承的句柄没有它（Python `open()` 默认不含该标志）⇒ **任何进程
（含内核自己）都无法重命名该文件**（实测 `WinError 32`，见 issue #1477 实测矩阵）⇒
#1380 的「启动期归档」在长驻内核期间**永不触发**（实测 246.2MB 且目录下无任何归档）。

改为由本模块 ``logger.add(...)`` **自己 open** 日志文件 ⇒ 库的 `rotation` 在内部完成
close → rename → reopen，Windows 可行。
"""

from __future__ import annotations

import copy
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType
from typing import Any

from loguru import logger

#: 单文件轮转阈值（Loguru `rotation`；str 支持 `"10 MB"`，测试可 monkeypatch 成字节数）
KERNEL_LOG_ROTATION: str | int = "10 MB"
#: 保留份数上限（与保留天数**同时生效**：超出任一只上限即清理）
KERNEL_LOG_RETENTION_FILES = 10
#: 保留天数上限
KERNEL_LOG_RETENTION_DAYS = 30


def paths_to_delete(paths: list[str]) -> list[str]:
    """纯函数：按两个上限算出**待删**路径（最多 10 份 / 最老不超 30 天，先到先清）。

    ⚠️ Loguru 0.7.3 的 callable `retention` 收到的是 ``list[str]``（路径字符串，按时间升序），
    **不是** `FileDate` 对象；也不接受 ``"10 files"`` 或 list 形态的 `retention`
    （实测 `ValueError` / `TypeError`）——故「两个上限」只能走 callable 扩展点。

    常量在**调用时**读取（模块属性），便于测试压到小份数 / 字节级。
    """
    if not paths:
        return []
    cutoff = datetime.now(UTC) - timedelta(days=KERNEL_LOG_RETENTION_DAYS)
    recent = set(paths[-KERNEL_LOG_RETENTION_FILES:])
    to_delete: list[str] = []
    for path in paths:
        if path not in recent:  # 超出份数上限
            to_delete.append(path)
            continue
        try:
            modified = datetime.fromtimestamp(Path(path).stat().st_mtime, tz=UTC)
        except OSError:
            continue  # 读不到时间 → 保守不清（宁多留、不误删）
        if modified < cutoff:  # 超出保留天数上限
            to_delete.append(path)
    return to_delete


def retention_policy(paths: list[str]) -> None:
    """Loguru `retention` 回调：按两个上限**自行删除**过期归档。

    🔴 Loguru 0.7.3 的 callable retention **忽略回调返回值**（`_file_sink.py`
    ``_terminate_file`` 只做 `self._retention_function(list(logs))`），内置的 int / timedelta
    分支同样是自行 `unlink` —— 故回调必须自己删，返回列表没有意义。
    """
    for path in paths_to_delete(paths):
        with suppress(OSError):
            Path(path).unlink()


class LoguruHandler(logging.Handler):
    """stdlib `logging` → Loguru 桥。

    内核的运行期日志**主要来自 uvicorn**（stdlib logging）。不桥接的话它们走 stderr ⇒
    被 `_spawn_kernel` 重定向进**引导日志**，绕过本模块的轮转（等于 #1477 没修）。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:  # 自定义级别名 → 回退数值级别
            level = record.levelno
        frame: FrameType | None = logging.currentframe()
        depth = 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def uvicorn_log_config(*, level: str) -> dict[str, Any]:
    """uvicorn 的 `log_config`：default/access handler 换成 Loguru 桥。

    在 uvicorn 文档的默认 dictConfig 上改，避免自己维护一份完整配置（漂移风险）。
    """
    from uvicorn.config import LOGGING_CONFIG

    config: dict[str, Any] = copy.deepcopy(LOGGING_CONFIG)
    handler_class = "inkflow.infrastructure.kernel.kernel_logging.LoguruHandler"
    config["handlers"]["default"] = {"class": handler_class}
    config["handlers"]["access"] = {"class": handler_class}
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        config["loggers"][name]["level"] = level.upper()
    return config
