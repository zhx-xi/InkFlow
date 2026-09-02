"""fake LLM 服务器（S0，ADR-047）：脚本化正确/错误/超时响应 + SSE 流 + 错误计数。

S3f-T3 §1.2 扩展：POST /v1/embeddings（OpenAI 兼容形状 / 确定性向量 / 请求记录）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncGenerator, Iterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .routing import select_fixture


def create_app(dim: int = 8) -> FastAPI:
    app = FastAPI()
    # 错误计数（供重试/退避测试）+ 收到的 prompt（供脱敏黑盒断言无 key）
    app.state.error_counts: dict[str, int] = {}
    app.state.received_prompts: list[list[dict]] = []
    # S3f-T3：embedding 维度（create_app 参数，缺省 8）+ 请求记录（供断言收到请求）
    app.state.embedding_dim = dim
    app.state.embedding_requests: list[dict] = []

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

    @app.post("/v1/embeddings", response_model=None)
    async def create_embeddings(request: Request) -> JSONResponse:
        """POST /v1/embeddings（S3f-T3 §1.2）：确定性向量 + 请求记录（OpenAI 形状）。

        input 合法形态（OpenAI 全三形态）：str | list[int]（单条 tokens）| 列表且元素为
        str 或 list[int]（批量，可混合）；归一化为条目列表：str 原样、tokens canonical
        化为 str(list) 参与哈希派生（同 tokens 恒等同向量）；[] → 200 data=[]（空批量）。
        非法（dict/None/嵌套非法/混合非法元素）→ 400 {"error": {"message": ...}}。
        """
        payload = await request.json()
        model = payload.get("model", "")
        raw_input = payload.get("input")
        inputs = _normalize_embedding_inputs(raw_input)
        if inputs is None:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "message": "input 缺失或类型非法（须为 str | list[int] | 混合批量）"
                    }
                },
            )
        dim = app.state.embedding_dim
        app.state.embedding_requests.append({"model": model, "input": inputs})
        data = [
            {
                "object": "embedding",
                "embedding": _embedding_vector(model, text, dim),
                "index": i,
            }
            for i, text in enumerate(inputs)
        ]
        return JSONResponse(
            status_code=200,
            content={"object": "list", "data": data, "model": model},
        )

    return app


def _embedding_vector(model: str, text: str, dim: int) -> list[float]:
    """确定性 embedding：sha256(model + "\\n" + text) 的 32 字节循环取模，float ∈ [0, 1]。"""
    digest = hashlib.sha256(f"{model}\n{text}".encode()).digest()
    return [digest[k % 32] / 255.0 for k in range(dim)]


def _is_token_list(value: Any) -> bool:
    """token 序列判定：list 且元素全为 int（[] 真空，空批量语义由调用方裁定）。"""
    return isinstance(value, list) and all(isinstance(token, int) for token in value)


def _normalize_embedding_inputs(raw_input: Any) -> list[str] | None:
    """input 归一化（OpenAI 全三形态）：str → [str]；list[int]（单条 tokens）→ [str(list)]；
    列表（str 或 list[int] 条目，可混合）→ 条目列表：str 原样、tokens canonical 化为 str(list)
    （同 tokens 恒等同向量、异 tokens 异向量）；[] → []（空批量合法）；
    其余（dict/None/嵌套非法/混合非法元素）→ None（调用方回 400）。"""
    if isinstance(raw_input, str):
        return [raw_input]
    if not isinstance(raw_input, list):
        return None
    if not raw_input:
        return []
    if _is_token_list(raw_input):
        return [str(raw_input)]
    entries: list[str] = []
    for item in raw_input:
        if isinstance(item, str):
            entries.append(item)
        elif _is_token_list(item):
            entries.append(str(item))
        else:
            return None
    return entries


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
