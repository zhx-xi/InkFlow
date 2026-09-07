"""#988 草稿来源大纲节点绑定 — Draft 模型字段 + DraftService create/confirm RED 契约.

被测模块（当前未实现，对照 origin/main 13b1305 实现全部【R】）:
- Draft 模型无 source_outline_id 字段（domain/models/draft.py:35-61）——Pydantic
  v2 默认 extra=ignore 静默丢弃构造键 → model_dump 无该键 → 断言 FAIL（RED）
- DraftService.create 不接收 source_outline_id 形参（draft_service.py:73-120）
  → svc.create(source_outline_id=...) TypeError（RED）
- DraftService.confirm 不草稿自取（draft_service.py:229-235 D4 仅显式参数）
  → 记录过来源的草稿 confirm 无参 → outline_bindder 不触达（RED）

GREEN 必实现（父侧定稿契约）:
- Draft 增 source_outline_id: uuid.UUID | None = None（来源大纲章节点），
  model_dump(mode="json") 随 list/confirm 响应暴露
- DraftService.create(*, project_id, chapter_id=None, content, summary="",
  agent_run_id=None, volume_id=None, source_outline_id=None) → 透传 repo.create
- DraftService.confirm 生效值优先级: 显式 source_outline_id 参数 >
  draft.source_outline_id（草稿自取）> None（D4 不触发，既有语义零回归）

asyncio 模式: pyproject asyncio_mode = "auto"；文件级 pytestmark 双保险。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.draft import Draft, DraftStatus

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
OUTLINE_ID = uuid.UUID(int=51)  # 小值 UUID（int↔UUID 惯例，镜像 976/988 先例）
NEW_CHAPTER_ID = uuid.UUID(int=99)  # 自动建章返回的小值 UUID
CONTENT = "第一章正文草稿。这是用于验证 source_outline_id 契约的正文内容。"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_draft(**overrides) -> Draft:
    """构造领域 Draft（当前无 source_outline_id 字段，extra=ignore 静默丢弃；GREEN 后保留）。"""
    kwargs: dict = dict(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=None,
        content=CONTENT,
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
        confirmed_at=None,
    )
    kwargs.update(overrides)
    return Draft(**kwargs)


# ── 契约 B1: Draft 模型字段 + 序列化暴露 ──────────────────────────


async def test_draft_model_source_outline_id_default_none():
    """【R】Draft 无显式 source_outline_id → 属性存在且为 None.

    当前模型无该字段 → AttributeError（RED）。GREEN: 字段默认 None。
    """
    draft = _make_draft()

    assert draft.source_outline_id is None


async def test_draft_model_source_outline_id_serialized():
    """【R】model_dump(mode="json") 暴露 source_outline_id（响应 DTO 契约）.

    当前 extra=ignore 静默丢弃 → dump 无该键 → KeyError（RED）。
    """
    draft = _make_draft(source_outline_id=OUTLINE_ID)

    dumped = draft.model_dump(mode="json")

    assert "source_outline_id" in dumped
    assert dumped["source_outline_id"] == str(OUTLINE_ID)


# ── 契约 B2: DraftService.create 透传 repo ────────────────────────


async def test_draft_service_create_passes_source_outline_id_to_repo():
    """【R】DraftService.create(source_outline_id=X) → repo.create 收到该 kwarg.

    当前 create 无 source_outline_id 形参 → TypeError（RED）。
    """
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    repo.create.return_value = _make_draft(source_outline_id=OUTLINE_ID)
    svc = DraftService(draft_repo=repo)

    await svc.create(
        project_id=PROJECT_ID,
        chapter_id=None,
        content=CONTENT,
        source_outline_id=OUTLINE_ID,
    )

    assert repo.create.await_args.kwargs["source_outline_id"] == OUTLINE_ID


async def test_draft_service_create_without_source_outline_id():
    """【R→G】不传 source_outline_id → repo.create 收到 None（既有调用零回归守护）.

    当前 create(source_outline_id=None) 直接 TypeError → RED；GREEN 后该形参
    默认 None 并透传，用例转 PASS。
    """
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    repo.create.return_value = _make_draft()
    svc = DraftService(draft_repo=repo)

    await svc.create(project_id=PROJECT_ID, content=CONTENT)

    assert repo.create.await_args.kwargs["source_outline_id"] is None


# ── 契约 B3: confirm 生效值优先级 ────────────────────────────────


def _confirm_deps(draft: Draft) -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """构造 confirm 流 mock 依赖（自动建章路径）：repo/chapter_service/creator/bindder."""
    repo = AsyncMock()
    repo.get.return_value = draft
    confirmed = draft.model_copy(
        update={
            "status": DraftStatus.CONFIRMED,
            "confirmed_at": _utcnow(),
            "chapter_id": NEW_CHAPTER_ID,
        }
    )
    repo.update_status.return_value = confirmed
    chapter_service = AsyncMock()
    creator = AsyncMock()
    creator.create_chapter.return_value = SimpleNamespace(id=NEW_CHAPTER_ID)
    bindder = AsyncMock()
    return repo, chapter_service, creator, bindder


async def test_confirm_draft_self_fetch_source_outline_id():
    """【R】草稿记录了 source_outline_id → confirm 无显式参数仍回填（自取闭环）.

    chat/book 轨创建时已记录的草稿，确认方（CLI/GUI 不重复上传）也必须触发 D4，
    否则「创建时记录」全程空转。当前 confirm 仅认显式参数 → bindder 不触达（RED）。
    """
    from inkflow.domain.services.draft_service import DraftService

    draft = _make_draft(source_outline_id=OUTLINE_ID)
    repo, chapter_service, creator, bindder = _confirm_deps(draft)
    svc = DraftService(
        draft_repo=repo,
        chapter_service=chapter_service,
        chapter_creator=creator,
        outline_bindder=bindder,
    )

    await svc.confirm("draft-1")

    bindder.assert_awaited_once_with(str(OUTLINE_ID), str(NEW_CHAPTER_ID))


async def test_confirm_explicit_param_overrides_draft_field():
    """【G】显式 source_outline_id 参数优先于草稿记录值（既有 D4 语义守护）.

    当前实现即成立（显式参数即 D4 现行通道）→ RED 期 PASS 刻意，防 GREEN 回归。
    """
    from inkflow.domain.services.draft_service import DraftService

    draft = _make_draft(source_outline_id=uuid.UUID(int=50))
    repo, chapter_service, creator, bindder = _confirm_deps(draft)
    svc = DraftService(
        draft_repo=repo,
        chapter_service=chapter_service,
        chapter_creator=creator,
        outline_bindder=bindder,
    )

    await svc.confirm("draft-1", source_outline_id=OUTLINE_ID)

    bindder.assert_awaited_once_with(str(OUTLINE_ID), str(NEW_CHAPTER_ID))


async def test_confirm_bound_draft_with_source_outline_id_skips_binding():
    """【G】已绑章草稿带 source_outline_id → 不自动建章，bindder 不触达.

    D4 语义不变：回填只发生在「自动建章」路径（new_chapter_id 非 None）。
    当前实现即成立 → RED 期 PASS 刻意。
    """
    from inkflow.domain.services.draft_service import DraftService

    bound = _make_draft(chapter_id=NEW_CHAPTER_ID, source_outline_id=OUTLINE_ID)
    repo, chapter_service, creator, bindder = _confirm_deps(bound)
    svc = DraftService(
        draft_repo=repo,
        chapter_service=chapter_service,
        chapter_creator=creator,
        outline_bindder=bindder,
    )

    await svc.confirm("draft-1")

    creator.create_chapter.assert_not_awaited()
    bindder.assert_not_awaited()


async def test_confirm_no_source_outline_id_anywhere_unchanged():
    """【G】显式与草稿记录皆无 → 自动建章但 bindder 不触达（现状语义守护）.

    当前实现即成立 → RED 期 PASS 刻意（chat 轨未回填草稿的 fallback 前形态）。
    """
    from inkflow.domain.services.draft_service import DraftService

    draft = _make_draft()
    repo, chapter_service, creator, bindder = _confirm_deps(draft)
    svc = DraftService(
        draft_repo=repo,
        chapter_service=chapter_service,
        chapter_creator=creator,
        outline_bindder=bindder,
    )

    await svc.confirm("draft-1")

    creator.create_chapter.assert_awaited_once()
    bindder.assert_not_awaited()
