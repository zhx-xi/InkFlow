"""F10 世界观提取管线 — 模板渲染 → LLM → JSON 解析 → 修复重试 → 合并落库.

依据: specs/f10-world-settings/spec.md §5（AI 提取模式，同 F9 §5，
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
   存在=更新(非空覆盖) / 不存在=创建（v1.1 真删：无「软删同名」分支）
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

from inkflow.domain.models.extraction import Granularity
from inkflow.domain.models.world import (
    ExtractedWorldSetting,
    WorldExtractionResult,
    WorldExtractRequest,
    WorldSetting,
)
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
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

_COARSE_MAX_ITEMS = 5
"""coarse 粒度每源条目上限（#1485 §5.8.3 ②，确定性上限）。"""

_COARSE_HINT = "只提取最重要的 5 条粗粒度条目，把相关的小点合并到同一条；不要拆分细节。"
"""coarse 粒度注入模板的指令（#1485 §5.8.3 ①，模板变量 granularity_hint）。"""


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


def _normalize_name(name: str) -> str:
    """条目名归一化：去掉全部空白字符（含全角空格 \\u3000）后 strip（#1485 §5.8.2）。"""
    return "".join(name.split())


def _is_synonym(normalized: str, other: str) -> bool:
    """近义判据（#1485 §5.8.2 档②）：归一化名互为子串，且较短者 ≥2 字且 ≥ 较长者一半长."""
    if not normalized or not other:
        return False
    if normalized not in other and other not in normalized:
        return False
    shorter, longer = sorted((len(normalized), len(other)))
    return shorter >= 2 and shorter * 2 >= longer


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
        granularity: Granularity = Granularity.FINE,
        dry_run: bool = False,
        batch_id: str | None = None,
    ) -> WorldExtractionResult:
        """执行世界观提取管线（§5.1 步骤 ②-⑦）。

        Args:
            request: 提取请求（project_id / text / 可选 model 覆盖）.
            default_model: 项目默认模型（project.config.model，
                由调用方 WorldService 校验项目存在后传入）.
            granularity: 提取粒度（#1485 §5.8.3；coarse = 注入粗粒度指令 +
                每源上限 ``_COARSE_MAX_ITEMS``）.
            dry_run: 仅预览（#1485 §5.8.4；不落库、不写 run 表，条目 batch_id 恒 None）.
            batch_id: 本批新建条目的批次标识（#1485 §5.8.5；更新条目保留原值）.

        Returns:
            合并落库后的提取报告.

        Raises:
            LLMRequestError: LLM 调用失败（透传，不消耗解析重试）.
            WorldExtractionError: 3 次尝试（1 原始 + 2 修复）均无法解析.
        """
        model = request.model or default_model

        # #1485 §5.8.1: 渲染前读取项目已有分类清单。仓储替身未配置该方法时返回
        # 非列表（既有单测 Mock）→ 退化为「无分类」，而不是抛错。
        cats = await self._repo.list_world_categories(request.project_id)
        category_names = [c.name for c, _ in cats] if isinstance(cats, (list, tuple)) else []
        # #1485 §5.8.2: 合并前扫描已有条目（同一 Mock 守卫口径）。仓储支持全量扫描
        # 时，三档匹配全在该列表内完成（含新建）；不支持（替身）才回退 get_by_name。
        rows = await self._repo.list_all_active(request.project_id)
        scanned = isinstance(rows, (list, tuple))
        existing = list(rows) if scanned else []

        # ② 渲染模板（变量: text / categories / granularity_hint）
        hint = "" if granularity is Granularity.FINE else _COARSE_HINT
        template = self._prompts.load(_TEMPLATE_NAME)
        # 变量值类型异构（text/hint 为 str，categories 为清单）→ dict[str, Any]
        variables: dict[str, Any] = {
            "text": request.text,
            "categories": category_names,
            "granularity_hint": hint,
        }
        rendered = self._prompts.render(template, variables)
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
            category_names=category_names,
            existing=existing,
            scanned=scanned,
            granularity=granularity,
            dry_run=dry_run,
            batch_id=batch_id,
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
        category_names: list[str],
        existing: list[WorldSetting],
        scanned: bool,
        granularity: Granularity,
        dry_run: bool,
        batch_id: str | None,
    ) -> WorldExtractionResult:
        """合并落库: 条目按 (project_id, name) 匹配活动条目，同名=同一世界观条目。

        #1485 写入策略（§5.8.1-§5.8.5）: 落库前类别归一（仅项目有分类时）→
        coarse 上限 → 同名更新 / 近义合并 / 新建三档；dry_run 只算不写。
        """
        warnings = list(item_warnings)
        # #1291：project_id 为领域 UUID，直传仓储
        pid = request.project_id

        if not world_settings:
            warnings.append("未从文本中提取到任何世界观条目")
        # #1485 §5.8.3 ②: coarse 确定性上限（按 LLM 输出顺序取前 N 条）
        if granularity is Granularity.COARSE and len(world_settings) > _COARSE_MAX_ITEMS:
            dropped = len(world_settings) - _COARSE_MAX_ITEMS
            world_settings = world_settings[:_COARSE_MAX_ITEMS]
            warnings.append(f"coarse 粒度：丢弃 {dropped} 条超出上限的条目")

        created: list[WorldSetting] = []
        updated: list[WorldSetting] = []
        # #1297: 新建条目必须归属父级 —— 与 WorldService.get_root_setting 同机制，
        # 仅查一次项目根条目（#849: 每项目仅允许 1 条 parent_id IS NULL）。
        roots, _ = await self._repo.list(request.project_id, top_level_only=True, limit=1)
        current_root: WorldSetting | None = roots[0] if roots else None

        for es in world_settings:
            # #1485 §5.8.1: 类别归一（项目无分类 → 不做归一，原样落库）
            category = es.category or ""
            if category_names and category.strip() not in category_names:
                raw = category.strip()
                if raw:
                    warnings.append(f"类别「{raw}」不在项目分类中，已归为未分类")
                category = ""

            normalized = _normalize_name(es.name)
            matched = _first_match(existing, normalized)
            # #1485 §5.8.2 档②: 近义（归一化后互为子串且长度占比过半）→ 合并进已有条目
            synonym = None if matched is not None else _first_synonym(existing, normalized)
            if synonym is not None:
                warnings.append(f"条目「{es.name}」与已有「{synonym.name}」近义，已合并")
                synonym_merged = _merge_synonym(existing=synonym, es=es)
                # #1485 §5.8.2: 合并结果原位写回扫描池 —— 同批后续条目基于已合并
                # 内容继续累积（否则第二次合并仍以合并前旧对象为基底，丢前一段追加）
                _replace_pool_entry(existing, synonym, synonym_merged)
                updated.append(
                    synonym_merged if dry_run else await self._repo.update(synonym_merged)
                )
                continue

            current = matched
            # 仓储不支持全量扫描（替身）→ 回退既有按名查询路径；否则列表即全量真相
            if current is None and not scanned:
                current = await self._repo.get_by_name(pid, es.name)
            if current is None:
                now = _utcnow()
                new_setting = WorldSetting(
                    id=uuid.uuid4(),
                    project_id=request.project_id,
                    name=es.name,
                    parent_id=current_root.id if current_root is not None else None,
                    category=category,
                    content=es.content or "",
                    # #1485 §5.8.5: 预览（dry_run）构造的条目不带批次
                    batch_id=None if dry_run else batch_id,
                    created_at=now,
                    updated_at=now,
                )
                if dry_run:
                    created.append(new_setting)
                else:
                    new_setting = await self._repo.add(new_setting)
                    created.append(new_setting)
                # 同批重复条目名幂等（列表可用时：新建条目即入匹配池）
                existing.append(new_setting)
                # 无既有根时首条建为根，同批后续条目挂到该条上（不得各自建根）
                if current_root is None:
                    current_root = new_setting
                continue

            merged = _merge_world_fields(current, es, category=category)
            if merged is None:
                # 幂等: 非空覆盖后字段无变化 → 不更新、不计入 updated
                continue
            updated.append(merged if dry_run else await self._repo.update(merged))

        for w in warnings:
            logger.warning("世界观提取警告: %s", w)

        return WorldExtractionResult(
            created=created,
            updated=updated,
            warnings=warnings,
            model=model,
        )


def _first_match(existing: list[WorldSetting], normalized: str) -> WorldSetting | None:
    """档① 同名匹配（#1485 §5.8.2）：归一化名**相等**的已有条目（无 → None）。"""
    if not normalized:
        return None
    for setting in existing:
        if _normalize_name(setting.name) == normalized:
            return setting
    return None


def _first_synonym(existing: list[WorldSetting], normalized: str) -> WorldSetting | None:
    """档② 近义匹配（#1485 §5.8.2）：归一化后互为子串且短者占比 ≥ 50%."""
    for setting in existing:
        if _is_synonym(normalized, _normalize_name(setting.name)):
            return setting
    return None


def _replace_pool_entry(pool: list[WorldSetting], old: WorldSetting, new: WorldSetting) -> None:
    """原位替换扫描池中的条目（#1485 §5.8.2 近义合并累积）.

    保持位置不变，使同批后续条目仍按归一化名匹配到已合并对象。
    """
    for index, item in enumerate(pool):
        if item is old:
            pool[index] = new
            return


def _merge_synonym(*, existing: WorldSetting, es: ExtractedWorldSetting) -> WorldSetting:
    """近义合并（#1485 §5.8.2 档②）: 保留已有身份与归属，content 追加新内容.

    已有 content 已包含该段 → 幂等跳过追加（其余字段仍按已有条目保留）。
    """
    addition = es.content or ""
    content = existing.content
    if addition and addition not in existing.content:
        content = f"{existing.content}\n\n{addition}" if existing.content else addition
    return existing.model_copy(update={"content": content, "updated_at": _utcnow()})


def _merge_world_fields(
    existing: WorldSetting,
    es: ExtractedWorldSetting,
    *,
    category: str | None = None,
) -> WorldSetting | None:
    """非空字段覆盖合并（category/content 独立判断）.

    无任何变化时返回 None（幂等跳过，不更新 updated_at）；否则
    保留 existing 的 id / parent_id / extra / batch_id / 时间戳等无关字段。

    #1485 §5.8.5: batch_id 必须原样保留 —— 被更新的条目不改写其原批次，
    否则更早批次的可回滚性被破坏。

    #1372: parent_id 必须原样保留 —— 漏传时数据类默认 None，会把该条
    写成同项目第二个根，撞 ``uq_world_settings_root_per_project``
    部分唯一索引 → IntegrityError → API 500（提取半途中断）。

    Args:
        existing: 库中同名条目.
        es: LLM 提取出的条目.
        category: 归一后的类别（#1485 §5.8.1；None = 用 LLM 原值）.

    Returns:
        合并后的完整条目；无变化返回 None.
    """
    new_category = (es.category if category is None else category) or existing.category
    new_content = es.content or existing.content
    if new_category == existing.category and new_content == existing.content:
        return None
    return WorldSetting(
        id=existing.id,
        project_id=existing.project_id,
        name=existing.name,
        parent_id=existing.parent_id,
        category=new_category,
        content=new_content,
        extra=existing.extra,
        batch_id=existing.batch_id,
        created_at=existing.created_at,
        updated_at=_utcnow(),
    )
