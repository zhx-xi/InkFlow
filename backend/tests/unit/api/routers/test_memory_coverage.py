"""Coverage backfill: memory PreferenceUpdate 校验分支（#521 契约）。

公开端点驱动：PATCH /api/v1/agent/preferences/{id}，body 中 pattern/value
为纯空白 → 422（memory.py 66/68 行）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from inkflow.api.app import app

client = TestClient(app)


def test_update_preference_blank_pattern_422() -> None:
    response = client.patch(
        "/api/v1/agent/preferences/12345678-1234-5678-1234-567812345678",
        json={"pattern": "   "},
    )

    assert response.status_code == 422
    assert any("pattern 不能为空" in err["msg"] for err in response.json()["detail"])


def test_update_preference_blank_value_422() -> None:
    response = client.patch(
        "/api/v1/agent/preferences/12345678-1234-5678-1234-567812345678",
        json={"value": "   "},
    )

    assert response.status_code == 422
    assert any("value 不能为空" in err["msg"] for err in response.json()["detail"])
