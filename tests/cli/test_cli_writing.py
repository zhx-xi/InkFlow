"""CLI 写作命令集成测试 — CliRunner + Mock WritingService。

测试范围：inkflow write generate/continue/revise。
需 pytest marker: @pytest.mark.writing
"""

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app

from .conftest import _parse_json_output

runner = CliRunner()


class _FakeWritingService:
    """CLI 测试用假 WritingService — 返回预设 WritingResult，不触发真实 LLM."""

    def __init__(self, *args, **kwargs):
        pass

    async def generate_chapter(self, request):
        return _preset_writing_result("generate")

    async def continue_writing(self, request):
        return _preset_writing_result("continue")

    async def revise_content(self, request):
        return _preset_writing_result("revise")


def _preset_writing_result(mode: str):
    from inkflow.domain.models.writing import WritingMode, WritingResult
    from inkflow.domain.ports.llm_client import TokenUsage

    return WritingResult(
        content="# 试炼场风波\n\n清晨的薄雾尚未散尽……",
        word_count=2347,
        mode=WritingMode(mode),
        format_valid=True,
        retry_count=1,
        model="deepseek/deepseek-chat",
        token_usage=TokenUsage(
            prompt_tokens=1820, completion_tokens=2600, total_tokens=4420
        ),
        warnings=[],
    )


class TestWriteCLI:
    """inkflow write 子命令测试 — Mock WritingService/ChapterService."""

    def _patch_write_services(self, monkeypatch, fake_service):
        import inkflow.cli.commands.write as write_mod

        monkeypatch.setattr(write_mod, "_build_service", lambda session: fake_service)

        class _FakeChapter:
            content = "已有内容。" * 30

        class _FakeChapterRepo:
            def __init__(self, *args, **kwargs):
                pass

            async def get_chapter(self, chapter_id):
                return _FakeChapter()

        monkeypatch.setattr(write_mod, "SQLiteChapterRepository", _FakeChapterRepo)

    @pytest.mark.writing
    def test_write_help(self):
        """inkflow write --help 正常且包含三个子命令."""
        result = runner.invoke(app, ["write", "--help"])
        assert result.exit_code == 0
        assert "AI 写作" in result.stdout
        assert all(cmd in result.stdout for cmd in ["generate", "continue", "revise"])

    @pytest.mark.writing
    def test_write_generate_human(self, isolated_db, monkeypatch):
        """generate 默认人类可读输出."""
        self._patch_write_services(monkeypatch, _FakeWritingService())
        result = runner.invoke(
            app,
            [
                "write",
                "generate",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--outline",
                "主角踏入试炼场",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "章节生成成功" in result.output
        assert "2347 字" in result.output

    @pytest.mark.writing
    def test_write_generate_json(self, isolated_db, monkeypatch):
        """generate --json 输出 WritingResult JSON."""
        self._patch_write_services(monkeypatch, _FakeWritingService())
        result = runner.invoke(
            app,
            [
                "write",
                "generate",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--outline",
                "主角踏入试炼场",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = _parse_json_output(result.output)
        assert data["mode"] == "generate"
        assert data["word_count"] == 2347
        assert data["format_valid"] is True

    @pytest.mark.writing
    def test_write_continue_json(self, isolated_db, monkeypatch):
        """continue --json 输出 WritingResult JSON."""
        self._patch_write_services(monkeypatch, _FakeWritingService())
        result = runner.invoke(
            app,
            [
                "write",
                "continue",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--target-words",
                "3000",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = _parse_json_output(result.output)
        assert data["mode"] == "continue"
        assert data["word_count"] == 2347

    @pytest.mark.writing
    def test_write_revise_json(self, isolated_db, monkeypatch):
        """revise --json 输出 WritingResult JSON."""
        self._patch_write_services(monkeypatch, _FakeWritingService())
        result = runner.invoke(
            app,
            [
                "write",
                "revise",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--feedback",
                "节奏太慢，删减环境描写",
                "--range",
                "第 3 段",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = _parse_json_output(result.output)
        assert data["mode"] == "revise"
        assert data["word_count"] == 2347

    @pytest.mark.writing
    def test_write_generate_llm_error(self, isolated_db, monkeypatch):
        """LLM 调用失败 → 退出码 1."""
        from inkflow.domain.ports.llm_errors import LLMRequestError

        class _FailingService:
            async def generate_chapter(self, request):
                raise LLMRequestError("LLM 调用失败，请稍后重试")

        self._patch_write_services(monkeypatch, _FailingService())
        result = runner.invoke(
            app,
            [
                "write",
                "generate",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--outline",
                "主角踏入试炼场",
            ],
        )
        assert result.exit_code == 1
        assert isinstance(result.exception, LLMRequestError)
