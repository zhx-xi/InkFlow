"""F14 vector CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（spec §4/§9 CLI 测试）.

覆盖（依据 specs/f14-extraction-service/spec.md §4/§9）:
- vector reindex 缺省（--type 省略 = None 透传）与多 --type 指定
- vector retrieve 参数透传（--query/--type/--top-k/--min-score）与排序输出
- 信封格式与退出码 0/1/2；INTERNAL_ERROR / NOT_FOUND 信封
- --type 非法值 → 退出码 2；缺 --query → 退出码 2

F38 改造（#169）：mock 目标从 domain Service 迁移到 ensure_kernel + InkFlowHTTPClient
（HTTP JSON 响应）；create_tables patch 已移除。

── RED 形态说明 ─────────────────────────────────────────────
- fake_http_client fixture patch 命令模块命名空间
  （inkflow.cli.commands.vector.ensure_kernel / .InkFlowHTTPClient）——当前命令模块
  尚无这两个属性 → fixture setup 抛 AttributeError → 相关用例 ERROR（同根因，
  预期 RED；GREEN 命令改造落地后自动转绿）。
- HttpApiError 在用例体内惰性导入：RED 阶段 inkflow.infrastructure.http 尚未实现，
  顶部 import 会使整文件收集失败（ModuleNotFoundError），无法呈现上述预期形态。

── 端点契约（spec §3.1 表）────────────────────────────────
- reindex → POST /projects/{pid}/vector/reindex（body: entity_types，缺省 None）
- retrieve → POST /projects/{pid}/vector/retrieve（body: query/entity_types/
  top_k/min_score；响应 {"items": [...]} 信封）
- 错误映射（spec §5.3）：404 → NOT_FOUND；500 无头 → INTERNAL_ERROR
  ⚠️ 错误码语义变更：直连时代 RAG_ERROR（RAGUnavailableError）由 CLI 产生；恒 HTTP
  后向量库错误在内核侧映射 500 无 X-InkFlow-Error-Code 头 → INTERNAL_ERROR
  （spec §5.3 注，message = detail 文本透传仍可读）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import typer
from typer.testing import CliRunner

from inkflow.cli.commands.vector import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


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


def _make_reindex_result(**overrides: object) -> dict:
    """构造测试用 ReindexResult JSON dict（entity_types 为字符串列表）."""
    defaults: dict[str, object] = dict(
        project_id=str(PID),
        entity_types=[
            "character",
            "setting",
            "foreshadowing",
            "timeline_event",
            "chapter_chunk",
        ],
        indexed=87,
        warnings=[],
    )
    defaults.update(overrides)
    return defaults


def _make_retrieved(**overrides: object) -> dict:
    """构造测试用 RetrievedEntity JSON dict."""
    defaults: dict[str, object] = dict(
        entity_id="f-0001",
        entity_type="foreshadowing",
        content="伏笔：林晚的身世。林晚右肩的胎记与女主母亲的信物相同。",
        relevance_score=0.82,
        metadata={"name": "林晚的身世", "project_id": str(PID)},
    )
    defaults.update(overrides)
    return defaults


class TestVectorRegistration:
    def test_group_help_lists_all_commands(self):
        """vector 组帮助包含 reindex/retrieve 两个命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）."""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in ("reindex", "retrieve"):
            assert name in result.output


class TestVectorReindex:
    def test_reindex_default_json(self, cli_runner, fake_http_client):
        """reindex 缺省 --type → entity_types=None 透传（服务层全量 5 种）."""
        fake_http_client.post.return_value = _make_reindex_result()
        result = cli_runner.invoke(
            app,
            ["reindex", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["indexed"] == 87
        assert data["data"]["entity_types"] == [
            "character",
            "setting",
            "foreshadowing",
            "timeline_event",
            "chapter_chunk",
        ]
        fake_http_client.post.assert_awaited_once_with(
            f"/projects/{PID}/vector/reindex", json={"entity_types": None}
        )

    def test_reindex_multiple_types(self, cli_runner, fake_http_client):
        """可重复 --type 指定多个实体类型 → 列表透传."""
        fake_http_client.post.return_value = _make_reindex_result(
            entity_types=["character", "setting"], indexed=12
        )
        result = cli_runner.invoke(
            app,
            [
                "reindex",
                "--project-id",
                str(PID),
                "--type",
                "character",
                "--type",
                "setting",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["indexed"] == 12
        fake_http_client.post.assert_awaited_once_with(
            f"/projects/{PID}/vector/reindex",
            json={"entity_types": ["character", "setting"]},
        )

    def test_reindex_human(self, cli_runner, fake_http_client):
        """reindex 人类模式 → ✅ 索引完成（类型列表 + 总数）."""
        fake_http_client.post.return_value = _make_reindex_result()
        result = cli_runner.invoke(
            app,
            ["reindex", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert (
            "✅ 索引完成: character/setting/foreshadowing/timeline_event/chapter_chunk 共 87 条"
            in result.output
        )

    def test_reindex_internal_error(self, cli_runner, fake_http_client):
        """向量库未装配（HTTP 500 无错误码头）→ INTERNAL_ERROR 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(500, "向量库未装配")
        result = cli_runner.invoke(
            app,
            ["reindex", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_reindex_invalid_uuid(self, cli_runner, fake_http_client):
        """无效 project-id UUID → NOT_FOUND（spec §7: 无效 UUID → 404 语义）."""
        result = cli_runner.invoke(
            app,
            ["reindex", "--project-id", "not-a-uuid"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        fake_http_client.post.assert_not_awaited()

    def test_reindex_invalid_type_exit_2(self, cli_runner, fake_http_client):
        """--type 非法值 → 退出码 2（Typer Choice 校验）."""
        result = cli_runner.invoke(
            app,
            ["reindex", "--project-id", str(PID), "--type", "bogus"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()


class TestVectorRetrieve:
    def test_retrieve_json(self, cli_runner, fake_http_client):
        """retrieve --json → 成功信封 + items 数组（含实体类型/分数/metadata）."""
        fake_http_client.post.return_value = {"items": [_make_retrieved()]}
        result = cli_runner.invoke(
            app,
            [
                "retrieve",
                "--project-id",
                str(PID),
                "--query",
                "林晚右肩的胎记",
                "--top-k",
                "5",
                "--min-score",
                "0.5",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        items = data["data"]["items"]
        assert len(items) == 1
        assert items[0]["entity_id"] == "f-0001"
        assert items[0]["entity_type"] == "foreshadowing"
        assert items[0]["relevance_score"] == 0.82
        assert items[0]["metadata"]["name"] == "林晚的身世"
        fake_http_client.post.assert_awaited_once_with(
            f"/projects/{PID}/vector/retrieve",
            json={
                "query": "林晚右肩的胎记",
                "entity_types": None,
                "top_k": 5,
                "min_score": 0.5,
            },
        )

    def test_retrieve_type_filter(self, cli_runner, fake_http_client):
        """--type 限定实体类型 → 列表透传."""
        fake_http_client.post.return_value = {"items": []}
        result = cli_runner.invoke(
            app,
            [
                "retrieve",
                "--project-id",
                str(PID),
                "--query",
                "林晚",
                "--type",
                "foreshadowing",
                "--type",
                "character",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.post.assert_awaited_once_with(
            f"/projects/{PID}/vector/retrieve",
            json={
                "query": "林晚",
                "entity_types": ["foreshadowing", "character"],
                "top_k": 10,
                "min_score": 0.0,
            },
        )

    def test_retrieve_sorted_output(self, cli_runner, fake_http_client):
        """结果按 relevance_score 降序输出（服务返回乱序时 CLI 负责排序）."""
        fake_http_client.post.return_value = {
            "items": [
                _make_retrieved(
                    entity_id="low", relevance_score=0.5, metadata={"name": "低相关"}
                ),
                _make_retrieved(
                    entity_id="high", relevance_score=0.9, metadata={"name": "高相关"}
                ),
                _make_retrieved(
                    entity_id="mid", relevance_score=0.7, metadata={"name": "中相关"}
                ),
            ]
        }
        result = cli_runner.invoke(
            app,
            ["retrieve", "--project-id", str(PID), "--query", "林晚"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "1. [foreshadowing] 高相关 — 0.90" in result.output
        assert "2. [foreshadowing] 中相关 — 0.70" in result.output
        assert "3. [foreshadowing] 低相关 — 0.50" in result.output
        assert result.output.index("高相关") < result.output.index("中相关")
        assert result.output.index("中相关") < result.output.index("低相关")

    def test_retrieve_human(self, cli_runner, fake_http_client):
        """retrieve 人类模式 → 🔍 检索结果（query/top + 编号条目 + 内容片段）."""
        fake_http_client.post.return_value = {
            "items": [
                _make_retrieved(
                    content=(
                        "伏笔：林晚的身世。林晚右肩的胎记与女主母亲的信物相同（埋设位置：第 5 章）"
                    )
                )
            ]
        }
        result = cli_runner.invoke(
            app,
            [
                "retrieve",
                "--project-id",
                str(PID),
                "--query",
                "林晚右肩的胎记",
                "--top-k",
                "5",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "🔍 检索结果 (query: 林晚右肩的胎记, top 5):" in result.output
        assert "1. [foreshadowing] 林晚的身世 — 0.82" in result.output
        assert "（伏笔：林晚的身世。林晚右肩的胎记与女主母亲的信物相同" in result.output

    def test_retrieve_empty(self, cli_runner, fake_http_client):
        """无结果 → 人类模式提示未找到（正常路径，退出码 0）."""
        fake_http_client.post.return_value = {"items": []}
        result = cli_runner.invoke(
            app,
            ["retrieve", "--project-id", str(PID), "--query", "不存在的关键词"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "未找到相关结果" in result.output

    def test_retrieve_empty_json(self, cli_runner, fake_http_client):
        """无结果 --json → 空 items 信封（正常路径，退出码 0）."""
        fake_http_client.post.return_value = {"items": []}
        result = cli_runner.invoke(
            app,
            ["retrieve", "--project-id", str(PID), "--query", "无"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["items"] == []

    def test_retrieve_missing_query_exit_2(self, cli_runner, fake_http_client):
        """缺 --query → 退出码 2（Typer 必填参数）."""
        result = cli_runner.invoke(
            app,
            ["retrieve", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()

    def test_retrieve_internal_error(self, cli_runner, fake_http_client):
        """向量库未装配（HTTP 500 无错误码头）→ INTERNAL_ERROR 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(500, "向量库未装配")
        result = cli_runner.invoke(
            app,
            ["retrieve", "--project-id", str(PID), "--query", "林晚"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_retrieve_invalid_type_exit_2(self, cli_runner, fake_http_client):
        """--type 非法值 → 退出码 2（Typer Choice 校验）."""
        result = cli_runner.invoke(
            app,
            [
                "retrieve",
                "--project-id",
                str(PID),
                "--query",
                "林晚",
                "--type",
                "bogus",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()


class TestVectorErrorBranches:
    """补齐 miss 行：typer.Exit 透传（reindex）、INTERNAL_ERROR 兜底（retrieve）."""

    def test_reindex_typer_exit_reraises(self, cli_runner, fake_http_client):
        """Client 抛 typer.Exit → 原样透传（退出码 3，不映射错误信封）."""
        fake_http_client.post.side_effect = typer.Exit(3)
        result = cli_runner.invoke(
            app,
            ["reindex", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 3

    def test_retrieve_db_error(self, cli_runner, fake_http_client):
        """HTTP 500 无错误码头 → INTERNAL_ERROR 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(500, "向量检索内部错误")
        result = cli_runner.invoke(
            app,
            ["retrieve", "--project-id", str(PID), "--query", "林晚"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert "向量检索内部错误" in data["error"]["message"]
