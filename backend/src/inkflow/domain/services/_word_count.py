"""字数统计工具 — 支持中英文混合内容，自动去除 Markdown 语法."""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_EN_WORD_RE = re.compile(r"[a-zA-Z]+")


def _strip_markdown(text: str) -> str:
    """去除常见 Markdown 语法，只保留可读文字."""
    text = re.sub(r"```[^`]*```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}|_{1,3}", "", text)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^-{3,}|_{3,}|\*{3,}", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    return text


def count_words(content: str) -> int:
    """统计中英文混合内容的字数.

    规则:
    - 每个中文字符计 1 字
    - 每个英文单词计 1 字
    - 数字、标点、Markdown 语法不计入
    """
    if not content:
        return 0

    text = _strip_markdown(content)

    cjk_count = len(_CJK_RE.findall(text))

    text_no_cjk = _CJK_RE.sub(" ", text)
    en_count = len(_EN_WORD_RE.findall(text_no_cjk))

    return cjk_count + en_count
