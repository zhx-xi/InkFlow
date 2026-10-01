"""#1430 方案 A：旧稿备份读口（恢复读口）API 契约（RED→GREEN）。

权威来源：issue #1430 实现清单第 3 条（恢复读口先 API；GUI 入口可另开单）。

契约（本契约冻结）
==================

- `POST /api/v1/chapters/{chapter_id}/restore-previous` → **200** 章 JSON
  （`previous_content` 写回 `content`；恢复动作自身也遵守覆盖口径 →
  `content` ⇄ `previous_content` 双向切换，可再恢复回去）
- 无可恢复的旧稿（`previous_content` 空/纯空白）→ **409**，detail「无可恢复的旧稿」
- 章不存在 → **404**
- `chapters.previous_content` 随章资源可见（`GET`/`PATCH`/`POST` 响应含该字段）——
  这是「不做静默备份」的读侧保证：用户能从章资源直接看到备份在位。

RED 形态：端点不存在 → 405/404；`previous_content` 字段不存在 → 第 1 步断言失败。
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app

TS = datetime(2026, 10, 2, 10, 0, 0, tzinfo=UTC)

_FIRST_DRAFT = "第一稿正文甲"
_SECOND_DRAFT = "第二稿正文乙"


async def _create_chapter(client: AsyncClient, project_id: uuid.UUID, content: str) -> dict:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={"title": "第一章 起", "content": content},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
@pytest.mark.api
async def test_chapter_create_has_no_previous_content_shell(
    db_session, sample_project, override_get_db
):
    """新建章无旧稿 → previous_content 为 None（不留空壳）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = await _create_chapter(client, sample_project.id, _FIRST_DRAFT)

    assert body["content"] == _FIRST_DRAFT
    assert body.get("previous_content") is None


@pytest.mark.asyncio
@pytest.mark.api
async def test_overwrite_then_restore_round_trip(db_session, sample_project, override_get_db):
    """覆盖 → 旧稿落 previous_content → 恢复读口写回（端到端往返）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await _create_chapter(client, sample_project.id, _FIRST_DRAFT)
        chapter_id = created["id"]

        overwritten = await client.patch(
            f"/api/v1/chapters/{chapter_id}", json={"content": _SECOND_DRAFT}
        )
        assert overwritten.status_code == 200, overwritten.text
        assert overwritten.json()["content"] == _SECOND_DRAFT
        assert overwritten.json()["previous_content"] == _FIRST_DRAFT  # 覆盖前必落，逐字

        restored = await client.post(f"/api/v1/chapters/{chapter_id}/restore-previous")
        assert restored.status_code == 200, restored.text
        assert restored.json()["content"] == _FIRST_DRAFT
        # 恢复动作本身也遵守覆盖口径 → 被替换的新正文落回备份位（可再切回）
        assert restored.json()["previous_content"] == _SECOND_DRAFT

        # 落库可回读（不是只改了响应体）
        readback = await client.get(f"/api/v1/chapters/{chapter_id}")
        assert readback.status_code == 200
        assert readback.json()["content"] == _FIRST_DRAFT
        assert readback.json()["previous_content"] == _SECOND_DRAFT


@pytest.mark.asyncio
@pytest.mark.api
async def test_restore_without_backup_409(db_session, sample_project, override_get_db):
    """没有旧稿可恢复 → 409「无可恢复的旧稿」（不静默 200）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await _create_chapter(client, sample_project.id, _FIRST_DRAFT)

        resp = await client.post(f"/api/v1/chapters/{created['id']}/restore-previous")

    assert resp.status_code == 409
    assert "无可恢复的旧稿" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.api
async def test_restore_unknown_chapter_404(db_session, sample_project, override_get_db):
    """章不存在 → 404。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/chapters/{uuid.uuid4()}/restore-previous")

    assert resp.status_code == 404
