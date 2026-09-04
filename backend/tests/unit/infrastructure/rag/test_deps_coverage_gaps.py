"""Coverage backfill: api/deps.py 公开装配函数返回体 + index rebuild vector 分支。

公开接口：直接调用 deps 依赖装配函数（构造无 I/O，仅组装服务实例）：
- get_draft_service / get_session_service / get_export_service 返回体（223/499/610）
- get_index_rebuild_service 在 vector store 可用时注入 vector 重建器（682）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from inkflow.api import deps
from inkflow.domain.services.draft_service import DraftService
from inkflow.domain.services.index_rebuild_service import IndexRebuildService
from inkflow.domain.services.output_service import ExportService
from inkflow.domain.services.session_service import SessionService


def test_get_draft_service_returns_assembled_instance() -> None:
    svc = deps.get_draft_service(db=MagicMock())
    assert isinstance(svc, DraftService)


def test_get_session_service_returns_assembled_instance() -> None:
    svc = deps.get_session_service(db=MagicMock())
    assert isinstance(svc, SessionService)


def test_get_export_service_returns_assembled_instance() -> None:
    svc = deps.get_export_service(db=MagicMock())
    assert isinstance(svc, ExportService)


@pytest.mark.asyncio
async def test_get_index_rebuild_service_injects_vector_when_available(
    monkeypatch,
) -> None:
    monkeypatch.setattr(deps, "_index_rebuild_service_instance", None)
    with patch(
        "inkflow.api.deps.get_vector_store_optional",
        return_value=MagicMock(),
    ):
        svc = await deps.get_index_rebuild_service(db=MagicMock())

    assert isinstance(svc, IndexRebuildService)
    # DI 装配断言：vector store 可用时注入重建器（镜像 test_book_deps_assembly 的装配检查）
    assert svc._vector is not None  # 装配检查：IndexRebuildService 私有字段
