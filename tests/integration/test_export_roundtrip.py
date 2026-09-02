"""S3f-T4 R2 契约：导出 HTTP 面 roundtrip（issue #869 / contract-s3f-t4.md §1 R2）。

TestClient 真 DB（镜像本目录 test_builtin_seed.py fixture 形态：in-memory sqlite +
get_db override + ASGITransport）建内容 → GET /api/v1/projects/{id}/export golden：

1. 【G→R 组合面】正文排序 + 中文编码：2 卷（B order_index=2 先建、A order_index=1
   后建——反序）→ 卷 A 2 章（order 2 先建、order 1 后建）+ 卷 B 1 章 + 1 未挂卷章
   → TXT 段序：卷 A 前、卷 B 后、未分组章最末、卷内按 order_index 升序；全文 UTF-8
   解码无乱码（正文中文字面量逐一 in text）。
2. 【G 现实现有，HTTP 面锁】include_settings=true → 「附录：设定档案」
   （_txt_exporter._APPENDIX_TITLE 字面量）+ 角色/世界观名出现；false/缺省 → 无附录
   标记、无设定名（正文内容刻意不含设定名，断言有区分度）。
3. 【R 新面】同数据两次 GET → 字节级一致（export1.content == export2.content；
   exporter 纯函数无时间戳——_txt_exporter.to_txt docstring 已实证）。
4. 【G】空项目导出 → 200 + 书名/分隔线骨架精确相等（不抛）。

依据 specs/f21-export/spec.md §3/§5.3/§6 与 backend/src/inkflow/domain/services/
output_service.py（卷 order_index ASC、章 (order_index, created_at) ASC、无卷章归
「未分组」末位、附录 5 类固定序）。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api.app import app
from inkflow.core.database import Base
from inkflow.domain.services import _txt_exporter
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM
from inkflow.infrastructure.database.models.character import CharacterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.world import WorldSettingORM

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"

# repo-root tests/ 树以 rootdir=仓库根 运行（无 backend pyproject asyncio_mode=auto）：
# pytest-asyncio STRICT，async 测试须显式 mark（镜像 test_agent_pipeline.py 惯例）
pytestmark = pytest.mark.asyncio

PROJECT_NAME = "蜀山剑冢录"
VOL_A = ("蜀山卷", 1.0)
VOL_B = ("雪域卷", 2.0)
CH_A_1 = ("第一章·雪夜入蜀山", 1.0, "大雪封山，玄明独自踏上蜀山石阶，剑穗沾满霜雪。")
CH_A_2 = ("第二章·剑冢", 2.0, "剑冢之内，万剑陈列，锈迹斑斑之下剑气犹存。")
CH_B_1 = ("第一章·雪域寻踪", 1.0, "雪域深处，一行足迹蜿蜒没入暴风雪中。")
CH_UNGROUPED = ("外传·雪夜", 5.0, "一场大雪掩去旧日恩怨，灯火阑珊处有人独立。")
# 设定档案（仅 include_settings=true 时出现；正文刻意不含下列名/词，断言有区分度）
CHARACTER_NAME = "宁晚"
CHARACTER = ("宁晚", "外冷内热，剑心通明", "雪域孤女，幼年被蜀山长老收养", "寻回失传的御剑心法")
WORLD_NAME = "蜀山剑派"
WORLD = ("蜀山剑派", "geo", "剑气冲霄，万剑归宗，山门立于蜀山之巅。")


def _export_url(project_id: int, include_settings: bool | None = None) -> str:
    pid = str(uuid.UUID(int=project_id))
    suffix = (
        f"?include_settings={str(include_settings).lower()}" if include_settings is not None else ""
    )
    return f"/api/v1/projects/{pid}/export{suffix}"


# ── Fixtures（镜像 tests/integration/test_builtin_seed.py 本地形态） ──


@pytest_asyncio.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库 + FK pragma（生产同口径）。"""
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


@pytest.fixture
def override_get_db(db_session):
    """FastAPI get_db → 本文件 db_session（API 与数据同库）。"""
    from inkflow.api.deps import get_db

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式：delenv INKFLOW_SERVER_TOKEN）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _add(db_session: AsyncSession, orm) -> None:
    db_session.add(orm)
    await db_session.commit()
    await db_session.refresh(orm)


async def _build_full_project(db_session: AsyncSession) -> int:
    """建项目 + 2 卷（B order 2 先建、A order 1 后建）+ 卷 A 2 章（order 2 先建、
    order 1 后建）+ 卷 B 1 章 + 1 未挂卷章 + 角色/世界观各 1（中文）。

    全部经 ORM 真库写入（导出聚合走的仓储读同一 DB）。返回项目 int 主键。
    """
    project = ProjectORM(name=PROJECT_NAME, language="zh-CN", target_words=500000, tags=["仙侠"])
    await _add(db_session, project)
    project_id = project.id

    vol_b = VolumeORM(project_id=project_id, title=VOL_B[0], order_index=VOL_B[1])
    await _add(db_session, vol_b)
    vol_a = VolumeORM(project_id=project_id, title=VOL_A[0], order_index=VOL_A[1])
    await _add(db_session, vol_a)

    for title, order, content in (CH_A_2, CH_A_1):  # order 2 先建 → 反序
        await _add(
            db_session,
            ChapterORM(
                project_id=project_id,
                volume_id=vol_a.id,
                title=title,
                content=content,
                order_index=order,
            ),
        )
    await _add(
        db_session,
        ChapterORM(
            project_id=project_id,
            volume_id=vol_b.id,
            title=CH_B_1[0],
            content=CH_B_1[2],
            order_index=CH_B_1[1],
        ),
    )
    await _add(
        db_session,
        ChapterORM(
            project_id=project_id,
            volume_id=None,
            title=CH_UNGROUPED[0],
            content=CH_UNGROUPED[2],
            order_index=CH_UNGROUPED[1],
        ),
    )
    await _add(
        db_session,
        CharacterORM(
            project_id=project_id,
            name=CHARACTER[0],
            personality=CHARACTER[1],
            background=CHARACTER[2],
            goals=CHARACTER[3],
        ),
    )
    await _add(
        db_session,
        WorldSettingORM(project_id=project_id, name=WORLD[0], category=WORLD[1], content=WORLD[2]),
    )
    return project_id


async def test_export_full_order_and_encoding(db_session, client, override_get_db) -> None:
    """R2-1：正文段序（卷 order / 卷内章 order / 未分组最末）+ 中文 UTF-8 无乱码。"""
    project_id = await _build_full_project(db_session)

    resp = await client.get(_export_url(project_id))
    assert resp.status_code == 200
    txt = resp.text

    # 段序：卷 A(order 1) → 卷 A 章序(1<2) → 卷 B(order 2) → 卷 B 章 → 未分组章最末
    anchors = [
        "第 1 卷 蜀山卷",
        "第一章·雪夜入蜀山",
        "第二章·剑冢",
        "第 2 卷 雪域卷",
        "第一章·雪域寻踪",
        "外传·雪夜",
    ]
    positions = [txt.index(a) for a in anchors]
    assert positions == sorted(positions), (
        f"导出段序错误: anchors={list(zip(anchors, positions, strict=True))}"
    )

    # 中文正文保全（UTF-8 解码无乱码：逐字面量命中）
    for _, _, content in (CH_A_1, CH_A_2, CH_B_1, CH_UNGROUPED):
        assert content in txt


async def test_include_settings_presence(db_session, client, override_get_db) -> None:
    """R2-2：include_settings=true → 附录段（角色名+世界观名）；false/缺省 → 无附录。"""
    project_id = await _build_full_project(db_session)

    resp_on = await client.get(_export_url(project_id, include_settings=True))
    assert resp_on.status_code == 200
    txt_on = resp_on.text
    assert _txt_exporter._APPENDIX_TITLE in txt_on
    assert CHARACTER_NAME in txt_on
    assert WORLD_NAME in txt_on

    resp_off = await client.get(_export_url(project_id))  # 缺省 = include_settings=false
    assert resp_off.status_code == 200
    txt_off = resp_off.text
    assert _txt_exporter._APPENDIX_TITLE not in txt_off
    assert CHARACTER_NAME not in txt_off
    assert WORLD_NAME not in txt_off


async def test_two_exports_byte_identical(db_session, client, override_get_db) -> None:
    """R2-3（新面）：同数据两次 GET → 字节级一致（导出器确定性，无时间戳）。"""
    project_id = await _build_full_project(db_session)

    export1 = await client.get(_export_url(project_id, include_settings=True))
    export2 = await client.get(_export_url(project_id, include_settings=True))
    assert export1.status_code == 200 and export2.status_code == 200
    assert export1.content == export2.content
    assert export1.content == export1.content  # 自反 sanity（非空且可重复读）
    assert len(export1.content) > 0


async def test_export_empty_project(db_session, client, override_get_db) -> None:
    """R2-4【G】：空项目（无卷无章无设定）→ 200 + 书名/分隔线骨架（不抛）。"""
    project = ProjectORM(name="空山新雨", language="zh-CN")
    await _add(db_session, project)

    resp = await client.get(_export_url(project.id))
    assert resp.status_code == 200
    assert resp.text == f"空山新雨\n{'=' * 30}\n"
