"""章节仓储端口 — 定义 Volume/Chapter 持久化操作的契约.

ChapterRepositoryProtocol 使用 typing.Protocol 实现结构化子类型（static duck typing），
基础设施层（SQLAlchemy / mock / memory）实现这些方法即可自动满足接口要求。
"""

from __future__ import annotations

from typing import Protocol

from inkflow.domain.models.chapter import Chapter, ChapterStatus, Volume


class ChapterRepositoryProtocol(Protocol):
    """章节仓储端口 — 定义 Volume/Chapter 持久化操作的契约."""

    # ---- Volume ----

    async def add_volume(self, volume: Volume) -> Volume:
        """新增卷.

        Args:
            volume: 待创建的卷实体.

        Returns:
            持久化后的完整 Volume（含 id 等自动生成字段）.
        """
        ...

    async def get_volume(self, volume_id: int) -> Volume | None:
        """根据主键获取卷.

        Args:
            volume_id: 卷主键.

        Returns:
            若找到则返回 Volume，否则返回 None.
        """
        ...

    async def list_volumes(self, project_id: int) -> list[Volume]:
        """列举项目的所有卷，按 order_index 升序排列.

        Args:
            project_id: 项目主键.

        Returns:
            属于该项目的 Volume 列表.
        """
        ...

    async def update_volume(self, volume: Volume) -> Volume:
        """更新卷.

        Args:
            volume: 包含新数据的卷实体（主键 id 标识待更新行）.

        Returns:
            更新后的完整 Volume.
        """
        ...

    async def delete_volume(self, volume_id: int) -> bool:
        """物理删除卷（级联删除所属章节）.

        Args:
            volume_id: 待删除的卷主键.

        Returns:
            True 表示成功删除一条记录，False 表示未找到记录.
        """
        ...

    async def get_next_volume_order(self, project_id: int) -> float:
        """获取项目下一个卷的顺序值.

        通常取项目内最大 order_index + 1，若项目无卷则返回 0.0.

        Args:
            project_id: 项目主键.

        Returns:
            可用的下一个 order_index 值.
        """
        ...

    # ---- Chapter ----

    async def add_chapter(self, chapter: Chapter) -> Chapter:
        """新增章节.

        Args:
            chapter: 待创建的章节实体.

        Returns:
            持久化后的完整 Chapter（含 id, created_at 等自动生成字段）.
        """
        ...

    async def get_chapter(self, chapter_id: int) -> Chapter | None:
        """根据主键获取章节.

        Args:
            chapter_id: 章节主键.

        Returns:
            若找到则返回 Chapter，否则返回 None.
        """
        ...

    async def list_chapters(
        self,
        project_id: int,
        volume_id: int | None = None,
        status: ChapterStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Chapter], int]:
        """分页列举章节，支持按卷筛选和状态筛选.

        Args:
            project_id: 项目主键.
            volume_id: 按卷筛选，None 表示不过滤.
            status: 按状态筛选，None 表示不过滤.
            offset: 偏移量，默认为 0.
            limit: 每页条数，默认为 50.

        Returns:
            (当前页章节列表, 符合条件的总记录数).
        """
        ...

    async def update_chapter(self, chapter: Chapter) -> Chapter:
        """更新章节.

        Args:
            chapter: 包含新数据的章节实体（主键 id 标识待更新行）.

        Returns:
            更新后的完整 Chapter.
        """
        ...

    async def delete_chapter(self, chapter_id: int) -> bool:
        """物理删除章节.

        Args:
            chapter_id: 待删除的章节主键.

        Returns:
            True 表示成功删除一条记录，False 表示未找到记录.
        """
        ...

    async def move_chapter(self, chapter_id: int, target_volume_id: int | None) -> Chapter | None:
        """移动章节到目标卷（或置为无卷归属）.

        Args:
            chapter_id: 待移动的章节主键.
            target_volume_id: 目标卷主键，None 表示移出卷.

        Returns:
            移动后的 Chapter，若章节不存在则返回 None.
        """
        ...

    async def get_next_chapter_order(self, project_id: int, volume_id: int | None = None) -> float:
        """获取项目（或卷内）下一个章节的顺序值.

        通常取指定范围内最大 order_index + 1，若无匹配则返回 0.0.

        Args:
            project_id: 项目主键.
            volume_id: 卷主键，None 表示取项目全局顺序值.

        Returns:
            可用的下一个 order_index 值.
        """
        ...

    async def get_project_word_count(self, project_id: int) -> int:
        """获取项目所有章节的字数总和.

        Args:
            project_id: 项目主键.

        Returns:
            字数总和.
        """
        ...

    async def get_volume_word_count(self, volume_id: int) -> int:
        """获取卷内所有章节的字数总和.

        Args:
            volume_id: 卷主键.

        Returns:
            字数总和.
        """
        ...
