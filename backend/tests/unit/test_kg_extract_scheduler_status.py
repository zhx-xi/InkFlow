"""F48 知识图谱定时调度器 — is_running/last_run 表面 + 边界分支契约测试（#479 覆盖率收尾）。

补测 G2 回补的 status 端点支撑属性（is_running/last_run spec §5.5.6）与
startup 补跑的 naive run_at（tzinfo None）分支、start-after-stop（task done）分支，
这些不在 G1 RED 批覆盖范围内。
依据: specs/f48-knowledge-graph/spec.md §5.5.3/§5.5.6。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from inkflow.domain.models.extraction import ExtractionResult, ExtractionStatus, ExtractionType
from inkflow.infrastructure.scheduler.kg_extract_scheduler import KnowledgeExtractScheduler

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


def _settings(**overrides) -> SimpleNamespace:
    base = {
        "kg_extract_enabled": False,
        "kg_extract_interval_hours": 24,
        "kg_extract_method": "rule",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _project(pid: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=pid, name="项目", is_deleted=False)


def _result(*, created: int = 1) -> ExtractionResult:
    return ExtractionResult(
        type=ExtractionType.CHARACTER, status=ExtractionStatus.SUCCESS, created=created
    )


def _make_scheduler(**overrides) -> KnowledgeExtractScheduler:
    settings_service = AsyncMock()
    settings_service.get_settings.return_value = _settings()
    project_repository = AsyncMock()
    project_repository.list_all.return_value = []
    relation_extraction_service = AsyncMock()
    relation_extraction_service.extract_for_project.return_value = _result()
    kwargs = {
        "settings_service": settings_service,
        "project_repository": project_repository,
        "relation_extraction_service": relation_extraction_service,
        "extraction_run_repo": None,
    }
    kwargs.update(overrides)
    return KnowledgeExtractScheduler(**kwargs)


class TestStatusSurface:
    """is_running / last_run 支撑属性（spec §5.5.6）。"""

    async def test_is_running_property_readable(self):
        sched = _make_scheduler()
        assert sched.is_running is False

    async def test_last_run_property_starts_none(self):
        sched = _make_scheduler()
        assert sched.last_run is None

    async def test_run_cycle_sets_last_run_when_items(self):
        """enabled + 有项目 → run_cycle 产出 items → last_run 维护摘要。"""
        settings_service = AsyncMock()
        settings_service.get_settings.return_value = _settings(kg_extract_enabled=True)
        project_repository = AsyncMock()
        project_repository.list_all.return_value = [_project(PID)]
        relation_extraction_service = AsyncMock()
        relation_extraction_service.extract_for_project.return_value = _result(created=2)
        sched = _make_scheduler(
            settings_service=settings_service,
            project_repository=project_repository,
            relation_extraction_service=relation_extraction_service,
        )

        items = await sched.run_cycle()

        assert len(items) == 1
        assert sched.last_run is not None
        assert sched.last_run["status"] == "success"
        assert sched.last_run["created"] == 2
        assert "run_at" in sched.last_run
        assert sched.is_running is False  # finally 释放

    async def test_run_cycle_disabled_returns_none_last_run(self):
        """disabled → 返回 []，last_run 保持 None（items 空不维护）。"""
        sched = _make_scheduler()
        items = await sched.run_cycle()
        assert items == []
        assert sched.last_run is None

    async def test_run_cycle_enabled_no_projects_keeps_last_run_none(self):
        """enabled 但项目表空 → items 空 → 走 L115 分支，last_run 维持 None。"""
        settings_service = AsyncMock()
        settings_service.get_settings.return_value = _settings(kg_extract_enabled=True)
        project_repository = AsyncMock()
        project_repository.list_all.return_value = []
        sched = _make_scheduler(
            settings_service=settings_service, project_repository=project_repository
        )

        items = await sched.run_cycle()

        assert items == []
        assert sched.last_run is None


class TestStartupCatchupBoundary:
    """startup 补跑的边界分支。"""

    async def test_naive_run_at_catches_up(self):
        """最近 run_at 为 naive datetime（tzinfo None）→ replace(UTC) 后判定补跑。"""
        run_repo = AsyncMock()
        naive = SimpleNamespace(
            run_at=datetime(2026, 8, 1, 10, 0, 0) - timedelta(hours=48),  # naive，无 tzinfo
            type="knowledge_relation",
        )
        run_repo.list.return_value = ([naive], 1)
        sched = _make_scheduler(extraction_run_repo=run_repo)
        sched.run_cycle = AsyncMock(return_value=[])
        await sched.start()
        for _ in range(5):
            await asyncio.sleep(0)
        await sched.stop()
        run_repo.list.assert_awaited()
        sched.run_cycle.assert_awaited()  # naive 距今 48h ≥ interval 24h → 补跑

    async def test_start_after_stop_respawns_task(self):
        """stop 后再次 start → _task.done() 分支（spawn 新 loop task，不抛错）。"""
        sched = _make_scheduler()
        sched.run_cycle = AsyncMock(return_value=[])
        await sched.start()
        for _ in range(3):
            await asyncio.sleep(0)
        await sched.stop()
        # 再次 start → 触发 _task.done() 分支
        await sched.start()
        for _ in range(3):
            await asyncio.sleep(0)
        await sched.stop()
        sched.run_cycle.assert_awaited()
