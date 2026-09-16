"""#1200 抽出的「大纲查询 / 章对象构造」mixin（book_service 超 900 行护栏）.

与 `BookRunMixin` 同构：承载 `BookService` 的内部分解方法，避免主文件突破
`ci_cd/check_file_length.py` 的 900 行硬上限（AGENTS.md §10.5）。纯搬移，零行为变更。

- `_to_chapter_dicts`：Outline 列表 → 章 dict，补章级写作要求真实列值（#1200）
- `_find_chapters` / `_find_volumes` / `_find_outline_node`：大纲节点查询
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, cast

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import WritingPlan

if TYPE_CHECKING:  # 循环导入防护：章 dict 类型定义于 book_service
    from inkflow.domain.services.book_service import ChapterDict, VolumeGroup


class BookOutlineMixin:
    async def _to_chapter_dicts(
        self, outlines: list[Outline], *, volume_outline_id: uuid.UUID | None = None
    ) -> list[ChapterDict]:
        """Outline 列表 → 章 dict 列表，**补上章级写作要求真实列值**（#1200）.

        `chapters.writing_requirements` 是 GUI 章级栏的真实存储；`_outline_to_chapter_dict`
        是纯函数取不到 DB，故在此按 `outline.chapter_id` 逐章取列值传入
        （getter 未装配 / 章无关联 / 列值为空 → 回退 `outline.extra`，不破既有断言）。
        """
        # 函数体 import：避免与 book_service 模块级循环依赖（转换函数定义于彼）
        from inkflow.domain.services.book_service import _outline_to_chapter_dict

        getter = self._chapter_requirements_getter  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
        out: list[ChapterDict] = []
        for o in outlines:
            requirements: str | None = None
            if getter is not None and o.chapter_id is not None:
                try:
                    requirements = await getter(o.chapter_id)
                except Exception:  # 列不可达 → 回退，绝不炸编排
                    requirements = None
            out.append(
                _outline_to_chapter_dict(
                    o, volume_outline_id=volume_outline_id, writing_requirements=requirements
                )
            )
        return out

    async def _find_chapters(self, plan: WritingPlan) -> list[Outline]:
        """取全部 level=chapter 节点，按 sort_order 升序（阶段 2 顺序派发，§5.2）.
        无 outline_repo → 空列表.
        """
        if self._outline_repo is None:  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            return []
        outlines_raw, _ = await self._outline_repo.list(  # type: ignore[attr-defined]  # 鸭子类型：outline_repo 按 OutlineRepositoryProtocol 提供 list
            plan.project_id
        )
        outlines: list[Outline] = cast(list[Outline], outlines_raw)
        chapters = [o for o in outlines if o.level == "chapter"]
        return sorted(chapters, key=lambda o: (o.sort_order, str(o.id)))

    async def _find_volumes(self, plan: WritingPlan) -> list[VolumeGroup]:
        """卷 planner 拆章：level=volume 节点 + 其下 chapter 子节点按卷分组
        （volume_outline_id 透传卷节点 id）；无卷节点 → 整本书一卷（root）."""
        if self._outline_repo is None:  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            return []
        outlines_raw, _ = await self._outline_repo.list(  # type: ignore[attr-defined]  # 鸭子类型：outline_repo 按 OutlineRepositoryProtocol 提供 list
            plan.project_id
        )
        outlines: list[Outline] = cast(list[Outline], outlines_raw)
        volume_nodes = sorted(
            (o for o in outlines if o.level == "volume"),
            key=lambda o: (o.sort_order, str(o.id)),
        )
        if volume_nodes:
            groups: list[VolumeGroup] = []
            for volume in volume_nodes:
                children = sorted(
                    (o for o in outlines if o.level == "chapter" and o.parent_id == volume.id),
                    key=lambda o: (o.sort_order, str(o.id)),
                )
                groups.append(
                    {
                        "volume_id": volume.id,
                        "chapters": await self._to_chapter_dicts(
                            children, volume_outline_id=volume.id
                        ),
                    }
                )
            return groups
        chapters = sorted(
            (o for o in outlines if o.level == "chapter"),
            key=lambda o: (o.sort_order, str(o.id)),
        )
        return [
            {
                "volume_id": plan.root_outline_id,
                "chapters": await self._to_chapter_dicts(chapters),
            }
        ]

    async def _find_outline_node(self, plan: WritingPlan, target: str) -> Outline | None:
        """按 outline_id 查大纲节点（无 outline_repo/非法 UUID/缺失 → None）."""
        if self._outline_repo is None:  # type: ignore[attr-defined]  # 混入类：属性由 BookService 提供
            return None
        outlines_raw, _ = await self._outline_repo.list(  # type: ignore[attr-defined]  # 鸭子类型：outline_repo 按 OutlineRepositoryProtocol 提供 list
            plan.project_id
        )
        outlines: list[Outline] = cast(list[Outline], outlines_raw)
        try:
            target_uuid = uuid.UUID(target)
        except ValueError:
            return None
        return next((o for o in outlines if o.id == target_uuid), None)
