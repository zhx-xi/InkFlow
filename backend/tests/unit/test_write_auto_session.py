"""RED 契约（#462）：plan auto 的 write_auto 委托必须使用独立 session。

缺陷背景（0.10.0-rc3 实证 2026-08-18）：books.py `_write_auto`（#460 引入）
闭包捕获请求 session `db`，函数体内 `from inkflow.api.routers.agent import _svc`
后 `_svc(db).execute(...)` 执行 F42 长任务管线——请求响应后 FastAPI 的
get_session 退出触发 session.close()，而 execute 仍在同一 session 上做
_connection_for_bind → SQLAlchemy InvalidRequestError / IllegalStateChangeError。
实测：`book plan auto`（respond auto=true）500。

本契约：断言 write_auto 委托在独立 session（async_session_factory 新建）上
执行管线，不捕获请求 db。

patch 目标（源头模块，镜像 test_http_client.py §7 模式）：
- `inkflow.core.database.async_session_factory`（write_auto 应经它建独立 session）
- `inkflow.api.routers.agent._svc`（当前实现函数体内 import 的装配入口）

⚠️ RED 期形态：当前实现不调 async_session_factory（捕获请求 db）→ 断言 FAIL。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inkflow.api.routers import books

AGENT_MOD = "inkflow.api.routers.agent._svc"
DB_MOD = "inkflow.core.database.async_session_factory"


@pytest.fixture
def fake_db():
    """假请求 session（get_planner_service(db) 的 db 参数）。"""
    return MagicMock()


def _patch_deps():
    """patch 源头模块：async_session_factory + agent._svc。

    返回 (patcher_factory, patcher_svc, mock_factory, mock_svc, mock_agent, mock_session)；
    mock_factory 产出的独立 session 记入 mock_factory.return_value.__aenter__.return_value。
    """
    patcher_factory = patch(DB_MOD)
    mock_factory = patcher_factory.start()
    mock_session = AsyncMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    patcher_svc = patch(AGENT_MOD)
    mock_svc = patcher_svc.start()
    mock_agent = AsyncMock()
    mock_agent.execute = AsyncMock(return_value=None)
    mock_svc.return_value = mock_agent

    return patcher_factory, patcher_svc, mock_factory, mock_svc, mock_agent, mock_session


def test_write_auto_uses_independent_session(fake_db):
    """write_auto 必须经 async_session_factory 独立 session（不捕获请求 db）。"""
    (pf, ps, mock_factory, _mock_svc, mock_agent, _) = _patch_deps()
    try:
        svc = books.get_planner_service(db=fake_db)
        asyncio.run(svc._write_auto("00000000-0000-0000-0000-000000000001", "一句话"))
        assert (
            mock_factory.called
        ), "write_auto 未使用 async_session_factory 独立 session（#462 根因）"
        assert mock_agent.execute.await_count == 1, "execute 应被调用一次"
    finally:
        pf.stop()
        ps.stop()


def test_write_auto_not_using_request_db(fake_db):
    """write_auto 不得把请求 db 传给 _svc（请求 session 不复用执行长任务）。"""
    (pf, ps, _, mock_svc, _, mock_session) = _patch_deps()
    try:
        svc = books.get_planner_service(db=fake_db)
        asyncio.run(svc._write_auto("00000000-0000-0000-0000-000000000001", "一句话"))
        # _svc 调用参数必须是独立 session（mock_session），不能是 fake_db
        if mock_svc.call_args is not None:
            args = mock_svc.call_args.args
            passed_db = args[0] if args else None
            assert passed_db is not fake_db, "write_auto 复用请求 db 执行长任务（#462 根因）"
            assert (
                passed_db is mock_session
            ), "write_auto 未传独立 session（async_session_factory 产物）"
    finally:
        pf.stop()
        ps.stop()
