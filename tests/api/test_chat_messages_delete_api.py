"""#744 chat 消息删除/归档/恢复 API RED 契约测试 — DELETE/POST /api/v1/chat/messages/{id} + /conversations/{conversation_id}。

父侧定稿契约（见 .hermes/plans/contract-744.md，镜像 sessions.py 两级删除先例）:
- DELETE /api/v1/chat/messages/{message_id}（无 force）→ 204 归档（软删 is_deleted=true）
- DELETE /api/v1/chat/messages/{message_id}?force=true → 204 真删
- POST /api/v1/chat/messages/{message_id}/restore → 200 恢复（返回 ChatMessage）
- DELETE /api/v1/chat/conversations/{conversation_id}（无 force）→ 204 归档线程
- DELETE /api/v1/chat/conversations/{conversation_id}?force=true → 204 真删线程
- POST /api/v1/chat/conversations/{conversation_id}/restore → 200 恢复线程
- 服务方法: archive_message/force_delete_message/restore_message（消息级）
  + archive_conversation/force_delete_conversation/restore_conversation（会话级，bool）
- 不存在 id → 404「chat 消息不存在」/「chat 会话不存在」
- 依赖注入点: get_chat_message_service 定义于 router 模块内（禁 Depends 形态）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app  # router 模块已注册，无需 stub

pytestmark = pytest.mark.asyncio  # F27 实测必写（asyncio_mode=auto 双保险）

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CONV_ID = uuid.UUID("22345678-1234-5678-1234-567812345678")
CREATED_AT = "2026-08-20T10:00:00Z"


def _client() -> AsyncClient:
    """构造 ASGI 测试客户端（镜像 test_chat_messages_api.py，不触发 lifespan）。"""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _message_dict(**overrides) -> dict:
    """ChatMessage 响应 dict（含 conversation_id）。"""
    msg = {
        "id": str(uuid.uuid4()),
        "project_id": str(PROJECT_ID),
        "conversation_id": str(CONV_ID),
        "role": "user",
        "content": "你好，请续写第三章。",
        "intent": None,
        "created_at": CREATED_AT,
    }
    msg.update(overrides)
    return msg


def _chat_route_paths() -> set[str]:
    """真实 app 已注册的 chat 相关路由路径（#245 装配契约）。"""
    paths: set[str] = set()
    for route in app.routes:
        if hasattr(route, "path"):
            paths.add(str(getattr(route, "path", "")))
        expand = getattr(route, "effective_route_contexts", None)
        if callable(expand):
            for ctx in expand():
                paths.add(str(getattr(ctx, "path", "")))
    return {p for p in paths if p.startswith("/api/v1/chat")}


@pytest.fixture
def chat_svc() -> MagicMock:
    """Mock ChatMessageService——全方法显式默认值（裸 AsyncMock 分支陷阱防护）。"""
    svc = MagicMock()
    svc.add_message = AsyncMock(return_value=_message_dict())
    svc.list_messages = AsyncMock(return_value=([], 0))
    svc.list_messages_by_conversation = AsyncMock(return_value=([], 0))
    svc.list_conversations = AsyncMock(return_value=[])
    svc.create_conversation = AsyncMock(return_value=_message_dict())
    svc.archive_message = AsyncMock(return_value=True)
    svc.force_delete_message = AsyncMock(return_value=True)
    svc.restore_message = AsyncMock(return_value=_message_dict())
    # #744 会话级（per-conversation）归档/真删/恢复
    svc.archive_conversation = AsyncMock(return_value=True)
    svc.force_delete_conversation = AsyncMock(return_value=True)
    svc.restore_conversation = AsyncMock(return_value=True)
    return svc


@pytest.fixture
def override_chat_svc(chat_svc: MagicMock) -> MagicMock:
    """@patch router 模块级 get_chat_message_service → mock ChatMessageService。"""
    with patch(
        "inkflow.api.routers.chat_messages.get_chat_message_service",
        return_value=chat_svc,
    ):
        yield chat_svc


class TestDeleteMessageEndpoint:
    """DELETE /api/v1/chat/messages/{id} — 默认归档（软删）。"""

    async def test_delete_archive_204(self, chat_svc, override_chat_svc):
        message_id = uuid.uuid4()
        async with _client() as client:
            resp = await client.delete(f"/api/v1/chat/messages/{message_id}")
        assert resp.status_code == 204
        chat_svc.archive_message.assert_awaited_once_with(message_id)

    async def test_delete_force_204(self, chat_svc, override_chat_svc):
        message_id = uuid.uuid4()
        async with _client() as client:
            resp = await client.delete(f"/api/v1/chat/messages/{message_id}?force=true")
        assert resp.status_code == 204
        chat_svc.force_delete_message.assert_awaited_once_with(message_id)

    async def test_delete_not_found_404(self, chat_svc, override_chat_svc):
        chat_svc.archive_message = AsyncMock(return_value=False)
        async with _client() as client:
            resp = await client.delete(f"/api/v1/chat/messages/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "chat 消息不存在"


class TestRestoreMessageEndpoint:
    """POST /api/v1/chat/messages/{id}/restore — 解除归档。"""

    async def test_restore_200(self, chat_svc, override_chat_svc):
        message_id = uuid.uuid4()
        msg = _message_dict(id=str(message_id))
        chat_svc.restore_message = AsyncMock(return_value=msg)
        async with _client() as client:
            resp = await client.post(f"/api/v1/chat/messages/{message_id}/restore")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(message_id)
        assert data["project_id"] == str(PROJECT_ID)
        assert data["conversation_id"] == str(CONV_ID)
        chat_svc.restore_message.assert_awaited_once_with(message_id)

    async def test_restore_not_found_404(self, chat_svc, override_chat_svc):
        chat_svc.restore_message = AsyncMock(return_value=None)
        async with _client() as client:
            resp = await client.post(f"/api/v1/chat/messages/{uuid.uuid4()}/restore")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "chat 消息不存在"


class TestChatDeleteAssembly:
    """#245 装配契约：chat 删除/恢复路由必须在真实 app 注册。"""

    def test_chat_delete_route_registered_in_app(self):
        paths = _chat_route_paths()
        assert any(
            p.endswith("/chat/messages/{message_id}") for p in paths
        ), f"缺 chat delete 路由: {sorted(paths)}"

    def test_chat_restore_route_registered_in_app(self):
        paths = _chat_route_paths()
        assert any(
            p.endswith("/chat/messages/{message_id}/restore") for p in paths
        ), f"缺 chat restore 路由: {sorted(paths)}"


class TestDeleteConversationEndpoint:
    """#744 DELETE /api/v1/chat/conversations/{conversation_id} — 线程级归档/真删。"""

    async def test_delete_conversation_archive_204(self, chat_svc, override_chat_svc):
        async with _client() as client:
            resp = await client.delete(f"/api/v1/chat/conversations/{CONV_ID}")
        assert resp.status_code == 204
        chat_svc.archive_conversation.assert_awaited_once_with(CONV_ID)

    async def test_delete_conversation_force_204(self, chat_svc, override_chat_svc):
        async with _client() as client:
            resp = await client.delete(f"/api/v1/chat/conversations/{CONV_ID}?force=true")
        assert resp.status_code == 204
        chat_svc.force_delete_conversation.assert_awaited_once_with(CONV_ID)

    async def test_delete_conversation_not_found_404(self, chat_svc, override_chat_svc):
        chat_svc.archive_conversation = AsyncMock(return_value=False)
        async with _client() as client:
            resp = await client.delete(f"/api/v1/chat/conversations/{CONV_ID}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "chat 会话不存在"


class TestRestoreConversationEndpointDelete:
    """#744 POST /api/v1/chat/conversations/{conversation_id}/restore — 线程恢复。"""

    async def test_restore_conversation_200(self, chat_svc, override_chat_svc):
        chat_svc.restore_conversation = AsyncMock(return_value=True)
        async with _client() as client:
            resp = await client.post(f"/api/v1/chat/conversations/{CONV_ID}/restore")
        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_id"] == str(CONV_ID)
        assert data["is_deleted"] is False
        chat_svc.restore_conversation.assert_awaited_once_with(CONV_ID)

    async def test_restore_conversation_not_found_404(self, chat_svc, override_chat_svc):
        chat_svc.restore_conversation = AsyncMock(return_value=False)
        async with _client() as client:
            resp = await client.post(f"/api/v1/chat/conversations/{CONV_ID}/restore")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "chat 会话不存在"


# ══════════════════════════════════════════════════════════════════════════
# #177 覆盖率盲区补测: 直接调用 router handler（不经 ASGITransport）——coverage.py
# 对 ASGI/AsyncClient 内 handler 执行存在统计盲区，直接调用可正常记录。
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def direct_svc() -> MagicMock:
    """直接调用 router handler 用的 mock service（全方法显式默认值）。"""
    svc = MagicMock()
    svc.add_message = AsyncMock(return_value=_message_dict())
    svc.list_messages = AsyncMock(return_value=([], 0))
    svc.list_messages_by_conversation = AsyncMock(return_value=([], 0))
    svc.list_conversations = AsyncMock(return_value=[])
    svc.create_conversation = AsyncMock(return_value=_message_dict())
    svc.archive_message = AsyncMock(return_value=True)
    svc.force_delete_message = AsyncMock(return_value=True)
    svc.restore_message = AsyncMock(return_value=_message_dict())
    svc.archive_conversation = AsyncMock(return_value=True)
    svc.force_delete_conversation = AsyncMock(return_value=True)
    svc.restore_conversation = AsyncMock(return_value=True)
    return svc


@pytest.fixture
def patch_direct_svc(direct_svc):
    """patch router 模块级 get_chat_message_service → mock（直接调用 handler 用）。"""
    with patch(
        "inkflow.api.routers.chat_messages.get_chat_message_service",
        return_value=direct_svc,
    ):
        yield direct_svc


class TestDirectRouterCoverage:
    """直接调用 router handler 覆盖（#177：ASGI 盲区）。"""

    async def test_post_message_direct(self, patch_direct_svc):
        from inkflow.api.routers.chat_messages import ChatMessagePostRequest, post_message

        data = ChatMessagePostRequest(
            project_id=PROJECT_ID, conversation_id=CONV_ID, role="user", content="你好"
        )
        result = await post_message(data, db=None)
        assert result["id"] == patch_direct_svc.add_message.return_value["id"]

    async def test_post_message_blank_content_422_direct(self, patch_direct_svc):
        from fastapi import HTTPException

        from inkflow.api.routers.chat_messages import ChatMessagePostRequest, post_message

        with pytest.raises(HTTPException) as ei:
            await post_message(
                ChatMessagePostRequest(
                    project_id=PROJECT_ID, conversation_id=CONV_ID, role="user", content="   "
                ),
                db=None,
            )
        assert ei.value.status_code == 422

    async def test_list_messages_direct(self, patch_direct_svc):
        from inkflow.api.routers.chat_messages import list_messages

        result = await list_messages(conversation_id=CONV_ID, offset=0, limit=50, db=None)
        assert result["total"] == 0
        assert result["items"] == []

    async def test_list_conversations_direct(self, patch_direct_svc):
        from inkflow.api.routers.chat_messages import list_conversations

        result = await list_conversations(db=None)
        assert result["total"] == 0

    async def test_delete_message_archive_direct(self, patch_direct_svc):
        from inkflow.api.routers.chat_messages import delete_message

        mid = uuid.uuid4()
        await delete_message(str(mid), force=False, db=None)
        patch_direct_svc.archive_message.assert_awaited_once_with(mid)

    async def test_delete_message_force_direct(self, patch_direct_svc):
        from inkflow.api.routers.chat_messages import delete_message

        mid = uuid.uuid4()
        await delete_message(str(mid), force=True, db=None)
        patch_direct_svc.force_delete_message.assert_awaited_once_with(mid)

    async def test_delete_message_invalid_uuid_404_direct(self, patch_direct_svc):
        from fastapi import HTTPException

        from inkflow.api.routers.chat_messages import delete_message

        with pytest.raises(HTTPException) as ei:
            await delete_message("not-a-uuid", force=False, db=None)
        assert ei.value.status_code == 404

    async def test_restore_message_direct(self, patch_direct_svc):
        from inkflow.api.routers.chat_messages import restore_message

        mid = uuid.uuid4()
        result = await restore_message(str(mid), db=None)
        assert result["id"] == patch_direct_svc.restore_message.return_value["id"]
        patch_direct_svc.restore_message.assert_awaited_once_with(mid)

    async def test_restore_message_none_404_direct(self, patch_direct_svc):
        from fastapi import HTTPException

        from inkflow.api.routers.chat_messages import restore_message

        patch_direct_svc.restore_message = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as ei:
            await restore_message(str(uuid.uuid4()), db=None)
        assert ei.value.status_code == 404

    async def test_delete_conversation_direct(self, patch_direct_svc):
        from inkflow.api.routers.chat_messages import delete_conversation

        await delete_conversation(str(CONV_ID), force=False, db=None)
        patch_direct_svc.archive_conversation.assert_awaited_once_with(CONV_ID)

    async def test_delete_conversation_force_direct(self, patch_direct_svc):
        from inkflow.api.routers.chat_messages import delete_conversation

        await delete_conversation(str(CONV_ID), force=True, db=None)
        patch_direct_svc.force_delete_conversation.assert_awaited_once_with(CONV_ID)

    async def test_delete_conversation_invalid_uuid_404_direct(self, patch_direct_svc):
        from fastapi import HTTPException

        from inkflow.api.routers.chat_messages import delete_conversation

        with pytest.raises(HTTPException) as ei:
            await delete_conversation("not-a-uuid", force=False, db=None)
        assert ei.value.status_code == 404

    async def test_delete_conversation_not_found_404_direct(self, patch_direct_svc):
        from fastapi import HTTPException

        from inkflow.api.routers.chat_messages import delete_conversation

        patch_direct_svc.archive_conversation = AsyncMock(return_value=False)
        with pytest.raises(HTTPException) as ei:
            await delete_conversation(str(uuid.uuid4()), force=False, db=None)
        assert ei.value.status_code == 404

    async def test_restore_message_invalid_uuid_404_direct(self, patch_direct_svc):
        from fastapi import HTTPException

        from inkflow.api.routers.chat_messages import restore_message

        with pytest.raises(HTTPException) as ei:
            await restore_message("not-a-uuid", db=None)
        assert ei.value.status_code == 404

    async def test_delete_message_not_found_404_direct(self, patch_direct_svc):
        from fastapi import HTTPException

        from inkflow.api.routers.chat_messages import delete_message

        patch_direct_svc.archive_message = AsyncMock(return_value=False)
        with pytest.raises(HTTPException) as ei:
            await delete_message(str(uuid.uuid4()), force=False, db=None)
        assert ei.value.status_code == 404

    async def test_message_to_json_non_dict_branch(self):
        """_message_to_json 收到 ChatMessage（非 dict）→ model_dump 分支（#177 L40 覆盖）。"""
        from datetime import UTC, datetime

        from inkflow.api.routers.chat_messages import _message_to_json
        from inkflow.domain.models.chat_message import ChatMessage

        msg = ChatMessage(
            id=uuid.uuid4(),
            project_id=PROJECT_ID,
            conversation_id=CONV_ID,
            role="user",
            content="你好",
            intent=None,
            created_at=datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC),
        )
        result = _message_to_json(msg)
        assert result["content"] == "你好"
        assert result["project_id"] == str(PROJECT_ID)
