"""F36 地图仓储端口 — 地图与 pin 持久化契约（真删语义，无软删列）.

依据: specs/f36-world-map/spec.md §5.4 + 父侧定稿契约。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.map import MapPin, WorldMap


class MapRepositoryProtocol(Protocol):
    """地图仓储端口.

    maps/map_pins 均【无 is_deleted】——所有删除为真删。FK 级联/SET NULL
    由 service 显式执行（D10=b，生产连接未开 foreign_keys=ON），repo 的
    delete/delete_many/delete_by_project 在单事务内显式删 pins。
    注: 方法名 list 遮蔽内置 list，返回注解用 builtins.list。
    """

    async def add(self, map: WorldMap) -> WorldMap:
        """插入新地图.

        Args:
            map: 待持久化的地图（id 为领域 UUID）.

        Returns:
            持久化后的 WorldMap（id 为 ORM 层映射回读的 UUID）.
        """
        ...

    async def get(self, map_id: int) -> WorldMap | None:
        """按主键查询地图.

        Args:
            map_id: 地图主键（int，与 ORM 层一致）.

        Returns:
            命中返回 WorldMap，否则返回 None.
        """
        ...

    async def get_by_name(self, project_id: int, name: str) -> WorldMap | None:
        """按项目内地图名查询.

        Args:
            project_id: 项目主键（int）.
            name: 地图名（已去空白）.

        Returns:
            命中返回 WorldMap，否则返回 None.
        """
        ...

    async def list(
        self,
        project_id: int,
        root_location_id: int | None = None,
        top_level_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[WorldMap], int]:
        """分页查询项目内地图列表，过滤三态.

        过滤组合（spec §3.1 Q3=A + 父侧定稿）:
        - root_location_id=None + top_level_only=False = 不过滤（全量）
        - top_level_only=True = 只返回全局图（root_location_id IS NULL）
        - root_location_id 非 None = 精确过滤（忽略 top_level_only）

        Args:
            project_id: 项目主键（int）.
            root_location_id: 根地点精确过滤（可选）.
            top_level_only: True 只返回全局图（root_location_id IS NULL）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (地图列表, 总数) 元组，按 created_at DESC 排序.
        """
        ...

    async def update(self, map: WorldMap) -> WorldMap | None:
        """更新地图（按 id 定位全字段覆盖）.

        Args:
            map: 含待更新字段的完整地图对象.

        Returns:
            持久化后的 WorldMap；地图不存在返回 None.
        """
        ...

    async def delete(self, map_id: int) -> bool:
        """真删地图（单事务显式级联删 pins）.

        单事务: DELETE map_pins WHERE map_id=? + DELETE maps WHERE id=?
        （D10=b，显式级联，不依赖 DB FK 动作）.

        Args:
            map_id: 地图主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    async def delete_many(self, map_ids: builtins.list[int]) -> int:
        """单事务按 id 集合真删多张地图（先删 pins 再删 maps 行）.

        Args:
            map_ids: 地图主键列表（int）.

        Returns:
            删除的 maps 行数（列表含不存在 id 不影响计数；空列表 = 0）.
        """
        ...

    async def list_pins(self, map_id: int) -> builtins.list[MapPin]:
        """列出地图全部 pin.

        Args:
            map_id: 地图主键（int）.

        Returns:
            pin 列表，按 created_at ASC 排序.
        """
        ...

    async def add_pin(self, pin: MapPin) -> MapPin:
        """插入新 pin.

        Args:
            pin: 待持久化的 pin（id 为领域 UUID，map_id 为持久化回读 UUID）.

        Returns:
            持久化后的 MapPin.
        """
        ...

    async def get_pin(self, pin_id: int) -> MapPin | None:
        """按主键查询 pin（update_pin 前置——service 需现有 pin 合并部分更新）.

        Args:
            pin_id: pin 主键（int）.

        Returns:
            命中返回 MapPin，否则 None.
        """
        ...

    async def update_pin(self, pin: MapPin) -> MapPin | None:
        """更新 pin（按 id 定位全字段覆盖）.

        Args:
            pin: 含待更新字段的完整 pin 对象.

        Returns:
            持久化后的 MapPin；pin 不存在返回 None.
        """
        ...

    async def delete_pin(self, pin_id: int) -> bool:
        """真删 pin.

        Args:
            pin_id: pin 主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    async def children(self, map_id: int) -> builtins.list[WorldMap]:
        """查询本图 pin 关联地点的子地图（drill-down，Q1=B）.

        单 SQL: JOIN map_pins p（p.map_id=:id AND p.location_id IS NOT NULL）
        JOIN world_settings w（w.id=p.location_id，v1.1 真删语义无 is_deleted 过滤）
        JOIN maps m2（m2.root_location_id=p.location_id）;
        DISTINCT; ORDER BY created_at ASC.

        Args:
            map_id: 地图主键（int）.

        Returns:
            子地图列表，按 created_at ASC 排序.
        """
        ...

    async def list_by_root_locations(
        self,
        project_id: int,
        location_ids: builtins.list[int],
        include_global: bool = True,
    ) -> builtins.list[WorldMap]:
        """按根地点集合查地图（#175 跨书复制共用查询；include_global=True 含全局图）.

        Args:
            project_id: 项目主键（int）.
            location_ids: 根地点主键列表（int）.
            include_global: True 时附加 root_location_id IS NULL 的全局图（Q3=B）.

        Returns:
            命中地图列表；空列表入参 + include_global=False → 空列表.
        """
        ...

    async def list_maps_by_project(self, project_id: int) -> builtins.list[WorldMap]:
        """收集项目全部地图（项目硬删钩子 cleanup 用）.

        Args:
            project_id: 项目主键（int）.

        Returns:
            项目内全部地图列表.
        """
        ...

    async def delete_by_project(self, project_id: int) -> int:
        """单事务真删项目全部地图（先删 pins 再删 maps 行）.

        Args:
            project_id: 项目主键（int）.

        Returns:
            删除的 maps 行数（D10=b 项目硬删钩子）.
        """
        ...

    async def clear_location_pins(self, location_id: int) -> int:
        """解除地点关联 pin（UPDATE map_pins SET location_id=NULL）.

        pin 保留、label 不变（D10=b 地点硬删钩子，SET NULL 由 service 显式执行）.

        Args:
            location_id: 地点主键（int）.

        Returns:
            更新行数.
        """
        ...

    async def clear_ref_pins(self, ref_type: str, ref_ids: builtins.list[int]) -> int:
        """解除角色/事件关联 pin（UPDATE map_pins SET ref_id=NULL
        WHERE type=:t AND ref_id IN :ids）.

        pin 保留、label 不变（F43 P5 角色/事件硬删钩子，SET NULL 由 service
        显式执行，生产 foreign_keys=OFF 下不依赖 FK）.

        Args:
            ref_type: pin 类型（role/event）.
            ref_ids: 待解除关联的实体主键列表（int）.

        Returns:
            更新行数.
        """
        ...

    async def clear_map_root_locations(self, location_ids: builtins.list[int]) -> int:
        """解除地图根地点关联（UPDATE maps SET root_location_id=NULL
        WHERE root_location_id IN :ids）.

        F43 P5 地点硬删钩子扩展: 地点删除后其挂载图 root_location_id 置 NULL
        （图保留，仅解除根地点关联）.

        Args:
            location_ids: 待解除关联的地点主键列表（int）.

        Returns:
            更新行数.
        """
        ...
