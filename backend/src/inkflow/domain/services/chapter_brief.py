"""章 brief（writer system_prompt）单一构造点 — #1185 三轨副本收敛.

背景（#1178/#1179/#1182/#1183）：book 写作三轨各自**逐字复制**一份硬编码 brief：

- ``BookService._build_chapter_brief``（T2 静态书级轨，`domain/services/book_service.py`）
- ``BookVolumePipeline._build_chapter_brief``（T3 卷级轨，`infrastructure/agent/book_pipeline.py`）
- ``BookAgenticPipeline._build_chapter_brief``（T4 自主轨，``agent/book_agentic_pipeline.py``）

三副本共同缺陷：角色恒占位符（「主角自定」/「见角色档案（plan.character_ids）」）、
项目 writing_style 恒不读（只有常量祈使句）、章级 writing_requirements 恒缺席、
目标字数恒缺席、F6 设定上下文（角色/世界观/未回收伏笔）恒缺席。

本模块是**唯一实现**（domain 层纯函数，可被 domain 与 infrastructure 同时依赖）；
三轨的 `_build_chapter_brief` 保留各自签名做适配并委托至此，不再各留一份拷贝。

注入六项（全部来自真实数据源；无数据 → **显式缺席**，不伪造占位符）：

1. 章节大纲切片   ``chapter.description``
2. 角色/世界观/伏笔   ``context``（装配层 F6 ``ContextService`` 产出文本）
3. 章节写作要求   ``chapter.writing_requirements``（章级，优先于项目级）
4. 项目写作风格   ``project_style``（``project.config.writing_style``）
5. 目标字数       ``default_words``（``project.config.default_words``）
6. 审校意见       ``audit_issues``（仅 T4 自主轨，修订必改）

依据: specs/f44-book-orchestrator/spec.md §5.1；
    .hermes/audit-writing-chain-20260915.md P0-2 / P1-2 / P1-5 / P1-6。
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from inkflow.domain.models.writing_plan import WritingPlan

#: 装配层 F6 上下文回调：(project_id, chapter) → str；同步/异步返回均容忍（鸭子类型）.
ContextBuilder = Callable[[uuid.UUID, object], Awaitable[str] | str]

#: 项目配置回调：project_id → ProjectConfig（或同形 dict）| None.
ProjectConfigGetter = Callable[[uuid.UUID], Awaitable[object]]

#: 项目级风格缺席时的通用祈使句（保留「风格/偏好」语义，不省略段）。
_DEFAULT_STYLE_HINT = "遵循项目写作风格与用户偏好（偏好优先于通用文风）。"


def _chapter_value(chapter: object, key: str) -> Any:
    """章取值 — dict（ChapterDict）与 Outline 领域对象双形态统一（三轨输入形态不同）."""
    if isinstance(chapter, dict):
        return chapter.get(key)
    return getattr(chapter, key, None)


def _text(value: object) -> str:
    """非空文本提取（None / 非 str → 空串）."""
    return value.strip() if isinstance(value, str) else ""


def _config_value(cfg: object, key: str) -> object:
    """配置取值 — ProjectConfig 领域对象与 dict 双形态（测试装配与真实装配形态不同）."""
    if isinstance(cfg, dict):
        return cfg.get(key)
    return getattr(cfg, key, None)


def _writing_requirements(chapter: object) -> str:
    """章级写作要求（#1017 字段）：直接键优先，回退 ``extra["writing_requirements"]``.

    Outline 轨道（T2）与章 dict 轨道（T3/T4）同键访问——F8：字段零 schema 改动接入。
    """
    direct = _text(_chapter_value(chapter, "writing_requirements"))
    if direct:
        return direct
    extra = _chapter_value(chapter, "extra")
    if isinstance(extra, dict):
        return _text(extra.get("writing_requirements"))
    return ""


def build_chapter_brief(
    plan: WritingPlan,
    chapter: object,
    *,
    context: str = "",
    project_style: str = "",
    default_words: int | None = None,
    audit_issues: list[str] | None = None,
) -> str:
    """构造章 brief（writer system_prompt）— 三轨唯一实现（#1185）.

    Args:
        plan: 书级计划（仅作契约形参；缺数据时 brief 显式缺席，不落占位符）.
        chapter: 章 Outline 领域对象（T2 轨）或 ChapterDict（T3/T4 轨）.
        context: F6 ContextService 产出文本（角色/世界观/未回收伏笔）；空 = 未接线.
        project_style: 项目级 ``config.writing_style`` 实值；空 = 通用文风祈使句.
        default_words: 项目级 ``config.default_words`` 目标字数；None = 不注入.
        audit_issues: 审校意见（T4 轨修订必改）；空 = 不注入.

    Returns:
        段式 brief 文本（大纲 → 设定注入 → 章级要求 → 风格 → 字数 → 审校意见）.
    """
    lines = [
        "你是一位小说章节写作者。请严格按大纲切片撰写本章正文。",
        f"【章节大纲】{_text(_chapter_value(chapter, 'description'))}",
    ]
    if _text(context):
        lines.append(f"【设定注入】\n{context.strip()}")
    requirement = _writing_requirements(chapter)
    if requirement:
        lines.append(f"【章节写作要求（章级优先于项目风格）】{requirement}")
    lines.append(f"【写作风格】{_text(project_style) or _DEFAULT_STYLE_HINT}")
    if default_words is not None:
        lines.append(f"【目标字数】{default_words}")
    issues = [issue for issue in (audit_issues or []) if issue]
    if issues:
        lines.append("【审校意见（修订必改）】" + "；".join(issues))
    return "\n".join(lines)


async def resolve_brief_setting(
    context_builder: ContextBuilder | None,
    project_config: object | None,
    plan: WritingPlan,
    chapter: object,
) -> dict[str, Any]:
    """解析章 brief 的装配层注入参数（context / project_style / default_words）.

    Args:
        context_builder: F6 上下文回调（装配层注入）；None = 未接线 → context 恒空
            （brief 显式缺席，**不伪造「见角色档案」占位符**，见 #1185 守护用例）.
        project_config: **已解析**的项目配置（ProjectConfig 或同形 dict）；
            None = 无项目级配置 → 风格/字数缺席（调用方负责复用已解析配置，避免重复取值）.
        plan: 书级计划（取 project_id）.
        chapter: 章对象（Outline 或 ChapterDict；F6 按章取上下文）.

    Returns:
        `build_chapter_brief` 的关键字参数字典。
    """
    context = ""
    if context_builder is not None:
        raw: object = context_builder(plan.project_id, chapter)
        if inspect.isawaitable(raw):
            resolved: object = await raw
            context = str(resolved or "")
        else:
            context = str(raw or "")
    project_style = ""
    default_words: int | None = None
    if project_config is not None:
        project_style = _text(_config_value(project_config, "writing_style"))
        raw_words = _config_value(project_config, "default_words")
        default_words = raw_words if isinstance(raw_words, int) else None
    return {
        "context": context,
        "project_style": project_style,
        "default_words": default_words,
    }
