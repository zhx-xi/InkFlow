"""tests/e2e_ai 共享 fixture — 真实模型实证套件（F59-M5 issue #966）守门。

与 tests/e2e/conftest.py（ADR-026）同规则：缺 key 永远 skip 不 fail，CI 永不执行
真实调用。与 e2e 套件不同，本套件按 provider 分 key（deepseek / zhipu /
dashscope），每项测试在自己的模块内声明 module-scoped autouse 守门，五（四主项 +
embedding 附带项）项可独立运行。

Env 约定（任务 #966 裸名 + provider_config.py 注册表约定双兼容，任一存在即可）：
- DEEPSEEK_API_KEY / INKFLOW_DEEPSEEK_API_KEY
- ZHIPU_API_KEY / INKFLOW_ZHIPU_API_KEY
- DASHSCOPE_API_KEY / INKFLOW_DASHSCOPE_API_KEY（dashscope 无内置 config 字段，
  代码内仅支持显式 api_key 参数 / 直传 ChatLiteLLM）
- DASHSCOPE_API_BASE（workspace 专属端点，默认
  https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1）

测试以显式 api_key 注入客户端（get_provider_config 优先级最高档），不依赖任何
注册表/APIKeyManager 已存 key。
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

_E2E_AI_MARKER = "e2e_ai: real-model E2E (local keys only, CI skip)"


def pytest_configure(config: pytest.Config) -> None:
    """注册 e2e_ai marker。

    backend/pyproject.toml 已声明（rootdir=backend）时不重复注册；rootdir=仓库根
    跑 tests/e2e_ai 时 ini 不加载，此处自包含兜底（tests/e2e/conftest.py
    同款形态）。
    """
    declared = {line.split(":", 1)[0].strip() for line in config.getini("markers")}
    if "e2e_ai" not in declared:
        config.addinivalue_line("markers", _E2E_AI_MARKER)


def _first_env(*names: str) -> str | None:
    """按序返回首个非空环境变量值（空串视为未设置）。"""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


@pytest.fixture(scope="module")
def deepseek_api_key() -> str:
    """deepseek key：任务裸名优先，注册表 INKFLOW_ 约定兜底；缺失 → skip。"""
    key = _first_env("DEEPSEEK_API_KEY", "INKFLOW_DEEPSEEK_API_KEY")
    if key is None:
        pytest.skip(
            "缺少 DEEPSEEK_API_KEY（或 INKFLOW_DEEPSEEK_API_KEY）— deepseek 真实模型测试跳过"
        )
    return key


@pytest.fixture(scope="module")
def zhipu_api_key() -> str:
    """zhipu key（chat 软降级 + embedding 两项共用）；缺失 → skip。"""
    key = _first_env("ZHIPU_API_KEY", "INKFLOW_ZHIPU_API_KEY")
    if key is None:
        pytest.skip(
            "缺少 ZHIPU_API_KEY（或 INKFLOW_ZHIPU_API_KEY）— zhipu 真实模型测试跳过"
        )
    return key


@pytest.fixture(scope="module")
def dashscope_api_key() -> str:
    """dashscope key；缺失 → skip。"""
    key = _first_env("DASHSCOPE_API_KEY", "INKFLOW_DASHSCOPE_API_KEY")
    if key is None:
        pytest.skip(
            "缺少 DASHSCOPE_API_KEY（或 INKFLOW_DASHSCOPE_API_KEY）— dashscope 透传测试跳过"
        )
    return key


@pytest.fixture(scope="module")
def dashscope_api_base() -> str:
    """dashscope workspace 专属 OpenAI 兼容端点：DASHSCOPE_API_BASE 可覆盖。"""
    return os.environ.get("DASHSCOPE_API_BASE") or (
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )


@pytest.fixture(scope="module", autouse=True)
def _bound_real_call_timeout() -> Iterator[None]:
    """真实调用超时收紧：CN 端点无响应时每项测试也必须 <120s 收束。

    pytest-timeout 未安装（pyproject 无该依赖，禁加）→ 收紧 config 层
    llm_request_timeout / llm_max_retries（fake e2e 同款 monkeypatch 形态）。
    模块结束还原，不影响其它测试。
    """
    from inkflow.core.config import config

    original_timeout = config.llm_request_timeout
    original_retries = config.llm_max_retries
    config.llm_request_timeout = 45
    config.llm_max_retries = 1
    try:
        yield
    finally:
        config.llm_request_timeout = original_timeout
        config.llm_max_retries = original_retries
