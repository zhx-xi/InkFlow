"""Coverage backfill batch 2: PlannerService 起点/落库未覆盖分支。

经公开 start/respond 驱动：
- start(mode="continue") 缺源大纲 -> 容忍空实现（228-230）
- start(mode="branch") 大纲服务未返回 id -> ValueError（293-295）
- 完成路径 start_type=branch 且 copied_outline_id 非空 -> root 取复制根（462-463）
- 主角 value 首片段为空 -> 回退 strip 原值（137-138）
- LLM 结构化输出为 JSON 数组（非对象）-> 解析失败回落（755-756）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.domain.services.planner_service import (
    ROUND1_QUESTIONS,
    ROUND2_QUESTIONS,
    PlannerService,
)


def _session(**overrides) -> PlannerSession:
    base = dict(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status="drafting",
        one_liner="写一本关于时间旅者的悬疑小说",
        round=1,
        asked_questions=list(ROUND1_QUESTIONS),
        answers={},
        authorized=[],
        writing_plan_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return PlannerSession(**base)


def _outline(project_id: uuid.UUID) -> Outline:
    now = datetime.now(UTC)
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id,
        name="源大纲",
        description="",
        sort_order=1.0,
        level="overall",
        parent_id=None,
        chapter_id=None,
        extra={},
        created_at=now,
        updated_at=now,
    )


def _make_repo(session: PlannerSession | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.get_planner_session.return_value = session
    repo.get_writing_plan.return_value = None
    return repo


def _make_service(repo: AsyncMock, **kwargs) -> PlannerService:
    return PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_start_continue_without_source_outline_is_tolerated() -> None:
    """continue 起点缺源大纲 -> 保持宽容不抛（228-230）。"""
    repo = _make_repo()
    svc = _make_service(repo)

    session = await svc.start(uuid.uuid4(), "写一本武侠小说", mode="continue")

    assert session.start_type == "continue"
    assert session.copied_outline_id is None
    repo.add_planner_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_branch_outline_service_without_id_raises() -> None:
    """分支复制时大纲服务未返回 id -> ValueError（293-295）。"""
    project_id = uuid.uuid4()
    root = _outline(project_id)
    repo = _make_repo()
    outline_repo = AsyncMock()
    outline_repo.get.return_value = root
    outline_repo.list.return_value = ([], 0)
    svc = PlannerService(
        repo=repo,
        outline_repo=outline_repo,
        outline_service=AsyncMock(return_value=SimpleNamespace()),
    )

    with pytest.raises(ValueError, match="未返回 id"):
        await svc.start(
            project_id, "写一本武侠小说", mode="branch", source_outline_id=root.id
        )

    repo.add_planner_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_branch_session_sets_root_outline() -> None:
    """完成路径 start_type=branch 且已复制大纲 -> root 取复制根（462-463）。"""
    copied = uuid.uuid4()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={"q1": "武侠", "q2": "三卷", "q3": "复仇"},
        start_type="branch",
        source_outline_id=uuid.uuid4(),
        copied_outline_id=copied,
    )
    repo = _make_repo(session)
    svc = _make_service(repo)

    result = await svc.respond(session.id, {"q4": "3 卷", "q5": "配角自定"})

    assert result.completed is True
    assert result.writing_plan is not None
    assert result.writing_plan.root_outline_id == copied


@pytest.mark.asyncio
async def test_protagonist_empty_first_segment_falls_back_to_stripped_value() -> None:
    """主角 value 以分隔符开头（首片段为空）-> 回退 strip 后的原值（137-138）。"""
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        confirmed_items=[{"key": "主角", "value": "、林尘", "source": "user"}],
    )
    repo = _make_repo(session)
    character_service = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    svc = _make_service(repo, character_service=character_service)

    await svc.respond(session.id, {"q4": "3 卷", "q5": "配角自定"})

    assert character_service.await_args.kwargs["name"] == "、林尘"


@pytest.mark.asyncio
async def test_respond_llm_array_payload_falls_back_to_deterministic() -> None:
    """LLM 输出 JSON 数组（非对象）-> 解析失败回落确定性题库（755-756）。"""
    session = _session(round=1, asked_questions=list(ROUND1_QUESTIONS), answers={})
    repo = _make_repo(session)
    llm = AsyncMock()
    llm.chat.return_value = ChatResponse(content="[]", model="test/model")
    svc = _make_service(repo, llm_client=llm, llm_default_model="test/model")

    result = await svc.respond(session.id, {"q1": "武侠"})

    assert result.completed is False
    assert result.questions
