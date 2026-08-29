"""F51 写作工具 RED 契约测试 — build_writing_tools 注册 + 执行信封.

依据 specs/f51-agent-tools-v2/spec.md §2.8。镜像 test_chat_setting_write_tools 形态。
锁定契约:
1. build_writing_tools(deps) 返回 [generate, continue, revise]。
2. 成功 {"ok": True, ...} / 失败 {"ok": False, "error": "..."}。
3. expected_project_id/expected_chapter_id 绑定。
4. 成功/失败均落审计（audit_service.record），审计异常静默。
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.infrastructure.agent.tools.writing_tools import (
    WritingToolDeps,
    build_writing_tools,
)

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
CHAPTER_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440001")


def _make_deps() -> WritingToolDeps:
    audit = MagicMock()
    audit.record = AsyncMock(return_value=None)
    return WritingToolDeps(
        writing_service=MagicMock(),
        audit_service=audit,
        expected_project_id=PROJECT_ID,
        expected_chapter_id=CHAPTER_ID,
    )


def _writing_result(word_count: int = 1200) -> SimpleNamespace:
    return SimpleNamespace(
        content="正文",
        word_count=word_count,
        mode="generate",
        format_valid=True,
        retry_count=0,
        model="m",
        token_usage=None,
        warnings=[],
    )


class TestBuildWritingTools:
    """build_writing_tools 注册 3 个写作工具。"""

    def test_registers_three_tools(self) -> None:
        tools = build_writing_tools(_make_deps())
        assert [t.spec.name for t in tools] == [
            "generate",
            "continue",
            "revise",
        ]

    def test_tool_specs_have_input_schema(self) -> None:
        for t in build_writing_tools(_make_deps()):
            assert isinstance(t.spec.input_schema, dict)
            assert "type" in t.spec.input_schema

    @pytest.mark.asyncio
    async def test_generate_success_envelope(self) -> None:
        deps = _make_deps()
        deps.writing_service.generate_chapter = AsyncMock(return_value=_writing_result())
        tools = {t.spec.name: t for t in build_writing_tools(deps)}
        result = json.loads(await tools["generate"].func(outline="第一章大纲"))
        assert result["ok"] is True
        assert result["word_count"] == 1200
        assert str(result["chapter_id"]) == str(CHAPTER_ID)

    @pytest.mark.asyncio
    async def test_continue_success_envelope(self) -> None:
        deps = _make_deps()
        deps.writing_service.continue_writing = AsyncMock(return_value=_writing_result(800))
        tools = {t.spec.name: t for t in build_writing_tools(deps)}
        result = json.loads(await tools["continue"].func(existing_content="已有内容" * 20))
        assert result["ok"] is True
        assert result["word_count"] == 800

    @pytest.mark.asyncio
    async def test_revise_success_envelope(self) -> None:
        deps = _make_deps()
        deps.writing_service.revise_content = AsyncMock(return_value=_writing_result(1500))
        tools = {t.spec.name: t for t in build_writing_tools(deps)}
        result = json.loads(await tools["revise"].func(content="正文", feedback="更简洁"))
        assert result["ok"] is True
        assert result["word_count"] == 1500

    @pytest.mark.asyncio
    async def test_generate_failure_envelope(self) -> None:
        deps = _make_deps()
        deps.writing_service.generate_chapter = AsyncMock(side_effect=ValueError("大纲不能为空"))
        tools = {t.spec.name: t for t in build_writing_tools(deps)}
        result = json.loads(await tools["generate"].func(outline=""))
        assert result["ok"] is False
        assert "大纲不能为空" in result["error"]

    @pytest.mark.asyncio
    async def test_expected_context_binding(self) -> None:
        """generate 恒用绑定 project_id/chapter_id。"""
        deps = _make_deps()
        deps.writing_service.generate_chapter = AsyncMock(return_value=_writing_result())
        tools = {t.spec.name: t for t in build_writing_tools(deps)}
        await tools["generate"].func(
            outline="第一章大纲",
            project_id="00000000-0000-0000-0000-000000000000",
            chapter_id="00000000-0000-0000-0000-000000000000",
        )
        args, kwargs = deps.writing_service.generate_chapter.call_args
        used = kwargs.get("request") or (args[0] if args else None)
        assert str(used.project_id) == str(PROJECT_ID)
        assert str(used.chapter_id) == str(CHAPTER_ID)


class TestWritingToolAudit:
    """成功/失败均落审计，审计异常静默。"""

    @pytest.mark.asyncio
    async def test_success_records_audit(self) -> None:
        deps = _make_deps()
        deps.writing_service.generate_chapter = AsyncMock(return_value=_writing_result())
        tools = {t.spec.name: t for t in build_writing_tools(deps)}
        await tools["generate"].func(outline="第一章大纲")
        assert deps.audit_service.record.await_count >= 1

    @pytest.mark.asyncio
    async def test_failure_records_audit(self) -> None:
        deps = _make_deps()
        deps.writing_service.generate_chapter = AsyncMock(
            side_effect=ValueError("boom")
        )
        tools = {t.spec.name: t for t in build_writing_tools(deps)}
        await tools["generate"].func(outline="第一章大纲")
        assert deps.audit_service.record.await_count >= 1
