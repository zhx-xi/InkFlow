"""#954 F58 grants 授权数据面 — agents grants API 契约测试（TDD RED 阶段）。

被测模块：`inkflow/api/routers/agents.py`（POST/PATCH agents grants 字段 + 响应
grants/resolved_tool_names 透出）+ `inkflow/domain/models/agent_grants.py`
（GREEN 新增 ToolDomain/ToolOp/GrantEntry，本文件不 import）+
`inkflow/infrastructure/agent/tools/registry.py`（GREEN 新增
GRANT_TOOL_MAP/expand_grants/grants_from_tool_ids/resolve_grants）。

契约节（contract-954.md）：§3 服务层（create/update grants 语义）+ §4 API
（_to_response 两键追加）+ §7 行为语义（N3 写入回显 / N4 存量推断）+
specs/f58-agent-tool-scope/spec.md §3.1（Agent CRUD 端点扩展）。

RED 预期形态（当前 src 未实现 grants，本文件全部用例【R】必红）：
- AgentCreate/AgentUpdate 无 grants 字段 → POST grants 被 Pydantic v2 忽略
  （extra=ignore），响应不带 grants / resolved_tool_names 键 → 201 后断言
  KeyError / 值不符 → 红。
- GET /agents/{id} 响应无 grants / resolved_tool_names 键 → N4 存量推断
  用例与内置用例断言 KeyError → 红。
- PATCH grants 被忽略 → 200 响应无 grants；PATCH grants+tool_ids → 200
  （应 422）→ 红。
- 非法 domain / op 当前被忽略 → 201（应 422）→ 红。
- 直插内置行带 grants kwarg → AgentORM（agent_entity.py）无 grants 列 →
  函数内构造 TypeError → 红。

【R】/【G】标注：本文件全部用例为新建 grants 契约（无既有行为守护用例），
均【R】；迁移既有 catalog 守卫见 test_agents_tools_api.py（§8 处置）。
测试方式镜像 tests/api/test_agents_api.py（无 token 模式 + ASGITransport +
override_get_db + skills_root fixture）。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import inkflow.api.routers.agents  # noqa: F401  # 模块存在性契约（GREEN 后即被使用）
from inkflow.api.app import app

# ── 契约常量（contract §2.1 GRANT_TOOL_MAP 逐字派生，非 GREEN import）──

ENDPOINT = "/api/v1/agents"
"""Agent 端点前缀（spec §3.1）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 直通。"""

WRITING_READ_TOOLS = ["get_prior_summary", "audit_chapter", "count_words"]
"""writing·read 格（GRANT_TOOL_MAP (WRITING, READ) 插入序，contract §2.1）。"""

WRITING_WRITE_TOOLS = ["save_draft", "generate", "continue", "revise"]
"""writing·write 格（GRANT_TOOL_MAP (WRITING, WRITE) 插入序，contract §2.1）。"""


# ── Fixtures（镜像 test_agents_api.py #1/#2/#15）──


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式）。

    #1/#2：显式 delenv INKFLOW_SERVER_TOKEN → token 中间件直通；ASGITransport
    不触发 lifespan，建表由 test_engine fixture 完成。
    """
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def skills_root(monkeypatch, tmp_path) -> Path:
    """文件系统 skill 真源根（#522）：monkeypatch config.data_dir → tmp_path。

    镜像 test_agents_api.py #9；本文件 grants 用例 skill_ids=[]，无需 seed
    skill，但仍保留 fixture 以撑起「POST 走真实 create 服务」的隔离根。
    """
    core_config_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
    root = tmp_path / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ── 契约断言辅助 ──


def _assert_grants_shape(data: dict) -> None:
    """响应 grants/resolved_tool_names 两键形状契约（contract §4）：
    grants 为 JSON 形状列表（每项 domain:str + ops:list[str]），
    resolved_tool_names 为 str 列表；不断言 GREEN 新符号类型（避免 import）。"""
    assert "grants" in data, "响应缺少契约字段 grants"
    assert isinstance(data["grants"], list)
    for g in data["grants"]:
        assert isinstance(g, dict)
        assert isinstance(g.get("domain"), str) and g["domain"] != ""
        assert isinstance(g.get("ops"), list)
        for op in g["ops"]:
            assert isinstance(op, str)
    assert "resolved_tool_names" in data, "响应缺少契约字段 resolved_tool_names"
    assert isinstance(data["resolved_tool_names"], list)
    for name in data["resolved_tool_names"]:
        assert isinstance(name, str)


async def _seed_agent_row(db_session, *, name: str, tool_ids: list[str] | None = None):
    """经 AgentORM 直插一行自定义 Agent 记录（设计假设 #7，无 grants kwarg）。

    ⚠️ 本 helper 不传 grants kwarg（RED 期 AgentORM 无 grants 列；N4 存量行
    兼容用例即靠「grants 列缺省」触发读取期推断）。返回 ORM 行。
    """
    from inkflow.infrastructure.database.models.agent import AgentORM

    row = AgentORM(name=name, tool_ids=tool_ids or [])
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


# ── POST /api/v1/agents（grants 授权写入，contract §3/§7 N3）──


@pytest.mark.asyncio
@pytest.mark.api
class TestCreateAgentGrants:
    """POST grants 写入契约（contract §3 create + §7 N3）。"""

    async def test_create_grants_201_echo_resolved(
        self, client, db_session, override_get_db, skills_root
    ):
        """【R】grants=[{writing·read+write}] → 201；grants 回显同值；
        resolved_tool_names == GRANT_TOOL_MAP 展开序。"""
        payload = {
            "name": "写作配权",
            "grants": [{"domain": "writing", "ops": ["read", "write"]}],
            "skill_ids": [],
        }
        resp = await client.post(ENDPOINT, json=payload)
        assert resp.status_code == 201
        data = resp.json()
        _assert_grants_shape(data)
        assert data["grants"] == [{"domain": "writing", "ops": ["read", "write"]}]
        assert data["resolved_tool_names"] == (
            WRITING_READ_TOOLS + WRITING_WRITE_TOOLS
        )

    async def test_create_tool_ids_alias_201_grant_inference(
        self, client, db_session, override_get_db, skills_root
    ):
        """【R】仅 tool_ids=['count_words']（旧别名）→ 201；tool_ids 回显 +
        grants 推断 == writing·[read] + resolved_tool_names 扩权（3 工具）。"""
        payload = {"name": "旧别名配权", "tool_ids": ["count_words"], "skill_ids": []}
        resp = await client.post(ENDPOINT, json=payload)
        assert resp.status_code == 201
        data = resp.json()
        _assert_grants_shape(data)
        assert data["tool_ids"] == ["count_words"]
        assert data["grants"] == [{"domain": "writing", "ops": ["read"]}]
        assert data["resolved_tool_names"] == WRITING_READ_TOOLS

    async def test_create_grants_and_tool_ids_422(
        self, client, db_session, override_get_db
    ):
        """【R】同传 grants+tool_ids → 422；detail 为 str 业务消息，
        内容含 'grants' 或 'tool_ids'（contract §3 create 同传判定）。"""
        resp = await client.post(
            ENDPOINT,
            json={
                "name": "双传配权",
                "grants": [{"domain": "writing", "ops": ["read"]}],
                "tool_ids": ["count_words"],
            },
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, str), "同传 422 detail 应为 str 业务消息"
        assert "grants" in detail or "tool_ids" in detail, detail

    async def test_create_invalid_domain_422(
        self, client, db_session, override_get_db
    ):
        """【R】grants domain 非法（'nope'）→ 422；Pydantic 校验，detail 为
        list（枚举拒绝，contract §1 GrantEntry）。"""
        resp = await client.post(
            ENDPOINT,
            json={"name": "非法域", "grants": [{"domain": "nope", "ops": []}]},
        )
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    async def test_create_invalid_op_422(self, client, db_session, override_get_db):
        """【R】grants ops 非法（'nuke'）→ 422；Pydantic 校验，detail 为 list。"""
        resp = await client.post(
            ENDPOINT,
            json={"name": "非法操作", "grants": [{"domain": "writing", "ops": ["nuke"]}]},
        )
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)


# ── GET /api/v1/agents/{id}（存量兼容推断，contract §7 N4）──


@pytest.mark.asyncio
@pytest.mark.api
class TestGetAgentGrantsLegacy:
    """存量 tool_ids-only 行读取期推断（contract §3 create → §2.4 resolve_grants）。"""

    async def test_get_legacy_tool_ids_row_grant_inference(
        self, client, db_session, override_get_db
    ):
        """【R】N4 核心：AgentORM 直插 tool_ids=['search_characters','count_words']、
        grants 列缺省 → GET 200；grants==推断矩阵（character·[read]+writing·[read]，
        按 domain 枚举序 character<writing）+ resolved_tool_names 扩权（按映射序）。"""
        row = await _seed_agent_row(
            db_session, name="存量甲", tool_ids=["search_characters", "count_words"]
        )
        resp = await client.get(f"{ENDPOINT}/{row.id!s}")
        assert resp.status_code == 200
        data = resp.json()
        _assert_grants_shape(data)
        assert data["grants"] == [
            {"domain": "character", "ops": ["read"]},
            {"domain": "writing", "ops": ["read"]},
        ]
        assert data["resolved_tool_names"] == (
            ["search_characters", "get_character", *WRITING_READ_TOOLS]
        )


# ── PATCH /api/v1/agents/{id}（grants 更新，contract §3 update）──


@pytest.mark.asyncio
@pytest.mark.api
class TestUpdateAgentGrants:
    """PATCH grants 更新契约（contract §3 update：grants 提供 → tool_ids 清 []）。"""

    async def test_patch_grants_200_clears_tool_ids(
        self, client, db_session, override_get_db
    ):
        """【R】PATCH 带 grants → 200；响应 grants 新值 + tool_ids==[]
        （清幽灵，contract §3 update）。"""
        row = await _seed_agent_row(db_session, name="待更配权", tool_ids=["save_draft"])
        resp = await client.patch(
            f"{ENDPOINT}/{row.id!s}",
            json={"grants": [{"domain": "writing", "ops": ["read"]}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        _assert_grants_shape(data)
        assert data["grants"] == [{"domain": "writing", "ops": ["read"]}]
        assert data["tool_ids"] == []

    async def test_patch_grants_and_tool_ids_422(
        self, client, db_session, override_get_db
    ):
        """【R】PATCH 同传 grants+tool_ids → 422（业务 str 消息，同 create 判定）。"""
        row = await _seed_agent_row(db_session, name="待更双传", tool_ids=["save_draft"])
        resp = await client.patch(
            f"{ENDPOINT}/{row.id!s}",
            json={
                "grants": [{"domain": "writing", "ops": ["read"]}],
                "tool_ids": ["count_words"],
            },
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, str), "PATCH 同传 422 detail 应为 str 业务消息"
        assert "grants" in detail or "tool_ids" in detail, detail


# ── GET 内置 Agent grants 回显（contract §4 _to_response / §7 N3）──


@pytest.mark.asyncio
@pytest.mark.api
class TestGetBuiltinAgentGrants:
    """内置 Agent grants 非空回显契约（spec §4 内置卡片 + guard)."""

    async def test_get_builtin_grants_nonempty(
        self, client, db_session, override_get_db
    ):
        """【R】直插 builtin=True 行带 grants → GET 200；grants 非空回显。

        ⚠️ RED 期 AgentORM（agent_entity.py）无 grants kwarg → 函数内构造
        TypeError（预期红形态）；GREEN 后 grants 列存在 → 回显非空。
        """
        from inkflow.infrastructure.database.models.agent import AgentORM

        row = AgentORM(
            name="内置配权",
            builtin=True,
            tool_ids=["count_words"],
            grants=[{"domain": "writing", "ops": ["read", "write"]}],
        )
        db_session.add(row)
        await db_session.commit()
        await db_session.refresh(row)

        resp = await client.get(f"{ENDPOINT}/{row.id!s}")
        assert resp.status_code == 200
        data = resp.json()
        _assert_grants_shape(data)
        assert data["grants"], "内置 Agent grants 应为非空回显"
        assert data["grants"] == [{"domain": "writing", "ops": ["read", "write"]}]
