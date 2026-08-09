"""F34 章节审计 LLM 提示词组装与输出解析纯函数层（spec §5.2/§5.3）.

依据 specs/f34-chapter-audit/spec.md §5.2：人设漂移（vs F9 角色档案）与
设定漂移（vs F10 世界观条目）两路提示词，输出严格 JSON（findings 列表，
字段见 §5.2 输出格式）；§5.3：LLM 输出解析/校验失败 → 返回 None
（service 层据此降级，不抛异常——HTTP 仍 200 + degraded 标记）。

镜像 _style_llm_analyzer.py 先例：_extract_json_fragment 同款平衡花括号
扫描（跳过字符串字面量），容忍 ```json 围栏与前后缀文字；仅依赖标准库
（json / uuid / typing）与 domain 内部模型/端口，不 import 任何框架 /
infrastructure（ADR-002/015：domain 层零框架 import）。

函数契约以 tests/unit/test_chapter_audit_llm.py 为准（RED 测试即契约）:
- build_character_drift_messages(chapter_text, characters, truncated)
- build_setting_drift_messages(chapter_text, settings, truncated)
- parse_drift_output(raw) -> list[ChapterAuditFinding] | None
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from inkflow.domain.models.chapter_audit import (
    AuditCheckType,
    AuditSeverity,
    ChapterAuditFinding,
)
from inkflow.domain.models.character import Character
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.llm_client import ChatMessage
from inkflow.domain.services._audit_context import _MAX_ENTITY_CHARS, _TRUNCATE_MARKER

_SYSTEM_PROMPT_CHARACTER = (
    "你是小说一致性审校。比对章节文本与角色档案，找出角色行为/言语/心理与"
    "档案描述冲突之处。只报明确冲突或明显疑似，不报细枝末节。\n"
    "输出严格 JSON，不要输出任何其他文字，格式：\n"
    "{\n"
    '  "findings": [\n'
    "    {\n"
    '      "check_type": "character_drift",\n'
    '      "severity": "error|warning",\n'
    '      "message": "...",\n'
    '      "suggestion": "...",\n'
    '      "ref_entity_id": "<角色UUID或null>",\n'
    '      "ref_entity_name": "...",\n'
    '      "context": "<≤200字相关片段>"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "check_type 必须为 character_drift；severity 必须为 error（明确矛盾）"
    "或 warning（明显疑似）。"
)

_SYSTEM_PROMPT_SETTING = (
    "你是小说一致性审校。比对章节文本与世界观条目，找出与设定描述冲突之处。"
    "只报明确冲突或明显疑似，不报细枝末节。\n"
    "输出严格 JSON，不要输出任何其他文字，格式：\n"
    "{\n"
    '  "findings": [\n'
    "    {\n"
    '      "check_type": "setting_drift",\n'
    '      "severity": "error|warning",\n'
    '      "message": "...",\n'
    '      "suggestion": "...",\n'
    '      "ref_entity_id": "<世界观条目UUID或null>",\n'
    '      "ref_entity_name": "...",\n'
    '      "context": "<≤200字相关片段>"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "check_type 必须为 setting_drift；severity 必须为 error（明确矛盾）"
    "或 warning（明显疑似）。"
)


def _extract_json_fragment(text: str) -> str | None:
    """从带围栏/前后缀文字的文本中提取首个 ``{...}`` 平衡片段.

    实现: 定位首个 ``{``，向后扫描花括号深度（跳过字符串字面量，含转义），
    深度归零时返回含首尾花括号的完整片段（同 F16 `_style_llm_analyzer`
    `_extract_json_fragment` 逻辑）.

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


def _format_character_profile(character: Character) -> str:
    """格式化单条角色档案（name/personality/background/goals，各 ≤500 字符）."""
    return (
        f"- 姓名：{character.name}\n"
        f"  性格：{character.personality[:_MAX_ENTITY_CHARS]}\n"
        f"  背景：{character.background[:_MAX_ENTITY_CHARS]}\n"
        f"  目标：{character.goals[:_MAX_ENTITY_CHARS]}"
    )


def _format_setting_profile(setting: WorldSetting) -> str:
    """格式化单条世界观条目（name/content，内容 ≤500 字符）."""
    return f"- 名称：{setting.name}\n  内容：{setting.content[:_MAX_ENTITY_CHARS]}"


def _chapter_section(chapter_text: str, truncated: bool) -> str:
    """章节文本小节：truncated=True 时前缀「（已截断，仅节选）」标注."""
    if truncated:
        return f"章节文本{_TRUNCATE_MARKER}：\n{chapter_text}"
    return f"章节文本：\n{chapter_text}"


def build_character_drift_messages(
    chapter_text: str,
    characters: list[Character],
    truncated: bool,
) -> list[ChatMessage]:
    """组装人设漂移检查消息（spec §5.2）— 返回 [system, user] 两条.

    Args:
        chapter_text: 章节文本（service 层已按 §5.4 截断/标注）.
        characters: 角色档案列表（每角色 name/personality/background/goals）.
        truncated: 章节文本是否已截断（True 时 user 消息含「已截断」字样）.

    Returns:
        [system 指令, user 携带档案 + 章节文本] 两条消息；档案为空仍返回两条.
    """
    profiles = "\n".join(_format_character_profile(c) for c in characters)
    user_content = f"角色档案：\n{profiles}\n\n{_chapter_section(chapter_text, truncated)}"
    return [
        ChatMessage(role="system", content=_SYSTEM_PROMPT_CHARACTER),
        ChatMessage(role="user", content=user_content),
    ]


def build_setting_drift_messages(
    chapter_text: str,
    settings: list[WorldSetting],
    truncated: bool,
) -> list[ChatMessage]:
    """组装设定漂移检查消息（spec §5.2）— 同构返回 [system, user] 两条.

    Args:
        chapter_text: 章节文本（service 层已按 §5.4 截断/标注）.
        settings: 世界观条目列表（每条 name/content）.
        truncated: 章节文本是否已截断（True 时 user 消息含「已截断」字样）.

    Returns:
        [system 指令, user 携带条目 + 章节文本] 两条消息；条目为空仍返回两条.
    """
    profiles = "\n".join(_format_setting_profile(s) for s in settings)
    user_content = f"世界观条目：\n{profiles}\n\n{_chapter_section(chapter_text, truncated)}"
    return [
        ChatMessage(role="system", content=_SYSTEM_PROMPT_SETTING),
        ChatMessage(role="user", content=user_content),
    ]


def _parse_check_type(value: Any) -> AuditCheckType | None:
    """check_type 字符串 → AuditCheckType；非字符串/非法值返回 None."""
    if not isinstance(value, str):
        return None
    try:
        return AuditCheckType(value)
    except ValueError:
        return None


def _parse_severity(value: Any) -> AuditSeverity | None:
    """severity 字符串 → AuditSeverity；非字符串/非法值返回 None."""
    if not isinstance(value, str):
        return None
    try:
        return AuditSeverity(value)
    except ValueError:
        return None


def _optional_str(value: Any) -> str | None:
    """可选字符串字段：缺省/None → ""；非字符串 → None（校验失败哨兵）."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return None
    return value


def parse_drift_output(raw: str) -> list[ChapterAuditFinding] | None:
    """解析 LLM 漂移输出（spec §5.2/§5.3）— 失败返回 None，不抛异常.

    提取首个平衡 ``{...}`` 片段（容忍 ```json 围栏与前后缀文字）→ json.loads
    → 校验 findings 列表与每条字段（check_type/severity 枚举合法、message
    非空、ref_entity_id 为 UUID 字符串或 null、其余字段缺省为空串）；
    任一解析/校验失败 → 整体 None（service 层据此降级，重试由 service 层做）.

    Args:
        raw: LLM 原始输出文本.

    Returns:
        映射后的 ChapterAuditFinding 列表（空 findings 返回 []）；
        任何解析/校验失败返回 None.
    """
    fragment = _extract_json_fragment(raw)
    if fragment is None:
        return None
    try:
        payload: Any = json.loads(fragment)
        if not isinstance(payload, dict):
            return None
        findings = payload.get("findings")
        if not isinstance(findings, list):
            return None
        result: list[ChapterAuditFinding] = []
        for item in findings:
            if not isinstance(item, dict):
                return None
            check_type = _parse_check_type(item.get("check_type"))
            if check_type is None:
                return None
            severity = _parse_severity(item.get("severity"))
            if severity is None:
                return None
            message = item.get("message")
            if not isinstance(message, str) or not message:
                return None
            suggestion = _optional_str(item.get("suggestion"))
            if suggestion is None:
                return None
            ref_entity_name = _optional_str(item.get("ref_entity_name"))
            if ref_entity_name is None:
                return None
            context = _optional_str(item.get("context"))
            if context is None:
                return None
            ref_entity_id: uuid.UUID | None = None
            raw_id = item.get("ref_entity_id")
            if raw_id is not None:
                if not isinstance(raw_id, str):
                    return None
                try:
                    ref_entity_id = uuid.UUID(raw_id)
                except ValueError:
                    return None
            result.append(
                ChapterAuditFinding(
                    check_type=check_type,
                    severity=severity,
                    message=message,
                    suggestion=suggestion,
                    ref_entity_id=ref_entity_id,
                    ref_entity_name=ref_entity_name,
                    context=context,
                )
            )
    except (ValueError, TypeError):
        # 兜底：任何解析/校验异常都按降级语义返回 None（spec §5.3，不抛异常）
        return None
    else:
        return result
