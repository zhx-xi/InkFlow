"""结构化日志配置 — 基于 loguru。"""

import sys

from loguru import logger

from inkflow.core.config import config


def setup_logging() -> None:
    """初始化全局日志配置。"""
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
    logger.add(
        "logs/inkflow_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="1 day",
        retention="30 days",
        compression="gz",
    )
