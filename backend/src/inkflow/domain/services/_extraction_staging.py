"""F14 统一提取服务的两段式暂存（spec §5.9，#1545）— 从门面拆分（#1545）.

门面 `extraction_service.py` 的「两段式暂存」横切能力（#1545 §5.9）拆分为本模块，
按 #307（`_extraction_rag.py`）先例，行为零变化，含两部分:

1. `_staged_entries`: 提取结果 detail 的 created / updated 条目 → `StagedEntry`
   列表（`extract(stage=True)` 落暂存区时使用，确定性、可单测）。
2. `_ExtractionStagingMixin`: `_staging()` 仓储取用 + `confirm_staged` 物化 /
   `cancel_staged` 清空 / `list_staged` 读取。

由 `ExtractionService` 继承（`class ExtractionService(_ExtractionRAGMixin,
_ExtractionStagingMixin)`）；共享属性（`_staging_repo` / `_project_repo` /
`_character_repo` / `_world_repo` / `_foreshadowing_repo` / `_timeline_repo` /
`_relation_repo` / `_relation_extraction_service`）由门面 `__init__` 装配，混入类内
以类型抑制声明（属性由 Service 提供）。

PR-2b（#1545 第二刀）: 暂存放开到全部可物化类型（`_STAGE_TARGETS` 分派表）——
`_staged_entries` 的 entity_type 覆盖 5 类，`confirm_staged` 按 entity_type 分派到
对应仓储（只要求该行对应仓储非空，支持部分装配），关系类型在 stage 下以
「只算不写」的 would-be 关系落暂存（`_staged_relation_result`）。

依据: specs/f14-extraction/spec.md §5.9。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from inkflow.domain.models.character import Character
from inkflow.domain.models.extraction import (
    CancelStagedResult,
    ConfirmStagedResult,
    ExtractionResult,
    ExtractionStatus,
    ExtractionType,
    StagedEntry,
    StagedListResult,
)
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.knowledge_graph import (
    KnowledgeRelation,
    KnowledgeRelationCreate,
    RelationSource,
)
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ExtractionRunError
from inkflow.domain.ports.extraction_staging_repository import (
    ExtractionStagingRepositoryProtocol,
)

_StageTarget = tuple[str, type[Any], str]
"""暂存物化分派三元组: (entity_type, 反序列化模型, Service 上的物化仓储属性名)."""

_STAGE_TARGETS: dict[ExtractionType, _StageTarget] = {
    ExtractionType.CHARACTER: ("character", Character, "_character_repo"),
    ExtractionType.SETTING: ("world_setting", WorldSetting, "_world_repo"),
    ExtractionType.FORESHADOWING: ("foreshadowing", Foreshadowing, "_foreshadowing_repo"),
    ExtractionType.TIMELINE: ("timeline_event", TimelineEvent, "_timeline_repo"),
    ExtractionType.KNOWLEDGE_RELATION: (
        "knowledge_relation",
        KnowledgeRelation,
        "_relation_repo",
    ),
}
"""两段式暂存类型分派表（§5.9，#1545 PR-2b 放开全类型）.

键 = 提取类型；值见 `_StageTarget`。outline / style 无档案实体产物（detail 不含
created / updated 清单）→ 不在表内（带 stage → 422）。
"""

_ENTITY_TARGETS: dict[str, _StageTarget] = {t[0]: t for t in _STAGE_TARGETS.values()}
"""entity_type → 分派三元组（`confirm_staged` 倒排查用；键与 `_STAGE_TARGETS` 同源）."""


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知），与各提取管线同款口径."""
    return datetime.now(UTC)


def _staged_entries(type_: ExtractionType, detail: dict[str, Any]) -> list[StagedEntry]:
    """detail 的 created / updated 条目 → 暂存条目（#1545 §5.9）."""
    target = _STAGE_TARGETS.get(type_)
    entity_type = target[0] if target is not None else type_.value
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

    def _stage_capable(self, type_: ExtractionType) -> bool:
        """该类型是否可两段式暂存（§5.9，#1545 PR-2b）.

        character / setting / foreshadowing / timeline 的暂存条目最终由
        `confirm_staged` 写回**对应**档案仓储 → 该仓储未装配时暂存不可兑现
        （门面按 422 处理）。knowledge_relation 的物化走 F48 关系写入点、不经
        F14 档案仓储，故不受该门控；outline / style 无档案实体产物 → 不可暂存。
        """
        if type_ is ExtractionType.KNOWLEDGE_RELATION:
            return True
        target = _STAGE_TARGETS.get(type_)
        if target is None:
            return False
        return getattr(self, target[2], None) is not None

    async def confirm_staged(self, project_id: uuid.UUID, batch_id: str) -> ConfirmStagedResult:
        """确认暂存批次（§5.9）：逐行按 entity_type / action 分派物化，随后清空本批暂存.

        #1545 PR-2b: 分派粒度到 entity_type —— 只要求**该行对应**的仓储非空
        （支持只装配部分仓储），不再要求 character / world 两仓齐备.
        """
        if await self._project_repo.get(project_id) is None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            raise ProjectNotFoundError()
        created = updated = 0
        for row in await self._staging().list_by_batch(project_id, batch_id):
            target = _ENTITY_TARGETS.get(row.entity_type)
            repo: Any = None if target is None else getattr(self, target[2], None)
            if target is None or repo is None:  # pragma: no cover - 分派表与 DI 装配一致
                raise ExtractionRunError(f"暂存目标仓储未装配，无法确认暂存（{row.entity_type}）")
            entity = target[1].model_validate(row.payload)
            write = repo.add if row.action == "create" else repo.update
            await write(entity)
            if row.action == "create":
                created += 1
            else:
                updated += 1
        await self._staging().delete_by_batch(project_id, batch_id)
        return ConfirmStagedResult(batch_id=batch_id, created=created, updated=updated)

    async def _staged_relation_result(self, project_id: uuid.UUID) -> ExtractionResult:
        """stage（零写入）下的 KNOWLEDGE_RELATION 结果（§5.9，#1545 PR-2b）.

        关系落库发生在 F48 `RelationExtractionService.extract_for_project` 内部，stage
        下不可调用 → 复用其确定性规则集（`extract_rules`：只算不写、零 LLM），把
        would-be 关系装配成完整 `KnowledgeRelation`（补 id / project_id / 时间戳；
        source=ai 对齐既有写入口径）后放进信封 detail 的 created 清单，供暂存区接管
        （`_staged_entries` → entity_type=knowledge_relation）。
        """
        service = self._relation_extraction_service  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
        if service is None:
            # 未装配关系服务 → 无可比算的 would-be 关系（stage 不因此 422，§5.9 全类型放开）
            return ExtractionResult(
                type=ExtractionType.KNOWLEDGE_RELATION,
                status=ExtractionStatus.SUCCESS,
                detail={"created": [], "updated": []},
            )
        candidates: list[KnowledgeRelationCreate] = []
        warnings: list[str] = []
        await service.extract_rules(project_id, candidates, warnings)
        now = _utcnow()
        relations = [
            KnowledgeRelation(
                id=uuid.uuid4(),
                project_id=project_id,
                source=RelationSource.AI,
                created_at=now,
                updated_at=now,
                **candidate.model_dump(),
            )
            for candidate in candidates
        ]
        return ExtractionResult(
            type=ExtractionType.KNOWLEDGE_RELATION,
            status=ExtractionStatus.SUCCESS,
            created=len(relations),
            updated=0,
            warnings=warnings,
            detail={"created": [r.model_dump(mode="json") for r in relations], "updated": []},
        )

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
