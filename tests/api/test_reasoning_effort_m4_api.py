"""F59-M4 RED (#965): provider-configs models[] 手动思考标记回显（spec §3.4 / contract B8）。

契约（B8 ``_to_response``）:
- 注册表条目存有手动覆盖值（``supports_reasoning`` 非 None，true/false）→ 响应同键保留
  ``supports_reasoning``（同值），**并新增** ``supports_reasoning_manual``（= 原始存储值）。
- 未手动（``supports_reasoning`` 为 None）→ 探测链填充 ``supports_reasoning``（bool），
  **且响应不含** ``supports_reasoning_manual`` 键（向后兼容：既有 API 测试 payload 无该键，
  响应也不得新增）。

镜像 tests/api/test_reasoning_effort_api.py §6 的 mock 形态（同款 client fixture + ORM seed）。

RED 预期失败形态（当前实现）:
- ``_to_response`` 未新增手动标记键 → 读取 ``supports_reasoning_manual`` 抛 KeyError（B8 缺功能）。
- 未手动（m1）守护用例：当前实现本就只探测填充、无 manual 键 → PASS（刻意守护）。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.api.deps import get_db


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    """ASGI 客户端 + get_db → 测试内存库（镜像 test_reasoning_effort_api.py）。"""
    monkeypatch.delenv("INKFLOW_SERVER_TOKEN", raising=False)

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _seed_models(db_session):
    """seed 一个含手动/未手动两个形态的 provider 条目（m1 未手动，m2/m3 手动 true/false）。"""
    from inkflow.infrastructure.database.models.provider_config import ProviderConfigORM

    row = ProviderConfigORM(
        name="probe-test",
        base_url="https://x.example/v1",
        default_model="probe-test/m1",
        models=[
            {"id": "m1", "type": "chat", "roles": []},
            {"id": "m2", "type": "chat", "roles": [], "supports_reasoning": True},
            {"id": "m3", "type": "chat", "roles": [], "supports_reasoning": False},
        ],
    )
    db_session.add(row)
    return row


def _probe_by_manual(model_full, provider=None, manual=None) -> bool:
    """探针替身：手动值优先原样回显，未手动 → False（B8 契约面）。"""
    return bool(manual) if manual is not None else False


@pytest.mark.asyncio
class TestProviderConfigsManualMarkerEcho:
    """B8：手动覆盖值 → supports_reasoning + supports_reasoning_manual 双键同值回显。"""

    async def test_manual_true_emits_manual_marker(self, client, db_session, monkeypatch) -> None:
        """m2 手动 True → 响应含 supports_reasoning=True 且 supports_reasoning_manual=True。"""
        _seed_models(db_session)
        await db_session.commit()
        monkeypatch.setattr(
            "inkflow.infrastructure.llm.capability_probe.supports_reasoning_for_model",
            _probe_by_manual,
        )
        resp = await client.get("/api/v1/provider-configs")
        assert resp.status_code == 200
        item = next(i for i in resp.json()["items"] if i["name"] == "probe-test")
        by_id = {m["id"]: m for m in item["models"]}
        assert by_id["m2"]["supports_reasoning"] is True, "手动 True 原样回显"
        assert by_id["m2"]["supports_reasoning_manual"] is True, (
            f"手动 True 必须带 supports_reasoning_manual=True（B8），实得 {by_id['m2']!r}"
        )

    async def test_manual_false_emits_manual_marker(self, client, db_session, monkeypatch) -> None:
        """m3 手动 False → 响应含 supports_reasoning=False 且 supports_reasoning_manual=False。"""
        _seed_models(db_session)
        await db_session.commit()
        monkeypatch.setattr(
            "inkflow.infrastructure.llm.capability_probe.supports_reasoning_for_model",
            _probe_by_manual,
        )
        resp = await client.get("/api/v1/provider-configs")
        assert resp.status_code == 200
        item = next(i for i in resp.json()["items"] if i["name"] == "probe-test")
        by_id = {m["id"]: m for m in item["models"]}
        assert by_id["m3"]["supports_reasoning"] is False, "手动 False 原样回显"
        assert by_id["m3"]["supports_reasoning_manual"] is False, (
            f"手动 False 必须带 supports_reasoning_manual=False（B8），实得 {by_id['m3']!r}"
        )

    async def test_automated_value_omits_manual_marker(
        self, client, db_session, monkeypatch
    ) -> None:
        """m1 未手动 → 探测填充 supports_reasoning=bool；响应不含 supports_reasoning_manual 键。"""
        _seed_models(db_session)
        await db_session.commit()
        monkeypatch.setattr(
            "inkflow.infrastructure.llm.capability_probe.supports_reasoning_for_model",
            lambda model_full, provider=None, manual=None: False,
        )
        resp = await client.get("/api/v1/provider-configs")
        assert resp.status_code == 200
        item = next(i for i in resp.json()["items"] if i["name"] == "probe-test")
        by_id = {m["id"]: m for m in item["models"]}
        assert isinstance(by_id["m1"]["supports_reasoning"], bool), "自动探测须填充 bool"
        assert "supports_reasoning_manual" not in by_id["m1"], (
            f"未手动条目不得出现 supports_reasoning_manual 键（B8，向后兼容），实得 {by_id['m1']!r}"
        )
