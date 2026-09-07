"""#1011 服务层自愈 WARNING 端到端可见 契约测试.

缺陷背景（#1011，已终裁）
-------------------------
v0.13.0-rc6 打包产物冷启动全新库：reindex 成功 → 立即 retrieve 首调 500。stack trace 证明
服务层自愈（_extraction_rag.py:489 except VectorStoreError → reindex → 第二次 retrieve L497）
确实执行了，但 store 层写后落盘窗口（≈2s 双保险合计）追不上冷启动 hnsw 段落盘（实测 ≈26s
才就绪）。

同时发现观测缺陷：_extraction_rag.py 等服务层模块（22 个）用标准 logging
（logging.getLogger(__name__)），而 core/log.py::setup_logging 只配 loguru sinks、无
std→loguru 拦截桥 → 自愈 WARNING 恒不落盘，造成「自愈从未触发」的错觉。

本文件锁定「观测缺陷」修复后的端到端可见性（双形态），补齐 #823 测试（仅 mock 断言
reindex 触发，未锁 WARNING 落盘可见）的观测闭环缺口：

契约形态（本文件，代码已 GREEN，属契约锁定批而非 RED）
------------------------------------------------------
1. caplog 形态：服务层自愈 WARNING 经标准 logging 以 logger 名
   「inkflow.domain.services._extraction_rag」出现，message 含「重建索引」。
2. 端到端闭环：调 setup_logging(log_dir=tmp_path) 装桥后执行同一自愈场景，读
   inkflow_*.log 文件内容断言含「重建索引」——证明自愈 WARNING 经 std→loguru 拦截桥
   真实落盘（#1011「自愈从未触发」错觉终结锁）。

Helper/_Deps 约定
-----------------
复用 test_extraction_retrieve.py:687-739 的 _Deps/_project/RetrievedEntity 构造镜像
（本文件自包含最小副本，不 import 既有测试文件）；仅 mock vector store，无需真实
FakeEmbeddings / reindex 重建。
"""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.core import log as log_module
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.ports.extraction_errors import VectorStoreError
from inkflow.domain.ports.vector_store import EntityType, RetrievedEntity
from inkflow.domain.services.extraction_service import ExtractionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"
_LOG_LOGGER_NAME = "inkflow.domain.services._extraction_rag"
_SELF_HEAL_MARKER = "重建索引"  # 自愈 WARNING 关键措辞（.retrieve 中 logger.warning）


def _project(*, extra: dict[str, Any] | None = None, model: str = DEFAULT_MODEL) -> Project:
    """构造测试项目（config.extra 可注入设置项；镜像 test_extraction_retrieve.py）。"""
    return Project(
        id=PID,
        name="测试项目",
        config=ProjectConfig(model=model, extra=extra or {}),
        created_at=TS,
        updated_at=TS,
    )


_NO_VECTOR = object()


class _Deps:
    """测试用依赖集合 — 全部 Mock，可逐项覆盖后调用 service() 装配门面。

    仅复制 test_extraction_retrieve.py 中与本契约相关的装配（vector_store / reindex /
    retrieve 接线），其余依赖以最小 Mock 补齐构造签名。
    """

    def __init__(self, project: Project | None = None) -> None:
        self.project = project
        self.project_repo = MagicMock()
        self.project_repo.get = AsyncMock(return_value=project)
        self.chapter_repo = MagicMock()
        self.chapter_repo.list_chapters = AsyncMock(return_value=([], 0))
        self.run_repo = MagicMock()
        self.run_repo.upsert = AsyncMock(side_effect=lambda r: r)
        self.character_service = MagicMock()
        self.character_service.extract = AsyncMock()
        self.world_service = MagicMock()
        self.world_service.extract = AsyncMock()
        self.outline_service = MagicMock()
        self.outline_service.generate = AsyncMock()
        self.timeline_service = MagicMock()
        self.timeline_service.check_consistency = AsyncMock()
        self.foreshadowing_extractor = MagicMock()
        self.foreshadowing_extractor.extract = AsyncMock()
        self.timeline_extractor = MagicMock()
        self.timeline_extractor.extract = AsyncMock()
        self.style_service = MagicMock()
        self.style_service.analyze = AsyncMock()
        self.character_repo = MagicMock()
        self.character_repo.list = AsyncMock(return_value=([], 0))
        self.world_repo = MagicMock()
        self.world_repo.list = AsyncMock(return_value=([], 0))
        self.timeline_repo = MagicMock()
        self.timeline_repo.list_all = AsyncMock(return_value=[])
        self.foreshadowing_repo = MagicMock()
        self.foreshadowing_repo.list = AsyncMock(return_value=([], 0))
        self.vector_store = MagicMock()
        self.vector_store.index_batch = AsyncMock()
        self.vector_store.retrieve = AsyncMock()

    def service(self, *, vector_store: Any = _NO_VECTOR) -> ExtractionService:
        """装配门面；vector_store 传 None 模拟 RAG 未装配。"""
        vs = self.vector_store if vector_store is _NO_VECTOR else vector_store
        return ExtractionService(
            project_repo=self.project_repo,
            chapter_repo=self.chapter_repo,
            run_repo=self.run_repo,
            character_service=self.character_service,
            world_service=self.world_service,
            outline_service=self.outline_service,
            timeline_service=self.timeline_service,
            foreshadowing_extractor=self.foreshadowing_extractor,
            timeline_extractor=self.timeline_extractor,
            style_service=self.style_service,
            character_repo=self.character_repo,
            world_repo=self.world_repo,
            timeline_repo=self.timeline_repo,
            foreshadowing_repo=self.foreshadowing_repo,
            vector_store=vs,
        )


@pytest.fixture(autouse=True)
def _restore_log_state():
    """每用例后恢复 loguru 默认 stderr sink + std logging 根 handler/level。

    镜像 tests/unit/core/test_log_intercept_bridge_1011.py 的 _restore_log_state 手法：
    setup_logging 里 logger.remove() 有全局副作用；std logging 根 logger 的 handlers
    亦会被桥修改 → 保存/恢复，防跨用例污染（含本文件两契约间及对其它测试文件的隔离）。
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    log_module.logger.remove()
    log_module.logger.add(sys.stderr, level="DEBUG")
    root.handlers = saved_handlers
    root.setLevel(saved_level)


def _log_files(directory: Path) -> list[Path]:
    """directory 下现有 inkflow 日志文件列表（无则空列表）。"""
    return sorted(directory.glob("inkflow_*.log"))


def _hits() -> list[RetrievedEntity]:
    """第二次 retrieve 返回的命中实体（自愈后成功路径）。"""
    return [
        RetrievedEntity(
            entity_id=str(uuid.uuid4()),
            entity_type=EntityType.FORESHADOWING,
            content="伏笔：铜镜",
            relevance_score=0.82,
            metadata={"project_id": str(PID)},
        )
    ]


def _vector_store_error() -> VectorStoreError:
    """hnsw 段读取失败（#823/#468 同族）——触发自愈重试的确定性异常。"""
    return VectorStoreError("向量检索失败：chromadb hnsw 段读取失败（foreshadowing）")


# ── 契约 1：caplog 形态——自愈 WARNING 经标准 logging 可见 ──


async def test_selfheal_emits_std_logging_warning(caplog: pytest.LogCaptureFixture) -> None:
    """契约 1：#1011 服务层自愈经标准 logging 发出 WARNING（caplog 锁定观测）。"""
    deps = _Deps(_project())
    svc = deps.service()
    svc.reindex = AsyncMock()  # 接管真实 reindex（无需真实重建，仅断言触发一次）
    hits = _hits()
    deps.vector_store.retrieve = AsyncMock(side_effect=[_vector_store_error(), hits])

    caplog.set_level(logging.WARNING, logger=_LOG_LOGGER_NAME)

    items = await svc.retrieve("铜镜", project_id=PID, entity_types=[EntityType.FORESHADOWING])

    svc.reindex.assert_awaited_once()
    svc.reindex.assert_awaited_once_with(PID, [EntityType.FORESHADOWING])
    assert deps.vector_store.retrieve.await_count == 2
    assert items == hits

    warning_records = [
        r for r in caplog.records if r.name == _LOG_LOGGER_NAME and r.levelno == logging.WARNING
    ]
    assert warning_records, (
        f"应捕获到服务层自愈 WARNING 记录，实际 0 条（logger={_LOG_LOGGER_NAME} "
        "propagate 必需，缺观测闭环）"
    )
    assert any(_SELF_HEAL_MARKER in r.getMessage() for r in warning_records), (
        f"自愈 WARNING message 应含「{_SELF_HEAL_MARKER}」，实际："
        + " | ".join(r.getMessage() for r in warning_records)
    )


# ── 契约 2：端到端闭环——自愈 WARNING 经 std→loguru 桥真实落盘 ──


async def test_selfheal_warning_reaches_file_sink_with_bridge(tmp_path: Path) -> None:
    """契约 2：#1011 自愈 WARNING 经 std→loguru 拦截桥真实落 inkflow_*.log。

    桥 GREEN 的直接验收：调 setup_logging(log_dir=tmp_path) 装桥后执行与契约 1 相同的
    自愈场景，然后读 tmp_path 下 inkflow_*.log 内容断言含「重建索引」——证明服务层
    自愈 WARNING 不再「恒不落盘」（#1011「自愈从未触发」错觉的终结锁）。
    """
    log_module.setup_logging(log_dir=tmp_path)

    deps = _Deps(_project())
    svc = deps.service()
    svc.reindex = AsyncMock()
    hits = _hits()
    deps.vector_store.retrieve = AsyncMock(side_effect=[_vector_store_error(), hits])

    items = await svc.retrieve("铜镜", project_id=PID, entity_types=[EntityType.FORESHADOWING])

    svc.reindex.assert_awaited_once()
    assert items == hits

    files = _log_files(tmp_path)
    assert files, "setup_logging 未创建 loguru 文件 sink（前置：文件 sink 应存在）"
    contents = "\n".join(p.read_text(encoding="utf-8") for p in files)
    assert _SELF_HEAL_MARKER in contents, (
        f"std→loguru 桥未生效：服务层自愈 WARNING 未落 inkflow_*.log（"
        f"{_LOG_LOGGER_NAME} 应经 InterceptHandler 进文件 sink）。文件内容采样："
        + (contents[:200] if contents else "<空>")
    )
