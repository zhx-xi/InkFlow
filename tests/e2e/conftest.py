"""tests/e2e 共享 fixture — 真实 AI 测试守卫（ADR-026）。

无 LLM_API_KEY 时所有 e2e 测试 skip（缺 key 永远 skip 不 fail，本地/CI 双守卫）。
"""

import os

import pytest

from inkflow.infrastructure.llm import provider_config


def pytest_configure(config: pytest.Config) -> None:
    """注册 e2e marker（CI 以 ../tests/e2e/ 运行时代 rootdir 在仓库根，
    backend/pyproject.toml 的 markers 声明不加载——此处自包含注册）。"""
    config.addinivalue_line("markers", "e2e: 端到端测试 — 完整用户链路（未来）")


@pytest.fixture(autouse=True)
def _require_llm_key():
    """真实 AI 测试守卫：无 LLM_API_KEY → 全部 skip。"""
    if not os.environ.get("LLM_API_KEY"):
        pytest.skip("LLM_API_KEY 未设置 — 真实 AI e2e 测试跳过")


@pytest.fixture
def llm_env(monkeypatch):
    """e2e LLM 环境配置。

    - LLM_MODEL（可选）：支持 `provider/model` 或裸模型名（如 `deepseek-chat`）——
      裸模型名自动挂 deepseek provider（LLM_BASE_URL 存在时覆盖其端点）
    - LLM_BASE_URL（可选）：覆盖对应 provider 的内置端点（不硬编码 provider）
    """
    raw = os.environ.get("LLM_MODEL", "deepseek-chat")
    if "/" in raw:
        provider, model_name = raw.split("/", 1)
        model = raw
    else:
        # 裸模型名（ADR-026 默认值口径）：挂 deepseek provider 槽位，
        # base_url 由 LLM_BASE_URL 覆盖（存在时）或走内置 deepseek 端点
        provider, model_name, model = "deepseek", raw, f"deepseek/{raw}"
    base_url = os.environ.get("LLM_BASE_URL")
    if base_url:
        monkeypatch.setitem(provider_config._PROVIDER_BASE_URLS, provider, base_url)
    return {
        "api_key": os.environ["LLM_API_KEY"],
        "model": model,
        "provider": provider,
        "model_name": model_name,
    }
