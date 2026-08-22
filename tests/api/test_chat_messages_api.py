"""#547 chat 消息持久化 API RED 契约测试 — /api/v1/chat/messages + /conversations（spec 待定稿）.

父侧定稿契约（2026-08-21，实现者以本文件为准）:
- 新 router: backend/src/inkflow/api/routers/chat_messages.py（prefix=/api/v1/chat），
  必须在 app.py include_router 真实装配（装配断言见 TestChatAssembly，防 #245 盲区）
- 依赖注入点: get_chat_message_service **定义于 router 模块内**（禁 Depends 形态——
  handler 内 `svc = get_chat_message_service(db)` 模块级裸名获取，patch 才可拦截；
  镜像 references/missing-module-stub-patch.md 附带契约）
- POST /api/v1/chat/messages → 201
  请求体: {project_id: UUID str, role: "user"|"ai", content: str,
  intent?: "content"|"conversation"|null}
  响应: {id: UUID str, project_id: UUID str, role, content, intent,
  created_at: ISO8601 UTC}
  * content trim 后为空 → 422，detail == "chat 消息内容不能为空"
  * role 非法 → 422（Pydantic 校验，detail 为 list）
  * 服务调用: svc.add_message(<ChatMessageCreate>)（参数逐字:
    project_id/role/content/intent）
- GET /api/v1/chat/messages?project_id=X&offset=0&limit=50 → 200
  响应: {items: [ChatMessage...按时间升序], total, offset, limit}
  * project_id 必填（缺 → 422）
  * 服务调用: svc.list_messages(project_id=..., offset=..., limit=...)，
    items/total 透传
- GET /api/v1/chat/conversations → 200
  响应: {items: [{project_id, project_name, last_message, message_count,
  updated_at}], total}，按 updated_at 降序（service 聚合；total 由 router
  按 len(items) 推导）
  * 服务调用: svc.list_conversations()，items 原样透传

RED 逃生门（规则 1e 变体，镜像 references/missing-module-stub-patch.md）:
RED 阶段 inkflow.api.routers.chat_messages 模块不存在——导入期注入同路径 stub
模块（sys.modules.setdefault）使 @patch 目标可解析 → 端点未注册 → 真实 app
404 ≠ 期望码 → 断言 FAILED（无收集错误）。GREEN 阶段该模块已被 app 导入链
注册进 sys.modules，setdefault 不覆盖真模块，同一份测试文件零改动转绿。

RED 预期: 全部端点用例断言 FAILED（assert 404 == 200/201/422）；
装配用例 FAILED（chat 路径未注册）；无收集错误、无 ERROR。

asyncio: pytestmark = pytest.mark.asyncio（F27 实测必写）；客户端镜像
test_f27_agentic_api.py（AsyncClient + ASGITransport，不触发 lifespan——
全 mock 轨无需 DB）。
"""

from __future__ import annotations

import sys
import uuid
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app  # 必须先于 stub 行（GREEN 时真模块已注册进 sys.modules）

# RED 阶段 inkflow.api.routers.chat_messages 模块不存在——注入同路径 stub 模块，
# 使 @patch 目标可解析（规则 1e 逃生门）→ 端点未注册 → 404 断言 FAILED。
# GREEN 阶段 app 导入链已注册真模块，setdefault 不覆盖（零改动转绿）。
_stub_chat_router = ModuleType("inkflow.api.routers.chat_messages")
_stub_chat_router.get_chat_message_service = MagicMock()
sys.modules.setdefault("inkflow.api.routers.chat_messages", _stub_chat_router)

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CONTENT = "你好，请续写第三章。"
CREATED_AT = "2026-08-20T10:00:00Z"


def _client():
    """构造 ASGI 测试客户端（镜像 test_f27_agentic_api.py，不触发 lifespan）。"""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _message_dict(**overrides) -> dict:
    """ChatMessage 响应 dict（spec 响应口径：id/project_id UUID str + UTC ISO8601）。"""
    msg = {
        "id": str(uuid.uuid4()),
        "project_id": str(PROJECT_ID),
        "role": "user",
        "content": CONTENT,
        "intent": None,
        "created_at": CREATED_AT,
    }
    msg.update(overrides)
    return msg


def _conversation_dict(**overrides) -> dict:
    """conversations 聚合 dict（project_name 可空，service 聚合结果形态）。"""
    conv = {
        "project_id": str(PROJECT_ID),
        "project_name": "测试项目",
        "last_message": CONTENT,
        "message_count": 3,
        "updated_at": CREATED_AT,
    }
    conv.update(overrides)
    return conv


def _chat_route_paths() -> set[str]:
    """真实 app 已注册的 chat 相关路由路径（#245 装配契约）。

    fastapi 0.141.1 的 include_router 为惰性注册：app.routes 中为
    _IncludedRouter 包装对象（无 path 属性），真实路径经
    effective_route_contexts() 展开（ctx.path）——两条路径都覆盖。
    """
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
    """宽松取参：位置或关键字（规则 1o 同款，兼容两种 GREEN 传参形态）。

    #547 GREEN 收尾（Codex 上报）：直接读 _Call.args/.kwargs——原写法
    `args, kwargs = call.await_args` 在 _Call 对象上二次访问 `.await_args`
    命中 _Call.__getattr__ 链式占位（3 元组），解包必抛 ValueError；
    传入的 call 已是 `svc.method.await_args` 的结果（_Call 实例）。
    """
    args, kwargs = call.args, call.kwargs
    return args[index] if len(args) > index else kwargs[name]


@pytest.fixture
def chat_svc():
    """Mock ChatMessageService——全方法显式默认值（裸 AsyncMock 分支陷阱防护，规则 1m）。"""
    svc = MagicMock()
    svc.add_message = AsyncMock(return_value=_message_dict())
    svc.list_messages = AsyncMock(return_value=([], 0))
    svc.list_conversations = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def override_chat_svc(chat_svc):
    """@patch router 模块级 get_chat_message_service → mock ChatMessageService。

    RED 阶段由 sys.modules stub 提供 patch 目标（规则 1e 逃生门）；GREEN 阶段
    命中真实 router 模块全局名——实现必须走模块级服务获取（禁 Depends 形态）。
    """
    with patch(
        "inkflow.api.routers.chat_messages.get_chat_message_service",
        return_value=chat_svc,
    ):
        yield chat_svc


class TestPostMessageEndpoint:
    """POST /api/v1/chat/messages — 追加 chat 消息（spec 待定稿）. """

    pytestmark = pytest.mark.asyncio  # 根目录 STRICT 模式显式标记（backend pyproject 为 auto）

    async def test_post_message_201(self, chat_svc, override_chat_svc):
        """POST 201: 响应五字段口径 + add_message 参数逐字断言。"""
        msg = _message_dict(role="user", content=CONTENT, intent="conversation")
        chat_svc.add_message.return_value = msg
        async with _client() as client:
            resp = await client.post(
                "/api/v1/chat/messages",
                json={
                    "project_id": str(PROJECT_ID),
                    "role": "user",
                    "content": CONTENT,
                    "intent": "conversation",
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert uuid.UUID(data["id"]) is not None  # id 可解析为 UUID
        assert data["id"] == msg["id"]
        assert data["project_id"] == str(PROJECT_ID)
        assert data["role"] == "user"
        assert data["content"] == CONTENT
        assert data["intent"] == "conversation"
        assert data["created_at"] == CREATED_AT
        # add_message 收到 ChatMessageCreate（参数逐字: project_id/role/content/intent）
        call = chat_svc.add_message.await_args
        assert call is not None
        arg = _call_arg(call, "data", 0)
        # GREEN 存在；RED 期被上方 404 断言挡住（函数体惰性 import，免顶部收集失败）
        from inkflow.domain.models.chat_message import ChatMessageCreate

        assert isinstance(arg, ChatMessageCreate)
        assert arg.project_id == PROJECT_ID
        assert arg.role == "user"
        assert arg.content == CONTENT
        assert arg.intent == "conversation"

    async def test_post_message_422_blank_content(self, chat_svc):
        """POST 422: content trim 后为空 → detail 精确文案（业务校验，先于服务）。"""
        async with _client() as client:
            resp = await client.post(
                "/api/v1/chat/messages",
                json={"project_id": str(PROJECT_ID), "role": "user", "content": "   "},
            )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "chat 消息内容不能为空"

    async def test_post_message_422_invalid_role(self, chat_svc):
        """POST 422: role 非法（非 user/ai）→ Pydantic 校验（detail 为 list）。"""
        async with _client() as client:
            resp = await client.post(
                "/api/v1/chat/messages",
                json={"project_id": str(PROJECT_ID), "role": "system", "content": CONTENT},
            )
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)


class TestListMessagesEndpoint:
    """GET /api/v1/chat/messages — 项目消息列表（按时间升序，分页透传）。"""

    pytestmark = pytest.mark.asyncio  # 根目录 STRICT 模式显式标记（backend pyproject 为 auto）

    async def test_list_messages_200(self, chat_svc, override_chat_svc):
        """GET 200: {items, total, offset, limit} + list_messages 参数透传。"""
        msg = _message_dict()
        chat_svc.list_messages.return_value = ([msg], 1)
        async with _client() as client:
            resp = await client.get(
                "/api/v1/chat/messages",
                params={"project_id": str(PROJECT_ID), "offset": 0, "limit": 50},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == [msg]
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 50
        call = chat_svc.list_messages.await_args
        assert call is not None
        assert _call_arg(call, "project_id", 0) == PROJECT_ID
        assert _call_arg(call, "offset", 1) == 0
        assert _call_arg(call, "limit", 2) == 50

    async def test_list_messages_422_missing_project_id(self, chat_svc):
        """GET 422: project_id 必填（Query(...) 校验，detail 为 list）。"""
        async with _client() as client:
            resp = await client.get("/api/v1/chat/messages")
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)


class TestConversationsEndpoint:
    """GET /api/v1/chat/conversations — 会话页聚合列表（按 updated_at 降序）。"""

    pytestmark = pytest.mark.asyncio  # 根目录 STRICT 模式显式标记（backend pyproject 为 auto）

    async def test_list_conversations_200(self, chat_svc, override_chat_svc):
        """GET 200: {items, total}，items 形状逐字断言（service 聚合透传）。"""
        conv = _conversation_dict()
        chat_svc.list_conversations.return_value = [conv]
        async with _client() as client:
            resp = await client.get("/api/v1/chat/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == [conv]
        assert data["total"] == 1
        for key in (
            "project_id",
            "project_name",
            "last_message",
            "message_count",
            "updated_at",
        ):
            assert key in data["items"][0]
        chat_svc.list_conversations.assert_awaited_once()

    async def test_list_conversations_include_deleted_200(
        self, chat_svc, override_chat_svc
    ):
        """#581 GET ?include_deleted=true → 200 + svc.list_conversations(include_deleted=True)。

        镜像 sessions 先例（sessions.py L127 include_deleted: bool = Query(False)）：
        include_deleted=true 时活动 + 归档全量返回（会话页恢复已归档会话入口）。
        """
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
        """#581 include_deleted=true 响应 items 带 is_deleted 键（前端归档视图过滤依赖）。"""
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


class TestChatAssembly:
    """#245 装配契约：chat_messages router 必须在真实 app 注册（不再手动安装）。"""

    def test_chat_messages_routes_registered_in_app(self):
        """app.routes 含 /api/v1/chat/messages（POST+GET）。"""
        paths = _chat_route_paths()
        assert "/api/v1/chat/messages" in paths, f"缺 chat messages 路由: {paths}"

    def test_chat_conversations_route_registered_in_app(self):
        """app.routes 含 /api/v1/chat/conversations。"""
        paths = _chat_route_paths()
        assert "/api/v1/chat/conversations" in paths, f"缺 conversations 路由: {paths}"


class TestRestoreConversationEndpoint:
    """#587 POST /api/v1/chat/conversations/{project_id}/restore — 整项目会话恢复。

    父侧定稿契约（镜像 DELETE /conversations/{project_id} 反操作 + restore_message 形态）:
    - POST /api/v1/chat/conversations/{project_id}/restore → 200
      请求: 路径参数 project_id: UUID str（小值 UUID——64 位范围内，
      不触发 service 溢出短路，完整走 repo 轨）
      响应: {project_id: UUID str, is_deleted: false}（归档解除后语义）
      服务调用: svc.restore_conversation(project_id)（参数逐字，收到 UUID）
    - 服务返回 0（项目不存在/无已归档消息）→ 404「chat 会话不存在」
      （镜像 delete_conversation 的 404 文案）

    RED 预期: router 无该端点 → 404 → status_code 断言 FAILED；
    不存在用例 detail 为 FastAPI 默认 "Not Found" → detail 断言 FAILED；
    装配用例 FAILED（新路由未注册）。无收集错误（router 模块已注册）。
    """

    @pytest.mark.asyncio
    async def test_restore_conversation_200(self, chat_svc, override_chat_svc):
        """归档项目 POST restore → 200（含 is_deleted=false）+ restore_conversation 收到 UUID。

        RED 预期: 路由未注册 → 404 → status_code 断言失败。
        """
        pid = uuid.UUID(int=42)  # 小值 UUID（64 位范围内，完整走 repo 轨）
        chat_svc.restore_conversation = AsyncMock(return_value=2)
        async with _client() as client:
            resp = await client.post(f"/api/v1/chat/conversations/{pid}/restore")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == str(pid)
        assert data["is_deleted"] is False
        chat_svc.restore_conversation.assert_awaited_once_with(pid)

    @pytest.mark.asyncio
    async def test_restore_conversation_not_found_404(self, chat_svc, override_chat_svc):
        """restore_conversation 返回 0（项目不存在/未归档）→ 404「chat 会话不存在」。

        RED 预期: 路由未注册 → detail 为 "Not Found" → detail 断言失败。
        """
        chat_svc.restore_conversation = AsyncMock(return_value=0)
        async with _client() as client:
            resp = await client.post(
                f"/api/v1/chat/conversations/{uuid.UUID(int=43)}/restore"
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "chat 会话不存在"

    def test_chat_restore_conversation_route_registered_in_app(self):
        """app.routes 含 /api/v1/chat/conversations/{project_id}/restore（装配契约）。"""
        paths = _chat_route_paths()
        assert any(
            p.endswith("/chat/conversations/{project_id}/restore") for p in paths
        ), f"缺 chat restore conversation 路由: {sorted(paths)}"
