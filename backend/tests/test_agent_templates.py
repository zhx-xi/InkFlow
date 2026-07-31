"""管线模板测试。"""

from inkflow.infrastructure.agent.pipeline_templates import (
    get_template,
    list_templates,
)


class TestBuiltinTemplates:
    def test_builtin_write_chapter_exists(self):
        """get_template('builtin:write_chapter') 返回非 None。"""
        tpl = get_template("builtin:write_chapter")
        assert tpl is not None

    def test_builtin_template_has_4_stages(self):
        """4 个阶段: architect, writer, auditor, reviser。"""
        tpl = get_template("builtin:write_chapter")
        assert [s.id for s in tpl.stages] == ["architect", "writer", "auditor", "reviser"]

    def test_builtin_template_stages_are_chain(self):
        """architect→writer→auditor→reviser 顺序链。
        architect.input_from=[], architect.output_to=['writer']
        writer.input_from=['architect'], writer.output_to=['auditor']
        auditor.input_from=['writer'], auditor.output_to=['reviser']
        reviser.input_from=['auditor'], reviser.output_to=[]
        """
        tpl = get_template("builtin:write_chapter")
        stages = {s.id: s for s in tpl.stages}
        assert stages["architect"].input_from == []
        assert stages["architect"].output_to == ["writer"]
        assert stages["writer"].input_from == ["architect"]
        assert stages["writer"].output_to == ["auditor"]
        assert stages["auditor"].input_from == ["writer"]
        assert stages["auditor"].output_to == ["reviser"]
        assert stages["reviser"].input_from == ["auditor"]
        assert stages["reviser"].output_to == []

    def test_builtin_template_source_is_builtin(self):
        """source='builtin', version=1。"""
        tpl = get_template("builtin:write_chapter")
        assert tpl.source == "builtin"
        assert tpl.version == 1

    def test_get_template_unknown_returns_none(self):
        """未知模板 id → None。"""
        assert get_template("builtin:does_not_exist") is None

    def test_list_templates_includes_builtin(self):
        """list_templates() 返回列表，至少包含 builtin:write_chapter。"""
        templates = list_templates()
        ids = [t["id"] for t in templates]
        assert "builtin:write_chapter" in ids

    def test_builtin_stages_have_default_agents(self):
        """每个阶段有 AgentRole，model 默认 openai/gpt-4o。"""
        tpl = get_template("builtin:write_chapter")
        for stage in tpl.stages:
            assert stage.agent is not None
            assert stage.agent.model == "openai/gpt-4o"

    def test_builtin_template_is_pipeline_config(self):
        """get_template 返回 PipelineConfig 实例。"""
        from inkflow.domain.models.agent_pipeline import PipelineConfig

        tpl = get_template("builtin:write_chapter")
        assert isinstance(tpl, PipelineConfig)
