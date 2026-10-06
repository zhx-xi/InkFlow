"""skill 白名单装配 —— 领域纯函数（spec f39 §5.2 v1.5 / #1472 + #1473）。

写手轨（infrastructure 装配层 `agentic_writer.py`）与管线链路（domain stage
构造 `agent_service_stream._build_pipeline_context`）共用**同一**拼接实现：
`_append_skills` 原定义在 `infrastructure/agent/agentic_writer.py`，因管线
stage 构造在 domain 层而 domain 层不得 import infrastructure（AGENTS.md §4.2），
故将该**纯字符串函数**下沉至本模块，infrastructure 以别名引用（避免两份实现）。

`resolve_effective_skills`（#1473）：有效技能集 = 显式挂载 ∪ 通用（库中未被任何
Agent 挂载者）。装配侧（管线链路 / 写手轨观测面）共用，`mounted_names` 由调用方
从 Agent 真源一次性聚合（零额外查询）。

本模块零外部依赖（仅标准库 pathlib / dataclasses），不引入循环；skill 内容真源
= `<data_dir>/skills/<name>/SKILL.md`（ADR-039 #522 文件系统真源）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

SKILL_FILENAME = "SKILL.md"
"""Skill 正文文件名（目录名 = slug，ADR-039 #522）。"""


@dataclass(frozen=True)
class FileSkill:
    """`append_skills` 的鸭子对象（含 name/content）——文件系统真源快照。"""

    name: str
    content: str


@dataclass(frozen=True)
class EffectiveSkill:
    """有效技能集条目（`resolve_effective_skills` 产出）。

    Attributes:
        name: skill 目录名（= frontmatter name，N2 规则）.
        source: 取集来源——`"explicit"`（该 Agent 显式挂载）/ `"general"`（通用）.
    """

    name: str
    source: str


def read_skill_content(skills_root: Path, name: str) -> str | None:
    """读 `<skills_root>/<name>/SKILL.md`；缺失/不可读 → None（跳过语义）。"""
    try:
        return (skills_root / name / SKILL_FILENAME).read_text(encoding="utf-8")
    except OSError:
        return None


def file_skill_lookup(skills_root: Path) -> Callable[[str], object | None]:
    """构造按目录名读文件系统真源的查表函数（`append_skills` 的 skill_lookup）。"""

    def lookup(name: str) -> object | None:
        content = read_skill_content(skills_root, name)
        return None if content is None else FileSkill(name=name, content=content)

    return lookup


def list_skill_names(skills_root: Path) -> list[str]:
    """列出 skill 库中已安装的目录名（含 `SKILL.md` 者，按名升序）。

    仅「目录 + `SKILL.md` 都在」才算已安装；库目录不存在 → 空列表（防御语义）。
    """
    if not skills_root.is_dir():
        return []
    return sorted(
        child.name
        for child in skills_root.iterdir()
        if child.is_dir() and (child / SKILL_FILENAME).is_file()
    )


def resolve_effective_skills(
    *,
    skills_root: Path,
    explicit_ids: Sequence[str],
    mounted_names: set[str],
) -> list[EffectiveSkill]:
    """解析**有效技能集** = 显式挂载（`explicit`）∪ 未被任何 Agent 挂载的通用 skill（`general`）。

    spec f39 §5.2 v1.5（#1473，推翻 #1472 的「只拼白名单」语义）：

    - 顺序 = explicit（按传入白名单序，去重）→ general（按目录名升序）；
    - 覆盖顺序：显式挂载优先于通用（已进 `explicit` 的目录名不再以 general 出现）；
    - 通用判据 = 目录名**不在** `mounted_names`（= 全库 Agent `skill_ids` 并集）；
    - 库中不存在该目录（无 `SKILL.md`）→ 跳过（防御语义，镜像 `append_skills`）。

    Args:
        skills_root: skill 库根（`<data_dir>/skills`）.
        explicit_ids: 该 Agent 的显式挂载白名单（目录名序列）.
        mounted_names: 全库「被任一 Agent 挂载过」的目录名集合.

    Returns:
        条目列表（`EffectiveSkill`，含 name + source）。
    """
    entries: list[EffectiveSkill] = []
    seen: set[str] = set()
    for name in explicit_ids:
        if name in seen or read_skill_content(skills_root, name) is None:
            continue
        entries.append(EffectiveSkill(name=name, source="explicit"))
        seen.add(name)
    for name in list_skill_names(skills_root):
        if name in seen or name in mounted_names:
            continue
        entries.append(EffectiveSkill(name=name, source="general"))
        seen.add(name)
    return entries


def append_skills(
    base_prompt: str,
    skill_ids: list[str],
    skill_lookup: Callable[[str], object | None],
) -> str:
    """把白名单 skill 内容按顺序拼接到 base prompt 之后（spec §5.2）。

    Args:
        base_prompt: 基础 system prompt（恒在前）.
        skill_ids: skill 白名单（skill 目录名列表，顺序固定，#522）.
        skill_lookup: 按 skill 目录名取 Skill 鸭子对象（含 name/content）的
            查表函数；查不到该目录名 → 跳过（防御语义，契约疑点 2）.

    Returns:
        拼接后的完整 system prompt：base + 每个命中 skill 追加
        '``\\n\\n# 技能：<name>\\n\\n<content>\\n\\n---\\n``'.
    """
    parts = [base_prompt]
    for skill_name in skill_ids:
        skill = skill_lookup(skill_name)
        if skill is None:
            continue
        name = getattr(skill, "name", "")
        content = getattr(skill, "content", "")
        parts.append(f"\n\n# 技能：{name}\n\n{content}\n\n---\n")
    return "".join(parts)
