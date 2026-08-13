"""ForeshadowingSource 数据源测试 — F6 注入集合构造（F13 M4，spec §5.3/§9 数据源）.

覆盖场景（spec §9 数据源部分，Mock Repo）:
- 有 open 伏笔 → 逐条 ContextItem（source=FORESHADOWING、title 前缀「伏笔：」、
  priority 透传、metadata 完整含 event_id）
- 挂接事件伏笔 metadata.event_id 为 UUID 字符串；未挂接为 null
- repo 返回顺序即注入顺序（priority 降序由仓储 list_open 保证，spec §6.2）
- 确定性提醒模板 _render_reminder：description / location 为空时省略对应段
- 无 open 伏笔 / 全部 resolved / 项目不存在 → 空列表（repo 返回空即空注入，
  不报错，同 F6 数据源惯例）

注: 过滤语义（resolved / 真删排除、priority DESC 排序）由仓储层保证
（SQLiteForeshadowingRepository.list_open，见 test_foreshadowing_repo.py）；
本文件只测数据源对 repo 结果的消费与 ContextItem 构造。

依据: specs/f13-foreshadowing-service/spec.md §5.3/§5.5/§9。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from inkflow.domain.models.context import ContextItem, ContextSourceType
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.infrastructure.context.sources import ForeshadowingSource


def _foreshadowing(title: str, **kw) -> Foreshadowing:
    """构造测试用 Foreshadowing — 必填时间戳自动补齐，其余字段可覆盖."""
    return Foreshadowing(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=100),
        title=title,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        **kw,
    )


class TestForeshadowingSourceCollect:
    """ForeshadowingSource.collect — 未回收伏笔 → ContextItem 列表（spec §5.3）."""

    async def test_builds_one_context_item_per_open_foreshadowing(self) -> None:
        """有 open 伏笔 → 逐条 ContextItem（source / title 前缀 / priority 透传）."""
        repo = AsyncMock()
        repo.list_open.return_value = [
            _foreshadowing("林晚的身世", priority=80),
            _foreshadowing("铜镜的秘密", priority=50),
        ]
        source = ForeshadowingSource(repo)

        items = await source.collect(uuid.UUID(int=100), uuid.UUID(int=2))

        assert len(items) == 2
        assert all(isinstance(i, ContextItem) for i in items)
        assert [i.source for i in items] == [ContextSourceType.FORESHADOWING] * 2
        assert [i.title for i in items] == ["伏笔：林晚的身世", "伏笔：铜镜的秘密"]
        assert [i.priority for i in items] == [80, 50]

    async def test_metadata_carries_full_fields(self) -> None:
        """metadata 完整：foreshadowing_id / status / location / event_id（挂接=UUID 字符串）."""
        attached = _foreshadowing("林晚的身世", location="第 5 章", event_id=uuid.UUID(int=7))
        repo = AsyncMock()
        repo.list_open.return_value = [attached]
        source = ForeshadowingSource(repo)

        items = await source.collect(uuid.UUID(int=100), uuid.UUID(int=2))

        assert items[0].metadata == {
            "foreshadowing_id": str(attached.id),
            "status": "open",
            "location": "第 5 章",
            "event_id": str(attached.event_id),
        }

    async def test_metadata_event_id_is_none_when_not_attached(self) -> None:
        """未挂接事件 → metadata.event_id 为 None（不携带 'None' 字符串）."""
        repo = AsyncMock()
        repo.list_open.return_value = [_foreshadowing("铜镜的秘密")]
        source = ForeshadowingSource(repo)

        items = await source.collect(uuid.UUID(int=100), uuid.UUID(int=2))

        assert items[0].metadata["event_id"] is None

    async def test_content_renders_full_reminder_template(self) -> None:
        """提醒文本完整模板：首段 + 描述段 + 埋设位置段."""
        repo = AsyncMock()
        repo.list_open.return_value = [
            _foreshadowing("林晚的身世", description="胎记与信物相同", location="第 5 章")
        ]
        source = ForeshadowingSource(repo)

        items = await source.collect(uuid.UUID(int=100), uuid.UUID(int=2))

        assert items[0].content == "未回收伏笔：林晚的身世。\n胎记与信物相同\n（埋设位置：第 5 章）"

    async def test_content_omits_description_when_empty(self) -> None:
        """description 为空 → 模板省略描述段."""
        repo = AsyncMock()
        repo.list_open.return_value = [
            _foreshadowing("林晚的身世", description="", location="第 5 章")
        ]
        source = ForeshadowingSource(repo)

        items = await source.collect(uuid.UUID(int=100), uuid.UUID(int=2))

        assert items[0].content == "未回收伏笔：林晚的身世。\n（埋设位置：第 5 章）"

    async def test_content_omits_location_when_empty(self) -> None:
        """location 为空 → 模板省略埋设位置段."""
        repo = AsyncMock()
        repo.list_open.return_value = [
            _foreshadowing("铜镜的秘密", description="镜子背面有暗纹", location="")
        ]
        source = ForeshadowingSource(repo)

        items = await source.collect(uuid.UUID(int=100), uuid.UUID(int=2))

        assert items[0].content == "未回收伏笔：铜镜的秘密。\n镜子背面有暗纹"

    async def test_preserves_repo_order_as_injection_order(self) -> None:
        """repo 返回顺序即注入顺序 — priority 降序由 list_open 保证，source 不重排."""
        repo = AsyncMock()
        repo.list_open.return_value = [
            _foreshadowing("主线", priority=90),
            _foreshadowing("支线", priority=60),
            _foreshadowing("彩蛋", priority=20),
        ]
        source = ForeshadowingSource(repo)

        items = await source.collect(uuid.UUID(int=100), uuid.UUID(int=2))

        assert [i.priority for i in items] == [90, 60, 20]
        assert [i.title for i in items] == ["伏笔：主线", "伏笔：支线", "伏笔：彩蛋"]

    async def test_calls_list_open_with_int_project_id(self) -> None:
        """UUID → int 主键转换：以 project_id.int 调用 list_open（F1 惯例）."""
        repo = AsyncMock()
        repo.list_open.return_value = []
        source = ForeshadowingSource(repo)

        await source.collect(uuid.UUID(int=100), uuid.UUID(int=2))

        repo.list_open.assert_awaited_once_with(100)

    async def test_returns_empty_when_no_open_foreshadowings(self) -> None:
        """无 open 伏笔 → 空列表（跳过，不报错）."""
        repo = AsyncMock()
        repo.list_open.return_value = []
        source = ForeshadowingSource(repo)

        items = await source.collect(uuid.UUID(int=100), uuid.UUID(int=2))

        assert items == []

    async def test_returns_empty_when_all_resolved(self) -> None:
        """全部已回收 → 空列表（resolved 不进入注入集合，repo 语义保证）."""
        repo = AsyncMock()
        repo.list_open.return_value = []  # list_open 只返回 open 活动伏笔
        source = ForeshadowingSource(repo)

        items = await source.collect(uuid.UUID(int=100), uuid.UUID(int=2))

        assert items == []

    async def test_returns_empty_when_project_missing(self) -> None:
        """项目不存在（repo 返回空）→ 空列表（F6 数据源惯例，组装层另有项目校验）."""
        repo = AsyncMock()
        repo.list_open.return_value = []
        source = ForeshadowingSource(repo)

        items = await source.collect(uuid.UUID(int=999), uuid.UUID(int=2))

        assert items == []
