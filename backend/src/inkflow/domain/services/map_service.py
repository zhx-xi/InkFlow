"""F36 地图业务服务 — 编排地图/pin CRUD + 图片资产生命周期 + 真删矩阵.

职责（spec §5.3/§5.4）:
- 地图/pin CRUD 编排：委托 MapRepositoryProtocol，负责领域层 UUID ↔ 仓储层
  int 转换（沿用 F1 `_to_int_id` 模式）
- 图片资产生命周期（D5）: 换图先写新成功后删旧；DB 落库失败回滚已写文件（防孤儿）
- 真删矩阵（D6）: 无子真删 / 有子必须 cascade 或 reparent / 递归子树级联
- 项目/地点硬删钩子（D10=b）: cleanup_project / clear_location_pins

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:
- repository: MapRepositoryProtocol（G3 已实现）
- asset_store: MapAssetStoreProtocol（G2 已实现，本地文件系统）
- world_repo: WorldRepositoryProtocol（F10/F35 已实现，location 校验）
- project_repo: ProjectRepositoryProtocol（F1 已实现，create 校验 + 项目硬删钩子）

依据: specs/f36-world-map/spec.md §5.3/§5.4。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from inkflow.domain.models.map import MapPin, MapPinUpdate, WorldMap, WorldMapUpdate
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.map_errors import (
    MapBgSourceError,
    MapChildrenActionRequiredError,
    MapNameConflictError,
    MapNotFoundError,
    MapPinLocationNotFoundError,
    MapPinRefNotFoundError,
    MapReparentTargetError,
    MapRootLocationConflictError,
    MapRootLocationNotFoundError,
)
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.world_errors import ProjectNotFoundError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.infrastructure.assets.map_asset_store import MapAssetStoreProtocol

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1 `_to_int_id` 模式）."""
    if isinstance(value, uuid.UUID):
        return value.int
    return value


class MapService:
    """F36 地图业务服务 — 编排地图/pin CRUD + 图片资产生命周期 + 真删矩阵.

    Args:
        repository: 地图仓储端口.
        asset_store: 图片资产存储端口（本地文件系统）.
        world_repo: 世界观条目仓储（root_location/pin location 校验）.
        project_repo: 项目仓储（create 校验 + 项目硬删钩子）.
        character_repo: 角色仓储（F43 P2 type=role 关联校验；None=跳过校验仅透传）.
        timeline_repo: 时间线仓储（F43 P2 type=event 关联校验；None=跳过校验仅透传）.
    """

    def __init__(
        self,
        *,
        repository: MapRepositoryProtocol,
        asset_store: MapAssetStoreProtocol,
        world_repo: WorldRepositoryProtocol,
        project_repo: ProjectRepositoryProtocol | None = None,
        character_repo: CharacterRepositoryProtocol | None = None,
        timeline_repo: TimelineRepositoryProtocol | None = None,
    ) -> None:
        self._repo = repository
        self._asset_store = asset_store
        self._world_repo = world_repo
        self._project_repo = project_repo
        self._character_repo = character_repo
        self._timeline_repo = timeline_repo

    # ── 地图 CRUD ───────────────────────────────────────────────

    async def create_map(
        self,
        project_id: int | uuid.UUID,
        name: str,
        description: str = "",
        root_location_id: int | uuid.UUID | None = None,
        image_filename: str = "",
        image_content: bytes = b"",
        bg_source: str = "image",
    ) -> WorldMap:
        """创建地图（spec §5.4 校验链 ①②③ + 文件/落库编排 ④⑤⑥）.

        Args:
            project_id: 所属项目 UUID（支持 int 或 UUID）.
            name: 地图名（项目内唯一）.
            description: 地图描述.
            root_location_id: 根地点 UUID；None = 全局图（不挂地点）.
            image_filename: 图片文件名（扩展名决定存储格式）.
            image_content: 图片字节内容.
            bg_source: F43 P2 底图来源（shape/image/ai）；shape/ai 可无图
                （image_path 存空串），image 模式缺图 → MapBgSourceError.

        Returns:
            持久化后的完整 WorldMap.

        Raises:
            ProjectNotFoundError: 项目不存在（404，world_errors 复用）.
            MapRootLocationNotFoundError: 根地点不存在或跨项目（422）.
            MapNameConflictError: 项目内同名地图已存在（422）.
            MapRootLocationConflictError: 根地点已挂有其他地图（422）.
            MapBgSourceError: bg_source 非法或 image 模式缺图片（422）.
            MapAssetError: 图片写入失败（500，透传不落库）.
        """
        if bg_source not in {"shape", "image", "ai"}:
            raise MapBgSourceError()
        pid_int = _to_int_id(project_id)
        # ① 项目存在性
        if self._project_repo is None or await self._project_repo.get(pid_int) is None:
            raise ProjectNotFoundError()
        # ② 根地点存在 + 同项目（repo.get 仅返回活动条目 → 软删地点 = 不存在）
        root_int = _to_int_id(root_location_id) if root_location_id is not None else None
        if root_int is not None:
            loc = await self._world_repo.get(root_int)
            if loc is None or _to_int_id(loc.project_id) != pid_int:
                raise MapRootLocationNotFoundError()
        # ③ 项目内同名 + 根地点唯一挂载
        if await self._repo.get_by_name(pid_int, name) is not None:
            raise MapNameConflictError()
        if root_int is not None:
            existing_maps, _ = await self._repo.list(pid_int, root_location_id=root_int)
            if existing_maps:
                raise MapRootLocationConflictError()
        # ④ 图片文件编排：image 模式必填图片（缺图 422）；shape/ai 可无图
        #    （不写图，image_path 存空串——F43 P2 简图语义）
        map_id = uuid.uuid4()
        if image_content:
            rel_path = await self._asset_store.save(
                map_id=map_id, filename=image_filename, content=image_content
            )
        else:
            if bg_source == "image":
                raise MapBgSourceError()
            rel_path = ""
        # ⑤ 落库失败 → 删已写文件防孤儿 → re-raise
        now = _utcnow()
        wm = WorldMap(
            id=map_id,
            project_id=uuid.UUID(int=pid_int),
            name=name,
            image_path=rel_path,
            description=description,
            root_location_id=uuid.UUID(int=root_int) if root_int is not None else None,
            bg_source=bg_source,
            created_at=now,
            updated_at=now,
        )
        try:
            return await self._repo.add(wm)
        except Exception:
            try:
                await self._asset_store.delete(rel_path)
            except Exception:
                logger.warning("创建地图失败后清理图片文件异常: %s", rel_path, exc_info=True)
            raise

    async def list_maps(
        self,
        project_id: int | uuid.UUID,
        root_location_id: int | uuid.UUID | None = None,
        top_level_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[WorldMap], int]:
        """分页查询项目内地图列表（透传 repo.list，root_location_id 转 int）.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.
            root_location_id: 根地点精确过滤（可选）.
            top_level_only: True 只返回全局图（root_location_id IS NULL）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (地图列表, 总数) 元组，按 created_at DESC 排序.
        """
        return await self._repo.list(
            project_id=_to_int_id(project_id),
            root_location_id=(
                _to_int_id(root_location_id) if root_location_id is not None else None
            ),
            top_level_only=top_level_only,
            offset=offset,
            limit=limit,
        )

    async def get_map(self, map_id: int | uuid.UUID) -> WorldMap | None:
        """按主键获取地图；不存在返回 None（router 转 404）."""
        return await self._repo.get(_to_int_id(map_id))

    async def get_image_file(self, map_id: int | uuid.UUID) -> Path | None:
        """返回地图图片的绝对路径（FileResponse 用；地图不存在返回 None）."""
        wm = await self._repo.get(_to_int_id(map_id))
        if wm is None:
            return None
        return self._asset_store.resolve(wm.image_path)

    async def update_map(self, map_id: int | uuid.UUID, update: WorldMapUpdate) -> WorldMap | None:
        """更新地图元数据（exclude_unset 语义；不换图，换图走 replace_image）.

        校验链（spec §5.4）:
        ① 地图不存在 → 返回 None
        ② 改名撞他图（排除自身）→ MapNameConflictError
        ③ 改挂根地点: 新地点不存在/跨项目 → MapRootLocationNotFoundError；
           该地点已被他图挂载 → MapRootLocationConflictError；null=改全局图

        Args:
            map_id: 地图主键（支持 int 或 UUID）.
            update: 更新 DTO（root_location_id None=不修改；出现且 null=改全局图）.

        Returns:
            更新后的 WorldMap；地图不存在返回 None.

        Raises:
            MapNameConflictError: 改名撞他图（422）.
            MapRootLocationNotFoundError: 新根地点不存在或跨项目（422）.
            MapRootLocationConflictError: 新根地点已被他图挂载（422）.
        """
        sid = _to_int_id(map_id)
        existing = await self._repo.get(sid)
        if existing is None:
            return None
        # ② 改名冲突（排除自身）
        if "name" in update.model_fields_set and update.name is not None:
            dup = await self._repo.get_by_name(_to_int_id(existing.project_id), update.name)
            if dup is not None and dup.id != existing.id:
                raise MapNameConflictError()
        # ③ 根地点改挂校验
        if "root_location_id" in update.model_fields_set and update.root_location_id is not None:
            new_int = _to_int_id(update.root_location_id)
            loc = await self._world_repo.get(new_int)
            if loc is None or _to_int_id(loc.project_id) != _to_int_id(existing.project_id):
                raise MapRootLocationNotFoundError()
            dups, _ = await self._repo.list(
                _to_int_id(existing.project_id), root_location_id=new_int
            )
            if dups and dups[0].id != existing.id:
                raise MapRootLocationConflictError()
        # ④ 合并（出现即更新；root_location_id 保持 UUID，仓储层负责 int 转换）
        updates = {k: v for k, v in update.model_dump(exclude_unset=True).items() if v is not None}
        if "root_location_id" in update.model_fields_set:
            updates["root_location_id"] = update.root_location_id
        merged = existing.model_copy(update=updates)
        return await self._repo.update(merged)

    async def replace_image(
        self,
        map_id: int | uuid.UUID,
        image_filename: str,
        image_content: bytes,
    ) -> WorldMap | None:
        """换图（先写新成功后删旧，spec §5.1 D5 原子性）.

        Args:
            map_id: 地图主键（支持 int 或 UUID）.
            image_filename: 新图片文件名（扩展名决定存储格式）.
            image_content: 新图片字节内容.

        Returns:
            更新后的 WorldMap；地图不存在返回 None.

        Raises:
            MapAssetError: 新图写入失败（旧文件与 DB 均不动，透传）.
        """
        sid = _to_int_id(map_id)
        existing = await self._repo.get(sid)
        if existing is None:
            return None
        # ② 先写新文件（失败透传——旧文件与 DB 不动）
        new_rel = await self._asset_store.save(
            map_id=existing.id, filename=image_filename, content=image_content
        )
        # ③ 更新 DB 成功后才删旧文件（update 失败 → 不删旧文件，保证旧图仍可用）
        updated = existing.model_copy(update={"image_path": new_rel, "updated_at": _utcnow()})
        updated_map = await self._repo.update(updated)
        if updated_map is not None:
            await self._delete_image(existing.image_path)
        return updated_map

    async def delete_map(
        self,
        map_id: int | uuid.UUID,
        cascade: bool = False,
        reparent_to: int | uuid.UUID | None = None,
    ) -> bool:
        """真删地图（D6 参数矩阵，spec §5.3）.

        - 无子: 真删自身 + 图片文件
        - 有子且未指定 cascade/reparent_to → MapChildrenActionRequiredError
        - cascade=True: 递归收集整棵子树（children DFS 含自身）→ delete_many
          单事务 + 逐图删文件（文件删除失败 log warning 不阻断）
        - reparent_to=<map_id>: 直接子图改挂新父（树平移靠 pin 转移，子图
          root_location_id 不变）→ 目标自动补 pin（D3，默认居中 + 地点名）
          → 真删自身 + 自身图片文件（子图文件保留）

        Args:
            map_id: 地图主键（支持 int 或 UUID）.
            cascade: True = 递归级联删除整棵子树.
            reparent_to: 目标父地图 UUID；子图 pin 改挂后删除自身.

        Returns:
            是否删除成功（无子场景地图不存在返回 False；router 转 404）.

        Raises:
            MapChildrenActionRequiredError: 有子且未指定动作（422）.
            MapReparentTargetError: 目标不存在/跨项目/是自身子孙（422）.
        """
        sid = _to_int_id(map_id)
        direct_children = await self._repo.children(sid)
        if cascade:
            return await self._delete_cascade(sid, direct_children)
        if reparent_to is not None:
            return await self._delete_reparent(sid, direct_children, reparent_to)
        if direct_children:
            raise MapChildrenActionRequiredError()
        existing = await self._repo.get(sid)
        if existing is None:
            return False
        await self._repo.delete(sid)
        await self._delete_image(existing.image_path)
        return True

    async def children(self, map_id: int | uuid.UUID) -> list[WorldMap]:
        """查询本图 pin 关联地点的子地图（drill-down；地点软删过滤由 repo 保证）."""
        return await self._repo.children(_to_int_id(map_id))

    # ── 删除辅助（D6 分支）────────────────────────────────────────

    async def _delete_cascade(self, sid: int, direct_children: list[WorldMap]) -> bool:
        """cascade 分支: 递归子树集合 → delete_many 单事务 → 逐图删文件."""
        # 自身文件路径先取（先 DB 后文件；删后 repo.get 将查不到自身）
        self_map = await self._repo.get(sid)
        subtree_ids: list[int] = [sid]
        subtree_maps: list[WorldMap] = []
        frontier = direct_children
        while frontier:
            next_frontier: list[WorldMap] = []
            for child in frontier:
                subtree_ids.append(child.id.int)
                subtree_maps.append(child)
                next_frontier.extend(await self._repo.children(child.id.int))
            frontier = next_frontier
        await self._repo.delete_many(subtree_ids)
        if self_map is not None:
            await self._delete_image(self_map.image_path)
        for child in subtree_maps:
            await self._delete_image(child.image_path)
        return True

    async def _delete_reparent(
        self,
        sid: int,
        direct_children: list[WorldMap],
        reparent_to: int | uuid.UUID,
    ) -> bool:
        """reparent 分支: 子图 pin 改挂新父（D3 自动补 pin）→ 真删自身."""
        target_int = _to_int_id(reparent_to)
        target = await self._repo.get(target_int)
        existing = await self._repo.get(sid)
        if target is None:
            raise MapReparentTargetError()
        if existing is None:
            return False
        if _to_int_id(target.project_id) != _to_int_id(existing.project_id):
            raise MapReparentTargetError()
        # ② 目标在自身子树（递归 children）→ 拒绝（防环）
        subtree_ids = {sid}
        frontier = direct_children
        while frontier:
            next_frontier: list[WorldMap] = []
            for child in frontier:
                subtree_ids.add(child.id.int)
                next_frontier.extend(await self._repo.children(child.id.int))
            frontier = next_frontier
        if target_int in subtree_ids:
            raise MapReparentTargetError()
        # ③ 直接子图改挂: 目标已有同地点 pin 则复用；否则自动补 pin（居中 + 地点名）
        target_pins = await self._repo.list_pins(target_int)
        now = _utcnow()
        for child in direct_children:
            b = child.root_location_id
            if b is None:
                continue
            b_int = _to_int_id(b)
            if any(
                p.location_id is not None and _to_int_id(p.location_id) == b_int
                for p in target_pins
            ):
                continue
            loc = await self._world_repo.get(b_int)
            label = loc.name if loc is not None else ""
            await self._repo.add_pin(
                MapPin(
                    id=uuid.uuid4(),
                    map_id=uuid.UUID(int=target_int),
                    location_id=b,
                    x=50.0,
                    y=50.0,
                    label=label,
                    created_at=now,
                    updated_at=now,
                )
            )
        # ④ 真删自身（repo.delete 显式级联其 pins）+ 删自身文件（子图文件保留）
        await self._repo.delete(sid)
        await self._delete_image(existing.image_path)
        return True

    async def _delete_image(self, relative_path: str) -> None:
        """删除地图图片文件；失败 log warning 不阻断（文件层异常不外抛）."""
        try:
            await self._asset_store.delete(relative_path)
        except Exception:
            logger.warning("地图图片文件删除失败: %s", relative_path, exc_info=True)

    # ── pin CRUD ────────────────────────────────────────────────

    async def add_pin(
        self,
        map_id: int | uuid.UUID,
        location_id: int | uuid.UUID | None = None,
        x: float = 0.0,
        y: float = 0.0,
        label: str = "",
        type: str = "location",
        ref_id: int | uuid.UUID | None = None,
    ) -> MapPin:
        """添加 pin（F43 P2: type/ref_id 关联校验 + 位置校验）.

        Args:
            map_id: 地图主键（支持 int 或 UUID）.
            location_id: 关联地点 UUID；None = 纯注释 pin.
            x/y: 坐标（0-100，DTO 层校验）.
            label: 显示标签.
            type: F43 P2 pin 类型（location/role/event/other，默认 location）.
            ref_id: F43 P2 type=role/event 关联实体 UUID（与 location_id 二选一）.

        Returns:
            持久化后的 MapPin.

        Raises:
            MapNotFoundError: 地图不存在（404）.
            MapBgSourceError: type 非法（非 location/role/event/other）（422）.
            MapPinRefNotFoundError: role/event 关联实体不存在或跨项目（422）.
            MapPinLocationNotFoundError: 地点不存在或跨项目（422）.
        """
        sid = _to_int_id(map_id)
        wm = await self._repo.get(sid)
        if wm is None:
            raise MapNotFoundError()
        if type not in {"location", "role", "event", "other"}:
            raise MapBgSourceError()
        # F43 P2: role/event 关联校验（未注入对应 repo 时跳过校验仅透传，D-17）
        ref_int = _to_int_id(ref_id) if ref_id is not None else None
        if type == "role" and self._character_repo is not None:
            char = await self._character_repo.get(ref_int) if ref_int is not None else None
            if char is None or _to_int_id(char.project_id) != _to_int_id(wm.project_id):
                raise MapPinRefNotFoundError()
        elif type == "event" and self._timeline_repo is not None:
            event = await self._timeline_repo.get(ref_int) if ref_int is not None else None
            if event is None or _to_int_id(event.project_id) != _to_int_id(wm.project_id):
                raise MapPinRefNotFoundError()
        loc_int = _to_int_id(location_id) if location_id is not None else None
        if loc_int is not None:
            loc = await self._world_repo.get(loc_int)
            if loc is None or _to_int_id(loc.project_id) != _to_int_id(wm.project_id):
                raise MapPinLocationNotFoundError()
        now = _utcnow()
        pin = MapPin(
            id=uuid.uuid4(),
            map_id=uuid.UUID(int=sid),
            location_id=uuid.UUID(int=loc_int) if loc_int is not None else None,
            x=x,
            y=y,
            label=label,
            type=type,
            ref_id=uuid.UUID(int=ref_int) if ref_int is not None else None,
            created_at=now,
            updated_at=now,
        )
        return await self._repo.add_pin(pin)

    async def list_pins(
        self, map_id: int | uuid.UUID, location_id: int | uuid.UUID | None = None
    ) -> list[MapPin]:
        """透传 repo.list_pins；location_id 提供时内存过滤（本地量级；repo 契约单参）."""
        pins = await self._repo.list_pins(_to_int_id(map_id))
        if location_id is not None:
            loc_int = _to_int_id(location_id)
            pins = [
                p
                for p in pins
                if p.location_id is not None and _to_int_id(p.location_id) == loc_int
            ]
        return pins

    async def update_pin(self, pin_id: int | uuid.UUID, update: MapPinUpdate) -> MapPin | None:
        """部分更新 pin（exclude_unset 语义；父侧裁定 2026-08-09 编排）.

        ① repo.get_pin(pin_id) → None → 返回 None（router 转 404）
        ② location_id 出现且非 None → world_repo.get 校验（不存在 → MapPinLocationNotFoundError）
        ③ model_copy 合并 → repo.update_pin(完整 MapPin)
        """
        pid = _to_int_id(pin_id)
        existing = await self._repo.get_pin(pid)
        if existing is None:
            return None
        if "location_id" in update.model_fields_set and update.location_id is not None:
            loc = await self._world_repo.get(_to_int_id(update.location_id))
            if loc is None:
                raise MapPinLocationNotFoundError()
        updates = {k: v for k, v in update.model_dump(exclude_unset=True).items() if v is not None}
        if "location_id" in update.model_fields_set:
            updates["location_id"] = update.location_id  # 出现即更新（null=转纯注释 pin）
        if "ref_id" in update.model_fields_set:
            updates["ref_id"] = update.ref_id  # F43 P2: 出现即更新（null=清关联）
        merged = existing.model_copy(update=updates)
        return await self._repo.update_pin(merged)

    async def delete_pin(self, pin_id: int | uuid.UUID) -> bool:
        """真删 pin（透传 repo.delete_pin；不存在返回 False）."""
        return await self._repo.delete_pin(_to_int_id(pin_id))

    # ── 项目/地点硬删钩子（D10=b）────────────────────────────────

    async def cleanup_project(self, project_id: int | uuid.UUID) -> int:
        """项目硬删钩子（D10=b）: 单事务删项目全部 maps+pins，再逐图删文件.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.

        Returns:
            删除的地图数量（文件删除失败 log warning 不阻断）.
        """
        pid_int = _to_int_id(project_id)
        maps = await self._repo.list_maps_by_project(pid_int)
        await self._repo.delete_by_project(pid_int)
        for m in maps:
            await self._delete_image(m.image_path)
        return len(maps)

    async def clear_location_pins(self, location_ids: list[uuid.UUID]) -> int:
        """地点硬删钩子（D10=b）: 解除地点关联 pin（SET NULL，pin 保留，label 不变）.

        Args:
            location_ids: 待解除关联的地点 UUID 列表.

        Returns:
            累计更新行数.
        """
        total = 0
        for location_id in location_ids:
            total += await self._repo.clear_location_pins(_to_int_id(location_id))
        return total
