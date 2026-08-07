"""#107 F19-GUI 子任务 G — Agent 模板 API 测试契约（TDD RED 阶段）。

本文件为 `api/routers/agent_templates.py`（NEW，spec §9.3 端点表 + §9.2 引用式
模板实体方案，用户拍板 Q1=A 项目覆盖/Q2=A 默认模板实体化/Q3=A 级联清空）定义
API 测试契约，覆盖 7 组端点：

- `GET    /api/v1/agent-templates`            — 模板列表（{items, total} 信封）
- `POST   /api/v1/agent-templates`            — 新建（201）
- `GET    /api/v1/agent-templates/{id}`       — 详情（含 used_by 引用列表）/ 404
- `PATCH  /api/v1/agent-templates/{id}`       — 更新 / 404
- `DELETE /api/v1/agent-templates/{id}`       — 删除（204）/ 404 / 默认模板 409 保护
- `POST   /api/v1/agent-templates/{id}/duplicate` — 复制（201，name 加「副本」后缀）
- `GET/PATCH /api/v1/agent-templates/default` — 默认模板查询（200 {template: null}
  或模板）/ 设为默认（body {id}，单例语义）

权威来源：specs/f19-gui/spec.md §9（§9.1 实体形态、§9.2 引用式机制 + ProjectConfig
扩展、§9.3 API 契约表、§9.4 文件结构、§9.5 测试策略、§9.6 验收 M1/M2、§9.7 ADR、
§9.8 Q1/Q2/Q3）。测试方式镜像 tests/api/test_provider_config_api.py（#106，契约
docstring 风格 + 无 token 模式 + ASGITransport + override_get_db 真实 DB 模式）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【测试方式】ASGITransport + AsyncClient 直连真实 app 对象（import
   inkflow.api.app），`override_get_db` fixture（tests/api/conftest.py）将
   get_db 替换为测试 db_session（tests/conftest.py 内存 SQLite），app 与测试
   共享同一数据库。本文件模块级 `import inkflow.api.routers.agent_templates`
   为 RED 收集断言（模块不存在 → 全文件收集期 ModuleNotFoundError，
   即预期失败形态）。所有用例显式 `@pytest.mark.asyncio`（免疫
   pytest-asyncio auto 模式差异）。

2. 【无 token 模式——硬性契约】本文件所有用例依赖 env `INKFLOW_SERVER_TOKEN`
   未设置时中间件直通（test_settings_api.py 设计假设 #2 同款）：client fixture
   内显式 monkeypatch.delenv，免疫开发者本机 shell 的 env 残留导致假失败。

3. 【模块契约】`inkflow.api.routers.agent_templates` 必须暴露：
   - `router = APIRouter(prefix="/api/v1/agent-templates", tags=["AgentTemplates"])`
     （app.py 需 `app.include_router(agent_templates.router)`，与既有 router
     模块级模式一致）
   - 【路由声明顺序——硬性契约】`GET /default` 与 `PATCH /default` 必须声明在
     `GET /{template_id}` 与 `PATCH /{template_id}` 之前（FastAPI 按声明顺序
     匹配：反序时 "default" 会被吞进 {template_id} 解析失败 → 404，默认模板
     用例全红）。

4. 【响应结构——实体契约（spec §9.1 实体字段）】模板响应：
   `{id, name, description, main_model, default_temperature,
   roles: {architect: {model, temperature, enabled}, writer: {...},
   auditor: {...}, reviser: {...}}, default_words, is_default,
   created_at, updated_at}`：
   - id：str 或 int 均可（ORM 主键自增整数或 UUID 皆可），测试一律以
     `str(row.id)` 驱动 URL、`str(data["id"])` 比对，不契约 id 类型
   - roles：dict，【恰好】含 4 个角色键 architect/writer/auditor/reviser
     （spec §9.1 四角色）；每个角色值为 dict {model: str, temperature:
     float|None, enabled: bool}（enabled=False = 该角色 model 不覆盖，§9.2.5）
   - is_default：bool —— 是否当前默认模板（§9.7 默认模板实体化）
   - created_at/updated_at：ISO 8601 字符串（datetime.fromisoformat 可解析）
   - 响应可含实体额外字段，本文件只断言契约键存在 + 值语义，
     【不做整 dict 全等】（容忍 GREEN 输出额外字段）

5. 【used_by 仅详情端点】`GET /api/v1/agent-templates/{id}` 额外含
   `used_by: [{id, name}]`（引用该模板的项目列表，spec §9.2.4 风险确认数据；
   实现提示 SQLite json_extract(config,'$.template_id')）。列表端点与
   POST/PATCH/duplicate 响应【不含 used_by】（不契约，容忍存在与否——
   断言辅助只对 detail=True 校验 used_by 键）。

6. 【列表端点】GET /api/v1/agent-templates → 200 + `{items: [...], total: N}`
   （repo 列表端点惯例：foreshadowings/volumes/provider-configs 同款
   envelope）。本契约只约束 items/total 两键（GREEN 可额外输出
   offset/limit 等分页字段）；无数据时 total=0、items=[]；每项满足
   基础响应契约（含 is_default）。

7. 【ORM 契约（seed 辅助用）】
   `inkflow.infrastructure.database.models.agent_template.AgentTemplateORM`，
   构造 kwargs name/description/main_model/default_temperature/roles/
   default_words（roles 为 JSON 列 dict，仿 ProjectORM.config），表名
   `agent_templates`，id 由 DB 默认生成；需在
   `infrastructure/database/models/__init__.py` 导出（注册进 Base.metadata，
   测试 test_engine fixture 的 create_all 才会建表）。

8. 【422 校验】POST：name 必填（缺失 / 空白 "   " → 422）；
   default_temperature ∈ [0.0, 2.0]（越界 → 422）；roles[].temperature
   同样 ∈ [0.0, 2.0]（越界 → 422）；多余字段忽略（Pydantic v2 默认行为，
   不 422）。PATCH：全可选（`{}` 合法 → 200 不变），提供即校验（name
   空白 / default_temperature 越界 → 422）。422 响应 detail 为 Pydantic
   校验错误列表。

9. 【404 语义】id 不存在或非法格式（非 UUID / 非整数）→ 404 +
   `{"detail": "模板不存在"}`（镜像 foreshadowings `_parse_id` 404 语义，
   非法格式不 422）。

10. 【创建契约】POST → 201 + 完整响应结构；name/description/main_model/
    default_temperature/default_words/roles 原样回显（roles 逐项 roundtrip
    相等）；is_default=False（新建默认非默认模板，默认模板只能经
    PATCH /default 设置）；DB 按 name 回查落库且 id 与响应一致（集成断言）。
    最小 body 仅 {name} 即可创建 —— roles 响应仍含 4 角色键（GREEN 提供
    默认 roles 结构）。

11. 【PATCH 语义】exclude_unset 浅合并（spec §9.1「PATCH config 浅合并」
    同款语义）：仅更新提供字段，未提供字段原样保留；roles 提供则
    【整体替换】（不深合并，镜像 #106 models 语义）。

12. 【删除契约】DELETE → 204 空响应体；不存在 → 404；
    【默认模板保护——本契约定稿】is_default=True 的模板 → 409 +
    `{"detail": "默认模板不可删除"}`（spec §9.7「内置模板不可删」实体化
    等价实现；409 后记录仍存在）；被引用但非默认模板 → 允许删除（204，
    spec §9.8 Q3=A：提示 + 回退默认，见 #15）。

13. 【默认模板契约——本契约定稿】
    - `GET /api/v1/agent-templates/default` → 200；无默认模板时
      `{"template": null}`（【不 404】：查询状态而非资源，前端可空态处理）；
      有默认时 `{"template": {完整模板响应}}`
    - `PATCH /api/v1/agent-templates/default` body `{"id": "<模板 id>"}`
      → 200 + 完整模板响应（is_default=True）；id 不存在/非法 → 404；
      body 缺 id / id 空白 → 422
    - 【单例语义】设 B 为默认后，A（原默认）is_default 自动变 False
      （spec §9.7「默认模板 = 系统内置」实体化：全表至多一条 is_default=True）

14. 【duplicate 契约】POST /{id}/duplicate → 201 + 完整模板响应；新 id ≠
    旧 id；name = `f"{旧 name} 副本"`（本契约定稿后缀）；其余字段
    （description/main_model/default_temperature/default_words/roles）
    原样拷贝；is_default=False（副本不继承默认位）；DB 中两行并存。
    不存在的 id → 404。

15. 【风险确认数据 + 级联清空（spec §9.2.4/§9.8 Q3=A）】
    - used_by 断言全链路：POST /api/v1/agent-templates 建模板 → POST
      /api/v1/projects body {name, genre, language, target_words,
      config: {"template_id": str(模板 id)}}（**#107 ProjectConfig 扩展
      契约**：`ProjectConfig.template_id: str | None = None`，spec §9.2.2
      MODIFY domain/models/project.py —— RED 阶段该字段不存在，extra 被
      Pydantic 忽略 → config 未落 template_id → used_by 空，即预期 RED
      形态）→ GET 项目详情 config.template_id == str(模板 id) → GET
      模板详情 used_by 含 {id: 项目 id, name: 项目名}
    - 删除被引用（非默认）模板 → 204；随后 GET 项目详情
      config.template_id 为 None（级联清空一次写，不做 load 兜底）——
      断言用 `config.get("template_id") is None`（容忍键缺失与显式 null
      两种落盘形态）。

16. 【lifespan/建表】ASGITransport 不触发 lifespan（test_chapter_api.py
    同款），建表由 test_engine fixture（tests/conftest.py）完成；本文件
    全部用例无 ./inkflow.db 副作用（不测 lifespan seed —— 模板无 seed
    契约，默认模板由 PATCH /default 设置，非内置行）。

17. 【独立于 #106/#79】本文件只契约 agent-templates 端点；provider-configs、
    settings/llm-keys 等既有端点不在本文件覆盖范围。项目创建走既有
    /api/v1/projects（真实 service + 真实 repo，override_get_db 同库）。

════════════════════════════════════════════════════════════════════
RED 阶段预期：`inkflow.api.routers.agent_templates` 模块不存在 → 本文件
【收集期 ModuleNotFoundError】collected 0 items（router 未注册，请求亦
404）。GREEN 阶段：按上述契约实现 §9.4 NEW ×7（domain/models/
agent_template.py、domain/ports/agent_template_repository.py + _errors.py、
domain/services/agent_template_service.py、infrastructure/database/models/
agent_template.py、infrastructure/database/repositories/agent_template_repo.py、
api/routers/agent_templates.py）+ MODIFY（project.py ProjectConfig 加
template_id、database/models/__init__.py、api/app.py include_router、
api/deps.py 装配）后全绿。
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient  # noqa: F401  # lifespan 用例预留（镜像 #106）
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import inkflow.api.routers.agent_templates  # noqa: F401  # RED 收集断言：模块存在性契约（GREEN 实现后即被使用）
from inkflow.api.app import app

# ── 契约常量 ──

ENDPOINT = "/api/v1/agent-templates"
"""Agent 模板端点前缀（spec §9.3）。"""

ENDPOINT_PROJECTS = "/api/v1/projects"
"""项目端点前缀（used_by 风险确认数据全链路用，设计假设 #15）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（spec §2.3.1）：本文件全部用例依赖未设置 → 直通。"""

DETAIL_NOT_FOUND = "模板不存在"
"""id 不存在/非法格式的 404 detail（设计假设 #9）。"""

DETAIL_DEFAULT_DELETE = "默认模板不可删除"
"""删除默认模板的 409 detail（设计假设 #12，本契约定稿）。"""

DUPLICATE_NAME_SUFFIX = " 副本"
"""duplicate 新模板 name 后缀（设计假设 #14，本契约定稿）。"""

ROLE_KEYS = ["architect", "writer", "auditor", "reviser"]
"""模板 roles 四角色键（spec §9.1，顺序契约）。"""

ROLES_PAYLOAD = {
    "architect": {"model": "openai/gpt-4o", "temperature": 0.7, "enabled": True},
    "writer": {"model": "openai/gpt-4o", "temperature": 0.8, "enabled": True},
    "auditor": {"model": "openai/gpt-4o", "temperature": 0.5, "enabled": True},
    "reviser": {"model": "openai/gpt-4o", "temperature": 0.6, "enabled": False},
}
"""完整 roles 载荷（含 enabled=False 的 reviser，验证 enabled 回显，#10）。"""

FULL_TEMPLATE_PAYLOAD = {
    "name": "标准小说模板",
    "description": "四角色完整配置模板",
    "main_model": "openai/gpt-4o",
    "default_temperature": 0.7,
    "roles": ROLES_PAYLOAD,
    "default_words": 100000,
}
"""完整创建载荷（#10 roundtrip 契约）。"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，test_chapter_api.py 同款 + 无 token 模式）。

    设计假设 #1/#2：显式 delenv INKFLOW_SERVER_TOKEN → token 中间件直通；
    ASGITransport 不触发 lifespan（#16），建表由 test_engine fixture 完成。
    """
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Seed / 断言辅助 ──


async def _seed_template(
    db_session,
    *,
    name: str,
    description: str = "",
    main_model: str = "openai/gpt-4o",
    default_temperature: float = 0.7,
    roles: dict | None = None,
    default_words: int = 100000,
):
    """经 ORM 注入一条 AgentTemplate 记录（设计假设 #7）。

    ORM 契约：inkflow.infrastructure.database.models.agent_template.
    AgentTemplateORM，构造 kwargs name/description/main_model/
    default_temperature/roles/default_words（roles 为 JSON 列 dict）；
    id 由 DB 默认生成。
    """
    from inkflow.infrastructure.database.models.agent_template import (
        AgentTemplateORM,
    )

    row = AgentTemplateORM(
        name=name,
        description=description,
        main_model=main_model,
        default_temperature=default_temperature,
        roles=roles or {},
        default_words=default_words,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


def _assert_roles_contract(roles) -> None:
    """roles 契约（#4）：恰好 4 角色键，每项 {model, temperature, enabled}。"""
    assert isinstance(roles, dict)
    assert list(roles.keys()) == ROLE_KEYS, f"roles 键序/键集不符: {list(roles.keys())}"
    for role_key in ROLE_KEYS:
        role = roles[role_key]
        assert isinstance(role, dict), f"roles[{role_key}] 应为 dict"
        assert "model" in role and isinstance(role["model"], str)
        assert "temperature" in role and (
            role["temperature"] is None or isinstance(role["temperature"], float)
        )
        assert "enabled" in role and isinstance(role["enabled"], bool)


def _assert_response_contract(data: dict, *, detail: bool = False) -> None:
    """响应结构契约（设计假设 #4/#5）：10 键存在 + 值语义，不做整 dict 全等。

    detail=True 时额外校验 used_by 键（仅详情端点契约，#5）。
    """
    for key in (
        "id",
        "name",
        "description",
        "main_model",
        "default_temperature",
        "roles",
        "default_words",
        "is_default",
        "created_at",
        "updated_at",
    ):
        assert key in data, f"响应缺少契约字段 {key}"
    datetime.fromisoformat(data["created_at"])
    datetime.fromisoformat(data["updated_at"])
    assert isinstance(data["is_default"], bool)
    # spec §9.2：default_temperature 为 float | None（None = 跟随默认，
    # 温度链第 3 级「非 None」语义）
    assert data["default_temperature"] is None or isinstance(
        data["default_temperature"], (int, float)
    )
    _assert_roles_contract(data["roles"])
    if detail:
        used_by = data.get("used_by")
        assert isinstance(used_by, list), "详情响应缺 used_by 列表（#5）"
        for entry in used_by:
            assert isinstance(entry, dict)
            assert "id" in entry and "name" in entry


# ── GET /api/v1/agent-templates（spec §9.3 列表）──


@pytest.mark.asyncio
@pytest.mark.api
class TestListAgentTemplates:
    """模板列表端点契约（设计假设 #6）。"""

    async def test_list_empty_when_no_templates(
        self, client, db_session, override_get_db
    ):
        """无模板 → 200 + {items: [], total: 0}（不隐式造数，#6）。"""
        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_list_returns_seeded_templates(
        self, client, db_session, override_get_db
    ):
        """seed 2 条 → 200 + {items, total}；每项满足基础响应契约（#6）。"""
        row_a = await _seed_template(db_session, name="模板甲")
        row_b = await _seed_template(
            db_session,
            name="模板乙",
            description="乙的说明",
            default_temperature=0.5,
            roles=ROLES_PAYLOAD,
        )

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        items = body["items"]
        assert len(items) == 2
        # 与 seed 行 id 一一对应（str 化比较，容忍 int/UUID 两种主键）
        seeded_ids = {str(row_a.id), str(row_b.id)}
        assert {str(it["id"]) for it in items} == seeded_ids
        for it in items:
            _assert_response_contract(it)
            assert it["is_default"] is False


# ── POST /api/v1/agent-templates（spec §9.3 新建）──


@pytest.mark.asyncio
@pytest.mark.api
class TestCreateAgentTemplate:
    """新建端点契约（设计假设 #8/#10）。"""

    async def test_create_201_contract(self, client, db_session, override_get_db):
        """成功：201 + 完整响应；字段原样回显（roles 逐项相等）；DB 落库（#10）。"""
        resp = await client.post(ENDPOINT, json=FULL_TEMPLATE_PAYLOAD)
        assert resp.status_code == 201
        data = resp.json()
        _assert_response_contract(data)
        assert data["name"] == FULL_TEMPLATE_PAYLOAD["name"]
        assert data["description"] == FULL_TEMPLATE_PAYLOAD["description"]
        assert data["main_model"] == FULL_TEMPLATE_PAYLOAD["main_model"]
        assert (
            data["default_temperature"] == FULL_TEMPLATE_PAYLOAD["default_temperature"]
        )
        assert data["roles"] == ROLES_PAYLOAD
        assert data["default_words"] == FULL_TEMPLATE_PAYLOAD["default_words"]
        assert data["is_default"] is False  # 新建不自动成为默认（#10）

        # 集成断言：按 name 回查落库，id 与响应一致
        from inkflow.infrastructure.database.models.agent_template import (
            AgentTemplateORM,
        )

        row = (
            await db_session.execute(
                select(AgentTemplateORM).where(
                    AgentTemplateORM.name == FULL_TEMPLATE_PAYLOAD["name"]
                )
            )
        ).scalar_one()
        assert str(row.id) == str(data["id"])
        assert row.roles == ROLES_PAYLOAD
        assert row.default_temperature == FULL_TEMPLATE_PAYLOAD["default_temperature"]

    async def test_create_minimal_name_only(self, client, db_session, override_get_db):
        """最小 body 仅 {name} → 201；roles 响应仍含 4 角色键（#10）。"""
        resp = await client.post(ENDPOINT, json={"name": "仅名称模板"})
        assert resp.status_code == 201
        data = resp.json()
        _assert_response_contract(data)
        assert data["name"] == "仅名称模板"
        assert data["description"] == ""
        assert data["is_default"] is False

    @pytest.mark.parametrize(
        "body",
        [
            {},  # name 缺失
            {"name": "   "},  # name 空白
            {"name": "x", "default_temperature": 2.5},  # 默认温度越界（> 2.0）
            {
                "name": "x",
                "roles": {"architect": {"model": "m", "temperature": -0.1}},
            },  # 角色温度越界（< 0.0）
        ],
        ids=[
            "name_missing",
            "name_blank",
            "default_temp_out_of_range",
            "role_temp_out_of_range",
        ],
    )
    async def test_create_validation_422(
        self, client, db_session, override_get_db, body
    ):
        """name 缺失/空白、温度越界 → 422（#8）。"""
        resp = await client.post(ENDPOINT, json=body)
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    async def test_create_extra_fields_ignored(
        self, client, db_session, override_get_db
    ):
        """多余字段忽略（不 422）→ 201（#8：Pydantic v2 默认行为）。"""
        resp = await client.post(
            ENDPOINT,
            json={"name": "my-template", "foo": "bar", "extra_nested": {"a": 1}},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "my-template"


# ── GET /api/v1/agent-templates/{id}（spec §9.3 详情）──


@pytest.mark.asyncio
@pytest.mark.api
class TestGetAgentTemplate:
    """详情端点契约（设计假设 #5/#9）。"""

    async def test_get_detail_200(self, client, db_session, override_get_db):
        """详情：200 + 完整响应结构 + used_by=[]（无引用，#5）。"""
        row = await _seed_template(
            db_session,
            name="详情模板",
            description="详情说明",
            main_model="deepseek/deepseek-chat",
            default_temperature=0.5,
            roles=ROLES_PAYLOAD,
            default_words=50000,
        )

        resp = await client.get(f"{ENDPOINT}/{row.id}")
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_contract(data, detail=True)
        assert str(data["id"]) == str(row.id)
        assert data["name"] == "详情模板"
        assert data["description"] == "详情说明"
        assert data["main_model"] == "deepseek/deepseek-chat"
        assert data["default_temperature"] == 0.5
        assert data["roles"] == ROLES_PAYLOAD
        assert data["default_words"] == 50000
        assert data["used_by"] == []  # 无引用项目

    async def test_get_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id → 404 + detail "模板不存在"（#9）。"""
        resp = await client.get(f"{ENDPOINT}/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_get_invalid_id_404(self, client, db_session, override_get_db):
        """非法 id 格式（非 UUID/非整数）→ 404（非 422，镜像 _parse_id，#9）。"""
        resp = await client.get(f"{ENDPOINT}/not-a-uuid")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND


# ── PATCH /api/v1/agent-templates/{id}（spec §9.3 更新）──


@pytest.mark.asyncio
@pytest.mark.api
class TestUpdateAgentTemplate:
    """更新端点契约（设计假设 #9/#11）。"""

    async def test_patch_partial_200(self, client, db_session, override_get_db):
        """部分更新：200 + 仅提供字段变更，未提供字段原样保留（#11）。"""
        row = await _seed_template(
            db_session,
            name="my-template",
            description="旧说明",
            main_model="openai/gpt-4o",
            default_temperature=0.7,
            roles=ROLES_PAYLOAD,
            default_words=100000,
        )

        resp = await client.patch(
            f"{ENDPOINT}/{row.id}",
            json={"name": "renamed", "default_temperature": 0.9},
        )
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_contract(data)
        assert data["name"] == "renamed"
        assert data["default_temperature"] == 0.9
        # exclude_unset 浅合并：未提供字段原样保留
        assert data["description"] == "旧说明"
        assert data["main_model"] == "openai/gpt-4o"
        assert data["roles"] == ROLES_PAYLOAD
        assert data["default_words"] == 100000

    async def test_patch_empty_body_ok(self, client, db_session, override_get_db):
        """空 body {} → 200 不变（全可选，#8/#11）。"""
        row = await _seed_template(db_session, name="my-template")

        resp = await client.patch(f"{ENDPOINT}/{row.id}", json={})
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_contract(data)
        assert data["name"] == "my-template"

    async def test_patch_roles_replaced_whole(
        self, client, db_session, override_get_db
    ):
        """roles 提供则整体替换（不深合并，#11）。"""
        row = await _seed_template(db_session, name="my-template", roles=ROLES_PAYLOAD)

        new_roles = {
            "architect": {
                "model": "deepseek/deepseek-chat",
                "temperature": 0.3,
                "enabled": True,
            },
            "writer": {
                "model": "deepseek/deepseek-chat",
                "temperature": 0.3,
                "enabled": True,
            },
            "auditor": {
                "model": "deepseek/deepseek-chat",
                "temperature": 0.3,
                "enabled": False,
            },
            "reviser": {
                "model": "deepseek/deepseek-chat",
                "temperature": 0.3,
                "enabled": False,
            },
        }
        resp = await client.patch(f"{ENDPOINT}/{row.id}", json={"roles": new_roles})
        assert resp.status_code == 200
        assert resp.json()["roles"] == new_roles

    async def test_patch_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id → 404（#9）。"""
        resp = await client.patch(f"{ENDPOINT}/{uuid.uuid4()}", json={"name": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    @pytest.mark.parametrize(
        "body",
        [
            {"name": "   "},  # name 空白
            {"default_temperature": 2.5},  # 温度越界
        ],
        ids=["name_blank", "default_temp_out_of_range"],
    )
    async def test_patch_validation_422(
        self, client, db_session, override_get_db, body
    ):
        """PATCH 提供即校验：name 空白 / 温度越界 → 422（#8）。"""
        row = await _seed_template(db_session, name="my-template")
        resp = await client.patch(f"{ENDPOINT}/{row.id}", json=body)
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)


# ── DELETE /api/v1/agent-templates/{id}（spec §9.3 删除）──


@pytest.mark.asyncio
@pytest.mark.api
class TestDeleteAgentTemplate:
    """删除端点契约（设计假设 #9/#12/#15）。"""

    async def test_delete_204_and_gone(self, client, db_session, override_get_db):
        """成功：204 空响应体；删除后 GET → 404（#12）。"""
        row = await _seed_template(db_session, name="my-template")

        resp = await client.delete(f"{ENDPOINT}/{row.id}")
        assert resp.status_code == 204
        assert resp.content == b""

        resp2 = await client.get(f"{ENDPOINT}/{row.id}")
        assert resp2.status_code == 404
        assert resp2.json()["detail"] == DETAIL_NOT_FOUND

    async def test_delete_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id → 404（#9）。"""
        resp = await client.delete(f"{ENDPOINT}/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_delete_invalid_id_404(self, client, db_session, override_get_db):
        """非法 id 格式 → 404（非 422，镜像 _parse_id，#9）。"""
        resp = await client.delete(f"{ENDPOINT}/not-a-uuid")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_delete_default_template_409(
        self, client, db_session, override_get_db
    ):
        """删除 is_default=True 的模板 → 409 + 保护 detail；记录仍存在（#12）。"""
        row = await _seed_template(db_session, name="默认模板")

        # 先经 PATCH /default 设为默认
        resp = await client.patch(f"{ENDPOINT}/default", json={"id": str(row.id)})
        assert resp.status_code == 200

        resp2 = await client.delete(f"{ENDPOINT}/{row.id}")
        assert resp2.status_code == 409
        assert resp2.json()["detail"] == DETAIL_DEFAULT_DELETE

        # 409 后记录未被删除
        resp3 = await client.get(f"{ENDPOINT}/{row.id}")
        assert resp3.status_code == 200
        assert resp3.json()["name"] == "默认模板"


# ── GET/PATCH /api/v1/agent-templates/default（spec §9.3 默认模板）──


@pytest.mark.asyncio
@pytest.mark.api
class TestDefaultTemplate:
    """默认模板端点契约（设计假设 #13，本契约定稿）。"""

    async def test_get_default_null_when_none(
        self, client, db_session, override_get_db
    ):
        """无默认模板 → 200 + {"template": null}（不 404，#13）。"""
        await _seed_template(db_session, name="普通模板")

        resp = await client.get(f"{ENDPOINT}/default")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"template"}
        assert body["template"] is None

    async def test_set_default_and_get(self, client, db_session, override_get_db):
        """PATCH /default {id} → 200 + is_default=True；GET /default 返回该模板（#13）。"""
        row = await _seed_template(db_session, name="候选默认")

        resp = await client.patch(f"{ENDPOINT}/default", json={"id": str(row.id)})
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_contract(data)
        assert str(data["id"]) == str(row.id)
        assert data["is_default"] is True

        resp2 = await client.get(f"{ENDPOINT}/default")
        assert resp2.status_code == 200
        body = resp2.json()
        assert body["template"] is not None
        assert str(body["template"]["id"]) == str(row.id)
        assert body["template"]["is_default"] is True

    async def test_default_singleton_switch(self, client, db_session, override_get_db):
        """单例语义：设 B 为默认后，A（原默认）is_default 变 False（#13）。"""
        row_a = await _seed_template(db_session, name="模板A")
        row_b = await _seed_template(db_session, name="模板B")

        resp = await client.patch(f"{ENDPOINT}/default", json={"id": str(row_a.id)})
        assert resp.status_code == 200

        resp2 = await client.patch(f"{ENDPOINT}/default", json={"id": str(row_b.id)})
        assert resp2.status_code == 200
        assert resp2.json()["is_default"] is True

        # A 不再是默认
        resp3 = await client.get(f"{ENDPOINT}/{row_a.id}")
        assert resp3.status_code == 200
        assert resp3.json()["is_default"] is False

        # GET /default 指向 B
        resp4 = await client.get(f"{ENDPOINT}/default")
        assert resp4.status_code == 200
        assert str(resp4.json()["template"]["id"]) == str(row_b.id)

    @pytest.mark.parametrize(
        "target_id",
        [uuid.uuid4(), "not-a-uuid"],
        ids=["nonexistent", "invalid_format"],
    )
    async def test_set_default_404(
        self, client, db_session, override_get_db, target_id
    ):
        """PATCH /default：id 不存在/非法格式 → 404（#13/#9）。"""
        resp = await client.patch(f"{ENDPOINT}/default", json={"id": str(target_id)})
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    @pytest.mark.parametrize(
        "body",
        [{}, {"id": ""}, {"id": "   "}],
        ids=["id_missing", "id_empty", "id_blank"],
    )
    async def test_set_default_422(self, client, db_session, override_get_db, body):
        """PATCH /default：body 缺 id / id 空白 → 422（#13/#8）。"""
        resp = await client.patch(f"{ENDPOINT}/default", json=body)
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)


# ── POST /api/v1/agent-templates/{id}/duplicate（spec §9.3 复制）──


@pytest.mark.asyncio
@pytest.mark.api
class TestDuplicateAgentTemplate:
    """复制端点契约（设计假设 #14，本契约定稿）。"""

    async def test_duplicate_201_copies_fields(
        self, client, db_session, override_get_db
    ):
        """复制：201 + 新 id ≠ 旧 id + name 加「副本」后缀 + 字段拷贝（#14）。"""
        row = await _seed_template(
            db_session,
            name="原始模板",
            description="原始说明",
            main_model="deepseek/deepseek-chat",
            default_temperature=0.4,
            roles=ROLES_PAYLOAD,
            default_words=30000,
        )

        resp = await client.post(f"{ENDPOINT}/{row.id}/duplicate")
        assert resp.status_code == 201
        data = resp.json()
        _assert_response_contract(data)
        assert str(data["id"]) != str(row.id), "副本 id 必须不同于原模板"
        assert data["name"] == f"原始模板{DUPLICATE_NAME_SUFFIX}"
        assert data["description"] == "原始说明"
        assert data["main_model"] == "deepseek/deepseek-chat"
        assert data["default_temperature"] == 0.4
        assert data["roles"] == ROLES_PAYLOAD
        assert data["default_words"] == 30000
        assert data["is_default"] is False  # 副本不继承默认位

        # DB 中两行并存
        from inkflow.infrastructure.database.models.agent_template import (
            AgentTemplateORM,
        )

        rows = (await db_session.execute(select(AgentTemplateORM))).scalars().all()
        assert {str(r.id) for r in rows} == {str(row.id), str(data["id"])}

    async def test_duplicate_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id → 404（#14/#9）。"""
        resp = await client.post(f"{ENDPOINT}/{uuid.uuid4()}/duplicate")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND


# ── used_by 引用列表 + 级联清空（spec §9.2.4 风险确认数据）──


@pytest.mark.asyncio
@pytest.mark.api
class TestUsedByReference:
    """used_by 风险确认数据全链路（设计假设 #15）。

    RED 形态：ProjectConfig 尚无 template_id 字段（spec §9.2.2 MODIFY 契约），
    POST /api/v1/projects 时 config 中 template_id 被 Pydantic extra 忽略 →
    config 未落 template_id → 模板详情 used_by 为空 → 断言失败；且
    agent_templates 模块本身不存在 → 收集期 ModuleNotFoundError 先行。
    """

    async def _create_template(self, client, name: str = "被引用模板"):
        """经 API 建模板，返回 str 化 id。"""
        resp = await client.post(ENDPOINT, json={"name": name})
        assert resp.status_code == 201
        return str(resp.json()["id"])

    async def _create_referencing_project(self, client, template_id: str, name: str):
        """经 API 建项目并引用模板（config.template_id，#15 ProjectConfig 扩展）。"""
        resp = await client.post(
            ENDPOINT_PROJECTS,
            json={
                "name": name,
                "genre": "玄幻",
                "language": "zh-CN",
                "target_words": 100000,
                "config": {"template_id": template_id},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        # ProjectConfig 扩展契约：config.template_id 必须落库（RED 阶段缺失）
        assert data["config"]["template_id"] == template_id
        return str(data["id"])

    async def test_detail_used_by_lists_referencing_projects(
        self, client, db_session, override_get_db
    ):
        """模板被项目引用 → 详情 used_by 含 {id, name}；无引用项目不含（#15）。"""
        tid = await self._create_template(client, "被引用模板")
        other = await _seed_template(db_session, name="未被引用模板")

        pid = await self._create_referencing_project(client, tid, "引用项目甲")

        resp = await client.get(f"{ENDPOINT}/{tid}")
        assert resp.status_code == 200
        used_by = resp.json()["used_by"]
        assert len(used_by) == 1
        entry = used_by[0]
        assert str(entry["id"]) == pid
        assert entry["name"] == "引用项目甲"

        # 未被引用的模板 used_by 为空
        resp2 = await client.get(f"{ENDPOINT}/{other.id}")
        assert resp2.status_code == 200
        assert resp2.json()["used_by"] == []

    async def test_delete_referenced_template_cascades_clear(
        self, client, db_session, override_get_db
    ):
        """删除被引用（非默认）模板 → 204；项目 config.template_id 级联清空（#15）。"""
        tid = await self._create_template(client, "级联清空模板")
        pid = await self._create_referencing_project(client, tid, "引用项目乙")

        resp = await client.delete(f"{ENDPOINT}/{tid}")
        assert resp.status_code == 204

        # 项目 config.template_id 回退（None 或键缺失，容忍两种落盘形态）
        resp2 = await client.get(f"{ENDPOINT_PROJECTS}/{pid}")
        assert resp2.status_code == 200
        config = resp2.json()["config"]
        assert config.get("template_id") is None


# ── #177 Coverage-Gap 补测：直接调用 _run_service（不经 TestClient）──


@pytest.mark.asyncio
@pytest.mark.api
class TestCoverageGapRunServiceDirect:
    """#177 覆盖率盲区补测 — 直接调用 router 模块 _run_service，让 except
    分支可被 coverage 记录（coverage.py 对 TestClient portal 线程内异常
    传播路径存在统计盲区；直接调用不经 TestClient，pytest 下可正常记录）。

    补测非 TDD：被测源码已存在（agent_templates.py L105-110），
    本类用例直接通过，不改动任何 src/ 文件。
    """

    async def test_run_service_not_found_maps_404(self):
        """AgentTemplateNotFoundError → HTTPException 404（detail 含异常
        消息，agent_templates.py L105-106）。"""
        from fastapi import HTTPException

        from inkflow.api.routers.agent_templates import _run_service
        from inkflow.domain.ports.agent_template_errors import (
            AgentTemplateNotFoundError,
        )

        async def _raise(exc):
            raise exc

        with pytest.raises(HTTPException) as ei:
            await _run_service(_raise(AgentTemplateNotFoundError("x")))
        assert ei.value.status_code == 404
        assert "x" in ei.value.detail

    async def test_run_service_builtin_maps_409(self):
        """AgentTemplateBuiltinError → HTTPException 409（detail 精确等于
        DEFAULT_DELETE_DETAIL，agent_templates.py L107-108）。"""
        from fastapi import HTTPException

        from inkflow.api.routers.agent_templates import (
            DEFAULT_DELETE_DETAIL,
            _run_service,
        )
        from inkflow.domain.ports.agent_template_errors import (
            AgentTemplateBuiltinError,
        )

        async def _raise(exc):
            raise exc

        with pytest.raises(HTTPException) as ei:
            await _run_service(_raise(AgentTemplateBuiltinError("x")))
        assert ei.value.status_code == 409
        assert ei.value.detail == DEFAULT_DELETE_DETAIL

    async def test_run_service_service_error_maps_422(self):
        """AgentTemplateServiceError → HTTPException 422（detail 含异常
        消息，agent_templates.py L109-110）。"""
        from fastapi import HTTPException

        from inkflow.api.routers.agent_templates import _run_service
        from inkflow.domain.ports.agent_template_errors import (
            AgentTemplateServiceError,
        )

        async def _raise(exc):
            raise exc

        with pytest.raises(HTTPException) as ei:
            await _run_service(_raise(AgentTemplateServiceError("x")))
        assert ei.value.status_code == 422
        assert "x" in ei.value.detail
