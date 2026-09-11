"""#1111 RED 契约 — 守卫与纯函数对**单行正文**的判断必须一致（硬不变量）。

背景
----
`chapter.py` 里两个函数对「单行正文」的判定口径曾经不一致：
`_has_noncanonical_indent` 以 ``"\\n" not in body`` 为唯一闸口（单行视作
无段落结构 → 不脏），而 `normalize_chapter_content` 的归一路径**没有**该
豁免 → 单行也会被前置全角缩进。issue #1111 的实证：

    c = "师父停了三天。"
    need(c, t)  → False   # 守卫说不脏
    N(c, t)     → "　　师父停了三天。"   # 纯函数却改了内容

#1112（幂等性修复，PR #1112）在 `normalize_chapter_content` **函数入口**加了
单行早退，但豁免条件比守卫的闸口**更强**（额外要求「无前导空白」且
「无 markdown」「不与 title 等价」）→ 只覆盖了 issue 里那一个形态，
**单行带前导空白**（全角/半角）仍然违反不变量：

    need("　师父停了三天。", t) → False
    N("　师父停了三天。", t)    → "　　师父停了三天。"   # 仍是「守卫说干净、纯函数改了」

契约（本文件锁定的不变量，即 issue #1111 验收第 1 条）
------------------------------------------------------
对**任意** content/title：
    need(content, title) == (N(content, title) != content)
即「守卫判干净 ⟺ 纯函数逐字节不动」。

实现自由：把单行豁免**下沉**进纯函数（使两支共用同一闸口），或让入口早退
条件与守卫**完全同口径**——只要不变量成立且既有契约不回归。

边界说明（不属本不变量范畴，勿据此判红）
--------------------------------------
`include_indent=False`（导出路径）是**另一条语义轴**：该档位下守卫有意
忽略「段首缩进非规范」，故 `need(c,t,include_indent=False) != (N!=c)`
是**设计如此**，本文件只对默认 `include_indent=True` 断言。
"""

from __future__ import annotations

import pytest

from inkflow.domain.models.chapter import (
    chapter_content_needs_normalize,
    normalize_chapter_content,
)

TITLE = "第1章 雪夜怪梦"
FW = "\u3000"

# 覆盖单行四形态（干净/带空白/带 markdown/与 title 等价）+ 多行 + 退化输入。
# 每条都必须满足「守卫 ⟺ 纯函数是否改动」。
INVARIANT_INPUTS = [
    # —— 单行：issue #1111 的实证形态 ——
    ("单行-纯正文（issue 实证）", "师父停了三天。"),
    ("单行-前导全角", f"{FW}师父停了三天。"),
    ("单行-前导半角", " 师父停了三天。"),
    ("单行-前导全角x2", f"{FW}{FW}师父停了三天。"),
    ("单行-前导混合", f" {FW}师父停了三天。"),
    ("单行-尾随全角", f"师父停了三天。{FW}"),
    ("单行-前后空白", "  师父停了三天。  "),
    ("单行-带 markdown 粗体", "**师父停了三天。**"),
    ("单行-带 markdown 井号", "# 师父停了三天。"),
    ("单行-与 title 等价", TITLE),
    ("单行-与 title 等价(全角缩进)", f"{FW}{TITLE}"),
    ("单行-带前导空白的 markdown", f"{FW}**师父停了三天。**"),
    # —— 多行：回归保护（#1095/#1112 已覆盖面）——
    ("多行-全无缩进", "师父停了三天。\n\n师兄走了。"),
    ("多行-已规范全角", f"{FW}{FW}师父停了三天。\n\n{FW}{FW}师兄走了。"),
    ("多行-单个全角缩进", f"{FW}师父停了三天。\n\n{FW}师兄走了。"),
    ("多行-半角缩进", " 师父停了三天。\n\n 师兄走了。"),
    ("多行-混合缩进", f" {FW}师父停了三天。\n\n{FW} 师兄走了。"),
    ("多行-含空行", "师父停了三天。\n\n\n师兄走了。"),
    ("多行-首行重复标题", f"{TITLE}\n\n正文第一段。"),
    ("多行-前导空行+标题", f"\n\n{TITLE}\n\n正文第一段。"),
    ("多行-正文含标题同文段", f"{TITLE}\n\n正文零。\n\n{TITLE}\n\n正文第一段。"),
    ("多行-带 markdown", "# 标题\n\n**正文**。"),
    # —— 首尾空行/换行框（F2/F3）：守卫忽略空行，但纯函数会 strip 掉它们 ——
    ("多行规范-前导空行", f"\n{FW}{FW}师父停了三天。\n\n{FW}{FW}师兄走了。"),
    ("多行规范-尾随换行", f"{FW}{FW}师父停了三天。\n\n{FW}{FW}师兄走了。\n"),
    ("多行规范-尾随空行", f"{FW}{FW}师父停了三天。\n\n{FW}{FW}师兄走了。\n\n"),
    ("多行规范-首尾空行", f"\n\n{FW}{FW}师父停了三天。\n\n{FW}{FW}师兄走了。\n\n"),
    ("多行规范-前导换行x2", f"\n\n{FW}{FW}师父停了三天。\n\n{FW}{FW}师兄走了。"),
    ("单行规范-尾随换行", f"{FW}{FW}师父停了三天。\n"),
    ("单行规范-尾随空行", f"{FW}{FW}师父停了三天。\n\n"),
    ("单行规范-前导换行", f"\n{FW}{FW}师父停了三天。"),
    ("多行脏-首尾空行", "\n师父停了三天。\n\n师兄走了。\n\n"),
    # —— 退化输入 ——
    ("空串", ""),
    ("纯空白-空格", "   "),
    ("纯空白-混换行", "   \n\n  \n"),
    ("纯换行", "\n\n\n"),
    ("仅全角空白", f"{FW}{FW}"),
]


class TestGuardPureFunctionInvariant:
    """I3（#1111 验收）：need(c,t) == (N(c,t) != c) 恒成立。"""

    @pytest.mark.parametrize(("name", "content"), INVARIANT_INPUTS)
    def test_guard_iff_pure_function_changes_content(self, name: str, content: str) -> None:
        need = chapter_content_needs_normalize(content, TITLE)
        changed = normalize_chapter_content(content, TITLE) != content
        assert need == changed, (
            f"[{name}] 守卫与纯函数不一致（守卫说 {'脏' if need else '干净'}，"
            f"纯函数{'改了' if changed else '没改'}）\n"
            f"  输入: {content!r}\n"
            f"  need: {need}\n"
            f"  N   : {normalize_chapter_content(content, TITLE)!r}"
        )


class TestSingleLineWhitespacePreserved:
    """单行带前导空白：#1111 发现的额外反例 —— 守卫已判干净，纯函数必须原样返回。"""

    @pytest.mark.parametrize(
        ("name", "content"),
        [
            ("前导全角", f"{FW}师父停了三天。"),
            ("前导半角", " 师父停了三天。"),
            ("前导全角x2", f"{FW}{FW}师父停了三天。"),
            ("前导混合", f" {FW}师父停了三天。"),
        ],
    )
    def test_guard_clean_single_line_returned_verbatim(self, name: str, content: str) -> None:
        assert (
            chapter_content_needs_normalize(content, TITLE) is False
        ), f"[{name}] 前置：守卫应判单行（含前导空白）为干净"
        assert normalize_chapter_content(content, TITLE) == content, (
            f"[{name}] 守卫判干净但纯函数改写了单行正文\n"
            f"  输入: {content!r}\n"
            f"  输出: {normalize_chapter_content(content, TITLE)!r}"
        )


class TestIssueExampleLocked:
    """issue #1111 正文里的原始实证，逐字节锁死。"""

    def test_issue_verbatim_example(self) -> None:
        c = "师父停了三天。"
        assert chapter_content_needs_normalize(c, "第1章 雪夜怪梦") is False
        assert normalize_chapter_content(c, "第1章 雪夜怪梦") == c


class TestNoDeleteRegression:
    """#1112 I4 回归护栏：修 F1/F2 **不得**靠放宽守卫（那会删正文段落）。

    这些形态来自既有契约（#1095/#1112/#1001），修复后必须逐字节保持。
    """

    @pytest.mark.parametrize(
        ("name", "content", "expected", "fragments"),
        [
            # 带全角缩进的 title 等价行 = 正文段落（#1112 铁律：不得判重删除）
            (
                "全角缩进 title 等价单行",
                f"{FW}{TITLE}",
                f"{FW}{FW}{TITLE}",
                (TITLE,),
            ),
            (
                "全角缩进 title 等价多行首行",
                f"{FW}{TITLE}\n\n{FW}正文第一段。",
                f"{FW}{FW}{TITLE}\n\n{FW}{FW}正文第一段。",
                (TITLE, "正文第一段。"),
            ),
            # 前导空行使 title 不在 line[0] → 是正文，不得删
            (
                "前导空行+title",
                f"\n\n{TITLE}\n\n正文第一段。",
                f"{FW}{FW}{TITLE}\n\n{FW}{FW}正文第一段。",
                (TITLE, "正文第一段。"),
            ),
            (
                "正文中重复出现章名",
                f"{TITLE}\n\n正文零。\n\n{TITLE}\n\n正文第一段。",
                f"{FW}{FW}正文零。\n\n{FW}{FW}{TITLE}\n\n{FW}{FW}正文第一段。",
                (TITLE, "正文第一段。"),
            ),
        ],
    )
    def test_body_paragraphs_never_deleted(
        self, name: str, content: str, expected: str, fragments: tuple[str, ...]
    ) -> None:
        out = normalize_chapter_content(content, TITLE)
        for frag in fragments:
            assert (
                frag in out
            ), f"[{name}] 归一删除了正文片段 {frag!r}\n  输入: {content!r}\n  输出: {out!r}"
        assert out == expected, f"[{name}] 归一结果变化\n  实际: {out!r}\n  期望: {expected!r}"
