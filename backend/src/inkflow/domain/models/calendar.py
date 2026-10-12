"""F12 历法 spec（数据契约）—— 0.18.0 / #1589 / ADR-068；契约见 specs/f12-timeline/spec.md §2.10.

本模块 = **纯数据契约 + 表达式词法/求值**（`LeapRule` 的合法性校验需要它，故与 spec 同模块）。
换算（累计日数 → 年月日）在 `domain/services/calendar.py` —— **唯一实现点**（纪律同 §2.8 E11）。

分层说明：本模块**只依赖 pydantic / re**（叶子模块）。历法 spec 被
`domain/models/project.py`（项目配置）与 `domain/models/timeline.py`（事件 `calendar_date` 字段）
引用 —— 若把数据类留在 `domain/services/calendar.py`，`models → services` 会触发
`domain/services/__init__.py` 的**全量服务导入**（→ infrastructure.llm → core.config 循环导入，
实测 ImportError）→ 故数据类必须在 models 层。

语义（ADR-068 决策 D1–D6）:
- 历法 spec 挂**项目配置**（``ProjectConfig.calendars``），**轴身份 = 事件的 ``era`` 值**
  （D1：每主轴一套）；
- 闰年 / 纪元周期用**受限表达式字符串**（``#`` = 年序号）—— 白名单词法递归下降求值，
  **永不 eval**（§3）；
- **未配历法 ⇒ 不换算**（D3：不给默认值、不猜）。

依据: specs/f12-timeline/spec.md §2.10 · adr/database/ADR-068.md。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

__all__ = [
    "CalendarConfig",
    "CalendarDate",
    "CalendarSpec",
    "EraCycle",
    "LeapRule",
    "evaluate_leap_rule",
]

_MAX_RULE_LEN = 200
_MAX_MONTHS = 24
_MAX_AXIS_LEN = 50
_MAX_EPOCH_LABEL_LEN = 20
_MAX_CYCLE_LABEL_LEN = 10

# ══════════════════════════ 受限表达式求值器（ADR-068 §3，永不 eval） ══════════════════════════

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


class CalendarDate(BaseModel):
    """换算结果（1 基）+ **轴显示数据**（年号 / 纪元名 —— 纯数据，前端不硬编码文案）."""

    year: int
    month: int
    day: int
    cycle: int | None = None
    """纪元周期序号（`era_cycle` 生效时；None = 无纪元周期）."""
    era_cycle_label: str | None = None
    """纪元名（如「劫」；仅 `cycle` 非空时有意义）—— 前端拼「{cycle} {era_cycle_label}」."""
    epoch_label: str | None = None
    """第 1 年年号（可空）—— 前端拼「{epoch_label} {year} 年」，无则「{year} 年」."""
