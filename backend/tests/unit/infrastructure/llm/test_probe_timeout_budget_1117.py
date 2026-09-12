"""#1117 RED 契约：探测门禁的**请求超时预算**（e2e-models 用例 5 flaky 根治）。

背景（CI 实证）：
`tests/e2e/e2e-models.spec.ts:304` 用例 5「添加模型」在 `probe-gate-force` 强制保存后，
等 `model-row-{modelId}` 出现 15s 超时（`element(s) not found`，spec:337）。
同 commit 三结果（PR pass / main push fail / rerun pass）= 非确定性。

根因（file:line，已溯源）：
```
tests/e2e/e2e-models.spec.ts:332   getByTestId('probe-gate-force').click()
  → AddModelDialog.handleForceSave (AddModelDialog.tsx:154)  await onAdd(..., { force: true })
    → stores/models.addModel → PATCH /api/v1/provider-configs/{id}?force=true
      → ProviderConfigService.update → _gate_models(force=False) 首次探测
        → InfrastructureLLMProbe.probe_chat (probe.py:37)  真实网络请求
          → LangChainLLMClient._build_chat_model (langchain_client.py:255)
              "request_timeout": float(provider_cfg.timeout)   ← 默认 120s（provider_config.py:97）
              "max_retries": provider_cfg.max_retries          ← 默认 3（provider_config.py:96）
```

探测是**最小连通性探针**，却继承了 provider 的 120s **业务**超时；`120s × 3`
重试在图标「保存前门禁」这条**交互式**路径上根本不该被用满——这才是用例 5 的
15s 断言窗口被击穿的原因（不是渲染竞态：`ModelsPanel.handleSaved` 只在保存成功
后 `loadProviders()`，链路本身无竞态；落库只发生在 PATCH resolve 之后）。

契约（不改任何已有断言语义，只钉「探测请求超时预算」）：
1. `LangChainLLMClient` 构造函数新增**可选** `request_timeout` 参数（seconds, int|None）：
   - `None`（默认）→ 维持既有行为：用 `provider_cfg.timeout`（**向后兼容，零回归**）
   - 非 None → 覆盖 `_build_chat_model` 里写入 ChatLiteLLM 的 `request_timeout`
2. `InfrastructureLLMProbe` 构造 `LangChainLLMClient` 时传自己的预算常量
   `PROBE_REQUEST_TIMEOUT_S`，两条构造分支（有/无 base_url）都传——不分叉。
3. `probe_embedding` 经 `LiteLLMEmbeddings(timeout=...)` 钉同一预算。
4. 预算须显著小于 provider 默认业务超时 120s，且 <= 15s（交互式路径可接受上界）。

原则：每用例针对真实契约面 + 有断言；不写无断言 smoke。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _async_none():
    async def _coro() -> None:
        return None

    return _coro()


class TestProbeRequestTimeoutBudget:
    """探测请求超时预算（#1117：探针不得继承 120s 业务超时）。"""

    def test_budget_constant_within_interactive_bounds(self) -> None:
        """预算常量存在、为正、<= 15s 且小于 provider 默认业务超时。"""
        from inkflow.domain.models.provider_config import ProviderConfig
        from inkflow.infrastructure.llm.probe import PROBE_REQUEST_TIMEOUT_S

        assert PROBE_REQUEST_TIMEOUT_S > 0, "预算须为正数秒"
        assert PROBE_REQUEST_TIMEOUT_S <= 15, (
            "探测预算须 <= 15s：门禁是「保存前最小连通性探针」，其耗时直接占用用户/用例的等待窗口"
        )
        assert ProviderConfig.model_fields["timeout"].default > PROBE_REQUEST_TIMEOUT_S, (
            "探测预算必须小于 provider 业务超时默认值（二者语义不同，不得共用）"
        )

    def test_client_accepts_optional_request_timeout(self) -> None:
        """LangChainLLMClient 构造接受 request_timeout（默认 None = 既有行为）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        # 默认不传 → 属性为 None（向后兼容）
        assert LangChainLLMClient().request_timeout is None, (
            "默认须为 None，保持既有 provider_cfg.timeout 行为不变"
        )
        # 显式传入 → 生效
        assert LangChainLLMClient(request_timeout=7).request_timeout == 7

    def test_client_override_reaches_chat_model_kwargs(self) -> None:
        """request_timeout 覆盖值必须落进 ChatLiteLLM 的 request_timeout kwarg。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        cfg = MagicMock()
        cfg.default_model = "deepseek-chat"
        cfg.provider = "deepseek"
        cfg.base_url = None
        cfg.api_key = "k"
        cfg.max_retries = 3
        cfg.timeout = 120  # provider 业务超时（默认）
        cfg.supports_reasoning = None

        client = LangChainLLMClient(default_model="deepseek/deepseek-chat", request_timeout=9)
        with patch("inkflow.infrastructure.llm.langchain_client.ChatLiteLLM") as m_chat:
            client._get_chat_model(cfg, model_name="deepseek-chat")

        kwargs = m_chat.call_args.kwargs
        assert kwargs.get("request_timeout") == 9.0, (
            f"覆盖值须传递到 ChatLiteLLM；实得 {kwargs.get('request_timeout')!r}"
        )

    def test_client_without_override_keeps_provider_timeout(self) -> None:
        """不传 request_timeout → 仍用 provider_cfg.timeout（零回归）。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        cfg = MagicMock()
        cfg.default_model = "deepseek-chat"
        cfg.provider = "deepseek"
        cfg.base_url = None
        cfg.api_key = "k"
        cfg.max_retries = 3
        cfg.timeout = 77
        cfg.supports_reasoning = None

        client = LangChainLLMClient(default_model="deepseek/deepseek-chat")
        with patch("inkflow.infrastructure.llm.langchain_client.ChatLiteLLM") as m_chat:
            client._get_chat_model(cfg, model_name="deepseek-chat")

        assert m_chat.call_args.kwargs.get("request_timeout") == 77.0, (
            "无覆盖时须保持 provider_cfg.timeout 语义不变"
        )

    async def test_probe_chat_pins_budget_without_base_url(self) -> None:
        """probe_chat（无 base_url 分支）以预算构造 client。"""
        from inkflow.infrastructure.llm.probe import (
            PROBE_REQUEST_TIMEOUT_S,
            InfrastructureLLMProbe,
        )

        probe = InfrastructureLLMProbe()
        fake_client = MagicMock()
        fake_client.chat = MagicMock(return_value=_async_none())
        with patch(
            "inkflow.infrastructure.llm.langchain_client.LangChainLLMClient",
            return_value=fake_client,
        ) as m_cls:
            await probe.probe_chat("deepseek", "deepseek-chat", "k")

        assert m_cls.call_args.kwargs.get("request_timeout") == PROBE_REQUEST_TIMEOUT_S, (
            "未钉 budget → 继承 120s×3，门禁在保存路径上挂满 → #1117 用例 5 必红"
        )

    async def test_probe_chat_pins_budget_with_base_url(self) -> None:
        """probe_chat（有 base_url 分支）同样钉预算——两分支不得分叉。"""
        from inkflow.infrastructure.llm.probe import (
            PROBE_REQUEST_TIMEOUT_S,
            InfrastructureLLMProbe,
        )

        probe = InfrastructureLLMProbe()
        fake_client = MagicMock()
        fake_client.chat = MagicMock(return_value=_async_none())
        with patch(
            "inkflow.infrastructure.llm.langchain_client.LangChainLLMClient",
            return_value=fake_client,
        ) as m_cls:
            await probe.probe_chat("openai", "gpt-4o", "k", "https://x.test/v1")

        kwargs = m_cls.call_args.kwargs
        assert kwargs.get("request_timeout") == PROBE_REQUEST_TIMEOUT_S
        assert kwargs.get("openai_api_base") == "https://x.test/v1", "既有契约不得回归"
        assert kwargs.get("default_model") == "openai/gpt-4o", "既有契约不得回归"

    async def test_probe_embedding_pins_budget(self) -> None:
        """probe_embedding 经 LiteLLMEmbeddings(request_timeout=...) 钉同一预算。

        注：embedding 侧的字段名是 `request_timeout`（与 chat 侧同名），
        非 `timeout` —— 见 LiteLLMEmbeddings.model_fields。
        """
        from inkflow.infrastructure.llm.probe import (
            PROBE_REQUEST_TIMEOUT_S,
            InfrastructureLLMProbe,
        )

        probe = InfrastructureLLMProbe()
        fake_emb = MagicMock()
        fake_emb.embed_query = MagicMock(return_value=[0.1] * 8)
        with patch("langchain_litellm.LiteLLMEmbeddings", return_value=fake_emb) as m_cls:
            await probe.probe_embedding("zhipu", "embedding-3", "k", "https://z.test/v1")

        kwargs = m_cls.call_args.kwargs
        assert kwargs.get("request_timeout") == PROBE_REQUEST_TIMEOUT_S, (
            "embedding 探测同预算（不得分叉）"
        )
        assert kwargs.get("model") == "openai/embedding-3", "既有契约不得回归"

    async def test_probe_failure_still_raises(self) -> None:
        """预算不影响失败语义：仍上抛（service 转 422 + force 逃生门）。"""
        from inkflow.infrastructure.llm.probe import InfrastructureLLMProbe

        probe = InfrastructureLLMProbe()
        fake_client = MagicMock()
        fake_client.chat = MagicMock(side_effect=TimeoutError("probe timeout"))
        with (
            patch(
                "inkflow.infrastructure.llm.langchain_client.LangChainLLMClient",
                return_value=fake_client,
            ),
            pytest.raises(TimeoutError),
        ):
            await probe.probe_chat("deepseek", "deepseek-chat", "k")
