"""#1430 方案 A：`POST /runs` force + confirm_overwrite 请求面 / 响应面契约（RED→GREEN）。

权威来源：issue #1430 实现清单第 4 条 + PR #1427 设计结论（请求面双条件）。

契约（本契约冻结）
==================

1. `BookRunRequest` 新增两个可选布尔位：`force` / `confirm_overwrite`（默认 False）。
2. **双条件在服务层判定，router 只透传**：只给其一 → `ValueError` → **422**
   （detail 分别点出缺的那一项）。目的是防止自动化链路静默带上 force
   ——覆盖正文即数据丢失，必须有人显式二次确认。
3. **备份落点随响应可见**（硬约束「不做静默备份」）：force 请求成功（202）时，
   响应体必须带 `overwrite` 块（`forced` / `backup_target` /
   `chapters_to_backup`），用户据此知道旧稿去哪找回。
4. **非 force 路径调用面逐字不变**：两个位都为 False 时，`prepare_run`
   调用不含 force/confirm_overwrite 关键字（既有 6 处 call-shape 契约断言零改动
   = 「非 force 路径行为零变化」的最强证据）。
5. **后台执行体同样收到 force**：`POST /runs` 的后台任务把 force 透传给
   `write_book` / `write_book_volume` / `write_book_agentic`（否则 force 只跳过
   入口预检，后台写正文时仍会撞闸 → 特性等于没做）；非 force 时调用面同样不变。

RED 形态：`BookRunRequest` 无这两字段（Pydantic 默认忽略未知字段 → 请求体被
静默丢弃，`prepare_run` 收到的 force 为 False）→ 用例 1/2/3 断言失败；
`_run_book` 无 force 形参 → 用例 6 TypeError。
"""

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import inkflow.api.routers.books  # noqa: F401  # 模块级 import 保留（镜像 test_books_api.py）
from inkflow.api.app import app
from inkflow.api.routers.books import _run_book, get_book_service, get_planner_service

BASE = "/api/v1/agent/books"

_FORCE_ONLY_DETAIL = "force 与 confirm_overwrite 必须同时提供"


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


# ── 请求面：双条件透传 + 拒绝映射 ────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_force_with_confirm_forwarded_and_backup_visible(client, override_services):
    """force + confirm_overwrite → 透传给 prepare_run；202 响应带备份可见信息。"""
    _, book = override_services
    plan_id = uuid.uuid4()
    book.prepare_run.return_value = {
        "run_id": str(uuid.uuid4()),
        "status": "running",
        "overwrite": {
            "forced": True,
            "backup_target": "chapters.previous_content",
            "chapters_to_backup": 2,
        },
    }

    resp = await client.post(
        f"{BASE}/runs",
        json={
            "writing_plan_id": str(plan_id),
            "force": True,
            "confirm_overwrite": True,
        },
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "running"
    # 备份落点/章数随响应可见（不做静默备份）
    assert body["overwrite"]["backup_target"] == "chapters.previous_content"
    assert body["overwrite"]["chapters_to_backup"] == 2
    book.prepare_run.assert_awaited_once_with(
        plan_id, None, mode="static", force=True, confirm_overwrite=True
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_force_without_confirm_422(client, override_services):
    """只给 force → 422（服务层不变量，detail 点出缺 confirm_overwrite）。"""
    _, book = override_services
    book.prepare_run.side_effect = ValueError(_FORCE_ONLY_DETAIL)

    resp = await client.post(
        f"{BASE}/runs",
        json={"writing_plan_id": str(uuid.uuid4()), "force": True},
    )

    assert resp.status_code == 422
    assert "confirm_overwrite" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_confirm_without_force_422(client, override_services):
    """只给 confirm_overwrite → 422（反之亦然），且调用面把两位都透传。"""
    _, book = override_services
    plan_id = uuid.uuid4()
    book.prepare_run.side_effect = ValueError(_FORCE_ONLY_DETAIL)

    resp = await client.post(
        f"{BASE}/runs",
        json={"writing_plan_id": str(plan_id), "confirm_overwrite": True},
    )

    assert resp.status_code == 422
    assert "force" in resp.json()["detail"]
    book.prepare_run.assert_awaited_once_with(
        plan_id, None, mode="static", force=False, confirm_overwrite=True
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_default_request_keeps_call_shape_unchanged(client, override_services):
    """非 force 路径零变化：默认请求的 prepare_run 调用**不含**两个新关键字。"""
    _, book = override_services
    plan_id = uuid.uuid4()
    book.prepare_run.return_value = {"run_id": str(uuid.uuid4()), "status": "running"}

    resp = await client.post(f"{BASE}/runs", json={"writing_plan_id": str(plan_id)})

    assert resp.status_code == 202
    assert "overwrite" not in resp.json()
    book.prepare_run.assert_awaited_once_with(plan_id, None, mode="static")

    await asyncio.sleep(0)
    book.write_book.assert_awaited_once_with(plan_id, None)  # 后台调用面同样不变


# ── 后台执行体：force 必须传到 write_book* ───────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_force_reaches_background_write_book(client, override_services):
    """POST /runs(force) → 后台 write_book 收到 force=True（否则后台仍撞闸）。"""
    _, book = override_services
    plan_id = uuid.uuid4()
    book.prepare_run.return_value = {
        "run_id": str(uuid.uuid4()),
        "status": "running",
        "overwrite": {"forced": True},
    }

    resp = await client.post(
        f"{BASE}/runs",
        json={
            "writing_plan_id": str(plan_id),
            "force": True,
            "confirm_overwrite": True,
        },
    )

    assert resp.status_code == 202
    await asyncio.sleep(0)
    book.write_book.assert_awaited_once_with(plan_id, None, force=True)


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_volume_mode_force_reaches_write_book_volume(client, override_services):
    """mode=volume + force → 后台 write_book_volume 收到 force=True（三轨口径一致）。"""
    _, book = override_services
    plan_id = uuid.uuid4()
    book.prepare_run.return_value = {
        "run_id": str(uuid.uuid4()),
        "status": "running",
        "overwrite": {"forced": True},
    }

    resp = await client.post(
        f"{BASE}/runs",
        json={
            "writing_plan_id": str(plan_id),
            "mode": "volume",
            "force": True,
            "confirm_overwrite": True,
        },
    )

    assert resp.status_code == 202
    await asyncio.sleep(0)
    book.write_book_volume.assert_awaited_once_with(plan_id, None, force=True)


@pytest.mark.asyncio
@pytest.mark.api
async def test_run_book_agentic_force_threaded():
    """_run_book(mode='agentic', force=True) → write_book_agentic 收到 force=True。"""
    book = AsyncMock()
    plan_id = uuid.uuid4()

    await _run_book(book, plan_id, None, mode="agentic", force=True)

    book.write_book_agentic.assert_awaited_once_with(plan_id, None, None, force=True)


@pytest.mark.asyncio
@pytest.mark.api
async def test_run_book_non_force_call_shape_unchanged():
    """非 force：_run_book 的三个模式方法调用面与既有契约逐字一致。"""
    book = AsyncMock()
    plan_id = uuid.uuid4()

    await _run_book(book, plan_id, None, mode="static")

    book.write_book.assert_awaited_once_with(plan_id, None)
