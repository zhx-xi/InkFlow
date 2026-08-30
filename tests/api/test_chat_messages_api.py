"""#744 chat 消息持久化 API RED 契约测试 — /api/v1/chat/messages + /conversations（多线程）。

父侧定稿契约（见 .hermes/plans/contract-744.md）:
- 新 router: backend/src/inkflow/api/routers/chat_messages.py（prefix=/api/v1/chat）
- 依赖注入点: get_chat_message_service **定义于 router 模块内**（禁 Depends 形态——
  handler 内 `svc = get_chat_message_service(db)` 模块级裸名获取，patch 才可拦截）
- POST /api/v1/chat/messages → 201
  请求体: {project_id: UUID str, conversation_id: UUID str, role: "user"|"ai",
  content: str, intent?: "content"|"conversation"|null}
  响应: {id, project_id, conversation_id, role, content, intent, created_at}
  * content trim 后为空 → 422，detail == "chat 消息内容不能为空"
  * 服务调用: svc.add_message(<ChatMessageCreate>)（含 conversation_id 逐字）
- GET /api/v1/chat/messages?conversation_id=X&offset=0&limit=50 → 200
  响应: {items: [ChatMessage...按时间升序], total, offset, limit}
  * conversation_id 必填（缺 → 422）
  * 服务调用: svc.list_messages(conversation_id=..., offset=..., limit=...)
- GET /api/v1/chat/conversations?include_deleted= → 200
  响应: {items: [{conversation_id, project_id, project_name, last_message,
  message_count, is_deleted, updated_at}], total}（按 updated_at 降序）
- POST /api/v1/chat/conversations（body {project_id}）→ 201 创建新线程
  响应: {conversation_id, project_id, created_at, is_deleted:false}
  服务调用: svc.create_conversation(project_id)
"""

from __future__ import annotations

import sys
import uuid
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app  # 必须先于 stub 行（GREEN 时真模块已注册进 sys.modules）

# RED 逃生门不变：chat_messages 模块缺失时注入同路径 stub（GREEN 后 setdefault 不覆盖真模块）
_stub_chat_router = ModuleType("inkflow.api.routers.chat_messages")
_stub_chat_router.get_chat_message_service = MagicMock()
sys.modules.setdefault("inkflow.api.routers.chat_messages", _stub_chat_router)

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CONV_ID = uuid.UUID("22345678-1234-5678-1234-567812345678")
CONTENT = "你好，请续写第三章。"
CREATED_AT = "2026-08-20T10:00:00Z"


def _client():
    """构造 ASGI 测试客户端（镜像 test_f27_agentic_api.py，不触发 lifespan）。"""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _message_dict(**overrides) -> dict:
    """ChatMessage 响应 dict（含 conversation_id）。"""
    msg = {
        "id": str(uuid.uuid4()),
        "project_id": str(PROJECT_ID),
        "conversation_id": str(CONV_ID),
        "role": "user",
        "content": CONTENT,
        "intent": None,
        "created_at": CREATED_AT,
    }
    msg.update(overrides)
    return msg


def _conversation_dict(**overrides) -> dict:
    """conversations 聚合 dict（含 conversation_id，service 聚合结果形态）。"""
    conv = {
        "conversation_id": str(CONV_ID),
        "project_id": str(PROJECT_ID),
        "project_name": "测试项目",
        "last_message": CONTENT,
        "message_count": 3,
        "is_deleted": False,
        "updated_at": CREATED_AT,
    }
    conv.update(overrides)
    return conv


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


def _call_arg(call, name: str, index: int) -> object:
    """宽松取参：位置或关键字。"""
    args, kwargs = call.args, call.kwargs
    return args[index] if len(args) > index else kwargs[name]


@pytest.fixture
def chat_svc():
    """Mock ChatMessageService——全方法显式默认值（裸 AsyncMock 分支陷阱防护）。"""
    svc = MagicMock()
    svc.add_message = AsyncMock(return_value=_message_dict())
    svc.list_messages = AsyncMock(return_value=([], 0))
    svc.list_messages_by_conversation = AsyncMock(return_value=([], 0))
    svc.list_conversations = AsyncMock(return_value=[])
    svc.create_conversation = AsyncMock(
        return_value={
            "conversation_id": str(CONV_ID),
            "project_id": str(PROJECT_ID),
            "created_at": CREATED_AT,
            "is_deleted": False,
        }
    )
    svc.get_or_create_conversation = AsyncMock(
        return_value={
            "id": str(CONV_ID),
            "project_id": str(PROJECT_ID),
            "created_at": CREATED_AT,
            "is_deleted": False,
        }
    )
    svc.archive_conversation = AsyncMock(return_value=True)
    svc.force_delete_conversation = AsyncMock(return_value=True)
    svc.restore_conversation = AsyncMock(return_value=True)
    return svc


@pytest.fixture
def override_chat_svc(chat_svc):
    """@patch router 模块级 get_chat_message_service → mock ChatMessageService。"""
    with patch(
        "inkflow.api.routers.chat_messages.get_chat_message_service",
        return_value=chat_svc,
    ):
        yield chat_svc


class TestPostMessageEndpoint:
    """POST /api/v1/chat/messages — 追加 chat 消息（conversation_id 必填）。"""

    pytestmark = pytest.mark.asyncio  # 根目录 STRICT 模式显式标记（backend pyproject 为 auto）

    async def test_post_message_201(self, chat_svc, override_chat_svc):
        msg = _message_dict(role="user", content=CONTENT, intent="conversation")
        chat_svc.add_message.return_value = msg
        async with _client() as client:
            resp = await client.post(
                "/api/v1/chat/messages",
                json={
                    "project_id": str(PROJECT_ID),
                    "conversation_id": str(CONV_ID),
                    "role": "user",
                    "content": CONTENT,
                    "intent": "conversation",
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert uuid.UUID(data["id"]) is not None
        assert data["id"] == msg["id"]
        assert data["project_id"] == str(PROJECT_ID)
        assert data["conversation_id"] == str(CONV_ID)
        assert data["role"] == "user"
        assert data["content"] == CONTENT
        assert data["intent"] == "conversation"
        assert data["created_at"] == CREATED_AT
        call = chat_svc.add_message.await_args
        assert call is not None
        arg = _call_arg(call, "data", 0)
        from inkflow.domain.models.chat_message import ChatMessageCreate

        assert isinstance(arg, ChatMessageCreate)
        assert arg.project_id == PROJECT_ID
        assert arg.conversation_id == CONV_ID
        assert arg.role == "user"
        assert arg.content == CONTENT
        assert arg.intent == "conversation"

    async def test_post_message_422_blank_content(self, chat_svc):
        async with _client() as client:
            resp = await client.post(
                "/api/v1/chat/messages",
                json={
                    "project_id": str(PROJECT_ID),
                    "conversation_id": str(CONV_ID),
                    "role": "user",
                    "content": "   ",
                },
            )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "chat 消息内容不能为空"

    async def test_post_message_422_invalid_role(self, chat_svc):
        async with _client() as client:
            resp = await client.post(
                "/api/v1/chat/messages",
                json={
                    "project_id": str(PROJECT_ID),
                    "conversation_id": str(CONV_ID),
                    "role": "system",
                    "content": CONTENT,
                },
            )
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)


class TestListMessagesEndpoint:
    """GET /api/v1/chat/messages — 线程消息列表（按时间升序，分页透传）。"""

    pytestmark = pytest.mark.asyncio  # 根目录 STRICT 模式显式标记

    async def test_list_messages_200(self, chat_svc, override_chat_svc):
        msg = _message_dict()
        chat_svc.list_messages_by_conversation.return_value = ([msg], 1)
        async with _client() as client:
            resp = await client.get(
                "/api/v1/chat/messages",
                params={"conversation_id": str(CONV_ID), "offset": 0, "limit": 50},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == [msg]
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 50
        call = chat_svc.list_messages_by_conversation.await_args
        assert call is not None
        assert _call_arg(call, "conversation_id", 0) == CONV_ID
        assert _call_arg(call, "offset", 1) == 0
        assert _call_arg(call, "limit", 2) == 50

    async def test_list_messages_422_missing_conversation_id(self, chat_svc):
        async with _client() as client:
            resp = await client.get("/api/v1/chat/messages")
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)


class TestConversationsEndpoint:
    """GET /api/v1/chat/conversations — 会话页聚合列表（多线程，按 updated_at 降序）。"""

    pytestmark = pytest.mark.asyncio  # 根目录 STRICT 模式显式标记

    async def test_list_conversations_200(self, chat_svc, override_chat_svc):
        conv = _conversation_dict()
        chat_svc.list_conversations.return_value = [conv]
        async with _client() as client:
            resp = await client.get("/api/v1/chat/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == [conv]
        assert data["total"] == 1
        for key in (
            "conversation_id",
            "project_id",
            "project_name",
            "last_message",
            "message_count",
            "is_deleted",
            "updated_at",
        ):
            assert key in data["items"][0]
        chat_svc.list_conversations.assert_awaited_once()

    async def test_list_conversations_include_deleted_200(
        self, chat_svc, override_chat_svc
    ):
        conv = _conversation_dict()
        chat_svc.list_conversations.return_value = [conv]
        async with _client() as client:
            resp = await client.get(
                "/api/v1/chat/conversations",
                params={"include_deleted": "true"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == [conv]
        assert data["total"] == 1
        chat_svc.list_conversations.assert_awaited_once_with(include_deleted=True)

    async def test_list_conversations_include_deleted_has_is_deleted_key(
        self, chat_svc, override_chat_svc
    ):
        conv = _conversation_dict(is_deleted=True)
        chat_svc.list_conversations.return_value = [conv]
        async with _client() as client:
            resp = await client.get(
                "/api/v1/chat/conversations",
                params={"include_deleted": "true"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "is_deleted" in data["items"][0]
        assert data["items"][0]["is_deleted"] is True


class TestCreateConversationEndpoint:
    """POST /api/v1/chat/conversations — 创建新线程（#744 归档后开新）。"""

    pytestmark = pytest.mark.asyncio  # 根目录 STRICT 模式显式标记

    async def test_create_conversation_201(self, chat_svc, override_chat_svc):
        async with _client() as client:
            resp = await client.post(
                "/api/v1/chat/conversations",
                json={"project_id": str(PROJECT_ID)},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["conversation_id"] == str(CONV_ID)
        assert data["project_id"] == str(PROJECT_ID)
        assert data["is_deleted"] is False
        chat_svc.create_conversation.assert_awaited_once_with(PROJECT_ID)

    async def test_create_conversation_422_missing_project(self, chat_svc):
        async with _client() as client:
            resp = await client.post("/api/v1/chat/conversations", json={})
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    def test_chat_create_conversation_route_registered_in_app(self):
        paths = _chat_route_paths()
        assert any(
            p.endswith("/chat/conversations") for p in paths
        ), f"缺 chat create conversation 路由: {sorted(paths)}"


class TestChatAssembly:
    """#245 装配契约：chat_messages router 必须在真实 app 注册。"""

    def test_chat_messages_routes_registered_in_app(self):
        paths = _chat_route_paths()
        assert "/api/v1/chat/messages" in paths, f"缺 chat messages 路由: {paths}"

    def test_chat_conversations_route_registered_in_app(self):
        paths = _chat_route_paths()
        assert "/api/v1/chat/conversations" in paths, f"缺 conversations 路由: {paths}"


class TestRestoreConversationEndpoint:
    """#744 POST /api/v1/chat/conversations/{conversation_id}/restore — 线程恢复。"""

    pytestmark = pytest.mark.asyncio  # 根目录 STRICT 模式显式标记

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

    def test_chat_restore_conversation_route_registered_in_app(self):
        paths = _chat_route_paths()
        assert any(
            p.endswith("/chat/conversations/{conversation_id}/restore") for p in paths
        ), f"缺 chat restore conversation 路由: {sorted(paths)}"
