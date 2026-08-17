"""F44 书级运行服务 - write_book 编排入口、进度状态机、上限校验、委托契约.

BookService 负责：
- write_book: 启动书级运行（run_id = WritingPlan.id），校验「至少一道有限护栏」，
  从 outline 表取全部 level=chapter 节点按 sort_order 顺序派发，委托 F27 writer.
- _delegate_chapter: 委托契约核心 - 章 brief → writer_factory → agent.invoke →
  save_draft 回收 → Draft 落库 → 返回 execution_id.
- get_status: 书级运行状态（进度树 + 计数器派生字段）.

阶段 1 上限写死 max_chapters=1/max_agent_calls=1（#335「上限写死但计数器立起来」），
阶段 2 放开配置：读取优先级 = 请求显式 > 项目级 ProjectConfig.extra > 默认常量
（§2.4/D11 Q2=C）；「内容已写」安全闸先于一切执行（§5.2/D8）.

仅依赖 domain/models 与注入的 repo/可调用对象（鸭子类型），
domain/ 零框架 import 门禁天然满足（ADR-002/015）.

依据: specs/f44-long-task-orchestrator/spec.md 搂2.4/搂5.1/搂13.1（v1.1）.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import (
    STAGE1_LIMITS,
    BookLimits,
    WritingPlan,
    merge_book_limits,
    validate_at_least_one_hard_limit,
)


class ChapterAlreadyWrittenError(Exception):
    """「内容已写」安全闸命中：该章已有内容或执行已完成，拒绝重跑（#309 语义）。
    依据: spec §5.2/D8（设计 §2.3-1 最高优先级——create_execution 前查，
    误判宁可拒绝不可重跑，防重复内容 + 双倍费用）。
    """


class BookService:
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
    ) -> None:
        self._repo = repo
        self._writer_factory = writer_factory
        self._draft_service = draft_service
        self._outline_repo = outline_repo
        self._limits = limits
        self._content_checker = content_checker
        self._project_config_getter = project_config_getter

    async def write_book(
        self, plan_id: uuid.UUID, limits: BookLimits | None = None
    ) -> dict[str, str]:
        """启动书级运行（202 语义）→ {run_id, status}（阶段 2 顺序派发）.

        limits 解析链（§2.4/D11 Q2=C）：默认 BookLimits() → 项目级
        ProjectConfig.extra（book_max_* 键）→ 请求显式字段（model_fields_set）
        → validate_at_least_one_hard_limit（全无护栏 → ValueError）.
        「内容已写」安全闸（§5.2/D8）先于一切执行：任一目标章执行已完成或
        已有内容 → ChapterAlreadyWrittenError，一个章都不委托.
        顺序派发：每章 in_progress 落库 → 委托 → done/failed 落库；
        硬护栏（章数/调用数）超限 → 剩余章 skipped 落库；无章节点 → completed.

        Args:
            plan_id: 计划 UUID（run 载体 = WritingPlan）.
            limits: 请求显式上限；None = 回退项目级 extra / 默认常量.

        Returns:
            {"run_id": str(plan.id), "status": "completed"}.

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
        for chapter in chapters:
            done_count = sum(1 for v in plan.progress.values() if v == "done")
            if (
                done_count >= merged.max_chapters
                or len(plan.execution_refs) >= merged.max_agent_calls
            ):
                plan.progress[str(chapter.id)] = "skipped"
                await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
                    plan
                )
                continue
            plan.progress[str(chapter.id)] = "in_progress"
            await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
                plan
            )
            try:
                execution_id = await self._delegate_chapter(plan, chapter, merged)
                plan.progress[str(chapter.id)] = "done"
                plan.execution_refs[str(chapter.id)] = execution_id
            except Exception:
                plan.progress[str(chapter.id)] = "failed"
            await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
                plan
            )
        plan.status = "completed"
        await self._repo.update_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_writing_plan
            plan
        )
        return {"run_id": str(plan.id), "status": "completed"}

    async def get_status(self, run_id: str) -> dict[str, Any] | None:
        """书级运行状态（进度树 + 计数器）→ None = run 不存在.

        Args:
            run_id: 书级运行 id（= WritingPlan.id 字符串）.

        Returns:
            {run_id, status, progress, counters}；
            counters = {max_chapters, max_agent_calls, max_tokens, tokens_used,
            tokens_warning, agent_calls, chapters_written}.
        """
        plan = await self._repo.get_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_writing_plan
            run_id
        )
        if plan is None:
            return None
        return {
            "run_id": run_id,
            "status": plan.status,
            "progress": plan.progress,
            "counters": {
                "max_chapters": plan.limits.get("max_chapters", 1),
                "max_agent_calls": plan.limits.get("max_agent_calls", 1),
                "max_tokens": plan.limits.get("max_tokens", 200_000),
                "tokens_used": plan.limits.get("tokens_used", 0),
                "tokens_warning": plan.limits.get("tokens_warning", False),
                "agent_calls": len(plan.execution_refs),
                "chapters_written": sum(1 for v in plan.progress.values() if v == "done"),
            },
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
        tokens = result.get("usage", {}).get("total_tokens", 0)
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
