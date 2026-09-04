"""LangChainPromptManager 单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from inkflow.domain.ports.llm_errors import TemplateNotFoundError, TemplateRenderError
from inkflow.domain.ports.prompt_template import PromptTemplate


class TestLangChainPromptManager:
    """Prompt Manager 测试套件。"""

    @pytest.fixture
    def templates_dir(self, tmp_path) -> Path:
        """创建临时模板目录，包含测试模板。"""
        tmpl_dir = tmp_path / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "test_writer.yaml").write_text(
            """name: test_writer
description: "Test writer template"
system_prompt: "You are a {genre} writer."
human_prompt: "Write chapter {chapter_num} about {topic}."
variables: [genre, chapter_num, topic]
""",
            encoding="utf-8",
        )
        (tmpl_dir / "minimal.yaml").write_text(
            """name: minimal
system_prompt: "Be helpful."
variables: []
""",
            encoding="utf-8",
        )
        return tmpl_dir

    @pytest.fixture
    def prompt_manager(self, templates_dir):
        from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager

        return LangChainPromptManager(templates_dir=templates_dir)

    # ── load() ──

    def test_load_existing_template(self, prompt_manager):
        """加载存在的模板应返回 PromptTemplate。"""
        tmpl = prompt_manager.load("test_writer")
        assert isinstance(tmpl, PromptTemplate)
        assert tmpl.name == "test_writer"
        assert "genre" in tmpl.variables
        assert "chapter_num" in tmpl.variables
        assert "topic" in tmpl.variables

    def test_load_nonexistent_template(self, prompt_manager):
        """加载不存在的模板应抛出 TemplateNotFoundError。"""
        with pytest.raises(TemplateNotFoundError):
            prompt_manager.load("nonexistent_template")

    # ── render() ──

    def test_render_with_all_variables(self, prompt_manager):
        """所有变量满足时应正确渲染。"""
        tmpl = prompt_manager.load("test_writer")
        result = prompt_manager.render(
            tmpl,
            {"genre": "玄幻", "chapter_num": "3", "topic": "主角突破"},
        )
        assert len(result.messages) == 2  # system + human
        assert result.messages[0]["role"] == "system"
        assert "玄幻" in result.messages[0]["content"]
        assert result.messages[1]["role"] == "user"
        assert "Write chapter 3 about 主角突破" in result.messages[1]["content"]

    def test_render_missing_variable(self, prompt_manager):
        """缺少变量时应抛出 TemplateRenderError。"""
        tmpl = prompt_manager.load("test_writer")
        with pytest.raises(TemplateRenderError) as exc_info:
            prompt_manager.render(tmpl, {"genre": "玄幻"})
        assert "chapter_num" in exc_info.value.missing_variables

    # ── validate() ──

    def test_validate_all_satisfied(self, prompt_manager):
        """变量全部满足时应返回空列表。"""
        tmpl = prompt_manager.load("test_writer")
        missing = prompt_manager.validate(
            tmpl, {"genre": "玄幻", "chapter_num": "1", "topic": "test"}
        )
        assert missing == []

    def test_validate_missing_variables(self, prompt_manager):
        """变量缺失时应返回缺失列表。"""
        tmpl = prompt_manager.load("test_writer")
        missing = prompt_manager.validate(tmpl, {"genre": "玄幻"})
        assert "chapter_num" in missing
        assert "topic" in missing

    # ── list_templates() ──

    def test_list_templates(self, prompt_manager):
        """应列出所有 .yaml 模板的名称。"""
        names = prompt_manager.list_templates()
        assert "test_writer" in names
        assert "minimal" in names

    # ── 最小模板 ──

    def test_minimal_template(self, prompt_manager):
        """最小模板（无变量）应正确加载和渲染。"""
        tmpl = prompt_manager.load("minimal")
        assert tmpl.variables == []
        result = prompt_manager.render(tmpl, {})
        assert len(result.messages) == 1
        assert result.messages[0]["content"] == "Be helpful."
