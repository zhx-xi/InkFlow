"""F48 知识图谱定时提取调度器 — 进程内 asyncio loop（#479 G1 交付）.

覆盖 spec f48-knowledge-graph §5.5.3 + §5.5.8:
- run_cycle: disabled 跳过 / enabled 逐项目执行 / 单项目异常不中断 / 每周期重读设置
- startup 补跑: extraction_run_repo=None 或无 run 记录 → 首启立即 run_cycle；
  有近期 run 记录 → 等待；距今 >= interval_hours → 立即补跑
- stop 幂等 + 后台任务不泄漏（F44 RED 陷阱）
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any


class KnowledgeExtractScheduler:
    """知识图谱定时提取调度器.

    Args:
        settings_service: get_settings() → 含 kg_extract_* 三属性的设置对象.
        project_repository: list_all() → 项目列表（只读 id）.
        relation_extraction_service: extract_for_project(project_id, method=...) 服务.
        extraction_run_repo: 可选；list(...) → (runs, total)，runs 按 run_at DESC.

    #479 G2 回补（status 端点支撑属性，spec §5.5.6）:
    - is_running: run_cycle 执行期间为 True，否则 False.
    - last_run: 最近一次 knowledge_relation run 摘要 {status, created, run_at}；无则 None.
    """

    def __init__(
        self,
        *,
        settings_service: object,
        project_repository: object,
        relation_extraction_service: object,
        extraction_run_repo: object | None = None,
    ) -> None:
        self._settings_service = settings_service
        self._project_repository = project_repository
        self._relation_extraction_service = relation_extraction_service
        self._extraction_run_repo = extraction_run_repo
        self._task: asyncio.Task | None = None
        self._is_running = False
        self._last_run: dict[str, Any] | None = None

    @property
    def is_running(self) -> bool:
        """run_cycle 是否正在执行（status 端点支撑属性，spec §5.5.6）。"""
        return self._is_running

    @property
    def last_run(self) -> dict[str, Any] | None:
        """最近一次 knowledge_relation run 摘要（无则 None，spec §5.5.6）。"""
        return self._last_run

    async def start(self) -> None:
        """spawn 常驻 loop task（F42 create_task 先例）；启动即执行补跑判定."""

        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """取消 loop task 并等待；幂等（未 start / 重复 stop 均合法）.

        #479 G2: 后台任务若已带异常结束，await 会复抛——shutdown 统一吞掉
        （lifespan 关闭不得因后台任务失败而崩）。
        """

        task = self._task
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task
        self._task = None

    async def run_cycle(self) -> list[dict[str, Any]]:
        """单周期执行体: 读设置 → 逐项目提取 → 汇总结果 dict 列表.

        执行期间 is_running=True，每项结束后维护 last_run 摘要（status 端点支撑，
        spec §5.5.6）；try/finally 保证异常时也释放 is_running。
        """

        self._is_running = True
        try:
            settings = await self._settings_service.get_settings()  # type: ignore[attr-defined]  # 鸭子类型：settings 按契约提供 get_settings
            if settings.kg_extract_enabled is False:
                return []
            projects = await self._project_repository.list_all()  # type: ignore[attr-defined]  # 鸭子类型：project_repository 按契约提供 list_all
            items: list[dict[str, Any]] = []
            for project in projects:
                try:
                    result = await self._relation_extraction_service.extract_for_project(  # type: ignore[attr-defined]  # 鸭子类型：提取服务按契约提供 extract_for_project
                        project.id, method=settings.kg_extract_method
                    )
                except Exception:
                    items.append({"project_id": project.id, "status": "error", "created": 0})
                else:
                    items.append(
                        {
                            "project_id": project.id,
                            "status": "success",
                            "created": result.created,
                        }
                    )
            if items:
                last = items[-1]
                self._last_run = {
                    "status": last["status"],
                    "created": last["created"],
                    "run_at": datetime.now(UTC).isoformat(),
                }
            return items
        finally:
            self._is_running = False

    async def _run(self) -> None:
        """后台常驻任务: startup 补跑判定 → 周期循环（interval 每周期重读）."""

        should_catch_up = True
        if self._extraction_run_repo is not None:
            runs, _total = await self._extraction_run_repo.list()  # type: ignore[attr-defined]  # 鸭子类型：run repo 按契约提供 list
            if runs:
                latest = runs[0].run_at
                settings = await self._settings_service.get_settings()  # type: ignore[attr-defined]  # 鸭子类型：settings 按契约提供 get_settings
                interval_hours = settings.kg_extract_interval_hours
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=UTC)
                age = datetime.now(UTC) - latest
                if age < timedelta(hours=interval_hours):
                    should_catch_up = False
        if should_catch_up:
            await self.run_cycle()
        while True:
            settings = await self._settings_service.get_settings()  # type: ignore[attr-defined]  # 鸭子类型：settings 按契约提供 get_settings
            interval_hours = settings.kg_extract_interval_hours
            await asyncio.sleep(interval_hours * 3600)
            await self.run_cycle()
