"""F27 M5 CLI RED 契约测试 — write next --mode agentic（agentic 生成 + 草稿确认指引，spec §4.1）.

测试范围：inkflow write next --mode agentic 真实执行路径（HTTP mock 轨）。

需 pytest marker: @pytest.mark.agent

══════════════════════════════════════════════════════════════════════════
HTTP 契约（实现者以本文件为准）:
- --mode agentic → POST /writing/agentic/generate（非流式，一次返回 run dict）
  body: {"project_id": "<UUID str>", "chapter_id": "<UUID str>", "outline": "...",
         "context": "...", "min_words": 2000, "style_hint": "..."|null,
         "max_steps": 12|null, "token_budget": 32000|null}（None 字段剔除——exclude_none）
  → 200: {"run_id": "<id>", "status": "completed", "draft_id": "<id>",
          "final_content": "...", "word_count": N,
          "steps": [{"index", "message_content", "tool_calls", "tokens"}],
          "token_usage_total": N, "terminated_by": "llm"}
  guardrail 终止同样 200（status="terminated_by_guardrail"）——非 HTTP 错误（ADR-D）
- --mode deterministic（默认）→ 既有流式路径 /writing/stream（零改动）
- 错误 = HttpApiError(status_code, detail[, code])：404（项目/章节不存在）→
  「❌ {detail}」stderr + 退出码 1
══════════════════════════════════════════════════════════════════════════

人类模式输出（父侧定稿，实现按此）:
- agentic 成功: 「✅ 草稿已保存 ({draft_id})，确认命令: inkflow agent draft confirm {draft_id}」
  + 轨迹摘要「步骤: {N} · 工具: [a → b] · tokens: {N} · 终止: {terminated_by}」
- guardrail 终止: 「⚠️ 护栏终止 ({terminated_by})，产物已保留」+ 轨迹摘要（退出码 0）
- --json: print_result 信封 {"ok": true, "data": <API 响应原样>}

RED 预期
--------
write next 现有签名无 --mode → typer exit 2（Unexpected argument）或未知选项报错；
help 断言（--mode 存在）FAIL；agentic 路径测试的 patch setup 抛 AttributeError
（write 模块无 agentic 调用所需属性——预期 RED）。

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

WRITE_MOD = "inkflow.cli.commands.write"

PROJECT_ID = str(uuid.uuid4())
CHAPTER_ID = str(uuid.uuid4())
DRAFT_ID = "draft-0001"
RUN_ID = "run-0001"


def _next_result(*extra_args):
    """write next --mode agentic 调用。"""
    return runner.invoke(
        app,
        [
            "write",
            "next",
            "--project-id",
            PROJECT_ID,
            "--chapter-id",
            CHAPTER_ID,
            "--outline",
            "本章大纲",
            *extra_args,
        ],
    )


@pytest.fixture
def fake_http_client():
    """Patch write 内 ensure_kernel + InkFlowHTTPClient → fake client 实例。"""
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(f"{WRITE_MOD}.ensure_kernel", AsyncMock(return_value=fake_handle)),
        patch(f"{WRITE_MOD}.InkFlowHTTPClient", autospec=True) as mock_cls,
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


def _agentic_run(**overrides) -> dict:
    run = {
        "run_id": RUN_ID,
        "status": "completed",
        "draft_id": DRAFT_ID,
        "final_content": "这是 agentic 生成的正文。",
        "word_count": 12,
        "steps": [
            {
                "index": 0,
                "message_content": "",
                "tool_calls": [
                    {
                        "step_index": 0,
                        "tool_name": "search_characters",
                        "arguments": {"project_id": PROJECT_ID},
                        "result": '{"ok": true, "data": []}',
                        "is_error": False,
                    }
                ],
                "tokens": 120,
            },
            {
                "index": 1,
                "message_content": "这是 agentic 生成的正文。",
                "tool_calls": [],
                "tokens": 300,
            },
        ],
        "token_usage_total": 420,
        "terminated_by": "llm",
    }
    run.update(overrides)
    return run


class TestWriteNextAgenticHelp:
    """write next --mode 帮助（RED: 现有签名无 --mode → exit 2 或 FAIL）。"""

    @staticmethod
    def _strip_ansi(text: str) -> str:
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    @pytest.mark.agent
    def test_next_help_has_mode(self):
        """write next --help 含 --mode 选项（deterministic|agentic）。"""
        result = runner.invoke(app, ["write", "next", "--help"])
        assert result.exit_code == 0
        assert "--mode" in self._strip_ansi(result.stdout)
        assert "agentic" in self._strip_ansi(result.stdout)


class TestWriteNextAgenticExecution:
    """write next --mode agentic 真实执行路径（HTTP mock 轨）。"""

    @pytest.mark.agent
    def test_agentic_success_human(self, fake_http_client):
        """agentic 成功：POST /writing/agentic/generate + 草稿确认指引 + 轨迹摘要。"""
        fake_http_client.post.return_value = _agentic_run()
        result = _next_result("--mode", "agentic")
        assert result.exit_code == 0
        call = fake_http_client.post.await_args
        assert call.args[0] == "/writing/agentic/generate"
        body = call.kwargs["json"]
        assert body["project_id"] == PROJECT_ID
        assert body["chapter_id"] == CHAPTER_ID
        assert body["outline"] == "本章大纲"
        assert body["min_words"] == 2000
        # 草稿确认指引（spec §4.1）
        assert f"✅ 草稿已保存 ({DRAFT_ID})" in result.stdout
        assert f"inkflow agent draft confirm {DRAFT_ID}" in result.stdout
        # 决策轨迹摘要
        assert "步骤: 2" in result.stdout
        assert "search_characters" in result.stdout
        assert "tokens: 420" in result.stdout
        assert "终止: llm" in result.stdout

    @pytest.mark.agent
    def test_agentic_json(self, fake_http_client):
        """agentic --json：stdout 信封 == API 响应（含 steps 决策轨迹）。"""
        payload = _agentic_run()
        fake_http_client.post.return_value = payload
        result = _next_result("--mode", "agentic", "--json")
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["ok"] is True
        data = parsed["data"]
        assert data["run_id"] == RUN_ID
        assert data["draft_id"] == DRAFT_ID
        assert len(data["steps"]) == 2

    @pytest.mark.agent
    def test_agentic_guardrail_not_error(self, fake_http_client):
        """guardrail 终止（max_steps 超限）：200 + status=terminated_by_guardrail，退出码 0。"""
        fake_http_client.post.return_value = _agentic_run(
            status="terminated_by_guardrail", terminated_by="max_steps", draft_id=None
        )
        result = _next_result("--mode", "agentic")
        assert result.exit_code == 0
        assert "⚠️ 护栏终止 (max_steps)" in result.stdout

    @pytest.mark.agent
    def test_agentic_completed_without_draft_id(self, fake_http_client):
        """completed 无 draft_id → 「未生成草稿」提示（覆盖 write.py:118）。"""
        fake_http_client.post.return_value = _agentic_run(draft_id=None)
        result = _next_result("--mode", "agentic")
        assert result.exit_code == 0
        assert "⚠️ 未生成草稿" in result.stdout

    @pytest.mark.agent
    def test_agentic_404(self, fake_http_client):
        """agentic 404（项目/章节不存在）→ stderr ❌ + 退出码 1。"""
        fake_http_client.post.side_effect = _http_err(404, "章节不存在")
        result = _next_result("--mode", "agentic")
        assert result.exit_code == 1
        assert "❌ 章节不存在" in result.stderr

    @pytest.mark.agent
    def test_agentic_invalid_mode_exit_2(self, fake_http_client):
        """--mode foo（非法枚举）→ 参数错误退出码 2 + typer 枚举校验消息。

        RED 阶段（无 --mode 参数）：stderr 为「No such option: --mode」不含
        "Invalid value" → 本断言 FAIL（区分未知选项与非法枚举）；GREEN 后
        typer 枚举校验消息含 "Invalid value" → PASS。
        """
        result = _next_result("--mode", "foo")
        assert result.exit_code == 2
        assert "Invalid value" in result.stderr


class TestWriteNextAgenticTimeout:
    """#274 契约：agentic 调用点必须传长 timeout（300s），其余端点默认。

    背景：rc9 实测 agentic 多步 ReAct 循环（LLM 多次调用 + 工具调用）耗时 44s+，
    远超 InkFlowHTTPClient 默认 30s → ReadTimeout 必失败；服务端实际生成成功。
    修复 = agentic 端点 per-request timeout 覆盖：post 传 timeout=300.0。

    RED 预期：当前 write.py agentic 分支调用 `client.post(path, json=body)`
    不带 timeout → `call.kwargs.get("timeout") is None` → 本断言 FAILED；
    GREEN 后 agentic 分支传 timeout=300.0 → PASS。
    """

    @pytest.mark.agent
    def test_agentic_post_uses_long_timeout(self, fake_http_client):
        """POST /writing/agentic/generate 带 timeout=300.0（长任务端点专用）。"""
        fake_http_client.post.return_value = _agentic_run()
        result = _next_result("--mode", "agentic")
        assert result.exit_code == 0
        call = fake_http_client.post.await_args
        assert call.args[0] == "/writing/agentic/generate"
        assert call.kwargs.get("timeout") == 300.0
