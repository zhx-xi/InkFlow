"""skill 白名单装配 —— 领域纯函数（spec f39 §5.2 v1.4 / #1472）。

写手轨（infrastructure 装配层 `agentic_writer.py`）与管线链路（domain stage
构造 `agent_service_stream._build_pipeline_context`）共用**同一**拼接实现：
`_append_skills` 原定义在 `infrastructure/agent/agentic_writer.py`，因管线
stage 构造在 domain 层而 domain 层不得 import infrastructure（AGENTS.md §4.2），
故将该**纯字符串函数**下沉至本模块，infrastructure 以别名引用（避免两份实现）。

本模块零外部依赖（仅标准库 pathlib / dataclasses），不引入循环；skill 内容真源
= `<data_dir>/skills/<name>/SKILL.md`（ADR-039 #522 文件系统真源）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SKILL_FILENAME = "SKILL.md"
"""Skill 正文文件名（目录名 = slug，ADR-039 #522）。"""


@dataclass(frozen=True)
class FileSkill:
    """`append_skills` 的鸭子对象（含 name/content）——文件系统真源快照。"""

    name: str
    content: str


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
