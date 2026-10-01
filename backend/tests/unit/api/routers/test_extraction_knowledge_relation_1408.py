"""#1408 契约（HTTP 边界）：POST /api/v1/extract `type=knowledge_relation` 不再 422。

本文件用**真实 ExtractionService**（依赖全 Mock）走 TestClient，锁死 issue #1408 的原始
症状：「CLI 收 7 种值，内核必定 422 不支持的提取类型」。

- 无源参数 → 200 + `type=knowledge_relation`（分发到 F48 RelationExtractionService）
- 带 `chapter_ids`（issue 里的原始命令形态）→ 422 但**换成语义正确的输入约束消息**
  （项目级提取不接受源参数），不再是「不支持的提取类型」——该文案是 #1408 的症状指纹。

依据: specs/f14-extraction/spec.md §3.2/§6.4/§7 + issue #1408。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.extraction import (
    ExtractionResult,
    ExtractionStatus,
    ExtractionType,
)
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.services.extraction_service import ExtractionService

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CH1 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000011")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _project() -> Project:
    """构造测试项目（项目级提取只要求项目存在）。"""
    return Project(
        id=PID,
        name="测试项目",
        config=ProjectConfig(model=None, extra={}),
        created_at=TS,
        updated_at=TS,
    )


def _relation_result() -> ExtractionResult:
    """构造 F48 RelationExtractionService 返回信封。"""
    return ExtractionResult(
        type=ExtractionType.KNOWLEDGE_RELATION,
        status=ExtractionStatus.SUCCESS,
        created=5,
        updated=0,
        warnings=[],
        model=None,
    )


def _service(*, relation: Any) -> ExtractionService:
    """装配真实门面（依赖全 Mock，不触发 I/O；与 domain/services 契约测试同构）。"""
    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=_project())
    chapter_repo = MagicMock()
    chapter_repo.get_chapter = AsyncMock(return_value=None)
    run_repo = MagicMock()
    run_repo.get = AsyncMock(return_value=None)
    run_repo.upsert = AsyncMock(side_effect=lambda r: r)
    return ExtractionService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        run_repo=run_repo,
        character_service=MagicMock(),
        world_service=MagicMock(),
        outline_service=MagicMock(),
        timeline_service=MagicMock(),
        foreshadowing_extractor=MagicMock(),
        timeline_extractor=MagicMock(),
        style_service=MagicMock(),
        character_repo=MagicMock(),
        world_repo=MagicMock(),
        timeline_repo=MagicMock(),
        foreshadowing_repo=MagicMock(),
        vector_store=MagicMock(),
        relation_extraction_service=relation,
    )


def test_extract_api_knowledge_relation_returns_200() -> None:
    """POST /extract {type: knowledge_relation} → 200（issue #1408 的 422 症状消失）。"""
    relation = MagicMock()
    relation.extract_for_project = AsyncMock(return_value=_relation_result())
    svc = _service(relation=relation)

    with patch(
        "inkflow.api.routers.extractions.get_extraction_service",
        AsyncMock(return_value=svc),
    ):
        resp = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "knowledge_relation"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "knowledge_relation"
    assert body["status"] == "success"
    assert body["created"] == 5
    assert body["model"] is None
    relation.extract_for_project.assert_awaited_once_with(PID, method="rule")


def test_extract_api_knowledge_relation_source_args_are_specific_422() -> None:
    """带 chapter_ids（issue 原始命令形态）→ 422 但文案换成输入约束，不再是「不支持的提取类型」。"""
    relation = MagicMock()
    relation.extract_for_project = AsyncMock()
    svc = _service(relation=relation)

    with patch(
        "inkflow.api.routers.extractions.get_extraction_service",
        AsyncMock(return_value=svc),
    ):
        resp = client.post(
            "/api/v1/extract",
            json={
                "project_id": str(PID),
                "type": "knowledge_relation",
                "chapter_ids": [str(CH1)],
            },
        )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "knowledge_relation" in detail
    assert "不支持的提取类型" not in detail, "不应再命中 #1408 的症状文案"
    relation.extract_for_project.assert_not_awaited()
