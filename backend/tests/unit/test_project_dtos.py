"""项目 DTO 单元测试 — 无 I/O，纯 Pydantic 验证。

测试范围：ProjectCreate / ProjectUpdate DTO 验证。
"""

import pytest
from pydantic import ValidationError

from inkflow.domain.models.project import Genre, ProjectCreate, ProjectUpdate


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
