"""Coverage backfill: export CLI 未覆盖分支（F21 spec §4/§7 + F7 错误映射）。

镜像 tests/cli/test_cli_export.py 的 fake_http_client 模式，全部通过公开
``inkflow export`` 命令驱动：
- UUID 形 project → GET /projects/{pid} 直查（_resolve_project else 分支）
- 搜索列表含非同名项 → 循环未命中 → NOT_FOUND（92->91 弧）
- KernelStartupError → KERNEL_ERROR；通用异常 → DB_ERROR（_run 兜底分支）
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.export import app
from inkflow.cli.context import CliContext
from inkflow.infrastructure.kernel import KernelStartupError

PROJECT_UUID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def fake_http_client():
    """patch ensure_kernel + InkFlowHTTPClient（F38 契约：命令模块命名空间）。"""
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
            "inkflow.cli.commands.export.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.cli.commands.export.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_uuid_project_resolved_directly(
    cli_runner, fake_http_client, tmp_path
) -> None:
    """UUID 形 project → GET /projects/{pid} 直查名称并成功导出（--json）。"""
    fake_http_client.get = AsyncMock(
        return_value={"id": str(PROJECT_UUID), "name": "我的书"}
    )
    fake_http_client.get_raw = AsyncMock(return_value="正文内容")

    result = cli_runner.invoke(
        app,
        ["export", str(PROJECT_UUID), "--output", str(tmp_path)],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)["data"]
    assert data["format"] == "txt"
    assert data["bytes"] == len("正文内容".encode())
    assert (tmp_path / data["filename"]).exists()
    fake_http_client.get.assert_awaited_once_with(f"/projects/{PROJECT_UUID}")


def test_search_list_mismatch_name_not_found(cli_runner, fake_http_client) -> None:
    """搜索列表含非同名项 → 循环未命中 → NOT_FOUND + exit 1（92->91 弧）。"""
    fake_http_client.get = AsyncMock(
        return_value={"items": [{"id": "1", "name": "别的书"}], "total": 1}
    )

    result = cli_runner.invoke(
        app,
        ["export", "不存在的书"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output or "项目不存在" in result.output


def test_kernel_startup_error_maps_to_kernel_error(
    cli_runner, fake_http_client, monkeypatch
) -> None:
    """ensure_kernel 抛 KernelStartupError → KERNEL_ERROR + exit 1。"""
    monkeypatch.setattr(
        "inkflow.cli.commands.export.ensure_kernel",
        AsyncMock(side_effect=KernelStartupError("kernel boom")),
    )

    result = cli_runner.invoke(
        app,
        ["export", "1"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "内核启动失败" in result.output


def test_generic_exception_maps_to_db_error(cli_runner, fake_http_client) -> None:
    """HTTP 层外通用异常 → DB_ERROR + exit 1（_run 兜底）。"""
    fake_http_client.get = AsyncMock(side_effect=RuntimeError("boom"))

    result = cli_runner.invoke(
        app,
        ["export", "我的书"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 1
    assert "内部错误" in result.output
