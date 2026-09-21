"""#1358 取证探针：真实 SQLite + 真实 repo，构造 3 张形态各异的地图 + 10 pin。

逐项排除 issue §5 的 5 个可疑方向（map 过滤 / 端点误杀 / 去重 / 软删 / id 语义）。

跑法（worktree 根）::

    cd backend
    ./.venv/Scripts/python.exe ../docs/evidence/1358-map-pin-scope/probe-exclusions.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend" / "src"))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.knowledge_graph import EntityType
from inkflow.domain.services.knowledge_graph_service import (
    KnowledgeGraphService,
)
from inkflow.infrastructure.database.models.character import CharacterORM
from inkflow.infrastructure.database.models.knowledge_graph import (
    KnowledgeRelationORM,
)
from inkflow.infrastructure.database.models.map import MapORM, MapPinORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.world import WorldSettingORM
from inkflow.infrastructure.database.repositories.character_repo import (
    SQLiteCharacterRepository,
)
from inkflow.infrastructure.database.repositories.knowledge_relation_repo import (
    SQLiteKnowledgeRelationRepository,
)
from inkflow.infrastructure.database.repositories.map_repo import (
    SQLiteMapRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.database.repositories.world_repo import (
    SQLiteWorldRepository,
)

PID = 900001
PID_U = uuid.UUID(int=PID)
CH_A = 900011
M_GLOBAL, M_ROOTED, M_CHILD = 900101, 900102, 900103
LOC = 900301
PINS = list(range(900201, 900211))


def _map_row(mid: int, name: str, now: datetime, **kw: object) -> MapORM:
    return MapORM(
        id=mid,
        project_id=PID,
        name=name,
        image_path="",
        description="",
        bg_source="image",
        extra={},
        created_at=now,
        updated_at=now,
        **kw,
    )


def _pin_row(pid: int, mid: int, now: datetime) -> MapPinORM:
    return MapPinORM(
        id=pid,
        map_id=mid,
        label=f"{mid}-pin{pid}",
        x=1.0,
        y=2.0,
        type="location",
        location_id=None,
        ref_id=None,
        created_at=now,
        updated_at=now,
    )


async def main() -> None:
    now = datetime.now(UTC)
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async with sf() as s:
        s.add(ProjectORM(id=PID, name="P", tags=[], language="zh-CN", target_words=1000, config={}))
        s.add(
            CharacterORM(
                id=CH_A, project_id=PID, name="角色甲", personality="", background="", goals=""
            )
        )
        s.add(WorldSettingORM(id=LOC, project_id=PID, name="地点甲", category="设定", content=""))
        s.add(_map_row(M_GLOBAL, "全局图", now, root_location_id=None))
        s.add(_map_row(M_ROOTED, "根地点图", now, root_location_id=LOC))
        s.add(_map_row(M_CHILD, "子图", now, parent_map_id=M_GLOBAL))

        idx = 0
        for mid, cnt in ((M_GLOBAL, 4), (M_ROOTED, 3), (M_CHILD, 3)):
            for _ in range(cnt):
                s.add(_pin_row(PINS[idx], mid, now))
                idx += 1
        for i in range(2):  # 仅前 2 个 pin 参与关系
            s.add(
                KnowledgeRelationORM(
                    id=900601 + i,
                    project_id=PID,
                    source_type="character",
                    source_id=CH_A,
                    target_type="map_pin",
                    target_id=PINS[i],
                    relation_type="出现于",
                    description="",
                    source="manual",
                    created_at=now,
                    updated_at=now,
                )
            )
        await s.commit()

    async with sf() as s:
        map_repo = SQLiteMapRepository(s)
        svc = KnowledgeGraphService(
            relation_repo=SQLiteKnowledgeRelationRepository(s),
            project_repo=SQLiteProjectRepository(s),
            character_repo=SQLiteCharacterRepository(s),
            world_repo=SQLiteWorldRepository(s),
            map_repo=map_repo,
        )

        print("── 方向 1：list_maps_by_project 是否排除某些 map ──")
        maps = await map_repo.list_maps_by_project(PID_U)
        print(f"  返回 {len(maps)} 张（期望 3）: {sorted(m.name for m in maps)}")

        print("\n── 方向 1b：地图形态是否影响 pin 遍历 ──")
        for wm in maps:
            pins = await map_repo.list_pins(wm.id)
            print(f"  {wm.name}: {len(pins)} pins")

        print("\n── 方向 5：id 语义 —— pin.id 与节点 id 是否一致 ──")
        view_all = await svc.graph(PID_U, scope="all")
        mp_all = [n for n in view_all.nodes if n.type is EntityType.MAP_PIN]
        got = sorted(n.entity_id.int for n in mp_all)
        print(f"  scope=all map_pin={len(mp_all)}  期望={len(PINS)}")
        print(f"  缺失: {sorted(set(PINS) - set(got))}")
        print(f"  节点 id 样例: {mp_all[0].id}")

        print("\n── 方向 2：端点在节点集的边 —— 参与关系的 pin 边是否保留 ──")
        print(f"  scope=all edges={len(view_all.edges)}（期望 2）")
        for e in view_all.edges:
            print(f"    {e.source} -> {e.target}")

        print("\n── 方向 3/4：去重 / 软删 ──")
        print("  map_pins 无 is_deleted 列（真删语义，见 models/map.py:77）")
        print("  maps 无 is_deleted 列（真删语义，见 models/map.py:22）")

        print("\n── 关键对照：scope=related（前端默认）vs scope=all ──")
        view_rel = await svc.graph(PID_U, scope="related")
        mp_rel = [n for n in view_rel.nodes if n.type is EntityType.MAP_PIN]
        print(f"  scope=all     → map_pin={len(mp_all)}/{len(PINS)}")
        print(f"  scope=related → map_pin={len(mp_rel)}/{len(PINS)}")
        print(f"  >>> related 语义下丢 {len(PINS) - len(mp_rel)} 个（未参与关系的 pin）")

    await engine.dispose()


asyncio.run(main())
