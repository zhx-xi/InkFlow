"""CLI `inkflow agent list` / `inkflow agent show` 命令契约测试（F39 #258，RED 阶段）.

只写测试不改 src/：agent 组当前仅有 run/status/validate 叶子命令 +
template/tools/runs/draft 子组，list/show 子命令尚未实现（GREEN 在
agent_cmd.py 组内新增）。本文件全部用例以 invoke(agent_cmd.app, [...])
形态断言契约。

════════════════════════════════════════════════════════════════════
命令契约（父侧定稿，spec §4，写进 docstring 供 GREEN）:
- `inkflow agent list [--json]`
    列出全部 Agent（name + description + builtin 标记）
    退出码: 0 成功 / 1 运行错误（内核启动失败/HTTP 错误）/ 2 参数错误
    --json 信封: {"ok": true, "data": {"items": [...], "total": N}}
    人类输出: 每 Agent 一行或等价形态——只断言 name 出现在 stdout +
    builtin 标记「内置」（builtin=True 的 Agent 行须含「内置」字样，
    不锁精确格式）
- `inkflow agent show --id <N> [--json]`
    查看单个 Agent 详情（system_prompt + tool_ids + skill_ids +
    model/temperature 覆盖）
    --id 必填；退出码 0 成功 / 1 运行错误（含 404 不存在）/ 2 参数错误
    --json 信封: {"ok": true, "data": <完整 Agent 实体>}
    404 → stderr「❌ Agent 不存在」或等价 + exit 1（map_http_error 语义）

HTTP 契约（F38 恒经 HTTP，路径相对 base_url——#246 教训）:
- list → GET /agents → {"items": [...], "total": N}
- show → GET /agents/{id} → 完整 Agent 实体；404 → HttpApiError(404, ...)
- 错误映射（map_http_error）: 404 → NOT_FOUND / 422 → VALIDATION_ERROR /
  其余 → INTERNAL_ERROR；KernelStartupError → KERNEL_ERROR

实现契约（GREEN）:
- MODIFY cli/commands/agent_cmd.py：agent 组新增 list/show 子命令
  （ensure_kernel + InkFlowHTTPClient 薄层，镜像 template 子组形态）
- 信封输出经 ctx.obj.json_output 驱动（镜像 template_list/template_get：
  `if cli_ctx.json_output: print_result(cli_ctx, data)`）；本文件不传命令级
  --json，GREEN 可额外声明 --json 选项但须保持 obj 驱动语义
  （如 `cli_ctx.json_output or json_output` 双读）
- 错误面走 _run_ctx（print_error 信封 + exit 1）

命名区分（防撞）: `inkflow agent list`（本文件，列 Agent 实体）≠
`inkflow agent template list`（F19，列模板）≠ `inkflow agent tools list`
（F26，本地静态枚举工具）。

── RED 预期形态 ────────────────────────────────────────────────
agent list/show 子命令不存在 → typer 报 `No such command 'list'.` /
`No such command 'show'.` + Usage 输出 + exit_code 2 → 各用例
`assert result.exit_code == 0/1` 干净 FAILED（无 ERROR——fixture patch
目标 ensure_kernel/InkFlowHTTPClient 均已在 agent_cmd 命名空间，patch
正常，失败纯为断言）；守护用例（show 缺 --id exit 2、run --help、
template --help）RED 阶段即 PASS。预期形态约 10 failed, 3 passed。

ci.yml 登记声明: 新文件需父 agent 追加进 ci.yml integration-cli-backend
job 文件列表（tests/cli 显式列文件，不在列表 CI 不收集）。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.agent_cmd import app
from inkflow.cli.context import CliContext

runner = CliRunner()

AGENT_MOD = "inkflow.cli.commands.agent_cmd"


def _strip_ansi(text: str) -> str:
    """去除 ANSI 转义码（CI 环境 rich_markup_mode 会引入颜色码）。"""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


@pytest.fixture
def fake_http_client():
    """Patch agent_cmd 内 ensure_kernel + InkFlowHTTPClient → fake client 实例.

    __aenter__ 返回自身：async with InkFlowHTTPClient(handle) as client 的
    client 即本 mock，后续 get 调用记录在 mock_instance 上（F38 轨）。
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


def _make_agent(**overrides) -> dict:
    """构造测试用 Agent JSON dict（spec §2.1 实体字段）。"""
    defaults = dict(
        id=1,
        name="架构师",
        description="章节结构/大纲规划",
        icon="🏗️",
        system_prompt="你是架构师，负责章节结构与大纲规划。",
        tool_ids=["search_characters", "check_foreshadowing", "get_prior_summary"],
        skill_ids=["1"],
        model_override="zhipu/glm-4.5",
        temperature_override=0.3,
        builtin=True,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _invoke(args: list[str], json_output: bool = False):
    """invoke agent 子组（直接 invoke agent_cmd.app，必须带 obj=CliContext）。"""
    return runner.invoke(app, args, obj=CliContext(json_output=json_output))


class TestAgentList:
    """`inkflow agent list` 契约。"""

    def test_list_json(self, fake_http_client):
        """--json 信封：{ok: true, data: {items, total}} + GET /agents."""
        fake_http_client.get.return_value = {
            "items": [
                _make_agent(),
                _make_agent(id=2, name="润色师", builtin=False),
            ],
            "total": 2,
        }
        result = _invoke(["list"], json_output=True)
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["total"] == 2
        items = data["data"]["items"]
        assert len(items) == 2
        assert items[0]["name"] == "架构师"
        assert items[0]["description"] == "章节结构/大纲规划"
        assert items[0]["builtin"] is True
        assert items[1]["builtin"] is False
        assert fake_http_client.get.await_args.args[0] == "/agents"

    def test_list_human(self, fake_http_client):
        """无 --json：name 出现在 stdout + builtin 标记「内置」（不锁格式）。"""
        fake_http_client.get.return_value = {
            "items": [
                _make_agent(),
                _make_agent(id=2, name="润色师", builtin=False),
            ],
            "total": 2,
        }
        result = _invoke(["list"])
        assert result.exit_code == 0
        stdout = _strip_ansi(result.stdout)
        assert "架构师" in stdout
        assert "润色师" in stdout
        assert "内置" in stdout

    def test_list_empty_json(self, fake_http_client):
        """空列表 --json：信封 total 0 + items []。"""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = _invoke(["list"], json_output=True)
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["items"] == []
        assert data["data"]["total"] == 0

    def test_list_empty_human(self, fake_http_client):
        """空列表人类模式 → 空提示。"""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = _invoke(["list"])
        assert result.exit_code == 0
        assert "暂无" in result.output or "📭" in result.output

    def test_list_http_error(self, fake_http_client):
        """HTTP 500 → exit 1 + INTERNAL_ERROR 信封（运行错误面）。"""
        fake_http_client.get.side_effect = _http_error(500, "内核内部错误")
        result = _invoke(["list"], json_output=True)
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_list_kernel_startup_error(self, fake_http_client):
        """内核启动失败 → exit 1 + KERNEL_ERROR 信封（运行错误面）。"""
        from inkflow.infrastructure.kernel import KernelStartupError

        with patch(
            f"{AGENT_MOD}.ensure_kernel",
            AsyncMock(side_effect=KernelStartupError("启动超时")),
        ):
            result = _invoke(["list"], json_output=True)
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "KERNEL_ERROR"


class TestAgentShow:
    """`inkflow agent show --id <N>` 契约。"""

    def test_show_json(self, fake_http_client):
        """--json 信封：data = 完整 Agent 实体 + GET /agents/1."""
        fake_http_client.get.return_value = _make_agent()
        result = _invoke(["show", "--id", "1"], json_output=True)
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        agent = data["data"]
        assert agent["id"] == 1
        assert agent["name"] == "架构师"
        assert agent["system_prompt"] == "你是架构师，负责章节结构与大纲规划。"
        assert agent["tool_ids"] == [
            "search_characters",
            "check_foreshadowing",
            "get_prior_summary",
        ]
        assert agent["skill_ids"] == ["1"]
        assert agent["model_override"] == "zhipu/glm-4.5"
        assert agent["temperature_override"] == 0.3
        assert agent["builtin"] is True
        assert fake_http_client.get.await_args.args[0] == "/agents/1"

    def test_show_human(self, fake_http_client):
        """无 --json：详情关键字段值出现在 stdout（不锁精确格式）。"""
        fake_http_client.get.return_value = _make_agent()
        result = _invoke(["show", "--id", "1"])
        assert result.exit_code == 0
        stdout = _strip_ansi(result.stdout)
        assert "架构师" in stdout
        assert "你是架构师" in stdout
        assert "search_characters" in stdout
        assert "zhipu/glm-4.5" in stdout

    def test_show_not_found_json(self, fake_http_client):
        """404 → exit 1 + NOT_FOUND 信封（map_http_error 语义）。"""
        fake_http_client.get.side_effect = _http_error(404, "Agent 不存在")
        result = _invoke(["show", "--id", "999"], json_output=True)
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "Agent 不存在" in data["error"]["message"]

    def test_show_not_found_human(self, fake_http_client):
        """404 人类模式 → stderr「❌ Agent 不存在」+ exit 1。"""
        fake_http_client.get.side_effect = _http_error(404, "Agent 不存在")
        result = _invoke(["show", "--id", "999"])
        assert result.exit_code == 1
        assert "❌ Agent 不存在" in result.stderr

    def test_show_missing_id(self):
        """缺 --id → 参数错误 exit 2。

        RED 阶段即 PASS：show 未注册时任意未知路径均 exit 2，本用例碰巧
        成立；GREEN 后锁「show 缺必填 --id → exit 2」契约。
        """
        result = _invoke(["show"])
        assert result.exit_code == 2


class TestAgentGroupGuard:
    """守护用例（RED 阶段即 PASS）：list/show 追加不破坏 agent 组既有命令。"""

    def test_agent_run_help(self):
        """agent run --help 仍可用。"""
        result = _invoke(["run", "--help"])
        assert result.exit_code == 0
        assert "--project-id" in _strip_ansi(result.stdout)

    def test_agent_template_group_untouched(self):
        """agent template 子组不受影响（F19 命名区分）。"""
        result = _invoke(["template", "--help"])
        assert result.exit_code == 0
        assert "list" in _strip_ansi(result.stdout)
