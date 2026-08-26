"""F14 分块纯函数测试 — chunk_text 边界、标点回溯切分、空文本.

⚠️ 契约升级（#277 M3，2026-08-16）: chunk_text 返回类型由 list[str] 升级为
list[Chunk]（spec §5.6.1 策略模式）——全部断言改为访问 .text/.start_offset。
RED 期（实现仍返回 str）→ AttributeError: 'str' object has no attribute 'text'。
"""

from __future__ import annotations

import pytest

from inkflow.domain.services._chunking import chunk_text


class TestChunkText:
    def test_empty_text_returns_no_chunks(self) -> None:
        """空文本返回空列表（0 块）."""
        assert chunk_text("") == []

    def test_short_text_is_single_chunk(self) -> None:
        """短文本（< 500 字符）整体为 1 块."""
        text = "短" * 100
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0].text == text

    def test_long_text_split_at_chunk_size_boundary(self) -> None:
        """无标点时按 ~500 字符边界硬切."""
        text = "长" * 1200
        chunks = chunk_text(text)
        assert len(chunks) == 3
        assert [len(c.text) for c in chunks] == [500, 500, 200]
        assert "".join(c.text for c in chunks) == text

    def test_split_backtracks_to_period_boundary(self) -> None:
        """切分优先回溯到句号边界（.。后切分），而非硬切 500."""
        # 第 480 字符处是句号：第一块应在句号后结束（481 字符）
        text = "字" * 480 + "。" + "字" * 800
        chunks = chunk_text(text)
        assert chunks[0].text == "字" * 480 + "。"
        assert chunks[0].text.endswith("。")
        assert len(chunks[0].text) == 481
        assert "".join(c.text for c in chunks) == text

    def test_split_backtracks_to_newline_boundary(self) -> None:
        """切分优先回溯到换行边界."""
        text = "段" * 450 + "\n" + "段" * 600
        chunks = chunk_text(text)
        assert chunks[0].text == "段" * 450 + "\n"
        assert "".join(c.text for c in chunks) == text

    def test_split_backtracks_to_exclamation_or_question(self) -> None:
        """切分优先回溯到 ！/？ 边界."""
        text = "惊" * 460 + "！" + "疑" * 470 + "？" + "续" * 600
        chunks = chunk_text(text)
        assert chunks[0].text == "惊" * 460 + "！"
        assert chunks[1].text == "疑" * 470 + "？"
        assert "".join(c.text for c in chunks) == text

    def test_chunks_non_overlapping_and_full_coverage(self) -> None:
        """块无重叠且拼接后还原原文."""
        text = "章" * 1500
        chunks = chunk_text(text)
        assert "".join(c.text for c in chunks) == text
        assert len(chunks) == 3
        assert all(len(c.text) <= 500 for c in chunks)

    def test_chinese_counted_by_characters_not_bytes(self) -> None:
        """中文按字符计数（len），而非 UTF-8 字节数."""
        # 1001 个中文字符：按字符切分为 500/500/1；按字节（每字 3 字节）会切成更多块
        text = "字" * 1001
        chunks = chunk_text(text)
        assert len(chunks) == 3
        assert [len(c.text) for c in chunks] == [500, 500, 1]

    def test_custom_chunk_size(self) -> None:
        """支持自定义 chunk_size."""
        text = "甲" * 250
        chunks = chunk_text(text, chunk_size=100)
        assert [len(c.text) for c in chunks] == [100, 100, 50]
        assert "".join(c.text for c in chunks) == text

    def test_non_positive_chunk_size_raises(self) -> None:
        """chunk_size <= 0 抛出 ValueError（避免空块/死循环）."""
        with pytest.raises(ValueError):
            chunk_text("内容", chunk_size=0)
        with pytest.raises(ValueError):
            chunk_text("内容", chunk_size=-5)
