"""#77 内核进程化 — SQLite WAL + busy_timeout PRAGMA 测试契约（RED 阶段）。

本文件只为 ``inkflow.core.database`` 的 PRAGMA 应用函数定义测试契约
（spec §2.4 / §2.6 / §2.7 M3）。测试不依赖真实 async engine 或服务启动，
一律用 Python 标准库 ``sqlite3`` 直接调用函数——轻量、可靠、零 I/O 副作用。

契约函数
--------
公开名：``apply_sqlite_pragma(dbapi_connection) -> None``
（位于 ``backend/src/inkflow/core/database.py``）。

- 入参 ``dbapi_connection``：暴露同步 ``cursor()`` 接口的连接对象。
  本测试一律传标准库 ``sqlite3.Connection``。生产路径（SQLAlchemy
  ``engine.sync_engine`` 的 "connect" 事件）传入的是 aiosqlite 方言的
  ``AsyncAdapt_aiosqlite_connection`` 适配器——其 ``cursor()`` 是同步方法
  且返回的 cursor 提供同步 ``execute``（已核对 SQLAlchemy 2.0.51 + aiosqlite
  0.22.1 源码），与 ``sqlite3.Connection`` 满足同一接口，故本契约对两种
  连接均成立，GREEN 实现无需针对 aiosqlite 写分支。
- 行为（spec §2.4 连接工厂统一处）：
  1. ``PRAGMA journal_mode=WAL``
  2. ``PRAGMA busy_timeout=<config.db_busy_timeout_ms>``
     busy_timeout 数值必须在**调用时**从 ``inkflow.core.config.config``
     单例读取（不是 import 时快照、不是默认参数固化），默认 5000。
- 返回 None；对同一连接重复调用幂等（不抛错、不改变已生效模式）。
- 内存库（:memory:）：``PRAGMA journal_mode=WAL`` 不抛错但无效，查询
  ``PRAGMA journal_mode`` 返回 ``'memory'``（SQLite 原生行为）——测试按
  连接类型分支断言，内存库不断言 'wal'（spec §2.4 回归风险条款）。

事件监听器契约（本文件不直接测试，由 spec §2.6 集成（DB）行与 §2.7 M3 覆盖）
-----------------------------------------------------------------------------
``core/database.py`` 须同时按 spec §2.4 形态注册：

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        apply_sqlite_pragma(dbapi_connection)

监听器只做委托，PRAGMA 应用逻辑收敛在 ``apply_sqlite_pragma`` 单一函数，
保证 CLI/agent/GUI/MCP 所有进程经连接工厂（create_async_engine）统一生效。
本文件只钉住独立函数行为，不与 engine/aiosqlite 适配器耦合。

配置契约
--------
``InkFlowConfig`` 新增字段 ``db_busy_timeout_ms: int = 5000``
（spec §2.4 配置表）。本文件只断言默认值，不设置任何 ``INKFLOW_*``
环境变量。

RED 状态说明
------------
``apply_sqlite_pragma`` 尚未实现，模块级 from-import 在收集期抛
ImportError，属预期 RED 信号；GREEN 实现后本文件即全绿。
"""

import sqlite3

import sqlalchemy
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

from inkflow.core import database as db_module
from inkflow.core.config import config
from inkflow.core.database import _set_sqlite_pragma, apply_sqlite_pragma
from inkflow.infrastructure.database.models.project import (  # noqa: F401  # 注册表到 Base.metadata
    ProjectORM,
)


def _journal_mode(conn: sqlite3.Connection) -> str:
    """查询连接当前 journal_mode（小写字符串）。"""
    return conn.execute("PRAGMA journal_mode").fetchone()[0]


def _busy_timeout(conn: sqlite3.Connection) -> int:
    """查询连接当前 busy_timeout（毫秒）。"""
    return conn.execute("PRAGMA busy_timeout").fetchone()[0]


def test_config_db_busy_timeout_ms_default_is_5000():
    """配置契约：``config.db_busy_timeout_ms`` 默认值为 5000（int）。

    spec §2.4 配置表：`db_busy_timeout_ms | 5000 | SQLite busy_timeout
    （毫秒），多进程写并发时等待锁`。使用默认配置单例，不依赖任何
    ``INKFLOW_*`` 环境变量。
    """
    assert isinstance(config.db_busy_timeout_ms, int)
    assert config.db_busy_timeout_ms == 5000


def test_apply_sqlite_pragma_sets_journal_mode_wal_on_file_db(tmp_path):
    """文件库：调用后 ``PRAGMA journal_mode`` 返回 ``'wal'``。

    对应 spec §2.6 集成（DB）行与 §2.7 M3「文件库 PRAGMA journal_mode
    返回 wal」。WAL 是文件级持久设置（写入 DB 文件头），故关闭连接后
    用新连接重开同一文件库，journal_mode 仍应为 'wal'（跨连接生效，
    spec §2.4）。
    """
    db_path = tmp_path / "pragma_test.db"
    conn = sqlite3.connect(db_path)
    try:
        apply_sqlite_pragma(conn)
        assert _journal_mode(conn) == "wal"
    finally:
        conn.close()

    reopened = sqlite3.connect(db_path)
    try:
        assert _journal_mode(reopened) == "wal"
    finally:
        reopened.close()


def test_apply_sqlite_pragma_sets_busy_timeout_from_config_default(tmp_path):
    """文件库：调用后 ``PRAGMA busy_timeout`` 等于配置默认值 5000。

    busy_timeout 是连接级设置，须与 ``config.db_busy_timeout_ms`` 一致
    （spec §2.6 集成（DB）行「PRAGMA busy_timeout = 配置值」、§2.7 M3
    「busy_timeout 为配置值」）。
    """
    conn = sqlite3.connect(tmp_path / "pragma_busy.db")
    try:
        apply_sqlite_pragma(conn)
        assert _busy_timeout(conn) == config.db_busy_timeout_ms
        assert _busy_timeout(conn) == 5000
    finally:
        conn.close()


def test_apply_sqlite_pragma_reads_busy_timeout_at_call_time(monkeypatch, tmp_path):
    """busy_timeout 数值在调用时读取 config，而非 import 时快照。

    契约：实现不得把 ``config.db_busy_timeout_ms`` 缓存在模块级常量或
    函数默认参数中，须在函数体内读取（spec §2.4 示意 f-string 位于函数
    内）。pydantic BaseSettings 默认允许属性赋值，monkeypatch 直接修改
    单例属性并在测试后自动还原；不涉及任何环境变量。
    """
    monkeypatch.setattr(config, "db_busy_timeout_ms", 12345)
    conn = sqlite3.connect(tmp_path / "pragma_custom.db")
    try:
        apply_sqlite_pragma(conn)
        assert _busy_timeout(conn) == 12345
    finally:
        conn.close()


def test_apply_sqlite_pragma_is_idempotent_on_file_db(tmp_path):
    """同一文件连接重复调用不抛错，且模式与超时保持生效值。

    spec §2.4 回归风险条款：PRAGMA 对既有 WAL 连接重复执行必须幂等
    （连接池复用场景：每个新连接都会触发 connect 事件）。
    """
    conn = sqlite3.connect(tmp_path / "pragma_idem.db")
    try:
        apply_sqlite_pragma(conn)
        apply_sqlite_pragma(conn)
        assert _journal_mode(conn) == "wal"
        assert _busy_timeout(conn) == 5000
    finally:
        conn.close()


def test_apply_sqlite_pragma_on_memory_db_no_raise():
    """内存库：调用不抛错，journal_mode 为 'memory'（不断言 'wal'）。

    spec §2.4：内存库不支持 WAL，``PRAGMA journal_mode=WAL`` 返回
    'memory'，PRAGMA 执行不报错但无效果——幂等即可。既有 1589 个测试
    多为内存库（sqlite+aiosqlite:///:memory:），此分支是 WAL 改动
    零回归的前提。
    """
    conn = sqlite3.connect(":memory:")
    try:
        apply_sqlite_pragma(conn)  # 若抛错，本测试直接 ERROR（即 RED）
        assert _journal_mode(conn) == "memory"
    finally:
        conn.close()


def test_apply_sqlite_pragma_sets_busy_timeout_before_wal():
    """根因契约（S3b M2）：busy_timeout 必须先于 journal_mode=WAL 设置。

    两个连接首次并发打开同一文件库时，``PRAGMA journal_mode=WAL`` 需要独占锁
    过渡（从非 WAL 转 WAL）；若 ``busy_timeout`` 在其后才设置，过渡不受超时保护，
    重试方会立即抛 ``sqlite3.OperationalError: database is locked``（双进程冷启动
    竞态）。契约：busy_timeout PRAGMA 的执行顺序必须先于 journal_mode=WAL。

    用 Fake cursor 捕获 execute 调用序列断言顺序——确定性（不依赖真实文件锁时序），
    当前实现 WAL 在前 → 本测试 FAIL（RED）；GREEN 调整顺序后 PASS。
    """
    calls: list[str] = []

    class _FakeCursor:
        def execute(self, sql) -> None:
            calls.append(sql)

        def close(self) -> None:
            pass

    class _FakeConn:
        def cursor(self) -> _FakeCursor:
            return _FakeCursor()

    apply_sqlite_pragma(_FakeConn())
    wal_idx = next(i for i, s in enumerate(calls) if "journal_mode" in s)
    busy_idx = next(i for i, s in enumerate(calls) if "busy_timeout" in s)
    assert busy_idx < wal_idx, (
        "busy_timeout 必须先于 journal_mode=WAL 设置，否则并发 WAL 转换竞态"
        "不受超时保护 → database is locked"
    )


# ── Phase 3 覆盖率补齐（#104）：connect 事件委托 + create/drop_tables ──


async def test_connect_event_delegates_to_apply_sqlite_pragma(tmp_path, monkeypatch):
    """engine connect 事件 → _set_sqlite_pragma 委托 apply_sqlite_pragma（45 行）。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'event.db'}")
    event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)
    calls: list = []
    monkeypatch.setattr(db_module, "apply_sqlite_pragma", lambda conn: calls.append(conn))
    try:
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
    finally:
        await engine.dispose()
    assert len(calls) == 1


async def test_connect_event_applies_real_pragma(tmp_path):
    """真实委托链路：connect 事件后文件库 journal_mode 为 wal。"""
    db_path = tmp_path / "event_pragma.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)
    try:
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
    finally:
        await engine.dispose()
    conn = sqlite3.connect(db_path)
    try:
        assert _journal_mode(conn) == "wal"
    finally:
        conn.close()


async def test_create_tables_and_drop_tables(tmp_path, monkeypatch):
    """create_tables/drop_tables 走模块级 engine（monkeypatch 为临时引擎）。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tables.db'}")
    monkeypatch.setattr(db_module, "engine", engine)
    try:
        await db_module.create_tables()
        async with engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: sqlalchemy.inspect(sync_conn).get_table_names()
            )
        assert "projects" in tables  # ProjectORM 已注册到 Base.metadata

        await db_module.drop_tables()
        async with engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: sqlalchemy.inspect(sync_conn).get_table_names()
            )
        assert tables == []
    finally:
        await engine.dispose()
