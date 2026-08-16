"""章节文本分块工具 — 策略模式切片器（fixed / paragraph / dialogue / llm）.

F14 §5.6.1-§5.6.7 分块规则（#277 M3 + #278 M4）: 策略模式支持固定长度（标点回溯）、
段落（空行切分 + 超长降级 FIXED）、对话（说话人切换识别 + 短块合并）、
LLM（analyzer 语义边界切分，失败降级段落）四种形态；overlap_ratio 开启滑动重叠
（spec §5.6.3），start_offset 记录每块在原文中的起始字符偏移（0-based）。

纯函数，仅标准库 + logging，无框架依赖（ADR-002/015: domain 层零框架 import）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)

_PUNCTUATION_BOUNDARIES = "。！？\n"

_DIALOGUE_LINE_PREFIXES = ("「", "“", "『", "——", "：“")
"""对话行识别前缀（spec §5.6.6 ①：引号 / 破折号 / 冒号+引号）。"""


class ChunkingMode(StrEnum):
    """切片模式（spec §5.6.1）— fixed/paragraph/dialogue/llm 四档真规则。"""

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
    analyzer: Callable[[str], list[int]] | None = None,
) -> list[Chunk]:
    """将文本按配置策略切分为块列表（Chunk 含 start_offset）.

    规则:
    - 空文本 → []
    - chunk_size <= 0 → ValueError（避免空块与死循环）
    - mode=FIXED: 优先在标点边界（。！？\n）回溯切分，找不到标点则硬切
    - mode=PARAGRAPH: 空行（\n\n）切分段落；单段 <= chunk_size 直接一块；
      单段 > chunk_size 降级 FIXED 标点回溯逻辑；单 \n 保留在段内
    - mode=DIALOGUE: 说话人切换识别（引号/破折号/冒号+引号）+ 连续对话归并 +
      短块向前合并叙述（spec §5.6.6）；无对话行降级段落切片
    - mode=LLM: analyzer 返回语义边界起始偏移（升序）→ 按边界切分；
      analyzer None / 抛异常 → 降级段落切片 + logger.warning（spec §5.6.7 ③）
    - overlap_ratio=0.0: 相邻块无重叠，start_offset 逐块累加，拼接还原原文
    - overlap_ratio>0: 滑动重叠，相邻块共享 int(chunk_size * overlap_ratio) 字符

    Args:
        text: 待切分文本.
        mode: 切片模式（默认 FIXED）.
        chunk_size: 每块目标字符数，必须大于 0（默认 500）.
        overlap_ratio: 重叠率（0.0 = 关；>0 滑动重叠）.
        analyzer: LLM 档语义边界提供器（Callable[[str], list[int]]，升序偏移；
            None = 未配置 → 降级段落切片）.

    Returns:
        切分后的 Chunk 列表；空文本返回空列表.

    Raises:
        ValueError: chunk_size <= 0 时抛出.
    """
    if mode == ChunkingMode.PARAGRAPH:
        return _chunk_paragraph(text, chunk_size, overlap_ratio)
    if mode == ChunkingMode.DIALOGUE:
        return _chunk_dialogue(text, chunk_size, overlap_ratio)
    if mode == ChunkingMode.LLM:
        return _chunk_llm(text, chunk_size, overlap_ratio, analyzer)
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


def _is_dialogue_line(line: str) -> bool:
    """判断一行是否为对话行（说话人切换识别，spec §5.6.6 ①）.

    识别规则: 行 strip 后以 引号（「“『） / 破折号（——） / 冒号+引号（：“）
    开头 → 对话行；行内含 冒号+引号（如「张三：“你来了？”」说话人前缀形态）
    同样视为对话行。空行/叙述行返回 False。
    """
    stripped = line.strip()
    return stripped.startswith(_DIALOGUE_LINE_PREFIXES) or "：“" in stripped


def _chunk_dialogue(
    text: str,
    chunk_size: int,
    overlap_ratio: float = 0.0,
    min_dialogue_len: int = 100,
) -> list[Chunk]:
    """DIALOGUE 模式: 说话人切换识别 + 连续对话归并 + 短块向前合并叙述.

    规则（spec §5.6.6）:
    - 空文本 → []；chunk_size <= 0 → ValueError（与 FIXED/PARAGRAPH 同契约）
    - 按 \n 拆行，行 strip 后以 引号/破折号/冒号+引号 开头（或行内含 “：”）
      → 对话行；连续对话行归并为一块（说话人切换不切块）
    - 短对话块（长度 < min_dialogue_len）且其前有叙述块 → 与前一叙述块合并
      （保持时间顺序：叙述在前、对话在后，\n 连接）
    - 长对话块（>= min_dialogue_len）独立，与相邻叙述块分开
    - 无任何对话行 → 降级段落切片 _chunk_paragraph（不产生空块）
    - 超长块（> chunk_size）→ 内部 _chunk_fixed 标点回溯切分（start_offset
      基于原文绝对偏移，overlap_ratio 透传超长降级路径）

    Args:
        text: 待切分文本.
        chunk_size: 每块目标字符数，必须大于 0.
        overlap_ratio: 重叠率（透传超长降级路径）.
        min_dialogue_len: 对话块长度阈值，低于该值的短对话块向前合并叙述.

    Returns:
        切分后的 Chunk 列表（start_offset 为原文 0-based 偏移）.

    Raises:
        ValueError: chunk_size <= 0 时抛出.
    """
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    # ① 拆行并按类型归并相邻行为块（保留原始行文本与绝对偏移）
    blocks: list[tuple[str, int, bool]] = []  # (text, start_offset, is_dialogue)
    offset = 0
    for line in text.split("\n"):
        is_dialogue = _is_dialogue_line(line)
        if blocks and blocks[-1][2] == is_dialogue:
            prev_text, prev_offset, prev_dialogue = blocks[-1]
            blocks[-1] = (prev_text + "\n" + line, prev_offset, prev_dialogue)
        else:
            blocks.append((line, offset, is_dialogue))
        offset += len(line) + 1

    # ② 无对话行 → 降级段落切片（spec ③）
    if not any(is_dialogue for _, _, is_dialogue in blocks):
        return _chunk_paragraph(text, chunk_size, overlap_ratio)

    # ③ 短对话块向前合并邻近叙述（保持时间顺序，spec ②）
    merged: list[tuple[str, int, bool]] = []
    for block_text, block_offset, is_dialogue in blocks:
        if is_dialogue and len(block_text) < min_dialogue_len and merged and not merged[-1][2]:
            prev_text, prev_offset, prev_dialogue = merged[-1]
            merged[-1] = (prev_text + "\n" + block_text, prev_offset, prev_dialogue)
        else:
            merged.append((block_text, block_offset, is_dialogue))

    # ④ 输出块（超长块内部 _chunk_fixed 标点回溯；空块跳过）
    chunks: list[Chunk] = []
    for block_text, block_offset, _ in merged:
        if not block_text:
            continue
        if len(block_text) <= chunk_size:
            chunks.append(Chunk(text=block_text, start_offset=block_offset))
        else:
            chunks.extend(
                Chunk(text=part.text, start_offset=block_offset + part.start_offset)
                for part in _chunk_fixed(block_text, chunk_size, overlap_ratio)
            )
    return chunks


def _chunk_llm(
    text: str,
    chunk_size: int,
    overlap_ratio: float,
    analyzer: Callable[[str], list[int]] | None,
) -> list[Chunk]:
    """LLM 模式: analyzer 语义边界切分；未配置/抛异常降级段落（spec §5.6.7）.

    规则:
    - 空文本 → []；chunk_size <= 0 → ValueError（与 FIXED/PARAGRAPH 同契约）
    - analyzer None → 降级段落切片 + logger.warning（「LLM 切片器未配置」）
    - analyzer 抛异常 → 降级段落切片 + logger.warning（异常不传播，reindex 不中断）
    - analyzer 返回边界列表（升序）→ 按边界切分: 首块 [0:b0]、次块 [b0:b1]...
      末块 [bn:end]，start_offset 相应；空边界 → 整篇一块
    - 边界防御: 过滤越界/非升序/非整数非法值；非法全过滤后退化为单块而非空

    Args:
        text: 待切分文本.
        chunk_size: 每块目标字符数，必须大于 0（LLM 边界档仅用于校验/降级路径）.
        overlap_ratio: 重叠率（降级段落路径透传）.
        analyzer: 语义边界提供器（Callable[[str], list[int]]，升序起始偏移）.

    Returns:
        切分后的 Chunk 列表（start_offset 为原文 0-based 偏移）.

    Raises:
        ValueError: chunk_size <= 0 时抛出.
    """
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    if analyzer is None:
        logger.warning("LLM 切片器未配置（analyzer=None），降级段落切片")
        return _chunk_paragraph(text, chunk_size, overlap_ratio)

    try:
        boundaries = analyzer(text)
    except Exception as exc:  # analyzer 异常不传播（reindex 不中断，spec §5.6.7 ③）
        logger.warning("LLM 切片器分析失败（%s），降级段落切片", exc)
        return _chunk_paragraph(text, chunk_size, overlap_ratio)

    # 边界防御: 仅保留 (0, len) 内严格升序的整数边界（非法全过滤 → 单块）
    valid: list[int] = []
    for boundary in boundaries:
        if (
            isinstance(boundary, int)
            and not isinstance(boundary, bool)
            and 0 < boundary < len(text)
            and (not valid or boundary > valid[-1])
        ):
            valid.append(boundary)

    if not valid:
        return [Chunk(text=text, start_offset=0)]

    chunks: list[Chunk] = []
    start = 0
    for boundary in valid:
        chunks.append(Chunk(text=text[start:boundary], start_offset=start))
        start = boundary
    chunks.append(Chunk(text=text[start:], start_offset=start))
    return chunks
