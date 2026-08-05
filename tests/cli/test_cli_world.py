"""World CLI 命令测试 — Mock WorldService 隔离数据库（spec §4 CLI 测试）.

覆盖（依据 specs/f10-world-service/spec.md §4/§4.2）:
- 各子命令成功路径与参数透传（create/list/categories/get/update/delete/restore/extract）
- 信封格式与退出码 0/1/2
- delete 二次确认 + --force；--json + delete 无 --force → VALIDATION_ERROR
- --text 与 --text-file 互斥 → 退出码 2
- extract 人类可读摘要与 --json 完整结果
- NOT_FOUND、LLM_ERROR、VALIDATION_ERROR 错误信封
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from inkflow.cli.commands.world import app
from inkflow.cli.context import CliContext
from inkflow.domain.models.world import (
    WorldExtractionResult,
    WorldExtractRequest,
    WorldSetting,
    WorldUpdate,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.world_errors import (
    ProjectNotFoundError,
    WorldExtractionError,
    WorldNameConflictError,
    WorldServiceError,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def mock_world_service():
    """Mock WorldService，绕过数据库（ADR-015 依赖注入）."""
    with patch("inkflow.cli.commands.world.WorldService", autospec=True) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_create_tables():
    """Mock create_tables 避免数据库初始化."""
    with patch("inkflow.cli.commands.world.create_tables", AsyncMock()):
        yield


def _make_setting(**overrides) -> WorldSetting:
    """构造测试用 WorldSetting 领域对象."""
    defaults = dict(
        id=uuid.uuid4(),
        project_id=PID,
        name="灵气复苏",
        category="设定",
        content="天地灵气重新复苏，修炼体系重现。",
        extra={},
        is_deleted=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return WorldSetting(**defaults)


def _make_extraction_result(**overrides) -> WorldExtractionResult:
    """构造测试用 WorldExtractionResult 领域对象."""
    defaults = dict(
        created=[_make_setting()],
        updated=[],
        warnings=['条目 "？？" 名称为空已跳过'],
        model="deepseek/deepseek-chat",
    )
    defaults.update(overrides)
    return WorldExtractionResult(**defaults)


class TestWorldCreate:
    def test_create_json_envelope(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """create --json → 成功信封 + 参数透传（UUID 转换）."""
        mock_world_service.create_setting.return_value = _make_setting(name="灵气复苏")
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "灵气复苏",
                "--category",
                "设定",
                "--content",
                "天地灵气重新复苏。",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "灵气复苏"
        assert data["data"]["category"] == "设定"
        mock_world_service.create_setting.assert_awaited_once_with(
            project_id=PID,
            name="灵气复苏",
            category="设定",
            content="天地灵气重新复苏。",
        )

    def test_create_human(self, cli_runner, mock_world_service, mock_create_tables):
        """create 人类模式 → 成功提示（含类别）."""
        mock_world_service.create_setting.return_value = _make_setting(name="灵气复苏")
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "灵气复苏",
                "--category",
                "设定",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "世界观条目创建成功" in result.output
        assert "灵气复苏" in result.output
        assert "设定" in result.output

    def test_create_name_conflict(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """同名条目 → VALIDATION_ERROR 信封 + 退出码 1."""
        mock_world_service.create_setting.side_effect = WorldNameConflictError()
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "灵气复苏"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"


class TestWorldList:
    def test_list_json(self, cli_runner, mock_world_service, mock_create_tables):
        """list --json → 成功信封 + 条目数组."""
        mock_world_service.list_settings.return_value = ([_make_setting()], 1)
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert isinstance(data["data"], list)
        assert data["data"][0]["name"] == "灵气复苏"

    def test_list_human_empty(self, cli_runner, mock_world_service, mock_create_tables):
        """空列表人类模式 → 暂无条目."""
        mock_world_service.list_settings.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无条目" in result.output

    def test_list_params_passthrough(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """list 搜索/类别/排序/分页参数透传."""
        mock_world_service.list_settings.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            [
                "list",
                "--project-id",
                str(PID),
                "--search",
                "灵气",
                "--category",
                "设定",
                "--sort",
                "name",
                "--no-sort-desc",
                "--offset",
                "10",
                "--limit",
                "5",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        mock_world_service.list_settings.assert_awaited_once_with(
            project_id=PID,
            search="灵气",
            category="设定",
            sort_by="name",
            sort_desc=False,
            offset=10,
            limit=5,
        )


class TestWorldCategories:
    def test_categories_json(self, cli_runner, mock_world_service, mock_create_tables):
        """categories --json → 类别计数列表信封."""
        mock_world_service.list_categories.return_value = [("设定", 3), ("地理", 1)]
        result = cli_runner.invoke(
            app,
            ["categories", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"][0] == {"category": "设定", "count": 3}
        assert data["data"][1] == {"category": "地理", "count": 1}
        mock_world_service.list_categories.assert_awaited_once_with(project_id=PID)

    def test_categories_human_empty(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """空类别人类模式 → 暂无类别."""
        mock_world_service.list_categories.return_value = []
        result = cli_runner.invoke(
            app,
            ["categories", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无类别" in result.output


class TestWorldGet:
    def test_get_json(self, cli_runner, mock_world_service, mock_create_tables):
        """条目存在 → 成功信封."""
        sid = uuid.uuid4()
        mock_world_service.get_setting.return_value = _make_setting(name="灵气复苏")
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(sid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "灵气复苏"
        mock_world_service.get_setting.assert_awaited_once_with(setting_id=sid)

    def test_get_not_found_json(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """条目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_world_service.get_setting.return_value = None
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "世界观条目不存在" in data["error"]["message"]

    def test_get_invalid_uuid(self, cli_runner, mock_world_service, mock_create_tables):
        """无效 UUID → NOT_FOUND（spec §7: 无效 UUID 格式 → 404 语义）."""
        result = cli_runner.invoke(
            app,
            ["get", "--id", "not-a-uuid"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestWorldUpdate:
    def test_update_json(self, cli_runner, mock_world_service, mock_create_tables):
        """update --json → 成功信封 + WorldUpdate 透传（仅传入字段）."""
        sid = uuid.uuid4()
        mock_world_service.update_setting.return_value = _make_setting(
            name="灵气复苏·改"
        )
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                str(sid),
                "--name",
                "灵气复苏·改",
                "--content",
                "新内容",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "灵气复苏·改"
        call = mock_world_service.update_setting.await_args
        assert call.kwargs["setting_id"] == sid
        upd: WorldUpdate = call.kwargs["update"]
        assert upd.name == "灵气复苏·改"
        assert upd.content == "新内容"
        assert "category" not in upd.model_fields_set

    def test_update_clear_category(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """update --category \"\" → 显式清除类别（category=\"\" 进入 update）."""
        sid = uuid.uuid4()
        mock_world_service.update_setting.return_value = _make_setting()
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(sid), "--category", ""],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_world_service.update_setting.await_args
        upd: WorldUpdate = call.kwargs["update"]
        assert "category" in upd.model_fields_set
        assert upd.category == ""

    def test_update_not_found(self, cli_runner, mock_world_service, mock_create_tables):
        """条目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_world_service.update_setting.return_value = None
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--name", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestWorldDelete:
    def test_delete_force_json(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """delete --force --json → 成功信封 + 软删除（force=False）."""
        sid = uuid.uuid4()
        mock_world_service.delete_setting.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        mock_world_service.delete_setting.assert_awaited_once_with(
            setting_id=sid, force=False
        )

    def test_delete_permanent_passes_force(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """delete --permanent → 服务层 force=True（物理删除）."""
        sid = uuid.uuid4()
        mock_world_service.delete_setting.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid), "--force", "--permanent"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        mock_world_service.delete_setting.assert_awaited_once_with(
            setting_id=sid, force=True
        )

    def test_delete_confirm_yes(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除."""
        sid = uuid.uuid4()
        mock_world_service.delete_setting.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output
        mock_world_service.delete_setting.assert_awaited_once_with(
            setting_id=sid, force=False
        )

    def test_delete_confirm_no(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """无 --force 人类模式 → 回答 n 取消，不调用服务."""
        sid = uuid.uuid4()
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid)],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "取消" in result.output
        mock_world_service.delete_setting.assert_not_awaited()

    def test_delete_json_no_force(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """--json 且无 --force → VALIDATION_ERROR + 退出码 1（F7 §7 约定）."""
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        mock_world_service.delete_setting.assert_not_awaited()

    def test_delete_not_found(self, cli_runner, mock_world_service, mock_create_tables):
        """条目不存在（服务返回 False）→ NOT_FOUND 错误信封."""
        mock_world_service.delete_setting.return_value = False
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestWorldRestore:
    def test_restore_json(self, cli_runner, mock_world_service, mock_create_tables):
        """restore --json → 成功信封."""
        mock_world_service.restore_setting.return_value = _make_setting(name="灵气复苏")
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "灵气复苏"

    def test_restore_not_found(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """条目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_world_service.restore_setting.return_value = None
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestWorldExtract:
    def test_extract_json(self, cli_runner, mock_world_service, mock_create_tables):
        """extract --text --json → 完整结果信封 + WorldExtractRequest 透传."""
        mock_world_service.extract.return_value = _make_extraction_result()
        result = cli_runner.invoke(
            app,
            [
                "extract",
                "--project-id",
                str(PID),
                "--text",
                "灵气复苏后，大陆进入修炼时代。",
                "--model",
                "deepseek/deepseek-chat",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["created"][0]["name"] == "灵气复苏"
        assert data["data"]["model"] == "deepseek/deepseek-chat"
        call = mock_world_service.extract.await_args
        req: WorldExtractRequest = call.args[0]
        assert req.project_id == PID
        assert req.text == "灵气复苏后，大陆进入修炼时代。"
        assert req.model == "deepseek/deepseek-chat"

    def test_extract_human_summary(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """extract 人类模式 → 可读摘要（新增/更新/警告计数）."""
        mock_world_service.extract.return_value = _make_extraction_result(
            created=[_make_setting(name="灵气复苏"), _make_setting(name="修炼体系")],
            updated=[_make_setting(name="天玄大陆")],
            warnings=['条目 "？？" 名称为空已跳过', "条目 类别超长已跳过"],
        )
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "灵气复苏。"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "提取完成" in result.output
        assert "新增 2 个条目" in result.output
        assert "更新 1 个条目" in result.output
        assert "警告 2 条" in result.output

    def test_extract_text_file(
        self, cli_runner, mock_world_service, mock_create_tables, tmp_path
    ):
        """extract --text-file → 读取文件内容作为提取文本."""
        text_file = tmp_path / "ch3.txt"
        text_file.write_text("灵气复苏后，大陆进入修炼时代。", encoding="utf-8")
        mock_world_service.extract.return_value = _make_extraction_result()
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text-file", str(text_file)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_world_service.extract.await_args
        req: WorldExtractRequest = call.args[0]
        assert req.text == "灵气复苏后，大陆进入修炼时代。"
        assert req.model is None

    def test_extract_text_and_text_file_exclusive(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """--text 与 --text-file 同时传入 → 用法错误退出码 2."""
        result = cli_runner.invoke(
            app,
            [
                "extract",
                "--project-id",
                str(PID),
                "--text",
                "正文",
                "--text-file",
                "ch3.txt",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_world_service.extract.assert_not_awaited()

    def test_extract_llm_error(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """LLM 输出无法解析 → LLM_ERROR 错误信封 + 退出码 1."""
        mock_world_service.extract.side_effect = WorldExtractionError(
            detail="非法 JSON"
        )
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "灵气复苏。"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "LLM_ERROR"

    def test_extract_project_not_found(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_world_service.extract.side_effect = ProjectNotFoundError()
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "灵气复苏。"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestWorldErrorMapping:
    """_run 异常映射补全：LLMRequestError / ValidationError / 文件缺失 / DB_ERROR."""

    def test_extract_llm_request_error(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """LLMRequestError → LLM_ERROR 信封 + 退出码 1."""
        mock_world_service.extract.side_effect = LLMRequestError("LLM 调用失败")
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "灵气复苏。"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "LLM_ERROR"
        assert "LLM 调用失败" in data["error"]["message"]

    def test_extract_validation_error(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """pydantic ValidationError → VALIDATION_ERROR 信封."""
        mock_world_service.extract.side_effect = ValidationError.from_exception_data(
            "WorldExtractRequest",
            [
                {
                    "type": "string_type",
                    "loc": ("text",),
                    "msg": "Input should be a valid string",
                    "input": 123,
                }
            ],
        )
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "灵气复苏。"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_extract_service_error(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """服务抛 WorldServiceError → VALIDATION_ERROR 信封."""
        mock_world_service.extract.side_effect = WorldServiceError("同名条目")
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "灵气复苏。"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "同名条目" in data["error"]["message"]

    def test_extract_text_file_missing(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """extract --text-file 指向不存在文件 → VALIDATION_ERROR（文本文件不存在）."""
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text-file", "no_such_file.txt"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "文本文件不存在" in data["error"]["message"]
        mock_world_service.extract.assert_not_awaited()

    def test_extract_db_error(self, cli_runner, mock_world_service, mock_create_tables):
        """服务抛未知异常 → DB_ERROR 信封 + 退出码 1."""
        mock_world_service.extract.side_effect = RuntimeError("boom")
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "灵气复苏。"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"
        assert "boom" in data["error"]["message"]


class TestWorldHumanOutput:
    """人类可读输出补全：无类别创建 / list 非空 / categories / get / update /
    restore / extract 无警告。"""

    def test_create_human_no_category(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """create 人类模式无类别 → 提示不含类别括号."""
        mock_world_service.create_setting.return_value = _make_setting(category="")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "灵气复苏"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "世界观条目创建成功: [灵气复苏]" in result.output

    def test_list_human_non_empty(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """list 人类模式非空 → 总数汇总 + 条目列表."""
        mock_world_service.list_settings.return_value = (
            [_make_setting(name="灵气复苏")],
            1,
        )
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "共 1 个条目" in result.output
        assert "灵气复苏" in result.output

    def test_categories_human(self, cli_runner, mock_world_service, mock_create_tables):
        """categories 人类模式 → 逐类别输出（含条目数）."""
        mock_world_service.list_categories.return_value = [("设定", 3), ("地理", 1)]
        result = cli_runner.invoke(
            app,
            ["categories", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "设定: 3 条" in result.output
        assert "地理: 1 条" in result.output

    def test_get_human(self, cli_runner, mock_world_service, mock_create_tables):
        """get 人类模式 → 全字段详情输出."""
        mock_world_service.get_setting.return_value = _make_setting(
            name="灵气复苏", category="设定", content="天地灵气重新复苏。"
        )
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        for token in (
            "ID:",
            "名称:",
            "灵气复苏",
            "类别:",
            "设定",
            "内容:",
            "天地灵气重新复苏。",
        ):
            assert token in result.output

    def test_update_human(self, cli_runner, mock_world_service, mock_create_tables):
        """update 人类模式 → 成功提示."""
        mock_world_service.update_setting.return_value = _make_setting(
            name="灵气复苏·改"
        )
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--name", "灵气复苏·改"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "条目已更新: [灵气复苏·改]" in result.output

    def test_restore_human(self, cli_runner, mock_world_service, mock_create_tables):
        """restore 人类模式 → 成功提示."""
        mock_world_service.restore_setting.return_value = _make_setting(name="灵气复苏")
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "条目已恢复: [灵气复苏]" in result.output

    def test_extract_human_no_warnings(
        self, cli_runner, mock_world_service, mock_create_tables
    ):
        """extract 人类模式无警告 → 不输出警告提示行."""
        mock_world_service.extract.return_value = _make_extraction_result(warnings=[])
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "灵气复苏。"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "提取完成" in result.output
        assert "但有警告" not in result.output
