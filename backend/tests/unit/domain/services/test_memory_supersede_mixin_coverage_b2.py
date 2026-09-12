"""Coverage backfill batch 2: MemorySupersedeMixin 用户级判定/审计分支。

经公开 ``MemoryService.record_draft_edit`` 驱动（镜像 test_memory_supersede_wiring）：
- 用户级 SupersedeDeterminationError + 有 audit -> 审计后跳过该候选（105-107 / 114）
- 用户级 dropped>0 -> 审计 semantic_summary_failed（115-116）
- audit_service=None：命中/未命中旧值的两条循环分支与末尾审计跳过
  （59->57 / 77->exit / 125->123 / 145->exit）
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.ports.preference_supersede_errors import SupersedeDeterminationError
from inkflow.domain.services.memory_service import MemoryService

pytestmark = pytest.mark.asyncio

PROJECT_ID = uuid.UUID(int=100)
_UNSET = object()


class FakeLearner:
    """最小 learner 桩：按序弹出项目级/用户级候选，耗尽返回 []。"""

    def __init__(self, candidates=None, user_candidates=None) -> None:
        self._candidates = list(candidates or [])
        self._user_candidates = list(user_candidates or [])

    def aggregate_candidates(self, events):
        return self._candidates.pop(0) if self._candidates else []

    def aggregate_user_candidates(self, events):
        return self._user_candidates.pop(0) if self._user_candidates else []

    def confidence_for(self, count: int) -> float:
        return 1 - 1 / (count + 1)


def _candidate(value: str) -> SimpleNamespace:
    return SimpleNamespace(
        category="style_word", pattern="词", value=value, count=2, confidence=0.67
    )


def _user_candidate(value: str) -> SimpleNamespace:
    return SimpleNamespace(
        category="style_word",
        pattern="词",
        value=value,
        count=2,
        project_count=2,
        confidence=0.67,
        source_projects=[],
        source_events=[],
    )


def _pref(value: str, *, pref_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=pref_id,
        project_id=PROJECT_ID,
        category="style_word",
        pattern="词",
        value=value,
        confidence=0.5,
        count=1,
        source_events=[],
        superseded_by="",
    )


def _user_pref(value: str, *, pref_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=pref_id,
        category="style_word",
        pattern="词",
        value=value,
        confidence=0.5,
        count=1,
        project_count=1,
        source_projects=[],
        source_events=[],
        superseded_by="",
    )


def _project() -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(extra={"memory_learning": True}), active_watermark=0.0
    )


def _determiner(*, values=(), dropped=0, error: Exception | None = None):
    determiner = SimpleNamespace(determine=AsyncMock())
    if error is not None:
        determiner.determine.side_effect = error
    else:
        determiner.determine.return_value = (list(values), dropped)
    return determiner


def _make_service(*, learner=None, determiner=None, audit_service=_UNSET):
    """构造 MemoryService：repo 全 mock；audit_service 可显式置 None。"""
    preference_repo = AsyncMock()
    preference_repo.list_by_project.return_value = ([], 0)
    preference_repo.create.return_value = _pref("新", pref_id="pref-new")
    preference_repo.update.return_value = None
    event_repo = AsyncMock()
    event_repo.create.return_value = SimpleNamespace(id="evt-1", event_type="draft_edited")
    event_repo.list_edited_by_project.return_value = []
    project_repo = AsyncMock()
    project_repo.get.return_value = _project()
    user_preference_repo = AsyncMock()
    user_preference_repo.list_all.return_value = ([], 0)
    user_preference_repo.create.return_value = _user_pref("新", pref_id="upref-new")
    user_preference_repo.update.return_value = None

    resolved_audit = AsyncMock() if audit_service is _UNSET else audit_service
    service = MemoryService(
        preference_repo=preference_repo,
        event_repo=event_repo,
        project_repo=project_repo,
        audit_service=resolved_audit,
        learner=learner or FakeLearner(),
        user_preference_repo=user_preference_repo,
        supersede_determiner=determiner,
        llm_default_model="test-model",
    )
    return service, {
        "preference_repo": preference_repo,
        "user_preference_repo": user_preference_repo,
        "audit_service": resolved_audit,
    }


def _arg(call, name, pos=None, default=None):
    if name in call.kwargs:
        return call.kwargs[name]
    if pos is not None and len(call.args) > pos:
        return call.args[pos]
    return default


def _audit_call(audit_service: AsyncMock, summary: str):
    for call in audit_service.record.await_args_list:
        if _arg(call, "severity_summary", 4) == summary:
            return call
    return None


async def _record(service) -> None:
    await service.record_draft_edit(
        draft_id="draft-1",
        project_id=PROJECT_ID,
        before="旧版内容",
        after="新版内容更长一些",
    )


async def test_user_supersede_error_audits_and_skips_candidate() -> None:
    """用户级判定抛错 + 有 audit -> semantic_summary_failed 且该候选不落库（105-114）。"""
    learner = FakeLearner(user_candidates=[[_user_candidate("新user语")]])
    service, deps = _make_service(
        learner=learner,
        determiner=_determiner(error=SupersedeDeterminationError("boom")),
    )
    deps["user_preference_repo"].list_all.return_value = (
        [_user_pref("旧user语", pref_id="upref-old")],
        1,
    )

    await _record(service)

    audit_call = _audit_call(deps["audit_service"], "semantic_summary_failed")
    assert audit_call is not None
    assert _arg(audit_call, "note", 9, "") == "LLM 判定失败"
    deps["user_preference_repo"].create.assert_not_awaited()


async def test_user_supersede_dropped_audits_and_still_creates() -> None:
    """用户级 dropped>0 -> 丢弃审计 + 候选仍落库（115-116）。"""
    learner = FakeLearner(user_candidates=[[_user_candidate("新user语")]])
    service, deps = _make_service(
        learner=learner, determiner=_determiner(values=[], dropped=2)
    )
    deps["user_preference_repo"].list_all.return_value = (
        [_user_pref("旧user语", pref_id="upref-old")],
        1,
    )

    await _record(service)

    audit_call = _audit_call(deps["audit_service"], "semantic_summary_failed")
    assert audit_call is not None
    assert "2" in _arg(audit_call, "note", 9, "")
    deps["user_preference_repo"].create.assert_awaited_once()


async def test_supersede_without_audit_service_skips_unknown_values() -> None:
    """audit_service=None：判定值未命中既有偏好 -> 跳过且不做审计（59/77/125/145）。"""
    learner = FakeLearner(
        candidates=[[_candidate("新项目语")]],
        user_candidates=[[_user_candidate("新user语")]],
    )
    service, deps = _make_service(
        learner=learner, determiner=_determiner(values=["幽灵值"]), audit_service=None
    )
    deps["preference_repo"].list_by_project.return_value = (
        [_pref("旧项目语", pref_id="pref-old")],
        1,
    )
    deps["user_preference_repo"].list_all.return_value = (
        [_user_pref("旧user语", pref_id="upref-old")],
        1,
    )

    await _record(service)

    deps["preference_repo"].update.assert_not_awaited()
    deps["user_preference_repo"].update.assert_not_awaited()
    deps["preference_repo"].create.assert_awaited_once()
    deps["user_preference_repo"].create.assert_awaited_once()


async def test_user_supersede_without_existing_items_skips_determiner() -> None:
    """无既有用户偏好 -> 不触发判定器，候选直接落库（96->115）。"""
    learner = FakeLearner(user_candidates=[[_user_candidate("新user语")]])
    determiner = _determiner(values=["任意"])
    service, deps = _make_service(learner=learner, determiner=determiner)

    await _record(service)

    determiner.determine.assert_not_awaited()
    deps["user_preference_repo"].create.assert_awaited_once()


async def test_user_supersede_error_without_audit_skips_candidate() -> None:
    """audit_service=None 且用户级判定失败 -> 直接返回不落库（106->114）。"""
    learner = FakeLearner(user_candidates=[[_user_candidate("新user语")]])
    service, deps = _make_service(
        learner=learner,
        determiner=_determiner(error=SupersedeDeterminationError("boom")),
        audit_service=None,
    )
    deps["user_preference_repo"].list_all.return_value = (
        [_user_pref("旧user语", pref_id="upref-old")],
        1,
    )

    await _record(service)

    deps["user_preference_repo"].create.assert_not_awaited()
