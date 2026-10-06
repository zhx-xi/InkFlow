"""CLI Agent 命令集成测试 — CliRunner + Mock ensure_kernel + InkFlowHTTPClient（F38 HTTP mock 轨）.

测试范围：inkflow agent run/status/validate/template --help。
需 pytest marker: @pytest.mark.agent

F38 改造（#169）：mock 目标从 domain Service/LLM 客户端迁移到 ensure_kernel +
InkFlowHTTPClient（HTTP JSON 响应 + SSE 流式 mock）；create_tables/session/LLM
patch 已移除（agent_cmd 不再直连 DB/AgentService）。RED 阶段命令模块无
ensure_kernel/InkFlowHTTPClient 属性 → fake_http_client fixture 的 patch setup
抛 AttributeError（同根因，预期 RED）。

══════════════════════════════════════════════════════════════════════════
HTTP 契约（实现者以本文件为准，F38 §3.1）:
- run      → POST /agent/pipelines/execute（body = PipelineExecuteRequest JSON；
  project_id/chapter_id 为 UUID 字符串；variables/role_overrides 原样透传）
- status   → GET /agent/pipelines/executions/{run_id}（无记录 → HTTP 404
  detail="执行记录不存在"）
- template → GET /agent/pipelines/templates（{"items": [...]}）
- 错误 = HttpApiError(status_code, detail[, code])：404（项目/章节/记录不存在）
  → 「❌ {detail}」stderr + 退出码 1；422（其余 AgentServiceError 语义）同形；
  HttpApiError 惰性 import（infrastructure.http RED 阶段不存在）
══════════════════════════════════════════════════════════════════════════
#1478 契约增量（RED 载于 TestAgentStatusExecution / TestAgentRunWatch）:
- status --json（命令级与根级 --json 等价）→ stdout 信封 {"ok": true, "data": <执行记录>}；
  非 2xx → print_error 错误信封（stdout）+ 退出码 1；人类可读输出（无 --json）逐字不变
- run --watch → 阻塞轮询 GET /agent/pipelines/executions/{id} 直到终态
  （终态 = 不在 {pending, running, waiting_hitl} 内）才返回；退避 1s→2s→…封顶
  _WATCH_MAX_INTERVAL；总超时 --watch-timeout（默认 600s）
- run --watch 总超时 → 退出码 1 + 明确错误（含 run_id，可继续 status 轮询）；
  json 模式 → {"ok": false, "error": {"code": "WATCH_TIMEOUT", ...}}
- run --watch 轮询失败（内核非 2xx）→ 报错退出（不静默成功）
- run 不带 --watch → 立即返回（行为与 #1478 前一致）
══════════════════════════════════════════════════════════════════════════
"""

import json
import uuid
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app
from inkflow.cli.commands import agent_cmd
from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest

runner = CliRunner()

# patch 目标模块：agent_cmd 内的符号（F38 后 = ensure_kernel + InkFlowHTTPClient）
AGENT_MOD = "inkflow.cli.commands.agent_cmd"


class TestAgentCLI:
    """Agent CLI 命令测试。"""

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """去除 ANSI 转义码（CI 环境 rich_markup_mode 会引入颜色码）。"""
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    @pytest.mark.agent
    def test_agent_run_help(self):
        """agent run --help 含 --watch / --watch-timeout（#1478）。"""
        result = runner.invoke(app, ["agent", "run", "--help"])
        assert result.exit_code == 0
        assert "--project-id" in self._strip_ansi(result.stdout)
        assert "--watch" in self._strip_ansi(result.stdout)
        assert "--watch-timeout" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_agent_status_help(self):
        """inkflow agent status --help 输出帮助。"""
        result = runner.invoke(app, ["agent", "status", "--help"])
        assert result.exit_code == 0
        assert "--run-id" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_agent_validate_help(self):
        """inkflow agent validate --help 输出帮助。"""
        result = runner.invoke(app, ["agent", "validate", "--help"])
        assert result.exit_code == 0
        assert "--file" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_agent_template_pipelines_help(self):
        """inkflow agent template --help 含 pipelines 子命令（#251：template 升级为
        管理组后，旧「列出内置管线模板」迁移至 pipelines 子命令）。"""
        result = runner.invoke(app, ["agent", "template", "--help"])
        assert result.exit_code == 0
        assert "pipelines" in self._strip_ansi(result.stdout)


# =====================================================================
# agent run / status / template 真实执行路径（mock 命令模块内 HTTP 符号）
# =====================================================================


@pytest.fixture
def fake_http_client():
    """Patch agent_cmd 内 ensure_kernel + InkFlowHTTPClient → fake client 实例.

    __aenter__ 返回自身：`async with InkFlowHTTPClient(handle) as client` 的
    client 即本 mock，后续 post/get 等调用记录在 mock_instance 上。
    """
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
    """惰性构造 HttpApiError（infrastructure.http RED 阶段不存在，禁顶部 import）."""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _run_result(*extra_args):
    """agent run 调用（--project-id 自动补合法 UUID）。"""
    return runner.invoke(app, ["agent", "run", "--project-id", str(uuid.uuid4()), *extra_args])


def _exec_record(**overrides) -> dict:
    """执行记录 dict（GET executions/{id} 响应形态，见 agent_service.get_status）。"""
    record = {
        "execution_id": "exec-1",
        "pipeline": "builtin:write_chapter",
        "project_id": "p-1",
        "status": "pending",
        "stages": [],
        "final_output": None,
        "total_duration_ms": 0,
        "error": None,
    }
    record.update(overrides)
    return record


class TestAgentRunExecution:
    """agent run 真实执行路径：--var/--override 解析、错误分支、输出格式。"""

    _EXEC_RESULT: ClassVar[dict] = {
        "execution_id": "exec-1",
        "pipeline": "builtin:write_chapter",
        "project_id": "p-1",
        "status": "pending",
        "created_at": "2026-01-01T00:00:00",
    }

    @pytest.mark.agent
    def test_run_parses_vars_and_overrides(self, fake_http_client):
        """--var key=value / --override role.field=value 解析进请求体。"""
        fake_http_client.post.return_value = self._EXEC_RESULT
        result = _run_result(
            "--chapter-id",
            str(uuid.uuid4()),
            "--pipeline",
            "builtin:write_chapter",
            "--var",
            "k1=v1",
            "--var",
            "k2=v2",
            "--override",
            "writer.temperature=0.9",
            "--override",
            "writer.model=gpt-4o",
            "--override",
            "writer.prompt=你是资深编辑",
        )
        assert result.exit_code == 0
        call = fake_http_client.post.await_args
        assert call.args[0] == "/agent/pipelines/execute"
        req = PipelineExecuteRequest.model_validate(call.kwargs["json"])
        assert req.variables == {"k1": "v1", "k2": "v2"}
        # 三字段 override 均落入 RoleOverride
        ro = req.role_overrides["writer"]
        assert ro.temperature == 0.9
        assert ro.model == "gpt-4o"
        assert ro.prompt == "你是资深编辑"
        # 人类可读输出
        assert "🚀 管线启动: builtin:write_chapter" in result.stdout
        assert "执行 ID: exec-1" in result.stdout
        assert "状态: pending" in result.stdout

    @pytest.mark.agent
    def test_run_invalid_overrides_ignored(self, fake_http_client):
        """无效 override（缺字段 / 缺值 / 非数字 temperature）逐条提示且不阻断执行。"""
        fake_http_client.post.return_value = self._EXEC_RESULT
        result = _run_result(
            "--override",
            "writer.temperature",
            "--override",
            "writer=0.9",
            "--override",
            "writer.temperature=abc",
        )
        assert result.exit_code == 0
        assert "⚠️ 忽略无效覆盖: writer.temperature" in result.stderr
        assert "⚠️ 忽略无效覆盖: writer=0.9" in result.stderr
        assert "⚠️ 忽略无效覆盖: writer.temperature=abc" in result.stderr
        # 无效值均未生效（temperature=abc 在 float 前已建空 RoleOverride 条目——
        # 源码行为：提示忽略但条目残留，字段保持 None）
        req = PipelineExecuteRequest.model_validate(fake_http_client.post.await_args.kwargs["json"])
        ro = req.role_overrides["writer"]
        assert ro.temperature is None
        assert ro.model is None
        assert ro.prompt is None

    @pytest.mark.agent
    def test_run_agent_service_error_exit_1(self, fake_http_client):
        """HTTP 404（项目不存在）→ stderr ❌ 消息 + 退出码 1。"""
        fake_http_client.post.side_effect = _http_err(404, "项目不存在")
        result = _run_result()
        assert result.exit_code == 1
        assert "❌ 项目不存在" in result.stderr

    @pytest.mark.agent
    def test_run_json_output(self, fake_http_client):
        """--json：stdout 为单一可解析 JSON == execute 返回值，无人类行。"""
        fake_http_client.post.return_value = self._EXEC_RESULT
        result = _run_result("--json")
        assert result.exit_code == 0
        assert json.loads(result.stdout) == self._EXEC_RESULT
        assert "🚀 管线启动" not in result.stdout

    @pytest.mark.agent
    def test_run_global_json_flag(self, fake_http_client):
        """根级 --json agent run（不带 --watch）→ 立即返回，stdout 为 run_id 结果 JSON（#1478）。"""
        fake_http_client.post.return_value = self._EXEC_RESULT
        result = runner.invoke(app, ["--json", "agent", "run", "--project-id", str(uuid.uuid4())])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == self._EXEC_RESULT

    @pytest.mark.agent
    def test_run_without_watch_returns_immediately(self, fake_http_client):
        """负例：不带 --watch → 不轮询（get 零调用）+ 人类启动行（#1478 前行为守住）。"""
        fake_http_client.post.return_value = self._EXEC_RESULT
        result = _run_result()
        assert result.exit_code == 0
        fake_http_client.get.assert_not_awaited()
        assert "🚀 管线启动: builtin:write_chapter" in result.stdout
        assert "(--watch" not in result.stdout

    @pytest.mark.agent
    def test_run_kernel_startup_error(self):
        """ensure_kernel 失败（内核冷启动超时）→ stderr ❌ 内核启动失败 + 退出码 1（F38 §5.3）."""
        from inkflow.infrastructure.kernel import KernelStartupError

        with patch(
            f"{AGENT_MOD}.ensure_kernel",
            AsyncMock(side_effect=KernelStartupError("启动超时")),
        ):
            result = runner.invoke(app, ["agent", "run", "--project-id", str(uuid.uuid4())])
        assert result.exit_code == 1
        assert "❌ 内核启动失败: 启动超时" in result.stderr

    @pytest.mark.agent
    def test_run_var_without_equals_ignored(self, fake_http_client):
        """--var 无 '=' 的条目被静默忽略（不进入 variables，覆盖 L140->139 False 弧）。"""
        fake_http_client.post.return_value = self._EXEC_RESULT
        result = _run_result("--var", "novalue")
        assert result.exit_code == 0
        req = PipelineExecuteRequest.model_validate(fake_http_client.post.await_args.kwargs["json"])
        assert req.variables == {}

    @pytest.mark.agent
    def test_run_override_unknown_field_ignored(self, fake_http_client):
        """--override 未知字段 → 静默忽略（覆盖 L157->146 False 弧）。"""
        fake_http_client.post.return_value = self._EXEC_RESULT
        result = _run_result("--override", "writer.custom=1")
        assert result.exit_code == 0
        req = PipelineExecuteRequest.model_validate(fake_http_client.post.await_args.kwargs["json"])
        ro = req.role_overrides["writer"]
        assert ro.temperature is None
        assert ro.model is None
        assert ro.prompt is None

    @pytest.mark.agent
    def test_run_none_result_returns(self, fake_http_client):
        """POST 返回 None → 静默 return 不输出（同 runs list/show 的 None 语义，#1478 补守卫）。"""
        fake_http_client.post.return_value = None
        result = _run_result()
        assert result.exit_code == 0
        assert result.stdout == ""


class TestAgentRunWatch:
    """#1478 ②：`run --watch` 阻塞轮询（退避 + 总超时 + 轮询失败不静默）。"""

    @pytest.fixture(autouse=True)
    def _fast_backoff(self, monkeypatch):
        """退避封顶压到 0 → 轮询不真实等待（min(interval, 0) == 0，退避算术照走）。"""
        monkeypatch.setattr(agent_cmd, "_WATCH_MAX_INTERVAL", 0.0)

    @staticmethod
    def _started() -> dict:
        return {
            "execution_id": "exec-1",
            "pipeline": "builtin:write_chapter",
            "status": "pending",
        }

    @pytest.mark.agent
    def test_watch_blocks_until_terminal_and_renders_progress(self, fake_http_client):
        """--watch：轮询到终态才返回；状态迁移与阶段完成各打印一次（去重），终态不打状态行。"""
        fake_http_client.post.return_value = self._started()
        fake_http_client.get.side_effect = [
            _exec_record(
                status="running",
                stages=[{"stage_id": "architect", "status": "completed", "duration_ms": 100}],
            ),
            _exec_record(
                status="running",
                stages=[
                    {"stage_id": "architect", "status": "completed", "duration_ms": 100},
                    {"stage_id": "writer", "status": "running", "duration_ms": 0},
                    {"status": "completed", "duration_ms": 7},  # 无 stage_id → 跳过
                ],
            ),
            _exec_record(status="completed", total_duration_ms=1234),
        ]
        result = _run_result("--watch")
        assert result.exit_code == 0
        assert fake_http_client.get.await_count == 3
        assert fake_http_client.get.await_args.args[0] == "/agent/pipelines/executions/exec-1"
        assert "🚀 管线启动: builtin:write_chapter" in result.stdout
        assert result.stdout.count("⏳ 状态: running") == 1
        assert result.stdout.count("· architect completed (100ms)") == 1
        assert "· writer" not in result.stdout
        assert "✅ 管线完成 (耗时 1234ms)" in result.stdout

    @pytest.mark.agent
    def test_watch_waits_through_hitl(self, fake_http_client):
        """waiting_hitl 非终态 → 继续轮询（CLI 不代人工确认），直到终态才返回。"""
        fake_http_client.post.return_value = self._started()
        fake_http_client.get.side_effect = [
            _exec_record(status="waiting_hitl"),
            _exec_record(status="completed", total_duration_ms=9),
        ]
        result = _run_result("--watch")
        assert result.exit_code == 0
        assert fake_http_client.get.await_count == 2
        assert "⏳ 状态: waiting_hitl" in result.stdout
        assert "✅ 管线完成 (耗时 9ms)" in result.stdout

    @pytest.mark.agent
    def test_watch_failed_terminal_reports_error(self, fake_http_client):
        """终态 failed → ❌ 管线失败 行；退出码 0（终态是结果非 CLI 错误，同 status 语义）。"""
        fake_http_client.post.return_value = self._started()
        fake_http_client.get.side_effect = [
            _exec_record(status="failed", error="阶段 'writer' 重试 3 次后仍失败: LLM 超时"),
        ]
        result = _run_result("--watch")
        assert result.exit_code == 0
        assert "❌ 管线失败: 阶段 'writer' 重试 3 次后仍失败: LLM 超时" in result.stdout

    @pytest.mark.agent
    def test_watch_timeout_exit_nonzero_keeps_run_id(self, fake_http_client):
        """总超时（mock 永不完成）→ 退出码 1 + 明确错误（含 run_id，可继续 status 轮询）。"""
        fake_http_client.post.return_value = self._started()
        fake_http_client.get.return_value = _exec_record(status="running")
        result = _run_result("--watch", "--watch-timeout", "0")
        assert result.exit_code == 1
        assert "超时" in result.stderr
        assert "exec-1" in result.stderr
        assert fake_http_client.get.await_count == 1

    @pytest.mark.agent
    def test_watch_timeout_json_error_envelope(self, fake_http_client):
        """根级 --json + 总超时 → 错误信封 WATCH_TIMEOUT（stdout）+ 退出码 1。"""
        fake_http_client.post.return_value = self._started()
        fake_http_client.get.return_value = _exec_record(status="running")
        result = runner.invoke(
            app,
            [
                "--json",
                "agent",
                "run",
                "--project-id",
                str(uuid.uuid4()),
                "--watch",
                "--watch-timeout",
                "0",
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "WATCH_TIMEOUT"
        assert "exec-1" in payload["error"]["message"]

    @pytest.mark.agent
    def test_watch_poll_error_not_silent_success(self, fake_http_client):
        """负例：轮询期间内核非 2xx → stderr ❌ + 退出码 1（不静默成功）。"""
        fake_http_client.post.return_value = self._started()
        fake_http_client.get.side_effect = _http_err(500, "内核内部错误", "INTERNAL_ERROR")
        result = _run_result("--watch")
        assert result.exit_code == 1
        assert "❌ 内核内部错误" in result.stderr

    @pytest.mark.agent
    def test_watch_json_returns_final_record(self, fake_http_client):
        """根级 --json + --watch → 阻塞到终态后 stdout 为终态记录（单一 JSON，无人类行）。"""
        fake_http_client.post.return_value = self._started()
        final = _exec_record(status="completed", total_duration_ms=4321)
        fake_http_client.get.side_effect = [_exec_record(status="running"), final]
        result = runner.invoke(
            app, ["--json", "agent", "run", "--project-id", str(uuid.uuid4()), "--watch"]
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout) == final
        assert "🚀 管线启动" not in result.stdout


class TestAgentStatusExecution:
    """agent status 真实执行路径：成功/无记录/--json/error 行。"""

    _STATUS_RESULT: ClassVar[dict] = {
        "execution_id": "exec-9",
        "pipeline": "builtin:write_chapter",
        "project_id": "p-1",
        "status": "running",
        "stages": [],
        "final_output": None,
        "total_duration_ms": 1500,
        "error": None,
    }

    @pytest.mark.agent
    def test_status_success_human(self, fake_http_client):
        """status 成功：打印 execution_id/pipeline/status/duration；error 为空不输出错误行。"""
        fake_http_client.get.return_value = self._STATUS_RESULT
        result = runner.invoke(app, ["agent", "status", "--run-id", "exec-9"])
        assert result.exit_code == 0
        assert "执行 ID: exec-9" in result.stdout
        assert "管线: builtin:write_chapter" in result.stdout
        assert "状态: running" in result.stdout
        assert "耗时: 1500ms" in result.stdout
        assert "错误:" not in result.stdout
        fake_http_client.get.assert_awaited_once_with("/agent/pipelines/executions/exec-9")

    @pytest.mark.agent
    def test_status_error_line(self, fake_http_client):
        """status 记录带 error → 输出错误行。"""
        fake_http_client.get.return_value = {
            **self._STATUS_RESULT,
            "status": "failed",
            "error": "LLM 超时",
        }
        result = runner.invoke(app, ["agent", "status", "--run-id", "exec-9"])
        assert result.exit_code == 0
        assert "错误: LLM 超时" in result.stdout

    @pytest.mark.agent
    def test_status_not_found_exit_1(self, fake_http_client):
        """status 查无记录（HTTP 404）→ stderr ❌ + 退出码 1。"""
        fake_http_client.get.side_effect = _http_err(404, "执行记录不存在")
        result = runner.invoke(app, ["agent", "status", "--run-id", "ghost"])
        assert result.exit_code == 1
        assert "❌ 执行记录不存在" in result.stderr

    @pytest.mark.agent
    def test_status_json(self, fake_http_client):
        """status --json（命令级）→ stdout 信封 {"ok": true, "data": <执行记录>}（#1478 ①）。"""
        fake_http_client.get.return_value = self._STATUS_RESULT
        result = runner.invoke(app, ["agent", "status", "--run-id", "exec-9", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"ok": True, "data": self._STATUS_RESULT}
        assert "执行 ID:" not in result.stdout

    @pytest.mark.agent
    def test_status_global_json_envelope(self, fake_http_client):
        """根级 --json agent status → 信封含 run_id + 状态（#1478 ①：全局 --json 曾被忽略）。"""
        fake_http_client.get.return_value = self._STATUS_RESULT
        result = runner.invoke(app, ["--json", "agent", "status", "--run-id", "exec-9"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload == {"ok": True, "data": self._STATUS_RESULT}
        assert payload["data"]["execution_id"] == "exec-9"
        assert payload["data"]["status"] == "running"

    @pytest.mark.agent
    def test_status_global_json_error_envelope(self, fake_http_client):
        """根级 --json + 404 → 错误信封（stdout）+ 退出码 1（print_error 通道）。"""
        fake_http_client.get.side_effect = _http_err(404, "执行记录不存在")
        result = runner.invoke(app, ["--json", "agent", "status", "--run-id", "ghost"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"] == {"code": "NOT_FOUND", "message": "执行记录不存在"}

    @pytest.mark.agent
    def test_status_none_result_exit_1(self, fake_http_client):
        """status get 返回 None → 「❌ 执行记录不存在」+ exit 1（覆盖 128-129）。"""
        fake_http_client.get.return_value = None
        result = runner.invoke(app, ["agent", "status", "--run-id", "ghost"])
        assert result.exit_code == 1
        assert "❌ 执行记录不存在" in result.stderr


class TestAgentValidateExecution:
    """agent validate 真实执行：读 YAML → POST /agent/pipelines/validate（#251 P3）。"""

    _VALID_RESULT: ClassVar[dict] = {"valid": True, "errors": []}

    @pytest.mark.agent
    def test_validate_reads_yaml_and_posts(self, fake_http_client, tmp_path):
        """读 YAML 文件 → POST /agent/pipelines/validate（body source=yaml）。"""
        yaml_file = tmp_path / "pipeline.yaml"
        yaml_file.write_text(
            "name: 测试管线\n"
            "description: 测试\n"
            "stages:\n"
            "  - id: writer\n"
            "    name: 写手\n"
            "    agent:\n"
            "      id: writer\n"
            "      name: 写手\n"
            "      system_prompt: 你是写手\n"
            "    input_from: []\n"
            "    output_to: []\n",
            encoding="utf-8",
        )
        fake_http_client.post.return_value = self._VALID_RESULT
        result = runner.invoke(app, ["agent", "validate", "--file", str(yaml_file)])
        assert result.exit_code == 0
        assert "✅" in result.output
        call = fake_http_client.post.await_args
        assert call is not None, "POST 未被调用"
        assert call.args[0] == "/agent/pipelines/validate"
        body = call.kwargs.get("json") or {}
        assert body["source"] == "yaml"
        assert body["name"] == "测试管线"

    @pytest.mark.agent
    def test_validate_file_not_found(self, fake_http_client):
        """文件不存在 → VALIDATION_ERROR 信封 + 退出码 1，不调 POST。"""
        result = runner.invoke(app, ["agent", "validate", "--file", "nonexistent.yaml"])
        assert result.exit_code == 1
        fake_http_client.post.assert_not_awaited()

    @pytest.mark.agent
    def test_validate_yaml_parse_error(self, fake_http_client, tmp_path):
        """非法 YAML → VALIDATION_ERROR + 退出码 1，不调 POST。"""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("name: [unclosed\n", encoding="utf-8")
        result = runner.invoke(app, ["agent", "validate", "--file", str(yaml_file)])
        assert result.exit_code == 1
        fake_http_client.post.assert_not_awaited()

    @pytest.mark.agent
    def test_validate_non_mapping(self, fake_http_client, tmp_path):
        """YAML 非映射（列表）→ VALIDATION_ERROR + 退出码 1，不调 POST。"""
        yaml_file = tmp_path / "list.yaml"
        yaml_file.write_text("- item1\n- item2\n", encoding="utf-8")
        result = runner.invoke(app, ["agent", "validate", "--file", str(yaml_file)])
        assert result.exit_code == 1
        fake_http_client.post.assert_not_awaited()

    @pytest.mark.agent
    def test_validate_invalid_pipeline(self, fake_http_client, tmp_path):
        """后端返回 valid=False → ❌ 管线配置无效 + errors 回显。"""
        yaml_file = tmp_path / "pipeline.yaml"
        yaml_file.write_text("name: x\nstages: []\n", encoding="utf-8")
        fake_http_client.post.return_value = {"valid": False, "errors": ["阶段为空"]}
        result = runner.invoke(app, ["agent", "validate", "--file", str(yaml_file)])
        assert result.exit_code == 0
        assert "❌ 管线配置无效" in result.output
        assert "阶段为空" in result.output

    @pytest.mark.agent
    def test_validate_json_output(self, fake_http_client, tmp_path):
        """根级 --json → 成功信封 data = {valid, errors}。"""
        yaml_file = tmp_path / "pipeline.yaml"
        yaml_file.write_text("name: x\nstages: []\n", encoding="utf-8")
        fake_http_client.post.return_value = {"valid": True, "errors": []}
        result = runner.invoke(app, ["--json", "agent", "validate", "--file", str(yaml_file)])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["valid"] is True

    @pytest.mark.agent
    def test_validate_missing_file_json_exit_1(self, fake_http_client, monkeypatch):
        """根级 --json + 文件不存在 → exit 1，不调 POST（覆盖 L246）。

        print_error 恒 raise typer.Exit → 其后 `raise typer.Exit(1)` 为死代码；
        测试内 no-op patch print_error，由 L246 自身抛出 Exit(1) 使其可达。
        """
        from inkflow.cli.commands import agent_cmd as _agent_cmd

        monkeypatch.setattr(_agent_cmd, "print_error", lambda *a, **k: None)
        result = runner.invoke(app, ["--json", "agent", "validate", "--file", "nonexistent.yaml"])
        assert result.exit_code == 1
        fake_http_client.post.assert_not_awaited()


class TestAgentTemplateExecution:
    """agent template pipelines 真实执行路径：有/无模板 + --json
    （#251：template 升级为管理组后，旧「列出内置管线模板」迁移至 pipelines 子命令）。"""

    _TPL: ClassVar[dict] = {
        "id": "builtin:write_chapter",
        "name": "章节写作",
        "stages": ["architect", "writer"],
    }

    @pytest.mark.agent
    def test_template_list_with_items(self, fake_http_client):
        """有模板：列出 id/name/阶段链。"""
        fake_http_client.get.return_value = {"items": [self._TPL]}
        result = runner.invoke(app, ["agent", "template", "pipelines"])
        assert result.exit_code == 0
        assert "内置管线模板:" in result.stdout
        assert "  [builtin:write_chapter] 章节写作" in result.stdout
        assert "      阶段: architect → writer" in result.stdout

    @pytest.mark.agent
    def test_template_list_empty(self, fake_http_client):
        """无模板：📭 空提示。"""
        fake_http_client.get.return_value = {"items": []}
        result = runner.invoke(app, ["agent", "template", "pipelines"])
        assert result.exit_code == 0
        assert "📭 暂无可用的管线模板" in result.stdout

    @pytest.mark.agent
    def test_template_json(self, fake_http_client):
        """template --json：stdout 为单一可解析 JSON。"""
        fake_http_client.get.return_value = {"items": [self._TPL]}
        result = runner.invoke(app, ["agent", "template", "pipelines", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"items": [self._TPL]}
        assert "内置管线模板" not in result.stdout

    @pytest.mark.agent
    def test_template_crud_list_with_items(self, fake_http_client):
        """agent template list（CRUD 组）有 items → 逐条输出（含默认标记）。"""
        fake_http_client.get.return_value = {
            "items": [{"id": 1, "name": "模板A", "is_default": True}]
        }
        result = runner.invoke(app, ["agent", "template", "list"])
        assert result.exit_code == 0
        assert "[1] 模板A" in result.output
        assert "⭐ 默认" in result.output


class TestAgentListShowNoneExecution:
    """agent list / show 的 mock 返回 None → data None → 静默 return（覆盖 L77-78 / L108-109）。"""

    @pytest.mark.agent
    def test_list_none_result_returns(self, fake_http_client):
        """GET /agents 返回 None → 直接 return，不输出、不抛错。"""
        fake_http_client.get.return_value = None
        result = runner.invoke(app, ["agent", "list"])
        assert result.exit_code == 0
        assert result.stdout == ""
        fake_http_client.get.assert_awaited_once_with("/agents")

    @pytest.mark.agent
    def test_show_none_result_returns(self, fake_http_client):
        """GET /agents/{id} 返回 None → 直接 return，不输出、不抛错。"""
        fake_http_client.get.return_value = None
        result = runner.invoke(app, ["agent", "show", "--id", "1"])
        assert result.exit_code == 0
        assert result.stdout == ""
        fake_http_client.get.assert_awaited_once_with("/agents/1")
