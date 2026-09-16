"""MemoryService 数据面变更事件测试（#1090 批次 B；spec §15.3.2/§15.3.3/§15.6.4）。

契约来源：W3C 设计裁定表 §2.6（父侧单一真相源）+ spec §15.2.3 双作用域 + §15.3.3。
- 项目偏好（create/update/remove_preference）→ project_id 非 None。
- 用户偏好（create/update/remove_user_preference）→ project_id 恒 None（全局作用域）。
- summarize：实际生成/更新 summary 成功 → 一条 **域级** 事件
  (resource_id=str(project_id))；返回 summarized=False（无内容/未生成）→ 不发。
- remove_summaries：删除成功后发 (resource_id=str(project_id))；项目不存在 → 异常不发。
- record_draft_edit / record_draft_rejected / record_draft_confirmed /
  record_session_completed（自动学习链）→ **不发**（§15.6.4 中间态；memory 页挂载拉取已覆盖）。

依赖全 Mock 注入（镜像 test_memory_service.py / test_memory_service_m2_summarize.py 形态）。
⚠️ PID 取 `uuid.UUID(int=100)`：memory_service 的 summarize / get_summaries /
remove_summaries / is_learning_enabled 均带「128 位 int 溢出 → 早退」守卫，测试 UUID 的
.int 必须落在 int64 内，否则用例走的是溢出分支（假契约）。
RED 阶段预期：正例断言 FAIL，负例可能已 PASS。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.preference import PreferenceCategory, ProjectPreference
from inkflow.domain.models.user_preference import UserPreference
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.services.memory_service import MemoryService, PreferenceNotFoundError

PID = uuid.UUID(int=100)
#: 项目缺失用例用（int 落在 int64 内，避免触发 memory_service 的 128 位溢出早退守卫）
MISSING_PID = uuid.UUID(int=999)
TS = datetime(2026, 8, 1, 10, 0, 0)
LLM_MODEL = "deepseek/deepseek-v4-flash"


def _project(*, learning: bool = True) -> SimpleNamespace:
    """项目鸭子对象（Project.config.extra 语义 — F13 先例 dict 读取）。"""
    return SimpleNamespace(config=SimpleNamespace(extra={"memory_learning": learning}))


def _pref(*, preference_id: str = "pref-1") -> ProjectPreference:
    """构造测试用项目偏好实体（固定时间戳，便于断言）。"""
    return ProjectPreference(
        id=preference_id,
        project_id=PID,
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value="低声道",
        confidence=0.6,
        count=2,
        created_at=TS,
        updated_at=TS,
    )


def _user_pref(*, preference_id: str = "upref-1") -> UserPreference:
    """构造测试用用户级偏好实体（全局作用域，无 project_id 字段）。"""
    return UserPreference(
        id=preference_id,
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value="低声道",
        confidence=0.6,
        count=3,
        project_count=2,
        created_at=TS,
        updated_at=TS,
    )


def _summary_duck(*, anchor_hash: str = "hash-1") -> SimpleNamespace:
    """语义总结鸭子对象（SemanticSummary 语义 — 实现手动取字段）。"""
    return SimpleNamespace(
        id="sum-1",
        scope="project",
        project_id=PID,
        content="叙述偏好：用角色全名而非代词",
        anchor_hash=anchor_hash,
        anchor_count=5,
        model=LLM_MODEL,
        updated_at="2026-08-01T11:00:00+00:00",
    )


class _FakeLearner:
    """确定性 learner 替身（隔离提取算法）：id 恒哈希、不提候选。

    memory_service 构造缺省注入 preference_learner 真实模块（需
    anchor_hash / aggregate_candidates / confidence_for）；本文件只需
    锚点哈希确定性，故以最小替身注入，避免测试耦合提取算法。
    """

    def anchor_hash(self, anchors: object) -> str:
        """锚点哈希恒返回固定值（幂等复用分支可确定性驱动）。"""
        return "hash-1"

    def aggregate_candidates(self, events: object) -> list:
        """不提候选（record_draft_edit 零发布守卫用例只需流程走完）。"""
        return []

    def aggregate_user_candidates(self, events: object) -> list:
        """用户级链同构（M1）：不提候选。"""
        return []


@pytest.fixture
def mock_preference_repo() -> MagicMock:
    """Mock 项目偏好仓储（鸭子类型）。"""
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.create = AsyncMock(return_value=_pref())
    repo.update = AsyncMock(return_value=_pref())
    repo.delete = AsyncMock(return_value=True)
    repo.list_by_project = AsyncMock(return_value=([], 0))
    repo.count_by_project = AsyncMock(return_value=0)
    return repo


@pytest.fixture
def mock_user_preference_repo() -> MagicMock:
    """Mock 用户级偏好仓储（鸭子类型）。"""
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.create = AsyncMock(return_value=_user_pref())
    repo.update = AsyncMock(return_value=_user_pref())
    repo.delete = AsyncMock(return_value=True)
    repo.list_all = AsyncMock(return_value=([], 0))
    return repo


@pytest.fixture
def mock_event_repo() -> MagicMock:
    """Mock 记忆事件仓储（鸭子类型）。"""
    repo = MagicMock()
    repo.create = AsyncMock(side_effect=lambda **kw: SimpleNamespace(id="evt-1", **kw))
    repo.list_by_project = AsyncMock(return_value=([], 0))
    repo.list_edited_by_project = AsyncMock(return_value=[])
    repo.list_all_edited = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock 项目仓储 — 默认 memory_learning 开启。"""
    repo = MagicMock()
    repo.get = AsyncMock(return_value=_project())
    return repo


@pytest.fixture
def mock_summary_repo() -> MagicMock:
    """Mock 语义总结仓储（鸭子类型）。"""
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.upsert = AsyncMock()
    repo.delete_by_project = AsyncMock(return_value=1)
    return repo


@pytest.fixture
def mock_summarizer() -> MagicMock:
    """Mock 语义总结管线 — 默认产出有效 summary。"""
    summarizer = MagicMock()
    summarizer.summarize = AsyncMock(return_value=(_summary_duck(), 0))
    return summarizer


@pytest.fixture
def service(
    mock_preference_repo: MagicMock,
    mock_user_preference_repo: MagicMock,
    mock_event_repo: MagicMock,
    mock_project_repo: MagicMock,
    mock_summary_repo: MagicMock,
    mock_summarizer: MagicMock,
) -> MemoryService:
    """被测服务实例（全 Mock 依赖注入 + 确定性 learner 替身）。"""
    return MemoryService(
        preference_repo=mock_preference_repo,
        event_repo=mock_event_repo,
        project_repo=mock_project_repo,
        user_preference_repo=mock_user_preference_repo,
        summary_repo=mock_summary_repo,
        summarizer=mock_summarizer,
        llm_default_model=LLM_MODEL,
        learner=_FakeLearner(),
    )


class TestProjectPreferenceDataChange:
    """项目偏好 CRUD → project_id 非 None。"""

    async def test_create_preference_publishes_create(
        self, service: MemoryService, recorded_events
    ) -> None:
        """create_preference 成功 → memory/create，project_id 取形参。"""
        created = await service.create_preference(
            project_id=PID,
            category=PreferenceCategory.STYLE_WORD,
            pattern="说",
            value="低声道",
        )

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("memory", "create")
        assert event.resource_id == created.id
        assert event.project_id == str(PID)

    async def test_update_preference_publishes_update(
        self, service: MemoryService, mock_preference_repo: MagicMock, recorded_events
    ) -> None:
        """update_preference 成功 → memory/update，project_id 从已加载偏好解析。"""
        mock_preference_repo.get = AsyncMock(return_value=_pref(preference_id="pref-9"))

        updated = await service.update_preference("pref-9", value="轻声道")

        assert updated is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("memory", "update")
        assert event.resource_id == "pref-9"
        assert event.project_id == str(PID)

    async def test_update_preference_missing_publishes_nothing(
        self, service: MemoryService, mock_preference_repo: MagicMock, recorded_events
    ) -> None:
        """反例：偏好不存在（NotFound 异常）→ 零发布。"""
        mock_preference_repo.get = AsyncMock(return_value=None)

        with pytest.raises(PreferenceNotFoundError):
            await service.update_preference("pref-9", value="轻声道")

        assert recorded_events == []

    async def test_remove_preference_publishes_delete(
        self, service: MemoryService, mock_preference_repo: MagicMock, recorded_events
    ) -> None:
        """remove_preference 成功 → memory/delete，project_id 从已加载偏好解析。"""
        mock_preference_repo.get = AsyncMock(return_value=_pref(preference_id="pref-9"))

        removed = await service.remove_preference("pref-9")

        assert removed.id == "pref-9"
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("memory", "delete")
        assert event.resource_id == "pref-9"
        assert event.project_id == str(PID)

    async def test_remove_preference_missing_publishes_nothing(
        self, service: MemoryService, mock_preference_repo: MagicMock, recorded_events
    ) -> None:
        """反例：偏好不存在（NotFound 异常）→ 零发布。"""
        mock_preference_repo.get = AsyncMock(return_value=None)

        with pytest.raises(PreferenceNotFoundError):
            await service.remove_preference("pref-9")

        assert recorded_events == []


class TestUserPreferenceDataChange:
    """用户偏好 CRUD → project_id 恒 None（§15.2.3 全局作用域）。"""

    async def test_create_user_preference_publishes_none_project_id(
        self, service: MemoryService, recorded_events
    ) -> None:
        """create_user_preference 成功 → memory/create，project_id=None（全局域）。"""
        created = await service.create_user_preference(
            category=PreferenceCategory.STYLE_WORD, pattern="说", value="低声道"
        )

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("memory", "create")
        assert event.resource_id == created.id
        assert event.project_id is None

    async def test_update_user_preference_publishes_none_project_id(
        self, service: MemoryService, mock_user_preference_repo: MagicMock, recorded_events
    ) -> None:
        """update_user_preference 成功 → memory/update，project_id=None。"""
        mock_user_preference_repo.get = AsyncMock(return_value=_user_pref(preference_id="upref-9"))

        updated = await service.update_user_preference("upref-9", value="轻声道")

        assert updated is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("memory", "update")
        assert event.resource_id == "upref-9"
        assert event.project_id is None

    async def test_update_user_preference_missing_publishes_nothing(
        self, service: MemoryService, mock_user_preference_repo: MagicMock, recorded_events
    ) -> None:
        """反例：偏好不存在（NotFound 异常）→ 零发布。"""
        mock_user_preference_repo.get = AsyncMock(return_value=None)

        with pytest.raises(PreferenceNotFoundError):
            await service.update_user_preference("upref-9", value="轻声道")

        assert recorded_events == []

    async def test_remove_user_preference_publishes_none_project_id(
        self, service: MemoryService, mock_user_preference_repo: MagicMock, recorded_events
    ) -> None:
        """remove_user_preference 成功 → memory/delete，project_id=None。"""
        mock_user_preference_repo.get = AsyncMock(return_value=_user_pref(preference_id="upref-9"))

        removed = await service.remove_user_preference("upref-9")

        assert removed.id == "upref-9"
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("memory", "delete")
        assert event.resource_id == "upref-9"
        assert event.project_id is None

    async def test_remove_user_preference_missing_publishes_nothing(
        self, service: MemoryService, mock_user_preference_repo: MagicMock, recorded_events
    ) -> None:
        """反例：偏好不存在（NotFound 异常）→ 零发布。"""
        mock_user_preference_repo.get = AsyncMock(return_value=None)

        with pytest.raises(PreferenceNotFoundError):
            await service.remove_user_preference("upref-9")

        assert recorded_events == []


class TestSummaryDataChange:
    """语义总结写路径：域级单条事件（resource_id=str(project_id)）。"""

    async def test_summarize_generated_publishes_single_domain_event(
        self, service: MemoryService, recorded_events
    ) -> None:
        """summarize 实际生成 summary → 恰好一条 memory/update 域级事件。"""
        result = await service.summarize(PID)

        assert result["summarized"] is True
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("memory", "update")
        assert event.resource_id == str(PID)
        assert event.project_id == str(PID)

    async def test_summarize_not_generated_publishes_nothing(
        self, service: MemoryService, mock_summarizer: MagicMock, recorded_events
    ) -> None:
        """反例：summarized=False（未生成/无内容）→ 零发布。"""
        mock_summarizer.summarize = AsyncMock(return_value=(None, 0))

        result = await service.summarize(PID)

        assert result["summarized"] is False
        assert recorded_events == []

    async def test_summarize_learning_disabled_publishes_nothing(
        self, service: MemoryService, mock_project_repo: MagicMock, recorded_events
    ) -> None:
        """反例：memory_learning=false → summarized=False，零发布。"""
        mock_project_repo.get = AsyncMock(return_value=_project(learning=False))

        result = await service.summarize(PID)

        assert result["summarized"] is False
        assert recorded_events == []

    async def test_summarize_reused_summary_publishes_nothing(
        self,
        service: MemoryService,
        mock_summary_repo: MagicMock,
        mock_user_preference_repo: MagicMock,
        recorded_events,
    ) -> None:
        """反例：anchor_hash 相同且非 force（复用不调 LLM）→ summarized=False，零发布。"""
        mock_summary_repo.get = AsyncMock(return_value=_summary_duck(anchor_hash="hash-1"))
        mock_user_preference_repo.list_all = AsyncMock(return_value=([], 0))

        result = await service.summarize(PID)

        assert result["summarized"] is False
        assert recorded_events == []

    async def test_remove_summaries_publishes_domain_delete(
        self, service: MemoryService, recorded_events
    ) -> None:
        """remove_summaries 删除成功 → memory/delete 域级事件。"""
        result = await service.remove_summaries(PID)

        assert result["deleted"] is True
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("memory", "delete")
        assert event.resource_id == str(PID)
        assert event.project_id == str(PID)

    async def test_remove_summaries_project_missing_publishes_nothing(
        self, service: MemoryService, mock_project_repo: MagicMock, recorded_events
    ) -> None:
        """反例：项目不存在（异常）→ 零发布。"""
        mock_project_repo.get = AsyncMock(return_value=None)

        with pytest.raises(ProjectNotFoundError):
            await service.remove_summaries(MISSING_PID)

        assert recorded_events == []


class TestAutoLearningChainPublishesNothing:
    """自动学习链（§15.6.4 中间态）零发布守卫契约。"""

    async def test_record_draft_edit_publishes_nothing(
        self, service: MemoryService, recorded_events
    ) -> None:
        """record_draft_edit（learning 开启）→ 落事件但不发数据面变更事件。"""
        await service.record_draft_edit(draft_id="d-1", project_id=PID, before="旧文", after="新文")

        assert recorded_events == []

    async def test_record_draft_confirmed_publishes_nothing(
        self, service: MemoryService, recorded_events
    ) -> None:
        """record_draft_confirmed → 零发布。"""
        await service.record_draft_confirmed(draft_id="d-1", project_id=PID)

        assert recorded_events == []

    async def test_record_draft_rejected_publishes_nothing(
        self, service: MemoryService, recorded_events
    ) -> None:
        """record_draft_rejected → 零发布。"""
        await service.record_draft_rejected(draft_id="d-1", project_id=PID)

        assert recorded_events == []

    async def test_record_session_completed_publishes_nothing(
        self, service: MemoryService, recorded_events
    ) -> None:
        """record_session_completed（#1098 会话事件源）→ 零发布。"""
        await service.record_session_completed(
            session_id=uuid.uuid4(), project_id=PID, title="第三章续写", outcome="完成了对峙场景"
        )

        assert recorded_events == []
