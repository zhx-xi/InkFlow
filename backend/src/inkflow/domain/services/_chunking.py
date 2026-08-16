"""章节文本分块工具 — 策略模式切片器（fixed / paragraph / dialogue / llm）.

F14 §5.6.1-§5.6.3 分块规则（#277 M3）: 策略模式支持固定长度（标点回溯）、
段落（空行切分 + 超长降级 FIXED）、对话/LLM（M3 降级段落）三种形态；
overlap_ratio 开启滑动重叠（spec §5.6.3），start_offset 记录每块在原文中的
起始字符偏移（0-based）。

纯函数，仅标准库，无框架依赖（ADR-002/015: domain 层零框架 import）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

_PUNCTUATION_BOUNDARIES = "。！？\n"


class ChunkingMode(StrEnum):
    """切片模式（spec §5.6.1）— M3 实现 fixed/paragraph，dialogue/llm 降级段落。"""

    FIXED = "fixed"
    PARAGRAPH = "paragraph"
    DIALOGUE = "dialogue"
    LLM = "llm"


@dataclass(frozen=True)
class Chunk:
    """单个文本块 — 块文本 + 起始字符偏移（0-based，spec §5.6.1）。"""

    text: str
    start_offset: int


@dataclass(frozen=True)
class ChunkingConfig:
    """切片配置（spec §5.6.1）— 门面注入 / settings 4 键映射。"""

    mode: ChunkingMode = ChunkingMode.FIXED
    chunk_size: int = 500
    overlap_ratio: float = 0.0


def chunk_text(
    text: str,
    *,
    mode: ChunkingMode = ChunkingMode.FIXED,
    chunk_size: int = 500,
    overlap_ratio: float = 0.0,
    analyzer: Callable[[str], list[int]] | None = None,  # 预留 M4 LLM 档，本批不使用
) -> list[Chunk]:
    """将文本按配置策略切分为块列表（Chunk 含 start_offset）.

    规则:
    - 空文本 → []
    - chunk_size <= 0 → ValueError（避免空块与死循环）
    - mode=FIXED: 优先在标点边界（。！？\n）回溯切分，找不到标点则硬切
    - mode=PARAGRAPH: 空行（\n\n）切分段落；单段 <= chunk_size 直接一块；
      单段 > chunk_size 降级 FIXED 标点回溯逻辑；单 \n 保留在段内
    - mode=DIALOGUE / LLM（M3 未实现真规则）→ 降级段落切片结果（§13 M12）
    - overlap_ratio=0.0: 相邻块无重叠，start_offset 逐块累加，拼接还原原文
    - overlap_ratio>0: 滑动重叠，相邻块共享 int(chunk_size * overlap_ratio) 字符

    Args:
        text: 待切分文本.
        mode: 切片模式（默认 FIXED）.
        chunk_size: 每块目标字符数，必须大于 0（默认 500）.
        overlap_ratio: 重叠率（0.0 = 关；>0 滑动重叠）.
        analyzer: 预留 M4 LLM 档边界提供器（本批不使用，恒 None）.

    Returns:
        切分后的 Chunk 列表；空文本返回空列表.

    Raises:
        ValueError: chunk_size <= 0 时抛出.
    """
    if mode in (ChunkingMode.DIALOGUE, ChunkingMode.LLM):
        # M3 降级：对话/LLM 未实现真规则，返回段落切片结果（spec §13 M12）
        mode = ChunkingMode.PARAGRAPH
    if mode is ChunkingMode.PARAGRAPH:
        return _chunk_paragraph(text, chunk_size, overlap_ratio)
    return _chunk_fixed(text, chunk_size, overlap_ratio)


def _chunk_fixed(text: str, chunk_size: int, overlap_ratio: float = 0.0) -> list[Chunk]:
    """FIXED 模式: 标点回溯切分（含滑动重叠支持，spec §5.6.3）。"""
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    chunks: list[Chunk] = []
    start = 0
    total = len(text)
    overlap_len = int(chunk_size * overlap_ratio) if overlap_ratio > 0 else 0
    while start < total:
        end = start + chunk_size
        if end >= total:
            # 最后一块: 直接取到文本末尾
            chunks.append(Chunk(text=text[start:], start_offset=start))
            break
        # 非最后一块: 从边界向前回溯，找最近的标点边界（在其后切分）
        cut = end
        while cut > start and text[cut - 1] not in _PUNCTUATION_BOUNDARIES:
            cut -= 1
        if cut > start:
            end = cut
        chunks.append(Chunk(text=text[start:end], start_offset=start))
        start = end - overlap_len if overlap_len > 0 and end - start > overlap_len else end
        if start <= 0 or start >= total:  # 防死循环
            break
    return chunks


def _chunk_paragraph(text: str, chunk_size: int, overlap_ratio: float = 0.0) -> list[Chunk]:
    """PARAGRAPH 模式: 空行（\n\n）切分段落；超长段落降级 FIXED 标点回溯。"""
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    chunks: list[Chunk] = []
    offset = 0
    paragraphs = text.split("\n\n")
    for index, para in enumerate(paragraphs):
        if len(para) <= chunk_size:
            if para:  # 空段落跳过（无空块）
                chunks.append(Chunk(text=para, start_offset=offset))
        else:
            # 超长段落降级 FIXED（保证单块 <= chunk_size；overlap 透传）
            chunks.extend(
                Chunk(text=c.text, start_offset=offset + c.start_offset)
                for c in _chunk_fixed(para, chunk_size, overlap_ratio)
            )
        offset += len(para)
        if index < len(paragraphs) - 1:
            offset += 2  # 段落间空行分隔符 "\n\n" 长度
    return chunks
