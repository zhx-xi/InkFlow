"""Coverage backfill: vector CLI 未覆盖分支（F14 spec §4/§7 + #276 status）。

镜像 tests/cli/test_cli_vector.py 的 fake_http_client 模式：
- status reason=no_embedding → 「未配置 embedding 模型」
- reindex/retrieve 前置 status stale=True → 「索引可能过期」警告
- retrieve --json → items 按 relevance_score 降序
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.vector import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


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
            "inkflow.cli.commands.vector.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.vector.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_status_no_embedding_human_label(cli_runner, fake_http_client) -> None:
    """status reason=no_embedding → 「未配置 embedding 模型」（98 行）。"""
    fake_http_client.get = AsyncMock(
        return_value={
            "stale": False,
            "reason": "no_embedding",
            "configured_fp": {},
        }
    )

    result = cli_runner.invoke(
        app,
        ["status", "--project-id", str(PID)],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "未配置 embedding 模型" in result.output


def test_reindex_stale_status_warns(cli_runner, fake_http_client) -> None:
    """reindex 前置 status stale=True → 打印「索引可能过期」警告（113 行）。"""

    async def _get(path: str, **kwargs):
        if path == f"/projects/{PID}/vector/status":
            return {"stale": True, "reason": "model_changed", "configured_fp": {}}
        raise AssertionError(f"unexpected GET {path}")

    fake_http_client.get = _get
    fake_http_client.post = AsyncMock(
        return_value={
            "project_id": str(PID),
            "entity_types": ["character"],
            "indexed": 3,
            "warnings": [],
        }
    )

    result = cli_runner.invoke(
        app,
        ["reindex", "--project-id", str(PID), "--type", "character"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "索引可能过期" in result.output
    assert "索引完成" in result.output


def test_retrieve_stale_status_warns(cli_runner, fake_http_client) -> None:
    """retrieve 前置 status stale=True → 打印「索引可能过期」警告（171-172）。"""

    async def _get(path: str, **kwargs):
        if path == f"/projects/{PID}/vector/status":
            return {"stale": True, "reason": "schema_old", "configured_fp": {}}
        raise AssertionError(f"unexpected GET {path}")

    fake_http_client.get = _get
    fake_http_client.post = AsyncMock(
        return_value={
            "items": [
                {
                    "entity_id": "f-1",
                    "entity_type": "foreshadowing",
                    "content": "伏笔",
                    "relevance_score": 0.5,
                    "metadata": {"name": "林晚的身世"},
                }
            ]
        }
    )

    result = cli_runner.invoke(
        app,
        ["retrieve", "--project-id", str(PID), "--query", "伏笔"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "索引可能过期" in result.output
    assert "检索结果" in result.output


def test_retrieve_json_sorts_by_relevance(cli_runner, fake_http_client) -> None:
    """retrieve --json → items 按 relevance_score 降序（218-219）。"""
    fake_http_client.get = AsyncMock(
        return_value={"stale": False, "reason": "fresh", "configured_fp": {}}
    )
    fake_http_client.post = AsyncMock(
        return_value={
            "items": [
                {
                    "entity_id": "low",
                    "entity_type": "character",
                    "content": "低相关",
                    "relevance_score": 0.2,
                    "metadata": {},
                },
                {
                    "entity_id": "high",
                    "entity_type": "character",
                    "content": "高相关",
                    "relevance_score": 0.9,
                    "metadata": {},
                },
            ]
        }
    )

    result = cli_runner.invoke(
        app,
        ["retrieve", "--project-id", str(PID), "--query", "角色"],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)["data"]
    assert [item["entity_id"] for item in data["items"]] == ["high", "low"]


def test_status_stale_fresh_reason_prints_warning(cli_runner, fake_http_client) -> None:
    """status stale=True + reason=fresh → _reason_label 空文案（97-98 行）。"""
    fake_http_client.get = AsyncMock(
        return_value={"stale": True, "reason": "fresh", "configured_fp": {}}
    )

    result = cli_runner.invoke(
        app,
        ["status", "--project-id", str(PID)],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "索引可能过期" in result.output


def test_reindex_status_fetch_failure_proceeds(
    cli_runner, fake_http_client
) -> None:
    """status 查询异常 → 不阻断 reindex（171-172 行）。"""
    fake_http_client.get = AsyncMock(side_effect=RuntimeError("status boom"))
    fake_http_client.post = AsyncMock(
        return_value={
            "project_id": str(PID),
            "entity_types": ["character"],
            "indexed": 2,
            "warnings": [],
        }
    )

    result = cli_runner.invoke(
        app,
        ["reindex", "--project-id", str(PID), "--type", "character"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "索引完成" in result.output


def test_retrieve_status_fetch_failure_proceeds(
    cli_runner, fake_http_client
) -> None:
    """status 查询异常 → 不阻断 retrieve（218-219 行）。"""
    fake_http_client.get = AsyncMock(side_effect=RuntimeError("status boom"))
    fake_http_client.post = AsyncMock(
        return_value={
            "items": [
                {
                    "entity_id": "c-1",
                    "entity_type": "character",
                    "content": "角色",
                    "relevance_score": 0.8,
                    "metadata": {"name": "林晚"},
                }
            ]
        }
    )

    result = cli_runner.invoke(
        app,
        ["retrieve", "--project-id", str(PID), "--query", "角色"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "检索结果" in result.output
