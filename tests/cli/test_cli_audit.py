"""F15 审计 CLI 命令测试 — Mock AuditService 隔离数据库（spec §4/§9 CLI 测试）。

覆盖（依据 specs/f15-audit-service/spec.md §4/§7/§9）:
- audit 组注册（check 命令）
- check 人类可读摘要两种形态（✅ 审计通过 / ❌ 不一致；error/warning 逐条、
  info 只计数不逐条、末尾提示 --json）
- check --json 完整报告信封（{"ok": true, "data": ...} + data.summary.consistent）
- 发现 error findings → 退出码恒 0（Q1 拍板 A：发现不一致是「结果」非「执行错误」）
- 项目不存在 → NOT_FOUND 错误信封 + 退出码 1
- 数据库读取失败 → DB_ERROR 错误信封 + 退出码 1
- 缺 --project-id → 退出码 2（Typer 必填参数）

策略: patch("inkflow.cli.commands.audit.AuditService") 整体替换服务类
（CLI 模块内 import 位置，同 F12/F14 CLI 测试）+ patch create_tables
避免数据库初始化。测试全同步（CliRunner.invoke），无需 pytestmark。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from inkflow.cli.commands.audit import app
from inkflow.domain.models.audit import (
    AuditDimension,
    AuditFinding,
    AuditReport,
    AuditSeverity,
    AuditSummary,
    DimensionSummary,
)
from inkflow.domain.ports.audit_errors import ProjectNotFoundError
from typer.testing import CliRunner

from inkflow.cli.context import CliContext
from inkflow.domain.models.timeline import (
    ConsistencyReport,
    TimelineConflict,
    TimelineEventRef,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）。"""
    return CliRunner()


@pytest.fixture
def mock_audit_service():
    """Mock AuditService，绕过数据库（ADR-015 依赖注入）。"""
    with patch("inkflow.cli.commands.audit.AuditService", autospec=True) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_create_tables():
    """Mock create_tables 避免数据库初始化。"""
    with patch("inkflow.cli.commands.audit.create_tables", AsyncMock()):
        yield


def _finding(**overrides: object) -> AuditFinding:
    """构造测试用 AuditFinding（默认 error 级关系悬空引用）。"""
    kwargs: dict[str, object] = {
        "id": "character.relation_ref:7a4f2c91-0000-4000-8000-000000000001",
        "rule_id": "character.relation_ref",
        "dimension": AuditDimension.CHARACTER,
        "severity": AuditSeverity.ERROR,
        "message": "关系 林晚→?? 的 to 端指向不存在的角色（悬空引用，请删除该关系或恢复目标角色）",
        "entity_type": "relation",
        "entity_id": uuid.UUID("7a4f2c91-0000-4000-8000-000000000001"),
        "entity_name": "林晚→??",
        "ref_type": "character",
        "ref_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "data": {"relation_type": "敌对"},
    }
    kwargs.update(overrides)
    return AuditFinding(**kwargs)  # type: ignore[arg-type]


def _timeline_check() -> ConsistencyReport:
    """构造 F12 ConsistencyReport 嵌套报告（1 条 order_conflict）。"""
    return ConsistencyReport(
        project_id=PID,
        checked=6,
        skipped=0,
        consistent=False,
        conflicts=[
            TimelineConflict(
                conflict_type="order_conflict",
                prev=TimelineEventRef(
                    id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
                    title="林晚入宫",
                    time_value=5.0,
                    time_display="",
                    narrative_position=1,
                    timeline_flag="",
                ),
                next=TimelineEventRef(
                    id=uuid.UUID("4a5b6c7d-0000-4000-8000-000000000001"),
                    title="外门往事",
                    time_value=3.0,
                    time_display="",
                    narrative_position=2,
                    timeline_flag="",
                ),
                message=(
                    "叙事顺序中「林晚入宫」之后是「外门往事」，但世界内时间 5.0 > 3.0"
                    "——时间倒流（未声明倒叙）"
                ),
            )
        ],
        flashbacks=[],
        event_timeline=[],
        narrative_order=[],
    )


def _make_report(**overrides: object) -> AuditReport:
    """构造不一致 AuditReport（1 error / 1 warning / 2 info + 嵌套时间线报告）。"""
    findings = [
        _finding(),
        _finding(
            id="foreshadowing.event_anchor:1a2b3c4d-0000-4000-8000-000000000001",
            rule_id="foreshadowing.event_anchor",
            dimension=AuditDimension.FORESHADOWING,
            severity=AuditSeverity.WARNING,
            message=(
                "伏笔「铜镜的秘密」锚点事件已软删（锚点保留但事件不在时间线视图中，"
                "请确认是否需解除挂接）"
            ),
            entity_type="foreshadowing",
            entity_id=uuid.UUID("1a2b3c4d-0000-4000-8000-000000000001"),
            entity_name="铜镜的秘密",
            ref_type="event",
            ref_id=uuid.UUID("8e9f0a1b-0000-4000-8000-000000000001"),
            data={},
        ),
        _finding(
            id="world.archive_gap:3f2e1d4a-0000-4000-8000-000000000001",
            rule_id="world.archive_gap",
            dimension=AuditDimension.WORLD,
            severity=AuditSeverity.INFO,
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
            dimension=AuditDimension.CROSS,
            severity=AuditSeverity.INFO,
            message="章节「第一章」从未执行过提取",
            entity_type="chapter",
            entity_id=uuid.UUID("5a6b7c8d-0000-4000-8000-000000000001"),
            entity_name="第一章",
            ref_type=None,
            ref_id=None,
            data={},
        ),
    ]
    summary = AuditSummary(
        consistent=False,
        total=4,
        by_dimension={
            AuditDimension.CHARACTER: DimensionSummary(error=1, warning=0, info=0),
            AuditDimension.TIMELINE: DimensionSummary(error=0, warning=0, info=0),
            AuditDimension.WORLD: DimensionSummary(error=0, warning=0, info=1),
            AuditDimension.FORESHADOWING: DimensionSummary(error=0, warning=1, info=0),
            AuditDimension.CROSS: DimensionSummary(error=0, warning=0, info=1),
        },
        counts={
            "characters": 3,
            "relations": 2,
            "groups": 1,
            "world_settings": 4,
            "events": 6,
            "foreshadowings": 2,
            "chapters": 3,
            "extraction_runs": 5,
        },
    )
    kwargs: dict[str, object] = {
        "project_id": PID,
        "generated_at": TS,
        "summary": summary,
        "findings": findings,
        "timeline_check": _timeline_check(),
    }
    kwargs.update(overrides)
    return AuditReport(**kwargs)  # type: ignore[arg-type]


def _consistent_report() -> AuditReport:
    """构造一致报告（0 error / 1 warning / 2 info，consistent=true）。"""
    findings = [
        _finding(
            id="foreshadowing.event_anchor:1a2b3c4d-0000-4000-8000-000000000001",
            rule_id="foreshadowing.event_anchor",
            dimension=AuditDimension.FORESHADOWING,
            severity=AuditSeverity.WARNING,
            message="伏笔「铜镜的秘密」锚点事件已软删（锚点保留但事件不在时间线视图中）",
            entity_type="foreshadowing",
            entity_id=uuid.UUID("1a2b3c4d-0000-4000-8000-000000000001"),
            entity_name="铜镜的秘密",
            ref_type="event",
            ref_id=uuid.UUID("8e9f0a1b-0000-4000-8000-000000000001"),
            data={},
        ),
        _finding(
            id="world.archive_gap:3f2e1d4a-0000-4000-8000-000000000001",
            rule_id="world.archive_gap",
            dimension=AuditDimension.WORLD,
            severity=AuditSeverity.INFO,
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
            dimension=AuditDimension.CROSS,
            severity=AuditSeverity.INFO,
            message="章节「第一章」从未执行过提取",
            entity_type="chapter",
            entity_id=uuid.UUID("5a6b7c8d-0000-4000-8000-000000000001"),
            entity_name="第一章",
            ref_type=None,
            ref_id=None,
            data={},
        ),
    ]
    return AuditReport(
        project_id=PID,
        generated_at=TS,
        summary=AuditSummary(
            consistent=True,
            total=3,
            by_dimension={
                AuditDimension.CHARACTER: DimensionSummary(error=0, warning=0, info=0),
                AuditDimension.TIMELINE: DimensionSummary(error=0, warning=0, info=0),
                AuditDimension.WORLD: DimensionSummary(error=0, warning=0, info=1),
                AuditDimension.FORESHADOWING: DimensionSummary(
                    error=0, warning=1, info=0
                ),
                AuditDimension.CROSS: DimensionSummary(error=0, warning=0, info=1),
            },
            counts={
                "characters": 3,
                "relations": 2,
                "groups": 1,
                "world_settings": 4,
                "events": 6,
                "foreshadowings": 2,
                "chapters": 3,
                "extraction_runs": 5,
            },
        ),
        findings=findings,
        timeline_check=ConsistencyReport(
            project_id=PID,
            checked=0,
            skipped=0,
            consistent=True,
            conflicts=[],
            flashbacks=[],
            event_timeline=[],
            narrative_order=[],
        ),
    )


class TestAuditRegistration:
    def test_group_help_lists_check(self):
        """audit 组帮助包含 check 命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）。"""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "check" in result.output


class TestAuditCheck:
    def test_check_human_consistent(
        self, cli_runner, mock_audit_service, mock_create_tables
    ):
        """check 人类模式一致 → ✅ 审计通过 + 三级计数摘要（spec §4.2）。"""
        mock_audit_service.run_audit.return_value = _consistent_report()
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 审计通过" in result.output
        assert "0 error / 1 warning / 2 info" in result.output

    def test_check_human_inconsistent(
        self, cli_runner, mock_audit_service, mock_create_tables
    ):
        """check 人类模式发现不一致 → ❌ 摘要 + error/warning 逐条 + info 只计数。"""
        mock_audit_service.run_audit.return_value = _make_report()
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

    def test_check_json_envelope(
        self, cli_runner, mock_audit_service, mock_create_tables
    ):
        """check --json → 成功信封 + 完整 AuditReport（data.summary.consistent）。"""
        mock_audit_service.run_audit.return_value = _make_report()
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
        mock_audit_service.run_audit.assert_awaited_once_with(project_id=PID)

    def test_check_error_findings_exit_0(
        self, cli_runner, mock_audit_service, mock_create_tables
    ):
        """发现 error findings → 退出码恒 0（Q1 拍板 A，spec §7/§12）。"""
        mock_audit_service.run_audit.return_value = _make_report()
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0

    def test_check_project_not_found_exit_1(
        self, cli_runner, mock_audit_service, mock_create_tables
    ):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1（spec §4.2 示例）。"""
        mock_audit_service.run_audit.side_effect = ProjectNotFoundError()
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

    def test_check_db_error_exit_1(
        self, cli_runner, mock_audit_service, mock_create_tables
    ):
        """数据库读取失败 → DB_ERROR 错误信封 + 退出码 1（spec §4/§7）。"""
        mock_audit_service.run_audit.side_effect = RuntimeError("数据库读取失败")
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"

    def test_check_missing_project_id_exit_2(
        self, cli_runner, mock_audit_service, mock_create_tables
    ):
        """缺 --project-id → 退出码 2（Typer 必填参数，spec §4/§9）。"""
        result = cli_runner.invoke(app, ["check"], obj=CliContext(json_output=False))
        assert result.exit_code == 2
