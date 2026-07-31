"""章节仓储层集成测试 — 真实 in-memory SQLite。

测试范围：VolumeORM / ChapterORM 模型、ChapterRepository CRUD 操作。
需 pytest marker: @pytest.mark.chapter
"""

import uuid

import pytest


class TestVolumeORM:
    """Volume ORM 集成测试."""

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_create_volume(self, db_session, sample_project):
        """创建卷 → 查询返回 title='第一卷'."""
        from inkflow.infrastructure.database.models.chapter import VolumeORM

        vol = VolumeORM(
            project_id=sample_project.id,
            title="第一卷",
            order_index=1.0,
        )
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        assert vol.id is not None
        assert vol.title == "第一卷"
        assert vol.order_index == 1.0


class TestChapterORM:
    """Chapter ORM 集成测试."""

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_create_chapter(self, db_session, sample_project):
        """创建章节 → 查询返回 title='第一章'."""
        from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM

        vol = VolumeORM(
            project_id=sample_project.id,
            title="卷A",
            order_index=0.0,
        )
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        ch = ChapterORM(
            project_id=sample_project.id,
            volume_id=vol.id,
            title="第一章",
            content="你好世界",
            status="draft",
            order_index=1.0,
        )
        db_session.add(ch)
        await db_session.commit()
        await db_session.refresh(ch)

        assert ch.id is not None
        assert ch.title == "第一章"
        assert ch.status == "draft"


class TestChapterRepository:
    """ChapterRepository 集成测试（真实 in-memory SQLite）."""

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_add_and_get_volume(self, db_session, sample_project):
        """创建卷 → 查询返回 title='第一卷'."""
        from inkflow.domain.models.chapter import Volume
        from inkflow.infrastructure.database.repositories.chapter_repo import (
            SQLiteChapterRepository,
        )

        repo = SQLiteChapterRepository(db_session)
        vol = Volume(
            id=uuid.uuid4(),
            project_id=uuid.UUID(int=sample_project.id),
            title="第一卷",
            order_index=1.0,
        )
        result = await repo.add_volume(vol)
        assert result.title == "第一卷"

        fetched = await repo.get_volume(result.id.int)
        assert fetched is not None
        assert fetched.title == "第一卷"

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_add_chapter_auto_word_count(self, db_session, sample_project):
        """创建章节 → 自动计算字数."""
        from inkflow.domain.models.chapter import Chapter
        from inkflow.infrastructure.database.repositories.chapter_repo import (
            SQLiteChapterRepository,
        )

        repo = SQLiteChapterRepository(db_session)
        ch = Chapter(
            id=uuid.uuid4(),
            project_id=uuid.UUID(int=sample_project.id),
            title="第一章",
            content="测试内容",
            order_index=1.0,
        )
        result = await repo.add_chapter(ch)
        assert result.title == "第一章"
        assert result.word_count == 4

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_list_volumes(self, db_session, sample_project):
        """列出卷 → 返回 2 个，按 order_index 升序."""
        from inkflow.domain.models.chapter import Volume
        from inkflow.infrastructure.database.repositories.chapter_repo import (
            SQLiteChapterRepository,
        )

        repo = SQLiteChapterRepository(db_session)
        await repo.add_volume(
            Volume(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=sample_project.id),
                title="A",
                order_index=2.0,
            )
        )
        await repo.add_volume(
            Volume(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=sample_project.id),
                title="B",
                order_index=1.0,
            )
        )

        volumes = await repo.list_volumes(sample_project.id)
        assert len(volumes) == 2
        assert volumes[0].title == "B"

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_move_chapter(self, db_session, sample_project):
        """跨卷移动 → volume_id 变更."""
        from inkflow.domain.models.chapter import Chapter, Volume
        from inkflow.infrastructure.database.repositories.chapter_repo import (
            SQLiteChapterRepository,
        )

        repo = SQLiteChapterRepository(db_session)
        v1 = await repo.add_volume(
            Volume(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=sample_project.id),
                title="V1",
                order_index=0,
            )
        )
        v2 = await repo.add_volume(
            Volume(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=sample_project.id),
                title="V2",
                order_index=1,
            )
        )
        ch = await repo.add_chapter(
            Chapter(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=sample_project.id),
                volume_id=v1.id,
                title="移动章节",
                content="test",
                order_index=0,
            )
        )

        moved = await repo.move_chapter(ch.id.int, v2.id.int)
        assert moved is not None
        assert moved.volume_id == v2.id

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_update_status_tracks_history(self, db_session, sample_project):
        """状态变更 → status_history 追加记录."""
        from inkflow.domain.models.chapter import Chapter, ChapterStatus
        from inkflow.infrastructure.database.repositories.chapter_repo import (
            SQLiteChapterRepository,
        )

        repo = SQLiteChapterRepository(db_session)
        ch = await repo.add_chapter(
            Chapter(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=sample_project.id),
                title="状态测试",
                content="test",
                status=ChapterStatus.DRAFT,
                order_index=0,
            )
        )
        ch.status = ChapterStatus.WRITING
        updated = await repo.update_chapter(ch)
        assert updated.status == ChapterStatus.WRITING
        assert len(updated.status_history) == 1
        assert updated.status_history[0].from_status == ChapterStatus.DRAFT
        assert updated.status_history[0].to_status == ChapterStatus.WRITING

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_delete_volume_orphans_chapters(self, db_session, sample_project):
        """删除卷 → 章节 volume_id 变 None."""
        from inkflow.domain.models.chapter import Chapter, Volume
        from inkflow.infrastructure.database.repositories.chapter_repo import (
            SQLiteChapterRepository,
        )

        repo = SQLiteChapterRepository(db_session)
        vol = await repo.add_volume(
            Volume(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=sample_project.id),
                title="临时",
                order_index=0,
            )
        )
        ch = await repo.add_chapter(
            Chapter(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=sample_project.id),
                volume_id=vol.id,
                title="孤儿",
                content="test",
                order_index=0,
            )
        )

        ok = await repo.delete_volume(vol.id.int)
        assert ok is True

        ch_after = await repo.get_chapter(ch.id.int)
        assert ch_after is not None
        assert ch_after.volume_id is None

    @pytest.mark.asyncio
    @pytest.mark.chapter
    async def test_project_word_count(self, db_session, sample_project):
        """项目总字数 = 所有章节字数之和."""
        from inkflow.domain.models.chapter import Chapter
        from inkflow.infrastructure.database.repositories.chapter_repo import (
            SQLiteChapterRepository,
        )

        repo = SQLiteChapterRepository(db_session)
        await repo.add_chapter(
            Chapter(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=sample_project.id),
                title="c1",
                content="测试",
                order_index=0,
            )
        )
        await repo.add_chapter(
            Chapter(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=sample_project.id),
                title="c2",
                content="hello world",
                order_index=1,
            )
        )

        total = await repo.get_project_word_count(sample_project.id)
        assert total == 4  # 2 CJK + 2 EN
