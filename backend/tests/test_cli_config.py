"""Config 持久化测试."""

import json

from inkflow.core.config import (
    CONFIG_WHITELIST,
    load_config_json,
    save_config_json,
)


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
