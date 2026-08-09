"""F34 上下文预算与截断纯函数单元测试 — domain/services/_audit_context.py（spec §5.4）.

覆盖:
- truncate_chapter: ≤8000 字符原样返回 (text, False)；>8000 字符截断采样
  （首段 + 末段 + 中间均匀采样，总长 ≤ 原长 60% 左右）返回 (text', True)；
  空文本返回 ("", False)
- select_entities: 名称子串匹配优先（保持原相对顺序）排前、未匹配排后、
  最多 _MAX_ENTITY_COUNT 条；空 entities / 空 text 边界

设计假设（GREEN 实现契约，依据 specs/f34-chapter-audit/spec.md §5.4）:
1. 模块路径: inkflow.domain.services._audit_context（CREATE；RED 阶段不存在 →
   顶部 import 抛 ModuleNotFoundError = 预期收集期失败，pytest 退出码 2）
2. truncate_chapter(content: str) -> tuple[str, bool]: 返回 (截断后文本,
   是否截断)。≤8000 字符 → 原样 + False；>8000 → 截断采样 + True；采样 =
   首段 + 末段 + 中间均匀采样（段落分隔符 "\n\n"），总长 ≤ 原长 60%
   （本文件断言 len(truncated) <= len(content) * 0.6）
3. 常量 _MAX_CHAPTER_CHARS = 8000 从模块 import（本文件不硬编码 8000，
   边界用例以常量构造）
4. select_entities(entities: list, text: str) -> list: 元素对象有 .name
   属性；名称匹配用子串（name in text）；出现名称的排前面且保持原相对顺序，
   未出现的排后面；最多 _MAX_ENTITY_COUNT = 20 条（常量从模块 import）；
   空 entities → []；text 为空 → 原序全量（≤ 上限）
5. 匹配对象用 SimpleNamespace(name=...) 轻量构造（不依赖 F9/F10 领域模型）
6. RED 预期: 收集期 1 error（ModuleNotFoundError: No module named
   'inkflow.domain.services._audit_context'），无其他失败

补测覆盖（覆盖率 miss 归因，2026-08）:
- _sample_paragraphs 中间段总和 ≤ 预算 → 全保留（L80 正路径；经
  truncate_chapter 入口数学上不可达——60% 预算恒小于首末段外余量，
  直接对私有纯函数施加宽松预算测分支本身）
- 采样循环递减到 0（L88/89）: 中间段全部超预算 → 仅保留首末段
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from inkflow.domain.services._audit_context import (
    _MAX_CHAPTER_CHARS,
    _MAX_ENTITY_COUNT,
    _sample_paragraphs,
    select_entities,
    truncate_chapter,
)


def _entity(name: str) -> SimpleNamespace:
    """构造带 .name 属性的轻量条目（角色/设定名称匹配测试用）。"""
    return SimpleNamespace(name=name)


def _entity_names(entities: list[SimpleNamespace]) -> list[str]:
    """提取条目名称列表（断言辅助）。"""
    return [e.name for e in entities]


class TestTruncateChapter:
    """truncate_chapter（§5.4: 8000 字符预算 + 超长采样截断）。"""

    @pytest.mark.parametrize("length", [0, 100, _MAX_CHAPTER_CHARS])
    def test_within_limit_returned_as_is(self, length):
        content = "甲" * length
        result, truncated = truncate_chapter(content)
        assert truncated is False
        assert result == content

    def test_constant_max_chapter_chars(self):
        """预算常量值（spec §5.4: 8000 字符）。"""
        assert _MAX_CHAPTER_CHARS == 8000

    def test_one_char_over_limit_truncates(self):
        content = "甲" * (_MAX_CHAPTER_CHARS + 1)
        result, truncated = truncate_chapter(content)
        assert truncated is True
        assert result != content
        assert len(result) <= len(content) * 0.6

    def test_over_limit_keeps_first_and_last_paragraphs(self):
        """超长截断: 首段 + 末段保留，中间均匀采样，总长 ≤ 原长 60%。"""
        paragraphs = ["首" * 1000] + ["甲" * 1000] * 8 + ["尾" * 1000]
        content = "\n\n".join(paragraphs)
        assert len(content) > _MAX_CHAPTER_CHARS
        result, truncated = truncate_chapter(content)
        assert truncated is True
        assert result != content
        assert len(result) <= len(content) * 0.6
        assert "首" * 1000 in result
        assert "尾" * 1000 in result

    def test_empty_content(self):
        result, truncated = truncate_chapter("")
        assert truncated is False
        assert result == ""

    def test_sampling_loop_decrements_to_zero_keeps_only_ends(self):
        """中间段落全部超预算（单段 > budget）→ 采样循环递减到 0（L88/89），
        只保留首末段。"""
        first, last = "首" * 3000, "尾" * 3000
        middle = ["中" * 5000, "中" * 5000]
        content = "\n\n".join([first, *middle, last])
        assert len(content) > _MAX_CHAPTER_CHARS
        result, truncated = truncate_chapter(content)
        assert truncated is True
        assert len(result) <= len(content) * 0.6
        assert first in result
        assert last in result
        assert "中" * 5000 not in result


class TestSampleParagraphs:
    """_sample_paragraphs 私有纯函数（补测 L80 正路径——经 truncate_chapter
    入口该分支数学上不可达：60% 预算恒小于首末段外的余量）。"""

    def test_keeps_all_when_middle_within_budget(self):
        """中间段总和 ≤ 预算 → 全保留（L80 正路径）。"""
        paragraphs = ["首" * 100, "中一", "中二", "中三", "尾" * 100]
        selected = _sample_paragraphs(paragraphs, max_chars=1000, marker_len=9)
        assert selected == paragraphs


class TestSelectEntities:
    """select_entities（§5.4: 名称匹配优先 + 20 条上限）。"""

    def test_constant_max_entity_count(self):
        """条目选取上限常量（spec §5.4: 最多 20 条）。"""
        assert _MAX_ENTITY_COUNT == 20

    def test_matching_entities_first_keep_original_order(self):
        entities = [_entity("龙"), _entity("林晚"), _entity("风")]
        result = select_entities(entities, "龙的苏醒，林晚出场")
        assert _entity_names(result) == ["龙", "林晚", "风"]

    def test_substring_matching(self):
        """名称匹配为子串语义（name in text），如「龙」命中「龙的苏醒」。"""
        entities = [_entity("林"), _entity("龙")]
        result = select_entities(entities, "龙的苏醒")
        assert _entity_names(result) == ["龙", "林"]

    def test_no_match_keeps_original_order(self):
        entities = [_entity("张三"), _entity("李四"), _entity("王五")]
        result = select_entities(entities, "与档案无关的章节文本")
        assert _entity_names(result) == ["张三", "李四", "王五"]

    def test_empty_entities_returns_empty(self):
        assert select_entities([], "任意文本") == []

    def test_empty_text_returns_all_in_original_order(self):
        entities = [_entity("张三"), _entity("李四"), _entity("王五")]
        result = select_entities(entities, "")
        assert _entity_names(result) == ["张三", "李四", "王五"]

    def test_cap_at_max_entity_count(self):
        """超 20 条时截断: 匹配的在前（原序），未匹配的补足到 20。"""
        entities = [_entity(f"匹配{i}") for i in range(10)] + [
            _entity(f"未匹配{i}") for i in range(15)
        ]
        text = " ".join(f"匹配{i}" for i in range(10))
        result = select_entities(entities, text)
        assert len(result) == _MAX_ENTITY_COUNT
        assert _entity_names(result)[:10] == [f"匹配{i}" for i in range(10)]
        assert set(_entity_names(result)[10:]) == {f"未匹配{i}" for i in range(10)}

    def test_exactly_max_count_no_loss(self):
        entities = [_entity(f"条目{i}") for i in range(_MAX_ENTITY_COUNT)]
        result = select_entities(entities, "")
        assert len(result) == _MAX_ENTITY_COUNT
        assert _entity_names(result) == [f"条目{i}" for i in range(_MAX_ENTITY_COUNT)]
