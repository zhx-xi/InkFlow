"""#719 chat 运行时中断：后端 abort 端点 + in-flight run 取消契约（D5=A）。

决策 D5=A：新增后端 abort 端点（取消 agent run），非仅前端隐藏。run 的 in-flight
状态由 chat_stream.py 模块级注册表承载（run_id -> asyncio.Event cancel token），
abort 端点置位事件 → 流式 gen 检查后 break → 产终止帧。

RED：chat_stream.py 尚无 `_register_inflight_run` / `abort_chat_run` /
`_inflight_runs` 注册表，也不含 `POST /agent/stream/{run_id}/abort` 路由 →
本文件全部用例 FAILED（ImportError 或 404/断言失败），符合 M1 门禁。
"""
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkflow.api.routers.chat_stream import router


def _get_abort_api():
    """用例体惰性取注册表契约——RED 期函数不存在 → ImportError（FAILED 非收集 ERROR）。"""
    from inkflow.api.routers.chat_stream import (
        _inflight_runs,
        _register_inflight_run,
        abort_chat_run,
    )

    return _register_inflight_run, abort_chat_run, _inflight_runs


def _make_client() -> TestClient:
    """独立 app 挂载 chat router，避免整 app 启动（镜像 router 级测试）。"""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestAbortChatRunRegistry:
    """操作 in-flight run 取消事件注册表（核心 D5=A 逻辑）。"""

    def test_abort_chat_run_sets_cancel_event(self) -> None:
        """abort_chat_run(run_id) 命中注册表 → 置 cancel event → 返回 True。"""
        _register, abort_run, inflight = _get_abort_api()
        ev = asyncio.Event()
        _register("run-1", ev)
        assert abort_run("run-1") is True
        assert ev.is_set()
        inflight.pop("run-1", None)

    def test_abort_unknown_run_returns_false(self) -> None:
        """未注册 run_id → abort_chat_run 返回 False（不抛异常）。"""
        _register, abort_run, _ = _get_abort_api()
        assert abort_run("no-such-run") is False


class TestAbortEndpoint:
    """HTTP 层：`POST /api/v1/chat/agent/stream/<run_id>/abort`。"""

    def test_abort_route_registered_in_openapi(self) -> None:
        """路由已在 chat router 注册（路径模板 /api/v1/chat/agent/stream/{run_id}/abort）。"""
        app = FastAPI()
        app.include_router(router)
        paths = app.openapi()["paths"]
        assert "/api/v1/chat/agent/stream/{run_id}/abort" in paths

    def test_abort_inflight_run_returns_200(self) -> None:
        """in-flight 注册后 abort → 200 {ok:true} 且 cancel event 置位。"""
        _register, _, inflight = _get_abort_api()
        ev = asyncio.Event()
        _register("run-9", ev)
        resp = _make_client().post("/api/v1/chat/agent/stream/run-9/abort")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert ev.is_set()
        inflight.pop("run-9", None)

    def test_abort_unknown_run_returns_404(self) -> None:
        """未注册 run_id → abort 端点 404。"""
        resp = _make_client().post("/api/v1/chat/agent/stream/no-such-run/abort")
        assert resp.status_code == 404
