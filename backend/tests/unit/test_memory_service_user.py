"""F45 M1 用户级偏好编排服务 RED 契约测试 — MemoryService M1 扩展（全 mock 轨）.

依据: specs/f45-memory-evolution/spec.md §5.1（用户级聚合链）/§5.2（开关零行为）/
§7（项目删除惰性重算 Q1=B + user-list 幽灵过滤）/§9 测试策略第 2 行 ⑥-⑩/
§13 M1-2 验收，父侧定稿契约同源（test_memory_service_user.py docstring 即
契约载体，镜像 F28 test_memory_service.py 全 mock 轨形态）。

被测模块: memory_service.py 已存在（F28 GREEN），M1 扩展未实现:
    from inkflow.domain.services.memory_service import (
        MemoryService, PreferenceNotFoundError,
    )
本文件零 import UserPreference 领域模型（RED 阶段 domain/models/user_preference.py
未实现——SimpleNamespace 鸭子轨镜像 F28，零模型构造；断言走字段访问 + StrEnum
字符串字面量，避免收集错误/ImportError 掩盖方法缺失根因）。

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. MemoryService 构造扩展: 新增关键字参数 `user_preference_repo: object | None
   = None`（放 audit_service 之后；F28 既有测试构造零改动）:

       def __init__(self, *, preference_repo, event_repo, project_repo,
                    audit_service=None, learner=None,
                    user_preference_repo=None): ...

2. 新增方法（父侧定稿，逐字）:

       async def list_user_preferences(
           self, category: PreferenceCategory | None = None,
       ) -> tuple[list[UserPreference], int]
           # 查全部用户级偏好（user_preference_repo.list_all(category=...)）+
           # 惰性重算（Q1=B）：逐条检查 source_projects 中项目是否仍存在
           # （project_repo.get(project_id.int)，镜像 is_learning_enabled 的
           # 鸭子调用）；已删项目 → 从 source_projects 移除、project_count 减 1、
           # update 写回；project_count < 2 → delete 该偏好（不返回）；返回
           # 过滤后的 (items, total)，user-list 不显示幽灵项目来源。

       async def remove_user_preference(self, preference_id: str) -> UserPreference
           # 不存在 → PreferenceNotFoundError（默认消息「偏好不存在」）；删除后
           # 审计 audit_service.record(severity_summary="user_preference_removed",
           # actor="memory")（audit_service 可空时跳过）。

       async def get_user_preferences_for_injection(
           self, project_id: uuid.UUID,
       ) -> list[UserPreference]
           # is_learning_enabled(project_id)=false → []（零行为）；true →
           # list_user_preferences 语义（惰性重算）后返回 items（count desc 排序）。

3. record_draft_edit 追加用户级聚合链（memory_learning=true 时，在既有项目级
   聚合之后）:
   - 全量 edited 事件查询 = event_repo.list_all_edited()（新增鸭子方法：返回
     全部项目 DRAFT_EDITED 事件，created_at asc）;
   - learner.aggregate_user_candidates(events)（新鸭子方法）;
   - 每个候选: 命中既有 user_preference（user_preference_repo.list_all 后按
     value 匹配）→ update（count/confidence/project_count/source_projects/
     source_events 全量替换为候选值）；未命中且候选 count≥2 且 project_count≥2
     → user_preference_repo.create + 审计 audit_service.record(
     severity_summary="user_preference_learned", actor="memory");
   - memory_learning=false → 用户级链不执行（零行为）。

4. stats 扩展: user_preference_repo 注入时输出
   "user_preferences": {"count": N, "projects": M}（N=用户级偏好总数；
   M=全部用户级偏好的 source_projects 并集大小）；user_preference_repo=None
   （F28 既有构造）→ 不含该键（向后兼容，F28 stats 断言零破坏）。

5. 测试侧钉死的依赖形态（全鸭子类型，镜像 F28 test_memory_service.py）:
       user_preference_repo.list_all(category=None) -> tuple[list, int]
       user_preference_repo.get(preference_id) -> UserPreference | None
       user_preference_repo.create(*, category, pattern, value, confidence,
           count, project_count, source_projects, source_events) -> UserPreference
       user_preference_repo.update(preference_id, *, count, confidence,
           project_count, source_projects, source_events) -> UserPreference | None
       user_preference_repo.delete(preference_id) -> bool
       event_repo.list_all_edited() -> list[MemoryEvent]  # 新增鸭子方法
       learner.aggregate_user_candidates(events) -> list[候选]  # 新增鸭子方法
           # 候选 = (category, pattern, value, count, project_count,
           #   source_projects, source_events, confidence) 鸭子对象
       project_repo.get(project_id.int) -> Project | None  # int 背书，F6 先例

契约裁定（父侧契约疑点，写进 docstring 供 GREEN 对齐）
----------------------------------------------------
- list_user_preferences 的 total = 过滤/删除后的条数（= len(items)）——契约
  「返回过滤后的 (items, total)」裁定；GREEN 若透传 repo total 需父侧复裁。
- 用户级聚合链与项目级候选解耦: memory_learning=true 即执行用户级链（项目级
  aggregate_candidates 返回空时仍执行），非 `if 项目候选` 嵌套。
- stats 契约不锁惰性重算: 断言仅覆盖 list_all 直读口径（count=total、
  projects=source_projects 并集大小）；GREEN 若复用 list_user_preferences
  重算路径亦满足（mock 下无已删项目，行为等价）。
- create/update 调用断言用宽松取参 helper `_arg`（kwargs 优先位置回退）——
  不锁实现传参形态（镜像 F28）。

RED 预期
--------
memory_service.py 已存在（F28 GREEN），M1 扩展未实现:
- 全部用例 FAILED（非收集错误）——`_make_service` 传新关键字参数
  user_preference_repo → `TypeError: MemoryService.__init__() got an
  unexpected keyword argument 'user_preference_repo'`（规则 1q 签名扩展
  TypeError 形态，失败点在用例体非收集期）;
- 守护用例 test_stats_without_user_repo_omits_key 用 F28 既有构造（不注入
  user_preference_repo）→ stats 既有实现直接通过（RED 阶段即 PASS 刻意，
  防父侧误判为假绿）;
- GREEN 后: 构造扩展实现 → 失败点迁移为用例体 AttributeError（方法缺失）；
  方法实现后全绿。

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

PROJECT_ID = uuid.UUID(int=100)
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
# 惰性重算测试用项目 id（PID_A/PID_B 存活，GHOST 已删除）
PID_A = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PID_B = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PID_C = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
GHOST = uuid.UUID("99999999-9999-4999-8999-999999999999")


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
        self.last_user_events = None

    def aggregate_candidates(self, events):
        self.aggregate_calls += 1
        if self._candidates:
            return self._candidates.pop(0)
        return []

    def aggregate_user_candidates(self, events):
        self.aggregate_user_calls += 1
        self.last_user_events = events
        if self._user_candidates:
            return self._user_candidates.pop(0)
        return []

    def confidence_for(self, count: int) -> float:
        return 1 - 1 / (count + 1)


def _user_candidate(
    value="低声道",
    *,
    category="style_word",
    pattern="说",
    count=2,
    project_count=2,
    confidence=None,
    source_projects=None,
    source_events=None,
) -> SimpleNamespace:
    """用户级候选鸭子对象（UserPreferenceCandidate 语义）. 缺省 count=2/
    project_count=2（跨项目聚合阈值，spec §5.1 第 6 步）."""
    return SimpleNamespace(
        category=category,
        pattern=pattern,
        value=value,
        count=count,
        project_count=project_count,
        confidence=confidence if confidence is not None else 1 - 1 / (count + 1),
        source_projects=list(source_projects or [str(PROJECT_ID)]),
        source_events=list(source_events or ["evt-1"]),
    )


def _user_pref(
    value="低声道",
    *,
    pref_id="up-1",
    category="style_word",
    pattern="说",
    confidence=0.5,
    count=2,
    project_count=2,
    source_projects=None,
    source_events=None,
) -> SimpleNamespace:
    """既有用户级偏好鸭子对象（UserPreference 语义）."""
    return SimpleNamespace(
        id=pref_id,
        category=category,
        pattern=pattern,
        value=value,
        confidence=confidence,
        count=count,
        project_count=project_count,
        source_projects=list(source_projects or [str(PROJECT_ID)]),
        source_events=list(source_events or ["evt-1"]),
    )


def _project(extra: dict) -> SimpleNamespace:
    """项目鸭子对象（Project.config.extra 语义——F13 先例 dict 读取）."""
    return SimpleNamespace(config=SimpleNamespace(extra=extra))


def _project_get_side_effect(deleted_ints: set):
    """project_repo.get 按 int 主键分发（镜像 is_learning_enabled 鸭子调用）:
    已删项目 → None，其余 → 存活项目."""

    def _impl(int_id: int):
        if int_id in deleted_ints:
            return None
        return _project({"memory_learning": True})

    return _impl


def _make_service(learner=None, extra=None, *, inject_user_repo: bool = True):
    """构造服务 + 依赖字典；全部 repo 方法显式默认值（裸 AsyncMock 陷阱防护）.

    inject_user_repo=True（默认）: 注入 user_preference_repo AsyncMock
    （M1 契约形态，RED 阶段构造 TypeError 即预期失败点）;
    inject_user_repo=False: F28 既有构造形态（向后兼容守护，⑩b 用）.
    """
    deps = {
        "preference_repo": AsyncMock(),
        "event_repo": AsyncMock(),
        "project_repo": AsyncMock(),
        "audit_service": AsyncMock(),
    }
    deps["preference_repo"].list_by_project.return_value = ([], 0)
    deps["preference_repo"].count_by_project.return_value = 0
    deps["preference_repo"].get.return_value = None
    deps["preference_repo"].create.return_value = SimpleNamespace(id="pref-new")
    deps["preference_repo"].update.return_value = None
    deps["preference_repo"].delete.return_value = True
    deps["event_repo"].create.return_value = SimpleNamespace(id="evt-1", event_type="draft_edited")
    deps["event_repo"].list_by_project.return_value = (
        [],
        0,
    )  # #249 契约修正：真实 repo 返回 (list, total) 元组
    deps["event_repo"].list_all_edited.return_value = []  # 新增鸭子方法（M1 用户级链）
    deps["project_repo"].get.return_value = _project(extra or {})
    kwargs: dict = {
        "preference_repo": deps["preference_repo"],
        "event_repo": deps["event_repo"],
        "project_repo": deps["project_repo"],
        "audit_service": deps["audit_service"],
        "learner": learner or FakeLearner(),
    }
    if inject_user_repo:
        user_repo = AsyncMock()
        user_repo.list_all.return_value = ([], 0)
        user_repo.get.return_value = None
        user_repo.create.return_value = _user_pref(pref_id="up-new")
        user_repo.update.return_value = None
        user_repo.delete.return_value = True
        deps["user_preference_repo"] = user_repo
        kwargs["user_preference_repo"] = user_repo
    service = MemoryService(**kwargs)
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


# ── 契约⑥: memory_learning=false 零行为（用户级链不执行 + 注入空） ──


async def test_record_draft_edit_user_chain_zero_behavior_when_disabled() -> None:
    """契约⑥a: memory_learning=false → 用户级链不执行（aggregate_user_candidates
    不调用、user_preference_repo.create 不调用、无 user_preference_learned 审计）."""
    learner = FakeLearner(
        candidates=[[]], user_candidates=[[_user_candidate(count=2, project_count=2)]]
    )
    service, deps = _make_service(learner=learner)  # extra 默认 {} → 开关 false
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
    deps["event_repo"].list_all_edited.assert_not_awaited()
    deps["user_preference_repo"].create.assert_not_awaited()
    deps["audit_service"].record.assert_not_awaited()
    assert learner.aggregate_user_calls == 0
    assert learner.aggregate_calls == 0  # 项目级链同样不执行


async def test_get_user_preferences_for_injection_disabled_empty() -> None:
    """契约⑥b: 开关 false → 注入 []（零行为，不查库）."""
    service, deps = _make_service()
    assert await service.get_user_preferences_for_injection(PROJECT_ID) == []
    deps["user_preference_repo"].list_all.assert_not_awaited()


# ── 契约⑥+（设计段聚合链正向：落库/更新/阈值三形态，防 GREEN 跳过链假绿） ──


async def test_record_draft_edit_user_chain_creates_user_preference() -> None:
    """契约⑥c: memory_learning=true → 用户级链执行：全量 edited 事件 →
    aggregate_user_candidates → 未命中且 count≥2 且 project_count≥2 →
    create + user_preference_learned 审计（项目级候选为空时链仍执行）."""
    learner = FakeLearner(
        candidates=[[]], user_candidates=[[_user_candidate(count=2, project_count=2)]]
    )
    service, deps = _make_service(extra={"memory_learning": True}, learner=learner)
    all_events = [
        SimpleNamespace(id="evt-1", event_type="draft_edited"),
        SimpleNamespace(id="evt-2", event_type="draft_edited"),
    ]
    deps["event_repo"].list_all_edited.return_value = all_events
    deps["user_preference_repo"].list_all.return_value = ([], 0)
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    assert learner.aggregate_user_calls == 1
    assert learner.last_user_events is all_events  # 全量跨项目 edited 事件透传
    deps["user_preference_repo"].create.assert_awaited_once()
    call = deps["user_preference_repo"].create.await_args
    assert _arg(call, "category", 0) == "style_word"
    assert _arg(call, "pattern", 1) == "说"
    assert _arg(call, "value", 2) == "低声道"
    assert _arg(call, "count", 4) == 2
    assert _arg(call, "project_count", 5) == 2
    assert _arg(call, "source_projects", 6) == [str(PROJECT_ID)]
    assert _arg(call, "source_events", 7) == ["evt-1"]
    deps["user_preference_repo"].update.assert_not_awaited()
    audit_call = _audit_call(deps["audit_service"], "user_preference_learned")
    assert audit_call is not None
    assert _arg(audit_call, "actor", 8) == "memory"


async def test_record_draft_edit_user_chain_updates_existing() -> None:
    """契约⑥d: 候选 value 命中既有用户级偏好 → update 全量替换
    （count/confidence/project_count/source_projects/source_events），不 create、
    无 user_preference_learned 审计."""
    learner = FakeLearner(
        candidates=[[]], user_candidates=[[_user_candidate(count=3, project_count=2)]]
    )
    service, deps = _make_service(extra={"memory_learning": True}, learner=learner)
    existing = _user_pref(
        value="低声道",
        pref_id="up-1",
        count=2,
        project_count=2,
        source_projects=[str(PROJECT_ID)],
        source_events=["evt-1"],
    )
    deps["user_preference_repo"].list_all.return_value = ([existing], 1)
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    deps["user_preference_repo"].create.assert_not_awaited()
    deps["user_preference_repo"].update.assert_awaited_once()
    call = deps["user_preference_repo"].update.await_args
    assert _arg(call, "preference_id", 0) == "up-1"
    assert _arg(call, "count", 1) == 3  # 候选 count
    assert _arg(call, "confidence", 2) == pytest.approx(1 - 1 / 4)  # 1 - 1/(3+1)
    assert _arg(call, "project_count", 3) == 2
    assert _arg(call, "source_projects", 4) == [str(PROJECT_ID)]
    assert _arg(call, "source_events", 5) == ["evt-1"]
    assert _audit_call(deps["audit_service"], "user_preference_learned") is None


async def test_record_draft_edit_user_chain_skips_low_project_support() -> None:
    """契约⑥e: 候选 project_count=1（保守规则防混算）→ 不 create 不 update
    （服务侧阈值双检 count≥2 且 project_count≥2）."""
    learner = FakeLearner(
        candidates=[[]],
        user_candidates=[[_user_candidate(count=2, project_count=1)]],
    )
    service, deps = _make_service(extra={"memory_learning": True}, learner=learner)
    deps["user_preference_repo"].list_all.return_value = ([], 0)
    await service.record_draft_edit(
        draft_id="draft-1", project_id=PROJECT_ID, before="旧版内容", after="新版内容更长"
    )
    deps["user_preference_repo"].create.assert_not_awaited()
    deps["user_preference_repo"].update.assert_not_awaited()
    assert _audit_call(deps["audit_service"], "user_preference_learned") is None


# ── 契约⑦: user_preferences CRUD ──


async def test_list_user_preferences_returns_tuple() -> None:
    """契约⑦a: list_user_preferences 返回 (items, total)（无已删项目 → 原样）."""
    service, deps = _make_service()
    p1 = _user_pref(pref_id="up-1")
    p2 = _user_pref(pref_id="up-2", value="林晚")
    deps["user_preference_repo"].list_all.return_value = ([p1, p2], 2)
    items, total = await service.list_user_preferences()
    assert [p.id for p in items] == ["up-1", "up-2"]
    assert total == 2
    deps["user_preference_repo"].update.assert_not_awaited()
    deps["user_preference_repo"].delete.assert_not_awaited()


async def test_list_user_preferences_category_filter_forwarded() -> None:
    """契约⑦b: category 过滤参数透传 user_preference_repo.list_all."""
    service, deps = _make_service()
    deps["user_preference_repo"].list_all.return_value = ([], 0)
    await service.list_user_preferences(category="addressing")
    deps["user_preference_repo"].list_all.assert_awaited_once()
    call = deps["user_preference_repo"].list_all.await_args
    assert _arg(call, "category", 1) == "addressing"


async def test_remove_user_preference_existing_deletes_and_audits() -> None:
    """契约⑦c: 存在 → 删除 + 审计 user_preference_removed，返回被删偏好."""
    service, deps = _make_service()
    pref = _user_pref(pref_id="up-1")
    deps["user_preference_repo"].get.return_value = pref
    result = await service.remove_user_preference("up-1")
    assert result is pref
    deps["user_preference_repo"].delete.assert_awaited_once()
    call = deps["user_preference_repo"].delete.await_args
    assert _arg(call, "preference_id", 0) == "up-1"
    audit_call = _audit_call(deps["audit_service"], "user_preference_removed")
    assert audit_call is not None
    assert _arg(audit_call, "actor", 8) == "memory"


async def test_remove_user_preference_missing_raises() -> None:
    """契约⑦d: 不存在 → PreferenceNotFoundError（默认消息「偏好不存在」）."""
    service, deps = _make_service()
    deps["user_preference_repo"].get.return_value = None
    with pytest.raises(PreferenceNotFoundError) as exc:
        await service.remove_user_preference("up-missing")
    assert "偏好不存在" in str(exc.value)
    deps["user_preference_repo"].delete.assert_not_awaited()


async def test_remove_user_preference_skips_audit_when_audit_none() -> None:
    """守护: audit_service 缺省 None 时删除成功且不崩溃（契约「可空时跳过」）."""
    user_repo = AsyncMock()
    user_repo.get.return_value = _user_pref(pref_id="up-1")
    user_repo.delete.return_value = True
    service = MemoryService(
        preference_repo=AsyncMock(),
        event_repo=AsyncMock(),
        project_repo=AsyncMock(),
        user_preference_repo=user_repo,
    )  # audit_service 缺省 None（F28 默认）
    result = await service.remove_user_preference("up-1")
    assert result is not None
    user_repo.delete.assert_awaited_once()


# ── 契约⑧: 删除后 collect 不含该条（实时查库无缓存） ──


async def test_user_injection_excludes_removed_preference_no_cache() -> None:
    """契约⑧: 开启时注入 count desc 排序；remove 后再次注入不含该条，
    list_all 每次实时查询（无缓存，F28「删除即停注入」语义延续）."""
    service, deps = _make_service(extra={"memory_learning": True})
    low = _user_pref(count=2, pref_id="up-low")
    high = _user_pref(count=5, pref_id="up-high", value="林晚")
    deps["user_preference_repo"].list_all.return_value = ([low, high], 2)
    result = await service.get_user_preferences_for_injection(PROJECT_ID)
    assert [p.id for p in result] == ["up-high", "up-low"]  # count desc 排序
    deps["user_preference_repo"].get.return_value = high
    removed = await service.remove_user_preference("up-high")
    assert removed is high
    deps["user_preference_repo"].list_all.return_value = ([low], 1)
    result2 = await service.get_user_preferences_for_injection(PROJECT_ID)
    assert [p.id for p in result2] == ["up-low"]
    assert "up-high" not in [p.id for p in result2]
    assert len(deps["user_preference_repo"].list_all.await_args_list) == 2  # 无缓存


# ── 契约⑨: 项目删除惰性重算（Q1=B 核心） ──


async def test_list_user_preferences_recomputes_removes_deleted_project() -> None:
    """契约⑨a: source_projects 含已删项目 → 重算：移除该项目 + project_count 减 1
    + update 写回（断言参数正确）；存活项目源偏好不受影响."""
    service, deps = _make_service()
    up1 = _user_pref(
        pref_id="up-1",
        count=3,
        project_count=3,
        source_projects=[str(PID_A), str(PID_B), str(GHOST)],
    )
    up2 = _user_pref(
        pref_id="up-2",
        value="林晚",
        project_count=2,
        source_projects=[str(PID_A), str(PID_B)],
    )
    deps["user_preference_repo"].list_all.return_value = ([up1, up2], 2)
    deps["project_repo"].get.side_effect = _project_get_side_effect({GHOST.int})
    items, total = await service.list_user_preferences()
    # update 写回（仅 up-1 含已删项目 GHOST）
    deps["user_preference_repo"].update.assert_awaited_once()
    call = deps["user_preference_repo"].update.await_args
    assert _arg(call, "preference_id", 0) == "up-1"
    assert _arg(call, "count", 1) == 3  # count/confidence/source_events 透传不变
    assert _arg(call, "confidence", 2) == pytest.approx(0.5)
    assert _arg(call, "project_count", 3) == 2  # 3 → 2
    assert _arg(call, "source_projects", 4) == [str(PID_A), str(PID_B)]  # 幽灵已剔
    assert _arg(call, "source_events", 5) == ["evt-1"]
    deps["user_preference_repo"].delete.assert_not_awaited()
    # 返回列表: up-1 已重算（无幽灵项目来源）、up-2 原样
    assert total == 2
    by_id = {p.id: p for p in items}
    assert by_id["up-1"].project_count == 2
    assert by_id["up-1"].source_projects == [str(PID_A), str(PID_B)]
    assert by_id["up-2"].project_count == 2


async def test_list_user_preferences_recomputes_deletes_low_support() -> None:
    """契约⑨b: 仅剩 1 个项目支撑（project_count 2→1 < 2）→ delete 该偏好
    （不返回），update 不调用."""
    service, deps = _make_service()
    up1 = _user_pref(
        pref_id="up-1",
        count=2,
        project_count=2,
        source_projects=[str(PID_A), str(GHOST)],
    )
    deps["user_preference_repo"].list_all.return_value = ([up1], 1)
    deps["project_repo"].get.side_effect = _project_get_side_effect({GHOST.int})
    items, total = await service.list_user_preferences()
    assert [p.id for p in items] == []  # 已删偏好不返回
    assert total == 0
    deps["user_preference_repo"].delete.assert_awaited_once()
    call = deps["user_preference_repo"].delete.await_args
    assert _arg(call, "preference_id", 0) == "up-1"
    deps["user_preference_repo"].update.assert_not_awaited()


async def test_list_user_preferences_ghost_only_source_not_displayed() -> None:
    """契约⑨c: 已删项目是唯一来源（project_count 1→0）→ delete 该偏好；
    user-list 返回列表不含幽灵项目来源."""
    service, deps = _make_service()
    up1 = _user_pref(
        pref_id="up-1",
        project_count=1,
        source_projects=[str(GHOST)],
    )
    deps["user_preference_repo"].list_all.return_value = ([up1], 1)
    deps["project_repo"].get.side_effect = _project_get_side_effect({GHOST.int})
    items, total = await service.list_user_preferences()
    assert [p.id for p in items] == []
    assert total == 0
    deps["user_preference_repo"].delete.assert_awaited_once()
    assert all(str(GHOST) not in p.source_projects for p in items)  # 无幽灵项目


# ── 契约⑩: stats 输出 user 层计数 ──


async def test_stats_includes_user_layer_counts() -> None:
    """契约⑩a: user_preference_repo 注入时 stats 含 user_preferences
    {"count": N, "projects": M}（N=总数，M=source_projects 并集大小）."""
    service, deps = _make_service()
    deps["user_preference_repo"].list_all.return_value = (
        [
            _user_pref(
                pref_id="up-1",
                source_projects=[str(PID_A), str(PID_B)],
            ),
            _user_pref(
                pref_id="up-2",
                value="林晚",
                source_projects=[str(PID_B), str(PID_C)],
            ),
        ],
        2,
    )
    stats = await service.stats(PROJECT_ID)
    assert stats["user_preferences"] == {"count": 2, "projects": 3}  # 并集 {A,B,C}


async def test_stats_without_user_repo_omits_key() -> None:
    """契约⑩b（守护）: user_preference_repo=None（F28 既有构造）→ stats 不含
    user_preferences 键（向后兼容，F28 stats 断言零破坏）.

    RED 阶段即 PASS 刻意——F28 既有构造 + 既有 stats 实现直接满足；防父侧
    误判为假绿（规则 1q 守护用例语义）.
    """
    service, _deps = _make_service(inject_user_repo=False)
    stats = await service.stats(PROJECT_ID)
    assert "user_preferences" not in stats


# ═══ F45 M1 coverage 补测（2026-08-17：防御分支行覆盖，ADR-027 门禁 98.5/95.0）═══


async def test_list_user_preferences_without_repo_returns_empty() -> None:
    """覆盖 L366-367: user_preference_repo=None（F28 既有构造）→ ([], 0) 早退."""
    service, _deps = _make_service(inject_user_repo=False)
    items, total = await service.list_user_preferences()
    assert items == []
    assert total == 0


async def test_list_user_preferences_skips_invalid_uuid() -> None:
    """覆盖 L379-380: source_projects 含非法 uuid 字符串 → ValueError 跳过，不崩."""
    service, deps = _make_service()
    deps["user_preference_repo"].list_all.return_value = (
        [
            _user_pref(
                pref_id="up-1",
                source_projects=["not-a-uuid", str(PID_A)],
            ),
        ],
        1,
    )
    items, total = await service.list_user_preferences()
    assert total == 1
    assert items[0].id == "up-1"


async def test_remove_user_preference_without_repo_raises() -> None:
    """覆盖 L421-422: user_preference_repo=None → remove_user_preference 抛 NotFound."""
    service, _deps = _make_service(inject_user_repo=False)
    with pytest.raises(PreferenceNotFoundError):
        await service.remove_user_preference("up-1")


# ═══ coverage 补测（2026-08-24：ADR-027 门禁 98.5/95.0 缺口行覆盖）═══


async def test_get_user_preferences_for_injection_repo_none_sorted() -> None:
    """覆盖 L610->611: user_preference_repo 未注入 + 开关开启 → []
    （list_user_preferences 早退 ([], 0) 后走 repo None 分支）."""
    service, _deps = _make_service(
        extra={"memory_learning": True}, inject_user_repo=False
    )
    assert await service.get_user_preferences_for_injection(PROJECT_ID) == []


async def test_get_user_preferences_for_injection_project_missing_sorted() -> None:
    """覆盖 L619->620: 仓库已注入 + 开关开启（首次 get 命中）但注入读口再查项目时
    缺失（二次 get → None）→ count desc 过滤列表。"""
    service, deps = _make_service(extra={"memory_learning": True})
    deps["user_preference_repo"].list_all.return_value = ([], 0)  # 惰性重算不触发额外 get
    deps["project_repo"].get.side_effect = [_project({"memory_learning": True}), None]
    assert await service.get_user_preferences_for_injection(PROJECT_ID) == []


async def test_get_user_preferences_for_injection_decay_full_path() -> None:
    """覆盖 L632-644 + L639->635 + L648-649: 用户级衰减分支——superseded 排除 +
    score 过滤（低分条目走 if 假分支后循环继续）+ 排序 + 注入即刷新水位。"""
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
    superseded = _user_pref(pref_id="up-sup", count=9)
    superseded.superseded_by = "up-high"  # F49 ② 被取代 → 注入排除
    stale = _user_pref(count=1, pref_id="up-stale")  # 无水位 → delta 500 → score < 0.05
    low = _user_pref(count=2, pref_id="up-low")
    low.active_watermark_at_last_access = 500.0
    high = _user_pref(count=5, pref_id="up-high", value="林晚")
    high.active_watermark_at_last_access = 500.0
    deps["user_preference_repo"].list_all.return_value = (
        [superseded, stale, low, high],
        4,
    )
    result = await service.get_user_preferences_for_injection(PROJECT_ID)
    assert [p.id for p in result] == ["up-high", "up-low"]  # 排除 superseded/低分 + score desc
    # 注入即刷新水位：仅被注入的两条写回 active_watermark_at_last_access
    assert deps["user_preference_repo"].update.await_count == 2
    assert high.active_watermark_at_last_access == 500.0
    assert low.active_watermark_at_last_access == 500.0



