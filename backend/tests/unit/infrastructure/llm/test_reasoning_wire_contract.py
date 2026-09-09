"""#1044 RED: 思考档位注入 wire 层契约（echo server 捕获真实 HTTP body，零 key）。

背景（#1044 真实实证）:
- **D1 静默丢弃**：ChatLiteLLM（langchain-litellm 0.7.1）pydantic 字段面无
  ``reasoning_effort``、未配 ``model_config.extra`` → 顶层构造 kwargs 被静默丢弃，
  线上 body 无 ``thinking`` → 选档实为 no-op。参数进 litellm 的唯一通道是
  ``model_kwargs``（litellm.py:475 ``**self.model_kwargs``）。
- **D4 探测/翻译器不一致**：能力探测第二级 ``litellm.supports_reasoning`` 命中即停，
  不核对该 provider 的参数翻译器 → ``dashscope/qwen3-max`` 探测 True，注入
  ``reasoning_effort`` 时 litellm ``check_valid_params`` 本地直抛
  ``UnsupportedParamsError``（请求未发出）→ 断流。

契约:
1. 注入通道 = ``model_kwargs``：deepseek 全档 → wire ``thinking`` 方言
   （``none`` → ``{"type": "disabled"}``；``minimal/low/medium/high/xhigh`` →
   ``{"type": "enabled"}``）；``default``/None → wire 完全无思考键（§5.2 不发）。
2. 翻译器无参数（dashscope/qwen3-max）→ 决策点软降级：wire 干净（无
   ``thinking``/``reasoning_effort``/``enable_thinking``）+ WARNING，绝不 SDK 断流。
3. 两构造点同契约：``LangChainLLMClient._get_chat_model`` 与 ``build_deep_agent``。

RED 预期失败形态（修复前）:
- deepseek high：顶层 kwargs 被 pydantic 丢弃 → wire 无 ``thinking``（断言失败）；
- dashscope high：无 WARNING（软降级门禁不存在）+ 若参数真到 SDK 则
  ``UnsupportedParamsError`` 断流。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from langchain_core.messages import HumanMessage

from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

# wire 上的思考参数族（任一出现即视为"参数已发送"）
REASONING_WIRE_KEYS = ("thinking", "reasoning_effort", "enable_thinking", "thinking_budget")
NON_NONE_EFFORTS = ["minimal", "low", "medium", "high", "xhigh"]


class _EchoHandler(BaseHTTPRequestHandler):
    """捕获请求 body 并回确定性 OpenAI 兼容响应（零 key 契约测试端点）。"""

    def do_POST(self) -> None:  # BaseHTTPRequestHandler 固定方法名
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:  # 契约测试：非 JSON body 原样留证不中断
            parsed = {"_raw": raw.decode("utf-8", "replace")[:200]}
        _CAPTURED.append(parsed)
        payload = json.dumps(
            {
                "id": "chatcmpl-echo",
                "object": "chat.completion",
                "created": 1,
                "model": parsed.get("model", "echo"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:  # 测试端点静音访问日志
        pass


_CAPTURED: list[dict] = []


@pytest.fixture(scope="module")
def echo_base() -> str:
    """模块级 echo server（127.0.0.1 随机端口，OpenAI 兼容 /v1）。"""
    server = HTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def loguru_records():
    """loguru WARNING 捕获 sink（test_capability_probe 同款形态）。"""
    from loguru import logger

    records: list[dict] = []
    sink_id = logger.add(
        lambda m: records.append(m.record), level="WARNING", format="{message}"
    )
    yield records
    logger.remove(sink_id)


def _provider_cfg(provider: str, model_name: str, base_url: str) -> LLMProviderConfig:
    return LLMProviderConfig(
        provider=provider,
        api_key="echo-key",
        base_url=base_url,
        default_model=model_name,
        max_retries=0,
        timeout=10,
    )


async def _invoke_via_client(
    echo_base: str, *, provider: str, model_name: str, effort: str | None
) -> dict:
    """经生产构造点 LangChainLLMClient._get_chat_model 打 echo server，返回 wire body。"""
    from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

    _CAPTURED.clear()
    chat = LangChainLLMClient()._get_chat_model(
        _provider_cfg(provider, model_name, echo_base),
        model_name=model_name,
        reasoning_effort=effort,
    )
    await chat.ainvoke([HumanMessage(content="hi")])
    assert _CAPTURED, "wire 请求未到达 echo server（注入被 SDK 本地拦截 = 断流缺陷）"
    return _CAPTURED[-1]


def _warns(records: list[dict]) -> list[dict]:
    return [r for r in records if r["level"].name == "WARNING"]


class TestWireInjection:
    """§5.2 注入 + §5.4 翻译器对齐的 wire 层契约（deepseek 方言实证）。"""

    @pytest.mark.parametrize("effort", NON_NONE_EFFORTS)
    async def test_deepseek_effort_reaches_wire_as_thinking_enabled(
        self, echo_base: str, effort: str
    ) -> None:
        """非 none 档 → wire ``thinking={"type": "enabled"}``（顶层 kwargs 必丢）。"""
        body = await _invoke_via_client(
            echo_base, provider="deepseek", model_name="deepseek-v4-flash", effort=effort
        )
        assert body.get("thinking") == {"type": "enabled"}, (
            f"effort={effort} 应翻译为 wire thinking.enabled，实际 wire keys={sorted(body)}"
        )
        assert "reasoning_effort" not in body, "litellm 应翻译为方言，不残留原始参数键"

    async def test_deepseek_none_reaches_wire_as_thinking_disabled(
        self, echo_base: str
    ) -> None:
        """none 档 → wire ``thinking={"type": "disabled"}``（显式关闭语义）。"""
        body = await _invoke_via_client(
            echo_base, provider="deepseek", model_name="deepseek-v4-flash", effort="none"
        )
        assert body.get("thinking") == {"type": "disabled"}

    @pytest.mark.parametrize("effort", ["default", None])
    async def test_default_and_absent_send_no_reasoning_param(
        self, echo_base: str, effort: str | None
    ) -> None:
        """§5.2 不发：default / 未传 → wire 无任何思考参数键。"""
        body = await _invoke_via_client(
            echo_base, provider="deepseek", model_name="deepseek-v4-flash", effort=effort
        )
        leaked = [key for key in REASONING_WIRE_KEYS if key in body]
        assert not leaked, f"default/None 不得发送思考参数，实际 wire 出现 {leaked}"


class TestTranslatorGateWire:
    """D4：探测 True 但翻译器无参数 → 决策点软降级（wire 干净 + WARNING，不断流）。"""

    @pytest.mark.parametrize("effort", ["high", "none"])
    async def test_dashscope_unsupported_translator_strips_and_warns(
        self, echo_base: str, loguru_records: list[dict], effort: str
    ) -> None:
        """dashscope/qwen3-max（探测 True、翻译器无 reasoning_effort）→ 剥离 + WARNING。"""
        body = await _invoke_via_client(
            echo_base, provider="dashscope", model_name="qwen3-max", effort=effort
        )
        leaked = [key for key in REASONING_WIRE_KEYS if key in body]
        assert not leaked, (
            f"翻译器不支持时不得发思考参数（否则 SDK 本地 UnsupportedParamsError 断流）；"
            f"实际 wire 出现 {leaked}"
        )
        warns = _warns(loguru_records)
        assert warns, "翻译器无参数必须软降级留痕（WARNING）"
        extra = warns[-1]["extra"]
        assert extra.get("message_key") == "log.check.reasoning_downgrade"
        assert (extra.get("params") or {}).get("reason") == "translator_unsupported"

    async def test_zai_unsupported_model_strips_and_warns(
        self, echo_base: str, loguru_records: list[dict]
    ) -> None:
        """zai/glm-4.5（探测 False）→ 既有软降级路径：wire 干净 + WARNING。"""
        body = await _invoke_via_client(
            echo_base, provider="zhipu", model_name="glm-4.5", effort="high"
        )
        leaked = [key for key in REASONING_WIRE_KEYS if key in body]
        assert not leaked
        warns = _warns(loguru_records)
        assert warns, "超能力档位必须软降级留痕（WARNING）"
        assert (warns[-1]["extra"].get("params") or {}).get("reason") == (
            "capability_unsupported"
        )


class TestHarnessWireContract:
    """构造点 2：build_deep_agent 直传的 ChatLiteLLM 实例同 wire 契约。"""

    async def test_harness_deepseek_high_wire_thinking_enabled(
        self, echo_base: str
    ) -> None:
        from unittest import mock

        from inkflow.infrastructure.agent.deepagents.harness import build_deep_agent

        _CAPTURED.clear()
        with mock.patch(
            "inkflow.infrastructure.agent.deepagents.harness.create_deep_agent"
        ) as create:
            build_deep_agent(
                model="deepseek/deepseek-v4-flash",
                api_key="echo-key",
                base_url=echo_base,
                tools=[],
                system_prompt="p",
                reasoning_effort="high",
            )
        chat = create.call_args.kwargs["model"]
        await chat.ainvoke([HumanMessage(content="hi")])
        assert _CAPTURED, "harness 构造点 wire 请求未到达 echo server"
        assert _CAPTURED[-1].get("thinking") == {"type": "enabled"}


class TestConstructSiteFitness:
    """适应度函数：两构造点必须经传输适配器（防"又有人把决策键放顶层"回归）。"""

    @pytest.mark.parametrize(
        "module_name",
        [
            "inkflow.infrastructure.llm.langchain_client",
            "inkflow.infrastructure.agent.deepagents.harness",
        ],
    )
    def test_construct_site_uses_transport_adapter(self, module_name: str) -> None:
        import importlib
        import inspect

        src = inspect.getsource(importlib.import_module(module_name))
        assert "to_chat_model_kwargs" in src, (
            f"{module_name} 构造点必须经 capability_probe.to_chat_model_kwargs "
            "把决策键搬进 model_kwargs（#1044 D1：顶层 kwargs 被 pydantic 静默丢弃）"
        )
