"""F27 save_draft 写工具——agent 唯一写面（草稿落库 + 单事务 + 审计，spec §5.2/ADR-F）.

与 F26 只读工具同形态（Tool/ToolSpec 复用 reader_tools）：
- 动态 deps 构建（不进静态 TOOL_REGISTRY）
- 成功: {"ok": True, "draft_id": "<id>", "status": "draft", "word_count": N}
- 失败: {"ok": False, "error": "<异常消息>"}（工具内部捕获一切 Exception 不抛出）
- 约束③：成功/失败均落审计（audit_service.record，actor="agent:writer"）；
  审计调用自身异常静默（不影响主返回）
- word_count 复用 domain/services/_word_count.count_words（纯函数）
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import dataclass

from pydantic import BaseModel

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.services._word_count import count_words
from inkflow.infrastructure.agent.tools.reader_tools import Tool


class SaveDraftParams(BaseModel):
    """save_draft 工具参数（spec §5.2）."""

    project_id: uuid.UUID
    chapter_id: uuid.UUID | None = None  # 目标章节（可选，确认时指定）
    content: str  # 草稿正文（Markdown）
    summary: str | None = None  # 一句话说明（用户确认时展示）


@dataclass
class SaveDraftToolDeps:
    """写工具工厂依赖——service 实例注入（鸭子类型，镜像 ReaderToolDeps）."""

    draft_service: object  # 有 create(*, project_id, chapter_id, content,
    #   summary="", agent_run_id=None) -> Draft
    audit_service: object  # 有 record(**kwargs)（AuditLogService 形态）


def build_save_draft_tool(deps: SaveDraftToolDeps) -> Tool:
    """构建 save_draft 工具（动态 deps，不进静态 TOOL_REGISTRY）.

    Args:
        deps: 工具依赖（draft_service + audit_service 实例）.

    Returns:
        可执行 Tool（spec.name="save_draft"，func 为异步闭包）.
    """
    spec = ToolSpec(
        name="save_draft",
        description=(
            "保存章节草稿（不修改正式章节）。agent 完成正文后必须调用本工具保存草稿；"
            "草稿需用户确认后才生效。返回草稿 id。"
        ),
        input_schema=SaveDraftParams.model_json_schema(),
    )

    async def _save_draft(
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
        content: str = "",
        summary: str | None = None,
    ) -> str:
        try:
            draft = await deps.draft_service.create(  # type: ignore[attr-defined]  # 鸭子类型：draft_service 按契约提供 create
                project_id=project_id,
                chapter_id=chapter_id,
                content=content,
                summary=summary or "",
                agent_run_id=None,
            )
            # 成功审计（约束③）；审计自身异常静默，不影响主返回
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:writer",
                    project_id=project_id,
                    chapter_id=chapter_id,
                    severity_summary="draft_saved",
                    summary=f"草稿保存 {count_words(content)} 字",
                    degraded=True,
                )
            return json.dumps(
                {
                    "ok": True,
                    "draft_id": draft.id,
                    "status": "draft",
                    "word_count": count_words(content),
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            # 失败亦落审计（约束③）；审计自身异常静默
            with contextlib.suppress(Exception):
                await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    actor="agent:writer",
                    project_id=project_id,
                    chapter_id=chapter_id,
                    severity_summary="draft_save_failed",
                    summary=str(exc),
                    degraded=True,
                )
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return Tool(spec=spec, func=_save_draft)
