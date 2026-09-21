"""#1320 角色等级筛选下沉后端契约（RED 优先）。

【缺陷】角色页「等级选项卡」筛选此前只作用于前端已取回的一页，分页条 total 吃服务端
**未筛选**总数 → 切「主角」仍显示 2 页，跨页主角不可达。

【修复契约（用户已拍板）】
- GET /projects/{pid}/characters 新增**可选** query 参数 `role_rank`（不传 = 既有行为零改动）。
- role_rank 不是列（存 `extra.role_rank` 列内 JSON）→ 过滤需走 JSON 路径提取：
  `json_extract(extra, '$.role_rank')`；**count 与 items 必须同条件**。
- 历史缺键行（#833 之前创建、无 role_rank 键）在该筛选下**不命中**（报告已说明）；
  空串/损坏 JSON 的 lenient 行不得让整条查询 500。
- 非法等级值 → 422（非五档枚举）。

RED 预期：router/service/repo 现无 role_rank 参数 → 用例 1/2 FAIL（TypeError / 断言不符）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api.app import app
from inkflow.core.database import Base
from inkflow.infrastructure.database.models.character import CharacterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.character_repo import SQLiteCharacterRepository

client = TestClient(app)


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """独立 in-memory SQLite（每个用例全新库）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _pragma(dbapi_connection, connection_record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session: AsyncSession) -> ProjectORM:
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def _seed(
    db_session: AsyncSession, project: ProjectORM, rows: list[tuple[str, dict]]
) -> None:
    """按 (角色名, extra) 落库（extra 直接落 JSON，模拟历史/新数据两种形态）。"""
    for name, extra in rows:
        db_session.add(
            CharacterORM(
                project_id=project.id,
                name=name,
                extra=extra,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
    await db_session.commit()


class TestCharacterRepoRoleRankFilter:
    """repo 层：extra JSON 路径过滤 + 同条件 count。"""

    async def test_list_role_rank_filter_and_count_same_condition(
        self, db_session: AsyncSession, project: ProjectORM
    ) -> None:
        """role_rank=protagonist 只返回该等级，且 total 为**过滤后**总数。"""
        await _seed(
            db_session,
            project,
            [
                ("主角甲", {"role_rank": "protagonist"}),
                ("主角乙", {"role_rank": "protagonist"}),
                ("配角丙", {"role_rank": "minor"}),
                ("配角丁", {"role_rank": "minor"}),
                ("配角戊", {"role_rank": "major"}),
            ],
        )
        repo = SQLiteCharacterRepository(db_session)
        items, total = await repo.list(uuid.UUID(int=project.id), role_rank="protagonist")

        assert total == 2, f"count 必须与过滤同条件，实际 total={total}"
        assert sorted(c.name for c in items) == ["主角乙", "主角甲"]

    async def test_list_role_rank_filter_pagination_within_filtered_set(
        self, db_session: AsyncSession, project: ProjectORM
    ) -> None:
        """过滤后分页：3 主角 + limit=2 → 第 2 页只有 1 条，total 恒为 3（非全量 5）。"""
        await _seed(
            db_session,
            project,
            [
                ("主角甲", {"role_rank": "protagonist"}),
                ("主角乙", {"role_rank": "protagonist"}),
                ("主角丙", {"role_rank": "protagonist"}),
                ("配角丁", {"role_rank": "minor"}),
                ("配角戊", {"role_rank": "minor"}),
            ],
        )
        repo = SQLiteCharacterRepository(db_session)
        page1, total1 = await repo.list(
            uuid.UUID(int=project.id),
            role_rank="protagonist",
            sort_by="name",
            sort_desc=False,
            offset=0,
            limit=2,
        )
        page2, total2 = await repo.list(
            uuid.UUID(int=project.id),
            role_rank="protagonist",
            sort_by="name",
            sort_desc=False,
            offset=2,
            limit=2,
        )
        assert total1 == total2 == 3
        # 中文按 Unicode 码点排序：乙(U+4E59) < 丙(U+4E19)? 不——实测甲/乙/丙 码点序为
        # 丙(4E19) < 乙(4E59) < 甲(7532) → 断言集合语义（分页不重不漏）而非字面顺序
        assert {c.name for c in page1} | {c.name for c in page2} == {"主角甲", "主角乙", "主角丙"}
        assert len(page1) == 2
        assert len(page2) == 1
        assert {c.id for c in page1}.isdisjoint({c.id for c in page2})

    async def test_list_role_rank_filter_excludes_missing_key_rows(
        self, db_session: AsyncSession, project: ProjectORM
    ) -> None:
        """历史缺键行（#833 之前无 role_rank）+ 空 extra 不命中筛选，也不使查询报错。"""
        await _seed(
            db_session,
            project,
            [
                ("主角甲", {"role_rank": "protagonist"}),
                ("历史角色", {}),  # #833 之前：无 role_rank 键
                ("空等级", {"role_rank": ""}),
                ("非五档", {"role_rank": "unknown-legacy"}),
            ],
        )
        repo = SQLiteCharacterRepository(db_session)
        items, total = await repo.list(uuid.UUID(int=project.id), role_rank="protagonist")
        assert total == 1
        assert [c.name for c in items] == ["主角甲"]

    async def test_list_without_role_rank_keeps_all_rows(
        self, db_session: AsyncSession, project: ProjectORM
    ) -> None:
        """不传 role_rank → 既有行为零改动（含历史缺键行全部返回）。"""
        await _seed(
            db_session,
            project,
            [("主角甲", {"role_rank": "protagonist"}), ("历史角色", {})],
        )
        repo = SQLiteCharacterRepository(db_session)
        items, total = await repo.list(uuid.UUID(int=project.id))
        assert total == 2
        assert len(items) == 2


class TestCharacterRouterRoleRankParam:
    """router 层：可选 query 参数透传 + 非法值 422。"""

    def test_list_characters_rejects_invalid_role_rank(self) -> None:
        """非法等级值 → 422（五档枚举校验，不落 DB 查询）。"""
        pid = uuid.uuid4()
        resp = client.get(f"/api/v1/projects/{pid}/characters", params={"role_rank": "bogus"})
        assert resp.status_code == 422

    def test_list_characters_accepts_role_rank_and_paginates(self) -> None:
        """带 role_rank 的请求可正常响应（200），不因新参数翻红既有契约。"""
        pid = uuid.uuid4()
        resp = client.get(
            f"/api/v1/projects/{pid}/characters",
            params={"role_rank": "protagonist", "limit": 5, "offset": 0},
        )
        # 项目不存在 → 404（参数本身被接受，未走 422 参数错误路径）
        assert resp.status_code in (200, 404)
        assert resp.status_code != 422
