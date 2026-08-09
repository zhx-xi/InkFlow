"""F37 世界观跨书复制（#175）— `world copy` CLI 契约测试（独立文件）。

拆分原因: 追加 copy 契约段后 tests/cli/test_cli_world.py 将超 900 行护栏
（实测 779 + 124 = 903），故 copy 用例独立成文件（F35 test_cli_world_tree.py
先例）；fixtures/helpers 从 test_cli_world.py 逐字复制保持同构。
⚠️ 新文件需父 agent 追加进 ci.yml integration-cli-backend job 文件列表。

覆盖（依据 specs/f37-world-copy/spec.md §4/§13 M6）:
- copy 成功 --json 信封（created 2 条 / pins_created 3）
- copy 人类模式完成摘要（条目/地图/pin 计数）
- body 契约（无 --root → 不含 root_setting_id 键；--root → 透传）
- POST 路径契约（/projects/{target}/world-settings/copy）
- 404 源项目不存在 → NOT_FOUND + exit 1（JSON 信封 + 人类模式）

契约签名（spec §4 字面，ancestors/descendants 同款位置参数形态）:
    copy(source_project_id: str = Argument(...),
         target_project_id: str = Argument(...),
         root: str | None = Option(None, "--root"))
HTTP: POST /projects/{target}/world-settings/copy，body =
    {"source_project_id": ..., "root_setting_id": ...}
    无 --root → body 不含 root_setting_id 键（镜像 create --parent 缺省契约）
成功 → F7 信封 {"ok": true, "data": {created/skipped/maps_created/
    pins_created/warnings}}；人类输出 "✅ 复制完成: N 条世界观条目,
    M 张地图, K 个 pin" + skipped/warnings 摘要行
404（源/目标项目不存在）→ NOT_FOUND + exit 1（_run 兜底）。

RED 预期（1e 追加段形态）: copy 子命令未注册 → CliRunner exit 2
（No such command 'copy'），各用例 assert exit_code == 0/1 干净 FAILED。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.world import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
SRC_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000a1")
TGT_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000a2")


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


def _make_copy_report(**overrides) -> dict:
    """构造测试用 WorldCopyResult JSON dict（spec §2/§3.2 形态）."""
    defaults = dict(
        created=[_make_setting(name="大越国"), _make_setting(name="青州")],
        skipped=[],
        maps_created=[{"id": str(uuid.uuid4()), "name": "清河县城图"}],
        pins_created=3,
        warnings=[],
    )
    defaults.update(overrides)
    return defaults


class TestWorldCopy:
    """world copy 命令契约（8 用例，含 skipped/warnings 人类输出分支）."""

    def test_copy_json_envelope(self, cli_runner, fake_http_client):
        """copy 成功 --json → 成功信封 + 复制报告透传（created 2 条 / pins 3）."""
        fake_http_client.post.return_value = _make_copy_report()
        result = cli_runner.invoke(
            app,
            ["copy", str(SRC_PID), str(TGT_PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert len(data["data"]["created"]) == 2
        assert data["data"]["pins_created"] == 3
        fake_http_client.post.assert_awaited()

    def test_copy_human_summary(self, cli_runner, fake_http_client):
        """copy 人类模式 → 完成摘要（条目/地图/pin 计数）."""
        fake_http_client.post.return_value = _make_copy_report()
        result = cli_runner.invoke(
            app,
            ["copy", str(SRC_PID), str(TGT_PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "复制完成" in result.output
        assert "2 条" in result.output
        assert "1 张" in result.output
        assert "3 个" in result.output

    def test_copy_body_default_root_omitted(self, cli_runner, fake_http_client):
        """无 --root → body 含 source_project_id、不含 root_setting_id 键."""
        fake_http_client.post.return_value = _make_copy_report()
        result = cli_runner.invoke(
            app,
            ["copy", str(SRC_PID), str(TGT_PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert body["source_project_id"] == str(SRC_PID)
        assert "root_setting_id" not in body

    def test_copy_body_with_root(self, cli_runner, fake_http_client):
        """--root <uuid> → body 含 root_setting_id（复制起点条目 ID 透传）."""
        root = uuid.uuid4()
        fake_http_client.post.return_value = _make_copy_report()
        result = cli_runner.invoke(
            app,
            ["copy", str(SRC_PID), str(TGT_PID), "--root", str(root)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert body["root_setting_id"] == str(root)

    def test_copy_post_path(self, cli_runner, fake_http_client):
        """POST 路径 = /projects/{target}/world-settings/copy（目标 ID 在路径）."""
        fake_http_client.post.return_value = _make_copy_report()
        result = cli_runner.invoke(
            app,
            ["copy", str(SRC_PID), str(TGT_PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.post.await_args
        assert call.args[0] == f"/projects/{TGT_PID}/world-settings/copy"

    def test_copy_source_not_found(self, cli_runner, fake_http_client):
        """源项目不存在（HTTP 404）→ NOT_FOUND 信封 + 人类模式错误输出，exit 1."""
        fake_http_client.post.side_effect = _http_error(404, "源项目不存在")
        result = cli_runner.invoke(
            app,
            ["copy", str(SRC_PID), str(TGT_PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        fake_http_client.post.reset_mock()
        result = cli_runner.invoke(
            app,
            ["copy", str(SRC_PID), str(TGT_PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 1
        assert "源项目不存在" in result.output

    def test_copy_human_skipped_branch(self, cli_runner, fake_http_client):
        """人类模式 + skipped 非空 → 「⚠️ 跳过同名条目: 青州」行（L330 分支）."""
        fake_http_client.post.return_value = _make_copy_report(skipped=["青州"])
        result = cli_runner.invoke(
            app,
            ["copy", str(SRC_PID), str(TGT_PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "跳过同名条目" in result.output
        assert "青州" in result.output

    def test_copy_human_warnings_branch(self, cli_runner, fake_http_client):
        """人类模式 + warnings 非空 → 逐条「⚠️ <warning>」输出（L332 循环）."""
        warning = "地图「总览图」的 1 个 pin 关联地点不在复制集合，已转为纯注释"
        fake_http_client.post.return_value = _make_copy_report(warnings=[warning])
        result = cli_runner.invoke(
            app,
            ["copy", str(SRC_PID), str(TGT_PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "⚠️" in result.output
        assert warning in result.output
