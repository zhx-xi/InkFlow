"""fake LLM routing 契约测试（S0，ADR-047）— 按 (model + 请求签名) 选 fixture。

RED 阶段：`.routing` 不存在 → 收集级 FAIL（feature missing）。
GREEN 后：select_fixture(model, payload) -> Fixture 按契约返回正确/错误场景。
"""

from __future__ import annotations

import pytest

# 契约：路由模块提供 select_fixture / Fixture（Fixture 经 select_fixture 返回值隐式验证）
from .routing import select_fixture


class TestRouteByModel:
    """① 主路由按 model 字符串选择场景。"""

    def test_correct_model_returns_correct_fixture(self) -> None:
        fixture = select_fixture("fake/correct", {"model": "fake/correct"})
        assert fixture.kind == "correct"
        assert fixture.status_code == 200
        assert fixture.content  # 非空断言：correct fixture 必须有内容

    @pytest.mark.parametrize(
        ("model", "expected_status", "expected_code"),
        [
            ("fake/error-401", 401, "unauthorized"),
            ("fake/error-429", 429, "rate_limit_exceeded"),
            ("fake/error-500", 500, "server_error"),
        ],
    )
    def test_error_model_returns_expected_status(
        self, model: str, expected_status: int, expected_code: str
    ) -> None:
        fixture = select_fixture(model, {"model": model})
        assert fixture.kind == "error"
        assert fixture.status_code == expected_status
        assert fixture.error_code == expected_code
        assert fixture.error_message is not None

    def test_timeout_model_has_delay(self) -> None:
        fixture = select_fixture("fake/error-timeout", {"model": "fake/error-timeout"})
        assert fixture.kind == "timeout"
        assert fixture.delay_seconds > 0

    def test_empty_model_has_empty_content(self) -> None:
        fixture = select_fixture("fake/empty", {"model": "fake/empty"})
        assert fixture.kind == "empty"
        assert fixture.content == ""

    def test_malformed_model_is_marked(self) -> None:
        fixture = select_fixture("fake/malformed", {"model": "fake/malformed"})
        assert fixture.kind == "malformed"

    def test_non_dict_message_ignored(self) -> None:
        """payload 含非 dict 消息（字符串/None）应被安全忽略，不崩溃，正常路由。"""
        fixture = select_fixture(
            "fake/correct",
            {"model": "fake/correct", "messages": ["raw-text", None]},
        )
        assert fixture.kind == "correct"


class TestRouteBySignature:
    """③② 请求签名哨兵覆盖 model 路由（错误注入用）。"""

    def test_signature_override_beats_model(self) -> None:
        """payload 含哨兵 [[fake-scenario:error-429]] 应覆盖 model=fake/correct。"""
        payload = {
            "model": "fake/correct",
            "messages": [{"role": "user", "content": "hi [[fake-scenario:error-429]]"}],
        }
        fixture = select_fixture("fake/correct", payload)
        assert fixture.kind == "error"
        assert fixture.status_code == 429
        assert fixture.error_code == "rate_limit_exceeded"

    def test_signature_override_correct_wins(self) -> None:
        """哨兵指向 correct 应返回 correct 场景（即使 model 是错误场景）。"""
        payload = {
            "model": "fake/error-500",
            "messages": [{"role": "user", "content": "go [[fake-scenario:correct]]"}],
        }
        fixture = select_fixture("fake/error-500", payload)
        assert fixture.kind == "correct"
        assert fixture.status_code == 200


class TestDefaultRouting:
    """未知 model 不应抛异常，默认走 correct fixture。"""

    def test_unknown_model_defaults_to_correct(self) -> None:
        fixture = select_fixture("fake/unknown-scenario", {"model": "fake/unknown-scenario"})
        assert fixture.kind == "correct"
        assert fixture.status_code == 200
