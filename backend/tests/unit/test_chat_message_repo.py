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
from datetime import UTC, datetime

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
