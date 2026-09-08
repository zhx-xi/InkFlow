"""#1001 RED 契约 — OutlineService 章级大纲 ↔ 章节自动关联（领域面）.

契约依据: specs/f11-outline/spec.md §16.2（`auto_link_chapter` /
`auto_link_chapter_by_title`）。当前实现不存在 → 用例首步 AttributeError（RED）。

铁律:
- 不 mock 被测服务本体；仓储用 AsyncMock(spec=Protocol)（先例 test_outline_service.py）。
- 不新增字段/实体（复用 outlines.chapter_id）。
- 「同名多条」为防御分支：DB 层 uq_outlines_active_name 保证活动行同名唯一，
  真库不可构造 → 本文件用 Mock 直证不自动改。
- **#999 形态不对称**（本契约的实测根因）：章标题按 `fmt=None` 落库（`第一章 启程`），
  章级大纲名按项目已选格式归一（默认 arabic → `第1章 启程`）→ 反查必须按
  「原样 / arabic / chinese」三种候选形态逐一点查（`get_by_name`）后去重取唯一命中。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.outline import Outline
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.services.outline_service import OutlineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PID_OTHER = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
OUTLINE_UUID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000a1")
CHAPTER_UUID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000b1")
OTHER_CHAPTER_UUID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000b2")
TS = datetime(2026, 9, 9, 10, 0, 0)
TITLE = "第一章 启程"
TITLE_ARABIC = "第1章 启程"


def _outline(
    *,
    name: str = TITLE,
    level: str = "chapter",
    chapter_id: uuid.UUID | None = None,
    project_id: uuid.UUID = PID,
) -> Outline:
    """构造测试用大纲实体（#1001 只关心 level / chapter_id / project_id）。"""
    return Outline(
        id=OUTLINE_UUID,
        project_id=project_id,
        name=name,
        description="",
        sort_order=0,
        level=level,
        chapter_id=chapter_id,
        created_at=TS,
        updated_at=TS,
    )


def _chapter(
    *,
    project_id: uuid.UUID = PID,
    chapter_id: uuid.UUID = CHAPTER_UUID,
    title: str = TITLE,
) -> Chapter:
    """构造测试用章节实体。"""
    return Chapter(
        id=chapter_id,
        project_id=project_id,
        title=title,
        content="",
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock OutlineRepositoryProtocol（默认 get/get_by_name=None / list=空）。"""
    repo = MagicMock(spec=OutlineRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.update = AsyncMock(side_effect=lambda o: o)
    return repo


@pytest.fixture
def mock_chapter_repo() -> MagicMock:
    """Mock ChapterRepositoryProtocol（默认章存在且同项目）。"""
    repo = MagicMock(spec=ChapterRepositoryProtocol)
    repo.get_chapter = AsyncMock(return_value=_chapter())
    return repo


@pytest.fixture
def service(mock_repo: MagicMock, mock_chapter_repo: MagicMock) -> OutlineService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return OutlineService(repository=mock_repo, chapter_repo=mock_chapter_repo)


class TestAutoLinkChapterDirect:
    """§16.2 auto_link_chapter(outline_id, chapter_id) -> bool。"""

    async def test_binds_when_chapter_id_empty(self, service, mock_repo) -> None:
        """【R】章级大纲 chapter_id 为空 → 写入并返回 True。"""
        mock_repo.get = AsyncMock(return_value=_outline(chapter_id=None))
        linked = await service.auto_link_chapter(OUTLINE_UUID, CHAPTER_UUID)
        assert linked is True
        updated = mock_repo.update.await_args.args[0]
        assert isinstance(updated, Outline)
        assert updated.chapter_id == CHAPTER_UUID

    async def test_rejects_non_chapter_level(self, service, mock_repo) -> None:
        """【R】level != chapter（卷纲/总纲）→ 不写、返回 False。"""
        mock_repo.get = AsyncMock(return_value=_outline(level="volume"))
        assert await service.auto_link_chapter(OUTLINE_UUID, CHAPTER_UUID) is False
        mock_repo.update.assert_not_awaited()

    async def test_returns_false_when_outline_missing(self, service, mock_repo) -> None:
        """【R】大纲不存在 → False（不抛错，镜像 make_outline_bindder 静默防御）。"""
        mock_repo.get = AsyncMock(return_value=None)
        assert await service.auto_link_chapter(OUTLINE_UUID, CHAPTER_UUID) is False
        mock_repo.update.assert_not_awaited()

    async def test_idempotent_when_already_bound_to_same_chapter(
        self, service, mock_repo
    ) -> None:
        """【R】已绑定同一章（重复写入）→ 不重复写、返回 False（幂等）。"""
        mock_repo.get = AsyncMock(return_value=_outline(chapter_id=CHAPTER_UUID))
        assert await service.auto_link_chapter(OUTLINE_UUID, CHAPTER_UUID) is False
        mock_repo.update.assert_not_awaited()

    async def test_does_not_overwrite_existing_other_binding(
        self, service, mock_repo
    ) -> None:
        """【R】已绑定到别的章 → 不覆盖（不静默改错，保留手动兜底）。"""
        mock_repo.get = AsyncMock(return_value=_outline(chapter_id=OTHER_CHAPTER_UUID))
        assert await service.auto_link_chapter(OUTLINE_UUID, CHAPTER_UUID) is False
        mock_repo.update.assert_not_awaited()

    async def test_rejects_chapter_from_other_project(
        self, service, mock_repo, mock_chapter_repo
    ) -> None:
        """【R】目标章属于别的项目 → 不写（跨项目防御）。"""
        mock_repo.get = AsyncMock(return_value=_outline())
        mock_chapter_repo.get_chapter = AsyncMock(
            return_value=_chapter(project_id=PID_OTHER)
        )
        assert await service.auto_link_chapter(OUTLINE_UUID, CHAPTER_UUID) is False
        mock_repo.update.assert_not_awaited()

    async def test_rejects_missing_chapter_row(
        self, service, mock_repo, mock_chapter_repo
    ) -> None:
        """【R】目标章行不存在 → 不写。"""
        mock_repo.get = AsyncMock(return_value=_outline())
        mock_chapter_repo.get_chapter = AsyncMock(return_value=None)
        assert await service.auto_link_chapter(OUTLINE_UUID, CHAPTER_UUID) is False
        mock_repo.update.assert_not_awaited()

    async def test_binds_without_chapter_repo(self, mock_repo) -> None:
        """【R】未注入 chapter_repo → 跳过存在性校验，仍可绑定（向后兼容）。"""
        mock_repo.get = AsyncMock(return_value=_outline())
        svc = OutlineService(repository=mock_repo, chapter_repo=None)
        assert await svc.auto_link_chapter(OUTLINE_UUID, CHAPTER_UUID) is True
        assert mock_repo.update.await_args.args[0].chapter_id == CHAPTER_UUID


class TestAutoLinkChapterByTitle:
    """§16.2 auto_link_chapter_by_title(project_id, chapter_id, title)。"""

    async def test_unique_hit_across_numbering_forms_binds(
        self, service, mock_repo
    ) -> None:
        """【R】#999 形态不对称：大纲名 arabic / 章标题 chinese → 仍唯一命中回填。"""
        target = _outline(name=TITLE_ARABIC, chapter_id=None)
        mock_repo.get_by_name = AsyncMock(return_value=target)
        mock_repo.get = AsyncMock(return_value=target)

        linked_id = await service.auto_link_chapter_by_title(PID, CHAPTER_UUID, TITLE)

        assert linked_id == OUTLINE_UUID
        assert mock_repo.update.await_args.args[0].chapter_id == CHAPTER_UUID
        probed = {call.args[1] for call in mock_repo.get_by_name.await_args_list}
        assert probed == {TITLE, TITLE_ARABIC}

    async def test_returns_none_when_no_candidate_hit(self, service, mock_repo) -> None:
        """【R】三种候选形态全无命中 → None，不写。"""
        mock_repo.get_by_name = AsyncMock(return_value=None)
        assert await service.auto_link_chapter_by_title(PID, CHAPTER_UUID, TITLE) is None
        mock_repo.update.assert_not_awaited()

    async def test_returns_none_on_duplicate_canonical_names(
        self, service, mock_repo
    ) -> None:
        """【R】候选形态命中到不同大纲（多义）→ 不自动改（保留手动「关联章节」兜底）。"""
        arabic = _outline(name=TITLE_ARABIC)
        chinese = _outline(name=TITLE)
        chinese.id = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000a2")

        async def _by_name(project_id: int, name: str) -> Outline | None:
            return {TITLE_ARABIC: arabic, TITLE: chinese}.get(name)

        mock_repo.get_by_name = AsyncMock(side_effect=_by_name)
        assert await service.auto_link_chapter_by_title(PID, CHAPTER_UUID, TITLE) is None
        mock_repo.update.assert_not_awaited()

    async def test_ignores_non_chapter_level_same_name(self, service, mock_repo) -> None:
        """【R】同名但 level != chapter → 不绑。"""
        mock_repo.get_by_name = AsyncMock(return_value=_outline(level="overall"))
        assert await service.auto_link_chapter_by_title(PID, CHAPTER_UUID, TITLE) is None
        mock_repo.update.assert_not_awaited()

    async def test_ignores_no_exact_match(self, service, mock_repo) -> None:
        """【R】名称只是近似（候选形态均无精确行）→ 不绑。"""
        mock_repo.get_by_name = AsyncMock(
            return_value=_outline(name=f"{TITLE}（上）")
        )
        assert await service.auto_link_chapter_by_title(PID, CHAPTER_UUID, TITLE) is None
        mock_repo.update.assert_not_awaited()

    async def test_blank_title_short_circuits(self, service, mock_repo) -> None:
        """【R】空白标题 → None 且不查库。"""
        assert await service.auto_link_chapter_by_title(PID, CHAPTER_UUID, "   ") is None
        mock_repo.get_by_name.assert_not_awaited()

    async def test_returns_none_when_target_already_bound(
        self, service, mock_repo
    ) -> None:
        """【R】唯一命中但已绑定别的章 → 不覆盖，返回 None。"""
        bound = _outline(name=TITLE_ARABIC, chapter_id=OTHER_CHAPTER_UUID)
        mock_repo.get_by_name = AsyncMock(return_value=bound)
        mock_repo.get = AsyncMock(return_value=bound)
        assert await service.auto_link_chapter_by_title(PID, CHAPTER_UUID, TITLE) is None
        mock_repo.update.assert_not_awaited()
