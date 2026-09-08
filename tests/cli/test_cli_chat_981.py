"""#981 RED 契约测试 — 全新 inkflow chat 一次性命令（SSE 消费 + AgentRun 回读）.

契约来源：.hermes/plans/red-981-c-chat.md（父侧已定稿）。实现者以此文件为准。

◤ SSE dict 帧表（只读基准 backend/src/inkflow/api/routers/chat_stream.py L100-160）◥
  - run_started: {"type": "run_started", "id": <run_id>, "done": false}
  - delta:       {"type": "delta", "delta": <str>, "done": false}
  - tool_call:   {"type": "tool_call", "id"/"name"/"args", "done": false}
  - tool_result: {"type": "tool_result", "id"/"name"/"result", "done": false}
  - interrupt:   {"type": "interrupt", "payload", "done": false}
  - done:        {"type": "done", "done": true, "run_id": <id>}
  - error:       {"type": "error", "error": <msg>, "done": true}
plain 端点 legacy 帧（无 type 键，chat_stream.py:92-99）：{"delta"/"done"}。

◤ 待测契约要点 ◥
1. 端点：--agent → client.stream_sse("/chat/agent/stream")；--plain →
   client.stream_sse("/chat/stream")。body 基础 {"project_id": <str>, "prompt": <str>}，
   条件键：--chapter → chapter_id；--conversation → conversation_id（缺省不含该两键）。
2. --json 数据源 = AgentRun 回读（#615）：done 帧后 client.get(f"/agent/runs/{run_id}") →
   run dict；信封 {"ok": true, "data": {"run_id", "steps", "tool_calls"(=展平
   run.steps[*].tool_calls), "final_content", "token_usage_total"}}。
3. 回读失败（HttpApiError，如 404）→ 降级：data 各字段从 SSE 帧现场收集兜底
   （steps=[], tool_calls=[], final_content=delta 拼接, run_id 来自 done 帧），
   信封仍 ok=true；**不做 SSE 帧重复解析**。
4. plain --json：{"ok": true, "data": {"content": <delta 拼接>}}，不查 run。
5. --json 由命令自带本地 --json 选项驱动（镜像 write next / agent_cmd，
   json_output: bool = typer.Option(False, "--json", ...)）——避免位置参后
   触发根 callback 全局 --json 的 #865 误置告警（app.py _leaf_declares_json）。
6. 帧 error → exit 1 + LLM_ERROR 信封/❌ <msg> stderr；空 prompt --json →
   VALIDATION_ERROR exit 1 且不发 HTTP；超时 HttpApiError(code="TIMEOUT") → error.code TIMEOUT。

◤ RED 形态说明（采用惰性/逐条 ERROR 形态）◥
inkflow.cli.commands.chat_cmd 模块尚不存在 → 不顶部 import（避免 isort 把无法解析为
first-party 的缺失模块误判为 third-party 触发 I001）。RED 触发点 = fixture 对
chat_cmd 命名空间的 patch（ensure_kernel + InkFlowHTTPClient）→ 收集通过（app
可导入），但每个用到 fake_http_client 的用例在 fixture setup 抛
AttributeError: module 'inkflow.cli.commands' has no attribute 'chat_cmd'
（逐条 ERROR）；
用例10 注册守护独立地 FAIL（"chat" not in app.registered_commands）。两种形态任务书均接受。
Top-level 仅 from inkflow.cli.app，ruff I001 在 RED→GREEN 全程稳定。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.app import app

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000777")

# 契约默认超时（任务书：--timeout 默认 = LLM_TASK_TIMEOUT 300.0）
_DEFAULT_TIMEOUT = 300.0

# AgentRun 回读样本（#615 GET /agent/runs/{run_id} → run dict）
_RUN_DICT = {
    "id": "R1",
    "status": "completed",
    "steps": [
        {
            "id": "s1",
            "type": "tool",
            "tool_calls": [
                {"id": "tc1", "name": "search_knowledge", "args": {}},
            ],
        },
        {
            "id": "s2",
            "type": "tool",
            "tool_calls": [
                {"id": "tc2", "name": "read_chapter", "args": {}},
            ],
        },
    ],
    "final_content": "回读的最终内容",
    "token_usage_total": 42,
}


def _sse(frames: list[dict]):
    """构造 stream_sse 的 side_effect：调用返回 async generator，逐帧 yield dict.

    与 test_cli_write.py L61-116 权威形态一致——MagicMock(side_effect=<factory>)：
    调用即返回 async generator（与真实 client.stream_sse 行为一致），同时保留调用
    记录供 call_args / assert_called_once_with 断言 path/body。帧列表参数化 helper。
    """
    def _factory(*args, **kwargs):
        async def _gen():
            for frame in frames:
                yield frame
        return _gen()
    return _factory


def _http_err(status_code: int, detail: str, code: str | None = None):
    """惰性构造 HttpApiError（infrastructure.http GREEN 阶段才存在，禁顶部 import）。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


@pytest.fixture
def cli_runner(monkeypatch):
    # CI 彩色环境（GITHUB_ACTIONS/FORCE_COLOR）下 Typer 0.27 会把 FORCE_TERMINAL
    # 固定为 True，help 渲染强制带样式使文本断言脆弱；禁用强制终端渲染 + NO_COLOR。
    monkeypatch.setattr("typer.rich_utils.FORCE_TERMINAL", False)
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def fake_http_client():
    """patch chat_cmd 命名空间 ensure_kernel + InkFlowHTTPClient → fake client 实例.

    与 test_cli_write.py fixture 同构：stream_sse = MagicMock(side_effect=<factory>)
    （调用返回 async gen 且保留调用记录）；get = AsyncMock(return_value=_RUN_DICT)；
    __aenter__ 返回自身。每个用例可通过
    `fake_http_client.stream_sse = MagicMock(side_effect=_sse(frames))` 覆盖帧序列。
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
            "inkflow.cli.commands.chat_cmd.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.chat_cmd.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.get.return_value = _RUN_DICT
        mock_instance.stream_sse = MagicMock(side_effect=_sse([]))
        mock_cls.return_value = mock_instance
        yield mock_instance


class TestChat981:
    def test_agent_json_success(self, cli_runner, fake_http_client):
        """用例1：agent 成功 --json，经 AgentRun 回读填充信封 data。

        帧：run_started + delta×2 + tool_call + tool_result + done(run_id=R1)；
        get 回读 → data.run_id==R1、final_content==回读值、steps 原样、
        tool_calls 展平计数；stream_sse path==/chat/agent/stream、body 断言。
        """
        pid = uuid.uuid4()
        fake_http_client.stream_sse = MagicMock(side_effect=_sse([
            {"type": "run_started", "id": "R1", "done": False},
            {"type": "delta", "delta": "你好", "done": False},
            {"type": "delta", "delta": "世界", "done": False},
            {"type": "tool_call", "id": "tc1", "name": "search_knowledge",
             "args": {}, "done": False},
            {"type": "tool_result", "id": "tc1", "name": "search_knowledge",
             "result": "...", "done": False},
            {"type": "done", "done": True, "run_id": "R1"},
        ]))
        result = cli_runner.invoke(
            app,
            ["chat", "你好", "--project", str(pid), "--json"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        data = payload["data"]
        assert data["run_id"] == "R1"
        assert data["final_content"] == _RUN_DICT["final_content"]
        assert data["steps"] == _RUN_DICT["steps"]
        # tool_calls 展平 = 各 step.tool_calls 列表串接（元素原样 dict）
        assert len(data["tool_calls"]) == 2
        assert data["tool_calls"][0]["name"] == "search_knowledge"
        assert data["tool_calls"][1]["name"] == "read_chapter"
        assert data["token_usage_total"] == 42
        # 端点与 body 契约
        call = fake_http_client.stream_sse.call_args
        assert call.args[0] == "/chat/agent/stream"
        assert call.kwargs["json"] == {"project_id": str(pid), "prompt": "你好"}

    def test_agent_human_delta(self, cli_runner, fake_http_client):
        """用例2：agent 成功人类模式——exit 0，stdout 含 delta 拼接（nl=False 连续）。"""
        pid = uuid.uuid4()
        fake_http_client.stream_sse = MagicMock(side_effect=_sse([
            {"type": "run_started", "id": "R1", "done": False},
            {"type": "delta", "delta": "清晨", "done": False},
            {"type": "delta", "delta": "薄雾", "done": False},
            {"type": "done", "done": True, "run_id": "R1"},
        ]))
        result = cli_runner.invoke(
            app,
            ["chat", "你好", "--project", str(pid)],
        )
        assert result.exit_code == 0
        assert "清晨薄雾" in result.stdout

    def test_plain_json(self, cli_runner, fake_http_client):
        """用例3：plain 成功 --json——path==/chat/stream（legacy 无 type 键）、
        data.content==delta 拼接、get 未被调（不查 run）。"""
        pid = uuid.uuid4()
        fake_http_client.stream_sse = MagicMock(side_effect=_sse([
            {"delta": "你", "done": False},
            {"delta": "好", "done": False},
            {"done": True},
        ]))
        result = cli_runner.invoke(
            app,
            ["chat", "你好", "--project", str(pid), "--plain", "--json"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["content"] == "你好"
        fake_http_client.get.assert_not_awaited()
        call = fake_http_client.stream_sse.call_args
        assert call.args[0] == "/chat/stream"
        assert call.kwargs["json"] == {"project_id": str(pid), "prompt": "你好"}

    def test_frame_error_json(self, cli_runner, fake_http_client):
        """用例4a：帧 error --json 信封 → exit 1 + code==LLM_ERROR。"""
        pid = uuid.uuid4()
        fake_http_client.stream_sse = MagicMock(side_effect=_sse([
            {"type": "run_started", "id": "R1", "done": False},
            {"type": "delta", "delta": "半句", "done": False},
            {"type": "error", "error": "内部错误", "done": True},
        ]))
        result = cli_runner.invoke(
            app,
            ["chat", "你好", "--project", str(pid), "--json"],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "LLM_ERROR"

    def test_frame_error_human(self, cli_runner, fake_http_client):
        """用例4b：帧 error 人类模式 → exit 1，stderr 含错误消息。"""
        pid = uuid.uuid4()
        fake_http_client.stream_sse = MagicMock(side_effect=_sse([
            {"type": "run_started", "id": "R1", "done": False},
            {"type": "error", "error": "内部错误", "done": True},
        ]))
        result = cli_runner.invoke(
            app,
            ["chat", "你好", "--project", str(pid)],
        )
        assert result.exit_code == 1
        assert "内部错误" in result.stderr

    def test_conditional_keys(self, cli_runner, fake_http_client):
        """用例5：--chapter/--conversation 条件键——传含、不传不含。"""
        pid = uuid.uuid4()
        cid = uuid.uuid4()
        conv = uuid.uuid4()
        fake_http_client.stream_sse = MagicMock(side_effect=_sse([
            {"type": "run_started", "id": "R1", "done": False},
            {"type": "done", "done": True, "run_id": "R1"},
        ]))
        cli_runner.invoke(
            app,
            ["chat", "你好", "--project", str(pid),
             "--chapter", str(cid), "--conversation", str(conv)],
        )
        body = fake_http_client.stream_sse.call_args.kwargs["json"]
        assert body["chapter_id"] == str(cid)
        assert body["conversation_id"] == str(conv)
        # 缺省：不含该两键
        fake_http_client.stream_sse = MagicMock(side_effect=_sse([
            {"type": "run_started", "id": "R1", "done": False},
            {"type": "done", "done": True, "run_id": "R1"},
        ]))
        cli_runner.invoke(app, ["chat", "你好", "--project", str(pid)])
        body2 = fake_http_client.stream_sse.call_args.kwargs["json"]
        assert "chapter_id" not in body2
        assert "conversation_id" not in body2

    def test_empty_prompt_json(self, cli_runner, fake_http_client):
        """用例6：空/纯空白 prompt --json → VALIDATION_ERROR exit 1，且不发 HTTP。"""
        pid = uuid.uuid4()
        result = cli_runner.invoke(
            app,
            ["chat", "   ", "--project", str(pid), "--json"],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.stream_sse.assert_not_called()

    def test_timeout_kwarg(self, cli_runner, fake_http_client):
        """用例7：--timeout 5 → stream_sse 调用 kwargs["timeout"] == 5.0。"""
        pid = uuid.uuid4()
        fake_http_client.stream_sse = MagicMock(side_effect=_sse([
            {"type": "run_started", "id": "R1", "done": False},
            {"type": "done", "done": True, "run_id": "R1"},
        ]))
        cli_runner.invoke(
            app,
            ["chat", "你好", "--project", str(pid), "--timeout", "5"],
        )
        call = fake_http_client.stream_sse.call_args
        assert call.kwargs["timeout"] == 5.0

    def test_transport_timeout(self, cli_runner, fake_http_client):
        """用例8：传输层超时（#926）→ --json error.code==TIMEOUT；人类 stderr 含 超时。"""
        pid = uuid.uuid4()
        fake_http_client.stream_sse = MagicMock(
            side_effect=_http_err(0, "请求超时 (5s)", "TIMEOUT")
        )
        result = cli_runner.invoke(
            app,
            ["chat", "你好", "--project", str(pid), "--json"],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "TIMEOUT"
        # 人类模式：exit 1 + stderr 含 超时
        fake_http_client.stream_sse = MagicMock(
            side_effect=_http_err(0, "请求超时 (5s)", "TIMEOUT")
        )
        result2 = cli_runner.invoke(app, ["chat", "你好", "--project", str(pid)])
        assert result2.exit_code == 1
        assert "超时" in result2.stderr

    def test_readback_404_fallback(self, cli_runner, fake_http_client):
        """用例9：回读 404 降级——get 抛 HttpApiError(404) → 信封仍 ok=true，
        run_id 来自 done 帧、final_content==delta 拼接、steps/tool_calls 空。"""
        pid = uuid.uuid4()
        fake_http_client.stream_sse = MagicMock(side_effect=_sse([
            {"type": "run_started", "id": "R2", "done": False},
            {"type": "delta", "delta": "兜底", "done": False},
            {"type": "done", "done": True, "run_id": "R2"},
        ]))
        fake_http_client.get.side_effect = _http_err(404, "not found", "NOT_FOUND")
        result = cli_runner.invoke(
            app,
            ["chat", "你好", "--project", str(pid), "--json"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        data = payload["data"]
        assert data["run_id"] == "R2"
        assert data["final_content"] == "兜底"
        assert data["steps"] == []
        assert data["tool_calls"] == []

    def test_registered_in_app(self):
        """用例10：注册守护——根 app 已注册 "chat" 单命令（镜像 search 压平形态）。"""
        cmd_names = [getattr(c, "name", None) for c in app.registered_commands]
        assert "chat" in cmd_names
