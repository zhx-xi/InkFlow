"""#485 Agent/Skill 复制（duplicate）端点 API 契约测试（TDD RED 阶段）。

本文件为既有 router（`api/routers/agents.py` / `api/routers/skills.py`）新增
「复制」端点定义 API 契约测试，覆盖 2 组端点（#485 需求：内置复制转用户态）：

- `POST /api/v1/agents/{agent_id}/duplicate` — 复制 Agent（201 完整实体）
- `POST /api/v1/skills/{skill_id}/duplicate`  — 复制 Skill（201 完整实体）

⚠️ 追加段方式：agents/skills 既有 API 测试文件已逼近 900 行护栏（test_agents_api.py
899 行 / test_skills_api.py 587 行），本文件独立成册，不修改既有两个测试文件。

权威来源：镜像 tests/api/test_agent_templates_api.py（F19 duplicate 用例 L776-815，
本契约定稿）语义 + tests/api/test_agents_api.py（F39 Agent/Skill 实体契约 +
_seed_agent/_seed_skill ORM 造数）+ tests/api/test_skills_api.py（Skill 8 键响应）。
测试方式镜像 test_agent_templates_api.py：无 token 模式 + ASGITransport +
override_get_db 真实 DB（tests/api/conftest.py + tests/conftest.py 内存 SQLite）。

════════════════════════════════════════════════════════════════════
错误映射表（契约，镜像 agents.py/skills.py 既有 _run_service）
════════════════════════════════════════════════════════════════════
- AgentNotFoundError  → 404（detail 即服务层消息「Agent 不存在」）
- SkillNotFoundError  → 404（detail 即服务层消息「Skill 不存在」）
- AgentNameConflictError（AgentServiceError 子类）→ 422（detail 非空即契约，
  不锁精确文案，镜像 test_agents_api.py 设计假设 #9）
- SkillNameConflictError（SkillServiceError 子类）→ 422（同上）

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【测试方式】ASGITransport + AsyncClient 直连真实 app 对象（import
   inkflow.api.app），`override_get_db` fixture（tests/api/conftest.py）将
   get_db 替换为测试 db_session（tests/conftest.py 内存 SQLite），app 与测试
   共享同一数据库。既有模块 `inkflow.api.routers.agents` / `...skills` 已存在
   （本文件不做收集期模块存在性断言——GREEN 只在既有 router 文件内追加端点）。
   所有用例显式 `@pytest.mark.asyncio` + `@pytest.mark.api`（免疫
   pytest-asyncio auto 模式差异，镜像 F19 惯例）。

2. 【无 token 模式——硬性契约】本文件所有用例依赖 env `INKFLOW_SERVER_TOKEN`
   未设置时中间件直通（test_settings_api.py 设计假设 #2 同款）：client fixture
   内显式 monkeypatch.delenv，免疫开发者本机 shell 的 env 残留导致假失败。

3. 【路径与 id 解析——硬性契约】duplicate 端点必须镜像既有 `_parse_id`
   语义：路径参数 str 声明 + 手动 int()，非法格式（非整数）→ 404
   「Agent 不存在」/「Skill 不存在」（禁止 `agent_id: int` FastAPI 类型声明，
   否则非整数被自动 422，破坏「非法 id → 404」契约——镜像 test_agents_api.py
   设计假设 #10 / test_skills_api.py #3）。

4. 【Agent 响应实体契约（spec §2.1 + #473 role_key 透出）】13 键：
   `{id, name, description, icon, system_prompt, tool_ids, skill_ids,
   model_override, temperature_override, builtin, role_key, created_at,
   updated_at}`（既有 `_to_response` 同形状）：
   - id：int 主键，测试一律 `str(row.id)` 驱动 URL、`str(data["id"])` 比对
   - name：str 非空白；tool_ids/skill_ids：list[str]（白名单）
   - model_override：str | None；temperature_override：float | None
   - builtin：bool —— 副本【恒 False】（#485 核心：内置复制转用户态，
     builtin=True 源复制后副本仍是用户可编辑的自定义 Agent）
   - role_key：键必存在；【副本不得继承源 role_key】（链角色键唯一性契约：
     内置「架构师」源 role_key="architect"，副本转用户态后为 None —— 本文件
     断言 `data["role_key"] != "architect"` 即「非源值」，不锁具体值，镜像
     任务契约「可不断言具体值或断言非源值」）
   - created_at/updated_at：ISO 8601 字符串（datetime.fromisoformat 可解析）
   - 只断言契约键存在 + 值语义，不做整 dict 全等（容忍 GREEN 额外字段）

5. 【Skill 响应实体契约（spec §2.2）】8 键：
   `{id, name, description, content, source, created_at, updated_at,
   agent_ids}`（既有 `_to_response(skill, agent_ids=...)` 同形状）：
   - content：完整 SKILL.md 原样存储（frontmatter + 正文，逐字 roundtrip）
   - source：`"builtin" | "user_upload"` —— 副本【恒 "user_upload"】（#485
     核心验收：内置复制转用户态；源为 user_upload 复制后仍 user_upload）
   - agent_ids：`[{id, name}]` 反查列表；新副本【无任何 Agent 引用 → []】
   - name：`f"{源 name} 副本"`（含空格，本契约定稿后缀，镜像 agent_templates
     duplicate）；内置中文名「架构方法论」副本名「架构方法论 副本」合法——
     duplicate 不走 frontmatter 校验（区别于 POST 创建端点的 frontmatter 解析）

6. 【duplicate 语义（镜像 agent_template_service.duplicate L130-154）】
   - 新 name = `f"{源 name} 副本"`；【同名查重】命中任意既有行（含自定义
     预插的同名行）→ 422（AgentNameConflictError / SkillNameConflictError）
   - id 重置（DB 自增分配新主键）；created_at/updated_at 重置
   - Agent 副本：builtin 重置 False、role_key 重置（不继承源值，见 #4）
   - Skill 副本：source 重置 "user_upload"（见 #5）
   - DB 中源 + 副本两行并存（集成断言：session 查表两个 name 都在）

7. 【404 语义】id 不存在（确定不存在的大整数，如 99999）或非法格式
   （非整数字符串 "abc"）→ 404 + `{"detail": "Agent 不存在"}` /
   `{"detail": "Skill 不存在"}`（镜像既有 _parse_id/_run_service 语义，
   非法格式不 422）。

8. 【422 校验——业务层】副本名冲突 → 422；detail 为服务层消息（str），
   本文件只断言状态码 + detail 非空，【不锁精确文案与 detail 类型】
   （镜像 test_agents_api.py 设计假设 #9）。

9. 【ORM 契约（seed 辅助用）】
   - `inkflow.infrastructure.database.models.agent_entity.AgentORM`（agents
     表；name 唯一；tool_ids/skill_ids 为 LenientJSON 列；role_key 列 #484），
     经 models/__init__.py re-export 可直接 `from
     inkflow.infrastructure.database.models import AgentORM`
   - `inkflow.infrastructure.database.models.skill.SkillORM`（skills 表；
     name 唯一；source 默认 "user_upload"），同源 re-export
   - 造数镜像 test_agents_api.py `_seed_agent`/`_seed_skill` 形态（本文件
     内复制辅助，不 import 测试模块）

10. 【lifespan/建表】ASGITransport 不触发 lifespan（test_chapter_api.py
    同款），建表由 test_engine fixture（tests/conftest.py）完成；本文件
    全部用例无 ./inkflow.db 副作用（不测 lifespan seed —— 内置行经
    `_seed_agent(builtin=True)` / `_seed_skill(source="builtin")` 预插驱动）。

════════════════════════════════════════════════════════════════════
RED 阶段预期（旧实现 duplicate 端点不存在 → 实测形态）
════════════════════════════════════════════════════════════════════
旧 router 未声明 `POST /{id}/duplicate` 路由 → FastAPI 路径不匹配 →
`POST .../duplicate` 返回 404 `{"detail": "Not Found"}`（FastAPI 默认
404，非 router 层「Agent 不存在」/「Skill 不存在」）：

- 【主 RED 信号】成功用例断言 `resp.status_code == 201` → 实际 404 → FAIL
  （4 条：Agent 成功 ×2 + Skill 成功 ×2）
- 422 用例断言 `resp.status_code == 422` → 实际 404 → FAIL（2 条）
- 404 用例：`status_code == 404` 断言【恰好 PASS（假绿守护）】，但 detail
  断言 `"Agent 不存在"` / `"Skill 不存在"` vs 实际 `"Not Found"` → FAIL
  （2 条，detail 为 RED 守护断言）

预期计数：8 failed / 0 passed。GREEN 阶段在 agents.py / skills.py 内追加
`POST /{id}/duplicate` 端点（_parse_id → service.duplicate → _run_service →
_to_response）并给 AgentEntityService / SkillService 增加 duplicate 方法后全绿。
"""

from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import inkflow.api.routers.agents  # 既有模块（GREEN 追加端点的宿主）
import inkflow.api.routers.skills  # noqa: F401  # 既有模块（GREEN 追加端点的宿主）
from inkflow.api.app import app
from inkflow.infrastructure.database.models import AgentORM, SkillORM

# ── 契约常量 ──

ENDPOINT_AGENTS = "/api/v1/agents"
"""Agent 端点前缀（spec §3.1）。"""

ENDPOINT_SKILLS = "/api/v1/skills"
"""Skill 端点前缀（spec §3.1）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（spec §2.3.1）：本文件全部用例依赖未设置 → 直通。"""

DETAIL_NOT_FOUND_AGENT = "Agent 不存在"
"""Agent id 不存在/非法格式的 404 detail（设计假设 #7，本契约定稿）。"""

DETAIL_NOT_FOUND_SKILL = "Skill 不存在"
"""Skill id 不存在/非法格式的 404 detail（设计假设 #7，本契约定稿）。"""

DUPLICATE_NAME_SUFFIX = " 副本"
"""duplicate 新实体 name 后缀（设计假设 #5/#6，本契约定稿，含前导空格）。"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，test_agent_templates_api.py 同款 + 无 token 模式）。

    设计假设 #1/#2：显式 delenv INKFLOW_SERVER_TOKEN → token 中间件直通；
    ASGITransport 不触发 lifespan（#10），建表由 test_engine fixture 完成。
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
    role_key: str | None = None,
):
    """经 ORM 注入一条 Agent 记录（设计假设 #9，镜像 test_agents_api.py）。

    role_key 列（#484）：内置源用例显式传入（如 "architect"）以获得确定性
    源值，供「副本不继承源 role_key」契约断言（#4）。
    """
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


async def _seed_skill(
    db_session,
    *,
    name: str,
    description: str = "",
    content: str = "",
    source: str = "user_upload",
):
    """经 ORM 注入一条 Skill 记录（设计假设 #9，镜像 test_agents_api.py）。

    内置源用例传 source="builtin"（源只读语义由 duplicate 契约豁免——复制
    允许，PATCH/DELETE 才 409）。
    """
    row = SkillORM(name=name, description=description, content=content, source=source)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


def _assert_agent_response_contract(data: dict) -> None:
    """Agent 响应结构契约（设计假设 #4）：13 键存在 + 值语义，不做整 dict 全等。"""
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
    """Skill 响应结构契约（设计假设 #5）：8 键存在 + 值语义，不做整 dict 全等。"""
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
    assert data["source"] in ("builtin", "user_upload")
    assert isinstance(data["agent_ids"], list)


# ── POST /api/v1/agents/{agent_id}/duplicate（#485 Agent 复制）──


@pytest.mark.asyncio
@pytest.mark.api
class TestDuplicateAgent:
    """Agent 复制端点契约（设计假设 #4/#6/#7/#8）。"""

    async def test_duplicate_builtin_source_201_user_state(
        self, client, db_session, override_get_db
    ):
        """内置源（builtin=True）→ 201 + 副本转用户态（builtin=False，#485 核心）。

        主 RED 信号：旧实现无 duplicate 端点 → 404「Not Found」≠ 201 → FAIL。
        契约：id ≠ 源 id；name = "架构师 副本"（含空格）；builtin=False；
        role_key 非源值（"architect" 不继承）；tool_ids/skill_ids 与源一致；
        DB 中两行并存。
        """
        # duplicate 对 skill_ids 做白名单校验（同 create）——必须先预插
        # 对应 Skill 行，否则副本校验 422（Codex GREEN 实证：#485 修复，
        # 原 hardcode "1" 无 Skill 行 → 422「skill_ids 含不存在的 Skill」）
        skill = await _seed_skill(
            db_session,
            name="架构方法论",
            description="章节结构/大纲规划方法论",
            content=(
                "---\nname: 架构方法论\ndescription: 章节结构/大纲规划方法论\n---\n# 架构方法论"
            ),
            source="builtin",
        )
        src = await _seed_agent(
            db_session,
            name="架构师",
            description="章节结构/大纲规划",
            icon="🏗️",
            system_prompt="你是架构师，负责章节结构与大纲规划。",
            tool_ids=["search_characters", "check_foreshadowing", "get_prior_summary"],
            skill_ids=[str(skill.id)],
            builtin=True,
            role_key="architect",
        )

        resp = await client.post(f"{ENDPOINT_AGENTS}/{src.id}/duplicate")
        assert resp.status_code == 201
        data = resp.json()
        _assert_agent_response_contract(data)
        assert str(data["id"]) != str(src.id), "副本 id 必须不同于源 Agent"
        assert data["name"] == f"架构师{DUPLICATE_NAME_SUFFIX}"
        assert data["description"] == "章节结构/大纲规划"
        assert data["icon"] == "🏗️"
        assert data["system_prompt"] == "你是架构师，负责章节结构与大纲规划。"
        assert data["tool_ids"] == [
            "search_characters",
            "check_foreshadowing",
            "get_prior_summary",
        ]
        assert data["skill_ids"] == [str(skill.id)]
        # #485 核心：内置复制转用户态 —— 副本 builtin 恒 False
        assert data["builtin"] is False, "内置 Agent 副本必须转用户态（builtin=False）"
        # 副本不得继承源 role_key（链角色键唯一性；转用户态后应为 None）
        assert data["role_key"] != "architect", "副本不得继承源 role_key"

        # DB 中两行并存（集成断言）
        rows = (await db_session.execute(select(AgentORM))).scalars().all()
        names = {r.name for r in rows}
        assert "架构师" in names and "架构师 副本" in names

    async def test_duplicate_custom_source_201(self, client, db_session, override_get_db):
        """自定义源（builtin=False）也可复制 → 201 + 副本 builtin=False（#4）。

        role_key 键存在但不断言具体值（GREEN 可给副本重新分配或 None）。
        """
        src = await _seed_agent(
            db_session,
            name="我的润色师",
            description="专注文笔润色的自定义角色",
            icon="✨",
            system_prompt="你是润色师，负责打磨文笔……",
            tool_ids=["count_words", "get_prior_summary", "save_draft"],
            model_override="zhipu/glm-4.5",
            temperature_override=0.6,
            builtin=False,
        )

        resp = await client.post(f"{ENDPOINT_AGENTS}/{src.id}/duplicate")
        assert resp.status_code == 201
        data = resp.json()
        _assert_agent_response_contract(data)
        assert str(data["id"]) != str(src.id), "副本 id 必须不同于源 Agent"
        assert data["name"] == f"我的润色师{DUPLICATE_NAME_SUFFIX}"
        assert data["builtin"] is False
        assert data["model_override"] == "zhipu/glm-4.5"
        assert data["temperature_override"] == 0.6
        assert data["tool_ids"] == ["count_words", "get_prior_summary", "save_draft"]
        assert data["skill_ids"] == []
        assert "role_key" in data  # 键存在即契约，不断言具体值

    async def test_duplicate_not_found_404(self, client, db_session, override_get_db):
        """id 不存在（99999）或非法格式（"abc"）→ 404 + detail「Agent 不存在」。

        ⚠️ RED 守护形态：旧实现无 duplicate 端点 → 路径不匹配 404
        {"detail": "Not Found"}——status_code==404 断言【假绿 PASS】，detail
        断言（"Not Found" ≠ "Agent 不存在"）FAIL 即本用例的 RED 信号；
        主 RED 信号见成功用例（期望 201 得 404）。GREEN 后两条断言全绿。
        """
        resp = await client.post(f"{ENDPOINT_AGENTS}/99999/duplicate")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND_AGENT

        resp2 = await client.post(f"{ENDPOINT_AGENTS}/abc/duplicate")
        assert resp2.status_code == 404
        assert resp2.json()["detail"] == DETAIL_NOT_FOUND_AGENT

    async def test_duplicate_name_conflict_422(self, client, db_session, override_get_db):
        """副本名冲突 → 422（#6/#8）：预插 name="架构师 副本" 的自定义 Agent。

        主 RED 信号：旧实现无 duplicate 端点 → 404「Not Found」≠ 422 → FAIL。
        detail 不锁精确文案（镜像 test_agents_api.py #9：业务层 422 detail 为
        服务层消息 str，只断言状态码 + detail 非空）。
        """
        src = await _seed_agent(
            db_session,
            name="架构师",
            builtin=True,
            role_key="architect",
        )
        # 预插同名冲突行（自定义 Agent，模拟用户已复制过一次）
        await _seed_agent(db_session, name=f"架构师{DUPLICATE_NAME_SUFFIX}")

        resp = await client.post(f"{ENDPOINT_AGENTS}/{src.id}/duplicate")
        assert resp.status_code == 422
        assert resp.json()["detail"]  # 非空即契约，不锁文案


# ── POST /api/v1/skills/{skill_id}/duplicate（#485 Skill 复制）──


@pytest.mark.asyncio
@pytest.mark.api
class TestDuplicateSkill:
    """Skill 复制端点契约（设计假设 #5/#6/#7/#8）。"""

    async def test_duplicate_builtin_source_201_user_state(
        self, client, db_session, override_get_db
    ):
        """内置源（source="builtin"）→ 201 + 副本转用户态（source="user_upload"）。

        主 RED 信号：旧实现无 duplicate 端点 → 404「Not Found」≠ 201 → FAIL。
        契约：id ≠ 源 id；name = "架构方法论 副本"（中文名 + 后缀合法——
        duplicate 不走 frontmatter 校验）；source="user_upload"（#485 核心
        验收）；content 逐字等于源 content；agent_ids=[]（新副本无引用）；
        DB 中两行并存。
        """
        src_content = (
            "---\nname: 架构方法论\ndescription: 章节结构/大纲规划\n---\n\n"
            "# 架构方法论\n\n章节结构设计与大纲规划的方法论正文。"
        )
        src = await _seed_skill(
            db_session,
            name="架构方法论",
            description="章节结构/大纲规划",
            content=src_content,
            source="builtin",
        )

        resp = await client.post(f"{ENDPOINT_SKILLS}/{src.id}/duplicate")
        assert resp.status_code == 201
        data = resp.json()
        _assert_skill_response_contract(data)
        assert str(data["id"]) != str(src.id), "副本 id 必须不同于源 Skill"
        assert data["name"] == f"架构方法论{DUPLICATE_NAME_SUFFIX}"
        assert data["description"] == "章节结构/大纲规划"
        # #485 核心验收：内置复制转用户态 —— 副本 source 恒 user_upload
        assert data["source"] == "user_upload", "内置 Skill 副本必须转用户态"
        # content 逐字拷贝（原样存储契约）
        assert data["content"] == src_content
        # 新副本无任何 Agent 引用
        assert data["agent_ids"] == []

        # DB 中两行并存（集成断言）
        rows = (await db_session.execute(select(SkillORM))).scalars().all()
        names = {r.name for r in rows}
        assert "架构方法论" in names and "架构方法论 副本" in names

    async def test_duplicate_user_upload_source_201(self, client, db_session, override_get_db):
        """user_upload 源也可复制 → 201 + 副本仍 user_upload（#5）。"""
        src_content = "---\nname: 自定义方法论\ndescription: 自建\n---\n\n自定义正文。"
        src = await _seed_skill(
            db_session,
            name="自定义方法论",
            description="自建",
            content=src_content,
            source="user_upload",
        )

        resp = await client.post(f"{ENDPOINT_SKILLS}/{src.id}/duplicate")
        assert resp.status_code == 201
        data = resp.json()
        _assert_skill_response_contract(data)
        assert str(data["id"]) != str(src.id), "副本 id 必须不同于源 Skill"
        assert data["name"] == f"自定义方法论{DUPLICATE_NAME_SUFFIX}"
        assert data["source"] == "user_upload"
        assert data["content"] == src_content
        assert data["agent_ids"] == []

    async def test_duplicate_not_found_404(self, client, db_session, override_get_db):
        """id 不存在（99999）或非法格式（"abc"）→ 404 + detail「Skill 不存在」。

        ⚠️ RED 守护形态：同 TestDuplicateAgent.test_duplicate_not_found_404
        （旧实现路径不匹配 → 404 {"detail": "Not Found"}，status_code 假绿
        PASS、detail 断言 FAIL 即 RED 信号；主 RED 信号见成功用例）。
        """
        resp = await client.post(f"{ENDPOINT_SKILLS}/99999/duplicate")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND_SKILL

        resp2 = await client.post(f"{ENDPOINT_SKILLS}/abc/duplicate")
        assert resp2.status_code == 404
        assert resp2.json()["detail"] == DETAIL_NOT_FOUND_SKILL

    async def test_duplicate_name_conflict_422(self, client, db_session, override_get_db):
        """副本名冲突 → 422（#6/#8）：预插 name="架构方法论 副本" 的 Skill。

        主 RED 信号：旧实现无 duplicate 端点 → 404「Not Found」≠ 422 → FAIL。
        """
        src = await _seed_skill(
            db_session,
            name="架构方法论",
            source="builtin",
        )
        # 预插同名冲突行（用户态 Skill，模拟用户已复制过一次）
        await _seed_skill(db_session, name=f"架构方法论{DUPLICATE_NAME_SUFFIX}")

        resp = await client.post(f"{ENDPOINT_SKILLS}/{src.id}/duplicate")
        assert resp.status_code == 422
        assert resp.json()["detail"]  # 非空即契约，不锁文案
