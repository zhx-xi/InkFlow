"""F59-M5 (#966) 真实模型实证 ⑤（附带项）— zhipu embedding 维度稳定。

spec f59 §5.3 / §9.1 真实 AI ④（embedding 迁移后维度探测一致）/ §13 M5 行。
装配镜像 api/deps.py::_build_store（ADR-051 迁移形态）：LiteLLMEmbeddings +
openai/ 前缀 + api_base（zhipu 注册表 base_url，OpenAI 兼容 /embeddings 端点；
wire 裸模型 id 由 litellm 剥前缀，#428 契约）。LangChainVectorStore 运行时
embedding_dimension 探针取的正是 embed_query 的首批向量长度——本项断言维度
>0 且两次调用稳定，即与该探针记录同源。

断言：向量非空、维度 >0、两次调用维度一致。成本 2 次真实调用（文本极短）。
"""

from __future__ import annotations

import pytest
from langchain_litellm import LiteLLMEmbeddings

from inkflow.infrastructure.llm.provider_config import get_provider_config

pytestmark = pytest.mark.e2e_ai

EMBEDDING_MODEL_ID = "embedding-3"
TEXT = "InkFlow 真实嵌入维度探针"


@pytest.fixture(scope="module", autouse=True)
def _require_zhipu_key(zhipu_api_key: str) -> None:
    """module 级守门：无 zhipu key → 整模块 skip（缺 key 永远 skip 不 fail）。"""


def _build_embeddings(api_key: str) -> LiteLLMEmbeddings:
    """LiteLLMEmbeddings 装配镜像 deps._build_store（openai/ 前缀 + api_base）。"""
    base_url = get_provider_config("zhipu", api_key=api_key).base_url
    assert base_url, "zhipu 内置 base_url 不应为空（OpenAI 兼容端点）"
    return LiteLLMEmbeddings(
        model=f"openai/{EMBEDDING_MODEL_ID}",
        api_key=api_key,
        api_base=base_url,
    )


def test_zhipu_embedding_dimension_stable(zhipu_api_key: str) -> None:
    """同一短文本两次嵌入：向量非空且维度一致（>0）。"""
    embeddings = _build_embeddings(zhipu_api_key)

    first = embeddings.embed_query(TEXT)
    second = embeddings.embed_query(TEXT)

    assert isinstance(first, list) and len(first) > 0, "首次嵌入应返回非空向量"
    assert isinstance(second, list) and len(second) > 0, "二次嵌入应返回非空向量"
    assert len(second) == len(first), (
        f"两次嵌入维度必须稳定（首次 {len(first)}，二次 {len(second)}）"
    )
    assert any(value != 0.0 for value in first), "向量不应为全零"
