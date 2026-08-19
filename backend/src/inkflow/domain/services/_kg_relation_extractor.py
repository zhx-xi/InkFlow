"""F48 知识图谱关系提取 LLM 辅助 — prompt 构建 + 顶层 JSON 数组容错解析.

AI 提取输出契约为顶层 JSON 数组（spec f48 §5.5.4）:
[{from_name, from_type, to_name, to_type, relation_type, description}]。
本私有模块承载 prompt 与数组片段解析，供 RelationExtractionService 复用
（同 F14 `_character_extractor.py` 私有模块命名惯例）。
"""

from __future__ import annotations

import json
from typing import Any

from inkflow.domain.ports.llm_client import ChatMessage

_SYSTEM_PROMPT = (
    "你是小说知识图谱关系抽取器。从给定章节正文中抽取实体间关系，只输出 JSON 数组。\n"
    "每个数组元素必须包含: from_name, from_type, to_name, to_type, relation_type, description。\n"
    "from_type/to_type 只允许: character, world, outline, timeline, foreshadow。\n"
    "不要输出数组以外的任何文字。"
)

_ENTITY_TYPE_VALUES = frozenset({"character", "world", "outline", "timeline", "foreshadow"})

_REQUIRED_KEYS = ("from_name", "from_type", "to_name", "to_type", "relation_type")


def build_kg_relation_messages(text: str) -> list[ChatMessage]:
    """构建关系提取对话消息（系统约束 + 章节正文）。"""
    return [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(role="user", content=f"章节正文:\n{text}"),
    ]


def build_fix_prompt(error: str) -> str:
    """构建修复重试提示（附上次解析错误信息）。"""
    return (
        "上次输出无法解析为合法 JSON 数组：\n"
        f"{error}\n"
        "请只输出 JSON 数组，不要包含任何其他文字。"
    )


def _extract_array_fragment(text: str) -> str | None:
    """从带围栏/前后缀文本中提取首个平衡的 JSON 数组片段."""

    start = text.find("[")
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
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_kg_relations(raw: str) -> tuple[list[dict[str, Any]] | None, str]:
    """解析 LLM 输出的关系数组.

    Args:
        raw: LLM 原始输出（可能带围栏/前后缀文字）.

    Returns:
        (关系字典列表, 错误信息)；成功时错误信息为空串，失败时列表为 None.
    """

    fragment = _extract_array_fragment(raw)
    if fragment is None:
        return None, "未找到平衡的 JSON 数组片段"
    try:
        payload: list[Any] = json.loads(fragment)
    except json.JSONDecodeError as exc:
        return None, f"JSON 语法错误: {exc.msg}（位置 {exc.pos}）"
    if not isinstance(payload, list):  # pragma: no cover
        return None, "JSON 顶层必须是数组"
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            return None, f"第 {index + 1} 条关系不是对象"
        missing = [key for key in _REQUIRED_KEYS if key not in item]
        if missing:
            return None, f"第 {index + 1} 条关系缺少字段: {missing}"
        for key in ("from_type", "to_type"):
            if item[key] not in _ENTITY_TYPE_VALUES:
                return None, f"第 {index + 1} 条关系 {key} 非法: {item[key]}"
    return payload, ""
