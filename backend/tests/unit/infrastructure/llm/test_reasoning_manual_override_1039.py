"""#1039 F59 收口 RED 契约：思考档位 manual 覆盖进注入链 + trace/content 形式断言.

三条发现（来源 #964 只读审查）对应契约：

发现②（本文件主体，真缺口）：harness.build_deep_agent 与
langchain_client._get_chat_model 调 apply_reasoning_effort 时不传 manual= →
注册表 models[].supports_reasoning 手动覆盖「显示层可见、注入层无效」。

契约：
1. provider_config.resolve_reasoning_manual(model) -> bool | None（新函数，
   构造点统一数据源，#976 全路径同机制）：入参 = 注册表模型全名
   （provider 前缀 = 注册表名，非 litellm 校准名——zhipu/glm-4.5 查 zhipu 行）；
   查持久化注册表对应条目的 supports_reasoning 手动值（True/False 返回、
   None/未命中/无条目/异常一律 None=跟随自动探测）。
2. 两构造点把 manual 传入 apply_reasoning_effort：
   - manual=True → effort 注入 model_kwargs（即使 litellm 真值表 False）+
     同传 allowed_openai_params=["reasoning_effort"]（Q1=A 拍板：litellm 本地
     门禁 check_valid_params 对表 False 模型直抛 UnsupportedParamsError，
     实证 probe B1/C1；不带旁路则 manual=True 注入被 SDK 断流，覆盖等于虚设。
     旁路仅随 manual=True 出现——自动探测路径零变化）。
   - manual=False → 剥离 + log.check.reasoning_downgrade WARNING
     （reason=capability_unsupported）。
   - manual=None → 现行为完全不变（含 test_deepagents_harness 全等断言）。
3. wire 级证据（Q2=A unit 轨自包含 echo server）：表 False 的自定义模型 +
   注册表 manual=True → 请求体真携带 reasoning_effort（修复前被决策点剥离 =
   wire 无思考键，RED FAIL）；manual=False → wire 干净 + WARNING + 不断流。

发现①（#1045 已闭合，本批补形式断言，用户拍板）：trace 收集轨 _collect_model_end
对 content=None（tool-call-only AIMessage）产出恒 str 的 message_content——
既有 #1045 用例只断言 delta 帧面，consume_trace() 返回值轨无显式锁定。

发现③（拍板 (b) 有意静默 + 锁定）：content_text 对非预期形状（None/int/非
text dict）返回 "" 且不产任何 WARNING 日志（行为 + 源码注释双锁，防「日后
偷偷加日志/加 repr」无契约回退）。

RED 预期失败形态（修复前）：
- provider_config 无 resolve_reasoning_manual → 用例内 getattr AttributeError；
- 两构造点查表绑定（harness/langchain_client 模块命名空间的
  resolve_reasoning_manual）不存在 → monkeypatch.setattr AttributeError；
- manual=True wire：决策点未消费注册表 → 剥离 → wire 无 reasoning_effort；
- ③ 源码注释锁：content_text 尚无「Intentionally silent」注释 → False。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from unittest import mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from inkflow.core.config import config
from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

# 表 False 且翻译器无思考参数的自定义模型（probe 实证 B1：注入无旁路必
# UnsupportedParamsError；manual=True 旁路后 wire 携带）
CUSTOM_MODEL = "openai/custom-q"
DEEPSEEK = "deepseek/deepseek-v4-flash"
ECHO_KEY = "sk-" + "echo-probe-key"  # 变量拼接防 Hermes redact 污染夹具（#614 坑 7）

# wire 上的思考参数族（任一出现即视为「参数已发送」）
REASONING_WIRE_KEYS = ("thinking", "reasoning_effort", "enable_thinking", "thinking_budget")


# ── 注册表替身（_await_registry_entry 返回值鸭子：只读 models 属性）──


def _registry_entry(models: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(models=models)


def _entry_true() -> SimpleNamespace:
    return _registry_entry(
        [
            SimpleNamespace(id="other-model", supports_reasoning=None),
            SimpleNamespace(id="custom-q", supports_reasoning=True),
        ]
    )


def _entry_false() -> SimpleNamespace:
    return _registry_entry([SimpleNamespace(id="custom-q", supports_reasoning=False)])


def _entry_miss() -> SimpleNamespace:
    return _registry_entry([SimpleNamespace(id="unrelated", supports_reasoning=True)])


def _patch_registry(monkeypatch: pytest.MonkeyPatch, entry: object | None) -> mock.MagicMock:
    """patch provider_config._await_registry_entry（构造点/直调共用注册表 seam）。"""
    fake = mock.MagicMock(return_value=entry)
    monkeypatch.setattr(
        "inkflow.infrastructure.llm.provider_config._await_registry_entry", fake
    )
    return fake


# ════════════════ 契约 1：resolve_reasoning_manual 纯函数（新）════════════════


class TestResolveReasoningManual:
    """注册表 manual 覆盖解析：True/False 透传，其余一律 None（=跟随自动探测）。"""

    def test_manual_true_parsed_from_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_registry(monkeypatch, _entry_true())
        from inkflow.infrastructure.llm.provider_config import resolve_reasoning_manual

        assert resolve_reasoning_manual(CUSTOM_MODEL) is True

    def test_manual_false_parsed_from_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_registry(monkeypatch, _entry_false())
        from inkflow.infrastructure.llm.provider_config import resolve_reasoning_manual

        assert resolve_reasoning_manual(CUSTOM_MODEL) is False

    def test_entry_without_override_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """条目存在但 supports_reasoning=None（自动探测）→ None，绝不泄漏 False。"""
        entry = _registry_entry([SimpleNamespace(id="custom-q", supports_reasoning=None)])
        _patch_registry(monkeypatch, entry)
        from inkflow.infrastructure.llm.provider_config import resolve_reasoning_manual

        assert resolve_reasoning_manual(CUSTOM_MODEL) is None

    def test_model_miss_in_registry_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """条目存在但模型名不匹配（同 provider 其他模型有覆盖）→ None。"""
        _patch_registry(monkeypatch, _entry_miss())
        from inkflow.infrastructure.llm.provider_config import resolve_reasoning_manual

        assert resolve_reasoning_manual(CUSTOM_MODEL) is None

    def test_registry_miss_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """provider 无注册表条目（内置回退形态）→ None。"""
        _patch_registry(monkeypatch, None)
        from inkflow.infrastructure.llm.provider_config import resolve_reasoning_manual

        assert resolve_reasoning_manual(DEEPSEEK) is None

    def test_bare_model_name_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无 provider/ 前缀裸名（parse ValueError）→ None（防御，绝不抛）。"""
        fake = _patch_registry(monkeypatch, _entry_true())
        from inkflow.infrastructure.llm.provider_config import resolve_reasoning_manual

        assert resolve_reasoning_manual("custom-q") is None
        assert fake.call_count == 0, "裸名不得触达注册表查询"

    def test_registry_exception_soft_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """注册表查询异常（DB 未初始化/无表）→ None（镜像 get_provider_config 回退）。"""

        def _boom(_provider: str) -> SimpleNamespace:
            raise RuntimeError("no such table: provider_configs")

        monkeypatch.setattr(
            "inkflow.infrastructure.llm.provider_config._await_registry_entry", _boom
        )
        from inkflow.infrastructure.llm.provider_config import resolve_reasoning_manual

        assert resolve_reasoning_manual(CUSTOM_MODEL) is None

    @pytest.mark.parametrize("models", [[], None])
    def test_empty_or_missing_models_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, models: list[object] | None
    ) -> None:
        """registry 命中但 models 空列表/缺属性 → None（防御分支锁定）。"""
        _patch_registry(monkeypatch, SimpleNamespace(models=models))
        from inkflow.infrastructure.llm.provider_config import resolve_reasoning_manual

        assert resolve_reasoning_manual(CUSTOM_MODEL) is None


# ════════════════ 契约 2：两构造点消费 manual（kwargs 面，mock ChatLiteLLM）════


class TestHarnessManualOverride:
    """构造点 1：harness.build_deep_agent 从注册表解析 manual 进注入链。"""

    def _call(self, model: str, effort: str, monkeypatch: pytest.MonkeyPatch):
        from inkflow.infrastructure.agent.deepagents import harness

        # RED 形态：GREEN 前 harness 命名空间无该绑定 → AttributeError（预期失败）
        monkeypatch.setattr(harness, "resolve_reasoning_manual", lambda _m: None)
        with (
            mock.patch("inkflow.infrastructure.agent.deepagents.harness.ChatLiteLLM") as chat_cls,
            mock.patch(
                "inkflow.infrastructure.agent.deepagents.harness.create_deep_agent",
                return_value=mock.MagicMock(name="agent"),
            ),
        ):
            harness.build_deep_agent(
                model=model,
                api_key="sk-test",
                base_url="https://x/v1",
                tools=[],
                system_prompt="p",
                reasoning_effort=effort,
            )
        return chat_cls

    def test_harness_looks_up_manual_with_registry_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """构造点必须查表，且入参 = 注册表全名（非 litellm 校准名——zhipu→zai 后
        查表必 miss，前缀口径陷阱锁）。"""
        from inkflow.infrastructure.agent.deepagents import harness

        calls: list[str] = []
        monkeypatch.setattr(harness, "resolve_reasoning_manual", calls.append)
        with (
            mock.patch("inkflow.infrastructure.agent.deepagents.harness.ChatLiteLLM"),
            mock.patch(
                "inkflow.infrastructure.agent.deepagents.harness.create_deep_agent",
                return_value=mock.MagicMock(name="agent"),
            ),
        ):
            harness.build_deep_agent(
                model="zhipu/glm-4.5",
                api_key="sk-test",
                base_url="https://x/v1",
                tools=[],
                system_prompt="p",
                reasoning_effort="high",
            )
        assert calls == ["zhipu/glm-4.5"], (
            f"必须以注册表全名查 manual（校准名 zai/glm-4.5 查表 miss），实得 {calls}"
        )

    def test_manual_true_injects_effort_even_when_litellm_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """litellm 表 False + 注册表 manual True → effort 照常注入（#1039 验收态 1）。"""
        from inkflow.infrastructure.llm.capability_probe import supports_reasoning_for_model

        assert supports_reasoning_for_model(CUSTOM_MODEL) is False, (
            "用例前提（probe 实证）：该模型 litellm 自动探测为 False"
        )
        from inkflow.infrastructure.agent.deepagents import harness

        monkeypatch.setattr(harness, "resolve_reasoning_manual", lambda _m: True)
        chat_cls = self._raw_build(
            harness, model=CUSTOM_MODEL, effort="high",
        )
        kwargs = chat_cls.call_args[1]
        mk = kwargs.get("model_kwargs") or {}
        assert mk.get("reasoning_effort") == "high", (
            f"manual=True 必须注入，实得 kwargs={kwargs}"
        )

    def test_manual_true_carries_allowed_openai_params_bypass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Q1=A：manual=True 注入必须同带 SDK 本地门禁旁路（实证 B1：无旁路注入 =
        UnsupportedParamsError 断流，覆盖等于虚设）。"""
        from inkflow.infrastructure.agent.deepagents import harness

        monkeypatch.setattr(harness, "resolve_reasoning_manual", lambda _m: True)
        chat_cls = self._raw_build(harness, model=CUSTOM_MODEL, effort="high")
        mk = chat_cls.call_args[1].get("model_kwargs") or {}
        assert mk.get("allowed_openai_params") == ["reasoning_effort"]

    def test_auto_probe_path_has_no_bypass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """反护栏：manual=None 走自动探测（deepseek 表 True）→ 注入但绝不含
        allowed_openai_params（Q1=A 范围纪律：旁路仅随显式覆盖）。"""
        from inkflow.infrastructure.agent.deepagents import harness

        monkeypatch.setattr(harness, "resolve_reasoning_manual", lambda _m: None)
        chat_cls = self._raw_build(harness, model=DEEPSEEK, effort="high")
        kwargs = chat_cls.call_args[1]
        mk = kwargs.get("model_kwargs") or {}
        assert mk.get("reasoning_effort") == "high"
        assert "allowed_openai_params" not in mk

    def test_manual_false_strips_and_warns(
        self, monkeypatch: pytest.MonkeyPatch, loguru_records: list[dict]
    ) -> None:
        """#1039 验收态 2：litellm 表 True 的 deepseek + 注册表 manual False →
        剥离 + reasoning_downgrade WARNING（覆盖向下生效）。"""
        from inkflow.infrastructure.agent.deepagents import harness

        monkeypatch.setattr(harness, "resolve_reasoning_manual", lambda _m: False)
        chat_cls = self._raw_build(harness, model=DEEPSEEK, effort="high")
        assert "reasoning_effort" not in (chat_cls.call_args[1].get("model_kwargs") or {})
        warns = [r for r in loguru_records if r["level"].name == "WARNING"]
        assert warns, "manual=False 剥离必须留痕"
        extra = warns[-1]["extra"]
        assert extra.get("message_key") == "log.check.reasoning_downgrade"
        assert (extra.get("params") or {}).get("reason") == "capability_unsupported"

    @pytest.mark.parametrize("effort", [None, "default"])
    def test_no_actionable_effort_skips_registry_lookup(
        self, monkeypatch: pytest.MonkeyPatch, effort: str | None
    ) -> None:
        """生产性能契约：档位不可行动（None/'default'）→ 绝不查注册表（构造点在
        每条 chat/写作链上都会走，避免无档位时的多余 DB 往返）。"""
        from inkflow.infrastructure.agent.deepagents import harness

        calls: list[str] = []
        monkeypatch.setattr(harness, "resolve_reasoning_manual", calls.append)
        with (
            mock.patch("inkflow.infrastructure.agent.deepagents.harness.ChatLiteLLM"),
            mock.patch(
                "inkflow.infrastructure.agent.deepagents.harness.create_deep_agent",
                return_value=mock.MagicMock(name="agent"),
            ),
        ):
            harness.build_deep_agent(
                model=DEEPSEEK,
                api_key="sk-test",
                base_url="https://x/v1",
                tools=[],
                system_prompt="p",
                reasoning_effort=effort,
            )
        assert calls == [], f"effort={effort!r} 不得触发注册表查询（多余 DB 往返）"

    def _raw_build(self, harness, *, model: str, effort: str):
        with (
            mock.patch("inkflow.infrastructure.agent.deepagents.harness.ChatLiteLLM") as chat_cls,
            mock.patch(
                "inkflow.infrastructure.agent.deepagents.harness.create_deep_agent",
                return_value=mock.MagicMock(name="agent"),
            ),
        ):
            harness.build_deep_agent(
                model=model,
                api_key="sk-test",
                base_url="https://x/v1",
                tools=[],
                system_prompt="p",
                reasoning_effort=effort,
            )
        return chat_cls


class TestLangchainClientManualOverride:
    """构造点 2：LangChainLLMClient._get_chat_model 同款消费注册表 manual。"""

    def _cfg(self, base_url: str) -> LLMProviderConfig:
        return LLMProviderConfig(
            provider="openai",
            api_key=ECHO_KEY,
            base_url=base_url,
            default_model="custom-q",
            max_retries=0,
            timeout=10,
        )

    def test_get_chat_model_looks_up_manual(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from inkflow.infrastructure.llm import langchain_client

        calls: list[str] = []
        monkeypatch.setattr(langchain_client, "resolve_reasoning_manual", calls.append)
        with mock.patch("inkflow.infrastructure.llm.langchain_client.ChatLiteLLM"):
            langchain_client.LangChainLLMClient()._get_chat_model(
                self._cfg("https://x/v1"), model_name="custom-q", reasoning_effort="high"
            )
        assert calls and calls[0].endswith("custom-q"), (
            f"必须以注册表模型全名查 manual，实得 {calls}"
        )

    def test_manual_true_injects_with_bypass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from inkflow.infrastructure.llm import langchain_client

        monkeypatch.setattr(langchain_client, "resolve_reasoning_manual", lambda _m: True)
        with mock.patch("inkflow.infrastructure.llm.langchain_client.ChatLiteLLM") as chat_cls:
            langchain_client.LangChainLLMClient()._get_chat_model(
                self._cfg("https://x/v1"), model_name="custom-q", reasoning_effort="high"
            )
        mk = chat_cls.call_args[1].get("model_kwargs") or {}
        assert mk.get("reasoning_effort") == "high"
        assert mk.get("allowed_openai_params") == ["reasoning_effort"]

    def test_manual_false_strips_and_warns(
        self, monkeypatch: pytest.MonkeyPatch, loguru_records: list[dict]
    ) -> None:
        from inkflow.infrastructure.llm import langchain_client

        monkeypatch.setattr(langchain_client, "resolve_reasoning_manual", lambda _m: False)
        with mock.patch("inkflow.infrastructure.llm.langchain_client.ChatLiteLLM") as chat_cls:
            langchain_client.LangChainLLMClient()._get_chat_model(
                self._cfg("https://x/v1"), model_name="custom-q", reasoning_effort="high"
            )
        assert "reasoning_effort" not in (chat_cls.call_args[1].get("model_kwargs") or {})
        warns = [r for r in loguru_records if r["level"].name == "WARNING"]
        assert warns
        assert warns[-1]["extra"].get("message_key") == "log.check.reasoning_downgrade"


# ════════════════ 契约 3：wire 级证据（Q2=A 自包含 echo server）════════════════


class _EchoHandler(BaseHTTPRequestHandler):
    """捕获请求 body 回确定性 OpenAI 兼容响应（零 key；#1044 wire 契约同款形态）。"""

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


async def _wire_via_client(
    echo_base: str, monkeypatch: pytest.MonkeyPatch, manual: bool | None
) -> dict:
    """经构造点 2 打 echo server（注册表替身），返回 wire body。"""
    from inkflow.infrastructure.llm import langchain_client
    from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

    monkeypatch.setattr(langchain_client, "resolve_reasoning_manual", lambda _m: manual)
    _CAPTURED.clear()
    chat = LangChainLLMClient()._get_chat_model(
        LLMProviderConfig(
            provider="openai",
            api_key=ECHO_KEY,
            base_url=echo_base,
            default_model="custom-q",
            max_retries=0,
            timeout=10,
        ),
        model_name="custom-q",
        reasoning_effort="high",
    )
    await chat.ainvoke([HumanMessage(content="hi")])
    assert _CAPTURED, "wire 请求未到达 echo server（SDK 本地拦截 = 断流缺陷）"
    return _CAPTURED[-1]


class TestManualOverrideWireEvidence:
    """#1039 验收「手动覆盖 → 请求体携带 reasoning_effort」的端到端 wire 证据。"""

    async def test_manual_true_reaches_wire(self, echo_base: str, monkeypatch) -> None:
        """修复前：决策点不查注册表 → 表 False 剥离 → wire 无思考键（RED FAIL）。"""
        body = await _wire_via_client(echo_base, monkeypatch, manual=True)
        assert body.get("reasoning_effort") == "high", (
            f"manual=True 必须使 wire 携带档位，实得 wire keys={sorted(body)}"
        )
        assert "allowed_openai_params" not in body, (
            "旁路参数仅供 litellm 本地校验，不得泄漏进请求体（probe V1 实证可剥除）"
        )

    async def test_manual_false_wire_clean_with_warning(
        self, echo_base: str, monkeypatch, loguru_records: list[dict]
    ) -> None:
        body = await _wire_via_client(echo_base, monkeypatch, manual=False)
        leaked = [key for key in REASONING_WIRE_KEYS if key in body]
        assert not leaked, f"manual=False 不得发送思考参数，实得 {leaked}"
        warns = [r for r in loguru_records if r["level"].name == "WARNING"]
        assert warns
        assert (warns[-1]["extra"].get("params") or {}).get("reason") == (
            "capability_unsupported"
        )

    async def test_manual_none_litellm_known_model_wire_ok(
        self, echo_base: str, monkeypatch
    ) -> None:
        """回归护栏：表 True（deepseek 方言）路径 manual=None → wire thinking 方言
        不破（#1044 契约不回退）。"""
        from inkflow.infrastructure.llm import langchain_client
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        monkeypatch.setattr(langchain_client, "resolve_reasoning_manual", lambda _m: None)
        _CAPTURED.clear()
        chat = LangChainLLMClient()._get_chat_model(
            LLMProviderConfig(
                provider="deepseek",
                api_key=ECHO_KEY,
                base_url=echo_base,
                default_model="deepseek-v4-flash",
                max_retries=0,
                timeout=10,
            ),
            model_name="deepseek-v4-flash",
            reasoning_effort="high",
        )
        await chat.ainvoke([HumanMessage(content="hi")])
        assert _CAPTURED[-1].get("thinking") == {"type": "enabled"}


# ════════════════ 发现①：trace 轨形式断言（#1045 闭合后锚定）════════════════


class TestTraceCollectNoneContentFormal1039:
    """#1039-①：consume_trace() 的 message_content 恒 str——补 #1045 未锁的
    tool-call-only（content=None）形态：trace 落库轨绝不存 None。"""

    async def test_none_content_trace_step_message_is_empty_str(self) -> None:
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        class _EndAgent:
            def __init__(self, output: object) -> None:
                self.output = output

            async def astream_events(self, inputs, version="v2", config=None):
                yield {"event": "on_chat_model_end", "data": {"output": self.output}}

        # 鸭子替身（AIMessage 类型层拒 content=None，真实 langchain-litellm 在
        # tool-call-only 时给 ""，但 _collect_model_end 契约是 getattr 鸭子读取——
        # None/未知形状必须防御归 ""，SimpleNamespace 直接锁收集函数本体）
        output = SimpleNamespace(
            content=None,
            tool_calls=[],
            response_metadata={},
        )
        svc = ChatAgentService(agent=_EndAgent(output), system_prompt="base")
        async for _ in svc.stream_events(prompt="hi", project_id="p1"):
            pass
        steps, final_content, _tokens = svc.consume_trace()
        assert len(steps) == 1
        assert isinstance(steps[0].message_content, str), (
            "tool-call-only end 的 message_content 必须是 str（None 污染 F47/F55 落库）"
        )
        assert steps[0].message_content == ""
        assert isinstance(final_content, str)

    def test_collect_model_end_direct_call_normalizes_block_list(self) -> None:
        """①形式断言核心：直接调用 _collect_model_end（不经 stream_events 流处理
        兜底），块列表 content → 收集的 AgentStep.message_content 恒 str 且不含
        thinking 文本、reasoning 走 additional_kwargs 保留。锁的是收集函数本体
        （#1045 既有用例经 stream 全链，此形为收集轨独立锚）。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        svc = ChatAgentService(agent=mock.MagicMock(name="agent"), system_prompt="base")
        output = AIMessage(
            content=[
                {"type": "thinking", "thinking": "思考B"},
                {"type": "text", "text": "正文B"},
            ],
            additional_kwargs={"reasoning_content": "思考B"},
        )
        svc._collect_model_end(output)
        steps, final_content, _tokens = svc.consume_trace()
        assert len(steps) == 1
        assert isinstance(steps[0].message_content, str)
        assert steps[0].message_content == "正文B"
        assert "思考B" not in steps[0].message_content
        assert steps[0].reasoning == "思考B"
        assert final_content == "正文B"


# ════════════════ 发现③：content_text 有意静默锁定（拍板 b）════════════════


class TestContentTextIntentionalSilence:
    """#1039-③(b)：非预期形状归 "" 是有意静默——行为锁定（不产 WARNING）+
    源码注释锚（防日后无痕翻转）。"""

    @pytest.mark.parametrize(
        "weird",
        [None, 123, 3.14, {"type": "image_url", "image_url": {"url": "x"}}, object()],
    )
    def test_unexpected_shape_returns_empty_without_log(
        self, weird: object, loguru_records: list[dict]
    ) -> None:
        from inkflow.infrastructure.llm.content_text import content_text

        assert content_text(weird) == ""
        assert not [r for r in loguru_records if r["level"].name == "WARNING"], (
            "有意静默：非预期形状归 "" 不发任何 WARNING（拍板 b）"
        )

    def test_source_annotates_intentional_silence(self) -> None:
        import inspect

        from inkflow.infrastructure.llm import content_text as module

        src = inspect.getsource(module)
        assert "Intentionally silent" in src, (
            "③(b) 拍板：fallback 必须带「Intentionally silent」注释锁定契约意图"
        )


class TestLlmProviderConfigUnchanged:
    """护栏：resolve_reasoning_manual 不污染 LLMProviderConfig 公共面（既有 8+ 处
    keyword 构造与全等断言零变化，本批零 schema 改动）。"""

    def test_dataclass_has_no_new_fields(self) -> None:
        import dataclasses

        names = {f.name for f in dataclasses.fields(LLMProviderConfig)}
        assert names == {
            "provider",
            "api_key",
            "base_url",
            "default_model",
            "models",
            "max_retries",
            "timeout",
        }


# ── config 单例污染护栏（#963 先例：写进程级单例必带恢复）──


@pytest.fixture(autouse=True)
def _restore_reasoning_config():
    saved = config.llm_reasoning_effort
    yield
    config.llm_reasoning_effort = saved
