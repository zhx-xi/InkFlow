"""章节服务层集成测试 — 真实 in-memory SQLite。

测试范围：ChapterService 业务逻辑（创建卷/章节、状态更新、移动、删除）。
需 pytest marker: @pytest.mark.chapter
"""

import pytest

from inkflow.domain.models.chapter import ChapterStatus, ChapterUpdate
from inkflow.domain.services.chapter_service import ChapterService


class TestChapterService:
    """ChapterService 业务逻辑测试."""

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_create_volume_auto_order(self, db_session, sample_project):
        """不传 order_index → 自动计算."""
        svc = ChapterService(db_session)
        v1 = await svc.create_volume(sample_project.id, "卷一")
        v2 = await svc.create_volume(sample_project.id, "卷二")
        assert v1.order_index == 1.0
        assert v2.order_index == 2.0

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_create_chapter_auto_word_count(self, db_session, sample_project):
        """创建章节 → 自动计算字数."""
        svc = ChapterService(db_session)
        ch = await svc.create_chapter(sample_project.id, "第一章", content="你好abc")
        assert ch.word_count == 3  # 2 CJK + 1 EN

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_update_status_history(self, db_session, sample_project):
        """更新状态 → status_history 追加记录."""
        svc = ChapterService(db_session)
        ch = await svc.create_chapter(sample_project.id, "st", content="x")
        assert ch.status == ChapterStatus.DRAFT

        updated = await svc.update_chapter(
            ch.id, ChapterUpdate(status=ChapterStatus.WRITING)
        )
        assert updated is not None
        assert updated.status == ChapterStatus.WRITING
        assert len(updated.status_history) == 1

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_move_chapter(self, db_session, sample_project):
        """跨卷移动 → volume_id 变更."""
        svc = ChapterService(db_session)
        v1 = await svc.create_volume(sample_project.id, "V1")
        v2 = await svc.create_volume(sample_project.id, "V2")
        ch = await svc.create_chapter(
            sample_project.id, "移动", volume_id=v1.id, content="x"
        )

        moved = await svc.move_chapter(ch.id, v2.id)
        assert moved is not None
        assert moved.volume_id == v2.id

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_delete_volume_with_chapters_raises_volume_not_empty(self, db_session, sample_project):
        """#648 新语义：卷下有章节且未指定处理方式 → 抛 VolumeNotEmptyError（禁止静默解绑）."""
        from inkflow.domain.services.chapter_service import VolumeNotEmptyError

        svc = ChapterService(db_session)
        v = await svc.create_volume(sample_project.id, "临时")
        ch = await svc.create_chapter(
            sample_project.id, "孤儿", volume_id=v.id, content="x"
        )

        with pytest.raises(VolumeNotEmptyError):
            await svc.delete_volume(v.id)
        # 卷未被删除，章节仍在原卷
        ch_after = await svc.get_chapter(ch.id)
        assert ch_after is not None
        assert ch_after.volume_id == v.id

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_list_chapters_filtered(self, db_session, sample_project):
        """按状态筛选 → 只返回匹配项."""
        svc = ChapterService(db_session)
        c1 = await svc.create_chapter(sample_project.id, "c1", content="x")
        await svc.update_chapter(c1.id, ChapterUpdate(status=ChapterStatus.FINAL))

        items, total = await svc.list_chapters(
            sample_project.id, status=ChapterStatus.FINAL
        )
        assert total == 1
        assert items[0].status == ChapterStatus.FINAL
