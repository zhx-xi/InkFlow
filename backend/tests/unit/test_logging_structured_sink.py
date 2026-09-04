"""#496 后端结构化 sink + correlation 上下文 — RED 契约测试（contract-496.md §1 B1 + §3 B4）。

契约来源
--------
.hermes/plans/contract-496.md §1（B1 结构化 sink：_structured_sink / _norm_sink_level /
WARN 归一 / filter 排除非 bind 记录 / DEBUG 默认关 / sink 故障静默 / handlers[0] 守护）
与 §3（B4：correlation.py contextvar + log_structured 解析链 显式参数 > contextvar > ''）。

目标模块
--------
backend/src/inkflow/core/log.py（setup_logging 追加第三类结构化 sink）+
backend/src/inkflow/logging/（correlation.py 与 __init__ 导出，B4）。

RED 阶段预期
------------
- 【R】落库链路用例 FAIL：core/log.py 尚无 _structured_sink → setup_logging 后
  log_structured 不落 StructuredLogStore（store 目录无记录）。
- 【R】B4 用例 FAIL：inkflow.logging 尚无 get/set_request_correlation_id → 函数体内
  import 抛 ImportError（符号缺失信号；镜像 f669 先例：禁模块级 import 防收集失败）。
- 【G】守护用例 PASS：handlers[0].levelno 20/10、缺省 correlation_id 空串、sink
  异常静默、非结构化/DEBUG-off 记录排除（RED 无 sink 时 vacuous pass，GREEN 后由
  sink level + filter 承接）。

隔离铁律（镜像 test_log.py / test_logging_schema.py 形态）
----------------------------------------------------------
1. config.data_dir + resolve_log_dir 一律 monkeypatch 到 tmp_path —— 绝不写真实
   backend/logs 或真实 data_dir（结构化目录 = config.data_dir/logs/structured）。
2. 每用例后 _restore_loguru：logger.remove() + 恢复默认 stderr（防污染其它测试）。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from loguru import logger

from inkflow.core import log as log_module
from inkflow.logging import StructuredLogStore, log_structured


@pytest.fixture(autouse=True)
def _restore_loguru():
    """每个测试后移除全部 loguru handler 并恢复默认 stderr，避免污染其他测试。"""
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")


def _patch_log_paths(
    monkeypatch, tmp_path, *, debug: bool = False, log_level: str = "INFO"
) -> None:
    """config.data_dir=tmp_path、resolve_log_dir=tmp_path/logs（结构化目录=tmp_path/logs/structured）。"""
    cfg_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg_mod.config, "data_dir", tmp_path)
    monkeypatch.setattr(cfg_mod.config, "debug", debug)
    monkeypatch.setattr(cfg_mod.config, "log_level", log_level)
    monkeypatch.setattr(log_module, "resolve_log_dir", lambda: tmp_path / "logs")


def _stored_records(tmp_path: Path) -> list[dict]:
    """StructuredLogStore 读回全部落库记录（目录不存在/无记录时返回空列表）。"""
    items, _total = StructuredLogStore(tmp_path / "logs" / "structured").query()
    return items


def _find_record(records: list[dict], caller_name: str) -> dict | None:
    """按 caller_name 找落库记录。"""
    return next((r for r in records if r.get("caller_name") == caller_name), None)


class TestStructuredSink:
    """B1 结构化 sink（contract-496.md §1）：setup_logging 追加的第三类 sink 落库契约。"""

    def test_info_record_lands_in_store_with_all_fields(self, monkeypatch, tmp_path):
        """【R】log_structured INFO → store 出现该记录，核心字段全部正确。"""
        _patch_log_paths(monkeypatch, tmp_path, debug=False, log_level="INFO")
        log_module.setup_logging()

        log_structured(
            level="INFO",
            caller_type="api",
            caller_name="x.y",
            event="e",
            message_key="log.event.x",
            params={"a": 1},
            correlation_id="c1",
        )

        rec = _find_record(_stored_records(tmp_path), "x.y")
        assert rec is not None, "log_structured INFO 记录未落入结构化 store（缺 _structured_sink）"
        assert rec["level"] == "INFO"
        assert rec["caller_type"] == "api"
        assert rec["event"] == "e"
        assert rec["message_key"] == "log.event.x"
        assert rec["params"] == {"a": 1}
        assert rec["correlation_id"] == "c1"
        assert rec["timestamp"], "sink 重建 timestamp 应为非空 JSON ISO 串"
        assert rec["logger"], "sink 应落 logger=record[name] 非空"

    def test_warning_level_normalized_to_warn(self, monkeypatch, tmp_path):
        """【R】loguru WARNING → 存储 'WARN'（_norm_sink_level 归一，与 store 查询口径对齐）。"""
        _patch_log_paths(monkeypatch, tmp_path, debug=False, log_level="INFO")
        log_module.setup_logging()

        log_structured(
            level="WARN",
            caller_type="agent",
            caller_name="warn.probe",
            event="w",
            message_key="log.event.w",
            params={},
            correlation_id="c-w",
        )

        rec = _find_record(_stored_records(tmp_path), "warn.probe")
        assert rec is not None, "WARN 记录未落入结构化 store（缺 _structured_sink）"
        assert rec["level"] == "WARN", "loguru WARNING 应归一为存储 'WARN'"

    def test_debug_default_off_filters_debug_keeps_info(self, monkeypatch, tmp_path):
        """【R】debug=False → INFO 落库、DEBUG 被 sink level 拦截（DEBUG 默认关）。"""
        _patch_log_paths(monkeypatch, tmp_path, debug=False, log_level="INFO")
        log_module.setup_logging()

        log_structured(
            level="INFO",
            caller_type="api",
            caller_name="dbg.off.info",
            event="i",
            message_key="log.event.i",
            params={},
            correlation_id="c-i",
        )
        log_structured(
            level="DEBUG",
            caller_type="api",
            caller_name="dbg.off.debug",
            event="d",
            message_key="log.event.d",
            params={},
            correlation_id="c-d",
        )

        records = _stored_records(tmp_path)
        assert _find_record(records, "dbg.off.info") is not None, "INFO 记录应落 store"
        assert _find_record(records, "dbg.off.debug") is None, "debug=False 时 DEBUG 不应落 store"

    def test_debug_on_stores_debug_records(self, monkeypatch, tmp_path):
        """【R】debug=True → sink level DEBUG → DEBUG 记录落库（level 原文 'DEBUG'）。"""
        _patch_log_paths(monkeypatch, tmp_path, debug=True, log_level="INFO")
        log_module.setup_logging()

        log_structured(
            level="DEBUG",
            caller_type="cli",
            caller_name="dbg.on.probe",
            event="d",
            message_key="log.event.d",
            params={},
            correlation_id="c-d",
        )

        rec = _find_record(_stored_records(tmp_path), "dbg.on.probe")
        assert rec is not None, "debug=True 时 DEBUG 记录应落入 store"
        assert rec["level"] == "DEBUG"

    def test_bare_loguru_record_excluded_from_store(self, monkeypatch, tmp_path):
        """【R】裸 logger.info（extra 无 caller_type）被 filter 排除；结构化记录仍落库。"""
        _patch_log_paths(monkeypatch, tmp_path, debug=False, log_level="INFO")
        log_module.setup_logging()

        logger.info("plain unstructured message")
        log_structured(
            level="INFO",
            caller_type="tool",
            caller_name="structured.only",
            event="s",
            message_key="log.event.s",
            params={},
            correlation_id="c-s",
        )

        records = _stored_records(tmp_path)
        assert len(records) == 1, f"仅结构化记录应落库，实际 {len(records)} 条"
        assert records[0]["caller_name"] == "structured.only"

    def test_handlers_first_stderr_levelno_20_when_debug_off(self, monkeypatch, tmp_path):
        """【G】守护（mirror test_logging_schema.py:248）：debug=False → levelno==20。"""
        _patch_log_paths(monkeypatch, tmp_path, debug=False, log_level="INFO")
        log_module.setup_logging()

        handlers = list(logger._core.handlers.values())
        assert handlers[0].levelno == 20  # loguru INFO = 20

    def test_handlers_first_stderr_levelno_10_when_debug_on(self, monkeypatch, tmp_path):
        """【G】守护（mirror test_logging_schema.py:260）：debug=True → handlers[0].levelno==10。"""
        _patch_log_paths(monkeypatch, tmp_path, debug=True, log_level="INFO")
        log_module.setup_logging()

        handlers = list(logger._core.handlers.values())
        assert handlers[0].levelno == 10  # loguru DEBUG = 10

    def test_structured_sink_exception_silently_swallowed(self, monkeypatch, tmp_path):
        """【G】sink 故障静默：append 抛 OSError 时 log_structured 不上抛（try/except pass）。

        RED：core/log.py 尚无 StructuredLogStore 引用 → raising=False 跳过 patch，无
        sink 自然不抛（vacuous pass）；GREEN：patch 命中模块引用 → sink 内异常被吞。
        """
        _patch_log_paths(monkeypatch, tmp_path, debug=False, log_level="INFO")

        class _BoomStore:
            def __init__(self, directory):
                self.directory = directory

            def append(self, record):
                raise OSError("simulated disk failure")

        monkeypatch.setattr(log_module, "StructuredLogStore", _BoomStore, raising=False)
        log_module.setup_logging()

        # 不应抛任何异常（含 OSError）
        log_structured(
            level="INFO",
            caller_type="api",
            caller_name="boom.probe",
            event="b",
            message_key="log.event.b",
            params={},
            correlation_id="c-b",
        )


class TestCorrelationContextVar:
    """B4 contextvar（contract-496.md §3）：解析链 显式参数 > contextvar > ''。"""

    def test_default_empty_string_when_contextvar_unset(self):
        """【G】零回归守护：无 contextvar（默认 ''）→ correlation_id=None 缺省落空串。

        现状行为（schema.py 现缺省 ''）逐字保持；GREEN 改走 get_request_correlation_id()
        后 contextvar 默认仍 '' → 断言不破。
        """
        records = []
        sid = logger.add(lambda m: records.append(m.record), level="INFO", format="{message}")
        try:
            log_structured(
                level="INFO",
                caller_type="api",
                caller_name="ctx.unset",
                event="e",
                message_key="log.event.x",
                params={},
                correlation_id=None,
            )
        finally:
            logger.remove(sid)

        assert len(records) == 1
        assert records[0]["extra"]["correlation_id"] == ""

    def test_set_contextvar_value_stored_when_correlation_id_none(self, monkeypatch, tmp_path):
        """【R】set('ctx-c-42') → log_structured(correlation_id=None) 落库 == 'ctx-c-42'。

        RED：符号不存在 → 函数体内 import 抛 ImportError（必 FAIL，禁模块级 import
        防整文件收集失败）。
        """
        from inkflow.logging import (
            get_request_correlation_id,
            reset_request_correlation_id,
            set_request_correlation_id,
        )

        _patch_log_paths(monkeypatch, tmp_path, debug=False, log_level="INFO")
        token = set_request_correlation_id("ctx-c-42")
        try:
            assert get_request_correlation_id() == "ctx-c-42"
            log_module.setup_logging()
            log_structured(
                level="INFO",
                caller_type="api",
                caller_name="ctx.used",
                event="e",
                message_key="log.event.x",
                params={},
                correlation_id=None,
            )
        finally:
            reset_request_correlation_id(token)  # 防 contextvar 泄漏污染其它用例

        rec = _find_record(_stored_records(tmp_path), "ctx.used")
        assert rec is not None, "contextvar 解析链记录未落入结构化 store"
        assert rec["correlation_id"] == "ctx-c-42"

    def test_explicit_correlation_id_wins_over_contextvar(self, monkeypatch, tmp_path):
        """【R】显式参数优先于 contextvar：set('ctx-should-lose') + 显式 'explicit-1'
        → 落库 'explicit-1'。

        RED：符号不存在 → 函数体内 import 抛 ImportError（必 FAIL）。
        """
        from inkflow.logging import reset_request_correlation_id, set_request_correlation_id

        _patch_log_paths(monkeypatch, tmp_path, debug=False, log_level="INFO")
        token = set_request_correlation_id("ctx-should-lose")
        try:
            log_module.setup_logging()
            log_structured(
                level="INFO",
                caller_type="api",
                caller_name="ctx.explicit",
                event="e",
                message_key="log.event.x",
                params={},
                correlation_id="explicit-1",
            )
        finally:
            reset_request_correlation_id(token)  # 防 contextvar 泄漏污染其它用例

        rec = _find_record(_stored_records(tmp_path), "ctx.explicit")
        assert rec is not None, "显式 correlation_id 记录未落入结构化 store"
        assert rec["correlation_id"] == "explicit-1"
