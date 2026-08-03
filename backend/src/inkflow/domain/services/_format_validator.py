"""格式校验器 — 7条规则校验 LLM 输出质量."""

from __future__ import annotations

import json
import re

from inkflow.domain.models.writing import FormatValidationResult
from inkflow.domain.services._word_count import count_words

_PARAGRAPH_SEP = re.compile(r"\n\s*\n|\n(?=[#])")


def _paragraphs(content: str) -> list[str]:
    """Split into paragraphs, excluding markdown headings."""
    raw = [p.strip() for p in _PARAGRAPH_SEP.split(content) if p.strip()]
    return [p for p in raw if not p.startswith("#")]


class FormatValidator:
    """LLM 输出格式校验器。

    规则列表:
        R1: 无代码块包裹
        R2: 非 JSON/键值对泄漏
        R3: 标题格式正确（跳过——当前不做强制校验）
        R4: 无占位符残留
        R5: 无重复段落
        R6: 无截断
        R7: 字数达标
    """

    _PLACEHOLDER_RE = re.compile(
        r"\{\{[^}]*\}\}|\[TODO\]|\[此处插入[^\]]*\]|\.{3,}\s*$",
    )
    _SENTENCE_ENDS = frozenset("。！？.!?)" + '"' + "」』")

    @staticmethod
    def validate(content: str, min_words: int) -> FormatValidationResult:
        errors: list[str] = []

        # R1: 无代码块包裹
        stripped = content.strip()
        if stripped.startswith("```") or stripped.endswith("```"):
            errors.append("R1: 内容被代码块包裹，请去掉 ``` 标记，直接输出正文")

        # R2: 非 JSON/键值对泄漏
        try:
            json.loads(stripped)
            errors.append("R2: 输出为 JSON 格式，请输出纯文本正文")
        except (json.JSONDecodeError, ValueError):
            pass
        if (
            re.search(r'"[^"]+"\s*:\s*', stripped)
            and not re.search(r"[#\n]", stripped[:50])
            and (not errors or "R2" not in str(errors))
        ):
            errors.append("R2: 检测到 JSON 键值对泄漏，请输出纯文本正文")

        # R4: 无占位符残留
        if FormatValidator._PLACEHOLDER_RE.search(content):
            errors.append("R4: 检测到占位符残留 ({{...}}, [TODO], [此处插入...], ...)，请补全内容")

        # R5: 无重复段落
        paras = _paragraphs(content)
        if len(paras) >= 3:
            counts: dict[str, int] = {}
            for p in paras:
                if len(p) >= 10:
                    counts[p] = counts.get(p, 0) + 1
            if any(c >= 3 for c in counts.values()):
                errors.append("R5: 检测到连续重复段落（同一段落出现 ≥3 次），请删除重复内容")

        # R6: 无截断
        if paras:
            last = paras[-1]
            is_short = len(last) < 5
            has_no_ending = not any(c in FormatValidator._SENTENCE_ENDS for c in last[-5:])
            is_placeholder = "未完待续" in last or "待续" in last or "……" in last
            if is_short or (has_no_ending and not is_placeholder):
                errors.append("R6: 检测到截断结尾，请补全完整段落")

        # R7: 字数达标
        wc = count_words(content)
        if wc < min_words:
            errors.append(f"R7: 字数不足（{wc}/{min_words}），请扩写内容")

        return FormatValidationResult(valid=len(errors) == 0, errors=errors)
