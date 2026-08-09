"""F21 TXT 序列化器单元测试 — 纯函数，无 I/O 无 DB（RED 阶段，仅测试不实现）。

被测模块: ``inkflow.domain.services._txt_exporter.to_txt(book: BookDocument) -> str``
（§5.3 纯函数，零依赖，UTF-8 文本；§8.1 D7 单文件形态）。

┌─ 模块契约（GREEN 实现者以此为准）──────────────────────────────────────┐
│ 1. 签名: to_txt(book: BookDocument) -> str（纯函数，无副作用）           │
│ 2. 结构（§5.3 + §6.2，行级精确断言见各用例）:                           │
│    a. 首行 = 书名                                                        │
│    b. 书名后分隔线 = "=" 重复 30 个                                      │
│    c. 每个卷: "第 {N} 卷 {title}"（N 从 1 计数；title 为空 →            │
│       "第 {N} 卷" 占位，§6.2）后接 "-" 重复 30 个分隔线                  │
│    d. 每个章: "第 {M} 章 {title}"（M = 卷内序号从 1 计数，§6.2）         │
│    e. 章正文原样保留（含换行，不转义不清洗，§7 E3）                      │
│    f. 无卷项目（所有章 volume_id=None → service 聚合为 title="未分组"  │
│       的单个卷）: to_txt 对 title == "未分组" 的卷不输出卷标题行与     │
│       "-" 分隔线，直接输出其章「第 {N} 章 {title}」（N 从 1 计数，    │
│       §5.3「单卷退化」；"未分组" 是 service 聚合常量，文件 3 联动）    │
│    g. 附录（settings 非空时）: 标题行 "附录：设定档案" + 按 type 分节:   │
│       character→【角色】world→【世界观】outline→【大纲】                │
│       timeline→【时间线】foreshadowing→【伏笔】；分节顺序固定为          │
│       character → world → outline → timeline → foreshadowing            │
│       （§5.1 ③ 顺序）；每条目输出 name 行 + content 行                  │
│    h. settings 为空 → 不输出附录（M2 缺省不含）                          │
│    i. 确定性: 同 fixture 两次调用输出完全相同（§5.4/§9.2 场景 1）        │
│ 3. 空项目（无卷无章无设定）→ 书名 + 分隔线（标题 + 空正文，§7 E4）       │
│ 4. 文本中章节/卷编号与卷标题独立（卷标题含"章"字不影响断言——测试卷    │
│    标题避开"章/卷"字样）                                                 │
└──────────────────────────────────────────────────────────────────────────┘

RED 预期（实现不存在，收集期失败属设计使然）:
    collected 0 items / 1 error
    ModuleNotFoundError: No module named 'inkflow.domain.models.output'
（顶部 import 缺失实现 → 收集期整文件 ModuleNotFoundError；GREEN 时
实现落地自动收集。）

依据: specs/f21-export-service/spec.md §3.2/§5.3/§6.2/§7 E3-E4/§9.2 场景 1。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from inkflow.domain.models.output import (
    BookChapter,
    BookDocument,
    BookMeta,
    BookSetting,
    BookVolume,
)
from inkflow.domain.services._txt_exporter import to_txt

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)

# §5.3 分隔线常量（契约锁死：= 30 个 / - 30 个）
LINE_EQ = "=" * 30
LINE_DASH = "-" * 30

# 附录分节标题映射（契约锁死，§5.3）
SECTION_TITLES = {
    "character": "【角色】",
    "world": "【世界观】",
    "outline": "【大纲】",
    "timeline": "【时间线】",
    "foreshadowing": "【伏笔】",
}

# 附录规范分节顺序（契约锁死，§5.1 ③：character → world → outline → timeline → foreshadowing）
_CANONICAL_ORDER = ["character", "world", "outline", "timeline", "foreshadowing"]


# ── make_* 工厂（与 test_output_models.py 同形，文件独立不互相 import）──


def make_meta(title: str = "我的小说") -> BookMeta:
    """构造 BookMeta（书名可覆盖）。"""
    return BookMeta(
        title=title,
        genre="玄幻",
        language="zh-CN",
        target_words=100_000,
        updated_at=TS,
    )


def make_chapter(
    title: str,
    content: str = "正文第一段。",
    order_index: float = 1.0,
    word_count: int = 100,
) -> BookChapter:
    """构造单章（title 必填——断言依赖章标题）。"""
    return BookChapter(
        title=title,
        content=content,
        order_index=order_index,
        word_count=word_count,
    )


def make_volume(
    title: str,
    order_index: float = 1.0,
    chapters: list[BookChapter] | None = None,
) -> BookVolume:
    """构造卷（title 传空串测试占位）。"""
    return BookVolume(
        title=title,
        order_index=order_index,
        chapters=chapters if chapters is not None else [],
    )


def make_setting(type_: str, name: str, content: str = "摘要内容。") -> BookSetting:
    """构造附录条目。"""
    return BookSetting(type=type_, name=name, content=content)


def make_document(
    meta: BookMeta | None = None,
    volumes: list[BookVolume] | None = None,
    settings: list[BookSetting] | None = None,
) -> BookDocument:
    """构造 BookDocument（默认：1 卷 1 章 + 无设定）。"""
    return BookDocument(
        meta=meta if meta is not None else make_meta(),
        volumes=(
            volumes
            if volumes is not None
            else [make_volume("第一卷", chapters=[make_chapter("第一章")])]
        ),
        settings=settings if settings is not None else [],
    )


def _lines(text: str) -> list[str]:
    """按行拆分（to_txt 输出的行级断言辅助）。"""
    return text.splitlines()


# ── 结构断言 ─────────────────────────────────────────────────────────


class TestToTxtStructure:
    def test_first_line_is_book_title(self):
        """首行 = 书名（§5.3）。"""
        text = to_txt(make_document())
        assert _lines(text)[0] == "我的小说"

    def test_title_separator_is_30_equals(self):
        """书名后分隔线 = "=" 重复 30 个（§3.2 示例）。"""
        text = to_txt(make_document())
        assert LINE_EQ in text
        assert "=" * 31 not in text

    def test_volume_line_and_dash_separator(self):
        """卷标题行「第 1 卷 序章」+ "-" 重复 30 个分隔线（§5.3）。"""
        book = make_document(volumes=[make_volume("序章", chapters=[make_chapter("第一章")])])
        text = to_txt(book)
        assert "第 1 卷 序章" in text
        assert LINE_DASH in text
        assert "-" * 31 not in text

    def test_chapter_line_and_content_preserved(self):
        """章标题「第 1 章 开端」+ 正文原样（含换行不转义，§7 E3）。"""
        content = "第一段。\n\n第二段。\n\n第三段。"
        book = make_document(
            volumes=[make_volume("序章", chapters=[make_chapter("开端", content=content)])]
        )
        text = to_txt(book)
        assert "第 1 章 开端" in text
        assert content in text  # 原样保留，不做任何清洗/转义

    def test_chapter_numbers_restart_per_volume(self):
        """章节编号 = 卷内序号从 1 计数：两卷各 1 章 → 两个「第 1 章」（§6.2）。"""
        book = make_document(
            volumes=[
                make_volume("序章", chapters=[make_chapter("开端")]),
                make_volume("终章", chapters=[make_chapter("结局")]),
            ]
        )
        text = to_txt(book)
        assert text.count("第 1 章") == 2
        assert "第 1 卷 序章" in text
        assert "第 2 卷 终章" in text

    def test_chapter_numbers_sequential_within_volume(self):
        """卷内多章编号连续 1、2、3（§6.2 卷内序号从 1 计数）。"""
        book = make_document(
            volumes=[
                make_volume(
                    "序章",
                    chapters=[
                        make_chapter("开端", order_index=1.0),
                        make_chapter("发展", order_index=2.0),
                        make_chapter("高潮", order_index=3.0),
                    ],
                )
            ]
        )
        text = to_txt(book)
        assert "第 1 章 开端" in text
        assert "第 2 章 发展" in text
        assert "第 3 章 高潮" in text

    def test_volume_numbers_sequential(self):
        """卷编号从 1 计数。"""
        book = make_document(
            volumes=[
                make_volume("序章", chapters=[]),
                make_volume("终章", chapters=[]),
            ]
        )
        text = to_txt(book)
        assert "第 1 卷 序章" in text
        assert "第 2 卷 终章" in text

    def test_empty_volume_title_uses_placeholder(self):
        """卷标题为空 → 「第 X 卷」占位（§6.2 F2 卷 title 可空）。"""
        book = make_document(volumes=[make_volume("", chapters=[make_chapter("第一章")])])
        text = to_txt(book)
        assert "第 1 卷" in text
        assert "第 1 卷 " not in text  # 无 title 尾随空格（占位形态无空 title）

    def test_no_volumes_project_omits_volume_prefix(self):
        """无卷项目（未分组卷，title="未分组"）省略卷前缀直接「第 N 章」（§5.3/§6.2）。"""
        book = make_document(
            volumes=[
                make_volume(
                    "未分组",
                    order_index=0.0,
                    chapters=[make_chapter("第一章"), make_chapter("第二章")],
                )
            ]
        )
        text = to_txt(book)
        assert "第 1 章 第一章" in text
        assert "第 2 章 第二章" in text
        assert "第 1 卷" not in text  # 无卷前缀
        assert LINE_DASH not in text  # 无卷分隔线

    def test_empty_project_emits_title_and_separator(self):
        """空项目（无卷无章无设定）→ 书名 + 分隔线，不报错（§7 E4）。"""
        text = to_txt(make_document(volumes=[], settings=[]))
        assert _lines(text)[0] == "我的小说"
        assert LINE_EQ in text
        assert "第 1 章" not in text


# ── 附录（settings）──────────────────────────────────────────────────


class TestToTxtAppendix:
    def test_appendix_title_present_when_settings_non_empty(self):
        """settings 非空 → 「附录：设定档案」标题出现（§3.2 示例）。"""
        book = make_document(settings=[make_setting("character", "李青焰")])
        text = to_txt(book)
        assert "附录：设定档案" in text

    def test_no_appendix_when_settings_empty(self):
        """settings 为空 → 无「附录：设定档案」（M2 缺省不含）。"""
        text = to_txt(make_document(settings=[]))
        assert "附录：设定档案" not in text

    @pytest.mark.parametrize(
        ("type_", "section"),
        [
            ("character", "【角色】"),
            ("world", "【世界观】"),
            ("outline", "【大纲】"),
            ("timeline", "【时间线】"),
            ("foreshadowing", "【伏笔】"),
        ],
    )
    def test_section_title_per_type(self, type_: str, section: str):
        """五种设定类型各输出对应分节标题（§5.3 同构分节）。"""
        book = make_document(settings=[make_setting(type_, "条目名")])
        text = to_txt(book)
        assert section in text
        assert "附录：设定档案" in text

    def test_sections_in_fixed_order(self):
        """分节顺序固定：角色 → 世界观 → 大纲 → 时间线 → 伏笔（§5.1 ③）。"""
        settings = [
            make_setting("foreshadowing", "伏笔条目"),
            make_setting("character", "角色条目"),
            make_setting("timeline", "时间线条目"),
            make_setting("world", "世界条目"),
            make_setting("outline", "大纲条目"),
        ]
        text = to_txt(make_document(settings=settings))
        # 规范序（§5.1 ③）：character → world → outline → timeline → foreshadowing。
        # 断言各分节标题在输出中的出现位置严格递增（而非按 settings 输入序——旧断言恒真空洞，
        # 父侧裁定 2026-08-09 改为锁定规范序）。
        positions = [text.index(SECTION_TITLES[t]) for t in _CANONICAL_ORDER]
        assert positions == sorted(positions)
        assert positions[0] < positions[1] < positions[2] < positions[3] < positions[4]

    def test_entry_contains_name_and_content(self):
        """每条目输出 name 行 + content 行（§5.3 示例形态）。"""
        book = make_document(
            settings=[make_setting("character", "李青焰", "性格：冷峻\n背景：孤儿")]
        )
        text = to_txt(book)
        assert "李青焰" in text
        assert "性格：冷峻\n背景：孤儿" in text

    def test_multiple_entries_same_type_all_present(self):
        """同类型多条目全部输出（不丢条目）。"""
        settings = [
            make_setting("character", "李青焰", "性格：冷峻"),
            make_setting("character", "沈砚", "性格：沉稳"),
        ]
        text = to_txt(make_document(settings=settings))
        assert "李青焰" in text
        assert "沈砚" in text


# ── 确定性（§9.2 场景 1 / M3）────────────────────────────────────────


class TestToTxtDeterminism:
    def test_same_fixture_twice_identical(self):
        """同一 fixture 两次 to_txt 文本完全相同（§5.4 确定性声明）。"""
        book = make_document(
            volumes=[
                make_volume(
                    "序章",
                    chapters=[make_chapter("开端", content="第一段。\n第二段。")],
                )
            ],
            settings=[
                make_setting("character", "李青焰", "性格：冷峻"),
                make_setting("world", "灵气复苏", "设定：灵气复苏"),
            ],
        )
        assert to_txt(book) == to_txt(book)

    def test_deterministic_across_separate_calls_with_full_tree(self):
        """完整文档树（2 卷 3 章 + 5 类设定）两次调用输出逐字节相同（M3）。"""
        book = make_document(
            volumes=[
                make_volume(
                    "序章",
                    chapters=[
                        make_chapter("开端", content="甲"),
                        make_chapter("发展", content="乙\n丙"),
                    ],
                ),
                make_volume("终章", chapters=[make_chapter("结局", content="丁")]),
            ],
            settings=[
                make_setting("character", "李青焰"),
                make_setting("world", "灵气复苏"),
                make_setting("outline", "主线"),
                make_setting("timeline", "大战"),
                make_setting("foreshadowing", "身世"),
            ],
        )
        first = to_txt(book)
        second = to_txt(book)
        assert first == second
        assert first  # 非空
