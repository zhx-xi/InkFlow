"""F45 M1 用户级偏好聚合 RED 契约测试 — preference_learner.aggregate_user_candidates
（用户级跨项目聚合纯函数，spec §5.1 M1 扩展 / §9 用户级聚合行 / §13 M1-1 验收）。

依据: specs/f45-memory-evolution/spec.md（§5.1 第一段 difflib 证据收集 M1 扩展 /
§9 测试策略用户级聚合行 / §13 M1-1 验收），父侧定稿契约同源。

被测模块（F28 已存在，本测试锁 M1 新增符号——RED 时 ImportError）:
    from inkflow.domain.services.preference_learner import (
        UserPreferenceCandidate, aggregate_user_candidates,
    )
（preference_learner.py 模块本身 F28 已存在：extract_edits/classify_edit/
aggregate_candidates/confidence_for/TextEdit/PreferenceCandidate；仅
UserPreferenceCandidate + aggregate_user_candidates 两个 M1 新符号缺失 →
ImportError: cannot import name（pytest 收集期 1 error / collected 0 items /
exit 2，等价失败形态）。MemoryEvent 构造在 _make_event 函数体惰性 import
（F28 领域模型已存在，GREEN 落地后自动解析）；分类断言走 StrEnum 字符串字面量
（PreferenceCategory 继承 str，== 字面量恒真，免 F401）。

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. 新增符号（spec §5.1，M1 扩展）:

       @dataclass
       class UserPreferenceCandidate:
           category: PreferenceCategory
           pattern: str
           value: str
           count: int
           project_count: int
           source_projects: list[str]
           source_events: list[str]
           confidence: float

       def aggregate_user_candidates(events: list[MemoryEvent]
                                     ) -> list[UserPreferenceCandidate]
           # 1) 只取 event_type == DRAFT_EDITED 且 before_content/after_content
           #    非空的事件
           # 2) 每事件用既有 extract_edits(before, after) 提取片段——共享 F28
           #    纯函数，零重复实现（spec §5.1「不重复 difflib 计算」）
           # 3) 聚合键 = (category, value)（无 project_id 维度）；同事件内重复
           #    同键只计一次（镜像 F28 aggregate_candidates 的 seen_in_event
           #    去重语义）
           # 4) count = 去重后事件数（跨项目累计）；projects = {event.project_id}
           #    集合；project_count = len(projects)
           # 5) source_projects = 支撑项目 id 的字符串列表、source_events =
           #    支撑事件 id 列表（均去重）
           # 6) 阈值: count >= 2 且 project_count >= 2 才产出（保守规则——仅
           #    1 个项目出现的 (category, value) 永不升用户级）
           # 7) pattern = 该组首个片段的 pattern；confidence = confidence_for(count)

2. 保守规则（spec §5.1 语义 6 / 落库语义表 / §2.1「不混算项目特有设定」）:
   同 (category, value) 在 ≥2 项目出现才升用户级；单项目特有设定永不升用户级
   （契约①/④，镜像 M1-6 手工验收）。

3. 共享 extract_edits（spec §5.1 关键，契约⑤/⑦）: 单事件多 replace 片段 →
   每片段独立候选互不合并；噪声过滤（value 纯标点 / 超长 >50）由 extract_edits
   复用，聚合层零重复过滤。

RED 预期
--------
preference_learner 模块已存在（F28 已合入），但 UserPreferenceCandidate /
aggregate_user_candidates 未实现 → 顶部 import 抛 ImportError:
    ImportError: cannot import name 'UserPreferenceCandidate'
pytest 收集期 1 error / collected 0 items / exit 2（等价失败形态；
§13 M1-1 验收命令 `pytest tests/unit/test_user_preference_learner.py` 的 RED 侧）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from inkflow.domain.services.preference_learner import (
    aggregate_user_candidates,
)

PROJECT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
PROJECT_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
PROJECT_C = uuid.UUID("33333333-3333-4333-8333-333333333333")


def _make_event(
    event_id: str, project_id: uuid.UUID, *, event_type="draft_edited", before=None, after=None
):
    """构造 MemoryEvent（惰性 import——镜像 F28 test_preference_learner.py）."""
    from inkflow.domain.models.memory_event import MemoryEvent

    return MemoryEvent(
        id=event_id,
        project_id=project_id,
        event_type=event_type,
        before_content=before,
        after_content=after,
        created_at=datetime.now(UTC),
    )


def _by_value(cands):
    return {c.value: c for c in cands}


# ── 契约 1: 保守规则——单项目不升用户级 ──


def test_user_aggregate_single_project_never_escalates() -> None:
    """契约①: 同一项目内同 (category, value) 出现 2 次 → 用户级产出为空
    （project_count=1 < 2，保守规则；镜像 M1-6 手工验收: A 内「她→林晚」改 2 次
    仅 A → user-list 不出现）."""
    evts = [
        _make_event("a1", PROJECT_A, before="她推开门", after="林晚推开门"),
        _make_event("a2", PROJECT_A, before="她推开门", after="林晚推开门"),
    ]
    assert aggregate_user_candidates(evts) == []


# ── 契约 2: 第 2 项目出现落库 ──


def test_user_aggregate_second_project_promotes() -> None:
    """契约②: 项目 A、B 各 1 次同 (category, value) 编辑 → 产出 1 个候选，
    count=2, project_count=2, confidence≈0.667, source_projects 含 A/B 的
    uuid 字符串, source_events 含 2 个事件 id（spec §5.1 落库语义表第 3 行）."""
    a1 = _make_event("a1", PROJECT_A, before="她推开门", after="林晚推开门")
    b1 = _make_event("b1", PROJECT_B, before="她推开门", after="林晚推开门")
    cands = aggregate_user_candidates([a1, b1])
    assert len(cands) == 1
    c = cands[0]
    assert c.category == "style_word"
    assert c.pattern == "她"  # 该组首个片段的 pattern（长度 1 不参与过滤）
    assert c.value == "林晚"
    assert c.count == 2
    assert c.project_count == 2
    assert c.confidence == pytest.approx(2 / 3)  # confidence_for(2) = 1 - 1/(2+1)
    assert set(c.source_projects) == {str(PROJECT_A), str(PROJECT_B)}
    assert set(c.source_events) == {"a1", "b1"}


# ── 契约 3: 第 3 项目更新 ──


def test_user_aggregate_third_project_updates() -> None:
    """契约③: A/B/C 各 1 次 → count=3, project_count=3, confidence=0.75
    （第 3 项目出现 → count+1, project_count+1, confidence 重算，
    spec §5.1 落库语义表第 4 行）."""
    evts = [
        _make_event("a1", PROJECT_A, before="她推开门", after="林晚推开门"),
        _make_event("b1", PROJECT_B, before="她推开门", after="林晚推开门"),
        _make_event("c1", PROJECT_C, before="她推开门", after="林晚推开门"),
    ]
    cands = aggregate_user_candidates(evts)
    assert len(cands) == 1
    c = cands[0]
    assert c.count == 3
    assert c.project_count == 3
    assert c.confidence == pytest.approx(0.75)  # confidence_for(3) = 1 - 1/4
    assert set(c.source_projects) == {str(PROJECT_A), str(PROJECT_B), str(PROJECT_C)}
    assert set(c.source_events) == {"a1", "b1", "c1"}


# ── 契约 4: 跨项目不混算 ──


def test_user_aggregate_project_specific_not_mixed() -> None:
    """契约④: A 内「她→林晚」×2（仅 A）、B 内「说→低声道」×2（仅 B）→ 用户级
    产出为空——各自 project_count=1 < 2，单项目特有设定永不升用户级
    （spec §2.1「不混算项目特有设定」规则，镜像 M1-7 跨项目不混算）."""
    evts = [
        _make_event("a1", PROJECT_A, before="她推开门", after="林晚推开门"),
        _make_event("a2", PROJECT_A, before="她推开门", after="林晚推开门"),
        _make_event("b1", PROJECT_B, before="她推开门说", after="她推开门低声道"),
        _make_event("b2", PROJECT_B, before="她推开门说", after="她推开门低声道"),
    ]
    assert aggregate_user_candidates(evts) == []


# ── 契约 5: 共享 extract_edits——单事件多片段独立候选 ──


def test_user_aggregate_shared_extract_multiple_fragments() -> None:
    """契约⑤: 一个 DRAFT_EDITED 事件含多个 replace 片段（「她推开门说」→
    「林晚推开门低声道」产生 2 片段）→ 每片段独立候选，互不合并——共享 F28
    extract_edits 纯函数，零重复 difflib 计算（spec §5.1 关键；
    镜像 F28 aggregate_candidates 单事件多片段语义）."""
    a1 = _make_event("a1", PROJECT_A, before="她推开门说", after="林晚推开门低声道")
    b1 = _make_event("b1", PROJECT_B, before="她推开门说", after="林晚推开门低声道")
    cands = aggregate_user_candidates([a1, b1])
    assert len(cands) == 2
    by_value = _by_value(cands)
    assert set(by_value) == {"林晚", "低声道"}
    c_linwan = by_value["林晚"]
    assert c_linwan.pattern == "她"
    assert c_linwan.category == "style_word"
    assert c_linwan.count == 2
    assert c_linwan.project_count == 2
    c_disheng = by_value["低声道"]
    assert c_disheng.pattern == "说"
    assert c_disheng.category == "style_word"
    assert c_disheng.count == 2
    assert c_disheng.project_count == 2


# ── 契约 6: 非 DRAFT_EDITED / 缺内容事件不参与 ──


def test_user_aggregate_ignores_non_edited() -> None:
    """契约⑥: rejected/confirmed 事件不参与聚合（只学用户编辑，spec §5.1 语义 1）."""
    evts = [
        _make_event("r1", PROJECT_A, event_type="draft_rejected", before="正文", after=None),
        _make_event("c1", PROJECT_B, event_type="draft_confirmed", before=None, after="正文"),
    ]
    assert aggregate_user_candidates(evts) == []


def test_user_aggregate_skips_event_missing_content() -> None:
    """契约⑥b: edited 事件缺 before/after 内容 → 跳过（spec §5.1 语义 1
    「before_content/after_content 非空」，镜像 F28 契约⑥f 形态）."""
    evts = [
        _make_event("e1", PROJECT_A, before=None, after="林晚推开门"),
        _make_event("e2", PROJECT_B, before="她推开门", after=None),
        _make_event("e3", PROJECT_A, before="她推开门", after="林晚推开门"),
    ]
    # e1/e2 缺内容跳过；e3 单项目单次 count=1 <2 不产出
    assert aggregate_user_candidates(evts) == []


# ── 契约 7: 噪声过滤复用 extract_edits ──


def test_user_aggregate_noise_pure_punctuation_reused() -> None:
    """契约⑦a: value 纯标点的事件被 extract_edits 过滤 → 不产出（聚合层零重复
    过滤，复用 F28 噪声规则——spec §5.1「共享 extract_edits」）."""
    evts = [
        _make_event("a1", PROJECT_A, before="这是好的。", after="这是好的！！"),
        _make_event("b1", PROJECT_B, before="这是好的。", after="这是好的！！"),
    ]
    assert aggregate_user_candidates(evts) == []


def test_user_aggregate_noise_value_too_long_reused() -> None:
    """契约⑦b: value 超长（>50 字符）的事件被 extract_edits 过滤 → 不产出."""
    before = "甲" + "x" * 50
    after = "甲" + "y" * 51  # value = 51 字符 > 50
    evts = [
        _make_event("a1", PROJECT_A, before=before, after=after),
        _make_event("b1", PROJECT_B, before=before, after=after),
    ]
    assert aggregate_user_candidates(evts) == []


# ── 契约 8: 事件内重复同键只计一次 ──


def test_user_aggregate_duplicate_key_in_event_counts_once() -> None:
    """契约⑧: 同一事件内同一 (category, value) 出现多次 → count 只 +1
    （「她说：她说」→「林晚低声道：林晚低声道」产生 2 个同键 replace 片段，
    镜像 F28 aggregate_candidates 的 seen_in_event 去重语义——若按片段计数
    count 会是 4，去重后 = 2 事件）."""
    a1 = _make_event("a1", PROJECT_A, before="她说：她说", after="林晚低声道：林晚低声道")
    b1 = _make_event("b1", PROJECT_B, before="她说：她说", after="林晚低声道：林晚低声道")
    cands = aggregate_user_candidates([a1, b1])
    assert len(cands) == 1
    c = cands[0]
    assert c.value == "林晚低声道"
    assert c.count == 2
    assert c.project_count == 2
    assert set(c.source_events) == {"a1", "b1"}
