"""#1581 暂存批次列表 + 条目级确认/丢弃 API 契约（RED）。

被测（GREEN 才实现）:
- ``GET    /api/v1/projects/{pid}/extractions/staging``
  → 200 + ``{"batches": [{batch_id, type, created_at, item_count}]}``（**契约冻结**，新→旧）
- ``POST   /api/v1/projects/{pid}/extractions/staging/{batch_id}/items/{item_id}/confirm``
  → 200 + ``{item_id, event_id}``（body ``{time_value, time_unit}``）
- ``DELETE /api/v1/projects/{pid}/extractions/staging/{batch_id}/items/{item_id}``
  → 200 + ``{deleted}``

RED 预期: 路由尚不存在 → 404「Not Found」，与断言不符即 FAIL。

依据: specs/f14-extraction/spec.md §5.9（#1581）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.extraction import StagingBatch, StagingBatchList
from inkflow.domain.ports.character_errors import ProjectNotFoundError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
BATCH = "ext-1581abc"
ITEM = 42
BASE = f"/api/v1/projects/{PID}/extractions/staging"


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_list_staging_batches_frozen_shape(mock_get_svc: MagicMock) -> None:
    """批次列表 → 200 + 冻结形状 {batches:[{batch_id,type,created_at,item_count}]}。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    svc.list_staging_batches = AsyncMock(
        return_value=StagingBatchList(
            batches=[
                StagingBatch(
                    batch_id=BATCH,
                    type="timeline",
                    created_at="2026-10-11T03:00:00Z",
                    item_count=7,
                )
            ]
        )
    )

    response = client.get(BASE)

    assert response.status_code == 200
    body = response.json()
    assert list(body.keys()) == ["batches"]
    assert body["batches"][0] == {
        "batch_id": BATCH,
        "type": "timeline",
        "created_at": "2026-10-11T03:00:00Z",
        "item_count": 7,
    }
    svc.list_staging_batches.assert_awaited_once()
    args, _ = svc.list_staging_batches.await_args
    assert args[0] == PID


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_confirm_staged_item_passes_time_override(mock_get_svc: MagicMock) -> None:
    """条目确认 → 200 + {item_id, event_id}；时间覆盖透传服务层。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    event_id = "11111111-2222-4333-8444-555555555555"
    svc.confirm_staged_item = AsyncMock(return_value={"item_id": ITEM, "event_id": event_id})

    response = client.post(
        f"{BASE}/{BATCH}/items/{ITEM}/confirm",
        json={"time_value": 3.0, "time_unit": "年"},
    )

    assert response.status_code == 200
    assert response.json() == {"item_id": ITEM, "event_id": event_id}
    _, kwargs = svc.confirm_staged_item.await_args
    assert kwargs["time_value"] == 3.0
    assert kwargs["time_unit"] == "年"


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_confirm_staged_item_requires_time_value(mock_get_svc: MagicMock) -> None:
    """确认**强制**带时间（f12 §2.9 D3）——缺 time_value → 422，不触达服务层。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    svc.confirm_staged_item = AsyncMock()

    response = client.post(f"{BASE}/{BATCH}/items/{ITEM}/confirm", json={})

    assert response.status_code == 422
    svc.confirm_staged_item.assert_not_awaited()


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_discard_staged_item_returns_deleted(mock_get_svc: MagicMock) -> None:
    """条目丢弃 → 200 + {deleted}（幂等；不存在 → 0）。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    svc.discard_staged_item = AsyncMock(return_value={"deleted": 1})

    response = client.delete(f"{BASE}/{BATCH}/items/{ITEM}")

    assert response.status_code == 200
    assert response.json() == {"deleted": 1}


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_list_staging_batches_project_not_found_is_404(mock_get_svc: MagicMock) -> None:
    """项目不存在 → 404「项目不存在」（同 rollback 口径）。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    svc.list_staging_batches = AsyncMock(side_effect=ProjectNotFoundError())

    response = client.get(BASE)

    assert response.status_code == 404
    assert response.json()["detail"] == "项目不存在"


@patch("inkflow.api.routers.extractions.get_extraction_service")
def test_discard_staged_item_project_not_found_is_404(mock_get_svc: MagicMock) -> None:
    """条目丢弃同样校验项目存在 → 404。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    svc.discard_staged_item = AsyncMock(side_effect=ProjectNotFoundError())

    response = client.delete(f"{BASE}/{BATCH}/items/{ITEM}")

    assert response.status_code == 404
    assert response.json()["detail"] == "项目不存在"
