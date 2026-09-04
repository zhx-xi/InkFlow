"""F12 时间线管理领域模型单元测试 — 无 I/O，纯 Pydantic 验证.

测试范围：TimelineEvent 实体、Create/Update DTO（含 time_value 清除语义）、
检查相关模型（TimelineEventRef / TimelineConflict / ConsistencyReport /
TimelineView）。
依据: specs/f12-timeline/spec.md §2.5/§2.6 + §9 测试策略「领域模型」。
"""

import math
import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from inkflow.domain.models.timeline import (
    TIME_VALUE_LIMIT,
    ConsistencyReport,
    TimelineConflict,
    TimelineEvent,
    TimelineEventCreate,
    TimelineEventRef,
    TimelineEventUpdate,
    TimelineView,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
EID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def make_ref(title: str = "事件", time_value: float | None = 317.5) -> TimelineEventRef:
    """构造一致性检查用的事件引用（轻量快照）."""
    return TimelineEventRef(
        id=EID,
        title=title,
        time_value=time_value,
        time_display="青元历 317 年秋",
        narrative_position=1,
        timeline_flag="",
    )


class TestTimelineEventModel:
    """TimelineEvent 领域实体测试."""

    def test_event_defaults(self):
        """默认值：description='', time_value=None, time_unit='', time_display='',
        narrative_position=0, timeline_flag='', extra={}."""
        event = TimelineEvent(
            id=EID,
            project_id=PID,
            title="林尘觉醒金手指",
            created_at=TS,
            updated_at=TS,
        )
        assert event.title == "林尘觉醒金手指"
        assert event.description == ""
        assert event.time_value is None
        assert event.time_unit == ""
        assert event.time_display == ""
        assert event.narrative_position == 0
        assert event.timeline_flag == ""
        assert event.extra == {}

    def test_event_required_fields(self):
        """缺少必填字段（title）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            TimelineEvent(
                id=EID,
                project_id=PID,
                created_at=TS,
                updated_at=TS,
            )


class TestTimelineEventCreateValidation:
    """TimelineEventCreate 请求 DTO 验证测试."""

    def test_create_valid_and_strips_title(self):
        """合法创建：title 去空白，其余字段取默认值（time_value=None = 时间未知）."""
        event = TimelineEventCreate(project_id=PID, title="  林尘觉醒金手指  ")
        assert event.title == "林尘觉醒金手指"
        assert event.description == ""
        assert event.time_value is None
        assert event.time_unit == ""
        assert event.time_display == ""
        assert event.narrative_position is None
        assert event.timeline_flag == ""

    def test_create_empty_title_raises(self):
        """空标题应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="事件标题不能为空"):
            TimelineEventCreate(project_id=PID, title="")

    def test_create_whitespace_title_raises(self):
        """纯空白标题应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="事件标题不能为空"):
            TimelineEventCreate(project_id=PID, title="   ")

    def test_create_title_too_long_raises(self):
        """超过 100 字符的标题应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="事件标题不能超过 100 个字符"):
            TimelineEventCreate(project_id=PID, title="长" * 101)

    def test_create_description_too_long_raises(self):
        """超过 5000 字符的 description 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="事件描述不能超过 5000 个字符"):
            TimelineEventCreate(project_id=PID, title="事件", description="文" * 5001)

    def test_create_time_value_none_allowed(self):
        """time_value=None 合法（世界内时间未知，计入 skipped）."""
        event = TimelineEventCreate(project_id=PID, title="事件", time_value=None)
        assert event.time_value is None

    def test_create_time_value_nan_raises(self):
        """time_value=NaN 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="世界内时间必须是有限数值"):
            TimelineEventCreate(project_id=PID, title="事件", time_value=math.nan)

    def test_create_time_value_inf_raises(self):
        """time_value=±Inf 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="世界内时间必须是有限数值"):
            TimelineEventCreate(project_id=PID, title="事件", time_value=math.inf)
        with pytest.raises(ValidationError, match="世界内时间必须是有限数值"):
            TimelineEventCreate(project_id=PID, title="事件", time_value=-math.inf)

    def test_create_time_value_out_of_range_raises(self):
        """time_value 越界（±1e12 之外）应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="世界内时间超出允许范围"):
            TimelineEventCreate(project_id=PID, title="事件", time_value=TIME_VALUE_LIMIT + 1)
        with pytest.raises(ValidationError, match="世界内时间超出允许范围"):
            TimelineEventCreate(project_id=PID, title="事件", time_value=-(TIME_VALUE_LIMIT + 1))

    def test_create_time_value_boundaries_allowed(self):
        """time_value=±1e12 边界值合法；负数（纪元前）合法."""
        upper = TimelineEventCreate(project_id=PID, title="事件", time_value=TIME_VALUE_LIMIT)
        assert upper.time_value == TIME_VALUE_LIMIT
        lower = TimelineEventCreate(project_id=PID, title="事件", time_value=-TIME_VALUE_LIMIT)
        assert lower.time_value == -TIME_VALUE_LIMIT
        negative = TimelineEventCreate(project_id=PID, title="事件", time_value=-317.5)
        assert negative.time_value == -317.5

    def test_create_short_texts_stripped_and_empty_allowed(self):
        """time_unit/time_display/timeline_flag 空串合法，非空时去空白保存."""
        event = TimelineEventCreate(
            project_id=PID,
            title="事件",
            time_unit=" 年 ",
            time_display=" 青元历 317 年秋 ",
            timeline_flag=" flashback ",
        )
        assert event.time_unit == "年"
        assert event.time_display == "青元历 317 年秋"
        assert event.timeline_flag == "flashback"

    def test_create_time_unit_too_long_raises(self):
        """超过 20 字符的 time_unit 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="时间单位不能超过 20 个字符"):
            TimelineEventCreate(project_id=PID, title="事件", time_unit="单" * 21)

    def test_create_time_display_too_long_raises(self):
        """超过 100 字符的 time_display 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="时间显示文本不能超过 100 个字符"):
            TimelineEventCreate(project_id=PID, title="事件", time_display="文" * 101)

    def test_create_timeline_flag_too_long_raises(self):
        """超过 20 字符的 timeline_flag 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="时间线标记不能超过 20 个字符"):
            TimelineEventCreate(project_id=PID, title="事件", timeline_flag="标" * 21)

    def test_create_negative_narrative_position_raises(self):
        """负的 narrative_position 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="叙事位置不能为负数"):
            TimelineEventCreate(project_id=PID, title="事件", narrative_position=-1)

    def test_create_narrative_position_none_allowed(self):
        """narrative_position=None 合法（追加到叙事末尾，max+1 语义）."""
        event = TimelineEventCreate(project_id=PID, title="事件", narrative_position=None)
        assert event.narrative_position is None

    def test_create_narrative_position_zero_allowed(self):
        """narrative_position=0 合法."""
        event = TimelineEventCreate(project_id=PID, title="事件", narrative_position=0)
        assert event.narrative_position == 0


class TestTimelineEventUpdate:
    """TimelineEventUpdate 部分更新语义测试（exclude_unset，同 F1）."""

    def test_update_partial_semantics(self):
        """未传入的字段保持 None，且不出现在 model_fields_set."""
        update = TimelineEventUpdate(title="新标题")
        assert update.title == "新标题"
        assert update.description is None
        assert update.time_value is None
        assert update.time_unit is None
        assert update.time_display is None
        assert update.narrative_position is None
        assert update.timeline_flag is None
        assert update.model_fields_set == {"title"}
        assert TimelineEventUpdate().model_fields_set == set()

    def test_update_time_value_none_means_no_change(self):
        """time_value=None 表示不修改（None 进 model_fields_set，与不传可区分）."""
        none_update = TimelineEventUpdate(time_value=None)
        assert none_update.time_value is None
        assert "time_value" in none_update.model_fields_set

    def test_update_time_value_empty_means_clear(self):
        """time_value=\"\" 表示清除世界内时间（置为未知）."""
        clear_update = TimelineEventUpdate(time_value="")
        assert clear_update.time_value == ""
        assert "time_value" in clear_update.model_fields_set

    def test_update_time_value_non_empty_str_raises(self):
        """time_value 传非空字符串（非数值）应抛出 ValidationError（422 语义）."""
        with pytest.raises(ValidationError, match="清除世界内时间请传空字符串"):
            TimelineEventUpdate(time_value="abc")

    def test_update_time_value_numeric_valid(self):
        """time_value 传数值合法（修改世界内时间）."""
        update = TimelineEventUpdate(time_value=400.0)
        assert update.time_value == 400.0

    def test_update_time_value_nan_raises(self):
        """time_value 传 NaN 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="世界内时间必须是有限数值"):
            TimelineEventUpdate(time_value=math.nan)

    def test_update_time_value_out_of_range_raises(self):
        """time_value 越界应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="世界内时间超出允许范围"):
            TimelineEventUpdate(time_value=TIME_VALUE_LIMIT + 1)

    def test_update_timeline_flag_empty_clears(self):
        """timeline_flag=\"\" 表示清除标记（置为正叙）；非空值正常更新."""
        clear_update = TimelineEventUpdate(timeline_flag="")
        assert clear_update.timeline_flag == ""
        assert "timeline_flag" in clear_update.model_fields_set
        set_update = TimelineEventUpdate(timeline_flag="flashback")
        assert set_update.timeline_flag == "flashback"

    def test_update_negative_narrative_position_raises(self):
        """负的 narrative_position 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="叙事位置不能为负数"):
            TimelineEventUpdate(narrative_position=-1)

    def test_update_empty_title_raises(self):
        """title 传空串/纯空白应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="事件标题不能为空"):
            TimelineEventUpdate(title="")
        with pytest.raises(ValidationError, match="事件标题不能为空"):
            TimelineEventUpdate(title="  ")

    def test_update_short_texts_too_long_raise(self):
        """time_unit/time_display/timeline_flag 超长应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="时间单位不能超过 20 个字符"):
            TimelineEventUpdate(time_unit="单" * 21)
        with pytest.raises(ValidationError, match="时间显示文本不能超过 100 个字符"):
            TimelineEventUpdate(time_display="文" * 101)
        with pytest.raises(ValidationError, match="时间线标记不能超过 20 个字符"):
            TimelineEventUpdate(timeline_flag="标" * 21)


class TestTimelineEventRef:
    """TimelineEventRef 轻量快照测试."""

    def test_ref_requires_all_fields(self):
        """TimelineEventRef 缺任一字段（title）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            TimelineEventRef(
                id=EID,
                time_value=None,
                time_display="",
                narrative_position=0,
                timeline_flag="",
            )

    def test_ref_accepts_none_time_value(self):
        """time_value=None（时间未知）合法."""
        ref = make_ref(time_value=None)
        assert ref.time_value is None


class TestTimelineConflict:
    """TimelineConflict 冲突记录 schema 测试."""

    def test_conflict_type_three_values_valid(self):
        """conflict_type 三值（order_conflict/flashback/flashforward）均合法."""
        for conflict_type in ("order_conflict", "flashback", "flashforward"):
            conflict = TimelineConflict(
                conflict_type=conflict_type,
                prev=make_ref("前事件", 500.0),
                next=make_ref("后事件", 100.0),
                message="叙事顺序与世界内时间矛盾",
            )
            assert conflict.conflict_type == conflict_type

    def test_conflict_type_invalid_raises(self):
        """conflict_type 非三值应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            TimelineConflict(
                conflict_type="other",
                prev=make_ref(),
                next=make_ref(),
                message="x",
            )

    def test_conflict_requires_fields(self):
        """缺少必填字段（message）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            TimelineConflict(
                conflict_type="order_conflict",
                prev=make_ref(),
                next=make_ref(),
            )


class TestConsistencyReport:
    """ConsistencyReport 检查报告 schema 测试."""

    def test_report_defaults_empty_lists(self):
        """默认值：conflicts/flashbacks/event_timeline/narrative_order 均为空列表."""
        report = ConsistencyReport(
            project_id=PID,
            checked=4,
            skipped=1,
            consistent=True,
        )
        assert report.checked == 4
        assert report.skipped == 1
        assert report.consistent is True
        assert report.conflicts == []
        assert report.flashbacks == []
        assert report.event_timeline == []
        assert report.narrative_order == []

    def test_report_requires_fields(self):
        """缺少必填字段（checked）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            ConsistencyReport(project_id=PID, skipped=0, consistent=True)


class TestTimelineView:
    """TimelineView 双线总览 schema 测试."""

    def test_view_requires_fields(self):
        """缺少必填字段（total）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            TimelineView(project_id=PID, event_timeline=[], narrative_order=[])

    def test_view_accepts_events(self):
        """双线视图可承载事件列表."""
        event = TimelineEvent(
            id=EID,
            project_id=PID,
            title="林尘觉醒金手指",
            created_at=TS,
            updated_at=TS,
        )
        view = TimelineView(
            project_id=PID,
            total=1,
            event_timeline=[event],
            narrative_order=[event],
        )
        assert view.total == 1
        assert view.event_timeline == [event]
        assert view.narrative_order == [event]
