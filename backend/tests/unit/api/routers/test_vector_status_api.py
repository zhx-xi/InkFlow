"""#276 S2c RAG 向量状态 API 契约测试（QA 报告 §4.2 契约 16-19/21）。

被测端点（extractions.py router 新增/改造，RED 阶段均未实现）:
- ``GET /api/v1/projects/{project_id}/vector/status`` —— 恒 200 语义，返回
  {configured_fp, indexed_fp, stale, reason, dimension_mismatch}（状态查询
  不应 404/500；未配置 embedding → 200 + reason="no_embedding"）
- ``POST /api/v1/projects/{project_id}/vector/reindex`` —— 前置单例刷新
  （await refresh_vector_store()，失败 → 500 且 reindex 拒绝执行），
  结果含 collections_recreated（维度不匹配重建分支）
- ``POST /api/v1/projects/{project_id}/vector/retrieve`` —— stale 期间
  200 + 旧向量结果（stale ≠ 错误，与 E12「异常→空结果」区分）

Mock 策略（镜像 test_extractions_api.py）:
- @patch("inkflow.api.routers.extractions.get_extraction_service") 替换
  Service 获取；被 await 的服务方法显式 AsyncMock
- get_vector_status / refresh_vector_store 为 GREEN 才存在的模块属性——
  用 monkeypatch.setattr(extractions, "get_vector_status", fake, raising=False)
  （规则 1e 逃生门 #266 实测）：RED 阶段静默创建无害属性 → 端点未注册 →
  404 断言 FAIL（纯断言失败）；GREEN 阶段覆盖模块绑定名 → 端点内模块全局
  名字查找命中

RED 形态: status 端点未注册 → 全部 status 用例 404 断言 FAIL；
reindex 端点已注册（既有）但未接 refresh/collections_recreated → 相应
断言 FAIL；既有 retrieve 用例（本文件无既有）不受影响。

依据: design/qa-rag-consistency-report.md §2.3/§2.4/§3.1/§4.2；Issue #276 范围 3/4。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers import extractions
from inkflow.domain.models.extraction import ReindexResult
from inkflow.domain.ports.extraction_errors import VectorStoreError
from inkflow.domain.ports.vector_store import EntityType, RetrievedEntity

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


def _reindex_result(**overrides: object) -> ReindexResult:
    """构造测试用 ReindexResult（GREEN 后含 collections_recreated 字段）。"""
    kwargs: dict[str, object] = {
        "project_id": PID,
        "entity_types": [EntityType.CHARACTER, EntityType.SETTING],
        "indexed": 5,
        "warnings": [],
        "collections_recreated": False,
    }
    kwargs.update(overrides)
    # collections_recreated 为 GREEN 新增字段——RED 阶段模型无此字段，
    # pydantic extra=ignore 静默丢弃 → model_dump 无键 → 用例 KeyError FAIL
    # （正确 RED：模型字段缺失）。
    return ReindexResult(**kwargs)  # type: ignore[arg-type]  # 测试 helper：**kwargs 注入 mock 依赖，真实签名由运行时校验


def _status_unknown() -> dict:
    """unknown 状态（存量用户升级后无指纹）。"""
    return {
        "configured_fp": {
            "schema_version": 1,
            "embedding": {
                "provider": "openai",
                "model_id": "text-embedding-3-small",
                "base_url": "https://api.test.example/v1",
                "dimension": 384,
            },
            "chunking": {
                "mode": "fixed",
                "chunk_size": 500,
                "overlap_ratio": 0.0,
                "chunker_version": 1,
            },
            "indexed_at": None,
            "status": "fresh",
        },
        "indexed_fp": None,
        "stale": True,
        "reason": "unknown",
        "dimension_mismatch": False,
    }


def _status_fresh() -> dict:
    """fresh 状态（指纹一致）。"""
    status = _status_unknown()
    status["indexed_fp"] = {
        "schema_version": 1,
        "embedding": {
            "provider": "openai",
            "model_id": "text-embedding-3-small",
            "base_url": "https://api.test.example/v1",
            "dimension": 384,
        },
        "chunking": {
            "mode": "fixed",
            "chunk_size": 500,
            "overlap_ratio": 0.0,
            "chunker_version": 1,
        },
        "indexed_at": "2026-08-12T08:00:00Z",
        "status": "fresh",
    }
    status["stale"] = False
    status["reason"] = None
    return status


def _status_stale_model_changed() -> dict:
    """stale 状态（模型已变更）。"""
    status = _status_fresh()
    status["configured_fp"]["embedding"]["model_id"] = "text-embedding-3-large"
    status["stale"] = True
    status["reason"] = "model_changed"
    return status


def _status_no_embedding() -> dict:
    """未配置 embedding 状态（200 语义，非错误）。"""
    return {
        "configured_fp": None,
        "indexed_fp": None,
        "stale": False,
        "reason": "no_embedding",
        "dimension_mismatch": False,
    }


# ── 契约 16: GET /vector/status 四态 + 200 语义 ──────────────────


def test_vector_status_unknown_returns_200_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """契约16: 无指纹（存量升级）→ 200 + stale=true + reason="unknown"。"""
    monkeypatch.setattr(
        extractions, "get_vector_status", AsyncMock(return_value=_status_unknown()), raising=False
    )
    resp = client.get(f"/api/v1/projects/{PID}/vector/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale"] is True
    assert body["reason"] == "unknown"
    assert body["indexed_fp"] is None
    assert body["dimension_mismatch"] is False


def test_vector_status_fresh_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """契约16: 指纹一致 → 200 + stale=false + reason=None。"""
    monkeypatch.setattr(
        extractions, "get_vector_status", AsyncMock(return_value=_status_fresh()), raising=False
    )
    resp = client.get(f"/api/v1/projects/{PID}/vector/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale"] is False
    assert body["reason"] is None
    assert body["indexed_fp"]["status"] == "fresh"


def test_vector_status_stale_model_changed_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """契约16: 配置变更 → 200 + stale=true + reason 细分（model_changed）。"""
    monkeypatch.setattr(
        extractions,
        "get_vector_status",
        AsyncMock(return_value=_status_stale_model_changed()),
        raising=False,
    )
    resp = client.get(f"/api/v1/projects/{PID}/vector/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale"] is True
    assert body["reason"] == "model_changed"
    assert body["configured_fp"]["embedding"]["model_id"] == "text-embedding-3-large"


def test_vector_status_no_embedding_returns_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """契约16: 未配置 embedding → 200 + reason="no_embedding"（状态查询不炸）。"""
    monkeypatch.setattr(
        extractions,
        "get_vector_status",
        AsyncMock(return_value=_status_no_embedding()),
        raising=False,
    )
    resp = client.get(f"/api/v1/projects/{PID}/vector/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured_fp"] is None
    assert body["stale"] is False
    assert body["reason"] == "no_embedding"


# ── 契约 17: reindex 联动（status stale → reindex → fresh；幂等）──


def test_reindex_flow_stale_to_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """契约17: 改配置后 status stale → reindex → status fresh（联动闭环）。"""
    responses = iter([_status_stale_model_changed(), _status_fresh()])
    monkeypatch.setattr(
        extractions,
        "get_vector_status",
        AsyncMock(side_effect=lambda pid, db=None: next(responses)),
        raising=False,
    )
    svc = MagicMock()
    svc.reindex = AsyncMock(
        return_value=_reindex_result(indexed=3, entity_types=[EntityType.CHARACTER])
    )

    with (
        patch("inkflow.api.routers.extractions.get_extraction_service", return_value=svc),
        patch("inkflow.api.routers.extractions.refresh_vector_store", new=AsyncMock()),
    ):
        # 1) 改配置后 → stale
        stale_resp = client.get(f"/api/v1/projects/{PID}/vector/status")
        assert stale_resp.json()["stale"] is True
        assert stale_resp.json()["reason"] == "model_changed"

        # 2) 重新向量化
        reindex_resp = client.post(
            f"/api/v1/projects/{PID}/vector/reindex",
            json={"entity_types": ["character"]},
        )
        assert reindex_resp.status_code == 200
        assert reindex_resp.json()["indexed"] == 3
        svc.reindex.assert_awaited_once()

        # 3) 完成后 → fresh
        fresh_resp = client.get(f"/api/v1/projects/{PID}/vector/status")
        assert fresh_resp.status_code == 200
        assert fresh_resp.json()["stale"] is False


def test_reindex_twice_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """契约17: 两次 reindex 幂等（indexed 数一致、无重复、不产生 stale 循环）。"""
    svc = MagicMock()
    svc.reindex = AsyncMock(return_value=_reindex_result())

    with (
        patch("inkflow.api.routers.extractions.get_extraction_service", return_value=svc),
        patch("inkflow.api.routers.extractions.refresh_vector_store", new=AsyncMock()),
    ):
        first = client.post(f"/api/v1/projects/{PID}/vector/reindex")
        second = client.post(f"/api/v1/projects/{PID}/vector/reindex")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["indexed"] == second.json()["indexed"] == 5
    assert svc.reindex.await_count == 2


# ── 契约 18: 维度不匹配 → collections_recreated=true ──────────────


def test_reindex_dimension_mismatch_reports_collections_recreated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """契约18: 维度不匹配走重建分支 → 响应含 collections_recreated=true。"""
    svc = MagicMock()
    svc.reindex = AsyncMock(
        return_value=_reindex_result(
            indexed=42,
            entity_types=[t for t in EntityType],
            collections_recreated=True,
        )
    )

    with (
        patch("inkflow.api.routers.extractions.get_extraction_service", return_value=svc),
        patch("inkflow.api.routers.extractions.refresh_vector_store", new=AsyncMock()),
    ):
        resp = client.post(f"/api/v1/projects/{PID}/vector/reindex")

    assert resp.status_code == 200
    body = resp.json()
    assert body["collections_recreated"] is True
    assert body["indexed"] == 42


# ── 契约 19: 失败路径（reindex 500 + status 仍 stale 防假成功）───


def test_reindex_failure_returns_500_and_status_stays_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """契约19: embedding 失败 → reindex 500 + status 仍 stale（commit-last 防假成功）。"""
    monkeypatch.setattr(
        extractions,
        "get_vector_status",
        AsyncMock(return_value=_status_stale_model_changed()),
        raising=False,
    )
    svc = MagicMock()
    svc.reindex = AsyncMock(side_effect=VectorStoreError("embedding api failed"))

    with (
        patch("inkflow.api.routers.extractions.get_extraction_service", return_value=svc),
        patch("inkflow.api.routers.extractions.refresh_vector_store", new=AsyncMock()),
    ):
        resp = client.post(f"/api/v1/projects/{PID}/vector/reindex")
        status_resp = client.get(f"/api/v1/projects/{PID}/vector/status")

    assert resp.status_code == 500
    assert status_resp.status_code == 200
    assert status_resp.json()["stale"] is True  # 失败不得提交指纹 → 仍 stale


# ── 契约 21: stale 期间语义检索 200 + 非空（stale ≠ 错误）────────


def test_retrieve_during_stale_returns_200_with_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """契约21: stale 期间 retrieve → 200 + 旧向量结果（不阻断写作，非 E12 空结果）。"""
    svc = MagicMock()
    svc.retrieve = AsyncMock(
        return_value=[
            RetrievedEntity(
                entity_id="ch1:0",
                entity_type="chapter_chunk",
                content="林晚走进青云城。",
                relevance_score=0.82,
                metadata={"project_id": str(PID)},
            )
        ]
    )

    with patch("inkflow.api.routers.extractions.get_extraction_service", return_value=svc):
        resp = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={"query": "青云城", "top_k": 5},
        )

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["relevance_score"] == 0.82
