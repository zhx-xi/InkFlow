"""F58 grants 授权模型 — domain × CRUD 授权矩阵基础类型（spec §2.1）.

本模块为纯 Pydantic 领域模型，仅定义 8 个工具域（ToolDomain）、3 个
授权操作（ToolOp）与单域授权条目（GrantEntry）；不感知 ORM / 框架。
域/操作枚举天然拒绝非法字符串：构造 GrantEntry 时非法取值抛
``pydantic.ValidationError``（API 层表现为 422 detail 校验列表）。

依据: specs/f58-agent-tool-scope/spec.md §2.1 + contract-954 §1。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ToolDomain(StrEnum):
    """工具授权域（spec §2.1 逐字，枚举序即声明序）. """

    OUTLINE = "outline"
    CHARACTER = "character"
    WORLD = "world"
    TIMELINE = "timeline"
    FORESHADOWING = "foreshadowing"
    MEMORY = "memory"
    WRITING = "writing"
    AGENT_CHAIN = "agent_chain"


class ToolOp(StrEnum):
    """授权操作（spec §2.1 逐字，枚举序 read < write < delete）. """

    READ = "read"
    WRITE = "write"
    DELETE = "delete"


class GrantEntry(BaseModel):
    """单域授权条目：domain + ops 列表（空列表 = 该域无授权）."""

    domain: ToolDomain
    ops: list[ToolOp] = Field(default_factory=list)
