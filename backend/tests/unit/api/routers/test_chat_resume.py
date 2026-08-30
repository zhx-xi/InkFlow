"""#766 阶段② POST /api/v1/chat/resume HITL 续跑契约测试.

spec f26-agent-tools §6.3（resume 端点: body {conversation_id, approved} →
ChatAgentService 调用 agent.invoke(..., command=Command(resume={"approved": approved}))
续跑）+ §6.5 装配点（新增 api/chat_resume.py）。契约锁定:
1. `POST /api/v1/chat/resume` body `{"conversation_id": str, "approved": bool}`
   → 200 `{"ok": true}`（approved=true/false 均返回 ok）;
2. conversation 不存在（get_conversation_service(db).get 返回 None）→ 404
   「chat 会话不存在」; conversation_id 非 UUID → 404（镜像 chat_messages 既有模式）;
3. 端点经 get_chat_agent_service 取 ChatAgentService 并调用
   svc.resume(conversation_id=..., approved=...) 续跑（task 允许断言 svc 或
   agent.resume 被调——本测试锁定 svc.resume 被 awaited 且 approved 值透传;
   GREEN 按 spec §6.3 在 ChatAgentService.resume 内部
   agent.invoke(Command(resume={"approved": approved}), config=thread_id)）;
4. patch 目标 = chat_resume 模块级 + deps 模块级双命名空间（f27 绑定名快照惯例，
   无论 GREEN 走 from-import 还是 deps_module 间接调用均命中）;
   chat_resume 惰性 import 发生在 patch 上下文内 → 模块级 from-import 亦取到 mock。

RED 形态（api/chat_resume.py 模块不存在）:
- 用例体惰性 import router → ImportError FAILED（逐用例粒度，无 collection error，
  missing-module-stub-patch 逃生门）;
- patch 目标在模块不存在时随惰性 import 一并失败——两种均 RED。
"""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkflow.api.deps import get_db

CONVERSATION_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _call_kw(call, name: str, index: int, default=None):
    """宽松取 mock 调用参数：优先关键字，回退位置参数（兼容两种 GREEN 形态）。"""
    args, kwargs = call
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else default


def _get_resume_router():
    """用例体惰性取 chat_resume.router——RED 期模块不存在 → ImportError FAILED。"""
    from inkflow.api.routers.chat_resume import router

    return router


def _post_resume(svc, conv_get: AsyncMock, **body):
    """patch 双命名空间 + TestClient 发请求（patch 在请求期间生效）。

    RED 期先惰性 import router → ImportError FAILED（先于 patch 目标解析失败，
    与 docstring 声明的 RED 形态一致）。
    """
    router = _get_resume_router()
    conv_svc = MagicMock()
    conv_svc.get = conv_get
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "inkflow.api.routers.chat_resume.get_chat_agent_service",
                return_value=svc,
            )
        )
        stack.enter_context(patch("inkflow.api.deps.get_chat_agent_service", return_value=svc))
        stack.enter_context(
            patch(
                "inkflow.api.routers.chat_resume.get_conversation_service",
                return_value=conv_svc,
            )
        )
        stack.enter_context(
            patch("inkflow.api.deps.get_conversation_service", return_value=conv_svc)
        )
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: MagicMock()
        return TestClient(app).post("/api/v1/chat/resume", json=body)


def _conv() -> SimpleNamespace:
    """会话替身（project_id/delete_permission 供 GREEN 装配续跑 agent 用）。"""
    return SimpleNamespace(
        id=CONVERSATION_ID,
        project_id=PROJECT_ID,
        delete_permission="ask_once",
    )


def _resume_svc() -> MagicMock:
    """ChatAgentService mock：resume 为 AsyncMock（GREEN 端点 await svc.resume 续跑）。"""
    svc = MagicMock()
    svc.resume = AsyncMock(return_value=None)
    return svc


class TestChatResumeEndpoint:
    """POST /api/v1/chat/resume HITL 续跑端点契约。"""

    def test_resume_approved_true_returns_ok(self) -> None:
        """approved=true → 200 {ok:true}，且 svc.resume 被 awaited（approved 透传 True）。"""
        svc = _resume_svc()
        resp = _post_resume(
            svc,
            AsyncMock(return_value=_conv()),
            conversation_id=CONVERSATION_ID,
            approved=True,
        )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        svc.resume.assert_awaited_once()
        call = svc.resume.await_args
        assert str(_call_kw(call, "conversation_id", 0)) == CONVERSATION_ID
        assert _call_kw(call, "approved", 1) is True

    def test_resume_approved_false_returns_ok(self) -> None:
        """approved=false（拒绝删除）→ 200 {ok:true}，approved 透传 False。"""
        svc = _resume_svc()
        resp = _post_resume(
            svc,
            AsyncMock(return_value=_conv()),
            conversation_id=CONVERSATION_ID,
            approved=False,
        )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        svc.resume.assert_awaited_once()
        call = svc.resume.await_args
        assert _call_kw(call, "approved", 1) is False

    def test_resume_missing_conversation_returns_404(self) -> None:
        """conversation 不存在（get 返回 None）→ 404「chat 会话不存在」，resume 不被调用。"""
        svc = _resume_svc()
        resp = _post_resume(
            svc,
            AsyncMock(return_value=None),
            conversation_id=CONVERSATION_ID,
            approved=True,
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "chat 会话不存在"
        svc.resume.assert_not_awaited()

    def test_resume_invalid_conversation_id_returns_404(self) -> None:
        """conversation_id 非 UUID → 404（镜像 chat_messages 既有 ValueError 模式）。"""
        svc = _resume_svc()
        resp = _post_resume(
            svc,
            AsyncMock(return_value=_conv()),
            conversation_id="not-a-uuid",
            approved=True,
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "chat 会话不存在"
        svc.resume.assert_not_awaited()
