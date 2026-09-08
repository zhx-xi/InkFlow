"""F59-M2 RED (#963): SettingsService 思考档位双向同步桥（D-1 方案 A 拍板形态）。

契约（镜像 #987 方案 A：DB 为 GUI 持久化面，config 单例为装配读取点收口）:
1. ``update_settings(AppSettingsUpdate(default_reasoning_effort=X))`` → 落库 +
   ``config.llm_reasoning_effort = X`` 内存即时生效（GUI 改档 → 下次装配即用）。
2. ``get_settings()``：DB 未持久化该键 → 回退 config.llm_reasoning_effort 现值
   （config.json/env 启动源在 GUI 可见，两通道不脱节）；DB 有键 → DB 值优先
   （GUI 显式选择覆盖启动源）。
3. 非档位字段（theme 等）行为零变化（回归锁）。

直调形态说明：本文件全部经 service 协程 await（同线程），同时锚 func-cov
「新函数须被测试执行」门禁（TestClient 线程对其不可见，#496 先例）。

RED 预期失败形态:
- AppSettings 无 default_reasoning_effort 字段 → 构造 TypeError / AttributeError。
"""

from __future__ import annotations

import pytest

from inkflow.core.config import config
from inkflow.domain.models.settings import AppSettings, AppSettingsUpdate
from inkflow.domain.services.settings_service import SettingsService


class _FakeRepo:
    """内存 settings repo（镜像 SettingsRepositoryProtocol：get_all/set_many）。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get_all(self) -> dict[str, str]:
        return dict(self.store)

    async def set_many(self, data: dict[str, str]) -> None:
        self.store.update(data)


@pytest.fixture
def restore_config():
    original = config.llm_reasoning_effort
    yield
    config.llm_reasoning_effort = original


@pytest.fixture
def service():
    return SettingsService(repository=_FakeRepo())


class TestDefaultReasoningField:
    def test_appsettings_default_value(self) -> None:
        assert AppSettings().default_reasoning_effort == "default"

    def test_settings_key_enum_registered(self) -> None:
        """白名单枚举（SettingsKey 值 = 字段名惯例，同 default_words）。"""
        from inkflow.domain.models.settings import SettingsKey

        assert SettingsKey.DEFAULT_REASONING_EFFORT == "default_reasoning_effort"


class TestUpdateToConfigBridge:
    @pytest.mark.asyncio
    async def test_update_syncs_config_singleton(
        self, service, restore_config: None
    ) -> None:
        await service.update_settings(AppSettingsUpdate(default_reasoning_effort="high"))
        assert config.llm_reasoning_effort == "high", (
            "D-1 方案 A：PATCH settings 必须即时回灌 config 内存单例（装配读点收口）"
        )

    @pytest.mark.asyncio
    async def test_update_persists_to_db(self, service, restore_config: None) -> None:
        repo = service._repository
        await service.update_settings(AppSettingsUpdate(default_reasoning_effort="low"))
        assert repo.store["default_reasoning_effort"] == '"low"'

    @pytest.mark.asyncio
    async def test_other_fields_untouched(self, service, restore_config: None) -> None:
        """回归锁：theme 更新不得触碰 config.llm_reasoning_effort。"""
        config.llm_reasoning_effort = "medium"
        await service.update_settings(AppSettingsUpdate(theme="night"))
        assert config.llm_reasoning_effort == "medium"


class TestGetFromConfigFallback:
    @pytest.mark.asyncio
    async def test_db_missing_key_falls_back_to_config(self, service, restore_config: None) -> None:
        """启动源（config.json/env 设的 llm_reasoning_effort）在 GUI 回显可见。"""
        config.llm_reasoning_effort = "xhigh"
        settings = await service.get_settings()
        assert settings.default_reasoning_effort == "xhigh"

    @pytest.mark.asyncio
    async def test_db_key_wins_over_config(self, service, restore_config: None) -> None:
        """GUI 显式持久化后优先于启动源现值（两通道不互相打脸，DB=用户最后动作）。"""
        repo = service._repository
        await repo.set_many({"default_reasoning_effort": '"none"'})
        config.llm_reasoning_effort = "high"
        settings = await service.get_settings()
        assert settings.default_reasoning_effort == "none"
