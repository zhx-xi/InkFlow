"""F51 写作工具——3 工具（generate / continue / revise），输出统一 JSON 信封.

镜像 #748 setting_write_tools 形态：
- 动态 deps 构建（不进静态 TOOL_REGISTRY）
- 成功: {"ok": True, "chapter_id": "<绑定章 id>", "word_count": N}
- 失败: {"ok": False, "error": "<异常消息>"}（工具内部捕获一切 Exception 不抛出）
- 成功/失败均落审计（audit_service.record，actor="agent:chat"）；审计自身异常静默
- project_id/chapter_id 一律由装配期 deps.expected_* 闭包绑定，schema 不含（LLM 不
  自报 id）；func 保留可选 shim（deepagents 只传 schema 内参数，shim 兜底兼容
  MCP/writer 直接调用）。写作必须有章：expected_chapter_id 未注入时返回失败信封。
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import dataclass

from pydantic import BaseModel

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    RevisionRequest,
    WritingRequest,
)
from inkflow.infrastructure.agent.tools.reader_tools import Tool


def _coerce_uuid(value: object) -> uuid.UUID:
    """规范化 uuid.UUID——deepagents 透传 LLM JSON 原值，参数恒为 str（#275）。"""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


# ─── 参数模型（用于生成 ToolSpec.input_schema；project_id/chapter_id 由装配期绑定） ───


class GenerateParams(BaseModel):
    """generate 工具参数。"""

    outline: str
    context: str = ""
    min_words: int = 2000
    max_words: int = 4000
    style_hint: str | None = None
    temperature: float | None = None


class ContinueParams(BaseModel):
    """continue 工具参数。"""

    existing_content: str
    context: str = ""
    target_words: int = 2000
    style_hint: str | None = None
    temperature: float | None = None


class ReviseParams(BaseModel):
    """revise 工具参数。"""

    content: str
    feedback: str
    target_range: str | None = None
    temperature: float | None = None


# ─── 工具 spec 静态常量（func 动态构建，镜像 setting_write_tools） ───


GENERATE_SPEC = ToolSpec(
    name="generate",
    description="根据章节上下文生成正文（写入章节内容）",
    input_schema=GenerateParams.model_json_schema(),
    group="writing",
)

CONTINUE_SPEC = ToolSpec(
    name="continue",
    description="续写正文",
    input_schema=ContinueParams.model_json_schema(),
    group="writing",
)

REVISE_SPEC = ToolSpec(
    name="revise",
    description="润色/改写正文",
    input_schema=ReviseParams.model_json_schema(),
    group="writing",
)


@dataclass
class WritingToolDeps:
    """写作工具工厂依赖——service 实例注入（鸭子类型，镜像 SaveDraftToolDeps）。

    expected_project_id/expected_chapter_id: #766 绑定上下文——每次 run 由装配层注入
    请求真实值；工具总是使用绑定值（LLM 无法编造全量 UUID 落孤儿数据）。写作必须有章：
    expected_chapter_id 为 None 时 func 直接返回失败信封。
    """

    writing_service: object  # 有 generate_chapter/continue_writing/revise_content
    audit_service: object  # 有 record(**kwargs)（AuditLogService 形态）
    expected_project_id: uuid.UUID | None = None
    expected_chapter_id: uuid.UUID | None = None


def _bind_project_id(expected: uuid.UUID | None, project_id: object) -> uuid.UUID | None:
    """解析绑定项目 id：装配期 expected 优先，未注入回退 caller 传入值."""
    bound = expected if expected is not None else project_id
    if bound is None:
        return None
    return bound if isinstance(bound, uuid.UUID) else _coerce_uuid(bound)


def build_writing_tools(deps: WritingToolDeps) -> list[Tool]:
    """构建写作工具（顺序固定：generate → continue → revise）。

    Args:
        deps: 工具依赖（writing + audit service 实例，绑定项目/章节上下文）。

    Returns:
        三个可执行 Tool；func 成功/失败均返回 JSON 信封且不抛异常。
    """

    async def _generate(
        project_id: uuid.UUID | str | None = None,
        chapter_id: uuid.UUID | str | None = None,
        outline: str = "",
        context: str = "",
        min_words: int = 2000,
        max_words: int = 4000,
        style_hint: str | None = None,
        temperature: float | None = None,
    ) -> str:
        if deps.expected_chapter_id is None:
            return json.dumps(
                {"ok": False, "error": "需要章节上下文"}, ensure_ascii=False
            )
        _project_id = _bind_project_id(deps.expected_project_id, project_id)
        try:
            _chapter_id = (
                deps.expected_chapter_id
                if isinstance(deps.expected_chapter_id, uuid.UUID)
                else _coerce_uuid(deps.expected_chapter_id)
            )
            request = WritingRequest.model_construct(
                project_id=_project_id,
                chapter_id=_chapter_id,
                outline=outline,
                context=context,
                min_words=min_words,
                max_words=max_words,
                style_hint=style_hint,
                temperature=temperature,
            )
            result = await deps.writing_service.generate_chapter(  # type: ignore[attr-defined]  # 鸭子类型：writing_service 按契约提供 generate_chapter
                request=request
            )
            # 成功审计；审计自身异常静默，不影响主返回
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="generate_completed",
                    summary=f"正文生成 {result.word_count} 字",
                    degraded=True,
                )
            return json.dumps(
                {
                    "ok": True,
                    "chapter_id": str(_chapter_id),
                    "word_count": result.word_count,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            # 失败亦落审计；审计自身异常静默
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="generate_failed",
                    summary=f"正文生成失败: {exc}",
                    degraded=True,
                )
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _continue_writing(
        project_id: uuid.UUID | str | None = None,
        chapter_id: uuid.UUID | str | None = None,
        existing_content: str = "",
        context: str = "",
        target_words: int = 2000,
        style_hint: str | None = None,
        temperature: float | None = None,
    ) -> str:
        if deps.expected_chapter_id is None:
            return json.dumps(
                {"ok": False, "error": "需要章节上下文"}, ensure_ascii=False
            )
        _project_id = _bind_project_id(deps.expected_project_id, project_id)
        try:
            _chapter_id = (
                deps.expected_chapter_id
                if isinstance(deps.expected_chapter_id, uuid.UUID)
                else _coerce_uuid(deps.expected_chapter_id)
            )
            request = ContinueWritingRequest.model_construct(
                project_id=_project_id,
                chapter_id=_chapter_id,
                existing_content=existing_content,
                context=context,
                target_words=target_words,
                style_hint=style_hint,
                temperature=temperature,
            )
            result = await deps.writing_service.continue_writing(  # type: ignore[attr-defined]  # 鸭子类型：writing_service 按契约提供 continue_writing
                request=request
            )
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="continue_completed",
                    summary=f"正文续写 {result.word_count} 字",
                    degraded=True,
                )
            return json.dumps(
                {
                    "ok": True,
                    "chapter_id": str(_chapter_id),
                    "word_count": result.word_count,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="continue_failed",
                    summary=f"正文续写失败: {exc}",
                    degraded=True,
                )
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _revise(
        project_id: uuid.UUID | str | None = None,
        chapter_id: uuid.UUID | str | None = None,
        content: str = "",
        feedback: str = "",
        target_range: str | None = None,
        temperature: float | None = None,
    ) -> str:
        if deps.expected_chapter_id is None:
            return json.dumps(
                {"ok": False, "error": "需要章节上下文"}, ensure_ascii=False
            )
        _project_id = _bind_project_id(deps.expected_project_id, project_id)
        try:
            _chapter_id = (
                deps.expected_chapter_id
                if isinstance(deps.expected_chapter_id, uuid.UUID)
                else _coerce_uuid(deps.expected_chapter_id)
            )
            request = RevisionRequest.model_construct(
                project_id=_project_id,
                chapter_id=_chapter_id,
                content=content,
                feedback=feedback,
                target_range=target_range,
                temperature=temperature,
            )
            result = await deps.writing_service.revise_content(  # type: ignore[attr-defined]  # 鸭子类型：writing_service 按契约提供 revise_content
                request=request
            )
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="revise_completed",
                    summary=f"正文修订 {result.word_count} 字",
                    degraded=True,
                )
            return json.dumps(
                {
                    "ok": True,
                    "chapter_id": str(_chapter_id),
                    "word_count": result.word_count,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:chat",
                    project_id=_project_id,
                    severity_summary="revise_failed",
                    summary=f"正文修订失败: {exc}",
                    degraded=True,
                )
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return [
        Tool(spec=GENERATE_SPEC, func=_generate),
        Tool(spec=CONTINUE_SPEC, func=_continue_writing),
        Tool(spec=REVISE_SPEC, func=_revise),
    ]
