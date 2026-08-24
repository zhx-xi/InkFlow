"""F28 M2 编排服务 RED 契约测试 — MemoryService（事件捕获/偏好 CRUD/统计，全 mock 轨）.
依据: specs/f28-agent-memory/spec.md（§5.1 事件捕获 / §5.2 提取 / §5.3 存储 /
§5.6 审计 / §5.7 统计 / §9 测试策略 / §13 M2 验收），父侧定稿契约同源
（test_memory_service.py docstring 即契约载体）。
被测模块（未实现，1c 整模块 RED 形态；顶层唯一 inkflow import = 主契约模块——
收集期整文件失败是预期（pytest exit 2 / collected 0 items / 1 error），GREEN 落地后
整文件自动收集）:
    from inkflow.domain.services.memory_service import (
        MemoryService, PreferenceNotFoundError,
    )
inkflow.domain.models.preference / memory_event 同缺但不顶层 import——测试体全 mock
轨 + SimpleNamespace 鸭子对象（service 依赖全鸭子类型，零模型构造），断言走 StrEnum
字符串字面量——收集错误只报主契约模块单一缺失。
设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. 错误类（domain/services/memory_service.py 内）:
       class PreferenceNotFoundError(Exception):
           # 默认消息「偏好不存在」（删除不存在偏好时抛出）
2. MemoryService 构造（全鸭子类型依赖）:
       def __init__(self, *, preference_repo, event_repo, project_repo,
                    audit_service=None, learner=None): ...
3. 方法契约（父侧定稿，逐字）:
       async def is_learning_enabled(self, project_id,
                                      override: bool | None = None) -> bool
           # override 显式 > project.config.extra["memory_learning"] > 默认 False
       async def record_draft_edit(self, *, draft_id, project_id,
                                   chapter_id=None, before, after,
                                   agent_run_id=None) -> MemoryEvent | None
           # memory_learning=false → 不落事件不提取不审计，返回 None（零行为）；
           # true → 落 MemoryEvent(DRAFT_EDITED,
           #   diff_chars=len(after)-len(before))，然后 aggregate 全部 edited
           # 事件：候选 value 已在库 → update(count+1, confidence 重算,
           #   source_events 追加)；不在库且 count>=2 → create(count=候选 count)；
           # 新偏好 create 时审计 audit_service.record(actor="memory",
           #   severity_summary="preference_learned", ...)；返回落库的 MemoryEvent。
       async def record_draft_rejected(self, *, draft_id, project_id,
                                       chapter_id=None) -> MemoryEvent | None
           # 落 MemoryEvent(DRAFT_REJECTED)；关闭 → None（零行为）
           # rejected 不提取（spec §5.2）——本文件不锁聚合调用
       async def record_draft_confirmed(self, *, draft_id, project_id,
                                        chapter_id=None) -> MemoryEvent | None
           # 落 MemoryEvent(DRAFT_CONFIRMED)；关闭 → None（零行为）
       async def list_preferences(self, project_id, category=None
                                  ) -> tuple[list[ProjectPreference], int]
           # 透传 preference_repo.list_by_project(project_id, category=category)
       async def remove_preference(self, preference_id) -> ProjectPreference
           # 不存在 → PreferenceNotFoundError；删除后审计 preference_removed
       async def get_preferences_for_injection(self, project_id
                                               ) -> list[ProjectPreference]
           # 开关 false → []；实时查库无缓存；count desc 排序
       async def stats(self, project_id) -> dict
           # {"project_id": str, "agentic": {"chapters": int,
           #   "direct_confirms": int, "avg_diff_chars": int,
           #   "modify_rate": float, "regenerate_rate": float},
           #  "learned_preferences": int,
           #  "baseline_ref": "docs/agent-baseline-2026-08-10.md"}
           # chapters = confirmed+rejected 事件数；direct_confirms = confirmed 数
           # modify_rate = (chapters-direct_confirms)/chapters（chapters=0→0.0）
           # avg_diff_chars = Σ|diff_chars| / edited 事件数（0 事件→0）
           # regenerate_rate = rejected/chapters（0→0.0）
           # learned_preferences = 库中偏好总数
4. 测试侧钉死的依赖形态（全鸭子类型，repo 命名镜像 F27 draft_repo 惯例）:
       project_repo.get(project_id) -> Project | None
           # 读取 project.config.extra["memory_learning"]（缺失 → False）
       event_repo.create(event) -> MemoryEvent          # 单位置参数，返回落库事件
       event_repo.list_by_project(project_id) -> list[MemoryEvent]
       preference_repo.list_by_project(project_id, category=None)
           -> tuple[list[ProjectPreference], int]
       preference_repo.get(preference_id) -> ProjectPreference | None
       preference_repo.create(*, project_id, category, pattern, value, count,
                              confidence, source_events) -> ProjectPreference
       preference_repo.update(preference_id, *, count, confidence, source_events)
           -> ProjectPreference | None
       preference_repo.delete(preference_id) -> bool
       preference_repo.count_by_project(project_id) -> int
       audit_service.record(*, project_id, ..., severity_summary, actor, ...)
           # F34 签名；本文件只钉 actor / severity_summary 两 kwarg
5. 学习器注入（learner 注入 fake，隔离提取算法——本文件不 import preference_learner，
   RED 时模块缺失；GREEN 时服务经 learner 调用真实实现）:
       fake.aggregate_candidates(events) -> list[候选]
           # 候选 = (category, pattern, value, count, confidence) 鸭子对象
       fake.confidence_for(count) -> float  # 1 - 1/(count+1)（update 重算用）
6. 级联不在本批（父侧契约 8 方法无 delete_by_project 入口）:
   项目删除级联（偏好/事件清理）归跨模块钩子批（规则 1k，MODIFY project_service
   接线，spec §5.3/§8）——本文件不测，GREEN 批另行覆盖。
RED 预期
--------
全文件收集期失败（1c 整模块 RED 形态: pytest exit 2 / collected 0 items / 1 error）:
    ModuleNotFoundError: No module named 'inkflow.domain.services.memory_service'
（父包 inkflow.domain.services 已存在、子模块文件缺失 → ModuleNotFoundError）
asyncio 模式: 本 venv（pytest-asyncio）实测头部 asyncio: mode=Mode.AUTO
（pyproject asyncio_mode = "auto" 生效）；文件级 pytestmark = pytest.mark.asyncio
双保险（STRICT/AUTO 两种模式均成立），全部用例 async def。
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.services.memory_service import (
    MemoryService,
    PreferenceNotFoundError,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO
PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
class FakeLearner:
    """注入 fake（隔离提取算法；本文件不 import preference_learner）.
    results: 每次 aggregate_candidates 依次弹出的候选列表，耗尽后返回 []。
    confidence_for: 复刻契约公式 1 - 1/(count+1)。
    """

    def __init__(self, results=None) -> None:
        self._results = list(results or [])
        self.aggregate_calls = 0

    def aggregate_candidates(self, events):
        self.aggregate_calls += 1
        if self._results:
            return self._results.pop(0)
        return []

    def confidence_for(self, count: int) -> float:
        return 1 - 1 / (count + 1)


def _candidate(
    value="低声道", *, category="style_word", pattern="说", count=2, confidence=None
) -> SimpleNamespace:
    """候选鸭子对象（PreferenceCandidate 语义）."""
    return SimpleNamespace(
        category=category,
        pattern=pattern,
        value=value,
        count=count,
        confidence=confidence if confidence is not None else 1 - 1 / (count + 1),
    )


def _pref(
    value="低声道",
    *,
    pref_id="pref-1",
    count=1,
    source_events=None,
    category="style_word",
    pattern="说",
    confidence=0.5,
) -> SimpleNamespace:
    """既有偏好鸭子对象（ProjectPreference 语义）."""
    return SimpleNamespace(
        id=pref_id,
        project_id=PROJECT_ID,
        category=category,
        pattern=pattern,
        value=value,
        confidence=confidence,
        count=count,
        source_events=list(source_events or []),
    )


def _event(event_type="draft_edited", *, diff_chars=0, event_id="evt-x") -> SimpleNamespace:
    """事件鸭子对象（MemoryEvent 语义）."""
    return SimpleNamespace(
        id=event_id,
        project_id=PROJECT_ID,
        event_type=event_type,
        diff_chars=diff_chars,
    )


def _project(extra: dict) -> SimpleNamespace:
    """项目鸭子对象（Project.config.extra 语义——F13 先例 dict 读取）."""
    return SimpleNamespace(config=SimpleNamespace(extra=extra))


def _make_service(learner=None, extra=None) -> tuple[MemoryService, dict]:
    """构造服务 + 依赖字典；全部 repo 方法显式默认值（裸 AsyncMock 陷阱防护）."""
    deps = {
        "preference_repo": AsyncMock(),
        "event_repo": AsyncMock(),
        "project_repo": AsyncMock(),
        "audit_service": AsyncMock(),
    }
    deps["preference_repo"].list_by_project.return_value = ([], 0)
    deps["preference_repo"].count_by_project.return_value = 0
    deps["preference_repo"].get.return_value = None
    deps["preference_repo"].create.return_value = _pref(pref_id="pref-new")
    deps["preference_repo"].update.return_value = None
    deps["preference_repo"].delete.return_value = True
    deps["event_repo"].create.return_value = SimpleNamespace(id="evt-1", event_type="draft_edited")
    deps["event_repo"].list_by_project.return_value = (
        [],
        0,
    )  # #249 契约修正：真实 repo 返回 (list, total) 元组
    deps["project_repo"].get.return_value = _project(extra or {})
    service = MemoryService(
        preference_repo=deps["preference_repo"],
        event_repo=deps["event_repo"],
        project_repo=deps["project_repo"],
        audit_service=deps["audit_service"],
        learner=learner or FakeLearner(),
    )
    return service, deps


def _arg(call, name, pos=None, default=None):
    """从 mock call 宽松取参（关键字优先，位置回退）——不锁实现传参形态."""
    if name in call.kwargs:
        return call.kwargs[name]
    if pos is not None and len(call.args) > pos:
        return call.args[pos]
    return default


def _audit_call(audit_service: AsyncMock, summary: str):
    """返回 audit_service.record 中 severity_summary == summary 的首个 call."""
    for c in audit_service.record.await_args_list:
        if _arg(c, "severity_summary", 4) == summary:
            return c
    return None


# ── 契约 1: is_learning_enabled 三态 ──


async def test_is_learning_enabled_override_true_wins() -> None:
    """契约①a: override=True 覆盖 extra=False → True."""
    service, _ = _make_service(extra={"memory_learning": False})
    assert await service.is_learning_enabled(PROJECT_ID, override=True) is True


async def test_is_learning_enabled_extra_true_no_override() -> None:
    """契约①b: extra=True 且无 override → True."""
    service, _ = _make_service(extra={"memory_learning": True})
    assert await service.is_learning_enabled(PROJECT_ID) is True


async def test_is_learning_enabled_default_false() -> None:
    """契约①c: 无 override 且 extra 无键 → 默认 False."""
    service, _ = _make_service()
    assert await service.is_learning_enabled(PROJECT_ID) is False


async def test_is_learning_enabled_override_false_wins() -> None:
    """契约①d: override=False 覆盖 extra=True → False."""
    service, _ = _make_service(extra={"memory_learning": True})
    assert await service.is_learning_enabled(PROJECT_ID, override=False) is False


async def test_is_learning_enabled_project_missing_false() -> None:
    """契约①e: 项目不存在（repo.get → None）→ False（QA 补测 2026-08-11，覆盖 83 行）."""
    service, deps = _make_service(extra={"memory_learning": True})
    deps["project_repo"].get.return_value = None
    assert await service.is_learning_enabled(PROJECT_ID) is False


# ── 契约 2: record_draft_edit（事件捕获 + 阈值学习） ──


async def test_record_draft_edit_disabled_zero_behavior() -> None:
    """契约②: memory_learning=false → 不落事件不提取不审计，返回 None."""
    learner = FakeLearner()
    service, deps = _make_service(learner=learner)
    result = await service.record_draft_edit(
        draft_id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        before="旧版内容",
        after="新版内容更长",
        agent_run_id="run-1",
    )
    assert result is None
    deps["event_repo"].create.assert_not_awaited()
    deps["audit_service"].record.assert_not_awaited()
    deps["preference_repo"].create.assert_not_awaited()
    assert learner.aggregate_calls == 0  # 不提取


async def test_record_draft_edit_enabled_persists_event() -> None:
    """契约③: 开启时落 DRAFT_EDITED 事件（字段透传；diff_chars 由 repo 层计算）.

    父侧定稿（2026-08-11）: event_repo.create 契约为字段展开形态
    （镜像 F27 draft_repo.create——repo 测试 docstring 同源）；diff_chars
    无契约参数，由 repo 内部按 len(after)-len(before) 计算。
    """
    service, deps = _make_service(extra={"memory_learning": True})
    result = await service.record_draft_edit(
        draft_id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        before="旧版内容",
        after="新版内容更长",
        agent_run_id="run-1",
    )
    deps["event_repo"].create.assert_awaited_once()
    call = deps["event_repo"].create.await_args
    assert _arg(call, "event_type", 4) == "draft_edited"
    assert _arg(call, "project_id", 0) == PROJECT_ID
    assert _arg(call, "draft_id", 1) == "draft-1"
    assert _arg(call, "chapter_id", 2) == CHAPTER_ID
    assert _arg(call, "agent_run_id", 3) == "run-1"
    assert _arg(call, "before_content", 5) == "旧版内容"
    assert _arg(call, "after_content", 6) == "新版内容更长"
    assert result is deps["event_repo"].create.return_value  # 返回落库事件


async def test_record_draft_edit_threshold_no_preference_on_first() -> None:
    """契约④a: 候选 count=1 → 偏好不落库（阈值语义 N≥2）."""
    learner = FakeLearner(results=[[_candidate(count=1)]])
    service, deps = _make_service(extra={"memory_learning": True}, learner=learner)
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    deps["preference_repo"].create.assert_not_awaited()
    assert learner.aggregate_calls == 1


async def test_record_draft_edit_threshold_creates_on_second() -> None:
    """契约④b: 候选 count=2 → 偏好落库（create count=候选 count）."""
    learner = FakeLearner(results=[[_candidate(count=2)]])
    service, deps = _make_service(extra={"memory_learning": True}, learner=learner)
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    deps["preference_repo"].create.assert_awaited_once()
    call = deps["preference_repo"].create.await_args
    assert _arg(call, "count", 4) == 2
    assert _arg(call, "value", 3) == "低声道"
    assert _arg(call, "project_id", 0) == PROJECT_ID


async def test_record_draft_edit_existing_preference_updates() -> None:
    """契约⑤: 候选 value 已在库 → update(count+1, confidence 重算,
    source_events 追加)，不 create."""
    learner = FakeLearner(results=[[_candidate(count=2)]])
    service, deps = _make_service(extra={"memory_learning": True}, learner=learner)
    deps["preference_repo"].list_by_project.return_value = (
        [_pref(count=1, source_events=["evt-1"])],
        1,
    )
    deps["event_repo"].create.return_value = SimpleNamespace(id="evt-2", event_type="draft_edited")
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    deps["preference_repo"].create.assert_not_awaited()
    deps["preference_repo"].update.assert_awaited_once()
    call = deps["preference_repo"].update.await_args
    assert _arg(call, "preference_id", 0) == "pref-1"
    assert _arg(call, "count", 1) == 2  # count+1（原 1）
    assert _arg(call, "confidence", 2) == pytest.approx(2 / 3)  # 1 - 1/(2+1)
    assert _arg(call, "source_events", 3) == ["evt-1", "evt-2"]  # 追加新事件 id


async def test_record_draft_edit_audit_on_new_preference() -> None:
    """契约⑥: 新偏好 create 时审计 actor="memory",
    severity_summary="preference_learned"."""
    learner = FakeLearner(results=[[_candidate(count=2)]])
    service, deps = _make_service(extra={"memory_learning": True}, learner=learner)
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    call = _audit_call(deps["audit_service"], "preference_learned")
    assert call is not None
    assert _arg(call, "actor", 8) == "memory"


# ── 契约 3: record_draft_rejected / record_draft_confirmed ──


async def test_record_draft_rejected_disabled_none() -> None:
    """契约⑦a: 关闭时拒绝草稿 → 零行为（返回 None，不落事件）."""
    service, deps = _make_service()
    result = await service.record_draft_rejected(
        draft_id="draft-1", project_id=PROJECT_ID, chapter_id=CHAPTER_ID
    )
    assert result is None
    deps["event_repo"].create.assert_not_awaited()


async def test_record_draft_rejected_enabled_persists() -> None:
    """契约⑦b: 开启时落 DRAFT_REJECTED 事件（字段透传；diff_chars 由 repo 计算）."""
    service, deps = _make_service(extra={"memory_learning": True})
    result = await service.record_draft_rejected(
        draft_id="draft-1", project_id=PROJECT_ID, chapter_id=CHAPTER_ID
    )
    deps["event_repo"].create.assert_awaited_once()
    call = deps["event_repo"].create.await_args
    assert _arg(call, "event_type", 4) == "draft_rejected"
    assert _arg(call, "project_id", 0) == PROJECT_ID
    assert result is deps["event_repo"].create.return_value


async def test_record_draft_confirmed_enabled_persists() -> None:
    """契约⑦c: 开启时落 DRAFT_CONFIRMED 事件."""
    service, deps = _make_service(extra={"memory_learning": True})
    result = await service.record_draft_confirmed(
        draft_id="draft-1", project_id=PROJECT_ID, chapter_id=CHAPTER_ID
    )
    deps["event_repo"].create.assert_awaited_once()
    call = deps["event_repo"].create.await_args
    assert _arg(call, "event_type", 4) == "draft_confirmed"
    assert _arg(call, "project_id", 0) == PROJECT_ID
    assert result is deps["event_repo"].create.return_value


async def test_record_draft_confirmed_disabled_none() -> None:
    """契约⑦d: 关闭时确认草稿 → 零行为（返回 None，不落事件）（QA 补测 2026-08-11，覆盖 222 行）."""
    service, deps = _make_service()
    result = await service.record_draft_confirmed(
        draft_id="draft-1", project_id=PROJECT_ID, chapter_id=CHAPTER_ID
    )
    assert result is None
    deps["event_repo"].create.assert_not_awaited()


# ── 契约 4: list_preferences ──


async def test_list_preferences_returns_tuple() -> None:
    """契约⑧a: 返回 (items, total) 元组（repo 结果透传）."""
    service, deps = _make_service()
    prefs = [_pref()]
    deps["preference_repo"].list_by_project.return_value = (prefs, 1)
    items, total = await service.list_preferences(PROJECT_ID)
    assert items is prefs
    assert total == 1


async def test_list_preferences_category_filter_forwarded() -> None:
    """契约⑧b: category 过滤参数透传 repo."""
    service, deps = _make_service()
    await service.list_preferences(PROJECT_ID, category="addressing")
    deps["preference_repo"].list_by_project.assert_awaited_once()
    call = deps["preference_repo"].list_by_project.await_args
    assert _arg(call, "project_id", 0) == PROJECT_ID
    assert _arg(call, "category", 1) == "addressing"


# ── 契约 5: remove_preference ──


async def test_remove_preference_missing_raises() -> None:
    """契约⑨a: 不存在 → PreferenceNotFoundError（默认消息「偏好不存在」）."""
    service, deps = _make_service()
    deps["preference_repo"].get.return_value = None
    with pytest.raises(PreferenceNotFoundError) as exc:
        await service.remove_preference("pref-missing")
    assert "偏好不存在" in str(exc.value)


async def test_remove_preference_existing_deletes_and_audits() -> None:
    """契约⑨b: 存在 → 删除 + 审计 preference_removed，返回被删偏好."""
    service, deps = _make_service()
    pref = _pref()
    deps["preference_repo"].get.return_value = pref
    result = await service.remove_preference("pref-1")
    assert result is pref
    deps["preference_repo"].delete.assert_awaited_once()
    call = deps["preference_repo"].delete.await_args
    assert _arg(call, "preference_id", 0) == "pref-1"
    audit_call = _audit_call(deps["audit_service"], "preference_removed")
    assert audit_call is not None
    assert _arg(audit_call, "actor", 8) == "memory"


# ── 契约 6: get_preferences_for_injection ──


async def test_get_preferences_for_injection_disabled_empty() -> None:
    """契约⑩a: 开关 false → []（零注入）."""
    service, _ = _make_service()
    assert await service.get_preferences_for_injection(PROJECT_ID) == []


async def test_get_preferences_for_injection_enabled_sorted() -> None:
    """契约⑩b: 开启 → 实时查库 + count desc 排序（无缓存，重复调用再查）."""
    service, deps = _make_service(extra={"memory_learning": True})
    low = _pref(count=2)
    high = _pref(count=5, pref_id="pref-2", value="林晚")
    deps["preference_repo"].list_by_project.return_value = ([low, high], 2)
    result = await service.get_preferences_for_injection(PROJECT_ID)
    assert result == [high, low]  # count 5 > 2
    result2 = await service.get_preferences_for_injection(PROJECT_ID)
    assert result2 == [high, low]
    assert len(deps["preference_repo"].list_by_project.await_args_list) == 2


# ── 契约 7: stats 统计口径 ──


async def test_stats_math() -> None:
    """契约⑪a: 事件序列 → chapters/direct_confirms/modify_rate/
    avg_diff_chars/regenerate_rate 数学正确."""
    service, deps = _make_service()
    deps["event_repo"].list_by_project.return_value = (
        [  # #249 契约修正：真实 repo 返回 (list, total) 元组（memory_event_repo.py L102）
            _event("draft_edited", diff_chars=5, event_id="e1"),
            _event("draft_edited", diff_chars=-3, event_id="e2"),
            _event("draft_confirmed", event_id="e3"),
            _event("draft_confirmed", event_id="e4"),
            _event("draft_rejected", event_id="e5"),
        ],
        5,
    )
    deps["preference_repo"].count_by_project.return_value = 3
    stats = await service.stats(PROJECT_ID)
    assert stats["project_id"] == str(PROJECT_ID)
    agentic = stats["agentic"]
    assert agentic["chapters"] == 3  # confirmed 2 + rejected 1
    assert agentic["direct_confirms"] == 2
    assert agentic["modify_rate"] == pytest.approx(1 / 3)  # (3-2)/3
    assert agentic["avg_diff_chars"] == 4  # (|5|+|-3|)/2
    assert agentic["regenerate_rate"] == pytest.approx(1 / 3)  # 1/3
    assert stats["learned_preferences"] == 3
    assert stats["baseline_ref"] == "docs/agent-baseline-2026-08-10.md"


async def test_stats_empty_project_zero_guards() -> None:
    """契约⑪b: 无事件 → 全零指标（除零守卫）."""
    service, _ = _make_service()
    stats = await service.stats(PROJECT_ID)
    agentic = stats["agentic"]
    assert agentic["chapters"] == 0
    assert agentic["modify_rate"] == 0.0
    assert agentic["avg_diff_chars"] == 0
    assert agentic["regenerate_rate"] == 0.0
    assert stats["learned_preferences"] == 0


# ── 契约 8: #521 手动创建/编辑记忆（create_preference / create_user_preference /
#    update_preference / update_user_preference；决策 2026-08-20 拍板） ──


def _user_pref(
    value="低声道",
    *,
    pref_id="upref-1",
    count=2,
    confidence=0.67,
    project_count=1,
    source_projects=None,
    source_events=None,
    category="style_word",
    pattern="说",
) -> SimpleNamespace:
    """用户级偏好鸭子对象（UserPreference 语义，#521）."""
    return SimpleNamespace(
        id=pref_id,
        category=category,
        pattern=pattern,
        value=value,
        confidence=confidence,
        count=count,
        project_count=project_count,
        source_projects=list(source_projects or []),
        source_events=list(source_events or []),
    )


def _make_service_manual(*, pref=None, user_pref=None, user_repo_installed=True):
    """#521 手动创建/编辑轨构造（镜像 _make_service，叠加 user_preference_repo）.

    pref/user_pref 非 None → 对应 repo.get 返回该既有偏好（update 前读取）;
    user_repo_installed=False → user_preference_repo=None（未装配轨）.
    """
    deps = {
        "preference_repo": AsyncMock(),
        "event_repo": AsyncMock(),
        "project_repo": AsyncMock(),
        "audit_service": AsyncMock(),
    }
    deps["preference_repo"].list_by_project.return_value = ([], 0)
    deps["preference_repo"].count_by_project.return_value = 0
    deps["preference_repo"].get.return_value = pref
    deps["preference_repo"].create.return_value = _pref(pref_id="pref-new")
    deps["preference_repo"].update.return_value = _pref(pref_id="pref-updated")
    deps["preference_repo"].delete.return_value = True
    deps["event_repo"].create.return_value = SimpleNamespace(id="evt-1", event_type="draft_edited")
    deps["event_repo"].list_by_project.return_value = ([], 0)
    deps["project_repo"].get.return_value = _project({})
    if user_repo_installed:
        deps["user_preference_repo"] = AsyncMock()
        deps["user_preference_repo"].get.return_value = user_pref
        deps["user_preference_repo"].create.return_value = _user_pref(pref_id="upref-new")
        deps["user_preference_repo"].update.return_value = _user_pref(pref_id="upref-updated")
        deps["user_preference_repo"].list_all.return_value = ([], 0)
    else:
        deps["user_preference_repo"] = None
    service = MemoryService(
        preference_repo=deps["preference_repo"],
        event_repo=deps["event_repo"],
        project_repo=deps["project_repo"],
        audit_service=deps["audit_service"],
        learner=FakeLearner(),
        user_preference_repo=deps["user_preference_repo"],
    )
    return service, deps


async def test_create_preference_persists_via_repo() -> None:
    """契约⑫a (#521): create_preference 手动创建项目偏好——confidence/count
    缺省落 1.0/1，source_events=[]，透传 repo.create 返回值.

    设计假设（父侧定稿，逐字签名）:

        async def create_preference(
            self, *, project_id: uuid.UUID,
            category: PreferenceCategory, pattern: str, value: str,
            confidence: float | None = None, count: int | None = None,
        ) -> ProjectPreference: ...

    语义: confidence 缺省 1.0、count 缺省 1、source_events=[]；调
    self._preference_repo.create(project_id=..., category=..., pattern=...,
    value=..., confidence=..., count=..., source_events=[])；返回落库偏好.
    """
    # 惰性：StrEnum 枚举类型（顶层唯一 inkflow import = 主契约模块惯例）
    from inkflow.domain.models.preference import PreferenceCategory

    service, deps = _make_service_manual()
    result = await service.create_preference(
        project_id=PROJECT_ID,
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value="低声道",
    )
    deps["preference_repo"].create.assert_awaited_once_with(
        project_id=PROJECT_ID,
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value="低声道",
        confidence=1.0,
        count=1,
        source_events=[],
    )
    assert result is deps["preference_repo"].create.return_value  # 透传落库偏好


async def test_create_user_preference_persists_via_repo() -> None:
    """契约⑫b (#521): create_user_preference 手动创建用户级偏好——confidence
    缺省 1.0、count 缺省 1、project_count=1、source_projects/source_events=[].

    设计假设（父侧定稿，逐字签名）:

        async def create_user_preference(
            self, *, category: PreferenceCategory, pattern: str, value: str,
            confidence: float | None = None, count: int | None = None,
        ) -> UserPreference: ...

    语义: 调 self._user_preference_repo.create(category=..., pattern=...,
    value=..., confidence=..., count=..., project_count=1,
    source_projects=[], source_events=[])；返回落库偏好.
    """
    from inkflow.domain.models.preference import PreferenceCategory

    service, deps = _make_service_manual()
    result = await service.create_user_preference(
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value="低声道",
    )
    deps["user_preference_repo"].create.assert_awaited_once_with(
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value="低声道",
        confidence=1.0,
        count=1,
        project_count=1,
        source_projects=[],
        source_events=[],
    )
    assert result is deps["user_preference_repo"].create.return_value


async def test_create_user_preference_uninstalled_raises() -> None:
    """契约⑫c (#521): user_preference_repo 未装配 → PreferenceNotFoundError."""
    service, _ = _make_service_manual(user_repo_installed=False)
    with pytest.raises(PreferenceNotFoundError):
        await service.create_user_preference(category="style_word", pattern="说", value="低声道")


async def test_update_preference_edits_fields_and_forwards_stats() -> None:
    """契约⑬a (#521): update_preference 编辑 category/pattern/value，透传既有
    统计字段（count/confidence/source_events）给 repo.update.

    设计假设（父侧定稿，逐字签名）:

        async def update_preference(
            self, preference_id: str, *,
            category: PreferenceCategory | None = None,
            pattern: str | None = None, value: str | None = None,
        ) -> ProjectPreference: ...

    语义: self._preference_repo.get(preference_id) → None →
    PreferenceNotFoundError；否则调 self._preference_repo.update(
    preference_id, count=pref.count, confidence=pref.confidence,
    source_events=pref.source_events, category=category, pattern=pattern,
    value=value)；返回更新后偏好.
    """
    from inkflow.domain.models.preference import PreferenceCategory

    pref = _pref(pref_id="pref-1", count=2, confidence=0.67, source_events=["e1"])
    service, deps = _make_service_manual(pref=pref)
    updated = _pref(
        pref_id="pref-1",
        count=2,
        confidence=0.67,
        source_events=["e1"],
        category="style_word",
        pattern="说",
        value="低声道",
    )
    deps["preference_repo"].update.return_value = updated
    result = await service.update_preference(
        "pref-1",
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value="低声道",
    )
    deps["preference_repo"].get.assert_awaited_once_with("pref-1")
    deps["preference_repo"].update.assert_awaited_once_with(
        "pref-1",
        count=2,
        confidence=0.67,
        source_events=["e1"],
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value="低声道",
    )
    assert result is updated  # 返回更新后偏好


async def test_update_preference_missing_raises_without_update() -> None:
    """契约⑬b (#521): get → None → PreferenceNotFoundError 且 update 未调用."""
    service, deps = _make_service_manual(pref=None)
    with pytest.raises(PreferenceNotFoundError):
        await service.update_preference(
            "pref-missing", category="style_word", pattern="说", value="低声道"
        )
    deps["preference_repo"].update.assert_not_awaited()


async def test_update_user_preference_edits_fields_and_forwards_stats() -> None:
    """契约⑭a (#521): update_user_preference 编辑字段 + 透传 user 版统计字段
    （count/confidence/project_count/source_projects/source_events）.

    设计假设（父侧定稿，逐字签名）:

        async def update_user_preference(
            self, preference_id: str, *,
            category: PreferenceCategory | None = None,
            pattern: str | None = None, value: str | None = None,
        ) -> UserPreference: ...

    语义: self._user_preference_repo is None → PreferenceNotFoundError；
    get → None → PreferenceNotFoundError；调 self._user_preference_repo.update(
    preference_id, count=pref.count, confidence=pref.confidence,
    project_count=pref.project_count, source_projects=pref.source_projects,
    source_events=pref.source_events, category=category, pattern=pattern,
    value=value)；返回更新后偏好.
    """
    from inkflow.domain.models.preference import PreferenceCategory

    user_pref = _user_pref(
        pref_id="upref-1",
        count=2,
        confidence=0.67,
        project_count=2,
        source_projects=["proj-a"],
        source_events=["e1"],
    )
    service, deps = _make_service_manual(user_pref=user_pref)
    updated = _user_pref(
        pref_id="upref-1",
        count=2,
        confidence=0.67,
        project_count=2,
        source_projects=["proj-a"],
        source_events=["e1"],
        category="style_word",
        pattern="说",
        value="低声道",
    )
    deps["user_preference_repo"].update.return_value = updated
    result = await service.update_user_preference(
        "upref-1",
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value="低声道",
    )
    deps["user_preference_repo"].get.assert_awaited_once_with("upref-1")
    deps["user_preference_repo"].update.assert_awaited_once_with(
        "upref-1",
        count=2,
        confidence=0.67,
        project_count=2,
        source_projects=["proj-a"],
        source_events=["e1"],
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value="低声道",
    )
    assert result is updated  # 返回更新后偏好


async def test_update_user_preference_uninstalled_raises() -> None:
    """契约⑭b (#521): user_preference_repo 未装配 → PreferenceNotFoundError."""
    service, _ = _make_service_manual(user_repo_installed=False)
    with pytest.raises(PreferenceNotFoundError):
        await service.update_user_preference(
            "upref-1", category="style_word", pattern="说", value="低声道"
        )



# ── 契约 15: remove_summaries（#619 F49 ③ 语义总结删除，Q2=B 越闸） ──


def _make_service_with_summary(extra: dict | None = None) -> tuple[MemoryService, dict]:
    """#619 删除轨构造（镜像 _make_service，叠加 summary_repo 注入）。

    summary_repo.delete_by_project 默认返回 0（幂等语义——无行可删也成功）。
    """
    deps = {
        "preference_repo": AsyncMock(),
        "event_repo": AsyncMock(),
        "project_repo": AsyncMock(),
        "audit_service": AsyncMock(),
        "summary_repo": AsyncMock(),
    }
    deps["preference_repo"].list_by_project.return_value = ([], 0)
    deps["preference_repo"].count_by_project.return_value = 0
    deps["preference_repo"].get.return_value = None
    deps["preference_repo"].create.return_value = _pref(pref_id="pref-new")
    deps["preference_repo"].update.return_value = None
    deps["preference_repo"].delete.return_value = True
    deps["event_repo"].create.return_value = SimpleNamespace(id="evt-1", event_type="draft_edited")
    deps["event_repo"].list_by_project.return_value = ([], 0)
    deps["project_repo"].get.return_value = _project(extra or {})
    deps["summary_repo"].delete_by_project.return_value = 0
    service = MemoryService(
        preference_repo=deps["preference_repo"],
        event_repo=deps["event_repo"],
        project_repo=deps["project_repo"],
        audit_service=deps["audit_service"],
        learner=FakeLearner(),
        summary_repo=deps["summary_repo"],
    )
    return service, deps


async def test_remove_summaries_existing_project_deletes() -> None:
    """契约⑮a (#619): 项目存在 → 返回 {"project_id", "deleted": True}，
    且 delete_by_project(project_id) 被调（删除 scope=project 行）。"""
    service, deps = _make_service_with_summary(extra={"memory_learning": True})
    result = await service.remove_summaries(PROJECT_ID)
    assert result == {"project_id": str(PROJECT_ID), "deleted": True}
    deps["summary_repo"].delete_by_project.assert_awaited_once()
    call = deps["summary_repo"].delete_by_project.await_args
    assert _arg(call, "project_id", 0) == PROJECT_ID


async def test_remove_summaries_project_missing_raises() -> None:
    """契约⑮b (#619): 项目不存在（project_repo.get → None）→
    ProjectNotFoundError，默认消息「项目不存在」。"""
    from inkflow.domain.ports.character_errors import ProjectNotFoundError

    service, deps = _make_service_with_summary()
    deps["project_repo"].get.return_value = None
    with pytest.raises(ProjectNotFoundError) as exc:
        await service.remove_summaries(PROJECT_ID)
    assert "项目不存在" in str(exc.value)
    deps["summary_repo"].delete_by_project.assert_not_awaited()


async def test_remove_summaries_disabled_still_deletes() -> None:
    """契约⑮c (#619, Q2=B 越闸): memory_learning=false 【仍可删】——
    方法【不】检查 memory_learning 开关，直接删除。"""
    service, deps = _make_service_with_summary(extra={"memory_learning": False})
    result = await service.remove_summaries(PROJECT_ID)
    assert result == {"project_id": str(PROJECT_ID), "deleted": True}
    deps["summary_repo"].delete_by_project.assert_awaited_once()


async def test_remove_summaries_idempotent_zero_rows() -> None:
    """契约⑮d (#619): 幂等——delete_by_project 返回 0（summary 不存在）→
    仍返回 deleted:True，不抛错、不 404。"""
    service, deps = _make_service_with_summary()
    deps["summary_repo"].delete_by_project.return_value = 0
    result = await service.remove_summaries(PROJECT_ID)
    assert result == {"project_id": str(PROJECT_ID), "deleted": True}


# ═══ coverage 补测（2026-08-24：ADR-027 门禁 98.5/95.0 缺口行覆盖）═══


async def test_remove_preference_without_audit_service_skips_audit() -> None:
    """覆盖 L335->342: audit_service 未注入（None）→ 删除成功且跳过审计，不崩溃."""
    pref = _pref(pref_id="pref-1")
    preference_repo = AsyncMock()
    preference_repo.get.return_value = pref
    preference_repo.delete.return_value = True
    service = MemoryService(
        preference_repo=preference_repo,
        event_repo=AsyncMock(),
        project_repo=AsyncMock(),
    )  # audit_service 缺省 None（F28 默认）
    result = await service.remove_preference("pref-1")
    assert result is pref
    preference_repo.delete.assert_awaited_once()
    preference_repo.get.assert_awaited_once_with("pref-1")


async def test_get_preferences_for_injection_project_missing_empty() -> None:
    """覆盖 L360->361: 开关开启（首次 get 命中）但注入读口再查项目时缺失
    （二次 get → None）→ []。"""
    service, deps = _make_service(extra={"memory_learning": True})
    deps["project_repo"].get.side_effect = [_project({"memory_learning": True}), None]
    deps["preference_repo"].list_by_project.return_value = (
        [_pref(count=5, pref_id="pref-2")],
        1,
    )
    assert await service.get_preferences_for_injection(PROJECT_ID) == []


async def test_get_preferences_for_injection_decay_multi_item_loop() -> None:
    """覆盖 L378->374: 衰减分支——低分条目走 if 假分支后循环继续（多条目），
    score 过滤 + 排序 + 注入即刷新水位。"""
    service, deps = _make_service(
        extra={
            "memory_learning": True,
            "memory_decay_enabled": True,
            "memory_decay_half_life": 30,
        }
    )
    project = _project(
        {
            "memory_learning": True,
            "memory_decay_enabled": True,
            "memory_decay_half_life": 30,
        }
    )
    project.active_watermark = 500.0  # 高分条目水位同值 → score=count；陈旧条目 → 衰减趋零
    deps["project_repo"].get.return_value = project
    stale = _pref(count=1, pref_id="pref-stale")  # 无水位 → delta 500 → score < 0.05
    low = _pref(count=2, pref_id="pref-low")
    low.active_watermark_at_last_access = 500.0
    high = _pref(count=5, pref_id="pref-high", value="林晚")
    high.active_watermark_at_last_access = 500.0
    deps["preference_repo"].list_by_project.return_value = ([stale, low, high], 3)
    result = await service.get_preferences_for_injection(PROJECT_ID)
    assert [p.id for p in result] == ["pref-high", "pref-low"]  # score desc，陈旧条目被滤
    # 注入即刷新水位（用即保鲜）：仅被注入的两条写回 active_watermark_at_last_access
    assert deps["preference_repo"].update.await_count == 2
    assert high.active_watermark_at_last_access == 500.0
    assert low.active_watermark_at_last_access == 500.0


async def test_update_user_preference_missing_raises() -> None:
    """覆盖 L584->585: 用户级偏好不存在（get → None）→ PreferenceNotFoundError 且 update 未调用."""
    service, deps = _make_service_manual(pref=None, user_pref=None)
    with pytest.raises(PreferenceNotFoundError):
        await service.update_user_preference(
            "upref-missing", category="style_word", pattern="说", value="低声道"
        )
    deps["user_preference_repo"].update.assert_not_awaited()


async def test_remove_summaries_without_summary_repo_skips_delete() -> None:
    """覆盖 L885->887: summary_repo 未注入 → 跳过 delete_by_project，仍返回 deleted:True."""
    deps = {
        "preference_repo": AsyncMock(),
        "event_repo": AsyncMock(),
        "project_repo": AsyncMock(),
    }
    deps["project_repo"].get.return_value = _project({"memory_learning": True})
    service = MemoryService(
        preference_repo=deps["preference_repo"],
        event_repo=deps["event_repo"],
        project_repo=deps["project_repo"],
        learner=FakeLearner(),
    )  # summary_repo 缺省 None
    result = await service.remove_summaries(PROJECT_ID)
    assert result == {"project_id": str(PROJECT_ID), "deleted": True}

