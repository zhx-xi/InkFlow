"""#999 normalize_chapter_title 纯函数单元测试（RED 批，单元层，无 I/O）。

契约锚点：.hermes/plans/999-contract.md §1（签名
``normalize_chapter_title(title: str, fmt: str | None = "arabic") -> str``）。

函数由 inkflow.domain.services.chapter_service 模块级导出。GREEN 前本文件顶层
import 会触发 ImportError —— 这是预期 RED 形态（收集期报错，非误报）。

覆盖：
- 双前缀去重（arabic / chinese / fmt=None）
- 中文↔阿拉伯序号转换（含廿/卅/百/千，30=三十 规范写法）
- 无序号纯名保持 / 中部「第N章」不识别
- 输出分隔归一 / 无尾空格
- 幂等
- 不可转换序号（0 / 10000）保持 + fmt 非法 ValueError
"""

import pytest

from inkflow.domain.services.chapter_service import normalize_chapter_title


class TestDualPrefixDedup:
    """双前缀去重：保留第一个前缀序号，删除后续重复前缀，循环收敛。"""

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("第1章 第一章 风雨前程", "第1章 风雨前程"),
            ("第一章第3章 风雨", "第一章 风雨"),
            ("第1章第一章第2章 x", "第1章 x"),
        ],
    )
    def test_dedup_fmt_none(self, title, expected):
        """fmt=None：去重 + 分隔归一，但保留序号原始形态。"""
        assert normalize_chapter_title(title, fmt=None) == expected

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            # 默认 fmt='arabic'：去重后剩余前缀转阿拉伯
            ("第1章 第一章 风雨前程", "第1章 风雨前程"),
            ("第1章第一章第2章 x", "第1章 x"),
        ],
    )
    def test_dedup_arabic_default(self, title, expected):
        """fmt='arabic'（默认值）：去重后剩余前缀转阿拉伯序号。"""
        assert normalize_chapter_title(title) == expected

    def test_dedup_arabic_converts_kept_chinese_prefix(self):
        """第一章第3章：去重保留第一章，fmt=arabic 再转第1章（分隔归一）。"""
        assert normalize_chapter_title("第一章第3章 风雨", fmt="arabic") == "第1章 风雨"


class TestChineseArabicConversion:
    """中文↔阿拉伯序号转换（fmt 决定输出形态）。"""

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("第三章 风起", "第3章 风起"),
            ("第廿一章", "第21章"),
            ("第卅章", "第30章"),
            ("第一百二十三章", "第123章"),
            ("第三百章", "第300章"),
            ("第二十一章", "第21章"),
            ("第1000章", "第1000章"),  # 阿拉伯输入在 arabic 下形态保持
        ],
    )
    def test_to_arabic(self, title, expected):
        """fmt='arabic'：中文序号 → 阿拉伯序号。"""
        assert normalize_chapter_title(title, fmt="arabic") == expected

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("第21章", "第二十一章"),
            ("第300章", "第三百章"),
            ("第30章", "第三十章"),  # 规范写法 30=三十 非 卅
            ("第123章", "第一百二十三章"),
            ("第1000章", "第一千章"),
            ("第21章 风起", "第二十一章 风起"),  # 带剩余文本
        ],
    )
    def test_to_chinese(self, title, expected):
        """fmt='chinese'：阿拉伯序号 → 中文序号（规范 30=三十 / 300=三百）。"""
        assert normalize_chapter_title(title, fmt="chinese") == expected


class TestNoNumberPassthrough:
    """无序号纯名 / 中部「第N章」不识别，返回 strip 后原样。"""

    @pytest.mark.parametrize(
        "title",
        ["一叶落", "怀念第3章"],
    )
    def test_no_number_kept(self, title):
        """无前缀或中部「第N章」未识别 → 原样（strip 后）。"""
        assert normalize_chapter_title(title) == title

    def test_empty_string(self):
        """空串 → 空串（非空校验交给 DTO 既有逻辑）。"""
        assert normalize_chapter_title("") == ""

    def test_whitespace_only(self):
        """纯空白 → 空串。"""
        assert normalize_chapter_title("   ") == ""


class TestOutputSeparator:
    """前缀 + 单个半角空格 + strip 后剩余文本；无剩余文本时无尾空格。"""

    def test_multi_spaces_collapsed(self):
        """前缀与剩余文本间多空格折叠为单个，尾部空白去除。"""
        assert normalize_chapter_title("第三章   风起  ") == "第3章 风起"

    def test_prefix_no_remainder_no_trailing_space(self):
        """仅有前缀 → 无尾空格。"""
        assert normalize_chapter_title("第3章") == "第3章"

    def test_fmt_none_separator_only(self):
        """fmt=None：去重+分隔归一但序号形态不变。"""
        assert normalize_chapter_title("第一章 风", fmt=None) == "第一章 风"


class TestIdempotent:
    """normalize(normalize(t, f), f) == normalize(t, f)。"""

    @pytest.mark.parametrize(
        ("title", "fmt"),
        [
            ("第1章 第一章 风雨前程", "arabic"),
            ("第三章 风起", "arabic"),
            ("第21章 风起", "chinese"),
            ("第1章 第一章 风雨", None),
            ("一叶落", "arabic"),
            ("第卅章", "arabic"),
            ("第一百二十三章", "arabic"),
        ],
    )
    def test_idempotent(self, title, fmt):
        once = normalize_chapter_title(title, fmt=fmt)
        assert normalize_chapter_title(once, fmt=fmt) == once


class TestNonConvertible:
    """序号不在 1..9999 → 仅去重与分隔归一，序号形态保持。"""

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("第0章 x", "第0章 x"),
            ("第10000章 x", "第10000章 x"),
            ("第0章 第0章 x", "第0章 x"),
            ("第10000章 第2章 x", "第10000章 x"),
        ],
    )
    def test_number_kept_as_is(self, title, expected):
        """不可转换序号保持原形（仍去重 + 分隔归一）。"""
        assert normalize_chapter_title(title) == expected

    @pytest.mark.parametrize("fmt", ["weird", "roman", ""])
    def test_invalid_fmt_raises_value_error(self, fmt):
        """fmt 不在 {'arabic', 'chinese', None} → ValueError（router 层 422 兜底）。"""
        with pytest.raises(ValueError):
            normalize_chapter_title("第1章 x", fmt=fmt)
