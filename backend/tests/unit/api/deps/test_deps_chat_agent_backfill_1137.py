"""#1137 覆盖率补齐 —— deps_chat_agent.py 装配期闭包经公开面驱动。

权威来源：
- specs/f26-agent-tools/spec.md §3（装配点：各 service getter + 工具工厂注入）
- specs/f47-chat-exec-detail（chat 装配：项目上下文段 + 多轮历史记忆注入）
- specs/f56-volume-outline-link #976 D3（草稿卷解析：章 id → 写作卷 UUID）

公开面（无私有成员/闭包直调）：
- ``await get_chat_agent_service(data, db)``（FastAPI 依赖装配函数）
- 装配产物 ``ChatAgentService.stream_events``（公开流式方法 → 触发上下文/历史注入）
- 装配产物工具 ``save_draft`` / ``agent_call`` 的 ``func``（build_*_tools 公开工厂产物）

deps 模块级工厂按本仓既有 DIRECT-CALL 模式 monkeypatch（test_deps_chat_agent_coverage_gaps.py）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkflow.api.deps import get_chat_agent_service
from inkflow.api.routers.chat_stream import ChatStreamRequest
from inkflow.infrastructure.agent.pipeline_templates import _CHAT_SYSTEM_AGENT_PROMPT
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM
from inkflow.infrastructure.database.models.chat_message import ChatMessageORM
from inkflow.infrastructure.database.models.conversation import ConversationORM
from inkflow.infrastructure.database.models.project import ProjectORM

SEED_PROJECT_ID = uuid.UUID(int=1)
"""projects.id 为 INTEGER 主键 → 领域 id = uuid.UUID(int=orm.id)。"""

CHAPTER_UUID = uuid.UUID(int=20)
VOLUME_UUID = uuid.UUID(int=3)

GETTERS = [
    "get_character_service",
    "get_foreshadowing_service",
    "get_summary_service",
    "get_chapter_audit_service",
    "get_world_service",
    "get_outline_service",
    "get_map_service",
    "get_timeline_service",
    "get_memory_service",
    "get_writing_service",
    "get_audit_service",
    "get_agent_service",
]


class _FakeAgent:
    """deep agent 替身：无事件流 + 可控 ainvoke（镜像 deepagents Runnable 契约）。"""

    def __init__(self) -> None:
        self.invoke_result: dict = {"messages": []}
        self.ainvoke = AsyncMock(side_effect=self._invoke)
        self.invoked_payloads: list[dict] = []
        self.streamed_payloads: list[dict] = []

    async def _invoke(self, payload: dict, **kwargs: object) -> dict:
        self.invoked_payloads.append(payload)
        return self.invoke_result

    async def astream_events(self, payload, version=None, config=None):
        self.streamed_payloads.append(payload)
        for event in ():
            yield event


async def _make_session(test_engine) -> AsyncSession:
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    return factory()


async def _seed_project(session: AsyncSession) -> None:
    session.add(ProjectORM(id=SEED_PROJECT_ID.int, name="chat 覆盖项目", config={}))
    await session.commit()


def _patch_assembly(monkeypatch, db: AsyncSession, agent: _FakeAgent) -> tuple[MagicMock, dict]:
    """按 inkflow.api.deps 命名空间 patch 装配工厂，返回 (build_deep_agent mock, stubs)。"""
    deep = MagicMock(return_value=agent)
    monkeypatch.setattr("inkflow.api.deps.build_deep_agent", deep)
    monkeypatch.setattr("inkflow.api.deps.build_reader_tools", MagicMock(return_value=[]))
    monkeypatch.setattr("inkflow.api.deps.build_setting_write_tools", MagicMock(return_value=[]))
    monkeypatch.setattr("inkflow.api.deps.build_setting_update_tools", MagicMock(return_value=[]))
    monkeypatch.setattr("inkflow.api.deps.build_world_rw_tools", MagicMock(return_value=[]))
    monkeypatch.setattr("inkflow.api.deps.build_memory_tools", MagicMock(return_value=[]))
    monkeypatch.setattr("inkflow.api.deps.build_writing_tools", MagicMock(return_value=[]))
    monkeypatch.setattr(
        "inkflow.api._llm_resolver.resolve_llm_credentials",
        MagicMock(return_value=("model", "key", "url")),
    )
    monkeypatch.setattr(
        "inkflow.api.deps_chat_agent.resolve_grants", MagicMock(return_value=None)
    )
    monkeypatch.setattr(
        "inkflow.api.deps_chat_agent.build_tools_by_grants", MagicMock(return_value=[])
    )

    stubs: dict[str, MagicMock] = {name: MagicMock() for name in GETTERS}
    stubs["get_project_service"] = MagicMock(
        return_value=SimpleNamespace(get=AsyncMock(return_value=None))
    )
    stubs["get_conversation_service"] = MagicMock(
        return_value=SimpleNamespace(get=AsyncMock(return_value=None))
    )
    stubs["get_draft_service"] = MagicMock(
        return_value=SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(id="draft-1")),
            find_pending=AsyncMock(return_value=None),
        )
    )
    stubs["get_agent_entity_service"] = MagicMock(
        return_value=SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(system_prompt="子 agent 提示词"))
        )
    )
    stubs["get_context_service"] = MagicMock(
        return_value=SimpleNamespace(
            build_context=AsyncMock(return_value="CTX-RESULT"),
            render_system_prompt=MagicMock(return_value="渲染后的项目上下文"),
        )
    )
    for name, stub in stubs.items():
        monkeypatch.setattr(f"inkflow.api.deps.{name}", stub)
    return deep, stubs


def _tools_by_name(deep_mock: MagicMock) -> dict:
    tools = deep_mock.call_args.kwargs["tools"]
    return {tool.spec.name: tool for tool in tools}


@pytest.mark.asyncio
async def test_stream_events_injects_project_context_and_history(test_engine, monkeypatch):
    """f47：stream_events 注入渲染后项目上下文段 + 多轮历史（user/ai → Human/AI 消息）。"""
    async with await _make_session(test_engine) as session:
        await _seed_project(session)
        session.add_all(
            [
                ConversationORM(id=7, project_id=SEED_PROJECT_ID.int),
                ChatMessageORM(
                    id=1,
                    project_id=SEED_PROJECT_ID.int,
                    conversation_id=7,
                    role="user",
                    content="上一轮提问",
                ),
                ChatMessageORM(
                    id=2,
                    project_id=SEED_PROJECT_ID.int,
                    conversation_id=7,
                    role="ai",
                    content="上一轮回答",
                ),
            ]
        )
        await session.commit()

        agent = _FakeAgent()
        _deep, stubs = _patch_assembly(monkeypatch, session, agent)
        data = ChatStreamRequest(project_id=str(SEED_PROJECT_ID), prompt="这一轮提问")

        svc = await get_chat_agent_service(data=data, db=session)
        events = [
            event
            async for event in svc.stream_events(
                "这一轮提问", project_id=str(SEED_PROJECT_ID)
            )
        ]

        assert [event.type for event in events] == ["done"]
        context_svc = stubs["get_context_service"].return_value
        context_request = context_svc.build_context.await_args.args[0]
        assert context_request.project_id == SEED_PROJECT_ID
        assert context_request.writing_requirements == "这一轮提问"
        messages = agent.streamed_payloads[0]["messages"]
        assert messages[0].content.startswith(_CHAT_SYSTEM_AGENT_PROMPT)
        assert "渲染后的项目上下文" in messages[0].content
        # #748 历史注入：[System, Human(历史), AI(历史), Human(当前)]
        assert [message.type for message in messages] == ["system", "human", "ai", "human"]
        assert messages[1].content == "上一轮提问"
        assert messages[2].content == "上一轮回答"
        assert messages[3].content == "这一轮提问"


@pytest.mark.asyncio
async def test_agent_call_tool_runs_single_agent(test_engine, monkeypatch):
    """f26 §3：agent_call 工具经 run_agent 装配钩子执行单 agent 并回传输出文本。"""
    async with await _make_session(test_engine) as session:
        agent = _FakeAgent()
        deep, _stubs = _patch_assembly(monkeypatch, session, agent)
        data = ChatStreamRequest(project_id=str(SEED_PROJECT_ID), prompt="hi")
        await get_chat_agent_service(data=data, db=session)
        call_tool = _tools_by_name(deep)["agent_call"]

        agent.invoke_result = {
            # 倒序扫描：末条非 ai 消息跳过（循环继续）→ 命中更早的 ai 消息
            "messages": [
                AIMessage(content="agent 输出文本"),
                HumanMessage(content="后续追问"),
            ],
        }
        result = json.loads(await call_tool.func(agent_id="a1", input="执行一次"))

        assert result == {"ok": True, "result": "agent 输出文本"}
        blueprint = agent.invoked_payloads[0]
        assert blueprint["messages"][0].content == "执行一次"
        # 单 agent 装配复用同一模型/凭据与子 agent 提示词（D5：不给配置 CRUD）
        assert deep.call_args.kwargs["system_prompt"] == "子 agent 提示词"
        assert deep.call_args.kwargs["tools"] == []

        agent.invoke_result = {"messages": []}
        empty = json.loads(await call_tool.func(agent_id="a1", input="再执行一次"))

        assert empty == {"ok": True, "result": ""}


@pytest.mark.asyncio
async def test_save_draft_tool_resolves_volume_from_chapter(test_engine, monkeypatch):
    """#976 D3：save_draft 工具按绑定章 id 解析写作卷并落库到草稿。"""
    async with await _make_session(test_engine) as session:
        await _seed_project(session)
        session.add(VolumeORM(id=VOLUME_UUID.int, project_id=SEED_PROJECT_ID.int, title="第一卷"))
        session.add(
            ChapterORM(
                id=CHAPTER_UUID.int,
                project_id=SEED_PROJECT_ID.int,
                volume_id=VOLUME_UUID.int,
                title="第一章",
            )
        )
        await session.commit()

        agent = _FakeAgent()
        deep, stubs = _patch_assembly(monkeypatch, session, agent)
        data = ChatStreamRequest(
            project_id=str(SEED_PROJECT_ID),
            prompt="hi",
            chapter_id=str(CHAPTER_UUID),
        )
        await get_chat_agent_service(data=data, db=session)
        save_draft = _tools_by_name(deep)["save_draft"]

        result = json.loads(await save_draft.func(content="第一章正文"))

        assert result["ok"] is True
        assert result["draft_id"] == "draft-1"
        create_kwargs = stubs["get_draft_service"].return_value.create.await_args.kwargs
        assert create_kwargs["volume_id"] == VOLUME_UUID


@pytest.mark.asyncio
async def test_save_draft_tool_volume_lookup_failure_stays_silent(
    test_engine, monkeypatch
):
    """#976 D3：卷解析异常静默 → 草稿仍落库（volume_id=None），不阻断工具路径。"""
    async with await _make_session(test_engine) as session:
        await _seed_project(session)

        async def _boom(self, chapter_id):
            raise RuntimeError("chapter repo down")

        monkeypatch.setattr(
            "inkflow.domain.services.chapter_service.ChapterService.get_chapter", _boom
        )
        agent = _FakeAgent()
        deep, stubs = _patch_assembly(monkeypatch, session, agent)
        data = ChatStreamRequest(
            project_id=str(SEED_PROJECT_ID),
            prompt="hi",
            chapter_id=str(CHAPTER_UUID),
        )
        await get_chat_agent_service(data=data, db=session)
        save_draft = _tools_by_name(deep)["save_draft"]

        result = json.loads(await save_draft.func(content="第一章正文"))

        assert result["ok"] is True
        create_kwargs = stubs["get_draft_service"].return_value.create.await_args.kwargs
        assert create_kwargs["volume_id"] is None
