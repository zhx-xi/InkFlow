"""F48 知识图谱领域模型 — 关系实体 + 图谱查询 DTO.

KnowledgeRelation 是持久化实体（对应 knowledge_relations 表，通过 SQLAlchemy
ORM 映射），KnowledgeRelationCreate / KnowledgeRelationUpdate 是请求 DTO，
GraphNode / GraphEdge / KnowledgeGraphView 是图谱聚合查询的响应模型。

依据: specs/f48-knowledge-graph/spec.md §2.3/§2.4。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, field_validator


class EntityType(StrEnum):
    """图谱实体类型枚举 — 六类设定实体（与 library.tsx 六分类 tab 对齐，rag 除外）."""

    CHARACTER = "character"
    WORLD = "world"
    OUTLINE = "outline"
    TIMELINE = "timeline"
    FORESHADOW = "foreshadow"
    MAP_PIN = "map_pin"


class RelationSource(StrEnum):
    """关系来源 — v1.0 手动创建恒 manual；ai 值预留给 #479 定时提取."""

    MANUAL = "manual"
    AI = "ai"  # 预留（#479），v1.0 不产生 ai 行


class KnowledgeRelation(BaseModel):
    """图谱关系领域实体 — 对应 knowledge_relations 表（有向边）.

    Attributes:
        id: 主键 UUID.
        project_id: 所属项目 UUID.
        source_type: 起点实体类型（EntityType）.
        source_id: 起点实体 UUID.
        target_type: 终点实体类型（EntityType）.
        target_id: 终点实体 UUID.
        relation_type: 关系类型（1-20 字符，去空白，自由文本）.
        description: 关系说明（≤ 500 字符）.
        source: 关系来源（manual/ai，v1.0 恒 manual）.
        created_at: 创建时间.
        updated_at: 最后更新时间.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    source_type: EntityType
    source_id: uuid.UUID
    target_type: EntityType
    target_id: uuid.UUID
    relation_type: str
    description: str = ""
    source: RelationSource = RelationSource.MANUAL
    created_at: datetime
    updated_at: datetime


class KnowledgeRelationCreate(BaseModel):
    """创建图谱关系请求 DTO — 六元组必填 + 可选描述.

    Attributes:
        source_type: 起点实体类型，必填.
        source_id: 起点实体 UUID，必填.
        target_type: 终点实体类型，必填.
        target_id: 终点实体 UUID，必填.
        relation_type: 关系类型，必填，1-20 字符，去空白.
        description: 关系说明，可选，≤ 500 字符.
    """

    source_type: EntityType
    source_id: uuid.UUID
    target_type: EntityType
    target_id: uuid.UUID
    relation_type: str
    description: str = ""

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        """校验关系类型：去空白后非空且不超过 20 字符."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("关系类型不能为空")
        if len(stripped) > 20:
            raise ValueError("关系类型不能超过 20 个字符")
        return stripped

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """校验关系说明：不超过 500 字符（空串合法）."""
        if len(v) > 500:
            raise ValueError("关系说明不能超过 500 个字符")
        return v


class KnowledgeRelationUpdate(BaseModel):
    """更新图谱关系请求 DTO — 全可选，exclude_unset 语义（同 F1）.

    说明: 关系键（六元组）允许修改（改终点/改类型）；description 传空串 = 清空.
    """

    source_type: EntityType | None = None
    source_id: uuid.UUID | None = None
    target_type: EntityType | None = None
    target_id: uuid.UUID | None = None
    relation_type: str | None = None
    description: str | None = None


class GraphNode(BaseModel):
    """图谱节点 — 六类实体统一视图.

    Attributes:
        id: 节点 ID，f"<entity_type>:<entity_uuid>"，跨表唯一（图谱边引用键）.
        type: 实体类型（EntityType）.
        entity_id: 实体 UUID（源实体表主键）.
        name: 节点显示名（实体 name/title/label 按表映射，§2.2）.
    """

    id: str  # f"{entity_type}:{entity_id}"
    type: EntityType
    entity_id: uuid.UUID
    name: str


class GraphEdge(BaseModel):
    """图谱边 — knowledge_relations + character_relations 合并去重后视图.

    Attributes:
        id: 边 ID，f"kr:<relation_uuid>" 或 "cr:<relation_uuid>"（来源区分）.
        source: 起点节点 ID（GraphNode.id 格式）.
        target: 终点节点 ID.
        label: 关系类型（relation_type）.
        description: 关系说明.
        source_table: "knowledge_relations" | "character_relations"（合并来源）.
    """

    id: str
    source: str
    target: str
    label: str
    description: str = ""
    source_table: str


class KnowledgeGraphView(BaseModel):
    """图谱聚合响应 — GET /projects/{pid}/knowledge-graph."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
