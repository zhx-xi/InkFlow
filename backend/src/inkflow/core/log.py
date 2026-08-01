"""结构化日志配置 — 基于 loguru。"""

import sys
from pathlib import Path

from loguru import logger

from inkflow.core.config import config


def resolve_log_dir() -> Path:
    """解析日志目录为绝对路径 — 基于包根（backend/logs），与运行时 cwd 无关。

    bug 背景（Issue #11）：文件 sink 使用相对路径 ``logs/...`` 时，日志落点
    随进程 cwd 漂移。此处从模块文件位置向上定位 backend 根目录，保证稳定。
    """
    # backend/src/inkflow/core/log.py → parents[3] = backend 根目录
    backend_root = Path(__file__).resolve().parents[3]
    return backend_root / "logs"


def setup_logging(log_dir: Path | None = None) -> None:
    """初始化全局日志配置。

    Args:
        log_dir: 日志目录（绝对路径）。默认基于包根解析为 backend/logs，
            避免相对路径导致日志落点随进程 cwd 漂移（Issue #11）。
    """
    logger.remove()  # 移除默认 handler
    logger.add(
        sys.stderr,
        level=config.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
            "| <level>{level: <8}</level> "
            "| <cyan>{name}</cyan>:<cyan>{line}</cyan> "
            "- <level>{message}</level>"
        ),
        colorize=True,
    )
    target_dir = log_dir if log_dir is not None else resolve_log_dir()
    logger.add(
        target_dir / "inkflow_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="1 day",
        retention="30 days",
        compression="gz",
    )
