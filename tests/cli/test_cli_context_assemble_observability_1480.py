"""#1480 装配可观测面 — `inkflow context assemble` CLI 契约测试.

契约（`specs/f6-context/spec.md` §6，v1.5 #1480）:
- 新增 3 个**默认关闭**的 flag：`--show-system-prompt` / `--show-skills` / `--show-tools`，
  开启时对应布尔字段进请求体（缺省**不进** body）。
- 人类模式在既有摘要行后追加观测段：`--show-skills` 打印 skill 名 + source + bytes。

RED 形态（实现前）：flag 不存在 → typer 报 unknown option（exit 2），三条正向用例 FAIL。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.context_cmd import app
from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（镜像 test_cli_context_assemble.py 模式）。"""
    fake_handle = SimpleNamespace(
        port=38293,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(
            "inkflow.cli.commands.context_cmd.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.cli.commands.context_cmd.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


PID = "00000000-0000-0000-0000-000000000001"
CID = "00000000-0000-0000-0000-00000000000a"
SKILL_NAME = "writing-methodology"


def _result_with_observability() -> dict:
    """组装结果 + 三件观测键（模拟内核开启全部观测 flag 后的响应）。"""
    return {
        "blocks": [
            {
                "item": {
                    "source": "writing_requirements",
                    "title": "写作要求",
                    "content": "保持悬疑节奏",
                    "priority": 0,
                    "metadata": {},
                },
                "layer": "protected",
                "token_count": 120,
                "compressed": False,
            }
        ],
        "budget_tokens": 8000,
        "total_tokens": 120,
        "model": "openai/gpt-4o",
        "dropped": [],
        "system_prompt": f"你是一位专业的小说章节写作助手\n\n# 技能：{SKILL_NAME}\n\n破折号密度\n",
        "skills": [
            {"name": SKILL_NAME, "bytes": 4460, "source": "explicit"},
            {"name": "my-general-skill", "bytes": 812, "source": "general"},
        ],
        "tools": ["search_characters", "save_draft"],
    }


def _invoke(cli_runner, *extra: str, json_output: bool = True):
    return cli_runner.invoke(
        app,
        [
            "assemble",
            "--project-id",
            PID,
            "--chapter-id",
            CID,
            "--model",
            "openai/gpt-4o",
            "--writing-requirements",
            "保持悬疑节奏",
            *extra,
        ],
        obj=CliContext(json_output=json_output),
    )


class TestObservabilityFlags:
    def test_flags_absent_by_default(self, cli_runner, fake_http_client):
        """不带观测 flag → 请求体不含任何 show_* 键（默认关闭）。"""
        fake_http_client.post.return_value = _result_with_observability()

        result = _invoke(cli_runner)

        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert "show_system_prompt" not in body
        assert "show_skills" not in body
        assert "show_tools" not in body

    def test_show_skills_flag_lands_in_body(self, cli_runner, fake_http_client):
        """--show-skills → 请求体 show_skills=true（其余观测 flag 不夹带）。"""
        fake_http_client.post.return_value = _result_with_observability()

        result = _invoke(cli_runner, "--show-skills")

        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert body["show_skills"] is True
        assert "show_system_prompt" not in body
        assert "show_tools" not in body

    def test_all_three_flags_land_in_body(self, cli_runner, fake_http_client):
        """三个 flag 同时开启 → 三个键都进 body。"""
        fake_http_client.post.return_value = _result_with_observability()

        result = _invoke(cli_runner, "--show-system-prompt", "--show-skills", "--show-tools")

        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert body["show_system_prompt"] is True
        assert body["show_skills"] is True
        assert body["show_tools"] is True

    def test_human_output_prints_skill_names(self, cli_runner, fake_http_client):
        """人类模式 --show-skills → 输出含 skill 名 + source。"""
        fake_http_client.post.return_value = _result_with_observability()

        result = _invoke(cli_runner, "--show-skills", json_output=False)

        assert result.exit_code == 0
        assert SKILL_NAME in result.output
        assert "my-general-skill" in result.output
        assert "explicit" in result.output
        assert "general" in result.output

    def test_human_output_prints_system_prompt_and_tools(self, cli_runner, fake_http_client):
        """人类模式 --show-system-prompt --show-tools → 输出含 prompt 正文与 tool id。"""
        fake_http_client.post.return_value = _result_with_observability()

        result = _invoke(cli_runner, "--show-system-prompt", "--show-tools", json_output=False)

        assert result.exit_code == 0
        assert "破折号密度" in result.output
        assert "search_characters" in result.output

    def test_human_output_clean_without_flags(self, cli_runner, fake_http_client):
        """不带观测 flag → 人类输出保持既有摘要形态（不打印观测段）。"""
        fake_http_client.post.return_value = _result_with_observability()

        result = _invoke(cli_runner, json_output=False)

        assert result.exit_code == 0
        assert SKILL_NAME not in result.output

    def test_json_output_passes_observability_through(self, cli_runner, fake_http_client):
        """--json → 三键原样进信封 data（薄层不裁剪）。"""
        fake_http_client.post.return_value = _result_with_observability()

        result = _invoke(cli_runner, "--show-skills")

        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["skills"][0]["name"] == SKILL_NAME
