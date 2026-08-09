"""F36 地图管理 CLI RED 测试 — inkflow.cli.commands.map（尚未实现）。

覆盖（父侧定稿契约，spec §4 命令签名，逐字记录）:
- map create --project-id <uuid> --name <text> --image <path>
  [--root-location <uuid>] [--description <text>]（上传本地图片建图）
- map list --project-id <uuid> [--root-location <uuid>|none]
- map get <map_id> [--image-output <path>]
- map update <map_id> [--name <text>] [--description <text>]
  [--root-location <uuid>|none]
- map image <map_id> --image <path>（换图）
- map delete <map_id> [--force] [--cascade] [--reparent-to <map_id>]
- map children <map_id>
- map pin add <map_id> --x <float> --y <float> --label <text>
  [--location <uuid>]
- map pin list <map_id>
- map pin update <pin_id> [--x] [--y] [--label] [--location <uuid>|none]
- map pin delete <pin_id>

设计假设（GREEN 实现按此落地）:
- 模块结构: app = typer.Typer(name='map', help='地图管理',
  no_args_is_help=True) + @app.command 子命令（无 callback；
  直接 invoke(app, [...]) 测试）；pin 为嵌套子组。
- 每个命令: _parse_uuid(cli_ctx, value, message) 校验（非法 →
  print_error NOT_FOUND + Exit 1）+ async _impl() 内 ensure_kernel()
  + InkFlowHTTPClient(handle) + async with client:
  client.<method>(path, ...)。
- _run catch 链照抄 world.py: HttpApiError → map_http_error 映射
  （404→NOT_FOUND、422→VALIDATION_ERROR、401→CONFIG_ERROR、
  500+LLM_ERROR 头→LLM_ERROR、其余→INTERNAL_ERROR）；
  KernelStartupError → KERNEL_ERROR；ValidationError /
  FileNotFoundError → VALIDATION_ERROR；其余 → DB_ERROR。
- HTTP 客户端新方法（GREEN 扩展 infrastructure/http/client.py）:
  post_file(path, *, data, filename, content, params=None) /
  put_file(path, *, data, filename, content, params=None) /
  get_bytes(path, *, params=None) -> bytes（原始字节下载）。
- create: 本地扩展名白名单 png/jpg/jpeg/webp（不在白名单 →
  print_error VALIDATION_ERROR + Exit 1，不发请求）+ data=
  {'name', 'description'}（root_location 提供才加
  'root_location_id' 键）+ post_file(f'/projects/{pid}/maps',
  data=..., filename=Path(image).name, content=...)。
- list: --root-location none → params={'root_location_id': 'none'}；
  <uuid> → params；缺省无 params；响应 {"items","total","offset",
  "limit"} → 命令层提取 items 输出（信封 data={'items': [...],
  'total': ...}）。
- get: GET /maps/{map_id} 输出详情；--image-output <path> →
  get_bytes(f'/maps/{map_id}/image') → Path.write_bytes。
- update: --root-location none → body {'root_location_id': None}
  （显式 null = 改全局图）；<uuid> → body 键；缺省 body 不含该键；
  只含提供的字段。
- image: put_file(f'/maps/{map_id}/image', data={}, filename=...,
  content=...)（data 可为空 dict）。
- delete: 二次确认 —— --json + 无 --force → VALIDATION_ERROR
  （'删除需 --force 或交互确认'）；非 json 无 --force →
  typer.confirm（测试用 --force 直通）；params: --cascade →
  {'cascade': 'true'}；--reparent-to <uuid> → {'reparent_to': str}；
  响应 204 无 body → 命令层自构 {'deleted': True, 'id': str}。
- pin add: POST /maps/{map_id}/pins body={'x', 'y', 'label'}
  （location 提供才加 'location_id' 键）；pin list: GET
  /maps/{map_id}/pins → items 提取；pin update: PATCH
  /map-pins/{pin_id} body 只含提供的字段（--location none →
  {'location_id': None}）；pin delete: DELETE /map-pins/{pin_id}
  → {'deleted': True, 'id': ...}。
- 成功输出: --json → print_result 信封；人类可读 → typer.echo
  （✅ 前缀，文案自由——测试主要断言 --json 信封 + 退出码）。

── RED 形态说明 ──────────────────────────────────────────────
命令模块 cli/commands/map.py 尚未实现 → 顶部
from inkflow.cli.commands.map import app 收集期抛 ModuleNotFoundError
= 预期 RED（fixture patch 目标同模块，setup 亦失败，同根因）。
GREEN 阶段同时需扩展 client.py（post_file / put_file / get_bytes）
——mock fixture 为裸 AsyncMock，任意方法自动生成，无需真实类属性。

⚠️ 新文件不在 ci.yml integration-cli-backend job 文件列表——
需父 agent 追加登记（本任务只写测试文件，不碰 ci.yml）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.map import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（同 test_cli_world.py）.

    F38 陷阱: async with client 形态必须覆盖 __aenter__/__aexit__，
    否则 await 记录在 child mock 上，await_args 断言失败。裸
    AsyncMock → post_file/put_file/get_bytes 新方法自动生成。
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
            "inkflow.cli.commands.map.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.cli.commands.map.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_error(status_code: int, detail: str, code: str | None = None):
    """构造 HttpApiError（lazy import：F38 已合入，仍用例体调用保稳）."""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _make_map(**overrides) -> dict:
    """构造测试用 Map JSON dict（id/project_id/name/image_path/...）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="世界地图",
        image_path="/uploads/maps/world.png",
        description="主世界地图",
        root_location_id=None,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_pin(**overrides) -> dict:
    """构造测试用 MapPin JSON dict（id/map_id/location_id/x/y/label/...）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        map_id=str(uuid.uuid4()),
        location_id=None,
        x=1.5,
        y=2.5,
        label="主角出生地",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


class TestMapCreate:
    """map create — 上传本地图片建图（spec §4）."""

    def test_create_json_upload_success(self, cli_runner, fake_http_client, tmp_path):
        """create --json → 成功信封 + post_file 路径/data/filename/content.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        img = tmp_path / "world.png"
        img_bytes = PNG_MAGIC + b"\x00" * 16
        img.write_bytes(img_bytes)
        fake_http_client.post_file.return_value = _make_map(name="世界地图")
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "世界地图",
                "--image",
                str(img),
                "--description",
                "主世界地图",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "世界地图"
        fake_http_client.post_file.assert_awaited()
        call = fake_http_client.post_file.await_args
        assert call.args[0] == f"/projects/{PID}/maps"
        assert call.kwargs["filename"] == "world.png"
        assert call.kwargs["content"] == img_bytes
        assert call.kwargs["data"]["name"] == "世界地图"
        assert call.kwargs["data"]["description"] == "主世界地图"
        assert "root_location_id" not in call.kwargs["data"]

    def test_create_root_location_adds_key(
        self, cli_runner, fake_http_client, tmp_path
    ):
        """create 提供 --root-location → data 加 'root_location_id' 键.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        img = tmp_path / "world.png"
        img.write_bytes(PNG_MAGIC + b"\x00" * 8)
        root_loc = uuid.uuid4()
        fake_http_client.post_file.return_value = _make_map()
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "世界地图",
                "--image",
                str(img),
                "--root-location",
                str(root_loc),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.post_file.assert_awaited()
        call = fake_http_client.post_file.await_args
        assert call.kwargs["data"]["root_location_id"] == str(root_loc)

    def test_create_extension_not_whitelisted(
        self, cli_runner, fake_http_client, tmp_path
    ):
        """create --image .gif（非白名单）→ exit 1 + VALIDATION_ERROR.

        白名单: png/jpg/jpeg/webp —— 本地校验，不发请求。

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        img = tmp_path / "map.gif"
        img.write_bytes(b"GIF89a" + b"\x00" * 8)
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "世界地图",
                "--image",
                str(img),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.post_file.assert_not_awaited()

    def test_create_image_file_missing(self, cli_runner, fake_http_client, tmp_path):
        """create --image 文件不存在 → FileNotFoundError → VALIDATION_ERROR.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        missing = tmp_path / "missing.png"
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "世界地图",
                "--image",
                str(missing),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.post_file.assert_not_awaited()


class TestMapList:
    """map list — 分页信封 + --root-location 过滤（spec §4）."""

    def test_list_root_location_params(self, cli_runner, fake_http_client):
        """--root-location none/<uuid>/缺省 → params 三种形态.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        fake_http_client.get.return_value = {
            "items": [_make_map()],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        # none → params={'root_location_id': 'none'}
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID), "--root-location", "none"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        assert fake_http_client.get.await_args.kwargs["params"] == {
            "root_location_id": "none"
        }
        # <uuid> → params={'root_location_id': str}
        fake_http_client.get.reset_mock()
        root_loc = uuid.uuid4()
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID), "--root-location", str(root_loc)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        assert fake_http_client.get.await_args.kwargs["params"] == {
            "root_location_id": str(root_loc)
        }
        # 缺省 → 无 params
        fake_http_client.get.reset_mock()
        result = cli_runner.invoke(
            app, ["list", "--project-id", str(PID)], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        assert fake_http_client.get.await_args.kwargs.get("params") is None
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["items"][0]["name"] == "世界地图"
        assert data["data"]["total"] == 1


class TestMapGet:
    """map get — 详情 + --image-output 下载（spec §4）."""

    def test_get_json_and_image_output(self, cli_runner, fake_http_client, tmp_path):
        """get --json → 详情信封；--image-output → get_bytes + 落盘.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        mid = uuid.uuid4()
        fake_http_client.get.return_value = _make_map(name="世界地图")
        result = cli_runner.invoke(
            app, ["get", str(mid)], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "世界地图"
        fake_http_client.get.assert_awaited()
        assert fake_http_client.get.await_args.args[0] == f"/maps/{mid}"
        # --image-output → get_bytes 下载 + 写文件
        fake_http_client.get.reset_mock()
        img_bytes = PNG_MAGIC + b"\x00" * 32
        fake_http_client.get_bytes.return_value = img_bytes
        out = tmp_path / "out.png"
        result = cli_runner.invoke(
            app,
            ["get", str(mid), "--image-output", str(out)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        assert fake_http_client.get.await_args.args[0] == f"/maps/{mid}"
        fake_http_client.get_bytes.assert_awaited()
        assert fake_http_client.get_bytes.await_args.args[0] == f"/maps/{mid}/image"
        assert out.exists()
        assert out.read_bytes() == img_bytes


class TestMapUpdate:
    """map update — 部分字段更新 + --root-location none（spec §4）."""

    def test_update_root_location_none_and_default(self, cli_runner, fake_http_client):
        """--root-location none → body 含 root_location_id=None；缺省 → 无键.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        mid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_map(name="新地图")
        result = cli_runner.invoke(
            app,
            ["update", str(mid), "--name", "新地图", "--root-location", "none"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.patch.assert_awaited()
        assert fake_http_client.patch.await_args.args[0] == f"/maps/{mid}"
        body = fake_http_client.patch.await_args.kwargs["json"]
        assert "root_location_id" in body
        assert body["root_location_id"] is None
        # 缺省 --root-location → body 不含该键
        fake_http_client.patch.reset_mock()
        result = cli_runner.invoke(
            app,
            ["update", str(mid), "--name", "新地图"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body = fake_http_client.patch.await_args.kwargs["json"]
        assert "root_location_id" not in body


class TestMapImage:
    """map image — put_file 换图（spec §4）."""

    def test_image_put_file_success(self, cli_runner, fake_http_client, tmp_path):
        """image <id> --image <path> → put_file 被调（filename/content）.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        mid = uuid.uuid4()
        img = tmp_path / "new.png"
        img_bytes = PNG_MAGIC + b"\x00" * 8
        img.write_bytes(img_bytes)
        fake_http_client.put_file.return_value = _make_map(
            image_path="/uploads/maps/new.png"
        )
        result = cli_runner.invoke(
            app,
            ["image", str(mid), "--image", str(img)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.put_file.assert_awaited()
        call = fake_http_client.put_file.await_args
        assert call.args[0] == f"/maps/{mid}/image"
        assert call.kwargs["filename"] == "new.png"
        assert call.kwargs["content"] == img_bytes


class TestMapDelete:
    """map delete — 二次确认 + --force/--cascade/--reparent-to + 错误映射."""

    def test_delete_json_without_force_validation_error(
        self, cli_runner, fake_http_client
    ):
        """--json 无 --force → VALIDATION_ERROR（'删除需 --force 或交互确认'）.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        result = cli_runner.invoke(
            app, ["delete", str(uuid.uuid4())], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "删除需 --force 或交互确认" in data["error"]["message"]
        fake_http_client.delete.assert_not_awaited()

    def test_delete_force_cascade(self, cli_runner, fake_http_client):
        """delete --force --cascade → params cascade=true + 自构信封.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        mid = uuid.uuid4()
        fake_http_client.delete.return_value = None  # 204 无 body
        result = cli_runner.invoke(
            app,
            ["delete", str(mid), "--force", "--cascade"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        assert data["data"]["id"] == str(mid)
        fake_http_client.delete.assert_awaited()
        call = fake_http_client.delete.await_args
        assert call.args[0] == f"/maps/{mid}"
        assert call.kwargs["params"]["cascade"] == "true"

    def test_delete_force_reparent_to(self, cli_runner, fake_http_client):
        """delete --force --reparent-to <uuid> → params reparent_to=str(uuid).

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        mid = uuid.uuid4()
        target = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", str(mid), "--force", "--reparent-to", str(target)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.delete.assert_awaited()
        call = fake_http_client.delete.await_args
        assert call.args[0] == f"/maps/{mid}"
        assert call.kwargs["params"]["reparent_to"] == str(target)

    def test_delete_errors_mapped(self, cli_runner, fake_http_client):
        """404 → NOT_FOUND；422（有子地图文案）→ VALIDATION_ERROR.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        fake_http_client.delete.side_effect = _http_error(404, "地图不存在")
        result = cli_runner.invoke(
            app,
            ["delete", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        # 422 MapChildrenActionRequiredError 文案 → VALIDATION_ERROR
        fake_http_client.delete.reset_mock()
        fake_http_client.delete.side_effect = _http_error(
            422,
            "该地图存在子地图，必须指定 cascade=true（级联删除）或 "
            "reparent_to=<id>（子地图改挂新父）",
        )
        result = cli_runner.invoke(
            app,
            ["delete", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "子地图" in data["error"]["message"]


class TestMapPin:
    """map pin — add/list/update/delete 嵌套子组（spec §4）."""

    def test_pin_add_location_optional(self, cli_runner, fake_http_client):
        """pin add 提供 --location → body 含 location_id；缺省 → 无键；x/y float.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        mid = uuid.uuid4()
        loc = uuid.uuid4()
        fake_http_client.post.return_value = _make_pin()
        result = cli_runner.invoke(
            app,
            [
                "pin",
                "add",
                str(mid),
                "--x",
                "1.5",
                "--y",
                "2.5",
                "--label",
                "主角出生地",
                "--location",
                str(loc),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.post.assert_awaited()
        call = fake_http_client.post.await_args
        assert call.args[0] == f"/maps/{mid}/pins"
        body = call.kwargs["json"]
        assert body["x"] == 1.5
        assert body["y"] == 2.5
        assert body["label"] == "主角出生地"
        assert body["location_id"] == str(loc)
        # 缺省 --location → body 不含 location_id
        fake_http_client.post.reset_mock()
        result = cli_runner.invoke(
            app,
            ["pin", "add", str(mid), "--x", "3.0", "--y", "4.0", "--label", "地标"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert "location_id" not in body

    def test_pin_list_success(self, cli_runner, fake_http_client):
        """pin list <map_id> → GET /maps/{id}/pins → items 提取.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        mid = uuid.uuid4()
        fake_http_client.get.return_value = {
            "items": [_make_pin()],
            "total": 1,
        }
        result = cli_runner.invoke(
            app, ["pin", "list", str(mid)], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["items"][0]["label"] == "主角出生地"
        assert data["data"]["total"] == 1
        fake_http_client.get.assert_awaited()
        assert fake_http_client.get.await_args.args[0] == f"/maps/{mid}/pins"

    def test_pin_update_partial_fields(self, cli_runner, fake_http_client):
        """pin update --location none → {'location_id': None}；--x → {'x': 1.5}.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        pin_id = uuid.uuid4()
        fake_http_client.patch.return_value = _make_pin()
        result = cli_runner.invoke(
            app,
            ["pin", "update", str(pin_id), "--location", "none"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.patch.assert_awaited()
        call = fake_http_client.patch.await_args
        assert call.args[0] == f"/map-pins/{pin_id}"
        body = call.kwargs["json"]
        assert "location_id" in body
        assert body["location_id"] is None
        # 只传 --x → body 仅含 x，无 location_id
        fake_http_client.patch.reset_mock()
        result = cli_runner.invoke(
            app,
            ["pin", "update", str(pin_id), "--x", "1.5"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body = fake_http_client.patch.await_args.kwargs["json"]
        assert body["x"] == 1.5
        assert "location_id" not in body

    def test_pin_delete_success(self, cli_runner, fake_http_client):
        """pin delete → DELETE /map-pins/{pin_id} + {'deleted': True}.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        pin_id = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app, ["pin", "delete", str(pin_id)], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        assert data["data"]["id"] == str(pin_id)
        fake_http_client.delete.assert_awaited()
        assert fake_http_client.delete.await_args.args[0] == f"/map-pins/{pin_id}"


class TestMapGuard:
    """命令守卫（spec §4 边界）."""

    def test_unknown_subcommand_exit_2(self, cli_runner, fake_http_client):
        """map nosuch → exit 2（Typer 未知命令守卫）.

        RED 预期: 命令模块未实现 → 收集期 ModuleNotFoundError → FAIL。
        """
        result = cli_runner.invoke(app, ["nosuch"], obj=CliContext(json_output=True))
        assert result.exit_code == 2
