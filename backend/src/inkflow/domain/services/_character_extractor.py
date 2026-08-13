"""F9 角色提取管线 — 模板渲染 → LLM → JSON 解析 → 修复重试 → 合并落库.

依据: specs/f9-character-service/spec.md §5（AI 提取模式，F10-F13 复用骨架）。
遵循 ADR-015: 领域层零 LangChain import，LLM / 模板 / 仓储均通过
Protocol 注入（LLMClientProtocol / PromptTemplateProtocol /
CharacterRepositoryProtocol），测试中注入 Mock。

管线步骤（§5.1）:
① 校验项目存在 —— 由调用方 CharacterService 负责，extractor 不重复
② 渲染 character_extract.yaml（PromptManager，变量 {text}）
③ LLMClient.chat(model or project.config.model, temperature=0.2)
④ 解析 JSON → Pydantic schema 校验（ExtractedCharacter / ExtractedRelation）
   → 非法条目跳过 + warning
⑤ 修复式重试 ≤ 2 次（附错误信息）→ 仍失败 → CharacterExtractionError
⑥ 合并落库（§5.4）: 角色按 (project_id, name) 匹配活动角色 →
   存在=更新(非空覆盖) / 不存在=创建（v1.1 真删：无「软删同名」分支）;
   关系名称解析为 id → 按 (from, to, type) upsert
⑦ 返回 CharacterExtractionResult
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from inkflow.domain.models.character import (
    Character,
    CharacterExtractionResult,
    CharacterExtractRequest,
    CharacterRelation,
    ExtractedCharacter,
    ExtractedRelation,
)
from inkflow.domain.ports.character_errors import CharacterExtractionError
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol

logger = logging.getLogger(__name__)

_TEMPLATE_NAME = "character_extract"
"""提取模板名（infrastructure/llm/templates/character_extract.yaml）。"""

_MAX_PARSE_RETRIES = 2
"""修复式重试次数上限（共 1 次原始 + 2 次修复 = 3 次尝试）。"""

_TEMPERATURE = 0.2
"""结构化输出固定低温（spec §5.5，不对外暴露）。"""


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1 `_to_int_id` 模式）。"""
    if isinstance(value, uuid.UUID):
        return value.int
    return value


def _extract_json_fragment(text: str) -> str | None:
    """从带围栏/前后缀文字的文本中提取首个 ``{...}`` 平衡片段.

    实现: 定位首个 ``{``，向后扫描花括号深度（跳过字符串字面量），
    深度归零时返回含首尾花括号的完整片段。

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


def _first_error(err: ValidationError) -> str:
    """提取 Pydantic 校验错误的第一条可读信息。"""
    errors = err.errors()
    if errors:
        loc = ".".join(str(p) for p in errors[0]["loc"])
        return f"{loc}: {errors[0]['msg']}"
    return str(err)


def _normalize_relation_item(item: Any) -> Any:
    """将模板约定的 from/to/type 键映射到模型字段名.

    character_extract.yaml 要求 LLM 输出 ``{"from": ..., "to": ...,
    "type": ...}``，而 ExtractedRelation 模型字段为
    from_name / to_name / relation_type（B1 已定稿）；解析时在此归一化。

    Args:
        item: 原始关系条目.

    Returns:
        归一化后的条目（键名已映射；非 dict 原样返回）.
    """
    if not isinstance(item, dict):
        return item
    key_map = {"from": "from_name", "to": "to_name", "type": "relation_type"}
    normalized = dict(item)
    for source, target in key_map.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized.pop(source)
    return normalized


def _build_fix_prompt(error_detail: str) -> str:
    """构建修复式重试 Prompt（原输出已在对话历史中）。"""
    return (
        "上一版输出无法解析为合法 JSON：\n"
        f"{error_detail}\n"
        "请只输出 JSON，不要包含任何其他文字（不要使用代码块围栏）。"
    )


@dataclass
class _ParseOutcome:
    """LLM 输出解析结果 — 结构失败时 error 非空，条目级失败进 warnings。"""

    characters: list[ExtractedCharacter] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        """是否结构解析成功（可进入合并阶段）。"""
        return not self.error


class CharacterExtractor:
    """角色提取管线服务（spec §5.1）。

    依赖全部通过构造函数注入（Protocol 类型），不感知基础设施具体类:

    Args:
        llm_client: LLM 客户端（F5）.
        prompt_manager: Prompt 模板管理器（F5）.
        repository: 角色/关系仓储端口（B1）.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClientProtocol,
        prompt_manager: PromptTemplateProtocol,
        repository: CharacterRepositoryProtocol,
    ) -> None:
        self._llm = llm_client
        self._prompts = prompt_manager
        self._repo = repository

    # ── 公共入口 ────────────────────────────────────────────────

    async def extract(
        self,
        request: CharacterExtractRequest,
        *,
        default_model: str,
    ) -> CharacterExtractionResult:
        """执行角色提取管线（§5.1 步骤 ②-⑦）。

        Args:
            request: 提取请求（project_id / text / 可选 model 覆盖）.
            default_model: 项目默认模型（project.config.model，
                由调用方 CharacterService 校验项目存在后传入）.

        Returns:
            合并落库后的提取报告.

        Raises:
            LLMRequestError: LLM 调用失败（透传，不消耗解析重试）.
            CharacterExtractionError: 3 次尝试（1 原始 + 2 修复）均无法解析.
        """
        model = request.model or default_model

        # ② 渲染模板（变量: text）
        template = self._prompts.load(_TEMPLATE_NAME)
        rendered = self._prompts.render(template, {"text": request.text})
        messages = [ChatMessage(role=m["role"], content=m["content"]) for m in rendered.messages]

        # ③④⑤ 调用 LLM + 解析 + 修复式重试（≤ 2 次）
        last_raw = ""
        outcome = _ParseOutcome()
        for retry_count in range(_MAX_PARSE_RETRIES + 1):
            # 传消息列表副本，避免客户端变异影响重试历史记录
            # LLM 调用失败透传，不消耗解析重试（§5.1 模式要点 4）
            response = await self._llm.chat(list(messages), model=model, temperature=_TEMPERATURE)

            last_raw = response.content
            outcome = self._parse_output(last_raw)
            if outcome.ok:
                break

            if retry_count >= _MAX_PARSE_RETRIES:
                raise CharacterExtractionError(
                    raw_output=last_raw[:500],
                    detail=(
                        f"{_MAX_PARSE_RETRIES} 次修复重试后仍无法解析为合法 JSON"
                        f"（最后错误: {outcome.error}）"
                    ),
                )

            messages.append(ChatMessage(role="assistant", content=last_raw))
            messages.append(ChatMessage(role="user", content=_build_fix_prompt(outcome.error)))

        # ⑥⑦ 合并落库 + 返回结果
        return await self._merge(
            request=request,
            characters=outcome.characters,
            relations=outcome.relations,
            item_warnings=outcome.warnings,
            model=model,
        )

    # ── 解析 ────────────────────────────────────────────────────

    def _parse_output(self, raw: str) -> _ParseOutcome:
        """解析 LLM 输出: 结构失败 → error；条目级非法 → 跳过 + warning。"""
        fragment = _extract_json_fragment(raw)
        if fragment is None:
            return _ParseOutcome(error="未找到平衡的 JSON 对象片段")
        try:
            payload: Any = json.loads(fragment)
        except json.JSONDecodeError as e:
            return _ParseOutcome(error=f"JSON 语法错误: {e.msg}（位置 {e.pos}）")
        if not isinstance(payload, dict):
            return _ParseOutcome(error="JSON 顶层必须是对象")

        raw_chars = payload.get("characters")
        raw_rels = payload.get("relations")
        if not isinstance(raw_chars, list):
            return _ParseOutcome(error="缺少 characters 列表")
        if not isinstance(raw_rels, list):
            return _ParseOutcome(error="缺少 relations 列表")

        warnings: list[str] = []
        characters: list[ExtractedCharacter] = []
        for index, item in enumerate(raw_chars):
            try:
                characters.append(ExtractedCharacter.model_validate(item))
            except ValidationError as e:
                warnings.append(f"跳过非法角色条目 #{index + 1}: {_first_error(e)}")

        relations: list[ExtractedRelation] = []
        for index, item in enumerate(raw_rels):
            try:
                relations.append(ExtractedRelation.model_validate(_normalize_relation_item(item)))
            except ValidationError as e:
                warnings.append(f"跳过非法关系条目 #{index + 1}: {_first_error(e)}")

        return _ParseOutcome(characters=characters, relations=relations, warnings=warnings)

    # ── 合并落库（§5.4）────────────────────────────────────────

    async def _merge(
        self,
        *,
        request: CharacterExtractRequest,
        characters: list[ExtractedCharacter],
        relations: list[ExtractedRelation],
        item_warnings: list[str],
        model: str,
    ) -> CharacterExtractionResult:
        """合并落库: 角色按 (project_id, name) 匹配，关系名称解析后按键 upsert。"""
        warnings = list(item_warnings)
        pid_int = _to_int_id(request.project_id)
        name_to_char: dict[str, Character] = {}

        if not characters:
            warnings.append("未从文本中提取到任何角色")

        created: list[Character] = []
        updated: list[Character] = []
        for ec in characters:
            existing = await self._repo.get_by_name(pid_int, ec.name)
            if existing is None:
                now = _utcnow()
                new_char = await self._repo.add(
                    Character(
                        id=uuid.uuid4(),
                        project_id=request.project_id,
                        name=ec.name,
                        personality=ec.personality or "",
                        background=ec.background or "",
                        goals=ec.goals or "",
                        created_at=now,
                        updated_at=now,
                    )
                )
                created.append(new_char)
                name_to_char[ec.name] = new_char
                continue

            merged = _merge_character_fields(existing, ec)
            if merged is None:
                # 幂等: 非空覆盖后字段无变化 → 不更新、不计入 updated
                name_to_char[ec.name] = existing
                continue
            persisted = await self._repo.update(merged)
            updated.append(persisted)
            name_to_char[ec.name] = persisted

        relations_created, relations_updated = await self._merge_relations(
            request=request,
            pid_int=pid_int,
            relations=relations,
            name_to_char=name_to_char,
            warnings=warnings,
        )

        for w in warnings:
            logger.warning("角色提取警告: %s", w)

        return CharacterExtractionResult(
            created=created,
            updated=updated,
            relations_created=relations_created,
            relations_updated=relations_updated,
            warnings=warnings,
            model=model,
        )

    async def _merge_relations(
        self,
        *,
        request: CharacterExtractRequest,
        pid_int: int,
        relations: list[ExtractedRelation],
        name_to_char: dict[str, Character],
        warnings: list[str],
    ) -> tuple[list[CharacterRelation], list[CharacterRelation]]:
        """关系合并: 名称解析为 id → 按 (from, to, type) 键 upsert。"""
        created: list[CharacterRelation] = []
        updated: list[CharacterRelation] = []

        for er in relations:
            if er.from_name == er.to_name:
                warnings.append(f"关系 {er.from_name} → {er.to_name} 为自环，已跳过")
                continue

            from_char = await self._resolve_character(pid_int, er.from_name, name_to_char)
            to_char = await self._resolve_character(pid_int, er.to_name, name_to_char)
            if from_char is None or to_char is None:
                warnings.append(f"关系 {er.from_name} → {er.to_name} 的角色无法解析，已跳过")
                continue

            existing_rel = await self._repo.get_relation_by_key(
                _to_int_id(from_char.id), _to_int_id(to_char.id), er.relation_type
            )
            if existing_rel is None:
                now = _utcnow()
                new_rel = await self._repo.add_relation(
                    CharacterRelation(
                        id=uuid.uuid4(),
                        project_id=request.project_id,
                        from_character_id=from_char.id,
                        to_character_id=to_char.id,
                        relation_type=er.relation_type,
                        description=er.description or "",
                        created_at=now,
                        updated_at=now,
                    )
                )
                created.append(new_rel)
                continue

            # 同键已存在: 提取描述非空且不同 → 更新；否则幂等跳过
            if er.description and er.description != existing_rel.description:
                merged = CharacterRelation(
                    id=existing_rel.id,
                    project_id=existing_rel.project_id,
                    from_character_id=existing_rel.from_character_id,
                    to_character_id=existing_rel.to_character_id,
                    relation_type=existing_rel.relation_type,
                    description=er.description,
                    created_at=existing_rel.created_at,
                    updated_at=_utcnow(),
                )
                updated.append(await self._repo.update_relation(merged))

        return created, updated

    # ── 私有辅助 ────────────────────────────────────────────────

    async def _resolve_character(
        self,
        pid_int: int,
        name: str,
        name_to_char: dict[str, Character],
    ) -> Character | None:
        """将角色名解析为角色实体: 先查本次提取产物，再查库中角色。"""
        char = name_to_char.get(name)
        if char is not None:
            return char
        return await self._repo.get_by_name(pid_int, name)


def _merge_character_fields(existing: Character, ec: ExtractedCharacter) -> Character | None:
    """非空字段覆盖合并（personality/background/goals 独立判断）.

    无任何变化时返回 None（幂等跳过，不更新 updated_at）；否则
    保留 existing 的 id / group_id / extra / 时间戳等无关字段。

    Args:
        existing: 库中同名角色.
        ec: LLM 提取出的角色.

    Returns:
        合并后的完整角色；无变化返回 None.
    """
    new_personality = ec.personality or existing.personality
    new_background = ec.background or existing.background
    new_goals = ec.goals or existing.goals
    if (
        new_personality == existing.personality
        and new_background == existing.background
        and new_goals == existing.goals
    ):
        return None
    return Character(
        id=existing.id,
        project_id=existing.project_id,
        name=existing.name,
        personality=new_personality,
        background=new_background,
        goals=new_goals,
        group_id=existing.group_id,
        extra=existing.extra,
        created_at=existing.created_at,
        updated_at=_utcnow(),
    )
