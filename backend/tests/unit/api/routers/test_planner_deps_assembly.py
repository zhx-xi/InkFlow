"""RED 契约（#460）：get_planner_service deps 装配完整（write_auto/outline/character 非 None）。

缺陷背景（0.10.0-rc2 实证 2026-08-18）：
- `book plan auto` 报 `? write_auto 未装配`——books.py get_planner_service 只注入 repo，
  write_auto 默认 None → _run_auto 抛 ValueError（auto 兜底路径必败）
- 访谈完成（respond）WritingPlan 无 root_outline_id/character_ids——outline_service/
  character_service 未注入 → _complete 跳过落库（spec §2.2「planner 产出直写
  outline/character 实体」违约）

本契约：直接调 books.get_planner_service(db)（真实 deps 装配，db 用 in-memory
SQLite 引擎），断言返回实例的 _write_auto / _outline_service / _character_service
**全部非 None**（装配完整）。修复后全部 PASS。

⚠️ RED 期形态：当前实现三个依赖全 None → 断言 FAIL（干净 RED）。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from inkflow.api.routers import books
from inkflow.core.database import Base


def db_session():
    """模块级 in-memory SQLite 会话工厂（测试直接调用；pytest 9 禁直接调 fixture）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Base.metadata.create_all 需真实表（get_planner_service 只建 repo 不查表，
    # 但保持与真实环境一致）
    import asyncio

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return asyncio.run(_setup())


def test_planner_deps_write_auto_injected():
    """get_planner_service 的 _write_auto 必须非 None（plan auto 兜底可委托 F42）。"""
    session_factory = db_session()
    svc = books.get_planner_service(db=session_factory())
    assert svc._write_auto is not None, "write_auto 未注入（plan auto 报『write_auto 未装配』）"
    # 可调用且 async：签名 (project_id, one_liner)
    assert callable(svc._write_auto), "write_auto 必须可调用"


def test_planner_deps_outline_service_injected():
    """get_planner_service 的 _outline_service 必须非 None（访谈产出落库 outline）。"""
    session_factory = db_session()
    svc = books.get_planner_service(db=session_factory())
    assert svc._outline_service is not None, "outline_service 未注入（访谈产出不落库 outline）"


def test_planner_deps_character_service_injected():
    """get_planner_service 的 _character_service 必须非 None（访谈产出落库 character）。"""
    session_factory = db_session()
    svc = books.get_planner_service(db=session_factory())
    assert (
        svc._character_service is not None
    ), "character_service 未注入（访谈产出不落库 character）"


def test_planner_deps_all_three():
    """三依赖同时非 None（装配完整快照）。"""
    session_factory = db_session()
    svc = books.get_planner_service(db=session_factory())
    missing = [
        name
        for name in ("_write_auto", "_outline_service", "_character_service")
        if getattr(svc, name, None) is None
    ]
    assert missing == [], f"deps 装配缺口: {missing}"
