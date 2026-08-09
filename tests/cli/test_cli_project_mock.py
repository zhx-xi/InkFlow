"""Project CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（HTTP JSON 响应）。

F38 改造（#169）：mock 目标从 domain Service（ProjectService + create_tables）
迁移到 ensure_kernel + InkFlowHTTPClient；返回值从 Project 领域对象改为
JSON dict（model_dump(mode="json") 等价物）；create_tables/session 相关
patch 已移除；错误路径抛 HttpApiError（lazy import，RED 阶段模块未实现）。

── RED 形态说明 ────────────────────────────────────────────────
命令模块仍直连 domain Service（未改造），patch 目标
inkflow.cli.commands.project.ensure_kernel / .InkFlowHTTPClient 不存在
→ 全部用例 fixture setup AttributeError（同根因，预期 RED）。
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner():
    # 注意: click 8.4 已移除 mix_stderr 参数，默认混合输出
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP。

    fake client 提供 post/get/patch/delete 返回预设 JSON（dict）；
    错误路径抛 HttpApiError。patch 目标 = 命令模块命名空间（GREEN 后
    命令模块 from-import 绑定自身命名空间，F19 #77 先例）。
    """
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
            "inkflow.cli.commands.project.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.project.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_error(status_code: int, detail: str, code: str | None = None):
    """构造 HttpApiError（lazy import：RED 阶段 inkflow.infrastructure.http
    未实现，仅在用例体调用时执行，不影响 RED 形态）。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _make_project(**overrides) -> dict:
    """构造测试用项目 JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        name="星辰变",
        genre="玄幻",
        language="zh-CN",
        target_words=100000,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        is_deleted=False,
    )
    defaults.update(overrides)
    return defaults


class TestProjectCreate:
    def test_create_json_envelope(self, cli_runner, fake_http_client):
        """--json 模式创建项目 → 信封."""
        from inkflow.cli.commands.project import app

        fake_http_client.post.return_value = _make_project()
        result = cli_runner.invoke(
            app, ["create", "--name", "星辰变"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "星辰变"
        assert data["data"]["genre"] == "玄幻"
        fake_http_client.post.assert_awaited()

    def test_create_human_mode(self, cli_runner, fake_http_client):
        """人类模式创建项目."""
        from inkflow.cli.commands.project import app

        fake_http_client.post.return_value = _make_project()
        result = cli_runner.invoke(
            app, ["create", "--name", "星辰变"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "星辰变" in result.output


class TestProjectGet:
    def test_get_json(self, cli_runner, fake_http_client):
        """项目存在 → 信封."""
        from inkflow.cli.commands.project import app

        fake_http_client.get.return_value = _make_project()
        result = cli_runner.invoke(
            app, ["get", "--id", "1"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "星辰变"

    def test_get_not_found_json(self, cli_runner, fake_http_client):
        """项目不存在 → 退出码 1 + 错误信封."""
        from inkflow.cli.commands.project import app

        fake_http_client.get.side_effect = _http_error(404, "项目不存在")
        result = cli_runner.invoke(
            app, ["get", "--id", "999"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestProjectList:
    def test_list_json(self, cli_runner, fake_http_client):
        """列出项目 JSON 模式."""
        from inkflow.cli.commands.project import app

        fake_http_client.get.return_value = {
            "items": [_make_project()],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(app, ["list"], obj=CliContext(json_output=True))
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert isinstance(data["data"], list)
        assert data["data"][0]["name"] == "星辰变"

    def test_list_human_empty(self, cli_runner, fake_http_client):
        """空列表人类模式."""
        from inkflow.cli.commands.project import app

        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(app, ["list"], obj=CliContext(json_output=False))
        assert result.exit_code == 0
        assert "暂无项目" in result.output


class TestProjectDelete:
    def test_delete_without_force_prompts(self, cli_runner, fake_http_client):
        """无 --force 时交互确认，回答 n 应取消."""
        from inkflow.cli.commands.project import app

        result = cli_runner.invoke(
            app,
            ["delete", "--id", "1"],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "取消" in result.output
        fake_http_client.delete.assert_not_awaited()
