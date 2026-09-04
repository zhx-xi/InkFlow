"""F50 LangSmith 追踪 — env 解析与注入单元测试（RED 契约）。

本测试为契约：`inkflow.core.langsmith_tracing` 模块尚未实现（RED 阶段，
GREEN 由 Codex 实现）。断言遵循 spec §4.1/§4.2 + §5 边界表。
"""

from __future__ import annotations

import os

import pytest

from inkflow.core.config import InkFlowConfig
from inkflow.core.langsmith_tracing import (
    _LANGSMITH_ENV_KEYS,
    apply_langsmith_tracing,
    resolve_langsmith_trace_env,
)

# key 样例——拼接构造，避免 Hermes redact 污染断言（skills 陷阱 #614）
_TEST_KEY = "lsv2-" + "test-key"


@pytest.fixture(autouse=True)
def _clean_langsmith_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个用例前后清空 LANGSMITH_*，避免跨用例残留污染。"""
    for k in _LANGSMITH_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    yield
    for k in _LANGSMITH_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def _make_config(**overrides: object) -> InkFlowConfig:
    """构造测试 config；不依赖实时 env。data_dir 用默认 ./data（gitignored）。"""
    base: dict[str, object] = {
        "langsmith_enabled": True,
        "langsmith_api_key": _TEST_KEY,
        "langsmith_project": "inkflow",
        "langsmith_endpoint": "",
    }
    base.update(overrides)
    return InkFlowConfig(**base)


class TestResolveLangsmithTraceEnv:
    """resolve_langsmith_trace_env — 纯函数（spec §4.1）。"""

    def test_disabled_returns_empty(self) -> None:
        cfg = _make_config(langsmith_enabled=False)
        assert resolve_langsmith_trace_env(cfg) == {}

    def test_enabled_without_key_returns_empty(self) -> None:
        cfg = _make_config(langsmith_api_key="")
        assert resolve_langsmith_trace_env(cfg) == {}

    def test_enabled_with_key_returns_full_env(self) -> None:
        cfg = _make_config()
        env = resolve_langsmith_trace_env(cfg)
        assert env == {
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": _TEST_KEY,
            "LANGSMITH_PROJECT": "inkflow",
        }

    def test_endpoint_included_when_set(self) -> None:
        cfg = _make_config(langsmith_endpoint="https://langsmith.example.com")
        env = resolve_langsmith_trace_env(cfg)
        assert env["LANGSMITH_ENDPOINT"] == "https://langsmith.example.com"

    def test_empty_project_falls_back_to_inkflow(self) -> None:
        cfg = _make_config(langsmith_project="")
        env = resolve_langsmith_trace_env(cfg)
        assert env["LANGSMITH_PROJECT"] == "inkflow"

    def test_pure_no_side_effect(self) -> None:
        cfg = _make_config()
        before = dict(os.environ)
        resolve_langsmith_trace_env(cfg)
        assert dict(os.environ) == before


class TestApplyLangsmithTracing:
    """apply_langsmith_tracing — 有副作用（spec §4.2）。"""

    def test_disabled_clears_stale_env(self) -> None:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = "stale"
        apply_langsmith_tracing(_make_config(langsmith_enabled=False))
        for k in _LANGSMITH_ENV_KEYS:
            assert os.environ.get(k) is None

    def test_enabled_injects_env(self) -> None:
        apply_langsmith_tracing(_make_config())
        assert os.environ["LANGSMITH_TRACING"] == "true"
        assert os.environ["LANGSMITH_API_KEY"] == _TEST_KEY
        assert os.environ["LANGSMITH_PROJECT"] == "inkflow"

    def test_idempotent(self) -> None:
        apply_langsmith_tracing(_make_config())
        first = dict(os.environ)
        apply_langsmith_tracing(_make_config())
        assert dict(os.environ) == first
