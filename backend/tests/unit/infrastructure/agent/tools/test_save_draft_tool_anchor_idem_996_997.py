"""#996/#997 RED 契约测试 — save_draft 工具锚点传递 + 同章幂等覆盖.

契约真相源: specs/f27-writer-agent/spec.md §5.2「装配期锚点绑定 + 同章幂等（#996/#997
增量）」+ specs/f44-book-orchestrator/spec.md §5.2「章级幂等写 v1.7 #997 修订」+
「锚点传递（#996）」。拍板契约回顾:

A. SaveDraftToolDeps 新增字段（默认 None）:
   expected_source_outline_id / expected_volume_outline_id
B. 工具 create kwargs source_outline_id = deps.expected_source_outline_id
   （chat 轨未注入时仍 None 透传——#988 既有测试用 .get(...) is None 判定，不翻转）。
C. 工具 volume_lookup 查表键优先级:
   bound_chapter_id（非 None 时）→ expected_volume_outline_id → expected_source_outline_id。
D. 工具幂等（#997）: 归组键（bound_chapter_id / expected_source_outline_id 至少其一非 None）
   时，create 前调 draft_service.find_pending(project_id, chapter_id=bound_chapter_id,
   source_outline_id=expected_source_outline_id):
   - 返回 Draft 实例 → replace_content(同 id, content, summary)；不调 create、不调
     volume_lookup；payload overritten:true + draft_id 同值；audit 照落。
   - 返回 None → 既有 create 路径（payload 不含 overwritten 键）。
   - 两归组键皆 None → 不调 find_pending 直接 create（chat 轨零回归）。
   - find_pending 返回值非 Draft（裸 AsyncMock 自动子 Mock）→ 视为未命中走 create。
   - replace_content 抛异常 → 既有 except 信封 {ok:false}（不抛出）。

当前实现对照（全部 RED）: SaveDraftToolDeps 无两个锚点字段（字段存在性断言 FAIL）；_save_draft
L136 硬编码 source_outline_id=None（B 断言 FAIL）；volume_lookup 恒传 _chapter_id（None）不
按优先级解析（C 断言 FAIL）；从不调 find_pending/replace_content（D 断言 FAIL）。

镜像 test_save_draft_tool.py / tools/test_save_draft_tool_source_outline_988.py 形态
（AsyncMock draft_service + tool.func 直调 + await_args.kwargs 断言）。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import fields
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.domain.services._word_count import count_words
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SaveDraftToolDeps,
    build_save_draft_tool,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
SOURCE_OUTLINE_ID = uuid.UUID(int=51)
VOLUME_OUTLINE_ID = uuid.UUID(int=41)
CONTENT = "第一章 测试内容。这是草稿正文，用于验证 save_draft 工具锚点与幂等契约。"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_draft(**overrides) -> Draft:
    kwargs: dict = dict(
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
    """构造 SaveDraftToolDeps（镜像既有 _make_deps 的 setattr 注入习惯）。

    默认不设置两个锚点字段（chat 轨形态）。锚点用例用 _make_anchor_deps。
    """
    deps = SaveDraftToolDeps(
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
        expected_project_id=PROJECT_ID,
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


def _make_anchor_deps(**overrides) -> SaveDraftToolDeps:
    """构造带 #996 锚点字段的 deps（当前 dataclass 缺失 → setattr 注入使工具逻辑可达）。

    锚点字段经 setattr 注入后，工具行为断言（而非 TypeError）成为 RED 主锚——因为
    现有实现根本不读这两个字段，行为自然偏离契约。
    """
    deps = _make_deps(expected_chapter_id=CHAPTER_ID)
    deps.expected_source_outline_id = None
    deps.expected_volume_outline_id = None
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


def _arg_or_kw(call, name: str, index: int, default=None):
    """宽松取 mock 调用参数：优先关键字，回退位置参数（兼容两种 GREEN 形态）。"""
    args, kwargs = call
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else default


# ── 契约 B/C: 锚点字段 + create source_outline_id 注入 ──


def test_deps_declares_anchor_fields() -> None:
    """【A/RED】SaveDraftToolDeps 声明两锚点字段（expected_source_outline_id/volume）。

    当前 dataclass 无这两个字段 → 字段名集合不含它们 → 断言 FAILED。
    """
    names = {f.name for f in fields(SaveDraftToolDeps)}
    assert "expected_source_outline_id" in names
    assert "expected_volume_outline_id" in names


async def test_create_source_outline_id_uses_anchor() -> None:
    """【B/RED】deps 注入锚点 → create kwargs source_outline_id == 锚点（不再恒 None）。

    当前 _save_draft L136 硬编码 source_outline_id=None → await_args.kwargs 为 None → FAILED。
    """
    deps = _make_anchor_deps(expected_source_outline_id=SOURCE_OUTLINE_ID)
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    await tool.func(content=CONTENT)

    create_call = deps.draft_service.create.await_args
    assert create_call is not None
    assert create_call.kwargs["source_outline_id"] == SOURCE_OUTLINE_ID


async def test_create_source_outline_id_none_when_no_anchor() -> None:
    """【B 守护/PASS】chat 轨未注入锚点 → create source_outline_id 仍 None（零回归）。"""
    deps = _make_deps()
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    await tool.func(content=CONTENT)

    create_call = deps.draft_service.create.await_args
    assert create_call is not None
    assert create_call.kwargs.get("source_outline_id") is None


# ── 契约 C: volume_lookup 查表键优先级 ──


async def test_volume_lookup_prefers_bound_chapter_id() -> None:
    """【C 守护/既有】bound_chapter_id 非 None 时查表键 = bound_chapter_id（优先级一级）。

    当前实现恒传 _chapter_id（=bound_chapter_id）→ 该守护 PASS（既有语义保留）。
    """
    recorded: dict = {}

    async def _vol(project_id, key):
        recorded["key"] = key
        return

    deps = _make_anchor_deps(
        expected_source_outline_id=SOURCE_OUTLINE_ID,
        expected_volume_outline_id=VOLUME_OUTLINE_ID,
        volume_lookup=_vol,
    )
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    await tool.func(content=CONTENT)

    assert recorded["key"] == CHAPTER_ID


async def test_volume_lookup_falls_back_to_volume_outline() -> None:
    """【C/RED】bound_chapter_id 为 None 且注入 volume_outline 锚点 → 查表键 = volume_outline。

    当前实现恒传 _chapter_id（None）→ recorded["key"] 为 None ≠ VOLUME_OUTLINE_ID → FAILED。
    """
    recorded: dict = {}

    async def _vol(project_id, key):
        recorded["key"] = key
        return str(uuid.UUID(int=5))

    deps = SaveDraftToolDeps(
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
        expected_project_id=PROJECT_ID,
    )
    deps.expected_source_outline_id = None
    deps.expected_volume_outline_id = VOLUME_OUTLINE_ID
    deps.volume_lookup = _vol
    deps.draft_service.create.return_value = _make_draft(volume_id=uuid.UUID(int=5))
    tool = build_save_draft_tool(deps)

    await tool.func(content=CONTENT)

    assert recorded["key"] == VOLUME_OUTLINE_ID
    # 命中卷后 create 仍收 volume_id（既有 #976 语义保留）
    assert deps.draft_service.create.await_args.kwargs["volume_id"] == uuid.UUID(int=5)


async def test_volume_lookup_falls_back_to_source_outline() -> None:
    """【C/RED】chapter 与 volume_outline 皆 None 时查表键 = source_outline（兜底）。

    当前实现恒传 _chapter_id（None）→ recorded["key"] 为 None ≠ SOURCE_OUTLINE_ID → FAILED。
    """
    recorded: dict = {}

    async def _vol(project_id, key):
        recorded["key"] = key
        return

    deps = SaveDraftToolDeps(
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
        expected_project_id=PROJECT_ID,
    )
    deps.expected_source_outline_id = SOURCE_OUTLINE_ID
    deps.expected_volume_outline_id = None
    deps.volume_lookup = _vol
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    await tool.func(content=CONTENT)

    assert recorded["key"] == SOURCE_OUTLINE_ID


# ── 契约 D: 同章幂等覆盖 ──


async def test_idempotent_hit_overwrites_content() -> None:
    """【D/RED】find_pending 命中 Draft → create 不被调、replace_content 收到 (id, content)、
    volume_lookup 不被调；payload overritten:true + draft_id 同值。

    当前实现忽略 find_pending 恒走 create、不调 volume_lookup 前置幂等 → 断言全 FAILED。
    """
    deps = _make_anchor_deps(
        expected_source_outline_id=SOURCE_OUTLINE_ID,
        volume_lookup=AsyncMock(return_value=None),
    )
    existing = _make_draft(id="draft-99")
    deps.draft_service.find_pending.return_value = existing
    deps.draft_service.replace_content.return_value = existing
    deps.draft_service.create.return_value = _make_draft(id="draft-1")
    tool = build_save_draft_tool(deps)

    result = await tool.func(content=CONTENT)

    payload = json.loads(result)
    # 命中覆盖: 不新增草稿（create 不被调）
    deps.draft_service.create.assert_not_awaited()
    deps.draft_service.volume_lookup.assert_not_awaited()
    deps.draft_service.find_pending.assert_awaited_once()
    deps.draft_service.replace_content.assert_awaited_once()
    call = deps.draft_service.replace_content.await_args
    assert _arg_or_kw(call, "draft_id", 0) == existing.id
    assert _arg_or_kw(call, "content", 1) == CONTENT
    assert payload["ok"] is True
    assert payload["draft_id"] == existing.id
    assert payload["status"] == "draft"
    assert payload["word_count"] == count_words(CONTENT)
    assert payload["overwritten"] is True


async def test_idempotent_hit_passes_summary_none() -> None:
    """【D/RED】覆盖时 summary 缺省（None）→ replace_content 收到 summary=None（保原值）。"""
    deps = _make_anchor_deps(expected_source_outline_id=SOURCE_OUTLINE_ID)
    existing = _make_draft(id="draft-99")
    deps.draft_service.find_pending.return_value = existing
    deps.draft_service.replace_content.return_value = existing
    deps.draft_service.create.return_value = _make_draft(id="draft-1")
    tool = build_save_draft_tool(deps)

    await tool.func(content=CONTENT)

    call = deps.draft_service.replace_content.await_args
    assert call is not None
    assert _arg_or_kw(call, "summary", 2, None) is None


async def test_idempotent_hit_passes_summary_value() -> None:
    """【D/RED】覆盖时 summary = 非空值 → replace_content 收到该 summary。"""
    deps = _make_anchor_deps(expected_source_outline_id=SOURCE_OUTLINE_ID)
    existing = _make_draft(id="draft-99")
    deps.draft_service.find_pending.return_value = existing
    deps.draft_service.replace_content.return_value = existing
    deps.draft_service.create.return_value = _make_draft(id="draft-1")
    tool = build_save_draft_tool(deps)

    await tool.func(content=CONTENT, summary="新摘要")

    call = deps.draft_service.replace_content.await_args
    assert call is not None
    assert _arg_or_kw(call, "summary", 2, None) == "新摘要"


async def test_idempotent_miss_create_path() -> None:
    """【D/RED】find_pending 返回 None → 走既有 create 路径，payload 无 overwritten 键。

    当前实现从不调 find_pending（assert_awaited_once FAILED）且 create source_outline_id
    恒 None（≠ 锚点 FAILED）。
    """
    deps = _make_anchor_deps(expected_source_outline_id=SOURCE_OUTLINE_ID)
    deps.draft_service.find_pending.return_value = None
    deps.draft_service.create.return_value = _make_draft(id="draft-1")
    tool = build_save_draft_tool(deps)

    result = await tool.func(content=CONTENT)

    payload = json.loads(result)
    deps.draft_service.find_pending.assert_awaited_once()
    deps.draft_service.create.assert_awaited_once()
    create_call = deps.draft_service.create.await_args
    assert create_call.kwargs["source_outline_id"] == SOURCE_OUTLINE_ID
    assert "overwritten" not in payload
    assert payload["ok"] is True


async def test_idempotent_no_anchor_no_find_pending() -> None:
    """【D 守护/PASS】两归组键皆 None → 不调 find_pending，直接 create（chat 轨零回归）。"""
    deps = _make_deps()  # 无 expected_chapter_id、无锚点字段 → bound_chapter_id None
    deps.draft_service.create.return_value = _make_draft(id="draft-1")
    tool = build_save_draft_tool(deps)

    result = await tool.func(content=CONTENT)  # 不传 caller chapter_id → bound_chapter_id None

    deps.draft_service.find_pending.assert_not_awaited()
    deps.draft_service.create.assert_awaited_once()
    assert json.loads(result)["ok"] is True


async def test_idempotent_auto_mock_find_pending_duck_create() -> None:
    """【D 守护/PASS】find_pending 返回裸 AsyncMock（非 Draft 实例）→ 视为未命中走 create。

    鸭子兼容（既有 #718 测试不翻转）: 当前实现恒走 create → 本守护 PASS。
    """
    deps = _make_anchor_deps(expected_source_outline_id=SOURCE_OUTLINE_ID)
    # 不设置 find_pending.return_value → AsyncMock 自动返回 AsyncMock（非 Draft）
    deps.draft_service.create.return_value = _make_draft(id="draft-1")
    tool = build_save_draft_tool(deps)

    result = await tool.func(content=CONTENT)

    payload = json.loads(result)
    assert payload["ok"] is True
    deps.draft_service.create.assert_awaited_once()


async def test_idempotent_replace_error_returns_ok_false() -> None:
    """【D/RED】replace_content 抛异常 → 既有 except 信封 {ok:false}（不抛出）+ 审计照落。

    当前实现从不调 replace_content 恒走 create → payload["ok"] is True → FAILED。
    """
    deps = _make_anchor_deps(expected_source_outline_id=SOURCE_OUTLINE_ID)
    existing = _make_draft(id="draft-99")
    deps.draft_service.find_pending.return_value = existing
    deps.draft_service.replace_content.side_effect = RuntimeError("数据库连接失败")
    deps.draft_service.create.return_value = _make_draft(id="draft-1")
    tool = build_save_draft_tool(deps)

    result = await tool.func(content=CONTENT)

    payload = json.loads(result)
    assert payload["ok"] is False
    assert "数据库连接失败" in payload["error"]
    deps.audit_service.record.assert_awaited()
