"""F14 提取 CLI 命令测试（错误映射部分）— Mock ensure_kernel + InkFlowHTTPClient。

从 test_cli_extraction.py 拆分（monster-file 护栏）：
TestExtractRunErrorMapping / TestExtractStatusEdgeBranches。

F38 改造（#169）：mock 目标从 domain Service 迁移到 ensure_kernel + InkFlowHTTPClient
（HTTP JSON 响应）；create_tables patch 已移除。

── RED 形态说明 ─────────────────────────────────────────────
- fake_http_client fixture patch 命令模块命名空间
  （inkflow.cli.commands.extract.ensure_kernel / .InkFlowHTTPClient）——当前命令模块
  尚无这两个属性 → fixture setup 抛 AttributeError → 相关用例 ERROR（同根因，
  预期 RED；GREEN 命令改造落地后自动转绿）。
- HttpApiError 在用例体内惰性导入：RED 阶段 inkflow.infrastructure.http 尚未实现，
  顶部 import 会使整文件收集失败（ModuleNotFoundError），无法呈现上述预期形态。

── 端点契约（spec §3.1/§5.3）──────────────────────────────
- run → POST /extract；status → GET /projects/{pid}/extractions/runs
- 错误映射：404 → NOT_FOUND；422 → VALIDATION_ERROR；500 +
  X-InkFlow-Error-Code: LLM_ERROR → LLM_ERROR（extract 含 LLM 路径，测试以
  code="LLM_ERROR" 模拟响应头——父侧拍板保留 LLM_ERROR 语义）；500 无头 →
  INTERNAL_ERROR。
  ⚠️ 错误码语义变更（恒 HTTP 后 CLI 只见状态码 + detail）：UNSUPPORTED_TYPE
  （UnsupportedExtractionTypeError → API 422）→ VALIDATION_ERROR；RAG_ERROR /
  EXTRACTION_ERROR / DB_ERROR → INTERNAL_ERROR（spec §5.3 注）。detail 文本
  透传，message 可读性保留。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import typer
from typer.testing import CliRunner

from inkflow.cli.commands.extract import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CH1 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP（F38 mock 轨）。"""
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(
            "inkflow.cli.commands.extract.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.extract.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _make_result(**overrides: object) -> dict:
    """构造测试用 ExtractionResult JSON dict（枚举 → 字符串）."""
    defaults: dict[str, object] = dict(
        type="character",
        status="success",
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
    return defaults


def _make_run(**overrides: object) -> dict:
    """构造测试用 ExtractionRun JSON dict（run_at → ISO 字符串）."""
    defaults: dict[str, object] = dict(
        id=1,
        project_id=str(PID),
        type="character",
        source_key=str(CH1),
        content_hash="abc123",
        status="success",
        created_count=2,
        updated_count=1,
        warnings_json="[]",
        error=None,
        model="deepseek-v3",
        indexed=True,
        run_at="2026-08-02T10:00:00",
    )
    defaults.update(overrides)
    return defaults


class TestExtractRunErrorMapping:
    """错误码映射补全（spec §4/§5.3）：VALIDATION_ERROR（参数/业务校验）/
    LLM_ERROR / INTERNAL_ERROR / typer.Exit 透传；人类模式无警告分支。"""

    def test_run_unsupported_type_validation_error(self, cli_runner, fake_http_client):
        """API 422（不支持的提取类型）→ VALIDATION_ERROR 信封 + 退出码 1.

        恒 HTTP 后 UnsupportedExtractionTypeError 在内核侧映射 422，CLI 只见
        状态码 → UNSUPPORTED_TYPE 坍缩为 VALIDATION_ERROR（spec §5.3）。
        """
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(422, "不支持的提取类型: novel")
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

    def test_run_extraction_service_error(self, cli_runner, fake_http_client):
        """API 422（类型参数约束）→ VALIDATION_ERROR + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(422, "类型参数约束不满足")
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

    def test_run_style_validation_error(self, cli_runner, fake_http_client):
        """API 422（F16 章节校验）→ VALIDATION_ERROR + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(422, "文本不能为空")
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

    def test_run_llm_error(self, cli_runner, fake_http_client):
        """LLM 调用失败（500 + LLM_ERROR 错误码头）→ LLM_ERROR 信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(
            500, "LLM 调用失败，请稍后重试", code="LLM_ERROR"
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
        assert data["error"]["code"] == "LLM_ERROR"

    def test_run_pydantic_validation_error(self, cli_runner, fake_http_client):
        """API 422（参数校验失败）→ VALIDATION_ERROR，detail 多消息 '; ' 连接透传."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(
            422, "Input should be a valid string; Input should be a valid integer"
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
        self, cli_runner, fake_http_client
    ):
        """detail 为空 → 兜底文案「参数校验失败」透传."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(422, "参数校验失败")
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

    def test_run_internal_error(self, cli_runner, fake_http_client):
        """HTTP 500 无错误码头 → INTERNAL_ERROR 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(500, "数据库连接失败")
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
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert "数据库连接失败" in data["error"]["message"]

    def test_run_typer_exit_reraises(self, cli_runner, fake_http_client):
        """Client 抛 typer.Exit → 原样透传（退出码 3，不映射错误信封）."""
        fake_http_client.post.side_effect = typer.Exit(3)
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

    def test_run_human_no_warnings(self, cli_runner, fake_http_client):
        """人类模式 result.warnings 为空 → 摘要不含警告计数（spec §4.3 条件行）."""
        fake_http_client.post.return_value = _make_result(warnings=[])
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

    def test_run_text_file_and_chapters_exit_2(self, cli_runner, fake_http_client):
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
        fake_http_client.post.assert_not_awaited()


class TestExtractStatusEdgeBranches:
    def test_status_human_unindexed_run(self, cli_runner, fake_http_client):
        """status 人类模式 indexed=False 的 success run → 不输出「已索引」."""
        fake_http_client.get.return_value = {
            "items": [_make_run(indexed=False)],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
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
