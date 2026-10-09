"""#1545 提取两段式暂存 API 端点契约（RED）。

被测（GREEN 才实现）:
- ``POST /api/v1/projects/{project_id}/extractions/staging/{batch_id}/confirm``
  → 200 + ConfirmStagedResult；项目不存在 → 404「项目不存在」
- ``POST /api/v1/projects/{project_id}/extractions/staging/{batch_id}/cancel``
  → 200 + CancelStagedResult
- ``GET  /api/v1/projects/{project_id}/extractions/staging/{batch_id}``
  → 200 + StagedListResult

RED 预期: 路由尚不存在 → 404「Not Found」，与断言不符即 FAIL。

依据: specs/f14-extraction/spec.md §3.1 + §5.9（#1545）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.ports.character_errors import ProjectNotFoundError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
BASE = f"/api/v1/projects/{PID}/extractions/staging/ext-1"


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_confirm_success_returns_counts(mock_get_svc: MagicMock) -> None:
    """确认落库 → 200 + {batch_id, created, updated}。"""
    from inkflow.domain.models.extraction import ConfirmStagedResult

    svc = MagicMock()
    mock_get_svc.return_value = svc
    svc.confirm_staged = AsyncMock(
        return_value=ConfirmStagedResult(batch_id="ext-1", created=2, updated=1)
    )

    response = client.post(f"{BASE}/confirm")

    assert response.status_code == 200
    assert response.json() == {"batch_id": "ext-1", "created": 2, "updated": 1}
    svc.confirm_staged.assert_awaited_once()
    args, _ = svc.confirm_staged.await_args
    assert args[0] == PID
    assert args[1] == "ext-1"


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_cancel_success_returns_deleted(mock_get_svc: MagicMock) -> None:
    """取消 → 200 + {batch_id, deleted}。"""
    from inkflow.domain.models.extraction import CancelStagedResult

    svc = MagicMock()
    mock_get_svc.return_value = svc
    svc.cancel_staged = AsyncMock(return_value=CancelStagedResult(batch_id="ext-1", deleted=3))

    response = client.post(f"{BASE}/cancel")

    assert response.status_code == 200
    assert response.json() == {"batch_id": "ext-1", "deleted": 3}
    svc.cancel_staged.assert_awaited_once()


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_list_staged_returns_items(mock_get_svc: MagicMock) -> None:
    """读取本批暂存条目 → 200 + {batch_id, items}。"""
    from inkflow.domain.models.extraction import StagedEntry, StagedListResult

    svc = MagicMock()
    mock_get_svc.return_value = svc
    svc.list_staged = AsyncMock(
        return_value=StagedListResult(
            batch_id="ext-1",
            items=[
                StagedEntry(
                    entity_type="character",
                    action="create",
                    name="角色甲",
                    payload={"id": "c1", "name": "角色甲"},
                )
            ],
        )
    )

    response = client.get(BASE)

    assert response.status_code == 200
    body = response.json()
    assert body["batch_id"] == "ext-1"
    assert body["items"][0]["action"] == "create"
    assert body["items"][0]["name"] == "角色甲"


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_confirm_project_not_found_is_404(mock_get_svc: MagicMock) -> None:
    """项目不存在 → 404「项目不存在」。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    svc.confirm_staged = AsyncMock(side_effect=ProjectNotFoundError())

    response = client.post(f"{BASE}/confirm")

    assert response.status_code == 404
    assert response.json()["detail"] == "项目不存在"
