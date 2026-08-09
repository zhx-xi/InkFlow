"""F22 全文搜索分词与预处理纯函数 —— jieba 封装，无 I/O（spec §5.5）.

镜像 _chunking.py / _style_analyzer.py 先例：模块级纯函数、无副作用、
严格幂等；仅依赖标准库（re）与 jieba（0.42.1 已锁定，F16 引入）。
契约以 tests/unit/test_search_tokenizer.py 为准。
"""

from __future__ import annotations

import re

import jieba


def escape_xml(text: str) -> str:
    """转义 & < > " 为 XML 实体（& 先转，防 snippet 注入 + FTS5 混淆）。"""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def tokenize(text: str) -> list[str]:
    """jieba.cut_for_search 分词后过滤：空白/纯标点/纯符号/英文单字母。"""
    return [w for w in jieba.cut_for_search(text) if _keep(w)]


def _keep(w: str) -> bool:
    """单个 token 是否保留（spec §5.5 ④：单字符中文保留）。"""
    if not w.strip():
        return False
    if re.fullmatch(r"[\W_]+", w):
        return False
    return not (len(w) == 1 and w.isalpha() and w.isascii())


def build_match(tokens: list[str]) -> str:
    """每词双引号包裹、空格连接构造 FTS5 MATCH（保护保留字 AND/OR/NOT）。"""
    return " ".join(f'"{t}"' for t in tokens)


def prepare_index_text(title: str, body: str) -> str:
    """索引文本全链路：拼接 → 转义 → 分词 → 空格连接（spec §5.5 ①②③④⑤）。"""
    return " ".join(tokenize(escape_xml(f"{title} {body}")))
