"""#1121 RED 契约 — 归一幂等（I1）与守卫不动点（I2）在**更宽输入域**下必须成立.

背景
----
``normalize_chapter_content`` docstring 第 ④ 条声明幂等（``N(N(x))==N(x)``），
``chapter_content_needs_normalize`` 声称与纯函数同口径（``need(N(x))==False``）。
#1095/#1112/#1120 的契约只在「真实散文 + 标题回声」形态上验证 —— 更宽输入域下
两条不变量仍被违反。

根因（源码实证）
----------------
``_word_count._strip_markdown`` 有 5 条 ``^`` 锚定（``re.MULTILINE``）行首正则
（``^#``、``^>``、``^-{3,}|_{3,}|\\*{3,}``、``^[\\s]*[-*+]\\s+``、``^\\d+\\.``）。
``_indent_paragraphs`` 在每行行首插入 ``U+3000 U+3000``，使**原本位于行首**的
装饰字符不再在行首。第二轮 ``_strip_markdown`` 因此「看见」第一轮看不见的装饰
并继续剥离 —— 剥离是**逐级**的，单次调用不是不动点。

实样（本文件锁定的最小复现）::

    c = '*\\u3000-\\u3000'
    N(c,  t)  = '\\u3000\\u3000-\\u3000'      # '*' 被剥离（^[\\s]*[-*+]\\s+ 的 * 分支）
    N(N(c), t) = ''                          # '-' 此时已在行首 → 第二轮被剥离

第 3 类正则 ``^[\\s]*[-*+]\\s+`` 每次只吃掉「一个标记 + 其后空白」，剥离后下一个
标记暴露到行首 → 需要迭代至不动点。

契约
----
I1 幂等：对任意 content/title，``N(N(x,t),t) == N(x,t)``
I2 守卫不动点：``need(N(x,t),t) is False``
I3 一致性：``need(x,t) == (N(x,t) != x)``
I4 不删正文（#1112 铁律守护）：真实散文段落不得被归一删除
I5 计数不回归：``count_words`` 不受剥离收敛化影响（装饰字符不计入字数）
"""

from __future__ import annotations

import itertools

import pytest

from inkflow.domain.models.chapter import (
    chapter_content_needs_normalize,
    normalize_chapter_content,
)
from inkflow.domain.services._word_count import count_words

TITLE = "第1章 雪夜怪梦"
FW = "\u3000"

# ---- 最小实样（issue #1121 正文） ----
ISSUE_SAMPLES = [
    ("issue 正文实样", "*\u3000-\u3000"),
    ("空格分隔双标记", "* - "),
    ("全角分隔双标记", "*\u3000#\u3000"),
    ("引用+分隔", "*\u3000>\u3000"),
    ("三标记级联", "*\u3000-\u3000#\u3000"),
    ("反序标记", "-\u3000*\u3000"),
    ("多行中的级联", "正文一。\n\n*\u3000-\u3000"),
]

# ---- 穷举小字母表（覆盖行首装饰 + 全角缩进 + 置换） ----
ALPHABET = ["", FW, "*", "-", "#", "x", " ", "\n", "\u3000\u3000", ">", "1", ".", "_", "**"]


def _exhaustive(max_len: int = 3) -> list[str]:
    return [
        "".join(c) for n in range(1, max_len + 1) for c in itertools.product(ALPHABET, repeat=n)
    ]


class TestI1IdempotencyIssueSamples:
    """I1：issue 实样 + 同族级联形态必须幂等。"""

    @pytest.mark.parametrize(("name", "content"), ISSUE_SAMPLES)
    def test_idempotent(self, name: str, content: str) -> None:
        once = normalize_chapter_content(content, TITLE)
        twice = normalize_chapter_content(once, TITLE)
        assert once == twice, (
            f"[{name}] 归一非幂等\n  输入: {content!r}\n  一次: {once!r}\n  二次: {twice!r}"
        )

    @pytest.mark.parametrize(("name", "content"), ISSUE_SAMPLES)
    def test_guard_fixed_point(self, name: str, content: str) -> None:
        """I2：归一产物不得再被判脏（否则落库/导出反复归一）。"""
        once = normalize_chapter_content(content, TITLE)
        assert chapter_content_needs_normalize(once, TITLE) is False, (
            f"[{name}] 守卫非不动点\n  归一产物: {once!r}"
        )


class TestI2ExhaustiveConvergence:
    """I1/I2/I3 在穷举输入域上违例数为 0（#1121 验收：fuzz/穷举违例 0）。"""

    def test_no_violations_across_exhaustive_domain(self) -> None:
        cases = _exhaustive(3)
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
            if chapter_content_needs_normalize(c, TITLE) is not (
                normalize_chapter_content(c, TITLE) != c
            ):
                i3.append(f"{c!r}")
        assert not i1, f"I1 幂等违例 {len(i1)} 例（前 5）: {i1[:5]}"
        assert not i2, f"I2 守卫不动点违例 {len(i2)} 例（前 5）: {i2[:5]}"
        assert not i3, f"I3 守卫一致性违例 {len(i3)} 例（前 5）: {i3[:5]}"


class TestI4NoBodyDeleted:
    """I4 守护（#1112 铁律）：收敛化剥离不得删除真实正文。"""

    @pytest.mark.parametrize(
        ("name", "content", "fragments"),
        [
            ("snake_case 保留", "调用 my_var_name 函数", ("my_var_name",)),
            (
                "多行 snake_case 保留",
                "他写下 my_var_name。\n\n另一个 other_thing。",
                ("my_var_name", "other_thing"),
            ),
            ("单行干净逐字节", "师父停了三天。", ("师父停了三天。",)),
            (
                "标题回声段不删",
                f"\n\n{TITLE}\n\n正文第一段。",
                (TITLE, "正文第一段。"),
            ),
            (
                "成对强调仍剥离",
                f"# {TITLE}\n\n他说 **重要** 的事。",
                ("他说", "重要", "的事。"),
            ),
        ],
    )
    def test_fragments_survive(self, name: str, content: str, fragments: tuple[str, ...]) -> None:
        out = normalize_chapter_content(content, TITLE)
        for frag in fragments:
            assert frag in out, f"[{name}] 归一丢失 {frag!r}\n  输出: {out!r}"

    def test_clean_single_line_byte_identical(self) -> None:
        c = "调用 my_var_name 函数"
        assert normalize_chapter_content(c, TITLE) == c


class TestI5CountWordsUnaffected:
    """I5：剥离收敛化只影响装饰字符（不计入字数）→ 计数不回归。"""

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("my_var_name", 3),
            ("other_thing", 2),
            ("a_b_c", 3),
            ("**强调**文字", 4),
            ("*重要*", 2),
        ],
    )
    def test_count_stable(self, content: str, expected: int) -> None:
        assert count_words(content) == expected

    def test_digits_not_counted_but_markers_preserved(self) -> None:
        """``3*4*5`` 是数学记号（#1110 S1）：* 保留，数字本身不计字。"""
        assert count_words("3*4*5") == 0
