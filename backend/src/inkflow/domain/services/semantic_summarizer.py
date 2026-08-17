"""F45 M2 语义总结管线 — 模板渲染 → LLM → JSON 解析 → 修复重试 → 防幻觉 B → SemanticSummary.

依据: specs/f45-memory-evolution/spec.md §5.3（LLM 总结管线①-⑥）/§5.3.1
（防幻觉 B 测试契约——anchor_refs ⊆ 锚点集校验，不通过丢弃）；镜像 F16
`_style_llm_analyzer.py` 骨架（_extract_json_fragment / _build_fix_prompt /
_ParseOutcome / 修复式重试模式，仅替换领域实体与模板）。
遵循 ADR-015: 领域层零框架 import，LLM / 模板均通过 Protocol 注入
（LLMClientProtocol / PromptTemplateProtocol），测试中注入 Mock。

管线步骤（spec §5.3）:
① 锚点为空 → 不调用 LLM，返回 (None, 0)
② 渲染 memory_semantic_summary 模板（变量 {anchors} 传原始锚点列表）
③ LLMClient.chat(model, temperature=0.2)——model 由调用方传入（#415 唯一默认源）
④ 解析 JSON（容忍围栏/前后缀文字，复用 F16 _extract_json_fragment）→ 校验两组结构
⑤ 修复式重试 ≤2 次（附错误信息）→ 仍失败 → SemanticSummaryError（502）
⑥ 按 scope 投影对应组 + 防幻觉 B（anchor_refs ⊆ 锚点 value 集，不通过丢弃）
⑦ content 截断 ≤2000 字符；剩余空 → (None, dropped)；否则落库 SemanticSummary

LLM 调用失败（LLMRequestError）→ 透传，不消耗解析重试（F16 §5.6 注同款）。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from inkflow.domain.models.semantic_summary import SemanticSummary, SummaryScope
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol
from inkflow.domain.ports.semantic_summary_errors import SemanticSummaryError

_TEMPLATE_NAME = "memory_semantic_summary"
"""语义总结模板名（infrastructure/llm/templates/memory_semantic_summary.yaml，Batch 2 创建）."""

_MAX_PARSE_RETRIES = 2
"""修复式重试次数上限（共 1 次原始 + 2 次修复 = 3 次尝试）."""

_TEMPERATURE = 0.2
"""结构化输出固定低温（spec §5.3 步骤③）."""

_MAX_CONTENT_CHARS = 2000
"""content 截断上限（spec §5.3 步骤⑥）."""


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


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
        "上一版输出无法解析为合法总结 JSON：\n"
        f"{error_detail}\n"
        "请只输出 JSON，不要包含任何其他文字（不要使用代码块围栏）。"
    )


@dataclass
class _ParseOutcome:
    """LLM 输出解析结果 — 解析/校验失败时 error 非空."""

    project_specific: list[dict[str, Any]] | None = None
    user_general: list[dict[str, Any]] | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        """是否解析校验成功（可进入防幻觉 B 阶段）."""
        return not self.error


class SemanticSummarizer:
    """LLM 语义总结管线服务（spec §5.3，镜像 F16 骨架）.

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

    async def summarize(
        self,
        anchors: list,
        *,
        scope: SummaryScope,
        project_id: uuid.UUID | None,
        anchor_hash: str,
        model: str,
    ) -> tuple[SemanticSummary | None, int]:
        """执行 LLM 语义总结管线（spec §5.3 步骤①-⑦）.

        Args:
            anchors: difflib 已落库锚点列表（ProjectPreference/UserPreference，
                均有 category/value）；空列表 → 不调用 LLM，直接返回 (None, 0).
            scope: 归属范围（project → project_specific 组；user → user_general 组）.
            project_id: scope=project 时的项目 UUID；scope=user 时为 None.
            anchor_hash: 锚点集合哈希（调用方按 §5.4 计算，本管线不感知编排幂等）.
            model: 生成模型（#415 唯一默认源，由调用方传入，代码不写第二份默认值）.

        Returns:
            (summary, dropped): summary 为语义总结（防幻觉 B 后仍无条目时为 None）；
            dropped 为防幻觉 B 丢弃条数（spec §5.3.1）.

        Raises:
            LLMRequestError: LLM 调用失败（透传，不消耗解析重试）.
            SemanticSummaryError: 3 次尝试（1 原始 + 2 修复）均无法解析/校验.
        """
        # ① 锚点为空 → 不调用 LLM，返回 (None, 0)（spec §5.3 ①/§9 ⑪）
        if not anchors:
            return None, 0

        # ② 渲染模板：契约断言 render 收到原始 anchors 列表对象（非格式化文本），
        #    与 PromptTemplateProtocol.render 声明的 variables: dict[str, str] 泛型不符（预期）
        template = self._prompts.load(_TEMPLATE_NAME)
        rendered = self._prompts.render(
            template, {"anchors": anchors}  # type: ignore[dict-item]  # 契约透传原始 anchors 列表
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
                raise SemanticSummaryError(
                    f"{_MAX_PARSE_RETRIES} 次修复重试后仍无法解析为合法总结 JSON"
                    f"（最后错误：{outcome.error}）"
                )

            messages.append(ChatMessage(role="assistant", content=last_raw))
            messages.append(ChatMessage(role="user", content=_build_fix_prompt(outcome.error)))

        # 走到此处必为 ok（否则已抛 SemanticSummaryError），组列表已由 _parse_output 填充
        group = outcome.project_specific if scope == SummaryScope.PROJECT else outcome.user_general
        assert group is not None  # mypy: ok 分支保证对应组已赋值

        # ⑤ 防幻觉 B（anchor_refs ⊆ 锚点 value 集合；不通过 → 丢弃该条，不重试）
        anchor_values = {a.value for a in anchors}
        kept: list[str] = []
        dropped = 0
        for entry in group:
            if not set(entry["anchor_refs"]) <= anchor_values:
                dropped += 1
                continue
            kept.append(entry["content"])

        # ⑥⑦ content 拼接 + 截断；剩余空 → (None, dropped)；否则落库 SemanticSummary
        content = "\n".join(kept)[:_MAX_CONTENT_CHARS]
        if not content:
            return None, dropped

        now = _utcnow()
        return (
            SemanticSummary(
                id=str(uuid.uuid4()),
                scope=scope,
                project_id=project_id,
                content=content,
                anchor_hash=anchor_hash,
                anchor_count=len(anchors),
                model=model,
                created_at=now,
                updated_at=now,
            ),
            dropped,
        )

    # ── 解析 ──────────────────────────────────────────────────────────────

    def _parse_output(self, raw: str) -> _ParseOutcome:
        """解析 LLM 输出: 提取 JSON 片段 → json.loads → 两组结构校验（镜像 F16 结构）.

        结构契约（spec §5.3 ④）: 顶层对象须含 "project_specific" 与 "user_general"
        两组，每组为 list，元素为 dict 且含 "content"（非空 str）与 "anchor_refs"
        （str 列表）；不满足 → 返回 error 非空（走修复式重试）。
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

        groups: dict[str, list[dict[str, Any]]] = {}
        for key in ("project_specific", "user_general"):
            group = payload.get(key)
            if not isinstance(group, list):
                return _ParseOutcome(error=f"{key} 必须是列表")
            entries: list[dict[str, Any]] = []
            for entry in group:
                if not isinstance(entry, dict):
                    return _ParseOutcome(error=f"{key} 元素必须是对象")
                content = entry.get("content")
                if not isinstance(content, str) or not content:
                    return _ParseOutcome(error=f"{key} 元素 content 必须是非空字符串")
                anchor_refs = entry.get("anchor_refs")
                if not isinstance(anchor_refs, list) or not all(
                    isinstance(ref, str) for ref in anchor_refs
                ):
                    return _ParseOutcome(error=f"{key} 元素 anchor_refs 必须是字符串列表")
                entries.append({"content": content, "anchor_refs": anchor_refs})
            groups[key] = entries

        return _ParseOutcome(
            project_specific=groups["project_specific"],
            user_general=groups["user_general"],
        )
