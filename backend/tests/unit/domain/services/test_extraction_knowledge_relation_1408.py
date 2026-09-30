"""#1408 契约：extract run --type knowledge_relation 打通（CLI 收 7 种，服务层只注册 6 种）。

根因（issue #1408 实证）：`ExtractionType.KNOWLEDGE_RELATION` 在枚举里、CLI `--type` 的
choices 由枚举自动派生（**接受 7 个值**），但 `ExtractionService` 的 handler 注册表只注册
6 种 → 门面在 `_handlers.get(...) is None` 处抛 `UnsupportedExtractionTypeError`
（domain/ports/extraction_errors.py → API 422「不支持的提取类型」）。
能力其实存在：`inkflow knowledge extract --method rule` 可跑通（零 LLM、model=null）。

本文件锁定修复后的**服务层契约**（方案 A：把 KNOWLEDGE_RELATION 接到 F48
RelationExtractionService，两条入口殊途同归）：

1. **7 槽全注册** —— 注册表键集合 == `ExtractionType` 全集；枚举扩张而忘注册 → FAIL
   （这就是 #1408 的漂移形态，本条即防复发闸门）。
2. **分发** —— KNOWLEDGE_RELATION → `RelationExtractionService.extract_for_project(
   project_id, method="rule")`（项目级规则关系提取，零 LLM，与 `knowledge extract
   --method rule` 同一执行体）。
3. **项目级语义** —— 不接受 `text`/`chapter_ids`（显式 422，同 outline 先例
   「类型不匹配字段一律 422 而非静默忽略」，spec §6.4）；单源 `"full"`、每次执行
   （无增量 skip 价值，同 outline/style）。
4. **降级防御** —— 未装配 relation 服务时保持 422（不静默成功）。
5. **RAG** —— `index=true` 忽略 + warning（关系不在 F14 RAG 投射范围）。

依据: specs/f14-extraction/spec.md §2.1/§5.3/§6.1/§6.4 + issue #1408。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.extraction import (
    ExtractionRequest,
    ExtractionResult,
    ExtractionRun,
    ExtractionStatus,
    ExtractionType,
)
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.ports.extraction_errors import (
    ExtractionValidationError,
    UnsupportedExtractionTypeError,
)
from inkflow.domain.services.extraction_service import ExtractionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CH1 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000011")
TS = datetime(2026, 8, 1, 10, 0, 0)

_NO = object()
"""哨兵：区分「未显式传入」与「显式传 None（模拟未装配）」."""


def _project() -> Project:
    """构造测试项目（KNOWLEDGE_RELATION 不读项目 config.extra）."""
    return Project(
        id=PID,
        name="测试项目",
        config=ProjectConfig(model=None, extra={}),
        created_at=TS,
        updated_at=TS,
    )


def _relation_result(
    *,
    created: int = 5,
    updated: int = 0,
    warnings: list[str] | None = None,
    model: str | None = None,
) -> ExtractionResult:
    """构造 F48 RelationExtractionService 的返回信封（type=knowledge_relation）."""
    return ExtractionResult(
        type=ExtractionType.KNOWLEDGE_RELATION,
        status=ExtractionStatus.SUCCESS,
        created=created,
        updated=updated,
        warnings=warnings if warnings is not None else ["规则提取完成（R1/R2/R3）"],
        model=model,
        detail={"rules": ["r1", "r2", "r3"]},
    )


def _req(**kw: Any) -> ExtractionRequest:
    """构造 KNOWLEDGE_RELATION 请求（默认无源参数——项目级提取）."""
    base: dict[str, Any] = {"project_id": PID, "type": ExtractionType.KNOWLEDGE_RELATION}
    base.update(kw)
    return ExtractionRequest(**base)


class _Deps:
    """最小依赖集合 — 全部 Mock，仅覆盖 KNOWLEDGE_RELATION 分发链（自包含副本）."""

    def __init__(self, project: Project | None = None) -> None:
        self.project_repo = MagicMock()
        self.project_repo.get = AsyncMock(return_value=project)
        self.chapter_repo = MagicMock()
        self.chapter_repo.get_chapter = AsyncMock(return_value=None)
        self.chapter_repo.list_chapters = AsyncMock(return_value=([], 0))
        self.run_repo = MagicMock()
        self.run_repo.get = AsyncMock(return_value=None)
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
        self.world_repo = MagicMock()
        self.timeline_repo = MagicMock()
        self.foreshadowing_repo = MagicMock()
        self.vector_store = MagicMock()
        self.vector_store.index_batch = AsyncMock()
        self.relation_service = MagicMock()
        self.relation_service.extract_for_project = AsyncMock(return_value=_relation_result())

    def service(self, *, relation: Any = _NO, vector_store: Any = _NO) -> ExtractionService:
        """装配门面；relation 显式传 None = 未装配（防御路径）."""
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
            vector_store=self.vector_store if vector_store is _NO else vector_store,
            relation_extraction_service=(self.relation_service if relation is _NO else relation),
        )


def _upserted_runs(deps: _Deps) -> list[ExtractionRun]:
    """收集 run_repo.upsert 收到的全部记录."""
    return [call.args[0] for call in deps.run_repo.upsert.await_args_list]


# ── ① 注册表完整性（#1408 漂移闸门）──────────────────────────────


async def test_handler_registry_covers_every_extraction_type() -> None:
    """注册表键集合 == ExtractionType 全集，且无 None 槽位.

    #1408 根因就是「枚举 7 个值 vs 注册表 6 个槽」——本断言在任何人新增枚举成员却
    忘记注册 handler 时 FAIL（枚举扩张 = 必须同步注册的契约）。
    """
    svc = _Deps(_project()).service()

    assert set(svc._handlers) == set(ExtractionType)
    assert all(handler is not None for handler in svc._handlers.values())


# ── ② 分发（不再 422，走到 F48 relation 服务）────────────────────


async def test_extract_knowledge_relation_dispatches_to_relation_service() -> None:
    """KNOWLEDGE_RELATION 无源参数 → 委托 RelationExtractionService（规则、零 LLM）.

    「不再 422」的服务层证据：修复前此处抛 UnsupportedExtractionTypeError。
    """
    deps = _Deps(_project())
    svc = deps.service()

    result = await svc.extract(_req())

    deps.relation_service.extract_for_project.assert_awaited_once_with(PID, method="rule")
    assert result.type is ExtractionType.KNOWLEDGE_RELATION
    assert result.status is ExtractionStatus.SUCCESS
    assert result.processed_sources == 1
    assert result.skipped_sources == 0
    assert result.created == 5
    assert result.updated == 0
    assert result.model is None  # 规则提取不花 LLM
    assert result.indexed is False


async def test_knowledge_relation_run_recorded_as_full_source() -> None:
    """项目级单源 → run 记录 source_key="full"（同 outline 先例，供 extract status 观察）."""
    deps = _Deps(_project())
    svc = deps.service()

    await svc.extract(_req())

    runs = _upserted_runs(deps)
    assert len(runs) == 1
    assert runs[0].source_key == "full"
    assert runs[0].type is ExtractionType.KNOWLEDGE_RELATION
    assert runs[0].status is ExtractionStatus.SUCCESS
    assert runs[0].created_count == 5


async def test_knowledge_relation_always_executes_no_increment_skip() -> None:
    """项目级单源 "full" 恒执行：run 表已有同 hash 记录也重跑（无增量价值，同 outline/style）."""
    deps = _Deps(_project())
    deps.run_repo.get = AsyncMock(
        return_value=ExtractionRun(
            id=0,
            project_id=PID,
            type=ExtractionType.KNOWLEDGE_RELATION,
            source_key="full",
            content_hash=hashlib.sha256(b"").hexdigest(),
            status=ExtractionStatus.SUCCESS,
            created_count=5,
            run_at=TS,
        )
    )
    svc = deps.service()

    result = await svc.extract(_req())

    deps.relation_service.extract_for_project.assert_awaited_once()
    assert result.status is ExtractionStatus.SUCCESS
    assert result.processed_sources == 1
    assert result.skipped_sources == 0


# ── ③ 项目级语义：源参数显式 422 ────────────────────────────────


@pytest.mark.parametrize(
    "source_kwargs",
    ({"text": "第一章内容"}, {"chapter_ids": [CH1]}),
    ids=("text", "chapter_ids"),
)
async def test_knowledge_relation_rejects_source_args(source_kwargs: dict[str, Any]) -> None:
    """knowledge_relation 是项目级提取：text/chapter_ids 无效 → 422（不静默忽略，spec §6.4）."""
    deps = _Deps(_project())
    svc = deps.service()

    with pytest.raises(ExtractionValidationError):
        await svc.extract(_req(**source_kwargs))

    deps.relation_service.extract_for_project.assert_not_awaited()


# ── ④ 降级防御 ─────────────────────────────────────────────────


async def test_knowledge_relation_without_relation_service_is_unsupported() -> None:
    """未装配 relation 服务 → 保持防御性 422，绝不静默成功."""
    svc = _Deps(_project()).service(relation=None)

    with pytest.raises(UnsupportedExtractionTypeError):
        await svc.extract(_req())


# ── ⑤ RAG：忽略 + warning ──────────────────────────────────────


async def test_knowledge_relation_index_true_ignored_with_warning() -> None:
    """index=true → indexed=False + warning（关系不在 F14 RAG 投射范围，同 style 先例）."""
    deps = _Deps(_project())
    svc = deps.service()

    result = await svc.extract(_req(index=True))

    assert result.indexed is False
    assert "knowledge_relation 类型不支持自动索引" in result.warnings
    deps.vector_store.index_batch.assert_not_awaited()
