"""F57 /api/v1/i18n/messages 端点 — RED 契约测试（任务 #888-S1 / spec §3.1 / §12 M2）。

契约来源
--------
specs/f57-logging-i18n/spec.md §3.1（GET /api/v1/i18n/messages?lng=）、§3.2（F7 信封）、
§5（resolve_locale per-call 准实时 + 缺键回退 zh）。

目标模块：`backend/src/inkflow/api/routers/i18n.py`（GET /api/v1/i18n/messages）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. GET /api/v1/i18n/messages?lng=<locale>
   - lng 归一化（resolve_locale）：zh-CN→zh / en-US→en / fr→zh（不支持回退 zh）。
   - 返回 F7 信封 {"ok": true, "data": {msgid: template}}（messages 域本地化目录，
     value 为未插值模板字符串）。
   - lng 缺省 → resolve_locale(None)（config.lang/OS/zh 链，默认 zh）。
   - data 含初始 ``log.event.*`` / ``api.error.*`` 键；zh/en 各返回对应语言文本。

RED 阶段预期：api/routers/i18n.py 未创建 + i18n 包未创建 → import 失败（门禁 M2）。
GREEN 阶段：实现 i18n router + resolver + messages/{zh,en}.json 后全绿。

测试方式：纯 HTTP（TestClient）。token 中间件在 env 未设置时直通（同既有测试基线）。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    """TestClient（i18n 读包内 messages 目录，不触 data_dir；隔离仅防 DB 污染）。"""
    cfg = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg.config, "data_dir", Path(tmp_path), raising=False)
    return TestClient(app)


class TestI18nMessages:
    def test_get_messages_envelope(self, client):
        resp = client.get("/api/v1/i18n/messages", params={"lng": "zh"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "data" in body
        assert isinstance(body["data"], dict)

    def test_get_messages_zh_text(self, client):
        data = client.get("/api/v1/i18n/messages", params={"lng": "zh"}).json()["data"]
        assert data["log.event.create_chapter"] == "创建章节：{title}"

    def test_get_messages_en_text(self, client):
        data = client.get("/api/v1/i18n/messages", params={"lng": "en"}).json()["data"]
        assert data["log.event.create_chapter"] == "Created chapter: {title}"

    def test_get_messages_default_locale_zh(self, client):
        data = client.get("/api/v1/i18n/messages").json()["data"]
        assert data["log.event.create_chapter"] == "创建章节：{title}"

    def test_get_messages_unsupported_locale_falls_back_zh(self, client):
        data = client.get("/api/v1/i18n/messages", params={"lng": "fr"}).json()["data"]
        assert data["log.event.create_chapter"] == "创建章节：{title}"

    def test_get_messages_contains_core_keys(self, client):
        data = client.get("/api/v1/i18n/messages", params={"lng": "en"}).json()["data"]
        for key in (
            "log.event.create_chapter",
            "api.error.project_not_found",
            "api.error.validation_failed",
        ):
            assert key in data, f"en 消息目录缺少核心键 {key}"
