"""#341 RAG 错误路径 API 测试（2026-08-14，从 test_extractions_api.py 拆分）。

背景：test_extractions_api.py 因追加 #341 契约超 900 行护栏（907>900），
本批 2 个 RAGUnavailableError 错误路径测试独立成文件（对齐 #281 拆分先例）。

覆盖（#341 修复目标）：
- reindex 前置 refresh_vector_store 抛 RAGUnavailableError
  → 500 + detail 含「未配置 embedding 模型」
- retrieve 服务装配（_get_svc 构造期 get_vector_store）抛 RAGUnavailableError
  → 500 + detail 不丢失
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.ports.extraction_errors import (
    RAGUnavailableError,
    VectorStoreError,
)
from inkflow.domain.services.extraction_service import ExtractionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")

client = TestClient(app)


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock ExtractionService（未赋值的方法 await 会 500——F4 4.1 陷阱）。"""
    svc = MagicMock(spec=ExtractionService)
    mock_get_svc.return_value = svc
    return svc


class TestVectorReindexRagUnavailable:
    """POST /api/v1/projects/{pid}/vector/reindex — 前置刷新抛 RAGUnavailableError。"""

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    @patch(
        "inkflow.api.routers.extractions.refresh_vector_store",
        side_effect=RAGUnavailableError(
            "未配置 embedding 模型，请先在 Provider 配置中添加 embedding 模型"
        ),
    )
    def test_reindex_refresh_unconfigured_embedding_500(
        self, mock_refresh: MagicMock, mock_get_svc: MagicMock
    ) -> None:
        """#341: 未配置 embedding 时 refresh_vector_store 抛错 → 500 且 detail 不丢失.

        端点前置刷新（L210）在 _run_service 之外——构造期 RAGUnavailableError
        冒泡成裸 500（detail=Internal Server Error）是 #330 修复不完整的残留；
        修复后应返回 500 + detail 含「未配置 embedding 模型」。
        """
        response = client.post(f"/api/v1/projects/{PID}/vector/reindex", json={})
        assert response.status_code == 500
        assert "未配置 embedding 模型" in response.json()["detail"]


class TestVectorRetrieveRagUnavailable:
    """POST /api/v1/projects/{pid}/vector/retrieve — 服务装配抛 RAGUnavailableError。"""

    @patch(
        "inkflow.api.routers.extractions.get_extraction_service",
        side_effect=RAGUnavailableError(
            "未配置 embedding 模型，请先在 Provider 配置中添加 embedding 模型"
        ),
    )
    def test_retrieve_unconfigured_embedding_500(self, mock_get_svc: MagicMock) -> None:
        """#341: 未配置 embedding 时服务装配抛错 → 500 且 detail 不丢失.

        _get_svc（构造期 get_vector_store 装配）在 _run_service 之外——
        RAGUnavailableError 冒泡成裸 500（detail=Internal Server Error）是
        #330 修复不完整的残留；修复后应返回 500 + detail 含「未配置
        embedding 模型」。
        """
        response = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={"query": "q"},
        )
        assert response.status_code == 500
        assert "未配置 embedding 模型" in response.json()["detail"]


class TestVectorRetrieveVectorStoreError:
    """POST /api/v1/projects/{pid}/vector/retrieve — 服务层抛 VectorStoreError（hnsw 段读取失败）
    → 500 + 清晰 detail（非吞空「内部错误（无详情）」，#823）。

    这是映射回归锁（_run_service L114-115 已映射 VectorStoreError→500+detail）；
    真正 RED 契约在 vector store/service 层（hnsw InternalError → VectorStoreError + 自愈重试）。
    """

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_retrieve_vector_store_error_clear_detail(self, mock_get_svc: MagicMock) -> None:
        """#823: 服务层抛 VectorStoreError（hnsw 段读取失败）→ 500 + detail 含诊断。"""
        svc = _mock_svc(mock_get_svc)
        svc.retrieve = AsyncMock(
            side_effect=VectorStoreError("向量检索失败：chromadb hnsw 段读取失败（character）")
        )
        response = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={"query": "q"},
        )
        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "chromadb hnsw" in detail
        assert "内部错误（无详情）" not in detail
