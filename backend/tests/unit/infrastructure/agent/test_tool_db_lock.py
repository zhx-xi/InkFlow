"""#837 设定库工具并行调用串行化锁 — 契约测试（RED 先写，全 FAIL 实证后交由 Codex GREEN）.

根因（issue #837 三重证据链）:
1. 同一请求 = 同一 AsyncSession 被所有工具共享（deps_chat_agent.py 每请求一个 db，
   各工具工厂传同一 db，各 repo 持同一 session）。
2. deepagents 用 Send API 并行分发工具调用（LLM 一次输出 N 个 tool_calls）。
3. 并行协程交错使用同一 AsyncSession → 事务状态机破坏（cannot start a transaction
   within a transaction / cannot commit / database is locked）。

方案 A（模块级 asyncio.Lock 串行化）契约:
1. 并发调用两个设定库工具（共享真实 session）→ 不报数据库错误（当前 FAIL）.
2. 锁顺序串行：工具 A/B 依次执行（互不重叠，锁生效）.
3. 锁是模块级单例（跨工具实例共享；非每实例一把锁）.
4. 锁覆盖读工具（list_maps 并行 execute 不交错）.
5. audit 链在锁内（业务写 + audit 记录不交错）.

测试形态说明:
- 真实 session 复现（契约 1）: 真实 in-memory SQLite + 真实 CharacterService +
  SQLiteCharacterRepository，共享同一 AsyncSession，asyncio.gather 并发调用两次
  create_character —— 无锁时 session 事务交错 → 报错（"This transaction is closed" /
  "Method 'commit()' can't be called here"），有锁时串行 → 双成功且都落库。
- 锁语义复现（契约 2-5）: 用 ConcurrencyMonitor 包装 service/audit 方法，检测并发
  工具调用是否重叠（max_active）——无锁时 max_active>=2，有锁时恒 1。

⚠️ pytest-asyncio 用 function-scoped 事件循环（conftest 的 session event_loop 未被
1.4.0 采纳，实测定序）。故每测试后须重建模块级锁，否则下一个并发测试因锁被前一个
loop 绑定而抛 RuntimeError（"bound to a different event loop"）。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.services.character_service import CharacterService
from inkflow.infrastructure.agent.tools.setting_write_tools import (
    SettingWriteToolDeps,
    build_setting_write_tools,
)
from inkflow.infrastructure.agent.tools.world_readwrite_tools import (
    WorldRwToolDeps,
    build_world_rw_tools,
)
from inkflow.infrastructure.database.repositories.character_repo import (
    SQLiteCharacterRepository,
)

# 小整数项目 UUID（InkFlow 项目 UUID=int(orm_id)，防 128 位溢出到 SQLite INTEGER）
PROJECT_ID = uuid.UUID(int=7)


@pytest.fixture(autouse=True)
def _reset_tool_db_lock():
    """每个测试后重建模块级锁，规避 pytest-asyncio function-scope 事件循环绑定.

    RED 阶段 `_tool_db_lock` 模块尚不存在（CODE 未加锁），导入失败 → no-op；
    GREEN 阶段把它重置为新锁，使每个并发测试在独立循环中重绑定。
    """
    yield
    try:
        from inkflow.infrastructure.agent.tools import _tool_db_lock as _lock_mod

        _lock_mod._tool_db_lock = asyncio.Lock()
    except Exception:  # RED 阶段锁模块尚未创建（BLE001 未启用，勿挂 noqa）
        pass


# ─── 真实 session 复现辅助 ──────────────────────────────────────────


class _DummyAudit:
    """极简审计替身：record 为 AsyncMock（真实 DB 错误来自 service/repo 会话交错）。"""

    def __init__(self) -> None:
        self.record = AsyncMock(return_value=None)


async def _make_real_session() -> tuple[AsyncSession, Any]:
    """真实 in-memory SQLite + 单 AsyncSession（镜像 test_character_repo fixture）."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db: AsyncSession = factory()
    return db, engine


# ─── 锁语义监测辅助 ──────────────────────────────────────────────


class ConcurrencyMonitor:
    """统计 service/audit 调用是否重叠（max_active）。

    guard() 进入时 active+1、记录峰值、await asyncio.sleep 强制让出，
    使同事件循环内的另一次并发调用得以进入——无锁时 max_active>=2。
    """

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def guard(self, *_args: object, **_kw: object) -> object:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        return _SimpleChar()


class _SimpleChar:
    """工具信封所需的实体替身（.id / .name）。"""

    def __init__(self, iid: str = "id-1", name: str = "林晚") -> None:
        self.id = iid
        self.name = name


def _monitor_char_deps(monitor: ConcurrencyMonitor) -> SettingWriteToolDeps:
    """构造 create_character 工具依赖：character_service.create_character 走 monitor."""
    deps = SettingWriteToolDeps(
        character_service=MagicMock(),
        world_service=MagicMock(),
        outline_service=MagicMock(),
        audit_service=_DummyAudit(),
        expected_project_id=PROJECT_ID,
    )
    deps.character_service.create_character = AsyncMock(side_effect=monitor.guard)
    return deps


def _monitor_map_deps(monitor: ConcurrencyMonitor) -> WorldRwToolDeps:
    """构造 list_maps 工具依赖：map_service.list_maps 走 monitor（返回空页）。

    _fetch_all_pages 会以 (project_id, offset=0, limit=50) 调用 list_maps 并期望
    tuple[list, int]（单页<50 即停）。这里 guard 记录并发、返回空页。
    """

    async def _list_maps_guarded(*args: object, **kw: object) -> tuple[list[object], int]:
        await monitor.guard(*args, **kw)
        return ([], 0)

    deps = WorldRwToolDeps(
        map_service=MagicMock(),
        timeline_service=MagicMock(),
        foreshadowing_service=MagicMock(),
        audit_service=_DummyAudit(),
        expected_project_id=PROJECT_ID,
    )
    deps.map_service.list_maps = _list_maps_guarded
    return deps


# ─── 契约 1: 共享真实 session 并发 → 不报数据库错误 ─────────────────┤


class TestConcurrentSettingWriteNoDbError:
    """两个设定库工具并发共享真实 session → 不报数据库错误（当前 FAIL）."""

    @pytest.mark.asyncio
    async def test_two_concurrent_creates_no_db_error(self) -> None:
        db, engine = await _make_real_session()
        try:
            char_svc = CharacterService(repository=SQLiteCharacterRepository(db))
            deps = SettingWriteToolDeps(
                character_service=char_svc,
                world_service=MagicMock(),
                outline_service=MagicMock(),
                audit_service=_DummyAudit(),
                expected_project_id=PROJECT_ID,
            )
            tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
            create = tools["create_character"].func

            results = await asyncio.gather(
                create(name="甲"), create(name="乙"), return_exceptions=True
            )
            # 两次调用都必须成功（无锁时失败: "This transaction is closed" 等）
            for r in results:
                assert not isinstance(r, BaseException), f"并发调用报数据库错误: {r}"
                payload = json.loads(r)
                assert payload["ok"] is True, f"并发调用未成功: {payload}"

            # 两次都真实落库（无锁时事务交错可能丢数据）
            items, total = await char_svc.list_characters(PROJECT_ID)
            assert total == 2, f"应落库 2 个角色，实际 {total}"
            assert {it.name for it in items} == {"甲", "乙"}
        finally:
            await engine.dispose()


# ─── 契约 2: 锁顺序串行 ─────────────────────────────────────────


class TestToolLockSerializes:
    """并发调用两个 create_character → service 依次执行不重叠."""

    @pytest.mark.asyncio
    async def test_create_character_serialized(self) -> None:
        monitor = ConcurrencyMonitor()
        deps = _monitor_char_deps(monitor)
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        create = tools["create_character"].func

        await asyncio.gather(create(name="A"), create(name="B"))
        assert monitor.max_active == 1, (
            f"工具未串行化——service 调用重叠（max_active={monitor.max_active}）。"
            "锁应让 A/B 依次执行而非交错。"
        )


# ─── 契约 3: 锁是模块级单例 ──────────────────────────────────────


class TestToolLockIsModuleSingleton:
    """两个工具实例（两次 build 调用）共享同一把锁（非每实例一把）."""

    @pytest.mark.asyncio
    async def test_cross_instance_shared_lock(self) -> None:
        monitor = ConcurrencyMonitor()
        deps_a = _monitor_char_deps(monitor)
        deps_b = _monitor_char_deps(monitor)
        tools_a = {t.spec.name: t for t in build_setting_write_tools(deps_a)}
        tools_b = {t.spec.name: t for t in build_setting_write_tools(deps_b)}
        create_a = tools_a["create_character"].func
        create_b = tools_b["create_character"].func

        await asyncio.gather(create_a(name="A"), create_b(name="B"))
        assert monitor.max_active == 1, (
            f"两次 build 实例未共享模块级锁——service 重叠（max_active={monitor.max_active}）。"
            "锁必须是模块级单例（跨所有工具实例共享），不能每实例一把。"
        )


# ─── 契约 4: 锁覆盖读工具（list_maps 并行 execute 不交错） ────────


class TestToolLockCoversReadTools:
    """锁覆盖读工具：list_maps 并行 execute 不交错."""

    @pytest.mark.asyncio
    async def test_list_maps_parallel_serialized(self) -> None:
        monitor = ConcurrencyMonitor()
        deps = _monitor_map_deps(monitor)
        tools = {t.spec.name: t for t in build_world_rw_tools(deps)}
        list_maps = tools["list_maps"].func

        await asyncio.gather(list_maps(), list_maps())
        assert monitor.max_active == 1, (
            f"读工具 list_maps 未串行化——并行 execute 交错（max_active={monitor.max_active}）。"
        )


# ─── 契约 5: audit 链在锁内 ──────────────────────────────────────


class TestAuditChainInsideLock:
    """audit 记录不与其他工具的业务写/审计交错（audit 也在锁范围内）."""

    @pytest.mark.asyncio
    async def test_audit_not_interleaved(self) -> None:
        monitor = ConcurrencyMonitor()
        deps = _monitor_char_deps(monitor)
        # 审计记录同样走 monitor：验证 audit 与业务写处于同一把锁的保护范围
        deps.audit_service.record = AsyncMock(side_effect=monitor.guard)
        tools = {t.spec.name: t for t in build_setting_write_tools(deps)}
        create = tools["create_character"].func

        await asyncio.gather(create(name="A"), create(name="B"))
        assert monitor.max_active == 1, (
            f"audit 链未在锁内——业务写+审计记录交错（max_active={monitor.max_active}）。"
            "锁必须覆盖整个 await 链（含 audit_service.record），不能只锁工具开头。"
        )
