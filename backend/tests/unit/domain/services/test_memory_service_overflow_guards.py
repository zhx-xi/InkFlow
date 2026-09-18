"""#633 溢出守卫补测：memory_service 三个方法对「越界项目 UUID」的降级语义（2026-08-24）.

⚠️ **契约变更（#1134 批 4 / #1291，2026-09-19）**：服务层的
`project_id.int > 2**63 - 1` 早退守卫**已退役** —— 越界判定收敛到 repo 层
`require_uuid_pk`（返回 None = 不存在）。服务层不再自行 `.int` 预检。

本文件因此改为断言**可观测语义不变**：越界 UUID ⇒
- `is_learning_enabled` → False；
- `get_preferences_for_injection` → []；
- `summarize` → skipped 结构。
驱动方式改为「repo.get 返回 None（越界 UUID 在 repo 层的等价结果）」。

依据：#1134 批 4（#1291）· ADR-060 D9 收窄契约。原守卫由来见 #633。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.services.memory_service import MemoryService

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

OVERFLOW_ID = uuid.UUID(int=2**63)  # > 2**63 - 1，SQLite INTEGER 绑定上限


def _make_service() -> tuple[MemoryService, dict]:
    """构造 MemoryService + 依赖字典（全 AsyncMock，同 test_memory_service*.py 模式）."""
    deps = {
        "preference_repo": AsyncMock(),
        "event_repo": AsyncMock(),
        "project_repo": AsyncMock(),
        "audit_service": AsyncMock(),
    }
    deps["preference_repo"].list_by_project.return_value = ([], 0)
    # #1291：越界 UUID 在 repo 层的等价结果 = 查不到（require_uuid_pk → None）
    deps["project_repo"].get.return_value = None
    deps["event_repo"].list_by_project.return_value = ([], 0)
    service = MemoryService(
        preference_repo=deps["preference_repo"],
        event_repo=deps["event_repo"],
        project_repo=deps["project_repo"],
        audit_service=deps["audit_service"],
    )
    return service, deps


async def test_is_learning_enabled_overflow_uuid_returns_false() -> None:
    """越界 project UUID（repo 层查不到）→ False."""
    service, deps = _make_service()
    assert await service.is_learning_enabled(OVERFLOW_ID) is False
    deps["project_repo"].get.assert_awaited()  # #1291：判定权移交 repo 层


async def test_get_preferences_for_injection_overflow_uuid_returns_empty() -> None:
    """越界 project UUID（repo 层查不到）→ []."""
    service, deps = _make_service()
    # 开关短路在前——视为已通过，直达项目读取分支
    service.is_learning_enabled = AsyncMock(return_value=True)
    assert await service.get_preferences_for_injection(OVERFLOW_ID) == []
    deps["preference_repo"].list_by_project.assert_awaited_once_with(OVERFLOW_ID)


async def test_summarize_overflow_uuid_returns_skipped_structure() -> None:
    """越界 project UUID（repo 层查不到）→ skipped 结构."""
    service, deps = _make_service()
    result = await service.summarize(OVERFLOW_ID)
    assert result == {
        "project_id": str(OVERFLOW_ID),
        "summarized": False,
        "project": None,
        "user": None,
    }
    deps["project_repo"].get.assert_awaited()  # #1291：判定权移交 repo 层
