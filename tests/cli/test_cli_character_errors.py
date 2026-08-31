"""Character CLI 命令测试（错误映射/人类输出）— Mock ensure_kernel + InkFlowHTTPClient。

覆盖（依据 specs/f9-character/spec.md §4/§7/§9）:
- _run 异常映射：HttpApiError（404→NOT_FOUND、422→VALIDATION_ERROR、
  code=LLM_ERROR→LLM_ERROR）与 pydantic ValidationError → VALIDATION_ERROR、
  未知异常 → DB_ERROR
- 内部 UUID 解析失败 / 文本文件缺失 → 命令侧错误（不发 HTTP 调用）
- 各子命令人类可读输出

F38 改造（#169）：mock 目标从 domain Service（CharacterService + create_tables）
迁移到 ensure_kernel + InkFlowHTTPClient；返回值从领域对象改为 JSON dict；
create_tables/session 相关 patch 已移除；领域异常（CharacterNotFoundError /
LLMRequestError 等）改为 HttpApiError（lazy import，RED 阶段模块未实现）。

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
from pydantic import ValidationError
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


class TestCharacterErrorMapping:
    """_run 异常映射补全：HttpApiError（LLM/404/422）/ ValidationError / DB_ERROR."""

    def test_create_llm_request_error(self, cli_runner, fake_http_client):
        """LLM_ERROR 响应头 → LLM_ERROR 信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(
            500, "LLM 调用失败，请稍后重试", code="LLM_ERROR"
        )
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "林尘", "--role-rank", "major"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "LLM_ERROR"
        assert "LLM 调用失败" in data["error"]["message"]

    def test_create_validation_error(self, cli_runner, fake_http_client):
        """pydantic ValidationError → VALIDATION_ERROR 信封（拼接 msg）."""
        fake_http_client.post.side_effect = ValidationError.from_exception_data(
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
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "林尘", "--role-rank", "major"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "Input should be a valid string" in data["error"]["message"]

    def test_create_not_found_error_raised(self, cli_runner, fake_http_client):
        """HTTP 404 → NOT_FOUND 信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(404, "角色不存在")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "林尘", "--role-rank", "major"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_update_internal_uuid_parse_fail(self, cli_runner, fake_http_client):
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
        fake_http_client.patch.assert_not_awaited()

    def test_update_background_goals(self, cli_runner, fake_http_client):
        """update --background/--goals → HTTP 调用发生（字段组装在命令侧）."""
        cid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_character()
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
        fake_http_client.patch.assert_awaited()

    def test_update_human(self, cli_runner, fake_http_client):
        """update 人类模式 → 成功提示."""
        fake_http_client.patch.return_value = _make_character(name="林尘")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--name", "林尘"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "角色已更新: [林尘]" in result.output

    def test_list_human_non_empty(self, cli_runner, fake_http_client):
        """list 人类模式非空 → 总数汇总 + 角色列表."""
        fake_http_client.get.return_value = {
            "items": [_make_character(name="林尘")],
            "total": 1,
        }
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "共 1 个角色" in result.output
        assert "林尘" in result.output

    def test_get_human(self, cli_runner, fake_http_client):
        """get 人类模式 → 全字段详情输出."""
        fake_http_client.get.return_value = _make_character(
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

    def test_relate_human(self, cli_runner, fake_http_client):
        """relate 人类模式 → 关系创建提示."""
        fake_http_client.post.return_value = _make_relation(relation_type="师徒")
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

    def test_unrelate_confirm_no(self, cli_runner, fake_http_client):
        """unrelate 无 --force 人类模式 → 回答 n 取消，不调用服务."""
        result = cli_runner.invoke(
            app,
            ["unrelate", "--id", str(uuid.uuid4()), "--relation-id", str(uuid.uuid4())],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已取消" in result.output
        fake_http_client.delete.assert_not_awaited()

    def test_unrelate_human_yes(self, cli_runner, fake_http_client):
        """unrelate 无 --force 人类模式 → 回答 y 删除成功."""
        rid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["unrelate", "--id", str(uuid.uuid4()), "--relation-id", str(rid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert f"关系 #{rid} 已删除" in result.output

    def test_unrelate_not_found(self, cli_runner, fake_http_client):
        """unrelate 关系不存在（HTTP 404）→ NOT_FOUND 错误信封."""
        fake_http_client.delete.side_effect = _http_error(404, "关系不存在")
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

    def test_relations_human_empty(self, cli_runner, fake_http_client):
        """relations 人类模式空列表 → 暂无关系."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            app,
            ["relations", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无关系" in result.output

    def test_relations_human(self, cli_runner, fake_http_client):
        """relations 人类模式 → 逐条关系输出（含描述后缀）."""
        rel = _make_relation(relation_type="师徒", description="亦师亦友")
        fake_http_client.get.return_value = {"items": [rel], "total": 1}
        result = cli_runner.invoke(
            app,
            ["relations", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert (
            f"[师徒] {rel['from_character_id']} → {rel['to_character_id']}"
            in result.output
        )
        assert "亦师亦友" in result.output

    def test_extract_text_file_missing(self, cli_runner, fake_http_client):
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
        fake_http_client.post.assert_not_awaited()

    def test_extract_db_error(self, cli_runner, fake_http_client):
        """HTTP 调用抛未知异常 → DB_ERROR 信封 + 退出码 1."""
        fake_http_client.post.side_effect = RuntimeError("boom")
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

    def test_extract_human_no_warnings(self, cli_runner, fake_http_client):
        """extract 人类模式无警告 → 不输出警告提示行."""
        fake_http_client.post.return_value = _make_extraction_result(warnings=[])
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "林尘是主角。"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "提取完成" in result.output
        assert "但有警告" not in result.output

    def test_group_create_human(self, cli_runner, fake_http_client):
        """group create 人类模式 → 成功提示."""
        fake_http_client.post.return_value = _make_group(name="主角团")
        result = cli_runner.invoke(
            group_app,
            ["create", "--project-id", str(PID), "--name", "主角团"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "分组创建成功: [主角团]" in result.output

    def test_group_list_human_empty(self, cli_runner, fake_http_client):
        """group list 人类模式空列表 → 暂无分组."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            group_app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无分组" in result.output

    def test_group_get_not_found(self, cli_runner, fake_http_client):
        """group get 分组不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.get.side_effect = _http_error(404, "分组不存在")
        result = cli_runner.invoke(
            group_app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_group_get_human(self, cli_runner, fake_http_client):
        """group get 人类模式 → 全字段详情输出."""
        fake_http_client.get.return_value = _make_group(
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

    def test_group_update_not_found(self, cli_runner, fake_http_client):
        """group update 分组不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.patch.side_effect = _http_error(404, "分组不存在")
        result = cli_runner.invoke(
            group_app,
            ["update", "--id", str(uuid.uuid4()), "--name", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_group_update_human(self, cli_runner, fake_http_client):
        """group update 人类模式 → 成功提示."""
        fake_http_client.patch.return_value = _make_group(name="新主角团")
        result = cli_runner.invoke(
            group_app,
            ["update", "--id", str(uuid.uuid4()), "--name", "新主角团"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "分组已更新: [新主角团]" in result.output

    def test_group_delete_confirm_no(self, cli_runner, fake_http_client):
        """group delete 无 --force 人类模式 → 回答 n 取消，不调用服务."""
        result = cli_runner.invoke(
            group_app,
            ["delete", "--id", str(uuid.uuid4())],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已取消" in result.output
        fake_http_client.delete.assert_not_awaited()

    def test_group_delete_human_yes(self, cli_runner, fake_http_client):
        """group delete 无 --force 人类模式 → 回答 y 删除成功."""
        gid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            group_app,
            ["delete", "--id", str(gid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert f"分组 #{gid} 已删除" in result.output

    def test_group_delete_not_found(self, cli_runner, fake_http_client):
        """group delete 分组不存在（HTTP 404）→ NOT_FOUND 错误信封."""
        fake_http_client.delete.side_effect = _http_error(404, "分组不存在")
        result = cli_runner.invoke(
            group_app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
