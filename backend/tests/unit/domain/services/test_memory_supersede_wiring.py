"""F49 ② #618 显式覆盖接线 RED 契约测试 — MemoryService supersede_determiner 接线（全 mock 轨）.

依据: .hermes/plans/task-618-contract.md §3（接线设计，唯一契约真相源），
镜像 test_memory_service.py 的 deps 鸭子 mock 形态（SimpleNamespace + AsyncMock）。

被测对象（memory_service.py 模块已存在——本轨为 MODIFY 接线，非新建模块）:
    from inkflow.domain.services.memory_service import MemoryService
顶层唯一 inkflow import = 主契约模块（惯例）；SupersedeDeterminationError
（domain/ports/preference_supersede_errors.py，新错误面，§2）惰性 import——
RED 时主模块构造即 TypeError，GREEN 时端口模块已落地。

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. MemoryService.__init__ 新增关键字参:

       supersede_determiner: object | None = None
           # 默认 None = 未装配 → 不判定（向后兼容，determiner 不被调用且候选正常 create）

2. 判定器契约（domain/services/preference_supersede_determiner.py，镜像
   semantic_summarizer.py 骨架）:

       async def determine(new_value: str, anchors: list, *, model: str)
           -> tuple[list[str], int]   # (superseded_values, dropped)
           # 防幻觉 B: 不在锚点 value 集合的判定值 → 丢弃（dropped 计数），不重试
           # 解析/校验失败（修复式重试 ≤2 后）→ 抛 SupersedeDeterminationError

3. record_draft_edit 项目级「未命中且 count>=2 → create」分支接线（§3.2）:
   - 仅当 existing_items（list_by_project 返回的 items）非空 且
     supersede_determiner 已装配时判定:
       (superseded_values, dropped) = await determine(candidate.value,
           existing_items, model=self._llm_default_model)
   - SupersedeDeterminationError → 捕获 → audit semantic_summary_failed
     （degraded=True, actor="memory", note="LLM 判定失败"）→ 该候选不 create，
     不抛错（不 502）;
   - dropped > 0（防幻觉 B 丢弃）→ audit semantic_summary_failed
     （note 含丢弃数）→ 仍 create 候选（determination 成功但部分丢弃）;
   - 对每个 superseded_values 的 value: existing_by_value.get(value) 命中 →
       preference_repo.update(old.id, count=..., confidence=...,
       source_events=..., superseded_by=candidate.value)（断言 update 被调且
       含 superseded_by=candidate.value）;
   - 然后 create 候选。
4. 用户级同规则（§3.2）: record_draft_edit 用户级聚合 create 分支
   （uc.count>=2 and uc.project_count>=2）同样判定 +
   user_preference_repo.update(superseded_by=uc.value)。
5. get_preferences_for_injection / get_user_preferences_for_injection:
   返回前过滤 superseded_by != ""（decay 关 count desc 分支与 decay 开
   score desc 分支都要过滤）;
   list_preferences / list_user_preferences: 不过滤 superseded（Q3=A 展示全部）。

RED 预期
--------
本轨为 MODIFY 接线——memory_service.py 模块已存在，收集期成功；全部用例在
MemoryService 关键字构造时因 supersede_determiner 参数未实现而 TypeError
（RED 正确，pytest 整文件 error）；GREEN 落地后整文件转绿。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.services.memory_service import MemoryService

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

PROJECT_ID = uuid.UUID(int=100)


class FakeLearner:
    """注入 fake（隔离提取算法；本文件不 import preference_learner）.

    candidates / user_candidates: 每次 aggregate_candidates /
    aggregate_user_candidates 依次弹出的候选列表，耗尽后返回 []。
    confidence_for: 复刻契约公式 1 - 1/(count+1)。
    """

    def __init__(self, candidates=None, user_candidates=None) -> None:
        self._candidates = list(candidates or [])
        self._user_candidates = list(user_candidates or [])
        self.aggregate_calls = 0
        self.aggregate_user_calls = 0

    def aggregate_candidates(self, events):
        self.aggregate_calls += 1
        if self._candidates:
            return self._candidates.pop(0)
        return []

    def aggregate_user_candidates(self, events):
        self.aggregate_user_calls += 1
        if self._user_candidates:
            return self._user_candidates.pop(0)
        return []

    def confidence_for(self, count: int) -> float:
        return 1 - 1 / (count + 1)


def _candidate(
    value="新用词", *, category="style_word", pattern="说", count=2, confidence=None
) -> SimpleNamespace:
    """候选鸭子对象（PreferenceCandidate 语义）."""
    return SimpleNamespace(
        category=category,
        pattern=pattern,
        value=value,
        count=count,
        confidence=confidence if confidence is not None else 1 - 1 / (count + 1),
    )


def _user_candidate(
    value="新user词",
    *,
    category="style_word",
    pattern="说",
    count=2,
    project_count=2,
    confidence=None,
    source_projects=None,
    source_events=None,
) -> SimpleNamespace:
    """用户级候选鸭子对象（UserPreferenceCandidate 语义）."""
    return SimpleNamespace(
        category=category,
        pattern=pattern,
        value=value,
        count=count,
        project_count=project_count,
        confidence=confidence if confidence is not None else 1 - 1 / (count + 1),
        source_projects=list(source_projects or []),
        source_events=list(source_events or []),
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
    superseded_by="",
) -> SimpleNamespace:
    """既有项目偏好鸭子对象（ProjectPreference 语义，含 #618 superseded_by）."""
    return SimpleNamespace(
        id=pref_id,
        project_id=PROJECT_ID,
        category=category,
        pattern=pattern,
        value=value,
        confidence=confidence,
        count=count,
        source_events=list(source_events or []),
        superseded_by=superseded_by,
    )


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
    superseded_by="",
) -> SimpleNamespace:
    """用户级偏好鸭子对象（UserPreference 语义，含 #618 superseded_by）."""
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
        superseded_by=superseded_by,
    )


def _project(extra: dict, watermark: float = 0.0) -> SimpleNamespace:
    """项目鸭子对象（Project.config.extra / active_watermark 语义）."""
    return SimpleNamespace(config=SimpleNamespace(extra=extra), active_watermark=watermark)


def _make_determiner(values=(), dropped=0, error=None) -> SimpleNamespace:
    """supersede_determiner 鸭子 mock: determine 返回 (values, dropped) 或抛 error."""
    determiner = SimpleNamespace()
    determiner.determine = AsyncMock()
    if error is not None:
        determiner.determine.side_effect = error
    else:
        determiner.determine.return_value = (list(values), dropped)
    return determiner


def _make_service(learner=None, extra=None, determiner=None, user_repo_installed=True):
    """构造服务 + 依赖字典；全部 repo 方法显式默认值（裸 AsyncMock 陷阱防护）.

    determiner=None → supersede_determiner 未装配（向后兼容轨）；user_repo_installed
    =False → user_preference_repo=None。llm_default_model 固定 "test-model" 供
    determine(model=...) 断言。
    """
    deps = {
        "preference_repo": AsyncMock(),
        "event_repo": AsyncMock(),
        "project_repo": AsyncMock(),
        "audit_service": AsyncMock(),
    }
    deps["preference_repo"].list_by_project.return_value = ([], 0)
    deps["preference_repo"].create.return_value = _pref(pref_id="pref-new")
    deps["preference_repo"].update.return_value = None
    deps["event_repo"].create.return_value = SimpleNamespace(id="evt-1", event_type="draft_edited")
    deps["event_repo"].list_edited_by_project.return_value = []
    deps["event_repo"].list_all_edited.return_value = []
    deps["project_repo"].get.return_value = _project(extra or {})
    if user_repo_installed:
        deps["user_preference_repo"] = AsyncMock()
        deps["user_preference_repo"].list_all.return_value = ([], 0)
        deps["user_preference_repo"].create.return_value = _user_pref(pref_id="upref-new")
        deps["user_preference_repo"].update.return_value = None
    else:
        deps["user_preference_repo"] = None
    service = MemoryService(
        preference_repo=deps["preference_repo"],
        event_repo=deps["event_repo"],
        project_repo=deps["project_repo"],
        audit_service=deps["audit_service"],
        learner=learner or FakeLearner(),
        user_preference_repo=deps["user_preference_repo"],
        supersede_determiner=determiner,
        llm_default_model="test-model",
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


# ── 契约 1: 项目级判定取代 → 旧偏好 update superseded_by + 注入排除 ──


async def test_project_supersede_updates_old_and_injection_excludes() -> None:
    """契约①: 未命中且 count>=2 → create 前判定；旧偏好 update 含
    superseded_by=candidate.value；候选仍 create；注入排除被取代偏好."""
    old = _pref(value="旧用词", pref_id="pref-old", count=1, source_events=["evt-0"])
    learner = FakeLearner(candidates=[[_candidate(value="新用词", count=2)]])
    determiner = _make_determiner(values=["旧用词"])
    service, deps = _make_service(
        learner=learner, extra={"memory_learning": True}, determiner=determiner
    )
    deps["preference_repo"].list_by_project.return_value = ([old], 1)

    def _apply_update(*args, **kwargs):  # repo 落库语义：superseded_by 写回旧偏好对象
        old.superseded_by = kwargs.get("superseded_by", "")
        return old

    deps["preference_repo"].update.side_effect = _apply_update
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    # 判定调用形态: determine(candidate.value, existing_items, model=...)
    determiner.determine.assert_awaited_once()
    call = determiner.determine.await_args
    assert call.args[0] == "新用词"
    assert call.args[1] == [old]
    assert _arg(call, "model", 2) == "test-model"
    # 旧偏好 update 含 superseded_by=candidate.value
    deps["preference_repo"].update.assert_awaited_once()
    ucall = deps["preference_repo"].update.await_args
    assert _arg(ucall, "preference_id", 0) == "pref-old"
    assert _arg(ucall, "superseded_by", 4) == "新用词"
    # 候选仍 create
    deps["preference_repo"].create.assert_awaited_once()
    # 注入排除 superseded（decay 关 count desc 分支）
    deps["preference_repo"].list_by_project.return_value = (
        [old, _pref(value="新用词", pref_id="pref-new", count=2)],
        2,
    )
    result = await service.get_preferences_for_injection(PROJECT_ID)
    assert [p.id for p in result] == ["pref-new"]


# ── 契约 2: 用户级同规则 ──


async def test_user_supersede_updates_old_user_pref() -> None:
    """契约②: 用户级 create 分支（uc.count>=2 and uc.project_count>=2）同样判定；
    旧用户偏好 update 含 superseded_by=uc.value；候选仍 create."""
    old_user = _user_pref(value="旧user词", pref_id="upref-old", count=1, project_count=1)
    learner = FakeLearner(user_candidates=[[_user_candidate(value="新user词")]])
    determiner = _make_determiner(values=["旧user词"])
    service, deps = _make_service(
        learner=learner, extra={"memory_learning": True}, determiner=determiner
    )
    deps["user_preference_repo"].list_all.return_value = ([old_user], 1)
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    determiner.determine.assert_awaited_once()
    call = determiner.determine.await_args
    assert call.args[0] == "新user词"
    assert call.args[1] == [old_user]
    assert _arg(call, "model", 2) == "test-model"
    deps["user_preference_repo"].update.assert_awaited_once()
    ucall = deps["user_preference_repo"].update.await_args
    assert _arg(ucall, "preference_id", 0) == "upref-old"
    assert _arg(ucall, "superseded_by", 6) == "新user词"
    deps["user_preference_repo"].create.assert_awaited_once()


# ── 契约 3: 防幻觉 B dropped>0 → audit + 仍 create ──


async def test_supersede_dropped_audits_and_still_creates() -> None:
    """契约③: dropped>0（防幻觉 B 丢弃）→ audit semantic_summary_failed（note 含
    丢弃数）；丢弃的 value 不标记 superseded（update 不调）；候选仍 create."""
    old = _pref(value="旧用词", pref_id="pref-old")
    learner = FakeLearner(candidates=[[_candidate(value="新用词", count=2)]])
    determiner = _make_determiner(values=[], dropped=2)  # 判定值全被防幻觉 B 丢弃
    service, deps = _make_service(
        learner=learner, extra={"memory_learning": True}, determiner=determiner
    )
    deps["preference_repo"].list_by_project.return_value = ([old], 1)
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    audit_call = _audit_call(deps["audit_service"], "semantic_summary_failed")
    assert audit_call is not None
    assert _arg(audit_call, "degraded", 5) is True
    assert _arg(audit_call, "actor", 8) == "memory"
    assert "2" in _arg(audit_call, "note", 9, "")  # note 含丢弃数
    deps["preference_repo"].create.assert_awaited_once()  # 仍 create（determination 成功）
    deps["preference_repo"].update.assert_not_awaited()  # 丢弃的 value 不标记 superseded


# ── 契约 4: SupersedeDeterminationError → audit + 不 create + 不抛 ──


async def test_supersede_error_audits_no_create_no_raise() -> None:
    """契约④: 解析/校验失败 → audit semantic_summary_failed（degraded=True,
    note="LLM 判定失败"）→ 该候选不 create + 不抛错（不 502，事件仍落库返回）."""
    from inkflow.domain.ports.preference_supersede_errors import SupersedeDeterminationError

    old = _pref(value="旧用词", pref_id="pref-old")
    learner = FakeLearner(candidates=[[_candidate(value="新用词", count=2)]])
    determiner = _make_determiner(error=SupersedeDeterminationError("LLM 判定失败"))
    service, deps = _make_service(
        learner=learner, extra={"memory_learning": True}, determiner=determiner
    )
    deps["preference_repo"].list_by_project.return_value = ([old], 1)
    result = await service.record_draft_edit(  # 不抛
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    assert result is deps["event_repo"].create.return_value  # 事件链不阻断
    audit_call = _audit_call(deps["audit_service"], "semantic_summary_failed")
    assert audit_call is not None
    assert _arg(audit_call, "degraded", 5) is True
    assert _arg(audit_call, "actor", 8) == "memory"
    assert "LLM 判定失败" in _arg(audit_call, "note", 9, "")
    deps["preference_repo"].create.assert_not_awaited()  # 该候选不 create（待判定）
    deps["preference_repo"].update.assert_not_awaited()  # 不标记 superseded
    assert _audit_call(deps["audit_service"], "preference_learned") is None  # 无学习审计


# ── 契约 5: get_preferences_for_injection 过滤 superseded（decay 关/开两分支）──


async def test_injection_filters_superseded_decay_off() -> None:
    """契约⑤a: decay 关 count desc 分支——superseded_by != "" 的条目被排除."""
    service, deps = _make_service(extra={"memory_learning": True})
    superseded = _pref(value="旧用词", pref_id="pref-old", count=5, superseded_by="新用词")
    normal = _pref(value="新用词", pref_id="pref-new", count=2)
    deps["preference_repo"].list_by_project.return_value = ([superseded, normal], 2)
    result = await service.get_preferences_for_injection(PROJECT_ID)
    assert [p.id for p in result] == ["pref-new"]


async def test_injection_filters_superseded_decay_on() -> None:
    """契约⑤b: decay 开 score desc 分支——过滤时同步排除 superseded 与 score<0.05."""
    extra = {
        "memory_learning": True,
        "memory_decay_enabled": True,
        "memory_decay_half_life": 30,
    }
    service, deps = _make_service(extra=extra)
    superseded = _pref(value="旧用词", pref_id="pref-old", count=5, superseded_by="新用词")
    normal = _pref(value="新用词", pref_id="pref-new", count=2)
    deps["preference_repo"].list_by_project.return_value = ([superseded, normal], 2)
    result = await service.get_preferences_for_injection(PROJECT_ID)
    assert [p.id for p in result] == ["pref-new"]


# ── 契约 6: get_user_preferences_for_injection 过滤 superseded ──


async def test_user_injection_filters_superseded() -> None:
    """契约⑥: 用户级注入同过滤——superseded_by != "" 的用户偏好被排除."""
    service, deps = _make_service(extra={"memory_learning": True})
    superseded = _user_pref(
        value="旧user词", pref_id="upref-old", count=5, superseded_by="新user词"
    )
    normal = _user_pref(value="新user词", pref_id="upref-new", count=2)
    deps["user_preference_repo"].list_all.return_value = ([superseded, normal], 2)
    result = await service.get_user_preferences_for_injection(PROJECT_ID)
    assert [p.id for p in result] == ["upref-new"]


# ── 契约 7: list 展示全部（含 superseded，Q3=A）──


async def test_list_preferences_shows_superseded() -> None:
    """契约⑦a: list_preferences 不过滤 superseded（repo 结果透传）."""
    service, deps = _make_service()
    prefs = [_pref(value="旧用词", pref_id="pref-old", superseded_by="新用词")]
    deps["preference_repo"].list_by_project.return_value = (prefs, 1)
    items, total = await service.list_preferences(PROJECT_ID)
    assert items is prefs  # 透传不过滤
    assert total == 1


async def test_list_user_preferences_shows_superseded() -> None:
    """契约⑦b: list_user_preferences 不过滤 superseded（幽灵项目过滤后仍保留）."""
    service, deps = _make_service()
    uprefs = [_user_pref(value="旧user词", pref_id="upref-old", superseded_by="新user词")]
    deps["user_preference_repo"].list_all.return_value = (uprefs, 1)
    items, total = await service.list_user_preferences()
    assert [p.id for p in items] == ["upref-old"]
    assert total == 1


# ── 契约 8: 未装配 determiner / 前置条件 → 不判定（向后兼容）──


async def test_no_determiner_backward_compat_creates() -> None:
    """契约⑧: supersede_determiner=None（未装配）→ 不判定（无 superseded 标记、
    无 semantic_summary_failed 审计），候选正常 create（向后兼容）."""
    learner = FakeLearner(candidates=[[_candidate(value="新用词", count=2)]])
    service, deps = _make_service(learner=learner, extra={"memory_learning": True})
    deps["preference_repo"].list_by_project.return_value = (
        [_pref(value="旧用词", pref_id="pref-old")],
        1,
    )
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    deps["preference_repo"].create.assert_awaited_once()  # 候选正常 create
    deps["preference_repo"].update.assert_not_awaited()  # 不标记 superseded
    assert _audit_call(deps["audit_service"], "semantic_summary_failed") is None


async def test_empty_existing_items_skips_determination() -> None:
    """契约⑨: existing_items 为空（无可取代对象）→ 不判定，候选仍正常 create."""
    learner = FakeLearner(candidates=[[_candidate(value="新用词", count=2)]])
    determiner = _make_determiner(values=["旧用词"])
    service, deps = _make_service(
        learner=learner, extra={"memory_learning": True}, determiner=determiner
    )
    # list_by_project 默认 ([], 0) → existing_items 空
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    determiner.determine.assert_not_awaited()
    deps["preference_repo"].create.assert_awaited_once()


async def test_below_threshold_no_determination_no_create() -> None:
    """契约⑩: 候选 count=1（未达阈值，不进入 create 分支）→ 不判定、不 create."""
    learner = FakeLearner(candidates=[[_candidate(value="新用词", count=1)]])
    determiner = _make_determiner(values=["旧用词"])
    service, deps = _make_service(
        learner=learner, extra={"memory_learning": True}, determiner=determiner
    )
    deps["preference_repo"].list_by_project.return_value = (
        [_pref(value="旧用词", pref_id="pref-old")],
        1,
    )
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    determiner.determine.assert_not_awaited()
    deps["preference_repo"].create.assert_not_awaited()
