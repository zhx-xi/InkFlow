"""Skill 业务服务 — 文件系统真源 CRUD + frontmatter 解析 + 删除级联清引用.

职责（spec §2.2/§3.3/§5.6/§7 + ADR-039 #522）:
- 文件系统真源：skill 实体 = data_dir/skills/<name>/SKILL.md（不再落 DB
  表）；list 扫描 skills_root/*/SKILL.md，get/create/update/delete/
  duplicate 全部内联文件系统操作（不再注入 skill_repository）
- frontmatter 后端解析（422）：create/update(content) 复用
  inkflow.cli.skills_parser.parse_skill_metadata（N2 严格规则
  ^[a-z0-9]+(-[a-z0-9]+)*$，name 须=目录名）；失败 → SkillFrontmatterError
- 同名唯一性校验（422）：create/duplicate 前检查同名目录已存在 →
  SkillNameConflictError
- 资源不存在（404 语义）：get/update/delete/duplicate 目标缺失 →
  SkillNotFoundError
- source 判定：目录名 ∈ BUILTIN_SKILL_NAMES（6 英文 slug）→ "builtin"
  （只读 409），否则 "user_upload"
- delete：source="builtin" → SkillBuiltinError（409）；被 N 个 Agent
  引用 → 先级联清引用（逐个移除 Agent.skill_ids 中的该目录名并
  agent_repository.update）再删目录（spec §5.6）
- 时间戳契约：created_at/updated_at 为 SKILL.md 文件 mtime ISO 字符串
  （create/update 写盘后读取；不锁精确值）

依赖通过构造函数注入（ADR-015，测试注入 Mock）；文件系统操作内联实现。
"""

from __future__ import annotations

import builtins
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.cli.skills_parser import SkillMetadata, SkillValidationError, parse_skill_metadata
from inkflow.domain.models.skill import Skill, SkillCreate, SkillUpdate
from inkflow.domain.ports.agent_repository import AgentRepositoryProtocol
from inkflow.domain.ports.skill_errors import (
    SkillBuiltinError,
    SkillFrontmatterError,
    SkillNameConflictError,
    SkillNotFoundError,
)

logger = logging.getLogger(__name__)


BUILTIN_SKILL_NAMES: list[str] = [
    "architecture-methodology",
    "writing-methodology",
    "audit-methodology",
    "revision-methodology",
    "worldview-methodology",
    "polishing-methodology",
]
"""内置 6 Skill 出厂目录名（英文 slug，N2 合规；顺序 = ensure_builtin_skills 写出序）."""


class _BuiltinSkillSpec(TypedDict):
    """内置 Skill 出厂配置项（spec §5.3，content = 完整 SKILL.md）."""

    name: str
    description: str
    content: str


BUILTIN_SKILL_SPECS: list[_BuiltinSkillSpec] = [
    {
        "name": "architecture-methodology",
        "description": "章节结构/大纲规划方法论",
        "content": (
            "---\n"
            "name: architecture-methodology\n"
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
        "name": "writing-methodology",
        "description": "正文生成方法论",
        "content": (
            "---\n"
            "name: writing-methodology\n"
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
        "name": "audit-methodology",
        "description": "一致性审计方法论",
        "content": (
            "---\n"
            "name: audit-methodology\n"
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
        "name": "revision-methodology",
        "description": "修订打磨方法论",
        "content": (
            "---\n"
            "name: revision-methodology\n"
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
        "name": "worldview-methodology",
        "description": "世界观一致性方法论",
        "content": (
            "---\n"
            "name: worldview-methodology\n"
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
        "name": "polishing-methodology",
        "description": "文笔润色方法论",
        "content": (
            "---\n"
            "name: polishing-methodology\n"
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
"""内置 6 Skill 出厂配置（spec §5.3，目录名 ∈ BUILTIN_SKILL_NAMES → source="builtin" 只读）."""


def _source_of(name: str) -> str:
    """source 判定：目录名 ∈ BUILTIN_SKILL_NAMES → "builtin"，否则 "user_upload"."""
    return "builtin" if name in BUILTIN_SKILL_NAMES else "user_upload"


def _mtime_iso(path: Path) -> str:
    """文件 mtime → ISO 8601 字符串（UTC，datetime.fromisoformat 可解析）."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def _frontmatter_name(content: str) -> str:
    """提取 content frontmatter 的 name 原值（未校验；缺失 → ""）."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        if key.strip() == "name":
            return value.strip().strip('"').strip("'")
    return ""


def _parse_upload(content: str, directory_name: str) -> SkillMetadata:
    """解析并校验 content frontmatter；失败 → SkillFrontmatterError（422）."""
    try:
        return parse_skill_metadata(content, directory_name)
    except SkillValidationError as err:
        raise SkillFrontmatterError() from err


class SkillService:
    """Skill 业务服务 — 文件系统真源 CRUD + frontmatter 解析 + 删除级联清引用.

    Args:
        skills_root: skill 文件系统真源根（data_dir/skills）.
        agent_repository: Agent 仓储端口（删除级联清引用用）.
    """

    def __init__(
        self,
        *,
        skills_root: Path,
        agent_repository: AgentRepositoryProtocol,
    ) -> None:
        self._skills_root = skills_root
        self._agent_repo = agent_repository

    async def create(self, data: SkillCreate) -> Skill:
        """创建用户上传 Skill（frontmatter 解析 → 同名查重 → 写文件）.

        目录名 = frontmatter name（parse_skill_metadata 强制 name == 目录名
        且匹配 N2）；同名目录已存在 → SkillNameConflictError（422）；成功
        → 写出 skills_root/<name>/SKILL.md（content 原样）并返回实体。
        """
        meta = _parse_upload(data.content, _frontmatter_name(data.content))
        name = meta.name
        target_dir = self._skills_root / name
        if target_dir.exists():
            raise SkillNameConflictError()
        self._skills_root.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        skill_file = target_dir / "SKILL.md"
        skill_file.write_text(data.content, encoding="utf-8")
        logger.info("创建 Skill: name=%s", name)
        return Skill(
            name=name,
            description=meta.description,
            content=data.content,
            source="user_upload",
            created_at=_mtime_iso(skill_file),
            updated_at=_mtime_iso(skill_file),
        )

    async def get(self, name: str) -> Skill:
        """按目录名读 skills_root/<name>/SKILL.md → Skill；缺失 → SkillNotFoundError（404）."""
        skill_file = self._skills_root / name / "SKILL.md"
        if not skill_file.is_file():
            raise SkillNotFoundError()
        content = skill_file.read_text(encoding="utf-8")
        description = ""
        try:
            description = parse_skill_metadata(content, name).description
        except SkillValidationError:
            description = ""
        return Skill(
            name=name,
            description=description,
            content=content,
            source=_source_of(name),
            created_at=_mtime_iso(skill_file),
            updated_at=_mtime_iso(skill_file),
        )

    async def list(self) -> builtins.list[Skill]:
        """列出全部 Skill（扫描 skills_root/*/SKILL.md 解析元数据，按 name 升序）."""
        if not self._skills_root.is_dir():
            return []
        items: builtins.list[Skill] = []
        for child in sorted(self._skills_root.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue
            content = skill_file.read_text(encoding="utf-8")
            description = ""
            try:
                description = parse_skill_metadata(content, child.name).description
            except SkillValidationError:
                description = ""
            items.append(
                Skill(
                    name=child.name,
                    description=description,
                    content=content,
                    source=_source_of(child.name),
                    created_at=_mtime_iso(skill_file),
                    updated_at=_mtime_iso(skill_file),
                )
            )
        return sorted(items, key=lambda s: s.name)

    async def update(self, name: str, data: SkillUpdate) -> Skill:
        """部分更新 Skill（文件系统真源）.

        None 值 = 不修改（exclude_unset 浅合并，同 F1/F13）；content 变更
        → 整文件写回 + 按新 frontmatter 重解析（非法 → SkillFrontmatterError）；
        内置目录 → SkillBuiltinError（409）；目标缺失 → SkillNotFoundError。
        """
        existing = await self.get(name)
        if existing.source == "builtin":
            raise SkillBuiltinError()
        updates = {
            k: getattr(data, k) for k in data.model_fields_set if getattr(data, k) is not None
        }
        if "content" in updates:
            content = updates["content"]
            _parse_upload(content, name)
            skill_file = self._skills_root / name / "SKILL.md"
            skill_file.write_text(content, encoding="utf-8")
            logger.info("更新 Skill: name=%s", name)
            return await self.get(name)
        if not updates:
            return existing
        merged = existing.model_copy(update=updates)
        logger.info("更新 Skill（元数据合并）: name=%s", name)
        return merged

    async def delete(self, name: str) -> None:
        """删除 Skill（内置只读 → 409；被引用 → 先级联清引用再删目录）.

        全部引用 Agent 的 update（清 skill_ids）先于目录删除（spec §5.6）；
        目标缺失 → SkillNotFoundError。
        """
        existing = await self.get(name)
        if existing.source == "builtin":
            raise SkillBuiltinError()
        refs = await self._agent_repo.list_agents_by_skill(name)
        for agent in refs:
            agent.skill_ids = [sid for sid in agent.skill_ids if sid != name]
            await self._agent_repo.update(agent)  # type: ignore[call-arg, arg-type]  # 测试 docstring 契约：update 以完整实体单参调用（G2 repo 签名双参形态兼容，见 agent_repo.update）
        target_dir = self._skills_root / name
        if target_dir.is_dir():
            shutil.rmtree(target_dir)
        logger.info("删除 Skill: name=%s", name)

    async def duplicate(self, name: str, *, new_name: str | None = None) -> Skill:
        """复制 Skill（#485 语义延续 + #522 文件系统真源）.

        新名 = 指定名或 f"{name}-copy"；副本目录已存在 → SkillNameConflictError
        （422）；源缺失 → SkillNotFoundError；成功 → 复制整个目录并返回
        副本实体（source="user_upload"）。
        """
        existing = await self.get(name)
        target_name = new_name or f"{name}-copy"
        target_dir = self._skills_root / target_name
        if target_dir.exists():
            raise SkillNameConflictError()
        src_dir = self._skills_root / name
        shutil.copytree(src_dir, target_dir)
        logger.info("复制 Skill: name=%s → %s", name, target_name)
        return Skill(
            name=target_name,
            description=existing.description,
            content=existing.content,
            source="user_upload",
            created_at=_mtime_iso(target_dir / "SKILL.md"),
            updated_at=_mtime_iso(target_dir / "SKILL.md"),
        )


def ensure_builtin_skills(skills_root: Path) -> int:
    """幂等写出 6 个内置 SKILL.md（ADR-039 D3b=A 启动回补）.

    目录缺失/内置缺失 → 写出（content 含 frontmatter name=slug，可被
    parse_skill_metadata 校验）；已存在 → 跳过；返回本次实际写入数。
    """
    skills_root.mkdir(parents=True, exist_ok=True)
    written = 0
    for spec in BUILTIN_SKILL_SPECS:
        target = skills_root / spec["name"] / "SKILL.md"
        if target.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(spec["content"], encoding="utf-8")
        written += 1
    return written


async def migrate_skills_from_db(session: AsyncSession, skills_root: Path) -> int:
    """一次性迁移旧 skills 表 user_upload 行 → 写出文件后清表（ADR-039 D3c=A）.

    raw SQL 实现（sqlalchemy.text），不得依赖 SkillORM；表不存在 → 0（不抛
    错、不重建旧表）；迁移后 DELETE 全部行（含 builtin 行）；返回迁移条数。
    """
    skills_root.mkdir(parents=True, exist_ok=True)
    try:
        result = await session.execute(
            text("SELECT name, content FROM skills WHERE source = 'user_upload'")
        )
    except Exception:
        # 旧库无 skills 表（全新安装/表已被清）→ 无存量可迁移
        await session.rollback()
        return 0
    rows = result.all()
    migrated = 0
    for row in rows:
        name = str(row[0])
        content = str(row[1])
        skill_dir = skills_root / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        migrated += 1
    await session.execute(text("DELETE FROM skills"))
    await session.commit()
    logger.info("迁移旧 skills 表: %s 条 user_upload 行写出文件", migrated)
    return migrated
