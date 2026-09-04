"""model_resolution 单元测试 — resolve_model 三级优先级 + D1 全局默认空起。

契约（#735 用户拍板 D1/D3）:
- D3: ``resolve_model(agent_model, project_model, global_default)`` →
      agent > 项目 > 全局，首个非空即用；全空 → None。
- D1: ``config.llm_default_model`` 默认空起（移除内置 deepseek/deepseek-v4-flash）。

RED 预期失败形态:
- ``inkflow.domain.services.model_resolution.resolve_model`` 不存在 →
  本文件收集期 ModuleNotFoundError / ImportError（1 个 collection error，非 N failed）。
- D1 断言 ``InkFlowConfig.model_fields["llm_default_model"].default == ""`` →
  当前默认 "deepseek/deepseek-v4-flash" → AssertionError。

依据: specs/f19-gui/spec.md + references/model-resolution-and-context-sources.md。
"""

from __future__ import annotations

from inkflow.core.config import InkFlowConfig
from inkflow.domain.services.model_resolution import resolve_model


class TestResolveModelPriority:
    """D3: agent > 项目 > 全局，首个非空即用。"""

    def test_agent_hits_first(self) -> None:
        """agent 命中 → 忽略项目/全局（首个匹配即用）。"""
        assert resolve_model("agent/m", "proj/m", "global/m") == "agent/m"

    def test_project_when_no_agent(self) -> None:
        """agent 为空 → 项目命中。"""
        assert resolve_model(None, "proj/m", "global/m") == "proj/m"

    def test_global_when_no_agent_and_no_project(self) -> None:
        """agent/project 均为空 → 全局命中。"""
        assert resolve_model(None, None, "global/m") == "global/m"

    def test_all_empty_returns_none(self) -> None:
        """agent/project/global 全为 None → None（无可解析模型）。"""
        assert resolve_model(None, None, None) is None

    def test_empty_string_treated_as_no_value(self) -> None:
        """D1: 空串（""）视为未配置 → 全空返回 None；有值仍命中。"""
        assert resolve_model("", "", "") is None
        assert resolve_model("", "", None) is None
        assert resolve_model(None, "proj/m", "") == "proj/m"
        assert resolve_model(None, None, "") is None


class TestDefaultEmpty:
    """D1: config.llm_default_model 默认空起（ROI：读取 class 默认，免疫 env 污染）。"""

    def test_default_model_field_default_is_empty(self) -> None:
        """字段声明的默认值为空串（移除内置 deepseek/deepseek-v4-flash）。"""
        assert InkFlowConfig.model_fields["llm_default_model"].default == ""
