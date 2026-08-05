"""章节 API 集成测试 — TDD RED 阶段.

使用 ASGITransport + AsyncClient 进行真实 HTTP 请求测试，
通过 app.dependency_overrides 将 get_db 替换为测试 db_session，
确保测试与 API 共享同一内存数据库。

fixture override_get_db 定义在 tests/api/conftest.py。
"""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_create_and_list_volumes(db_session, sample_project, override_get_db):
    """创建卷 → 列表返回."""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第一卷"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "第一卷"

        resp = await client.get(f"/api/v1/projects/{sample_project.id}/volumes")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_chapter_lifecycle(db_session, sample_project, override_get_db):
    """章节完整生命周期：创建 → 更新状态 → 删除."""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/projects/{sample_project.id}/chapters",
            json={"title": "第一章", "content": "测试内容hello"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["word_count"] > 0
        chapter_id = data["id"]

        resp = await client.patch(
            f"/api/v1/chapters/{chapter_id}",
            json={"status": "writing"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "writing"
        assert len(resp.json()["status_history"]) == 1

        resp = await client.delete(f"/api/v1/chapters/{chapter_id}")
        assert resp.status_code == 204


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_move_chapter_api(db_session, sample_project, override_get_db):
    """跨卷移动 API."""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "V1"},
        )
        r2 = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "V2"},
        )
        v1_id = r1.json()["id"]
        v2_id = r2.json()["id"]

        r3 = await client.post(
            f"/api/v1/projects/{sample_project.id}/chapters",
            json={"title": "移动章", "volume_id": v1_id},
        )
        ch_id = r3.json()["id"]

        resp = await client.post(
            f"/api/v1/chapters/{ch_id}/move?target_volume_id={v2_id}"
        )
        assert resp.status_code == 200
        assert resp.json()["volume_id"] == v2_id


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_get_volume_api(db_session, sample_project, override_get_db):
    """GET /api/v1/volumes/{volume_id}：成功 200 返回卷字段 + 404 卷不存在."""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第一卷"},
        )
        assert created.status_code == 201
        vol_id = created.json()["id"]

        resp = await client.get(f"/api/v1/volumes/{vol_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == vol_id
        assert data["title"] == "第一卷"
        assert data["project_id"] == created.json()["project_id"]

        missing = await client.get(
            "/api/v1/volumes/00000000-0000-0000-0000-000000000000"
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == "卷不存在"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_update_volume_api(db_session, sample_project, override_get_db):
    """PATCH /api/v1/volumes/{volume_id}：成功 200 改 title + 404 卷不存在."""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第一卷"},
        )
        assert created.status_code == 201
        vol_id = created.json()["id"]

        resp = await client.patch(
            f"/api/v1/volumes/{vol_id}", json={"title": "第一卷·修订"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == vol_id
        assert data["title"] == "第一卷·修订"

        missing = await client.patch(
            "/api/v1/volumes/00000000-0000-0000-0000-000000000000",
            json={"title": "不存在"},
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == "卷不存在"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_delete_volume_api(db_session, sample_project, override_get_db):
    """DELETE /api/v1/volumes/{volume_id}：成功 204 无 body + 404 卷不存在."""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第一卷"},
        )
        assert created.status_code == 201
        vol_id = created.json()["id"]

        resp = await client.delete(f"/api/v1/volumes/{vol_id}")
        assert resp.status_code == 204
        assert resp.content == b""

        # 删除后详情应 404
        after = await client.get(f"/api/v1/volumes/{vol_id}")
        assert after.status_code == 404

        # 再删不存在的卷仍是 404
        missing = await client.delete(f"/api/v1/volumes/{vol_id}")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "卷不存在"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_list_chapters_structure(db_session, sample_project, override_get_db):
    """GET /api/v1/projects/{project_id}/chapters：items/total/offset/limit 结构."""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for title in ("第一章", "第二章"):
            resp = await client.post(
                f"/api/v1/projects/{sample_project.id}/chapters",
                json={"title": title},
            )
            assert resp.status_code == 201

        resp = await client.get(f"/api/v1/projects/{sample_project.id}/chapters")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["offset"] == 0
        assert data["limit"] == 50
        assert len(data["items"]) == 2
        assert {c["title"] for c in data["items"]} == {"第一章", "第二章"}


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_list_chapters_filter_by_volume(
    db_session, sample_project, override_get_db
):
    """GET chapters 按 volume_id 过滤：只返回该卷下的章节."""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        vol = await client.post(
            f"/api/v1/projects/{sample_project.id}/volumes",
            json={"title": "第一卷"},
        )
        assert vol.status_code == 201
        v1_id = vol.json()["id"]

        r1 = await client.post(
            f"/api/v1/projects/{sample_project.id}/chapters",
            json={"title": "卷内章", "volume_id": v1_id},
        )
        r2 = await client.post(
            f"/api/v1/projects/{sample_project.id}/chapters",
            json={"title": "无卷章"},
        )
        assert r1.status_code == 201
        assert r2.status_code == 201

        resp = await client.get(
            f"/api/v1/projects/{sample_project.id}/chapters",
            params={"volume_id": v1_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "卷内章"
        assert data["items"][0]["volume_id"] == v1_id


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_list_chapters_filter_by_status(
    db_session, sample_project, override_get_db
):
    """GET chapters 按 status 过滤：只返回指定状态的章节."""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post(
            f"/api/v1/projects/{sample_project.id}/chapters",
            json={"title": "草稿章"},
        )
        r2 = await client.post(
            f"/api/v1/projects/{sample_project.id}/chapters",
            json={"title": "写作章"},
        )
        assert r1.status_code == 201
        assert r2.status_code == 201

        patched = await client.patch(
            f"/api/v1/chapters/{r2.json()['id']}", json={"status": "writing"}
        )
        assert patched.status_code == 200

        resp = await client.get(
            f"/api/v1/projects/{sample_project.id}/chapters",
            params={"status": "writing"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "写作章"
        assert data["items"][0]["status"] == "writing"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_list_chapters_pagination(db_session, sample_project, override_get_db):
    """GET chapters 分页：offset/limit 生效且 total 反映全量."""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for title in ("第一章", "第二章", "第三章"):
            resp = await client.post(
                f"/api/v1/projects/{sample_project.id}/chapters",
                json={"title": title},
            )
            assert resp.status_code == 201

        resp = await client.get(
            f"/api/v1/projects/{sample_project.id}/chapters",
            params={"offset": 1, "limit": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["offset"] == 1
        assert data["limit"] == 2
        assert len(data["items"]) == 2
        assert {c["title"] for c in data["items"]} == {"第二章", "第三章"}


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_get_chapter_api(db_session, sample_project, override_get_db):
    """GET /api/v1/chapters/{chapter_id}：成功 200 返回章节字段 + 404 章节不存在."""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            f"/api/v1/projects/{sample_project.id}/chapters",
            json={"title": "第一章", "content": "测试内容hello"},
        )
        assert created.status_code == 201
        chapter_id = created.json()["id"]

        resp = await client.get(f"/api/v1/chapters/{chapter_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == chapter_id
        assert data["title"] == "第一章"
        assert data["status"] == "draft"
        assert data["word_count"] > 0

        missing = await client.get(
            "/api/v1/chapters/00000000-0000-0000-0000-000000000000"
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == "章节不存在"
