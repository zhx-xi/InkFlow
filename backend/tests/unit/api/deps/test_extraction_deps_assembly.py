"""RED 契约（#536）：get_extraction_service 未配置 embedding 时仍装配成功
（vector_store=None 降级）。

缺陷背景（0.11.0-rc1 实证 2026-08-20）：deps.py get_extraction_service 无条件
`vector_store = await get_vector_store()`——未配置 embedding 模型时 RAGUnavailableError
在 service 构造阶段抛出 → `extract run --type character`（CLI 默认 index=False，
纯 LLM 提取路径，根本不需要向量库）全部 500「未配置 embedding 模型」。

契约：
- 未配置 embedding（get_vector_store 抛 RAGUnavailableError）→ get_extraction_service
  返回实例且 `._vector_store is None`（降级成功，非 500）
- 配置 embedding（get_vector_store 返回 fake）→ `._vector_store` 非 None（对照）

同族先例：get_search_service 已用 get_vector_store_optional()（#264）。

⚠️ RED 期形态：当前无条件 get_vector_store() → 未配 embedding 时异常上抛 → 断言 FAIL（干净 RED）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inkflow.api import deps
from inkflow.domain.ports.extraction_errors import RAGUnavailableError


@pytest.fixture
def db() -> MagicMock:
    """Mock AsyncSession — service getter 仅透传 session，不执行 SQL（test_api_deps.py 同款）。"""
    return MagicMock()


@pytest.fixture(autouse=True)
def _reset_vector_store_singleton():
    """每个用例前后重置模块级 _vector_store 单例，隔离懒加载状态（test_api_deps.py 同款）。"""
    original = deps._vector_store
    deps._vector_store = None
    yield
    deps._vector_store = original


async def test_extraction_service_assembles_without_embedding(db) -> None:
    """未配置 embedding（get_vector_store 抛 RAGUnavailableError）→ 装配成功且 vector_store=None。

    #536：无条件 get_vector_store() 让 extract run（index=False 纯 LLM 路径）500；
    修复后应降级为 None，服务层仅在 index=True 时才报 RAGUnavailableError。
    """
    with patch.object(
        deps, "get_vector_store",
        AsyncMock(side_effect=RAGUnavailableError("未配置 embedding 模型")),
    ):
        svc = await deps.get_extraction_service(db=db)
    assert svc is not None
    assert svc._vector_store is None, "未配置 embedding 时应注入 None（降级）"


async def test_extraction_service_vector_store_injected_when_configured(db) -> None:
    """配置 embedding（get_vector_store 返回 fake）→ vector_store 非 None（对照）。"""
    fake_store = AsyncMock()
    fake_store.embedding_dimension = 1024
    with patch.object(deps, "get_vector_store", AsyncMock(return_value=fake_store)):
        svc = await deps.get_extraction_service(db=db)
    assert svc._vector_store is not None, "配置 embedding 后应注入实例"
