"""CLI `inkflow agent tools list` 命令契约测试（F26 M3 CLI tools list，RED 阶段）.

只写测试不改 src/：tools 子组尚未注册（GREEN 在 agent_cmd 组内 add_typer 一个 tools
Typer），本文件全部用例以 `runner.invoke(app, ["agent", "tools", ...])` 形态断言契约。

════════════════════════════════════════════════════════════════════
命令契约（GREEN 按此实现，父侧定稿）:
- `inkflow agent tools list [--json]`
    退出码: 0 成功 / 1 运行错误（TOOL_REGISTRY import 失败等）/ 2 参数错误
- 本地静态枚举：import `inkflow.infrastructure.agent.tools` 的 TOOL_REGISTRY
  （list[ToolSpec]），不 ensure_kernel、不发 HTTP —— F38 恒 HTTP 的豁免命令，
  同 config/llm 组先例
- ToolSpec 字段: name / description / input_schema（dict）
- 人类输出（无 --json）：每个工具一行 `name: description` 或等价形态，
  本文件只断言 5 个工具名出现在 stdout，不锁精确格式
- --json 输出信封: {"ok": true, "data": {"items": [ToolSpec...]}}，
  items 每项含 name/description/input_schema 三键
- 工具名顺序固定（5 个）:
  search_characters, check_foreshadowing, get_prior_summary,
  audit_chapter, count_words
- 运行错误（TOOL_REGISTRY import 失败）→ stderr + exit 1（mock 场景下难以触发，
  本文件不测，参数错误面由未知命令 exit 2 覆盖）
════════════════════════════════════════════════════════════════════
RED 预期: tools 子组未注册 → typer 报 `No such command 'tools'.` +
Usage 输出 + exit_code 2 → 各用例 `assert result.exit_code == 0`
干净 FAILED（无 ERROR）；预期形态 6 failed, 2 passed（用例 7/8
RED 阶段即 PASS，见各自 docstring）。

本地枚举豁免声明: tools list 禁止 ensure_kernel / InkFlowHTTPClient，
用例 test_tools_list_ensure_kernel_not_called 以 patch 锁「不启动内核」；
该 patch 用 `patch.object(agent_cmd, "ensure_kernel", mock)` with 块形态
（实测 `patch(..., new=AsyncMock())` 装饰器形态不把 mock 传参给测试函数，
须自持引用）。

ci.yml 登记声明: 新文件需父 agent 追加进 ci.yml integration-cli-backend
job 文件列表（tests/cli 显式列文件，不在列表 CI 不收集）。
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app
from inkflow.cli.commands import agent_cmd

runner = CliRunner()

# 工具名顺序固定契约（父侧定稿，GREEN 按此顺序输出）
TOOL_NAMES = [
    "search_characters",
    "check_foreshadowing",
    "get_prior_summary",
    "audit_chapter",
    "count_words",
    "save_draft",
    "create_character",
    "create_world_setting",
    "create_outline",
    "update_character",
    "update_world_setting",
    "update_outline",
    "list_maps",
    "create_map",
    "update_map",
    "list_timeline_events",
    "create_timeline_event",
    "update_timeline_event",
    "create_foreshadowing",
    "update_foreshadowing",
    "memory_list",
    "memory_add",
    "memory_update",
    "generate",
    "continue",
    "revise",
]


class TestAgentToolsCLI:
    """`inkflow agent tools` 嵌套子组契约测试（F26 M3）。"""

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """去除 ANSI 转义码（CI 环境 rich_markup_mode 会引入颜色码）。"""
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    @pytest.mark.agent
    def test_tools_list_json(self):
        """--json：exit 0；信封 ok=True；items 26 项且顺序固定；每项含三键。"""
        result = runner.invoke(app, ["agent", "tools", "list", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        items = payload["data"]["items"]
        assert [item["name"] for item in items] == TOOL_NAMES
        for item in items:
            assert "name" in item
            assert "description" in item
            assert "input_schema" in item
            assert isinstance(item["input_schema"], dict)

    @pytest.mark.agent
    def test_tools_list_json_description_nonempty(self):
        """--json 信封内：每项 description 为非空 str。"""
        result = runner.invoke(app, ["agent", "tools", "list", "--json"])
        assert result.exit_code == 0
        items = json.loads(result.stdout)["data"]["items"]
        assert len(items) == 26
        for item in items:
            assert isinstance(item["description"], str)
            assert item["description"].strip() != ""

    @pytest.mark.agent
    def test_tools_list_human(self):
        """无 --json：26 个工具名均出现在 stdout（不锁精确格式）。"""
        result = runner.invoke(app, ["agent", "tools", "list"])
        assert result.exit_code == 0
        stdout = self._strip_ansi(result.stdout)
        for name in TOOL_NAMES:
            assert name in stdout

    @pytest.mark.agent
    def test_tools_list_ensure_kernel_not_called(self):
        """本地静态枚举豁免：不 ensure_kernel、不发 HTTP。"""
        mock_ensure = AsyncMock()
        with patch.object(agent_cmd, "ensure_kernel", mock_ensure):
            result = runner.invoke(app, ["agent", "tools", "list", "--json"])
        assert result.exit_code == 0
        mock_ensure.assert_not_awaited()

    @pytest.mark.agent
    def test_tools_help(self):
        """agent tools --help：exit 0 且列出 list 子命令。"""
        result = runner.invoke(app, ["agent", "tools", "--help"])
        assert result.exit_code == 0
        assert "list" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_tools_list_help(self):
        """agent tools list --help：exit 0 且含 --json 选项。"""
        result = runner.invoke(app, ["agent", "tools", "list", "--help"])
        assert result.exit_code == 0
        assert "--json" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_tools_unknown_command(self):
        """未知子命令 → 参数错误面 exit 2。

        RED 阶段即 PASS：tools 组未注册时任意未知路径均 exit 2，本用例
        碰巧成立；GREEN 后仍锁「tools 组内未知命令 → exit 2」契约。
        """
        result = runner.invoke(app, ["agent", "tools", "unknown"])
        assert result.exit_code == 2

    @pytest.mark.agent
    def test_agent_group_still_works(self):
        """守护用例（RED 阶段即 PASS）：tools 子组新增不破坏 agent 组既有命令。"""
        result = runner.invoke(app, ["agent", "run", "--help"])
        assert result.exit_code == 0
        assert "--project-id" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_tools_list_import_failure_exit_1(self):
        """TOOL_REGISTRY import 失败 → stderr「❌ 工具注册表加载失败」+ 退出码 1（覆盖 511-515）。

        sys.modules 注入替身模块：from ...tools import TOOL_REGISTRY 时
        __getattr__ 抛 ImportError → 落入 except Exception 分支。
        """
        import sys

        class _BoomToolsModule:
            """属性访问恒抛 ImportError 的 sys.modules 替身。"""

            def __getattr__(self, name):
                raise ImportError(f"cannot import name {name!r} from boom")

        with patch.dict(
            sys.modules,
            {"inkflow.infrastructure.agent.tools": _BoomToolsModule()},
        ):
            result = runner.invoke(app, ["agent", "tools", "list"])
        assert result.exit_code == 1
        assert "❌ 工具注册表加载失败" in result.stderr
