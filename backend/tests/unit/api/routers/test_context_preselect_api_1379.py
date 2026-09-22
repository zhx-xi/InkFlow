"""#1379 RED 契约：预选端点 POST /api/v1/context/preselect（真实 DB + mock LLM）.

端到端形态（镜像 test_outline_862.py 的 HTTP 全链路）：真 in-memory SQLite
（角色 / 世界观 / 伏笔 / 章纲落库）→ 真实 `get_context_service` 组装链
（真源 + 真仓储 + 真 LlmContextPreselector + 真 prompt 模板）→ 仅 LLM 客户端
`LangChainLLMClient.chat` 被 mock（mock 边界在 LLM，不在服务层）。

契约：
  1. 有大纲 + LLM 返回三类子集 → 200 + mode="agent" + 子集 id（≠ 全量）
  2. 无大纲 → 200 + mode="fallback" + 三类**全量** id，且 LLM 零调用（不浪费往返）
  3. LLM 抛错 → 200 + mode="fallback" + 全量（前端据此回退全选）
  4. writing_requirements 空白 → 422（Pydantic min_length，与 assemble 同口径）
  5. 可证伪自证：候选集过滤被移除时，用例 1 的「子集 == [CHAR_A]」断言必 FAIL
     （LLM 返回的脏 id 会原样透传）

依据: issue #1379（方案 A，一次 LLM 调用）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkflow.api.deps import get_db
from inkflow.api.routers.context import router
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.character import CharacterORM
from inkflow.infrastructure.database.models.foreshadowing import ForeshadowingORM
from inkflow.infrastructure.database.models.outline import OutlineORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.world import WorldSettingORM

PROJECT_ID = uuid.UUID(int=1)
CHAPTER_ID = uuid.UUID(int=7)
CHAR_A = uuid.UUID(int=31)
CHAR_B = uuid.UUID(int=32)
WORLD_A = uuid.UUID(int=41)
WORLD_B = uuid.UUID(int=42)
FORE_A = uuid.UUID(int=51)
FORE_B = uuid.UUID(int=52)

MODEL = "openai/gpt-4o"

_LLM_CHAT_PATH = "inkflow.infrastructure.llm.langchain_client.LangChainLLMClient.chat"


def _session_factory(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def _seed(session: AsyncSession, *, with_outline: bool = True) -> None:
    """真 DB 落库：项目 + 章 + 角色×2 + 世界观×2（根 + 子，避根单例约束）+ 伏笔×2 + 章纲."""
    session.add(ProjectORM(id=PROJECT_ID.int, name="预选契约项目", config={}))
    session.add(
        ChapterORM(
            id=CHAPTER_ID.int,
            project_id=PROJECT_ID.int,
            title="第一章 初入山门",
            content="",
            status="draft",
            word_count=0,
            order_index=1,
        )
    )
    session.add(
        CharacterORM(id=CHAR_A.int, project_id=PROJECT_ID.int, name="角色甲", brief="少年剑客")
    )
    session.add(
        CharacterORM(id=CHAR_B.int, project_id=PROJECT_ID.int, name="角色乙", brief="门派长老")
    )
    session.add(
        WorldSettingORM(
            id=WORLD_A.int,
            project_id=PROJECT_ID.int,
            name="山门",
            category="location",
            content="北方剑宗",
        )
    )
    session.add(
        WorldSettingORM(
            id=WORLD_B.int,
            project_id=PROJECT_ID.int,
            parent_id=WORLD_A.int,
            name="后山禁地",
            category="location",
            content="后山封印",
        )
    )
    session.add(
        ForeshadowingORM(
            id=FORE_A.int,
            project_id=PROJECT_ID.int,
            title="玉佩来历",
            description="玉佩暗藏身世线索",
            priority=5,
            status="open",
            location="第一章",
        )
    )
    session.add(
        ForeshadowingORM(
            id=FORE_B.int,
            project_id=PROJECT_ID.int,
            title="长老旧伤",
            description="长老旧伤复发伏笔",
            priority=3,
            status="open",
            location="第一章",
        )
    )
    if with_outline:
        session.add(
            OutlineORM(
                id=101,
                project_id=PROJECT_ID.int,
                name="第一章 初入山门",
                description="少年甲拜入乙门下，卷入玉佩之谜",
                sort_order=1,
                level="chapter",
                chapter_id=CHAPTER_ID.int,
            )
        )
    await session.commit()


def _app(session: AsyncSession) -> FastAPI:
    """独立 app + get_db override（yield 真 session）→ 走真实 service 组装链."""
    app = FastAPI()
    app.include_router(router)

    async def _override() -> AsyncGenerator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db] = _override
    return app


def _body(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_id": str(PROJECT_ID),
        "chapter_id": str(CHAPTER_ID),
        "model": MODEL,
        "writing_requirements": "续写第一章",
    }
    payload.update(overrides)
    return payload


def _llm_returning(payload: dict[str, list[str]]) -> AsyncMock:
    """mock LangChainLLMClient.chat → 返回给定 JSON 文本。"""
    return AsyncMock(
        return_value=ChatResponse(content=json.dumps(payload, ensure_ascii=False), model=MODEL)
    )


# ── 1 · 子集返回（真实 DB 全链路） ──────────────────────────────────────


@pytest.mark.asyncio
async def test_preselect_returns_subset_with_real_db(test_engine) -> None:
    async with _session_factory(test_engine)() as session:
        await _seed(session)
        app = _app(session)
        chat = _llm_returning(
            {
                "character_ids": [str(CHAR_A)],
                "world_ids": [str(WORLD_B)],
                "foreshadowing_ids": [],
            }
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch(_LLM_CHAT_PATH, new=chat):
                resp = await client.post("/api/v1/context/preselect", json=_body())

        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "agent"
        assert body["character_ids"] == [str(CHAR_A)]
        assert body["world_ids"] == [str(WORLD_B)]
        assert body["foreshadowing_ids"] == []
        assert chat.await_count == 1


# ── 2 · 无大纲 → 回退全选（零 LLM 调用） ─────────────────────────────────


@pytest.mark.asyncio
async def test_preselect_falls_back_without_outline(test_engine) -> None:
    async with _session_factory(test_engine)() as session:
        await _seed(session, with_outline=False)
        app = _app(session)
        chat = _llm_returning({"character_ids": [], "world_ids": [], "foreshadowing_ids": []})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch(_LLM_CHAT_PATH, new=chat):
                resp = await client.post("/api/v1/context/preselect", json=_body())

        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "fallback"
        assert sorted(body["character_ids"]) == sorted([str(CHAR_A), str(CHAR_B)])
        assert sorted(body["world_ids"]) == sorted([str(WORLD_A), str(WORLD_B)])
        assert sorted(body["foreshadowing_ids"]) == sorted([str(FORE_A), str(FORE_B)])
        assert chat.await_count == 0


# ── 3 · LLM 失败 → 回退全选 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preselect_falls_back_on_llm_error(test_engine) -> None:
    async with _session_factory(test_engine)() as session:
        await _seed(session)
        app = _app(session)
        chat = AsyncMock(side_effect=RuntimeError("provider down"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch(_LLM_CHAT_PATH, new=chat):
                resp = await client.post("/api/v1/context/preselect", json=_body())

        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "fallback"
        assert sorted(body["character_ids"]) == sorted([str(CHAR_A), str(CHAR_B)])


# ── 4 · 空写作要求 → 422 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preselect_blank_requirements_422(test_engine) -> None:
    async with _session_factory(test_engine)() as session:
        await _seed(session)
        app = _app(session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/context/preselect", json=_body(writing_requirements="")
            )

        assert resp.status_code == 422
