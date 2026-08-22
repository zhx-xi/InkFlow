"""#547 chat 消息仓储测试 — SQLiteChatMessageRepository（真实 in-memory SQLite 轨）。

coverage 补测（#562 CI：chat_message_repo.py 33% → 补齐 add/list/conversations 全路径）：
- API 测试 mock service、service 测试用 fake repo——真实仓储此前零测试触达；
  本文件用 in-memory SQLite（create_async_engine + Base.metadata.create_all，镜像
  test_semantic_summary_repo.py db_session 形态）覆盖真实 SQL 路径：
  add（int↔UUID 转换/落库）、list_by_project（过滤/升序/分页/总数）、
  list_conversations（聚合 last_message/count/updated_at + projects join + 降序）。
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

# 小值 UUID：int 必须 ≤ SQLite INTEGER 上限（2^63-1）——128 位 uuid4 会
# OverflowError: Python int too large to convert to SQLite INTEGER（F48 已知坑）
PROJECT_ID = uuid.UUID(int=1)
PROJECT_ID_2 = uuid.UUID(int=2)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（镜像既有 repo 测试形态）。"""

    # 惰性导入必须在 create_all 之前——Base.metadata 需先注册表
    from inkflow.infrastructure.database.models.chat_message import (  # noqa: F401  # 惰性导入触发 Base.metadata 表注册（create_all 需要）
        ChatMessageORM,
    )
    from inkflow.infrastructure.database.models.project import (  # noqa: F401  # 惰性导入触发 Base.metadata 表注册（conversations join 需要）
        ProjectORM,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_message(
    *,
    project_id: uuid.UUID = PROJECT_ID,
    role: str = "user",
    content: str = "你好，请续写第三章。",
    intent: str | None = None,
    created_at: datetime | None = None,
):
    """构造 ChatMessage 领域对象（惰性 import；id 缺省 uuid4）。"""
    from inkflow.domain.models.chat_message import ChatMessage

    return ChatMessage(
        id=uuid.uuid4(),
        project_id=project_id,
        role=role,
        content=content,
        intent=intent,
        created_at=created_at or datetime.now(UTC),
    )


class TestChatMessageCreateValidation:
    """DTO 校验分支（coverage 补测：>10000 字符分支）。"""

    async def test_content_too_long_raises(self):
        from inkflow.domain.models.chat_message import ChatMessageCreate

        with pytest.raises(ValueError, match="不能超过 10000"):
            ChatMessageCreate(project_id=PROJECT_ID, role="user", content="x" * 10001)

    async def test_content_blank_raises(self):
        from inkflow.domain.models.chat_message import ChatMessageCreate

        with pytest.raises(ValueError, match="chat 消息内容不能为空"):
            ChatMessageCreate(project_id=PROJECT_ID, role="user", content="   ")


class TestAdd:
    """add — 落库 + int↔UUID 转换 + intent 透传。"""

    async def test_add_persists_and_returns_entity(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        msg = _make_message(content="第一条", intent="conversation")

        created = await repo.add(msg)

        assert isinstance(created.id, uuid.UUID)
        assert created.project_id == PROJECT_ID
        assert created.content == "第一条"
        assert created.intent == "conversation"
        assert created.created_at.tzinfo is not None
        # 落库可回读（总数 1）
        items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 1
        assert items[0].content == "第一条"
        assert items[0].id == created.id

    async def test_add_intent_none_default(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message())
        assert created.intent is None


class TestListByProject:
    """list_by_project — 项目过滤 + 升序 + 分页 + 总数。"""

    async def _seed(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        base = datetime(2026, 8, 20, 8, 0, 0, tzinfo=UTC)
        for i, content in enumerate(["第一", "第二", "第三"]):
            await repo.add(_make_message(content=content, created_at=base.replace(hour=8 + i)))
        await repo.add(_make_message(project_id=PROJECT_ID_2, content="另一项目"))
        return repo

    async def test_filters_by_project_asc_order(self, db_session):
        repo = await self._seed(db_session)
        items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 3
        assert [m.content for m in items] == ["第一", "第二", "第三"]  # created_at 升序

    async def test_pagination(self, db_session):
        repo = await self._seed(db_session)
        items, total = await repo.list_by_project(PROJECT_ID, offset=1, limit=2)
        assert total == 3
        assert [m.content for m in items] == ["第二", "第三"]

    async def test_empty_project(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        items, total = await repo.list_by_project(PROJECT_ID)
        assert items == []
        assert total == 0


class TestListConversations:
    """list_conversations — 按项目聚合（最新消息/条数/更新时间）+ project_name join + 降序。"""

    async def _seed(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        base = datetime(2026, 8, 20, 8, 0, 0, tzinfo=UTC)
        # P1：3 条（最新 content=第三，时间 10:00）
        await repo.add(_make_message(content="第一", created_at=base.replace(hour=8)))
        await repo.add(_make_message(content="第二", created_at=base.replace(hour=9)))
        await repo.add(
            _make_message(
                content="第三", role="ai", intent="content", created_at=base.replace(hour=10)
            )
        )
        # P2：1 条（时间 09:30 → P1 最新在前）
        await repo.add(
            _make_message(
                project_id=PROJECT_ID_2,
                content="另一项目",
                created_at=base.replace(hour=9, minute=30),
            )
        )
        return repo

    async def test_aggregates_per_project_sorted_desc(self, db_session):
        repo = await self._seed(db_session)
        convs = await repo.list_conversations()

        assert len(convs) == 2
        # 降序：P1（10:00）在前
        assert convs[0]["project_id"] == str(PROJECT_ID)
        assert convs[0]["message_count"] == 3
        assert convs[0]["last_message"] == "第三"
        assert convs[1]["project_id"] == str(PROJECT_ID_2)
        assert convs[1]["message_count"] == 1
        # project_name 可空（无 projects 行）
        assert convs[0]["project_name"] is None
        # updated_at 为 ISO 字符串
        assert convs[0]["updated_at"].startswith("2026-08-20T10:00:00")

    async def test_project_name_join(self, db_session):
        from inkflow.infrastructure.database.models.project import ProjectORM

        repo = await self._seed(db_session)
        # 显式插入 projects 行（id = message.project_id.int 才能 join 命中）
        db_session.add(ProjectORM(id=PROJECT_ID.int, name="测试项目"))
        await db_session.commit()

        convs = await repo.list_conversations()
        p1 = next(c for c in convs if c["project_id"] == str(PROJECT_ID))
        assert p1["project_name"] == "测试项目"

    async def test_empty(self, db_session):
        repo = SQLiteChatMessageRepository(db_session)
        assert await repo.list_conversations() == []

    async def test_list_conversations_include_deleted_true(self, db_session):
        """#581 include_deleted=True → 聚合包含已归档项目（会话页恢复入口）。

        镜像 sessions 的 include_deleted 先例：默认排除已归档，
        include_deleted=true 时活动 + 归档全量返回。
        """
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message(content="将归档"))
        await repo.archive(created.id.int)

        convs = await repo.list_conversations(include_deleted=True)

        assert any(c["project_id"] == str(PROJECT_ID) for c in convs)

    async def test_list_conversations_is_deleted_flag(self, db_session):
        """#581 聚合结果带 is_deleted 标志（镜像 sessions.is_deleted 语义，归档视图区分用）。

        判定 = 该项目聚合的消息是否全部 is_deleted（archive_by_project 整轮归档语义）：
        - 活动项目（有任一活动消息）→ is_deleted=False
        - 归档项目（全部消息已归档）→ is_deleted=True
        """
        repo = SQLiteChatMessageRepository(db_session)
        # P1：1 条活动消息
        await repo.add(_make_message(content="活动"))
        # P2：1 条消息 → 归档
        archived = await repo.add(
            _make_message(project_id=PROJECT_ID_2, content="已归档")
        )
        await repo.archive(archived.id.int)

        convs = await repo.list_conversations(include_deleted=True)
        by_id = {c["project_id"]: c for c in convs}
        assert by_id[str(PROJECT_ID)]["is_deleted"] is False
        assert by_id[str(PROJECT_ID_2)]["is_deleted"] is True


class TestArchiveDeleteRestore:
    """#566 两级删除 — archive / force_delete / restore + is_deleted 过滤。

    契约（镜像 SQLiteSessionRepository soft_delete/restore/hard_delete）:
    - archive(message_id: int) -> bool（软删 is_deleted=true；False = 不存在/已归档）
    - force_delete(message_id: int) -> bool（真删；False = 不存在）
    - restore(message_id: int) -> ChatMessage | None（解除归档；None = 不存在/未归档）
    - list_by_project / list_conversations 过滤已归档（is_deleted=false）

    RED 预期: repo 无 archive/force_delete/restore 方法 + domain ChatMessage 无
    is_deleted 字段 + list_by_project 无 is_deleted 过滤 → 本类用例 FAILED。
    """

    async def test_archive_soft_deletes_and_list_excludes(self, db_session):
        """archive → is_deleted=true；list_by_project 不再返回该条。"""
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message(content="待归档"))
        # list_by_project 仍含（未归档）
        _items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 1

        ok = await repo.archive(created.id.int)
        assert ok is True

        items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 0
        assert items == []

    async def test_archive_not_found_false(self, db_session):
        """archive 不存在的 id → False。"""
        repo = SQLiteChatMessageRepository(db_session)
        assert await repo.archive(999_999) is False

    async def test_archive_already_archived_false(self, db_session):
        """已归档消息再次 archive → False（幂等，镜像 session soft_delete）。"""
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message(content="待归档"))
        assert await repo.archive(created.id.int) is True
        assert await repo.archive(created.id.int) is False

    async def test_force_delete_removes_row(self, db_session):
        """force_delete → 物理删除；list_by_project 不再返回。"""
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message(content="待真删"))
        ok = await repo.force_delete(created.id.int)
        assert ok is True
        _items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 0

    async def test_force_delete_not_found_false(self, db_session):
        """force_delete 不存在的 id → False。"""
        repo = SQLiteChatMessageRepository(db_session)
        assert await repo.force_delete(999_999) is False

    async def test_restore_reappears_in_list(self, db_session):
        """archive → restore → list_by_project 重新包含该条。"""
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message(content="待恢复"))
        await repo.archive(created.id.int)
        assert (await repo.list_by_project(PROJECT_ID))[1] == 0

        restored = await repo.restore(created.id.int)
        assert restored is not None
        assert restored.id == created.id
        assert restored.is_deleted is False
        items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 1
        assert items[0].content == "待恢复"

    async def test_restore_not_found_none(self, db_session):
        """restore 不存在的 id → None。"""
        repo = SQLiteChatMessageRepository(db_session)
        assert await repo.restore(999_999) is None

    async def test_restore_not_archived_none(self, db_session):
        """restore 未归档消息 → None（无副作用，镜像 session restore）。"""
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message(content="活跃"))
        assert await repo.restore(created.id.int) is None

    async def test_list_conversations_excludes_archived(self, db_session):
        """list_conversations 聚合排除已归档消息（is_deleted=false）。"""
        repo = SQLiteChatMessageRepository(db_session)
        created = await repo.add(_make_message(content="将归档"))
        # 归档前聚合含 1 条
        convs_before = await repo.list_conversations()
        assert any(c["project_id"] == str(PROJECT_ID) for c in convs_before)

        await repo.archive(created.id.int)
        convs_after = await repo.list_conversations()
        assert not any(c["project_id"] == str(PROJECT_ID) for c in convs_after)


class TestArchiveDeleteByProject:
    """#566 会话级（per-project）归档/真删 — archive_by_project / force_delete_by_project。"""

    async def test_archive_by_project_marks_all(self, db_session):
        """archive_by_project 归档整项目活跃消息，返回受影响行数。"""
        repo = SQLiteChatMessageRepository(db_session)
        await repo.add(_make_message(content="一"))
        await repo.add(_make_message(content="二"))
        n = await repo.archive_by_project(PROJECT_ID.int)
        assert n == 2
        _items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 0

    async def test_archive_by_project_only_active(self, db_session):
        """archive_by_project 仅归档未归档消息（已归档不计入）。"""
        repo = SQLiteChatMessageRepository(db_session)
        c1 = await repo.add(_make_message(content="一"))
        await repo.archive(c1.id.int)  # 已归档
        await repo.add(_make_message(content="二"))
        n = await repo.archive_by_project(PROJECT_ID.int)
        assert n == 1  # 仅「二」被归档

    async def test_force_delete_by_project(self, db_session):
        """force_delete_by_project 物理删除整项目消息，返回受影响行数。"""
        repo = SQLiteChatMessageRepository(db_session)
        await repo.add(_make_message(content="一"))
        await repo.add(_make_message(content="二"))
        n = await repo.force_delete_by_project(PROJECT_ID.int)
        assert n == 2
        _items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 0


class TestRestoreByProject:
    """#587 会话级恢复 — restore_by_project 解除整项目归档（is_deleted=false）。

    契约（镜像 archive_by_project 反操作，服务层 restore_conversation 的 repo 落点）:
    - restore_by_project(project_id: int) -> int
      （整项目 is_deleted=true → false；返回受影响行数；0 = 无已归档消息）
    - 恢复后 list_conversations 重新包含该项目且 is_deleted=false；
      list_by_project 重新返回消息（is_deleted 过滤解除）。

    RED 预期: repo 无 restore_by_project 方法 → AttributeError
    （'SQLiteChatMessageRepository' object has no attribute 'restore_by_project'）
    → 本类用例 FAILED。
    """

    async def test_restore_by_project_restores_whole_project(self, db_session):
        """归档后 restore_by_project 使整项目 list_conversations 恢复（is_deleted=false）。"""
        repo = SQLiteChatMessageRepository(db_session)
        await repo.add(_make_message(content="一"))
        await repo.add(_make_message(content="二"))
        await repo.archive_by_project(PROJECT_ID.int)
        # 归档后默认聚合排除该项目
        assert not any(
            c["project_id"] == str(PROJECT_ID) for c in await repo.list_conversations()
        )

        n = await repo.restore_by_project(PROJECT_ID.int)
        assert n == 2
        convs = await repo.list_conversations()
        p1 = next(c for c in convs if c["project_id"] == str(PROJECT_ID))
        assert p1["is_deleted"] is False
        # list_by_project 同步恢复（is_deleted 过滤解除）
        items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 2
        assert [m.content for m in items] == ["一", "二"]

    async def test_restore_by_project_only_archived(self, db_session):
        """restore_by_project 仅解除已归档消息（活跃消息不受影响，行数只计已归档）。"""
        repo = SQLiteChatMessageRepository(db_session)
        c1 = await repo.add(_make_message(content="一"))
        await repo.add(_make_message(content="二"))
        await repo.archive(c1.id.int)  # 仅归档「一」

        n = await repo.restore_by_project(PROJECT_ID.int)
        assert n == 1  # 仅「一」被恢复
        convs = await repo.list_conversations()
        p1 = next(c for c in convs if c["project_id"] == str(PROJECT_ID))
        assert p1["is_deleted"] is False
        _items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 2


class TestChatMessageAssemblyAndOrm:
    """#566 覆盖率补测：get_chat_message_service 真实装配 + ORM 默认值/__repr__。"""

    async def test_get_chat_message_service_assembly(self, db_session):
        """get_chat_message_service(真实 session) → ChatMessageService 实例（#177 L33 覆盖）。"""
        from inkflow.api.routers.chat_messages import get_chat_message_service
        from inkflow.domain.services.chat_message_service import ChatMessageService

        svc = get_chat_message_service(db_session)
        assert isinstance(svc, ChatMessageService)

    async def test_orm_created_at_default_and_repr(self, db_session):
        """ChatMessageORM 不传 created_at → 默认 _utcnow；__repr__ 可用（#177 L14/L38 覆盖）。"""
        from inkflow.infrastructure.database.models.chat_message import ChatMessageORM

        orm = ChatMessageORM(project_id=PROJECT_ID.int, role="user", content="hi")
        db_session.add(orm)
        await db_session.commit()
        assert orm.created_at is not None
        assert "ChatMessageORM" in repr(orm)

    async def test_repo_utcnow_helper(self):
        """chat_message_repo._utcnow 返回 UTC 时区感知时间（#576 coverage 补测 L20）。"""
        from inkflow.infrastructure.database.repositories.chat_message_repo import _utcnow

        assert _utcnow().tzinfo is not None
        assert _utcnow().tzinfo.utcoffset(_utcnow()) == timedelta(0)

    async def test_domain_model_utcnow_helper(self):
        """chat_message 领域模型 _utcnow 返回 UTC 时区感知时间（#576 coverage 补测 L13）。"""
        from inkflow.domain.models.chat_message import _utcnow

        assert _utcnow().tzinfo is not None
