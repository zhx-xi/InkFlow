"""F14 统一提取服务领域模型 — 枚举 / DTO / 增量追踪记录.

ExtractionType 是统一提取接口的入口枚举（6 种类型，spec §2.1）；
ExtractionRequest / ExtractionResult 是统一提取的请求/结果信封（§2.2）；
ExtractionRun 是增量追踪记录（每 (project, type, source) 一行最新状态，
§2.3）；ReindexResult 是全量重建索引结果（§5.6），引用 P0-11 已定义的
EntityType（§2.4，不重定义）。

依据: specs/f14-extraction-service/spec.md §2.1/§2.2/§2.3/§2.5。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from inkflow.domain.ports.vector_store import EntityType  # P0-11 已定义，引用不重定义（§2.4）


class ExtractionType(StrEnum):
    """统一提取接口的 6 种类型（PRD P1-06 验收标准 ①，§2.1）.

    Attributes:
        CHARACTER: 角色提取 → 委托 F9 CharacterService.extract.
        SETTING: 世界提取 → 委托 F10 WorldService.extract.
        OUTLINE: 大纲生成 → 委托 F11 OutlineService.generate（生成模式）.
        TIMELINE: 时间线事件提取（设置项开启，§5.5）/ 一致性检查（关闭，
            委托 F12 check_consistency）.
        FORESHADOWING: 伏笔提取 → 本模块新建 ForeshadowingExtractor
            （F13 移交，§5.4）.
        STYLE: 风格检测 → 注册占位（F16 未实现，调用返回 422，§6.1）.
    """

    CHARACTER = "character"
    SETTING = "setting"
    OUTLINE = "outline"
    TIMELINE = "timeline"
    FORESHADOWING = "foreshadowing"
    STYLE = "style"
    KNOWLEDGE_RELATION = "knowledge_relation"


class ExtractionStatus(StrEnum):
    """统一结果状态 — MVP 产出 SUCCESS / SKIPPED；ERROR 预留（§5.3）.

    Attributes:
        SUCCESS: 管线执行完成（含部分成功：部分源 skip、部分源执行）.
        SKIPPED: 全部源内容未变更（增量提取，§5.2），未调用 LLM.
        ERROR: 预留：门面内错误走异常（ADR-012），该值供 run 记录表使用.
    """

    SUCCESS = "success"
    SKIPPED = "skipped"
    ERROR = "error"


class ExtractionRequest(BaseModel):
    """统一提取请求（§2.2）— 类型相关参数约束见 §6.4 输入约束表.

    Attributes:
        project_id: 所属项目 UUID.
        type: 提取类型（6 种，决定参数语义与分发目标）.
        text: 手动文本（与 chapter_ids 互斥，≤ 50000 字符；仅
            character/setting/foreshadowing 及 timeline 开启时使用）.
        chapter_ids: 章节模式（从 F2 读取内容，增量追踪，≤ 100 章）.
        prompt: outline: 生成约束（透传 F11）.
        num_chapters: outline: 规划章节数 1-100（透传 F11）.
        save: outline: 落库开关（透传 F11；False=仅预览）.
        include_flashbacks: timeline: 透传 F12 check_consistency（关闭语义）.
        auto_extract: timeline: TIMELINE 设置项覆盖（覆盖项目配置
            timeline_auto_extract，§2.6；None=跟随项目配置）.
        model: LLM 类型: 覆盖项目默认模型（provider/model_name）.
        index: 提取成功后自动索引本次产物（RAG，§5.6）.
        force: 忽略增量 skip，强制重跑（§5.2）.
    """

    project_id: uuid.UUID
    type: ExtractionType
    text: str | None = None  # 手动文本（与 chapter_ids 互斥，≤ 50000 字符）
    chapter_ids: list[uuid.UUID] | None = None  # 章节模式（从 F2 读取内容，增量追踪，≤ 100 章）
    prompt: str | None = None  # outline: 生成约束（透传 F11）
    num_chapters: int | None = None  # outline: 规划章节数 1-100（透传 F11）
    save: bool = True  # outline: 落库开关（透传 F11；False=仅预览）
    include_flashbacks: bool = True  # timeline: 透传 F12 check_consistency（关闭语义）
    auto_extract: bool | None = None  # timeline: TIMELINE 设置项覆盖（§2.6；None=跟随项目配置）
    model: str | None = None  # LLM 类型: 覆盖项目默认模型（provider/model_name）
    index: bool = False  # 提取成功后自动索引本次产物（RAG，§5.6）
    force: bool = False  # 忽略增量 skip，强制重跑（§5.2）

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str | None) -> str | None:
        """验证手动文本：None 合法；去空白后非空且不超过 50000 字符."""
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("章节文本不能为空")
        if len(stripped) > 50000:
            raise ValueError("章节文本不能超过 50000 个字符")
        return stripped

    @field_validator("chapter_ids")
    @classmethod
    def validate_chapter_ids(cls, v: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        """验证章节模式：None 合法；非空列表且不超过 100 章."""
        if v is None:
            return None
        if not v:
            raise ValueError("chapter_ids 不能为空列表")
        if len(v) > 100:
            raise ValueError("单次提取章节数不能超过 100")
        return v

    @field_validator("num_chapters")
    @classmethod
    def validate_num_chapters(cls, v: int | None) -> int | None:
        """验证大纲规划章节数：None 合法；否则须在 1-100 之间."""
        if v is None:
            return None
        if not 1 <= v <= 100:
            raise ValueError("num_chapters 必须在 1-100 之间")
        return v

    @model_validator(mode="after")
    def validate_source_exclusive(self) -> ExtractionRequest:
        """验证 text 与 chapter_ids 互斥（二选一，§2.2/§7：422 语义）."""
        if self.text is not None and self.chapter_ids is not None:
            raise ValueError("text 与 chapter_ids 不能同时使用")
        return self


class ExtractionResult(BaseModel):
    """统一提取结果（§2.2/§5.3）— 各类型共用的信封结构.

    Attributes:
        type: 请求类型原样回显.
        status: success / skipped（error 走异常 + run 记录，§5.3）.
        skipped_reason: status=skipped 时的原因文案（如「内容未变更
            （源: chapter xxx）」）.
        processed_sources: 执行管线的源数（章节模式=执行的章数；手动=1；
            outline=1；timeline=开启时按源数、关闭时=1）.
        skipped_sources: 增量跳过的源数（章节模式=hash 相同的章数；
            手动=0 或 1；timeline 关闭时=0）.
        created: 归一化「新增」计数（§5.3 各类型口径）.
        updated: 归一化「更新」计数.
        warnings: 各管线 warning 汇总（解析条目跳过、软删同名新建等）.
        model: 实际使用的 LLM 模型（LLM 类型；timeline 关闭时为 None）.
        indexed: 是否执行了向量索引（request.index 且类型支持；
            timeline 关闭时恒 False）.
        detail: 各类型原始结果 model_dump（§5.3），含实体列表与冲突明细.
    """

    type: ExtractionType
    status: ExtractionStatus
    skipped_reason: str | None = None  # status=skipped 时的原因文案
    processed_sources: int = 0  # 本次实际执行管线的源数（章节模式=执行的章数，手动=1）
    skipped_sources: int = 0  # 本次因内容未变更跳过的源数
    created: int = 0  # 归一化「新增」计数（§5.3 各类型口径）
    updated: int = 0  # 归一化「更新」计数
    warnings: list[str] = Field(default_factory=list)  # 各管线 warning 汇总
    model: str | None = None  # 实际使用的 LLM 模型（LLM 类型；timeline 关闭时为 None）
    indexed: bool = False  # 本次是否执行了向量索引（request.index 且类型支持）
    detail: dict[str, Any] = Field(default_factory=dict)  # 各类型原始结果 model_dump（§5.3）


class ExtractionRun(BaseModel):
    """增量追踪记录（§2.3）— 每 (project, type, source) 一行最新状态.

    记录「每个 (project, type, 源) 的最后一次提取状态」，是增量提取的判定
    依据（§5.2）。每源一行最新状态（upsert），不是历史表——历史变更审计
    归 F15（§10）。

    Attributes:
        id: DB 自增主键（领域层直接暴露 int id，同 timeline_events 先例）.
        project_id: 所属项目 UUID.
        type: ExtractionType.value.
        source_key: 源标识：章节模式=str(chapter_id)；手动模式="manual"；
            outline 与 timeline（设置项关闭）固定 "full".
        content_hash: 源内容 sha256（UTF-8），增量判定指纹（§5.2）.
        status: success / skipped / error（失败 run 也落库，供 extract status
            观察缺口）.
        created_count: 该源本次新增数.
        updated_count: 该源本次更新数.
        warnings_json: warnings JSON 序列化（持久化可观测性）.
        error: status=error 时的错误消息（截断 ≤ 500 字符）.
        model: 该源实际使用的 LLM 模型.
        indexed: 该源是否已索引（index=true 且类型支持时置 True）.
        run_at: 本次运行时间 (UTC).
    """

    model_config = {"from_attributes": True}

    id: int  # DB 自增主键（领域层直接暴露 int id，同 timeline_events 先例）
    project_id: uuid.UUID  # 所属项目 UUID
    type: ExtractionType  # ExtractionType.value
    source_key: str  # 源标识：章节模式=str(chapter_id)；手动模式="manual"
    content_hash: str  # 源内容 sha256（UTF-8），增量判定指纹（§5.2）
    status: ExtractionStatus = ExtractionStatus.SUCCESS  # success / skipped / error
    created_count: int = 0  # 该源本次新增数
    updated_count: int = 0  # 该源本次更新数
    warnings_json: str = "[]"  # warnings JSON 序列化（持久化可观测性）
    error: str | None = None  # status=error 时的错误消息（截断 ≤ 500 字符）
    model: str | None = None  # 该源实际使用的 LLM 模型
    indexed: bool = False  # 该源是否已索引（index=true 且类型支持时置 True）
    run_at: datetime  # 本次运行时间 (UTC)


class ReindexResult(BaseModel):
    """全量重建索引结果（§5.6）— vector reindex / POST vector/reindex.

    Attributes:
        project_id: 所属项目 UUID.
        entity_types: 实际处理的实体类型（EntityType 枚举）.
        indexed: 索引的实体总数（含 upsert 覆盖）.
        warnings: 重建过程中的 warning 汇总.
        collections_recreated: 维度不匹配重建标志（#276）——探测到现存向量
            维度与当前 embedding 维度不一致时重建 collection 为 True.
    """

    project_id: uuid.UUID
    entity_types: list[EntityType]  # 实际处理的实体类型
    indexed: int  # 索引的实体总数（含 upsert 覆盖）
    warnings: list[str] = Field(default_factory=list)  # warning 汇总
    collections_recreated: bool = False  # 维度不匹配重建标志（#276）
