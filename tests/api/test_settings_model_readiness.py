"""F60 首启模型就绪判据 API 契约测试（RED — #934 §3.1/§9.2）。

被测端点：`GET /api/v1/settings/model-readiness`（挂既有 settings router）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【端点】`GET /api/v1/settings/model-readiness`，挂在既有
   `inkflow.api.routers.settings.router`（prefix=/api/v1/settings）。RED
   阶段子路由未注册 → 405（路径存在但方法/子路径未匹配）或 404。

2. 【响应契约】200 + body 精确 4 键：
   `{"ready": bool, "has_chat_model": bool, "has_embedding_model": bool,
     "reason": str}`。reason ∈ {"ready","no_provider","no_chat_model","no_key"}，
   ready=true 时 reason="ready"。

3. 【判据同源】端点读 provider_configs 注册表（经 get_db 注入的 session）+
   APIKeyManager.list_providers()（key_saved 语义，镜像
   routers/provider_configs.py:129 的 key 判定）。判据函数 =
   `inkflow.domain.services.model_readiness.compute_readiness`（纯函数，
   单元测试见 tests/unit/test_model_readiness.py）。

4. 【测试注入】DB：override get_db → 本文件 db_session（真 in-memory SQLite，
   用例可插入真实 ProviderORM 行）；key：patch settings 模块的
   `_get_key_manager` → fake（返回预置 provider 名集合）——两处均为端点
   GREEN 实现必须提供的注入点。

5. 【无 token 模式】env INKFLOW_SERVER_TOKEN 未设置 → 中间件直通
   （client fixture 内显式 delenv）；401 用例专用 set_token_env fixture。

6. 【500 契约】DB/内部异常 → 500 + `{"detail": "就绪状态查询失败，请稍后重试"}`
   （ADR-012 通用文案，不泄漏内部细节）。

RED 阶段预期：端点未注册 → 全部用例 FAIL/ERROR。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import inkflow.api.routers.settings  # noqa: F401  # RED 收集断言：模块存在性契约
from inkflow.api.app import app
from inkflow.core.database import Base
from inkflow.domain.models.provider_config import ProviderConfig

# ── 契约常量 ──

ENDPOINT = "/api/v1/settings/model-readiness"
"""就绪判据端点（#934 §3.1，挂 settings router 下）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 中间件直通（无 token 模式）。"""

TEST_TOKEN = "test-token-934-readiness"
"""401 用例固定 token（test_settings_data_dir.py set_token_env 同款）。"""

PATCH_KEY_MANAGER = "inkflow.api.routers.settings._get_key_manager"
"""key 判定注入点（设计假设 #4）：GREEN 须在 settings 模块内以 _get_key_manager() 取 key 集合。"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（设计假设 #4）。

    镜像 tests/integration/test_builtin_seed.py 同款（create_all + PRAGMA
    foreign_keys=ON，生产同口径 #327）。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def override_get_db(db_session):
    """将 FastAPI 的 get_db 替换为本文件 db_session（设计假设 #4）。"""
    from inkflow.api.deps import get_db

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.clear()


class _FakeKeyManager:
    """最小 fake APIKeyManager：list_providers() 返回预置 provider 名集合。"""

    def __init__(self, saved: set[str]) -> None:
        self._saved = saved

    def list_providers(self) -> set[str]:
        return set(self._saved)


@pytest.fixture
def patch_keys():
    """patch _get_key_manager → fake（返回指定已存 key 的 provider 名集合）。

    用法：`with patch_keys({"openai"}): ...`；不调用则该端点默认 patch 为
    空集合（无任何 key）。
    """

    def _apply(saved: set[str]) -> Any:
        return patch(PATCH_KEY_MANAGER, return_value=_FakeKeyManager(saved))

    return _apply


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式：delenv INKFLOW_SERVER_TOKEN）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def set_token_env(monkeypatch):
    """设置 INKFLOW_SERVER_TOKEN（401 用例专用，test_settings_data_dir.py 同款）。"""
    monkeypatch.setenv(ENV_TOKEN, TEST_TOKEN)
    return TEST_TOKEN


# ── seed 辅助（写真实 provider_configs 行）──


async def _seed_provider(
    db_session: AsyncSession,
    name: str,
    models: list[ProviderConfig],
    *,
    model_types: list[str] | None = None,
) -> None:
    """插入一个 provider 行（models JSON = [{id,type,roles}] 形态）。

    直接走 ORM 表以便端点经同一 session 读到（设计假设 #4）。
    """
    from inkflow.infrastructure.database.models.provider_config import ProviderConfigORM

    types = model_types or []
    entries = [{"id": f"m{i}", "type": t, "roles": []} for i, t in enumerate(types)]
    row = ProviderConfigORM(
        name=name,
        base_url="",
        default_model=None,
        models=entries,
        max_retries=3,
        timeout=120,
    )
    db_session.add(row)
    await db_session.commit()


# ── 200 契约：四条 reason 分支 ──


class TestModelReadinessEndpoint:
    """GET /api/v1/settings/model-readiness 契约（#934 §3.1/§3.3）。"""

    @pytest.mark.asyncio
    async def test_empty_registry_no_provider(
        self, client, override_get_db, patch_keys
    ) -> None:
        """空注册表 → 200 + ready=False, reason='no_provider'。"""
        with patch_keys(set()):
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "ready": False,
            "has_chat_model": False,
            "has_embedding_model": False,
            "reason": "no_provider",
        }

    @pytest.mark.asyncio
    async def test_only_embedding_model_no_chat_model_929_regression(
        self, client, override_get_db, patch_keys, db_session
    ) -> None:
        """#929 回归锚：唯一 provider 只配 embedding 模型 + 有 key → no_chat_model。"""
        await _seed_provider(db_session, "zhipu", [], model_types=["embedding"])
        with patch_keys({"zhipu"}):
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is False
        assert body["reason"] == "no_chat_model"
        assert body["has_chat_model"] is False
        assert body["has_embedding_model"] is True

    @pytest.mark.asyncio
    async def test_chat_model_without_key_no_key(
        self, client, override_get_db, patch_keys, db_session
    ) -> None:
        """有 chat 模型但无 key → reason='no_key'。"""
        await _seed_provider(db_session, "openai", [], model_types=["chat"])
        with patch_keys(set()):
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is False
        assert body["reason"] == "no_key"

    @pytest.mark.asyncio
    async def test_chat_model_with_key_ready(
        self, client, override_get_db, patch_keys, db_session
    ) -> None:
        """有 chat 模型 + key → ready=True, reason='ready'（N3/N4 升级零打扰）。"""
        await _seed_provider(db_session, "deepseek", [], model_types=["chat"])
        with patch_keys({"deepseek"}):
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is True
        assert body["reason"] == "ready"
        assert body["has_chat_model"] is True

    @pytest.mark.asyncio
    async def test_has_embedding_model_with_chat(
        self, client, override_get_db, patch_keys, db_session
    ) -> None:
        """chat + embedding 双配 + key → ready=True 且 has_embedding_model=True（N2）。"""
        await _seed_provider(db_session, "deepseek", [], model_types=["chat", "embedding"])
        with patch_keys({"deepseek"}):
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is True
        assert body["has_embedding_model"] is True

    @pytest.mark.asyncio
    async def test_response_has_exactly_four_keys(
        self, client, override_get_db, patch_keys
    ) -> None:
        """响应精确 4 键（契约稳定，防未来字段漂移）。"""
        with patch_keys(set()):
            resp = await client.get(ENDPOINT)
        assert set(resp.json().keys()) == {
            "ready",
            "has_chat_model",
            "has_embedding_model",
            "reason",
        }

    @pytest.mark.asyncio
    async def test_idempotent_repeated_calls(
        self, client, override_get_db, patch_keys, db_session
    ) -> None:
        """就绪后重复调用幂等（只读端点，无副作用）。"""
        await _seed_provider(db_session, "deepseek", [], model_types=["chat"])
        with patch_keys({"deepseek"}):
            first = await client.get(ENDPOINT)
            second = await client.get(ENDPOINT)
        # 显式断言状态码：RED 阶段端点缺失返回 404，若只比 body 会假绿
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()


# ── 401 / 500 异常路径 ──


class TestModelReadinessErrors:
    """异常映射（#934 §3.3）。"""

    @pytest.mark.asyncio
    async def test_without_token_401(self, client, set_token_env) -> None:
        """token 环境变量已设置且请求不带 token → 401（全站中间件契约）。"""
        resp = await client.get(ENDPOINT)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_registry_failure_500_generic_detail(
        self, client, override_get_db, patch_keys
    ) -> None:
        """注册表读取异常 → 500 + 通用文案（不泄漏内部细节，ADR-012）。"""
        with (
            patch_keys(set()),
            patch(
                "inkflow.api.routers.settings.compute_model_readiness",
                side_effect=RuntimeError("boom-internal-detail"),
            ),
        ):
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 500
        assert resp.json()["detail"] == "就绪状态查询失败，请稍后重试"
        assert "boom-internal-detail" not in resp.text
