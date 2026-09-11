"""#1095 RED 契约 — 章节正文格式归一（normalize_chapter_content）.

来源: issue #1095（章节正文格式未归一：重复标题 / markdown # / 无全角缩进）
同族上游: #999（normalize_chapter_title，只归一 title 字段）

契约面（决策点 4 拍板 = A 统一去掉首行标题）:
  归一函数落点 = domain/models/chapter.py（与 normalize_chapter_title 同文件，
  避免 models→services 反向依赖；chapter_service 侧 re-export 供落库路径使用）

  P1 首行标题剥离
     - 首行 trim 后 == title → 删除该行（含其后空行）
     - 首行带 markdown 前缀（# / ##）× title → 同样删除
     - 首行「标题（markdown 包裹）」→ 删除
     - 首行归一后与归一后的 title 相等（序号形态不同，如 第1章 vs 第一章）→ 删除
  P2 markdown 标题前缀剥离（作用于正文并回写，非只读）
     - 正文中间的 # 行 → 去 # 保留文字
  P3 段首全角缩进
     - 每个非空段落前置 U+3000 x2
     - 已有全角缩进 → 幂等跳过（不得二次缩进）
     - 已有半角缩进 → 归一为全角（不叠加）
  P4 幂等
     - normalize(normalize(x)) == normalize(x)
  P5 反例（正常文本不被破坏）
     - 无标题行的干净多段正文 → 只加缩进，不加标题、不删内容
     - 空串 / 纯空白 → 返回空
     - 正文中与 title 同名的非首行句子 → 不删除
"""

from __future__ import annotations

from inkflow.domain.models.chapter import normalize_chapter_content

FULLWIDTH = "\u3000"

TITLE = "第1章 雪夜怪梦"


class TestP1FirstLineTitleStripping:
    """P1: 首行重复标题必须剥离（issue #1095 子现象 1，实测 7/10 章）。"""

    def test_plain_duplicate_first_line_removed(self) -> None:
        """首行与 title 完全相同的裸标题行 → 删除该行及其后空行。"""
        content = f"{TITLE}\n\n师父停了三天。\n\n李慕白醒了。"
        out = normalize_chapter_content(content, TITLE)
        assert TITLE not in out
        assert out.startswith(f"{FULLWIDTH}{FULLWIDTH}师父停了三天。")

    def test_hash_prefixed_first_line_removed(self) -> None:
        """首行 `# <title>`（markdown 标题）= issue #1095 子现象 2（实测 2 章）。"""
        content = f"# {TITLE}\n\n师父停了三天。"
        out = normalize_chapter_content(content, TITLE)
        assert "#" not in out
        assert TITLE not in out
        assert "师父停了三天。" in out

    def test_h2_prefixed_first_line_removed(self) -> None:
        """`## <title>` 同样剥离（形态鲁棒性）。"""
        content = f"## {TITLE}\n\n师父停了三天。"
        out = normalize_chapter_content(content, TITLE)
        assert "#" not in out
        assert "师父停了三天。" in out

    def test_title_inside_markdown_wrapper_removed(self) -> None:
        """`**<title>**` 粗体包裹的首行 → 剥离（markdown 装饰不阻碍识别）。"""
        content = f"**{TITLE}**\n\n师父停了三天。"
        out = normalize_chapter_content(content, TITLE)
        assert TITLE not in out
        assert "**" not in out
        assert "师父停了三天。" in out

    def test_numbering_form_difference_still_stripped(self) -> None:
        """首行序号形态与 title 不同（第1章 vs 第一章）但归一后相等 → 剥离。

        复用 #999 normalize_chapter_title 的序号归一能力（同族一致性）。
        """
        content = "第一章 雪夜怪梦\n\n师父停了三天。"
        out = normalize_chapter_content(content, TITLE)
        assert "雪夜怪梦" not in out
        assert "师父停了三天。" in out

    def test_same_sentence_not_first_line_is_kept(self) -> None:
        """反例：与 title 同名但**不在首行**的正文句子 → 必须保留。"""
        content = f"师父停了三天。\n\n{TITLE}\n\n李慕白醒了。"
        out = normalize_chapter_content(content, TITLE)
        assert "李慕白醒了。" in out
        assert out.count("师父停了三天。") == 1


class TestP2MarkdownPrefixWriteback:
    """P2: `#` 剥离从「只读计数」提升为「可写归一」（issue #1095 根因 2）。"""

    def test_mid_content_hash_line_stripped(self) -> None:
        """正文中间的小标题行 `# 某人` → 去 # 保留文字（不回写则 # 落库）。"""
        content = "# 归途\n\n师父停了三天。\n\n## 夜谈\n\n李慕白醒了。"
        out = normalize_chapter_content(content, TITLE)
        assert "#" not in out
        assert "归途" in out
        assert "夜谈" in out

    def test_code_fence_and_bold_cleaned(self) -> None:
        """markdown 装饰（代码块 / 行内 code / 粗体）随归一清除。"""
        content = f"{TITLE}\n\n```\ncode block\n```\n\n**强调**文本。"
        out = normalize_chapter_content(content, TITLE)
        assert "```" not in out
        assert "**" not in out
        assert "强调" in out


class TestP3CjkIndent:
    """P3: 每非空段落前置全角双空格（issue #1095 子现象 3，实测 0/58 行）。"""

    def test_each_paragraph_indented(self) -> None:
        content = f"{TITLE}\n\n师父停了三天。\n\n李慕白醒了。\n\n他推开窗。"
        out = normalize_chapter_content(content, TITLE)
        paragraphs = [p for p in out.split("\n") if p.strip()]
        assert paragraphs, "归一出空正文 — 契约失效"
        for para in paragraphs:
            assert para.startswith(FULLWIDTH * 2), f"段首缺全角缩进: {para!r}"

    def test_existing_fullwidth_indent_not_doubled(self) -> None:
        """已有全角缩进 → 幂等跳过（不得二次缩进）。"""
        content = f"{FULLWIDTH * 2}师父停了三天。"
        out = normalize_chapter_content(content, TITLE)
        assert out.startswith(FULLWIDTH * 2)
        assert not out.startswith(FULLWIDTH * 3)

    def test_halfwidth_indent_normalized_to_fullwidth(self) -> None:
        """半角缩进 → 归一为全角，不叠加成混合缩进。"""
        content = "  师父停了三天。"
        out = normalize_chapter_content(content, TITLE)
        assert out.startswith(FULLWIDTH * 2)
        assert not out.startswith(" ")


class TestP4Idempotency:
    """P4: 二次执行不得改变结果（防二次缩进 —— issue 验收硬要求）。"""

    def test_full_shape_idempotent(self) -> None:
        content = f"# {TITLE}\n\n师父停了三天。\n\n李慕白醒了。"
        once = normalize_chapter_content(content, TITLE)
        twice = normalize_chapter_content(once, TITLE)
        assert once == twice

    def test_indent_only_idempotent(self) -> None:
        content = f"{FULLWIDTH * 2}师父停了三天。\n\n{FULLWIDTH * 2}李慕白醒了。"
        once = normalize_chapter_content(content, TITLE)
        twice = normalize_chapter_content(once, TITLE)
        assert once == twice
        assert once.count(FULLWIDTH * 2) == 2


class TestP5CounterExamples:
    """P5: 正常文本反例 —— 归一不得破坏干净的内容。"""

    def test_clean_text_keeps_all_content(self) -> None:
        """干净多段正文：文字零丢失，仅补缩进。"""
        content = "师父停了三天。\n\n李慕白醒了。\n\n他推开窗。"
        out = normalize_chapter_content(content, TITLE)
        for sentence in ("师父停了三天。", "李慕白醒了。", "他推开窗。"):
            assert sentence in out

    def test_empty_content_returns_empty(self) -> None:
        assert normalize_chapter_content("", TITLE) == ""

    def test_whitespace_only_returns_empty(self) -> None:
        assert normalize_chapter_content("   \n\n  \n", TITLE).strip() == ""


class TestP6CountWordsConsistency:
    """P6: count_words 与可见正文一致（issue 影响面：显示字数 ≠ 可见文本）。"""

    def test_word_count_matches_visible_text(self) -> None:
        """归一后计数 == 对可见正文字符的计数（# 与标题行不再虚增）。"""
        from inkflow.domain.services._word_count import count_words

        dirty = f"# {TITLE}\n\n师父停了三天。"
        clean = normalize_chapter_content(dirty, TITLE)
        # 归一后：`#`/标题已消失 → 计数等于干净文本的计数
        assert count_words(clean) == count_words("师父停了三天。")
