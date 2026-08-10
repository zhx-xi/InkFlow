"""AppSettings 领域模型 — 应用级设置（全局用户偏好，settings 表承载）。

依据: specs/f32-settings-persistence/spec.md §2。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

ThemeName = Literal["paper", "night", "ink"]
ThemeBg = Literal["default", "parchment", "navy", "ochre"]
Lang = Literal["zh", "en"]
FontKey = Literal["serif", "sans", "mono"]
CloseBehavior = Literal["tray", "quit"]


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
    AGENT_MAX_CONSECUTIVE_TOOL = "agent_max_consecutive_tool"


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
    agent_max_consecutive_tool: int = 3


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
    agent_max_consecutive_tool: int | None = None
