"""Foreshadowing CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（spec §4/§9 CLI 测试）.

覆盖（依据 specs/f13-foreshadowing/spec.md §4/§9）:
- 各子命令成功路径与参数透传（create/list/get/update/delete/resolve/reopen，含 --event-id）
- 信封格式与退出码 0/1/2（--status 非法值 → 退出码 2）
- delete 二次确认 + --force；--json + delete 无 --force → VALIDATION_ERROR
- resolve/reopen 人类可读输出（✅ 伏笔已回收/已重新开启）与 --json 完整对象
- NOT_FOUND 错误信封；--event-id "" 清除语义透传

F38 改造（#169）：mock 目标从 domain Service 迁移到 ensure_kernel + InkFlowHTTPClient
（HTTP JSON 响应）；create_tables patch 已移除。

── RED 形态说明 ─────────────────────────────────────────────
fake_http_client fixture patch 命令模块命名空间（inkflow.cli.commands.foreshadowing.
ensure_kernel / .InkFlowHTTPClient）——当前命令模块尚无这两个属性 → fixture setup 抛
AttributeError → 相关用例 ERROR（同根因，预期 RED；GREEN 命令改造落地后自动转绿）。
HttpApiError 在用例体内惰性导入：RED 阶段 inkflow.infrastructure.http 尚未实现，顶部
import 会使整文件收集失败（ModuleNotFoundError），无法呈现上述预期形态。

── 端点契约（spec §3.1 表）────────────────────────────────
create → POST /projects/{pid}/foreshadowings（body: title/description/priority/
location/event_id）；list → GET /projects/{pid}/foreshadowings（params: search/
status/sort_by/sort_desc）；get → GET /foreshadowings/{id}；update → PATCH
/foreshadowings/{id}；delete → DELETE /foreshadowings/{id}（v1.1 真删，
无 params）；resolve/reopen → POST /foreshadowings/{id}/resolve|reopen。
错误映射（spec §5.3）：404 → NOT_FOUND；422 → VALIDATION_ERROR；500 无头 →
INTERNAL_ERROR（DB_ERROR 恒 HTTP 后由 INTERNAL_ERROR 替代，spec §5.3 注）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.foreshadowing import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP（F38 mock 轨）。"""
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
            "inkflow.cli.commands.foreshadowing.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.foreshadowing.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _make_foreshadowing(**overrides: object) -> dict:
    """构造测试用 Foreshadowing JSON dict（model_dump(mode="json") 形态）."""
    defaults: dict[str, object] = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        title="林晚的身世",
        description="林晚右肩的胎记与女主母亲的信物相同；预期第 30 章前后揭露。",
        priority=80,
        status="open",
        location="第 5 章·林晚沐浴场景",
        event_id=None,
        resolved_at=None,
        extra={},
        created_at="2026-08-02T12:00:00",
        updated_at="2026-08-02T12:00:00",
    )
    defaults.update(overrides)
    return defaults


class TestForeshadowingRegistration:
    def test_group_help_lists_all_commands(self):
        """foreshadowing 组帮助包含全部 7 个命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）."""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in (
            "create",
            "list",
            "get",
            "update",
            "delete",
            "resolve",
            "reopen",
        ):
            assert name in result.output


class TestForeshadowingCreate:
    def test_create_json_envelope(self, cli_runner, fake_http_client):
        """create --json → 成功信封 + 参数透传（UUID/priority 转换，含 --event-id 挂接）."""
        eid = uuid.uuid4()
        fake_http_client.post.return_value = _make_foreshadowing(event_id=str(eid))
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--title",
                "林晚的身世",
                "--description",
                "林晚右肩的胎记与女主母亲的信物相同。",
                "--priority",
                "80",
                "--location",
                "第 5 章·林晚沐浴场景",
                "--event-id",
                str(eid),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林晚的身世"
        assert data["data"]["priority"] == 80
        assert data["data"]["event_id"] == str(eid)
        fake_http_client.post.assert_awaited_once_with(
            f"/projects/{PID}/foreshadowings",
            json={
                "title": "林晚的身世",
                "description": "林晚右肩的胎记与女主母亲的信物相同。",
                "priority": 80,
                "location": "第 5 章·林晚沐浴场景",
                "event_id": str(eid),
            },
        )

    def test_create_human(self, cli_runner, fake_http_client):
        """create 人类模式 → 成功提示（含优先级与未回收状态）."""
        fake_http_client.post.return_value = _make_foreshadowing(priority=80)
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 伏笔创建成功: [林晚的身世]" in result.output
        assert "优先级 80" in result.output
        assert "未回收" in result.output

    def test_create_project_not_found(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(404, "项目不存在")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_create_kernel_startup_error(self, cli_runner):
        """ensure_kernel 失败（内核冷启动超时）→ KERNEL_ERROR 信封 + 退出码 1（F38 spec §5.3）."""
        from inkflow.infrastructure.kernel import KernelStartupError

        with patch(
            "inkflow.cli.commands.foreshadowing.ensure_kernel",
            AsyncMock(side_effect=KernelStartupError("启动超时")),
        ):
            result = cli_runner.invoke(
                app,
                ["create", "--project-id", str(PID), "--title", "林晚的身世"],
                obj=CliContext(json_output=True),
            )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "KERNEL_ERROR"
        assert "内核启动失败" in data["error"]["message"]


class TestForeshadowingList:
    def test_list_json(self, cli_runner, fake_http_client):
        """list --json → 成功信封 + 伏笔数组."""
        fake_http_client.get.return_value = {
            "items": [_make_foreshadowing()],
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
        assert data["data"][0]["title"] == "林晚的身世"

    def test_list_human_empty(self, cli_runner, fake_http_client):
        """空列表人类模式 → 暂无伏笔."""
        fake_http_client.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无伏笔" in result.output

    def test_list_human_open(self, cli_runner, fake_http_client):
        """未回收伏笔人类模式 → 📋 摘要（编号 + 优先级 + 埋设位置）."""
        fake_http_client.get.return_value = {
            "items": [_make_foreshadowing()],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "未回收伏笔 1 条" in result.output
        assert "1. [林晚的身世] (优先级 80, 第 5 章·林晚沐浴场景)" in result.output

    def test_list_human_resolved(self, cli_runner, fake_http_client):
        """已回收伏笔人类模式 → 🔍 摘要（含回收日期）."""
        fake_http_client.get.return_value = {
            "items": [
                _make_foreshadowing(
                    status="resolved", resolved_at="2026-08-10T03:00:00"
                )
            ],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已回收伏笔 1 条" in result.output
        assert "[林晚的身世] (回收于 2026-08-10)" in result.output

    def test_list_params_passthrough(self, cli_runner, fake_http_client):
        """list 状态过滤/搜索/排序/降序参数透传."""
        fake_http_client.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            app,
            [
                "list",
                "--project-id",
                str(PID),
                "--status",
                "open",
                "--search",
                "身世",
                "--sort",
                "title",
                "--no-sort-desc",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.get.assert_awaited_once_with(
            f"/projects/{PID}/foreshadowings",
            params={
                "search": "身世",
                "status": "open",
                "sort_by": "title",
                "sort_desc": False,
            },
        )

    def test_list_invalid_status_exit_code_2(self, cli_runner, fake_http_client):
        """--status 非法值 → 用法错误退出码 2（F7 §7 非法枚举值）."""
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID), "--status", "bogus"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.get.assert_not_awaited()

    def test_list_project_not_found(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.get.side_effect = HttpApiError(404, "项目不存在")
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestForeshadowingGet:
    def test_get_json(self, cli_runner, fake_http_client):
        """伏笔存在 → 成功信封 + id 透传."""
        eid = uuid.uuid4()
        fake_http_client.get.return_value = _make_foreshadowing()
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林晚的身世"
        fake_http_client.get.assert_awaited_once_with(f"/foreshadowings/{eid}")

    def test_get_not_found_json(self, cli_runner, fake_http_client):
        """伏笔不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.get.side_effect = HttpApiError(404, "伏笔不存在")
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "伏笔不存在" in data["error"]["message"]

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


class TestForeshadowingUpdate:
    def test_update_json(self, cli_runner, fake_http_client):
        """update --json → 成功信封 + ForeshadowingUpdate 透传（仅传入字段）."""
        eid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_foreshadowing(title="林晚的身世·改")
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                str(eid),
                "--title",
                "林晚的身世·改",
                "--description",
                "新描述",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林晚的身世·改"
        call = fake_http_client.patch.await_args
        assert call.args[0] == f"/foreshadowings/{eid}"
        body: dict = call.kwargs["json"]
        assert body["title"] == "林晚的身世·改"
        assert body["description"] == "新描述"
        assert "priority" not in body
        assert "event_id" not in body

    def test_update_clear_event_id(self, cli_runner, fake_http_client):
        """update --event-id "" → 清除语义透传（event_id="" 进入 body）."""
        eid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_foreshadowing(event_id=None)
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(eid), "--event-id", ""],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body: dict = fake_http_client.patch.await_args.kwargs["json"]
        assert "event_id" in body
        assert body["event_id"] == ""

    def test_update_event_id_uuid(self, cli_runner, fake_http_client):
        """update --event-id <uuid> → UUID 转换后进入 body."""
        eid = uuid.uuid4()
        new_eid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_foreshadowing(event_id=str(new_eid))
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(eid), "--event-id", str(new_eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body: dict = fake_http_client.patch.await_args.kwargs["json"]
        assert body["event_id"] == str(new_eid)

    def test_update_not_found(self, cli_runner, fake_http_client):
        """伏笔不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.patch.side_effect = HttpApiError(404, "伏笔不存在")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestForeshadowingDelete:
    def test_delete_force_json(self, cli_runner, fake_http_client):
        """delete --force --json → 成功信封 + 真删除（无确认 GET）."""
        eid = uuid.uuid4()
        fake_http_client.delete.return_value = {}
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        assert data["data"]["id"] == str(eid)
        fake_http_client.delete.assert_awaited_once_with(f"/foreshadowings/{eid}")

    def test_delete_confirm_yes(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除（输出含标题）."""
        eid = uuid.uuid4()
        fake_http_client.delete.return_value = {}
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert f"✅ 伏笔 #{eid} 已删除" in result.output
        fake_http_client.delete.assert_awaited_once_with(f"/foreshadowings/{eid}")

    def test_delete_confirm_no(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 回答 n 取消，不调用删除."""
        eid = uuid.uuid4()
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid)],
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
        """伏笔不存在（DELETE 404）→ NOT_FOUND 错误信封."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.delete.side_effect = HttpApiError(404, "伏笔不存在")
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestForeshadowingResolve:
    def test_resolve_json(self, cli_runner, fake_http_client):
        """resolve --json → 成功信封 + 完整对象（status=resolved）."""
        eid = uuid.uuid4()
        fake_http_client.post.return_value = _make_foreshadowing(
            status="resolved", resolved_at="2026-08-10T03:00:00"
        )
        result = cli_runner.invoke(
            app,
            ["resolve", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["status"] == "resolved"
        assert data["data"]["resolved_at"] is not None
        fake_http_client.post.assert_awaited_once_with(f"/foreshadowings/{eid}/resolve")

    def test_resolve_human(self, cli_runner, fake_http_client):
        """resolve 人类模式 → ✅ 伏笔已回收."""
        eid = uuid.uuid4()
        fake_http_client.post.return_value = _make_foreshadowing(status="resolved")
        result = cli_runner.invoke(
            app,
            ["resolve", "--id", str(eid)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 伏笔已回收: [林晚的身世]" in result.output

    def test_resolve_not_found(self, cli_runner, fake_http_client):
        """伏笔不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(404, "伏笔不存在")
        result = cli_runner.invoke(
            app,
            ["resolve", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestForeshadowingReopen:
    def test_reopen_json(self, cli_runner, fake_http_client):
        """reopen --json → 成功信封 + 完整对象（status=open, resolved_at=None）."""
        eid = uuid.uuid4()
        fake_http_client.post.return_value = _make_foreshadowing(
            status="open", resolved_at=None
        )
        result = cli_runner.invoke(
            app,
            ["reopen", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["status"] == "open"
        assert data["data"]["resolved_at"] is None
        fake_http_client.post.assert_awaited_once_with(f"/foreshadowings/{eid}/reopen")

    def test_reopen_human(self, cli_runner, fake_http_client):
        """reopen 人类模式 → ✅ 伏笔已重新开启."""
        eid = uuid.uuid4()
        fake_http_client.post.return_value = _make_foreshadowing()
        result = cli_runner.invoke(
            app,
            ["reopen", "--id", str(eid)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 伏笔已重新开启: [林晚的身世]" in result.output

    def test_reopen_not_found(self, cli_runner, fake_http_client):
        """伏笔不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(404, "伏笔不存在")
        result = cli_runner.invoke(
            app,
            ["reopen", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestForeshadowingErrorMapping:
    """错误映射补全：ServiceError / ValidationError / INTERNAL_ERROR."""

    def test_create_service_error(self, cli_runner, fake_http_client):
        """API 422（业务校验失败）→ VALIDATION_ERROR 信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(422, "同名伏笔已存在")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "同名伏笔已存在" in data["error"]["message"]

    def test_create_validation_error(self, cli_runner, fake_http_client):
        """API 422（参数校验）→ VALIDATION_ERROR 信封."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(
            422, "Input should be a valid string"
        )
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_create_internal_error(self, cli_runner, fake_http_client):
        """HTTP 500 无错误码头 → INTERNAL_ERROR 信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(500, "boom")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert "boom" in data["error"]["message"]


class TestForeshadowingHumanOutput:
    """人类可读输出补全：已回收状态 / get 详情 / update / delete 失败."""

    def test_create_human_resolved_status(self, cli_runner, fake_http_client):
        """create 人类模式返回已回收状态 → 状态标签为已回收."""
        fake_http_client.post.return_value = _make_foreshadowing(status="resolved")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已回收" in result.output

    def test_list_human_resolved_no_date(self, cli_runner, fake_http_client):
        """已回收且无回收日期 → 列表项显示（已回收）."""
        fake_http_client.get.return_value = {
            "items": [_make_foreshadowing(status="resolved", resolved_at=None)],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已回收伏笔 1 条" in result.output
        assert "[林晚的身世] (已回收)" in result.output

    def test_get_human(self, cli_runner, fake_http_client):
        """get 人类模式 → 全字段详情输出（含未挂接/未回收回退）."""
        fake_http_client.get.return_value = _make_foreshadowing()
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        for token in (
            "标题:",
            "林晚的身世",
            "优先级:",
            "状态:",
            "未回收",
            "埋设位置:",
            "事件锚点:",
            "（未挂接）",
            "回收时间:",
            "（未回收）",
        ):
            assert token in result.output

    def test_update_priority_location(self, cli_runner, fake_http_client):
        """update --priority/--location → 字段进入 body."""
        eid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_foreshadowing()
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                str(eid),
                "--priority",
                "90",
                "--location",
                "第 8 章",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body: dict = fake_http_client.patch.await_args.kwargs["json"]
        assert body["priority"] == 90
        assert body["location"] == "第 8 章"
        assert "title" not in body

    def test_update_human(self, cli_runner, fake_http_client):
        """update 人类模式 → 成功提示."""
        fake_http_client.patch.return_value = _make_foreshadowing(title="林晚的身世·改")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "林晚的身世·改"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "伏笔已更新: [林晚的身世·改]" in result.output

    def test_delete_not_found_on_delete(self, cli_runner, fake_http_client):
        """delete 时 API 404 → NOT_FOUND 错误信封."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        eid = uuid.uuid4()
        fake_http_client.delete.side_effect = HttpApiError(404, "伏笔不存在")
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
