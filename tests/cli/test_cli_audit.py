"""F15 审计 CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（spec §4/§9 CLI 测试）。

覆盖（依据 specs/f15-consistency-audit/spec.md §4/§7/§9）:
- audit 组注册（check 命令）
- check 人类可读摘要两种形态（✅ 审计通过 / ❌ 不一致；error/warning 逐条、
  info 只计数不逐条、末尾提示 --json）
- check --json 完整报告信封（{"ok": true, "data": ...} + data.summary.consistent）
- 发现 error findings → 退出码恒 0（Q1 拍板 A：发现不一致是「结果」非「执行错误」）
- 项目不存在 → NOT_FOUND 错误信封 + 退出码 1
- 数据库读取失败 → INTERNAL_ERROR 错误信封 + 退出码 1
- 缺 --project-id → 退出码 2（Typer 必填参数）

F38 改造（#169）：mock 目标从 domain Service 迁移到 ensure_kernel + InkFlowHTTPClient
（HTTP JSON 响应）；create_tables patch 已移除。命令签名/信封/退出码不变。

── RED 形态说明 ─────────────────────────────────────────────
- fake_http_client fixture patch 命令模块命名空间
  （inkflow.cli.commands.audit.ensure_kernel / .InkFlowHTTPClient）——当前命令模块
  尚无这两个属性 → fixture setup 抛 AttributeError → 相关用例 ERROR（同根因，
  预期 RED；GREEN 命令改造落地后自动转绿）。
- HttpApiError 在用例体内惰性导入：RED 阶段 inkflow.infrastructure.http 尚未实现，
  顶部 import 会使整文件收集失败（ModuleNotFoundError），无法呈现上述预期形态。

── 错误映射契约（spec §5.3 表）────────────────────────────
- HttpApiError(404, detail) → NOT_FOUND（message = detail 透传）
- HttpApiError(500, detail)（无 X-InkFlow-Error-Code 头）→ INTERNAL_ERROR
  ⚠️ 错误码语义变更：直连时代 DB_ERROR 由 CLI 产生；恒 HTTP 后 DB 访问全部在
  内核侧，CLI 只见 500 → INTERNAL_ERROR（spec §5.3 注，DB_ERROR 由
  INTERNAL_ERROR 替代）。测试断言随契约更新。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import typer
from typer.testing import CliRunner

from inkflow.cli.commands.audit import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = "2026-08-02T12:00:00Z"


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）。"""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP。

    命令模块将从 inkflow.infrastructure.kernel/http from-import 这两个名字——
    patch 目标 = 命令模块命名空间（F38 契约）。__aenter__ 返回自身，兼容
    spec §4.2 的 `async with InkFlowHTTPClient(handle) as client` 形态。
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
        patch(
            "inkflow.cli.commands.audit.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.audit.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _finding(**overrides: object) -> dict:
    """构造测试用 AuditFinding JSON dict（默认 error 级关系悬空引用）。"""
    kwargs: dict[str, object] = {
        "id": "character.relation_ref:7a4f2c91-0000-4000-8000-000000000001",
        "rule_id": "character.relation_ref",
        "dimension": "character",
        "severity": "error",
        "message": "关系 林晚→?? 的 to 端指向不存在的角色（悬空引用，请删除该关系或恢复目标角色）",
        "entity_type": "relation",
        "entity_id": "7a4f2c91-0000-4000-8000-000000000001",
        "entity_name": "林晚→??",
        "ref_type": "character",
        "ref_id": "11111111-1111-1111-1111-111111111111",
        "data": {"relation_type": "敌对"},
    }
    kwargs.update(overrides)
    return kwargs


def _timeline_check() -> dict:
    """构造 F12 ConsistencyReport 嵌套报告 JSON dict（1 条 order_conflict）。"""
    return {
        "project_id": str(PID),
        "checked": 6,
        "skipped": 0,
        "consistent": False,
        "conflicts": [
            {
                "conflict_type": "order_conflict",
                "prev": {
                    "id": "9b1c2d3e-0000-4000-8000-000000000001",
                    "title": "林晚入宫",
                    "time_value": 5.0,
                    "time_display": "",
                    "narrative_position": 1,
                    "timeline_flag": "",
                },
                "next": {
                    "id": "4a5b6c7d-0000-4000-8000-000000000001",
                    "title": "外门往事",
                    "time_value": 3.0,
                    "time_display": "",
                    "narrative_position": 2,
                    "timeline_flag": "",
                },
                "message": (
                    "叙事顺序中「林晚入宫」之后是「外门往事」，但世界内时间 5.0 > 3.0"
                    "——时间倒流（未声明倒叙）"
                ),
            }
        ],
        "flashbacks": [],
        "event_timeline": [],
        "narrative_order": [],
    }


def _make_report(**overrides: object) -> dict:
    """构造不一致 AuditReport JSON dict（1 error / 1 warning / 2 info + 嵌套时间线报告）。"""
    findings = [
        _finding(),
        _finding(
            id="foreshadowing.event_anchor:1a2b3c4d-0000-4000-8000-000000000001",
            rule_id="foreshadowing.event_anchor",
            dimension="foreshadowing",
            severity="warning",
            message=(
                "伏笔「铜镜的秘密」锚点事件已软删（锚点保留但事件不在时间线视图中，"
                "请确认是否需解除挂接）"
            ),
            entity_type="foreshadowing",
            entity_id="1a2b3c4d-0000-4000-8000-000000000001",
            entity_name="铜镜的秘密",
            ref_type="event",
            ref_id="8e9f0a1b-0000-4000-8000-000000000001",
            data={},
        ),
        _finding(
            id="world.archive_gap:3f2e1d4a-0000-4000-8000-000000000001",
            rule_id="world.archive_gap",
            dimension="world",
            severity="info",
            message=(
                "项目已有 3 个章节但尚未建立世界观档案"
                "（可运行 inkflow extract run --type setting 提取）"
            ),
            entity_type="project",
            entity_id=None,
            entity_name="测试项目",
            ref_type=None,
            ref_id=None,
            data={},
        ),
        _finding(
            id="extraction.run_gap:5a6b7c8d-0000-4000-8000-000000000001",
            rule_id="extraction.run_gap",
            dimension="cross",
            severity="info",
            message="章节「第一章」从未执行过提取",
            entity_type="chapter",
            entity_id="5a6b7c8d-0000-4000-8000-000000000001",
            entity_name="第一章",
            ref_type=None,
            ref_id=None,
            data={},
        ),
    ]
    summary = {
        "consistent": False,
        "total": 4,
        "by_dimension": {
            "character": {"error": 1, "warning": 0, "info": 0},
            "timeline": {"error": 0, "warning": 0, "info": 0},
            "world": {"error": 0, "warning": 0, "info": 1},
            "foreshadowing": {"error": 0, "warning": 1, "info": 0},
            "cross": {"error": 0, "warning": 0, "info": 1},
        },
        "counts": {
            "characters": 3,
            "relations": 2,
            "groups": 1,
            "world_settings": 4,
            "events": 6,
            "foreshadowings": 2,
            "chapters": 3,
            "extraction_runs": 5,
        },
    }
    kwargs: dict[str, object] = {
        "project_id": str(PID),
        "generated_at": TS,
        "summary": summary,
        "findings": findings,
        "timeline_check": _timeline_check(),
    }
    kwargs.update(overrides)
    return kwargs


def _consistent_report() -> dict:
    """构造一致报告 JSON dict（0 error / 1 warning / 2 info，consistent=true）。"""
    findings = [
        _finding(
            id="foreshadowing.event_anchor:1a2b3c4d-0000-4000-8000-000000000001",
            rule_id="foreshadowing.event_anchor",
            dimension="foreshadowing",
            severity="warning",
            message="伏笔「铜镜的秘密」锚点事件已软删（锚点保留但事件不在时间线视图中）",
            entity_type="foreshadowing",
            entity_id="1a2b3c4d-0000-4000-8000-000000000001",
            entity_name="铜镜的秘密",
            ref_type="event",
            ref_id="8e9f0a1b-0000-4000-8000-000000000001",
            data={},
        ),
        _finding(
            id="world.archive_gap:3f2e1d4a-0000-4000-8000-000000000001",
            rule_id="world.archive_gap",
            dimension="world",
            severity="info",
            message=(
                "项目已有 3 个章节但尚未建立世界观档案"
                "（可运行 inkflow extract run --type setting 提取）"
            ),
            entity_type="project",
            entity_id=None,
            entity_name="测试项目",
            ref_type=None,
            ref_id=None,
            data={},
        ),
        _finding(
            id="extraction.run_gap:5a6b7c8d-0000-4000-8000-000000000001",
            rule_id="extraction.run_gap",
            dimension="cross",
            severity="info",
            message="章节「第一章」从未执行过提取",
            entity_type="chapter",
            entity_id="5a6b7c8d-0000-4000-8000-000000000001",
            entity_name="第一章",
            ref_type=None,
            ref_id=None,
            data={},
        ),
    ]
    return {
        "project_id": str(PID),
        "generated_at": TS,
        "summary": {
            "consistent": True,
            "total": 3,
            "by_dimension": {
                "character": {"error": 0, "warning": 0, "info": 0},
                "timeline": {"error": 0, "warning": 0, "info": 0},
                "world": {"error": 0, "warning": 0, "info": 1},
                "foreshadowing": {"error": 0, "warning": 1, "info": 0},
                "cross": {"error": 0, "warning": 0, "info": 1},
            },
            "counts": {
                "characters": 3,
                "relations": 2,
                "groups": 1,
                "world_settings": 4,
                "events": 6,
                "foreshadowings": 2,
                "chapters": 3,
                "extraction_runs": 5,
            },
        },
        "findings": findings,
        "timeline_check": {
            "project_id": str(PID),
            "checked": 0,
            "skipped": 0,
            "consistent": True,
            "conflicts": [],
            "flashbacks": [],
            "event_timeline": [],
            "narrative_order": [],
        },
    }


class TestAuditRegistration:
    def test_group_help_lists_check(self):
        """audit 组帮助包含 check 命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）。"""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "check" in result.output


class TestAuditCheck:
    def test_check_human_consistent(self, cli_runner, fake_http_client):
        """check 人类模式一致 → ✅ 审计通过 + 三级计数摘要（spec §4.2）。"""
        fake_http_client.get.return_value = _consistent_report()
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 审计通过" in result.output
        assert "0 error / 1 warning / 2 info" in result.output

    def test_check_human_inconsistent(self, cli_runner, fake_http_client):
        """check 人类模式发现不一致 → ❌ 摘要 + error/warning 逐条 + info 只计数。"""
        fake_http_client.get.return_value = _make_report()
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "❌ 不一致" in result.output
        assert "1 error / 1 warning / 2 info" in result.output
        # error / warning 逐条列出（[级别] 维度: 消息）
        assert "[error] 角色" in result.output
        assert "悬空引用" in result.output
        assert "[warning] 伏笔" in result.output
        assert "锚点事件已软删" in result.output
        # info 只计数不逐条（避免噪音，spec §4.2）
        assert "尚未建立世界观档案" not in result.output
        # 末尾提示 --json 完整报告
        assert "完整报告见 inkflow audit check --json" in result.output

    def test_check_json_envelope(self, cli_runner, fake_http_client):
        """check --json → 成功信封 + 完整 AuditReport（data.summary.consistent）。"""
        fake_http_client.get.return_value = _make_report()
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["project_id"] == str(PID)
        assert data["data"]["summary"]["consistent"] is False
        assert data["data"]["summary"]["total"] == 4
        assert data["data"]["findings"][0]["rule_id"] == "character.relation_ref"
        assert data["data"]["timeline_check"]["checked"] == 6
        fake_http_client.get.assert_awaited_once_with(f"/projects/{PID}/audit")

    def test_check_error_findings_exit_0(self, cli_runner, fake_http_client):
        """发现 error findings → 退出码恒 0（Q1 拍板 A，spec §7/§12）。"""
        fake_http_client.get.return_value = _make_report()
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0

    def test_check_project_not_found_exit_1(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1（spec §4.2 示例）。"""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.get.side_effect = HttpApiError(404, "项目不存在")
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "项目不存在" in data["error"]["message"]

    def test_check_db_error_exit_1(self, cli_runner, fake_http_client):
        """数据库读取失败 → INTERNAL_ERROR 错误信封 + 退出码 1（spec §4/§5.3）。"""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.get.side_effect = HttpApiError(500, "数据库读取失败")
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_check_missing_project_id_exit_2(self, cli_runner, fake_http_client):
        """缺 --project-id → 退出码 2（Typer 必填参数，spec §4/§9）。"""
        result = cli_runner.invoke(app, ["check"], obj=CliContext(json_output=False))
        assert result.exit_code == 2


class TestAuditCheckEdgeBranches:
    """补齐 miss 行：无效 UUID、typer.Exit 透传、无 findings 人类模式（不提示 --json）."""

    def test_check_invalid_uuid(self, cli_runner, fake_http_client):
        """无效 project-id UUID → NOT_FOUND 信封 + 退出码 1（spec §7: 无效 UUID → 404 语义）."""
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", "not-a-uuid"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        fake_http_client.get.assert_not_awaited()

    def test_check_typer_exit_reraises(self, cli_runner, fake_http_client):
        """Client 抛 typer.Exit → 原样透传（退出码 3，不映射错误信封）."""
        fake_http_client.get.side_effect = typer.Exit(3)
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 3

    def test_check_human_no_findings(self, cli_runner, fake_http_client):
        """无 findings 人类模式 → ❌ 摘要 + 0/0/0 计数，不提示 --json 完整报告."""
        fake_http_client.get.return_value = _make_report(findings=[])
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "❌ 不一致" in result.output
        assert "0 error / 0 warning / 0 info" in result.output
        assert "完整报告见 inkflow audit check --json" not in result.output

    def test_check_kernel_startup_error(self, cli_runner):
        """ensure_kernel 失败（内核冷启动超时）→ KERNEL_ERROR 信封 + 退出码 1（F38 spec §5.3）."""
        from inkflow.infrastructure.kernel import KernelStartupError

        with patch(
            "inkflow.cli.commands.audit.ensure_kernel",
            AsyncMock(side_effect=KernelStartupError("启动超时")),
        ):
            result = cli_runner.invoke(
                app,
                ["check", "--project-id", str(PID)],
                obj=CliContext(json_output=True),
            )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "KERNEL_ERROR"
        assert "内核启动失败" in data["error"]["message"]
