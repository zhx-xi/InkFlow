"""CLI `inkflow skill list` 命令契约测试（#522 存储重构，TDD RED 阶段）。

命令契约（父侧统一契约 2026-08-20 #10，写进 docstring 供 GREEN）:
- `inkflow skill list [--json]`
    列出全部 Skill（name + source + 被引用 Agent 数；HTTP 薄层，业务经
    ensure_kernel() + InkFlowHTTPClient 调内核 REST API）
    退出码: 0 成功 / 1 运行错误 / 2 参数错误
    --json 信封: {"ok": true, "data": {"items": [...], "total": N}}
    人类输出: name + source + 引用数——只断言 name/source 出现在 stdout，
    不锁精确格式

HTTP 契约（F38 恒经 HTTP，路径相对 base_url——#246 教训）:
- list → GET /skills（相对 base_url，【不含 /api/v1 前缀】——base_url 已含
  /api/v1，镜像 backend/tests/unit/test_book_cli_paths.py 断言形态）
- 服务器响应: {"items": [...], "total": N}；items 每项含 id/name/description/
  source/agent_ids；#522 后 id 字段值 = name（契约 #2 兼容层）
- 错误映射（map_http_error）: 404 → NOT_FOUND / 422 → VALIDATION_ERROR /
  其余 → INTERNAL_ERROR；KernelStartupError → KERNEL_ERROR

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【路径契约——硬性契约，镜像 test_book_cli_paths.py】`skill list` 的 HTTP
   请求路径必须为相对 base_url 的 `/skills`（不含 `/api/v1` 前缀）。若实现
   写成 `/api/v1/skills` 或绝对 URL → 双前缀 404（#246 教训，0.10.0-rc1
   实证）。mock InkFlowHTTPClient 断言 `get.await_args.args[0]`。

2. 【信封契约】--json 输出 = {"ok": true, "data": {"items", "total"}}（命令级
   --json 选项驱动，镜像 tools_list_cmd 形态）；错误信封 {"ok": false,
   "error": {"code", "message"}} + exit 1。

3. 【数据形状】items 透传服务器响应：#522 后 id 字段值 = name（契约 #2）、
   内置 name 为英文 slug（如 "architecture-methodology"）。CLI 为薄层，
   仅透传 + 格式化，不做任何业务变换。

4. 【mock 策略】patch `inkflow.cli.commands.skill_cmd` 命名空间的
   ensure_kernel + InkFlowHTTPClient（镜像 test_book_cli_paths.py 的
   patch.object 形态；本文件沿用 CliRunner 根 app invoke 形态）。

════════════════════════════════════════════════════════════════════
RED 阶段预期（旧实现：skill_cmd.py 已存在且请求路径已为 /skills）
════════════════════════════════════════════════════════════════════
⚠️ 本文件为 #522 契约重写：CLI 是 HTTP 薄层，旧实现（src 未改）的请求路径
（"/skills" 相对 base_url、不含 /api/v1）与 --json 信封已符合新契约 → 本
文件断言在旧实现下【全绿】。RED 信号不在本文件（薄层对存储重构透明），
由 API 层测试文件承载；本文件锁定「CLI 不得引入 /api/v1 双前缀」回归契约。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.app import app
from inkflow.cli.context import CliContext

runner = CliRunner()

SKILL_MOD = "inkflow.cli.commands.skill_cmd"

EXPECTED_LIST_PATH = "/skills"
"""skill list 的 HTTP 请求路径（相对 base_url，不含 /api/v1，契约 #1）。"""


def _strip_ansi(text: str) -> str:
    """去除 ANSI 转义码（CI 环境 rich_markup_mode 会引入颜色码）。"""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


@pytest.fixture
def fake_http_client():
    """Patch skill_cmd 内 ensure_kernel + InkFlowHTTPClient → fake client 实例.

    GREEN 阶段模块存在 → 正常 patch；__aenter__ 返回自身（async with
    InkFlowHTTPClient(handle) as client 形态），调用记录在 mock_instance 上。
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
    """构造测试用 Skill JSON dict（#522 契约 #2：id 字段值 = name；内置名英文 slug）。"""
    defaults = dict(
        id="architecture-methodology",
        name="architecture-methodology",
        description="章节结构/大纲规划方法论",
        content="---\nname: architecture-methodology\n---\n# 正文",
        source="builtin",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        agent_ids=[{"id": 1, "name": "架构师"}, {"id": 2, "name": "写手"}],
    )
    defaults.update(overrides)
    return defaults


def _invoke(args: list[str], json_output: bool = False):
    """invoke 根 app；--json 走命令级选项（skill list 必须声明并据此输出信封）。"""
    full = [*args, "--json"] if json_output else args
    return runner.invoke(app, full, obj=CliContext(json_output=json_output))


class TestSkillList:
    """`inkflow skill list` 契约。"""

    def test_list_json(self, fake_http_client):
        """--json 信封：{ok: true, data: {items, total}} + GET /skills。"""
        fake_http_client.get.return_value = {
            "items": [
                _make_skill(),
                _make_skill(
                    id="writing-methodology",
                    name="writing-methodology",
                    source="user_upload",
                    agent_ids=[],
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
        assert items[0]["name"] == "architecture-methodology"
        assert items[0]["id"] == "architecture-methodology"
        assert items[0]["source"] == "builtin"
        assert [a["name"] for a in items[0]["agent_ids"]] == ["架构师", "写手"]
        assert items[1]["agent_ids"] == []

    def test_list_path_no_api_v1_prefix(self, fake_http_client):
        """请求路径 = /skills（相对 base_url，不含 /api/v1 前缀）——镜像 test_book_cli_paths.py。

        #246 教训：InkFlowHTTPClient base_url 已含 /api/v1（client.py L65），
        路径再写 /api/v1/skills → httpx 拼出 /api/v1/api/v1/skills → 404。
        """
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = _invoke(["skill", "list"], json_output=True)
        assert result.exit_code == 0
        path = fake_http_client.get.await_args.args[0]
        assert path == EXPECTED_LIST_PATH, f"list path={path!r} 必须相对 base_url"
        assert "/api/v1" not in path, f"list path={path!r} 含 /api/v1 双前缀"

    def test_list_human(self, fake_http_client):
        """无 --json：name + source 出现在 stdout（不锁精确格式）。"""
        fake_http_client.get.return_value = {
            "items": [
                _make_skill(),
                _make_skill(
                    id="writing-methodology",
                    name="writing-methodology",
                    source="user_upload",
                ),
            ],
            "total": 2,
        }
        result = _invoke(["skill", "list"])
        assert result.exit_code == 0
        stdout = _strip_ansi(result.stdout)
        assert "architecture-methodology" in stdout
        assert "writing-methodology" in stdout
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
        """skill --help：exit 0 且列出 list 子命令。"""
        result = _invoke(["skill", "--help"])
        assert result.exit_code == 0
        assert "list" in _strip_ansi(result.stdout)


class TestSkillGuard:
    """守护用例（既有行为回归）。"""

    def test_skill_unknown_subcommand(self):
        """未知子命令 → 参数错误 exit 2。"""
        result = _invoke(["skill", "unknown"])
        assert result.exit_code == 2

    def test_skills_plural_group_untouched(self):
        """守护用例：F19-skills 复数组（文件系统导入）不受影响。"""
        result = _invoke(["skills", "--help"])
        assert result.exit_code == 0
        assert "list" in _strip_ansi(result.stdout)
