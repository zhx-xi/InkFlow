"""F57 @instrument 装饰器 — RED 契约测试（任务 #888-S1 / spec §4.1）。

契约来源
--------
specs/f57-logging-i18n/spec.md §4.1（装饰器设计要点：functools.wraps / async 感知 /
日志后原样 re-raise / 「log.call.*」message_key / caller_name 从 __qualname__ 推导）。

目标模块：`backend/src/inkflow/logging/instrument.py`（instrument，经 logging/__init__ 导出）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. instrument(fn=None, *, caller_type: str = "api", event: str | None = None)
   - 支持 @instrument 与 @instrument(caller_type="api") 两种形态（fn=None 时返回装饰器）。
   - functools.wraps：保留 __name__ / __qualname__ / __doc__ / 签名（inspect.signature
     经 __wrapped__ 与原始函数一致）。
   - async 感知：inspect.iscoroutinefunction 分派；async 函数返回 async wrapper，
     sync 函数返回 sync wrapper。
   - caller_name 从 func.__qualname__ 自动推导；event 默认 func.__name__。
   - 用 `import time` + `time.perf_counter()`（勿 `from time import perf_counter`——测试
     需 monkeypatch time.perf_counter）。

2. 日志（经 logging.log_structured 发布到 loguru；message 为 loguru record["message"]，
   结构化字段在 record["extra"]）：
   - 入口：DEBUG，message_key = f"log.call.{event}"，message = f"{event} started"。
   - 出口成功：DEBUG，message = f"{event} completed"，extra 带 duration_ms（>=0）。
   - 异常：ERROR，message = f"{event} failed"，extra 带 duration_ms + stack +
     error_code="X_UNCAUGHT"；记录后原样 re-raise（不吞异常）。

RED 阶段预期：`inkflow.logging` 包未创建 → import 即失败（整文件收集失败，门禁 M4）。
GREEN 阶段：实现 logging/instrument.py 后全绿。

F53 红线：instrument 不泄漏参数中的敏感值（本批不 dump params 摘要——防泄 key）。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import asyncio
import inspect
import sys

import pytest
from loguru import logger

from inkflow.logging import instrument


@pytest.fixture(autouse=True)
def _restore_loguru():
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")


def _capture_records(level: str = "DEBUG"):
    records: list = []
    sid = logger.add(lambda m: records.append(m.record), level=level, format="{message}")
    return records, sid


def _find(records: list, level: str, event: str) -> dict:
    """返回匹配 level 且 extra.event == event 的完整 loguru record；无则 AssertionError。"""
    for rec in records:
        if rec["level"].name == level and rec["extra"].get("event") == event:
            return rec
    raise AssertionError(
        f"未捕获到 level={level} event={event} 的记录；levels={[r['level'].name for r in records]}"
    )


def _exit_records(records: list, event: str) -> list[dict]:
    """匹配 level=DEBUG、event 相同、extra 带 duration_ms 的出口记录。"""
    return [
        r
        for r in records
        if r["level"].name == "DEBUG"
        and r["extra"].get("event") == event
        and r["extra"].get("duration_ms") is not None
    ]


# ── 签名/元数据保真 ──


class TestInstrumentSignature:
    def test_sync_signature_preserved(self):
        @instrument
        def create_chapter(self, title: str, *, count: int = 1) -> str:
            return f"{title}-{count}"

        assert create_chapter.__name__ == "create_chapter"
        assert "title" in inspect.signature(create_chapter).parameters
        assert list(inspect.signature(create_chapter).parameters) == ["self", "title", "count"]

    def test_async_signature_preserved(self):
        @instrument
        async def create_chapter(self, title: str) -> str:
            return title

        assert create_chapter.__name__ == "create_chapter"
        assert list(inspect.signature(create_chapter).parameters) == ["self", "title"]

    def test_method_qualname_used_as_caller_name(self, monkeypatch):
        monkeypatch.setattr("time.perf_counter", lambda: 10.0)  # 固定时钟免 flaky

        @instrument
        def my_method(self):
            return 1

        records, sid = _capture_records("DEBUG")
        try:
            my_method(type("X", (), {}))  # 绑定 self 调用
        finally:
            logger.remove(sid)
        rec = _find(records, "DEBUG", "my_method")
        assert rec["extra"]["caller_name"] == my_method.__qualname__
        assert "TestInstrumentSignature" in rec["extra"]["caller_name"]


# ── sync 函数：入口/出口/异常 ──


class TestInstrumentSync:
    def test_sync_entry_and_exit_debug_records(self):
        @instrument(caller_type="api")
        def create_chapter(title: str) -> str:
            return f"done:{title}"

        records, sid = _capture_records("DEBUG")
        try:
            result = create_chapter("第一章")
        finally:
            logger.remove(sid)
        assert result == "done:第一章"
        entry = _find(records, "DEBUG", "create_chapter")
        assert entry["extra"]["caller_type"] == "api"
        assert entry["extra"]["message_key"] == "log.call.create_chapter"
        assert "started" in entry["message"]
        exit_recs = _exit_records(records, "create_chapter")
        assert exit_recs, "出口 DEBUG 记录应带 duration_ms"
        assert exit_recs[0]["extra"]["duration_ms"] >= 0

    def test_sync_unhandled_exception_logs_error_and_reraises(self):
        @instrument
        def broken() -> None:
            raise ValueError("boom")

        records, sid = _capture_records("ERROR")
        try:
            with pytest.raises(ValueError, match="boom"):
                broken()
        finally:
            logger.remove(sid)
        err = _find(records, "ERROR", "broken")
        assert err["extra"]["stack"]  # ERROR 带 stack
        assert err["extra"]["error_code"] == "X_UNCAUGHT"


# ── async 函数：入口/出口/异常 ──


class TestInstrumentAsync:
    async def test_async_entry_and_exit_debug_records(self):
        @instrument(caller_type="agent")
        async def run_agent(step: str) -> str:
            await asyncio.sleep(0)
            return f"step:{step}"

        records, sid = _capture_records("DEBUG")
        try:
            result = await run_agent("plan")
        finally:
            logger.remove(sid)
        assert result == "step:plan"
        entry = _find(records, "DEBUG", "run_agent")
        assert entry["extra"]["caller_type"] == "agent"
        assert "started" in entry["message"]
        exit_recs = _exit_records(records, "run_agent")
        assert exit_recs, "async 出口 DEBUG 记录应带 duration_ms"

    async def test_async_unhandled_exception_logs_error_and_reraises(self):
        @instrument
        async def broken_async() -> None:
            raise RuntimeError("async boom")

        records, sid = _capture_records("ERROR")
        try:
            with pytest.raises(RuntimeError, match="async boom"):
                await broken_async()
        finally:
            logger.remove(sid)
        err = _find(records, "ERROR", "broken_async")
        assert err["extra"]["stack"]
        assert err["extra"]["error_code"] == "X_UNCAUGHT"


# ── @instrument(...) 带参形态 ──


class TestInstrumentWithArgs:
    def test_caller_type_override(self):
        @instrument(caller_type="llm")
        def call_llm() -> str:
            return "ok"

        records, sid = _capture_records("DEBUG")
        try:
            call_llm()
        finally:
            logger.remove(sid)
        entry = _find(records, "DEBUG", "call_llm")
        assert entry["extra"]["caller_type"] == "llm"

    def test_event_override(self):
        @instrument(event="custom.event")
        def do_thing() -> str:
            return "x"

        records, sid = _capture_records("DEBUG")
        try:
            do_thing()
        finally:
            logger.remove(sid)
        entry = _find(records, "DEBUG", "custom.event")
        assert entry["extra"]["message_key"] == "log.call.custom.event"
