"""BookService 后台运行辅助混入（#456）：prepare_run / mark_failed；F49 自主编排入口.

拆文件动机：book_service.py 触 monster file ban（>900 行，check_file_length 门禁）——
prepare_run/mark_failed 为后台任务改造（#456）新增的预校验/异常兜底方法，逻辑自洽
可独立成 mixin（与 BookService 强耦合，调用其私有方法；write_book_agentic（F49 #551）
同为服务装配层新增，镜像 write_book_volume 校验 + BookAgenticPipeline 委托，一并归入；
不改类契约：
BookService(BookRunMixin) 后 prepare_run/mark_failed 仍为实例方法，既有测试零改动）。

依据: specs/f44-book-orchestrator/spec.md §3/§13.4（#456 FastAPI 后台任务）.
    specs/f27-writer-agent/spec.md §5.4（BookService 装配）.
"""

from __future__ import annotations

import uuid

from inkflow.domain.models.agent_book import AgenticBookConfig
from inkflow.domain.models.writing_plan import BookLimits


class BookRunMixin:
    """书级运行后台任务辅助（预校验 + 异常兜底），供 BookService 混入。"""

    async def prepare_run(
        self,
        plan_id: uuid.UUID,
        limits: BookLimits | None = None,
        mode: str = "static",
    ) -> dict:
        """启动前预校验（endpoint 内 await，错误立即 4xx/409/422）+ running 落库（#456）.

        与 write_book/write_book_volume 前置校验一致（计划存在 / 至少一道护栏 /
        「内容已写」安全阀），不执行任何章委托——供 POST /runs 预校验后启后台任务；
        无章节点 → completed 快路径（不启任务）；plan.status=="running" → ValueError.

        Args:
            plan_id: 计划 UUID（run 载体 = WritingPlan）.
            limits: 请求显式上限；None = 回退项目级 extra / 默认常量.
            mode: "static"（顺序派发）/ "volume"（卷级编排）/ "agentic"（自主编排）.

        Returns:
            {"run_id": str(plan.id), "status": "running"} 或
            {"run_id": str(plan.id), "status": "completed"}（无章快路径）.

        Raises:
            ValueError: 计划不存在 / 上限全无 / 运行已在进行中.
            ChapterAlreadyWrittenError: 任一目标章已有内容或执行已完成.
        """
        # 函数体 import：避免与 book_service 模块级循环依赖（错误类定义于彼）
        from inkflow.domain.services.book_service import ChapterAlreadyWrittenError

        plan = await self._repo.get_writing_plan(  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            plan_id
        )
        if plan is None:
            raise ValueError("计划不存在")
        if plan.status == "running":
            raise ValueError("运行已在进行中")
        merged = await self._resolve_merged_limits(plan, limits)  # type: ignore[attr-defined]  # 混入类：方法由 BookService 提供
        # 生效上限写回 plan.limits（M5：book status 显示真实配置；不覆盖 tokens_* 运行计数）
        for _field in ("max_chapters", "max_agent_calls", "max_tokens", "max_sessions"):
            plan.limits[_field] = getattr(merged, _field)
        if mode == "volume":
            volumes = await self._find_volumes(plan)  # type: ignore[attr-defined]  # 混入类：方法由 BookService 提供
            for volume in volumes:
                for chapter in volume["chapters"]:
                    if await self._check_chapter_written(plan, chapter):  # type: ignore[attr-defined]  # 混入类：方法由 BookService 提供
                        raise ChapterAlreadyWrittenError("该章已有内容，拒绝重跑")
            has_targets = bool(volumes)
        elif mode == "agentic":
            await self._check_agentic_authorized(plan)
            chapters = await self._find_chapters(plan)  # type: ignore[attr-defined]  # 混入类：方法由 BookService 提供
            for chapter in chapters:
                if await self._check_content_written(plan, chapter):  # type: ignore[attr-defined]  # 混入类：方法由 BookService 提供
                    raise ChapterAlreadyWrittenError("该章已有内容，拒绝重跑")
            # 镜像 volume 分支「书级 run 隐式目标 = 整本书」语义：预校验通过即 running
            # 落库（RED 契约 test_prepare_run_mode_agentic 期望 running；无章 completion
            # 由 write_book_agentic → pipeline 空章路径兜底）
            has_targets = True
        else:
            chapters = await self._find_chapters(plan)  # type: ignore[attr-defined]  # 混入类：方法由 BookService 提供
            for chapter in chapters:
                if await self._check_content_written(plan, chapter):  # type: ignore[attr-defined]  # 混入类：方法由 BookService 提供
                    raise ChapterAlreadyWrittenError("该章已有内容，拒绝重跑")
            has_targets = bool(chapters)
        if not has_targets:
            plan.status = "completed"
            await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
                plan
            )
            return {"run_id": str(plan.id), "status": "completed"}
        plan.status = "running"
        await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            plan
        )
        return {"run_id": str(plan.id), "status": "running"}

    async def _check_agentic_authorized(self, plan) -> None:
        """#598 全自动授权门禁：config 明确存在且 auto_write_enabled=False → 拒绝。
        config 不存在（None）或 auto_write_enabled=True → 放行（向后兼容 CLI/旧路径）。"""
        if self._project_config_getter is None:  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            return
        config = await self._project_config_getter(plan.project_id)  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
        if config is not None and getattr(config, "auto_write_enabled", False) is False:
            raise ValueError("全自动写作未授权，请先在执行详情旁开启「是否全自动」开关")

    async def mark_failed(self, run_id: str) -> dict:
        """后台任务异常兜底：运行标记 failed 落库（#456 状态映射 running → failed）.

        Args:
            run_id: 书级运行 id（= WritingPlan.id 字符串）.

        Returns:
            {"run_id": run_id, "status": "failed"}.

        Raises:
            ValueError: 运行不存在.
        """
        plan = await self._repo.get_writing_plan(  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            run_id
        )
        if plan is None:
            raise ValueError("运行不存在")
        plan.status = "failed"
        await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            plan
        )
        return {"run_id": run_id, "status": "failed"}

    async def write_book_agentic(
        self,
        plan_id: uuid.UUID,
        limits: BookLimits | None = None,
        config: AgenticBookConfig | None = None,
    ) -> dict[str, str]:
        """book-level 自主编排入口（F49 #551，spec §5.4）：校验 → 安全阀 → 委托 execute.

        limits 解析链复用 F44（_resolve_merged_limits → 生效上限写回 plan.limits）；
        章节点 = _find_chapters（level=chapter，sort_order 升序）；「内容已写」安全阀
        先于一切执行（任一章命中 → ChapterAlreadyWrittenError，pipeline 零调用）；
        thread_id = str(plan.id)（书级运行 ↔ 图 checkpoint 一一映射，F44 阶段 4 语义），
        execute 返回后按 result.status 写回 plan.status + thread_id 落库。

        Args:
            plan_id: 计划 UUID（run 载体 = WritingPlan）.
            limits: 请求显式上限；None = 回退项目级 extra / 默认常量.
            config: agentic 模式配置（AgenticBookConfig）；None = 默认配置.

        Returns:
            {"run_id": str(plan.id), "status": plan.status}.

        Raises:
            ValueError: 计划不存在；或 agentic_pipeline 未配置（防静默降级）.
            ChapterAlreadyWrittenError: 任一目标章已有内容或执行已完成.
        """
        # 函数体 import：避免与 book_service 模块级循环依赖（错误类定义于彼）
        from inkflow.domain.services.book_service import ChapterAlreadyWrittenError

        plan = await self._repo.get_writing_plan(  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            plan_id
        )
        if plan is None:
            raise ValueError("计划不存在")
        if self._agentic_pipeline is None:  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            raise ValueError("agentic_pipeline 未配置")
        merged = await self._resolve_merged_limits(plan, limits)  # type: ignore[attr-defined]  # 混入类：方法由 BookService 提供
        chapters = await self._find_chapters(plan)  # type: ignore[attr-defined]  # 混入类：方法由 BookService 提供
        for chapter in chapters:
            if await self._check_content_written(plan, chapter):  # type: ignore[attr-defined]  # 混入类：方法由 BookService 提供
                raise ChapterAlreadyWrittenError("该章已有内容，拒绝重跑")
        result = await self._agentic_pipeline.execute(  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供；鸭子类型：agentic_pipeline 按 BookAgenticPipeline 契约提供 execute
            plan, chapters, merged, config=config, thread_id=str(plan.id)
        )
        plan.status = str(result.get("status", "completed"))
        plan.thread_id = result.get("thread_id", str(plan.id))
        await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            plan
        )
        return {"run_id": str(plan.id), "status": plan.status}
