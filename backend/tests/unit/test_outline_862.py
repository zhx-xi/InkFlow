"""#862 RED 契约测试：PATCH 大纲关联字段经 HTTP JSON 字符串形态必须真正落库并读回。

实证根因（Python 3.13.13 + pydantic 2.13.4 实测）:
OutlineUpdate.chapter_id: uuid.UUID | str | None = None（parent_id/volume_id 同构）。
smart union 从左到右对 str 输入保留 str（OutlineUpdate(chapter_id=str(uuid4())).chapter_id
type 实测为 str，不强制转 UUID）。HTTP JSON body 的 UUID 字符串经 FastAPI 校验后仍是
str → service update_outline 判定行 `not isinstance(x, uuid.UUID)`
（outline_service.py L334/L337/L340）为 True → 走「清除」分支 → chapter_id 写 None →
PATCH 200 但 GET 读回 null（#862 缺陷）。

期望语义（OutlineUpdate docstring）: 合法 UUID 字符串 = 设置；空串/空白串 = 清除；
显式 None = 清除。

RED 预期形态（当前实现，整文件可收集、零收集 ERROR）:
- test_outline_update_coerces_valid_uuid_strings: str 保留 → isinstance 断言失败
- test_patch_outline_chapter_id_via_http_json: PATCH 200 但 body chapter_id=null →
  == str(chapter_uuid) 断言失败
- test_patch_outline_parent_id_via_http_json: str 被当清除 → parent 置空 → 孤立章 422
  （status_code == 200 断言失败）
GREEN 回归护栏（当前应 PASS，防修复把清除语义改坏）:
- test_update_outline_chapter_id_survives_str_uuid: UUID 对象直通 service 落库读回
- test_clear_semantics_preserved: "" 清除后 GET 读回 null

GREEN 必实现（#862 修复）: OutlineUpdate 加 field_validator(mode="before")，合法
UUID 字符串 → uuid.UUID；空串/空白串/None 保持清除语义。本文件只钉死「合法 UUID
字符串经模型/HTTP 全链路后 chapter_id/parent_id 等值落库并读回」。

形态: 模型层同步契约 + service 层真 in-memory SQLite 轨（镜像 test_outline_p3.py
TestOutlineP3Repo fixture）+ HTTP 全链路独立 app（镜像 test_search_api.py 的
dependency_overrides[get_db]，override 为 async generator yield 真 session，走真实
get_outline_service 组装链，不经 patch 服务层）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api.deps import get_db
from inkflow.api.routers.outlines import router
from inkflow.core.database import Base
from inkflow.domain.models.outline import Outline, OutlineUpdate
from inkflow.domain.services.outline_service import OutlineService
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.outline_repo import SQLiteOutlineRepository

TS = datetime(2026, 8, 1, 10, 0, 0)


def _outline(
    name: str,
    *,
    project_id: uuid.UUID,
    level: str = "chapter",
    parent_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
) -> Outline:
    """构造测试用大纲实体（固定时间戳；三级 + 章/卷关联字段透传）."""
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        level=level,
        parent_id=parent_id,
        chapter_id=chapter_id,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite session — 每个测试一个全新数据库（启用 FK 级联）."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_tree(session: AsyncSession, *, link_chapter: bool = False):
    """种 overall→volume→chapter 三层大纲 + 同项目 ChapterORM 行（真 SQLiteOutlineRepository）.

    Returns:
        (pid, volume, chap, chapter_uuid)：pid=项目 UUID；volume/chap=领域 Outline
        （id 已按 DB rowid 回读映射）；chapter_uuid=写作章节行 UUID（始终存在）；
        link_chapter=True 时 chap 初始已关联该章节。
    """
    project = ProjectORM(name="测试项目")
    session.add(project)
    await session.commit()
    await session.refresh(project)
    pid = uuid.UUID(int=project.id)

    chapter_orm = ChapterORM(project_id=project.id, title="第一章 试剑大典")
    session.add(chapter_orm)
    await session.commit()
    await session.refresh(chapter_orm)
    chapter_uuid = uuid.UUID(int=chapter_orm.id)

    repo = SQLiteOutlineRepository(session)
    overall = await repo.add(_outline("整本大纲", project_id=pid, level="overall"))
    volume = await repo.add(
        _outline("卷一", project_id=pid, level="volume", parent_id=overall.id)
    )
    chap = await repo.add(
        _outline(
            "第一章 试剑大典",
            project_id=pid,
            level="chapter",
            parent_id=volume.id,
            chapter_id=chapter_uuid if link_chapter else None,
        )
    )
    return pid, volume, chap, chapter_uuid


def _http_client(session: AsyncSession) -> AsyncClient:
    """独立 FastAPI app：outlines router + get_db override → 同一真 session。

    走真实 get_outline_service 组装链（deps.py L450：OutlineService + generator +
    project_repo + chapter_repo 全真实；LangChainLLMClient 构造不触凭据，已实测可组装）。
    """
    app = FastAPI()
    app.include_router(router)

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_db] = _override_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def test_outline_update_coerces_valid_uuid_strings() -> None:
    """模型层契约：合法 UUID 字符串 → 强制转 uuid.UUID 且值相等（#862 根因第一环）。

    RED 预期: smart union 保留 str → isinstance(..., uuid.UUID) False → 断言失败。
    GREEN 必实现: OutlineUpdate chapter_id/parent_id/volume_id 加 mode="before"
    validator：非空白 str 可解析为 UUID → uuid.UUID(v)；空串/空白串保持 str（清除哨兵）。
    """
    s1 = str(uuid.uuid4())
    s2 = str(uuid.uuid4())
    s3 = str(uuid.uuid4())
    upd = OutlineUpdate(chapter_id=s1, parent_id=s2, volume_id=s3)

    assert isinstance(upd.chapter_id, uuid.UUID)  # RED: str 保留 → False
    assert upd.chapter_id == uuid.UUID(s1)
    assert isinstance(upd.parent_id, uuid.UUID)
    assert upd.parent_id == uuid.UUID(s2)
    assert isinstance(upd.volume_id, uuid.UUID)
    assert upd.volume_id == uuid.UUID(s3)


@pytest.mark.integration
class TestOutline862Service:
    """Service 层契约（真 in-memory SQLite，镜像 test_outline_p3.py Repo 轨）. """

    async def test_update_outline_chapter_id_survives_str_uuid(self, db_session) -> None:
        """UUID 对象（模型层直通形态）经真 repo 链路 update → 落库且读回相等。

        当前应 PASS（回归护栏）：isinstance(uuid.UUID) 命中「设置」分支，chapter_id
        不被清除；GREEN 加 str 转 UUID validator 后 UUID 对象直通行为不得回归。
        """
        _, _, chap, chapter_uuid = await _seed_tree(db_session)
        repo = SQLiteOutlineRepository(db_session)
        svc = OutlineService(repository=repo)  # 不注入 chapter_repo，跳过存在性校验

        result = await svc.update_outline(
            chap.id, OutlineUpdate(chapter_id=chapter_uuid)
        )
        assert result is not None
        assert result.chapter_id == chapter_uuid

        got = await repo.get(chap.id.int)
        assert got is not None
        assert got.chapter_id == chapter_uuid


@pytest.mark.integration
class TestOutline862HttpLink:
    """HTTP 全链路契约：真实 get_outline_service + 真 session（PATCH → GET 读回）. """

    async def test_patch_outline_chapter_id_via_http_json(self, db_session) -> None:
        """#862 核心 RED：PATCH body chapter_id=合法 UUID 字符串 → 200 且落库读回相等。

        RED 预期: JSON 字符串经模型层保留 str → service 走「清除」分支 → PATCH 200
        但 body chapter_id=null → `== str(chapter_uuid)` 断言失败；GET 同样读回 null。
        GREEN 必实现: 模型层转 UUID → service「设置」分支 → repo 落库（chapter 行
        同项目已存在，chapter_repo 校验放行）→ PATCH/GET body 均 == str(chapter_uuid)。
        """
        _, _, chap, chapter_uuid = await _seed_tree(db_session)
        url = f"/api/v1/outlines/{chap.id}"
        async with _http_client(db_session) as client:
            resp = await client.patch(url, json={"chapter_id": str(chapter_uuid)})
            assert resp.status_code == 200
            assert resp.json()["chapter_id"] == str(chapter_uuid)  # RED: null

            resp2 = await client.get(url)
            assert resp2.status_code == 200
            assert resp2.json()["chapter_id"] == str(chapter_uuid)  # RED: null

    async def test_clear_semantics_preserved(self, db_session) -> None:
        """清除语义回归护栏："" 清 chapter_id / volume_id 仍走清除（当前应 PASS）。

        防 GREEN 修复把「空串=清除」改坏：清空后 GET 必须读回 null；对 chapter 级
        大纲清 volume_id 无层级冲突 → 200。
        """
        _, _, chap, _ = await _seed_tree(db_session, link_chapter=True)
        url = f"/api/v1/outlines/{chap.id}"
        async with _http_client(db_session) as client:
            resp = await client.patch(url, json={"chapter_id": ""})
            assert resp.status_code == 200
            assert resp.json()["chapter_id"] is None

            resp2 = await client.get(url)
            assert resp2.status_code == 200
            assert resp2.json()["chapter_id"] is None

            resp3 = await client.patch(url, json={"volume_id": ""})
            assert resp3.status_code == 200
            assert resp3.json()["volume_id"] is None

    async def test_patch_outline_parent_id_via_http_json(self, db_session) -> None:
        """同构字段全链路：PATCH parent_id=合法 UUID 字符串（= 既有卷纲）→ 设置并读回。

        RED 预期: 同根因——str 被当清除 → parent_id 置 None → chapter 孤立 →
        OutlineHierarchyError → 422（status_code == 200 断言失败），比 chapter_id
        的「200 但 null」更早暴露。
        GREEN 必实现: parent_id 转 UUID 后 service「设置」分支，父卷纲同项目存在
        （level=volume）→ 200 且 PATCH/GET body parent_id == str(volume.id)。
        """
        _, volume, chap, _ = await _seed_tree(db_session)
        url = f"/api/v1/outlines/{chap.id}"
        async with _http_client(db_session) as client:
            resp = await client.patch(url, json={"parent_id": str(volume.id)})
            assert resp.status_code == 200  # RED: 422（清除 → 孤立章）
            assert resp.json()["parent_id"] == str(volume.id)

            resp2 = await client.get(url)
            assert resp2.status_code == 200
            assert resp2.json()["parent_id"] == str(volume.id)
