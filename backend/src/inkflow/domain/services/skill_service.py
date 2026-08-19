"""Skill 业务服务 — Skill CRUD + frontmatter 解析 + 删除级联清引用.

职责（spec §2.2/§3.3/§5.6/§7）:
- CRUD 编排：委托 SkillRepositoryProtocol / AgentRepositoryProtocol
- frontmatter 后端解析（422）：create 时解析 content 的 --- 块提取
  name/description；块缺失 / name 或 description 缺失 / name 格式非法
  （1-64 小写字母数字+连字符）→ SkillFrontmatterError（不查重）
- 同名唯一性校验（422）：create 前 / update 改名时经 skill_repository.get_by_name
  检查，命中 → SkillNameConflictError
- 资源不存在（404 语义）：get/update/delete 目标缺失 → SkillNotFoundError
- update 为 exclude_unset 浅合并（同 F1/F13）：None 值 = 不修改，予以剔除；
  仅 name 变更时查重；updated_at 刷新为 now(UTC)，created_at 保留
- delete：source="builtin"（内置只读）→ SkillBuiltinError（409）；被 N 个
  Agent 引用 → 先级联清引用（逐个移除 Agent.skill_ids 中的该 id 并
  agent_repository.update）再删（spec §5.6）；repo.delete 返回 False（竞态
  已删）→ NotFound
- 时间戳契约：create/update 填充 created_at/updated_at 为 datetime.now(UTC)
  （时区感知）；source 由服务层固定 "user_upload"

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）。
"""

from __future__ import annotations

import builtins
import logging
import re
from datetime import UTC, datetime
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.skill import Skill, SkillCreate, SkillUpdate
from inkflow.domain.ports.agent_repository import AgentRepositoryProtocol
from inkflow.domain.ports.skill_errors import (
    SkillBuiltinError,
    SkillFrontmatterError,
    SkillNameConflictError,
    SkillNotFoundError,
)
from inkflow.domain.ports.skill_repository import SkillRepositoryProtocol
from inkflow.infrastructure.database.repositories.skill_repo import (
    SQLiteSkillRepository,
)

logger = logging.getLogger(__name__)

_NAME_PATTERN = re.compile(r"^[a-z0-9-]{1,64}$")
"""frontmatter name 合法格式：1-64 小写字母数字+连字符（spec §2.2）. """


BUILTIN_SKILL_NAMES: list[str] = [
    "架构方法论",
    "写作方法论",
    "审校方法论",
    "修订方法论",
    "世界观方法论",
    "润色方法论",
]
"""内置 6 Skill 出厂名称（spec §5.3；顺序 = seed_builtin_skills 插入序）."""


class _BuiltinSkillSpec(TypedDict):
    """内置 Skill 出厂配置项（spec §5.3）."""

    name: str
    description: str
    content: str


BUILTIN_SKILL_SPECS: list[_BuiltinSkillSpec] = [
    {
        "name": "架构方法论",
        "description": "章节结构/大纲规划方法论",
        "content": (
            "---\n"
            "name: 架构方法论\n"
            "description: 章节结构/大纲规划方法论\n"
            "---\n"
            "\n"
            "# 架构方法论\n"
            "\n"
            "- 先确认目标章节在大纲中的位置与前后文弧线。\n"
            "- 规划章节结构：起承转合、冲突推进、悬念埋设与回收。\n"
            "- 保持与已有伏笔、角色设定、世界观设定的一致性。\n"
        ),
    },
    {
        "name": "写作方法论",
        "description": "正文生成方法论",
        "content": (
            "---\n"
            "name: 写作方法论\n"
            "description: 正文生成方法论\n"
            "---\n"
            "\n"
            "# 写作方法论\n"
            "\n"
            "- 按大纲撰写正文，场景切换自然，对话符合人设。\n"
            "- 保持视角一致，避免视角漂移与信息矛盾。\n"
            "- 完成正文后调用 save_draft 保存草稿。\n"
        ),
    },
    {
        "name": "审校方法论",
        "description": "一致性审计方法论",
        "content": (
            "---\n"
            "name: 审校方法论\n"
            "description: 一致性审计方法论\n"
            "---\n"
            "\n"
            "# 审校方法论\n"
            "\n"
            "- 对章节执行一致性审计：字数、设定漂移、伏笔状态。\n"
            "- 优先复核角色档案、世界观设定与前后文摘要的冲突点。\n"
            "- 输出结构化 findings，逐条标注问题类型与证据。\n"
        ),
    },
    {
        "name": "修订方法论",
        "description": "修订打磨方法论",
        "content": (
            "---\n"
            "name: 修订方法论\n"
            "description: 修订打磨方法论\n"
            "---\n"
            "\n"
            "# 修订方法论\n"
            "\n"
            "- 在保留原意的前提下修订打磨章节，控制改动幅度。\n"
            "- 修订后统计字数并保存草稿供用户确认。\n"
        ),
    },
    {
        "name": "世界观方法论",
        "description": "世界观一致性方法论",
        "content": (
            "---\n"
            "name: 世界观方法论\n"
            "description: 世界观一致性方法论\n"
            "---\n"
            "\n"
            "# 世界观方法论\n"
            "\n"
            "- 校验角色档案与伏笔是否符合项目世界观设定。\n"
            "- 发现矛盾时给出修正建议而非直接改写。\n"
        ),
    },
    {
        "name": "润色方法论",
        "description": "文笔润色方法论",
        "content": (
            "---\n"
            "name: 润色方法论\n"
            "description: 文笔润色方法论\n"
            "---\n"
            "\n"
            "# 润色方法论\n"
            "\n"
            "- 润色文笔：精炼句式、优化节奏、统一用词。\n"
            "- 不改变情节与人物行动，润色后统计字数。\n"
        ),
    },
]
"""内置 6 Skill 出厂配置（spec §5.3，source="builtin" 只读）."""


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _parse_frontmatter(content: str) -> tuple[str, str]:
    """解析 SKILL.md frontmatter，返回 (name, description).

    --- 块缺失 / name 或 description 缺失 / name 格式非法 →
    SkillFrontmatterError（422）。
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillFrontmatterError()
    fields: dict[str, str] = {}
    closed = False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            closed = True
            break
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        fields[key.strip()] = value.strip().strip('"').strip("'")
    if not closed:
        raise SkillFrontmatterError()
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not name or not description or _NAME_PATTERN.fullmatch(name) is None:
        raise SkillFrontmatterError()
    return name, description


class SkillService:
    """Skill 业务服务 — CRUD + frontmatter 解析 + 删除级联清引用.

    Args:
        skill_repository: Skill 仓储端口.
        agent_repository: Agent 仓储端口（删除级联清引用用）.
    """

    def __init__(
        self,
        *,
        skill_repository: SkillRepositoryProtocol,
        agent_repository: AgentRepositoryProtocol,
    ) -> None:
        self._skill_repo = skill_repository
        self._agent_repo = agent_repository

    async def create(self, data: SkillCreate) -> Skill:
        """创建用户上传 Skill（frontmatter 解析 → 同名查重 → 落库）.

        构造实体（id=None、source="user_upload"、content 原样、时间戳填充为
        now(UTC)）→ 委托 repo.add。
        """
        name, description = _parse_frontmatter(data.content)
        existing = await self._skill_repo.get_by_name(name)
        if existing is not None:
            raise SkillNameConflictError()
        now = _utcnow()
        entity = Skill(
            id=None,
            name=name,
            description=description,
            content=data.content,
            source="user_upload",
            created_at=now,
            updated_at=now,
        )
        logger.info("创建 Skill: name=%s", name)
        return await self._skill_repo.add(entity)

    async def get(self, skill_id: int) -> Skill:
        """按主键获取 Skill；不存在 → SkillNotFoundError（404）."""
        skill = await self._skill_repo.get(skill_id)
        if skill is None:
            raise SkillNotFoundError()
        return skill

    async def list(self) -> builtins.list[Skill]:
        """列出全部 Skill（按 name 升序，委托 repo）."""
        return await self._skill_repo.list()

    async def update(self, skill_id: int, data: SkillUpdate) -> Skill:
        """部分更新 Skill（exclude_unset 浅合并，同 F1/F13）.

        None 值 = 不修改（与未传入等价，合并前剔除）；仅 name 变更时查重
        （命中其他 id → 422）；updated_at 刷新为 now(UTC)，created_at 保留。
        """
        existing = await self._skill_repo.get(skill_id)
        if existing is None:
            raise SkillNotFoundError()
        if existing.source == "builtin":
            raise SkillBuiltinError()
        updates = {
            k: getattr(data, k) for k in data.model_fields_set if getattr(data, k) is not None
        }
        if "name" in updates and updates["name"] != existing.name:
            dup = await self._skill_repo.get_by_name(updates["name"])
            if dup is not None and dup.id != existing.id:
                raise SkillNameConflictError()
        merged = existing.model_copy(update=updates)
        merged.updated_at = _utcnow()
        logger.info("更新 Skill: skill_id=%s", skill_id)
        result = await self._skill_repo.update(merged)  # type: ignore[call-arg, arg-type]  # 测试 docstring 契约：update 以实体单参调用（G2 repo 签名待父侧对齐）
        if result is None:
            raise SkillNotFoundError()
        return result

    async def delete(self, skill_id: int) -> None:
        """删除 Skill（内置只读 → 409；被引用 → 先级联清引用再删）.

        全部引用 Agent 的 update（清 skill_ids）先于 skill delete（spec
        §5.6）；repo.delete 返回 False（竞态已删）→ NotFound。
        """
        existing = await self._skill_repo.get(skill_id)
        if existing is None:
            raise SkillNotFoundError()
        if existing.source == "builtin":
            raise SkillBuiltinError()
        refs = await self._agent_repo.list_agents_by_skill(skill_id)
        target = str(skill_id)
        for agent in refs:
            agent.skill_ids = [sid for sid in agent.skill_ids if sid != target]
            await self._agent_repo.update(agent)  # type: ignore[call-arg, arg-type]  # 测试 docstring 契约：update 以实体单参调用（G2 repo 签名待父侧对齐）
        if not await self._skill_repo.delete(skill_id):
            raise SkillNotFoundError()
        logger.info("删除 Skill: skill_id=%s", skill_id)

    async def duplicate(self, skill_id: int, *, name: str | None = None) -> Skill:
        """复制 Skill（镜像 agent_template_service.duplicate，#485）.

        目标不存在 → SkillNotFoundError；新 name = 指定名或 f"{原 name} 副本"
        （中文合法——duplicate 不走 _parse_frontmatter，区别于 create 的
        frontmatter 校验）；经 skill_repository.get_by_name 查重命中 →
        SkillNameConflictError；成功 → 构造副本（id=None、source="user_upload"、
        description/content 原样）并委托 skill_repository.add，直接返回其结果.
        """
        existing = await self._skill_repo.get(skill_id)
        if existing is None:
            raise SkillNotFoundError()
        new_name = name or f"{existing.name} 副本"
        dup = await self._skill_repo.get_by_name(new_name)
        if dup is not None:
            raise SkillNameConflictError()
        now = _utcnow()
        clone = existing.model_copy(
            update={
                "id": None,
                "name": new_name,
                "source": "user_upload",
                "created_at": now,
                "updated_at": now,
            }
        )
        logger.info("复制 Skill: skill_id=%s → name=%s", skill_id, new_name)
        return await self._skill_repo.add(clone)


async def seed_builtin_skills(session: AsyncSession) -> int:
    """幂等 seed 内置 6 Skill（spec §5.3，source="builtin" 只读）.

    镜像 seed_builtin_providers 幂等模式：按 name 判重，同名跳过，重复启动
    不重复插入；返回本次实际插入条数。content 为含 frontmatter（name/
    description）+ 正文的完整 SKILL.md，与 DB name/description 列一致。
    """
    # seed 契约（test_builtin_seed.py）固定本函数位置 + session 显式注入。
    skill_repo = SQLiteSkillRepository(session)
    inserted = 0
    for spec in BUILTIN_SKILL_SPECS:
        if await skill_repo.get_by_name(spec["name"]) is not None:
            continue
        await skill_repo.add(
            Skill(
                id=None,
                name=spec["name"],
                description=spec["description"],
                content=spec["content"],
                source="builtin",
            )
        )
        inserted += 1
    return inserted
