"""AgentService 设定/前文 context 装配分支覆盖（#687 coverage-gap 补测）。

覆盖 agent_service.py 的 _assemble_setting_context / _assemble_continue_context
各 repo 部分为 None、异常回退、前文摘要异常跳过等分支弧（直调私有方法，只依赖
注入的 repos，不触真实 pipeline）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.services.agent_service import AgentService

PROJECT_ID = "6f5c1f9e-9a4e-4f2e-8f3a-1b2c3d4e5f6a"
CHAPTER_ID = "11111111-1111-1111-1111-111111111111"


def _make_svc(**kw) -> AgentService:
    """最小构造 AgentService：pipeline/db_session 位置 + 全 mock repos。"""
    return AgentService(
        pipeline=AsyncMock(),
        db_session=AsyncMock(),
        store=AsyncMock(),
        project_repo=AsyncMock(),
        **kw,
    )


@pytest.mark.asyncio
async def test_setting_all_repos_none_returns_vars():
    """覆盖 L732-733：三个设定源全 None -> 原样返回 variables。"""
    svc = _make_svc(character_repo=None, world_repo=None, outline_repo=None)
    variables = {"topic": "x"}
    result = await svc._assemble_setting_context(PROJECT_ID, variables)
    assert result is variables


@pytest.mark.asyncio
async def test_setting_character_only_appends():
    """覆盖 L740-746、L749-False、L757-False、L765-766：仅角色源，内容非空 -> 注入 setting。"""
    char = SimpleNamespace(name="张三", personality="冷酷", background=None, goals=None)
    char_repo = AsyncMock()
    char_repo.list.return_value = ([char], 1)
    svc = _make_svc(character_repo=char_repo, world_repo=None, outline_repo=None)
    variables = {}
    result = await svc._assemble_setting_context(PROJECT_ID, variables)
    assert "【角色】张三：冷酷" in result["setting"]


@pytest.mark.asyncio
async def test_setting_outline_only_empty_description():
    """覆盖 L740-False、L749-False、L757-True、L761-False、L765-False：仅大纲源，description 空。"""
    outline = SimpleNamespace(name="大纲", description=None)
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([outline], 1)
    svc = _make_svc(character_repo=None, world_repo=None, outline_repo=outline_repo)
    variables = {}
    result = await svc._assemble_setting_context(PROJECT_ID, variables)
    assert "setting" not in result


@pytest.mark.asyncio
async def test_setting_outline_exception_swallowed():
    """覆盖 L763-764：outline 源读取异常 -> WARNING 回退（失败隔离）。"""
    outline_repo = AsyncMock()
    outline_repo.list.side_effect = RuntimeError("db down")
    svc = _make_svc(character_repo=None, world_repo=None, outline_repo=outline_repo)
    variables = {}
    result = await svc._assemble_setting_context(PROJECT_ID, variables)
    assert "setting" not in result


@pytest.mark.asyncio
async def test_continue_project_none_returns_vars():
    """覆盖 L784-785：project 不存在 -> 原样返回 variables。"""
    svc = _make_svc(summary_service=AsyncMock(), chapter_repo=AsyncMock())
    svc._project_repo.get.return_value = None
    variables = {}
    result = await svc._assemble_continue_context(PROJECT_ID, CHAPTER_ID, variables)
    assert result is variables


@pytest.mark.asyncio
async def test_continue_chapter_none_returns_vars():
    """覆盖 L787-788：当前章不存在 -> 原样返回 variables。"""
    svc = _make_svc(summary_service=AsyncMock(), chapter_repo=AsyncMock())
    svc._project_repo.get.return_value = SimpleNamespace(config=SimpleNamespace(model="m"))
    svc._chapter_repo.get_chapter.return_value = None
    variables = {}
    result = await svc._assemble_continue_context(PROJECT_ID, CHAPTER_ID, variables)
    assert result is variables


@pytest.mark.asyncio
async def test_continue_summary_exception_skips():
    """覆盖 L797-806：前文摘要生成异常 -> WARNING + continue，parts 空则不注入。"""
    current = SimpleNamespace(id=uuid.uuid4(), order_index=5, title="第五章")
    prev1 = SimpleNamespace(id=uuid.uuid4(), order_index=1, title="第一章")
    svc = _make_svc(summary_service=AsyncMock(), chapter_repo=AsyncMock())
    svc._project_repo.get.return_value = SimpleNamespace(config=SimpleNamespace(model="m"))
    svc._chapter_repo.get_chapter.return_value = current
    svc._chapter_repo.list_chapters.return_value = ([prev1, current], 2)
    svc._summary_service.ensure_summary.side_effect = RuntimeError("summary failed")
    variables = {}
    result = await svc._assemble_continue_context(PROJECT_ID, CHAPTER_ID, variables)
    assert "context" not in result


@pytest.mark.asyncio
async def test_continue_exception_swallowed():
    """覆盖 L808-809：list_chapters 整体异常 -> WARNING 回退。"""
    svc = _make_svc(summary_service=AsyncMock(), chapter_repo=AsyncMock())
    svc._project_repo.get.return_value = SimpleNamespace(config=SimpleNamespace(model="m"))
    svc._chapter_repo.get_chapter.return_value = SimpleNamespace(id=uuid.uuid4(), order_index=5)
    svc._chapter_repo.list_chapters.side_effect = RuntimeError("list fail")
    variables = {}
    result = await svc._assemble_continue_context(PROJECT_ID, CHAPTER_ID, variables)
    assert result is variables


@pytest.mark.asyncio
async def test_setting_world_only_appends():
    """覆盖 L749-756：仅世界观源，content 非空 -> 注入 setting。"""
    world = SimpleNamespace(name="大陆", content="东方玄幻")
    world_repo = AsyncMock()
    world_repo.list.return_value = ([world], 1)
    svc = _make_svc(character_repo=None, world_repo=world_repo, outline_repo=None)
    variables = {}
    result = await svc._assemble_setting_context(PROJECT_ID, variables)
    assert "【世界观】大陆：东方玄幻" in result["setting"]


@pytest.mark.asyncio
async def test_setting_world_exception_swallowed():
    """覆盖 L755-756：world 源读取异常 -> WARNING 回退。"""
    world_repo = AsyncMock()
    world_repo.list.side_effect = RuntimeError("world down")
    svc = _make_svc(character_repo=None, world_repo=world_repo, outline_repo=None)
    variables = {}
    result = await svc._assemble_setting_context(PROJECT_ID, variables)
    assert "setting" not in result
