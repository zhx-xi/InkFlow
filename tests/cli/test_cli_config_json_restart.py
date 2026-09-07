"""#987 config.json 启动读回 ↔ CLI config show 同源契约（tests/cli/）。

契约节 #987 回归第 4 条（CLI 半边）：`inkflow config set default.model x/y` 落盘
config.json 后，模拟重启（重建 InkFlowConfig 注入 config_cmd 模块单例）→
`config show` 输出 x/y（现实现重启回空 → FAIL）。

CLI 测试隔离手法镜像 tests/cli/conftest.py 惯例：monkeypatch 替换
config_cmd 模块的 config 属性（show 消费模块属性，调用时动态解析）。
"""

from __future__ import annotations

import importlib
import json

from typer.testing import CliRunner

from inkflow.cli.context import CliContext

# inkflow.core 包把 config 属性重绑定为实例，importlib 取 sys.modules 真实模块
core_config_mod = importlib.import_module("inkflow.core.config")
config_cmd_mod = importlib.import_module("inkflow.cli.commands.config_cmd")


def _patch_anchor(monkeypatch, anchor) -> None:
    monkeypatch.setattr(
        core_config_mod, "get_instance_env_path", lambda: anchor, raising=False
    )


def test_config_show_reads_config_json_after_restart(monkeypatch, tmp_path) -> None:
    """【R】set default.model 落盘 → 重启（重建实例）→ config show 回该值。

    等价 issue 复现步骤 3。GREEN 义务：ConfigJsonSettingsSource 并入后，重建的
    InkFlowConfig 从 config.json 读回 llm_default_model，show 消费同源字段。
    """
    anchor = tmp_path / "appdata" / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("", encoding="utf-8")
    monkeypatch.delenv("INKFLOW_LLM_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)

    from inkflow.cli.commands.config_cmd import app
    from inkflow.core.config import save_config_json

    runner = CliRunner()
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    # 写入端现即工作（config set 落盘语义，键名同 config_cmd.py:101）
    save_config_json(data_dir, {"llm_default_model": "deepseek/deepseek-chat"})

    # 模拟内核/CLI 进程重启：从 config.json 重新构造配置
    restarted = core_config_mod.InkFlowConfig(data_dir=data_dir)
    monkeypatch.setattr(config_cmd_mod, "config", restarted)

    result = runner.invoke(
        app, ["show"], obj=CliContext(json_output=True)
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["data"]["default_model"] == "deepseek/deepseek-chat"


def test_config_show_instance_env_still_wins_after_restart(monkeypatch, tmp_path) -> None:
    """【G】优先级守护：instance.env 与 config.json 同键并存 → show 输出 instance.env 值
    （方案 A 拍板序 B1 的 CLI 消费面镜像；GREEN 后不得翻转）。"""
    anchor = tmp_path / "appdata" / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("INKFLOW_LLM_DEFAULT_MODEL=instance-side/value\n", encoding="utf-8")
    monkeypatch.delenv("INKFLOW_LLM_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)

    from inkflow.cli.commands.config_cmd import app

    runner = CliRunner()
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "config.json").write_text(
        json.dumps({"llm_default_model": "json-side/value"}), encoding="utf-8"
    )

    restarted = core_config_mod.InkFlowConfig(data_dir=data_dir)
    monkeypatch.setattr(config_cmd_mod, "config", restarted)

    result = runner.invoke(app, ["show"], obj=CliContext(json_output=True))

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["data"]["default_model"] == "instance-side/value"
