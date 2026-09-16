"""DraftService 数据面变更事件负例契约（#1090 批次 B；spec §15.6.2/§15.6.4）。

契约来源：W3C 设计裁定表 §2.9（父侧单一真相源）。
**draft 域零接入**：create / update / confirm / reject / replace_content 任一调用 →
`recorded_events == []`（§15.6.2 暂不推送；draft 页不订阅数据面变更）。
本文件为**纯负例守卫**——RED 阶段全部 PASS 属预期（实现本就零发布）；
GREEN 阶段若被误接入发布点，本文件即转红（防过度实现）。

依赖全 Mock 注入（镜像 test_draft_service_update.py 的 fixture 形态）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.domain.services.draft_service import DraftService

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
DRAFT_ID = "draft-0001"


def _draft(*, content: str = "旧版内容", status: DraftStatus = DraftStatus.DRAFT) -> Draft:
    """构造 Draft 领域实例。"""
    return Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        agent_run_id="run-1",
        content=content,
        status=status,
        summary="",
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
        confirmed_at=None,
    )


@pytest.fixture
def deps() -> dict:
    """草稿依赖字典 — repo 全显式默认值（裸 AsyncMock 陷阱防护，规则 1m）。"""
    draft_repo = AsyncMock()
    draft_repo.create.return_value = _draft()
    draft_repo.get.return_value = _draft()
    draft_repo.update_content.return_value = _draft(content="新版内容更长")
    draft_repo.update_status.return_value = _draft(status=DraftStatus.CONFIRMED)
    return {
        "draft_repo": draft_repo,
        "chapter_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "memory_service": AsyncMock(),
    }


@pytest.fixture
def service(deps: dict) -> DraftService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return DraftService(
        draft_repo=deps["draft_repo"],
        chapter_service=deps["chapter_service"],
        audit_service=deps["audit_service"],
        memory_service=deps["memory_service"],
    )


class TestDraftDomainPublishesNothing:
    """draft 域零发布守卫（§15.6.2）。"""

    async def test_create_publishes_nothing(
        self, service: DraftService, deps: dict, recorded_events
    ) -> None:
        """create 落库草稿 → 不发数据面变更事件。"""
        created = await service.create(project_id=PROJECT_ID, content="草稿正文")

        assert created is not None
        assert recorded_events == []

    async def test_update_publishes_nothing(
        self, service: DraftService, deps: dict, recorded_events
    ) -> None:
        """update 编辑草稿正文 → 不发数据面变更事件。"""
        updated = await service.update(DRAFT_ID, "新版内容更长")

        assert updated is not None
        assert recorded_events == []

    async def test_confirm_publishes_nothing(
        self, service: DraftService, deps: dict, recorded_events
    ) -> None:
        """confirm 确认落章 → 不发数据面变更事件。"""
        confirmed = await service.confirm(DRAFT_ID)

        assert confirmed is not None
        assert recorded_events == []

    async def test_reject_publishes_nothing(
        self, service: DraftService, deps: dict, recorded_events
    ) -> None:
        """reject 拒绝草稿 → 不发数据面变更事件。"""
        rejected = await service.reject(DRAFT_ID)

        assert rejected is not None
        assert recorded_events == []

    async def test_replace_content_publishes_nothing(
        self, service: DraftService, deps: dict, recorded_events
    ) -> None:
        """agent 覆盖草稿正文（#997）→ 不发数据面变更事件。"""
        replaced = await service.replace_content(DRAFT_ID, "覆盖后的正文")

        assert replaced is not None
        assert recorded_events == []
