"""#1001 API 契约 — HTTP 装配闭环：正文落盘 → GET outlines.chapter_id 非空.

验证 `api/deps.get_chapter_service` 真实装配（outline_autolinker 注入）在 HTTP 层生效。
形态镜像 tests/api/test_chapter_normalize_titles_api.py（ASGITransport +
app.dependency_overrides 替换 get_db 同库访问；sample_project/db_session 来自顶层
tests/conftest.py 共享 fixture）。

铁律: pytest fixture 不跨模块注入——本文件本地镜像 client fixture。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.app import app
from inkflow.api.deps import get_db

TITLE = "第一章 启程"
CONTENT = "启程一章的正文（HTTP 装配契约）。"


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """本地镜像 ASGI 客户端：get_db 覆盖为测试 db_session（同库访问）。"""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _create_outline(client: AsyncClient, project_id: int, name: str) -> dict:
    """经真实 API 建合法树形的章级大纲（overall → volume → chapter）.

    F43 v1.5 / #835 起强制树形：``level=chapter`` 必须挂 ``level=volume`` 父大纲
    （裸章级大纲 422「章大纲必须挂载在卷大纲下」）——seed 必须先建整体/卷两级。
    """
    overall = await client.post(
        f"/api/v1/projects/{project_id}/outlines",
        json={"name": f"{name}-总纲", "level": "overall"},
    )
    assert overall.status_code == 201
    volume = await client.post(
        f"/api/v1/projects/{project_id}/outlines",
        json={
            "name": f"{name}-卷纲",
            "level": "volume",
            "parent_id": overall.json()["id"],
        },
    )
    assert volume.status_code == 201
    chapter_outline = await client.post(
        f"/api/v1/projects/{project_id}/outlines",
        json={"name": name, "level": "chapter", "parent_id": volume.json()["id"]},
    )
    assert chapter_outline.status_code == 201
    return chapter_outline.json()


async def _create_chapter(
    client: AsyncClient, project_id: int, title: str, content: str = ""
) -> dict:
    """经真实 API 建章节。"""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={"title": title, "content": content},
    )
    assert resp.status_code == 201
    return resp.json()


async def _outline_chapter_id(client: AsyncClient, project_id: int, outline_id: str):
    """读回该大纲的 chapter_id（GET 列表 + 定位）。"""
    resp = await client.get(f"/api/v1/projects/{project_id}/outlines")
    assert resp.status_code == 200
    items = resp.json()["items"]
    matched = [o for o in items if o["id"] == outline_id]
    assert len(matched) == 1
    return matched[0]["chapter_id"]


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_patch_content_autolinks_matching_chapter_outline(
    client, sample_project
) -> None:
    """【R】PATCH 正文 → 同名唯一章级大纲 chapter_id 回填为本章 id。"""
    pid = sample_project.id
    outline = await _create_outline(client, pid, TITLE)
    chapter = await _create_chapter(client, pid, TITLE)

    resp = await client.patch(
        f"/api/v1/chapters/{chapter['id']}", json={"content": CONTENT}
    )
    assert resp.status_code == 200

    assert await _outline_chapter_id(client, pid, outline["id"]) == chapter["id"]


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_repeat_patch_keeps_single_binding(client, sample_project) -> None:
    """【R】重复 PATCH 正文 → 绑定保持为同一章（幂等）。"""
    pid = sample_project.id
    outline = await _create_outline(client, pid, TITLE)
    chapter = await _create_chapter(client, pid, TITLE)

    for content in (CONTENT, f"{CONTENT} 第二段"):
        resp = await client.patch(
            f"/api/v1/chapters/{chapter['id']}", json={"content": content}
        )
        assert resp.status_code == 200

    assert await _outline_chapter_id(client, pid, outline["id"]) == chapter["id"]


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_no_match_keeps_chapter_id_null(client, sample_project) -> None:
    """【R】章标题与大纲名不相等 → chapter_id 保持 null（保留手动兜底）。"""
    pid = sample_project.id
    outline = await _create_outline(client, pid, TITLE)
    chapter = await _create_chapter(client, pid, "未匹配章")

    resp = await client.patch(
        f"/api/v1/chapters/{chapter['id']}", json={"content": CONTENT}
    )
    assert resp.status_code == 200

    assert await _outline_chapter_id(client, pid, outline["id"]) is None


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_create_with_content_autolinks(client, sample_project) -> None:
    """【R】创建章节即带正文 → 同样触发回填（正文出现的另一入口）。"""
    pid = sample_project.id
    outline = await _create_outline(client, pid, TITLE)
    chapter = await _create_chapter(client, pid, TITLE, content=CONTENT)

    assert await _outline_chapter_id(client, pid, outline["id"]) == chapter["id"]
