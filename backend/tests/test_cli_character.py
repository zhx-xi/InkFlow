"""Character CLI 命令测试 — Mock CharacterService 隔离数据库（spec §9 CLI 测试）.

覆盖（依据 specs/f9-character-service/spec.md §4/§7/§9）:
- 各子命令成功路径与参数透传（create/list/get/update/delete/restore/relate/unrelate/
  relations/extract + group 子组）
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
from typer.testing import CliRunner

from inkflow.cli.commands.character import app, group_app
from inkflow.cli.context import CliContext
from inkflow.domain.models.character import (
    Character,
    CharacterExtractionResult,
    CharacterExtractRequest,
    CharacterGroup,
    CharacterRelation,
    CharacterUpdate,
)
from inkflow.domain.ports.character_errors import (
    CharacterExtractionError,
    CharacterNameConflictError,
    ProjectNotFoundError,
    SelfRelationError,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def mock_character_service():
    """Mock CharacterService，绕过数据库（ADR-015 依赖注入）."""
    with patch("inkflow.cli.commands.character.CharacterService", autospec=True) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_create_tables():
    """Mock create_tables 避免数据库初始化."""
    with patch("inkflow.cli.commands.character.create_tables", AsyncMock()):
        yield


def _make_character(**overrides) -> Character:
    """构造测试用 Character 领域对象."""
    defaults = dict(
        id=uuid.uuid4(),
        project_id=PID,
        name="林尘",
        personality="坚毅",
        background="出身贫寒",
        goals="成为强者",
        group_id=None,
        extra={},
        is_deleted=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return Character(**defaults)


def _make_group(**overrides) -> CharacterGroup:
    """构造测试用 CharacterGroup 领域对象."""
    defaults = dict(
        id=uuid.uuid4(),
        project_id=PID,
        name="主角团",
        description="核心小队",
        sort_order=0,
        is_deleted=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return CharacterGroup(**defaults)


def _make_relation(**overrides) -> CharacterRelation:
    """构造测试用 CharacterRelation 领域对象."""
    defaults = dict(
        id=uuid.uuid4(),
        project_id=PID,
        from_character_id=uuid.uuid4(),
        to_character_id=uuid.uuid4(),
        relation_type="师徒",
        description="亦师亦友",
        is_deleted=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return CharacterRelation(**defaults)


def _make_extraction_result(**overrides) -> CharacterExtractionResult:
    """构造测试用 CharacterExtractionResult 领域对象."""
    defaults = dict(
        created=[_make_character()],
        updated=[],
        relations_created=[_make_relation()],
        relations_updated=[],
        warnings=['角色 "？？" 名称为空已跳过'],
        model="deepseek/deepseek-chat",
    )
    defaults.update(overrides)
    return CharacterExtractionResult(**defaults)


class TestCharacterCreate:
    def test_create_json_envelope(self, cli_runner, mock_character_service, mock_create_tables):
        """create --json → 成功信封 + 参数透传（UUID 转换）."""
        mock_character_service.create_character.return_value = _make_character(name="林尘")
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "林尘",
                "--personality",
                "坚毅",
                "--background",
                "出身贫寒",
                "--goals",
                "成为强者",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "林尘"
        mock_character_service.create_character.assert_awaited_once_with(
            project_id=PID,
            name="林尘",
            personality="坚毅",
            background="出身贫寒",
            goals="成为强者",
            group_id=None,
        )

    def test_create_with_group_id(self, cli_runner, mock_character_service, mock_create_tables):
        """create --group-id → 透传 UUID."""
        gid = uuid.uuid4()
        mock_character_service.create_character.return_value = _make_character(group_id=gid)
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "林尘", "--group-id", str(gid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        mock_character_service.create_character.assert_awaited_once_with(
            project_id=PID,
            name="林尘",
            personality="",
            background="",
            goals="",
            group_id=gid,
        )

    def test_create_human(self, cli_runner, mock_character_service, mock_create_tables):
        """create 人类模式 → 成功提示."""
        mock_character_service.create_character.return_value = _make_character(name="林尘")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "林尘"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "角色创建成功" in result.output

    def test_create_name_conflict(self, cli_runner, mock_character_service, mock_create_tables):
        """同名角色 → VALIDATION_ERROR 信封 + 退出码 1."""
        mock_character_service.create_character.side_effect = CharacterNameConflictError()
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "林尘"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"


class TestCharacterList:
    def test_list_json(self, cli_runner, mock_character_service, mock_create_tables):
        """list --json → 成功信封 + 角色数组."""
        mock_character_service.list_characters.return_value = ([_make_character()], 1)
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert isinstance(data["data"], list)
        assert data["data"][0]["name"] == "林尘"

    def test_list_human_empty(self, cli_runner, mock_character_service, mock_create_tables):
        """空列表人类模式 → 暂无角色."""
        mock_character_service.list_characters.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无角色" in result.output

    def test_list_params_passthrough(self, cli_runner, mock_character_service, mock_create_tables):
        """list 搜索/分组/排序/分页参数透传."""
        gid = uuid.uuid4()
        mock_character_service.list_characters.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            [
                "list",
                "--project-id",
                str(PID),
                "--search",
                "林",
                "--group-id",
                str(gid),
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
        mock_character_service.list_characters.assert_awaited_once_with(
            project_id=PID,
            search="林",
            group_id=gid,
            sort_by="name",
            sort_desc=False,
            offset=10,
            limit=5,
        )


class TestCharacterGet:
    def test_get_json(self, cli_runner, mock_character_service, mock_create_tables):
        """角色存在 → 成功信封."""
        cid = uuid.uuid4()
        mock_character_service.get_character.return_value = _make_character(name="林尘")
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(cid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "林尘"
        mock_character_service.get_character.assert_awaited_once_with(character_id=cid)

    def test_get_not_found_json(self, cli_runner, mock_character_service, mock_create_tables):
        """角色不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_character_service.get_character.return_value = None
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "角色不存在" in data["error"]["message"]

    def test_get_invalid_uuid(self, cli_runner, mock_character_service, mock_create_tables):
        """无效 UUID → NOT_FOUND（spec §7: 无效 UUID 格式 → 404 角色不存在）."""
        result = cli_runner.invoke(
            app,
            ["get", "--id", "not-a-uuid"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestCharacterUpdate:
    def test_update_json(self, cli_runner, mock_character_service, mock_create_tables):
        """update --json → 成功信封 + CharacterUpdate 透传（仅传入字段）."""
        cid = uuid.uuid4()
        mock_character_service.update_character.return_value = _make_character(name="林尘二世")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(cid), "--name", "林尘二世", "--personality", "沉稳"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "林尘二世"
        call = mock_character_service.update_character.await_args
        assert call.kwargs["character_id"] == cid
        upd: CharacterUpdate = call.kwargs["update"]
        assert upd.name == "林尘二世"
        assert upd.personality == "沉稳"
        assert "background" not in upd.model_fields_set
        assert "goals" not in upd.model_fields_set

    def test_update_clear_group(self, cli_runner, mock_character_service, mock_create_tables):
        """update --group-id \"\" → 显式清除分组（group_id=None 进入 update）."""
        cid = uuid.uuid4()
        mock_character_service.update_character.return_value = _make_character()
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(cid), "--group-id", ""],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_character_service.update_character.await_args
        upd: CharacterUpdate = call.kwargs["update"]
        assert "group_id" in upd.model_fields_set
        assert upd.group_id is None

    def test_update_not_found(self, cli_runner, mock_character_service, mock_create_tables):
        """角色不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_character_service.update_character.return_value = None
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--name", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestCharacterDelete:
    def test_delete_force_json(self, cli_runner, mock_character_service, mock_create_tables):
        """delete --force --json → 成功信封 + 软删除（force=False）."""
        cid = uuid.uuid4()
        mock_character_service.delete_character.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(cid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        mock_character_service.delete_character.assert_awaited_once_with(
            character_id=cid, force=False
        )

    def test_delete_permanent_passes_force(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """delete --permanent → 服务层 force=True（物理删除）."""
        cid = uuid.uuid4()
        mock_character_service.delete_character.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(cid), "--force", "--permanent"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        mock_character_service.delete_character.assert_awaited_once_with(
            character_id=cid, force=True
        )

    def test_delete_confirm_yes(self, cli_runner, mock_character_service, mock_create_tables):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除."""
        cid = uuid.uuid4()
        mock_character_service.delete_character.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(cid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output
        mock_character_service.delete_character.assert_awaited_once_with(
            character_id=cid, force=False
        )

    def test_delete_confirm_no(self, cli_runner, mock_character_service, mock_create_tables):
        """无 --force 人类模式 → 回答 n 取消，不调用服务."""
        cid = uuid.uuid4()
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(cid)],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "取消" in result.output
        mock_character_service.delete_character.assert_not_awaited()

    def test_delete_json_no_force(self, cli_runner, mock_character_service, mock_create_tables):
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
        mock_character_service.delete_character.assert_not_awaited()

    def test_delete_not_found(self, cli_runner, mock_character_service, mock_create_tables):
        """角色不存在（服务返回 False）→ NOT_FOUND 错误信封."""
        mock_character_service.delete_character.return_value = False
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestCharacterRestore:
    def test_restore_json(self, cli_runner, mock_character_service, mock_create_tables):
        """restore --json → 成功信封."""
        mock_character_service.restore_character.return_value = _make_character(name="林尘")
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "林尘"

    def test_restore_not_found(self, cli_runner, mock_character_service, mock_create_tables):
        """角色不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_character_service.restore_character.return_value = None
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestCharacterRelate:
    def test_relate_json(self, cli_runner, mock_character_service, mock_create_tables):
        """relate --json → 成功信封 + 参数透传."""
        cid, to = uuid.uuid4(), uuid.uuid4()
        mock_character_service.create_relation.return_value = _make_relation(relation_type="师徒")
        result = cli_runner.invoke(
            app,
            [
                "relate",
                "--id",
                str(cid),
                "--to",
                str(to),
                "--type",
                "师徒",
                "--description",
                "亦师亦友",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["relation_type"] == "师徒"
        mock_character_service.create_relation.assert_awaited_once_with(
            character_id=cid,
            to_character_id=to,
            relation_type="师徒",
            description="亦师亦友",
        )

    def test_relate_self_error(self, cli_runner, mock_character_service, mock_create_tables):
        """自环关系 → VALIDATION_ERROR 错误信封 + 退出码 1."""
        mock_character_service.create_relation.side_effect = SelfRelationError()
        result = cli_runner.invoke(
            app,
            ["relate", "--id", str(uuid.uuid4()), "--to", str(uuid.uuid4()), "--type", "师徒"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"


class TestCharacterUnrelate:
    def test_unrelate_force_json(self, cli_runner, mock_character_service, mock_create_tables):
        """unrelate --force --json → 成功信封 + 参数透传."""
        cid, rid = uuid.uuid4(), uuid.uuid4()
        mock_character_service.delete_relation.return_value = True
        result = cli_runner.invoke(
            app,
            ["unrelate", "--id", str(cid), "--relation-id", str(rid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        mock_character_service.delete_relation.assert_awaited_once_with(
            character_id=cid, relation_id=rid
        )

    def test_unrelate_json_no_force(self, cli_runner, mock_character_service, mock_create_tables):
        """unrelate --json 且无 --force → VALIDATION_ERROR."""
        result = cli_runner.invoke(
            app,
            ["unrelate", "--id", str(uuid.uuid4()), "--relation-id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"


class TestCharacterRelations:
    def test_relations_json(self, cli_runner, mock_character_service, mock_create_tables):
        """relations --json → 双向关系列表信封."""
        cid = uuid.uuid4()
        mock_character_service.list_relations.return_value = [_make_relation()]
        result = cli_runner.invoke(
            app,
            ["relations", "--id", str(cid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert isinstance(data["data"], list)
        assert data["data"][0]["relation_type"] == "师徒"
        mock_character_service.list_relations.assert_awaited_once_with(character_id=cid)


class TestCharacterExtract:
    def test_extract_json(self, cli_runner, mock_character_service, mock_create_tables):
        """extract --text --json → 完整结果信封 + CharacterExtractRequest 透传."""
        mock_character_service.extract.return_value = _make_extraction_result()
        result = cli_runner.invoke(
            app,
            [
                "extract",
                "--project-id",
                str(PID),
                "--text",
                "林尘是主角，萧炎是他的师父。",
                "--model",
                "deepseek/deepseek-chat",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["created"][0]["name"] == "林尘"
        assert data["data"]["relations_created"][0]["relation_type"] == "师徒"
        assert data["data"]["model"] == "deepseek/deepseek-chat"
        call = mock_character_service.extract.await_args
        req: CharacterExtractRequest = call.args[0]
        assert req.project_id == PID
        assert req.text == "林尘是主角，萧炎是他的师父。"
        assert req.model == "deepseek/deepseek-chat"

    def test_extract_human_summary(self, cli_runner, mock_character_service, mock_create_tables):
        """extract 人类模式 → 可读摘要（新增/更新/关系/警告计数）."""
        mock_character_service.extract.return_value = _make_extraction_result(
            created=[_make_character(name="林尘"), _make_character(name="萧炎")],
            updated=[_make_character(name="药老")],
            relations_created=[_make_relation()],
            warnings=['角色 "？？" 名称为空已跳过', "关系 萧炎→？？ 无法解析已跳过"],
        )
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "林尘是主角。"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "提取完成" in result.output
        assert "新增 2 个角色" in result.output
        assert "更新 1 个角色" in result.output
        assert "警告 2 条" in result.output

    def test_extract_text_file(
        self, cli_runner, mock_character_service, mock_create_tables, tmp_path
    ):
        """extract --text-file → 读取文件内容作为提取文本."""
        text_file = tmp_path / "ch3.txt"
        text_file.write_text("林尘是主角，萧炎是他的师父。", encoding="utf-8")
        mock_character_service.extract.return_value = _make_extraction_result()
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text-file", str(text_file)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_character_service.extract.await_args
        req: CharacterExtractRequest = call.args[0]
        assert req.text == "林尘是主角，萧炎是他的师父。"
        assert req.model is None

    def test_extract_text_and_text_file_exclusive(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """--text 与 --text-file 同时传入 → 用法错误退出码 2."""
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "正文", "--text-file", "ch3.txt"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_character_service.extract.assert_not_awaited()

    def test_extract_llm_error(self, cli_runner, mock_character_service, mock_create_tables):
        """LLM 输出无法解析 → LLM_ERROR 错误信封 + 退出码 1."""
        mock_character_service.extract.side_effect = CharacterExtractionError(detail="非法 JSON")
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "林尘是主角。"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "LLM_ERROR"

    def test_extract_project_not_found(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_character_service.extract.side_effect = ProjectNotFoundError()
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "林尘是主角。"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestGroupCommands:
    def test_group_create_json(self, cli_runner, mock_character_service, mock_create_tables):
        """group create --json → 成功信封 + 参数透传."""
        mock_character_service.create_group.return_value = _make_group(name="主角团")
        result = cli_runner.invoke(
            group_app,
            ["create", "--project-id", str(PID), "--name", "主角团", "--description", "核心小队"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "主角团"
        mock_character_service.create_group.assert_awaited_once_with(
            project_id=PID, name="主角团", description="核心小队"
        )

    def test_group_list_json(self, cli_runner, mock_character_service, mock_create_tables):
        """group list --json → 分组列表信封."""
        mock_character_service.list_groups.return_value = [_make_group()]
        result = cli_runner.invoke(
            group_app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"][0]["name"] == "主角团"
        mock_character_service.list_groups.assert_awaited_once_with(project_id=PID)

    def test_group_get_json(self, cli_runner, mock_character_service, mock_create_tables):
        """group get --json → 成功信封."""
        mock_character_service.get_group.return_value = _make_group()
        result = cli_runner.invoke(
            group_app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "主角团"

    def test_group_update_json(self, cli_runner, mock_character_service, mock_create_tables):
        """group update --json → 成功信封 + 参数透传."""
        gid = uuid.uuid4()
        mock_character_service.update_group.return_value = _make_group(name="新主角团")
        result = cli_runner.invoke(
            group_app,
            ["update", "--id", str(gid), "--name", "新主角团"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "新主角团"
        mock_character_service.update_group.assert_awaited_once_with(
            group_id=gid, name="新主角团", description=None
        )

    def test_group_delete_force_json(self, cli_runner, mock_character_service, mock_create_tables):
        """group delete --force --json → 成功信封 + 软删除."""
        gid = uuid.uuid4()
        mock_character_service.delete_group.return_value = True
        result = cli_runner.invoke(
            group_app,
            ["delete", "--id", str(gid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        mock_character_service.delete_group.assert_awaited_once_with(group_id=gid, force=False)

    def test_group_delete_json_no_force(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """group delete --json 且无 --force → VALIDATION_ERROR."""
        result = cli_runner.invoke(
            group_app,
            ["delete", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"
