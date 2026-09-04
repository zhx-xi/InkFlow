"""#908 RED 契约测试：PATCH plot-point 的 arc_id 合法 UUID 字符串必须真正落库（#862 同构）。

实证根因（与 #862 完全同族，Python 3.13 + Pydantic v2 实测）:
PlotPointUpdate.arc_id: uuid.UUID | str | None = None（str "" = 清除哨兵）。
smart union 从左到右对 str 输入保留 str（PlotPointUpdate(arc_id=str(uuid4())).arc_id
type 实测为 str，不强制转 UUID）。HTTP JSON body 的 UUID 字符串经 FastAPI 校验后仍是
str → service update_point 判定行 `isinstance(update.arc_id, uuid.UUID)`
（outline_service.py L461）为 False → 走「清除」分支 → arc_id 写 None →
PATCH 200 但 GET 读回 null（#908 缺陷）；不存在/跨项目弧线的非法设置也被静默吞成
「清除 200」而非 422。

期望语义（PlotPointUpdate docstring / spec §3.3）: 合法 UUID 字符串 = 设置（校验弧线
存在且同项目）；空串/空白串 = 清除；显式 None = 清除；其它非空字符串 = 422。

修复方案（issue #908 指定，复用 #862/PR #907 刚落地的三态归一器）:
models/outline.py 给 PlotPointUpdate.arc_id 加 @field_validator(mode="before")，
调 _normalize_ref_field(v, "弧线关联")。service 层不动。

RED 预期形态（当前实现，整文件可收集、零收集 ERROR）:
- test_plot_point_update_coerces_valid_uuid_string: str 保留 → isinstance 断言失败
- test_whitespace_clear_sentinel_normalized: "  " 当前原样保留 → == "" 断言失败
- test_garbage_string_rejected / test_illegal_type_rejected: 当前无校验 → 不抛错
- test_patch_plot_point_arc_id_via_http_json: PATCH 200 但 arc_id=null → 断言失败
- test_patch_unknown_arc_returns_422: str 被当清除 → 200 而非 422 → 断言失败
回归护栏（当前应 PASS，防修复把清除/设置语义改坏）:
- test_update_point_arc_uuid_object_survives: UUID 对象直通 service 落库读回
- test_update_point_arc_cleared_by_empty_sentinel: "" 走 service 清除分支
- test_patch_plot_point_arc_clear_via_http_json: "" / null 清除后读回 null

形态: 模型层同步契约 + service 层真 in-memory SQLite 轨 + HTTP 全链路独立 app
（镜像 test_outline_862.py 的 dependency_overrides[get_db]，override 为 async
generator yield 真 session，走真实 get_outline_service 组装链）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api.deps import get_db
from inkflow.api.routers.outlines import router
from inkflow.core.database import Base
from inkflow.domain.models.outline import Outline, PlotPoint, PlotPointUpdate, StoryArc
from inkflow.domain.services.outline_service import OutlineService
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.outline_repo import SQLiteOutlineRepository

TS = datetime(2026, 8, 1, 10, 0, 0)


def _outline(project_id: uuid.UUID) -> Outline:
    """构造测试用大纲实体（overall 顶层，固定时间戳）."""
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id,
        name="整本大纲",
        level="overall",
        created_at=TS,
        updated_at=TS,
    )


def _point(
    outline_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    arc_id: uuid.UUID | None = None,
) -> PlotPoint:
    """构造测试用情节点实体（arc_id 可选挂载）."""
    return PlotPoint(
        id=uuid.uuid4(),
        outline_id=outline_id,
        project_id=project_id,
        name="主角登场",
        arc_id=arc_id,
        created_at=TS,
        updated_at=TS,
    )


def _arc(project_id: uuid.UUID, name: str = "主线弧") -> StoryArc:
    """构造测试用故事弧线实体."""
    return StoryArc(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite session — 每个测试一个全新数据库（启用 FK）."""
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


async def _seed_point_with_arc(
    session: AsyncSession, *, mount: bool = True
) -> tuple[uuid.UUID, PlotPoint, StoryArc]:
    """种 项目→大纲→弧线（同项目）→情节点。

    Returns:
        (pid, point, arc)：point/arc 的 id 已按 DB rowid 回读映射；
        mount=True 时情节点初始已挂载弧线，False 时未挂载（设置轨用）。
    """
    project = ProjectORM(name="测试项目")
    session.add(project)
    await session.commit()
    await session.refresh(project)
    pid = uuid.UUID(int=project.id)

    repo = SQLiteOutlineRepository(session)
    outline = await repo.add(_outline(pid))
    arc = await repo.add_arc(_arc(pid))
    point = await repo.add_point(_point(outline.id, pid, arc_id=arc.id if mount else None))
    return pid, point, arc


def _http_client(session: AsyncSession) -> AsyncClient:
    """独立 FastAPI app：outlines router + get_db override → 同一真 session。

    走真实 get_outline_service 组装链（镜像 test_outline_862.py，LangChainLLMClient
    构造不触凭据，可直接组装，不经 patch 服务层）。
    """
    app = FastAPI()
    app.include_router(router)

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_db] = _override_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def test_plot_point_update_coerces_valid_uuid_string() -> None:
    """模型层契约：合法 UUID 字符串 → 强制转 uuid.UUID 且值相等（#908 根因第一环）。

    RED 预期: smart union 保留 str → isinstance(..., uuid.UUID) False → 断言失败。
    GREEN 必实现: PlotPointUpdate.arc_id 加 mode="before" validator →
    _normalize_ref_field(v, "弧线关联")。
    """
    s = str(uuid.uuid4())
    upd = PlotPointUpdate(arc_id=s)

    assert isinstance(upd.arc_id, uuid.UUID)  # RED: str 保留 → False
    assert upd.arc_id == uuid.UUID(s)


def test_plot_point_update_uuid_object_passthrough() -> None:
    """模型层回归护栏：uuid.UUID 对象直通（不被 validator 破坏）."""
    u = uuid.uuid4()
    assert PlotPointUpdate(arc_id=u).arc_id == u


def test_whitespace_clear_sentinel_normalized() -> None:
    """纯空白字符串归一为 "" 清除哨兵（不抛错，清除态由 service 层转 None）。

    RED 预期: 当前无 validator，"  " 原样保留 → == "" 断言失败。
    """
    assert PlotPointUpdate(arc_id="   ").arc_id == ""
    assert PlotPointUpdate(arc_id=" \t ").arc_id == ""


def test_garbage_string_rejected_not_silently_cleared() -> None:
    """垃圾非空字符串（非 UUID）→ ValidationError，消息含「弧线关联」「合法 UUID」。

    RED 预期: 当前无校验，str 直接接受 → pytest.raises 失败（不抛错 = 静默清除入口）。
    """
    with pytest.raises(ValidationError) as excinfo:
        PlotPointUpdate(arc_id="not-a-uuid")
    msg = str(excinfo.value)
    assert "弧线关联" in msg
    assert "合法 UUID" in msg


def test_illegal_type_rejected() -> None:
    """非 str/UUID/None 类型（int）→ ValidationError，消息含「UUID」。

    RED 预期: 当前 union 报错消息不含「弧线关联」标签 → 断言失败。
    """
    with pytest.raises(ValidationError) as excinfo:
        PlotPointUpdate(arc_id=123)
    msg = str(excinfo.value)
    assert "弧线关联" in msg
    assert "UUID" in msg


@pytest.mark.integration
class TestPlotPoint908Service:
    """Service 层契约（真 in-memory SQLite）：设置/清除两分支现状护栏。"""

    async def test_update_point_arc_uuid_object_survives(self, db_session) -> None:
        """UUID 对象（进程内直通形态）经真 repo 链路 update → 落库且读回相等。

        当前应 PASS（回归护栏）：isinstance(uuid.UUID) 命中「设置」分支；GREEN 加
        validator 后 UUID 对象直通行为不得回归。
        """
        _, point, arc = await _seed_point_with_arc(db_session, mount=False)
        repo = SQLiteOutlineRepository(db_session)
        svc = OutlineService(repository=repo)

        result = await svc.update_point(point.id, PlotPointUpdate(arc_id=arc.id))
        assert result is not None
        assert result.arc_id == arc.id

        got = await repo.get_point(point.id.int)
        assert got is not None
        assert got.arc_id == arc.id

    async def test_update_point_arc_cleared_by_empty_sentinel(self, db_session) -> None:
        """空串哨兵经 service 走「清除」分支 → 落库 None（当前 PASS，GREEN 不得改坏）。"""
        _, point, arc = await _seed_point_with_arc(db_session)
        repo = SQLiteOutlineRepository(db_session)
        svc = OutlineService(repository=repo)
        assert point.arc_id == arc.id

        result = await svc.update_point(point.id, PlotPointUpdate(arc_id=""))
        assert result is not None
        assert result.arc_id is None

        got = await repo.get_point(point.id.int)
        assert got is not None
        assert got.arc_id is None


@pytest.mark.integration
class TestPlotPoint908HttpLink:
    """HTTP 全链路契约：真实 get_outline_service + 真 session（PATCH → GET 读回）。"""

    async def test_patch_plot_point_arc_id_via_http_json(self, db_session) -> None:
        """#908 核心 RED：PATCH body arc_id=合法 UUID 字符串 → 200 且落库读回相等。

        RED 预期: JSON 字符串经模型层保留 str → service 走「清除」分支 → PATCH 200
        但 body arc_id=null → == str(arc.id) 断言失败；GET 同样读回 null、
        arc_name 丢失。
        GREEN 必实现: 模型层转 UUID → service「设置」分支（弧线同项目存在，校验
        放行）→ PATCH/GET body 均 == str(arc.id)，GET 聚合 arc_name == 弧线名。
        """
        _, point, arc = await _seed_point_with_arc(db_session, mount=False)
        url = f"/api/v1/plot-points/{point.id}"
        async with _http_client(db_session) as client:
            resp = await client.patch(url, json={"arc_id": str(arc.id)})
            assert resp.status_code == 200
            assert resp.json()["arc_id"] == str(arc.id)  # RED: null

            resp2 = await client.get(url)
            assert resp2.status_code == 200
            assert resp2.json()["arc_id"] == str(arc.id)  # RED: null
            assert resp2.json()["arc_name"] == arc.name  # RED: null

    async def test_patch_plot_point_arc_clear_via_http_json(self, db_session) -> None:
        """清除语义回归护栏（当前 PASS）："" 与 null 均清除弧线归属 → 读回 null。"""
        _, point, _ = await _seed_point_with_arc(db_session)
        url = f"/api/v1/plot-points/{point.id}"
        async with _http_client(db_session) as client:
            resp = await client.patch(url, json={"arc_id": ""})
            assert resp.status_code == 200
            assert resp.json()["arc_id"] is None

            resp2 = await client.get(url)
            assert resp2.status_code == 200
            assert resp2.json()["arc_id"] is None
            assert resp2.json()["arc_name"] is None

            resp3 = await client.patch(url, json={"arc_id": None})
            assert resp3.status_code == 200
            assert resp3.json()["arc_id"] is None

    async def test_patch_plot_point_arc_id_not_modified_preserved(self, db_session) -> None:
        """不传 arc_id → 不修改（回归护栏，当前 PASS）：仅改名不得清弧线。"""
        _, point, arc = await _seed_point_with_arc(db_session)
        url = f"/api/v1/plot-points/{point.id}"
        async with _http_client(db_session) as client:
            resp = await client.patch(url, json={"name": "配角登场"})
            assert resp.status_code == 200
            assert resp.json()["name"] == "配角登场"
            assert resp.json()["arc_id"] == str(arc.id)

    async def test_patch_unknown_arc_returns_422(self, db_session) -> None:
        """非法设置不得静默吞：arc_id=不存在弧线的合法 UUID 字符串 → 422。

        RED 预期: str 被 service 当「清除」→ 200 且 null（用户要求被静默丢弃）。
        GREEN 必实现: validator 转 UUID → service「设置」分支 → get_arc 查无 →
        ArcNotInProjectError → 422。
        """
        _, point, _ = await _seed_point_with_arc(db_session)
        url = f"/api/v1/plot-points/{point.id}"
        async with _http_client(db_session) as client:
            resp = await client.patch(url, json={"arc_id": str(uuid.uuid4())})
            assert resp.status_code == 422  # RED: 当前 200

    async def test_patch_garbage_arc_id_returns_422(self, db_session) -> None:
        """垃圾字符串 arc_id（非 UUID 非空）→ 422（绝不静默清除）。

        RED 预期: 当前 union 对任意 str 均保留（"not-a-uuid" 也是 str）→ service 当
        「清除」→ 200 且原挂载被静默摘除 → status_code == 422 断言失败。
        GREEN 必实现: validator 抛 ValueError → FastAPI 422，且原 arc_id 挂载保持不变。
        """
        _, point, arc = await _seed_point_with_arc(db_session)
        url = f"/api/v1/plot-points/{point.id}"
        async with _http_client(db_session) as client:
            resp = await client.patch(url, json={"arc_id": "not-a-uuid"})
            assert resp.status_code == 422  # RED: 当前 200（静默清除）
            resp2 = await client.get(url)
            assert resp2.json()["arc_id"] == str(arc.id)  # RED: 被清除成 null
