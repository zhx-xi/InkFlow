"""Agent 实体业务服务 — 自定义 Agent CRUD + 同名查重 + tool/skill 白名单校验.

职责（spec §2.1/§3.3/§5.6/§7 + ADR-039 #522）:
- CRUD 编排：委托 AgentRepositoryProtocol
- 同名唯一性校验（422）：create 前 / update 改名时经 agent_repository.get_by_name
  检查，命中 → AgentNameConflictError
- 工具白名单校验（422，#838）：tool_ids 逐个对照统一目录 ALL_TOOL_SPECS（工具名
  唯一真源，spec §6）；目录外或 allow_custom_agent=False（核心工具，自定义
  agent 不可勾选）→ ToolReferenceError
- skill 引用校验（422，#522 目录名语义）：skill_ids 逐个检查
  skills_root/<name>/SKILL.md 存在（Path.is_file），任一缺失 →
  SkillReferenceError（不再 int() 解析 DB 主键）
- 资源不存在（404 语义）：get/update/delete 目标缺失 → AgentNotFoundError
- update 为 exclude_unset 浅合并（同 F1/F13）：None 值 = 不修改，予以剔除；
  仅 name 变更时查重；updated_at 刷新为 now(UTC)，created_at 保留
- delete：builtin=True（内置只读）→ AgentBuiltinError（409）；repo.delete
  返回 False（竞态已删）→ NotFound
- 时间戳契约：create/update 填充 created_at/updated_at 为 datetime.now(UTC)
  （时区感知）；id 由 repo 分配（构造 None），builtin 服务层固定 False

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）；ALL_TOOL_SPECS 为静态
统一工具目录常量，按测试 docstring 契约在服务内部 import 校验。
"""

from __future__ import annotations

import builtins
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
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
from inkflow.infrastructure.agent.tools import ALL_TOOL_SPECS
from inkflow.infrastructure.database.repositories.agent_repo import (
    SQLiteAgentRepository,
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
        "system_prompt": (
            "你的职责：作为架构师，负责章节结构与大纲规划，先确认目标章节在大纲中的位置与前文弧线。\n"
            "工具使用：规划前获取前文摘要；用 search_characters 核对角色状态；\n"
            "用 check_foreshadowing 检查伏笔埋设与回收，保证规划与既有设定一致。\n"
            "输出规范：输出结构化章节规划，包含章节目标、场景清单、关键事件、伏笔操作与衔接要点，不直接撰写正文。\n"
        ),
        "tool_ids": ["search_characters", "check_foreshadowing", "get_prior_summary"],
        "skill_name": "architecture-methodology",
        "role_key": "architect",
    },
    {
        "name": "写手",
        "description": "正文生成",
        "icon": "✍️",
        "system_prompt": (
            "你的职责：作为写手，按既定大纲撰写章节正文，场景切换自然、对话符合人设，保持视角一致。\n"
            "工具使用：动笔前获取前文摘要；用 search_characters 核对角色语气与设定；\n"
            "用 check_foreshadowing 确认伏笔衔接，完成后用 save_draft 保存草稿。\n"
            "输出规范：输出可直接阅读的正文初稿，覆盖大纲关键事件，保存草稿后向用户报告完成情况。\n"
        ),
        "tool_ids": [
            "search_characters",
            "check_foreshadowing",
            "get_prior_summary",
            "save_draft",
        ],
        "skill_name": "writing-methodology",
        "role_key": "writer",
    },
    {
        "name": "审校员",
        "description": "一致性审计",
        "icon": "🔍",
        "system_prompt": (
            "你的职责：作为审校员，对章节执行一致性审计，检查字数、设定漂移与伏笔状态。\n"
            "工具使用：用 count_words 统计章节字数；用 audit_chapter 执行章节级检查；\n"
            "用 search_characters 复核角色档案与世界观设定的冲突点。\n"
            "输出规范：输出结构化 findings，逐条标注问题类型、位置、证据与修改建议，不改写正文。\n"
        ),
        "tool_ids": ["audit_chapter", "count_words", "search_characters"],
        "skill_name": "audit-methodology",
        "role_key": "auditor",
    },
    {
        "name": "修订师",
        "description": "修订打磨",
        "icon": "🛠️",
        "system_prompt": (
            "你的职责：作为修订师，在保留原意的前提下修订打磨章节，\n"
            "依据审校 findings 控制改动幅度，不做风格性重写。\n"
            "工具使用：修订前获取前文摘要；用 count_words 核对修订前后字数；\n"
            "完成后用 save_draft 保存草稿。\n"
            "输出规范：输出修订后的正文草稿与改动清单，说明每处修改对应的 finding，供用户确认。\n"
        ),
        "tool_ids": ["get_prior_summary", "count_words", "save_draft"],
        "skill_name": "revision-methodology",
        "role_key": "reviser",
    },
    {
        "name": "世界观顾问",
        "description": "世界观一致",
        "icon": "🌍",
        "system_prompt": (
            "你的职责：作为世界观顾问，校验角色档案与伏笔是否符合项目世界观设定。\n"
            "工具使用：用 search_characters 核对角色的出身、能力与关系；\n"
            "用 check_foreshadowing 检查伏笔走向是否越过世界观边界。\n"
            "输出规范：输出世界观一致性问题清单，逐条给出矛盾点、世界观依据与修正建议，不直接改写档案或正文。\n"
        ),
        "tool_ids": ["search_characters", "check_foreshadowing"],
        "skill_name": "worldview-methodology",
        "role_key": "worldview",
    },
    {
        "name": "润色师",
        "description": "文笔润色",
        "icon": "✨",
        "system_prompt": (
            "你的职责：作为润色师，在不改变情节与人物行动的前提下润色文笔，精炼句式、优化节奏、统一用词。\n"
            "工具使用：润色前获取前文摘要以保持文风一致；完成后用 count_words 统计字数。\n"
            "输出规范：输出润色后的正文与改动摘要，明确说明修改仅限文笔层面，不涉及情节调整。\n"
        ),
        "tool_ids": ["count_words", "get_prior_summary"],
        "skill_name": "polishing-methodology",
        "role_key": "polisher",
    },
]
"""内置 6 Agent 出厂配置（spec §5.3 出厂表，builtin=True 只读）."""


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _slugify_role_key(name: str) -> str:
    """name slug 化（§5.7.2）：小写 + 非 [a-z0-9_] 替换为 _ + 去首尾 _；结果为空 → 'agent'."""
    slug = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    return slug or "agent"


def _validate_tool_ids(tool_ids: list[str]) -> None:
    """工具白名单校验：目录外或 allow_custom_agent=False（核心）→ ToolReferenceError（422）.

    #838: 自定义 agent 不可勾选目录内核心工具（agent_run/agent_call + 删除类），
    与目录外名同等拒绝——均按统一目录 ALL_TOOL_SPECS 判定。
    """
    specs = {spec.name: spec for spec in ALL_TOOL_SPECS}
    for tool_id in tool_ids:
        spec = specs.get(tool_id)
        if spec is None or not spec.allow_custom_agent:
            raise ToolReferenceError()


class AgentEntityService:
    """Agent 实体业务服务 — CRUD + 同名查重 + tool/skill 白名单校验.

    Args:
        agent_repository: Agent 仓储端口.
        skills_root: skill 文件系统真源根（data_dir/skills，#522）.
    """

    def __init__(
        self,
        *,
        agent_repository: AgentRepositoryProtocol,
        skills_root: Path,
    ) -> None:
        self._agent_repo = agent_repository
        self._skills_root = skills_root

    async def create(self, data: AgentCreate) -> Agent:
        """创建自定义 Agent（同名冲突 → 422；tool/skill 白名单校验）.

        查重未命中 → 白名单全过 → 构造实体（id=None、builtin=False、时间戳
        填充为 now(UTC)、role_key 自动分配）→ 委托 repo.add。
        """
        existing = await self._agent_repo.get_by_name(data.name)
        if existing is not None:
            raise AgentNameConflictError()
        _validate_tool_ids(data.tool_ids)
        await self._validate_skill_ids(data.skill_ids)
        # v1.5 #484（spec §5.7.2）：role_key = name slug 化 base，冲突追加数字后缀
        existing_keys = {a.role_key for a in await self._agent_repo.list() if a.role_key}
        base = _slugify_role_key(data.name)
        assigned = base
        suffix = 1
        while assigned in existing_keys:
            assigned = f"{base}_{suffix}"
            suffix += 1
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
            role_key=assigned,
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

    async def duplicate(self, agent_id: int, *, name: str | None = None) -> Agent:
        """复制 Agent（镜像 agent_template_service.duplicate，#485）.

        目标不存在 → AgentNotFoundError；新 name = 指定名或 f"{原 name} 副本"
        （空格分隔）；经 agent_repository.get_by_name 查重命中 →
        AgentNameConflictError；成功 → 构造副本（id=None、builtin=False、
        role_key 按 create 同名逻辑重分配、白名单校验同 create）并委托
        agent_repository.add，直接返回其结果.
        """
        existing = await self._agent_repo.get(agent_id)
        if existing is None:
            raise AgentNotFoundError()
        new_name = name or f"{existing.name} 副本"
        dup = await self._agent_repo.get_by_name(new_name)
        if dup is not None:
            raise AgentNameConflictError()
        _validate_tool_ids(existing.tool_ids)
        await self._validate_skill_ids(existing.skill_ids)
        # role_key 按 create 同名逻辑重新分配（中文副本名 slug 回退 "agent"）
        existing_keys = {a.role_key for a in await self._agent_repo.list() if a.role_key}
        base = _slugify_role_key(new_name)
        assigned = base
        suffix = 1
        while assigned in existing_keys:
            assigned = f"{base}_{suffix}"
            suffix += 1
        now = _utcnow()
        clone = existing.model_copy(
            update={
                "id": None,
                "name": new_name,
                "builtin": False,
                "role_key": assigned,
                "created_at": now,
                "updated_at": now,
            }
        )
        logger.info("复制 Agent: agent_id=%s → name=%s", agent_id, new_name)
        return await self._agent_repo.add(clone)

    async def _validate_skill_ids(self, skill_ids: builtins.list[str]) -> None:
        """skill 引用校验（#522 目录名语义）：任一目录名无 <name>/SKILL.md
        文件 → SkillReferenceError（422）."""
        for skill_name in skill_ids:
            if not (self._skills_root / skill_name / "SKILL.md").is_file():
                raise SkillReferenceError()


async def seed_builtin_agents(session: AsyncSession) -> int:
    """幂等 seed 内置 6 Agent（spec §5.3 出厂表，builtin=True 只读）.

    镜像 seed_builtin_providers 幂等模式：按 name 判重，同名跳过，重复启动
    不重复插入；返回本次实际插入条数。skill_ids = [spec.skill_name]（skill
    目录名英文 slug，#522：不再按 BUILTIN_SKILL_NAMES.index 预测主键）。
    """
    # seed 契约（test_builtin_seed.py）固定本函数位置 + session 显式注入；
    # 此处按既有模块内 infra import 先例（ALL_TOOL_SPECS）构造 SQLite 仓储。
    agent_repo = SQLiteAgentRepository(session)
    inserted = 0
    for spec in BUILTIN_AGENT_SPECS:
        name = spec["name"]
        existing = await agent_repo.get_by_name(name)
        if existing is not None:
            # v1.5 #484 seed 升级钩子：存量同名（v1.5 前已 seed）role_key 为空且
            # spec 有 role_key → 补值 UPDATE（不重复插入）
            if existing.role_key is None and spec["role_key"] is not None:
                existing.role_key = spec["role_key"]
                await agent_repo.update(existing)
            continue
        await agent_repo.add(
            Agent(
                id=None,
                name=name,
                description=spec["description"],
                icon=spec["icon"],
                system_prompt=spec["system_prompt"],
                tool_ids=list(spec["tool_ids"]),
                skill_ids=[spec["skill_name"]],
                builtin=True,
                role_key=spec["role_key"],
            )
        )
        inserted += 1
    return inserted
