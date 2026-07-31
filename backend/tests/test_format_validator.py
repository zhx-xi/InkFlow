"""F3 格式校验器测试 — 7条规则 R1-R7."""

from __future__ import annotations

from inkflow.domain.services._format_validator import FormatValidator


class TestFormatValidator:
    def test_valid_markdown_chapter(self) -> None:
        content = (
            "# 第一章 开端\n\n"
            "清晨的阳光洒在青石板上，林尘踏入了试炼场。\n\n"
            "他深吸一口气，感受着周围灵气的流动。"
        )
        result = FormatValidator.validate(content, min_words=30)
        assert result.valid is True
        assert result.errors == []

    def test_fenced_code_block_detected(self) -> None:
        content = "```\n# 第一章\n正文内容\n```"
        result = FormatValidator.validate(content, min_words=5)
        assert result.valid is False
        assert any("R1" in e for e in result.errors)

    def test_json_output_detected(self) -> None:
        content = '{"chapter": "第一章", "content": "正文内容"}'
        result = FormatValidator.validate(content, min_words=5)
        assert result.valid is False
        assert any("R2" in e for e in result.errors)

    def test_placeholder_detected_todo(self) -> None:
        content = "## 开局\n\n主角来到宗门 [TODO] 然后遇到了长老。"
        result = FormatValidator.validate(content, min_words=10)
        assert result.valid is False
        assert any("R4" in e for e in result.errors)

    def test_placeholder_detected_template(self) -> None:
        content = "{{主角名}}走进了房间，看到了{{场景描述}}。"
        result = FormatValidator.validate(content, min_words=5)
        assert result.valid is False
        assert any("R4" in e for e in result.errors)

    def test_duplicate_paragraph_detected(self) -> None:
        para = "这是一个重复的段落。它应该被检测出来。"
        content = "# 标题\n\n" + "\n\n".join([para] * 4)
        result = FormatValidator.validate(content, min_words=5)
        assert result.valid is False
        assert any("R5" in e for e in result.errors)

    def test_truncated_ending_detected(self) -> None:
        content = "# 第一章\n\n林尘站在山门前，望着云雾缭绕的青云宗。他心中感慨万千。\n\n一切仿"
        result = FormatValidator.validate(content, min_words=10)
        assert result.valid is False
        assert any("R6" in e for e in result.errors)

    def test_word_count_below_minimum(self) -> None:
        content = "只有一句话。"
        result = FormatValidator.validate(content, min_words=2000)
        assert result.valid is False
        assert any("R7" in e for e in result.errors)

    def test_word_count_meets_minimum(self) -> None:
        content = "第一章 开端\n\n" + "正文内容足够长。" * 500
        result = FormatValidator.validate(content, min_words=30)
        assert result.valid is True

    def test_multi_error_reporting(self) -> None:
        content = (
            "```json\n"
            + '{"title": "test"}\n'
            + "```\n\n{{变量}}\n\n[TODO]\n\n"
            + "唯一不重复的句子。\n"
        )
        result = FormatValidator.validate(content, min_words=5)
        assert result.valid is False
        assert len(result.errors) >= 2
