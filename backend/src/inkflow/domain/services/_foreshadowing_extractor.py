"""F14 伏笔提取管线 — 模板渲染 → LLM → JSON 解析 → 修复重试 → 合并落库.

依据: specs/f14-extraction-service/spec.md §5.4（伏笔提取管线，F13 移交）。
镜像 F9 `_character_extractor.py` 骨架（管线步骤/JSON 解析/重试/合并全参考），
仅替换领域实体（ExtractedForeshadowing → Foreshadowing）与模板
（foreshadowing_extract.yaml）。
遵循 ADR-015: 领域层零 LangChain import，LLM / 模板 / 仓储均通过
Protocol 注入（LLMClientProtocol / PromptTemplateProtocol /
ForeshadowingRepositoryProtocol），测试中注入 Mock。

管线步骤（§5.4）:
① 校验项目存在 —— 由门面统一负责（§5.1），extractor 不重复
② 渲染 foreshadowing_extract.yaml（PromptManager，变量 {text}）
③ LLMClient.chat(model or project.config.model, temperature=0.2)
④ 解析 JSON → Pydantic schema 校验（ExtractedForeshadowing）
   → 非法条目跳过 + warning
⑤ 修复式重试 ≤ 2 次（附错误信息）→ 仍失败 → ForeshadowingExtractionError
⑥ 合并落库（§5.4 合并策略）: 按 (project_id, title) 匹配伏笔 →
   存在=非空字段覆盖（description/location 独立判断，不重置 status）/
   不存在=创建（status=open, priority=50, event_id=None；
   v1.1 真删：无「软删同名」分支）
⑦ 返回 ForeshadowingExtractionResult（created/updated/warnings + model）
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from inkflow.domain.models.foreshadowing import (
    ExtractedForeshadowing,
    Foreshadowing,
    ForeshadowingExtractionResult,
    ForeshadowingExtractRequest,
    ForeshadowingStatus,
)
from inkflow.domain.ports.foreshadowing_errors import ForeshadowingExtractionError
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol

logger = logging.getLogger(__name__)

_TEMPLATE_NAME = "foreshadowing_extract"
"""提取模板名（infrastructure/llm/templates/foreshadowing_extract.yaml）。"""

_MAX_PARSE_RETRIES = 2
"""修复式重试次数上限（共 1 次原始 + 2 次修复 = 3 次尝试）。"""

_TEMPERATURE = 0.2
"""结构化输出固定低温（spec §5.4，不对外暴露）。"""


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

    foreshadowings: list[ExtractedForeshadowing] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        """是否结构解析成功（可进入合并阶段）。"""
        return not self.error


class ForeshadowingExtractor:
    """伏笔提取管线服务（spec §5.4）。

    依赖全部通过构造函数注入（Protocol 类型），不感知基础设施具体类:

    Args:
        llm_client: LLM 客户端（F5）.
        prompt_manager: Prompt 模板管理器（F5）.
        foreshadowing_repo: 伏笔仓储端口（F13）.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClientProtocol,
        prompt_manager: PromptTemplateProtocol,
        foreshadowing_repo: ForeshadowingRepositoryProtocol,
    ) -> None:
        self._llm = llm_client
        self._prompts = prompt_manager
        self._repo = foreshadowing_repo

    # ── 公共入口 ────────────────────────────────────────────────

    async def extract(
        self,
        request: ForeshadowingExtractRequest,
        *,
        default_model: str,
    ) -> ForeshadowingExtractionResult:
        """执行伏笔提取管线（§5.4 步骤 ②-⑦）。

        Args:
            request: 提取请求（project_id / text / 可选 model 覆盖）.
            default_model: 项目默认模型（project.config.model，
                由调用方门面校验项目存在后传入）.

        Returns:
            合并落库后的提取报告.

        Raises:
            LLMRequestError: LLM 调用失败（透传，不消耗解析重试）.
            ForeshadowingExtractionError: 3 次尝试（1 原始 + 2 修复）均无法解析.
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
            # LLM 调用失败透传，不消耗解析重试（§5.4 同 F9 模式要点）
            response = await self._llm.chat(list(messages), model=model, temperature=_TEMPERATURE)

            last_raw = response.content
            outcome = self._parse_output(last_raw)
            if outcome.ok:
                break

            if retry_count >= _MAX_PARSE_RETRIES:
                raise ForeshadowingExtractionError(
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
            foreshadowings=outcome.foreshadowings,
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

        raw_items = payload.get("foreshadowings")
        if not isinstance(raw_items, list):
            return _ParseOutcome(error="缺少 foreshadowings 列表")

        warnings: list[str] = []
        foreshadowings: list[ExtractedForeshadowing] = []
        for index, item in enumerate(raw_items):
            try:
                foreshadowings.append(ExtractedForeshadowing.model_validate(item))
            except ValidationError as e:
                warnings.append(f"跳过非法伏笔条目 #{index + 1}: {_first_error(e)}")

        return _ParseOutcome(foreshadowings=foreshadowings, warnings=warnings)

    # ── 合并落库（§5.4 合并策略）────────────────────────────────

    async def _merge(
        self,
        *,
        request: ForeshadowingExtractRequest,
        foreshadowings: list[ExtractedForeshadowing],
        item_warnings: list[str],
        model: str,
    ) -> ForeshadowingExtractionResult:
        """合并落库: 按 (project_id, title) 匹配伏笔 → 覆盖/新建。"""
        warnings = list(item_warnings)
        pid_int = _to_int_id(request.project_id)

        if not foreshadowings:
            warnings.append("未从文本中提取到任何伏笔")

        created: list[Foreshadowing] = []
        updated: list[Foreshadowing] = []
        for ef in foreshadowings:
            existing = await self._repo.get_by_title(pid_int, ef.title)
            if existing is None:
                now = _utcnow()
                new_fs = await self._repo.add(
                    Foreshadowing(
                        id=uuid.uuid4(),
                        project_id=request.project_id,
                        title=ef.title,
                        description=ef.description or "",
                        priority=50,
                        status=ForeshadowingStatus.OPEN,
                        location=ef.location or "",
                        event_id=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                created.append(new_fs)
                continue

            merged = _merge_foreshadowing_fields(existing, ef)
            if merged is None:
                # 幂等: 非空覆盖后字段无变化 → 不更新、不计入 updated
                continue
            updated.append(await self._repo.update(merged))

        for w in warnings:
            logger.warning("伏笔提取警告: %s", w)

        return ForeshadowingExtractionResult(
            created=created,
            updated=updated,
            warnings=warnings,
            model=model,
        )


def _merge_foreshadowing_fields(
    existing: Foreshadowing, ef: ExtractedForeshadowing
) -> Foreshadowing | None:
    """非空字段覆盖合并（description/location 独立判断，status 不重置）.

    无任何变化时返回 None（幂等跳过，不更新 updated_at）；否则
    保留 existing 的 id / priority / status / event_id / 时间戳等无关字段。

    Args:
        existing: 库中同名伏笔.
        ef: LLM 提取出的伏笔.

    Returns:
        合并后的完整伏笔；无变化返回 None.
    """
    new_description = ef.description or existing.description
    new_location = ef.location or existing.location
    if new_description == existing.description and new_location == existing.location:
        return None
    return Foreshadowing(
        id=existing.id,
        project_id=existing.project_id,
        title=existing.title,
        description=new_description,
        priority=existing.priority,
        status=existing.status,  # 不重置（open/resolved 原样保留，§5.4 合并策略）
        location=new_location,
        event_id=existing.event_id,
        resolved_at=existing.resolved_at,
        extra=existing.extra,
        created_at=existing.created_at,
        updated_at=_utcnow(),
    )
