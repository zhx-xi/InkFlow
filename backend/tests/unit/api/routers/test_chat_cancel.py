"""S3b C3 取消契约 — chat agent 流 断连→终态 + abort 幂等/新 run（#842/#719 补测）。

锚定 stream_chat_agent 路由层异常处理：客户端断连或用户 abort 时，run 必须离开
RUNNING 落到 TERMINATED/COMPLETED/FAILED 终态，绝不遗留 running（M3 门禁）。

「断连时正 await LLM 被 CancelledError」是本批核心缺口（genuine RED）：
- asyncio.CancelledError 继承 BaseException（Py3.8+），路由 `except Exception`
  不捕获 → CancelledError 从 async for 直接上抛 → `_end_run_terminated`
  （repo.save(TERMINATED)）不会执行 → run 停留在 RUNNING。这正是要抓的缺陷。
- 本文件用 mock svc.stream_events 在首个事件后【同步 raise CancelledError】模拟
  「await LLM 被取消」——确定性触发路由异常路径，无需真实 HTTP 断连（后者依赖
  ASGI transport/Starlette cancel 语义，非确定性；真实断连 smoke 由 e2e 覆盖）。

── GREEN 实现契约（Codex 必须满足）────────────────────────────────────
1. stream_chat_agent 的 _event_stream 必须捕获 asyncio.CancelledError：
   捕获后调用 _end_run_terminated(repo, svc, run, data)（落 TERMINATED 终态 +
   done 终帧回传 run_id），绝不裸抛、绝不遗留 running。README 注释标注 #842。
2. abort 端点（POST /api/v1/chat/agent/stream/{run_id}/abort）：
   - 命中注册表 → 200 {ok:true}，置位取消事件；重复 abort 幂等（再次 200）。
   - 未注册/已完成/不存在 → 404。
   - abort 后同 conversation 的新 run 独立注册、可正常 abort（前 run 的取消不污染）。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from httpx_sse import aconnect_sse

from inkflow.api.app import app
from inkflow.domain.models.agent_run import AgentRun, AgentRunStatus

PROMPT = "帮我整理一下主角的人物设定"
PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _ev(
    type_: str,
    delta: str = "",
    done: bool = False,
    error: str | None = None,
    id_: str | None = None,
    name: str | None = None,
    args: dict | None = None,
    result: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        type=type_,
        delta=delta,
        done=done,
        error=error,
        id=id_,
        name=name,
        args=args,
        result=result,
    )


def _make_run(run_id: str = "chat-run-0001") -> AgentRun:
    now = datetime.now(UTC)
    return AgentRun(
        id=run_id,
        project_id=uuid.UUID(PROJECT_ID),
        created_at=now,
        updated_at=now,
    )


def _make_repo() -> MagicMock:
    repo = MagicMock()
    repo.create = AsyncMock(return_value=_make_run())
    repo.save = AsyncMock(return_value=None)
    return repo


def _make_client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=httpx.Timeout(30.0),
    )


def _payload(prompt: str = PROMPT) -> dict:
    return {"project_id": PROJECT_ID, "prompt": prompt}


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


@pytest.fixture
def override_agent_stream():
    """override 两个依赖：get_chat_agent_service（mock svc）与 get_agent_run_repo（mock repo）。"""

    def _install(svc: MagicMock, repo: MagicMock):
        from inkflow.api.deps import get_agent_run_repo, get_chat_agent_service

        app.dependency_overrides[get_agent_run_repo] = lambda: repo
        app.dependency_overrides[get_chat_agent_service] = lambda: svc

    yield _install
    _clear_overrides()


class TestAgentStreamDisconnectTerminal:
    """断连/取消 → run 必达终态（不遗留 running）；CancelledError 不被 except Exception 吞掉。"""

    @pytest.mark.asyncio
    async def test_cancelled_error_leaves_run_terminated(
        self, override_agent_stream
    ) -> None:
        """await LLM 期间被取消（CancelledError）→ 落 TERMINATED 终态，绝不遗留 running。

        RED：当前路由 `except Exception` 不捕获 CancelledError → _end_run_terminated
        未执行 → repo.save(TERMINATED) 未调用 → 断言失败（run 停留 RUNNING）。
        """
        repo = _make_repo()
        svc = MagicMock()
        svc.consume_trace = MagicMock(return_value=([], "部分结果", 0))

        async def _gen(prompt, project_id=None, chapter_context=None, cancel_event=None):
            yield _ev("delta", delta="你")
            raise asyncio.CancelledError()  # 模拟 await LLM 被取消
            yield  # pragma: no cover

        svc.stream_events = _gen
        override_agent_stream(svc, repo)

        # 驱动端点：CancelledError 上抛到 ASGI 层（Starlette 可能中断/500），
        # 终态断言是核心契约，客户端侧异常容错。
        try:
            async with _make_client() as client, aconnect_sse(
                client, "POST", "/api/v1/chat/agent/stream", json=_payload()
            ) as sse:
                async for _ in sse.aiter_sse():
                    pass
        except Exception:
            pass

        # 核心断言：run 必须从 RUNNING 离开，落 TERMINATED（repo.save 被调用）
        assert repo.save.called, "取消后必须落终态（repo.save），当前实现遗留 running"
        saved = repo.save.call_args
        saved_run = saved.args[0] if saved.args else saved.kwargs.get("agent_run")
        assert saved_run is not None
        assert saved_run.status == AgentRunStatus.TERMINATED

    @pytest.mark.asyncio
    async def test_completed_run_saved_as_completed(self, override_agent_stream) -> None:
        """正常流完成 → repo.save(COMPLETED)（终态护栏：正常路径不遗留 running）。"""
        repo = _make_repo()
        svc = MagicMock()
        svc.consume_trace = MagicMock(return_value=([], "完整回答", 10))

        async def _gen(prompt, project_id=None, chapter_context=None, cancel_event=None):
            yield _ev("delta", delta="你")
            yield _ev("done", done=True)

        svc.stream_events = _gen
        override_agent_stream(svc, repo)

        async with _make_client() as client, aconnect_sse(
            client, "POST", "/api/v1/chat/agent/stream", json=_payload()
        ) as sse:
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]

        assert repo.save.called
        saved_run = repo.save.call_args.args[0]
        assert saved_run.status == AgentRunStatus.COMPLETED
        # 终帧回传 run_id（前端据此关联 run）
        assert frames[-1]["type"] == "done"
        assert frames[-1]["run_id"] == "chat-run-0001"


class TestAbortSemantics:
    """abort 端点语义：幂等 / 404 / abort 后同 conversation 新 run 正常。"""

    def _register(self, run_id: str):
        from inkflow.api.routers.chat_stream import (
            _inflight_runs,
            _register_inflight_run,
        )

        _inflight_runs.clear()
        _register_inflight_run(run_id, asyncio.Event())

    def _client(self) -> httpx.Client:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from inkflow.api.routers.chat_stream import router

        a = FastAPI()
        a.include_router(router)
        return TestClient(a)

    def test_abort_then_abort_again_is_idempotent(self) -> None:
        """同一 run 连续 abort 两次：首次 200，二次仍 200（幂等，不因已 abort 而 404）。"""
        self._register("run-abc")
        client = self._client()
        first = client.post("/api/v1/chat/agent/stream/run-abc/abort")
        second = client.post("/api/v1/chat/agent/stream/run-abc/abort")
        assert first.status_code == 200
        assert first.json()["ok"] is True
        assert second.status_code == 200
        assert second.json()["ok"] is True
        from inkflow.api.routers.chat_stream import _inflight_runs

        _inflight_runs.clear()

    def test_abort_non_existent_run_404(self) -> None:
        """未注册 run_id → 404（无此运行中 run）。"""
        _resp = self._client().post("/api/v1/chat/agent/stream/no-such-run/abort")
        assert _resp.status_code == 404

    def test_abort_then_new_run_same_conversation_works(self) -> None:
        """abort 后同 conversation 新 run：独立注册、可正常 abort（不被前 run 取消污染）。"""
        from inkflow.api.routers.chat_stream import (
            _inflight_runs,
            _register_inflight_run,
        )

        _inflight_runs.clear()
        ev_old = asyncio.Event()
        ev_new = asyncio.Event()
        _register_inflight_run("old-run", ev_old)
        client = self._client()
        # abort 旧 run
        assert client.post("/api/v1/chat/agent/stream/old-run/abort").status_code == 200
        assert ev_old.is_set()
        # 新 run 注册（同 conversation）
        _register_inflight_run("new-run", ev_new)
        assert ev_new.is_set() is False
        assert client.post("/api/v1/chat/agent/stream/new-run/abort").status_code == 200
        assert ev_new.is_set()
        _inflight_runs.clear()
