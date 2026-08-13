"""F22 全文搜索 API 端点测试契约（TDD RED 阶段）。

本文件为 `api/routers/search.py`（NEW，spec §3 API 契约）定义测试契约，
覆盖 2 个端点：

- GET  /api/v1/search          — 全文搜索（q / project_id|project_ids /
  types / mode / limit / offset）
- POST /api/v1/search/rebuild  — 手动全量重建索引（project_id 可选，缺省 = 全部项目）

权威来源：specs/f22-search-service/spec.md §3.1-§3.3（端点总览 / 请求
响应示例 / 异常映射表）、§9.1（API 测试层次）、§13 M4（验收标准）。

════════════════════════════════════════════════════════════════════
设计假设（RED 阶段按 spec 口径记录，GREEN 实现必须满足，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 测试方式：fastapi.testclient.TestClient 直连真实 app 对象（import
   inkflow.api.app），验证纯 HTTP 行为；search 路由为新增模块
   `inkflow.api.routers.search`，本文件模块级 import 它（RED 阶段该
   模块不存在 → 收集期 ImportError: cannot import name 'search' from
   'inkflow.api.routers'，即预期失败形态，全部用例不执行）。

2. 【无 token 模式——硬性契约】本文件所有用例依赖 env
   INKFLOW_SERVER_TOKEN 未设置时中间件直通（test_settings_api.py 设计
   假设 #2 同款）：client fixture 内显式 monkeypatch.delenv，免疫开发者
   本机 shell 的 env 残留导致假失败。TestClient(app) 触发 lifespan →
   create_tables() 在 CWD 写 ./inkflow.db（test_settings_api.py #13
   同款行为，已接受）。

3. 【模块契约】`inkflow.api.routers.search` 必须暴露（本文件 patch
   目标 = 最终契约，GREEN 必须匹配）：
   - `router = APIRouter(prefix="/api/v1/search", tags=["Search"])`
     （app.py 需 `app.include_router(search.router)`，与既有 router
     模块级模式一致）
   - `_get_svc() -> SearchService`：零参模块级工厂函数（镜像
     api/routers/settings.py 既有 `_get_key_manager()` 模式）——本
     文件全部用例经 `patch("inkflow.api.routers.search._get_svc")`
     注入 mock service，GREEN 必须保留此工厂名与零参签名
   - SearchService 方法契约：
     `async def search(self, query: SearchQuery) -> SearchResponse`
     `async def rebuild(self, project_id: int | None) -> dict`
     （rebuild 返回 {"rebuilt_at": str, "project_id": str | None}；
     router 对 service 返回值做 JSON 序列化透传，响应体见假设 #9）

4. GET /api/v1/search 请求契约（spec §3.1-§3.2）：
   - q：必填，1-100 字符（缺失 / 空白 / 超长 → 422）
   - project_id 或 project_ids：必填其一（project_ids = 逗号分隔
     UUID 数组 = 同世界观选择器 Q3）；同时缺省 → 422
   - types：可选，逗号分隔 SearchEntityType 枚举（非法 → 422）
   - mode：可选 keyword/semantic，默认 keyword（非法 → 422）
   - limit：可选，默认 20，范围 1-100（0 / 101 → 422）
   - offset：可选，默认 0
   router 组装 SearchQuery（domain/models/search.py §2.2）后调用
   `await svc.search(query)`——测试断言 service 收到的 query 字段
   （q 为 str；project_ids 为 uuid.UUID 列表；mode 为 SearchMode
   枚举，StrEnum 与字符串相等）。

5. GET 200 响应 = SearchResponse JSON：{total, hits: [{entity_type,
   entity_id, project_id, title, snippet, score}], query, types, mode,
   project_ids}（spec §2.2/§3.2 示例）；测试以 dict 形态 mock service
   返回值，断言响应 JSON 结构与字段值（router 透传 / 序列化，不做
   二次加工）。空结果 = total 0 + hits []（spec E5）。

6. GET 404（spec §3.3 首行）：service.search 抛 ProjectNotFoundError
   （复用 F9 inkflow.domain.ports.character_errors，构造参数 = 消息
   字符串）→ router 显式 except 映射 404，响应 body 精确等于
   {"detail": "Project not found: <id>"}（<id> = 项目 UUID 字符串，
   GREEN 可透传异常消息或按请求参数自行格式化，响应体必须与 spec 一致）。

7. GET 422（spec §3.3）：q / types / mode / limit 校验失败 → Pydantic
   校验错误（detail 为 list，字段名在 str(detail) 中回显）；project_id
   与 project_ids 同时缺省 → detail 精确等于字符串 "project_id or
   project_ids required"（GREEN 可在 DTO validator 或 router 层实现，
   响应体必须与 spec 一致）；全部 422 均不触达 service
   （mock_svc.search.assert_not_awaited()）。

8. GET/POST 500（spec §3.3 末行）：service 抛任意异常（RuntimeError）
   → router except Exception → 500 + body {"detail": "Internal server
   error"}，内部异常消息不得泄漏进响应（TestClient 默认
   raise_server_exceptions=True，GREEN 必须捕获并转 HTTPException）。

9. POST /api/v1/search/rebuild 请求契约（spec §3.1-§3.2，v1.2 新增；#251 P3 多项目升级）：
   - query 参数 project_id（单值）或 project_ids（逗号分隔多值）：可选；
     都缺省 → service.rebuild(None)（重建全部项目索引）；提供 →
     service.rebuild([<UUID>.int, ...])（list[int] 口径，spec §8.2）
   - 200 响应：{"rebuilt_at": "<ISO8601 UTC>", "project_ids":
     ["<uuid>", ...] | null}——全量重建 project_ids 为 null，
     指定项目回显 UUID 字符串列表
   - 404：service.rebuild 抛 ProjectNotFoundError（映射同假设 #6）

10. RED 阶段预期：`inkflow.api.routers.search` 模块不存在 → 本文件
    收集期 ImportError（cannot import name 'search' from
    'inkflow.api.routers'），collected 0 items + 1 error（退出码 2）。
    GREEN 阶段：按上述契约实现 api/routers/search.py + app.py
    include_router 后全绿。

覆盖场景（spec §9.1 API 行 + M4）：GET 200 命中 / 空结果、GET 404、
GET 422 全矩阵（q 缺失 / 空白 / 超长 101、types / mode 非法、limit
0 / 101、双参数缺省精确 detail）、mode=semantic 回显 + service 枚举
透传、project_id 单值 → service 收 project_ids=[UUID]、project_ids
逗号分隔多值解析、GET/POST 500 通用 detail、POST rebuild 200 全量 /
单项目（UUID.int 断言 + 响应回显）、POST rebuild 404。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers import (
    search,  # noqa: F401  # RED 收集断言：模块存在性契约（GREEN 实现后即被使用）
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（F19 §2.3.1）：本文件全部用例依赖未设置 → 直通。"""

ENDPOINT_SEARCH = "/api/v1/search"
"""全文搜索端点（spec §3.1）。"""

ENDPOINT_REBUILD = "/api/v1/search/rebuild"
"""手动全量重建索引端点（spec §3.1，v1.2 新增）。"""

PROJECT_A = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
"""测试项目 A（命中来源项目）。"""

PROJECT_B = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
"""测试项目 B（同世界观选择器第二项目）。"""

ENTITY_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-00000000000a")
"""测试命中实体 ID。"""

TS = "2026-08-09T12:00:00Z"
"""rebuild 响应 rebuilt_at 测试值（ISO8601 UTC）。"""


# ── Fixtures ──


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient 实例（函数级，与 tests/api 既有风格一致）。

    设计假设 #2：显式 delenv INKFLOW_SERVER_TOKEN → token 中间件直通，
    全部用例无 token 直连；monkeypatch 自动还原，测试间互不污染。
    """
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    return TestClient(app)


@pytest.fixture
def mock_svc():
    """注入 mock SearchService（设计假设 #3）：patch router 模块级工厂 `_get_svc`。

    与 test_settings_api.py patch `_get_key_manager` 同模式——mock
    service 的 search / rebuild 为 AsyncMock，用例按需设置 return_value
    或 side_effect。
    """
    svc = AsyncMock()
    svc.search = AsyncMock()
    svc.rebuild = AsyncMock()
    with patch("inkflow.api.routers.search._get_svc", return_value=svc):
        yield svc


def _hit(**overrides: object) -> dict:
    """构造单条 SearchHit JSON dict（spec §2.2 字段全集）。"""
    hit: dict[str, object] = {
        "entity_type": "chapter",
        "entity_id": str(ENTITY_ID),
        "project_id": str(PROJECT_A),
        "title": "第 3 章 龙的苏醒",
        "snippet": "古井深处，<mark>龙</mark>瞳睁开。它沉睡千年……",
        "score": 3.2,
    }
    hit.update(overrides)
    return hit


def _search_response(**overrides: object) -> dict:
    """构造完整 SearchResponse JSON dict（spec §2.2 / §3.2 示例）。"""
    data: dict[str, object] = {
        "total": 1,
        "hits": [_hit()],
        "query": "龙",
        "types": None,
        "mode": "keyword",
        "project_ids": [str(PROJECT_A)],
    }
    data.update(overrides)
    return data


def _query_arg(svc):
    """取 service.search 收到的 SearchQuery（位置或关键字传参，兼容两种 GREEN 形态）。"""
    call = svc.search.await_args
    assert call is not None, "service.search 未被调用"
    return call.args[0] if call.args else call.kwargs["query"]


def _rebuild_arg(svc):
    """取 service.rebuild 收到的 project_ids 列表（位置或关键字传参）。"""
    call = svc.rebuild.await_args
    assert call is not None, "service.rebuild 未被调用"
    return call.args[0] if call.args else call.kwargs["project_ids"]


# ── GET /api/v1/search（spec §3.1-§3.3）──


class TestSearchGet:
    """GET /api/v1/search 端点契约（设计假设 #4-#8）。"""

    def test_get_200_hits(self, client, mock_svc):
        """200 命中：SearchResponse JSON 结构完整（M4；假设 #4/#5）。"""
        mock_svc.search.return_value = _search_response(
            types=["chapter", "world"],
            project_ids=[str(PROJECT_A), str(PROJECT_B)],
        )
        resp = client.get(
            ENDPOINT_SEARCH,
            params={
                "q": "龙",
                "project_ids": f"{PROJECT_A},{PROJECT_B}",
                "types": "chapter,world",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["hits"]) == 1
        hit = body["hits"][0]
        assert hit["entity_type"] == "chapter"
        assert hit["entity_id"] == str(ENTITY_ID)
        assert hit["project_id"] == str(PROJECT_A)
        assert hit["title"] == "第 3 章 龙的苏醒"
        assert "<mark>" in hit["snippet"]
        assert hit["score"] == 3.2
        assert body["query"] == "龙"
        assert body["types"] == ["chapter", "world"]
        assert body["mode"] == "keyword"
        assert body["project_ids"] == [str(PROJECT_A), str(PROJECT_B)]
        # 请求参数到达 service（假设 #4：router 组装 SearchQuery 透传）
        query = _query_arg(mock_svc)
        assert query.q == "龙"
        assert query.project_ids == [PROJECT_A, PROJECT_B]

    def test_get_200_empty(self, client, mock_svc):
        """200 空结果：total 0 + hits []（spec E5；假设 #5）。"""
        mock_svc.search.return_value = _search_response(
            total=0, hits=[], query="不存在的词"
        )
        resp = client.get(
            ENDPOINT_SEARCH,
            params={"q": "不存在的词", "project_id": str(PROJECT_A)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["hits"] == []
        assert body["query"] == "不存在的词"

    def test_get_404_project_not_found(self, client, mock_svc):
        """任一项目不存在 → 404 {"detail": "Project not found: <id>"}（假设 #6）。"""
        mock_svc.search.side_effect = ProjectNotFoundError(
            f"Project not found: {PROJECT_A}"
        )
        resp = client.get(
            ENDPOINT_SEARCH, params={"q": "龙", "project_id": str(PROJECT_A)}
        )
        assert resp.status_code == 404
        assert resp.json() == {"detail": f"Project not found: {PROJECT_A}"}

    @pytest.mark.parametrize(
        ("params", "token"),
        [
            ({"project_id": str(PROJECT_A)}, "q"),  # q 缺失
            ({"q": "   ", "project_id": str(PROJECT_A)}, "q"),  # q 空白
            ({"q": "x" * 101, "project_id": str(PROJECT_A)}, "q"),  # q 超长 101
            ({"q": "龙", "project_id": str(PROJECT_A), "types": "banana"}, "types"),
            ({"q": "龙", "project_id": str(PROJECT_A), "mode": "banana"}, "mode"),
            ({"q": "龙", "project_id": str(PROJECT_A), "limit": 0}, "limit"),
            ({"q": "龙", "project_id": str(PROJECT_A), "limit": 101}, "limit"),
        ],
        ids=[
            "q_missing",
            "q_blank",
            "q_too_long",
            "types_invalid",
            "mode_invalid",
            "limit_zero",
            "limit_101",
        ],
    )
    def test_get_validation_422(self, client, mock_svc, params, token):
        """422 矩阵：Pydantic 校验错误（detail=list，字段名回显），不触达 service。

        设计假设 #7：q 缺失 / 空白 / 超长、types / mode 非法枚举、
        limit 越界（0 / 101）均为 DTO 层校验错误。
        """
        resp = client.get(ENDPOINT_SEARCH, params=params)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert f"'{token}'" in str(detail)
        mock_svc.search.assert_not_awaited()

    def test_get_422_project_params_both_missing(self, client, mock_svc):
        """project_id 与 project_ids 同时缺省 → 422 精确 detail（v1.1 Q3，假设 #7）。"""
        resp = client.get(ENDPOINT_SEARCH, params={"q": "龙"})
        assert resp.status_code == 422
        assert resp.json()["detail"] == "project_id or project_ids required"
        mock_svc.search.assert_not_awaited()

    def test_get_mode_semantic_passthrough(self, client, mock_svc):
        """mode=semantic：响应回显 + service 收到 SearchMode 枚举（v1.1 §5.8）。"""
        mock_svc.search.return_value = _search_response(mode="semantic")
        resp = client.get(
            ENDPOINT_SEARCH,
            params={"q": "龙", "project_id": str(PROJECT_A), "mode": "semantic"},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "semantic"
        query = _query_arg(mock_svc)
        assert query.mode == "semantic"  # SearchMode StrEnum 与字符串相等

    def test_get_project_id_single_value(self, client, mock_svc):
        """project_id 单值 → service 收到 project_ids=[该 UUID]（Q3 单项目语义）。"""
        mock_svc.search.return_value = _search_response()
        resp = client.get(
            ENDPOINT_SEARCH, params={"q": "龙", "project_id": str(PROJECT_A)}
        )
        assert resp.status_code == 200
        query = _query_arg(mock_svc)
        assert query.project_ids == [PROJECT_A]

    def test_get_project_ids_comma_separated(self, client, mock_svc):
        """project_ids 逗号分隔多值 → service 收到两个 UUID（同世界观选择器）。"""
        mock_svc.search.return_value = _search_response(
            project_ids=[str(PROJECT_A), str(PROJECT_B)]
        )
        resp = client.get(
            ENDPOINT_SEARCH,
            params={"q": "龙", "project_ids": f"{PROJECT_A},{PROJECT_B}"},
        )
        assert resp.status_code == 200
        query = _query_arg(mock_svc)
        assert query.project_ids == [PROJECT_A, PROJECT_B]
        assert resp.json()["project_ids"] == [str(PROJECT_A), str(PROJECT_B)]

    def test_get_500_internal_error(self, client, mock_svc):
        """service 抛 RuntimeError → 500 通用 detail，内部消息不泄漏（假设 #8）。"""
        mock_svc.search.side_effect = RuntimeError("boom")
        resp = client.get(
            ENDPOINT_SEARCH, params={"q": "龙", "project_id": str(PROJECT_A)}
        )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"
        assert "boom" not in resp.text


# ── POST /api/v1/search/rebuild（spec §3.1-§3.3，v1.2 新增）──


class TestSearchRebuild:
    """POST /api/v1/search/rebuild 端点契约（设计假设 #9）。"""

    def test_rebuild_200_all(self, client, mock_svc):
        """缺省 project_id/project_ids → service.rebuild(None)，响应 project_ids=null。"""
        mock_svc.rebuild.return_value = {"rebuilt_at": TS, "project_ids": None}
        resp = client.post(ENDPOINT_REBUILD)
        assert resp.status_code == 200
        body = resp.json()
        assert body["rebuilt_at"] == TS
        assert body["project_ids"] is None
        assert _rebuild_arg(mock_svc) is None

    def test_rebuild_200_single_project(self, client, mock_svc):
        """project_id=X → service.rebuild 收到 [UUID.int]，响应回显 UUID 列表。"""
        mock_svc.rebuild.return_value = {
            "rebuilt_at": TS,
            "project_ids": [str(PROJECT_A)],
        }
        resp = client.post(ENDPOINT_REBUILD, params={"project_id": str(PROJECT_A)})
        assert resp.status_code == 200
        body = resp.json()
        assert body["rebuilt_at"] == TS
        assert body["project_ids"] == [str(PROJECT_A)]
        assert _rebuild_arg(mock_svc) == [PROJECT_A.int]

    def test_rebuild_200_multi_project(self, client, mock_svc):
        """project_ids=X,Y → service.rebuild 收到 [X.int, Y.int]（#251 P3 多项目）。"""
        mock_svc.rebuild.return_value = {
            "rebuilt_at": TS,
            "project_ids": [str(PROJECT_A), str(PROJECT_B)],
        }
        resp = client.post(
            ENDPOINT_REBUILD,
            params={"project_ids": f"{PROJECT_A},{PROJECT_B}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rebuilt_at"] == TS
        assert body["project_ids"] == [str(PROJECT_A), str(PROJECT_B)]
        assert _rebuild_arg(mock_svc) == [PROJECT_A.int, PROJECT_B.int]

    def test_rebuild_404_project_not_found(self, client, mock_svc):
        """project_id 不存在 → 404（映射同 GET，假设 #6/#9）。"""
        mock_svc.rebuild.side_effect = ProjectNotFoundError(
            f"Project not found: {PROJECT_A}"
        )
        resp = client.post(ENDPOINT_REBUILD, params={"project_id": str(PROJECT_A)})
        assert resp.status_code == 404
        assert resp.json() == {"detail": f"Project not found: {PROJECT_A}"}

    def test_rebuild_500_internal_error(self, client, mock_svc):
        """service.rebuild 抛 RuntimeError → 500 通用 detail（假设 #8）。"""
        mock_svc.rebuild.side_effect = RuntimeError("boom")
        resp = client.post(ENDPOINT_REBUILD)
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"
        assert "boom" not in resp.text
