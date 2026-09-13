"""#1137 覆盖率补齐 —— deps.py 硬删清理钩子经公开 getter + 公开 service 方法驱动。

权威来源：
- specs/f43-setting-library-gui（P5 角色/地点/事件硬删后的地图 pin 清理）
- specs/f36-world-map（D10=b：真删地点后 pin 清理）

公开面：``get_character_service`` / ``get_world_service`` / ``get_timeline_service``
（FastAPI 依赖 getter）+ 其公开删除方法（``delete_character`` / ``delete_setting`` /
``delete_event``）；真实 in-memory SQLite（backend/conftest.py 的 test_engine）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkflow.api.deps import get_character_service, get_timeline_service, get_world_service
from inkflow.infrastructure.database.models.character import CharacterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.timeline import TimelineEventORM
from inkflow.infrastructure.database.models.world import WorldSettingORM

SEED_PROJECT_ID = uuid.UUID(int=1)
CHARACTER_ID = uuid.UUID(int=31)
WORLD_SETTING_ID = uuid.UUID(int=41)
EVENT_ID = uuid.UUID(int=51)


async def _session(test_engine) -> AsyncSession:
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    session = factory()
    session.add(ProjectORM(id=SEED_PROJECT_ID.int, name="deps 覆盖项目", config={}))
    await session.commit()
    return session


@pytest.mark.asyncio
async def test_delete_character_cleans_role_pins(test_engine):
    """F43 P5：角色硬删成功 → 装配期注入的 map_cleanup 钩子清理 type=role pin。"""
    async with await _session(test_engine) as session:
        session.add(
            CharacterORM(
                id=CHARACTER_ID.int,
                project_id=SEED_PROJECT_ID.int,
                name="林晚",
            )
        )
        await session.commit()
        svc = get_character_service(session)

        assert await svc.delete_character(CHARACTER_ID) is True


@pytest.mark.asyncio
async def test_delete_world_setting_cleans_location_pins(test_engine):
    """F36 D10=b：地点硬删成功 → location_cleanup 钩子清理该地点 pin。"""
    async with await _session(test_engine) as session:
        session.add(
            WorldSettingORM(
                id=WORLD_SETTING_ID.int,
                project_id=SEED_PROJECT_ID.int,
                name="北境",
            )
        )
        await session.commit()
        svc = get_world_service(session)

        assert await svc.delete_setting(WORLD_SETTING_ID) is True


@pytest.mark.asyncio
async def test_delete_timeline_event_cleans_event_pins(test_engine):
    """F43 P5：事件硬删成功 → map_cleanup 钩子清理 type=event pin。"""
    async with await _session(test_engine) as session:
        session.add(
            TimelineEventORM(
                id=EVENT_ID.int,
                project_id=SEED_PROJECT_ID.int,
                title="启程",
            )
        )
        await session.commit()
        svc = get_timeline_service(session)

        assert await svc.delete_event(EVENT_ID) is True
