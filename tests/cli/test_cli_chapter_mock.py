"""Chapter/Volume CLI 命令测试."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.chapter import chapter_app, volume_app
from inkflow.cli.context import CliContext
from inkflow.domain.models.chapter import Chapter, ChapterStatus, ChapterUpdate, Volume


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

    def test_create_volume_human(
        self, cli_runner, mock_chapter_service, mock_create_tables
    ):
        """volume create 人类模式 → 成功提示（含卷标题）."""
        mock_chapter_service.create_volume.return_value = _make_volume()
        result = cli_runner.invoke(
            volume_app,
            ["create", "--project-id", str(uuid.uuid4()), "--title", "第一卷"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "卷创建成功: [第一卷]" in result.output


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

    def test_delete_confirm_no(
        self, cli_runner, mock_chapter_service, mock_create_tables
    ):
        """无 --force 人类模式 → 回答 n 取消，不调用服务."""
        cid = uuid.uuid4()
        result = cli_runner.invoke(
            chapter_app,
            ["delete", "--id", str(cid)],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        mock_chapter_service.delete_chapter.assert_not_awaited()

    def test_delete_not_found(
        self, cli_runner, mock_chapter_service, mock_create_tables
    ):
        """章节不存在（服务返回 False）→ NOT_FOUND 错误信封 + 退出码 1."""
        mock_chapter_service.delete_chapter.return_value = False
        result = cli_runner.invoke(
            chapter_app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"


class TestVolumeList:
    def test_list_json(self, cli_runner, mock_chapter_service, mock_create_tables):
        """volume list --json → 成功信封 + 卷数组."""
        mock_chapter_service.list_volumes.return_value = [_make_volume()]
        result = cli_runner.invoke(
            volume_app,
            ["list", "--project-id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"][0]["title"] == "第一卷"

    def test_list_human(self, cli_runner, mock_chapter_service, mock_create_tables):
        """volume list 人类模式 → 逐卷输出."""
        mock_chapter_service.list_volumes.return_value = [_make_volume()]
        result = cli_runner.invoke(
            volume_app,
            ["list", "--project-id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "第一卷" in result.output


class TestVolumeDelete:
    def test_delete_force_json(
        self, cli_runner, mock_chapter_service, mock_create_tables
    ):
        """volume delete --force --json → 成功信封 + 服务调用."""
        vid = uuid.uuid4()
        mock_chapter_service.delete_volume.return_value = True
        result = cli_runner.invoke(
            volume_app,
            ["delete", "--id", str(vid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["deleted"] is True
        mock_chapter_service.delete_volume.assert_awaited_once_with(vid)

    def test_delete_confirm_yes(
        self, cli_runner, mock_chapter_service, mock_create_tables
    ):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除."""
        vid = uuid.uuid4()
        mock_chapter_service.delete_volume.return_value = True
        result = cli_runner.invoke(
            volume_app,
            ["delete", "--id", str(vid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        mock_chapter_service.delete_volume.assert_awaited_once_with(vid)

    def test_delete_confirm_no(
        self, cli_runner, mock_chapter_service, mock_create_tables
    ):
        """无 --force 人类模式 → 回答 n 取消，不调用服务."""
        vid = uuid.uuid4()
        result = cli_runner.invoke(
            volume_app,
            ["delete", "--id", str(vid)],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        mock_chapter_service.delete_volume.assert_not_awaited()

    def test_delete_not_found(
        self, cli_runner, mock_chapter_service, mock_create_tables
    ):
        """卷不存在（服务返回 False）→ NOT_FOUND 错误信封."""
        mock_chapter_service.delete_volume.return_value = False
        result = cli_runner.invoke(
            volume_app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"


class TestChapterList:
    def test_list_json_with_filters(
        self, cli_runner, mock_chapter_service, mock_create_tables
    ):
        """chapter list --json → 信封 + volume_id/status 参数透传（UUID/枚举转换）."""
        pid, vid = uuid.uuid4(), uuid.uuid4()
        mock_chapter_service.list_chapters.return_value = ([_make_chapter()], 1)
        result = cli_runner.invoke(
            chapter_app,
            [
                "list",
                "--project-id",
                str(pid),
                "--volume-id",
                str(vid),
                "--status",
                "final",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["total"] == 1
        assert payload["data"]["chapters"][0]["title"] == "测试章"
        mock_chapter_service.list_chapters.assert_awaited_once_with(
            pid, vid, ChapterStatus.FINAL
        )

    def test_list_human_empty(
        self, cli_runner, mock_chapter_service, mock_create_tables
    ):
        """chapter list 人类模式空列表 → total 汇总输出."""
        mock_chapter_service.list_chapters.return_value = ([], 0)
        result = cli_runner.invoke(
            chapter_app,
            ["list", "--project-id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "total" in result.output


class TestChapterUpdate:
    def test_update_json(self, cli_runner, mock_chapter_service, mock_create_tables):
        """chapter update --json → 成功信封 + ChapterUpdate DTO 透传（status 转换）."""
        cid = uuid.uuid4()
        mock_chapter_service.update_chapter.return_value = _make_chapter()
        result = cli_runner.invoke(
            chapter_app,
            [
                "update",
                "--id",
                str(cid),
                "--title",
                "新标题",
                "--content",
                "正文",
                "--status",
                "final",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["title"] == "测试章"
        call = mock_chapter_service.update_chapter.await_args
        assert call.args[0] == cid
        dto: ChapterUpdate = call.args[1]
        assert dto.title == "新标题"
        assert dto.content == "正文"
        assert dto.status == ChapterStatus.FINAL

    def test_update_not_found(
        self, cli_runner, mock_chapter_service, mock_create_tables
    ):
        """章节不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_chapter_service.update_chapter.return_value = None
        result = cli_runner.invoke(
            chapter_app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新标题"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"


class TestChapterMove:
    def test_move_json(self, cli_runner, mock_chapter_service, mock_create_tables):
        """chapter move --json → 成功信封 + to_volume UUID 透传."""
        cid, vid = uuid.uuid4(), uuid.uuid4()
        mock_chapter_service.move_chapter.return_value = _make_chapter()
        result = cli_runner.invoke(
            chapter_app,
            ["move", "--id", str(cid), "--to-volume", str(vid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        mock_chapter_service.move_chapter.assert_awaited_once_with(cid, vid)

    def test_move_not_found(self, cli_runner, mock_chapter_service, mock_create_tables):
        """章节不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_chapter_service.move_chapter.return_value = None
        result = cli_runner.invoke(
            chapter_app,
            ["move", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"
