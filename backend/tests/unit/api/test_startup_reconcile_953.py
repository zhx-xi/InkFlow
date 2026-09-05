"""#953 契约 RED-3a — 启动 reconcile（writing_plans 遗留 running 态对账）。

先读契约 ``.hermes/plans/contract-953.md`` §2 RED-3a / §1d 后再编码。

被测（GREEN 才实现）：
    from inkflow.core.startup_reconcile import reconcile_stale_running_plans
    （GREEN round-2 迁移：原拟 core/database.py，因 database.py 破 900 行护栏
    拆出独立模块 core/startup_reconcile.py，函数语义与 lifespan wiring 不变）

RED 预期
--------
- ``test_reconcile_marks_running_plans_failed``【R】：``reconcile_stale_running_plans``
  尚不存在 → 函数体 import 抛 ``ImportError/ModuleNotFoundError``（镜像契约 RED 惯例，
  import 放用例函数体内，避免收集期 ImportError 吞掉整个文件）。
- ``test_lifespan_wires_reconcile``【R】：lifespan 尚未调用 reconcile → 源文本断言 STRING 缺失。

GREEN 契约（§1d）
-----------------
``reconcile_stale_running_plans(session_factory) -> int``：把
``writing_plans.status='running'`` 的行置为 ``'failed'``，``progress_reason`` 写
``'内核重启对账：运行遗留 running 态（#953）'``，返回处理行数；lifespan 启动段（yield 前、
seed 之后）调用之。
"""

from __future__ import annotations

import uuid


async def test_reconcile_marks_running_plans_failed() -> None:
    """【R】真实 in-memory aiosqlite：running 行 → failed + progress_reason；ready 不动；返回 1。

    契约 §2 RED-3a：running 行变 failed 且 progress_reason 非空；ready 行不动；返回值==1。
    文案以 §1d 原文断言（GREEN 以此为准）。
    """
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from inkflow.core.database import Base
    from inkflow.core.startup_reconcile import reconcile_stale_running_plans
    from inkflow.infrastructure.database.models.writing_plan import WritingPlanORM

    # 真实 in-memory aiosqlite（同 loop 内建、同 loop 内用，避免跨事件循环绑定问题）
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    running_id = str(uuid.UUID(int=1))
    ready_id = str(uuid.UUID(int=2))
    project_id = str(uuid.UUID(int=10))

    async with factory() as session:
        session.add_all(
            [
                WritingPlanORM(
                    id=running_id,
                    project_id=project_id,
                    title="running 书",
                    status="running",
                ),
                WritingPlanORM(
                    id=ready_id,
                    project_id=project_id,
                    title="ready 书",
                    status="ready",
                ),
            ]
        )
        await session.commit()

    count = await reconcile_stale_running_plans(factory)

    assert count == 1, f"reconcile 应处理 1 行 running，实际 {count}"

    async with factory() as session:
        running = await session.get(WritingPlanORM, running_id)
        ready = await session.get(WritingPlanORM, ready_id)

    assert running is not None, "running 行应仍存在"
    assert running.status == "failed", f"running 行应转 failed，实际 {running.status!r}"
    assert running.progress_reason == "内核重启对账：运行遗留 running 态（#953）", (
        f"progress_reason 应按 §1d 文案写入，实际 {running.progress_reason!r}"
    )
    assert ready is not None and ready.status == "ready", "ready 行不应被对账改动"


def test_lifespan_wires_reconcile() -> None:
    """【R】最小 wiring 守护：lifespan 启动段必须调用 reconcile_stale_running_plans
    且位于 yield 之前。

    当前实现（app.py L101-186）lifespan 仅在 seed 后启动 scheduler，从未调用
    ``reconcile_stale_running_plans`` → 源文本断言字符串缺失 → FAIL。
    该守护防「函数存在但从不调用」——GREEN 在 seed 之后（app.py L149-157 区块后）插入调用行即转绿。

    注释：全量 TestClient(app) 触发 create_tables/seed/scheduler 副作用过重，父侧已核实
    落点 app.py:149-157 后，故选可靠形态②（源码级断言）。
    """
    import importlib
    import inspect

    # ⚠️ 包属性遮蔽陷阱：inkflow/api/__init__.py 的 `from inkflow.api.app import app`
    # 把包属性 inkflow.api.app 遮蔽为 FastAPI 实例，`import x.y.z as m` 经 getattr
    # 解析会拿到 FastAPI 对象 → 必须 importlib.import_module 直取真模块（sys.modules）。
    app_mod = importlib.import_module("inkflow.api.app")

    # @asynccontextmanager 会以 functools.wraps 包裹原 async 生成器，__wrapped__ 指向原始函数
    lifespan_fn = getattr(app_mod.lifespan, "__wrapped__", app_mod.lifespan)
    source = inspect.getsource(lifespan_fn)

    assert "reconcile_stale_running_plans" in source, (
        "RED-3a: lifespan 启动钩子必须在 seed 后调用 reconcile_stale_running_plans(异步工厂)"
    )
    assert source.index("reconcile_stale_running_plans") < source.index("yield"), (
        "RED-3a: reconcile 必须在 lifespan yield 之前执行（启动段），"
        "防函数存在但从不调用"
    )
