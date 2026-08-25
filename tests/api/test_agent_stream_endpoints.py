"""#642-1 Agent 管线 REST 端点补测 — api/routers/agent.py (coverage-gap #645)。

覆盖 agent.py 剩余缺口（非 RED——端点已实现，补测即过）：
- _parse_id ValueError → 404（L33-36）
- _encode_frame_pipeline 三帧编码（delta/done/error；L73-85）+ _encode_pipeline_error（L90）
- POST /api/v1/agent/pipelines/stream 校验 + error 帧兜底 + is_disconnected 短路（L101-114）
- execute_pipeline builtin:chat 缺 prompt → 422（L133）；项目/章节不存在 → 404（L140）
- get_execution_status 不存在 → 404（L153）

镜像 tests/api/test_pipeline_stream_api.py 的 httpx_sse aconnect_sse + patch _svc 风格；
is_disconnected 短路用直接调用端点函数（mock request.is_disconnected=True）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

# 本地 3.13 + pydantic 2.13.4 + mcp-types 2.0.0：导入 inkflow.api.app 时 mcp_types 建
# RootModel[Result] 泛型子模型报 KeyError 'pydantic.root_model'（CI 3.11 无此问题）。
# 先 import pydantic.root_model 预热 sys.modules 稳定收集；对 CI 3.11 为无副作用 no-op。
import pydantic.root_model  # noqa: F401  # 预热 sys.modules 稳定 mcp_types 泛型导入（本地 py313）
import pytest
from httpx import ASGITransport, AsyncClient
from httpx_sse import aconnect_sse

from inkflow.api.app import app
from inkflow.api.routers.agent import (
    _encode_frame_pipeline,
    _encode_pipeline_error,
    _parse_id,
    stream_pipeline,
)
from inkflow.domain.ports.agent_pipeline import PipelineStreamEvent

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _make_request(pipeline: str = "builtin:write_auto", **kwargs) -> dict:
    return {"project_id": PROJECT_ID, "pipeline": pipeline, **kwargs}


def _make_svc(*events) -> MagicMock:
    """mock _svc —— stream_pipeline 为异步生成器；其余被等待的方法用 AsyncMock。"""
    svc = MagicMock()
    svc.stream_pipeline = _stream_stub(*events)
    svc.execute = AsyncMock()
    svc.get_status = AsyncMock()
    svc.confirm_execution = AsyncMock()
    svc.list_executions = AsyncMock()
    svc.validate_pipeline = MagicMock()
    svc.list_templates = MagicMock()
    return svc


def _stream_stub(*events):
    async def _gen(data):
        for ev in events:
            yield ev

    return _gen


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=httpx.Timeout(30.0)
    )


# ── 纯函数契约：_parse_id / _encode_frame_pipeline ──


class TestParseId:
    """_parse_id：合法 UUID → 对象；非法字符串 → 404。"""

    def test_valid_uuid_returns_object(self):
        assert _parse_id(PROJECT_ID) is not None

    def test_invalid_uuid_raises_404(self):
        with pytest.raises(Exception) as exc:
            _parse_id("not-a-uuid")
        assert exc.value.status_code == 404
        assert exc.value.detail == "资源不存在"


class TestEncodeFramePipeline:
    """_encode_frame_pipeline 三帧编码：delta / done(final_output+intent+execution_id) / error。"""

    def test_delta_frame(self):
        ev = PipelineStreamEvent(type="delta", delta="你好", done=False)
        payload = json.loads(_encode_frame_pipeline(ev)[6:])
        assert payload == {"type": "delta", "delta": "你好", "done": False}

    def test_done_frame_with_metadata(self):
        ev = PipelineStreamEvent(
            type="done", done=True, final_output="正文", intent="content", execution_id="e1"
        )
        payload = json.loads(_encode_frame_pipeline(ev)[6:])
        assert payload["type"] == "done"
        assert payload["done"] is True
        assert payload["final_output"] == "正文"
        assert payload["intent"] == "content"
        assert payload["execution_id"] == "e1"

    def test_error_frame(self):
        ev = PipelineStreamEvent(type="done", done=True, error="boom")
        payload = json.loads(_encode_frame_pipeline(ev)[6:])
        assert payload == {"type": "error", "error": "boom", "done": True}

    def test_done_frame_without_optional_metadata(self):
        """done 帧 final_output/intent/execution_id 均空 → 仅 type/done 键（L77-85 空值分支）。"""
        ev = PipelineStreamEvent(
            type="done", done=True, final_output="", intent=None, execution_id=""
        )
        payload = json.loads(_encode_frame_pipeline(ev)[6:])
        assert payload == {"type": "done", "done": True}

    def test_encode_pipeline_error_helper(self):
        payload = json.loads(_encode_pipeline_error("bad request")[6:])
        assert payload["type"] == "error"
        assert payload["error"] == "bad request"


# ── POST /api/v1/agent/pipelines/stream ──


class TestPipelinesStreamEndpoint:
    """端点层：stream 成功帧 / error 帧兜底 / is_disconnected 短路。"""

    @pytest.mark.asyncio
    async def test_stream_success_frames(self):
        """200 + delta/done(final_output, intent=content) 帧。"""
        svc = _make_svc(
            SimpleNamespace(
                type="delta", delta="序章", done=False, final_output="", intent=None,
                error="", execution_id="",
            ),
            SimpleNamespace(
                type="done", delta="", done=True, final_output="序章正文", intent="content",
                error="", execution_id="e1",
            ),
        )
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with (
                _client() as client,
                aconnect_sse(
                    client, "POST", "/api/v1/agent/pipelines/stream",
                    json=_make_request(pipeline="builtin:write_continue"),
                ) as sse,
            ):
                assert sse.response.status_code == 200
                frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
        assert frames[0] == {"type": "delta", "delta": "序章", "done": False}
        assert frames[1]["type"] == "done"
        assert frames[1]["done"] is True
        assert frames[1]["final_output"] == "序章正文"
        assert frames[1]["intent"] == "content"

    @pytest.mark.asyncio
    async def test_stream_service_error_frame(self):
        """service 抛异常 → SSE error 帧（HTTP 仍 200）。"""
        svc = MagicMock()

        async def _gen(data):
            raise RuntimeError("service down")

        svc.stream_pipeline = _gen
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with (
                _client() as client,
                aconnect_sse(
                    client, "POST", "/api/v1/agent/pipelines/stream", json=_make_request()
                ) as sse,
            ):
                assert sse.response.status_code == 200
                frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
        assert frames[0]["type"] == "error"
        assert frames[0]["done"] is True

    @pytest.mark.asyncio
    async def test_stream_disconnected_short_circuit(self):
        """request.is_disconnected() = True → _event_stream 首帧前 return（空 body）。"""
        svc = _make_svc(
            SimpleNamespace(
                type="delta", delta="一", done=False, final_output="", intent=None,
                error="", execution_id="",
            ),
        )
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=True)
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            response = await stream_pipeline(
                data=SimpleNamespace(pipeline="builtin:write_auto", variables={}),
                request=request,
                db=MagicMock(),
            )
        # is_disconnected 恒 True → _event_stream return 无 yield → body 为空
        chunks = [chunk async for chunk in response.body_iterator]
        assert chunks == []
        request.is_disconnected.assert_awaited()

    @pytest.mark.asyncio
    async def test_stream_builtin_chat_without_prompt_422(self):
        """builtin:chat 缺 variables.prompt → 422（镜像 execute_pipeline 校验语义）。"""
        svc = _make_svc()
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/agent/pipelines/stream", json=_make_request(pipeline="builtin:chat")
                )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "chat 管线需要 variables.prompt"


# ── POST /api/v1/agent/pipelines/execute 校验 ──


class TestExecutePipelineValidation:
    """execute_pipeline：builtin:chat 缺 prompt → 422；项目/章节不存在 → 404。"""

    @pytest.mark.asyncio
    async def test_execute_builtin_chat_without_prompt_422(self):
        svc = _make_svc()
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/agent/pipelines/execute", json=_make_request(pipeline="builtin:chat")
                )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "chat 管线需要 variables.prompt"

    @pytest.mark.asyncio
    async def test_execute_project_not_found_404(self):
        from inkflow.domain.services.agent_service import AgentServiceError

        svc = _make_svc()
        svc.execute = AsyncMock(side_effect=AgentServiceError("项目不存在"))
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/agent/pipelines/execute", json=_make_request()
                )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "项目不存在"

    @pytest.mark.asyncio
    async def test_execute_chapter_not_found_404(self):
        from inkflow.domain.services.agent_service import AgentServiceError

        svc = _make_svc()
        svc.execute = AsyncMock(side_effect=AgentServiceError("章节不存在"))
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/agent/pipelines/execute", json=_make_request()
                )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "章节不存在"


# ── GET /api/v1/agent/pipelines/executions/{execution_id} ──


class TestGetExecutionStatus:
    """get_execution_status：记录不存在 → 404。"""

    @pytest.mark.asyncio
    async def test_execution_not_found_404(self):
        svc = _make_svc()
        svc.get_status = AsyncMock(return_value=None)
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with _client() as client:
                resp = await client.get("/api/v1/agent/pipelines/executions/abc")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "执行记录不存在"


class TestRemainingEndpoints:
    """list_executions / validate_pipeline / list_templates（agent.py L181-199）。"""

    @pytest.mark.asyncio
    async def test_list_executions_returns_items(self):
        """GET /pipelines/executions?project_id= → 200 + {items, total}。"""
        svc = _make_svc()
        svc.list_executions = AsyncMock(return_value={"items": [], "total": 0})
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with _client() as client:
                resp = await client.get(
                    "/api/v1/agent/pipelines/executions", params={"project_id": PROJECT_ID}
                )
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}
        svc.list_executions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_validate_pipeline_returns_errors(self):
        """POST /pipelines/validate → 200 + 校验错误列表（sync 调用）。"""
        svc = _make_svc()
        svc.validate_pipeline = MagicMock(return_value=["阶段 id 重复"])
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/agent/pipelines/validate",
                    json={
                        "name": "custom",
                        "stages": [
                            {
                                "id": "s1",
                                "name": "阶段1",
                                "agent": {"id": "a1", "name": "A1", "system_prompt": "提示"},
                            }
                        ],
                    },
                )
        assert resp.status_code == 200
        assert resp.json() == ["阶段 id 重复"]
        svc.validate_pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_templates_returns_list(self):
        """GET /pipelines/templates → 200 + 模板列表（sync 调用）。"""
        svc = _make_svc()
        svc.list_templates = MagicMock(return_value=[{"name": "builtin:write_auto"}])
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with _client() as client:
                resp = await client.get("/api/v1/agent/pipelines/templates")
        assert resp.status_code == 200
        assert resp.json() == [{"name": "builtin:write_auto"}]
        svc.list_templates.assert_called_once()


class TestConfirmExecution:
    """POST /pipelines/executions/{id}/confirm → AgentServiceError 映射 404/422。"""

    @pytest.mark.asyncio
    async def test_confirm_execution_not_found_404(self):
        from inkflow.domain.services.agent_service import AgentServiceError

        svc = _make_svc()
        svc.confirm_execution = AsyncMock(side_effect=AgentServiceError("执行记录不存在"))
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/agent/pipelines/executions/abc/confirm", json={"approved": True}
                )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "执行记录不存在"

    @pytest.mark.asyncio
    async def test_confirm_execution_generic_error_422(self):
        from inkflow.domain.services.agent_service import AgentServiceError

        svc = _make_svc()
        svc.confirm_execution = AsyncMock(side_effect=AgentServiceError("状态不符"))
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/agent/pipelines/executions/abc/confirm", json={"approved": False}
                )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "状态不符"


class TestSvcAssembly:
    """_svc(db) 装配：_supervisor_pipeline 为 None 时初始化（agent.py L54-56）。"""

    def test_svc_initializes_supervisor_pipeline(self):
        import inkflow.api.routers.agent as agent_mod
        from inkflow.domain.services.agent_service import AgentService

        old = agent_mod._supervisor_pipeline
        agent_mod._supervisor_pipeline = None
        try:
            with (
                patch("inkflow.api.routers.agent.LangChainLLMClient"),
                patch("inkflow.api.routers.agent.LangGraphAgentPipeline"),
                patch("inkflow.api.routers.agent.SupervisorPipeline"),
                patch("inkflow.api.routers.agent.get_summary_service"),
                patch(
                    "inkflow.infrastructure.database.repositories.character_repo.SQLiteCharacterRepository"
                ),
                patch("inkflow.infrastructure.database.repositories.world_repo.SQLiteWorldRepository"),
                patch(
                    "inkflow.infrastructure.database.repositories.outline_repo.SQLiteOutlineRepository"
                ),
            ):
                svc = agent_mod._svc(MagicMock())
                assert isinstance(svc, AgentService)
                # _supervisor_pipeline 初值 None → 初始化 Singleton（L54-56）
                assert agent_mod._supervisor_pipeline is not None
        finally:
            agent_mod._supervisor_pipeline = old
