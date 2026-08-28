"""#744 chat 消息仓储测试 — SQLiteChatMessageRepository（真实 in-memory SQLite 轨）。

契约（见 .hermes/plans/contract-744.md）:
- add(message) 绑 conversation_id + project_id
- create_conversation(project_id) -> Conversation（落库）
- get_active_conversation(project_id) -> Conversation | None（最近未归档）
- list_by_conversation(conversation_id, offset, limit) -> (items, total)
- list_conversations(include_deleted=False) -> list[dict]（按 conversation 分组）
- archive_message / force_delete_message / restore_message（消息级）
- archive_conversation / force_delete_conversation / restore_conversation（会话级）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.infrastructure.database.repositories.chat_message_repo import (
    SQLiteChatMessageRepository,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# 小值 UUID：int 必须 ≤ SQLite INTEGER 上限（2^63-1）——128 位 uuid4 会 OverflowError
PROJECT_ID = uuid.UUID(int=1)
PROJECT_ID_2 = uuid.UUID(int=2)
CONV_ID = uuid.UUID(int=101)
CONV_ID_2 = uuid.UUID(int=102)
CONV_ID_3 = uuid.UUID(int=103)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（镜像既有 repo 测试形态）。"""

    # 惰性导入必须在 create_all 之前——Base.metadata 需先注册表
    from inkflow.infrastructure.database.models.chat_message import (  # noqa: F401
        ChatMessageORM,
    )
    from inkflow.infrastructure.database.models.conversation import (  # noqa: F401
        ConversationORM,
    )
    from inkflow.infrastructure.database.models.project import (  # noqa: F401
        ProjectORM,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_conversation_orm(
    *, project_id: uuid.UUID = PROJECT_ID, is_deleted: bool = False
) -> object:
    """构造 ConversationORM（惰性 import；落库用）。"""
    from inkflow.infrastructure.database.models.conversation import ConversationORM

    return ConversationORM(project_id=project_id.int, is_deleted=is_deleted)


def _make_message(
    *,
    project_id: uuid.UUID = PROJECT_ID,
    conversation_id: uuid.UUID = CONV_ID,
    role: str = "user",
    content: str = "你好，请续写第三章。",
    intent: str | None = None,
    created_at: datetime | None = None,
):
    """构造 ChatMessage 领域对象（惰性 import；conversation_id 必填）。"""
    from inkflow.domain.models.chat_message import ChatMessage

    return ChatMessage(
        id=uuid.uuid4(),
        project_id=project_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        intent=intent,
        created_at=created_at or datetime.now(UTC),
    )


async def _create_conv(db, *, project_id=PROJECT_ID, is_deleted=False) -> uuid.UUID:
    """经 repo.create_conversation 建线程，返回其 domain UUID。"""
    repo = SQLiteChatMessageRepository(db)
    conv = await repo.create_conversation(project_id)
    return conv.id


class TestChatMessageCreateValidation:
    """DTO 校验分支（coverage 补测：>10000 字符分支）。"""

    async def test_content_too_long_raises(self):
        from inkflow.domain.models.chat_message import ChatMessageCreate

        with pytest.raises(ValueError, match="不能超过 10000"):
            ChatMessageCreate(
                project_id=PROJECT_ID, conversation_id=CONV_ID, role="user", content="x" * 10001
            )

    async def test_content_blank_raises(self):
        from inkflow.domain.models.chat_message import ChatMessageCreate

        with pytest.raises(ValueError, match="chat 消息内容不能为空"):
            ChatMessageCreate(
                project_id=PROJECT_ID, conversation_id=CONV_ID, role="user", content="   "
            )


class TestAdd:
    """add — 落库 + conversation_id/int↔UUID 转换 + intent 透传。"""

    async def test_add_persists_and_returns_entity(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        msg = _make_message(content="第一条", intent="conversation")

        created = await repo.add(msg)

        assert isinstance(created.id, uuid.UUID)
        assert created.project_id == PROJECT_ID
        assert created.conversation_id == CONV_ID
        assert created.content == "第一条"
        assert created.intent == "conversation"
        assert created.created_at.tzinfo is not None
        items, total = await repo.list_by_conversation(CONV_ID)
        assert total == 1
        assert items[0].content == "第一条"
        assert items[0].id == created.id

    async def test_add_intent_none_default(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message())
        assert created.intent is None


class TestConversationLifecycle:
    """create_conversation / get_active_conversation — 线程生命周期。"""

    async def test_create_conversation_returns_entity(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        conv = await repo.create_conversation(PROJECT_ID)
        assert isinstance(conv.id, uuid.UUID)
        assert conv.project_id == PROJECT_ID
        assert conv.is_deleted is False
        assert conv.created_at.tzinfo is not None

    async def test_get_active_conversation_returns_most_recent_not_archived(
        self, db_session
    ):
        repo = SQLiteChatMessageRepository(db_session)
        await repo.create_conversation(PROJECT_ID)  # conv A
        await repo.create_conversation(PROJECT_ID)  # conv B
        active = await repo.get_active_conversation(PROJECT_ID)
        assert active is not None
        assert active.is_deleted is False

    async def test_get_active_conversation_none_when_all_archived(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        cid = await _create_conv(db_session)
        await repo.archive_conversation(cid)
        assert await repo.get_active_conversation(PROJECT_ID) is None

    async def test_get_active_conversation_none_when_no_conversation(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        assert await repo.get_active_conversation(PROJECT_ID) is None


class TestListByConversation:
    """list_by_conversation — 线程过滤 + 升序 + 分页 + 总数。"""

    async def _seed(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        base = datetime(2026, 8, 20, 8, 0, 0, tzinfo=UTC)
        for i, content in enumerate(["第一", "第二", "第三"]):
            await repo.add(
                _make_message(content=content, created_at=base.replace(hour=8 + i))
            )
        await repo.add(
            _make_message(project_id=PROJECT_ID_2, conversation_id=CONV_ID_2, content="另一线程")
        )
        return repo

    async def test_filters_by_conversation_asc_order(self, db_session):
        repo = await self._seed(db_session)
        items, total = await repo.list_by_conversation(CONV_ID)
        assert total == 3
        assert [m.content for m in items] == ["第一", "第二", "第三"]  # created_at 升序

    async def test_pagination(self, db_session):
        repo = await self._seed(db_session)
        items, total = await repo.list_by_conversation(CONV_ID, offset=1, limit=2)
        assert total == 3
        assert [m.content for m in items] == ["第二", "第三"]

    async def test_empty_conversation(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        items, total = await repo.list_by_conversation(CONV_ID)
        assert items == []
        assert total == 0


class TestListConversations:
    """list_conversations — 按 conversation 分组（多线程/project）+ project_name join + 降序。"""

    async def _seed(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        base = datetime(2026, 8, 20, 8, 0, 0, tzinfo=UTC)
        # conv A（project1）：3 条
        await repo.add(_make_message(content="第一", created_at=base.replace(hour=8)))
        await repo.add(_make_message(content="第二", created_at=base.replace(hour=9)))
        await repo.add(
            _make_message(
                content="第三", role="ai", intent="content", created_at=base.replace(hour=10)
            )
        )
        # conv B（project2）：1 条（时间 09:30 → conv A 最新在前）
        await repo.add(
            _make_message(
                project_id=PROJECT_ID_2,
                conversation_id=CONV_ID_2,
                content="另一线程",
                created_at=base.replace(hour=9, minute=30),
            )
        )
        return repo

    async def test_aggregates_per_conversation_sorted_desc(self, db_session):
        repo = await self._seed(db_session)
        convs = await repo.list_conversations()

        assert len(convs) == 2
        # 降序：conv A（10:00）在前
        assert convs[0]["conversation_id"] == str(CONV_ID)
        assert convs[0]["project_id"] == str(PROJECT_ID)
        assert convs[0]["message_count"] == 3
        assert convs[0]["last_message"] == "第三"
        assert convs[0]["is_deleted"] is False
        assert convs[1]["conversation_id"] == str(CONV_ID_2)
        assert convs[1]["message_count"] == 1
        assert convs[0]["project_name"] is None
        assert convs[0]["updated_at"].startswith("2026-08-20T10:00:00")

    async def test_multiple_conversations_same_project_shown_separately(
        self, db_session
    ):
        """#744 核心：同一项目两个线程 → 列表输出两个卡（各 count/updated_at 独立）。"""
        repo = SQLiteChatMessageRepository(db_session)
        await repo.add(
            _make_message(
                content="线程A消息",
                created_at=datetime(2026, 8, 20, 8, 0, 0, tzinfo=UTC),
            )
        )
        await repo.add(
            _make_message(
                conversation_id=CONV_ID_3,
                content="线程B消息",
                created_at=datetime(2026, 8, 20, 9, 0, 0, tzinfo=UTC),
            )
        )
        convs = await repo.list_conversations()
        assert len(convs) == 2
        by_id = {c["conversation_id"]: c for c in convs}
        assert by_id[str(CONV_ID)]["message_count"] == 1
        assert by_id[str(CONV_ID)]["last_message"] == "线程A消息"
        assert by_id[str(CONV_ID_3)]["message_count"] == 1
        assert by_id[str(CONV_ID_3)]["last_message"] == "线程B消息"

    async def test_project_name_join(self, db_session):
        from inkflow.infrastructure.database.models.project import ProjectORM

        repo = await self._seed(db_session)
        db_session.add(ProjectORM(id=PROJECT_ID.int, name="测试项目"))
        await db_session.commit()

        convs = await repo.list_conversations()
        p1 = next(c for c in convs if c["conversation_id"] == str(CONV_ID))
        assert p1["project_name"] == "测试项目"

    async def test_empty(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        assert await repo.list_conversations() == []

    async def test_list_conversations_excludes_archived(self, db_session):
        """默认不显示归档线程（conversations.is_deleted=True）。"""
        repo = SQLiteChatMessageRepository(db_session)
        await repo.add(_make_message(content="将归档"))
        await repo.archive_conversation(CONV_ID)
        convs = await repo.list_conversations()
        assert not any(c["conversation_id"] == str(CONV_ID) for c in convs)

    async def test_list_conversations_include_deleted_true(self, db_session):
        """#744 include_deleted=True → 含归档线程（会话页恢复入口）。"""
        repo = SQLiteChatMessageRepository(db_session)
        await repo.add(_make_message(content="将归档"))
        await repo.archive_conversation(CONV_ID)
        convs = await repo.list_conversations(include_deleted=True)
        archived = next(c for c in convs if c["conversation_id"] == str(CONV_ID))
        assert archived["is_deleted"] is True

    async def test_list_conversations_is_deleted_from_conversation_flag(self, db_session):
        """#744 is_deleted 由图 conversation.is_deleted 决定（不再从消息计数推导）。"""
        repo = SQLiteChatMessageRepository(db_session)
        # conv A：1 条活动
        await repo.add(_make_message(content="活动"))
        # conv B：1 条 → 归档
        await repo.add(_make_message(conversation_id=CONV_ID_2, content="已归档"))
        await repo.archive_conversation(CONV_ID_2)

        convs = await repo.list_conversations(include_deleted=True)
        by_id = {c["conversation_id"]: c for c in convs}
        assert by_id[str(CONV_ID)]["is_deleted"] is False
        assert by_id[str(CONV_ID_2)]["is_deleted"] is True


class TestArchiveDeleteRestoreMessage:
    """消息级两级删除 — archive / force_delete / restore。"""

    async def test_archive_soft_deletes_and_list_excludes(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message(content="待归档"))
        _items, total = await repo.list_by_conversation(CONV_ID)
        assert total == 1

        ok = await repo.archive_message(created.id.int)
        assert ok is True

        items, total = await repo.list_by_conversation(CONV_ID)
        assert total == 0
        assert items == []

    async def test_archive_not_found_false(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        assert await repo.archive_message(999_999) is False

    async def test_force_delete_removes_row(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message(content="待真删"))
        ok = await repo.force_delete_message(created.id.int)
        assert ok is True
        _items, total = await repo.list_by_conversation(CONV_ID)
        assert total == 0

    async def test_restore_reappears_in_list(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message(content="待恢复"))
        await repo.archive_message(created.id.int)
        assert (await repo.list_by_conversation(CONV_ID))[1] == 0

        restored = await repo.restore_message(created.id.int)
        assert restored is not None
        assert restored.id == created.id
        assert restored.is_deleted is False
        items, total = await repo.list_by_conversation(CONV_ID)
        assert total == 1
        assert items[0].content == "待恢复"


class TestConversationLevelArchive:
    """#744 会话级（per-conversation）归档/真删/恢复。"""

    async def test_archive_conversation_marks_messages_and_flag(self, db_session):
        """archive_conversation → conversation.is_deleted=True + 其消息 is_deleted=True。"""
        repo = SQLiteChatMessageRepository(db_session)
        await repo.add(_make_message(content="一"))
        await repo.add(_make_message(content="二"))
        ok = await repo.archive_conversation(CONV_ID)
        assert ok is True
        # 消息全归档 → list_by_conversation 为空
        assert (await repo.list_by_conversation(CONV_ID))[1] == 0
        # 列表默认隐藏，include_deleted 可见且 is_deleted=True
        convs = await repo.list_conversations(include_deleted=True)
        archived = next(c for c in convs if c["conversation_id"] == str(CONV_ID))
        assert archived["is_deleted"] is True

    async def test_archive_conversation_not_found_false(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        assert await repo.archive_conversation(uuid.UUID(int=999_999)) is False

    async def test_force_delete_conversation_removes_messages(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        await repo.add(_make_message(content="一"))
        await repo.add(_make_message(content="二"))
        ok = await repo.force_delete_conversation(CONV_ID)
        assert ok is True
        assert (await repo.list_by_conversation(CONV_ID))[1] == 0
        assert not any(
            c["conversation_id"] == str(CONV_ID)
            for c in await repo.list_conversations(include_deleted=True)
        )

    async def test_restore_conversation_unarchives(self, db_session):
        """restore_conversation → conversation.is_deleted=False + 消息 is_deleted=False。"""
        repo = SQLiteChatMessageRepository(db_session)
        await repo.add(_make_message(content="一"))
        await repo.archive_conversation(CONV_ID)
        assert (await repo.list_by_conversation(CONV_ID))[1] == 0

        ok = await repo.restore_conversation(CONV_ID)
        assert ok is True
        assert (await repo.list_by_conversation(CONV_ID))[1] == 1
        convs = await repo.list_conversations()
        p1 = next(c for c in convs if c["conversation_id"] == str(CONV_ID))
        assert p1["is_deleted"] is False

    async def test_restore_conversation_not_archived_false(self, db_session):
        """未归档线程 restore → False（无副作用）。"""
        repo = SQLiteChatMessageRepository(db_session)
        assert await repo.restore_conversation(CONV_ID) is False


class TestChatMessageAssemblyAndOrm:
    """覆盖率补测：get_chat_message_service 真实装配 + ORM 默认值/__repr__。"""

    async def test_get_chat_message_service_assembly(self, db_session):
        from inkflow.api.routers.chat_messages import get_chat_message_service
        from inkflow.domain.services.chat_message_service import ChatMessageService

        svc = get_chat_message_service(db_session)
        assert isinstance(svc, ChatMessageService)

    async def test_orm_created_at_default_and_repr(self, db_session):
        from inkflow.infrastructure.database.models.chat_message import ChatMessageORM

        orm = ChatMessageORM(
            project_id=PROJECT_ID.int,
            conversation_id=CONV_ID.int,
            role="user",
            content="hi",
        )
        db_session.add(orm)
        await db_session.commit()
        assert orm.created_at is not None
        assert "ChatMessageORM" in repr(orm)

    async def test_conversation_orm_repr(self, db_session):
        from inkflow.infrastructure.database.models.conversation import ConversationORM

        orm = ConversationORM(project_id=PROJECT_ID.int)
        db_session.add(orm)
        await db_session.commit()
        assert "ConversationORM" in repr(orm)

    async def test_repo_utcnow_helper(self):
        from inkflow.infrastructure.database.repositories.chat_message_repo import _utcnow

        assert _utcnow().tzinfo is not None
        assert _utcnow().tzinfo.utcoffset(_utcnow()) == timedelta(0)

    async def test_domain_model_utcnow_helper(self):
        from inkflow.domain.models.chat_message import _utcnow

        assert _utcnow().tzinfo is not None
