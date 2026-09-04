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
from typing import Any

from loguru import logger

from inkflow.domain.models.agent_book import AgenticBookConfig
from inkflow.domain.models.writing_plan import BookLimits, WritingPlan


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
        plan.progress_reason = None  # 整单异常兜底无章级原因语义：清空陈旧值（防跨态泄漏）
        await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            plan
        )
        return {"run_id": run_id, "status": "failed"}

    @staticmethod
    def _derive_run_status(progress: dict[str, str]) -> str:
        """按章级事实派生 run 终态（spec §5.5 表，#897）：无 failed → completed；
        failed>0 且 done==0 → failed；其余（部分成功）→ degraded。"""
        failed_count = sum(1 for value in progress.values() if value == "failed")
        done_count = sum(1 for value in progress.values() if value == "done")
        if failed_count == 0:
            return "completed"
        if done_count == 0:
            return "failed"
        return "degraded"

    @staticmethod
    def _chapter_facts_from_state(state: object) -> dict[str, str] | None:
        """pipeline checkpoint state → 章级事实 {outline_id: 状态词|execution_id}.

        volume/agentic checkpoint 两轨权威源均为 state["results"]（execution 事实）；
        state["progress"] 仅作旧形态回退；非 dict / 空 → None（旧鸭子无
        get_checkpoint_state 或 AsyncMock 自动属性 → 跳过派生维持原态）。
        """
        if not isinstance(state, dict):
            return None
        results = state.get("results")
        facts: dict[Any, Any] | None
        if isinstance(results, dict):
            facts = results
        else:
            progress = state.get("progress")
            facts = progress if isinstance(progress, dict) else None
        return dict(facts) if facts else None

    @staticmethod
    def _static_track_reason(lines: list[str]) -> str:
        """失败原因行列表 → 摘要：换行拼接后截断至 String(2000) 上限."""
        return "\n".join(lines)[:2000]

    def _finalize_from_state(self, plan: WritingPlan, state: object, fallback_reason: str) -> str:
        """#897 收尾派生核心：checkpoint 章事实同步回 plan 后按 §5.5 表重判终态.

        facts 缺失（旧形态 checkpoint / 非 dict）→ 返回 completed 不碰 plan；
        facts 非空 → 同步 plan.progress/execution_refs（补 volume 轨长期不回写章
        进度的掩蔽），failed/degraded 时以 failed 章列表 + fallback_reason 提示写
        progress_reason。usage 同步在 progress 同步后执行（#902：checkpoint usage
        事件通道全量覆盖派生 tokens_used/prompt_tokens/completion_tokens；无 usage
        键/空列表 → 三键不写——#897/#860 旧 checkpoint 向后兼容）。
        """
        facts = self._chapter_facts_from_state(state)
        if facts is None:
            return "completed"
        for oid, ref in facts.items():
            if ref == "failed":
                plan.progress[oid] = "failed"
            else:
                plan.progress[oid] = "done"
                if ref not in {"done", "in_progress"}:
                    plan.execution_refs[oid] = ref
        status = self._derive_run_status(plan.progress)
        if status in {"failed", "degraded"}:
            failed_ids = [oid for oid, value in plan.progress.items() if value == "failed"]
            plan.progress_reason = self._static_track_reason(
                [f"{oid} {fallback_reason}" for oid in failed_ids]
            )
        else:
            plan.progress_reason = None
        self._overwrite_usage_from_events(plan, state)
        return status

    @staticmethod
    def _overwrite_usage_from_events(plan: WritingPlan, state: object) -> None:
        """#902 收尾 usage 覆盖派生：state["usage"] 事件列表求和 → 覆盖写三键 + 告警.

        覆盖语义 = 幂等（checkpoint 为权威全量源：同 state 收尾两次不重复计费，跨
        HITL resume 后一次覆盖吞并前一次值）；无 usage 键 / 非 list / 空列表 → 不碰
        三键（旧 checkpoint 向后兼容守护）。
        """
        if not isinstance(state, dict):
            return
        events = state.get("usage")
        if not isinstance(events, list) or not events:
            return
        total = sum(int(e.get("total_tokens", 0)) for e in events if isinstance(e, dict))
        prompt = sum(int(e.get("prompt_tokens", 0)) for e in events if isinstance(e, dict))
        completion = sum(int(e.get("completion_tokens", 0)) for e in events if isinstance(e, dict))
        plan.limits["tokens_used"] = total
        plan.limits["prompt_tokens"] = prompt
        plan.limits["completion_tokens"] = completion
        plan.limits["tokens_warning"] = total > int(plan.limits.get("max_tokens", 200_000))

    async def _sync_usage_from_state(
        self, plan: WritingPlan, pipeline: object, *, thread_id: str
    ) -> None:
        """#902 waiting_hitl 落点 usage 同步：读 checkpoint 后同 _finalize 覆盖派生.

        旧鸭子无 get_checkpoint_state / await 抛异常 / 返回非 dict / 无 usage 键或空
        → 静默跳过（向后兼容守护，不抛）。收尾点（_sync_and_finalize）经
        _finalize_from_state 内联同步，零额外 checkpoint 读。
        """
        getter = getattr(pipeline, "get_checkpoint_state", None)
        if getter is None:
            return
        try:
            state = await getter(thread_id)
        except Exception as exc:
            logger.warning("#902 checkpoint usage 同步失败（thread_id=%s）: %s", thread_id, exc)
            return
        if isinstance(state, dict):
            self._overwrite_usage_from_events(plan, state)

    async def _sync_and_finalize(
        self,
        plan: WritingPlan,
        pipeline: object,
        *,
        thread_id: str,
        fallback_reason: str,
    ) -> str:
        """读取 pipeline checkpoint 后统一收尾派生（#897 收尾入口）.

        旧鸭子（无 get_checkpoint_state）/ 读 checkpoint 抛异常 / 返回非 dict →
        跳过派生返回 completed（阶段 3/4 既有 mock 向后兼容守护）。
        """
        getter = getattr(pipeline, "get_checkpoint_state", None)
        if getter is None:
            return "completed"
        try:
            state = await getter(thread_id)
        except Exception as exc:
            state = None  # fresh mock/DB 无 checkpoint → 按旧语义维持 completed
            logger.warning(
                "#897 checkpoint 读取失败，跳过收尾派生（thread_id=%s）: %s", thread_id, exc
            )
        return self._finalize_from_state(plan, state, fallback_reason)

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
        安全阀（Outline 形态）通过后、execute 前统一转章 dict（_outline_to_chapter_dict，
        镜像卷轨 #337 装配契约，#915：pipeline 消费 ChapterDict 而非 Outline 领域对象），
        execute 返回后按 result.status 写回 plan.status + thread_id 落库。

        Args:
            plan_id: 计划 UUID（run 载体 = WritingPlan）.
            limits: 请求显式上限；None = 回退项目级 extra / 默认常量.
            config: agentic 模式配置（AgenticBookConfig）；None = 默认配置.

        Returns:
            {"run_id": str(plan.id), "status": plan.status（执行后完成态重派生为
            completed | failed | degraded）}.

        Raises:
            ValueError: 计划不存在；或 agentic_pipeline 未配置（防静默降级）.
            ChapterAlreadyWrittenError: 任一目标章已有内容或执行已完成.
        """
        # 函数体 import：避免与 book_service 模块级循环依赖（错误类/章转换函数均定义于彼）
        from inkflow.domain.services.book_service import (
            ChapterAlreadyWrittenError,
            _outline_to_chapter_dict,
        )

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
        # #915：execute 前统一转章 dict（镜像卷轨 _outline_to_chapter_dict 装配契约，
        # pipeline 消费 ChapterDict——outline_id/chapter_id/name/...，而非 Outline 对象）
        chapters = [_outline_to_chapter_dict(c) for c in chapters]
        result = await self._agentic_pipeline.execute(  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供；鸭子类型：agentic_pipeline 按 BookAgenticPipeline 契约提供 execute
            plan, chapters, merged, config=config, thread_id=str(plan.id)
        )
        plan.status = str(result.get("status", "completed"))
        plan.thread_id = result.get("thread_id", str(plan.id))
        if plan.status == "completed":
            # #897：pipeline 报告 completed 也按 checkpoint 章事实重派生（_fallback_node
            # 硬编码 completed 时全章 failed 不再假绿）
            plan.status = await self._sync_and_finalize(
                plan,
                self._agentic_pipeline,  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
                thread_id=plan.thread_id or str(plan.id),
                fallback_reason="凭据无效或运行时错误，详见章执行日志",
            )
        await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            plan
        )
        return {"run_id": str(plan.id), "status": plan.status}
