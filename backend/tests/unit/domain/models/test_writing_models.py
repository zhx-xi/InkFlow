"""F3 写作模型测试 — DTO 验证规则、枚举值、默认值."""

from __future__ import annotations

import uuid

import pytest
from pydantic import TypeAdapter, ValidationError

from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    FormatValidationResult,
    RevisionRequest,
    StreamContinueRequest,
    StreamGenerateRequest,
    StreamReviseRequest,
    StreamWritingRequest,
    WritingMode,
    WritingRequest,
    WritingResult,
    WritingStreamEvent,
)
from inkflow.domain.ports.llm_client import TokenUsage


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

    def test_context_too_long_raises(self) -> None:
        """context 超长 → ValueError（#273 覆盖率补测：L95-97 分支）。"""
        with pytest.raises(ValidationError, match="上下文不能超过 20000 个字符"):
            ContinueWritingRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                existing_content="已有内容" * 20,
                context="x" * 20001,
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


# ── F23 SSE 流式（spec §2/§9 M1；RED 阶段预期：顶部 import 收集期 ImportError）──


class TestWritingStreamEvent:
    """F23 §2.1 WritingStreamEvent — 流式事件 dataclass 默认值与帧构造.

    设计假设（F16 契约，实现以测试为准）:
    - 定义位置: inkflow.domain.models.writing（新增；dataclass 而非 Pydantic，
      与 F5 StreamEvent 一致——事件是内部传输载体不进 OpenAPI，spec §2.1 注）
    - 接口签名: WritingStreamEvent(
          delta: str = "",
          done: bool = False,
          format_valid: bool | None = None,
          warnings: list[str] = field(default_factory=list),
          word_count: int | None = None,
          model: str | None = None,
          token_usage: TokenUsage | None = None,
          error: str | None = None,
      )
    - warnings 必须 default_factory=list（实例间不共享，防可变默认值串扰）
    - done 帧: done=True + 结果字段（format_valid/warnings/word_count/model/token_usage）
    - error 帧: error 非空 + done=True，结果字段保持 None（spec §7 E3 帧后流结束）
    """

    def test_defaults(self) -> None:
        ev = WritingStreamEvent()
        assert ev.delta == ""
        assert ev.done is False
        assert ev.format_valid is None
        assert ev.warnings == []
        assert ev.word_count is None
        assert ev.model is None
        assert ev.token_usage is None
        assert ev.error is None

    def test_warnings_default_not_shared_between_instances(self) -> None:
        ev1 = WritingStreamEvent()
        ev2 = WritingStreamEvent()
        ev1.warnings.append("字数不足: 500/2000")
        assert ev2.warnings == []

    def test_done_frame_fields(self) -> None:
        usage = TokenUsage(prompt_tokens=1820, completion_tokens=2600, total_tokens=4420)
        ev = WritingStreamEvent(
            done=True,
            format_valid=True,
            warnings=["字数不足: 500/2000"],
            word_count=2347,
            model="deepseek/deepseek-chat",
            token_usage=usage,
        )
        assert ev.done is True
        assert ev.format_valid is True
        assert ev.warnings == ["字数不足: 500/2000"]
        assert ev.word_count == 2347
        assert ev.model == "deepseek/deepseek-chat"
        assert ev.token_usage == usage

    def test_error_frame_fields(self) -> None:
        ev = WritingStreamEvent(done=True, error="LLM 调用失败，请稍后重试")
        assert ev.done is True
        assert ev.error == "LLM 调用失败，请稍后重试"
        assert ev.format_valid is None
        assert ev.word_count is None


class TestStreamWritingRequest:
    """F23 §2.2 StreamWritingRequest 判别联合（Q1=C）— mode 分发/校验继承/序列化.

    设计假设（F16 契约，实现以测试为准）:
    - 定义位置: inkflow.domain.models.writing（三个包装模型继承 F3 DTO，既有模型零变更）
    - StreamGenerateRequest(WritingRequest): mode: Literal["generate"] = "generate"
    - StreamContinueRequest(ContinueWritingRequest): mode: Literal["continue"] = "continue"
    - StreamReviseRequest(RevisionRequest): mode: Literal["revise"] = "revise"
    - StreamWritingRequest = Annotated[Union[StreamGenerateRequest, StreamContinueRequest,
      StreamReviseRequest], Field(discriminator="mode")]
    - 判别解析: pydantic.TypeAdapter(StreamWritingRequest).validate_python(payload) → 正确分支实例
    - mode 缺失/非法 → pydantic.ValidationError（FastAPI 422 语义，判别字段必填，spec §3.2 E2）
    - 字段校验全继承 F3（精确文案）: outline 空 → "大纲不能为空"；existing_content < 50 字符 →
      "已有内容太短，无法续写（至少需要 50 个字符）"；feedback 空 → "修订意见不能为空"
    - 序列化: model_dump(mode="json") 含 mode 判别字段；直接构造（不带 mode）默认值为分支字面量
    """

    _adapter = TypeAdapter(StreamWritingRequest)

    def _payload(self, **overrides: str) -> dict[str, str]:
        base = {
            "project_id": str(uuid.uuid4()),
            "chapter_id": str(uuid.uuid4()),
        }
        base.update(overrides)
        return base

    def test_parse_generate_branch(self) -> None:
        req = self._adapter.validate_python(
            self._payload(mode="generate", outline="主角首次踏入宗门试炼场")
        )
        assert isinstance(req, StreamGenerateRequest)
        assert req.mode == "generate"
        assert req.outline == "主角首次踏入宗门试炼场"

    def test_parse_continue_branch(self) -> None:
        req = self._adapter.validate_python(
            self._payload(
                mode="continue",
                existing_content="这是已有内容，至少需要五十个字符。" * 3,
            )
        )
        assert isinstance(req, StreamContinueRequest)
        assert req.mode == "continue"

    def test_parse_revise_branch(self) -> None:
        req = self._adapter.validate_python(
            self._payload(
                mode="revise",
                content="待修订原文内容。" * 2,
                feedback="节奏太慢，删减环境描写",
            )
        )
        assert isinstance(req, StreamReviseRequest)
        assert req.mode == "revise"

    def test_missing_mode_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._adapter.validate_python(self._payload(outline="test"))

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._adapter.validate_python(self._payload(mode="translate", outline="test"))

    def test_generate_inherits_outline_validation(self) -> None:
        with pytest.raises(ValidationError, match="大纲不能为空"):
            StreamGenerateRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                outline="",
            )

    def test_continue_inherits_existing_content_validation(self) -> None:
        with pytest.raises(ValidationError, match="已有内容太短"):
            StreamContinueRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                existing_content="ab",
            )

    def test_revise_inherits_feedback_validation(self) -> None:
        with pytest.raises(ValidationError, match="修订意见不能为空"):
            StreamReviseRequest(
                project_id=uuid.uuid4(),
                chapter_id=uuid.uuid4(),
                content="待修订内容",
                feedback="",
            )

    def test_serialize_contains_mode(self) -> None:
        pid = uuid.uuid4()
        req = StreamGenerateRequest(
            project_id=pid,
            chapter_id=uuid.uuid4(),
            outline="test",
        )
        assert req.mode == "generate"  # 默认值 = 分支字面量
        dumped = req.model_dump(mode="json")
        assert dumped["mode"] == "generate"
        assert dumped["project_id"] == str(pid)
        assert dumped["min_words"] == 2000  # 继承 F3 默认值
