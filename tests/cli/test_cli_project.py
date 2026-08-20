"""CLI 项目命令集成测试 — 有状态 fake client（内存项目表）模拟内核 HTTP JSON。

测试范围：inkflow project create/list/get/delete/restore, serve。
需 pytest marker: @pytest.mark.project

F38 改造（#169）：mock 目标从 domain Service 迁移到 ensure_kernel +
InkFlowHTTPClient（HTTP JSON 响应）；create_tables/session 相关 patch 已移除。
原 isolated_db（临时 SQLite）语义由「有状态 fake client」内存版替代：
post 追加并返回 dict、get 按 id 查（404 抛 HttpApiError）、list 返回全部
（search 过滤）、delete 标记 is_deleted、restore 恢复。端点路径与响应形态
以已 GREEN 的 API 路由为准（POST/GET/DELETE /api/v1/projects、POST
/projects/{id}/restore；list 返回 {"items", "total", "offset", "limit"}）。

── RED 形态说明 ────────────────────────────────────────────────
命令模块仍直连 domain Service（未改造），patch 目标
inkflow.cli.commands.project.ensure_kernel / .InkFlowHTTPClient 不存在
→ 全部 CRUD 用例 fixture setup AttributeError（同根因，预期 RED）；
serve 两用例（--help / 真实子进程冒烟）不依赖该 mock → PASS。
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app

from .conftest import _parse_json_output

runner = CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP。

    有状态 fake：内存项目表模拟内核 HTTP JSON 语义（isolated_db 内存版）。
    - POST /projects（json body）→ 追加并返回项目 dict（id 从 1 递增）
    - POST /projects/{id}/restore → 恢复软删除并返回项目 dict
    - GET /projects?search= → {"items", "total", "offset", "limit"}
    - GET /projects/{id} → 项目 dict；不存在 → HttpApiError(404)
    - DELETE /projects/{id} → 标记 is_deleted（返回 None，204 语义）
    patch 目标 = 命令模块命名空间（GREEN 后命令模块 from-import 绑定自身）。
    """
    with (
        patch(
            "inkflow.cli.commands.project.ensure_kernel",
            AsyncMock(
                return_value=SimpleNamespace(
                    port=38291,
                    token="test-token",
                    pid=1,
                    version="0.1.0",
                    started_at="",
                    reused=True,
                )
            ),
        ),
        patch(
            "inkflow.cli.commands.project.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        # lazy import：RED 阶段 inkflow.infrastructure.http 未实现（patch 先行
        # 失败为预期形态，此行使 GREEN 后真实错误类可用）
        from inkflow.infrastructure.http import HttpApiError

        store: dict[str, dict] = {}
        counter = {"n": 0}

        async def _post(path, **kwargs):
            parsed = urlparse(path)
            if parsed.path.endswith("/restore"):
                item_id = parsed.path.split("/")[-2]
                item = store.get(item_id)
                if item is None:
                    raise HttpApiError(status_code=404, detail="项目不存在")
                item["is_deleted"] = False
                return item
            counter["n"] += 1
            item_id = str(counter["n"])
            data = dict(kwargs.get("json") or {})
            item = {
                "id": item_id,
                "name": data.get("name", ""),
                "genre": data.get("genre", "其他"),
                "language": data.get("language", "zh-CN"),
                "target_words": data.get("target_words", 0),
                "is_deleted": False,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
            store[item_id] = item
            return item

        async def _get(path, **kwargs):
            parsed = urlparse(path)
            params = dict(kwargs.get("params") or {})
            params.update({k: v[0] for k, v in parse_qs(parsed.query).items()})
            if parsed.path == "/projects":
                items = [it for it in store.values() if not it["is_deleted"]]
                search = params.get("search")
                if search:
                    items = [it for it in items if search in it["name"]]
                return {"items": items, "total": len(items), "offset": 0, "limit": 50}
            item = store.get(parsed.path.rsplit("/", 1)[-1])
            if item is None or item["is_deleted"]:
                raise HttpApiError(status_code=404, detail="项目不存在")
            return item

        async def _delete(path, **kwargs):
            item = store.get(urlparse(path).path.rsplit("/", 1)[-1])
            if item is None:
                raise HttpApiError(status_code=404, detail="项目不存在")
            item["is_deleted"] = True

        mock_instance = AsyncMock()
        mock_instance.post.side_effect = _post
        mock_instance.get.side_effect = _get
        mock_instance.delete.side_effect = _delete
        mock_cls.return_value = mock_instance
        yield mock_instance


# ── project create ──────────────────────────────────────────────


@pytest.mark.project
def test_create_output(fake_http_client):
    result = runner.invoke(
        app, ["project", "create", "--name", "测试小说", "--genre", "玄幻"]
    )
    assert result.exit_code == 0, result.output
    assert "✅" in result.output
    assert "测试小说" in result.output


@pytest.mark.project
def test_create_json_output(fake_http_client):
    result = runner.invoke(
        app, ["--json", "project", "create", "--name", "星辰", "--genre", "科幻"]
    )
    assert result.exit_code == 0, result.output
    data = _parse_json_output(result.output)
    assert data["name"] == "星辰"


@pytest.mark.project
def test_create_with_target_words(fake_http_client):
    result = runner.invoke(
        app, ["--json", "project", "create", "--name", "长篇", "-w", "300000"]
    )
    assert result.exit_code == 0
    data = _parse_json_output(result.output)
    assert data["target_words"] == 300000


# ── project list ────────────────────────────────────────────────


@pytest.mark.project
def test_list_empty(fake_http_client):
    result = runner.invoke(app, ["project", "list"])
    assert result.exit_code == 0
    assert "暂无项目" in result.output


@pytest.mark.project
def test_list_with_projects(fake_http_client):
    runner.invoke(app, ["project", "create", "--name", "A项目", "--genre", "玄幻"])
    runner.invoke(app, ["project", "create", "--name", "B项目", "--genre", "科幻"])
    result = runner.invoke(app, ["project", "list"])
    assert result.exit_code == 0
    assert "2 个项目" in result.output
    assert "A项目" in result.output


@pytest.mark.project
def test_list_json_output(fake_http_client):
    runner.invoke(app, ["project", "create", "--name", "唯一", "--genre", "悬疑"])
    result = runner.invoke(app, ["--json", "project", "list"])
    assert result.exit_code == 0
    data = _parse_json_output(result.output)
    assert isinstance(data, list) and len(data) == 1


@pytest.mark.project
def test_list_search(fake_http_client):
    runner.invoke(app, ["project", "create", "--name", "玄幻大作", "--genre", "玄幻"])
    runner.invoke(app, ["project", "create", "--name", "科幻巨作", "--genre", "科幻"])
    result = runner.invoke(app, ["--json", "project", "list", "--search", "科幻"])
    data = _parse_json_output(result.output)
    assert len(data) == 1
    assert data[0]["name"] == "科幻巨作"


# ── project get ─────────────────────────────────────────────────


@pytest.mark.project
def test_get_existing(fake_http_client):
    runner.invoke(app, ["project", "create", "--name", "详情测试", "--genre", "仙侠"])
    result = runner.invoke(app, ["project", "get", "--id", "1"])
    assert result.exit_code == 0, result.output
    assert "详情测试" in result.output


@pytest.mark.project
def test_get_json_output(fake_http_client):
    runner.invoke(app, ["project", "create", "--name", "JSON测试", "--genre", "都市"])
    result = runner.invoke(app, ["--json", "project", "get", "--id", "1"])
    assert result.exit_code == 0
    data = _parse_json_output(result.output)
    assert data["name"] == "JSON测试"


@pytest.mark.project
def test_get_not_found(fake_http_client):
    result = runner.invoke(app, ["project", "get", "--id", "999"])
    assert result.exit_code == 1
    assert "项目不存在" in result.output


# ── project delete ──────────────────────────────────────────────


@pytest.mark.project
def test_delete_soft(fake_http_client):
    runner.invoke(app, ["project", "create", "--name", "删除测试", "--genre", "历史"])
    result = runner.invoke(app, ["project", "delete", "--id", "1", "--force"])
    assert result.exit_code == 0, result.output
    assert "已删除" in result.output
    lr = runner.invoke(app, ["--json", "project", "list"])
    assert len(_parse_json_output(lr.output)) == 0


@pytest.mark.project
def test_delete_not_found(fake_http_client):
    result = runner.invoke(app, ["project", "delete", "--id", "999", "--force"])
    assert result.exit_code == 1
    # 🔒 强化（#524）：人类模式错误必须向用户说明失败原因（stderr 含「不存在」）
    assert "不存在" in (result.output + result.stderr)


@pytest.mark.project
def test_delete_permanent(fake_http_client):
    runner.invoke(app, ["project", "create", "--name", "永久删除", "--genre", "武侠"])
    result = runner.invoke(
        app, ["project", "delete", "--id", "1", "--permanent", "--force"]
    )
    assert result.exit_code == 0
    assert "永久删除" in result.output


# ── project restore ─────────────────────────────────────────────


@pytest.mark.project
def test_restore_after_delete(fake_http_client):
    runner.invoke(app, ["project", "create", "--name", "恢复测试", "--genre", "游戏"])
    runner.invoke(app, ["project", "delete", "--id", "1", "--force"])
    result = runner.invoke(app, ["project", "restore", "--id", "1"])
    assert result.exit_code == 0, result.output
    assert "已恢复" in result.output
    lr = runner.invoke(app, ["--json", "project", "list"])
    assert len(_parse_json_output(lr.output)) == 1


@pytest.mark.project
def test_restore_not_found(fake_http_client):
    result = runner.invoke(app, ["project", "restore", "--id", "999"])
    assert result.exit_code == 1
    assert "不存在" in (result.output + result.stderr)


# ── serve ───────────────────────────────────────────────────────


def test_serve_help():
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output
    assert "启动" in result.output


@pytest.mark.skipif(
    "CI" in os.environ or os.name != "nt",
    reason="serve smoke test requires local environment",
)
def test_serve_smoke(tmp_path):
    """serve 冒烟：读 INKFLOW_READY 拿 token → 带 token /health 200、无 token 401（仅本地）."""
    import http.client

    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    env = os.environ.copy()
    env["INKFLOW_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/test.db"

    proc = subprocess.Popen(
        [sys.executable, "-m", "inkflow", "serve", "--port", "18765"],
        cwd=backend_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # stdout 逐行入队：Windows PIPE readline 阻塞，必须线程化避免卡死主线程轮询
        ready_queue: queue.Queue[str] = queue.Queue()

        def _read_stdout() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                ready_queue.put(line.decode(errors="replace"))

        threading.Thread(target=_read_stdout, daemon=True).start()

        # 1) 轮询 INKFLOW_READY 交付行（~6s 超时），解析 token（§2.7 M1 契约）
        ready_line: str | None = None
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            try:
                line = ready_queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if line.startswith("INKFLOW_READY "):
                ready_line = line
                break
        assert (
            ready_line is not None
        ), "server did not emit INKFLOW_READY within 6 seconds"
        ready = json.loads(ready_line[len("INKFLOW_READY ") :].strip())
        assert {"port", "token", "pid", "version"} <= set(ready)
        assert ready["port"] == 18765
        token = ready["token"]

        def _health(token_to_send: str | None) -> tuple[int, str]:
            conn = http.client.HTTPConnection("127.0.0.1", 18765, timeout=2)
            headers = {"X-InkFlow-Token": token_to_send} if token_to_send else {}
            conn.request("GET", "/health", headers=headers)
            resp = conn.getresponse()
            body = resp.read().decode()
            conn.close()
            return resp.status, body

        # 2) 带 token 请求 /health → 200 且 body 含 "status":"ok"
        #    （服务就绪可能稍晚于 READY 行，保留轮询）
        status: int | None = None
        body: str | None = None
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            try:
                status, body = _health(token)
                if status == 200 and '"status":"ok"' in body:
                    break
            except (ConnectionRefusedError, OSError):
                pass
            time.sleep(0.3)
        assert (
            status == 200 and '"status":"ok"' in body
        ), f"health with token failed: status={status} body={body}"

        # 3) 反向断言（Q2=B 核心语义）：无 token 请求 /health → 401
        status_no_token, body_no_token = _health(None)
        assert (
            status_no_token == 401
        ), f"expected 401 without token, got {status_no_token}: {body_no_token}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# ── 内核启动失败 / 错误信封 / 无 force 交互（迁移自 test_cli_project_mock.py，#281 T3 合并）──


@pytest.mark.project
def test_create_kernel_startup_error(fake_http_client):
    """ensure_kernel 失败（内核冷启动超时）→ KERNEL_ERROR 信封 + 退出码 1（F38 spec §5.3）。"""
    from inkflow.infrastructure.kernel import KernelStartupError

    with patch(
        "inkflow.cli.commands.project.ensure_kernel",
        AsyncMock(side_effect=KernelStartupError("启动超时")),
    ):
        result = runner.invoke(app, ["--json", "project", "create", "--name", "测试"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["error"]["code"] == "KERNEL_ERROR"
    assert "内核启动失败" in data["error"]["message"]


@pytest.mark.project
def test_get_not_found_json(fake_http_client):
    """get 不存在项目（--json）→ 退出码 1 + 错误信封 NOT_FOUND。"""
    result = runner.invoke(app, ["--json", "project", "get", "--id", "999"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["error"]["code"] == "NOT_FOUND"


@pytest.mark.project
def test_delete_without_force_prompts(fake_http_client):
    """delete 无 --force → 交互确认，回答 n 取消（不调用 delete）。"""
    result = runner.invoke(app, ["project", "delete", "--id", "1"], input="n\n")
    assert result.exit_code == 0
    assert "取消" in result.output
    fake_http_client.delete.assert_not_awaited()
