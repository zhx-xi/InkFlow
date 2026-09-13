"""#1121 fuzz 骨架 — 随机 + 穷举双通道验证归一收敛性（违例数 0）.

复用 #1120 审查期骨架（当时为 ad-hoc，未持久化）。本文件把它固化为契约守卫：
任何未来的 `_strip_markdown` / `_indent_paragraphs` 改动若破坏收敛性，本文件必 FAIL。

双通道
------
A. 穷举：小字母表（行首装饰 + 全角缩进 + 空白 + 换行）全排列至长度 4。
B. 随机：20 万例，从「装饰/空白/正文」混合池采样（确定性 seed，失败可复现）。

不变量（与 issue #1121 验收一致）
    I1 幂等：N(N(x,t),t) == N(x,t)
    I2 守卫不动点：need(N(x,t),t) is False
    I3 一致性：need(x,t) == (N(x,t) != x)
"""

from __future__ import annotations

import itertools
import random

from inkflow.domain.models.chapter import (
    chapter_content_needs_normalize,
    normalize_chapter_content,
)

TITLE = "第1章 雪夜怪梦"
FW = "\u3000"

# 装饰标记 + 空白 + 全角缩进 + 换行 + 正文种子 + 标题回声
ALPHABET = ["", FW, "*", "-", "#", "x", " ", "\n", "\u3000\u3000", ">", "1", ".", "_", "**"]
RANDOM_POOL = [
    *ALPHABET,
    TITLE,
    "正文",
    "。",
    "\n\n",
    "\t",
    "\u3000\u3000\u3000",
    "++",
    ")",
    "(",
]


def _violations(cases: list[str]) -> tuple[list[str], list[str], list[str]]:
    i1: list[str] = []
    i2: list[str] = []
    i3: list[str] = []
    for c in cases:
        once = normalize_chapter_content(c, TITLE)
        twice = normalize_chapter_content(once, TITLE)
        if once != twice:
            i1.append(f"{c!r} -> {once!r} -> {twice!r}")
        if chapter_content_needs_normalize(once, TITLE):
            i2.append(f"{c!r} -> {once!r}")
        if chapter_content_needs_normalize(c, TITLE) is not (once != c):
            i3.append(f"{c!r} need={chapter_content_needs_normalize(c, TITLE)} changed={once != c}")
    return i1, i2, i3


def _assert_clean(cases: list[str], label: str) -> None:
    i1, i2, i3 = _violations(cases)
    assert not i1, f"[{label}] I1 幂等违例 {len(i1)}/{len(cases)}（前 5）: {i1[:5]}"
    assert not i2, f"[{label}] I2 守卫不动点违例 {len(i2)}/{len(cases)}（前 5）: {i2[:5]}"
    assert not i3, f"[{label}] I3 一致性违例 {len(i3)}/{len(cases)}（前 5）: {i3[:5]}"


class TestExhaustiveChannel:
    """A 通道：穷举小字母表（<=4 token）—— 覆盖所有级联/置换组合。"""

    def test_exhaustive_len_3(self) -> None:
        cases = ["".join(c) for n in range(1, 4) for c in itertools.product(ALPHABET, repeat=n)]
        _assert_clean(cases, "exhaustive<=3")

    def test_exhaustive_len_4(self) -> None:
        cases = ["".join(c) for n in range(1, 5) for c in itertools.product(ALPHABET, repeat=n)]
        _assert_clean(cases, "exhaustive<=4")


class TestRandomChannel:
    """B 通道：20 万随机混合输入（确定性 seed）。"""

    def test_random_200k(self) -> None:
        rng = random.Random(1121)
        cases = [
            "".join(rng.choice(RANDOM_POOL) for _ in range(rng.randint(1, 12)))
            for _ in range(200_000)
        ]
        _assert_clean(cases, "random-200k")
