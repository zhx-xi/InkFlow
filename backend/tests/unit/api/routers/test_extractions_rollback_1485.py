"""#1485 批次回滚 API 端点契约（RED）。

被测（GREEN 才实现）: ``POST /api/v1/projects/{project_id}/extractions/rollback``
（body ``{batch_id}`` → 200 + RollbackResult；空白 → 422；项目不存在 → 404）。

RED 预期: 路由尚不存在 → 全部返回 404「Not Found」，与断言不符即 FAIL。

依据: specs/f14-extraction/spec.md §3.1 + §5.8.5 + §7（#1485）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.ports.character_errors import ProjectNotFoundError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
URL = f"/api/v1/projects/{PID}/extractions/rollback"


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_rollback_success_returns_deleted_count(mock_get_svc: MagicMock) -> None:
    """成功回滚 → 200 + {batch_id, deleted, warnings}。"""
    from inkflow.domain.models.extraction import RollbackResult

    svc = MagicMock()
    mock_get_svc.return_value = svc
    svc.rollback_batch = AsyncMock(
        return_value=RollbackResult(batch_id="ext-1", deleted=3, warnings=["已更新条目不回滚"])
    )

    response = client.post(URL, json={"batch_id": "ext-1"})

    assert response.status_code == 200
    assert response.json() == {
        "batch_id": "ext-1",
        "deleted": 3,
        "warnings": ["已更新条目不回滚"],
    }
    svc.rollback_batch.assert_awaited_once()
    args, _ = svc.rollback_batch.await_args
    assert args[0] == PID
    assert args[1] == "ext-1"


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_rollback_blank_batch_id_is_422(mock_get_svc: MagicMock) -> None:
    """空白 batch_id → 422（Pydantic 校验）。"""
    mock_get_svc.return_value = MagicMock()

    response = client.post(URL, json={"batch_id": "   "})

    assert response.status_code == 422


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_rollback_project_not_found_is_404(mock_get_svc: MagicMock) -> None:
    """项目不存在 → 404「项目不存在」。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    svc.rollback_batch = AsyncMock(side_effect=ProjectNotFoundError())

    response = client.post(URL, json={"batch_id": "ext-1"})

    assert response.status_code == 404
    assert response.json()["detail"] == "项目不存在"
