"""F57-S2 显式 checkpoint — INFO 数据变化契约测试（spec §4.1 语义层）。

契约来源
--------
specs/f57-logging-i18n/spec.md §4（API/服务层 INFO=写操作数据变化）+ §4.1（显式
checkpoint：create/update/delete 成功 → INFO，message_key=log.event.*）。

设计假设（GREEN 必须满足）
--------------------------
ProjectService（domain/services/project_service.py）写操作**成功**后，经 loguru
`log_structured` 发 INFO 结构化事件（repo 返回成功后打，失败/None 不打）：

1. create_project(...) 成功 → level=INFO, caller_type ∈ {"api","agent","cli"} 不强制
   （推荐 "api"），message_key == "log.event.create_project"，
   params 含 name（str），禁止含 config 里的 api_key 明文。
2. update(...) 成功（返回非 None）→ message_key == "log.event.update_project"，
   params 含 name。**update 返回 None（不存在）→ 不打 INFO 事件**。
3. soft_delete(...) 返回 True → message_key == "log.event.delete_project"；
   返回 False → 不打。

断言方式：loguru sink 捕获（record["extra"]），按 message_key 匹配。
RED 预期：checkpoint 未铺开 → 无对应记录 → 失败。
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger

from inkflow.domain.models.project import Project, ProjectConfig, ProjectUpdate
from inkflow.domain.services.project_service import ProjectService
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _restore_loguru():
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")


def _capture():
    records: list = []
    sid = logger.add(lambda m: records.append(m.record), level="DEBUG", format="{message}")
    return records, sid


def _by_key(records: list, key: str) -> list[dict]:
    return [r for r in records if r["extra"].get("message_key") == key]


def _project(**overrides: object) -> Project:
    defaults: dict[str, object] = {
        "id": PID,
        "name": "旧名字",
        "tags": [],
        "language": "zh-CN",
        "target_words": 100,
        "config": ProjectConfig(),
        "is_deleted": False,
        "created_at": TS,
        "updated_at": TS,
    }
    defaults.update(overrides)
    return Project(**defaults)


@pytest.fixture
def svc() -> ProjectService:
    service = ProjectService(db_session=MagicMock())
    repo = MagicMock(spec=SQLiteProjectRepository)
    repo.get = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda p: p)
    repo.update = AsyncMock(side_effect=lambda p: p)
    repo.soft_delete = AsyncMock(return_value=True)
    service._repo = repo
    return service


class TestProjectWriteEvents:
    async def test_create_project_emits_info_event(self, svc) -> None:
        records, sid = _capture()
        try:
            result = await svc.create_project("新项目")
        finally:
            logger.remove(sid)
        assert result.name == "新项目"
        events = _by_key(records, "log.event.create_project")
        assert events, "create_project 成功应发 INFO log.event.create_project"
        rec = events[0]
        assert rec["level"].name == "INFO"
        assert rec["extra"]["params"]["name"] == "新项目"

    async def test_update_success_emits_info_event(self, svc) -> None:
        svc._repo.get = AsyncMock(return_value=_project())
        records, sid = _capture()
        try:
            result = await svc.update(PID, ProjectUpdate(name="新名字"))
        finally:
            logger.remove(sid)
        assert result is not None and result.name == "新名字"
        events = _by_key(records, "log.event.update_project")
        assert events, "update 成功应发 INFO log.event.update_project"
        assert events[0]["level"].name == "INFO"
        assert events[0]["extra"]["params"]["name"] == "新名字"

    async def test_update_missing_project_no_info_event(self, svc) -> None:
        """update 返回 None（不存在）→ 不打数据变化 INFO。"""
        records, sid = _capture()
        try:
            result = await svc.update(PID, ProjectUpdate(name="x"))
        finally:
            logger.remove(sid)
        assert result is None
        assert not _by_key(records, "log.event.update_project")

    async def test_soft_delete_true_emits_info_event(self, svc) -> None:
        records, sid = _capture()
        try:
            ok = await svc.soft_delete(PID)
        finally:
            logger.remove(sid)
        assert ok is True
        events = _by_key(records, "log.event.delete_project")
        assert events, "soft_delete 成功应发 INFO log.event.delete_project"
        assert events[0]["level"].name == "INFO"

    async def test_soft_delete_false_no_info_event(self, svc) -> None:
        svc._repo.soft_delete = AsyncMock(return_value=False)
        records, sid = _capture()
        try:
            ok = await svc.soft_delete(PID)
        finally:
            logger.remove(sid)
        assert ok is False
        assert not _by_key(records, "log.event.delete_project")
