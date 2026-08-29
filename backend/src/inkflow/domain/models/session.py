"""会话管理领域模型 — 会话主实体与履历日志子实体.

Session 是持久化实体（对应 sessions 表，通过 SQLAlchemy ORM 映射），
SessionLogEntry 是会话日志条目（对应 session_logs 表，容器语义：随会话
归档保留、随会话真实删除级联）。SessionCreate / SessionUpdate /
SessionLogCreate / SessionComplete / SessionFail 是请求 DTO；
SessionView 是会话 + 履历摘要视图（详情/列表项）。

依据: specs/f24-session/spec.md §2.1/§2.2/§2.6。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SessionType(StrEnum):
    """会话类型."""

    WRITING = "writing"  # 写作会话（上下文快照供 F3 恢复续写）
    TASK = "task"  # 任务会话（daemon/agent 任务履历）


class SessionStatus(StrEnum):
    """会话状态（§2.4 状态机）."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class LogLevel(StrEnum):
    """日志级别."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


def _validate_title(v: str) -> str:
    """共享的标题校验：去空白后非空且不超过 100 字符."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("会话标题不能为空")
    if len(stripped) > 100:
        raise ValueError("会话标题不能超过 100 个字符")
    return stripped


def _validate_description(v: str) -> str:
    """共享的描述校验：不超过 5000 字符."""
    if len(v) > 5000:
        raise ValueError("会话描述不能超过 5000 个字符")
    return v


def _validate_message(v: str) -> str:
    """日志消息校验：去空白后非空且不超过 2000 字符."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("日志消息不能为空")
    if len(stripped) > 2000:
        raise ValueError("日志消息不能超过 2000 个字符")
    return stripped


class Session(BaseModel):
    """会话领域实体. 对应 sessions 表."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    session_type: SessionType
    status: SessionStatus = SessionStatus.ACTIVE
    project_id: uuid.UUID | None = None
    title: str
    description: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    started_at: datetime
    paused_at: datetime | None = None
    completed_at: datetime | None = None
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class SessionCreate(BaseModel):
    """创建会话请求 DTO."""

    session_type: SessionType
    project_id: uuid.UUID | None = None
    title: str
    description: str = ""
    context: dict[str, Any] = Field(default_factory=dict)

    _title = field_validator("title")(_validate_title)
    _description = field_validator("description")(_validate_description)


class SessionUpdate(BaseModel):
    """更新会话请求 DTO（不承载 status——状态机走动作端点，同 F13）."""

    title: str | None = None
    description: str | None = None
    context: dict[str, Any] | None = None

    @field_validator("title")
    @classmethod
    def _validate_title_opt(cls, v: str | None) -> str | None:
        return _validate_title(v) if v is not None else None

    @field_validator("description")
    @classmethod
    def _validate_description_opt(cls, v: str | None) -> str | None:
        return _validate_description(v) if v is not None else None


class SessionLogEntry(BaseModel):
    """会话日志条目领域实体. 对应 session_logs 表."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    session_id: uuid.UUID
    seq: int
    level: LogLevel = LogLevel.INFO
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SessionLogCreate(BaseModel):
    """追加日志请求 DTO."""

    level: LogLevel = LogLevel.INFO
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)

    _message = field_validator("message")(_validate_message)


class SessionComplete(BaseModel):
    """完成会话请求 DTO（active/paused → completed）."""

    result: dict[str, Any] = Field(default_factory=dict)


class SessionFail(BaseModel):
    """失败会话请求 DTO（active/paused → failed）."""

    error: str

    @field_validator("error")
    @classmethod
    def _validate_error(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("失败原因不能为空")
        if len(stripped) > 2000:
            raise ValueError("失败原因不能超过 2000 个字符")
        return stripped


class SessionView(BaseModel):
    """会话 + 履历摘要视图（详情/列表项）."""

    model_config = {"from_attributes": True}

    session: Session
    log_count: int
    last_log: SessionLogEntry | None = None
