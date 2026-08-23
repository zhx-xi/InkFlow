"""Project Update CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（HTTP JSON 响应）。

测试范围：#251 P1-C — inkflow project update（config 字段级更新，#225 三态语义）。

HTTP 契约（实现者以本文件为准，project.py PATCH 端点 + project_service 合并语义）:
- update → PATCH /projects/{id}
  - 顶层字段: name/tags/language/target_words（exclude_unset 浅合并）
  - config 字段级: body {"config": {字段...}}（服务层 model_copy 合并，字段级生效）
  - 三态（#225）: "null" → None（关闭）/ "__default__" → sentinel（跟随默认）/
    字符串（provider/model 指定模型）；数字值 → int/float；JSON 数组/对象解析
  - --config KEY=VALUE 可重复；--config-json '{...}' 整体 dict（F42 §4 形态，
    与 --config 合并：config-json 先、--config 覆盖）
  - agent_order 嵌套 JSON 值经 --config 透传（F42 §2.1 list[list[str]]，后端
    字段落位后经既有合并语义生效）
- 路径一律相对 base_url（InkFlowHTTPClient base_url 已含 /api/v1，#246 教训）

── RED 形态说明 ────────────────────────────────────────────────
project.py 当前无 update 命令 → invoke ["update", ...] 报 No such command
exit 2（断言 FAIL）；project.py ensure_kernel/InkFlowHTTPClient 已存在，
fixture 正常，纯断言 FAIL（非 AttributeError）。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner():
    # click 8.4 / typer 0.27 已移除 mix_stderr 参数，默认混合输出
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（镜像 test_cli_project_mock.py）."""
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
            "inkflow.cli.commands.project.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.project.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_error(status_code: int, detail: str, code: str | None = None):
    """惰性构造 HttpApiError."""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _make_project(**overrides) -> dict:
    """构造测试用项目 JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id="1",
        name="星辰变",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
        config={
            "model": "gpt-4o",
            "agent_architect": None,
            "agent_writer": "deepseek/deepseek-chat",
            "agent_auditor": None,
            "agent_reviser": None,
            "temperature": 0.7,
            "role_architect_temperature": None,
            "role_writer_temperature": None,
            "role_auditor_temperature": None,
            "role_reviser_temperature": None,
            "template_id": None,
            "writing_style": "",
            "default_words": 800000,
            "extra": {},
        },
        is_deleted=False,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


class TestProjectUpdateBasic:
    def test_update_uuid_id(self, cli_runner, fake_http_client):
        """--id 支持 UUID 字符串（真实项目 id 为 UUID，#251 冒烟实证）。

        RED 预期：当前 --id 为 int 选项 → UUID 字符串解析失败 exit 2 → 断言
        FAIL。GREEN 后 --id 改 str 原样透传路径。
        """
        from inkflow.cli.commands.project import app

        pid = "00000000-0000-0000-0000-000000000001"
        fake_http_client.patch.return_value = _make_project(id=pid)
        result = cli_runner.invoke(
            app,
            ["update", "--id", pid, "--name", "新书名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.args[0] == f"/projects/{pid}"

    def test_update_name_json(self, cli_runner, fake_http_client):
        """更新顶层 name → PATCH /projects/{id} + 信封."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project(name="新书名")
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--name", "新书名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "新书名"
        call = fake_http_client.patch.await_args
        assert call.args[0] == "/projects/1"
        assert call.kwargs["json"] == {"name": "新书名"}

    def test_update_human(self, cli_runner, fake_http_client):
        """人类模式更新成功提示."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project(name="新书名")
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--name", "新书名"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "新书名" in result.output

    def test_update_tags(self, cli_runner, fake_http_client):
        """--tags 多值标签 → 原样进 body."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project(tags=["科幻"])
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--tags", "科幻"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {"tags": ["科幻"]}

    def test_update_language(self, cli_runner, fake_http_client):
        """--language 透传进 body."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project(language="en-US")
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--language", "en-US"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {"language": "en-US"}

    def test_update_target_words(self, cli_runner, fake_http_client):
        """--target-words int → body."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project(target_words=500000)
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--target-words", "500000"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {"target_words": 500000}


class TestProjectUpdateConfigTristate:
    def test_config_string_model(self, cli_runner, fake_http_client):
        """--config agent_writer=zhipu/glm-4.5 → 字符串指定模型."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project()
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config", "agent_writer=zhipu/glm-4.5"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {"config": {"agent_writer": "zhipu/glm-4.5"}}

    def test_config_sentinel_default(self, cli_runner, fake_http_client):
        """--config agent_writer=__default__ → sentinel（跟随默认）."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project()
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config", "agent_writer=__default__"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {"config": {"agent_writer": "__default__"}}

    def test_config_null_disables(self, cli_runner, fake_http_client):
        """--config agent_writer=null → None（关闭角色，#225 三态）."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project()
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config", "agent_writer=null"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {"config": {"agent_writer": None}}

    def test_config_number_value(self, cli_runner, fake_http_client):
        """--config temperature=0.5 → float 数值."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project()
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config", "temperature=0.5"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {"config": {"temperature": 0.5}}

    def test_config_multiple_keys(self, cli_runner, fake_http_client):
        """多个 --config 合并进同一 config body."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project()
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                "1",
                "--config",
                "agent_writer=zhipu/glm-4.5",
                "--config",
                "temperature=0.8",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {
            "config": {"agent_writer": "zhipu/glm-4.5", "temperature": 0.8}
        }

    def test_config_int_value(self, cli_runner, fake_http_client):
        """--config 整数 → int 值（_parse_config_value int 分支）."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project()
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config", "default_words=100000"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {"config": {"default_words": 100000}}

    def test_config_without_equals(self, cli_runner, fake_http_client):
        """--config 无 = → VALIDATION_ERROR + 不调用 PATCH."""
        from inkflow.cli.commands.project import app

        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config", "agent_writer"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "KEY=VALUE" in data["error"]["message"]
        fake_http_client.patch.assert_not_awaited()

    def test_config_json_not_object(self, cli_runner, fake_http_client):
        """--config-json 非 JSON 对象 → VALIDATION_ERROR + 不调用 PATCH."""
        from inkflow.cli.commands.project import app

        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config-json", '["a", "b"]'],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "JSON 对象" in data["error"]["message"]
        fake_http_client.patch.assert_not_awaited()


class TestProjectUpdateAgentOrder:
    def test_config_agent_order_json_value(self, cli_runner, fake_http_client):
        """--config agent_order=[...] 嵌套 JSON → list[list[str]] 透传（F42 §2.1）."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project()
        order = (
            '[["agent_architect"],["agent_writer","agent_auditor"],["agent_reviser"]]'
        )
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config", f"agent_order={order}"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {
            "config": {
                "agent_order": [
                    ["agent_architect"],
                    ["agent_writer", "agent_auditor"],
                    ["agent_reviser"],
                ]
            }
        }

    def test_config_agent_order_empty_layers(self, cli_runner, fake_http_client):
        """agent_order 空槽（[]）与跳号 JSON 原样透传."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project()
        order = '[["agent_architect"],[],["agent_writer"]]'
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config", f"agent_order={order}"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {
            "config": {"agent_order": [["agent_architect"], [], ["agent_writer"]]}
        }

    def test_config_bad_json_falls_back_to_string(self, cli_runner, fake_http_client):
        """JSON 解析失败 → 回落字符串原样透传（后端校验兜底）."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project()
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config", "agent_order=[bad"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {"config": {"agent_order": "[bad"}}


class TestProjectUpdateConfigJson:
    def test_config_json_whole_dict(self, cli_runner, fake_http_client):
        """--config-json 整体 dict 透传（F42 §4 形态）."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project()
        cfg = '{"agent_writer": "zhipu/glm-4.5", "temperature": 0.5}'
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config-json", cfg],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {
            "config": {"agent_writer": "zhipu/glm-4.5", "temperature": 0.5}
        }

    def test_config_json_merged_with_config_flag(self, cli_runner, fake_http_client):
        """--config-json 与 --config 合并（--config 覆盖同键）."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.return_value = _make_project()
        cfg = '{"agent_writer": "zhipu/glm-4.5", "temperature": 0.5}'
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                "1",
                "--config-json",
                cfg,
                "--config",
                "temperature=0.9",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"] == {
            "config": {"agent_writer": "zhipu/glm-4.5", "temperature": 0.9}
        }

    def test_config_json_invalid(self, cli_runner, fake_http_client):
        """--config-json 非法 JSON → VALIDATION_ERROR 信封 + 退出码 1."""
        from inkflow.cli.commands.project import app

        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config-json", "{bad"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.patch.assert_not_awaited()


class TestProjectUpdateErrors:
    def test_update_not_found(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 信封 + 退出码 1."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.side_effect = _http_error(404, "项目不存在")
        result = cli_runner.invoke(
            app,
            ["update", "--id", "999", "--name", "x"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_update_validation_422(self, cli_runner, fake_http_client):
        """后端校验失败（如 agent_order 缺启用角色）→ VALIDATION_ERROR."""
        from inkflow.cli.commands.project import app

        fake_http_client.patch.side_effect = _http_error(
            422, "agent_order 必须包含全部启用角色: agent_writer"
        )
        result = cli_runner.invoke(
            app,
            ["update", "--id", "1", "--config", "agent_order=[[agent_architect]]"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "agent_order" in data["error"]["message"]
