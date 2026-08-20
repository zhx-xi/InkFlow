"""
项目/书籍领域模型 — 定义核心领域实体与数据传输对象.

Genre 枚举包含 11 种中文网络小说分类，
ProjectConfig 管理各项目的独立 AI 写作配置，
Project 是持久化实体，ProjectCreate/ProjectUpdate 是请求 DTO。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 225 拍板——字符串 "__default__" = 跟随默认（预留 sentinel，前端本期不暴露中间态 UI）。
AGENT_DEFAULT_SENTINEL = "__default__"


class Genre(StrEnum):
    """中文网络小说分类枚举."""

    XUANHUAN = "玄幻"
    KEHUAN = "科幻"
    YANQING = "言情"
    XIANXIA = "仙侠"
    WUXIA = "武侠"
    DUSHI = "都市"
    LISHI = "历史"
    YOUXI = "游戏"
    XUANYI = "悬疑"
    QIHUAN = "奇幻"
    QITA = "其他"


class AgentRelation(BaseModel):
    """角色间有向边（#270，spec §1.2.1 依赖类型语义）。"""

    # serialize_by_alias=True：契约 test_roundtrip_model_dump 要求
    # ProjectConfig.model_dump() 中 agent_relations 输出 "from" 键（spec §2.1 别名口径）
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    from_: str = Field(alias="from", description="源角色字段名（带 agent_ 前缀，如 agent_auditor）")
    to: str = Field(description="目标角色字段名（带 agent_ 前缀，如 agent_reviser）")
    type: Literal["sequential", "data", "conditional"] = Field(
        default="sequential",
        description="依赖类型：sequential=顺序依赖 / data=数据传递 / conditional=条件分支",
    )

    @field_validator("from_", "to")
    @classmethod
    def _validate_role_ref(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("agent_relations 的 from/to 不能为空")
        return stripped

    @field_validator("type", mode="before")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        # mode="before"：先于 Literal 校验触发，保证契约报错消息
        # 「agent_relations 类型非法: xxx」出现（after 模式会被 literal_error 抢先）
        if v not in ("sequential", "data", "conditional"):
            raise ValueError(f"agent_relations 类型非法: {v}（应为 sequential/data/conditional）")
        return v


class SupervisorProjectConfig(BaseModel):
    """项目级 Supervisor/HITL 配置（#343 拍板 2A）。

    Attributes:
        hitl_roles: HITL 确认角色列表（这些角色执行前 interrupt 等待人工确认；
            空列表 = 不启用 HITL，supervisor 模式仍可用但无确认点）。
    """

    hitl_roles: list[str] = Field(default_factory=list)


class ProjectConfig(BaseModel):
    """项目 AI 写作配置，可序列化为 JSON 进行导入/导出.

    Attributes:
        model: 默认 AI 模型名称（None=未配置，装配时回退全局默认）.
        agent_architect: 架构师 Agent 模型（None=关闭；字符串=指定模型；"__default__"=跟随默认）.
        agent_writer: 写手 Agent 模型（None=关闭；字符串=指定模型；"__default__"=跟随默认）.
        agent_auditor: 审阅 Agent 模型（None=关闭；字符串=指定模型；"__default__"=跟随默认）.
        agent_reviser: 修订 Agent 模型（None=关闭；字符串=指定模型；"__default__"=跟随默认）.
        agent_worldview: 世界观顾问 Agent 模型（v1.5 #484；None=关闭；字符串=指定模型；
            "__default__"=跟随默认）.
        agent_polisher: 润色师 Agent 模型（v1.5 #484；None=关闭；字符串=指定模型；
            "__default__"=跟随默认）.
        agent_roles: 自定义角色三态字段（key 带 agent_ 前缀，value 三态语义
            与 agent_* 完全一致；spec §5.3.4 数据面）.
        temperature: 生成温度 (0.0 - 2.0).
        role_architect_temperature: 架构师角色独立温度（None = 跟随默认）.
        role_writer_temperature: 写手角色独立温度（None = 跟随默认）.
        role_auditor_temperature: 审阅角色独立温度（None = 跟随默认）.
        role_reviser_temperature: 修订角色独立温度（None = 跟随默认）.
        template_id: 引用的 AgentTemplate id（str 存储于 config JSON；
            None = 未引用，回退默认装配，spec §9.2）.
        writing_style: 写作风格描述.
        supervisor: 项目级 Supervisor/HITL 配置（None = 未启用，零迁移）.
        extra: 扩展配置字典.
    """

    model: str | None = Field(
        default=None, description="默认 AI 模型（None=未配置，装配时回退全局默认）"
    )
    agent_architect: str | None = None
    agent_writer: str | None = None
    agent_auditor: str | None = None
    agent_reviser: str | None = None
    agent_worldview: str | None = None
    """世界观顾问 Agent 模型（v1.5 #484，spec §5.7.1；None=关闭 / "__default__"=跟随默认 /
    字符串=指定模型，与内置 4 角色同三态语义）."""
    agent_polisher: str | None = None
    """润色师 Agent 模型（v1.5 #484，spec §5.7.1；None=关闭 / "__default__"=跟随默认 /
    字符串=指定模型，与内置 4 角色同三态语义）."""
    agent_roles: dict[str, str | None] = Field(default_factory=dict)
    """自定义角色三态字段（F42 #295，spec §5.3.4 数据面第 2 点）.

    key 为带 agent_ 前缀的角色字段名（如 agent_researcher），value 三态语义
    与 agent_* 完全对齐：None=关闭 / "__default__"=跟随默认 /
    "<provider>/<model>"=指定模型。零迁移：旧 config JSON 无键 → 默认空 dict。
    """
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    role_architect_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    role_writer_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    role_auditor_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    role_reviser_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    template_id: str | None = None
    writing_style: str = ""
    default_words: int = Field(default=800000, ge=1000, le=10_000_000, description="新章节默认字数")
    extra: dict[str, Any] = Field(default_factory=dict)
    agent_order: list[list[str]] = Field(default_factory=list)
    """Agent 链执行拓扑 — 层级嵌套数组（v1.1 拍板：同层并行；v1.2 拍板：槽位编号 0-9）。

    - 外层索引 = 槽位编号 0-9（共 10 个数字，v1.2 拍板）——索引 0 先执行，逐层串行
    - 内层 = 同槽位（同编号）并行角色字段名数组（agent_architect 等，带 agent_ 前缀）
    - 示例: [["agent_architect"], ["agent_writer", "agent_auditor"], ["agent_reviser"]]
            = 槽位 0 架构规划 → 槽位 1 写作+审阅并行 → 槽位 2 修订
    - 默认模板 = 槽位 0-3（architect=0/writer=1/auditor=2/reviser=3）；槽位 4-9 预留自定义 Agent
    - 空层（[]）= 空槽（该编号无角色，跳过）——允许跳号
    - 长度上限 10（编号 0-9）；空列表 = 未配置 → 默认模板拓扑
    - 双模式（v1.3 B1）：空列表 = 默认模板模式——agent_* null 不触发真禁用（跟随模板）；
      非空 = 配置驱动模式——null 真禁用（跳过，§2.2）
    - 角色名支持任意字符串（自定义 Agent，v1.2 执行解锁 + v1.3 数据面）
    """
    supervisor: SupervisorProjectConfig | None = Field(
        default=None,
        description="Supervisor/HITL 项目级配置（None = 未启用，零迁移）",
    )
    agent_relations: list[AgentRelation] = Field(default_factory=list)
    """角色间显式关联关系（#270，spec §1.2）。

    - 空列表 = 未配置 → 纯 agent_order 基线（现状零迁移，§1.2.3 线性兼容）
    - 非空 = 在基线 DAG 上叠加显式边（关系优先，§5.3.1）
    - 示例: [{"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"}]
            = reviser 在 auditor 通过后才执行
    """

    @field_validator(
        "agent_architect",
        "agent_writer",
        "agent_auditor",
        "agent_reviser",
        "agent_worldview",
        "agent_polisher",
    )
    @classmethod
    def validate_agent_model(cls, v: str | None) -> str | None:
        """agent_* 三态语义校验（#225）：None=关闭；"__default__"=跟随默认；字符串必须非空。"""
        if v is None or v == AGENT_DEFAULT_SENTINEL:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("Agent 模型不能为空字符串")
        return stripped

    @field_validator("agent_roles")
    @classmethod
    def validate_agent_roles(cls, v: dict[str, str | None]) -> dict[str, str | None]:
        """agent_roles 三态语义校验（F42 #295，spec §5.3.4 数据面第 2 点）.

        与 validate_agent_model 完全对齐：None=关闭；"__default__"=跟随默认；
        字符串 strip 后必须非空（空串 ValueError「Agent 模型不能为空字符串」）。
        """
        result: dict[str, str | None] = {}
        for key, value in v.items():
            if value is None or value == AGENT_DEFAULT_SENTINEL:
                result[key] = value
                continue
            stripped = value.strip()
            if not stripped:
                raise ValueError("Agent 模型不能为空字符串")
            result[key] = stripped
        return result

    @field_validator("agent_order", mode="before")
    @classmethod
    def validate_agent_order(cls, v: Any) -> list[list[str]]:
        """存储层校验（spec §2.1）：结构 + 去重 + 长度上限。

        - 长度 ≤ 10（槽位编号 0-9）
        - 每层必须为数组；空层（[]）= 空槽，允许
        - 元素必须为非空字符串（strip 后判空）；跨层全局去重（防歧义）
        - 返回 strip 规范化后的新列表；空列表原样返回（默认模板模式）
        """
        # 契约固定 ValueError（TRY004 建议 TypeError，测试断言 ValueError 消息）
        if not isinstance(v, list):
            raise ValueError("agent_order 每层必须为数组")  # noqa: TRY004  # 契约固定 ValueError（测试断言消息）
        if len(v) > 10:
            raise ValueError("agent_order 最多 10 层（槽位编号 0-9）")
        seen: set[str] = set()
        result: list[list[str]] = []
        for layer in v:
            if not isinstance(layer, list):
                raise ValueError("agent_order 每层必须为数组")  # noqa: TRY004  # 契约固定 ValueError（测试断言消息）
            layer_items: list[str] = []
            for item in layer:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError("agent_order 元素必须为非空字符串")
                stripped = item.strip()
                if stripped in seen:
                    raise ValueError(f"agent_order 角色重复: {stripped}")
                seen.add(stripped)
                layer_items.append(stripped)
            result.append(layer_items)
        return result

    @field_validator("agent_relations", mode="before")
    @classmethod
    def validate_agent_relations(cls, v: Any) -> list[AgentRelation]:
        """存储层校验（spec §2.3）：结构 + 自环 + 重复边 + 类型（类型/非空在
        AgentRelation 内校验）。"""
        if not isinstance(v, list):
            raise ValueError("agent_relations 必须为数组")  # noqa: TRY004  # 契约固定 ValueError（测试断言消息）
        relations: list[AgentRelation] = []
        seen: set[tuple[str, str]] = set()
        for item in v:
            rel = item if isinstance(item, AgentRelation) else AgentRelation.model_validate(item)
            key = (rel.from_, rel.to)
            if rel.from_ == rel.to:
                raise ValueError(f"agent_relations 自环非法: {rel.from_}")
            if key in seen:
                raise ValueError(f"agent_relations 重复边: {rel.from_} -> {rel.to}")
            seen.add(key)
            relations.append(rel)
        return relations


class Project(BaseModel):
    """项目/书籍领域实体.

    对应数据库中的 projects 表，通过 SQLAlchemy ORM 映射持久化。

    Attributes:
        id: 主键 UUID.
        name: 项目名称.
        genre: 小说分类.
        language: 写作语言（默认为 zh-CN）.
        target_words: 目标字数.
        config: AI 写作配置.
        is_deleted: 软删除标记.
        created_at: 创建时间.
        updated_at: 最后更新时间.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    genre: Genre = Genre.QITA
    language: str = "zh-CN"
    target_words: int = 0
    config: ProjectConfig = Field(default_factory=ProjectConfig)
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    """创建项目请求 DTO.

    Attributes:
        name: 项目名称，必填，1-100 字符，不能为空白.
        genre: 小说分类 默认为“其他”.
        language: 写作语言，默认为 zh-CN.
        target_words: 目标字数，默认为 0（不限）.
        config: AI 写作配置.
        template_id: 新建项目引用的 AgentTemplate id（None = 默认模板）.
    """

    name: str
    genre: Genre = Genre.QITA
    language: str = "zh-CN"
    target_words: int = 0
    config: ProjectConfig = Field(default_factory=ProjectConfig)
    template_id: int | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证项目名称：去除前后空白后不能为空，长度 1-100 字符."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("项目名称不能为空")
        if len(stripped) > 100:
            raise ValueError("项目名称不能超过 100 个字符")
        return stripped


class ProjectUpdate(BaseModel):
    """更新项目请求 DTO — 所有字段均为可选项.

    只有传入的字段会被更新，未传入的字段保持不变.
    """

    name: str | None = None
    genre: Genre | None = None
    language: str | None = None
    target_words: int | None = None
    config: ProjectConfig | None = None
    is_deleted: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """验证项目名称：如果提供了值，去除空白后不能为空且不超过 100 字符."""
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("项目名称不能为空")
        if len(stripped) > 100:
            raise ValueError("项目名称不能超过 100 个字符")
        return stripped
