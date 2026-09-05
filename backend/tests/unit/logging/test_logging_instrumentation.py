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

F53 红线：instrument 不泄漏参数中的敏感值（params 摘要仅含标量 + mask_fields 脱敏，
敏感键名（key/token/secret/password/...）值恒为 "****"）。

#930 契约扩展（TestInstrumentFailureParams）：失败/预期失败/流中断路径必须填 params
摘要（F57 spec §字段约定「params 含脱敏后参数摘要」）：
- 从调用签名绑定实参提取**标量**（str/int/float/bool）入参；None/复杂对象/dict 跳过；
- 名为 content/text/prompt/body/draft/markdown/html/code 的大文本字段排除；
- str 值截断 ≤100 字符（超出以 "…" 结尾）；实参摘要最多 8 键（按签名顺序）；
- _log_expected 额外 http_status（int）+ detail（str(exc.detail) 截断）；
- _log_failed 额外 error_type（type name）+ error（str(exc) 截断）；
- 全部经 mask_fields 脱敏。
RED 预期：当前 _log_failed/_log_expected/_log_stream_broken 不填 params → 断言 FAIL。
════════════════════════════════════════════════════════════════════════
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


# ── #930 失败/预期失败/流断路径 params 摘要 ──


class TestInstrumentFailureParams:
    """契约：_log_failed/_log_expected/_log_stream_broken 填脱敏后的入参摘要。

    F57 spec §字段约定：params 含脱敏后参数摘要（不泄 key）。当前实现不填 → RED。
    """

    def test_http_expected_warn_params_has_scalar_args_and_http_info(self):
        from fastapi import HTTPException

        @instrument(caller_type="api")
        def get_summary(project_id: int, chapter_name: str):
            raise HTTPException(status_code=404, detail="章节不存在")

        records, sid = _capture_records("WARNING")
        try:
            with pytest.raises(HTTPException):
                get_summary(project_id=7, chapter_name="第三章")
        finally:
            logger.remove(sid)
        warn = _find(records, "WARNING", "get_summary")
        params = warn["extra"]["params"]
        assert params.get("project_id") == 7
        assert params.get("chapter_name") == "第三章"
        assert params.get("http_status") == 404
        assert params.get("detail") == "章节不存在"
        assert warn["extra"]["error_code"] == "E_HTTP_404"

    async def test_http_expected_warn_params_from_positional_args(self):
        from fastapi import HTTPException

        @instrument(caller_type="api")
        async def get_summary(project_id: int, q: str):
            raise HTTPException(status_code=404, detail="nf")

        records, sid = _capture_records("WARNING")
        try:
            with pytest.raises(HTTPException):
                await get_summary(7, "蜀山")
        finally:
            logger.remove(sid)
        params = _find(records, "WARNING", "get_summary")["extra"]["params"]
        assert params.get("project_id") == 7
        assert params.get("q") == "蜀山"

    def test_uncaught_error_params_has_error_info(self):
        @instrument(caller_type="api")
        def broken(project_id: int):
            raise ValueError("boom")

        records, sid = _capture_records("ERROR")
        try:
            with pytest.raises(ValueError):
                broken(project_id=3)
        finally:
            logger.remove(sid)
        err = _find(records, "ERROR", "broken")
        params = err["extra"]["params"]
        assert params.get("project_id") == 3
        assert params.get("error_type") == "ValueError"
        assert "boom" in params.get("error", "")
        assert err["extra"]["error_code"] == "X_UNCAUGHT"

    async def test_stream_broken_warn_params_has_args(self):
        @instrument(caller_type="llm")
        async def flaky_stream(model: str):
            yield "a"
            raise RuntimeError("broke")

        records, sid = _capture_records("WARNING")
        try:
            with pytest.raises(RuntimeError):
                async for _ in flaky_stream(model="gpt-x"):
                    pass
        finally:
            logger.remove(sid)
        warn = _find(records, "WARNING", "flaky_stream")
        params = warn["extra"]["params"]
        assert params.get("model") == "gpt-x"
        assert warn["extra"]["error_code"] == "X_STREAM_BROKEN"

    def test_params_sensitive_masked_bigtext_excluded(self):
        @instrument(caller_type="api")
        def create(name: str, api_key: str, content: str):
            raise RuntimeError("x")

        records, sid = _capture_records("ERROR")
        try:
            with pytest.raises(RuntimeError):
                create(name=" proj ", api_key="sk-secret", content="a" * 500)
        finally:
            logger.remove(sid)
        params = _find(records, "ERROR", "create")["extra"]["params"]
        assert params.get("api_key") == "****"  # F53：敏感键名值脱敏
        assert params.get("name") == " proj "
        assert "content" not in params  # 大文本字段排除

    def test_params_str_truncated_100_and_max_8_keys(self):
        @instrument(caller_type="api")
        def many(a: str, b1: int, b2: int, b3: int, b4: int, b5: int, b6: int, b7: int, b8: int):
            raise RuntimeError("x")

        records, sid = _capture_records("ERROR")
        try:
            with pytest.raises(RuntimeError):
                many(a="长" * 200, b1=1, b2=2, b3=3, b4=4, b5=5, b6=6, b7=7, b8=8)
        finally:
            logger.remove(sid)
        params = _find(records, "ERROR", "many")["extra"]["params"]
        assert params["a"].endswith("…")
        assert len(params["a"]) == 101  # 100 字符 + 省略号
        arg_keys = [k for k in params if k.startswith("b")]
        assert len(arg_keys) <= 7  # 实参摘要（不含 error_type/error）≤ 8 键


class TestInstrumentPydanticBody:
    """#930：Pydantic 请求体（generate_outline 同名 422 场景）提取资源标识标量字段。"""

    def test_pydantic_body_scalar_fields_extracted(self):
        from fastapi import HTTPException
        from pydantic import BaseModel

        class OutlineCreate(BaseModel):
            name: str
            description: str = "d" * 300
            num_chapters: int = 3

        @instrument(caller_type="api")
        def generate_outline(body: OutlineCreate):
            raise HTTPException(status_code=422, detail="同名项目已存在")

        records, sid = _capture_records("WARNING")
        try:
            with pytest.raises(HTTPException):
                generate_outline(body=OutlineCreate(name="同名的项目"))
        finally:
            logger.remove(sid)
        params = _find(records, "WARNING", "generate_outline")["extra"]["params"]
        assert params.get("name") == "同名的项目"
        assert params.get("http_status") == 422
        assert "detail" in params
        assert "body" not in params  # 模型对象本身不入 params
        assert "description" not in params  # 大文本字段排除
