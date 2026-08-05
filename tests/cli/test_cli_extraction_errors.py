"""F14 提取 CLI 命令测试（错误映射部分）— Mock ExtractionService 隔离数据库。

从 test_cli_extraction.py 拆分（monster-file 护栏）：
TestExtractRunErrorMapping / TestExtractStatusEdgeBranches。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
import typer
from pydantic import ValidationError
from typer.testing import CliRunner

from inkflow.cli.commands.extract import app
from inkflow.cli.context import CliContext
from inkflow.domain.models.extraction import (
    ExtractionResult,
    ExtractionRun,
    ExtractionStatus,
    ExtractionType,
)
from inkflow.domain.ports.extraction_errors import (
    ExtractionServiceError,
    UnsupportedExtractionTypeError,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.style_errors import StyleValidationError

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


class TestExtractRunErrorMapping:
    """错误码映射补全（spec §4/§7）：UNSUPPORTED_TYPE / VALIDATION_ERROR（服务/风格/参数
    校验）/ LLM_ERROR / DB_ERROR / typer.Exit 透传；人类模式无警告分支。"""

    def test_run_unsupported_type_error(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """Service 抛 UnsupportedExtractionTypeError → UNSUPPORTED_TYPE 信封 + 退出码 1."""
        mock_extraction_service.extract.side_effect = UnsupportedExtractionTypeError(
            "不支持的提取类型: novel"
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
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "UNSUPPORTED_TYPE"

    def test_run_extraction_service_error(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """Service 抛 ExtractionServiceError（类型参数约束）→ VALIDATION_ERROR + 退出码 1."""
        mock_extraction_service.extract.side_effect = ExtractionServiceError(
            "类型参数约束不满足"
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
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "类型参数约束不满足" in data["error"]["message"]

    def test_run_style_validation_error(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """Service 抛 StyleValidationError（F16 章节校验）→ VALIDATION_ERROR + 退出码 1."""
        mock_extraction_service.extract.side_effect = StyleValidationError(
            "文本不能为空"
        )
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
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_run_llm_error(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """Service 抛 LLMRequestError → LLM_ERROR 信封 + 退出码 1."""
        mock_extraction_service.extract.side_effect = LLMRequestError("LLM 调用失败")
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
        assert data["error"]["code"] == "LLM_ERROR"

    def test_run_pydantic_validation_error(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """ExtractionRequest 校验失败（pydantic ValidationError）→ VALIDATION_ERROR，
        多条消息以 '; ' 连接."""
        mock_extraction_service.extract.side_effect = (
            ValidationError.from_exception_data(
                "ExtractionRequest",
                [
                    {
                        "type": "string_type",
                        "loc": ("text",),
                        "msg": "Input should be a valid string",
                        "input": 123,
                    },
                    {
                        "type": "int_type",
                        "loc": ("num_chapters",),
                        "msg": "Input should be a valid integer",
                        "input": "x",
                    },
                ],
            )
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
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert (
            "Input should be a valid string; Input should be a valid integer"
            in data["error"]["message"]
        )

    def test_run_pydantic_validation_error_empty_messages(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """pydantic 错误消息为空 → 兜底文案「参数校验失败」."""
        mock_extraction_service.extract.side_effect = (
            ValidationError.from_exception_data("ExtractionRequest", [])
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
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert data["error"]["message"] == "参数校验失败"

    def test_run_db_error(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """其余异常 → DB_ERROR 错误信封 + 退出码 1."""
        mock_extraction_service.extract.side_effect = RuntimeError("数据库连接失败")
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
        assert data["error"]["code"] == "DB_ERROR"
        assert "数据库连接失败" in data["error"]["message"]

    def test_run_typer_exit_reraises(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """Service 抛 typer.Exit → _run 原样透传（退出码 3，不映射错误信封）."""
        mock_extraction_service.extract.side_effect = typer.Exit(3)
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
        assert result.exit_code == 3

    def test_run_human_no_warnings(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """人类模式 result.warnings 为空 → 摘要不含警告计数（spec §4.3 条件行）."""
        mock_extraction_service.extract.return_value = _make_result(warnings=[])
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
            "✅ 提取完成: character 处理 2 个源（跳过 0），新增 3 更新 2"
            in result.output
        )
        assert "警告" not in result.output

    def test_run_text_file_and_chapters_exit_2(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """--text-file 与 --chapters 同时使用 → 退出码 2（三选一互斥第三分支）."""
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--project-id",
                str(PID),
                "--type",
                "character",
                "--text-file",
                "chapter.txt",
                "--chapters",
                str(CH1),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_extraction_service.extract.assert_not_awaited()


class TestExtractStatusEdgeBranches:
    def test_status_human_unindexed_run(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """status 人类模式 indexed=False 的 success run → 不输出「已索引」."""
        mock_extraction_service.list_runs.return_value = (
            [_make_run(indexed=False)],
            1,
        )
        result = cli_runner.invoke(
            app,
            ["status", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert (
            f"  [character] {CH1} — ✅ success (2026-08-02 10:00, 新增 2 更新 1)"
            in (result.output)
        )
        assert "已索引" not in result.output
