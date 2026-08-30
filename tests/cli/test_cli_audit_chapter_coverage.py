"""Coverage backfill: audit chapter CLI 未覆盖分支（F34 spec §4/§7）。

镜像 tests/cli/test_cli_audit_chapter.py 的 fake_http_client 模式：
- 分页循环第二页（_load_all_chapters offset += 50，章名跨页解析）
- 项目名/章名列表非命中 → 循环继续弧（100->99 / 135->134）
- --history 空日志 → 「（暂无审计记录）」；日志无 confirmed_at → 不带确认后缀
- KernelStartupError → KERNEL_ERROR；通用异常 → DB_ERROR
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.audit_chapter import app
from inkflow.cli.context import CliContext
from inkflow.infrastructure.kernel import KernelStartupError

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000002")


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
            "inkflow.cli.commands.audit_chapter.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.audit_chapter.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_kernel_startup_error_maps_to_kernel_error(
    cli_runner, fake_http_client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "inkflow.cli.commands.audit_chapter.ensure_kernel",
        AsyncMock(side_effect=KernelStartupError("kernel boom")),
    )

    result = cli_runner.invoke(
        app,
        ["chapter", str(CID), "--project", str(PID)],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "内核启动失败" in result.output


def test_generic_exception_maps_to_db_error(cli_runner, fake_http_client) -> None:
    fake_http_client.get = AsyncMock(side_effect=RuntimeError("boom"))

    result = cli_runner.invoke(
        app,
        ["chapter", str(CID), "--project", "我的书"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "内部错误" in result.output


def test_project_name_loop_continue_then_not_found(
    cli_runner, fake_http_client
) -> None:
    """项目名列表含非同名项 → 循环继续 → NOT_FOUND（100->99 弧）。"""
    fake_http_client.get = AsyncMock(
        return_value={"items": [{"id": str(PID), "name": "别的项目"}], "total": 1}
    )

    result = cli_runner.invoke(
        app,
        ["chapter", str(CID), "--project", "不存在的项目"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "项目不存在" in result.output


def test_chapter_name_resolves_across_pages(cli_runner, fake_http_client) -> None:
    """章名在第一页查无、第二页命中 → 分页循环 offset 递增（119 行）。"""
    page1 = {
        "items": [
            {"id": str(uuid.uuid4()), "title": f"无关章节 {i}"} for i in range(50)
        ],
        "total": 51,
    }
    page2 = {
        "items": [{"id": str(CID), "title": "目标章节"}],
        "total": 51,
    }

    async def _get(path: str, **kwargs):
        if path == "/projects":
            return {"items": [{"id": str(PID), "name": "我的书"}], "total": 1}
        if path == f"/projects/{PID}/chapters":
            offset = int((kwargs.get("params") or {}).get("offset", 0))
            return page2 if offset else page1
        raise AssertionError(f"unexpected GET {path}")

    fake_http_client.get = _get
    fake_http_client.post = AsyncMock(
        return_value={
            "chapter_id": str(CID),
            "chapter_title": "目标章节",
            "status": "pending",
            "findings": [],
            "summary": "",
            "degraded": False,
        }
    )

    result = cli_runner.invoke(
        app,
        ["chapter", "目标章节", "--project", "我的书"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    fake_http_client.post.assert_awaited_once()


def test_chapter_name_loop_continue_then_not_found(
    cli_runner, fake_http_client
) -> None:
    """章名列表含非同名项 → 循环继续 → NOT_FOUND（135->134 弧）。"""

    async def _get(path: str, **kwargs):
        if path == "/projects":
            return {"items": [{"id": str(PID), "name": "我的书"}], "total": 1}
        if path == f"/projects/{PID}/chapters":
            return {"items": [{"id": str(CID), "title": "别的章节"}], "total": 1}
        raise AssertionError(f"unexpected GET {path}")

    fake_http_client.get = _get

    result = cli_runner.invoke(
        app,
        ["chapter", "不存在的章节", "--project", "我的书"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "章节不存在" in result.output


def test_history_empty_logs_human_output(cli_runner, fake_http_client) -> None:
    """--history 空日志 → 「（暂无审计记录）」（176-177）。"""
    fake_http_client.get = AsyncMock(
        side_effect=lambda path, **kwargs: (
            {"items": [{"id": str(PID), "name": "我的书"}], "total": 1}
            if path == "/projects"
            else {"logs": []}
        )
    )

    result = cli_runner.invoke(
        app,
        ["chapter", "--history", "--project", "我的书"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "暂无审计记录" in result.output


def test_history_log_without_confirmed_at(cli_runner, fake_http_client) -> None:
    """日志无 confirmed_at → 行输出不带「确认于」后缀（183->185 弧）。"""
    fake_http_client.get = AsyncMock(
        side_effect=lambda path, **kwargs: (
            {"items": [{"id": str(PID), "name": "我的书"}], "total": 1}
            if path == "/projects"
            else {
                "logs": [
                    {
                        "chapter_title": "第一章",
                        "status": "accepted",
                        "severity_summary": "1 error",
                        "created_at": "2026-08-09T10:00:00Z",
                    }
                ]
            }
        )
    )

    result = cli_runner.invoke(
        app,
        ["chapter", "--history", "--project", "我的书"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "第一章" in result.output
    assert "确认于" not in result.output
