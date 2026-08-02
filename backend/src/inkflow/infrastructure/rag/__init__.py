"""RAG 基础设施包 — ADR-013 首次落地（LangChain Chroma + 本地 Embedding）。

实现 ``domain/ports/vector_store.py`` 定义的 ``VectorStoreProtocol``，
领域层不感知本包实现细节（ADR-002/015）。
"""

from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore

__all__ = ["LangChainVectorStore"]
