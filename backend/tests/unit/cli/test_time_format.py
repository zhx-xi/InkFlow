"""#1000 CLI 时间显示本地化 RED 契约 — inkflow.cli._time.format_local（ADR-055）。

契约（用户拍板 #1000：存储/传输一律 UTC，面向用户显示一律本地时区）：

- naive ISO（生产 API 常态：SQLite DateTime 列剥 tzinfo，值=UTC——探针实证
  tzinfo=None）→ 必须先补 UTC 再转本地。任务书直转公式
  `fromisoformat(iso).astimezone()` 对 naive 输入会当本地时间不转换（漏偏移），
  本文件 test_naive_* 用例即该陷阱的守护。
- aware ISO（Z / ±HH:MM）→ 直接换算到目标时区。
- tz 注入参数 = 测试确定性通道：Windows 无 time.tzset 且 TZ env 被 msvcrt
  误解析（探针实证 TZ=Asia/Shanghai 下 astimezone() 输出 +1 而非 +8），
  故已知时区断言一律走 tz 注入，不依赖 runner 系统时区。
- tz=None → 系统本地时区（datetime.astimezone() 无参语义）。
- 空串/None/解析失败 → 原样直出（显示层防御，CLI 不炸）。
- 输出形态 'YYYY-MM-DD HH:mm:ss'（秒粒度；微秒截断不进位）。

RED 预期：inkflow.cli._time 模块尚不存在 → 本文件收集期 ModuleNotFoundError
（collected 0 items）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from inkflow.cli._time import format_local  # RED: 模块尚不存在

TZ8 = timezone(timedelta(hours=8))
TZ_MINUS5 = timezone(timedelta(hours=-5))


class TestFormatLocalTzInjection:
    """已知时区 + 已知 ISO 的确定断言（tz 注入，与 runner 系统时区解耦）。"""

    def test_naive_utc_input_converts_to_injected_tz(self) -> None:
        """naive = UTC 存储口径 → +8 注入必须加 8 小时（直转陷阱守护）。"""
        assert format_local("2026-01-01T00:00:00", tz=TZ8) == "2026-01-01 08:00:00"

    def test_aware_z_input_converts(self) -> None:
        assert format_local("2026-08-09T10:05:00Z", tz=TZ8) == "2026-08-09 18:05:00"

    def test_aware_offset_input_normalizes(self) -> None:
        """+08:00 偏移串 → 同一瞬间在 +8 目标时区显示原值。"""
        assert format_local("2026-08-09T10:05:00+08:00", tz=TZ8) == "2026-08-09 10:05:00"

    def test_negative_tz_injection_cross_day(self) -> None:
        assert format_local("2026-01-01T00:00:00Z", tz=TZ_MINUS5) == "2025-12-31 19:00:00"

    def test_micros_truncated_not_rounded(self) -> None:
        assert format_local("2026-09-09T23:58:53.963575", tz=TZ8) == "2026-09-10 07:58:53"

    def test_cross_day_carry(self) -> None:
        assert format_local("2026-09-04T23:30:00Z", tz=TZ8) == "2026-09-05 07:30:00"


class TestFormatLocalSystemTz:
    """tz=None → 系统本地时区（与内联独立换算等价，任意 runner TZ 下成立）。"""

    @pytest.mark.parametrize(
        "iso",
        [
            "2026-01-01T00:00:00",
            "2026-08-09T10:05:00Z",
            "2026-08-09T10:05:00+08:00",
        ],
    )
    def test_matches_inline_local_conversion(self, iso: str) -> None:
        parsed = datetime.fromisoformat(iso)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        expected = parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        assert format_local(iso) == expected


class TestFormatLocalDefensive:
    """空/None/非法 → 原样直出（显示层防御契约）。"""

    def test_empty_string_passthrough(self) -> None:
        assert format_local("") == ""

    def test_none_passthrough(self) -> None:
        assert format_local(None) == ""

    def test_invalid_iso_passthrough(self) -> None:
        assert format_local("not-a-date") == "not-a-date"
