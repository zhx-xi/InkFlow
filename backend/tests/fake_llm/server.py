"""fake LLM 服务器（S0，ADR-047）：脚本化正确/错误/超时响应 + SSE 流 + 错误计数。"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncGenerator, Iterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .routing import select_fixture


def create_app() -> FastAPI:
    app = FastAPI()
    # 错误计数（供重试/退避测试）+ 收到的 prompt（供脱敏黑盒断言无 key）
    app.state.error_counts: dict[str, int] = {}
    app.state.received_prompts: list[list[dict]] = []

    @app.post("/v1/chat/completions", response_model=None)
    async def chat_completions(request: Request) -> StreamingResponse | JSONResponse:
        payload = await request.json()
        app.state.received_prompts.append(payload.get("messages", []))
        model = payload.get("model", "")
        stream = bool(payload.get("stream", False))
        fixture = select_fixture(model, payload)

        # 场景名（错误计数 key）：签名覆盖时取签名 scene，否则取 model 后缀
        scenario = _resolve_scenario(model, payload)

        if fixture.kind in ("error", "timeout", "malformed"):
            app.state.error_counts[scenario] = app.state.error_counts.get(scenario, 0) + 1

        if fixture.kind == "timeout" and fixture.delay_seconds > 0:
            await asyncio.sleep(fixture.delay_seconds)

        if fixture.kind == "error":
            error_code = fixture.error_code or "unknown"
            error_message = fixture.error_message or "fake error"
            if not stream:
                return JSONResponse(
                    status_code=fixture.status_code,
                    content={
                        "error": {"code": error_code, "message": error_message, "type": "fake"}
                    },
                )

            def _err_stream() -> Iterator[str]:
                err_frame = {"error": {"code": error_code, "message": error_message}}
                yield f"data: {json.dumps(err_frame)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(_err_stream(), media_type="text/event-stream")

        # correct / empty：非流式 JSON ChatResponse
        if not stream:
            return JSONResponse(
                status_code=200,
                content={
                    "id": "chatcmpl-fake",
                    "object": "chat.completion",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": fixture.content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                },
            )

        # 流式：SSE delta 帧 + data: [DONE]
        async def _sse_stream() -> AsyncGenerator[str, None]:
            content = fixture.content or "ok"
            for ch in content[:4]:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "id": "chatcmpl-fake",
                            "object": "chat.completion.chunk",
                            "model": model,
                            "choices": [
                                {"index": 0, "delta": {"content": ch}, "finish_reason": None}
                            ],
                        }
                    )
                    + "\n\n"
                )
            yield "data: [DONE]\n\n"

        return StreamingResponse(_sse_stream(), media_type="text/event-stream")

    return app


def _resolve_scenario(model: str, payload: dict) -> str:
    """错误计数 key：签名 `[[fake-scenario:<scene>]]` 优先，否则取 model 的 '/' 后后缀。
    例：model="fake/error-429" → "error-429"；签名 "[[fake-scenario:error-500]]" → "error-500"。"""
    pattern = re.compile(r"\[\[fake-scenario:([\w-]+)\]\]")
    for msg in payload.get("messages", []):
        if not isinstance(msg, dict):
            continue
        match = pattern.search(str(msg.get("content", "")))
        if match:
            return match.group(1)
    return model.rsplit("/", 1)[-1] if "/" in model else model


app = create_app()
