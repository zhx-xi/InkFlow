"""#335 F44 阶段1 `inkflow book` 命令组 CLI 契约测试（TDD RED 阶段）。

权威来源：specs/f44-book-orchestrator/spec.md §4（CLI 命令签名，v1.1）
+ §13.1 M1-M3。本文件为 `cli/commands/book_cmd.py`（NEW）定义契约。

════════════════════════════════════════════════════════════════════
命令契约（父侧定稿，spec §4，写进 docstring 供 GREEN）:
- `inkflow book plan start "<一句话>" --project <uuid> [--json]`
    启动访谈会话（POST /agent/books/planner body
    {project_id, one_liner}）→ 打印第一轮问题（≤5 问 + template）
    退出码: 0 成功 / 1 运行错误 / 2 参数错误
    --json 信封: {"ok": true, "data": {session_id, round, questions, max_rounds}}
    人类输出: 每问一行或等价形态——只断言 q1 的 id/text 出现在 stdout
- `inkflow book plan respond <session> "<回答>" [--json]`
    回复本轮（POST /agent/books/planner/{session}/respond body
    {answers: {"answer": <回答>}, auto: false}）→ 下一轮问 / 完成
    （宽容映射契约见 test_planner_service.py：单字符串回答 → 第一个必答）
    --json 信封: {"ok": true, "data": {session_id, round, completed,
    questions, writing_plan}}
    人类输出: 只断言 stdout 含「完成」或问题文本
- `inkflow book plan auto "<一句话>" --project <uuid> [--json]`
    「全部你决定」→ 直接跑 F42 write_auto（两步：POST /planner 创建会话 +
    POST /planner/{session}/respond {answers: {}, auto: true}）→ 打印
    WritingPlan（status=auto）
    --json 信封: {"ok": true, "data": {session_id, round, completed: true,
    questions: [], writing_plan: {...}}}
- `inkflow book plan show <session> [--json]`
    会话状态（GET /agent/books/planner/{session}）→ asked_questions/
    answers 快照
    --json 信封: {"ok": true, "data": <完整 PlannerSession>}
- `inkflow book plan run <plan_id> [--json]`
    委托一章（POST /agent/books/runs body {writing_plan_id}）→
    202 {run_id, status}（M1：plan start + plan respond + plan run）
    --json 信封: {"ok": true, "data": {run_id, status}}
- `inkflow book status <run_id> [--density performance|dashboard|silent] [--json]`
    书级运行状态（GET /agent/books/runs/{run_id}）→ 进度树 + 计数器
    （M3：上限写死章=1/调用=1 但计数器立起来——人类输出含 max/agent_calls/
    chapters_written 字样）
    --json 信封: {"ok": true, "data": {run_id, status, progress, counters}}

HTTP 契约（F38 恒经 HTTP，路径相对 base_url）:
- plan start → POST /agent/books/planner
- plan respond → POST /agent/books/planner/{session}/respond
- plan auto → POST /agent/books/planner + POST .../respond (auto=true)
- plan show → GET /agent/books/planner/{session}
- plan run → POST /agent/books/runs
- book status → GET /agent/books/runs/{run_id}
- 错误映射（map_http_error）: 404 → NOT_FOUND / 422 → VALIDATION_ERROR /
  其余 → INTERNAL_ERROR；KernelStartupError → KERNEL_ERROR

实现契约（GREEN）:
- CREATE cli/commands/book_cmd.py：`app = typer.Typer(name="book",
  help="书级编排管理", no_args_is_help=True)` + plan 子组
  （`plan_app = typer.Typer(name="plan", ...)` + `app.add_typer(plan_app)`）
- cli/app.py 注册 `app.add_typer(book_cmd.app, name="book")`
- 薄层：ensure_kernel + InkFlowHTTPClient（镜像 agent_cmd 形态）；
  错误面走 _run_ctx（print_error 信封 + exit 1）；人类输出走 typer.echo
- --json 经 ctx.obj.json_output 或命令级 --json 双读驱动
  （镜像 test_cli_agent_entity.py 契约）

── RED 预期形态 ────────────────────────────────────────────────
book 命令组不存在 → typer 报 `No such command 'book'.` + Usage +
exit_code 2 → 各用例 `assert result.exit_code == 0/1` 干净 FAILED；
守护用例（plan --help、run 缺参 exit 2）RED 阶段即 PASS。
预期形态约 12 failed, 2 passed。

ci.yml 登记声明: 新文件需父 agent 追加进 ci.yml integration-cli-backend
job 文件列表（tests/cli 显式列文件）。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.book_cmd import app
from inkflow.cli.context import CliContext

runner = CliRunner()

BOOK_MOD = "inkflow.cli.commands.book_cmd"


def _strip_ansi(text: str) -> str:
    """去除 ANSI 转义码（CI 环境 rich_markup_mode 会引入颜色码）。"""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


@pytest.fixture
def fake_http_client():
    """Patch book_cmd 内 ensure_kernel + InkFlowHTTPClient → fake client 实例."""
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(f"{BOOK_MOD}.ensure_kernel", AsyncMock(return_value=fake_handle)),
        patch(f"{BOOK_MOD}.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance
        yield mock_instance


def _invoke(*args, obj=None):
    """CliRunner 调用 book 命令组。"""
    ctx_obj = obj or CliContext(json_output=False)
    return runner.invoke(app, list(args), obj=ctx_obj)


# ════ F44 阶段4 追加段（#338 干预命令 + 回归摘要命令）════
# 权威来源：.hermes/plans/f44-stage4-contract.md §4。契约清单：
# 10. book intervene <run_id> --action pause → POST runs/{run_id}/intervene
#     body {"action": "pause", "target": None, "to": None, "payload": None}
#     + exit 0 + 人类输出「已暂停」+ run_id
# 11. book intervene <run_id> --action redirect --target c1 --to skip →
#     body {"action": "redirect", "target": "c1", "to": "skip", "payload": None}
#     + 人类输出「已跳过」
# 12. book intervene <run_id> --action edit --target c1 --brief ... → body
#     {"action": "edit", "target": "c1", "to": None, "payload": {"brief": ...}}
#     + --json 信封 {ok, data{run_id, status, diff}}
# 13. book intervene <run_id> --action resume --json → body
#     {"action": "resume", "target": None, "to": None, "payload": None} + 信封
# 14. book summary <run_id> → GET runs/{run_id}/summary + 人类输出含
#     进度/计数器内容（c1 + agent_calls）
# 15. book summary <run_id> --export <file> → GET + JSON 文件写盘内容断言
# 16. book summary <run_id> --json → 信封 {ok, data{run_id, status, progress,
#     counters, steps, next}}
#
# RED 预期形态：intervene/summary 命令未注册 → typer `No such command
# 'intervene'/'summary'.` + Usage + exit 2 → 各用例 `assert result.exit_code
# == 0` 干净 FAILED。预期形态：约 7 failed（新增段内）。


def _sample_summary_response():
    """回归摘要响应样本（§3.3 六键：run_id/status/progress/counters/steps/next）。"""
    return {
        "run_id": "run-1",
        "status": "waiting_hitl",
        "progress": {"c1": "done", "c2": "in_progress"},
        "counters": {
            "max_chapters": 2,
            "max_agent_calls": 2,
            "agent_calls": 1,
            "chapters_written": 1,
        },
        "steps": [
            {"index": 0, "outline_id": "c1", "status": "done", "execution_id": "e1"},
            {
                "index": 1,
                "outline_id": "c2",
                "status": "in_progress",
                "execution_id": None,
            },
        ],
        "next": {
            "volume_index": 0,
            "total_volumes": 2,
            "finished": False,
            "status": "running",
        },
    }


# ── book intervene ───────────────────────────────────────────────


def test_book_intervene_pause_human(fake_http_client):
    """book intervene --action pause：POST intervene + 人类输出「已暂停」（§4）。

    body {"action": "pause", "target": None, "to": None, "payload": None}。
    RED 期失败形态：intervene 命令未注册 → typer `No such command 'intervene'.`
    + Usage + exit 2 → `assert result.exit_code == 0` FAILED（干净 RED）。
    """
    fake_http_client.post.return_value = {"run_id": "run-1", "status": "paused"}

    result = _invoke("intervene", "run-1", "--action", "pause")

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "已暂停" in out
    assert "run-1" in out
    fake_http_client.post.assert_awaited_once_with(
        "/agent/books/runs/run-1/intervene",
        json={"action": "pause", "target": None, "to": None, "payload": None},
    )


def test_book_intervene_redirect_skip(fake_http_client):
    """book intervene --action redirect --target c1 --to skip：人类输出「已跳过」。

    RED 期失败形态：intervene 命令未注册 → No such command + exit 2 →
    `assert result.exit_code == 0` FAILED（干净 RED）。
    """
    fake_http_client.post.return_value = {
        "run_id": "run-1",
        "status": "running",
        "diff": {"target": "c1", "from": "in_progress", "to": "skipped"},
    }

    result = _invoke(
        "intervene", "run-1", "--action", "redirect", "--target", "c1", "--to", "skip"
    )

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "已跳过" in out
    fake_http_client.post.assert_awaited_once_with(
        "/agent/books/runs/run-1/intervene",
        json={"action": "redirect", "target": "c1", "to": "skip", "payload": None},
    )


def test_book_intervene_edit_json(fake_http_client):
    """book intervene --action edit --target c1 --brief ... --json：信封 + diff。

    body payload={"brief": ...}（§4 brief → payload 构造）。
    RED 期失败形态：intervene 命令未注册 → No such command + exit 2 →
    `assert result.exit_code == 0` FAILED（干净 RED）。
    """
    fake_http_client.post.return_value = {
        "run_id": "run-1",
        "status": "running",
        "diff": {
            "target": "c1",
            "before": "旧",
            "after": "新简介",
            "diff": "--- 旧\n+++ 新简介",
        },
    }

    result = _invoke(
        "intervene",
        "run-1",
        "--action",
        "edit",
        "--target",
        "c1",
        "--brief",
        "新简介",
        "--json",
    )

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    assert body["ok"] is True
    assert body["data"]["run_id"] == "run-1"
    assert body["data"]["diff"]["after"] == "新简介"
    fake_http_client.post.assert_awaited_once_with(
        "/agent/books/runs/run-1/intervene",
        json={
            "action": "edit",
            "target": "c1",
            "to": None,
            "payload": {"brief": "新简介"},
        },
    )


def test_book_intervene_resume_json(fake_http_client):
    """book intervene --action resume --json：信封 {ok, data{run_id, status}}。

    RED 期失败形态：intervene 命令未注册 → No such command + exit 2 →
    `assert result.exit_code == 0` FAILED（干净 RED）。
    """
    fake_http_client.post.return_value = {"run_id": "run-1", "status": "running"}

    result = _invoke("intervene", "run-1", "--action", "resume", "--json")

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    assert body["ok"] is True
    assert body["data"]["run_id"] == "run-1"
    assert body["data"]["status"] == "running"


# ── book summary ─────────────────────────────────────────────────


def test_book_summary_human(fake_http_client):
    """book summary：GET runs/{run_id}/summary + 人类输出含进度/计数器（§4）。

    RED 期失败形态：summary 命令未注册 → typer `No such command 'summary'.`
    + Usage + exit 2 → `assert result.exit_code == 0` FAILED（干净 RED）。
    """
    fake_http_client.get.return_value = _sample_summary_response()

    result = _invoke("summary", "run-1")

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "c1" in out
    assert "agent_calls" in out
    fake_http_client.get.assert_awaited_once_with("/agent/books/runs/run-1/summary")


def test_book_summary_export_json(fake_http_client, tmp_path):
    """book summary --export <file>：GET + 摘要 JSON 写盘内容断言（§4 导出）。"""
    fake_http_client.get.return_value = _sample_summary_response()
    export_file = tmp_path / "summary.json"

    result = _invoke("summary", "run-1", "--export", str(export_file))

    assert result.exit_code == 0
    saved = json.loads(export_file.read_text(encoding="utf-8"))
    assert saved["run_id"] == "run-1"
    assert saved["status"] == "waiting_hitl"
    assert saved["progress"] == {"c1": "done", "c2": "in_progress"}
    assert "steps" in saved
    assert "next" in saved


def test_book_summary_json_envelope(fake_http_client):
    """book summary --json：信封 {ok, data{run_id, status, progress, steps, next}}。

    RED 期失败形态：summary 命令未注册 → No such command + exit 2 →
    `assert result.exit_code == 0` FAILED（干净 RED）。
    """
    fake_http_client.get.return_value = _sample_summary_response()

    result = _invoke("summary", "run-1", "--json")

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    assert body["ok"] is True
    data = body["data"]
    assert data["run_id"] == "run-1"
    assert data["status"] == "waiting_hitl"
    assert data["steps"][0]["outline_id"] == "c1"
    assert data["next"]["finished"] is False


# ── TestCoverageGapCli：F44 覆盖率收口补测（人类输出渲染分支）────────────


class TestCoverageGapCli:
    """F44 阶段4 覆盖率门禁收口：book_cmd.py 人类输出渲染分支补测。

    - L373 resume 人类输出「已恢复」（既有仅 resume --json）
    - L377-385 edit 人类输出「已编辑」+ before/after（既有仅 edit --json）
    - L375 redirect mark_failed → _REDIRECT_LABELS 映射「已标记失败」（既有仅 redirect skip）
    - L76-77 _parse_limits 跳过无 `=` 的 item 分支
    """

    def test_intervene_resume_human(self, fake_http_client):
        """book intervene --action resume（人类输出）→「已恢复」+ run_id（L373）。"""
        fake_http_client.post.return_value = {"run_id": "run-1", "status": "running"}

        result = _invoke("intervene", "run-1", "--action", "resume")

        assert result.exit_code == 0
        out = _strip_ansi(result.stdout)
        assert "已恢复" in out
        assert "run-1" in out
        fake_http_client.post.assert_awaited_once_with(
            "/agent/books/runs/run-1/intervene",
            json={"action": "resume", "target": None, "to": None, "payload": None},
        )

    def test_intervene_edit_human(self, fake_http_client):
        """book intervene --action edit（人类输出）→「已编辑」+ before/after（L377-385）。"""
        fake_http_client.post.return_value = {
            "run_id": "run-1",
            "status": "running",
            "diff": {
                "target": "c1",
                "before": "旧梗概",
                "after": "新梗概",
                "diff": "--- 旧梗概\n+++ 新梗概",
            },
        }

        result = _invoke(
            "intervene",
            "run-1",
            "--action",
            "edit",
            "--target",
            "c1",
            "--brief",
            "新梗概",
        )

        assert result.exit_code == 0
        out = _strip_ansi(result.stdout)
        assert "已编辑" in out
        assert "c1" in out
        assert "before: 旧梗概" in out
        assert "after: 新梗概" in out
        fake_http_client.post.assert_awaited_once_with(
            "/agent/books/runs/run-1/intervene",
            json={
                "action": "edit",
                "target": "c1",
                "to": None,
                "payload": {"brief": "新梗概"},
            },
        )

    def test_intervene_redirect_mark_failed_human(self, fake_http_client):
        """book intervene --action redirect --to mark_failed（人类输出）→「已标记失败」（L375）。"""
        fake_http_client.post.return_value = {
            "run_id": "run-1",
            "status": "running",
            "diff": {"target": "c1", "from": "in_progress", "to": "failed"},
        }

        result = _invoke(
            "intervene",
            "run-1",
            "--action",
            "redirect",
            "--target",
            "c1",
            "--to",
            "mark_failed",
        )

        assert result.exit_code == 0
        out = _strip_ansi(result.stdout)
        assert "已标记失败" in out
        assert "c1" in out
        fake_http_client.post.assert_awaited_once_with(
            "/agent/books/runs/run-1/intervene",
            json={
                "action": "redirect",
                "target": "c1",
                "to": "mark_failed",
                "payload": None,
            },
        )

    def test_parse_limits_skips_item_without_equals(self):
        """_parse_limits 跳过无 `=` 的 item（L76-77）：仅解析合法 k=v。"""
        from inkflow.cli.commands.book_cmd import _parse_limits

        assert _parse_limits("max_chapters=5,noequal") == {"max_chapters": 5}
