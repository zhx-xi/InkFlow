"""#1185 A9/A11 · 写作轨 factory 授权与上下文注入 — API 装配层 RED 契约。

权威来源：`.hermes/audit-writing-chain-20260915.md` P1-4（F58/F39 授权未接）、
P0-3（F3 轨上下文恒空）。

为什么在 API 层
--------------
两处 writer factory 都是**依赖函数内的闭包**
（`api/routers/books.py::get_book_service._writer_factory`、
`api/deps_agentic_writer.py::get_agentic_writer_service._build_agent`），
单元测试无法触及。必须 import 真实依赖函数、patch `build_agentic_writer`、
经公开服务方法驱动（模式镜像 `test_books_coverage_backfill_1137.py:304-337`）。

契约
----
1. **A9**：两 factory 均须把 `tool_ids` / `skill_ids` 传给 `build_agentic_writer`。
   当前两者 kwargs 均无这两键 → `_WRITER_READER_NAMES` 硬编码兜底、
   `skill_ids` 恒 None → `_append_skills` 永不执行（F39 全写作轨失效）。
   ⚠️ 两条 A9 用例属 #1181（W2 范畴），2026-09-15 已拆出至
   `.hermes/pending-w2/tests/api/test_writer_factory_authorization.py`。
2. **A11**：`get_writing_service`（`api/deps.py`）须注入非 Null 的
   `context_provider`（F6 `ContextService`）。当前不传 → 恒落
   `NullContextProvider`（`writing_service.py:58`）→ F3 轨上下文恒空。

现状（2026-09-15）：A11 已随 W1-B（commit `9192b5c`）转绿；A9 两条已拆出交 W2。
下方 `_seed` / `_patch_pipelines` 是 A9 用例的装配夹具，保留供 W2 恢复时复用。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.api.routers.books import get_book_service
from inkflow.infrastructure.database.models.outline import OutlineORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.writing_plan import WritingPlanORM

SEED_PROJECT_ID = uuid.UUID(int=1)
"""projects.id 为 INTEGER 主键 → 领域 id = uuid.UUID(int=orm.id)。"""

pytestmark = pytest.mark.asyncio


async def _seed(db_session, *, plan_id: uuid.UUID) -> None:
    """落表：project + chapter outline + writing plan（真实 repo，非 mock）。

    口径镜像 `test_books_coverage_backfill_1137.py::_seed_plan`：
    WritingPlanORM.id / project_id 存**字符串**形态的 UUID，且显式 commit。
    """
    db_session.add(ProjectORM(id=SEED_PROJECT_ID.int, name="测试项目", language="zh-CN"))
    db_session.add(
        OutlineORM(
            id=11,
            project_id=SEED_PROJECT_ID.int,
            name="第一卷",
            level="volume",
            sort_order=0,
        )
    )
    db_session.add(
        OutlineORM(
            id=10,
            project_id=SEED_PROJECT_ID.int,
            name="第一章大纲",
            level="chapter",
            chapter_id=20,
            sort_order=0,
        )
    )
    db_session.add(
        WritingPlanORM(
            id=str(plan_id),
            project_id=str(SEED_PROJECT_ID),
            title="测试计划",
            status="ready",
            root_outline_id=str(uuid.UUID(int=11)),
            character_ids=[],
            limits={"max_chapters": 5, "max_agent_calls": 50},
            progress={},
            execution_refs={},
        )
    )
    await db_session.commit()


@pytest.fixture(autouse=True)
def _patch_pipelines(monkeypatch):
    """隔离 books.py 模块级 pipeline 单例（镜像 test_books_coverage_backfill_1137）。"""
    monkeypatch.setattr("inkflow.api.routers.books._book_volume_pipeline", None, raising=False)
    monkeypatch.setattr("inkflow.api.routers.books._book_agentic_pipeline", None, raising=False)
    monkeypatch.setattr(
        "inkflow.api._llm_resolver.resolve_llm_credentials",
        lambda *a, **kw: ("model", "key", "url"),
    )


# ── A9：books.py writer factory 透传 tool_ids / skill_ids ──────────────


async def test_books_writer_factory_forwards_authorization(db_session, monkeypatch):
    """`get_book_service` 的 `_writer_factory` 须把 tool_ids/skill_ids 透传。

    可证伪性：factory 不传（现状）→ captured 无这两键 → FAIL。
    """
    plan_id = uuid.UUID(int=1)
    await _seed(db_session, plan_id=plan_id)

    captured: dict = {}

    def _fake_writer(**kwargs):
        captured.update(kwargs)
        agent = MagicMock()
        agent.invoke = AsyncMock(
            return_value={"messages": [{"type": "ai", "content": "第一章正文内容"}]}
        )
        return agent

    monkeypatch.setattr(
        "inkflow.infrastructure.agent.agentic_writer.build_agentic_writer", _fake_writer
    )

    svc = get_book_service(db_session)
    await svc.write_book(plan_id)

    assert "tool_ids" in captured, "books.py writer factory 必须透传 tool_ids"
    assert "skill_ids" in captured, "books.py writer factory 必须透传 skill_ids"


# ── A9：deps_agentic_writer.py factory 透传 tool_ids / skill_ids ───────


async def test_deps_agentic_writer_factory_forwards_authorization(monkeypatch):
    """`get_agentic_writer_service` 的 `_build_agent` 须透传 tool_ids/skill_ids。

    可证伪性：不传（现状）→ captured 无这两键 → FAIL。
    """
    from inkflow.api import deps_agentic_writer as daw_mod

    captured: dict = {}

    def _fake_writer(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "inkflow.infrastructure.agent.agentic_writer.build_agentic_writer", _fake_writer
    )

    # 闭包捕获于 get_agentic_writer_service 返回值内部 —— 经其公开面驱动
    svc = daw_mod.get_agentic_writer_service(MagicMock())
    factory = getattr(svc, "_agent_factory", None)
    assert factory is not None, "AgenticWriterService 未暴露 agent_factory"

    request = MagicMock()
    request.project_id = uuid.uuid4()
    request.chapter_id = uuid.uuid4()
    factory(request)  # `_build_agent` 为同步函数（deps_agentic_writer.py:79）

    assert "tool_ids" in captured, "deps_agentic_writer.py 必须透传 tool_ids"
    assert "skill_ids" in captured, "deps_agentic_writer.py 必须透传 skill_ids"


# ── A11：F3 轨 context_provider 注入非 Null ────────────────────────────


async def test_get_writing_service_injects_real_context_provider(db_session):
    """`get_writing_service` 须注入真实 F6 context_provider（非 Null）。

    当前不传 → 恒落 `NullContextProvider`（P0-3）→ FAIL。
    可证伪性：删掉 context_provider 注入 → FAIL。
    """
    from inkflow.api.deps import get_writing_service
    from inkflow.domain.services.writing_service import NullContextProvider

    svc = get_writing_service(db_session)

    provider = svc._context_provider
    assert not isinstance(provider, NullContextProvider), (
        "F3 轨必须注入真实 ContextProvider（F6），当前为 NullContextProvider"
    )
