"""Chapter Summary CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（HTTP JSON 响应）。

测试范围：#251 P2 — inkflow chapter summary get / refresh。summary 子组挂载于
chapter 组（chapter_app.add_typer(summary_app, name="summary")），HTTP 轨
（镜像 test_cli_llm_provider.py P1 模式）。

HTTP 契约（实现者以本文件为准，#251 任务书 + api/routers/context.py 端点）:
- get     → GET  /context/chapters/{id}/summary    → {"summary": str, "chapter_id": str}
- refresh → POST /context/chapters/{id}/summary/refresh → 同上
- 404 → NOT_FOUND 信封（exit 1）；非法 UUID → ValueError → DB_ERROR 信封
  （chapter 组既有行为，uuid.UUID() 直接构造）
- 路径一律相对 base_url（InkFlowHTTPClient base_url 已含 /api/v1，#246 教训；
  端点真实前缀是 /context/chapters/...，非 /chapters/...）

── RED 形态说明 ────────────────────────────────────────────────
chapter.py 已存在且 import ensure_kernel / InkFlowHTTPClient（P1 迁移后），
但无 summary 子组 → invoke ["summary", "get", ...] 报 No such command
→ exit 2 ≠ 0（断言 FAIL）+ mock 未被调用（await_args None）。预期：
全部用例 FAILED（断言失败形态，无收集错误）。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP。

    patch 目标 = 命令模块命名空间（chapter.py 已 from-import 绑定自身）。
    """
    fake_handle = SimpleNamespace(
        port=38292,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(
            "inkflow.cli.commands.chapter.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.chapter.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_error(status_code: int, detail: str, code: str | None = None):
    """构造 HttpApiError（lazy import：RED 阶段不影响收集形态）。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _summary_response(chapter_id: str = "00000000-0000-0000-0000-000000000001"):
    return {
        "summary": "这是章节摘要缓存文本。",
        "chapter_id": chapter_id,
    }


class TestSummaryGet:
    def test_get_json(self, cli_runner, fake_http_client):
        """chapter summary get --id <uuid> → GET /context/chapters/{id}/summary + 信封."""
        from inkflow.cli.commands.chapter import chapter_app

        fake_http_client.get.return_value = _summary_response()
        result = cli_runner.invoke(
            chapter_app,
            ["summary", "get", "--id", "00000000-0000-0000-0000-000000000001"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["summary"] == "这是章节摘要缓存文本。"
        assert fake_http_client.get.await_args.args[0] == (
            "/context/chapters/00000000-0000-0000-0000-000000000001/summary"
        )

    def test_get_human(self, cli_runner, fake_http_client):
        """人类模式直接输出摘要文本."""
        from inkflow.cli.commands.chapter import chapter_app

        fake_http_client.get.return_value = _summary_response()
        result = cli_runner.invoke(
            chapter_app,
            ["summary", "get", "--id", "00000000-0000-0000-0000-000000000001"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "这是章节摘要缓存文本。" in result.output

    def test_get_not_found(self, cli_runner, fake_http_client):
        """章节不存在 → NOT_FOUND 信封 + 退出码 1."""
        from inkflow.cli.commands.chapter import chapter_app

        fake_http_client.get.side_effect = _http_error(404, "章节不存在")
        result = cli_runner.invoke(
            chapter_app,
            ["summary", "get", "--id", "00000000-0000-0000-0000-000000000099"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "章节不存在" in data["error"]["message"]

    def test_get_invalid_uuid(self, cli_runner, fake_http_client):
        """非法 UUID → DB_ERROR 信封（chapter 组既有行为：uuid.UUID ValueError）."""
        from inkflow.cli.commands.chapter import chapter_app

        result = cli_runner.invoke(
            chapter_app,
            ["summary", "get", "--id", "not-a-uuid"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"
        fake_http_client.get.assert_not_awaited()


class TestSummaryRefresh:
    def test_refresh_json(self, cli_runner, fake_http_client):
        """chapter summary refresh --id <uuid> → POST 刷新端点 + 信封."""
        from inkflow.cli.commands.chapter import chapter_app

        fake_http_client.post.return_value = _summary_response()
        result = cli_runner.invoke(
            chapter_app,
            ["summary", "refresh", "--id", "00000000-0000-0000-0000-000000000001"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["chapter_id"] == "00000000-0000-0000-0000-000000000001"
        assert fake_http_client.post.await_args.args[0] == (
            "/context/chapters/00000000-0000-0000-0000-000000000001/summary/refresh"
        )

    def test_refresh_human(self, cli_runner, fake_http_client):
        """人类模式刷新成功提示."""
        from inkflow.cli.commands.chapter import chapter_app

        fake_http_client.post.return_value = _summary_response()
        result = cli_runner.invoke(
            chapter_app,
            ["summary", "refresh", "--id", "00000000-0000-0000-0000-000000000001"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅" in result.output

    def test_refresh_not_found(self, cli_runner, fake_http_client):
        """章节不存在 → NOT_FOUND 信封 + 退出码 1."""
        from inkflow.cli.commands.chapter import chapter_app

        fake_http_client.post.side_effect = _http_error(404, "章节不存在")
        result = cli_runner.invoke(
            chapter_app,
            ["summary", "refresh", "--id", "00000000-0000-0000-0000-000000000099"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_refresh_invalid_uuid(self, cli_runner, fake_http_client):
        """非法 UUID → DB_ERROR 信封 + 不调用 POST."""
        from inkflow.cli.commands.chapter import chapter_app

        result = cli_runner.invoke(
            chapter_app,
            ["summary", "refresh", "--id", "not-a-uuid"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"
        fake_http_client.post.assert_not_awaited()
