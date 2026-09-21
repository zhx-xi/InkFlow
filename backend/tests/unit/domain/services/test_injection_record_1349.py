"""#1349 章级注入记录落库与面板回显契约（RED）。

缺口：写作页「上下文注入」面板只展示 assemble 预览（"如果现在生成，将注入什么"），
无任何「上一章生成时**实际**注入了哪些条目」的持久化痕迹（全仓 grep 注入记录类模式 = 0 命中）。

落库载体 = ``agent_executions``（pipeline 执行的**唯一**既有落库点）：
该表已有 ``chapter_id`` 列 + 4 个 ``LenientJSON`` 列先例（hitl_payload / relations /
trace / thread_id），``core/database.py`` 有同表 4 次 ``PRAGMA 检缺列 → ALTER TABLE`` 模板
→ 加第 5 列 ``injected_context`` 属照抄既有模式（零迁移路径）。

被测（本 PR）：
1. ``ensure_agent_executions_injected_context_column`` 幂等迁移三形态
   （对齐 hitl_payload/relations/trace 先例 #354/#270/#379）
2. ``ExecutionStore.update_stages`` 接受 ``injected_context`` 参数并落库
3. ``AgentService._inject_context`` 收集「本次实际注入」的三源 id 明细
   （与 ``_assemble_setting_context`` 实际产出**同源**：白名单过滤后真正进 setting 的条目）
4. ``AgentService.list_chapter_injections`` 章级读回（最新一条有记录的 execution）
5. ``GET /api/v1/agent/chapters/{chapter_id}/injections`` 端点
6. 可证伪自证：剥掉落库写入 → 断言 3 必须 FAIL

RED 形态：
- ``ensure_agent_executions_injected_context_column`` 不存在 → 模块级 import 收集期
  ImportError（exit 2）
- ``ExecutionStore.update_stages`` 无 ``injected_context`` 参数 → TypeError
- ``AgentService._inject_context`` 无返回值/明细 → 断言失败
- ``AgentService.list_chapter_injections`` 不存在 → AttributeError
- 端点不存在 → 404 / 路由缺失
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text

from inkflow.core.database import ensure_agent_executions_injected_context_column

# 🔴 #1317 实测：ORM 模型必须在 `create_all()` **之前** import —— 表是在被 import 时
# 才注册到 Base.metadata；在 create_all 之后才 import 会让首个用例报
# `no such table: agent_executions`（看起来像 fixture 坏了，实为注册顺序）。
from inkflow.infrastructure.database.models.agent import (  # noqa: F401  # 导入即注册 Base.metadata
    AgentExecutionORM,
)

OLD_SCHEMA = """
CREATE TABLE agent_executions (
    id VARCHAR(36) PRIMARY KEY,
    pipeline VARCHAR(100) NOT NULL,
    project_id VARCHAR(36) NOT NULL,
    chapter_id VARCHAR(36),
    status VARCHAR(20) NOT NULL,
    stages TEXT NOT NULL,
    final_output TEXT NOT NULL,
    error TEXT NOT NULL,
    total_duration_ms INTEGER NOT NULL,
    created_at DATETIME NOT NULL
)
"""

NEW_SCHEMA = OLD_SCHEMA.replace(
    "created_at DATETIME NOT NULL",
    "injected_context TEXT, created_at DATETIME NOT NULL",
)


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


class TestInjectedContextMigration:
    """ensure_agent_executions_injected_context_column 幂等迁移三形态。"""

    def test_old_db_gets_column(self, tmp_path) -> None:
        """旧库：agent_executions 无 injected_context → 迁移后补列（幂等可重跑）。"""
        db = tmp_path / "old.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            conn.execute(text(OLD_SCHEMA))
        with engine.connect() as conn:
            assert "injected_context" not in _columns(conn, "agent_executions")
            ensure_agent_executions_injected_context_column(conn)
            assert "injected_context" in _columns(conn, "agent_executions")
            ensure_agent_executions_injected_context_column(conn)
            assert "injected_context" in _columns(conn, "agent_executions")
        engine.dispose()

    def test_new_db_noop(self, tmp_path) -> None:
        """新库：create_all 已含 injected_context → no-op 不改变列集。"""
        db = tmp_path / "new.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            conn.execute(text(NEW_SCHEMA))
        with engine.connect() as conn:
            before = _columns(conn, "agent_executions")
            ensure_agent_executions_injected_context_column(conn)
            assert _columns(conn, "agent_executions") == before
        engine.dispose()

    def test_missing_table_noop(self, tmp_path) -> None:
        """表不存在（全新环境）→ no-op 不抛错，等 create_all 建新表。"""
        db = tmp_path / "empty.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.connect() as conn:
            ensure_agent_executions_injected_context_column(conn)
            tables = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
            assert tables == []
        engine.dispose()


class TestExecutionStoreInjectedContext:
    """ExecutionStore.update_stages 接受 injected_context 并落库。"""

    async def test_update_stages_persists_injected_context(self, test_engine) -> None:
        """update_stages(..., injected_context={...}) → get_execution 读回同值。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.agent.execution_store import ExecutionStore

        payload = {
            "character_ids": ["c1", "c2"],
            "world_ids": ["w1"],
            "foreshadowing_ids": ["f1"],
        }
        session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with session_factory() as session:
            store = ExecutionStore(session)
            row = await store.create_execution("builtin:write_auto", "p1", "ch1")
            await store.update_stages(
                execution_id=row.id,
                stages=[],
                status="completed",
                final_output="成品",
                injected_context=payload,
            )
            got = await store.get_execution(row.id)
            assert got is not None
            assert got.injected_context == payload

    async def test_update_stages_without_injected_context_defaults_none(self, test_engine) -> None:
        """update_stages 不传 injected_context → 保持 None（既有调用零改动）。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.agent.execution_store import ExecutionStore

        session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with session_factory() as session:
            store = ExecutionStore(session)
            row = await store.create_execution("builtin:write_auto", "p1")
            await store.update_stages(execution_id=row.id, stages=[], status="completed")
            got = await store.get_execution(row.id)
            assert got is not None
            assert got.injected_context is None


# ── 注入明细收集（与 _assemble_setting_context 实际产出同源）──────────────────


class _FakeSource:
    """最小来源实体（id/name/content/personality… 消费面）。"""

    def __init__(self, **kwargs):  # 测试桩：签名从简  # 测试桩：字段随来源而定
        self.__dict__.update(kwargs)


class _Repo:
    def __init__(self, items):
        self._items = items

    async def list(self, project_id, limit=50):  # 测试桩：签名从简
        return list(self._items), len(self._items)

    async def list_open(self, project_id):  # 测试桩：签名从简
        return list(self._items)


class _ProjectRepo:
    def __init__(self, project):
        self._project = project

    async def get(self, project_id):  # 测试桩：签名从简
        return self._project


def _svc_with_sources(*, characters=(), worlds=(), foreshadows=()):
    """构造只装配三源的 AgentService（镜像 tests 既有 __new__ 构造形态）。"""
    from inkflow.domain.services.agent_service import AgentService

    svc = AgentService.__new__(AgentService)
    svc._character_repo = _Repo(characters) if characters else None
    svc._world_repo = _Repo(worlds) if worlds else None
    svc._foreshadowing_repo = _Repo(foreshadows) if foreshadows else None
    svc._outline_repo = None
    svc._summary_service = None
    svc._chapter_repo = None
    svc._project_repo = _ProjectRepo(object())
    return svc


PROJECT_ID = str(uuid.uuid4())


class TestInjectionDetailCollection:
    """_inject_context 回传本次实际注入的三源 id 明细。"""

    async def test_returns_three_source_ids(self) -> None:
        """三源齐全 → 返回 {character_ids, world_ids, foreshadowing_ids} 三键。"""
        from inkflow.domain.ports.agent_pipeline import PipelineContext

        svc = _svc_with_sources(
            characters=[_FakeSource(id="c1", name="角色甲", personality="p", background=None)],
            worlds=[_FakeSource(id="w1", name="地点乙", content="内容")],
            foreshadows=[_FakeSource(id="f1", title="伏笔丙", description="描述")],
        )
        ctx = PipelineContext(project_id=PROJECT_ID, variables={})
        detail = await svc._inject_context(ctx, continue_context=False, override=None)
        assert detail is not None, "_inject_context 必须回传本次注入明细"
        assert set(detail) == {"character_ids", "world_ids", "foreshadowing_ids"}
        assert detail["character_ids"] == ["c1"]
        assert detail["world_ids"] == ["w1"]
        assert detail["foreshadowing_ids"] == ["f1"]

    async def test_detail_matches_setting_produced(self) -> None:
        """明细 == 实际进 variables['setting'] 的条目（同源，非"候选全集"）。

        override 只放行 c1（uuid.UUID(int=1)）与零世界观 —— 明细必须反映**过滤后**
        的产出：被剔掉的角色不进明细，回显面不会撒谎。
        """
        from inkflow.domain.models.context import ContextOverride
        from inkflow.domain.ports.agent_pipeline import PipelineContext

        keep = uuid.uuid4()
        svc = _svc_with_sources(
            characters=[
                _FakeSource(id=str(keep), name="角色甲", personality="p1", background=None),
                _FakeSource(id=str(uuid.uuid4()), name="角色乙", personality="p2", background=None),
            ],
            worlds=[_FakeSource(id=str(uuid.uuid4()), name="地点乙", content="内容")],
            foreshadows=[],
        )
        ctx = PipelineContext(project_id=PROJECT_ID, variables={})
        detail = await svc._inject_context(
            ctx,
            continue_context=False,
            override=ContextOverride(character_ids=[keep], world_ids=[], foreshadowing_ids=[]),
        )
        assert detail is not None
        # 白名单只留「角色甲」→ 明细只该有它
        assert detail["character_ids"] == [str(keep)]
        assert detail["world_ids"] == []
        setting = ctx.variables.get("setting", "")
        assert "角色甲" in setting
        assert "角色乙" not in setting
        # 明细与 setting 实际产出同源：setting 里出现几个角色，明细就该有几条
        assert detail["character_ids"] == [str(keep)]

    async def test_no_sources_returns_empty_lists(self) -> None:
        """无任何 repo 装配 → 明细为三个空列表（不是 None / 不抛错）。"""
        from inkflow.domain.ports.agent_pipeline import PipelineContext

        svc = _svc_with_sources()
        ctx = PipelineContext(project_id=PROJECT_ID, variables={})
        detail = await svc._inject_context(ctx, continue_context=False, override=None)
        assert detail == {"character_ids": [], "world_ids": [], "foreshadowing_ids": []}

    async def test_character_without_content_excluded(self) -> None:
        """角色三字段全空 → 不进 setting → 也不进明细（同源守护）。"""
        from inkflow.domain.ports.agent_pipeline import PipelineContext

        svc = _svc_with_sources(
            characters=[
                _FakeSource(id="c1", name="角色甲", personality=None, background=None, goals=None)
            ]
        )
        ctx = PipelineContext(project_id=PROJECT_ID, variables={})
        detail = await svc._inject_context(ctx, continue_context=False, override=None)
        assert detail is not None
        assert detail["character_ids"] == []
        assert "setting" not in ctx.variables


# ── 章级读回 ────────────────────────────────────────────────────────────────


class _ExecRow:
    """镜像 AgentExecutionORM 的消费面。"""

    def __init__(self, *, exec_id, chapter_id, injected_context, created_at=None):
        self.id = exec_id
        self.chapter_id = chapter_id
        self.project_id = "p1"
        self.pipeline = "builtin:write_auto"
        self.status = "completed"
        self.injected_context = injected_context
        self.created_at = created_at


class _Store:
    def __init__(self, rows):
        self._rows = rows
        self.list_calls: list[tuple] = []

    async def list_chapter_executions(self, chapter_id, limit=20):  # 测试桩：签名从简
        self.list_calls.append((chapter_id, limit))
        hits = [r for r in self._rows if r.chapter_id == chapter_id]
        return hits[:limit], len(hits)


class TestChapterInjectionReadback:
    """AgentService.list_chapter_injections 章级读回。"""

    async def test_returns_latest_record_with_payload(self) -> None:
        """有落库记录 → 返回最新一条的 injected_context + execution_id。"""
        from inkflow.domain.services.agent_service import AgentService

        payload = {"character_ids": ["c1"], "world_ids": [], "foreshadowing_ids": ["f1"]}
        store = _Store([_ExecRow(exec_id="e1", chapter_id="ch1", injected_context=payload)])
        svc = AgentService.__new__(AgentService)
        svc._store = store
        result = await svc.list_chapter_injections("ch1")
        assert store.list_calls == [("ch1", 20)]
        assert result["chapter_id"] == "ch1"
        assert result["execution_id"] == "e1"
        assert result["injected_context"] == payload

    async def test_no_record_returns_none_payload(self) -> None:
        """无记录（或记录未写明细）→ injected_context=None（前端据此回退预览态）。"""
        from inkflow.domain.services.agent_service import AgentService

        store = _Store([_ExecRow(exec_id="e1", chapter_id="ch1", injected_context=None)])
        svc = AgentService.__new__(AgentService)
        svc._store = store
        result = await svc.list_chapter_injections("ch1")
        assert result["injected_context"] is None
        assert result["chapter_id"] == "ch1"

    async def test_empty_store_returns_none_payload(self) -> None:
        """零执行记录 → injected_context=None 且不抛错。"""
        from inkflow.domain.services.agent_service import AgentService

        svc = AgentService.__new__(AgentService)
        svc._store = _Store([])
        result = await svc.list_chapter_injections("ch1")
        assert result["injected_context"] is None


# ── 落库接线：两条执行路径都必须把明细写进 store ────────────────────────────
#
# 🔴 本组是可证伪自证的落点：`_persist_injection_detail` 若不被调用 / 明细不回传，
# 「落库」这条链路就是空的（前面各组只测收集与读写原语，测不到「接线」）。


class _RecordingStore:
    """记录 update_injected_context 调用的桩 store。"""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def create_execution(
        self, pipeline, project_id, chapter_id=None, **kwargs
    ):  # 测试桩：签名从简
        return type("Exec", (), {"id": "e-99", "created_at": None})()

    async def get_execution(self, execution_id):  # 测试桩：签名从简
        return None

    async def update_stages(self, **kwargs):  # 测试桩：签名从简
        return None

    async def update_status(self, **kwargs):  # 测试桩：签名从简
        return None

    async def update_injected_context(self, execution_id, injected_context):  # 测试桩：签名从简
        self.calls.append((execution_id, injected_context))


class _StreamPipeline:
    """最小流式管线：发一个 stage 帧 + done 帧。"""

    async def stream(self, stages, context, conditional_edges=None):  # 测试桩：签名从简
        from inkflow.domain.ports.agent_pipeline import PipelineStreamEvent

        yield PipelineStreamEvent(type="stage", stage_id="s1")
        yield PipelineStreamEvent(type="done", done=True, final_output="成品")


class TestPersistWiring:
    """stream_pipeline / _run_pipeline 把明细落到 store（真正的「落库写入」）。"""

    async def _run_stream(self, store):  # 测试桩：签名从简装配
        from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest
        from inkflow.domain.services.agent_service import AgentService

        svc = AgentService.__new__(AgentService)
        svc._store = store
        svc._pipeline = _StreamPipeline()
        svc._supervisor_pipeline = None
        svc._project_repo = _ProjectRepo(object())
        svc._character_repo = _Repo(
            [_FakeSource(id="c1", name="角色甲", personality="p", background=None)]
        )
        svc._world_repo = None
        svc._foreshadowing_repo = None
        svc._outline_repo = None
        svc._summary_service = None
        svc._chapter_repo = None
        svc._db_session = None
        svc._get_template = lambda _p: type(
            "Tpl",
            (),
            {"stages": [], "roles": None},
        )()
        svc._load_template = _noop_template
        svc._merge_role_configs = _passthrough_stages
        # 绕开 _build_pipeline_context 的模板/agent 真源装配：直接打桩
        svc._build_pipeline_context = _stub_build_context

        request = PipelineExecuteRequest(
            project_id=PROJECT_ID,
            pipeline="builtin:write_auto",
            chapter_id=None,
            variables={},
        )
        events = [ev async for ev in svc.stream_pipeline(request)]
        return events  # noqa: RET504  # 命名保留可读性，值即 stream_pipeline 全量帧

    async def test_stream_pipeline_persists_detail(self) -> None:
        """stream_pipeline 执行 → store.update_injected_context 收到 execution_id + 三源明细。"""
        store = _RecordingStore()
        await self._run_stream(store)
        assert store.calls, "stream_pipeline 必须把注入明细落库（回执面唯一取数源）"
        execution_id, detail = store.calls[0]
        assert execution_id == "e-99"
        assert detail["character_ids"] == ["c1"]

    async def test_persist_uses_dedicated_write_path(self) -> None:
        """落库走 update_injected_context（注入先于 stage 流，不依赖 run 结果）。"""
        store = _RecordingStore()
        await self._run_stream(store)
        assert len(store.calls) == 1

    async def test_persist_failure_does_not_break_stream(self) -> None:
        """落库抛错 → 生成主流不中断（观测面失败隔离，镜像 _inject_context 语义）。"""

        class _BoomStore(_RecordingStore):
            async def update_injected_context(
                self, execution_id, injected_context
            ):  # 测试桩：签名从简
                raise RuntimeError("db down")

        events = await self._run_stream(_BoomStore())
        assert any(getattr(ev, "done", False) for ev in events), "落库失败不得阻断 done 帧"


async def _noop_template(_config):  # 测试桩：签名从简
    return None


async def _passthrough_stages(stages, *_a, **_kw):  # 测试桩：签名从简
    return stages


async def _stub_build_context(request):  # 测试桩：签名从简
    from inkflow.domain.ports.agent_pipeline import PipelineContext

    return (
        [],
        PipelineContext(
            project_id=str(request.project_id),
            chapter_id=str(request.chapter_id) if request.chapter_id else None,
            variables=dict(request.variables),
        ),
        # 🔴 必须给「有 stream 的」管线实现：返回 None → getattr(None,"stream") 为 None
        # → 落进 supervisor 降级分支的 `while status is None` 死循环（本会话实测挂死）
        _StreamPipeline(),
        [],
        [],
    )


# ── 端点 ────────────────────────────────────────────────────────────────────


class TestChapterInjectionsEndpoint:
    """GET /api/v1/agent/chapters/{chapter_id}/injections。"""

    def test_route_registered(self) -> None:
        """路由存在且路径形状正确（openapi 含该 path）。"""
        from inkflow.api.routers.agent import router

        paths = {r.path for r in router.routes if hasattr(r, "path")}
        assert "/api/v1/agent/chapters/{chapter_id}/injections" in paths

    @pytest.mark.asyncio
    async def test_endpoint_returns_payload(self) -> None:
        """TestClient：200 + 信封含 injected_context（路由→service→store 整流走通）。"""
        from unittest.mock import patch

        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from inkflow.api.routers import agent as agent_router_mod
        from inkflow.domain.services.agent_service import AgentService

        payload = {"character_ids": ["c1"], "world_ids": ["w1"], "foreshadowing_ids": []}

        class _StubStore:
            async def list_chapter_executions(self, chapter_id, limit=20):  # 测试桩：签名从简
                row = type(
                    "Row",
                    (),
                    {"id": "e1", "injected_context": payload, "chapter_id": chapter_id},
                )()
                return [row], 1

        svc = AgentService.__new__(AgentService)
        svc._store = _StubStore()
        app = FastAPI()
        app.include_router(agent_router_mod.router)
        transport = ASGITransport(app=app)
        # 端点内 `svc = _svc(db)` 是模块级直调（非 Depends 注入）→ 必须 patch 该工厂名
        with patch.object(agent_router_mod, "_svc", lambda _db: svc):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/agent/chapters/ch1/injections")
        assert resp.status_code == 200
        assert resp.json()["injected_context"] == payload


class TestRealStoreNewMethods:
    """真实 ExecutionStore 跑两个新方法（func-coverage 门禁：0 new uncalled）。

    🔴 为何单列一组：其余用例用桩 store 断言「谁被调用」，
    但真实方法的**正文**从未执行 → CI `coverage-function` 判新函数零调用。
    这里用真 SQLite engine + 真 store，覆盖正文与 `execution is None` 早退分支。
    """

    async def test_update_injected_context_persists(self, test_engine) -> None:
        """真实 update_injected_context → get_execution 读回同值。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.agent.execution_store import ExecutionStore

        payload = {"character_ids": ["c1"], "world_ids": ["w9"], "foreshadowing_ids": []}
        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            store = ExecutionStore(session)
            row = await store.create_execution("builtin:write_auto", "p1", "ch-real")
            await store.update_injected_context(row.id, payload)
            got = await store.get_execution(row.id)
            assert got is not None
            assert got.injected_context == payload

    async def test_update_injected_context_missing_execution_is_noop(self, test_engine) -> None:
        """execution_id 不存在 → 早退不抛错（idempotent 防御分支）。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.agent.execution_store import ExecutionStore

        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            store = ExecutionStore(session)
            await store.update_injected_context("no-such-id", {"character_ids": []})

    async def test_list_chapter_executions_filters_and_orders(self, test_engine) -> None:
        """真实 list_chapter_executions：仅返回该章、created_at 降序、total 正确。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.agent.execution_store import ExecutionStore

        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            store = ExecutionStore(session)
            await store.create_execution("builtin:write_auto", "p1", "ch-target")
            await store.create_execution("builtin:write_auto", "p1", "ch-other")
            await store.create_execution("builtin:write_auto", "p1", "ch-target")

            rows, total = await store.list_chapter_executions("ch-target")
            assert total == 2
            assert len(rows) == 2
            assert all(r.chapter_id == "ch-target" for r in rows)
            # created_at 降序（同秒时由插入序兜底，此处断言序列单调不增）
            stamps = [r.created_at for r in rows]
            assert stamps == sorted(stamps, reverse=True)

    async def test_list_chapter_executions_empty(self, test_engine) -> None:
        """无该章记录 → ([], 0)。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.agent.execution_store import ExecutionStore

        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            store = ExecutionStore(session)
            rows, total = await store.list_chapter_executions("nope")
            assert rows == []
            assert total == 0
