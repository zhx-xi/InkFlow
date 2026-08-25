"""F22/F14 统一索引重建后台任务编排服务（#659）.

承载「全文 FTS5 + 向量 chroma」一起异步重建（scope 可分开 fulltext/vector/both），
后台 fire-and-forget 任务 + 进度状态轮询（前端 #657 按此契约 mock 通过）。
镜像 books.py 后台任务模式：start_rebuild 预校验 → 注册进度 → spawn 后台任务 → 立即返回。

进度状态 DTO（每 task）：{status, step, progress_done, progress_total, rebuilt_at, error}。
progress_total = 项目数；step 标识当前阶段（fulltext/vector）。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.infrastructure.background.tasks import spawn_background_task

_PAGE_SIZE = 50
"""分页枚举全部项目页大小（镜像 SearchService._list_all_projects）。"""


class IndexRebuildService:
    """统一异步索引重建编排（#659）：全文 + 向量一起/分开重建 + 进度轮询.

    全部依赖经构造注入（Keyword-only）：project_repo 校验项目存在；
    fulltext 为全文重建 callable（生产装配 = SearchService.rebuild）；
    vector 为向量重建 callable（None = 未配 embedding，vector/both scope 前置 422）。
    """

    def __init__(
        self,
        *,
        project_repo: ProjectRepositoryProtocol,
        fulltext: Callable[[list[int] | None], Awaitable[None]],
        vector: Callable[[list[int] | None], Awaitable[None]] | None,
    ) -> None:
        self._project_repo = project_repo
        self._fulltext = fulltext
        self._vector = vector
        self._running: set[tuple[int, ...] | None] = set()
        """running 任务的 project 范围集合（None = 全部项目）；用于 409 冲突检测."""
        self._tasks: dict[str, dict[str, Any]] = {}
        """task_id → 进度状态 DTO（status/step/progress/rebuilt_at/error 六字段）."""

    async def start_rebuild(
        self,
        project_ids: list[int] | list[uuid.UUID] | None,
        scope: str = "both",
    ) -> dict:
        """预校验 → 注册进度 → spawn 后台任务 → 返回 {task_id, status: 'running'}.

        预校验顺序（#659 决策）：scope 非法 → ValueError；scope=vector/both 且
        未配 vector → ValueError("未配置 embedding 模型")（→422）；任一 project
        不存在 → ProjectNotFoundError（→404）；相同 project 范围已有 running
        任务 → ValueError("索引重建进行中")（→409）。
        """
        if scope not in ("fulltext", "vector", "both"):
            raise ValueError(f"invalid scope: {scope}")
        if scope in ("vector", "both") and self._vector is None:
            raise ValueError("未配置 embedding 模型")
        resolved: list[int] | None = None
        if project_ids is not None:
            resolved = []
            for pid in project_ids:
                resolved.append(pid.int if isinstance(pid, uuid.UUID) else pid)
            for pid in resolved:
                project = await self._project_repo.get(pid)
                if project is None:
                    raise ProjectNotFoundError(f"Project not found: {pid}")
        else:
            resolved = await self._list_all_project_ids()
        key: tuple[int, ...] | None = tuple(resolved) if resolved else None
        if key in self._running:
            raise ValueError("索引重建进行中")
        self._running.add(key)
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = {
            "status": "running",
            "step": "vector" if scope == "vector" else "fulltext",
            "progress_done": 0,
            "progress_total": len(resolved) if resolved is not None else None,
            "rebuilt_at": None,
            "error": None,
        }
        spawn_background_task(self._run(task_id, project_ids, scope), key=task_id)
        return {"task_id": task_id, "status": "running"}

    async def get_status(self, task_id: str) -> dict | None:
        """查询任务进度状态；未注册 → None（router 映射 404）."""
        return self._tasks.get(task_id)

    async def _run(
        self,
        task_id: str,
        project_ids: list[int] | list[uuid.UUID] | None,
        scope: str,
    ) -> None:
        """后台执行体：按 scope 顺序执行 fulltext → vector，进度分段上报.

        任一步抛异常 → status='failed' + error=str(e)（try/except 包住整个执行体，
        避免 fire-and-forget 异常吞掉）；全部成功 → status='done' + rebuilt_at。
        """
        try:
            resolved: list[int] | None = None
            if project_ids is not None:
                resolved = []
                for pid in project_ids:
                    resolved.append(pid.int if isinstance(pid, uuid.UUID) else pid)
            if scope in ("fulltext", "both"):
                await self._fulltext(resolved)
                self._tasks[task_id].update(
                    {
                        "step": "fulltext",
                        "progress_done": self._tasks[task_id]["progress_total"],
                    }
                )
            if scope in ("vector", "both"):
                if self._vector is None:
                    raise RuntimeError("embedding 模型不可用")  # noqa: TRY301  # 失败即记录 error，不得吞掉
                await self._vector(resolved)
                self._tasks[task_id].update(
                    {
                        "step": "vector",
                        "progress_done": self._tasks[task_id]["progress_total"],
                    }
                )
            self._tasks[task_id].update(
                {
                    "status": "done",
                    "rebuilt_at": datetime.now(UTC).isoformat(),
                }
            )
        except Exception as e:
            self._tasks[task_id].update({"status": "failed", "error": str(e)})
        finally:
            key: tuple[int, ...] | None = (
                tuple(pid.int if isinstance(pid, uuid.UUID) else pid for pid in project_ids)
                if project_ids
                else None
            )
            self._running.discard(key)

    async def _list_all_project_ids(self) -> list[int]:
        """分页枚举全部项目 id（project_ids=None → 全部项目重建）."""
        project_ids: list[int] = []
        offset = 0
        while True:
            batch, total = await self._project_repo.list_all(offset=offset, limit=_PAGE_SIZE)
            project_ids.extend(project.id.int for project in batch)
            offset += len(batch)
            if offset >= total or not batch:
                break
        return project_ids
