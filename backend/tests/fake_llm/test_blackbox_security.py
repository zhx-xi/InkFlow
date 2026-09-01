"""#872 非功能安全/超时重试黑盒（S3a，ADR-047 口径）——真 fake LLM server 经真实 HTTP。

本文件用例都走**真 HTTP**（fake_llm fixture 起真 uvicorn），验证「真实内核/LLM 客户端
经 wire 与 fake server 交互」的端到端契约：
- M2（C5②）：/api/v1/chat/stream 端点在把 prompt 发给 LLM **前**脱敏——fake server 收到
  的 messages 必须不含已存 key 形态（黑盒闭环）。
- M4a（C4）：LLM 调用超时 → SSE error 帧（HTTP 仍 200，不泄内部细节）。
- M4b（C4）：max_retries 重试计数——fake server 按场景统计命中次数 == 配置次数。

样例 key 一律模块级拼接构造（源码不出连续敏感形态，防上层输出脱敏污染）。
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from httpx_sse import aconnect_sse

from inkflow.api.app import app
from inkflow.core.config import config
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.provider_config import get_provider_config

# ── 拼接构造（运行时值正确，源码不含连续敏感形态）──
FAKE_PROV = "fake"
KEY = "sk-" + ("k" * 16)  # sk-<16k>（A 正则命中 → 遮蔽；known_keys 为空时仅 A 兜底）


def _patch_fake_config(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    """把 config 指向 fake provider（LLM 客户端/端点经 base_url 打真 fake server）。"""
    monkeypatch.setattr(config, "llm_base_url", base_url)
    monkeypatch.setattr(config, "llm_default_model", f"{FAKE_PROV}/correct")
    monkeypatch.setattr(config, "llm_max_retries", 3)
    monkeypatch.setattr(config, "llm_request_timeout", 30)


def _received_prompts(fake_llm) -> list[list[dict]]:
    return fake_llm.app.state.received_prompts


# ── M2：/stream 端点脱敏黑盒 ───────────────────────────────────────


class TestPromptKeyBlackbox:
    """fake LLM 收到的 prompt 断言无 key（F53 脱敏黑盒闭环）。"""

    @pytest.mark.asyncio
    async def test_stream_redacts_key_before_llm(self, fake_llm, monkeypatch) -> None:
        """带 key 的 prompt 经 /stream 端点 → fake server 收到的 messages 无该 key。"""
        _patch_fake_config(monkeypatch, fake_llm.base_url)

        async with (
            AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
            ) as client,
            aconnect_sse(
                client,
                "POST",
                "/api/v1/chat/stream",
                json={
                    "project_id": str(uuid.uuid4()),
                    "prompt": f"请用密钥 {KEY} 继续写",
                },
            ) as sse,
        ):
            assert sse.response.status_code == 200
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]

        assert frames[-1]["done"] is True  # 正常流完成
        received = _received_prompts(fake_llm)
        assert received, "fake server 应至少收到一次请求"
        for msg in received[0]:
            content = str(msg.get("content", ""))
            assert KEY not in content  # 脱敏后不发 key
            assert f"{KEY[:3]}****" in content or "****" in content
        # done 帧无 key
        assert KEY not in json.dumps(frames, ensure_ascii=False)


# ── M4b：重试计数 ─────────────────────────────────────────────────


class TestRetryCount:
    """max_retries 重试：fake server error_counts 命中次数 == 配置次数。"""

    @pytest.mark.asyncio
    async def test_max_retries_count(self, fake_llm, monkeypatch) -> None:
        """error-500 场景：LLM 客户端应重试，server 命中次数 == llm_max_retries+1 总尝试。

        契约：虚假 error-500 时 ChatOpenAI(max_retries=N) 的 wire 请求次数 = N+1
        （首次 + N 次重试）。这钉住「max_retries 真正到达 LLM 层」的事实。
        """
        monkeypatch.setattr(config, "llm_base_url", fake_llm.base_url)
        monkeypatch.setattr(config, "llm_max_retries", 2)
        # fake provider 需 base_url；get_provider_config("fake")
        client = LangChainLLMClient(default_model=f"{FAKE_PROV}/error-500")

        with pytest.raises(LLMRequestError):
            await client.chat(
                [  # 让 LangChainLLMClient 走到 LLM 调用
                    _chat_message("user", "hi")
                ]
            )

        counts = fake_llm.app.state.error_counts
        assert counts.get("error-500") == 3  # 首次 + 2 次重试

    def test_provider_config_wires_timeout_and_retries(self, monkeypatch) -> None:
        """provider_config 把 config.llm_request_timeout/max_retries 传给 fake provider。"""
        monkeypatch.setattr(config, "llm_base_url", "http://127.0.0.1:1/v1")
        monkeypatch.setattr(config, "llm_max_retries", 7)
        monkeypatch.setattr(config, "llm_request_timeout", 123)
        cfg = get_provider_config(FAKE_PROV)
        assert cfg.max_retries == 7
        assert cfg.timeout == 123


# ── M4a：LLM 超时 → error 帧 ──────────────────────────────────────


class TestTimeoutErrorFrame:
    """LLM 调用失败/超时 → SSE error 帧（HTTP 仍 200，不泄内部细节）。"""

    @pytest.mark.asyncio
    async def test_stream_llm_error_yields_error_frame(self, fake_llm, monkeypatch) -> None:
        """fake server 返回 error-500 → /stream 端点产出 error 终帧。"""
        _patch_fake_config(monkeypatch, fake_llm.base_url)

        async with (
            AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
            ) as client,
            aconnect_sse(
                client,
                "POST",
                "/api/v1/chat/stream",
                json={
                    "project_id": str(uuid.uuid4()),
                    "prompt": "hi [[fake-scenario:error-500]]",
                },
            ) as sse,
        ):
            assert sse.response.status_code == 200
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]

        last = frames[-1]
        assert last.get("done") is True
        assert last.get("error", "") != ""
        # 不泄内部细节（500 错误消息不直接透传）
        assert "Internal server error" not in json.dumps(frames, ensure_ascii=False)


def _chat_message(role: str, content: str):
    from inkflow.domain.ports.llm_client import ChatMessage

    return ChatMessage(role=role, content=content)
