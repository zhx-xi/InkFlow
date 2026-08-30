"""F28 M1 偏好提取算法 RED 契约测试 — preference_learner（difflib 规则化统计纯函数）.

依据: specs/f28-memory-learning/spec.md（§5.2 提取算法 / §5.3 存储 / §9 测试策略 /
§13 M1 验收），父侧定稿契约同源（test_preference_learner.py docstring 即契约载体）。

被测模块（全部未实现，1c 整模块 RED 形态；顶层唯一 inkflow import = 主契约模块——
收集期整文件失败是预期（pytest exit 2 / collected 0 items / 1 error），GREEN 落地后
整文件自动收集）:
    from inkflow.domain.services.preference_learner import (
        aggregate_candidates, classify_edit, confidence_for, extract_edits,
    )
（TextEdit / PreferenceCandidate 契约符号仅 docstring 钉死——测试体零引用，
断言走字段访问 + StrEnum 字符串字面量，免 F401）
inkflow.domain.models.preference / memory_event 同缺但不顶层 import——分类断言走
StrEnum 字符串字面量（PreferenceCategory 继承 str，== 字面量恒真），MemoryEvent
构造在 _make_event 函数体惰性 import——收集错误只报主契约模块单一缺失（F21/F34
实测规则）。

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. 领域模型（domain/models/preference.py 新建，RED 时不存在）:

       class PreferenceCategory(StrEnum):
           ADDRESSING = "addressing"
           STYLE_WORD = "style_word"
           STRUCTURE = "structure"
           OTHER = "other"

       class ProjectPreference(BaseModel):
           model_config = {"from_attributes": True}
           id: str
           project_id: uuid.UUID
           category: PreferenceCategory
           pattern: str
           value: str
           confidence: float
           count: int
           source_events: list[str] = []
           created_at: datetime
           updated_at: datetime

2. diff 事件模型（domain/models/memory_event.py 新建）:

       class MemoryEventType(StrEnum):
           DRAFT_EDITED = "draft_edited"
           DRAFT_REJECTED = "draft_rejected"
           DRAFT_CONFIRMED = "draft_confirmed"

       class MemoryEvent(BaseModel):
           model_config = {"from_attributes": True}
           id: str
           project_id: uuid.UUID
           draft_id: str | None = None
           chapter_id: uuid.UUID | None = None
           agent_run_id: str | None = None
           event_type: MemoryEventType
           before_content: str | None = None
           after_content: str | None = None
           diff_chars: int = 0
           created_at: datetime

3. preference_learner.py 纯函数（零 IO，无依赖注入）:

       @dataclass
       class TextEdit:
           pattern: str
           value: str
           category: PreferenceCategory

       @dataclass
       class PreferenceCandidate:
           category: PreferenceCategory
           pattern: str
           value: str
           count: int
           confidence: float

       def extract_edits(before: str, after: str) -> list[TextEdit]
           # difflib replace 片段对 + 噪声过滤：长度<2 跳过 / value 纯标点
           # 跳过 / value>50 跳过
           # SequenceMatcher replace 块给出旧文本 i1:i2 与新文本 j1:j2；
           # 若其中一段为空（纯删除/纯插入）跳过该候选（只学替换）
           # 噪声阈值「长度<2」作用于 value（契约① pattern=「她」长度 1
           # 仍产出 → pattern 长度不参与过滤）
           # 单事件内多片段 → 每片段独立候选（spec §5.2 边界）

       def classify_edit(pattern: str, value: str,
                         character_names: list[str] | None = None
                         ) -> PreferenceCategory
           # 判定顺序: addressing → structure → style_word → other
           # addressing: value 命中 character_names（value in names 或任一
           #   name 是 value 子串）；或 pattern/value 含称谓动词（称呼/叫/唤/称）
           # structure: pattern 或 value 含行首 Markdown 标记
           #   （#、- 、* 、数字+点）
           # style_word: 2 <= len(value) <= 20 且 value 不以句末标点
           #   （。！？；）结尾
           # other: 兜底

       def aggregate_candidates(events: list[MemoryEvent]
                                ) -> list[PreferenceCandidate]
           # 只取 DRAFT_EDITED（draft_rejected/draft_confirmed 不提取——spec §5.2）
           # 聚合键 = (project_id, category, value)——跨项目不混算
           #   （父侧契约⑦：输入可跨项目事件，按 event.project_id 区分）
           # 同键聚合 count；count<2 不产出；confidence = 1 - 1/(count+1)

       def confidence_for(count: int) -> float
           # 1 - 1/(count+1)（单调递增: N=2→0.667, N=3→0.75, N=5→0.833）

RED 预期
--------
全文件收集期失败（1c 整模块 RED 形态: pytest exit 2 / collected 0 items / 1 error）:
    ModuleNotFoundError: No module named 'inkflow.domain.services.preference_learner'
（父包 inkflow.domain.services 已存在、子模块文件缺失 → ModuleNotFoundError；
F21/F34 实测：子模块缺失报 ModuleNotFoundError，仅父包内名字缺失报 ImportError）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from inkflow.domain.services.preference_learner import (
    aggregate_candidates,
    classify_edit,
    confidence_for,
    extract_edits,
)

PROJECT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
PROJECT_B = uuid.UUID("22222222-2222-4222-8222-222222222222")


def _make_event(
    event_id: str, project_id: uuid.UUID, *, event_type="draft_edited", before=None, after=None
):
    """构造 MemoryEvent（惰性 import——RED 时模块缺失；GREEN 落地后自动解析）."""
    from inkflow.domain.models.memory_event import MemoryEvent

    return MemoryEvent(
        id=event_id,
        project_id=project_id,
        event_type=event_type,
        before_content=before,
        after_content=after,
        created_at=datetime.now(UTC),
    )


def _pairs(edits):
    return [(e.pattern, e.value) for e in edits]


# ── 契约 1: extract_edits 替换片段提取 ──


def test_extract_edits_replacement_pair() -> None:
    """契约①: 单替换片段 → (pattern, value) 正确提取 + category 填充."""
    edits = extract_edits("她推开门", "林晚推开门")
    assert _pairs(edits) == [("她", "林晚")]
    # 无 character_names → 非 addressing；len 2 无句末标点 → style_word
    assert edits[0].category == "style_word"


def test_extract_edits_pure_insert_skipped() -> None:
    """契约②a: 纯插入（旧片段为空）不产出——只学替换."""
    assert extract_edits("你好", "你好啊") == []


def test_extract_edits_pure_delete_skipped() -> None:
    """契约②b: 纯删除（新片段为空）不产出."""
    assert extract_edits("你好啊", "你好") == []


def test_extract_edits_noise_value_too_short() -> None:
    """契约③a: value 长度 <2 → 噪声过滤跳过."""
    assert extract_edits("甲乙", "甲丙") == []  # value=「丙」长度 1


def test_extract_edits_noise_value_pure_punctuation() -> None:
    """契约③b: value 纯标点 → 噪声过滤跳过."""
    assert extract_edits("这是好的。", "这是好的！！") == []  # value=「！！」


def test_extract_edits_noise_value_too_long() -> None:
    """契约③c: value 长度 >50 → 噪声过滤跳过."""
    before = "甲" + "x" * 50
    after = "甲" + "y" * 51
    assert extract_edits(before, after) == []  # value=51 字符


def test_extract_edits_identical_text_empty() -> None:
    """契约③d: before == after（无实际修改）→ 空结果（幂等，spec §5.2 边界）."""
    assert extract_edits("一样的内容", "一样的内容") == []


def test_extract_edits_multiple_fragments() -> None:
    """契约④: 单事件内多替换片段 → 每片段独立候选."""
    edits = extract_edits("她推开门说", "林晚推开门低声道")
    assert _pairs(edits) == [("她", "林晚"), ("说", "低声道")]


# ── 契约 2: classify_edit 四类判定 ──


def test_classify_addressing_character_names() -> None:
    """契约⑤a: value 命中 character_names → addressing（精确命中 + 子串命中）."""
    assert classify_edit("她", "林晚", ["林晚"]) == "addressing"
    assert classify_edit("她", "林晚", ["晚"]) == "addressing"  # name 是 value 子串


def test_classify_addressing_verb() -> None:
    """契约⑤b: pattern/value 含称谓动词（称呼/叫/唤/称）→ addressing."""
    assert classify_edit("称呼", "叫唤") == "addressing"  # pattern 含「称呼」
    assert classify_edit("低声", "称呼道") == "addressing"  # value 含「称呼」


def test_classify_structure_markdown() -> None:
    """契约⑤c: pattern/value 含行首 Markdown 标记（# / - / * / 数字+点）→ structure."""
    assert classify_edit("旧段落", "# 新标题") == "structure"  # value 行首 #
    assert classify_edit("1. 旧大纲", "2. 新大纲") == "structure"  # pattern 数字+点
    assert classify_edit("- 旧列表", "列表项") == "structure"  # pattern 行首 -


def test_classify_style_word() -> None:
    """契约⑤d: 2 <= len(value) <= 20 且不以句末标点（。！？；）结尾 → style_word."""
    assert classify_edit("说", "低声道") == "style_word"
    assert classify_edit("说", "嗯") == "other"  # 长度 <2
    assert classify_edit("说", "低声道。") == "other"  # 句末标点结尾
    assert classify_edit("说", "字" * 21) == "other"  # 长度 >20


def test_classify_other_fallback() -> None:
    """契约⑤e: 无 names / 无动词 / 无标记 / 不满足长度规则 → other 兜底."""
    assert classify_edit("abc", "xyz") == "other"


# ── 契约 3: aggregate_candidates 阈值聚合 ──


def test_aggregate_threshold_two_events() -> None:
    """契约⑥a: 1 次事件无产出；同项目 2 次同 (category, value) → count=2 产出."""
    evt = _make_event("evt-1", PROJECT_A, before="她推开门", after="林晚推开门")
    assert aggregate_candidates([evt]) == []  # count=1 <2 不产出
    cands = aggregate_candidates(
        [
            evt,
            _make_event("evt-2", PROJECT_A, before="她推开门", after="林晚推开门"),
        ]
    )
    assert len(cands) == 1
    c = cands[0]
    assert c.category == "style_word"
    assert c.pattern == "她"
    assert c.value == "林晚"
    assert c.count == 2
    assert c.confidence == pytest.approx(2 / 3)  # 1 - 1/(2+1)


def test_aggregate_three_events_escalates() -> None:
    """契约⑥b: 3 次同键 → count=3，confidence 重算 ≈0.75."""
    evts = [
        _make_event(f"evt-{i}", PROJECT_A, before="她推开门", after="林晚推开门") for i in range(3)
    ]
    cands = aggregate_candidates(evts)
    assert len(cands) == 1
    assert cands[0].count == 3
    assert cands[0].confidence == pytest.approx(0.75)


def test_aggregate_project_isolation() -> None:
    """契约⑦: 聚合键含 project_id——跨项目同 value 不混算."""
    a1 = _make_event("a1", PROJECT_A, before="她推开门", after="林晚推开门")
    b1 = _make_event("b1", PROJECT_B, before="她推开门", after="林晚推开门")
    assert aggregate_candidates([a1, b1]) == []  # 各项目仅 1 次
    a2 = _make_event("a2", PROJECT_A, before="她推开门", after="林晚推开门")
    cands = aggregate_candidates([a1, b1, a2])
    assert len(cands) == 1
    assert cands[0].count == 2  # 只聚合 PROJECT_A 的 2 次


def test_aggregate_ignores_non_edited() -> None:
    """契约⑥e: 非 DRAFT_EDITED 事件不参与聚合（只学用户编辑，spec §5.2）."""
    evts = [
        _make_event("e1", PROJECT_A, event_type="draft_rejected"),
        _make_event("e2", PROJECT_A, event_type="draft_confirmed"),
    ]
    assert aggregate_candidates(evts) == []


def test_aggregate_skips_event_missing_content() -> None:
    """契约⑥f: edited 事件缺 before/after 内容 → 跳过（QA 补测 2026-08-11，覆盖 178 行）."""
    evts = [
        _make_event("e1", PROJECT_A, before=None, after="林晚推开门"),
        _make_event("e2", PROJECT_A, before="她推开门", after=None),
        _make_event("e3", PROJECT_A, before="她推开门", after="林晚推开门"),
    ]
    cands = aggregate_candidates(evts)
    assert len(cands) == 0  # 前两个缺内容跳过；e3 单次 count=1 <2 不产出


def test_aggregate_ignores_confirmed_rejected() -> None:
    """契约⑥c: 只取 DRAFT_EDITED——confirmed/rejected 事件不提取."""
    confirmed = _make_event(
        "c1", PROJECT_A, event_type="draft_confirmed", before=None, after="正文"
    )
    rejected = _make_event("r1", PROJECT_A, event_type="draft_rejected", before="正文", after=None)
    assert aggregate_candidates([confirmed, rejected]) == []


# ── 契约 4: confidence_for 单调 ──


def test_confidence_for_monotonic() -> None:
    """契约⑧: confidence_for 单调递增（2→0.667, 3→0.75, 5→0.833）."""
    assert confidence_for(2) == pytest.approx(2 / 3)
    assert confidence_for(3) == pytest.approx(0.75)
    assert confidence_for(5) == pytest.approx(5 / 6)
