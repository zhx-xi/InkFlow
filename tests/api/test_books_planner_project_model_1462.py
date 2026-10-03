"""#1462 全链路（HTTP）契约：仅配项目级模型 → 访谈走 LLM → confirm 走通；重复访谈幂等。

════════════════════════════════════════════════════════════════════
复现 #1462 的原始场景（真实 repo / 真实 OutlineService / 真实会话仓储，
仅 LLM 客户端为替身；全局默认模型强制为空 → 只剩项目级 config.model 可用）：

  当前实现 `_generate_questions` 传 `session.project_id.int` → 真实
  `SQLiteProjectRepository.get` 的 `require_uuid_pk` 抛 TypeError → 被
  `except Exception` 吞 → 项目级模型恒空 → 降级模板题库 + `confirming`
  永不置位 → `confirm` 恒 422。

实现契约（GREEN 必须满足）：
  1. start 返回的 questions 必须是 LLM 动态提问（非 ROUND1 模板题）——
     证明「项目」一级在 resolve_model 中真的非空；
  2. respond 后 `confirming=true` → confirm 返回 200 + `writing_plan.root_outline_id` 非空；
  3. 同一项目同一句话的第二次访谈（新会话）同样能 start/respond/confirm 全绿
     —— 覆盖 #1463「同名总纲冲突」的原始复现路径。

════════════════════════════════════════════════════════════════════
用例分组与预期（RED 阶段；实现者不得改本文件）

【新增契约】当前必须 FAIL：
  F-1 test_full_chain_with_only_project_level_model
  F-2 test_second_interview_same_project_and_one_liner_succeeds

若某条实际状态与预期不符，**如实报告，不要改断言凑数**。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.api.routers.books import get_planner_service
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.domain.services.character_service import CharacterService
from inkflow.domain.services.outline_service import OutlineService
from inkflow.domain.services.planner_service import PlannerService
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.character_repo import (
    SQLiteCharacterRepository,
)
from inkflow.infrastructure.database.repositories.outline_repo import SQLiteOutlineRepository
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.repositories.book_repository import SQLiteBookRepository

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/agent/books"
PROJECT_MODEL = "project/model"
ONE_LINER = "写一本关于时间旅者的悬疑小说"
PROJECT_ROW_ID = 900101
"""ORM 主键用小的确定性 int（uuid4().int 会溢出 SQLite INT64）。"""
PROJECT_ID = uuid.UUID(int=PROJECT_ROW_ID)

_LLM_QUESTIONS = [
    {
        "id": "llm-q1",
        "text": "题材：悬疑为主还是混合？",
        "template": "以 ___ 为主",
        "kind": "general",
    },
    {
        "id": "llm-q2",
        "text": "篇幅：预计多少字？",
        "template": "约 ___ 字",
        "kind": "general",
    },
    {
        "id": "llm-q3",
        "text": "主题：一句话描述主题？",
        "template": "主题是 ___",
        "kind": "general",
    },
]
_ANSWERS = {
    "llm-q1": "悬疑为主，加入时间悖论",
    "llm-q2": "约 30 万字",
    "llm-q3": "主题是时间悖论",
}


class _FakeLLMClient:
    """LLMClientProtocol 替身：记录每次调用的 model，返回结构化访谈 JSON。"""

    def __init__(self) -> None:
        self.models: list[str | None] = []

    async def chat(self, messages: object, *, model: str | None = None, **kwargs: object):
        self.models.append(model)
        payload = json.dumps(
            {"questions": _LLM_QUESTIONS, "confirmed_items": [], "conflicts": []},
            ensure_ascii=False,
        )
        return ChatResponse(content=payload, model=model or "unknown")


@pytest.fixture
def client(monkeypatch):
    """无 token 模式 AsyncClient（INKFLOW_SERVER_TOKEN 未设置直通）。"""
    monkeypatch.delenv("INKFLOW_SERVER_TOKEN", raising=False)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def project_row(db_session):
    """预置项目行：**只配项目级** config.model（全局默认模型强制为空）。"""
    db_session.add(
        ProjectORM(
            id=PROJECT_ROW_ID,
            name="端到端项目",
            tags=["奇幻"],
            language="zh-CN",
            target_words=100000,
            config={"model": PROJECT_MODEL},
        )
    )
    await db_session.commit()
    return PROJECT_ROW_ID


@pytest_asyncio.fixture
async def real_planner(db_session, override_get_db):
    """真实装配的 PlannerService（镜像 api/routers/books.get_planner_service）。"""
    fake = _FakeLLMClient()
    outline_repo = SQLiteOutlineRepository(db_session)
    character_repo = SQLiteCharacterRepository(db_session)

    async def _outline_service(
        project_id: uuid.UUID, name: str, description: str, level: str
    ) -> object:
        return await OutlineService(repository=outline_repo).create_outline(
            project_id=project_id, name=name, description=description, level=level
        )

    async def _character_service(
        project_id: uuid.UUID, name: str, extra: dict | None = None
    ) -> object:
        from inkflow.domain.models.character import CharacterCreate

        create = CharacterCreate(project_id=project_id, name=name, extra=extra)
        return await CharacterService(repository=character_repo).create_character(
            project_id=create.project_id, name=create.name, extra=create.extra
        )

    async def _project_context_getter(project_id: uuid.UUID) -> str:
        return ""

    svc = PlannerService(
        repo=SQLiteBookRepository(db_session),
        outline_service=_outline_service,
        character_service=_character_service,
        llm_client=fake,
        project_context_getter=_project_context_getter,
        prompt_manager=None,
        outline_repo=outline_repo,
        character_repo=character_repo,
        project_repo=SQLiteProjectRepository(db_session),
        llm_default_model="",  # 全局为空：只有项目级模型可用（#1462 原始场景）
    )

    async def _override() -> PlannerService:
        return svc

    app.dependency_overrides[get_planner_service] = _override
    yield svc, fake
    app.dependency_overrides.pop(get_planner_service, None)


async def _run_interview(client: AsyncClient) -> dict:
    """start → respond → confirm 三步全链路，返回各步响应体（断言内联在各用例）。"""
    resp = await client.post(
        f"{BASE}/planner", json={"project_id": str(PROJECT_ID), "one_liner": ONE_LINER}
    )
    assert resp.status_code == 201, resp.text[:400]
    started = resp.json()
    sid = started["session_id"]

    resp = await client.post(f"{BASE}/planner/{sid}/respond", json={"answers": dict(_ANSWERS)})
    assert resp.status_code == 200, resp.text[:400]
    answered = resp.json()

    resp = await client.post(f"{BASE}/planner/{sid}/respond", json={"confirm": True})
    assert resp.status_code == 200, resp.text[:400]
    return {"started": started, "answered": answered, "confirmed": resp.json(), "sid": sid}


async def test_full_chain_with_only_project_level_model(client, project_row, real_planner) -> None:
    """【新增契约 F-1】仅项目级模型 → LLM 动态提问 → confirming=true → confirm 200。"""
    _svc, fake = real_planner

    result = await _run_interview(client)

    assert [q["id"] for q in result["started"]["questions"]] == ["llm-q1", "llm-q2", "llm-q3"], (
        "题面必须是 LLM 动态提问（落模板题库 = 项目级模型未生效）"
    )
    assert result["answered"]["confirming"] is True, "必答项齐备后必须进入末尾总体确认"
    assert result["confirmed"]["completed"] is True
    plan = result["confirmed"]["writing_plan"]
    assert plan is not None and plan["root_outline_id"] is not None
    assert fake.models, "LLM 必须被调用"
    assert set(fake.models) == {PROJECT_MODEL}, "每次调用都必须带项目级模型"


async def test_second_interview_same_project_and_one_liner_succeeds(
    client, project_row, real_planner
) -> None:
    """【新增契约 F-2】同项目同一句话的第二次访谈 → 全链路仍成功（#1463 原始复现）。"""
    first = await _run_interview(client)
    second = await _run_interview(client)

    assert first["confirmed"]["completed"] is True
    assert second["started"]["session_id"] != first["started"]["session_id"]
    assert second["answered"]["confirming"] is True
    assert second["confirmed"]["completed"] is True
    assert (
        second["confirmed"]["writing_plan"]["root_outline_id"]
        == first["confirmed"]["writing_plan"]["root_outline_id"]
    ), "同名总纲必须复用既有行（不得新建第二个）"
