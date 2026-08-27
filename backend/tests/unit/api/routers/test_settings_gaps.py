"""#708 coverage 补测 鈥?settings 路由缺口分支（直接调用 endpoint / 工厂函数）。

被测模块: ``inkflow.api.routers.settings``
补齐缺口:
- LLMTestRequest.model 缺省 鈫?validate_model None 分支（95->96 + 96 行）
- ``_get_key_manager`` 工厂函数体（118 行）
- ``_resolve_probe_model`` 命中注册表 default_model / 回退全局默认（150->151 / 150->155）
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.api.routers import settings as settings_mod
from inkflow.domain.models.provider_config import ProviderConfig


class _FakeLLMClient:
    """chat 返回非 coroutine 鈫?router 跳过 await，直接走成功路径。"""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def chat(self, messages: object) -> str:
        self.messages = messages
        return "pong"


def test_llm_test_request_model_none_validator() -> None:
    """model 缺省 鈫?validate_model(None) 走 return None 分支。"""
    req = settings_mod.LLMTestRequest(provider="openai", model=None, api_key="k")
    assert req.model is None


def test_get_key_manager_constructs_api_key_manager(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """真实 _get_key_manager 工厂 鈫?构造 APIKeyManager（118 行）。"""
    monkeypatch.setattr(
        settings_mod,
        "config",
        SimpleNamespace(secret_key="test-key", data_dir=tmp_path),
        raising=False,
    )

    km = settings_mod._get_key_manager()

    from inkflow.infrastructure.llm.key_manager import APIKeyManager

    assert isinstance(km, APIKeyManager)


async def test_resolve_probe_model_uses_registered_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注册表条目含 default_model 鈫?直接返回（150->151）。"""
    svc = AsyncMock()
    svc.get_by_name = AsyncMock(
        return_value=ProviderConfig(id=1, name="openai", default_model="openai/gpt-4o")
    )
    monkeypatch.setattr(settings_mod, "get_provider_config_service", lambda db: svc, raising=False)

    model = await settings_mod._resolve_probe_model("openai", db=object())

    assert model == "openai/gpt-4o"
    svc.get_by_name.assert_awaited_once_with("openai")


async def test_resolve_probe_model_falls_back_to_global_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注册表无条目 鈫?回退 config.llm_default_model（150->155）。"""
    svc = AsyncMock()
    svc.get_by_name = AsyncMock(return_value=None)
    monkeypatch.setattr(settings_mod, "get_provider_config_service", lambda db: svc, raising=False)

    model = await settings_mod._resolve_probe_model("openai", db=object())

    assert model == settings_mod.config.llm_default_model


async def test_llm_test_connection_ok_with_fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """探测成功路径：缺省 model + fake client 鈫?200 ok:true。"""
    entry = ProviderConfig(id=1, name="openai", default_model="openai/gpt-4o")
    svc = AsyncMock()
    svc.get_by_name = AsyncMock(return_value=entry)
    monkeypatch.setattr(settings_mod, "get_provider_config_service", lambda db: svc, raising=False)
    fake = _FakeLLMClient()
    monkeypatch.setattr(settings_mod, "_get_llm_client", lambda *a, **kw: fake, raising=False)

    result = await settings_mod.test_llm_connection(
        data=settings_mod.LLMTestRequest(provider="openai", api_key="k"),
        db=object(),
    )

    assert result["ok"] is True
    assert result["model"] == "openai/gpt-4o"
    assert fake.messages[0].role == "user"
