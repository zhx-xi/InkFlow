"""Chapter/Volume CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（HTTP JSON 响应）。

F38 改造（#169）：mock 目标从 domain Service（ChapterService + create_tables）
迁移到 ensure_kernel + InkFlowHTTPClient；返回值从 Chapter/Volume 领域对象
改为 JSON dict（model_dump(mode="json") 等价物）；create_tables/session 相关
patch 已移除；错误路径抛 HttpApiError（lazy import，RED 阶段模块未实现）。
list 端点返回 {"items", "total"}，命令层提取 items 后保持原信封
{"total", "chapters"}（输出不变）。

── RED 形态说明 ────────────────────────────────────────────────
命令模块仍直连 domain Service（未改造），patch 目标
inkflow.cli.commands.chapter.ensure_kernel / .InkFlowHTTPClient 不存在
→ 全部用例 fixture setup AttributeError（同根因，预期 RED）。

── #231 追加段（CLI chapter list 422 修复契约）─────────────────
根因（0.6.0 验证实测 + httpx 行为验证）：list_ch 显式构造 params
{"volume_id": None, "status": None}，httpx 将 value=None 的查询参数
编码为空字符串（httpx.URL params 编码实测 b'volume_id=&status='）→
API Query 收到 status='' → Pydantic ChapterStatus 枚举校验 422
「Input should be 'draft', 'writing', 'review' or 'final', input: ''」。
契约（修复方向 A：CLI 层构造 params 时过滤 None，不放松 API 层校验）：
- 不传 --status/--volume-id → params 不含 status/volume_id 键
  （RED 阶段 FAIL：当前 params 含两键且值为 None）
- 传 --status draft → params["status"] == "draft"（守护，RED 阶段即 PASS）
RED 预期：1 failed，其余既有用例全部 passed（新增用例失败点为
断言 FAIL，非 ERROR）。
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.chapter import chapter_app, volume_app
from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner():
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
            "inkflow.cli.commands.chapter.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.chapter.InkFlowHTTPClient", autospec=True
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


def _make_chapter(**overrides) -> dict:
    """构造测试用 Chapter JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        title="测试章",
        content="",
        status="draft",
        word_count=0,
        volume_id=None,
        order_index=1.0,
    )
    defaults.update(overrides)
    return defaults


def _make_volume(**overrides) -> dict:
    """构造测试用 Volume JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        title="第一卷",
        order_index=1.0,
    )
    defaults.update(overrides)
    return defaults


class TestChapterCreate:
    def test_create_json(self, cli_runner, fake_http_client):
        """create --json 输出 JSON 信封."""
        fake_http_client.post.return_value = _make_chapter()
        result = cli_runner.invoke(
            chapter_app,
            ["create", "--project-id", str(uuid.uuid4()), "--title", "测试章"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["title"] == "测试章"

    def test_create_human(self, cli_runner, fake_http_client):
        """create 人类可读模式正常退出."""
        fake_http_client.post.return_value = _make_chapter()
        result = cli_runner.invoke(
            chapter_app,
            ["create", "--project-id", str(uuid.uuid4()), "--title", "测试章"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0


class TestChapterGet:
    def test_get_not_found(self, cli_runner, fake_http_client):
        """章节不存在时输出错误信封并退出码 1."""
        fake_http_client.get.side_effect = _http_error(404, "章节不存在")
        result = cli_runner.invoke(
            chapter_app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"

    def test_get_found_json(self, cli_runner, fake_http_client):
        """章节存在时输出成功信封."""
        fake_http_client.get.return_value = _make_chapter()
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
    def test_create_volume_json(self, cli_runner, fake_http_client):
        """volume create --json 输出 JSON 信封."""
        fake_http_client.post.return_value = _make_volume()
        result = cli_runner.invoke(
            volume_app,
            ["create", "--project-id", str(uuid.uuid4()), "--title", "第一卷"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["title"] == "第一卷"

    def test_create_volume_human(self, cli_runner, fake_http_client):
        """volume create 人类模式 → 成功提示（含卷标题）."""
        fake_http_client.post.return_value = _make_volume()
        result = cli_runner.invoke(
            volume_app,
            ["create", "--project-id", str(uuid.uuid4()), "--title", "第一卷"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "卷创建成功: [第一卷]" in result.output


class TestChapterDelete:
    def test_delete_force(self, cli_runner, fake_http_client):
        """delete --force 跳过确认并成功删除."""
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            chapter_app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["deleted"] is True

    def test_delete_confirm_no(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 回答 n 取消，不调用服务."""
        cid = uuid.uuid4()
        result = cli_runner.invoke(
            chapter_app,
            ["delete", "--id", str(cid)],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        fake_http_client.delete.assert_not_awaited()

    def test_delete_not_found(self, cli_runner, fake_http_client):
        """章节不存在（HTTP 404）→ NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.delete.side_effect = _http_error(404, "章节不存在")
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
    def test_list_json(self, cli_runner, fake_http_client):
        """volume list --json → 成功信封 + 卷数组."""
        fake_http_client.get.return_value = {"items": [_make_volume()], "total": 1}
        result = cli_runner.invoke(
            volume_app,
            ["list", "--project-id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"][0]["title"] == "第一卷"

    def test_list_human(self, cli_runner, fake_http_client):
        """volume list 人类模式 → 逐卷输出."""
        fake_http_client.get.return_value = {"items": [_make_volume()], "total": 1}
        result = cli_runner.invoke(
            volume_app,
            ["list", "--project-id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "第一卷" in result.output


class TestVolumeDelete:
    def test_delete_force_json(self, cli_runner, fake_http_client):
        """volume delete --force --json → 成功信封 + HTTP 调用."""
        vid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            volume_app,
            ["delete", "--id", str(vid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["deleted"] is True
        fake_http_client.delete.assert_awaited()

    def test_delete_confirm_yes(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除."""
        vid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            volume_app,
            ["delete", "--id", str(vid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        fake_http_client.delete.assert_awaited()

    def test_delete_confirm_no(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 回答 n 取消，不调用服务."""
        vid = uuid.uuid4()
        result = cli_runner.invoke(
            volume_app,
            ["delete", "--id", str(vid)],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        fake_http_client.delete.assert_not_awaited()

    def test_delete_not_found(self, cli_runner, fake_http_client):
        """卷不存在（HTTP 404）→ NOT_FOUND 错误信封."""
        fake_http_client.delete.side_effect = _http_error(404, "卷不存在")
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
    def test_list_json_with_filters(self, cli_runner, fake_http_client):
        """chapter list --json → 信封 + volume_id/status 过滤参数（枚举转 .value）."""
        pid, vid = uuid.uuid4(), uuid.uuid4()
        fake_http_client.get.return_value = {
            "items": [_make_chapter()],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
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
        fake_http_client.get.assert_awaited()

    def test_list_human_empty(self, cli_runner, fake_http_client):
        """chapter list 人类模式空列表 → total 汇总输出."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            chapter_app,
            ["list", "--project-id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "total" in result.output

    def test_list_no_filters_sends_no_none_params(self, cli_runner, fake_http_client):
        """#231：不传 --status/--volume-id → params 不含 status/volume_id 键.

        httpx 将 value=None 的查询参数编码为空字符串（status=），API 枚举
        校验收到空串报 422 —— 契约：None 值不得进入 params。
        """
        pid = uuid.uuid4()
        fake_http_client.get.return_value = {
            "items": [_make_chapter()],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            chapter_app,
            ["list", "--project-id", str(pid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["total"] == 1
        params = fake_http_client.get.await_args.kwargs.get("params") or {}
        assert "status" not in params
        assert "volume_id" not in params

    def test_list_with_status_still_sends_status(self, cli_runner, fake_http_client):
        """#231 守护：传 --status draft → params 含 status=draft（不回归）."""
        pid = uuid.uuid4()
        fake_http_client.get.return_value = {
            "items": [_make_chapter(status="draft")],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            chapter_app,
            ["list", "--project-id", str(pid), "--status", "draft"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        params = fake_http_client.get.await_args.kwargs.get("params") or {}
        assert params.get("status") == "draft"


class TestChapterUpdate:
    def test_update_json(self, cli_runner, fake_http_client):
        """chapter update --json → 成功信封（status 转换在命令侧）."""
        cid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_chapter()
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
        fake_http_client.patch.assert_awaited()

    def test_update_not_found(self, cli_runner, fake_http_client):
        """章节不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.patch.side_effect = _http_error(404, "章节不存在")
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
    def test_move_json(self, cli_runner, fake_http_client):
        """chapter move --json → 成功信封（POST /chapters/{id}/move）."""
        cid, vid = uuid.uuid4(), uuid.uuid4()
        fake_http_client.post.return_value = _make_chapter()
        result = cli_runner.invoke(
            chapter_app,
            ["move", "--id", str(cid), "--to-volume", str(vid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        fake_http_client.post.assert_awaited()

    def test_move_not_found(self, cli_runner, fake_http_client):
        """章节不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(404, "章节不存在")
        result = cli_runner.invoke(
            chapter_app,
            ["move", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"


class TestVolumeUpdate:
    """volume update 命令契约（#251 P3：现仅 create/list/delete）。"""

    def test_update_json(self, cli_runner, fake_http_client):
        """volume update --json → PATCH /volumes/{id}（--order → body order_index）."""
        vid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_volume(title="新卷名")
        result = cli_runner.invoke(
            volume_app,
            ["update", "--id", str(vid), "--title", "新卷名", "--order", "2.5"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["data"]["title"] == "新卷名"
        call = fake_http_client.patch.await_args
        assert call is not None, "PATCH 未被调用"
        assert call.args[0] == f"/volumes/{vid}"
        body = call.kwargs.get("json") or {}
        assert body["title"] == "新卷名"
        assert body["order_index"] == 2.5

    def test_update_human(self, cli_runner, fake_http_client):
        """volume update 人类模式 → 成功提示."""
        fake_http_client.patch.return_value = _make_volume()
        result = cli_runner.invoke(
            volume_app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新卷名"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "新卷名" in result.output

    def test_update_not_found(self, cli_runner, fake_http_client):
        """卷不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.patch.side_effect = _http_error(404, "卷不存在")
        result = cli_runner.invoke(
            volume_app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新卷名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "NOT_FOUND"
