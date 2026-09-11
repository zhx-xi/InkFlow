"""卷/章节领域模型 — 定义核心领域实体与数据传输对象.

ChapterStatus 枚举包含 4 种章节写作状态，
Volume 和 Chapter 是持久化实体，
VolumeCreate/VolumeUpdate/ChapterCreate/ChapterUpdate 是请求 DTO。

#999 契约 §1：normalize_chapter_title 纯函数 + 中文数字转换 helper
（定义在本 models 文件，避免 models→services 反向依赖；
chapter_service 从本文件 re-export 供 RED import 路径使用）。
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

# #999 中文数字字符表（〇零=0，一~九=1-9，两=2；十/百/千 为位权；廿=20 卅=30）
_CN_DIGITS = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_NUM_CHARS = "〇零一二两三四五六七八九十百千廿卅"
_ARABIC_PREFIX_RE = re.compile(r"^第\s*(\d+)\s*章")
_CHINESE_PREFIX_RE = re.compile(rf"^第\s*([{_CN_NUM_CHARS}]+)\s*章")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _cn_to_int(num_text: str) -> int | None:
    """中文数字文本 → int（#999 契约 §1；廿=20、卅=30；非法组合返回 None）.

    支持 1..9999 规范组合（二十一↔21、一百二十三↔123、三百↔300）；
    首数可缺省时「百」=100、「千」=1000（如「第百章」→ 100）。
    """
    text = num_text.replace("廿", "二十").replace("卅", "三十")
    if not text:
        return None
    total = 0
    section = 0
    digit = 0
    for ch in text:
        if ch in ("〇", "零"):
            digit = 0
            continue
        if ch in _CN_DIGITS:
            digit = _CN_DIGITS[ch]
            continue
        if ch == "十":
            section += (digit if digit else 1) * 10
            digit = 0
        elif ch == "百":
            section += (digit if digit else 1) * 100
            digit = 0
        elif ch == "千":
            total += (section + (digit if digit else 1)) * 1000
            section = 0
            digit = 0
        else:
            return None
    return total + section + digit


def _int_to_cn(value: int) -> str:
    """整数（1..9999）→ 规范中文数字写法（30=三十 非 卅；300=三百）."""
    units = ("零", "一", "二", "三", "四", "五", "六", "七", "八", "九")
    result = ""
    if value >= 1000:
        result += units[value // 1000] + "千"
        value %= 1000
        if value and value < 100:
            result += "零"
    if value >= 100:
        result += units[value // 100] + "百"
        value %= 100
        if value and value < 10:
            result += "零"
    if value >= 10:
        result += (units[value // 10] if value >= 20 else "") + "十"
        value %= 10
    if value:
        result += units[value]
    return result


def _match_chapter_prefix(text: str) -> tuple[str, str, str] | None:
    """匹配标题开头「第N章」前缀；返回 (形态, 原始序号文本, 剩余文本)."""
    m = _ARABIC_PREFIX_RE.match(text)
    if m:
        return "arabic", m.group(1), text[m.end() :]
    m = _CHINESE_PREFIX_RE.match(text)
    if m:
        return "chinese", m.group(1), text[m.end() :]
    return None


def normalize_chapter_title(title: str, fmt: str | None = "arabic") -> str:
    """章节标题双编号归一化（#999 契约 §1）.

    - fmt='arabic'：中文序号 → 阿拉伯（第三→第3）；fmt='chinese'：反向
      （第21→第二十一，30=三十 规范写法）；fmt=None：只做双前缀去重与
      分隔归一，不改序号形态（DTO 落库闸口语义）。
    - 开头连续多个「第N章」前缀 → 只保留第一个前缀序号，循环剥离收敛。
    - 无前缀纯名 / 中部「第N章」→ strip 后原样返回；序号不在 1..9999
      或中文无法解析 → 仅去重 + 分隔归一，序号形态保持。
    - fmt 非法（非 arabic/chinese/None）→ ValueError（router 层 422 兜底）。
    """
    if fmt not in (None, "arabic", "chinese"):
        raise ValueError(f"不支持的章节标题格式: {fmt}")
    stripped = title.strip()
    if not stripped:
        return ""

    prefixes: list[tuple[str, str]] = []
    rest = stripped
    separator = True
    while True:
        matched = _match_chapter_prefix(rest)
        if matched is None:
            break
        kind, raw, tail = matched
        if kind == "chinese" and _cn_to_int(raw) is None:
            # 中文序号无法解析（如「第X章」X 非数字）→ 不视为前缀，原样保持
            break
        prefixes.append((kind, raw))
        # 最小干预（#999）：最后剥离的前缀后紧邻文本无空白 → 不凭空插入分隔符
        separator = bool(tail) and tail[0].isspace()
        rest = tail.strip()
    if not prefixes:
        return stripped

    kind, raw = prefixes[0]
    if fmt is None:
        num_text = raw
    else:
        parsed = _cn_to_int(raw) if kind == "chinese" else int(raw)
        if parsed is not None and 1 <= parsed <= 9999:
            num_text = str(parsed) if fmt == "arabic" else _int_to_cn(parsed)
        else:
            num_text = raw
    prefix = f"第{num_text}章"
    if not rest:
        return prefix
    return f"{prefix} {rest}" if separator else f"{prefix}{rest}"


# #1095 正文格式归一样板：全角缩进常量 + markdown 装饰剥离正则
_FULLWIDTH_INDENT = "\u3000\u3000"
_LEADING_HASH_RE = re.compile(r"^#{1,6}\s*")
_LEADING_EMPHASIS_RE = re.compile(r"^[*_]{1,3}\s*")
_TRAILING_EMPHASIS_RE = re.compile(r"\s*[*_]{1,3}$")
_LEADING_WHITESPACE_RE = re.compile(r"^[ \t\u3000]+")


def _strip_title_line_decoration(line: str) -> str:
    """剥掉首行标题的 markdown 装饰前缀/后缀（# ~ ###### / ** / * / _）."""
    text = line.strip()
    text = _LEADING_HASH_RE.sub("", text)
    text = _LEADING_EMPHASIS_RE.sub("", text)
    text = _TRAILING_EMPHASIS_RE.sub("", text)
    return text.strip()


def _is_duplicate_title_line(line: str, title: str) -> bool:
    """首行（去除 markdown 装饰后）与 title 归一后是否等价（#1095 决策点 4=A）."""
    candidate = _strip_title_line_decoration(line)
    if not candidate:
        return False
    normalized_title = normalize_chapter_title(title)
    if not normalized_title:
        return False
    return normalize_chapter_title(candidate) == normalized_title


def _has_noncanonical_indent(body: str) -> bool:
    """正文是否含「段首缩进非规范」的非空行（缺缩进/半角/混合/多余全角）.

    单行正文（不含换行）视作无段落结构的短文本，不纳入缩进归一：既有契约钉死
    单行 content 逐字节原样往返（#1001 自动关联 / 章节部分更新用例），
    issue #1095 实测的脏数据均为多行段落形态（第1章 58 个非空行）。
    """
    if "\n" not in body:
        return False
    for line in body.split("\n"):
        if not line.strip():
            continue
        match = _LEADING_WHITESPACE_RE.match(line)
        leading = match.group(0) if match else ""
        if leading != _FULLWIDTH_INDENT:
            return True
    return False


def _indent_paragraphs(body: str) -> str:
    """每个非空段落前置全角双空格；已有缩进先剥离再统一补全角（不叠加）."""
    lines: list[str] = []
    for line in body.split("\n"):
        if not line.strip():
            lines.append("")
            continue
        lines.append(_FULLWIDTH_INDENT + _LEADING_WHITESPACE_RE.sub("", line))
    return "\n".join(lines).strip("\n")


def _strip_markdown_text(text: str) -> str:
    """复用 services 层 ``_strip_markdown`` 正则能力（局部 import 规避循环依赖）."""
    # 局部 import：models 层若在包初始化期反向拉起 domain.services 会触发循环 import，
    # 故延迟到调用期；仅借用其正则能力，不建立持久依赖。
    from inkflow.domain.services._word_count import _strip_markdown

    return _strip_markdown(text)


def chapter_content_needs_normalize(
    content: str, title: str, *, include_indent: bool = True
) -> bool:
    """正文是否含 #1095 三类脏数据（重复标题行 / markdown / 段首缩进非规范）.

    「段首缩进非规范」含缺缩进与半角/混合/多余全角（多行正文）；单行正文
    无段落结构，原样保留。

    Args:
        include_indent: 是否把「段首缩进非规范」计为脏数据。落库路径
            （create/update 章节正文）为 True —— #1095 子现象 3「0/58 非空
            行有全角缩进」的修复面；导出路径为 False —— 导出对「无重复标题、
            无 markdown」的存量正文保持逐字节原样（既有契约）。

    落库与导出路径借此保留「干净正文原样落库」的既有语义（DRAFT 直落正文等
    场景不得被改写），仅对脏数据调用 :func:`normalize_chapter_content`。
    """
    if not content:
        return False
    if not content.strip():
        return True  # 纯空白 → 归一为空串
    lines = content.split("\n")
    if lines and _is_duplicate_title_line(lines[0], title):
        return True
    if _strip_markdown_text(content) != content:
        return True
    if not include_indent:
        return False
    return _has_noncanonical_indent(content)


def normalize_chapter_content(content: str, title: str) -> str:
    """章节正文格式归一（#1095）— 首行标题剥离 → markdown 剥离 → 段首全角缩进.

    行为（四步顺序固定）:
    ① 首行去除 markdown 装饰后与 title 等价（复用 normalize_chapter_title 容忍
       序号形态差异，如「第一章」对齐「第1章」）→ 删除该行及其后紧邻空行；
       **只处理首行**，正文中间与 title 同名的句子保留。
    ② 复用 ``_strip_markdown`` 正则剥离正文 markdown 前缀并回写（代码块内容会
       随剥离删除，属契约可接受行为）。
    ③ 每个非空段落前置 U+3000 两枚；已有全角缩进幂等跳过，半角/混合缩进归一为
       全角不叠加。
    ④ 幂等：``normalize(normalize(x)) == normalize(x)``；空串/纯空白 → ``""``。

    Args:
        content: 章节正文（可能含重复标题行 / markdown / 无缩进）。
        title: 章节标题（落库合并后的最终 title），用作首行重复判定基准。

    Returns:
        归一后的正文（空串/纯空白 → ``""``）。
    """
    if not content or not content.strip():
        return ""

    lines = content.split("\n")
    if lines and _is_duplicate_title_line(lines[0], title):
        rest = lines[1:]
        start = 0
        while start < len(rest) and not rest[start].strip():
            start += 1
        lines = rest[start:]

    normalized = _indent_paragraphs(_strip_markdown_text("\n".join(lines)))
    return normalized if normalized.strip() else ""


class ChapterStatus(StrEnum):
    """章节写作状态：草稿 → 写作中 → 审阅中 → 定稿."""

    DRAFT = "draft"
    WRITING = "writing"
    REVIEW = "review"
    FINAL = "final"


class StatusHistoryEntry(BaseModel):
    """单条状态变更记录."""

    from_status: ChapterStatus
    to_status: ChapterStatus
    at: datetime


class Volume(BaseModel):
    """卷领域实体."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    order_index: float = 0.0


class VolumeCreate(BaseModel):
    """创建卷请求 DTO."""

    title: str
    order_index: float | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("卷标题不能为空")
        if len(stripped) > 200:
            raise ValueError("卷标题不能超过 200 个字符")
        return stripped


class VolumeUpdate(BaseModel):
    """更新卷请求 DTO."""

    title: str | None = None
    order_index: float | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("卷标题不能为空")
        if len(stripped) > 200:
            raise ValueError("卷标题不能超过 200 个字符")
        return stripped


class Chapter(BaseModel):
    """章节领域实体."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    volume_id: uuid.UUID | None = None
    title: str
    content: str = ""
    status: ChapterStatus = ChapterStatus.DRAFT
    word_count: int = 0
    order_index: float = 0.0
    status_history: list[StatusHistoryEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ChapterCreate(BaseModel):
    """创建章节请求 DTO."""

    title: str
    volume_id: uuid.UUID | None = None
    content: str = ""
    order_index: float | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """#999 契约 §2：strip → fmt=None 去重/分隔归一 → 非空/长度校验."""
        stripped = v.strip()
        normalized = normalize_chapter_title(stripped, fmt=None)
        if not normalized:
            raise ValueError("章节标题不能为空")
        if len(normalized) > 500:
            raise ValueError("章节标题不能超过 500 个字符")
        return normalized


class ChapterUpdate(BaseModel):
    """更新章节请求 DTO."""

    title: str | None = None
    volume_id: uuid.UUID | None = None
    content: str | None = None
    status: ChapterStatus | None = None
    order_index: float | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        """#999 契约 §2：strip → fmt=None 去重/分隔归一 → 非空/长度校验."""
        if v is None:
            return v
        stripped = v.strip()
        normalized = normalize_chapter_title(stripped, fmt=None)
        if not normalized:
            raise ValueError("章节标题不能为空")
        if len(normalized) > 500:
            raise ValueError("章节标题不能超过 500 个字符")
        return normalized
