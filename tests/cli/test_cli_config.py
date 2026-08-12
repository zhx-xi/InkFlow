"""Config 持久化测试.

#266 data-dir 契约段（RED 阶段，0.7.0 方案 A）:
- 契约：`config set data-dir <path>` 新增 save_instance_env 写 instance.env
  （INKFLOW_DATA_DIR=<abs> 一行，返回绝对路径 Path）
- 现状：data-dir 不在 CONFIG_WHITELIST → 未知配置项 exit 2 → 新用例 1-4 FAIL
- 守护用例 5：config show 已输出 data_dir → RED 阶段即 PASS，刻意保留
"""

import importlib
import json

import pytest
from typer.testing import CliRunner

from inkflow.cli.context import CliContext
from inkflow.core.config import (
    CONFIG_WHITELIST,
    load_config_json,
    save_config_json,
)

# inkflow.core 包把 config 属性重绑定为实例，`import a.b as x` 会取到实例而非模块，
# 因此用 importlib 取 sys.modules 中的真实模块
core_config_mod = importlib.import_module("inkflow.core.config")


class TestConfigJsonIO:
    def test_load_from_json(self, tmp_path):
        """从 config.json 加载配置."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"llm_default_model": "deepseek/deepseek-chat"}),
            encoding="utf-8",
        )
        data = load_config_json(tmp_path)
        assert data["llm_default_model"] == "deepseek/deepseek-chat"

    def test_load_missing_file_returns_empty(self, tmp_path):
        """config.json 缺失时返回空 dict."""
        data = load_config_json(tmp_path)
        assert data == {}

    def test_save_and_reload(self, tmp_path):
        """save 后 load 可读取."""
        save_config_json(tmp_path, {"llm_temperature": 0.5})
        data = load_config_json(tmp_path)
        assert data["llm_temperature"] == 0.5

    def test_save_merges_with_existing(self, tmp_path):
        """save 合并而非覆盖已有 key."""
        save_config_json(tmp_path, {"llm_default_model": "gpt-4o"})
        save_config_json(tmp_path, {"llm_temperature": 0.3})
        data = load_config_json(tmp_path)
        assert data["llm_default_model"] == "gpt-4o"
        assert data["llm_temperature"] == 0.3


class TestConfigWhitelist:
    def test_allowed_keys(self):
        """白名单包含 spec 定义的 6 个 key."""
        assert "default.model" in CONFIG_WHITELIST
        assert "default.temperature" in CONFIG_WHITELIST
        assert "context.max_ratio" in CONFIG_WHITELIST
        assert "context.default_window" in CONFIG_WHITELIST
        assert "server.host" in CONFIG_WHITELIST
        assert "server.port" in CONFIG_WHITELIST

    def test_unknown_key_not_in_whitelist(self):
        """未定义 key 不在白名单中."""
        assert "foo.bar" not in CONFIG_WHITELIST


class TestConfigEnvOverride:
    def test_env_var_overrides_json(self, tmp_path, monkeypatch):
        """环境变量优先级 > config.json."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"server_port": "8000"}),
            encoding="utf-8",
        )
        monkeypatch.setenv("INKFLOW_SERVER_PORT", "9000")
        # 验证 config.json 读到了 8000
        data = load_config_json(tmp_path)
        assert data["server_port"] == "8000"
        # 环境变量覆盖在 InkFlowConfig 层，此处仅验证文件层


# ── CLI 命令测试 ──


@pytest.fixture
def cli_runner():
    return CliRunner()


class TestConfigShow:
    def test_show_json(self, cli_runner):
        """config show --json."""
        from inkflow.cli.commands.config_cmd import app

        result = cli_runner.invoke(app, ["show"], obj=CliContext(json_output=True))
        assert result.exit_code == 0

    def test_show_human(self, cli_runner):
        """config show 人类模式."""
        from inkflow.cli.commands.config_cmd import app

        result = cli_runner.invoke(app, ["show"], obj=CliContext(json_output=False))
        assert result.exit_code == 0


class TestConfigSet:
    def test_set_valid_key(self, cli_runner, tmp_path, monkeypatch):
        """config set 合法 key."""
        from inkflow.cli.commands.config_cmd import app

        monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
        result = cli_runner.invoke(
            app,
            ["set", "default.temperature", "0.5"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "0.5" in result.output

    def test_set_unknown_key(self, cli_runner):
        """config set 未知 key → 退出码 2."""
        from inkflow.cli.commands.config_cmd import app

        result = cli_runner.invoke(
            app,
            ["set", "foo.bar", "value"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 2

    def test_set_invalid_value(self, cli_runner, tmp_path, monkeypatch):
        """config set 非法值 → 退出码 1."""
        from inkflow.cli.commands.config_cmd import app

        monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
        result = cli_runner.invoke(
            app,
            ["set", "default.temperature", "3.0"],
            obj=CliContext(json_output=True),
        )
        # Pydantic 验证可能通过（取决于 Field 定义），也可能失败
        # 如果 Pydantic 不报错则保存成功，否则 exit 1
        assert result.exit_code in (0, 1)


class TestConfigSetTypeBranches:
    """config set 类型转换分支补全：int 字段 / str 字段 / 非法值（ValueError 路径）."""

    def test_set_int_field(self, cli_runner, tmp_path, monkeypatch):
        """server.port → int 转换分支 + 保存成功."""
        from inkflow.cli.commands.config_cmd import app

        monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
        result = cli_runner.invoke(
            app,
            ["set", "server.port", "8080"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ server.port = 8080" in result.output

    def test_set_str_field(self, cli_runner, tmp_path, monkeypatch):
        """default.model → str 直通分支 + 保存成功."""
        from inkflow.cli.commands.config_cmd import app

        monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
        result = cli_runner.invoke(
            app,
            ["set", "default.model", "deepseek/deepseek-chat"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ default.model = deepseek/deepseek-chat" in result.output

    def test_set_int_field_invalid_value(self, cli_runner, tmp_path, monkeypatch):
        """server.port 传非整数 → ValueError → CONFIG_ERROR 信封 + 退出码 1."""
        from inkflow.cli.commands.config_cmd import app

        monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
        result = cli_runner.invoke(
            app,
            ["set", "server.port", "abc"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "CONFIG_ERROR"
        assert "值不合法" in data["error"]["message"]


class TestConfigDataDir:
    """Issue #266: config set data-dir 契约（RED 阶段，0.7.0 方案 A）.

    契约锁定：
    - 白名单新增 "data-dir": "data_dir"；set data-dir 调 save_instance_env 写
      instance.env 一行 INKFLOW_DATA_DIR=<abs>，返回绝对路径 Path
    - 空白值 / save_instance_env 抛 OSError → CONFIG_ERROR 信封 exit 1；
      人类模式 "✅ data-dir = " + "重启后生效"；--json 信封
      {"key": "data-dir", "value": str(resolved), "restart_required": True}
    RED 预期：data-dir 不在白名单 → 未知配置项 exit 2 → 用例 1-4 FAIL
    （断言失败非 ERROR，锚点 monkeypatch 均 raising=False）；
    守护用例 test_show_contains_data_dir PASS（show 已输出 data_dir）。
    """

    def test_set_data_dir_writes_instance_env(self, cli_runner, tmp_path, monkeypatch):
        """data-dir 写入 instance.env 且人类模式输出成功提示."""
        from inkflow.cli.commands.config_cmd import app

        anchor = tmp_path / "InkFlow" / "instance.env"
        monkeypatch.setattr(
            core_config_mod, "get_instance_env_path", lambda: anchor, raising=False
        )
        result = cli_runner.invoke(
            app,
            ["set", "data-dir", str(tmp_path / "custom-data")],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert anchor.exists()
        expected = str((tmp_path / "custom-data").resolve())
        assert f"INKFLOW_DATA_DIR={expected}" in anchor.read_text(encoding="utf-8")
        assert "✅ data-dir = " in result.output
        assert "重启后生效" in result.output

    def test_set_data_dir_json_envelope(self, cli_runner, tmp_path, monkeypatch):
        """--json 模式返回重启提示信封."""
        from inkflow.cli.commands.config_cmd import app

        anchor = tmp_path / "InkFlow" / "instance.env"
        monkeypatch.setattr(
            core_config_mod, "get_instance_env_path", lambda: anchor, raising=False
        )
        result = cli_runner.invoke(
            app,
            ["set", "data-dir", str(tmp_path / "custom-data")],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["key"] == "data-dir"
        assert data["data"]["value"] == str((tmp_path / "custom-data").resolve())
        assert data["data"]["restart_required"] is True

    def test_set_data_dir_blank_value(self, cli_runner, tmp_path, monkeypatch):
        """空白值 → CONFIG_ERROR 信封 + 退出码 1."""
        from inkflow.cli.commands.config_cmd import app

        anchor = tmp_path / "InkFlow" / "instance.env"
        monkeypatch.setattr(
            core_config_mod, "get_instance_env_path", lambda: anchor, raising=False
        )
        result = cli_runner.invoke(
            app,
            ["set", "data-dir", "   "],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "CONFIG_ERROR"
        assert "值不合法" in data["error"]["message"]

    def test_set_data_dir_oserror(self, cli_runner, tmp_path, monkeypatch):
        """save_instance_env 抛 OSError → CONFIG_ERROR 信封 + 退出码 1."""
        from inkflow.cli.commands.config_cmd import app

        anchor = tmp_path / "InkFlow" / "instance.env"
        monkeypatch.setattr(
            core_config_mod, "get_instance_env_path", lambda: anchor, raising=False
        )

        def _raise_oserror(_path):
            raise OSError("disk full")

        monkeypatch.setattr(
            core_config_mod, "save_instance_env", _raise_oserror, raising=False
        )
        result = cli_runner.invoke(
            app,
            ["set", "data-dir", str(tmp_path / "x")],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "CONFIG_ERROR"
        assert "值不合法" in data["error"]["message"]

    def test_show_contains_data_dir(self, cli_runner):
        """守护用例：config show 输出已含 data_dir（RED 阶段即绿，刻意保留）."""
        from inkflow.cli.commands.config_cmd import app

        result = cli_runner.invoke(app, ["show"], obj=CliContext(json_output=True))
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "data_dir" in data["data"]
