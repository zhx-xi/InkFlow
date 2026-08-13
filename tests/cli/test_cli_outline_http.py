"""Outline CLI 命令测试（generate/错误映射/人类输出）— Mock ensure_kernel + InkFlowHTTPClient。

F38 改造（#169）：mock 目标从 domain Service（OutlineService + create_tables）
迁移到 ensure_kernel + InkFlowHTTPClient；返回值从领域对象改为 JSON dict
（model_dump(mode="json") 等价物）；create_tables/session 相关 patch 已移除；
错误路径抛 HttpApiError（lazy import，RED 阶段模块未实现）。
HTTP 错误码映射（命令侧，输出不变）：404→NOT_FOUND、422→VALIDATION_ERROR、
code=LLM_ERROR→LLM_ERROR、未知异常→DB_ERROR。

── 拆分说明 ────────────────────────────────────────────────────
原 test_cli_outline.py 1408 行超 CI check_file_length（< 900）护栏，F38 改造
时拆分为二：本文件承载 generate / 错误映射 / 人类输出用例（复制所需 imports
与 helpers）；test_cli_outline.py 保留 outline/point/arc CRUD 用例。

── RED 形态说明 ────────────────────────────────────────────────
命令模块仍直连 domain Service（未改造），patch 目标
inkflow.cli.commands.outline.ensure_kernel / .InkFlowHTTPClient 不存在
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

from inkflow.cli.commands.outline import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
AID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000003")


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
            "inkflow.cli.commands.outline.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.outline.InkFlowHTTPClient", autospec=True
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


def _make_outline(**overrides) -> dict:
    """构造测试用 Outline JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="第一卷大纲",
        description="故事主线概述",
        sort_order=0,
        extra={},
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_point(**overrides) -> dict:
    """构造测试用 PlotPoint JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        outline_id=str(OID),
        project_id=str(PID),
        name="主角登场",
        type="开篇",
        description="主角在宗门大比中亮相。",
        position=1,
        arc_id=None,
        extra={},
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_arc(**overrides) -> dict:
    """构造测试用 StoryArc JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="主角成长线",
        description="主角从废柴到巅峰的成长轨迹。",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_generation_result(**overrides) -> dict:
    """构造测试用 OutlineGenerationResult JSON dict."""
    defaults = dict(
        saved=True,
        outline=_make_outline(name="第一卷大纲"),
        plot_points=[_make_point(name="主角登场", type="开篇")],
        arcs=[_make_arc(name="主角成长线")],
        preview=None,
        warnings=[],
        model="deepseek/deepseek-chat",
    )
    defaults.update(overrides)
    return defaults


def _make_preview(**overrides) -> dict:
    """构造测试用 GeneratedOutline JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        name="第一卷大纲",
        description="",
        arcs=[{"name": "主角成长线", "description": ""}],
        plot_points=[
            {
                "name": "主角登场",
                "type": "开篇",
                "description": "",
                "arc": "主角成长线",
            }
        ],
    )
    defaults.update(overrides)
    return defaults


class TestGenerate:
    def test_generate_save_json(self, cli_runner, fake_http_client):
        """generate --json → 完整结果信封（请求构造在命令侧）."""
        fake_http_client.post.return_value = _make_generation_result(
            plot_points=[
                _make_point(name="主角登场", type="开篇"),
                _make_point(name="转折", type="转折"),
            ],
            arcs=[_make_arc(name="主角成长线"), _make_arc(name="反派阴谋线")],
        )
        result = cli_runner.invoke(
            app,
            [
                "generate",
                "--project-id",
                str(PID),
                "--name",
                "第一卷大纲",
                "--prompt",
                "爽文, 废柴逆袭",
                "--num-chapters",
                "12",
                "--model",
                "deepseek/deepseek-chat",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["saved"] is True
        assert data["data"]["outline"]["name"] == "第一卷大纲"
        assert len(data["data"]["plot_points"]) == 2
        assert data["data"]["plot_points"][0]["name"] == "主角登场"
        assert data["data"]["arcs"][1]["name"] == "反派阴谋线"
        assert data["data"]["model"] == "deepseek/deepseek-chat"
        fake_http_client.post.assert_awaited()

    def test_generate_no_save_json(self, cli_runner, fake_http_client):
        """generate --no-save --json → 预览结果信封（saved=False + preview）."""
        fake_http_client.post.return_value = _make_generation_result(
            saved=False,
            outline=None,
            plot_points=[],
            arcs=[],
            preview=_make_preview(),
        )
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--no-save", "--prompt", "爽文"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["saved"] is False
        assert data["data"]["outline"] is None
        assert data["data"]["preview"]["plot_points"][0]["name"] == "主角登场"
        fake_http_client.post.assert_awaited()

    def test_generate_human_summary_saved(self, cli_runner, fake_http_client):
        """generate 人类模式（保存）→ 可读摘要（含情节点/弧线计数与警告）."""
        fake_http_client.post.return_value = _make_generation_result(
            plot_points=[
                _make_point(name="主角登场"),
                _make_point(name="转折"),
                _make_point(name="高潮"),
            ],
            arcs=[_make_arc(name="主角成长线"), _make_arc(name="反派阴谋线")],
            warnings=['情节点 "？？" 名称为空已跳过'],
        )
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt", "爽文"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "大纲生成并保存" in result.output
        assert "第一卷大纲" in result.output
        assert "3 个情节点、2 条弧线" in result.output
        assert "生成完成但有警告" in result.output

    def test_generate_human_summary_preview(self, cli_runner, fake_http_client):
        """generate 人类模式（--no-save）→ 预览摘要提示."""
        fake_http_client.post.return_value = _make_generation_result(
            saved=False,
            outline=None,
            plot_points=[],
            arcs=[],
            preview=_make_preview(),
        )
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--no-save", "--prompt", "爽文"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "大纲预览（未保存）" in result.output
        assert "1 个情节点、1 条弧线" in result.output
        assert "使用 --save 保存后落库" in result.output

    def test_generate_prompt_file(self, cli_runner, fake_http_client, tmp_path):
        """generate --prompt-file → 读取文件内容作为生成提示."""
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("废柴逆袭，宗门大比。", encoding="utf-8")
        fake_http_client.post.return_value = _make_generation_result()
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt-file", str(prompt_file)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.post.assert_awaited()

    def test_generate_prompt_and_prompt_file_exclusive(
        self, cli_runner, fake_http_client
    ):
        """--prompt 与 --prompt-file 同时传入 → 用法错误退出码 2."""
        result = cli_runner.invoke(
            app,
            [
                "generate",
                "--project-id",
                str(PID),
                "--prompt",
                "爽文",
                "--prompt-file",
                "p.txt",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()

    def test_generate_llm_error(self, cli_runner, fake_http_client):
        """LLM 输出无法解析 → LLM_ERROR 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(
            500, "大纲生成失败: LLM 输出无法解析，请重试", code="LLM_ERROR"
        )
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt", "爽文"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "LLM_ERROR"

    def test_generate_project_not_found(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(404, "项目不存在")
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt", "爽文"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestOutlineErrorMapping:
    """_run 异常映射补全：HttpApiError（LLM/404/422）/ ValidationError / DB_ERROR."""

    def test_generate_llm_request_error(self, cli_runner, fake_http_client):
        """LLM_ERROR 响应头 → LLM_ERROR 信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(
            500, "LLM 调用失败，请稍后重试", code="LLM_ERROR"
        )
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt", "爽文"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "LLM_ERROR"
        assert "LLM 调用失败" in data["error"]["message"]

    def test_generate_validation_error(self, cli_runner, fake_http_client):
        """pydantic ValidationError → VALIDATION_ERROR 信封."""
        fake_http_client.post.side_effect = ValidationError.from_exception_data(
            "OutlineGenerateRequest",
            [
                {
                    "type": "string_type",
                    "loc": ("prompt",),
                    "msg": "Input should be a valid string",
                    "input": 123,
                }
            ],
        )
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt", "爽文"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "Input should be a valid string" in data["error"]["message"]

    def test_generate_prompt_file_missing(self, cli_runner, fake_http_client):
        """generate --prompt-file 指向不存在文件 → VALIDATION_ERROR（文本文件不存在）."""
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt-file", "no_such.txt"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "文本文件不存在" in data["error"]["message"]
        fake_http_client.post.assert_not_awaited()

    def test_generate_db_error(self, cli_runner, fake_http_client):
        """HTTP 调用抛未知异常 → DB_ERROR 信封 + 退出码 1."""
        fake_http_client.post.side_effect = RuntimeError("boom")
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt", "爽文"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"
        assert "boom" in data["error"]["message"]

    def test_point_update_internal_arc_id_parse_fail(
        self, cli_runner, fake_http_client
    ):
        """_impl 内部 arc_id UUID 解析失败 → typer.Exit 原样重抛（退出码 1 + NOT_FOUND）."""
        result = cli_runner.invoke(
            app,
            ["point", "update", "--id", str(uuid.uuid4()), "--arc-id", "not-a-uuid"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "弧线不存在" in data["error"]["message"]
        fake_http_client.patch.assert_not_awaited()


class TestOutlineHumanOutput:
    """人类可读输出补全：list 非空 / get / update / point / arc / delete 确认."""

    def test_list_human_non_empty(self, cli_runner, fake_http_client):
        """list 人类模式非空 → 总数汇总 + 大纲列表."""
        fake_http_client.get.return_value = {
            "items": [_make_outline(name="第一卷大纲")],
            "total": 1,
        }
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "共 1 个大纲" in result.output
        assert "第一卷大纲" in result.output

    def test_get_human(self, cli_runner, fake_http_client):
        """get 人类模式 → 全字段详情输出."""
        fake_http_client.get.return_value = _make_outline(
            name="第一卷大纲", description="故事主线概述", sort_order=2
        )
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        for token in ("ID:", "名称:", "第一卷大纲", "描述:", "故事主线概述", "排序:"):
            assert token in result.output

    def test_update_only_description(self, cli_runner, fake_http_client):
        """update 仅传 --description → HTTP 调用发生（description 进入 update，命令侧）."""
        oid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_outline()
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(oid), "--description", "新描述"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.patch.assert_awaited()

    def test_update_human(self, cli_runner, fake_http_client):
        """update 人类模式 → 成功提示."""
        fake_http_client.patch.return_value = _make_outline(name="第一卷大纲·改")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--name", "第一卷大纲·改"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "大纲已更新: [第一卷大纲·改]" in result.output

    def test_point_list_human_empty(self, cli_runner, fake_http_client):
        """point list 人类模式空列表 → 暂无情节点."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            app,
            ["point", "list", "--outline-id", str(OID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无情节点" in result.output

    def test_point_update_description(self, cli_runner, fake_http_client):
        """point update --description → HTTP 调用发生（description 进入 update，命令侧）."""
        pid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_point()
        result = cli_runner.invoke(
            app,
            ["point", "update", "--id", str(pid), "--description", "新要点"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.patch.assert_awaited()

    def test_point_update_not_found(self, cli_runner, fake_http_client):
        """point update 情节点不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.patch.side_effect = _http_error(404, "情节点不存在")
        result = cli_runner.invoke(
            app,
            ["point", "update", "--id", str(uuid.uuid4()), "--name", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_point_update_human(self, cli_runner, fake_http_client):
        """point update 人类模式 → 成功提示."""
        fake_http_client.patch.return_value = _make_point(name="主角登场·改")
        result = cli_runner.invoke(
            app,
            ["point", "update", "--id", str(uuid.uuid4()), "--name", "主角登场·改"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "情节点已更新: [主角登场·改]" in result.output

    def test_point_delete_confirm_no(self, cli_runner, fake_http_client):
        """point delete 无 --force 人类模式 → 回答 n 取消，不调用服务."""
        result = cli_runner.invoke(
            app,
            ["point", "delete", "--id", str(uuid.uuid4())],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已取消" in result.output
        fake_http_client.delete.assert_not_awaited()

    def test_point_delete_human_yes(self, cli_runner, fake_http_client):
        """point delete 无 --force 人类模式 → 回答 y 删除成功."""
        pid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["point", "delete", "--id", str(pid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert f"情节点 #{pid} 已删除" in result.output

    def test_point_delete_not_found(self, cli_runner, fake_http_client):
        """point delete 情节点不存在（HTTP 404）→ NOT_FOUND 错误信封."""
        fake_http_client.delete.side_effect = _http_error(404, "情节点不存在")
        result = cli_runner.invoke(
            app,
            ["point", "delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_arc_list_human_empty(self, cli_runner, fake_http_client):
        """arc list 人类模式空列表 → 暂无弧线."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            app,
            ["arc", "list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无弧线" in result.output

    def test_arc_create_human(self, cli_runner, fake_http_client):
        """arc create 人类模式 → 成功提示."""
        fake_http_client.post.return_value = _make_arc(name="主角成长线")
        result = cli_runner.invoke(
            app,
            ["arc", "create", "--project-id", str(PID), "--name", "主角成长线"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "弧线创建成功: [主角成长线]" in result.output

    def test_arc_update_only_description(self, cli_runner, fake_http_client):
        """arc update 仅传 --description → HTTP 调用发生（description 进入 update，命令侧）."""
        aid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_arc()
        result = cli_runner.invoke(
            app,
            ["arc", "update", "--id", str(aid), "--description", "新说明"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.patch.assert_awaited()

    def test_arc_update_not_found(self, cli_runner, fake_http_client):
        """arc update 弧线不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.patch.side_effect = _http_error(404, "弧线不存在")
        result = cli_runner.invoke(
            app,
            ["arc", "update", "--id", str(uuid.uuid4()), "--name", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_arc_update_human(self, cli_runner, fake_http_client):
        """arc update 人类模式 → 成功提示."""
        fake_http_client.patch.return_value = _make_arc(name="主角成长线·改")
        result = cli_runner.invoke(
            app,
            ["arc", "update", "--id", str(uuid.uuid4()), "--name", "主角成长线·改"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "弧线已更新: [主角成长线·改]" in result.output

    def test_arc_delete_confirm_no(self, cli_runner, fake_http_client):
        """arc delete 无 --force 人类模式 → 回答 n 取消，不调用服务."""
        result = cli_runner.invoke(
            app,
            ["arc", "delete", "--id", str(uuid.uuid4())],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已取消" in result.output
        fake_http_client.delete.assert_not_awaited()

    def test_arc_delete_human_yes(self, cli_runner, fake_http_client):
        """arc delete 无 --force 人类模式 → 回答 y 删除成功."""
        aid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["arc", "delete", "--id", str(aid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert f"弧线 #{aid} 已删除" in result.output

    def test_arc_delete_not_found(self, cli_runner, fake_http_client):
        """arc delete 弧线不存在（HTTP 404）→ NOT_FOUND 错误信封."""
        fake_http_client.delete.side_effect = _http_error(404, "弧线不存在")
        result = cli_runner.invoke(
            app,
            ["arc", "delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
