"""#1015 归档会话只读：GET /api/v1/chat/messages include_deleted 透传契约.

spec specs/f19-gui/sessions.md §6.2：归档线程的消息随 conversation 级联软删
（chat_message_repo.archive_conversation），既有 GET /messages 硬过滤
~is_deleted → 归档会话打开显示空。新增 query：
- include_deleted=true → svc.list_messages_by_conversation 收到
  include_deleted=True（含已归档消息）；
- 缺省 → False（既有「不含已归档」语义不变，护栏）。

RED 形态：router 未声明 include_deleted query（FastAPI 忽略未知参数）→
svc 调用不含该信息 → 透传断言 FAIL。

注入点镜像 test_chat_conversation_patch.py：patch 模块级
get_chat_message_service + SQLiteChatMessageRepository 双命名空间。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkflow.api.deps import get_db
from inkflow.api.routers.chat_messages import router

CONVERSATION_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


def _svc_with_messages() -> MagicMock:
    """svc mock：list_messages_by_conversation → ([msg dict], 1)（dict 透传序列化）。"""
    svc = MagicMock()
    svc.list_messages_by_conversation = AsyncMock(
        return_value=(
            [
                {
                    "id": str(uuid.uuid4()),
                    "project_id": str(uuid.uuid4()),
                    "conversation_id": CONVERSATION_ID,
                    "role": "user",
                    "content": "归档前的消息",
                    "intent": None,
                    "created_at": "2026-08-20T08:00:00Z",
                }
            ],
            1,
        )
    )
    return svc


def _get_with_mock(svc: MagicMock, url: str):
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
        return _client().get(url)


def _include_deleted_of(call) -> bool | None:
    """宽松读取 include_deleted 实参值：关键字优先，回退位置参数 index=3；
    未传递 → None（RED 判据：router 尚无该 query 时不含任何形态）。"""
    args, kwargs = call
    if "include_deleted" in kwargs:
        return bool(kwargs["include_deleted"])
    if len(args) > 3:
        return bool(args[3])
    return None


class TestListMessagesIncludeDeleted:
    """GET /api/v1/chat/messages?include_deleted= 透传契约。"""

    def test_include_deleted_true_forwards_to_service(self) -> None:
        """include_deleted=true → 200 且 svc.list_messages_by_conversation 收到 True。"""
        svc = _svc_with_messages()
        resp = _get_with_mock(
            svc,
            f"/api/v1/chat/messages?conversation_id={CONVERSATION_ID}&include_deleted=true",
        )

        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        svc.list_messages_by_conversation.assert_awaited_once()
        call = svc.list_messages_by_conversation.await_args
        assert _include_deleted_of(call) is True

    def test_include_deleted_false_forwards_to_service(self) -> None:
        """include_deleted=false → 透传 False（显式值不被吞）。"""
        svc = _svc_with_messages()
        resp = _get_with_mock(
            svc,
            f"/api/v1/chat/messages?conversation_id={CONVERSATION_ID}&include_deleted=false",
        )

        assert resp.status_code == 200
        call = svc.list_messages_by_conversation.await_args
        assert _include_deleted_of(call) is False

    def test_default_omitted_means_false(self) -> None:
        """缺省（无该 query）→ 有效语义 False（护栏：未声明=未传 → None/False 皆
        合法，GREEN 前恒 None；GREEN 后必须 False——绝不默认 True 泄漏归档消息）。"""
        svc = _svc_with_messages()
        resp = _get_with_mock(
            svc,
            f"/api/v1/chat/messages?conversation_id={CONVERSATION_ID}",
        )

        assert resp.status_code == 200
        call = svc.list_messages_by_conversation.await_args
        value = _include_deleted_of(call)
        assert value is None or value is False
