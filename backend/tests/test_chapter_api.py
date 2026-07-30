"""章节 API 集成测试 — TDD RED 阶段.

使用 ASGITransport + AsyncClient 进行真实 HTTP 请求测试，
通过 app.dependency_overrides 将 get_db 替换为测试 db_session，
确保测试与 API 共享同一内存数据库。
"""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def override_get_db(db_session):
    """将 FastAPI 的 get_db 替换为测试的 db_session，实现同库访问。"""
    from inkflow.api.deps import get_db

    async def _get_db_override():
        yield db_session

    from inkflow.api.app import app

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
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

        resp = await client.post(f"/api/v1/chapters/{ch_id}/move?target_volume_id={v2_id}")
        assert resp.status_code == 200
        assert resp.json()["volume_id"] == v2_id
