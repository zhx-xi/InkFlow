"""#541 chat 流式 SSE 端点契约测试（Issue #541：AI 对话流式输出）。

镜像 tests/api/test_writing_api.py 的 F23 SSE 契约先例：httpx_sse aconnect_sse +
dependency_overrides 注入 mock ChatService；帧协议与 writing.py _encode_sse 同款
（`data: {json}\n\n`）。

RED 阶段（本文件首次提交）：inkflow.api.routers.chat_stream 模块不存在——注入同路径
sys.modules stub（backend-red-contract-tests 规则 1e 逃生门，见
references/missing-module-stub-patch.md），使 fixture 内 get_chat_service 导入可解析
→ 全部用例跑到端点 → 「路由未注册 → 404」纯断言失败（逐用例粒度）。
GREEN 阶段 app 导入链已把真模块注册进 sys.modules，setdefault 不覆盖真模块 →
同一文件零改动转绿。

GREEN 实现契约（Codex 按此实现）：
1. 新 router backend/src/inkflow/api/routers/chat_stream.py：
   router = APIRouter(prefix="/api/v1/chat", tags=["AI 对话"])，POST /stream；
   app.py 模块顶层静态导入并 include_router（镜像 writing 等既有 router——保证
   app import 时真模块注册进 sys.modules，本文件的 stub 逃生门依赖此序）。
2. 请求体 ChatStreamRequest：project_id: UUID、prompt: str | None（须可缺省，
   否则 Pydantic 422 detail 是 list 而非自定义文案）、chapter_id?: UUID、
   chapter_context?: str。
3. prompt 缺失或 trim 后为空 → HTTPException(422, "chat 流式请求需要 prompt")
   （镜像 agent.py builtin:chat 校验语义，文案不同）。
4. 依赖注入点 get_chat_service 在 chat_stream 模块内定义；handler 经
   Depends(get_chat_service) 取 ChatService 实例。
5. service 调用签名：svc.stream(prompt: str, chapter_context: str | None = None)
   （async generator 调用，不 await）。
6. 帧协议镜像 writing.py _encode_sse：delta 帧仅 {"delta": str, "done": false} 两键；
   终帧仅 {"done": true}；流中 LLMRequestError → SSE error 终帧
   {"done": true, "error": "LLM 调用失败，请稍后重试"}（HTTP 仍 200）。
7. StreamingResponse media_type="text/event-stream"。
"""

from __future__ import annotations

import json
import sys
import uuid
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from httpx_sse import aconnect_sse

from inkflow.api.app import app  # 必须先于 stub 行导入（GREEN 时 app 导入链注册真模块）
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.services.chat_service import ChatService

# RED 阶段 inkflow.api.routers.chat_stream 模块不存在——注入同路径 stub 模块，
# 使 fixture 内 get_chat_service 导入可解析（规则 1e 逃生门）→ 用例跑到端点呈现 404。
# GREEN 阶段该模块已被 app 导入链注册进 sys.modules，setdefault 不覆盖真模块。
_stub_chat_stream = ModuleType("inkflow.api.routers.chat_stream")
_stub_chat_stream.get_chat_service = MagicMock()
sys.modules.setdefault("inkflow.api.routers.chat_stream", _stub_chat_stream)

PROMPT = "你好，请介绍一下你自己"


def _ev(delta: str = "", done: bool = False, error: str | None = None) -> SimpleNamespace:
    """构造 ChatStreamEvent 形状的事件对象。

    RED 期 chat_service 模块不存在——SimpleNamespace 鸭子替代；GREEN 期 router 仅
    访问 .delta/.done/.error 属性，两者兼容。
    """
    return SimpleNamespace(delta=delta, done=done, error=error)


def _stream_stub(*events):
    """service.stream() mock 工厂 — 返回预置事件序列的 async generator。

    签名锁定 GREEN 契约：`svc.stream(prompt=..., chapter_context=...)`。
    """

    async def _gen(prompt: str, chapter_context: str | None = None):
        for ev in events:
            yield ev

    return _gen


@pytest.fixture
def mock_chat_service() -> MagicMock:
    """Mock ChatService — stream() 默认产出 2 delta + done 帧序列。

    #541 GREEN 收尾（Codex 上报）：stream 用 MagicMock(side_effect=...) 包一层，
    既返回 async generator 又保留调用记录（普通函数赋值会丢 assert_called_once_with）。
    """
    svc = MagicMock()
    svc.stream = MagicMock(
        side_effect=_stream_stub(
            _ev(delta="你"),
            _ev(delta="好"),
            _ev(done=True),
        )
    )
    return svc


@pytest.fixture
def override_chat_service(mock_chat_service):
    """将 router 模块内定义的 get_chat_service 依赖替换为 mock（新 DI 点）。"""
    from inkflow.api.routers.chat_stream import get_chat_service

    app.dependency_overrides[get_chat_service] = lambda: mock_chat_service
    yield mock_chat_service
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    """SSE 测试客户端 — 长超时（30s）防流式慢挂（镜像 test_writing_api.py）。"""
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=httpx.Timeout(30.0),
    )


def _payload(prompt: str = PROMPT) -> dict:
    return {"project_id": str(uuid.uuid4()), "prompt": prompt}


# ── 成功路径 ────────────────────────────────────────────────────


class TestChatStreamSuccess:
    """POST /api/v1/chat/stream — 200 + SSE 帧序列（帧协议镜像 writing.py）。"""

    @pytest.mark.asyncio
    async def test_stream_deltas_and_done_frame(self, override_chat_service):
        """2 delta + done 终帧：逐帧 JSON 形状锁定 + delta 拼接 == "你好"。"""
        body = _payload()
        async with (
            _client() as client,
            aconnect_sse(client, "POST", "/api/v1/chat/stream", json=body) as sse,
        ):
            status = sse.response.status_code
            assert status == 200  # RED：路由未注册 → 404，此处断言失败
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
            content_type = sse.response.headers["content-type"]
        assert content_type.startswith("text/event-stream")
        assert len(frames) == 3
        assert frames[0] == {"delta": "你", "done": False}  # 非 done 帧只有 delta + done 键
        assert frames[1] == {"delta": "好", "done": False}
        assert frames[2] == {"done": True}  # 终帧只有 done 键
        assert "".join(f["delta"] for f in frames[:2]) == "你好"

    @pytest.mark.asyncio
    async def test_stream_calls_service_with_chapter_context(
        self, override_chat_service, mock_chat_service
    ):
        """mock stream() 收到 prompt + chapter_context（keyword 透传）。"""
        body = {
            **_payload("帮我写一段打斗场景"),
            "chapter_id": str(uuid.uuid4()),
            "chapter_context": "第一章：主角初入宗门，遭遇同门挑衅。",
        }
        async with (
            _client() as client,
            aconnect_sse(client, "POST", "/api/v1/chat/stream", json=body) as sse,
        ):
            status = sse.response.status_code
            assert status == 200
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
        assert frames[-1]["done"] is True
        mock_chat_service.stream.assert_called_once_with(
            prompt="帮我写一段打斗场景",
            chapter_context="第一章：主角初入宗门，遭遇同门挑衅。",
        )

    @pytest.mark.asyncio
    async def test_stream_without_chapter_context(
        self, override_chat_service, mock_chat_service
    ):
        """chapter_context 缺省 → stream(chapter_context=None)。"""
        body = _payload()
        async with (
            _client() as client,
            aconnect_sse(client, "POST", "/api/v1/chat/stream", json=body) as sse,
        ):
            status = sse.response.status_code
            assert status == 200
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
        assert frames[-1]["done"] is True
        mock_chat_service.stream.assert_called_once_with(prompt=PROMPT, chapter_context=None)


# ── 流中错误路径 ────────────────────────────────────────────────


class TestChatStreamErrors:
    """流中 LLM 失败 → SSE error 终帧，HTTP 仍 200（镜像 writing.py _event_generator）。"""

    @pytest.mark.asyncio
    async def test_stream_llm_error_yields_error_frame(
        self, override_chat_service, mock_chat_service
    ):
        """首帧 delta 后抛 LLMRequestError → error 终帧，不泄漏内部细节。"""

        async def _gen(prompt: str, chapter_context: str | None = None):
            yield _ev(delta="你")
            raise LLMRequestError("API key invalid")
            yield  # pragma: no cover

        mock_chat_service.stream = _gen
        body = _payload()
        async with (
            _client() as client,
            aconnect_sse(client, "POST", "/api/v1/chat/stream", json=body) as sse,
        ):
            status = sse.response.status_code
            assert status == 200
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
        assert len(frames) == 2
        assert frames[0] == {"delta": "你", "done": False}
        assert frames[1] == {"done": True, "error": "LLM 调用失败，请稍后重试"}
        assert "API key invalid" not in json.dumps(frames, ensure_ascii=False)


# ── 装配路径 ────────────────────────────────────────────────────


class TestChatStreamAssembly:
    """真实装配：get_chat_service() 产出可用的 ChatService（#541 coverage 补测）。"""

    def test_get_chat_service_returns_assembled_service(self) -> None:
        """DI 覆盖绕过真实装配——本用例直接调用确认可构造（LangChainLLMClient 构造无网络）。"""
        from inkflow.api.routers.chat_stream import get_chat_service

        svc = get_chat_service()
        assert isinstance(svc, ChatService)
        # system_prompt 来自 _CHAT_ASSISTANT_PROMPT（含创作助手语义标识）
        assert "资深小说创作对话助手" in svc._system_prompt  # 单测直查装配内部提示词


class TestChatStreamDisconnect:
    """客户端提前断开 → 服务端生成器经 request.is_disconnected 分支终止（coverage 补测）。"""

    @pytest.mark.asyncio
    async def test_stream_client_disconnect_terminates_generator(
        self, override_chat_service, mock_chat_service
    ) -> None:
        """读 1 帧后关闭连接：多帧流在断开点停止（无异常；分支执行与否由 transport 决定）。"""

        async def _gen(prompt: str, chapter_context: str | None = None):
            for _ in range(200):
                yield _ev(delta="x")

        mock_chat_service.stream = _gen
        async with (
            _client() as client,
            aconnect_sse(client, "POST", "/api/v1/chat/stream", json=_payload()) as sse,
        ):
            async for _ in sse.aiter_sse():
                break  # 读 1 帧后立即关闭（模拟客户端断开）


# ── 校验错误路径 ────────────────────────────────────────────────


class TestChatStreamValidation:
    """prompt 缺失/空白 → 422「chat 流式请求需要 prompt」（镜像 agent.py 校验语义）。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            {"project_id": str(uuid.uuid4())},  # prompt 缺失
            {"project_id": str(uuid.uuid4()), "prompt": "   "},  # trim 后为空
        ],
    )
    async def test_missing_or_blank_prompt_returns_422(self, override_chat_service, body):
        async with _client() as client:
            resp = await client.post("/api/v1/chat/stream", json=body)
        assert resp.status_code == 422
        assert resp.json()["detail"] == "chat 流式请求需要 prompt"
