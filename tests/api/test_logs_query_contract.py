"""#496 统一日志页 — GET /api/v1/logs 查询契约 RED 测试（B2 多值 / B3 UUID / B4 头沿用）。

契约来源
--------
- specs/f496-log-page/spec.md §2.2：
  B2 level/caller_type 逗号分隔多值过滤（大小写不敏感，单值向后兼容）；
  B3 project_id 查询参数接受 UUID 串（纯数字→int / 合法 UUID→uuid.UUID(s).int / 非法→422）；
  B4 X-Correlation-Id 请求头 → 该请求内 log_structured/@instrument 埋点 correlation_id 沿用。
- .hermes/plans/contract-496.md §1-3（签名/文案/行为固化）与 §8（本文件 = 新建，RED 契约）。
- 目标模块：backend/src/inkflow/logging/store.py（B2）、api/routers/logs.py（B3）、
  api/middleware/correlation.py + logging/correlation.py（B4，待创建）。

RED 阶段预期（baseline = origin/main@75e26a2，B2/B3/B4 均未实现）
----------------------------------------------------------------
- 【R】用例全 FAIL（修复锚）：
  B2 多值：store.query 仍为单值 _text_eq → "INFO,WARN,ERROR" 整串等值比较永不命中 → 空集；
  B3 UUID：project_id 仍为 int 参数 → UUID 串 / 非数字被 FastAPI 参数校验拦成 422
    （非契约的 200 空集 / 422 契约文案）；
  B4 头沿用：无 CorrelationIdMiddleware + 无 B1 structured sink → @instrument 埋点
    不入 store 或 correlation 落空串 → correlation_id 回查为空。
- 【G】用例全 PASS（回归守护，B2/B3 零回归红线 contract-496 §9.1）：
  单值 level=WARN / caller_type=agent 过滤、project_id int 串路径（'123' → 123）。

形态镜像 tests/api/test_logs_api.py：TestClient + monkeypatch config.data_dir → tmp_path
（store 目录 per-test 隔离）；造数走 POST /api/v1/logs 真实契约面。
"""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from inkflow.api.app import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    """TestClient + 隔离 store 目录（config.data_dir → tmp_path，/logs 读写隔离）。"""
    cfg = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg.config, "data_dir", Path(tmp_path), raising=False)
    return TestClient(app)


@pytest.fixture
def sink_client(client, monkeypatch, tmp_path):
    """client + 显式注册结构化 sink（父侧契约补全）。

    TestClient 不进 with 块 → lifespan 不执行 → setup_logging 不会自动跑。
    B4 回查 @instrument 埋点的前提是本进程已注册结构化 sink——本 fixture 显式
    调用 setup_logging（resolve_log_dir 一并 patch 到 tmp，防文件 sink 写真实目录），
    用例后恢复 loguru（镜像 backend/tests/unit/test_logging_structured_sink.py 形态）。
    """
    log_mod = importlib.import_module("inkflow.core.log")
    monkeypatch.setattr(log_mod, "resolve_log_dir", lambda: tmp_path / "logs")
    log_mod.setup_logging()
    try:
        yield client
    finally:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")


def _seed(
    client,
    *,
    level: str = "INFO",
    caller_type: str = "frontend",
    event: str,
    marker: str | None = None,
    project_id: int | None = None,
) -> None:
    """经 POST /api/v1/logs 写入一条记录（造数走真实契约面）；写失败立即报错。"""
    body: dict = {
        "level": level,
        "caller_type": caller_type,
        "caller_name": "QueryContract.seed",
        "event": event,
        "message_key": "log.event.create_chapter",
        "params": {"marker": marker} if marker is not None else {},
        "correlation_id": "",
    }
    if project_id is not None:
        body["project_id"] = project_id
    resp = client.post("/api/v1/logs", json=body)
    assert resp.status_code == 200, resp.text


class TestSingleValueRegressionGuards:
    """既有单值行为回归守护（contract-496 §2 / §9.1 红线 1），【G】。

    镜像 tests/api/test_logs_api.py 既有断言形态；B2 _csv_match / B3 str 化改造后
    这些路径必须逐字保持（q=<marker> 仅排除 @instrument 噪音行，保证 total 精确）。
    """

    def test_g_b2_single_value_level_warn(self, client):
        """【G】level=WARN 单值查询只命中 WARN 记录。"""
        _seed(client, level="INFO", event="evt_info")
        _seed(client, level="WARN", event="evt_warn")
        data = client.get("/api/v1/logs", params={"level": "WARN"}).json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["level"] == "WARN"

    def test_g_b2_single_value_caller_type_agent(self, client):
        """【G】caller_type=agent 单值查询只命中 agent 记录。"""
        _seed(client, caller_type="frontend", event="evt_fe")
        _seed(client, caller_type="agent", event="evt_agent")
        data = client.get("/api/v1/logs", params={"caller_type": "agent"}).json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["caller_type"] == "agent"

    def test_g_b3_project_id_int_string_hits(self, client):
        """【G】project_id int 串 '123' 命中 int 落库记录（B3 参数 str 化后仍须命中，§9.1）。"""
        _seed(client, event="evt_p123", project_id=123)
        hit = client.get("/api/v1/logs", params={"project_id": "123"}).json()["data"]
        assert hit["total"] == 1
        assert hit["items"][0]["project_id"] == 123
        miss = client.get("/api/v1/logs", params={"project_id": "999999"}).json()["data"]
        assert miss["total"] == 0


class TestB2MultiValueFilter:
    """B2 level/caller_type 逗号多值过滤（spec §2.2 B2 / contract-496 §2），【R】。

    当前 store.query 用单值 _text_eq 把 "INFO,WARN,ERROR" 当整串等值比较 → 永不命中
    → 本类用例全 FAIL（修复锚）。q=<marker> 只把断言限定到本用例造数的记录上
    （排除 @instrument 噪音行以保证 total 精确），不参与多值匹配本身。
    """

    def test_r_b2_level_csv_union(self, client):
        """【R】?level=INFO,WARN,ERROR → INFO/WARN/ERROR 并集精确命中 3 行，DEBUG 排除。"""
        marker = "b2-level-union"
        for level, ctype in (
            ("INFO", "api"),
            ("WARN", "agent"),
            ("ERROR", "llm"),
            ("DEBUG", "tool"),
        ):
            _seed(
                client, level=level, caller_type=ctype,
                event=f"evt_{level.lower()}", marker=marker,
            )
        data = client.get(
            "/api/v1/logs", params={"level": "INFO,WARN,ERROR", "q": marker}
        ).json()["data"]
        assert data["total"] == 3, f"level=INFO,WARN,ERROR 应命中 3 行，实得 {data['total']}"
        assert {item["level"] for item in data["items"]} == {"INFO", "WARN", "ERROR"}

    def test_r_b2_level_csv_case_insensitive(self, client):
        """【R】CSV 大小写不敏感：?level=info,error 命中 INFO/ERROR（_csv_match 双端 upper）。"""
        marker = "b2-level-ci"
        for level, ctype in (("INFO", "api"), ("WARN", "agent"), ("ERROR", "llm")):
            _seed(
                client, level=level, caller_type=ctype,
                event=f"evt_{level.lower()}", marker=marker,
            )
        data = client.get(
            "/api/v1/logs", params={"level": "info,error", "q": marker}
        ).json()["data"]
        assert data["total"] == 2
        assert {item["level"] for item in data["items"]} == {"INFO", "ERROR"}

    def test_r_b2_caller_type_csv_union(self, client):
        """【R】?caller_type=api,agent,tool,cli,mcp（内核 tab 口径）→ api/agent 命中，
        llm/frontend 排除。"""
        marker = "b2-caller-union"
        for ctype, evt in (
            ("api", "evt_api"),
            ("agent", "evt_agent"),
            ("llm", "evt_llm"),
            ("frontend", "evt_fe"),
        ):
            _seed(client, caller_type=ctype, event=evt, marker=marker)
        data = client.get(
            "/api/v1/logs",
            params={"caller_type": "api,agent,tool,cli,mcp", "q": marker},
        ).json()["data"]
        assert data["total"] == 2
        assert {item["caller_type"] for item in data["items"]} == {"api", "agent"}


class TestB3ProjectIdUuid:
    """B3 project_id 接受合法 UUID（spec §2.2 B3 / contract-496 §2），UUID 路径【R】。

    当前参数类型 int → UUID 串过不了 FastAPI int 解析 → 422；契约要求参数 str | None +
    _resolve_project_id（纯数字→int / 合法 UUID→uuid.UUID(s).int / 非法→HTTPException
    422 detail="project_id 须为整数或合法 UUID"）。
    """

    def test_r_b3_uuid4_legal_string_returns_200_empty(self, client):
        """【R】?project_id=<合法 uuid4 串>（无对应记录）不报错 → 200 空集（当前 422 FAIL）。"""
        pid = str(uuid.uuid4())
        resp = client.get("/api/v1/logs", params={"project_id": pid})
        assert resp.status_code == 200, f"合法 UUID 串应 200，实得 {resp.status_code}: {resp.text}"
        assert resp.json()["data"]["total"] == 0

    def test_r_b3_uuid_int_roundtrip_hits(self, client):
        """【R】前端 UUID→int 往返：POST project_id=<uuid.int> 落库
        → GET ?project_id=<UUID 串> 命中。"""
        pid_uuid = uuid.uuid4()
        _seed(client, event="evt_uuid_proj", project_id=pid_uuid.int)
        resp = client.get("/api/v1/logs", params={"project_id": str(pid_uuid)})
        assert resp.status_code == 200, f"UUID 串查询应 200，实得 {resp.status_code}: {resp.text}"
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["project_id"] == pid_uuid.int

    def test_r_b3_invalid_value_422_with_contract_detail(self, client):
        """【R】?project_id=not-an-id → 422 + 契约文案 detail
        （当前 pydantic int 错误体 → FAIL）。"""
        resp = client.get("/api/v1/logs", params={"project_id": "not-an-id"})
        assert resp.status_code == 422
        assert resp.json() == {"detail": "project_id 须为整数或合法 UUID"}


class TestB4CorrelationHeaderFlow:
    """B4 X-Correlation-Id 请求头沿用（spec §2.2 B4 / contract-496 §3），【R】。

    契约行为：携带 X-Correlation-Id 的请求内，任何 @instrument / log_structured 埋点
    落库 correlation_id == 请求头值 → GET /logs?correlation_id=<头值> 可回查命中。
    当前无中间件（correlation 落空串）+ 无 B1 structured sink → 埋点不入 store → 回查空 FAIL。

    触发点说明：pydantic 参数/body 校验级 422 发生在 @instrument 包裹的端点之外，
    不产生埋点（故不能用非法 caller_type 的 POST 做触发）；本用例用 B3 的端点内
    HTTPException(422)（project_id 非法）触发 @instrument 的 WARN E_HTTP_422 埋点。
    实现约束：B3 的 _resolve_project_id 须在 query_logs 函数体内调用——若改为
    FastAPI Depends 抛错，@instrument 捕获不到，B4 回查将落空。
    """

    def test_r_b4_instrument_warn_keeps_request_header_correlation(self, sink_client):
        """【R】X-Correlation-Id: c-42-496 请求 → instrument WARN 落库同 correlation → 回查命中。"""
        cid = "c-42-496"
        trigger = sink_client.get(
            "/api/v1/logs",
            params={"project_id": "not-an-id"},
            headers={"X-Correlation-Id": cid},
        )
        assert trigger.status_code == 422
        data = sink_client.get("/api/v1/logs", params={"correlation_id": cid}).json()["data"]
        assert data["total"] >= 1, "带 X-Correlation-Id 请求的埋点未按 correlation 回查到"
        assert any(
            item["correlation_id"] == cid
            and item["level"] == "WARN"
            and item["caller_type"] == "api"
            and item["error_code"] == "E_HTTP_422"
            for item in data["items"]
        ), "回查结果中缺少 correlation_id 沿用的 instrument WARN(E_HTTP_422) 埋点记录"
