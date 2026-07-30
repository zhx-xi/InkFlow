"""章节领域模型测试 — TDD RED 阶段."""

import uuid

import pytest
from pydantic import ValidationError


class TestChapterStatus:
    """ChapterStatus 枚举测试."""

    def test_enum_values(self):
        from inkflow.domain.models.chapter import ChapterStatus

        assert ChapterStatus.DRAFT == "draft"
        assert ChapterStatus.WRITING == "writing"
        assert ChapterStatus.REVIEW == "review"
        assert ChapterStatus.FINAL == "final"


class TestVolumeCreateValidation:
    """VolumeCreate DTO 验证测试."""

    def test_create_valid(self):
        from inkflow.domain.models.chapter import VolumeCreate

        v = VolumeCreate(title="第一卷")
        assert v.title == "第一卷"

    def test_create_empty_title_raises(self):
        from inkflow.domain.models.chapter import VolumeCreate

        with pytest.raises(ValidationError, match="卷标题不能为空"):
            VolumeCreate(title="")

    def test_create_whitespace_title_raises(self):
        from inkflow.domain.models.chapter import VolumeCreate

        with pytest.raises(ValidationError, match="卷标题不能为空"):
            VolumeCreate(title="   ")

    def test_create_title_too_long_raises(self):
        from inkflow.domain.models.chapter import VolumeCreate

        with pytest.raises(ValidationError, match="卷标题不能超过 200 个字符"):
            VolumeCreate(title="长" * 201)


class TestChapterCreateValidation:
    """ChapterCreate DTO 验证测试."""

    def test_create_valid(self):
        from inkflow.domain.models.chapter import ChapterCreate

        c = ChapterCreate(title="第一章")
        assert c.title == "第一章"
        assert c.content == ""
        assert c.volume_id is None

    def test_create_empty_title_raises(self):
        from inkflow.domain.models.chapter import ChapterCreate

        with pytest.raises(ValidationError, match="章节标题不能为空"):
            ChapterCreate(title="")

    def test_create_title_too_long_raises(self):
        from inkflow.domain.models.chapter import ChapterCreate

        with pytest.raises(ValidationError, match="章节标题不能超过 500 个字符"):
            ChapterCreate(title="长" * 501)


class TestChapterUpdateValidation:
    """ChapterUpdate DTO 验证测试."""

    def test_update_partial(self):
        from inkflow.domain.models.chapter import ChapterUpdate

        u = ChapterUpdate(title="新标题")
        assert u.title == "新标题"
        assert u.content is None
        assert u.status is None
        assert u.volume_id is None


class TestWordCount:
    """字数统计工具测试."""

    def test_chinese_only(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("测试内容") == 4

    def test_english_only(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("hello world") == 2

    def test_mixed_cn_en(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("你好world测试abc") == 6

    def test_empty(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("") == 0

    def test_markdown_heading(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("## 标题") == 2

    def test_markdown_bold(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("**强调**文字") == 4

    def test_markdown_code_block(self):
        from inkflow.domain.services._word_count import count_words

        text = "```python\nprint('hello')\n```\n正文"
        assert count_words(text) == 2

    def test_markdown_link(self):
        from inkflow.domain.services._word_count import count_words

        assert count_words("[点击](url)这里") == 4


class TestVolumeORM:
    """Volume ORM 集成测试."""

    @pytest.mark.asyncio
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


class TestChapterService:
    """ChapterService 业务逻辑测试."""

    @pytest.mark.asyncio
    async def test_create_volume_auto_order(self, db_session, sample_project):
        """不传 order_index → 自动计算."""
        from inkflow.domain.services.chapter_service import ChapterService

        svc = ChapterService(db_session)
        v1 = await svc.create_volume(sample_project.id, "卷一")
        v2 = await svc.create_volume(sample_project.id, "卷二")
        assert v1.order_index == 1.0
        assert v2.order_index == 2.0

    @pytest.mark.asyncio
    async def test_create_chapter_auto_word_count(self, db_session, sample_project):
        """创建章节 → 自动计算字数."""
        from inkflow.domain.services.chapter_service import ChapterService

        svc = ChapterService(db_session)
        ch = await svc.create_chapter(sample_project.id, "第一章", content="你好abc")
        assert ch.word_count == 3  # 2 CJK + 1 EN

    @pytest.mark.asyncio
    async def test_update_status_history(self, db_session, sample_project):
        """更新状态 → status_history 追加记录."""
        from inkflow.domain.models.chapter import ChapterStatus, ChapterUpdate
        from inkflow.domain.services.chapter_service import ChapterService

        svc = ChapterService(db_session)
        ch = await svc.create_chapter(sample_project.id, "st", content="x")
        assert ch.status == ChapterStatus.DRAFT

        updated = await svc.update_chapter(ch.id, ChapterUpdate(status=ChapterStatus.WRITING))
        assert updated is not None
        assert updated.status == ChapterStatus.WRITING
        assert len(updated.status_history) == 1

    @pytest.mark.asyncio
    async def test_move_chapter(self, db_session, sample_project):
        """跨卷移动 → volume_id 变更."""
        from inkflow.domain.services.chapter_service import ChapterService

        svc = ChapterService(db_session)
        v1 = await svc.create_volume(sample_project.id, "V1")
        v2 = await svc.create_volume(sample_project.id, "V2")
        ch = await svc.create_chapter(sample_project.id, "移动", volume_id=v1.id, content="x")

        moved = await svc.move_chapter(ch.id, v2.id)
        assert moved is not None
        assert moved.volume_id == v2.id

    @pytest.mark.asyncio
    async def test_delete_volume_orphans(self, db_session, sample_project):
        """删卷 → 章节变未分类."""
        from inkflow.domain.services.chapter_service import ChapterService

        svc = ChapterService(db_session)
        v = await svc.create_volume(sample_project.id, "临时")
        ch = await svc.create_chapter(sample_project.id, "孤儿", volume_id=v.id, content="x")

        await svc.delete_volume(v.id)
        ch_after = await svc.get_chapter(ch.id)
        assert ch_after.volume_id is None

    @pytest.mark.asyncio
    async def test_list_chapters_filtered(self, db_session, sample_project):
        """按状态筛选 → 只返回匹配项."""
        from inkflow.domain.models.chapter import ChapterStatus, ChapterUpdate
        from inkflow.domain.services.chapter_service import ChapterService

        svc = ChapterService(db_session)
        c1 = await svc.create_chapter(sample_project.id, "c1", content="x")
        await svc.update_chapter(c1.id, ChapterUpdate(status=ChapterStatus.FINAL))

        items, total = await svc.list_chapters(sample_project.id, status=ChapterStatus.FINAL)
        assert total == 1
        assert items[0].status == ChapterStatus.FINAL
