"""F9 角色管理领域模型单元测试 — 无 I/O，纯 Pydantic 验证.

测试范围：Character / CharacterCreate / CharacterUpdate / CharacterGroup /
CharacterRelation / CharacterRelationCreate / ExtractedCharacter /
ExtractedRelation / CharacterExtractRequest。
依据: specs/f9-character-service/spec.md §2.5/§2.6 + §9 测试策略「领域模型」。
"""

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from inkflow.domain.models.character import (
    Character,
    CharacterCreate,
    CharacterExtractRequest,
    CharacterGroup,
    CharacterRelation,
    CharacterRelationCreate,
    CharacterUpdate,
    ExtractedCharacter,
    ExtractedRelation,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


class TestCharacterModel:
    """Character 领域实体测试."""

    def test_character_defaults(self):
        """默认值：personality='', group_ids=[], extra={}."""
        char = Character(
            id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
            project_id=PID,
            name="林尘",
            created_at=TS,
            updated_at=TS,
        )
        assert char.name == "林尘"
        assert char.personality == ""
        assert char.background == ""
        assert char.goals == ""
        assert char.group_ids == []
        assert char.extra == {}

    def test_character_required_fields(self):
        """缺少必填字段（name）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            Character(
                id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
                project_id=PID,
                created_at=TS,
                updated_at=TS,
            )


class TestCharacterCreateValidation:
    """CharacterCreate 请求 DTO 验证测试."""

    def test_create_valid_and_strips_name(self):
        """合法创建：name 去空白，其余字段取默认值."""
        char = CharacterCreate(project_id=PID, name="  林尘  ")
        assert char.name == "林尘"
        assert char.personality == ""
        assert char.background == ""
        assert char.goals == ""
        assert char.group_ids == []

    def test_create_empty_name_raises(self):
        """空名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="角色名不能为空"):
            CharacterCreate(project_id=PID, name="")

    def test_create_whitespace_name_raises(self):
        """纯空白名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="角色名不能为空"):
            CharacterCreate(project_id=PID, name="   ")

    def test_create_name_too_long_raises(self):
        """超过 50 字符的名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="角色名不能超过 50 个字符"):
            CharacterCreate(project_id=PID, name="长" * 51)


class TestCharacterUpdate:
    """CharacterUpdate 部分更新语义测试（exclude_unset，同 F1）."""

    def test_update_partial_semantics(self):
        """未传入的字段保持 None，且不出现在 model_fields_set."""
        update = CharacterUpdate(name="新名字")
        assert update.name == "新名字"
        assert update.personality is None
        assert update.background is None
        assert update.goals is None
        assert update.group_ids is None
        assert update.model_fields_set == {"name"}

    def test_update_explicit_none_group_id_clears(self):
        """N:M 新语义: group_ids=None（不传=不修改）与 group_ids=[]（显式清空）可区分."""
        update = CharacterUpdate(name="新名字")
        assert update.group_ids is None
        assert "group_ids" not in update.model_fields_set
        cleared = CharacterUpdate(group_ids=[])
        assert cleared.group_ids == []
        assert "group_ids" in cleared.model_fields_set
        assert CharacterUpdate().model_fields_set == set()


class TestCharacterGroupModel:
    """CharacterGroup 领域实体测试."""

    def test_group_defaults(self):
        """默认值：description='', sort_order=0."""
        group = CharacterGroup(
            id=uuid.UUID("5a1b2c3d-0000-4000-8000-000000000001"),
            project_id=PID,
            name="主角团",
            created_at=TS,
            updated_at=TS,
        )
        assert group.description == ""
        assert group.sort_order == 0


class TestCharacterRelationModel:
    """CharacterRelation 领域实体测试."""

    def test_relation_basic_fields(self):
        """基本字段构造：relation_type 必填，description 默认空串."""
        relation = CharacterRelation(
            id=uuid.UUID("7a8b9c0d-0000-4000-8000-000000000001"),
            project_id=PID,
            from_character_id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
            to_character_id=uuid.UUID("2e3f4a5b-0000-4000-8000-000000000001"),
            relation_type="师徒",
            created_at=TS,
            updated_at=TS,
        )
        assert relation.relation_type == "师徒"
        assert relation.description == ""


class TestCharacterRelationCreate:
    """CharacterRelationCreate 请求 DTO 验证测试."""

    def test_relation_create_strips_type(self):
        """relation_type 去空白，description 默认为空串."""
        rel = CharacterRelationCreate(
            to_character_id=uuid.UUID("2e3f4a5b-0000-4000-8000-000000000001"),
            relation_type=" 师徒 ",
        )
        assert rel.relation_type == "师徒"
        assert rel.description == ""

    def test_relation_type_too_long_raises(self):
        """超过 20 字符的 relation_type 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="关系类型不能超过 20 个字符"):
            CharacterRelationCreate(
                to_character_id=uuid.UUID("2e3f4a5b-0000-4000-8000-000000000001"),
                relation_type="关" * 21,
            )


class TestExtractedSchema:
    """LLM 提取结果 schema 校验测试."""

    def test_extracted_character_requires_name(self):
        """name 必填；personality/background/goals 可空."""
        with pytest.raises(ValidationError):
            ExtractedCharacter()
        ec = ExtractedCharacter(name="林尘")
        assert ec.personality is None
        assert ec.background is None
        assert ec.goals is None

    def test_extracted_relation_requires_fields(self):
        """from_name/to_name/relation_type 必填；description 可空."""
        with pytest.raises(ValidationError):
            ExtractedRelation(from_name="林尘", to_name="青云真人")
        er = ExtractedRelation(from_name="林尘", to_name="青云真人", relation_type="师徒")
        assert er.description is None


class TestCharacterExtractRequest:
    """CharacterExtractRequest 提取请求验证测试."""

    def test_extract_request_valid_and_model_optional(self):
        """text 去空白后保存；model 可选（None 表示用项目默认模型）."""
        req = CharacterExtractRequest(project_id=PID, text="  第一章内容  ")
        assert req.text == "第一章内容"
        assert req.model is None

    def test_extract_request_empty_text_raises(self):
        """空/纯空白 text 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="提取文本不能为空"):
            CharacterExtractRequest(project_id=PID, text="   ")

    def test_extract_request_text_too_long_raises(self):
        """超过 50000 字符的 text 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="提取文本不能超过 50000 个字符"):
            CharacterExtractRequest(project_id=PID, text="文" * 50001)


class TestCharacterExtraContract:
    """F43 P1 角色 extra 字段契约（spec §2.4）— RED: CharacterCreate/Update 尚无 extra 字段.

    【RED 预期】CharacterCreate/CharacterUpdate 目前无 extra 字段 → Pydantic
    extra='ignore' 静默丢弃 → model_dump() 无 extra 键（KeyError）/ 属性访问
    AttributeError = 断言失败形态（非 ERROR）。GREEN 后自动转绿。
    """

    def test_create_accepts_extra_field(self):
        """CharacterCreate 带 extra（role_rank/groups）→ 字段存在且值原样."""
        create = CharacterCreate(
            project_id=PID,
            name="林尘",
            extra={"role_rank": "major", "groups": ["主角团"]},
        )
        assert create.model_dump()["extra"] == {"role_rank": "major", "groups": ["主角团"]}

    def test_create_extra_defaults_to_empty_dict(self):
        """CharacterCreate 缺省 extra → 字段存在且为空 dict（向后兼容）."""
        create = CharacterCreate(project_id=PID, name="林尘")
        assert create.model_dump()["extra"] == {}

    def test_update_accepts_extra_field(self):
        """CharacterUpdate 带 extra → 字段存在且进入 model_fields_set（exclude_unset 整体替换）."""
        update = CharacterUpdate(name="林尘", extra={"role_rank": "major", "groups": ["主角团"]})
        assert update.extra == {"role_rank": "major", "groups": ["主角团"]}
        assert "extra" in update.model_fields_set
