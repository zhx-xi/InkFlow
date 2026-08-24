"""#631 memory summaries 随机 UUID 128 位溢出 RED 契约测试 — 真实 DB 轨.

（#631 RED 契约：随机 UUID → DELETE 404 / GET 200 空结构（修复前均 500）真实 DB 轨）

issue #631（rc2 验证发现）：DELETE/GET /api/v1/agent/memory/summaries?project_id=<随机 UUID>
→ 500 OverflowError。根因：service 层 get_summaries/remove_summaries 用 project_id.int
（128 位）调 project_repo.get，超出 SQLite 64 位 INTEGER 绑定范围 → OverflowError。

契约（本项目「项目缺失」语义 = 随机 UUID 等价语义）：
- DELETE /api/v1/agent/memory/summaries?project_id=<随机 uuid4> → 404「项目不存在」
  （remove_summaries 对项目缺失 raise ProjectNotFoundError → router 映射 404）
- GET /api/v1/agent/memory/summaries?project_id=<随机 uuid4> → 200 空结构
  {"project_id": str(project_id), "project": None, "user": None}
  （get_summaries 对项目缺失返回空结构——spec §7「项目缺失 → 空结构」，无 404 路径）

测试形态：真实 DB 轨（client + db_session + override_get_db，镜像
test_chat_messages_overflow_api.py），不 patch get_memory_service —— 真实 service +
真实 repo 走 128 位 int 绑定路径。

RED 预期（修复前当前实现）：GET/DELETE 全部 500 ≠ 期望码/空结构 → FAIL；
对照用例（有效项目 GET → 200）PASS —— 证明 DB 轨链路正常，RED 信号纯粹来自随机 UUID
的 128 位溢出。
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

DETAIL_PROJECT_NOT_FOUND = "项目不存在"
"""项目不存在 404 detail（character_errors.ProjectNotFoundError 默认文案）。"""


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式，镜像 test_chat_messages_overflow_api.py）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.api
class TestMemorySummaryOverflowDelete:
    """#631 随机 UUID DELETE summaries → 404「项目不存在」（真实 DB 轨）。"""

    async def test_delete_summaries_random_uuid_404(
        self, client, db_session, override_get_db
    ):
        """DELETE summaries 随机 UUID project_id → 404「项目不存在」。"""
        project_id = uuid.uuid4()
        resp = await client.delete(
            f"/api/v1/agent/memory/summaries?project_id={project_id}"
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_PROJECT_NOT_FOUND


@pytest.mark.api
class TestMemorySummaryOverflowGet:
    """#631 随机 UUID GET summaries → 200 空结构（真实 DB 轨）。"""

    async def test_get_summaries_random_uuid_empty_structure(
        self, client, db_session, override_get_db
    ):
        """GET summaries 随机 UUID project_id → 200 空结构（project/user=None）。"""
        project_id = uuid.uuid4()
        resp = await client.get(
            f"/api/v1/agent/memory/summaries?project_id={project_id}"
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "project_id": str(project_id),
            "project": None,
            "user": None,
        }


@pytest.mark.api
class TestExistingProjectControl:
    """对照用例：有效项目（小 int id）GET summaries → 200（链路正常）。

    证明真实 DB 轨 + override_get_db 链路正常；RED 信号纯粹来自随机 UUID 的
    128 位 int 绑定溢出（修复前 random 用例 500、本用例 200——区分「轨道坏」vs
    「仅溢出错误」）。
    """

    async def test_get_summaries_existing_project_200(
        self, client, db_session, override_get_db, sample_project
    ):
        """预置有效项目（sample_project fixture）→ GET summaries → 200 空结构。"""
        project_id = uuid.UUID(int=sample_project.id)
        resp = await client.get(
            f"/api/v1/agent/memory/summaries?project_id={project_id}"
        )
        assert resp.status_code == 200
