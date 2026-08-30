"""#770 会话页架构 API RED 契约 — POST /chat/conversations title + PATCH 改名 + GET title。

父侧定稿契约（spec §17.3 + 任务书）：
- ConversationCreate 加 title（可选，上限 200，去空白）→ POST /api/v1/chat/conversations
  透传 title → 201 响应含 title（_conversation_to_json 序列化含 title）
- 新增 PATCH /api/v1/chat/conversations/{conversation_id}（body {title} 必填 1-200）
  * 成功 → 200 {conversation_id, title}
  * 会话不存在 → 404，detail == "chat 会话不存在"
  * title 超 200 → 422；空白 → 422
- GET /api/v1/chat/conversations items 每项含 title 字段（service 聚合 dict 透传——
  API 层为 passthrough 守卫；list 真契约在 unit 层 test_conversation_title.py 的
  repo 用例断言 items 含 title）

RED 形态（MODIFY 轨：src 均存在，收集成功）：
- POST 带 title：svc mock 返回真实 Conversation(title=...) → 模型无 title 字段
  构造 TypeError（GREEN 后经 _conversation_to_json 序列化含 title）
- POST 不带 title：真实 Conversation 构造成功 → 响应无 title 键 → KeyError
- PATCH 路由未注册 → 404 Not Found（状态/详情断言失败）
- GET items title：mock dict 含 title 透传 → 天然 GREEN（passthrough 守卫，
  按任务书注明「既有代码可过的断言属正常」）
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
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
TITLE = "第十二章 剑心蒙尘"
RENAME_TITLE = "改名后的标题"


def _client():
    """构造 ASGI 测试客户端（镜像 test_chat_messages_api.py，不触发 lifespan）。"""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _conversation_dict(**overrides) -> dict:
    """conversations 聚合 dict（service 聚合结果形态，含 title）。"""
    conv = {
        "conversation_id": str(CONV_ID),
        "project_id": str(PROJECT_ID),
        "project_name": "测试项目",
        "last_message": CONTENT,
        "message_count": 3,
        "is_deleted": False,
        "updated_at": CREATED_AT,
        "title": TITLE,
    }
    conv.update(overrides)
    return conv


def _conversation_entity(**overrides) -> object:
    """真实 Conversation 领域实体（svc mock 返回值）——走 _conversation_to_json 真实序列化路径。"""
    from inkflow.domain.models.conversation import Conversation

    base = {
        "id": CONV_ID,
        "project_id": PROJECT_ID,
        "created_at": datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC),
        "is_deleted": False,
    }
    base.update(overrides)
    return Conversation(**base)


def _chat_routes() -> dict[str, set[str]]:
    """真实 app 已注册的 chat 路由 path -> HTTP methods 集合（#245 装配契约）。

    路由经 _EffectiveRouteContext 包装，需 effective_route_contexts() 展开
    （镜像 test_chat_messages_api.py 的 _chat_route_paths 处理）。
    """
    routes: dict[str, set[str]] = {}
    for route in app.routes:
        expand = getattr(route, "effective_route_contexts", None)
        contexts = expand() if callable(expand) else [route]
        for ctx in contexts:
            path = str(getattr(ctx, "path", ""))
            methods = getattr(ctx, "methods", None)
            if path.startswith("/api/v1/chat") and methods:
                routes.setdefault(path, set()).update(methods)
    return routes


def _call_arg(call, name: str, index: int) -> object:
    """宽松取参：位置或关键字。"""
    args, kwargs = call.args, call.kwargs
    return args[index] if len(args) > index else kwargs[name]


@pytest.fixture
def chat_svc():
    """Mock ChatMessageService——全方法显式默认值（裸 AsyncMock 分支陷阱防护）。

    注意：create_conversation 默认 return_value=None，由用例按需覆盖——避免在
    fixture 装配期构造 Conversation(title=...)（RED 期模型无 title 字段会
    TypeError 污染全部用例的失败形态）。
    """
    svc = MagicMock()
    svc.list_conversations = AsyncMock(return_value=[])
    svc.create_conversation = AsyncMock(return_value=None)
    svc.rename_conversation = AsyncMock(return_value=True)
    return svc


@pytest.fixture
def override_chat_svc(chat_svc):
    """@patch router 模块级 get_chat_message_service → mock ChatMessageService。"""
    with patch(
        "inkflow.api.routers.chat_messages.get_chat_message_service",
        return_value=chat_svc,
    ):
        yield chat_svc


class TestCreateConversationTitle:
    """POST /api/v1/chat/conversations — title 可选透传 + _conversation_to_json 含 title。"""

    pytestmark = pytest.mark.asyncio  # 根目录 STRICT 模式显式标记（backend pyproject 为 auto）

    async def test_create_conversation_with_title_201(self, chat_svc, override_chat_svc):
        """带 title → 201 响应含 title；svc.create_conversation 收到 project_id + title。"""
        chat_svc.create_conversation.return_value = _conversation_entity(title=TITLE)
        async with _client() as client:
            resp = await client.post(
                "/api/v1/chat/conversations",
                json={"project_id": str(PROJECT_ID), "title": TITLE},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["conversation_id"] == str(CONV_ID)
        assert data["title"] == TITLE
        call = chat_svc.create_conversation.await_args
        assert call is not None
        assert _call_arg(call, "project_id", 0) == PROJECT_ID
        assert _call_arg(call, "title", 1) == TITLE

    async def test_create_conversation_without_title_default_empty_201(
        self, chat_svc, override_chat_svc
    ):
        """不带 title → 201 响应 title 默认 ""。"""
        chat_svc.create_conversation.return_value = _conversation_entity()
        async with _client() as client:
            resp = await client.post(
                "/api/v1/chat/conversations",
                json={"project_id": str(PROJECT_ID)},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["conversation_id"] == str(CONV_ID)
        assert data["title"] == ""

    async def test_create_conversation_title_over_200_422(self, chat_svc, override_chat_svc):
        """title 超 200 → 422（ConversationCreate 上限校验）。"""
        async with _client() as client:
            resp = await client.post(
                "/api/v1/chat/conversations",
                json={"project_id": str(PROJECT_ID), "title": "章" * 201},
            )
        assert resp.status_code == 422


class TestRenameConversationEndpoint:
    """PATCH /api/v1/chat/conversations/{conversation_id} — 会话改名（#770 新增）。"""

    pytestmark = pytest.mark.asyncio  # 根目录 STRICT 模式显式标记（backend pyproject 为 auto）

    async def test_rename_conversation_200(self, chat_svc, override_chat_svc):
        """改名成功 → 200 {conversation_id, title}；svc.rename_conversation 收到 title。"""
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/chat/conversations/{CONV_ID}",
                json={"title": RENAME_TITLE},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["conversation_id"] == str(CONV_ID)
        assert data["title"] == RENAME_TITLE
        call = chat_svc.rename_conversation.await_args
        assert call is not None
        assert _call_arg(call, "conversation_id", 0) == CONV_ID
        assert _call_arg(call, "title", 1) == RENAME_TITLE

    async def test_rename_conversation_not_found_404(self, chat_svc, override_chat_svc):
        """会话不存在 → 404 detail 含「chat 会话不存在」。"""
        chat_svc.rename_conversation = AsyncMock(return_value=False)
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/chat/conversations/{CONV_ID}",
                json={"title": RENAME_TITLE},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "chat 会话不存在"

    async def test_rename_title_over_200_422(self, chat_svc, override_chat_svc):
        """title 超 200 → 422。"""
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/chat/conversations/{CONV_ID}",
                json={"title": "章" * 201},
            )
        assert resp.status_code == 422

    async def test_rename_title_blank_422(self, chat_svc, override_chat_svc):
        """title 空白（纯空格）→ 422。"""
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/chat/conversations/{CONV_ID}",
                json={"title": "   "},
            )
        assert resp.status_code == 422


class TestChatConversationAssembly:
    """#245 装配契约：PATCH 改名路由必须在真实 app 注册（sync，不带 asyncio mark）。"""

    def test_chat_rename_conversation_route_registered_in_app(self):
        """PATCH 改名路由须在真实 app 注册（按方法区分，防 DELETE 误配）。"""
        routes = _chat_routes()
        assert "PATCH" in routes.get(
            "/api/v1/chat/conversations/{conversation_id}", set()
        ), f"缺 PATCH chat rename conversation 路由: {routes}"


class TestListConversationsTitleField:
    """GET /api/v1/chat/conversations — items 每项含 title（API 层 passthrough 守卫）。"""

    pytestmark = pytest.mark.asyncio  # 根目录 STRICT 模式显式标记（backend pyproject 为 auto）

    async def test_list_conversations_items_include_title(self, chat_svc, override_chat_svc):
        """items[0] 含 title 字段（repo 聚合含 title，经 service 透传）。"""
        chat_svc.list_conversations.return_value = [_conversation_dict()]
        async with _client() as client:
            resp = await client.get("/api/v1/chat/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"][0]["title"] == TITLE
        for key in ("conversation_id", "project_id", "title"):
            assert key in data["items"][0]
