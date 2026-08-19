"""AppSettings 领域模型 — 应用级设置（全局用户偏好，settings 表承载）。

依据: specs/f32-settings-persistence/spec.md §2。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, field_validator

ThemeName = Literal["paper", "night", "ink"]
ThemeBg = Literal["default", "parchment", "navy", "ochre"]
Lang = Literal["zh", "en"]
FontKey = Literal["serif", "sans", "mono"]
CloseBehavior = Literal["tray", "quit"]
ChunkMode = Literal["fixed", "paragraph", "dialogue", "llm"]


class SettingsKey(StrEnum):
    """设置键枚举 — app_settings 表 key 列的稳定标识（新增设置项在此扩展）。"""

    THEME = "theme"
    BG = "bg"
    LANG = "lang"
    FONT = "font"
    CLOSE_BEHAVIOR = "close_behavior"
    TRAY_HINT_DISMISSED = "tray_hint_dismissed"
    DEFAULT_WORDS = "default_words"
    AGENT_MAX_STEPS = "agent_max_steps"
    AGENT_TOKEN_BUDGET = "agent_token_budget"
    AGENT_MAX_TOTAL_TOOL_CALLS = "agent_max_total_tool_calls"
    RAG_CHUNK_MODE = "rag_chunk_mode"
    RAG_CHUNK_SIZE = "rag_chunk_size"
    RAG_CHUNK_OVERLAP = "rag_chunk_overlap"
    RAG_CHUNK_OVERLAP_RATIO = "rag_chunk_overlap_ratio"
    KG_EXTRACT_ENABLED = "kg_extract_enabled"
    KG_EXTRACT_INTERVAL_HOURS = "kg_extract_interval_hours"
    KG_EXTRACT_METHOD = "kg_extract_method"


class AppSettings(BaseModel):
    """全量设置对象（GET / PATCH 响应统一形态；字段缺省 = 默认值语义）。

    默认值与前端现状对齐（§2.1 表）：theme='paper' 是「无显式选择」的
    后端表示，系统深色跟随策略由前端首帧处理（§5.2），后端不感知。
    """

    model_config = {"from_attributes": True}

    theme: ThemeName = "paper"
    bg: ThemeBg = "default"
    lang: Lang = "zh"
    font: FontKey = "sans"
    close_behavior: CloseBehavior = "tray"
    tray_hint_dismissed: bool = False
    default_words: int = 800000
    agent_max_steps: int = 12
    agent_token_budget: int = 32000
    agent_max_total_tool_calls: int = 20
    rag_chunk_mode: ChunkMode = "fixed"
    rag_chunk_size: int = 500
    rag_chunk_overlap: bool = False
    rag_chunk_overlap_ratio: float = 0.15
    kg_extract_enabled: bool = False
    kg_extract_interval_hours: int = 24
    kg_extract_method: Literal["rule", "ai", "both"] = "rule"

    @field_validator("rag_chunk_size")
    @classmethod
    def _validate_chunk_size(cls, v: int) -> int:
        """切片大小越界校验（spec §5.6.2: 100-2000，越界 → 422 ValidationError）。"""
        if not 100 <= v <= 2000:
            raise ValueError("rag_chunk_size 必须在 100-2000 之间")
        return v

    @field_validator("rag_chunk_overlap_ratio")
    @classmethod
    def _validate_overlap_ratio(cls, v: float) -> float:
        """重叠比例越界校验（spec §5.6.3: [0.10, 0.20]，越界 → 422）。"""
        if not 0.10 <= v <= 0.20:
            raise ValueError("rag_chunk_overlap_ratio 必须在 0.10-0.20 之间")
        return v

    @field_validator("kg_extract_interval_hours")
    @classmethod
    def _validate_kg_interval(cls, v: int) -> int:
        """知识图谱定时提取间隔越界校验（spec f48 §5.5.2: 1-168 小时）。"""
        if not 1 <= v <= 168:
            raise ValueError("kg_extract_interval_hours 必须在 1-168 之间")
        return v


class AppSettingsUpdate(BaseModel):
    """PATCH /settings 请求 DTO — 全字段可选（部分更新语义）。

    extra='forbid'：未知字段直接 422（#105 教训：extra='ignore' 静默吞掉
    前端拼写错误，接口无感知——设置接口是高频手写路径，必须显式报错）。
    空 body（无任何字段）→ 路由层 422「至少提供一个设置字段」。
    """

    model_config = {"extra": "forbid"}

    theme: ThemeName | None = None
    bg: ThemeBg | None = None
    lang: Lang | None = None
    font: FontKey | None = None
    close_behavior: CloseBehavior | None = None
    tray_hint_dismissed: bool | None = None
    default_words: int | None = None
    agent_max_steps: int | None = None
    agent_token_budget: int | None = None
    agent_max_total_tool_calls: int | None = None
    rag_chunk_mode: ChunkMode | None = None
    rag_chunk_size: int | None = None
    rag_chunk_overlap: bool | None = None
    rag_chunk_overlap_ratio: float | None = None
    kg_extract_enabled: bool | None = None
    kg_extract_interval_hours: int | None = None
    kg_extract_method: Literal["rule", "ai", "both"] | None = None

    @field_validator("rag_chunk_size")
    @classmethod
    def _validate_update_chunk_size(cls, v: int | None) -> int | None:
        """更新 DTO 切片大小越界校验（None 放行——部分更新语义）。"""
        if v is not None and not 100 <= v <= 2000:
            raise ValueError("rag_chunk_size 必须在 100-2000 之间")
        return v

    @field_validator("rag_chunk_overlap_ratio")
    @classmethod
    def _validate_update_overlap_ratio(cls, v: float | None) -> float | None:
        """更新 DTO 重叠比例越界校验（None 放行——部分更新语义）。"""
        if v is not None and not 0.10 <= v <= 0.20:
            raise ValueError("rag_chunk_overlap_ratio 必须在 0.10-0.20 之间")
        return v

    @field_validator("kg_extract_interval_hours")
    @classmethod
    def _validate_update_kg_interval(cls, v: int | None) -> int | None:
        """更新 DTO 提取间隔越界校验（None 放行——部分更新语义）。"""
        if v is not None and not 1 <= v <= 168:
            raise ValueError("kg_extract_interval_hours 必须在 1-168 之间")
        return v
