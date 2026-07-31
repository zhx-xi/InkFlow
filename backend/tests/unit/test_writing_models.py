"""F3 写作模型测试 — DTO 验证规则、枚举值、默认值."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    FormatValidationResult,
    RevisionRequest,
    WritingMode,
    WritingRequest,
    WritingResult,
)


class TestWritingModeEnum:
    def test_writing_mode_values(self) -> None:
        assert WritingMode.GENERATE == "generate"
        assert WritingMode.CONTINUE == "continue"
        assert WritingMode.REVISE == "revise"

    def test_writing_mode_from_string(self) -> None:
        assert WritingMode("generate") == WritingMode.GENERATE
        assert WritingMode("continue") == WritingMode.CONTINUE
        assert WritingMode("revise") == WritingMode.REVISE


class TestWritingRequest:
    def test_defaults(self) -> None:
        req = WritingRequest(
            project_id=uuid.uuid4(),
            chapter_id=uuid.uuid4(),
            outline="章节大纲内容",
        )
        assert req.min_words == 2000
        assert req.max_words == 4000
        assert req.context == ""
        assert req.style_hint is None
        assert req.model is None
        assert req.temperature is None

    def test_empty_outline_raises(self) -> None:
        with pytest.raises(ValidationError, match="大纲不能为空"):
            WritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                outline="",
            )

    def test_whitespace_outline_raises(self) -> None:
        with pytest.raises(ValidationError, match="大纲不能为空"):
            WritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                outline="   ",
            )

    def test_outline_too_long_raises(self) -> None:
        with pytest.raises(ValidationError, match="大纲不能超过 5000 个字符"):
            WritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                outline="x" * 5001,
            )

    def test_min_words_below_2000_raises(self) -> None:
        with pytest.raises(ValidationError):
            WritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                outline="test",
                min_words=1000,
            )

    def test_min_words_above_50000_raises(self) -> None:
        with pytest.raises(ValidationError):
            WritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                outline="test",
                min_words=50001,
            )

    def test_max_words_less_than_min_words_raises(self) -> None:
        with pytest.raises(ValidationError):
            WritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                outline="test",
                min_words=3000,
                max_words=2000,
            )

    def test_context_too_long_raises(self) -> None:
        with pytest.raises(ValidationError, match="上下文不能超过 20000 个字符"):
            WritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                outline="test",
                context="x" * 20001,
            )

    def test_style_hint_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            WritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                outline="test",
                style_hint="x" * 1001,
            )

    def test_temperature_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            WritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                outline="test",
                temperature=3.0,
            )


class TestContinueWritingRequest:
    def test_short_existing_content_raises(self) -> None:
        with pytest.raises(ValidationError, match="已有内容太短"):
            ContinueWritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                existing_content="ab",
            )

    def test_default_target_words(self) -> None:
        req = ContinueWritingRequest(
            project_id=uuid.uuid4(),
            chapter_id=uuid.uuid4(),
            existing_content="这是已有内容，至少需要五十个字符。" * 3,
        )
        assert req.target_words == 2000

    def test_target_words_below_200_raises(self) -> None:
        with pytest.raises(ValidationError):
            ContinueWritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                existing_content="这是已有内容，至少需要五十个字符。" * 3,
                target_words=100,
            )


class TestRevisionRequest:
    def test_empty_feedback_raises(self) -> None:
        with pytest.raises(ValidationError, match="修订意见不能为空"):
            RevisionRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                content="待修订内容",
                feedback="",
            )

    def test_whitespace_feedback_raises(self) -> None:
        with pytest.raises(ValidationError, match="修订意见不能为空"):
            RevisionRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                content="待修订内容",
                feedback="   ",
            )

    def test_feedback_too_long_raises(self) -> None:
        with pytest.raises(ValidationError, match="修订意见不能超过 2000 个字符"):
            RevisionRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                content="待修订内容",
                feedback="x" * 2001,
            )

    def test_empty_content_raises(self) -> None:
        with pytest.raises(ValidationError, match="待修订内容不能为空"):
            RevisionRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                content="",
                feedback="修改意见",
            )

    def test_content_too_short_raises(self) -> None:
        with pytest.raises(ValidationError, match="待修订内容太短"):
            RevisionRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                content="ab",
                feedback="修改意见",
            )

    def test_target_range_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            RevisionRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                content="足够长的待修订内容用于测试",
                feedback="修改意见",
                target_range="x" * 201,
            )


class TestWritingResult:
    def test_all_fields(self) -> None:
        result = WritingResult(
            content="# 章节标题\n\n正文内容……",
            word_count=2347,
            mode=WritingMode.GENERATE,
            format_valid=True,
            retry_count=1,
            model="deepseek/deepseek-chat",
            warnings=[],
        )
        assert result.content == "# 章节标题\n\n正文内容……"
        assert result.word_count == 2347
        assert result.mode == WritingMode.GENERATE
        assert result.format_valid is True
        assert result.retry_count == 1
        assert result.model == "deepseek/deepseek-chat"
        assert result.token_usage is None
        assert result.warnings == []

    def test_with_warnings(self) -> None:
        result = WritingResult(
            content="正文",
            word_count=500,
            mode=WritingMode.GENERATE,
            format_valid=False,
            retry_count=3,
            model="openai/gpt-4o",
            warnings=["字数不足: 500/2000"],
        )
        assert result.format_valid is False
        assert len(result.warnings) == 1


class TestFormatValidationResult:
    def test_valid(self) -> None:
        r = FormatValidationResult(valid=True, errors=[])
        assert r.valid is True
        assert r.errors == []

    def test_invalid_with_errors(self) -> None:
        r = FormatValidationResult(valid=False, errors=["R1: 代码块包裹", "R4: 占位符残留"])
        assert r.valid is False
        assert len(r.errors) == 2
        assert "R1" in r.errors[0]
