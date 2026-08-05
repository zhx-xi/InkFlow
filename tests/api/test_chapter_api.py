"""章节 API 集成测试 — TDD RED 阶段.

使用 ASGITransport + AsyncClient 进行真实 HTTP 请求测试，
通过 app.dependency_overrides 将 get_db 替换为测试 db_session，
确保测试与 API 共享同一内存数据库。

fixture override_get_db 定义在 tests/api/conftest.py。

# Issue #104 Phase 3 覆盖率补齐：mock 服务层补 chapter router 剩余 miss。
# 背景：既有 chapter 测试走真实 DB（aiosqlite 线程池），coverage 对
# 「await 之后的行」（return / None→404 分支）存在测量盲区；mock 版测试
# （TestClient + @patch(get_chapter_service)）与 tests/unit/test_outline_api.py
# 同策略，await AsyncMock 无线程池切换，可完整覆盖端点函数的全部行。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.domain.models.chapter import Chapter, ChapterStatus, Volume

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


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


# ═══════════════════════════════════════════════════════════════════════════
# Issue #104 Phase 3 覆盖率补齐：_parse_id 非法格式 404 / None 路径 404 分支
# ═══════════════════════════════════════════════════════════════════════════


def test_parse_id_accepts_uuid_int_and_rejects_invalid():
    """_parse_id：UUID 字符串 / 整数格式（非 hex 但 int 可解析）→ UUID；非法 → 404。"""
    import uuid as uuid_module

    from fastapi import HTTPException

    from inkflow.api.routers.chapter import _parse_id

    uid = uuid_module.uuid4()
    assert _parse_id(str(uid)) == uid
    assert _parse_id("+123") == uuid_module.UUID(int=123)

    with pytest.raises(HTTPException) as exc_info:
        _parse_id("xyz", detail="自定义详情")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "自定义详情"


def _volume(**kw) -> Volume:
    """构造测试用卷实体（固定时间戳，便于断言）。"""
    base = {
        "id": uuid.uuid4(),
        "project_id": PID,
        "title": "第一卷",
        "order_index": 1.0,
    }
    base.update(kw)
    return Volume(**base)


def _chapter(**kw) -> Chapter:
    """构造测试用章节实体。"""
    base = {
        "id": uuid.uuid4(),
        "project_id": PID,
        "title": "第一章",
        "content": "测试内容",
        "status": ChapterStatus.DRAFT,
        "word_count": 4,
        "order_index": 1.0,
        "created_at": TS,
        "updated_at": TS,
    }
    base.update(kw)
    return Chapter(**base)


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock ChapterService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestVolumeAPIMocked:
    """卷端点 — mock 服务层（覆盖 await 后 return/404 分支）。"""

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_create_volume_success(self, mock_get_svc: MagicMock) -> None:
        """创建卷返回 201 + Volume JSON。"""
        svc = _mock_svc(mock_get_svc)
        vol = _volume(title="第一卷·修订", order_index=2.5)
        svc.create_volume = AsyncMock(return_value=vol)

        response = client.post(
            f"/api/v1/projects/{PID}/volumes",
            json={"title": "第一卷·修订", "order_index": 2.5},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(vol.id)
        assert data["title"] == "第一卷·修订"
        assert data["project_id"] == str(PID)
        assert data["order_index"] == 2.5
        svc.create_volume.assert_awaited_once_with(PID, "第一卷·修订", 2.5)

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_list_volumes_success(self, mock_get_svc: MagicMock) -> None:
        """卷列表返回 200 + items。"""
        svc = _mock_svc(mock_get_svc)
        vol = _volume()
        svc.list_volumes = AsyncMock(return_value=[vol])

        response = client.get(f"/api/v1/projects/{PID}/volumes")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == str(vol.id)
        assert data["items"][0]["title"] == "第一卷"
        svc.list_volumes.assert_awaited_once_with(PID)

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_get_volume_missing_404(self, mock_get_svc: MagicMock) -> None:
        """卷不存在返回 404（get_volume None 分支）。"""
        svc = _mock_svc(mock_get_svc)
        svc.get_volume = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/volumes/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "卷不存在"

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_update_volume_missing_404(self, mock_get_svc: MagicMock) -> None:
        """更新不存在的卷返回 404（update_volume None 分支）。"""
        svc = _mock_svc(mock_get_svc)
        svc.update_volume = AsyncMock(return_value=None)

        response = client.patch(
            f"/api/v1/volumes/{uuid.uuid4()}", json={"title": "不存在"}
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "卷不存在"

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_delete_volume_missing_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的卷返回 404（delete_volume False 分支）。"""
        svc = _mock_svc(mock_get_svc)
        svc.delete_volume = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/volumes/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "卷不存在"


class TestChapterAPIMocked:
    """章节端点 — mock 服务层（覆盖 await 后 return/404 分支）。"""

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_create_chapter_success(self, mock_get_svc: MagicMock) -> None:
        """创建章节返回 201 + Chapter JSON。"""
        svc = _mock_svc(mock_get_svc)
        ch = _chapter(title="第一章·定稿", content="正文内容")
        svc.create_chapter = AsyncMock(return_value=ch)

        response = client.post(
            f"/api/v1/projects/{PID}/chapters",
            json={"title": "第一章·定稿", "content": "正文内容", "order_index": 3},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(ch.id)
        assert data["title"] == "第一章·定稿"
        assert data["status"] == "draft"
        svc.create_chapter.assert_awaited_once_with(
            PID, "第一章·定稿", None, "正文内容", 3
        )

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_list_chapters_success(self, mock_get_svc: MagicMock) -> None:
        """章节列表返回 200 + items/total/offset/limit。"""
        svc = _mock_svc(mock_get_svc)
        ch = _chapter()
        svc.list_chapters = AsyncMock(return_value=([ch], 1))

        response = client.get(
            f"/api/v1/projects/{PID}/chapters", params={"offset": 0, "limit": 10}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 10
        assert data["items"][0]["id"] == str(ch.id)
        svc.list_chapters.assert_awaited_once_with(PID, None, None, 0, 10)

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_get_chapter_missing_404(self, mock_get_svc: MagicMock) -> None:
        """章节不存在返回 404（get_chapter None 分支）。"""
        svc = _mock_svc(mock_get_svc)
        svc.get_chapter = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/chapters/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "章节不存在"

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_update_chapter_missing_404(self, mock_get_svc: MagicMock) -> None:
        """更新不存在的章节返回 404（update_chapter None 分支）。"""
        svc = _mock_svc(mock_get_svc)
        svc.update_chapter = AsyncMock(return_value=None)

        response = client.patch(
            f"/api/v1/chapters/{uuid.uuid4()}", json={"title": "不存在"}
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "章节不存在"

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_delete_chapter_missing_404(self, mock_get_svc: MagicMock) -> None:
        """删除不存在的章节返回 404（delete_chapter False 分支）。"""
        svc = _mock_svc(mock_get_svc)
        svc.delete_chapter = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/chapters/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "章节不存在"

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_move_chapter_missing_404(self, mock_get_svc: MagicMock) -> None:
        """移动不存在的章节返回 404（move_chapter None 分支）。"""
        svc = _mock_svc(mock_get_svc)
        svc.move_chapter = AsyncMock(return_value=None)

        response = client.post(f"/api/v1/chapters/{uuid.uuid4()}/move")
        assert response.status_code == 404
        assert response.json()["detail"] == "章节不存在"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_create_volume_invalid_project_id_404(db_session, override_get_db):
    """POST volumes 项目 ID 非法格式 → 404「项目不存在」（_parse_id 错误分支）。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/projects/not-a-uuid/volumes", json={"title": "卷"}
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "项目不存在"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_get_chapter_invalid_id_404(db_session, override_get_db):
    """GET chapter 非法 ID 格式 → 404「章节不存在」。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/chapters/not-a-uuid")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "章节不存在"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_update_chapter_missing_404(db_session, override_get_db):
    """PATCH 不存在的章节 → 404「章节不存在」（update_chapter None 路径）。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            "/api/v1/chapters/00000000-0000-0000-0000-000000000000",
            json={"title": "不存在"},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "章节不存在"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_delete_chapter_missing_404(db_session, override_get_db):
    """DELETE 不存在的章节 → 404「章节不存在」（delete_chapter False 路径）。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            "/api/v1/chapters/00000000-0000-0000-0000-000000000000"
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "章节不存在"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_move_chapter_missing_404(db_session, override_get_db):
    """move 不存在的章节 → 404「章节不存在」（move_chapter None 路径）。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chapters/00000000-0000-0000-0000-000000000000/move"
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "章节不存在"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_move_chapter_invalid_target_volume_404(
    db_session, sample_project, override_get_db
):
    """move 目标卷 ID 非法格式 → 404（_parse_id 默认 detail「资源不存在」）。"""
    from inkflow.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            f"/api/v1/projects/{sample_project.id}/chapters",
            json={"title": "第一章"},
        )
        assert created.status_code == 201
        chapter_id = created.json()["id"]

        resp = await client.post(
            f"/api/v1/chapters/{chapter_id}/move?target_volume_id=bad-id"
        )
    assert resp.status_code == 404


class TestChapterAPIMockedSuccess:
    """章节端点成功路径 — mock 服务层（覆盖 await 后 return 行）。"""

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_get_chapter_success(self, mock_get_svc: MagicMock) -> None:
        """章节详情成功返回 200（get_chapter 非 None → return 行）。"""
        svc = _mock_svc(mock_get_svc)
        ch = _chapter()
        svc.get_chapter = AsyncMock(return_value=ch)

        response = client.get(f"/api/v1/chapters/{ch.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(ch.id)
        assert data["title"] == "第一章"
        svc.get_chapter.assert_awaited_once_with(ch.id)

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_update_chapter_success(self, mock_get_svc: MagicMock) -> None:
        """更新章节成功返回 200（update_chapter 非 None → return 行）。"""
        svc = _mock_svc(mock_get_svc)
        ch = _chapter(title="第一章·修订")
        svc.update_chapter = AsyncMock(return_value=ch)

        response = client.patch(
            f"/api/v1/chapters/{ch.id}", json={"title": "第一章·修订"}
        )
        assert response.status_code == 200
        assert response.json()["title"] == "第一章·修订"
        svc.update_chapter.assert_awaited_once()

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_delete_chapter_success(self, mock_get_svc: MagicMock) -> None:
        """删除章节成功返回 204（delete_chapter True → if not ok False 分支）。"""
        svc = _mock_svc(mock_get_svc)
        svc.delete_chapter = AsyncMock(return_value=True)

        response = client.delete(f"/api/v1/chapters/{uuid.uuid4()}")
        assert response.status_code == 204
        assert response.content == b""

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_move_chapter_success(self, mock_get_svc: MagicMock) -> None:
        """移动章节成功返回 200（move_chapter 非 None → return 行）。"""
        svc = _mock_svc(mock_get_svc)
        ch = _chapter(volume_id=PID)
        svc.move_chapter = AsyncMock(return_value=ch)

        response = client.post(
            f"/api/v1/chapters/{ch.id}/move", params={"target_volume_id": str(PID)}
        )
        assert response.status_code == 200
        assert response.json()["volume_id"] == str(PID)
        svc.move_chapter.assert_awaited_once_with(ch.id, PID)


class TestVolumeAPIMockedSuccess:
    """卷端点成功路径 — mock 服务层（覆盖 await 后 return 行）。"""

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_get_volume_success(self, mock_get_svc: MagicMock) -> None:
        """卷详情成功返回 200（get_volume 非 None → return 行）。"""
        svc = _mock_svc(mock_get_svc)
        vol = _volume()
        svc.get_volume = AsyncMock(return_value=vol)

        response = client.get(f"/api/v1/volumes/{vol.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(vol.id)
        assert data["title"] == "第一卷"
        svc.get_volume.assert_awaited_once_with(vol.id)

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_update_volume_success(self, mock_get_svc: MagicMock) -> None:
        """更新卷成功返回 200（update_volume 非 None → return 行）。"""
        svc = _mock_svc(mock_get_svc)
        vol = _volume(title="第一卷·修订")
        svc.update_volume = AsyncMock(return_value=vol)

        response = client.patch(
            f"/api/v1/volumes/{vol.id}", json={"title": "第一卷·修订"}
        )
        assert response.status_code == 200
        assert response.json()["title"] == "第一卷·修订"
        svc.update_volume.assert_awaited_once()

    @patch("inkflow.api.routers.chapter.get_chapter_service")
    def test_delete_volume_success(self, mock_get_svc: MagicMock) -> None:
        """删除卷成功返回 204（delete_volume True → if not ok False 分支）。"""
        svc = _mock_svc(mock_get_svc)
        svc.delete_volume = AsyncMock(return_value=True)

        response = client.delete(f"/api/v1/volumes/{uuid.uuid4()}")
        assert response.status_code == 204
        assert response.content == b""
