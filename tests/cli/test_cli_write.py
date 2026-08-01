"""Write CLI 命令测试."""

import json
import types
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.write import app
from inkflow.cli.context import CliContext
from inkflow.domain.models.writing import WritingMode, WritingResult
from inkflow.domain.ports.llm_errors import LLMRequestError

_EXISTING_CONTENT = (
    "这是已有的章节内容，用于测试续写与修订功能。这一段文本足够长，"
    "以通过续写请求对已有内容的最少字符数校验要求，同时也满足修订请求"
    "对内容长度的基本校验。"
)


@pytest.fixture
def cli_runner(monkeypatch):
    # CI 彩色环境（GITHUB_ACTIONS/FORCE_COLOR）下，Typer 0.27 在 import 时把
    # rich_utils.FORCE_TERMINAL 固定为 True，help 渲染强制带样式，选项名
    # "--count" 被高亮器拆成 ANSI span（"-count"），导致文本断言脆弱。
    # 禁用强制终端渲染 + NO_COLOR，恢复无样式输出。
    monkeypatch.setattr("typer.rich_utils.FORCE_TERMINAL", False)
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def mock_writing_service():
    """Mock WritingService + 相关依赖."""
    with patch(
        "inkflow.cli.commands.write.WritingService", autospec=True
    ) as mock_svc_cls:
        mock_svc = AsyncMock()
        mock_svc_cls.return_value = mock_svc

        with patch("inkflow.cli.commands.write.LangChainLLMClient", autospec=True):
            with patch(
                "inkflow.cli.commands.write.LangChainPromptManager", autospec=True
            ):
                with patch(
                    "inkflow.cli.commands.write.NullContextProvider", autospec=True
                ):
                    with patch(
                        "inkflow.cli.commands.write.SQLiteChapterRepository",
                        autospec=True,
                    ) as mock_repo_cls:
                        mock_repo = AsyncMock()
                        mock_repo_cls.return_value = mock_repo
                        mock_repo.get_chapter.return_value = types.SimpleNamespace(
                            content=_EXISTING_CONTENT
                        )
                        yield mock_svc


class TestWriteNext:
    def test_next_json(self, cli_runner, mock_writing_service):
        """write next --json 成功."""
        mock_writing_service.generate_chapter.return_value = WritingResult(
            content="test content",
            word_count=100,
            mode=WritingMode.GENERATE,
            format_valid=True,
            retry_count=0,
            model="test-model",
        )
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["content"] == "test content"
        mock_writing_service.generate_chapter.assert_awaited_once()

    def test_next_count_param(self, cli_runner, mock_writing_service):
        """write next --count / --show-context 参数出现在 help."""
        result = cli_runner.invoke(
            app, ["next", "--help"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "--count" in result.output
        assert "--show-context" in result.output

    def test_next_show_context_placeholder(self, cli_runner, mock_writing_service):
        """--show-context 占位打印."""
        mock_writing_service.generate_chapter.return_value = WritingResult(
            content="test content",
            word_count=100,
            mode=WritingMode.GENERATE,
            format_valid=True,
            retry_count=0,
            model="test-model",
        )
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
                "--show-context",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "(--show-context 功能将在 F6 联调时启用)" in result.output

    def test_next_llm_error(self, cli_runner, mock_writing_service):
        """LLM 错误映射为 LLM_ERROR 信封."""
        mock_writing_service.generate_chapter.side_effect = LLMRequestError(
            "provider down"
        )
        result = cli_runner.invoke(
            app,
            [
                "next",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--outline",
                "test outline",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "LLM_ERROR"

    def test_generate_renamed_to_next(self, cli_runner):
        """generate 命令已移除（重命名为 next）."""
        result = cli_runner.invoke(
            app, ["generate", "--help"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 2
        assert "No such command" in result.stderr


class TestWriteContinue:
    def test_continue_json(self, cli_runner, mock_writing_service):
        """write continue --json 成功."""
        mock_writing_service.continue_writing.return_value = WritingResult(
            content="continued",
            word_count=50,
            mode=WritingMode.CONTINUE,
            format_valid=True,
            retry_count=0,
            model="test-model",
        )
        result = cli_runner.invoke(
            app,
            [
                "continue",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["content"] == "continued"


class TestWriteRevise:
    def test_revise_json(self, cli_runner, mock_writing_service):
        """write revise --instruction --json 成功."""
        mock_writing_service.revise_content.return_value = WritingResult(
            content="revised",
            word_count=80,
            mode=WritingMode.REVISE,
            format_valid=True,
            retry_count=0,
            model="test-model",
        )
        result = cli_runner.invoke(
            app,
            [
                "revise",
                "--project-id",
                str(uuid.uuid4()),
                "--chapter-id",
                str(uuid.uuid4()),
                "--instruction",
                "改短一点",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["content"] == "revised"

    def test_revise_feedback_removed(self, cli_runner):
        """--feedback 已改名为 --instruction."""
        result = cli_runner.invoke(
            app, ["revise", "--feedback", "x"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 2
        assert "No such option" in result.stderr
