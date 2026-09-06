"""F44 v1.2 #475 访谈 LLM 动态提问 API 契约测试（TDD RED 阶段，兄弟文件）。

权威来源：specs/f44-book-orchestrator/spec.md §3.2（v1.2 响应扩展——
questions[] 含 kind；respond 响应加 confirmed_items/conflicts/confirming；
PlannerRespondRequest 加 confirm）、§3.5（非 confirming 阶段 confirm → 422）、
§13.5 M13（API 测试：confirm 端点 + confirmed_items/conflicts 响应字段）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约）
════════════════════════════════════════════════════════════════════

1. 【响应契约扩展】（§3.2 v1.2）
   - POST /planner → 201：questions[] 每项含 kind（general|targeted|conflict）；
     响应含 confirmed_items / conflicts / confirming（默认空/False）
   - POST /planner/{id}/respond → 200：响应含 confirmed_items / conflicts /
     confirming（PlannerRespondResult 新字段透传）
   - GET /planner/{id} → 200：session.model_dump 含 confirmed_items / conflicts /
     confirming（PlannerSession v1.2 字段）

2. 【请求体扩展】（§5.1 前端契约 / §3.2）
   - PlannerRespondRequest 加 confirm: bool = False；
     respond 端点把 data.confirm 透传给 svc.respond(..., confirm=data.confirm)

3. 【异常映射】（§3.5 v1.2）
   - 非 confirming 阶段 confirm → svc.respond 抛 ValueError → 422

4. 【mock 策略】同 test_books_api.py：dependency_overrides 注入 AsyncMock
   PlannerService；mock 返回值必须是合法领域对象（UUID 用 uuid4()）；
   PlannerRespondResult 实例带 v1.2 新字段（RED 期 Pydantic extra=ignore
   忽略 → 端点不输出 → 断言失败；GREEN 后透传）。

5. 【RED 预期形态】端点未透传 confirm/未输出 v1.2 字段 → 断言失败；
   confirm 透传用例锁定 svc.respond 调用签名。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import inkflow.api.routers.books  # noqa: F401  # 模块契约断言
from inkflow.api.app import app
from inkflow.api.routers.books import get_planner_service
from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.models.writing_plan import WritingPlan
from inkflow.domain.services.planner_service import (
    ROUND1_QUESTIONS,
    PlannerRespondResult,
)
from inkflow.infrastructure.database.models.project import ProjectORM

BASE = "/api/v1/agent/books"

SAMPLE_SESSION_ID = uuid.uuid4()
SAMPLE_PROJECT_ID = uuid.uuid4()

# #977 §0/§4 RED-2 迁移前提：真实装配用例须 seed 项目行（config.model 非空）→ 修复后
# project_repo.get 命中 → resolve_model 走项目模型 → chat 仍被调。id 用小值
# uuid.UUID(int=1)（SQLite projects.id 为 INTEGER 主键，随机 uuid4 超出 int64 →
# repo.get 超范围守卫 return None，见 project_repo.py:78-81）。
SEED_PROJECT_ID = uuid.UUID(int=1)

_CONFIRMED = [
    {"key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user"},
    {"key": "篇幅", "value": "10 万字", "source": "user"},
    {"key": "主题", "value": "时间旅者自我救赎", "source": "llm_inferred"},
]


@pytest.fixture
def client(monkeypatch):
    """无 token 模式 AsyncClient（INKFLOW_SERVER_TOKEN 未设置直通）。"""
    monkeypatch.delenv("INKFLOW_SERVER_TOKEN", raising=False)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def override_planner(client):
    """注入 AsyncMock 版 PlannerService（依赖 override）。"""
    planner = AsyncMock()

    async def _planner_override():
        return planner

    app.dependency_overrides[get_planner_service] = _planner_override
    yield planner
    app.dependency_overrides.clear()


def _sample_session_v12() -> PlannerSession:
    """带 v1.2 字段的会话（RED 期 extra=ignore 忽略，GREEN 后生效）。"""
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
                "kind": "general",
            },
            {
                "id": "q4",
                "text": "时间旅者的穿越机制是设备还是能力？",
                "template": "穿越通过 ___ 实现",
                "kind": "targeted",
            },
        ],
        answers={},
        authorized=[],
        confirmed_items=[],
        conflicts=[],
        confirming=False,
        writing_plan_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _respond_result_v12(
    completed: bool = False,
    confirming: bool = False,
    plan: WritingPlan | None = None,
) -> PlannerRespondResult:
    """带 v1.2 字段的 respond 结果（GREEN 后字段生效）。"""
    return PlannerRespondResult(
        session_id=SAMPLE_SESSION_ID,
        round=2,
        completed=completed,
        questions=[],
        confirmed_items=list(_CONFIRMED),
        conflicts=[
            {
                "round": 1,
                "question_id": "q5",
                "answer": "配角 5 个",
                "conflict_with": "篇幅/复杂度合理性",
                "resolution": "pending",
            }
        ],
        confirming=confirming,
        writing_plan=plan,
    )


async def _seed_project(db_session, *, model: str | None) -> uuid.UUID:
    """Seed 单行项目行（#977 RED-2 迁移前提）。

    ProjectORM.config 为 LenientJSON 列：{"model": <模型>} round-trip 至领域
    ProjectConfig.model（_orm_to_domain project_repo.py:37）。created_at/updated_at
    显式给值（nullable=False 坑，contract §4 警示）。返回 domain 项目 id
    （uuid.UUID(int=orm.id)）。
    """
    orm = ProjectORM(
        id=SEED_PROJECT_ID.int,
        name="seed-project-977",
        config={"model": model},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(orm)
    await db_session.commit()
    await db_session.refresh(orm)
    return SEED_PROJECT_ID


# ── POST /planner：v1.2 响应字段 ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_start_response_has_v12_fields(client, override_planner):
    """启动访谈 → 201：questions 含 kind + confirmed_items/conflicts/confirming。"""
    planner = override_planner
    planner.start.return_value = _sample_session_v12()

    resp = await client.post(
        f"{BASE}/planner",
        json={
            "project_id": str(SAMPLE_PROJECT_ID),
            "one_liner": "写一本关于时间旅者的悬疑小说",
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["confirmed_items"] == []
    assert body["conflicts"] == []
    assert body["confirming"] is False
    kinds = {q.get("kind") for q in body["questions"]}
    assert "general" in kinds and "targeted" in kinds


# ── POST /planner/{id}/respond：v1.2 响应字段 + confirm 透传 ───────


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_response_has_v12_fields(client, override_planner):
    """回复 → 200：响应含 confirmed_items/conflicts/confirming（新字段透传）。"""
    planner = override_planner
    planner.respond.return_value = _respond_result_v12()

    resp = await client.post(
        f"{BASE}/planner/{SAMPLE_SESSION_ID}/respond",
        json={"answers": {"q1": "悬疑为主，加入时间悖论"}, "auto": False},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed_items"] == _CONFIRMED
    assert body["conflicts"][0]["conflict_with"] == "篇幅/复杂度合理性"
    assert body["conflicts"][0]["resolution"] == "pending"
    assert body["confirming"] is False


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_confirm_true_passed_to_service(client, override_planner):
    """末尾总体确认：respond body {confirm: true} → svc.respond 收到 confirm=True。"""
    planner = override_planner
    plan = WritingPlan(
        id=uuid.uuid4(),
        project_id=SAMPLE_PROJECT_ID,
        title="写一本关于时间旅者的悬疑小说",
        status="ready",
        limits={"max_chapters": 1, "max_agent_calls": 1},
        progress={},
        execution_refs={},
    )
    planner.respond.return_value = _respond_result_v12(completed=True, confirming=True, plan=plan)

    resp = await client.post(
        f"{BASE}/planner/{SAMPLE_SESSION_ID}/respond",
        json={"answers": {}, "confirm": True},
    )

    assert resp.status_code == 200
    assert resp.json()["completed"] is True
    planner.respond.assert_awaited_once_with(SAMPLE_SESSION_ID, {}, auto=False, confirm=True)


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_confirm_not_confirming_422(client, override_planner):
    """非 confirming 阶段 confirm → 422（§3.5 v1.2 异常映射）。"""
    planner = override_planner
    planner.respond.side_effect = ValueError("非确认阶段")

    resp = await client.post(
        f"{BASE}/planner/{SAMPLE_SESSION_ID}/respond",
        json={"answers": {}, "confirm": True},
    )

    assert resp.status_code == 422


# ── GET /planner/{id}：v1.2 字段 ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_get_response_has_v12_fields(client, override_planner):
    """会话状态 → 200：响应含 confirmed_items/conflicts/confirming（审计回溯）。"""
    planner = override_planner
    session = _sample_session_v12()
    session.confirming = True
    session.confirmed_items = list(_CONFIRMED)
    planner.get.return_value = session

    resp = await client.get(f"{BASE}/planner/{SAMPLE_SESSION_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed_items"] == _CONFIRMED
    assert body["conflicts"] == []
    assert body["confirming"] is True


# ── Coverage-Gap 补测（2026-08-19 CI coverage-backend 98.34% 缺口）──
# 缺失行映射：books.py _project_context_getter 成功空数据 + except 分支 +
# planner_service 模板渲染路径（540-554）+ 装配闭包 _outline_service/
# _character_service（125/134）+ BookService 回调（172-205）真实执行。


@pytest.mark.asyncio
@pytest.mark.api
async def test_get_planner_service_llm_start_real_assembly(db_session):
    """真实装配 + mock LLM：start 走 _project_context_getter（seed 项目 → 设定摘要）+
    模板渲染路径（540-554 真实 PromptManager）。

    #977 迁移（§0/§4 RED-2）：seed 项目行（config.model 非空），start 用 seed 项目
    id → 修复后 project_repo.get 命中 → resolve_model 走项目模型 → chat 仍被调
    （保持原 `chat.assert_awaited_once` 绿，锁「真实装配回调 + 模板渲染」语义不变）。
    """
    import json as _json
    from unittest.mock import AsyncMock

    from inkflow.api.routers.books import get_planner_service
    from inkflow.domain.ports.llm_client import ChatResponse

    await _seed_project(db_session, model="deepseek/deepseek-v4-flash")
    svc = get_planner_service(db_session)
    assert svc is not None
    svc._llm_client = AsyncMock()
    svc._llm_client.chat.return_value = ChatResponse(
        content=_json.dumps(
            {
                "questions": [
                    {
                        "id": "q1",
                        "text": "题材：悬疑为主还是悬疑+科幻混合？",
                        "template": "悬疑为主，但加入 ___ 元素",
                        "kind": "general",
                    },
                    {
                        "id": "q2",
                        "text": "篇幅：预计多少字？",
                        "template": "约 ___ 字",
                        "kind": "general",
                    },
                    {
                        "id": "q3",
                        "text": "主题：能否一句话描述主题？",
                        "template": "主题是 ___",
                        "kind": "general",
                    },
                ],
                "confirmed_items": [],
                "conflicts": [],
            },
            ensure_ascii=False,
        ),
        model="test",
    )

    session = await svc.start(SEED_PROJECT_ID, "写一本关于时间旅者的悬疑小说")

    assert session.status == "drafting"
    assert len(session.asked_questions) == 3
    assert all(q.get("kind") == "general" for q in session.asked_questions)
    svc._llm_client.chat.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.api
async def test_get_planner_service_context_getter_exception(db_session, monkeypatch):
    """_project_context_getter 异常 → 返回空串（books.py except 分支）。

    #977 迁移（§0/§4 RED-2）：seed 项目行（config.model 非空）+ start 用 seed 项目
    id → 修复后 project_repo.get 命中 → resolve_model 走项目模型 → chat 仍被调
    （保持 `chat.await_count == 2` 锁「必答项缺失 → 重试 1 次」语义不变）。
    """
    import json as _json
    from unittest.mock import AsyncMock

    from inkflow.api.routers.books import get_planner_service
    from inkflow.domain.ports.llm_client import ChatResponse

    async def _boom(*args, **kwargs):
        raise RuntimeError("repo down")

    monkeypatch.setattr(
        "inkflow.infrastructure.database.repositories.outline_repo.SQLiteOutlineRepository.list",
        _boom,
    )

    await _seed_project(db_session, model="deepseek/deepseek-v4-flash")
    svc = get_planner_service(db_session)
    svc._llm_client = AsyncMock()
    svc._llm_client.chat.return_value = ChatResponse(
        content=_json.dumps(
            {
                "questions": [
                    {
                        "id": "q1",
                        "text": "题材：悬疑为主还是悬疑+科幻混合？",
                        "template": "悬疑为主，但加入 ___ 元素",
                        "kind": "general",
                    }
                ],
                "confirmed_items": [],
                "conflicts": [],
            },
            ensure_ascii=False,
        ),
        model="test",
    )

    session = await svc.start(SEED_PROJECT_ID, "写一本关于时间旅者的悬疑小说")

    assert session.status == "drafting"
    # LLM 返回 1 问缺必答项 → 重试 1 次 → 仍缺 → 服务端补问 → 题材/篇幅/主题 齐备
    assert len(session.asked_questions) == 3
    assert svc._llm_client.chat.await_count == 2  # 必答项缺失 → 重试 1 次


@pytest.mark.asyncio
@pytest.mark.api
async def test_get_planner_service_real_assembly_complete(db_session):
    """真实装配 + mock LLM：完整访谈 → confirm → 装配闭包 _outline_service/
    _character_service 真实落库（books.py 125/134 行覆盖）。

    #977 迁移（§0/§4 RED-2）：seed 项目行（config.model 非空）→ 修复后
    project_repo.get(seed) 命中 → resolve 项目模型 → chat 仍被调（完整访谈链不破）。
    注：project_id 用小值 uuid.UUID(int=1)（outline/character 表 project_id
    为 SQLite INTEGER，uuid4 128 位溢出，F48 已知坑）。
    """
    import json as _json
    from unittest.mock import AsyncMock

    from inkflow.api.routers.books import get_planner_service
    from inkflow.domain.ports.llm_client import ChatResponse

    await _seed_project(db_session, model="deepseek/deepseek-v4-flash")
    svc = get_planner_service(db_session)
    llm = AsyncMock()
    llm.chat.side_effect = [
        ChatResponse(
            content=_json.dumps(
                {
                    "questions": [
                        {
                            "id": "q1",
                            "text": "题材：悬疑为主还是悬疑+科幻混合？",
                            "template": "悬疑为主，但加入 ___ 元素",
                            "kind": "general",
                        },
                        {
                            "id": "q2",
                            "text": "篇幅：预计多少字？",
                            "template": "约 ___ 字",
                            "kind": "general",
                        },
                        {
                            "id": "q3",
                            "text": "主题：能否一句话描述主题？",
                            "template": "主题是 ___",
                            "kind": "general",
                        },
                    ],
                    "confirmed_items": [],
                    "conflicts": [],
                },
                ensure_ascii=False,
            ),
            model="test",
        ),
        ChatResponse(
            content=_json.dumps(
                {
                    "questions": [],
                    "confirmed_items": [
                        {"key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user"},
                        {"key": "篇幅", "value": "10 万字", "source": "user"},
                        {"key": "主题", "value": "时间旅者自我救赎", "source": "user"},
                    ],
                    "conflicts": [],
                },
                ensure_ascii=False,
            ),
            model="test",
        ),
    ]
    svc._llm_client = llm

    session = await svc.start(SEED_PROJECT_ID, "写一本关于时间旅者的悬疑小说")
    r1 = await svc.respond(
        session.id,
        {"q1": "悬疑为主", "q2": "约 10 万字", "q3": "主题是自我救赎"},
    )
    assert r1.confirming is True

    r2 = await svc.respond(session.id, {}, confirm=True)

    assert r2.completed is True
    assert r2.writing_plan is not None
    assert r2.writing_plan.status == "ready"
    assert r2.writing_plan.root_outline_id is not None  # _outline_service 真实落库
    assert r2.writing_plan.character_ids  # _character_service 真实落库


@pytest.mark.asyncio
@pytest.mark.api
async def test_get_book_service_real_assembly_callbacks(db_session):
    """真实装配 BookService 装配回调：content_checker/project_config_getter/
    outline 适配器真实执行（books.py 172-205 行覆盖，空库 → False/None/空）。"""
    from inkflow.api.routers.books import get_book_service

    svc = get_book_service(db_session)
    assert svc is not None
    # 安全阀内容检查：空库 → chapter None → False（私有属性 _content_checker）
    checker = getattr(svc, "_content_checker", None)
    assert checker is not None
    assert await checker(uuid.UUID(int=1)) is False
    # 项目级上限：空库 → project None → None（_project_config_getter）
    getter = getattr(svc, "_project_config_getter", None)
    assert getter is not None
    assert await getter(uuid.UUID(int=1)) is None
    # _OutlineListAdapter.list：UUID → int 适配（空库 → ([], 0)）
    outline_repo = getattr(svc, "_outline_repo", None)
    if outline_repo is not None:
        outlines, total = await outline_repo.list(uuid.UUID(int=1))
        assert outlines == [] and total == 0


# ── #977 RED-2 轨：真实装配 model 全链 + 空链 WARN 模板 ─────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_get_planner_service_real_assembly_passes_project_model(db_session):
    """【R】#977 真实装配全链锁 model 传递：books 装配 → PlannerService →
    LLM client chat 收到项目模型。

    契约节 #977 §0-①/§2/§4 RED-2a：get_planner_service 修复后注入
    project_repo=SQLiteProjectRepository(db) + llm_default_model=config.llm_default_model；
    seed 项目 config.model 非空 → resolve_model(None, 项目模型, 全局默认) = 项目模型
    → chat(model=项目模型)。
    RED：planner_service.py:598 chat 现无 model= 关键字 → await_args.kwargs 缺
    "model" 键 → KeyError（断言 kwargs 缺失）。
    """
    import json as _json
    from unittest.mock import AsyncMock

    from inkflow.api.routers.books import get_planner_service
    from inkflow.domain.ports.llm_client import ChatResponse

    await _seed_project(db_session, model="deepseek/deepseek-v4-flash")
    svc = get_planner_service(db_session)
    assert svc is not None
    svc._llm_client = AsyncMock()
    svc._llm_client.chat.return_value = ChatResponse(
        content=_json.dumps(
            {
                "questions": [
                    {
                        "id": "q1",
                        "text": "题材：悬疑为主还是悬疑+科幻混合？",
                        "template": "悬疑为主，但加入 ___ 元素",
                        "kind": "general",
                    },
                    {
                        "id": "q2",
                        "text": "篇幅：预计多少字？",
                        "template": "约 ___ 字",
                        "kind": "general",
                    },
                    {
                        "id": "q3",
                        "text": "主题：能否一句话描述主题？",
                        "template": "主题是 ___",
                        "kind": "general",
                    },
                ],
                "confirmed_items": [],
                "conflicts": [],
            },
            ensure_ascii=False,
        ),
        model="test",
    )

    session = await svc.start(SEED_PROJECT_ID, "写一本关于时间旅者的悬疑小说")

    assert session.status == "drafting"
    assert svc._llm_client.chat.await_args.kwargs["model"] == "deepseek/deepseek-v4-flash"


@pytest.mark.asyncio
@pytest.mark.api
async def test_get_planner_service_empty_chain_warns_template(db_session, monkeypatch):
    """【R】#977 两级皆空 → 不调 chat + 一次 WARN + 模板兜底（零 ERROR）。

    契约节 #977 §0-①/§4 RED-2b：seed 项目 config.model=None + 全局默认空
    （monkeypatch config.llm_default_model=""）→ resolve_model(None, None, "")
    → None → 一次 loguru WARNING「未配置默认模型，访谈使用模板题库」+ 不调 chat
    + return None → ROUND1 模板兜底。
    RED：planner_service.py 现无 model 解析/无 WARN → chat 被调（assert_not_awaited
    失败）+ sink 捕获 0 条 WARN（len==1 失败）。
    """
    from unittest.mock import AsyncMock

    from loguru import logger

    from inkflow.api.routers.books import get_planner_service
    from inkflow.core.config import config
    from inkflow.domain.ports.llm_client import ChatResponse

    await _seed_project(db_session, model=None)
    monkeypatch.setattr(config, "llm_default_model", "", raising=False)

    svc = get_planner_service(db_session)
    assert svc is not None
    svc._llm_client = AsyncMock()
    svc._llm_client.chat.return_value = ChatResponse(content="{}", model="test")

    records: list = []
    sink_id = logger.add(lambda m: records.append(m), level="WARNING", format="{message}")
    try:
        session = await svc.start(SEED_PROJECT_ID, "写一本关于时间旅者的悬疑小说")
    finally:
        logger.remove(sink_id)

    assert session.status == "drafting"
    # 两级皆空 → 不调 chat → ROUND1 模板 3 题兜底（asked_questions 保持默认模板）
    assert len(session.asked_questions) == 3
    assert session.asked_questions == ROUND1_QUESTIONS
    svc._llm_client.chat.assert_not_awaited()

    warnings = [r for r in records if r.record["level"].name == "WARNING"]
    errors = [r for r in records if r.record["level"].name == "ERROR"]
    assert len(warnings) == 1
    assert "未配置默认模型，访谈使用模板题库" in warnings[0].record["message"]
    assert errors == []
