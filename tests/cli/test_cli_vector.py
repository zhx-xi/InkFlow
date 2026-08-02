"""F14 vector CLI 命令测试 — Mock ExtractionService 隔离数据库（spec §4/§9 CLI 测试）.

覆盖（依据 specs/f14-extraction-service/spec.md §4/§9）:
- vector reindex 缺省（--type 省略 = None 透传）与多 --type 指定
- vector retrieve 参数透传（--query/--type/--top-k/--min-score）与排序输出
- 信封格式与退出码 0/1/2；RAG_ERROR / NOT_FOUND 信封
- --type 非法值 → 退出码 2；缺 --query → 退出码 2
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.vector import app
from inkflow.cli.context import CliContext
from inkflow.domain.models.extraction import ReindexResult
from inkflow.domain.ports.extraction_errors import RAGUnavailableError
from inkflow.domain.ports.vector_store import EntityType, RetrievedEntity

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def mock_extraction_service():
    """Mock ExtractionService，绕过数据库（ADR-015 依赖注入）."""
    with patch(
        "inkflow.cli.commands.vector.ExtractionService", autospec=True
    ) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_create_tables():
    """Mock create_tables 避免数据库初始化."""
    with patch("inkflow.cli.commands.vector.create_tables", AsyncMock()):
        yield


def _make_reindex_result(**overrides) -> ReindexResult:
    """构造测试用 ReindexResult 领域对象."""
    defaults = dict(
        project_id=PID,
        entity_types=list(EntityType),
        indexed=87,
        warnings=[],
    )
    defaults.update(overrides)
    return ReindexResult(**defaults)


def _make_retrieved(**overrides) -> RetrievedEntity:
    """构造测试用 RetrievedEntity 领域对象."""
    defaults = dict(
        entity_id="f-0001",
        entity_type=EntityType.FORESHADOWING,
        content="伏笔：林晚的身世。林晚右肩的胎记与女主母亲的信物相同。",
        relevance_score=0.82,
        metadata={"name": "林晚的身世", "project_id": str(PID)},
    )
    defaults.update(overrides)
    return RetrievedEntity(**defaults)


class TestVectorRegistration:
    def test_group_help_lists_all_commands(self):
        """vector 组帮助包含 reindex/retrieve 两个命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）."""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in ("reindex", "retrieve"):
            assert name in result.output


class TestVectorReindex:
    def test_reindex_default_json(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """reindex 缺省 --type → entity_types=None 透传（服务层全量 5 种）."""
        mock_extraction_service.reindex.return_value = _make_reindex_result()
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
        mock_extraction_service.reindex.assert_awaited_once_with(
            project_id=PID, entity_types=None
        )

    def test_reindex_multiple_types(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """可重复 --type 指定多个实体类型 → 列表透传."""
        mock_extraction_service.reindex.return_value = _make_reindex_result(
            entity_types=[EntityType.CHARACTER, EntityType.SETTING], indexed=12
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
        mock_extraction_service.reindex.assert_awaited_once_with(
            project_id=PID,
            entity_types=[EntityType.CHARACTER, EntityType.SETTING],
        )

    def test_reindex_human(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """reindex 人类模式 → ✅ 索引完成（类型列表 + 总数）."""
        mock_extraction_service.reindex.return_value = _make_reindex_result()
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

    def test_reindex_rag_error(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """向量库未装配 → RAG_ERROR 错误信封 + 退出码 1."""
        mock_extraction_service.reindex.side_effect = RAGUnavailableError()
        result = cli_runner.invoke(
            app,
            ["reindex", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "RAG_ERROR"

    def test_reindex_invalid_uuid(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
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
        mock_extraction_service.reindex.assert_not_awaited()

    def test_reindex_invalid_type_exit_2(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """--type 非法值 → 退出码 2（Typer Choice 校验）."""
        result = cli_runner.invoke(
            app,
            ["reindex", "--project-id", str(PID), "--type", "bogus"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_extraction_service.reindex.assert_not_awaited()


class TestVectorRetrieve:
    def test_retrieve_json(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """retrieve --json → 成功信封 + items 数组（含实体类型/分数/metadata）."""
        mock_extraction_service.retrieve.return_value = [_make_retrieved()]
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
        mock_extraction_service.retrieve.assert_awaited_once_with(
            "林晚右肩的胎记",
            project_id=PID,
            entity_types=None,
            top_k=5,
            min_score=0.5,
        )

    def test_retrieve_type_filter(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """--type 限定实体类型 → 列表透传."""
        mock_extraction_service.retrieve.return_value = []
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
        mock_extraction_service.retrieve.assert_awaited_once_with(
            "林晚",
            project_id=PID,
            entity_types=[EntityType.FORESHADOWING, EntityType.CHARACTER],
            top_k=10,
            min_score=0.0,
        )

    def test_retrieve_sorted_output(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """结果按 relevance_score 降序输出（服务返回乱序时 CLI 负责排序）."""
        mock_extraction_service.retrieve.return_value = [
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

    def test_retrieve_human(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """retrieve 人类模式 → 🔍 检索结果（query/top + 编号条目 + 内容片段）."""
        mock_extraction_service.retrieve.return_value = [
            _make_retrieved(
                content=(
                    "伏笔：林晚的身世。林晚右肩的胎记与女主母亲的信物相同"
                    "（埋设位置：第 5 章）"
                )
            )
        ]
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

    def test_retrieve_empty(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """无结果 → 人类模式提示未找到（正常路径，退出码 0）."""
        mock_extraction_service.retrieve.return_value = []
        result = cli_runner.invoke(
            app,
            ["retrieve", "--project-id", str(PID), "--query", "不存在的关键词"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "未找到相关结果" in result.output

    def test_retrieve_empty_json(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """无结果 --json → 空 items 信封（正常路径，退出码 0）."""
        mock_extraction_service.retrieve.return_value = []
        result = cli_runner.invoke(
            app,
            ["retrieve", "--project-id", str(PID), "--query", "无"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["items"] == []

    def test_retrieve_missing_query_exit_2(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """缺 --query → 退出码 2（Typer 必填参数）."""
        result = cli_runner.invoke(
            app,
            ["retrieve", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_extraction_service.retrieve.assert_not_awaited()

    def test_retrieve_rag_error(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
        """向量库未装配 → RAG_ERROR 错误信封 + 退出码 1."""
        mock_extraction_service.retrieve.side_effect = RAGUnavailableError()
        result = cli_runner.invoke(
            app,
            ["retrieve", "--project-id", str(PID), "--query", "林晚"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "RAG_ERROR"

    def test_retrieve_invalid_type_exit_2(
        self, cli_runner, mock_extraction_service, mock_create_tables
    ):
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
        mock_extraction_service.retrieve.assert_not_awaited()
