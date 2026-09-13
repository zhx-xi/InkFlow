"""Batch 3 coverage backfill: agent tools and structured logging."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger

from inkflow.domain.models.preference import PreferenceCategory
from inkflow.infrastructure.agent.tools.memory_tools import (
    MemoryToolDeps,
    build_memory_tools,
)
from inkflow.infrastructure.agent.tools.setting_write_tools import (
    SettingWriteToolDeps,
    build_setting_write_tools,
)
from inkflow.infrastructure.agent.tools.writing_tools import (
    WritingToolDeps,
    build_writing_tools,
)
from inkflow.logging import StructuredLogStore, instrument


def _audit() -> MagicMock:
    audit = MagicMock()
    audit.record = AsyncMock(return_value=None)
    return audit


def _writing_result() -> SimpleNamespace:
    return SimpleNamespace(
        content="body",
        word_count=123,
        mode="generate",
        format_valid=True,
        retry_count=0,
        model="model",
        token_usage=None,
        warnings=[],
    )


@pytest.mark.asyncio
async def test_memory_tools_coerce_fallback_and_update_optional_fields() -> None:
    """Public memory tools coerce caller UUIDs and forward optional update fields."""
    project_id = uuid.UUID(int=11)
    deps = MemoryToolDeps(
        memory_service=MagicMock(),
        audit_service=_audit(),
        expected_project_id=None,
    )
    deps.memory_service.create_preference = AsyncMock(
        return_value=SimpleNamespace(id="pref-1")
    )
    deps.memory_service.update_preference = AsyncMock(
        return_value=SimpleNamespace(id="pref-1")
    )
    deps.memory_service.list_preferences = AsyncMock(return_value=([], 0))
    tools = {tool.spec.name: tool for tool in build_memory_tools(deps)}

    add_result = json.loads(
        await tools["memory_add"].func(
            project_id=str(project_id),
            category="addressing",
            pattern="short",
            note="keep",
        )
    )
    update_result = json.loads(
        await tools["memory_update"].func(
            preference_id="pref-1",
            category="addressing",
            pattern="long",
            note="updated",
        )
    )
    note_only = json.loads(
        await tools["memory_update"].func(preference_id="pref-1", note="only-note")
    )
    list_result = json.loads(await tools["memory_list"].func(project_id=None))

    assert add_result["ok"] is True
    assert update_result["ok"] is True
    assert note_only["ok"] is True
    assert list_result["ok"] is True
    assert deps.memory_service.create_preference.await_args.kwargs["project_id"] == project_id
    update_kwargs = deps.memory_service.update_preference.await_args_list[0].kwargs
    assert update_kwargs["category"] == PreferenceCategory.ADDRESSING
    assert update_kwargs["pattern"] == "long"
    assert update_kwargs["value"] == "updated"
    note_only_kwargs = deps.memory_service.update_preference.await_args_list[-1].kwargs
    assert "pattern" not in note_only_kwargs
    assert note_only_kwargs["value"] == "only-note"
    assert deps.memory_service.list_preferences.await_args.args[0] is None


@pytest.mark.asyncio
async def test_memory_list_failure_returns_error_envelope() -> None:
    """Public memory_list converts service errors to an error envelope."""
    deps = MemoryToolDeps(
        memory_service=MagicMock(),
        audit_service=_audit(),
        expected_project_id=uuid.UUID(int=1),
    )
    deps.memory_service.list_preferences = AsyncMock(side_effect=ValueError("list failed"))
    tools = {tool.spec.name: tool for tool in build_memory_tools(deps)}

    result = json.loads(await tools["memory_list"].func())

    assert result["ok"] is False
    assert "list failed" in result["error"]


@pytest.mark.asyncio
async def test_writing_tools_coerce_and_none_project_id() -> None:
    """Public writing tools coerce project IDs and preserve the None fallback."""
    project_id = uuid.UUID(int=12)
    chapter_id = uuid.UUID(int=13)
    deps = WritingToolDeps(
        writing_service=MagicMock(),
        audit_service=_audit(),
        expected_project_id=None,
        expected_chapter_id=chapter_id,
    )
    deps.writing_service.generate_chapter = AsyncMock(return_value=_writing_result())
    tools = {tool.spec.name: tool for tool in build_writing_tools(deps)}

    coerced = json.loads(
        await tools["generate"].func(outline="outline", project_id=str(project_id))
    )
    unbound = json.loads(await tools["generate"].func(outline="outline", project_id=None))

    assert coerced["ok"] is True
    assert unbound["ok"] is True
    first_request = deps.writing_service.generate_chapter.await_args_list[0].kwargs["request"]
    second_request = deps.writing_service.generate_chapter.await_args_list[1].kwargs["request"]
    assert first_request.project_id == project_id
    assert second_request.project_id is None


@pytest.mark.asyncio
async def test_writing_tools_continue_and_revise_require_chapter_context() -> None:
    """Public continue/revise fail fast when no chapter context is bound."""
    deps = WritingToolDeps(
        writing_service=MagicMock(),
        audit_service=_audit(),
        expected_project_id=uuid.UUID(int=12),
        expected_chapter_id=None,
    )
    tools = {tool.spec.name: tool for tool in build_writing_tools(deps)}

    continued = json.loads(await tools["continue"].func(existing_content="existing"))
    revised = json.loads(await tools["revise"].func(content="body", feedback="tighter"))

    assert continued["ok"] is False
    assert revised["ok"] is False
    assert continued["error"] == revised["error"]


@pytest.mark.asyncio
async def test_setting_write_tools_coerce_group_and_parent_ids() -> None:
    """Public setting tools coerce nested UUID strings and parent IDs."""
    project_id = uuid.UUID(int=21)
    group_id = uuid.UUID(int=22)
    parent_id = uuid.UUID(int=23)
    deps = SettingWriteToolDeps(
        character_service=MagicMock(),
        world_service=MagicMock(),
        audit_service=_audit(),
        expected_project_id=None,
    )
    deps.character_service.create_character = AsyncMock(
        return_value=SimpleNamespace(id="char-1")
    )
    deps.world_service.create_setting = AsyncMock(return_value=SimpleNamespace(id="setting-1"))
    tools = {tool.spec.name: tool for tool in build_setting_write_tools(deps)}

    character = json.loads(
        await tools["create_character"].func(
            project_id=str(project_id),
            name="Name",
            group_ids=[group_id, str(group_id)],
        )
    )
    setting = json.loads(
        await tools["create_world_setting"].func(
            project_id=str(project_id),
            name="Setting",
            parent_id=str(parent_id),
        )
    )

    assert character["ok"] is True
    assert setting["ok"] is True
    character_kwargs = deps.character_service.create_character.await_args.kwargs
    setting_kwargs = deps.world_service.create_setting.await_args.kwargs
    assert character_kwargs["project_id"] == project_id
    assert character_kwargs["group_ids"] == [group_id, group_id]
    assert setting_kwargs["parent_id"] == parent_id


def test_structured_log_store_skips_malformed_rows_and_filters_to_ts(tmp_path: Path) -> None:
    """Public query handles malformed/non-string timestamps and inclusive to_ts."""
    store = StructuredLogStore(tmp_path)
    path = tmp_path / "inkflow_structured_2026-01-01.log"
    rows = [
        "",
        "{bad",
        json.dumps(["not", "a", "record"]),
        json.dumps({"level": 123, "timestamp": "2026-01-01T00:00:00", "event": "bad-level"}),
        json.dumps({"level": "INFO", "timestamp": 123, "event": "non-str-ts"}),
        json.dumps({"level": "INFO", "timestamp": "not-a-time", "event": "bad-ts"}),
        json.dumps(
            {
                "level": "INFO",
                "timestamp": "2026-01-01T00:00:00",
                "event": "naive-ts",
            }
        ),
        json.dumps(
            {
                "level": "INFO",
                "timestamp": "2026-01-02T00:00:00+00:00",
                "event": "too-late",
            }
        ),
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    items, total = store.query(
        level="info",
        to_ts=datetime(2026, 1, 1, 12, tzinfo=UTC),
    )

    assert total == 3
    assert {item["event"] for item in items} == {"non-str-ts", "bad-ts", "naive-ts"}


def test_instrument_scalar_summary_bind_failure_uses_kwargs() -> None:
    """Public decorator logs kwargs when the wrapped call has a binding TypeError."""
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="ERROR")

    @instrument(caller_type="api")
    def needs_one(value: int) -> None:
        return None

    try:
        with pytest.raises(TypeError):
            needs_one(1, unexpected=2)  # type: ignore[call-arg]  # intentional bind failure
    finally:
        logger.remove(sink_id)

    failure = next(record for record in records if record["extra"].get("event") == "needs_one")
    assert failure["extra"]["params"]["unexpected"] == 2
    assert failure["extra"]["params"]["error_type"] == "TypeError"
