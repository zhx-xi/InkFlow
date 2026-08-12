"""#275 服务端防御契约 — DraftService 全零 project_id 拒绝 + 孤儿草稿清理（prune_orphans）.

TDD 铁律（F28 实测）：MODIFY 既有 service 的新方法必须有 unit 级契约文件——
本文件覆盖 DraftService 两处 #275 服务端防线：
1. create: project_id == 全零 UUID（00000000-...0000，rc9 孤儿数据签名）
   → ValueError（服务端 create 校验，孤儿写入直接报错——不依赖 SQLite
   默认无外键约束兜底）
2. prune_orphans(*, dry_run=False) -> int：委托 repo 删除全零 project_id
   草稿（旧孤儿数据清理手段的服务层入口）

被测: inkflow.domain.services.draft_service.DraftService（全 mock repo 轨，
镜像 test_draft_service_update.py 构造形态）。

RED 预期
--------
- test_create_rejects_zero_project_id: 当前实现不校验全零 → repo.create 被调
  → pytest.raises 断言 FAILED（clean FAILED）
- test_create_accepts_normal_project_id: 守护用例（RED 阶段 PASS 刻意）
- prune 两用例: DraftService 无 prune_orphans 方法 → AttributeError FAILED

asyncio 模式: 本 venv 实测 asyncio_mode = "auto"；文件级 pytestmark 双保险。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.domain.services.draft_service import DraftService

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
ZERO_PROJECT_ID = uuid.UUID(int=0)  # #275: rc9 缺陷数据签名（全零 UUID）


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_draft(**overrides) -> Draft:
    kwargs = dict(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=None,
        content="草稿正文。",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
        confirmed_at=None,
    )
    kwargs.update(overrides)
    return Draft(**kwargs)


def _make_service() -> tuple[DraftService, dict[str, AsyncMock]]:
    """构造 DraftService（全 mock repo 轨，镜像 test_draft_service_update.py）。"""
    deps = {
        "draft_repo": AsyncMock(),
        "chapter_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "memory_service": AsyncMock(),
    }
    svc = DraftService(
        draft_repo=deps["draft_repo"],
        chapter_service=deps["chapter_service"],
        audit_service=deps["audit_service"],
        memory_service=deps["memory_service"],
    )
    return svc, deps


# ── #275 防线一: create 拒绝全零 project_id（服务端兜底） ──


async def test_create_rejects_zero_project_id() -> None:
    """#275 服务端兜底: create 全零 project_id → ValueError（孤儿写入直接报错）.

    RED 预期: 当前实现不校验 → 插入照常 → pytest.raises 断言 FAILED。
    """
    svc, deps = _make_service()

    with pytest.raises(ValueError, match="project_id"):
        await svc.create(project_id=ZERO_PROJECT_ID, content="草稿正文。")

    deps["draft_repo"].create.assert_not_awaited()


async def test_create_accepts_normal_project_id() -> None:
    """守护: 正常 project_id 不触发拒绝（向后兼容，RED 阶段 PASS 刻意）。"""
    svc, deps = _make_service()
    deps["draft_repo"].create.return_value = _make_draft()

    draft = await svc.create(project_id=PROJECT_ID, content="草稿正文。")

    assert draft.project_id == PROJECT_ID
    deps["draft_repo"].create.assert_awaited_once()


# ── #275 防线二: prune_orphans（孤儿草稿清理手段的服务层入口） ──


async def test_prune_orphans_delegates_to_repo() -> None:
    """prune_orphans 委托 repo（dry_run=False 删除）并透传删除条数。

    RED 预期: DraftService 无 prune_orphans → AttributeError FAILED。
    """
    svc, deps = _make_service()
    deps["draft_repo"].prune_orphans = AsyncMock(return_value=3)

    count = await svc.prune_orphans()

    assert count == 3
    deps["draft_repo"].prune_orphans.assert_awaited_once_with(dry_run=False)


async def test_prune_orphans_dry_run_forwards_flag() -> None:
    """prune_orphans(dry_run=True) 透传 repo（只统计不删除）。"""
    svc, deps = _make_service()
    deps["draft_repo"].prune_orphans = AsyncMock(return_value=2)

    count = await svc.prune_orphans(dry_run=True)

    assert count == 2
    deps["draft_repo"].prune_orphans.assert_awaited_once_with(dry_run=True)
