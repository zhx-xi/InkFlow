"""CLI 时间显示本地化收敛口（#1000 / ADR-055）。

存储层与数据层（REST API / MCP / ``--json`` 信封）一律 UTC；面向用户的 CLI
人类输出统一经本函数转换为系统本地时区，形态 ``YYYY-MM-DD HH:mm:ss``。

生产 API 返回的 SQLite ``DateTime`` 值为 naive ISO 串（tzinfo 被剥离，值本身
= UTC）。故 naive 输入必须先 ``replace(tzinfo=UTC)`` 再 ``astimezone()``：
直接对 naive 值调用 ``astimezone()`` 会被 Python 当作系统本地时间、漏掉整个
时区偏移。aware 输入（``Z`` / ``±HH:MM``）直接换算。

``tz`` 参数是测试确定性注入通道（Windows 无 ``time.tzset`` 且 ``TZ`` 环境变量
被 msvcrt 误解析）；``tz=None`` 表示系统本地时区。
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo

_DISPLAY_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_local(iso: str | None, tz: tzinfo | None = None) -> str:
    """UTC ISO 串 → 本地时区显示串（秒粒度，微秒截断不进位）。

    空值/空串/解析失败原样直出（显示层防御，CLI 不炸）；naive 输入按 UTC 口径
    补齐 tzinfo 后再换算到 ``tz``（``None`` = 系统本地时区）。
    """
    if not iso:
        return ""
    try:
        parsed = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return iso
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(tz).strftime(_DISPLAY_FORMAT)
