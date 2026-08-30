"""Coverage backfill: chat_messages 路由错误分支（#770/#766 契约）。

公开端点驱动：
- PATCH /api/v1/chat/conversations/{id} body 空 → 422「至少提供一个字段」（221 行）
- POST /api/v1/chat/conversations/{bad}/restore 非法 UUID → 404（232-233 行）
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from inkflow.api.app import app

client = TestClient(app)


def test_patch_conversation_no_fields_422() -> None:
    response = client.patch(
        "/api/v1/chat/conversations/22345678-1234-5678-1234-567812345678",
        json={},
    )

    assert response.status_code == 422
    assert "至少提供一个" in response.json()["detail"]


def test_restore_conversation_invalid_uuid_404() -> None:
    response = client.post("/api/v1/chat/conversations/not-a-uuid/restore")

    assert response.status_code == 404
    assert "chat 会话不存在" in response.json()["detail"]
