"""CLI `inkflow skill list` 命令契约测试（F39 #258，RED 阶段）.

只写测试不改 src/：cli/commands/skill_cmd.py 整个不存在、skill 子组未在
app.py 注册（GREEN = CREATE skill_cmd.py + MODIFY app.py 注册）。本文件
全部用例以根 app invoke(["skill", ...]) 形态断言契约。

════════════════════════════════════════════════════════════════════
命令契约（父侧定稿，spec §4，写进 docstring 供 GREEN）:
- `inkflow skill list [--json]`
    列出全部 Skill（name + source + 被引用 Agent 数）
    退出码: 0 成功 / 1 运行错误 / 2 参数错误
    --json 信封: {"ok": true, "data": {"items": [...], "total": N}}
    人类输出: name + source + 引用数——只断言 name/source 出现在 stdout，
    不锁精确格式

HTTP 契约（F38 恒经 HTTP，路径相对 base_url——#246 教训）:
- list → GET /skills → {"items": [...], "total": N}
- items 每项含 id/name/description/source/agent_ids（spec §3.2 反查：
  agent_ids = [{id, name}, ...] = 被引用 Agent 列表）
- 错误映射（map_http_error）: 404 → NOT_FOUND / 422 → VALIDATION_ERROR /
  其余 → INTERNAL_ERROR；KernelStartupError → KERNEL_ERROR

实现契约（GREEN）:
- CREATE cli/commands/skill_cmd.py：app = typer.Typer(name="skill",
  help="Skill 管理", no_args_is_help=True) + @app.command("list")；
  模块级 import ensure_kernel + InkFlowHTTPClient（patch 目标 =
  skill_cmd 命名空间，见 fake_http_client fixture）
- MODIFY cli/app.py：`from inkflow.cli.commands.skill_cmd import app as
  skill_app` + `app.add_typer(skill_app, name="skill")`
- 信封输出由命令级 --json 选项驱动（`json_output: bool = typer.Option(
  False, "--json", ...)` + `if json_output: 信封输出`，镜像 tools_list_cmd/
  validate 形态）——根 app invoke 下 ctx.obj.json_output 恒 False，
  读取 ctx.obj 的实现在本契约下不可测
- 错误面 print_error 语义（信封 + exit 1）

命名区分（防撞）: `inkflow skill list`（本文件，单数，DB 实体）≠
`inkflow skills list`（F19-skills，复数，文件系统导入）——两者互不消费
（spec §1.3）。

── RED 预期形态 ────────────────────────────────────────────────
skill 子组未注册 → 根 app invoke ["skill", "list"] 报
`No such command 'skill'.` + Usage 输出 + exit_code 2 → 各用例
`assert result.exit_code == 0/1` 干净 FAILED（无 ERROR）。fake_http_client
fixture 双阶段语义：RED 阶段 skill_cmd 模块不存在 → patch setup 抛
AttributeError（Python 3.13 mock 逐级 getattr 形态）→ yield 占位
AsyncMock（用例仍以 exit 2 干净 FAILED，断言永不触达 await_args）；
GREEN 阶段模块存在 → 正常 patch。守护用例（未知子命令 exit 2、
skills 复数组 --help）RED 阶段即 PASS。预期形态约 6 failed, 2 passed。

ci.yml 登记声明: 新文件需父 agent 追加进 ci.yml integration-cli-backend
job 文件列表（tests/cli 显式列文件，不在列表 CI 不收集）。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.app import app
from inkflow.cli.context import CliContext

runner = CliRunner()

SKILL_MOD = "inkflow.cli.commands.skill_cmd"


def _strip_ansi(text: str) -> str:
    """去除 ANSI 转义码（CI 环境 rich_markup_mode 会引入颜色码）。"""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


@pytest.fixture
def fake_http_client():
    """Patch skill_cmd 内 ensure_kernel + InkFlowHTTPClient → fake client 实例.

    双阶段语义：RED 阶段 skill_cmd 模块不存在 → patch setup 抛
    AttributeError（Python 3.13 mock 经 pkgutil.resolve_name 逐级 getattr，
    缺失模块报 AttributeError 而非 ModuleNotFoundError）→ yield 占位
    AsyncMock（断言仍以 exit 2 干净 FAILED）；GREEN 阶段模块存在 →
    正常 patch，__aenter__ 返回自身（async with
    InkFlowHTTPClient(handle) as client 形态，调用记录在 mock_instance 上）。
    """
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    try:
        with (
            patch(f"{SKILL_MOD}.ensure_kernel", AsyncMock(return_value=fake_handle)),
            patch(f"{SKILL_MOD}.InkFlowHTTPClient", autospec=True) as mock_cls,
        ):
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_instance
            yield mock_instance
    except (ModuleNotFoundError, AttributeError):
        yield AsyncMock()


def _http_error(status_code: int, detail: str, code: str | None = None):
    """惰性构造 HttpApiError."""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _make_skill(**overrides) -> dict:
    """构造测试用 Skill JSON dict（spec §2.2 实体 + §3.2 反查字段）。"""
    defaults = dict(
        id=1,
        name="架构方法论",
        description="章节结构/大纲规划方法论",
        content="---\nname: 架构方法论\n---\n# 正文",
        source="builtin",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        agent_ids=[{"id": 1, "name": "架构师"}, {"id": 2, "name": "写手"}],
    )
    defaults.update(overrides)
    return defaults


def _invoke(args: list[str], json_output: bool = False):
    """invoke 根 app（skill 子组未注册 → No such command；显式 obj 无害）。

    --json 走命令级选项（skill list 必须声明并据此输出信封）。
    """
    full = [*args, "--json"] if json_output else args
    return runner.invoke(app, full, obj=CliContext(json_output=json_output))


class TestSkillList:
    """`inkflow skill list` 契约。"""

    def test_list_json(self, fake_http_client):
        """--json 信封：{ok: true, data: {items, total}} + GET /skills."""
        fake_http_client.get.return_value = {
            "items": [
                _make_skill(),
                _make_skill(
                    id=2, name="写作方法论", source="user_upload", agent_ids=[]
                ),
            ],
            "total": 2,
        }
        result = _invoke(["skill", "list"], json_output=True)
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["total"] == 2
        items = data["data"]["items"]
        assert len(items) == 2
        assert items[0]["name"] == "架构方法论"
        assert items[0]["source"] == "builtin"
        assert [a["name"] for a in items[0]["agent_ids"]] == ["架构师", "写手"]
        assert items[1]["agent_ids"] == []
        assert fake_http_client.get.await_args.args[0] == "/skills"

    def test_list_human(self, fake_http_client):
        """无 --json：name + source 出现在 stdout（不锁精确格式）。"""
        fake_http_client.get.return_value = {
            "items": [
                _make_skill(),
                _make_skill(id=2, name="写作方法论", source="user_upload"),
            ],
            "total": 2,
        }
        result = _invoke(["skill", "list"])
        assert result.exit_code == 0
        stdout = _strip_ansi(result.stdout)
        assert "架构方法论" in stdout
        assert "写作方法论" in stdout
        assert "builtin" in stdout
        assert "user_upload" in stdout

    def test_list_empty_json(self, fake_http_client):
        """空列表 --json：信封 total 0 + items []。"""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = _invoke(["skill", "list"], json_output=True)
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["items"] == []
        assert data["data"]["total"] == 0

    def test_list_empty_human(self, fake_http_client):
        """空列表人类模式 → 空提示。"""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = _invoke(["skill", "list"])
        assert result.exit_code == 0
        assert "暂无" in result.output or "📭" in result.output

    def test_list_http_error(self, fake_http_client):
        """HTTP 500 → exit 1 + INTERNAL_ERROR 信封（运行错误面）。"""
        fake_http_client.get.side_effect = _http_error(500, "内核内部错误")
        result = _invoke(["skill", "list"], json_output=True)
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_skill_group_help(self):
        """skill --help：exit 0 且列出 list 子命令（RED 阶段 exit 2 FAIL）。"""
        result = _invoke(["skill", "--help"])
        assert result.exit_code == 0
        assert "list" in _strip_ansi(result.stdout)


class TestSkillGuard:
    """守护用例（RED 阶段即 PASS）。"""

    def test_skill_unknown_subcommand(self):
        """未知子命令 → 参数错误 exit 2。

        RED 阶段即 PASS：skill 组未注册时任意未知路径均 exit 2，本用例
        碰巧成立；GREEN 后锁「skill 组内未知命令 → exit 2」契约。
        """
        result = _invoke(["skill", "unknown"])
        assert result.exit_code == 2

    def test_skills_plural_group_untouched(self):
        """守护用例：F19-skills 复数组（文件系统导入）不受影响。"""
        result = _invoke(["skills", "--help"])
        assert result.exit_code == 0
        assert "list" in _strip_ansi(result.stdout)
