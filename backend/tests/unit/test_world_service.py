"""F10 世界观服务单元测试 — Mock Repository（F10 服务层 RED→GREEN）.

覆盖 spec §9 服务测试 + §7 边界表（镜像 F9 test_character_service.py，
去掉关系/分组相关用例）:
- 创建/更新/软删/恢复/硬删全流程（Mock Repository）
- 同名活动条目创建/改名 → WorldNameConflictError（422 语义）
- 条目不存在各操作 → None（router 层转 404）
- list 透传搜索/category 过滤/排序/分页；list_categories 透传
- extract 入口：校验项目存在 → 调用 WorldExtractor → 返回 WorldExtractionResult；
  项目不存在 → ProjectNotFoundError；extractor/project_repo 未注入 → 配置错误

依据: specs/f10-world-service/spec.md §7 + §9 测试策略。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.models.world import (
    WorldExtractionResult,
    WorldExtractRequest,
    WorldSetting,
    WorldUpdate,
)
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_errors import (
    ProjectNotFoundError,
    WorldNameConflictError,
    WorldServiceError,
)

# F35（#173）：新增错误类尚未实现（RED 阶段）——用临时 stub 保证文件可收集、
# 既有用例不受影响；GREEN 后自动使用真实类（spec §3.3 异常映射表）。
try:  # pragma: no cover - RED 阶段占位分支
    from inkflow.domain.ports.world_errors import (
        WorldChildrenActionRequiredError,
        WorldCycleError,
        WorldParentNotFoundError,
        WorldReparentTargetError,
    )
except ImportError:  # pragma: no cover - RED 阶段占位分支
    WorldParentNotFoundError = type("WorldParentNotFoundError", (Exception,), {})
    WorldCycleError = type("WorldCycleError", (Exception,), {})
    WorldChildrenActionRequiredError = type("WorldChildrenActionRequiredError", (Exception,), {})
    WorldReparentTargetError = type("WorldReparentTargetError", (Exception,), {})
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._world_extractor import WorldExtractor
from inkflow.domain.services.world_service import WorldService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OTHER_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")  # F35: 跨项目校验用
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _setting(
    name: str,
    *,
    category: str = "",
    content: str = "",
    project_id: uuid.UUID = PID,
    parent_id: uuid.UUID | None = None,  # F35: 父地点；None = 顶层
) -> WorldSetting:
    """构造测试用世界观条目实体（固定时间戳，便于断言）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        category=category,
        content=content,
        parent_id=parent_id,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_categories = AsyncMock(return_value=[])
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.update = AsyncMock(side_effect=lambda s: s)
    repo.hard_delete = AsyncMock(return_value=True)
    # F35（#173）新方法默认值：既有用例零影响，新用例按需覆盖
    repo.get_by_parent_and_name = AsyncMock(return_value=None)
    repo.collect_ancestor_ids = AsyncMock(return_value=[])
    repo.list_descendants = AsyncMock(return_value=[])
    repo.hard_delete_many = AsyncMock(return_value=0)
    repo.delete_with_reparent = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — extract 入口校验项目存在性。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_extractor() -> MagicMock:
    """Mock WorldExtractor — extract 入口的管线调用。"""
    extractor = MagicMock(spec=WorldExtractor)
    extractor.extract = AsyncMock()
    return extractor


@pytest.fixture
def service(
    mock_repo: MagicMock,
    mock_project_repo: MagicMock,
    mock_extractor: MagicMock,
) -> WorldService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return WorldService(
        repository=mock_repo,
        extractor=mock_extractor,
        project_repo=mock_project_repo,
    )


class TestWorldSettingCrud:
    """世界观条目 CRUD — 创建/查询/更新/软删/恢复/硬删。"""

    async def test_create_setting_success_persists(self, service, mock_repo) -> None:
        """创建条目 → repo.add 收到完整实体（UUID 项目归属、类别/内容、默认软删标记）。"""
        created = await service.create_setting(
            PID, "灵气复苏", category="设定", content="天地灵气复苏"
        )
        assert created.name == "灵气复苏"
        mock_repo.get_by_name.assert_awaited_once_with(PID.int, "灵气复苏")
        added = mock_repo.add.await_args.args[0]
        assert isinstance(added, WorldSetting)
        assert added.project_id == PID
        assert added.name == "灵气复苏"
        assert added.category == "设定"
        assert added.content == "天地灵气复苏"

    async def test_create_setting_duplicate_active_name_raises_conflict(
        self, service, mock_repo
    ) -> None:
        """同名活动条目已存在 → WorldNameConflictError（422 语义），不落库。"""
        mock_repo.get_by_name = AsyncMock(return_value=_setting(name="灵气复苏"))
        with pytest.raises(WorldNameConflictError):
            await service.create_setting(PID, "灵气复苏")
        mock_repo.add.assert_not_awaited()

    async def test_get_setting_returns_none_when_missing(self, service, mock_repo) -> None:
        """条目不存在 → None（router 层转 404）；存在 → 返回实体。"""
        setting = _setting(name="灵气复苏")
        mock_repo.get = AsyncMock(return_value=setting)
        result = await service.get_setting(setting.id)
        assert result == setting
        mock_repo.get.assert_awaited_once_with(setting.id.int)

        mock_repo.get = AsyncMock(return_value=None)
        assert await service.get_setting(uuid.uuid4()) is None

    async def test_list_settings_forwards_filters_and_pagination(self, service, mock_repo) -> None:
        """列表查询透传搜索/category 过滤/排序/分页（UUID→int 转换）。"""
        setting = _setting(name="灵气复苏", category="设定")
        mock_repo.list = AsyncMock(return_value=([setting], 1))
        items, total = await service.list_settings(
            project_id=PID,
            search="灵气",
            category="设定",
            sort_by="name",
            sort_desc=False,
            offset=10,
            limit=5,
        )
        assert items == [setting]
        assert total == 1
        kwargs = mock_repo.list.await_args.kwargs
        assert kwargs["project_id"] == PID.int
        assert kwargs["search"] == "灵气"
        assert kwargs["category"] == "设定"
        assert kwargs["sort_by"] == "name"
        assert kwargs["sort_desc"] is False
        assert kwargs["offset"] == 10
        assert kwargs["limit"] == 5

    async def test_list_categories_forwards(self, service, mock_repo) -> None:
        """类别汇总透传项目 id（UUID→int）。"""
        mock_repo.list_categories = AsyncMock(return_value=[("设定", 3), ("规则", 1)])
        result = await service.list_categories(PID)
        assert result == [("设定", 3), ("规则", 1)]
        mock_repo.list_categories.assert_awaited_once_with(PID.int)

    async def test_update_setting_merges_provided_fields(self, service, mock_repo) -> None:
        """部分更新：仅覆盖传入字段；category="" 清除类别；category=None 不修改。"""
        existing = _setting(name="灵气复苏", category="设定", content="旧内容")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_name = AsyncMock(return_value=existing)  # 同名自更 → 不冲突
        mock_repo.update = AsyncMock(side_effect=lambda s: s)

        update = WorldUpdate(name="灵气复苏", category="", content="新内容")
        result = await service.update_setting(existing.id, update)

        merged = mock_repo.update.await_args.args[0]
        assert isinstance(merged, WorldSetting)
        assert merged.id == existing.id
        assert merged.name == "灵气复苏"
        assert merged.category == ""  # 显式清除类别（置为未分类）
        assert merged.content == "新内容"
        assert merged.created_at == TS
        assert result == merged

        # category=None 表示不修改（与未传入等价），保持原类别
        mock_repo.update = AsyncMock(side_effect=lambda s: s)
        result2 = await service.update_setting(existing.id, WorldUpdate(category=None))
        merged2 = mock_repo.update.await_args.args[0]
        assert merged2.category == "设定"
        assert result2 == merged2

    async def test_update_setting_returns_none_when_missing(self, service, mock_repo) -> None:
        """条目不存在 → None（router 层转 404），不触发仓储更新。"""
        mock_repo.get = AsyncMock(return_value=None)
        result = await service.update_setting(uuid.uuid4(), WorldUpdate(name="灵力体系"))
        assert result is None
        mock_repo.update.assert_not_awaited()

    async def test_update_setting_rename_conflict_raises(self, service, mock_repo) -> None:
        """改名为项目内其他活动条目名 → WorldNameConflictError（422 语义）。"""
        existing = _setting(name="灵气复苏")
        other = _setting(name="灵力体系")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_name = AsyncMock(return_value=other)
        with pytest.raises(WorldNameConflictError):
            await service.update_setting(existing.id, WorldUpdate(name="灵力体系"))
        mock_repo.update.assert_not_awaited()

    async def test_delete_setting_hard_deletes(self, service, mock_repo) -> None:
        """真删条目（v1.1）：委托 repo.hard_delete；不存在 → False。"""
        setting = _setting(name="灵气复苏")
        result = await service.delete_setting(setting.id)
        assert result is True
        mock_repo.hard_delete.assert_awaited_once_with(setting.id.int)

        mock_repo.hard_delete = AsyncMock(return_value=False)
        assert await service.delete_setting(uuid.uuid4()) is False


class TestExtract:
    """AI 提取入口 — 项目存在性校验 + 委托 WorldExtractor。"""

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
        result = WorldExtractionResult(created=[], updated=[], warnings=[], model=DEFAULT_MODEL)
        mock_extractor.extract = AsyncMock(return_value=result)

        request = WorldExtractRequest(project_id=PID, text="第一章正文")
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
            await service.extract(WorldExtractRequest(project_id=PID, text="第一章正文"))
        mock_extractor.extract.assert_not_awaited()

    async def test_extract_unconfigured_extractor_raises(self, mock_repo) -> None:
        """extractor 未注入 → WorldServiceError（配置错误，防静默降级）。"""
        svc = WorldService(repository=mock_repo)
        with pytest.raises(WorldServiceError):
            await svc.extract(WorldExtractRequest(project_id=PID, text="第一章正文"))

    async def test_extract_unconfigured_project_repo_raises(
        self, mock_repo, mock_extractor
    ) -> None:
        """project_repo 未注入 → WorldServiceError（配置错误，防静默降级）。"""
        svc = WorldService(repository=mock_repo, extractor=mock_extractor)
        with pytest.raises(WorldServiceError):
            await svc.extract(WorldExtractRequest(project_id=PID, text="第一章正文"))


# ── F35 地点树（#173）：create 校验链 / update parent 语义 / 删除矩阵 ──


class TestF35CreateValidationChain:
    """F35 create_setting 校验链（spec §5.1 ①②③④⑤：父存在→同级同名→循环→落库）.

    RED 阶段预期: create_setting 签名无 parent_id 参数 → 传 parent_id 的调用
    TypeError；未传 parent_id 的用例因 get_by_parent_and_name 未被调用 /
    add 收到的实体无 parent_id 属性而失败（AssertionError / AttributeError）。
    """

    async def test_create_parent_missing_raises_parent_not_found(self, service, mock_repo) -> None:
        """parent_id 指向不存在条目（repo.get → None）→ WorldParentNotFoundError（spec §7 边界 1）.
        # F35
        RED: create_setting 无 parent_id 参数 → TypeError.
        """
        mock_repo.get = AsyncMock(return_value=None)
        with pytest.raises(WorldParentNotFoundError):
            await service.create_setting(PID, "清河县城", parent_id=uuid.uuid4())
        mock_repo.add.assert_not_awaited()

    async def test_create_parent_cross_project_raises_parent_not_found(
        self, service, mock_repo
    ) -> None:
        """parent_id 指向跨项目条目（repo.get 返回他项目实体）→
        WorldParentNotFoundError（数据隔离基线，spec §7 边界 3）.  # F35
        RED: create_setting 无 parent_id 参数 → TypeError.
        """
        other_parent = _setting(name="他国", project_id=OTHER_PID)
        mock_repo.get = AsyncMock(return_value=other_parent)
        with pytest.raises(WorldParentNotFoundError):
            await service.create_setting(PID, "清河县城", parent_id=other_parent.id)
        mock_repo.add.assert_not_awaited()

    async def test_create_same_parent_duplicate_name_raises_conflict(
        self, service, mock_repo
    ) -> None:
        """同级同名（get_by_parent_and_name 命中）→ WorldNameConflictError（DB 兜底前预检，spec
        §5.1 ③）.  # F35
        RED: create_setting 无 parent_id 参数 → TypeError.
        """
        parent = _setting(name="青州")
        mock_repo.get = AsyncMock(return_value=parent)
        mock_repo.get_by_parent_and_name = AsyncMock(return_value=_setting(name="清河县城"))
        with pytest.raises(WorldNameConflictError):
            await service.create_setting(PID, "清河县城", parent_id=parent.id)
        mock_repo.add.assert_not_awaited()

    async def test_create_top_level_duplicate_name_raises_conflict(
        self, service, mock_repo
    ) -> None:
        """顶层同名（get_by_parent_and_name(pid, None, name) 命中）→ WorldNameConflictError（spec
        §2.4: SQLite NULL 不冲突 → 应用层校验）.  # F35
        RED: get_by_parent_and_name 未被调用 → 断言失败.
        """
        mock_repo.get_by_parent_and_name = AsyncMock(return_value=_setting(name="大越国"))
        with pytest.raises(WorldNameConflictError):
            await service.create_setting(PID, "大越国")
        mock_repo.add.assert_not_awaited()

    async def test_create_with_parent_id_passes_uuid_to_add(self, service, mock_repo) -> None:
        """成功路径：create_setting(pid, name, parent_id=X) → 父校验通过后 add 收到 parent_id=X
        的实体（UUID→int 转换断言）.  # F35
        RED: create_setting 无 parent_id 参数 → TypeError.
        """
        parent = _setting(name="青州")
        mock_repo.get = AsyncMock(return_value=parent)
        mock_repo.get_by_parent_and_name = AsyncMock(return_value=None)

        created = await service.create_setting(PID, "清河县城", parent_id=parent.id)

        assert created.name == "清河县城"
        # 校验链调用参数：父 id 已转 int、顶层/同级预检走 (pid, parent_int, name)
        mock_repo.get_by_parent_and_name.assert_awaited_once_with(
            PID.int, parent.id.int, "清河县城"
        )
        added = mock_repo.add.await_args.args[0]
        assert added.parent_id == parent.id  # 领域层保留 UUID

    async def test_create_without_parent_id_passes_none(self, service, mock_repo) -> None:
        """成功路径：无 parent_id → add 收到 parent_id=None 实体（顶层）；顶层同名预检用 (pid,
        None, name).  # F35
        RED: 顶层预检未被调用 → 断言失败；add 实体无 parent_id 属性 → AttributeError.
        """
        created = await service.create_setting(PID, "大越国")

        assert created.name == "大越国"
        mock_repo.get_by_parent_and_name.assert_awaited_once_with(PID.int, None, "大越国")
        added = mock_repo.add.await_args.args[0]
        assert added.parent_id is None


class TestF35UpdateParentSemantics:
    """F35 update_setting parent_id 特殊处理（spec §2.2 None 语义差异，load-bearing）.

    RED 阶段预期: WorldUpdate 无 parent_id 字段（静默忽略）→ model_fields_set
    不含 parent_id → merged 实体无 parent_id 属性 → AttributeError / DID NOT RAISE。
    """

    async def test_update_parent_id_none_moves_to_top(self, service, mock_repo) -> None:
        """WorldUpdate(parent_id=None)（model_fields_set 含 parent_id）→ 置顶：repo.update 收到
        parent_id=None 的实体（spec §5.1 load-bearing）.  # F35
        RED: 字段缺失静默忽略 → merged 无 parent_id 属性 → AttributeError.
        """
        parent = _setting(name="青州")
        existing = _setting(name="清河县城", parent_id=parent.id)
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(side_effect=lambda s: s)

        result = await service.update_setting(existing.id, WorldUpdate(parent_id=None))

        merged = mock_repo.update.await_args.args[0]
        assert merged.id == existing.id
        assert merged.parent_id is None  # 显式 null = 置顶
        assert result == merged

    async def test_update_without_parent_id_keeps_parent(self, service, mock_repo) -> None:
        """WorldUpdate(name='x') 不含 parent_id → 不修改 parent：repo.update 收到
        parent_id=原值（与置顶可区分）.  # F35
        RED: merged 无 parent_id 属性 → AttributeError.
        """
        parent = _setting(name="青州")
        existing = _setting(name="清河县城", parent_id=parent.id)
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(side_effect=lambda s: s)

        await service.update_setting(existing.id, WorldUpdate(name="清河县城·改"))

        merged = mock_repo.update.await_args.args[0]
        assert merged.parent_id == parent.id  # 未出现 → 保持原值

    async def test_update_reparent_cycle_raises(self, service, mock_repo) -> None:
        """改挂循环：新父祖先链含自身 → WorldCycleError（spec §5.2 祖先链反向校验）.
        RED: WorldUpdate 静默忽略 parent_id → 不抛异常 → DID NOT RAISE.
        """
        parent = _setting(name="青州")
        existing = _setting(name="清河县城", parent_id=parent.id)
        target = _setting(name="清河县城分县")  # 假设 target 是 existing 的子孙
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.collect_ancestor_ids = AsyncMock(
            return_value=[existing.id.int]
        )  # 新父祖先链含自身

        with pytest.raises(WorldCycleError):
            await service.update_setting(existing.id, WorldUpdate(parent_id=target.id))
        mock_repo.update.assert_not_awaited()
        mock_repo.collect_ancestor_ids.assert_awaited_once_with(target.id.int)

    async def test_update_reparent_name_conflict_raises(self, service, mock_repo) -> None:
        """改挂到新父时同级已存在同名 → WorldNameConflictError（同级唯一校验，spec §5.1 ③）.  # F35
        RED: WorldUpdate 静默忽略 parent_id → 不抛异常 → DID NOT RAISE.
        """
        parent = _setting(name="青州")
        existing = _setting(name="清河县城", parent_id=parent.id)
        target = _setting(name="东大陆")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_parent_and_name = AsyncMock(return_value=_setting(name="清河县城"))
        mock_repo.collect_ancestor_ids = AsyncMock(return_value=[])

        with pytest.raises(WorldNameConflictError):
            await service.update_setting(existing.id, WorldUpdate(parent_id=target.id))
        mock_repo.update.assert_not_awaited()

    async def test_update_reparent_missing_parent_raises(self, service, mock_repo) -> None:
        """改挂父不存在（repo.get(新父) → None）→ WorldParentNotFoundError（spec §7 边界 1）.
        # F35 coverage-gap 补测（非 RED）：改挂父存在性校验 L253 未覆盖.
        """
        parent = _setting(name="青州")
        existing = _setting(name="清河县城", parent_id=parent.id)
        mock_repo.get = AsyncMock(
            side_effect=lambda sid: existing if sid == existing.id.int else None
        )

        with pytest.raises(WorldParentNotFoundError):
            await service.update_setting(existing.id, WorldUpdate(parent_id=uuid.uuid4()))
        mock_repo.update.assert_not_awaited()

    async def test_update_reparent_cross_project_parent_raises(self, service, mock_repo) -> None:
        """改挂父跨项目（repo.get(新父) 返回他项目实体）→ WorldParentNotFoundError（数据隔离）.
        # F35 coverage-gap 补测（非 RED）：改挂父同项目校验 raise 分支 L250-253 未覆盖.
        """
        parent = _setting(name="青州")
        existing = _setting(name="清河县城", parent_id=parent.id)
        other_parent = _setting(name="他国", project_id=OTHER_PID)
        mock_repo.get = AsyncMock(
            side_effect=lambda sid: existing if sid == existing.id.int else other_parent
        )

        with pytest.raises(WorldParentNotFoundError):
            await service.update_setting(existing.id, WorldUpdate(parent_id=other_parent.id))
        mock_repo.update.assert_not_awaited()

    async def test_update_reparent_with_rename_conflict_raises(self, service, mock_repo) -> None:
        """改挂+同时改名：新父下改名后撞同级（get_by_parent_and_name 命中他条目）→
        WorldNameConflictError（new_name=update.name 分支 L258 + 改挂后同级校验 L261-265）.
        # F35 coverage-gap 补测（非 RED）：name+parent_id 同时变更路径未覆盖.
        """
        parent = _setting(name="青州")
        existing = _setting(name="清河县城", parent_id=parent.id)
        target = _setting(name="东大陆")
        mock_repo.get = AsyncMock(
            side_effect=lambda sid: existing if sid == existing.id.int else target
        )
        # 第一次调用（改名后新父同级预检）不冲突；第二次调用（改挂后同级校验）命中他条目
        mock_repo.get_by_parent_and_name = AsyncMock(
            side_effect=[None, _setting(name="清河县城·迁")]
        )
        mock_repo.collect_ancestor_ids = AsyncMock(return_value=[])

        with pytest.raises(WorldNameConflictError):
            await service.update_setting(
                existing.id, WorldUpdate(name="清河县城·迁", parent_id=target.id)
            )
        mock_repo.update.assert_not_awaited()
        assert mock_repo.get_by_parent_and_name.await_count == 2

    async def test_update_rename_conflict_same_parent_raises(self, service, mock_repo) -> None:
        """有父条目改名撞同级（get_by_parent_and_name(pid, 原父, 新名) 命中他条目）→
        WorldNameConflictError（F35 同级改名校验 L239 未覆盖）.
        # F35 coverage-gap 补测（非 RED）：既有改名冲突用例仅覆盖顶层 get_by_name 路径.
        """
        parent = _setting(name="青州")
        existing = _setting(name="清河县城", parent_id=parent.id)
        other = _setting(name="清河县城·改")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_parent_and_name = AsyncMock(return_value=other)

        with pytest.raises(WorldNameConflictError):
            await service.update_setting(existing.id, WorldUpdate(name="清河县城·改"))
        mock_repo.update.assert_not_awaited()
        mock_repo.get_by_parent_and_name.assert_awaited_once_with(
            PID.int, parent.id.int, "清河县城·改"
        )

    async def test_update_reparent_to_self_raises(self, service, mock_repo) -> None:
        """改挂父为自身（parent_id == 自身 id）→ WorldCycleError（L394-395 直接自环短路分支）.
        # F35 coverage-gap 补测（非 RED）：_assert_no_cycle 直接自环分支未覆盖.
        """
        existing = _setting(name="青州")
        mock_repo.get = AsyncMock(return_value=existing)

        with pytest.raises(WorldCycleError):
            await service.update_setting(existing.id, WorldUpdate(parent_id=existing.id))
        mock_repo.update.assert_not_awaited()
        mock_repo.collect_ancestor_ids.assert_not_awaited()  # 直接自环短路，不再查祖先链


class TestF35DeleteMatrix:
    """F35 delete_setting 删除语义矩阵（spec §5.5，load-bearing；边界 X：无子软删保持 F10）.

    RED 阶段预期: delete_setting 签名无 cascade/reparent_to → 相关调用 TypeError；
    有子用例因不抛 WorldChildrenActionRequiredError → DID NOT RAISE。
    """

    async def test_delete_no_children_hard_deletes(self, service, mock_repo) -> None:
        """无子地点（repo.list(parent_id=sid) 空）→ 无参 delete → repo.hard_delete（v1.1 真删）.
        RED: 当前实现不查子 → list 未被调用 → 断言失败.
        """
        setting = _setting(name="清河县城")
        sid = setting.id.int
        mock_repo.list = AsyncMock(return_value=([], 0))

        result = await service.delete_setting(setting.id)

        assert result is True
        mock_repo.hard_delete.assert_awaited_once_with(sid)
        mock_repo.list.assert_awaited()
        assert mock_repo.list.await_args.kwargs["parent_id"] == sid  # 查子用直接子级过滤

    async def test_delete_with_children_requires_action(self, service, mock_repo) -> None:
        """有子地点（repo.list(parent_id=sid) 非空）+ 无 cascade/reparent →
        WorldChildrenActionRequiredError（强制显式选择，spec §5.5）.  # F35
        RED: 不抛异常 → DID NOT RAISE.
        """
        setting = _setting(name="青州")
        child = _setting(name="清河县城")
        mock_repo.list = AsyncMock(return_value=([child], 1))

        with pytest.raises(WorldChildrenActionRequiredError):
            await service.delete_setting(setting.id)
        mock_repo.hard_delete.assert_not_awaited()

    async def test_delete_cascade_hard_deletes_subtree(self, service, mock_repo) -> None:
        """cascade=True → list_descendants(sid) 收集子树（含自身）→ hard_delete_many(子树 int 集合)
        真删（spec §5.5 D4=A，单事务原子）.  # F35
        RED: delete_setting 无 cascade 参数 → TypeError.
        """
        setting = _setting(name="青州")
        child = _setting(name="清河县城")
        sid, child_int = setting.id.int, child.id.int
        mock_repo.list = AsyncMock(return_value=([child], 1))
        mock_repo.list_descendants = AsyncMock(return_value=[setting, child])

        result = await service.delete_setting(setting.id, cascade=True)

        assert result is True
        mock_repo.list_descendants.assert_awaited_once_with(sid)
        mock_repo.hard_delete_many.assert_awaited_once()
        assert set(mock_repo.hard_delete_many.await_args.args[0]) == {sid, child_int}

    async def test_delete_reparent_moves_children_to_target(self, service, mock_repo) -> None:
        """reparent_to=X → 先校验目标（存在+同项目+非自身子树）→ delete_with_reparent(sid, X.int)
        （自身真删 + 直接子改挂，spec §5.5 D2=A）.  # F35
        RED: delete_setting 无 reparent_to 参数 → TypeError.
        """
        setting = _setting(name="青州")
        child = _setting(name="清河县城")
        target = _setting(name="东大陆")
        sid = setting.id.int
        mock_repo.list = AsyncMock(return_value=([child], 1))
        mock_repo.list_descendants = AsyncMock(return_value=[setting, child])  # target 不在子树
        mock_repo.get = AsyncMock(return_value=target)

        result = await service.delete_setting(setting.id, reparent_to=target.id)

        assert result is True
        mock_repo.delete_with_reparent.assert_awaited_once_with(sid, target.id.int)
        mock_repo.hard_delete_many.assert_not_awaited()
        mock_repo.hard_delete.assert_not_awaited()

    async def test_delete_reparent_missing_target_raises(self, service, mock_repo) -> None:
        """reparent 目标不存在（repo.get → None）→ WorldReparentTargetError（spec §5.5 注 + §7 边界
        11）.  # F35
        RED: delete_setting 无 reparent_to 参数 → TypeError.
        """
        setting = _setting(name="青州")
        child = _setting(name="清河县城")
        mock_repo.list = AsyncMock(return_value=([child], 1))
        mock_repo.get = AsyncMock(return_value=None)

        with pytest.raises(WorldReparentTargetError):
            await service.delete_setting(setting.id, reparent_to=uuid.uuid4())
        mock_repo.delete_with_reparent.assert_not_awaited()

    async def test_delete_reparent_cross_project_target_raises(self, service, mock_repo) -> None:
        """reparent 目标跨项目 → WorldReparentTargetError（数据隔离基线）.  # F35
        RED: delete_setting 无 reparent_to 参数 → TypeError.
        """
        setting = _setting(name="青州")
        child = _setting(name="清河县城")
        other_target = _setting(name="他国", project_id=OTHER_PID)
        mock_repo.list = AsyncMock(return_value=([child], 1))
        mock_repo.get = AsyncMock(return_value=other_target)

        with pytest.raises(WorldReparentTargetError):
            await service.delete_setting(setting.id, reparent_to=other_target.id)
        mock_repo.delete_with_reparent.assert_not_awaited()

    async def test_delete_reparent_target_in_own_subtree_raises(self, service, mock_repo) -> None:
        """reparent 目标是自身子树（X ∈ list_descendants(sid) 集合）→
        WorldReparentTargetError（spec §5.5 注）.  # F35
        RED: delete_setting 无 reparent_to 参数 → TypeError.
        """
        setting = _setting(name="青州")
        child = _setting(name="清河县城")
        target = _setting(name="清河县城分县")  # 假设是自身子孙
        mock_repo.list = AsyncMock(return_value=([child], 1))
        mock_repo.list_descendants = AsyncMock(return_value=[setting, child, target])
        mock_repo.get = AsyncMock(return_value=target)

        with pytest.raises(WorldReparentTargetError):
            await service.delete_setting(setting.id, reparent_to=target.id)
        mock_repo.delete_with_reparent.assert_not_awaited()

    async def test_delete_cascade_precedes_reparent(self, service, mock_repo) -> None:
        """cascade + reparent_to 同时提供 → cascade 优先（hard_delete_many 调用，
        delete_with_reparent 不调用，spec §5.5）.  # F35
        RED: delete_setting 无 cascade/reparent_to 参数 → TypeError.
        """
        setting = _setting(name="青州")
        child = _setting(name="清河县城")
        target = _setting(name="东大陆")
        sid = setting.id.int
        mock_repo.list = AsyncMock(return_value=([child], 1))
        mock_repo.list_descendants = AsyncMock(return_value=[setting, child])
        mock_repo.get = AsyncMock(return_value=target)

        result = await service.delete_setting(setting.id, cascade=True, reparent_to=target.id)

        assert result is True
        mock_repo.hard_delete_many.assert_awaited_once()
        assert set(mock_repo.hard_delete_many.await_args.args[0]) == {sid, child.id.int}
        mock_repo.delete_with_reparent.assert_not_awaited()


class TestF35TreeQueries:
    """F35 树查询 service 透传."""

    async def test_list_descendants_forwards(self, service, mock_repo) -> None:
        """list_descendants(sid) 透传 repo（UUID→int；层序/含自身由 repo 保证，spec §5.3）.  # F35
        RED: service 无此方法 → AttributeError.
        """
        setting = _setting(name="青州")
        child = _setting(name="清河县城")
        mock_repo.list_descendants = AsyncMock(return_value=[setting, child])

        result = await service.list_descendants(setting.id)

        assert result == [setting, child]
        mock_repo.list_descendants.assert_awaited_once_with(setting.id.int)

    async def test_list_ancestors_returns_self_then_ancestors(self, service, mock_repo) -> None:
        """3 级祖先链（自身→父→祖父）：返回 [自身, 父, 祖父]（自身在前，面包屑顺序）.
        # F35 coverage-gap 补测（非 RED）：list_ancestors while 循环主体 L356-380 全未覆盖.
        """
        grandparent = _setting(name="大越国")
        parent = _setting(name="青州", parent_id=grandparent.id)
        setting = _setting(name="清河县城", parent_id=parent.id)
        by_id = {
            setting.id.int: setting,
            parent.id.int: parent,
            grandparent.id.int: grandparent,
        }
        mock_repo.get = AsyncMock(side_effect=lambda sid: by_id.get(sid))

        result = await service.list_ancestors(setting.id)

        assert result == [setting, parent, grandparent]
        mock_repo.get.assert_any_await(setting.id.int)
        mock_repo.get.assert_any_await(parent.id.int)
        mock_repo.get.assert_any_await(grandparent.id.int)

    async def test_list_ancestors_truncates_at_missing_parent(self, service, mock_repo) -> None:
        """父已软删（repo.get(父) → None）→ 链在父处截断，仅返回自身（面包屑不悬挂）.
        # F35 coverage-gap 补测（非 RED）：while 循环 break 分支 L376-377.
        """
        parent = _setting(name="青州")
        setting = _setting(name="清河县城", parent_id=parent.id)
        mock_repo.get = AsyncMock(
            side_effect=lambda sid: setting if sid == setting.id.int else None
        )

        result = await service.list_ancestors(setting.id)

        assert result == [setting]
        mock_repo.get.assert_any_await(parent.id.int)  # 已尝试上溯到父

    async def test_list_ancestors_truncates_at_cycle(self, service, mock_repo) -> None:
        """数据异常成环（父反指子）→ seen 防御截断，不死循环（L372-373 防御分支）.
        链上溯一圈后回到自身 → 再次访问自身时其父已在 seen 中 → 截断（自身出现两次 = 环闭合点）.
        # F35 coverage-gap 补测（非 RED）：while 循环成环截断分支未覆盖.
        """
        parent = _setting(name="青州")
        setting = _setting(name="清河县城", parent_id=parent.id)
        parent_cyclic = parent.model_copy(update={"parent_id": setting.id})  # 异常：父反指子
        by_id = {setting.id.int: setting, parent_cyclic.id.int: parent_cyclic}
        mock_repo.get = AsyncMock(side_effect=lambda sid: by_id.get(sid))

        result = await service.list_ancestors(setting.id)

        assert result == [setting, parent_cyclic, setting]  # 上溯一圈后截断

    async def test_list_ancestors_missing_returns_none(self, service, mock_repo) -> None:
        """条目不存在（repo.get → None）→ 返回 None（router 转 404）.
        # F35 coverage-gap 补测（非 RED）：list_ancestors 入口 None 分支 L364-365.
        """
        mock_repo.get = AsyncMock(return_value=None)

        assert await service.list_ancestors(uuid.uuid4()) is None


# ══ P5 删除引用残留清理（#284 最后一批，spec §2.10/§5.18）══
#
# 生产 foreign_keys=OFF → 删除世界观条目后 maps.root_location_id / pin
# location_id 残留。cascade/单删路径已调 location_cleanup（F36 D10=b）；
# **reparent 路径漏调**（spec §5.18）——本段契约补上。


class TestP5DeleteSettingReparentTriggersLocationCleanup:
    """C9：delete_setting reparent 路径触发 location_cleanup——RED 预期 FAIL."""

    async def test_delete_setting_reparent_calls_location_cleanup(
        self, mock_repo, mock_project_repo, mock_extractor
    ) -> None:
        """reparent 删除（子改挂新父）→ location_cleanup 钩子被调用（[被删条目 id]）."""
        location_cleanup = AsyncMock()
        svc = WorldService(
            repository=mock_repo,
            extractor=mock_extractor,
            project_repo=mock_project_repo,
            location_cleanup=location_cleanup,
        )
        setting = _setting(name="清河县城")
        target = _setting(name="青州")
        mock_repo.get = AsyncMock(
            side_effect=lambda sid: target if sid == target.id.int else setting
        )
        mock_repo.list = AsyncMock(return_value=([_setting(name="子地点")], 1))
        mock_repo.delete_with_reparent = AsyncMock(return_value=True)

        result = await svc.delete_setting(setting.id, reparent_to=target.id)

        assert result is True
        location_cleanup.assert_awaited_once()
        call = location_cleanup.await_args
        assert call is not None and call.args[0] == [setting.id.int]
