"""写作 REST API — generate / continue / revise 端点.

三个端点均为动作型接口（不创建持久化资源），统一返回 200。
错误映射遵循 ADR-012：领域异常 → 404/422，基础设施异常 → 500（不泄漏细节）。
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from inkflow.api.deps import get_agentic_writer_service, get_writing_service
from inkflow.domain.models.agent_run import AgenticWriteRequest
from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    RevisionRequest,
    StreamWritingRequest,
    WritingRequest,
    WritingStreamEvent,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.services.agentic_writer_service import (
    AgenticWriteNotFoundError,
    AgenticWriterService,
)
from inkflow.domain.services.writing_service import WritingService, _NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/writing", tags=["写作"])

#: 服务层以 LLMRequestError(message) 表达的领域不存在错误（spec §3.3）
_NOT_FOUND_MESSAGES = ("项目不存在", "章节不存在")


def _map_service_error(exc: Exception) -> HTTPException:
    """将服务层异常映射为 HTTP 响应（ADR-012）。

    - 项目/章节不存在 → 404（spec §3.3 异常映射表）
    - LLM 调用失败 → 500 通用消息，记录原始异常，不泄漏内部细节
    - 其他未知异常 → 500 通用消息
    """
    if isinstance(exc, _NotFoundError):
        return HTTPException(status_code=404, detail=exc.args[0] if exc.args else "章节不存在")
    if isinstance(exc, LLMRequestError):
        if exc.args and exc.args[0] in _NOT_FOUND_MESSAGES:
            return HTTPException(status_code=404, detail=exc.args[0])
        logger.exception("LLM 调用失败: %s", exc)
        return HTTPException(
            status_code=500,
            detail="LLM 调用失败，请稍后重试",
            headers={"X-InkFlow-Error-Code": "LLM_ERROR"},
        )
    logger.exception("写作服务未预期异常: %s", exc)
    return HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")


def _map_agentic_service_error(exc: Exception) -> HTTPException:
    """将 agentic 服务层异常映射为 HTTP 响应（ADR-012 镜像）.

    - AgenticWriteNotFoundError（项目/章节不存在）→ 404（detail=异常消息）
    - 其余异常 → 500 + X-InkFlow-Error-Code: LLM_ERROR 头（不泄漏内部细节）
    """
    if isinstance(exc, AgenticWriteNotFoundError):
        return HTTPException(
            status_code=404,
            detail=exc.args[0] if exc.args else "章节不存在",
        )
    logger.exception("Agentic 写作服务未预期异常: %s", exc)
    return HTTPException(
        status_code=500,
        detail="LLM 调用失败，请稍后重试",
        headers={"X-InkFlow-Error-Code": "LLM_ERROR"},
    )


@router.post("/generate")
async def generate_chapter(
    data: WritingRequest,
    svc: WritingService = Depends(get_writing_service),
) -> dict:
    """生成章节 — 从大纲+上下文生成完整章节。"""
    try:
        result = await svc.generate_chapter(data)
    except Exception as exc:
        raise _map_service_error(exc) from exc
    return result.model_dump(mode="json")


@router.post("/continue")
async def continue_writing(
    data: ContinueWritingRequest,
    svc: WritingService = Depends(get_writing_service),
) -> dict:
    """续写内容 — 接续已有内容继续写作。"""
    try:
        result = await svc.continue_writing(data)
    except Exception as exc:
        raise _map_service_error(exc) from exc
    return result.model_dump(mode="json")


@router.post("/revise")
async def revise_content(
    data: RevisionRequest,
    svc: WritingService = Depends(get_writing_service),
) -> dict:
    """修改润色 — 基于反馈修订指定内容。"""
    try:
        result = await svc.revise_content(data)
    except Exception as exc:
        raise _map_service_error(exc) from exc
    return result.model_dump(mode="json")


@router.post("/agentic/generate")
async def agentic_generate(
    data: AgenticWriteRequest,
    svc: AgenticWriterService = Depends(get_agentic_writer_service),
) -> dict:
    """agentic 生成章节（spec §3.1/§3.3）——guardrail 双形态均 200（ADR-D）."""
    try:
        run = await svc.run(data)
    except Exception as exc:
        raise _map_agentic_service_error(exc) from exc
    return {
        "run_id": run.id,
        "status": run.status.value,
        "draft_id": run.draft_id,
        "final_content": run.final_content,
        "word_count": len(run.final_content) if run.final_content else 0,
        "steps": [s.model_dump(mode="json") for s in run.steps],
        "token_usage_total": run.token_usage_total,
        "terminated_by": run.terminated_by,
    }


# ═══════════════════════════════════════════════════════════════════════
# F23 SSE 流式端点（spec §3/§5.2/§6）— 统一端点 + mode 判别联合
# ═══════════════════════════════════════════════════════════════════════


def _encode_sse(ev: WritingStreamEvent) -> str:
    """WritingStreamEvent → SSE 帧字符串（data: <json> + 空行，spec §6.2）."""
    payload: dict = {"done": ev.done}
    if ev.delta:
        payload["delta"] = ev.delta
    if ev.error:
        payload["error"] = ev.error
    if ev.format_valid is not None:
        payload["format_valid"] = ev.format_valid
    if ev.warnings:
        payload["warnings"] = ev.warnings
    if ev.word_count is not None:
        payload["word_count"] = ev.word_count
    if ev.model:
        payload["model"] = ev.model
    if ev.token_usage:
        payload["token_usage"] = dataclasses.asdict(ev.token_usage)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _event_generator(
    request: Request,
    events: AsyncGenerator[WritingStreamEvent, None],
) -> AsyncGenerator[str, None]:
    """包装 service 流 → SSE 帧字符串；客户端断开立即停止（spec §5.3）."""
    try:
        async for ev in events:
            if await request.is_disconnected():
                await events.aclose()  # 客户端断开 → 终止 service 生成器（不泄漏任务）
                return
            yield _encode_sse(ev)  # §6.2 帧编码
    except LLMRequestError:
        # 流中 LLM 失败 → SSE error 帧后流结束（§7 E3）
        yield _encode_sse(WritingStreamEvent(done=True, error="LLM 调用失败，请稍后重试"))


@router.post("/stream")
async def stream_write(
    data: StreamWritingRequest,
    request: Request,
    svc: WritingService = Depends(get_writing_service),
) -> StreamingResponse:
    """流式写作 — SSE 逐 token 推送（mode 判别分发，帧协议见 spec §6）."""
    try:
        if data.mode == "generate":
            events = svc.stream_generate(data)
        elif data.mode == "continue":
            events = svc.stream_continue(data)
        else:
            events = svc.stream_revise(data)
        # 预消费探针（惰性生成器陷阱，spec §3.2）：async generator 函数体在首次迭代
        # 才执行——项目/章节校验异常在此抛出，须映射 HTTP 状态码而非流中 error 帧
        first = await events.__anext__()
    except Exception as exc:
        # 流开始前校验异常（项目/章节不存在等）→ HTTP 状态码（spec §3.2）
        raise _map_service_error(exc) from exc

    async def _prefetched_stream() -> AsyncGenerator[str, None]:
        try:
            # 首事件已被探针消费——先补发其编码帧，再消费余下事件
            yield _encode_sse(first)
            async for ev in _event_generator(request, events):
                yield ev
        finally:
            # 探针已启动 events——客户端在首帧后断开时确保其被关闭（spec §5.3/E4）
            await events.aclose()

    return StreamingResponse(
        _prefetched_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
