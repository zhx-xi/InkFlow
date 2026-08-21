"""#547 chat 消息服务单元测试 — Fake Repository（RED 契约，spec 待定稿）.

契约（实现者以本文件为准）:
- 服务: inkflow.domain.services.chat_message_service.ChatMessageService
  构造: ChatMessageService(*, repo: object)（鸭子 repo，全 mock 轨）
- 方法签名（全部 async）:
  * add_message(data: ChatMessageCreate) -> ChatMessage
    （构造实体 id=uuid4 + created_at=now(UTC) → repo.add → 返回落库实体；
    intent 默认 None 透传；内容校验由 ChatMessageCreate 构造期完成，
    service 不重复校验）
  * list_messages(project_id: uuid.UUID, offset: int = 0, limit: int = 50)
    -> tuple[list[ChatMessage], int]（透传 repo.list_by_project，位置透传
    (project_id, offset, limit)）
  * list_conversations() -> list[dict]
    （[{project_id, project_name, last_message, message_count, updated_at}]
    由 repo 聚合；project_name 可空；service 原样透传）
- 鸭子 repo 方法:
  * add(message: ChatMessage) -> ChatMessage
  * list_by_project(project_id, offset, limit) -> (items, total)
  * list_conversations() -> list[dict]
- 领域模型: inkflow.domain.models.chat_message
  * ChatMessage: id/project_id: uuid.UUID、role: str（"user"/"ai"）、
    content: str、intent: str | None = None、created_at: datetime（UTC aware）
  * ChatMessageCreate: project_id/role/content 必填、intent 可选；
    field_validator: content 去空白非空 ≤ 10000 字符
    （空文案「chat 消息内容不能为空」）；role ∈ {user, ai}

RED 预期: inkflow.domain.models.chat_message / services.chat_message_service
模块均不存在 → 顶部 import 收集期 ImportError（等价 ModuleNotFoundError
收集错误，exit 2），整文件不执行（规则 1c 首选形态，任务书认可）。

asyncio: pyproject asyncio_mode = "auto"；文件级 pytestmark 双保险。
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
ChatMessageService = chat_message_service.ChatMessageService

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

PID = uuid.UUID("12345678-1234-5678-1234-567812345678")
TS = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)
CONTENT = "你好，请续写第三章。"


def _message(**overrides) -> ChatMessage:
    """构造测试用 ChatMessage 实体（固定 UTC aware 时间戳，便于断言）。"""
    base = {
        "id": uuid.uuid4(),
        "project_id": PID,
        "role": "user",
        "content": CONTENT,
        "intent": None,
        "created_at": TS,
    }
    base.update(overrides)
    return ChatMessage(**base)


def _conversation_dict(**overrides) -> dict:
    """conversations 聚合 dict（repo 聚合结果形态，project_name 可空）。"""
    conv = {
        "project_id": str(PID),
        "project_name": "测试项目",
        "last_message": CONTENT,
        "message_count": 3,
        "updated_at": "2026-08-20T10:00:00Z",
    }
    conv.update(overrides)
    return conv


@pytest.fixture
def fake_repo() -> MagicMock:
    """鸭子 repo（规则 1m：全方法显式默认值，禁裸 AsyncMock 分支）。"""
    repo = MagicMock()
    repo.add = AsyncMock(side_effect=lambda m: m)
    repo.list_by_project = AsyncMock(return_value=([], 0))
    repo.list_conversations = AsyncMock(return_value=[])
    # #566 两级删除（镜像 session_repo soft_delete/restore/hard_delete）：
    # archive = 软删（is_deleted=true）返回 bool；force_delete = 硬删返回 bool；
    # restore = 解除归档返回 ChatMessage | None。
    repo.archive = AsyncMock(return_value=True)
    repo.force_delete = AsyncMock(return_value=True)
    repo.restore = AsyncMock(return_value=None)
    # #566 会话级（per-project）归档/真删
    repo.archive_by_project = AsyncMock(return_value=2)
    repo.force_delete_by_project = AsyncMock(return_value=2)
    return repo


@pytest.fixture
def service(fake_repo: MagicMock) -> ChatMessageService:
    """被测服务实例（全 mock 依赖注入）。"""
    return ChatMessageService(repo=fake_repo)


class TestAddMessage:
    """add_message — 持久化 + intent 默认 None 透传。"""

    async def test_add_message_persists_via_repo(self, service, fake_repo):
        """repo.add 记录调用；返回实体含 id/created_at（UTC aware）；intent 默认 None。"""
        created = await service.add_message(
            ChatMessageCreate(project_id=PID, role="user", content=CONTENT)
        )
        assert isinstance(created, ChatMessage)
        assert created.project_id == PID
        assert created.role == "user"
        assert created.content == CONTENT
        assert created.intent is None  # intent 缺省 → None 透传
        assert isinstance(created.id, uuid.UUID)
        assert created.created_at is not None
        assert created.created_at.tzinfo is not None  # UTC aware
        # repo.add 收到完整实体（service 返回落库实体，同一性）
        fake_repo.add.assert_awaited_once()
        added = fake_repo.add.await_args.args[0]
        assert isinstance(added, ChatMessage)
        assert added.id == created.id
        assert added.intent is None

    async def test_add_message_intent_passthrough(self, service, fake_repo):
        """intent="conversation" 显式透传至实体与 repo.add。"""
        created = await service.add_message(
            ChatMessageCreate(project_id=PID, role="ai", content="好的。", intent="conversation")
        )
        assert created.intent == "conversation"
        fake_repo.add.assert_awaited_once()

    async def test_add_message_blank_content_raises(self, service, fake_repo):
        """content 纯空白 → ChatMessageCreate 构造期 ValueError（DTO validator，
        service 不重复校验）→ repo.add 不被调用。"""
        with pytest.raises(ValueError, match="chat 消息内容不能为空"):
            await service.add_message(ChatMessageCreate(project_id=PID, role="user", content="   "))
        fake_repo.add.assert_not_awaited()


class TestListMessages:
    """list_messages — 透传 repo (items, total) + 参数位置透传。"""

    async def test_list_messages_passthrough(self, service, fake_repo):
        """显式 offset/limit → repo.list_by_project(PID, 5, 20) 位置透传。"""
        items = [_message(), _message(role="ai", content="好的，已续写。")]
        fake_repo.list_by_project = AsyncMock(return_value=(items, 2))
        result, total = await service.list_messages(PID, offset=5, limit=20)
        assert result == items
        assert total == 2
        # 契约锁位置透传 (project_id, offset, limit)
        fake_repo.list_by_project.assert_awaited_once_with(PID, 5, 20)

    async def test_list_messages_defaults(self, service, fake_repo):
        """全缺省 → repo.list_by_project(PID, 0, 50)。"""
        await service.list_messages(PID)
        fake_repo.list_by_project.assert_awaited_once_with(PID, 0, 50)


class TestListConversations:
    """list_conversations — 透传 repo 聚合结果（project_name 可空）。"""

    async def test_list_conversations_passthrough(self, service, fake_repo):
        """repo 聚合 dict 列表原样透传（含 project_name=None 可空形态）。"""
        convs = [_conversation_dict(), _conversation_dict(project_name=None)]
        fake_repo.list_conversations = AsyncMock(return_value=convs)
        result = await service.list_conversations()
        assert result == convs
        fake_repo.list_conversations.assert_awaited_once()


class TestArchiveDeleteRestore:
    """#566 两级删除 — archive_message / force_delete_message / restore_message。

    契约（镜像 session_service.delete/restore 模式）:
    - archive_message(message_id: uuid.UUID) -> bool
      （软删 is_deleted=true；repo.archive 收到 int 主键；False = 不存在/已归档）
    - force_delete_message(message_id: uuid.UUID) -> bool
      （真删；repo.force_delete 收到 int 主键；False = 不存在）
    - restore_message(message_id: uuid.UUID) -> ChatMessage | None
      （解除归档；repo.restore 收到 int 主键；None = 不存在/未归档）

    RED 预期: service 无这三方法 → AttributeError（'ChatMessageService' object has
    no attribute 'archive_message'）→ 用例 FAILED。
    """

    async def test_archive_message_delegates_to_repo(self, service, fake_repo):
        """archive_message → repo.archive(message_id.int) 位置透传，返回 bool。"""
        message_id = uuid.UUID(int=42)
        result = await service.archive_message(message_id)
        assert result is True
        fake_repo.archive.assert_awaited_once_with(message_id.int)

    async def test_archive_message_not_found_false(self, service, fake_repo):
        """repo.archive 返回 False（不存在/已归档）→ service 原样透传 False。"""
        fake_repo.archive = AsyncMock(return_value=False)
        assert await service.archive_message(uuid.UUID(int=42)) is False

    async def test_force_delete_message_delegates_to_repo(self, service, fake_repo):
        """force_delete_message → repo.force_delete(message_id.int) 位置透传。"""
        message_id = uuid.UUID(int=42)
        result = await service.force_delete_message(message_id)
        assert result is True
        fake_repo.force_delete.assert_awaited_once_with(message_id.int)

    async def test_force_delete_message_not_found_false(self, service, fake_repo):
        """repo.force_delete 返回 False → service 原样透传 False。"""
        fake_repo.force_delete = AsyncMock(return_value=False)
        assert await service.force_delete_message(uuid.UUID(int=42)) is False

    async def test_restore_message_returns_entity(self, service, fake_repo):
        """restore_message → repo.restore(message_id.int)；返回 ChatMessage。"""
        message_id = uuid.UUID(int=42)
        restored = _message(id=str(message_id))
        fake_repo.restore = AsyncMock(return_value=restored)
        result = await service.restore_message(message_id)
        assert result is restored
        fake_repo.restore.assert_awaited_once_with(message_id.int)

    async def test_restore_message_not_found_none(self, service, fake_repo):
        """repo.restore 返回 None（不存在/未归档）→ service 原样透传 None。"""
        assert await service.restore_message(uuid.UUID(int=42)) is None

    async def test_archive_conversation_delegates_to_repo(self, service, fake_repo):
        """archive_conversation → repo.archive_by_project(project_id.int) 位置透传，返回 int。"""
        result = await service.archive_conversation(uuid.UUID(int=42))
        assert result == 2
        fake_repo.archive_by_project.assert_awaited_once()

    async def test_force_delete_conversation_delegates_to_repo(self, service, fake_repo):
        """force_delete_conversation → repo.force_delete_by_project(project_id.int) 位置透传。"""
        result = await service.force_delete_conversation(uuid.UUID(int=42))
        assert result == 2
        fake_repo.force_delete_by_project.assert_awaited_once()


class Test578ServiceOverflowGuard:
    """#578 RED：service 层 128 位溢出预检。

    契约（修复方案：service 层预检短路）:
    - 收到超出 SQLite 64 位 INTEGER 主键范围的 id（随机 uuid4 的 int 表示
      > 2**63-1）→ 必然不存在 → 直接返回等价「不存在」语义，**不调用 repo**:
      * archive_message -> False
      * force_delete_message -> False
      * restore_message -> None
      * archive_conversation -> 0
      * force_delete_conversation -> 0
    - 小值 id（64 位范围内，如 uuid.UUID(int=42)）正常透传 repo（防过度防御）。

    RED 预期: 当前 service 无条件 _to_int_id 后透传 repo（fake 不溢出，返回
    默认值）→「repo 未被调用」断言 FAILED；修复后预检短路 → PASS。
    """

    async def test_archive_message_overflow_uuid_skips_repo(self, service, fake_repo):
        """随机 uuid4（int > 2**63-1）→ 返回 False 且 repo.archive 未被调用。"""
        result = await service.archive_message(uuid.uuid4())
        fake_repo.archive.assert_not_awaited()
        assert result is False

    async def test_force_delete_message_overflow_uuid_skips_repo(self, service, fake_repo):
        """随机 uuid4 → 返回 False 且 repo.force_delete 未被调用。"""
        result = await service.force_delete_message(uuid.uuid4())
        fake_repo.force_delete.assert_not_awaited()
        assert result is False

    async def test_restore_message_overflow_uuid_skips_repo(self, service, fake_repo):
        """随机 uuid4 → 返回 None 且 repo.restore 未被调用。"""
        result = await service.restore_message(uuid.uuid4())
        fake_repo.restore.assert_not_awaited()
        assert result is None

    async def test_archive_conversation_overflow_uuid_skips_repo(self, service, fake_repo):
        """随机 uuid4 → 返回 0 且 repo.archive_by_project 未被调用。"""
        result = await service.archive_conversation(uuid.uuid4())
        fake_repo.archive_by_project.assert_not_awaited()
        assert result == 0

    async def test_force_delete_conversation_overflow_uuid_skips_repo(self, service, fake_repo):
        """随机 uuid4 → 返回 0 且 repo.force_delete_by_project 未被调用。"""
        result = await service.force_delete_conversation(uuid.uuid4())
        fake_repo.force_delete_by_project.assert_not_awaited()
        assert result == 0

    async def test_archive_message_small_id_still_delegates(self, service, fake_repo):
        """对照: uuid.UUID(int=42)（64 位范围内）→ repo.archive 照常调用，返回值透传。"""
        result = await service.archive_message(uuid.UUID(int=42))
        assert result is True
        fake_repo.archive.assert_awaited_once_with(42)

    async def test_restore_message_small_id_still_delegates(self, service, fake_repo):
        """对照: uuid.UUID(int=42) → repo.restore 照常调用一次。"""
        await service.restore_message(uuid.UUID(int=42))
        fake_repo.restore.assert_awaited_once_with(42)
