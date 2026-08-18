"""#258 F39 多 Agent 后端核心 — Agent API 契约测试（TDD RED 阶段）。

本文件为 `api/routers/agents.py`（NEW，spec §3 API 契约 + §5.3 seed 表 +
§13 M1/M2/M5 验收）定义 API 契约测试，覆盖 6 组端点（前缀 /api/v1/agents）：

- `GET    /api/v1/agents`          — Agent 列表（{items, total} 信封）
- `GET    /api/v1/agents/tools`    — 工具目录（6 工具 + group 分组；路由顺序硬契约）
- `POST   /api/v1/agents`          — 创建自定义 Agent（201 完整实体）
- `GET    /api/v1/agents/{agent_id}` — 详情（200 完整实体）/ 404
- `PATCH  /api/v1/agents/{agent_id}` — 部分更新（exclude_unset）/ 404 / 内置 409
- `DELETE /api/v1/agents/{agent_id}` — 删除（204）/ 404 / 内置 409

权威来源：specs/f39-multi-agent/spec.md §3（§3.1 端点总览、§3.2 请求/响应
示例、§3.3 异常映射表）+ §5.3（6 Agent 出厂配置 seed）+ §13（M1/M2/M5）。
测试方式镜像 tests/api/test_agent_templates_api.py（F19，契约 docstring 风格
+ 无 token 模式 + ASGITransport + override_get_db 真实 DB 模式）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【测试方式】ASGITransport + AsyncClient 直连真实 app 对象（import
   inkflow.api.app），`override_get_db` fixture（tests/api/conftest.py）将
   get_db 替换为测试 db_session（tests/conftest.py 内存 SQLite），app 与测试
   共享同一数据库。本文件模块级 `import inkflow.api.routers.agents` 为 RED
   收集断言（模块不存在 → 全文件收集期 ModuleNotFoundError，即预期失败
   形态）。所有用例类显式 `@pytest.mark.asyncio` + `@pytest.mark.api`
   （免疫 pytest-asyncio auto 模式差异，镜像 F19 惯例）。

2. 【无 token 模式——硬性契约】本文件所有用例依赖 env `INKFLOW_SERVER_TOKEN`
   未设置时中间件直通：client fixture 内显式 monkeypatch.delenv，免疫开发者
   本机 shell 的 env 残留导致假失败（test_settings_api.py 设计假设 #2 同款）。

3. 【模块契约】`inkflow.api.routers.agents` 必须暴露：
   - `router = APIRouter(prefix="/api/v1/agents", tags=["Agents"])`
     （app.py 需 `app.include_router(agents.router)`，与既有 router 模块级
     模式一致）
   - 【路由声明顺序——硬性契约】`GET /tools` 必须声明在 `GET /{agent_id}`
     之前（FastAPI 按声明顺序匹配：反序时 "tools" 被吞进 {agent_id} 路径
     参数 → _parse_id 404「Agent 不存在」→ 工具目录用例全红；镜像 F19
     `/default` 契约 #3，spec §3.1 明示约束）。

4. 【响应实体契约（spec §2.1 实体字段）】Agent 响应 12 键：
   `{id, name, description, icon, system_prompt, tool_ids, skill_ids,
   model_override, temperature_override, builtin, created_at, updated_at}`：
   - id：int 主键（ORM 自增），测试一律以 `str(row.id)` 驱动 URL、
     `str(data["id"])` 比对
   - name：str 非空白；description/icon/system_prompt：str（默认 ""）
   - tool_ids：list[str]（工具目录 name 白名单）；skill_ids：list[str]
     （Skill.id 字符串化白名单）
   - model_override：str | None（provider/model 格式）；temperature_override：
     float | None ∈ [0.0, 2.0]
   - builtin：bool —— 内置出厂 Agent 只读（PATCH/DELETE → 409）
   - created_at/updated_at：ISO 8601 字符串（datetime.fromisoformat 可解析）
   - 响应可含实体额外字段，本文件只断言契约键存在 + 值语义，【不做整 dict
     全等】（容忍 GREEN 输出额外字段）

5. 【列表端点】GET /api/v1/agents → 200 + `{items: [...], total: N}`（repo
   列表端点惯例 envelope）。本契约只约束 items/total 两键（GREEN 可额外
   输出 offset/limit 等分页字段）；无数据时 total=0、items=[]；每项满足
   基础响应契约（含 builtin 值回显）。

6. 【工具目录端点】GET /api/v1/agents/tools → 200 + `{items: [{name,
   description, group, input_schema}]}`（spec §2.3/§5.1）：
   - 完整 6 工具目录：save_draft（writing）/ search_characters（retrieval）/
     check_foreshadowing（retrieval）/ get_prior_summary（retrieval）/
     audit_chapter（audit）/ count_words（audit）——名字全集契约
   - 目录排序固定：先 5 只读后 save_draft（spec §5.1）——本契约只锁
     save_draft 为末位（前 5 只读相对顺序为实现细节）
   - group ∈ {writing, retrieval, audit, project} 四分组键；save_draft
     group == "writing"（spec §2.3 表）
   - input_schema 为 dict（Pydantic model_json_schema() 产物）
   - 本端点 200 即路由顺序契约的验证：若 /tools 声明在 /{agent_id} 之后 →
     "tools" 被 _parse_id → 404「Agent 不存在」→ 200 断言 FAIL

7. 【ORM 契约（seed 辅助用）】
   - `inkflow.infrastructure.database.models.agent.AgentORM`（`agents` 表），
     构造 kwargs name/description/icon/system_prompt/tool_ids/skill_ids/
     model_override/temperature_override/builtin（tool_ids/skill_ids 为
     LenientJSON 列，镜像 ProjectORM.config 形态），id 由 DB 默认生成
     （注意：该文件已含 F27 AgentExecutionORM，AgentORM 为 F39 新增类）
   - `inkflow.infrastructure.database.models.skill.SkillORM`（`skills` 表），
     构造 kwargs name/description/content/source（name 唯一列）
   - 两者需在 `infrastructure/database/models/__init__.py` 导出（注册进
     Base.metadata，test_engine fixture 的 create_all 才会建表）

8. 【422 校验——Pydantic 层】POST：name 必填且去空白非空（缺失 / "   " →
   422）；temperature_override ∈ [0.0, 2.0]（越界 → 422）；多余字段忽略
   （Pydantic v2 默认行为，不 422）。PATCH：全可选（`{}` 合法 → 200 不变），
   提供即校验（name 空白 / temperature_override 越界 → 422）。Pydantic 层
   422 响应 detail 为校验错误列表（list）。

9. 【422 校验——业务层（spec §3.3 异常映射）】同名 → AgentNameConflictError
   → 422（创建同名 / PATCH 改名撞名皆然）；tool_ids 含目录外工具名 →
   ToolReferenceError → 422；skill_ids 含不存在 skill id → SkillReferenceError
   → 422。业务层 422 detail 为服务层消息（str），本文件只断言状态码 + detail
   非空，【不锁精确文案与 detail 类型】。

10. 【404 语义】id 不存在或非法格式（非整数）→ 404 + `{"detail": "Agent 不
    存在"}`（镜像 foreshadowings/_parse_id 404 语义，非法格式不 422）。
    _parse_id 只接受整数格式字符串。

11. 【创建契约】POST → 201 + 完整响应结构；name/description/icon/
    system_prompt/tool_ids/skill_ids/model_override/temperature_override
    原样回显；builtin=False（新建恒为自定义 Agent）；DB 按 name 回查落库且
    id 与响应一致（集成断言）。最小 body 仅 {name} 即可创建——默认值
    description=""、icon=""、system_prompt=""、tool_ids=[]、skill_ids=[]、
    model_override=None、temperature_override=None。注意 skill_ids 引用
    校验（#9）：成功用例的 skill_ids 必须指向真实预插 skill（见 #14）。

12. 【PATCH 语义】exclude_unset 浅合并：仅更新提供字段，未提供字段原样
    保留；空 body {} → 200 不变；内置 Agent（builtin=True）→ 409（#13）。

13. 【内置只读保护（spec §5.6）】builtin=True 的 Agent → PATCH/DELETE →
    409；409 后记录仍存在（GET → 200）。409 detail【不锁精确文案】：服务层
    AgentBuiltinError 默认消息或 router 层映射文案皆可，本契约锁
    `"内置" in detail`（验证语义而非逐字，参照 agent_templates 先例的
    宽松变体）。

14. 【白名单引用校验的确定性方案（本契约定稿）】走真实 repo 轨而非 patch
    service：skill_ids 合法引用用例先经 `_seed_skill`（SkillORM 真实落库）
    预插 skill 行拿 id；不存在引用用例用确定不存在的大整数 id（如
    "999999"）；tool_ids 合法性由实现对照 TOOL_REGISTRY（静态 6 工具目录）
    判定，用例直接传目录外名（如 "no_such_tool"）。全链路真实 DB + 真实
    service，无 mock。

15. 【lifespan/建表】ASGITransport 不触发 lifespan（test_chapter_api.py
    同款），建表由 test_engine fixture（tests/conftest.py）完成；本文件
    全部用例无 ./inkflow.db 副作用。spec §5.3 的 6 内置 Agent 出厂 seed
    由 app lifespan 执行（测试不依赖）；内置只读 409 用例经 `_seed_agent
    (builtin=True)` 预插驱动。

16. 【独立于既有测试】本文件只契约 /api/v1/agents（F39 新路由，复数前缀）；
    不触碰 tests/api/test_agent_api.py（F4 编排 API，单数前缀 /api/v1/agent，
    与本文件被测对象不同域）。agent-templates/skills 等端点不在本文件覆盖
    范围（skills 端点契约属 F39 并行批 tests/api/test_skills_api.py）。

17. 【role_key 透出（#473 R1，角色集合单一来源前置）】内置 Agent 响应含
    role_key 字段（str | None）——builtin=True 且名字匹配 BUILTIN_AGENT_SPECS
    出厂表 → 链角色键映射（架构师=architect、写手=writer、审校员=auditor、
    修订师=reviser）；非链内置（世界观顾问/润色师）与自定义 Agent → null。
    列表端点与详情端点都透出（前端 AgentChainCard 按 role_key 派生角色行，
    不再 hardcode 名称/图标/描述；config.agent_* 持久化契约不变）。

════════════════════════════════════════════════════════════════════
RED 阶段预期：`inkflow.api.routers.agents` 模块不存在 → 本文件【收集期
ModuleNotFoundError】collected 0 items（pytest exit 2；router 未注册，请求
亦 404）。GREEN 阶段：按上述契约实现 spec §8.1 CREATE（domain/models/
agent.py、domain/ports/agent_repository.py + agent_errors.py、domain/services/
agent_service.py、infrastructure/database/models/skill.py、infrastructure/
database/repositories/agent_repo.py、api/routers/agents.py）+ §8.2 MODIFY
（domain/models/agent_tools.py ToolSpec.group、tools/__init__.py TOOL_REGISTRY
6 工具、database/models/__init__.py、api/app.py include_router）后全绿。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import inkflow.api.routers.agents  # noqa: F401  # RED 收集断言：模块存在性契约（GREEN 实现后即被使用）
from inkflow.api.app import app
from inkflow.domain.models.agent import Agent, AgentUpdate
from inkflow.domain.ports.agent_errors import (
    AgentBuiltinError,
    AgentNameConflictError,
    AgentNotFoundError,
)
from inkflow.domain.ports.agent_repository import AgentRepositoryProtocol
from inkflow.domain.ports.skill_repository import SkillRepositoryProtocol
from inkflow.domain.services.agent_entity_service import AgentEntityService

# ── 契约常量 ──

ENDPOINT = "/api/v1/agents"
"""Agent 端点前缀（spec §3.1）。"""

ENDPOINT_TOOLS = "/api/v1/agents/tools"
"""工具目录端点（spec §3.1；路由顺序硬契约 #3）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（spec §2.3.1）：本文件全部用例依赖未设置 → 直通。"""

DETAIL_NOT_FOUND = "Agent 不存在"
"""id 不存在/非法格式的 404 detail（设计假设 #10，本契约定稿）。"""

TOOL_GROUPS = ("writing", "retrieval", "audit", "project")
"""工具目录四分组键（spec §2.3，D2 勾选 UI 用）。"""

EXPECTED_TOOL_NAMES = {
    "save_draft",
    "search_characters",
    "check_foreshadowing",
    "get_prior_summary",
    "audit_chapter",
    "count_words",
}
"""完整 6 工具目录名字全集（spec §2.3 表，M2 验收）。"""

FULL_AGENT_PAYLOAD = {
    "name": "我的润色师",
    "description": "专注文笔润色的自定义角色",
    "icon": "✨",
    "system_prompt": "你是润色师，负责打磨文笔……",
    "tool_ids": ["count_words", "get_prior_summary", "save_draft"],
    "model_override": "zhipu/glm-4.5",
    "temperature_override": 0.6,
}
"""完整创建载荷基座（#11 roundtrip 契约）。

skill_ids 不在此常量内：skill_ids 引用校验（设计假设 #9/#14）要求引用
真实预插 skill，用例内经 _seed_skill 拿 id 后动态补入。
"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，test_chapter_api.py 同款 + 无 token 模式）。

    设计假设 #1/#2：显式 delenv INKFLOW_SERVER_TOKEN → token 中间件直通；
    ASGITransport 不触发 lifespan（#15），建表由 test_engine fixture 完成。
    """
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Seed / 断言辅助 ──


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
):
    """经 ORM 注入一条 Agent 记录（设计假设 #7）。

    ORM 契约：inkflow.infrastructure.database.models.agent.AgentORM（agents
    表），构造 kwargs name/description/icon/system_prompt/tool_ids/skill_ids/
    model_override/temperature_override/builtin；id 由 DB 默认生成。
    """
    from inkflow.infrastructure.database.models.agent import AgentORM

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
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _seed_skill(
    db_session,
    *,
    name: str,
    description: str = "",
    content: str = "",
    source: str = "user_upload",
):
    """经 ORM 注入一条 Skill 记录（设计假设 #7/#14）。

    ORM 契约：inkflow.infrastructure.database.models.skill.SkillORM（skills
    表），构造 kwargs name/description/content/source；id 由 DB 默认生成。
    供 skill_ids 引用校验用例的确定性造数（#14）。
    """
    from inkflow.infrastructure.database.models.skill import SkillORM

    row = SkillORM(name=name, description=description, content=content, source=source)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


def _assert_response_contract(data: dict) -> None:
    """响应结构契约（设计假设 #4）：12 键存在 + 值语义，不做整 dict 全等。"""
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
        "created_at",
        "updated_at",
    ):
        assert key in data, f"响应缺少契约字段 {key}"
    datetime.fromisoformat(data["created_at"])
    datetime.fromisoformat(data["updated_at"])
    assert isinstance(data["name"], str) and data["name"].strip() != ""
    assert isinstance(data["description"], str)
    assert isinstance(data["icon"], str)
    assert isinstance(data["system_prompt"], str)
    assert isinstance(data["tool_ids"], list)
    assert isinstance(data["skill_ids"], list)
    assert data["model_override"] is None or isinstance(data["model_override"], str)
    assert data["temperature_override"] is None or isinstance(
        data["temperature_override"], (int, float)
    )
    assert isinstance(data["builtin"], bool)


def _assert_tool_entry(tool: dict) -> None:
    """工具目录单项契约（设计假设 #6）：{name, description, group, input_schema}。"""
    assert isinstance(tool, dict)
    for key in ("name", "description", "group", "input_schema"):
        assert key in tool, f"工具目录项缺少契约字段 {key}"
    assert isinstance(tool["name"], str) and tool["name"] != ""
    assert isinstance(tool["description"], str)
    assert tool["group"] in TOOL_GROUPS, f"未知分组: {tool['group']}"
    assert isinstance(tool["input_schema"], dict)


def _assert_tool_catalog(items: list) -> None:
    """工具目录整体契约（设计假设 #6）：6 工具全集 + 末位 save_draft + 分组。"""
    assert isinstance(items, list)
    names = [t["name"] for t in items]
    assert set(names) == EXPECTED_TOOL_NAMES, f"工具目录名字全集不符: {names}"
    assert names[-1] == "save_draft", "目录排序：save_draft 必须为末位（先 5 只读）"
    for tool in items:
        _assert_tool_entry(tool)
    save_draft = next(t for t in items if t["name"] == "save_draft")
    assert save_draft["group"] == "writing"


# ── GET /api/v1/agents（spec §3.1 列表）──


@pytest.mark.asyncio
@pytest.mark.api
class TestListAgents:
    """Agent 列表端点契约（设计假设 #5）。"""

    async def test_list_empty_when_no_agents(self, client, db_session, override_get_db):
        """无 Agent → 200 + {items: [], total: 0}（不隐式造数，#5）。"""
        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_list_returns_seeded_agents(
        self, client, db_session, override_get_db
    ):
        """seed 2 条（1 自定义 + 1 内置）→ 200 + {items, total}；builtin 值回显。"""
        row_a = await _seed_agent(db_session, name="自定义甲", description="甲说明")
        row_b = await _seed_agent(
            db_session,
            name="内置乙",
            builtin=True,
            tool_ids=["count_words", "save_draft"],
        )

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        items = body["items"]
        assert len(items) == 2
        # 与 seed 行 id 一一对应（str 化比较）
        seeded_ids = {str(row_a.id), str(row_b.id)}
        assert {str(it["id"]) for it in items} == seeded_ids
        by_id = {str(it["id"]): it for it in items}
        for it in items:
            _assert_response_contract(it)
        # builtin 值回显（内置 / 自定义分流契约，#4）
        assert by_id[str(row_a.id)]["builtin"] is False
        assert by_id[str(row_b.id)]["builtin"] is True
        assert by_id[str(row_b.id)]["tool_ids"] == ["count_words", "save_draft"]


# ── GET /api/v1/agents/tools（spec §3.1 工具目录 + 路由顺序硬契约）──


@pytest.mark.asyncio
@pytest.mark.api
class TestToolCatalog:
    """工具目录端点契约（设计假设 #3/#6，M2 验收）。

    路由顺序硬契约的验证机制：若 GREEN 实现把 `GET /tools` 声明在
    `GET /{agent_id}` 之后，"tools" 会被 {agent_id} 路径参数捕获 →
    _parse_id 解析失败 → 404「Agent 不存在」→ 下方 200 断言 FAIL。
    """

    async def test_tools_route_not_swallowed_by_agent_id(
        self, client, db_session, override_get_db
    ):
        """GET /api/v1/agents/tools → 200（非 404）+ 顶层含 items 键（#3）。"""
        resp = await client.get(ENDPOINT_TOOLS)
        assert (
            resp.status_code == 200
        ), f"/tools 被 /{{agent_id}} 吞（路由顺序错）或端点未实现: {resp.status_code}"
        body = resp.json()
        assert isinstance(body, dict)
        assert "items" in body

    async def test_tools_catalog_six_tools_with_groups(
        self, client, db_session, override_get_db
    ):
        """工具目录：6 工具全集 + group 分组 + save_draft 末位（#6，M2）。"""
        resp = await client.get(ENDPOINT_TOOLS)
        assert resp.status_code == 200
        items = resp.json()["items"]
        _assert_tool_catalog(items)


# ── POST /api/v1/agents（spec §3.1 新建）──


@pytest.mark.asyncio
@pytest.mark.api
class TestCreateAgent:
    """新建端点契约（设计假设 #8/#9/#11/#14）。"""

    async def test_create_201_contract(self, client, db_session, override_get_db):
        """成功：201 + 完整响应；字段原样回显（skill_ids 引用真实 seed）；DB 落库。"""
        skill_a = await _seed_skill(db_session, name="润色方法论")
        skill_b = await _seed_skill(db_session, name="修订方法论")
        payload = {
            **FULL_AGENT_PAYLOAD,
            "skill_ids": [str(skill_a.id), str(skill_b.id)],
        }

        resp = await client.post(ENDPOINT, json=payload)
        assert resp.status_code == 201
        data = resp.json()
        _assert_response_contract(data)
        assert data["name"] == FULL_AGENT_PAYLOAD["name"]
        assert data["description"] == FULL_AGENT_PAYLOAD["description"]
        assert data["icon"] == FULL_AGENT_PAYLOAD["icon"]
        assert data["system_prompt"] == FULL_AGENT_PAYLOAD["system_prompt"]
        assert data["tool_ids"] == FULL_AGENT_PAYLOAD["tool_ids"]
        assert data["skill_ids"] == [str(skill_a.id), str(skill_b.id)]
        assert data["model_override"] == "zhipu/glm-4.5"
        assert data["temperature_override"] == 0.6
        assert data["builtin"] is False  # 新建恒为自定义 Agent（#11）
        # 集成断言：按 name 回查落库，id 与响应一致
        from inkflow.infrastructure.database.models.agent import AgentORM

        row = (
            await db_session.execute(
                select(AgentORM).where(AgentORM.name == FULL_AGENT_PAYLOAD["name"])
            )
        ).scalar_one()
        assert str(row.id) == str(data["id"])
        assert row.tool_ids == FULL_AGENT_PAYLOAD["tool_ids"]
        assert row.skill_ids == [str(skill_a.id), str(skill_b.id)]

    async def test_create_minimal_name_only(self, client, db_session, override_get_db):
        """最小 body 仅 {name} → 201；其余字段默认值语义（#11）。"""
        resp = await client.post(ENDPOINT, json={"name": "仅名称 Agent"})
        assert resp.status_code == 201
        data = resp.json()
        _assert_response_contract(data)
        assert data["name"] == "仅名称 Agent"
        assert data["description"] == ""
        assert data["icon"] == ""
        assert data["system_prompt"] == ""
        assert data["tool_ids"] == []
        assert data["skill_ids"] == []
        assert data["model_override"] is None
        assert data["temperature_override"] is None
        assert data["builtin"] is False

    @pytest.mark.parametrize(
        "body",
        [
            {},  # name 缺失
            {"name": "   "},  # name 空白
            {"name": "x", "temperature_override": 2.5},  # 温度越界（> 2.0）
            {"name": "x", "temperature_override": -0.1},  # 温度越界（< 0.0）
        ],
        ids=[
            "name_missing",
            "name_blank",
            "temp_above_max",
            "temp_below_min",
        ],
    )
    async def test_create_validation_422(
        self, client, db_session, override_get_db, body
    ):
        """name 缺失/空白、温度越界 → 422（Pydantic 校验错误列表，#8）。"""
        resp = await client.post(ENDPOINT, json=body)
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    async def test_create_extra_fields_ignored(
        self, client, db_session, override_get_db
    ):
        """多余字段忽略（不 422）→ 201（#8：Pydantic v2 默认行为）。"""
        resp = await client.post(
            ENDPOINT,
            json={"name": "my-agent", "foo": "bar", "extra_nested": {"a": 1}},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "my-agent"

    async def test_create_name_conflict_422(self, client, db_session, override_get_db):
        """同名 → 422（AgentNameConflictError，#9）；首建 201 且落库。"""
        resp = await client.post(ENDPOINT, json={"name": "唯一名甲"})
        assert resp.status_code == 201

        resp2 = await client.post(ENDPOINT, json={"name": "唯一名甲"})
        assert resp2.status_code == 422
        assert resp2.json()["detail"], "同名 422 detail 应为非空消息（#9）"

    async def test_create_tool_ids_unknown_422(
        self, client, db_session, override_get_db
    ):
        """tool_ids 含目录外工具名 → 422（ToolReferenceError，#9）。"""
        resp = await client.post(
            ENDPOINT, json={"name": "白名单错配", "tool_ids": ["no_such_tool"]}
        )
        assert resp.status_code == 422
        assert resp.json()["detail"], "目录外工具名 422 detail 应为非空消息（#9）"

    async def test_create_skill_ids_missing_422(
        self, client, db_session, override_get_db
    ):
        """skill_ids 含不存在 skill id → 422（SkillReferenceError，#9）。"""
        resp = await client.post(
            ENDPOINT, json={"name": "skill 错配", "skill_ids": ["999999"]}
        )
        assert resp.status_code == 422
        assert resp.json()["detail"], "不存在 skill id 422 detail 应为非空消息（#9）"

    async def test_create_with_seeded_skill_201(
        self, client, db_session, override_get_db
    ):
        """skill_ids 引用真实预插 skill → 201 且回显（#14 确定性造数）。"""
        skill = await _seed_skill(
            db_session, name="世界观方法论", description="世界观一致性方法论"
        )

        resp = await client.post(
            ENDPOINT, json={"name": "世界观顾问", "skill_ids": [str(skill.id)]}
        )
        assert resp.status_code == 201
        data = resp.json()
        _assert_response_contract(data)
        assert data["skill_ids"] == [str(skill.id)]


# ── GET /api/v1/agents/{agent_id}（spec §3.1 详情）──


@pytest.mark.asyncio
@pytest.mark.api
class TestGetAgent:
    """详情端点契约（设计假设 #4/#10）。"""

    async def test_get_detail_200(self, client, db_session, override_get_db):
        """详情：200 + 完整响应结构 + 字段回显（#4）。"""
        row = await _seed_agent(
            db_session,
            name="详情 Agent",
            description="详情说明",
            icon="🔍",
            system_prompt="你是详情演示 Agent",
            tool_ids=["count_words", "get_prior_summary"],
            model_override="deepseek/deepseek-chat",
            temperature_override=0.5,
        )

        resp = await client.get(f"{ENDPOINT}/{row.id}")
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_contract(data)
        assert str(data["id"]) == str(row.id)
        assert data["name"] == "详情 Agent"
        assert data["description"] == "详情说明"
        assert data["icon"] == "🔍"
        assert data["system_prompt"] == "你是详情演示 Agent"
        assert data["tool_ids"] == ["count_words", "get_prior_summary"]
        assert data["skill_ids"] == []
        assert data["model_override"] == "deepseek/deepseek-chat"
        assert data["temperature_override"] == 0.5
        assert data["builtin"] is False

    async def test_get_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id（int 域大数）→ 404 + detail「Agent 不存在」（#10）。"""
        resp = await client.get(f"{ENDPOINT}/999999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_get_invalid_id_404(self, client, db_session, override_get_db):
        """非法 id 格式（非整数）→ 404（非 422，镜像 _parse_id，#10）。"""
        resp = await client.get(f"{ENDPOINT}/not-an-int")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND


# ── PATCH /api/v1/agents/{agent_id}（spec §3.1 更新）──


@pytest.mark.asyncio
@pytest.mark.api
class TestUpdateAgent:
    """更新端点契约（设计假设 #10/#12/#13）。"""

    async def test_patch_partial_200(self, client, db_session, override_get_db):
        """部分更新：200 + 仅提供字段变更，未提供字段原样保留（#12）。"""
        row = await _seed_agent(
            db_session,
            name="my-agent",
            description="旧说明",
            system_prompt="旧 prompt",
            tool_ids=["count_words"],
        )

        resp = await client.patch(
            f"{ENDPOINT}/{row.id}",
            json={"name": "renamed", "system_prompt": "新 prompt"},
        )
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_contract(data)
        assert data["name"] == "renamed"
        assert data["system_prompt"] == "新 prompt"
        # exclude_unset 浅合并：未提供字段原样保留（#12）
        assert data["description"] == "旧说明"
        assert data["tool_ids"] == ["count_words"]
        assert data["skill_ids"] == []
        assert data["builtin"] is False

    async def test_patch_empty_body_ok(self, client, db_session, override_get_db):
        """空 body {} → 200 不变（全可选，#8/#12）。"""
        row = await _seed_agent(db_session, name="my-agent")

        resp = await client.patch(f"{ENDPOINT}/{row.id}", json={})
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_contract(data)
        assert data["name"] == "my-agent"

    async def test_patch_builtin_409(self, client, db_session, override_get_db):
        """内置 Agent（builtin=True）→ 409；记录仍存在（#13）。"""
        row = await _seed_agent(db_session, name="内置写手", builtin=True)

        resp = await client.patch(f"{ENDPOINT}/{row.id}", json={"name": "改名"})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert (
            isinstance(detail, str) and "内置" in detail
        ), f"409 detail 应含「内置」语义: {detail!r}"

        # 409 后记录未被修改
        resp2 = await client.get(f"{ENDPOINT}/{row.id}")
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "内置写手"

    async def test_patch_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id → 404（#10）。"""
        resp = await client.patch(f"{ENDPOINT}/999999", json={"name": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_patch_rename_conflict_422(self, client, db_session, override_get_db):
        """PATCH 改名撞已有名 → 422（AgentNameConflictError，#9）。"""
        row_a = await _seed_agent(db_session, name="甲")
        row_b = await _seed_agent(db_session, name="乙")

        resp = await client.patch(f"{ENDPOINT}/{row_b.id}", json={"name": "甲"})
        assert resp.status_code == 422
        assert resp.json()["detail"], "改名撞名 422 detail 应为非空消息（#9）"

        # 原记录未受影响
        resp2 = await client.get(f"{ENDPOINT}/{row_a.id}")
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "甲"

    @pytest.mark.parametrize(
        "body",
        [
            {"name": "   "},  # name 空白
            {"temperature_override": 2.5},  # 温度越界
        ],
        ids=["name_blank", "temp_out_of_range"],
    )
    async def test_patch_validation_422(
        self, client, db_session, override_get_db, body
    ):
        """PATCH 提供即校验：name 空白 / 温度越界 → 422（#8）。"""
        row = await _seed_agent(db_session, name="my-agent")
        resp = await client.patch(f"{ENDPOINT}/{row.id}", json=body)
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)


# ── DELETE /api/v1/agents/{agent_id}（spec §3.1 删除）──


@pytest.mark.asyncio
@pytest.mark.api
class TestDeleteAgent:
    """删除端点契约（设计假设 #10/#13）。"""

    async def test_delete_204_and_gone(self, client, db_session, override_get_db):
        """成功：204 空响应体；删除后 GET → 404（#10）。"""
        row = await _seed_agent(db_session, name="my-agent")

        resp = await client.delete(f"{ENDPOINT}/{row.id}")
        assert resp.status_code == 204
        assert resp.content == b""

        resp2 = await client.get(f"{ENDPOINT}/{row.id}")
        assert resp2.status_code == 404
        assert resp2.json()["detail"] == DETAIL_NOT_FOUND

    async def test_delete_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id → 404（#10）。"""
        resp = await client.delete(f"{ENDPOINT}/999999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_delete_invalid_id_404(self, client, db_session, override_get_db):
        """非法 id 格式 → 404（非 422，镜像 _parse_id，#10）。"""
        resp = await client.delete(f"{ENDPOINT}/not-an-int")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_delete_builtin_409(self, client, db_session, override_get_db):
        """内置 Agent（builtin=True）→ 409；记录仍存在（#13）。"""
        row = await _seed_agent(db_session, name="内置审校员", builtin=True)

        resp = await client.delete(f"{ENDPOINT}/{row.id}")
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert (
            isinstance(detail, str) and "内置" in detail
        ), f"409 detail 应含「内置」语义: {detail!r}"

        # 409 后记录未被删除
        resp2 = await client.get(f"{ENDPOINT}/{row.id}")
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "内置审校员"


# ═══ coverage 缺口补测（2026-08-16）：router 盲区行 + service 边界 ═══
# 测量盲区根因 1（aiosqlite 线程池 await 后行不记录，功能已由既有真实 DB 用例
# 覆盖）——mock 服务层补记（镜像 test_outline_api.py）；service 段补 L210/L221。


def _mock_agent(agent_id: int = 1, **overrides: object) -> Agent:
    """构造 router 响应断言用 Agent 实体（固定时间戳，镜像 unit 测试 _agent）。"""
    ts = datetime(2026, 8, 1, 10, 0, 0)
    fields: dict[str, object] = {
        "name": "mock-agent",
        "description": "",
        "icon": "",
        "system_prompt": "",
        "tool_ids": [],
        "skill_ids": [],
        "model_override": None,
        "temperature_override": None,
        "builtin": False,
        "created_at": ts,
        "updated_at": ts,
    }
    fields.update(overrides)
    return Agent(id=agent_id, **fields)


@pytest.mark.asyncio
@pytest.mark.api
class TestAgentRouterMockCoverage:
    """router 盲区行补覆盖：mock _get_service + AsyncMock service。

    补记 L88/119/131/144（成功 return）与 L68-73（异常映射 404/409/422）。
    """

    async def test_list_success_envelope(self, client) -> None:
        """list 成功：{items, total} 信封（覆盖 L86-88）。"""
        svc = MagicMock()
        svc.list = AsyncMock(return_value=[_mock_agent(1), _mock_agent(2)])
        with patch("inkflow.api.routers.agents._get_service", return_value=svc):
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_create_success_201(self, client) -> None:
        """create 成功：201 + 实体（覆盖 L117-119）。"""
        svc = MagicMock()
        svc.create = AsyncMock(return_value=_mock_agent(1))
        with patch("inkflow.api.routers.agents._get_service", return_value=svc):
            resp = await client.post(ENDPOINT, json={"name": "mock-agent"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "mock-agent"

    async def test_get_success_200(self, client) -> None:
        """get 成功：200 + 实体（覆盖 L128-131）。"""
        svc = MagicMock()
        svc.get = AsyncMock(return_value=_mock_agent(1))
        with patch("inkflow.api.routers.agents._get_service", return_value=svc):
            resp = await client.get(f"{ENDPOINT}/1")
        assert resp.status_code == 200
        assert str(resp.json()["id"]) == "1"

    async def test_update_success_200(self, client) -> None:
        """update 成功：200 + 实体（覆盖 L140-144）。"""
        svc = MagicMock()
        svc.update = AsyncMock(return_value=_mock_agent(1, name="renamed"))
        with patch("inkflow.api.routers.agents._get_service", return_value=svc):
            resp = await client.patch(f"{ENDPOINT}/1", json={"name": "renamed"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "renamed"

    async def test_not_found_404_mapping(self, client) -> None:
        """服务层 AgentNotFoundError → 404（覆盖 L68-69 异常映射）。"""
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=AgentNotFoundError())
        with patch("inkflow.api.routers.agents._get_service", return_value=svc):
            resp = await client.get(f"{ENDPOINT}/1")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_builtin_409_mapping(self, client) -> None:
        """服务层 AgentBuiltinError → 409（覆盖 L70-71 异常映射）。"""
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=AgentBuiltinError())
        with patch("inkflow.api.routers.agents._get_service", return_value=svc):
            resp = await client.delete(f"{ENDPOINT}/1")
        assert resp.status_code == 409
        assert "内置" in resp.json()["detail"]

    async def test_service_error_422_mapping(self, client) -> None:
        """服务层 AgentNameConflictError（AgentServiceError 子类）→ 422（覆盖 L72-73）。"""
        svc = MagicMock()
        svc.create = AsyncMock(side_effect=AgentNameConflictError())
        with patch("inkflow.api.routers.agents._get_service", return_value=svc):
            resp = await client.post(ENDPOINT, json={"name": "撞名"})
        assert resp.status_code == 422
        assert resp.json()["detail"]


@pytest.mark.asyncio
class TestAgentEntityServiceUpdateEdges:
    """服务层边界：update 竞态分支（agent_entity_service L210/L221）。

    真实 DB 下两分支不可达且 unit 未覆盖——直接构造 service + mock 仓储补记。
    """

    async def test_update_rename_no_conflict_merges(self) -> None:
        """name 变更但查重未命中 → 走 merged（L210 False 分支）。"""
        agent_repo = MagicMock(spec=AgentRepositoryProtocol)
        skill_repo = MagicMock(spec=SkillRepositoryProtocol)
        agent_repo.get = AsyncMock(return_value=_mock_agent(1))
        agent_repo.get_by_name = AsyncMock(return_value=None)
        agent_repo.update = AsyncMock(side_effect=lambda a: a)
        svc = AgentEntityService(
            agent_repository=agent_repo, skill_repository=skill_repo
        )

        merged = await svc.update(1, AgentUpdate(name="new-name"))
        assert merged.name == "new-name"
        agent_repo.get_by_name.assert_awaited_once()

    async def test_update_repo_returns_none_raises_not_found(self) -> None:
        """repo.update 返回 None（竞态已删）→ AgentNotFoundError（L220-221）。"""
        agent_repo = MagicMock(spec=AgentRepositoryProtocol)
        skill_repo = MagicMock(spec=SkillRepositoryProtocol)
        agent_repo.get = AsyncMock(return_value=_mock_agent(1))
        agent_repo.get_by_name = AsyncMock(return_value=None)
        agent_repo.update = AsyncMock(return_value=None)
        svc = AgentEntityService(
            agent_repository=agent_repo, skill_repository=skill_repo
        )

        with pytest.raises(AgentNotFoundError, match="不存在"):
            await svc.update(1, AgentUpdate(description="d2"))
        agent_repo.update.assert_awaited_once()


# ── #473 R1 role_key 透出（角色集合单一来源前置）──


@pytest.mark.asyncio
@pytest.mark.api
class TestRoleKeyExposure:
    """内置 Agent role_key 透出契约（#473 R1，角色集合单一来源前置）。

    设计假设 #17：内置 Agent 响应含 role_key 字段（str | None）——builtin=True
    且名字匹配 BUILTIN_AGENT_SPECS 出厂表 → 链角色键映射（架构师=architect、
    写手=writer、审校员=auditor、修订师=reviser）；非链内置（世界观顾问/
    润色师）与自定义 Agent → null。列表端点与详情端点都透出（前端
    AgentChainCard 按 role_key 派生角色行，不再 hardcode 名称/图标/描述）。
    """

    async def test_list_builtin_chain_roles_expose_role_key(
        self, client, db_session, override_get_db
    ):
        """seed 4 链内置（架构师/写手/审校员/修订师）→ 列表透出 role_key 映射。"""
        for name in ("架构师", "写手", "审校员", "修订师"):
            await _seed_agent(db_session, name=name, builtin=True)

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        by_name = {it["name"]: it for it in resp.json()["items"]}
        for name, role_key in (
            ("架构师", "architect"),
            ("写手", "writer"),
            ("审校员", "auditor"),
            ("修订师", "reviser"),
        ):
            assert by_name[name].get("role_key") == role_key, f"{name} role_key 映射错误"

    async def test_list_non_chain_builtin_role_key_none(
        self, client, db_session, override_get_db
    ):
        """非链内置（世界观顾问/润色师）→ role_key 为 None（#484 才动态化）。"""
        for name in ("世界观顾问", "润色师"):
            await _seed_agent(db_session, name=name, builtin=True)

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        by_name = {it["name"]: it for it in resp.json()["items"]}
        # sentinel 区分「字段缺失」vs「值为 null」——缺失时 get 返回 'MISSING' 才 FAIL
        # （防确认型假绿：字段未透出时「is None」断言天然通过）
        assert by_name["世界观顾问"].get("role_key", "MISSING") is None
        assert by_name["润色师"].get("role_key", "MISSING") is None

    async def test_list_custom_agent_role_key_none(
        self, client, db_session, override_get_db
    ):
        """自定义 Agent → role_key 为 None（非内置无链映射）。"""
        await _seed_agent(db_session, name="自定义甲")

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["builtin"] is False
        # sentinel 区分「字段缺失」vs「值为 null」（防确认型假绿）
        assert item.get("role_key", "MISSING") is None

    async def test_detail_exposes_role_key(
        self, client, db_session, override_get_db
    ):
        """详情端点同样透出 role_key（内置链角色 → 映射；自定义 → None）。"""
        builtin_row = await _seed_agent(db_session, name="架构师", builtin=True)
        custom_row = await _seed_agent(db_session, name="自定义乙")

        resp = await client.get(f"{ENDPOINT}/{builtin_row.id}")
        assert resp.status_code == 200
        assert resp.json().get("role_key") == "architect"

        resp = await client.get(f"{ENDPOINT}/{custom_row.id}")
        assert resp.status_code == 200
        # sentinel 区分「字段缺失」vs「值为 null」（防确认型假绿）
        assert resp.json().get("role_key", "MISSING") is None
