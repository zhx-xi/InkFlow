"""F22 全文搜索领域 DTO 模型 —— 纯 Pydantic 校验，无 I/O.

SearchMode / SearchEntityType 枚举、SearchQuery 请求校验（空白拒绝、types=[]
归一为 None、limit/offset 边界）、SearchHit 命中和 SearchResponse 响应封装，
对应 specs/f22-search/spec.md §2.1/§2.2/§6.3。
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class SearchMode(StrEnum):
    """检索模式（spec §2.2：keyword 词法默认，semantic AI 语义增强）。"""

    KEYWORD = "keyword"
    SEMANTIC = "semantic"


class SearchEntityType(StrEnum):
    """可搜索内容类型（spec §2.1，与 F21 附件类型集对齐）。"""

    CHAPTER = "chapter"
    CHARACTER = "character"
    WORLD = "world"
    OUTLINE = "outline"
    TIMELINE = "timeline"
    FORESHADOWING = "foreshadowing"


class SearchQuery(BaseModel):
    """查询参数（spec §2.2：API query / CLI 选项统一语义）。"""

    q: str = Field(min_length=1, max_length=100)
    project_ids: list[uuid.UUID]
    types: list[SearchEntityType] | None = None
    mode: SearchMode = SearchMode.KEYWORD
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("q")
    @classmethod
    def _reject_blank_query(cls, v: str) -> str:
        """strip 后全空白拒绝（spec §3.3：q 空白 → 422）。"""
        if not v.strip():
            raise ValueError("q must not be blank after strip")
        return v

    @field_validator("types")
    @classmethod
    def _normalize_empty_types(
        cls, v: list[SearchEntityType] | None
    ) -> list[SearchEntityType] | None:
        """types=[] 归一为 None（spec §6.3：客户端省略参数的自然形态）。"""
        if v == []:
            return None
        return v


class SearchHit(BaseModel):
    """单条命中（spec §2.2）。"""

    entity_type: SearchEntityType
    entity_id: uuid.UUID
    project_id: uuid.UUID
    title: str
    snippet: str
    score: float = 0.0


class SearchResponse(BaseModel):
    """搜索结果响应（spec §2.2：query/types/mode/project_ids 回显）。"""

    total: int
    hits: list[SearchHit]
    query: str
    types: list[SearchEntityType] | None
    mode: SearchMode
    project_ids: list[uuid.UUID]
