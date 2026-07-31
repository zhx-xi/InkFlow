"""Project CLI 命令测试 — Mock ProjectService 隔离数据库."""

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.context import CliContext
from inkflow.domain.models.project import Project


@pytest.fixture
def cli_runner():
    # 注意: click 8.4 已移除 mix_stderr 参数，默认混合输出
    return CliRunner()


@pytest.fixture
def mock_project_service():
    """Mock ProjectService，绕过数据库."""
    with patch("inkflow.cli.commands.project.ProjectService", autospec=True) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_create_tables():
    """Mock create_tables 避免数据库初始化."""
    with patch("inkflow.cli.commands.project.create_tables", AsyncMock()):
        yield


def _make_project(**overrides) -> Project:
    """构造测试用 Project 领域对象."""
    defaults = dict(
        id=uuid.uuid4(),
        name="星辰变",
        genre="玄幻",
        language="zh-CN",
        target_words=100000,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        is_deleted=False,
    )
    defaults.update(overrides)
    return Project(**defaults)


class TestProjectCreate:
    def test_create_json_envelope(self, cli_runner, mock_project_service, mock_create_tables):
        """--json 模式创建项目 → 信封."""
        from inkflow.cli.commands.project import app

        mock_project_service.create_project.return_value = _make_project()
        result = cli_runner.invoke(
            app, ["create", "--name", "星辰变"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "星辰变"
        assert data["data"]["genre"] == "玄幻"

    def test_create_human_mode(self, cli_runner, mock_project_service, mock_create_tables):
        """人类模式创建项目."""
        from inkflow.cli.commands.project import app

        mock_project_service.create_project.return_value = _make_project()
        result = cli_runner.invoke(
            app, ["create", "--name", "星辰变"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "星辰变" in result.output


class TestProjectGet:
    def test_get_json(self, cli_runner, mock_project_service, mock_create_tables):
        """项目存在 → 信封."""
        from inkflow.cli.commands.project import app

        mock_project_service.get.return_value = _make_project()
        result = cli_runner.invoke(app, ["get", "--id", "1"], obj=CliContext(json_output=True))
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "星辰变"

    def test_get_not_found_json(self, cli_runner, mock_project_service, mock_create_tables):
        """项目不存在 → 退出码 1 + 错误信封."""
        from inkflow.cli.commands.project import app

        mock_project_service.get.return_value = None
        result = cli_runner.invoke(app, ["get", "--id", "999"], obj=CliContext(json_output=True))
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestProjectList:
    def test_list_json(self, cli_runner, mock_project_service, mock_create_tables):
        """列出项目 JSON 模式."""
        from inkflow.cli.commands.project import app

        mock_project_service.list_projects.return_value = ([_make_project()], 1)
        result = cli_runner.invoke(app, ["list"], obj=CliContext(json_output=True))
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert isinstance(data["data"], list)
        assert data["data"][0]["name"] == "星辰变"

    def test_list_human_empty(self, cli_runner, mock_project_service, mock_create_tables):
        """空列表人类模式."""
        from inkflow.cli.commands.project import app

        mock_project_service.list_projects.return_value = ([], 0)
        result = cli_runner.invoke(app, ["list"], obj=CliContext(json_output=False))
        assert result.exit_code == 0
        assert "暂无项目" in result.output


class TestProjectDelete:
    def test_delete_without_force_prompts(
        self, cli_runner, mock_project_service, mock_create_tables
    ):
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
