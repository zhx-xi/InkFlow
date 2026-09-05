"""#953 RED-2 集成契约测试 — book run sync 桥崩溃面最小复现（adapter+真实图+真实 DB）.

崩溃面（契约 §0#3/#4：DeepAgentInvokeAdapter.invoke L93 在 async 上下文中同步调
graph.invoke）：真实 CompiledStateGraph 的 sync invoke → ToolNode sync 路径 → func 桥
（harness._make_sync_wrapper）→ 在独立 worker 线程 + 新事件循环上运行 save_draft 协程。
save_draft 经模块级 `_tool_db_lock`（asyncio.Lock 单例）穿过新循环（§0#2/#3）——跨循环
锁竞争时抛 `RuntimeError: ... is bound to a different event loop`。

RED 形态说明（实证，父侧探针 + 本文件测前探针）：
- 单次 `await adapter.invoke`（无竞争）时，sync 桥把工具挪到 closed worker 循环执行，
  但模块锁 acquire 从不被竞争 ⇒ save_draft 成功、草稿落库（当前实现「能跑」但不代表
  桥是安全路径）。契约 §2 RES-2 的「预热 acquire/release 绑定」在 Python 3.13 下
  **不会**把 asyncio.Lock 绑定到宿主循环（`lock._loop` 保持 None；只有竞争 acquire 才
  触发 `_get_loop()` 绑定）。因此单调用裸跑不会复现崩溃。
- 真正的桥崩溃面具现：「锁已被绑定到宿主循环 + 持锁状态下运行 adapter」。
  sync 桥 worker 循环 acquire 该锁 ⇒ `_get_loop()` 发现 running loop != 绑定 loop ⇒
  立即抛 `RuntimeError: bound to a different event loop`（不会死锁，也不会被 ToolNode
  吞成 error ToolMessage——sync ToolNode 直接向上抛）。本文件用**公开 API**（先真实竞争
  acquire 把锁绑定到宿主循环，再持锁运行）确定性触发该签名。

GREEN 判据（C1 + 1a 落地后）：adapter.invoke 走 `await ainvoke` → save_draft 协程在
宿主循环执行 + `get_tool_db_lock()` 返回 per-loop 锁（与 `_tool_db_lock` 不同对象）⇒
不受测试持锁影响 ⇒ 草稿落库（count==1）、无异常 ⇒ 本测试转绿。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.services.draft_service import DraftService
from inkflow.infrastructure.agent.agentic_writer import DeepAgentInvokeAdapter
from inkflow.infrastructure.agent.deepagents.harness import _map_tools
from inkflow.infrastructure.agent.tools import _tool_db_lock as _tool_db_lock_mod
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SaveDraftToolDeps,
    build_save_draft_tool,
)
from inkflow.infrastructure.database.models.agent_run import DraftORM
from inkflow.infrastructure.database.repositories.draft_repo import SQLiteDraftRepository

# 小整数项目/章节 UUID（InkFlow 惯例：UUID=int(orm_id)，防 128 位随机 UUID 溢出 SQLite
# INTEGER；DraftORM.project_id/chapter_id 为 String(36) 无 FK，chapter_id 可空——无需 seed 行）
PROJECT_ID = uuid.UUID(int=7)          # 非全零（DraftService.create 拒绝全零项目）
CHAPTER_ID = uuid.UUID(int=8)
DRAFT_CONTENT = "这是 agent 写出的章节草稿正文，测试落库正确性。"
DRAFT_SUMMARY = "测试保存"


@pytest.fixture(autouse=True)
def _reset_tool_db_lock():
    """每个测试后重建模块级锁（镜像 test_tool_db_lock.py 形态）。

    R 用例会把 `_tool_db_lock` 绑定到 pytest-asyncio 的事件循环，G 用例又在
    sync 上下文执行 asyncio.run——不重置则跨用例持锁绑定污染（bound to a different
    event loop）。"""
    yield
    with contextlib.suppress(Exception):
        _tool_db_lock_mod._tool_db_lock = asyncio.Lock()



class _DummyAudit:
    """极简审计替身：record 为 AsyncMock（错误形态来自锁/会话跨循环，非审计）。"""

    def __init__(self) -> None:
        self.record = AsyncMock(return_value=None)


async def _make_real_session() -> tuple[AsyncSession, object]:
    """真实 in-memory aiosqlite + 单 AsyncSession（镜像 test_tool_db_lock.py 形态）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db: AsyncSession = factory()
    return db, engine


class _FakeSaveDraftModel(GenericFakeChatModel):
    """fake chat model：覆写 bind_tools 返回 self（父侧探针实证：对实例 setattr 会
    pydantic ValueError，必须子类化覆写）。消息脚本为一个 save_draft tool_call → 最终 AI。"""

    def bind_tools(self, tools, **kwargs):  # 父侧形态：返回 self 即可
        return self


def _make_fake_model() -> _FakeSaveDraftModel:
    """每用例新实例（消息 iter 一次性）。"""
    return _FakeSaveDraftModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "save_draft",
                            "args": {"content": DRAFT_CONTENT, "summary": DRAFT_SUMMARY},
                            "id": "call_save_draft_1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="done"),
            ]
        )
    )


async def _build_adapter(db: AsyncSession) -> tuple[DeepAgentInvokeAdapter, DraftService]:
    """装配：真实 DraftService(真实 SQLiteDraftRepository) → build_save_draft_tool →
    _map_tools → 真实 create_agent(fake model) 内层图 → DeepAgentInvokeAdapter。"""
    draft_svc = DraftService(draft_repo=SQLiteDraftRepository(db))
    tool = build_save_draft_tool(
        SaveDraftToolDeps(
            draft_service=draft_svc,
            audit_service=_DummyAudit(),
            expected_project_id=PROJECT_ID,
            expected_chapter_id=CHAPTER_ID,
        )
    )
    mapped = _map_tools([tool])
    graph = create_agent(
        _make_fake_model(),
        tools=mapped,
        system_prompt="你是一个助手",
        checkpointer=None,
    )
    return DeepAgentInvokeAdapter(graph), draft_svc


def _final_ai_text(result: dict) -> str:
    """从 result['messages'] 提取最终 AI 文本（content=='done'）。"""
    for msg in result.get("messages", []):
        if isinstance(msg, AIMessage):
            text = str(msg.content)
            if text.strip() == "done":
                return text
    return ""


async def _bind_tool_db_lock_to_host_loop() -> None:
    """把模块级 `_tool_db_lock` 绑定到当前（宿主）事件循环（公开 API，确定性）。

    asyncio.Lock 只在「竞争 acquire」时调用 `_get_loop()` 绑定 loop；
    无竞争的 acquire/release 不绑定（Python 3.13 实证 `_loop` 保持 None）。
    这里用真实竞争 acquire 使锁绑定到宿主循环，随后释放（锁保持「已绑定宿主循环但未锁」）。
    """
    lock = _tool_db_lock_mod._tool_db_lock

    async def _contender() -> None:
        async with lock:
            pass

    # 宿主循环先持有锁
    await lock.acquire()
    contender = asyncio.create_task(_contender())
    # 让 contender 运行其首个 await（竞争 acquire → _get_loop() → 绑定宿主循环后进入等待）
    await asyncio.sleep(0)
    lock.release()  # 释放锁，唤醒 contender → 它 acquire+release 收尾
    await contender


class TestAdapterAinvokeBridgeCrashRepro:
    """bridge 崩溃面：sync 桥跨循环锁竞争 → 草稿不落库（当前实现应 RED）。"""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_adapter_ainvoke_runs_tool_on_host_loop(self) -> None:
        """[R] adapter.invoke 在 pytest-asyncio 循环内执行 → ① 返回含最终 AI 文本；
        ② save_draft 真实落库（count==1、内容正确）；③ 无异常。

        当前实现（sync invoke + 模块锁）：先绑定模块锁到宿主循环再持锁运行 ⇒
        sync 桥 worker 循环 acquire 抛 `RuntimeError: bound to a different event loop`，
        草稿零落库 ⇒ 断言 ①/②/③ FAIL（RED 锚=草稿不落库 + 跨循环异常）。
        GREEN（C1 ainvoke + 1a per-loop 锁）后应全绿。
        """
        db, engine = await _make_real_session()
        try:
            adapter, draft_svc = await _build_adapter(db)

            # 复用契约 §2 RES-2 的桥崩溃面：锁绑定宿主循环 + 持锁运行 adapter
            # （单次无竞争 warmup 无法绑定锁，见模块 docstring）
            await _bind_tool_db_lock_to_host_loop()

            # ❶ 在 pytest-asyncio 宿主循环内执行 adapter.invoke
            raised: RuntimeError | None = None
            result: dict = {}
            try:
                async with _tool_db_lock_mod._tool_db_lock:
                    result = await adapter.invoke([AIMessage(content="写吧")])
            except RuntimeError as exc:
                raised = exc

            # ② save_draft 真实落库（同 session 查询）
            drafts, total = await draft_svc.list(PROJECT_ID)

            # —— RED 锚：当前实现 sync 桥跨循环锁竞争 → 草稿零落库 ——
            if raised is not None:
                assert "bound to a different event loop" in str(raised), (
                    f"非预期异常（非 #953 桥崩溃签名）: {raised}"
                )
                assert total == 0, (
                    f"跨循环崩溃后草稿应零落库，实际落库 {total} 条（RED 锚=草稿不落库）"
                )
                pytest.fail(  # 让 RED 用例失败：#953 待 C1(ainvoke)+1a(per-loop 锁) 修复
                    f"sync 桥跨循环崩溃: {raised!r}; 草稿未落库（total={total}）——#953 RED-2"
                )

            # —— GREEN 路径：契约断言①/②/③ ——
            assert total == 1, f"草稿应落库 1 条，实际 {total}"
            assert drafts[0].content == DRAFT_CONTENT

            # ① 返回含最终 AI 文本
            assert _final_ai_text(result) == "done", "adapter 返回未含最终 AI 文本"

            # ③ 消息历史无 status='error' 的 ToolMessage
            error_tool_msgs = [
                m for m in result.get("messages", []) if getattr(m, "status", None) == "error"
            ]
            assert not error_tool_msgs, f"消息历史含 error ToolMessage: {error_tool_msgs}"
        finally:
            await engine.dispose()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_session_usable_after_agent_run(self) -> None:
        """[G] adapter 运行后，宿主循环继续用同一 session 读写不抛（session 未被跨循环污染）。

        当前实现：sync 桥在 worker 循环用共享 session，完成后宿主循环再 query + insert +
        commit。实证（探针）Python 3.13 + aiosqlite 下 session 跨循环复用不抛 ⇒ 本用例作
        守护（当前即 PASS）；若未来 bridge 让 session 绑定 worker 循环则此处转红。
        """
        db, engine = await _make_real_session()
        try:
            adapter, _ = await _build_adapter(db)
            _ = await adapter.invoke([AIMessage(content="写吧")])  # 经 sync 桥落一稿

            # 宿主循环继续读写同一 session
            rows = (await db.execute(select(DraftORM).limit(1))).scalars().all()
            assert len(rows) == 1
            db.add(
                DraftORM(
                    project_id=str(PROJECT_ID),
                    chapter_id=str(CHAPTER_ID),
                    content="宿主循环后续写入",
                    summary="",
                )
            )
            await db.commit()
            after = (await db.execute(select(DraftORM))).scalars().all()
            assert len(after) == 2
        finally:
            await engine.dispose()


class TestMapToolsDualChannel:
    """_map_tools 产物 func+coroutine 双给（结构契约防回归，镜像 test_harness_sync_wrapper.py）。"""

    def test_map_tools_dual_channel_unchanged(self) -> None:
        """[G] _map_tools 产物仍 func+coroutine 双给：func=sync wrapper（非原始 async 函数），
        coroutine=原始 async 函数。当前实现已满足 → PASS。"""
        # 重置模块锁（避免 R 用例把锁绑定到 pytest 循环后，sync 上下文的 asyncio.run 跨循环）
        _tool_db_lock_mod._tool_db_lock = asyncio.Lock()
        draft_service = MagicMock()
        draft_service.create = AsyncMock(
            return_value=SimpleNamespace(id="draft-1", content=DRAFT_CONTENT)
        )
        tool = build_save_draft_tool(
            SaveDraftToolDeps(
                draft_service=draft_service,
                audit_service=_DummyAudit(),
                expected_project_id=PROJECT_ID,
                expected_chapter_id=CHAPTER_ID,
            )
        )
        mapped = _map_tools([tool])
        assert len(mapped) == 1
        st = mapped[0]
        assert st.coroutine is tool.func, "coroutine 必须是原始 async 函数（async 路径）"
        assert st.func is not tool.func, "func 必须是 sync 桥接 wrapper（sync 路径）"
        assert st.name == "save_draft"
        assert st.description
        # sync 上下文（无运行中事件循环）可执行
        payload = json.loads(st.func(content=DRAFT_CONTENT, summary=DRAFT_SUMMARY))
        assert payload.get("ok") is True
