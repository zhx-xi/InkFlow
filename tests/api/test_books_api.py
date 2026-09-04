"""#335 F44 阶段1 书级运行 API 契约测试（TDD RED 阶段）。

权威来源：specs/f44-book-orchestrator/spec.md §3（API 契约，v1.1）
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

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import inkflow.api.routers.books  # noqa: F401  # RED 收集断言：模块不存在 → 收集期失败
from inkflow.api.app import app
from inkflow.api.routers.books import get_book_service, get_planner_service
from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.models.writing_plan import BookLimits, WritingPlan
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
    # 🔒 强化（#524）：锁 detail 含「不存在」——区分期望 404 与 FastAPI 默认 404
    assert "不存在" in resp.json()["detail"]


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
    # 🔒 强化（#524）：锁 detail（router 404 静态文案「会话不存在」）
    assert "不存在" in resp.json()["detail"]


# ── POST /runs ────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_202(client, override_services):
    """启动书级运行 → 202 + {run_id, status: running}（prepare_run 预校验 + 后台任务）。

    F44 阶段4 新契约：POST /runs 先 `await svc.prepare_run(plan_id, limits,
    mode=...)` 预校验（错误立即 404/409/422），返回 running 后 fire-and-forget
    后台任务执行 write_book——请求不阻塞。write_book 由后台任务调用，
    需 `await asyncio.sleep(0)` 让出事件循环后再断言。
    """
    _, book = override_services
    plan_id = uuid.uuid4()
    limits = BookLimits(max_chapters=1, max_agent_calls=1)
    book.prepare_run.return_value = {"run_id": str(uuid.uuid4()), "status": "running"}

    resp = await client.post(
        f"{BASE}/runs",
        json={
            "writing_plan_id": str(plan_id),
            "limits": {"max_chapters": 1, "max_agent_calls": 1},
        },
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"]
    assert body["status"] == "running"
    book.prepare_run.assert_awaited_once_with(plan_id, limits, mode="static")

    await asyncio.sleep(0)
    book.write_book.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_plan_missing_404(client, override_services):
    """计划不存在 → 404（prepare_run 预校验 ValueError「不存在」→ 404）。"""
    _, book = override_services
    book.prepare_run.side_effect = ValueError("计划不存在")

    resp = await client.post(
        f"{BASE}/runs", json={"writing_plan_id": str(uuid.uuid4())}
    )

    assert resp.status_code == 404
    # 🔒 强化（#524）：锁 detail 含「不存在」（prepare_run ValueError 消息透传）
    assert "不存在" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_no_hard_limit_422(client, override_services):
    """上限全无护栏 → 422（prepare_run 预校验，§3.5 上限校验失败）。"""
    _, book = override_services
    book.prepare_run.side_effect = ValueError("至少一道有限护栏")

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
    # 🔒 强化（#524）：锁 detail 含「不存在」（router 静态文案「运行不存在」）
    assert "不存在" in resp.json()["detail"]


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
    # 🔒 强化（#524）：锁「非『不存在』ValueError → 422」分支文案（router 透传 str(e)）
    assert "未装配" in resp.json()["detail"]


# ── F44 阶段2（#336）：安全阀 409 + limits 传参 + 多章状态/counters 新键 ──
# 权威来源：spec.md §3.5（「内容已写」安全阀 409）、§5.2（多维上限/进度状态机）、
# §13.2 M4-M6。GREEN 实现须满足：ChapterAlreadyWrittenError → 409；counters
# 新增 max_tokens/tokens_used/tokens_warning 三键。


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_chapter_already_written_409(client, override_services):
    """「内容已写」安全阀命中 → 409（§3.5/M6）：prepare_run 预校验抛 ChapterAlreadyWrittenError。

    RED 期失败形态：ChapterAlreadyWrittenError 为阶段 2 新增（定义于
    inkflow.domain.services.book_service），阶段 1 尚未定义 → 本用例运行时
    ImportError（即预期 RED）。detail 锁「已有内容」防假绿（仅断言 409
    可能被其他异常映射误命中）。
    #456 迁移：安全阀前移到 prepare_run 预校验层（后台任务改造），
    端点不再直接 await write_book。
    """
    from inkflow.domain.services.book_service import ChapterAlreadyWrittenError

    _, book = override_services
    book.prepare_run.side_effect = ChapterAlreadyWrittenError("该章已有内容，拒绝重跑")

    resp = await client.post(
        f"{BASE}/runs", json={"writing_plan_id": str(uuid.uuid4())}
    )

    assert resp.status_code == 409
    assert "已有内容" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_limits_passed_to_service(client, override_services):
    """POST /runs limits 显式传参 → prepare_run 预校验 + write_book 后台执行均收到 BookLimits
    （§2.4/§5.2 多维上限透传契约）。

    守护形态（RED 期 PASS 刻意）：阶段 1 路由器已把 limits dict 转换 BookLimits 并透传——
    本用例锁定 prepare_run(writing_plan_id, BookLimits(max_chapters=2, max_agent_calls=2),
    mode="static") 签名契约 + 后台 write_book 同参透传（#456 后台任务改造后：
    预校验层与执行层共享 limits）。
    """
    from inkflow.domain.models.writing_plan import BookLimits

    _, book = override_services
    book.prepare_run.return_value = {"run_id": str(uuid.uuid4()), "status": "running"}
    book.write_book.return_value = {"run_id": str(uuid.uuid4()), "status": "completed"}
    plan_id = uuid.uuid4()

    resp = await client.post(
        f"{BASE}/runs",
        json={
            "writing_plan_id": str(plan_id),
            "limits": {"max_chapters": 2, "max_agent_calls": 2},
        },
    )

    assert resp.status_code == 202
    book.prepare_run.assert_awaited_once_with(
        plan_id, BookLimits(max_chapters=2, max_agent_calls=2), mode="static"
    )
    await asyncio.sleep(0)
    book.write_book.assert_awaited_once_with(
        plan_id, BookLimits(max_chapters=2, max_agent_calls=2)
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_status_multi_chapter_progress(client, override_services):
    """GET /runs 多章进度树完整返回 + counters 新键（M4 顺序派发 3 章 + M5 软护栏计数）。

    守护形态（RED 期 PASS 刻意）：阶段 1 路由器为 dict 透传（get_status 原样出）——
    本用例锁定阶段 2「progress 3 章状态 + counters 含 max_tokens/tokens_used/
    tokens_warning」返回体契约（防 GREEN 漏键/丢进度）。
    #902（§1.5）：counters 补 prompt_tokens/completion_tokens 新键期望
    （路由器透传不丢新键——契约升级守护）。
    """
    _, book = override_services
    run_id = str(uuid.uuid4())
    book.get_status.return_value = {
        "run_id": run_id,
        "status": "running",
        "progress": {"c1": "done", "c2": "done", "c3": "in_progress"},
        "counters": {
            "max_chapters": 3,
            "max_agent_calls": 3,
            "agent_calls": 2,
            "chapters_written": 2,
            "max_tokens": 200_000,
            "tokens_used": 12_000,
            "tokens_warning": False,
            "prompt_tokens": 7_200,
            "completion_tokens": 4_800,
        },
    }

    resp = await client.get(f"{BASE}/runs/{run_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["progress"] == {"c1": "done", "c2": "done", "c3": "in_progress"}
    counters = body["counters"]
    assert counters["chapters_written"] == 2
    assert counters["max_tokens"] == 200_000
    assert counters["tokens_used"] == 12_000
    assert counters["tokens_warning"] is False
    assert counters["prompt_tokens"] == 7_200
    assert counters["completion_tokens"] == 4_800


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_status_counters_new_keys(client, override_services):
    """GET /runs counters 新键契约：max_tokens=200000 / tokens_used=0 / tokens_warning=False。

    守护形态（RED 期 PASS 刻意）：dict 透传直出——本用例锁定阶段 2「token 软护栏」
    计数三键齐备（防 GREEN 只加硬护栏键、漏软护栏三键）。
    #902（§1.5）：counters 补 prompt_tokens/completion_tokens 新键期望
    （零用量默认 0 透传——契约升级守护）。
    """
    _, book = override_services
    run_id = str(uuid.uuid4())
    book.get_status.return_value = {
        "run_id": run_id,
        "status": "running",
        "progress": {},
        "counters": {
            "max_chapters": 3,
            "max_agent_calls": 3,
            "agent_calls": 0,
            "chapters_written": 0,
            "max_tokens": 200_000,
            "tokens_used": 0,
            "tokens_warning": False,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        },
    }

    resp = await client.get(f"{BASE}/runs/{run_id}")

    assert resp.status_code == 200
    counters = resp.json()["counters"]
    assert counters["max_tokens"] == 200_000
    assert counters["tokens_used"] == 0
    assert counters["tokens_warning"] is False
    assert counters["prompt_tokens"] == 0
    assert counters["completion_tokens"] == 0


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_no_hard_limit_422_detail(client, override_services):
    """全无护栏 → 422 + detail 锁「至少一道」（§3.5 上限校验失败，防假绿：仅 422 不锁文案）。

    守护形态（RED 期 PASS 刻意）：阶段 1 已映射 422 且 detail 透传 ValueError 消息——
    本用例锁定「至少一道有限护栏」不变式文案契约（M5），防 GREEN 改文案/丢 detail。
    #456 迁移：上限校验在 prepare_run 预校验层（后台任务改造），端点不再直接 await write_book。
    """
    _, book = override_services
    book.prepare_run.side_effect = ValueError(
        "至少一道有限护栏：max_chapters 或 max_agent_calls 必须大于 0"
    )

    resp = await client.post(
        f"{BASE}/runs",
        json={
            "writing_plan_id": str(uuid.uuid4()),
            "limits": {"max_chapters": 0, "max_agent_calls": 0},
        },
    )

    assert resp.status_code == 422
    assert "至少一道" in resp.json()["detail"]


# ════ F44 阶段3 追加段（#337 confirm 端点/命令）════
# 权威来源：.hermes/plans/f44-stage3-contract.md §3.1/§3.2/§3.5/§5.C +
# specs/f44-book-orchestrator/spec.md §13.3 M8。GREEN 实现须满足：
# - POST /runs/{run_id}/confirm（body {approved, decision?}）→ 200
#   {run_id, status, next_checkpoint}；ValueError「运行不存在」→ 404；
#   ValueError「未处于等待确认状态」→ 422（detail 原样透传）。
# - POST /runs mode="volume" → svc.write_book_volume；mode 缺省 static
#   保持既有 write_book 派发（向后兼容）。
# 用例清单：
# 1. confirm 200：mock confirm_run 返回 {run_id, status, next_checkpoint}
#    → 200 + 响应体 + assert_awaited_once_with(run_id, approved=True,
#    decision="继续下一卷")
# 2. confirm 404：confirm_run 抛 ValueError("运行不存在") → 404 + detail 含
#    「不存在」（防假绿：端点未注册时默认 404 的 detail="Not Found" 不含该串）
# 3. confirm 422：confirm_run 抛 ValueError("运行未处于等待确认状态")
#    → 422 + detail 锁「未处于等待确认状态」（防假绿，锁字符串区分默认错误）
# 4. POST /runs mode=volume：write_book_volume 被调用（assert_awaited_once_with
#    plan_id）+ 202 {run_id, status}
# 5. POST /runs mode 缺省 static：write_book 既有路径（守护用例 RED 期 PASS 刻意）
#
# RED 预期形态：confirm 端点未注册 → FastAPI 默认 404 "Not Found"——用例 1/3
# 状态断言 FAILED；用例 2 状态恰撞默认 404、detail 锁 "Not Found" 不含「不存在」
# → detail 断言 FAILED（防假绿生效）；用例 4 阶段 1/2 路由器忽略 mode 恒调
# write_book → 202/响应体 PASS 后 write_book_volume.assert_awaited_once_with
# FAILED（AsyncMock 自动创建属性、从未 await，干净 FAILED）；用例 5 守护 PASS。
# 预期形态：约 4 failed, 1 passed（父侧估「约 3 failed, 2 passed」，按用例清单
# 逐条推算为 4/1——用例 2 的 404 状态断言在端点未注册时恰好命中默认 404）。


# ── POST /runs/{run_id}/confirm ──────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_confirm_run_200(client, override_services):
    """确认卷边界 HITL（approved=true）→ 200 + {run_id, status, next_checkpoint}（§3.2/M8）。

    RED 期失败形态：confirm 端点阶段 3 才注册 → 404 "Not Found" →
    `assert resp.status_code == 200` 断言 FAILED（干净 RED）。
    """
    _, book = override_services
    run_id = str(uuid.uuid4())
    book.confirm_run.return_value = {
        "run_id": run_id,
        "status": "running",
        "next_checkpoint": "卷 2",
    }

    resp = await client.post(
        f"{BASE}/runs/{run_id}/confirm",
        json={"approved": True, "decision": "继续下一卷"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["status"] == "running"
    assert body["next_checkpoint"] == "卷 2"
    book.confirm_run.assert_awaited_once_with(
        run_id, approved=True, decision="继续下一卷"
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_confirm_run_missing_404(client, override_services):
    """运行不存在 → 404 + detail 含「不存在」（§3.5 运行不存在 → 404）。

    RED 期失败形态：confirm 端点未注册 → 默认 404 的 detail="Not Found"——
    状态断言恰命中，detail 锁「不存在」为 False → 断言 FAILED（防假绿生效）。
    """
    _, book = override_services
    book.confirm_run.side_effect = ValueError("运行不存在")

    resp = await client.post(
        f"{BASE}/runs/{uuid.uuid4()}/confirm",
        json={"approved": True},
    )

    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.api
async def test_confirm_run_not_waiting_422(client, override_services):
    """非 waiting_hitl 确认 → 422 + detail 锁「未处于等待确认状态」（§3.5 防假绿）。

    RED 期失败形态：confirm 端点未注册 → 404 ≠ 422 → 状态断言 FAILED（干净 RED）；
    防假绿 = detail 锁字符串，区分「期望 422」与 FastAPI 默认 404 错误。
    """
    _, book = override_services
    book.confirm_run.side_effect = ValueError("运行未处于等待确认状态")

    resp = await client.post(
        f"{BASE}/runs/{uuid.uuid4()}/confirm",
        json={"approved": True},
    )

    assert resp.status_code == 422
    assert "未处于等待确认状态" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_mode_volume(client, override_services):
    """POST /runs mode="volume" → 202 + 后台 write_book_volume(plan_id, None)（阶段 4 新契约）。

    新契约：prepare_run 预校验（mode="volume"）返回 running 后，后台任务
    fire-and-forget 执行 write_book_volume——恒传 limits 参数，无 limits 传
    None；write_book_volume 由后台任务调用，需 sleep(0) 让出事件循环再断言。
    """
    _, book = override_services
    plan_id = uuid.uuid4()
    run_id = str(uuid.uuid4())
    book.prepare_run.return_value = {"run_id": run_id, "status": "running"}

    resp = await client.post(
        f"{BASE}/runs",
        json={"writing_plan_id": str(plan_id), "mode": "volume"},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["status"] == "running"
    book.prepare_run.assert_awaited_once_with(plan_id, None, mode="volume")

    await asyncio.sleep(0)
    book.write_book_volume.assert_awaited_once_with(plan_id, None)


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_mode_default_static_guard(client, override_services):
    """POST /runs 无 mode（缺省 static）→ prepare_run(mode="static") + 后台 write_book（守护）。

    本用例锁定 mode 缺省装配的向后兼容：缺省 mode 必须仍走 static 路径
    （prepare_run mode="static" → 后台 write_book，不派发 write_book_volume）。
    """
    _, book = override_services
    plan_id = uuid.uuid4()
    book.prepare_run.return_value = {"run_id": str(uuid.uuid4()), "status": "running"}

    resp = await client.post(f"{BASE}/runs", json={"writing_plan_id": str(plan_id)})

    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"]
    assert body["status"] == "running"
    book.prepare_run.assert_awaited_once_with(plan_id, None, mode="static")

    await asyncio.sleep(0)
    book.write_book.assert_awaited_once_with(plan_id, None)
    book.write_book_volume.assert_not_awaited()
