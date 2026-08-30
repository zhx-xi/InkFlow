"""#770 会话页架构 RED 契约：Conversation/ConversationCreate title + 迁移 + repo/service 透传。

被测（spec §17.3 + 任务书，MODIFY 轨：src 均存在，收集成功）：
1. Conversation 领域模型 + ConversationCreate DTO 新增 title（默认 ""，上限 200，去空白）
2. ConversationORM.title 列（String(200)）
3. ensure_conversation_title_column 幂等迁移三形态（对齐 ensure_agent_executions_trace_column 先例）
4. repo.create_conversation(project_id, title="") 落 title + rename_conversation +
   list_conversations items 每项含 title（_conv_to_domain 透传）
5. service.create_conversation 透传 title + rename_conversation

RED 形态（收集成功，逐用例在其最契约相关点失败）：
- Conversation/ConversationCreate 无 title → 构造 TypeError / .title AttributeError
- ensure_conversation_title_column 不存在 → 用例体内惰性 import ImportError
- repo.create_conversation 无 title 参数 → TypeError；rename_conversation 不存在 → AttributeError
- list_conversations items 无 title 键 → KeyError / 断言失败
- ConversationORM 无 title 列 → 断言失败
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from inkflow.domain.models.conversation import Conversation, ConversationCreate
from inkflow.domain.services.chat_message_service import ChatMessageService
from inkflow.infrastructure.database.models.conversation import ConversationORM

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CONV_ID = uuid.UUID("22345678-1234-5678-1234-567812345678")
TS = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
TITLE = "第十二章 剑心蒙尘"
RENAME_TITLE = "改名后的标题"

# repo 真实 DB 用例专用：int 必须 ≤ SQLite INTEGER 上限（2^63-1），
# 128 位 uuid4 .int 会 OverflowError（镜像 test_chat_message_repo.py 小值 UUID 约定）
REPO_PROJECT_ID = uuid.UUID(int=1)


def _make_conversation(**overrides) -> Conversation:
    """构造最小 Conversation 领域实体（title 由用例按需覆盖）。"""
    base = {
        "id": CONV_ID,
        "project_id": PROJECT_ID,
        "created_at": TS,
        "is_deleted": False,
    }
    base.update(overrides)
    return Conversation(**base)


def _title_arg(call) -> object:
    """从 repo 调用中取 title（位置或关键字，宽松——不约束实现传参形态）。"""
    args, kwargs = call.args, call.kwargs
    return args[1] if len(args) > 1 else kwargs.get("title")


# ---- 迁移三形态（镜像 test_agent_trace.py 的 OLD/NEW_SCHEMA 手法）----

OLD_SCHEMA = """
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT 0
)
"""

NEW_SCHEMA = OLD_SCHEMA.replace(
    "is_deleted BOOLEAN NOT NULL DEFAULT 0",
    "is_deleted BOOLEAN NOT NULL DEFAULT 0, title VARCHAR(200)",
)


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


class TestConversationTitleField:
    """Conversation 领域模型 title 字段（默认空 / 上限 200 / 去空白）。"""

    def test_title_default_empty(self) -> None:
        """不传 title → 默认 ""。"""
        conv = _make_conversation()
        assert conv.title == ""

    def test_title_max_200_accepted(self) -> None:
        """200 字符（上限含边界）→ 合法。"""
        title = "章" * 200
        conv = _make_conversation(title=title)
        assert conv.title == title

    def test_title_over_200_validation_error(self) -> None:
        """201 字符 → ValidationError。"""
        with pytest.raises(ValidationError):
            _make_conversation(title="章" * 201)

    def test_title_blank_validation_error(self) -> None:
        """空白（纯空格）→ ValidationError。"""
        with pytest.raises(ValidationError):
            _make_conversation(title="   ")

    def test_title_strips_whitespace(self) -> None:
        """去空白：首尾空白剥除，内部保留。"""
        conv = _make_conversation(title="  第十二章 剑心蒙尘  ")
        assert conv.title == "第十二章 剑心蒙尘"


class TestConversationCreateTitle:
    """ConversationCreate DTO title 字段（可选 / 上限 200 / 去空白）。"""

    def test_without_title_defaults_empty(self) -> None:
        """不传 title → 默认 ""。"""
        dto = ConversationCreate(project_id=PROJECT_ID)
        assert dto.title == ""

    def test_with_title(self) -> None:
        """带 title → 透传。"""
        dto = ConversationCreate(project_id=PROJECT_ID, title=TITLE)
        assert dto.title == TITLE

    def test_title_over_200_validation_error(self) -> None:
        """201 字符 → ValidationError。"""
        with pytest.raises(ValidationError):
            ConversationCreate(project_id=PROJECT_ID, title="章" * 201)

    def test_title_blank_validation_error(self) -> None:
        """空白（纯空格）→ ValidationError。"""
        with pytest.raises(ValidationError):
            ConversationCreate(project_id=PROJECT_ID, title="   ")


class TestConversationORM:
    """ConversationORM.title 列（String(200)）。"""

    def test_orm_has_title_column(self) -> None:
        """ORM 元数据含 title 列（String(200)）。"""
        from sqlalchemy import String

        columns = ConversationORM.__table__.columns
        assert "title" in columns
        col = columns["title"]
        assert isinstance(col.type, String)
        assert col.type.length == 200


class TestConversationTitleMigration:
    """ensure_conversation_title_column 幂等迁移三形态（spec §17.3 迁移行）。"""

    def test_old_db_gets_title_column(self, tmp_path) -> None:
        """旧库：conversations 无 title → 迁移后补列（幂等可重跑）。"""
        # 惰性 import：RED 时 ensure_conversation_title_column 不存在 → ImportError
        from inkflow.core.database import ensure_conversation_title_column

        db = tmp_path / "old.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            conn.execute(text(OLD_SCHEMA))
        with engine.connect() as conn:
            assert "title" not in _columns(conn, "conversations")
            ensure_conversation_title_column(conn)
            assert "title" in _columns(conn, "conversations")
            ensure_conversation_title_column(conn)
            assert "title" in _columns(conn, "conversations")
        engine.dispose()

    def test_new_db_noop(self, tmp_path) -> None:
        """新库：create_all 已含 title → no-op 不改变列集。"""
        # 惰性 import：RED 时 ensure_conversation_title_column 不存在 → ImportError
        from inkflow.core.database import ensure_conversation_title_column

        db = tmp_path / "new.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            conn.execute(text(NEW_SCHEMA))
        with engine.connect() as conn:
            before = _columns(conn, "conversations")
            ensure_conversation_title_column(conn)
            assert _columns(conn, "conversations") == before
        engine.dispose()

    def test_missing_table_noop(self, tmp_path) -> None:
        """表不存在（全新环境）→ no-op 不抛错。"""
        # 惰性 import：RED 时 ensure_conversation_title_column 不存在 → ImportError
        from inkflow.core.database import ensure_conversation_title_column

        db = tmp_path / "empty.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.connect() as conn:
            ensure_conversation_title_column(conn)
            tables = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
            assert tables == []
        engine.dispose()


class TestChatMessageServiceTitle:
    """service.create_conversation 透传 title + rename_conversation（#770 新增）。"""

    async def test_create_conversation_passes_title_to_repo(self) -> None:
        """create_conversation(project_id, title) → repo 收到 project_id + title。"""
        repo = MagicMock()
        repo.create_conversation = AsyncMock(return_value=_make_conversation())
        svc = ChatMessageService(repo=repo)
        await svc.create_conversation(PROJECT_ID, title=TITLE)
        call = repo.create_conversation.await_args
        assert call is not None
        args, kwargs = call.args, call.kwargs
        assert (args[0] if args else kwargs["project_id"]) == PROJECT_ID
        assert _title_arg(call) == TITLE

    async def test_rename_conversation_returns_true(self) -> None:
        """rename_conversation(conversation_id, title) → repo 收到 title → True。"""
        repo = MagicMock()
        repo.rename_conversation = AsyncMock(return_value=True)
        svc = ChatMessageService(repo=repo)
        ok = await svc.rename_conversation(CONV_ID, RENAME_TITLE)
        assert ok is True
        call = repo.rename_conversation.await_args
        assert call is not None
        assert _title_arg(call) == RENAME_TITLE

    async def test_rename_conversation_missing_returns_false(self) -> None:
        """会话不存在 → repo False → service False。"""
        repo = MagicMock()
        repo.rename_conversation = AsyncMock(return_value=False)
        svc = ChatMessageService(repo=repo)
        ok = await svc.rename_conversation(CONV_ID, RENAME_TITLE)
        assert ok is False

    async def test_rename_conversation_random_overflow_shortcircuits(self) -> None:
        """随机 uuid4 超 64 位 → False 且不调 repo（镜像 #744 会话级 overflow 守卫）。"""
        repo = MagicMock()
        repo.rename_conversation = AsyncMock(return_value=True)
        svc = ChatMessageService(repo=repo)
        overflow_id = uuid.UUID(int=2**63 + 12345, version=4)
        ok = await svc.rename_conversation(overflow_id, RENAME_TITLE)
        assert ok is False
        repo.rename_conversation.assert_not_awaited()


class TestChatMessageRepoTitle:
    """repo.create_conversation 落 title / rename_conversation / list_conversations 含 title。"""

    async def test_create_conversation_persists_title(self, test_engine) -> None:
        """create_conversation(project_id, title) → 落库 + _conv_to_domain 透传 + list 读回。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.database.repositories.chat_message_repo import (
            SQLiteChatMessageRepository,
        )

        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            repo = SQLiteChatMessageRepository(session)
            conv = await repo.create_conversation(REPO_PROJECT_ID, title=TITLE)
            assert conv.title == TITLE  # _conv_to_domain 透传
            items = await repo.list_conversations()
            assert items[0]["title"] == TITLE  # list 聚合含 title

    async def test_create_conversation_default_title_empty(self, test_engine) -> None:
        """create_conversation(project_id) 不带 title → title 默认 ""。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.database.repositories.chat_message_repo import (
            SQLiteChatMessageRepository,
        )

        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            repo = SQLiteChatMessageRepository(session)
            await repo.create_conversation(REPO_PROJECT_ID)
            items = await repo.list_conversations()
            assert items[0]["title"] == ""

    async def test_list_conversations_items_include_title_key(self, test_engine) -> None:
        """list_conversations items 每项含 title 键。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.database.repositories.chat_message_repo import (
            SQLiteChatMessageRepository,
        )

        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            repo = SQLiteChatMessageRepository(session)
            await repo.create_conversation(REPO_PROJECT_ID)
            items = await repo.list_conversations()
            assert "title" in items[0]

    async def test_rename_conversation_persists_title(self, test_engine) -> None:
        """rename_conversation → True + list 读回新 title。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.database.repositories.chat_message_repo import (
            SQLiteChatMessageRepository,
        )

        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            repo = SQLiteChatMessageRepository(session)
            conv = await repo.create_conversation(REPO_PROJECT_ID)
            ok = await repo.rename_conversation(conv.id, RENAME_TITLE)
            assert ok is True
            items = await repo.list_conversations()
            assert items[0]["title"] == RENAME_TITLE

    async def test_rename_conversation_missing_returns_false(self, test_engine) -> None:
        """会话不存在 → rename_conversation False。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from inkflow.infrastructure.database.repositories.chat_message_repo import (
            SQLiteChatMessageRepository,
        )

        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        async with factory() as session:
            repo = SQLiteChatMessageRepository(session)
            ok = await repo.rename_conversation(999999, RENAME_TITLE)
            assert ok is False
