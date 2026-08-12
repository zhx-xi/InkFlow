"""Context Assemble CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（HTTP JSON 响应）。

测试范围：#251 P2 — inkflow context assemble。context 命令组位于
cli/commands/context_cmd.py（命名参照 agent_cmd.py，规避 cli/context.py
的 CliContext），HTTP 轨（镜像 test_cli_llm_provider.py P1 模式）。

HTTP 契约（实现者以本文件为准，#251 任务书 + api/routers/context.py 端点 +
domain/models/context.py ContextRequest）:
- assemble → POST /context/assemble
  body: {"project_id": str(uuid), "chapter_id": str(uuid), "model": str,
         "writing_requirements": str, "max_tokens": int | None(缺省不传)}
  响应: ContextAssemblyResult.model_dump() → {"blocks": [...], "budget_tokens": int,
        "total_tokens": int, "model": str, "dropped": [...]}
- 400（ValueError / ContextBudgetExceededError）→ INTERNAL_ERROR 信封（exit 1，
  map_http_error 既有映射，detail 透传）
- 404 → NOT_FOUND 信封（exit 1）；非法 UUID → ValueError → DB_ERROR 信封
- 路径一律相对 base_url（InkFlowHTTPClient base_url 已含 /api/v1，#246 教训）

── RED 形态说明 ────────────────────────────────────────────────
context_cmd 模块整个不存在 → 顶部模块级 import 收集期 ModuleNotFoundError
（exit 2，1c 规则首选形态）；实现补齐后用例应全绿。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.context_cmd import app
from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP。

    patch 目标 = 命令模块命名空间（context_cmd 实现后 from-import 绑定自身）。
    RED 阶段模块不存在 → fixture setup ModuleNotFoundError（预期）。
    """
    fake_handle = SimpleNamespace(
        port=38293,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(
            "inkflow.cli.commands.context_cmd.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.context_cmd.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_error(status_code: int, detail: str, code: str | None = None):
    """构造 HttpApiError（lazy import：RED 阶段不影响收集形态）。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


PID = "00000000-0000-0000-0000-000000000001"
CID = "00000000-0000-0000-0000-00000000000a"


def _assembly_result(**overrides) -> dict:
    """构造 ContextAssemblyResult.model_dump() JSON 等价物."""
    defaults = dict(
        blocks=[
            {
                "item": {
                    "source": "writing_requirements",
                    "title": "写作要求",
                    "content": "保持悬疑节奏",
                    "priority": 0,
                    "metadata": {},
                },
                "layer": "protected",
                "token_count": 120,
                "compressed": False,
            }
        ],
        budget_tokens=8000,
        total_tokens=120,
        model="openai/gpt-4o",
        dropped=[],
    )
    defaults.update(overrides)
    return defaults


class TestAssemble:
    def test_assemble_json(self, cli_runner, fake_http_client):
        """context assemble 全必填参数 → POST /context/assemble + 信封."""
        fake_http_client.post.return_value = _assembly_result()
        result = cli_runner.invoke(
            app,
            [
                "assemble",
                "--project-id",
                PID,
                "--chapter-id",
                CID,
                "--model",
                "openai/gpt-4o",
                "--writing-requirements",
                "保持悬疑节奏",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["total_tokens"] == 120
        assert data["data"]["model"] == "openai/gpt-4o"
        call = fake_http_client.post.await_args
        assert call.args[0] == "/context/assemble"
        body = call.kwargs["json"]
        assert body["project_id"] == PID
        assert body["chapter_id"] == CID
        assert body["model"] == "openai/gpt-4o"
        assert body["writing_requirements"] == "保持悬疑节奏"
        assert "max_tokens" not in body

    def test_assemble_with_max_tokens(self, cli_runner, fake_http_client):
        """--max-tokens 可选参数落入请求体."""
        fake_http_client.post.return_value = _assembly_result(budget_tokens=5000)
        result = cli_runner.invoke(
            app,
            [
                "assemble",
                "--project-id",
                PID,
                "--chapter-id",
                CID,
                "--model",
                "openai/gpt-4o",
                "--writing-requirements",
                "写作要求",
                "--max-tokens",
                "5000",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert body["max_tokens"] == 5000

    def test_assemble_human(self, cli_runner, fake_http_client):
        """人类模式输出组装摘要."""
        fake_http_client.post.return_value = _assembly_result()
        result = cli_runner.invoke(
            app,
            [
                "assemble",
                "--project-id",
                PID,
                "--chapter-id",
                CID,
                "--model",
                "openai/gpt-4o",
                "--writing-requirements",
                "保持悬疑节奏",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅" in result.output
        assert "openai/gpt-4o" in result.output

    def test_assemble_budget_exceeded(self, cli_runner, fake_http_client):
        """预算超限（400）→ INTERNAL_ERROR 信封 + detail 透传 + exit 1."""
        fake_http_client.post.side_effect = _http_error(
            400, "上下文预算超限: 需求 9000 > 预算 8000"
        )
        result = cli_runner.invoke(
            app,
            [
                "assemble",
                "--project-id",
                PID,
                "--chapter-id",
                CID,
                "--model",
                "openai/gpt-4o",
                "--writing-requirements",
                "保持悬疑节奏",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert "上下文预算超限" in data["error"]["message"]

    def test_assemble_not_found(self, cli_runner, fake_http_client):
        """项目不存在（404）→ NOT_FOUND 信封 + exit 1."""
        fake_http_client.post.side_effect = _http_error(404, "项目不存在")
        result = cli_runner.invoke(
            app,
            [
                "assemble",
                "--project-id",
                PID,
                "--chapter-id",
                CID,
                "--model",
                "openai/gpt-4o",
                "--writing-requirements",
                "保持悬疑节奏",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_assemble_missing_requirements(self, cli_runner, fake_http_client):
        """缺 --writing-requirements → usage error exit 2（必填选项）."""
        result = cli_runner.invoke(
            app,
            [
                "assemble",
                "--project-id",
                PID,
                "--chapter-id",
                CID,
                "--model",
                "openai/gpt-4o",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()

    def test_assemble_invalid_uuid(self, cli_runner, fake_http_client):
        """非法 UUID → DB_ERROR 信封 + 不调用 POST."""
        result = cli_runner.invoke(
            app,
            [
                "assemble",
                "--project-id",
                "not-a-uuid",
                "--chapter-id",
                CID,
                "--model",
                "openai/gpt-4o",
                "--writing-requirements",
                "保持悬疑节奏",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"
        fake_http_client.post.assert_not_awaited()
