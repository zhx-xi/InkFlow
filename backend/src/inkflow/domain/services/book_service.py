"""F44 书级运行服务 - write_book 编排入口、进度状态机、上限校验、委托契约.

BookService 职责：
- write_book: 启动书级运行（run_id = WritingPlan.id），校验「至少一道有限护栏」，
  从 outline 表取全部 level=chapter 节点按 sort_order 顺序派发，委托 F27 writer。
- prepare_run: 后台任务改造（#456）新增——启动前预校验（计划/护栏/安全阀）+ running
  落库，不执行章委托；POST /runs 预校验后启后台任务。
- _delegate_chapter: 委托契约核心 - 章 brief → writer_factory → agent.invoke →
  save_draft 回收 → Draft 落库 → 返回 execution_id。
- get_status: 书级运行状态（进度树 + 计数器派生字段）。

阶段 1 上限写死 max_chapters=1/max_agent_calls=1（#335「上限写死但计数器立起来」），
阶段 2 放开配置：读取优先级 = 请求显式 > 项目级 ProjectConfig.extra > 默认常量
（§2.4/D11 Q2=C）；「内容已写」安全闸先于一切执行（§5.2/D8）。

阶段 3 卷级编排（#337）：write_book_volume（安全阀 → 卷 planner 拆章 → 卷图 Send 扇出 →
卷边界 HITL 暂停落库 waiting_hitl）+ confirm_run（waiting_hitl → pipeline.resume）+
get_status 顶层 waiting_hitl/hitl_payload（§3/§13.3 M8）。

仅依赖 domain/models 与注入的 repo/可调用对象（鸭子类型），
domain/ 零框架 import 门禁天然满足（ADR-002/015）。

依据: specs/f44-book-orchestrator/spec.md §2.4/§5.1/§13.1（v1.1）.
"""

from __future__ import annotations

import difflib
import inspect
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict, cast

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import (
    STAGE1_LIMITS,
    BookLimits,
    WritingPlan,
    merge_book_limits,
    validate_at_least_one_hard_limit,
)
from inkflow.domain.services.book_run_mixin import BookRunMixin


class ChapterAlreadyWrittenError(Exception):
    """「内容已写」安全闸命中：该章已有内容或执行已完成，拒绝重跑（#309 语义）。
    依据: spec §5.2/D8（设计 §2.3-1 最高优先级——create_execution 前查，
    误判宁可拒绝不可重跑，防重复内容 + 双倍费用）。
    """


def _outline_to_chapter_dict(o: Outline) -> ChapterDict:
    """Outline 章节点 → 卷级编排图章 dict（契约 §3.5 形态：pipeline 消费字典非领域对象）。

    卷级编排图（BookVolumePipeline）按 dict 契约消费章数据（outline_id/chapter_id/name/
    description/sort_order）——装配缺口实证（2026-08-17 真实冒烟：mock 轨全绿但真实链路
    传 Outline 对象致 _write_chapter 下标访问 TypeError），拆章层统一转换。
    """
    return {
        "outline_id": o.id,
        "chapter_id": o.chapter_id,
        "name": o.name,
        "description": o.description,
        "sort_order": o.sort_order,
    }


class ChapterDict(TypedDict):
    """卷级编排图章 dict（_outline_to_chapter_dict 产物，pipeline 消费形态）。"""

    outline_id: uuid.UUID
    chapter_id: uuid.UUID | None
    name: str
    description: str
    sort_order: int


class VolumeGroup(TypedDict):
    """卷 planner 拆章产出（镜像契约 §1.2）：volume_id + 其下 chapters（章 dict）."""

    volume_id: uuid.UUID | None
    chapters: list[ChapterDict]


class BookService(BookRunMixin):
    """书级运行服务.

    Args:
        repo: BookRepositoryProtocol（鸭子类型，get_writing_plan/update_writing_plan）.
        writer_factory: 可调用（镜像 build_agentic_writer 签名 **kwargs → agent，
            含 async invoke(messages)）；None = 委托时报错（防静默降级）.
        draft_service: 鸭子对象（create(*, project_id, chapter_id, content,
            summary) → Draft）；save_draft 回收.
        outline_repo: 鸭子对象（list(project_id, ...) → (list[Outline], total)，
            镜像 OutlineRepositoryProtocol）— 找计划章节点.
        limits: BookLimits（默认 STAGE1_LIMITS = 写死 max_chapters=1/
            max_agent_calls=1）.
        content_checker: 可调用（给定 chapter_id 返回该章是否已有内容，
            镜像 Chapter.content/Draft 检查）；None = 安全闸只查执行记录.
        project_config_getter: 可调用（给定 project_id 返回 ProjectConfig | None，
            Q2=C：取 config.extra 的 book_max_* 键作项目级上限）；None = 无项目级.
        volume_pipeline: 卷级编排引擎（鸭子类型，镜像 BookVolumePipeline：async
            execute(plan, volumes, limits) / async resume(interrupt_obj, *, approved,
            decision)）；None = 卷级入口未配置（write_book_volume/confirm_run 拒绝）.
        execution_store: 执行记录仓储（鸭子类型，镜像 ExecutionStore：async
            create_execution(pipeline, project_id, *, thread_id, execution_id) /
            async update_status(execution_id, status, hitl_payload=None)）；None =
            跳过执行记录落库（防御分支）.
        outline_updater: 可调用（async (outline_id: uuid.UUID, description: str) →
            object | None，改 outline.description）；None = edit 干预拒绝.
        agentic_pipeline: book-level 自主编排引擎（鸭子类型，镜像 BookAgenticPipeline：
            async execute(plan, chapters, limits, *, config, thread_id)）；None =
            write_book_agentic 拒绝（防静默降级）.
    """

    def __init__(
        self,
        *,
        repo: object,
        writer_factory: Callable[..., Awaitable[object]] | None = None,
        draft_service: object | None = None,
        outline_repo: object | None = None,
        limits: BookLimits = STAGE1_LIMITS,
        content_checker: Callable[[uuid.UUID], Awaitable[bool]] | None = None,
        project_config_getter: Callable[[uuid.UUID], Awaitable[object]] | None = None,
        volume_pipeline: object | None = None,  # 新增：卷级编排引擎（BookVolumePipeline 鸭子类型）
        execution_store: object | None = None,  # 新增：执行记录仓储（ExecutionStore 鸭子类型）
        outline_updater: Callable[[uuid.UUID, str], Awaitable[object | None]] | None = None,
        agentic_pipeline: object | None = None,  # 新增：book-level 自主编排引擎（鸭子类型）
    ) -> None:
        self._repo = repo
        self._writer_factory = writer_factory
        self._draft_service = draft_service
        self._outline_repo = outline_repo
        self._limits = limits
        self._content_checker = content_checker
        self._project_config_getter = project_config_getter
        self._volume_pipeline = volume_pipeline
        self._execution_store = execution_store
        self._outline_updater = outline_updater
        self._agentic_pipeline = agentic_pipeline

    async def write_book(
        self, plan_id: uuid.UUID, limits: BookLimits | None = None
    ) -> dict[str, str]:
        """启动书级运行（202 语义）→ {run_id, status}（阶段 2 顺序派发）.

        limits 解析链（§2.4/D11 Q2=C）：默认 → 项目级 ProjectConfig.extra（book_max_* 键）
        → 请求显式字段（model_fields_set）→ validate_at_least_one_hard_limit.
        「内容已写」安全闸（§5.2/D8）先于一切执行：任一目标章已有内容/执行完成 →
        ChapterAlreadyWrittenError，一个章都不委托。顺序派发：每章 in_progress → 委托
        → done/failed 落库；硬护栏（章数/调用数）超限 → 剩余章 skipped；无章 → completed.

        Args:
            plan_id: 计划 UUID（run 载体 = WritingPlan）.
            limits: 请求显式上限；None = 回退项目级 extra / 默认常量.

        Returns:
            {"run_id": str(plan.id), "status": "completed" | "failed" | "degraded"}.

        Raises:
            ValueError: 计划不存在；或上限全无（「至少一道有限护栏」不变量）.
            ChapterAlreadyWrittenError: 任一目标章已有内容或执行已完成.
        """
        plan = await self._repo.get_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_writing_plan
            plan_id
        )
        if plan is None:
            raise ValueError("计划不存在")
        project_extra: dict[str, Any] | None = None
        if self._project_config_getter is not None:
            config: object | None = await self._project_config_getter(plan.project_id)
            project_extra = getattr(config, "extra", None)
        merged = merge_book_limits(limits, project_extra)
        validate_at_least_one_hard_limit(merged)
        # 生效上限写回 plan.limits（M5：book status 显示真实配置；不覆盖 tokens_* 运行计数）
        for _field in ("max_chapters", "max_agent_calls", "max_tokens", "max_sessions"):
            plan.limits[_field] = getattr(merged, _field)
        chapters = await self._find_chapters(plan)
        for chapter in chapters:
            if await self._check_content_written(plan, chapter):
                raise ChapterAlreadyWrittenError("该章已有内容，拒绝重跑")
        if not chapters:
            plan.status = "completed"
            await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
                plan
            )
            return {"run_id": str(plan.id), "status": "completed"}
        failure_reasons: dict[str, str] = {}
        for chapter in chapters:
            done_count = sum(1 for v in plan.progress.values() if v == "done")
            if (
                done_count >= merged.max_chapters
                or len(plan.execution_refs) >= merged.max_agent_calls
            ):
                plan.progress[str(chapter.id)] = "skipped"
                await self._repo.update_writing_plan(plan)  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
                continue
            plan.progress[str(chapter.id)] = "in_progress"
            await self._repo.update_writing_plan(plan)  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
            try:
                execution_id = await self._delegate_chapter(plan, chapter, merged)
                plan.progress[str(chapter.id)] = "done"
                plan.execution_refs[str(chapter.id)] = execution_id
            except Exception as exc:
                plan.progress[str(chapter.id)] = "failed"
                failure_reasons[str(chapter.id)] = f"{type(exc).__name__}: {exc}"
            await self._repo.update_writing_plan(plan)  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
        plan.status = self._derive_run_status(plan.progress)
        plan.progress_reason = (
            self._static_track_reason([f"{oid}: {msg}" for oid, msg in failure_reasons.items()])
            if plan.status in {"failed", "degraded"}
            else None
        )
        await self._repo.update_writing_plan(plan)  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
        return {"run_id": str(plan.id), "status": plan.status}

    async def write_book_volume(
        self, plan_id: uuid.UUID, limits: BookLimits | None = None
    ) -> dict[str, str]:
        """卷级编排入口（阶段 3，#337）：安全阀预检 → 卷 planner 拆章 → 卷图 Send 扇出 → 卷边界暂停.

        limits 解析链复用阶段 2（§2.4/D11）：merge_book_limits + validate_at_least_one_hard_limit，
        生效上限写回 plan.limits。「内容已写」安全阀（§5.2/D8）先于一切执行：任一目标章已有
        内容/执行完成 → ChapterAlreadyWrittenError，volume_pipeline 零调用。
        卷 planner 拆章（_find_volumes）：有 level=volume 节点按 parent_id 分组，无卷节点整本
        书作为一卷；委托 volume_pipeline.execute(plan, volumes, merged) 恰一次。
        阶段 4（#338）：thread_id = str(plan.id)（书级运行 ↔ 图 checkpoint 一一映射）写回
        plan.thread_id 并落库；execution_store 落库书级运行执行记录（pipeline="book:volume"，
        execution_id/thread_id = str(plan.id)）。

        Args:
            plan_id: 计划 UUID（run 载体 = WritingPlan）.
            limits: 请求显式上限；None = 回退项目级 extra / 默认常量.

        Returns:
            {"run_id": str(plan.id), "status": "waiting_hitl" | "completed" | "failed" |
            "degraded"}.

        Raises:
            ValueError: 计划不存在 / 上限全无 / volume_pipeline 未配置.
            ChapterAlreadyWrittenError: 任一目标章已有内容或执行完成.
        """
        plan = await self._repo.get_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_writing_plan
            plan_id
        )
        if plan is None:
            raise ValueError("计划不存在")
        merged = await self._resolve_merged_limits(plan, limits)
        volumes = await self._find_volumes(plan)
        # 安全阀预检全部目标章（§5.2/D8）：任一章已有内容/执行完成 → 拒绝重跑，卷图零调用
        # volumes[].chapters 为章 dict（_outline_to_chapter_dict 产物）——按 outline_id 判
        for volume in volumes:
            for chapter in volume["chapters"]:
                if await self._check_chapter_written(plan, chapter):
                    raise ChapterAlreadyWrittenError("该章已有内容，拒绝重跑")
        if self._volume_pipeline is None:
            raise ValueError("volume_pipeline 未配置")
        # thread_id = 书级运行 id（run_id 语义统一：书级运行 ↔ 图 checkpoint 一一映射）
        thread_id = str(plan.id)
        plan.thread_id = thread_id
        # execution_store 落库（None 则跳过防御）：书级运行执行记录 id 固定 = str(plan.id)
        if self._execution_store is not None:
            await self._execution_store.create_execution(  # type: ignore[attr-defined]  # 鸭子类型：execution_store 按 ExecutionStore 契约提供 create_execution
                pipeline="book:volume",
                project_id=str(plan.project_id),
                thread_id=thread_id,
                execution_id=thread_id,
            )
        # 函数体 import：domain 层不形成对 infrastructure 的模块级依赖（ADR-002/015）
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt
        try:
            await self._call_pipeline_execute(plan, volumes, merged, thread_id=thread_id)
        except VolumeHITLInterrupt as exc:
            # 卷边界/卷失败中断：waiting_hitl + payload + thread_id 落库（中断不传播）
            plan.status = "waiting_hitl"
            plan.hitl_payload = exc.payload
            await self._repo.update_writing_plan(plan)  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
            return {"run_id": str(plan.id), "status": "waiting_hitl"}
        plan.status = await self._sync_and_finalize(
            plan,
            self._volume_pipeline,
            thread_id=thread_id,
            fallback_reason="凭据无效或运行时错误，详见章执行日志",
        )
        await self._repo.update_writing_plan(plan)  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
        return {"run_id": str(plan.id), "status": plan.status}

    async def confirm_run(self, run_id: str, *, approved: bool, decision: str = "") -> dict:
        """卷级 HITL 确认（阶段 3，#337）：waiting_hitl → pipeline.resume 继续 / 再次暂停.

        interrupt_obj 由 plan.hitl_payload 重建（VolumeHITLInterrupt，函数体 import）；
        resume 再抛 → 更新 hitl_payload + 落库返回 waiting_hitl；正常返回 → 按 result.status
        更新 plan.status。阶段 4（#338）：resume 传 thread_id（plan.thread_id 兜底
        str(plan.id)）；正常返回后 execution_store.update_status 同步执行记录状态.

        Args:
            run_id: 书级运行 id（= WritingPlan.id 字符串）.
            approved: 卷边界确认：True 继续下一卷 / False 中止.
            decision: 卷失败恢复决策：continue / abort / supervisor（卷边界忽略）.

        Returns:
            resume 结果 {"run_id", "status": running | waiting_hitl | completed} 或
            {"run_id", "status": "waiting_hitl", "hitl_payload": ...}.

        Raises:
            ValueError: 运行不存在 / 未处于等待确认状态 / volume_pipeline 未配置.
        """
        plan = await self._repo.get_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_writing_plan
            run_id
        )
        if plan is None:
            raise ValueError("运行不存在")
        if plan.status != "waiting_hitl":
            raise ValueError("运行未处于等待确认状态")
        if self._volume_pipeline is None:
            raise ValueError("volume_pipeline 未配置")
        # 函数体 import：domain 层不形成对 infrastructure 的模块级依赖（ADR-002/015）
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        interrupt_obj = VolumeHITLInterrupt(plan.hitl_payload or {})
        thread_id = plan.thread_id or str(plan.id)
        try:
            result = await self._call_pipeline_resume(
                interrupt_obj, approved=approved, decision=decision, thread_id=thread_id
            )
        except VolumeHITLInterrupt as exc:
            # 下一卷边界：更新 payload + 落库，保持 waiting_hitl
            plan.hitl_payload = exc.payload
            await self._repo.update_writing_plan(plan)  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
            return {
                "run_id": str(plan.id),
                "status": "waiting_hitl",
                "hitl_payload": exc.payload,
            }
        plan.status = str(result.get("status", "completed"))
        if plan.status == "completed":
            plan.status = await self._sync_and_finalize(
                plan,
                self._volume_pipeline,
                thread_id=thread_id,
                fallback_reason="凭据无效或运行时错误，详见章执行日志",
            )
            result["status"] = plan.status
        await self._repo.update_writing_plan(plan)  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
        # execution_store 状态同步（书级运行执行记录 id 固定 = str(plan.id)，阶段 4）
        if self._execution_store is not None:
            await self._execution_store.update_status(  # type: ignore[attr-defined]  # 鸭子类型：execution_store 按 ExecutionStore 契约提供 update_status
                execution_id=str(plan.id), status=plan.status
            )
        return cast(dict, result)

    async def get_status(self, run_id: str) -> dict[str, Any] | None:
        """书级运行状态（进度树 + 计数器）→ None = run 不存在.

        Args:
            run_id: 书级运行 id（= WritingPlan.id 字符串）.

        Returns:
            {run_id, status, progress, progress_reason, waiting_hitl, hitl_payload,
            counters}；progress_reason 仅 failed/degraded 透出（键恒在）.
        """
        plan = await self._repo.get_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_writing_plan
            run_id
        )
        if plan is None:
            return None
        reason = plan.progress_reason if plan.status in {"failed", "degraded"} else None
        return {
            "run_id": run_id,
            "status": plan.status,
            "progress": plan.progress,
            "progress_reason": reason,
            "waiting_hitl": plan.status == "waiting_hitl",
            "hitl_payload": plan.hitl_payload if plan.status == "waiting_hitl" else None,
            "counters": self._build_counters(plan),
        }

    async def intervene(
        self,
        run_id: str,
        *,
        action: str,
        target: str | None = None,
        to: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        """中途干预 API（阶段 4，#338；spec Q3=A/D12）：pause / resume / redirect / edit.

        读 plan 不存在 → ValueError("运行不存在")；pause：仅 running 可暂停；
        resume：仅 paused 可恢复为 running（续跑逻辑在 resume_run）；redirect：章级
        被动动作 skip/retry/mark_failed（改 plan.progress + execution_refs，零 LLM）；
        edit：改 outline.description + difflib unified_diff 标注。
        已完成章（progress=done）拒绝干预 → ValueError("已完成章不可干预").

        Args:
            run_id: 书级运行 id（= WritingPlan.id 字符串）.
            action: pause / resume / redirect / edit.
            target: 目标 outline_id（redirect/edit）.
            to: redirect 动作：skip / retry / mark_failed.
            payload: edit 载荷 {"brief": str}.

        Returns:
            pause/resume: {"run_id", "status"}；redirect/edit 带 "diff" 字段.

        Raises:
            ValueError: 运行不存在 / 非法干预动作 / 未处于可暂停状态 /
                干预目标不存在 / 已完成章不可干预 / 大纲更新器未装配 / 干预参数缺失.
        """
        plan = await self._repo.get_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_writing_plan
            run_id
        )
        if plan is None:
            raise ValueError("运行不存在")
        if action not in {"pause", "resume", "redirect", "edit"}:
            raise ValueError("非法干预动作")
        if action == "pause":
            if plan.status != "running":
                raise ValueError("运行未处于可暂停状态")
            plan.status = "paused"
            await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
                plan
            )
            return {"run_id": str(plan.id), "status": "paused"}
        if action == "resume":
            if plan.status != "paused":
                raise ValueError("运行未处于可暂停状态")
            plan.status = "running"
            await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
                plan
            )
            return {"run_id": str(plan.id), "status": "running"}
        if action == "redirect":
            if not target:
                raise ValueError("干预目标不存在")
            if to not in {"skip", "retry", "mark_failed"}:
                raise ValueError("非法干预动作")
            if target in plan.progress:
                from_status = plan.progress[target]
            else:
                node = await self._find_outline_node(plan, target)
                if node is None:
                    raise ValueError("干预目标不存在")
                from_status = "pending"
            if plan.progress.get(target) == "done":
                raise ValueError("已完成章不可干预")
            if to == "skip":
                new_status = "skipped"
                plan.execution_refs.pop(target, None)
            elif to == "retry":
                new_status = "pending"
                plan.execution_refs.pop(target, None)
            else:
                new_status = "failed"
            plan.progress[target] = new_status
            await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
                plan
            )
            return {
                "run_id": str(plan.id),
                "status": plan.status,
                "diff": {"target": target, "from": from_status, "to": new_status},
            }
        # edit：brief 必填 → 目标章判定 → done 拒绝 → updater 装配 → before 来源
        if not target:
            raise ValueError("干预目标不存在")
        brief = payload.get("brief") if payload else None
        if not brief:
            raise ValueError("干预参数缺失")
        if target not in plan.progress:
            node = await self._find_outline_node(plan, target)
            if node is None:
                raise ValueError("干预目标不存在")
        if plan.progress.get(target) == "done":
            raise ValueError("已完成章不可干预")
        if self._outline_updater is None:
            raise ValueError("大纲更新器未装配")
        node = await self._find_outline_node(plan, target)
        if node is None:
            raise ValueError("干预目标不存在")
        before = node.description
        await self._outline_updater(uuid.UUID(target), brief)
        diff_str = "".join(difflib.unified_diff([before], [brief], lineterm=""))
        return {
            "run_id": str(plan.id),
            "status": plan.status,
            "diff": {"target": target, "before": before, "after": brief, "diff": diff_str},
        }

    async def resume_run(self, run_id: str) -> dict:
        """跨重启续跑（阶段 4，#338；spec §13.3 M10 + §3.2 最终裁定）.

        完整续跑逻辑：paused → 读 checkpoint（get_checkpoint_state(thread_id)）→
        有 pending __interrupt__ → resume(approved=True, thread_id=thread_id)；
        无 __interrupt__（task 被 cancel 停在普通 superstep）→ 重新 _find_volumes +
        execute(plan, volumes, merged, thread_id=thread_id) 同 thread_id 续跑.
        两者再抛 VolumeHITLInterrupt → waiting_hitl + hitl_payload 落库.

        Args:
            run_id: 书级运行 id（= WritingPlan.id 字符串）.

        Returns:
            resume/execute 结果 {"run_id", "status": running | waiting_hitl |
            completed | failed | degraded} 或 {"run_id", "status": "waiting_hitl"}.

        Raises:
            ValueError: 运行不存在 / 运行未处于可暂停状态 / volume_pipeline 未配置.
        """
        plan = await self._repo.get_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_writing_plan
            run_id
        )
        if plan is None:
            raise ValueError("运行不存在")
        if plan.status != "paused":
            raise ValueError("运行未处于可暂停状态")
        if self._volume_pipeline is None:
            raise ValueError("volume_pipeline 未配置")
        thread_id = plan.thread_id or str(plan.id)
        state = await self._volume_pipeline.get_checkpoint_state(  # type: ignore[attr-defined]  # 鸭子类型：volume_pipeline 按 BookVolumePipeline 契约提供 get_checkpoint_state
            thread_id
        )
        # 函数体 import：domain 层不形成对 infrastructure 的模块级依赖（ADR-002/015）
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt
        if state is not None and state.get("__interrupt__"):
            # pending interrupt：由 checkpoint __interrupt__ 值重建 VolumeHITLInterrupt 续跑
            interrupt_obj = VolumeHITLInterrupt(state["__interrupt__"][0].value)
            try:
                result = await self._call_pipeline_resume(
                    interrupt_obj, approved=True, thread_id=thread_id
                )
            except VolumeHITLInterrupt as exc:
                plan.status = "waiting_hitl"
                plan.hitl_payload = exc.payload
                await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
                    plan
                )
                return {"run_id": str(plan.id), "status": "waiting_hitl"}
            plan.status = str(result.get("status", "completed"))
            if plan.status == "completed":
                # fresh 重读：动作前快照仅供中断判定，收尾以动作后 checkpoint 为事实源（#897）
                plan.status = await self._sync_and_finalize(
                    plan,
                    self._volume_pipeline,
                    thread_id=thread_id,
                    fallback_reason="凭据无效或运行时错误，详见章执行日志",
                )
                result["status"] = plan.status  # #897：派生态回写 result
            await self._repo.update_writing_plan(plan)  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
            return cast(dict, result)
        # 无 interrupt（cancel 停在普通 superstep）：重新拆卷 + 同 thread_id 续跑
        volumes = await self._find_volumes(plan)
        merged = await self._resolve_merged_limits(plan, None)
        try:
            result = await self._call_pipeline_execute(plan, volumes, merged, thread_id=thread_id)
        except VolumeHITLInterrupt as exc:
            plan.status = "waiting_hitl"
            plan.hitl_payload = exc.payload
            await self._repo.update_writing_plan(plan)  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
            return {"run_id": str(plan.id), "status": "waiting_hitl"}
        plan.status = str(result.get("status", "completed"))
        if plan.status == "completed":
            plan.status = await self._sync_and_finalize(
                plan,
                self._volume_pipeline,
                thread_id=thread_id,
                fallback_reason="凭据无效或运行时错误，详见章执行日志",
            )
            result["status"] = plan.status
        await self._repo.update_writing_plan(plan)  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
        return cast(dict, result)

    async def get_summary(self, run_id: str) -> dict[str, Any] | None:
        """回归摘要（阶段 4，#338；spec §13.3 M12）：进度树 + 计数器 + steps 章级快照
        + 下一卷 checkpoint 状态 → None = run 不存在（API 404）.

        steps 从 progress/execution_refs 派生（不含章名——渲染层补充）；counters 与
        get_status 同构 7 键；next 取 checkpoint 的 volume_index/total_volumes/
        finished/status，无 checkpoint 或 volume_pipeline 未配置 → {"finished": True}.

        Args:
            run_id: 书级运行 id（= WritingPlan.id 字符串）.

        Returns:
            {"run_id", "status", "progress", "counters", "steps", "next"} 或 None.
        """
        plan = await self._repo.get_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_writing_plan
            run_id
        )
        if plan is None:
            return None
        steps = [
            {
                "index": i,
                "outline_id": oid,
                "status": plan.progress.get(oid, "pending"),
                "execution_id": plan.execution_refs.get(oid),
            }
            for i, oid in enumerate(plan.progress.keys())
        ]
        next_dict: dict[str, Any]
        if self._volume_pipeline is not None and plan.thread_id:
            state = await self._volume_pipeline.get_checkpoint_state(  # type: ignore[attr-defined]  # 鸭子类型：volume_pipeline 按 BookVolumePipeline 契约提供 get_checkpoint_state
                plan.thread_id
            )
            if state is not None:
                next_dict = {
                    "volume_index": state.get("volume_index"),
                    "total_volumes": state.get("total_volumes"),
                    "finished": state.get("finished", False),
                    "status": state.get("status"),
                }
            else:
                next_dict = {"finished": True}
        else:
            next_dict = {"finished": True}
        reason = plan.progress_reason if plan.status in {"failed", "degraded"} else None
        return {
            "run_id": run_id,
            "status": plan.status,
            "progress": plan.progress,
            "progress_reason": reason,
            "counters": self._build_counters(plan),
            "steps": steps,
            "next": next_dict,
        }

    async def _find_chapters(self, plan: WritingPlan) -> list[Outline]:
        """取全部 level=chapter 节点，按 sort_order 升序（阶段 2 顺序派发，§5.2）.
        无 outline_repo → 空列表.
        """
        if self._outline_repo is None:
            return []
        outlines_raw, _ = await self._outline_repo.list(  # type: ignore[attr-defined]  # 鸭子类型：outline_repo 按 OutlineRepositoryProtocol 提供 list
            plan.project_id
        )
        outlines: list[Outline] = cast(list[Outline], outlines_raw)
        chapters = [o for o in outlines if o.level == "chapter"]
        return sorted(chapters, key=lambda o: (o.sort_order, str(o.id)))

    async def _find_volumes(self, plan: WritingPlan) -> list[VolumeGroup]:
        """卷 planner 拆章（阶段 3，#337）：outline 表取 level=volume 节点 + 其下 level=chapter
        子节点（parent_id=volume.id，sort_order 升序）→ 按卷分组；无卷节点 → 整本书作为一卷
        （volume_id = plan.root_outline_id，章节 = 全部 level=chapter 按 sort_order 升序）.
        无 outline_repo → 空列表（镜像 _find_chapters 防御分支）.
        """
        if self._outline_repo is None:
            return []
        outlines_raw, _ = await self._outline_repo.list(  # type: ignore[attr-defined]  # 鸭子类型：outline_repo 按 OutlineRepositoryProtocol 提供 list
            plan.project_id
        )
        outlines: list[Outline] = cast(list[Outline], outlines_raw)
        volume_nodes = sorted(
            (o for o in outlines if o.level == "volume"),
            key=lambda o: (o.sort_order, str(o.id)),
        )
        if volume_nodes:
            return [
                {
                    "volume_id": volume.id,
                    "chapters": [
                        _outline_to_chapter_dict(o)
                        for o in sorted(
                            (
                                o
                                for o in outlines
                                if o.level == "chapter" and o.parent_id == volume.id
                            ),
                            key=lambda o: (o.sort_order, str(o.id)),
                        )
                    ],
                }
                for volume in volume_nodes
            ]
        chapters = sorted(
            (o for o in outlines if o.level == "chapter"),
            key=lambda o: (o.sort_order, str(o.id)),
        )
        return [
            {
                "volume_id": plan.root_outline_id,
                "chapters": [_outline_to_chapter_dict(o) for o in chapters],
            }
        ]

    async def _find_outline_node(self, plan: WritingPlan, target: str) -> Outline | None:
        """按 outline_id 查大纲节点（干预目标判定 + edit before 来源）.
        无 outline_repo / 目标非合法 UUID / 节点不存在 → None.
        """
        if self._outline_repo is None:
            return None
        outlines_raw, _ = await self._outline_repo.list(  # type: ignore[attr-defined]  # 鸭子类型：outline_repo 按 OutlineRepositoryProtocol 提供 list
            plan.project_id
        )
        outlines: list[Outline] = cast(list[Outline], outlines_raw)
        try:
            target_uuid = uuid.UUID(target)
        except ValueError:
            return None
        return next((o for o in outlines if o.id == target_uuid), None)

    async def _resolve_merged_limits(
        self, plan: WritingPlan, limits: BookLimits | None
    ) -> BookLimits:
        """上限解析链（阶段 2 §2.4/D11 Q2=C，write_book_volume/resume_run 复用）：
        请求显式 > 项目级 ProjectConfig.extra > 默认常量；validate + 生效上限写回
        plan.limits（不覆盖 tokens_* 运行计数）."""
        project_extra: dict[str, Any] | None = None
        if self._project_config_getter is not None:
            config: object | None = await self._project_config_getter(plan.project_id)
            project_extra = getattr(config, "extra", None)
        merged = merge_book_limits(limits, project_extra)
        validate_at_least_one_hard_limit(merged)
        for _field in ("max_chapters", "max_agent_calls", "max_tokens", "max_sessions"):
            plan.limits[_field] = getattr(merged, _field)
        return merged

    @staticmethod
    def _build_counters(plan: WritingPlan) -> dict[str, Any]:
        """书级运行计数器（get_status / get_summary 同构 7 键，缺省与阶段 1 常量一致）."""
        return {
            "max_chapters": plan.limits.get("max_chapters", 1),
            "max_agent_calls": plan.limits.get("max_agent_calls", 1),
            "max_tokens": plan.limits.get("max_tokens", 200_000),
            "tokens_used": plan.limits.get("tokens_used", 0),
            "tokens_warning": plan.limits.get("tokens_warning", False),
            "agent_calls": len(plan.execution_refs),
            "chapters_written": sum(1 for v in plan.progress.values() if v == "done"),
        }

    @staticmethod
    def _pipeline_accepts_thread_id(method: Callable[..., Any]) -> bool:
        """thread_id 兼容判定：阶段 4 契约要求 execute/resume 透传 thread_id（书级运行
        ↔ checkpoint 一一映射），但阶段 3 旧形态鸭子（测试 mock 无该参数）需回退位置
        调用——按签名探测；AsyncMock 等无签名对象按新契约透传."""
        try:
            sig = inspect.signature(method)
        except (TypeError, ValueError):
            return True
        return "thread_id" in sig.parameters or any(
            param.kind is inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()
        )

    async def _call_pipeline_execute(
        self,
        plan: WritingPlan,
        volumes: list[VolumeGroup],
        merged: BookLimits,
        *,
        thread_id: str,
    ) -> dict[str, Any]:
        """execute 委派：新形态 pipeline 透传 thread_id；旧形态鸭子回退位置调用."""
        method = self._volume_pipeline.execute  # type: ignore[union-attr]  # 鸭子类型：volume_pipeline 按 BookVolumePipeline 契约提供 execute
        if self._pipeline_accepts_thread_id(method):
            return cast(dict[str, Any], await method(plan, volumes, merged, thread_id=thread_id))
        return cast(dict[str, Any], await method(plan, volumes, merged))

    async def _call_pipeline_resume(
        self,
        interrupt_obj: object,
        *,
        approved: bool,
        decision: str = "",
        thread_id: str,
    ) -> dict[str, Any]:
        """resume 委派：新形态 pipeline 透传 thread_id（跨重启从 plan.thread_id 读）；
        旧形态鸭子回退位置调用."""
        method = self._volume_pipeline.resume  # type: ignore[union-attr]  # 鸭子类型：volume_pipeline 按 BookVolumePipeline 契约提供 resume
        if self._pipeline_accepts_thread_id(method):
            return cast(
                dict[str, Any],
                await method(
                    interrupt_obj,
                    approved=approved,
                    decision=decision,
                    thread_id=thread_id,
                ),
            )
        return cast(
            dict[str, Any],
            await method(interrupt_obj, approved=approved, decision=decision),
        )

    async def _check_content_written(self, plan: WritingPlan, chapter: Outline) -> bool:
        """「内容已写」安全闸判定（§5.2/D8）：执行已完成 或 该章已有内容 → True.
        执行已完成 = execution_refs[outline_id] 存在且 progress==done；
        内容已写 = content_checker(chapter.chapter_id) 返回 True（未装配则跳过）.
        """
        if str(chapter.id) in plan.execution_refs and plan.progress.get(str(chapter.id)) == "done":
            return True
        if self._content_checker is not None and chapter.chapter_id is not None:
            return bool(await self._content_checker(chapter.chapter_id))
        return False

    async def _check_chapter_written(self, plan: WritingPlan, chapter: ChapterDict) -> bool:
        """「内容已写」安全闸（dict 形态，卷级编排用）——镜像 _check_content_written 语义。

        volumes[].chapters 为章 dict（_outline_to_chapter_dict 产物）；content_checker 消费
        领域 chapter_id（uuid）——从 dict 提取，语义与 Outline 形态一致。
        """
        outline_id = str(chapter["outline_id"])
        if outline_id in plan.execution_refs and plan.progress.get(outline_id) == "done":
            return True
        chapter_id = chapter.get("chapter_id")
        if self._content_checker is not None and chapter_id is not None:
            return bool(await self._content_checker(chapter_id))
        return False

    async def _delegate_chapter(
        self, plan: WritingPlan, chapter: Outline, limits: BookLimits
    ) -> str:
        """委托契约核心：章 brief → writer_factory → agent.invoke → save_draft 回收.

        Args:
            plan: 书级计划（提供 project_id / character_ids）.
            chapter: 目标章 outline 节点.
            limits: 合并后的书级上限.

        Returns:
            execution_id（Draft.id 字符串）.

        Raises:
            ValueError: writer_factory 未装配.
        """
        if self._writer_factory is None:
            raise ValueError("writer_factory 未装配")
        system_prompt = self._build_chapter_brief(plan, chapter)
        agent = await self._writer_factory(
            system_prompt=system_prompt,
            expected_project_id=plan.project_id,
            expected_chapter_id=chapter.chapter_id,
        )
        result = await agent.invoke(  # type: ignore[attr-defined]  # 鸭子类型：agent 按 F27 契约提供 async invoke(messages)
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请撰写章节《{chapter.name}》：{chapter.description}"},
            ]
        )
        tokens = _extract_usage_tokens(result)
        plan.limits["tokens_used"] = plan.limits.get("tokens_used", 0) + tokens
        if plan.limits["tokens_used"] > limits.max_tokens:
            plan.limits["tokens_warning"] = True
        content = _extract_final_content(result)
        draft = await self._draft_service.create(  # type: ignore[union-attr]  # 鸭子类型：draft_service 按 F27 契约提供 async create
            project_id=plan.project_id,
            chapter_id=chapter.chapter_id,
            content=content,
            summary="书级委托保存",
        )
        return str(getattr(draft, "id", ""))

    @staticmethod
    def _build_chapter_brief(plan: WritingPlan, chapter: Outline) -> str:
        """构造章 brief（system_prompt）：大纲切片 + character 摘要 + 风格/偏好注入."""
        character_summary = (
            "主角自定" if not plan.character_ids else "见角色档案（plan.character_ids）"
        )
        return (
            "你是一位小说章节写作者。请严格按大纲切片撰写本章正文。\n"
            f"【章节大纲】{chapter.description}\n"
            f"【角色摘要】{character_summary}\n"
            "【风格/偏好注入】遵循项目写作风格与用户偏好（偏好优先于通用文风）。"
        )


def _extract_final_content(result: dict[str, Any]) -> str:
    """从 agent.invoke 结果（dict，含 "messages"）提取最终 message content."""
    messages = result.get("messages", [])
    if not messages:
        return ""
    final = messages[-1]
    content = getattr(final, "content", None)
    if content is None and isinstance(final, dict):
        content = final.get("content")
    if content is None:
        return ""
    return str(content)


def _extract_usage_tokens(result: dict[str, Any]) -> int:
    """Extract cumulative total_tokens from an agent.invoke result.

    Primary source (real deepagents 0.7.5 graph result): per-AIMessage
    usage_metadata dicts ({'total_tokens': N, ...}) — sum over ALL messages
    (a ReAct loop makes multiple LLM calls; top-level result has NO usage key).
    Fallback (legacy/service-level contract, older fakes): top-level
    result["usage"]["total_tokens"] when present and non-zero.
    """
    messages = result.get("messages") or []
    total = 0
    for msg in messages:
        usage = getattr(msg, "usage_metadata", None)
        if usage is None and isinstance(msg, dict):
            usage = msg.get("usage_metadata")
        if isinstance(usage, dict):
            total += int(usage.get("total_tokens") or 0)
    if total == 0:
        usage = result.get("usage")
        if isinstance(usage, dict):
            total = int(usage.get("total_tokens") or 0)
    return total
