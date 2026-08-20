"""#522 Skill 存储重构 — duplicate 端点契约测试（TDD RED 阶段）。

覆盖 2 组 duplicate 端点（#485 既有 + #522 新契约）：

- `POST /api/v1/agents/{agent_id}/duplicate`   — Agent 复制（#485 契约不变）
- `POST /api/v1/skills/{skill_name}/duplicate` — Skill 复制（#522 新契约：
  路径标识 = skill_name 目录名；新实体 name = f"{name}-copy"；内置复制后
  source=user_upload）

Skill duplicate 新旧契约差异（父侧统一契约 2026-08-20 #5）：
- 旧：路径 int id；新名 = f"{name} 副本"（中文后缀，含空格）
- 新：路径 skill_name（目录名）；新名 = f"{name}-copy"（-copy 后缀）；
  冲突 → 422「同名 skill 已存在」；内置源可复制、副本 source=user_upload

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【Skill 路径——硬性契约】`/api/v1/skills/{skill_name}/duplicate`：
   skill_name = 目录名（N2 规则）。不存在/非法 → 404「Skill 不存在」。
   Agent 侧保持 `/{agent_id}/duplicate`（int id，_parse_id 语义不变，#485）。

2. 【Skill duplicate 语义（契约 #5）】
   - 成功 → 201 + 新实体：name = f"{源 name}-copy"；id 字段值 = name；
     description/content 与源一致；agent_ids=[]（新副本无引用）
   - source：源为 user_upload → 副本 user_upload；源为 builtin（目录名 ∈
     BUILTIN 英文 slug）→ 副本 user_upload（内置复制转用户态，#485 核心）
   - 文件系统：新目录 skills_root/<name>-copy/SKILL.md 写出（content 逐字）
   - 冲突：skills_root 下已存在 f"{name}-copy" 目录 → 422「同名 skill 已存在」
   - 404：源目录不存在 → 404（守护用例，旧实现同返 404）

3. 【Agent duplicate 语义（#485 契约不变，本文件保留守护）】
   - 内置源（builtin=True）→ 201 + 副本 builtin=False、role_key 非源值
   - 自定义源 → 201 + 副本 builtin=False
   - 副本名冲突 → 422；不存在/非法 id → 404「Agent 不存在」
   - Agent 测试 skill_ids 传 []（#522 后 skill_ids 存目录名；Agent 域契约
     不变，避免与 skill 真源耦合——本文件聚焦 Skill duplicate 新契约）

4. 【skills_root 解析】同 test_skills_api.py 设计假设 #9：GREEN 经
   `config.data_dir / "skills"` 解析真源根；skills_root fixture monkeypatch
   config.data_dir → tmp_path 并造目录。

5. 【测试方式】ASGITransport + AsyncClient 直连真实 app；override_get_db
   （tests/api/conftest.py）+ db_session（tests/conftest.py）；无 token 模式。

════════════════════════════════════════════════════════════════════
RED 阶段预期（旧实现：DB 形态 + int id + 中文副本后缀）
════════════════════════════════════════════════════════════════════
- Skill duplicate 成功用例：旧 router `_parse_id` 对 skill_name → 404 ≠ 201
  → FAIL（4 条：user 源 ×1 + builtin 源 ×1 + 冲突 422 用例 ×1 + fs 断言）
- 冲突 422 用例：断言 422 → 实际 404 → FAIL
- 404 守护用例：status 404 假绿 PASS、detail「Skill 不存在」同返 → PASS
- Agent duplicate 用例：#485 已实现 → 全绿 PASS（守护，非 #522 范围）
预期形态约 4 failed / 5 passed；GREEN 后全绿。
"""

from __future__ import annotations

import importlib
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.infrastructure.database.models import AgentORM

# ── 契约常量 ──

ENDPOINT_AGENTS = "/api/v1/agents"
"""Agent 端点前缀（spec §3.1）。"""

ENDPOINT_SKILLS = "/api/v1/skills"
"""Skill 端点前缀（#522 契约 #1）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 直通。"""

DETAIL_NOT_FOUND_AGENT = "Agent 不存在"
"""Agent id 不存在/非法格式的 404 detail（#485 契约）。"""

DETAIL_NOT_FOUND_SKILL = "Skill 不存在"
"""Skill name 不存在/非法格式的 404 detail（#522 契约 #1）。"""

DETAIL_CONFLICT = "同名 skill 已存在"
"""Skill 副本名冲突的 422 detail（父侧定稿文案，契约 #5）。"""

DUPLICATE_NAME_SUFFIX = "-copy"
"""Skill duplicate 新实体 name 后缀（父侧定稿，契约 #5）。"""

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


def _write_skill(
    root: Path,
    name: str,
    *,
    description: str = "方法论描述",
    body: str = "# 正文\n1. 步骤一\n",
) -> Path:
    """向 skills_root 写入 `skills/<name>/SKILL.md`（frontmatter name=目录名）。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


def _write_builtin(root: Path, name: str = "architecture-methodology") -> Path:
    """写入内置 skill 目录（name ∈ BUILTIN_SKILL_NAMES → source=builtin）。"""
    assert name in BUILTIN_SKILL_NAMES
    return _write_skill(root, name, description="章节结构/大纲规划方法论")


async def _seed_agent(
    db_session,
    *,
    name: str,
    description: str = "",
    icon: str = "",
    system_prompt: str = "",
    tool_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
    model_override: str | None = None,
    temperature_override: float | None = None,
    builtin: bool = False,
    role_key: str | None = None,
):
    """经 ORM 注入一条 Agent 记录（#485 契约；skill_ids 存目录名列表，#522 形态）。"""
    row = AgentORM(
        name=name,
        description=description,
        icon=icon,
        system_prompt=system_prompt,
        tool_ids=tool_ids or [],
        skill_ids=skill_ids or [],
        model_override=model_override,
        temperature_override=temperature_override,
        builtin=builtin,
        role_key=role_key,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


def _assert_agent_response_contract(data: dict) -> None:
    """Agent 响应结构契约（#485）：13 键存在 + 值语义，不做整 dict 全等。"""
    for key in (
        "id",
        "name",
        "description",
        "icon",
        "system_prompt",
        "tool_ids",
        "skill_ids",
        "model_override",
        "temperature_override",
        "builtin",
        "role_key",
        "created_at",
        "updated_at",
    ):
        assert key in data, f"响应缺少契约字段 {key}"
    datetime.fromisoformat(data["created_at"])
    datetime.fromisoformat(data["updated_at"])
    assert isinstance(data["name"], str) and data["name"].strip() != ""
    assert isinstance(data["tool_ids"], list)
    assert isinstance(data["skill_ids"], list)
    assert data["model_override"] is None or isinstance(data["model_override"], str)
    assert data["temperature_override"] is None or isinstance(
        data["temperature_override"], (int, float)
    )
    assert isinstance(data["builtin"], bool)


def _assert_skill_response_contract(data: dict) -> None:
    """Skill 响应结构契约（#522 契约 #2/#5）：8 键 + id==name + 值语义。"""
    for key in (
        "id",
        "name",
        "description",
        "content",
        "source",
        "created_at",
        "updated_at",
        "agent_ids",
    ):
        assert key in data, f"响应缺少契约字段 {key}"
    datetime.fromisoformat(data["created_at"])
    datetime.fromisoformat(data["updated_at"])
    assert isinstance(data["name"], str) and data["name"].strip() != ""
    assert data["id"] == data["name"], f"id 必须 = name（契约 #2）: {data['id']!r}"
    assert data["source"] in ("builtin", "user_upload")
    assert isinstance(data["agent_ids"], list)


# ── POST /api/v1/skills/{skill_name}/duplicate（#522 Skill 复制新契约）──


@pytest.mark.asyncio
@pytest.mark.api
class TestDuplicateSkill:
    """Skill 复制端点契约（设计假设 #1/#2）。"""

    async def test_duplicate_user_skill_201_copy(
        self, client, db_session, override_get_db, skills_root
    ):
        """user_upload 源 → 201；name=f"{name}-copy"；id==name；content 逐字；fs 新目录写出。

        主 RED 信号：旧实现 `_parse_id` 对 skill_name → 404「Skill 不存在」
        ≠ 201 → FAIL。
        """
        src_content = (
            "---\nname: research-notes\ndescription: 调研笔记方法论\n---\n\n"
            "# 调研笔记\n\n- 记录来源与结论。\n"
        )
        _write_skill(
            skills_root,
            "research-notes",
            description="调研笔记方法论",
            body="# 调研笔记\n\n- 记录来源与结论。\n",
        )

        resp = await client.post(f"{ENDPOINT_SKILLS}/research-notes/duplicate")
        assert resp.status_code == 201
        data = resp.json()
        _assert_skill_response_contract(data)
        assert data["name"] == f"research-notes{DUPLICATE_NAME_SUFFIX}"
        assert data["id"] == f"research-notes{DUPLICATE_NAME_SUFFIX}"
        assert data["description"] == "调研笔记方法论"
        assert data["source"] == "user_upload"
        assert data["agent_ids"] == []

        # 文件系统真源：新目录 + SKILL.md 逐字拷贝
        f = skills_root / "research-notes-copy" / "SKILL.md"
        assert f.is_file(), f"副本必须写出文件: {f}"
        assert f.read_text(encoding="utf-8") == src_content

    async def test_duplicate_builtin_source_201_user_state(
        self, client, db_session, override_get_db, skills_root
    ):
        """内置源（目录名 ∈ BUILTIN 英文 slug）→ 201 + 副本转用户态（source=user_upload）。

        #485 核心验收：内置复制转用户态；副本名 = f"{slug}-copy"。
        """
        _write_builtin(skills_root)  # architecture-methodology
        resp = await client.post(
            f"{ENDPOINT_SKILLS}/architecture-methodology/duplicate"
        )
        assert resp.status_code == 201
        data = resp.json()
        _assert_skill_response_contract(data)
        assert data["name"] == "architecture-methodology-copy"
        assert data["source"] == "user_upload", "内置 Skill 副本必须转用户态"
        assert data["agent_ids"] == []
        assert (skills_root / "architecture-methodology-copy" / "SKILL.md").is_file()

    async def test_duplicate_name_conflict_422(
        self, client, db_session, override_get_db, skills_root
    ):
        """副本名已存在（skills_root 下已有 f"{name}-copy" 目录）→ 422「同名 skill 已存在」。

        主 RED 信号：旧实现 → 404 ≠ 422 → FAIL。
        """
        _write_skill(skills_root, "research-notes", description="调研笔记方法论")
        _write_skill(skills_root, "research-notes-copy", description="已存在副本")

        resp = await client.post(f"{ENDPOINT_SKILLS}/research-notes/duplicate")
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_CONFLICT

    async def test_duplicate_not_found_404(
        self, client, db_session, override_get_db, skills_root
    ):
        """源目录不存在 → 404「Skill 不存在」（守护用例，旧实现同返 404）。"""
        resp = await client.post(f"{ENDPOINT_SKILLS}/no-such-skill/duplicate")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND_SKILL


# ── POST /api/v1/agents/{agent_id}/duplicate（#485 Agent 复制，契约不变）──


@pytest.mark.asyncio
@pytest.mark.api
class TestDuplicateAgent:
    """Agent 复制端点契约守护（设计假设 #3，非 #522 范围）。"""

    async def test_duplicate_builtin_source_201_user_state(
        self, client, db_session, override_get_db
    ):
        """内置源（builtin=True）→ 201 + 副本转用户态（builtin=False）；role_key 非源值。"""
        src = await _seed_agent(
            db_session,
            name="架构师",
            description="章节结构/大纲规划",
            icon="🏗️",
            system_prompt="你是架构师，负责章节结构与大纲规划。",
            tool_ids=["search_characters", "check_foreshadowing", "get_prior_summary"],
            builtin=True,
            role_key="architect",
        )

        resp = await client.post(f"{ENDPOINT_AGENTS}/{src.id}/duplicate")
        assert resp.status_code == 201
        data = resp.json()
        _assert_agent_response_contract(data)
        assert str(data["id"]) != str(src.id), "副本 id 必须不同于源 Agent"
        assert data["name"] == "架构师 副本"
        assert data["builtin"] is False, "内置 Agent 副本必须转用户态（builtin=False）"
        assert data["role_key"] != "architect", "副本不得继承源 role_key"
        assert data["skill_ids"] == []

    async def test_duplicate_custom_source_201(
        self, client, db_session, override_get_db
    ):
        """自定义源（builtin=False）也可复制 → 201 + 副本 builtin=False。"""
        src = await _seed_agent(
            db_session,
            name="我的润色师",
            description="专注文笔润色的自定义角色",
            tool_ids=["count_words", "get_prior_summary", "save_draft"],
            model_override="zhipu/glm-4.5",
            temperature_override=0.6,
        )

        resp = await client.post(f"{ENDPOINT_AGENTS}/{src.id}/duplicate")
        assert resp.status_code == 201
        data = resp.json()
        _assert_agent_response_contract(data)
        assert str(data["id"]) != str(src.id), "副本 id 必须不同于源 Agent"
        assert data["name"] == "我的润色师 副本"
        assert data["builtin"] is False
        assert data["skill_ids"] == []

    async def test_duplicate_name_conflict_422(
        self, client, db_session, override_get_db
    ):
        """副本名冲突 → 422（预插 name="架构师 副本" 的自定义 Agent）。"""
        src = await _seed_agent(
            db_session, name="架构师", builtin=True, role_key="architect"
        )
        await _seed_agent(db_session, name="架构师 副本")

        resp = await client.post(f"{ENDPOINT_AGENTS}/{src.id}/duplicate")
        assert resp.status_code == 422
        assert resp.json()["detail"]

    async def test_duplicate_not_found_404(self, client, db_session, override_get_db):
        """id 不存在（99999）/非法格式（abc）→ 404「Agent 不存在」（守护用例）。"""
        resp = await client.post(f"{ENDPOINT_AGENTS}/99999/duplicate")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND_AGENT

        resp2 = await client.post(f"{ENDPOINT_AGENTS}/abc/duplicate")
        assert resp2.status_code == 404
        assert resp2.json()["detail"] == DETAIL_NOT_FOUND_AGENT
