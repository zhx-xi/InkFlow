"""#479 依赖装配 deps_kg_extract — 真实装配 + scheduler 503 分支契约测试（覆盖率收尾）。

补测 G2 抽出 deps_kg_extract 后的装配胶水（测试主体经 dependency_overrides 覆盖，
本文件覆盖真实路径：get_relation_extraction_service 装配 + get_kg_extract_scheduler
未就绪 503 / 就绪返回）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from inkflow.api.deps_kg_extract import (
    get_kg_extract_scheduler,
    get_relation_extraction_service,
)
from inkflow.domain.services.relation_extraction_service import RelationExtractionService


class TestGetRelationExtractionService:
    """真实装配（db 用鸭子 session，构造不查询）。"""

    def test_assembles_relation_extraction_service(self):
        db = AsyncMock()
        svc = get_relation_extraction_service(db)
        assert isinstance(svc, RelationExtractionService)

    def test_key_manager_factory_builds(self):
        """调用 key_manager_factory 触发真实 _get_key_manager 闭包（AI 门禁依赖）。"""
        db = AsyncMock()
        svc = get_relation_extraction_service(db)
        km = svc._key_manager_factory()  # 闭包体执行（真实 APIKeyManager 构造）
        assert km is not None


class TestGetKgExtractScheduler:
    """scheduler getter：未就绪 503 / 就绪返回。"""

    def test_not_ready_raises_503(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        with pytest.raises(HTTPException) as exc:
            get_kg_extract_scheduler(request)
        assert exc.value.status_code == 503

    def test_ready_returns_scheduler(self):
        sched = object()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(kg_scheduler=sched)))
        result = get_kg_extract_scheduler(request)
        assert result is sched
