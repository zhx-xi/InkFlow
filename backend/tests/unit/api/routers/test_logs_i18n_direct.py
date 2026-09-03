"""/logs、/i18n handler 同线程直接调用 — func-cov 门禁补偿（任务 #888-S1）。

背景
----
api 层测试走 TestClient → FastAPI 在独立线程/事件循环运行 handler；func_cov_plugin
的 ``sys.settrace`` 是 per-thread，无法记录该线程内的 handler 调用 → 经 HTTP 触达的
``query_logs`` / ``ingest_log`` / ``get_log_store`` / ``get_messages`` / ``store.query`` /
``store.append`` 被判为「未调用」，函数覆盖门禁把本批新函数标为新增未调用（既有 api
handler 都在 baseline_uncalled 里，新增的不在）。

本文件同线程直接调用这些 handler + store 方法（主线程 → 被 func-cov 记录）。

契约映射（源自 api/routers/logs.py + api/routers/i18n.py + logging/store.py）：
- ``logs.get_log_store()`` -> StructuredLogStore
- ``logs._parse_query_ts(s)`` -> datetime | None（ISO 解析 / None / 非法值）
- ``logs.query_logs(...)`` -> {"ok": True, "data": {items,total,offset,limit}}
- ``logs.ingest_log(LogRecordInput, store)`` -> {"ok": True} 且 store.append 被调用（params 脱敏）
- ``i18n.get_messages(lng)`` -> {"ok": True, "data": {msgid: template}}
- ``StructuredLogStore.append/query`` 直接往返（覆盖 _parse_ts / _normalize_ts /
  _text_eq / _record_matches_q）
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from inkflow.api.routers import i18n, logs
from inkflow.logging import StructuredLogRecord, StructuredLogStore


class TestGetLogStore:
    def test_get_log_store_returns_store(self, monkeypatch, tmp_path):
        import importlib

        cfg = importlib.import_module("inkflow.core.config")
        monkeypatch.setattr(cfg.config, "data_dir", Path(tmp_path), raising=False)
        assert isinstance(logs.get_log_store(), StructuredLogStore)


class TestParseQueryTs:
    def test_valid_iso_parsed_aware(self):
        dt = logs._parse_query_ts("2020-01-01T00:00:00Z")
        assert isinstance(dt, datetime)
        assert dt.tzinfo is not None

    def test_none_returns_none(self):
        assert logs._parse_query_ts(None) is None
        assert logs._parse_query_ts("") is None

    def test_invalid_returns_none(self):
        assert logs._parse_query_ts("not-a-date") is None


class TestQueryLogsDirect:
    @pytest.mark.asyncio
    async def test_query_logs_envelope_with_mock_store(self):
        store = MagicMock()
        store.query = MagicMock(return_value=([{"event": "a", "level": "INFO"}], 1))

        # 直接调用：from_/to 默认是 FastAPI Query(...) 对象，须显式 None
        result = await logs.query_logs(from_=None, to=None, store=store)
        assert result["ok"] is True
        assert result["data"]["total"] == 1
        assert result["data"]["items"][0]["event"] == "a"
        assert result["data"]["offset"] == 0
        assert result["data"]["limit"] == 50
        store.query.assert_called()

    @pytest.mark.asyncio
    async def test_query_logs_passes_filters(self):
        store = MagicMock()
        store.query = MagicMock(return_value=([], 0))
        await logs.query_logs(
            level="WARN", caller_type="api", project_id=123, from_=None, to=None,
            q="x", correlation_id="c", page=1, limit=10, store=store,
        )
        kwargs = store.query.call_args.kwargs
        assert kwargs["level"] == "WARN"
        assert kwargs["caller_type"] == "api"
        assert kwargs["project_id"] == 123
        assert kwargs["page"] == 1
        assert kwargs["limit"] == 10


class TestIngestLogDirect:
    @pytest.mark.asyncio
    async def test_ingest_log_masks_and_appends(self):
        store = MagicMock()
        store.append = MagicMock()
        payload = logs.LogRecordInput(
            level="INFO",
            caller_type="frontend",
            caller_name="WritingPage.createChapter",
            event="create_chapter",
            message_key="log.event.create_chapter",
            params={"title": "第一章", "api_key": "sk-abc"},
            correlation_id="corr-1",
        )
        result = await logs.ingest_log(payload, store)
        assert result == {"ok": True}
        store.append.assert_called_once()
        appended = store.append.call_args.args[0]
        assert appended.params["api_key"] == "****"  # 脱敏
        assert appended.params["title"] == "第一章"


class TestGetMessagesDirect:
    @pytest.mark.asyncio
    async def test_get_messages_en(self):
        result = await i18n.get_messages("en")
        assert result["ok"] is True
        assert result["data"]["log.event.create_chapter"] == "Created chapter: {title}"

    @pytest.mark.asyncio
    async def test_get_messages_default_zh(self):
        result = await i18n.get_messages()
        assert result["ok"] is True
        assert result["data"]["log.event.create_chapter"] == "创建章节：{title}"


class TestStoreRoundtrip:
    def test_append_query_roundtrip_covers_helpers(self, tmp_path):
        rec = StructuredLogRecord(
            level="INFO",
            logger="inkflow",
            caller_type="api",
            caller_name="writing.create_chapter",
            event="create_chapter",
            message_key="log.event.create_chapter",
            params={"title": "第一章"},
            correlation_id="corr-1",
        )
        store = StructuredLogStore(tmp_path)
        store.append(rec)
        # 带 level/caller_type/q/from/to 过滤 → 覆盖 _text_eq / _record_matches_q /
        # _normalize_ts / _parse_ts
        items, total = store.query(
            level="info",
            caller_type="api",
            q="create_chapter",
            from_ts=datetime(2020, 1, 1, tzinfo=UTC),
            to_ts=datetime(2100, 1, 1, tzinfo=UTC),
        )
        assert total == 1
        assert items[0]["event"] == "create_chapter"
        assert items[0]["params"]["title"] == "第一章"
