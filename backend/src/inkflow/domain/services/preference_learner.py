"""F28 偏好提取算法 — 规则化统计纯函数模块（difflib + N≥2 阈值，ADR-G）.

本模块是偏好学习闭环的提取核心（spec §5.2）:
- extract_edits: difflib.SequenceMatcher replace 片段对 + 噪声过滤（零 IO）;
- classify_edit: 四类判定（addressing → structure → style_word → other，
  Q1 拍板）;
- aggregate_candidates: 事件列表 → 候选偏好聚合（同项目同 (category, value)
  N≥2 才产出，跨项目不混算）;
- confidence_for: 置信度公式 1 - 1/(count+1)（单调递增）.

纯函数零依赖注入：不 import 任何框架 / 仓储，测试直接直测（spec §9）。
依据: specs/f28-agent-memory/spec.md §5.2/§9。
"""

from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass

from inkflow.domain.models.memory_event import MemoryEvent, MemoryEventType
from inkflow.domain.models.preference import PreferenceCategory

# 称谓动词（spec §5.2 分类 1: pattern/value 含「称呼/叫/唤/称」之一 → addressing）。
_ADDRESSING_VERBS = ("称呼", "叫", "唤", "称")

# 行首 Markdown 结构标记（spec §5.2 分类 3: 行首 # / - / * / 数字+点）。
_MARKDOWN_LINE_RE = re.compile(r"^\s*(?:#{1,6}\s+|[-*]\s+|\d+\.\s+)")

# 句末标点（spec §5.2 分类 2: value 以句末标点结尾不判 style_word）。
_SENTENCE_END_CHARS = ("。", "！", "？", "；")

# CJK 汉字范围（style_word 隐含契约: value 须含汉字——纯 ASCII 如「xyz」不判
# style_word，测试契约⑫「abc」/「xyz」→ other，测试断言为准）。
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")

# 纯标点字符集（噪声过滤: value 全为标点 → 跳过；含空白/换行纯变体，
# spec §5.2「忽略空白/换行纯变体」）。
_PUNCTUATION_CHARS = frozenset("，。！？；：、,.!?;:'\"“”‘’（）()【】[]《》〈〉…—～· \t\r\n")


@dataclass
class TextEdit:
    """一段用户修改（difflib 提取的替换片段对）.

    Attributes:
        pattern: 被替换的旧文本.
        value: 替换后的新文本.
        category: 分类维度（extract_edits 内部经 classify_edit 填充）.
    """

    pattern: str
    value: str
    category: PreferenceCategory


@dataclass
class PreferenceCandidate:
    """聚合后的候选偏好（count>=2 才可落库）.

    Attributes:
        category: 分类维度.
        pattern: 该组首个片段的 pattern（被替换旧文本）.
        value: 偏好值（用户反复修改后保留的新文本）.
        count: 支撑事件数.
        confidence: 置信度（confidence_for(count)）.
    """

    category: PreferenceCategory
    pattern: str
    value: str
    count: int
    confidence: float


def extract_edits(before: str, after: str) -> list[TextEdit]:
    """difflib.SequenceMatcher opcodes → replace 片段对 + 噪声过滤.

    - 只取 replace 操作；replace 块中旧文本或新文本为空（纯删除/纯插入）→ 跳过
    - 过滤: value 长度 < 2 或 > 50 → 跳过（pattern 长度不参与过滤——契约①
      pattern=「她」长度 1 仍产出）; value 纯标点 → 跳过
    - 单事件内多片段 → 每片段独立候选（spec §5.2 边界）
    - category 经 classify_edit(pattern, value) 填充（无角色名 → 非 addressing 分支）

    Args:
        before: 修改前内容.
        after: 修改后内容.

    Returns:
        TextEdit 列表（噪声已过滤，分类已填充）.
    """
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    edits: list[TextEdit] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        pattern = before[i1:i2]
        value = after[j1:j2]
        if not pattern or not value:
            continue
        if len(value) < 2 or len(value) > 50:
            continue
        if all(ch in _PUNCTUATION_CHARS for ch in value):
            continue
        edits.append(
            TextEdit(
                pattern=pattern,
                value=value,
                category=classify_edit(pattern, value),
            )
        )
    return edits


def classify_edit(
    pattern: str,
    value: str,
    character_names: list[str] | None = None,
) -> PreferenceCategory:
    """四类判定（Q1=A），判定顺序: addressing → structure → style_word → other.

    - ADDRESSING: value 命中 character_names（value in names 或任一 name 是
      value 的子串）；或 pattern/value 含称谓动词之一（称呼/叫/唤/称）
    - STRUCTURE: pattern 或 value 含行首 Markdown 标记（行首 # / - / * / 数字+点）
    - STYLE_WORD: 2 <= len(value) <= 20 且 value 不以句末标点（。！？；）结尾
      且含汉字（纯 ASCII 值不判 style_word——测试契约⑫「abc」/「xyz」→ other）
    - OTHER: 兜底

    Args:
        pattern: 被替换的旧文本.
        value: 替换后的新文本.
        character_names: 项目角色名列表（可空；空则不判 addressing 名称分支）.

    Returns:
        命中的偏好分类.
    """
    if character_names and (
        value in character_names or any(name in value for name in character_names)
    ):
        return PreferenceCategory.ADDRESSING
    if any(verb in pattern or verb in value for verb in _ADDRESSING_VERBS):
        return PreferenceCategory.ADDRESSING
    if _MARKDOWN_LINE_RE.match(pattern) or _MARKDOWN_LINE_RE.match(value):
        return PreferenceCategory.STRUCTURE
    if (
        2 <= len(value) <= 20
        and not value.endswith(_SENTENCE_END_CHARS)
        and _CJK_CHAR_RE.search(value) is not None
    ):
        return PreferenceCategory.STYLE_WORD
    return PreferenceCategory.OTHER


def aggregate_candidates(events: list[MemoryEvent]) -> list[PreferenceCandidate]:
    """事件列表 → 候选偏好聚合（阈值语义 N≥2，spec §5.2）.

    - 只取 event_type == DRAFT_EDITED 的事件（draft_rejected/draft_confirmed
      不提取——spec §5.2）
    - 每事件用 extract_edits(before_content, after_content) 提取片段对，再
      classify_edit 分类；聚合键 = (event.project_id, category, value)——跨项目
      不混算
    - 每组聚合: pattern 取该组首个片段的 pattern；count = 组内事件出现次数
      （单事件内重复同键片段只计一次）；confidence = confidence_for(count)
    - count < 2 → 不产出（1 次修改不学，ADR-G 阈值）

    Args:
        events: 项目事件列表（可跨项目——按 event.project_id 区分）.

    Returns:
        满足 N≥2 阈值的 PreferenceCandidate 列表（无顺序保证，按聚合首见序）.
    """
    groups: dict[tuple[uuid.UUID, PreferenceCategory, str], tuple[set[str], str]] = {}
    for event in events:
        if event.event_type != MemoryEventType.DRAFT_EDITED:
            continue
        if not event.before_content or not event.after_content:
            continue
        seen_in_event: set[str] = set()
        for edit in extract_edits(event.before_content, event.after_content):
            category = classify_edit(edit.pattern, edit.value)
            key = (event.project_id, category, edit.value)
            event_ids, _ = groups.setdefault(key, (set(), edit.pattern))
            if event.id not in seen_in_event:
                event_ids.add(event.id)
                seen_in_event.add(event.id)
    return [
        PreferenceCandidate(
            category=category,
            pattern=first_pattern,
            value=value,
            count=len(event_ids),
            confidence=confidence_for(len(event_ids)),
        )
        for (_, category, value), (event_ids, first_pattern) in groups.items()
        if len(event_ids) >= 2
    ]


def confidence_for(count: int) -> float:
    """置信度公式: 1 - 1 / (count + 1)（单调递增: N=2→0.667, N=3→0.75, N=5→0.833）.

    Args:
        count: 支撑事件数（≥1）.

    Returns:
        置信度浮点值（0-1 区间）.
    """
    return 1 - 1 / (count + 1)


@dataclass
class UserPreferenceCandidate:
    """用户级聚合候选（spec §5.1 M1 扩展）——跨项目 (category, value) 聚合，
    project_count≥2 才可落库。

    Attributes:
        category: 分类维度.
        pattern: 该组首个片段的 pattern（被替换旧文本）.
        value: 偏好值（用户反复修改后保留的新文本）.
        count: 支撑事件数（跨项目累计）.
        project_count: 支撑项目数.
        source_projects: 支撑项目 id 字符串列表（去重）.
        source_events: 支撑事件 id 列表（去重）.
        confidence: 置信度（confidence_for(count)）.
    """

    category: PreferenceCategory
    pattern: str
    value: str
    count: int
    project_count: int
    source_projects: list[str]
    source_events: list[str]
    confidence: float


def aggregate_user_candidates(events: list[MemoryEvent]) -> list[UserPreferenceCandidate]:
    """事件列表 → 用户级候选聚合（跨项目，spec §5.1 M1 扩展）.

    与 aggregate_candidates 共享 extract_edits（零重复 difflib 计算）：
    1) 只取 event_type == DRAFT_EDITED 且 before_content/after_content 非空
    2) 每事件 extract_edits(before_content, after_content) 提取片段
    3) 聚合键 = (category, value)（无 project_id 维度）；同事件内重复同键只计一次
    4) count = 去重后事件数（跨项目累计）；projects = {event.project_id}；
       project_count = len(projects)
    5) source_projects = 支撑项目 id 字符串列表（去重）、source_events = 支撑事件 id 列表（去重）
    6) 阈值: count >= 2 且 project_count >= 2 才产出（保守规则——仅 1 个项目出现永不升用户级）
    7) pattern = 该组首个片段的 pattern；confidence = confidence_for(count)

    Args:
        events: 事件列表（可跨项目——用户级聚合无 project_id 维度）.

    Returns:
        满足 count>=2 且 project_count>=2 阈值的 UserPreferenceCandidate 列表
        （按聚合首见序）.
    """
    groups: dict[tuple[PreferenceCategory, str], tuple[set[str], set[str], str]] = {}
    for event in events:
        if event.event_type != MemoryEventType.DRAFT_EDITED:
            continue
        if not event.before_content or not event.after_content:
            continue
        seen_in_event: set[tuple[PreferenceCategory, str]] = set()
        for edit in extract_edits(event.before_content, event.after_content):
            category = classify_edit(edit.pattern, edit.value)
            key = (category, edit.value)
            if key in seen_in_event:
                continue
            seen_in_event.add(key)
            event_ids, project_ids, _ = groups.setdefault(key, (set(), set(), edit.pattern))
            event_ids.add(event.id)
            project_ids.add(str(event.project_id))
    return [
        UserPreferenceCandidate(
            category=category,
            pattern=first_pattern,
            value=value,
            count=len(event_ids),
            project_count=len(project_ids),
            source_projects=sorted(project_ids),
            source_events=sorted(event_ids),
            confidence=confidence_for(len(event_ids)),
        )
        for (category, value), (event_ids, project_ids, first_pattern) in groups.items()
        if len(event_ids) >= 2 and len(project_ids) >= 2
    ]
