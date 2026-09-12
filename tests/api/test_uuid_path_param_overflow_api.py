"""#1106 UUID 路径参数 128 位溢出 RED 契约测试 — 真实 DB 轨.

（#1106 RED 契约：随机 UUID 路径参数 → 404（修复前 500）真实 DB 轨）

issue #1106（#1093 发现场景）：对使用 UUID 路径参数的端点传入「格式合法但非仓库
主键映射」的 UUID（如 uuid.uuid4()）→ 500：

    OverflowError: Python int too large to convert to SQLite INTEGER

根因：
- service 层 `_to_int_id` 直接 `return value.int`（128 位）
- 仓储映射约定是 `uuid.UUID(int=orm.id)`（小整数可容纳），外部任意 UUID 溢出
- router 层 `_parse_id` 只校验格式，不校验取值范围

契约（本项目「资源缺失」语义 = 随机 UUID 等价语义，族内先例 #578/#631）：
- 所有 UUID 路径端点：随机 uuid4（128 位，必不存在）→ 404，非 500
- 合法小整数 UUID 但不存在 → 404
- 真实 id（uuid.UUID(int=orm.id)）→ 200（对照，链路正常）
- 反例守护：小整数 UUID 不被误判为超范围

测试形态：真实 DB 轨（client + db_session + override_get_db），不 patch service ——
真实 service + 真实 repo 走 128 位 int 绑定路径（镜像 test_chat_messages_overflow_api.py）。

RED 预期（修复前当前实现）：带 <id> 占位的 GET 端点全部 500 ≠ 404 → FAIL；
对照用例（小整数 UUID → 404「不存在」而非 500）PASS —— 证明 DB 轨链路正常，
RED 信号纯粹来自随机 UUID 的 128 位溢出。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app

pytestmark = pytest.mark.asyncio  # F27 实测必写（asyncio_mode=auto 双保险）

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 直通（无 token 模式）。"""


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式，镜像 test_chat_messages_overflow_api.py）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# 一族代表端点（GET + <id> 占位）：覆盖各限界上下文，router 各自持有 _parse_id 副本。
# 只列「资源缺失 → 404」语义的详情端点；避免 list/嵌套路径引入额外前置校验噪声。
OVERFLOW_ENDPOINTS = [
    "/api/v1/maps/{id}",
    "/api/v1/characters/{id}",
    "/api/v1/foreshadowings/{id}",
    "/api/v1/outlines/{id}",
    "/api/v1/world-settings/{id}",
    "/api/v1/timeline/events/{id}",
    "/api/v1/knowledge-relations/{id}",
]
"""**id 占位的一族详情端点（随机 UUID → 应 404 而非 500）。

注：/knowledge-relations/{relation_id} 对应 router `knowledge_graph.py:157`；
早期草稿误写为 /knowledge-graph/entities/{id}（该路由不存在，恒 404 → 空过用例）。"""


@pytest.mark.api
@pytest.mark.parametrize("template", OVERFLOW_ENDPOINTS)
class TestUuidPathParamOverflow:
    """#1106 随机 UUID（128 位）路径参数 → 404 契约（真实 DB 轨）。

    修复前（当前 main）：真实 repo 绑定 128 位 int → SQLite OverflowError → 500 ≠ 404
    → 全部 FAIL（RED 成立）。
    """

    async def test_random_uuid_returns_404_not_500(
        self, client, db_session, override_get_db, template
    ):
        """随机 uuid4 路径参数 → 404（不得 500）。"""
        url = template.format(id=uuid.uuid4())
        resp = await client.get(url)
        assert resp.status_code == 404, (
            f"{url} 应为 404（资源不存在），实际 {resp.status_code}: {resp.text[:200]}"
        )

    async def test_small_int_uuid_not_found_returns_404(
        self, client, db_session, override_get_db, template
    ):
        """合法小整数 UUID（在 64 位范围内但不存在）→ 404（范围校验不得误伤）。"""
        url = template.format(id=uuid.UUID(int=987654321))
        resp = await client.get(url)
        assert resp.status_code == 404, (
            f"{url} 应为 404（资源不存在），实际 {resp.status_code}: {resp.text[:200]}"
        )
