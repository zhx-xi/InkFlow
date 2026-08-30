"""F21 导出服务领域模型单元测试 — DTO/枚举/文件名清洗（RED 阶段，仅测试不实现）。

被测模块: ``inkflow.domain.models.output``（§2.1-2.3）与
``inkflow.domain.services._export_filename.suggest_filename``（§8.1，E5/E7）。

┌─ 模块契约（GREEN 实现者以此为准）──────────────────────────────────────┐
│ 模块路径: inkflow.domain.models.output                                    │
│ 1. ExportFormat(StrEnum): TXT = "txt"（v1.1 唯一值；StrEnum 直接与字符串 │
│    相等，model_dump 输出 "txt"）                                          │
│ 2. BookMeta: title:str / genre:str / language:str / target_words:int /   │
│    updated_at:datetime                                                    │
│ 3. BookChapter: title:str / content:str / order_index:float /            │
│    word_count:int                                                         │
│ 4. BookVolume: title:str / order_index:float /                           │
│    chapters:list[BookChapter]                                             │
│ 5. BookSetting: type:str（character/world/outline/timeline/              │
│    foreshadowing）/ name:str / content:str                                │
│ 6. BookDocument: meta:BookMeta / volumes:list[BookVolume] /              │
│    settings:list[BookSetting]                                             │
│ 7. ExportRequest: format:ExportFormat = ExportFormat.TXT /               │
│    include_settings:bool = False（Q3=C 拍板默认不含）                     │
│ 8. ExportResult: format:ExportFormat / filename:str / bytes:int /        │
│    path:str                                                               │
│ 9. suggest_filename(title: str, fmt: ExportFormat) -> str                │
│    （模块 inkflow.domain.services._export_filename，§7 E5/E7）:          │
│    a. title.strip() 后为空 → "untitled-{fmt.value}.txt"（E7）            │
│    b. Windows 禁符 \\ / : * ? " < > | 逐一替换为 "_"（E5）               │
│    c. 清洗后书名截断前 60 字符（E5 超长截断）                             │
│    d. 拼接 "{书名}-{fmt.value}.txt"（fmt.value 即 "txt"）                │
└──────────────────────────────────────────────────────────────────────────┘

RED 预期（全部实现不存在，收集期失败属设计使然）:
    collected 0 items / 1 error
    ModuleNotFoundError: No module named 'inkflow.domain.models.output'
（文件顶部 import 缺失实现 → 收集期整文件 ModuleNotFoundError；GREEN 时
实现落地一落地整文件自动收集——规则 1c 首选形态。）

依据: specs/f21-export/spec.md §2/§7 E5-E7/§8.1/§9.2 场景 7。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from inkflow.domain.models.output import (
    BookChapter,
    BookDocument,
    BookMeta,
    BookSetting,
    BookVolume,
    ExportFormat,
    ExportRequest,
    ExportResult,
)
from inkflow.domain.services._export_filename import suggest_filename

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


# ── make_* 工厂（既有测试惯例）──────────────────────────────────────────


def make_meta(
    title: str = "我的小说",
    genre: str = "玄幻",
    language: str = "zh-CN",
    target_words: int = 100_000,
    updated_at: datetime = TS,
) -> BookMeta:
    """构造 BookMeta（全字段显式，便于覆盖）。"""
    return BookMeta(
        title=title,
        genre=genre,
        language=language,
        target_words=target_words,
        updated_at=updated_at,
    )


def make_chapter(
    title: str = "第一章",
    content: str = "第一段正文。",
    order_index: float = 1.0,
    word_count: int = 120,
) -> BookChapter:
    """构造 BookChapter。"""
    return BookChapter(
        title=title,
        content=content,
        order_index=order_index,
        word_count=word_count,
    )


def make_volume(
    title: str = "第一卷",
    order_index: float = 1.0,
    chapters: list[BookChapter] | None = None,
) -> BookVolume:
    """构造 BookVolume（chapters 默认空列表——工厂默认值不共享可变对象）。"""
    return BookVolume(
        title=title,
        order_index=order_index,
        chapters=chapters if chapters is not None else [],
    )


def make_setting(
    type_: str = "character",
    name: str = "李青焰",
    content: str = "性格：冷峻",
) -> BookSetting:
    """构造 BookSetting（type 参数名为 type_ 避开内置名）。"""
    return BookSetting(type=type_, name=name, content=content)


def make_document(
    meta: BookMeta | None = None,
    volumes: list[BookVolume] | None = None,
    settings: list[BookSetting] | None = None,
) -> BookDocument:
    """构造 BookDocument（默认：1 卷 1 章 + 1 条设定）。"""
    return BookDocument(
        meta=meta if meta is not None else make_meta(),
        volumes=volumes if volumes is not None else [make_volume(chapters=[make_chapter()])],
        settings=settings if settings is not None else [make_setting()],
    )


def make_request(
    format_: ExportFormat = ExportFormat.TXT,
    include_settings: bool = False,
) -> ExportRequest:
    """构造 ExportRequest（format 参数名为 format_ 避开内置名）。"""
    return ExportRequest(format=format_, include_settings=include_settings)


def make_result(
    format_: ExportFormat = ExportFormat.TXT,
    filename: str = "我的小说-txt.txt",
    bytes_: int = 2048,
    path: str = "我的小说-txt.txt",
) -> ExportResult:
    """构造 ExportResult（bytes 参数名为 bytes_ 避开内置名）。"""
    return ExportResult(format=format_, filename=filename, bytes=bytes_, path=path)


# ── ExportFormat ──────────────────────────────────────────────────────


class TestExportFormat:
    def test_single_value_txt(self):
        """v1.1 单值枚举：TXT = "txt"（StrEnum 与字符串直接相等）。"""
        assert ExportFormat.TXT == "txt"
        assert ExportFormat.TXT.value == "txt"

    def test_export_request_roundtrip_serializes_format(self):
        """ExportRequest.model_dump 中 format 序列化为 "txt" 字符串。"""
        req = make_request()
        dumped = req.model_dump()
        assert dumped["format"] == "txt"
        # 字符串 "txt" 可反序列化回 ExportFormat.TXT（StrEnum 契约）
        restored = ExportRequest.model_validate(dumped)
        assert restored.format is ExportFormat.TXT
        assert restored == req


# ── BookMeta ─────────────────────────────────────────────────────────


class TestBookMeta:
    def test_full_construction(self):
        """全字段构造 + 字段值断言。"""
        meta = make_meta()
        assert meta.title == "我的小说"
        assert meta.genre == "玄幻"
        assert meta.language == "zh-CN"
        assert meta.target_words == 100_000
        assert meta.updated_at == TS

    def test_required_fields(self):
        """缺少必填字段（title/updated_at）抛 ValidationError。"""
        with pytest.raises(ValidationError):
            BookMeta(genre="玄幻", language="zh-CN", target_words=0)
        with pytest.raises(ValidationError):
            BookMeta(title="t", genre="玄幻", language="zh-CN", target_words=0)

    def test_json_roundtrip(self):
        """JSON roundtrip：model_validate(model_dump()) 等值（datetime 往返无损）。"""
        meta = make_meta(updated_at=datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC))
        restored = BookMeta.model_validate(meta.model_dump())
        assert restored == meta
        assert restored.updated_at == meta.updated_at


# ── BookChapter / BookVolume ─────────────────────────────────────────


class TestBookChapter:
    def test_full_construction(self):
        """全字段构造 + 字段值断言（order_index 为 float）。"""
        ch = make_chapter(content="第一段。\n\n第二段。", order_index=2.5, word_count=300)
        assert ch.title == "第一章"
        assert ch.content == "第一段。\n\n第二段。"
        assert ch.order_index == 2.5
        assert ch.word_count == 300

    def test_required_fields(self):
        """缺少必填字段（title/content）抛 ValidationError。"""
        with pytest.raises(ValidationError):
            BookChapter(content="正文", order_index=1.0, word_count=0)
        with pytest.raises(ValidationError):
            BookChapter(title="t", order_index=1.0, word_count=0)

    def test_json_roundtrip(self):
        """JSON roundtrip：含换行正文 + float 排序键无损。"""
        ch = make_chapter(content="第一段。\n\n第二段。", order_index=3.0)
        restored = BookChapter.model_validate(ch.model_dump())
        assert restored == ch
        assert restored.order_index == 3.0


class TestBookVolume:
    def test_full_construction_with_chapters(self):
        """卷可嵌套章节列表，chapters 顺序原样保留。"""
        chapters = [make_chapter(title="第一章"), make_chapter(title="第二章", order_index=2.0)]
        vol = make_volume(chapters=chapters)
        assert vol.title == "第一卷"
        assert vol.order_index == 1.0
        assert [c.title for c in vol.chapters] == ["第一章", "第二章"]

    def test_empty_chapters_default(self):
        """chapters 默认空列表（无共享可变对象陷阱）。"""
        vol1, vol2 = make_volume(), make_volume()
        assert vol1.chapters == []
        assert vol2.chapters == []
        vol1.chapters.append(make_chapter())
        assert vol2.chapters == []

    def test_required_fields(self):
        """缺少必填字段（title/order_index/chapters）抛 ValidationError。"""
        with pytest.raises(ValidationError):
            BookVolume(order_index=1.0, chapters=[])
        with pytest.raises(ValidationError):
            BookVolume(title="t", chapters=[])
        with pytest.raises(ValidationError):
            BookVolume(title="t", order_index=1.0)

    def test_json_roundtrip(self):
        """JSON roundtrip：卷 + 嵌套章节无损。"""
        vol = make_volume(chapters=[make_chapter(title="第一章", order_index=1.0)])
        restored = BookVolume.model_validate(vol.model_dump())
        assert restored == vol
        assert restored.chapters[0].order_index == 1.0


# ── BookSetting / BookDocument ───────────────────────────────────────


class TestBookSetting:
    def test_full_construction(self):
        """全字段构造。"""
        s = make_setting(type_="world", name="灵气复苏", content="设定：灵气复苏")
        assert s.type == "world"
        assert s.name == "灵气复苏"
        assert s.content == "设定：灵气复苏"

    def test_required_fields(self):
        """缺少必填字段（type/name/content）抛 ValidationError。"""
        with pytest.raises(ValidationError):
            BookSetting(name="n", content="c")
        with pytest.raises(ValidationError):
            BookSetting(type="character", content="c")
        with pytest.raises(ValidationError):
            BookSetting(type="character", name="n")

    def test_json_roundtrip(self):
        """JSON roundtrip 无损。"""
        s = make_setting(type_="timeline", name="大战", content="青元历 317 年秋｜大战")
        assert BookSetting.model_validate(s.model_dump()) == s


class TestBookDocument:
    def test_full_construction(self):
        """嵌套文档树构造：meta + 多卷 + 多设定。"""
        doc = make_document(
            volumes=[
                make_volume(title="第一卷", chapters=[make_chapter(title="第一章")]),
                make_volume(title="第二卷", chapters=[make_chapter(title="第二章")]),
            ],
            settings=[
                make_setting(type_="character", name="李青焰"),
                make_setting(type_="world", name="灵气复苏"),
            ],
        )
        assert doc.meta.title == "我的小说"
        assert len(doc.volumes) == 2
        assert doc.volumes[1].chapters[0].title == "第二章"
        assert len(doc.settings) == 2
        assert doc.settings[1].type == "world"

    def test_empty_lists_default(self):
        """volumes/settings 默认空列表（空项目 E2 的表示形态）。"""
        doc = BookDocument(meta=make_meta())
        assert doc.volumes == []
        assert doc.settings == []

    def test_json_roundtrip(self):
        """整树 JSON roundtrip 无损（嵌套列表 + datetime 往返）。"""
        doc = make_document(
            volumes=[
                make_volume(
                    title="第一卷",
                    chapters=[make_chapter(title="第一章", content="正文\n多行", order_index=1.0)],
                )
            ],
            settings=[make_setting(type_="foreshadowing", name="林晚的身世")],
        )
        restored = BookDocument.model_validate(doc.model_dump())
        assert restored == doc
        assert restored.volumes[0].chapters[0].content == "正文\n多行"


# ── ExportRequest / ExportResult（传输 DTO）───────────────────────────


class TestExportRequest:
    def test_defaults(self):
        """默认值：format=TXT、include_settings=False（Q3=C 拍板）。"""
        req = ExportRequest()
        assert req.format is ExportFormat.TXT
        assert req.include_settings is False

    def test_include_settings_true(self):
        """显式 include_settings=True 可切换。"""
        assert ExportRequest(include_settings=True).include_settings is True

    def test_invalid_format_rejected(self):
        """非 txt 字符串 → ValidationError（v1.1 仅接受 txt，§3.3 422 契约）。"""
        with pytest.raises(ValidationError):
            ExportRequest(format="epub")  # type: ignore[arg-type]  # 故意传非法值测校验

    def test_json_roundtrip(self):
        """JSON roundtrip 无损（format 枚举 ↔ 字符串双向）。"""
        for req in (make_request(), make_request(include_settings=True)):
            restored = ExportRequest.model_validate(req.model_dump())
            assert restored == req
            assert restored.format is ExportFormat.TXT


class TestExportResult:
    def test_full_construction(self):
        """全字段构造（CLI --json 信封 payload，§2.3）。"""
        r = make_result(filename="我的书-txt.txt", bytes_=1_234_567, path="./out/我的书-txt.txt")
        assert r.format is ExportFormat.TXT
        assert r.filename == "我的书-txt.txt"
        assert r.bytes == 1_234_567
        assert r.path == "./out/我的书-txt.txt"

    def test_required_fields(self):
        """缺少必填字段（format/filename/bytes/path）抛 ValidationError。"""
        with pytest.raises(ValidationError):
            ExportResult(filename="f.txt", bytes=1, path="p")
        with pytest.raises(ValidationError):
            ExportResult(format=ExportFormat.TXT, bytes=1, path="p")
        with pytest.raises(ValidationError):
            ExportResult(format=ExportFormat.TXT, filename="f.txt", path="p")
        with pytest.raises(ValidationError):
            ExportResult(format=ExportFormat.TXT, filename="f.txt", bytes=1)

    def test_json_roundtrip(self):
        """JSON roundtrip：bytes 字段在 dump 中为 int，format 反序列化为枚举。"""
        r = make_result(bytes_=2048)
        dumped = r.model_dump()
        assert dumped["bytes"] == 2048
        assert dumped["format"] == "txt"
        restored = ExportResult.model_validate(dumped)
        assert restored == r
        assert restored.bytes == 2048


# ── suggest_filename（§8.1 _export_filename，E5/E7）───────────────────


class TestSuggestFilename:
    def test_normal_book_title(self):
        """正常书名 + txt → 「{书名}-txt.txt」。"""
        assert suggest_filename("我的书", ExportFormat.TXT) == "我的书-txt.txt"

    def test_strips_leading_trailing_whitespace(self):
        """书名两端空白先 strip（设计假设：strip → 空判定 → 清洗 → 截断）。"""
        assert suggest_filename("  我的书  ", ExportFormat.TXT) == "我的书-txt.txt"

    @pytest.mark.parametrize("bad", ["\\", "/", ":", "*", "?", '"', "<", ">", "|"])
    def test_windows_forbidden_chars_replaced_with_underscore(self, bad):
        """Windows 禁符（\\ / : * ? " < > |）逐一清洗为 _（E5）。"""
        assert suggest_filename(f"a{bad}b", ExportFormat.TXT) == "a_b-txt.txt"

    def test_mixed_forbidden_chars(self):
        """多个禁符混合一次清洗。"""
        title = 'a/b:c*d?e"f<g>h|i'
        assert suggest_filename(title, ExportFormat.TXT) == "a_b_c_d_e_f_g_h_i-txt.txt"

    def test_title_starting_with_forbidden_char(self):
        """书名首字符为禁符同样清洗。"""
        assert suggest_filename(":开头", ExportFormat.TXT) == "_开头-txt.txt"

    def test_all_forbidden_chars_does_not_become_untitled(self):
        """全禁符书名清洗为 _ 后非空 → 不触发 untitled（清洗 ≠ 空判定）。"""
        assert suggest_filename("***", ExportFormat.TXT) == "___-txt.txt"

    def test_overlong_title_truncated_to_60_chars(self):
        """超长书名截断前 60 字符（E5）。"""
        title = "长" * 100
        result = suggest_filename(title, ExportFormat.TXT)
        assert result == "长" * 60 + "-txt.txt"
        assert len(result) == 60 + len("-txt.txt")

    def test_overlong_title_with_forbidden_char(self):
        """超长 + 禁符：先清洗后截断（设计假设顺序：strip → 空判定 → 清洗 → 截断）。"""
        title = "长" * 100 + "/"
        assert suggest_filename(title, ExportFormat.TXT) == "长" * 60 + "-txt.txt"

    def test_exactly_60_chars_not_truncated(self):
        """恰好 60 字符不截断（边界）。"""
        title = "字" * 60
        assert suggest_filename(title, ExportFormat.TXT) == "字" * 60 + "-txt.txt"

    def test_empty_title_untitled(self):
        """空书名 → untitled 占位（E7）。"""
        assert suggest_filename("", ExportFormat.TXT) == "untitled-txt.txt"

    def test_whitespace_title_untitled(self):
        """纯空白书名（strip 后空）→ untitled 占位（E7 边界）。"""
        assert suggest_filename("   ", ExportFormat.TXT) == "untitled-txt.txt"

    def test_filename_contains_format_value(self):
        """文件名内嵌 fmt.value（"txt"），契约 §3.2 Content-Disposition 同名。"""
        result = suggest_filename("我的书", ExportFormat.TXT)
        assert result.endswith("-txt.txt")
        assert "我的书-txt" in result
