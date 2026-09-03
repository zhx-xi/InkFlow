"""F57 API 端点 @instrument 铺开 — RED 契约测试（任务 #888-S2 / spec §4.1 / §12 M4）。

契约来源
--------
specs/f57-logging-i18n/spec.md §4 埋点矩阵（API 路由端点 DEBUG 入口调试）+ §4.1 结构层
（@instrument 装饰器铺开 API 路由端点）+ §12 M4（可断言：任一端点 handler 触发 DEBUG
入口日志；DEBUG 关闭时无 DEBUG 记录）。

目标：**真实 FastAPI 应用**（inkflow.api.app）的全部 `/api/v1` 路由端点已挂 @instrument；
一个零依赖端点 handler 触发 DEBUG 入口日志；默认 debug=False 时 DEBUG 不落 INFO sink。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 必须满足的契约）
════════════════════════════════════════════════════════════════════
1. 全部 `/api/v1` APIRoute 的 endpoint 已用 @instrument 包裹（结构层）：route.endpoint
   有 __wrapped__（functools.wraps 设置），且 __name__ 保留原 handler 名。
   - FastAPI 0.141+ 用 _IncludedRouter 惰性挂载：app.routes 顶层是 _IncludedRouter，
     其 original_router.routes 才是真实 APIRoute（本测试递归展平）。
   - api_status（inkflow/api/__init__.py 直接 @app.get）也是 APIRoute，须同样被包裹。
2. 端点触发 DEBUG 入口日志（可断言）：调用 api_status() → 经 @instrument 打 DEBUG
   `f"{event} started"`，caller_type="api"，message_key="log.call.api_status"；成功出口
   DEBUG `f"{event} completed"` 带 duration_ms。
3. 默认 debug=False：log_structured(level="DEBUG") 不落入 INFO sink；config.debug 默认 False。
4. 两族 message_key 不冲突：装饰器产 log.call.*，显式语义产 log.event.*/log.check.*。

RED 阶段预期：S1 基座端点均未挂 @instrument → 断言 __wrapped__ 失败 + 无 DEBUG 入口日志。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import importlib
import sys
import unittest

import pytest
from fastapi.routing import APIRoute
from loguru import logger

from inkflow.api.app import app
from inkflow.logging import log_structured


@pytest.fixture(autouse=True)
def _restore_loguru():
    """每个测试后移除全部 loguru handler 并恢复默认，避免污染其他测试。"""
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")


def _iter_api_v1_routes(app_obj):
    """递归展平 FastAPI 0.141+ 的 _IncludedRouter，产出 /api/v1 全部 APIRoute。"""
    seen: set[int] = set()

    def _walk(routes):
        for r in routes:
            if id(r) in seen:
                continue
            seen.add(id(r))
            if isinstance(r, APIRoute):
                if getattr(r, "path", "").startswith("/api/v1"):
                    yield r
            elif type(r).__name__ == "_IncludedRouter":
                orig = getattr(r, "original_router", None)
                if orig is not None:
                    yield from _walk(orig.routes)
            elif hasattr(r, "routes"):
                yield from _walk(r.routes)

    yield from _walk(app_obj.routes)


def _capture_records(level: str = "DEBUG"):
    records: list = []
    sid = logger.add(lambda m: records.append(m.record), level=level, format="{message}")
    return records, sid


def _find(records: list, level: str, event: str) -> dict:
    for rec in records:
        if rec["level"].name == level and rec["extra"].get("event") == event:
            return rec
    raise AssertionError(
        f"未捕获到 level={level} event={event}；levels={[r['level'].name for r in records]}"
    )


class TestApiV1Sweep:
    """结构层：全部 /api/v1 端点已挂 @instrument。"""

    def test_all_api_v1_endpoints_are_instrumented(self):
        routes = list(_iter_api_v1_routes(app))
        assert len(routes) >= 200, f"预期 ≥200 个 /api/v1 端点，实际 {len(routes)}"
        bare = []
        for r in routes:
            ep = r.endpoint
            if not hasattr(ep, "__wrapped__"):
                bare.append(f"{sorted(r.methods)} {r.path} -> {getattr(ep, '__name__', ep)!r}")
        assert not bare, "以下端点未挂 @instrument：\n" + "\n".join(bare)

    def test_status_endpoint_is_instrumented(self):
        """api_status 直接 @app.get 注册，也须被包裹。"""
        routes = [r for r in _iter_api_v1_routes(app) if r.path == "/api/v1/status"]
        assert routes, "未找到 /api/v1/status 路由"
        assert hasattr(routes[0].endpoint, "__wrapped__"), "api_status 未挂 @instrument"


class TestBehavioralDebugEntry:
    """可断言：零依赖端点触发 DEBUG 入口日志。"""

    @pytest.mark.asyncio
    async def test_status_emits_debug_entry_and_exit(self):
        from inkflow.api import api_status

        records, sid = _capture_records("DEBUG")
        try:
            result = await api_status()
        finally:
            logger.remove(sid)
        assert result["status"] == "operational"
        entry = _find(records, "DEBUG", "api_status")
        assert entry["extra"]["caller_type"] == "api"
        assert entry["extra"]["message_key"] == "log.call.api_status"
        assert "started" in entry["message"]
        exit_recs = [
            r
            for r in records
            if r["level"].name == "DEBUG"
            and r["extra"].get("event") == "api_status"
            and r["extra"].get("duration_ms") is not None
        ]
        assert exit_recs, "出口 DEBUG 记录应带 duration_ms"


class TestMessageKeyFamily:
    """两族 message_key 不冲突：装饰器 log.call.* / 显式 log.event.*。"""

    @pytest.mark.asyncio
    async def test_instrument_uses_log_call_family(self):
        from inkflow.api import api_status

        records, sid = _capture_records("DEBUG")
        try:
            await api_status()
        finally:
            logger.remove(sid)
        rec = _find(records, "DEBUG", "api_status")
        assert rec["extra"]["message_key"].startswith("log.call.")

    def test_semantic_family_distinct_from_call(self):
        # 结构键与语义键是不同前缀；log_structured 可发 log.event.*
        records, sid = _capture_records("INFO")
        try:
            log_structured(
                level="INFO",
                caller_type="api",
                caller_name="writing.create_chapter",
                event="create_chapter",
                message_key="log.event.create_chapter",
                message="created",
                correlation_id="c1",
            )
        finally:
            logger.remove(sid)
        rec = records[0]
        assert rec["extra"]["message_key"].startswith("log.event.")


class TestDebugDefaultOff:
    """DEBUG 默认关：config.debug False；DEBUG 不落 INFO sink。"""

    def test_config_debug_defaults_false(self):
        cfg = importlib.import_module("inkflow.core.config")
        assert cfg.config.debug is False

    def test_debug_log_not_captured_by_info_sink(self):
        records, sid = _capture_records("INFO")
        try:
            log_structured(
                level="DEBUG",
                caller_type="api",
                caller_name="x.endpoint",
                event="e",
                message_key="log.call.e",
                correlation_id="c1",
            )
        finally:
            logger.remove(sid)
        assert records == [], "DEBUG 默认关：INFO sink 不应捕获 DEBUG 记录"


class TestExpectedHttpErrorNotUncaught:
    """预期 HTTPException（4xx 业务流）≠ 未捕获异常：不得标 ERROR X_UNCAUGHT。

    spec §4 矩阵：API 行「校验失败(422)→WARN」「未捕获异常→ERROR」。
    契约：instrument 包装的函数抛 fastapi.HTTPException（带 status_code<500）
    → 记 WARN（error_code=f"E_HTTP_{status}"）后原样 re-raise；
    status_code>=500 → 仍 ERROR X_UNCAUGHT re-raise。
    实现判据用鸭子类型 getattr(exc, "status_code", None)（logging 不引 fastapi 依赖）。
    """

    @pytest.mark.asyncio
    async def test_4xx_warns_not_error_and_reraises(self):
        from fastapi import HTTPException

        from inkflow.logging import instrument

        @instrument(caller_type="api")
        async def get_missing():
            raise HTTPException(status_code=404, detail="not found")

        records, sid = _capture_records("WARNING")
        try:
            with pytest.raises(HTTPException):
                await get_missing()
        finally:
            logger.remove(sid)
        errs = [r for r in records if r["level"].name == "ERROR"]
        assert not errs, f"预期 4xx 不应产生 ERROR 记录：{[r['message'] for r in errs]}"
        warns = [r for r in records if r["level"].name == "WARNING"]
        assert warns, "4xx 应记 WARN（校验/资源缺失属自愈可恢复）"
        rec = warns[0]
        assert rec["extra"]["error_code"] == "E_HTTP_404"
        assert rec["extra"]["message_key"] == "log.call.get_missing"

    @pytest.mark.asyncio
    async def test_5xx_still_error_uncaught(self):
        from fastapi import HTTPException

        from inkflow.logging import instrument

        @instrument(caller_type="api")
        async def broken():
            raise HTTPException(status_code=503, detail="down")

        records, sid = _capture_records("ERROR")
        try:
            with pytest.raises(HTTPException):
                await broken()
        finally:
            logger.remove(sid)
        errs = [r for r in records if r["level"].name == "ERROR"]
        assert errs, "5xx 属服务端故障，仍应 ERROR"
        assert errs[0]["extra"]["error_code"] == "X_UNCAUGHT"


class TestAsyncGenSemantics:
    """@instrument async-generator 分支（spec §4.1 设计要点 2/3）。

    真 asyncgen（chat_stream/stream_events/stream 等）：入口 DEBUG started 即时；
    completed（duration_ms）**仅在全量消费后**发出；流中途异常记 WARN
    （error_code="X_STREAM_BROKEN"，流级失败非函数级崩溃）后原样 re-raise。
    当前 sync 路径实现下，created 即 completed、流中异常逃逸 wrapper（RED 预期失败）。
    """

    @pytest.mark.asyncio
    async def test_completed_only_after_full_iteration(self):
        from inkflow.logging import instrument

        @instrument(caller_type="llm")
        async def stream():
            yield "a"
            yield "b"

        records, sid = _capture_records("DEBUG")
        try:
            agen = stream()
            exits_at_create = [
                r
                for r in records
                if r["level"].name == "DEBUG"
                and r["extra"].get("event") == "stream"
                and r["extra"].get("duration_ms") is not None
            ]
            assert not exits_at_create, "生成器刚创建未消费：不应已发 completed（流未结束）"
            chunks = [c async for c in agen]
        finally:
            logger.remove(sid)
        assert chunks == ["a", "b"]
        _find(records, "DEBUG", "stream")  # started 存在
        exits = [
            r
            for r in records
            if r["level"].name == "DEBUG"
            and r["extra"].get("event") == "stream"
            and r["extra"].get("duration_ms") is not None
        ]
        assert exits, "全量消费后应发 completed（带 duration_ms）"

    @pytest.mark.asyncio
    async def test_midstream_error_logged_and_reraised(self):
        from inkflow.logging import instrument

        @instrument(caller_type="llm")
        async def flaky_stream():
            yield "ok"
            raise RuntimeError("stream broke")

        records, sid = _capture_records("WARNING")
        try:
            with pytest.raises(RuntimeError, match="stream broke"):
                async for _ in flaky_stream():
                    pass
        finally:
            logger.remove(sid)
        errs = [r for r in records if r["level"].name == "ERROR"]
        assert not errs, "流级失败不应标函数级 ERROR X_UNCAUGHT"
        warns = [r for r in records if r["level"].name == "WARNING"]
        assert warns, "流中途异常应被 instrument 记 WARN 后 re-raise"
        assert warns[0]["extra"]["error_code"] == "X_STREAM_BROKEN"


if __name__ == "__main__":
    unittest.main()
