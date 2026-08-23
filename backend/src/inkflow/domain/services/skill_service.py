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
            "## 目标\n"
            "\n"
            "本 skill 用于在撰写正文之前规划章节结构与大纲，确保目标章节在全书弧线中\n"
            "的位置清晰、起承转合完整，并与既有伏笔、角色设定和世界观设定保持一致。\n"
            "适用于新建章节规划、章节拆分合并以及大纲调整场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. 先确认目标章节在大纲中的位置：读取前文摘要，判断本章处于全书弧线\n"
            "的开端、发展、高潮还是收束阶段，据此决定本章节奏与篇幅。\n"
            "2. 规划章节骨架：按起承转合组织内容，明确冲突推进与情绪转折，\n"
            "确定悬念埋设与伏笔回收计划，保证章节节奏张弛有度。\n"
            "3. 核对角色设定与伏笔状态：确认新规划不偏离既有档案，不重复、不矛盾、不漏回收。\n"
            "4. 输出结构化章节规划：列出章节目标、场景清单、关键事件、伏笔操作与衔接要点。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 不直接撰写正文：本 skill 只产出章节规划，正文由写作方法论负责。\n"
            "- 不擅自新增角色或世界观设定：超出既有档案的内容标注为待确认项，交由用户决策。\n"
            "- 避免规划过度具体：场景描写与对话台词留给正文阶段，此处只锁定结构、冲突与伏笔走向。\n"
            "\n"
            "## 示例\n"
            "\n"
            "规划「第 12 章 真相浮出」：先读取前文摘要确认本章位于发展段转折点，再核对\n"
            "主角状态与第 3 章埋下的信物伏笔，输出规划——本章目标为回收信物伏笔并引出\n"
            "下一冲突，场景清单为「旧宅搜查 → 信件发现 → 对峙」。\n"
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
            "## 目标\n"
            "\n"
            "本 skill 用于按既定大纲撰写章节正文，将规划落地为可读的小说文本，要求\n"
            "场景切换自然、对话符合人设、视角保持一致，并在完成后保存草稿。适用于\n"
            "大纲已确认、需要产出正文初稿的场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. 先读取大纲或章节规划，明确本章目标、场景清单与关键事件，并获取前文摘要保持衔接。\n"
            "2. 按大纲顺序撰写正文：每个场景一段推进，切换场景时用过渡句自然衔接，避免跳切生硬。\n"
            "3. 撰写对话时对照角色档案：确认语气、称呼与禁忌符合人设，全程保持统一视角。\n"
            "4. 完成后保存草稿，并检查是否遗漏规划中的关键事件或伏笔操作。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 不擅自改变大纲结构：情节走向、关键事件与结局须遵循规划，需要调整时先回到大纲规划。\n"
            "- 不引入与既有设定矛盾的信息：写作用到角色或世界观细节时先查证，拿不准就留白。\n"
            "- 不在草稿中插入审查性评论：审校、修订与润色由后续方法论负责。\n"
            "\n"
            "## 示例\n"
            "\n"
            "撰写「第 12 章 真相浮出」：先获取前文摘要，再按规划的场景清单写「旧宅搜查 →\n"
            "信件发现 → 对峙」三段正文；对话按角色档案调整语气，统一使用第三人称限知视角；\n"
            "写完后保存草稿并确认关键事件全部落地。\n"
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
            "## 目标\n"
            "\n"
            "本 skill 用于对章节草稿执行一致性审计，检查字数、设定漂移与伏笔状态等\n"
            "方面的矛盾或遗漏，输出结构化 findings。适用于正文初稿完成、需要质量把关\n"
            "的场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. 先统计章节字数，确认是否符合目标篇幅，偏差过大时记为一条发现。\n"
            "2. 获取前文摘要，将本章内容与前文事实对照，找出时间线、地点、事件顺序上的矛盾。\n"
            "3. 复核角色档案与伏笔状态：性格、能力、关系是否漂移，应回收的伏笔是否兑现或遗漏。\n"
            "4. 汇总输出结构化 findings：逐条标注问题类型、位置、证据原文与修改建议。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 只审计不改写：本 skill 产出问题清单，正文修改由修订方法论或写手完成。\n"
            "- 不臆断作者意图：证据不足的疑点标注为「存疑」而非直接判定错误。\n"
            "- 避免噪音式报错：重复问题合并为一条，聚焦影响读者理解的一致性缺陷。\n"
            "\n"
            "## 示例\n"
            "\n"
            "审计「第 12 章 真相浮出」：统计字数发现超出目标 2000 字；复核角色档案发现\n"
            "主角称呼与前文不一致；检查伏笔发现第 3 章信物应在本章回收却缺失。最终输出\n"
            "3 条 findings，每条含类型、位置、证据与建议。\n"
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
            "## 目标\n"
            "\n"
            "本 skill 用于在保留原意的前提下修订打磨章节草稿，依据审校 findings 或用户\n"
            "意见修改文本，控制改动幅度，修订后统计字数并保存草稿供用户确认。适用于\n"
            "草稿已有明确问题、需要修改落地的场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. 先获取前文摘要，再对照审校 findings 或用户要求，确定本次修订的范围与优先级。\n"
            "2. 逐条处理：修正设定矛盾、补齐遗漏伏笔、理顺逻辑与衔接，保留作者原意。\n"
            "3. 控制改动幅度：只改问题点对应的句子与段落，不重排场景结构，避免引入新矛盾。\n"
            "4. 修订完成后统计新字数并保存草稿，向用户说明改动清单。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 不超出指定范围：没有对应 finding 或用户要求的段落不主动大改，尤其不动情节走向。\n"
            "- 不替审校下结论：findings 的判定由审计方法论负责，修订只按结论执行。\n"
            "- 避免重复打回：保存前复查改动是否引入新的设定矛盾，必要时再走一次审计。\n"
            "\n"
            "## 示例\n"
            "\n"
            "按审校 findings 修订「第 12 章」：先获取前文摘要，修正主角称呼并补写缺失的\n"
            "信物伏笔细节，其余段落保持原样；完成后统计字数并保存草稿，回复用户改动点\n"
            "清单。\n"
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
            "## 目标\n"
            "\n"
            "本 skill 用于校验角色档案与伏笔是否符合项目世界观设定，发现矛盾时给出修正\n"
            "建议而非直接改写。适用于设定档案更新、新章节引入新设定或需要全局一致性\n"
            "把关的场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. 先确认世界观基准：明确力量体系、地理、时代、社会规则等不可违背的约束。\n"
            "2. 检查角色档案：角色的出身、能力、关系是否与世界观规则冲突。\n"
            "3. 检查伏笔：伏笔内容与兑现方式是否越过世界观边界，存在设定层面的矛盾。\n"
            "4. 输出修正建议：逐条列出矛盾点、世界观依据与建议方案，不直接改写档案与正文。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 只建议不改写：本 skill 产出建议清单，实际修改由用户或修订方法论执行。\n"
            "- 不扩大解释设定：世界观未明示的细节不作硬性推断，标注为待确认项。\n"
            "- 与审计的职责边界：本 skill 聚焦世界观规则本身，章节内部叙事一致性问题交给审计。\n"
            "\n"
            "## 示例\n"
            "\n"
            "校验新角色「矿脉巫师」：检查档案发现其能力依赖地脉水晶，但世界观设定中水晶\n"
            "早已枯竭，且前文未埋下再生伏笔。输出建议——调整能力来源或补充枯竭例外设定，\n"
            "交由用户决定。\n"
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
            "## 目标\n"
            "\n"
            "本 skill 用于在内容不变的前提下润色章节文笔：精炼句式、优化节奏、统一用词，\n"
            "提升阅读体验。适用于正文内容已定稿、需要文笔层面收尾打磨的场景。\n"
            "\n"
            "## 方法步骤\n"
            "\n"
            "1. 先获取前文摘要，保持润色后与前文文风、称谓、措辞一致。\n"
            "2. 逐段润色：精炼冗余句式、拆分过长句子、优化段落节奏，统一同义词与称呼用法。\n"
            "3. 检查细节：删减重复修饰、修正语病与标点，确保语气与人设、场景氛围相符。\n"
            "4. 完成后统计字数，向用户说明改动幅度，不改动情节与人物行动。\n"
            "\n"
            "## 边界\n"
            "\n"
            "- 不改变情节与人物行动：影响剧情走向、事件结果或角色决策的改动属于修订而非润色。\n"
            "- 不做结构级调整：场景顺序、段落重组与增删内容不在本 skill 范围内。\n"
            "- 保持作者风格：只清除明显冗余与瑕疵，不把文本改写成统一模板腔。\n"
            "\n"
            "## 示例\n"
            "\n"
            "润色「第 12 章 真相浮出」：先获取前文摘要确认用词习惯，再逐段精炼句式、统一\n"
            "指代并优化对峙段落的节奏；完成后统计字数并回复改动摘要，正文内容与情节保持\n"
            "不变。\n"
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
