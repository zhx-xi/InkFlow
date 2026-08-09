"""F34 章节审计 CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（spec §4/§9 CLI 测试）。

覆盖（specs/f34-chapter-audit/spec.md §4 CLI 命令签名 / §7 E12/E13 / §9.1 CLI 层 /
§9.2 关键场景 4）:

- 触发审计（人类输出）: findings 按 severity 打印（error 在前）+ degraded 提示
- 触发审计 --json: {"ok": true, "data": ChapterAuditReport} 信封（F7 全局约定）
- 项目名/章节名解析: 名称 → GET 列表匹配 id（UUID 直传不查列表）
- 项目/章节不存在 → NOT_FOUND 错误信封 + 退出 1
- --confirm accept/reject（+ --note）: POST confirm body {action, note} → 退出 0
- --confirm 无 pending（422）→ 退出 1（E12）
- --note 无 --confirm → 退出 2（E13）；--confirm 值非法 → 退出 2；
  --confirm 与 --history 互斥 → 退出 2；无 chapter 且无 --history → 退出 2
- --history: GET audit-logs → 人类列表输出（章名/状态/摘要/时间）

F38 恒 HTTP 模式（#169）: mock 目标 = ensure_kernel + InkFlowHTTPClient
（命令模块命名空间），HTTP JSON 响应直供，绕过真实内核。

── RED 形态说明 ─────────────────────────────────────────────
- 顶部 `from inkflow.cli.commands.audit_chapter import app` —— 命令模块尚
  不存在 → 本文件【收集期 ModuleNotFoundError】（collected 0 items）。
- HttpApiError 在用例体内惰性导入（tests/cli/test_cli_style.py 惯例）；
  inkflow.infrastructure.http 已实现（F38 已落地），可直接 import。

── 端点契约（spec §3.1 表；路径相对 InkFlowHTTPClient base_url /api/v1）──
- 触发:  POST /projects/{pid}/chapters/{cid}/audit       body {"include_static": bool}
- 确认:  POST /projects/{pid}/chapters/{cid}/audit/confirm  body {action, note}
- 历史:  GET  /projects/{pid}/audit-logs
- 名称解析: GET /projects（项目名→id）、GET /projects/{pid}/chapters（章名→id）
  —— 列表响应为 F22 CLI 先例信封 {"items": [...], "total": N}；
  items 字段契约: 项目 {"id", "name"}、章节 {"id", "title"}。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【命令注册】`inkflow.cli.commands.audit_chapter` 暴露
   `app = typer.Typer(name="chapter")` + `@app.command("chapter")`（F15
   audit.py add_typer 挂载后最终形态 `inkflow audit chapter ...`）；
   本文件直接 invoke app、首参 "chapter"。**必须带 `@app.callback()`
   空回调**（Typer 单命令提升规避，F15 audit.py 先例）——无 callback 时
   直接 invoke 会把命令名 "chapter" 吞为位置参数、后续参数报
   "Got unexpected extra argument(s)"（实测陷阱）。
2. 【参数】chapter: 位置参数（str|None——--history 模式下可不传，命令体内
   校验「无 chapter 且无 --history → 退出 2」）；--project/-p 必填；
   --include-static（默认含，spec §4）；--confirm accept|reject（Typer
   Option，非法值 → 退出 2）；--note/-n 默认 ""；--json 走
   ctx.obj.json_output（测试以 obj=CliContext(json_output=...) 注入，
   不传 "--json" 字面量，同 test_cli_style.py 惯例）。
3. 【HTTP 流程】ensure_kernel() → InkFlowHTTPClient(handle) → async with →
   项目解析（UUID 直传；名称 → GET /projects 匹配 name，无匹配 → NOT_FOUND
   退出 1）→ 章节解析（UUID 直传；名称 → GET /projects/{pid}/chapters 匹配
   title，无匹配 → NOT_FOUND 退出 1）→ 触发 POST /audit（body
   {"include_static": bool}，默认 True）/ 确认 POST /audit/confirm（body
   {"action": ..., "note": ...}）/ 历史 GET /audit-logs。
4. 【人类输出】触发: findings 逐条（error 在前），degraded=true 时输出含
   「降级」字样；确认: 「已接受」/「已拒绝」+ 确认时间（confirmed_at 原样
   透传）；历史: 列表含章节名/状态/摘要/时间。--json: print_result 信封
   （F7 {"ok": true, "data": ...}）。
5. 【错误映射】HttpApiError 经 map_http_error（同 F15 audit.py）: 404 →
   NOT_FOUND、422 → VALIDATION_ERROR、500 无头 → INTERNAL_ERROR；均退出 1。
6. 【退出码】成功 0；资源不存在/无 pending 1；用法错误 2。用法错误必须
   `typer.echo(..., err=True) + raise typer.Exit(code=2)`（F16 style.py
   L189-200 先例）——命令体内 `raise click.UsageError` 在本 Typer 版本下
   实测被映射为退出码 1（破坏退出 2 契约，陷阱）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.audit_chapter import app  # RED: 命令模块尚不存在
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000002")
TS = "2026-08-09T10:00:00Z"
CONFIRMED_TS = "2026-08-09T10:05:00Z"


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（NO_COLOR 规避 FORCE_COLOR 渲染坑，项目惯例）。"""
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP（F38 mock 轨）。

    命令模块将从 inkflow.infrastructure.kernel/http from-import 这两个名字——
    patch 目标 = 命令模块命名空间（F38 契约）。__aenter__ 返回自身，兼容
    spec §4 的 `async with InkFlowHTTPClient(handle) as client` 形态。
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
            "inkflow.cli.commands.audit_chapter.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.audit_chapter.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _finding(**overrides: object) -> dict:
    """构造单条 finding JSON dict（默认 character_drift ERROR，spec §3.2 示例同款）。"""
    kwargs: dict[str, object] = {
        "check_type": "character_drift",
        "severity": "error",
        "message": "本章「李青焰」怒斥同伴，但角色档案性格为「温厚沉稳」，行为可能与人设冲突",
        "suggestion": "可改为隐忍不发，或先铺垫情绪积累",
        "ref_entity_id": "0c000000-0000-4000-8000-00000000000c",
        "ref_entity_name": "李青焰",
        "context": "“够了！”李青焰猛地拍案而起，怒视众人……",
    }
    kwargs.update(overrides)
    return kwargs


def _report(**overrides: object) -> dict:
    """构造 POST audit 响应 JSON dict（ChapterAuditReport，spec §2.2/§3.2）。"""
    kwargs: dict[str, object] = {
        "chapter_id": str(CID),
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "findings": [
            _finding(),
            _finding(
                check_type="word_count",
                severity="info",
                message="本章 2,845 字，低于目标 3,000 字",
                suggestion="",
                ref_entity_id=None,
                ref_entity_name="",
                context="",
            ),
        ],
        "summary": "本章整体符合设定，一处角色行为值得斟酌",
        "degraded": False,
        "created_at": TS,
        "confirmed_at": None,
    }
    kwargs.update(overrides)
    return kwargs


def _log(**overrides: object) -> dict:
    """构造 audit_logs 列表项 JSON dict（spec §2.3/§3.2）。"""
    kwargs: dict[str, object] = {
        "id": "00000000-0000-4000-8000-0000000000a1",
        "project_id": str(PID),
        "chapter_id": str(CID),
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "accepted",
        "severity_summary": "1 error, 2 warnings, 0 info",
        "summary": "本章整体符合设定，一处角色行为值得斟酌",
        "degraded": False,
        "note": "",
        "created_at": TS,
        "confirmed_at": CONFIRMED_TS,
    }
    kwargs.update(overrides)
    return kwargs


def _project_item(**overrides: object) -> dict:
    """构造 GET /projects 列表项（id/name 契约，F22 CLI 先例）。"""
    kwargs: dict[str, object] = {"id": str(PID), "name": "测试项目"}
    kwargs.update(overrides)
    return kwargs


def _chapter_item(**overrides: object) -> dict:
    """构造 GET /projects/{pid}/chapters 列表项（id/title 契约）。"""
    kwargs: dict[str, object] = {"id": str(CID), "title": "第 3 章 龙的苏醒"}
    kwargs.update(overrides)
    return kwargs


class TestAuditTrigger:
    """inkflow audit chapter <chapter> -p <project> — 触发审计（spec §4 用法 1）。"""

    def test_trigger_uuid_direct_human(self, cli_runner, fake_http_client):
        """项目/章节 UUID 直传 → POST audit；人类输出 findings（error 在前）。"""
        fake_http_client.post.return_value = _report()

        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", str(PID)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        # UUID 直传：不查项目/章节列表
        fake_http_client.get.assert_not_awaited()
        call = fake_http_client.post.await_args
        assert call.args[0] == f"/projects/{PID}/chapters/{CID}/audit"
        assert call.kwargs["json"] == {"include_static": True}
        # 人类输出：error finding 在前，info 在后（spec §6 排序键）
        err_msg = "本章「李青焰」怒斥同伴"
        info_msg = "本章 2,845 字，低于目标 3,000 字"
        assert err_msg in result.output
        assert info_msg in result.output
        assert result.output.index(err_msg) < result.output.index(info_msg)
        assert "降级" not in result.output

    def test_trigger_project_name_resolution(self, cli_runner, fake_http_client):
        """项目名 → GET /projects 匹配 name → 用解析出的 id 调 audit。"""
        fake_http_client.get.return_value = {"items": [_project_item()], "total": 1}
        fake_http_client.post.return_value = _report()

        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", "测试项目"],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        assert fake_http_client.get.await_args.args[0] == "/projects"
        call = fake_http_client.post.await_args
        assert call.args[0] == f"/projects/{PID}/chapters/{CID}/audit"
        assert call.kwargs["json"] == {"include_static": True}

    def test_trigger_chapter_title_resolution(self, cli_runner, fake_http_client):
        """章节名 → GET /projects/{pid}/chapters 匹配 title → 用解析出的 id 调 audit。"""
        fake_http_client.get.return_value = {"items": [_chapter_item()], "total": 1}
        fake_http_client.post.return_value = _report()

        result = cli_runner.invoke(
            app,
            ["chapter", "第 3 章 龙的苏醒", "-p", str(PID)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        assert fake_http_client.get.await_args.args[0] == f"/projects/{PID}/chapters"
        call = fake_http_client.post.await_args
        assert call.args[0] == f"/projects/{PID}/chapters/{CID}/audit"

    def test_trigger_project_not_found_exit_1(self, cli_runner, fake_http_client):
        """项目名无匹配 → NOT_FOUND 错误信封 + 退出 1（spec §4 失败语义）。"""
        fake_http_client.get.return_value = {"items": [], "total": 0}

        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", "不存在的项目"],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "项目不存在" in data["error"]["message"]
        fake_http_client.post.assert_not_awaited()

    def test_trigger_chapter_not_found_exit_1(self, cli_runner, fake_http_client):
        """章节名无匹配 → NOT_FOUND 错误信封 + 退出 1。"""
        fake_http_client.get.return_value = {"items": [], "total": 0}

        result = cli_runner.invoke(
            app,
            ["chapter", "不存在的章节", "-p", str(PID)],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "章节不存在" in data["error"]["message"]
        fake_http_client.post.assert_not_awaited()

    def test_trigger_degraded_hint(self, cli_runner, fake_http_client):
        """LLM 降级报告 → 人类输出含降级提示（spec §5.3，降级不阻塞退出 0）。"""
        fake_http_client.post.return_value = _report(degraded=True)

        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", str(PID)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        assert "降级" in result.output

    def test_trigger_json_envelope(self, cli_runner, fake_http_client):
        """--json → {"ok": true, "data": ChapterAuditReport}（F7 信封）。"""
        fake_http_client.post.return_value = _report()

        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", str(PID)],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["chapter_id"] == str(CID)
        assert data["data"]["status"] == "pending"
        assert data["data"]["findings"][0]["check_type"] == "character_drift"
        assert data["data"]["degraded"] is False


class TestAuditConfirm:
    """inkflow audit chapter ... --confirm accept|reject [--note] — 确认（Q2=B）。"""

    def test_confirm_accept_exit_0(self, cli_runner, fake_http_client):
        """--confirm accept → POST confirm body {action, note: ""} → 退出 0「已接受」。"""
        fake_http_client.post.return_value = {
            "status": "accepted",
            "confirmed_at": CONFIRMED_TS,
        }

        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", str(PID), "--confirm", "accept"],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        call = fake_http_client.post.await_args
        assert call.args[0] == f"/projects/{PID}/chapters/{CID}/audit/confirm"
        assert call.kwargs["json"] == {"action": "accept", "note": ""}
        assert "已接受" in result.output
        assert CONFIRMED_TS in result.output

    def test_confirm_reject_with_note(self, cli_runner, fake_http_client):
        """--confirm reject --note → body 含 note → 退出 0「已拒绝」（spec §4 用法 3）。"""
        fake_http_client.post.return_value = {
            "status": "rejected",
            "confirmed_at": CONFIRMED_TS,
        }

        result = cli_runner.invoke(
            app,
            [
                "chapter",
                str(CID),
                "-p",
                str(PID),
                "--confirm",
                "reject",
                "--note",
                "人设需再打磨",
            ],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        call = fake_http_client.post.await_args
        assert call.args[0] == f"/projects/{PID}/chapters/{CID}/audit/confirm"
        assert call.kwargs["json"] == {"action": "reject", "note": "人设需再打磨"}
        assert "已拒绝" in result.output

    def test_confirm_no_pending_exit_1(self, cli_runner, fake_http_client):
        """--confirm 但无 pending 记录（HTTP 422）→ 退出 1（E12）。"""
        from inkflow.infrastructure.http import HttpApiError  # 惰性导入惯例

        fake_http_client.post.side_effect = HttpApiError(422, "该章无待确认审计")

        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", str(PID), "--confirm", "accept"],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 1
        assert "该章无待确认审计" in result.output

    def test_note_without_confirm_exit_2(self, cli_runner, fake_http_client):
        """--note 无 --confirm → 退出 2（用法错误，spec §4 v1.1 说明 / E13）。"""
        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", str(PID), "--note", "备注"],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()

    def test_confirm_invalid_value_exit_2(self, cli_runner, fake_http_client):
        """--confirm 值非 accept/reject → 退出 2（spec §4 用法错误）。"""
        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", str(PID), "--confirm", "maybe"],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()

    def test_confirm_with_history_exit_2(self, cli_runner, fake_http_client):
        """--confirm 与 --history 互斥 → 退出 2（spec §4 v1.1 说明）。"""
        result = cli_runner.invoke(
            app,
            ["chapter", str(CID), "-p", str(PID), "--confirm", "accept", "--history"],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 2
        fake_http_client.get.assert_not_awaited()
        fake_http_client.post.assert_not_awaited()


class TestAuditHistory:
    """inkflow audit chapter --history -p <project> — 审计记录查询（Q1=C）。"""

    def test_history_lists_logs_human(self, cli_runner, fake_http_client):
        """--history → GET audit-logs → 人类列表输出（章名/状态/摘要/时间）。"""
        fake_http_client.get.return_value = {"total": 1, "logs": [_log()]}

        result = cli_runner.invoke(
            app,
            ["chapter", "--history", "-p", str(PID)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        assert fake_http_client.get.await_args.args[0] == f"/projects/{PID}/audit-logs"
        assert "第 3 章 龙的苏醒" in result.output
        assert "accepted" in result.output
        assert "1 error, 2 warnings, 0 info" in result.output
        assert CONFIRMED_TS in result.output

    def test_history_json_envelope(self, cli_runner, fake_http_client):
        """--history --json → {"ok": true, "data": {total, logs}}。"""
        fake_http_client.get.return_value = {"total": 1, "logs": [_log()]}

        result = cli_runner.invoke(
            app,
            ["chapter", "--history", "-p", str(PID)],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["total"] == 1
        assert data["data"]["logs"][0]["chapter_title"] == "第 3 章 龙的苏醒"
        assert data["data"]["logs"][0]["status"] == "accepted"

    def test_no_chapter_no_history_exit_2(self, cli_runner, fake_http_client):
        """无 chapter 且无 --history → 退出 2（无事可做，用法错误）。"""
        result = cli_runner.invoke(
            app,
            ["chapter", "-p", str(PID)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 2
        fake_http_client.get.assert_not_awaited()
        fake_http_client.post.assert_not_awaited()
