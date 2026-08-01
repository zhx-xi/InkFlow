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
        """默认值：category='', content='', extra={}, is_deleted=False."""
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
        assert setting.is_deleted is False

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
