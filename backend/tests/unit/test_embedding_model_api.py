"""#525/#526 RED 契约 — PUT /api/v1/vector/embedding-model 端点契约（#525 向量模型选择器）。

被测端点（extractions.py router 新增，RED 阶段未注册）:
- ``PUT /api/v1/vector/embedding-model`` —— body {provider, model_id}，切换
  激活 embedding 模型；成功 200 + {ok, provider, model_id}；provider 不存在
  → 404「Provider 不存在」；model_id 不在该 provider models → 404
  「模型不存在」；空串 / 缺字段 → 422（Pydantic 校验拒绝）。

Mock 策略（镜像 test_vector_status_api.py）:
- get_provider_config_service 为 GREEN 才引入的模块属性——用
  monkeypatch.setattr(extractions, "get_provider_config_service", fake,
  raising=False)（规则 1e 逃生门 #266 实测）: RED 阶段静默创建无害属性 →
  端点未注册 → 404 断言 FAIL（纯断言失败）；GREEN 阶段覆盖模块绑定名 →
  端点内模块全局名字查找命中。
- 端点须镜像 provider_configs.py _get_svc 模式: handler 内调用模块级
  get_provider_config_service(db)（同步函数，直接返回服务实例）。

RED 形态: 端点未注册 → 全部用例 404 断言 FAIL（detail="Not Found" 与契约
detail 不符 / 状态码非 200/422）。

依据: Issue #525 向量模型选择器；任务书 s8a red-backend-task.md 文件 1。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers import extractions
from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel

client = TestClient(app)


def _provider(name: str, models: list[ProviderModel]) -> ProviderConfig:
    """构造测试用 ProviderConfig 实体（id 固定，便于区分 provider）。"""
    return ProviderConfig(id=1, name=name, models=models)


def _patch_svc(monkeypatch: pytest.MonkeyPatch, svc: MagicMock) -> None:
    """把 svc 挂到 extractions.get_provider_config_service（RED 期属性不存在，静默创建）。"""
    monkeypatch.setattr(extractions, "get_provider_config_service", lambda db: svc, raising=False)


def test_set_embedding_model_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """契约: 目标 provider 含该模型 → 200 + {ok, provider, model_id} + 委托调用。"""
    svc = MagicMock()
    svc.get_by_name = AsyncMock(
        return_value=_provider("zhipu", [ProviderModel(id="embedding-3", type="chat")])
    )
    svc.set_embedding_model = AsyncMock(
        return_value=_provider("zhipu", [ProviderModel(id="embedding-3", type="embedding")])
    )
    _patch_svc(monkeypatch, svc)

    resp = client.put(
        "/api/v1/vector/embedding-model",
        json={"provider": "zhipu", "model_id": "embedding-3"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "provider": "zhipu", "model_id": "embedding-3"}
    svc.get_by_name.assert_awaited_once_with("zhipu")
    svc.set_embedding_model.assert_awaited_once_with("zhipu", "embedding-3")


def test_set_embedding_model_provider_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """契约: get_by_name 返回 None → 404「Provider 不存在」，且不触发切换。"""
    svc = MagicMock()
    svc.get_by_name = AsyncMock(return_value=None)
    svc.set_embedding_model = AsyncMock()
    _patch_svc(monkeypatch, svc)

    resp = client.put(
        "/api/v1/vector/embedding-model",
        json={"provider": "ghost", "model_id": "embedding-3"},
    )

    assert resp.status_code == 404
    assert "Provider 不存在" in resp.json()["detail"]
    svc.set_embedding_model.assert_not_awaited()


def test_set_embedding_model_model_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """契约: provider 存在但 models 不含 model_id → 404「模型不存在」。"""
    svc = MagicMock()
    svc.get_by_name = AsyncMock(
        return_value=_provider("zhipu", [ProviderModel(id="glm-4", type="chat")])
    )
    svc.set_embedding_model = AsyncMock()
    _patch_svc(monkeypatch, svc)

    resp = client.put(
        "/api/v1/vector/embedding-model",
        json={"provider": "zhipu", "model_id": "embedding-3"},
    )

    assert resp.status_code == 404
    assert "模型不存在" in resp.json()["detail"]
    svc.set_embedding_model.assert_not_awaited()


def test_set_embedding_model_blank_body() -> None:
    """契约: provider / model_id 空串 → 422（Pydantic 校验拒绝）。"""
    for body in (
        {"provider": "", "model_id": "embedding-3"},
        {"provider": "zhipu", "model_id": ""},
    ):
        resp = client.put("/api/v1/vector/embedding-model", json=body)
        assert resp.status_code == 422


def test_set_embedding_model_missing_field() -> None:
    """契约: 缺 model_id → 422（必填字段缺失）。"""
    resp = client.put("/api/v1/vector/embedding-model", json={"provider": "zhipu"})
    assert resp.status_code == 422
