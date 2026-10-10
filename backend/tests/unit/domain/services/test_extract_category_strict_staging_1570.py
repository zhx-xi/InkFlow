"""#1570 两段式暂存（stage）路径同样受类别严格校验约束 —— 不能只在物化时拦.

覆盖：
- ``ExtractionService.extract(type=setting, stage=True)`` 遇未注册类别 → **在落暂存之前**
  抛 ``WorldCategoryNotRegisteredError``（列出缺失分类名）；
- 暂存区零行（``staging_repo.add_many`` 未被调用）→ 无物化可确认，故
  ``confirm_staged`` 不可能把无类别条目写进正式表（物化侧无后门）。

用**真实** ``WorldService`` + **真实** ``WorldExtractor``（只替 LLM / 模板 / 仓储），
确保「stage ⇒ 管线 dry_run=True ⇒ 类别校验生效」这条链真的成立，而不是靠 mock 假设。

依据: specs/f14-extraction/spec.md §5.9 + §5.8.1（#1570 修订）。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.extraction import ExtractionRequest, ExtractionType
from inkflow.domain.models.world import WorldCategory
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.domain.ports.prompt_template import PromptTemplate, RenderedPrompt
from inkflow.domain.ports.world_errors import WorldCategoryNotRegisteredError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._world_extractor import WorldExtractor
from inkflow.domain.services.extraction_service import ExtractionService
from inkflow.domain.services.world_service import WorldService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 10, tzinfo=UTC)
MODEL = "openai/gpt-4o"


def _category(name: str) -> WorldCategory:
    return WorldCategory(id=uuid.uuid4(), project_id=PID, name=name, created_at=NOW, updated_at=NOW)


def _project() -> MagicMock:
    project = MagicMock()
    project.config.model = MODEL
    return project


def _llm(payload_category: str) -> MagicMock:
    llm = MagicMock()
    llm.chat = AsyncMock(
        return_value=ChatResponse(
            content=json.dumps(
                {
                    "world_settings": [
                        {"name": "北方大陆", "category": payload_category, "content": "c"}
                    ]
                },
                ensure_ascii=False,
            ),
            model=MODEL,
        )
    )
    return llm


def _prompt_manager() -> MagicMock:
    pm = MagicMock()
    pm.load = MagicMock(
        return_value=PromptTemplate(
            name="world_extract", description="d", system_prompt="s", human_prompt="h"
        )
    )
    pm.render = MagicMock(
        return_value=RenderedPrompt(messages=[{"role": "user", "content": "t"}], token_estimate=1)
    )
    return pm


def _service(*, registered: list[str], payload_category: str) -> ExtractionService:
    """装配真实 WorldService/WorldExtractor 的 ExtractionService（仅外部依赖替身）。"""
    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=_project())
    run_repo = MagicMock()
    run_repo.get = AsyncMock(return_value=None)
    run_repo.upsert = AsyncMock()

    world_repo = MagicMock(spec=WorldRepositoryProtocol)
    world_repo.get_by_name = AsyncMock(return_value=None)
    world_repo.list = AsyncMock(return_value=([], 0))
    world_repo.list_all_active = AsyncMock(return_value=[])
    world_repo.list_world_categories = AsyncMock(
        return_value=[(_category(n), 0) for n in registered]
    )
    world_repo.add = AsyncMock(side_effect=lambda s: s)
    world_repo.update = AsyncMock(side_effect=lambda s: s)

    extractor = WorldExtractor(
        llm_client=_llm(payload_category),
        prompt_manager=_prompt_manager(),
        repository=world_repo,
    )
    world_service = WorldService(
        repository=world_repo, extractor=extractor, project_repo=project_repo
    )

    staging_repo = MagicMock()
    staging_repo.add_many = AsyncMock(return_value=1)
    staging_repo.list_by_batch = AsyncMock(return_value=[])
    staging_repo.delete_by_batch = AsyncMock(return_value=0)

    return ExtractionService(
        project_repo=project_repo,
        chapter_repo=MagicMock(),
        run_repo=run_repo,
        character_service=MagicMock(),
        world_service=world_service,
        outline_service=MagicMock(),
        timeline_service=MagicMock(),
        foreshadowing_extractor=MagicMock(),
        timeline_extractor=MagicMock(),
        style_service=MagicMock(),
        world_repo=world_repo,
        staging_repo=staging_repo,
    )


def _staging_repo(svc: ExtractionService) -> Any:
    """取门面装配的暂存仓储替身（私有属性由 `__init__` 装配、混入类不声明）."""
    return svc._staging_repo


def _staging_add_calls(svc: ExtractionService) -> int:
    return _staging_repo(svc).add_many.await_count


class TestStagePathCategoryStrict:
    """stage=true 提取遇未注册类别 → 拒绝且暂存区零行。"""

    async def test_stage_rejects_unregistered_category_before_staging(self) -> None:
        svc = _service(registered=["背景设定"], payload_category="地理")

        with pytest.raises(WorldCategoryNotRegisteredError) as excinfo:
            await svc.extract(
                ExtractionRequest(project_id=PID, type=ExtractionType.SETTING, text="t", stage=True)
            )

        assert excinfo.value.missing == ["地理"]
        # 拒绝发生在落暂存之前 → 暂存区零行（物化侧无物可写）
        assert _staging_add_calls(svc) == 0
        # 正式表同样零写入
        world_repo = svc._world_repo
        assert world_repo.add.await_count == 0

    async def test_stage_succeeds_when_category_registered(self) -> None:
        """建类后重试（stage）→ 成功落暂存区，类别正确。"""
        svc = _service(registered=["地理"], payload_category="地理")

        result = await svc.extract(
            ExtractionRequest(project_id=PID, type=ExtractionType.SETTING, text="t", stage=True)
        )

        assert result.batch_id and result.batch_id.startswith("ext-")
        assert _staging_add_calls(svc) == 1
        entries = _staging_repo(svc).add_many.await_args.args[-1]
        assert len(entries) == 1
        assert entries[0].payload["category"] == "地理"
