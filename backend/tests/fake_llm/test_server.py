"""fake LLM server HTTP 契约测试（S0，ADR-047）— POST /v1/chat/completions。

① POST 返回 scripted 正确/错误 fixture；② SSE 逐帧 delta/done/error；④ 错误计数。

RED 阶段：`.server` 不存在 → 收集级 FAIL（feature missing）。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from .routing import select_fixture
from .server import app, create_app


@pytest.fixture
def server_app():
    """module-level app 与 create_app() 均应可用（契约钉住入口）。"""
    assert app is not None
    return create_app()


@pytest.fixture
def client(server_app) -> TestClient:
    return TestClient(server_app)


def _post(client: TestClient, model: str, **extra) -> Response:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        **extra,
    }
    return client.post("/v1/chat/completions", json=payload)


class TestChatCompletionsNonStream:
    """① 非流式：JSON 返回 scripted correct fixture。"""

    def test_returns_correct_fixture(self, client: TestClient) -> None:
        resp = _post(client, "fake/correct")
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "chat.completion"
        assert body["model"] == "fake/correct"
        expected = select_fixture("fake/correct", {"model": "fake/correct"})
        assert body["choices"][0]["message"]["content"] == expected.content
        assert body["choices"][0]["finish_reason"] == "stop"
        # usage 契约：正常响应含 token usage
        assert "usage" in body

    def test_error_model_maps_to_http_status(self, client: TestClient) -> None:
        """错误 fixture → 对应 HTTP 状态 + OpenAI 错误 body。"""
        for model, status in [
            ("fake/error-401", 401),
            ("fake/error-429", 429),
            ("fake/error-500", 500),
        ]:
            resp = _post(client, model)
            assert resp.status_code == status
            body = resp.json()
            assert "error" in body
            assert body["error"]["code"] == select_fixture(model, {"model": model}).error_code


class TestChatCompletionsStream:
    """② SSE 流式：逐帧 delta + data:[DONE] 结尾。"""

    def test_stream_returns_delta_frames_then_done(self, client: TestClient) -> None:
        with client.stream("POST", "/v1/chat/completions", json={
            "model": "fake/correct",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            frames: list[str] = []
            for line in resp.iter_lines():
                if line:
                    frames.append(line)
        # 末尾必须 data: [DONE]
        assert frames[-1] == "data: [DONE]"
        # 前面的帧必须是 data: <json>（delta chunk）
        deltas = [json.loads(f[6:]) for f in frames[:-1] if f.startswith("data: ")]
        assert deltas, "流式响应应至少包含一个 delta 帧"
        assert all(d["object"] == "chat.completion.chunk" for d in deltas)
        # 至少一帧含非空 delta.content
        contents = [c["choices"][0]["delta"].get("content", "") for c in deltas]
        assert any(c for c in contents)

    def test_stream_error_frame_emitted(self, client: TestClient) -> None:
        """错误场景流式：以 error 帧结束（不抛裸异常）。"""
        with client.stream("POST", "/v1/chat/completions", json={
            "model": "fake/error-500",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }) as resp:
            frames: list[str] = []
            for line in resp.iter_lines():
                if line:
                    frames.append(line)
        last = frames[-1]
        # 要么流式 status 500 + error body，要么 SSE error 帧，二者取一
        if resp.status_code == 200:
            assert "error" in last or "data: [DONE]" in last
        else:
            assert resp.status_code in (400, 401, 429, 500)


class TestErrorCounting:
    """④ scripted 超时/错误计数：服务器按场景统计命中次数（供重试/退避测试）。"""

    def test_error_counts_increment_per_hit(self, client: TestClient, server_app) -> None:
        _post(client, "fake/error-429")
        _post(client, "fake/error-429")
        counts = server_app.state.error_counts
        assert counts.get("error-429") == 2

        _post(client, "fake/error-500")
        assert counts.get("error-500") == 1
        # correct 不计入 error_counts
        assert counts.get("correct") in (None, 0)


class TestScriptedTimeoutAndSignature:
    """参数化超时 / 哨兵签名经 HTTP 层的确定性行为（覆盖率补测）。"""

    def test_scripted_timeout_returns_empty_content(self, client: TestClient) -> None:
        """脚本化超时：非流式应 sleep 后返回 200 + empty content。"""
        resp = _post(client, "fake/error-timeout")
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == ""

    def test_sentinel_signature_override_via_http(
        self, client: TestClient, server_app
    ) -> None:
        """哨兵 [[fake-scenario:error-429]] 经 HTTP 应覆盖 model 并计入错误计数。"""
        payload = {
            "model": "fake/correct",
            "messages": [{"role": "user", "content": "go [[fake-scenario:error-429]]"}],
        }
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 429
        assert server_app.state.error_counts.get("error-429") == 1

    def test_non_dict_message_via_http_is_safe(self, client: TestClient) -> None:
        """HTTP 层非 dict 消息（字符串）应被安全忽略，返回正确响应。"""
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "fake/correct", "messages": ["raw-text"]},
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"]
