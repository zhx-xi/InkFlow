"""#1317 契约 RED — 对账加实例归属判据（修跨实例误伤 running）。

先读 ``.hermes/plans/w18b-plan.md`` §6/§7 后再编码。

缺陷（rc4 实测，issue #1317）：``core/startup_reconcile.py`` 的
``UPDATE writing_plans SET status='failed' WHERE status='running'`` **无实例归属判据**
→ 多内核并存时，新实例 lifespan 对账把**别实例正在跑的 run** 打成 failed
（progress_reason 写「内核重启对账」，counters 归零）。

修复方向（方案 1a，零迁移）：归属标记放 ``writing_plans.limits``（LenientJSON 列，
已实测可往返），字段名 ``kernel_owner_pid``（int）；存活判据经**关键字参数注入**
（core/ 禁止 import infrastructure；注入点是 api/app.py 的 lifespan）。

契约语义（issue 审计评论已拍板）：

===============  ==========================  ==================  ==========================
#                场景                        owner 存活          期望
===============  ==========================  ==================  ==========================
1                本实例遗留（owner 已死）     False               置 failed（释放名额）
2                **他实例存活**（核心场景）  True                **不碰**（修复前误伤）
3                他实例已死                  False               置 failed（合理释放）
4                无 owner（历史遗留行）      缺失                置 failed（兼容旧行为）
===============  ==========================  ==================  ==========================

可证伪自证（已实测）：只给被测函数加 ``**kwargs`` 兼容壳、不加归属逻辑
→ ``test_owner_other_instance_alive_is_not_touched`` 与
``test_mixed_rows_only_unowned_and_dead_released`` 均以**真断言**失败
（``应只释放 2 行，实际 3``），证明断言咬的是行为而非签名。

🔴 测试装置形态（踩坑记录）：engine 必须**在异步用例内**创建并在用例内 dispose
（镜像 ``test_startup_reconcile_953.py:47``）。**不要**改用 conftest 的
``test_engine`` fixture —— 该 fixture 的 ``create_all`` 跑在 fixture 自己的 event loop，
而 pytest-asyncio(auto) 给用例另起 loop → ``:memory:`` 库「表不在」，
首个用例报 ``no such table: writing_plans``（本轮实测踩过）。
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

import pytest

# 🔴 模块级 import ORM：必须在任何 ``Base.metadata.create_all()`` **之前**完成
# 注册，否则 ``create_all`` 建不出 ``writing_plans`` 表 → 首个用例报
# ``no such table: writing_plans``（本轮实测：懒 import（在 create_all 之后）必踩）。
from inkflow.infrastructure.database.models.writing_plan import WritingPlanORM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

REASON_953 = "内核重启对账：运行遗留 running 态（#953）"
OWNER_KEY = "kernel_owner_pid"


class _Db:
    """per-test 真实 in-memory SQLite（引擎在用例 loop 内建、用例内释放）。"""

    def __init__(self, engine: object, factory: async_sessionmaker[AsyncSession]) -> None:
        self.engine = engine
        self.factory = factory

    async def seed(self, rows: list[tuple[str, str, dict]]) -> None:
        """rows = [(plan_id, title, limits)]，一律 status='running'。"""

        async with self.factory() as session:
            session.add_all(
                [
                    WritingPlanORM(
                        id=pid,
                        project_id=str(uuid.UUID(int=10)),
                        title=title,
                        status="running",
                        limits=limits,
                    )
                    for pid, title, limits in rows
                ]
            )
            await session.commit()

    async def add_status(self, plan_id: str, title: str, status: str) -> None:
        """额外插一行指定状态的 plan（如 ready）。"""

        async with self.factory() as session:
            session.add(
                WritingPlanORM(
                    id=plan_id,
                    project_id=str(uuid.UUID(int=10)),
                    title=title,
                    status=status,
                    limits={},
                )
            )
            await session.commit()

    async def status_of(self, plan_id: str) -> tuple[str, str | None]:

        async with self.factory() as session:
            row = await session.get(WritingPlanORM, plan_id)
            assert row is not None
            return row.status, row.progress_reason

    async def dispose(self) -> None:
        await self.engine.dispose()  # type: ignore[attr-defined]


async def _make_db() -> _Db:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from inkflow.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return _Db(engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))


async def test_owner_other_instance_alive_is_not_touched() -> None:
    """【核心场景·可证伪】他实例存活 → 本实例对账**不碰**它（修复前被误伤为 failed）。

    可证伪自证：去掉实现里的 ``is_alive(owner)`` 判据（一律放行）→ 本用例必 FAIL。
    """
    from inkflow.core.startup_reconcile import reconcile_stale_running_plans

    db = await _make_db()
    try:
        alive_pid = os.getpid()  # 真实存活进程，充当「别实例」
        victim = str(uuid.UUID(int=201))
        await db.seed([(victim, "他实例正在跑的书", {"max_chapters": 10, OWNER_KEY: alive_pid})])

        count = await reconcile_stale_running_plans(
            db.factory, is_alive=lambda pid: pid == alive_pid
        )

        status, reason = await db.status_of(victim)
        assert status == "running", (
            f"#1317: 他实例（pid={alive_pid}）存活时 running 行必须保持 running，实际 {status!r}"
        )
        assert reason != REASON_953, "不应被对账写入「重启遗留」原因"
        assert count == 0, f"存活他实例不应计入处理行数，实际 {count}"
    finally:
        await db.dispose()


async def test_owner_this_instance_dead_is_released() -> None:
    """本实例遗留（owner 已死，含本进程重启后的场景）→ 释放为 failed。"""
    from inkflow.core.startup_reconcile import reconcile_stale_running_plans

    db = await _make_db()
    try:
        dead_pid = 999_999_999
        plan_id = str(uuid.UUID(int=202))
        await db.seed([(plan_id, "本实例遗留的书", {"max_chapters": 10, OWNER_KEY: dead_pid})])

        count = await reconcile_stale_running_plans(
            db.factory, is_alive=lambda pid: pid == os.getpid()
        )

        status, reason = await db.status_of(plan_id)
        assert status == "failed", f"owner 已死的 running 行应释放为 failed，实际 {status!r}"
        assert reason == REASON_953, f"progress_reason 应为 #953 文案，实际 {reason!r}"
        assert count == 1, f"应处理 1 行，实际 {count}"
    finally:
        await db.dispose()


async def test_owner_other_instance_dead_is_released() -> None:
    """他实例已死（崩溃遗留）→ 释放为 failed（合理回收，不因「非本实例」而漏放）。"""
    from inkflow.core.startup_reconcile import reconcile_stale_running_plans

    db = await _make_db()
    try:
        dead_pid = 999_999_998
        plan_id = str(uuid.UUID(int=203))
        await db.seed([(plan_id, "他实例崩溃遗留", {"max_chapters": 10, OWNER_KEY: dead_pid})])

        count = await reconcile_stale_running_plans(db.factory, is_alive=lambda _pid: False)

        status, _ = await db.status_of(plan_id)
        assert status == "failed", f"owner 已死的 running 行应释放为 failed，实际 {status!r}"
        assert count == 1, f"应处理 1 行，实际 {count}"
    finally:
        await db.dispose()


async def test_owner_missing_keeps_legacy_behaviour() -> None:
    """兼容语义：无 owner 标记的历史遗留行 → 保持现行为（置 failed）。"""
    from inkflow.core.startup_reconcile import reconcile_stale_running_plans

    db = await _make_db()
    try:
        plan_id = str(uuid.UUID(int=204))
        await db.seed([(plan_id, "历史遗留无 owner", {"max_chapters": 10})])

        count = await reconcile_stale_running_plans(db.factory, is_alive=lambda _pid: True)

        status, reason = await db.status_of(plan_id)
        assert status == "failed", f"无 owner 的旧行应保持现行为（failed），实际 {status!r}"
        assert reason == REASON_953
        assert count == 1, f"应处理 1 行，实际 {count}"
    finally:
        await db.dispose()


async def test_mixed_rows_only_unowned_and_dead_released() -> None:
    """混合批次：存活他实例留下、其余释放；返回行数与实际改动一致。"""
    from inkflow.core.startup_reconcile import reconcile_stale_running_plans

    db = await _make_db()
    try:
        alive_pid = os.getpid()
        r_alive = str(uuid.UUID(int=205))
        r_dead = str(uuid.UUID(int=206))
        r_none = str(uuid.UUID(int=207))
        r_ready = str(uuid.UUID(int=208))
        await db.seed(
            [
                (r_alive, "存活他实例", {"max_chapters": 10, OWNER_KEY: alive_pid}),
                (r_dead, "已死他实例", {"max_chapters": 10, OWNER_KEY: 999_999_997}),
                (r_none, "无 owner", {"max_chapters": 10}),
            ]
        )
        await db.add_status(r_ready, "ready 行", "ready")

        count = await reconcile_stale_running_plans(
            db.factory, is_alive=lambda pid: pid == alive_pid
        )

        assert count == 2, f"应只释放 2 行（已死 + 无 owner），实际 {count}"
        assert (await db.status_of(r_alive))[0] == "running"
        assert (await db.status_of(r_dead))[0] == "failed"
        assert (await db.status_of(r_none))[0] == "failed"
        assert (await db.status_of(r_ready))[0] == "ready", "ready 行不应被对账改动"
    finally:
        await db.dispose()


@pytest.mark.parametrize("pid_value", [None, "not-an-int", True])
async def test_malformed_owner_is_treated_as_unowned(pid_value: object) -> None:
    """畸形 owner（None / 非法串 / bool）→ 按「无 owner」处置（不抛异常，走兼容路径）。

    bool 单列：Python 里 ``True`` 是 ``int`` 子类，若实现用 ``isinstance(v, int)``
    会把它当 pid=1 去探测 → 结果取决于机器上 pid 1 是否存在（不可判定）。
    契约要求它归入「无 owner」，保证行为确定。
    """
    from inkflow.core.startup_reconcile import reconcile_stale_running_plans

    db = await _make_db()
    try:
        plan_id = str(uuid.UUID(int=210))
        await db.seed([(plan_id, "畸形 owner", {"max_chapters": 10, OWNER_KEY: pid_value})])

        count = await reconcile_stale_running_plans(db.factory, is_alive=lambda _pid: True)

        status, reason = await db.status_of(plan_id)
        assert status == "failed", f"畸形 owner 应按无 owner 处置（failed），实际 {status!r}"
        assert reason == REASON_953
        assert count == 1, f"应处理 1 行，实际 {count}"
    finally:
        await db.dispose()


async def test_is_alive_none_preserves_positional_call_contract() -> None:
    """既有契约不变：``reconcile_stale_running_plans(factory)`` 位置调用仍工作。

    默认 ``is_alive=None`` → 退化为「无法判定存活」→ 保持现行为（全部释放）。
    这是 #953 的重启释放语义向后兼容面，也是既有契约文件的原始调用形态。
    """
    from inkflow.core.startup_reconcile import reconcile_stale_running_plans

    db = await _make_db()
    try:
        with_owner = str(uuid.UUID(int=211))
        no_owner = str(uuid.UUID(int=212))
        await db.seed(
            [
                (with_owner, "带 owner", {"max_chapters": 10, OWNER_KEY: 999_999_996}),
                (no_owner, "无 owner", {"max_chapters": 10}),
            ]
        )

        count = await reconcile_stale_running_plans(db.factory)

        assert count == 2, f"is_alive 缺省时应释放全部 running 行，实际 {count}"
        assert (await db.status_of(with_owner))[0] == "failed"
        assert (await db.status_of(no_owner))[0] == "failed"
    finally:
        await db.dispose()


async def test_owner_survives_repo_round_trip() -> None:
    """载体契约：``limits['kernel_owner_pid']`` 经 **repo 写 + 读**往返不失真（LenientJSON）。

    断言的是**生产链路同一函数**（``update_writing_plan`` 写入 → ``get_writing_plan`` 读回），
    而非手工构造输入 —— 否则只是验证 SQLite 能存 JSON，证明不了归属标记在生产上落得下去。
    """
    from inkflow.infrastructure.repositories.book_repository import SQLiteBookRepository

    db = await _make_db()
    try:
        plan_id = str(uuid.UUID(int=213))
        await db.seed([(plan_id, "往返", {"max_chapters": 10})])

        session = db.factory()
        repo = SQLiteBookRepository(session)  # type: ignore[arg-type]
        plan = await repo.get_writing_plan(plan_id)
        assert plan is not None
        plan.limits["kernel_owner_pid"] = 12345  # 生产写入点就是这样写 limits 的
        await repo.update_writing_plan(plan)
        await session.close()

        session2 = db.factory()
        repo2 = SQLiteBookRepository(session2)  # type: ignore[arg-type]
        reloaded = await repo2.get_writing_plan(plan_id)
        assert reloaded is not None
        assert reloaded.limits.get(OWNER_KEY) == 12345, (
            f"owner 标记必须经 repo 写+读往返保真，实际 {reloaded.limits!r}"
        )
        assert reloaded.limits.get("max_chapters") == 10, "原有 limits 键不得被覆写丢失"
        await session2.close()
    finally:
        await db.dispose()
