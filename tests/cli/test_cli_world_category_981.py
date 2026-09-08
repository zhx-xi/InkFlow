"""#981 RED 契约测试 — `inkflow world category add` CLI（新增分类）。

覆盖点（依据契约书 red-981-a-world.md）：
1. 成功 --json：信封 data 为分类 dict；post 恰调用一次；断言 path 为
   /projects/{PID}/world-categories 且 body 为 {name, kind: geo}（默认 kind 显式发送）。
2. 成功 --kind abstract：body 中 kind 值等于 abstract。
3. 人类模式成功：exit 0 + stdout 含 分类创建成功、name、kind。
4. 非法 project-id：exit 1 + NOT_FOUND（--json 信封 code 断言）。
5. 422 同名（人类）：exit 1 + 输出含 detail 原文。
6. 422 同名（--json）：exit 1 + 信封 ok=false、error.code 为 VALIDATION_ERROR、
   error.message 含 detail。
7. --kind 非法值（terrain）：exit 2（click 参数校验）。
8. 守护：既有 `inkflow world categories --project-id <pid>` 汇总仍工作
   （mock get 返回 items，exit 0）——锁回归。

── RED 形态说明 ────────────────────────────────────────────────
命令模块 category_app 子组 + add 命令尚未实现，invoke category add 会
得到 click No such command，exit 2。用例 1-6 在 exit_code 断言处 FAIL
（干净断言，不触发 json.loads 二次错误）；用例 7 期望 exit 2 与
No such command 巧合一致，可能 PASS；用例 8 守护（categories 既有命令，
patch 已生效）应 PASS。
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


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 默认混合输出，与既有 world 测试同法）。"""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP。

    patch 目标为命令模块命名空间（GREEN 后 category_app 自模块内导入绑定）。
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
    """构造 HttpApiError（lazy import：RED 阶段 http 包未实现）。

    仅在用例体调用时执行，不改变 RED 形态；当命令不存在时用例先行在
    exit_code 断言处 FAIL，绝不触达本函数，保证干净 RED。
    """
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _make_category(**overrides) -> dict:
    """构造测试用 world-category JSON dict（分类新建成功响应 201 模型）。"""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="背景设定",
        kind="geo",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


class TestWorldCategoryAdd:
    """`inkflow world category add` 契约测试（#981）。"""

    def test_add_json_envelope(self, cli_runner, fake_http_client):
        """成功 --json：信封 + HTTP 调用断言（默认 kind=geo 显式发送）。"""
        fake_http_client.post.return_value = _make_category(name="背景设定")
        result = cli_runner.invoke(
            app,
            ["category", "add", "--project-id", str(PID), "--name", "背景设定"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "背景设定"
        assert data["data"]["kind"] == "geo"
        fake_http_client.post.assert_awaited_once()
        url = fake_http_client.post.await_args.args[0]
        body = fake_http_client.post.await_args.kwargs["json"]
        assert url == f"/projects/{PID}/world-categories"
        assert body == {"name": "背景设定", "kind": "geo"}

    def test_add_kind_abstract(self, cli_runner, fake_http_client):
        """成功 --kind abstract → body 中 kind 值等于 abstract。"""

        fake_http_client.post.return_value = _make_category(
            name="背景设定", kind="abstract"
        )
        result = cli_runner.invoke(
            app,
            [
                "category",
                "add",
                "--project-id",
                str(PID),
                "--name",
                "背景设定",
                "--kind",
                "abstract",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert body["kind"] == "abstract"

    def test_add_human(self, cli_runner, fake_http_client):
        """人类模式成功 → stdout 含 分类创建成功、name、kind。"""
        fake_http_client.post.return_value = _make_category(
            name="背景设定", kind="geo"
        )
        result = cli_runner.invoke(
            app,
            ["category", "add", "--project-id", str(PID), "--name", "背景设定"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "分类创建成功" in result.output
        assert "背景设定" in result.output
        assert "geo" in result.output

    def test_add_invalid_project_id(self, cli_runner, fake_http_client):
        """非法 project-id → exit 1 + NOT_FOUND（指令层 _parse_uuid 拦截）。"""
        result = cli_runner.invoke(
            app,
            ["category", "add", "--project-id", "not-a-uuid", "--name", "背景设定"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_add_name_conflict_human(self, cli_runner, fake_http_client):
        """422 同名（人类）：exit 1 + 输出含 detail 原文。"""
        fake_http_client.post.side_effect = _http_error(
            422, "分类名已存在: 背景设定"
        )
        result = cli_runner.invoke(
            app,
            ["category", "add", "--project-id", str(PID), "--name", "背景设定"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 1
        assert "分类名已存在" in result.output

    def test_add_name_conflict_json(self, cli_runner, fake_http_client):
        """422 同名（--json）：exit 1 + 信封 VALIDATION_ERROR + message 含 detail。"""
        fake_http_client.post.side_effect = _http_error(
            422, "分类名已存在: 背景设定"
        )
        result = cli_runner.invoke(
            app,
            ["category", "add", "--project-id", str(PID), "--name", "背景设定"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "分类名已存在" in data["error"]["message"]

    def test_add_invalid_kind(self, cli_runner, fake_http_client):
        """--kind 非法值 terrain → click 参数校验 exit 2（不触达 HTTP）。"""
        result = cli_runner.invoke(
            app,
            [
                "category",
                "add",
                "--project-id",
                str(PID),
                "--name",
                "背景设定",
                "--kind",
                "terrain",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()


class TestWorldCategoriesGuard:
    """守护：既有 `inkflow world categories` 汇总不被 #981 改造破坏（锁回归）。"""

    def test_categories_regression(self, cli_runner, fake_http_client):
        """categories --json → 类别计数列表信封（mock get 返回 items，exit 0）。"""
        fake_http_client.get.return_value = {
            "items": [{"category": "设定", "count": 3}],
            "total": 1,
        }
        result = cli_runner.invoke(
            app,
            ["categories", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"][0] == {"category": "设定", "count": 3}
