"""RED 契约（#1152 缺陷 3）：llm/test 的 api_key 可选 + keychain 回退语义。

缺陷（GUI 实测 2026-09-14）：引导页步骤 2「测试连接」恒 422 死路 ——
前端 ``SetupGuide.tsx:93-101`` 硬编码 ``api_key: ''``，后端
``LLMTestRequest.api_key`` 必填非空（settings.py:82-85,102-105），
且 ``test_llm_connection``(187-192) 无 keychain 回退。

修复方案 A（本契约锁定，RED 阶段未实现）：
1. ``LLMTestRequest.api_key: str | None = None``（缺省 = 用已存 key）
2. ``validate_api_key``：None 放行，非 None 仍 ``_validate_not_blank``
   （显式空串仍 422 —— 边界不放松）
3. ``test_llm_connection``：``api_key = data.api_key or _get_key_manager().get_key(provider)``；
   仍为空 → 200 ``{"ok": False, "message": <可读文案>}``（不是 422）

用例状态（RED 形态）：
- F1/F2/F5 → 当前 422 FAIL（api_key 仍必填）
- F3（显式空串仍 422）/ F4（显式 key 不读 keychain）→ 反例守护，当前 PASS

mock 策略：``TestClient`` + 最小 app（include_router + get_db override，镜像
test_chat_conversation_patch.py）；``_get_llm_client`` 为模块级全局名，patch
``settings_mod._get_llm_client``；keychain 走真实 ``APIKeyManager`` 落盘
（tmp_path，镜像 test_settings_gaps.py 的 ``config`` monkeypatch 法）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkflow.api.deps import get_db
from inkflow.api.routers import settings as settings_mod

TEST_PROVIDER = "deepseek"
TEST_MODEL = "deepseek/deepseek-chat"
TEST_PATH = "/api/v1/settings/llm/test"
KEYS_PATH = "/api/v1/settings/llm-keys"

# 32 字节 hex → APIKeyManager 走 GCM 加密路径（非明文降级）
_SECRET_KEY = "11" * 32


class _FakeLLMClient:
    """chat 返回非 coroutine → router 跳过 await，直接走成功路径。"""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def chat(self, messages: Any) -> str:
        self.messages = messages
        return "pong"


def _probe_body(**overrides: Any) -> dict[str, Any]:
    """llm/test 请求体；不带 api_key 字段 = 缺省（用已存 key）。"""
    body: dict[str, Any] = {"provider": TEST_PROVIDER, "model": TEST_MODEL}
    body.update(overrides)
    return body


@pytest.fixture
def llm_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> SimpleNamespace:
    """tmp data_dir 下的真实 keychain + 捕获 _get_llm_client 实参。"""
    monkeypatch.setattr(
        settings_mod,
        "config",
        SimpleNamespace(secret_key=_SECRET_KEY, data_dir=tmp_path),
        raising=False,
    )
    captured: dict[str, Any] = {}

    def _fake_get_llm_client(
        provider: str, model: str, api_key: str, *, base_url: str | None = None
    ) -> _FakeLLMClient:
        captured.update(provider=provider, model=model, api_key=api_key, base_url=base_url)
        return _FakeLLMClient()

    monkeypatch.setattr(settings_mod, "_get_llm_client", _fake_get_llm_client, raising=False)

    app = FastAPI()
    app.include_router(settings_mod.router)
    app.dependency_overrides[get_db] = lambda: object()  # model 恒显式 → db 不被触碰
    return SimpleNamespace(client=TestClient(app), captured=captured)


def _store_key(client: TestClient, api_key: str, provider: str = TEST_PROVIDER) -> None:
    resp = client.post(KEYS_PATH, json={"provider": provider, "api_key": api_key})
    assert resp.status_code == 201, resp.text


# ── RED：缺省 api_key → keychain 回退 ────────────────────────────────────────


def test_omitted_api_key_uses_stored_key(llm_env: SimpleNamespace) -> None:
    """F1：缺省 api_key + provider 有已存 key → 200 ok:true，且客户端拿到已存 key。"""
    _store_key(llm_env.client, "sk-stored")

    resp = llm_env.client.post(TEST_PATH, json=_probe_body())

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert llm_env.captured["api_key"] == "sk-stored"


def test_omitted_api_key_and_no_stored_key_is_ok_false_not_422(
    llm_env: SimpleNamespace,
) -> None:
    """F2：缺省 api_key + 无已存 key → 200 ok:false + 可读文案（关键：不是 422）。

    422 会让前端只拿到 pydantic detail 数组、拿不到可读 message（死路根因）。
    """
    resp = llm_env.client.post(TEST_PATH, json=_probe_body())

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert isinstance(body.get("message"), str)
    assert body["message"].strip()


def test_null_api_key_behaves_like_omitted(llm_env: SimpleNamespace) -> None:
    """F5：显式 JSON null 等同缺省 → 用已存 key。"""
    _store_key(llm_env.client, "sk-stored")

    resp = llm_env.client.post(TEST_PATH, json=_probe_body(api_key=None))

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert llm_env.captured["api_key"] == "sk-stored"


# ── 反例守护：边界不放松（当前应 PASS） ──────────────────────────────────────


def test_explicit_blank_api_key_still_422(llm_env: SimpleNamespace) -> None:
    """F3 守卫：显式 api_key:"" → 仍 422 且 loc 仍指向 body.api_key。

    「可选」只对 None/缺省生效；显式空串是客户端 bug，不得被静默吞成 keychain 回退。
    """
    resp = llm_env.client.post(TEST_PATH, json=_probe_body(api_key=""))

    assert resp.status_code == 422, resp.text
    loc = [err.get("loc", []) for err in resp.json()["detail"]]
    assert ["body", "api_key"] in loc


def test_explicit_api_key_skips_keychain(
    llm_env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F4 守卫：提供非空 api_key → 走原路径，绝不读 keychain（向后兼容）。"""
    read: list[str] = []

    class _SpyKeyManager:
        def get_key(self, provider: str) -> str:
            read.append(provider)
            return "sk-stored-should-not-win"

    monkeypatch.setattr(settings_mod, "_get_key_manager", lambda: _SpyKeyManager(), raising=False)

    resp = llm_env.client.post(TEST_PATH, json=_probe_body(api_key="sk-explicit"))

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert llm_env.captured["api_key"] == "sk-explicit"
    assert read == []
