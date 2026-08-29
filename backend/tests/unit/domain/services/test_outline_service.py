"""F11 大纲服务单元测试 — Mock Repository（F11 服务层 RED→GREEN）.

覆盖 spec §9 服务测试 + §7 边界表:
- 大纲 CRUD 全流程（Mock Repository）：创建/更新/真删（v1.1 默认硬删）
- 同名活动大纲创建/改名 → OutlineNameConflictError（422 语义）
- 大纲不存在各操作 → None（router 层转 404；create_point 抛 OutlineNotFoundError）
- 情节点 CRUD：create_point（position 缺省 → next_position）、update_point
  （arc_id 三态：不传不修改 / None 清除 / UUID 设置）、真删
- 情节点挂不存在的弧线（含跨项目）→ ArcNotInProjectError（422 语义）
- 弧线 CRUD + 真删编排（成员 arc_id 由 FK SET NULL 置空）
- 大纲真删 → 情节点由 FK CASCADE 级联物理删除（无软删级联编排）
- generate 入口：校验项目存在 → 组装 project_info → 调用 OutlineGenerator →
  返回 OutlineGenerationResult；项目不存在 → ProjectNotFoundError；
  generator / project_repo 未注入 → OutlineServiceError（配置错误）

依据: specs/f11-outline/spec.md §6 + §7 + §9 测试策略。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.outline import (
    Outline,
    OutlineGenerateRequest,
    OutlineGenerationResult,
    OutlineUpdate,
    PlotPoint,
    PlotPointUpdate,
    StoryArc,
    StoryArcUpdate,
)
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.ports.outline_errors import (
    ArcNameConflictError,
    ArcNotInProjectError,
    OutlineNameConflictError,
    OutlineNotFoundError,
    OutlineServiceError,
    ProjectNotFoundError,
)
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.services._outline_generator import OutlineGenerator
from inkflow.domain.services.outline_service import OutlineService, _build_project_info

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PID_OTHER = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _outline(
    name: str,
    *,
    project_id: uuid.UUID = PID,
    description: str = "",
    sort_order: int = 0,
) -> Outline:
    """构造测试用大纲实体（固定时间戳，便于断言）。"""
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        description=description,
        sort_order=sort_order,
        created_at=TS,
        updated_at=TS,
    )


def _point(
    name: str,
    *,
    outline: Outline,
    type: str = "",
    position: int = 0,
    arc_id: uuid.UUID | None = None,
) -> PlotPoint:
    """构造测试用情节点实体。"""
    return PlotPoint(
        id=uuid.uuid4(),
        outline_id=outline.id,
        project_id=outline.project_id,
        name=name,
        type=type,
        position=position,
        arc_id=arc_id,
        created_at=TS,
        updated_at=TS,
    )


def _arc(name: str, *, project_id: uuid.UUID = PID, description: str = "") -> StoryArc:
    """构造测试用弧线实体。"""
    return StoryArc(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        description=description,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock OutlineRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=OutlineRepositoryProtocol)
    # ── Outline ──
    repo.add = AsyncMock(side_effect=lambda o: o)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.update = AsyncMock(side_effect=lambda o: o)
    repo.hard_delete = AsyncMock(return_value=True)
    # ── PlotPoint ──
    repo.add_point = AsyncMock(side_effect=lambda p: p)
    repo.get_point = AsyncMock(return_value=None)
    repo.list_points = AsyncMock(return_value=[])
    repo.list_points_by_arc = AsyncMock(return_value=[])
    repo.next_position = AsyncMock(return_value=1)
    repo.update_point = AsyncMock(side_effect=lambda p: p)
    repo.hard_delete_point = AsyncMock(return_value=True)
    repo.clear_arc_of_points = AsyncMock(return_value=None)
    # ── StoryArc ──
    repo.add_arc = AsyncMock(side_effect=lambda a: a)
    repo.get_arc = AsyncMock(return_value=None)
    repo.get_arc_by_name = AsyncMock(return_value=None)
    repo.list_arcs = AsyncMock(return_value=[])
    repo.update_arc = AsyncMock(side_effect=lambda a: a)
    repo.hard_delete_arc = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — generate 入口校验项目存在性。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_generator() -> MagicMock:
    """Mock OutlineGenerator — generate 入口的管线调用。"""
    generator = MagicMock(spec=OutlineGenerator)
    generator.generate = AsyncMock()
    return generator


@pytest.fixture
def service(
    mock_repo: MagicMock,
    mock_project_repo: MagicMock,
    mock_generator: MagicMock,
) -> OutlineService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return OutlineService(
        repository=mock_repo,
        generator=mock_generator,
        project_repo=mock_project_repo,
    )


class TestOutlineCrud:
    """大纲 CRUD — 创建/查询/更新/真删（v1.1 默认硬删）。"""

    async def test_create_outline_success_persists(self, service, mock_repo) -> None:
        """创建大纲 → repo.add 收到完整实体（UUID 项目归属）。"""
        created = await service.create_outline(
            project_id=PID, name="第一卷大纲", description="主角觉醒", sort_order=1
        )
        assert created.name == "第一卷大纲"
        mock_repo.get_by_name.assert_awaited_once_with(PID.int, "第一卷大纲")
        added = mock_repo.add.await_args.args[0]
        assert isinstance(added, Outline)
        assert added.project_id == PID
        assert added.name == "第一卷大纲"
        assert added.description == "主角觉醒"
        assert added.sort_order == 1

    async def test_create_outline_duplicate_active_name_raises(self, service, mock_repo) -> None:
        """同名活动大纲已存在 → OutlineNameConflictError（422 语义），不落库。"""
        mock_repo.get_by_name = AsyncMock(return_value=_outline(name="第一卷大纲"))
        with pytest.raises(OutlineNameConflictError):
            await service.create_outline(project_id=PID, name="第一卷大纲")
        mock_repo.add.assert_not_awaited()

    async def test_get_outline_returns_none_when_missing(self, service, mock_repo) -> None:
        """大纲不存在 → None（router 层转 404）；存在 → 返回实体。"""
        outline = _outline(name="第一卷大纲")
        mock_repo.get = AsyncMock(return_value=outline)
        result = await service.get_outline(outline.id)
        assert result == outline
        mock_repo.get.assert_awaited_once_with(outline.id.int)

        mock_repo.get = AsyncMock(return_value=None)
        assert await service.get_outline(uuid.uuid4()) is None

    async def test_list_outlines_forwards_filters_and_pagination(self, service, mock_repo) -> None:
        """列表查询透传搜索/排序/分页（UUID→int 转换）。"""
        outline = _outline(name="第一卷大纲")
        mock_repo.list = AsyncMock(return_value=([outline], 1))
        items, total = await service.list_outlines(
            project_id=PID,
            search="第一卷",
            sort_by="name",
            sort_desc=False,
            offset=10,
            limit=5,
        )
        assert items == [outline]
        assert total == 1
        kwargs = mock_repo.list.await_args.kwargs
        assert kwargs["project_id"] == PID.int
        assert kwargs["search"] == "第一卷"
        assert kwargs["sort_by"] == "name"
        assert kwargs["sort_desc"] is False
        assert kwargs["offset"] == 10
        assert kwargs["limit"] == 5

    async def test_update_outline_merges_provided_fields(self, service, mock_repo) -> None:
        """部分更新：仅覆盖传入字段；同名自更不冲突。"""
        existing = _outline(name="第一卷大纲", description="旧描述", sort_order=0)
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_name = AsyncMock(return_value=existing)  # 同名自更 → 不冲突
        mock_repo.update = AsyncMock(side_effect=lambda o: o)

        update = OutlineUpdate(name="第一卷大纲", description="新描述", sort_order=2)
        result = await service.update_outline(existing.id, update)

        merged = mock_repo.update.await_args.args[0]
        assert isinstance(merged, Outline)
        assert merged.id == existing.id
        assert merged.name == "第一卷大纲"
        assert merged.description == "新描述"
        assert merged.sort_order == 2
        assert merged.created_at == TS
        assert result == merged

    async def test_update_outline_returns_none_when_missing(self, service, mock_repo) -> None:
        """大纲不存在 → None（router 层转 404），不触发仓储更新。"""
        mock_repo.get = AsyncMock(return_value=None)
        result = await service.update_outline(uuid.uuid4(), OutlineUpdate(name="新大纲"))
        assert result is None
        mock_repo.update.assert_not_awaited()

    async def test_update_outline_rename_conflict_raises(self, service, mock_repo) -> None:
        """改名为项目内其他活动大纲名 → OutlineNameConflictError（422 语义）。"""
        existing = _outline(name="第一卷大纲")
        other = _outline(name="第二卷大纲")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_name = AsyncMock(return_value=other)
        with pytest.raises(OutlineNameConflictError):
            await service.update_outline(existing.id, OutlineUpdate(name="第二卷大纲"))
        mock_repo.update.assert_not_awaited()

    async def test_delete_outline_hard_deletes(self, service, mock_repo) -> None:
        """真删大纲（v1.1）：委托 repo.hard_delete（情节点由 FK CASCADE）；不存在 → False。"""
        outline = _outline(name="第一卷大纲")
        result = await service.delete_outline(outline.id)
        assert result is True
        mock_repo.hard_delete.assert_awaited_once_with(outline.id.int)

        mock_repo.hard_delete = AsyncMock(return_value=False)
        assert await service.delete_outline(uuid.uuid4()) is False


class TestPlotPointCrud:
    """情节点 — 创建（position 缺省/弧线校验）/更新（arc_id 三态）/真删。"""

    async def test_create_point_success_with_default_position(self, service, mock_repo) -> None:
        """position 缺省 → 用 next_position（大纲末尾 +1）；项目归属取自大纲。"""
        outline = _outline(name="第一卷大纲")
        mock_repo.get = AsyncMock(return_value=outline)
        mock_repo.next_position = AsyncMock(return_value=5)

        created = await service.create_point(
            outline.id, name="主角登场", type="开篇", description="外门测试"
        )
        mock_repo.next_position.assert_awaited_once_with(outline.id.int)
        added = mock_repo.add_point.await_args.args[0]
        assert isinstance(added, PlotPoint)
        assert added.outline_id == outline.id
        assert added.project_id == PID
        assert added.name == "主角登场"
        assert added.type == "开篇"
        assert added.description == "外门测试"
        assert added.position == 5
        assert added.arc_id is None
        assert created == added

    async def test_create_point_explicit_position_skips_next_position(
        self, service, mock_repo
    ) -> None:
        """position 显式传入 → 直接使用，不调用 next_position。"""
        outline = _outline(name="第一卷大纲")
        mock_repo.get = AsyncMock(return_value=outline)
        created = await service.create_point(outline.id, name="高潮", position=3)
        mock_repo.next_position.assert_not_awaited()
        assert created.position == 3

    async def test_create_point_outline_missing_raises(self, service, mock_repo) -> None:
        """大纲不存在 → OutlineNotFoundError（router 层转 404），不落库。"""
        mock_repo.get = AsyncMock(return_value=None)
        with pytest.raises(OutlineNotFoundError):
            await service.create_point(uuid.uuid4(), name="主角登场")
        mock_repo.add_point.assert_not_awaited()

    async def test_create_point_with_arc_success(self, service, mock_repo) -> None:
        """弧线属于同一项目 → 情节点挂载该弧线。"""
        outline = _outline(name="第一卷大纲")
        arc = _arc(name="主角成长线")
        mock_repo.get = AsyncMock(return_value=outline)
        mock_repo.get_arc = AsyncMock(return_value=arc)

        created = await service.create_point(outline.id, name="金手指觉醒", arc_id=arc.id)
        mock_repo.get_arc.assert_awaited_once_with(arc.id.int)
        assert created.arc_id == arc.id

    async def test_create_point_arc_missing_or_cross_project_raises(
        self, service, mock_repo
    ) -> None:
        """弧线不存在或属于其他项目 → ArcNotInProjectError（422 语义）。"""
        outline = _outline(name="第一卷大纲")
        foreign_arc = _arc(name="敌方线", project_id=PID_OTHER)
        mock_repo.get = AsyncMock(return_value=outline)

        mock_repo.get_arc = AsyncMock(return_value=None)
        with pytest.raises(ArcNotInProjectError):
            await service.create_point(outline.id, name="转折", arc_id=uuid.uuid4())

        mock_repo.get_arc = AsyncMock(return_value=foreign_arc)
        with pytest.raises(ArcNotInProjectError):
            await service.create_point(outline.id, name="转折", arc_id=foreign_arc.id)
        mock_repo.add_point.assert_not_awaited()

    async def test_update_point_arc_id_three_states(self, service, mock_repo) -> None:
        """arc_id 三态：不传不修改 / None 清除 / UUID 设置（校验归属）。"""
        outline = _outline(name="第一卷大纲")
        arc = _arc(name="主角成长线")
        existing = _point("主角登场", outline=outline, position=1, arc_id=arc.id)
        mock_repo.get_point = AsyncMock(return_value=existing)
        mock_repo.get_arc = AsyncMock(return_value=arc)
        mock_repo.update_point = AsyncMock(side_effect=lambda p: p)

        # ① 不传 arc_id → 不修改（保持原 arc_id）
        result = await service.update_point(existing.id, PlotPointUpdate(type="发展"))
        merged = mock_repo.update_point.await_args.args[0]
        assert merged.arc_id == arc.id
        assert merged.type == "发展"
        mock_repo.get_arc.assert_not_awaited()

        # ② 显式传 None → 清除弧线归属
        result = await service.update_point(existing.id, PlotPointUpdate(arc_id=None))
        merged = mock_repo.update_point.await_args.args[0]
        assert merged.arc_id is None
        mock_repo.get_arc.assert_not_awaited()

        # ③ 传 UUID → 设置（校验弧线存在且同项目）
        other_arc = _arc(name="新线")
        mock_repo.get_arc = AsyncMock(return_value=other_arc)
        result = await service.update_point(existing.id, PlotPointUpdate(arc_id=other_arc.id))
        merged = mock_repo.update_point.await_args.args[0]
        assert merged.arc_id == other_arc.id
        mock_repo.get_arc.assert_awaited_once_with(other_arc.id.int)
        assert result == merged

    async def test_update_point_arc_not_in_project_raises(self, service, mock_repo) -> None:
        """更新时弧线缺失或属于其他项目 → ArcNotInProjectError（422 语义）。"""
        outline = _outline(name="第一卷大纲")
        existing = _point("主角登场", outline=outline)
        mock_repo.get_point = AsyncMock(return_value=existing)
        foreign_arc = _arc(name="敌方线", project_id=PID_OTHER)

        mock_repo.get_arc = AsyncMock(return_value=None)
        with pytest.raises(ArcNotInProjectError):
            await service.update_point(existing.id, PlotPointUpdate(arc_id=uuid.uuid4()))

        mock_repo.get_arc = AsyncMock(return_value=foreign_arc)
        with pytest.raises(ArcNotInProjectError):
            await service.update_point(existing.id, PlotPointUpdate(arc_id=foreign_arc.id))
        mock_repo.update_point.assert_not_awaited()

    async def test_update_point_returns_none_when_missing(self, service, mock_repo) -> None:
        """情节点不存在 → None（router 层转 404），不触发仓储更新。"""
        mock_repo.get_point = AsyncMock(return_value=None)
        result = await service.update_point(uuid.uuid4(), PlotPointUpdate(name="新名"))
        assert result is None
        mock_repo.update_point.assert_not_awaited()

    async def test_delete_point_hard_deletes(self, service, mock_repo) -> None:
        """真删情节点（v1.1）：委托 repo.hard_delete_point；不存在 → False。"""
        point = _point("主角登场", outline=_outline(name="第一卷大纲"))
        result = await service.delete_point(point.id)
        assert result is True
        mock_repo.hard_delete_point.assert_awaited_once_with(point.id.int)

        mock_repo.hard_delete_point = AsyncMock(return_value=False)
        assert await service.delete_point(uuid.uuid4()) is False

    async def test_list_points(self, service, mock_repo) -> None:
        """情节点列表透传大纲 id；大纲不存在 → 空列表（无悬空查询）。"""
        outline = _outline(name="第一卷大纲")
        point = _point("主角登场", outline=outline)
        mock_repo.get = AsyncMock(return_value=outline)
        mock_repo.list_points = AsyncMock(return_value=[point])

        result = await service.list_points(outline.id)
        assert result == [point]
        mock_repo.list_points.assert_awaited_once_with(outline.id.int)

        mock_repo.get = AsyncMock(return_value=None)
        assert await service.list_points(uuid.uuid4()) == []
        assert mock_repo.list_points.await_count == 1


class TestStoryArcCrud:
    """弧线 — 创建（同名唯一）/查询/更新/真删。"""

    async def test_create_arc_success(self, service, mock_repo) -> None:
        """创建弧线 → repo.add_arc 收到完整实体（UUID 项目归属）。"""
        arc = await service.create_arc(PID, "主角成长线", "从废柴到强者的蜕变")
        assert arc.name == "主角成长线"
        mock_repo.get_arc_by_name.assert_awaited_once_with(PID.int, "主角成长线")
        added = mock_repo.add_arc.await_args.args[0]
        assert isinstance(added, StoryArc)
        assert added.project_id == PID
        assert added.description == "从废柴到强者的蜕变"

    async def test_create_arc_duplicate_name_raises(self, service, mock_repo) -> None:
        """项目内同名活动弧线 → ArcNameConflictError（422 语义），不落库。"""
        mock_repo.get_arc_by_name = AsyncMock(return_value=_arc(name="主角成长线"))
        with pytest.raises(ArcNameConflictError):
            await service.create_arc(PID, "主角成长线")
        mock_repo.add_arc.assert_not_awaited()

    async def test_get_and_list_arcs(self, service, mock_repo) -> None:
        """弧线查询：不存在 → None；列表透传项目 id（UUID→int）。"""
        arc = _arc(name="主角成长线")
        mock_repo.get_arc = AsyncMock(return_value=arc)
        assert await service.get_arc(arc.id) == arc
        mock_repo.get_arc.assert_awaited_once_with(arc.id.int)

        mock_repo.get_arc = AsyncMock(return_value=None)
        assert await service.get_arc(uuid.uuid4()) is None

        mock_repo.list_arcs = AsyncMock(return_value=[arc])
        result = await service.list_arcs(PID)
        assert result == [arc]
        mock_repo.list_arcs.assert_awaited_once_with(PID.int)

    async def test_update_arc_merges_fields_and_conflict(self, service, mock_repo) -> None:
        """更新弧线：仅覆盖传入字段；改名为已有弧线名 → 冲突；缺失 → None。"""
        arc = _arc(name="主角成长线", description="旧说明")
        mock_repo.get_arc = AsyncMock(return_value=arc)
        mock_repo.get_arc_by_name = AsyncMock(return_value=None)
        mock_repo.update_arc = AsyncMock(side_effect=lambda a: a)

        result = await service.update_arc(
            arc.id, StoryArcUpdate(name="蜕变线", description="新说明")
        )
        merged = mock_repo.update_arc.await_args.args[0]
        assert isinstance(merged, StoryArc)
        assert merged.id == arc.id
        assert merged.name == "蜕变线"
        assert merged.description == "新说明"
        assert result == merged

        other = _arc(name="蜕变线")
        mock_repo.get_arc_by_name = AsyncMock(return_value=other)
        with pytest.raises(ArcNameConflictError):
            await service.update_arc(arc.id, StoryArcUpdate(name="蜕变线"))

        mock_repo.get_arc = AsyncMock(return_value=None)
        assert await service.update_arc(uuid.uuid4(), StoryArcUpdate(name="x")) is None

    async def test_delete_arc_hard_deletes(self, service, mock_repo) -> None:
        """真删弧线（v1.1）：委托 repo.hard_delete_arc（成员 arc_id 由 FK SET NULL）；
        无 clear_arc 编排；不存在 → False。"""
        arc = _arc(name="主角成长线")
        result = await service.delete_arc(arc.id)
        assert result is True
        mock_repo.hard_delete_arc.assert_awaited_once_with(arc.id.int)
        mock_repo.clear_arc_of_points.assert_not_awaited()

        mock_repo.hard_delete_arc = AsyncMock(return_value=False)
        assert await service.delete_arc(uuid.uuid4()) is False


class TestGenerate:
    """AI 生成入口 — 项目存在性校验 + 组装 project_info + 委托 OutlineGenerator。"""

    async def test_generate_calls_generator_with_default_model(
        self, service, mock_project_repo, mock_generator
    ) -> None:
        """项目存在 → 组装 project_info（含项目名）并以项目默认模型调用 generator。"""
        project = Project(
            id=PID,
            name="测试项目",
            config=ProjectConfig(model=DEFAULT_MODEL),
            created_at=TS,
            updated_at=TS,
        )
        mock_project_repo.get = AsyncMock(return_value=project)
        result = OutlineGenerationResult(saved=True, model=DEFAULT_MODEL)
        mock_generator.generate = AsyncMock(return_value=result)

        request = OutlineGenerateRequest(project_id=PID, name="第一卷大纲")
        outcome = await service.generate(request)

        assert outcome == result
        mock_project_repo.get.assert_awaited_once_with(PID.int)
        mock_generator.generate.assert_awaited_once()
        call = mock_generator.generate.await_args
        assert call.args[0] == request  # request 按位置传参
        kwargs = call.kwargs
        assert "测试项目" in kwargs["project_info"]
        assert kwargs["default_model"] == DEFAULT_MODEL

    async def test_generate_project_missing_raises(
        self, service, mock_project_repo, mock_generator
    ) -> None:
        """项目不存在 → ProjectNotFoundError（router 层转 404），不调用生成管线。"""
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            await service.generate(OutlineGenerateRequest(project_id=PID))
        mock_generator.generate.assert_not_awaited()

    async def test_generate_project_model_none_falls_back_to_llm_default_model(
        self, mock_project_repo, mock_generator
    ) -> None:
        """#520 D1=C：project.config.model=None → default_model 回退注入的 llm_default_model。"""
        project = Project(
            id=PID,
            name="测试项目",
            config=ProjectConfig(model=None),
            created_at=TS,
            updated_at=TS,
        )
        mock_project_repo.get = AsyncMock(return_value=project)
        fallback = "deepseek/deepseek-v4-flash"
        result = OutlineGenerationResult(saved=True, model=fallback)
        mock_generator.generate = AsyncMock(return_value=result)
        svc = OutlineService(
            repository=MagicMock(),
            generator=mock_generator,
            project_repo=mock_project_repo,
            llm_default_model=fallback,
        )

        request = OutlineGenerateRequest(project_id=PID, name="第一卷大纲")
        outcome = await svc.generate(request)

        assert outcome == result
        assert mock_generator.generate.await_args.kwargs["default_model"] == fallback

    async def test_generate_missing_dependencies_raise(self, mock_repo) -> None:
        """generator / project_repo 未注入 → OutlineServiceError（配置错误）。"""
        bare = OutlineService(repository=mock_repo)
        with pytest.raises(OutlineServiceError):
            await bare.generate(OutlineGenerateRequest(project_id=PID))

        no_project_repo = OutlineService(repository=mock_repo, generator=MagicMock())
        with pytest.raises(OutlineServiceError):
            await no_project_repo.generate(OutlineGenerateRequest(project_id=PID))


# ── Phase 3 覆盖率补齐（#104）──────────────────────────────────


class TestCoverageGaps:
    """int id 直传 / 部分更新跳过冲突检查 / project_info extra / get_point。"""

    async def test_get_outline_with_int_id(self, service, mock_repo) -> None:
        """int id 直传仓储，不做 UUID 转换。"""
        mock_repo.get = AsyncMock(return_value=None)
        assert await service.get_outline(7) is None
        mock_repo.get.assert_awaited_once_with(7)

    async def test_update_outline_without_name_skips_conflict_check(
        self, service, mock_repo
    ) -> None:
        """不传 name → 跳过同名冲突检查，仅合并 description。"""
        outline = _outline(name="第一卷大纲")
        mock_repo.get = AsyncMock(return_value=outline)
        mock_repo.update = AsyncMock(side_effect=lambda o: o)

        updated = await service.update_outline(outline.id, OutlineUpdate(description="新描述"))

        assert updated is not None
        merged = mock_repo.update.await_args.args[0]
        assert merged.description == "新描述"
        assert merged.name == "第一卷大纲"
        mock_repo.get_by_name.assert_not_awaited()

    async def test_get_point(self, service, mock_repo) -> None:
        """get_point → 委托 repo.get_point（int id）。"""
        outline = _outline(name="第一卷大纲")
        point = _point(name="觉醒", outline=outline, type="转折")
        mock_repo.get_point = AsyncMock(return_value=point)

        assert await service.get_point(point.id) == point

        mock_repo.get_point.assert_awaited_once_with(point.id.int)

    async def test_update_arc_without_name_skips_conflict_check(self, service, mock_repo) -> None:
        """不传 name → 跳过同名冲突检查，仅合并 description。"""
        arc = _arc(name="主线")
        mock_repo.get_arc = AsyncMock(return_value=arc)
        mock_repo.update_arc = AsyncMock(side_effect=lambda a: a)

        updated = await service.update_arc(arc.id, StoryArcUpdate(description="新说明"))

        assert updated is not None
        merged = mock_repo.update_arc.await_args.args[0]
        assert merged.description == "新说明"
        assert merged.name == "主线"
        mock_repo.get_arc_by_name.assert_not_awaited()

    def test_build_project_info_includes_extra(self) -> None:
        """project.config.extra 非空 → project_info 含 JSON 序列化的扩展配置。"""
        project = Project(
            id=PID,
            name="测试项目",
            config=ProjectConfig(extra={"基调": "热血"}),
            created_at=TS,
            updated_at=TS,
        )

        info = _build_project_info(project)

        assert "项目名: 测试项目" in info
        assert '扩展配置: {"基调": "热血"}' in info

    def test_build_project_info_without_extra(self) -> None:
        """project.config.extra 为空 → project_info 不含扩展配置段。"""
        project = Project(
            id=PID,
            name="测试项目",
            config=ProjectConfig(),
            created_at=TS,
            updated_at=TS,
        )

        info = _build_project_info(project)

        assert "项目名: 测试项目" in info
        assert "扩展配置" not in info
