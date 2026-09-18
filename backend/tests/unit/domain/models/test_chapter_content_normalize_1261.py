"""#1261 RED 契约 — 收口阶段剥离「标题回声」（修 #1095 回归）。

来源: issue #1261（v0.15.0-rc2 打包产物实测：10 章中 5 章正文首行重复输出标题）

根因（实证，非推测）
--------------------
「缩进先于标题剥离」在**内容层无法修复**——它需要推翻 #1112 铁律：

    #1112 保护:  `　　<title>` 是**正文段落**（编辑器手写正文可能与章名同文）
    #1261 待剥离: `　　第1章 梦境觉醒…` 是**待剥离标题**

两者**逐字节同构**，且走同一个 `normalize_chapter_content(content, title)`，
故判据只能落在**流水线阶段**：确认收口（`draft_service.confirm`）是唯一
「知道首行是标题回声」的阶段 —— 草稿层当归一时 `title=""`（draft_service.py:118），
无从识别标题，首行被加上缩进；收口时才有真实 title 可用。

真实链路（draft_service.py:118 → :242）
---------------------------------------
    ① 草稿落库  normalize_chapter_content(content, "")   ← title 空 → 剥离跳过
    ② 首行被加缩进                          → "　　第1章 xxx"
    ③ 收口      strip_first_line_title_echo(draft.content, title)  ← 本轨修复点
    ④ 落库归一  chapter_service.update_chapter → 通用归一（缩进正文）

契约
----
C1 收口剥离：缩进形态的首行标题回声 → 剥离（issue 主现象，实测 5/9 章）
C2 缩进正确：剥离后每个正文段恰有一段 U+3000×2 前导（不多不少）
C3 反向断言：剥离不得依赖「无缩进」前提 —— 三档缩进宽度结果一致
C4 保真：非回声首行（正文 / 中部同名段 / 空 title）→ 逐字节原样
C5 #1112 铁律零回归：通用归一/守卫仍视 `　　<title>` 为正文段落
C6 真实链路：issue 表格 4 个失败章标题全部修复
"""

from __future__ import annotations

import pytest

from inkflow.domain.models.chapter import (
    chapter_content_needs_normalize,
    normalize_chapter_content,
    strip_first_line_title_echo,
)

FW = "\u3000"
TITLE = "第1章 梦境觉醒：异乡人的第一天"


class TestC1TitleEchoStripped:
    """C1: 首行标题回声必须剥离（issue #1261 主现象）。"""

    def test_indented_title_echo_removed(self) -> None:
        """🔴 主用例：`　　第1章 …` → 剥离（issue 表格 5 章的实际形态）。"""
        out = strip_first_line_title_echo(f"{FW}{FW}{TITLE}\n\n梦里有光。", TITLE)
        assert TITLE not in out, f"标题回声未剥离: {out!r}"
        assert out == "梦里有光。"

    def test_single_fullwidth_indent_echo_removed(self) -> None:
        """单个 U+3000 缩进的回声 → 剥离（阈值边界）。"""
        out = strip_first_line_title_echo(f"{FW}{TITLE}\n\n梦里有光。", TITLE)
        assert TITLE not in out, f"单全角缩进回声未剥离: {out!r}"

    def test_halfwidth_indent_echo_removed(self) -> None:
        """半角空格缩进的回声 → 剥离。"""
        out = strip_first_line_title_echo(f"  {TITLE}\n\n梦里有光。", TITLE)
        assert TITLE not in out, f"半角缩进回声未剥离: {out!r}"

    def test_leading_blank_then_echo_removed(self) -> None:
        """前导空行 + 回声行 → 仍剥离。"""
        out = strip_first_line_title_echo(f"\n\n{FW}{FW}{TITLE}\n\n梦里有光。", TITLE)
        assert TITLE not in out, f"前导空行的回声未剥离: {out!r}"
        assert out == "梦里有光。"

    def test_chinese_numeral_echo_removed(self) -> None:
        """序号形态差异（第一章 vs 第1章）→ 仍剥离（#999 归一能力）。"""
        content = f"{FW}{FW}第一章 梦境觉醒：异乡人的第一天\n\n梦里有光。"
        out = strip_first_line_title_echo(content, TITLE)
        assert "梦境觉醒" not in out, f"序号差异回声未剥离: {out!r}"


class TestC2IndentAfterStrip:
    """C2: 剥离后经通用归一 → 每段恰有一段 U+3000×2 前导。"""

    def test_paragraphs_indented_exactly_once(self) -> None:
        stripped = strip_first_line_title_echo(f"{FW}{FW}{TITLE}\n\n梦里有光。\n\n他醒了。", TITLE)
        out = normalize_chapter_content(stripped, TITLE)
        paragraphs = [p for p in out.split("\n") if p.strip()]
        assert len(paragraphs) == 2, f"段落数不为 2（标题未剥离或段落丢失）: {out!r}"
        for para in paragraphs:
            assert para.startswith(f"{FW}{FW}"), f"段首缺缩进: {para!r}"
            assert not para.startswith(f"{FW}{FW}{FW}"), f"段落被二次缩进: {para!r}"


class TestC3ReverseAssertion:
    """C3: 反向断言 —— 剥离不得依赖「无缩进」这一偶然前提。

    若把修复退回「缩进先、剥离后」的顶格铁律路径，
    缩进形态（n=1,2）会拒识 → 本类必红。
    """

    @pytest.mark.parametrize("indent_units", [1, 2])
    def test_strip_independent_of_indent_width(self, indent_units: int) -> None:
        out = strip_first_line_title_echo(f"{FW * indent_units}{TITLE}\n\n梦里有光。", TITLE)
        assert TITLE not in out, (
            f"[C3] 缩进 {indent_units} 档下回声未被剥离 —— 剥离依赖了「无缩进」前提"
            f"\n  输出: {out!r}"
        )
        assert out == "梦里有光。"

    def test_echo_is_specifically_indented_title(self) -> None:
        """判据同源性佐证：顶格行由通用归一路径处理，不属回声。"""
        content = f"{TITLE}\n\n梦里有光。"
        assert strip_first_line_title_echo(content, TITLE) == content


class TestC4Fidelity:
    """C4: 非回声首行 → 逐字节原样（不得误删合法正文）。"""

    @pytest.mark.parametrize(
        ("name", "content"),
        [
            ("顶格标题（归一路径管）", f"{TITLE}\n\n梦里有光。"),
            ("普通正文", "梦里有光。\n\n他醒了。"),
            ("顶格同名正文段", f"{TITLE}\n\n正文。"),
            ("空 title", f"{FW}{FW}{TITLE}\n\n梦里有光。"),
            ("空串", ""),
            ("纯空白", "   \n\n  \n"),
        ],
    )
    def test_non_echo_untouched(self, name: str, content: str) -> None:
        title = "" if name == "空 title" else TITLE
        assert strip_first_line_title_echo(content, title) == content, f"[{name}] 非回声被改写"

    def test_mid_body_same_name_paragraph_kept(self) -> None:
        """正文中部与 title 同文的段落 → 保留（只处理首行）。"""
        content = f"{FW}{FW}{TITLE}\n\n正文零。\n\n{FW}{FW}{TITLE}\n\n正文第一段。"
        out = strip_first_line_title_echo(content, TITLE)
        assert "正文零。" in out
        assert "正文第一段。" in out
        assert out.count(TITLE) == 1, f"应只删首行回声，实得: {out!r}"

    @pytest.mark.parametrize(
        ("name", "content"),
        [
            ("回声首行", f"{FW}{FW}{TITLE}\n\n梦里有光。"),
            ("已剥离正文", f"{FW}{FW}梦里有光。"),
            ("顶格标题", f"{TITLE}\n\n梦里有光。"),
            ("中部同名", f"{FW}{FW}{TITLE}\n\n正文零。\n\n{FW}{FW}{TITLE}\n\n正文一。"),
            ("空串", ""),
        ],
    )
    def test_idempotent(self, name: str, content: str) -> None:
        """幂等：重复收口不得再改变结果（防重复 confirm 再删正文）。"""
        once = strip_first_line_title_echo(content, TITLE)
        twice = strip_first_line_title_echo(once, TITLE)
        assert once == twice, f"[{name}] 非幂等: {once!r} -> {twice!r}"

    def test_title_only_content_becomes_empty(self) -> None:
        """全篇仅标题行 → 剥成空串（不产生幽灵空段）。"""
        assert strip_first_line_title_echo(f"{FW}{FW}{TITLE}", TITLE) == ""


class TestC5NoRegression1112:
    """C5: #1112 顶格铁律零回归 —— 通用归一/守卫仍视 `　　<title>` 为正文段落。"""

    def test_generic_normalize_still_preserves_indented_title(self) -> None:
        """（#1112 I4）通用归一仍保留缩进 title 等价行 —— 本轨不得推翻。"""
        content = f"{FW}{TITLE}\n\n{FW}正文第一段。"
        out = normalize_chapter_content(content, TITLE)
        assert TITLE in out, f"[C5] 推翻 #1112 铁律（缩进 title 应作正文保留）: {out!r}"
        assert "正文第一段。" in out

    def test_leading_blank_title_paragraph_preserved(self) -> None:
        """（#1121 I4 护栏）前导空行使 title 属正文 → 两次归一后仍保留。"""
        content = f"\n\n{TITLE}\n\n正文第一段。"
        once = normalize_chapter_content(content, TITLE)
        twice = normalize_chapter_content(once, TITLE)
        assert TITLE in twice, f"[C5] 二次归一删除了正文段: {once!r} -> {twice!r}"

    def test_guard_invariant_holds(self) -> None:
        """（#1111 I3）need(x) == (N(x) != x) 对回声形态成立。"""
        for content in (f"{FW}{FW}{TITLE}\n\n梦里有光。", f"{TITLE}\n\n梦里有光。", "梦里有光。"):
            need = chapter_content_needs_normalize(content, TITLE)
            changed = normalize_chapter_content(content, TITLE) != content
            assert need == changed, f"守卫不一致: {content!r} need={need} changed={changed}"


class TestC6RealPathRegression:
    """C6: 复现 issue #1261 完整链路（草稿归一 → 收口剥离 → 落库归一）。"""

    def test_draft_then_confirm_pipeline(self) -> None:
        raw = f"{TITLE}\n\n梦里有光。"
        drafted = normalize_chapter_content(raw, "")  # ① 草稿落库，title 空 → 加缩进
        assert drafted.startswith(FW), "前置：草稿路径应对首行加缩进"
        stripped = strip_first_line_title_echo(drafted, TITLE)  # ③ 收口剥离回声
        confirmed = normalize_chapter_content(stripped, TITLE)  # ④ 落库归一
        assert TITLE not in confirmed, (
            f"[C6] 真实链路未修复：收口后标题仍在正文\n"
            f"  草稿: {drafted!r}\n  剥离: {stripped!r}\n  落库: {confirmed!r}"
        )
        assert "梦里有光。" in confirmed

    @pytest.mark.parametrize(
        "title",
        [
            "第1章 梦境觉醒：异乡人的第一天",
            "第3章 带着宁晚长大：两个孩子的日常",
            "第6章 雪夜遗命：继续救人",
            "第7章 灵堂见人心：谁来了，谁没来",
            "第10章 续灯：一剂一剂，卷末人心小聚",
        ],
    )
    def test_issue_table_titles(self, title: str) -> None:
        """issue #1261 表格里 5 个真实失败章标题 → 全部修复。"""
        raw = f"{title}\n\n天没亮透，蜀山小院的檐下响了三声咳嗽。"
        drafted = normalize_chapter_content(raw, "")
        stripped = strip_first_line_title_echo(drafted, title)
        confirmed = normalize_chapter_content(stripped, title)
        assert title not in confirmed, (
            f"issue 实测失败章未修复: {title!r}\n  落库产物: {confirmed!r}"
        )
        assert "天没亮透" in confirmed
