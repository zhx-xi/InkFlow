"""F57 /api/v1/logs 端点 — RED 契约测试（任务 #888-S1 / spec §3 / §12 M2）。

契约来源
--------
specs/f57-logging-i18n/spec.md §3.1（GET/POST /logs）、§3.2（F7 信封 {ok,data}）、
§3.3（本地鉴权 token 401 + 参数脱敏）。

目标模块：`backend/src/inkflow/api/routers/logs.py`（GET/POST /api/v1/logs）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. POST /api/v1/logs（前端桥接上报）
   - body: {level, caller_type, caller_name, event, message_key, params, correlation_id,
     project_id?, entity_id?, duration_ms?, error_code?}。
   - caller_type 非法 → 422（pydantic 校验）。
   - params 中的敏感键（api_key/token/secret/password 等）经 mask_fields 脱敏后落盘。
   - 成功 → 200 + {"ok": true}（F7 信封）。

2. GET /api/v1/logs（日志页查询）
   - Query: level / caller_type / project_id / from / to / q / correlation_id / page / limit。
   - from/to 为 ISO8601 时间过滤；q 为关键字过滤（message/event/params/caller_name）；
     page 从 0 起，默认 limit=50。
   - 响应 F7 信封：{"ok": true, "data": {"items": [...], "total": N,
     "offset": page*limit, "limit": limit}}。

3. 安全（spec §3.3）：INKFLOW_SERVER_TOKEN 已设时，GET/POST /logs 缺 token → 401
   {"detail": "Unauthorized"}（同 ADR-021 中间件）。

4. 存储：结构化日志经 `logging.StructuredLogStore` 读写 `{config.data_dir}/logs/structured/`
   JSON 行文件（POST 写、GET 读同一目录 → 往返一致）。

RED 阶段预期：api/routers/logs.py 未创建 + logging 包未创建 → import 失败（门禁 M2）。
GREEN 阶段：实现 logs router + logging 包后全绿。

测试方式：纯 HTTP（TestClient），store 目录经 monkeypatch config.data_dir 隔离到 tmp_path。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app

TOKEN_HEADER = "X-InkFlow-Token"
ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
TEST_TOKEN = "test-token-f57"

_VALID_BODY = {
    "level": "INFO",
    "caller_type": "frontend",
    "caller_name": "WritingPage.createChapter",
    "event": "create_chapter",
    "message_key": "log.event.create_chapter",
    "params": {"title": "第一章"},
    "correlation_id": "corr-1",
    "project_id": 123,
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    """TestClient + 隔离 store 目录（config.data_dir → tmp_path，/logs 读写隔离）。"""
    cfg = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg.config, "data_dir", Path(tmp_path), raising=False)
    return TestClient(app)


@pytest.fixture
def set_token_env(monkeypatch):
    monkeypatch.setenv(ENV_TOKEN, TEST_TOKEN)
    return TEST_TOKEN


# ── POST：桥接上报 ──


class TestPostLogs:
    def test_post_valid_returns_ok(self, client):
        resp = client.post("/api/v1/logs", json=_VALID_BODY)
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_post_invalid_caller_type_422(self, client):
        body = {**_VALID_BODY, "caller_type": "bogus"}
        resp = client.post("/api/v1/logs", json=body)
        assert resp.status_code == 422

    def test_post_missing_caller_type_422(self, client):
        body = {k: v for k, v in _VALID_BODY.items() if k != "caller_type"}
        resp = client.post("/api/v1/logs", json=body)
        assert resp.status_code == 422

    def test_post_masks_sensitive_params(self, client):
        body = {**_VALID_BODY, "params": {"api_key": "sk-abc", "title": "第一章"}}
        assert client.post("/api/v1/logs", json=body).status_code == 200
        # 回读：api_key 已脱敏，title 保留
        data = client.get("/api/v1/logs").json()["data"]
        assert data["total"] >= 1
        item = data["items"][0]
        assert item["params"]["api_key"] == "****"
        assert item["params"]["title"] == "第一章"


# ── GET：查询 + 过滤 + 分页 ──


class TestGetLogs:
    def _seed(self, client, *, level="INFO", caller_type="frontend", event="create_chapter"):
        body = {**_VALID_BODY, "level": level, "caller_type": caller_type, "event": event}
        assert client.post("/api/v1/logs", json=body).status_code == 200

    def test_get_returns_envelope(self, client):
        self._seed(client)
        body = client.get("/api/v1/logs").json()
        assert body["ok"] is True
        assert "data" in body
        assert {"items", "total", "offset", "limit"} <= set(body["data"])
        assert isinstance(body["data"]["items"], list)
        assert body["data"]["total"] >= 1

    def test_get_roundtrip_returns_posted_item(self, client):
        self._seed(client)
        data = client.get("/api/v1/logs").json()["data"]
        assert data["total"] >= 1
        item = data["items"][0]
        assert item["caller_type"] == "frontend"
        assert item["message_key"] == "log.event.create_chapter"
        assert item["correlation_id"] == "corr-1"

    def test_get_filter_by_level(self, client):
        self._seed(client, level="INFO", event="create_chapter")
        self._seed(client, level="WARN", event="warn_thing")
        data = client.get("/api/v1/logs", params={"level": "WARN"}).json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["level"] == "WARN"

    def test_get_filter_by_caller_type(self, client):
        self._seed(client, caller_type="frontend", event="a")
        self._seed(client, caller_type="agent", event="b")
        data = client.get("/api/v1/logs", params={"caller_type": "agent"}).json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["caller_type"] == "agent"

    def test_get_filter_by_project_id(self, client):
        self._seed(client, event="a")
        data = client.get("/api/v1/logs", params={"project_id": 123}).json()["data"]
        assert data["total"] >= 1
        bad = client.get("/api/v1/logs", params={"project_id": 999999}).json()["data"]
        assert bad["total"] == 0

    def test_get_filter_by_correlation_id(self, client):
        self._seed(client, event="a")
        data = client.get("/api/v1/logs", params={"correlation_id": "corr-1"}).json()["data"]
        assert data["total"] >= 1
        bad = client.get("/api/v1/logs", params={"correlation_id": "no-such"}).json()["data"]
        assert bad["total"] == 0

    def test_get_keyword_search(self, client):
        self._seed(client, event="create_chapter")
        data = client.get("/api/v1/logs", params={"q": "create_chapter"}).json()["data"]
        assert data["total"] >= 1
        none = client.get("/api/v1/logs", params={"q": "no-such-token"}).json()["data"]
        assert none["total"] == 0

    def test_get_from_to_filter(self, client):
        self._seed(client, event="a")
        within = client.get(
            "/api/v1/logs",
            params={"from": "2000-01-01T00:00:00Z", "to": "2100-01-01T00:00:00Z"},
        ).json()["data"]
        assert within["total"] >= 1
        future = client.get(
            "/api/v1/logs", params={"from": "2100-01-01T00:00:00Z"}
        ).json()["data"]
        assert future["total"] == 0

    def test_get_pagination(self, client):
        self._seed(client, event="a")
        self._seed(client, event="b")
        self._seed(client, event="c")
        page0 = client.get("/api/v1/logs", params={"page": 0, "limit": 1}).json()["data"]
        assert page0["offset"] == 0
        assert len(page0["items"]) == 1
        assert page0["total"] >= 3
        page1 = client.get("/api/v1/logs", params={"page": 1, "limit": 1}).json()["data"]
        assert page1["offset"] == 1
        assert len(page1["items"]) == 1


# ── 安全：token 401 ──


class TestLogsAuth:
    def test_get_without_token_401(self, client, set_token_env):
        resp = client.get("/api/v1/logs")
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}

    def test_post_without_token_401(self, client, set_token_env):
        resp = client.post("/api/v1/logs", json=_VALID_BODY)
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}

    def test_get_with_correct_token_200(self, client, set_token_env):
        resp = client.get("/api/v1/logs", headers={TOKEN_HEADER: TEST_TOKEN})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
