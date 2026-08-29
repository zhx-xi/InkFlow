"""时间线管理领域模型 — 时间线事件实体与检查相关模型.

TimelineEvent 是持久化实体（对应 timeline_events 表，通过 SQLAlchemy ORM
映射），同时携带两个时间维度：**世界内时间**（time_value / time_unit /
time_display 三字段，构成事件时间线）与**叙事位置**（narrative_position，
构成叙事时间线）。TimelineEventCreate / TimelineEventUpdate 是请求 DTO，
TimelineEventRef / TimelineConflict / ConsistencyReport / TimelineView 是
双线视图与一致性检查（§5，确定性算法，无 LLM）的输出模型。

依据: specs/f12-timeline/spec.md §2.5/§2.6。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

TIME_VALUE_LIMIT = 1e12


def _validate_title(v: str) -> str:
    """共享的标题校验：去空白后非空且不超过 100 字符.

    Args:
        v: 原始输入标题.

    Returns:
        去空白后的标题.

    Raises:
        ValueError: 标题为空/纯空白，或超过 100 字符.
    """
    stripped = v.strip()
    if not stripped:
        raise ValueError("事件标题不能为空")
    if len(stripped) > 100:
        raise ValueError("事件标题不能超过 100 个字符")
    return stripped


def _validate_short_text(v: str, field: str, max_len: int) -> str:
    """共享的短文本校验：去空白且不超过 max_len 字符（空串 = 无，允许）.

    Args:
        v: 原始输入文本.
        field: 字段中文名（用于错误消息，如「时间单位」「时间线标记」）.
        max_len: 最大长度.

    Returns:
        去空白后的短文本.

    Raises:
        ValueError: 短文本超过 max_len 字符.
    """
    stripped = v.strip()
    if len(stripped) > max_len:
        raise ValueError(f"{field}不能超过 {max_len} 个字符")
    return stripped


def _validate_description(v: str) -> str:
    """共享的描述校验：不超过 5000 字符（不强制去空白）.

    Args:
        v: 原始输入描述.

    Returns:
        原样返回的描述.

    Raises:
        ValueError: 描述超过 5000 字符.
    """
    if len(v) > 5000:
        raise ValueError("事件描述不能超过 5000 个字符")
    return v


def _validate_time_value(v: float | None) -> float | None:
    """共享的世界内时间校验：有限数值且 |v| ≤ 1e12；None = 时间未知（允许）.

    Args:
        v: 原始输入时间值.

    Returns:
        校验通过的时间值（None 原样返回）.

    Raises:
        ValueError: 时间值为 NaN/±Inf，或超出 [-1e12, 1e12] 范围.
    """
    if v is None:
        return None
    if not math.isfinite(v):
        raise ValueError("世界内时间必须是有限数值")
    if abs(v) > TIME_VALUE_LIMIT:
        raise ValueError("世界内时间超出允许范围（[-10^12, 10^12]）")
    return v


def _validate_text(v: str) -> str:
    """共享的提取文本校验：去空白后非空且不超过 50000 字符.

    Args:
        v: 原始输入文本.

    Returns:
        去空白后的文本.

    Raises:
        ValueError: 文本为空/纯空白，或超过 50000 字符.
    """
    stripped = v.strip()
    if not stripped:
        raise ValueError("提取文本不能为空")
    if len(stripped) > 50000:
        raise ValueError("提取文本不能超过 50000 个字符")
    return stripped


class TimelineEvent(BaseModel):
    """时间线事件领域实体 — 对应 timeline_events 表.

    事件同时携带世界内时间（事件发生在何时）与叙事位置（第几个被讲）两个
    时间维度，两者独立可编辑——正是需要一致性检查（§5）的原因。

    Attributes:
        id: 主键 UUID.
        project_id: 所属项目 UUID.
        title: 事件标题；允许重复（事件是实例而非档案，无唯一约束）.
        description: 事件描述（该时刻发生了什么）.
        time_value: 世界内时间数值键（可排序、可比较）；None = 时间未知
            （事件时间线排末尾、不参与一致性检查）.
        time_unit: 时间单位标签（纪元/年/月/日/时；自由文本，仅语义，不参与排序）.
        time_display: 原始时间表达（time_value 的人工可读镜像，不参与排序）.
        narrative_position: 叙事位置（单一线性序号，小者在前 = 先被叙述）.
        timeline_flag: 时间线标记（"" = 正叙、flashback = 倒叙、
            flashforward = 插叙/预叙；自由文本，未在建议词表的值等同未标记）.
        source_chapter_id: F14 提取来源章节（Q3 联动锚点）— 仅作来源追溯，
            不参与业务规则校验；None = 手工事件（不参与提取合并匹配）.
        extra: 扩展属性字典（参与角色、地点、标签等 Phase 2+ 字段预留）.
        created_at: 创建时间 (UTC).
        updated_at: 最后更新时间 (UTC).
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str = ""
    time_value: float | None = None  # None = 世界内时间未知
    time_unit: str = ""  # 单位标签（纪元/年/日…），仅语义
    time_display: str = ""  # 原始时间表达（如「青元历 317 年秋」）
    narrative_position: int = 0
    timeline_flag: str = ""  # ""/flashback/flashforward（建议值，自由文本）
    source_chapter_id: uuid.UUID | None = None  # F14 提取来源章节（Q3 联动）; None = 手工事件
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class TimelineEventCreate(BaseModel):
    """创建时间线事件请求 DTO.

    Attributes:
        project_id: 所属项目 UUID，必填.
        title: 事件标题，必填，1-100 字符，去空白.
        description: 事件描述，默认为空串，≤ 5000 字符.
        time_value: 世界内时间数值键；None = 时间未知（合法，计入 skipped）.
        time_unit: 时间单位标签，默认为空串，≤ 20 字符，去空白.
        time_display: 原始时间表达，默认为空串，≤ 100 字符，去空白.
        narrative_position: 叙事位置；None = 追加到叙事末尾（max+1），≥ 0.
        timeline_flag: 时间线标记，默认为空串（正叙），≤ 20 字符，去空白.
        source_chapter_id: F14 提取来源章节；None = 手工事件（不参与提取合并匹配）.
    """

    project_id: uuid.UUID
    title: str
    description: str = ""
    time_value: float | None = None  # None = 时间未知
    time_unit: str = ""
    time_display: str = ""
    narrative_position: int | None = None  # None = 追加到叙事末尾（max+1）
    timeline_flag: str = ""
    source_chapter_id: uuid.UUID | None = None  # None = 手工事件（不参与提取合并匹配）

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """验证事件标题：去空白后非空且不超过 100 字符."""
        return _validate_title(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """验证事件描述：不超过 5000 字符."""
        return _validate_description(v)

    @field_validator("time_value")
    @classmethod
    def validate_time_value(cls, v: float | None) -> float | None:
        """验证世界内时间：None 合法；否则须有限且 |v| ≤ 1e12."""
        return _validate_time_value(v)

    @field_validator("time_unit")
    @classmethod
    def validate_time_unit(cls, v: str) -> str:
        """验证时间单位：去空白且不超过 20 字符（空串合法）."""
        return _validate_short_text(v, "时间单位", 20)

    @field_validator("time_display")
    @classmethod
    def validate_time_display(cls, v: str) -> str:
        """验证时间显示文本：去空白且不超过 100 字符（空串合法）."""
        return _validate_short_text(v, "时间显示文本", 100)

    @field_validator("narrative_position")
    @classmethod
    def validate_narrative_position(cls, v: int | None) -> int | None:
        """验证叙事位置：None（追加语义）合法；否则须非负."""
        if v is not None and v < 0:
            raise ValueError("叙事位置不能为负数")
        return v

    @field_validator("timeline_flag")
    @classmethod
    def validate_timeline_flag(cls, v: str) -> str:
        """验证时间线标记：去空白且不超过 20 字符（空串合法）."""
        return _validate_short_text(v, "时间线标记", 20)


class TimelineEventUpdate(BaseModel):
    """更新时间线事件请求 DTO — 所有字段可选（exclude_unset 语义，同 F1）.

    time_value: None 表示不修改；"" 表示清除世界内时间（置为未知）.
    timeline_flag: None 表示不修改；"" 表示清除标记（置为正叙）.
    time_unit/time_display: None 表示不修改；"" 表示清除（置空串）.
    source_chapter_id: None 表示不修改（同其他可空字段语义）.
    只有传入的字段会被更新，未传入的字段保持不变.
    """

    title: str | None = None
    description: str | None = None
    time_value: float | str | None = None  # str "" = 清除世界内时间
    time_unit: str | None = None
    time_display: str | None = None
    narrative_position: int | None = None
    timeline_flag: str | None = None
    source_chapter_id: uuid.UUID | None = None  # None 不修改（同其他可空字段语义）

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        """验证事件标题：None（未提供）直接返回；否则复用共享校验."""
        return _validate_title(v) if v is not None else None

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """验证事件描述：None（不修改）直接返回；否则复用共享校验."""
        return _validate_description(v) if v is not None else None

    @field_validator("time_value")
    @classmethod
    def validate_time_value(cls, v: float | str | None) -> float | str | None:
        """验证世界内时间：None（不修改）直接返回；""（清除）合法；否则须有限且在范围内."""
        if isinstance(v, str):
            if v != "":
                raise ValueError("清除世界内时间请传空字符串")
            return v
        return _validate_time_value(v)

    @field_validator("time_unit")
    @classmethod
    def validate_time_unit(cls, v: str | None) -> str | None:
        """验证时间单位：None（不修改）直接返回；""（清除）合法；否则复用共享校验."""
        return _validate_short_text(v, "时间单位", 20) if v is not None else None

    @field_validator("time_display")
    @classmethod
    def validate_time_display(cls, v: str | None) -> str | None:
        """验证时间显示文本：None（不修改）直接返回；""（清除）合法；否则复用共享校验."""
        return _validate_short_text(v, "时间显示文本", 100) if v is not None else None

    @field_validator("narrative_position")
    @classmethod
    def validate_narrative_position(cls, v: int | None) -> int | None:
        """验证叙事位置：None（不修改）直接返回；否则须非负."""
        if v is not None and v < 0:
            raise ValueError("叙事位置不能为负数")
        return v

    @field_validator("timeline_flag")
    @classmethod
    def validate_timeline_flag(cls, v: str | None) -> str | None:
        """验证时间线标记：None（不修改）直接返回；""（清除）合法；否则复用共享校验."""
        return _validate_short_text(v, "时间线标记", 20) if v is not None else None


class TimelineEventRef(BaseModel):
    """一致性检查中的事件引用（轻量快照，避免整表序列化）.

    Attributes:
        id: 事件 UUID.
        title: 事件标题.
        time_value: 世界内时间数值键（None = 时间未知）.
        time_display: 原始时间表达.
        narrative_position: 叙事位置.
        timeline_flag: 时间线标记.
    """

    id: uuid.UUID
    title: str
    time_value: float | None
    time_display: str
    narrative_position: int
    timeline_flag: str


class TimelineConflict(BaseModel):
    """单条时间线冲突/倒叙记录.

    conflict_type:
      - order_conflict: 未标记的逆序对（叙事顺序与世界内时间矛盾，需修正）
      - flashback: 逆序对且 next 事件声明了 flashback（合法倒叙）
      - flashforward: 逆序对且 prev 事件声明了 flashforward（合法插叙/预叙）
    """

    conflict_type: Literal["order_conflict", "flashback", "flashforward"]
    prev: TimelineEventRef  # 叙事顺序中靠前的事件（世界内时间较晚）
    next: TimelineEventRef  # 叙事顺序中靠后的事件（世界内时间较早）
    message: str  # 人类可读描述（含修正建议）


class ConsistencyReport(BaseModel):
    """时间线一致性检查报告（§5）.

    Attributes:
        project_id: 所属项目 UUID.
        checked: 参与比较的事件数（time_value 非 None）.
        skipped: 时间未知被跳过的事件数.
        consistent: conflicts 为空.
        conflicts: 需修正的冲突（order_conflict）.
        flashbacks: 已声明的倒叙/插叙（include_flashbacks=false 时为空列表）.
        event_timeline: 事件时间线视图（time_value 升序，未知排末尾）.
        narrative_order: 叙事顺序视图（narrative_position 升序）.
    """

    project_id: uuid.UUID
    checked: int  # 参与比较的事件数（time_value 非 None）
    skipped: int  # 时间未知被跳过的事件数
    consistent: bool  # conflicts 为空
    conflicts: list[TimelineConflict] = []  # 需修正的冲突（order_conflict）
    flashbacks: list[TimelineConflict] = []  # 倒叙/插叙（include_flashbacks=false 时为空）
    event_timeline: list[TimelineEvent] = []  # 事件时间线视图（time_value 升序，未知排末尾）
    narrative_order: list[TimelineEvent] = []  # 叙事顺序视图（narrative_position 升序）


class EventCheckReport(BaseModel):
    """单事件检查报告（F43 P4 spec §2.9/§3.7）.

    仅报告该事件作为叙事相邻对 prev/next 参与的逆序冲突（复用 check_consistency
    的相邻对分类：order_conflict/flashback/flashforward，零新冲突类型）。

    Attributes:
        event_id: 被检查事件 UUID.
        checked: 该事件 time_value 是否非 None（None = 不参与检查）.
        consistent: conflicts 为空.
        conflicts: 该事件参与的 order_conflict.
        flashbacks: 该事件参与的 flashback/flashforward.
    """

    event_id: uuid.UUID
    checked: bool
    consistent: bool
    conflicts: list[TimelineConflict] = []
    flashbacks: list[TimelineConflict] = []


class TimelineView(BaseModel):
    """双时间线总览（事件时间线 + 叙事时间线）.

    Attributes:
        project_id: 所属项目 UUID.
        total: 事件总数.
        event_timeline: 事件时间线（世界内时间升序，未知排末尾）.
        narrative_order: 叙事时间线（叙事位置升序）.
    """

    project_id: uuid.UUID
    total: int
    event_timeline: list[TimelineEvent]  # 事件时间线（世界内时间升序，未知排末尾）
    narrative_order: list[TimelineEvent]  # 叙事时间线（叙事位置升序）


class ExtractedTimelineEvent(BaseModel):
    """LLM 提取出的时间线事件（F14 §5.5 schema 校验用；落库前合并）.

    提取字段 None = 「未知/不覆盖」（合并时保留库中原值）；空字符串是
    明确值（如 timeline_flag="" = 明确无标记），照常覆盖。title 是合并
    匹配键 (project_id, title, source_chapter_id) 的一部分，不参与覆盖。

    Attributes:
        title: 事件标题，必填，1-100 字符，去空白.
        description: 事件描述（该时刻发生了什么）；None = 不覆盖.
        time_value: 世界内时间数值键（无法推断 → null）；None = 不覆盖；
            校验同 F12：有限且 |v| ≤ 1e12.
        time_unit: 时间单位标签（纪元/年/月/日/时）；None = 不覆盖.
        narrative_position: 叙事位置（LLM 输出或 null——新建时 null = F12
            追加语义）；None = 不覆盖.
        timeline_flag: 时间线标记（""/flashback/flashforward）；None = 不覆盖.
    """

    title: str
    description: str | None = None
    time_value: float | None = None
    time_unit: str | None = None
    narrative_position: int | None = None
    timeline_flag: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """验证事件标题：去空白后非空且不超过 100 字符."""
        return _validate_title(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """验证事件描述：None（不覆盖）直接返回；否则不超过 5000 字符."""
        return _validate_description(v) if v is not None else None

    @field_validator("time_value")
    @classmethod
    def validate_time_value(cls, v: float | None) -> float | None:
        """验证世界内时间：None（不覆盖）直接返回；否则须有限且 |v| ≤ 1e12."""
        return _validate_time_value(v)

    @field_validator("time_unit")
    @classmethod
    def validate_time_unit(cls, v: str | None) -> str | None:
        """验证时间单位：None（不覆盖）直接返回；否则去空白且不超过 20 字符."""
        return _validate_short_text(v, "时间单位", 20) if v is not None else None

    @field_validator("narrative_position")
    @classmethod
    def validate_narrative_position(cls, v: int | None) -> int | None:
        """验证叙事位置：None（不覆盖）直接返回；否则须非负."""
        if v is not None and v < 0:
            raise ValueError("叙事位置不能为负数")
        return v

    @field_validator("timeline_flag")
    @classmethod
    def validate_timeline_flag(cls, v: str | None) -> str | None:
        """验证时间线标记：None（不覆盖）直接返回；否则去空白且不超过 20 字符."""
        return _validate_short_text(v, "时间线标记", 20) if v is not None else None


class TimelineExtractRequest(BaseModel):
    """时间线提取请求（F14 §5.5 管线入口 DTO）.

    Attributes:
        project_id: 所属项目 UUID.
        chapter_id: 来源章节 UUID（合并匹配键 (project_id, title,
            source_chapter_id) 的一部分；新建事件记录为 source_chapter_id）.
        text: 待提取文本，必填，去空白非空，≤ 50000 字符.
        model: 覆盖项目默认模型（格式 provider/model_name）；None 用默认.
    """

    project_id: uuid.UUID
    chapter_id: uuid.UUID
    text: str
    model: str | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        """验证提取文本：去空白后非空且不超过 50000 字符."""
        return _validate_text(v)


class TimelineExtractionResult(BaseModel):
    """时间线提取结果 — 合并落库后的报告（F14 §5.5 步骤 ⑦）.

    Attributes:
        created: 本次新建的事件列表.
        updated: 本次更新（同名同章合并）的事件列表.
        warnings: 提取/合并过程中的警告信息（跳过条目等）.
        model: 实际使用的模型.
    """

    created: list[TimelineEvent]
    updated: list[TimelineEvent]
    warnings: list[str]
    model: str
