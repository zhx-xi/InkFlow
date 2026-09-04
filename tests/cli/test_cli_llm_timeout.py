"""#926 CLI 族 per-request timeout RED 契约测试（契约 §4 文件 A）.

覆盖（仅新建本文件，禁改任何既有文件与 src/）：
  - §4-A 参数化【R】13 个 LLM 长任务 CLI 调用点：`client.post(...)` 必须携带
    `timeout=300.0`（LLM_TASK_TIMEOUT）。当前实现各调用点 `client.post(path, json=...)`
    不带 per-request timeout（§0 根因表）→ `call.kwargs.get("timeout") is None`
    → 本族用例必 FAIL（RED）。
  - §4-A-R14【R】端到端超时语义：真实传输层（MockTransport）抛 httpx 读超时 →
    命令错误信封 `error.code` 应为 "TIMEOUT"。当前 `httpx.ReadTimeout` 从真
    AsyncClient 抛出 → `outline._run` except Exception → `{"code":"DB_ERROR"}` →
    FAIL（恰为本缺陷，§0-根因表 #3）。
  - §4-A-G1/2/3【G】守护：outline create / outline list / vector status 等纯 CRUD
    调用（GET/POST）不得被 300s 覆盖，`kwargs.get("timeout") is None`。

fixture 镜像 tests/cli/test_cli_outline_http.py:46-73（patch 命令模块命名空间
ensure_kernel + InkFlowHTTPClient autospec；AsyncMock 子 mock 自动支持 async
上下文管理器）。A-R14 真实传输层轨镜像 backend/tests/unit/api/routers/
test_http_client.py:139-155 `_mock_http` 捕获形态。

纪律：断言超时值一律字面 300.0；失败原因必须是 timeout 断言不匹配，而非
未配置 mock 返回 MagicMock 被 json.dump 炸出的 TypeError。
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from inkflow.cli.commands import audit_chapter as audit_chapter_mod
from inkflow.cli.commands import book_cmd as book_cmd_mod
from inkflow.cli.commands import chapter as chapter_mod
from inkflow.cli.commands import character as character_mod
from inkflow.cli.commands import extract as extract_mod
from inkflow.cli.commands import knowledge_graph as knowledge_graph_mod
from inkflow.cli.commands import memory_cmd as memory_cmd_mod
from inkflow.cli.commands import outline as outline_mod
from inkflow.cli.commands import style as style_mod
from inkflow.cli.commands import vector as vector_mod
from inkflow.cli.commands import world as world_mod
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")

# 需要 patch 的命令模块（from-import ensure_kernel + InkFlowHTTPClient 后绑定自身命名空间）。
_CLI_MODULES = (
    "outline",
    "extract",
    "world",
    "character",
    "knowledge_graph",
    "memory_cmd",
    "style",
    "chapter",
    "audit_chapter",
    "vector",
    "book_cmd",
)


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock 全部 CLI LLM 长任务命令模块的 ensure_kernel + InkFlowHTTPClient.

    patch 目标 = 各命令模块自身命名空间（GREEN 后命令模块 from-import 绑定自身
    命名空间，F19 #77 先例）。所有模块共享同一 mock_client 实例，`async with
    client:` 由 AsyncMock 子 mock 自动支持。返回 mock_client 供用例配置
    `.post.return_value` / `.get.return_value` 并读取 `.post.await_args`。
    """
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    mock_client = AsyncMock()
    with ExitStack() as stack:
        for mod in _CLI_MODULES:
            stack.enter_context(
                patch(
                    f"inkflow.cli.commands.{mod}.ensure_kernel",
                    AsyncMock(return_value=fake_handle),
                )
            )
            mock_cls = stack.enter_context(
                patch(
                    f"inkflow.cli.commands.{mod}.InkFlowHTTPClient",
                    autospec=True,
                )
            )
            mock_cls.return_value = mock_client
        yield mock_client


# ---------------------------------------------------------------------------
# §4-A 参数化【R】13 用例：test_cli 长任务调用点 post 需带 timeout=300.0
# ---------------------------------------------------------------------------

_LONG_TASK_CASES = [
    pytest.param(
        outline_mod.app,
        ["generate", "--project-id", str(PID)],
        "/outlines/generate",
        {},
        None,
        id="A1-outline-generate-R",
    ),
    pytest.param(
        extract_mod.app,
        ["run", "--project-id", str(PID), "--type", "character", "--text", "样本文本"],
        "/extract",
        {},
        None,
        id="A2-extract-run-R",
    ),
    pytest.param(
        world_mod.app,
        ["extract", "--project-id", str(PID), "--text", "样本"],
        "/world-settings/extract",
        {},
        None,
        id="A3-world-extract-R",
    ),
    pytest.param(
        character_mod.app,
        ["extract", "--project-id", str(PID), "--text", "样本"],
        "/characters/extract",
        {},
        None,
        id="A4-character-extract-R",
    ),
    pytest.param(
        knowledge_graph_mod.app,
        ["extract", "--project", str(PID)],
        "/knowledge/extract",
        {},
        None,
        id="A5-knowledge-extract-R",
    ),
    pytest.param(
        memory_cmd_mod.app,
        ["summarize", "--project-id", str(PID)],
        "/agent/memory/summarize",
        {},
        None,
        id="A6-memory-summarize-R",
    ),
    pytest.param(
        style_mod.app,
        ["analyze", "--project-id", str(PID), "--text", "样本"],
        f"/projects/{PID}/style/analyze",
        {},
        None,
        id="A7-style-analyze-R",
    ),
    pytest.param(
        chapter_mod.chapter_app,
        ["summary", "refresh", "--id", str(CID)],
        f"/context/chapters/{CID}/summary/refresh",
        {},
        None,
        id="A8-chapter-summary-refresh-R",
    ),
    pytest.param(
        audit_chapter_mod.app,
        ["chapter", str(CID), "-p", str(PID)],
        f"/projects/{PID}/chapters/{CID}/audit",
        {},
        None,
        id="A9-audit-chapter-R",
    ),
    pytest.param(
        vector_mod.app,
        ["reindex", "--project-id", str(PID)],
        f"/projects/{PID}/vector/reindex",
        {},
        {"stale": False},
        id="A10-vector-reindex-R",
    ),
    pytest.param(
        book_cmd_mod.plan_app,
        ["start", "剑派复兴", "--project", str(PID)],
        "/agent/books/planner",
        {},
        None,
        id="A11-book-plan-start-R",
    ),
    pytest.param(
        book_cmd_mod.plan_app,
        ["respond", "sess-1", "回答"],
        "/agent/books/planner/sess-1/respond",
        {},
        None,
        id="A12-book-plan-respond-R",
    ),
]


class TestCliLongTaskPerRequestTimeout:
    """§4-A【R】：11 个 CLI LLM 长任务调用点 per-request timeout==300.0.

    契约依据：contract-926.md §4-A 参数化表（每条用例的 A 编号/端点见
    pytest.param id）。RED 现状：各调用点 `client.post(path, json=...)` 不带
    timeout → `call.kwargs.get("timeout")` 为 None ≠ 300.0 → 全部 FAIL。
    GREEN 后各调用点补 `timeout=LLM_TASK_TIMEOUT`（=300.0）→ 全部 PASS。
    """

    @pytest.mark.parametrize(
        "app,argv,expected_path,post_ret,get_ret", _LONG_TASK_CASES
    )
    def test_long_task_post_has_300s_timeout(
        self,
        cli_runner,
        fake_http_client,
        app,
        argv,
        expected_path,
        post_ret,
        get_ret,
    ):
        """【R】LLM 长任务 CLI 调用点 post 必须带 timeout=300.0（其余 kwargs 不锁）。"""
        # 先配置 mock 返回值，防止未配置 AsyncMock 返回 MagicMock 被 json.dump 炸出假红。
        fake_http_client.post.return_value = post_ret
        if get_ret is not None:
            fake_http_client.get.return_value = get_ret

        cli_runner.invoke(app, argv, obj=CliContext(json_output=True))

        call = fake_http_client.post.await_args
        assert call is not None, "post 未被调用（argv/命令签名可能有误）"
        assert call.args[0] == expected_path
        # 【R】当前无 timeout → None != 300.0 → FAIL；GREEN 后 == 300.0 → PASS。
        assert call.kwargs.get("timeout") == 300.0

    def test_book_plan_auto_both_posts_use_300s_timeout(
        self, cli_runner, fake_http_client
    ):
        """【R】A13：book plan auto 两次 post（planner + respond）均带 timeout=300.0."""
        fake_http_client.post.return_value = {"session_id": "sess-1"}
        cli_runner.invoke(
            book_cmd_mod.plan_app,
            ["auto", "构思", "--project", str(PID)],
            obj=CliContext(json_output=True),
        )
        calls = fake_http_client.post.await_args_list
        assert len(calls) == 2, "auto 应发生两次 post"
        # 第二次 post 路径使用第一次返回的 session_id。
        assert calls[0].args[0] == "/agent/books/planner"
        assert calls[1].args[0] == "/agent/books/planner/sess-1/respond"
        for call in calls:
            # 【R】当前两次 post 均无 timeout → None != 300.0 → FAIL。
            assert call.kwargs.get("timeout") == 300.0


# ---------------------------------------------------------------------------
# §4-A-R14【R】：真实传输层超时 → 命令错误信封 code == "TIMEOUT"
# ---------------------------------------------------------------------------


@pytest.fixture
def timeout_transport():
    """A-R14 真实传输层轨：patch outline.ensure_kernel + httpx.AsyncClient.

    捕获 patch 前的原类（_real_async_client），工厂构造
    `AsyncClient(transport=MockTransport(handler))`——handler 抛
    httpx.ReadTimeout（TimeoutException 子类），模拟服务端读超时。
    镜像 backend/tests/unit/api/routers/test_http_client.py:139-155 `_mock_http`。
    RED 现状：ReadTimeout 从真 client 抛出 → outline._run except Exception →
    DB_ERROR 信封（恰为本缺陷）；GREEN 后 `_send` 转 HttpApiError(0, ..., "TIMEOUT")
    → map_http_error → "TIMEOUT"。
    """
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )

    def _handler(request):
        raise httpx.ReadTimeout("read timed out", request=request)

    _real_async_client = httpx.AsyncClient  # patch 前捕获原类（防无限递归）

    def _factory(**kwargs):
        return _real_async_client(transport=httpx.MockTransport(_handler), **kwargs)

    with (
        patch(
            "inkflow.cli.commands.outline.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.infrastructure.http.client.httpx.AsyncClient", new=_factory),
    ):
        yield


class TestCliTimeoutEndToEndSemantics:
    """§4-A-R14【R】：超时端到端语义——命令错误信封应为 TIMEOUT 而非 DB_ERROR."""

    def test_generate_timeout_envelope_code_timeout(self, cli_runner, timeout_transport):
        """【R】outline generate 遇读超时 → envelope code=="TIMEOUT" 且含「超时」.

        契约依据：contract-926.md §4-A-R14 + §0 根因表 #3、§1-D1。文案断言仅用
        子串（"超时" 命中、不含 "DB_ERROR"），不锁全句逐字（GREEN 侧 §1-D3 定稿）。
        """
        result = cli_runner.invoke(
            outline_mod.app,
            ["generate", "--project-id", str(PID), "--name", "x"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        error = data["error"]
        # 【R】当前为 "DB_ERROR" → 本断言 FAIL；GREEN 后 "TIMEOUT" → PASS。
        assert error["code"] == "TIMEOUT"
        assert error["message"]
        assert "超时" in error["message"]
        assert "DB_ERROR" not in error["message"]


# ---------------------------------------------------------------------------
# §4-A-G1/2/3【G】守护：纯 CRUD 调用不得被 300s 覆盖
# ---------------------------------------------------------------------------


class TestCliCrudTimeoutGuard:
    """§4-A-G1/2/3【G】：CRUD 调用（GET/POST）timeout 保持 None。

    契约依据：contract-926.md §4-A-G1/2/3 + §1-D5（纯 CRUD 30s 合理，issue body
    明示）。现即应 PASS（守护误伤）；若 GREEN 侧误给 CRUD 加 300s 覆盖则转红。
    """

    def test_outline_create_post_timeout_none(self, cli_runner, fake_http_client):
        """【G】A-G1：outline create（POST /projects/{pid}/outlines）timeout 为 None."""
        fake_http_client.post.return_value = {}
        cli_runner.invoke(
            outline_mod.app,
            ["create", "--project-id", str(PID), "--name", "x"],
            obj=CliContext(json_output=True),
        )
        call = fake_http_client.post.await_args
        assert call is not None
        assert call.args[0] == f"/projects/{PID}/outlines"
        assert call.kwargs.get("timeout") is None

    def test_outline_list_get_timeout_none(self, cli_runner, fake_http_client):
        """【G】A-G2：outline list（GET /projects/{pid}/outlines）timeout 为 None."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        cli_runner.invoke(
            outline_mod.app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        call = fake_http_client.get.await_args
        assert call is not None
        assert call.args[0] == f"/projects/{PID}/outlines"
        assert call.kwargs.get("timeout") is None

    def test_vector_status_get_timeout_none(self, cli_runner, fake_http_client):
        """【G】A-G3：vector status（GET /projects/{pid}/vector/status）timeout 为 None."""
        fake_http_client.get.return_value = {"stale": False}
        cli_runner.invoke(
            vector_mod.app,
            ["status", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        call = fake_http_client.get.await_args
        assert call is not None
        assert call.args[0] == f"/projects/{PID}/vector/status"
        assert call.kwargs.get("timeout") is None
