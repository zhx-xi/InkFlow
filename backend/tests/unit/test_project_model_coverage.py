"""#627 coverage-gap closure: 补 domain/models/project.py 漏覆盖分支（纯 validator）。

- `_normalize_tags`：非 list（L22->23）、元素非 str（L27->28）。
- `ProjectConfig`：agent_order 非 list（L219->220）、extra 非 dict（L269->270）。
- `ProjectUpdate`：tags=None 原样返回（L378->379）、name=None 原样返回（L386->387）、
  name 超 100 字符（L391->392）。
"""

from __future__ import annotations

import pytest

from inkflow.domain.models.project import Project, ProjectConfig, ProjectUpdate


class TestNormalizeTagsBranches:
    """_normalize_tags 防御分支。"""

    def test_non_list_raises(self):
        """tags 非 list → ValueError（L22->23）。"""
        with pytest.raises(ValueError, match="项目标签必须为数组"):
            Project(name="p", tags="x")

    def test_non_str_item_raises(self):
        """tags 元素非 str → ValueError（L27->28）。"""
        with pytest.raises(ValueError, match="项目标签必须为数组"):
            Project(name="p", tags=[1])


class TestProjectConfigValidators:
    """ProjectConfig agent_order / extra 防御分支。"""

    def test_agent_order_not_list_raises(self):
        """agent_order 非 list → ValueError（L219->220）。"""
        with pytest.raises(ValueError, match="agent_order 每层必须为数组"):
            ProjectConfig(agent_order="x")

    def test_extra_not_dict_raises(self):
        """extra 非 dict → ValueError（L269->270）。"""
        with pytest.raises(ValueError, match="extra 必须为对象"):
            ProjectConfig(extra="x")


class TestProjectUpdateValidators:
    """ProjectUpdate tags / name 防御分支（mode="before" 校验，显式传 None 触发）。"""

    def test_tags_none_passthrough(self):
        """tags=None 原样返回（L378->379）。"""
        assert ProjectUpdate(tags=None).tags is None

    def test_name_none_passthrough(self):
        """name=None 原样返回（L386->387）。"""
        assert ProjectUpdate(name=None).name is None

    def test_name_too_long_raises(self):
        """name 超 100 字符 → ValueError（L391->392）。"""
        with pytest.raises(ValueError, match="项目名称不能超过 100 个字符"):
            ProjectUpdate(name="x" * 101)
