"""#77 内核进程化 token 鉴权中间件 — API 测试契约（TDD RED 阶段）。

本文件为 `api/middleware/token_auth.py`（NEW，spec §2.3.1）+ `api/app.py`
（注册中间件 + CORS 配置化，spec §2.3.2）+ `core/config.py`
（新增 `server_cors_origins` 等字段，spec §2.5）定义测试契约。

权威来源：specs/f19-gui/spec.md §2.1.3（token 传递）、§2.3.1（token 中间件）、
§2.3.2（CORS 配置化）、§2.6（测试策略）、§2.7 M2/M4（验收）。
2026-08-03 评审 Q2=选项 B：/health 不豁免，豁免仅 /docs /redoc /openapi.json。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 测试方式：fastapi.testclient.TestClient 直连真实 app 对象（import
   inkflow.api.app），验证纯 HTTP 行为。token 鉴权是 API 层关注点，
   与 CLI/Typer 无关——本文件不涉及 CliRunner，FORCE_COLOR 等 CLI 颜色
   环境变量与本文件无关。

2. 【env 读取时机——硬性契约】中间件必须在【每次请求时】读取环境变量
   `INKFLOW_SERVER_TOKEN`（在其 dispatch/__call__ 内部调用 os.environ /
   os.getenv），【禁止】在模块 import 时或 app 构建时缓存读取。
   原因：本文件与 tests/api/ 其他文件共享同一 pytest 进程，`inkflow.api.app`
   的 import 顺序不可控；测试通过 monkeypatch.setenv/delenv 在 import 之后
   修改环境。若实现改为启动时读取，本文件的通过/失败将取决于 pytest 收集
   顺序——不可接受的脆弱性。spec §2.3.1 的「避免 config 单例启动时序问题」
   同理适用于此。

3. 【强制层——硬性契约】token 校验只能由 HTTP 中间件完成（spec §2.3.1：
   `@app.middleware("http")` 或纯 ASGI 中间件）。全局 HTTPBearer security
   scheme（spec §2.3.1 末条）仅用于 OpenAPI 文档（Swagger UI Authorize
   按钮），【禁止】将其作为路由的强制依赖（dependency）——FastAPI 的
   HTTPBearer 依赖会返回 403/自带 WWW-Authenticate 挑战，破坏本文件
   第 4 条的 401 契约；且 env 未设置时（既有测试环境）既有 1667 个测试
   全部直连 app 不带 token，强制依赖会全量破坏（违反「env 未设置时
   中间件直通、既有测试零破坏」spec 补充行）。

4. 401 契约（spec §2.3.1）：状态码 401；响应体精确等于
   `{"detail": "Unauthorized"}`（无内部细节，防探测）；【无】
   WWW-Authenticate 响应头（非 HTTP Basic/Bearer 挑战语义）。

5. 校验范围（Q2 选项 B）：所有端点均需 token，【含 /health】；豁免仅
   /docs /redoc /openapi.json（静态文档，无数据面）。/api/v1/projects
   为代表性数据面端点。

6. 无 token 模式（spec §2.3.1 补充行）：env `INKFLOW_SERVER_TOKEN`
   未设置时中间件直通（不校验任何请求）。token 校验是 `serve` 命令的
   职责（serve 必设 env），不是 app 内置认证。本文件的无 token 模式
   测试显式 monkeypatch.delenv，避免开发者本机 shell 恰好设置了该 env
   导致假失败。

7. DB 规避策略：GET /api/v1/projects 依赖 DB（Depends(get_db) →
   get_project_service(db)）。本文件沿用 tests/api/test_project_api.py
   的既有模式：`patch("inkflow.api.routers.project.get_project_service")`
   + AsyncMock 替换 service 层（handler 内 `_get_svc(db)` 调用该模块级
   函数），使 200-through 断言不触达 service/DB 业务层。注意 get_db
   依赖仍会执行（打开会话），与 tests/api 既有测试行为完全一致——
   这是既有套件已接受的基线，本文件不新增污染。CORS 相关测试改用
   /health（无 DB 依赖），完全不需要 mock。

8. lifespan/TestClient：TestClient(app) 触发 lifespan → create_tables()
   会在 CWD 写 ./inkflow.db，与 tests/api 既有测试（test_health.py、
   test_project_api.py）行为一致，已接受，不做规避。

9. CORS 契约（spec §2.3.2 + M4）：白名单从 config.server_cors_origins
   （list[str]）读取，默认含 http://localhost:5173 http://127.0.0.1:5173
   http://localhost:8765 http://127.0.0.1:8765 与 "null"（Electron #78
   file:// 加载）；allow_credentials=True 保留。行为对齐现有 app.py
   CORSMiddleware：白名单内 Origin 的响应携带 Access-Control-Allow-Origin
   （回显具体源，非 *）；白名单外 Origin 不携带该头。

10. 【preflight 契约】预检 OPTIONS 请求（浏览器跨域先决请求）【不带】
    X-InkFlow-Token 头（浏览器不会在 preflight 上附加自定义头）。token
    中间件必须放行 preflight——实现方式二选一（按注册顺序或显式豁免）：
    a) 中间件注册顺序：CORSMiddleware 先 add_middleware（外层），token
       中间件后 add（内层）→ preflight 被 CORS 层短路，token 层不可见；
    b) token 中间件对 OPTIONS 预检请求显式豁免。
    无论哪种，行为契约相同：白名单 Origin 的 OPTIONS 预检 → 200 + ACAO。

11. HTTPBearer scheme 注册（spec §2.6 集成场景）：/openapi.json 的
    components.securitySchemes 中必须出现一个 type=http / scheme=bearer
    的 security scheme（Swagger Authorize 按钮的数据基础）。

════════════════════════════════════════════════════════════════════
RED 阶段预期：中间件未实现 → 本文件在「env 已设置」场景下全部 FAIL
（请求直接 200 而非 401）；「env 未设置」场景与 CORS 场景在中间件
合入前可能 PASS（依赖既有 app 行为）。GREEN 阶段：按上述契约实现
`api/middleware/token_auth.py` + 注册到 app.py + CORS 配置化后全绿。
════════════════════════════════════════════════════════════════════
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app

# ── 契约常量 ──
TOKEN_HEADER = "X-InkFlow-Token"
"""token 传递请求头（spec §2.1.3）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（spec §2.3.1）：serve 启动时注入进程环境。"""

TEST_TOKEN = "test-token-77-aB3xQ9"
"""测试固定 token（spec §2.3.1：测试可设固定值）。"""

WRONG_TOKEN = "wrong-token-zzz"
"""错误 token，用于 401 分支。"""

WHITELISTED_ORIGIN = "http://localhost:5173"
"""默认 CORS 白名单内的 Vite dev server Origin。"""

EVIL_ORIGIN = "http://evil.example.com"
"""默认 CORS 白名单外的 Origin（防 DNS rebinding 探测场景）。"""


# ── Fixtures ──


@pytest.fixture
def client():
    """FastAPI TestClient 实例（函数级，与 tests/api 既有风格一致）。

    触发 lifespan → create_tables()，行为与 test_health.py 相同。
    """
    return TestClient(app)


@pytest.fixture
def set_token_env(monkeypatch):
    """设置 INKFLOW_SERVER_TOKEN=TEST_TOKEN，返回 token 值。

    monkeypatch 自动还原，测试间互不污染。依赖设计假设 #2：
    中间件每次请求时读 env，故在 app import 之后设置仍然有效。
    """
    monkeypatch.setenv(ENV_TOKEN, TEST_TOKEN)
    return TEST_TOKEN


@pytest.fixture
def patched_project_list_service():
    """mock service 层，使 GET /api/v1/projects 200-through 不触达 DB。

    与 tests/api/test_project_api.py 的既有模式一致：
    patch 模块级 get_project_service（handler 内 `_get_svc(db)` 调用），
    AsyncMock.list_projects 返回 ([], 0) → 响应 {"items": [], "total": 0}。
    """
    with patch("inkflow.api.routers.project.get_project_service") as mock_get_service:
        mock_service = AsyncMock()
        mock_service.list_projects = AsyncMock(return_value=([], 0))
        mock_get_service.return_value = mock_service
        yield mock_service


# ── token 校验三分支（env 已设置，spec §2.3.1 / §2.7 M2）──


class TestTokenAuthRequired:
    """token 校验强制场景：env 已设置时，除静态文档外全部端点强制。"""

    def test_missing_token_returns_401(self, client, set_token_env):
        """GET /api/v1/projects 无 X-InkFlow-Token 头 → 401。

        数据面端点（/api/v1/*）token 缺失必须被中间件拦截。
        """
        resp = client.get("/api/v1/projects")
        assert resp.status_code == 401
        # 🔒 强化（#524）：锁精确 body（同文件 test_unauthorized_response_contract 已示范）
        assert resp.json() == {"detail": "Unauthorized"}

    def test_wrong_token_returns_401(self, client, set_token_env):
        """GET /api/v1/projects 带错误 token → 401。

        token 不匹配必须拒绝；错误值不得泄露任何差异信息。
        """
        resp = client.get("/api/v1/projects", headers={TOKEN_HEADER: WRONG_TOKEN})
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}

    def test_correct_token_returns_200(
        self, client, set_token_env, patched_project_list_service
    ):
        """GET /api/v1/projects 带正确 token → 200。

        正确 token 放行至路由层；service 层被 mock（设计假设 #7），
        响应为 items/total 列表结构。
        """
        resp = client.get("/api/v1/projects", headers={TOKEN_HEADER: TEST_TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_health_missing_token_returns_401(self, client, set_token_env):
        """GET /health 无 token → 401（Q2 选项 B：/health 不豁免）。

        评审拍板：/health 与数据面端点同规则，堵 DNS rebinding 探测通道。
        """
        resp = client.get("/health")
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}

    def test_health_correct_token_returns_200(self, client, set_token_env):
        """GET /health 带正确 token → 200 + status=ok。

        壳（#78）解析 INKFLOW_READY 行拿 token 后轮询健康检查，零成本。
        """
        resp = client.get("/health", headers={TOKEN_HEADER: TEST_TOKEN})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_unauthorized_response_contract(self, client, set_token_env):
        """401 响应契约（spec §2.3.1）：精确 body + 无 WWW-Authenticate。

        - 响应体精确等于 {"detail": "Unauthorized"}（无内部细节，防探测）
        - 无 WWW-Authenticate 响应头（非 HTTP Basic/Bearer 挑战语义）
        """
        resp = client.get("/api/v1/projects")
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}
        assert "WWW-Authenticate" not in resp.headers

    def test_unauthorized_rejected_before_handler(
        self, client, set_token_env, patched_project_list_service
    ):
        """鉴权失败必须在路由 handler 之前拦截（service 层零调用）。

        401 请求不得进入业务层：防探测 + 不浪费 DB 连接。
        mock 的 service.list_projects 不应被 await。
        """
        resp = client.get("/api/v1/projects", headers={TOKEN_HEADER: WRONG_TOKEN})
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}
        patched_project_list_service.list_projects.assert_not_awaited()


# ── 静态文档豁免（spec §2.1.3 / §2.3.1）──


class TestTokenAuthExemptions:
    """豁免仅 /docs /redoc /openapi.json（静态文档，无数据面）。"""

    def test_docs_exempt_from_token(self, client, set_token_env):
        """GET /docs 无 token → 200（Swagger UI 文档页）。"""
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_redoc_exempt_from_token(self, client, set_token_env):
        """GET /redoc 无 token → 200（ReDoc 文档页）。"""
        resp = client.get("/redoc")
        assert resp.status_code == 200

    def test_openapi_json_exempt_from_token(self, client, set_token_env):
        """GET /openapi.json 无 token → 200（OpenAPI schema）。"""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200

    def test_openapi_registers_httpbearer_scheme(self, client, set_token_env):
        """OpenAPI 必须注册全局 HTTPBearer security scheme（spec §2.3.1 / §2.6）。

        components.securitySchemes 中出现 type=http / scheme=bearer 的
        scheme —— Swagger UI Authorize 按钮的数据基础，兼作 ADR-024
        云端 JWT（Authorization: Bearer）前置。仅文档元数据，不参与
        强制（设计假设 #3）。
        """
        schema = client.get("/openapi.json").json()
        schemes = schema["components"]["securitySchemes"]
        bearer_schemes = [
            s
            for s in schemes.values()
            if s.get("type") == "http" and s.get("scheme") == "bearer"
        ]
        assert (
            bearer_schemes
        ), f"OpenAPI components.securitySchemes 缺少 HTTPBearer scheme: {list(schemes)}"


# ── 无 token 模式（env 未设置 → 直通，spec §2.3.1 补充行）──


class TestNoTokenMode:
    """env 未设置时中间件直通——既有测试零破坏的保障。"""

    def test_no_token_mode_projects_passthrough(
        self, client, monkeypatch, patched_project_list_service
    ):
        """env 未设置 + 无 token 头 → /api/v1/projects 200。

        显式 delenv 免疫开发者本机 shell 的 env 残留（设计假设 #6）。
        该模式是既有 1667 测试的运行前提。
        """
        monkeypatch.delenv(ENV_TOKEN, raising=False)
        resp = client.get("/api/v1/projects")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_no_token_mode_health_passthrough(self, client, monkeypatch):
        """env 未设置 + 无 token 头 → /health 200。

        直通模式对全部端点生效（含 /health）。
        """
        monkeypatch.delenv(ENV_TOKEN, raising=False)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── CORS 白名单（spec §2.3.2 / §2.7 M4）──


class TestCorsWhitelist:
    """CORS 白名单来自 config.server_cors_origins，本地源放行、非本地源拒绝。

    使用 /health + 正确 token（DB-free，设计假设 #7）；CORS 头由
    CORSMiddleware 包裹全部响应，路径无关。
    """

    def test_whitelisted_origin_gets_allow_origin(self, client, set_token_env):
        """Origin=http://localhost:5173（白名单内）+ 正确 token → ACAO 回显。

        allow_credentials=True 时回显具体源（非 *）：Vite dev server 跨域。
        """
        resp = client.get(
            "/health",
            headers={TOKEN_HEADER: TEST_TOKEN, "Origin": WHITELISTED_ORIGIN},
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == WHITELISTED_ORIGIN

    def test_null_origin_allowed(self, client, set_token_env):
        """Origin=null（白名单内，Electron #78 file:// 加载）→ ACAO 回显 null。

        spec §2.3.2：生产模式 file:// 加载时浏览器 Origin 为 null，
        必须放行（#78 消费方）。
        """
        resp = client.get(
            "/health",
            headers={TOKEN_HEADER: TEST_TOKEN, "Origin": "null"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "null"

    def test_non_whitelisted_origin_no_allow_origin(self, client, set_token_env):
        """Origin=http://evil.example.com（白名单外）→ 响应无 ACAO 头。

        非白名单源不加 CORS 头（现有 CORSMiddleware 行为），浏览器
        读不到 ACAO 即拦截响应——封堵 DNS rebinding 端口探测。
        """
        resp = client.get(
            "/health",
            headers={TOKEN_HEADER: TEST_TOKEN, "Origin": EVIL_ORIGIN},
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" not in resp.headers

    def test_preflight_without_token_passes(self, client, set_token_env):
        """白名单 Origin 的 OPTIONS 预检无 token → 200 + ACAO（设计假设 #10）。

        浏览器跨域预检【不会】携带自定义头 X-InkFlow-Token；token
        中间件必须放行 preflight（CORS 外层短路或显式豁免 OPTIONS），
        否则浏览器拿不到 ACAO、真实请求永远不会发出。
        """
        resp = client.options(
            "/health",
            headers={
                "Origin": WHITELISTED_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == WHITELISTED_ORIGIN
