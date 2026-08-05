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
from pydantic import ValidationError
from typer.testing import CliRunner

from inkflow.cli.commands.character import app, group_app
from inkflow.cli.context import CliContext
from inkflow.domain.models.character import (
    Character,
    CharacterExtractionResult,
    CharacterGroup,
    CharacterRelation,
    CharacterUpdate,
)
from inkflow.domain.ports.character_errors import (
    CharacterNotFoundError,
)
from inkflow.domain.ports.llm_errors import LLMRequestError

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def mock_character_service():
    """Mock CharacterService，绕过数据库（ADR-015 依赖注入）."""
    with patch(
        "inkflow.cli.commands.character.CharacterService", autospec=True
    ) as mock_cls:
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


class TestCharacterErrorMapping:
    """_run 异常映射补全：LLMRequestError / ValidationError / 内部 UUID 解析 / DB_ERROR."""

    def test_create_llm_request_error(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """LLMRequestError → LLM_ERROR 信封 + 退出码 1."""
        mock_character_service.create_character.side_effect = LLMRequestError(
            "LLM 调用失败"
        )
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "林尘"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "LLM_ERROR"
        assert "LLM 调用失败" in data["error"]["message"]

    def test_create_validation_error(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """pydantic ValidationError → VALIDATION_ERROR 信封（拼接 msg）."""
        mock_character_service.create_character.side_effect = (
            ValidationError.from_exception_data(
                "Character",
                [
                    {
                        "type": "string_type",
                        "loc": ("name",),
                        "msg": "Input should be a valid string",
                        "input": 123,
                    }
                ],
            )
        )
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "林尘"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "Input should be a valid string" in data["error"]["message"]

    def test_create_not_found_error_raised(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """CharacterNotFoundError → NOT_FOUND 信封 + 退出码 1."""
        mock_character_service.create_character.side_effect = CharacterNotFoundError()
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "林尘"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_update_internal_uuid_parse_fail(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """_impl 内部 group_id UUID 解析失败 → 捕获 typer.Exit 并原样重抛
        （退出码 1 + NOT_FOUND）。"""
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--group-id", "not-a-uuid"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "分组不存在" in data["error"]["message"]
        mock_character_service.update_character.assert_not_awaited()

    def test_update_background_goals(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """update --background/--goals → 字段进入 CharacterUpdate."""
        cid = uuid.uuid4()
        mock_character_service.update_character.return_value = _make_character()
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                str(cid),
                "--background",
                "新背景",
                "--goals",
                "新目标",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_character_service.update_character.await_args
        upd: CharacterUpdate = call.kwargs["update"]
        assert upd.background == "新背景"
        assert upd.goals == "新目标"
        assert "name" not in upd.model_fields_set

    def test_update_human(self, cli_runner, mock_character_service, mock_create_tables):
        """update 人类模式 → 成功提示."""
        mock_character_service.update_character.return_value = _make_character(
            name="林尘"
        )
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--name", "林尘"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "角色已更新: [林尘]" in result.output

    def test_list_human_non_empty(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """list 人类模式非空 → 总数汇总 + 角色列表."""
        mock_character_service.list_characters.return_value = (
            [_make_character(name="林尘")],
            1,
        )
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "共 1 个角色" in result.output
        assert "林尘" in result.output

    def test_get_human(self, cli_runner, mock_character_service, mock_create_tables):
        """get 人类模式 → 全字段详情输出."""
        mock_character_service.get_character.return_value = _make_character(
            name="林尘", personality="坚毅", background="出身贫寒", goals="成为强者"
        )
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        for token in ("名称:", "林尘", "性格:", "坚毅", "背景:", "目标:", "分组:"):
            assert token in result.output

    def test_restore_human(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """restore 人类模式 → 成功提示."""
        mock_character_service.restore_character.return_value = _make_character(
            name="林尘"
        )
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "角色已恢复: [林尘]" in result.output

    def test_relate_human(self, cli_runner, mock_character_service, mock_create_tables):
        """relate 人类模式 → 关系创建提示."""
        mock_character_service.create_relation.return_value = _make_relation(
            relation_type="师徒"
        )
        result = cli_runner.invoke(
            app,
            [
                "relate",
                "--id",
                str(uuid.uuid4()),
                "--to",
                str(uuid.uuid4()),
                "--type",
                "师徒",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "关系已创建" in result.output
        assert "师徒" in result.output

    def test_unrelate_confirm_no(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """unrelate 无 --force 人类模式 → 回答 n 取消，不调用服务."""
        result = cli_runner.invoke(
            app,
            ["unrelate", "--id", str(uuid.uuid4()), "--relation-id", str(uuid.uuid4())],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已取消" in result.output
        mock_character_service.delete_relation.assert_not_awaited()

    def test_unrelate_human_yes(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """unrelate 无 --force 人类模式 → 回答 y 删除成功."""
        rid = uuid.uuid4()
        mock_character_service.delete_relation.return_value = True
        result = cli_runner.invoke(
            app,
            ["unrelate", "--id", str(uuid.uuid4()), "--relation-id", str(rid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert f"关系 #{rid} 已删除" in result.output

    def test_unrelate_not_found(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """unrelate 关系不存在（服务返回 False）→ NOT_FOUND 错误信封."""
        mock_character_service.delete_relation.return_value = False
        result = cli_runner.invoke(
            app,
            [
                "unrelate",
                "--id",
                str(uuid.uuid4()),
                "--relation-id",
                str(uuid.uuid4()),
                "--force",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_relations_human_empty(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """relations 人类模式空列表 → 暂无关系."""
        mock_character_service.list_relations.return_value = []
        result = cli_runner.invoke(
            app,
            ["relations", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无关系" in result.output

    def test_relations_human(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """relations 人类模式 → 逐条关系输出（含描述后缀）."""
        rel = _make_relation(relation_type="师徒", description="亦师亦友")
        mock_character_service.list_relations.return_value = [rel]
        result = cli_runner.invoke(
            app,
            ["relations", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert (
            f"[师徒] {rel.from_character_id} → {rel.to_character_id}" in result.output
        )
        assert "亦师亦友" in result.output

    def test_extract_text_file_missing(
        self, cli_runner, mock_character_service, mock_create_tables
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
        mock_character_service.extract.assert_not_awaited()

    def test_extract_db_error(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """服务抛未知异常 → DB_ERROR 信封 + 退出码 1."""
        mock_character_service.extract.side_effect = RuntimeError("boom")
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "林尘是主角。"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"
        assert "boom" in data["error"]["message"]

    def test_extract_human_no_warnings(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """extract 人类模式无警告 → 不输出警告提示行."""
        mock_character_service.extract.return_value = _make_extraction_result(
            warnings=[]
        )
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "林尘是主角。"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "提取完成" in result.output
        assert "但有警告" not in result.output

    def test_group_create_human(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """group create 人类模式 → 成功提示."""
        mock_character_service.create_group.return_value = _make_group(name="主角团")
        result = cli_runner.invoke(
            group_app,
            ["create", "--project-id", str(PID), "--name", "主角团"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "分组创建成功: [主角团]" in result.output

    def test_group_list_human_empty(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """group list 人类模式空列表 → 暂无分组."""
        mock_character_service.list_groups.return_value = []
        result = cli_runner.invoke(
            group_app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无分组" in result.output

    def test_group_get_not_found(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """group get 分组不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_character_service.get_group.return_value = None
        result = cli_runner.invoke(
            group_app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_group_get_human(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """group get 人类模式 → 全字段详情输出."""
        mock_character_service.get_group.return_value = _make_group(
            name="主角团", description="核心小队", sort_order=1
        )
        result = cli_runner.invoke(
            group_app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        for token in ("名称:", "主角团", "说明:", "核心小队", "排序:"):
            assert token in result.output

    def test_group_update_not_found(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """group update 分组不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_character_service.update_group.return_value = None
        result = cli_runner.invoke(
            group_app,
            ["update", "--id", str(uuid.uuid4()), "--name", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_group_update_human(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """group update 人类模式 → 成功提示."""
        mock_character_service.update_group.return_value = _make_group(name="新主角团")
        result = cli_runner.invoke(
            group_app,
            ["update", "--id", str(uuid.uuid4()), "--name", "新主角团"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "分组已更新: [新主角团]" in result.output

    def test_group_delete_confirm_no(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """group delete 无 --force 人类模式 → 回答 n 取消，不调用服务."""
        result = cli_runner.invoke(
            group_app,
            ["delete", "--id", str(uuid.uuid4())],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已取消" in result.output
        mock_character_service.delete_group.assert_not_awaited()

    def test_group_delete_human_yes(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """group delete 无 --force 人类模式 → 回答 y 删除成功."""
        gid = uuid.uuid4()
        mock_character_service.delete_group.return_value = True
        result = cli_runner.invoke(
            group_app,
            ["delete", "--id", str(gid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert f"分组 #{gid} 已删除" in result.output

    def test_group_delete_not_found(
        self, cli_runner, mock_character_service, mock_create_tables
    ):
        """group delete 分组不存在（服务返回 False）→ NOT_FOUND 错误信封."""
        mock_character_service.delete_group.return_value = False
        result = cli_runner.invoke(
            group_app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
