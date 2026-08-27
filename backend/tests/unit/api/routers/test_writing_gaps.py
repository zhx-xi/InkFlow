"""#708 coverage 补测 鈥?writing 路由缺口分支（直接调用 endpoint / 辅助函数）。

被测模块: ``inkflow.api.routers.writing``
补齐缺口:
- ``_map_agentic_service_error`` 非 AgenticWriteNotFoundError 鈫?500（80-81 行 + 75->80）
- ``agentic_generate`` memory_svc.get_summaries 失败 鈫?fallback 字典（152-153 行）
- ``_event_generator`` 客户端未断开 鈫?正常产出 SSE 帧（191->194）
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.api.routers import writing as writing_mod
from inkflow.domain.models.writing import WritingStreamEvent

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def test_map_agentic_service_error_generic_500() -> None:
    """非 AgenticWriteNotFoundError 异常 鈫?logger + 500 + LLM_ERROR 头。"""
    exc = writing_mod._map_agentic_service_error(RuntimeError("boom"))

    assert exc.status_code == 500
    assert exc.headers == {"X-InkFlow-Error-Code": "LLM_ERROR"}


async def test_agentic_generate_memory_failure_uses_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_summaries 失败 鈫?semantic_summaries 回退默认字典（152-153 行）。"""
    run = SimpleNamespace(
        id="run-1",
        status=SimpleNamespace(value="completed"),
        draft_id="draft-1",
        final_content="生成内容",
        steps=[],
        token_usage_total=10,
        terminated_by="llm",
    )
    svc = AsyncMock()
    svc.run = AsyncMock(return_value=run)

    def _boom_memory(db: object) -> object:
        raise RuntimeError("memory summary failed")

    monkeypatch.setattr(writing_mod, "get_memory_service", _boom_memory, raising=False)

    result = await writing_mod.agentic_generate(
        data=SimpleNamespace(project_id=PROJECT_ID),
        svc=svc,
        db=object(),
    )

    assert result["semantic_summaries"] == {
        "project_id": PROJECT_ID,
        "project": None,
        "user": None,
    }
    assert result["run_id"] == "run-1"


async def test_event_generator_yields_encoded_frame_when_connected() -> None:
    """客户端未断开 鈫?yield SSE 帧（191->194 False 分支）。"""
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))

    async def _events():
        yield WritingStreamEvent(delta="你好")

    frames = [s async for s in writing_mod._event_generator(request, _events())]

    assert len(frames) == 1
    assert frames[0].startswith("data: ")
    assert '"delta": "你好"' in frames[0]
