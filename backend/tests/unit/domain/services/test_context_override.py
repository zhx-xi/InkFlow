"""ContextRequest.override 通道测试 — 勾选的角色/伏笔才注入（issue #593）.

测试范围 (spec f6-context-service v1.1):
    - ContextRequest.override.character_ids 非空时，只注入 metadata.character_id 命中的角色 item
    - ContextRequest.override.foreshadowing_ids 非空时，同理只注入命中伏笔
    - override 为空/None 时注入全部（默认行为不受影响）
    - override 只过滤 character/foreshadowing，不影响 outline/summary 等其他数据源
"""

from __future__ import annotations

import uuid

from inkflow.domain.models.context import (
    ContextItem,
    ContextOverride,
    ContextRequest,
    ContextSourceType,
)
from inkflow.domain.services.context_service import ContextService


async def _mock_count_tokens(text: str, _model: str = "") -> int:
    """基于字符数的 Token 估算（与 test_context_service 一致的 char/4 兜底）."""
    return max(1, len(text) // 4)


class MockSource:
    """返回固定 items 的 Mock 数据源（带 metadata）."""

    def __init__(self, items: list[ContextItem]) -> None:
        self._items = items

    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        return list(self._items)


def _item(source: ContextSourceType, title: str, metadata: dict) -> ContextItem:
    return ContextItem(source=source, title=title, content=f"内容-{title}", metadata=metadata)


def _req(**overrides) -> ContextRequest:
    defaults = {
        "project_id": uuid.uuid4(),
        "chapter_id": uuid.uuid4(),
        "model": "openai/gpt-4o",
        "writing_requirements": "写一段文字",
    }
    defaults.update(overrides)
    return ContextRequest(**defaults)


def _character_svc(id_a: uuid.UUID, id_b: uuid.UUID) -> ContextService:
    return ContextService(
        sources={
            ContextSourceType.CHARACTER_SETTING: MockSource(
                [
                    _item(
                        ContextSourceType.CHARACTER_SETTING,
                        f"角色A-{id_a}",
                        {"character_id": str(id_a)},
                    ),
                    _item(
                        ContextSourceType.CHARACTER_SETTING,
                        f"角色B-{id_b}",
                        {"character_id": str(id_b)},
                    ),
                ]
            )
        },
        count_tokens=_mock_count_tokens,
    )


class TestContextOverride:
    """override 通道 — 勾选的角色/伏笔才注入."""

    @staticmethod
    def _character_blocks(result) -> list[ContextItem]:
        return [
            b.item for b in result.blocks if b.item.source == ContextSourceType.CHARACTER_SETTING
        ]

    async def test_character_override_keeps_only_selected(self) -> None:
        """character_ids 指定后，只注入命中 id 的角色 item；未勾选不注入."""
        id_a = uuid.uuid4()
        id_b = uuid.uuid4()
        svc = _character_svc(id_a, id_b)

        result = await svc.build_context(_req(override=ContextOverride(character_ids=[id_a])))

        character_items = self._character_blocks(result)
        assert len(character_items) == 1
        assert character_items[0].metadata["character_id"] == str(id_a)

    async def test_foreshadowing_override_keeps_only_selected(self) -> None:
        """foreshadowing_ids 指定后，只注入命中 id 的伏笔 item."""
        id_x = uuid.uuid4()
        id_y = uuid.uuid4()
        svc = ContextService(
            sources={
                ContextSourceType.FORESHADOWING: MockSource(
                    [
                        _item(
                            ContextSourceType.FORESHADOWING,
                            f"伏笔X-{id_x}",
                            {"foreshadowing_id": str(id_x)},
                        ),
                        _item(
                            ContextSourceType.FORESHADOWING,
                            f"伏笔Y-{id_y}",
                            {"foreshadowing_id": str(id_y)},
                        ),
                    ]
                )
            },
            count_tokens=_mock_count_tokens,
        )

        result = await svc.build_context(_req(override=ContextOverride(foreshadowing_ids=[id_x])))

        foreshadowing_items = [
            b.item for b in result.blocks if b.item.source == ContextSourceType.FORESHADOWING
        ]
        assert len(foreshadowing_items) == 1
        assert foreshadowing_items[0].metadata["foreshadowing_id"] == str(id_x)

    async def test_override_none_injects_all(self) -> None:
        """override 为 None → 注入全部（默认行为不受影响）."""
        id_a = uuid.uuid4()
        id_b = uuid.uuid4()
        svc = _character_svc(id_a, id_b)

        result = await svc.build_context(_req())

        assert len(self._character_blocks(result)) == 2

    async def test_override_empty_lists_injects_all(self) -> None:
        """override 提供但列表为空 → 视为未勾选，注入全部."""
        id_a = uuid.uuid4()
        id_b = uuid.uuid4()
        svc = _character_svc(id_a, id_b)

        result = await svc.build_context(_req(override=ContextOverride()))

        assert len(self._character_blocks(result)) == 2

    async def test_override_does_not_affect_other_sources(self) -> None:
        """override 只过滤 character/foreshadowing，不影响 chapter_summary 等其他数据源."""
        id_a = uuid.uuid4()
        svc = ContextService(
            sources={
                ContextSourceType.CHARACTER_SETTING: MockSource(
                    [
                        _item(
                            ContextSourceType.CHARACTER_SETTING,
                            f"角色A-{id_a}",
                            {"character_id": str(id_a)},
                        ),
                        _item(
                            ContextSourceType.CHARACTER_SETTING,
                            "角色B",
                            {"character_id": str(uuid.uuid4())},
                        ),
                    ]
                ),
                ContextSourceType.CHAPTER_SUMMARY: MockSource(
                    [
                        _item(
                            ContextSourceType.CHAPTER_SUMMARY,
                            "第1章摘要",
                            {"chapter_id": str(uuid.uuid4())},
                        )
                    ]
                ),
            },
            count_tokens=_mock_count_tokens,
        )

        result = await svc.build_context(_req(override=ContextOverride(character_ids=[id_a])))

        summary_blocks = [
            b for b in result.blocks if b.item.source == ContextSourceType.CHAPTER_SUMMARY
        ]
        assert len(summary_blocks) == 1  # summary 不受 override 影响
        # 角色被过滤到只剩 1 条
        assert len(self._character_blocks(result)) == 1

    async def test_world_override_keeps_only_selected(self) -> None:
        """world_ids 指定后，只注入命中 world_setting_id 的世界观 item."""
        id_w = uuid.uuid4()
        id_v = uuid.uuid4()
        svc = ContextService(
            sources={
                ContextSourceType.WORLD_SETTING: MockSource(
                    [
                        _item(
                            ContextSourceType.WORLD_SETTING,
                            f"世界观A-{id_w}",
                            {"world_setting_id": str(id_w)},
                        ),
                        _item(
                            ContextSourceType.WORLD_SETTING,
                            f"世界观B-{id_v}",
                            {"world_setting_id": str(id_v)},
                        ),
                    ]
                )
            },
            count_tokens=_mock_count_tokens,
        )

        result = await svc.build_context(_req(override=ContextOverride(world_ids=[id_w])))

        world_items = [
            b.item for b in result.blocks if b.item.source == ContextSourceType.WORLD_SETTING
        ]
        assert len(world_items) == 1
        assert world_items[0].metadata["world_setting_id"] == str(id_w)
