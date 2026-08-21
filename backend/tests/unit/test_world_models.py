"""F10 世界观管理领域模型单元测试 — 无 I/O，纯 Pydantic 验证.

测试范围：WorldSetting / WorldCreate / WorldUpdate / ExtractedWorldSetting /
WorldExtractRequest。
依据: specs/f10-world-service/spec.md §2.5/§2.6 + §9 测试策略「领域模型」。
"""

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from inkflow.domain.models.world import (
    ExtractedWorldSetting,
    WorldCreate,
    WorldExtractRequest,
    WorldSetting,
    WorldUpdate,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


class TestWorldSettingModel:
    """WorldSetting 领域实体测试."""

    def test_world_setting_defaults(self):
        """默认值：category='', content='', extra={}, parent_id=None."""
        setting = WorldSetting(
            id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
            project_id=PID,
            name="灵气复苏",
            created_at=TS,
            updated_at=TS,
        )
        assert setting.name == "灵气复苏"
        assert setting.category == ""
        assert setting.content == ""
        assert setting.extra == {}
        assert setting.parent_id is None

    def test_world_setting_required_fields(self):
        """缺少必填字段（name）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            WorldSetting(
                id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
                project_id=PID,
                created_at=TS,
                updated_at=TS,
            )


class TestWorldCreateValidation:
    """WorldCreate 请求 DTO 验证测试."""

    def test_create_valid_and_strips_name(self):
        """合法创建：name 去空白，category/content 取默认值."""
        setting = WorldCreate(project_id=PID, name="  灵气复苏  ")
        assert setting.name == "灵气复苏"
        assert setting.category == ""
        assert setting.content == ""

    def test_create_empty_name_raises(self):
        """空名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="条目名不能为空"):
            WorldCreate(project_id=PID, name="")

    def test_create_whitespace_name_raises(self):
        """纯空白名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="条目名不能为空"):
            WorldCreate(project_id=PID, name="   ")

    def test_create_name_too_long_raises(self):
        """超过 50 字符的名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="条目名不能超过 50 个字符"):
            WorldCreate(project_id=PID, name="长" * 51)

    def test_create_category_empty_and_stripped_allowed(self):
        """category 空串合法（未分类），非空时去空白保存."""
        empty = WorldCreate(project_id=PID, name="宗门等级体系", category="")
        assert empty.category == ""
        stripped = WorldCreate(project_id=PID, name="宗门等级体系", category=" 设定 ")
        assert stripped.category == "设定"

    def test_create_category_too_long_raises(self):
        """超过 50 字符的 category 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="类别不能超过 50 个字符"):
            WorldCreate(project_id=PID, name="宗门等级体系", category="类" * 51)

    def test_create_content_too_long_raises(self):
        """超过 20000 字符的 content 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="内容不能超过 20000 个字符"):
            WorldCreate(project_id=PID, name="宗门等级体系", content="文" * 20001)


class TestWorldUpdate:
    """WorldUpdate 部分更新语义测试（exclude_unset，同 F1）."""

    def test_update_partial_semantics(self):
        """未传入的字段保持 None，且不出现在 model_fields_set."""
        update = WorldUpdate(name="新条目名")
        assert update.name == "新条目名"
        assert update.category is None
        assert update.content is None
        assert update.model_fields_set == {"name"}

    def test_update_category_none_vs_empty_clear(self):
        """category: None 表示不修改，\"\" 表示清除类别 — 两者可区分."""
        none_update = WorldUpdate(category=None)
        assert none_update.category is None
        assert "category" in none_update.model_fields_set
        clear_update = WorldUpdate(category="")
        assert clear_update.category == ""
        assert "category" in clear_update.model_fields_set
        assert WorldUpdate().model_fields_set == set()

    def test_update_all_defaults_none(self):
        """#576 补测（非 RED）：全默认/显式 None 构造成功，validator None 直通（L192/208）。"""
        empty = WorldUpdate()
        assert empty.name is None
        assert empty.content is None
        assert empty.model_fields_set == set()

        explicit = WorldUpdate(name=None, content=None)
        assert explicit.name is None
        assert explicit.content is None
        assert explicit.model_fields_set == {"name", "content"}


class TestExtractedWorldSetting:
    """LLM 提取结果 schema 校验测试."""

    def test_extracted_requires_name_optional_fields(self):
        """name 必填；category/content 可空（None）."""
        with pytest.raises(ValidationError):
            ExtractedWorldSetting()
        extracted = ExtractedWorldSetting(name="灵气复苏")
        assert extracted.category is None
        assert extracted.content is None


class TestWorldExtractRequest:
    """WorldExtractRequest 提取请求验证测试."""

    def test_extract_request_valid_and_model_optional(self):
        """text 去空白后保存；model 可选（None 表示用项目默认模型）."""
        req = WorldExtractRequest(project_id=PID, text="  第一章内容  ")
        assert req.text == "第一章内容"
        assert req.model is None

    def test_extract_request_empty_text_raises(self):
        """空/纯空白 text 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="提取文本不能为空"):
            WorldExtractRequest(project_id=PID, text="   ")

    def test_extract_request_text_too_long_raises(self):
        """超过 50000 字符的 text 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="提取文本不能超过 50000 个字符"):
            WorldExtractRequest(project_id=PID, text="文" * 50001)


class TestF35ParentIdModel:
    """F35 地点树 — parent_id 字段契约（spec §2.2 数据模型）.

    RED 阶段预期: WorldSetting/WorldCreate/WorldUpdate 尚未加 parent_id 字段，
    Pydantic v2 默认 extra='ignore' 会**静默丢弃**未知字段 —— 因此必须显式断言
    model_dump() 键存在（#107 空洞陷阱：仅断言属性 roundtrip 会因静默忽略而假绿）。
    """

    def test_world_setting_parent_id_roundtrip_and_dump_key(self):
        """带 parent_id 构造 → roundtrip 保留；model_dump() 必须含 parent_id 键（防 extra='ignore'
        空洞）.
        RED: 字段缺失 → model_dump()['parent_id'] KeyError.
        """
        parent = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000099")
        setting = WorldSetting(
            id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
            project_id=PID,
            name="清河县城",
            parent_id=parent,
            created_at=TS,
            updated_at=TS,
        )
        dumped = setting.model_dump()
        assert dumped["parent_id"] == parent  # 键存在（#107 空洞陷阱）
        assert setting.parent_id == parent  # 属性 roundtrip

    def test_world_setting_parent_id_defaults_none(self):
        """不传 parent_id → 默认 None（顶层，spec §2.1 可空=顶层）.
        RED: 属性不存在 → AttributeError.
        """
        setting = WorldSetting(
            id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
            project_id=PID,
            name="大越国",
            created_at=TS,
            updated_at=TS,
        )
        assert setting.parent_id is None

    def test_world_create_parent_id_roundtrip_and_default(self):
        """WorldCreate 带 parent_id 构造 + roundtrip；缺省 None（顶层）.
        RED: 字段缺失 → KeyError / AttributeError.
        """
        parent = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000099")
        with_parent = WorldCreate(project_id=PID, name="清河县城", parent_id=parent)
        assert with_parent.model_dump()["parent_id"] == parent
        assert with_parent.parent_id == parent

        top = WorldCreate(project_id=PID, name="大越国")
        assert top.model_dump()["parent_id"] is None
        assert top.parent_id is None

    def test_world_update_parent_id_explicit_none_in_fields_set(self):
        """WorldUpdate(parent_id=None) → model_fields_set 含 parent_id（置顶语义 load-bearing，spec
        §2.2 None 语义差异）.
        RED: 字段缺失静默忽略 → model_fields_set 为空 → 断言失败.
        """
        update = WorldUpdate(parent_id=None)
        assert "parent_id" in update.model_fields_set  # 出现即更新（None=置顶）
        assert update.parent_id is None

    def test_world_update_parent_id_absent_when_not_provided(self):
        """WorldUpdate(name='x') 不含 parent_id → 不修改 parent（与「置顶」可区分，spec §2.2）."""
        update = WorldUpdate(name="新名")
        assert "parent_id" not in update.model_fields_set

    def test_world_setting_extra_scale_preserved(self):
        """extra.scale 自由文本键 roundtrip 保留（spec §2.1: scale 纯展示标签，extra JSON
        零迁移承载）."""
        setting = WorldSetting(
            id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
            project_id=PID,
            name="清河县城",
            extra={"scale": "县城"},
            created_at=TS,
            updated_at=TS,
        )
        assert setting.model_dump()["extra"] == {"scale": "县城"}
        assert setting.extra == {"scale": "县城"}
