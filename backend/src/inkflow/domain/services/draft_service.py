"""F27 草稿服务——落库/确认/拒绝/列表（spec §5.2/§5.3，ADR-F 约束①②）.

DraftService 是 Agentic 写作闭环的草稿保存区服务：
- create: 落库草稿（status=DRAFT），单次 commit = 单工具单事务（ADR-F 约束②），写操作落审计
- confirm: 确认流——内容写入目标章节 + chapter status 置 FINAL（spec §2.4/§5.2 约束④），
  draft 状态置 CONFIRMED 并回填 confirmed_at
- reject: 拒绝流——draft 状态置 REJECTED（保留记录，供 F28 分析）
- update: F28 编辑流——确认前手动修改正文（update_content 落库），
  经可选注入的 memory_service 捕获 diff 事件（memory_learning 开启时），
  last_learned 透传本次编辑是否触发新偏好落库

仅依赖 domain/models 与注入的 repo/service（鸭子类型，不感知 ORM/框架），
domain/ 零框架 import 门禁天然满足（ADR-002/015）。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import cast

from inkflow.domain.models.chapter import ChapterStatus, ChapterUpdate
from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.domain.services._word_count import count_words

_ZERO_PROJECT_ID = uuid.UUID(int=0)


class DraftNotFoundError(Exception):
    """草稿不存在（API 映射 404）。"""

    def __init__(self, message: str = "草稿不存在") -> None:
        super().__init__(message)


class DraftStateError(Exception):
    """草稿状态不允许该操作（API 映射 409，如重复确认）。"""

    def __init__(self, message: str = "草稿状态不允许该操作") -> None:
        super().__init__(message)


class DraftService:
    """草稿服务——落库/确认/拒绝/列表（调 repo 不碰 ORM，ADR-F 约束①）.

    Args:
        draft_repo: SQLiteDraftRepository（鸭子类型，需 create/get/list/update_status）.
        chapter_service: ChapterService（确认流写正式章节用，可空；测试可注入 mock）.
        audit_service: AuditLogService（写操作审计，可空）.
        memory_service: MemoryService（可选注入——F28 diff 事件捕获入口；
            关闭时 memory_service 内部零行为，测试可注入 mock）.
    """

    def __init__(
        self,
        *,
        draft_repo: object,
        chapter_service: object | None = None,
        audit_service: object | None = None,
        memory_service: object | None = None,
        chapter_creator: object | None = None,
        outline_bindder: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._repo = draft_repo
        self._chapter_service = chapter_service
        self._audit_service = audit_service
        self._memory_service = memory_service
        self._chapter_creator = chapter_creator
        self._outline_bindder = outline_bindder
        self.last_learned: bool = False  # F28: 本次 update 是否触发新偏好落库

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
        content: str,
        summary: str = "",
        agent_run_id: str | None = None,
        volume_id: uuid.UUID | None = None,
    ) -> Draft:
        """创建草稿（status=DRAFT），单次 commit = 单工具单事务（ADR-F 约束②），写操作落审计.

        Args:
            project_id: 所属项目 UUID.
            chapter_id: 目标章节 UUID（None = 确认时指定）.
            content: 草稿正文.
            summary: 草稿摘要（默认空）.
            agent_run_id: 产生该草稿的 run id（可空）.
            volume_id: 所属写作卷 UUID（#976，None = 未归卷）.

        Returns:
            已落库的 Draft（id 为 uuid4 字符串）.

        Raises:
            ValueError: project_id 为全零 UUID（#275 孤儿数据签名），或 content strip 后为空.
        """
        if project_id == _ZERO_PROJECT_ID:
            raise ValueError("project_id 不能为全零 UUID（#275 孤儿数据签名）")
        if not content.strip():
            raise ValueError("草稿内容不能为空")
        draft: Draft = await self._repo.create(  # type: ignore[attr-defined]  # 鸭子类型：draft_repo 按契约提供 create
            project_id=project_id,
            chapter_id=chapter_id,
            content=content,
            summary=summary,
            agent_run_id=agent_run_id,
            volume_id=volume_id,
        )
        if self._audit_service is not None:
            await self._audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                actor="agent:writer",
                project_id=project_id,
                chapter_id=chapter_id,
                severity_summary="draft_saved",
                summary=f"草稿保存 {count_words(content)} 字",
                degraded=True,
            )
        return draft

    async def get(self, draft_id: str) -> Draft | None:
        """按草稿 id 查询（uuid4 字符串）；缺失 → None."""
        draft: Draft | None = await self._repo.get(draft_id)  # type: ignore[attr-defined]  # 鸭子类型：draft_repo 按契约提供 get
        return draft

    async def list(
        self,
        project_id: uuid.UUID,
        status: DraftStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Draft], int]:
        """按项目 + 状态分页查询草稿（created_at desc 最新在前）.

        Args:
            project_id: 所属项目 UUID.
            status: 状态精确过滤（不传 = 全部）.
            offset: 分页偏移（默认 0）.
            limit: 每页条数（默认 50）.

        Returns:
            (页内 Draft 列表, 该项目草稿总数).
        """
        result: tuple[list[Draft], int] = await self._repo.list(  # type: ignore[attr-defined]  # 鸭子类型：draft_repo 按契约提供 list
            project_id,
            status=status,
            offset=offset,
            limit=limit,
        )
        return result

    async def confirm(
        self,
        draft_id: str,
        chapter_id: uuid.UUID | None = None,
        *,
        source_outline_id: uuid.UUID | None = None,
        title: str | None = None,
    ) -> Draft:
        """确认草稿——内容写入目标章节 + status 置 FINAL（spec §2.4/§5.2 约束④）.

        Args:
            draft_id: 草稿 id（uuid4 字符串）.
            chapter_id: 目标章节 UUID（草稿未绑定时指定；两者皆无 → DraftStateError）.
            source_outline_id: 来源大纲章节点 UUID（D4：自动建章后回填
                outlines.chapter_id；仅注入 outline_bindder 且草稿未绑定时生效）.
            title: 自动建章标题（D4：显式优先于 summary/content 派生）.

        Returns:
            已确认的 Draft（status=CONFIRMED，confirmed_at 已回填）.

        Raises:
            DraftNotFoundError: 草稿不存在（或确认前被并发删除）.
            DraftStateError: 草稿非 DRAFT 状态（重复确认/已拒绝），或未绑定目标章节
                且未注入 chapter_creator.
        """
        draft = await self._repo.get(draft_id)  # type: ignore[attr-defined]  # 鸭子类型：draft_repo 按契约提供 get
        if draft is None:
            raise DraftNotFoundError("草稿不存在")
        if draft.status != DraftStatus.DRAFT:
            message = "草稿已确认" if draft.status is DraftStatus.CONFIRMED else "草稿已拒绝"
            raise DraftStateError(message)
        target = draft.chapter_id or chapter_id
        new_chapter_id: uuid.UUID | None = None
        if target is None:
            # D4：无目标时若注入了 chapter_creator → 自动建章（草稿卷绑定透传）
            if self._chapter_creator is None:
                raise DraftStateError("草稿未绑定目标章节")
            if title is not None and title.strip():
                chapter_title = title
            else:
                chapter_title = (draft.summary or draft.content).strip()[:30] or "草稿章节"
            create_method = cast(
                Callable[..., Awaitable[object]],
                getattr(self._chapter_creator, "create_chapter", None)
                or self._chapter_creator,
            )
            created = await create_method(
                draft.project_id,
                chapter_title,
                volume_id=draft.volume_id,
                content="",
            )
            created_id = getattr(created, "id", None)
            if created_id is None:
                raise DraftStateError("自动建章失败：未返回章节 id")
            target = (
                created_id
                if isinstance(created_id, uuid.UUID)
                else uuid.UUID(str(created_id))
            )
            new_chapter_id = target
            await self._repo.update_chapter_binding(  # type: ignore[attr-defined]  # 鸭子类型：draft_repo 按 D4 契约提供 update_chapter_binding
                draft_id, target
            )
        if self._chapter_service is not None:
            await self._chapter_service.update_chapter(  # type: ignore[attr-defined]  # 鸭子类型：chapter_service 按契约提供 update_chapter
                target,
                ChapterUpdate(content=draft.content, status=ChapterStatus.FINAL),
            )
        confirmed: Draft | None = await self._repo.update_status(  # type: ignore[attr-defined]  # 鸭子类型：draft_repo 按契约提供 update_status
            draft_id,
            DraftStatus.CONFIRMED,
            confirmed_at=datetime.now(UTC),
        )
        if confirmed is None:
            raise DraftNotFoundError("草稿不存在")  # 竞态防御：确认前被删除
        if (
            self._outline_bindder is not None
            and source_outline_id is not None
            and new_chapter_id is not None
        ):
            # D4：自动建章后回填 outlines.chapter_id（仅调用方显式传 source_outline_id）
            await self._outline_bindder(str(source_outline_id), str(new_chapter_id))
        if self._audit_service is not None:
            await self._audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                actor="agent:writer",
                project_id=draft.project_id,
                chapter_id=target,
                severity_summary="draft_confirmed",
                degraded=True,
            )
        return confirmed

    async def reject(self, draft_id: str) -> Draft:
        """拒绝草稿——状态置 REJECTED（保留记录，供 F28 分析）.

        Args:
            draft_id: 草稿 id（uuid4 字符串）.

        Returns:
            已拒绝的 Draft（status=REJECTED）.

        Raises:
            DraftNotFoundError: 草稿不存在（或拒绝前被并发删除）.
            DraftStateError: 草稿非 DRAFT 状态（重复操作）.
        """
        draft = await self._repo.get(draft_id)  # type: ignore[attr-defined]  # 鸭子类型：draft_repo 按契约提供 get
        if draft is None:
            raise DraftNotFoundError("草稿不存在")
        if draft.status != DraftStatus.DRAFT:
            message = "草稿已确认" if draft.status is DraftStatus.CONFIRMED else "草稿已拒绝"
            raise DraftStateError(message)
        rejected: Draft | None = await self._repo.update_status(  # type: ignore[attr-defined]  # 鸭子类型：draft_repo 按契约提供 update_status
            draft_id,
            DraftStatus.REJECTED,
        )
        if rejected is None:
            raise DraftNotFoundError("草稿不存在")  # 竞态防御：拒绝前被删除
        if self._audit_service is not None:
            await self._audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                actor="agent:writer",
                project_id=draft.project_id,
                chapter_id=draft.chapter_id,
                severity_summary="draft_rejected",
                degraded=True,
            )
        return rejected

    async def update(self, draft_id: str, content: str) -> Draft:
        """编辑草稿正文（确认前手动修改；F28 diff 事件捕获入口）.

        Raises:
            DraftNotFoundError: 草稿不存在.
            DraftStateError: 草稿非 DRAFT 状态（confirmed/rejected 不可编辑）.
            ValueError: content strip 后为空.
        """
        if not content.strip():
            raise ValueError("草稿内容不能为空")
        draft = await self._repo.get(draft_id)  # type: ignore[attr-defined]  # 鸭子类型：draft_repo 按契约提供 get
        if draft is None:
            raise DraftNotFoundError("草稿不存在")
        if draft.status != DraftStatus.DRAFT:
            message = "草稿已确认" if draft.status is DraftStatus.CONFIRMED else "草稿已拒绝"
            raise DraftStateError(message)
        updated: Draft | None = await self._repo.update_content(  # type: ignore[attr-defined]  # 鸭子类型：draft_repo 按契约提供 update_content；注解收窄 Any（镜像 confirm 写法）
            draft_id, content
        )
        if updated is None:
            raise DraftNotFoundError("草稿不存在")
        # F28 事件捕获（可选注入；关闭时 memory_service 内部零行为）
        if self._memory_service is not None:
            await self._memory_service.record_draft_edit(  # type: ignore[attr-defined]  # 鸭子类型：memory_service 按 F28 契约提供 record_draft_edit
                draft_id=draft_id,
                project_id=draft.project_id,
                chapter_id=draft.chapter_id,
                before=draft.content,
                after=content,
                agent_run_id=draft.agent_run_id,
            )
            self.last_learned = bool(getattr(self._memory_service, "last_learned", False))
        return updated

    async def prune_orphans(self, *, dry_run: bool = False) -> int:
        """删除孤儿草稿（project_id=全零 UUID，#275 旧数据清理）→ 删除条数.

        Args:
            dry_run: True = 只统计不删除（清理前预览）.

        Returns:
            匹配的孤儿草稿条数（dry_run=True 时不删除）.
        """
        count: int = await self._repo.prune_orphans(  # type: ignore[attr-defined]  # 鸭子类型：draft_repo 按契约提供 prune_orphans
            dry_run=dry_run
        )
        return count
