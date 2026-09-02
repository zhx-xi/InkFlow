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


class TestEmbeddings:
    """S3f-T3 §1.2 POST /v1/embeddings：OpenAI 兼容形状 / 确定性 / 维度恒定 / 记录。

    契约裁定（§1.2 错误分支）：input=[] 空数组 → 200 data==[]（OpenAI 空输入空输出，
    非 400），与「缺 input → 400」并存。RED 期 server.py 无此端点 → 404/405。
    """

    MODEL = "e2e-embed-test"

    def _post_embeddings(self, client: TestClient, input_value) -> Response:
        payload = {"model": self.MODEL, "input": input_value}
        return client.post("/v1/embeddings", json=payload)

    def test_list_shape_ordered_index_and_float_embeddings(self, client: TestClient) -> None:
        """形状：object=list、data 顺序对应 input、index 递增、embedding 为 float 列表。"""
        resp = self._post_embeddings(client, ["你好", "world"])
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "list"
        assert body["model"] == self.MODEL
        assert len(body["data"]) == 2
        for i, item in enumerate(body["data"]):
            assert item["object"] == "embedding"
            assert item["index"] == i
            assert isinstance(item["embedding"], list)
            assert all(isinstance(x, float) for x in item["embedding"])

    def test_deterministic_same_input_vectors_equal(self, client: TestClient) -> None:
        """确定性：同 input 两次请求 → 向量逐元素相等。"""
        inputs = ["你好", "world"]
        first = self._post_embeddings(client, inputs).json()["data"]
        second = self._post_embeddings(client, inputs).json()["data"]
        assert [item["embedding"] for item in first] == [item["embedding"] for item in second]

    def test_different_input_vectors_differ(self, client: TestClient) -> None:
        """确定性反例：不同 input → 向量不等。"""
        base = self._post_embeddings(client, ["你好"]).json()["data"]
        other = self._post_embeddings(client, ["world"]).json()["data"]
        assert base[0]["embedding"] != other[0]["embedding"]

    def test_default_dim_constant_8(self) -> None:
        """维度恒定：默认 create_app() → 所有向量 len==8。"""
        app8 = TestClient(create_app())
        data = self._post_embeddings(app8, ["你好", "world"]).json()["data"]
        assert {len(item["embedding"]) for item in data} == {8}

    def test_custom_dim_4_applies(self) -> None:
        """维度恒定：create_app(dim=4) → 所有向量 len==4（自定义 app 生效）。"""
        app4 = TestClient(create_app(dim=4))
        data = self._post_embeddings(app4, ["你好", "world", "第三个"]).json()["data"]
        assert {len(item["embedding"]) for item in data} == {4}

    def test_string_input_single_embedding(self, client: TestClient) -> None:
        """input 为字符串（非数组）：200 且 data 长度 1。"""
        resp = self._post_embeddings(client, "单串")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["index"] == 0

    def test_missing_input_returns_400_openai_error_shape(self, client: TestClient) -> None:
        """错误：body 缺 input → 400 + {"error": {"message": ...}} 形状。"""
        resp = client.post("/v1/embeddings", json={"model": self.MODEL})
        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body
        assert "message" in body["error"]

    def test_empty_input_list_returns_empty_data(self, client: TestClient) -> None:
        """契约裁定（§1.2）：input=[] → 200 data==[]（OpenAI 空输入空输出）。"""
        resp = self._post_embeddings(client, [])
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_embedding_requests_recorded_with_model(self, client: TestClient, server_app) -> None:
        """记录：app.state.embedding_requests 随请求增长，含 model 字段。"""
        self._post_embeddings(client, ["你好"])
        self._post_embeddings(client, "world")
        records = server_app.state.embedding_requests
        assert len(records) == 2
        assert [record["model"] for record in records] == [self.MODEL, self.MODEL]

    # ── S3f-T3 黑盒修正（reindex probe 实证）：langchain OpenAIEmbeddings len-safe
    # 路径实际发送 token 数组（list[list[int]] / list[int]），非原文。真实 OpenAI
    # /v1/embeddings 契约 input: string | list[int] | list[list[int]]（三种全支持）。
    # 只收 str 列表 = 真实内核 RAG 链 400 → probe_embedding_dimension 失败 → reindex 500。

    def test_token_batch_input_supported(self, client: TestClient) -> None:
        """input=list[list[int]]（len-safe 批量 token）→ 200，data 一一对应且向量互异。"""
        resp = self._post_embeddings(client, [[1, 2, 3], [4, 5]])
        assert resp.status_code == 200, f"token 批量应 200，实际 {resp.status_code}"
        data = resp.json()["data"]
        assert len(data) == 2
        assert data[0]["embedding"] != data[1]["embedding"]

    def test_single_token_list_input(self, client: TestClient) -> None:
        """input=list[int]（单条 token 序列）→ 200 且 data 长度 1（OpenAI 规范第三形态）。"""
        resp = self._post_embeddings(client, [7, 8, 9])
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    def test_token_input_deterministic(self, client: TestClient) -> None:
        """token 数组确定性：同 tokens 两次请求向量逐元素相等（reindex 幂等基础）。"""
        first = self._post_embeddings(client, [[1, 2, 3]]).json()["data"][0]["embedding"]
        second = self._post_embeddings(client, [[1, 2, 3]]).json()["data"][0]["embedding"]
        assert first == second

    def test_mixed_token_and_text_batch(self, client: TestClient) -> None:
        """混合批量 [[1,2], "文本"] → 200 data 长度 2（宽容对齐 OpenAI 宽松形态）。"""
        resp = self._post_embeddings(client, [[1, 2], "文本"])
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2
