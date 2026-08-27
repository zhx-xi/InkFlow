"""#708 coverage 补测 鈥?provider_configs 路由缺口分支（直接调用 endpoint，稳定行级追踪）。

被测模块: ``inkflow.api.routers.provider_configs``
补齐缺口（来自 CI 四份 coverage 合并 artifact）:
- list/create/get/update 的 ``_get_key_manager()`` / ``_to_response`` 调用行（138/153/202/215）
- delete 内置 provider 鈫?409 与普通 provider 鈫?服务删除（227-228 + 两分支）
- discover_models 非 2xx 与未识别 data/models 格式（179-180/189-190 + 两分支）
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from inkflow.api.routers import provider_configs as pc
from inkflow.domain.models.provider_config import (
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigUpdate,
)


def _provider(name: str = "my-provider") -> ProviderConfig:
    """构造最小 ProviderConfig 实体（key_saved 计算依赖 name）。"""
    return ProviderConfig(id=1, name=name, base_url="", default_model=f"{name}/m", models=[])


class _FakeKeyManager:
    """key_saved 计算的 fake：list_providers 返回预置 provider 名列表。"""

    def __init__(self, providers: list[str] | None = None) -> None:
        self._providers = list(providers or [])

    def list_providers(self) -> list[str]:
        return list(self._providers)


def _patch_svc(monkeypatch: pytest.MonkeyPatch, svc: AsyncMock) -> None:
    """把模块级 _get_svc 工厂替换为返回给定 svc。"""
    monkeypatch.setattr(pc, "_get_svc", lambda db: svc, raising=False)


def _patch_km(
    monkeypatch: pytest.MonkeyPatch, providers: list[str] | None = None
) -> _FakeKeyManager:
    """把模块级 _get_key_manager 替换为 fake，并返回 fake 供断言。"""
    fake = _FakeKeyManager(providers)
    monkeypatch.setattr(pc, "_get_key_manager", lambda: fake, raising=False)
    return fake


async def test_list_covers_key_manager_line_and_key_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    """list 端点 鈫?覆盖 ``key_manager = _get_key_manager()`` 行 + key_saved 计算。"""
    svc = AsyncMock()
    svc.list = AsyncMock(return_value=[_provider("openai")])
    _patch_svc(monkeypatch, svc)
    fake = _patch_km(monkeypatch, ["openai"])

    result = await pc.list_provider_configs(db=object())

    assert result["total"] == 1
    assert result["items"][0]["key_saved"] is True
    assert fake.list_providers() == ["openai"]


async def test_create_covers_to_response_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """create 端点 鈫?覆盖 ``return _to_response(pc, _get_key_manager())`` 行。"""
    svc = AsyncMock()
    svc.create = AsyncMock(return_value=_provider("my"))
    _patch_svc(monkeypatch, svc)
    _patch_km(monkeypatch)

    result = await pc.create_provider_config(data=ProviderConfigCreate(name="my"), db=object())

    assert result["name"] == "my"
    svc.create.assert_awaited_once()


async def test_get_covers_to_response_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """get 端点 鈫?覆盖 ``return _to_response(pc, _get_key_manager())`` 行。"""
    svc = AsyncMock()
    svc.get = AsyncMock(return_value=_provider("my"))
    _patch_svc(monkeypatch, svc)
    _patch_km(monkeypatch)

    result = await pc.get_provider_config(provider_config_id="1", db=object())

    assert result["id"] == 1
    svc.get.assert_awaited_once_with(1)


async def test_update_covers_to_response_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """update 端点 鈫?覆盖 ``return _to_response(pc, _get_key_manager())`` 行。"""
    svc = AsyncMock()
    svc.update = AsyncMock(return_value=_provider("my"))
    _patch_svc(monkeypatch, svc)
    _patch_km(monkeypatch)

    result = await pc.update_provider_config(
        provider_config_id="1", data=ProviderConfigUpdate(name="my"), db=object()
    )

    assert result["name"] == "my"
    svc.update.assert_awaited_once()


async def test_delete_builtin_provider_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """删除内置 provider（openai）鈫?409，且不调用 svc.delete。"""
    svc = AsyncMock()
    svc.get = AsyncMock(return_value=_provider("openai"))
    svc.delete = AsyncMock(return_value=None)
    _patch_svc(monkeypatch, svc)
    _patch_km(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await pc.delete_provider_config(provider_config_id="1", db=object())

    assert exc.value.status_code == 409
    svc.delete.assert_not_awaited()


async def test_delete_non_builtin_calls_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """删除普通 provider 鈫?227 False 分支，调用 svc.delete(pid)。"""
    svc = AsyncMock()
    svc.get = AsyncMock(return_value=_provider("my"))
    svc.delete = AsyncMock(return_value=None)
    _patch_svc(monkeypatch, svc)
    _patch_km(monkeypatch)

    result = await pc.delete_provider_config(provider_config_id="1", db=object())

    assert result is None
    svc.delete.assert_awaited_once_with(1)


class _FakeAsyncClient:
    """httpx.AsyncClient 替身：async context manager + get() 返回预置响应。"""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.url: str | None = None
        self.headers: dict | None = None

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, headers: dict | None = None) -> httpx.Response:
        self.url = url
        self.headers = headers
        return self._response


async def test_discover_models_upstream_5xx_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上游返回非 2xx 鈫?200 + ok:false（178->179 分支 + 179-180 行）。"""
    fake = _FakeAsyncClient(httpx.Response(500, json={}))
    monkeypatch.setattr(pc.httpx, "AsyncClient", lambda **kw: fake, raising=False)

    result = await pc.discover_models(pc.ModelDiscoveryRequest(base_url="https://example.test/v1"))

    assert result["ok"] is False
    assert "HTTP 500" in result["message"]
    assert fake.url == "https://example.test/v1/models"


async def test_discover_models_unrecognized_format_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2xx 但 data/models 格式未识别 鈫?200 + ok:false（187->189 分支 + 189-190 行）。"""
    fake = _FakeAsyncClient(httpx.Response(200, json={"data": "not-a-list"}))
    monkeypatch.setattr(pc.httpx, "AsyncClient", lambda **kw: fake, raising=False)

    result = await pc.discover_models(pc.ModelDiscoveryRequest(base_url="https://example.test/v1"))

    assert result["ok"] is False
    assert "未找到模型列表" in result["message"]
