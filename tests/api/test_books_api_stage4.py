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
