"""#999 章节标题双编号归一化 — 批量端点 HTTP 契约（RED-2 批）。

对应契约定稿: .hermes/plans/999-contract.md §2/§3/§4。

范围（仅异步 API 契约，实现不存在 → 新用例预期全 FAIL/ERROR）:
- POST /api/v1/projects/{project_id}/chapters/normalize-titles:
  200 计数 + 落库回读 / 幂等（第二次计数 0）/ config 持久化回读 / arabic 反向 /
  非法/unset format 422 / 项目不存在 404 / outline 同步 + 撞名跳过（uq_outlines_active_name）。
- ChapterCreate DTO 经 API 归一：双前缀去重落库（§2 "fmt=None" 去重不改格式）。

形态镜像 tests/api/test_chapter_api.py（ASGITransport + app.dependency_overrides
替换 get_db 同库访问；sample_project/db_session 来自顶层 tests/conftest.py 共享 fixture）。

铁律:
- pytest fixture 不跨模块注入：本文件本地镜像构造 overrides/client fixture
  （import 只取常量与纯函数；不 import 其它测试文件的 fixture）。
- 真实落表 seed 用 sample_project.id（project 表 id=INTEGER）派生；
  outline 用 OutlineORM 直插（level=chapter, volume_id=None——uq_outlines_volume_id
  唯一索引下多行 NULL 合法，一卷一纲互不冲突）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.app import app
from inkflow.api.deps import get_db
from inkflow.infrastructure.database.models.outline import OutlineORM

# 合法 UUID 字符串但不存在的项目（用于 404 路径；detail 断言区分路由层 "Not Found"）
NONEXISTENT_PROJECT = "3f2e1d4a-0000-4000-8000-0000deadbeef01"


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """本地镜像的 ASGI 客户端：把 get_db 覆盖为测试 db_session（同库访问）。"""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _create_chapters(client: AsyncClient, project_id: int, titles: list[str]) -> None:
    """经真实 API 种章节行（title 原样落库——DTO 尚未归一时为 RED 前状态）。"""
    for title in titles:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/chapters", json={"title": title}
        )
        assert resp.status_code == 201


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_titles_chapters_chinese(client, sample_project):
    """chinese 归一：'第1章 起点'→'第一章 起点'（计数 1）；其余不动；GET 回读验证。"""
    pid = sample_project.id
    await _create_chapters(client, pid, ["第1章 起点", "第三章 转折", "一叶落"])

    resp = await client.post(
        f"/api/v1/projects/{pid}/chapters/normalize-titles",
        json={"format": "chinese"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "chinese"
    assert body["chapters_replaced"] == 1
    assert body["outlines_replaced"] == 0

    lst = (await client.get(f"/api/v1/projects/{pid}/chapters")).json()
    titles = {c["title"] for c in lst["items"]}
    assert titles == {"第一章 起点", "第三章 转折", "一叶落"}


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_titles_idempotent(client, sample_project):
    """同 fmt 第二次调用 → chapters_replaced==0（幂等）。"""
    pid = sample_project.id
    await _create_chapters(client, pid, ["第1章 起点"])

    first = await client.post(
        f"/api/v1/projects/{pid}/chapters/normalize-titles",
        json={"format": "chinese"},
    )
    assert first.status_code == 200
    assert first.json()["chapters_replaced"] == 1

    second = await client.post(
        f"/api/v1/projects/{pid}/chapters/normalize-titles",
        json={"format": "chinese"},
    )
    assert second.status_code == 200
    assert second.json()["chapters_replaced"] == 0


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_titles_persists_config(client, sample_project):
    """normalize 后 GET /projects/{pid} → config.chapter_title_format=='chinese'。"""
    pid = sample_project.id
    await _create_chapters(client, pid, ["第1章 起点"])

    resp = await client.post(
        f"/api/v1/projects/{pid}/chapters/normalize-titles",
        json={"format": "chinese"},
    )
    assert resp.status_code == 200

    proj = (await client.get(f"/api/v1/projects/{pid}")).json()
    assert proj["config"]["chapter_title_format"] == "chinese"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_titles_arabic(client, sample_project):
    """arabic 反向：'第三章 转折'→'第3章 转折' 计数 1；'第1章 起点' 保持原样。"""
    pid = sample_project.id
    await _create_chapters(client, pid, ["第1章 起点", "第三章 转折", "一叶落"])

    resp = await client.post(
        f"/api/v1/projects/{pid}/chapters/normalize-titles",
        json={"format": "arabic"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "arabic"
    assert body["chapters_replaced"] == 1

    lst = (await client.get(f"/api/v1/projects/{pid}/chapters")).json()
    titles = {c["title"] for c in lst["items"]}
    assert titles == {"第1章 起点", "第3章 转折", "一叶落"}


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_titles_invalid_format_422(client, sample_project):
    """format='weird' → 422。"""
    pid = sample_project.id
    resp = await client.post(
        f"/api/v1/projects/{pid}/chapters/normalize-titles",
        json={"format": "weird"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_titles_missing_format_422(client, sample_project):
    """缺 format → 422。"""
    pid = sample_project.id
    resp = await client.post(
        f"/api/v1/projects/{pid}/chapters/normalize-titles", json={}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_titles_project_not_found_404(client, sample_project):
    """项目不存在 → 404（detail 契约文案 '项目不存在'，与路由层 'Not Found' 区分）。"""
    resp = await client.post(
        f"/api/v1/projects/{NONEXISTENT_PROJECT}/chapters/normalize-titles",
        json={"format": "chinese"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "项目不存在"


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_titles_outline_sync(client, sample_project, db_session):
    """chapter 级大纲随归一：'第5章 风起'→'第五章 风起'、'第100章 终'→'第一百章 终'，
    outlines_replaced==2；GET /outlines 回读验证。

    注: 契约 §4 仅统计「归一后不同」的条目。契约定稿示例 '第一百章 终' 本身已是中文序号，
    chinese 归一后不变、不被计数；为使示例满足 count==2，第二例改用 '第100章 终'
    （chinese 下变化）。见交付报告「契约偏离/歧义」。
    """
    pid = sample_project.id
    db_session.add(
        OutlineORM(project_id=pid, name="第5章 风起", level="chapter", volume_id=None)
    )
    db_session.add(
        OutlineORM(project_id=pid, name="第100章 终", level="chapter", volume_id=None)
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/projects/{pid}/chapters/normalize-titles",
        json={"format": "chinese"},
    )
    assert resp.status_code == 200
    assert resp.json()["outlines_replaced"] == 2

    outlines = (await client.get(f"/api/v1/projects/{pid}/outlines")).json()["items"]
    names = {o["name"] for o in outlines}
    assert names == {"第五章 风起", "第一百章 终"}


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_titles_outline_dup_name_skipped(
    client, sample_project, db_session
):
    """归一后与既有活动大纲重名（uq_outlines_active_name）→ 跳过该条不计入 replaced，
    库中无 IntegrityError。

    最小例:种 '第1章 a' 与 '第一章 a' —— chinese 归一后 '第1章 a'→'第一章 a' 撞已有
    '第一章 a' → 跳过；'第一章 a' 本身不变。outlines_replaced==0，两条原样留存。
    """
    pid = sample_project.id
    db_session.add(
        OutlineORM(project_id=pid, name="第1章 a", level="chapter", volume_id=None)
    )
    db_session.add(
        OutlineORM(project_id=pid, name="第一章 a", level="chapter", volume_id=None)
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/projects/{pid}/chapters/normalize-titles",
        json={"format": "chinese"},
    )
    assert resp.status_code == 200
    assert resp.json()["outlines_replaced"] == 0

    outlines = (await client.get(f"/api/v1/projects/{pid}/outlines")).json()["items"]
    names = {o["name"] for o in outlines}
    assert "第1章 a" in names  # 被跳过的条目保持原样
    assert "第一章 a" in names


@pytest.mark.asyncio
@pytest.mark.chapter
async def test_normalize_titles_dto_dedupe(client, sample_project):
    """ChapterCreate 经 API 归一：双前缀 '第2章 第二章 风雨' → 落库 '第2章 风雨'
    （§2 fmt=None 去重 + 分隔归一，不改序号格式；'第2章 第二章' 取第一个前缀序号 2）。"""
    pid = sample_project.id
    resp = await client.post(
        f"/api/v1/projects/{pid}/chapters",
        json={"title": "第2章 第二章 风雨"},
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["title"] == "第2章 风雨"
