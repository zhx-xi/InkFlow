"""F44 #927 装配层契约（TDD RED）：planner 建主角走 CharacterCreate DTO 校验。

缺陷背景（#927 现象 3）：books.py get_planner_service 的 _character_service 闭包
`create_character(project_id, name)` 不带 extra → 服务层 validate-if-present
(required=False) 直通落库，旁路 CharacterCreate 的 #833 创建必填校验 →
主角 extra={} 无 role_rank。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约）
════════════════════════════════════════════════════════════════════

1. 装配的 _character_service 签名扩展 (project_id, name, extra=None)；
2. 内部构造 CharacterCreate DTO 走 #833 校验（extra 缺省补
   {'role_rank': 'protagonist'}——planner 产出恒为主角）；
3. 合法调用 → 落库角色 extra.role_rank == 'protagonist'；
   非法 role_rank → 抛错（CharacterRoleRankError / ValidationError），
   不得静默落库。

⚠️ RED 期形态：当前 _character_service(project_id, name) 无 extra 参数 →
TypeError；落库角色 extra={} 无 role_rank → 断言 FAIL。
"""

from __future__ import annotations

import asyncio
import inspect
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from inkflow.api.routers import books
from inkflow.core.database import Base
from inkflow.infrastructure.database.models.project import ProjectORM


def db_session():
    """模块级 in-memory SQLite 会话工厂（镜像 test_planner_deps_assembly）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return asyncio.run(_setup())


def _seed_project(session_factory: async_sessionmaker) -> uuid.UUID:
    """落一行真实 ProjectORM，返回其 int 主键映射的小 UUID。

    characters.project_id 是 64-bit INTEGER FK（ai-traps #18）：跨实体引用必须
    用持久化行派生的 uuid.UUID(int=row.id)，随机 uuid4 会 OverflowError。
    """

    async def _run():
        async with session_factory() as session:
            p = ProjectORM(name="测试项目")
            session.add(p)
            await session.commit()
            await session.refresh(p)
            return uuid.UUID(int=p.id)

    return asyncio.run(_run())


def _planner_service(session_factory):
    return books.get_planner_service(db=session_factory())


def test_character_service_accepts_extra_kwarg():
    """_character_service 必须支持 extra 关键字（planner 传递 role_rank 入口）。"""
    svc = _planner_service(db_session())
    sig = inspect.signature(svc._character_service)
    assert "extra" in sig.parameters, "装配闭包无 extra 参数（#927 role_rank 旁路）"


def test_character_service_persists_role_rank():
    """extra={'role_rank': 'protagonist'} → 落库角色带 role_rank。"""
    session_factory = db_session()
    svc = _planner_service(session_factory)
    project_id = _seed_project(session_factory)

    async def _run():
        return await svc._character_service(
            project_id=project_id,
            name="玄明",
            extra={"role_rank": "protagonist"},
        )

    character = asyncio.run(_run())
    assert getattr(character, "extra", {}).get("role_rank") == "protagonist"


def test_character_service_default_protagonist_without_extra():
    """缺省 extra → 装配层补 protagonist（走 CharacterCreate 必填校验不逃逸）。"""
    session_factory = db_session()
    svc = _planner_service(session_factory)
    project_id = _seed_project(session_factory)

    async def _run():
        return await svc._character_service(project_id=project_id, name="叶知秋")

    character = asyncio.run(_run())
    assert getattr(character, "extra", {}).get("role_rank") == "protagonist"


def test_character_service_rejects_invalid_role_rank():
    """非法 role_rank → 抛错，不静默落库（#833 DTO 校验生效，DB 前拦截）。"""
    session_factory = db_session()
    svc = _planner_service(session_factory)
    project_id = _seed_project(session_factory)

    async def _run():
        return await svc._character_service(
            project_id=project_id,
            name="反派",
            extra={"role_rank": "not_a_rank"},
        )

    with pytest.raises(Exception) as excinfo:
        asyncio.run(_run())
    assert "角色等级" in str(excinfo.value) or "role_rank" in str(excinfo.value)
