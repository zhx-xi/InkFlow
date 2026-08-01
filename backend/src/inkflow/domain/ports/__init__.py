"""出站端口接口（Protocol 定义） — 基础设施层实现这些接口。

依赖方向：Domain → Port (Protocol) ← Infrastructure
领域层定义契约，基础设施层提供实现。测试时可注入 Mock。

端口列表：
    - project_repository: 项目仓储（F1，已实现）
    - llm_client: LLM 客户端（F5，LangChain ChatLiteLLM 实现）
    - agent_pipeline: Agent 管线编排（F4，LangGraph StateGraph 实现）
    - vector_store: RAG 向量存储（Phase 2，LangChain Chroma 实现）
    - prompt_template: Prompt 模板管理（LangChain ChatPromptTemplate 实现）
    - llm_errors: LLM 领域异常类型
    - context_sources: 上下文数据源（F6，Phase 1 部分空实现）
    - context_errors: 上下文管理异常（F6）
    - summary_repository: 前文摘要缓存仓储（F6）
    - character_repository: 角色/分组/关系仓储（F9）
    - character_errors: 角色管理异常（F9）
    - outline_repository: 大纲/情节点/弧线仓储（F11）
    - outline_errors: 大纲管理异常（F11）
    - timeline_errors: 时间线管理异常（F12）
"""

from inkflow.domain.ports.agent_pipeline import (
    AgentPipelineProtocol,
    AgentRole,
    PipelineContext,
    PipelineError,
    PipelineResult,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.ports.character_errors import (
    CharacterExtractionError,
    CharacterNameConflictError,
    CharacterNotFoundError,
    CharacterServiceError,
    CrossProjectRelationError,
    GroupNameConflictError,
    GroupNotInProjectError,
    ProjectNotFoundError,
    RelationConflictError,
    SelfRelationError,
)
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.context_errors import (
    ContextBudgetExceededError,
    SummaryGenerationError,
)
from inkflow.domain.ports.context_provider import ContextProviderProtocol
from inkflow.domain.ports.context_sources import ContextSourceProtocol
from inkflow.domain.ports.llm_client import (
    ChatMessage,
    ChatResponse,
    LLMClientProtocol,
    StreamEvent,
    TokenUsage,
)
from inkflow.domain.ports.llm_errors import (
    LLMRequestError,
    TemplateNotFoundError,
    TemplateRenderError,
)
from inkflow.domain.ports.outline_errors import (
    ArcNameConflictError,
    ArcNotInProjectError,
    OutlineGenerationError,
    OutlineNameConflictError,
    OutlineNotFoundError,
    OutlineServiceError,
    PlotPointNotFoundError,
    StoryArcNotFoundError,
)
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.ports.summary_repository import SummaryRepositoryProtocol
from inkflow.domain.ports.timeline_errors import (
    TimelineNotFoundError,
    TimelineServiceError,
)
from inkflow.domain.ports.vector_store import (
    EntityType,
    IndexableEntity,
    RetrievedEntity,
    VectorStoreProtocol,
)
from inkflow.domain.ports.world_errors import (
    WorldExtractionError,
    WorldNameConflictError,
    WorldNotFoundError,
    WorldServiceError,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol

__all__ = [
    # ── context ──
    "ContextProviderProtocol",
    "ContextSourceProtocol",
    "ContextBudgetExceededError",
    "SummaryGenerationError",
    # ── summary ──
    "SummaryRepositoryProtocol",
    # ── character (F9) ──
    "CharacterRepositoryProtocol",
    "CharacterExtractionError",
    "CharacterServiceError",
    "CharacterNotFoundError",
    "ProjectNotFoundError",
    "CharacterNameConflictError",
    "GroupNameConflictError",
    "GroupNotInProjectError",
    "SelfRelationError",
    "CrossProjectRelationError",
    "RelationConflictError",
    # ── project ──
    "ProjectRepositoryProtocol",
    # ── llm ──
    "LLMClientProtocol",
    "ChatMessage",
    "ChatResponse",
    "StreamEvent",
    "TokenUsage",
    # ── llm errors ──
    "LLMRequestError",
    "TemplateNotFoundError",
    "TemplateRenderError",
    # ── agent pipeline ──
    "AgentPipelineProtocol",
    "AgentRole",
    "PipelineContext",
    "PipelineError",
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
    # ── world (F10) ──
    "WorldRepositoryProtocol",
    "WorldExtractionError",
    "WorldServiceError",
    "WorldNotFoundError",
    "WorldNameConflictError",
    # ── outline (F11) ──
    "OutlineRepositoryProtocol",
    "OutlineGenerationError",
    "OutlineServiceError",
    "OutlineNotFoundError",
    "PlotPointNotFoundError",
    "StoryArcNotFoundError",
    "OutlineNameConflictError",
    "ArcNameConflictError",
    "ArcNotInProjectError",
    # ── timeline (F12) ──
    "TimelineServiceError",
    "TimelineNotFoundError",
]
