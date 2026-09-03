"""F57 日志结构化 schema — RED 契约测试（任务 #888-S1 / spec §2.2 / §12 M1 / §4 DEBUG 默认关）。

契约来源
--------
specs/f57-logging-i18n/spec.md §2.2（日志结构字段 + caller_type 枚举 + 必填/可选）、
§4（DEBUG 默认关）、§12 M1（结构化 schema + 脱敏契约）。

目标模块：`backend/src/inkflow/logging/`（mask_fields / bind_correlation /
StructuredLogRecord / log_structured，基于 loguru）+ `core/log.py`（setup_logging 切级）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. mask_fields(params: dict, *, mask: str = "****", sensitive_keys: set[str] | None = None) -> dict
   - 返回新 dict（不改原输入）。
   - 敏感键（key.lower() 含 api_key/apikey/token/secret/password/authorization/credential/
     bearer/auth/key）的值替换为 mask。
   - 递归处理嵌套 dict / list（深层键也脱敏）。

2. bind_correlation(correlation_id=None, *, trace_id=None, span_id=None) -> dict
   - 返回 {correlation_id, trace_id, span_id} 子集（None 值键不出现）。

3. StructuredLogRecord（pydantic，spec §2.2 字段）
   - 必填：level / logger / caller_type / caller_name / event / message_key / correlation_id。
   - 可选：params（默认 {}）/ trace_id / span_id / project_id / entity_id / duration_ms /
     error_code / stack；timestamp 默认当前 UTC aware datetime；params 默认 {}。
   - caller_type 必须是 Literal["api","agent","llm","tool","cli","mcp","frontend"]；
     非法值 → pydantic.ValidationError。

4. log_structured(...)（发布到 loguru 的入口）
   - 构建 StructuredLogRecord → mask params → logger.bind(extra).log(level, message)。
   - extra 含 caller_type/caller_name/event/message_key/params(已脱敏)/correlation_id 等。

5. setup_logging(): debug=False 默认 → console/stderr sink levelno == 20（INFO，DEBUG 关、
   INFO 可见）；config.debug=True → levelno == 10（DEBUG 开）。

RED 阶段预期：`inkflow.logging` 包未创建 → import 即失败（整文件收集失败，门禁 M1）。
GREEN 阶段：实现 logging/（schema+instrument 等）+ core/log.py 切级后全绿。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import importlib
import sys

import pytest
from loguru import logger
from pydantic import ValidationError

from inkflow.logging import (
    StructuredLogRecord,
    bind_correlation,
    log_structured,
    mask_fields,
)


@pytest.fixture(autouse=True)
def _restore_loguru():
    """每个测试后移除全部 loguru handler 并恢复默认 stderr，避免污染其他测试。"""
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")


def _capture_records(level: str = "DEBUG"):
    """添加 loguru sink 收集 record dict，返回 (records, sink_id)。"""
    records: list = []
    sid = logger.add(lambda m: records.append(m.record), level=level, format="{message}")
    return records, sid


# ── mask_fields：脱敏 ──


class TestMaskFields:
    def test_masks_sensitive_keys(self):
        result = mask_fields(
            {"api_key": "sk-abc", "token": "t-xyz", "password": "p", "title": "第一章"}
        )
        assert result["api_key"] == "****"
        assert result["token"] == "****"
        assert result["password"] == "****"
        assert result["title"] == "第一章"

    def test_masks_secret_key_variant_and_authorization(self):
        result = mask_fields({"secret_key": "s", "Authorization": "Bearer xyz"})
        assert result["secret_key"] == "****"
        assert result["Authorization"] == "****"

    def test_recurses_nested_dict(self):
        result = mask_fields({"project": {"api_key": "inner", "name": "n"}})
        assert result["project"]["api_key"] == "****"
        assert result["project"]["name"] == "n"

    def test_recurses_nested_list(self):
        result = mask_fields([{"api_key": "a"}, {"token": "b", "title": "t"}])
        assert result[0]["api_key"] == "****"
        assert result[1]["token"] == "****"
        assert result[1]["title"] == "t"

    def test_does_not_mutate_input(self):
        params = {"api_key": "sk-x", "title": "t"}
        mask_fields(params)
        assert params["api_key"] == "sk-x"
        assert params["title"] == "t"

    def test_custom_mask(self):
        assert mask_fields({"token": "x"}, mask="<mask>") == {"token": "<mask>"}

    def test_custom_sensitive_keys(self):
        result = mask_fields({"foo": "1", "title": "t"}, sensitive_keys={"foo"})
        assert result["foo"] == "****"
        assert result["title"] == "t"


# ── bind_correlation ──


class TestBindCorrelation:
    def test_only_correlation_id(self):
        assert bind_correlation("abc") == {"correlation_id": "abc"}

    def test_correlation_and_optional(self):
        assert bind_correlation("abc", trace_id="t1", span_id="s1") == {
            "correlation_id": "abc",
            "trace_id": "t1",
            "span_id": "s1",
        }

    def test_none_values_omitted(self):
        assert bind_correlation(None, trace_id="t1") == {"trace_id": "t1"}


# ── StructuredLogRecord：schema 校验 ──


class TestStructuredLogRecord:
    def _valid_kwargs(self) -> dict:
        return {
            "level": "INFO",
            "logger": "inkflow.api.routers.logs",
            "caller_type": "api",
            "caller_name": "writing.create_chapter",
            "event": "create_chapter",
            "message_key": "log.event.create_chapter",
            "correlation_id": "c1",
        }

    def test_accepts_full_fields(self):
        rec = StructuredLogRecord(
            **self._valid_kwargs(),
            params={"title": "第一章"},
            project_id=123,
            error_code="E_VALIDATION",
            stack="traceback...",
        )
        assert rec.caller_type == "api"
        assert rec.params == {"title": "第一章"}
        assert rec.project_id == 123
        assert rec.error_code == "E_VALIDATION"
        assert rec.stack == "traceback..."

    def test_rejects_invalid_caller_type(self):
        with pytest.raises(ValidationError):
            StructuredLogRecord(**{**self._valid_kwargs(), "caller_type": "bogus"})

    def test_requires_correlation_id(self):
        kwargs = self._valid_kwargs()
        kwargs.pop("correlation_id")
        with pytest.raises(ValidationError):
            StructuredLogRecord(**kwargs)

    def test_default_params_and_timestamp(self):
        rec = StructuredLogRecord(**self._valid_kwargs())
        assert rec.params == {}
        assert rec.timestamp.tzinfo is not None

    def test_dump_serializable(self):
        rec = StructuredLogRecord(**self._valid_kwargs())
        d = rec.model_dump(mode="json")
        assert d["timestamp"] is not None
        assert d["caller_type"] == "api"
        assert d["params"] == {}


# ── log_structured：结构化发布 ──


class TestLogStructured:
    def test_emits_bound_extra_and_masks_params(self):
        records, sid = _capture_records("INFO")
        try:
            log_structured(
                level="INFO",
                caller_type="api",
                caller_name="writing.create_chapter",
                event="create_chapter",
                message_key="log.event.create_chapter",
                message="created",
                params={"title": "第一章", "api_key": "sk-abc"},
                correlation_id="corr-1",
            )
        finally:
            logger.remove(sid)
        assert len(records) == 1
        rec = records[0]
        assert rec["level"].name == "INFO"
        assert rec["extra"]["caller_type"] == "api"
        assert rec["extra"]["message_key"] == "log.event.create_chapter"
        assert rec["extra"]["params"]["api_key"] == "****"
        assert rec["extra"]["params"]["title"] == "第一章"
        assert rec["extra"]["correlation_id"] == "corr-1"
        assert rec["extra"]["event"] == "create_chapter"

    def test_rejects_invalid_caller_type(self):
        with pytest.raises(ValidationError):
            log_structured(
                level="INFO",
                caller_type="bogus",
                caller_name="x",
                event="e",
                message_key="m",
                message="m",
                correlation_id="c",
            )


# ── setup_logging：DEBUG 默认关 / INFO 可见 ──


class TestSetupLoggingLevel:
    def _config_mod(self):
        return importlib.import_module("inkflow.core.config")

    def test_debug_default_off_keeps_info_level(self, monkeypatch, tmp_path):
        cfg = self._config_mod()
        monkeypatch.setattr(cfg.config, "debug", False, raising=False)
        monkeypatch.setattr(cfg.config, "log_level", "INFO", raising=False)
        import inkflow.core.log as log_mod

        monkeypatch.setattr(log_mod, "resolve_log_dir", lambda: tmp_path / "logs")

        log_mod.setup_logging()
        handlers = list(logger._core.handlers.values())
        assert handlers[0].levelno == 20  # loguru INFO = 20（DEBUG=10 被关）

    def test_debug_on_lowers_to_debug_level(self, monkeypatch, tmp_path):
        cfg = self._config_mod()
        monkeypatch.setattr(cfg.config, "debug", True, raising=False)
        monkeypatch.setattr(cfg.config, "log_level", "INFO", raising=False)
        import inkflow.core.log as log_mod

        monkeypatch.setattr(log_mod, "resolve_log_dir", lambda: tmp_path / "logs")

        log_mod.setup_logging()
        handlers = list(logger._core.handlers.values())
        assert handlers[0].levelno == 10  # loguru DEBUG = 10
