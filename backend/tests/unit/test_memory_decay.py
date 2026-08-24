"""F49 M1 #617 时间衰减 RED 契约测试 — _score_pref 数学锁定 + 注入读路径改造.

依据: specs/f49-memory-decay/spec.md §2.3/§5.1/§7/§13 M1（拍板固化 Q1=A 表列）.
被测模块 inkflow.domain.services.memory_service / domain.models.project 均已存在
（F28/F45 已合入），本批为增量契约——新函数 _score_pref 缺失 → ImportError 形态
RED（惰性 import 于用例内，避免整文件收集失败，新功能用例各自 FAIL）。

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. 模块级纯函数 _score_pref（供 get_preferences_for_injection /
   get_user_preferences_for_injection 共用，零 LLM 依赖）:

       def _score_pref(pref, active_watermark_now, half_life) -> float
           # score = pref.count × 0.5 ** ((active_watermark_now
           #   - pref.active_watermark_at_last_access) / half_life)
           # pref 为鸭子对象（需 .count / .active_watermark_at_last_access）

2. MemoryService 注入读路径改造（memory_decay_enabled=true 时）:
   - get_preferences_for_injection(project_id): 开关 false → []；否则查库取
     items；读 project（project_repo.get(project_id.int)）拿 active_watermark
     与 config.extra；memory_decay_enabled 缺省 false → legacy count desc；
     true → 逐条 _score_pref（half_life 取 extra 默认 30），过滤 score<0.05，
     按 score desc 排序，并刷新每条 active_watermark_at_last_access =
     当前水位（用即保鲜，_bump_access_watermark）。
   - get_user_preferences_for_injection(project_id): 同规则（用户级同构）。
   - _bump_access_watermark(pref, active_watermark_now): 更新
     pref.active_watermark_at_last_access 并经 preference_repo.update 持久化
     （count/confidence/source_events 透传 + active_watermark_at_last_access）。

3. ProjectConfig.extra 键校验:
   - memory_decay_enabled 必须 bool（非 bool → ValueError）
   - memory_decay_half_life 必须 int 且 1-365（越界/非 int → ValueError）
   - 缺省（extra 无键）→ 零迁移（不校验，默认行为）

4. 零行为边界: memory_learning=false → get_preferences_for_injection 返回 []
   （回归既有行为不变）。

RED 预期
--------
新功能用例（_score_pref 数学锁定 / 注入 score desc+过滤+刷新 / 用户级排序 /
bump 持久化 / config 校验）在旧实现下全部 FAIL（函数缺失或行为未实现）；
回归用例（memory_learning=false → [] / decay disabled → count desc）PASS
（锁定既有正确行为防回归）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.services.memory_service import MemoryService

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

PROJECT_ID = uuid.UUID(int=100)


def _pref(
    value="低声道",
    *,
    pref_id="pref-1",
    count=5,
    confidence=0.5,
    at_last_access=0.0,
    source_events=None,
) -> SimpleNamespace:
    """既有偏好鸭子对象（ProjectPreference 语义 + active_watermark_at_last_access）."""
    return SimpleNamespace(
        id=pref_id,
        project_id=PROJECT_ID,
        category="style_word",
        pattern="说",
        value=value,
        confidence=confidence,
        count=count,
        source_events=list(source_events or []),
        active_watermark_at_last_access=at_last_access,
    )


def _project(extra: dict, active_watermark: float = 0.0) -> SimpleNamespace:
    """项目鸭子对象（Project.config.extra + active_watermark 语义）."""
    return SimpleNamespace(
        active_watermark=active_watermark,
        config=SimpleNamespace(extra=dict(extra)),
    )


def _make_service_decay(*, extra=None, active_watermark=0.0, user=False):
    """构造 MemoryService + 依赖字典（decay 注入读路径轨）.

    extra: project.config.extra 内容；active_watermark: project.active_watermark。
    user=True 时装配 user_preference_repo。
    """
    deps = {
        "preference_repo": AsyncMock(),
        "event_repo": AsyncMock(),
        "project_repo": AsyncMock(),
        "audit_service": AsyncMock(),
    }
    deps["preference_repo"].list_by_project.return_value = ([], 0)
    deps["preference_repo"].update.return_value = None
    deps["project_repo"].get.return_value = _project(extra or {}, active_watermark)
    kwargs = {
        "preference_repo": deps["preference_repo"],
        "event_repo": deps["event_repo"],
        "project_repo": deps["project_repo"],
        "audit_service": deps["audit_service"],
    }
    if user:
        deps["user_preference_repo"] = AsyncMock()
        deps["user_preference_repo"].list_all.return_value = ([], 0)
        deps["user_preference_repo"].update.return_value = None
        kwargs["user_preference_repo"] = deps["user_preference_repo"]
    return MemoryService(**kwargs), deps


# ── 契约 1: _score_pref 数学锁定（纯函数，无 LLM 依赖） ──


async def test_score_pref_zero_delta_equals_count() -> None:
    """Δt_active=0 → score = count（0.5^0 = 1）."""
    from inkflow.domain.services.memory_service import _score_pref

    pref = _pref(count=5, at_last_access=10.0)
    assert _score_pref(pref, 10.0, 30) == pytest.approx(5.0)


async def test_score_pref_half_life_equals_count_over_two() -> None:
    """Δt_active=half_life → score = count/2（0.5^1 = 0.5）."""
    from inkflow.domain.services.memory_service import _score_pref

    pref = _pref(count=5, at_last_access=0.0)
    assert _score_pref(pref, 30.0, 30) == pytest.approx(2.5)


async def test_score_pref_two_half_lives_quarter() -> None:
    """Δt_active=2×half_life → score = count/4（0.5^2 = 0.25）."""
    from inkflow.domain.services.memory_service import _score_pref

    pref = _pref(count=8, at_last_access=0.0)
    assert _score_pref(pref, 60.0, 30) == pytest.approx(2.0)


async def test_score_pref_large_delta_approaches_zero() -> None:
    """Δt_active→∞ → score → 0（0.5^大幂趋于 0）."""
    from inkflow.domain.services.memory_service import _score_pref

    pref = _pref(count=100, at_last_access=0.0)
    assert _score_pref(pref, 100_000.0, 30) < 0.0001


async def test_score_pref_custom_half_life() -> None:
    """half_life 为独立参数（默认 30，可被 extra 覆盖）."""
    from inkflow.domain.services.memory_service import _score_pref

    pref = _pref(count=4, at_last_access=0.0)
    assert _score_pref(pref, 7.0, 7) == pytest.approx(2.0)


# ── 契约 2: memory_learning=false 零行为回归 ──


async def test_injection_disabled_returns_empty() -> None:
    """memory_learning=false → get_preferences_for_injection 返回 []（零注入）+ 不查偏好."""
    service, deps = _make_service_decay(extra={})
    assert await service.get_preferences_for_injection(PROJECT_ID) == []
    deps["preference_repo"].list_by_project.assert_not_awaited()


# ── 契约 3: memory_decay_enabled=false legacy count desc（回归零影响） ──


async def test_injection_decay_disabled_keeps_count_desc() -> None:
    """memory_decay_enabled 缺省 false → 排序仍 count desc（回归零影响，不读 active_watermark）."""
    service, deps = _make_service_decay(extra={"memory_learning": True}, active_watermark=90.0)
    low = _pref(pref_id="pref-low", count=2)
    high = _pref(pref_id="pref-high", count=5, value="林晚")
    deps["preference_repo"].list_by_project.return_value = ([low, high], 2)
    result = await service.get_preferences_for_injection(PROJECT_ID)
    assert result == [high, low]  # count 5 > 2，legacy
    deps["preference_repo"].update.assert_not_awaited()  # 不刷新水位


# ── 契约 4: memory_decay_enabled=true → score desc + 过滤 score<0.05 + 保鲜刷新 ──


async def test_injection_scores_desc_filters_and_refreshes() -> None:
    """decay 开启 → score desc + 过滤 <0.05 + 刷新水位（用即保鲜）.

    watermark=300, half_life=30, 0.5^10 = 0.0009766：
      - pref-stale: count=100, at_last=0   → score 0.09766（>0.05 保留，score 低）
      - pref-recent: count=20, at_last=300 → score 20（score 最高）
      - pref-below: count=1, at_last=0     → score 0.0009766（<0.05 过滤）
    count desc 序 = stale(100) > recent(20) > below(1)；score desc 序 =
    recent(20) > stale(0.0977)，below 过滤。此用例区分 score desc vs count desc。
    """
    service, deps = _make_service_decay(
        extra={
            "memory_learning": True,
            "memory_decay_enabled": True,
            "memory_decay_half_life": 30,
        },
        active_watermark=300.0,
    )
    stale = _pref(pref_id="pref-stale", count=100, confidence=0.99, at_last_access=0.0)
    recent = _pref(pref_id="pref-recent", count=20, confidence=0.95, at_last_access=300.0)
    below = _pref(pref_id="pref-below", count=1, confidence=0.5, at_last_access=0.0)
    deps["preference_repo"].list_by_project.return_value = ([stale, recent, below], 3)
    result = await service.get_preferences_for_injection(PROJECT_ID)
    assert [p.id for p in result] == ["pref-recent", "pref-stale"]  # below 被过滤
    # 保鲜刷新：每个注入偏好 active_watermark_at_last_access 写为当前水位 300
    update_calls = deps["preference_repo"].update.await_args_list
    ids_updated = {_arg(c, "preference_id", 0) for c in update_calls}
    assert ids_updated == {"pref-recent", "pref-stale"}
    for c in update_calls:
        assert _arg(c, "active_watermark_at_last_access", 4) == 300.0


async def test_injection_probe_watermark_not_advanced_score_stable() -> None:
    """探针实证：不推进活跃水位 → score 不变（刷新后 Δt=0 → score=count 不衰减）."""
    service, deps = _make_service_decay(
        extra={
            "memory_learning": True,
            "memory_decay_enabled": True,
            "memory_decay_half_life": 30,
        },
        active_watermark=90.0,
    )
    # 首次注入：delta=0（at_last=90）→ score=count；刷新写回 at_last=90。
    pref = _pref(pref_id="pref-x", count=20, at_last_access=90.0)
    deps["preference_repo"].list_by_project.return_value = ([pref], 1)
    first = await service.get_preferences_for_injection(PROJECT_ID)
    assert first[0].active_watermark_at_last_access == 90.0
    # 水位未推进，再次注入：活动水位仍 90 → Δt=0 → score=count 不变
    deps["preference_repo"].list_by_project.return_value = ([pref], 1)
    second = await service.get_preferences_for_injection(PROJECT_ID)
    assert second[0].id == "pref-x"
    assert second == [pref]


def _arg(call, name, pos=None, default=None):
    """从 mock call 宽松取参（关键字优先，位置回退）——不锁实现传参形态."""
    if name in call.kwargs:
        return call.kwargs[name]
    if pos is not None and len(call.args) > pos:
        return call.args[pos]
    return default


# ── 契约 5: get_user_preferences_for_injection 同规则 score desc ──


async def test_user_injection_scores_desc() -> None:
    """用户级注入读口同规则：memory_learning=true + decay enabled → score desc."""
    service, deps = _make_service_decay(
        extra={
            "memory_learning": True,
            "memory_decay_enabled": True,
            "memory_decay_half_life": 30,
        },
        active_watermark=90.0,
        user=True,
    )
    stale = SimpleNamespace(
        id="u-stale",
        category="style_word",
        pattern="说",
        value="低声道",
        confidence=0.9,
        count=100,
        project_count=2,
        source_projects=["proj-a"],
        source_events=["e1"],
        active_watermark_at_last_access=0.0,
    )
    recent = SimpleNamespace(
        id="u-recent",
        category="style_word",
        pattern="说",
        value="林晚",
        confidence=0.8,
        count=20,
        project_count=2,
        source_projects=["proj-a"],
        source_events=["e2"],
        active_watermark_at_last_access=90.0,
    )
    deps["user_preference_repo"].list_all.return_value = ([stale, recent], 2)
    deps["user_preference_repo"].get.return_value = None
    deps["project_repo"].get.return_value = None  # list_user_preferences 惰性重算无幽灵来源
    # 覆盖 project_repo.get 用于惰性重算：source_projects 均有效
    deps["project_repo"].get.side_effect = lambda _pid: _project(
        {"memory_learning": True, "memory_decay_enabled": True, "memory_decay_half_life": 30},
        90.0,
    )
    result = await service.get_user_preferences_for_injection(PROJECT_ID)
    assert [p.id for p in result] == ["u-recent", "u-stale"]  # score 20 > 0.0977


# ── 契约 6: _bump_access_watermark 持久化刷新 ──


async def test_bump_access_watermark_persists() -> None:
    """_bump_access_watermark 更新 pref 水位并经 preference_repo.update 持久化."""
    service, deps = _make_service_decay(extra={"memory_learning": True})
    deps["preference_repo"].update.return_value = _pref(pref_id="pref-1", at_last_access=42.0)
    pref = _pref(pref_id="pref-1", count=5, at_last_access=0.0)
    await service._bump_access_watermark(pref, 42.0)
    deps["preference_repo"].update.assert_awaited_once()
    call = deps["preference_repo"].update.await_args
    assert _arg(call, "preference_id", 0) == "pref-1"
    assert _arg(call, "active_watermark_at_last_access", 4) == 42.0
    assert pref.active_watermark_at_last_access == 42.0
