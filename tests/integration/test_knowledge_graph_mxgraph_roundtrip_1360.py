"""#1360 drawio（mxGraph XML）端到端往返 — 真 DB + 真 repo（M9；只写测试，不改 src/）.

TestClient（ASGI）+ in-memory SQLite + 真仓储装配（镜像本目录
test_export_roundtrip.py / backend/tests/unit/infrastructure/database/
test_knowledge_relation_repo.py 的 fixture 形态）：

- 数据面：`get_knowledge_graph_service(db)` 真装配 → create_relation 逐条建关系；
  ORM 真写入 projects/characters/world_settings（实体校验走真仓储）。
- 契约面：HTTP 端点（§5.7.2/§5.7.3）——**往返幂等**、冲突跳过、非法 XML 不落库、
  replace 清空语义。
- 本地 UUID 口径：`uuid.UUID(int=<orm.id>)`（F1 惯例，仓储层入参统一领域 UUID）。

【RED 预期】端点/编解码未实现 → 导出 404 / import 401 等 → 用例 FAIL。

依据: specs/f48-knowledge-graph/spec.md §5.7/§9 场景 18-22/§13 M9。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api.app import app
from inkflow.api.deps import get_db, get_knowledge_graph_service
from inkflow.core.database import Base
from inkflow.infrastructure.database.models.character import CharacterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.world import WorldSettingORM

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
pytestmark = pytest.mark.asyncio

PROJECT_NAME = "测试书稿"
CHAR_A = "角色甲"
CHAR_B = "角色乙"
WORLD_A = "门派乙"


# ── Fixtures ───────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """独立 in-memory SQLite — 每测试一个全新库（FK pragma 同生产）。"""
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


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    """ASGI 客户端 + get_db 覆盖到本测试库（无 token 模式）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


# ── 造数 ───────────────────────────────────────────────────────────


async def _seed(db_session: AsyncSession) -> dict:
    """项目 + 2 角色 + 1 世界观（真 ORM 写入），返回各实体领域 UUID。"""
    project = ProjectORM(name=PROJECT_NAME, language="zh-CN", target_words=200000, tags=["仙侠"])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    char_a = CharacterORM(
        project_id=project.id, name=CHAR_A, personality="", background="", goals=""
    )
    char_b = CharacterORM(
        project_id=project.id, name=CHAR_B, personality="", background="", goals=""
    )
    world_a = WorldSettingORM(
        project_id=project.id, name=WORLD_A, category="geo", content="门派所在"
    )
    db_session.add_all([char_a, char_b, world_a])
    await db_session.commit()
    for row in (char_a, char_b, world_a):
        await db_session.refresh(row)

    return {
        "pid": uuid.UUID(int=project.id),
        "char_a": uuid.UUID(int=char_a.id),
        "char_b": uuid.UUID(int=char_b.id),
        "world_a": uuid.UUID(int=world_a.id),
        "pid_str": str(uuid.UUID(int=project.id)),
    }


async def _create_relation(db_session: AsyncSession, ids: dict, **kw) -> None:
    """经真 service 校验链建关系（默认「角色甲 --师承--> 角色乙」）。"""
    svc = get_knowledge_graph_service(db_session)
    await svc.create_relation(
        ids["pid"],
        kw.get("source_type", "character"),
        kw.get("source_id", ids["char_a"]),
        kw.get("target_type", "character"),
        kw.get("target_id", ids["char_b"]),
        kw.get("relation_type", "师承"),
        kw.get("description", ""),
    )


def _export_url(pid_str: str) -> str:
    return f"/api/v1/projects/{pid_str}/knowledge-graph/export?format=mxgraph"


def _import_url(pid_str: str, mode: str) -> str:
    return f"/api/v1/projects/{pid_str}/knowledge-graph/import?mode={mode}"


def _xml(*cells: str) -> str:
    body = "".join(cells)
    head = (
        '<mxfile host="InkFlow" type="device">'
        '<diagram id="inkflow-knowledge-graph" name="知识图谱">'
    )
    model = (
        '<mxGraphModel dx="800" dy="600" grid="1" gridSize="10" page="1"'
        ' pageWidth="850" pageHeight="1100">'
    )
    return (
        f"{head}{model}"
        f'<root><mxCell id="0" /><mxCell id="1" parent="0" />{body}</root>'
        "</mxGraphModel></diagram></mxfile>"
    )


def _edge_cell(
    edge_id: str, label: str, source: str, target: str, tooltip: str | None = None
) -> str:
    tip = f' tooltip="{tooltip}"' if tooltip is not None else ""
    cell = (
        '<mxCell edge="1" parent="1" style="endArrow=classic;"'
        f' source="{source}" target="{target}">'
        '<mxGeometry relative="1" as="geometry" /></mxCell>'
    )
    return f'<object id="{edge_id}" label="{label}"{tip}>{cell}</object>'


# ── 往返幂等 ───────────────────────────────────────────────────────


async def test_export_import_export_is_byte_stable(db_session, client) -> None:
    """场景 18：导出 → 导入(merge，同键全命中) → 再导出，逐字节相等。"""
    ids = await _seed(db_session)
    await _create_relation(db_session, ids, relation_type="师承")
    await _create_relation(
        db_session,
        ids,
        target_type="world",
        target_id=ids["world_a"],
        relation_type="属于",
        description="出身门派",
    )

    first = await client.get(_export_url(ids["pid_str"]))
    assert first.status_code == 200
    xml1 = first.text
    assert 'label="师承"' in xml1 and 'label="属于"' in xml1
    assert f'id="character:{ids["char_a"]}"' in xml1
    assert 'tooltip="出身门派"' in xml1

    imported = await client.post(
        _import_url(ids["pid_str"], "merge"),
        content=xml1.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )
    assert imported.status_code == 200
    body = imported.json()
    assert (body["total"], body["imported"], body["skipped"], body["failed"]) == (2, 0, 2, 0)

    second = await client.get(_export_url(ids["pid_str"]))
    assert second.status_code == 200
    assert second.text == xml1


async def test_export_twice_is_identical(db_session, client) -> None:
    """导出为只读纯函数：同数据两次 GET 字节相等。"""
    ids = await _seed(db_session)
    await _create_relation(db_session, ids)
    a = await client.get(_export_url(ids["pid_str"]))
    b = await client.get(_export_url(ids["pid_str"]))
    assert a.status_code == b.status_code == 200
    assert a.text == b.text


async def test_export_without_relations_is_empty(db_session, client) -> None:
    ids = await _seed(db_session)
    resp = await client.get(_export_url(ids["pid_str"]))
    assert resp.status_code == 200
    assert 'edge="1"' not in resp.text
    assert 'vertex="1"' not in resp.text


# ── 冲突跳过 / 校验拒绝 ────────────────────────────────────────────


async def test_conflict_skipped_and_counts_identity(db_session, client) -> None:
    """场景 19：1 新边 + 1 既有边 + 1 自环边 → imported/skipped/failed 各 1。"""
    ids = await _seed(db_session)
    await _create_relation(db_session, ids, relation_type="师承")

    xml = _xml(
        _edge_cell("kr:new", "宿敌", f"character:{ids['char_a']}", f"character:{ids['char_b']}"),
        _edge_cell("kr:dup", "师承", f"character:{ids['char_a']}", f"character:{ids['char_b']}"),
        _edge_cell("kr:loop", "自指", f"character:{ids['char_a']}", f"character:{ids['char_a']}"),
    )
    resp = await client.post(
        _import_url(ids["pid_str"], "merge"),
        content=xml.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert (body["imported"], body["skipped"], body["failed"]) == (1, 1, 1)
    assert body["total"] == body["imported"] + body["skipped"] + body["failed"]
    kinds = sorted(d["kind"] for d in body["details"])
    assert kinds == ["failed", "skipped"]


async def test_cross_project_entity_uses_existing_rejection(db_session, client) -> None:
    """场景 21：边指向其它项目的实体 → failed（不 500），其余边照常导入。"""
    ids = await _seed(db_session)
    other = ProjectORM(name="另一个项目", language="zh-CN", target_words=100000, tags=[])
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    foreign = CharacterORM(
        project_id=other.id, name="外来者", personality="", background="", goals=""
    )
    db_session.add(foreign)
    await db_session.commit()
    await db_session.refresh(foreign)

    xml = _xml(
        _edge_cell(
            "kr:cross", "属于", f"character:{uuid.UUID(int=foreign.id)}", f"world:{ids['world_a']}"
        ),
        _edge_cell("kr:ok", "师承", f"character:{ids['char_a']}", f"character:{ids['char_b']}"),
    )
    resp = await client.post(
        _import_url(ids["pid_str"], "merge"),
        content=xml.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert (body["imported"], body["failed"]) == (1, 1)
    assert "同一项目" in body["details"][0]["reason"]


async def test_unresolvable_endpoint_counts_failed(db_session, client) -> None:
    """场景 21：手工在 drawio 新画的节点（id 非 InkFlow 实体引用）→ failed。"""
    ids = await _seed(db_session)
    xml = _xml(_edge_cell("kr:x", "师承", "X1a2b3c", f"character:{ids['char_b']}"))
    resp = await client.post(
        _import_url(ids["pid_str"], "merge"),
        content=xml.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body["imported"], body["failed"]) == (0, 1)
    assert "端点无法解析" in body["details"][0]["reason"]


# ── 非法 XML / replace 语义 ────────────────────────────────────────


async def test_invalid_xml_422_and_replace_deletes_nothing(db_session, client) -> None:
    """场景 20：解析失败时数据零变更（replace 也不清空）。"""
    ids = await _seed(db_session)
    await _create_relation(db_session, ids, relation_type="师承")

    bad = await client.post(
        _import_url(ids["pid_str"], "replace"),
        content=b"<mxfile><diagram></mxfile>",
        headers={"Content-Type": "application/xml"},
    )
    assert bad.status_code == 422
    assert "非法 mxGraph XML" in bad.json()["detail"]

    still = await client.get(f"/api/v1/projects/{ids['pid_str']}/knowledge-relations")
    assert still.status_code == 200
    assert still.json()["total"] == 1


async def test_replace_clears_then_writes(db_session, client) -> None:
    """场景 22：replace 清空既有关系再写入文件内容。"""
    ids = await _seed(db_session)
    await _create_relation(db_session, ids, relation_type="师承")
    await _create_relation(
        db_session, ids, target_type="world", target_id=ids["world_a"], relation_type="属于"
    )

    xml = _xml(
        _edge_cell("kr:new", "宿敌", f"character:{ids['char_a']}", f"character:{ids['char_b']}")
    )
    resp = await client.post(
        _import_url(ids["pid_str"], "replace"),
        content=xml.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert (body["deleted"], body["imported"]) == (2, 1)

    remaining = await client.get(f"/api/v1/projects/{ids['pid_str']}/knowledge-relations")
    assert remaining.json()["total"] == 1
    assert remaining.json()["items"][0]["relation_type"] == "宿敌"


async def test_merge_keeps_existing_rows(db_session, client) -> None:
    """merge 恒 deleted=0，既有行保留。"""
    ids = await _seed(db_session)
    await _create_relation(db_session, ids, relation_type="师承")

    xml = _xml(
        _edge_cell("kr:new", "宿敌", f"character:{ids['char_a']}", f"character:{ids['char_b']}")
    )
    resp = await client.post(
        _import_url(ids["pid_str"], "merge"),
        content=xml.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0

    after = await client.get(f"/api/v1/projects/{ids['pid_str']}/knowledge-relations")
    assert after.json()["total"] == 2
