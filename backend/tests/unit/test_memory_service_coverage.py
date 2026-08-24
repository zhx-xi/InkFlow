"""#627 coverage-gap closure: MemoryService 覆盖率补测（独立文件，避免
test_memory_service.py 触 900 行 monster-file 门禁）。

从 test_memory_service.py 拆出 #627 覆盖补测段（5 用例，任务 2026-08-24）。
覆盖 memory_service.py 的 L335->342 / L360->361 / L378->374 / L584->585 /
L885->887 分支。helper 逐字复制自 test_memory_service.py（鸭子类型依赖，全 mock）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.services.memory_service import MemoryService, PreferenceNotFoundError

pytestmark = pytest.mark.asyncio

PROJECT_ID = uuid.UUID(int=100)


class FakeLearner:
    """注入 fake（隔离提取算法；同 test_memory_service.py）。"""

    def __init__(self, results=None) -> None:
        self._results = list(results or [])
        self.aggregate_calls = 0

    def aggregate_candidates(self, events):
        self.aggregate_calls += 1
        if self._results:
            return self._results.pop(0)
        return []

    def confidence_for(self, count: int) -> float:
        return 1 - 1 / (count + 1)


def _pref(
    value="低声道",
    *,
    pref_id="pref-1",
    count=1,
    source_events=None,
    category="style_word",
    pattern="说",
    confidence=0.5,
) -> SimpleNamespace:
    """既有偏好鸭子对象（ProjectPreference 语义）。"""
    return SimpleNamespace(
        id=pref_id,
        project_id=PROJECT_ID,
        category=category,
        pattern=pattern,
        value=value,
        confidence=confidence,
        count=count,
        source_events=list(source_events or []),
    )


def _project(extra: dict) -> SimpleNamespace:
    """项目鸭子对象（Project.config.extra 语义）。"""
    return SimpleNamespace(config=SimpleNamespace(extra=extra))


def _user_pref(
    value="低声道",
    *,
    pref_id="upref-1",
    count=2,
    confidence=0.67,
    project_count=1,
    source_projects=None,
    source_events=None,
    category="style_word",
    pattern="说",
) -> SimpleNamespace:
    """用户级偏好鸭子对象（UserPreference 语义，#521）。"""
    return SimpleNamespace(
        id=pref_id,
        category=category,
        pattern=pattern,
        value=value,
        confidence=confidence,
        count=count,
        project_count=project_count,
        source_projects=list(source_projects or []),
        source_events=list(source_events or []),
    )


def _make_service(learner=None, extra=None) -> tuple[MemoryService, dict]:
    """构造服务 + 依赖字典（同 test_memory_service.py）。"""
    deps = {
        "preference_repo": AsyncMock(),
        "event_repo": AsyncMock(),
        "project_repo": AsyncMock(),
        "audit_service": AsyncMock(),
    }
    deps["preference_repo"].list_by_project.return_value = ([], 0)
    deps["preference_repo"].count_by_project.return_value = 0
    deps["preference_repo"].get.return_value = None
    deps["preference_repo"].create.return_value = _pref(pref_id="pref-new")
    deps["preference_repo"].update.return_value = None
    deps["preference_repo"].delete.return_value = True
    deps["event_repo"].create.return_value = SimpleNamespace(id="evt-1", event_type="draft_edited")
    deps["event_repo"].list_by_project.return_value = ([], 0)
    deps["project_repo"].get.return_value = _project(extra or {})
    service = MemoryService(
        preference_repo=deps["preference_repo"],
        event_repo=deps["event_repo"],
        project_repo=deps["project_repo"],
        audit_service=deps["audit_service"],
        learner=learner or FakeLearner(),
    )
    return service, deps


def _make_service_manual(*, pref=None, user_pref=None, user_repo_installed=True):
    """#521 手动创建/编辑轨构造（同 test_memory_service.py）。"""
    deps = {
        "preference_repo": AsyncMock(),
        "event_repo": AsyncMock(),
        "project_repo": AsyncMock(),
        "audit_service": AsyncMock(),
    }
    deps["preference_repo"].list_by_project.return_value = ([], 0)
    deps["preference_repo"].count_by_project.return_value = 0
    deps["preference_repo"].get.return_value = pref
    deps["preference_repo"].create.return_value = _pref(pref_id="pref-new")
    deps["preference_repo"].update.return_value = _pref(pref_id="pref-updated")
    deps["preference_repo"].delete.return_value = True
    deps["event_repo"].create.return_value = SimpleNamespace(id="evt-1", event_type="draft_edited")
    deps["event_repo"].list_by_project.return_value = ([], 0)
    deps["project_repo"].get.return_value = _project({})
    if user_repo_installed:
        deps["user_preference_repo"] = AsyncMock()
        deps["user_preference_repo"].get.return_value = user_pref
        deps["user_preference_repo"].create.return_value = _user_pref(pref_id="upref-new")
        deps["user_preference_repo"].update.return_value = _user_pref(pref_id="upref-updated")
        deps["user_preference_repo"].list_all.return_value = ([], 0)
    else:
        deps["user_preference_repo"] = None
    service = MemoryService(
        preference_repo=deps["preference_repo"],
        event_repo=deps["event_repo"],
        project_repo=deps["project_repo"],
        audit_service=deps["audit_service"],
        learner=FakeLearner(),
        user_preference_repo=deps["user_preference_repo"],
    )
    return service, deps


async def test_remove_preference_without_audit_service_skips_audit() -> None:
    """覆盖 L335->342: audit_service 未注入（None）→ 删除成功且跳过审计。"""
    pref = _pref(pref_id="pref-1")
    preference_repo = AsyncMock()
    preference_repo.get.return_value = pref
    preference_repo.delete.return_value = True
    service = MemoryService(
        preference_repo=preference_repo,
        event_repo=AsyncMock(),
        project_repo=AsyncMock(),
    )
    result = await service.remove_preference("pref-1")
    assert result is pref
    preference_repo.delete.assert_awaited_once()
    preference_repo.get.assert_awaited_once_with("pref-1")


async def test_get_preferences_for_injection_project_missing_empty() -> None:
    """覆盖 L360->361: 注入读口再查项目时缺失（二次 get → None）→ []。"""
    service, deps = _make_service(extra={"memory_learning": True})
    deps["project_repo"].get.side_effect = [_project({"memory_learning": True}), None]
    deps["preference_repo"].list_by_project.return_value = ([_pref(count=5, pref_id="pref-2")], 1)
    assert await service.get_preferences_for_injection(PROJECT_ID) == []


async def test_get_preferences_for_injection_decay_multi_item_loop() -> None:
    """覆盖 L378->374: 衰减分支——低分条目走 if 假分支后循环继续。"""
    service, deps = _make_service(
        extra={"memory_learning": True, "memory_decay_enabled": True, "memory_decay_half_life": 30}
    )
    project = _project(
        {"memory_learning": True, "memory_decay_enabled": True, "memory_decay_half_life": 30}
    )
    project.active_watermark = 500.0
    deps["project_repo"].get.return_value = project
    stale = _pref(count=1, pref_id="pref-stale")
    low = _pref(count=2, pref_id="pref-low")
    low.active_watermark_at_last_access = 500.0
    high = _pref(count=5, pref_id="pref-high", value="林晚")
    high.active_watermark_at_last_access = 500.0
    deps["preference_repo"].list_by_project.return_value = ([stale, low, high], 3)
    result = await service.get_preferences_for_injection(PROJECT_ID)
    assert [p.id for p in result] == ["pref-high", "pref-low"]
    assert deps["preference_repo"].update.await_count == 2


async def test_update_user_preference_missing_raises() -> None:
    """覆盖 L584->585: 用户级偏好不存在 → PreferenceNotFoundError 且 update 未调用。"""
    service, deps = _make_service_manual(pref=None, user_pref=None)
    with pytest.raises(PreferenceNotFoundError):
        await service.update_user_preference(
            "upref-missing", category="style_word", pattern="说", value="低声道"
        )
    deps["user_preference_repo"].update.assert_not_awaited()


async def test_remove_summaries_without_summary_repo_skips_delete() -> None:
    """覆盖 L885->887: summary_repo 未注入 → 跳过 delete_by_project，仍 deleted:True。"""
    deps = {"preference_repo": AsyncMock(), "event_repo": AsyncMock(), "project_repo": AsyncMock()}
    deps["project_repo"].get.return_value = _project({"memory_learning": True})
    service = MemoryService(
        preference_repo=deps["preference_repo"],
        event_repo=deps["event_repo"],
        project_repo=deps["project_repo"],
        learner=FakeLearner(),
    )
    result = await service.remove_summaries(PROJECT_ID)
    assert result == {"project_id": str(PROJECT_ID), "deleted": True}
