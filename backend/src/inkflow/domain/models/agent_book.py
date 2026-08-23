"""F49 自主全自动写作 - book-level agent 编排配置（mode="agentic" 时生效）.

依据: specs/f49-autonomous-writing/spec.md §2.2（AgenticRunConfig DTO）.
领域层保持纯净：仅依赖 Pydantic v2，不感知 LangGraph / 基础设施（ADR-015）.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgenticBookConfig(BaseModel):
    """agentic 模式书级运行配置（book supervisor 护栏 + HITL 白名单 + 章节循环上限）.

    读取优先级：请求显式 config > 默认常量（本模块）。
    """

    # 护栏（复用 F29 supervisor 语义 + F44 上限）
    max_steps: int = Field(
        default=100, ge=1, le=200, description="book supervisor 路由步数上限（振荡护栏）"
    )
    max_consecutive: int = Field(
        default=4, ge=1, le=10, description="同操作连续调度上限（振荡护栏）"
    )
    hitl_points: list[str] = Field(
        default_factory=list,
        description="HITL 确认点白名单：book_start/chapter_done/finish；空=无 HITL（全自动）",
    )
    fallback_on_error: bool = Field(
        default=True,
        description="异常/超限回退确定性链（continue writing remaining chapters）",
    )
    supervisor_prompt: str | None = Field(
        default=None, description="book supervisor 决策 system prompt 覆盖（默认模板）"
    )
    max_chapter_cycles: int = Field(
        default=5, ge=1, le=20, description="章节级 write/audit/revise 循环上限（防无限修订）"
    )
    audit_required: bool = Field(
        default=True, description="每章写后必须至少一次审校；False=agent 可跳审"
    )
