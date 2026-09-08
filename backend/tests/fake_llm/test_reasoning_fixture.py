"""#964 F59-M3 fake LLM reasoning 场景 RED 契约测试（plan A9）.

fake_llm 需新增 `Fixture.reasoning_content` 字段 + `reasoning` 场景：
- `select_fixture("openai/reasoning", ...)` → `fixture.reasoning_content == '先分析再回答'`；
  content 非空。
- prompt 签名 `[[fake-scenario:reasoning]]` 优先：model 后缀不是 reasoning 时也命中 reasoning 场景。
- HTTP（fastapi.testclient）流式：SSE 中存在 `reasoning_content` delta 帧，且出现在首个
  `content` delta 之前；末尾仍有 `data: [DONE]`。非流式：`choices[0].message.reasoning_content`
  == '先分析再回答' 且 `message.content` 非空。
- 既有场景不回归：`select_fixture("openai/correct", ...)` → reasoning_content == ""。

当前 routing.Fixture 无 reasoning_content 字段、server 不注入 reasoning_content → 本批逐用例 FAIL
（AttributeError / KeyError / 无 reasoning delta 帧）。写法镜像 test_server.py 的 TestClient 形态。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from .routing import select_fixture
from .server import create_app

REASONING_TEXT = "先分析再回答"


@pytest.fixture
def client() -> TestClient:
    """独立 app（避免共享 module app 污染 error_counts）。"""
    return TestClient(create_app())


class TestSelectFixtureReasoning:
    """契约 1/2/4：select_fixture 命中/签名覆盖/既有场景不回归。"""

    def test_reasoning_model_returns_reasoning_fixture(self) -> None:
        """model 后缀为 reasoning → fixture.reasoning_content 非空 + content 非空。"""
        fixture = select_fixture(
            "openai/reasoning", {"messages": [{"role": "user", "content": "hi"}]}
        )
        assert fixture.reasoning_content == REASONING_TEXT
        assert fixture.content

    def test_prompt_signature_overrides_model(self) -> None:
        """prompt 签名 [[fake-scenario:reasoning]] 优先：model 非 reasoning 后缀也命中。"""
        fixture = select_fixture(
            "openai/o3-mini",
            {"messages": [{"role": "user", "content": "go [[fake-scenario:reasoning]]"}]},
        )
        assert fixture.reasoning_content == REASONING_TEXT
        assert fixture.content

    def test_correct_fixture_has_no_reasoning(self) -> None:
        """既有场景不回归：correct → reasoning_content 为空串。"""
        fixture = select_fixture(
            "openai/correct", {"messages": [{"role": "user", "content": "hi"}]}
        )
        assert fixture.reasoning_content == ""


class TestReasoningHttp:
    """契约 3：HTTP 面（流式 reasoning delta 先发；非流式 reasoning_content 在 message）。"""

    def _post(self, client: TestClient, model: str, **extra):
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            **extra,
        }
        return client.post("/v1/chat/completions", json=payload)

    def test_non_stream_json_has_reasoning_content(self, client: TestClient) -> None:
        """非流式：choices[0].message.reasoning_content == 思考文本 + content 非空。"""
        resp = self._post(client, "openai/reasoning")
        assert resp.status_code == 200
        message = resp.json()["choices"][0]["message"]
        assert message["reasoning_content"] == REASONING_TEXT
        assert message["content"]

    def test_stream_emits_reasoning_delta_before_content(self, client: TestClient) -> None:
        """流式：SSE 存在 reasoning_content delta 帧且在首个 content delta 之前。"""
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "openai/reasoning",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            frames: list[str] = [line for line in resp.iter_lines() if line]

        # 末尾必须 data: [DONE]
        assert frames[-1] == "data: [DONE]"
        deltas = [json.loads(f[6:]) for f in frames[:-1] if f.startswith("data: ")]
        assert deltas, "流式响应应至少包含一个 delta 帧"

        reasoning_idx: int | None = None
        content_idx: int | None = None
        for i, d in enumerate(deltas):
            delta = d["choices"][0]["delta"]
            if reasoning_idx is None and "reasoning_content" in delta:
                reasoning_idx = i
            if content_idx is None and delta.get("content"):
                content_idx = i

        # 存在 reasoning_content delta 帧
        assert reasoning_idx is not None, "SSE 必须包含 reasoning_content delta 帧"
        # 出现在首个 content delta 之前
        assert content_idx is not None, "SSE 必须包含首 content delta 帧"
        assert reasoning_idx < content_idx, "reasoning_content delta 应在首个 content delta 之前"
