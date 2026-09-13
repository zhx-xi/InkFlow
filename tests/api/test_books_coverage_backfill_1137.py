"""#1137 覆盖率补齐 —— books.py 装配期闭包经公开面驱动。

权威来源：
- specs/f44-book-orchestrator/spec.md §3.1/§3.2（planner 项目上下文摘要、/runs 预检）
- specs/f56-volume-outline-link（#976 D3：outline/章 id → 写作卷 UUID 解析）

公开面（不含私有成员/闭包直调）：
- 依赖装配函数 get_planner_service / get_book_service（FastAPI 依赖）
- PlannerService.start / BookService.write_book（公开服务方法）
- POST /api/v1/agent/books/runs 端点（ASGITransport + dependency_overrides）
- 路由处理函数 start_run（同步 TestClient 会跑在独立线程，直接 await 等价调用同一公开契约）
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.api.routers.books import (
    BookRunRequest,
    get_book_service,
    get_planner_service,
    start_run,
)
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM
from inkflow.infrastructure.database.models.character import CharacterORM
from inkflow.infrastructure.database.models.outline import OutlineORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.writing_plan import WritingPlanORM
from inkflow.infrastructure.database.repositories.project_repo import SQLiteProjectRepository
from inkflow.infrastructure.repositories.book_repository import SQLiteBookRepository

BASE = "/api/v1/agent/books"

SEED_PROJECT_ID = uuid.UUID(int=1)
"""projects.id 为 INTEGER 主键 → 领域 id = uuid.UUID(int=orm.id)。"""


@pytest.fixture
def client(monkeypatch):
    """无 token 模式 AsyncClient（INKFLOW_SERVER_TOKEN 未设置直通）。"""
    monkeypatch.delenv("INKFLOW_SERVER_TOKEN", raising=False)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _reset_book_pipelines(monkeypatch):
    """隔离 books.py 模块级 pipeline 单例（复用会绑到已释放的测试 session）。"""
    monkeypatch.setattr(
        "inkflow.api.routers.books._book_volume_pipeline", None, raising=False
    )
    monkeypatch.setattr(
        "inkflow.api.routers.books._book_agentic_pipeline", None, raising=False
    )


def _provider(db_session):
    """dependency_overrides：注入真实装配的 BookService（走 _build_book_service 全链）。"""

    def _override():
        return get_book_service(db_session)

    return _override


async def _seed_project(db_session) -> None:
    db_session.add(
        ProjectORM(
            id=SEED_PROJECT_ID.int,
            name="覆盖补齐项目",
            config={"model": "deepseek/deepseek-v4-flash"},
        )
    )
    await db_session.commit()


async def _seed_plan(db_session, plan_id: uuid.UUID) -> None:
    db_session.add(
        WritingPlanORM(
            id=str(plan_id),
            project_id=str(SEED_PROJECT_ID),
            title="覆盖补齐计划",
            status="ready",
        )
    )
    await db_session.commit()


def _fake_llm(content: str) -> MagicMock:
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=ChatResponse(content=content, model="test"))
    return llm


def _questions_payload() -> str:
    return json.dumps(
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
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_start_builds_project_context_from_outlines_and_characters(
    db_session, monkeypatch
):
    """F44 §5.1：planner 项目设定摘要 = 已落库大纲/角色拼接（含/不含 description 两分支）。"""
    await _seed_project(db_session)
    db_session.add_all(
        [
            OutlineORM(
                id=11,
                project_id=SEED_PROJECT_ID.int,
                name="第一卷大纲",
                description="开篇提要",
                level="volume",
                sort_order=0,
            ),
            OutlineORM(
                id=12,
                project_id=SEED_PROJECT_ID.int,
                name="孤章大纲",
                description="",
                level="chapter",
                sort_order=1,
            ),
            OutlineORM(
                id=13,
                project_id=SEED_PROJECT_ID.int,
                name="",
                description="未命名大纲",
                level="chapter",
                sort_order=2,
            ),
            CharacterORM(
                id=21,
                project_id=SEED_PROJECT_ID.int,
                name="林晚",
                brief="冷静的时间旅人",
            ),
            CharacterORM(
                id=22,
                project_id=SEED_PROJECT_ID.int,
                name="无名氏",
                brief="",
            ),
            CharacterORM(
                id=23,
                project_id=SEED_PROJECT_ID.int,
                name="",
                brief="空名不注入",
            ),
        ]
    )
    await db_session.commit()

    llm = _fake_llm(_questions_payload())
    monkeypatch.setattr(
        "inkflow.infrastructure.llm.langchain_client.LangChainLLMClient",
        lambda *args, **kwargs: llm,
    )

    svc = get_planner_service(db_session)
    session = await svc.start(SEED_PROJECT_ID, "写一本关于时间旅行者的悬疑小说")

    assert session.status == "drafting"
    assert len(session.asked_questions) == 3
    messages = llm.chat.await_args.args[0]
    joined = "\n".join(str(message["content"]) for message in messages)
    # 有 description / brief → 名称+括注；无 description / brief → 仅名称（books.py 条件分支）
    assert "大纲：第一卷大纲（开篇提要）" in joined
    assert "大纲：孤章大纲" in joined
    assert "大纲：孤章大纲（" not in joined
    assert "角色：林晚（冷静的时间旅人）" in joined
    assert "角色：无名氏" in joined
    assert "角色：无名氏（" not in joined
    assert "未命名大纲" not in joined  # 空名条目不进摘要
    assert "空名不注入" not in joined  # 空名角色不进摘要


@pytest.mark.asyncio
@pytest.mark.api
async def test_start_run_falls_through_when_plan_lookup_raises(
    client, db_session, monkeypatch
):
    """#929：/runs 入口预检 plan 查询异常 → 吞异常继续预检，凭据按全局默认解析（不 500）。"""
    plan_id = uuid.uuid4()
    calls = {"n": 0}

    async def _flaky_get_writing_plan(self, plan_id_arg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("writing plan repo down")
        return

    monkeypatch.setattr(
        SQLiteBookRepository, "get_writing_plan", _flaky_get_writing_plan
    )
    resolve = MagicMock(return_value=("model", "key", "url"))
    monkeypatch.setattr("inkflow.api._llm_resolver.resolve_llm_credentials", resolve)
    app.dependency_overrides[get_book_service] = _provider(db_session)
    try:
        resp = await client.post(
            f"{BASE}/runs", json={"writing_plan_id": str(plan_id), "mode": "static"}
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
    assert "计划不存在" in resp.json()["detail"]
    # cfg 解析失败 → project_model=None（凭据解析兜底全局默认，不阻断预检）
    assert resolve.call_args.kwargs["project_model"] is None


@pytest.mark.asyncio
@pytest.mark.api
async def test_start_run_precheck_survives_project_config_lookup_failure(
    db_session, monkeypatch
):
    """端到端预检：项目配置读取异常被吞 → cfg=None → 无章快路径返回 completed（非 500）。"""
    planned_plan_id = uuid.uuid4()
    await _seed_project(db_session)
    await _seed_plan(db_session, planned_plan_id)

    async def _boom_get(self, project_id):
        raise RuntimeError("project repo down")

    monkeypatch.setattr(SQLiteProjectRepository, "get", _boom_get)
    resolve = MagicMock(return_value=("model", "key", "url"))
    monkeypatch.setattr("inkflow.api._llm_resolver.resolve_llm_credentials", resolve)

    result = await start_run(
        BookRunRequest(writing_plan_id=planned_plan_id, mode="static"),
        get_book_service(db_session),
    )

    assert result == {"run_id": str(planned_plan_id), "status": "completed"}
    assert resolve.call_args.kwargs["project_model"] is None


@pytest.mark.asyncio
@pytest.mark.api
async def test_write_book_resolves_draft_volume_from_outline_and_chapter(
    db_session, monkeypatch
):
    """#976 D3：草稿兜底卷解析 —— 章 id → 写作卷 UUID；无映射/越界 → None。"""
    await _seed_project(db_session)
    plan_id = uuid.uuid4()
    db_session.add(VolumeORM(id=3, project_id=SEED_PROJECT_ID.int, title="第一卷"))
    db_session.add(
        ChapterORM(id=20, project_id=SEED_PROJECT_ID.int, volume_id=3, title="第一章")
    )
    db_session.add(
        OutlineORM(
            id=11,
            project_id=SEED_PROJECT_ID.int,
            name="卷大纲",
            level="volume",
            volume_id=3,
        )
    )
    db_session.add(
        OutlineORM(
            id=10,
            project_id=SEED_PROJECT_ID.int,
            name="第一章大纲",
            level="chapter",
            chapter_id=20,
            sort_order=0,
        )
    )
    await _seed_plan(db_session, plan_id)

    monkeypatch.setattr(
        "inkflow.api._llm_resolver.resolve_llm_credentials",
        lambda *args, **kwargs: ("model", "key", "url"),
    )
    seen: dict = {}

    def _fake_writer(**kwargs):
        seen["deps"] = kwargs["deps"]
        agent = MagicMock()
        # 未调用 save_draft 的 agent 输出 → 触发服务层兜底建草稿（#975/#976 D3）
        agent.invoke = AsyncMock(
            return_value={"messages": [{"type": "ai", "content": "第一章正文内容"}]}
        )
        return agent

    monkeypatch.setattr(
        "inkflow.infrastructure.agent.agentic_writer.build_agentic_writer", _fake_writer
    )

    svc = get_book_service(db_session)
    result = await svc.write_book(plan_id)

    assert result == {"run_id": str(plan_id), "status": "completed"}
    volume_lookup = seen["deps"].volume_lookup
    # outline（level=volume）→ 所属写作卷 UUID
    assert await volume_lookup(SEED_PROJECT_ID, uuid.UUID(int=11)) == str(uuid.UUID(int=3))
    # 章 id → 所属写作卷 UUID（str 形态，与前端 Volume.id 一致）
    assert await volume_lookup(SEED_PROJECT_ID, uuid.UUID(int=20)) == str(uuid.UUID(int=3))
    # 无 id → None（未分组不落卷）
    assert await volume_lookup(SEED_PROJECT_ID, None) is None
    # 无映射行 → None
    assert await volume_lookup(SEED_PROJECT_ID, uuid.UUID(int=999999)) is None
    # uuid4 随机值溢出 SQLite INTEGER 主键 → None（不做越界查询）
    assert await volume_lookup(SEED_PROJECT_ID, uuid.UUID(int=2**63)) is None

