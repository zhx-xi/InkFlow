"""F60 CLI `config show` 首启引导状态行契约（RED — #934 §4 / R6）。

被测：`inkflow config show`（`cli/commands/config_cmd.py`）新增 2 键：
- `model_ready: bool` — 是否已具备可用 chat 模型配置
- `model_ready_hint: str | None` — 未就绪时的可操作提示行；就绪 = None

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约）
════════════════════════════════════════════════════════════════════

1. 【零 kernel 契约】`config show` 严禁触发内核拉起（既有
   tests/cli/test_cli_http_kernel.py:194 豁免契约）——本文件用例不
   patch kernel，若 GREEN 引入 spawn 会因无内核而挂/超时 → 契约自然守护。

2. 【判据（CLI 本地派生）】config show 无 DB session：就绪判据 =
   `bool(config.llm_default_model)`（全局默认 chat 模型已配为唯一本地信号）。
   理由：#735 D2 保证首个含 chat 模型的 provider 新增即自动落全局默认
   （provider_config_service.py:78-85），故「全局默认非空」⇔「注册表有可用
   chat 模型」在正常配置路径下等价；CLI 是**状态可见性**面（GUI 是主路径），
   判据取本地最小信号即可，不引入 kernel 依赖。

3. 【JSON 模式】`--json` 信封含 `model_ready` + `model_ready_hint` 两键。

4. 【人类模式】未就绪 → output 含提示行（「模型未配置」+ GUI 入口指引）；
   就绪 → 不输出提示行。

5. 【RED 阶段预期】`model_ready` 键缺失 → JSON 用例 FAIL；
   人类模式提示行缺失 → FAIL。

patch seam：`config` 为模块级单例（`inkflow.cli.commands.config_cmd.config`），
用例经 monkeypatch.setattr 改其 llm_default_model（镜像既有属性 patch 惯例）。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from inkflow.cli.context import CliContext

# ── 契约常量 ──

HINT_ANCHOR = "模型未配置"
"""未就绪提示行的锚文本（人类模式断言用，防文案微调导致脆弱断言）。"""


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


class TestConfigShowModelReadiness:
    """config show 首启状态行（#934 §4 / R6）。"""

    def test_show_json_includes_model_ready_keys(self, cli_runner, monkeypatch) -> None:
        """JSON 模式：信封含 model_ready + model_ready_hint 两键。"""
        from inkflow.cli.commands import config_cmd

        monkeypatch.setattr(config_cmd.config, "llm_default_model", "")
        result = cli_runner.invoke(config_cmd.app, ["show"], obj=CliContext(json_output=True))
        assert result.exit_code == 0
        payload = _json_payload(result.output)
        assert "model_ready" in payload
        assert "model_ready_hint" in payload

    def test_not_ready_json_false_with_hint(self, cli_runner, monkeypatch) -> None:
        """全局默认为空 → model_ready=False + hint 非空（可操作指引）。"""
        from inkflow.cli.commands import config_cmd

        monkeypatch.setattr(config_cmd.config, "llm_default_model", "")
        result = cli_runner.invoke(config_cmd.app, ["show"], obj=CliContext(json_output=True))
        assert result.exit_code == 0
        payload = _json_payload(result.output)
        assert payload["model_ready"] is False
        assert payload["model_ready_hint"]

    def test_ready_json_true_hint_null(self, cli_runner, monkeypatch) -> None:
        """全局默认非空 → model_ready=True + hint=None。"""
        from inkflow.cli.commands import config_cmd

        monkeypatch.setattr(
            config_cmd.config, "llm_default_model", "deepseek/deepseek-chat"
        )
        result = cli_runner.invoke(config_cmd.app, ["show"], obj=CliContext(json_output=True))
        assert result.exit_code == 0
        payload = _json_payload(result.output)
        assert payload["model_ready"] is True
        assert payload["model_ready_hint"] is None

    def test_not_ready_human_prints_hint_line(self, cli_runner, monkeypatch) -> None:
        """人类模式：未就绪 → 输出提示行（含锚文本）。"""
        from inkflow.cli.commands import config_cmd

        monkeypatch.setattr(config_cmd.config, "llm_default_model", "")
        result = cli_runner.invoke(config_cmd.app, ["show"], obj=CliContext(json_output=False))
        assert result.exit_code == 0
        assert HINT_ANCHOR in result.output

    def test_ready_human_no_hint_line(self, cli_runner, monkeypatch) -> None:
        """人类模式：就绪 → 不输出提示行（零打扰）。"""
        from inkflow.cli.commands import config_cmd

        monkeypatch.setattr(
            config_cmd.config, "llm_default_model", "deepseek/deepseek-chat"
        )
        result = cli_runner.invoke(config_cmd.app, ["show"], obj=CliContext(json_output=False))
        assert result.exit_code == 0
        assert HINT_ANCHOR not in result.output


def _json_payload(output: str) -> dict:
    """从 CLI 输出中提取 JSON 信封的 data 段（信封 = {"ok": true, "data": {...}}）。"""
    import json

    start = output.find("{")
    assert start != -1, f"输出中未找到 JSON 信封: {output!r}"
    envelope = json.loads(output[start:])
    return envelope["data"]
