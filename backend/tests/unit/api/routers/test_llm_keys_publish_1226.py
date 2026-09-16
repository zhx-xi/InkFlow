"""RED 契约（#1226）：POST /settings/llm-keys 写成功后须发布 provider_config 变更事件。

缺陷（#1218 实测发现）
----------------------
``store_llm_key``（settings.py:167-180）只调 ``km.store()`` 写 keychain，**不发布任何
F23 数据面变更事件**——keychain 不是 ``provider_configs`` 表行，注册表行未变更故
``provider_config_service`` 的发布点不会触发；``settings`` 域事件只在
``SettingsService.update_settings`` 发布，不经此端点。

而模型就绪判据依赖「provider ∈ 已存 key 集合」：:

    # domain/services/model_readiness.py:105
    if provider not in saved_provider_names and not builtin.get(provider):
        return False

→ 「provider 已建但无 key」（reason=``no_key``）经 GUI/CLI 存 key 后，**无事件推送**，
已打开且停在 SetupGuide 的窗口收不到即时通知（只能等 #1218 的 5s 轮询兜底）。

修复契约（本契约锁定，RED 阶段未实现）
--------------------------------------
``store_llm_key`` 在 ``km.store()`` **成功之后**发布：

    await publish_change("provider_config", "update", <resource_id>, None)

- ``domain="provider_config"``：镜像 ``provider_config_service`` 的既有域选择，
  且前端已订阅该域（``App.tsx`` #1218：``['provider_config','settings']``）
- ``project_id=None``：全局域（spec §15.2.3）
- ``resource_id``：**provider 名**——keychain 无 DB id，provider 名即其唯一标识；
  镜像 ``settings`` 域用固定标识 ``SETTINGS_RESOURCE_ID="global"`` 的既有裁决
  （§15.6.2 失效矩阵：``provider_config`` 全域 FR，前端按 domain 过滤，
  resource_id 不参与路由 → 具体取值不影响失效行为）
- 写失败（``km.store`` 抛异常 → 端点 500）**不发布**（spec §15.3.3：写成功才发）

RED 形态
--------
GREEN 前 ``store_llm_key`` 无 publish 调用 → 记录型总线零事件 → ``assert`` FAIL。

测试约定
--------
TestClient + 最小 app（include_router + get_db override，镜像
test_llm_test_keychain_fallback_1152.py）；keychain 走真实 ``APIKeyManager``
落盘（tmp_path + monkeypatch ``settings_mod.config``）；总线替换为记录型替身
（镜像 test_data_change_event.py 的 ``_RecordingBus`` fixture）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkflow.api.deps import get_db
from inkflow.api.routers import settings as settings_mod
from inkflow.domain.models.data_change_event import DataChangeEvent

TEST_PROVIDER = "deepseek"
KEYS_PATH = "/api/v1/settings/llm-keys"

# 32 字节 hex → APIKeyManager 走 GCM 加密路径（非明文降级）
_SECRET_KEY = "11" * 32


class _RecordingBus:
    """记录型事件总线替身 —— 断言端点产出的信封字段。"""

    def __init__(self) -> None:
        self.events: list[DataChangeEvent] = []

    async def publish(self, event: DataChangeEvent) -> None:
        self.events.append(event)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _RecordingBus:
    """替换进程级总线单例为记录型替身。"""
    import inkflow.infrastructure.events.event_bus as bus_module

    bus = _RecordingBus()
    monkeypatch.setattr(bus_module, "_event_bus", bus, raising=False)
    return bus


@pytest.fixture
def keys_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> SimpleNamespace:
    """tmp data_dir 下的真实 keychain。"""
    monkeypatch.setattr(
        settings_mod,
        "config",
        SimpleNamespace(secret_key=_SECRET_KEY, data_dir=tmp_path),
        raising=False,
    )
    app = FastAPI()
    app.include_router(settings_mod.router)
    app.dependency_overrides[get_db] = lambda: object()  # 本端点不触碰 db
    return SimpleNamespace(client=TestClient(app))


# ── RED：存 key 成功 → 发布 provider_config 事件 ────────────────────────────


def test_store_llm_key_publishes_provider_config_event(
    keys_env: SimpleNamespace, recorder: _RecordingBus
) -> None:
    """F1：存 key 成功 → 发布恰好 1 条 provider_config 事件（域/op/资源/作用域正确）。

    RED：GREEN 前零发布 → ``recorder.events`` 为空 → FAIL。
    """
    resp = keys_env.client.post(KEYS_PATH, json={"provider": TEST_PROVIDER, "api_key": "sk-1226"})

    assert resp.status_code == 201, resp.text
    assert len(recorder.events) == 1, (
        f"存 key 成功应发布恰好 1 条事件（keychain 变更影响 readiness 判据），"
        f"实际 {len(recorder.events)} 条"
    )
    ev = recorder.events[0]
    assert ev.domain == "provider_config", f"域应为 provider_config，实际 {ev.domain!r}"
    assert ev.op == "update", f"op 应为 update，实际 {ev.op!r}"
    assert ev.resource_id == TEST_PROVIDER, (
        f"resource_id 应为 provider 名（keychain 无 DB id，名即其标识），实际 {ev.resource_id!r}"
    )
    assert ev.project_id is None, "provider_config 是全局域 → project_id 必须为 None"


def test_second_provider_key_publishes_distinct_resource_id(
    keys_env: SimpleNamespace, recorder: _RecordingBus
) -> None:
    """F2：不同 provider 存 key → resource_id 随 provider 变化（非硬编码常量）。"""
    keys_env.client.post(KEYS_PATH, json={"provider": "openai", "api_key": "sk-a"})
    keys_env.client.post(KEYS_PATH, json={"provider": TEST_PROVIDER, "api_key": "sk-b"})

    assert [ev.resource_id for ev in recorder.events] == ["openai", TEST_PROVIDER]
