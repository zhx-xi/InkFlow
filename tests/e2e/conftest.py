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

    - LLM_MODEL（可选）：provider/model 格式，默认 deepseek/deepseek-chat
    - LLM_BASE_URL（可选）：覆盖对应 provider 的内置端点（不硬编码 provider）
    """
    model = os.environ.get("LLM_MODEL", "deepseek/deepseek-chat")
    provider = model.split("/", 1)[0]
    base_url = os.environ.get("LLM_BASE_URL")
    if base_url:
        monkeypatch.setitem(provider_config._PROVIDER_BASE_URLS, provider, base_url)
    return {"api_key": os.environ["LLM_API_KEY"], "model": model}
