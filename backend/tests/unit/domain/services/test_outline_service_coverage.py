"""OutlineService 层级校验分支覆盖（#687 coverage-gap 补测）。

直调 _validate_outline_hierarchy 覆盖 chapter_repo None 跳过 / 章同项目匹配 /
volume 分支 chapter_repo None 且无已有卷纲等分支弧（只依赖注入 repos，无副作用）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.services.outline_service import OutlineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


def _svc(repo=None, chapter_repo=None) -> OutlineService:
    """最小构造 OutlineService：repository/generator/project_repo 全 mock。"""
    return OutlineService(
        repository=repo or AsyncMock(),
        generator=AsyncMock(),
        project_repo=AsyncMock(),
        chapter_repo=chapter_repo,
    )


@pytest.mark.asyncio
async def test_validate_chapter_repo_none_skips_check():
    """覆盖 L178 br=[182]：chapter_repo None 跳过章校验（向后兼容）。"""
    svc = _svc(chapter_repo=None)
    await svc._validate_outline_hierarchy(PID, "chapter", None, uuid.uuid4())


@pytest.mark.asyncio
async def test_validate_chapter_matches_project():
    """覆盖 L180 br=[182]：章存在且同项目 -> 校验通过。"""
    cr = AsyncMock()
    cr.get_chapter.return_value = SimpleNamespace(project_id=PID)
    svc = _svc(chapter_repo=cr)
    await svc._validate_outline_hierarchy(PID, "chapter", None, uuid.uuid4())
    cr.get_chapter.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_volume_repo_none_and_no_existing():
    """覆盖 L185 br=[189] + L192 br=[exit]：volume 分支 chapter_repo None 且无已有卷纲。"""
    repo = AsyncMock()
    repo.get_outline_by_volume.return_value = None
    svc = _svc(repo=repo, chapter_repo=None)
    await svc._validate_outline_hierarchy(PID, "volume", None, None, volume_id=uuid.uuid4())
    repo.get_outline_by_volume.assert_awaited_once()
