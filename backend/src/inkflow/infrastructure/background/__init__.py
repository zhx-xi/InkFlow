"""后台任务基础设施包（F44 阶段4 #456）：共享 fire-and-forget 任务框架。"""

from inkflow.infrastructure.background.tasks import get_background_task, spawn_background_task

__all__ = ["get_background_task", "spawn_background_task"]
