"""F27 M6 CLI RED 契约测试 — agent draft list/confirm/reject（草稿确认流，spec §4.2）.

测试范围：inkflow agent draft list/confirm/reject --help 与真实执行路径（HTTP mock 轨）。

需 pytest marker: @pytest.mark.agent

══════════════════════════════════════════════════════════════════════════
HTTP 契约（实现者以本文件为准）:
- draft list → GET /agent/drafts（params: project_id, status, offset, limit）
  → 200: {"items": [draft...], "total": N}
- draft confirm → POST /agent/drafts/{draft_id}/confirm（body {"chapter_id"} 可选）
  → 200: {"draft_id": "<id>", "status": "confirmed", "chapter_id": "<UUID str>"}
- draft reject → POST /agent/drafts/{draft_id}/reject（body: 空或 {"reason": "..."}）
  → 200: {"draft_id": "<id>", "status": "rejected"}
- 错误 = HttpApiError(status_code, detail[, code])：404（草稿不存在）→
  「❌ {detail}」stderr + 退出码 1；409（草稿已确认/状态非 draft）→ 同形
══════════════════════════════════════════════════════════════════════════

人类模式输出（父侧定稿，实现按此）:
- list: 首行「共 N 条草稿」；每行「{id}  {status}  {summary or "-"}」
- confirm 成功: 「✅ 章节已更新 (status=final, 字数 {N})」（N = 确认后内容字数）
- reject 成功: 「✅ 草稿已拒绝（保留记录）」
- --json: print_result 信封 {"ok": true, "data": <API 响应原样>}

RED 预期
--------
agent draft 子命令不存在 → typer exit 2（No such command 'draft'）；help 断言
FAIL；执行路径测试的 patch setup 抛 AttributeError（agent_cmd 无
ensure_kernel/InkFlowHTTPClient 属性——同 test_cli_agent.py 根因，预期 RED）。

asyncio 模式: 本 venv 实测头部 asyncio: mode=Mode.AUTO（pyproject asyncio_mode = "auto"
生效）；fake_http_client fixture 内 AsyncMock 覆盖。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app

runner = CliRunner()

AGENT_MOD = "inkflow.cli.commands.agent_cmd"

PROJECT_ID = str(uuid.uuid4())
CHAPTER_ID = str(uuid.uuid4())
DRAFT_ID = "draft-0001"


def _draft_result(*extra_args):
    """agent draft 调用。"""
    return runner.invoke(app, ["agent", "draft", *extra_args])


@pytest.fixture
def fake_http_client():
    """Patch agent_cmd 内 ensure_kernel + InkFlowHTTPClient → fake client 实例。"""
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


def _http_err(status_code: int, detail: str, code: str | None = None):
    """惰性构造 HttpApiError。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _draft_dict(**overrides) -> dict:
    draft = {
        "id": DRAFT_ID,
        "project_id": PROJECT_ID,
        "chapter_id": CHAPTER_ID,
        "agent_run_id": "run-0001",
        "content": "草稿正文。",
        "status": "draft",
        "summary": "第一章草稿",
        "created_at": "2026-08-10T12:00:00",
        "confirmed_at": None,
    }
    draft.update(overrides)
    return draft


class TestAgentDraftHelp:
    """agent draft 子命令帮助（RED: 命令不存在 → exit 2 + No such command）。"""

    @staticmethod
    def _strip_ansi(text: str) -> str:
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    @pytest.mark.agent
    def test_draft_help(self):
        """agent draft --help 含 list/confirm/reject 子命令。"""
        result = runner.invoke(app, ["agent", "draft", "--help"])
        assert result.exit_code == 0
        assert "list" in self._strip_ansi(result.stdout)
        assert "confirm" in self._strip_ansi(result.stdout)
        assert "reject" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_draft_list_help(self):
        """agent draft list --help 含 --project-id/--status/--json。"""
        result = runner.invoke(app, ["agent", "draft", "list", "--help"])
        assert result.exit_code == 0
        assert "--project-id" in self._strip_ansi(result.stdout)
        assert "--status" in self._strip_ansi(result.stdout)
        assert "--json" in self._strip_ansi(result.stdout)

    @pytest.mark.agent
    def test_draft_confirm_help(self):
        """agent draft confirm --help 含 DRAFT_ID 位置参数与 --chapter-id/--json。"""
        result = runner.invoke(app, ["agent", "draft", "confirm", "--help"])
        assert result.exit_code == 0
        assert "--chapter-id" in self._strip_ansi(result.stdout)
        assert "--json" in self._strip_ansi(result.stdout)


class TestAgentDraftExecution:
    """agent draft list/confirm/reject 真实执行路径（HTTP mock 轨）。"""

    @pytest.mark.agent
    def test_draft_list_success(self, fake_http_client):
        """draft list 成功：GET /agent/drafts（params 正确）+ 人类摘要输出。"""
        fake_http_client.get.return_value = {
            "items": [_draft_dict(), _draft_dict(id="draft-0002", status="confirmed")],
            "total": 2,
        }
        result = _draft_result("list", "--project-id", PROJECT_ID)
        assert result.exit_code == 0
        call = fake_http_client.get.await_args
        assert call.args[0] == "/agent/drafts"
        assert call.kwargs["params"]["project_id"] == PROJECT_ID
        assert "共 2 条草稿" in result.stdout
        assert DRAFT_ID in result.stdout
        assert "confirmed" in result.stdout

    @pytest.mark.agent
    def test_draft_list_status_filter(self, fake_http_client):
        """draft list --status draft：status 参数透传。"""
        fake_http_client.get.return_value = {"items": [_draft_dict()], "total": 1}
        result = _draft_result("list", "--project-id", PROJECT_ID, "--status", "draft")
        assert result.exit_code == 0
        assert fake_http_client.get.await_args.kwargs["params"]["status"] == "draft"

    @pytest.mark.agent
    def test_draft_list_json(self, fake_http_client):
        """draft list --json：stdout 信封 == API 响应原样。"""
        payload = {"items": [_draft_dict()], "total": 1}
        fake_http_client.get.return_value = payload
        result = _draft_result("list", "--project-id", PROJECT_ID, "--json")
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"ok": True, "data": payload}

    @pytest.mark.agent
    def test_draft_confirm_success(self, fake_http_client):
        """draft confirm 成功：POST /agent/drafts/{id}/confirm → 「章节已更新」。"""
        fake_http_client.post.return_value = {
            "draft_id": DRAFT_ID,
            "status": "confirmed",
            "chapter_id": CHAPTER_ID,
        }
        result = _draft_result("confirm", DRAFT_ID)
        assert result.exit_code == 0
        call = fake_http_client.post.await_args
        assert call.args[0] == f"/agent/drafts/{DRAFT_ID}/confirm"
        assert "✅ 章节已更新" in result.stdout
        assert "status=final" in result.stdout

    @pytest.mark.agent
    def test_draft_confirm_with_chapter(self, fake_http_client):
        """draft confirm --chapter-id：body 含 chapter_id（草稿未绑定时指定）。"""
        fake_http_client.post.return_value = {
            "draft_id": DRAFT_ID,
            "status": "confirmed",
            "chapter_id": CHAPTER_ID,
        }
        result = _draft_result("confirm", DRAFT_ID, "--chapter-id", CHAPTER_ID)
        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert body["chapter_id"] == CHAPTER_ID

    @pytest.mark.agent
    def test_draft_confirm_conflict_409(self, fake_http_client):
        """draft confirm 409（重复确认/状态非 draft）→ stderr ❌ + 退出码 1。"""
        fake_http_client.post.side_effect = _http_err(409, "草稿已确认")
        result = _draft_result("confirm", DRAFT_ID)
        assert result.exit_code == 1
        assert "❌ 草稿已确认" in result.stderr

    @pytest.mark.agent
    def test_draft_reject_success(self, fake_http_client):
        """draft reject 成功：POST /agent/drafts/{id}/reject → 「草稿已拒绝」。"""
        fake_http_client.post.return_value = {
            "draft_id": DRAFT_ID,
            "status": "rejected",
        }
        result = _draft_result("reject", DRAFT_ID)
        assert result.exit_code == 0
        call = fake_http_client.post.await_args
        assert call.args[0] == f"/agent/drafts/{DRAFT_ID}/reject"
        assert "✅ 草稿已拒绝" in result.stdout

    @pytest.mark.agent
    def test_draft_confirm_404(self, fake_http_client):
        """draft confirm 404（草稿不存在）→ stderr ❌ + 退出码 1。"""
        fake_http_client.post.side_effect = _http_err(404, "草稿不存在")
        result = _draft_result("confirm", DRAFT_ID)
        assert result.exit_code == 1
        assert "❌ 草稿不存在" in result.stderr

    @pytest.mark.agent
    def test_draft_confirm_json(self, fake_http_client):
        """draft confirm --json：stdout 信封 == API 响应。"""
        payload = {
            "draft_id": DRAFT_ID,
            "status": "confirmed",
            "chapter_id": CHAPTER_ID,
        }
        fake_http_client.post.return_value = payload
        result = _draft_result("confirm", DRAFT_ID, "--json")
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"ok": True, "data": payload}
