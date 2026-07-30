"""CLI 集成测试 — CliRunner + serve smoke test.

每个测试用独立临时 SQLite，通过 monkeypatch 直接修改 engine/session_factory。
"""

import json
import os
import subprocess
import sys
import time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from typer.testing import CliRunner

import inkflow.core.database as db
from inkflow.__main__ import app

runner = CliRunner()


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    """每个测试独立临时 SQLite — patch CLI 和 core 两处."""
    db_path = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # patch core 模块（API 依赖）
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "async_session_factory", factory)

    # patch CLI 模块（CLI 命令的 import 缓存）
    import inkflow.cli.commands.project as cli_mod

    monkeypatch.setattr(cli_mod, "async_session_factory", factory)

    yield


def _parse_json_output(output: str):
    """从 CliRunner 输出中提取 JSON."""
    text = output.strip()
    for i, ch in enumerate(text):
        if ch in ("[", "{"):
            return json.loads(text[i:])
    raise ValueError(f"No JSON found: {text[:100]!r}")


# ── project create ──────────────────────────────────────────────


def test_create_output(isolated_db):
    result = runner.invoke(app, ["project", "create", "--name", "测试小说", "--genre", "玄幻"])
    assert result.exit_code == 0, result.output
    assert "✅" in result.output
    assert "测试小说" in result.output


def test_create_json_output(isolated_db):
    result = runner.invoke(
        app, ["project", "create", "--name", "星辰", "--genre", "科幻", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _parse_json_output(result.output)
    assert data["name"] == "星辰"


def test_create_with_target_words(isolated_db):
    result = runner.invoke(app, ["project", "create", "--name", "长篇", "-w", "300000", "--json"])
    assert result.exit_code == 0
    data = _parse_json_output(result.output)
    assert data["target_words"] == 300000


# ── project list ────────────────────────────────────────────────


def test_list_empty(isolated_db):
    result = runner.invoke(app, ["project", "list"])
    assert result.exit_code == 0
    assert "暂无项目" in result.output


def test_list_with_projects(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "A项目", "--genre", "玄幻"])
    runner.invoke(app, ["project", "create", "--name", "B项目", "--genre", "科幻"])
    result = runner.invoke(app, ["project", "list"])
    assert result.exit_code == 0
    assert "2 个项目" in result.output
    assert "A项目" in result.output


def test_list_json_output(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "唯一", "--genre", "悬疑"])
    result = runner.invoke(app, ["project", "list", "--json"])
    assert result.exit_code == 0
    data = _parse_json_output(result.output)
    assert isinstance(data, list) and len(data) == 1


def test_list_search(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "玄幻大作", "--genre", "玄幻"])
    runner.invoke(app, ["project", "create", "--name", "科幻巨作", "--genre", "科幻"])
    result = runner.invoke(app, ["project", "list", "--search", "科幻", "--json"])
    data = _parse_json_output(result.output)
    assert len(data) == 1
    assert data[0]["name"] == "科幻巨作"


# ── project get ─────────────────────────────────────────────────


def test_get_existing(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "详情测试", "--genre", "仙侠"])
    result = runner.invoke(app, ["project", "get", "--id", "1"])
    assert result.exit_code == 0, result.output
    assert "详情测试" in result.output


def test_get_json_output(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "JSON测试", "--genre", "都市"])
    result = runner.invoke(app, ["project", "get", "--id", "1", "--json"])
    assert result.exit_code == 0
    data = _parse_json_output(result.output)
    assert data["name"] == "JSON测试"


def test_get_not_found(isolated_db):
    result = runner.invoke(app, ["project", "get", "--id", "999"])
    assert result.exit_code == 1
    assert "项目不存在" in result.output


# ── project delete ──────────────────────────────────────────────


def test_delete_soft(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "删除测试", "--genre", "历史"])
    result = runner.invoke(app, ["project", "delete", "--id", "1", "--force"])
    assert result.exit_code == 0, result.output
    assert "已删除" in result.output
    lr = runner.invoke(app, ["project", "list", "--json"])
    assert len(_parse_json_output(lr.output)) == 0


def test_delete_not_found(isolated_db):
    result = runner.invoke(app, ["project", "delete", "--id", "999", "--force"])
    assert result.exit_code == 1


def test_delete_permanent(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "永久删除", "--genre", "武侠"])
    result = runner.invoke(app, ["project", "delete", "--id", "1", "--permanent", "--force"])
    assert result.exit_code == 0
    assert "永久删除" in result.output


# ── project restore ─────────────────────────────────────────────


def test_restore_after_delete(isolated_db):
    runner.invoke(app, ["project", "create", "--name", "恢复测试", "--genre", "游戏"])
    runner.invoke(app, ["project", "delete", "--id", "1", "--force"])
    result = runner.invoke(app, ["project", "restore", "--id", "1"])
    assert result.exit_code == 0, result.output
    assert "已恢复" in result.output
    lr = runner.invoke(app, ["project", "list", "--json"])
    assert len(_parse_json_output(lr.output)) == 1


def test_restore_not_found(isolated_db):
    result = runner.invoke(app, ["project", "restore", "--id", "999"])
    assert result.exit_code == 1


# ── serve ───────────────────────────────────────────────────────


def test_serve_help(isolated_db):
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--no-open" in result.output


def test_serve_smoke(isolated_db, tmp_path):
    """serve --no-open 启动后 /health 返回 200."""
    backend_dir = os.path.join(os.path.dirname(__file__), "..", "src")
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
