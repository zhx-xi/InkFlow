"""#258 F39 后端核心 — Skill API 测试契约（TDD RED 阶段）。

本文件为 `api/routers/skills.py`（NEW，spec §2.2 Skill 实体 + §3 API 契约 +
§5.6 删除保护 + §13 M1/M4/M5 验收）定义 API 测试契约，覆盖 5 组端点：

- `GET    /api/v1/skills`      — Skill 列表（{items, total} 信封 + agent_ids 反查）
- `POST   /api/v1/skills`      — 上传/创建（body {content}，frontmatter 解析，201）
- `GET    /api/v1/skills/{id}` — 详情（完整实体含反查）/ 404「Skill 不存在」
- `PATCH  /api/v1/skills/{id}` — 部分更新（exclude_unset）/ 404 / 内置 409 / 改名同名 422
- `DELETE /api/v1/skills/{id}` — 删除（204）/ 404 / 内置 409 / 被引用级联清引用

权威来源：specs/f39-multi-agent/spec.md §2.2（Skill 实体字段 + frontmatter 契约）、
§3（API 契约表 + 异常映射表）、§5.6（删除保护语义：内置 409 / 用户 skill 被引用
级联清引用）、§13 M1/M4/M5（验收锚点）。测试方式镜像 tests/api/
test_agent_templates_api.py（#107 F19：契约 docstring 风格 + 无 token 模式 +
ASGITransport + override_get_db 真实 DB 模式）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【测试方式】ASGITransport + AsyncClient 直连真实 app 对象（import
   inkflow.api.app），`override_get_db` fixture（tests/api/conftest.py）将
   get_db 替换为测试 db_session（tests/conftest.py 内存 SQLite），app 与测试
   共享同一数据库。本文件模块级 `from inkflow.api.routers import skills`
   为 RED 收集断言（skills 模块不存在 → cannot import name → 全文件收集期
   ImportError，即预期失败形态，等价 ModuleNotFoundError 收集错误）。
   所有用例显式 `@pytest.mark.asyncio` + `@pytest.mark.api`（免疫
   pytest-asyncio auto 模式差异——顶层 tests/ 运行 rootdir 无 ini 配置）。

2. 【无 token 模式——硬性契约】本文件所有用例依赖 env `INKFLOW_SERVER_TOKEN`
   未设置时中间件直通（test_settings_api.py 设计假设 #2 同款）：client fixture
   内显式 monkeypatch.delenv，免疫开发者本机 shell 的 env 残留导致假失败。

3. 【模块契约】`inkflow.api.routers.skills` 必须暴露：
   - `router = APIRouter(prefix="/api/v1/skills", tags=["Skills"])`
     （app.py 需 `app.include_router(skills.router)`，与既有 router 模块级
     模式一致，spec §8.2）
   - 【id 解析——硬性契约】路径参数必须走 `_parse_id` 语义（str 声明 +
     手动 int()，非法 → 404「Skill 不存在」），禁止 `skill_id: int` FastAPI
     类型声明（非整数会被 FastAPI 自动 422，破坏 §3.3 契约「非法 id → 404」）。

4. 【响应结构——实体契约（spec §2.2 字段）】详情/创建响应 8 键：
   `{id, name, description, content, source, created_at, updated_at,
   agent_ids}`：
   - id：str 或 int 均可，测试一律以 `str(data["id"])` 驱动 URL、比对
   - name：frontmatter name 提取（去冗余索引列）；description 同理
   - content：完整 SKILL.md 原样存储（frontmatter + 正文，逐字 roundtrip）
   - source：`"builtin" | "user_upload"`（创建产物恒 "user_upload"）
   - created_at/updated_at：ISO 8601 字符串（datetime.fromisoformat 可解析）
   - agent_ids：`[{id, name}]` 反查列表（引用该 skill 的 Agent；无引用 = []）
   - 响应可含实体额外字段，本文件只断言契约键存在 + 值语义，
     【不做整 dict 全等】（容忍 GREEN 输出额外字段）

5. 【列表端点】GET /api/v1/skills → 200 + `{items: [...], total: N}`。
   本契约只约束 items/total 两键；无数据时 total=0、items=[]。每项契约键
   = `{id, name, description, source, agent_ids}`（spec §3.2 列表示例不含
   content/created_at/updated_at，不要求也不禁止——只断言 5 键存在）。
   列表项同样含 agent_ids 反查（§5.4 管理列表「被哪些 Agent 引用」数据源）。

6. 【frontmatter 契约（spec §2.2/§5.4，F40 上传解析）】POST body 仅
   `{content}`，后端解析 frontmatter：
   - name：必选，1-64 小写字母数字+连字符（`^[a-z0-9-]{1,64}$` 语义）
   - description：必选
   - tags：可选，本 spec 不落列、保留在 content frontmatter 内
   - 缺失 name/description 或 name 格式非法 → `SkillFrontmatterError` 422
   - 同名（name 唯一）→ `SkillNameConflictError` 422
   - content 完整 SKILL.md 原样落库（真相源 blob，§2.2）

7. 【ORM 契约（seed 辅助用）】`SkillORM`（`skills` 表，构造 kwargs
   name/description/content/source，name 唯一，id 由 DB 默认生成）——测试经
   `from inkflow.infrastructure.database.models import SkillORM` 惰性导入，
   GREEN 必须在 `infrastructure/database/models/__init__.py` 导出（注册进
   Base.metadata，测试 db_session fixture 的 create_all 才会建表）。

8. 【404 语义】id 不存在或非法格式（非整数）→ 404 +
   `{"detail": "Skill 不存在"}`（父侧定稿文案；镜像 foreshadowings `_parse_id`
   404 语义，非法格式不 422）。【409/422 detail 文案未钉死】——只断言状态码 +
   detail 非空（GREEN 以业务异常 str(exc) 为 detail 即可满足）。

9. 【PATCH 语义】exclude_unset 浅合并（spec §9.1 F19 同款）：仅更新提供
   字段，未提供字段原样保留。改名为其他已存在 skill 的 name → 422
   （SkillNameConflictError）。source="builtin" → 409（SkillBuiltinError，
   §5.6 内置只读），409 后记录原样保留。

10. 【删除契约（spec §5.6）】DELETE → 204 空响应体；不存在 → 404；
    source="builtin" → 409（记录仍存在）；被引用 user skill → 服务层先移除
    所有 Agent.skill_ids 中的该 id（级联清引用）再删 → 204。

11. 【agent_ids 反查全链路（§5.4 双向视图）】创建 skill（POST /skills）→
    创建引用它的 Agent（POST /api/v1/agents body {name, skill_ids:
    [str(skill_id)]}，spec §3.2 示例）→ GET /skills 列表 / GET /skills/{id}
    详情反查含该 agent `{id, name}`；无引用 → agent_ids = []。依赖
    `/api/v1/agents` 端点（F39 同批实现，spec §8.1 api/routers/agents.py）。

════════════════════════════════════════════════════════════════════
RED 阶段预期：`inkflow.api.routers.skills` 模块不存在 → 本文件
【收集期 ImportError】（cannot import name 'skills'，收集错误形态，collected
0 items；router 未注册，请求亦 404）。GREEN 阶段：按上述契约实现 §8.1
NEW（domain/models/skill.py、
domain/ports/skill_errors.py + skill_repository.py、domain/services/
skill_service.py、infrastructure/database/models/skill.py +
repositories/skill_repo.py、api/routers/skills.py）+ §8.2 MODIFY（app.py
include_router + lifespan seed_builtin_skills）后全绿。
"""

from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from inkflow.api.app import app
from inkflow.api.routers import (
    skills,  # noqa: F401  # RED 收集断言：模块存在性契约（GREEN 实现后即被使用）
)

# ── 契约常量 ──

ENDPOINT = "/api/v1/skills"
"""Skill 端点前缀（spec §3.1）。"""

ENDPOINT_AGENTS = "/api/v1/agents"
"""Agent 端点前缀（agent_ids 反查/级联清引用全链路用，设计假设 #11）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（spec §2.3.1）：本文件全部用例依赖未设置 → 直通。"""

DETAIL_NOT_FOUND = "Skill 不存在"
"""id 不存在/非法格式的 404 detail（设计假设 #8，父侧定稿文案）。"""

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
"""合法 SKILL.md 样例（frontmatter 含 name/description/tags + 正文，设计假设 #6）。"""

SKILL_MD_2 = (
    "---\n"
    "name: outline-arch\n"
    "description: 大纲架构方法论\n"
    "---\n"
    "# 大纲\n"
    "- 三幕结构\n"
)
"""第二个合法 SKILL.md 样例（改名冲突/列表用例用，name 与 SKILL_MD 不同）。"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，test_chapter_api.py 同款 + 无 token 模式）。

    设计假设 #1/#2：显式 delenv INKFLOW_SERVER_TOKEN → token 中间件直通；
    ASGITransport 不触发 lifespan（F19 同款），建表由 db_session fixture 完成。
    """
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Seed / 断言辅助 ──


async def _seed_skill(
    db_session,
    *,
    name: str,
    description: str = "",
    content: str = "",
    source: str = "user_upload",
):
    """经 ORM 注入一条 Skill 记录（设计假设 #7）。

    source 参数用于内置只读用例（"builtin"）——内置行不依赖 seed 函数，
    保证 API 契约文件自包含（seed 幂等契约见 tests/integration/
    test_builtin_seed.py）。
    """
    from inkflow.infrastructure.database.models import SkillORM

    row = SkillORM(
        name=name,
        description=description,
        content=content,
        source=source,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


def _assert_list_item_contract(item: dict) -> None:
    """列表项契约（设计假设 #5）：5 键存在 + 值语义，容忍额外字段。

    spec §3.2 列表示例不含 content/created_at/updated_at —— 只断言
    父侧钉死的 {id, name, description, source, agent_ids}。
    """
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
    """详情/创建响应契约（设计假设 #4）：8 键存在 + 值语义，不做整 dict 全等。"""
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


async def _create_skill_via_api(client, content: str = SKILL_MD) -> str:
    """经 POST /api/v1/skills 创建 user skill，返回 str 化 id。"""
    resp = await client.post(ENDPOINT, json={"content": content})
    assert resp.status_code == 201
    return str(resp.json()["id"])


async def _create_referencing_agent(client, skill_id: str, name: str) -> str:
    """经 POST /api/v1/agents 创建引用 skill 的 Agent，返回 str 化 id。

    设计假设 #11：AgentCreate.skill_ids 存 str(skill_id)（spec §2.1），
    POST /agents 对 skill_ids 做 SkillReferenceError 校验（§3.3）——
    先建 skill 后建 agent，引用恒合法。
    """
    resp = await client.post(
        ENDPOINT_AGENTS,
        json={"name": name, "skill_ids": [skill_id]},
    )
    assert resp.status_code == 201
    return str(resp.json()["id"])


# ── GET /api/v1/skills（spec §3.1 列表，含反查）──


@pytest.mark.asyncio
@pytest.mark.api
class TestListSkills:
    """Skill 列表端点契约（设计假设 #5）。"""

    async def test_list_empty_when_no_skills(self, client, db_session, override_get_db):
        """无 skill → 200 + {items: [], total: 0}（不隐式造数，#5）。"""
        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_list_returns_created_skills(
        self, client, db_session, override_get_db
    ):
        """POST 2 条 → 200 + {items, total: 2}；每项满足列表项契约（#5）。"""
        sid_a = await _create_skill_via_api(client, SKILL_MD)
        sid_b = await _create_skill_via_api(client, SKILL_MD_2)

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        assert {str(it["id"]) for it in body["items"]} == {sid_a, sid_b}
        for item in body["items"]:
            _assert_list_item_contract(item)
            assert item["source"] == "user_upload"


# ── POST /api/v1/skills（spec §3.1 上传/创建，frontmatter 解析）──


@pytest.mark.asyncio
@pytest.mark.api
class TestCreateSkill:
    """上传/创建端点契约（设计假设 #4/#6）。"""

    async def test_create_201_contract(self, client, db_session, override_get_db):
        """成功：201 + 完整响应；frontmatter 解析 name/description；content 原样；
        source=user_upload；agent_ids=[]；DB 落库（#4/#6）。"""
        resp = await client.post(ENDPOINT, json={"content": SKILL_MD})
        assert resp.status_code == 201
        data = resp.json()
        _assert_detail_contract(data)
        assert data["name"] == "web-research"
        assert data["description"] == "网络调研方法论"
        assert data["content"] == SKILL_MD  # 完整 SKILL.md 原样存储
        assert data["source"] == "user_upload"
        assert data["agent_ids"] == []

        # 集成断言：DB 按 name 回查落库且 id 与响应一致
        from inkflow.infrastructure.database.models import SkillORM

        rows = (await db_session.execute(select(SkillORM))).scalars().all()
        assert len(rows) == 1
        assert str(rows[0].id) == str(data["id"])
        assert rows[0].name == "web-research"
        assert rows[0].content == SKILL_MD
        assert rows[0].source == "user_upload"

    @pytest.mark.parametrize(
        "content",
        [
            "---\ndescription: 缺 name\n---\n正文",  # 缺失 name
            "---\nname: web-research\n---\n正文",  # 缺失 description
            "---\nname: Web-Research\ndescription: 大写非法\n---\n正文",  # name 大写
            "---\nname: web research\ndescription: 含空格非法\n---\n正文",  # name 含空格
            "---\nname: "
            + "a" * 65
            + "\ndescription: 超长非法\n---\n正文",  # name 超 64
        ],
        ids=[
            "missing_name",
            "missing_description",
            "uppercase_name",
            "space_in_name",
            "name_too_long",
        ],
    )
    async def test_create_frontmatter_invalid_422(
        self, client, db_session, override_get_db, content
    ):
        """frontmatter 缺失 name/description 或 name 格式非法 → 422
        SkillFrontmatterError（#6；detail 文案未钉死，只断言非空）。"""
        resp = await client.post(ENDPOINT, json={"content": content})
        assert resp.status_code == 422
        assert resp.json()["detail"]

    async def test_create_duplicate_name_422(self, client, db_session, override_get_db):
        """同名（name 唯一）→ 422 SkillNameConflictError（#6）。"""
        await _create_skill_via_api(client, SKILL_MD)
        resp = await client.post(ENDPOINT, json={"content": SKILL_MD})
        assert resp.status_code == 422
        assert resp.json()["detail"]


# ── GET /api/v1/skills/{skill_id}（spec §3.1 详情，含反查）──


@pytest.mark.asyncio
@pytest.mark.api
class TestGetSkill:
    """Skill 详情端点契约（设计假设 #4/#8/#11）。"""

    async def test_get_detail_contract(self, client, db_session, override_get_db):
        """成功：200 + 完整 8 键响应；content 原样；无引用 agent_ids=[]（#4/#11）。"""
        sid = await _create_skill_via_api(client)
        resp = await client.get(f"{ENDPOINT}/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        _assert_detail_contract(data)
        assert str(data["id"]) == sid
        assert data["name"] == "web-research"
        assert data["content"] == SKILL_MD
        assert data["agent_ids"] == []

    async def test_get_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id → 404 + detail「Skill 不存在」（#8）。"""
        resp = await client.get(f"{ENDPOINT}/99999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_get_invalid_id_404(self, client, db_session, override_get_db):
        """非法 id 格式（非整数）→ 404（非 422，_parse_id 语义，#8）。"""
        resp = await client.get(f"{ENDPOINT}/not-an-int")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND


# ── PATCH /api/v1/skills/{skill_id}（spec §3.1 部分更新）──


@pytest.mark.asyncio
@pytest.mark.api
class TestPatchSkill:
    """部分更新端点契约（设计假设 #8/#9）。"""

    async def test_patch_update_200(self, client, db_session, override_get_db):
        """成功：200 + 完整响应；仅更新提供字段（exclude_unset），未提供字段
        原样保留（#9）。"""
        sid = await _create_skill_via_api(client)
        resp = await client.patch(
            f"{ENDPOINT}/{sid}", json={"description": "修订后的描述"}
        )
        assert resp.status_code == 200
        data = resp.json()
        _assert_detail_contract(data)
        assert data["description"] == "修订后的描述"
        assert data["name"] == "web-research"  # 未提供字段保留
        assert data["content"] == SKILL_MD  # 未提供字段保留

    async def test_patch_rename_conflict_422(self, client, db_session, override_get_db):
        """改名与其他已存在 skill 同名 → 422 SkillNameConflictError（#9）。"""
        sid_a = await _create_skill_via_api(client, SKILL_MD)
        await _create_skill_via_api(client, SKILL_MD_2)
        resp = await client.patch(f"{ENDPOINT}/{sid_a}", json={"name": "outline-arch"})
        assert resp.status_code == 422
        assert resp.json()["detail"]

    async def test_patch_builtin_409(self, client, db_session, override_get_db):
        """source="builtin" → 409（内置只读，§5.6）；409 后记录原样保留（#9）。"""
        row = await _seed_skill(
            db_session,
            name="builtin-skill",
            description="内置技能描述",
            content=SKILL_MD,
            source="builtin",
        )
        resp = await client.patch(f"{ENDPOINT}/{row.id}", json={"description": "篡改"})
        assert resp.status_code == 409
        assert resp.json()["detail"]

        resp2 = await client.get(f"{ENDPOINT}/{row.id}")
        assert resp2.status_code == 200
        assert resp2.json()["description"] == "内置技能描述"

    async def test_patch_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id → 404（#8）。"""
        resp = await client.patch(f"{ENDPOINT}/99999", json={"description": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND


# ── DELETE /api/v1/skills/{skill_id}（spec §3.1 删除 + §5.6 保护）──


@pytest.mark.asyncio
@pytest.mark.api
class TestDeleteSkill:
    """删除端点契约（设计假设 #8/#10）。"""

    async def test_delete_204_and_gone(self, client, db_session, override_get_db):
        """成功：204 空响应体；删除后 GET → 404（#10）。"""
        sid = await _create_skill_via_api(client)
        resp = await client.delete(f"{ENDPOINT}/{sid}")
        assert resp.status_code == 204
        assert resp.content == b""

        resp2 = await client.get(f"{ENDPOINT}/{sid}")
        assert resp2.status_code == 404
        assert resp2.json()["detail"] == DETAIL_NOT_FOUND

    async def test_delete_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id → 404（#8）。"""
        resp = await client.delete(f"{ENDPOINT}/99999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_delete_invalid_id_404(self, client, db_session, override_get_db):
        """非法 id 格式 → 404（非 422，镜像 _parse_id，#8）。"""
        resp = await client.delete(f"{ENDPOINT}/not-an-int")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_delete_builtin_409(self, client, db_session, override_get_db):
        """source="builtin" → 409；409 后记录仍存在（#10）。"""
        row = await _seed_skill(
            db_session,
            name="builtin-skill",
            description="内置技能描述",
            content=SKILL_MD,
            source="builtin",
        )
        resp = await client.delete(f"{ENDPOINT}/{row.id}")
        assert resp.status_code == 409
        assert resp.json()["detail"]

        resp2 = await client.get(f"{ENDPOINT}/{row.id}")
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "builtin-skill"

    async def test_delete_referenced_skill_cascades_clear(
        self, client, db_session, override_get_db
    ):
        """删除被引用 user skill → 204；Agent.skill_ids 级联清引用（#10/#11）。"""
        sid = await _create_skill_via_api(client)
        aid = await _create_referencing_agent(client, sid, name="引用Agent甲")

        # 引用确认：Agent 详情 skill_ids 含该 skill id
        resp = await client.get(f"{ENDPOINT_AGENTS}/{aid}")
        assert resp.status_code == 200
        assert sid in resp.json()["skill_ids"]

        # 删除 → 204
        resp2 = await client.delete(f"{ENDPOINT}/{sid}")
        assert resp2.status_code == 204

        # 级联：Agent.skill_ids 不再含该 id（服务层显式清理，非 FK）
        resp3 = await client.get(f"{ENDPOINT_AGENTS}/{aid}")
        assert resp3.status_code == 200
        assert sid not in resp3.json()["skill_ids"]

        # skill 已删除
        resp4 = await client.get(f"{ENDPOINT}/{sid}")
        assert resp4.status_code == 404
        assert resp4.json()["detail"] == DETAIL_NOT_FOUND


# ── agent_ids 反查（spec §5.4 双向视图数据源）──


@pytest.mark.asyncio
@pytest.mark.api
class TestSkillAgentReferences:
    """agent_ids 反查契约（设计假设 #11）。"""

    async def test_list_agent_ids_reverse_lookup(
        self, client, db_session, override_get_db
    ):
        """skill 被 Agent 引用 → GET /skills 列表项 agent_ids 含 {id, name}（#11）。"""
        sid = await _create_skill_via_api(client)
        aid = await _create_referencing_agent(client, sid, name="列表引用Agent")

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        matches = [it for it in resp.json()["items"] if str(it["id"]) == sid]
        assert len(matches) == 1
        item = matches[0]
        _assert_list_item_contract(item)
        assert any(
            str(entry["id"]) == aid and entry["name"] == "列表引用Agent"
            for entry in item["agent_ids"]
        )

    async def test_detail_agent_ids_reverse_lookup(
        self, client, db_session, override_get_db
    ):
        """skill 被 Agent 引用 → GET /skills/{id} 详情 agent_ids 含该 agent（#11）。"""
        sid = await _create_skill_via_api(client)
        aid = await _create_referencing_agent(client, sid, name="详情引用Agent")

        resp = await client.get(f"{ENDPOINT}/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        _assert_detail_contract(data)
        assert any(
            str(entry["id"]) == aid and entry["name"] == "详情引用Agent"
            for entry in data["agent_ids"]
        )

    async def test_agent_ids_empty_when_unreferenced(
        self, client, db_session, override_get_db
    ):
        """无引用的 skill → 列表项与详情 agent_ids 均为 []（#4/#11）。"""
        sid = await _create_skill_via_api(client)

        resp = await client.get(ENDPOINT)
        matches = [it for it in resp.json()["items"] if str(it["id"]) == sid]
        assert len(matches) == 1
        assert matches[0]["agent_ids"] == []

        resp2 = await client.get(f"{ENDPOINT}/{sid}")
        assert resp2.status_code == 200
        assert resp2.json()["agent_ids"] == []
