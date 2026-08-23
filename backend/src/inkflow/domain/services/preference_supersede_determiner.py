"""F49 ② (#618) 偏好取代判定管线 — 模板渲染 → LLM → JSON 解析 → 修复重试 → 防幻觉 B.

依据: .hermes/plans/task-618-contract.md §2（LLM 冲突判定管线）；镜像 F45
`semantic_summarizer.py` 骨架（_extract_json_fragment / _build_fix_prompt /
_ParseOutcome / 修复式重试 ≤2 / 温度 0.2 / 防幻觉 B），仅替换领域实体与模板。
遵循 ADR-015: 领域层零框架 import，LLM / 模板均通过 Protocol 注入
（LLMClientProtocol / PromptTemplateProtocol），测试中注入 Mock。

管线步骤（contract §2）:
① 锚点为空 → 不调用 LLM，返回 ([], 0)
② 渲染 memory_supersede 模板（变量 {new_value}/{anchors}，anchors 传原始列表对象）
③ LLMClient.chat(model, temperature=0.2)——model 由调用方传入（#415 唯一默认源）
④ 解析 JSON（容忍围栏/前后缀文字，复用 F16 _extract_json_fragment）→ 校验
   顶层对象含 "superseded" 为 str 列表
⑤ 修复式重试 ≤2 次（附错误信息）→ 仍失败 → SupersedeDeterminationError
⑥ 防幻觉 B: 每个 superseded value 必须 ∈ 锚点 value 集合 {a.value for a in anchors}，
   不在者丢弃（dropped 计数，不重试）→ 返回 (superseded_values, dropped)

LLM 调用失败（LLMRequestError）→ 透传，不消耗解析重试（F16 §5.6 注同款）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.preference_supersede_errors import SupersedeDeterminationError
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol

_TEMPLATE_NAME = "memory_supersede"
"""偏好取代判定模板名（infrastructure/llm/templates/memory_supersede.yaml）."""

_MAX_PARSE_RETRIES = 2
"""修复式重试次数上限（共 1 次原始 + 2 次修复 = 3 次尝试）."""

_TEMPERATURE = 0.2
"""结构化输出固定低温（contract §0 温度 0.2）."""


def _extract_json_fragment(text: str) -> str | None:
    """从带围栏/前后缀文字的文本中提取首个 ``{...}`` 平衡片段.

    实现: 定位首个 ``{``，向后扫描花括号深度（跳过字符串字面量）；
    深度归零时返回含首尾花括号的完整片段（逐字镜像 F16
    `_style_llm_analyzer._extract_json_fragment` 逻辑）.

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
    """构建修复式重试 Prompt（原输出已在对话历史中）."""
    return (
        "上一版输出无法解析为合法 supersede JSON：\n"
        f"{error_detail}\n"
        "请只输出 JSON，不要包含任何其他文字（不要使用代码块围栏）。"
    )


@dataclass
class _ParseOutcome:
    """LLM 输出解析结果 — 解析/校验失败时 error 非空."""

    superseded: list[str] | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        """是否解析校验成功（可进入防幻觉 B 阶段）."""
        return not self.error


class PreferenceSupersedeDeterminer:
    """LLM 偏好取代判定管线服务（contract §2，镜像 F45 骨架）.

    依赖全部通过构造函数注入（Protocol 类型，ADR-015），不感知基础设施具体类。

    Args:
        llm_client: LLM 客户端（F5）.
        prompt_manager: Prompt 模板管理器（F5）.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClientProtocol,
        prompt_manager: PromptTemplateProtocol,
    ) -> None:
        self._llm = llm_client
        self._prompts = prompt_manager

    # ── 公共入口 ──────────────────────────────────────────────────────────

    async def determine(
        self, new_value: str, anchors: list, *, model: str
    ) -> tuple[list[str], int]:
        """执行 LLM 偏好取代判定管线（contract §2 步骤①-⑥）.

        Args:
            new_value: 新候选偏好 value（判定其语义上取代的既有偏好）.
            anchors: 既有偏好列表（ProjectPreference/UserPreference，均有
                .value 字段）；空列表 → 不调用 LLM，直接返回 ([], 0).
            model: 生成模型（#415 唯一默认源，由调用方传入，代码不写第二份默认值）.

        Returns:
            (superseded_values, dropped): superseded_values 为通过防幻觉 B 的
            既有偏好 value 列表；dropped 为防幻觉 B 丢弃条数.

        Raises:
            LLMRequestError: LLM 调用失败（透传，不消耗解析重试）.
            SupersedeDeterminationError: 3 次尝试（1 原始 + 2 修复）均无法解析/校验.
        """
        # ① 锚点为空 → 不调用 LLM（contract §2）
        if not anchors:
            return [], 0

        # ② 渲染模板：契约断言 render 收到原始 anchors 列表对象（非格式化文本），
        #    与 PromptTemplateProtocol.render 声明的 variables: dict[str, str] 泛型不符（预期）
        template = self._prompts.load(_TEMPLATE_NAME)
        rendered = self._prompts.render(
            template,
            {"new_value": new_value, "anchors": anchors},  # type: ignore[dict-item]  # 契约透传原始 anchors 列表
        )
        messages = [ChatMessage(role=m["role"], content=m["content"]) for m in rendered.messages]

        # ③④⑤ 调用 LLM + 解析校验 + 修复式重试（≤2 次）
        last_raw = ""
        outcome = _ParseOutcome()
        for retry_count in range(_MAX_PARSE_RETRIES + 1):
            # 传消息列表副本，避免客户端变异影响重试历史记录；
            # LLM 调用失败透传，不消耗解析重试（F16 §5.6 注同款）
            response = await self._llm.chat(
                list(messages), model=model, temperature=_TEMPERATURE
            )

            last_raw = response.content
            outcome = self._parse_output(last_raw)
            if outcome.ok:
                break

            if retry_count >= _MAX_PARSE_RETRIES:
                raise SupersedeDeterminationError(
                    f"{_MAX_PARSE_RETRIES} 次修复重试后仍无法解析为合法 supersede JSON"
                    f"（最后错误：{outcome.error}）"
                )

            messages.append(ChatMessage(role="assistant", content=last_raw))
            messages.append(ChatMessage(role="user", content=_build_fix_prompt(outcome.error)))

        # 走到此处必为 ok（否则已抛 SupersedeDeterminationError），列表已由 _parse_output 填充
        assert outcome.superseded is not None  # mypy: ok 分支保证已赋值

        # ⑥ 防幻觉 B（value ∈ 锚点 value 集合；不在 → 丢弃，不重试）
        anchor_values = {a.value for a in anchors}
        kept: list[str] = []
        dropped = 0
        for value in outcome.superseded:
            if value not in anchor_values:
                dropped += 1
                continue
            kept.append(value)
        return kept, dropped

    # ── 解析 ──────────────────────────────────────────────────────────────

    def _parse_output(self, raw: str) -> _ParseOutcome:
        """解析 LLM 输出: 提取 JSON 片段 → json.loads → 结构校验（镜像 F16 结构）.

        结构契约（contract §2）: 顶层对象须含 "superseded" 为 list[str]；
        缺键/非 list/元素非 str → 返回 error 非空（走修复式重试）。
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

        superseded = payload.get("superseded")
        if not isinstance(superseded, list):
            return _ParseOutcome(error="superseded 必须是列表")
        if not all(isinstance(value, str) for value in superseded):
            return _ParseOutcome(error="superseded 元素必须是字符串")

        return _ParseOutcome(superseded=superseded)
