"""#1476 集成契约测试 — 写作轨检索工具的**真实**项目上下文（真 SQLite + 真 service + 真装配）.

背景：issue #1476 的 `write next --mode agentic` 实测表里 4 个工具 3 个返回
`{"ok": false, "error": "项目不存在"}`（第 4 个 `get_prior_summary` 假绿返回 `[]`），
Agent 遂盲写自造人名地名。根因 = `build_agentic_writer` 调 `build_reader_tools` 漏传
`project_id`（闭包绑定入口），单元轨由
`tests/unit/infrastructure/agent/test_agentic_writer_project_binding_1476.py` 锁定。

本文件补「真库」层证据（单元轨是 mock service，仅证绑定值传递正确）：
  - 种子 = 真实 ProjectORM + 经**真实 service/getter** 建 角色 / 世界观 / 伏笔 + 章 + 摘要
  - 装配 = 真实 `build_agentic_writer`（只 patch `build_deep_agent`，不触 LLM）
  - 断言 = issue 表格里的 4 个工具逐个返回 `{"ok": true, …}` 且数据来自**本项目**
    （跨项目隔离：同库另一项目的同名实体不得出现）

seed 形态镜像 tests/integration/test_draft_confirm_http_assembly_988.py：
项目/章主键取小值 id（int ↔ uuid.UUID(int=X)），防随机 uuid4 溢出 SQLite INTEGER 列。

中性占位名（不引任何真实设定素材）。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api.deps import (
    get_character_service,
    get_foreshadowing_service,
    get_summary_service,
    get_world_service,
)
from inkflow.core.database import Base
from inkflow.domain.models.foreshadowing import ForeshadowingCreate
from inkflow.infrastructure.agent.agentic_writer import AgenticWriterDeps, build_agentic_writer
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.summary_repo import SQLiteSummaryRepository

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# 小值 UUID 惯例：本项目 id=7（内部 id=8 = 另一个项目）
PROJECT_ID = uuid.UUID(int=7)
OTHER_PROJECT_ID = uuid.UUID(int=8)
CHAPTER_UUID = uuid.UUID(int=101)
CHAPTER_ID_INT = 101

MODEL = "deepseek/deepseek-v4-flash"  # 伪契约同步：mock 参数非语义断言
API_KEY = "test-key"
BASE_URL = "https://example.test/v1"
BASE_PROMPT = "你是章节写手，负责按大纲撰写正文。"

CHARACTER_NAME = "角色甲"  # 本项目
OTHER_CHARACTER_NAME = "角色乙"  # 另一个项目（隔离探针）
WORLD_SETTING_NAME = "设定乙"
WORLD_CATEGORY = "地理设定"
FORESHADOWING_TITLE = "伏笔丙"
PRIOR_SUMMARY = "前文摘要内容：主角初入山门。"

# issue #1476 表格里被实际调用的 4 个工具（项目域 + 摘要域）
ISSUE_TOOLS = [
    "search_characters",
    "list_world_settings",
    "list_foreshadowing",
    "get_prior_summary",
]


async def _make_real_session() -> tuple[AsyncSession, object]:
    """真实 in-memory aiosqlite + 单 AsyncSession（镜像 #988 集成轨）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


async def _seed_two_projects(db: AsyncSession) -> None:
    """种子：两个项目 + 各自角色；本项目另含 世界观 / 伏笔 / 章 + 摘要。"""
    db.add(ProjectORM(id=7, name="测试项目"))
    db.add(ProjectORM(id=8, name="另一个项目"))
    await db.commit()

    character_svc = get_character_service(db)
    await character_svc.create_character(PROJECT_ID, name=CHARACTER_NAME, personality="沉静")
    await character_svc.create_character(OTHER_PROJECT_ID, name=OTHER_CHARACTER_NAME)

    await get_foreshadowing_service(db).create(
        ForeshadowingCreate(
            project_id=PROJECT_ID, title=FORESHADOWING_TITLE, description="未回收线索"
        )
    )

    world_svc = get_world_service(db)
    root = await world_svc.ensure_root_setting(PROJECT_ID)
    await world_svc.create_category(PROJECT_ID, WORLD_CATEGORY)  # #834/#1321 分类前置
    await world_svc.create_setting(
        PROJECT_ID,
        name=WORLD_SETTING_NAME,
        category=WORLD_CATEGORY,
        content="位面设定正文",
        parent_id=root.id,
    )

    db.add(
        ChapterORM(
            id=CHAPTER_ID_INT,
            project_id=7,
            title="第一章",
            content="章节正文" * 10,
            status="final",
            word_count=40,
            order_index=1.0,
        )
    )
    await db.commit()
    await SQLiteSummaryRepository(db).upsert(CHAPTER_UUID, PRIOR_SUMMARY, MODEL)


def _assemble_writer_tools(db: AsyncSession, project_id: uuid.UUID) -> dict[str, object]:
    """真实装配写作轨 agent（只 patch build_deep_agent）→ {tool_name: Tool}。"""
    deps = AgenticWriterDeps(
        character_service=get_character_service(db),
        foreshadowing_service=get_foreshadowing_service(db),
        summary_service=get_summary_service(db),
        chapter_audit_service=MagicMock(),
        draft_service=MagicMock(),
        audit_service=MagicMock(),
        world_service=get_world_service(db),
    )
    with patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent") as m_da:
        m_da.return_value = MagicMock()
        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=deps,
            system_prompt=BASE_PROMPT,
            tool_ids=ISSUE_TOOLS,
            expected_project_id=project_id,
        )
        tools = m_da.call_args.kwargs["tools"]
    return {tool.spec.name: tool for tool in tools}


async def _call(tool: object) -> dict:
    """驱动工具协程并解析 JSON 信封（在既存事件循环内 await）。"""
    return json.loads(await tool.func())  # type: ignore[attr-defined]  # Tool.func 为 async 闭包


class TestWriterRetrievalToolsHitRealProject:
    """真库上 issue #1476 的 4 个工具必须取到**本项目**数据."""

    async def test_four_tools_return_real_project_data(self) -> None:
        """【R】4 工具逐个 `ok: true` —— 当前（未修）为 `项目不存在` / 空列表。"""
        db, engine = await _make_real_session()
        try:
            await _seed_two_projects(db)
            tools = _assemble_writer_tools(db, PROJECT_ID)

            assert sorted(tools) == sorted(ISSUE_TOOLS)

            characters = await _call(tools["search_characters"])
            assert characters["ok"] is True, characters
            names = [c["name"] for c in characters["data"]]
            assert names == [CHARACTER_NAME], f"应只取到本项目角色，实得 {names}"

            world = await _call(tools["list_world_settings"])
            assert world["ok"] is True, world
            assert WORLD_SETTING_NAME in [s["name"] for s in world["data"]]

            foreshadowing = await _call(tools["list_foreshadowing"])
            assert foreshadowing["ok"] is True, foreshadowing
            assert FORESHADOWING_TITLE in [f["title"] for f in foreshadowing["data"]]

            prior = await _call(tools["get_prior_summary"])
            assert prior["ok"] is True, prior
            assert PRIOR_SUMMARY in [s["summary"] for s in prior["data"]], (
                "前文摘要不得为空列表（issue #1476 的假绿形态）"
            )
        finally:
            await db.close()
            await engine.dispose()  # type: ignore[attr-defined]  # AsyncEngine

    async def test_other_project_context_sees_other_project(self) -> None:
        """【R】装配到另一个项目 → 只取到另一个项目的角色（隔离双向成立）."""
        db, engine = await _make_real_session()
        try:
            await _seed_two_projects(db)
            tools = _assemble_writer_tools(db, OTHER_PROJECT_ID)

            characters = await _call(tools["search_characters"])
            assert characters["ok"] is True, characters
            names = [c["name"] for c in characters["data"]]
            assert names == [OTHER_CHARACTER_NAME], names

            # 另一个项目无摘要/伏笔/世界观条目 → 空列表（不得串到本项目）
            assert (await _call(tools["list_foreshadowing"]))["data"] == []
            assert (await _call(tools["get_prior_summary"]))["data"] == []
        finally:
            await db.close()
            await engine.dispose()  # type: ignore[attr-defined]  # AsyncEngine
