"""#744 chat 消息服务单元测试 — Fake Repository（RED 契约：conversation 多线程）。

契约（实现者以本文件为准，见 .hermes/plans/contract-744.md）:
- 服务: inkflow.domain.services.chat_message_service.ChatMessageService
  构造: ChatMessageService(*, repo: object)（鸭子 repo，全 mock 轨）
- 方法签名（全部 async）:
  * add_message(data: ChatMessageCreate) -> ChatMessage
    （构造实体含 data.conversation_id；data.conversation_id 为空 → get_or_create_conversation
    自动解析；构造 id=uuid4 + created_at=now(UTC) → repo.add → 返回落库实体；
    内容校验由 ChatMessageCreate 构造期完成）
  * get_or_create_conversation(project_id) -> Conversation
    （repo.get_active_conversation 有活动线程→返回；无→repo.create_conversation 新建）
  * list_messages(conversation_id: uuid.UUID, offset: int = 0, limit: int = 50)
    -> tuple[list[ChatMessage], int]（透传 repo.list_by_conversation）
  * list_conversations(include_deleted=False) -> list[dict]（透传 repo）
  * archive_message(message_id) -> bool（repo.archive，overflow 短路）
  * force_delete_message(message_id) -> bool（repo.force_delete，overflow 短路）
  * restore_message(message_id) -> ChatMessage | None（repo.restore，overflow 短路）
  * archive_conversation(conversation_id) -> bool（repo.archive_conversation，overflow 短路）
  * force_delete_conversation(conversation_id) -> bool
  * restore_conversation(conversation_id) -> bool
- 鸭子 repo 方法:
  * add(message: ChatMessage) -> ChatMessage
  * list_by_conversation(conversation_id, offset, limit) -> (items, total)
  * list_conversations() -> list[dict]
  * get_active_conversation(project_id) -> Conversation | None
  * create_conversation(project_id) -> Conversation
  * archive / force_delete / restore（消息级）
  * archive_conversation / force_delete_conversation / restore_conversation（会话级）
- 领域模型: inkflow.domain.models.chat_message
  * ChatMessage: id/project_id/conversation_id: uuid.UUID、role（"user"/"ai"）、
    content: str、intent: str | None = None、created_at: datetime（UTC aware）
  * ChatMessageCreate: project_id/conversation_id/role/content 必填、intent 可选；
    field_validator: content 去空白非空 ≤ 10000 字符（空文案「chat 消息内容不能为空」）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models import chat_message
from inkflow.domain.services import chat_message_service

ChatMessage = chat_message.ChatMessage
ChatMessageCreate = chat_message.ChatMessageCreate
# Conversation / ConversationCreate 惰性 import（RED 时 conversation 模块未建 →
# 免顶部 collection error，逐用例 FAILED 更干净）
ChatMessageService = chat_message_service.ChatMessageService

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

PID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CID = uuid.UUID("22345678-1234-5678-1234-567812345678")
CID2 = uuid.UUID("32345678-1234-5678-1234-567812345678")
TS = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
CONTENT = "你好，请续写第三章。"


def _message(**overrides) -> ChatMessage:
    """构造测试用 ChatMessage 实体（conversation_id 必填）。"""
    base = {
        "id": uuid.uuid4(),
        "project_id": PID,
        "conversation_id": CID,
        "role": "user",
        "content": CONTENT,
        "intent": None,
        "created_at": TS,
    }
    base.update(overrides)
    return ChatMessage(**base)


def _conversation(**overrides) -> object:
    """构造 Conversation 领域对象（惰性 import conversation 模块）。"""
    from inkflow.domain.models.conversation import Conversation

    base = {
        "id": CID,
        "project_id": PID,
        "created_at": TS,
        "is_deleted": False,
    }
    base.update(overrides)
    return Conversation(**base)


def _conversation_dict(**overrides) -> dict:
    """conversations 聚合 dict（repo 聚合结果形态，含 conversation_id）。"""
    conv = {
        "conversation_id": str(CID),
        "project_id": str(PID),
        "project_name": "测试项目",
        "last_message": CONTENT,
        "message_count": 3,
        "is_deleted": False,
        "updated_at": "2026-08-20T10:00:00Z",
    }
    conv.update(overrides)
    return conv


@pytest.fixture
def fake_repo() -> MagicMock:
    """鸭子 repo（规则 1m：全方法显式默认值，禁裸 AsyncMock 分支）。"""
    repo = MagicMock()
    repo.add = AsyncMock(side_effect=lambda m: m)
    repo.list_by_conversation = AsyncMock(return_value=([], 0))
    # #748 agent 聊天历史：list_messages(project_id) 仍读项目级
    repo.list_by_project = AsyncMock(return_value=([], 0))
    repo.list_conversations = AsyncMock(return_value=[])
    repo.get_active_conversation = AsyncMock(return_value=None)
    repo.create_conversation = AsyncMock(side_effect=lambda pid: _conversation(project_id=pid))
    # 消息级两级删除
    repo.archive = AsyncMock(return_value=True)
    repo.force_delete = AsyncMock(return_value=True)
    repo.restore = AsyncMock(return_value=None)
    # #744 会话级（per-conversation）归档/真删/恢复
    repo.archive_conversation = AsyncMock(return_value=True)
    repo.force_delete_conversation = AsyncMock(return_value=True)
    repo.restore_conversation = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def service(fake_repo: MagicMock) -> ChatMessageService:
    """被测服务实例（全 mock 依赖注入）。"""
    return ChatMessageService(repo=fake_repo)


class TestAddMessage:
    """add_message — 持久化 + conversation_id 透传。"""

    async def test_add_message_persists_via_repo(self, service, fake_repo):
        created = await service.add_message(
            ChatMessageCreate(project_id=PID, conversation_id=CID, role="user", content=CONTENT)
        )
        assert isinstance(created, ChatMessage)
        assert created.project_id == PID
        assert created.conversation_id == CID
        assert created.role == "user"
        assert created.content == CONTENT
        assert created.intent is None
        assert isinstance(created.id, uuid.UUID)
        assert created.created_at.tzinfo is not None
        fake_repo.add.assert_awaited_once()
        added = fake_repo.add.await_args.args[0]
        assert isinstance(added, ChatMessage)
        assert added.conversation_id == CID

    async def test_add_message_resolves_active_conversation_when_missing(
        self, service, fake_repo
    ):
        """#744：add_message 缺 conversation_id → get_or_create 自动解析（归档后无活动线程 → 新建）。"""
        fake_repo.get_active_conversation = AsyncMock(return_value=None)
        created = await service.add_message(
            ChatMessageCreate(project_id=PID, conversation_id=None, role="user", content=CONTENT)
        )
        fake_repo.get_active_conversation.assert_awaited_once_with(PID)
        fake_repo.create_conversation.assert_awaited_once_with(PID)
        assert created.conversation_id == CID  # create_conversation 返回的 id

    async def test_add_message_reuses_active_conversation_when_exists(
        self, service, fake_repo
    ):
        """#744：存在活动线程 → get_or_create 复用其 conversation_id（不新建）。"""
        active = _conversation()
        fake_repo.get_active_conversation = AsyncMock(return_value=active)
        created = await service.add_message(
            ChatMessageCreate(project_id=PID, conversation_id=None, role="user", content=CONTENT)
        )
        fake_repo.create_conversation.assert_not_awaited()
        assert created.conversation_id == active.id

    async def test_add_message_intent_passthrough(self, service, fake_repo):
        created = await service.add_message(
            ChatMessageCreate(
                project_id=PID, conversation_id=CID, role="ai", content="好的。", intent="conversation"
            )
        )
        assert created.intent == "conversation"
        fake_repo.add.assert_awaited_once()

    async def test_add_message_blank_content_raises(self, service, fake_repo):
        with pytest.raises(ValueError, match="chat 消息内容不能为空"):
            await service.add_message(
                ChatMessageCreate(project_id=PID, conversation_id=CID, role="user", content="   ")
            )
        fake_repo.add.assert_not_awaited()


class TestGetOrCreateConversation:
    """get_or_create_conversation — 有活动线程复用 / 无则新建。"""

    async def test_returns_active_when_exists(self, service, fake_repo):
        active = _conversation()
        fake_repo.get_active_conversation = AsyncMock(return_value=active)
        result = await service.get_or_create_conversation(PID)
        assert result is active
        fake_repo.create_conversation.assert_not_awaited()

    async def test_creates_when_none(self, service, fake_repo):
        fake_repo.get_active_conversation = AsyncMock(return_value=None)
        result = await service.get_or_create_conversation(PID)
        fake_repo.get_active_conversation.assert_awaited_once_with(PID)
        fake_repo.create_conversation.assert_awaited_once_with(PID)
        assert result.project_id == PID


class TestListMessagesByConversation:
    """list_messages_by_conversation — 线程级读消息（透传 repo.list_by_conversation）。"""

    async def test_list_messages_by_conversation_passthrough(self, service, fake_repo):
        items = [_message(), _message(role="ai", content="好的，已续写。")]
        fake_repo.list_by_conversation = AsyncMock(return_value=(items, 2))
        result, total = await service.list_messages_by_conversation(CID, offset=5, limit=20)
        assert result == items
        assert total == 2
        fake_repo.list_by_conversation.assert_awaited_once_with(CID, 5, 20)

    async def test_list_messages_by_conversation_defaults(self, service, fake_repo):
        await service.list_messages_by_conversation(CID)
        fake_repo.list_by_conversation.assert_awaited_once_with(CID, 0, 50)


class TestListMessagesByProject:
    """list_messages — 项目级读（#748 agent 聊天历史），透传 repo.list_by_project。"""

    async def test_list_messages_project_history(self, service, fake_repo):
        # 保持项目级读供 agent history_getter 用
        await service.list_messages(PID, offset=0, limit=20)
        fake_repo.list_by_project.assert_awaited_once_with(PID, 0, 20)


class TestListConversations:
    """list_conversations — 透传 repo 聚合结果（含 conversation_id）。"""

    async def test_list_conversations_passthrough(self, service, fake_repo):
        convs = [_conversation_dict(), _conversation_dict(conversation_id=str(CID2), project_name=None)]
        fake_repo.list_conversations = AsyncMock(return_value=convs)
        result = await service.list_conversations()
        assert result == convs
        fake_repo.list_conversations.assert_awaited_once()

    async def test_list_conversations_include_deleted_passthrough(self, service, fake_repo):
        convs = [_conversation_dict()]
        fake_repo.list_conversations = AsyncMock(return_value=convs)
        result = await service.list_conversations(include_deleted=True)
        assert result == convs
        fake_repo.list_conversations.assert_awaited_once_with(include_deleted=True)


class TestArchiveDeleteRestore:
    """消息级两级删除 — archive_message / force_delete_message / restore_message。"""

    async def test_archive_message_delegates_to_repo(self, service, fake_repo):
        message_id = uuid.UUID(int=42)
        result = await service.archive_message(message_id)
        assert result is True
        fake_repo.archive.assert_awaited_once_with(message_id.int)

    async def test_archive_message_not_found_false(self, service, fake_repo):
        fake_repo.archive = AsyncMock(return_value=False)
        assert await service.archive_message(uuid.UUID(int=42)) is False

    async def test_force_delete_message_delegates_to_repo(self, service, fake_repo):
        message_id = uuid.UUID(int=42)
        result = await service.force_delete_message(message_id)
        assert result is True
        fake_repo.force_delete.assert_awaited_once_with(message_id.int)

    async def test_restore_message_returns_entity(self, service, fake_repo):
        message_id = uuid.UUID(int=42)
        restored = _message(id=str(message_id))
        fake_repo.restore = AsyncMock(return_value=restored)
        result = await service.restore_message(message_id)
        assert result is restored
        fake_repo.restore.assert_awaited_once_with(message_id.int)


class TestConversationLevelArchive:
    """#744 会话级（per-conversation）归档/真删/恢复。"""

    async def test_archive_conversation_delegates_to_repo(self, service, fake_repo):
        result = await service.archive_conversation(CID)
        assert result is True
        fake_repo.archive_conversation.assert_awaited_once_with(CID.int)

    async def test_force_delete_conversation_delegates_to_repo(self, service, fake_repo):
        result = await service.force_delete_conversation(CID)
        assert result is True
        fake_repo.force_delete_conversation.assert_awaited_once_with(CID.int)

    async def test_restore_conversation_delegates_to_repo(self, service, fake_repo):
        result = await service.restore_conversation(CID)
        assert result is True
        fake_repo.restore_conversation.assert_awaited_once_with(CID.int)


class Test578ServiceOverflowGuard:
    """#578 RED：service 层 128 位溢出预检（随机 uuid4 → 短路，不调用 repo）。"""

    async def test_archive_message_overflow_uuid_skips_repo(self, service, fake_repo):
        result = await service.archive_message(uuid.uuid4())
        fake_repo.archive.assert_not_awaited()
        assert result is False

    async def test_force_delete_message_overflow_uuid_skips_repo(self, service, fake_repo):
        result = await service.force_delete_message(uuid.uuid4())
        fake_repo.force_delete.assert_not_awaited()
        assert result is False

    async def test_restore_message_overflow_uuid_skips_repo(self, service, fake_repo):
        result = await service.restore_message(uuid.uuid4())
        fake_repo.restore.assert_not_awaited()
        assert result is None

    async def test_archive_conversation_overflow_uuid_skips_repo(self, service, fake_repo):
        result = await service.archive_conversation(uuid.uuid4())
        fake_repo.archive_conversation.assert_not_awaited()
        assert result is False

    async def test_force_delete_conversation_overflow_uuid_skips_repo(self, service, fake_repo):
        result = await service.force_delete_conversation(uuid.uuid4())
        fake_repo.force_delete_conversation.assert_not_awaited()
        assert result is False

    async def test_restore_conversation_overflow_uuid_skips_repo(self, service, fake_repo):
        result = await service.restore_conversation(uuid.uuid4())
        fake_repo.restore_conversation.assert_not_awaited()
        assert result is False

    async def test_archive_message_small_id_still_delegates(self, service, fake_repo):
        result = await service.archive_message(uuid.UUID(int=42))
        assert result is True
        fake_repo.archive.assert_awaited_once_with(42)
