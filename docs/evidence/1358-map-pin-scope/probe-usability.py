"""#1358 取证探针：related 语义下 map_pin 的可用性检验（两条上图路径）。

路径 (a) 建 character→map_pin 关系 → pin 立即上图；
路径 (b) scope=all 开关 → 10/10。

跑法（worktree 根）::

    cd backend
    ./.venv/Scripts/python.exe ../docs/evidence/1358-map-pin-scope/probe-usability.py
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
from inkflow.infrastructure.database.models.map import MapORM, MapPinORM
from inkflow.infrastructure.database.models.project import ProjectORM
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

PID = 900001
PID_U = uuid.UUID(int=PID)
CH_A = 900011
MAP_A = 900101
PINS = list(range(900201, 900211))


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
        s.add(
            MapORM(
                id=MAP_A,
                project_id=PID,
                name="地图甲",
                image_path="",
                description="",
                bg_source="image",
                extra={},
                created_at=now,
                updated_at=now,
            )
        )
        for p in PINS:
            s.add(
                MapPinORM(
                    id=p,
                    map_id=MAP_A,
                    label=f"pin{p}",
                    x=1.0,
                    y=2.0,
                    type="location",
                    location_id=None,
                    ref_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        await s.commit()

    async with sf() as s:
        svc = KnowledgeGraphService(
            relation_repo=SQLiteKnowledgeRelationRepository(s),
            project_repo=SQLiteProjectRepository(s),
            character_repo=SQLiteCharacterRepository(s),
            map_repo=SQLiteMapRepository(s),
        )

        async def counts(tag: str) -> None:
            for scope in ("related", "all"):
                v = await svc.graph(PID_U, scope=scope)
                mp = sum(1 for n in v.nodes if n.type is EntityType.MAP_PIN)
                print(
                    f"  [{tag}] scope={scope:8s} 总节点={len(v.nodes):3d}"
                    f" map_pin={mp:2d} edges={len(v.edges)}"
                )

        print("── 初始态（无任何关系）──")
        await counts("初始")

        print("\n── 路径 (a)：经 create_relation 建 character -> map_pin ──")
        try:
            rel = await svc.create_relation(
                PID_U,
                source_type="character",
                source_id=uuid.UUID(int=CH_A),
                target_type="map_pin",
                target_id=uuid.UUID(int=PINS[0]),
                relation_type="出现于",
            )
            print(f"  create_relation 成功: {rel.id}")
        except Exception as e:
            print(f"  create_relation 失败: {type(e).__name__}: {e}")
        await counts("建 1 条关系后")

        print("\n── 路径 (b)：scope=all 开关 ──")
        v = await svc.graph(PID_U, scope="all")
        mp = [n for n in v.nodes if n.type is EntityType.MAP_PIN]
        print(f"  scope=all map_pin={len(mp)}/10")

    await engine.dispose()


asyncio.run(main())
