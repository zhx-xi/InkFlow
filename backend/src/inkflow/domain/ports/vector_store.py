"""
向量存储端口 — 定义领域层与 RAG 检索引擎之间的契约。

基础设施层（LangChain Chroma + sentence-transformers）实现此 Protocol。
领域层只依赖此接口，不感知 langchain-chroma 或 sentence-transformers。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class EntityType(StrEnum):
    """可被索引的实体类型。"""

    CHARACTER = "character"
    """角色档案。"""

    SETTING = "setting"
    """世界设定（地点、规则、文化等）。"""

    FORESHADOWING = "foreshadowing"
    """伏笔（已埋设/已回收）。"""

    TIMELINE_EVENT = "timeline_event"
    """时间线事件。"""

    CHAPTER_CHUNK = "chapter_chunk"
    """章节文本块（用于语义检索前文内容）。"""


@dataclass
class IndexableEntity:
    """待索引的实体 — 统一数据模型。

    基础设施层负责将其转换为 LangChain Document 并存入 Chroma。
    """

    id: str
    """实体唯一标识。"""

    entity_type: EntityType
    """实体类型。"""

    project_id: str
    """所属项目 ID。"""

    content: str
    """用于生成 embedding 的文本内容（搜索时匹配此字段）。"""

    metadata: dict[str, str | int | float] = field(default_factory=dict)
    """附加元数据（用于 filtering / display）。如 name, chapter_number, status 等。"""


@dataclass
class RetrievedEntity:
    """检索结果 — 从向量库中检索到的实体。

    与 LangChain Document 解耦，领域层不感知框架类型。
    """

    entity_id: str
    """实体 ID。"""

    entity_type: EntityType
    """实体类型。"""

    content: str
    """实体的文本内容。"""

    relevance_score: float
    """语义相似度分数（0-1，越高越相关）。"""

    metadata: dict[str, str | int | float] = field(default_factory=dict)
    """附加元数据。"""


class VectorStoreProtocol(Protocol):
    """向量存储端口 — 实体索引 + 语义检索。

    基础设施层实现示例：
        from langchain_chroma import Chroma
        from langchain_community.embeddings import HuggingFaceBgeEmbeddings
        class LangChainVectorStore: ...

    测试时可注入 Mock 实现（如内存 dict），不依赖真实 Chroma。
    """

    async def index(self, entity: IndexableEntity) -> None:
        """索引一个实体到向量库。

        如果同 ID 实体已存在，则更新（upsert）。

        Args:
            entity: 待索引的实体。
        """
        ...

    async def index_batch(self, entities: list[IndexableEntity]) -> None:
        """批量索引实体。

        Args:
            entities: 待索引的实体列表。
        """
        ...

    async def retrieve(
        self,
        query: str,
        *,
        project_id: str,
        entity_types: list[EntityType] | None = None,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[RetrievedEntity]:
        """语义检索与查询最相关的实体。

        Args:
            query: 查询文本（如当前章节的内容片段）。
            project_id: 限定在指定项目内检索。
            entity_types: 限定实体类型，None 表示检索所有类型。
            top_k: 返回结果数量上限。
            min_score: 最低相关度阈值（0-1），过滤低相关结果。

        Returns:
            按相关度降序排列的检索结果列表。
        """
        ...

    async def delete(self, entity_id: str, entity_type: EntityType) -> None:
        """从向量库中删除指定实体。

        Args:
            entity_id: 实体 ID。
            entity_type: 实体类型。
        """
        ...

    async def delete_project(self, project_id: str) -> int:
        """删除指定项目的所有向量数据。

        Args:
            project_id: 项目 ID。

        Returns:
            删除的实体数量。
        """
        ...
