"""F27 M9 CLI RED 契约测试 — agent runs list/show（决策轨迹查询）.

拍板 A: 复数 runs 与 REST /agent/runs 命名一致。

测试范围：inkflow agent runs list / agent runs show --help 与真实执行路径（HTTP mock 轨）。

需 pytest marker: @pytest.mark.agent

══════════════════════════════════════════════════════════════════════════
HTTP 契约（实现者以本文件为准）:
- runs list → GET /agent/runs（params: project_id=<UUID str>, limit=<int 默认 20>）
  → 200: {"items": [run...], "total": N}
- runs show → GET /agent/runs/{run_id}（run_id 位置参数）
  → 200: run dict（含 steps 决策轨迹全量: [{"index", "message_content",
    "tool_calls": [{"step_index", "tool_name", "arguments", "result", "is_error"}],
    "tokens"}], final_content, status, terminated_by, token_usage_total...）
- 错误 = HttpApiError(status_code, detail[, code])：404（运行记录不存在）→
  「❌ {detail}」stderr + 退出码 1；其余非 2xx 同形
══════════════════════════════════════════════════════════════════════════

人类模式输出（父侧定稿，实现按此）:
- list: 首行「共 N 条运行记录」；每行「{id}  {status}  {terminated_by or "-"}  {tokens}」
- show: 「运行 {id} (status={status})」+「步骤: {len(steps)}」+「工具: {tool 序列 a → b}」+
  「tokens: {token_usage_total}」+「终止: {terminated_by or "-"}」
- --json: print_result 信封 {"ok": true, "data": <API 响应原样>}

RED 预期
--------
agent runs 子命令不存在 → typer exit 2（No such command 'runs'）；help 断言
（--project-id/--run-id 存在）FAIL；执行路径测试的 patch setup 抛
AttributeError（agent_cmd 无 ensure_kernel/InkFlowHTTPClient 属性——同 test_cli_agent.py
根因，预期 RED）。

asyncio 模式: 本 venv 实测头部 asyncio: mode=Mode.AUTO（pyproject asyncio_mode = "auto"
生效）；fake_http_client fixture 内 AsyncMock 覆盖。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app

runner = CliRunner()

AGENT_MOD = "inkflow.cli.commands.agent_cmd"

PROJECT_ID = str(uuid.uuid4())
RUN_ID = "run-0001"


def _run_result(*extra_args):
    """agent runs 调用（--project-id 自动补合法 UUID）。"""
    return runner.invoke(app, ["agent", "runs", *extra_args])


@pytest.fixture
def fake_http_client():
    """Patch agent_cmd 内 ensure_kernel + InkFlowHTTPClient → fake client 实例。"""
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(f"{AGENT_MOD}.ensure_kernel", AsyncMock(return_value=fake_handle)),
        patch(f"{AGENT_MOD}.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_err(status_code: int, detail: str, code: str | None = None):
    """惰性构造 HttpApiError。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _run_dict(**overrides) -> dict:
    run = {
        "id": RUN_ID,
        "project_id": PROJECT_ID,
        "chapter_id": None,
        "mode": "agentic",
        "status": "completed",
        "steps": [
            {
                "index": 0,
                "message_content": "",
                "tool_calls": [
                    {
                        "step_index": 0,
                        "tool_name": "search_characters",
                        "arguments": {"project_id": PROJECT_ID},
                        "result": '{"ok": true, "data": []}',
                        "is_error": False,
                    }
                ],
                "tokens": 120,
            },
            {
                "index": 1,
                "message_content": "这是正文。",
                "tool_calls": [],
                "tokens": 300,
            },
        ],
        "final_content": "这是正文。",
        "draft_id": "draft-1",
        "model": "zhipu/glm-4.5",
        "token_usage_total": 420,
        "terminated_by": "llm",
        "created_at": "2026-08-10T12:00:00",
        "updated_at": "2026-08-10T12:00:05",
    }
    run.update(overrides)
    return run


class TestAgentRunsHelp:
    """agent runs 子命令帮助（RED: 命令不存在 → exit 2 + No such command）。"""

    @staticmethod
    def _strip_ansi(text: str) -> str:
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    @pytest.mark.agent
    def test_runs_help(self):
        """agent runs --help 含 list/show 子命令。"""
        result = runner.invoke(app, ["agent", "runs", "--help"])
        assert result.exit_code == 0
        assert "list" in self._strip_ansi(result.stdout)
        assert "show" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_runs_list_help(self):
        """agent runs list --help 含 --project-id/--limit/--json。"""
        result = runner.invoke(app, ["agent", "runs", "list", "--help"])
        assert result.exit_code == 0
        assert "--project-id" in self._strip_ansi(result.stdout)
        assert "--limit" in self._strip_ansi(result.stdout)
        assert "--json" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_runs_show_help(self):
        """agent runs show --help 含 RUN_ID 位置参数与 --json。"""
        result = runner.invoke(app, ["agent", "runs", "show", "--help"])
        assert result.exit_code == 0
        assert "--json" in self._strip_ansi(result.stdout)


class TestAgentRunsExecution:
    """agent runs list/show 真实执行路径（HTTP mock 轨）。"""

    @pytest.mark.agent
    def test_runs_list_success(self, fake_http_client):
        """runs list 成功：GET /agent/runs（params 正确）+ 人类摘要输出。"""
        fake_http_client.get.return_value = {
            "items": [
                _run_dict(),
                _run_dict(id="run-0002", status="terminated_by_guardrail"),
            ],
            "total": 2,
        }
        result = _run_result("list", "--project-id", PROJECT_ID, "--limit", "20")
        assert result.exit_code == 0
        call = fake_http_client.get.await_args
        assert call.args[0] == "/agent/runs"
        assert call.kwargs["params"]["project_id"] == PROJECT_ID
        assert call.kwargs["params"]["limit"] == 20
        assert "共 2 条运行记录" in result.stdout
        assert RUN_ID in result.stdout
        assert "terminated_by_guardrail" in result.stdout

    @pytest.mark.agent
    def test_runs_list_json(self, fake_http_client):
        """runs list --json：stdout 信封 == API 响应原样。"""
        payload = {"items": [_run_dict()], "total": 1}
        fake_http_client.get.return_value = payload
        result = _run_result("list", "--project-id", PROJECT_ID, "--json")
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"ok": True, "data": payload}

    @pytest.mark.agent
    def test_runs_show_success(self, fake_http_client):
        """runs show 成功：GET /agent/runs/{id} + 决策轨迹摘要（步骤/工具序列/token/终止）。"""
        fake_http_client.get.return_value = _run_dict()
        result = _run_result("show", RUN_ID)
        assert result.exit_code == 0
        call = fake_http_client.get.await_args
        assert call.args[0] == f"/agent/runs/{RUN_ID}"
        assert f"运行 {RUN_ID} (status=completed)" in result.stdout
        assert "步骤: 2" in result.stdout
        assert "search_characters" in result.stdout  # 工具序列含工具名
        assert "tokens: 420" in result.stdout
        assert "终止: llm" in result.stdout

    @pytest.mark.agent
    def test_runs_show_json_steps_full(self, fake_http_client):
        """runs show --json：steps 决策轨迹全量（工具调用含 arguments/result）。"""
        fake_http_client.get.return_value = _run_dict()
        result = _run_result("show", RUN_ID, "--json")
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        data = payload["data"]
        assert data["id"] == RUN_ID
        assert len(data["steps"]) == 2
        assert data["steps"][0]["tool_calls"][0]["tool_name"] == "search_characters"
        assert data["steps"][0]["tool_calls"][0]["result"] is not None

    @pytest.mark.agent
    def test_runs_show_404(self, fake_http_client):
        """runs show 404（运行记录不存在）→ stderr ❌ + 退出码 1。"""
        fake_http_client.get.side_effect = _http_err(404, "运行记录不存在")
        result = _run_result("show", RUN_ID)
        assert result.exit_code == 1
        assert "❌ 运行记录不存在" in result.stderr

    @pytest.mark.agent
    def test_runs_list_kernel_startup_error(self):
        """ensure_kernel 失败 → stderr ❌ 内核启动失败 + 退出码 1。"""
        from inkflow.infrastructure.kernel import KernelStartupError

        with patch(
            f"{AGENT_MOD}.ensure_kernel",
            AsyncMock(side_effect=KernelStartupError("启动超时")),
        ):
            result = _run_result("list", "--project-id", PROJECT_ID)
        assert result.exit_code == 1
        assert "❌ 内核启动失败: 启动超时" in result.stderr

    @pytest.mark.agent
    def test_runs_list_none_result_returns(self, fake_http_client):
        """GET /agent/runs 返回 None → data None → 直接 return，不输出（覆盖 L583->584）。"""
        fake_http_client.get.return_value = None
        result = _run_result("list", "--project-id", PROJECT_ID)
        assert result.exit_code == 0
        assert result.stdout == ""

    @pytest.mark.agent
    def test_runs_show_none_result_returns(self, fake_http_client):
        """GET /agent/runs/{id} 返回 None → 直接 return，不输出（覆盖 L611->612）。"""
        fake_http_client.get.return_value = None
        result = _run_result("show", RUN_ID)
        assert result.exit_code == 0
        assert result.stdout == ""

    @pytest.mark.agent
    def test_runs_show_tool_sequence_skips_unnamed_and_duplicate(self, fake_http_client):
        """_tool_sequence 跳过无名（无 tool_name）/重复工具调用（覆盖 L547->545 False 弧）。"""
        fake_http_client.get.return_value = _run_dict(
            steps=[
                {
                    "index": 0,
                    "message_content": "",
                    "tool_calls": [
                        {
                            "step_index": 0,
                            "tool_name": "search_characters",
                            "arguments": {},
                            "result": "",
                            "is_error": False,
                        },
                        {
                            "step_index": 1,
                            "arguments": {},
                            "result": "",
                            "is_error": False,
                        },
                    ],
                    "tokens": 100,
                },
                {
                    "index": 1,
                    "message_content": "",
                    "tool_calls": [
                        {
                            "step_index": 0,
                            "tool_name": "search_characters",
                            "arguments": {},
                            "result": "",
                            "is_error": False,
                        }
                    ],
                    "tokens": 200,
                },
            ]
        )
        result = _run_result("show", RUN_ID)
        assert result.exit_code == 0
        assert "工具: search_characters" in result.stdout
