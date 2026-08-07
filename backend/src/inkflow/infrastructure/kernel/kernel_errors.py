"""内核冷启动错误类型。"""

from __future__ import annotations


class KernelStartupError(Exception):
    """内核冷启动失败（超时 / 秒退 / spawn 命令缺失 / 状态未就绪）。"""
