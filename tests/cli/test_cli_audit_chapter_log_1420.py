"""#1420 RED 契约 —— CLI `inkflow audit chapter --log <id>`（按记录 ID 取回明细）.

覆盖（spec §4 v1.4 演进 + §7）:
- `--log <id>`: GET /audit-logs/{id} → 人类可读明细（记录元信息 + findings 逐条，error 在前）
  —— **无 -p 也能用**（超时场景下客户端只有 log id）
- `--log <id> -p <项目>`: -p 被忽略，不做项目名解析（不发 GET /projects）
- `--log <id> --json`: {"ok": true, "data": AuditLogDetail}（F7 全局信封）
- `--log` 记录不存在（HTTP 404）→ NOT_FOUND 错误信封 + 退出 1
- 用法错误（退出 2）: `--log` + chapter / `--log` + `--confirm` / `--log` + `--history` /
  既无 `--log` 又无 `-p`（--history 亦无）
- 反例守护: `--log` 模式不得触碰 /projects/{pid}/audit-logs（列表）与 audit 触发端点

F38 恒 HTTP 模式（#169）: mock 目标 = ensure_kernel + InkFlowHTTPClient（命令模块命名空间）。

依据: issue #1420 + specs/f34-chapter-audit/spec.md §4（v1.4 演进留痕）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.audit_chapter import app
from inkflow.cli.context import CliContext

from .conftest import local_display

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000002")
LOG_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
CHAR_ID = "0c000000-0000-4000-8000-00000000000c"
TS = "2026-08-09T10:00:00Z"


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（NO_COLOR 规避 FORCE_COLOR 渲染坑，项目惯例）。"""
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（命令模块命名空间，F38 mock 轨）。"""
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
            "inkflow.cli.commands.audit_chapter.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.cli.commands.audit_chapter.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _finding(**overrides: object) -> dict:
    """构造单条 finding JSON dict（error 优先展示用例）。"""
    kwargs: dict[str, object] = {
        "check_type": "character_drift",
        "severity": "error",
        "message": "角色行为疑似与人设冲突",
        "suggestion": "可改为隐忍不发",
        "ref_entity_id": CHAR_ID,
        "ref_entity_name": "角色甲",
        "context": "节选片段",
    }
    kwargs.update(overrides)
    return kwargs


def _detail(**overrides: object) -> dict:
    """构造 GET /audit-logs/{id} 响应 JSON dict（AuditLogDetail）。"""
    kwargs: dict[str, object] = {
        "id": str(LOG_ID),
        "project_id": str(PID),
        "chapter_id": str(CID),
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "severity_summary": "1 error, 1 warnings, 0 info",
        "summary": "",
        "degraded": False,
        "note": "",
        "created_at": TS,
        "confirmed_at": None,
        "findings": [
            _finding(),
            _finding(
                check_type="word_count",
                severity="info",
                message="本章 2,845 字，低于目标 3,000 字",
                suggestion="",
                ref_entity_id=None,
                ref_entity_name="",
                context="",
            ),
        ],
    }
    kwargs.update(overrides)
    return kwargs


class TestAuditLogDetailCli:
    """inkflow audit chapter --log <id> — 按记录 ID 取回审计明细（#1420 方案 2）。"""

    def test_log_mode_human_without_project(self, cli_runner, fake_http_client):
        """`--log <id>`（无 -p）→ GET /audit-logs/{id} → 明细人类输出，退出 0."""
        fake_http_client.get.return_value = _detail()

        result = cli_runner.invoke(
            app,
            ["chapter", "--log", str(LOG_ID)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        fake_http_client.get.assert_awaited_once()
        assert fake_http_client.get.await_args.args[0] == f"/audit-logs/{LOG_ID}"
        fake_http_client.post.assert_not_awaited()
        # 记录元信息 + findings 逐条（error 在前）+ 本地时区时间
        assert str(LOG_ID) in result.output
        assert "第 3 章 龙的苏醒" in result.output
        assert "1 error, 1 warnings, 0 info" in result.output
        assert local_display(TS) in result.output
        err_msg = "角色行为疑似与人设冲突"
        info_msg = "本章 2,845 字，低于目标 3,000 字"
        assert err_msg in result.output
        assert info_msg in result.output
        assert result.output.index(err_msg) < result.output.index(info_msg)

    def test_log_mode_ignores_project_option(self, cli_runner, fake_http_client):
        """`--log <id> -p <项目名>` → -p 被忽略（不发 GET /projects），仍退出 0."""
        fake_http_client.get.return_value = _detail()

        result = cli_runner.invoke(
            app,
            ["chapter", "--log", str(LOG_ID), "-p", "某项目名"],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        assert fake_http_client.get.await_args.args[0] == f"/audit-logs/{LOG_ID}"
        assert fake_http_client.get.await_count == 1

    def test_log_mode_json_envelope(self, cli_runner, fake_http_client):
        """`--log <id> --json` → {"ok": true, "data": AuditLogDetail}（F7 信封）."""
        fake_http_client.get.return_value = _detail()

        result = cli_runner.invoke(
            app,
            ["chapter", "--log", str(LOG_ID)],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["id"] == str(LOG_ID)
        assert data["data"]["severity_summary"] == "1 error, 1 warnings, 0 info"
        assert data["data"]["findings"][0]["check_type"] == "character_drift"

    def test_log_mode_not_found_exit_1(self, cli_runner, fake_http_client):
        """记录不存在（HTTP 404）→ NOT_FOUND 错误信封 + 退出 1."""
        from inkflow.infrastructure.http import HttpApiError  # 惰性导入惯例

        fake_http_client.get.side_effect = HttpApiError(404, "审计记录不存在")

        result = cli_runner.invoke(
            app,
            ["chapter", "--log", str(LOG_ID)],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "审计记录不存在" in data["error"]["message"]

    def test_log_does_not_touch_history_or_trigger(self, cli_runner, fake_http_client):
        """反例守护：--log 模式只读单条明细（不碰 /projects/{pid}/audit-logs 与触发端点）."""
        fake_http_client.get.return_value = _detail()

        result = cli_runner.invoke(
            app,
            ["chapter", "--log", str(LOG_ID)],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        for call in fake_http_client.get.await_args_list:
            assert call.args[0] == f"/audit-logs/{LOG_ID}"
        fake_http_client.post.assert_not_awaited()

    def test_log_with_history_exit_2(self, cli_runner, fake_http_client):
        """`--log` 与 `--history` 互斥 → 退出 2（用法错误）."""
        result = cli_runner.invoke(
            app,
            ["chapter", "--log", str(LOG_ID), "--history", "-p", str(PID)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 2
        fake_http_client.get.assert_not_awaited()
        fake_http_client.post.assert_not_awaited()

    def test_log_with_chapter_exit_2(self, cli_runner, fake_http_client):
        """`--log` 与位置参数 chapter 互斥 → 退出 2."""
        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "--log", str(LOG_ID)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 2
        fake_http_client.get.assert_not_awaited()

    def test_log_with_confirm_exit_2(self, cli_runner, fake_http_client):
        """`--log` 与 `--confirm` 互斥 → 退出 2."""
        result = cli_runner.invoke(
            app,
            ["chapter", "--log", str(LOG_ID), "--confirm", "accept"],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 2
        fake_http_client.get.assert_not_awaited()
        fake_http_client.post.assert_not_awaited()

    def test_missing_project_without_log_exit_2(self, cli_runner, fake_http_client):
        """既无 `--log` 又无 `-p`（也无 --history）→ 退出 2（用法错误，非资源错误）."""
        result = cli_runner.invoke(
            app,
            ["chapter", str(CID)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 2
        fake_http_client.get.assert_not_awaited()
        fake_http_client.post.assert_not_awaited()
