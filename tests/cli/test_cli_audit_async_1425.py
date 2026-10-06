"""#1425 RED 契约 —— CLI 异步语义（默认 --wait 保 UX；--no-wait 返回 log_id）.

契约（GREEN 实现必须满足，spec §4 v1.5）:
- 默认 `--wait`：POST 触发（得 202 `{log_id, status}`）→ 轮询
  `GET /audit-logs/{log_id}/status` 至 `completed` → `GET /audit-logs/{log_id}`
  取回记录明细 → **人类输出与同步版一致**（findings 按 severity 打印）。
- `--no-wait`：只 POST，人类输出受理凭证（含 `log_id` + 查询指引）；不轮询。
- 轮询到 `run_status='failed'` → 退出 1（错误信封含 log_id 恢复指引）。
- `--json`：信封 data = 记录明细（--wait）/ 受理凭证（--no-wait）。

F38 恒 HTTP 模式（#169）: mock 目标 = 命令模块命名空间的 ensure_kernel + InkFlowHTTPClient。

依据: issue #1425 + specs/f34-chapter-audit/spec.md §4（v1.5）/§7 E19/E22。
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

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000002")
LOG_ID = "00000000-0000-4000-8000-0000000000a1"
TS = "2026-10-07T10:00:00Z"


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（NO_COLOR 规避 FORCE_COLOR 渲染坑，项目惯例）."""
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（命令模块命名空间，F38 mock 轨）."""
    fake_handle = SimpleNamespace(
        port=38291, token="test-token", pid=1, version="0.1.0", started_at="", reused=True
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


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """轮询间隔归零（测试不真等）."""
    monkeypatch.setattr("inkflow.cli.commands.audit_chapter._POLL_INTERVAL", 0)


def _accepted(status: str = "running") -> dict:
    """POST /audit 的 202 响应体（spec §3.2 v1.5）."""
    return {"log_id": LOG_ID, "status": status}


def _status(run_status: str = "completed", error: str = "") -> dict:
    """GET /audit-logs/{id}/status 的 200 响应体（spec §3.2 v1.5）."""
    return {
        "log_id": LOG_ID,
        "run_status": run_status,
        "status": "pending",
        "degraded": False,
        "error": error,
        "chapter_id": str(CID),
        "chapter_title": "第 3 章 龙的苏醒",
        "created_at": TS,
    }


def _detail() -> dict:
    """GET /audit-logs/{id} 的 AuditLogDetail 响应体（v1.4 读口 + v1.5 执行态）."""
    return {
        "id": LOG_ID,
        "project_id": str(PID),
        "chapter_id": str(CID),
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "run_status": "completed",
        "severity_summary": "1 error, 1 warnings, 0 info",
        "summary": "",
        "degraded": False,
        "note": "",
        "created_at": TS,
        "confirmed_at": None,
        "error": "",
        "findings": [
            {
                "check_type": "character_drift",
                "severity": "error",
                "message": "本章「李青焰」怒斥同伴，但角色档案性格为「温厚沉稳」",
                "suggestion": "可改为隐忍不发",
                "ref_entity_id": None,
                "ref_entity_name": "李青焰",
                "context": "",
            },
            {
                "check_type": "word_count",
                "severity": "info",
                "message": "本章 2,845 字，低于目标 3,000 字",
                "suggestion": "",
                "ref_entity_id": None,
                "ref_entity_name": "",
                "context": "",
            },
        ],
    }


class TestWaitDefault:
    """默认 --wait：轮询至终态后输出报告（UX 与同步版一致）."""

    def test_wait_polls_then_prints_report(self, cli_runner, fake_http_client) -> None:
        """running → completed → 取回明细并打印 findings（error 在前）."""
        fake_http_client.post.return_value = _accepted("running")
        statuses = [_status("running"), _status("completed")]
        details = [_detail()]

        async def _get(path, **kwargs):  # 测试替身
            if path.endswith("/status"):
                return statuses.pop(0)
            if path.startswith("/audit-logs/"):
                return details.pop(0)
            raise AssertionError(f"意外路径: {path}")

        fake_http_client.get.side_effect = _get

        result = cli_runner.invoke(
            app, ["chapter", str(CID), "-p", str(PID)], obj=CliContext(json_output=False)
        )

        assert result.exit_code == 0
        err_msg = "本章「李青焰」怒斥同伴"
        info_msg = "本章 2,845 字，低于目标 3,000 字"
        assert err_msg in result.output
        assert info_msg in result.output
        assert result.output.index(err_msg) < result.output.index(info_msg)
        # 轮询两次 status + 一次明细
        paths = [c.args[0] for c in fake_http_client.get.await_args_list]
        assert paths == [
            f"/audit-logs/{LOG_ID}/status",
            f"/audit-logs/{LOG_ID}/status",
            f"/audit-logs/{LOG_ID}",
        ]

    def test_wait_failed_exits_1_with_log_id_hint(self, cli_runner, fake_http_client) -> None:
        """轮询到 failed → 退出 1（错误信封含 log_id 恢复指引）."""
        fake_http_client.post.return_value = _accepted("running")

        async def _get(path, **kwargs):  # 测试替身
            return _status("failed", error="审计任务失败: boom")

        fake_http_client.get.side_effect = _get

        result = cli_runner.invoke(
            app, ["chapter", str(CID), "-p", str(PID)], obj=CliContext(json_output=True)
        )

        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert LOG_ID in data["error"]["message"]
        assert "boom" in data["error"]["message"]

    def test_wait_json_envelope_is_detail(self, cli_runner, fake_http_client) -> None:
        """--json + --wait → data = AuditLogDetail（含 findings）。"""
        fake_http_client.post.return_value = _accepted("completed")

        async def _get(path, **kwargs):  # 测试替身
            return _detail()

        fake_http_client.get.side_effect = _get

        result = cli_runner.invoke(
            app, ["chapter", str(CID), "-p", str(PID)], obj=CliContext(json_output=True)
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["id"] == LOG_ID
        assert data["data"]["run_status"] == "completed"
        assert len(data["data"]["findings"]) == 2


class TestNoWait:
    """--no-wait：只受理，输出 {log_id, status}（批场景/自管轮询）."""

    def test_no_wait_prints_log_id(self, cli_runner, fake_http_client) -> None:
        """人类输出受理凭证 + 查询指引；不轮询."""
        fake_http_client.post.return_value = _accepted("running")

        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", str(PID), "--no-wait"],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        assert LOG_ID in result.output
        assert "running" in result.output
        fake_http_client.get.assert_not_awaited()

    def test_no_wait_json_envelope_is_accepted(self, cli_runner, fake_http_client) -> None:
        """--no-wait --json → data = {log_id, status}."""
        fake_http_client.post.return_value = _accepted("running")

        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", str(PID), "--no-wait"],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"] == {"log_id": LOG_ID, "status": "running"}
