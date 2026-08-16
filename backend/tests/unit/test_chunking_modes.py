"""F14 切片器变体契约（#277 M3）— 段落 / 重叠 / 块 id / 降级 / 元数据 / 指纹联动.

依据: specs/f14-extraction-service/spec.md §5.6.1-§5.6.5 + §13 M12 验收 + §9 测试策略。
覆盖（§13 M12）: 段落切分 / 重叠率 ∈ 区间 / 块 id 三态 / 对话降级 / LLM 降级 /
元数据输出与 fallback / 指纹联动。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

1. ``inkflow.domain.services._chunking`` 扩展（spec §5.6.1 代码块逐字为准）:
   - ``class ChunkingMode(StrEnum)``: FIXED="fixed" / PARAGRAPH="paragraph" /
     DIALOGUE="dialogue" / LLM="llm"
   - ``@dataclass class Chunk``: ``text: str`` + ``start_offset: int``
   - ``def chunk_text(text, *, mode=ChunkingMode.FIXED, chunk_size=500,
     overlap_ratio=0.0, analyzer=None) -> list[Chunk]``
     * 空文本 → []；chunk_size <= 0 → ValueError（既有契约）
     * mode=DIALOGUE / mode=LLM（M3 未实现真规则）→ 降级段落切片结果
       （§13 M12「对话降级/LLM 降级」；M4 才实现真规则）
     * overlap_ratio > 0 → 相邻块共享 overlap_len = int(chunk_size * overlap_ratio)
       字符，下一块从 end - overlap_len 开始（滑动重叠）
   - 纯函数，零框架依赖（ADR-002/015）

2. ``inkflow.domain.services._extraction_rag._project_chapter_chunk`` 扩展
   （spec §5.6.3/§5.6.4）:
   - 签名: ``(chapter_id, chapter_title, chunk_index, chunk: Chunk, project_id,
     *, overlap: bool = False, chapter_x=None, chapter_y=None,
     volume_title=None, indexed_at=None)``
   - 块 id: overlap=False → ``f"{chapter_id}:{chunk_index}"``（现状不变）；
     overlap=True → ``f"{chapter_id}:{chunk_index}:{chunk.start_offset}"``
   - metadata 新增: ``chunk_start=chunk.start_offset``、``indexed_at``（传参时写入）；
     ``chapter_x/chapter_y/volume_title`` 有值时写入、None 省略（QA §P2-1
     fallback 兜底——新代码禁止直接下标访问缺失键）

3. 指纹联动（§5.6.5，不重定义 #276 协议）: 复用既有
   ``build_fingerprint`` / ``compare_fingerprints``——切片配置（mode/chunk_size/
   overlap_ratio/chunker_version）任一变更 → ``(True, "chunking_changed")``。
   本文件仅锁纯函数层（守护用例，RED 期即 PASS 刻意）；deps 装配层在
   test_deps_embedding.py 覆盖。

RED 形态: 顶层 import ``ChunkingMode`` / ``Chunk``（符号缺失）→ 收集期
ImportError（cannot import name）；段落/重叠/块 id/降级用例失败；
指纹守护用例 PASS。
"""

from __future__ import annotations

import uuid
from itertools import pairwise

import pytest

from inkflow.domain.services._chunking import Chunk, ChunkingMode, chunk_text
from inkflow.domain.services._extraction_rag import _project_chapter_chunk
from inkflow.domain.services.vector_fingerprint import (
    build_fingerprint,
    compare_fingerprints,
)

CH1 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000011")
PID = "3f2e1d4a-0000-4000-8000-000000000001"


class TestParagraphChunking:
    """段落切片器（spec §5.6.2）— 空行切分 + 超长降级标点回溯."""

    def test_paragraph_splits_on_blank_lines(self) -> None:
        """① 空行（连续 \\n\\n）切分段落；单 \\n 不切."""
        text = "第一段。\n\n第二段。\n\n第三段。"
        chunks = chunk_text(text, mode=ChunkingMode.PARAGRAPH, chunk_size=500)
        assert [c.text for c in chunks] == ["第一段。", "第二段。", "第三段。"]
        # 单 \n 保留在段内
        text2 = "第一行\n第二行\n\n新段落。"
        chunks2 = chunk_text(text2, mode=ChunkingMode.PARAGRAPH, chunk_size=500)
        assert [c.text for c in chunks2] == ["第一行\n第二行", "新段落。"]

    def test_paragraph_short_paragraph_single_chunk(self) -> None:
        """② 单段长度 <= chunk_size → 直接作为一块."""
        text = "短段落。" * 10  # 40 字符 < 500
        chunks = chunk_text(text, mode=ChunkingMode.PARAGRAPH, chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0].text == text

    def test_paragraph_long_paragraph_backtracks_punctuation(self) -> None:
        """③ 单段长度 > chunk_size → 降级标点回溯（复用 FIXED 逻辑）."""
        # 一段 1000 字符无空行，第 480 字符处句号 → 第一块应在句号后
        text = "字" * 480 + "。" + "字" * 520
        chunks = chunk_text(text, mode=ChunkingMode.PARAGRAPH, chunk_size=500)
        assert chunks[0].text == "字" * 480 + "。"
        assert len(chunks[0].text) <= 500
        # 拼接还原（降级路径仍是 FIXED 无重叠语义）
        assert "".join(c.text for c in chunks) == text

    def test_paragraph_empty_text(self) -> None:
        """④ 空文本 → []."""
        assert chunk_text("", mode=ChunkingMode.PARAGRAPH) == []

    def test_paragraph_custom_chunk_size(self) -> None:
        """chunk_size 可配（默认 500，范围由 settings 层校验）."""
        text = "甲" * 250
        chunks = chunk_text(text, mode=ChunkingMode.PARAGRAPH, chunk_size=100)
        assert [len(c.text) for c in chunks] == [100, 100, 50]
        assert "".join(c.text for c in chunks) == text

    def test_paragraph_non_positive_chunk_size_raises(self) -> None:
        """chunk_size <= 0 → ValueError（与 FIXED 同契约）."""
        with pytest.raises(ValueError):
            chunk_text("内容", mode=ChunkingMode.PARAGRAPH, chunk_size=0)
        with pytest.raises(ValueError):
            chunk_text("内容", mode=ChunkingMode.PARAGRAPH, chunk_size=-5)


class TestChunkingModesFallback:
    """mode=DIALOGUE / LLM 在 M3 降级段落（§13 M12）."""

    def test_dialogue_mode_falls_back_to_paragraph(self) -> None:
        """对话模式（M3 未实现）→ 降级段落切片结果（不崩、无空块）."""
        text = "第一段。\n\n第二段。"
        expected = chunk_text(text, mode=ChunkingMode.PARAGRAPH)
        actual = chunk_text(text, mode=ChunkingMode.DIALOGUE)
        assert actual == expected
        assert all(c.text for c in actual)

    def test_llm_mode_falls_back_to_paragraph(self) -> None:
        """LLM 模式（M3 未实现，analyzer 未注入）→ 降级段落切片结果."""
        text = "第一段。\n\n第二段。"
        expected = chunk_text(text, mode=ChunkingMode.PARAGRAPH)
        actual = chunk_text(text, mode=ChunkingMode.LLM)
        assert actual == expected
        assert all(c.text for c in actual)


class TestOverlapChunking:
    """滑动重叠（spec §5.6.3）— 默认关；开启后相邻块共享内容."""

    def test_overlap_zero_keeps_reassembly_invariant(self) -> None:
        """overlap=0（默认关）→ 拼接还原原文不变式（现状行为）."""
        text = "章" * 1200
        chunks = chunk_text(text, chunk_size=500, overlap_ratio=0.0)
        assert "".join(c.text for c in chunks) == text
        assert [c.start_offset for c in chunks] == [0, 500, 1000]

    def test_overlap_ratio_within_range(self) -> None:
        """重叠率 ∈ 区间: 相邻块共享字符数 / chunk_size ≈ 配置比例（10%-20%）."""
        text = "章" * 3000
        for ratio in (0.10, 0.15, 0.20):
            chunks = chunk_text(text, chunk_size=500, overlap_ratio=ratio)
            # 每对相邻块的重叠长度 = 上一块 end - 下一块 start
            for prev, nxt in pairwise(chunks):
                overlap_len = (prev.start_offset + len(prev.text)) - nxt.start_offset
                actual_ratio = overlap_len / 500
                assert 0.08 <= actual_ratio <= 0.22, f"ratio={ratio} actual={actual_ratio}"

    def test_overlap_weak_invariant_every_char_covered(self) -> None:
        """overlap>0 → 弱不变式「原文每字符至少被一块覆盖」."""
        text = "章" * 1200
        chunks = chunk_text(text, chunk_size=500, overlap_ratio=0.15)
        covered = [False] * len(text)
        for c in chunks:
            for i in range(c.start_offset, min(c.start_offset + len(c.text), len(text))):
                covered[i] = True
        assert all(covered), "原文存在未被任何块覆盖的字符"

    def test_overlap_short_text_no_duplicate_chunks(self) -> None:
        """超短文本（< chunk_size）不产生重复块（单块）."""
        text = "短" * 100
        chunks = chunk_text(text, chunk_size=500, overlap_ratio=0.15)
        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].start_offset == 0

    def test_overlap_start_offsets_advance(self) -> None:
        """overlap>0 时 start_offset 递增且首块为 0."""
        text = "章" * 2000
        chunks = chunk_text(text, chunk_size=500, overlap_ratio=0.2)
        assert chunks[0].start_offset == 0
        offsets = [c.start_offset for c in chunks]
        assert offsets == sorted(offsets)
        assert len(set(offsets)) == len(offsets)  # 无重复偏移


class TestChunkProjection:
    """_project_chapter_chunk 块 id 三态 + 元数据补强（§5.6.3/§5.6.4）."""

    def _chunk(self, text: str, offset: int) -> Chunk:
        return Chunk(text=text, start_offset=offset)

    def test_chunk_id_without_overlap_keeps_legacy(self) -> None:
        """overlap=False（默认关）→ 块 id = {chapter_id}:{idx}（现状不变）."""
        entity = _project_chapter_chunk(
            CH1,
            "第一章",
            2,
            self._chunk("块文本", 0),
            PID,
        )
        assert entity.id == f"{CH1}:2"

    def test_chunk_id_with_overlap_includes_start_offset(self) -> None:
        """overlap=True → 块 id = {chapter_id}:{idx}:{start_offset}."""
        entity = _project_chapter_chunk(
            CH1,
            "第一章",
            2,
            self._chunk("块文本", 750),
            PID,
            overlap=True,
        )
        assert entity.id == f"{CH1}:2:750"

    def test_chunk_metadata_includes_position_context(self) -> None:
        """元数据补强: chapter_x/chapter_y/volume_title/chunk_start/indexed_at."""
        entity = _project_chapter_chunk(
            CH1,
            "第一章",
            0,
            self._chunk("块文本", 0),
            PID,
            chapter_x=3,
            chapter_y=10,
            volume_title="第一卷",
            indexed_at="2026-08-16T08:00:00+00:00",
        )
        md = entity.metadata
        assert md["chapter_x"] == 3
        assert md["chapter_y"] == 10
        assert md["volume_title"] == "第一卷"
        assert md["chunk_start"] == 0
        assert md["indexed_at"] == "2026-08-16T08:00:00+00:00"
        # 既有键保留
        assert md["chapter_id"] == str(CH1)
        assert md["chapter_title"] == "第一章"
        assert md["chunk_index"] == 0
        assert md["project_id"] == PID

    def test_chunk_metadata_omits_optional_keys_when_none(self) -> None:
        """可选元数据（x/y/volume_title/indexed_at）None 时省略键（QA §P2-1 fallback）."""
        entity = _project_chapter_chunk(
            CH1,
            "第一章",
            0,
            self._chunk("块文本", 0),
            PID,
        )
        md = entity.metadata
        assert "chapter_x" not in md
        assert "chapter_y" not in md
        assert "volume_title" not in md
        assert "indexed_at" not in md
        # chunk_start 恒有（Chunk.start_offset 始终可得）
        assert md["chunk_start"] == 0


class TestChunkingFingerprintLinkage:
    """指纹联动（§5.6.5）— 复用 #276 纯函数；守护用例 RED 期即 PASS 刻意."""

    def test_chunking_config_change_reports_chunking_changed(self) -> None:
        """切片配置变更（mode/chunk_size/overlap）→ compare_fingerprints 报 chunking_changed."""
        base = build_fingerprint(
            embedding={"provider": "openai", "model_id": "m", "base_url": "http://x"},
            chunking={},
        )
        changed = build_fingerprint(
            embedding={"provider": "openai", "model_id": "m", "base_url": "http://x"},
            chunking={"mode": "paragraph", "chunk_size": 600, "overlap_ratio": 0.15},
        )
        stale, reason = compare_fingerprints(changed, base)
        assert stale is True
        assert reason == "chunking_changed"

    def test_same_chunking_config_not_stale(self) -> None:
        """切片配置一致 → 不 stale（守护：确认比对粒度含 chunking 全字段）."""
        fp = build_fingerprint(
            embedding={"provider": "openai", "model_id": "m", "base_url": "http://x"},
            chunking={"mode": "paragraph", "chunk_size": 600, "overlap_ratio": 0.15},
        )
        stale, reason = compare_fingerprints(fp, fp)
        assert stale is False
        assert reason is None
