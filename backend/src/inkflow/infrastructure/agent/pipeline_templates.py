"""管线模板 — 内置写作流水线定义。"""

# #415 G1：角色默认模型引用 config.llm_default_model（配置文件=唯一默认源，代码不写第二份默认值）。

from __future__ import annotations

from inkflow.core.config import config
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

请输出：1) 优点 2) 需改进之处（具体指出段落）3) 一致性检查结果

请最后输出：4) 审核结论：通过 / 不通过"""

_REVISER_PROMPT = """你是一位专业文稿修订师。根据审阅意见修订章节：
- 原文: {writer_output}
- 审阅意见: {auditor_output}

请输出修订后的完整章节，保持原有优点，针对性地改进问题。"""

_AUTO_ARCHITECT_PROMPT = """你是一位资深小说架构师。为一个全新章节从零规划结构与情节：
- 题材: {genre}
- 目标字数: {target_words}
- 设定库摘要: {setting}
- 本章标题: {chapter_title}

请输出：1) 本章核心冲突 2) 情节节奏（起承转合）3) 关键场景列表"""

_AUTO_WRITER_PROMPT = """你是一位专业小说写手。根据架构师的规划，从零撰写本章完整内容：
- 架构规划: {architect_output}
- 写作风格: {writing_style}
- 设定库摘要: {setting}
- 本章标题: {chapter_title}

请写出完整章节，语言流畅自然，情节紧扣规划，无需依赖前文。"""

_AUTO_AUDITOR_PROMPT = (
    "你是一位资深文学审阅。仔细审校以下章节内容，从文笔、结构、一致性三个维度评估：\n"
    "- 章节内容: {writer_output}\n"
    "\n"
    "请输出：1) 优点 2) 需改进之处（具体指出段落）3) 一致性检查结果\n"
    "\n"
    "请最后输出：4) 审核结论：通过 / 不通过"
)

_AUTO_REVISER_PROMPT = """你是一位专业文稿修订师。根据审阅意见修订章节：
- 原文: {writer_output}
- 审阅意见: {auditor_output}

请输出修订后的完整章节，保持原有优点，针对性地改进问题。"""

_CONTINUE_WRITER_PROMPT = """你是一位专业小说写手。根据前文摘要续写下一章节：
- 前文摘要: {context}
- 写作风格: {writing_style}
- 设定库摘要: {setting}
- 本章标题: {chapter_title}

请续写本章完整内容，保持与前文的情节连贯、人物一致、文风统一。"""

_CONTINUE_AUDITOR_PROMPT = (
    "你是一位资深文学审阅。仔细审校续写章节，从文笔、结构、与前文连贯性三个维度评估：\n"
    "- 章节内容: {writer_output}\n"
    "\n"
    "请输出：1) 优点 2) 需改进之处（具体指出段落）3) 连贯性检查结果\n"
    "\n"
    "请最后输出：4) 审核结论：通过 / 不通过"
)

_CONTINUE_REVISER_PROMPT = """你是一位专业文稿修订师。根据审阅意见修订续写章节：
- 原文: {writer_output}
- 审阅意见: {auditor_output}

请输出修订后的完整章节，保持与前文的连贯性，针对性地改进问题。"""


def _build_write_chapter_template() -> PipelineConfig:
    """构建 builtin:write_chapter 模板 — Architect→Writer→Auditor→Reviser 四阶段链。"""
    architect = AgentRole(
        id="architect",
        name="架构师",
        system_prompt=_ARCHITECT_PROMPT,
        model=config.llm_default_model,
        temperature=None,  # None = 跟随默认 → 项目顶层温度（spec §9.2.3 温度链）
    )
    writer = AgentRole(
        id="writer",
        name="写手",
        system_prompt=_WRITER_PROMPT,
        model=config.llm_default_model,
        temperature=0.8,
    )
    auditor = AgentRole(
        id="auditor",
        name="审阅",
        system_prompt=_AUDITOR_PROMPT,
        model=config.llm_default_model,
        temperature=0.5,
    )
    reviser = AgentRole(
        id="reviser",
        name="修订",
        system_prompt=_REVISER_PROMPT,
        model=config.llm_default_model,
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
        # F4 模板数据修正（spec §5.3.2 实证）：reviser 同时依赖 writer（原文）与
        # auditor（审阅意见）——模板/节点/测试三者不一致，真相来源收敛回模板数据
        PipelineStage(
            id="reviser",
            name="修订定稿",
            agent=reviser,
            input_from=["writer", "auditor"],
        ),
    ]

    return PipelineConfig(
        name="章节写作 (4 阶段)",
        description="Architect → Writer → Auditor → Reviser 标准写作流水线",
        stages=stages,
        source="builtin",
    )


def _build_write_auto_template() -> PipelineConfig:
    """构建 builtin:write_auto 模板 — Architect→Writer→Auditor→Reviser 全自动新章节写作链。"""
    architect = AgentRole(
        id="architect",
        name="架构师",
        system_prompt=_AUTO_ARCHITECT_PROMPT,
        model=config.llm_default_model,
        temperature=None,  # None = 跟随默认 → 项目顶层温度（spec §9.2.3 温度链）
    )
    writer = AgentRole(
        id="writer",
        name="写手",
        system_prompt=_AUTO_WRITER_PROMPT,
        model=config.llm_default_model,
        temperature=0.8,
    )
    auditor = AgentRole(
        id="auditor",
        name="审阅",
        system_prompt=_AUTO_AUDITOR_PROMPT,
        model=config.llm_default_model,
        temperature=0.5,
    )
    reviser = AgentRole(
        id="reviser",
        name="修订",
        system_prompt=_AUTO_REVISER_PROMPT,
        model=config.llm_default_model,
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
        # F4 模板数据修正（spec §5.3.2 实证）：reviser 同时依赖 writer（原文）与
        # auditor（审阅意见）——模板/节点/测试三者不一致，真相来源收敛回模板数据
        PipelineStage(
            id="reviser",
            name="修订定稿",
            agent=reviser,
            input_from=["writer", "auditor"],
        ),
    ]

    return PipelineConfig(
        name="全自动写作 (4 阶段)",
        description="Architect → Writer → Auditor → Reviser 全自动新章节写作流水线（无需前文）",
        stages=stages,
        source="builtin",
    )


def _build_write_continue_template() -> PipelineConfig:
    """构建 builtin:write_continue 模板 — Writer→Auditor→Reviser 续写链（无 Architect）。"""
    writer = AgentRole(
        id="writer",
        name="写手",
        system_prompt=_CONTINUE_WRITER_PROMPT,
        model=config.llm_default_model,
        temperature=0.8,
    )
    auditor = AgentRole(
        id="auditor",
        name="审阅",
        system_prompt=_CONTINUE_AUDITOR_PROMPT,
        model=config.llm_default_model,
        temperature=0.5,
    )
    reviser = AgentRole(
        id="reviser",
        name="修订",
        system_prompt=_CONTINUE_REVISER_PROMPT,
        model=config.llm_default_model,
        temperature=0.6,
    )

    stages = [
        PipelineStage(
            id="writer",
            name="内容写作",
            agent=writer,
            output_to=["auditor"],
        ),
        PipelineStage(
            id="auditor",
            name="质量审校",
            agent=auditor,
            input_from=["writer"],
            output_to=["reviser"],
        ),
        # F4 模板数据修正（spec §5.3.2 实证）：reviser 同时依赖 writer（原文）与
        # auditor（审阅意见）——模板/节点/测试三者不一致，真相来源收敛回模板数据
        PipelineStage(
            id="reviser",
            name="修订定稿",
            agent=reviser,
            input_from=["writer", "auditor"],
        ),
    ]

    return PipelineConfig(
        name="续写 (3 阶段)",
        description="Writer → Auditor → Reviser 基于前文摘要的续写流水线",
        stages=stages,
        source="builtin",
    )


BUILTIN_TEMPLATES: dict[str, PipelineConfig] = {
    "builtin:write_chapter": _build_write_chapter_template(),
    "builtin:write_auto": _build_write_auto_template(),
    "builtin:write_continue": _build_write_continue_template(),
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
