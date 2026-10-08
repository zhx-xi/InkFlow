"""#1539 RED 契约 —— 搜索 / 索引重建的会话未归还（#1530 同缺陷类收口）。

现象（0.17.0-rc1 内核日志）::

    ERROR | logging:handle: The garbage collector is trying to clean up
    non-checked-in connection <AdaptedConnection <aiosqlite.core.Connection ...>>

两处同机制根因（本文件锁定的契约）：

① `api/routers/search.py::_get_svc` —— **每个搜索请求**裸建
   `async_session_factory()` 会话，**从无 `close()`**；请求结束被回收时连接未归还。
   修复 = 改用端点 `Depends(get_db)` 的**请求 session**（由 `get_db` 统一归还）。

② `api/deps.py::get_index_rebuild_service` —— 建**模块级单例** session 并随进程
   存活期持有；索引重建后台任务（`index_rebuild_service.py::_run`）在该单例
   session 上执行、**从不归还** → 首次重建后长期扣住 1 条连接。
   修复 = 后台任务**自持 session**（`async with async_session_factory()`），
   模块单例**只保留服务对象、不持有 session**（对照 #1530 范式）。

判据（根因断言，**非**「日志里没告警」）：连接池 `checkedout()` 不得随搜索次数
单调上升；触发一次重建并等其完成后必须**回到基线**。文件型 SQLite → `QueuePool`
→ 暴露 `checkedout()` 计数。

  - 修复前：① 每请求 +1（不归还）；② 单例 +1 常驻 → 本文件 FAIL（RED 证据）
  - 修复后：两者均回到基线

⚠️ 修复前 `search._get_svc` 经模块级 `async_session_factory` 自建会话——本文件把该
符号 patch 到测试引擎（`raising=False`）以便把泄漏**落在被观测的池**上；修复后该符号
不再是泄漏路径，patch 成 no-op（断言仍成立：请求 session 被 `get_db` 归还）。

依据: issue #1539（0.17.0 · rc1 修复批 W8b 轨 4）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from inkflow.api.app import app
from inkflow.api.deps import get_db
from inkflow.core.database import Base
from inkflow.domain.models.search import SearchQuery, SearchResponse
from inkflow.infrastructure.database.models.project import ProjectORM

BASE_URL = "http://test1539"


@pytest_asyncio.fixture
async def db_engine(tmp_path) -> AsyncGenerator[AsyncEngine]:
    """文件型 SQLite（QueuePool → 暴露 `checkedout()` 计数）+ 建全表。"""
    db_file = tmp_path / "session-release-1539.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def real_get_db(db_engine: AsyncEngine):
    """`get_db` override = **真实请求级生命周期**（`async with factory()`）。

    与 `tests/api/conftest.override_get_db`（`yield <共享 session>`，永不 close）不同：
    逐请求新建并用上下文管理器归还连接，复刻生产 `get_db` 语义 —— 唯有如此才能观测
    「请求结束后连接是否被泄漏」。
    """
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override() -> AsyncGenerator[object]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    yield factory
    app.dependency_overrides.pop(get_db, None)


class _FakeSearchService:
    """最小 SearchService 替身：只**触库**（checkout 连接）以暴露会话是否被归还。"""

    def __init__(self, session: object) -> None:
        self._session = session

    async def search(self, query: SearchQuery) -> SearchResponse:
        await self._session.execute(text("SELECT 1"))  # type: ignore[attr-defined]  # 触发 checkout
        return SearchResponse(
            total=0,
            hits=[],
            query=query.q,
            types=query.types,
            mode=query.mode,
            project_ids=query.project_ids,
        )

    async def rebuild(self, project_ids: object = None) -> dict:
        await self._session.execute(text("SELECT 1"))  # type: ignore[attr-defined]  # 触发 checkout
        return {"rebuilt_at": "", "project_ids": None}


async def _fake_get_search_service(db: object) -> _FakeSearchService:
    return _FakeSearchService(db)


def _search_patches(monkeypatch, factory) -> None:
    """patch 搜索链装配：装配替身 + 修复前的自建会话路径落到测试引擎。"""
    from inkflow.api.routers import search as search_router

    monkeypatch.setattr(search_router, "get_search_service", _fake_get_search_service)
    # 修复前 `_get_svc` 走模块级 async_session_factory（自建会话、从不 close）；
    # 修复后该符号已移除 → raising=False 成 no-op（断言仍成立）。
    monkeypatch.setattr(search_router, "async_session_factory", factory, raising=False)


async def _seed_project(factory) -> uuid.UUID:
    async with factory() as session:
        session.add(ProjectORM(id=1, name="session-release-1539", config={"model": ""}))
        await session.commit()
    return uuid.UUID(int=1)


async def _search_once(client: AsyncClient, pid: uuid.UUID) -> None:
    resp = await client.get("/api/v1/search", params={"q": "x", "project_id": str(pid)})
    assert resp.status_code == 200, resp.text[:300]


@pytest.mark.asyncio
@pytest.mark.api
async def test_search_reuses_request_session(
    real_get_db, db_engine: AsyncEngine, monkeypatch
) -> None:
    """① 同一批搜索 N 次 → `checkedout()` 不随次数单调上升（修复前：每请求 +1 不归还）。"""
    factory = real_get_db
    pid = await _seed_project(factory)
    _search_patches(monkeypatch, factory)

    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        for _ in range(4):
            await _search_once(client, pid)
        after_first_batch = db_engine.pool.checkedout()
        for _ in range(4):
            await _search_once(client, pid)
        after_second_batch = db_engine.pool.checkedout()

    assert after_second_batch == after_first_batch, (
        f"#1539 ①: 搜索 8 次后 checkedout={after_second_batch}（前 4 次 {after_first_batch}）"
        f" —— 连接随请求数单调上升，搜索未复用请求 session"
    )
    assert after_second_batch == 0, f"#1539 ①: 搜索结束后仍扣住 {after_second_batch} 条连接未归还"


@pytest.mark.asyncio
@pytest.mark.api
async def test_index_rebuild_releases_connections(
    real_get_db, db_engine: AsyncEngine, monkeypatch
) -> None:
    """② 触发一次重建并等其完成 → `checkedout()` 回到基线（修复前：单例 session 常驻 +1）。"""
    from inkflow.api import deps
    from inkflow.domain.services import index_rebuild_service as irs

    factory = real_get_db
    pid = await _seed_project(factory)
    monkeypatch.setattr(deps, "async_session_factory", factory)
    monkeypatch.setattr(deps, "_index_rebuild_service_instance", None)
    monkeypatch.setattr(deps, "get_vector_store_optional", AsyncMock(return_value=None))
    monkeypatch.setattr(deps, "get_search_service", _fake_get_search_service)

    spawned: list[object] = []

    def _capture(coro, *, key=None):
        spawned.append(coro)
        return AsyncMock()

    monkeypatch.setattr(irs, "spawn_background_task", _capture)

    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.post(
            "/api/v1/index/rebuild",
            json={"project_ids": [str(pid)], "scope": "fulltext"},
        )
    assert resp.status_code == 202, resp.text[:300]

    assert spawned, "后台任务未派发（spawn_background_task 未被调用）"
    await spawned[0]  # 等后台执行体跑完

    leaked = db_engine.pool.checkedout()
    assert leaked == 0, (
        f"#1539 ②: 重建完成后仍扣住 {leaked} 条连接未归还 —— "
        f"单例 session 常驻（应后台任务自持 async with 生命周期）"
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_search_and_rebuild_do_not_leak(
    real_get_db, db_engine: AsyncEngine, monkeypatch
) -> None:
    """根因组合断言：搜索 N 次 + 触发一次重建后 `checkedout()` 不随次数上升且归零。"""
    from inkflow.api import deps
    from inkflow.domain.services import index_rebuild_service as irs

    factory = real_get_db
    pid = await _seed_project(factory)
    _search_patches(monkeypatch, factory)
    monkeypatch.setattr(deps, "async_session_factory", factory)
    monkeypatch.setattr(deps, "_index_rebuild_service_instance", None)
    monkeypatch.setattr(deps, "get_vector_store_optional", AsyncMock(return_value=None))
    monkeypatch.setattr(deps, "get_search_service", _fake_get_search_service)

    spawned: list[object] = []

    def _capture(coro, *, key=None):
        spawned.append(coro)
        return AsyncMock()

    monkeypatch.setattr(irs, "spawn_background_task", _capture)

    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        for _ in range(3):
            await _search_once(client, pid)
        after_three = db_engine.pool.checkedout()
        for _ in range(3):
            await _search_once(client, pid)
        after_six = db_engine.pool.checkedout()

        assert after_six == after_three, (
            f"#1539: 搜索 6 次后 checkedout={after_six}（前 3 次 {after_three}）"
            f" —— 连接随搜索次数单调上升"
        )

        resp = await client.post(
            "/api/v1/index/rebuild",
            json={"project_ids": [str(pid)], "scope": "fulltext"},
        )
    assert resp.status_code == 202, resp.text[:300]
    assert spawned, "后台任务未派发（spawn_background_task 未被调用）"
    await spawned[0]

    final = db_engine.pool.checkedout()
    assert final == 0, f"#1539: 搜索 + 重建后仍扣住 {final} 条连接未归还"
