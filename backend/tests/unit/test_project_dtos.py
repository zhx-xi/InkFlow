"""项目 DTO 单元测试 — 无 I/O，纯 Pydantic 验证。

测试范围：ProjectCreate / ProjectUpdate DTO 验证。
"""

import pytest
from pydantic import ValidationError

from inkflow.domain.models.project import (
    Genre,
    ProjectConfig,
    ProjectCreate,
    ProjectUpdate,
)


class TestProjectCreateValidation:
    """Pydantic DTO 层面的创建验证测试."""

    def test_create_with_valid_data(self):
        """正常创建，所有字段合法."""
        project = ProjectCreate(
            name="测试小说",
            genre=Genre.XUANHUAN,
            language="zh-CN",
            target_words=100000,
        )
        assert project.name == "测试小说"
        assert project.genre == Genre.XUANHUAN
        assert project.language == "zh-CN"
        assert project.target_words == 100000

    def test_create_empty_name_raises(self):
        """空名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="项目名称不能为空"):
            ProjectCreate(name="")

    def test_create_whitespace_name_raises(self):
        """纯空格名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="项目名称不能为空"):
            ProjectCreate(name="   ")

    def test_create_name_too_long_raises(self):
        """超过 100 字符的名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="项目名称不能超过 100 个字符"):
            ProjectCreate(name="长" * 101)

    def test_create_defaults(self):
        """默认值：genre='其他', language='zh-CN', target_words=0, config.model='gpt-4o'."""
        project = ProjectCreate(name="默认测试")
        assert project.genre == Genre.QITA
        assert project.language == "zh-CN"
        assert project.target_words == 0
        assert project.config.model == "gpt-4o"


class TestProjectUpdateValidation:
    """更新请求 Pydantic 验证测试."""

    def test_update_partial(self):
        """部分更新：未提供的字段应为 None."""
        update = ProjectUpdate(name="新名称")
        assert update.name == "新名称"
        assert update.genre is None
        assert update.language is None
        assert update.target_words is None
        assert update.config is None
        assert update.is_deleted is None

    def test_update_empty_name_raises(self):
        """空名称更新应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="项目名称不能为空"):
            ProjectUpdate(name="")


class TestProjectConfigDefaultWords:
    """ProjectConfig.default_words 字段契约（🔴-4 方案 A）.

    契约：默认 800000，范围 [1000, 10_000_000]，序列化 round-trip 保留。
    评审 finding：前端 PATCH config.default_words 被后端静默丢弃（模型无此字段，
    Pydantic extra='ignore'）——本类测试先锁定字段契约，修复后转 GREEN。
    """

    def test_default_words_default_value(self):
        """未显式赋值时 default_words 默认为 800000."""
        config = ProjectConfig()
        assert config.default_words == 800000

    def test_default_words_explicit_value(self):
        """显式赋值保留：default_words=50000."""
        config = ProjectConfig(default_words=50000)
        assert config.default_words == 50000

    def test_default_words_below_min_raises(self):
        """default_words=0 低于 ge=1000 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="greater than or equal to 1000"):
            ProjectConfig(default_words=0)

    def test_default_words_above_max_raises(self):
        """default_words=10000001 高于 le=10_000_000 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="less than or equal to 10000000"):
            ProjectConfig(default_words=10000001)

    def test_default_words_serialization_roundtrip(self):
        """model_dump 序列化 round-trip 保留 default_words 字段值."""
        config = ProjectConfig(default_words=50000)
        assert config.model_dump()["default_words"] == 50000
