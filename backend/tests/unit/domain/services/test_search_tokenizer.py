"""F22 全文搜索分词与预处理纯函数单元测试 — jieba 封装纯函数，无 I/O.

RED 阶段：inkflow/domain/services/_search_tokenizer.py 不存在 → 收集期
ModuleNotFoundError 即预期失败形态（collected 0 items + 1 error，exit 2）。

测试范围（spec §5.5 ①-⑤ + §9.2 关键场景 1/4/10 + §7 E9/E10 + §13 M7/M9）：
escape_xml 转义、tokenize 中文词拆分与过滤（纯标点/英文单字母/空白剔除、
单字符中文保留）、build_match MATCH 构造（FTS5 保留字引号保护）、
prepare_index_text 全链路（HTML 标签字面转义）。

依据: specs/f22-search-service/spec.md §5.5（分词预处理）/ §7 E9/E10 /
§9.2 / §13 M7/M9。

jieba 说明：jieba 首次 import 加载词典 ~1s（0.42.1 已锁定，缓存后 ~0.4s）。
RED 阶段模块缺失于收集期失败、不触达 jieba；GREEN 阶段随 _search_tokenizer
模块加载触发一次即可，无需特殊处理。本文件不直接 import jieba（避免 F401
未使用导入）——tokenize 断言即 jieba 行为断言，实测输出见各用例 docstring。

设计假设（RED 阶段按 spec 口径记录，实现须满足）:
- 模块路径: inkflow/domain/services/_search_tokenizer.py（_style_analyzer.py
  同族下划线私有纯函数模块先例，spec §8.1 CREATE 清单），导出 escape_xml /
  tokenize / build_match / prepare_index_text。
- escape_xml(text: str) -> str：仅转义 & < > " 四字符为 &amp; &lt; &gt; &quot;
  （§5.5 ①，防 snippet 注入 + 防 FTS5 语法混淆）；& 必须先于 < > " 转义
  （"<" → "&lt;" 后 & 不得二次转义为 "&amp;lt;"）；普通文本原样返回。
- tokenize(text: str) -> list[str]：jieba.cut_for_search(text) 词序列（§5.5 ③，
  搜索引擎模式长词+子词）后过滤（§5.5 ④）：
  - 剔除空白 token（jieba 对空格返回 " "）；
  - 剔除纯标点 token（"。。。" 拆为三个 "。"，全剔除）；
  - 剔除纯符号 token（如 "&"）；剔除英文单字母 token（"a"）；
  - 保留单字符中文词（"龙"、"的"）；保留多字符中英文词与数字（"苏醒"/"the"/"123"）。
- build_match(tokens: list[str]) -> str：每词双引号包裹、空格连接（§5.5 查询侧，
  ["龙","苏醒"] → '"龙" "苏醒"'）；引号同时保护 FTS5 保留字 AND/OR/NOT（E9/M7）；
  空列表 → 返回空串。
- prepare_index_text(title: str, body: str) -> str：escape_xml(title + " " + body)
  → tokenize → 空格连接（§5.5 ②-⑤ 全链路，入库 body 列）。
- jieba 0.42.1 实测（RED 阶段验证，GREEN 断言按此形态）:
  - cut_for_search("龙的苏醒") == ["龙", "的", "苏醒"]——单字 "龙" 可拆出；
  - cut_for_search("北京大学") == ["北京", "大学", "北京大学"]——长词+子词；
  - cut_for_search("古井深处龙瞳睁开") == ["古井", "深处", "龙瞳", "睁开"]——
    "龙瞳" 是整词典词、不拆 "龙" 子词（§9.2 场景 1 文本，断言稳定词 "龙瞳"）；
  - cut_for_search("。。。") == ["。", "。", "。"]；
  - cut_for_search("a 龙 the 123") == ["a", " ", "龙", " ", "the", " ", "123"]；
  - cut_for_search("&lt;b&gt;龙&lt;/b&gt; 苏醒") 拆出 "&"/"lt"/"b" 等碎片——
    转义实体无字面 "<b>" 形态（E10 断言：结果不含 "<b>"/"</b>" 字面标签）。
"""

from __future__ import annotations

from inkflow.domain.services._search_tokenizer import (
    build_match,
    escape_xml,
    prepare_index_text,
    tokenize,
)


class TestEscapeXml:
    """escape_xml 转义（§5.5 ①，防 snippet 注入 + 防 FTS5 语法混淆）."""

    def test_ampersand(self) -> None:
        """& → &amp;."""
        assert escape_xml("&") == "&amp;"

    def test_less_than(self) -> None:
        """< → &lt;（& 不得二次转义——"<" 必须产出 "&lt;" 而非 "&amp;lt;"）."""
        assert escape_xml("<") == "&lt;"

    def test_greater_than(self) -> None:
        """> → &gt;."""
        assert escape_xml(">") == "&gt;"

    def test_double_quote(self) -> None:
        """ " → &quot;."""
        assert escape_xml('"') == "&quot;"

    def test_plain_text_unchanged(self) -> None:
        """无特殊字符的普通文本原样返回."""
        assert escape_xml("普通文本 123 abc") == "普通文本 123 abc"

    def test_combined(self) -> None:
        """多字符混合文本逐个转义（含引号属性形态）."""
        assert escape_xml('<a href="x">&') == "&lt;a href=&quot;x&quot;&gt;&amp;"

    def test_entity_like_input_single_pass(self) -> None:
        """输入含实体样文本（"&lt;"）时 & 仍单遍转义为 &amp;lt;，不识别既有实体."""
        assert escape_xml("&lt;") == "&amp;lt;"


class TestTokenize:
    """tokenize 分词与过滤（§5.5 ③④，jieba.cut_for_search + 过滤）."""

    def test_empty_text(self) -> None:
        """空文本 → 空列表."""
        assert tokenize("") == []

    def test_whitespace_only(self) -> None:
        """纯空白文本（空格 token 全剔除）→ 空列表."""
        assert tokenize("   ") == []

    def test_chinese_split_contains_dragon(self) -> None:
        """中文词拆分：查询 "龙" 场景文本（§9.2 场景 1 同族）拆出单字 "龙"."""
        tokens = tokenize("龙的苏醒")
        assert "龙" in tokens
        assert "苏醒" in tokens

    def test_single_char_chinese_kept(self) -> None:
        """单字符中文词保留（§5.5 ④："龙" 是有效查询；"的" 同属单字中文）."""
        tokens = tokenize("龙的苏醒")
        assert "的" in tokens

    def test_cut_for_search_long_and_subword(self) -> None:
        """cut_for_search 长词+子词：北京大学 → 北京 + 大学 + 北京大学（§5.5 ③）."""
        assert tokenize("北京大学") == ["北京", "大学", "北京大学"]

    def test_index_scene_text_stable_words(self) -> None:
        """§9.2 场景 1 文本 "古井深处龙瞳睁开"：断言稳定词（"龙瞳" 为整词典词）."""
        tokens = tokenize("古井深处龙瞳睁开")
        assert "古井" in tokens
        assert "龙瞳" in tokens

    def test_pure_punctuation_filtered(self) -> None:
        """纯标点文本 → 空列表（M9：纯标点查询空结果的 tokenizer 侧依据）."""
        assert tokenize("。。。") == []

    def test_punctuation_token_filtered(self) -> None:
        """词间标点 token 剔除，中文词保留."""
        assert tokenize("龙。苏醒") == ["龙", "苏醒"]

    def test_single_english_letter_filtered(self) -> None:
        """英文单字母剔除、多字母英文词/数字/单字中文保留（§5.5 ④边界）."""
        assert tokenize("a 龙 the 123") == ["龙", "the", "123"]

    def test_whitespace_token_filtered(self) -> None:
        """jieba 拆出的空白 token（" "）剔除，不进入结果."""
        assert " " not in tokenize("a 龙 the 123")


class TestBuildMatch:
    """build_match MATCH 构造（§5.5 查询侧：每词双引号包裹空格连接）."""

    def test_basic(self) -> None:
        """多词 → '"词" "词"' 空格连接."""
        assert build_match(["龙", "苏醒"]) == '"龙" "苏醒"'

    def test_single(self) -> None:
        """单词 → 单个双引号词."""
        assert build_match(["龙"]) == '"龙"'

    def test_fts5_reserved_words_quoted(self) -> None:
        """FTS5 保留字 AND/OR/NOT 被引号包裹按普通词处理（E9/M7）."""
        assert build_match(["AND", "OR", "NOT"]) == '"AND" "OR" "NOT"'

    def test_empty(self) -> None:
        """空 tokens → 空串（分词后无有效词 → 空结果，§3.3）."""
        assert build_match([]) == ""


class TestPrepareIndexText:
    """prepare_index_text 全链路（§5.5 ②-⑤：拼接 → 转义 → 分词 → 空格连接）."""

    def test_full_pipeline(self) -> None:
        """title + body 全链路：含标题与正文的关键词 token，空格连接."""
        result = prepare_index_text("第 3 章 龙的苏醒", "古井深处，龙瞳睁开。")
        words = result.split()
        assert "龙" in words
        assert "苏醒" in words
        assert "龙瞳" in words
        assert " " in result  # 空格连接（§5.5 ⑤）

    def test_html_tags_escaped_literal(self) -> None:
        """正文 HTML 标签按字面转义，不出现字面 "<b>"（E10/M7）."""
        result = prepare_index_text("<b>龙</b>", "苏醒")
        assert "<b>" not in result
        assert "</b>" not in result
        assert "龙" in result
        assert "苏醒" in result

    def test_empty_body(self) -> None:
        """空 body：仅标题参与索引."""
        assert prepare_index_text("龙", "") == "龙"
