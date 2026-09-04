"""#106 get_provider_config 解析改造 + key 回退单元测试（RED 批，P2 改造）。

对象: ``inkflow.infrastructure.llm.provider_config.get_provider_config``
（模块已存在但行为未改造 → 本文件可正常收集，RED 形态为 fixture
patch 的 AttributeError / 断言失败 / 意外 ValueError，非收集错误）。

改造契约（spec §8.2②「provider 解析改造 + key 回退」+ §8.7 ADR「key 回退 =
provider_config 层」）:

api_key 解析优先级（高 → 低）:
  1. 显式传入 ``api_key`` 参数 → 直接使用（连通探测等按请求携带密钥场景）
  2. 环境变量 ``INKFLOW_{PROVIDER.upper()}_API_KEY``（调用时读 os.environ）
  3. ``APIKeyManager.load(provider)`` 已存 key（data_dir/keys/{provider}.json）:
     构造 ``APIKeyManager(secret_key=config.secret_key,
     storage_dir=config.data_dir / "keys")``（镜像 settings.py _get_key_manager）；
     load 抛 FileNotFoundError（无已存 key）→ 继续回退
  4. 内置占位（ollama 既有行为: _BUILTIN_PROVIDERS["ollama"]="ollama"，
     本地运行无需真实 key）→ 否则 ValueError，文案包含
     **"API key not configured"**（既有文案前缀，不得变更）

base_url / default_model 解析（spec §8.2②「先查注册表」）:
  - 注册表命中（``ProviderConfigService.get_by_name(provider)`` 返回实体）→
    base_url/default_model 取注册表值
  - 注册表未命中（get_by_name 返回 None）→ 回退内置硬编码
    （_PROVIDER_BASE_URLS + config.model_routing / config.llm_default_model，
    兼容既有调用，spec「注册表无则回退内置硬编码」）

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

- patch 目标 1（注册表 seam）: provider_config.py 顶部必须
  ``from inkflow.domain.services.provider_config_service import
  ProviderConfigService``（模块级名字暴露），get_provider_config 内部经
  ``ProviderConfigService(...)`` 构造 service（repository 注入方式 GREEN 自选，
  可复用 core.database 的 async_session_factory）并调用
  ``await svc.get_by_name(provider)``。测试
  ``patch("inkflow.infrastructure.llm.provider_config.ProviderConfigService",
  return_value=fake_svc)`` —— 当前模块无此属性 → AttributeError（RED）。
  查询为 async：get_provider_config 是同步函数，GREEN 需自选桥接方式
  （如 asyncio.run / 事件循环复用），测试只约束 patch 后的行为。
- patch 目标 2（key 回退）: ``inkflow.infrastructure.llm.key_manager.
  APIKeyManager.load``（类已存在，patch 可成功；当前实现不调用它 →
  行为不变 → 断言失败即 RED）。GREEN 不得绕过该 seam（必须经
  APIKeyManager 类方法 load）。
- 注册表实体读取: 仅约束 get_by_name 返回对象上的 base_url / default_model
  属性被采用；测试用鸭子类型替身（不 import 未实现的领域模型，保证本文件
  可收集）。models 字段映射（ProviderModel → LLMProviderConfig.models）不在
  本批断言范围（前端展示用，GREEN 自行决定）。
- 环境变量读取时机: 调用时读 os.environ（monkeypatch.setenv/delenv 生效）；
  不再依赖模块导入时 config 快照（现状 _BUILTIN_PROVIDERS 导入期求值 → RED）。
- 既有行为不得回归: ollama 无 env/无已存 key 时仍回退内置占位 "ollama"。
- 本批不触碰: parse_model_string、_PROVIDER_BASE_URLS、config 字段、
  LangChainLLMClient（tests/unit/test_llm_client.py 已 mock langchain_client
  层的 get_provider_config，互不影响）。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述契约改造后本文件应全绿。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inkflow.core.config import config
from inkflow.infrastructure.llm.provider_config import get_provider_config


class _FakeRegistryEntry:
    """注册表命中替身（ProviderConfig 的鸭子类型 — 避免依赖未实现的领域模型，
    保证本文件可正常收集；GREEN 实际返回领域实体，本测试只读这两个属性）。"""

    def __init__(self, *, name: str, base_url: str | None = None, default_model: str | None = None):
        self.name = name
        self.base_url = base_url
        self.default_model = default_model


def _fake_registry_service(entry: _FakeRegistryEntry | None) -> MagicMock:
    """构造 fake ProviderConfigService（get_by_name 为 AsyncMock，返回给定条目）。"""
    svc = MagicMock()
    svc.get_by_name = AsyncMock(return_value=entry)
    return svc


@pytest.fixture
def registry_miss():
    """注册表未命中：patch provider_config.ProviderConfigService → fake
    （get_by_name → None，回退内置）。

    RED 形态: 当前模块无 ProviderConfigService 属性 → AttributeError
    （预期失败，如实上报）。
    """
    svc = _fake_registry_service(None)
    with patch(
        "inkflow.infrastructure.llm.provider_config.ProviderConfigService",
        return_value=svc,
    ):
        yield svc


@pytest.fixture
def registry_hit():
    """注册表命中：fake get_by_name 返回注册表条目（base_url/default_model
    覆盖内置值）。

    RED 形态: 同 registry_miss（AttributeError）。
    """
    entry = _FakeRegistryEntry(
        name="openai",
        base_url="https://registry.example/v1",
        default_model="registry-model",
    )
    svc = _fake_registry_service(entry)
    with patch(
        "inkflow.infrastructure.llm.provider_config.ProviderConfigService",
        return_value=svc,
    ):
        yield svc


class TestApiKeyResolutionPriority:
    """api_key 解析链（spec §8.2②）: 显式 → 环境变量 → APIKeyManager → 报错。"""

    def test_explicit_api_key_takes_priority(self, registry_miss):
        """显式传入 api_key 优先使用（连通探测等按请求携带密钥场景）。"""
        cfg = get_provider_config("deepseek", api_key="explicit-key")
        assert cfg.api_key == "explicit-key"

    def test_env_var_api_key_fallback(self, registry_miss, monkeypatch):
        """无显式 key → 环境变量 INKFLOW_{PROVIDER}_API_KEY（调用时读取）。"""
        monkeypatch.setenv("INKFLOW_DEEPSEEK_API_KEY", "env-key")
        cfg = get_provider_config("deepseek")
        assert cfg.api_key == "env-key"

    def test_stored_key_fallback_via_api_key_manager(self, registry_miss, monkeypatch):
        """无 env → APIKeyManager.load 已存 key（data_dir/keys/{provider}.json）。

        patch 目标: inkflow.infrastructure.llm.key_manager.APIKeyManager.load
        （类已存在；当前实现不调用 → 行为不变，本测试 RED）。
        """
        monkeypatch.delenv("INKFLOW_ZHIPU_API_KEY", raising=False)
        with patch(
            "inkflow.infrastructure.llm.key_manager.APIKeyManager.load",
            return_value="stored-key",
        ):
            cfg = get_provider_config("zhipu")
        assert cfg.api_key == "stored-key"

    def test_no_key_anywhere_raises_value_error(self, registry_miss, monkeypatch):
        """全无 key（无显式/无 env/无已存）→ ValueError，文案含
        「API key not configured」（既有文案前缀，不得变更）。"""
        monkeypatch.delenv("INKFLOW_OPENAI_API_KEY", raising=False)
        with (
            patch(
                "inkflow.infrastructure.llm.key_manager.APIKeyManager.load",
                side_effect=FileNotFoundError("No key file for provider: openai"),
            ),
            pytest.raises(ValueError, match="API key not configured"),
        ):
            get_provider_config("openai")

    def test_ollama_builtin_placeholder_key_preserved(self, registry_miss, monkeypatch):
        """回归保护（既有行为）: ollama 无 env/无已存 key 仍回退内置占位
        "ollama"（本地运行无需真实 key，_BUILTIN_PROVIDERS 既有语义）。"""
        monkeypatch.delenv("INKFLOW_OLLAMA_API_KEY", raising=False)
        with patch(
            "inkflow.infrastructure.llm.key_manager.APIKeyManager.load",
            side_effect=FileNotFoundError("No key file for provider: ollama"),
        ):
            cfg = get_provider_config("ollama")
        assert cfg.api_key == "ollama"


class TestRegistryPriority:
    """注册表优先（spec §8.2②）: 命中用注册表值，未命中回退内置。"""

    def test_registry_values_override_builtin(self, registry_hit):
        """注册表命中 → base_url/default_model 取注册表值；key 仍走显式参数。"""
        cfg = get_provider_config("openai", api_key="explicit-key")
        assert cfg.base_url == "https://registry.example/v1"
        assert cfg.default_model == "registry-model"
        assert cfg.api_key == "explicit-key"
        registry_hit.get_by_name.assert_awaited_once_with("openai")

    def test_registry_miss_falls_back_to_builtin(self, registry_miss):
        """注册表未命中 → 回退内置（#929 迁移：provider 键路由 → provider/model 拼接）。"""
        cfg = get_provider_config("deepseek", api_key="k")
        assert cfg.base_url == "https://api.deepseek.com/v1"
        entry = config.model_routing["deepseek"]
        assert cfg.default_model == f"deepseek/{entry.model}"
        registry_miss.get_by_name.assert_awaited_once_with("deepseek")
