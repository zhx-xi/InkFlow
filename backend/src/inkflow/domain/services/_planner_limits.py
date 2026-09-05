"""F44 #927 访谈回答 → 书级运行上限提取（纯函数，无 IO）.

planner 完成路径按用户访谈回答 / 已确定项文本中的「N 章」声明提取
max_chapters 与 max_agent_calls（卷轨拆章 + 逐章委托余量，保持 STAGE1
「章:调用 = 1:2」精神）；未命中保守回退 STAGE1_LIMITS（1/1，向后兼容）。

依据: specs/f44-book-orchestrator/spec.md §2.4 + Issue #927。
"""

from __future__ import annotations

import re

_CHAPTER_SEQUENCE_RE = re.compile(r"第\s*\d+\s*章")
"""章序引用（第N章）——不是章数声明，提取前剔除，防误抽."""

_CHAPTER_COUNT_RE = re.compile(r"(\d+)\s*章")
"""章数声明：阿拉伯数字紧跟「章」（允许中间空白）."""


def extract_limits_from_interview(
    answers: dict[str, str],
    confirmed_items: list[dict],
) -> dict[str, int]:
    """从访谈 answers + confirmed_items 文本提取章数上限.

    Args:
        answers: 用户回答快照 {question_id: answer}.
        confirmed_items: 已确定项快照（{"key", "value", "source"}）.

    Returns:
        {"max_chapters": n, "max_agent_calls": 2 * n}；多处命中取最大值；
        无章数声明时保守返回 {"max_chapters": 1, "max_agent_calls": 1}.
    """
    texts = [text for text in answers.values() if isinstance(text, str)]
    texts.extend(
        value for item in confirmed_items if isinstance(value := item.get("value"), str)
    )
    max_chapters = 0
    for text in texts:
        stripped = _CHAPTER_SEQUENCE_RE.sub("", text)
        counts = [int(raw) for raw in _CHAPTER_COUNT_RE.findall(stripped)]
        if counts:
            max_chapters = max(max_chapters, max(counts))
    if max_chapters <= 0:
        return {"max_chapters": 1, "max_agent_calls": 1}
    return {"max_chapters": max_chapters, "max_agent_calls": 2 * max_chapters}
