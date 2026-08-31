"""stream_chat_agent 端点契约测试（拆分自超长文件，>900 行护栏）。"""

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
from inkflow.infrastructure.agent.tools.reader_tools import Tool

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
EXPECTED_SETTING_WRITE_NAMES = [
    "create_character",
    "create_world_setting",
    "create_outline",
]
EXPECTED_SETTING_UPDATE_NAMES = [
    "update_character",
    "update_world_setting",
    "update_outline",
]
EXPECTED_WORLD_RW_NAMES = [
    "list_maps",
    "create_map",
    "update_map",
    "list_timeline_events",
    "create_timeline_event",
    "update_timeline_event",
    "create_foreshadowing",
    "update_foreshadowing",
]
EXPECTED_MEMORY_NAMES = [
    "memory_list",
    "memory_add",
    "memory_update",
]
EXPECTED_WRITING_NAMES = [
    "generate",
    "continue",
    "revise",
]

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
CHAPTER_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
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

    async def astream_events(self, inputs, version="v2", config=None):
        self.calls.append({"inputs": inputs, "version": version, "config": config})
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
    async def test_disconnected_saves_terminal_run(self):
        """#842 is_disconnected=True（agent 流）→ 落 TERMINATED 终态（不遗留 running）。"""
        svc, _ = _make_svc(events=[_llm_chunk_event("你")])
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=True)
        mock_repo = MagicMock()
        mock_repo.create = AsyncMock(
            return_value=SimpleNamespace(id="r1", created_at=datetime.now(UTC))
        )
        mock_repo.save = AsyncMock(return_value=None)
        with patch("inkflow.api.deps.get_agent_run_repo", return_value=mock_repo):
            resp = await stream_chat_agent(
                data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
                request=request,
                svc=svc,
                repo=mock_repo,
            )
        # 消费 body_iterator（断连后生成器仍执行，触发 run 终态落库）
        async for _frame in resp.body_iterator:
            pass
        # #842：断连不再让 run 遗留 running —— 落终态（failed/cancelled）
        mock_repo.save.assert_awaited_once()
        saved_run = _kwarg_or_positional(mock_repo.save.await_args, "run", 0)
        assert saved_run.status == "terminated"

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
    async def test_generic_exception_emits_error_frame_and_saves_failed(self):
        """#697 stream_events 内工具异常（RuntimeError 非 LLM）→ 端点产 error 帧 + done 帧，
        不 raise 500（前端不再 network error），run 落 FAILED 终态。"""
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
        frames = [frame async for frame in resp.body_iterator]
        payloads = [json.loads(f.removeprefix("data: ").strip()) for f in frames]
        # 不抛异常：流可正常消费完，含 error 帧 + done 帧（前端不再 network error）
        assert any(p["type"] == "error" for p in payloads)
        assert payloads[-1]["type"] == "done"
        mock_repo.save.assert_awaited_once()
        saved_run = _kwarg_or_positional(mock_repo.save.await_args, "run", 0)
        assert saved_run.status == "failed"


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
