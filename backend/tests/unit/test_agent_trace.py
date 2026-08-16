"""F47 执行轨迹契约（spec §2.1 + §3.1）：agent_executions.trace 列 + 捕获 + 返回。

被测（PR 2）：
1. ensure_agent_executions_trace_column 幂等迁移（对齐 hitl_payload/relations 先例 #354/#270）
2. ExecutionStore.update_stages 接受 trace 参数并落库
3. AgentService.get_status 响应含 trace（缺省 []）
4. PipelineResult.trace 字段 + LangGraphPipeline 执行收集 stage trace
   （node=stage_id, type=stage, reasoning=LLM 输出）

RED 形态：
- ensure_agent_executions_trace_column 不存在 → import 收集期 ImportError（exit 2）
- ExecutionStore.update_stages 无 trace 参数 → TypeError
- PipelineResult 无 trace 字段 → 构造/访问 AttributeError
- get_status 响应无 trace → KeyError/断言失败
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from inkflow.core.database import ensure_agent_executions_trace_column
from inkflow.domain.models.agent_pipeline import PipelineContext
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.domain.services.agent_service import AgentService
from inkflow.infrastructure.agent.langgraph_pipeline import LangGraphAgentPipeline
from inkflow.infrastructure.agent.pipeline_templates import get_template

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
    "trace TEXT, created_at DATETIME NOT NULL",
)


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


class TestTraceMigration:
    """ensure_agent_executions_trace_column 幂等迁移三形态（spec §5 错误表）。"""

    def test_old_db_gets_trace_column(self, tmp_path) -> None:
        """旧库：agent_executions 无 trace → 迁移后补列（幂等可重跑）。"""
        db = tmp_path / "old.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            conn.execute(text(OLD_SCHEMA))
        with engine.connect() as conn:
            assert "trace" not in _columns(conn, "agent_executions")
            ensure_agent_executions_trace_column(conn)
            assert "trace" in _columns(conn, "agent_executions")
            ensure_agent_executions_trace_column(conn)
            assert "trace" in _columns(conn, "agent_executions")
        engine.dispose()

    def test_new_db_noop(self, tmp_path) -> None:
        """新库：create_all 已含 trace → no-op 不改变列集。"""
        db = tmp_path / "new.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            conn.execute(text(NEW_SCHEMA))
        with engine.connect() as conn:
            before = _columns(conn, "agent_executions")
            ensure_agent_executions_trace_column(conn)
            assert _columns(conn, "agent_executions") == before
        engine.dispose()

    def test_missing_table_noop(self, tmp_path) -> None:
        """表不存在（全新环境）→ no-op 不抛错。"""
        db = tmp_path / "empty.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.connect() as conn:
            ensure_agent_executions_trace_column(conn)
            tables = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
            assert tables == []
        engine.dispose()


class FakeExecution:
    """镜像 AgentExecutionORM 的 get_status 消费面。"""

    def __init__(self, *, trace=None):
        self.id = "e1"
        self.pipeline = "builtin:write_auto"
        self.project_id = "p1"
        self.status = "completed"
        self.stages = []
        self.relations = []
        self.trace = trace
        self.final_output = "成品"
        self.total_duration_ms = 100
        self.error = ""
        self.hitl_payload = None


class FakeStore:
    def __init__(self, execution):
        self._execution = execution

    async def get_execution(self, execution_id: str):
        return self._execution


class TestExecutionStoreTrace:
    """ExecutionStore.update_stages 接受 trace 并落库。"""

    async def test_update_stages_with_trace_persists(self, test_engine) -> None:
        """update_stages(..., trace=[...]) → get_execution 读回 trace。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.agent.execution_store import ExecutionStore

        session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with session_factory() as session:
            store = ExecutionStore(session)
            exec_row = await store.create_execution("builtin:write_auto", "p1")
            trace = [
                {
                    "node": "architect",
                    "type": "stage",
                    "reasoning": "规划",
                    "tool_calls": [],
                    "output": "大纲",
                    "duration_ms": 10,
                    "ts": "2026-08-16T10:00:00Z",
                },
            ]
            await store.update_stages(
                execution_id=exec_row.id,
                stages=[],
                status="completed",
                final_output="成品",
                total_duration_ms=100,
                trace=trace,
            )
            got = await store.get_execution(exec_row.id)
            assert got is not None
            assert got.trace == trace

    async def test_update_stages_without_trace_defaults_empty(self, test_engine) -> None:
        """update_stages 不传 trace → trace 默认 []。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.agent.execution_store import ExecutionStore

        session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with session_factory() as session:
            store = ExecutionStore(session)
            exec_row = await store.create_execution("builtin:write_auto", "p1")
            await store.update_stages(execution_id=exec_row.id, stages=[], status="completed")
            got = await store.get_execution(exec_row.id)
            assert got is not None
            assert got.trace == []


class TestAgentServiceStatusTrace:
    """AgentService.get_status 响应含 trace（spec §3.1）。"""

    async def test_get_status_returns_trace(self) -> None:
        """执行记录含 trace → 响应 trace 透传。"""
        svc = AgentService(
            pipeline=None,
            db_session=None,
            store=FakeStore(
                FakeExecution(trace=[{"node": "architect", "type": "stage", "reasoning": "规划"}])
            ),
        )
        status = await svc.get_status("e1")
        assert status["trace"] == [{"node": "architect", "type": "stage", "reasoning": "规划"}]

    async def test_get_status_trace_defaults_empty(self) -> None:
        """执行记录无 trace 属性 → 响应 trace = []。"""
        svc = AgentService(
            pipeline=None, db_session=None, store=FakeStore(FakeExecution(trace=None))
        )
        status = await svc.get_status("e1")
        assert status["trace"] == []


class TestPipelineStageTrace:
    """LangGraphPipeline 执行收集 stage trace（spec §2.1 type=stage）。"""

    async def test_result_trace_contains_stage_entry(self) -> None:
        """chat 模板执行 → result.trace 含 node=chat 的 stage 条目（reasoning 非空）。"""
        llm = _MockLLM(["对话回复"])
        pipeline = LangGraphAgentPipeline(llm)
        tpl = get_template("builtin:chat")
        assert tpl is not None
        ctx = PipelineContext(project_id="p1", variables={"prompt": "你好"})
        result = await pipeline.execute(tpl.stages, ctx)
        assert result.trace, "PipelineResult.trace 应为非空列表"
        entry = result.trace[0]
        assert entry["node"] == "chat"
        assert entry["type"] == "stage"
        assert entry["reasoning"]


class _MockLLM:
    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0

    async def chat(self, messages, *, model=None, temperature=None, max_tokens=None, **kwargs):
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return ChatResponse(content=resp, model=model or "mock", finish_reason="stop")
        self.call_count += 1
        return ChatResponse(content=f"mock_{self.call_count}", model=model or "mock")
