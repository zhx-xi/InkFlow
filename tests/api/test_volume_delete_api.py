"""卷删除 API 集成测试 — TDD RED 阶段 (#648).

锁定 DELETE /api/v1/volumes/{volume_id} 的新删除语义：
- 卷下有章节且未指定处理方式 → 409 阻塞（废除「静默解绑到未分组」）
- delete_chapters=true → 级联删除章节（而非把章 volume_id 置 None）
- move_to=<vid> → 章节移动到目标卷后删除本卷
- 空卷直接删除（回归护栏）

使用 ASGITransport + AsyncClient 进行真实 HTTP 请求测试，
通过 app.dependency_overrides 将 get_db 替换为测试 db_session，
确保测试与 API 共享同一内存数据库（真实 DB 轨，不 Mock Service 层——
删除卷的阻塞/级联/移动语义在 Service/Repo 层，Mock 无法验证）。

fixture override_get_db 定义在 tests/api/conftest.py。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_delete_volume_with_chapters_no_param_409(
    db_session, sample_project, override_get_db
):
    """卷下有章节且未指定级联/移动 → 409 阻塞（旧实现静默解绑返回 204，本测试 RED）。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        vol = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第一卷"},
        )
        assert vol.status_code == 201
        v1_id = vol.json()["id"]

        for title in ("第一章", "第二章"):
            ch = await client.post(
                f"/api/v1/projects/{sample_project.id}/chapters",
                json={"title": title, "volume_id": v1_id},
            )
            assert ch.status_code == 201

        resp = await client.delete(f"/api/v1/volumes/{v1_id}")
        assert resp.status_code == 409
        assert resp.json()["detail"] == "卷下存在章节，请选择级联删除或移动到其他卷"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_delete_volume_cascade_chapters(
    db_session, sample_project, override_get_db
):
    """delete_chapters=true → 204 且卷下章节被真正级联删除（旧实现只解绑不删章，本测试 RED）。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        vol = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第一卷"},
        )
        assert vol.status_code == 201
        v1_id = vol.json()["id"]

        ch_ids = []
        for title in ("第一章", "第二章"):
            ch = await client.post(
                f"/api/v1/projects/{sample_project.id}/chapters",
                json={"title": title, "volume_id": v1_id},
            )
            assert ch.status_code == 201
            ch_ids.append(ch.json()["id"])
        ch1_id = ch_ids[0]

        resp = await client.delete(f"/api/v1/volumes/{v1_id}?delete_chapters=true")
        assert resp.status_code == 204
        assert resp.content == b""

        # 卷本身已删除
        after = await client.get(f"/api/v1/volumes/{v1_id}")
        assert after.status_code == 404

        # 关键：章节被真正级联删除，而非解绑到未分组（旧实现置 volume_id=None，
        # 章仍存在 → GET 200，此断言让测试 RED）
        ch1 = await client.get(f"/api/v1/chapters/{ch1_id}")
        assert ch1.status_code == 404

        # 原卷下章节列表为空
        listing = await client.get(
            f"/api/v1/projects/{sample_project.id}/chapters",
            params={"volume_id": v1_id},
        )
        assert listing.status_code == 200
        assert listing.json()["total"] == 0


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_delete_volume_move_chapters_to_target(
    db_session, sample_project, override_get_db
):
    """move_to=<vid> → 204 且卷下章节改挂目标卷（旧实现把章 volume_id 置 None，本测试 RED）。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第一卷"},
        )
        r2 = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第二卷"},
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        v1_id = r1.json()["id"]
        v2_id = r2.json()["id"]

        ch_ids = []
        for title in ("第一章", "第二章"):
            ch = await client.post(
                f"/api/v1/projects/{sample_project.id}/chapters",
                json={"title": title, "volume_id": v1_id},
            )
            assert ch.status_code == 201
            ch_ids.append(ch.json()["id"])
        ch1_id = ch_ids[0]

        resp = await client.delete(f"/api/v1/volumes/{v1_id}?move_to={v2_id}")
        assert resp.status_code == 204

        # 卷本身已删除
        after = await client.get(f"/api/v1/volumes/{v1_id}")
        assert after.status_code == 404

        # 关键：章节改挂到 V2（旧实现把章 volume_id 置 None → total 0，此断言让测试 RED）
        listing = await client.get(
            f"/api/v1/projects/{sample_project.id}/chapters",
            params={"volume_id": v2_id},
        )
        assert listing.status_code == 200
        data = listing.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert {c["title"] for c in data["items"]} == {"第一章", "第二章"}

        # 章节详情确认归属目标卷
        ch1 = await client.get(f"/api/v1/chapters/{ch1_id}")
        assert ch1.status_code == 200
        assert ch1.json()["volume_id"] == v2_id


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_delete_volume_move_to_nonexistent_422(
    db_session, sample_project, override_get_db
):
    """move_to=<不存在的卷 id> → 422（旧实现忽略参数直接删除返回 204，本测试 RED）。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        vol = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第一卷"},
        )
        assert vol.status_code == 201
        v1_id = vol.json()["id"]

        ch = await client.post(
            f"/api/v1/projects/{sample_project.id}/chapters",
            json={"title": "第一章", "volume_id": v1_id},
        )
        assert ch.status_code == 201

        ghost_id = str(uuid.uuid4())
        resp = await client.delete(f"/api/v1/volumes/{v1_id}?move_to={ghost_id}")
        assert resp.status_code == 422
        assert "detail" in resp.json()


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_delete_volume_move_to_self_422(
    db_session, sample_project, override_get_db
):
    """move_to=<本卷 id> → 422（旧实现忽略参数直接删除返回 204，本测试 RED）。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        vol = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第一卷"},
        )
        assert vol.status_code == 201
        v1_id = vol.json()["id"]

        ch = await client.post(
            f"/api/v1/projects/{sample_project.id}/chapters",
            json={"title": "第一章", "volume_id": v1_id},
        )
        assert ch.status_code == 201

        resp = await client.delete(f"/api/v1/volumes/{v1_id}?move_to={v1_id}")
        assert resp.status_code == 422
        assert "detail" in resp.json()


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_delete_volume_empty_204(db_session, sample_project, override_get_db):
    """空卷（无章节）直接删除 → 204 无 body + 卷 404（回归护栏，新旧实现均通过）。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        vol = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第一卷"},
        )
        assert vol.status_code == 201
        v1_id = vol.json()["id"]

        resp = await client.delete(f"/api/v1/volumes/{v1_id}")
        assert resp.status_code == 204
        assert resp.content == b""

        after = await client.get(f"/api/v1/volumes/{v1_id}")
        assert after.status_code == 404
