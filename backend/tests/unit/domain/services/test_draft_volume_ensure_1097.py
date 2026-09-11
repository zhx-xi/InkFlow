"""#1097 RED 契约 — confirm D4 自动建章「按卷大纲 ensure 卷 + 章节归卷」（领域面）.

根因（数据面实证）: book 轨写完 10 章 → GET /volumes n=0、10/10 章 volume_id=None，
但大纲树完整（overall → 第一卷·蜀山重立 → 第1..10章）。断链点 =
`draft_service.confirm` 的 D4 自动建章分支只透传 `draft.volume_id`（book 轨恒 None，
因卷 outline 节点的 `OutlineORM.volume_id` 列未写）→ 建章 volume_id=None。

GREEN 必实现（父侧定稿契约）:
- `DraftService.__init__` 增可选注入 `volume_ensurer`：
  `Callable[[uuid.UUID, uuid.UUID], Awaitable[uuid.UUID | None]]`
  （project_id, chapter_outline_id）→ 卷 UUID 或 None（弱依赖，永不抛错）。
- confirm D4 自动建章分支：`draft.volume_id` 为空且 `volume_ensurer` 已注入且
  生效来源 outline 非空 → 调 `volume_ensurer(draft.project_id, effective_source)`
  取卷 UUID（None = 无卷父，保持 None 不臆造），结果透传 `create_chapter(volume_id=...)`。
- `draft.volume_id` 非空时不调 ensurer（草稿既有绑定优先，零回归）。

铁律: 不 mock 被测服务本体（DraftService 真实构造）；repo/creator/bindder/ensurer
用 AsyncMock。契约文件级 pytestmark 双保险（pyproject asyncio_mode=auto）。
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
VOLUME_OUTLINE_ID = uuid.UUID(int=41)  # 卷大纲节点 id（parent 上溯目标）
CHAPTER_OUTLINE_ID = uuid.UUID(int=51)  # 章大纲节点 id（source_outline_id）
VOLUME_ID = uuid.UUID(int=71)  # ensure 出的卷 UUID
NEW_CHAPTER_ID = uuid.UUID(int=99)  # 自动建章返回的小值 UUID
CONTENT = "第一章正文草稿。这是用于验证 #1097 自动建卷归卷契约的正文内容。"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_draft(**overrides) -> Draft:
    """构造领域 Draft（source_outline_id 已由 #988 提供）。"""
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


def _confirm_deps(
    draft: Draft,
    *,
    volume_id: uuid.UUID | None,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """构造 confirm 流 mock 依赖（自动建章路径）：repo/chapter_service/creator/ensurer.

    volume_id = ensurer 返回值（None = 无卷父）。bindder 缺省不注入（#994 面
    由 test_draft_source_outline_988.py 锁定；本文件聚焦卷面）。
    """
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
    ensurer = AsyncMock(return_value=volume_id)
    return repo, chapter_service, creator, ensurer


# ── 契约 A: 建卷 + 归卷（有卷父） ──────────────────────────────


async def test_confirm_ensures_volume_and_assigns_to_new_chapter():
    """【R】有卷父 → ensurer 被调 (project_id, source_outline_id)，建章带 volume_id.

    当前 __init__ 无 volume_ensurer 形参 → TypeError（RED）。
    GREEN: ensurer 收到 (draft.project_id, effective_source)，卷 UUID 透传 create_chapter。
    """
    from inkflow.domain.services.draft_service import DraftService

    draft = _make_draft(source_outline_id=CHAPTER_OUTLINE_ID)
    repo, chapter_service, creator, ensurer = _confirm_deps(draft, volume_id=VOLUME_ID)
    svc = DraftService(
        draft_repo=repo,
        chapter_service=chapter_service,
        chapter_creator=creator,
        volume_ensurer=ensurer,
    )

    await svc.confirm("draft-1")

    ensurer.assert_awaited_once_with(PROJECT_ID, CHAPTER_OUTLINE_ID)
    assert creator.create_chapter.await_args.kwargs["volume_id"] == VOLUME_ID


async def test_confirm_explicit_source_outline_drives_volume_ensure():
    """【R】显式 source_outline_id 参数优先驱动卷解析（D4 生效值口径一致）.

    显式参数 > 草稿自取（#988 既有语义）在卷面同样成立：ensurer 收显式参数。
    """
    from inkflow.domain.services.draft_service import DraftService

    draft = _make_draft(source_outline_id=uuid.UUID(int=50))
    repo, chapter_service, creator, ensurer = _confirm_deps(draft, volume_id=VOLUME_ID)
    svc = DraftService(
        draft_repo=repo,
        chapter_service=chapter_service,
        chapter_creator=creator,
        volume_ensurer=ensurer,
    )

    await svc.confirm("draft-1", source_outline_id=CHAPTER_OUTLINE_ID)

    ensurer.assert_awaited_once_with(PROJECT_ID, CHAPTER_OUTLINE_ID)
    assert creator.create_chapter.await_args.kwargs["volume_id"] == VOLUME_ID


# ── 契约 B: 幂等 / 多章同卷 ────────────────────────────────────


async def test_confirm_repeated_same_volume_reuses_same_volume_id():
    """【R】多章同卷（重复 confirm 同卷父）→ 建章落同一卷 UUID（幂等复用）.

    幂等由 ensurer 保证（同项目同名复用），service 侧只透传其返回值；
    两次 confirm 结果的 volume_id 必须一致（不得各自新建卷）。
    """
    from inkflow.domain.services.draft_service import DraftService

    seen: list[uuid.UUID] = []
    for n in (1, 2):
        draft = _make_draft(id=f"draft-{n}", source_outline_id=CHAPTER_OUTLINE_ID)
        repo, chapter_service, creator, ensurer = _confirm_deps(draft, volume_id=VOLUME_ID)
        svc = DraftService(
            draft_repo=repo,
            chapter_service=chapter_service,
            chapter_creator=creator,
            volume_ensurer=ensurer,
        )

        await svc.confirm(f"draft-{n}")

        seen.append(creator.create_chapter.await_args.kwargs["volume_id"])

    assert seen == [VOLUME_ID, VOLUME_ID]


# ── 契约 C: 无卷父（不臆造） ───────────────────────────────────


async def test_confirm_no_volume_parent_keeps_none():
    """【G】无卷父（ensurer 返回 None）→ 建章 volume_id=None（不臆造卷）.

    书级/总纲下直挂章是合法旧形态（F43 P3 前孤立章）；ensurer 返回 None
    必须透传 None，绝不兜底建「未命名卷」。
    """
    from inkflow.domain.services.draft_service import DraftService

    draft = _make_draft(source_outline_id=CHAPTER_OUTLINE_ID)
    repo, chapter_service, creator, ensurer = _confirm_deps(draft, volume_id=None)
    svc = DraftService(
        draft_repo=repo,
        chapter_service=chapter_service,
        chapter_creator=creator,
        volume_ensurer=ensurer,
    )

    await svc.confirm("draft-1")

    assert creator.create_chapter.await_args.kwargs["volume_id"] is None


async def test_confirm_no_source_outline_does_not_call_ensurer():
    """【G】无来源 outline（chat 轨）→ 不调 ensurer，建章 volume_id=None.

    无锚点即无卷解析依据；当前语义（volume_id=draft.volume_id=None）必须保持。
    """
    from inkflow.domain.services.draft_service import DraftService

    draft = _make_draft()
    repo, chapter_service, creator, ensurer = _confirm_deps(draft, volume_id=VOLUME_ID)
    svc = DraftService(
        draft_repo=repo,
        chapter_service=chapter_service,
        chapter_creator=creator,
        volume_ensurer=ensurer,
    )

    await svc.confirm("draft-1")

    ensurer.assert_not_awaited()
    assert creator.create_chapter.await_args.kwargs["volume_id"] is None


# ── 契约 D: 零回归守护（既有绑定优先 / 未注入兜底） ────────────


async def test_confirm_draft_volume_binding_skips_ensurer():
    """【G】草稿已有 volume_id → 不调 ensurer，沿用草稿绑定（零回归）.

    book 轨 #976 已解析出卷并落草稿时，不得被 outline 反查覆盖（草稿绑定
    是更精确的 per-draft 事实）。
    """
    from inkflow.domain.services.draft_service import DraftService

    draft = _make_draft(
        source_outline_id=CHAPTER_OUTLINE_ID,
        volume_id=VOLUME_ID,
    )
    repo, chapter_service, creator, ensurer = _confirm_deps(draft, volume_id=uuid.UUID(int=72))
    svc = DraftService(
        draft_repo=repo,
        chapter_service=chapter_service,
        chapter_creator=creator,
        volume_ensurer=ensurer,
    )

    await svc.confirm("draft-1")

    ensurer.assert_not_awaited()
    assert creator.create_chapter.await_args.kwargs["volume_id"] == VOLUME_ID


async def test_confirm_without_ensurer_injected_unchanged():
    """【G】未注入 volume_ensurer → 用 draft.volume_id（既有装配零回归）.

    镜像 #988 的「未注入即不触发」契约：CLI/测试等轻装配路径不得因本批变红。
    """
    from inkflow.domain.services.draft_service import DraftService

    draft = _make_draft(source_outline_id=CHAPTER_OUTLINE_ID)
    repo, chapter_service, creator, ensurer = _confirm_deps(draft, volume_id=VOLUME_ID)
    svc = DraftService(
        draft_repo=repo,
        chapter_service=chapter_service,
        chapter_creator=creator,
    )

    await svc.confirm("draft-1")

    ensurer.assert_not_awaited()
    assert creator.create_chapter.await_args.kwargs["volume_id"] is None


# ── 契约 E: #994 回填面不回归（同批共存） ─────────────────────


async def test_confirm_994_outline_binding_still_fires_with_volume_ensure():
    """【R】#994 回填 + #1097 建卷同轮共存（两回调互不吞并）.

    同一次 confirm 自动建章：outline_bindder 收 (outline, chapter)，
    volume_ensurer 收 (project, outline) —— 双双触达，#994 断言不回归。
    """
    from inkflow.domain.services.draft_service import DraftService

    draft = _make_draft(source_outline_id=CHAPTER_OUTLINE_ID)
    repo, chapter_service, creator, ensurer = _confirm_deps(draft, volume_id=VOLUME_ID)
    bindder = AsyncMock()
    svc = DraftService(
        draft_repo=repo,
        chapter_service=chapter_service,
        chapter_creator=creator,
        outline_bindder=bindder,
        volume_ensurer=ensurer,
    )

    await svc.confirm("draft-1")

    bindder.assert_awaited_once_with(str(CHAPTER_OUTLINE_ID), str(NEW_CHAPTER_ID))
    ensurer.assert_awaited_once_with(PROJECT_ID, CHAPTER_OUTLINE_ID)
