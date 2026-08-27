"""#718 RED 契约测试 — save_draft 写工具绑定项目上下文（不再要求 LLM 自报 project_id）.

背景（根因实证）: #680 已让 5 个只读工具 schema 移除 project_id（装配期闭包绑定），
但 save_draft 仍保留 project_id 必填（save_draft_tool.py:26-34 SaveDraftParams），
与 chat 系统提示词 `_CHAT_SYSTEM_AGENT_PROMPT`（"当前项目已绑定…无需用户提供项目 ID"）
矛盾 → LLM 或省略 project_id（_save_draft 缺参 TypeError，实测）或误报 project_id
（_validate_context 校验不符 → {ok:False}，实测）→ 工具失败 → agent 循环无法收敛 →
前端无限 running。

本文件锁定的契约（决策已拍板）:
1. `SaveDraftParams` 移除 `project_id`/`chapter_id` 字段（LLM 不感知、无需自报）。
2. `_save_draft` 在 `deps.expected_project_id/chapter_id` 注入时 **总是使用绑定值**
   （LLM 无法编造/误报 id → 消灭 {ok:False} 循环来源）；未注入时回退 caller 传入值
   （MCP / F27 writer 兼容，shim 保留 project_id/chapter_id 可选参）。
3. 工具吞一切异常 → {ok:False} 信封（不抛出）。
4. 成功: {"ok": True, "draft_id", "status": "draft", "word_count"}；草稿落库+审计。

RED 预期（对照当前实现）:
- test_save_draft_tool_spec: schema["properties"] 当前含 project_id → 断言"不在" FAILED。
- test_save_draft_params_validation: SaveDraftParams(project_id=...) 当前合法 → 断言
  project_id 字段不存在 FAILED。
- test_save_draft_without_self_reported_id: 当前 _save_draft 缺 project_id → TypeError FAILED。
- test_uses_bound_expected_project_id: 当前要求 caller 传 project_id（省略则 TypeError）
  → FAILED。
- test_ignores_conflicting_caller_project_id: 当前 caller 传错 id → {ok:False}（拒绝）；
  断言"使用绑定值成功" FAILED。
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.domain.services._word_count import count_words
from inkflow.infrastructure.agent.tools.reader_tools import Tool
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SaveDraftParams,
    SaveDraftToolDeps,
    build_save_draft_tool,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
WRONG_ID = uuid.UUID("99999999-9999-4999-8999-999999999999")

CONTENT = "第一章 测试内容。这是草稿正文，用于验证 save_draft 工具契约。"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_draft(**overrides) -> Draft:
    kwargs = dict(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content=CONTENT,
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
        confirmed_at=None,
    )
    kwargs.update(overrides)
    return Draft(**kwargs)


def _make_deps(**overrides) -> SaveDraftToolDeps:
    deps = SaveDraftToolDeps(
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


# ── 契约: 工具定义 ──


def test_save_draft_tool_spec() -> None:
    """契约①: spec.name 固定 save_draft；schema 不再暴露 project_id/chapter_id."""
    deps = _make_deps()
    tool = build_save_draft_tool(deps)

    assert isinstance(tool, Tool)
    assert tool.spec.name == "save_draft"
    assert "草稿" in tool.spec.description
    assert "确认" in tool.spec.description
    # #718: LLM 不感知 project_id/chapter_id（绑定在装配期 deps）
    schema = tool.spec.input_schema
    properties = schema.get("properties", {})
    assert "content" in properties
    assert "project_id" not in properties
    assert "chapter_id" not in properties
    assert schema.get("required") == ["content"]


def test_save_draft_params_validation() -> None:
    """契约②: SaveDraftParams 仅 content 必填、summary 可选（无 project_id/chapter_id）. """
    params = SaveDraftParams(content=CONTENT)
    assert params.summary is None
    # project_id/chapter_id 字段已移除
    assert not hasattr(params, "project_id")
    assert not hasattr(params, "chapter_id")

    with pytest.raises(ValidationError):
        SaveDraftParams()  # content 必填


# ── 契约: 成功路径（绑定 project_id + 草稿落库 + 审计 + 单事务） ──


async def test_save_draft_without_self_reported_id_does_not_raise() -> None:
    """契约③: LLM 省略 project_id（chat 提示词"无需提供"）→ 工具不抛 TypeError，成功落库."""
    deps = _make_deps(expected_project_id=PROJECT_ID, expected_chapter_id=CHAPTER_ID)
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    # 不传 project_id/chapter_id —— 当前实现会 TypeError（缺必填参）→ RED
    result = await tool.func(content=CONTENT)

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["draft_id"] == "draft-1"
    assert payload["status"] == "draft"
    assert payload["word_count"] == count_words(CONTENT)
    deps.draft_service.create.assert_awaited_once()


async def test_uses_bound_expected_project_id() -> None:
    """契约④: deps 注入 expected_project_id → 工具总是使用绑定值（非 caller 缺省）."""
    deps = _make_deps(expected_project_id=PROJECT_ID, expected_chapter_id=CHAPTER_ID)
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    result = await tool.func(content=CONTENT)

    payload = json.loads(result)
    assert payload["ok"] is True
    create_call = deps.draft_service.create.await_args
    # 绑定值 = deps.expected_*（LLM 无需/不能指定 project/chapter）
    assert create_call.kwargs["project_id"] == PROJECT_ID
    assert create_call.kwargs["chapter_id"] == CHAPTER_ID


async def test_ignores_conflicting_caller_project_id_uses_bound() -> None:
    """契约⑤: caller 误传错 project_id，但 deps 已绑定 → 工具用绑定值成功（不 reject）.

    #718 根因: 旧实现 _validate_context 对不符 project_id 拒绝 → {ok:False} → LLM
    循环失败。修复后绑定值优先，LLM 无法注入错误 id → 不再 {ok:False} 循环。
    """
    deps = _make_deps(expected_project_id=PROJECT_ID, expected_chapter_id=CHAPTER_ID)
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    result = await tool.func(project_id=WRONG_ID, chapter_id=WRONG_ID, content=CONTENT)

    payload = json.loads(result)
    assert payload["ok"] is True  # 旧实现: {ok:False}（不符拒绝）→ RED
    create_call = deps.draft_service.create.await_args
    assert create_call.kwargs["project_id"] == PROJECT_ID
    assert create_call.kwargs["chapter_id"] == CHAPTER_ID


async def test_binds_expected_chapter_id_when_omitted() -> None:
    """契约⑥: deps 绑定 expected_chapter_id，LLM 省略 chapter_id → 工具用绑定章节."""
    deps = _make_deps(expected_project_id=PROJECT_ID, expected_chapter_id=CHAPTER_ID)
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    result = await tool.func(content=CONTENT)

    payload = json.loads(result)
    assert payload["ok"] is True
    create_call = deps.draft_service.create.await_args
    assert create_call.kwargs["chapter_id"] == CHAPTER_ID


async def test_no_expected_context_falls_back_to_caller() -> None:
    """契约⑦: deps 未注入 expected（None）→ 回退 caller 传入值（MCP/F27 writer 兼容）."""
    deps = _make_deps()
    deps.draft_service.create.return_value = _make_draft(chapter_id=None)
    tool = build_save_draft_tool(deps)

    result = await tool.func(project_id=PROJECT_ID, content=CONTENT)

    payload = json.loads(result)
    assert payload["ok"] is True
    create_call = deps.draft_service.create.await_args
    assert create_call.kwargs["project_id"] == PROJECT_ID


async def test_save_draft_service_error_returns_ok_false() -> None:
    """契约⑧: draft_service 抛异常 → {"ok": false, "error": "..."} 不抛出（吞异常回信封）."""
    deps = _make_deps(expected_project_id=PROJECT_ID, expected_chapter_id=CHAPTER_ID)
    deps.draft_service.create.side_effect = RuntimeError("数据库连接失败")
    tool = build_save_draft_tool(deps)

    result = await tool.func(content=CONTENT)

    payload = json.loads(result)
    assert payload["ok"] is False
    assert "数据库连接失败" in payload["error"]
    deps.audit_service.record.assert_awaited()  # 失败亦落审计


async def test_save_draft_empty_content_error_envelope() -> None:
    """契约⑨: 空 content 被 service 拒 → {ok:False} 信封（service 层校验，工具透传）."""
    deps = _make_deps(expected_project_id=PROJECT_ID)
    deps.draft_service.create.side_effect = ValueError("草稿内容不能为空")
    tool = build_save_draft_tool(deps)

    result = await tool.func(content="")

    payload = json.loads(result)
    assert payload["ok"] is False
    assert "不能为空" in payload["error"]


# ── 契约: 标题/审计 ──


async def test_save_draft_audit_records_on_success() -> None:
    """契约⑩: 成功路径 audit_service.record 被调（actor=agent:writer，含草稿摘要）."""
    deps = _make_deps(expected_project_id=PROJECT_ID)
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    await tool.func(content=CONTENT)

    deps.audit_service.record.assert_awaited_once()
    call = deps.audit_service.record.await_args
    assert call.kwargs["project_id"] == PROJECT_ID
    assert call.kwargs["actor"] == "agent:writer"
