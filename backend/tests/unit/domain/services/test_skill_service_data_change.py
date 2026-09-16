"""SkillService 数据面变更事件测试（#1090 批次 B；spec §15.3.2/§15.3.3/§15.6.4）。

契约来源：W3C 设计裁定表 §2.8（父侧单一真相源）+ spec §15.3.3 四不变量。
skill 为**全局域**（文件系统真源，无项目归属）→ 事件 project_id 恒 None。
- create：文件写出成功后（方法末尾）→ skill/create，resource_id=name。
- update：**仅 content 写回路径**发 skill/update；updates 空 / 元数据合并路径（无持久化）
  → 不发（无实际变化）。
- delete：目录删除完成后 → skill/delete；NotFound / Builtin 走异常 → 不发。
- duplicate：copytree 成功后 → skill/create，resource_id=target_name。

依赖：真实 tmp_path 目录 + AsyncMock agent 仓储（镜像 test_skill_service.py 的形态）。
RED 阶段预期：正例断言 FAIL，负例可能已 PASS。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.skill import SkillCreate, SkillUpdate
from inkflow.domain.ports.skill_errors import SkillNameConflictError, SkillNotFoundError
from inkflow.domain.services.skill_service import SkillService

SKILL_NAME = "web-research"
SKILL_CONTENT = (
    "---\nname: web-research\ndescription: 网络调研方法论\n---\n# 调研流程\n1. 明确问题\n"
)
COPY_NAME = "web-research-copy"


def _write_skill(root: Path, name: str, content: str) -> Path:
    """手工写一个 skills_root/<name>/SKILL.md（模拟文件系统真源布局）。"""
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


@pytest.fixture
def mock_agent_repo() -> MagicMock:
    """Mock AgentRepositoryProtocol — 删除级联清引用用（默认无 Agent 引用）。"""
    repo = MagicMock()
    repo.list_agents_by_skill = AsyncMock(return_value=[])
    repo.update = AsyncMock()
    return repo


@pytest.fixture
def service(tmp_path: Path, mock_agent_repo: MagicMock) -> SkillService:
    """被测服务实例（tmp_path 文件系统真源 + Mock agent 仓储）。"""
    return SkillService(skills_root=tmp_path, agent_repository=mock_agent_repo)


class TestDataChangeEvents:
    """#1090 批次 B：skill 全局域写路径发布事件（project_id=None）。"""

    async def test_create_publishes_create(
        self, service: SkillService, tmp_path: Path, recorded_events
    ) -> None:
        """create 写文件成功 → skill/create，project_id=None（全局域）。"""
        created = await service.create(SkillCreate(content=SKILL_CONTENT))

        assert (tmp_path / SKILL_NAME / "SKILL.md").is_file()
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("skill", "create")
        assert event.resource_id == created.name
        assert event.project_id is None

    async def test_create_conflict_publishes_nothing(
        self, service: SkillService, tmp_path: Path, recorded_events
    ) -> None:
        """反例：同名目录已存在（写失败）→ 零发布。"""
        _write_skill(tmp_path, SKILL_NAME, SKILL_CONTENT)

        with pytest.raises(SkillNameConflictError):
            await service.create(SkillCreate(content=SKILL_CONTENT))

        assert recorded_events == []

    async def test_update_content_publishes_update(
        self, service: SkillService, tmp_path: Path, recorded_events
    ) -> None:
        """update 走 content 写回路径 → skill/update，project_id=None。"""
        _write_skill(tmp_path, SKILL_NAME, SKILL_CONTENT)
        new_content = SKILL_CONTENT.replace("# 调研流程", "# 调研流程（修订）")

        updated = await service.update(SKILL_NAME, SkillUpdate(content=new_content))

        assert updated.name == SKILL_NAME
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("skill", "update")
        assert event.resource_id == SKILL_NAME
        assert event.project_id is None

    async def test_update_metadata_only_publishes_nothing(
        self, service: SkillService, tmp_path: Path, recorded_events
    ) -> None:
        """反例：元数据合并路径（无持久化写入）→ 零发布（无实际变化）。"""
        _write_skill(tmp_path, SKILL_NAME, SKILL_CONTENT)

        await service.update(SKILL_NAME, SkillUpdate(description="新描述"))

        assert recorded_events == []

    async def test_update_missing_publishes_nothing(
        self, service: SkillService, recorded_events
    ) -> None:
        """反例：目标缺失（404 异常）→ 零发布。"""
        with pytest.raises(SkillNotFoundError):
            await service.update(SKILL_NAME, SkillUpdate(content=SKILL_CONTENT))

        assert recorded_events == []

    async def test_delete_publishes_delete(
        self, service: SkillService, tmp_path: Path, recorded_events
    ) -> None:
        """delete 目录删除完成 → skill/delete，project_id=None。"""
        _write_skill(tmp_path, SKILL_NAME, SKILL_CONTENT)

        await service.delete(SKILL_NAME)

        assert not (tmp_path / SKILL_NAME).exists()
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("skill", "delete")
        assert event.resource_id == SKILL_NAME
        assert event.project_id is None

    async def test_delete_missing_publishes_nothing(
        self, service: SkillService, recorded_events
    ) -> None:
        """反例：目标缺失（404 异常）→ 零发布。"""
        with pytest.raises(SkillNotFoundError):
            await service.delete(SKILL_NAME)

        assert recorded_events == []

    async def test_duplicate_publishes_create_for_target(
        self, service: SkillService, tmp_path: Path, recorded_events
    ) -> None:
        """duplicate copytree 成功 → skill/create，resource_id=target_name。"""
        _write_skill(tmp_path, SKILL_NAME, SKILL_CONTENT)

        duplicated = await service.duplicate(SKILL_NAME, new_name=COPY_NAME)

        assert (tmp_path / COPY_NAME / "SKILL.md").is_file()
        assert duplicated.name == COPY_NAME
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("skill", "create")
        assert event.resource_id == COPY_NAME
        assert event.project_id is None

    async def test_duplicate_conflict_publishes_nothing(
        self, service: SkillService, tmp_path: Path, recorded_events
    ) -> None:
        """反例：副本目录已存在（写失败）→ 零发布。"""
        _write_skill(tmp_path, SKILL_NAME, SKILL_CONTENT)
        _write_skill(tmp_path, COPY_NAME, SKILL_CONTENT)

        with pytest.raises(SkillNameConflictError):
            await service.duplicate(SKILL_NAME, new_name=COPY_NAME)

        assert recorded_events == []

    async def test_duplicate_missing_source_publishes_nothing(
        self, service: SkillService, recorded_events
    ) -> None:
        """反例：源缺失（404 异常）→ 零发布。"""
        with pytest.raises(SkillNotFoundError):
            await service.duplicate(SKILL_NAME)

        assert recorded_events == []
