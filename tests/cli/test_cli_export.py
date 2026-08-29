"""F21 导出 CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（spec §4/§9 CLI 测试）。

覆盖（依据 specs/f21-export/spec.md §4/§7/§9.1/§13 M1-M2）:
- export 组注册（export 命令）
- 导出成功：名称解析 → 下载 TXT → 落盘（tmp_path）+ 人类模式输出
- --json 成功信封 {"ok": true, "data": {format/filename/bytes/path}} 精确断言
- --include-settings 透传 query include_settings=true（默认 false 且不含该键，#247）
- 项目不存在（搜索无匹配）→ NOT_FOUND 错误信封 + 退出码 1
- 下载途中 404 / 500 → NOT_FOUND / INTERNAL_ERROR + 退出码 1
- --output/-o 目录 vs 文件路径 vs 默认 cwd 语义
- 数字 ID 直通（跳过名称搜索）
- 写文件失败 → DB_ERROR 错误信封 + 退出码 1

── HTTP 模式（F38 #169 父侧裁定）────────────────────────────
F38 后全仓 CLI 恒经 HTTP：ensure_kernel() + InkFlowHTTPClient。
spec §4「直接消费 service 不经 HTTP」为未同步 F38 的陈旧措辞，
本测试按 HTTP 模式编写（镜像 tests/cli/test_cli_audit.py）。

── RED 形态说明 ───────────────────────────────────────────
inkflow.cli.commands.export 模块尚不存在 → 顶部 import 收集期
ModuleNotFoundError → collected 0 items / 1 error（exit 2），属预期
RED；GREEN 命令模块落地后自动转绿。HttpApiError 可顶部导入：
infrastructure.http 已随 F38 GREEN（与 audit RED 期不同，无需惰性导入）。

── 设计假设（GREEN 契约，本文件定义，父侧已拍板 HTTP 模式）──────
1. 模块路径: inkflow.cli.commands.export；app = typer.Typer(name="export",
   help=..., no_args_is_help=True) + 空 callback（Typer 单命令组压平规避，
   镜像 audit 模块）。
2. 命令签名:
   export_cmd(ctx: typer.Context,
              project: str = typer.Argument(..., help="项目名称或 ID"),
              include_settings: bool = typer.Option(False, "--include-settings"),
              output: str | None = typer.Option(None, "--output", "-o"))
   --json 是根 app 全局选项（cli/app.py main callback），测试经
   obj=CliContext(json_output=...) 注入（镜像 test_cli_audit.py）。
3. 项目解析（F1 约定：名称精确匹配，数字按 ID 解析）:
   - project 全数字（str.isdigit()）或形如 UUID → 直接当 project_id；
     此路径下 CLI 调 client.get(f"/projects/{pid}") 取项目对象
     （name 供建议文件名）。
   - 否则视为名称 → client.get("/projects", params={"search": <name>})
     返回 {"items": [...], "total": N, "offset": 0, "limit": 50}，
     精确匹配 items[].name == <name> 取 id（多个同名取首个）；
     无匹配 → print_error(cli_ctx, "NOT_FOUND", f"项目不存在: {name}")
     + 退出 1。items 元素只读 id/name 字段，其余字段测试不关心。
4. 下载: InkFlowHTTPClient 新增方法
   async def get_raw(self, path, *, params=None) -> str
   返回原始响应文本（TXT，非 JSON 信封）；非 2xx 抛 HttpApiError
   （GREEN 扩展 infrastructure/http/client.py）。
   include_settings=true 时 params={"include_settings": "true"}；
   默认（false）params 完全不含 include_settings 键（#247 契约收紧：
   None 值必须过滤——None → httpx 空串 include_settings= → API 422）。
5. 建议文件名: 由项目 name 生成 "{name}-txt.txt"（GREEN 可复用服务侧
   _export_filename.suggest_filename 或自行拼装；非法字符清洗 E5/空书名
   占位 E7 归单元层 tests/unit/test_output_models.py，本文件只用干净名称）。
6. 输出路径语义（spec §4）:
   - --output 为已存在目录 → 目录 / 建议文件名
   - --output 为其他路径 → 视为文件路径直接写入（父目录需存在；E8 已存在
     文件直接覆盖）
   - 缺省 → Path.cwd() / 建议文件名
7. 人类模式成功输出（码点精确，GREEN 按此实现）:
   f"✅ 导出成功: {name} → {path} ({bytes:,} bytes)"
   path = 实际写入文件路径字符串；bytes = TXT UTF-8 字节数。
   --json 成功信封（print_result）: {"ok": true, "data": {"format": "txt",
   "filename": <建议文件名>, "bytes": N, "path": <实际写入路径>}}
   —— F7 实际契约 ok 键（spec §4 示例 success 键为过时措辞）。
   --json 模式不抑制落盘（信封在写文件之后输出）。
8. 错误映射（_run 兜底，镜像 audit）:
   - HttpApiError → map_http_error: 404 → NOT_FOUND、500 无头 →
     INTERNAL_ERROR（detail 透传）
   - 写文件失败（OSError 系）在 _impl 内捕获 →
     print_error(cli_ctx, "DB_ERROR", f"写文件失败: {exc}") + 退出 1
   - typer.Exit 原样透传
9. ⚠️ ci.yml integration-cli-backend job 需显式追加本文件（spec §8.1
   陷阱 13/15——Windows pytest 不展开 glob），由父 agent 负责。

── 错误映射契约（spec §5.3 表 / F7）────────────────────────
- 搜索无匹配（项目不存在）→ NOT_FOUND，message = "项目不存在: <name>"
- get_raw 抛 HttpApiError(404)（导出途中项目被删）→ NOT_FOUND
- get_raw 抛 HttpApiError(500)（内部错误）→ INTERNAL_ERROR
- 写文件失败 → DB_ERROR，message 含 "写文件失败"
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.export import (
    app,
)  # RED 期模块不存在 → 收集期 ModuleNotFoundError（预期）
from inkflow.cli.context import CliContext
from inkflow.infrastructure.http import HttpApiError  # F38 已 GREEN，可顶部导入

PID = 1
PROJECT_NAME = "我的书"
TXT = (
    "我的书\n"
    "==============================\n"
    "\n"
    "第 1 卷 第一卷\n"
    "------------------------------\n"
    "\n"
    "第 1 章 开端\n"
    "\n"
    "（正文……）\n"
)
EXPECTED_BYTES = len(TXT.encode("utf-8"))


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）。"""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP。

    命令模块将从 inkflow.infrastructure.kernel/http from-import 这两个名字——
    patch 目标 = 命令模块命名空间（F38 契约）。__aenter__ 返回自身，兼容
    spec §4.2 的 `async with InkFlowHTTPClient(handle) as client` 形态。
    mock_instance 是裸 AsyncMock：get_raw（GREEN 才加入客户端）等任意属性
    自动生成 child mock，无需在真实类上存在。
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
            "inkflow.cli.commands.export.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.export.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _project(**overrides: object) -> dict:
    """构造测试用项目 JSON dict（search 列表项 / GET /projects/{id} 响应）。"""
    data: dict[str, object] = {"id": PID, "name": PROJECT_NAME}
    data.update(overrides)
    return data


def _project_list(projects: list[dict] | None = None) -> dict:
    """构造 GET /projects 列表信封 JSON dict（F1 router 实际形态）。"""
    items = projects if projects is not None else [_project()]
    return {"items": items, "total": len(items), "offset": 0, "limit": 50}


def _raw_call_params(mock) -> dict:
    """取 get_raw 最近一次调用的 params（兼容未传 params 的 GREEN 形态）。"""
    kwargs = mock.await_args.kwargs
    return kwargs.get("params") or {}


class TestExportRegistration:
    def test_group_help_lists_export(self):
        """export 组帮助包含 export 命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）。"""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "export" in result.output
        assert "导出" in result.output


class TestExportSuccess:
    def test_export_human_writes_file(self, cli_runner, fake_http_client, tmp_path):
        """导出成功：搜索解析名称 → get_raw 下载 → 落盘 + 人类输出（spec §4）。"""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        fake_http_client.get.return_value = _project_list()
        fake_http_client.get_raw.return_value = TXT

        result = cli_runner.invoke(
            app,
            ["export", PROJECT_NAME, "--output", str(out_dir)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        expected = out_dir / f"{PROJECT_NAME}-txt.txt"
        assert expected.read_text(encoding="utf-8") == TXT
        # 名称解析调用（GET /projects?search=）
        fake_http_client.get.assert_awaited_once_with(
            "/projects", params={"search": PROJECT_NAME}
        )
        # 下载路径
        assert fake_http_client.get_raw.await_args.args[0] == f"/projects/{PID}/export"
        # 人类模式成功文案（码点精确，见设计假设 7）
        assert (
            f"✅ 导出成功: {PROJECT_NAME} → {expected} ({EXPECTED_BYTES:,} bytes)"
            in result.output
        )

    def test_export_json_envelope(self, cli_runner, fake_http_client, tmp_path):
        """--json 成功信封精确断言（ok 键契约，F7；落盘不因 --json 抑制）。"""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        fake_http_client.get.return_value = _project_list()
        fake_http_client.get_raw.return_value = TXT

        result = cli_runner.invoke(
            app,
            ["export", PROJECT_NAME, "--output", str(out_dir)],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        expected = out_dir / f"{PROJECT_NAME}-txt.txt"
        assert expected.read_text(encoding="utf-8") == TXT
        data = json.loads(result.stdout)
        assert data == {
            "ok": True,
            "data": {
                "format": "txt",
                "filename": f"{PROJECT_NAME}-txt.txt",
                "bytes": EXPECTED_BYTES,
                "path": str(expected),
            },
        }

    def test_export_numeric_id_skips_search(
        self, cli_runner, fake_http_client, tmp_path
    ):
        """数字 project 参数 → 直接当 ID（F1 约定）：不搜索，GET /projects/42 取名称。"""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        fake_http_client.get.return_value = _project(id=42, name=PROJECT_NAME)
        fake_http_client.get_raw.return_value = TXT

        result = cli_runner.invoke(
            app,
            ["export", "42", "--output", str(out_dir)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        fake_http_client.get.assert_awaited_once_with("/projects/42")
        fake_http_client.get_raw.assert_awaited()
        assert fake_http_client.get_raw.await_args.args[0] == "/projects/42/export"
        assert (out_dir / f"{PROJECT_NAME}-txt.txt").read_text(encoding="utf-8") == TXT


class TestExportIncludeSettings:
    def test_export_include_settings_true(self, cli_runner, fake_http_client, tmp_path):
        """--include-settings → 下载 query 含 include_settings=true（spec §2.3 Q3=C）。"""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        fake_http_client.get.return_value = _project_list()
        fake_http_client.get_raw.return_value = TXT

        result = cli_runner.invoke(
            app,
            ["export", PROJECT_NAME, "--include-settings", "--output", str(out_dir)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        assert fake_http_client.get_raw.await_args.args[0] == f"/projects/{PID}/export"
        assert (
            _raw_call_params(fake_http_client.get_raw).get("include_settings") == "true"
        )

    def test_export_include_settings_default_false(
        self, cli_runner, fake_http_client, tmp_path
    ):
        """缺省（不带 flag）→ 下载 query **完全不含** include_settings 键。

        #247 契约收紧（rc1 验证实测）：旧实现 `params={"include_settings":
        "true" if flag else None}` 在 False 时把 None 传给 httpx → 序列化为
        空串 `include_settings=` → FastAPI bool_parsing 422。契约 = None 值
        必须过滤（#231 同族修复）。
        """
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        fake_http_client.get.return_value = _project_list()
        fake_http_client.get_raw.return_value = TXT

        result = cli_runner.invoke(
            app,
            ["export", PROJECT_NAME, "--output", str(out_dir)],
            obj=CliContext(json_output=False),
        )

        assert result.exit_code == 0
        assert "include_settings" not in _raw_call_params(fake_http_client.get_raw)


class TestExportOutputPaths:
    def test_export_output_file_writes_directly(
        self, cli_runner, fake_http_client, tmp_path
    ):
        """--output 为文件路径 → 直接写入该文件（建议文件名仅入信封，spec §4）。"""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        target = out_dir / "自定义名.txt"
        fake_http_client.get.return_value = _project_list()
        fake_http_client.get_raw.return_value = TXT

        result = cli_runner.invoke(
            app,
            ["export", PROJECT_NAME, "-o", str(target)],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        assert target.read_text(encoding="utf-8") == TXT
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["filename"] == f"{PROJECT_NAME}-txt.txt"
        assert data["data"]["path"] == str(target)

    def test_export_default_output_cwd(
        self, cli_runner, fake_http_client, tmp_path, monkeypatch
    ):
        """缺省 --output → 当前工作目录 + 建议文件名（spec §4 默认语义）。"""
        monkeypatch.chdir(tmp_path)
        fake_http_client.get.return_value = _project_list()
        fake_http_client.get_raw.return_value = TXT

        result = cli_runner.invoke(
            app,
            ["export", PROJECT_NAME],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 0
        expected = tmp_path / f"{PROJECT_NAME}-txt.txt"
        assert expected.read_text(encoding="utf-8") == TXT
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["path"] == str(expected)


class TestExportErrors:
    def test_export_project_not_found(self, cli_runner, fake_http_client):
        """项目不存在（搜索无匹配）→ NOT_FOUND 错误信封 + 退出码 1（spec §4）。"""
        fake_http_client.get.return_value = _project_list([])

        result = cli_runner.invoke(
            app,
            ["export", "不存在的书"],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert data["error"]["message"] == "项目不存在: 不存在的书"
        fake_http_client.get_raw.assert_not_awaited()

    def test_export_raw_http_404(self, cli_runner, fake_http_client, tmp_path):
        """下载途中 404（解析后项目被删）→ NOT_FOUND 错误信封 + 退出码 1。"""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        fake_http_client.get.return_value = _project_list()
        fake_http_client.get_raw.side_effect = HttpApiError(404, "Project not found")

        result = cli_runner.invoke(
            app,
            ["export", PROJECT_NAME, "--output", str(out_dir)],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_export_http_500(self, cli_runner, fake_http_client, tmp_path):
        """下载 500（内部错误）→ INTERNAL_ERROR 错误信封 + 退出码 1（spec §5.3）。"""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        fake_http_client.get.return_value = _project_list()
        fake_http_client.get_raw.side_effect = HttpApiError(500, "内部错误")

        result = cli_runner.invoke(
            app,
            ["export", PROJECT_NAME, "--output", str(out_dir)],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_export_write_failure(self, cli_runner, fake_http_client, tmp_path):
        """写文件失败（父路径是文件，open 必失败）→ DB_ERROR 信封 + 退出码 1（spec §4）。"""
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        out_path = blocker / "out.txt"  # 父路径是普通文件 → OSError（平台无关构造）
        fake_http_client.get.return_value = _project_list()
        fake_http_client.get_raw.return_value = TXT

        result = cli_runner.invoke(
            app,
            ["export", PROJECT_NAME, "--output", str(out_path)],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"
        assert "写文件失败" in data["error"]["message"]
