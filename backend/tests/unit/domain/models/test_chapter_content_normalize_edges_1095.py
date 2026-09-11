"""#1095 归一边界分支覆盖 — 补齐 coverage-backend 分支门禁（branch >= 95%）。

CI 门禁实证：首轮实现后 branch coverage 94.99% < 95.0%。
本文件覆盖 normalize_chapter_content / chapter_content_needs_normalize 的
**防御分支与边界**，不重复主契约文件（test_chapter_content_normalize_1095.py）
已覆盖的主路径。

覆盖目标（父侧 coverage json 定位）：
  chapter.py:183   _is_duplicate_title_line → 首行装饰剥离后为空 → False
  chapter.py:186   _is_duplicate_title_line → 归一后 title 为空 → False
  chapter.py:201   _has_noncanonical_indent → 空行 continue
  chapter.py:206   _has_noncanonical_indent → 遍历完无脏行 → False
  chapter.py:204   → 199 回边（多行，全规范）
"""

from __future__ import annotations

from inkflow.domain.models.chapter import (
    chapter_content_needs_normalize,
    normalize_chapter_content,
)

FULLWIDTH = "\u3000"


class TestDuplicateTitleLineEdgeBranches:
    """_is_duplicate_title_line 的两个防御分支。"""

    def test_decoration_only_first_line_is_not_title(self) -> None:
        """首行只有 markdown 装饰（`#` / `**`）→ 剥离后为空 → 不判为标题行。

        覆盖 chapter.py:183 —— 否则会因空串与 title 不等而误判。
        """
        content = "#\n\n师父停了三天。"
        # 装饰剥离后 candidate == "" → 不应被当成重复标题（只做 markdown 剥离）
        assert chapter_content_needs_normalize(content, "第1章 雪夜怪梦") is True

    def test_empty_title_never_matches(self) -> None:
        """title 为空 → 不认为存在重复标题行（覆盖 chapter.py:186）。

        空 title 下不应把任意文本行误删；缩进仍应归一。
        """
        content = "师父停了三天。\n\n李慕白醒了。"
        out = normalize_chapter_content(content, "")
        assert "师父停了三天。" in out
        assert "李慕白醒了。" in out


class TestIndentScanEdgeBranches:
    """_has_noncanonical_indent 的空行 continue 与扫描收敛分支。"""

    def test_blank_lines_between_paragraphs_skipped(self) -> None:
        """段落间空行 → continue（覆盖 chapter.py:201），不误判为脏缩进。"""
        content = f"{FULLWIDTH * 2}师父停了三天。\n\n{FULLWIDTH * 2}李慕白醒了。"
        assert chapter_content_needs_normalize(content, "第1章 雪夜怪梦") is False

    def test_leading_blank_lines_then_clean_paragraphs(self) -> None:
        """开头空行 + 后续全规范 → 扫描收敛到 False（覆盖 chapter.py:206 与 204→199 回边）。"""
        content = f"\n\n{FULLWIDTH * 2}师父停了三天。\n\n{FULLWIDTH * 2}李慕白醒了。\n"
        assert chapter_content_needs_normalize(content, "第1章 雪夜怪梦") is False
        # 幂等：规范内容重复归一逐字节不变
        assert normalize_chapter_content(content, "第1章 雪夜怪梦") == (
            f"{FULLWIDTH * 2}师父停了三天。\n\n{FULLWIDTH * 2}李慕白醒了。"
        )

    def test_single_line_content_not_indent_flagged(self) -> None:
        """单行正文 → 不纳入缩进归一（既有契约：单行 content 逐字节往返）。"""
        assert chapter_content_needs_normalize("师父停了三天。", "第1章 雪夜怪梦") is False
