"""#1430 方案 A：`book run` 显式覆盖（force + confirm_overwrite 双条件）契约（RED→GREEN）。

权威来源：issue #1430（用户 2026-10-01 拍板 A2）+ PR #1427 设计结论。

语义（本契约冻结）
==================

1. **双条件**：`force` 与 `confirm_overwrite` **必须成对**提供；只给其一 →
   `ValueError`（API 层 422）。目的是防止任何自动化链路**静默**带上 force
   （覆盖正文 = 数据丢失，必须有人显式二次确认）。
2. **force 只做显式跳过**：`force=True + confirm_overwrite=True` 时跳过
   「内容已写」安全闸（#1265 判据本身**零改动**）；`force=False` 时既有闸门
   行为**逐字不变**（本文件有对照组守护）。
3. **备份落点随响应可见**（硬约束「不做静默备份」）：force 响应必须带
   `overwrite` 块，明说备份落点 = `chapters.previous_content` 与**待备份章数**
   （= 目标章中当前已有正文、覆盖时会被快照的章数），否则用户不知道去哪找回。
4. **后台执行体同样生效**：`write_book` / `write_book_volume` 也吃 `force`
   （`prepare_run` 只预检 + 落 running；真正写正文的是后台的 write_book*，
   若它们不跳闸，force 会在后台立刻 409 等价的失败 → 特性等于没做）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService, ChapterAlreadyWrittenError

_PLAN_ID = uuid.UUID("01920000-0000-7000-8000-000000001440")
_PROJECT_ID = uuid.UUID("01920000-0000-7000-8000-000000001441")
_CHAPTER_ID = uuid.UUID("01920000-0000-7000-8000-000000001442")
_OUTLINE_ID = uuid.UUID("01920000-0000-7000-8000-000000001443")

_BACKUP_TARGET = "chapters.previous_content"


def _chapter() -> Outline:
    """目标章节点（level=chapter，挂 chapter_id → content_checker 参与判据）。"""
    now = datetime.now(UTC)
    return Outline(
        id=_OUTLINE_ID,
        project_id=_PROJECT_ID,
        name="第一章",
        description="开篇",
        level="chapter",
        sort_order=1,
        chapter_id=_CHAPTER_ID,
        created_at=now,
        updated_at=now,
    )


def _plan() -> WritingPlan:
    """可执行态的 plan（status=ready，无执行痕迹）。"""
    return WritingPlan(
        id=_PLAN_ID,
        project_id=_PROJECT_ID,
        title="测试书",
        status="ready",
        progress={},
        execution_refs={},
        limits={"max_chapters": 100, "max_agent_calls": 200},
    )


async def _find_chapters_stub(_plan: object) -> list[Outline]:
    return [_chapter()]


async def _find_volumes_stub(_plan: object) -> list[dict]:
    """卷划分替身：单卷单章（章 dict 形态，镜像 _outline_to_chapter_dict 产物）。"""
    chapter = _chapter()
    return [
        {
            "volume_id": None,
            "chapters": [
                {
                    "outline_id": chapter.id,
                    "chapter_id": chapter.chapter_id,
                    "name": chapter.name,
                    "description": chapter.description,
                    "sort_order": chapter.sort_order,
                    "volume_outline_id": None,
                    "writing_requirements": None,
                }
            ],
        }
    ]


def _build_service(*, content_written: bool) -> tuple[BookService, AsyncMock]:
    """装配 BookService：闸门结论只取决于 content_checker（镜像 #1265/#1282 契约形状）。

    writer_factory 返回可用的假 agent（``invoke`` 落一条正文消息），否则委托会走
    failed 分支、`write_book(force=True)` 的「真的委托了」断言失去意义。
    """
    plan = _plan()
    repo = AsyncMock()
    repo.get_writing_plan = AsyncMock(return_value=plan)
    repo.update_writing_plan = AsyncMock()
    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="覆盖后的新正文", tool_calls=[])]
    }
    writer_factory = AsyncMock(return_value=fake_agent)
    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1430")
    svc = BookService(
        repo=repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
        outline_repo=AsyncMock(),
        limits=BookLimits(),
        content_checker=AsyncMock(return_value=content_written),
    )
    svc._find_chapters = _find_chapters_stub  # type: ignore[method-assign]  # 章节点解析出 DB，测试注入替身
    svc._find_volumes = _find_volumes_stub  # type: ignore[method-assign]  # 卷划分解析出 DB，测试注入替身
    return svc, repo


# ── 双条件 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prepare_run_force_without_confirm_rejected() -> None:
    """只给 force 不给 confirm_overwrite → ValueError（防自动化静默覆盖）。"""
    svc, _repo = _build_service(content_written=True)

    with pytest.raises(ValueError, match="confirm_overwrite"):
        await svc.prepare_run(_PLAN_ID, force=True)


@pytest.mark.asyncio
async def test_prepare_run_confirm_without_force_rejected() -> None:
    """只给 confirm_overwrite 不给 force → ValueError（反之亦然）。"""
    svc, _repo = _build_service(content_written=True)

    with pytest.raises(ValueError, match="force"):
        await svc.prepare_run(_PLAN_ID, confirm_overwrite=True)


@pytest.mark.asyncio
async def test_prepare_run_force_without_confirm_rejected_even_when_no_content() -> None:
    """双条件是**入口不变量**：与「是否有正文」无关（空书也只给 force 同样拒绝）。"""
    svc, _repo = _build_service(content_written=False)

    with pytest.raises(ValueError, match="confirm_overwrite"):
        await svc.prepare_run(_PLAN_ID, force=True)


# ── force 跳过安全闸 + 备份可见 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_prepare_run_force_with_confirm_skips_gate_and_reports_backup() -> None:
    """force + confirm → 跳过安全闸转 running，且响应明说备份落点与待备份章数。"""
    svc, _repo = _build_service(content_written=True)

    result = await svc.prepare_run(_PLAN_ID, force=True, confirm_overwrite=True)

    assert result["status"] == "running"
    assert result["overwrite"] == {
        "forced": True,
        "backup_target": _BACKUP_TARGET,
        "chapters_to_backup": 1,
    }


@pytest.mark.asyncio
async def test_prepare_run_force_reports_zero_backup_when_nothing_written() -> None:
    """无旧正文可备份 → chapters_to_backup=0（用户据此知道没有备份可落）。"""
    svc, _repo = _build_service(content_written=False)

    result = await svc.prepare_run(_PLAN_ID, force=True, confirm_overwrite=True)

    assert result["status"] == "running"
    assert result["overwrite"] == {
        "forced": True,
        "backup_target": _BACKUP_TARGET,
        "chapters_to_backup": 0,
    }


# ── 非 force 路径零变化（对照组，闸门判据 #1265 原样） ──────────────────


@pytest.mark.asyncio
async def test_prepare_run_non_force_still_blocks_written_chapter() -> None:
    """非 force 路径零变化：正文仍在 → 照旧 ChapterAlreadyWrittenError。"""
    svc, _repo = _build_service(content_written=True)

    with pytest.raises(ChapterAlreadyWrittenError, match="已有内容"):
        await svc.prepare_run(_PLAN_ID)


@pytest.mark.asyncio
async def test_prepare_run_non_force_response_has_no_overwrite_block() -> None:
    """非 force 响应不带 overwrite 块（既有响应形状零变化）。"""
    svc, _repo = _build_service(content_written=False)

    result = await svc.prepare_run(_PLAN_ID)

    assert result == {"run_id": str(_PLAN_ID), "status": "running"}


# ── 后台执行体：force 必须同样生效 ────────────────────────────────────


@pytest.mark.asyncio
async def test_write_book_force_skips_gate_and_delegates() -> None:
    """write_book(force=True) 跳过安全闸并真的委托（后台路径不跳闸 = 特性等于没做）。"""
    svc, _repo = _build_service(content_written=True)

    result = await svc.write_book(_PLAN_ID, force=True)

    assert result["status"] in {"completed", "running", "degraded"}
    svc._writer_factory.assert_awaited()  # type: ignore[attr-defined]  # 鸭子属性


@pytest.mark.asyncio
async def test_write_book_without_force_still_blocks() -> None:
    """write_book(force=False) 零变化：正文仍在 → 拒绝，零 LLM 委托。"""
    svc, _repo = _build_service(content_written=True)

    with pytest.raises(ChapterAlreadyWrittenError, match="已有内容"):
        await svc.write_book(_PLAN_ID)

    svc._writer_factory.assert_not_awaited()  # type: ignore[attr-defined]  # 鸭子属性


@pytest.mark.asyncio
async def test_write_book_volume_force_skips_gate() -> None:
    """卷级轨 write_book_volume(force=True) 同样跳过安全阀（三轨口径一致）。"""
    svc, _repo = _build_service(content_written=True)
    pipeline = AsyncMock()
    pipeline.execute = AsyncMock(return_value={"status": "completed"})
    svc._volume_pipeline = pipeline  # type: ignore[assignment]  # 鸭子管道替身

    result = await svc.write_book_volume(_PLAN_ID, force=True)

    assert result["run_id"] == str(_PLAN_ID)
    pipeline.execute.assert_awaited()


@pytest.mark.asyncio
async def test_write_book_volume_without_force_still_blocks() -> None:
    """卷级轨非 force 零变化：安全阀仍在，pipeline 零调用。"""
    svc, _repo = _build_service(content_written=True)
    pipeline = AsyncMock()
    svc._volume_pipeline = pipeline  # type: ignore[assignment]  # 鸭子管道替身

    with pytest.raises(ChapterAlreadyWrittenError, match="已有内容"):
        await svc.write_book_volume(_PLAN_ID)

    pipeline.execute.assert_not_awaited()
