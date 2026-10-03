"""#1353 时间线纪元承载 — 领域模型契约（f12 spec v1.3 §2.8 E1/E2/E4）。

【规格依据】specs/f12-timeline/spec.md §2.8（承载键约定 E1/E2 + 写入成对语义 E4）
          + §3.4（422 文案）+ §7（边界表新增行）。

【本契约钉住的四件事】
1. 承载键名固定为 ``extra.era`` / ``extra.era_value``（E1/E2），轴名 ≤ 50 字符去空白，
   轴内值须为有限数值
2. ``apply_era`` 纯函数实现 E4 的成对语义：未传=不变 / ``""``=删两键 / 非空=写入，
   且 **不原地修改** 传入的 extra
3. 两个请求 DTO（``TimelineEventCreate`` / ``TimelineEventUpdate``）都接受
   ``era`` / ``era_value``，校验同源（超长 / 非有限 → ValidationError）
4. **零 DDL**：本契约只描述既有 ``extra`` JSON 列上的读写，不涉及任何新列

【RED 预期】``apply_era`` / ``ERA_KEY`` / ``ERA_VALUE_KEY`` / ``ERA_MAX_LEN`` 尚不存在
→ 收集期 ImportError（预期 RED 形态，非 SyntaxError）；GREEN 后逐条断言。
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
    TimelineEventCreate,
    TimelineEventUpdate,
    apply_era,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


class TestEraConstants:
    """承载键名是**跨层契约**（API / CLI / GUI / 0.17.0 正式列迁移）→ 钉死。"""

    def test_key_names(self) -> None:
        assert ERA_KEY == "era"
        assert ERA_VALUE_KEY == "era_value"
        assert ERA_MAX_LEN == 50


class TestApplyEraPairSemantics:
    """§2.8 E4 成对语义（纯函数，四个分支）。"""

    def test_era_none_keeps_extra_untouched(self) -> None:
        """era 未传 → extra 不变（此时 era_value 被忽略）。"""
        extra = {ERA_KEY: "示例历", ERA_VALUE_KEY: 317.5, "tags": ["甲"]}
        assert apply_era(extra, None, 999.0) == extra

    def test_era_empty_clears_both_keys(self) -> None:
        """era="" → 删除两键（回到默认轴），其余键保留。"""
        extra = {ERA_KEY: "示例历", ERA_VALUE_KEY: 317.5, "tags": ["甲"]}
        assert apply_era(extra, "", None) == {"tags": ["甲"]}

    def test_era_empty_on_extra_without_era_is_noop(self) -> None:
        """无纪元事件被清一次 → 仍无纪元（幂等，反例守护）。"""
        assert apply_era({"tags": []}, "", None) == {"tags": []}

    def test_era_non_empty_writes_name_and_value(self) -> None:
        assert apply_era({}, "  示例历  ", 317.5) == {ERA_KEY: "示例历", ERA_VALUE_KEY: 317.5}

    def test_era_without_value_keeps_existing_value(self) -> None:
        """era 非空 + era_value 未传 → 保留原轴内值（改轴名不丢值）。"""
        extra = {ERA_KEY: "示例历", ERA_VALUE_KEY: 317.5}
        assert apply_era(extra, "示例仙历", None) == {ERA_KEY: "示例仙历", ERA_VALUE_KEY: 317.5}

    def test_era_without_value_on_new_era_has_no_value_key(self) -> None:
        """新建带轴名不带值时，extra 里**不存在** era_value 键（轴内值未知）。"""
        assert apply_era({}, "示例历", None) == {ERA_KEY: "示例历"}

    def test_era_value_empty_string_clears_value_only(self) -> None:
        """era_value="" → 只删轴内值，保留轴名。"""
        assert apply_era({ERA_KEY: "示例历", ERA_VALUE_KEY: 317.5}, "示例历", "") == {
            ERA_KEY: "示例历"
        }

    def test_apply_era_does_not_mutate_input(self) -> None:
        extra = {ERA_KEY: "示例历", ERA_VALUE_KEY: 317.5}
        apply_era(extra, "", None)
        assert extra == {ERA_KEY: "示例历", ERA_VALUE_KEY: 317.5}


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
    """更新 DTO：None = 不修改，"" = 清除（与 time_value 清除语义同构）。"""

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
