"""#869 S3f-T1：/docs /redoc docs 门控中间件 — API 测试契约（TDD RED 阶段）。

本文件为 `backend/src/inkflow/api/middleware/docs_gate.py`（NEW，G1 修复）+
`api/app.py`（注册中间件，docs_gate 注册在 token_auth 之后 = 外层）定义测试契约。

权威来源：.hermes/plans/contract-s3f-t1.md §2.1（用例 1-8 逐字对齐）+
§1.1（行为矩阵 / debug 读取时机 / 注册顺序）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 测试方式：fastapi.testclient.TestClient 直连真实 app 对象（import
   inkflow.api.app），验证纯 HTTP 行为；与 tests/api 既有文件（test_token_auth.py
   等）共享同一 pytest 进程与 config 单例。

2. 行为矩阵（contract §1.1）：
   - config.debug=False → GET /docs /redoc（含子路径）→ 404
     {"detail": "Not Found"}（JSON，不暴露 debug 存在）；
   - config.debug=True → 透传 FastAPI 默认 Swagger/ReDoc 页（200 text/html）；
   - /openapi.json 与其余路径恒不受影响（快照 ci_cd/export_openapi.py 直调
     app.openapi() + gen:api 契约 + test_token_auth HTTPBearer scheme 用例依赖）。
   - docs 404 先于 token 401：非 debug /docs 无 token → 404（不是 401），
     证明 docs_gate 注册在 token_auth 之外层（§1.1 注册顺序契约：
     后注册者先执行，docs_gate 注册在 token_auth 之后）。

3. 【debug 读取时机——硬性契约】docs_gate 必须【每次请求时】读 config.debug，
   【禁止】import/实例化时缓存——同 token_auth 设计决策 #2。原因：本文件与
   tests/api/ 其他文件共享同一 pytest 进程，config 单例 import 顺序不可控；
   测试在 import 之后 monkeypatch.setattr 控制。注意 memory 坑：须
   `importlib.import_module("inkflow.core.config")` 取真模块（`import
   inkflow.core.config as cfg_mod` 会绑定到实例——inkflow.core 包内 from-import
   遮蔽子模块属性），再 setattr cfg_mod.config（单例实例）的 debug 属性；
   app.py 的 `from inkflow.core.config import config` 与中间件读到同一实例对象
   → 请求期生效。若实现改为启动时缓存，本文件通过/失败将取决于 pytest 收集
   顺序——不可接受的脆弱性。

4. 路径判定对齐 token_auth 前缀匹配：`path == p or path.startswith(p + "/")`
   （/docs 子路径亦须 404，非透传 HTML/401）。

RED 阶段预期（contract §2.1 标注）：
- 【R】用例 1/2/7（debug=False → 404 / docs 404 先于 token 401）：docs_gate
  未实现 → FastAPI 恒注册文档页 → 断言 404 得 200 → FAIL。
- 【G】用例 3/4/5/8（debug=True 透传 / openapi 不受影响）：当前即 PASS
  （既有 FastAPI 默认行为，守护合法）。
- 用例 6（/docs/x 前缀）：当前 FastAPI 未匹配路由自带 JSON 404 → 可能 PASS，
  守护前缀语义（GREEN 后由中间件显式返回同样 404）。
GREEN 阶段：docs_gate.py 按矩阵实现 + app.py 注册后全绿。
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app

# ── 契约常量 ──
ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（spec §2.3.1）：serve 启动时注入进程环境。"""

TEST_TOKEN = "test-token-s3f-t1"
"""测试固定 token：#7/#8 需 env 已设以验证 token 层参与顺序。"""


# ── Fixtures ──


@pytest.fixture
def client_factory(monkeypatch):
    """TestClient 工厂：按 debug 参数控制 config 单例后直连真实 app（contract §2.1）。

    monkeypatch.setattr(inkflow.core.config.config, "debug", X) + TestClient(app)。
    app 为模块级单例——docs_gate 每次请求时读 config.debug（设计假设 #3），
    单例复用无时序问题；TestClient 触发 lifespan → create_tables() 落 CWD
    ./inkflow.db，与 tests/api 既有基线一致（不规避）。
    """

    cfg_mod = importlib.import_module("inkflow.core.config")

    def _make(debug: bool) -> TestClient:
        monkeypatch.setattr(cfg_mod.config, "debug", debug)
        return TestClient(app)

    return _make


@pytest.fixture
def set_token_env(monkeypatch):
    """设置 INKFLOW_SERVER_TOKEN=TEST_TOKEN（#7/#8 token 参与场景）。

    monkeypatch 自动还原，测试间互不污染（同 test_token_auth.set_token_env）。
    """

    monkeypatch.setenv(ENV_TOKEN, TEST_TOKEN)
    return TEST_TOKEN


# ── docs 门控矩阵（contract §2.1）──


class TestDocsGate:
    """/docs /redoc 按 config.debug 门控；openapi 恒透传；docs 404 先于 token 401。"""

    def test_docs_404_when_not_debug(self, client_factory):
        """【R】debug=False：GET /docs → 404，body 不暴露 debug 存在。

        当前（无 docs_gate）FastAPI 恒注册 /docs → 200 HTML → FAIL（RED）。
        """
        client = client_factory(False)
        resp = client.get("/docs")
        assert resp.status_code == 404, f"非 debug 模式 /docs 应 404，实际 {resp.status_code}"
        assert resp.json() == {"detail": "Not Found"}
        assert "debug" not in resp.text.lower()

    def test_redoc_404_when_not_debug(self, client_factory):
        """【R】debug=False：GET /redoc → 404，body 不暴露 debug 存在。"""
        client = client_factory(False)
        resp = client.get("/redoc")
        assert resp.status_code == 404, f"非 debug 模式 /redoc 应 404，实际 {resp.status_code}"
        assert resp.json() == {"detail": "Not Found"}
        assert "debug" not in resp.text.lower()

    def test_docs_200_when_debug(self, client_factory):
        """【G】debug=True：GET /docs → 200 text/html（透传 FastAPI Swagger 页）。"""
        client = client_factory(True)
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")

    def test_redoc_200_when_debug(self, client_factory):
        """【G】debug=True：GET /redoc → 200 text/html（透传 FastAPI ReDoc 页）。"""
        client = client_factory(True)
        resp = client.get("/redoc")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")

    def test_openapi_json_unaffected(self, client_factory):
        """【G】debug=False：GET /openapi.json → 200 + info.title == "InkFlow API"。

        /openapi.json 恒透传——快照 ci_cd/export_openapi.py 直调 app.openapi()
        + gen:api 契约 + test_token_auth HTTPBearer scheme 用例依赖它，docs
        门控不得拦截。
        """
        client = client_factory(False)
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        assert resp.json()["info"]["title"] == "InkFlow API"

    def test_docs_subpath_prefix_404(self, client_factory):
        """【R】debug=False：GET /docs/x → 404（前缀匹配 startswith(p + "/")）。"""
        client = client_factory(False)
        resp = client.get("/docs/x")
        assert resp.status_code == 404, f"非 debug 模式 /docs 子路径应 404，实际 {resp.status_code}"
        assert resp.json() == {"detail": "Not Found"}

    def test_docs_404_precedes_token_401(self, client_factory, set_token_env):
        """【R】debug=False + token env 已设 + 无 token：GET /docs → 404（非 401）。

        证明 docs_gate 注册在 token_auth 之后（外层）：docs 404 先于 token 401。
        当前（无 docs_gate）token 中间件豁免 /docs → 200 → FAIL（RED）。
        """
        client = client_factory(False)
        resp = client.get("/docs")
        assert resp.status_code == 404, (
            f"非 debug /docs 应先于 token 401 返回 404，实际 {resp.status_code}"
        )

    def test_debug_docs_still_token_exempt(self, client_factory, set_token_env):
        """【G】debug=True + token env 已设 + 无 token：GET /docs → 200。

        debug 透传后 token 豁免语义不变（/docs 静态文档无数据面，spec §2.3.1）。
        """
        client = client_factory(True)
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
