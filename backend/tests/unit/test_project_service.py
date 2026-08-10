"""项目业务服务单元测试 — Mock Repository（#104 覆盖率补测 + #225 契约升级）.

覆盖:
- update: 项目不存在 → None（不触发仓储更新）；部分更新合并
  （existing.model_copy(update=dto.model_dump(exclude_unset=True))）
- #225 契约升级：config 子对象从「整体替换」改为「字段级合并」——显式 null=关闭、
  缺失字段不改、sentinel "__default__"=跟随默认（预留）；顶层字段合并语义不变
- create/get/list/soft_delete/restore/hard_delete 基础委托与 UUID→int 转换
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import Genre, Project, ProjectConfig, ProjectUpdate
from inkflow.domain.services.project_service import ProjectService
from inkflow.infrastructure.database.repositories.project_repo import SQLiteProjectRepository

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


def _project(**overrides: object) -> Project:
    """构造测试用 Project 实体（固定时间戳，便于断言）。"""
    defaults: dict[str, object] = {
        "id": PID,
        "name": "旧名字",
        "genre": Genre.XUANHUAN,
        "language": "zh-CN",
        "target_words": 100_000,
        "config": ProjectConfig(model="gpt-4o", temperature=0.7),
        "is_deleted": False,
        "created_at": TS,
        "updated_at": TS,
    }
    defaults.update(overrides)
    return Project(**defaults)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock SQLiteProjectRepository — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=SQLiteProjectRepository)
    repo.get = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda p: p)
    repo.update = AsyncMock(side_effect=lambda p: p)
    repo.list_all = AsyncMock(return_value=([], 0))
    repo.soft_delete = AsyncMock(return_value=True)
    repo.restore = AsyncMock(return_value=None)
    repo.hard_delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def svc(mock_repo: MagicMock) -> ProjectService:
    """被测服务实例 — __init__ 直接构造真实 repo，测试中替换为 mock（零 I/O）。"""
    service = ProjectService(db_session=MagicMock())
    service._repo = mock_repo
    return service


class TestProjectUpdate:
    """update 部分更新 — None 分支 + 合并更新路径。"""

    async def test_update_returns_none_when_project_missing(self, svc, mock_repo) -> None:
        """项目不存在 → 返回 None，不触发仓储更新。"""
        result = await svc.update(PID, ProjectUpdate(name="新名字"))
        assert result is None
        mock_repo.get.assert_awaited_once_with(PID.int)
        mock_repo.update.assert_not_awaited()

    async def test_update_merges_provided_fields(self, svc, mock_repo) -> None:
        """部分更新：仅覆盖 DTO 传入字段，其余保持不变，返回合并后的 Project。"""
        existing = _project()
        mock_repo.get = AsyncMock(return_value=existing)

        result = await svc.update(PID, ProjectUpdate(name="新名字", target_words=500_000))

        merged = mock_repo.update.await_args.args[0]
        assert isinstance(merged, Project)
        assert merged.id == PID
        assert merged.name == "新名字"  # 传入字段已更新
        assert merged.target_words == 500_000  # 传入字段已更新
        assert merged.genre == Genre.XUANHUAN  # 未传字段保持不变
        assert merged.language == "zh-CN"  # 未传字段保持不变
        assert merged.config == existing.config
        assert merged.created_at == TS
        assert merged.updated_at == TS
        assert result == merged
        assert result is not None

    async def test_update_merges_config_subobject_fields(self, svc, mock_repo) -> None:
        """#225 契约升级：config 传入 → 字段级合并（不再整体替换），未传 config 字段保留。

        原契约（#104）为「整体替换」——PATCH 只传部分字段会把其余 agent_* 打回默认
        None（关闭/跟随默认语义混淆，前端省略 undefined 键 → 落库 null 的根因链）。
        #225 拍板：config 子对象按字段合并，缺失字段不改。
        """
        existing = _project(
            config=ProjectConfig(
                model="gpt-4o", temperature=0.7, agent_writer="deepseek/deepseek-chat"
            )
        )
        mock_repo.get = AsyncMock(return_value=existing)

        new_config = ProjectConfig(model="deepseek-v3", temperature=0.3, writing_style="冷峻")
        result = await svc.update(PID, ProjectUpdate(genre=Genre.KEHUAN, config=new_config))

        merged = mock_repo.update.await_args.args[0]
        assert merged.genre == Genre.KEHUAN
        # 字段级合并：merged.config 为 ProjectConfig 实例（非 dict），显式传入字段更新
        assert isinstance(merged.config, ProjectConfig)
        assert merged.config.model == "deepseek-v3"
        assert merged.config.temperature == 0.3
        assert merged.config.writing_style == "冷峻"
        # 未传 config 字段保留 existing 值（#225 核心：缺失字段不改）
        assert merged.config.agent_writer == "deepseek/deepseek-chat"
        assert merged.name == "旧名字"  # 顶层未传字段保持不变
        assert result is not None

    async def test_update_config_explicit_null_disables_role(self, svc, mock_repo) -> None:
        """#225 M1：PATCH config {agent_writer: null} → 显式 null 落库（关闭），其余字段保留。"""
        existing = _project(
            config=ProjectConfig(
                model="gpt-4o", agent_writer="deepseek/deepseek-chat", temperature=0.5
            )
        )
        mock_repo.get = AsyncMock(return_value=existing)

        # 显式传 None → fields_set 含 agent_writer → exclude_unset dump 保留 agent_writer: None
        await svc.update(PID, ProjectUpdate(config=ProjectConfig(agent_writer=None)))

        merged = mock_repo.update.await_args.args[0]
        assert isinstance(merged.config, ProjectConfig)
        assert merged.config.agent_writer is None  # 显式 null = 关闭
        assert merged.config.model == "gpt-4o"  # 未传字段保留
        assert merged.config.temperature == 0.5  # 未传字段保留

    async def test_update_config_missing_field_unchanged(self, svc, mock_repo) -> None:
        """#225 M1：PATCH config 缺失 agent_writer → 该字段不改（保留原字符串）。"""
        existing = _project(
            config=ProjectConfig(model="gpt-4o", agent_writer="deepseek/deepseek-chat")
        )
        mock_repo.get = AsyncMock(return_value=existing)

        await svc.update(PID, ProjectUpdate(config=ProjectConfig(model="deepseek-v3")))

        merged = mock_repo.update.await_args.args[0]
        assert isinstance(merged.config, ProjectConfig)
        assert merged.config.model == "deepseek-v3"  # 显式传的字段更新
        assert merged.config.agent_writer == "deepseek/deepseek-chat"  # 缺失字段不改

    async def test_update_config_sentinel_follows_default(self, svc, mock_repo) -> None:
        """#225 M3：sentinel "__default__" = 跟随默认（预留）——字符串值落库 roundtrip。"""
        existing = _project(config=ProjectConfig(model="gpt-4o"))
        mock_repo.get = AsyncMock(return_value=existing)

        await svc.update(PID, ProjectUpdate(config=ProjectConfig(agent_writer="__default__")))

        merged = mock_repo.update.await_args.args[0]
        assert isinstance(merged.config, ProjectConfig)
        assert merged.config.agent_writer == "__default__"
        assert merged.config.model == "gpt-4o"  # 未传字段保留


class TestProjectServiceBasics:
    """基础委托 — create/get/list/soft_delete/restore/hard_delete。"""

    async def test_create_project_builds_entity(self, svc, mock_repo) -> None:
        """创建项目 → repo.add 收到完整实体（默认 config、未软删）。"""
        created = await svc.create_project(
            name="新书",
            genre=Genre.KEHUAN,
            language="en-US",
            target_words=50_000,
        )
        assert created.name == "新书"
        added = mock_repo.add.await_args.args[0]
        assert isinstance(added, Project)
        assert isinstance(added.id, uuid.UUID)
        assert added.genre == Genre.KEHUAN
        assert added.language == "en-US"
        assert added.target_words == 50_000
        assert added.is_deleted is False
        assert added.config == ProjectConfig()

    async def test_get_returns_project_or_none(self, svc, mock_repo) -> None:
        """get 委托：UUID → int 转换；int id 直接透传；不存在 → None。"""
        project = _project()
        mock_repo.get = AsyncMock(return_value=project)
        assert await svc.get(PID) == project
        mock_repo.get.assert_awaited_once_with(PID.int)

        mock_repo.get = AsyncMock(return_value=None)
        assert await svc.get(42) is None
        mock_repo.get.assert_awaited_once_with(42)

    async def test_list_projects_forwards_filters(self, svc, mock_repo) -> None:
        """列表查询透传搜索/排序/分页参数。"""
        project = _project()
        mock_repo.list_all = AsyncMock(return_value=([project], 1))
        items, total = await svc.list_projects(
            search="玄幻", sort_by="name", sort_desc=False, offset=5, limit=10
        )
        assert items == [project]
        assert total == 1
        mock_repo.list_all.assert_awaited_once_with("玄幻", "name", False, 5, 10)

    async def test_soft_delete_restore_hard_delete(self, svc, mock_repo) -> None:
        """软删/恢复/硬删委托与返回值透传。"""
        assert await svc.soft_delete(PID) is True
        mock_repo.soft_delete.assert_awaited_once_with(PID.int)

        project = _project()
        mock_repo.restore = AsyncMock(return_value=project)
        assert await svc.restore(PID) == project
        mock_repo.restore.assert_awaited_once_with(PID.int)

        mock_repo.hard_delete = AsyncMock(return_value=False)
        assert await svc.hard_delete(999) is False
        mock_repo.hard_delete.assert_awaited_once_with(999)
