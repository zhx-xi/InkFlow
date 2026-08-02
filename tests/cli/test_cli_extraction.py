"""F14 提取 CLI 命令测试 — Mock ExtractionService 隔离数据库（spec §4/§9 CLI 测试）.

覆盖（依据 specs/f14-extraction-service/spec.md §4/§9）:
- extract run 各类型参数透传（--text/--text-file/--chapters 三选一、--prompt、
  --num-chapters、--no-save、--auto-extract/--no-auto-extract、--index、--force）
- success/skipped 人类可读输出与 --json 信封
- extract status 人类可读与 --json（含 --type 过滤透传）
- 信封格式与退出码 0/1/2；STYLE → UNSUPPORTED_TYPE 信封（退出码 1）；
  NOT_FOUND / RAG_ERROR / EXTRACTION_ERROR 信封
- --text 与 --text-file 同时使用 → 退出码 2；--type 非法值 → 退出码 2
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.extract import app
from inkflow.cli.context import CliContext
from inkflow.domain.models.extraction import (
    ExtractionResult,
    ExtractionRun,
    ExtractionStatus,
    ExtractionType,
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import RAGUnavailableError
from inkflow.domain.ports.foreshadowing_errors import ForeshadowingExtractionError

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CH1 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000001")
CH2 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000002")


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def mock_extraction_service():
    """Mock ExtractionService，绕过数据库（ADR-015 依赖注入）."""
    with patch(
        "inkflow.cli.commands.extract.ExtractionService", autospec=True
    ) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_create_tables():
    """Mock create_tables 避免数据库初始化."""
    with patch("inkflow.cli.commands.extract.create_tables", AsyncMock()):
        yield


def _make_result(**overrides) -> ExtractionResult:
    """构造测试用 ExtractionResult 领域对象."""
    defaults = dict(
        type=ExtractionType.CHARACTER,
        status=ExtractionStatus.SUCCESS,
        skipped_reason=None,
        processed_sources=2,
        skipped_sources=0,
        created=3,
        updated=2,
        warnings=["解析跳过 1 个条目"],
        model="deepseek-v3",
        indexed=True,
        detail={"created": [], "updated": []},
    )
    defaults.update(overrides)
    return ExtractionResult(**defaults)


def _make_run(**overrides) -> ExtractionRun:
    """构造测试用 ExtractionRun 领域对象."""
    defaults = dict(
        id=1,
        project_id=PID,
        type=ExtractionType.CHARACTER,
        source_key=str(CH1),
        content_hash="abc123",
        status=ExtractionStatus.SUCCESS,
        created_count=2,
        updated_count=1,
        warnings_json="[]",
        error=None,
        model="deepseek-v3",
        indexed=True,
        run_at=datetime(2026, 8, 2, 10, 0, 0),
    )
    defaults.update(overrides)
    return ExtractionRun(**defaults)


class TestExtractRegistration:
    def test_group_help_lists_all_commands(self):
        """extract 组帮助包含 run/status 两个命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）."""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in ("run", "status"):
            assert name in result.output


class TestExtractRun:
    def test_run_character_text_json(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """run --type character --text --json → 成功信封 + ExtractionRequest 透传."""
        mock_extraction_service.extract.return_value = _make_result(
            type=ExtractionType.CHARACTER, indexed=False
        )
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "character",
                "--text",
                "林晚推开柴门，月色下她右肩的胎记若隐若现。",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["type"] == "character"
        assert data["data"]["status"] == "success"
        assert data["data"]["created"] == 3
        call = mock_extraction_service.extract.await_args
        request = call.kwargs["request"]
        assert request.project_id == PID
        assert request.type is ExtractionType.CHARACTER
        assert "林晚推开柴门" in request.text
        assert request.chapter_ids is None
        assert request.index is False

    def test_run_text_file(
        self, cli_runner, mock_extraction_service, mock_create_tables, tmp_path
    ):
        """--text-file 读取文件内容作为 text 透传."""
        src = tmp_path / "chapter.txt"
        src.write_text("第一章：林晚在山神庙中醒来。", encoding="utf-8")
        mock_extraction_service.extract.return_value = _make_result()
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "setting",
                "--text-file",
                str(src),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_extraction_service.extract.await_args
        request = call.kwargs["request"]
        assert request.text == "第一章：林晚在山神庙中醒来。"
        assert request.type is ExtractionType.SETTING

    def test_run_chapters(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """--chapters 逗号分隔 UUID 列表 → chapter_ids 透传."""
        mock_extraction_service.extract.return_value = _make_result()
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "foreshadowing",
                "--chapters",
                f"{CH1},{CH2}",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_extraction_service.extract.await_args
        request = call.kwargs["request"]
        assert request.chapter_ids == [CH1, CH2]
        assert request.text is None

    def test_run_outline_params(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """outline 参数透传: --prompt/--num-chapters/--no-save."""
        mock_extraction_service.extract.return_value = _make_result(
            type=ExtractionType.OUTLINE, created=1, updated=0, warnings=[]
        )
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "outline",
                "--prompt",
                "都市异能，双女主",
                "--num-chapters",
                "20",
                "--no-save",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_extraction_service.extract.await_args
        request = call.kwargs["request"]
        assert request.type is ExtractionType.OUTLINE
        assert request.prompt == "都市异能，双女主"
        assert request.num_chapters == 20
        assert request.save is False

    def test_run_timeline_auto_extract(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """--auto-extract 显式开启 timeline 设置项覆盖."""
        mock_extraction_service.extract.return_value = _make_result(
            type=ExtractionType.TIMELINE, indexed=False
        )
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "timeline",
                "--chapters",
                str(CH1),
                "--auto-extract",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_extraction_service.extract.await_args
        request = call.kwargs["request"]
        assert request.auto_extract is True

    def test_run_timeline_no_auto_extract(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """--no-auto-extract 显式关闭 timeline 设置项覆盖."""
        mock_extraction_service.extract.return_value = _make_result(
            type=ExtractionType.TIMELINE, indexed=False
        )
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "timeline",
                "--no-auto-extract",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_extraction_service.extract.await_args
        request = call.kwargs["request"]
        assert request.auto_extract is False

    def test_run_index_force(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """--index --force → index=True + force=True 透传."""
        mock_extraction_service.extract.return_value = _make_result()
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "character",
                "--text",
                "林晚",
                "--index",
                "--force",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_extraction_service.extract.await_args
        request = call.kwargs["request"]
        assert request.index is True
        assert request.force is True

    def test_run_human_success(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """run 人类模式 success → ✅ 提取完成 摘要（处理/跳过/新增/更新/警告）."""
        mock_extraction_service.extract.return_value = _make_result()
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "character",
                "--chapters",
                f"{CH1},{CH2}",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert (
            "✅ 提取完成: character 处理 2 个源（跳过 0），新增 3 更新 2，警告 1 条"
            in result.output
        )

    def test_run_human_skipped(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """run 人类模式 skipped → ⏭ 提取跳过（含原因，未调用 LLM）."""
        mock_extraction_service.extract.return_value = _make_result(
            status=ExtractionStatus.SKIPPED,
            skipped_reason="内容未变更（源: chapter 7a4f2c91-...）",
        )
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "character",
                "--text",
                "林晚",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert (
            "⏭ 提取跳过: character 内容未变更（源: chapter 7a4f2c91-...），未调用 LLM"
            in result.output
        )

    def test_run_style_unsupported(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """--type style → UNSUPPORTED_TYPE 错误信封 + 退出码 1（F16 占位）."""
        from inkflow.domain.ports.extraction_errors import StyleNotImplementedError

        mock_extraction_service.extract.side_effect = StyleNotImplementedError()
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "style",
                "--text",
                "林晚",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "UNSUPPORTED_TYPE"
        assert "风格提取尚未实现" in data["error"]["message"]

    def test_run_project_not_found(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_extraction_service.extract.side_effect = ProjectNotFoundError()
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "character",
                "--text",
                "林晚",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_run_invalid_uuid(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """无效 project-id UUID → NOT_FOUND（spec §7: 无效 UUID → 404 语义）."""
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                "not-a-uuid",
                "--type",
                "character",
                "--text",
                "林晚",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        mock_extraction_service.extract.assert_not_awaited()

    def test_run_rag_error(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """index=true 但向量库不可用 → RAG_ERROR 错误信封 + 退出码 1."""
        mock_extraction_service.extract.side_effect = RAGUnavailableError()
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "character",
                "--text",
                "林晚",
                "--index",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "RAG_ERROR"

    def test_run_extraction_error(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """管线解析失败 → EXTRACTION_ERROR 错误信封 + 退出码 1."""
        mock_extraction_service.extract.side_effect = ForeshadowingExtractionError(
            "3 次尝试后仍无法解析为合法 JSON"
        )
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "foreshadowing",
                "--text",
                "林晚",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "EXTRACTION_ERROR"

    def test_run_text_and_text_file_exit_2(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """--text 与 --text-file 同时使用 → 退出码 2（F9 先例）."""
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "character",
                "--text",
                "林晚",
                "--text-file",
                "chapter.txt",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_extraction_service.extract.assert_not_awaited()

    def test_run_text_and_chapters_exit_2(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """--text 与 --chapters 同时使用 → 退出码 2（三选一互斥）."""
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "character",
                "--text",
                "林晚",
                "--chapters",
                str(CH1),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_extraction_service.extract.assert_not_awaited()

    def test_run_invalid_type_exit_2(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """--type 非法值 → 退出码 2（Typer Choice 校验）."""
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "bogus",
                "--text",
                "林晚",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_extraction_service.extract.assert_not_awaited()


class TestExtractStatus:
    def test_status_json(self, cli_runner, mock_extraction_service, mock_create_tables):
        """status --json → 成功信封 + runs 数组（items/total）+ --type 过滤透传."""
        mock_extraction_service.list_runs.return_value = (
            [_make_run(), _make_run(id=2, type=ExtractionType.SETTING, indexed=False)],
            2,
        )
        result = cli_runner.invoke(
            app,
            ["status", "--project-id", str(PID), "--type", "character"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["total"] == 2
        assert data["data"]["items"][0]["type"] == "character"
        assert data["data"]["items"][0]["source_key"] == str(CH1)
        assert data["data"]["items"][0]["created_count"] == 2
        assert data["data"]["items"][0]["indexed"] is True
        mock_extraction_service.list_runs.assert_awaited_once_with(
            project_id=PID, type=ExtractionType.CHARACTER, offset=0, limit=50
        )

    def test_status_human(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """status 人类模式 → 📋 状态行（success/skipped/error 三态）."""
        mock_extraction_service.list_runs.return_value = (
            [
                _make_run(),
                _make_run(
                    id=2,
                    type=ExtractionType.SETTING,
                    status=ExtractionStatus.SKIPPED,
                    source_key="manual",
                ),
                _make_run(
                    id=3,
                    type=ExtractionType.FORESHADOWING,
                    status=ExtractionStatus.ERROR,
                    source_key="manual",
                    error="3 次尝试后仍无法解析为合法 JSON",
                ),
            ],
            3,
        )
        result = cli_runner.invoke(
            app,
            ["status", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert f"📋 提取状态（project {PID}）:" in result.output
        assert (
            f"  [character] {CH1} — ✅ success (2026-08-02 10:00, 新增 2 更新 1, 已索引)"
            in result.output
        )
        assert "  [setting] manual — ⏭ skipped (内容未变更)" in result.output
        assert (
            "  [foreshadowing] manual — ❌ error (3 次尝试后仍无法解析为合法 JSON)"
            in result.output
        )

    def test_status_human_empty(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """无记录人类模式 → 暂无提取记录."""
        mock_extraction_service.list_runs.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            ["status", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无提取记录" in result.output

    def test_status_invalid_type_exit_2(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """status --type 非法值 → 退出码 2."""
        result = cli_runner.invoke(
            app,
            ["status", "--project-id", str(PID), "--type", "bogus"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_extraction_service.list_runs.assert_not_awaited()
