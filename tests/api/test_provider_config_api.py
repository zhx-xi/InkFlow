"""#106 F19-GUI 子任务 F — ProviderConfig 注册表 API 测试契约（TDD RED 阶段）。

本文件为 `api/routers/provider_configs.py`（NEW，spec §8.3 端点表 + §8.2 注册表
实体方案，用户拍板 Q1=B/Q2=B/Q3=A）定义 API 测试契约，覆盖 5 个端点：

- `GET    /api/v1/provider-configs`       — 注册表列表（含 key_saved + models）
- `POST   /api/v1/provider-configs`       — 新建（201）
- `GET    /api/v1/provider-configs/{id}`  — 详情（含 models）/ 404
- `PATCH  /api/v1/provider-configs/{id}`  — 更新 / 404
- `DELETE /api/v1/provider-configs/{id}`  — 删除（204）/ 404 / 内置 seed 409 保护

权威来源：specs/f19-gui/spec.md §8.2（ProviderConfig 实体 + 内置 seed 4 条，
2026-08-06 源码核实 openai/deepseek/zhipu/ollama）、§8.3（端点表）、§8.4
（NEW ×7 文件结构）、§8.5/§8.6（测试策略与验收 M1）。spec §8.3 既有端点
`/settings/llm-keys`、`/settings/llm/test`（#79）本文件不覆盖（test_settings_api.py
已契约）。测试方式镜像 tests/api/test_settings_api.py（契约 docstring 风格 +
无 token 模式）与 tests/api/test_chapter_api.py（ASGITransport + override_get_db
真实 DB 模式）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【测试方式】ASGITransport + AsyncClient 直连真实 app 对象（import
   inkflow.api.app），`override_get_db` fixture（tests/api/conftest.py）将
   get_db 替换为测试 db_session（tests/conftest.py 内存 SQLite），app 与测试
   共享同一数据库。本文件模块级 `import inkflow.api.routers.provider_configs`
   为 RED 收集断言（模块不存在 → 全文件收集期 ModuleNotFoundError，
   即预期失败形态）。所有用例显式
   `@pytest.mark.asyncio`（免疫 pytest-asyncio strict/auto 模式差异）。

2. 【无 token 模式——硬性契约】本文件所有用例依赖 env
   `INKFLOW_SERVER_TOKEN` 未设置时中间件直通（test_settings_api.py 设计
   假设 #2 同款）：client fixture 内显式 monkeypatch.delenv，免疫开发者
   本机 shell 的 env 残留导致假失败。

3. 【模块契约】`inkflow.api.routers.provider_configs` 必须暴露（本文件 patch
   目标 = 最终契约，GREEN 必须匹配）：
   - `router = APIRouter(prefix="/api/v1/provider-configs", tags=["ProviderConfigs"])`
     （app.py 需 `app.include_router(provider_configs.router)`，与既有
     router 模块级模式一致）
   - `_get_key_manager() -> APIKeyManager`：零参模块级工厂（镜像
     api/routers/settings.py 同款工厂）——key_saved 计算【唯一】入口

4. 【响应结构——全部端点统一（spec §8.3「含 key_saved + models」）】
   `{id, name, base_url, default_model, models, key_saved, created_at, updated_at}`：
   - id：str 或 int 均可（ORM 主键自增整数或 UUID 皆可），测试一律以
     `str(row.id)` 驱动 URL、`str(data["id"])` 比对，不契约 id 类型
   - models：list[dict]，每项 `{id: str, type: "chat"|"embedding",
     roles: list[str]}`（spec §8.2 实体 models 契约；roles 默认 []）
   - key_saved：bool —— 该 provider 是否已在 APIKeyManager 存 key
   - created_at/updated_at：ISO 8601 字符串（datetime.fromisoformat 可解析）
   - 实体另有 max_retries/timeout 字段（spec §8.2），响应可含可省——本文件
     只断言契约 8 键存在 + 值语义，【不做整 dict 全等】（容忍 GREEN 输出
     实体额外字段）

5. 【key_saved 计算契约】路由经 `_get_key_manager()`（零参）→
   `.list_providers()`（APIKeyManager 既有方法，返回已存 key 的 provider
   名列表）→ `key_saved = name in list_providers()`。测试 patch
   `inkflow.api.routers.provider_configs._get_key_manager` 注入
   FakeKeyManager 驱动（禁直接读 key 文件）。全部成功路径用例均 patch
   （免疫本机 data_dir 残留 key 文件导致的假阳性）。

6. 【列表端点】GET /api/v1/provider-configs → 200 + `{items: [...], total: N}`
   （repo 列表端点惯例：foreshadowings/volumes 同款 envelope）。本契约只
   约束 items/total 两键（GREEN 可额外输出 offset/limit 等分页字段）；无
   seed 时 total=0、items=[]。

7. 【内置 seed（spec §8.2，2026-08-06 源码核实）】openai/deepseek/zhipu/
   ollama 共 4 条。【#106 F1 评审拍板（2026-08-06）】seed 由 app
   lifespan 显式调用 `ProviderConfigService.seed_builtin_providers()`
   （幂等）——`create_tables()` 本身【不】seed；修复前 lifespan 仅
   create_tables() → 全新安装注册表为空（TestSeedBuiltinProviders
   RED 契约）。本文件其余用例仍自行经 ORM 注入 seed 行（lifespan
   seed 写入真实 DB 文件，与 override 的测试内存库无关——
   test_settings_api.py 设计假设 #13 同款）。ORM 契约：
   `inkflow.infrastructure.database.models.provider_config.ProviderConfigORM`，
   构造 kwargs `name/base_url/default_model/models`（models 为 JSON 列
   list[dict]，仿 ProjectORM.config），表名 `provider_configs`，id 由 DB
   默认生成；需在 `infrastructure/database/models/__init__.py` 导出（注册
   进 Base.metadata，测试 test_engine fixture 的 create_all 才会建表）。

8. 【422 校验】POST：name 必填（缺失 / 空白 "   " → 422）；models[].type
   仅 "chat"|"embedding"（非法 → 422）；models[].id 空白 → 422；多余字段
   忽略（Pydantic v2 默认行为，不 422）。PATCH：全可选（`{}` 合法 → 200
   不变），提供即校验（name 空白 / type 非法 → 422）。422 响应 detail 为
   Pydantic 校验错误列表。

9. 【404 语义】id 不存在或非法格式（非 UUID / 非整数）→ 404 +
   `{"detail": "Provider 不存在"}`（镜像 foreshadowings `_parse_id` 404
   语义，非法格式不 422）。

10. 【创建契约】POST → 201 + 完整响应结构；name/base_url/default_model/
    models 原样回显（models 逐项 roundtrip 相等）；key_saved=False（无已存
    key）；DB 按 name 回查落库且 id 与响应一致（集成断言）。

11. 【PATCH 语义】exclude_unset 浅合并（spec §8.1 既有 PATCH 语义，同
    api/routers/project.py L94）：仅更新提供字段，未提供字段原样保留；
    models 提供则【整体替换】（不深合并）。

12. 【删除契约】DELETE → 204 空响应体（镜像 foreshadowings delete）；
    不存在 → 404；【内置 seed 保护】name ∈ {openai, deepseek, zhipu,
    ollama} → 409 + `{"detail": "内置 Provider 不可删除"}`（GREEN 可用
    is_builtin 列等价实现，但 4 内置名必须受保护；409 后记录仍存在）；
    PATCH 内置【允许】（spec §8.3 仅 DELETE 受保护）。

13. 【used_by 删除提示（spec §8.3「被模型绑定引用时返回 used_by 提示」）】
    依赖 #107 AgentTemplate 绑定表——不在本文件契约内；GREEN 若实现须
    409 + used_by 字段，本文件不覆盖、不约束。

14. 【名称唯一性不契约】POST/PATCH 重名（含与内置重名）行为由 GREEN
    决定（本文件不覆盖），但 4 内置名 seed 行的删除保护必须成立（#12）。

15. 【lifespan/建表】ASGITransport 不触发 lifespan（test_chapter_api.py
    同款），建表由 test_engine fixture（tests/conftest.py）完成；常规
    用例无 ./inkflow.db 副作用。【例外——#106 F1 lifespan 契约】
    TestSeedBuiltinProviders.test_lifespan_startup_seeds_builtin_providers
    使用 TestClient(app)（触发真实 lifespan）+ monkeypatch.chdir(tmp_path)
    把真实 DB 文件（./inkflow.db）隔离到 tmp 目录（规避仓库根残留/
    污染，测试结束自动清理），GET 与 lifespan 共享同一真实 DB。

16. 【#106 F1 seed 接线契约（2026-08-06 评审修复）】lifespan 启动后
    注册表必须含内置 4 provider（openai/deepseek/zhipu/ollama），且
    seed 幂等：重复调用不报错、不重复插入（repo get_by_name 判重，
    第二次返回插入数 0）。测试覆盖两路径：① 真实 lifespan 执行
    （TestClient）+ GET 列表断言各内置名恰好 1 条（RED 形态：lifespan
    未接线 → 列表空）；② 直接调 service seed 两次 + GET 列表断言
    total=4（回归护栏，当前实现已满足）。

════════════════════════════════════════════════════════════════════
RED 阶段预期：`inkflow.api.routers.provider_configs` 模块不存在 →
本文件【收集期 ModuleNotFoundError】collected 0 items（router 未注册，
请求亦 404）。GREEN 阶段：按上述契约实现 §8.4 NEW ×7
（domain/models/provider_config.py、domain/ports/provider_config_repository.py
+ _errors.py、domain/services/provider_config_service.py、
infrastructure/database/models/provider_config.py、
infrastructure/database/repositories/provider_config_repo.py、
api/routers/provider_configs.py）+ MODIFY app.py include_router 后全绿。

#106 F1 补充契约（2026-08-06 评审修复批）：lifespan seed 接线契约见
TestSeedBuiltinProviders —— 修复前 lifespan 未调 seed_builtin_providers
→ test_lifespan_startup_seeds_builtin_providers RED（列表空）。

══════════════ #126 A1 builtin_key 契约（2026-08-06，方案已拍板）══════════════

17. 【builtin_key 响应字段】响应结构契约升级：全部端点响应新增
    ``builtin_key: str | None`` 键 —— 内置行稳定标识（seed 行 = openai/
    deepseek/zhipu/ollama 之一），用户行 = null。``_assert_response_contract``
    键列表加 ``builtin_key``（GREEN 后全绿；RED 阶段既有 5 个调用点
    因「响应缺少契约字段 builtin_key」失败，属预期契约升级）。

18. 【PATCH 改名保持 builtin_key】内置行改名（openai→myai）→ 响应
    builtin_key 保持 'openai'（exclude_unset 浅合并不触碰 DTO 外字段）。

19. 【验收场景——改名后重启不复活】seed（service 直调，真实 repo）→
    PATCH 改名 openai→myai → 再次 seed → 返回 0（按 builtin_key 判重，
    不再按名判重）；GET 列表仅 4 行 {myai, deepseek, zhipu, ollama}、
    无重复 openai 行、myai 行 builtin_key='openai'。RED 阶段 seed 仍按
    名判重 → 改名后再次 seed 返回 1（复活 openai）→ 断言失败 + 列表 5 行。

20. 【RED 预期失败形态】① 响应缺 builtin_key 键 → 5 个既有用例断言失败
    （_assert_response_contract）+ 新用例 KeyError；② 验收场景 seed 返回
    1 ≠ 0 断言失败（openai 复活）。

════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import inkflow.api.routers.provider_configs  # noqa: F401  # RED 收集断言：模块存在性契约（GREEN 实现后即被使用）
from inkflow.api.app import app

# ── 契约常量 ──

ENDPOINT = "/api/v1/provider-configs"
"""ProviderConfig 注册表端点前缀（spec §8.3）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（spec §2.3.1）：本文件全部用例依赖未设置 → 直通。"""

BUILTIN_NAMES = ["openai", "deepseek", "zhipu", "ollama"]
"""内置 seed 4 provider 名（spec §8.2，2026-08-06 源码核实 _BUILTIN_PROVIDERS）。"""

DETAIL_NOT_FOUND = "Provider 不存在"
"""id 不存在/非法格式的 404 detail（设计假设 #9）。"""

DETAIL_BUILTIN_DELETE = "内置 Provider 不可删除"
"""删除内置 seed 的 409 detail（设计假设 #12）。"""

BUILTIN_SEED = [
    {
        "name": "openai",
        "base_url": "https://api.openai.com/v1",
        "default_model": "openai/gpt-4o-mini",
        "models": [
            {"id": "gpt-4o-mini", "type": "chat", "roles": ["writing"]},
            {"id": "text-embedding-3-small", "type": "embedding", "roles": ["rag"]},
        ],
    },
    {
        "name": "deepseek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek/deepseek-chat",
        "models": [
            {"id": "deepseek-chat", "type": "chat", "roles": ["writing"]},
        ],
    },
    {
        "name": "zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "zhipu/glm-4-flash",
        "models": [
            {"id": "glm-4-flash", "type": "chat", "roles": []},
        ],
    },
    {
        "name": "ollama",
        "base_url": "http://localhost:11434",
        "default_model": "ollama/llama3.1",
        "models": [
            {"id": "llama3.1", "type": "chat", "roles": []},
            {"id": "bge-m3", "type": "embedding", "roles": ["rag"]},
        ],
    },
]
"""内置 seed 4 条（openai/deepseek/zhipu/ollama）——测试经 ORM 注入用（设计假设 #7）。"""


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


class FakeKeyManager:
    """key_saved 计算的 fake（设计假设 #5）：记录 list_providers 调用次数。"""

    def __init__(self, providers: list[str] | None = None) -> None:
        self._providers = list(providers or [])
        self.list_calls = 0

    def list_providers(self) -> list[str]:
        self.list_calls += 1
        return list(self._providers)


@pytest.fixture
def patch_key_manager():
    """返回工厂：patch provider_configs._get_key_manager 为 FakeKeyManager。

    用法：`fake = patch_key_manager(["deepseek"])` 后发起请求；fixture 结束
    自动 stop 全部 patcher（测试间互不污染）。
    """

    patchers: list = []

    def _patch(providers: list[str] | None = None) -> FakeKeyManager:
        fake = FakeKeyManager(providers)
        patcher = patch(
            "inkflow.api.routers.provider_configs._get_key_manager",
            return_value=fake,
        )
        patcher.start()
        patchers.append(patcher)
        return fake

    yield _patch
    for patcher in patchers:
        patcher.stop()


# ── Seed / 断言辅助 ──


async def _seed_provider(
    db_session,
    *,
    name: str,
    base_url: str = "",
    default_model: str = "",
    models: list[dict] | None = None,
):
    """经 ORM 注入一条 ProviderConfig 记录（设计假设 #7）。

    ORM 契约：inkflow.infrastructure.database.models.provider_config.
    ProviderConfigORM，构造 kwargs name/base_url/default_model/models
    （models 为 JSON 列 list[dict]）；id 由 DB 默认生成。
    """
    from inkflow.infrastructure.database.models.provider_config import (
        ProviderConfigORM,
    )

    row = ProviderConfigORM(
        name=name,
        base_url=base_url,
        default_model=default_model,
        models=models or [],
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _seed_builtin_providers(db_session):
    """注入内置 seed 4 条（openai/deepseek/zhipu/ollama），返回 ORM 行列表。"""
    rows = []
    for spec in BUILTIN_SEED:
        rows.append(await _seed_provider(db_session, **spec))
    return rows


def _assert_models_contract(models) -> None:
    """models 数组契约：每项 {id 非空, type ∈ chat|embedding, roles list}（#4）。"""
    assert isinstance(models, list)
    for m in models:
        assert isinstance(m, dict)
        assert "id" in m and str(m["id"]).strip(), "model id 缺失或空白"
        assert m["type"] in ("chat", "embedding"), f"非法 model type: {m['type']}"
        assert isinstance(m.get("roles", []), list)


def _assert_response_contract(data: dict) -> None:
    """响应结构契约（设计假设 #4 + #126 A1 #17）：9 键存在 + 值语义，不做整 dict 全等。"""
    for key in (
        "id",
        "name",
        "base_url",
        "default_model",
        "models",
        "key_saved",
        "builtin_key",  # #126 A1：内置行稳定标识（seed 行=内置 key，用户行=null）
        "created_at",
        "updated_at",
    ):
        assert key in data, f"响应缺少契约字段 {key}"
    datetime.fromisoformat(data["created_at"])
    datetime.fromisoformat(data["updated_at"])
    assert isinstance(data["key_saved"], bool)
    _assert_models_contract(data["models"])


# ── GET /api/v1/provider-configs（spec §8.3 列表）──


@pytest.mark.asyncio
@pytest.mark.api
class TestListProviderConfigs:
    """注册表列表端点契约（设计假设 #5/#6/#7）。"""

    async def test_list_returns_seeded_builtin_providers(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """内置 seed 4 条 → 200 + {items, total}；每项满足响应结构契约。

        设计假设 #6/#7：列表含内置 4 provider（openai/deepseek/zhipu/
        ollama），items 与 seed 行 id 一一对应（str 化比较，容忍 int/UUID
        两种主键）；无已存 key → 全部 key_saved=False。
        """
        rows = await _seed_builtin_providers(db_session)
        fake = patch_key_manager([])

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 4
        items = body["items"]
        assert len(items) == 4
        assert {it["name"] for it in items} == set(BUILTIN_NAMES)
        for it in items:
            _assert_response_contract(it)
            assert it["key_saved"] is False
        # 与 seed 行 id 一一对应
        seeded_ids = {str(r.id) for r in rows}
        assert {str(it["id"]) for it in items} == seeded_ids
        assert fake.list_calls >= 1

    async def test_list_key_saved_flag(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """key_saved 标记：已存 key 的 provider → True，其余 False（#5）。

        FakeKeyManager.list_providers() 返回 ["deepseek"] → 仅 deepseek 项
        key_saved=True；key 判定必须经 _get_key_manager() 工厂（patch 目标）。
        """
        await _seed_builtin_providers(db_session)
        fake = patch_key_manager(["deepseek"])

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        key_by_name = {it["name"]: it["key_saved"] for it in resp.json()["items"]}
        assert key_by_name["deepseek"] is True
        assert key_by_name["openai"] is False
        assert key_by_name["zhipu"] is False
        assert key_by_name["ollama"] is False
        assert fake.list_calls >= 1

    async def test_list_empty_when_no_seed(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """无 seed → 200 + {items: [], total: 0}（不隐式造数，#6）。"""
        patch_key_manager([])
        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0


# ── #106 F1：lifespan 内置 seed 接线契约（2026-08-06 评审修复）──


class TestSeedBuiltinProviders:
    """#106 F1 契约：lifespan 启动即 seed 内置 4 provider + seed 幂等。

    设计假设 #7/#16：seed 由 app lifespan 显式调用
    ProviderConfigService.seed_builtin_providers()（幂等）。修复前
    lifespan 仅 create_tables() 不 seed → 全新安装注册表为空 ——
    test_lifespan_startup_seeds_builtin_providers 即 RED 形态（列表空）。
    """

    def test_lifespan_startup_seeds_builtin_providers(self, monkeypatch, tmp_path):
        """真实 lifespan 执行后 GET 列表含内置 4 provider（各恰好 1 条）。

        触发路径 = TestClient(app) 上下文（__enter__ 运行真实 lifespan：
        create_tables +【GREEN】seed 真实 DB 文件）；monkeypatch.chdir
        (tmp_path) 把 ./inkflow.db 隔离到 tmp 目录（设计假设 #15 例外，
        规避仓库根 DB 残留/污染），GET 与 lifespan 共享同一真实 DB。
        断言内置名各恰好 1 条（seed 幂等 → 不重复插入）；不做 total
        全等（容忍真实 DB 残留自定义 provider 行）。
        """
        monkeypatch.delenv(ENV_TOKEN, raising=False)
        monkeypatch.chdir(tmp_path)
        with patch(
            "inkflow.api.routers.provider_configs._get_key_manager",
            return_value=FakeKeyManager(),
        ), TestClient(app) as tc:
            resp = tc.get(ENDPOINT)
        assert resp.status_code == 200
        names = [it["name"] for it in resp.json()["items"]]
        for name in BUILTIN_NAMES:
            assert names.count(name) == 1, (
                f"lifespan 后内置 {name} 应恰好 1 条（seed 未接线 → 0 条，"
                f"或重复插入 → >1 条），实际 {names.count(name)} 条"
            )

    @pytest.mark.asyncio
    async def test_seed_builtin_providers_idempotent(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """seed 幂等：重复调用不报错、不重复插入；GET 列表可见 4 条（#16）。

        直接调 ProviderConfigService.seed_builtin_providers()（lifespan
        的等价调用路径，注入测试 db_session）：第一次返回 4（实际插入
        4 条），第二次返回 0（repo get_by_name 判重，不重复插入）；
        随后 GET 列表 total=4 且内置名集合一致。
        """
        from inkflow.domain.services.provider_config_service import (
            ProviderConfigService,
        )
        from inkflow.infrastructure.database.repositories.provider_config_repo import (
            SQLiteProviderConfigRepository,
        )

        svc = ProviderConfigService(
            repository=SQLiteProviderConfigRepository(db_session)
        )
        assert await svc.seed_builtin_providers() == 4
        assert await svc.seed_builtin_providers() == 0  # 幂等：不重复插入

        patch_key_manager([])
        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 4
        assert {it["name"] for it in body["items"]} == set(BUILTIN_NAMES)


# ── POST /api/v1/provider-configs（spec §8.3 新建）──


@pytest.mark.asyncio
@pytest.mark.api
class TestCreateProviderConfig:
    """新建端点契约（设计假设 #8/#10）。"""

    async def test_create_201_contract(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """成功：201 + 完整响应；字段原样回显；DB 落库且 id 一致（#10）。"""
        fake = patch_key_manager([])
        payload = {
            "name": "my-provider",
            "base_url": "https://example.com/v1",
            "default_model": "my-provider/my-model",
            "models": [
                {"id": "my-model", "type": "chat", "roles": ["writing"]},
                {"id": "my-embed", "type": "embedding", "roles": ["rag"]},
            ],
        }

        resp = await client.post(ENDPOINT, json=payload)
        assert resp.status_code == 201
        data = resp.json()
        _assert_response_contract(data)
        assert data["name"] == "my-provider"
        assert data["base_url"] == "https://example.com/v1"
        assert data["default_model"] == "my-provider/my-model"
        assert data["models"] == payload["models"]
        assert data["key_saved"] is False
        assert fake.list_calls >= 1

        # 集成断言：按 name 回查落库，id 与响应一致
        from inkflow.infrastructure.database.models.provider_config import (
            ProviderConfigORM,
        )

        row = (
            await db_session.execute(
                select(ProviderConfigORM).where(ProviderConfigORM.name == "my-provider")
            )
        ).scalar_one()
        assert str(row.id) == str(data["id"])
        assert row.models == payload["models"]

    @pytest.mark.parametrize(
        "body",
        [
            {},  # name 缺失
            {"name": "   "},  # name 空白
            {
                "name": "my-provider",
                "models": [{"id": "m1", "type": "vision"}],
            },  # type 非法
            {
                "name": "my-provider",
                "models": [{"id": "   ", "type": "chat"}],
            },  # model id 空白
        ],
        ids=["name_missing", "name_blank", "model_type_invalid", "model_id_blank"],
    )
    async def test_create_validation_422(
        self, client, db_session, override_get_db, body
    ):
        """name 缺失/空白、models[].type 非法、models[].id 空白 → 422（#8）。"""
        resp = await client.post(ENDPOINT, json=body)
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    async def test_create_extra_fields_ignored(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """多余字段忽略（不 422）→ 201（#8：Pydantic v2 默认行为）。"""
        patch_key_manager([])
        resp = await client.post(
            ENDPOINT,
            json={
                "name": "my-provider",
                "base_url": "https://example.com/v1",
                "foo": "bar",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "my-provider"


# ── GET /api/v1/provider-configs/{id}（spec §8.3 详情）──


@pytest.mark.asyncio
@pytest.mark.api
class TestGetProviderConfig:
    """详情端点契约（设计假设 #9）。"""

    async def test_get_detail_200(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """详情：200 + 完整响应结构（含 models 原样、key_saved）。"""
        row = await _seed_provider(
            db_session,
            name="openai",
            base_url="https://api.openai.com/v1",
            default_model="openai/gpt-4o-mini",
            models=[
                {"id": "gpt-4o-mini", "type": "chat", "roles": ["writing"]},
            ],
        )
        patch_key_manager([])

        resp = await client.get(f"{ENDPOINT}/{row.id}")
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_contract(data)
        assert str(data["id"]) == str(row.id)
        assert data["name"] == "openai"
        assert data["base_url"] == "https://api.openai.com/v1"
        assert data["models"] == [
            {"id": "gpt-4o-mini", "type": "chat", "roles": ["writing"]},
        ]
        assert data["key_saved"] is False

    async def test_get_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id → 404 + detail "Provider 不存在"（#9）。"""
        resp = await client.get(f"{ENDPOINT}/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    async def test_get_invalid_id_404(self, client, db_session, override_get_db):
        """非法 id 格式（非 UUID/非整数）→ 404（非 422，镜像 _parse_id，#9）。"""
        resp = await client.get(f"{ENDPOINT}/not-a-uuid")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND


# ── PATCH /api/v1/provider-configs/{id}（spec §8.3 更新）──


@pytest.mark.asyncio
@pytest.mark.api
class TestUpdateProviderConfig:
    """更新端点契约（设计假设 #9/#11/#12）。"""

    async def test_patch_partial_200(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """部分更新：200 + 仅提供字段变更，未提供字段原样保留（#11）。"""
        row = await _seed_provider(
            db_session,
            name="my-provider",
            base_url="https://example.com/v1",
            default_model="my-provider/my-model",
            models=[{"id": "m1", "type": "chat", "roles": []}],
        )
        patch_key_manager([])

        resp = await client.patch(
            f"{ENDPOINT}/{row.id}",
            json={"name": "renamed", "default_model": "my-provider/new-model"},
        )
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_contract(data)
        assert data["name"] == "renamed"
        assert data["default_model"] == "my-provider/new-model"
        # exclude_unset 浅合并：未提供字段原样保留
        assert data["base_url"] == "https://example.com/v1"
        assert data["models"] == [{"id": "m1", "type": "chat", "roles": []}]
        assert data["key_saved"] is False

    async def test_patch_empty_body_ok(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """空 body {} → 200 不变（全可选，#8/#11）。"""
        row = await _seed_provider(
            db_session, name="my-provider", default_model="my-provider/my-model"
        )
        patch_key_manager([])

        resp = await client.patch(f"{ENDPOINT}/{row.id}", json={})
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_contract(data)
        assert data["name"] == "my-provider"
        assert data["default_model"] == "my-provider/my-model"

    async def test_patch_models_replaced_whole(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """models 提供则整体替换（不深合并，#11）。"""
        row = await _seed_provider(
            db_session,
            name="my-provider",
            models=[{"id": "old-model", "type": "chat", "roles": []}],
        )
        patch_key_manager([])

        resp = await client.patch(
            f"{ENDPOINT}/{row.id}",
            json={
                "models": [
                    {"id": "new-model", "type": "embedding", "roles": ["rag"]},
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["models"] == [
            {"id": "new-model", "type": "embedding", "roles": ["rag"]},
        ]

    async def test_patch_not_found_404(self, client, db_session, override_get_db):
        """不存在的 id → 404（#9）。"""
        resp = await client.patch(f"{ENDPOINT}/{uuid.uuid4()}", json={"name": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND

    @pytest.mark.parametrize(
        "body",
        [
            {"name": "   "},  # name 空白
            {"models": [{"id": "m1", "type": "nope"}]},  # type 非法
        ],
        ids=["name_blank", "model_type_invalid"],
    )
    async def test_patch_validation_422(
        self, client, db_session, override_get_db, body
    ):
        """PATCH 提供即校验：name 空白 / type 非法 → 422（#8）。"""
        row = await _seed_provider(db_session, name="my-provider")
        resp = await client.patch(f"{ENDPOINT}/{row.id}", json=body)
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    async def test_patch_builtin_allowed_200(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """PATCH 内置 seed 允许（仅 DELETE 受保护，#12）。"""
        row = await _seed_provider(
            db_session,
            name="deepseek",
            base_url="https://api.deepseek.com",
            default_model="deepseek/deepseek-chat",
        )
        patch_key_manager([])

        resp = await client.patch(
            f"{ENDPOINT}/{row.id}",
            json={"base_url": "https://custom.example.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["base_url"] == "https://custom.example.com"
        assert resp.json()["name"] == "deepseek"


# ── DELETE /api/v1/provider-configs/{id}（spec §8.3 删除）──


@pytest.mark.asyncio
@pytest.mark.api
class TestDeleteProviderConfig:
    """删除端点契约（设计假设 #9/#12/#13）。"""

    async def test_delete_204_and_gone(self, client, db_session, override_get_db):
        """成功：204 空响应体；删除后 GET → 404（#12）。"""
        row = await _seed_provider(
            db_session, name="my-provider", default_model="my-provider/my-model"
        )

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

    async def test_delete_builtin_seed_409(self, client, db_session, override_get_db):
        """删除内置 seed（name=deepseek）→ 409 + 保护 detail；记录仍存在（#12）。"""
        row = await _seed_provider(
            db_session,
            name="deepseek",
            base_url="https://api.deepseek.com",
            default_model="deepseek/deepseek-chat",
            models=[{"id": "deepseek-chat", "type": "chat", "roles": []}],
        )

        resp = await client.delete(f"{ENDPOINT}/{row.id}")
        assert resp.status_code == 409
        assert resp.json()["detail"] == DETAIL_BUILTIN_DELETE

        # 409 后记录未被删除
        resp2 = await client.get(f"{ENDPOINT}/{row.id}")
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "deepseek"

    async def test_delete_invalid_id_404(self, client, db_session, override_get_db):
        """非法 id 格式 → 404（非 422，镜像 _parse_id，#9）。"""
        resp = await client.delete(f"{ENDPOINT}/not-a-uuid")
        assert resp.status_code == 404
        assert resp.json()["detail"] == DETAIL_NOT_FOUND


# ── #126 A1：builtin_key 契约（2026-08-06，方案已拍板）──


@pytest.mark.asyncio
@pytest.mark.api
class TestBuiltinKeyContract:
    """#126 A1 builtin_key — PATCH 改名保持 + seed 按 key 判重（改名重启不复活）。

    RED 预期（实现未写，详见文件头部 docstring #17-#20）:
    - 响应缺 builtin_key 键 → KeyError / _assert_response_contract 断言失败
    - seed 仍按名判重 → 验收场景 seed 返回 1（复活 openai）→ 断言失败
    """

    @staticmethod
    async def _seed_via_service(db_session):
        """经真实 repo + service 触发 seed（与 lifespan 等价调用路径）。"""
        from inkflow.domain.services.provider_config_service import (
            ProviderConfigService,
        )
        from inkflow.infrastructure.database.repositories.provider_config_repo import (
            SQLiteProviderConfigRepository,
        )

        return ProviderConfigService(
            repository=SQLiteProviderConfigRepository(db_session)
        )

    @staticmethod
    async def _get_orm_row(db_session, name: str):
        """按 name 查 ORM 行（PATCH 目标 id 来源）。"""
        from inkflow.infrastructure.database.models.provider_config import (
            ProviderConfigORM,
        )

        return (
            await db_session.execute(
                select(ProviderConfigORM).where(ProviderConfigORM.name == name)
            )
        ).scalar_one()

    async def test_patch_rename_preserves_builtin_key(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """内置行改名（openai→myai）→ 响应 builtin_key 保持 'openai'（#18）。"""
        svc = await self._seed_via_service(db_session)
        assert await svc.seed_builtin_providers() == 4
        row = await self._get_orm_row(db_session, "openai")
        patch_key_manager([])

        resp = await client.patch(f"{ENDPOINT}/{row.id}", json={"name": "myai"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "myai"
        assert data["builtin_key"] == "openai"  # RED: KeyError（响应缺 builtin_key 键）

    async def test_seed_after_rename_does_not_resurrect(
        self, client, db_session, override_get_db, patch_key_manager
    ):
        """验收场景（#19）：seed → PATCH 改名 openai→myai → 再 seed 返回 0
        （不复活）；GET 列表仅 4 行、无重复 openai、myai 行 builtin_key='openai'。"""
        svc = await self._seed_via_service(db_session)
        assert await svc.seed_builtin_providers() == 4
        row = await self._get_orm_row(db_session, "openai")

        resp = await client.patch(f"{ENDPOINT}/{row.id}", json={"name": "myai"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "myai"

        assert (
            await svc.seed_builtin_providers() == 0
        )  # RED: 按名判重 → 实际 1（openai 复活）

        patch_key_manager([])
        resp2 = await client.get(ENDPOINT)
        assert resp2.status_code == 200
        body = resp2.json()
        assert body["total"] == 4  # RED: 实际 5 行
        names = [it["name"] for it in body["items"]]
        assert names.count("openai") == 0
        assert set(names) == {"myai", "deepseek", "zhipu", "ollama"}
        myai = next(it for it in body["items"] if it["name"] == "myai")
        assert myai["builtin_key"] == "openai"
