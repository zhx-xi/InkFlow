"""Skill 领域模型 — Skill 实体与请求 DTO.

Skill 是持久化实体（对应 skills 表，通过 SQLAlchemy ORM 映射），存储
完整 SKILL.md（frontmatter + markdown 正文，原样），name/description 为
frontmatter 解析的去冗余索引列（列表展示 + 唯一性校验用）。SkillCreate
仅含 content（name/description 由后端解析 frontmatter 填充），
SkillUpdate 全字段可选（exclude_unset 语义，同 F1/F13）。

依据: specs/f39-multi-agent/spec.md §2.2。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Skill(BaseModel):
    """Skill 实体（§2.2 字段全集）.

    Attributes:
        id: 主键（None = 未落库；repo.add 后 DB 自增分配）.
        name: skill 名（唯一，frontmatter name 提取）.
        description: 描述（frontmatter description 提取）.
        content: 完整 SKILL.md 内容（frontmatter + markdown 正文，原样存储）.
        source: 来源（"builtin" | "user_upload"）.
        created_at: 创建时间 (UTC)（服务层落库时填充）.
        updated_at: 最后更新时间 (UTC).
    """

    model_config = {"from_attributes": True}

    id: int | None = None
    name: str
    description: str = ""
    content: str = ""
    source: str = "user_upload"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkillCreate(BaseModel):
    """创建 Skill 请求 DTO — 仅 content 必填.

    name/description 不是 DTO 字段：由服务层解析 content 的 frontmatter
    提取（缺失或 name 格式非法 → SkillFrontmatterError）；id/source/
    时间戳字段服务层填充（source 固定 "user_upload"）。
    """

    content: str


class SkillUpdate(BaseModel):
    """更新 Skill 请求 DTO — 全字段可选（exclude_unset 语义，同 F1/F13）.

    None 值表示不修改（与未传入等价，服务层合并时剔除）；content 更新
    是否重解析 frontmatter 由服务层决定。
    """

    name: str | None = None
    description: str | None = None
    content: str | None = None
