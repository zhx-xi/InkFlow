"""F12 历法换算（0.18.0 / #1589 / ADR-068；契约见 specs/f12-timeline/spec.md §2.10）.

纯领域模块：无 I/O、无框架依赖、确定性（同输入同输出）。

语义（ADR-068 决策 D1–D6）:
- 历法 spec 挂**项目配置**（``ProjectConfig.calendars``），**轴身份 = 事件的 ``era`` 值**
  （D1：每主轴一套）；
- ``day_count_to_date`` 把**累计日数**换算为 ``{year, month, day}``（1 基）；亚日小数**同日归整**
  （D6/C1）；
- 闰年 / 纪元周期用**受限表达式字符串**（``#`` = 年序号）—— 白名单词法递归下降求值，
  **永不 eval**（§3）；
- **未配历法 ⇒ 调用方不调用本模块**（回落「N 日」）；**本模块只产数据、不产文案**
  （粒度归前端，§2.1 S1）。

**唯一实现点**：CLI / API / GUI 不得各写一份（纪律同 §2.8 E11）。
换算**只做显示层投影**，不回写 ``time_value`` / ``era_value`` / ``era_scale``（D6）。

依据: specs/f12-timeline/spec.md §2.10 · adr/database/ADR-068.md。
"""

from __future__ import annotations

import math
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

__all__ = [
    "CalendarConfig",
    "CalendarDate",
    "CalendarSpec",
    "EraCycle",
    "LeapRule",
    "day_count_to_date",
    "evaluate_leap_rule",
    "resolve_day_count",
]

# ── 单位 → 日因子（spec §2.7 S2 归一表；`时/时辰` 按 S4 当天时刻、无日锚点时锚点取 0） ──
_UNIT_DAYS: dict[str, float] = {
    "年": 365.0,
    "岁": 365.0,
    "月": 30.0,
    "周": 7.0,
    "星期": 7.0,
    "日": 1.0,
    "天": 1.0,
    "时": 1.0 / 24.0,
    "时辰": 1.0 / 24.0,
}

_MAX_RULE_LEN = 200
_MAX_MONTHS = 24
_MAX_AXIS_LEN = 50
_MAX_EPOCH_LABEL_LEN = 20
_MAX_CYCLE_LABEL_LEN = 10

# ══════════════════════════ 受限表达式求值器（#ADR-068 §3，永不 eval） ══════════════════════════

_TOKEN_RE = re.compile(r"\s*(\d+|#|==|!=|<=|>=|&&|\|\||[+\-*/%!<>()])")
_INT_RE = re.compile(r"\d+")
_CMP_OPS = frozenset({"==", "!=", "<=", ">=", "<", ">"})

_TOKEN_LABELS = {
    "HASH": "#",
    "INT": "整数",
    "OP": "运算符",
    "EOF": "结束",
}


class _Tok:
    """token（``kind`` = INT / HASH / OP / EOF）."""

    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value


def _tokenize(rule: str) -> list[_Tok]:
    """词法：**只**接受白名单 token，其余一律报错（ADR-068 X1/X3）."""
    toks: list[_Tok] = []
    pos = 0
    while pos < len(rule):
        m = _TOKEN_RE.match(rule, pos)
        if m is None:
            raise ValueError(f"表达式含非法字符: {rule[pos : pos + 8]!r}")
        raw = m.group(1)
        if _INT_RE.fullmatch(raw):
            toks.append(_Tok("INT", raw))
        elif raw == "#":
            toks.append(_Tok("HASH", raw))
        else:
            toks.append(_Tok("OP", raw))
        pos = m.end()
    toks.append(_Tok("EOF", ""))
    return toks


class _Parser:
    """递归下降解析 + 求值（语法见 ADR-068 §3；只做布尔判定）."""

    def __init__(self, toks: list[_Tok], year: int) -> None:
        self._toks = toks
        self._i = 0
        self._year = year

    # ── token 工具 ──
    def _peek(self) -> _Tok:
        return self._toks[self._i]

    def _next(self) -> _Tok:
        tok = self._toks[self._i]
        self._i += 1
        return tok

    def _accept_op(self, *ops: str) -> str | None:
        tok = self._peek()
        if tok.kind == "OP" and tok.value in ops:
            self._next()
            return tok.value
        return None

    def _expect_op(self, op: str) -> None:
        if self._accept_op(op) is None:
            raise ValueError(f"表达式语法错误：期望 {op!r}（位置 {self._i}）")

    def parse(self) -> float | bool:
        value = self._or()
        if self._peek().kind != "EOF":
            raise ValueError(f"表达式语法错误：多余 token {self._peek().value!r}")
        return value

    def _or(self) -> float | bool:
        left = self._and()
        while self._accept_op("||"):
            right = self._and()
            left = bool(left) or bool(right)
        return left

    def _and(self) -> float | bool:
        left = self._cmp()
        while self._accept_op("&&"):
            if not bool(left):  # 短路：左侧已假 → 不评估右侧（防右侧除零等）
                self._skip_cmp()
                left = False
                continue
            right = self._cmp()
            left = bool(left) and bool(right)
        return left

    def _skip_cmp(self) -> None:
        """短路求值仍需**消费**右侧 token（语法完整性）——按同构子式求值但丢弃结果."""
        self._cmp()

    def _cmp(self) -> float | bool:
        left = self._add()
        op = self._accept_op(*_CMP_OPS)
        if op is None:
            return left
        right = self._add()
        return _compare(op, left, right)

    def _add(self) -> float | bool:
        left = self._mul()
        while True:
            op = self._accept_op("+", "-")
            if op is None:
                return left
            right = self._mul()
            lhs, rhs = _operand(left), _operand(right)
            left = lhs + rhs if op == "+" else lhs - rhs

    def _mul(self) -> float | bool:
        left = self._unary()
        while True:
            op = self._accept_op("*", "/", "%")
            if op is None:
                return left
            right = self._unary()
            lhs, rhs = _operand(left), _operand(right)
            if op == "*":
                left = lhs * rhs
            elif op == "/":
                left = lhs / rhs
            else:
                left = lhs % rhs

    def _unary(self) -> float | bool:
        if self._accept_op("!"):
            return not bool(self._unary())
        if self._accept_op("-"):
            return -_operand(self._unary())
        return self._primary()

    def _primary(self) -> float | bool:
        tok = self._peek()
        if tok.kind == "INT":
            self._next()
            return int(tok.value)
        if tok.kind == "HASH":
            self._next()
            return self._year
        if self._accept_op("("):
            value = self._or()
            self._expect_op(")")
            return value
        raise ValueError(
            f"表达式语法错误：意外的 {_TOKEN_LABELS.get(tok.kind, tok.kind)} {tok.value!r}"
        )


def _operand(value: float | bool) -> float:
    """算术运算的操作数（``bool`` 按 ``int`` 语义参与 —— Python 口径，不为布尔单独设语法）."""
    return float(value)


def _compare(op: str, left: float | bool, right: float | bool) -> bool:
    a, b = _operand(left), _operand(right)
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    return a >= b


def evaluate_leap_rule(rule: str, year: int) -> bool:
    """求值闰年表达式（``#`` = 年序号，第 1 年起）.

    Args:
        rule: 表达式字符串（白名单词法；见 ADR-068 §3）.
        year: 年序号（1 基）.

    Returns:
        布尔判定结果.

    Raises:
        ValueError: 表达式为空 / 超长 / 含非法字符 / 语法错误（⇒ spec 非法，写入面 422）.

    Note:
        求值**异常**（除零等）不抛 —— 按「不命中闰年」处置（ADR-068 X4）。
    """
    text = rule.strip()
    if not text:
        raise ValueError("表达式为空")
    if len(text) > _MAX_RULE_LEN:
        raise ValueError(f"表达式超长（>{_MAX_RULE_LEN} 字符）")
    toks = _tokenize(text)
    try:
        return bool(_Parser(toks, year).parse())
    except ZeroDivisionError:
        return False


# ══════════════════════════ 历法 spec（ADR-068 §1） ══════════════════════════


class LeapRule(BaseModel):
    """闰年规则：``rule`` 表达式命中 ⇒ 该年**多出** ``add_days`` 天，计入第 ``month`` 月."""

    rule: str
    add_days: int = Field(default=1, ge=1, le=10)
    month: int = Field(default=1, ge=1)

    @field_validator("rule")
    @classmethod
    def _validate_rule(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("表达式为空")
        if len(text) > _MAX_RULE_LEN:
            raise ValueError(f"表达式超长（>{_MAX_RULE_LEN} 字符）")
        _tokenize(text)  # 词法自检：失败抛 ValueError（不等到求值）
        return text


class EraCycle(BaseModel):
    """「N 年一纪元」：``cycle = floor((year - 1) / years) + 1``，标签前插「{cycle} {label}」."""

    years: int = Field(ge=2, le=10_000)
    label: str = Field(min_length=1, max_length=_MAX_CYCLE_LABEL_LEN)


class CalendarSpec(BaseModel):
    """一条轴的历法（轴身份 = 事件 ``era`` 值；``""`` = 默认轴）.

    Attributes:
        axis: 轴名（= 事件 ``era`` 值；``""`` = 默认轴）；去空白、≤ 50 字符.
        epoch_label: 第 1 年年号（可空 ⇒ 只显示数字）.
        month_names: 月名（可空；非空时必须与 ``month_days`` 等长）.
        month_days: 每月天数（不等月长；非空、每项 ≥ 1、上限 24 个月）.
        leap: 闰年规则（可空 ⇒ 无闰）.
        intercalary: **0.18.0 保留字段、不参与换算**（无名日 / 独立节日）.
        era_cycle: 纪元周期（可空）.
    """

    axis: str = ""
    epoch_label: str | None = Field(default=None, max_length=_MAX_EPOCH_LABEL_LEN)
    month_names: list[str] | None = None
    month_days: list[int] = Field(min_length=1, max_length=_MAX_MONTHS)
    leap: LeapRule | None = None
    intercalary: list[dict[str, Any]] = Field(default_factory=list)
    era_cycle: EraCycle | None = None

    @field_validator("axis")
    @classmethod
    def _strip_axis(cls, value: str) -> str:
        text = value.strip()
        if len(text) > _MAX_AXIS_LEN:
            raise ValueError(f"轴名超长（>{_MAX_AXIS_LEN} 字符）")
        return text

    @field_validator("month_days")
    @classmethod
    def _months_positive(cls, value: list[int]) -> list[int]:
        if any(days < 1 for days in value):
            raise ValueError("每月天数必须 ≥ 1")
        return value

    @field_validator("month_names")
    @classmethod
    def _names_non_empty(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not name.strip() for name in value):
            raise ValueError("月名不得为空串")
        return value

    @model_validator(mode="after")
    def _cross_checks(self) -> CalendarSpec:
        if self.month_names is not None and len(self.month_names) != len(self.month_days):
            raise ValueError("month_names 长度必须与 month_days 一致")
        if self.leap is not None and self.leap.month > len(self.month_days):
            raise ValueError("leap.month 超出 month_days 长度")
        return self

    @property
    def days_per_year(self) -> int:
        """平年年长（不含闰日）."""
        return sum(self.month_days)


class CalendarConfig(BaseModel):
    """项目级历法配置（``ProjectConfig.calendars``；轴名唯一）."""

    calendars: list[CalendarSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _axes_unique(self) -> CalendarConfig:
        axes = [spec.axis for spec in self.calendars]
        if len(set(axes)) != len(axes):
            raise ValueError("calendars 中同一 axis 不得重复")
        return self

    def spec_for(self, axis: str) -> CalendarSpec | None:
        """取某轴的历法；未配置 → None（调用方据此回落「N 日」，D3）."""
        key = axis.strip()
        for spec in self.calendars:
            if spec.axis == key:
                return spec
        return None


class CalendarDate(BaseModel):
    """换算结果（1 基；``cycle`` = 纪元周期序号，None = 无纪元周期）."""

    year: int
    month: int
    day: int
    cycle: int | None = None


# ══════════════════════════ 换算口径（ADR-068 §2 / f12 §2.10 L1–L5） ══════════════════════════


def _year_length(spec: CalendarSpec, year: int) -> int:
    """年长 = 平年月长和 +（闰年规则命中 ? add_days : 0）（L2）."""
    length = spec.days_per_year
    if spec.leap is not None and evaluate_leap_rule(spec.leap.rule, year):
        length += spec.leap.add_days
    return length


def day_count_to_date(day_count: float, spec: CalendarSpec) -> CalendarDate:
    """累计日数 → ``{year, month, day}``（L1–L4；唯一实现点）.

    Args:
        day_count: 归一日数（**亚日小数同日归整**：内部 ``floor`` —— 同一日内的多个刻度
            得到同一结果）.
        spec: 该轴的历法（未配历法时调用方**不应**调用本函数）.

    Returns:
        ``CalendarDate``（``year`` / ``month`` / ``day`` 均 1 基；``era_cycle`` 生效时
        带 ``cycle``）.

    Note:
        逐年 / 逐月累加：历法年数 < 10⁴ 足够（ADR-068 C3）；更大时改前缀和 / 闭式。
    """
    remaining = math.floor(day_count)
    if remaining < 0:
        remaining = 0

    year = 1
    while remaining >= _year_length(spec, year):
        remaining -= _year_length(spec, year)
        year += 1

    leap_days = _year_length(spec, year) - spec.days_per_year
    leap_month = spec.leap.month if spec.leap is not None and leap_days else 0
    for index, days in enumerate(spec.month_days):
        length = days + (leap_days if index + 1 == leap_month else 0)
        if remaining < length:
            day = remaining + 1
            cycle = None
            if spec.era_cycle is not None:
                cycle = (year - 1) // spec.era_cycle.years + 1
            return CalendarDate(year=year, month=index + 1, day=day, cycle=cycle)
        remaining -= length

    # 不可达（循环内必然返回）；保留以防 month_days 为空（已被校验拒绝）
    raise AssertionError("month_days 为空：spec 校验应已拒绝")


def resolve_day_count(
    era: str,
    era_value: float | None,
    time_value: float | None,
    time_unit: str | None,
) -> float | None:
    """取「用于换算的日数」——**现行标签的取值来源**（ADR-068 §2.1 S2/S3）.

    Args:
        era: 事件 `era` 值；非空 = 纪元轴.
        era_value: 轴内值.
        time_value: 全局标量（累计时长）.
        time_unit: `time_value` 的物理尺度（§2.7 S2）.

    Returns:
        归一到「日」的数值；输入未知 → None.

    Note:
        ① 纪元轴（`era` 非空）⇒ 取 `era_value`（**该历法自己的「日」尺度**，S3），
        **不看** `time_value` / `time_unit`；
        ② 默认轴 ⇒ `time_value × factor(time_unit)`（S2：年/岁=365、月=30、周/星期=7、日/天=1，
        `时/时辰` = 当天时刻按 S4 无日锚点取 0）；未列举单位 = 时基裸值（因子 1）；
        ③ **本函数不接收 `era_scale`** —— 流速比只影响跨轴纵向定位（D6 / 验收 N7）。
    """
    if era.strip():
        return None if era_value is None else float(era_value)
    if time_value is None:
        return None
    factor = _UNIT_DAYS.get((time_unit or "").strip(), 1.0)
    return float(time_value) * factor
