"""F12/F14 时间线「后置时间归一」——确定性文本解析器（#1581，ADR-067 / spec f12 §2.9 Z2）.

把提取出的 `time_display` **原文表达**解析为可入 `time_value` 的数值键。

设计约束（spec f12 §2.9）:

- **纯函数**（同输入同输出，零 I/O、零框架依赖；领域层，无 LangChain —— ADR-015）；
- **零 LLM**：确定性识别，不猜、不推算、不做跨事件锚定；
- **失败必须带 reason**（禁止静默丢弃；调用方据此落暂存区并在待确认区展示）；
- 只覆盖**绝对可定位**形态 —— 纪年式 / 真序数 / 数量 / 月日；
  相对与模糊表达（``第二天`` / ``过了两天`` / ``那年冬天`` / ``卯时三刻`` / ``三十二岁``）
  一律返回失败，交作者在待确认区确认。

单位口径：**保留原单位**（``unit`` 即尺度标签，f12 §2.7 S1/S3 不变）——
月日折算为「日」，其余按原文单位原样产出。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["ParsedTime", "parse_time_display"]

_CN_DIGITS = {
    "零": 0,
    "〇": 0,
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
_CN_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}

_CN_CHARS = "".join(_CN_DIGITS) + "".join(_CN_SMALL_UNITS) + "万"

_UNITS = "天|日|年|月|周|星期"
"""数量 / 序数形态认可的时间单位（**不含「岁」** —— 人物年龄不是世界内时间）。"""

_NUM_ARABIC = r"[0-9]+"
_NUM_CN = rf"[{_CN_CHARS}]+"

_ERA_RE = re.compile(rf"^(?P<era>[^\d\s第]{{1,10}})[\s·]*(?P<n>{_NUM_ARABIC})\s*年[^\d]{{0,4}}$")
_ORDINAL_ARABIC_RE = re.compile(rf"第\s*(?P<n>{_NUM_ARABIC})\s*(?P<u>{_UNITS})")
_MONTH_DAY_RE = re.compile(
    rf"^(?P<m>{_NUM_ARABIC}|{_NUM_CN})\s*月\s*(?P<d>[初廿]{_NUM_CN}|{_NUM_ARABIC}|{_NUM_CN})\s*[日号]?$"
)
_QUANTITY_RE = re.compile(rf"^(?P<n>{_NUM_ARABIC}|{_NUM_CN})\s*个?\s*(?P<u>{_UNITS})$")

_CLOCK_RE = re.compile(
    rf"^(?:[子丑寅卯辰巳午未申酉戌亥]时|[0-9{_CN_CHARS}]{{1,3}}更|[0-9{_CN_CHARS}]{{1,3}}刻)"
)
_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile("岁"), "人物年龄，非世界内时间"),
    (_CLOCK_RE, "当天时刻，无日锚点"),
    (re.compile(r"^(?:过了|隔|又过|经过|走了)"), "相对时长，需作者锚定"),
    (re.compile(r"[后前]$"), "相对时间，需作者锚定"),
    (re.compile(r"[几多]"), "数量模糊，无法定位"),
)

_DAYS_PER_MONTH = 30
"""月日折算口径（对齐 f12 §2.7 S2 的「月 = 30 日」常量表）。"""


@dataclass(frozen=True)
class ParsedTime:
    """解析成功的时间三元组.

    Attributes:
        value: 数值键（原单位下的量；月日折算为「日」）.
        unit: 尺度标签（保留原单位）.
        era: 纪元轴名（仅纪年式非空）.
    """

    value: float
    unit: str
    era: str = ""


def _to_int(token: str) -> int | None:
    """把「阿拉伯数字 / 中文数字」token 转为 int；不可解析返回 None."""
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    total = 0
    section = 0
    digit = 0
    seen = False
    for ch in token:
        if ch in _CN_DIGITS:
            digit = _CN_DIGITS[ch]
            seen = True
        elif ch in _CN_SMALL_UNITS:
            unit = _CN_SMALL_UNITS[ch]
            section += (digit if digit else 1) * unit
            digit = 0
            seen = True
        elif ch == "万":
            section = (section + digit) * 10000
            total += section
            section = 0
            digit = 0
            seen = True
        else:
            return None
    return (total + section + digit) if seen else None


def _fail_reason(raw: str) -> str:
    """未定原因（供待确认区展示，禁止静默丢弃）."""
    text = raw.strip()
    if not text:
        return "原文未给出时间线索"
    for pattern, reason in _HINTS:
        if pattern.search(text):
            return reason
    return "无绝对时间量（相对 / 模糊表达）"


def parse_time_display(raw: str | None) -> tuple[ParsedTime | None, str]:
    """`time_display` 原文 → (``ParsedTime``, "") 或 (``None``, reason).

    Args:
        raw: 原文时间表达（``None`` / 空串 / 纯空白 → 失败）.

    Returns:
        成功 → ``(ParsedTime(value, unit, era), "")``；
        失败 → ``(None, reason)``（reason 非空，供暂存区展示）.
    """
    text = (raw or "").strip()
    if not text:
        return None, _fail_reason(text)

    # 真序数优先于纪年式：「第16年」是序号，不是「轴名 = 第」（纪年式另排除了「第」）
    ordinal = _ORDINAL_ARABIC_RE.search(text)
    if ordinal is not None:
        # 仅认**阿拉伯数字**序号（「第 5 天」/「第16年」）——中文数字序号
        # （「第二天」「第九天」）在叙述文中是相对表达 → 不覆盖，交作者确认。
        return ParsedTime(value=float(int(ordinal.group("n"))), unit=ordinal.group("u")), ""

    era_match = _ERA_RE.match(text)
    if era_match is not None:
        return (
            ParsedTime(
                value=float(int(era_match.group("n"))),
                unit="年",
                era=era_match.group("era").strip(),
            ),
            "",
        )

    month_day = _MONTH_DAY_RE.match(text)
    if month_day is not None:
        month = _to_int(month_day.group("m"))
        day_token = month_day.group("d")
        if day_token[0] in ("初", "廿"):
            day = _to_int(day_token[1:])
            if day is not None and day_token[0] == "廿":
                day += 20
        else:
            day = _to_int(day_token)
        if (
            month is not None
            and day is not None
            and 1 <= month <= 12
            and 1 <= day <= _DAYS_PER_MONTH
        ):
            return ParsedTime(value=float((month - 1) * _DAYS_PER_MONTH + day), unit="日"), ""

    quantity = _QUANTITY_RE.match(text)
    if quantity is not None:
        number = _to_int(quantity.group("n"))
        if number is not None:
            return ParsedTime(value=float(number), unit=quantity.group("u")), ""

    return None, _fail_reason(text)
