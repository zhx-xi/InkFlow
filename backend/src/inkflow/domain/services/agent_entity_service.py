"""Agent 实体业务服务 — 自定义 Agent CRUD + 同名查重 + tool/skill 白名单校验.

职责（spec §2.1/§3.3/§5.6/§7）:
- CRUD 编排：委托 AgentRepositoryProtocol / SkillRepositoryProtocol
- 同名唯一性校验（422）：create 前 / update 改名时经 agent_repository.get_by_name
  检查，命中 → AgentNameConflictError
- 工具白名单校验（422）：tool_ids 逐个对照工具目录 TOOL_REGISTRY（工具名唯一
  真源，spec §6），目录外 → ToolReferenceError
- skill 引用校验（422）：skill_ids 逐个 skill_repository.get(int(skill_id))，
  任一缺失 → SkillReferenceError
- 资源不存在（404 语义）：get/update/delete 目标缺失 → AgentNotFoundError
- update 为 exclude_unset 浅合并（同 F1/F13）：None 值 = 不修改，予以剔除；
  仅 name 变更时查重；updated_at 刷新为 now(UTC)，created_at 保留
- delete：builtin=True（内置只读）→ AgentBuiltinError（409）；repo.delete
  返回 False（竞态已删）→ NotFound
- 时间戳契约：create/update 填充 created_at/updated_at 为 datetime.now(UTC)
  （时区感知）；id 由 repo 分配（构造 None），builtin 服务层固定 False

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）；TOOL_REGISTRY 为静态
工具目录常量，按测试 docstring 契约在服务内部 import 校验。
"""

from __future__ import annotations

import builtins
import logging
from datetime import UTC, datetime
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.agent import Agent, AgentCreate, AgentUpdate
from inkflow.domain.ports.agent_errors import (
    AgentBuiltinError,
    AgentNameConflictError,
    AgentNotFoundError,
    SkillReferenceError,
    ToolReferenceError,
)
from inkflow.domain.ports.agent_repository import AgentRepositoryProtocol
from inkflow.domain.ports.skill_repository import SkillRepositoryProtocol
from inkflow.domain.services.skill_service import BUILTIN_SKILL_NAMES
from inkflow.infrastructure.agent.tools import TOOL_REGISTRY
from inkflow.infrastructure.database.repositories.agent_repo import (
    SQLiteAgentRepository,
)
from inkflow.infrastructure.database.repositories.skill_repo import (
    SQLiteSkillRepository,
)

logger = logging.getLogger(__name__)


class _BuiltinAgentSpec(TypedDict):
    """内置 Agent 出厂配置项（spec §5.3）.

    内置链角色键映射（#473 R1）：架构师=architect 等；非链内置 None。
    """

    name: str
    description: str
    icon: str
    system_prompt: str
    tool_ids: list[str]
    skill_name: str
    role_key: str | None


BUILTIN_AGENT_SPECS: list[_BuiltinAgentSpec] = [
    {
        "name": "架构师",
        "description": "章节结构/大纲规划",
        "icon": "🏗️",
        "system_prompt": "你是架构师，负责章节结构与大纲规划。",
        "tool_ids": ["search_characters", "check_foreshadowing", "get_prior_summary"],
        "skill_name": "架构方法论",
        "role_key": "architect",
    },
    {
        "name": "写手",
        "description": "正文生成",
        "icon": "✍️",
        "system_prompt": "你是写手，负责按大纲撰写正文，完成章节后用 save_draft 保存草稿。",
        "tool_ids": [
            "search_characters",
            "check_foreshadowing",
            "get_prior_summary",
            "save_draft",
        ],
        "skill_name": "写作方法论",
        "role_key": "writer",
    },
    {
        "name": "审校员",
        "description": "一致性审计",
        "icon": "🔍",
        "system_prompt": "你是审校员，负责对章节进行一致性审计，输出 findings。",
        "tool_ids": ["audit_chapter", "count_words", "search_characters"],
        "skill_name": "审校方法论",
        "role_key": "auditor",
    },
    {
        "name": "修订师",
        "description": "修订打磨",
        "icon": "🛠️",
        "system_prompt": "你是修订师，负责在前文基础上修订打磨章节，完成后保存草稿。",
        "tool_ids": ["get_prior_summary", "count_words", "save_draft"],
        "skill_name": "修订方法论",
        "role_key": "reviser",
    },
    {
        "name": "世界观顾问",
        "description": "世界观一致",
        "icon": "🌍",
        "system_prompt": "你是世界观顾问，负责校验角色与伏笔的世界观一致性。",
        "tool_ids": ["search_characters", "check_foreshadowing"],
        "skill_name": "世界观方法论",
        "role_key": None,
    },
    {
        "name": "润色师",
        "description": "文笔润色",
        "icon": "✨",
        "system_prompt": "你是润色师，负责在前文基础上润色文笔。",
        "tool_ids": ["count_words", "get_prior_summary"],
        "skill_name": "润色方法论",
        "role_key": None,
    },
]
"""内置 6 Agent 出厂配置（spec §5.3 出厂表，builtin=True 只读）."""


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _validate_tool_ids(tool_ids: list[str]) -> None:
    """工具白名单校验：含目录外工具名 → ToolReferenceError（422）."""
    registry_names = {spec.name for spec in TOOL_REGISTRY}
    unknown = [tool_id for tool_id in tool_ids if tool_id not in registry_names]
    if unknown:
        raise ToolReferenceError()


class AgentEntityService:
    """Agent 实体业务服务 — CRUD + 同名查重 + tool/skill 白名单校验.

    Args:
        agent_repository: Agent 仓储端口.
        skill_repository: Skill 仓储端口（skill_ids 白名单校验查询用）.
    """

    def __init__(
        self,
        *,
        agent_repository: AgentRepositoryProtocol,
        skill_repository: SkillRepositoryProtocol,
    ) -> None:
        self._agent_repo = agent_repository
        self._skill_repo = skill_repository

    async def create(self, data: AgentCreate) -> Agent:
        """创建自定义 Agent（同名冲突 → 422；tool/skill 白名单校验）.

        查重未命中 → 白名单全过 → 构造实体（id=None、builtin=False、时间戳
        填充为 now(UTC)）→ 委托 repo.add。
        """
        existing = await self._agent_repo.get_by_name(data.name)
        if existing is not None:
            raise AgentNameConflictError()
        _validate_tool_ids(data.tool_ids)
        await self._validate_skill_ids(data.skill_ids)
        now = _utcnow()
        entity = Agent(
            id=None,
            name=data.name,
            description=data.description,
            icon=data.icon,
            system_prompt=data.system_prompt,
            tool_ids=list(data.tool_ids),
            skill_ids=list(data.skill_ids),
            model_override=data.model_override,
            temperature_override=data.temperature_override,
            builtin=False,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建 Agent: name=%s", data.name)
        return await self._agent_repo.add(entity)

    async def get(self, agent_id: int) -> Agent:
        """按主键获取 Agent；不存在 → AgentNotFoundError（404）."""
        agent = await self._agent_repo.get(agent_id)
        if agent is None:
            raise AgentNotFoundError()
        return agent

    async def list(self) -> builtins.list[Agent]:
        """列出全部 Agent（按 name 升序，委托 repo）."""
        return await self._agent_repo.list()

    async def update(self, agent_id: int, data: AgentUpdate) -> Agent:
        """部分更新 Agent（exclude_unset 浅合并，同 F1/F13）.

        None 值 = 不修改（与未传入等价，合并前剔除）；仅 name 变更时查重
        （命中其他 id → 422）；tool_ids/skill_ids 白名单校验仅针对本次传入
        字段；updated_at 刷新为 now(UTC)，created_at 保留。
        """
        existing = await self._agent_repo.get(agent_id)
        if existing is None:
            raise AgentNotFoundError()
        if existing.builtin:
            raise AgentBuiltinError()
        updates = {
            k: getattr(data, k) for k in data.model_fields_set if getattr(data, k) is not None
        }
        if "name" in updates and updates["name"] != existing.name:
            dup = await self._agent_repo.get_by_name(updates["name"])
            if dup is not None and dup.id != existing.id:
                raise AgentNameConflictError()
        if "tool_ids" in updates:
            _validate_tool_ids(updates["tool_ids"])
        if "skill_ids" in updates:
            await self._validate_skill_ids(updates["skill_ids"])
        merged = existing.model_copy(update=updates)
        merged.updated_at = _utcnow()
        logger.info("更新 Agent: agent_id=%s", agent_id)
        result = await self._agent_repo.update(merged)  # type: ignore[call-arg, arg-type]  # 测试 docstring 契约：update 以实体单参调用（G2 repo 签名待父侧对齐）
        if result is None:
            raise AgentNotFoundError()
        return result

    async def delete(self, agent_id: int) -> None:
        """删除自定义 Agent（内置只读 → 409；repo.delete False → NotFound）."""
        existing = await self._agent_repo.get(agent_id)
        if existing is None:
            raise AgentNotFoundError()
        if existing.builtin:
            raise AgentBuiltinError()
        if not await self._agent_repo.delete(agent_id):
            raise AgentNotFoundError()
        logger.info("删除 Agent: agent_id=%s", agent_id)

    async def _validate_skill_ids(self, skill_ids: builtins.list[str]) -> None:
        """skill 引用校验：任一 skill id 不存在 → SkillReferenceError（422）."""
        for skill_id in skill_ids:
            skill = await self._skill_repo.get(int(skill_id))
            if skill is None:
                raise SkillReferenceError()


async def seed_builtin_agents(session: AsyncSession) -> int:
    """幂等 seed 内置 6 Agent（spec §5.3 出厂表，builtin=True 只读）.

    镜像 seed_builtin_providers 幂等模式：按 name 判重，同名跳过，重复启动
    不重复插入；返回本次实际插入条数。skill_ids 指向对应出厂 Skill（按 skill
    名解析主键字符串化）；出厂 skill 尚未 seed 时按出厂列表序预测主键——
    fresh DB 下 skills 表自增 id 与 seed_builtin_skills 插入序一一对应，
    与调用顺序（agents 先 / skills 先）无关。
    """
    # seed 契约（test_builtin_seed.py）固定本函数位置 + session 显式注入；
    # 此处按既有模块内 infra import 先例（TOOL_REGISTRY）构造 SQLite 仓储。
    agent_repo = SQLiteAgentRepository(session)
    skill_repo = SQLiteSkillRepository(session)
    inserted = 0
    for spec in BUILTIN_AGENT_SPECS:
        name = spec["name"]
        if await agent_repo.get_by_name(name) is not None:
            continue
        skill_name = spec["skill_name"]
        skill = await skill_repo.get_by_name(skill_name)
        skill_id = (
            str(skill.id) if skill is not None else str(BUILTIN_SKILL_NAMES.index(skill_name) + 1)
        )
        await agent_repo.add(
            Agent(
                id=None,
                name=name,
                description=spec["description"],
                icon=spec["icon"],
                system_prompt=spec["system_prompt"],
                tool_ids=list(spec["tool_ids"]),
                skill_ids=[skill_id],
                builtin=True,
            )
        )
        inserted += 1
    return inserted
