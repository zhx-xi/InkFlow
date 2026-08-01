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
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._world_extractor import WorldExtractor
from inkflow.domain.services.world_service import WorldService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _setting(
    name: str,
    *,
    category: str = "",
    content: str = "",
    is_deleted: bool = False,
    project_id: uuid.UUID = PID,
) -> WorldSetting:
    """构造测试用世界观条目实体（固定时间戳，便于断言）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        category=category,
        content=content,
        is_deleted=is_deleted,
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
    repo.soft_delete = AsyncMock(return_value=True)
    repo.restore = AsyncMock(return_value=None)
    repo.hard_delete = AsyncMock(return_value=True)
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
        assert added.is_deleted is False

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

    async def test_delete_setting_soft_deletes(self, service, mock_repo) -> None:
        """软删条目：委托 repo.soft_delete；不存在 → False。"""
        setting = _setting(name="灵气复苏")
        result = await service.delete_setting(setting.id)
        assert result is True
        mock_repo.soft_delete.assert_awaited_once_with(setting.id.int)
        mock_repo.hard_delete.assert_not_awaited()

        mock_repo.soft_delete = AsyncMock(return_value=False)
        assert await service.delete_setting(uuid.uuid4()) is False

    async def test_delete_setting_force_hard_deletes(self, service, mock_repo) -> None:
        """force=True → 物理删除，不触发软删。"""
        setting = _setting(name="灵气复苏")
        result = await service.delete_setting(setting.id, force=True)
        assert result is True
        mock_repo.hard_delete.assert_awaited_once_with(setting.id.int)
        mock_repo.soft_delete.assert_not_awaited()

    async def test_restore_setting_restores(self, service, mock_repo) -> None:
        """恢复软删条目：委托 repo.restore；不存在 → None（重复操作无毒）。"""
        setting = _setting(name="灵气复苏")
        mock_repo.restore = AsyncMock(return_value=setting)
        result = await service.restore_setting(setting.id)
        assert result == setting
        mock_repo.restore.assert_awaited_once_with(setting.id.int)

        mock_repo.restore = AsyncMock(return_value=None)
        assert await service.restore_setting(uuid.uuid4()) is None


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
