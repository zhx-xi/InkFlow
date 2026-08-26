"""#633 溢出守卫补测：memory_service 三个未覆盖分支（2026-08-24）.

PR #633（main @ 84e2ee8）为 5 个方法加了 `project_id.int > 2**63 - 1` 早退守卫；
API 层测试已覆盖 get_summaries / remove_summaries（HTTP 可见路径），CI coverage-backend
门禁 branch=94.98% < 95% 差在其余 3 个守卫：

- is_learning_enabled → False；
- get_preferences_for_injection → []；
- summarize → {"project_id", "summarized": False, "project": None, "user": None}.

本文件用鸭子类型 mock（同 test_memory_service_coverage.py 的 fixture 模式）分别触发
3 个守卫的 True 分支，并断言 project_repo.get 未被 await（溢出 UUID 不应落到 64 位
int 背书查询）。注意 get_preferences_for_injection 的内层守卫位于 is_learning_enabled
之后——同一溢出 UUID 会先被开关短路，故该用例将开关视为已通过（AsyncMock 恒 True），
直达内层 2**63-1 守卫。
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
    service = MemoryService(
        preference_repo=deps["preference_repo"],
        event_repo=deps["event_repo"],
        project_repo=deps["project_repo"],
        audit_service=deps["audit_service"],
    )
    return service, deps


async def test_is_learning_enabled_overflow_uuid_returns_false() -> None:
    """#633 守卫①: project_id.int 溢出 → 短路返回 False，不查 project_repo.get."""
    service, deps = _make_service()
    assert await service.is_learning_enabled(OVERFLOW_ID) is False
    deps["project_repo"].get.assert_not_awaited()


async def test_get_preferences_for_injection_overflow_uuid_returns_empty() -> None:
    """#633 守卫②: 开关通过后 project_id.int 溢出 → 短路返回 []，不调 project_repo.get."""
    service, deps = _make_service()
    # 内层守卫位于 is_learning_enabled 之后，同一溢出 UUID 会先被开关短路；
    # 故将开关视为已通过（AsyncMock 恒 True），直达 2**63-1 守卫分支。
    service.is_learning_enabled = AsyncMock(return_value=True)
    assert await service.get_preferences_for_injection(OVERFLOW_ID) == []
    deps["preference_repo"].list_by_project.assert_awaited_once_with(OVERFLOW_ID)
    deps["project_repo"].get.assert_not_awaited()


async def test_summarize_overflow_uuid_returns_skipped_structure() -> None:
    """#633 守卫③: project_id.int 溢出 → 短路返回 skipped 结构，不查 project_repo.get."""
    service, deps = _make_service()
    result = await service.summarize(OVERFLOW_ID)
    assert result == {
        "project_id": str(OVERFLOW_ID),
        "summarized": False,
        "project": None,
        "user": None,
    }
    deps["project_repo"].get.assert_not_awaited()
