"""Character.brief 字段契约测试（issue #593 D5-a1）.

测试范围 (spec f9-character-service v1.1):
    - Character.brief 字段默认空串；可传值
    - CharacterCreate.brief 可传值；默认空串；超长报错
    - CharacterUpdate.brief 可传值；None 表示不修改
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from inkflow.domain.models.character import Character, CharacterCreate, CharacterUpdate


def _now() -> datetime:
    return datetime.now(UTC)


class TestCharacterBrief:
    """角色领域实体的 brief 字段. """

    def test_brief_defaults_empty_string(self) -> None:
        """不传 brief → 默认空串（不破坏既有构造）. """
        char = Character(
            id=uuid.UUID(int=1),
            project_id=uuid.UUID(int=1),
            name="林晚",
            created_at=_now(),
            updated_at=_now(),
        )
        assert char.brief == ""

    def test_brief_accepts_value(self) -> None:
        """传 brief → 被接纳. """
        char = Character(
            id=uuid.UUID(int=2),
            project_id=uuid.UUID(int=1),
            name="萧炎",
            brief="废柴癌变体",
            created_at=_now(),
            updated_at=_now(),
        )
        assert char.brief == "废柴癌变体"

    def test_brief_whitespace_not_stripped_in_entity(self) -> None:
        """实体层不强制去空白（与 personality 等字段一致，DST 层负责校验）. """
        char = Character(
            id=uuid.UUID(int=3),
            project_id=uuid.UUID(int=1),
            name="青云真人",
            brief=" 元婴老祖 ",
            created_at=_now(),
            updated_at=_now(),
        )
        assert char.brief == " 元婴老祖 "


class TestCharacterCreateBrief:
    """创建 DTO 的 brief 字段. """

    def test_create_brief_defaults_empty(self) -> None:
        dto = CharacterCreate(project_id=uuid.UUID(int=1), name="林晚")
        assert dto.brief == ""

    def test_create_brief_accepts_value(self) -> None:
        dto = CharacterCreate(project_id=uuid.UUID(int=1), name="林晚", brief="冷傲大小姐")
        assert dto.brief == "冷傲大小姐"

    def test_create_brief_over_length_raises(self) -> None:
        """brief 超过 500 字符 → ValidationError. """
        with pytest.raises(ValueError):
            CharacterCreate(project_id=uuid.UUID(int=1), name="林晚", brief="x" * 501)


class TestCharacterUpdateBrief:
    """更新 DTO 的 brief 字段（exclude_unset 语义）. """

    def test_update_brief_accepts_value(self) -> None:
        dto = CharacterUpdate(brief="新简介")
        assert dto.brief == "新简介"

    def test_update_brief_none_means_no_change(self) -> None:
        dto = CharacterUpdate(brief=None)
        assert dto.brief is None
