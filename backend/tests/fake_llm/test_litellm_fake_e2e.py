"""#962 F59-M1 迁移批第一 RED 项（spec §5.1 fake 段 / §9.1 / §13 M1，ADR-047）：
fake server 全链路黑盒——ChatLiteLLM/LiteLLMEmbeddings 经真实 HTTP 打 fake
provider（openai/ 前缀 + api_base 兼容形态）跑通 chat / embedding 两面。

契约：
- FE1 chat：LangChainLLMClient(default_model="fake/<scene>") 经 fake provider 短接
  （get_provider_config("fake")，base_url=INKFLOW_LLM_BASE_URL）→ fake server 收到
  wire 请求（裸 model 名 + OpenAI 兼容形状）→ ChatResponse 内容/用量正确。
- FE2 retry 语义单层化：error-500 场景 wire 命中次数 == llm_max_retries+1
  （与既有 test_blackbox_security.TestRetryCount 同契约——迁移不得改变重试次数，
  双层叠加（tenacity × openai SDK num_retries）实证 5≠3，属迁移缺陷）。
- FE3 embedding：LiteLLMEmbeddings(model="openai/<id>", api_base=fake) →
  embed_query 打 /v1/embeddings，wire model 为**裸 id**（#428 剥前缀契约在
  litellm openai/ 路径自动保留）。
- FE4 harness：build_deep_agent(model="fake/correct", ...) → create_deep_agent
  经 ChatLiteLLM 打 fake server 完成一轮（agentic 面 fake 兼容）。

形态与 test_blackbox_security.py 一致：fake_llm fixture（真 uvicorn 端口）。
"""

from __future__ import annotations

import pytest

from inkflow.core.config import config
from inkflow.domain.ports.llm_client import ChatMessage

FAKE_PROV = "fake"


def _patch_fake(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    monkeypatch.setattr(config, "llm_base_url", base_url)
    monkeypatch.setattr(config, "llm_default_model", f"{FAKE_PROV}/correct")
    monkeypatch.setattr(config, "llm_max_retries", 3)
    monkeypatch.setattr(config, "llm_request_timeout", 30)


class TestFakeLitellmFullChain:
    """fake provider（ADR-047 测试缝）在 ChatLiteLLM 迁移后的全链路黑盒。"""

    @pytest.mark.asyncio
    async def test_fe1_chat_roundtrip(self, fake_llm, monkeypatch) -> None:
        """chat()：fake 短接 → wire OpenAI 兼容请求 → 确定性响应 + usage 归一。"""
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        _patch_fake(monkeypatch, fake_llm.base_url)
        client = LangChainLLMClient(default_model=f"{FAKE_PROV}/correct")

        response = await client.chat([ChatMessage(role="user", content="你好")])

        assert response.content == "这是确定性 fake 响应"
        # wire 契约：fake server 收到请求（脱敏面同款 state 记录）
        assert fake_llm.app.state.received_prompts, "fake server 应收到 wire 请求"
        # wire model 裸场景名（openai/ 前缀经 litellm 剥离，routing 场景
        # 「model.rsplit('/')[-1]」解析到 correct——fake provider 路由契约）
        # usage 归一（ChatLiteLLM response_metadata token_usage 为 Usage 对象，
        # _to_chat_response 必须兼容 .get 形态——dict 旧轨保留）
        assert response.token_usage is not None
        assert response.token_usage.total_tokens == 30

    @pytest.mark.asyncio
    async def test_fe2_retry_single_layer(self, fake_llm, monkeypatch) -> None:
        """error-500：wire 命中次数 == max_retries+1（迁移后仍单层，禁双层叠加）。"""
        from inkflow.domain.ports.llm_errors import LLMRequestError
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        monkeypatch.setattr(config, "llm_base_url", fake_llm.base_url)
        monkeypatch.setattr(config, "llm_max_retries", 2)
        client = LangChainLLMClient(default_model=f"{FAKE_PROV}/error-500")

        with pytest.raises(LLMRequestError):
            await client.chat([ChatMessage(role="user", content="hi")])

        counts = fake_llm.app.state.error_counts
        assert counts.get("error-500") == 3, (
            f"wire 尝试次数应为 首次+2 重试=3（单层），实际 {counts}"
        )

    @pytest.mark.asyncio
    async def test_fe3_embedding_roundtrip_bare_model(self, fake_llm) -> None:
        """LiteLLMEmbeddings：openai/ 前缀 + api_base → /v1/embeddings，wire 裸 id。"""
        from langchain_litellm import LiteLLMEmbeddings

        emb = LiteLLMEmbeddings(
            model="openai/embedding-3",
            api_key="placeholder-fake-key",
            api_base=fake_llm.base_url,
        )
        vec = emb.embed_query("测试文本")

        assert len(vec) == fake_llm.app.state.embedding_dim
        reqs = fake_llm.app.state.embedding_requests
        assert reqs, "fake server 应收到 embedding 请求"
        assert reqs[-1]["model"] == "embedding-3", (
            "#428 wire 裸 id 契约：litellm openai/ 路径应剥前缀"
        )

    @pytest.mark.asyncio
    async def test_fe4_deep_agent_roundtrip(self, fake_llm, monkeypatch) -> None:
        """harness 面：build_deep_agent(fake) → deepagents 循环打 fake server 出答。"""
        from langchain_core.messages import HumanMessage

        from inkflow.infrastructure.agent.deepagents.harness import build_deep_agent

        _patch_fake(monkeypatch, fake_llm.base_url)
        agent = build_deep_agent(
            model=f"{FAKE_PROV}/correct",
            api_key="placeholder-fake-key",
            base_url=fake_llm.base_url,
            tools=[],
            system_prompt="你是测试助手",
        )
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="你好")]},
            config={"configurable": {"thread_id": "f59-m1-fe4"}},
        )
        messages = result.get("messages", [])
        assert messages, "deep agent 经 fake server 应产出消息"
        last = messages[-1]
        content = last.content if isinstance(last.content, str) else str(last.content)
        assert "这是确定性 fake 响应" in content
