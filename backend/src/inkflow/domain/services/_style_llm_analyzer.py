"""F16 风格 LLM 深度分析管线 — 模板渲染 → LLM → JSON 解析 → 修复重试 → StyleLLMAssessment.

依据: specs/f16-style-service/spec.md §5.6（LLM 深度分析管线步骤 ①-⑥，Q1=C 拍板，
可选增强板块）。镜像 F14 `_timeline_extractor.py` 骨架，仅替换领域实体
（StyleLLMAssessment ↔ TimelineExtractionResult）与模板（style_llm_analysis ↔
timeline_extract）。
遵循 ADR-015: 领域层零 LangChain import，LLM / 模板均通过 Protocol 注入
（LLMClientProtocol / PromptTemplateProtocol），测试中注入 Mock。

管线步骤（§5.6）:
① 空文本 → 不调用 LLM，直接返回 None（llm_assessment=None 语义，spec §7）
② 渲染 style_llm_analysis.yaml（PromptManager，变量 {text}）
③ LLMClient.chat(model or project.config.model, temperature=0.2)
④ 解析 JSON（容忍代码块围栏/前后缀文字）→ 校验 verdict ∈ {likely_human,
   uncertain, likely_ai} + reasoning 非空字符串
⑤ 修复式重试 ≤ 2 次（附错误信息）→ 仍失败 → StyleLLMAnalysisError（500）
⑥ reasoning 截断 ≤ 2000 字符 → 返回 StyleLLMAssessment（model / generated_at=UTC now）

LLM 调用失败（LLMRequestError）→ 透传，不消耗解析重试（spec §5.6 注）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from inkflow.core.config import config
from inkflow.domain.models.project import Project
from inkflow.domain.models.style import StyleLLMAssessment
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol
from inkflow.domain.ports.style_errors import StyleLLMAnalysisError
from inkflow.domain.services.model_resolution import resolve_model

_TEMPLATE_NAME = "style_llm_analysis"
"""LLM 深度分析模板名（infrastructure/llm/templates/style_llm_analysis.yaml）。"""

_MAX_PARSE_RETRIES = 2
"""修复式重试次数上限（共 1 次原始 + 2 次修复 = 3 次尝试）。"""

_TEMPERATURE = 0.2
"""结构化输出固定低温（spec §5.6 步骤 ②，同 F14 timeline 提取先例）。"""

_MAX_REASONING_CHARS = 2000
"""reasoning 截断上限（spec §2.7/§5.6 步骤 ⑤）。"""

_VALID_VERDICTS = frozenset({"likely_human", "uncertain", "likely_ai"})
"""LLM 判定合法值域（与 AITraceVerdict 同值域，spec §2.3/§5.6 步骤 ③）。"""


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


def _extract_json_fragment(text: str) -> str | None:
    """从带围栏/前后缀文字的文本中提取首个 ``{...}`` 平衡片段.

    实现: 定位首个 ``{``，向后扫描花括号深度（跳过字符串字面量），
    深度归零时返回含首尾花括号的完整片段（同 F14 `_timeline_extractor` 逻辑）.

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


def _build_fix_prompt(error_detail: str) -> str:
    """构建修复式重试 Prompt（原输出已在对话历史中）。"""
    return (
        "上一版输出无法解析为合法判定 JSON：\n"
        f"{error_detail}\n"
        "请只输出 JSON，不要包含任何其他文字（不要使用代码块围栏）。"
    )


@dataclass
class _ParseOutcome:
    """LLM 输出解析结果 — 解析/校验失败时 error 非空。"""

    verdict: str = ""
    reasoning: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        """是否解析校验成功（可进入截断返回阶段）。"""
        return not self.error


class StyleLLMAnalyzer:
    """LLM 深度分析管线服务（spec §5.6，Q1=C 可选增强板块）。

    依赖全部通过构造函数注入（Protocol 类型，ADR-015），不感知基础设施具体类:

    Args:
        llm_client: LLM 客户端（F5）.
        prompt_manager: Prompt 模板管理器（F5）.
        llm_default_model: 全局默认模型（#520 D1=C）——project.config.model 为
            None 时回退该值（deps.py 注入 config.llm_default_model）.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClientProtocol,
        prompt_manager: PromptTemplateProtocol,
        llm_default_model: str = config.llm_default_model,
    ) -> None:
        self._llm = llm_client
        self._prompts = prompt_manager
        self._llm_default_model = llm_default_model

    # ── 公共入口 ────────────────────────────────────────────────

    async def analyze(
        self,
        project: Project,
        text: str,
        *,
        model: str | None = None,
    ) -> StyleLLMAssessment | None:
        """执行 LLM 深度分析管线（spec §5.6 步骤 ①-⑥）。

        Args:
            project: 所属项目（config.model 为项目默认模型）.
            text: 待分析文本；空文本 → 不调用 LLM，直接返回 None.
            model: 可选模型覆盖（缺省 → project.config.model）.

        Returns:
            StyleLLMAssessment（llm_verdict / reasoning / model /
            generated_at=UTC now）；空文本返回 None（llm_assessment=None 语义）.

        Raises:
            LLMRequestError: LLM 调用失败（透传，不消耗解析重试）.
            StyleLLMAnalysisError: 3 次尝试（1 原始 + 2 修复）均无法解析/校验.
        """
        # ① 空文本 → 不调用 LLM，返回 None（spec §7「空文本项目 → llm_assessment=None」）
        if not text.strip():
            return None

        resolved_model = (
            resolve_model(model, project.config.model, self._llm_default_model) or ""
        )

        # ② 渲染模板（变量: text）
        template = self._prompts.load(_TEMPLATE_NAME)
        rendered = self._prompts.render(template, {"text": text})
        messages = [ChatMessage(role=m["role"], content=m["content"]) for m in rendered.messages]

        # ③④⑤ 调用 LLM + 解析校验 + 修复式重试（≤ 2 次）
        last_raw = ""
        outcome = _ParseOutcome()
        for retry_count in range(_MAX_PARSE_RETRIES + 1):
            # 传消息列表副本，避免客户端变异影响重试历史记录
            # LLM 调用失败透传，不消耗解析重试（spec §5.6 注）
            response = await self._llm.chat(
                list(messages), model=resolved_model, temperature=_TEMPERATURE
            )

            last_raw = response.content
            outcome = self._parse_output(last_raw)
            if outcome.ok:
                break

            if retry_count >= _MAX_PARSE_RETRIES:
                raise StyleLLMAnalysisError(
                    f"{_MAX_PARSE_RETRIES} 次修复重试后仍无法解析为合法判定 JSON"
                    f"（最后错误: {outcome.error}）"
                )

            messages.append(ChatMessage(role="assistant", content=last_raw))
            messages.append(ChatMessage(role="user", content=_build_fix_prompt(outcome.error)))

        # ⑥ reasoning 截断（≤ 2000 字符）+ 返回 StyleLLMAssessment
        return StyleLLMAssessment(
            llm_verdict=outcome.verdict,
            reasoning=outcome.reasoning[:_MAX_REASONING_CHARS],
            model=resolved_model,
            generated_at=_utcnow(),
        )

    # ── 解析 ────────────────────────────────────────────────────

    def _parse_output(self, raw: str) -> _ParseOutcome:
        """解析 LLM 输出: 提取 JSON 片段 → json.loads → verdict/reasoning 校验。"""
        fragment = _extract_json_fragment(raw)
        if fragment is None:
            return _ParseOutcome(error="未找到平衡的 JSON 对象片段")
        try:
            payload: Any = json.loads(fragment)
        except json.JSONDecodeError as e:
            return _ParseOutcome(error=f"JSON 语法错误: {e.msg}（位置 {e.pos}）")
        if not isinstance(payload, dict):
            return _ParseOutcome(error="JSON 顶层必须是对象")

        verdict = payload.get("verdict")
        if not isinstance(verdict, str) or verdict not in _VALID_VERDICTS:
            return _ParseOutcome(error="verdict 必须是 likely_human / uncertain / likely_ai 之一")

        reasoning = payload.get("reasoning")
        if not isinstance(reasoning, str) or not reasoning:
            return _ParseOutcome(error="reasoning 必须是非空字符串")

        return _ParseOutcome(verdict=verdict, reasoning=reasoning)
