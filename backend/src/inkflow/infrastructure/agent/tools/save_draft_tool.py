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


SAVE_DRAFT_SPEC = ToolSpec(
    name="save_draft",
    description=(
        "保存章节草稿（不修改正式章节）。agent 完成正文后必须调用本工具保存草稿；"
        "草稿需用户确认后才生效。返回草稿 id。"
    ),
    input_schema=SaveDraftParams.model_json_schema(),
    group="writing",
)
"""save_draft 静态 spec 常量（spec §5.1：静态化入 TOOL_REGISTRY；func 仍动态构建）."""


@dataclass
class SaveDraftToolDeps:
    """写工具工厂依赖——service 实例注入（鸭子类型，镜像 ReaderToolDeps）.

    expected_project_id/expected_chapter_id: #275 期望上下文——每次 run 由
    装配层注入请求真实值；工具参数与期望不符 → 拒绝（防 LLM 编造全零 UUID
    落孤儿数据）。
    """

    draft_service: object  # 有 create(*, project_id, chapter_id, content,
    #   summary="", agent_run_id=None) -> Draft
    audit_service: object  # 有 record(**kwargs)（AuditLogService 形态）
    expected_project_id: uuid.UUID | None = None
    expected_chapter_id: uuid.UUID | None = None


def build_save_draft_tool(deps: SaveDraftToolDeps) -> Tool:
    """构建 save_draft 工具（动态 deps，不进静态 TOOL_REGISTRY）.

    Args:
        deps: 工具依赖（draft_service + audit_service 实例）.

    Returns:
        可执行 Tool（spec.name="save_draft"，func 为异步闭包）.
    """
    spec = SAVE_DRAFT_SPEC  # 复用静态常量（与 TOOL_REGISTRY 同源，行为不变）

    async def _save_draft(
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
        content: str = "",
        summary: str | None = None,
    ) -> str:
        project_id = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(str(project_id))
        chapter_id = (
            None
            if chapter_id is None
            else (chapter_id if isinstance(chapter_id, uuid.UUID) else uuid.UUID(str(chapter_id)))
        )

        def _validate_context() -> None:
            """#275 工具上下文校验——参数与期望不符直接抛 ValueError.

            统一 except 路径生成错误信封（约束③失败审计自动覆盖）。
            """
            if deps.expected_project_id is not None and project_id != deps.expected_project_id:
                raise ValueError(
                    f"project_id 与当前项目上下文不符（期望 {deps.expected_project_id}，"
                    f"收到 {project_id}）"
                )
            if (
                deps.expected_chapter_id is not None
                and chapter_id is not None
                and chapter_id != deps.expected_chapter_id
            ):
                raise ValueError(
                    f"chapter_id 与当前章节上下文不符（期望 {deps.expected_chapter_id}，"
                    f"收到 {chapter_id}）"
                )

        try:
            _validate_context()
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
