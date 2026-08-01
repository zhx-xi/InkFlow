"""Chapter/Volume CLI 命令测试."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.chapter import chapter_app, volume_app
from inkflow.cli.context import CliContext
from inkflow.domain.models.chapter import Chapter, ChapterStatus, Volume


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def mock_chapter_service():
    with patch(
        "inkflow.cli.commands.chapter.ChapterService", autospec=True
    ) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_create_tables():
    with patch("inkflow.cli.commands.chapter.create_tables", AsyncMock()):
        yield


def _make_chapter(**overrides) -> Chapter:
    """构造测试用 Chapter 领域对象."""
    return Chapter(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="测试章",
        content="",
        status=ChapterStatus.DRAFT,
        word_count=0,
        volume_id=None,
        order_index=1.0,
        **overrides,
    )


def _make_volume(**overrides) -> Volume:
    """构造测试用 Volume 领域对象."""
    return Volume(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="第一卷",
        order_index=1.0,
        **overrides,
    )


class TestChapterCreate:
    def test_create_json(self, cli_runner, mock_chapter_service, mock_create_tables):
        """create --json 输出 JSON 信封."""
        mock_chapter_service.create_chapter.return_value = _make_chapter()
        result = cli_runner.invoke(
            chapter_app,
            ["create", "--project-id", str(uuid.uuid4()), "--title", "测试章"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["title"] == "测试章"

    def test_create_human(self, cli_runner, mock_chapter_service, mock_create_tables):
        """create 人类可读模式正常退出."""
        mock_chapter_service.create_chapter.return_value = _make_chapter()
        result = cli_runner.invoke(
            chapter_app,
            ["create", "--project-id", str(uuid.uuid4()), "--title", "测试章"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0


class TestChapterGet:
    def test_get_not_found(self, cli_runner, mock_chapter_service, mock_create_tables):
        """章节不存在时输出错误信封并退出码 1."""
        mock_chapter_service.get_chapter.return_value = None
        result = cli_runner.invoke(
            chapter_app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"

    def test_get_found_json(self, cli_runner, mock_chapter_service, mock_create_tables):
        """章节存在时输出成功信封."""
        mock_chapter_service.get_chapter.return_value = _make_chapter()
        result = cli_runner.invoke(
            chapter_app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["title"] == "测试章"


class TestVolumeCreate:
    def test_create_volume_json(
        self, cli_runner, mock_chapter_service, mock_create_tables
    ):
        """volume create --json 输出 JSON 信封."""
        mock_chapter_service.create_volume.return_value = _make_volume()
        result = cli_runner.invoke(
            volume_app,
            ["create", "--project-id", str(uuid.uuid4()), "--title", "第一卷"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["title"] == "第一卷"


class TestChapterDelete:
    def test_delete_force(self, cli_runner, mock_chapter_service, mock_create_tables):
        """delete --force 跳过确认并成功删除."""
        mock_chapter_service.delete_chapter.return_value = True
        result = cli_runner.invoke(
            chapter_app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["deleted"] is True
