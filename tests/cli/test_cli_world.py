"""World CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（HTTP JSON 响应）。

覆盖（依据 specs/f10-world-service/spec.md §4/§4.2）:
- 各子命令成功路径与参数透传（create/list/categories/get/update/delete/restore/extract）
- 信封格式与退出码 0/1/2
- delete 二次确认 + --force；--json + delete 无 --force → VALIDATION_ERROR
- --text 与 --text-file 互斥 → 退出码 2
- extract 人类可读摘要与 --json 完整结果
- NOT_FOUND、LLM_ERROR、VALIDATION_ERROR 错误信封

F38 改造（#169）：mock 目标从 domain Service（WorldService + create_tables）
迁移到 ensure_kernel + InkFlowHTTPClient；返回值从 WorldSetting 等领域对象
改为 JSON dict（model_dump(mode="json") 等价物）；create_tables/session 相关
patch 已移除；错误路径抛 HttpApiError（lazy import，RED 阶段模块未实现）。
list/categories 端点返回 {"items", "total"}，命令层提取 items 后保持原信封。
HTTP 错误码映射（命令侧，输出不变）：404→NOT_FOUND、422→VALIDATION_ERROR、
code=LLM_ERROR→LLM_ERROR。

── RED 形态说明 ────────────────────────────────────────────────
命令模块仍直连 domain Service（未改造），patch 目标
inkflow.cli.commands.world.ensure_kernel / .InkFlowHTTPClient 不存在
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

from inkflow.cli.commands.world import app
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
            "inkflow.cli.commands.world.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.world.InkFlowHTTPClient", autospec=True
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


def _make_setting(**overrides) -> dict:
    """构造测试用 WorldSetting JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="灵气复苏",
        category="设定",
        content="天地灵气重新复苏，修炼体系重现。",
        extra={},
        is_deleted=False,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_extraction_result(**overrides) -> dict:
    """构造测试用 WorldExtractionResult JSON dict."""
    defaults = dict(
        created=[_make_setting()],
        updated=[],
        warnings=['条目 "？？" 名称为空已跳过'],
        model="deepseek/deepseek-chat",
    )
    defaults.update(overrides)
    return defaults


class TestWorldCreate:
    def test_create_json_envelope(self, cli_runner, fake_http_client):
        """create --json → 成功信封 + HTTP 调用（UUID 转换在命令侧）."""
        fake_http_client.post.return_value = _make_setting(name="灵气复苏")
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
        fake_http_client.post.assert_awaited()

    def test_create_human(self, cli_runner, fake_http_client):
        """create 人类模式 → 成功提示（含类别）."""
        fake_http_client.post.return_value = _make_setting(name="灵气复苏")
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

    def test_create_name_conflict(self, cli_runner, fake_http_client):
        """同名条目 → VALIDATION_ERROR 信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(422, "同名条目")
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
    def test_list_json(self, cli_runner, fake_http_client):
        """list --json → 成功信封 + 条目数组."""
        fake_http_client.get.return_value = {
            "items": [_make_setting()],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
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

    def test_list_human_empty(self, cli_runner, fake_http_client):
        """空列表人类模式 → 暂无条目."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无条目" in result.output

    def test_list_params_passthrough(self, cli_runner, fake_http_client):
        """list 搜索/类别/排序/分页参数 → HTTP 调用发生（参数透传在命令侧）."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
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
        fake_http_client.get.assert_awaited()


class TestWorldCategories:
    def test_categories_json(self, cli_runner, fake_http_client):
        """categories --json → 类别计数列表信封."""
        fake_http_client.get.return_value = {
            "items": [
                {"category": "设定", "count": 3},
                {"category": "地理", "count": 1},
            ],
            "total": 2,
        }
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
        fake_http_client.get.assert_awaited()

    def test_categories_human_empty(self, cli_runner, fake_http_client):
        """空类别人类模式 → 暂无类别."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            app,
            ["categories", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无类别" in result.output


class TestWorldGet:
    def test_get_json(self, cli_runner, fake_http_client):
        """条目存在 → 成功信封."""
        sid = uuid.uuid4()
        fake_http_client.get.return_value = _make_setting(name="灵气复苏")
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(sid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "灵气复苏"
        fake_http_client.get.assert_awaited()

    def test_get_not_found_json(self, cli_runner, fake_http_client):
        """条目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.get.side_effect = _http_error(404, "世界观条目不存在")
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

    def test_get_invalid_uuid(self, cli_runner, fake_http_client):
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
    def test_update_json(self, cli_runner, fake_http_client):
        """update --json → 成功信封（仅传入字段进入 update，命令侧）."""
        sid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_setting(name="灵气复苏·改")
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
        fake_http_client.patch.assert_awaited()

    def test_update_clear_category(self, cli_runner, fake_http_client):
        """update --category \"\" → 显式清除类别（HTTP 调用发生）."""
        sid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_setting()
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(sid), "--category", ""],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.patch.assert_awaited()

    def test_update_not_found(self, cli_runner, fake_http_client):
        """条目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.patch.side_effect = _http_error(404, "世界观条目不存在")
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
    def test_delete_force_json(self, cli_runner, fake_http_client):
        """delete --force --json → 成功信封 + 软删除（force=False）."""
        sid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        fake_http_client.delete.assert_awaited()

    def test_delete_permanent_passes_force(self, cli_runner, fake_http_client):
        """delete --permanent → HTTP 调用发生（force=True 透传在命令侧）."""
        sid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid), "--force", "--permanent"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.delete.assert_awaited()

    def test_delete_confirm_yes(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除."""
        sid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output
        fake_http_client.delete.assert_awaited()

    def test_delete_confirm_no(self, cli_runner, fake_http_client):
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
        fake_http_client.delete.assert_not_awaited()

    def test_delete_json_no_force(self, cli_runner, fake_http_client):
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
        fake_http_client.delete.assert_not_awaited()

    def test_delete_not_found(self, cli_runner, fake_http_client):
        """条目不存在（HTTP 404）→ NOT_FOUND 错误信封."""
        fake_http_client.delete.side_effect = _http_error(404, "世界观条目不存在")
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
    def test_restore_json(self, cli_runner, fake_http_client):
        """restore --json → 成功信封."""
        fake_http_client.post.return_value = _make_setting(name="灵气复苏")
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "灵气复苏"

    def test_restore_not_found(self, cli_runner, fake_http_client):
        """条目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(404, "世界观条目不存在")
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
        fake_http_client.post.assert_awaited()

    def test_extract_human_summary(self, cli_runner, fake_http_client):
        """extract 人类模式 → 可读摘要（新增/更新/警告计数）."""
        fake_http_client.post.return_value = _make_extraction_result(
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

    def test_extract_text_file(self, cli_runner, fake_http_client, tmp_path):
        """extract --text-file → 读取文件内容作为提取文本."""
        text_file = tmp_path / "ch3.txt"
        text_file.write_text("灵气复苏后，大陆进入修炼时代。", encoding="utf-8")
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
            500, "世界观提取失败: LLM 输出无法解析，请重试", code="LLM_ERROR"
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

    def test_extract_project_not_found(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(404, "项目不存在")
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
    """_run 异常映射补全：HttpApiError（LLM/422）/ ValidationError / 文件缺失 / DB_ERROR."""

    def test_extract_llm_request_error(self, cli_runner, fake_http_client):
        """LLM_ERROR 响应头 → LLM_ERROR 信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(
            500, "LLM 调用失败，请稍后重试", code="LLM_ERROR"
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
        assert "LLM 调用失败" in data["error"]["message"]

    def test_extract_validation_error(self, cli_runner, fake_http_client):
        """pydantic ValidationError → VALIDATION_ERROR 信封."""
        fake_http_client.post.side_effect = ValidationError.from_exception_data(
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

    def test_extract_service_error(self, cli_runner, fake_http_client):
        """HTTP 422 → VALIDATION_ERROR 信封（detail 透传为 message）."""
        fake_http_client.post.side_effect = _http_error(422, "同名条目")
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

    def test_create_human_no_category(self, cli_runner, fake_http_client):
        """create 人类模式无类别 → 提示不含类别括号."""
        fake_http_client.post.return_value = _make_setting(category="")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "灵气复苏"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "世界观条目创建成功: [灵气复苏]" in result.output

    def test_list_human_non_empty(self, cli_runner, fake_http_client):
        """list 人类模式非空 → 总数汇总 + 条目列表."""
        fake_http_client.get.return_value = {
            "items": [_make_setting(name="灵气复苏")],
            "total": 1,
        }
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "共 1 个条目" in result.output
        assert "灵气复苏" in result.output

    def test_categories_human(self, cli_runner, fake_http_client):
        """categories 人类模式 → 逐类别输出（含条目数）."""
        fake_http_client.get.return_value = {
            "items": [
                {"category": "设定", "count": 3},
                {"category": "地理", "count": 1},
            ],
            "total": 2,
        }
        result = cli_runner.invoke(
            app,
            ["categories", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "设定: 3 条" in result.output
        assert "地理: 1 条" in result.output

    def test_get_human(self, cli_runner, fake_http_client):
        """get 人类模式 → 全字段详情输出."""
        fake_http_client.get.return_value = _make_setting(
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

    def test_update_human(self, cli_runner, fake_http_client):
        """update 人类模式 → 成功提示."""
        fake_http_client.patch.return_value = _make_setting(name="灵气复苏·改")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--name", "灵气复苏·改"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "条目已更新: [灵气复苏·改]" in result.output

    def test_restore_human(self, cli_runner, fake_http_client):
        """restore 人类模式 → 成功提示."""
        fake_http_client.post.return_value = _make_setting(name="灵气复苏")
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "条目已恢复: [灵气复苏]" in result.output

    def test_extract_human_no_warnings(self, cli_runner, fake_http_client):
        """extract 人类模式无警告 → 不输出警告提示行."""
        fake_http_client.post.return_value = _make_extraction_result(warnings=[])
        result = cli_runner.invoke(
            app,
            ["extract", "--project-id", str(PID), "--text", "灵气复苏。"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "提取完成" in result.output
        assert "但有警告" not in result.output
