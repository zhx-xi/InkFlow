"""F37 世界观跨书复制服务 — 编排条目/地图/pin 复制（spec §5.1）.

职责（spec §5.1/§5.2/§5.3）:
- 复制集合确定：root_setting_id 提供 → list_descendants（含自身层序）；
  缺省 → list_all_active（created_at ASC 稳定排序）
- 名称冲突预筛（目标项目同父同名 → 跳过 + warning，不覆盖目标既有数据）
- 层序落库：父先子后，old→new id 映射顺序建立（子 parent_id 依赖父已落库）
- 地图复制（F36 依赖，map_repo 与 asset_store 均非 None 才执行）：
  关联图 root 重映射 / 全局图保持 NULL（Q3=B）；pin 关联地点在复制集合内
  重映射、集合外（或 NULL）转纯注释（label/坐标保留）+ warning 汇总
- 落库阶段任何 repo 写方法抛错 → 异常原样传播（fail-fast，不吞错）

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:
- repository: WorldRepositoryProtocol（F10/F35）
- project_repo: ProjectRepositoryProtocol（F1，源/目标存在性校验）
- map_repo: MapRepositoryProtocol（F36，可选——未装配时静默跳过地图复制）
- asset_store: MapAssetStoreProtocol（F36，可选）

依据: specs/f37-world-copy/spec.md §5/§7/§9。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from loguru import logger

from inkflow.domain.models.copy import WorldCopyResult
from inkflow.domain.models.map import MapPin, WorldMap
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.map_errors import MapAssetError
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_errors import (
    CopyRootNotFoundError,
    CopySourceNotFoundError,
    ProjectNotFoundError,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.infrastructure.assets.map_asset_store import MapAssetStoreProtocol


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1 `_to_int_id` 模式）."""
    if isinstance(value, uuid.UUID):
        return value.int
    return value


class WorldCopyService:
    """F37 世界观跨书复制业务服务 — 编排跨书复制全流程.

    Args:
        repository: 世界观条目仓储端口（F10/F35）.
        project_repo: 项目仓储端口（F1，源/目标存在性校验）.
        map_repo: 地图仓储端口（F36，可选）；None = 地图复制静默跳过（防御）.
        asset_store: 地图图片资产存储端口（F36，可选）；None = 地图复制静默跳过.
    """

    def __init__(
        self,
        *,
        repository: WorldRepositoryProtocol,
        project_repo: ProjectRepositoryProtocol,
        map_repo: MapRepositoryProtocol | None = None,
        asset_store: MapAssetStoreProtocol | None = None,
    ) -> None:
        self._repo = repository
        self._project_repo = project_repo
        self._map_repo = map_repo
        self._asset_store = asset_store

    async def copy(
        self,
        source_project_id: int | uuid.UUID,
        target_project_id: int | uuid.UUID,
        root_setting_id: int | uuid.UUID | None = None,
        self_only: bool = False,
    ) -> WorldCopyResult:
        """复制源项目世界观到目标项目（spec §5.1 算法 ①-⑧）.

        Args:
            source_project_id: 源项目主键（支持 int 或 UUID）.
            target_project_id: 目标项目主键（支持 int 或 UUID）.
            root_setting_id: 复制起点条目（指定子树）；None = 复制源项目全部活动条目.
            self_only: True = 仅复制 root_setting_id 本体（不含子级）；缺省 False 保持子树语义.

        Returns:
            WorldCopyResult: created=新条目列表, skipped=冲突源条目名,
            maps_created=新图列表, pins_created=复制 pin 数, warnings=警告列表.

        Raises:
            ProjectNotFoundError: 目标项目不存在（404）.
            CopySourceNotFoundError: 源项目不存在（404）.
            CopyRootNotFoundError: 复制起点不存在或不在源项目（404）.
        """
        source_int = _to_int_id(source_project_id)
        target_int = _to_int_id(target_project_id)
        logger.info(
            "世界观跨书复制开始: source=%s target=%s root=%s",
            source_project_id,
            target_project_id,
            root_setting_id,
        )
        # ① 目标项目存在性（ProjectNotFoundError，复用 world_errors）
        if await self._project_repo.get(target_int) is None:
            raise ProjectNotFoundError()
        # ② 源项目存在性（CopySourceNotFoundError）
        if await self._project_repo.get(source_int) is None:
            raise CopySourceNotFoundError()
        # ③ 复制集合：root 提供 → 校验在源项目活动条目内 + list_descendants（含自身层序）；
        #    缺省 → list_all_active（created_at ASC 稳定排序）
        if root_setting_id is not None:
            root_int = _to_int_id(root_setting_id)
            root = await self._repo.get(root_int)
            if root is None or _to_int_id(root.project_id) != source_int:
                raise CopyRootNotFoundError()
            # P1: self_only=True → 仅复制 root 本体（不含子级）
            if self_only:
                copy_set = [root]
            else:
                copy_set = await self._repo.list_descendants(root_int)
        else:
            copy_set = await self._repo.list_all_active(source_int)

        now = _utcnow()
        created: list[WorldSetting] = []
        skipped: list[str] = []
        warnings: list[str] = []
        # old→new id 映射（层序建立；父先于子，子 parent_id 依赖父已落库）
        id_map: dict[int, uuid.UUID] = {}
        # 复制集合源 id → 名称（父被跳过时置顶 warning 取父名用）
        src_ids = {s.id.int for s in copy_set}
        src_names = {s.id.int: s.name for s in copy_set}
        for src in copy_set:
            # 父被跳过/不在集合 → parent_new=None（子置顶层）
            parent_new = id_map.get(src.parent_id.int) if src.parent_id is not None else None
            # ④ 同级同名冲突预筛（target, 映射后父 id, name；父先落库再预筛子）
            conflict = await self._repo.get_by_parent_and_name(
                target_int, parent_new.int if parent_new is not None else None, src.name
            )
            if conflict is not None:
                skipped.append(src.name)
                warnings.append(f"目标项目已存在同名条目「{src.name}」，已跳过")
                logger.warning("复制跳过同名条目: target=%s name=%s", target_project_id, src.name)
                continue  # 不入 id_map、不复制
            # 父条目被跳过（目标同名冲突）→ 子置顶层 + warning（spec §5.2）
            if src.parent_id is not None and parent_new is None and src.parent_id.int in src_ids:
                warnings.append(
                    f"父条目「{src_names[src.parent_id.int]}」已跳过，"
                    f"子条目「{src.name}」已置为顶层"
                )
            # ⑤ 落库：新 UUID + project_id=target + parent 经 old→new 映射 + 字段原样
            new = WorldSetting(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=target_int),
                name=src.name,
                parent_id=parent_new,
                category=src.category,
                content=src.content,
                extra=src.extra,
                created_at=now,
                updated_at=now,
            )
            saved = await self._repo.add(new)
            id_map[src.id.int] = saved.id
            created.append(saved)

        # ⑥ 地图复制（map_repo 与 asset_store 均非 None 才执行；Q3=B 含全局图）
        maps_created: list[WorldMap] = []
        pins_created = 0
        if self._map_repo is not None and self._asset_store is not None:
            copy_ids = [s.id.int for s in copy_set]
            maps = await self._map_repo.list_by_root_locations(
                source_int, copy_ids, include_global=True
            )
            for m in maps:
                # 目标项目同名图 → 跳过 + warning（不覆盖）
                if await self._map_repo.get_by_name(target_int, m.name) is not None:
                    warnings.append(f"目标项目已存在同名地图「{m.name}」，已跳过")
                    logger.warning("复制跳过同名地图: target=%s name=%s", target_project_id, m.name)
                    continue
                # 先复制图片文件（失败 → 该图跳过 + warning，DB 行不复制）
                new_map_id = uuid.uuid4()
                try:
                    new_path = await self._asset_store.copy(m.image_path, map_id=new_map_id)
                except MapAssetError as e:
                    warnings.append(f"地图「{m.name}」图片复制失败，已跳过（{e}）")
                    logger.warning(
                        "地图图片复制失败: source=%s map=%s error=%s",
                        source_project_id,
                        m.name,
                        e,
                    )
                    continue
                new_map = WorldMap(
                    id=new_map_id,
                    project_id=uuid.UUID(int=target_int),
                    name=m.name,
                    image_path=new_path,
                    description=m.description,
                    # 关联图 root 重映射；全局图（root NULL，Q3=B）保持 None
                    root_location_id=(
                        id_map.get(m.root_location_id.int)
                        if m.root_location_id is not None
                        else None
                    ),
                    created_at=now,
                    updated_at=now,
                )
                saved_map = await self._map_repo.add(new_map)
                maps_created.append(saved_map)
                # pins 复制：location ∈ 映射 → 重映射；∉（或 NULL 纯注释）→ 转纯注释
                note_count = 0
                pins = await self._map_repo.list_pins(m.id.int)
                for p in pins:
                    loc_new = id_map.get(p.location_id.int) if p.location_id is not None else None
                    if p.location_id is not None and loc_new is None:
                        note_count += 1
                    pin = MapPin(
                        id=uuid.uuid4(),
                        map_id=saved_map.id,
                        location_id=loc_new,
                        x=p.x,
                        y=p.y,
                        label=p.label,
                        created_at=now,
                        updated_at=now,
                    )
                    await self._map_repo.add_pin(pin)
                    pins_created += 1
                if note_count:
                    warnings.append(
                        f"地图「{m.name}」的 {note_count} 个 pin 关联地点"
                        "不在复制集合，已转为纯注释"
                    )

        logger.info(
            "世界观跨书复制完成: source=%s target=%s created=%d skipped=%d maps=%d pins=%d",
            source_project_id,
            target_project_id,
            len(created),
            len(skipped),
            len(maps_created),
            pins_created,
        )
        # ⑧ 返回复制结果报告
        return WorldCopyResult(
            created=created,
            skipped=skipped,
            maps_created=maps_created,
            pins_created=pins_created,
            warnings=warnings,
        )
