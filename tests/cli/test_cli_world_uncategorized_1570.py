"""#1570 存量无类别条目处置路径 —— `world uncategorized` 只读审计（CLI）.

判据（issue #1570 拍板第 3 条）：存量无类别条目有**明确处置路径**（回填或标记待人工），
且该路径**不静默删除数据**。本命令只读列出「非根且无类别」条目 + 回填指引；
回填本身走既有 `world update --id <id> --category <已注册分类名>`（用户显式调用）。

RED（GREEN 前）预期：`app` 无 `uncategorized` 命令 → 退出码 2（usage error）。

依据: specs/f10-world-settings/spec.md §4.1（#1570 增补）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.world import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
ROOT_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000aa")


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（同 tests/cli/test_cli_world.py 模式）。"""
    fake_handle = SimpleNamespace(
        port=38291, token="test-token", pid=1, version="0.1.0", started_at="", reused=True
    )
    with (
        patch("inkflow.cli.commands.world.ensure_kernel", AsyncMock(return_value=fake_handle)),
        patch("inkflow.cli.commands.world.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _setting(name: str, *, parent_id: uuid.UUID | None, category: str = "") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "project_id": str(PID),
        "name": name,
        "parent_id": str(parent_id) if parent_id else None,
        "category": category,
        "content": "",
        "extra": {},
        "batch_id": None,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


def _page(items: list[dict]) -> dict:
    return {"items": items, "total": len(items), "offset": 0, "limit": 100}


class TestWorldUncategorizedCli:
    """`world uncategorized` — 只读审计存量无类别条目。"""

    def test_json_lists_non_root_uncategorized_only(self, cli_runner, fake_http_client):
        """空类别查询返回根 + 非根 → 命令只输出**非根**（根无类别属正常）。"""
        fake_http_client.get.return_value = _page(
            [
                _setting("世界观总纲", parent_id=None),
                _setting("北方大陆", parent_id=ROOT_ID),
                _setting("宗门体系", parent_id=ROOT_ID),
            ]
        )
        result = cli_runner.invoke(
            app, ["uncategorized", "--project-id", str(PID)], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        names = [s["name"] for s in data["data"]["items"]]
        assert names == ["北方大陆", "宗门体系"]
        assert data["data"]["total"] == 2
        # 查询参数：空类别过滤
        assert fake_http_client.get.await_args.kwargs["params"]["category"] == ""

    def test_human_output_lists_rows_and_backfill_hint(self, cli_runner, fake_http_client):
        """人类模式：列出条目 + 回填指引。"""
        fake_http_client.get.return_value = _page([_setting("北方大陆", parent_id=ROOT_ID)])
        result = cli_runner.invoke(
            app, ["uncategorized", "--project-id", str(PID)], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "北方大陆" in result.output
        assert "world update" in result.output

    def test_no_rows_prints_empty_notice(self, cli_runner, fake_http_client):
        fake_http_client.get.return_value = _page([_setting("世界观总纲", parent_id=None)])
        result = cli_runner.invoke(
            app, ["uncategorized", "--project-id", str(PID)], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "无非根且无类别的条目" in result.output

    def test_read_only_never_writes(self, cli_runner, fake_http_client):
        """处置路径**不静默删除/改写数据**：命令只 GET，不 DELETE/PATCH/POST。"""
        fake_http_client.get.return_value = _page([_setting("北方大陆", parent_id=ROOT_ID)])
        result = cli_runner.invoke(
            app, ["uncategorized", "--project-id", str(PID)], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        fake_http_client.get.assert_awaited()
        fake_http_client.delete.assert_not_awaited()
        fake_http_client.patch.assert_not_awaited()
        fake_http_client.post.assert_not_awaited()
