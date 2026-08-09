"""Character CLI 命令测试（关系/提取/分组）— Mock ensure_kernel + InkFlowHTTPClient。

覆盖（依据 specs/f9-character-service/spec.md §4/§7/§9）:
- relate/unrelate/relations + extract + group 子组成功路径与参数透传
- 信封格式与退出码 0/1/2
- delete 二次确认 + --force；--json + delete 无 --force → VALIDATION_ERROR
- --text 与 --text-file 互斥 → 退出码 2
- extract 人类可读摘要与 --json 完整结果
- NOT_FOUND、LLM_ERROR、VALIDATION_ERROR 错误信封

F38 改造（#169）：mock 目标从 domain Service（CharacterService + create_tables）
迁移到 ensure_kernel + InkFlowHTTPClient；返回值从领域对象改为 JSON dict
（model_dump(mode="json") 等价物）；create_tables/session 相关 patch 已移除；
错误路径抛 HttpApiError（lazy import，RED 阶段模块未实现）。
relations 端点返回 {"items", "total"}，命令层提取 items 后保持原信封（list 输出）。
HTTP 错误码映射（命令侧，输出不变）：404→NOT_FOUND、422→VALIDATION_ERROR、
code=LLM_ERROR→LLM_ERROR。

── RED 形态说明 ────────────────────────────────────────────────
命令模块仍直连 domain Service（未改造），patch 目标
inkflow.cli.commands.character.ensure_kernel / .InkFlowHTTPClient 不存在
→ 全部用例 fixture setup AttributeError（同根因，预期 RED）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.character import app, group_app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP。

    fake client 提供 post/get/patch/delete 返回预设 JSON（dict）；
    错误路径抛 HttpApiError。patch 目标 = 命令模块命名空间（GREEN 后
    命令模块 from-import 绑定自身命名空间，F19 #77 先例）。
    """
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
            "inkflow.cli.commands.character.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.character.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_error(status_code: int, detail: str, code: str | None = None):
    """构造 HttpApiError（lazy import：RED 阶段 inkflow.infrastructure.http
    未实现，仅在用例体调用时执行，不影响 RED 形态）。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _make_character(**overrides) -> dict:
    """构造测试用 Character JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="林尘",
        personality="坚毅",
        background="出身贫寒",
        goals="成为强者",
        group_id=None,
        extra={},
        is_deleted=False,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_group(**overrides) -> dict:
    """构造测试用 CharacterGroup JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="主角团",
        description="核心小队",
        sort_order=0,
        is_deleted=False,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_relation(**overrides) -> dict:
    """构造测试用 CharacterRelation JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        from_character_id=str(uuid.uuid4()),
        to_character_id=str(uuid.uuid4()),
        relation_type="师徒",
        description="亦师亦友",
        is_deleted=False,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_extraction_result(**overrides) -> dict:
    """构造测试用 CharacterExtractionResult JSON dict."""
    defaults = dict(
        created=[_make_character()],
        updated=[],
        relations_created=[_make_relation()],
        relations_updated=[],
        warnings=['角色 "？？" 名称为空已跳过'],
        model="deepseek/deepseek-chat",
    )
    defaults.update(overrides)
    return defaults


class TestCharacterRelate:
    def test_relate_json(self, cli_runner, fake_http_client):
        """relate --json → 成功信封 + HTTP 调用（参数透传在命令侧）."""
        cid, to = uuid.uuid4(), uuid.uuid4()
        fake_http_client.post.return_value = _make_relation(relation_type="师徒")
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
        fake_http_client.post.assert_awaited()

    def test_relate_self_error(self, cli_runner, fake_http_client):
        """自环关系 → VALIDATION_ERROR 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(422, "不能与自己建立关系")
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
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"


class TestCharacterUnrelate:
    def test_unrelate_force_json(self, cli_runner, fake_http_client):
        """unrelate --force --json → 成功信封 + HTTP 调用."""
        cid, rid = uuid.uuid4(), uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["unrelate", "--id", str(cid), "--relation-id", str(rid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        fake_http_client.delete.assert_awaited()

    def test_unrelate_json_no_force(self, cli_runner, fake_http_client):
        """unrelate --json 且无 --force → VALIDATION_ERROR."""
        result = cli_runner.invoke(
            app,
            ["unrelate", "--id", str(uuid.uuid4()), "--relation-id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.delete.assert_not_awaited()


class TestCharacterRelations:
    def test_relations_json(self, cli_runner, fake_http_client):
        """relations --json → 双向关系列表信封."""
        cid = uuid.uuid4()
        fake_http_client.get.return_value = {
            "items": [_make_relation()],
            "total": 1,
        }
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
        fake_http_client.get.assert_awaited()


class TestCharacterExtract:
    def test_extract_json(self, cli_runner, fake_http_client):
        """extract --text --json → 完整结果信封（请求构造在命令侧）."""
        fake_http_client.post.return_value = _make_extraction_result()
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
        fake_http_client.post.assert_awaited()

    def test_extract_human_summary(self, cli_runner, fake_http_client):
        """extract 人类模式 → 可读摘要（新增/更新/关系/警告计数）."""
        fake_http_client.post.return_value = _make_extraction_result(
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

    def test_extract_text_file(self, cli_runner, fake_http_client, tmp_path):
        """extract --text-file → 读取文件内容作为提取文本."""
        text_file = tmp_path / "ch3.txt"
        text_file.write_text("林尘是主角，萧炎是他的师父。", encoding="utf-8")
        fake_http_client.post.return_value = _make_extraction_result()
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text-file", str(text_file)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.post.assert_awaited()

    def test_extract_text_and_text_file_exclusive(self, cli_runner, fake_http_client):
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
        fake_http_client.post.assert_not_awaited()

    def test_extract_llm_error(self, cli_runner, fake_http_client):
        """LLM 输出无法解析 → LLM_ERROR 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(
            500, "角色提取失败: LLM 输出无法解析，请重试", code="LLM_ERROR"
        )
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "林尘是主角。"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "LLM_ERROR"

    def test_extract_project_not_found(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(404, "项目不存在")
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
    def test_group_create_json(self, cli_runner, fake_http_client):
        """group create --json → 成功信封 + HTTP 调用."""
        fake_http_client.post.return_value = _make_group(name="主角团")
        result = cli_runner.invoke(
            group_app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "主角团",
                "--description",
                "核心小队",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "主角团"
        fake_http_client.post.assert_awaited()

    def test_group_list_json(self, cli_runner, fake_http_client):
        """group list --json → 分组列表信封."""
        fake_http_client.get.return_value = {
            "items": [_make_group()],
            "total": 1,
        }
        result = cli_runner.invoke(
            group_app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"][0]["name"] == "主角团"
        fake_http_client.get.assert_awaited()

    def test_group_get_json(self, cli_runner, fake_http_client):
        """group get --json → 成功信封."""
        fake_http_client.get.return_value = _make_group()
        result = cli_runner.invoke(
            group_app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "主角团"

    def test_group_update_json(self, cli_runner, fake_http_client):
        """group update --json → 成功信封 + HTTP 调用."""
        gid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_group(name="新主角团")
        result = cli_runner.invoke(
            group_app,
            ["update", "--id", str(gid), "--name", "新主角团"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "新主角团"
        fake_http_client.patch.assert_awaited()

    def test_group_delete_force_json(self, cli_runner, fake_http_client):
        """group delete --force --json → 成功信封 + 软删除."""
        gid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            group_app,
            ["delete", "--id", str(gid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        fake_http_client.delete.assert_awaited()

    def test_group_delete_json_no_force(self, cli_runner, fake_http_client):
        """group delete --json 且无 --force → VALIDATION_ERROR."""
        result = cli_runner.invoke(
            group_app,
            ["delete", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.delete.assert_not_awaited()
