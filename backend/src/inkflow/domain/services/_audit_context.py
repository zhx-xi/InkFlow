"""F34 章节审计上下文纯函数层（spec §5.4）— 章节截断采样 + 档案条目选取.

依据 specs/f34-chapter-audit/spec.md §5.4：章节全文超过 8000 字符时按段落
（\\n\\n 或 \\n）取首段 + 末段 + 中间均匀采样，总长控制在原长 60% 左右，
末尾追加「（已截断，仅节选）」标注；角色/设定条目按「名称在章节文本中
出现」优先选取（保持原相对顺序），未出现的排后，最多 _MAX_ENTITY_COUNT 条；
条目内容截断（≤ _MAX_ENTITY_CHARS）由 service 层负责，本函数只选条目。

镜像 _style_analyzer.py 先例：全部为模块级纯函数，无 I/O、无副作用、
严格幂等（同输入同输出）；仅依赖标准库（typing），不 import 任何框架 /
infrastructure（ADR-002/015：domain 层零框架 import）。

函数契约以 tests/unit/test_audit_context.py 为准（RED 测试即契约）:
- truncate_chapter(content) -> tuple[str, bool]
- select_entities(entities, text) -> list
- 常量 _MAX_CHAPTER_CHARS / _MAX_ENTITY_CHARS / _MAX_ENTITY_COUNT
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 上下文预算常量（spec §5.4 —— 集中本模块，防魔法数字散落，可单测）
# ---------------------------------------------------------------------------

_MAX_CHAPTER_CHARS = 8000  # 章节全文预算（超过则采样截断）
_MAX_ENTITY_CHARS = 500  # 单条档案内容预算（service 层截断）
_MAX_ENTITY_COUNT = 20  # 单次选取档案条目上限

# 截断标注（spec §5.4「LLM 提示『已截断，关注节选』」；测试断言「已截断」字样）
_TRUNCATE_MARKER = "（已截断，仅节选）"

# 回退分块大小：单段/少段超预算时按固定字符块切分后再采样，
# 保证首 + 末 + 标注远小于 60% 预算（>8000 字符时必然可容纳）
_CHUNK_CHARS = 800


def _split_paragraphs(content: str) -> list[str]:
    """按段落分隔符切分章节文本（优先 \\n\\n，其次 \\n），过滤空段落。"""
    parts = content.split("\n\n") if "\n\n" in content else content.split("\n")
    return [part for part in parts if part]


def _uniform_indices(count: int, sample_size: int) -> list[int]:
    """在 [0, count) 上均匀取 sample_size 个下标（确定性均匀覆盖）。"""
    return [i * count // sample_size for i in range(sample_size)]


def _joined_length(paragraphs: list[str]) -> int:
    """计算段落列表以 \\n\\n 连接后的总长（不含截断标注）。"""
    if not paragraphs:
        return 0
    return sum(len(p) for p in paragraphs) + 2 * (len(paragraphs) - 1)


def _sample_paragraphs(
    paragraphs: list[str],
    max_chars: int,
    marker_len: int,
) -> list[str]:
    """首段 + 末段 + 中间均匀采样，总长（含分隔符与标注）不超过 max_chars.

    Args:
        paragraphs: 切分后的段落/分块列表.
        max_chars: 截断总预算（含截断标注）.
        marker_len: 截断标注字符数.

    Returns:
        采样后的段落列表（首/末段保留，中间均匀子采样）.
    """
    if len(paragraphs) <= 2:
        return paragraphs
    first, last = paragraphs[0], paragraphs[-1]
    middle = paragraphs[1:-1]
    # 悲观预算：分隔符按最多情形预留（2*(k+1) ≤ 2*len(middle)+2），
    # 保证最终连接（含标注）不超 max_chars（k 为选中中间段数）
    budget = max_chars - marker_len - len(first) - len(last) - 2 * len(middle) - 2
    if sum(len(p) for p in middle) <= budget:
        return paragraphs
    avg = sum(len(p) for p in middle) / len(middle)
    sample_size = max(1, int(budget / avg)) if avg > 0 else 1
    while sample_size > 0:
        indices = _uniform_indices(len(middle), sample_size)
        chosen = [middle[i] for i in indices]
        if sum(len(p) for p in chosen) <= budget:
            return [first, *chosen, last]
        sample_size -= 1
    return [first, last]


def _chunk_text(content: str, size: int) -> list[str]:
    """将文本按固定字符长度切块（单段/少段超预算时的回退分段）。"""
    return [content[i : i + size] for i in range(0, len(content), size)]


def truncate_chapter(content: str) -> tuple[str, bool]:
    """章节全文上下文截断（spec §5.4：8000 字符预算 + 超长采样截断）.

    Args:
        content: 章节全文.

    Returns:
        (截断后文本, 是否截断)：≤8000 字符原样返回 + False；超长时按
        首段 + 末段 + 中间均匀采样（总长 ≤ 原长 60% 左右），末尾追加
        「（已截断，仅节选）」标注，返回 + True；空文本原样返回 + False.
    """
    if len(content) <= _MAX_CHAPTER_CHARS:
        return content, False
    max_chars = int(len(content) * 0.6)
    selected = _sample_paragraphs(_split_paragraphs(content), max_chars, len(_TRUNCATE_MARKER))
    # 首/末段自身超预算（或段落过少）时退化为固定块切分后再采样
    if _joined_length(selected) + len(_TRUNCATE_MARKER) > max_chars:
        selected = _sample_paragraphs(
            _chunk_text(content, _CHUNK_CHARS), max_chars, len(_TRUNCATE_MARKER)
        )
    return "\n\n".join(selected) + _TRUNCATE_MARKER, True


def select_entities(entities: list[Any], text: str) -> list[Any]:
    """档案条目按相关性选取（spec §5.4：名称匹配优先 + 20 条上限）.

    名称匹配为子串语义（name in text）；匹配条目保持原相对顺序排前，
    未匹配条目保持原相对顺序排后；最多返回 _MAX_ENTITY_COUNT 条；
    条目内容截断（≤ _MAX_ENTITY_CHARS）由 service 层负责，本函数只选条目.

    Args:
        entities: 角色/设定条目列表（对象须有 .name 属性）.
        text: 章节文本（名称匹配依据）.

    Returns:
        选取后的条目列表（最多 _MAX_ENTITY_COUNT 条；空列表返回 []）.
    """
    matched = [entity for entity in entities if entity.name in text]
    unmatched = [entity for entity in entities if entity.name not in text]
    return (matched + unmatched)[:_MAX_ENTITY_COUNT]
