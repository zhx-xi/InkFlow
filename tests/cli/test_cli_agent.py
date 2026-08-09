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
"""

import json
import uuid
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app
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
        """inkflow agent run --help 输出帮助信息。"""
        result = runner.invoke(app, ["agent", "run", "--help"])
        assert result.exit_code == 0
        assert "--project-id" in self._strip_ansi(result.stdout)

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
    def test_agent_template_list_help(self):
        """inkflow agent template list --help。"""
        result = runner.invoke(app, ["agent", "template", "--help"])
        assert result.exit_code == 0
        assert "--json" in self._strip_ansi(result.stdout)


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
    return runner.invoke(
        app, ["agent", "run", "--project-id", str(uuid.uuid4()), *extra_args]
    )


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
        req = PipelineExecuteRequest.model_validate(
            fake_http_client.post.await_args.kwargs["json"]
        )
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
    def test_run_watch_hint(self, fake_http_client):
        """--watch（非 json）：输出 Phase 2 占位提示。"""
        fake_http_client.post.return_value = self._EXEC_RESULT
        result = _run_result("--watch")
        assert result.exit_code == 0
        assert "(--watch 功能将在 Phase 2 完善)" in result.stdout

    @pytest.mark.agent
    def test_run_kernel_startup_error(self):
        """ensure_kernel 失败（内核冷启动超时）→ stderr ❌ 内核启动失败 + 退出码 1（F38 §5.3）."""
        from inkflow.infrastructure.kernel import KernelStartupError

        with patch(
            f"{AGENT_MOD}.ensure_kernel",
            AsyncMock(side_effect=KernelStartupError("启动超时")),
        ):
            result = runner.invoke(
                app, ["agent", "run", "--project-id", str(uuid.uuid4())]
            )
        assert result.exit_code == 1
        assert "❌ 内核启动失败: 启动超时" in result.stderr


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
        fake_http_client.get.assert_awaited_once_with(
            "/agent/pipelines/executions/exec-9"
        )

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
        """status --json：stdout 为单一可解析 JSON == get_status 返回值。"""
        fake_http_client.get.return_value = self._STATUS_RESULT
        result = runner.invoke(app, ["agent", "status", "--run-id", "exec-9", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == self._STATUS_RESULT
        assert "执行 ID:" not in result.stdout


class TestAgentValidateExecution:
    """agent validate 真实执行：Phase 1 占位提示。"""

    @pytest.mark.agent
    def test_validate_prints_phase2_hint(self):
        """validate：打印 Phase 2 占位提示 + 文件路径回显。"""
        result = runner.invoke(app, ["agent", "validate", "--file", "pipeline.yaml"])
        assert result.exit_code == 0
        assert "⚠️ YAML 管线校验将在 Phase 2 实现" in result.stdout
        assert "   文件: pipeline.yaml" in result.stdout


class TestAgentTemplateExecution:
    """agent template 真实执行路径：有/无模板 + --json。"""

    _TPL: ClassVar[dict] = {
        "id": "builtin:write_chapter",
        "name": "章节写作",
        "stages": ["architect", "writer"],
    }

    @pytest.mark.agent
    def test_template_list_with_items(self, fake_http_client):
        """有模板：列出 id/name/阶段链。"""
        fake_http_client.get.return_value = {"items": [self._TPL]}
        result = runner.invoke(app, ["agent", "template"])
        assert result.exit_code == 0
        assert "内置管线模板:" in result.stdout
        assert "  [builtin:write_chapter] 章节写作" in result.stdout
        assert "      阶段: architect → writer" in result.stdout

    @pytest.mark.agent
    def test_template_list_empty(self, fake_http_client):
        """无模板：📭 空提示。"""
        fake_http_client.get.return_value = {"items": []}
        result = runner.invoke(app, ["agent", "template"])
        assert result.exit_code == 0
        assert "📭 暂无可用的管线模板" in result.stdout

    @pytest.mark.agent
    def test_template_json(self, fake_http_client):
        """template --json：stdout 为单一可解析 JSON。"""
        fake_http_client.get.return_value = {"items": [self._TPL]}
        result = runner.invoke(app, ["agent", "template", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"items": [self._TPL]}
        assert "内置管线模板" not in result.stdout
