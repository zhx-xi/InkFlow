"""F16 风格检测 CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（spec §4/§9 CLI 测试）.

覆盖（依据 specs/f16-style-service/spec.md §4/§7/§9）:
- style 组注册（analyze 命令）
- analyze 人类可读输出（三大板块摘要 + 高频词前 5 + verdict 中文映射 +
  jieba 行 + LLM 行（开启时）+ warnings 逐条 + 末尾提示 --json）
- verdict 三档中文映射（likely_human→倾向人类创作 / uncertain→特征不明显 /
  likely_ai→倾向 AI 生成）；likely_ai 结论 → 退出码恒 0（结论是结果非错误，§12）
- analyze --json 完整报告信封（{"ok": true, "data": ...}）
- --text / --text-file / --chapters 三选一互斥：缺参 → 退出码 2；
  --text 与 --text-file 同时 → 退出码 2（Typer 参数校验，同 F14 先例）
- --llm-analysis / --no-llm-analysis 透传（缺省 None = 跟随项目配置，spec §2.8）
- 项目不存在 → NOT_FOUND 信封 + 退出码 1；StyleValidationError → VALIDATION_ERROR；
  LLM 深度分析不可用 → LLM_ERROR；内部错误 → INTERNAL_ERROR

F38 改造（#169）：mock 目标从 domain Service 迁移到 ensure_kernel + InkFlowHTTPClient
（HTTP JSON 响应）；create_tables patch 已移除。

── RED 形态说明 ─────────────────────────────────────────────
- fake_http_client fixture patch 命令模块命名空间
  （inkflow.cli.commands.style.ensure_kernel / .InkFlowHTTPClient）——当前命令模块
  尚无这两个属性 → fixture setup 抛 AttributeError → 相关用例 ERROR（同根因，
  预期 RED；GREEN 命令改造落地后自动转绿）。
- HttpApiError 在用例体内惰性导入：RED 阶段 inkflow.infrastructure.http 尚未实现，
  顶部 import 会使整文件收集失败（ModuleNotFoundError），无法呈现上述预期形态。

── 端点契约（spec §3.1 表）────────────────────────────────
- analyze → POST /projects/{pid}/style/analyze（body: text/chapter_ids/
  llm_analysis，StyleAnalyzeRequest 字段）
- 错误映射（spec §5.3）：404 → NOT_FOUND；422 → VALIDATION_ERROR；
  500 + X-InkFlow-Error-Code: LLM_ERROR → LLM_ERROR（style 含 LLM 路径，
  测试以 code="LLM_ERROR" 模拟响应头——父侧拍板保留 LLM_ERROR 语义）；
  500 无头 → INTERNAL_ERROR（DB_ERROR 恒 HTTP 后由 INTERNAL_ERROR 替代）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import typer
from typer.testing import CliRunner

from inkflow.cli.commands.style import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = "2026-08-02T12:00:00Z"
TEXT = "林晚推开窗，夜色如墨。她低声说：「三年了，我终究还是回来了。」"


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）。"""
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
            "inkflow.cli.commands.style.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.style.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _report(**overrides: object) -> dict:
    """构造完整 StyleReport JSON dict（三大板块 + jieba + LLM 板块 + warnings，spec §2.6/§4.3）。"""
    kwargs: dict[str, object] = {
        "project_id": str(PID),
        "source": "manual",
        "generated_at": TS,
        "fingerprint": {
            "char_count": 2850,
            "sentence_count": 62,
            "avg_sentence_length": 45.9,
            "sentence_length_std": 12.3,
            "paragraph_count": 18,
            "avg_paragraph_length": 158.3,
            "punctuation_density": 0.1213,
            "exclamation_density": 0.0164,
            "ellipsis_density": 0.0088,
            "dialogue_ratio": 0.3251,
            "vocabulary_richness": 0.6102,
            "top_words": [
                {"word": "林晚", "count": 12, "first_index": 0},
                {"word": "她", "count": 9, "first_index": 3},
                {"word": "说", "count": 8, "first_index": 7},
                {"word": "夜", "count": 7, "first_index": 11},
                {"word": "风", "count": 6, "first_index": 15},
            ],
        },
        "ai_trace": {
            "ai_score": 0.23,
            "verdict": "likely_human",
            "features": [
                {
                    "feature": "sentence_uniformity",
                    "value": 0.62,
                    "score": 0.38,
                    "note": "句长变异系数 0.62——句式波动正常",
                },
                {
                    "feature": "exclamation_density_low",
                    "value": 0.0164,
                    "score": 0.0,
                    "note": "感叹号密度 0.0164（≥ 0.005）——感叹号使用正常",
                },
            ],
            "evidence": [
                "各特征得分均低于 0.5，无明显 AI 特征（综合得分 0.23 → likely_human）"
            ],
        },
        "lexical": {
            "total_words": 1520,
            "unique_words": 927,
            "top_words": [
                {"word": "林晚", "count": 12, "first_index": 0},
                {"word": "她", "count": 9, "first_index": 3},
            ],
            "avg_word_length": 2.42,
            "stopword_ratio": 0.2812,
            "jieba": {
                "jieba_total_words": 1631,
                "jieba_unique_words": 1012,
                "jieba_avg_word_length": 2.18,
                "jieba_top_words": [{"word": "林晚", "count": 12, "first_index": 0}],
            },
        },
        "llm_assessment": {
            "llm_verdict": "likely_human",
            "reasoning": "句式长短错落、对话与叙述穿插自然——统计特征未显示明显 AI 生成模式。",
            "model": "gpt-4o",
            "generated_at": TS,
        },
        "warnings": ["多章节合并分析（单章粒度分析归 Phase 2+）"],
    }
    kwargs.update(overrides)
    return kwargs


class TestStyleRegistration:
    def test_group_help_lists_analyze(self):
        """style 组帮助包含 analyze 命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）。"""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "analyze" in result.output


class TestStyleAnalyze:
    def test_analyze_human_full_summary(self, cli_runner, fake_http_client):
        """analyze 人类模式 → 三大板块摘要 + 高频词前 5 + jieba/LLM 行 + warnings 逐条。"""
        fake_http_client.post.return_value = _report()
        result = cli_runner.invoke(
            app,
            [
                "analyze",
                "--project-id",
                str(PID),
                "--chapters",
                "7a4f2c91-0000-4000-8000-000000000011",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        # 头部 + 三大板块（spec §4.3）
        assert f"📊 风格分析 (project {PID}):" in result.output
        assert "【风格指纹】" in result.output
        assert "字数 2850" in result.output and "句子 62" in result.output
        # 高频词前 5（(count DESC, first_index ASC) 排序，§6.3）
        assert "林晚(12)" in result.output and "她(9)" in result.output
        assert (
            "说(8)" in result.output
            and "夜(7)" in result.output
            and "风(6)" in result.output
        )
        # AI 痕迹: ai_score + verdict 中文映射 + 倾向特征逐条（[特征名] note）
        assert "【AI 痕迹】" in result.output
        assert "AI 得分 0.23 → ✅ 倾向人类创作" in result.output
        assert "[sentence_uniformity] 句长变异系数 0.62——句式波动正常" in result.output
        # 词汇分析 + jieba 增强行 + LLM 深度分析行
        assert "【词汇分析】" in result.output
        assert (
            "总词数 1520 · 唯一词 927 · 平均词长 2.42 · 停用词占比 0.2812"
            in result.output
        )
        assert "【jieba 增强】" in result.output and "总词数 1631" in result.output
        assert "【LLM 深度分析】" in result.output and "gpt-4o" in result.output
        # warnings 逐条 + 末尾提示 --json
        assert "⚠ 多章节合并分析（单章粒度分析归 Phase 2+）" in result.output
        assert "完整报告见 inkflow style analyze --json" in result.output
        fake_http_client.post.assert_awaited_once_with(
            f"/projects/{PID}/style/analyze",
            json={
                "text": None,
                "chapter_ids": ["7a4f2c91-0000-4000-8000-000000000011"],
                "llm_analysis": None,
            },
        )

    @pytest.mark.parametrize(
        ("verdict", "expected"),
        [
            ("likely_human", "✅ 倾向人类创作"),
            ("uncertain", "特征不明显"),
            ("likely_ai", "⚠ 倾向 AI 生成"),
        ],
        ids=["likely_human", "uncertain", "likely_ai"],
    )
    def test_analyze_human_verdict_mapping(
        self, cli_runner, fake_http_client, verdict, expected
    ):
        """verdict 三档中文映射（spec §4.3/§6.2）；likely_ai 结论 → 退出码恒 0。"""
        report = _report(
            ai_trace={
                "ai_score": 0.72 if verdict == "likely_ai" else 0.5,
                "verdict": verdict,
                "features": [],
                "evidence": ["各特征得分均低于 0.5，无明显 AI 特征"],
            },
            llm_assessment=None,
        )
        fake_http_client.post.return_value = report
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", TEXT],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert expected in result.output
        # 未开启 LLM → 无 LLM 深度分析行
        assert "【LLM 深度分析】" not in result.output

    def test_analyze_json_envelope(self, cli_runner, fake_http_client):
        """analyze --json → 成功信封 + 完整 StyleReport（data.fingerprint/ai_trace/lexical）。"""
        fake_http_client.post.return_value = _report()
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", TEXT],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        report = data["data"]
        assert report["project_id"] == str(PID)
        assert report["source"] == "manual"
        assert report["fingerprint"]["char_count"] == 2850
        assert report["ai_trace"]["verdict"] == "likely_human"
        assert report["lexical"]["jieba"]["jieba_total_words"] == 1631
        assert report["llm_assessment"]["model"] == "gpt-4o"
        assert report["warnings"] == ["多章节合并分析（单章粒度分析归 Phase 2+）"]

    def test_analyze_text_file(self, cli_runner, fake_http_client, tmp_path):
        """--text-file 读取文件内容作为 text 透传（三选一互斥输入，spec §4.2）。"""
        src = tmp_path / "chapter.txt"
        src.write_text("第一章：林晚在山神庙中醒来。", encoding="utf-8")
        fake_http_client.post.return_value = _report()
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text-file", str(src)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.post.assert_awaited_once_with(
            f"/projects/{PID}/style/analyze",
            json={
                "text": "第一章：林晚在山神庙中醒来。",
                "chapter_ids": None,
                "llm_analysis": None,
            },
        )

    def test_analyze_llm_analysis_true_passthrough(self, cli_runner, fake_http_client):
        """--llm-analysis 显式开启 → body 收到 llm_analysis=True（Q1=C，spec §4.2）。"""
        fake_http_client.post.return_value = _report()
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", TEXT, "--llm-analysis"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.post.assert_awaited_once_with(
            f"/projects/{PID}/style/analyze",
            json={"text": TEXT, "chapter_ids": None, "llm_analysis": True},
        )

    def test_analyze_no_llm_analysis_false_passthrough(
        self, cli_runner, fake_http_client
    ):
        """--no-llm-analysis 显式关闭 → body 收到 llm_analysis=False（spec §2.8）。"""
        fake_http_client.post.return_value = _report()
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", TEXT, "--no-llm-analysis"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.post.assert_awaited_once_with(
            f"/projects/{PID}/style/analyze",
            json={"text": TEXT, "chapter_ids": None, "llm_analysis": False},
        )

    def test_analyze_missing_source_exit_2(self, cli_runner, fake_http_client):
        """三选一均未提供 → 退出码 2（Typer 参数校验，spec §4.2/§7）。"""
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()

    def test_analyze_text_and_text_file_exit_2(self, cli_runner, fake_http_client):
        """--text 与 --text-file 同时使用 → 退出码 2（互斥，同 F9/F14 先例）。"""
        result = cli_runner.invoke(
            app,
            [
                "analyze",
                "--project-id",
                str(PID),
                "--text",
                TEXT,
                "--text-file",
                "chapter.txt",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()

    def test_analyze_project_not_found_exit_1(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1（spec §4.3 示例）。"""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(404, "项目不存在")
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", TEXT],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "项目不存在" in data["error"]["message"]

    def test_analyze_validation_error_exit_1(self, cli_runner, fake_http_client):
        """API 422（业务校验失败）→ VALIDATION_ERROR 信封 + 退出码 1（spec §4/§7）。"""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(422, "文本不能为空")
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", "   "],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "文本不能为空" in data["error"]["message"]

    def test_analyze_llm_error_exit_1(self, cli_runner, fake_http_client):
        """LLM 深度分析不可用（未装配）→ LLM_ERROR 信封 + 退出码 1（Q1=C，spec §4/§7）。"""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(
            500, "LLM 调用失败，请稍后重试", code="LLM_ERROR"
        )
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", TEXT, "--llm-analysis"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "LLM_ERROR"

    def test_analyze_internal_error_exit_1(self, cli_runner, fake_http_client):
        """数据库读取失败（HTTP 500 无错误码头）→ INTERNAL_ERROR + 退出码 1（spec §4/§5.3）。"""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(500, "数据库读取失败")
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", TEXT],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_analyze_kernel_startup_error(self, cli_runner):
        """ensure_kernel 失败（内核冷启动超时）→ KERNEL_ERROR 信封 + 退出码 1（spec §5.3）."""
        from inkflow.infrastructure.kernel import KernelStartupError

        with patch(
            "inkflow.cli.commands.style.ensure_kernel",
            AsyncMock(side_effect=KernelStartupError("启动超时")),
        ):
            result = cli_runner.invoke(
                app,
                ["analyze", "--project-id", str(PID), "--text", TEXT],
                obj=CliContext(json_output=True),
            )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "KERNEL_ERROR"
        assert "内核启动失败" in data["error"]["message"]


class TestStyleAnalyzeEdgeBranches:
    """补齐 miss 行：无效 UUID、typer.Exit 透传、高频词超 5 省略号、jieba=None、
    LLM 理由截断、--text/--chapters 与 --text-file/--chapters 互斥。"""

    def test_analyze_invalid_uuid(self, cli_runner, fake_http_client):
        """无效 project-id UUID → NOT_FOUND 信封 + 退出码 1（spec §7: 无效 UUID → 404 语义）."""
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", "not-a-uuid", "--text", TEXT],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        fake_http_client.post.assert_not_awaited()

    def test_analyze_typer_exit_reraises(self, cli_runner, fake_http_client):
        """Client 抛 typer.Exit → 原样透传（退出码 3，不映射错误信封）."""
        fake_http_client.post.side_effect = typer.Exit(3)
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", TEXT],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 3

    def test_analyze_human_top_words_overflow(self, cli_runner, fake_http_client):
        """高频词超过 5 个 → 前 5 个 + 省略号（spec §4.3 _TOP_WORDS_LIMIT）."""
        words = [
            {"word": f"词{i}", "count": 10 - i, "first_index": i} for i in range(6)
        ]
        report = _report(
            fingerprint={
                "char_count": 100,
                "sentence_count": 5,
                "avg_sentence_length": 20.0,
                "sentence_length_std": 5.0,
                "paragraph_count": 2,
                "avg_paragraph_length": 50.0,
                "punctuation_density": 0.1,
                "exclamation_density": 0.0,
                "ellipsis_density": 0.0,
                "dialogue_ratio": 0.2,
                "vocabulary_richness": 0.5,
                "top_words": words,
            }
        )
        fake_http_client.post.return_value = report
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", TEXT],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "词0(10) 词1(9) 词2(8) 词3(7) 词4(6) …" in result.output

    def test_analyze_human_no_jieba(self, cli_runner, fake_http_client):
        """jieba 未装配（None）→ 不输出 jieba 增强行（spec §2.5 防御分支）."""
        report = _report(
            lexical={
                "total_words": 10,
                "unique_words": 8,
                "top_words": [],
                "avg_word_length": 2.1,
                "stopword_ratio": 0.1,
                "jieba": None,
            },
            llm_assessment=None,
        )
        fake_http_client.post.return_value = report
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", TEXT],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "【jieba 增强】" not in result.output
        assert "【词汇分析】总词数 10" in result.output

    def test_analyze_human_llm_reasoning_truncated(self, cli_runner, fake_http_client):
        """LLM 理由超 40 字符 → 截断 + 省略号（spec §4.3 _REASONING_MAX_CHARS）."""
        long_reasoning = (
            "这是一段特别长的分析理由，其长度远超四十个字符的限制，"
            "因此人类可读摘要必须截断并追加省略号。"
        )
        report = _report(
            llm_assessment={
                "llm_verdict": "likely_ai",
                "reasoning": long_reasoning,
                "model": "gpt-4o",
                "generated_at": TS,
            }
        )
        fake_http_client.post.return_value = report
        result = cli_runner.invoke(
            app,
            ["analyze", "--project-id", str(PID), "--text", TEXT],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert (
            f"【LLM 深度分析】⚠ 倾向 AI 生成（gpt-4o）——{long_reasoning[:40]}…"
            in result.output
        )

    def test_analyze_text_and_chapters_exit_2(self, cli_runner, fake_http_client):
        """--text 与 --chapters 同时使用 → 退出码 2（三选一互斥第二分支）."""
        result = cli_runner.invoke(
            app,
            [
                "analyze",
                "--project-id",
                str(PID),
                "--text",
                TEXT,
                "--chapters",
                "7a4f2c91-0000-4000-8000-000000000011",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()

    def test_analyze_text_file_and_chapters_exit_2(self, cli_runner, fake_http_client):
        """--text-file 与 --chapters 同时使用 → 退出码 2（三选一互斥第三分支）."""
        result = cli_runner.invoke(
            app,
            [
                "analyze",
                "--project-id",
                str(PID),
                "--text-file",
                "chapter.txt",
                "--chapters",
                "7a4f2c91-0000-4000-8000-000000000011",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()
