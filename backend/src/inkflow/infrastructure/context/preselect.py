"""上下文 Agent 预选实现 — 一次 LLM 调用按本章大纲挑相关条目（#1379）.

依据: issue #1379（方案 A）. 骨架镜像 `domain/services/_style_llm_analyzer.py`
的「模板渲染 → LLM → JSON 解析」，但**不做修复式重试**——预选是增强项，
失败即回退全选（与既有「全选」行为等价），重试只会放大用户的等待延迟。

领域层零 LangChain：本类实现 `PreselectFn` 签名（见 context_service），
经 `api/deps.py` 注入 `ContextService`；LLM / 模板均通过 Protocol 依赖。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from inkflow.domain.models.context import ContextItem, ContextOverride, ContextSourceType
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol

_TEMPLATE_NAME = "context_preselect"
"""Prompt 模板名（infrastructure/i18n/prompts/{zh,en}/context_preselect.yaml）。"""

_TEMPERATURE = 0.2
"""结构化输出固定低温（同 style / timeline 提取先例）。"""

_MAX_CANDIDATE_CHARS = 120
"""单条候选文本截断上限（控制 prompt 体积；候选 content 多为名 + 简介）。"""

_LABELS: dict[ContextSourceType, str] = {
    ContextSourceType.CHARACTER_SETTING: "角色",
    ContextSourceType.WORLD_SETTING: "世界观",
    ContextSourceType.FORESHADOWING: "伏笔",
}
"""候选清单一节标题。"""

_ID_KEYS: dict[ContextSourceType, str] = {
    ContextSourceType.CHARACTER_SETTING: "character_id",
    ContextSourceType.WORLD_SETTING: "world_setting_id",
    ContextSourceType.FORESHADOWING: "foreshadowing_id",
}
"""来源 → metadata 中的 id 键（与 `context_service._apply_override` 同口径）。"""


class LlmContextPreselector:
    """按本章大纲预选相关上下文条目（#1379）.

    依赖经构造函数注入（Protocol 类型），不感知基础设施具体实现:

    Args:
        llm_client: LLM 客户端（F5）.
        prompt_manager: Prompt 模板管理器（F5）.
        temperature: 采样温度（缺省 0.2，结构化输出低温）.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClientProtocol,
        prompt_manager: PromptTemplateProtocol,
        temperature: float = _TEMPERATURE,
    ) -> None:
        self._llm = llm_client
        self._prompts = prompt_manager
        self._temperature = temperature

    async def __call__(
        self,
        candidates: list[ContextItem],
        outline_text: str,
        writing_requirements: str,
        model: str,
    ) -> ContextOverride:
        """渲染模板 → 一次 LLM 调用 → 解析三类 id 子集.

        Args:
            candidates: 三类候选条目（混合列表）.
            outline_text: 本章大纲文本.
            writing_requirements: 本章写作要求.
            model: 目标模型名（provider/model_name）.

        Returns:
            预选出的三类 id（未经候选集过滤，过滤在服务侧）.

        Raises:
            LLMRequestError: LLM 调用失败（服务侧回退全选）.
            ValueError: 输出未含平衡 JSON 对象 / 语法错误 / 顶层非对象（服务侧回退全选）.
        """
        template = self._prompts.load(_TEMPLATE_NAME)
        rendered = self._prompts.render(
            template,
            {
                "outline": outline_text,
                "requirements": writing_requirements,
                "candidates": _render_candidates(candidates),
            },
        )
        messages = [ChatMessage(role=m["role"], content=m["content"]) for m in rendered.messages]
        response = await self._llm.chat(list(messages), model=model, temperature=self._temperature)
        return _parse_picked(response.content)


def _render_candidates(candidates: list[ContextItem]) -> str:
    """候选条目清单 — 按类别分组，每条「- id=<uuid> <名：简介>」（id 供 LLM 复述选择）.

    Args:
        candidates: 三类候选条目（混合列表）.

    Returns:
        分组清单文本；无有效条目返回空串.
    """
    grouped: dict[ContextSourceType, list[str]] = {source: [] for source in _LABELS}
    for item in candidates:
        lines = grouped.get(item.source)
        if lines is None:
            continue
        raw_id = str(item.metadata.get(_ID_KEYS[item.source], ""))
        if not raw_id:
            continue
        summary = item.content[:_MAX_CANDIDATE_CHARS]
        lines.append(f"- id={raw_id} {summary}")
    sections = [
        f"[{_LABELS[source]}]\n" + "\n".join(lines) for source, lines in grouped.items() if lines
    ]
    return "\n\n".join(sections)


def _parse_picked(raw: str) -> ContextOverride:
    """解析 LLM 输出为三类 id（容忍代码块围栏 / 前后缀文字）.

    Args:
        raw: LLM 原始输出.

    Returns:
        三类 id（缺失字段 / 非法项按空处理，不视为失败）.

    Raises:
        ValueError: 未找到平衡 JSON 对象片段 / JSON 语法错误 / 顶层非对象.
    """
    fragment = _extract_json_fragment(raw)
    if fragment is None:
        raise ValueError("LLM 输出未包含平衡的 JSON 对象片段")
    payload: Any = json.loads(fragment)  # JSONDecodeError 是 ValueError 子类，直接透传
    if not isinstance(payload, dict):
        raise ValueError("LLM 输出顶层必须是 JSON 对象")  # noqa: TRY004  # LLM 数据非法（非调用方类型错）
    return ContextOverride(
        character_ids=_parse_id_list(payload.get("character_ids")),
        world_ids=_parse_id_list(payload.get("world_ids")),
        foreshadowing_ids=_parse_id_list(payload.get("foreshadowing_ids")),
    )


def _parse_id_list(value: Any) -> list[uuid.UUID]:
    """宽松解析 id 列表 — 非 list / 非字符串项 / 非法 UUID 一律跳过.

    Args:
        value: LLM 输出的某类字段原值.

    Returns:
        合法 uuid 列表（保持出现顺序）.
    """
    if not isinstance(value, list):
        return []
    ids: list[uuid.UUID] = []
    for entry in value:
        if not isinstance(entry, str):
            continue
        try:
            ids.append(uuid.UUID(entry))
        except ValueError:
            continue
    return ids


def _extract_json_fragment(text: str) -> str | None:
    """从带围栏 / 前后缀文字的文本中提取首个 ``{...}`` 平衡片段.

    实现与 `domain/services/_style_llm_analyzer._extract_json_fragment` 同策略
    （定位首个 ``{`` 后按花括号深度扫描、跳过字符串字面量）；此处独立一份以避免
    基础设施层反向依赖领域服务的私有函数。

    Args:
        text: LLM 原始输出.

    Returns:
        平衡的 JSON 对象片段；未找到返回 None.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None
