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
