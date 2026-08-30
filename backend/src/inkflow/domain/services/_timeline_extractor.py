"""F14 时间线提取管线 — 模板渲染 → LLM → JSON 解析 → 修复重试 → 合并落库.

依据: specs/f14-extraction/spec.md §5.5（时间线提取管线，Q2 拍板，
设置项 timeline_auto_extract 开启时由门面调用）。镜像 F9 `_character_extractor.py`
骨架，仅替换领域实体（TimelineEvent ↔ Character）与模板（timeline_extract ↔
character_extract）。
遵循 ADR-015: 领域层零 LangChain import，LLM / 模板 / 仓储均通过
Protocol 注入（LLMClientProtocol / PromptTemplateProtocol /
TimelineRepositoryProtocol），测试中注入 Mock。

管线步骤（§5.5）:
① 校验项目存在 —— 由调用方门面负责，extractor 不重复
② 渲染 timeline_extract.yaml（PromptManager，变量 {text}）
③ LLMClient.chat(model or project.config.model, temperature=0.2)
④ 解析 JSON → Pydantic schema 校验（ExtractedTimelineEvent）
   → 非法条目跳过 + warning
⑤ 修复式重试 ≤ 2 次（附错误信息）→ 仍失败 → TimelineExtractionError
⑥ 合并落库（§5.5 合并策略）: 按 (project_id, title, source_chapter_id)
   匹配事件 → 存在=非空字段覆盖 / 不存在=新建（narrative_position=None
   走 F12 next_position 追加语义；v1.1 真删：无「软删同名同章」分支）
⑦ 返回 TimelineExtractionResult（created/updated/warnings + model）
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from inkflow.domain.models.timeline import (
    ExtractedTimelineEvent,
    TimelineEvent,
    TimelineExtractionResult,
    TimelineExtractRequest,
)
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol
from inkflow.domain.ports.timeline_errors import TimelineExtractionError
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol

logger = logging.getLogger(__name__)

_TEMPLATE_NAME = "timeline_extract"
"""提取模板名（infrastructure/llm/templates/timeline_extract.yaml）。"""

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

    events: list[ExtractedTimelineEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        """是否结构解析成功（可进入合并阶段）。"""
        return not self.error


class TimelineExtractor:
    """时间线提取管线服务（spec §5.5）。

    依赖全部通过构造函数注入（Protocol 类型），不感知基础设施具体类:

    Args:
        llm_client: LLM 客户端（F5）.
        prompt_manager: Prompt 模板管理器（F5）.
        timeline_repo: 时间线事件仓储端口（F12，跨模块 MODIFY 后含
            list_by_chapter）.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClientProtocol,
        prompt_manager: PromptTemplateProtocol,
        timeline_repo: TimelineRepositoryProtocol,
    ) -> None:
        self._llm = llm_client
        self._prompts = prompt_manager
        self._repo = timeline_repo

    # ── 公共入口 ────────────────────────────────────────────────

    async def extract(
        self,
        request: TimelineExtractRequest,
        *,
        default_model: str,
    ) -> TimelineExtractionResult:
        """执行时间线提取管线（§5.5 步骤 ②-⑦）。

        Args:
            request: 提取请求（project_id / chapter_id / text / 可选 model 覆盖）.
            default_model: 项目默认模型（project.config.model，
                由调用方门面校验项目存在后传入）.

        Returns:
            合并落库后的提取报告.

        Raises:
            LLMRequestError: LLM 调用失败（透传，不消耗解析重试）.
            TimelineExtractionError: 3 次尝试（1 原始 + 2 修复）均无法解析.
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
                raise TimelineExtractionError(
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
            events=outcome.events,
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

        raw_events = payload.get("events")
        if not isinstance(raw_events, list):
            return _ParseOutcome(error="缺少 events 列表")

        warnings: list[str] = []
        events: list[ExtractedTimelineEvent] = []
        for index, item in enumerate(raw_events):
            try:
                events.append(ExtractedTimelineEvent.model_validate(item))
            except ValidationError as e:
                warnings.append(f"跳过非法时间线事件条目 #{index + 1}: {_first_error(e)}")

        return _ParseOutcome(events=events, warnings=warnings)

    # ── 合并落库（§5.5 合并策略）────────────────────────────────

    async def _merge(
        self,
        *,
        request: TimelineExtractRequest,
        events: list[ExtractedTimelineEvent],
        item_warnings: list[str],
        model: str,
    ) -> TimelineExtractionResult:
        """合并落库: 按 (project_id, title, source_chapter_id) 匹配事件。"""
        warnings = list(item_warnings)
        pid_int = _to_int_id(request.project_id)
        cid_int = _to_int_id(request.chapter_id)

        if not events:
            warnings.append("未从文本中提取到任何时间线事件")

        created: list[TimelineEvent] = []
        updated: list[TimelineEvent] = []
        for ee in events:
            existing = await self._find_active_by_title(pid_int, cid_int, ee.title)
            if existing is None:
                now = _utcnow()
                narrative_position = ee.narrative_position
                if narrative_position is None:
                    narrative_position = await self._repo.next_position(pid_int)
                new_event = await self._repo.add(
                    TimelineEvent(
                        id=uuid.uuid4(),
                        project_id=request.project_id,
                        title=ee.title,
                        description=ee.description or "",
                        time_value=ee.time_value,
                        time_unit=ee.time_unit or "",
                        time_display="",
                        narrative_position=narrative_position,
                        timeline_flag=ee.timeline_flag or "",
                        source_chapter_id=request.chapter_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
                created.append(new_event)
                continue

            merged = _merge_event_fields(existing, ee)
            if merged is None:
                # 幂等: 非空覆盖后字段无变化 → 不更新、不计入 updated
                continue
            updated.append(await self._repo.update(merged))

        for w in warnings:
            logger.warning("时间线提取警告: %s", w)

        return TimelineExtractionResult(
            created=created,
            updated=updated,
            warnings=warnings,
            model=model,
        )

    # ── 私有辅助 ────────────────────────────────────────────────

    async def _find_active_by_title(
        self, pid_int: int, cid_int: int, title: str
    ) -> TimelineEvent | None:
        """在指定来源章的事件中按 title 精确匹配（§5.5 匹配逻辑在服务层）。"""
        events = await self._repo.list_by_chapter(pid_int, cid_int)
        for event in events:
            if event.title == title:
                return event
        return None


def _merge_event_fields(
    existing: TimelineEvent, ee: ExtractedTimelineEvent
) -> TimelineEvent | None:
    """非空字段覆盖合并（description/time_value/time_unit/narrative_position/
    timeline_flag 独立判断）.

    提取字段 None = 「未知/不覆盖」，保留 existing 原值；空字符串是明确值
    （如 timeline_flag="" = 明确无标记），照常覆盖（spec §5.5 表）。
    title 是匹配键 (project_id, title, source_chapter_id) 的一部分，
    不参与覆盖。

    无任何变化时返回 None（幂等跳过，不更新 updated_at）；否则
    保留 existing 的 id / time_display / source_chapter_id / extra /
    时间戳等无关字段。

    Args:
        existing: 库中同名同章事件.
        ee: LLM 提取出的事件.

    Returns:
        合并后的完整事件；无变化返回 None.
    """
    new_description = ee.description if ee.description is not None else existing.description
    new_time_value = ee.time_value if ee.time_value is not None else existing.time_value
    new_time_unit = ee.time_unit if ee.time_unit is not None else existing.time_unit
    new_narrative_position = (
        ee.narrative_position if ee.narrative_position is not None else existing.narrative_position
    )
    new_timeline_flag = ee.timeline_flag if ee.timeline_flag is not None else existing.timeline_flag
    if (
        new_description == existing.description
        and new_time_value == existing.time_value
        and new_time_unit == existing.time_unit
        and new_narrative_position == existing.narrative_position
        and new_timeline_flag == existing.timeline_flag
    ):
        return None
    return TimelineEvent(
        id=existing.id,
        project_id=existing.project_id,
        title=existing.title,
        description=new_description,
        time_value=new_time_value,
        time_unit=new_time_unit,
        time_display=existing.time_display,
        narrative_position=new_narrative_position,
        timeline_flag=new_timeline_flag,
        source_chapter_id=existing.source_chapter_id,
        extra=existing.extra,
        created_at=existing.created_at,
        updated_at=_utcnow(),
    )
