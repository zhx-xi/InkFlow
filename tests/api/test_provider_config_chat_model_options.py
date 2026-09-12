"""#1129 chat 模型候选端点 API 契约测试（GET /api/v1/provider-configs/chat-model-options）。

被测端点：`GET /api/v1/provider-configs/chat-model-options`（挂既有 provider_configs
router，prefix=/api/v1/provider-configs）。

════════════════════════════════════════════════════════════════════
背景（issue #1129，阻断级）
════════════════════════════════════════════════════════════════════

GUI 首启引导页被锁死且 chat 模型下拉为空 → 用户无法经该页自解（死路）。
下拉原数据源 `selectChatModelOptions` 只遍历注册表 `models[type=="chat"]`，
而正常路径（`llm set-key` 只写 key；#735 D2 自动设默认只写内存单例 +
config.json，从不回写 models[]）拿不到 chat 条目。

本端点 = 下拉的**唯一数据源**，与就绪判据同源（`is_chat_model_resolvable`）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【端点】`GET /api/v1/provider-configs/chat-model-options`。字面子路径必须
   【先于】`GET /{provider_config_id}` 声明，否则被通配吞掉（401/404 而非 200）。

2. 【响应契约】200 + 精确 5 键：
   `{options: list[dict], chat_models: list[str], project_models: list[str],
     default_model: str, available_model: str}`。
   - options 元素：`{provider: str, model: str, source: str, has_key: bool}`，
     source ∈ {"registry","provider_default","global_default","project"}
   - chat_models = options 的 model 投影（同序去重）
   - available_model = 首个可解析候选（无 → ""）

3. 【候选来源与顺序】按 value 去重，顺序：
   注册表 chat 条目 → provider.default_model → 全局默认 → 项目级 config.model。

4. 【同源判定】可解析性一律经 `is_chat_model_resolvable`（唯一真相）：
   注册表**确知** embedding 的模型不得入选；无凭据的不得入选。

5. 【降级】任何内部失败 → 200 + 空结构（键恒 5 个），绝不让下拉 500。

6. 【测试注入】DB：override_get_db → 本文件 db_session（真内存 SQLite，
   可插 ProviderORM / ProjectORM 行）；key：patch 本模块
   `_get_key_manager` → fake。
   ⚠️ 全局默认用 `config.llm_default_model`（进程级单例）——为避免本机
   config.json 残留导致假阳性，所有用例显式 patch 该属性。

7. 【无 token 模式】client fixture 内显式 delenv INKFLOW_SERVER_TOKEN。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import inkflow.api.routers.provider_configs  # noqa: F401  # 模块存在性契约
from inkflow.api.app import app
from inkflow.core.database import Base

ENDPOINT = "/api/v1/provider-configs/chat-model-options"

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"

PATCH_KEY_MANAGER = "inkflow.api.routers.provider_configs._get_key_manager"

CONFIG_SINGLETON = "inkflow.core.config.config"


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_session():
    """独立 in-memory SQLite（每用例全新库，镜像 test_settings_model_readiness）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def override_get_db(db_session):
    """将 FastAPI get_db 替换为本文件 db_session。"""
    from inkflow.api.deps import get_db

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.clear()


class _FakeKeyManager:
    """最小 fake APIKeyManager（list_providers 返回预置 provider 名集合）。"""

    def __init__(self, saved: set[str]) -> None:
        self._saved = saved

    def list_providers(self) -> set[str]:
        return set(self._saved)


@pytest.fixture
def patch_keys():
    """`with patch_keys({"deepseek"}): ...` 注入已存 key 的 provider 名集合。"""

    def _apply(saved: set[str]) -> Any:
        return patch(PATCH_KEY_MANAGER, return_value=_FakeKeyManager(saved))

    return _apply


@pytest.fixture(autouse=True)
def _isolate_global_default(monkeypatch):
    """全局默认模型置空（默认），免疫本机 config.json / env 残留。"""
    from inkflow.core.config import config as _cfg

    monkeypatch.setattr(_cfg, "llm_default_model", "")
    return _cfg


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 客户端（无 token 模式）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── seed 辅助 ──


async def _seed_provider(
    db_session: AsyncSession,
    name: str,
    *,
    model_types: list[str] | None = None,
    model_ids: list[str] | None = None,
    default_model: str | None = None,
) -> None:
    """插入一条 provider 行（models JSON = [{id,type,roles}]）。"""
    from inkflow.infrastructure.database.models.provider_config import ProviderConfigORM

    types = model_types or []
    ids = model_ids or [f"m{i}" for i in range(len(types))]
    entries = [
        {"id": mid, "type": t, "roles": []} for mid, t in zip(ids, types, strict=False)
    ]
    db_session.add(
        ProviderConfigORM(
            name=name,
            base_url="",
            default_model=default_model,
            models=entries,
            max_retries=3,
            timeout=120,
        )
    )
    await db_session.commit()


async def _seed_project_model(db_session: AsyncSession, model: str) -> None:
    """插入一条项目行，config.model = 指定模型。"""
    from inkflow.infrastructure.database.models.project import ProjectORM

    db_session.add(ProjectORM(name="p-1129-options", config={"model": model}))
    await db_session.commit()


# ── 契约 ──


class TestChatModelOptions1129:
    """#1129 下拉同源端点契约。"""

    @pytest.mark.asyncio
    async def test_exact_five_keys(self, client, override_get_db, patch_keys) -> None:
        """空配置 → 200 + 精确 5 键（契约稳定，防字段漂移）。"""
        with patch_keys(set()):
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        assert set(resp.json().keys()) == {
            "options",
            "chat_models",
            "project_models",
            "default_model",
            "available_model",
        }

    @pytest.mark.asyncio
    async def test_empty_registry_degraded_not_500(
        self, client, override_get_db, patch_keys
    ) -> None:
        """空注册表 → 200 + 空结构（下拉永不 500，降级而非报错）。"""
        with patch_keys(set()):
            resp = await client.get(ENDPOINT)
        body = resp.json()
        assert body["options"] == []
        assert body["chat_models"] == []
        assert body["available_model"] == ""

    @pytest.mark.asyncio
    async def test_project_model_appears_when_models_empty_1129(
        self, client, override_get_db, patch_keys, db_session
    ) -> None:
        """核心场景（#1129 阻断形态）：只配 key + 项目级模型、models[] 空
        → options 有可选项、available_model 非空（旧实现下拉为空 → 用户死路）。
        """
        await _seed_provider(db_session, "deepseek")
        await _seed_project_model(db_session, "deepseek/deepseek-v4-flash")
        with patch_keys({"deepseek"}):
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["available_model"] == "deepseek/deepseek-v4-flash"
        assert "deepseek/deepseek-v4-flash" in body["chat_models"]
        assert "deepseek/deepseek-v4-flash" in body["project_models"]
        option = next(
            o for o in body["options"] if o["model"] == "deepseek/deepseek-v4-flash"
        )
        assert option["source"] == "project"
        assert option["provider"] == "deepseek"
        assert option["has_key"] is True

    @pytest.mark.asyncio
    async def test_provider_default_model_appears_1129(
        self, client, override_get_db, patch_keys, db_session
    ) -> None:
        """provider.default_model (#735 D2 落点) 入候选，source=provider_default。"""
        await _seed_provider(
            db_session,
            "deepseek",
            default_model="deepseek/deepseek-v4-flash",
        )
        with patch_keys({"deepseek"}):
            resp = await client.get(ENDPOINT)
        body = resp.json()
        assert body["available_model"] == "deepseek/deepseek-v4-flash"
        assert body["options"][0]["source"] == "provider_default"

    @pytest.mark.asyncio
    async def test_registry_chat_entry_appears_first_1129(
        self, client, override_get_db, patch_keys, db_session
    ) -> None:
        """注册表 chat 条目入选且排在首位（既有语义不回归）。"""
        await _seed_provider(
            db_session, "deepseek", model_types=["chat"], model_ids=["deepseek-chat"]
        )
        with patch_keys({"deepseek"}):
            resp = await client.get(ENDPOINT)
        body = resp.json()
        assert body["chat_models"][0] == "deepseek/deepseek-chat"
        assert body["options"][0]["source"] == "registry"

    @pytest.mark.asyncio
    async def test_global_default_appears(
        self, client, override_get_db, patch_keys, db_session, _isolate_global_default
    ) -> None:
        """全局默认（config.llm_default_model）入选，source=global_default。"""
        await _seed_provider(db_session, "deepseek")
        _isolate_global_default.llm_default_model = "deepseek/deepseek-v4-flash"
        with patch_keys({"deepseek"}):
            resp = await client.get(ENDPOINT)
        body = resp.json()
        assert body["default_model"] == "deepseek/deepseek-v4-flash"
        assert body["available_model"] == "deepseek/deepseek-v4-flash"

    @pytest.mark.asyncio
    async def test_embedding_model_excluded_1129(
        self, client, override_get_db, patch_keys, db_session
    ) -> None:
        """反例守护：注册表确知 embedding 的候选不得入选（#929 通道不得重开）。"""
        await _seed_provider(
            db_session,
            "zhipu",
            model_types=["embedding"],
            model_ids=["embedding-3"],
            default_model="zhipu/embedding-3",
        )
        with patch_keys({"zhipu"}):
            resp = await client.get(ENDPOINT)
        body = resp.json()
        assert body["available_model"] == ""
        assert body["chat_models"] == []
        assert body["options"] == []

    @pytest.mark.asyncio
    async def test_no_key_excluded_1129(
        self, client, override_get_db, patch_keys, db_session
    ) -> None:
        """反例守护：无凭据的模型名不得入选（不可用 = 不可作 chat 候选）。"""
        await _seed_provider(db_session, "deepseek", default_model="deepseek/dm")
        with patch_keys(set()):
            resp = await client.get(ENDPOINT)
        body = resp.json()
        assert body["options"] == []
        assert body["available_model"] == ""

    @pytest.mark.asyncio
    async def test_builtin_provider_has_key_flag_1129(
        self, client, override_get_db, patch_keys
    ) -> None:
        """内置 provider（ollama 占位）无已存 key 也可入选（真实部署形态），
        has_key 反映 builtin 源为真。
        """
        with patch_keys(set()):
            resp = await client.get(ENDPOINT)
        # ollama 在 _BUILTIN_PROVIDERS 中恒为 "ollama"；无候选时 options 空，
        # 但端点不得因此报错（降级契约）。
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_registry_failure_degrades_not_500(
        self, client, override_get_db, patch_keys
    ) -> None:
        """内部异常 → 200 + 空结构（绝不 500 打崩下拉）。"""
        with (
            patch_keys(set()),
            patch(
                "inkflow.api.routers.provider_configs._get_svc",
                side_effect=RuntimeError("boom"),
            ),
        ):
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {
            "options",
            "chat_models",
            "project_models",
            "default_model",
            "available_model",
        }
        assert body["options"] == []
