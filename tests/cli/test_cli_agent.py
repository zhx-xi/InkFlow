"""CLI Agent 命令集成测试 — CliRunner。

测试范围：inkflow agent run/status/validate/template --help。
需 pytest marker: @pytest.mark.agent
"""

import json
import uuid
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app
from inkflow.domain.services.agent_service import AgentServiceError

runner = CliRunner()

# patch 目标模块：agent_cmd 内的符号（绕过 DB / LLM / 真实 AgentService）
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
# agent run / status / template 真实执行路径（mock 模块内符号，绕过 DB/LLM）
# =====================================================================


@pytest.fixture
def mock_agent_service():
    """Patch agent_cmd 模块内基础设施符号 + AgentService 类。

    覆盖：create_tables（async）、async_session_factory（async CM）、
    LangGraphAgentPipeline / LangChainLLMClient（构造）、AgentService（实例方法
    execute/get_status 为 AsyncMock，list_templates 为同步 MagicMock）。
    """
    with (
        patch(f"{AGENT_MOD}.create_tables", AsyncMock()),
        patch(f"{AGENT_MOD}.async_session_factory", MagicMock()) as mock_factory,
        patch(f"{AGENT_MOD}.LangGraphAgentPipeline", MagicMock()),
        patch(f"{AGENT_MOD}.LangChainLLMClient", MagicMock()),
        patch(f"{AGENT_MOD}.AgentService", MagicMock()) as mock_svc_cls,
    ):
        # async_session_factory() 必须返回支持 async with 的 CM：
        # MagicMock 调用返回子 mock（同步），其 __aenter__/__aexit__ 设为 AsyncMock
        mock_factory.return_value.__aenter__ = AsyncMock(return_value="session")
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_svc = MagicMock()
        mock_svc.execute = AsyncMock()
        mock_svc.get_status = AsyncMock()
        mock_svc.list_templates = MagicMock()
        mock_svc_cls.return_value = mock_svc
        yield mock_svc


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
    def test_run_parses_vars_and_overrides(self, mock_agent_service):
        """--var key=value / --override role.field=value 解析进 PipelineExecuteRequest。"""
        mock_agent_service.execute.return_value = self._EXEC_RESULT
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
        mock_agent_service.execute.assert_awaited_once()
        req = mock_agent_service.execute.await_args.args[0]
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
    def test_run_invalid_overrides_ignored(self, mock_agent_service):
        """无效 override（缺字段 / 缺值 / 非数字 temperature）逐条提示且不阻断执行。"""
        mock_agent_service.execute.return_value = self._EXEC_RESULT
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
        req = mock_agent_service.execute.await_args.args[0]
        ro = req.role_overrides["writer"]
        assert ro.temperature is None
        assert ro.model is None
        assert ro.prompt is None

    @pytest.mark.agent
    def test_run_agent_service_error_exit_1(self, mock_agent_service):
        """AgentServiceError → stderr ❌ 消息 + 退出码 1。"""
        mock_agent_service.execute.side_effect = AgentServiceError("项目不存在")
        result = _run_result()
        assert result.exit_code == 1
        assert "❌ 项目不存在" in result.stderr

    @pytest.mark.agent
    def test_run_json_output(self, mock_agent_service):
        """--json：stdout 为单一可解析 JSON == execute 返回值，无人类行。"""
        mock_agent_service.execute.return_value = self._EXEC_RESULT
        result = _run_result("--json")
        assert result.exit_code == 0
        assert json.loads(result.stdout) == self._EXEC_RESULT
        assert "🚀 管线启动" not in result.stdout

    @pytest.mark.agent
    def test_run_watch_hint(self, mock_agent_service):
        """--watch（非 json）：输出 Phase 2 占位提示。"""
        mock_agent_service.execute.return_value = self._EXEC_RESULT
        result = _run_result("--watch")
        assert result.exit_code == 0
        assert "(--watch 功能将在 Phase 2 完善)" in result.stdout


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
    def test_status_success_human(self, mock_agent_service):
        """status 成功：打印 execution_id/pipeline/status/duration；error 为空不输出错误行。"""
        mock_agent_service.get_status.return_value = self._STATUS_RESULT
        result = runner.invoke(app, ["agent", "status", "--run-id", "exec-9"])
        assert result.exit_code == 0
        assert "执行 ID: exec-9" in result.stdout
        assert "管线: builtin:write_chapter" in result.stdout
        assert "状态: running" in result.stdout
        assert "耗时: 1500ms" in result.stdout
        assert "错误:" not in result.stdout

    @pytest.mark.agent
    def test_status_error_line(self, mock_agent_service):
        """status 记录带 error → 输出错误行。"""
        mock_agent_service.get_status.return_value = {
            **self._STATUS_RESULT,
            "status": "failed",
            "error": "LLM 超时",
        }
        result = runner.invoke(app, ["agent", "status", "--run-id", "exec-9"])
        assert result.exit_code == 0
        assert "错误: LLM 超时" in result.stdout

    @pytest.mark.agent
    def test_status_not_found_exit_1(self, mock_agent_service):
        """status 查无记录 → stderr ❌ + 退出码 1。"""
        mock_agent_service.get_status.return_value = None
        result = runner.invoke(app, ["agent", "status", "--run-id", "ghost"])
        assert result.exit_code == 1
        assert "❌ 执行记录不存在" in result.stderr

    @pytest.mark.agent
    def test_status_json(self, mock_agent_service):
        """status --json：stdout 为单一可解析 JSON == get_status 返回值。"""
        mock_agent_service.get_status.return_value = self._STATUS_RESULT
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
    def test_template_list_with_items(self, mock_agent_service):
        """有模板：列出 id/name/阶段链。"""
        mock_agent_service.list_templates.return_value = {"items": [self._TPL]}
        result = runner.invoke(app, ["agent", "template"])
        assert result.exit_code == 0
        assert "内置管线模板:" in result.stdout
        assert "  [builtin:write_chapter] 章节写作" in result.stdout
        assert "      阶段: architect → writer" in result.stdout

    @pytest.mark.agent
    def test_template_list_empty(self, mock_agent_service):
        """无模板：📭 空提示。"""
        mock_agent_service.list_templates.return_value = {"items": []}
        result = runner.invoke(app, ["agent", "template"])
        assert result.exit_code == 0
        assert "📭 暂无可用的管线模板" in result.stdout

    @pytest.mark.agent
    def test_template_json(self, mock_agent_service):
        """template --json：stdout 为单一可解析 JSON。"""
        mock_agent_service.list_templates.return_value = {"items": [self._TPL]}
        result = runner.invoke(app, ["agent", "template", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"items": [self._TPL]}
        assert "内置管线模板" not in result.stdout
