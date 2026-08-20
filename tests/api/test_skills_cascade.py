"""#522 Skill 存储重构 — 删除级联清引用契约测试（TDD RED 阶段）。

本文件锁定删除端点新契约（父侧统一契约 2026-08-20 #7 展开）：
被引用的 user_upload skill 删除 → 204 + 目录删除 + Agent.skill_ids 中
该【目录名】被移除（真实 SQLiteAgentRepository 全链路，非 FK 级联）。

与旧契约差异（旧：int id 字符串化引用；新：skill_ids 存目录名，删除按
目录名精确匹配清理——契约 #7「级联清 Agent.skill_ids 引用」）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【测试方式】ASGITransport + AsyncClient 直连真实 app；override_get_db
   （tests/api/conftest.py）替换 get_db 为测试 db_session（tests/conftest.py
   内存 SQLite）——服务层经真实 SQLiteAgentRepository 读写 Agent.skill_ids。
   无 token 模式：client fixture 显式 delenv INKFLOW_SERVER_TOKEN。

2. 【skills_root 解析】同 test_skills_api.py 设计假设 #9：GREEN 经
   `config.data_dir / "skills"` 解析真源根；本文件 skills_root fixture
   monkeypatch `inkflow.core.config.config.data_dir` → tmp_path 并造目录。

3. 【引用形态】Agent.skill_ids 存【目录名】列表（#522 契约 #7/#8）；测试经
   AgentORM 直接造数（skill_ids=["web-research"]），与 GREEN 的
   list_agents_by_skill(skill_name) 精确含目录名反查语义一致。

4. 【级联语义（契约 #7）】DELETE /api/v1/skills/{skill_name}：
   - user_upload 且被 N 个 Agent 引用 → 204；每个 Agent.skill_ids 移除该
     目录名（其余引用保留）；目录删除
   - builtin（目录名 ∈ BUILTIN_SKILL_NAMES 英文 slug）→ 409「内置 skill 只读」
   - 不存在 → 404「Skill 不存在」

════════════════════════════════════════════════════════════════════
RED 阶段预期（旧实现：DB 形态 + int id + _parse_id）
════════════════════════════════════════════════════════════════════
- 全部 name 路径用例：旧 router `_parse_id` 对非整数 → 404 ≠ 204/409 → FAIL
- 404 守护用例（不存在名）：旧实现同返 404 → 假绿 PASS
预期形态约 4 failed / 1 passed；GREEN 后全绿。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.api.routers import (
    skills,  # noqa: F401  # 模块存在性契约（既有模块，GREEN 在其内改实现）
)

# ── 契约常量 ──

ENDPOINT = "/api/v1/skills"
"""Skill 端点前缀（#522 契约 #1）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 直通。"""

DETAIL_NOT_FOUND = "Skill 不存在"
"""skill_name 不存在/非法格式的 404 detail（父侧定稿文案）。"""

DETAIL_BUILTIN = "内置 skill 只读"
"""内置 skill 删除的 409 detail（父侧定稿文案，契约 #3）。"""

BUILTIN_SKILL_NAMES = [
    "architecture-methodology",
    "writing-methodology",
    "audit-methodology",
    "revision-methodology",
    "worldview-methodology",
    "polishing-methodology",
]
"""内置 6 Skill 英文 slug（父侧定稿，契约 #3）。"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def skills_root(monkeypatch, tmp_path) -> Path:
    """skills root: tmp_path/skills + config.data_dir redirect."""
    core_config_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
    root = tmp_path / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ── Seed / 断言辅助 ──


def _write_skill(root: Path, name: str, *, description: str = "方法论描述") -> Path:
    """向 skills_root 写入 `skills/<name>/SKILL.md`（frontmatter name=目录名）。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n# {name} 正文\n"
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


def _write_builtin(root: Path, name: str = "architecture-methodology") -> Path:
    """写入内置 skill 目录（name ∈ BUILTIN_SKILL_NAMES → source=builtin）。"""
    assert name in BUILTIN_SKILL_NAMES
    return _write_skill(root, name, description="章节结构/大纲规划方法论")


async def _seed_agent(db_session, *, name: str, skill_ids: list[str] | None = None):
    """经 ORM 注入一条 Agent 记录（skill_ids 存目录名列表，契约 #3）。"""
    from inkflow.infrastructure.database.models import AgentORM

    row = AgentORM(name=name, skill_ids=skill_ids or [])
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _agent_skill_ids(db_session, agent_id: int) -> list[str]:
    """回读 AgentORM.skill_ids（真实 DB 断言，非 API 透传）。"""
    from inkflow.infrastructure.database.models import AgentORM

    row = await db_session.get(AgentORM, agent_id)
    assert row is not None
    return list(row.skill_ids)


# ── DELETE 级联清引用（契约 #7）──


@pytest.mark.asyncio
@pytest.mark.api
class TestSkillDeleteCascade:
    """删除级联清引用契约（设计假设 #4）。"""

    async def test_delete_referenced_skill_cascades_clear(
        self, client, db_session, override_get_db, skills_root
    ):
        """被引用 user_upload skill 删除 → 204；Agent.skill_ids 移除该目录名（真实 DB 断言）。"""
        _write_skill(skills_root, "web-research", description="网络调研方法论")
        agent = await _seed_agent(
            db_session, name="引用Agent甲", skill_ids=["web-research"]
        )

        # 引用确认：Agent.skill_ids 含目录名
        assert await _agent_skill_ids(db_session, agent.id) == ["web-research"]

        resp = await client.delete(f"{ENDPOINT}/web-research")
        assert resp.status_code == 204

        # 级联：Agent.skill_ids 不再含该目录名（服务层显式清理，非 FK）
        assert await _agent_skill_ids(db_session, agent.id) == []

        # 真源：目录已删除；skill 详情 404
        assert not (skills_root / "web-research").exists()
        resp2 = await client.get(f"{ENDPOINT}/web-research")
        assert resp2.status_code == 404
        assert resp2.json()["detail"] == DETAIL_NOT_FOUND

    async def test_cascade_preserves_other_skill_references(
        self, client, db_session, override_get_db, skills_root
    ):
        """Agent 引用 2 个 skill → 删除其一 → 另一引用保留（级联只清目标目录名）。"""
        _write_skill(skills_root, "web-research", description="网络调研方法论")
        _write_skill(skills_root, "outline-arch", description="大纲架构方法论")
        agent = await _seed_agent(
            db_session, name="双引用Agent", skill_ids=["web-research", "outline-arch"]
        )

        resp = await client.delete(f"{ENDPOINT}/web-research")
        assert resp.status_code == 204

        remaining = await _agent_skill_ids(db_session, agent.id)
        assert remaining == ["outline-arch"], f"其余引用必须保留: {remaining}"

    async def test_delete_unreferenced_skill_removes_dir(
        self, client, db_session, override_get_db, skills_root
    ):
        """无引用的 user_upload skill → 204 + 目录删除。"""
        _write_skill(skills_root, "web-research", description="网络调研方法论")
        resp = await client.delete(f"{ENDPOINT}/web-research")
        assert resp.status_code == 204
        assert resp.content == b""
        assert not (skills_root / "web-research").exists()

    async def test_delete_builtin_409_and_dir_kept(
        self, client, db_session, override_get_db, skills_root
    ):
        """内置 skill（目录名 ∈ BUILTIN 英文 slug）→ 409「内置 skill 只读」；目录保留。"""
        d = _write_builtin(skills_root)
        resp = await client.delete(f"{ENDPOINT}/architecture-methodology")
        assert resp.status_code == 409
        assert resp.json()["detail"] == DETAIL_BUILTIN

        assert d.is_dir(), "内置目录不得被删除"
        resp2 = await client.get(f"{ENDPOINT}/architecture-methodology")
        assert resp2.status_code == 200
        assert resp2.json()["source"] == "builtin"

    async def test_delete_not_found_404(
        self, client, db_session, override_get_db, skills_root
    ):
        """不存在的 skill_name → 404「Skill 不存在」（守护用例，旧实现同返 404）。"""
        resp = await client.delete(f"{ENDPOINT}/no-such-skill")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND
