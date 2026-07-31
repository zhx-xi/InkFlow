"""CLI 项目命令集成测试 — CliRunner + 临时 SQLite。

测试范围：inkflow project create/list/get/delete/restore, serve。
需 pytest marker: @pytest.mark.project
"""

import os
import subprocess
import sys
import time

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app

from .conftest import _parse_json_output

runner = CliRunner()


# ── project create ──────────────────────────────────────────────


@pytest.mark.project
def test_create_output(isolated_db):
    result = runner.invoke(
        app, ["project", "create", "--name", "测试小说", "--genre", "玄幻"]
    )
    assert result.exit_code == 0, result.output
    assert "✅" in result.output
    assert "测试小说" in result.output


@pytest.mark.project
def test_create_json_output(isolated_db):
    result = runner.invoke(
        app, ["project", "create", "--name", "星辰", "--genre", "科幻", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _parse_json_output(result.output)
    assert data["name"] == "星辰"


@pytest.mark.project
def test_create_with_target_words(isolated_db):
    result = runner.invoke(
        app, ["project", "create", "--name", "长篇", "-w", "300000", "--json"]
    )
    assert result.exit_code == 0
    data = _parse_json_output(result.output)
    assert data["target_words"] == 300000


# ── project list ────────────────────────────────────────────────


@pytest.mark.project
def test_list_empty(isolated_db):
    result = runner.invoke(app, ["project", "list"])
    assert result.exit_code == 0
    assert "暂无项目" in result.output


@pytest.mark.project
def test_list_with_projects(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "A项目", "--genre", "玄幻"])
    runner.invoke(app, ["project", "create", "--name", "B项目", "--genre", "科幻"])
    result = runner.invoke(app, ["project", "list"])
    assert result.exit_code == 0
    assert "2 个项目" in result.output
    assert "A项目" in result.output


@pytest.mark.project
def test_list_json_output(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "唯一", "--genre", "悬疑"])
    result = runner.invoke(app, ["project", "list", "--json"])
    assert result.exit_code == 0
    data = _parse_json_output(result.output)
    assert isinstance(data, list) and len(data) == 1


@pytest.mark.project
def test_list_search(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "玄幻大作", "--genre", "玄幻"])
    runner.invoke(app, ["project", "create", "--name", "科幻巨作", "--genre", "科幻"])
    result = runner.invoke(app, ["project", "list", "--search", "科幻", "--json"])
    data = _parse_json_output(result.output)
    assert len(data) == 1
    assert data[0]["name"] == "科幻巨作"


# ── project get ─────────────────────────────────────────────────


@pytest.mark.project
def test_get_existing(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "详情测试", "--genre", "仙侠"])
    result = runner.invoke(app, ["project", "get", "--id", "1"])
    assert result.exit_code == 0, result.output
    assert "详情测试" in result.output


@pytest.mark.project
def test_get_json_output(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "JSON测试", "--genre", "都市"])
    result = runner.invoke(app, ["project", "get", "--id", "1", "--json"])
    assert result.exit_code == 0
    data = _parse_json_output(result.output)
    assert data["name"] == "JSON测试"


@pytest.mark.project
def test_get_not_found(isolated_db):
    result = runner.invoke(app, ["project", "get", "--id", "999"])
    assert result.exit_code == 1
    assert "项目不存在" in result.output


# ── project delete ──────────────────────────────────────────────


@pytest.mark.project
def test_delete_soft(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "删除测试", "--genre", "历史"])
    result = runner.invoke(app, ["project", "delete", "--id", "1", "--force"])
    assert result.exit_code == 0, result.output
    assert "已删除" in result.output
    lr = runner.invoke(app, ["project", "list", "--json"])
    assert len(_parse_json_output(lr.output)) == 0


@pytest.mark.project
def test_delete_not_found(isolated_db):
    result = runner.invoke(app, ["project", "delete", "--id", "999", "--force"])
    assert result.exit_code == 1


@pytest.mark.project
def test_delete_permanent(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "永久删除", "--genre", "武侠"])
    result = runner.invoke(
        app, ["project", "delete", "--id", "1", "--permanent", "--force"]
    )
    assert result.exit_code == 0
    assert "永久删除" in result.output


# ── project restore ─────────────────────────────────────────────


@pytest.mark.project
def test_restore_after_delete(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "恢复测试", "--genre", "游戏"])
    runner.invoke(app, ["project", "delete", "--id", "1", "--force"])
    result = runner.invoke(app, ["project", "restore", "--id", "1"])
    assert result.exit_code == 0, result.output
    assert "已恢复" in result.output
    lr = runner.invoke(app, ["project", "list", "--json"])
    assert len(_parse_json_output(lr.output)) == 1


@pytest.mark.project
def test_restore_not_found(isolated_db):
    result = runner.invoke(app, ["project", "restore", "--id", "999"])
    assert result.exit_code == 1


# ── serve ───────────────────────────────────────────────────────


def test_serve_help(isolated_db):
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output
    assert "启动" in result.output


@pytest.mark.skipif(
    "CI" in os.environ or os.name != "nt",
    reason="serve smoke test requires local environment",
)
def test_serve_smoke(isolated_db, tmp_path):
    """serve --no-open 启动后 /health 返回 200 — 仅本地运行."""
    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    env = os.environ.copy()
    env["INKFLOW_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/test.db"

    proc = subprocess.Popen(
        [sys.executable, "-m", "inkflow", "serve", "--no-open", "--port", "18765"],
        cwd=backend_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(20):
            time.sleep(0.3)
            try:
                import http.client

                conn = http.client.HTTPConnection("127.0.0.1", 18765, timeout=2)
                conn.request("GET", "/health")
                resp = conn.getresponse()
                body = resp.read().decode()
                conn.close()
                if resp.status == 200:
                    assert '"status":"ok"' in body
                    return
            except (ConnectionRefusedError, OSError):
                pass
        pytest.fail("server did not start within 6 seconds")
    finally:
        proc.terminate()
        proc.wait(timeout=5)
