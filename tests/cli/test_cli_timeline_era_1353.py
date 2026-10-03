"""#1353 时间线纪元承载 — CLI 契约（f12 spec v1.3 §4.1 create/update + §14.2）。

【契约（钉住两件事）】
1. ``timeline create --era <轴名> --era-value <数值>`` → POST body 带
   ``era`` / ``era_value``（落 extra，零 DDL）
2. **向后兼容**：不传 ``--era`` → body **不含** era / era_value 键
   （既有 exact-payload 用例零改动，spec v1.2 行为零变化）
   ``timeline update --era ""`` → body 含 ``era: ""``（清除纪元，§2.8 E4）

【RED 预期】CLI 尚无 --era / --era-value 选项 → click 报
``no such option``（exit_code 2）/ payload 断言 FAIL；零 SyntaxError。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.timeline import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
EID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000002")


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（同 test_cli_timeline_ops.py 形态）。"""
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(
            "inkflow.cli.commands.timeline.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.cli.commands.timeline.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _event_json(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "id": str(EID),
        "project_id": str(PID),
        "title": "事件甲",
        "description": "",
        "time_value": None,
        "time_unit": "",
        "time_display": "",
        "narrative_position": 3,
        "timeline_flag": "",
        "extra": {},
    }
    payload.update(overrides)
    return payload


def _payload(client: AsyncMock) -> dict:
    """取 HTTP 调用体（create → post / update → patch）。"""
    call = client.post.await_args if client.post.await_count else client.patch.await_args
    assert call is not None
    return call.kwargs["json"]


class TestCreateEventEraCLI:
    def test_create_with_era_sends_both_keys(self, cli_runner: CliRunner, fake_http_client) -> None:
        fake_http_client.post.return_value = _event_json(
            extra={"era": "示例历", "era_value": 317.5}
        )

        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--title",
                "事件甲",
                "--era",
                "示例历",
                "--era-value",
                "317.5",
            ],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        payload = _payload(fake_http_client)
        assert payload["era"] == "示例历"
        assert payload["era_value"] == 317.5
        assert json.loads(result.stdout)["data"]["extra"] == {
            "era": "示例历",
            "era_value": 317.5,
        }

    def test_create_without_era_omits_keys(self, cli_runner: CliRunner, fake_http_client) -> None:
        """向后兼容守护：不带 --era → body 无 era/era_value 键（v1.2 行为零变化）。"""
        fake_http_client.post.return_value = _event_json()

        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "事件甲"],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        payload = _payload(fake_http_client)
        assert "era" not in payload
        assert "era_value" not in payload


class TestUpdateEventEraCLI:
    def test_update_clear_era_sends_empty_string(
        self, cli_runner: CliRunner, fake_http_client
    ) -> None:
        fake_http_client.patch.return_value = _event_json(extra={})

        result = cli_runner.invoke(
            app,
            ["update", "--id", str(EID), "--era", ""],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        assert _payload(fake_http_client) == {"era": ""}

    def test_update_with_era_and_value(self, cli_runner: CliRunner, fake_http_client) -> None:
        fake_http_client.patch.return_value = _event_json(
            extra={"era": "示例仙历", "era_value": 1024.0}
        )

        result = cli_runner.invoke(
            app,
            ["update", "--id", str(EID), "--era", "示例仙历", "--era-value", "1024"],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        assert _payload(fake_http_client) == {"era": "示例仙历", "era_value": 1024.0}

    def test_update_era_value_non_numeric_rejected_locally(
        self, cli_runner: CliRunner, fake_http_client
    ) -> None:
        """非数值 --era-value → 本地 VALIDATION_ERROR 信封 + 退出码 1（不发起内核调用）。

        语义：纪元轴内值须为有限数值（f12 spec §3.4「纪元轴内值必须是有限数值」）；
        CLI 侧提前拒绝，避免构造 DTO 时抛裸 pydantic 异常（体验缺陷）。
        """
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(EID), "--era", "示例仙历", "--era-value", "abc"],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "VALIDATION_ERROR"
        assert "纪元轴内值" in payload["error"]["message"]
        assert fake_http_client.patch.await_count == 0

    def test_create_era_value_non_numeric_rejected_locally(
        self, cli_runner: CliRunner, fake_http_client
    ) -> None:
        """创建路径同样本地拒绝非数值 --era-value（不进入内核启动/HTTP）。"""
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--title",
                "事件甲",
                "--era",
                "示例历",
                "--era-value",
                "nan",
            ],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error"]["code"] == "VALIDATION_ERROR"
        assert fake_http_client.post.await_count == 0
