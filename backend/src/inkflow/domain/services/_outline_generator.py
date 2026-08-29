"""F11 大纲生成管线 — 模板渲染 → LLM → JSON 解析 → 修复重试 → 落库/预览.

依据: specs/f11-outline/spec.md §5（AI 生成模式，关键差异见 §5.6）。
实现为 F10 `_world_extractor.py` 的镜像，仅替换领域实体（Outline /
PlotPoint / StoryArc ↔ WorldSetting）与模板名（outline_generate ↔
world_extract），并按 §5.6 调整落库语义: 生成即新建（大纲同名 → 422，
不合并/不覆盖）+ 弧线按名复用 + save 两态（默认落库 / 仅预览不落库）。
遵循 ADR-015: 领域层零 LangChain import，LLM / 模板 / 仓储均通过
Protocol 注入（LLMClientProtocol / PromptTemplateProtocol /
OutlineRepositoryProtocol），测试中注入 Mock。

管线步骤（§5.1）:
① 校验项目存在 + 组装 project_info —— 由调用方 OutlineService 负责，
   generator 不重复（MVP 只传项目基本信息，角色/世界观档案查询归 Phase 2+）
② 渲染 outline_generate.yaml（PromptManager，变量 project_info/prompt/num_chapters）
③ LLMClient.chat(model or project.config.model, temperature=0.2)
④ 解析 JSON → Pydantic schema 校验（GeneratedOutline / GeneratedPlotPoint /
   GeneratedArc）→ 非法条目跳过 + warning
⑤ 修复式重试 ≤ 2 次（附错误信息）→ 仍失败 → OutlineGenerationError
⑥ 落库（save=True，§5.4）: 大纲新建（同名活动冲突 → OutlineNameConflictError
   422）；弧线按 (project_id, name) 匹配活动弧线 → 存在=复用 / 不存在=创建；
   情节点按输出顺序分配 position（1,2,3...），arc 名解析为 arc_id，
   无法解析 → 跳过关联 + warning；空情节点 → warning「未生成情节点」
   save=False → 仅返回 preview（GeneratedOutline），不落库、不做同名检查
⑦ 返回 OutlineGenerationResult

num_chapters 处理: F5 PromptManager 的渲染是 str.replace（见
infrastructure/llm/prompt_manager.py `_format`），不支持 Jinja2 条件段 —
outline_generate.yaml 中的 {% if num_chapters %}...{% endif %} 与
{{ num_chapters }} 会原样透传。本管线在渲染后对消息内容做条件段解析
（_resolve_num_chapters_in_text）: num_chapters 有值 → 去除条件标签并将
{{ num_chapters }} 替换为数字；无值 → 移除整段条件。保证发送给 LLM 的
文本无字面 Jinja 标记残留。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from inkflow.domain.models.outline import (
    GeneratedArc,
    GeneratedOutline,
    GeneratedPlotPoint,
    Outline,
    OutlineGenerateRequest,
    OutlineGenerationResult,
    PlotPoint,
    StoryArc,
)
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.outline_errors import (
    OutlineGenerationError,
    OutlineNameConflictError,
)
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol

logger = logging.getLogger(__name__)

_TEMPLATE_NAME = "outline_generate"
"""生成模板名（infrastructure/llm/templates/outline_generate.yaml）。"""

_MAX_PARSE_RETRIES = 2
"""修复式重试次数上限（共 1 次原始 + 2 次修复 = 3 次尝试）。"""

_TEMPERATURE = 0.2
"""结构化输出固定低温（spec §5.5，不对外暴露）。"""

_DEFAULT_OUTLINE_NAME = "未命名大纲"
"""大纲名缺省值（LLM 与请求均未提供时，spec §2.6/§5.4）。"""

_IF_TAG = "{% if num_chapters %}"
"""模板条件段开标签（str.replace 渲染会原样透传，需本管线解析）。"""

_ENDIF_TAG = "{% endif %}"
"""模板条件段闭标签。"""

_NUM_CHAPTERS_PLACEHOLDER = "{{ num_chapters }}"
"""模板章节数占位符（带空格，str.replace 不会命中，需本管线替换）。"""


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


def _resolve_num_chapters_in_text(text: str, num_chapters: int | None) -> str:
    """解析 str.replace 渲染残留的 Jinja2 条件段（outline_generate.yaml）.

    F5 PromptManager._format 只做 ``{key}`` 字面替换，``{% if num_chapters %}``
    与 ``{{ num_chapters }}`` 会原样透传。此处:
    - num_chapters 有值 → 去除条件标签，占位符替换为数字；
    - num_chapters 为 None → 移除整段条件（含标签），不注入章节数提示。
    保证发送给 LLM 的文本不含字面 Jinja 标记。

    Args:
        text: 渲染后的消息内容.
        num_chapters: 请求中的可选规划章节数（1-100）.

    Returns:
        清理后的消息内容.
    """
    if _IF_TAG not in text and _NUM_CHAPTERS_PLACEHOLDER not in text:
        return text

    if num_chapters is None:
        # 移除整段 {% if num_chapters %} ... {% endif %}（含标签）
        while True:
            start = text.find(_IF_TAG)
            if start == -1:
                break
            end = text.find(_ENDIF_TAG, start)
            if end == -1:
                # 无闭标签的异常模板：仅去除开标签，避免循环
                text = text[:start] + text[start + len(_IF_TAG) :]
                break
            text = text[:start] + text[end + len(_ENDIF_TAG) :]
        return text

    return (
        text.replace(_IF_TAG, "")
        .replace(_ENDIF_TAG, "")
        .replace(_NUM_CHAPTERS_PLACEHOLDER, str(num_chapters))
    )


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

    generated: GeneratedOutline | None = None
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        """是否结构解析成功（可进入落库/预览阶段）。"""
        return not self.error


class OutlineGenerator:
    """大纲生成管线服务（spec §5.1）。

    依赖全部通过构造函数注入（Protocol 类型），不感知基础设施具体类:

    Args:
        llm_client: LLM 客户端（F5）.
        prompt_manager: Prompt 模板管理器（F5）.
        repository: 大纲/情节点/弧线仓储端口（B1）.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClientProtocol,
        prompt_manager: PromptTemplateProtocol,
        repository: OutlineRepositoryProtocol,
    ) -> None:
        self._llm = llm_client
        self._prompts = prompt_manager
        self._repo = repository

    # ── 公共入口 ────────────────────────────────────────────────

    async def generate(
        self,
        request: OutlineGenerateRequest,
        *,
        project_info: str,
        default_model: str,
    ) -> OutlineGenerationResult:
        """执行大纲生成管线（§5.1 步骤 ②-⑦）。

        Args:
            request: 生成请求（project_id / name? / prompt? /
                num_chapters? / save / model?）.
            project_info: 项目基本信息纯文本（项目名/类型/目标字数/
                写作风格/extra，由调用方 OutlineService 组装；MVP 不查
                F9/F10 档案，§5.1 要点 3）.
            default_model: 项目默认模型（project.config.model，由调用方
                OutlineService 校验项目存在后传入）.

        Returns:
            落库后的生成报告（save=True）或预览结构（save=False）.

        Raises:
            LLMRequestError: LLM 调用失败（透传，不消耗解析重试）.
            OutlineGenerationError: 3 次尝试（1 原始 + 2 修复）均无法解析.
            OutlineNameConflictError: 同名活动大纲已存在（save=True）.
        """
        model = request.model or default_model

        # ② 渲染模板（变量: project_info/prompt/num_chapters）
        template = self._prompts.load(_TEMPLATE_NAME)
        rendered = self._prompts.render(
            template,
            {
                "project_info": project_info,
                "prompt": request.prompt or "",
                # str.replace 渲染需要占位符；条件段由 _resolve_num_chapters_in_text 解析
                "num_chapters": str(request.num_chapters)
                if request.num_chapters is not None
                else "",
            },
        )
        messages = [
            ChatMessage(
                role=m["role"],
                content=_resolve_num_chapters_in_text(m["content"], request.num_chapters),
            )
            for m in rendered.messages
        ]

        # ③④⑤ 调用 LLM + 解析 + 修复式重试（≤ 2 次）
        last_raw = ""
        outcome = _ParseOutcome()
        for retry_count in range(_MAX_PARSE_RETRIES + 1):
            # 传消息列表副本，避免客户端变异影响重试历史记录
            # LLM 调用失败透传，不消耗解析重试（§5.1 要点 4）
            response = await self._llm.chat(list(messages), model=model, temperature=_TEMPERATURE)

            last_raw = response.content
            outcome = self._parse_output(last_raw)
            if outcome.ok:
                break

            if retry_count >= _MAX_PARSE_RETRIES:
                raise OutlineGenerationError(
                    raw_output=last_raw[:500],
                    detail=(
                        f"{_MAX_PARSE_RETRIES} 次修复重试后仍无法解析为合法 JSON"
                        f"（最后错误: {outcome.error}）"
                    ),
                )

            messages.append(ChatMessage(role="assistant", content=last_raw))
            messages.append(ChatMessage(role="user", content=_build_fix_prompt(outcome.error)))

        generated = outcome.generated
        assert generated is not None  # ok 分支必然已填充（mypy 收窄）

        # ⑥⑦ 落库/预览 + 返回结果（§5.1 要点 6: save=false 零落库）
        if not request.save:
            return OutlineGenerationResult(
                saved=False,
                outline=None,
                plot_points=[],
                arcs=[],
                preview=generated,
                warnings=outcome.warnings,
                model=model,
            )
        return await self._persist(
            request=request,
            generated=generated,
            warnings=outcome.warnings,
            model=model,
        )

    # ── 解析 ────────────────────────────────────────────────────

    def _parse_output(self, raw: str) -> _ParseOutcome:
        """解析 LLM 输出: 结构失败 → error；条目级非法 → 跳过 + warning。

        LLM 输出格式（§5.2）: ``{"outline": {...}, "arcs": [...], "plot_points": [...]}``，
        其中 outline 的 name/description 缺省时回退到请求参数。
        """
        fragment = _extract_json_fragment(raw)
        if fragment is None:
            return _ParseOutcome(error="未找到平衡的 JSON 对象片段")
        try:
            payload: Any = json.loads(fragment)
        except json.JSONDecodeError as e:
            return _ParseOutcome(error=f"JSON 语法错误: {e.msg}（位置 {e.pos}）")
        if not isinstance(payload, dict):
            return _ParseOutcome(error="JSON 顶层必须是对象")

        raw_outline = payload.get("outline")
        if raw_outline is None:
            outline_data: dict[str, Any] = {}
        elif isinstance(raw_outline, dict):
            outline_data = raw_outline
        else:
            return _ParseOutcome(error="outline 字段必须是对象")

        raw_arcs = payload.get("arcs") or []
        if not isinstance(raw_arcs, list):
            return _ParseOutcome(error="arcs 字段必须是列表")
        raw_points = payload.get("plot_points") or []
        if not isinstance(raw_points, list):
            return _ParseOutcome(error="plot_points 字段必须是列表")

        # 大纲级字段校验（失败 → 整体重试；name/description 可缺省回退）
        try:
            outline_level = GeneratedOutline.model_validate(
                {
                    "name": outline_data.get("name"),
                    "description": outline_data.get("description"),
                }
            )
        except ValidationError as e:
            return _ParseOutcome(error=f"大纲 schema 校验失败: {_first_error(e)}")

        # 条目级校验（非法 → 跳过 + warning，不影响其余落库）
        warnings: list[str] = []
        arcs: list[GeneratedArc] = []
        for index, item in enumerate(raw_arcs):
            try:
                arcs.append(GeneratedArc.model_validate(item))
            except ValidationError as e:
                warnings.append(f"跳过非法弧线 #{index + 1}: {_first_error(e)}")

        plot_points: list[GeneratedPlotPoint] = []
        for index, item in enumerate(raw_points):
            try:
                plot_points.append(GeneratedPlotPoint.model_validate(item))
            except ValidationError as e:
                warnings.append(f"跳过非法情节点 #{index + 1}: {_first_error(e)}")

        return _ParseOutcome(
            generated=GeneratedOutline(
                name=outline_level.name,
                description=outline_level.description,
                arcs=arcs,
                plot_points=plot_points,
            ),
            warnings=warnings,
        )

    # ── 落库（§5.4 生成即新建 + 弧线复用）───────────────────────

    async def _persist(
        self,
        *,
        request: OutlineGenerateRequest,
        generated: GeneratedOutline,
        warnings: list[str],
        model: str,
    ) -> OutlineGenerationResult:
        """落库: 大纲新建（同名 422）/ 弧线按名复用 / 情节点顺序落库。"""
        out_warnings = list(warnings)
        pid_int = _to_int_id(request.project_id)

        # 大纲: 生成即新建（同名活动冲突 → 422，不合并/不覆盖旧规划）
        outline_name = generated.name or request.name or _DEFAULT_OUTLINE_NAME
        existing = await self._repo.get_by_name(pid_int, outline_name)
        if existing is not None:
            raise OutlineNameConflictError()
        now = _utcnow()
        outline = await self._repo.add(
            Outline(
                id=uuid.uuid4(),
                project_id=request.project_id,
                name=outline_name,
                description=generated.description or "",
                created_at=now,
                updated_at=now,
            )
        )

        # 弧线: 按 (project_id, name) 匹配活动弧线 → 存在=复用 / 不存在=创建
        arcs: list[StoryArc] = []
        arc_by_name: dict[str, StoryArc] = {}
        for ga in generated.arcs:
            existing_arc = await self._repo.get_arc_by_name(pid_int, ga.name)
            if existing_arc is not None:
                arc_by_name[ga.name] = existing_arc
                arcs.append(existing_arc)
                continue
            new_arc = await self._repo.add_arc(
                StoryArc(
                    id=uuid.uuid4(),
                    project_id=request.project_id,
                    name=ga.name,
                    description=ga.description or "",
                    created_at=now,
                    updated_at=now,
                )
            )
            arc_by_name[ga.name] = new_arc
            arcs.append(new_arc)

        # 情节点: 按输出顺序分配 position（1,2,3...）；arc 名解析为 arc_id
        plot_points: list[PlotPoint] = []
        for index, gp in enumerate(generated.plot_points, start=1):
            arc_id = None
            if gp.arc:
                arc_name = gp.arc.strip()
                if arc_name:
                    arc = arc_by_name.get(arc_name)
                    if arc is None:
                        arc = await self._repo.get_arc_by_name(pid_int, arc_name)
                    if arc is not None:
                        arc_by_name[arc_name] = arc
                        arc_id = arc.id
                    else:
                        out_warnings.append(
                            f"情节点 {gp.name} 的弧线 {arc_name} 无法解析已跳过关联"
                        )
            plot_points.append(
                await self._repo.add_point(
                    PlotPoint(
                        id=uuid.uuid4(),
                        outline_id=outline.id,
                        project_id=request.project_id,
                        name=gp.name,
                        type=gp.type or "",
                        description=gp.description or "",
                        position=index,
                        arc_id=arc_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
            )

        if not generated.plot_points:
            out_warnings.append("未生成情节点")

        for w in out_warnings:
            logger.warning("大纲生成警告: %s", w)

        return OutlineGenerationResult(
            saved=True,
            outline=outline,
            plot_points=plot_points,
            arcs=arcs,
            preview=None,
            warnings=out_warnings,
            model=model,
        )
