"""#335 F44 阶段1 `inkflow book` 命令组 CLI 契约测试（TDD RED 阶段）。

权威来源：specs/f44-long-task-orchestrator/spec.md §4（CLI 命令签名，v1.1）
+ §13.1 M1-M3。本文件为 `cli/commands/book_cmd.py`（NEW）定义契约。

════════════════════════════════════════════════════════════════════
命令契约（父侧定稿，spec §4，写进 docstring 供 GREEN）:
- `inkflow book plan start "<一句话>" --project <uuid> [--json]`
    启动访谈会话（POST /api/v1/agent/books/planner body
    {project_id, one_liner}）→ 打印第一轮问题（≤5 问 + template）
    退出码: 0 成功 / 1 运行错误 / 2 参数错误
    --json 信封: {"ok": true, "data": {session_id, round, questions, max_rounds}}
    人类输出: 每问一行或等价形态——只断言 q1 的 id/text 出现在 stdout
- `inkflow book plan respond <session> "<回答>" [--json]`
    回复本轮（POST /api/v1/agent/books/planner/{session}/respond body
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
    会话状态（GET /api/v1/agent/books/planner/{session}）→ asked_questions/
    answers 快照
    --json 信封: {"ok": true, "data": <完整 PlannerSession>}
- `inkflow book plan run <plan_id> [--json]`
    委托一章（POST /api/v1/agent/books/runs body {writing_plan_id}）→
    202 {run_id, status}（M1：plan start + plan respond + plan run）
    --json 信封: {"ok": true, "data": {run_id, status}}
- `inkflow book status <run_id> [--density performance|dashboard|silent] [--json]`
    书级运行状态（GET /api/v1/agent/books/runs/{run_id}）→ 进度树 + 计数器
    （M3：上限写死章=1/调用=1 但计数器立起来——人类输出含 max/agent_calls/
    chapters_written 字样）
    --json 信封: {"ok": true, "data": {run_id, status, progress, counters}}

HTTP 契约（F38 恒经 HTTP，路径相对 base_url）:
- plan start → POST /api/v1/agent/books/planner
- plan respond → POST /api/v1/agent/books/planner/{session}/respond
- plan auto → POST /api/v1/agent/books/planner + POST .../respond (auto=true)
- plan show → GET /api/v1/agent/books/planner/{session}
- plan run → POST /api/v1/agent/books/runs
- book status → GET /api/v1/agent/books/runs/{run_id}
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


def _sample_start_response():
    return {
        "session_id": "sess-1",
        "round": 1,
        "questions": [
            {
                "id": "q1",
                "text": "题材：悬疑为主，还是悬疑+科幻混合？",
                "template": "悬疑为主，但加入 ___ 元素",
            },
            {"id": "q2", "text": "篇幅：预计多少字？", "template": "约 ___ 字"},
        ],
        "max_rounds": 5,
    }


def _sample_respond_response():
    return {
        "session_id": "sess-1",
        "round": 2,
        "completed": False,
        "questions": [
            {"id": "q4", "text": "配角：需要几个主要配角？", "template": "___ 个"}
        ],
        "writing_plan": None,
    }


def _sample_status_response():
    return {
        "run_id": "run-1",
        "status": "completed",
        "progress": {"c1": "done"},
        "counters": {
            "max_chapters": 1,
            "max_agent_calls": 1,
            "agent_calls": 1,
            "chapters_written": 1,
        },
    }


# ── plan start ────────────────────────────────────────────────────


def test_plan_start_human(fake_http_client):
    """plan start 人类模式：POST planner + stdout 含问题文本 + exit 0。"""
    fake_http_client.post.return_value = _sample_start_response()

    result = _invoke(
        "plan", "start", "写一本关于时间旅者的悬疑小说", "--project", "proj-1"
    )

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "题材" in out
    fake_http_client.post.assert_awaited_once_with(
        "/api/v1/agent/books/planner",
        json={"project_id": "proj-1", "one_liner": "写一本关于时间旅者的悬疑小说"},
    )


def test_plan_start_json(fake_http_client):
    """plan start --json：信封 {ok, data{session_id, round, questions}}。"""
    fake_http_client.post.return_value = _sample_start_response()

    result = _invoke(
        "plan", "start", "写一本关于时间旅者的悬疑小说", "--project", "proj-1", "--json"
    )

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    assert body["ok"] is True
    assert body["data"]["session_id"] == "sess-1"
    assert body["data"]["round"] == 1
    assert len(body["data"]["questions"]) <= 5


# ── plan respond ──────────────────────────────────────────────────


def test_plan_respond(fake_http_client):
    """plan respond：POST respond + 宽容映射（answers={"answer": ...}）+ exit 0。"""
    fake_http_client.post.return_value = _sample_respond_response()

    result = _invoke("plan", "respond", "sess-1", "悬疑为主，加入时间悖论")

    assert result.exit_code == 0
    fake_http_client.post.assert_awaited_once_with(
        "/api/v1/agent/books/planner/sess-1/respond",
        json={"answers": {"answer": "悬疑为主，加入时间悖论"}, "auto": False},
    )


def test_plan_respond_json_completed(fake_http_client):
    """plan respond --json completed：信封含 writing_plan（status=ready）。"""
    fake_http_client.post.return_value = {
        "session_id": "sess-1",
        "round": 3,
        "completed": True,
        "questions": [],
        "writing_plan": {
            "id": "plan-1",
            "project_id": "proj-1",
            "title": "写一本关于时间旅者的悬疑小说",
            "status": "ready",
        },
    }

    result = _invoke("plan", "respond", "sess-1", "3 卷", "--json")

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    assert body["ok"] is True
    assert body["data"]["completed"] is True
    assert body["data"]["writing_plan"]["status"] == "ready"


# ── plan auto ─────────────────────────────────────────────────────


def test_plan_auto_calls_write_auto_path(fake_http_client):
    """plan auto：两步（POST planner 创建会话 + POST respond auto=true）→ status=auto。"""
    fake_http_client.post.side_effect = [
        _sample_start_response(),
        {
            "session_id": "sess-1",
            "round": 1,
            "completed": True,
            "questions": [],
            "writing_plan": {
                "id": "plan-auto",
                "project_id": "proj-1",
                "title": "写一本关于时间旅者的悬疑小说",
                "status": "auto",
            },
        },
    ]

    result = _invoke(
        "plan", "auto", "写一本关于时间旅者的悬疑小说", "--project", "proj-1"
    )

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "auto" in out
    calls = fake_http_client.post.await_args_list
    assert len(calls) == 2
    # 第二步：respond auto=true（「全部你决定」→ F42 委托）
    second = calls[1]
    assert second.args[0] == "/api/v1/agent/books/planner/sess-1/respond"
    assert second.kwargs["json"] == {"answers": {}, "auto": True}


def test_plan_auto_json(fake_http_client):
    """plan auto --json：信封含 writing_plan.status=auto。"""
    fake_http_client.post.side_effect = [
        _sample_start_response(),
        {
            "session_id": "sess-1",
            "round": 1,
            "completed": True,
            "questions": [],
            "writing_plan": {
                "id": "plan-auto",
                "project_id": "proj-1",
                "title": "写一本关于时间旅者的悬疑小说",
                "status": "auto",
            },
        },
    ]

    result = _invoke(
        "plan", "auto", "写一本关于时间旅者的悬疑小说", "--project", "proj-1", "--json"
    )

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    assert body["ok"] is True
    assert body["data"]["completed"] is True
    assert body["data"]["writing_plan"]["status"] == "auto"


# ── plan show ─────────────────────────────────────────────────────


def test_plan_show(fake_http_client):
    """plan show：GET planner/{session} + 会话状态快照 + exit 0。"""
    fake_http_client.get.return_value = {
        "id": "sess-1",
        "project_id": "proj-1",
        "status": "drafting",
        "one_liner": "写一本关于时间旅者的悬疑小说",
        "round": 1,
        "asked_questions": [
            {
                "id": "q1",
                "text": "题材：悬疑为主，还是悬疑+科幻混合？",
                "template": "___",
            }
        ],
        "answers": {},
        "authorized": [],
        "writing_plan_id": None,
    }

    result = _invoke("plan", "show", "sess-1")

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "题材" in out
    fake_http_client.get.assert_awaited_once_with("/api/v1/agent/books/planner/sess-1")


# ── plan run ──────────────────────────────────────────────────────


def test_plan_run_returns_run_id(fake_http_client):
    """plan run：POST runs + 返回 run_id/status（M1 验收 plan run）。"""
    fake_http_client.post.return_value = {"run_id": "run-1", "status": "pending"}

    result = _invoke("plan", "run", "plan-1")

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "run-1" in out
    fake_http_client.post.assert_awaited_once_with(
        "/api/v1/agent/books/runs",
        json={"writing_plan_id": "plan-1"},
    )


def test_plan_run_json(fake_http_client):
    """plan run --json：信封 {ok, data{run_id, status}}。"""
    fake_http_client.post.return_value = {"run_id": "run-1", "status": "pending"}

    result = _invoke("plan", "run", "plan-1", "--json")

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    assert body["data"]["run_id"] == "run-1"
    assert body["data"]["status"] == "pending"


# ── book status ───────────────────────────────────────────────────


def test_book_status_shows_counters(fake_http_client):
    """book status：GET runs/{run_id} + 人类输出含计数（M3 上限计数器立起来）。"""
    fake_http_client.get.return_value = _sample_status_response()

    result = _invoke("status", "run-1")

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "run-1" in out
    assert "max_chapters" in out or "max_agent_calls" in out or "agent_calls" in out
    fake_http_client.get.assert_awaited_once_with("/api/v1/agent/books/runs/run-1")


def test_book_status_json_counters(fake_http_client):
    """book status --json：信封含 progress + counters（max=1/1）。"""
    fake_http_client.get.return_value = _sample_status_response()

    result = _invoke("status", "run-1", "--json")

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    counters = body["data"]["counters"]
    assert counters["max_chapters"] == 1
    assert counters["max_agent_calls"] == 1
    assert counters["agent_calls"] == 1
    assert counters["chapters_written"] == 1


# ── 错误面 ────────────────────────────────────────────────────────


def test_plan_start_http_404(fake_http_client):
    """HTTP 404 → stderr ❌ + exit 1（map_http_error 语义）。"""
    from inkflow.infrastructure.http import HttpApiError

    fake_http_client.post.side_effect = HttpApiError(404, "会话不存在", "NOT_FOUND")

    result = _invoke("plan", "start", "一句话", "--project", "proj-x")

    assert result.exit_code == 1
    err = _strip_ansi(result.stderr)
    assert "❌" in err


def test_plan_run_missing_argument():
    """plan run 缺 plan_id → exit 2（参数错误）。"""
    result = _invoke("plan", "run")
    assert result.exit_code == 2


def test_book_plan_help():
    """book plan --help 显示子命令（守护用例，RED 阶段即 PASS）。"""
    result = _invoke("plan", "--help")
    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "start" in out and "respond" in out and "auto" in out


# ── Coverage-Gap 补测（2026-08-17 CI coverage-backend 98.39% 缺口）──


def test_kernel_startup_error(fake_http_client):
    """内核启动失败 → stderr KERNEL_ERROR + exit 1（KernelStartupError 分支）。"""
    from inkflow.infrastructure.kernel import KernelStartupError

    fake_http_client.post.side_effect = KernelStartupError("内核起不来")

    result = _invoke("plan", "start", "一句话", "--project", "proj-x")

    assert result.exit_code == 1
    err = _strip_ansi(result.stderr)
    assert "KERNEL_ERROR" in err or "内核启动失败" in err


def test_global_json_output_driver(fake_http_client):
    """全局 ctx.obj.json_output=True 驱动信封（_human_or_json 全局分支）。"""
    fake_http_client.get.return_value = {
        "id": "sess-1",
        "project_id": "proj-1",
        "status": "drafting",
        "one_liner": "一句话",
        "round": 1,
        "asked_questions": [],
        "answers": {},
        "authorized": [],
        "writing_plan_id": None,
    }

    # 不带命令级 --json，但全局 obj.json_output=True
    result = _invoke("plan", "show", "sess-1", obj=CliContext(json_output=True))

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    assert body["ok"] is True
    assert body["data"]["id"] == "sess-1"


def test_plan_respond_completed_human_output(fake_http_client):
    """respond completed 人类输出：✓ 访谈完成 + writing_plan 摘要（渲染分支）。"""
    fake_http_client.post.return_value = {
        "session_id": "sess-1",
        "round": 3,
        "completed": True,
        "questions": [],
        "writing_plan": {
            "id": "plan-1",
            "project_id": "proj-1",
            "title": "一句话",
            "status": "ready",
        },
    }

    result = _invoke("plan", "respond", "sess-1", "3 卷")

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "访谈完成" in out
    assert "ready" in out


def test_plan_show_data_none_early_return(fake_http_client):
    """show HTTP 404 → data None 早退 exit 1（错误路径已由 _run_ctx 处理）。"""
    from inkflow.infrastructure.http import HttpApiError

    fake_http_client.get.side_effect = HttpApiError(404, "会话不存在", "NOT_FOUND")

    result = _invoke("plan", "show", "nope")

    assert result.exit_code == 1
    assert "❌" in _strip_ansi(result.stderr)


# ── 阶段 2（#336）：book run 顶层命令 + 多章状态 ─────────────────
#
# 契约（父侧定稿，spec §4 阶段 2 + §5.2 + §13.2 M4/M5）:
# - `inkflow book run <plan_id> [--limits max_chapters=5,max_tokens=200000] [--json]`
#     顶层命令（app.command("run")，不在 plan 子组；plan run 保留兼容）
#     POST /api/v1/agent/books/runs body {writing_plan_id, limits?} →
#     {run_id, status}
#     --limits 逗号分隔 k=v 解析为 dict（"max_chapters=5,max_tokens=200000"
#     → {"max_chapters": 5, "max_tokens": 200000}）；不传则 body 无 limits 键
#     人类输出含 run_id；--json 信封: {"ok": true, "data": {run_id, status}}
# - `inkflow book status` 人类输出每章一行状态（progress 行，M4 已满足，
#   测试只断言 progress 行存在，不锁章名渲染）
#
# RED 预期形态（阶段 1 实现）：顶层 run 未注册 → typer 报
# `No such command 'run'.` + Usage + exit 2 → run 三用例断言 exit_code==0
# 干净 FAILED；缺参用例（exit 2）与 status 多章用例（progress 行已渲染）
# RED 期即 PASS（守护，刻意）。


def test_book_run_top_level_command(fake_http_client):
    """book run 顶层命令：POST /api/v1/agent/books/runs body {writing_plan_id}
    → run_id/status（spec §4 阶段 2：inkflow book run <plan_id>）。"""
    fake_http_client.post.return_value = {"run_id": "run-1", "status": "pending"}

    result = _invoke("run", "plan-1")

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "run-1" in out
    fake_http_client.post.assert_awaited_once_with(
        "/api/v1/agent/books/runs",
        json={"writing_plan_id": "plan-1"},
    )


def test_book_run_with_limits(fake_http_client):
    """book run --limits：逗号分隔 k=v 解析为 dict 进 body.limits
    （"max_chapters=5,max_tokens=200000" → {max_chapters: 5, max_tokens: 200000}）。"""
    fake_http_client.post.return_value = {"run_id": "run-1", "status": "pending"}

    result = _invoke("run", "plan-1", "--limits", "max_chapters=5,max_tokens=200000")

    assert result.exit_code == 0
    fake_http_client.post.assert_awaited_once_with(
        "/api/v1/agent/books/runs",
        json={
            "writing_plan_id": "plan-1",
            "limits": {"max_chapters": 5, "max_tokens": 200000},
        },
    )


def test_book_run_json_envelope(fake_http_client):
    """book run --json：信封 {ok: true, data: {run_id, status}}（F7 全局约定）。"""
    fake_http_client.post.return_value = {"run_id": "run-1", "status": "pending"}

    result = _invoke("run", "plan-1", "--json")

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    assert body["ok"] is True
    assert body["data"]["run_id"] == "run-1"
    assert body["data"]["status"] == "pending"


def test_book_run_missing_argument():
    """book run 缺 plan_id → exit 2（守护用例：RED 期顶层 run 未注册时
    No such command 亦 exit 2 → 本用例 RED 期 PASS 刻意；GREEN 后为 typer
    参数缺失 exit 2）。"""
    result = _invoke("run")
    assert result.exit_code == 2


def test_book_status_multi_chapter_progress(fake_http_client):
    """book status 多章：progress 3 章 → 人类输出每章一行状态（M4 每章状态显示。
    守护用例：阶段 1 status 已渲染 progress 行 → RED 期 PASS 刻意）。"""
    fake_http_client.get.return_value = {
        "run_id": "run-1",
        "status": "completed",
        "progress": {"c1": "done", "c2": "done", "c3": "done"},
        "counters": {
            "max_chapters": 3,
            "max_agent_calls": 3,
            "agent_calls": 3,
            "chapters_written": 3,
        },
    }

    result = _invoke("status", "run-1")

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "c1" in out and "c2" in out and "c3" in out
    assert out.count("done") == 3


# ════ F44 阶段3 追加段（#337 confirm 端点/命令）════
# 权威来源：.hermes/plans/f44-stage3-contract.md §4 + spec.md §4/§13.3 M8。
# 契约清单：
# 6. book confirm <run_id> --approved → POST /api/v1/agent/books/runs/{run_id}/
#    confirm body {"approved": true, "decision": ""} + exit 0 + 人类输出含状态
# 7. book confirm <run_id> --reject --decision "中止" → body
#    {"approved": false, "decision": "中止"} + exit 0
# 8. book confirm <run_id> --approved --json → 信封 {"ok": true, "data":
#    {run_id, status, next_checkpoint}}
# 9. book confirm（无 run_id）→ exit 2（守护用例：RED 期命令未注册时
#    `No such command 'confirm'.` 亦 exit 2 → PASS 刻意，docstring 注明双阶段语义）
#
# RED 预期形态：book confirm 命令未注册 → typer 报 `No such command 'confirm'.`
# + Usage + exit 2 → 用例 6/7/8 `assert result.exit_code == 0` 干净 FAILED；
# 用例 9（缺参 exit 2）RED 期即 PASS（守护，刻意）。预期形态 ≈ 3 failed, 1 passed。


# ── book confirm ─────────────────────────────────────────────────


def test_book_confirm_approved(fake_http_client):
    """book confirm --approved：POST runs/{run_id}/confirm + exit 0（M8）。

    body {"approved": true, "decision": ""}（--approved 缺省 decision=""）；
    人类输出含状态（已确认 + run_id + status）。
    RED 期失败形态：confirm 命令未注册 → typer `No such command 'confirm'.`
    + Usage + exit 2 → `assert result.exit_code == 0` FAILED（干净 RED）。
    """
    fake_http_client.post.return_value = {
        "run_id": "run-1",
        "status": "running",
        "next_checkpoint": "卷 2",
    }

    result = _invoke("confirm", "run-1", "--approved")

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert "已确认" in out
    assert "run-1" in out
    assert "running" in out
    fake_http_client.post.assert_awaited_once_with(
        "/api/v1/agent/books/runs/run-1/confirm",
        json={"approved": True, "decision": ""},
    )


def test_book_confirm_reject_decision(fake_http_client):
    """book confirm --reject --decision：approved=false + decision 透传 + exit 0。

    body {"approved": false, "decision": "中止"}（--reject/--decision 组合，
    §4 互斥/可选语义）。
    RED 期失败形态：confirm 命令未注册 → typer `No such command 'confirm'.`
    + Usage + exit 2 → `assert result.exit_code == 0` FAILED（干净 RED）。
    """
    fake_http_client.post.return_value = {
        "run_id": "run-1",
        "status": "completed",
        "next_checkpoint": None,
    }

    result = _invoke("confirm", "run-1", "--reject", "--decision", "中止")

    assert result.exit_code == 0
    fake_http_client.post.assert_awaited_once_with(
        "/api/v1/agent/books/runs/run-1/confirm",
        json={"approved": False, "decision": "中止"},
    )


def test_book_confirm_json_envelope(fake_http_client):
    """book confirm --approved --json：信封 {ok, data{run_id, status, next_checkpoint}}。

    RED 期失败形态：confirm 命令未注册 → typer `No such command 'confirm'.`
    + Usage + exit 2 → `assert result.exit_code == 0` FAILED（干净 RED）。
    """
    fake_http_client.post.return_value = {
        "run_id": "run-1",
        "status": "running",
        "next_checkpoint": "卷 2",
    }

    result = _invoke("confirm", "run-1", "--approved", "--json")

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    assert body["ok"] is True
    assert body["data"]["run_id"] == "run-1"
    assert body["data"]["status"] == "running"
    assert body["data"]["next_checkpoint"] == "卷 2"


def test_book_confirm_missing_argument():
    """book confirm 缺 run_id → exit 2（守护用例：RED 期 confirm 命令未注册时
    `No such command 'confirm'.` 亦 exit 2 → 本用例 RED 期 PASS 刻意；GREEN 后
    为 typer 参数缺失 exit 2，双阶段语义）。"""
    result = _invoke("confirm")
    assert result.exit_code == 2


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
        "/api/v1/agent/books/runs/run-1/intervene",
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
        "/api/v1/agent/books/runs/run-1/intervene",
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
        "/api/v1/agent/books/runs/run-1/intervene",
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
    fake_http_client.get.assert_awaited_once_with(
        "/api/v1/agent/books/runs/run-1/summary"
    )


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
            "/api/v1/agent/books/runs/run-1/intervene",
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
            "/api/v1/agent/books/runs/run-1/intervene",
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
            "/api/v1/agent/books/runs/run-1/intervene",
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
