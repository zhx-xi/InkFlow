"""#335 F44 阶段1 书级运行 API 契约测试（TDD RED 阶段）。

权威来源：specs/f44-long-task-orchestrator/spec.md §3（API 契约，v1.1）
+ §13.1 M1-M3。本文件为 `api/routers/books.py`（NEW）定义契约。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【测试方式】ASGITransport + AsyncClient 直连真实 app 对象（import
   inkflow.api.app），`override_get_db` fixture（tests/api/conftest.py）将
   get_db 替换为测试 db_session。所有用例类显式 `@pytest.mark.asyncio` +
   `@pytest.mark.api`（镜像 F19/F39 惯例）。
   本文件模块级 `import inkflow.api.routers.books` 为 RED 收集断言
   （模块不存在 → 全文件收集期 ModuleNotFoundError，即预期失败形态）。

2. 【无 token 模式——硬性契约】所有用例依赖 env `INKFLOW_SERVER_TOKEN`
   未设置时中间件直通：client fixture 内显式 monkeypatch.delenv（镜像
   test_settings_api.py / test_agents_api.py 惯例）。

3. 【模块契约】`inkflow.api.routers.books` 必须暴露：
   - `router = APIRouter(prefix="/api/v1/agent/books", tags=["Books"])`
     （app.py 需 `app.include_router(books.router)`）
   - 端点（§3.1 端点总览，阶段 1）：
     * `POST /planner`           — 启动访谈会话（body {project_id, one_liner}）
       → 201 {session_id, round, questions, max_rounds}
     * `POST /planner/{session_id}/respond` — 回复本轮（body {answers, auto}）
       → 200 {session_id, round, completed, questions, writing_plan?}
     * `GET  /planner/{session_id}` — 会话状态 → 200 / 404
     * `POST /runs`              — 启动书级运行（body {writing_plan_id,
       limits?, mode?}）→ 202 {run_id, status}
     * `GET  /runs/{run_id}`     — 运行状态（进度树 + 计数器）→ 200 / 404
   - 服务装配依赖（供测试 override）：
     * `get_planner_service(db: AsyncSession = Depends(get_db)) -> PlannerService`
     * `get_book_service(db: AsyncSession = Depends(get_db)) -> BookService`
     （端点以 `svc: PlannerService = Depends(get_planner_service)` 注入）

4. 【响应契约（§3.2 示例）】
   - POST /planner → 201：
     {session_id: str, round: int(1), questions: [{id, text, template}, ...],
      max_rounds: int(5)}——questions ≤5 条，每条含 template 非空
   - POST /planner/{id}/respond → 200：
     {session_id, round, completed: bool, questions: [...],
      writing_plan: {...} | null}；completed=true 时 writing_plan 非空
     （含 id/status/title/limits/progress）
   - POST /runs → 202：{run_id: str, status: str}
   - GET /runs/{run_id} → 200：
     {run_id, status, progress: {outline_id: status}, counters: {...}}
     counters 含 max_chapters/max_agent_calls/agent_calls/chapters_written

5. 【异常映射（§3.5）】会话不存在 → 404；运行不存在 → 404；
   上限校验失败（全无护栏）→ 422；计划不存在 → 404。

6. 【mock 策略】本文件用 dependency_overrides 注入 AsyncMock 版
   PlannerService/BookService（不做真实 DB 集成——真实 DB 由
   tests/integration/test_book_repository.py 覆盖；LLM 调用路径由
   unit 层 mock 断言）。端点响应由 mock 返回值驱动，断言路由/状态码/
   请求体/响应体/异常映射契约。
   - get_planner_service mock：start/respond/get 返回值（PlannerSession /
     PlannerRespondResult 领域对象，响应序列化）
   - get_book_service mock：write_book/get_status 返回值（dict）
   ⚠️ mock 返回值必须是**合法领域对象**（UUID 用 uuid4()，非法字符串会被
   Pydantic 拒绝）；respond mock 返回 PlannerRespondResult 实例（端点读
   .session_id/.round/.completed/.questions/.writing_plan 属性）。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import inkflow.api.routers.books  # noqa: F401  # RED 收集断言：模块不存在 → 收集期失败
from inkflow.api.app import app
from inkflow.api.routers.books import get_book_service, get_planner_service
from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.models.writing_plan import WritingPlan
from inkflow.domain.services.planner_service import PlannerRespondResult

BASE = "/api/v1/agent/books"

SAMPLE_SESSION_ID = uuid.uuid4()
SAMPLE_PROJECT_ID = uuid.uuid4()


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


def _sample_session() -> PlannerSession:
    return PlannerSession(
        id=SAMPLE_SESSION_ID,
        project_id=SAMPLE_PROJECT_ID,
        status="drafting",
        one_liner="写一本关于时间旅者的悬疑小说",
        round=1,
        asked_questions=[
            {
                "id": "q1",
                "text": "题材：悬疑为主，还是悬疑+科幻混合？",
                "template": "悬疑为主，但加入 ___ 元素",
            },
            {"id": "q2", "text": "篇幅：预计多少字？", "template": "约 ___ 字"},
            {
                "id": "q3",
                "text": "主角：能否一句话描述主角？",
                "template": "主角是 ___",
            },
        ],
        answers={},
        authorized=[],
        writing_plan_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _respond_result(completed: bool, plan: WritingPlan | None) -> PlannerRespondResult:
    return PlannerRespondResult(
        session_id=SAMPLE_SESSION_ID,
        round=2,
        completed=completed,
        questions=[],
        writing_plan=plan,
    )


# ── POST /planner ─────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_start_201(client, override_services):
    """启动访谈 → 201 + session_id/round/questions(≤5, template 非空)/max_rounds。"""
    planner, _ = override_services
    planner.start.return_value = _sample_session()

    resp = await client.post(
        f"{BASE}/planner",
        json={
            "project_id": str(SAMPLE_PROJECT_ID),
            "one_liner": "写一本关于时间旅者的悬疑小说",
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["session_id"] == str(SAMPLE_SESSION_ID)
    assert body["round"] == 1
    assert len(body["questions"]) <= 5
    assert all(q.get("template") for q in body["questions"])
    assert body["max_rounds"] == 5
    planner.start.assert_awaited_once()


# ── POST /planner/{id}/respond ────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_next_round_200(client, override_services):
    """回复 → 200 + 下一轮（completed=false + questions）。"""
    planner, _ = override_services
    result = _respond_result(completed=False, plan=None)
    result.questions = [
        {"id": "q4", "text": "配角：需要几个主要配角？", "template": "___ 个"}
    ]
    planner.respond.return_value = result

    resp = await client.post(
        f"{BASE}/planner/{SAMPLE_SESSION_ID}/respond",
        json={
            "answers": {
                "q1": "悬疑为主，加入时间悖论",
                "q2": "约 8 万字",
                "q3": "主角是时间旅者",
            },
            "auto": False,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["round"] == 2
    assert body["completed"] is False
    assert body["questions"][0]["id"] == "q4"
    planner.respond.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_completed_returns_writing_plan(
    client, override_services
):
    """回复完成 → 200 + completed=true + writing_plan 非空。"""
    planner, _ = override_services
    plan = WritingPlan(
        id=uuid.uuid4(),
        project_id=SAMPLE_PROJECT_ID,
        title="写一本关于时间旅者的悬疑小说",
        status="ready",
        limits={"max_chapters": 1, "max_agent_calls": 1},
        progress={},
        execution_refs={},
    )
    planner.respond.return_value = _respond_result(completed=True, plan=plan)

    resp = await client.post(
        f"{BASE}/planner/{SAMPLE_SESSION_ID}/respond",
        json={
            "answers": {"q4": "3 卷", "q5": "配角自定"},
            "auto": False,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["completed"] is True
    assert body["writing_plan"] is not None
    assert body["writing_plan"]["id"] == str(plan.id)
    assert body["writing_plan"]["status"] == "ready"


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_auto_true(client, override_services):
    """「全部你决定」（auto=true）→ 200 + completed + writing_plan.status=auto。"""
    planner, _ = override_services
    plan = WritingPlan(
        id=uuid.uuid4(),
        project_id=SAMPLE_PROJECT_ID,
        title="写一本关于时间旅者的悬疑小说",
        status="auto",
        limits={},
        progress={},
        execution_refs={},
    )
    planner.respond.return_value = _respond_result(completed=True, plan=plan)

    resp = await client.post(
        f"{BASE}/planner/{SAMPLE_SESSION_ID}/respond",
        json={
            "answers": {},
            "auto": True,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["completed"] is True
    assert resp.json()["writing_plan"]["status"] == "auto"
    planner.respond.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_missing_404(client, override_services):
    """会话不存在 → 404。"""
    planner, _ = override_services
    planner.respond.side_effect = ValueError("会话不存在")

    resp = await client.post(
        f"{BASE}/planner/{SAMPLE_SESSION_ID}/respond",
        json={
            "answers": {"q1": "x"},
            "auto": False,
        },
    )

    assert resp.status_code == 404


# ── GET /planner/{id} ─────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_get_200(client, override_services):
    """会话状态 → 200（asked_questions/answers 快照）。"""
    planner, _ = override_services
    planner.get.return_value = _sample_session()

    resp = await client.get(f"{BASE}/planner/{SAMPLE_SESSION_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(SAMPLE_SESSION_ID)
    assert body["round"] == 1
    assert body["asked_questions"]


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_get_missing_404(client, override_services):
    """会话不存在 → 404。"""
    planner, _ = override_services
    planner.get.return_value = None

    resp = await client.get(f"{BASE}/planner/{SAMPLE_SESSION_ID}")

    assert resp.status_code == 404


# ── POST /runs ────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_202(client, override_services):
    """启动书级运行 → 202 + {run_id, status}。"""
    _, book = override_services
    book.write_book.return_value = {"run_id": str(uuid.uuid4()), "status": "pending"}

    resp = await client.post(
        f"{BASE}/runs",
        json={
            "writing_plan_id": str(uuid.uuid4()),
            "limits": {"max_chapters": 1, "max_agent_calls": 1},
        },
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"]
    assert body["status"] == "pending"
    book.write_book.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_plan_missing_404(client, override_services):
    """计划不存在 → 404。"""
    _, book = override_services
    book.write_book.side_effect = ValueError("计划不存在")

    resp = await client.post(
        f"{BASE}/runs", json={"writing_plan_id": str(uuid.uuid4())}
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_no_hard_limit_422(client, override_services):
    """上限全无护栏 → 422（§3.5 上限校验失败）。"""
    _, book = override_services
    book.write_book.side_effect = ValueError("至少一道有限护栏")

    resp = await client.post(
        f"{BASE}/runs",
        json={
            "writing_plan_id": str(uuid.uuid4()),
            "limits": {"max_chapters": 0, "max_agent_calls": 0},
        },
    )

    assert resp.status_code == 422


# ── GET /runs/{run_id} ────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_status_200_counters(client, override_services):
    """运行状态 → 200 + progress + counters（M3：上限写死计数器立起来）。"""
    _, book = override_services
    book.get_status.return_value = {
        "run_id": str(uuid.uuid4()),
        "status": "completed",
        "progress": {"c1": "done"},
        "counters": {
            "max_chapters": 1,
            "max_agent_calls": 1,
            "agent_calls": 1,
            "chapters_written": 1,
        },
    }

    resp = await client.get(f"{BASE}/runs/{uuid.uuid4()}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["progress"] == {"c1": "done"}
    counters = body["counters"]
    assert counters["max_chapters"] == 1
    assert counters["max_agent_calls"] == 1
    assert counters["agent_calls"] == 1
    assert counters["chapters_written"] == 1


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_status_missing_404(client, override_services):
    """运行不存在 → 404。"""
    _, book = override_services
    book.get_status.return_value = None

    resp = await client.get(f"{BASE}/runs/{uuid.uuid4()}")

    assert resp.status_code == 404


# ── Coverage-Gap 补测（2026-08-17 CI coverage-backend 98.39% 缺口）──


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_invalid_uuid_404(client, override_services):
    """非法 session_id（非 UUID）→ 404（_parse_id ValueError 分支）。"""
    resp = await client.post(
        f"{BASE}/planner/not-a-uuid/respond",
        json={
            "answers": {"q1": "x"},
            "auto": False,
        },
    )

    assert resp.status_code == 404
    planner, _ = override_services
    planner.respond.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.api
async def test_get_planner_service_real_assembly(db_session):
    """get_planner_service 真实装配：repo 注入 SQLiteBookRepository（依赖函数体覆盖）。

    注：get_planner_service 是普通函数（非 async）——直接调用返回 service。
    """
    from inkflow.api.routers.books import get_planner_service

    svc = get_planner_service(db_session)
    assert svc is not None
    assert hasattr(svc, "start")


@pytest.mark.asyncio
@pytest.mark.api
async def test_get_book_service_real_assembly(db_session):
    """get_book_service 真实装配：repo 注入 SQLiteBookRepository（依赖函数体覆盖）。

    注：get_book_service 是普通函数（非 async）——直接调用返回 service。
    """
    from inkflow.api.routers.books import get_book_service

    svc = get_book_service(db_session)
    assert svc is not None
    assert hasattr(svc, "write_book")


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_other_value_error_422(client, override_services):
    """respond 非「不存在」ValueError（如 write_auto 未装配）→ 422。"""
    planner, _ = override_services
    planner.respond.side_effect = ValueError("write_auto 未装配")

    resp = await client.post(
        f"{BASE}/planner/{SAMPLE_SESSION_ID}/respond",
        json={
            "answers": {},
            "auto": True,
        },
    )

    assert resp.status_code == 422
