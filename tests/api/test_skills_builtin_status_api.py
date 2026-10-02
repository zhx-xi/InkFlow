"""#1331 内置 skill 版本化 — API 契约测试（builtin status/diff 端点，RED 阶段）。

契约来源
--------
``specs/f39-multi-agent/spec.md``（#1331 修订节）

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约）
════════════════════════════════════════════════════════════════════

1. ``GET /api/v1/skills/builtin/status`` → 200 ``{"items": [...], "total": N}``
   每项键（容忍额外字段）：``name`` / ``latest_version`` / ``installed`` /
   ``installed_version`` / ``user_modified`` / ``has_update``。
   - 未播种（空 skills_root）→ ``installed=False`` / ``installed_version=None`` /
     ``user_modified=False`` / ``has_update=True``
   - 已播种且未改 → ``installed=True`` / ``installed_version==latest_version`` /
     ``user_modified=False`` / ``has_update=False``
   - 用户改过 → ``user_modified=True``
2. ``GET /api/v1/skills/builtin/{name}/diff`` → 200
   ``{"name", "installed_version", "latest_version", "diff"}``（diff = unified
   diff 文本，新旧不同时非空）；非内置 slug → 404 detail「Skill 不存在」。
3. 路由注册：``/builtin/status``（两段静态）不得被 ``/{skill_name}`` 捕获。

测试方式：ASGITransport + AsyncClient 直连真实 app（镜像 tests/api/ 惯例），
``skills_root`` fixture 经 monkeypatch ``config.data_dir`` 重定向（镜像
test_builtin_seed.py），无 token 模式。

RED 阶段预期：端点不存在 → 404（FastAPI 未注册路由）→ 用例 FAILED。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.domain.services.skill_service import BUILTIN_SKILL_NAMES, ensure_builtin_skills

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
STATUS_ENDPOINT = "/api/v1/skills/builtin/status"
DETAIL_NAME_MISSING = "Skill 不存在"
_STATE_FILENAME = ".builtin_state.json"


@pytest_asyncio.fixture
async def db_session_override():
    """把 get_db 替换为无需真库的哑实现（builtin status/diff 不查 DB）。"""
    from inkflow.api.deps import get_db

    async def _get_db_override():
        yield None

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(monkeypatch, db_session_override):
    """ASGI 测试客户端（函数级，无 token 模式）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def skills_root(monkeypatch, tmp_path) -> Path:
    """文件系统 skill 真源根 = tmp_path/skills + config.data_dir 重定向。"""
    core_config_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
    root = tmp_path / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.mark.asyncio
@pytest.mark.api
class TestBuiltinStatusEndpoint:
    """/skills/builtin/status 契约。"""

    async def test_unseeded_reports_missing(self, client, skills_root) -> None:
        """空 skills_root：6 条内置全部 installed=False / has_update=True。"""
        resp = await client.get(STATUS_ENDPOINT)
        assert resp.status_code == 200, f"status 端点未注册或异常: {resp.status_code}"
        data = resp.json()
        assert data["total"] == 6
        by_name = {it["name"]: it for it in data["items"]}
        assert set(by_name) == set(BUILTIN_SKILL_NAMES)
        for item in by_name.values():
            assert item["installed"] is False
            assert item["installed_version"] is None
            assert item["user_modified"] is False
            assert item["has_update"] is True

    async def test_seeded_reports_installed_no_update(self, client, skills_root) -> None:
        """播种后且未改：installed=True / installed_version==latest_version / 无更新。"""
        assert ensure_builtin_skills(skills_root) == 6
        resp = await client.get(STATUS_ENDPOINT)
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["installed"] is True
            assert item["installed_version"] == item["latest_version"]
            assert item["user_modified"] is False
            assert item["has_update"] is False

    async def test_flags_user_modified(self, client, skills_root) -> None:
        """用户改过的副本 → user_modified=True（不可被自动升级）。"""
        assert ensure_builtin_skills(skills_root) == 6
        slug = BUILTIN_SKILL_NAMES[0]
        target = skills_root / slug / "SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "\n\n用户补充\n", encoding="utf-8")

        resp = await client.get(STATUS_ENDPOINT)
        item = next(it for it in resp.json()["items"] if it["name"] == slug)
        assert item["user_modified"] is True
        assert item["has_update"] is False, "被定制的副本不应提示自动升级"


@pytest.mark.asyncio
@pytest.mark.api
class TestBuiltinDiffEndpoint:
    """/skills/builtin/{name}/diff 契约。"""

    async def test_diff_for_older_unmodified_release(self, client, skills_root) -> None:
        """未改的旧版 → 200 + diff 非空（含增删行）。"""
        assert ensure_builtin_skills(skills_root) == 6
        slug = BUILTIN_SKILL_NAMES[1]
        target = skills_root / slug / "SKILL.md"
        latest = target.read_text(encoding="utf-8")
        older = latest.replace("version: 1.0.0", "version: 0.9.0", 1)
        target.write_text(older, encoding="utf-8")

        resp = await client.get(f"/api/v1/skills/builtin/{slug}/diff")
        assert resp.status_code == 200, f"diff 端点异常: {resp.status_code}"
        data = resp.json()
        assert data["name"] == slug
        assert data["installed_version"] == "0.9.0"
        assert data["diff"], "旧版差异应为非空 unified diff"

    async def test_diff_unknown_name_404(self, client, skills_root) -> None:
        """非内置 slug → 404「Skill 不存在」（与详情端点同语义）。"""
        resp = await client.get("/api/v1/skills/builtin/not-a-builtin/diff")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NAME_MISSING


@pytest.mark.asyncio
@pytest.mark.api
class TestRouteRegistration:
    """路由顺序：静态段不得被 /{skill_name} 捕获。"""

    async def test_status_path_not_swallowed_by_detail(self, client, skills_root) -> None:
        """GET /skills/builtin/status 返回 status 信封，而非详情 404.//"""
        resp = await client.get(STATUS_ENDPOINT)
        assert resp.status_code == 200
        assert "items" in resp.json(), f"被 /{{skill_name}} 捕获: {resp.json()}"
