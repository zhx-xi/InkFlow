"""F42 #297 内置管线模板注册契约（spec §5.6 + §8 + §13 M8）。

被测：pipeline_templates.py BUILTIN_TEMPLATES 新增两个默认模板
- builtin:write_auto（全自动新章节）：architect → writer → auditor → reviser
- builtin:write_continue（续写）：writer → auditor → reviser（无 architect）

契约（spec §5.6 双模板表 + v1.3 F4 校验）:
1. get_template 返回正确 stage 链（角色链 + 边）
2. write_continue 无 architect（writer 为入口，input_from=[]）
3. 占位符 ⊆ input_from（F4）：每 stage 的 system_prompt 引用的 {xxx_output}
   占位符集合必须 ⊆ input_from；上下文变量（{genre}/{target_words}/{context}
   /{writing_style}）不受 input_from 约束
4. prompt 场景差异（§5.6「按场景独立编写」）：
   write_auto architect 强调从零规划（含 {target_words}，不含 {context}）；
   write_continue writer 强调前文摘要引导（含 {context}，不含 {architect_output}）
5. 成品身份（🔴-1）：两模板 reviser 均为终点（output_to=[]）

RED 形态：get_template("builtin:write_auto"/"builtin:write_continue") 返回 None
→ 断言 None 失败（AssertionError）/ None.stages 抛 AttributeError；无收集 ERROR。
"""

from __future__ import annotations

import re

from inkflow.domain.ports.agent_pipeline import PipelineStage
from inkflow.infrastructure.agent.pipeline_templates import BUILTIN_TEMPLATES, get_template

_VARIABLE_RE = re.compile(r"\{(\\w+)\}")


def _role_output_placeholders(prompt: str) -> set[str]:
    """扫描 prompt 中 {xxx_output} 占位符，返回 xxx 集合（不含 _output 后缀）。"""
    return {
        m.group(1)[: -len("_output")]
        for m in _VARIABLE_RE.finditer(prompt)
        if m.group(1).endswith("_output")
    }


def _by_id(stages: list[PipelineStage]) -> dict[str, PipelineStage]:
    return {s.id: s for s in stages}


def _assert_placeholders_covered_by_input_from(stages: list[PipelineStage]) -> None:
    """F4 校验：每 stage 的 {xxx_output} 占位符 ⊆ input_from。"""
    for stage in stages:
        placeholders = _role_output_placeholders(stage.agent.system_prompt)
        assert placeholders <= set(
            stage.input_from
        ), f"stage {stage.id} prompt 引用 {placeholders} 但 input_from={stage.input_from}"


class TestWriteAutoTemplate:
    """builtin:write_auto（全自动新章节）四阶段链契约。"""

    def test_get_template_returns_config(self) -> None:
        """get_template("builtin:write_auto") 返回非 None。"""
        assert get_template("builtin:write_auto") is not None

    def test_stage_chain(self) -> None:
        """角色链 = architect → writer → auditor → reviser（§5.6 表）。"""
        stages = get_template("builtin:write_auto").stages
        assert [s.id for s in stages] == ["architect", "writer", "auditor", "reviser"]

    def test_edges(self) -> None:
        """链式边：architect→writer→auditor→reviser；reviser 依赖 writer+auditor（F4）。"""
        by_id = _by_id(get_template("builtin:write_auto").stages)
        assert by_id["architect"].input_from == []
        assert by_id["architect"].output_to == ["writer"]
        assert by_id["writer"].input_from == ["architect"]
        assert by_id["writer"].output_to == ["auditor"]
        assert by_id["auditor"].input_from == ["writer"]
        assert by_id["auditor"].output_to == ["reviser"]
        assert by_id["reviser"].input_from == ["writer", "auditor"]
        assert by_id["reviser"].output_to == []

    def test_placeholders_covered_by_input_from(self) -> None:
        """F4 校验：write_auto 每 stage 占位符 ⊆ input_from。"""
        _assert_placeholders_covered_by_input_from(get_template("builtin:write_auto").stages)

    def test_architect_prompt_from_scratch(self) -> None:
        """场景差异：architect 从零规划——含目标字数，不含前文摘要（{context}）。"""
        prompt = _by_id(get_template("builtin:write_auto").stages)["architect"].agent.system_prompt
        assert "{target_words}" in prompt
        assert "{context}" not in prompt

    def test_terminal_is_reviser(self) -> None:
        """成品身份（🔴-1）：reviser 为终点（output_to=[]）。"""
        by_id = _by_id(get_template("builtin:write_auto").stages)
        assert by_id["reviser"].output_to == []


class TestWriteContinueTemplate:
    """builtin:write_continue（续写）三角色链契约（无 architect）。"""

    def test_get_template_returns_config(self) -> None:
        """get_template("builtin:write_continue") 返回非 None。"""
        assert get_template("builtin:write_continue") is not None

    def test_stage_chain(self) -> None:
        """角色链 = writer → auditor → reviser（无 architect，§5.6 表）。"""
        stages = get_template("builtin:write_continue").stages
        assert [s.id for s in stages] == ["writer", "auditor", "reviser"]

    def test_edges(self) -> None:
        """链式边：writer→auditor→reviser；writer 为入口（input_from=[]）。"""
        by_id = _by_id(get_template("builtin:write_continue").stages)
        assert by_id["writer"].input_from == []
        assert by_id["writer"].output_to == ["auditor"]
        assert by_id["auditor"].input_from == ["writer"]
        assert by_id["auditor"].output_to == ["reviser"]
        assert by_id["reviser"].input_from == ["writer", "auditor"]
        assert by_id["reviser"].output_to == []

    def test_no_architect_stage(self) -> None:
        """无 architect 角色（前文摘要注入上下文，F6 复用）。"""
        stage_ids = {s.id for s in get_template("builtin:write_continue").stages}
        assert "architect" not in stage_ids

    def test_placeholders_covered_by_input_from(self) -> None:
        """F4 校验：write_continue 每 stage 占位符 ⊆ input_from。"""
        _assert_placeholders_covered_by_input_from(get_template("builtin:write_continue").stages)

    def test_writer_prompt_foreshadowing(self) -> None:
        """场景差异：writer 前文摘要引导——含 {context}，不含 {architect_output}。"""
        prompt = _by_id(get_template("builtin:write_continue").stages)["writer"].agent.system_prompt
        assert "{context}" in prompt
        assert "{architect_output}" not in prompt

    def test_terminal_is_reviser(self) -> None:
        """成品身份（🔴-1）：reviser 为终点（output_to=[]）。"""
        by_id = _by_id(get_template("builtin:write_continue").stages)
        assert by_id["reviser"].output_to == []


class TestBuiltinRegistry:
    """BUILTIN_TEMPLATES 注册面：两新模板并入既有分发。"""

    def test_builtin_templates_contains_both_new_templates(self) -> None:
        """BUILTIN_TEMPLATES 含两个新 key + 既有 write_chapter。"""
        assert "builtin:write_auto" in BUILTIN_TEMPLATES
        assert "builtin:write_continue" in BUILTIN_TEMPLATES
        assert "builtin:write_chapter" in BUILTIN_TEMPLATES
