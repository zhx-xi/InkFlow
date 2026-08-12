"""CLI Agent Template 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（HTTP JSON 响应）。

测试范围：#251 P1-B — inkflow agent template list/get/create/update/delete/
duplicate/set-default/get-default + pipelines（既有「列出内置管线模板」迁移）。

HTTP 契约（实现者以本文件为准，agent_templates.py 8 端点）:
- list         → GET  /agent-templates                 → {"items": [...], "total": N}
- get          → GET  /agent-templates/{id}            → 404 「模板不存在」
- create       → POST /agent-templates                 → 201 完整响应（roles 四键归一）
- update       → PATCH /agent-templates/{id}           → 完整响应（roles 整体替换）
- delete       → DELETE /agent-templates/{id}          → 204 空响应；默认模板 → 409
                  「默认模板不可删除」
- duplicate    → POST /agent-templates/{id}/duplicate  → 201（name = 原名称 副本）
- set-default  → PATCH /agent-templates/default {id}   → 完整响应
- get-default  → GET  /agent-templates/default         → {"template": null|完整响应}
- pipelines    → GET  /agent/pipelines/templates       → {"items": [...]}（迁移自
                  旧叶子 `agent template`，#251「扩展为管理组」）
- 路径一律相对 base_url（InkFlowHTTPClient base_url 已含 /api/v1，#246 教训）

── RED 形态说明 ────────────────────────────────────────────────
agent_cmd.py 当前 `template` 为叶子命令（无 template_app 子组、无 create 等
子命令）→ 用例 invoke ["agent", "template", "list"] 等报 No such command
exit 2（断言 FAIL）；test_agent_template_pipelines_help 中 pipelines 同样
不存在（exit 2 断言 FAIL）——命令模块 ensure_kernel/InkFlowHTTPClient 已存在，
fixture 正常，纯断言 FAIL（非 AttributeError）。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.context import CliContext

AGENT_MOD = "inkflow.cli.commands.agent_cmd"


@pytest.fixture
def cli_runner():
    # click 8.4 / typer 0.27 已移除 mix_stderr 参数，默认混合输出
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Patch agent_cmd 内 ensure_kernel + InkFlowHTTPClient → fake client 实例.

    __aenter__ 返回自身：async with InkFlowHTTPClient(handle) as client 的
    client 即本 mock，后续 get/post/patch/delete 调用记录在 mock_instance 上。
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


def _http_error(status_code: int, detail: str, code: str | None = None):
    """惰性构造 HttpApiError."""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _make_template(**overrides) -> dict:
    """构造测试用 AgentTemplate JSON dict（roles 四键归一响应形态）."""
    defaults = dict(
        id=1,
        name="默认模板",
        description="",
        main_model="openai/gpt-4o",
        default_temperature=0.7,
        roles={
            "architect": {
                "model": "openai/gpt-4o",
                "temperature": None,
                "enabled": True,
            },
            "writer": {"model": "openai/gpt-4o", "temperature": None, "enabled": True},
            "auditor": {"model": "openai/gpt-4o", "temperature": None, "enabled": True},
            "reviser": {"model": "openai/gpt-4o", "temperature": None, "enabled": True},
        },
        default_words=800000,
        is_default=False,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


class TestTemplateHelp:
    def test_template_group_help(self, cli_runner):
        """agent template --help 显示管理组子命令（#251 扩展为管理组）."""
        from inkflow.cli.commands.agent_cmd import app

        result = cli_runner.invoke(app, ["template", "--help"])
        assert result.exit_code == 0
        for cmd in [
            "list",
            "create",
            "update",
            "delete",
            "duplicate",
            "set-default",
            "get-default",
            "pipelines",
        ]:
            assert cmd in result.stdout

    def test_template_pipelines_help(self, cli_runner):
        """agent template pipelines --help 保留旧 --json（迁移后旧功能）。

        注意 CI 环境 help 输出含 ANSI 转义码（rich 渲染），断言前必须 strip
        （#300 CI 实测：本地子组 help 无 ANSI、CI 有 → '--json' 子串被截断）。
        """
        import re

        from inkflow.cli.commands.agent_cmd import app

        result = cli_runner.invoke(app, ["template", "pipelines", "--help"])
        assert result.exit_code == 0
        text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
        assert "--json" in text


class TestTemplateList:
    def test_list_json(self, cli_runner, fake_http_client):
        """agent template list --json → 信封 + GET /agent-templates."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.get.return_value = {"items": [_make_template()], "total": 1}
        result = cli_runner.invoke(
            app, ["template", "list"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["total"] == 1
        assert data["data"]["items"][0]["name"] == "默认模板"
        assert fake_http_client.get.await_args.args[0] == "/agent-templates"

    def test_list_human_empty(self, cli_runner, fake_http_client):
        """空列表人类模式."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            app, ["template", "list"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "暂无" in result.output or "📭" in result.output


class TestTemplateGet:
    def test_get_json(self, cli_runner, fake_http_client):
        """agent template get --id 1 → 信封."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.get.return_value = _make_template()
        result = cli_runner.invoke(
            app, ["template", "get", "--id", "1"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "默认模板"
        assert fake_http_client.get.await_args.args[0] == "/agent-templates/1"

    def test_get_not_found(self, cli_runner, fake_http_client):
        """不存在 → NOT_FOUND."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.get.side_effect = _http_error(404, "模板不存在")
        result = cli_runner.invoke(
            app, ["template", "get", "--id", "999"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "NOT_FOUND"


class TestTemplateCreate:
    def test_create_json(self, cli_runner, fake_http_client):
        """创建模板 → POST /agent-templates + 信封."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.post.return_value = _make_template(id=2, name="新模板")
        result = cli_runner.invoke(
            app,
            ["template", "create", "--name", "新模板"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "新模板"
        call = fake_http_client.post.await_args
        assert call.args[0] == "/agent-templates"
        assert call.kwargs["json"]["name"] == "新模板"

    def test_create_with_roles_json(self, cli_runner, fake_http_client):
        """--roles-json 四键 roles 整体透传."""
        from inkflow.cli.commands.agent_cmd import app

        roles = {
            "architect": {
                "model": "deepseek/deepseek-chat",
                "temperature": 0.3,
                "enabled": True,
            },
            "writer": {"model": "zhipu/glm-4.5", "temperature": None, "enabled": True},
        }
        fake_http_client.post.return_value = _make_template(id=2, name="双角色")
        result = cli_runner.invoke(
            app,
            [
                "template",
                "create",
                "--name",
                "双角色",
                "--roles-json",
                json.dumps(roles),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.post.await_args
        assert call.kwargs["json"]["roles"] == roles

    def test_create_conflict_422(self, cli_runner, fake_http_client):
        """重名冲突 → VALIDATION_ERROR."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.post.side_effect = _http_error(422, "模板名称已存在")
        result = cli_runner.invoke(
            app,
            ["template", "create", "--name", "默认模板"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"


class TestTemplateUpdate:
    def test_update_json(self, cli_runner, fake_http_client):
        """更新模板 → PATCH /agent-templates/{id} + 信封."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.patch.return_value = _make_template(description="新描述")
        result = cli_runner.invoke(
            app,
            ["template", "update", "--id", "1", "--description", "新描述"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["description"] == "新描述"
        call = fake_http_client.patch.await_args
        assert call.args[0] == "/agent-templates/1"
        assert call.kwargs["json"] == {"description": "新描述"}

    def test_update_not_found(self, cli_runner, fake_http_client):
        """不存在 → NOT_FOUND."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.patch.side_effect = _http_error(404, "模板不存在")
        result = cli_runner.invoke(
            app,
            ["template", "update", "--id", "999", "--description", "x"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "NOT_FOUND"


class TestTemplateDelete:
    def test_delete_force_json(self, cli_runner, fake_http_client):
        """--force 删除 → DELETE /agent-templates/{id} + {deleted: true}."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.delete.return_value = {}
        result = cli_runner.invoke(
            app,
            ["template", "delete", "--id", "3", "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        assert fake_http_client.delete.await_args.args[0] == "/agent-templates/3"

    def test_delete_without_force_prompts(self, cli_runner, fake_http_client):
        """无 --force 交互确认，回答 n 取消."""
        from inkflow.cli.commands.agent_cmd import app

        result = cli_runner.invoke(
            app,
            ["template", "delete", "--id", "3"],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "取消" in result.output
        fake_http_client.delete.assert_not_awaited()

    def test_delete_json_without_force_rejected(self, cli_runner, fake_http_client):
        """--json + 无 --force → VALIDATION_ERROR 短路."""
        from inkflow.cli.commands.agent_cmd import app

        result = cli_runner.invoke(
            app,
            ["template", "delete", "--id", "3"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.delete.assert_not_awaited()

    def test_delete_default_409(self, cli_runner, fake_http_client):
        """默认模板删除 → 409「默认模板不可删除」→ INTERNAL_ERROR 信封."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.delete.side_effect = _http_error(409, "默认模板不可删除")
        result = cli_runner.invoke(
            app,
            ["template", "delete", "--id", "1", "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert "默认模板不可删除" in data["error"]["message"]


class TestTemplateDuplicate:
    def test_duplicate_json(self, cli_runner, fake_http_client):
        """复制模板 → POST /agent-templates/{id}/duplicate."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.post.return_value = _make_template(id=4, name="默认模板 副本")
        result = cli_runner.invoke(
            app,
            ["template", "duplicate", "--id", "1"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert (
            fake_http_client.post.await_args.args[0] == "/agent-templates/1/duplicate"
        )

    def test_duplicate_not_found(self, cli_runner, fake_http_client):
        """源模板不存在 → NOT_FOUND."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.post.side_effect = _http_error(404, "模板不存在")
        result = cli_runner.invoke(
            app,
            ["template", "duplicate", "--id", "999"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "NOT_FOUND"


class TestTemplateSetDefault:
    def test_set_default_json(self, cli_runner, fake_http_client):
        """设为默认 → PATCH /agent-templates/default {id}."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.patch.return_value = _make_template(is_default=True)
        result = cli_runner.invoke(
            app,
            ["template", "set-default", "--id", "1"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        call = fake_http_client.patch.await_args
        assert call.args[0] == "/agent-templates/default"
        assert call.kwargs["json"] == {"id": "1"}

    def test_set_default_not_found(self, cli_runner, fake_http_client):
        """模板不存在 → NOT_FOUND."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.patch.side_effect = _http_error(404, "模板不存在")
        result = cli_runner.invoke(
            app,
            ["template", "set-default", "--id", "999"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "NOT_FOUND"


class TestTemplateGetDefault:
    def test_get_default_null(self, cli_runner, fake_http_client):
        """无默认模板 → {template: null} 信封."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.get.return_value = {"template": None}
        result = cli_runner.invoke(
            app,
            ["template", "get-default"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["template"] is None

    def test_get_default_with_template(self, cli_runner, fake_http_client):
        """有默认模板 → 完整响应."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.get.return_value = {
            "template": _make_template(is_default=True)
        }
        result = cli_runner.invoke(
            app,
            ["template", "get-default"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["template"]["name"] == "默认模板"


class TestTemplatePipelines:
    def test_pipelines_json(self, cli_runner, fake_http_client):
        """agent template pipelines --json → GET /agent/pipelines/templates（迁移）."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.get.return_value = {
            "items": [
                {"id": "builtin:write_chapter", "name": "写章", "stages": ["architect"]}
            ]
        }
        result = cli_runner.invoke(
            app, ["template", "pipelines"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["items"][0]["id"] == "builtin:write_chapter"
        assert fake_http_client.get.await_args.args[0] == "/agent/pipelines/templates"

    def test_pipelines_human(self, cli_runner, fake_http_client):
        """人类模式列出内置管线模板."""
        from inkflow.cli.commands.agent_cmd import app

        fake_http_client.get.return_value = {
            "items": [
                {"id": "builtin:write_chapter", "name": "写章", "stages": ["architect"]}
            ]
        }
        result = cli_runner.invoke(
            app, ["template", "pipelines"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "builtin:write_chapter" in result.output
