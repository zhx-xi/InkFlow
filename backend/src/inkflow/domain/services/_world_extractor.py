"""F10 世界观提取管线 — 模板渲染 → LLM → JSON 解析 → 修复重试 → 合并落库.

依据: specs/f10-world-service/spec.md §5（AI 提取模式，同 F9 §5，
无 relations 步骤）。实现为 F9 `_character_extractor.py` 的镜像，
仅替换领域实体（WorldSetting ↔ Character）与模板名
（world_extract ↔ character_extract），不重新设计管线。
遵循 ADR-015: 领域层零 LangChain import，LLM / 模板 / 仓储均通过
Protocol 注入（LLMClientProtocol / PromptTemplateProtocol /
WorldRepositoryProtocol），测试中注入 Mock。

管线步骤（§5.1）:
① 校验项目存在 —— 由调用方 WorldService 负责，extractor 不重复
② 渲染 world_extract.yaml（PromptManager，变量 {text}）
③ LLMClient.chat(model or project.config.model, temperature=0.2)
④ 解析 JSON → Pydantic schema 校验（ExtractedWorldSetting）
   → 非法条目跳过 + warning
⑤ 修复式重试 ≤ 2 次（附错误信息）→ 仍失败 → WorldExtractionError
⑥ 合并落库（§5.4）: 条目按 (project_id, name) 匹配活动条目 →
   存在=更新(非空覆盖) / 不存在=创建（软删同名 → 新建 + warning）
⑦ 返回 WorldExtractionResult
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from inkflow.domain.models.world import (
    ExtractedWorldSetting,
    WorldExtractionResult,
    WorldExtractRequest,
    WorldSetting,
)
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol
from inkflow.domain.ports.world_errors import WorldExtractionError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol

logger = logging.getLogger(__name__)

_TEMPLATE_NAME = "world_extract"
"""提取模板名（infrastructure/llm/templates/world_extract.yaml）。"""

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

    world_settings: list[ExtractedWorldSetting] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        """是否结构解析成功（可进入合并阶段）。"""
        return not self.error


class WorldExtractor:
    """世界观提取管线服务（spec §5.1）。

    依赖全部通过构造函数注入（Protocol 类型），不感知基础设施具体类:

    Args:
        llm_client: LLM 客户端（F5）.
        prompt_manager: Prompt 模板管理器（F5）.
        repository: 世界观条目仓储端口（B1）.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClientProtocol,
        prompt_manager: PromptTemplateProtocol,
        repository: WorldRepositoryProtocol,
    ) -> None:
        self._llm = llm_client
        self._prompts = prompt_manager
        self._repo = repository

    # ── 公共入口 ────────────────────────────────────────────────

    async def extract(
        self,
        request: WorldExtractRequest,
        *,
        default_model: str,
    ) -> WorldExtractionResult:
        """执行世界观提取管线（§5.1 步骤 ②-⑦）。

        Args:
            request: 提取请求（project_id / text / 可选 model 覆盖）.
            default_model: 项目默认模型（project.config.model，
                由调用方 WorldService 校验项目存在后传入）.

        Returns:
            合并落库后的提取报告.

        Raises:
            LLMRequestError: LLM 调用失败（透传，不消耗解析重试）.
            WorldExtractionError: 3 次尝试（1 原始 + 2 修复）均无法解析.
        """
        model = request.model or default_model

        # ② 渲染模板（变量: text）
        template = self._prompts.load(_TEMPLATE_NAME)
        rendered = self._prompts.render(template, {"text": request.text})
        messages = [ChatMessage(role=m["role"], content=m["content"]) for m in rendered.messages]

        # ③④⑤ 调用 LLM + 解析 + 修复式重试（≤ 2 次）
        retry_count = 0
        last_raw = ""
        outcome = _ParseOutcome()
        for _ in range(_MAX_PARSE_RETRIES + 1):
            try:
                # 传消息列表副本，避免客户端变异影响重试历史记录
                response = await self._llm.chat(
                    list(messages), model=model, temperature=_TEMPERATURE
                )
            except LLMRequestError:
                raise  # LLM 调用失败透传，不消耗解析重试（§5.1 模式要点 4）

            last_raw = response.content
            outcome = self._parse_output(last_raw)
            if outcome.ok:
                break

            retry_count += 1
            if retry_count > _MAX_PARSE_RETRIES:
                raise WorldExtractionError(
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
            world_settings=outcome.world_settings,
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

        raw_settings = payload.get("world_settings")
        if not isinstance(raw_settings, list):
            return _ParseOutcome(error="缺少 world_settings 列表")

        warnings: list[str] = []
        world_settings: list[ExtractedWorldSetting] = []
        for index, item in enumerate(raw_settings):
            try:
                world_settings.append(ExtractedWorldSetting.model_validate(item))
            except ValidationError as e:
                warnings.append(f"跳过非法条目 #{index + 1}: {_first_error(e)}")

        return _ParseOutcome(world_settings=world_settings, warnings=warnings)

    # ── 合并落库（§5.4）────────────────────────────────────────

    async def _merge(
        self,
        *,
        request: WorldExtractRequest,
        world_settings: list[ExtractedWorldSetting],
        item_warnings: list[str],
        model: str,
    ) -> WorldExtractionResult:
        """合并落库: 条目按 (project_id, name) 匹配活动条目，同名=同一世界观条目。"""
        warnings = list(item_warnings)
        pid_int = _to_int_id(request.project_id)

        if not world_settings:
            warnings.append("未从文本中提取到任何世界观条目")

        created: list[WorldSetting] = []
        updated: list[WorldSetting] = []
        for es in world_settings:
            existing = await self._repo.get_by_name(pid_int, es.name)
            if existing is None:
                if await self._has_soft_deleted_same_name(pid_int, es.name):
                    warnings.append(f"存在已删除的同名条目档案「{es.name}」，已新建条目")
                now = _utcnow()
                new_setting = await self._repo.add(
                    WorldSetting(
                        id=uuid.uuid4(),
                        project_id=request.project_id,
                        name=es.name,
                        category=es.category or "",
                        content=es.content or "",
                        created_at=now,
                        updated_at=now,
                    )
                )
                created.append(new_setting)
                continue

            merged = _merge_world_fields(existing, es)
            if merged is None:
                # 幂等: 非空覆盖后字段无变化 → 不更新、不计入 updated
                continue
            updated.append(await self._repo.update(merged))

        for w in warnings:
            logger.warning("世界观提取警告: %s", w)

        return WorldExtractionResult(
            created=created,
            updated=updated,
            warnings=warnings,
            model=model,
        )

    # ── 私有辅助 ────────────────────────────────────────────────

    async def _has_soft_deleted_same_name(self, pid_int: int, name: str) -> bool:
        """检查项目内是否存在已软删除的同名条目档案（用于 warning 提示）。

        通过 list 搜索同名校验；若仓储实现默认排除软删除记录，
        该场景仅影响提示，不影响合并行为（新建条目）。
        """
        settings, _ = await self._repo.list(project_id=pid_int, search=name, limit=100)
        return any(s.is_deleted and s.name == name for s in settings)


def _merge_world_fields(existing: WorldSetting, es: ExtractedWorldSetting) -> WorldSetting | None:
    """非空字段覆盖合并（category/content 独立判断）.

    无任何变化时返回 None（幂等跳过，不更新 updated_at）；否则
    保留 existing 的 id / extra / 时间戳等无关字段。

    Args:
        existing: 库中同名活动条目.
        es: LLM 提取出的条目.

    Returns:
        合并后的完整条目；无变化返回 None.
    """
    new_category = es.category or existing.category
    new_content = es.content or existing.content
    if new_category == existing.category and new_content == existing.content:
        return None
    return WorldSetting(
        id=existing.id,
        project_id=existing.project_id,
        name=existing.name,
        category=new_category,
        content=new_content,
        extra=existing.extra,
        is_deleted=existing.is_deleted,
        created_at=existing.created_at,
        updated_at=_utcnow(),
    )
