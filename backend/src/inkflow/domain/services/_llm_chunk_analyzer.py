"""F14 LLM 分析切片器 — 模板渲染 → LLM → JSON 解析 → 修复重试 → 边界列表.

依据: specs/f14-extraction-service/spec.md §5.6.7（LLM 分析切片器）+ §9 测试策略。
镜像 F16 `_style_llm_analyzer.py` 骨架（模板渲染 → LLM chat → JSON 解析 →
边界校验 → 修复式重试 ≤2），仅替换领域实体（list[int] ↔ StyleLLMAssessment）
与模板（llm_chunk ↔ style_llm_analysis）。
遵循 ADR-015: 领域层零 LangChain import，LLM / 模板均通过 Protocol 注入
（LLMClientProtocol / PromptTemplateProtocol），测试中注入 Mock。

管线（§5.6.7）:
① 空文本 → 不调用 LLM，直接返回 []（spec §9「空文本 → []」）
② 渲染 llm_chunk.yaml（PromptManager，变量 {text}）
③ LLMClient.chat(model or config.llm_default_model, temperature=0.2)
④ 解析 JSON（容忍代码块围栏/前后缀文字）→ 校验 boundaries: 全部整数、
   严格升序、0 < b < len(text)
⑤ 修复式重试 ≤ 2 次（对话历史追加 assistant 原输出 + user 修复提示）→
   仍失败 → LLMChunkAnalyzerError

LLM 调用失败（LLMRequestError）→ 透传，不消耗解析重试（spec §5.6.7 ③）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from inkflow.core.config import config
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol

_TEMPLATE_NAME = "llm_chunk"
"""LLM 切片边界分析模板名（infrastructure/llm/templates/llm_chunk.yaml）。"""

_MAX_PARSE_RETRIES = 2
"""修复式重试次数上限（共 1 次原始 + 2 次修复 = 3 次尝试）。"""

_TEMPERATURE = 0.2
"""结构化输出固定低温（同 F16 style 深度分析先例）。"""


class LLMChunkAnalyzerError(Exception):
    """LLM 切片边界解析失败（修复式重试 ≤2 仍失败）.

    同 F16 StyleLLMAnalysisError / F14 TimelineExtractionError 语义——
    reindex 层捕获后降级段落切片（spec §5.6.7 ③），reindex 不中断。
    """

    def __init__(self, message: str = "LLM 切片边界解析失败") -> None:
        super().__init__(message)


def _extract_json_fragment(text: str) -> str | None:
    """从带围栏/前后缀文字的文本中提取首个 ``{...}`` 平衡片段.

    实现: 定位首个 ``{``，向后扫描花括号深度（跳过字符串字面量），
    深度归零时返回含首尾花括号的完整片段（镜像 F16 `_style_llm_analyzer`）.

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
    """构建修复式重试 Prompt（原输出已在对话历史中，镜像 F16）."""
    return (
        "上一版输出无法解析为合法边界 JSON：\n"
        f"{error_detail}\n"
        "请只输出 JSON，不要包含任何其他文字（不要使用代码块围栏）。"
    )


@dataclass
class _ParseOutcome:
    """LLM 输出解析结果 — 解析/校验失败时 error 非空。"""

    boundaries: list[int] | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        """是否解析校验成功（可进入返回阶段）。"""
        return not self.error


class LLMChunkAnalyzer:
    """LLM 语义边界分析器（spec §5.6.7）— async 边界提供器.

    依赖全部通过构造函数注入（Protocol 类型，ADR-015），不感知基础设施具体类:

    Args:
        llm_client: LLM 客户端（F5）.
        prompt_manager: Prompt 模板管理器（F5）.
        model: 可选模型覆盖（缺省 → config.llm_default_model）.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClientProtocol,
        prompt_manager: PromptTemplateProtocol,
        model: str | None = None,
    ) -> None:
        self._llm = llm_client
        self._prompts = prompt_manager
        self._model = model

    # ── 公共入口 ────────────────────────────────────────────────

    async def analyze(self, text: str) -> list[int]:
        """执行 LLM 语义边界分析管线（spec §5.6.7 ①-⑤）.

        Args:
            text: 待分析文本；空文本 → 不调用 LLM，直接返回 [].

        Returns:
            语义边界起始偏移列表（升序，首块 0 不包含）.

        Raises:
            LLMRequestError: LLM 调用失败（透传，不消耗解析重试）.
            LLMChunkAnalyzerError: 3 次尝试（1 原始 + 2 修复）均无法解析/校验.
        """
        # ① 空文本 → 不调用 LLM，返回 []（spec §9「空文本 → []」）
        if not text.strip():
            return []

        resolved_model = self._model or config.llm_default_model

        # ② 渲染模板（变量: text）
        template = self._prompts.load(_TEMPLATE_NAME)
        rendered = self._prompts.render(template, {"text": text})
        messages = [ChatMessage(role=m["role"], content=m["content"]) for m in rendered.messages]

        # ③④⑤ 调用 LLM + 解析校验 + 修复式重试（≤ 2 次）
        last_raw = ""
        outcome = _ParseOutcome()
        for retry_count in range(_MAX_PARSE_RETRIES + 1):
            # 传消息列表副本，避免客户端变异影响重试历史记录
            # LLM 调用失败（LLMRequestError）透传，不消耗解析重试（spec §5.6.7 ③）
            response = await self._llm.chat(
                list(messages), model=resolved_model, temperature=_TEMPERATURE
            )

            last_raw = response.content
            outcome = self._parse_output(last_raw, text)
            if outcome.ok:
                return outcome.boundaries or []

            if retry_count >= _MAX_PARSE_RETRIES:
                raise LLMChunkAnalyzerError(
                    f"{_MAX_PARSE_RETRIES} 次修复重试后仍无法解析为合法边界 JSON"
                    f"（最后错误: {outcome.error}）"
                )

            messages.append(ChatMessage(role="assistant", content=last_raw))
            messages.append(ChatMessage(role="user", content=_build_fix_prompt(outcome.error)))

        raise LLMChunkAnalyzerError("LLM 切片边界解析失败")  # 不可达（重试循环内必 raise）

    # ── 解析 ────────────────────────────────────────────────────

    def _parse_output(self, raw: str, text: str) -> _ParseOutcome:
        """解析 LLM 输出: 提取 JSON 片段 → json.loads → boundaries 校验."""
        fragment = _extract_json_fragment(raw)
        if fragment is None:
            return _ParseOutcome(error="未找到平衡的 JSON 对象片段")
        try:
            payload: Any = json.loads(fragment)
        except json.JSONDecodeError as e:
            return _ParseOutcome(error=f"JSON 语法错误: {e.msg}（位置 {e.pos}）")
        if not isinstance(payload, dict):
            return _ParseOutcome(error="JSON 顶层必须是对象")

        boundaries = payload.get("boundaries")
        if not isinstance(boundaries, list):
            return _ParseOutcome(error="boundaries 必须是数组")

        valid: list[int] = []
        for value in boundaries:
            if not isinstance(value, int) or isinstance(value, bool):
                return _ParseOutcome(error="boundaries 元素必须是整数")
            if not 0 < value < len(text):
                return _ParseOutcome(error=f"boundaries 元素越界（须满足 0 < b < {len(text)}）")
            if valid and value <= valid[-1]:
                return _ParseOutcome(error="boundaries 必须严格升序")
            valid.append(value)
        return _ParseOutcome(boundaries=valid)
