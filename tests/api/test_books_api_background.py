"""#456 F44 阶段4 FastAPI 后台任务 API 契约测试（TDD RED 阶段，fix/010-bug-batch）。

权威来源：.hermes/plans/fix-010-bug-batch.md §任务 2（F44 阶段4 FastAPI 后台任务）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【POST /runs 后台化契约】端点不再同步 await write_book/write_book_volume：
   - 先 `await svc.prepare_run(plan_id, limits, mode=...)` 预校验（错误立即
     404/409/422），返回 {"run_id", "status"}；
   - status == "running" → fire-and-forget 后台任务执行 write_book /
     write_book_volume（limits 恒传，无 limits 传 None），请求立即返回 202
     （不被长任务阻塞）；
   - status != "running"（如 "completed" 无章快路径）→ 不启后台任务，直接返回。
2. 【后台任务异常】任务体内 write_book/write_book_volume 抛异常 → 捕获后
   `svc.mark_failed(str(plan_id))` 落 failed 状态；响应已 202 返回，不 500。
3. 【intervene 组合】POST /runs 启动后，POST /runs/{run_id}/intervene
   body {action: "pause"} → 200 + {run_id, status: "paused"}；svc.intervene
   调用形态 = (run_id, action=..., target=..., to=..., payload=...)（全量透传
   含 None）。
   （注：intervene 端点既有代码已实现、intervene 段可能已绿——本用例为契约
   组合测试，整体 RED 由 POST /runs 段保证。）
4. 【测试方式】镜像 test_books_api.py：dependency_overrides 注入 AsyncMock
   版 BookService；ASGITransport 与测试同事件循环直连 app，后台任务靠
   `await asyncio.sleep(0)` 让出事件循环推进。模块级 import books 保留。
5. 【后台任务防泄漏】用例 1 的 release Event 在 finally 中 set，保证
   write_book 侧效果协程不被挂起（RED 期 wait_for 超时取消后同样安全）。
"""

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import inkflow.api.routers.books  # noqa: F401  # 模块级 import 保留（镜像 test_books_api.py）
from inkflow.api.app import app
from inkflow.api.routers.books import get_book_service, get_planner_service

BASE = "/api/v1/agent/books"


@pytest.fixture
def client(monkeypatch):
    """无 token 模式 AsyncClient（INKFLOW_SERVER_TOKEN 未设置直通）。"""
    monkeypatch.delenv("INKFLOW_SERVER_TOKEN", raising=False)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def override_services(client):
    """注入 AsyncMock 版 PlannerService/BookService（依赖 override）。"""
    planner = AsyncMock()
    book = AsyncMock()

    async def _planner_override():
        return planner

    async def _book_override():
        return book

    app.dependency_overrides[get_planner_service] = _planner_override
    app.dependency_overrides[get_book_service] = _book_override
    yield planner, book
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_returns_immediately_not_blocking(client, override_services):
    """关键契约：启动长任务后请求立即返回（不被 write_book 阻塞）。

    write_book 挂 started/release 双 Event：GREEN 下后台任务启动即卡在
    release.wait()，POST 已 202 返回；RED 下（同步执行）请求被 write_book
    阻塞 → asyncio.wait_for(timeout=1.0) 超时（预期失败形态）。
    """
    _, book = override_services
    plan_id = uuid.uuid4()
    book.prepare_run.return_value = {"run_id": "run-bg", "status": "running"}
    started = asyncio.Event()
    release = asyncio.Event()

    async def _blocking_write(_plan_id, _limits):
        started.set()
        await release.wait()

    book.write_book.side_effect = _blocking_write

    try:
        resp = await asyncio.wait_for(
            client.post(f"{BASE}/runs", json={"writing_plan_id": str(plan_id)}),
            timeout=1.0,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["run_id"] == "run-bg"
        assert body["status"] == "running"

        # 请求已返回；后台任务已开始执行（卡在 release.wait()）
        await asyncio.sleep(0)
        assert started.is_set()

        release.set()
        await asyncio.sleep(0)
        book.write_book.assert_awaited_once()
    finally:
        release.set()


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_task_failure_marks_failed(client, override_services):
    """后台任务内 write_book 抛异常 → mark_failed(run_id)，请求仍 202。

    契约：任务体捕获 write_book/write_book_volume 异常并调用
    `svc.mark_failed(str(plan_id))`；响应已 202 返回（不 500）。
    run_id 取 str(plan_id)：GREEN 实现 mark_failed(str(plan_id))，run_id 与
    plan_id 同值保证断言可满足（计划 §任务 2 设计 B/C）。
    """
    _, book = override_services
    plan_id = uuid.uuid4()
    run_id = str(plan_id)
    book.prepare_run.return_value = {"run_id": run_id, "status": "running"}
    book.write_book.side_effect = RuntimeError("boom")

    resp = await client.post(f"{BASE}/runs", json={"writing_plan_id": str(plan_id)})

    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["status"] == "running"

    await asyncio.sleep(0)
    book.mark_failed.assert_awaited_once_with(run_id)


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_completed_fast_path_no_task(client, override_services):
    """无章快路径：prepare_run 返回 completed → 直接返回，不启后台任务。

    契约：prepare_run 预校验发现无章 → plan.status="completed" → 返回
    {"run_id", "status": "completed"}；endpoint 对非 running 状态直接返回，
    不 spawn 后台任务 → write_book/write_book_volume 均不得被调用。
    """
    _, book = override_services
    book.prepare_run.return_value = {"run_id": "run-done", "status": "completed"}

    resp = await client.post(
        f"{BASE}/runs", json={"writing_plan_id": str(uuid.uuid4())}
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"] == "run-done"
    assert body["status"] == "completed"

    await asyncio.sleep(0)
    book.write_book.assert_not_awaited()
    book.write_book_volume.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.api
async def test_intervene_while_running_200(client, override_services):
    """运行中 intervene pause → 200 + paused + 调用形态断言（组合契约）。

    先 POST /runs 启动（prepare_run → running）再 intervene pause；
    svc.intervene 调用形态 = (run_id, action=..., target=..., to=...,
    payload=...)（全量透传含 None）。
    注：intervene 段在既有代码已实现（可能已绿），整体 RED 由 POST /runs
    段（同步执行 + prepare_run 缺失）保证。
    """
    _, book = override_services
    run_id = "run-x"
    book.prepare_run.return_value = {"run_id": run_id, "status": "running"}

    resp = await client.post(
        f"{BASE}/runs", json={"writing_plan_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 202

    book.intervene.return_value = {"run_id": run_id, "status": "paused"}
    resp = await client.post(
        f"{BASE}/runs/{run_id}/intervene", json={"action": "pause"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["status"] == "paused"
    book.intervene.assert_awaited_once_with(
        run_id, action="pause", target=None, to=None, payload=None
    )
