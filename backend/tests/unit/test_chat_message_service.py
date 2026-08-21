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
            ChatMessageCreate(
                project_id=PID, role="ai", content="好的。", intent="conversation"
            )
        )
        assert created.intent == "conversation"
        fake_repo.add.assert_awaited_once()

    async def test_add_message_blank_content_raises(self, service, fake_repo):
        """content 纯空白 → ChatMessageCreate 构造期 ValueError（DTO validator，
        service 不重复校验）→ repo.add 不被调用。"""
        with pytest.raises(ValueError, match="chat 消息内容不能为空"):
            await service.add_message(
                ChatMessageCreate(project_id=PID, role="user", content="   ")
            )
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
