"""#479 CLI 知识图谱提取命令 RED 契约测试（只写测试，不改 src/）。

被测模块: inkflow.cli.commands.knowledge_graph（F48 已交付 graph/relation 子组；
#479 追加 `extract` 命令，spec §5.5.6）。
镜像 tests/cli/test_cli_knowledge_graph.py（F48）形态: CliRunner +
fake_http_client fixture（patch 命令模块命名空间 ensure_kernel / InkFlowHTTPClient）；
路径断言镜像 tests/unit/test_book_cli_paths.py（#458 base_url 双前缀坑）。

【统一契约签名节】（父侧定稿，与 unit 批共享防漂移——mock 断言必须逐字匹配）:

- inkflow knowledge extract --project <uuid> [--method rule|ai|both]
  （cli/commands/knowledge_graph.py 追加，信封/退出码同既有 knowledge 组；
  --method 缺省跟随 settings——CLI 缺省不传 method 键，由端点读 settings）
  - --project 非法 UUID → _parse_uuid(cli_ctx, value, "项目不存在") →
    NOT_FOUND 错误信封 + 退出码 1（镜像既有 _parse_uuid 模式）
  - 请求: POST /knowledge/extract（相对 base_url，严禁 /api/v1 双前缀），
    json = {'project_id': str(pid), 'method': <str>?}
  - 成功 → 信封 data = API 原样（type/status/created/updated/warnings/model/
    skipped_reason，含 created/status）
  - 错误: HttpApiError 422（未配置模型 LLMNotConfiguredError / 运行中守卫）
    → VALIDATION_ERROR 信封 + 退出码 1；404（项目不存在）→ NOT_FOUND 信封
    + 退出码 1（map_http_error，镜像 test_cli_knowledge_graph.py）
  - --method 透传断言: POST body method='ai'（CLI → 端点 →
    svc.extract_for_project(method='ai') 由 API 批断言，本批锁定 body 层）

【RED 预期】命令未注册 → typer「No such command 'extract'.」退出码 2
（断言 exit_code==0 失败 = 预期 RED 形态；守护用例 graph 冒烟当前 PASS）。

【纪律】本文件**不在顶部 import inkflow.cli**（tests/unit 守护契约
test_http_client.py::TestImportSurface::test_no_cli_import_on_http_import
断言 'inkflow.cli' not in sys.modules）——命令模块经 _kg() 执行期
importlib.import_module 惰性加载。

依据: specs/f48-knowledge-graph/spec.md §5.5.6/§5.5.8（v1.2 定稿契约，唯一真相）
+ 父侧定稿统一契约签名节（#479）。
"""

from __future__ import annotations

import importlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


def _kg():
    """执行期惰性 import 命令模块（镜像 tests/unit/test_book_cli_paths.py）。

    不能顶部 import: tests/unit 套件守护契约
    test_http_client.py::TestImportSurface::test_no_cli_import_on_http_import
    断言 'inkflow.cli' not in sys.modules。F48 已交付模块，RED 期只缺 extract 命令。
    """
    return importlib.import_module("inkflow.cli.commands.knowledge_graph")


def _ctx(json_output: bool):
    """构造 CliContext（惰性 import，避免顶部载入 inkflow.cli）。"""
    from inkflow.cli.context import CliContext

    return CliContext(json_output=json_output)


def _http_error(status_code: int, detail: str, code: str | None = None):
    """构造 HttpApiError（惰性 import，保持与兄弟文件一致形态）。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _extract_result(**overrides: object) -> dict:
    """构造测试用提取结果 JSON dict（ExtractionResult.model_dump(mode='json') 等价物）。"""
    defaults = dict(
        type="knowledge_relation",
        status="success",
        skipped_reason=None,
        processed_sources=2,
        skipped_sources=0,
        created=3,
        updated=0,
        warnings=[],
        model=None,
        indexed=False,
        detail={},
    )
    defaults.update(overrides)
    return defaults


def _assert_no_api_v1_prefix(path: str) -> None:
    """#458 load-bearing: 请求路径必须相对 base_url（不含 /api/v1 双前缀）。"""
    assert (
        "/api/v1" not in path
    ), f"请求路径 {path!r} 含 /api/v1 双前缀（base_url 已含 /api/v1）"


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）。"""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（命令模块命名空间），绕过真实内核与 HTTP。

    patch 目标 = 命令模块命名空间（GREEN 后命令模块 from-import 绑定自身命名空间，
    F19 #77 先例）；RED 期模块存在只缺 extract 命令 → 本 fixture 正常，命令未注册
    由 typer 退出码 2 暴露（预期 RED 形态）。
    """
    kg = _kg()
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch.object(kg, "ensure_kernel", AsyncMock(return_value=fake_handle)),
        patch.object(kg, "InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


class TestKnowledgeExtractCmd:
    """inkflow knowledge extract --project <uuid> [--method rule|ai|both]（spec §5.5.6）。"""

    def test_extract_json_success_with_method_ai(self, cli_runner, fake_http_client):
        """extract --method ai → 成功信封 data 含 created/status；POST 路径相对
        base_url + body method='ai' 透传（#458 双前缀防护）。"""
        fake_http_client.post.return_value = _extract_result()
        result = cli_runner.invoke(
            _kg().app,
            ["extract", "--project", str(PID), "--method", "ai"],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["created"] == 3
        assert data["data"]["status"] == "success"
        fake_http_client.post.assert_awaited_once()
        call = fake_http_client.post.await_args
        path = call.args[0]
        assert path == "/knowledge/extract"
        _assert_no_api_v1_prefix(path)
        body = call.kwargs["json"]
        assert body["project_id"] == str(PID)
        assert body["method"] == "ai"

    def test_extract_json_default_method_no_method_key(
        self, cli_runner, fake_http_client
    ):
        """--method 缺省 → body 不含 method 键（跟随 settings 由端点读）。"""
        fake_http_client.post.return_value = _extract_result()
        result = cli_runner.invoke(
            _kg().app,
            ["extract", "--project", str(PID)],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert body["project_id"] == str(PID)
        assert "method" not in body

    def test_extract_llm_not_configured_422(self, cli_runner, fake_http_client):
        """服务端 422（未配置模型，LLMNotConfiguredError 映射）→ VALIDATION_ERROR
        信封 + 退出码 1。"""
        fake_http_client.post.side_effect = _http_error(
            422, "未配置大模型，无法进行 AI 提取"
        )
        result = cli_runner.invoke(
            _kg().app,
            ["extract", "--project", str(PID), "--method", "ai"],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "未配置" in data["error"]["message"]

    def test_extract_running_guard_422(self, cli_runner, fake_http_client):
        """服务端 422（运行中守卫「提取正在进行」）→ VALIDATION_ERROR + 退出码 1。"""
        fake_http_client.post.side_effect = _http_error(422, "提取正在进行")
        result = cli_runner.invoke(
            _kg().app,
            ["extract", "--project", str(PID)],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "提取正在进行" in data["error"]["message"]

    def test_extract_project_not_found_404(self, cli_runner, fake_http_client):
        """服务端 404（项目不存在）→ NOT_FOUND 信封 + 退出码 1。"""
        fake_http_client.post.side_effect = _http_error(404, "项目不存在")
        result = cli_runner.invoke(
            _kg().app,
            ["extract", "--project", str(PID)],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert data["error"]["message"] == "项目不存在"

    def test_extract_invalid_uuid_not_found(self, cli_runner, fake_http_client):
        """--project 非法 UUID → NOT_FOUND 信封「项目不存在」+ 退出码 1
        （_parse_uuid 模式，不调 POST）。"""
        result = cli_runner.invoke(
            _kg().app,
            ["extract", "--project", "not-a-uuid"],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert data["error"]["message"] == "项目不存在"
        fake_http_client.post.assert_not_awaited()


class TestKnowledgeExtractGuardian:
    """守护用例（当前 PASS）——既有 knowledge graph 命令冒烟，验证测试夹具可用。"""

    def test_graph_smoke_guardian(self, cli_runner, fake_http_client):
        """graph --json → 成功信封 {nodes, edges}（F48 已交付，RED 期即 PASS）。"""
        fake_http_client.get.return_value = {"nodes": [], "edges": []}
        result = cli_runner.invoke(
            _kg().app,
            ["graph", str(PID)],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"] == {"nodes": [], "edges": []}
