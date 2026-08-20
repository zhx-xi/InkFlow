"""F9 角色业务服务 — 编排角色/分组/关系 CRUD + AI 提取入口.

职责（spec §7/§9）:
- 角色/分组/关系 CRUD 编排：委托 CharacterRepositoryProtocol，负责领域层
  UUID ↔ 仓储层 int 转换（沿用 F1 `_to_int_id` 模式）
- 业务校验（422 语义，抛 CharacterServiceError 子类）: 同名活动角色/分组、
  分组跨项目、关系自环、关系跨项目、重复关系
- 资源不存在（404 语义）: 多数方法返回 None 由 router 层转 404；
  create_relation 等返回非 Optional 的方法抛 CharacterNotFoundError
- 级联编排（spec §2.3/§6，v1.1 真删）: 角色真删 → 关系由 DB FK CASCADE
  物理级联删除；分组真删 → 成员角色 group_id 置 NULL（角色本身保留）
- AI 提取入口（§5.1 步骤 ①）: 校验项目存在并取 project.config.model 作为
  默认模型，再委托 CharacterExtractor 执行管线（②-⑦）

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:
- repository: CharacterRepositoryProtocol（B1/B2 已实现）
- extractor: CharacterExtractor（B2 已实现）
- project_repo: ProjectRepositoryProtocol（F1 已实现，extract 入口校验用）

依据: specs/f9-character-service/spec.md §7/§8/§9。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from inkflow.core.config import config
from inkflow.domain.models.character import (
    Character,
    CharacterExtractionResult,
    CharacterExtractRequest,
    CharacterGroup,
    CharacterRelation,
    CharacterUpdate,
)
from inkflow.domain.ports.character_errors import (
    CharacterNameConflictError,
    CharacterNotFoundError,
    CharacterServiceError,
    CrossProjectRelationError,
    GroupNameConflictError,
    GroupNotInProjectError,
    ProjectNotFoundError,
    RelationConflictError,
    SelfRelationError,
)
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.services._character_extractor import CharacterExtractor

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1 `_to_int_id` 模式）."""
    if isinstance(value, uuid.UUID):
        return value.int
    return value


class CharacterService:
    """角色业务服务 — 编排角色/分组/关系 CRUD 与 AI 提取.

    Args:
        repository: 角色/分组/关系仓储端口（B1/B2）.
        extractor: 角色提取管线（B2）；deps.py 负责组装，默认 None 时
            extract 入口报错（防止静默降级）.
        project_repo: 项目仓储（F1），extract 入口校验项目存在并读取默认模型.
        map_cleanup: 角色硬删钩子（F43 P5）：删除成功后解除 map_pins.ref_id
            （type=role）关联；失败由 deps 闭包处理，不阻断主流程.
        llm_default_model: 全局默认模型（#520 D1=C）——project.config.model 为
            None 时回退该值（deps.py 注入 config.llm_default_model）.
    """

    def __init__(
        self,
        *,
        repository: CharacterRepositoryProtocol,
        extractor: CharacterExtractor | None = None,
        project_repo: ProjectRepositoryProtocol | None = None,
        map_cleanup: Callable[[int], Awaitable[None]] | None = None,
        llm_default_model: str = config.llm_default_model,
    ) -> None:
        self._repo = repository
        self._extractor = extractor
        self._project_repo = project_repo
        self._map_cleanup = map_cleanup
        self._llm_default_model = llm_default_model

    # ── Character ──────────────────────────────────────────────────

    async def create_character(
        self,
        project_id: uuid.UUID,
        name: str,
        personality: str = "",
        background: str = "",
        goals: str = "",
        group_id: uuid.UUID | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Character:
        """创建角色（spec §7: 同名活动角色 → 422；分组跨项目 → 422）.

        Args:
            project_id: 所属项目 UUID（router 解析路径参数后传入）.
            name: 角色名（CharacterCreate 已去空白校验）.
            personality: 性格描述.
            background: 背景设定.
            goals: 目标/动机.
            group_id: 所属分组 UUID（None 表示未分组）.
            extra: 扩展属性字典（role_rank/groups 等）；None 落库为空 dict.

        Returns:
            持久化后的完整 Character.

        Raises:
            CharacterNameConflictError: 项目内已存在同名活动角色.
            GroupNotInProjectError: 分组不存在或不属于该项目.
        """
        pid_int = _to_int_id(project_id)
        existing = await self._repo.get_by_name(pid_int, name)
        if existing is not None:
            raise CharacterNameConflictError()
        if group_id is not None:
            group = await self._repo.get_group(_to_int_id(group_id))
            if group is None or group.project_id != project_id:
                raise GroupNotInProjectError()
        now = _utcnow()
        character = Character(
            id=uuid.uuid4(),
            project_id=project_id,
            name=name,
            personality=personality,
            background=background,
            goals=goals,
            group_id=group_id,
            extra=extra or {},
            created_at=now,
            updated_at=now,
        )
        logger.info("创建角色: project=%s name=%s", project_id, name)
        return await self._repo.add(character)

    async def get_character(self, character_id: int | uuid.UUID) -> Character | None:
        """按主键获取角色；不存在返回 None（router 转 404）."""
        return await self._repo.get(_to_int_id(character_id))

    async def list_characters(
        self,
        project_id: int | uuid.UUID,
        search: str | None = None,
        group_id: int | uuid.UUID | None = None,
        sort_by: str = "updated_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Character], int]:
        """分页查询项目内角色列表，支持搜索、分组过滤、排序.

        Returns:
            (当前页角色列表, 符合条件的总记录数).
        """
        return await self._repo.list(
            project_id=_to_int_id(project_id),
            search=search,
            group_id=_to_int_id(group_id) if group_id is not None else None,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )

    async def update_character(
        self, character_id: int | uuid.UUID, update: CharacterUpdate
    ) -> Character | None:
        """部分更新角色（exclude_unset 语义，同 F1）.

        业务校验（spec §7）: 改名撞项目内其他活动角色 → 422；group_id 指派
        的分组不存在或跨项目 → 422；group_id 显式置 None 表示清除分组。

        Args:
            character_id: 角色主键（支持 int 或 UUID）.
            update: 含待更新字段的 CharacterUpdate DTO.

        Returns:
            更新后的完整 Character；角色不存在返回 None（router 转 404）.
        """
        cid = _to_int_id(character_id)
        existing = await self._repo.get(cid)
        if existing is None:
            return None
        if "name" in update.model_fields_set and update.name is not None:
            dup = await self._repo.get_by_name(_to_int_id(existing.project_id), update.name)
            if dup is not None and dup.id != existing.id:
                raise CharacterNameConflictError()
        if "group_id" in update.model_fields_set and update.group_id is not None:
            group = await self._repo.get_group(_to_int_id(update.group_id))
            if group is None or group.project_id != existing.project_id:
                raise GroupNotInProjectError()
        merged = existing.model_copy(update=update.model_dump(exclude_unset=True))
        logger.info("更新角色: character_id=%s", character_id)
        return await self._repo.update(merged)

    async def delete_character(self, character_id: int | uuid.UUID) -> bool:
        """真删角色（v1.1，spec §7: 角色不存在 → False，router 转 404）.

        F43 P5: 删除成功后触发 map_cleanup 钩子（解除 map_pins.ref_id 关联）。

        Args:
            character_id: 角色主键（支持 int 或 UUID）.

        Returns:
            True 表示删除成功；False 表示未找到记录.
        """
        cid = _to_int_id(character_id)
        logger.info("真删角色: character_id=%s（关系显式清理 + FK 级联）", character_id)
        deleted = await self._repo.hard_delete(cid)
        if deleted and self._map_cleanup is not None:
            await self._map_cleanup(cid)
        return deleted

    # ── CharacterRelation ──────────────────────────────────────────

    async def list_relations(self, character_id: int | uuid.UUID) -> list[CharacterRelation]:
        """查询角色全部关系（双向: 作为 from 或 to，spec §6.1）.

        Args:
            character_id: 角色主键（支持 int 或 UUID）.

        Returns:
            该角色作为起点或终点的全部关系；角色不存在返回空列表.
        """
        cid = _to_int_id(character_id)
        character = await self._repo.get(cid)
        if character is None:
            return []
        return await self._repo.list_relations(_to_int_id(character.project_id), cid)

    async def create_relation(
        self,
        character_id: int | uuid.UUID,
        to_character_id: int | uuid.UUID,
        relation_type: str,
        description: str = "",
    ) -> CharacterRelation:
        """创建角色关系（from = 路径角色，spec §2.3 业务规则）.

        Args:
            character_id: 起点角色主键（支持 int 或 UUID）.
            to_character_id: 终点角色主键（支持 int 或 UUID）.
            relation_type: 关系类型（CharacterRelationCreate 已去空白校验）.
            description: 关系描述.

        Returns:
            持久化后的完整 CharacterRelation.

        Raises:
            SelfRelationError: 关系两端是同一角色（自环）.
            CharacterNotFoundError: 起点或终点角色不存在（router 转 404）.
            CrossProjectRelationError: 两端角色不属于同一项目.
            RelationConflictError: 同键 (from, to, relation_type) 活动关系已存在.
        """
        cid = _to_int_id(character_id)
        tid = _to_int_id(to_character_id)
        if cid == tid:
            raise SelfRelationError()
        from_char = await self._repo.get(cid)
        if from_char is None:
            raise CharacterNotFoundError()
        to_char = await self._repo.get(tid)
        if to_char is None:
            raise CharacterNotFoundError()
        if from_char.project_id != to_char.project_id:
            raise CrossProjectRelationError()
        if await self._repo.get_relation_by_key(cid, tid, relation_type) is not None:
            raise RelationConflictError()
        now = _utcnow()
        relation = CharacterRelation(
            id=uuid.uuid4(),
            project_id=from_char.project_id,
            from_character_id=from_char.id,
            to_character_id=to_char.id,
            relation_type=relation_type,
            description=description,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建关系: from=%s to=%s type=%s", from_char.name, to_char.name, relation_type)
        return await self._repo.add_relation(relation)

    async def update_relation(
        self,
        character_id: int | uuid.UUID,
        relation_id: int | uuid.UUID,
        *,
        relation_type: str | None = None,
        description: str | None = None,
    ) -> CharacterRelation | None:
        """部分更新关系（from/to 不变，仅 relation_type / description）.

        改关系类型撞同键活动关系 → RelationConflictError（422）。

        Args:
            character_id: 关系所属角色主键（from 或 to 均可）.
            relation_id: 关系主键.
            relation_type: 新关系类型（None 表示不修改）.
            description: 新关系描述（None 表示不修改）.

        Returns:
            更新后的完整 CharacterRelation；关系不存在或不属于该角色返回 None.
        """
        cid = _to_int_id(character_id)
        rid = _to_int_id(relation_id)
        relation = await self._repo.get_relation(rid)
        if relation is None or (
            _to_int_id(relation.from_character_id) != cid
            and _to_int_id(relation.to_character_id) != cid
        ):
            return None
        if relation_type is not None and relation_type != relation.relation_type:
            dup = await self._repo.get_relation_by_key(
                _to_int_id(relation.from_character_id),
                _to_int_id(relation.to_character_id),
                relation_type,
            )
            if dup is not None and dup.id != relation.id:
                raise RelationConflictError()
        merged = relation.model_copy(
            update={
                "relation_type": relation_type or relation.relation_type,
                "description": description if description is not None else relation.description,
            }
        )
        logger.info("更新关系: relation_id=%s", relation_id)
        return await self._repo.update_relation(merged)

    async def delete_relation(
        self, character_id: int | uuid.UUID, relation_id: int | uuid.UUID
    ) -> bool:
        """真删关系（v1.1，spec §7: 关系不存在/不属于该角色 → False，router 转 404）.

        Args:
            character_id: 关系所属角色主键（from 或 to 均可）.
            relation_id: 关系主键.

        Returns:
            True 表示删除成功；False 表示未找到记录.
        """
        cid = _to_int_id(character_id)
        rid = _to_int_id(relation_id)
        relation = await self._repo.get_relation(rid)
        if relation is None or (
            _to_int_id(relation.from_character_id) != cid
            and _to_int_id(relation.to_character_id) != cid
        ):
            return False
        logger.info("真删关系: relation_id=%s", relation_id)
        return await self._repo.hard_delete_relation(rid)

    # ── CharacterGroup ─────────────────────────────────────────────

    async def create_group(
        self,
        project_id: uuid.UUID,
        name: str,
        description: str = "",
        sort_order: int = 0,
    ) -> CharacterGroup:
        """创建角色分组（spec §2.2: 项目内活动分组名唯一）.

        Args:
            project_id: 所属项目 UUID.
            name: 分组名（1-50 字符，去空白）.
            description: 分组说明.
            sort_order: 排序权重（小在前，≥ 0）.

        Returns:
            持久化后的完整 CharacterGroup.

        Raises:
            GroupNameConflictError: 项目内已存在同名活动分组.
        """
        pid_int = _to_int_id(project_id)
        if any(g.name == name for g in await self._repo.list_groups(pid_int)):
            raise GroupNameConflictError()
        now = _utcnow()
        group = CharacterGroup(
            id=uuid.uuid4(),
            project_id=project_id,
            name=name,
            description=description,
            sort_order=sort_order,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建分组: project=%s name=%s", project_id, name)
        return await self._repo.add_group(group)

    async def get_group(self, group_id: int | uuid.UUID) -> CharacterGroup | None:
        """按主键获取分组；不存在返回 None（router 转 404）."""
        return await self._repo.get_group(_to_int_id(group_id))

    async def list_groups(self, project_id: int | uuid.UUID) -> list[CharacterGroup]:
        """查询项目内全部分组（按 sort_order 升序）."""
        return await self._repo.list_groups(_to_int_id(project_id))

    async def update_group(
        self,
        group_id: int | uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        sort_order: int | None = None,
    ) -> CharacterGroup | None:
        """部分更新分组；改名撞项目内其他活动分组 → GroupNameConflictError.

        Args:
            group_id: 分组主键（支持 int 或 UUID）.
            name: 新分组名（None 表示不修改）.
            description: 新分组说明（None 表示不修改）.
            sort_order: 新排序权重（None 表示不修改）.

        Returns:
            更新后的完整 CharacterGroup；分组不存在返回 None（router 转 404）.
        """
        gid = _to_int_id(group_id)
        group = await self._repo.get_group(gid)
        if group is None:
            return None
        if name is not None and name != group.name:
            groups = await self._repo.list_groups(_to_int_id(group.project_id))
            if any(g.name == name and g.id != group.id for g in groups):
                raise GroupNameConflictError()
        updates: dict[str, object] = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if sort_order is not None:
            updates["sort_order"] = sort_order
        merged = group.model_copy(update=updates)
        logger.info("更新分组: group_id=%s", group_id)
        return await self._repo.update_group(merged)

    async def delete_group(self, group_id: int | uuid.UUID) -> bool:
        """真删分组（v1.1，spec §6.2/§7: 成员角色 group_id 置 NULL，角色本身保留）.

        Args:
            group_id: 分组主键（支持 int 或 UUID）.

        Returns:
            True 表示删除成功；False 表示未找到记录.
        """
        gid = _to_int_id(group_id)
        logger.info("真删分组: group_id=%s（成员 group_id 置 NULL）", group_id)
        return await self._repo.hard_delete_group(gid)

    # ── AI 提取入口（spec §5.1 步骤 ①）────────────────────────────

    async def extract(self, request: CharacterExtractRequest) -> CharacterExtractionResult:
        """AI 提取角色/关系 — 校验项目存在后委托 CharacterExtractor.

        Args:
            request: 提取请求（project_id / text / 可选 model 覆盖）.

        Returns:
            合并落库后的提取报告.

        Raises:
            ProjectNotFoundError: 项目不存在（router 转 404「项目不存在」）.
            CharacterServiceError: 提取器/项目仓储未注入（配置错误）.
            CharacterExtractionError: 提取管线解析失败（透传，router 转 500）.
            LLMRequestError: LLM 调用失败（透传，router 转 500）.
        """
        if self._extractor is None:
            raise CharacterServiceError("角色提取器未配置")
        if self._project_repo is None:
            raise CharacterServiceError("项目仓储未配置，无法校验项目存在性")
        project = await self._project_repo.get(_to_int_id(request.project_id))
        if project is None:
            raise ProjectNotFoundError()
        logger.info(
            "角色提取: project=%s model=%s",
            request.project_id,
            request.model or project.config.model,
        )
        return await self._extractor.extract(
            request, default_model=project.config.model or self._llm_default_model
        )
