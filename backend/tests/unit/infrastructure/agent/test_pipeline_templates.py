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

import pytest

from inkflow.core.config import config
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


# ── F46 #270 auditor 审核结论约定（spec §5.3.3 gate 判定依据）─────────


class TestAuditorReviewConclusion:
    """三个内置 auditor prompt 输出加「审核结论：通过 / 不通过」行（spec §5.3.3）。

    conditional 边 gate = 关键词匹配（通过/PASS/通过审核/合格），auditor 是内置唯一
    典型 conditional 上游（如 auditor→reviser 通过才修订）——prompt 约定使 gate 稳定
    判定（自定义角色由用户自行在 prompt 约定标记）。
    """

    @pytest.mark.parametrize(
        "template_id",
        ["builtin:write_chapter", "builtin:write_auto", "builtin:write_continue"],
    )
    def test_auditor_prompt_has_review_conclusion_line(self, template_id: str) -> None:
        """每个内置模板的 auditor prompt 均含「审核结论：通过 / 不通过」约定行。"""
        auditor = _by_id(get_template(template_id).stages)["auditor"]
        prompt = auditor.agent.system_prompt
        assert "审核结论" in prompt, f"{template_id} auditor prompt 缺审核结论约定"
        assert "通过" in prompt, f"{template_id} auditor prompt 缺「通过」标记"
        assert "不通过" in prompt, f"{template_id} auditor prompt 缺「不通过」标记"


# ── 模板默认模型契约（#415 G1，2026-08-16）─────────────────────────
# 用户拍板：pipeline_templates 不写第二份默认值，角色 model 引用 config.llm_default_model。
# 契约值 = deepseek/deepseek-v4-flash（产品决策）。


def test_builtin_templates_roles_default_to_deepseek_v4_flash() -> None:
    """三内置模板全部角色 model = deepseek/deepseek-v4-flash
    （#415 G1；现值 openai/gpt-4o → FAIL）。"""
    for tid, tpl in BUILTIN_TEMPLATES.items():
        for stage in tpl.stages:
            assert stage.agent.model == "deepseek/deepseek-v4-flash", f"{tid}/{stage.id}"


def test_builtin_templates_model_follows_config_default() -> None:
    """模板默认模型与 config.llm_default_model 一致
    （#415 守护；RED 阶段二者 openai 相等 → PASS）。"""
    for tid, tpl in BUILTIN_TEMPLATES.items():
        for stage in tpl.stages:
            assert stage.agent.model == config.llm_default_model, f"{tid}/{stage.id}"


# ── #477 chat 意图分离 prompt 契约（2026-08-19）────────────────────────


class TestChatIntentSeparationPrompt:
    """builtin:chat 单 stage prompt 的意图分离标记契约（#477）。

    方案：#477「插入正文」意图分离——后端 chat prompt 约束 LLM：
    - 产出正文类回复时用 <<<CONTENT>>> ... <<<END>>> 包裹正文
    - 对话类回复（问答/闲聊）不包裹
    前端 parseChatReply 解析标记判定意图（content / conversation）。

    RED 形态：现 prompt 无标记约束 → 标记/指令断言 AssertionError；
    {prompt} 占位符与对话语义断言为守护（现值已满足 → PASS）。
    """

    def _chat_prompt(self) -> str:
        stages = get_template("builtin:chat").stages
        assert len(stages) == 1, "builtin:chat 应为单 stage"
        return stages[0].agent.system_prompt

    def test_chat_prompt_contains_content_markers(self) -> None:
        """prompt 含 <<<CONTENT>>> 与 <<<END>>> 标记（产出正文的包裹标记）。"""
        prompt = self._chat_prompt()
        assert "<<<CONTENT>>>" in prompt
        assert "<<<END>>>" in prompt

    def test_chat_prompt_has_wrap_and_no_wrap_instructions(self) -> None:
        """prompt 含「包裹」正向指令与「不要包裹」负向指令（问答/闲聊不包裹）。"""
        prompt = self._chat_prompt()
        assert "包裹" in prompt
        assert "不要包裹" in prompt

    def test_chat_prompt_keeps_user_prompt_placeholder(self) -> None:
        """prompt 仍含 {prompt} 占位符（用户提问渲染不回归）。"""
        prompt = self._chat_prompt()
        assert "{prompt}" in prompt

    def test_chat_prompt_keeps_assistant_semantics(self) -> None:
        """守护既有语义：prompt 仍含「对话」「助手」「回答」至少其一
        （对应 test_chat_pipeline.py::test_chat_role_prompt_assistant_semantics）。"""
        prompt = self._chat_prompt()
        assert any(kw in prompt for kw in ("对话", "助手", "回答"))


class TestWriteAutoTagsSubject:
    """#595 write_auto 题材 = tags 全拼（2026-08-23 拍板 D6=B / D6-a1）。

    契约：write_auto（及 write_chapter）architect prompt 的题材占位符由 {genre}
    改为 {tags}（`- 题材: {tags}`），前端 usePipeline 注入 `vars.tags = " ".join(tags)`；
    删 genre 枚举后题材引导从 tags 全拼取（不再读 genre）。

    RED 预期：当前 prompt 仍用 `- 题材: {genre}` → `{tags}` not in prompt 断言 FAIL、
    `{genre}` not in prompt 断言 FAIL；GREEN 后全部转绿。
    """

    def test_write_auto_architect_prompt_uses_tags(self) -> None:
        """write_auto architect prompt 用 {tags} 而非 {genre}（题材引导 = tags 全拼）。"""
        prompt = _by_id(get_template("builtin:write_auto").stages)["architect"].agent.system_prompt
        assert "题材" in prompt  # 守护：题材行仍在
        assert "{tags}" in prompt, "write_auto architect prompt 缺 {tags} 占位符"
        assert "{genre}" not in prompt, "write_auto 不应再读 {genre}（已删枚举）"

    def test_write_chapter_architect_prompt_uses_tags(self) -> None:
        """write_chapter architect prompt 同迁移（{genre} → {tags}）。"""
        architect = _by_id(get_template("builtin:write_chapter").stages)["architect"]
        prompt = architect.agent.system_prompt
        assert "{tags}" in prompt
        assert "{genre}" not in prompt
