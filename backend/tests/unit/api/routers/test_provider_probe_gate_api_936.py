"""#936 C 项 RED 契约（API 层）：保存路径探测门禁 + force 透传。

契约（#936 spec §3.3）：
① `POST /api/v1/provider-configs`（create）与
   `PATCH /api/v1/provider-configs/{id}`（update）
   新增 query 参数 `force: bool = False`；
② `PUT /api/v1/vector/embedding-model` 同样 +`force`（激活路径同门禁）；
③ 探测失败 → 422（非 500），detail 含模型 id + 摘要；
④ `force=true` → 201/200 正常落库。

Mock 策略（镜像既有 test_embedding_model_api.py）：
- `get_provider_config_service` 为模块级函数 → monkeypatch 模块属性为
  `lambda db: svc`（RED 期端点未注入 force → 查询参数被忽略，断言 FAIL）。

RED 形态：
- create/update 的 `force` 查询参数未声明 → FastAPI 忽略之，探测仍抛 422，
  与「force 应放行」的期望冲突 → 断言 FAIL。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers import extractions, provider_configs
from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel
from inkflow.domain.ports.provider_config_errors import ProviderConfigServiceError

client = TestClient(app)

GATE_DETAIL = "模型 openai/gpt-4o 连接失败"


def _provider(name: str, models: list[ProviderModel], pid: int = 1) -> ProviderConfig:
    """构造测试用 ProviderConfig 实体。"""
    return ProviderConfig(id=pid, name=name, models=models)


def _patch_pc_svc(monkeypatch: pytest.MonkeyPatch, svc: MagicMock) -> None:
    """把 svc 挂到 provider_configs._get_svc（模块级函数，直接覆盖）。"""
    monkeypatch.setattr(provider_configs, "_get_svc", lambda db: svc)
    monkeypatch.setattr(
        provider_configs, "_get_key_manager", lambda: MagicMock(list_providers=lambda: [])
    )


class TestCreateForceParam:
    """契约①③④：create 端点的 force 透传与 422 语义。"""

    def test_r1_gate_failure_returns_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """【R】探测失败 → 422（非 500），detail 含模型 id。"""
        svc = MagicMock()
        svc.create = AsyncMock(side_effect=ProviderConfigServiceError(GATE_DETAIL))
        _patch_pc_svc(monkeypatch, svc)

        resp = client.post(
            "/api/v1/provider-configs",
            json={"name": "openai", "models": [{"id": "gpt-4o", "type": "chat"}]},
        )

        assert resp.status_code == 422, f"门禁失败须 422，实际 {resp.status_code}"
        assert "gpt-4o" in resp.json()["detail"]

    def test_r2_force_true_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """【R】`?force=true` → 透传 service.create(..., force=True)。

        RED 形态：端点未声明 force 查询参数 → 调用不带 force →
        `assert_awaited_once_with(..., force=True)` FAIL。
        """
        svc = MagicMock()
        svc.create = AsyncMock(return_value=_provider("openai", []))
        _patch_pc_svc(monkeypatch, svc)

        resp = client.post(
            "/api/v1/provider-configs?force=true",
            json={"name": "openai", "models": [{"id": "gpt-4o", "type": "chat"}]},
        )

        assert resp.status_code == 201
        assert svc.create.await_args.kwargs.get("force") is True, (
            "force=true 须透传 service（显式逃生门）"
        )

    def test_g1_default_force_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """【G】护栏：未传 force → 默认 False（门禁生效）。"""
        svc = MagicMock()
        svc.create = AsyncMock(return_value=_provider("openai", []))
        _patch_pc_svc(monkeypatch, svc)

        resp = client.post(
            "/api/v1/provider-configs",
            json={"name": "openai", "models": [{"id": "gpt-4o", "type": "chat"}]},
        )

        assert resp.status_code == 201
        assert svc.create.await_args.kwargs.get("force", False) is False


class TestUpdateForceParam:
    """契约①：update 端点 force 透传。"""

    def test_r3_update_force_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """【R】PATCH `?force=true` → 透传 service.update(..., force=True)。"""
        svc = MagicMock()
        svc.update = AsyncMock(return_value=_provider("openai", []))
        _patch_pc_svc(monkeypatch, svc)

        resp = client.patch(
            "/api/v1/provider-configs/1?force=true",
            json={"models": [{"id": "gpt-4o", "type": "chat"}]},
        )

        assert resp.status_code == 200
        assert svc.update.await_args.kwargs.get("force") is True

    def test_r4_update_gate_failure_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """【R】update 探测失败 → 422。"""
        svc = MagicMock()
        svc.update = AsyncMock(side_effect=ProviderConfigServiceError(GATE_DETAIL))
        _patch_pc_svc(monkeypatch, svc)

        resp = client.patch(
            "/api/v1/provider-configs/1",
            json={"models": [{"id": "gpt-4o", "type": "chat"}]},
        )

        assert resp.status_code == 422


class TestEmbeddingModelForceParam:
    """契约②：PUT /vector/embedding-model 的 force 透传。"""

    def test_r5_embedding_force_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """【R】`?force=true` → 透传 svc.set_embedding_model(..., force=True)。"""
        svc = MagicMock()
        svc.get_by_name = AsyncMock(
            return_value=_provider("zhipu", [ProviderModel(id="embedding-3", type="chat")])
        )
        svc.set_embedding_model = AsyncMock(
            return_value=_provider("zhipu", [ProviderModel(id="embedding-3", type="embedding")])
        )
        monkeypatch.setattr(
            extractions, "get_provider_config_service", lambda db: svc, raising=False
        )

        resp = client.put(
            "/api/v1/vector/embedding-model?force=true",
            json={"provider": "zhipu", "model_id": "embedding-3"},
        )

        assert resp.status_code == 200
        assert svc.set_embedding_model.await_args.kwargs.get("force") is True

    def test_g2_embedding_default_force_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """【G】护栏：未传 force → 默认 False。"""
        svc = MagicMock()
        svc.get_by_name = AsyncMock(
            return_value=_provider("zhipu", [ProviderModel(id="embedding-3", type="chat")])
        )
        svc.set_embedding_model = AsyncMock(
            return_value=_provider("zhipu", [ProviderModel(id="embedding-3", type="embedding")])
        )
        monkeypatch.setattr(
            extractions, "get_provider_config_service", lambda db: svc, raising=False
        )

        resp = client.put(
            "/api/v1/vector/embedding-model",
            json={"provider": "zhipu", "model_id": "embedding-3"},
        )

        assert resp.status_code == 200
        assert svc.set_embedding_model.await_args.kwargs.get("force", False) is False
