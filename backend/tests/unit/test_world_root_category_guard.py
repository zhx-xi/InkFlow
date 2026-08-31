"""#834 世界观「先建根/先建分类」后端前置校验 RED 契约测试.

锁定契约（当前实现缺失强制校验 → 应 FAIL）:
1. 项目无根世界时创建非根条目（带 parent_id）→ 拒绝并要求先建根（WorldRootMissingError）
2. 根世界单例：已存在根时再建根（parent_id=None）→ 拒绝（WorldRootConflictError，#567）
3. 创建带非空 category 条目但分类未先建 → 拒绝（WorldCategoryMissingError）
4. 合法路径：先建根 → 再建分类 → 再建带该分类条目 → 成功（且须走 get_category_by_name 校验）
5. AI 工具 create_world_setting 显式 root/parent 前置语义（描述含根/分类前置）

依据: issue #834 + specs/f10-world-settings/spec.md §5.1/§13。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.world import WorldCategory, WorldSetting
from inkflow.domain.ports.world_errors import (
    WorldCategoryMissingError,
    WorldRootConflictError,
    WorldRootMissingError,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.world_service import WorldService
from inkflow.infrastructure.agent.tools.setting_write_tools import (
    CREATE_WORLD_SETTING_SPEC,
    SettingWriteToolDeps,
    build_setting_write_tools,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _setting(name: str, *, parent_id: uuid.UUID | None = None) -> WorldSetting:
    """构造测试用世界观条目实体（固定时间戳，parent_id 可置顶/置子）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        category="",
        content="",
        parent_id=parent_id,
        created_at=TS,
        updated_at=TS,
    )


def _category(name: str) -> WorldCategory:
    """构造测试用世界观分类实体."""
    return WorldCategory(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        kind="abstract",
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol — 默认无根、默认分类存在（get_category_by_name 恒 truthy）。"""
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))  # 默认无根（top_level_only 空）
    repo.get_by_parent_and_name = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.get_category_by_name = AsyncMock()  # 未配置 → 返回 truthy MagicMock = 分类存在
    return repo


@pytest.fixture
def service(mock_repo: MagicMock) -> WorldService:
    """被测服务实例（全 Mock 依赖注入，extractor/project_repo 占位）。"""
    return WorldService(
        repository=mock_repo,
        extractor=AsyncMock(),
        project_repo=AsyncMock(),
    )


class TestRootPrerequisite:
    """#834 先建根前置校验（根世界单例 + 非根条目须已有根）。"""

    async def test_create_non_root_without_root_raises_root_required(
        self, service: WorldService, mock_repo: MagicMock
    ) -> None:
        """项目无根世界时创建非根条目（带 parent_id）→ 拒绝并要求先建根。

        当前实现 FAIL：无根时父校验先触发 WorldParentNotFoundError（而非 WorldRootMissingError）；
        或 parent_id=None 时直接建条目成为根（无「先建根」强制）。
        """
        mock_repo.list = AsyncMock(return_value=([], 0))  # 无根
        with pytest.raises(WorldRootMissingError):
            await service.create_setting(
                PID,
                "宗门等级体系",
                category="设定",
                content="...",
                parent_id=uuid.uuid4(),
            )
        mock_repo.add.assert_not_awaited()

    async def test_create_second_root_raises_root_conflict(
        self, service: WorldService, mock_repo: MagicMock
    ) -> None:
        """根世界单例：已存在根时再建根（parent_id=None）→ 拒绝（#567）。

        当前实现 FAIL：无该校验，直接创建第二个根条目成为新的根。
        """
        root = _setting("天元大陆")
        mock_repo.list = AsyncMock(return_value=([root], 1))  # 已有根
        with pytest.raises(WorldRootConflictError):
            await service.create_setting(PID, "灵气复苏")
        mock_repo.add.assert_not_awaited()


class TestCategoryPrerequisite:
    """#834 先建分类前置校验。"""

    async def test_create_with_category_not_created_raises(
        self, service: WorldService, mock_repo: MagicMock
    ) -> None:
        """创建带非空 category 条目但分类未先建 → 拒绝（WorldCategoryMissingError）。

        当前实现 FAIL：category 是自由字符串快照，任意字符串直接放行落库。
        """
        root = _setting("天元大陆")
        mock_repo.list = AsyncMock(return_value=([root], 1))  # 已有根
        mock_repo.get = AsyncMock(return_value=root)  # parent 存在
        mock_repo.get_category_by_name = AsyncMock(return_value=None)  # 分类「设定」未建
        with pytest.raises(WorldCategoryMissingError):
            await service.create_setting(
                PID,
                "宗门等级体系",
                category="设定",
                content="...",
                parent_id=root.id,
            )
        mock_repo.add.assert_not_awaited()

    async def test_legal_path_root_then_category_then_entry_succeeds(
        self, service: WorldService, mock_repo: MagicMock
    ) -> None:
        """合法路径：先建根 → 再建分类 → 再建带该分类条目 → 成功。

        GREEN 后须证明走 get_category_by_name 校验（当前未调用 → 断言 FAIL）。
        """
        root = _setting("天元大陆")
        mock_repo.list = AsyncMock(return_value=([root], 1))  # 根已存在（先建根完成）
        mock_repo.get = AsyncMock(return_value=root)  # parent 存在
        mock_repo.get_category_by_name = AsyncMock(return_value=_category("设定"))  # 分类已建
        created = await service.create_setting(
            PID,
            "宗门等级体系",
            category="设定",
            content="...",
            parent_id=root.id,
        )
        assert created.name == "宗门等级体系"
        assert created.category == "设定"
        mock_repo.add.assert_awaited_once()
        # 证明合法路径 ALSO 走了分类校验（当前实现不调用 get_category_by_name → FAIL）
        mock_repo.get_category_by_name.assert_awaited_once_with(PID, "设定")


class TestCreateWorldSettingToolRootCategoryGuard:
    """#834 AI 工具 create_world_setting 显式 root/parent 前置语义。"""

    def test_create_world_setting_spec_exposes_root_and_category_prereq(self) -> None:
        """工具 spec 描述须显式暴露「先建根/先建分类」前置语义（当前描述无 → FAIL）。"""
        desc = CREATE_WORLD_SETTING_SPEC.description
        assert "根" in desc
        assert "parent_id" in desc
        assert "分类" in desc

    @staticmethod
    def _make_tool_deps() -> SettingWriteToolDeps:
        audit = MagicMock()
        audit.record = AsyncMock(return_value=None)
        return SettingWriteToolDeps(
            character_service=MagicMock(),
            world_service=MagicMock(),
            outline_service=MagicMock(),
            audit_service=audit,
            expected_project_id=PID,
        )

    @pytest.mark.asyncio
    async def test_create_world_setting_propagates_root_missing_as_ok_false(self) -> None:
        """工具将 world_service 抛出的 WorldRootMissingError 以 {ok:False} 信封返回（不裸抛）。"""
        deps = self._make_tool_deps()
        deps.world_service.create_setting = AsyncMock(side_effect=WorldRootMissingError())
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        result = json.loads(await tools["create_world_setting"].func(name="宗门等级体系"))
        assert result["ok"] is False
        assert "根" in result["error"]

    @pytest.mark.asyncio
    async def test_create_world_setting_propagates_category_missing_as_ok_false(self) -> None:
        """工具将 world_service 抛出的 WorldCategoryMissingError 以 {ok:False} 信封返回。"""
        deps = self._make_tool_deps()
        deps.world_service.create_setting = AsyncMock(side_effect=WorldCategoryMissingError("设定"))
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        result = json.loads(
            await tools["create_world_setting"].func(name="宗门等级体系", category="设定")
        )
        assert result["ok"] is False
        assert "分类" in result["error"]
