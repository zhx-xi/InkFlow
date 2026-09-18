"""F48 知识图谱业务服务 — 跨实体关系校验链 + 图谱聚合 + 清理回调 + #479 预留端口.

职责（spec §5.1/§5.2/§5.3/§5.5）:
- 跨实体校验链: 项目存在 → 自环 → 六元组字段校验（Pydantic）→ 实体存在 + 同项目
  → 同键唯一 → 落库（source 恒 manual）；各实体 repo 的「不存在」统一转换
  KnowledgeEntityNotFoundError（图谱域统一错误面，不泄漏 F9-F13 错误类）
- 图谱聚合: nodes = 六类实体全量（组序 character→world→outline→timeline→
  foreshadow→map_pin，组内 name ASC）；edges = knowledge_relations 单表全量，
  created_at ASC；character_relations 已 #495 合并；孤立边跳过 + warning
- 实体硬删级联清理: cleanup_for_entity 委托 relation_repo（F36 钩子先例，
  默认 None 依赖向后兼容）
- #479 预留: bulk_create_relations（单事务批量 + 同键幂等跳过）

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）: 仅依赖 domain/ports
协议层，不 import 各实体 service（防循环依赖，spec §6）。

依据: specs/f48-knowledge-graph/spec.md §5.1/§5.2/§5.3/§5.5/§5.6/§7。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from pydantic import ValidationError

from inkflow.domain.models.knowledge_graph import (
    EntityType,
    GraphEdge,
    GraphNode,
    KnowledgeGraphView,
    KnowledgeRelation,
    KnowledgeRelationCreate,
    RelationSource,
)
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.knowledge_graph_errors import (
    KnowledgeEntityNotFoundError,
    KnowledgeRelationConflictError,
    KnowledgeRelationNotFoundError,
    KnowledgeRelationSelfLoopError,
    KnowledgeRelationValidationError,
)
from inkflow.domain.ports.knowledge_relation_repository import (
    KnowledgeRelationRepositoryProtocol,
)
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.world_errors import ProjectNotFoundError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._data_change import publish_change


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _to_uuid(value: int | uuid.UUID) -> uuid.UUID:
    """将 int 或 UUID 统一转为 uuid.UUID（#1291：仅兼容外部 int 入参，非仓库层中转）."""
    if isinstance(value, int):
        return uuid.UUID(int=value)
    return value


class KnowledgeGraphService:
    """知识图谱业务服务 — 跨实体关系编排 + 图谱聚合.

    Args:
        relation_repo: 图谱关系仓储端口（必填）.
        project_repo: 项目仓储（create 入口校验项目存在性；None = 未注入）.
        character_repo: 角色仓储（实体校验 + 图谱节点）.
        world_repo: 世界观仓储（实体校验 + 图谱节点）.
        outline_repo: 大纲仓储（实体校验 + 图谱节点）.
        timeline_repo: 时间线仓储（实体校验 + 图谱节点）.
        foreshadow_repo: 伏笔仓储（实体校验 + 图谱节点）.
        map_repo: 地图仓储（map_pin 校验链路 + 图谱节点）.
    """

    def __init__(
        self,
        *,
        relation_repo: KnowledgeRelationRepositoryProtocol,
        project_repo: ProjectRepositoryProtocol | None = None,
        character_repo: CharacterRepositoryProtocol | None = None,
        world_repo: WorldRepositoryProtocol | None = None,
        outline_repo: OutlineRepositoryProtocol | None = None,
        timeline_repo: TimelineRepositoryProtocol | None = None,
        foreshadow_repo: ForeshadowingRepositoryProtocol | None = None,
        map_repo: MapRepositoryProtocol | None = None,
    ) -> None:
        self._relation_repo = relation_repo
        self._project_repo = project_repo
        self._character_repo = character_repo
        self._world_repo = world_repo
        self._outline_repo = outline_repo
        self._timeline_repo = timeline_repo
        self._foreshadow_repo = foreshadow_repo
        self._map_repo = map_repo

    async def _validate_entity(
        self,
        project_id_uuid: uuid.UUID,
        entity_type: EntityType,
        entity_id: uuid.UUID,
        endpoint: str,
    ) -> None:
        """校验实体存在且属于目标项目；失败统一抛 KnowledgeEntityNotFoundError.

        各实体按 EntityType 分派只读校验（spec §2.2）: character/world/outline/
        timeline/foreshadow → repo.get(id) 存在 + 同项目；map_pin → repo.get_pin(id)
        + repo.get(pin.map_id) 的 map.project_id == 项目（经 map→project 链路推导）.

        Args:
            project_id_uuid: 目标项目主键（领域 UUID）。
            entity_type: 实体类型.
            entity_id: 实体主键（领域 UUID）.
            endpoint: 端点标识（"source" / "target"，用于错误 detail）.

        Raises:
            KnowledgeEntityNotFoundError: 实体不存在或不在同一项目.
        """
        if entity_type is EntityType.MAP_PIN:
            pin = (
                await self._map_repo.get_pin(_to_uuid(entity_id))
                if self._map_repo is not None
                else None
            )
            wm = (
                await self._map_repo.get(pin.map_id)
                if self._map_repo is not None and pin is not None
                else None
            )
            if wm is None or wm.project_id != project_id_uuid:
                raise KnowledgeEntityNotFoundError(
                    message=f"{endpoint} 实体不存在或不在同一项目: {entity_type.value}"
                )
            return
        repo = self._repo_for(entity_type)
        entity = await repo.get(entity_id) if repo is not None else None
        if entity is None or entity.project_id != project_id_uuid:
            raise KnowledgeEntityNotFoundError(
                message=f"{endpoint} 实体不存在或不在同一项目: {entity_type.value}"
            )

    def _repo_for(
        self, entity_type: EntityType
    ) -> (
        CharacterRepositoryProtocol
        | WorldRepositoryProtocol
        | OutlineRepositoryProtocol
        | TimelineRepositoryProtocol
        | ForeshadowingRepositoryProtocol
        | None
    ):
        """按实体类型返回校验 repo（map_pin 走独立链路，不会走到这里）."""
        if entity_type is EntityType.CHARACTER:
            return self._character_repo
        if entity_type is EntityType.WORLD:
            return self._world_repo
        if entity_type is EntityType.OUTLINE:
            return self._outline_repo
        if entity_type is EntityType.TIMELINE:
            return self._timeline_repo
        if entity_type is EntityType.FORESHADOW:
            return self._foreshadow_repo
        return None

    # ── 关系 CRUD（spec §5.1 校验链）────────────────────────────────────

    async def create_relation(
        self,
        project_id: uuid.UUID,
        source_type: str,
        source_id: uuid.UUID,
        target_type: str,
        target_id: uuid.UUID,
        relation_type: str,
        description: str = "",
    ) -> KnowledgeRelation:
        """创建图谱关系（校验链 ①-⑥）.

        Args:
            project_id: 所属项目 UUID.
            source_type: 起点实体类型（EntityType 值字符串）.
            source_id: 起点实体 UUID.
            target_type: 终点实体类型（EntityType 值字符串）.
            target_id: 终点实体 UUID.
            relation_type: 关系类型（去空白 1-20 字符）.
            description: 关系说明（≤ 500 字符）.

        Returns:
            持久化后的 KnowledgeRelation（source 恒 manual）.

        Raises:
            ProjectNotFoundError: 项目不存在（404，world_errors 复用）.
            KnowledgeRelationSelfLoopError: 自环（同类型同 id）.
            KnowledgeRelationValidationError: 六元组字段校验失败.
            KnowledgeEntityNotFoundError: 起点/终点实体不存在或跨项目.
            KnowledgeRelationConflictError: 同键关系已存在.
        """
        pid_int = _to_uuid(project_id)
        # ① 项目存在
        project = (
            await self._project_repo.get(project_id) if self._project_repo is not None else None
        )
        if project is None:
            raise ProjectNotFoundError()
        # ② 自环
        if source_type == target_type and _to_uuid(source_id) == _to_uuid(target_id):
            raise KnowledgeRelationSelfLoopError()
        # ③ 六元组字段校验（Pydantic → 422）
        try:
            dto = KnowledgeRelationCreate(
                source_type=EntityType(source_type),
                source_id=source_id,
                target_type=EntityType(target_type),
                target_id=target_id,
                relation_type=relation_type,
                description=description,
            )
        except ValidationError as exc:
            raise KnowledgeRelationValidationError(str(exc)) from exc
        # ④ 实体存在 + 同项目（source 先于 target）
        await self._validate_entity(pid_int, dto.source_type, dto.source_id, "source")
        await self._validate_entity(pid_int, dto.target_type, dto.target_id, "target")
        # ⑤ 同键唯一
        if (
            await self._relation_repo.get_by_key(
                pid_int,
                dto.source_type.value,
                _to_uuid(dto.source_id),
                dto.target_type.value,
                _to_uuid(dto.target_id),
                dto.relation_type,
            )
            is not None
        ):
            raise KnowledgeRelationConflictError()
        # ⑥ 落库（source 恒 manual，§2.1 规则 5）
        now = _utcnow()
        relation = KnowledgeRelation(
            id=uuid.uuid4(),
            project_id=project_id,
            source_type=dto.source_type,
            source_id=dto.source_id,
            target_type=dto.target_type,
            target_id=dto.target_id,
            relation_type=dto.relation_type,
            description=dto.description,
            source=RelationSource.MANUAL,
            created_at=now,
            updated_at=now,
        )
        logger.info(
            "创建图谱关系: project=%s %s:%s --%s--> %s:%s",
            project_id,
            dto.source_type.value,
            dto.source_id,
            dto.relation_type,
            dto.target_type.value,
            dto.target_id,
        )
        created: KnowledgeRelation = await self._relation_repo.add(relation)
        await publish_change("knowledge_relation", "create", created.id, created.project_id)
        return created

    async def get_relation(self, relation_id: uuid.UUID) -> KnowledgeRelation:
        """按主键获取关系；不存在 → KnowledgeRelationNotFoundError（404）."""
        relation = await self._relation_repo.get(relation_id)
        if relation is None:
            raise KnowledgeRelationNotFoundError()
        return relation

    async def update_relation(
        self,
        relation_id: uuid.UUID,
        *,
        source_type: str | None = None,
        source_id: uuid.UUID | None = None,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        relation_type: str | None = None,
        description: str | None = None,
        source: str | None = None,
    ) -> KnowledgeRelation:
        """部分更新关系（只校验传入字段；六元组可改）.

        Args:
            relation_id: 关系主键 UUID.
            source_type/source_id/target_type/target_id/relation_type/description:
                可更新字段，None 表示不修改；description 传空串 = 清空.
            source: 不可修改（#479 写入方才能置 ai）.

        Returns:
            更新后的 KnowledgeRelation.

        Raises:
            KnowledgeRelationNotFoundError: 关系不存在（404）.
            KnowledgeRelationValidationError: source 不可改 / 字段校验失败.
            KnowledgeEntityNotFoundError: 变更端点实体不存在或跨项目.
            KnowledgeRelationConflictError: 改键后与另一行冲突.
        """
        existing = await self._relation_repo.get(relation_id)
        if existing is None:
            raise KnowledgeRelationNotFoundError()
        # ② source 不可改（§7 边界 7）
        if source is not None:
            raise KnowledgeRelationValidationError("source 字段不可修改")
        updates: dict[str, object] = {}
        if source_type is not None:
            updates["source_type"] = source_type
        if source_id is not None:
            updates["source_id"] = source_id
        if target_type is not None:
            updates["target_type"] = target_type
        if target_id is not None:
            updates["target_id"] = target_id
        if relation_type is not None:
            updates["relation_type"] = relation_type
        if description is not None:
            updates["description"] = description
        merged = existing.model_copy(update=updates)
        # 传入字段重新校验（同 create ②③④，只校验传入字段）
        if updates:
            try:
                dto = KnowledgeRelationCreate(
                    source_type=EntityType(merged.source_type),
                    source_id=merged.source_id,
                    target_type=EntityType(merged.target_type),
                    target_id=merged.target_id,
                    relation_type=merged.relation_type,
                    description=merged.description,
                )
            except ValidationError as exc:
                raise KnowledgeRelationValidationError(str(exc)) from exc
        else:
            dto = KnowledgeRelationCreate(
                source_type=merged.source_type,
                source_id=merged.source_id,
                target_type=merged.target_type,
                target_id=merged.target_id,
                relation_type=merged.relation_type,
                description=merged.description,
            )
        # 自环检查：仅当两端字段被变更时重查
        if dto.source_type is dto.target_type and _to_uuid(dto.source_id) == _to_uuid(
            dto.target_id
        ):
            raise KnowledgeRelationSelfLoopError()
        pid_int = _to_uuid(existing.project_id)
        # 实体存在 + 同项目（只校验传入端点）
        if source_type is not None or source_id is not None:
            await self._validate_entity(pid_int, dto.source_type, dto.source_id, "source")
        if target_type is not None or target_id is not None:
            await self._validate_entity(pid_int, dto.target_type, dto.target_id, "target")
        # ③ 同键唯一（改键后与另一行冲突 → 422；查到自身 = 键未变，放行，#537）
        existing_by_key: KnowledgeRelation | None = await self._relation_repo.get_by_key(
            pid_int,
            dto.source_type.value,
            _to_uuid(dto.source_id),
            dto.target_type.value,
            _to_uuid(dto.target_id),
            dto.relation_type,
        )
        if existing_by_key is not None and _to_uuid(existing_by_key.id) != _to_uuid(relation_id):
            raise KnowledgeRelationConflictError()
        merged = merged.model_copy(update={"updated_at": _utcnow()})
        logger.info("更新图谱关系: relation_id=%s", relation_id)
        updated: KnowledgeRelation | None = await self._relation_repo.update(merged)
        await publish_change("knowledge_relation", "update", relation_id, existing.project_id)
        return updated if updated is not None else merged

    async def delete_relation(self, relation_id: uuid.UUID) -> bool:
        """真删关系；不存在 → KnowledgeRelationNotFoundError（404）."""
        relation: KnowledgeRelation = await self.get_relation(relation_id)
        logger.info("真删图谱关系: relation_id=%s", relation_id)
        deleted: bool = await self._relation_repo.delete(_to_uuid(relation_id))
        if deleted:
            await publish_change("knowledge_relation", "delete", relation_id, relation.project_id)
        return deleted

    async def list_relations(
        self,
        project_id: uuid.UUID,
        *,
        source_type: str | None = None,
        target_type: str | None = None,
        relation_type: str | None = None,
        source: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[KnowledgeRelation], int]:
        """过滤 + 分页查询项目内关系（委托 repo.filter）.

        Returns:
            (关系列表, 总数) 元组，created_at DESC 由 repo 保证.
        """
        pid_int = _to_uuid(project_id)
        # #1151: 先判父项目存在——缺失 → 404；顺带防 128 位 int 走到过滤 SQL 绑定
        # 抛 OverflowError → 500（project_repo.get 自带 int64 守卫，#1139 同族口径）
        project_repo = self._project_repo
        if project_repo is not None and await project_repo.get(project_id) is None:
            raise ProjectNotFoundError()
        return await self._relation_repo.filter(
            pid_int,
            source_type=source_type,
            target_type=target_type,
            relation_type=relation_type,
            source=source,
            offset=offset,
            limit=limit,
        )

    # ── 图谱聚合（spec §5.2/§5.6）──────────────────────────────────────

    async def graph(self, project_id: uuid.UUID) -> KnowledgeGraphView:
        """图谱聚合查询：六类实体全量节点 + knowledge_relations 单表边.

        nodes 组序 character→world→outline→timeline→foreshadow→map_pin，组内
        name ASC；edges 单一来源 knowledge_relations（character↔character 已
        #495 合并），按 created_at ASC；孤立边（端点不在 nodes）跳过 + warning。

        Args:
            project_id: 项目 UUID.

        Returns:
            KnowledgeGraphView（nodes + edges）.
        """
        pid_int = _to_uuid(project_id)
        # #1151: 先判父项目存在——缺失 → 404；顺带防 128 位 int 走到聚合各 repo
        # 绑定抛 OverflowError → 500（project_repo.get 自带 int64 守卫）
        project_repo = self._project_repo
        if project_repo is not None and await project_repo.get(project_id) is None:
            raise ProjectNotFoundError()
        nodes: list[GraphNode] = []
        nodes.extend(await self._collect_nodes(pid_int, EntityType.CHARACTER, lambda e: e.name))
        nodes.extend(await self._collect_nodes(pid_int, EntityType.WORLD, lambda e: e.name))
        nodes.extend(await self._collect_nodes(pid_int, EntityType.OUTLINE, lambda e: e.name))
        nodes.extend(await self._collect_nodes(pid_int, EntityType.TIMELINE, lambda e: e.title))
        nodes.extend(await self._collect_nodes(pid_int, EntityType.FORESHADOW, lambda e: e.title))
        nodes.extend(await self._collect_map_pin_nodes(pid_int))
        nodes.sort(key=lambda n: (_NODE_TYPE_ORDER.index(n.type), n.name))
        node_ids = {n.id for n in nodes}

        kr_edges: list[tuple[datetime, GraphEdge]] = []
        for kr in await self._relation_repo.list_by_project(pid_int):
            src = f"{kr.source_type.value}:{kr.source_id}"
            tgt = f"{kr.target_type.value}:{kr.target_id}"
            if src not in node_ids or tgt not in node_ids:
                logger.warning(
                    "图谱孤立边跳过: relation=%s（端点 %s / %s 不在节点集）",
                    kr.id,
                    src,
                    tgt,
                )
                continue
            kr_edges.append(
                (
                    kr.created_at,
                    GraphEdge(
                        id=f"kr:{kr.id}",
                        source=src,
                        target=tgt,
                        label=kr.relation_type,
                        description=kr.description,
                        source_table="knowledge_relations",
                    ),
                )
            )
        kr_edges.sort(key=lambda pair: pair[0])

        edges = [e for _, e in kr_edges]
        return KnowledgeGraphView(nodes=nodes, edges=edges)

    async def _collect_nodes(
        self,
        project_id_uuid: uuid.UUID,
        entity_type: EntityType,
        name_of: Callable[[Any], str],
    ) -> list[GraphNode]:
        """收集一类实体为图谱节点（repo 未注入 → 空列表）."""
        repo = self._repo_for(entity_type)
        if repo is None:
            return []
        items, _ = await repo.list(project_id_uuid)
        nodes: list[GraphNode] = []
        for item in items:
            nodes.append(
                GraphNode(
                    id=f"{entity_type.value}:{item.id}",
                    type=entity_type,
                    entity_id=item.id,
                    name=name_of(item),
                )
            )
        return nodes

    async def _collect_map_pin_nodes(self, project_id_uuid: uuid.UUID) -> list[GraphNode]:
        """收集项目全部 map_pin 节点（经 map→pin 链路）."""
        if self._map_repo is None:
            return []
        maps = await self._map_repo.list_maps_by_project(project_id_uuid)
        nodes: list[GraphNode] = []
        for wm in maps:
            pins = await self._map_repo.list_pins(wm.id)
            for pin in pins:
                nodes.append(
                    GraphNode(
                        id=f"map_pin:{pin.id}",
                        type=EntityType.MAP_PIN,
                        entity_id=pin.id,
                        name=pin.label,
                    )
                )
        return nodes

    # ── 实体硬删清理回调（spec §5.3）──────────────────────────────────

    async def cleanup_for_entity(
        self, entity_type: EntityType | str, entity_id: int | uuid.UUID
    ) -> int:
        """实体硬删后级联清理关系行（委托 relation_repo.cleanup_for_entity）.

        Args:
            entity_type: 实体类型（EntityType 枚举或值字符串）.
            entity_id: 实体主键（支持 int 或 UUID）.

        Returns:
            删除行数.
        """
        type_str = entity_type.value if isinstance(entity_type, EntityType) else entity_type
        deleted: int = await self._relation_repo.cleanup_for_entity(type_str, _to_uuid(entity_id))
        logger.info(
            "图谱关系清理回调: entity_type=%s entity_id=%s deleted=%s",
            type_str,
            entity_id,
            deleted,
        )
        if deleted:
            logger.warning(
                "knowledge_relation 删除事件缺 project_id"
                "（cleanup_for_entity 签名无 project_id，spec §15.3.2）: id=%s",
                entity_id,
            )
            await publish_change("knowledge_relation", "delete", str(entity_id), None)
        return deleted

    # ── #479 预留端口（spec §5.5）──────────────────────────────────────

    async def bulk_create_relations(
        self,
        project_id: uuid.UUID,
        relations: list[KnowledgeRelationCreate],
        source: RelationSource | str = RelationSource.AI,
    ) -> list[KnowledgeRelation]:
        """批量写入关系 — #479 预留端口.

        单事务批量 + 同键幂等（get_by_key 已存在 → 跳过该行）；实体存在性由
        #479 调用方保证（本端口不重复校验）。

        Args:
            project_id: 所属项目 UUID.
            relations: 待写入关系 DTO 列表.
            source: 关系来源（默认 ai，#479 提取写入）.

        Returns:
            实际落库的关系列表（跳过行不返回）.
        """
        pid_int = _to_uuid(project_id)
        source_value = source if isinstance(source, RelationSource) else RelationSource(source)
        now = _utcnow()
        created: list[KnowledgeRelation] = []
        for dto in relations:
            if (
                await self._relation_repo.get_by_key(
                    pid_int,
                    dto.source_type.value,
                    _to_uuid(dto.source_id),
                    dto.target_type.value,
                    _to_uuid(dto.target_id),
                    dto.relation_type,
                )
                is not None
            ):
                logger.warning(
                    "图谱批量写入同键跳过: %s:%s --%s--> %s:%s",
                    dto.source_type.value,
                    dto.source_id,
                    dto.relation_type,
                    dto.target_type.value,
                    dto.target_id,
                )
                continue
            relation = KnowledgeRelation(
                id=uuid.uuid4(),
                project_id=project_id,
                source_type=dto.source_type,
                source_id=dto.source_id,
                target_type=dto.target_type,
                target_id=dto.target_id,
                relation_type=dto.relation_type,
                description=dto.description,
                source=source_value,
                created_at=now,
                updated_at=now,
            )
            created.append(await self._relation_repo.add(relation))
        if created:
            await publish_change("knowledge_relation", "create", str(project_id), project_id)
        return created


_NODE_TYPE_ORDER = [
    EntityType.CHARACTER,
    EntityType.WORLD,
    EntityType.OUTLINE,
    EntityType.TIMELINE,
    EntityType.FORESHADOW,
    EntityType.MAP_PIN,
]
