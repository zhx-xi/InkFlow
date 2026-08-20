"""#522 Skill 存储架构重构（DB → 文件系统真源）— Skill API 契约测试（TDD RED 阶段）。

背景：skill 从 DB 表（int id、source 列）改为 `data_dir/skills/<name>/SKILL.md`
文件真源（#522）。本文件为 `api/routers/skills.py` 定义新契约，覆盖 5 组端点：

- `GET    /api/v1/skills`            — Skill 列表（{items, total} 信封，按 name 升序）
- `POST   /api/v1/skills`            — 上传（body {content}，frontmatter 解析 name=目录名，201）
- `GET    /api/v1/skills/{skill_name}` — 详情 / 404「Skill 不存在」
- `PATCH  /api/v1/skills/{skill_name}` — 更新（content 写回文件）/ 内置 409「内置 skill 只读」
- `DELETE /api/v1/skills/{skill_name}` — 删除（删目录 + 级联清 Agent 引用）/ 内置 409

权威来源：父侧统一契约 2026-08-20（#522 定稿，跨文件漂移将导致 GREEN 失败）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【路径标识——硬性契约】`/api/v1/skills/{skill_name}`：skill_name = 目录名
   （= frontmatter name，N2 规则：小写字母数字 + 单连字符）。非法格式/不存在
   → 404 detail「Skill 不存在」（镜像旧 `_parse_id` 语义：非法格式不 422）。
   禁止 `skill_id: int` FastAPI 类型声明（非整数会被自动 422）。

2. 【响应实体】Skill 实体含 id 字段但【值 = name】（兼容层，前端 P2 再对齐）；
   其余字段 name/description/content/source/created_at/updated_at/agent_ids。
   content 与文件内容逐字 roundtrip。

3. 【source 推导——硬性契约】目录名 ∈ BUILTIN_SKILL_NAMES（6 英文 slug）
   → "builtin"（PATCH/DELETE → 409 detail「内置 skill 只读」）；否则
   "user_upload"。source 不再来自 DB 列。

4. 【POST 上传】body 仅 {content} → 201 + frontmatter 解析 name=目录名，写出
   `skills_root/<name>/SKILL.md`（content 原样）；同名已存在 → 422 detail
   「同名 skill 已存在」；frontmatter 缺失/非法（缺 name/description、name
   含大写/空格/双连字符/超长）→ 422 detail「frontmatter 不合法」。

5. 【列表】GET /api/v1/skills → 200 + {items, total}，items 按 name 升序；
   无数据 total=0、items=[]。列表项契约键 = {id, name, description, source,
   agent_ids}（容忍额外字段）。

6. 【PATCH】user_upload 可改：description 变更 → 响应更新；content 变更 →
   写回文件（文件内容 = 新 content）；内置 → 409「内置 skill 只读」且文件
   原样保留；不存在 → 404。

7. 【DELETE】user_upload → 204 空响应体 + 删除目录 + 级联清 Agent.skill_ids
   中该目录名（契约见 test_skills_cascade.py）；内置 → 409 且目录保留；
   不存在 → 404。

8. 【agent_ids 反查】按 Agent.skill_ids 精确含目录名反查（[{id, name}]，
   无引用 = []）；Agent 由测试经 AgentORM 直接造数（skill_ids 存目录名
   列表，spec §2.1 字符串化惯例的 #522 形态）。

9. 【skills_root 解析】GREEN 的 router/服务层经 `config.data_dir / "skills"`
   解析真源根（镜像 cli/commands/skills.py::_skills_root 既有惯例：config
   单例动态读取，测试 monkeypatch 实例属性）。本文件 skills_root fixture
   monkeypatch `inkflow.core.config.config.data_dir` → tmp_path，并在
   tmp_path/skills 下造目录/文件。

10. 【测试方式】ASGITransport + AsyncClient 直连真实 app；override_get_db
    fixture（tests/api/conftest.py）替换 get_db 为测试 db_session
    （tests/conftest.py 内存 SQLite，Agent 造数用）。无 token 模式：
    client fixture 显式 delenv INKFLOW_SERVER_TOKEN。所有用例显式
    @pytest.mark.asyncio + @pytest.mark.api。

════════════════════════════════════════════════════════════════════
RED 阶段预期（旧实现：DB 形态 + int id + 中文内置名，src 未改）
════════════════════════════════════════════════════════════════════
- 全部 name 路径用例：旧 router `_parse_id` 对非整数 → 404「Skill 不存在」，
  成功用例断言 200/201/204 → FAIL；内置 409 用例断言 409 → 实际 404 → FAIL
- POST 创建：旧实现落 DB（201、id=int），id==name 断言 → FAIL；文件系统断言
  （skills_root/<name>/SKILL.md 存在）→ FAIL
- frontmatter 422：旧实现 422（旧 detail 文案），detail == 「frontmatter 不合法」
  → FAIL（状态码假绿，detail 为 RED 守护）
- 同名 422：旧实现不查 fs → 201 → 断言 422 → FAIL
- 404 守护用例（不存在/非法名）：旧实现同返 404 → 假绿 PASS（守护断言）
预期形态约 13 failed / 5 passed；GREEN 按上述契约实现后全绿。
"""

from __future__ import annotations

import importlib
import re
from datetime import datetime
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
"""token 来源环境变量：本文件全部用例依赖未设置 → 中间件直通。"""

DETAIL_NOT_FOUND = "Skill 不存在"
"""skill_name 不存在/非法格式的 404 detail（父侧定稿文案，契约 #1）。"""

DETAIL_BUILTIN = "内置 skill 只读"
"""内置 skill PATCH/DELETE 的 409 detail（父侧定稿文案，契约 #3）。"""

DETAIL_CONFLICT = "同名 skill 已存在"
"""同名 skill 上传/复制的 422 detail（父侧定稿文案，契约 #4）。"""

DETAIL_FRONTMATTER = "frontmatter 不合法"
"""frontmatter 缺失/非法的 422 detail（父侧定稿文案，契约 #4）。"""

BUILTIN_SKILL_NAMES = [
    "architecture-methodology",
    "writing-methodology",
    "audit-methodology",
    "revision-methodology",
    "worldview-methodology",
    "polishing-methodology",
]
"""内置 6 Skill 英文 slug（父侧定稿，契约 #3；顺序 = 出厂序）。"""

_N2_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
"""N2 名称规则：小写字母数字 + 单连字符（契约 #1/#4）。"""

SKILL_MD = (
    "---\n"
    "name: web-research\n"
    "description: 网络调研方法论\n"
    "tags: [research, web]\n"
    "---\n"
    "# 调研流程\n"
    "1. 确定关键词\n"
    "2. 检索与筛选\n"
)
"""合法 SKILL.md 样例（frontmatter name=web-research 满足 N2，契约 #4）。"""

SKILL_MD_2 = (
    "---\n"
    "name: outline-arch\n"
    "description: 大纲架构方法论\n"
    "---\n"
    "# 大纲\n"
    "- 三幕结构\n"
)
"""第二个合法 SKILL.md 样例（列表排序/多 skill 用例用）。"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式：delenv INKFLOW_SERVER_TOKEN）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def skills_root(monkeypatch, tmp_path) -> Path:
    """文件系统 skill 真源根 = tmp_path/skills + config.data_dir 重定向。

    设计假设 #9：monkeypatch `inkflow.core.config.config.data_dir` → tmp_path，
    GREEN 的 router/服务层经 `config.data_dir / "skills"` 解析真源根（镜像
    cli/commands/skills.py::_skills_root「测试可 monkeypatch 实例属性」惯例）。
    测试经 _write_skill 在根下造 skill 目录。
    """
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
    """向 skills_root 写入 `skills/<name>/SKILL.md`（frontmatter name=目录名）。

    frontmatter name 必须满足 N2（_N2_PATTERN），否则 GREEN 读取时 422。
    """
    assert _N2_PATTERN.fullmatch(name), f"测试造数 name 必须满足 N2: {name!r}"
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


def _write_builtin(root: Path, name: str = "architecture-methodology") -> Path:
    """写入内置 skill 目录（name ∈ BUILTIN_SKILL_NAMES → source=builtin，契约 #3）。"""
    assert name in BUILTIN_SKILL_NAMES
    return _write_skill(
        root,
        name,
        description="章节结构/大纲规划方法论",
        body="# 架构方法论\n- 规划章节结构、冲突推进。\n",
    )


async def _seed_agent(
    db_session,
    *,
    name: str,
    skill_ids: list[str] | None = None,
    description: str = "",
    icon: str = "",
    system_prompt: str = "",
    builtin: bool = False,
):
    """经 ORM 注入一条 Agent 记录（skill_ids 存目录名列表，契约 #8）。"""
    from inkflow.infrastructure.database.models import AgentORM

    row = AgentORM(
        name=name,
        description=description,
        icon=icon,
        system_prompt=system_prompt,
        tool_ids=[],
        skill_ids=skill_ids or [],
        builtin=builtin,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


def _assert_list_item_contract(item: dict) -> None:
    """列表项契约（设计假设 #5）：5 键存在 + 值语义，容忍额外字段。"""
    for key in ("id", "name", "description", "source", "agent_ids"):
        assert key in item, f"列表项缺少契约字段 {key}"
    assert isinstance(item["name"], str) and item["name"]
    assert isinstance(item["description"], str)
    assert item["source"] in ("builtin", "user_upload")
    assert isinstance(item["agent_ids"], list)
    for entry in item["agent_ids"]:
        assert isinstance(entry, dict)
        assert "id" in entry and "name" in entry


def _assert_detail_contract(data: dict) -> None:
    """详情/创建响应契约（设计假设 #2）：8 键 + id==name + 值语义，不做整 dict 全等。"""
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
    assert data["id"] == data["name"], "id must equal name (#2)"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["description"], str)
    assert isinstance(data["content"], str) and data["content"]
    assert data["source"] in ("builtin", "user_upload")
    datetime.fromisoformat(data["created_at"])
    datetime.fromisoformat(data["updated_at"])
    assert isinstance(data["agent_ids"], list)
    for entry in data["agent_ids"]:
        assert isinstance(entry, dict)
        assert "id" in entry and "name" in entry


# ── GET /api/v1/skills（契约 #5 列表，按 name 升序）──


@pytest.mark.asyncio
@pytest.mark.api
class TestListSkills:
    """Skill 列表端点契约（设计假设 #5）。"""

    async def test_list_empty_when_no_skills(
        self, client, db_session, override_get_db, skills_root
    ):
        """skills_root 为空 → 200 + {items: [], total: 0}。"""
        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_list_sorted_by_name_and_source_derivation(
        self, client, db_session, override_get_db, skills_root
    ):
        """fs 造 2 user + 1 builtin → total 3；items 按 name 升序；source 由目录名推导（#3/#5）。"""
        _write_builtin(skills_root)  # architecture-methodology（builtin）
        _write_skill(skills_root, "web-research", description="网络调研方法论")
        _write_skill(skills_root, "outline-arch", description="大纲架构方法论")

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        names = [it["name"] for it in body["items"]]
        assert names == sorted(names), f"items 必须按 name 升序: {names}"
        assert names == ["architecture-methodology", "outline-arch", "web-research"]
        for item in body["items"]:
            _assert_list_item_contract(item)
            assert item["id"] == item["name"], f"列表项 id 必须 = name: {item['id']!r}"
        by_name = {it["name"]: it for it in body["items"]}
        assert by_name["architecture-methodology"]["source"] == "builtin"
        assert by_name["web-research"]["source"] == "user_upload"
        assert by_name["outline-arch"]["source"] == "user_upload"


# ── POST /api/v1/skills（契约 #4 上传，frontmatter 解析 name=目录名）──


@pytest.mark.asyncio
@pytest.mark.api
class TestCreateSkill:
    """上传/创建端点契约（设计假设 #2/#4）。"""

    async def test_create_201_contract(
        self, client, db_session, override_get_db, skills_root
    ):
        """Create 201: id==name, content written to SKILL.md."""
        resp = await client.post(ENDPOINT, json={"content": SKILL_MD})
        assert resp.status_code == 201
        data = resp.json()
        _assert_detail_contract(data)
        assert data["name"] == "web-research"
        assert data["description"] == "网络调研方法论"
        assert data["content"] == SKILL_MD
        assert data["source"] == "user_upload"
        assert data["agent_ids"] == []

        # 文件系统真源断言：目录 + SKILL.md 原样 roundtrip
        f = skills_root / "web-research" / "SKILL.md"
        assert f.is_file(), f"上传后必须写出文件: {f}"
        assert f.read_text(encoding="utf-8") == SKILL_MD  # 完整 SKILL.md 原样存储

    @pytest.mark.parametrize(
        "content",
        [
            "---\ndescription: 缺 name\n---\n正文",  # 缺失 name
            "---\nname: web-research\n---\n正文",  # 缺失 description
            "---\nname: Web-Research\ndescription: 大写非法\n---\n正文",  # name 含大写
            "---\nname: web research\ndescription: 含空格非法\n---\n正文",  # name 含空格
            "---\nname: web--research\ndescription: 双连字符非法\n---\n正文",  # N2 单连字符
            "---\nname: "
            + "a" * 65
            + "\ndescription: 超长非法\n---\n正文",  # name 超 64
        ],
        ids=[
            "missing_name",
            "missing_description",
            "uppercase_name",
            "space_in_name",
            "double_hyphen_name",
            "name_too_long",
        ],
    )
    async def test_create_frontmatter_invalid_422(
        self, client, db_session, override_get_db, skills_root, content
    ):
        """Missing/invalid frontmatter (N2) -> 422."""
        resp = await client.post(ENDPOINT, json={"content": content})
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_FRONTMATTER

    async def test_create_duplicate_name_422(
        self, client, db_session, override_get_db, skills_root
    ):
        """同名（目录已存在）→ 422 detail「同名 skill 已存在」（契约 #4）。"""
        _write_skill(skills_root, "web-research", description="已存在")
        resp = await client.post(ENDPOINT, json={"content": SKILL_MD})
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_CONFLICT


# ── GET /api/v1/skills/{skill_name}（契约 #1/#2/#3 详情）──


@pytest.mark.asyncio
@pytest.mark.api
class TestGetSkill:
    """Skill 详情端点契约（设计假设 #1/#2/#3/#8）。"""

    async def test_get_detail_contract(
        self, client, db_session, override_get_db, skills_root
    ):
        """成功：200 + id==name；content 与文件逐字一致；无引用 agent_ids=[]（#2/#8）。"""
        _write_skill(skills_root, "web-research", description="网络调研方法论")
        resp = await client.get(f"{ENDPOINT}/web-research")
        assert resp.status_code == 200
        data = resp.json()
        _assert_detail_contract(data)
        assert data["name"] == "web-research"
        assert data["id"] == "web-research"
        assert data["source"] == "user_upload"
        assert data["agent_ids"] == []
        assert data["content"] == (skills_root / "web-research" / "SKILL.md").read_text(
            encoding="utf-8"
        )

    async def test_get_builtin_source(
        self, client, db_session, override_get_db, skills_root
    ):
        """内置目录名 → 200 + source=builtin（目录名 ∈ BUILTIN 推导，#3）。"""
        _write_builtin(skills_root)
        resp = await client.get(f"{ENDPOINT}/architecture-methodology")
        assert resp.status_code == 200
        data = resp.json()
        _assert_detail_contract(data)
        assert data["source"] == "builtin"

    async def test_get_not_found_404(
        self, client, db_session, override_get_db, skills_root
    ):
        """不存在的 skill_name → 404 + detail「Skill 不存在」（#1）。"""
        resp = await client.get(f"{ENDPOINT}/no-such-skill")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    @pytest.mark.parametrize(
        "name",
        ["Web-Research", "web research", "web--research"],
        ids=["uppercase", "space", "double_hyphen"],
    )
    async def test_get_invalid_name_404(
        self, client, db_session, override_get_db, skills_root, name
    ):
        """非法 skill_name 格式（N2 违规）→ 404（非 422，#1）。"""
        resp = await client.get(f"{ENDPOINT}/{name}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND


# ── PATCH /api/v1/skills/{skill_name}（契约 #6 更新）──


@pytest.mark.asyncio
@pytest.mark.api
class TestPatchSkill:
    """更新端点契约（设计假设 #6）。"""

    async def test_patch_description_200(
        self, client, db_session, override_get_db, skills_root
    ):
        """user_upload：PATCH description → 200；description 更新；name/id 不变（#6）。"""
        _write_skill(skills_root, "web-research", description="网络调研方法论")
        resp = await client.patch(
            f"{ENDPOINT}/web-research", json={"description": "修订后的描述"}
        )
        assert resp.status_code == 200
        data = resp.json()
        _assert_detail_contract(data)
        assert data["description"] == "修订后的描述"
        assert data["name"] == "web-research"
        assert data["id"] == "web-research"

    async def test_patch_content_written_back(
        self, client, db_session, override_get_db, skills_root
    ):
        """user_upload：PATCH content → 200；响应 content 与文件均 = 新 content（写回，#6）。"""
        _write_skill(skills_root, "web-research", description="网络调研方法论")
        new_md = (
            "---\n"
            "name: web-research\n"
            "description: 网络调研方法论\n"
            "---\n"
            "# 修订版正文\n"
            "1. 第一步\n"
            "2. 第二步\n"
        )
        resp = await client.patch(f"{ENDPOINT}/web-research", json={"content": new_md})
        assert resp.status_code == 200
        data = resp.json()
        _assert_detail_contract(data)
        f = skills_root / "web-research" / "SKILL.md"
        assert f.read_text(encoding="utf-8") == new_md  # content written back to file

    async def test_patch_with_references_returns_agent_ids(
        self, client, db_session, override_get_db, skills_root
    ):
        """coverage-gap #522 (routers/skills.py L153): referenced PATCH
        response includes agent_ids reverse lookup."""
        _write_skill(skills_root, "web-research", description="network research")
        await _seed_agent(
            db_session,
            name="ReferringAgent",
            skill_ids=["web-research"],
        )

        resp = await client.patch(
            f"{ENDPOINT}/web-research",
            json={"description": "revised-after-ref"},
        )
        assert resp.status_code == 200
        data = resp.json()
        _assert_detail_contract(data)
        names = [a["name"] for a in data["agent_ids"]]
        assert "ReferringAgent" in names, f"agent_ids should include ref agent: {names}"

    async def test_patch_builtin_409(
        self, client, db_session, override_get_db, skills_root
    ):
        """内置目录名 → 409 detail「内置 skill 只读」；文件原样保留（#3/#6）。"""
        d = _write_builtin(skills_root)
        original = (d / "SKILL.md").read_text(encoding="utf-8")
        resp = await client.patch(
            f"{ENDPOINT}/architecture-methodology", json={"description": "篡改"}
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == DETAIL_BUILTIN

        resp2 = await client.get(f"{ENDPOINT}/architecture-methodology")
        assert resp2.status_code == 200
        assert resp2.json()["source"] == "builtin"
        assert (d / "SKILL.md").read_text(
            encoding="utf-8"
        ) == original, "内置文件不得被改写"

    async def test_patch_not_found_404(
        self, client, db_session, override_get_db, skills_root
    ):
        """不存在的 skill_name → 404（#1）。"""
        resp = await client.patch(
            f"{ENDPOINT}/no-such-skill", json={"description": "x"}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND


# ── DELETE /api/v1/skills/{skill_name}（契约 #7 删除）──


@pytest.mark.asyncio
@pytest.mark.api
class TestDeleteSkill:
    """删除端点契约（设计假设 #7；级联清引用见 test_skills_cascade.py）。"""

    async def test_delete_204_and_gone(
        self, client, db_session, override_get_db, skills_root
    ):
        """成功：204 空响应体；目录被删；GET → 404（#7）。"""
        _write_skill(skills_root, "web-research", description="网络调研方法论")
        resp = await client.delete(f"{ENDPOINT}/web-research")
        assert resp.status_code == 204
        assert resp.content == b""

        assert not (skills_root / "web-research").exists(), "删除后目录必须移除（真源）"
        resp2 = await client.get(f"{ENDPOINT}/web-research")
        assert resp2.status_code == 404
        assert resp2.json()["detail"] == DETAIL_NOT_FOUND

    async def test_delete_builtin_409(
        self, client, db_session, override_get_db, skills_root
    ):
        """内置目录名 → 409 detail「内置 skill 只读」；目录保留（#3/#7）。"""
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
        """不存在的 skill_name → 404（#1）。"""
        resp = await client.delete(f"{ENDPOINT}/no-such-skill")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND


# ── agent_ids 反查（契约 #8，Agent.skill_ids 精确含目录名）──


@pytest.mark.asyncio
@pytest.mark.api
class TestSkillAgentReferences:
    """agent_ids 反查契约（设计假设 #8）。"""

    async def test_agent_ids_reverse_lookup(
        self, client, db_session, override_get_db, skills_root
    ):
        """skill 被 Agent 引用（skill_ids=[目录名]）→ 详情与列表项 agent_ids 含该 agent（#8）。"""
        _write_skill(skills_root, "web-research", description="网络调研方法论")
        agent = await _seed_agent(
            db_session, name="引用Agent甲", skill_ids=["web-research"]
        )

        resp = await client.get(f"{ENDPOINT}/web-research")
        assert resp.status_code == 200
        data = resp.json()
        _assert_detail_contract(data)
        assert any(
            str(entry["id"]) == str(agent.id) and entry["name"] == "引用Agent甲"
            for entry in data["agent_ids"]
        ), f"详情 agent_ids 应含引用 Agent: {data['agent_ids']}"

        resp2 = await client.get(ENDPOINT)
        matches = [it for it in resp2.json()["items"] if it["name"] == "web-research"]
        assert len(matches) == 1
        assert any(
            str(entry["id"]) == str(agent.id) and entry["name"] == "引用Agent甲"
            for entry in matches[0]["agent_ids"]
        )

    async def test_agent_ids_empty_when_unreferenced(
        self, client, db_session, override_get_db, skills_root
    ):
        """无引用的 skill → 详情与列表项 agent_ids 均为 []（#2/#8）。"""
        _write_skill(skills_root, "web-research", description="网络调研方法论")
        resp = await client.get(f"{ENDPOINT}/web-research")
        assert resp.status_code == 200
        assert resp.json()["agent_ids"] == []

        resp2 = await client.get(ENDPOINT)
        matches = [it for it in resp2.json()["items"] if it["name"] == "web-research"]
        assert len(matches) == 1
        assert matches[0]["agent_ids"] == []
