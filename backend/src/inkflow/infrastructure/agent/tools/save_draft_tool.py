"""F27 save_draft 写工具——agent 唯一写面（草稿落库 + 单事务 + 审计，spec §5.2/ADR-F）.

#718: 移除 SaveDraftParams 的 project_id/chapter_id——LLM 无需也无需自报项目/章节 id
（chat 系统提示词提示「当前项目已绑定，无需用户提供项目 ID」）。项目/章节上下文由
装配期 deps.expected_project_id/expected_chapter_id 绑定（镜像 #680 reader 工具闭包绑定），
工具总是使用绑定值（LLM 无法编造全零 UUID 落孤儿数据）。

与 F26 只读工具同形态（Tool/ToolSpec 复用 reader_tools）:
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
from inkflow.infrastructure.agent.tools import _tool_db_lock as _tool_db_lock_mod
from inkflow.infrastructure.agent.tools.reader_tools import Tool
from inkflow.logging import instrument


class SaveDraftParams(BaseModel):
    """save_draft 工具参数（spec §5.2）.

    #718: 移除 project_id/chapter_id——装配期 deps.expected_* 绑定，LLM 无需/不能自报。
    """

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

    expected_project_id/expected_chapter_id: #718 绑定上下文——每次 run 由装配层注入
    请求真实值；工具总是使用绑定值（LLM 无法编造全零 UUID 落孤儿数据），未注入时
    回退 caller 传入值（MCP/F27 writer 兼容）。
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

    @instrument(caller_type="tool")
    async def _save_draft(
        project_id: uuid.UUID | str | None = None,
        chapter_id: uuid.UUID | str | None = None,
        content: str = "",
        summary: str | None = None,
    ) -> str:
        async with _tool_db_lock_mod._tool_db_lock:
            # #718: 绑定到装配期上下文——deps.expected_* 注入时总是使用绑定值
            # （LLM 无需也无需自报 id，杜绝编造全零/误报导致 {ok:False} 循环失败）；
            # 未注入时回退 caller 传入值（MCP/F27 writer 兼容）。
            bound_project_id = (
                deps.expected_project_id if deps.expected_project_id is not None else project_id
            )
            bound_chapter_id = (
                deps.expected_chapter_id if deps.expected_chapter_id is not None else chapter_id
            )
            try:
                _project_id = (
                    bound_project_id
                    if isinstance(bound_project_id, uuid.UUID)
                    else uuid.UUID(str(bound_project_id))
                )
                _chapter_id = (
                    None
                    if bound_chapter_id is None
                    else (
                        bound_chapter_id
                        if isinstance(bound_chapter_id, uuid.UUID)
                        else uuid.UUID(str(bound_chapter_id))
                    )
                )
                draft = await deps.draft_service.create(  # type: ignore[attr-defined]  # 鸭子类型：draft_service 按契约提供 create
                    project_id=_project_id,
                    chapter_id=_chapter_id,
                    content=content,
                    summary=summary or "",
                    agent_run_id=None,
                )
                # 成功审计（约束③）；审计自身异常静默，不影响主返回
                with contextlib.suppress(Exception):
                    await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        actor="agent:writer",
                        project_id=_project_id,
                        chapter_id=_chapter_id,
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
                        project_id=_project_id,
                        chapter_id=_chapter_id,
                        severity_summary="draft_save_failed",
                        summary=str(exc),
                        degraded=True,
                    )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return Tool(spec=spec, func=_save_draft)
