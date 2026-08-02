"""章节文本分块工具 — chunk_text 纯函数（~500 字/块，优先标点边界回溯）.

F14 §5.6 分块规则: 按字符 ~500 字/块，优先在段落/句号边界切分（中文文本按
`。！？\\n` 回溯），无重叠；单章 < 500 字 = 1 块；空内容跳过。

纯函数，仅标准库，无框架依赖（ADR-002/015: domain 层零框架 import）。
"""

from __future__ import annotations

_PUNCTUATION_BOUNDARIES = "。！？\n"


def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    """将文本按字符切分为无重叠的块.

    规则:
    - 每块约 chunk_size 字符（按 Python len 计字符，中文每字计 1）
    - 优先在标点边界（。！？\\n）回溯切分——从边界向前找最近的标点，在其后切分
    - 找不到标点则按 chunk_size 硬切
    - 块无重叠且拼接后还原原文；空文本返回空列表

    Args:
        text: 待切分文本.
        chunk_size: 每块目标字符数，必须大于 0（默认 500）.

    Returns:
        切分后的文本块列表；空文本返回空列表.

    Raises:
        ValueError: chunk_size <= 0 时抛出（避免空块与死循环）.
    """
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    chunks: list[str] = []
    start = 0
    total = len(text)
    while start < total:
        end = start + chunk_size
        if end >= total:
            # 最后一块: 直接取到文本末尾
            chunks.append(text[start:])
            break
        # 非最后一块: 从边界向前回溯，找最近的标点边界（在其后切分）
        cut = end
        while cut > start and text[cut - 1] not in _PUNCTUATION_BOUNDARIES:
            cut -= 1
        if cut > start:
            end = cut
        chunks.append(text[start:end])
        start = end
    return chunks
