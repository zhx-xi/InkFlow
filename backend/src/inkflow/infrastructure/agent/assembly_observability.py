"""#1480 装配可观测面 — 写手轨**目标装配**（system prompt / skill 清单 / tool id 清单）.

背景（issue #1480）：`context assemble` / `write --show-context` / 内核日志都不含
system prompt、注入的 skill 清单与 tool 清单，导致 #1472（管线不装配 skill）/
#1473（通用 skill 全局生效）/ #1476（工具空参）无法从外部验收。

本模块提供「目标装配预览」：按写手轨授权（`resolve_writer_authorization`）+ skill 库
解析**有效技能集**，并复用真实装配代码（`writer_agent.yaml` 渲染 + `_append_skills`）
产出 system prompt，使「这一次运行注入了什么」可外部观测。

语义边界（spec §5.2 v1.5 #1480）：**只观测、不改行为**——本模块不读取生产 deps 的
接线状态（`AgenticWriterDeps.skill_lookup` 现状未注入 → 生产写手轨实际不拼 skill，
属 #1472 范围）；输出描述的是「按当前授权 + skill 库应当注入什么」。

依据: specs/f6-context/spec.md §5.1/§5.2/§6（v1.5 #1480）。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.infrastructure.agent.agentic_writer import (
    _append_skills,
    build_writer_agent_system_prompt,
    resolve_writer_authorization,
)
from inkflow.infrastructure.llm import LangChainPromptManager

_SKILL_FILENAME = "SKILL.md"
"""Skill 正文文件名（目录名 = slug，ADR-039 #522 文件系统真源）。"""


class SkillEntry(TypedDict):
    """有效技能集条目（响应 `skills[]` 元素形状，spec §5.2）."""

    name: str
    bytes: int
    source: str  # "explicit" | "general"


@dataclass(frozen=True)
class _FileSkill:
    """`_append_skills` 的鸭子对象（含 name/content）——文件系统真源快照."""

    name: str
    content: str


def _skill_content(skills_root: Path, name: str) -> str | None:
    """读 `skills_root/<name>/SKILL.md`；缺失/不可读 → None（跳过语义，镜像 `_append_skills`）."""
    try:
        return (skills_root / name / _SKILL_FILENAME).read_text(encoding="utf-8")
    except OSError:
        return None


def list_library_skills(skills_root: Path) -> list[str]:
    """列出 skill 库中已安装的目录名（含 `SKILL.md` 者，按名升序）."""
    if not skills_root.is_dir():
        return []
    return sorted(
        child.name
        for child in skills_root.iterdir()
        if child.is_dir() and (child / _SKILL_FILENAME).is_file()
    )


def resolve_effective_skills(
    *,
    skills_root: Path,
    explicit_ids: list[str],
    mounted_names: set[str],
) -> list[SkillEntry]:
    """解析**有效技能集** = 显式挂载（`explicit`）∪ 未被任何 Agent 挂载的通用 skill（`general`）.

    Args:
        skills_root: skill 库根（`data_dir/skills`）.
        explicit_ids: 写手授权白名单（目录名序 = 拼接序）.
        mounted_names: 全库「被任一 Agent 挂载过」的目录名集合（general 判据 = 不在其中）.

    Returns:
        条目列表；顺序 = explicit（按白名单序）→ general（按名升序）；
        库中不存在的目录名跳过；`bytes` = 该 SKILL.md 的 UTF-8 字节数。
    """
    entries: list[SkillEntry] = []
    seen: set[str] = set()
    for name in explicit_ids:
        content = _skill_content(skills_root, name)
        if content is None:
            continue
        entries.append({"name": name, "bytes": len(content.encode("utf-8")), "source": "explicit"})
        seen.add(name)
    for name in list_library_skills(skills_root):
        if name in seen or name in mounted_names:
            continue
        content = _skill_content(skills_root, name)
        if content is None:
            continue
        entries.append({"name": name, "bytes": len(content.encode("utf-8")), "source": "general"})
    return entries


async def collect_mounted_skill_names(db: AsyncSession) -> set[str]:
    """全库「被任一 Agent 挂载过」的 skill 目录名集合（general = 引用数为 0）.

    与 `inkflow skill list` 的「引用 N 个 Agent」同源（同一 `agents.skill_ids` 数据面）。
    """
    from inkflow.infrastructure.database.repositories.agent_repo import SQLiteAgentRepository

    agents = await SQLiteAgentRepository(db).list()
    return {
        str(skill_id) for agent in agents for skill_id in (getattr(agent, "skill_ids", None) or [])
    }


def _file_skill_lookup(skills_root: Path) -> Callable[[str], object | None]:
    """构造 `_append_skills` 的查表函数（按目录名读文件系统真源）."""

    def lookup(name: str) -> object | None:
        content = _skill_content(skills_root, name)
        return None if content is None else _FileSkill(name=name, content=content)

    return lookup


def build_observable_system_prompt(
    *,
    skills_root: Path,
    context_text: str,
    project_id: uuid.UUID,
    chapter_id: uuid.UUID | None,
    effective_skills: list[SkillEntry],
) -> str:
    """写手轨目标装配产物 = `writer_agent.yaml` 渲染（含本次 context 段）+ 有效技能集正文."""
    base = build_writer_agent_system_prompt(
        LangChainPromptManager(),
        project_id=project_id,
        chapter_id=chapter_id,
        context=context_text,
    )
    names = [str(entry["name"]) for entry in effective_skills]
    return _append_skills(base, names, _file_skill_lookup(skills_root))


async def build_assembly_observability(
    *,
    db: AsyncSession,
    skills_root: Path,
    context_text: str,
    project_id: uuid.UUID,
    chapter_id: uuid.UUID | None,
    show_system_prompt: bool,
    show_skills: bool,
    show_tools: bool,
) -> dict[str, Any]:
    """按开启的观测开关返回 `{system_prompt?, skills?, tools?}` 子集（默认全关 → 空 dict）.

    三个开关互相独立；`tools` 无需读 skill 库（装配层 tool id 恒可得），
    `skills`/`system_prompt` 才触发有效技能集解析（含一次 Agent 表查询）。
    """
    payload: dict[str, Any] = {}
    if not (show_system_prompt or show_skills or show_tools):
        return payload

    tool_ids, explicit_ids = resolve_writer_authorization()
    if show_tools:
        payload["tools"] = list(tool_ids)
    if not (show_system_prompt or show_skills):
        return payload

    mounted = await collect_mounted_skill_names(db)
    effective = resolve_effective_skills(
        skills_root=skills_root,
        explicit_ids=explicit_ids,
        mounted_names=mounted,
    )
    if show_skills:
        payload["skills"] = effective
    if show_system_prompt:
        payload["system_prompt"] = build_observable_system_prompt(
            skills_root=skills_root,
            context_text=context_text,
            project_id=project_id,
            chapter_id=chapter_id,
            effective_skills=effective,
        )
    return payload
