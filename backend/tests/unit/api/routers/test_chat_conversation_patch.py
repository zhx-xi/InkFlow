"""#766 阶段② PATCH /api/v1/chat/conversations/{id} 删除授权契约测试.

spec f26-agent-tools §6.4（前端分段控件变更 → PATCH 更新 conversation 级权限）+
§6.5 装配点。契约锁定:
1. `PATCH /api/v1/chat/conversations/{conversation_id}` body
   `{"delete_permission": "manual"|"ask_once"|"auto"}` → 200 返回更新后的权限
   （响应含 conversation_id + delete_permission）;
2. 非法 delete_permission（如 "bad"）→ 422（Pydantic Literal 校验）;
3. conversation 不存在（svc 返回 None）→ 404「chat 会话不存在」;
   conversation_id 非 UUID → 404（镜像 delete_conversation 既有 ValueError 模式）;
4. PATCH 后服务层 update_delete_permission 被调用（task 允许 repo/service 任一层;
   本测试同时 patch 路由器命名空间的 get_chat_message_service 与
   SQLiteChatMessageRepository 双注入点，GREEN 走任一即命中）。

RED 形态（chat_messages.py 尚无 PATCH 路由，路径已有 DELETE 注册）:
- PATCH 返回 405 Method Not Allowed（§8: 405 = 路径在、方法缺）;
- 200 用例: assert 405 == 200 干净失败;
- 422 用例: assert 405 == 422 干净失败（405 不解析 body）;
- 404 用例: assert 405 == 404 + detail "Method Not Allowed" != "chat 会话不存在"
  → detail 断言防 405 假绿（GREEN 后映射正确性由 detail 保证）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkflow.api.deps import get_db
from inkflow.api.routers.chat_messages import router

CONVERSATION_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


def _call_kw(call, name: str, index: int, default=None):
    """宽松取 mock 调用参数：优先关键字，回退位置参数（兼容两种 GREEN 形态）。"""
    args, kwargs = call
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else default


def _client() -> TestClient:
    """独立 app 挂载 chat router + get_db override（mock session）。"""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


def _patch_request(svc, method: str, url: str, **kwargs):
    """patch 双注入点（get_chat_message_service + SQLiteChatMessageRepository，
    均返回 svc mock）后发请求——patch 在请求期间生效。"""
    with (
        patch(
            "inkflow.api.routers.chat_messages.get_chat_message_service",
            return_value=svc,
        ),
        patch(
            "inkflow.api.routers.chat_messages.SQLiteChatMessageRepository",
            return_value=svc,
        ),
    ):
        return _client().request(method, url, **kwargs)


def _svc_with_update(return_value) -> MagicMock:
    """svc mock：update_delete_permission 为 AsyncMock（返回更新后会话/None）。"""
    svc = MagicMock()
    svc.update_delete_permission = AsyncMock(return_value=return_value)
    return svc


class TestPatchConversationDeletePermission:
    """PATCH /api/v1/chat/conversations/{id} 删除授权端点契约。"""

    def test_patch_ask_once_returns_updated_permission(self) -> None:
        """delete_permission="ask_once" → 200 返回更新后权限，且 svc.update_delete_permission
        被调用（conversation_id + 新权限透传）。"""
        svc = _svc_with_update(
            {
                "conversation_id": CONVERSATION_ID,
                "delete_permission": "ask_once",
            }
        )
        resp = _patch_request(
            svc,
            "PATCH",
            f"/api/v1/chat/conversations/{CONVERSATION_ID}",
            json={"delete_permission": "ask_once"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["conversation_id"] == CONVERSATION_ID
        assert body["delete_permission"] == "ask_once"
        svc.update_delete_permission.assert_awaited_once()
        call = svc.update_delete_permission.await_args
        assert str(_call_kw(call, "conversation_id", 0)) == CONVERSATION_ID
        assert _call_kw(call, "delete_permission", 1) == "ask_once"

    def test_patch_invalid_delete_permission_returns_422(self) -> None:
        """非法 delete_permission（"bad"）→ 422（Pydantic Literal 校验，不触达服务层）。"""
        svc = _svc_with_update(
            {
                "conversation_id": CONVERSATION_ID,
                "delete_permission": "ask_once",
            }
        )
        resp = _patch_request(
            svc,
            "PATCH",
            f"/api/v1/chat/conversations/{CONVERSATION_ID}",
            json={"delete_permission": "bad"},
        )

        assert resp.status_code == 422

    def test_patch_missing_conversation_returns_404(self) -> None:
        """conversation 不存在（svc 返回 None）→ 404「chat 会话不存在」。"""
        svc = _svc_with_update(None)
        resp = _patch_request(
            svc,
            "PATCH",
            f"/api/v1/chat/conversations/{CONVERSATION_ID}",
            json={"delete_permission": "auto"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "chat 会话不存在"

    def test_patch_invalid_conversation_id_returns_404(self) -> None:
        """conversation_id 非 UUID → 404（镜像 delete_conversation 的 ValueError 模式）。"""
        svc = _svc_with_update(
            {
                "conversation_id": CONVERSATION_ID,
                "delete_permission": "ask_once",
            }
        )
        resp = _patch_request(
            svc,
            "PATCH",
            "/api/v1/chat/conversations/not-a-uuid",
            json={"delete_permission": "ask_once"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "chat 会话不存在"
