"""Character CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（HTTP JSON 响应）。

覆盖（依据 specs/f9-character-service/spec.md §4/§7/§9）:
- 各子命令成功路径与参数透传（create/list/get/update/delete/restore + group 子组）
- 信封格式与退出码 0/1/2
- delete 二次确认 + --force；--json + delete 无 --force → VALIDATION_ERROR
- NOT_FOUND、VALIDATION_ERROR 错误信封

F38 改造（#169）：mock 目标从 domain Service（CharacterService + create_tables）
迁移到 ensure_kernel + InkFlowHTTPClient；返回值从 Character 等领域对象改为
JSON dict（model_dump(mode="json") 等价物）；create_tables/session 相关
patch 已移除；错误路径抛 HttpApiError（lazy import，RED 阶段模块未实现）。
list 端点返回 {"items", "total"}，命令层提取 items 后保持原信封（list 输出）。
HTTP 错误码映射（命令侧，输出不变）：404→NOT_FOUND、422→VALIDATION_ERROR。

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

from inkflow.cli.commands.character import app
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


class TestCharacterCreate:
    def test_create_json_envelope(self, cli_runner, fake_http_client):
        """create --json → 成功信封 + HTTP 调用（UUID 转换在命令侧）."""
        fake_http_client.post.return_value = _make_character(name="林尘")
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
        fake_http_client.post.assert_awaited()

    def test_create_with_group_id(self, cli_runner, fake_http_client):
        """create --group-id → 透传 UUID（HTTP 调用发生）."""
        gid = uuid.uuid4()
        fake_http_client.post.return_value = _make_character(group_id=str(gid))
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "林尘",
                "--group-id",
                str(gid),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.post.assert_awaited()

    def test_create_human(self, cli_runner, fake_http_client):
        """create 人类模式 → 成功提示."""
        fake_http_client.post.return_value = _make_character(name="林尘")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "林尘"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "角色创建成功" in result.output

    def test_create_name_conflict(self, cli_runner, fake_http_client):
        """同名角色 → VALIDATION_ERROR 信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(422, "同名角色")
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
    def test_list_json(self, cli_runner, fake_http_client):
        """list --json → 成功信封 + 角色数组."""
        fake_http_client.get.return_value = {
            "items": [_make_character()],
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
        assert data["data"][0]["name"] == "林尘"

    def test_list_human_empty(self, cli_runner, fake_http_client):
        """空列表人类模式 → 暂无角色."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无角色" in result.output

    def test_list_params_passthrough(self, cli_runner, fake_http_client):
        """list 搜索/分组/排序/分页参数 → HTTP 调用发生（参数透传在命令侧）."""
        gid = uuid.uuid4()
        fake_http_client.get.return_value = {"items": [], "total": 0}
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
        fake_http_client.get.assert_awaited()


class TestCharacterGet:
    def test_get_json(self, cli_runner, fake_http_client):
        """角色存在 → 成功信封."""
        cid = uuid.uuid4()
        fake_http_client.get.return_value = _make_character(name="林尘")
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(cid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "林尘"
        fake_http_client.get.assert_awaited()

    def test_get_not_found_json(self, cli_runner, fake_http_client):
        """角色不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.get.side_effect = _http_error(404, "角色不存在")
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

    def test_get_invalid_uuid(self, cli_runner, fake_http_client):
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
    def test_update_json(self, cli_runner, fake_http_client):
        """update --json → 成功信封（仅传入字段进入 update，命令侧）."""
        cid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_character(name="林尘二世")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(cid), "--name", "林尘二世", "--personality", "沉稳"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "林尘二世"
        fake_http_client.patch.assert_awaited()

    def test_update_clear_group(self, cli_runner, fake_http_client):
        """update --group-id \"\" → 显式清除分组（HTTP 调用发生）."""
        cid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_character()
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(cid), "--group-id", ""],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.patch.assert_awaited()

    def test_update_not_found(self, cli_runner, fake_http_client):
        """角色不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.patch.side_effect = _http_error(404, "角色不存在")
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
    def test_delete_force_json(self, cli_runner, fake_http_client):
        """delete --force --json → 成功信封 + 软删除（force=False）."""
        cid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(cid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        fake_http_client.delete.assert_awaited()

    def test_delete_permanent_passes_force(self, cli_runner, fake_http_client):
        """delete --permanent → HTTP 调用发生（force=True 透传在命令侧）."""
        cid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(cid), "--force", "--permanent"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.delete.assert_awaited()

    def test_delete_confirm_yes(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除."""
        cid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(cid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output
        fake_http_client.delete.assert_awaited()

    def test_delete_confirm_no(self, cli_runner, fake_http_client):
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
        """角色不存在（HTTP 404）→ NOT_FOUND 错误信封."""
        fake_http_client.delete.side_effect = _http_error(404, "角色不存在")
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
    def test_restore_json(self, cli_runner, fake_http_client):
        """restore --json → 成功信封."""
        fake_http_client.post.return_value = _make_character(name="林尘")
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "林尘"

    def test_restore_not_found(self, cli_runner, fake_http_client):
        """角色不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(404, "角色不存在")
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
