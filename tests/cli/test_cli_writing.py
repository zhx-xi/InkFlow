"""CLI 写作命令集成测试 — CliRunner + Mock WritingService。

测试范围：inkflow write next/continue/revise。
需 pytest marker: @pytest.mark.writing
"""

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app

from .conftest import _parse_json_output

runner = CliRunner()


class _FakeWritingService:
    """CLI 测试用假 WritingService — 返回预设 WritingStreamEvent，不触发真实 LLM.

    F23（spec §4，Q3 拍板）: CLI 默认流式——只消费 stream_generate /
    stream_continue / stream_revise；非流式三方法保留仅供对照（CLI 不再调用）。
    """

    def __init__(self, *args, **kwargs):
        pass

    async def generate_chapter(self, request):
        return _preset_writing_result("generate")

    async def continue_writing(self, request):
        return _preset_writing_result("continue")

    async def revise_content(self, request):
        return _preset_writing_result("revise")

    async def stream_generate(self, request):
        for event in _preset_stream_events("generate"):
            yield event

    async def stream_continue(self, request):
        for event in _preset_stream_events("continue"):
            yield event

    async def stream_revise(self, request):
        for event in _preset_stream_events("revise"):
            yield event


def _preset_stream_events(mode: str):
    """F23 流式事件序列 — delta（全文单帧）+ done 帧，镜像 _preset_writing_result 字段."""
    from inkflow.domain.models.writing import WritingStreamEvent
    from inkflow.domain.ports.llm_client import TokenUsage

    yield WritingStreamEvent(delta="# 试炼场风波\n\n清晨的薄雾尚未散尽……")
    yield WritingStreamEvent(
        done=True,
        format_valid=True,
        word_count=2347,
        model="deepseek/deepseek-chat",
        token_usage=TokenUsage(
            prompt_tokens=1820, completion_tokens=2600, total_tokens=4420
        ),
        warnings=[],
    )


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
        assert all(cmd in result.stdout for cmd in ["next", "continue", "revise"])

    @pytest.mark.writing
    def test_write_next_human(self, isolated_db, monkeypatch):
        """next 默认人类可读输出."""
        self._patch_write_services(monkeypatch, _FakeWritingService())
        result = runner.invoke(
            app,
            [
                "write",
                "next",
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
    def test_write_next_json(self, isolated_db, monkeypatch):
        """next --json 输出 WritingResult JSON."""
        self._patch_write_services(monkeypatch, _FakeWritingService())
        result = runner.invoke(
            app,
            [
                "--json",
                "write",
                "next",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--outline",
                "主角踏入试炼场",
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
                "--json",
                "write",
                "continue",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--target-words",
                "3000",
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
                "--json",
                "write",
                "revise",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--instruction",
                "节奏太慢，删减环境描写",
                "--range",
                "第 3 段",
            ],
        )
        assert result.exit_code == 0, result.output
        data = _parse_json_output(result.output)
        assert data["mode"] == "revise"
        assert data["word_count"] == 2347

    @pytest.mark.writing
    def test_write_next_llm_error(self, isolated_db, monkeypatch):
        """LLM 调用失败 → 退出码 1，stderr 输出错误信息（F23: 流中异常 → LLM_ERROR）."""
        from inkflow.domain.ports.llm_errors import LLMRequestError

        class _FailingService:
            async def stream_generate(self, request):
                raise LLMRequestError("LLM 调用失败，请稍后重试")
                yield  # pragma: no cover — 使函数为 async generator，首个 next() 即抛异常

        self._patch_write_services(monkeypatch, _FailingService())
        result = runner.invoke(
            app,
            [
                "write",
                "next",
                "--project-id",
                "11111111-1111-1111-1111-111111111111",
                "--chapter-id",
                "22222222-2222-2222-2222-222222222222",
                "--outline",
                "主角踏入试炼场",
            ],
        )
        assert result.exit_code == 1
        assert "LLM 调用失败" in result.stderr
