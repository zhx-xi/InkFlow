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


# ── F44 阶段2（#336）：安全阀 409 + limits 传参 + 多章状态/counters 新键 ──
# 权威来源：spec.md §3.5（「内容已写」安全阀 409）、§5.2（多维上限/进度状态机）、
# §13.2 M4-M6。GREEN 实现须满足：ChapterAlreadyWrittenError → 409；counters
# 新增 max_tokens/tokens_used/tokens_warning 三键。


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_chapter_already_written_409(client, override_services):
    """「内容已写」安全阀命中 → 409（§3.5/M6）：write_book 抛 ChapterAlreadyWrittenError。

    RED 期失败形态：ChapterAlreadyWrittenError 为阶段 2 新增（定义于
    inkflow.domain.services.book_service），阶段 1 尚未定义 → 本用例运行时
    ImportError（即预期 RED）。detail 锁「已有内容」防假绿（仅断言 409
    可能被其他异常映射误命中）。
    """
    from inkflow.domain.services.book_service import ChapterAlreadyWrittenError

    _, book = override_services
    book.write_book.side_effect = ChapterAlreadyWrittenError("该章已有内容，拒绝重跑")

    resp = await client.post(
        f"{BASE}/runs", json={"writing_plan_id": str(uuid.uuid4())}
    )

    assert resp.status_code == 409
    assert "已有内容" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_limits_passed_to_service(client, override_services):
    """POST /runs limits 显式传参 → write_book 收到 BookLimits（§2.4/§5.2 多维上限透传契约）。

    守护形态（RED 期 PASS 刻意）：阶段 1 路由器已把 limits dict 转换 BookLimits 并透传——
    本用例锁定 write_book(writing_plan_id, BookLimits(max_chapters=2, max_agent_calls=2))
    签名契约（防 GREEN 阶段 2 改动装配时破坏 limits 透传）。
    """
    from inkflow.domain.models.writing_plan import BookLimits

    _, book = override_services
    book.write_book.return_value = {"run_id": str(uuid.uuid4()), "status": "pending"}
    plan_id = uuid.uuid4()

    resp = await client.post(
        f"{BASE}/runs",
        json={
            "writing_plan_id": str(plan_id),
            "limits": {"max_chapters": 2, "max_agent_calls": 2},
        },
    )

    assert resp.status_code == 202
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


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_status_counters_new_keys(client, override_services):
    """GET /runs counters 新键契约：max_tokens=200000 / tokens_used=0 / tokens_warning=False。

    守护形态（RED 期 PASS 刻意）：dict 透传直出——本用例锁定阶段 2「token 软护栏」
    计数三键齐备（防 GREEN 只加硬护栏键、漏软护栏三键）。
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
        },
    }

    resp = await client.get(f"{BASE}/runs/{run_id}")

    assert resp.status_code == 200
    counters = resp.json()["counters"]
    assert counters["max_tokens"] == 200_000
    assert counters["tokens_used"] == 0
    assert counters["tokens_warning"] is False


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_no_hard_limit_422_detail(client, override_services):
    """全无护栏 → 422 + detail 锁「至少一道」（§3.5 上限校验失败，防假绿：仅 422 不锁文案）。

    守护形态（RED 期 PASS 刻意）：阶段 1 已映射 422 且 detail 透传 ValueError 消息——
    本用例锁定「至少一道有限护栏」不变式文案契约（M5），防 GREEN 改文案/丢 detail。
    """
    _, book = override_services
    book.write_book.side_effect = ValueError(
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
# specs/f44-long-task-orchestrator/spec.md §13.3 M8。GREEN 实现须满足：
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
    """POST /runs mode="volume" → 202 + write_book_volume 被调用（阶段 3 卷级派发）。

    RED 期失败形态：阶段 1/2 路由器忽略 mode 恒调 write_book——为让用例跑到
    契约断言点，write_book 也预置 dict 返回值（防 FastAPI 序列化 Mock 报 500）；
    202/响应体断言 PASS 后 `write_book_volume.assert_awaited_once_with` FAILED
    （AsyncMock 自动创建属性、从未 await，干净 FAILED）。
    """
    _, book = override_services
    plan_id = uuid.uuid4()
    run_id = str(uuid.uuid4())
    book.write_book_volume.return_value = {"run_id": run_id, "status": "waiting_hitl"}
    book.write_book.return_value = {"run_id": run_id, "status": "waiting_hitl"}

    resp = await client.post(
        f"{BASE}/runs",
        json={"writing_plan_id": str(plan_id), "mode": "volume"},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["status"] == "waiting_hitl"
    book.write_book_volume.assert_awaited_once_with(plan_id)


@pytest.mark.asyncio
@pytest.mark.api
async def test_runs_start_mode_default_static_guard(client, override_services):
    """POST /runs 无 mode（缺省 static）→ write_book 既有路径（守护用例 RED 期 PASS 刻意）。

    本用例锁定阶段 3 mode 派发装配的向后兼容：缺省 mode 必须仍走 write_book
    （防 GREEN 把缺省 mode 误派发到 write_book_volume）。
    """
    _, book = override_services
    book.write_book.return_value = {"run_id": str(uuid.uuid4()), "status": "pending"}

    resp = await client.post(
        f"{BASE}/runs", json={"writing_plan_id": str(uuid.uuid4())}
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"]
    assert body["status"] == "pending"
    book.write_book.assert_awaited_once()
    book.write_book_volume.assert_not_awaited()


# ════ F44 阶段4 追加段（#338 干预 API + 回归摘要）════
# 权威来源：.hermes/plans/f44-stage4-contract.md §3.2/§3.3。GREEN 实现须满足：
# - POST /runs/{run_id}/intervene（body {action, target?, to?, payload?}）→ 200
#   {run_id, status, diff?}；svc.intervene 调用形态 = (run_id, action=...,
#   target=..., to=..., payload=...)（§2 关键字参数契约，全量透传含 None）。
# - 异常映射：ValueError「不存在」→ 404；其余 ValueError（非法干预动作 /
#   已完成章不可干预 / 运行未处于可暂停状态 / 干预目标不存在）→ 422
#   （detail 锁字符串防假绿）。
# - GET /runs/{run_id}/summary → 200 {run_id, status, progress, counters,
#   steps, next}；svc.get_summary 返回 None → 404。
# 用例清单：
# 1. intervene pause → 200 + {run_id, status: paused} + 调用断言
# 2. intervene resume → 200 + {run_id, status: running} + 调用断言
# 3. intervene redirect → 200 + diff + to 透传
# 4. intervene edit → 200 + diff + payload.brief 透传
# 5. intervene 运行不存在 → 404 + detail 含「不存在」
# 6. intervene 其余 ValueError ×4 → 422 + detail 锁字符串（parametrize）
# 7. summary → 200 + 六键响应体
# 8. summary 运行不存在 → 404 + detail 含「不存在」
# 9. 守护：confirm 端点不受影响（RED 期 PASS 刻意）
#
# RED 预期形态（父侧 §7 估「API 4xx FAIL」，逐条推算如下）：intervene/summary
# 端点未注册 → FastAPI 默认 404 "Not Found"——用例 1-4/6/7 状态断言 FAILED；
# 用例 5/8 状态恰撞默认 404、detail 锁「不存在」为 False → detail 断言 FAILED
# （F28 防假绿在 RED 期充当失败定位点）；用例 9 守护 PASS。
# 预期形态：约 11 failed, 1 passed（新增段内）。


# ── POST /runs/{run_id}/intervene ────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_intervene_pause_200(client, override_services):
    """pause 干预 → 200 + {run_id, status: paused}（§3.2 干预端点）。

    RED 期失败形态：intervene 端点阶段 4 才注册 → 404 "Not Found" →
    `assert resp.status_code == 200` 断言 FAILED（干净 RED）。
    """
    _, book = override_services
    run_id = str(uuid.uuid4())
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


@pytest.mark.asyncio
@pytest.mark.api
async def test_intervene_resume_200(client, override_services):
    """resume 干预 → 200 + {run_id, status: running}（§3.2 resume 快响应）。

    RED 期失败形态：intervene 端点未注册 → 404 ≠ 200 → 状态断言 FAILED。
    """
    _, book = override_services
    run_id = str(uuid.uuid4())
    book.intervene.return_value = {"run_id": run_id, "status": "running"}

    resp = await client.post(
        f"{BASE}/runs/{run_id}/intervene", json={"action": "resume"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["status"] == "running"
    book.intervene.assert_awaited_once_with(
        run_id, action="resume", target=None, to=None, payload=None
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_intervene_redirect_200(client, override_services):
    """redirect 章级干预 → 200 + diff（skip/retry/mark_failed，§3.2 to 透传）。

    RED 期失败形态：intervene 端点未注册 → 404 ≠ 200 → 状态断言 FAILED。
    """
    _, book = override_services
    run_id = str(uuid.uuid4())
    book.intervene.return_value = {
        "run_id": run_id,
        "status": "running",
        "diff": {"target": "c1", "from": "in_progress", "to": "skipped"},
    }

    resp = await client.post(
        f"{BASE}/runs/{run_id}/intervene",
        json={"action": "redirect", "target": "c1", "to": "skip"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["diff"]["to"] == "skipped"
    book.intervene.assert_awaited_once_with(
        run_id, action="redirect", target="c1", to="skip", payload=None
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_intervene_edit_200(client, override_services):
    """edit 章级干预 → 200 + diff（payload.brief 透传，§3.2 edit）。

    RED 期失败形态：intervene 端点未注册 → 404 ≠ 200 → 状态断言 FAILED。
    """
    _, book = override_services
    run_id = str(uuid.uuid4())
    book.intervene.return_value = {
        "run_id": run_id,
        "status": "running",
        "diff": {
            "target": "c1",
            "before": "旧",
            "after": "新",
            "diff": "--- 旧\n+++ 新",
        },
    }

    resp = await client.post(
        f"{BASE}/runs/{run_id}/intervene",
        json={"action": "edit", "target": "c1", "payload": {"brief": "新简介"}},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["diff"]["after"] == "新"
    book.intervene.assert_awaited_once_with(
        run_id, action="edit", target="c1", to=None, payload={"brief": "新简介"}
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_intervene_missing_404(client, override_services):
    """运行不存在 → 404 + detail 含「不存在」（§3.2 异常映射）。

    RED 期失败形态：intervene 端点未注册 → 默认 404 的 detail="Not Found"——
    状态断言恰命中，detail 锁「不存在」为 False → 断言 FAILED（防假绿生效）。
    """
    _, book = override_services
    book.intervene.side_effect = ValueError("运行不存在")

    resp = await client.post(
        f"{BASE}/runs/{uuid.uuid4()}/intervene", json={"action": "pause"}
    )

    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


@pytest.mark.parametrize(
    "detail",
    [
        "非法干预动作",
        "已完成章不可干预",
        "运行未处于可暂停状态",
        "干预目标不存在",
    ],
)
@pytest.mark.asyncio
@pytest.mark.api
async def test_intervene_other_value_error_422(client, override_services, detail):
    """intervene 其余 ValueError → 422 + detail 锁字符串（§3.2 防假绿）。

    RED 期失败形态：intervene 端点未注册 → 404 ≠ 422 → 状态断言 FAILED
    （4 个参数化用例各自干净 FAILED）。
    """
    _, book = override_services
    book.intervene.side_effect = ValueError(detail)

    resp = await client.post(
        f"{BASE}/runs/{uuid.uuid4()}/intervene",
        json={"action": "redirect", "target": "c1"},
    )

    assert resp.status_code == 422
    assert detail in resp.json()["detail"]


# ── GET /runs/{run_id}/summary ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_run_summary_200(client, override_services):
    """回归摘要 → 200 + {run_id, status, progress, counters, steps, next}（§3.3）。

    RED 期失败形态：summary 端点阶段 4 才注册 → 404 "Not Found" →
    `assert resp.status_code == 200` 断言 FAILED（干净 RED）。
    """
    _, book = override_services
    run_id = str(uuid.uuid4())
    book.get_summary.return_value = {
        "run_id": run_id,
        "status": "waiting_hitl",
        "progress": {"c1": "done"},
        "counters": {
            "max_chapters": 1,
            "max_agent_calls": 1,
            "agent_calls": 1,
            "chapters_written": 1,
        },
        "steps": [
            {"index": 0, "outline_id": "c1", "status": "done", "execution_id": "e1"}
        ],
        "next": {"volume_index": 0, "total_volumes": 1, "finished": False},
    }

    resp = await client.get(f"{BASE}/runs/{run_id}/summary")

    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["status"] == "waiting_hitl"
    assert body["progress"] == {"c1": "done"}
    assert body["counters"]["chapters_written"] == 1
    assert body["steps"][0]["outline_id"] == "c1"
    assert body["next"]["finished"] is False
    book.get_summary.assert_awaited_once_with(run_id)


@pytest.mark.asyncio
@pytest.mark.api
async def test_run_summary_missing_404(client, override_services):
    """运行不存在 → 404 + detail 含「不存在」（§3.3 get_summary None → 404）。

    RED 期失败形态：summary 端点未注册 → 默认 404 的 detail="Not Found"——
    状态断言恰命中，detail 锁「不存在」为 False → 断言 FAILED（防假绿生效）。
    """
    _, book = override_services
    book.get_summary.return_value = None

    resp = await client.get(f"{BASE}/runs/{uuid.uuid4()}/summary")

    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


# ── 守护用例 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_intervene_guard_confirm_unaffected(client, override_services):
    """守护：既有 confirm 端点不受阶段 4 改动影响（RED 期 PASS 刻意）。

    本用例锁定 confirm_run 既有契约（阶段 3 已 GREEN）在阶段 4 追加
    intervene/summary 后仍成立——防 GREEN 重构路由时破坏既有端点。
    """
    _, book = override_services
    run_id = str(uuid.uuid4())
    book.confirm_run.return_value = {
        "run_id": run_id,
        "status": "running",
        "next_checkpoint": "卷 2",
    }

    resp = await client.post(f"{BASE}/runs/{run_id}/confirm", json={"approved": True})

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


# ════ F44 阶段4 覆盖率补测追加段（规则 1j：coverage.xml hits=0 行补测）════
# 缺口定位（backend/coverage.xml books.py 类块，全量套件口径）：
# - L233 `return await svc.write_book_volume(data.writing_plan_id, limits)`
#   ——mode=volume + limits 非 None 分支。既有 test_runs_start_mode_volume
#   只覆盖 L232（limits 缺省单参形态），L231 branch missing-branches=233。
# - L259 confirm 兜底 422（ValueError 非「不存在」非「未处于等待确认状态」）。
#   既有 test_confirm_run_not_waiting_422 只覆盖 L257-258（「未处于等待确认
#   状态」分支），L257 branch missing-branches=259。
# 跳过项及原因：
# - static + limits（L234）已由既有 test_runs_start_limits_passed_to_service
#   覆盖（coverage.xml hits=1）→ 不补冗余用例。
# - 装配分支 L99-132（_OutlineListAdapter.list / _content_checker /
#   _project_config_getter 函数体）在 override_services mock 轨下不执行；
#   覆盖需真实 BookService 方法消费这些闭包（真实 DB 建表 + plan/outline/
#   chapter 数据 + LLM 调用 mock + 卷级编排真实跑），tests/api 无同形态
#   先例（既有 override_get_db 真实 DB 用例属 repo 直查型 service），且
#   books.py L134-136 声明「真实 writer 装配留待 M2 冒烟」→ 本批跳过，
#   由门禁余量/后续集成测试覆盖（阶段 1 遗留装配代码，非本批新增）。
# 本批新用例为补测形态（被测代码已 GREEN，直接通过，无 RED 阶段）。


class TestCoverageGapApi:
    """F44 阶段4 覆盖率缺口补测（规则 1j，coverage.xml 驱动，books.py）。

    补测 books.py hits=0 行：L233（mode=volume + limits 分支）+ L259
    （confirm 兜底 422）；static+limits（L234）已覆盖、装配分支 L99-132
    跳过，见段注释。
    """

    @pytest.mark.asyncio
    @pytest.mark.api
    async def test_runs_start_mode_volume_with_limits(self, client, override_services):
        """mode=volume + limits 显式传入 → write_book_volume 收到 BookLimits。

        覆盖 books.py L233（write_book_volume(plan_id, limits) 分支）——
        既有 test_runs_start_mode_volume 只覆盖 L232（limits 缺省形态）；
        L231 分支缺口 missing-branches=233 由此闭合。write_book 预置返回值
        防误派发时 FastAPI 序列化 Mock 报 500（镜像既有 volume 用例手法）。
        """
        from inkflow.domain.models.writing_plan import BookLimits

        _, book = override_services
        plan_id = uuid.uuid4()
        run_id = str(uuid.uuid4())
        book.write_book_volume.return_value = {
            "run_id": run_id,
            "status": "waiting_hitl",
        }
        book.write_book.return_value = {"run_id": run_id, "status": "waiting_hitl"}

        resp = await client.post(
            f"{BASE}/runs",
            json={
                "writing_plan_id": str(plan_id),
                "mode": "volume",
                "limits": {"max_chapters": 3},
            },
        )

        assert resp.status_code == 202
        assert resp.json()["run_id"] == run_id
        book.write_book_volume.assert_awaited_once_with(
            plan_id, BookLimits(max_chapters=3)
        )
        book.write_book.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.api
    async def test_runs_start_mode_volume_partial_limits_defaults(
        self, client, override_services
    ):
        """mode=volume + 部分键 limits → BookLimits 未传字段取模型默认。

        锁 BookLimits(**data.limits) 构造语义（books.py L227）：只传
        max_tokens 时 max_chapters/max_agent_calls 保持默认 100/200——
        防 GREEN 改动 limits 构造形态破坏默认值填充契约。
        """
        from inkflow.domain.models.writing_plan import BookLimits

        _, book = override_services
        plan_id = uuid.uuid4()
        book.write_book_volume.return_value = {
            "run_id": str(uuid.uuid4()),
            "status": "waiting_hitl",
        }

        resp = await client.post(
            f"{BASE}/runs",
            json={
                "writing_plan_id": str(plan_id),
                "mode": "volume",
                "limits": {"max_tokens": 50_000},
            },
        )

        assert resp.status_code == 202
        book.write_book_volume.assert_awaited_once_with(
            plan_id, BookLimits(max_tokens=50_000)
        )
        received = book.write_book_volume.await_args.args[1]
        assert received.max_chapters == 100
        assert received.max_agent_calls == 200

    @pytest.mark.parametrize("detail", ["其它错误", "运行已中止"])
    @pytest.mark.asyncio
    @pytest.mark.api
    async def test_confirm_run_other_value_error_422(
        self, client, override_services, detail
    ):
        """confirm 其它 ValueError（非「不存在」非「未处于等待确认状态」）→ 422 兜底。

        覆盖 books.py L259（confirm_run 兜底 422）——既有用例只覆盖
        L257-258（「未处于等待确认状态」分支），L257 branch
        missing-branches=259 由此闭合；detail 精确透传锁兜底映射
        （防 GREEN 把兜底误映射为 404/500）。
        """
        _, book = override_services
        book.confirm_run.side_effect = ValueError(detail)

        resp = await client.post(
            f"{BASE}/runs/{uuid.uuid4()}/confirm",
            json={"approved": True},
        )

        assert resp.status_code == 422
        assert resp.json()["detail"] == detail
