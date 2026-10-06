"""#1353/#1410 时间线纪元 — 领域模型契约（f12 spec v1.4 §2.8，ADR-065）。

【规格依据】specs/f12-timeline/spec.md §2.1（三列）+ §2.8（E1/E2 承载 + E4 成对语义
          + E9 遗留键）+ §3.4（422 文案）+ §7（边界表）。

【v1.4 变更（#1410）】承载位由 ``extra`` 迁到**正式列** ``era`` / ``era_value`` /
``era_scale``：
- ``resolve_era_fields`` 纯函数实现 E4 的成对语义（对**正式列**读写）
- ``TimelineEvent`` 实体新增 ``era`` / ``era_value`` / ``era_scale`` 三字段
- ``ERA_KEY`` / ``ERA_VALUE_KEY`` 降级为 **v1.3 遗留键**（仅供迁移回填读取 ``extra``）

【本契约钉住四件事】
1. 遗留键名固定（E9）：``ERA_KEY`` = ``"era"`` / ``ERA_VALUE_KEY`` = ``"era_value"``；
   轴名 ≤ 50 字符去空白，轴内值须为有限数值
2. ``resolve_era_fields`` 实现 E4 成对语义：未传=不变 / ``""``=清空 / 非空=写入，
   （返回新元组，**不修改入参**）
3. 两个请求 DTO（``TimelineEventCreate`` / ``TimelineEventUpdate``）接受
   ``era`` / ``era_value``，校验同源（超长 / 非有限 → ValidationError）
4. ``TimelineEvent`` 实体承载三列（``era_scale`` 默认 1.0）

【RED 预期（v1.4）】``resolve_era_fields`` 尚不存在 / ``TimelineEvent`` 无三字段
→ 收集期 ImportError 或断言 FAIL；零 SyntaxError。
"""

from __future__ import annotations

import math
import uuid

import pytest
from pydantic import ValidationError

from inkflow.domain.models.timeline import (
    ERA_KEY,
    ERA_MAX_LEN,
    ERA_VALUE_KEY,
    TimelineEvent,
    TimelineEventCreate,
    TimelineEventUpdate,
    resolve_era_fields,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = "2026-10-06T10:00:00Z"


class TestEraConstants:
    """遗留键名是**跨层契约**（v1.3 `extra` 承载 + 迁移回填）→ 钉死。"""

    def test_key_names(self) -> None:
        assert ERA_KEY == "era"
        assert ERA_VALUE_KEY == "era_value"
        assert ERA_MAX_LEN == 50


class TestResolveEraFieldsPairSemantics:
    """§2.8 E4 成对语义（纯函数，四个分支；作用于**正式列**）。"""

    def test_era_none_keeps_current_untouched(self) -> None:
        """era 未传 → 不改（此时 era_value 被忽略）。"""
        assert resolve_era_fields("示例历", 317.5, None, 999.0) == ("示例历", 317.5)

    def test_era_none_on_empty_is_noop(self) -> None:
        assert resolve_era_fields("", None, None, 999.0) == ("", None)

    def test_era_empty_clears_both(self) -> None:
        """era=\"\" → 清空轴名与轴内值（回到默认轴）。"""
        assert resolve_era_fields("示例历", 317.5, "", None) == ("", None)

    def test_era_empty_on_default_axis_is_noop(self) -> None:
        """默认轴被清一次 → 仍是默认轴（幂等，反例守护）。"""
        assert resolve_era_fields("", None, "", None) == ("", None)

    def test_era_non_empty_writes_name_and_value(self) -> None:
        assert resolve_era_fields("", None, "  示例历  ", 317.5) == ("示例历", 317.5)

    def test_era_without_value_keeps_existing_value(self) -> None:
        """era 非空 + era_value 未传 → 保留原轴内值（改轴名不丢值）。"""
        assert resolve_era_fields("示例历", 317.5, "示例仙历", None) == ("示例仙历", 317.5)

    def test_era_without_value_on_new_era_yields_none(self) -> None:
        """新建带轴名不带值 → 轴内值为 None（轴内值未知）。"""
        assert resolve_era_fields("", None, "示例历", None) == ("示例历", None)

    def test_era_value_empty_string_clears_value_only(self) -> None:
        """era_value=\"\" → 只清轴内值，保留轴名。"""
        assert resolve_era_fields("示例历", 317.5, "示例历", "") == ("示例历", None)

    def test_resolve_does_not_mutate_input(self) -> None:
        """纯函数：入参为不可变标量，返回值即结果（无副作用）。"""
        assert resolve_era_fields("示例历", 317.5, "", None) == ("", None)
        # 再调一次结论不变（幂等）
        assert resolve_era_fields("示例历", 317.5, "", None) == ("", None)


class TestTimelineEventEntityEraFields:
    """v1.4：实体承载三列（``era`` 默认空串 = 默认轴；``era_scale`` 默认 1.0）。"""

    def test_defaults(self) -> None:
        event = TimelineEvent(
            id=uuid.uuid4(),
            project_id=PID,
            title="事件甲",
            created_at=TS,
            updated_at=TS,
        )
        assert event.era == ""
        assert event.era_value is None
        assert event.era_scale == 1.0

    def test_explicit_values(self) -> None:
        event = TimelineEvent(
            id=uuid.uuid4(),
            project_id=PID,
            title="事件甲",
            era="示例历",
            era_value=317.5,
            era_scale=2.0,
            created_at=TS,
            updated_at=TS,
        )
        assert (event.era, event.era_value, event.era_scale) == ("示例历", 317.5, 2.0)


class TestCreateDtoEraValidation:
    """创建 DTO：era/era_value 默认不设纪元（v1.2 行为零变化）。"""

    def test_defaults_are_no_era(self) -> None:
        event = TimelineEventCreate(project_id=PID, title="事件甲")
        assert event.era == ""
        assert event.era_value is None

    def test_era_stripped(self) -> None:
        event = TimelineEventCreate(project_id=PID, title="事件甲", era="  示例历  ")
        assert event.era == "示例历"

    def test_era_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimelineEventCreate(project_id=PID, title="事件甲", era="轴" * (ERA_MAX_LEN + 1))

    def test_era_at_limit_allowed(self) -> None:
        event = TimelineEventCreate(project_id=PID, title="事件甲", era="轴" * ERA_MAX_LEN)
        assert len(event.era) == ERA_MAX_LEN

    def test_era_value_non_finite_rejected(self) -> None:
        for bad in (math.nan, math.inf, -math.inf):
            with pytest.raises(ValidationError):
                TimelineEventCreate(project_id=PID, title="事件甲", era="示例历", era_value=bad)

    def test_era_value_empty_string_allowed(self) -> None:
        event = TimelineEventCreate(project_id=PID, title="事件甲", era="示例历", era_value="")
        assert event.era_value == ""

    def test_era_value_non_numeric_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimelineEventCreate(project_id=PID, title="事件甲", era="示例历", era_value="abc")


class TestUpdateDtoEraValidation:
    """更新 DTO：None = 不修改，\"\" = 清除（与 time_value 清除语义同构）。"""

    def test_unset_era_is_none(self) -> None:
        update = TimelineEventUpdate()
        assert update.era is None
        assert update.era_value is None
        assert "era" not in update.model_fields_set

    def test_era_empty_string_allowed_and_tracked(self) -> None:
        update = TimelineEventUpdate(era="")
        assert update.era == ""
        assert "era" in update.model_fields_set

    def test_era_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimelineEventUpdate(era="轴" * (ERA_MAX_LEN + 1))

    def test_era_value_empty_string_allowed(self) -> None:
        assert TimelineEventUpdate(era_value="").era_value == ""

    def test_era_value_non_numeric_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimelineEventUpdate(era_value="abc")

    def test_era_value_non_finite_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimelineEventUpdate(era_value=math.nan)
