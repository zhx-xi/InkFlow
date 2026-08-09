"""F14 提取 CLI 命令测试（CRUD/status 部分）— Mock ensure_kernel + InkFlowHTTPClient。

从 test_cli_extraction.py 拆分（monster-file 护栏）：
TestExtractRegistration / TestExtractRun / TestExtractStatus。

F38 改造（#169）：mock 目标从 domain Service 迁移到 ensure_kernel + InkFlowHTTPClient
（HTTP JSON 响应）；create_tables patch 已移除。

── RED 形态说明 ─────────────────────────────────────────────
- fake_http_client fixture patch 命令模块命名空间
  （inkflow.cli.commands.extract.ensure_kernel / .InkFlowHTTPClient）——当前命令模块
  尚无这两个属性 → fixture setup 抛 AttributeError → 相关用例 ERROR（同根因，
  预期 RED；GREEN 命令改造落地后自动转绿）。
- HttpApiError 在用例体内惰性导入：RED 阶段 inkflow.infrastructure.http 尚未实现，
  顶部 import 会使整文件收集失败（ModuleNotFoundError），无法呈现上述预期形态。

── 端点契约（spec §3.1 表）────────────────────────────────
- run → POST /extract（body = ExtractionRequest 字段，project_id 在 body 内——
  端点扁平无路径参数；type/text/chapter_ids/prompt/num_chapters/save/
  auto_extract/index/force 等，JSON 形态：枚举 → 字符串、UUID → 字符串）
- status → GET /projects/{pid}/extractions/runs（params: type；响应
  {"items": [...], "total", "offset", "limit"} 信封）
- 错误映射（spec §5.3）：404 → NOT_FOUND；422 → VALIDATION_ERROR；
  500 + X-InkFlow-Error-Code: LLM_ERROR → LLM_ERROR（extract 含 LLM 路径，
  测试以 code="LLM_ERROR" 模拟响应头——父侧拍板保留 LLM_ERROR 语义）；
  500 无头 → INTERNAL_ERROR。
  ⚠️ 错误码语义变更（恒 HTTP 后 CLI 只见状态码 + detail）：RAG_ERROR
  （RAGUnavailableError）→ INTERNAL_ERROR；EXTRACTION_ERROR
  （ForeshadowingExtractionError 等）→ INTERNAL_ERROR；DB_ERROR →
  INTERNAL_ERROR（spec §5.3 注）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.extract import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CH1 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000001")
CH2 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000002")


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


class TestExtractRegistration:
    def test_group_help_lists_all_commands(self):
        """extract 组帮助包含 run/status 两个命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）."""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in ("run", "status"):
            assert name in result.output


class TestExtractRun:
    def test_run_character_text_json(self, cli_runner, fake_http_client):
        """run --type character --text --json → 成功信封 + ExtractionRequest body 透传."""
        fake_http_client.post.return_value = _make_result(
            type="character", indexed=False
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
        call = fake_http_client.post.await_args
        assert call.args[0] == "/extract"
        body: dict = call.kwargs["json"]
        assert body["project_id"] == str(PID)
        assert body["type"] == "character"
        assert "林晚推开柴门" in body["text"]
        assert body["chapter_ids"] is None
        assert body["index"] is False

    def test_run_text_file(self, cli_runner, fake_http_client, tmp_path):
        """--text-file 读取文件内容作为 text 透传."""
        src = tmp_path / "chapter.txt"
        src.write_text("第一章：林晚在山神庙中醒来。", encoding="utf-8")
        fake_http_client.post.return_value = _make_result()
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
        body: dict = fake_http_client.post.await_args.kwargs["json"]
        assert body["text"] == "第一章：林晚在山神庙中醒来。"
        assert body["type"] == "setting"

    def test_run_chapters(self, cli_runner, fake_http_client):
        """--chapters 逗号分隔 UUID 列表 → chapter_ids 透传（JSON 字符串数组）."""
        fake_http_client.post.return_value = _make_result()
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
        body: dict = fake_http_client.post.await_args.kwargs["json"]
        assert body["chapter_ids"] == [str(CH1), str(CH2)]
        assert body["text"] is None

    def test_run_outline_params(self, cli_runner, fake_http_client):
        """outline 参数透传: --prompt/--num-chapters/--no-save."""
        fake_http_client.post.return_value = _make_result(
            type="outline", created=1, updated=0, warnings=[]
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
        body: dict = fake_http_client.post.await_args.kwargs["json"]
        assert body["type"] == "outline"
        assert body["prompt"] == "都市异能，双女主"
        assert body["num_chapters"] == 20
        assert body["save"] is False

    def test_run_timeline_auto_extract(self, cli_runner, fake_http_client):
        """--auto-extract 显式开启 timeline 设置项覆盖."""
        fake_http_client.post.return_value = _make_result(
            type="timeline", indexed=False
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
        body: dict = fake_http_client.post.await_args.kwargs["json"]
        assert body["auto_extract"] is True

    def test_run_timeline_no_auto_extract(self, cli_runner, fake_http_client):
        """--no-auto-extract 显式关闭 timeline 设置项覆盖."""
        fake_http_client.post.return_value = _make_result(
            type="timeline", indexed=False
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
        body: dict = fake_http_client.post.await_args.kwargs["json"]
        assert body["auto_extract"] is False

    def test_run_index_force(self, cli_runner, fake_http_client):
        """--index --force → index=True + force=True 透传."""
        fake_http_client.post.return_value = _make_result()
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
        body: dict = fake_http_client.post.await_args.kwargs["json"]
        assert body["index"] is True
        assert body["force"] is True

    def test_run_human_success(self, cli_runner, fake_http_client):
        """run 人类模式 success → ✅ 提取完成 摘要（处理/跳过/新增/更新/警告）."""
        fake_http_client.post.return_value = _make_result()
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

    def test_run_human_skipped(self, cli_runner, fake_http_client):
        """run 人类模式 skipped → ⏭ 提取跳过（含原因，未调用 LLM）."""
        fake_http_client.post.return_value = _make_result(
            status="skipped",
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

    def test_run_style_success(self, cli_runner, fake_http_client):
        """--type style → 正常执行：退出码 0 + ✅ 提取完成摘要（F16 落地，spec §4.1/§8.2）。

        门面结果归一（spec §8.2 表 #6）: created=0/updated=0/model=None、
        detail 为 StyleReport JSON（不落实体）；STYLE 不再是 UNSUPPORTED_TYPE。
        """
        style_detail = {
            "project_id": str(PID),
            "source": "manual",
            "generated_at": "2026-08-02T10:00:00",
            "fingerprint": {
                "char_count": 48,
                "sentence_count": 3,
                "avg_sentence_length": 16.0,
                "sentence_length_std": 9.9,
                "paragraph_count": 1,
                "avg_paragraph_length": 48.0,
                "punctuation_density": 0.1667,
                "exclamation_density": 0.0,
                "ellipsis_density": 0.0417,
                "dialogue_ratio": 0.2083,
                "vocabulary_richness": 0.8235,
                "top_words": [{"word": "林晚", "count": 1, "first_index": 0}],
            },
            "ai_trace": {
                "ai_score": 0.26,
                "verdict": "likely_human",
                "features": [],
                "evidence": [],
            },
            "lexical": {
                "total_words": 17,
                "unique_words": 14,
                "top_words": [],
                "avg_word_length": 2.1,
                "stopword_ratio": 0.0588,
                "jieba": None,
            },
            "llm_assessment": None,
            "warnings": [],
        }
        fake_http_client.post.return_value = _make_result(
            type="style",
            status="success",
            processed_sources=1,
            skipped_sources=0,
            created=0,
            updated=0,
            warnings=["style 类型不支持自动索引"],
            model=None,
            indexed=False,
            detail=style_detail,
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
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert (
            "✅ 提取完成: style 处理 1 个源（跳过 0），新增 0 更新 0，警告 1 条"
            in result.output
        )
        body: dict = fake_http_client.post.await_args.kwargs["json"]
        assert body["type"] == "style"
        assert body["text"] == "林晚"

    def test_run_project_not_found(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(404, "项目不存在")
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

    def test_run_invalid_uuid(self, cli_runner, fake_http_client):
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
        fake_http_client.post.assert_not_awaited()

    def test_run_internal_error(self, cli_runner, fake_http_client):
        """index=true 但向量库不可用（HTTP 500 无错误码头）→ INTERNAL_ERROR + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(500, "向量库未装配")
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
        assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_run_extraction_internal_error(self, cli_runner, fake_http_client):
        """管线解析失败（HTTP 500 无错误码头）→ INTERNAL_ERROR 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(
            500, "3 次尝试后仍无法解析为合法 JSON"
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
        assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_run_text_and_text_file_exit_2(self, cli_runner, fake_http_client):
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
        fake_http_client.post.assert_not_awaited()

    def test_run_text_and_chapters_exit_2(self, cli_runner, fake_http_client):
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
        fake_http_client.post.assert_not_awaited()

    def test_run_invalid_type_exit_2(self, cli_runner, fake_http_client):
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
        fake_http_client.post.assert_not_awaited()


class TestExtractStatus:
    def test_status_json(self, cli_runner, fake_http_client):
        """status --json → 成功信封 + runs 数组（items/total）+ --type 过滤透传."""
        fake_http_client.get.return_value = {
            "items": [
                _make_run(),
                _make_run(id=2, type="setting", indexed=False),
            ],
            "total": 2,
            "offset": 0,
            "limit": 50,
        }
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
        call = fake_http_client.get.await_args
        assert call.args[0] == f"/projects/{PID}/extractions/runs"
        assert call.kwargs["params"]["type"] == "character"

    def test_status_human(self, cli_runner, fake_http_client):
        """status 人类模式 → 📋 状态行（success/skipped/error 三态）."""
        fake_http_client.get.return_value = {
            "items": [
                _make_run(),
                _make_run(
                    id=2,
                    type="setting",
                    status="skipped",
                    source_key="manual",
                ),
                _make_run(
                    id=3,
                    type="foreshadowing",
                    status="error",
                    source_key="manual",
                    error="3 次尝试后仍无法解析为合法 JSON",
                ),
            ],
            "total": 3,
            "offset": 0,
            "limit": 50,
        }
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

    def test_status_human_empty(self, cli_runner, fake_http_client):
        """无记录人类模式 → 暂无提取记录."""
        fake_http_client.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            app,
            ["status", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无提取记录" in result.output

    def test_status_invalid_type_exit_2(self, cli_runner, fake_http_client):
        """status --type 非法值 → 退出码 2."""
        result = cli_runner.invoke(
            app,
            ["status", "--project-id", str(PID), "--type", "bogus"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.get.assert_not_awaited()
