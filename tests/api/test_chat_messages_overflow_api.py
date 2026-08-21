"""#578 chat 消息/会话删除 128 位 UUID 溢出 RED 契约测试 — 真实 DB 轨.

（#578 RED 契约：随机 UUID 404（修复前 500）真实 DB 轨）

issue #578（rc4 验证发现）：DELETE/restore chat 消息传随机（不存在）UUID →
500 OverflowError。根因：service 层 `_to_int_id` 将 128 位 UUID 转为 int，
超出 SQLite 64 位 INTEGER 绑定范围 → repo 执行时 OverflowError。契约要求
等价「不存在」→ 404。

本文件锁定修复方向（service 层预检：> 2^63-1 → 等价不存在），契约逐条：
- DELETE /api/v1/chat/messages/{id}（默认归档）→ 404「chat 消息不存在」
- DELETE /api/v1/chat/messages/{id}?force=true → 404「chat 消息不存在」
- POST /api/v1/chat/messages/{id}/restore → 404「chat 消息不存在」
- DELETE /api/v1/chat/conversations/{project_id} → 404「chat 会话不存在」
- DELETE /api/v1/chat/conversations/{project_id}?force=true → 404「chat 会话不存在」

测试形态：真实 DB 轨（client + db_session + override_get_db，镜像
test_agent_skill_duplicate_api.py），不 patch get_chat_message_service ——
真实 service + 真实 repo 走 128 位 int 绑定路径。

RED 预期（修复前当前实现）：5 条主契约全部 500 ≠ 404 → FAIL；对照用例
（预置小 int id 消息 → DELETE 204）PASS —— 证明 DB 轨链路正常，RED 信号
纯粹来自随机 UUID 的 128 位溢出。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.infrastructure.database.models.chat_message import ChatMessageORM

pytestmark = pytest.mark.asyncio  # F27 实测必写（asyncio_mode=auto 双保险）

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 直通（无 token 模式）。"""

DETAIL_MESSAGE_NOT_FOUND = "chat 消息不存在"
"""消息不存在 404 detail（#566 契约）。"""

DETAIL_CONVERSATION_NOT_FOUND = "chat 会话不存在"
"""会话不存在 404 detail（#566 契约）。"""


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式，镜像 test_agent_skill_duplicate_api.py）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.api
class TestChatMessageOverflowNotFound:
    """#578 随机 UUID（128 位）→ 404 契约（真实 DB 轨）。

    修复前（当前 main）：真实 repo 绑定 128 位 int → SQLite OverflowError →
    500 ≠ 404 → 全部 FAIL（RED 成立）。
    """

    async def test_delete_message_random_uuid_404(
        self, client, db_session, override_get_db
    ):
        """DELETE 消息（默认归档）随机 UUID → 404「chat 消息不存在」。"""
        message_id = uuid.uuid4()
        resp = await client.delete(f"/api/v1/chat/messages/{message_id}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_MESSAGE_NOT_FOUND

    async def test_delete_message_force_random_uuid_404(
        self, client, db_session, override_get_db
    ):
        """DELETE 消息 ?force=true 随机 UUID → 404「chat 消息不存在」。"""
        message_id = uuid.uuid4()
        resp = await client.delete(f"/api/v1/chat/messages/{message_id}?force=true")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_MESSAGE_NOT_FOUND

    async def test_restore_message_random_uuid_404(
        self, client, db_session, override_get_db
    ):
        """POST restore 随机 UUID → 404「chat 消息不存在」。"""
        message_id = uuid.uuid4()
        resp = await client.post(f"/api/v1/chat/messages/{message_id}/restore")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_MESSAGE_NOT_FOUND

    async def test_delete_conversation_random_uuid_404(
        self, client, db_session, override_get_db
    ):
        """DELETE 会话（默认归档）随机 UUID project_id → 404「chat 会话不存在」。"""
        project_id = uuid.uuid4()
        resp = await client.delete(f"/api/v1/chat/conversations/{project_id}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_CONVERSATION_NOT_FOUND

    async def test_delete_conversation_force_random_uuid_404(
        self, client, db_session, override_get_db
    ):
        """DELETE 会话 ?force=true 随机 UUID project_id → 404「chat 会话不存在」。"""
        project_id = uuid.uuid4()
        resp = await client.delete(f"/api/v1/chat/conversations/{project_id}?force=true")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_CONVERSATION_NOT_FOUND


@pytest.mark.api
class TestExistingMessageControl:
    """对照用例：已存在（小 int id）消息 DELETE → 204。

    证明真实 DB 轨 + override_get_db 链路正常；RED 信号纯粹来自随机 UUID
    的 128 位 int 绑定溢出（修复前后本用例均 PASS）。
    """

    async def test_delete_existing_message_204(
        self, client, db_session, override_get_db
    ):
        """预置一条 chat 消息（project_id 小 int）→ DELETE → 204。"""
        row = ChatMessageORM(project_id=1, role="user", content="你好")
        db_session.add(row)
        await db_session.commit()
        await db_session.refresh(row)

        # DB int id ↔ UUID.int 可逆（repo._orm_to_domain 同构）→ 合法 UUID 格式请求
        message_id = uuid.UUID(int=row.id)
        resp = await client.delete(f"/api/v1/chat/messages/{message_id}")
        assert resp.status_code == 204
