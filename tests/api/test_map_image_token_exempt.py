"""#1093 地图底图 token 豁免 — API 测试契约。

缺陷：世界观 → 地图视图「图片」tab 底图破图。MapCanvas.tsx:272 用
``<img src={baseURL}/api/v1/maps/{id}/image>`` 直接加载；``<img src>`` 无法
携带自定义请求头，而后端 token 中间件拦截全部数据面端点 → 裸请求 401 → 破图。
仅真实 GUI 复现（vitest/jsdom 无中间件、API 层测试自带 token 头，均测不出）。

方案 A（本 issue 采用）：后端豁免 ``GET /api/v1/maps/{id}/image`` token 校验。
该端点返回项目内已上传的静态图片，可由已获 token 的客户端枚举到 map id，
不构成新的信息暴露面；写路径（PUT 同 URL）**不豁免**。

权威来源：specs/f19-gui/spec.md §2.3.1（token 中间件豁免面）。
本文件补充其豁免清单：原仅 /docs /redoc /openapi.json（静态文档）；
#1093 增加 GET /api/v1/maps/{id}/image（图片渲染通道，浏览器原生 img 无法带头）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约）
════════════════════════════════════════════════════════════════════

1. 豁免面 = 精确正则 ``^/api/v1/maps/[^/]+/image$``，方法限定 GET。
   - ``/api/v1/maps/x/image/extra``、``/api/v1/maps/x/images``、``/api/v1/maps``
     均**不在**豁免面内（防前缀匹配导致的豁免面外溢）。
   - PUT 同路径为写操作（上传替换图片），**不豁免**。
2. env ``INKFLOW_SERVER_TOKEN`` 未设置时中间件直通（既有语义不变）。
3. 豁免判定先于 token 比较，且不触达路由 handler 之外的行为——
   豁免请求仍可因资源不存在返回 404（本文件用"非 401"断言，
   避免为造 200 而 mock 大量 DB/service 依赖）。

════════════════════════════════════════════════════════════════════
RED 阶段预期
════════════════════════════════════════════════════════════════════
- ``TestMapImageTokenExempt``：中间件未豁免 → 401 → FAIL（RED 主体）。
- 反例类 ``TestExemptionSurfaceNoOverflow``：当前即 401 → PASS（守护语义，
  必须保持 PASS；若豁免实现放宽成前缀匹配，此类将 FAIL）。
- ``TestNoTokenModeUnchanged``：直通语义 → PASS。

禁改本文件断言（F15 铁律）：测试是契约，实现不得修改测试。
════════════════════════════════════════════════════════════════════
"""

import uuid
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app

#: 合法 UUID 形态的 map id（豁免判定不依赖该 id 是否存在）。
#: 用 ``uuid.UUID(int=<小整数>)`` 而非 ``uuid.uuid4()``：真实主键映射是
#: ``uuid.UUID(int=orm.id)``（map_repo._orm_to_domain），128-bit 随机 UUID 的
#: ``.int`` 超出 SQLite 64-bit INTEGER → 仓储层 OverflowError 500
#: （既存缺陷，非本 issue 范围）；本文件只测中间件豁免面，不应被它带偏。
MAP_ID = str(uuid.UUID(int=424242))

# ── 契约常量（对齐 test_token_auth.py）──
TOKEN_HEADER = "X-InkFlow-Token"
"""token 传递请求头（spec §2.1.3）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（spec §2.3.1）。"""

TEST_TOKEN = "test-token-1093-mapImg"
"""测试固定 token。"""


# ── Fixtures ──


@pytest.fixture
def client():
    """FastAPI TestClient（与 tests/api 既有风格一致）。"""
    return TestClient(app)


@pytest.fixture
def set_token_env(monkeypatch):
    """设置 INKFLOW_SERVER_TOKEN=TEST_TOKEN（中间件每请求读 env）。"""
    monkeypatch.setenv(ENV_TOKEN, TEST_TOKEN)
    return TEST_TOKEN


# ── 豁免面：GET /api/v1/maps/{id}/image（#1093 主体）──


class TestMapImageTokenExempt:
    """GET /maps/{id}/image 必须豁免 token——浏览器 <img src> 无法带自定义头。"""

    def test_map_image_without_token_not_rejected(self, client, set_token_env):
        """无 token GET /api/v1/maps/{uuid}/image → 非 401（RED 主体）。

        豁免后请求越过中间件进入路由层；该 map 不存在 → 404。
        断言"非 401"而非 200：本用例只验证鉴权层豁免，不为造 200 而 mock
        整条 service/DB 链（豁免与否在中间件层即可判定）。
        """
        resp = client.get(f"/api/v1/maps/{MAP_ID}/image")
        assert resp.status_code != 401, (
            f"GET /maps/{{id}}/image 应豁免 token（<img src> 无法带自定义头，"
            f"#1093 底图破图根因），实际 {resp.status_code}"
        )

    def test_map_image_wrong_token_not_rejected(self, client, set_token_env):
        """带错误 token GET /maps/{id}/image → 非 401（豁免面不校验 token）。"""
        resp = client.get(
            f"/api/v1/maps/{MAP_ID}/image",
            headers={TOKEN_HEADER: "wrong-token"},
        )
        assert resp.status_code != 401

    def test_map_image_with_token_still_works(self, client, set_token_env):
        """带正确 token GET /maps/{id}/image → 非 401（豁免不破坏原带 token 路径）。"""
        resp = client.get(
            f"/api/v1/maps/{MAP_ID}/image",
            headers={TOKEN_HEADER: TEST_TOKEN},
        )
        assert resp.status_code != 401


# ── 反例守护：豁免面不得外溢（#1093 安全边界）──


class TestExemptionSurfaceNoOverflow:
    """豁免仅限 GET /maps/{id}/image —— 其它端点必须仍然 401。

    若实现把豁免写成粗粒度前缀匹配（如 startswith("/api/v1/maps")），
    下列用例会全部 FAIL——这是本类的存在意义。
    """

    #: 无 token 时必须 401 的敏感端点（GET = 读，其它 = 写/删）
    SENSITIVE_ENDPOINTS: ClassVar[list[tuple[str, str]]] = [
        ("GET", "/api/v1/projects"),
        ("GET", "/api/v1/maps"),
        ("GET", f"/api/v1/maps/{MAP_ID}"),
        ("GET", f"/api/v1/maps/{MAP_ID}/children"),
        ("GET", f"/api/v1/maps/{MAP_ID}/pins"),
        ("GET", "/api/v1/worlds"),
        ("GET", "/api/v1/settings"),
        ("GET", "/health"),
        ("PUT", f"/api/v1/maps/{MAP_ID}/image"),
        ("DELETE", f"/api/v1/maps/{MAP_ID}"),
    ]

    @pytest.mark.parametrize("method,path", SENSITIVE_ENDPOINTS)
    def test_sensitive_endpoint_still_401(self, client, set_token_env, method, path):
        """无 token 访问敏感端点 → 401（豁免面不外溢）。"""
        resp = client.request(method, path)
        assert resp.status_code == 401, (
            f"{method} {path} 不应被 #1093 豁免面覆盖（豁免仅 GET /maps/{{id}}/image），"
            f"实际 {resp.status_code}"
        )

    @pytest.mark.parametrize(
        "path",
        [
            f"/api/v1/maps/{MAP_ID}/image/extra",
            f"/api/v1/maps/{MAP_ID}/images",
            "/api/v1/maps/image",
        ],
    )
    def test_near_miss_paths_still_401(self, client, set_token_env, path):
        """近似路径不得被豁免（正则精确匹配，非前缀）。

        - ``.../image/extra``：多一段
        - ``.../images``：复数（非 image 端点）
        - ``/api/v1/maps/image``：id 段缺失
        """
        resp = client.get(path)
        assert resp.status_code == 401, (
            f"{path} 是近似路径，不应命中豁免正则 ^/api/v1/maps/[^/]+/image$，"
            f"实际 {resp.status_code}"
        )

    def test_put_map_image_write_not_exempt(self, client, set_token_env):
        """PUT 同 URL（上传替换图片）为写操作 → 不豁免（显式反例）。

        豁免只针对浏览器原生 GET 渲染通道；写路径继续受 token 保护。
        """
        resp = client.put(
            f"/api/v1/maps/{MAP_ID}/image", files={"file": ("a.png", b"x")}
        )
        assert resp.status_code == 401


# ── 无 token 模式（既有语义不变）──


class TestNoTokenModeUnchanged:
    """env 未设置时中间件直通——既有测试零破坏的保障，本 issue 不动该语义。"""

    def test_no_token_mode_map_image_passthrough(self, client, monkeypatch):
        """env 未设置 → GET /maps/{id}/image 直通（非 401）。"""
        monkeypatch.delenv(ENV_TOKEN, raising=False)
        resp = client.get(f"/api/v1/maps/{MAP_ID}/image")
        assert resp.status_code != 401

    def test_no_token_mode_sensitive_passthrough(self, client, monkeypatch):
        """env 未设置 → 敏感端点亦直通（整体直通语义不变）。"""
        monkeypatch.delenv(ENV_TOKEN, raising=False)
        resp = client.get("/api/v1/projects")
        assert resp.status_code != 401
