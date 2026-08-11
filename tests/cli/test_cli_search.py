"""F22 全文搜索 CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（F38 mock 轨）。

覆盖（依据 specs/f22-search-service/spec.md §4/§9 + M2/M13，v1.2 拍板
「CLI 恒经 HTTP」ADR-030/F38）：
- 命中人类可读输出（类型徽标 + 项目名 + 标题 + snippet，<mark> → [ ] 方括号替换）
- --json 成功信封（{"ok": true, "data": SearchResponse}）
- HttpApiError(404) → NOT_FOUND 错误信封 + 退出码 1（F38 错误码映射）
- 多 -p 多 -t（及 --limit / --offset）透传 GET /search params
- --rebuild → POST /search/rebuild（人类输出 + --json 信封两种形态）
- --mode semantic 透传
- query 缺失 → 退出码 2（Typer 自动）
- 项目名 → GET /projects 解析为 id（父侧裁定：--project 接受名或 UUID）

> **⚠️ 契约修正（#246，2026-08-11 rc1 验证实测）**：端点路径**不带**
> `/api/v1` 前缀——InkFlowHTTPClient base_url 已含 `/api/v1`
> （infrastructure/http/client.py L55），双前缀拼出 `/api/v1/api/v1/search`
> → 真实 HTTP 404（0.6.0 F38 改造遗留，mock 轨测不出 URL 拼接）。
> 以下 docstring/断言中 `/api/v1/search`、`/api/v1/search/rebuild`、
> `/api/v1/projects` 均为修正后形态（`/search`、`/search/rebuild`、`/projects`）。

── RED 形态说明 ─────────────────────────────────────────────
- 本文件模块级 import `inkflow.cli.commands.search`（命令模块不存在）
  → 收集期 ModuleNotFoundError（整文件 error，collected 0 items）——
  预期 RED；GREEN 命令模块落地后自动转绿。
- fake_http_client fixture patch 命令模块命名空间
  （inkflow.cli.commands.search.ensure_kernel / .InkFlowHTTPClient）——
  与 test_cli_style.py 同构。
- HttpApiError 经 _http_error helper 在用例体内惰性导入（F38 已合入
  main，inkflow.infrastructure.http 存在；惰性仅为防御收集期连锁失败）。

── 端点契约（spec §4，v1.2；#246 修正：路径不含 /api/v1 前缀）────────────────
- search <query> -p X → GET /search（params: q / project_ids
  逗号连接 / types 逗号连接 / mode / limit / offset）
- --rebuild [-p X] → POST /search/rebuild（params: project_id 可选）
- 错误映射（F38 map_http_error）：404 → NOT_FOUND；422 →
  VALIDATION_ERROR；500 + LLM_ERROR 头 → LLM_ERROR；其余 → INTERNAL_ERROR

════════════════════════════════════════════════════════════════════
设计假设（RED 阶段按 spec 口径记录，GREEN 实现必须满足，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 测试方式：typer.testing.CliRunner + F38 mock 轨（test_cli_style.py
   同款 fixture）：fake_http_client 同时 patch
   `inkflow.cli.commands.search.ensure_kernel`（AsyncMock 返回
   SimpleNamespace KernelHandle）与
   `inkflow.cli.commands.search.InkFlowHTTPClient`（autospec=True，
   mock_cls.return_value = AsyncMock 实例，且
   `mock_instance.__aenter__.return_value = mock_instance` 自引用覆盖
   ——命令经 `async with InkFlowHTTPClient(handle) as client:` 形态）。
   命令模块 `inkflow.cli.commands.search` 本文件模块级 import（RED
   阶段不存在 → 收集期 ModuleNotFoundError）。

2. 【模块结构——GREEN 必须匹配】search.py 暴露：
   - `app = typer.Typer(name="search", help=..., no_args_is_help=True)`
   - 唯一命令函数 `search(...)`（`@app.command()` 装饰，无 callback
     → typer 0.27 单命令组压平为命令本身，serve.py 先例；本 venv 实测
     位置参数经压平组直接透传）——测试统一
     `runner.invoke(app, ["<query>", ...], obj=CliContext(...))`，
     【不带】子命令名 "search"
   - root 注册：cli/app.py `app.command(name="search")(search_fn)`
     （spec §8.1，serve 同款）
   命令签名（spec §4）：query 位置参数（必填，--rebuild 模式不适用）、
   --project / -p（可重复，项目名或 UUID，必填 ≥1）、--type / -t
   （可重复）、--mode（keyword/semantic，默认 keyword）、--limit
   （默认 20）、--offset（默认 0）、--rebuild、--json。

3. HTTP 端点映射（spec §4，v1.2；#246 修正：base_url 已含 /api/v1，路径不带前缀）：
   - 查询 → `await client.get("/search", params={...})`——
     params 含 q、project_ids（多 -p 逗号连接 UUID 字符串）、types
     （多 -t 逗号连接枚举）、mode、limit、offset
   - --rebuild → `await client.post("/search/rebuild",
     params={...})`——project_id 仅当 --project 提供（缺省 = 重建全部）
   - client 方法以位置参数传 path（F38 既有命令形态）
   - 项目名解析与命中展示的项目名映射均经 `GET /projects`
     列表端点（响应信封 {"items": [{id, name}, ...], "total"}）——
     本文件 mock 仅覆盖该列表端点 + search / rebuild 端点，其余路径
     视为测试错误（_route_http 抛 AssertionError）

4. 人类可读输出（spec §4 示例）：每命中一行「类型徽标 + 项目名 +
   标题」（如 `[chapter] 测试之书 · 第 3 章 龙的苏醒`，分隔符不锁定），
   snippet 单独行且 `<mark>` → `[ ]` 方括号替换（终端无 HTML 语义）；
   `--json` 时 data = SearchResponse 原样、snippet 保留 `<mark>`
   （消费端自行渲染）。

5. --json 信封（F7 约定）：成功 {"ok": true, "data": <SearchResponse
   JSON>}；--rebuild 成功 data = {"rebuilt_at", "project_id"}；失败
   {"ok": false, "error": {"code": <F38 错误码>, "message": <detail>}}
   （print_error 写 stdout，退出码 1）。

6. 错误映射（F38 map_http_error，spec §4）：HttpApiError(404) →
   NOT_FOUND 信封 + 退出码 1；query 缺失（非 --rebuild）→ 退出码 2
   （Typer 参数校验或命令内显式校验均可，spec §4「query 空白 → 退出 2」）。

7. RED 阶段预期：`inkflow.cli.commands.search` 模块不存在 → 本文件
   收集期 ModuleNotFoundError（collected 0 items + 1 error，退出码 2）。
   GREEN 阶段：实现 cli/commands/search.py + cli/app.py 注册后全绿。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.search import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PID2 = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
ENTITY_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-00000000000a")
PROJECT_NAME = "测试之书"
TS = "2026-08-09T12:00:00Z"


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）。"""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP（F38 mock 轨）。

    设计假设 #1：patch 目标 = inkflow.cli.commands.search 命名空间
    （GREEN 后命令 from-import 绑定自身模块属性）。
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
            "inkflow.cli.commands.search.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.search.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_error(status_code: int, detail: str, code: str | None = None):
    """构造 HttpApiError（用例体内惰性导入，防收集期连锁失败）。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code, detail, code=code)


def _hit(**overrides: object) -> dict:
    """构造单条 SearchHit JSON dict（spec §2.2）。"""
    hit: dict[str, object] = {
        "entity_type": "chapter",
        "entity_id": str(ENTITY_ID),
        "project_id": str(PID),
        "title": "第 3 章 龙的苏醒",
        "snippet": "古井深处，<mark>龙</mark>瞳睁开。它沉睡千年……<mark>龙</mark>息如雷。",
        "score": 3.2,
    }
    hit.update(overrides)
    return hit


def _search_response(**overrides: object) -> dict:
    """构造完整 SearchResponse JSON dict（spec §2.2 / §3.2 示例）。"""
    data: dict[str, object] = {
        "total": 1,
        "hits": [_hit()],
        "query": "龙",
        "types": None,
        "mode": "keyword",
        "project_ids": [str(PID)],
    }
    data.update(overrides)
    return data


def _projects_response(**overrides: object) -> dict:
    """构造 GET /api/v1/projects 列表响应（F1 信封：items/total/offset/limit）。"""
    data: dict[str, object] = {
        "items": [{"id": str(PID), "name": PROJECT_NAME}],
        "total": 1,
        "offset": 0,
        "limit": 50,
    }
    data.update(overrides)
    return data


def _route_http(*args, **kwargs) -> dict:
    """mock client.get 的 URL 路由：/projects 与 /search 返回不同响应。

    设计假设 #3：--project 项目名解析（GET /projects 匹配 name）与
    人类输出项目名映射共用该列表端点；未预期路径抛错 = 测试失败。
    #246 修正：路径不带 /api/v1 前缀（base_url 已含）——实现若仍传
    /api/v1/... 前缀，本路由抛 AssertionError = RED 预期。
    """
    path = args[0] if args else kwargs.get("path")
    if path == "/projects":
        return _projects_response()
    if path == "/search":
        return _search_response()
    raise AssertionError(f"unexpected GET path: {path!r}")


def _search_call(client):
    """取 GET /search 的调用记录（兼容 CLI 先拉项目列表的多调用形态）。

    #246 修正：路径不带 /api/v1 前缀。
    """
    calls = client.get.await_args_list
    search_calls = [c for c in calls if c.args and c.args[0] == "/search"]
    assert search_calls, "GET /search 未被调用"
    return search_calls[-1]


def _params(call) -> dict:
    """取调用记录的 params（兼容显式 params 与不传两种 GREEN 形态）。"""
    return call.kwargs.get("params") or {}


# ── inkflow search <query>（spec §4，M2）──


class TestSearchQuery:
    """查询命令契约（设计假设 #2-#6）。"""

    def test_search_human_output(self, cli_runner, fake_http_client):
        """命中人类输出：类型徽标 + 项目名 + 标题 + snippet（<mark> → [ ] 替换）。

        设计假设 #4：snippet 中 <mark>/</mark> 替换为 [ ] 方括号；
        项目名经 GET /api/v1/projects 列表映射。
        """
        fake_http_client.get.side_effect = _route_http
        result = cli_runner.invoke(
            app,
            ["龙", "-p", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "[chapter]" in result.output
        assert PROJECT_NAME in result.output
        assert "第 3 章 龙的苏醒" in result.output
        assert "[龙]瞳睁开" in result.output
        assert "[龙]息如雷" in result.output
        assert "<mark>" not in result.output

    def test_search_json_envelope(self, cli_runner, fake_http_client):
        """--json 成功信封：data = SearchResponse 原样（snippet 保留 <mark>）。"""
        fake_http_client.get.side_effect = _route_http
        result = cli_runner.invoke(
            app,
            ["龙", "-p", str(PID), "--json"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        body = data["data"]
        assert body["total"] == 1
        assert body["hits"][0]["entity_type"] == "chapter"
        assert body["hits"][0]["title"] == "第 3 章 龙的苏醒"
        assert "<mark>" in body["hits"][0]["snippet"]
        assert body["query"] == "龙"
        assert body["mode"] == "keyword"
        assert body["project_ids"] == [str(PID)]

    def test_search_http_error_404_not_found(self, cli_runner, fake_http_client):
        """HttpApiError(404) → NOT_FOUND 错误信封 + 退出码 1（F38 错误码映射）。

        设计假设 #6：spec §4「项目不存在 → 退出 1，error = 项目不存在: <name>」。
        """
        fake_http_client.get.side_effect = _http_error(404, "项目不存在: 测试之书")
        result = cli_runner.invoke(
            app,
            ["龙", "-p", str(PID), "--json"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "项目不存在" in data["error"]["message"]

    def test_search_multi_project_multi_type_passthrough(
        self, cli_runner, fake_http_client
    ):
        """多 -p 多 -t + --limit/--offset 透传 GET params（Q3 选择器 + M2）。

        设计假设 #3：project_ids / types 逗号连接成单参数。
        """
        fake_http_client.get.side_effect = _route_http
        result = cli_runner.invoke(
            app,
            [
                "龙",
                "-p",
                str(PID),
                "-p",
                str(PID2),
                "-t",
                "chapter",
                "-t",
                "character",
                "--limit",
                "5",
                "--offset",
                "10",
                "--json",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        params = _params(_search_call(fake_http_client))
        assert params["q"] == "龙"
        assert params["project_ids"] == f"{PID},{PID2}"
        assert params["types"] == "chapter,character"
        assert params["limit"] == "5"
        assert params["offset"] == "10"

    def test_search_mode_semantic_passthrough(self, cli_runner, fake_http_client):
        """--mode semantic 透传（v1.1 AI 检索增强，spec §4）。"""
        fake_http_client.get.side_effect = _route_http
        result = cli_runner.invoke(
            app,
            ["龙", "-p", str(PID), "--mode", "semantic", "--json"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        params = _params(_search_call(fake_http_client))
        assert params["mode"] == "semantic"

    def test_query_missing_exit_2(self, cli_runner, fake_http_client):
        """query 缺失（非 --rebuild）→ 退出码 2（Typer 自动，spec §4）。"""
        result = cli_runner.invoke(app, [], obj=CliContext(json_output=False))
        assert result.exit_code == 2
        fake_http_client.get.assert_not_awaited()

    def test_project_name_resolution(self, cli_runner, fake_http_client):
        """--project 项目名 → GET /projects 匹配 name 解析为 id（父侧裁定）。

        设计假设 #3：列表信封 {"items": [{id, name}]}；解析后查询
        params project_ids = 解析出的 UUID 字符串。
        """
        fake_http_client.get.side_effect = _route_http
        result = cli_runner.invoke(
            app,
            ["龙", "-p", PROJECT_NAME, "--json"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        calls = fake_http_client.get.await_args_list
        assert any(
            c.args and c.args[0] == "/projects" for c in calls
        ), "GET /projects 未被调用（项目名解析）"
        params = _params(_search_call(fake_http_client))
        assert params["project_ids"] == str(PID)


# ── inkflow search --rebuild（spec §4，M13）──


class TestSearchRebuild:
    """--rebuild 命令契约（设计假设 #3/#5，v1.2 经 POST 端点）。"""

    def test_rebuild_human_post_called(self, cli_runner, fake_http_client):
        """--rebuild 缺省项目 → POST /search/rebuild（无 project_id），退出 0。"""
        fake_http_client.post.return_value = {"rebuilt_at": TS, "project_id": None}
        result = cli_runner.invoke(
            app, ["--rebuild"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        call = fake_http_client.post.await_args
        assert call is not None, "POST /search/rebuild 未被调用"
        assert call.args[0] == "/search/rebuild"
        assert "project_id" not in _params(call)

    def test_rebuild_json_envelope(self, cli_runner, fake_http_client):
        """--rebuild --json → 成功信封 data = {"rebuilt_at", "project_id"}。"""
        fake_http_client.post.return_value = {"rebuilt_at": TS, "project_id": None}
        result = cli_runner.invoke(
            app, ["--rebuild", "--json"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"] == {"rebuilt_at": TS, "project_id": None}

    def test_rebuild_with_project_passes_project_id(self, cli_runner, fake_http_client):
        """--rebuild -p X → POST params project_id=str(X)（单项目重建）。"""
        fake_http_client.post.return_value = {
            "rebuilt_at": TS,
            "project_id": str(PID),
        }
        result = cli_runner.invoke(
            app, ["--rebuild", "-p", str(PID)], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        call = fake_http_client.post.await_args
        assert call is not None, "POST /search/rebuild 未被调用"
        assert call.args[0] == "/search/rebuild"
        assert _params(call)["project_id"] == str(PID)


# ── 错误分支全覆盖（F22 QA 补测 2026-08-09：覆盖率 98.47 < 98.5 门禁，F38 各 CLI 同款分支）──


class TestSearchErrorBranches:
    """_run 兜底链 + 项目名解析失败 + 空结果（设计假设 #3/#6，F38 同构）。

    覆盖 src/inkflow/cli/commands/search.py 的错误分支：
    - KernelStartupError → KERNEL_ERROR（ensure_kernel 冷启动失败）
    - ValidationError → VALIDATION_ERROR（pydantic 校验失败）
    - 其余异常 → DB_ERROR（内部错误）
    - 项目名未匹配 → NOT_FOUND + 退出 1
    - 空结果 → 人类输出「📭 无结果」
    """

    def test_kernel_startup_error_maps_kernel_error(self, cli_runner, fake_http_client):
        """ensure_kernel 失败（内核冷启动超时）→ KERNEL_ERROR 信封 + 退出码 1（F38 模式）。"""
        from inkflow.infrastructure.kernel import KernelStartupError

        fake_http_client.get.side_effect = KernelStartupError("内核启动超时")
        result = cli_runner.invoke(
            app, ["龙", "-p", str(PID), "--json"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "KERNEL_ERROR"
        assert "内核启动失败" in data["error"]["message"]

    def test_validation_error_maps_validation_error(self, cli_runner, fake_http_client):
        """pydantic ValidationError → VALIDATION_ERROR 信封 + 退出码 1（F38 模式）。"""
        from pydantic import ValidationError

        fake_http_client.get.side_effect = ValidationError.from_exception_data(
            "SearchResponse", []
        )
        result = cli_runner.invoke(
            app, ["龙", "-p", str(PID), "--json"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_unexpected_exception_maps_db_error(self, cli_runner, fake_http_client):
        """其余异常 → DB_ERROR 信封 + 退出码 1（F38 兜底）。"""
        fake_http_client.get.side_effect = RuntimeError("boom")
        result = cli_runner.invoke(
            app, ["龙", "-p", str(PID), "--json"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"

    def test_project_name_not_found_exit_1(self, cli_runner, fake_http_client):
        """--project 项目名未匹配 → NOT_FOUND 信封 + 退出码 1（设计假设 #3 项目名解析失败）。"""
        fake_http_client.get.side_effect = _route_http  # 列表仅含 PROJECT_NAME
        result = cli_runner.invoke(
            app, ["龙", "-p", "不存在的书", "--json"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "项目不存在: 不存在的书" in data["error"]["message"]

    def test_empty_result_human_output(self, cli_runner, fake_http_client):
        """空结果 → 人类输出「📭 无结果」（spec E5 无命中语义）。"""
        fake_http_client.get.return_value = _search_response(total=0, hits=[])
        result = cli_runner.invoke(
            app, ["龙", "-p", str(PID)], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "无结果" in result.output
