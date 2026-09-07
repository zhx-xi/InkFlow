"""#988 响应 DTO RED 契约 — drafts list/confirm 暴露 source_outline_id（mock 轨）.

被测: api/routers/agent_runs.py 草稿路由响应序列化。ConfirmRequest body →
svc.confirm kwargs 透传已由 tests/api/test_f27_agentic_api.py 的 #976 用例锁定
（当前即 RED→GREEN 愈）；本文件补「响应 DTO」增量面（fixture 本地自含镜像同文件，
overrides 不跨模块 import——pytest fixture 模块作用域）:

- list_drafts → items 来自 Draft.model_dump(mode="json")：GREEN 后 Draft 增
  source_outline_id 字段 → 响应 items 含该键（当前模型无字段 → KeyError RED）
- confirm_draft → 响应回显 source_outline_id（确认方核对回填来源）：当前响应
  字典无该键 → KeyError（RED）
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.draft import Draft, DraftStatus

pytestmark = pytest.mark.asyncio

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
DRAFT_ID = "draft-0001"
OUTLINE_ID = uuid.UUID(int=51)


@pytest.fixture
def overrides():
    """替换 deps 草稿服务依赖 → Mock（镜像 test_f27_agentic_api.overrides）。"""

    from inkflow.api.app import app
    from inkflow.api.deps import get_agent_run_repo, get_draft_service

    draft_svc = MagicMock()
    draft_svc.list = AsyncMock(return_value=([], 0))
    draft_svc.confirm = AsyncMock(return_value=None)
    draft_svc.reject = AsyncMock(return_value=None)

    run_repo = MagicMock()
    run_repo.get = AsyncMock(return_value=None)
    run_repo.list = AsyncMock(return_value=([], 0))

    app.dependency_overrides[get_draft_service] = lambda: draft_svc
    app.dependency_overrides[get_agent_run_repo] = lambda: run_repo
    yield {"draft": draft_svc}
    app.dependency_overrides.clear()


@pytest.fixture
def client(overrides):  # overrides 注入依赖替身后构造客户端（fixture 依赖序）
    from httpx import ASGITransport, AsyncClient

    from inkflow.api.app import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _draft_model(**overrides_kw) -> Draft:
    kwargs: dict = dict(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="正文。",
        status=DraftStatus.DRAFT,
        created_at="2026-08-10T12:00:00",
        confirmed_at=None,
    )
    kwargs.update(overrides_kw)
    return Draft(**kwargs)


async def test_drafts_list_exposes_source_outline_id(client, overrides):
    """【R】GET /agent/drafts → items 含 source_outline_id 键（Draft 模型暴露）.

    当前 Draft 无该字段 → extra=ignore 丢弃构造键 → 响应 items 无该键 → KeyError。
    """
    overrides["draft"].list.return_value = ([_draft_model(source_outline_id=OUTLINE_ID)], 1)

    async with client as c:
        resp = await c.get("/api/v1/agent/drafts", params={"project_id": str(PROJECT_ID)})

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["source_outline_id"] == str(OUTLINE_ID)


async def test_drafts_list_source_outline_id_none_serialized(client, overrides):
    """【R】未记录来源的草稿 → 响应含 source_outline_id 键且为 null（DTO 恒暴露）.

    当前模型无字段 → dump 无该键 → KeyError（RED）。
    """
    overrides["draft"].list.return_value = ([_draft_model(id="draft-0002", chapter_id=None)], 1)

    async with client as c:
        resp = await c.get("/api/v1/agent/drafts", params={"project_id": str(PROJECT_ID)})

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert "source_outline_id" in item
    assert item["source_outline_id"] is None


async def test_drafts_confirm_response_echoes_source_outline_id(client, overrides):
    """【R】POST confirm 成功 → 响应回显 source_outline_id（确认方核对回填来源）.

    当前 confirm 响应字典无该键 → KeyError（RED）。GREEN: 响应加
    "source_outline_id": str(draft.source_outline_id) if draft.source_outline_id else None。
    """
    confirmed = _draft_model(
        status=DraftStatus.CONFIRMED,
        confirmed_at="2026-08-10T12:05:00",
        source_outline_id=OUTLINE_ID,
    )
    overrides["draft"].confirm.return_value = confirmed

    async with client as c:
        resp = await c.post(
            f"/api/v1/agent/drafts/{DRAFT_ID}/confirm",
            json={"source_outline_id": str(OUTLINE_ID)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["source_outline_id"] == str(OUTLINE_ID)
    # 既有键零回归守护
    assert data["status"] == "confirmed"
    assert data["chapter_id"] == str(CHAPTER_ID)
