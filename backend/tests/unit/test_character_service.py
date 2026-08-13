"""F9 角色服务单元测试 — Mock Repository（F9 M3 RED→GREEN）.

覆盖 spec §9 服务测试 + §7 边界表:
- 创建/更新/真删全流程（Mock Repository）
- 同名活动角色创建 → CharacterNameConflictError（422 语义）
- group_id 跨项目 → GroupNotInProjectError
- 关系自环 / 重复 / 跨项目 → SelfRelationError / RelationConflictError / CrossProjectRelationError
- 角色不存在各操作 → None（router 层转 404；create_relation 抛 CharacterNotFoundError）
- 删除编排（委托 hard_delete / hard_delete_group / hard_delete_relation，关系由 DB FK CASCADE）
- 分组删除 → 成员 group_id 置 NULL 的编排（委托 hard_delete_group）
- extract 入口：校验项目存在 → 调用 CharacterExtractor → 返回 CharacterExtractionResult

依据: specs/f9-character-service/spec.md §7 + §9 测试策略。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.character import (
    Character,
    CharacterExtractionResult,
    CharacterExtractRequest,
    CharacterGroup,
    CharacterRelation,
    CharacterUpdate,
)
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.ports.character_errors import (
    CharacterNameConflictError,
    CharacterNotFoundError,
    CharacterServiceError,
    CrossProjectRelationError,
    GroupNameConflictError,
    GroupNotInProjectError,
    ProjectNotFoundError,
    RelationConflictError,
    SelfRelationError,
)
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.services._character_extractor import CharacterExtractor
from inkflow.domain.services.character_service import CharacterService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PID_OTHER = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _char(
    name: str,
    *,
    personality: str = "",
    background: str = "",
    goals: str = "",
    group_id: uuid.UUID | None = None,
    project_id: uuid.UUID = PID,
) -> Character:
    """构造测试用角色实体（固定时间戳，便于断言）。"""
    return Character(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        personality=personality,
        background=background,
        goals=goals,
        group_id=group_id,
        created_at=TS,
        updated_at=TS,
    )


def _group(name: str, *, project_id: uuid.UUID = PID, sort_order: int = 0) -> CharacterGroup:
    """构造测试用分组实体。"""
    return CharacterGroup(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        sort_order=sort_order,
        created_at=TS,
        updated_at=TS,
    )


def _rel(
    from_char: Character,
    to_char: Character,
    *,
    relation_type: str,
    description: str = "",
) -> CharacterRelation:
    """构造测试用关系实体。"""
    return CharacterRelation(
        id=uuid.uuid4(),
        project_id=from_char.project_id,
        from_character_id=from_char.id,
        to_character_id=to_char.id,
        relation_type=relation_type,
        description=description,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock CharacterRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.add = AsyncMock(side_effect=lambda c: c)
    repo.update = AsyncMock(side_effect=lambda c: c)
    repo.soft_delete = AsyncMock(return_value=True)
    repo.hard_delete = AsyncMock(return_value=True)
    repo.add_group = AsyncMock(side_effect=lambda g: g)
    repo.get_group = AsyncMock(return_value=None)
    repo.list_groups = AsyncMock(return_value=[])
    repo.update_group = AsyncMock(side_effect=lambda g: g)
    repo.soft_delete_group = AsyncMock(return_value=True)
    repo.hard_delete_group = AsyncMock(return_value=True)
    repo.add_relation = AsyncMock(side_effect=lambda r: r)
    repo.get_relation = AsyncMock(return_value=None)
    repo.get_relation_by_key = AsyncMock(return_value=None)
    repo.list_relations = AsyncMock(return_value=[])
    repo.update_relation = AsyncMock(side_effect=lambda r: r)
    repo.soft_delete_relation = AsyncMock(return_value=True)
    repo.hard_delete_relation = AsyncMock(return_value=True)
    repo.soft_delete_relations_of = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — extract 入口校验项目存在性。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_extractor() -> MagicMock:
    """Mock CharacterExtractor — extract 入口的管线调用。"""
    extractor = MagicMock(spec=CharacterExtractor)
    extractor.extract = AsyncMock()
    return extractor


@pytest.fixture
def service(
    mock_repo: MagicMock,
    mock_project_repo: MagicMock,
    mock_extractor: MagicMock,
) -> CharacterService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return CharacterService(
        repository=mock_repo,
        extractor=mock_extractor,
        project_repo=mock_project_repo,
    )


class TestCharacterCrud:
    """角色 CRUD — 创建/查询/更新/真删。"""

    async def test_create_character_success_persists(self, service, mock_repo) -> None:
        """创建角色 → repo.add 收到完整实体（UUID 项目归属、空分组）。"""
        created = await service.create_character(
            project_id=PID, name="林尘", personality="坚韧", background="山村少年", goals="变强"
        )
        assert created.name == "林尘"
        mock_repo.get_by_name.assert_awaited_once_with(PID.int, "林尘")
        added = mock_repo.add.await_args.args[0]
        assert isinstance(added, Character)
        assert added.project_id == PID
        assert added.name == "林尘"
        assert added.personality == "坚韧"
        assert added.background == "山村少年"
        assert added.goals == "变强"
        assert added.group_id is None

    async def test_create_character_duplicate_active_name_raises_conflict(
        self, service, mock_repo
    ) -> None:
        """同名活动角色已存在 → CharacterNameConflictError（422 语义），不落库。"""
        mock_repo.get_by_name = AsyncMock(return_value=_char(name="林尘"))
        with pytest.raises(CharacterNameConflictError):
            await service.create_character(project_id=PID, name="林尘")
        mock_repo.add.assert_not_awaited()

    async def test_create_character_with_group_success(self, service, mock_repo) -> None:
        """分组属于该项目 → 角色归属该分组。"""
        group = _group(name="主角团")
        mock_repo.get_group = AsyncMock(return_value=group)
        created = await service.create_character(project_id=PID, name="林尘", group_id=group.id)
        mock_repo.get_group.assert_awaited_once_with(group.id.int)
        assert created.group_id == group.id

    async def test_create_character_group_not_in_project_raises(self, service, mock_repo) -> None:
        """分组缺失或属于其他项目 → GroupNotInProjectError（422 语义）。"""
        foreign_group = _group(name="敌方分组", project_id=PID_OTHER)
        mock_repo.get_group = AsyncMock(return_value=foreign_group)
        with pytest.raises(GroupNotInProjectError):
            await service.create_character(project_id=PID, name="林尘", group_id=foreign_group.id)
        mock_repo.get_group = AsyncMock(return_value=None)
        with pytest.raises(GroupNotInProjectError):
            await service.create_character(project_id=PID, name="林尘", group_id=uuid.uuid4())
        mock_repo.add.assert_not_awaited()

    async def test_get_character_returns_none_when_missing(self, service, mock_repo) -> None:
        """角色不存在 → None（router 层转 404）；存在 → 返回实体。"""
        char = _char(name="林尘")
        mock_repo.get = AsyncMock(return_value=char)
        result = await service.get_character(char.id)
        assert result == char
        mock_repo.get.assert_awaited_once_with(char.id.int)

        mock_repo.get = AsyncMock(return_value=None)
        assert await service.get_character(uuid.uuid4()) is None

    async def test_list_characters_forwards_filters_and_pagination(
        self, service, mock_repo
    ) -> None:
        """列表查询透传搜索/分组过滤/排序/分页（UUID→int 转换）。"""
        char = _char(name="林尘")
        group = _group(name="主角团")
        mock_repo.list = AsyncMock(return_value=([char], 1))
        items, total = await service.list_characters(
            project_id=PID,
            search="林",
            group_id=group.id,
            sort_by="name",
            sort_desc=False,
            offset=10,
            limit=5,
        )
        assert items == [char]
        assert total == 1
        kwargs = mock_repo.list.await_args.kwargs
        assert kwargs["project_id"] == PID.int
        assert kwargs["search"] == "林"
        assert kwargs["group_id"] == group.id.int
        assert kwargs["sort_by"] == "name"
        assert kwargs["sort_desc"] is False
        assert kwargs["offset"] == 10
        assert kwargs["limit"] == 5

    async def test_update_character_merges_provided_fields(self, service, mock_repo) -> None:
        """部分更新：仅覆盖传入字段；同名自更不冲突；group_id=None 清除分组。"""
        group = _group(name="主角团")
        existing = _char(
            name="林尘",
            personality="旧性格",
            background="旧背景",
            goals="旧目标",
            group_id=group.id,
        )
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_name = AsyncMock(return_value=existing)  # 同名自更 → 不冲突
        mock_repo.update = AsyncMock(side_effect=lambda c: c)

        update = CharacterUpdate(name="林尘", personality="新性格", goals="新目标", group_id=None)
        result = await service.update_character(existing.id, update)

        merged = mock_repo.update.await_args.args[0]
        assert isinstance(merged, Character)
        assert merged.id == existing.id
        assert merged.name == "林尘"
        assert merged.personality == "新性格"
        assert merged.goals == "新目标"
        assert merged.background == "旧背景"  # 未传入字段保持不变
        assert merged.group_id is None  # 显式清除
        assert merged.created_at == TS
        assert result == merged

    async def test_update_character_returns_none_when_missing(self, service, mock_repo) -> None:
        """角色不存在 → None（router 层转 404），不触发仓储更新。"""
        mock_repo.get = AsyncMock(return_value=None)
        result = await service.update_character(uuid.uuid4(), CharacterUpdate(name="林尘"))
        assert result is None
        mock_repo.update.assert_not_awaited()

    async def test_update_character_rename_conflict_raises(self, service, mock_repo) -> None:
        """改名为项目内其他活动角色名 → CharacterNameConflictError（422 语义）。"""
        existing = _char(name="林尘")
        other = _char(name="苏瑶")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_name = AsyncMock(return_value=other)
        with pytest.raises(CharacterNameConflictError):
            await service.update_character(existing.id, CharacterUpdate(name="苏瑶"))
        mock_repo.update.assert_not_awaited()

    async def test_update_character_group_not_in_project_raises(self, service, mock_repo) -> None:
        """更新时分组缺失或属于其他项目 → GroupNotInProjectError（422 语义）。"""
        existing = _char(name="林尘")
        foreign_group = _group(name="敌方分组", project_id=PID_OTHER)
        mock_repo.get = AsyncMock(return_value=existing)

        mock_repo.get_group = AsyncMock(return_value=foreign_group)
        with pytest.raises(GroupNotInProjectError):
            await service.update_character(existing.id, CharacterUpdate(group_id=foreign_group.id))
        mock_repo.get_group = AsyncMock(return_value=None)
        with pytest.raises(GroupNotInProjectError):
            await service.update_character(existing.id, CharacterUpdate(group_id=uuid.uuid4()))
        mock_repo.update.assert_not_awaited()

    async def test_delete_character_hard_deletes(self, service, mock_repo) -> None:
        """真删角色（v1.1）：委托 repo.hard_delete（关系由 DB FK CASCADE）；不存在 → False."""
        char = _char(name="林尘")
        result = await service.delete_character(char.id)
        assert result is True
        mock_repo.hard_delete.assert_awaited_once_with(char.id.int)
        mock_repo.soft_delete.assert_not_awaited()

        mock_repo.hard_delete = AsyncMock(return_value=False)
        assert await service.delete_character(uuid.uuid4()) is False


class TestRelationCrud:
    """角色关系 — 创建（自环/跨项目/重复校验）/双向查询/更新/真删。"""

    async def test_create_relation_success(self, service, mock_repo) -> None:
        """创建关系 → repo.add_relation 收到完整边（from/to/type/description，同项目）。"""
        from_char = _char(name="林尘")
        to_char = _char(name="苏瑶")
        mock_repo.get = AsyncMock(side_effect=[from_char, to_char])
        mock_repo.get_relation_by_key = AsyncMock(return_value=None)

        rel = await service.create_relation(from_char.id, to_char.id, "同伴", "结伴同行")
        assert rel.from_character_id == from_char.id
        assert rel.to_character_id == to_char.id
        assert rel.relation_type == "同伴"
        assert rel.description == "结伴同行"
        mock_repo.get_relation_by_key.assert_awaited_once_with(
            from_char.id.int, to_char.id.int, "同伴"
        )
        added = mock_repo.add_relation.await_args.args[0]
        assert isinstance(added, CharacterRelation)
        assert added.project_id == PID

    async def test_create_relation_self_loop_raises(self, service, mock_repo) -> None:
        """自环（两端同一角色）→ SelfRelationError（422 语义），不触达仓储。"""
        char = _char(name="林尘")
        with pytest.raises(SelfRelationError):
            await service.create_relation(char.id, char.id, "自我")
        mock_repo.get.assert_not_awaited()
        mock_repo.add_relation.assert_not_awaited()

    async def test_create_relation_cross_project_raises(self, service, mock_repo) -> None:
        """to 角色与 from 角色不同项目 → CrossProjectRelationError（422 语义）。"""
        from_char = _char(name="林尘")
        to_char = _char(name="苏瑶", project_id=PID_OTHER)
        mock_repo.get = AsyncMock(side_effect=[from_char, to_char])
        with pytest.raises(CrossProjectRelationError):
            await service.create_relation(from_char.id, to_char.id, "相识")
        mock_repo.add_relation.assert_not_awaited()

    async def test_create_relation_duplicate_raises(self, service, mock_repo) -> None:
        """同键活动关系已存在 → RelationConflictError（422 语义）。"""
        from_char = _char(name="林尘")
        to_char = _char(name="苏瑶")
        mock_repo.get = AsyncMock(side_effect=[from_char, to_char])
        mock_repo.get_relation_by_key = AsyncMock(
            return_value=_rel(from_char, to_char, relation_type="同伴")
        )
        with pytest.raises(RelationConflictError):
            await service.create_relation(from_char.id, to_char.id, "同伴")
        mock_repo.add_relation.assert_not_awaited()

    async def test_create_relation_missing_character_raises(self, service, mock_repo) -> None:
        """from 或 to 角色不存在 → CharacterNotFoundError（router 层转 404）。"""
        from_char = _char(name="林尘")
        to_char = _char(name="苏瑶")

        mock_repo.get = AsyncMock(side_effect=[None])
        with pytest.raises(CharacterNotFoundError):
            await service.create_relation(uuid.uuid4(), to_char.id, "相识")

        mock_repo.get = AsyncMock(side_effect=[from_char, None])
        with pytest.raises(CharacterNotFoundError):
            await service.create_relation(from_char.id, uuid.uuid4(), "相识")

    async def test_list_relations_bidirectional(self, service, mock_repo) -> None:
        """角色关系双向查询：repo.list_relations 收到 (project_id, character_id)。"""
        from_char = _char(name="林尘")
        to_char = _char(name="苏瑶")
        rel = _rel(from_char, to_char, relation_type="同伴")
        mock_repo.get = AsyncMock(return_value=from_char)
        mock_repo.list_relations = AsyncMock(return_value=[rel])

        result = await service.list_relations(from_char.id)
        assert result == [rel]
        mock_repo.list_relations.assert_awaited_once_with(PID.int, from_char.id.int)

        # 角色不存在 → 空列表（无悬空查询）
        mock_repo.get = AsyncMock(return_value=None)
        assert await service.list_relations(uuid.uuid4()) == []
        assert mock_repo.list_relations.await_count == 1

    async def test_update_relation_merges_fields(self, service, mock_repo) -> None:
        """更新关系：relation_type/description 覆盖；from/to 不变；缺失 → None。"""
        from_char = _char(name="林尘")
        to_char = _char(name="苏瑶")
        rel = _rel(from_char, to_char, relation_type="同伴", description="旧描述")
        mock_repo.get_relation = AsyncMock(return_value=rel)
        mock_repo.get_relation_by_key = AsyncMock(return_value=None)
        mock_repo.update_relation = AsyncMock(side_effect=lambda r: r)

        result = await service.update_relation(
            from_char.id, rel.id, relation_type="宿敌", description="新描述"
        )
        merged = mock_repo.update_relation.await_args.args[0]
        assert merged.id == rel.id
        assert merged.from_character_id == from_char.id
        assert merged.to_character_id == to_char.id
        assert merged.relation_type == "宿敌"
        assert merged.description == "新描述"
        mock_repo.get_relation_by_key.assert_awaited_once_with(
            from_char.id.int, to_char.id.int, "宿敌"
        )
        assert result == merged

        # 关系缺失或不属于该角色 → None（router 层转 404）
        mock_repo.get_relation = AsyncMock(return_value=None)
        assert await service.update_relation(from_char.id, uuid.uuid4(), description="x") is None
        other_char = _char(name="萧炎")
        mock_repo.get_relation = AsyncMock(return_value=rel)
        assert await service.update_relation(other_char.id, rel.id, description="x") is None

    async def test_delete_relation_hard_deletes(self, service, mock_repo) -> None:
        """真删关系（v1.1）：委托 repo.hard_delete_relation；关系缺失/不属于该角色 → False。"""
        from_char = _char(name="林尘")
        to_char = _char(name="苏瑶")
        rel = _rel(from_char, to_char, relation_type="同伴")
        mock_repo.get_relation = AsyncMock(return_value=rel)
        mock_repo.hard_delete_relation = AsyncMock(return_value=True)

        result = await service.delete_relation(from_char.id, rel.id)
        assert result is True
        mock_repo.hard_delete_relation.assert_awaited_once_with(rel.id.int)
        mock_repo.soft_delete_relation.assert_not_awaited()

        mock_repo.get_relation = AsyncMock(return_value=None)
        assert await service.delete_relation(from_char.id, uuid.uuid4()) is False
        other_char = _char(name="萧炎")
        mock_repo.get_relation = AsyncMock(return_value=rel)
        assert await service.delete_relation(other_char.id, rel.id) is False


class TestGroupCrud:
    """角色分组 — 创建（同名唯一）/查询/更新/删除编排。"""

    async def test_create_group_success(self, service, mock_repo) -> None:
        """创建分组 → repo.add_group 收到完整实体。"""
        group = await service.create_group(PID, "主角团", "主角及其伙伴", sort_order=1)
        assert group.name == "主角团"
        added = mock_repo.add_group.await_args.args[0]
        assert isinstance(added, CharacterGroup)
        assert added.project_id == PID
        assert added.description == "主角及其伙伴"
        assert added.sort_order == 1

    async def test_create_group_duplicate_name_raises(self, service, mock_repo) -> None:
        """项目内同名活动分组 → GroupNameConflictError（422 语义）。"""
        mock_repo.list_groups = AsyncMock(return_value=[_group(name="主角团")])
        with pytest.raises(GroupNameConflictError):
            await service.create_group(PID, "主角团")
        mock_repo.add_group.assert_not_awaited()

    async def test_get_and_list_groups(self, service, mock_repo) -> None:
        """分组查询：不存在 → None；列表透传项目 id（UUID→int）。"""
        group = _group(name="主角团")
        mock_repo.get_group = AsyncMock(return_value=group)
        assert await service.get_group(group.id) == group
        mock_repo.get_group.assert_awaited_once_with(group.id.int)

        mock_repo.get_group = AsyncMock(return_value=None)
        assert await service.get_group(uuid.uuid4()) is None

        mock_repo.list_groups = AsyncMock(return_value=[group])
        result = await service.list_groups(PID)
        assert result == [group]
        mock_repo.list_groups.assert_awaited_once_with(PID.int)

    async def test_update_group_merges_fields(self, service, mock_repo) -> None:
        """更新分组：仅覆盖传入字段；改名为已有分组名 → 冲突；缺失 → None。"""
        group = _group(name="主角团")
        mock_repo.get_group = AsyncMock(return_value=group)
        mock_repo.list_groups = AsyncMock(return_value=[])
        mock_repo.update_group = AsyncMock(side_effect=lambda g: g)

        result = await service.update_group(
            group.id, name="核心团队", description="新描述", sort_order=3
        )
        merged = mock_repo.update_group.await_args.args[0]
        assert merged.id == group.id
        assert merged.name == "核心团队"
        assert merged.description == "新描述"
        assert merged.sort_order == 3
        assert result == merged

        other = _group(name="核心团队")
        mock_repo.list_groups = AsyncMock(return_value=[other])
        with pytest.raises(GroupNameConflictError):
            await service.update_group(group.id, name="核心团队")

        mock_repo.get_group = AsyncMock(return_value=None)
        assert await service.update_group(uuid.uuid4(), name="x") is None

    async def test_delete_group_hard_deletes(self, service, mock_repo) -> None:
        """分组删除编排（v1.1 真删）：委托 repo.hard_delete_group；不存在 → False。"""
        group = _group(name="主角团")
        result = await service.delete_group(group.id)
        assert result is True
        mock_repo.hard_delete_group.assert_awaited_once_with(group.id.int)
        mock_repo.soft_delete_group.assert_not_awaited()

        mock_repo.hard_delete_group = AsyncMock(return_value=False)
        assert await service.delete_group(uuid.uuid4()) is False


class TestExtract:
    """AI 提取入口 — 项目存在性校验 + 委托 CharacterExtractor。"""

    async def test_extract_calls_extractor_with_default_model(
        self, service, mock_project_repo, mock_extractor
    ) -> None:
        """项目存在 → 以 project.config.model 为默认模型调用 extractor，返回提取结果。"""
        project = Project(
            id=PID,
            name="测试项目",
            config=ProjectConfig(model=DEFAULT_MODEL),
            created_at=TS,
            updated_at=TS,
        )
        mock_project_repo.get = AsyncMock(return_value=project)
        result = CharacterExtractionResult(
            created=[],
            updated=[],
            relations_created=[],
            relations_updated=[],
            warnings=[],
            model=DEFAULT_MODEL,
        )
        mock_extractor.extract = AsyncMock(return_value=result)

        request = CharacterExtractRequest(project_id=PID, text="第一章正文")
        outcome = await service.extract(request)

        assert outcome == result
        mock_project_repo.get.assert_awaited_once_with(PID.int)
        mock_extractor.extract.assert_awaited_once_with(request, default_model=DEFAULT_MODEL)

    async def test_extract_project_missing_raises(
        self, service, mock_project_repo, mock_extractor
    ) -> None:
        """项目不存在 → ProjectNotFoundError（router 层转 404），不调用提取管线。"""
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            await service.extract(CharacterExtractRequest(project_id=PID, text="第一章正文"))
        mock_extractor.extract.assert_not_awaited()


# ── Phase 3 覆盖率补齐（#104）──────────────────────────────────


class TestIntIdConversion:
    """领域 UUID ↔ 仓储层 int 转换 — int 直传路径（_to_int_id 的 return value 分支）。"""

    async def test_get_character_with_int_id(self, service, mock_repo) -> None:
        """int id 直传仓储，不做 UUID 转换。"""
        mock_repo.get = AsyncMock(return_value=None)
        assert await service.get_character(12345) is None
        mock_repo.get.assert_awaited_once_with(12345)


class TestUpdateCharacterGroup:
    """update_character 的 group_id 合法分支。"""

    async def test_update_character_with_valid_group(self, service, mock_repo) -> None:
        """group_id 指向同项目分组 → 校验通过，合并更新。"""
        char = _char(name="林尘")
        group = _group(name="主角团")
        mock_repo.get = AsyncMock(return_value=char)
        mock_repo.get_group = AsyncMock(return_value=group)
        mock_repo.update = AsyncMock(side_effect=lambda c: c)

        updated = await service.update_character(char.id, CharacterUpdate(group_id=group.id))

        assert updated is not None
        merged = mock_repo.update.await_args.args[0]
        assert merged.group_id == group.id
        mock_repo.get_group.assert_awaited_once_with(group.id.int)


class TestUpdateRelationVariants:
    """update_relation 的类型不变/冲突分支。"""

    async def test_update_relation_same_type_skips_conflict_check(self, service, mock_repo) -> None:
        """relation_type 与现状相同 → 不做冲突检查，仅合并 description。"""
        a = _char(name="林尘")
        b = _char(name="柳如烟")
        rel = _rel(a, b, relation_type="师徒")
        mock_repo.get_relation = AsyncMock(return_value=rel)
        mock_repo.update_relation = AsyncMock(side_effect=lambda r: r)

        updated = await service.update_relation(
            a.id, rel.id, relation_type="师徒", description="亦师亦友"
        )

        assert updated is not None
        merged = mock_repo.update_relation.await_args.args[0]
        assert merged.description == "亦师亦友"
        mock_repo.get_relation_by_key.assert_not_awaited()

    async def test_update_relation_without_type_keeps_type(self, service, mock_repo) -> None:
        """relation_type=None → 类型不变，也不做冲突检查。"""
        a = _char(name="林尘")
        b = _char(name="柳如烟")
        rel = _rel(a, b, relation_type="师徒")
        mock_repo.get_relation = AsyncMock(return_value=rel)
        mock_repo.update_relation = AsyncMock(side_effect=lambda r: r)

        updated = await service.update_relation(a.id, rel.id, description="新描述")

        assert updated is not None
        merged = mock_repo.update_relation.await_args.args[0]
        assert merged.relation_type == "师徒"
        mock_repo.get_relation_by_key.assert_not_awaited()

    async def test_update_relation_type_conflict_raises(self, service, mock_repo) -> None:
        """改类型撞同键活动关系 → RelationConflictError（422 语义）。"""
        a = _char(name="林尘")
        b = _char(name="柳如烟")
        rel = _rel(a, b, relation_type="师徒")
        dup = _rel(a, b, relation_type="宿敌")
        mock_repo.get_relation = AsyncMock(return_value=rel)
        mock_repo.get_relation_by_key = AsyncMock(return_value=dup)

        with pytest.raises(RelationConflictError):
            await service.update_relation(a.id, rel.id, relation_type="宿敌")


class TestUpdateGroupPartial:
    """update_group 的部分字段更新（None 字段不覆盖）。"""

    async def test_update_group_description_only(self, service, mock_repo) -> None:
        """只更新 description → name/sort_order 保持不变，无同名冲突检查。"""
        group = _group(name="主角团")
        mock_repo.get_group = AsyncMock(return_value=group)
        mock_repo.update_group = AsyncMock(side_effect=lambda g: g)

        updated = await service.update_group(group.id, description="核心成员")

        assert updated is not None
        merged = mock_repo.update_group.await_args.args[0]
        assert merged.name == "主角团"
        assert merged.description == "核心成员"
        assert merged.sort_order == 0
        mock_repo.list_groups.assert_not_awaited()

    async def test_update_group_name_only(self, service, mock_repo) -> None:
        """只更新 name → description/sort_order 保持不变（description=None 分支）。"""
        group = _group(name="主角团")
        mock_repo.get_group = AsyncMock(return_value=group)
        mock_repo.list_groups = AsyncMock(return_value=[])
        mock_repo.update_group = AsyncMock(side_effect=lambda g: g)

        updated = await service.update_group(group.id, name="核心团队")

        assert updated is not None
        merged = mock_repo.update_group.await_args.args[0]
        assert merged.name == "核心团队"
        assert merged.description == ""
        assert merged.sort_order == 0


class TestExtractConfigErrors:
    """extract 入口的依赖缺失保护（防静默降级）。"""

    async def test_extract_without_extractor_raises(self, mock_repo) -> None:
        """extractor 未注入 → CharacterServiceError（角色提取器未配置）。"""
        svc = CharacterService(repository=mock_repo)
        with pytest.raises(CharacterServiceError, match="角色提取器未配置"):
            await svc.extract(CharacterExtractRequest(project_id=PID, text="x"))

    async def test_extract_without_project_repo_raises(self, mock_repo, mock_extractor) -> None:
        """project_repo 未注入 → CharacterServiceError（项目仓储未配置）。"""
        svc = CharacterService(repository=mock_repo, extractor=mock_extractor)
        with pytest.raises(CharacterServiceError, match="项目仓储未配置"):
            await svc.extract(CharacterExtractRequest(project_id=PID, text="x"))


class TestCharacterExtraContract:
    """F43 P1 角色 extra 透传契约（spec §2.4）— create_character 加 extra 参数透传到实体.

    【RED 预期】create_character 签名尚无 extra 参数 → 传 extra= 触发 TypeError
    （FAILED）；缺省用例（守护）当前即 PASS——GREEN 后 extra or {} 语义保持。
    """

    async def test_create_character_passes_extra_to_entity(self, service, mock_repo) -> None:
        """传 extra → repo.add 收到的 Character.extra == 该 dict（role_rank/groups 原样落库）."""
        extra = {"role_rank": "major", "groups": ["主角团"]}
        created = await service.create_character(
            project_id=PID,
            name="林尘",
            personality="坚韧",
            background="山村少年",
            goals="变强",
            extra=extra,
        )
        added = mock_repo.add.await_args.args[0]
        assert added.extra == extra
        assert created.extra == extra

    async def test_create_character_extra_defaults_empty(self, service, mock_repo) -> None:
        """不传 extra（默认 None）→ Character.extra == {}（向后兼容，既有行为）."""
        await service.create_character(project_id=PID, name="林尘")
        added = mock_repo.add.await_args.args[0]
        assert added.extra == {}


# ══ P5 删除引用残留清理（#284 最后一批，spec §2.10/§5.18）══
#
# 生产 foreign_keys=OFF → 删除角色后 map_pins.ref_id(type=role) 残留。
# 本段契约：delete_character 注入 map_cleanup 钩子 → 删除成功后调用
# clear_ref_pins('role', [角色 int id])。镜像 world_service 的
# location_cleanup 钩子先例（F36 D10=b）。


class TestP5DeleteCharacterTriggersMapCleanup:
    """C7：delete_character 触发 map_cleanup 钩子——RED 预期 FAIL（现无钩子调用）."""

    async def test_delete_character_calls_map_cleanup_hook(
        self, mock_repo, mock_project_repo, mock_extractor
    ) -> None:
        """删除成功 → map_cleanup 钩子被调用（clear_ref_pins('role', [cid])）."""
        map_cleanup = AsyncMock()
        svc = CharacterService(
            repository=mock_repo,
            extractor=mock_extractor,
            project_repo=mock_project_repo,
            map_cleanup=map_cleanup,
        )
        char = _char(name="林尘")
        mock_repo.hard_delete = AsyncMock(return_value=True)

        result = await svc.delete_character(char.id)

        assert result is True
        map_cleanup.assert_awaited_once()
        # 钩子接收角色 int id（map_pins.ref_id 为 int 主键）
        call = map_cleanup.await_args
        assert call is not None and call.args[0] == char.id.int

    async def test_delete_character_missing_skips_map_cleanup(
        self, mock_repo, mock_project_repo, mock_extractor
    ) -> None:
        """删除失败（角色不存在）→ 钩子不被调用."""
        map_cleanup = AsyncMock()
        svc = CharacterService(
            repository=mock_repo,
            extractor=mock_extractor,
            project_repo=mock_project_repo,
            map_cleanup=map_cleanup,
        )
        mock_repo.hard_delete = AsyncMock(return_value=False)

        result = await svc.delete_character(uuid.uuid4())

        assert result is False
        map_cleanup.assert_not_awaited()
