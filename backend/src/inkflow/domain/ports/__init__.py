"""
出站端口接口（Protocol 定义） — 基础设施层实现这些接口。

依赖方向：Domain → Port (Protocol) ← Infrastructure
领域层定义契约，基础设施层提供实现。测试时可注入 Mock。

端口列表：
    - project_repository: 项目仓储（F1，已实现）
    - llm_client: LLM 客户端（F5，LangChain ChatLiteLLM 实现）
    - agent_pipeline: Agent 管线编排（F4，LangGraph StateGraph 实现）
    - vector_store: RAG 向量存储（Phase 2，LangChain Chroma 实现）
    - prompt_template: Prompt 模板管理（LangChain ChatPromptTemplate 实现）
"""

from inkflow.domain.ports.agent_pipeline import (
    AgentPipelineProtocol,
    AgentRole,
    PipelineContext,
    PipelineResult,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.ports.llm_client import (
    ChatMessage,
    ChatResponse,
    LLMClientProtocol,
    StreamEvent,
    TokenUsage,
)
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.ports.vector_store import (
    EntityType,
    IndexableEntity,
    RetrievedEntity,
    VectorStoreProtocol,
)

__all__ = [
    # ── project ──
    "ProjectRepositoryProtocol",
    # ── llm ──
    "LLMClientProtocol",
    "ChatMessage",
    "ChatResponse",
    "StreamEvent",
    "TokenUsage",
    # ── agent pipeline ──
    "AgentPipelineProtocol",
    "AgentRole",
    "PipelineContext",
    "PipelineResult",
    "PipelineStage",
    "StageResult",
    "StageStatus",
    # ── vector store ──
    "VectorStoreProtocol",
    "EntityType",
    "IndexableEntity",
    "RetrievedEntity",
    # ── prompt template ──
    "PromptTemplateProtocol",
    "PromptTemplate",
    "RenderedPrompt",
]
