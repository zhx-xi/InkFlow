"""F27 M3 run 仓储 RED 契约测试 — AgentRunRepository（真实 in-memory SQLite 轨）.

被测模块（全部未实现，1l repo 整模块 RED 形态）:
    from inkflow.infrastructure.database.repositories.agent_run_repo import (
        SQLiteAgentRunRepository,
    )

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. SQLiteAgentRunRepository（infrastructure/database/repositories/agent_run_repo.py
   新建，异步 SQLAlchemy，构造签名 `SQLiteAgentRunRepository(db_session: AsyncSession)`，
   镜像 ExecutionStore 模式）:

       class SQLiteAgentRunRepository:
           async def create(
               self, *, project_id: uuid.UUID, chapter_id: uuid.UUID | None,
               mode: str = "agentic",
           ) -> AgentRun:
               '''创建 running 状态的 run 记录，返回领域 AgentRun（id/created_at 回填）.'''
           async def get(self, run_id: str) -> AgentRun | None: ...
           async def list(
               self, project_id: uuid.UUID, limit: int = 20,
           ) -> tuple[list[AgentRun], int]: ...
           async def update_result(
               self, run_id: str, *, status: AgentRunStatus,
               steps: list[AgentStep], final_content: str,
               draft_id: str | None, model: str,
               token_usage_total: int, terminated_by: str,
           ) -> AgentRun | None:
               '''run 结束后一次性写回（steps JSON 快照全量，决策轨迹持久化）.'''

2. AgentRunORM（infrastructure/database/models/agent_run.py 新建）:
   - 表名 agent_runs；列: id(str uuid4 主键) / project_id(FK projects.id, CASCADE) /
     chapter_id(FK chapters.id, nullable, CASCADE) / mode(str default "agentic") /
     status(str default "running") / steps(JSON default list) /
     final_content(Text default "") / draft_id(str nullable) / model(str default "") /
     token_usage_total(Integer default 0) / terminated_by(str default "") /
     created_at(DateTime UTC) / updated_at(DateTime UTC)
   - steps JSON 快照（Q4 拍板 A：与 AgentExecutionORM.stages JSON 先例一致）

3. 领域 AgentRun 依赖（domain/models/agent_run.py 新建，Pydantic）:
   - AgentToolCall / AgentStep / AgentRunStatus / AgentRun（见
     test_agentic_writer_service.py 设计假设 1——两文件契约同源）

RED 预期
--------
收集期失败（1l 整模块 RED 形态: pytest exit 2 / collected 0 items / 1 error）:
    ModuleNotFoundError: No module named
    'inkflow.infrastructure.database.repositories.agent_run_repo'
顶部仅 import 主契约模块（agent_run_repo）；ORM 惰性导入在 create_all 之前
（规则 1l）。同时缺失 domain.models.agent_run —— 顶部 import 报字母序首个
缺失模块（inkflow.domain.models.agent_run），GREEN 后 agent_run_repo 缺失
报 agent_run_repo——两者同批落地。

asyncio 模式: 本 venv（pytest-asyncio 1.4.0）实测头部 asyncio: mode=Mode.AUTO
（pyproject asyncio_mode = "auto" 生效）；文件级 pytestmark = pytest.mark.asyncio
双保险（STRICT/AUTO 两种模式均成立），全部用例 async def。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.agent_run import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentToolCall,
)
from inkflow.infrastructure.database.repositories.agent_run_repo import (
    SQLiteAgentRunRepository,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_step(index: int, tool_name: str = "search_characters") -> AgentStep:
    return AgentStep(
        index=index,
        message_content="",
        tool_calls=[
            AgentToolCall(
                step_index=index,
                tool_name=tool_name,
                arguments={"project_id": str(PROJECT_ID)},
                result='{"ok": true, "data": []}',
            )
        ],
        tokens=120,
    )


def _make_steps(n: int = 2) -> list[AgentStep]:
    return [_make_step(i) for i in range(n)]


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库.

    ORM 惰性导入必须在 create_all 之前（规则 1l）——Base.metadata 需先注册
    新表（AgentRunORM/ProjectORM），否则 create_all 不建 agent_runs 表.
    """

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session):
    """1 个项目（agent_runs 表 FK 依赖 projects.id）."""
    from inkflow.infrastructure.database.models.project import ProjectORM

    proj = ProjectORM(name="测试项目")
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


@pytest.mark.integration
class TestAgentRunRepository:
    """SQLiteAgentRunRepository 集成测试."""

    async def test_create_run(self, db_session, project):
        """契约①: create 落库 running 状态，返回领域 AgentRun 含 id/时间戳."""
        repo = SQLiteAgentRunRepository(db_session)

        run = await repo.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, mode="agentic")

        assert isinstance(run, AgentRun)
        assert run.status == AgentRunStatus.RUNNING
        assert run.mode == "agentic"
        assert run.project_id == PROJECT_ID
        assert run.steps == []
        assert isinstance(run.id, str)
        assert isinstance(run.created_at, datetime)

        # 持久化验证：读回
        fetched = await repo.get(run.id)
        assert fetched is not None
        assert fetched.status == AgentRunStatus.RUNNING

    async def test_get_missing_returns_none(self, db_session, project):
        """契约②: get 对缺失 run 返回 None."""
        repo = SQLiteAgentRunRepository(db_session)

        assert await repo.get("00000000-0000-0000-0000-000000000000") is None

    async def test_update_result_completed(self, db_session, project):
        """契约③: update_result 写回完成态（steps JSON 快照全量 + terminated_by）."""
        repo = SQLiteAgentRunRepository(db_session)
        run = await repo.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, mode="agentic")

        updated = await repo.update_result(
            run.id,
            status=AgentRunStatus.COMPLETED,
            steps=_make_steps(2),
            final_content="最终正文。",
            draft_id="draft-1",
            model="deepseek/deepseek-chat",
            token_usage_total=8120,
            terminated_by="llm",
        )

        assert updated is not None
        assert updated.status == AgentRunStatus.COMPLETED
        assert updated.terminated_by == "llm"
        assert updated.final_content == "最终正文。"
        assert updated.draft_id == "draft-1"
        assert updated.token_usage_total == 8120

        # 持久化读回：steps JSON 快照往返无损
        fetched = await repo.get(run.id)
        assert fetched is not None
        assert len(fetched.steps) == 2
        assert fetched.steps[0].tool_calls[0].tool_name == "search_characters"
        assert fetched.steps[0].tokens == 120
        assert fetched.status == AgentRunStatus.COMPLETED

    async def test_update_result_guardrail(self, db_session, project):
        """契约④: guardrail 终止同样写回（terminated_by_guardrail + 产物保留）."""
        repo = SQLiteAgentRunRepository(db_session)
        run = await repo.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, mode="agentic")

        updated = await repo.update_result(
            run.id,
            status=AgentRunStatus.TERMINATED_BY_GUARDRAIL,
            steps=_make_steps(3),
            final_content="",
            draft_id=None,
            model="deepseek/deepseek-chat",
            token_usage_total=5000,
            terminated_by="max_steps",
        )

        assert updated is not None
        assert updated.status == AgentRunStatus.TERMINATED_BY_GUARDRAIL
        assert updated.terminated_by == "max_steps"
        # 产物保留：steps 已落库可读
        fetched = await repo.get(run.id)
        assert fetched is not None
        assert len(fetched.steps) == 3

    async def test_update_result_missing_returns_none(self, db_session, project):
        """契约⑤: update_result 对缺失 run 返回 None."""
        repo = SQLiteAgentRunRepository(db_session)

        result = await repo.update_result(
            "00000000-0000-0000-0000-000000000000",
            status=AgentRunStatus.COMPLETED,
            steps=[],
            final_content="",
            draft_id=None,
            model="",
            token_usage_total=0,
            terminated_by="llm",
        )
        assert result is None

    async def test_list_runs(self, db_session, project):
        """契约⑥: list 按 project_id 过滤，created_at 倒序 + 分页."""
        repo = SQLiteAgentRunRepository(db_session)

        r1 = await repo.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, mode="agentic")
        r2 = await repo.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, mode="agentic")
        await repo.create(
            project_id=uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            chapter_id=None,
            mode="agentic",
        )

        items, total = await repo.list(project_id=PROJECT_ID)
        assert total == 2
        assert {r.id for r in items} == {r1.id, r2.id}

        # limit 分页
        items_1, total_1 = await repo.list(project_id=PROJECT_ID, limit=1)
        assert len(items_1) == 1
        assert total_1 == 2
