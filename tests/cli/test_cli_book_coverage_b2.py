"""Coverage backfill batch 2: book_cmd 未覆盖分支。

镜像 tests/cli/test_book_cmd.py 的 fake_http_client 模式，经公开
``inkflow book`` 子命令驱动：
- plan confirm 未完成 -> 回落到逐条问题渲染（249->257 / 257）
- book run --limits 含无 key 条目 -> 跳过并省略 body.limits（86->81）
- intervene --action edit 无 diff -> 跳过 before/after（439->441 / 441->exit）
- intervene 未知 action -> 动作分支全部落空（434->exit）
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.book_cmd import app
from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def fake_http_client():
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
            "inkflow.cli.commands.book_cmd.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.book_cmd.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_plan_confirm_incomplete_renders_questions(
    cli_runner, fake_http_client
) -> None:
    """plan confirm 未完成 -> 渲染剩余问题（257）。"""
    fake_http_client.post.return_value = {
        "completed": False,
        "questions": [{"text": "主角叫什么？"}],
    }

    result = cli_runner.invoke(
        app, ["plan", "confirm", "sess-1"], obj=CliContext(json_output=False)
    )

    assert result.exit_code == 0
    assert "主角叫什么？" in result.stdout
    fake_http_client.post.assert_awaited_once()


def test_run_limits_skips_item_without_key(cli_runner, fake_http_client) -> None:
    """--limits 条目 ``=5``（无 key）-> 跳过且不写 body.limits（86->81）。"""
    fake_http_client.post.return_value = {"run_id": "r1", "status": "queued"}

    result = cli_runner.invoke(
        app, ["run", "plan-1", "--limits", "=5"], obj=CliContext(json_output=False)
    )

    assert result.exit_code == 0
    body = fake_http_client.post.await_args.kwargs["json"]
    assert body == {"writing_plan_id": "plan-1"}


def test_intervene_edit_without_diff_skips_before_after(
    cli_runner, fake_http_client
) -> None:
    """intervene --action edit 无 diff -> 只输出编辑行（439->441 / 441->exit）。"""
    fake_http_client.post.return_value = {"run_id": "r1"}

    result = cli_runner.invoke(
        app,
        ["intervene", "r1", "--action", "edit", "--target", "c1"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "c1" in result.stdout
    assert "before" not in result.stdout
    assert "after" not in result.stdout


def test_intervene_unknown_action_is_silent(cli_runner, fake_http_client) -> None:
    """intervene 未知 action -> 全部动作分支落空，仅退出码 0（434->exit）。"""
    fake_http_client.post.return_value = {"run_id": "r1"}

    result = cli_runner.invoke(
        app,
        ["intervene", "r1", "--action", "teleport", "--target", "c1"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == ""
