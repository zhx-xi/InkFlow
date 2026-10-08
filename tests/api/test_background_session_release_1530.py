"""#1530 RED 契约 —— 后台 fire-and-forget 任务不得复用请求 session（连接泄漏）。

现象（0.17.0-rc1 内核日志）::

    ERROR | logging:handle: The garbage collector is trying to clean up
    non-checked-in connection <AdaptedConnection <aiosqlite.core.Connection ...>>

根因（本文件锁定的契约）：`spawn_background_task` 派发的后台任务复用了
**HTTP 请求级 session**（`Depends(get_db)` 的 `async with` 生命周期）：

- `api/routers/chapter_audit.py` → `spawn_background_task(svc.run_audit_job(...), key=...)`
- `api/routers/books.py`       → `spawn_background_task(_run_book(svc, ...), key=...)`

请求返回时 `get_db` 关闭会话并归还连接；后台任务此后仍在该会话上执行 →
SQLAlchemy 重新 checkout 一条连接，且**任务体从不 `close()`** → 连接不归还。
若此时仍有引用（运行中的任务 / 异常 traceback 等），GC 回收该会话即打印上述告警；
长会话 / 并发下连接持续被扣住可致连接池耗尽。

判据（根因断言，**非**「日志里没告警」）：后台任务执行完毕后，连接池
`checkedout()` 必须为 0。本文件在断言前**保留对请求级 service 的引用**
（`_captured`）——否则 CPython 引用计数会在任务结束后静默释放该会话，
把「连接从未显式归还」的真实状态掩盖成 `checkedout == 0`（假绿）。

  - 修复前：== 1（连接被后台任务持有、未归还）→ 本文件 FAIL（RED 证据）
  - 修复后：== 0（后台任务自持 session，任务结束归还）

对照范式：`infrastructure/context/summary_background_refresh.py` 的后台任务
**自建** `async_session_factory()` 并以 `async with` 管理生命周期（正确形态）。

依据: issue #1530（0.17.0 · rc1 修复批 W8d）。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from inkflow.api.app import app
from inkflow.api.deps import get_db
from inkflow.core.database import Base
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.writing_plan import WritingPlanORM

BASE_URL = "http://test1530"


@pytest_asyncio.fixture
async def db_engine(tmp_path) -> AsyncGenerator[AsyncEngine]:
    """文件型 SQLite（QueuePool → 暴露 `checkedout()` 计数）+ 建全表。"""
    db_file = tmp_path / "conn-leak-1530.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def real_get_db(db_engine: AsyncEngine):
    """`get_db` override = **真实请求级生命周期**（`async with factory()`）。

    与既有 `tests/api/conftest.override_get_db`（`yield <共享 session>`，永不 close）
    不同：这里逐请求新建并用上下文管理器归还连接，复刻生产 `get_db` 语义 —— 唯有
    如此才能观测「请求结束后连接是否被后台任务扣住」。
    """
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override() -> AsyncGenerator[object]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    yield factory
    app.dependency_overrides.pop(get_db, None)


async def _seed_project(factory, *, chapter: bool) -> tuple[uuid.UUID, uuid.UUID | None]:
    """落库 1 项目（+ 可选 1 空章节）；领域 id = uuid.UUID(int=orm.id)。"""
    async with factory() as session:
        session.add(ProjectORM(id=1, name="conn-leak-1530", config={"model": ""}))
        await session.commit()
    cid: uuid.UUID | None = None
    if chapter:
        async with factory() as session:
            session.add(ChapterORM(id=1, project_id=1, title="第1章", content="", word_count=0))
            await session.commit()
        cid = uuid.UUID(int=1)
    return uuid.UUID(int=1), cid


@pytest.mark.asyncio
@pytest.mark.api
async def test_audit_background_task_releases_request_connection(
    real_get_db, db_engine: AsyncEngine
) -> None:
    """审计后台任务（#1425 异步链）执行完毕后，请求连接必须已归还。

    gate 卡住后台任务首个动作（`_run_checks`），确保它在**请求结束之后**才真正
    触碰数据库 —— 复刻生产「长任务跑在请求生命周期之外」的时序。
    """
    from inkflow.api.routers import chapter_audit as audit_router
    from inkflow.domain.services.chapter_audit_service import ChapterAuditService

    factory = real_get_db
    pid, cid = await _seed_project(factory, chapter=True)
    assert cid is not None

    captured: list[object] = []
    original_factory = audit_router.get_chapter_audit_service

    def _recording_factory(db, **kwargs):
        svc = original_factory(db, **kwargs)
        captured.append(svc)  # 保留引用：暴露「连接从未显式归还」的真状态
        return svc

    gate = asyncio.Event()
    original_run_checks = ChapterAuditService._run_checks

    async def _gated_run_checks(self, *args, **kwargs):
        await gate.wait()  # 请求结束后测试才放行 → 强制在请求 session 关闭后触库
        return await original_run_checks(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(audit_router, "get_chapter_audit_service", _recording_factory)
        mp.setattr(ChapterAuditService, "_run_checks", _gated_run_checks)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                f"/api/v1/projects/{pid}/chapters/{cid}/audit",
                json={"include_static": False},
            )
        assert resp.status_code == 202, resp.text[:300]
        # 请求已结束（get_db 的 async with 已关闭 session）→ 放行后台任务
        gate.set()
        await asyncio.sleep(0.15)  # 让后台任务跑完

    assert captured, "审计服务未装配（端点未走真实 get_chapter_audit_service）"
    leaked = db_engine.pool.checkedout()
    assert leaked == 0, (
        f"#1530: 后台任务执行完毕后仍扣住 {leaked} 条连接未归还 —— "
        f"audit 后台任务复用了请求 session（应自持 async with 生命周期）"
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_book_run_background_task_releases_request_connection(
    real_get_db, db_engine: AsyncEngine
) -> None:
    """书级运行后台任务（#456/#1425 同款 fire-and-forget）执行完毕后连接必须归还。

    agentic 模式（`_check_agentic_authorized` 见项目 config.auto_write_enabled=True）
    下 `prepare_run` 落 running → 端点 `spawn_background_task(_run_book(svc, ...))`。
    后台写体被 gate 卡住，待请求结束（请求 session 关闭）后再执行一次**非提交读**
    （`get_writing_plan` 为纯 SELECT）——模拟长任务中途：事务保持打开、连接被该
    session 持有，任务结束后若不复用归还则泄漏。
    """
    from inkflow.api.routers import books
    from inkflow.domain.services.book_service import BookService

    factory = real_get_db
    async with factory() as session:
        session.add(
            ProjectORM(
                id=1,
                name="conn-leak-1530-book",
                config={"model": "", "auto_write_enabled": True},
            )
        )
        await session.commit()
    plan_id = uuid.uuid4()
    async with factory() as session:
        session.add(WritingPlanORM(id=str(plan_id), project_id=1, title="计划", status="ready"))
        await session.commit()

    captured: list[object] = []
    original_build = books._build_book_service

    def _recording_build(db):
        svc = original_build(db)
        captured.append(svc)  # 保留引用：暴露「连接从未显式归还」的真状态
        return svc

    gate = asyncio.Event()

    async def _gated_write(self, *args, **kwargs):
        await gate.wait()  # 请求结束后放行 → 后台任务在请求 session 关闭后才触库
        # 非提交读（`get_writing_plan` 为纯 SELECT）：模拟长任务中途——事务保持打开，
        # 连接被该 session 持有、任务结束后未归还（生产长任务的真实形态）。
        await self._repo.get_writing_plan(str(plan_id))

    with pytest.MonkeyPatch.context() as mp:
        # 模块级 pipeline 单例会绑到已释放的测试 session → 重置
        mp.setattr(books, "_book_volume_pipeline", None, raising=False)
        mp.setattr(books, "_book_agentic_pipeline", None, raising=False)
        mp.setattr(books, "_build_book_service", _recording_build)
        mp.setattr(BookService, "write_book_agentic", _gated_write)
        mp.setattr(
            "inkflow.api._llm_resolver.resolve_llm_credentials",
            lambda *_a, **_k: ("deepseek/deepseek-v4-flash", "k", "https://x.test/v1"),
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/agent/books/runs",
                json={"writing_plan_id": str(plan_id), "mode": "agentic"},
            )
        assert resp.status_code == 202, resp.text[:300]
        assert resp.json()["status"] == "running", resp.json()
        gate.set()
        await asyncio.sleep(0.15)  # 让后台任务的 mark_failed 兜底写完

    assert captured, "书级服务未装配（端点未走真实 _build_book_service）"
    leaked = db_engine.pool.checkedout()
    assert leaked == 0, (
        f"#1530: 后台任务执行完毕后仍扣住 {leaked} 条连接未归还 —— "
        f"book run 后台任务复用了请求 session（应自持 async with 生命周期）"
    )
