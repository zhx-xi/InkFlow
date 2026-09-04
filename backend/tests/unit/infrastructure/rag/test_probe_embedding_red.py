"""#328 RED 契约：reindex 空字符串探测 embedding 维度.

当前实现 `_probe_embedding_dimension_sync` 用 `embed_query("")` 探测维度，
zhipu embedding API 拒绝空 prompt（400 code 1213）→ reindex 失败。
修复：改用非空占位符（"0"）。本契约断言 probe 调用参数非空。

RED 阶段：实现传 "" → 断言 call.args[0] != "" FAIL。
GREEN 阶段：传 "0" → PASS。

依据: #328（0.8.0-rc2 修复批）；spec f14 §9。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore


@pytest.mark.asyncio
async def test_probe_embedding_dimension_uses_nonempty_query(tmp_path: Path) -> None:
    """#328: 维度探测的 embed_query 参数必须非空（空串被 zhipu 400 拒绝）.

    RED 形态：当前实现 embed_query("") → 断言参数非空 FAIL。
    """
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = [0.1] * 384
    store = LangChainVectorStore(
        persist_dir=tmp_path / "chroma",
        embeddings=mock_embeddings,
    )

    dim = await store.probe_embedding_dimension()

    assert dim == 384
    call = mock_embeddings.embed_query.call_args
    assert call is not None
    assert call.args[0] != "", "探测 embedding 维度不得使用空字符串（zhipu 400 code 1213）"


@pytest.mark.asyncio
async def test_probe_embedding_dimension_caches_result(tmp_path: Path) -> None:
    """#328 守护: 维度探测结果缓存到实例属性（第二次不重复 embed）."""
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = [0.1] * 384
    store = LangChainVectorStore(
        persist_dir=tmp_path / "chroma",
        embeddings=mock_embeddings,
    )

    first = await store.probe_embedding_dimension()
    second = await store.probe_embedding_dimension()

    assert first == second == 384
    assert mock_embeddings.embed_query.call_count == 1
