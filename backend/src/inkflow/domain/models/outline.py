"""大纲管理领域模型 — 大纲/情节点/弧线实体与生成相关 DTO.

Outline / PlotPoint / StoryArc 是持久化实体（对应 outlines / plot_points /
story_arcs 表，通过 SQLAlchemy ORM 映射），OutlineCreate / OutlineUpdate /
PlotPointCreate / PlotPointUpdate / StoryArcCreate / StoryArcUpdate 是请求
DTO，GeneratedOutline / GeneratedPlotPoint / GeneratedArc 是 LLM 生成结果
的 schema 校验模型，OutlineGenerateRequest / OutlineGenerationResult 是
生成服务的入参/出参。

依据: specs/f11-outline/spec.md §2.5/§2.6。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _validate_name(v: str, field: str = "名称", max_len: int = 50) -> str:
    """共享的名称校验：去空白后非空且不超过 max_len 字符.

    Args:
        v: 原始输入名称.
        field: 字段中文名（用于错误消息，如「大纲名」「情节点名」「弧线名」）.
        max_len: 最大长度.

    Returns:
        去空白后的名称.

    Raises:
        ValueError: 名称为空/纯空白，或超过 max_len 字符.
    """
    stripped = v.strip()
    if not stripped:
        raise ValueError(f"{field}不能为空")
    if len(stripped) > max_len:
        raise ValueError(f"{field}不能超过 {max_len} 个字符")
    return stripped


def _validate_type(v: str) -> str:
    """情节点类型校验：去空白且不超过 20 字符（空串 = 未分类，允许）.

    Args:
        v: 原始输入类型.

    Returns:
        去空白后的类型.

    Raises:
        ValueError: 类型超过 20 字符.
    """
    stripped = v.strip()
    if len(stripped) > 20:
        raise ValueError("情节点类型不能超过 20 个字符")
    return stripped


def _validate_description(v: str, field: str = "描述", max_len: int = 5000) -> str:
    """描述类字段校验：不超过 max_len 字符（不强制去空白）.

    Args:
        v: 原始输入描述.
        field: 字段中文名（用于错误消息，如「大纲描述」「弧线说明」）.
        max_len: 最大长度.

    Returns:
        原样返回的描述.

    Raises:
        ValueError: 描述超过 max_len 字符.
    """
    if len(v) > max_len:
        raise ValueError(f"{field}不能超过 {max_len} 个字符")
    return v


def _validate_level(v: str) -> str:
    """大纲层级校验：仅接受 overall/volume/chapter（F43 P3 三级结构，spec §2.8）.

    Args:
        v: 原始层级值.

    Returns:
        原样返回的合法层级.

    Raises:
        ValueError: 层级不是 overall/volume/chapter.
    """
    if v not in {"overall", "volume", "chapter"}:
        raise ValueError("大纲层级只能为 overall/volume/chapter")
    return v


def _normalize_ref_field(v: Any, field: str) -> Any:
    """引用字段三态归一器（OutlineUpdate.parent_id/chapter_id/volume_id）.

    Args:
        v: 原始输入（HTTP JSON 字符串 / uuid.UUID / None）.
        field: 字段中文名（用于错误消息）.

    Returns:
        None（显式 null / 默认）; ""（空白字符串 → 清除哨兵，service 层转 None）;
        uuid.UUID（UUID 对象直通；合法 UUID 字符串强转，修复 #862）.

    Raises:
        ValueError: 非空且非 UUID 的字符串，或 str/UUID/None 之外的类型（→ 422）.
    """
    if v is None or isinstance(v, uuid.UUID):
        return v
    if isinstance(v, str):
        stripped = v.strip()
        if not stripped:
            return ""
        try:
            return uuid.UUID(stripped)
        except ValueError:
            raise ValueError(f"{field}必须是合法 UUID 字符串，空字符串表示清除") from None
    raise ValueError(f"{field}必须是 UUID 字符串、uuid.UUID 或 null")


class Outline(BaseModel):
    """大纲领域实体 — 对应 outlines 表.

    Attributes:
        id: 主键 UUID.
        project_id: 所属项目 UUID.
        name: 大纲名；项目内唯一（全唯一索引，见 spec §2.4）.
        description: 大纲总体描述（故事主线概述）.
        sort_order: 大纲间排序权重（小者在前）.
        level: 大纲层级（overall/volume/chapter；旧数据默认 chapter = 孤立章）.
        parent_id: 父大纲 UUID（volume→overall、chapter→volume；None = 顶层/孤立章）.
        chapter_id: 关联写作章节 UUID（仅 level=chapter 可设）.
        extra: 扩展属性字典（生成标记、来源约束等 Phase 2+ 字段预留）.
        created_at: 创建时间.
        updated_at: 最后更新时间.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str = ""
    sort_order: int = 0
    level: str = "chapter"  # F43 P3：overall/volume/chapter
    parent_id: uuid.UUID | None = None  # F43 P3：父大纲
    chapter_id: uuid.UUID | None = None  # F43 P3：关联写作章节（仅 chapter 可设）
    volume_id: uuid.UUID | None = None  # 卷关联（仅 level=volume 可设；本 spec #592）
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        """验证大纲层级：仅接受 overall/volume/chapter."""
        return _validate_level(v)


class PlotPoint(BaseModel):
    """情节点领域实体 — 对应 plot_points 表.

    Attributes:
        id: 主键 UUID.
        outline_id: 所属大纲 UUID（大纲删除 → FK 级联）.
        project_id: 所属项目 UUID（冗余存储，便于弧线归属校验与项目隔离）.
        name: 情节点名；大纲内允许重名（不做唯一约束）.
        type: 情节点类型（建议值：开篇/发展/转折/高潮/结局；空串 = 未分类）.
        description: 情节点要点描述.
        position: 大纲内排序（小者在前）；允许重复.
        arc_id: 所属故事弧线 UUID（可选；弧线删除 → FK 置 NULL）.
        extra: 扩展属性字典（参与角色、地点等 Phase 2+ 字段预留）.
        created_at: 创建时间.
        updated_at: 最后更新时间.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    outline_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    type: str = ""
    description: str = ""
    position: int = 0
    arc_id: uuid.UUID | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class StoryArc(BaseModel):
    """故事弧线领域实体 — 对应 story_arcs 表.

    Attributes:
        id: 主键 UUID.
        project_id: 所属项目 UUID.
        name: 弧线名；项目内唯一（全唯一索引，见 spec §2.4）.
        description: 弧线说明.
        created_at: 创建时间.
        updated_at: 最后更新时间.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str = ""
    created_at: datetime
    updated_at: datetime


class OutlineCreate(BaseModel):
    """创建大纲请求 DTO.

    Attributes:
        project_id: 所属项目 UUID，必填.
        name: 大纲名，必填，1-50 字符，去空白.
        description: 大纲描述，默认为空串，≤ 5000 字符.
        sort_order: 排序权重，默认为 0，≥ 0.
        level: 大纲层级，默认为 chapter（孤立章）.
        parent_id: 父大纲 UUID（可选；overall 禁父、volume 父须 overall、chapter 父须 volume）.
        chapter_id: 关联写作章节 UUID（可选；仅 level=chapter 可设）.
    """

    project_id: uuid.UUID
    name: str
    description: str = ""
    sort_order: int = 0
    level: str = "chapter"
    parent_id: uuid.UUID | None = None
    chapter_id: uuid.UUID | None = None
    volume_id: uuid.UUID | None = None  # 仅 level=volume 可设

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证大纲名：去空白后非空且不超过 50 字符."""
        return _validate_name(v, "大纲名", 50)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """验证大纲描述：不超过 5000 字符."""
        return _validate_description(v, "大纲描述", 5000)

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, v: int) -> int:
        """验证排序权重：非负."""
        if v < 0:
            raise ValueError("排序权重不能为负数")
        return v

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        """验证大纲层级：仅接受 overall/volume/chapter."""
        return _validate_level(v)


class OutlineUpdate(BaseModel):
    """更新大纲请求 DTO — 所有字段可选（exclude_unset 语义，同 F1）.

    name/description/sort_order: None 表示不修改；只有传入的字段会被更新，
    未传入的字段保持不变。
    level: None 表示不修改；传入合法层级则更新。
    parent_id/chapter_id/volume_id 三态（#862 修复后的契约）:
    - 未传入 = 不修改（默认 None 且不在 model_fields_set）;
    - 合法 UUID 对象或 UUID 字符串 = 设置（字符串经 mode="before" 校验器强转
      uuid.UUID）;
    - "" / 纯空白字符串 = 清除（保留 "" 哨兵，由 service 层转 None）; 显式 null 同清除;
    - 其它非空字符串（非 UUID）= ValueError → 422（绝不静默清除）。
    """

    name: str | None = None
    description: str | None = None
    sort_order: int | None = None
    level: str | None = None
    parent_id: uuid.UUID | str | None = None  # str "" = 清除父大纲
    chapter_id: uuid.UUID | str | None = None  # str "" = 清除章关联
    volume_id: uuid.UUID | str | None = None  # str "" = 清除卷关联

    @field_validator("parent_id", mode="before")
    @classmethod
    def validate_parent_id(cls, v: Any) -> Any:
        """父大纲引用归一：UUID 直通/字符串强转，"" 保留清除哨兵，垃圾串报错."""
        return _normalize_ref_field(v, "父大纲")

    @field_validator("chapter_id", mode="before")
    @classmethod
    def validate_chapter_id(cls, v: Any) -> Any:
        """章关联引用归一：UUID 直通/字符串强转，"" 保留清除哨兵，垃圾串报错."""
        return _normalize_ref_field(v, "章关联")

    @field_validator("volume_id", mode="before")
    @classmethod
    def validate_volume_id(cls, v: Any) -> Any:
        """卷关联引用归一：UUID 直通/字符串强转，"" 保留清除哨兵，垃圾串报错."""
        return _normalize_ref_field(v, "卷关联")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证大纲名：None（未提供）直接返回；否则复用共享校验."""
        if v is None:
            return v
        return _validate_name(v, "大纲名", 50)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """验证大纲描述：None（不修改）直接返回；否则复用共享校验."""
        if v is None:
            return v
        return _validate_description(v, "大纲描述", 5000)

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, v: int | None) -> int | None:
        """验证排序权重：None（不修改）直接返回；否则须非负."""
        if v is None:
            return v
        if v < 0:
            raise ValueError("排序权重不能为负数")
        return v

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str | None) -> str | None:
        """验证大纲层级：None（不修改）直接返回；否则仅接受 overall/volume/chapter."""
        if v is None:
            return v
        return _validate_level(v)


class PlotPointCreate(BaseModel):
    """创建情节点请求 DTO — project_id 取自大纲，不在 body.

    Attributes:
        outline_id: 所属大纲 UUID，必填.
        name: 情节点名，必填，1-100 字符，去空白.
        type: 情节点类型，默认为空串（未分类），≤ 20 字符，去空白.
        description: 情节点描述，默认为空串，≤ 5000 字符.
        position: 大纲内排序；None = 追加到大纲末尾（max+1），≥ 0.
        arc_id: 所属故事弧线 UUID（可选；None = 不挂弧线）.
    """

    outline_id: uuid.UUID
    name: str
    type: str = ""
    description: str = ""
    position: int | None = None
    arc_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证情节点名：去空白后非空且不超过 100 字符."""
        return _validate_name(v, "情节点名", 100)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """验证情节点类型：去空白且不超过 20 字符（空串合法）."""
        return _validate_type(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """验证情节点描述：不超过 5000 字符."""
        return _validate_description(v, "情节点描述", 5000)

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: int | None) -> int | None:
        """验证排序位置：None（追加语义）合法；否则须非负."""
        if v is not None and v < 0:
            raise ValueError("排序位置不能为负数")
        return v


class PlotPointUpdate(BaseModel):
    """更新情节点请求 DTO.

    arc_id: None 表示不修改；"" 表示清除弧线归属（置为不挂弧线）.
    只有传入的字段会被更新，未传入的字段保持不变.
    """

    name: str | None = None
    type: str | None = None
    description: str | None = None
    position: int | None = None
    arc_id: uuid.UUID | str | None = None  # str "" = 清除弧线

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证情节点名：None（未提供）直接返回；否则复用共享校验."""
        if v is None:
            return v
        return _validate_name(v, "情节点名", 100)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        """验证情节点类型：None（不修改）直接返回；""（清除类型）合法；否则复用共享校验."""
        if v is None:
            return v
        return _validate_type(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """验证情节点描述：None（不修改）直接返回；否则复用共享校验."""
        if v is None:
            return v
        return _validate_description(v, "情节点描述", 5000)

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: int | None) -> int | None:
        """验证排序位置：None（不修改）直接返回；否则须非负."""
        if v is None:
            return v
        if v < 0:
            raise ValueError("排序位置不能为负数")
        return v


class StoryArcCreate(BaseModel):
    """创建故事弧线请求 DTO.

    Attributes:
        project_id: 所属项目 UUID，必填.
        name: 弧线名，必填，1-50 字符，去空白.
        description: 弧线说明，默认为空串，≤ 500 字符.
    """

    project_id: uuid.UUID
    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证弧线名：去空白后非空且不超过 50 字符."""
        return _validate_name(v, "弧线名", 50)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """验证弧线说明：不超过 500 字符."""
        return _validate_description(v, "弧线说明", 500)


class StoryArcUpdate(BaseModel):
    """更新故事弧线请求 DTO — 所有字段可选（exclude_unset 语义，同 F1）.

    name/description: None 表示不修改；只有传入的字段会被更新，
    未传入的字段保持不变。
    """

    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证弧线名：None（未提供）直接返回；否则复用共享校验."""
        if v is None:
            return v
        return _validate_name(v, "弧线名", 50)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """验证弧线说明：None（不修改）直接返回；否则复用共享校验."""
        if v is None:
            return v
        return _validate_description(v, "弧线说明", 500)


class GeneratedArc(BaseModel):
    """LLM 生成出的弧线（schema 校验用）.

    name 非法（空/超长）时该条被跳过并记录 warning，不影响其余落库。
    """

    name: str  # 1-50 去空白；非法 → 跳过 + warning
    description: str | None = None  # ≤ 500；None/空串 = 无说明

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证弧线名：去空白后非空且不超过 50 字符."""
        return _validate_name(v, "弧线名", 50)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """验证弧线说明：None 直接返回；否则不超过 500 字符."""
        if v is None:
            return v
        return _validate_description(v, "弧线说明", 500)


class GeneratedPlotPoint(BaseModel):
    """LLM 生成出的情节点（schema 校验用）.

    name 非法（空/超长）时该条被跳过并记录 warning，不影响其余落库。
    arc 为弧线名引用（须能在 arcs 列表或库中解析）；无法解析 → 跳过关联 + warning，
    情节点本身照常落库（arc_id=None）。
    """

    name: str  # 1-100 去空白；非法 → 跳过 + warning
    type: str | None = None  # ≤ 20；None/空串 = 未分类
    description: str | None = None  # ≤ 5000；None/空串 = 无描述
    arc: str | None = None  # 弧线名引用（落库时解析为 arc_id）

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证情节点名：去空白后非空且不超过 100 字符."""
        return _validate_name(v, "情节点名", 100)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        """验证情节点类型：None 直接返回；否则去空白且不超过 20 字符."""
        if v is None:
            return v
        return _validate_type(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """验证情节点描述：None 直接返回；否则不超过 5000 字符."""
        if v is None:
            return v
        return _validate_description(v, "情节点描述", 5000)


class GeneratedOutline(BaseModel):
    """LLM 生成的结构化大纲（schema 校验用，§5.2 模板输出）.

    name/description 缺省时回退到请求参数（request.name / ""）。
    level 缺省 overall（整本根）；parent 为父大纲名引用（level=volume/chapter 时用于建链；
    overall 为根无需 parent）。
    """

    name: str | None = None
    description: str | None = None
    level: str = "overall"  # #835：overall/volume/chapter，默认整本根
    parent: str | None = None  # #835：父大纲名引用（落库时按名解析建链）
    arcs: list[GeneratedArc] = Field(default_factory=list)  # 可空
    plot_points: list[GeneratedPlotPoint] = Field(default_factory=list)  # 可空（空 → warning）

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证大纲名：None（回退请求参数）直接返回；否则复用共享校验."""
        if v is None:
            return v
        return _validate_name(v, "大纲名", 50)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """验证大纲描述：None（回退空串）直接返回；否则不超过 5000 字符."""
        if v is None:
            return v
        return _validate_description(v, "大纲描述", 5000)

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        """验证生成大纲层级：仅接受 overall/volume/chapter."""
        return _validate_level(v)


class OutlineGenerateRequest(BaseModel):
    """AI 生成大纲请求.

    Attributes:
        project_id: 所属项目 UUID，必填.
        name: 目标大纲名；缺省「未命名大纲」（撞名 → 422）.
        prompt: 可选创作约束/设定摘要（自由文本，≤ 20000；None/空 = 无约束）.
        num_chapters: 可选规划章节数提示（1-100）.
        save: True=自动落库；False=仅返回预览（不创建任何实体）.
        model: 覆盖项目默认模型（格式 provider/model_name）.
        target_outline_id: 覆盖目标大纲（仅 mode="replace" 有效；缺省 None）.
        mode: 生成模式；"new"=生成即新建（现行为），"replace"=覆盖目标大纲
            全部情节点（#669，需用户确认后应用）.
    """

    project_id: uuid.UUID
    name: str | None = None
    prompt: str | None = None
    num_chapters: int | None = None
    save: bool = True
    model: str | None = None
    target_outline_id: uuid.UUID | None = None  # 覆盖目标大纲（仅 mode="replace" 有效）
    mode: str = "new"  # "new"=生成即新建（现行为）/ "replace"=覆盖目标大纲情节点

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证目标大纲名：None（缺省）直接返回；否则复用共享校验."""
        if v is None:
            return v
        return _validate_name(v, "大纲名", 50)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str | None) -> str | None:
        """验证生成提示：None/空串（无约束）合法；否则不超过 20000 字符."""
        if v is None:
            return v
        if len(v) > 20000:
            raise ValueError("生成提示不能超过 20000 个字符")
        return v

    @field_validator("num_chapters")
    @classmethod
    def validate_num_chapters(cls, v: int | None) -> int | None:
        """验证规划章节数：None（不提示）合法；否则须在 1-100 之间."""
        if v is None:
            return v
        if v < 1:
            raise ValueError("章节数不能小于 1")
        if v > 100:
            raise ValueError("章节数不能超过 100")
        return v

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        """验证生成模式：仅接受 new/replace（#669）."""
        if v not in {"new", "replace"}:
            raise ValueError("生成模式只能为 new/replace")
        return v

    @model_validator(mode="after")
    def validate_mode_target(self) -> OutlineGenerateRequest:
        """交叉校验 mode/target_outline_id（#669）：replace 必须指定目标大纲；
        new 模式不允许携带目标大纲."""
        if self.mode == "replace" and self.target_outline_id is None:
            raise ValueError("覆盖模式必须指定目标大纲")
        if self.mode == "new" and self.target_outline_id is not None:
            raise ValueError("目标大纲仅在覆盖模式下有效")
        return self


class OutlineGenerationResult(BaseModel):
    """大纲生成结果.

    save=True: outline/plot_points/arcs 为落库后的实体（含新 id）.
    save=False: preview 为生成的原始结构（未落库，无 id），outline 为 None.
    requires_confirmation: replace 模式（save=True）暂存待确认 = True（#669）.
    target_outline_id: 覆盖模式回显目标大纲（缺省 None）.
    """

    saved: bool
    outline: Outline | None = None
    plot_points: list[PlotPoint] = Field(default_factory=list)
    arcs: list[StoryArc] = Field(default_factory=list)
    preview: GeneratedOutline | None = None  # 仅 save=False 时非空
    warnings: list[str] = Field(default_factory=list)
    model: str
    requires_confirmation: bool = False  # replace 模式暂存待确认 = True（#669）
    target_outline_id: uuid.UUID | None = None  # 覆盖模式回显目标大纲
