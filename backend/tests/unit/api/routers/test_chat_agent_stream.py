"""#597 chat 系统级 Agent 后端 RED 契约测试 — ChatAgentService 帧映射 + get_chat_agent_service 装配.

spec f47 §14.2（#597 增量）：POST /api/v1/chat/agent/stream 驱动 deepagents 系统级
Agent（全量工具：5 只读 + save_draft），agent.astream_events(version="v2") 事件流 →
ChatStreamEvent 帧（delta / tool_call / tool_result / done）。

被测对象（GREEN 建，RED 期不存在 → 用例体惰性 import → ImportError FAILED，合法）：
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService
    from inkflow.api.deps import get_chat_agent_service

父侧定稿契约（GREEN 按此实现）
--------------------------------
1. ChatStreamEvent 扩展（inkflow/domain/services/chat_service.py MODIFY）：
   新增字段 type: str = "delta"、id: str | None = None、name: str | None = None、
   args: dict | None = None、result: str | None = None（delta/done/error 既有字段保留）。
2. ChatAgentService（inkflow/infrastructure/agent/chat_agent_service.py NEW）：
       class ChatAgentService:
           def __init__(self, *, agent, system_prompt: str) -> None
           async def stream_events(self, prompt: str, chapter_context: str | None = None)
               -> AsyncGenerator[ChatStreamEvent, None]
   - messages 组装：[SystemMessage(system_prompt), HumanMessage(user_content)]；
     user_content = prompt；chapter_context 非空时追加
     f"{prompt}\\n\\n章节上下文：\\n{chapter_context}"（镜像 ChatService.stream）
   - 迭代 agent.astream_events({"messages": messages}, version="v2") 事件 dict（v2 schema）：
       {"event": "on_chat_model_stream", "run_type": "llm", "data": {"chunk": chunk}}
           → ChatStreamEvent(type="delta", delta=chunk.content)
       {"event": "on_tool_start", "run_id": <id>, "name": <name>, "data": {"input": <args>}}
           → ChatStreamEvent(type="tool_call", id=run_id, name=name, args=data["input"])
       {"event": "on_tool_end", "run_id": <id>, "name": <name>, "data": {"output": <result>}}
           → ChatStreamEvent(type="tool_result", id=run_id, name=name, result=data["output"])
   - 流结束 → ChatStreamEvent(type="done", done=True)
   - LLMRequestError（agent 抛出）→ 原样传播（端点层转 error 帧，service 不吞）
3. get_chat_agent_service（inkflow/api/deps.py MODIFY，spec §14.6）：
       def get_chat_agent_service(
           data: ChatStreamRequest, db: AsyncSession = Depends(get_db),
       ) -> ChatAgentService
   - 装配：build_reader_tools(ReaderToolDeps(character_service, foreshadowing_service,
     summary_service, chapter_audit_service)) 全量 5 只读 + build_save_draft_tool(
     SaveDraftToolDeps(draft_service, audit_service,
     expected_project_id=uuid.UUID(data.project_id),
     expected_chapter_id=uuid.UUID(data.chapter_id) if data.chapter_id else None))
     → build_deep_agent(model=..., api_key=..., base_url=..., tools=全量,
     system_prompt=chat_system_agent_prompt, profile_key=None)
     → ChatAgentService(agent=build_deep_agent 产物, system_prompt=同源提示词)
   - deps.py 模块顶层 from-import 三工厂（patch 目标 = inkflow.api.deps.<名>，
     f27 绑定名快照先例）；service getter 均走 deps 模块函数（本文件 patch 之）

patch 注入点（f27 先例：patch 调用方模块的绑定名）
--------------------------------------------------
    inkflow.api.deps.build_deep_agent / build_reader_tools / build_save_draft_tool
    inkflow.api.deps.get_character_service / get_foreshadowing_service / get_summary_service /
    get_chapter_audit_service / get_draft_service / get_audit_service

RED 预期（当前无 chat_agent_service 模块 / deps.get_chat_agent_service /
ChatStreamEvent 新字段）：
- ChatAgentService / get_chat_agent_service 用例：惰性 import → ImportError FAILED
  （inkflow.infrastructure.agent.chat_agent_service 模块不存在，parent 裁定 module-not-found 合法）
- ChatStreamEvent 默认值用例：ev.type → AttributeError FAILED（字段未扩展）
- fake agent 帧映射用例：同 ImportError FAILED
预期总结行：全 FAILED（逐用例粒度，无 collection error）。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inkflow.api.routers.chat_stream import ChatStreamRequest, stream_chat_agent
from inkflow.domain.models.agent_run import AgentRun
from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.services.chat_service import ChatStreamEvent
from inkflow.infrastructure.agent.tools.reader_tools import ReaderToolDeps, Tool
from inkflow.infrastructure.agent.tools.save_draft_tool import SaveDraftToolDeps

SYSTEM_PROMPT = "你是 InkFlow 系统级 Agent，拥有全部创作工具（检索/写入/审计）"
MODEL = "deepseek/deepseek-v4-flash"  # #415 G3 伪契约同步：mock 参数非语义断言
API_KEY = "test-key"
BASE_URL = "https://example.test/v1"

EXPECTED_READER_NAMES = [
    "search_characters",
    "check_foreshadowing",
    "get_prior_summary",
    "audit_chapter",
    "count_words",
]

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
CHAPTER_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


# ── 辅助 ──────────────────────────────────────


def _kwarg_or_positional(call, name: str, index: int, default=None):
    """宽松取 mock 调用参数：优先关键字，回退位置参数（兼容两种 GREEN 形态）。"""
    args, kwargs = call
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else default


def _fake_tool(name: str) -> Tool:
    """构造最小真实 Tool（spec.name 可断言，func 不执行）。"""
    return Tool(
        spec=ToolSpec(name=name, description="", input_schema={}),
        func=MagicMock(),
    )


def _get_chat_agent_service():
    """用例体惰性取 get_chat_agent_service——RED 期不存在 → ImportError（FAILED 非收集 ERROR）。"""
    from inkflow.api.deps import get_chat_agent_service

    return get_chat_agent_service


def _get_chat_agent_service_cls():
    """用例体惰性取 ChatAgentService——RED 期模块不存在 → ImportError（FAILED 非收集 ERROR）。"""
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

    return ChatAgentService


def _chunk(content: str) -> SimpleNamespace:
    """AIMessageChunk 鸭子替身（.content）。"""
    return SimpleNamespace(content=content)


def _llm_chunk_event(content: str) -> dict:
    """astream_events v2：on_chat_model_stream（run_type='llm'）→ delta 帧源。"""
    return {"event": "on_chat_model_stream", "run_type": "llm", "data": {"chunk": _chunk(content)}}


def _tool_start_event(run_id: str, name: str, args: dict) -> dict:
    """astream_events v2：on_tool_start → tool_call 帧源。"""
    return {"event": "on_tool_start", "run_id": run_id, "name": name, "data": {"input": args}}


def _tool_end_event(run_id: str, name: str, output: str) -> dict:
    """astream_events v2：on_tool_end → tool_result 帧源。"""
    return {"event": "on_tool_end", "run_id": run_id, "name": name, "data": {"output": output}}


class _FakeAgent:
    """fake deepagents agent — astream_events 为 async generator，按预置事件 dict 列表 yield。

    error_after=N：yield 前 N 个事件后抛 error（None = 不抛）——锁定「LLMRequestError
    传播」语义（service 不吞异常）。calls 记录每次 astream_events 的 inputs/version。
    """

    def __init__(
        self,
        events: list[dict] | None = None,
        error: Exception | None = None,
        error_after: int | None = None,
    ) -> None:
        self._events = list(events or [])
        self._error = error
        self._error_after = error_after
        self.calls: list[dict] = []

    async def astream_events(self, inputs, version="v2"):
        self.calls.append({"inputs": inputs, "version": version})
        for i, ev in enumerate(self._events):
            if self._error is not None and self._error_after is not None and i >= self._error_after:
                raise self._error
            yield ev
        if self._error is not None and (
            self._error_after is None or self._error_after >= len(self._events)
        ):
            raise self._error


def _make_svc(events=None, error=None, error_after=None, system_prompt: str = SYSTEM_PROMPT):
    """构造 ChatAgentService(agent=fake, system_prompt=...)——RED 期 ChatAgentService 不存在。"""
    agent = _FakeAgent(events=events, error=error, error_after=error_after)
    svc = _get_chat_agent_service_cls()(agent=agent, system_prompt=system_prompt)
    return svc, agent


# ── TestChatStreamEventDefaults: ChatStreamEvent 扩展 ──


class TestChatStreamEventDefaults:
    """ChatStreamEvent 扩展默认值契约（chat_service.py MODIFY，spec §14.2 帧表）。"""

    def test_agent_frame_fields_defaults(self) -> None:
        """新增字段默认值：type='delta'，id/name/args/result 均 None；既有字段不变。"""
        ev = ChatStreamEvent()
        assert ev.type == "delta"  # RED：字段未扩展 → AttributeError FAILED
        assert ev.id is None
        assert ev.name is None
        assert ev.args is None
        assert ev.result is None
        # 向后兼容守护：既有字段默认值不变
        assert ev.delta == ""
        assert ev.done is False
        assert ev.error is None


# ── TestChatAgentStreamEvents: 帧映射 ──


class TestChatAgentStreamEvents:
    """ChatAgentService.stream_events 帧映射——fake agent 预置 v2 事件 dict 流。"""

    @pytest.mark.asyncio
    async def test_llm_chunk_maps_to_delta(self) -> None:
        """on_chat_model_stream(run_type='llm') → type='delta' 帧（delta=chunk.content）。"""
        svc, _ = _make_svc(events=[_llm_chunk_event("你"), _llm_chunk_event("好")])
        events = [ev async for ev in svc.stream_events(prompt="你好")]
        assert [ev.type for ev in events] == ["delta", "delta", "done"]
        assert [ev.delta for ev in events[:-1]] == ["你", "好"]
        assert "".join(ev.delta for ev in events[:-1]) == "你好"
        assert events[-1].done is True
        assert events[-1].type == "done"

    @pytest.mark.asyncio
    async def test_model_end_full_response_streams_delta_via_sleep(self) -> None:
        """#642：仅 on_chat_model_end（完整 AIMessage、无 on_chat_model_stream）时，
        stream_events 仍应产 ≥2 个 delta 帧（sleep 分块模拟流式）——前端 onDelta 逐字累积
        才能显示。RED：当前实现（chat_agent_service.py L65-67）只在 on_chat_model_stream
        时产 delta，本用例只产 on_chat_model_end → 仅 done、0 delta → FAIL（正确 RED）。"""
        content = "这是一个较长的完整回复，用于验证非流式响应也会被切块流式输出，界面能逐字显示。"
        output = SimpleNamespace(
            content=content,
            tool_calls=[],
            response_metadata={"usage": {"total_tokens": 30}},
        )
        events = [
            {
                "event": "on_chat_model_end",
                "name": "ChatOpenAI",
                "run_id": "llm_1",
                "data": {"output": output},
            }
        ]
        svc, _ = _make_svc(events=events)
        frames = [ev async for ev in svc.stream_events(prompt="你好")]
        delta_frames = [ev for ev in frames if ev.type == "delta"]
        # 完整响应也应被切成 ≥2 块流式送出（否则前端 onDelta 无触发 → UI 空白）
        assert len(delta_frames) >= 2
        assert "".join(ev.delta for ev in delta_frames) == content
        assert frames[-1].done is True

    @pytest.mark.asyncio
    async def test_tool_start_end_maps_to_tool_call_result(self) -> None:
        """on_tool_start → tool_call（id=run_id/name/args）；on_tool_end →
        tool_result（id/name/result）。"""
        args = {"project_id": PROJECT_ID}
        result = '{"ok": true, "data": []}'
        svc, _ = _make_svc(
            events=[
                _tool_start_event("call_1", "search_characters", args),
                _tool_end_event("call_1", "search_characters", result),
            ]
        )
        events = [ev async for ev in svc.stream_events(prompt="找一下主角")]
        assert [ev.type for ev in events] == ["tool_call", "tool_result", "done"]
        call_ev, result_ev = events[0], events[1]
        assert call_ev.id == "call_1"
        assert call_ev.name == "search_characters"
        assert call_ev.args == args
        assert result_ev.id == "call_1"
        assert result_ev.name == "search_characters"
        assert result_ev.result == result

    @pytest.mark.asyncio
    async def test_messages_system_then_user_passed_to_agent(self) -> None:
        """astream_events 收到 {'messages': [SystemMessage(system_prompt),
        HumanMessage(prompt)]}, version='v2'。"""
        svc, agent = _make_svc(events=[_llm_chunk_event("好")])
        async for _ in svc.stream_events(prompt="介绍一下主角"):
            pass
        assert len(agent.calls) == 1
        assert agent.calls[0]["version"] == "v2"
        messages = agent.calls[0]["inputs"]["messages"]
        assert len(messages) == 2
        assert messages[0].content == SYSTEM_PROMPT
        assert messages[1].content == "介绍一下主角"

    @pytest.mark.asyncio
    async def test_chapter_context_appended_to_user_message(self) -> None:
        """chapter_context 非空 → HumanMessage content 追加章节上下文段落。"""
        svc, agent = _make_svc(events=[_llm_chunk_event("好")])
        async for _ in svc.stream_events(
            prompt="继续写", chapter_context="第一章：主角初入宗门，遭遇同门挑衅。"
        ):
            pass
        messages = agent.calls[0]["inputs"]["messages"]
        assert "继续写" in messages[1].content
        assert "第一章：主角初入宗门，遭遇同门挑衅。" in messages[1].content

    @pytest.mark.asyncio
    async def test_chapter_context_none_keeps_user_content_as_prompt(self) -> None:
        """chapter_context 缺省 → user content 就是 prompt 本身（无追加段落）。"""
        svc, agent = _make_svc(events=[_llm_chunk_event("好")])
        async for _ in svc.stream_events(prompt="继续写"):
            pass
        messages = agent.calls[0]["inputs"]["messages"]
        assert messages[1].content == "继续写"

    @pytest.mark.asyncio
    async def test_stream_ends_with_done_after_empty_events(self) -> None:
        """agent 无任何事件 → 仅 done 终帧（type='done', done=True）。"""
        svc, _ = _make_svc(events=[])
        events = [ev async for ev in svc.stream_events(prompt="你好")]
        assert len(events) == 1
        assert events[0].type == "done"
        assert events[0].done is True

    @pytest.mark.asyncio
    async def test_llm_request_error_propagates(self) -> None:
        """agent 流中抛 LLMRequestError → 原样传播（端点层转 error 帧，service 不吞）。"""
        svc, _ = _make_svc(
            events=[_llm_chunk_event("你"), _llm_chunk_event("好")],
            error=LLMRequestError("API key invalid"),
            error_after=1,
        )
        with pytest.raises(LLMRequestError):
            async for _ in svc.stream_events(prompt="你好"):
                pass

    @pytest.mark.asyncio
    async def test_on_chat_model_end_collects_steps_via_consume_trace(self) -> None:
        """#615 契约①：on_chat_model_end（完整 AIMessage，含 tool_calls + usage）+
        随后的 on_tool_end → stream_events 累积收集 steps；流结束后 consume_trace()
        返回 (steps, final_content, token_usage_total)。

        工具结果按 tool_call_id（AIMessage.tool_calls[].id ↔ on_tool_end.run_id）回填；
        tokens 取 response_metadata.usage.total_tokens。RED 期 consume_trace()
        不存在 → AttributeError FAILED（正确 RED）。
        """
        output = SimpleNamespace(
            content="介绍主角",
            tool_calls=[
                {"name": "search_characters", "args": {"project_id": PROJECT_ID}, "id": "call_1"}
            ],
            response_metadata={"usage": {"total_tokens": 25}},
        )
        events = [
            {
                "event": "on_chat_model_end",
                "name": "ChatOpenAI",
                "run_id": "llm_1",
                "data": {"output": output},
            },
            _tool_end_event("call_1", "search_characters", '{"ok":true,"data":[]}'),
        ]
        svc, _ = _make_svc(events=events)
        frames = [ev async for ev in svc.stream_events(prompt="找主角")]
        assert frames[-1].done is True  # 流完整结束（含 done 终帧）后再取 trace

        steps, final_content, token_usage_total = svc.consume_trace()

        assert len(steps) == 1
        assert steps[0].message_content == "介绍主角"
        assert steps[0].tool_calls[0].tool_name == "search_characters"
        assert steps[0].tool_calls[0].arguments == {"project_id": PROJECT_ID}
        assert steps[0].tool_calls[0].result == '{"ok":true,"data":[]}'
        assert steps[0].tool_calls[0].is_error is False
        assert steps[0].tokens == 25
        assert token_usage_total == 25
        assert final_content == "介绍主角"


# ── TestGetChatAgentService: 装配 ──


class TestGetChatAgentService:
    """get_chat_agent_service 装配契约（spec §14.2）— mock service + 三工厂，锁定全量工具面。

    patch 目标 = deps.py 模块顶层绑定名（f27 绑定名快照先例）；service getter 均为
    deps 既有函数（mock 返回 AsyncMock 形态，断言身份同一性）。
    """

    @patch("inkflow.api.deps.build_deep_agent")
    @patch("inkflow.api.deps.build_save_draft_tool")
    @patch("inkflow.api.deps.build_reader_tools")
    @patch("inkflow.api.deps.get_chapter_audit_service")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.api.deps.get_draft_service")
    @patch("inkflow.api.deps.get_summary_service")
    @patch("inkflow.api.deps.get_foreshadowing_service")
    @patch("inkflow.api.deps.get_character_service")
    def test_assembles_full_tools(
        self, m_char, m_foresh, m_sum, m_draft, m_audit, m_audit_ch, m_rt, m_sd, m_da
    ) -> None:
        """全量工具面：5 只读 + save_draft → build_deep_agent；返回 ChatAgentService。"""
        data = ChatStreamRequest(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, prompt="你好")
        m_rt.return_value = [_fake_tool(name) for name in EXPECTED_READER_NAMES]
        m_sd.return_value = _fake_tool("save_draft")

        svc = _get_chat_agent_service()(data=data, db=MagicMock())

        # 4 只读 service 注入 ReaderToolDeps（身份同一性）
        reader_deps = _kwarg_or_positional(m_rt.call_args, "deps", 0)
        assert isinstance(reader_deps, ReaderToolDeps)
        assert reader_deps.character_service is m_char.return_value
        assert reader_deps.foreshadowing_service is m_foresh.return_value
        assert reader_deps.summary_service is m_sum.return_value
        assert reader_deps.chapter_audit_service is m_audit_ch.return_value
        # save_draft deps：draft/audit service + expected 上下文（spec §14.2）
        save_deps = _kwarg_or_positional(m_sd.call_args, "deps", 0)
        assert isinstance(save_deps, SaveDraftToolDeps)
        assert save_deps.draft_service is m_draft.return_value
        assert save_deps.audit_service is m_audit.return_value
        assert save_deps.expected_project_id == uuid.UUID(PROJECT_ID)
        assert save_deps.expected_chapter_id == uuid.UUID(CHAPTER_ID)
        # build_deep_agent：全量工具（5 只读 + save_draft）、profile_key=None、prompt 透传
        assert m_da.call_count == 1
        tools = _kwarg_or_positional(m_da.call_args, "tools", 3, None)
        assert [tool.spec.name for tool in tools] == [*EXPECTED_READER_NAMES, "save_draft"]
        assert _kwarg_or_positional(m_da.call_args, "profile_key", 5, None) is None
        prompt = _kwarg_or_positional(m_da.call_args, "system_prompt", 4, None)
        assert isinstance(prompt, str) and prompt
        # 返回值：ChatAgentService（agent=build_deep_agent 产物；system_prompt 同源）
        chat_agent_cls = _get_chat_agent_service_cls()
        assert isinstance(svc, chat_agent_cls)
        assert svc._agent is m_da.return_value  # type: ignore[attr-defined]  # 测试直查装配内部
        assert svc._system_prompt == prompt  # type: ignore[attr-defined]  # 测试直查装配内部

    @patch("inkflow.api.deps.build_deep_agent")
    @patch("inkflow.api.deps.build_save_draft_tool")
    @patch("inkflow.api.deps.build_reader_tools")
    @patch("inkflow.api.deps.get_chapter_audit_service")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.api.deps.get_draft_service")
    @patch("inkflow.api.deps.get_summary_service")
    @patch("inkflow.api.deps.get_foreshadowing_service")
    @patch("inkflow.api.deps.get_character_service")
    def test_assembles_without_chapter_id(
        self, m_char, m_foresh, m_sum, m_draft, m_audit, m_audit_ch, m_rt, m_sd, m_da
    ) -> None:
        """chapter_id 缺省 → SaveDraftToolDeps.expected_chapter_id 为 None。"""
        m_rt.return_value = [_fake_tool(name) for name in EXPECTED_READER_NAMES]
        m_sd.return_value = _fake_tool("save_draft")
        data = ChatStreamRequest(project_id=PROJECT_ID, prompt="你好")

        _get_chat_agent_service()(data=data, db=MagicMock())

        save_deps = _kwarg_or_positional(m_sd.call_args, "deps", 0)
        assert save_deps.expected_project_id == uuid.UUID(PROJECT_ID)
        assert save_deps.expected_chapter_id is None
        tools = _kwarg_or_positional(m_da.call_args, "tools", 3, None)
        assert [tool.spec.name for tool in tools] == [*EXPECTED_READER_NAMES, "save_draft"]


# ── TestGetChatAgentServiceDbAndParseFallback: coverage-gap 补测（deps_chat_agent.py） ──


def _session_gen(*sessions):
    """单/多 session 的 async generator——mock deps.get_db 的返回物。"""

    async def _gen():
        for s in sessions:
            yield s

    return _gen()


class TestGetChatAgentServiceDbAndParseFallback:
    """deps_chat_agent.py 覆盖缺口补测（#597 新文件 LINE 84.4% / BRANCH 0.0%，非 RED 直通）：

    - _get_db（L32-37）：deps.get_db 惰性代理，async for 逐 session yield；
    - get_chat_agent_service except ValueError（L70-71）：parse_model_string 抛
      ValueError → api_key/base_url 回退空串，装配继续不抛异常。
    """

    @pytest.mark.asyncio
    async def test_get_db_delegates_to_deps_get_db(self) -> None:
        """_get_db 调用期 from deps import get_db，async for 逐 session yield。"""
        from inkflow.api.deps_chat_agent import _get_db

        fake_session = MagicMock()
        with patch("inkflow.api.deps.get_db") as m_get_db:
            m_get_db.return_value = _session_gen(fake_session)
            sessions = [s async for s in _get_db()]

        assert sessions == [fake_session]
        m_get_db.assert_called_once_with()

    @patch("inkflow.api.deps.build_deep_agent")
    @patch("inkflow.api.deps.build_save_draft_tool")
    @patch("inkflow.api.deps.build_reader_tools")
    @patch("inkflow.api.deps.get_chapter_audit_service")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.api.deps.get_draft_service")
    @patch("inkflow.api.deps.get_summary_service")
    @patch("inkflow.api.deps.get_foreshadowing_service")
    @patch("inkflow.api.deps.get_character_service")
    @patch("inkflow.infrastructure.llm.provider_config.parse_model_string", side_effect=ValueError)
    def test_parse_model_string_value_error_falls_back_to_defaults(
        self, m_parse, m_char, m_foresh, m_sum, m_draft, m_audit, m_audit_ch, m_rt, m_sd, m_da
    ) -> None:
        """parse_model_string 抛 ValueError → except 分支：api_key/base_url 回退空串，
        装配继续，get_chat_agent_service 正常返回 ChatAgentService（不抛异常）。"""
        data = ChatStreamRequest(project_id=PROJECT_ID, prompt="你好")

        svc = _get_chat_agent_service()(data=data, db=MagicMock())

        m_parse.assert_called_once()
        chat_agent_cls = _get_chat_agent_service_cls()
        assert isinstance(svc, chat_agent_cls)
        # 回退空串 → build_deep_agent 收到 api_key="" / base_url=""
        assert _kwarg_or_positional(m_da.call_args, "api_key", 1, None) == ""
        assert _kwarg_or_positional(m_da.call_args, "base_url", 2, None) == ""


# ── TestStreamChatAgentPersistsRun: #615 端点落 run ──


class TestStreamChatAgentPersistsRun:
    """#615 契约②：stream_chat_agent 落 run（mode=chat）+ done 帧回传 run_id。

    直接调用端点函数并注入 repo（test_chat_stream_api.py 同款：SSE 端点不走
    HTTP 层），另 patch deps.get_agent_run_repo（f27 绑定名快照惯例）兜底
    运行时取仓路径。run_id 来自 repo.create 返回值。

    RED 期端点未接 repo 参数 → TypeError（unexpected keyword argument 'repo'）
    FAILED = 正确 RED（落库未接线）。
    """

    @patch("inkflow.api.deps.get_agent_run_repo")
    @pytest.mark.asyncio
    async def test_stream_chat_agent_persists_run_with_chat_mode(self, m_get_repo) -> None:
        """repo.create(project_id/chapter_id, mode='chat') → 流式（steps 收集）→
        repo.save(completed run, steps 非空) → done 帧含 run_id。"""
        run_id = "chat-run-0001"
        now = datetime.now(UTC)
        mock_run = AgentRun(
            id=run_id,
            project_id=uuid.UUID(PROJECT_ID),
            chapter_id=uuid.UUID(CHAPTER_ID),
            mode="chat",
            created_at=now,
            updated_at=now,
        )
        mock_repo = MagicMock()
        mock_repo.create = AsyncMock(return_value=mock_run)
        mock_repo.save = AsyncMock(return_value=None)
        m_get_repo.return_value = mock_repo

        # 事件序列复用契约①：on_chat_model_end + on_tool_end → steps 非空
        output = SimpleNamespace(
            content="介绍主角",
            tool_calls=[
                {"name": "search_characters", "args": {"project_id": PROJECT_ID}, "id": "call_1"}
            ],
            response_metadata={"usage": {"total_tokens": 25}},
        )
        svc, _ = _make_svc(
            events=[
                {
                    "event": "on_chat_model_end",
                    "name": "ChatOpenAI",
                    "run_id": "llm_1",
                    "data": {"output": output},
                },
                _tool_end_event("call_1", "search_characters", '{"ok":true,"data":[]}'),
            ]
        )

        data = ChatStreamRequest(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, prompt="找主角")
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)

        resp = await stream_chat_agent(data=data, request=request, svc=svc, repo=mock_repo)
        frames = [frame async for frame in resp.body_iterator]

        # ① 前置落 running run：create(mode="chat")
        mock_repo.create.assert_awaited_once_with(
            project_id=uuid.UUID(PROJECT_ID),
            chapter_id=uuid.UUID(CHAPTER_ID),
            mode="chat",
        )
        # ② 流结束 save 终态：completed + steps 非空 + final_content/token 回填
        mock_repo.save.assert_awaited_once()
        saved_run = _kwarg_or_positional(mock_repo.save.await_args, "run", 0)
        assert saved_run.status == "completed"
        assert saved_run.steps
        assert saved_run.final_content == "介绍主角"
        assert saved_run.token_usage_total == 25
        # ③ done 帧回传 run_id（前端 #599 存 runId → 点开详情）
        done_payload = json.loads(frames[-1].removeprefix("data: ").strip())
        assert done_payload["type"] == "done"
        assert done_payload["done"] is True
        assert done_payload["run_id"] == run_id


class TestStreamChatAgentBranchCoverageGaps:
    """#645 stream_chat_agent 分支补测。"""

    @pytest.mark.asyncio
    async def test_disconnected_returns_empty_body(self):
        """is_disconnected=True（agent 流）→ 首帧前 return，body 为空（L214-215）。"""
        svc, _ = _make_svc(events=[_llm_chunk_event("你")])
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=True)
        mock_repo = MagicMock()
        mock_repo.create = AsyncMock(
            return_value=SimpleNamespace(id="r1", created_at=datetime.now(UTC))
        )
        with patch("inkflow.api.deps.get_agent_run_repo", return_value=mock_repo):
            resp = await stream_chat_agent(
                data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
                request=request,
                svc=svc,
                repo=mock_repo,
            )
        frames = [frame async for frame in resp.body_iterator]
        assert frames == []

    @pytest.mark.asyncio
    async def test_llm_request_error_saves_failed_and_emits_error_frame(self):
        """LLMRequestError（run 已建）→ _save_failed_run + error 帧。"""
        svc, _ = _make_svc(error=LLMRequestError("API down"), error_after=0)
        mock_repo = MagicMock()
        mock_repo.create = AsyncMock(
            return_value=SimpleNamespace(id="r1", created_at=datetime.now(UTC))
        )
        mock_repo.save = AsyncMock(return_value=None)
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)
        with patch("inkflow.api.deps.get_agent_run_repo", return_value=mock_repo):
            resp = await stream_chat_agent(
                data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
                request=request,
                svc=svc,
                repo=mock_repo,
            )
        frames = [frame async for frame in resp.body_iterator]
        payload = json.loads(frames[0].removeprefix("data: ").strip())
        assert payload["type"] == "error"
        assert payload["done"] is True
        mock_repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_request_error_before_run_create_skips_save(self):
        """repo.create 抛 LLMRequestError（run 未建）→ 不 save，仅 error 帧。"""
        svc, _ = _make_svc(events=[_llm_chunk_event("你")])
        mock_repo = MagicMock()
        mock_repo.create = AsyncMock(side_effect=LLMRequestError("create fail"))
        mock_repo.save = AsyncMock(return_value=None)
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)
        with patch("inkflow.api.deps.get_agent_run_repo", return_value=mock_repo):
            resp = await stream_chat_agent(
                data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
                request=request,
                svc=svc,
                repo=mock_repo,
            )
        frames = [frame async for frame in resp.body_iterator]
        payload = json.loads(frames[0].removeprefix("data: ").strip())
        assert payload["type"] == "error"
        assert payload["done"] is True
        mock_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generic_exception_saves_failed_then_rethrows(self):
        """stream_events 抛 RuntimeError（非 LLM）→ _save_failed_run + 重抛（L239-242）。"""
        svc, _ = _make_svc(error=RuntimeError("weird"), error_after=0)
        mock_repo = MagicMock()
        mock_repo.create = AsyncMock(
            return_value=SimpleNamespace(id="r1", created_at=datetime.now(UTC))
        )
        mock_repo.save = AsyncMock(return_value=None)
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)
        with patch("inkflow.api.deps.get_agent_run_repo", return_value=mock_repo):
            resp = await stream_chat_agent(
                data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
                request=request,
                svc=svc,
                repo=mock_repo,
            )
        with pytest.raises(RuntimeError):
            async for _ in resp.body_iterator:
                pass
        mock_repo.save.assert_awaited_once()

# ── TestStreamChatAgentPassesProjectId: #680 端点透传 project_id ──


class TestStreamChatAgentPassesProjectId:
    """#680 数据面断链修复：stream_chat_agent 调用 svc.stream_events 必须透传 data.project_id。

    当前实现（chat_stream.py:213）调 svc.stream_events(prompt=prompt,
    chapter_context=data.chapter_context)——只传 prompt/chapter_context，
    data.project_id 仅用于落 AgentRun 与 save_draft 守卫；Agent 拿不到 project_id →
    reader tools 收不到绑定 → Agent 反问用户。本用例锁定端点透传 project_id 契约。
    """

    @pytest.mark.asyncio
    async def test_passes_project_id_to_stream_events(self) -> None:
        data = ChatStreamRequest(project_id=PROJECT_ID, prompt="hi")
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)
        mock_repo = MagicMock()
        mock_repo.create = AsyncMock(
            return_value=SimpleNamespace(id="r1", created_at=datetime.now(UTC))
        )
        captured: dict[str, object] = {}

        async def _stream_events(**kwargs):
            captured.update(kwargs)
            yield ChatStreamEvent(done=True)

        svc = MagicMock()
        svc.stream_events = _stream_events
        svc.consume_trace = MagicMock(return_value=([], "", 0))
        with patch("inkflow.api.deps.get_agent_run_repo", return_value=mock_repo):
            resp = await stream_chat_agent(data=data, request=request, svc=svc, repo=mock_repo)
        frames = [frame async for frame in resp.body_iterator]

        assert captured.get("project_id") == PROJECT_ID
        assert frames  # 透传不破坏出帧
