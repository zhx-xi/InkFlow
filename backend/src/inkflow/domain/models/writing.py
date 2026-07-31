"""F3 写作管道领域模型 — WritingMode、DTOs、WritingResult、FormatValidationResult."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from inkflow.domain.ports.llm_client import TokenUsage


class WritingMode(StrEnum):
    """写作操作模式."""

    GENERATE = "generate"  # 生成章节
    CONTINUE = "continue"  # 续写内容
    REVISE = "revise"  # 修改润色


def _strip_validator(v: str) -> str:
    """去除首尾空白后在 validator 中使用."""
    return v.strip() if isinstance(v, str) else v


class WritingRequest(BaseModel):
    """生成章节请求."""

    project_id: uuid.UUID
    chapter_id: uuid.UUID
    outline: str
    context: str = ""
    min_words: int = Field(default=2000, ge=2000, le=50000)
    max_words: int = Field(default=4000, ge=2000, le=100000)
    style_hint: str | None = Field(default=None, max_length=1000)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)

    @field_validator("outline")
    @classmethod
    def validate_outline(cls, v: str) -> str:
        v = _strip_validator(v)
        if not v:
            raise ValueError("大纲不能为空")
        if len(v) > 5000:
            raise ValueError("大纲不能超过 5000 个字符")
        return v

    @field_validator("context")
    @classmethod
    def validate_context(cls, v: str) -> str:
        if len(v) > 20000:
            raise ValueError("上下文不能超过 20000 个字符")
        return v

    @field_validator("style_hint")
    @classmethod
    def validate_style_hint(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 1000:
            raise ValueError("风格提示不能超过 1000 个字符")
        return v

    @model_validator(mode="after")
    def validate_word_range(self) -> WritingRequest:
        if self.max_words < self.min_words:
            raise ValueError("max_words 不能小于 min_words")
        return self


class ContinueWritingRequest(BaseModel):
    """续写请求."""

    project_id: uuid.UUID
    chapter_id: uuid.UUID
    existing_content: str
    context: str = ""
    target_words: int = Field(default=2000, ge=200, le=50000)
    style_hint: str | None = Field(default=None, max_length=1000)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)

    @field_validator("existing_content")
    @classmethod
    def validate_existing_content(cls, v: str) -> str:
        v = _strip_validator(v)
        if len(v) < 50:
            raise ValueError("已有内容太短，无法续写（至少需要 50 个字符）")
        return v

    @field_validator("context")
    @classmethod
    def validate_context(cls, v: str) -> str:
        if len(v) > 20000:
            raise ValueError("上下文不能超过 20000 个字符")
        return v


class RevisionRequest(BaseModel):
    """修订请求."""

    project_id: uuid.UUID
    chapter_id: uuid.UUID
    content: str
    feedback: str
    target_range: str | None = Field(default=None, max_length=200)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = _strip_validator(v)
        if not v:
            raise ValueError("待修订内容不能为空")
        if len(v) < 10:
            raise ValueError("待修订内容太短（至少需要 10 个字符）")
        return v

    @field_validator("feedback")
    @classmethod
    def validate_feedback(cls, v: str) -> str:
        v = _strip_validator(v)
        if not v:
            raise ValueError("修订意见不能为空")
        if len(v) > 2000:
            raise ValueError("修订意见不能超过 2000 个字符")
        return v


class WritingResult(BaseModel):
    """写作结果."""

    content: str
    word_count: int
    mode: WritingMode
    format_valid: bool
    retry_count: int
    model: str
    token_usage: TokenUsage | None = None
    warnings: list[str] = Field(default_factory=list)


@dataclass
class FormatValidationResult:
    """格式校验内部结果 — 不对外暴露."""

    valid: bool
    errors: list[str] = field(default_factory=list)
