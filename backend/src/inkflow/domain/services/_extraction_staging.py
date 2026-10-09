"""F14 统一提取服务的两段式暂存（spec §5.9，#1545）— 从门面拆分（#1545）.

门面 `extraction_service.py` 的「两段式暂存」横切能力（#1545 §5.9）拆分为本模块，
按 #307（`_extraction_rag.py`）先例，行为零变化，含两部分:

1. `_staged_entries`: 提取结果 detail 的 created / updated 条目 → `StagedEntry`
   列表（`extract(stage=True)` 落暂存区时使用，确定性、可单测）。
2. `_ExtractionStagingMixin`: `_staging()` 仓储取用 + `confirm_staged` 物化 /
   `cancel_staged` 清空 / `list_staged` 读取。

由 `ExtractionService` 继承（`class ExtractionService(_ExtractionRAGMixin,
_ExtractionStagingMixin)`）；共享属性（`_staging_repo` / `_project_repo` /
`_character_repo` / `_world_repo`）由门面 `__init__` 装配，混入类内以类型抑制声明
（属性由 Service 提供）。

依据: specs/f14-extraction/spec.md §5.9。
"""

from __future__ import annotations

import uuid
from typing import Any

from inkflow.domain.models.character import Character
from inkflow.domain.models.extraction import (
    CancelStagedResult,
    ConfirmStagedResult,
    ExtractionType,
    StagedEntry,
    StagedListResult,
)
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ExtractionRunError
from inkflow.domain.ports.extraction_staging_repository import (
    ExtractionStagingRepositoryProtocol,
)


def _staged_entries(type_: ExtractionType, detail: dict[str, Any]) -> list[StagedEntry]:
    """detail 的 created / updated 条目 → 暂存条目（#1545 §5.9）."""
    entity_type = "character" if type_ is ExtractionType.CHARACTER else "world_setting"
    keys = (("create", "created"), ("update", "updated"))
    return [
        StagedEntry(entity_type=entity_type, action=action, name=p.get("name", ""), payload=p)
        for action, key in keys
        for p in detail.get(key, [])
    ]


class _ExtractionStagingMixin:
    """两段式暂存编排（spec §5.9，#1545）— confirm 物化 / cancel 清空 / list 读取.

    由 `ExtractionService` 继承（#1545 拆分）；共享属性由门面 `__init__` 装配，
    混入类不持有状态（鸭子类型访问，其内以类型抑制声明）。
    """

    def _staging(self) -> ExtractionStagingRepositoryProtocol:
        """暂存仓储（DI 由 deps.py 装配；未装配 → 500 防御，§5.9）."""
        if self._staging_repo is None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            raise ExtractionRunError("暂存仓储未装配")
        return self._staging_repo  # type: ignore[attr-defined, no-any-return]  # 混入类：属性由 Service 提供，仓储协议由 Duck typing 满足

    async def confirm_staged(self, project_id: uuid.UUID, batch_id: str) -> ConfirmStagedResult:
        """确认暂存批次（§5.9）：逐行按 action 走既有仓储物化，随后清空本批暂存."""
        if await self._project_repo.get(project_id) is None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            raise ProjectNotFoundError()
        character_repo = self._character_repo  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
        world_repo = self._world_repo  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
        if character_repo is None or world_repo is None:  # pragma: no cover - DI 恒装配
            raise ExtractionRunError("档案仓储未装配，无法确认暂存")
        created = updated = 0
        for row in await self._staging().list_by_batch(project_id, batch_id):
            if row.entity_type == "character":
                character = Character.model_validate(row.payload)
                write_char = character_repo.add if row.action == "create" else character_repo.update
                await write_char(character)
            else:
                setting = WorldSetting.model_validate(row.payload)
                write_world = world_repo.add if row.action == "create" else world_repo.update
                await write_world(setting)
            if row.action == "create":
                created += 1
            else:
                updated += 1
        await self._staging().delete_by_batch(project_id, batch_id)
        return ConfirmStagedResult(batch_id=batch_id, created=created, updated=updated)

    async def cancel_staged(self, project_id: uuid.UUID, batch_id: str) -> CancelStagedResult:
        """取消暂存批次（§5.9）：仅清空本批暂存行，零物化."""
        if await self._project_repo.get(project_id) is None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            raise ProjectNotFoundError()
        deleted = await self._staging().delete_by_batch(project_id, batch_id)
        return CancelStagedResult(batch_id=batch_id, deleted=deleted)

    async def list_staged(self, project_id: uuid.UUID, batch_id: str) -> StagedListResult:
        """读取本批暂存条目（§5.9，GET 暂存端点）."""
        if await self._project_repo.get(project_id) is None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            raise ProjectNotFoundError()
        items = await self._staging().list_by_batch(project_id, batch_id)
        return StagedListResult(batch_id=batch_id, items=items)
