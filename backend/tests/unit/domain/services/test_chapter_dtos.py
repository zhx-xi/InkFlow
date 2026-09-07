"""章节 DTO 与工具函数单元测试 — 无 I/O，纯逻辑。

测试范围：ChapterStatus 枚举、VolumeCreate/ChapterCreate/ChapterUpdate DTO 验证、字数统计。
"""

import pytest
from pydantic import ValidationError


class TestChapterStatus:
    """ChapterStatus 枚举测试."""

    def test_enum_values(self):
        from inkflow.domain.models.chapter import ChapterStatus

        assert ChapterStatus.DRAFT == "draft"
        assert ChapterStatus.WRITING == "writing"
        assert ChapterStatus.REVIEW == "review"
        assert ChapterStatus.FINAL == "final"


class TestVolumeCreateValidation:
    """VolumeCreate DTO 验证测试."""

    def test_create_valid(self):
        from inkflow.domain.models.chapter import VolumeCreate

        v = VolumeCreate(title="第一卷")
        assert v.title == "第一卷"

    def test_create_empty_title_raises(self):
        from inkflow.domain.models.chapter import VolumeCreate

        with pytest.raises(ValidationError, match="卷标题不能为空"):
            VolumeCreate(title="")

    def test_create_whitespace_title_raises(self):
        from inkflow.domain.models.chapter import VolumeCreate

        with pytest.raises(ValidationError, match="卷标题不能为空"):
            VolumeCreate(title="   ")

    def test_create_title_too_long_raises(self):
        from inkflow.domain.models.chapter import VolumeCreate

        with pytest.raises(ValidationError, match="卷标题不能超过 200 个字符"):
            VolumeCreate(title="长" * 201)


class TestChapterCreateValidation:
    """ChapterCreate DTO 验证测试."""

    def test_create_valid(self):
        from inkflow.domain.models.chapter import ChapterCreate

        c = ChapterCreate(title="第一章")
        assert c.title == "第一章"
        assert c.content == ""
        assert c.volume_id is None

    def test_create_empty_title_raises(self):
        from inkflow.domain.models.chapter import ChapterCreate

        with pytest.raises(ValidationError, match="章节标题不能为空"):
            ChapterCreate(title="")

    def test_create_title_too_long_raises(self):
        from inkflow.domain.models.chapter import ChapterCreate

        with pytest.raises(ValidationError, match="章节标题不能超过 500 个字符"):
            ChapterCreate(title="长" * 501)


class TestChapterUpdateValidation:
    """ChapterUpdate DTO 验证测试."""

    def test_update_partial(self):
        from inkflow.domain.models.chapter import ChapterUpdate

        u = ChapterUpdate(title="新标题")
        assert u.title == "新标题"
        assert u.content is None
        assert u.status is None
        assert u.volume_id is None

    def test_update_none_title_ok(self):
        from inkflow.domain.models.chapter import ChapterUpdate

        u = ChapterUpdate(title=None)
        assert u.title is None

    def test_update_empty_title_raises(self):
        from inkflow.domain.models.chapter import ChapterUpdate

        with pytest.raises(ValidationError, match="章节标题不能为空"):
            ChapterUpdate(title="")

    def test_update_title_too_long_raises(self):
        from inkflow.domain.models.chapter import ChapterUpdate

        with pytest.raises(ValidationError, match="章节标题不能超过 500 个字符"):
            ChapterUpdate(title="长" * 501)


class TestVolumeUpdateValidation:
    """VolumeUpdate DTO 验证测试（None 直通 / 空标题 / 超长 / 合法）."""

    def test_update_none_title_ok(self):
        from inkflow.domain.models.chapter import VolumeUpdate

        u = VolumeUpdate(title=None)
        assert u.title is None
        assert u.order_index is None

    def test_update_valid_title_stripped(self):
        from inkflow.domain.models.chapter import VolumeUpdate

        u = VolumeUpdate(title="  第一卷  ")
        assert u.title == "第一卷"

    def test_update_empty_title_raises(self):
        from inkflow.domain.models.chapter import VolumeUpdate

        with pytest.raises(ValidationError, match="卷标题不能为空"):
            VolumeUpdate(title="   ")

    def test_update_title_too_long_raises(self):
        from inkflow.domain.models.chapter import VolumeUpdate

        with pytest.raises(ValidationError, match="卷标题不能超过 200 个字符"):
            VolumeUpdate(title="长" * 201)


class TestWordCount:
    """字数统计工具测试."""

    def test_chinese_only(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("测试内容") == 4

    def test_english_only(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("hello world") == 2

    def test_mixed_cn_en(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("你好world测试abc") == 6

    def test_empty(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("") == 0

    def test_markdown_heading(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("## 标题") == 2

    def test_markdown_bold(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("**强调**文字") == 4

    def test_markdown_code_block(self):
        from inkflow.domain.services._word_count import count_words

        text = "```python\nprint('hello')\n```\n正文"
        assert count_words(text) == 2

    def test_markdown_link(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("[点击](url)这里") == 4


class TestChapterDtoNormalizationGate:
    """#999 DTO 落库闸口（契约 §2）：validate_title 借道 normalize 去重/分隔归一。

    只去重 + 分隔归一，不改变序号格式（fmt=None）；空/超长既有语义零破坏
    （既有用例已覆盖，不重复）。VolumeCreate 卷标题不做归一（卷无「第N章」语义）。
    """

    def test_create_title_dedup_normalized(self):
        """ChapterCreate title：双前缀去重但序号形态保持（fmt=None）。"""
        from inkflow.domain.models.chapter import ChapterCreate

        c = ChapterCreate(title="第1章 第一章 风雨")
        assert c.title == "第1章 风雨"

    def test_create_title_strip_then_normalize(self):
        """先 strip 再归一：首尾空白去除后做去重。"""
        from inkflow.domain.models.chapter import ChapterCreate

        c = ChapterCreate(title="  第1章 第一章 风雨  ")
        assert c.title == "第1章 风雨"

    def test_create_title_mixed_dedupe_keeps_first(self):
        """保留第一个前缀序号，删除后续前缀。"""
        from inkflow.domain.models.chapter import ChapterCreate

        c = ChapterCreate(title="第一章第3章 风雨")
        assert c.title == "第一章 风雨"

    def test_update_title_dedup_normalized(self):
        """ChapterUpdate title：去重但序号形态保持（fmt=None）。"""
        from inkflow.domain.models.chapter import ChapterUpdate

        u = ChapterUpdate(title="第1章 第一章 风雨")
        assert u.title == "第1章 风雨"

    def test_update_title_keeps_chinese_form(self):
        """fmt=None 去重不改变保留前缀序号形态。"""
        from inkflow.domain.models.chapter import ChapterUpdate

        u = ChapterUpdate(title="第一章 风")
        assert u.title == "第一章 风"

    def test_volume_title_not_normalized(self):
        """VolumeCreate 卷标题不归一卷（无「第N章」语义）——只 strip 原样保存。"""
        from inkflow.domain.models.chapter import VolumeCreate

        v = VolumeCreate(title="  第1卷 第一卷 x  ")
        assert v.title == "第1卷 第一卷 x"
