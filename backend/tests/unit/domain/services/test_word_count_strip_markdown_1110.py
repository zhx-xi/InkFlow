"""#1110 RED 契约 — _strip_markdown 强调标记剥离须要求成对/边界.

来源: issue #1110（#1095 影响放大器：strip 正则 ``\\*{1,3}|_{1,3}`` 不要求成对，
任何 * / _ 出现 1-3 次即删 —— snake_case/变量名/文件名/数学记号被静默破坏。
#1095 把该能力提升为「可写归一并回写正文」后，后果从字数偏差升级为正文损坏。）

契约面（决策 = 收窄为成对 + 词边界匹配）:
  S1 反例保全（RED 主面，旧实现下必挂）
     - my_var_name / other_thing / a_b_c / 3*4*5 逐字符原样保留
     - count_words 按保全后的词形计数（my var name = 3）
  S2 成对语义不丢（守护面，新旧实现都过，防修过头）
     - *重要* / **必须** / _emphasis_ 仍被正确剥离
     - **多行**（DOTALL）粗体仍被剥离
  S3 词边界（(?<!\\w)/(?!\\w) 防「单词内下划线」被当强调）
     - a_b_c 中间的 _b_ 不得匹配（两侧是单词字符）
     - my _var_ name（两侧空白）正常剥离
  S4 归一回写面（normalize_chapter_content 复用同一真相源）
     - 含 snake_case 的干净单行正文逐字节原样（守卫不动点）
     - 多行归一后 snake_case token 仍在正文里
     - needs_normalize(include_indent=False) 不把 snake_case 判为脏
  S5 计数一致性（#1095 P6 同族）
     - count_words 剥离前后对同一可见文字结果一致

⚠️ 已知取舍（issue 建议正则原样采纳）：CJK 紧邻的 ``他说*重要*的话`` 因
(?<!\\w) 边界不再剥离 —— 保守方向（宁可不剥，绝不破坏正文），见 PR 报备。
"""

from __future__ import annotations

from inkflow.domain.models.chapter import (
    chapter_content_needs_normalize,
    normalize_chapter_content,
)
from inkflow.domain.services._word_count import _strip_markdown, count_words

TITLE = "第1章 雪夜怪梦"


class TestS1SnakeCasePreserved:
    """S1: 非成对 * / _ 是正文字符，不是 markdown —— 必须原样保留。"""

    def test_strip_keeps_snake_case_identifiers(self) -> None:
        assert _strip_markdown("my_var_name") == "my_var_name"
        assert _strip_markdown("other_thing") == "other_thing"
        assert _strip_markdown("a_b_c") == "a_b_c"

    def test_strip_keeps_file_like_token(self) -> None:
        assert _strip_markdown("config_file_path.yaml") == "config_file_path.yaml"

    def test_strip_keeps_unpaired_star_math(self) -> None:
        assert _strip_markdown("3*4*5") == "3*4*5"

    def test_count_words_snake_case_tokens(self) -> None:
        # 保全后按英文单词计数：my/var/name 三段
        assert count_words("my_var_name") == 3
        assert count_words("other_thing") == 2


class TestS2PairedMarkdownStillStripped:
    """S2: 成对强调标记的剥离语义不得丢失（守护既有契约）。"""

    def test_strip_paired_single_star(self) -> None:
        assert _strip_markdown("*重要*") == "重要"

    def test_strip_paired_double_star(self) -> None:
        assert _strip_markdown("**必须**") == "必须"

    def test_strip_paired_underscore(self) -> None:
        assert _strip_markdown("_emphasis_ word") == "emphasis word"

    def test_strip_bold_spanning_newline(self) -> None:
        # DOTALL：跨行粗体仍剥离（旧实现逐符删星号，结果等价，语义保持）
        assert _strip_markdown("**多行\n强调**文字") == "多行\n强调文字"

    def test_strip_paired_keeps_visible_text_count(self) -> None:
        assert count_words("**强调**文字") == count_words("强调文字") == 4


class TestS3WordBoundary:
    """S3: (?<!\\w)/(?!\\w) 边界 —— 防单词内下划线被当强调标记。"""

    def test_boundary_protects_inner_underscore(self) -> None:
        # a_b_c 的中间段 _b_ 两侧均为单词字符 → 不构成强调
        assert _strip_markdown("a_b_c") == "a_b_c"

    def test_spaced_underscore_pair_still_strips(self) -> None:
        assert _strip_markdown("my _var_ name") == "my var name"


class TestS4NormalizeWriteback:
    """S4: 可写归一（#1095）复用同一真相源后，正文不得被破坏。"""

    def test_clean_single_line_with_snake_case_byte_identical(self) -> None:
        # 旧实现：下划线被剥 → 触发归一路径 → 正文损坏（本契约的核心回归）
        content = "调用 my_var_name 函数"
        assert normalize_chapter_content(content, TITLE) == content

    def test_multiline_normalize_keeps_snake_case(self) -> None:
        content = "他写下 my_var_name。\n\n另一个 other_thing。"
        out = normalize_chapter_content(content, TITLE)
        assert "my_var_name" in out
        assert "other_thing" in out

    def test_needs_normalize_false_for_snake_case_only(self) -> None:
        # 导出路径（include_indent=False）：snake_case 不是 markdown 脏数据
        assert (
            chapter_content_needs_normalize("my_var_name 保持原样", TITLE, include_indent=False)
            is False
        )


class TestS5CountVisibleConsistency:
    """S5: count_words 与归一后可见正文一致（#1095 P6 同族）。"""

    def test_count_matches_normalized_visible_text(self) -> None:
        dirty = f"# {TITLE}\n\n他说 **重要** 的事，参数 my_var_name。"
        clean = normalize_chapter_content(dirty, TITLE)
        assert count_words(clean) == count_words("他说 重要 的事，参数 my_var_name。")
