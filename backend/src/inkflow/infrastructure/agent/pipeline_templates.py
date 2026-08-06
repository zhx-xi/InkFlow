"""管线模板 — 内置写作流水线定义。"""

from __future__ import annotations

from inkflow.domain.models.agent_pipeline import PipelineConfig
from inkflow.domain.ports.agent_pipeline import AgentRole, PipelineStage

# 内置角色默认 Prompt（中文）
_ARCHITECT_PROMPT = """你是一位资深小说架构师。根据以下信息规划章节结构和情节走向：
- 题材: {genre}
- 目标字数: {target_words}
- 前文摘要: {context}

请输出：1) 本章核心冲突 2) 情节节奏（起承转合）3) 关键场景列表"""

_WRITER_PROMPT = """你是一位专业小说写手。根据架构师的规划撰写章节内容：
- 架构规划: {architect_output}
- 写作风格: {writing_style}

请写出完整章节，语言流畅自然，情节紧扣规划。"""

_AUDITOR_PROMPT = """你是一位资深文学审阅。仔细审校以下章节内容，从文笔、结构、一致性三个维度评估：
- 章节内容: {writer_output}

请输出：1) 优点 2) 需改进之处（具体指出段落）3) 一致性检查结果"""

_REVISER_PROMPT = """你是一位专业文稿修订师。根据审阅意见修订章节：
- 原文: {writer_output}
- 审阅意见: {auditor_output}

请输出修订后的完整章节，保持原有优点，针对性地改进问题。"""


def _build_write_chapter_template() -> PipelineConfig:
    """构建 builtin:write_chapter 模板 — Architect→Writer→Auditor→Reviser 四阶段链。"""
    architect = AgentRole(
        id="architect",
        name="架构师",
        system_prompt=_ARCHITECT_PROMPT,
        model="openai/gpt-4o",
        temperature=None,  # None = 跟随默认 → 项目顶层温度（spec §9.2.3 温度链）
    )
    writer = AgentRole(
        id="writer",
        name="写手",
        system_prompt=_WRITER_PROMPT,
        model="openai/gpt-4o",
        temperature=0.8,
    )
    auditor = AgentRole(
        id="auditor",
        name="审阅",
        system_prompt=_AUDITOR_PROMPT,
        model="openai/gpt-4o",
        temperature=0.5,
    )
    reviser = AgentRole(
        id="reviser",
        name="修订",
        system_prompt=_REVISER_PROMPT,
        model="openai/gpt-4o",
        temperature=0.6,
    )

    stages = [
        PipelineStage(id="architect", name="架构规划", agent=architect, output_to=["writer"]),
        PipelineStage(
            id="writer",
            name="内容写作",
            agent=writer,
            input_from=["architect"],
            output_to=["auditor"],
        ),
        PipelineStage(
            id="auditor",
            name="质量审校",
            agent=auditor,
            input_from=["writer"],
            output_to=["reviser"],
        ),
        PipelineStage(id="reviser", name="修订定稿", agent=reviser, input_from=["auditor"]),
    ]

    return PipelineConfig(
        name="章节写作 (4 阶段)",
        description="Architect → Writer → Auditor → Reviser 标准写作流水线",
        stages=stages,
        source="builtin",
    )


BUILTIN_TEMPLATES: dict[str, PipelineConfig] = {
    "builtin:write_chapter": _build_write_chapter_template(),
}


def get_template(template_id: str) -> PipelineConfig | None:
    """获取内置模板。"""
    return BUILTIN_TEMPLATES.get(template_id)


def list_templates() -> list[dict]:
    """列出所有模板元信息（不含完整 Prompt）。"""
    return [
        {
            "id": tid,
            "name": tpl.name,
            "description": tpl.description,
            "stages": [s.id for s in tpl.stages],
            "source": tpl.source,
        }
        for tid, tpl in BUILTIN_TEMPLATES.items()
    ]
