"""RAG 索引编排 + reindex 全量 — Mock 各模块 Service + Repo + VectorStore。

覆盖: RAG 索引编排（index=true 实体投影 + 未装配报错）/ reindex 全量。

拆分自 test_extraction_service.py（#281 测试文件规模治理）；
共享 helper/_Deps 定义见本文件（各拆分文件自包含副本）。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.character import (
    Character,
    CharacterExtractionResult,
)
from inkflow.domain.models.extraction import (
    ExtractionRequest,
    ExtractionRun,
    ExtractionStatus,
    ExtractionType,
    ReindexResult,
)
from inkflow.domain.models.foreshadowing import (
    Foreshadowing,
    ForeshadowingExtractionResult,
    ForeshadowingStatus,
)
from inkflow.domain.models.outline import (
    OutlineGenerationResult,
)
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.models.timeline import (
    ConsistencyReport,
    TimelineEvent,
    TimelineExtractionResult,
)
from inkflow.domain.models.world import (
    WorldExtractionResult,
    WorldSetting,
)
from inkflow.domain.ports.extraction_errors import (
    RAGUnavailableError,
)
from inkflow.domain.ports.vector_store import EntityType
from inkflow.domain.services.extraction_service import ExtractionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OTHER_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
CH1 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000011")
CH2 = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000012")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"
CUSTOM_MODEL = "anthropic/claude-3.5-sonnet"
CONTENT_1 = "第一章内容：林晚走进青云城，风尘仆仆。"
CONTENT_2 = "第二章内容：沈砚在城门等候多时。"


def _sha(text: str) -> str:
    """计算源内容 sha256 指纹（与门面增量判定一致，§5.2）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _project(*, extra: dict[str, Any] | None = None, model: str = DEFAULT_MODEL) -> Project:
    """构造测试项目（config.extra 可注入 timeline_auto_extract 设置项）。"""
    return Project(
        id=PID,
        name="测试项目",
        config=ProjectConfig(model=model, extra=extra or {}),
        created_at=TS,
        updated_at=TS,
    )


def _chapter(
    cid: uuid.UUID,
    content: str,
    *,
    project_id: uuid.UUID = PID,
    title: str = "章",
) -> Chapter:
    """构造测试章节（默认属于 PID）。"""
    return Chapter(id=cid, project_id=project_id, title=title, content=content)


def _char(name: str, *, project_id: uuid.UUID = PID) -> Character:
    """构造测试角色实体。"""
    return Character(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        personality="冷静",
        background="出身寒门",
        goals="复仇",
        created_at=TS,
        updated_at=TS,
    )


def _setting(name: str) -> WorldSetting:
    """构造测试世界观条目实体。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        category="地理",
        content="青云城坐落于群山之间",
        created_at=TS,
        updated_at=TS,
    )


def _fs(title: str) -> Foreshadowing:
    """构造测试伏笔实体。"""
    return Foreshadowing(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        description="铜镜的秘密",
        priority=50,
        status=ForeshadowingStatus.OPEN,
        location="第 1 章",
        created_at=TS,
        updated_at=TS,
    )


def _event(title: str, *, chapter_id: uuid.UUID | None = CH1) -> TimelineEvent:
    """构造测试时间线事件实体（默认来源章节 CH1）。"""
    return TimelineEvent(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        description="林晚入宫",
        time_value=3.5,
        time_unit="年",
        narrative_position=1,
        timeline_flag="",
        source_chapter_id=chapter_id,
        created_at=TS,
        updated_at=TS,
    )


def _run(
    source_key: str,
    content_hash: str,
    *,
    type_: ExtractionType = ExtractionType.CHARACTER,
    status: ExtractionStatus = ExtractionStatus.SUCCESS,
    created_count: int = 0,
    updated_count: int = 0,
    model: str | None = None,
) -> ExtractionRun:
    """构造测试 run 记录（id=0 占位，同仓储测试约定）。"""
    return ExtractionRun(
        id=0,
        project_id=PID,
        type=type_,
        source_key=source_key,
        content_hash=content_hash,
        status=status,
        created_count=created_count,
        updated_count=updated_count,
        model=model,
        run_at=TS,
    )


def _character_result(
    *,
    created: int = 1,
    updated: int = 0,
    warnings: list[str] | None = None,
    model: str = DEFAULT_MODEL,
) -> CharacterExtractionResult:
    """构造角色提取管线返回结果。"""
    return CharacterExtractionResult(
        created=[_char(f"角色{i}") for i in range(created)],
        updated=[_char(f"旧角色{i}") for i in range(updated)],
        relations_created=[],
        relations_updated=[],
        warnings=warnings or [],
        model=model,
    )


def _world_result(
    *,
    created: int = 1,
    updated: int = 0,
    warnings: list[str] | None = None,
    model: str = DEFAULT_MODEL,
) -> WorldExtractionResult:
    """构造世界观提取管线返回结果。"""
    return WorldExtractionResult(
        created=[_setting(f"设定{i}") for i in range(created)],
        updated=[_setting(f"旧设定{i}") for i in range(updated)],
        warnings=warnings or [],
        model=model,
    )


def _outline_result(
    *,
    saved: bool = True,
    warnings: list[str] | None = None,
    model: str = DEFAULT_MODEL,
) -> OutlineGenerationResult:
    """构造大纲生成管线返回结果。"""
    return OutlineGenerationResult(
        saved=saved,
        outline=None,
        plot_points=[],
        arcs=[],
        preview=None,
        warnings=warnings or [],
        model=model,
    )


def _fs_result(
    *,
    created: int = 1,
    updated: int = 0,
    warnings: list[str] | None = None,
    model: str = DEFAULT_MODEL,
) -> ForeshadowingExtractionResult:
    """构造伏笔提取管线返回结果。"""
    return ForeshadowingExtractionResult(
        created=[_fs(f"伏笔{i}") for i in range(created)],
        updated=[_fs(f"旧伏笔{i}") for i in range(updated)],
        warnings=warnings or [],
        model=model,
    )


def _timeline_result(
    *,
    created: int = 1,
    updated: int = 0,
    warnings: list[str] | None = None,
    model: str = DEFAULT_MODEL,
) -> TimelineExtractionResult:
    """构造时间线提取管线返回结果。"""
    return TimelineExtractionResult(
        created=[_event(f"事件{i}") for i in range(created)],
        updated=[_event(f"旧事件{i}") for i in range(updated)],
        warnings=warnings or [],
        model=model,
    )


def _consistency_report() -> ConsistencyReport:
    """构造 F12 一致性检查报告（无冲突空报告）。"""
    return ConsistencyReport(
        project_id=PID,
        checked=0,
        skipped=0,
        consistent=True,
        conflicts=[],
        flashbacks=[],
        event_timeline=[],
        narrative_order=[],
    )


def _style_report(**overrides: Any) -> Any:
    """构造 F16 StyleReport（spec §2.6）— 惰性 import F16 模型。

    模型未实现时（RED 阶段）仅 STYLE 用例失败，不影响本文件其他 F14 用例收集。
    """
    from inkflow.domain.models.style import (
        AITraceAssessment,
        AITraceFeature,
        AITraceVerdict,
        LexicalAnalysis,
        StyleFingerprint,
        StyleReport,
        WordFrequency,
    )

    kwargs: dict[str, Any] = {
        "project_id": PID,
        "source": "manual",
        "generated_at": TS,
        "fingerprint": StyleFingerprint(
            char_count=48,
            sentence_count=3,
            avg_sentence_length=16.0,
            sentence_length_std=9.9,
            paragraph_count=1,
            avg_paragraph_length=48.0,
            punctuation_density=0.1667,
            exclamation_density=0.0,
            ellipsis_density=0.0417,
            dialogue_ratio=0.2083,
            vocabulary_richness=0.8235,
            top_words=[WordFrequency(word="林晚", count=1, first_index=0)],
        ),
        "ai_trace": AITraceAssessment(
            ai_score=0.26,
            verdict=AITraceVerdict.LIKELY_HUMAN,
            features=[
                AITraceFeature(
                    feature="sentence_uniformity",
                    value=0.62,
                    score=0.38,
                    note="句长变异系数 0.62——句式波动正常",
                )
            ],
            evidence=["各特征得分均低于 0.5，无明显 AI 特征（综合得分 0.26 → likely_human）"],
        ),
        "lexical": LexicalAnalysis(
            total_words=17,
            unique_words=14,
            top_words=[WordFrequency(word="林晚", count=1, first_index=0)],
            avg_word_length=2.1,
            stopword_ratio=0.0588,
        ),
        "llm_assessment": None,
        "warnings": ["未检测到完整句子（句尾符不足）——句子统计仅供参考"],
    }
    kwargs.update(overrides)
    return StyleReport(**kwargs)  # type: ignore[arg-type]  # kwargs 为动态 dict，无法静态匹配构造器参数签名


def _req(type_: ExtractionType, **kw: Any) -> ExtractionRequest:
    """构造 ExtractionRequest（自动带 project_id=PID）。"""
    base: dict[str, Any] = {"project_id": PID, "type": type_}
    base.update(kw)
    return ExtractionRequest(**base)


def _chapter_by_id(cid: int) -> Chapter:
    """按仓储层 int id 返回对应测试章节（CH1/CH2 两章批量场景用）。"""
    return _chapter(CH1, CONTENT_1) if cid == CH1.int else _chapter(CH2, CONTENT_2)


_NO_VECTOR = object()


class _Deps:
    """测试用依赖集合 — 全部 Mock，可逐项覆盖后调用 service() 装配门面。"""

    def __init__(self, project: Project | None = None) -> None:
        self.project = project
        self.project_repo = MagicMock()
        self.project_repo.get = AsyncMock(return_value=project)
        self.chapter_repo = MagicMock()
        self.chapter_repo.get_chapter = AsyncMock(return_value=None)
        self.chapter_repo.list_chapters = AsyncMock(return_value=([], 0))
        self.run_repo = MagicMock()
        self.run_repo.get = AsyncMock(return_value=None)
        self.run_repo.upsert = AsyncMock(side_effect=lambda r: r)
        self.run_repo.list = AsyncMock(return_value=([], 0))
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
        # #276 G4（2026-08-12）：reindex 协议新方法——probe 维度/差集删除/指纹
        self.vector_store.probe_embedding_dimension = AsyncMock(return_value=384)
        self.vector_store.probe_collection_dimension = AsyncMock(return_value=0)
        self.vector_store.delete_stale = AsyncMock(return_value=0)
        self.vector_store.write_fingerprint = AsyncMock()

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
            style_service=self.style_service,  # F16: STYLE 槽位 handler（spec §8.2）
            character_repo=self.character_repo,
            world_repo=self.world_repo,
            timeline_repo=self.timeline_repo,
            foreshadowing_repo=self.foreshadowing_repo,
            vector_store=vs,
        )

    def stub_chapter(self, chapter: Chapter | None) -> None:
        """让章节仓储返回指定章节（None = 不存在）。"""
        self.chapter_repo.get_chapter = AsyncMock(return_value=chapter)

    def stub_runs(self, runs: dict[str, ExtractionRun]) -> None:
        """让 run 仓储按 source_key 返回既有记录（增量判定用）。"""

        async def _get(
            project_id: int, type_: ExtractionType, source_key: str
        ) -> ExtractionRun | None:
            return runs.get(source_key)

        self.run_repo.get = AsyncMock(side_effect=_get)


def _upserted_runs(deps: _Deps) -> list[ExtractionRun]:
    """收集 run_repo.upsert 收到的全部记录。"""
    return [call.args[0] for call in deps.run_repo.upsert.await_args_list]


# ── 分发正确性 ──────────────────────────────────────────────────


async def test_index_true_indexes_entities_and_chunks() -> None:
    """index=true：index_batch 收到本次 created/updated 实体 + 章节 chapter_chunk。"""
    deps = _Deps(_project())
    deps.stub_chapter(_chapter(CH1, CONTENT_1))
    deps.character_service.extract = AsyncMock(return_value=_character_result(created=1, updated=1))
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1], index=True))

    assert result.indexed is True
    deps.vector_store.index_batch.assert_awaited_once()
    entities = deps.vector_store.index_batch.await_args.args[0]
    # 2 个角色实体 + 1 个 chapter_chunk 块（短文本单块）
    assert len(entities) == 3
    chars = [e for e in entities if e.entity_type is EntityType.CHARACTER]
    assert len(chars) == 2
    for e in chars:
        assert e.project_id == str(PID)
        assert e.content.startswith("姓名：")
        assert "性格：" in e.content and "背景：" in e.content and "目标：" in e.content
        assert e.metadata["project_id"] == str(PID)
        assert "name" in e.metadata
    chunks = [e for e in entities if e.entity_type is EntityType.CHAPTER_CHUNK]
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.id == f"{CH1}:0"
    assert chunk.content == CONTENT_1
    assert chunk.metadata["chapter_id"] == str(CH1)
    assert chunk.metadata["chapter_title"] == "章"
    assert chunk.metadata["chunk_index"] == 0
    assert chunk.metadata["project_id"] == str(PID)
    # run 行记录已索引
    runs = _upserted_runs(deps)
    assert runs[0].indexed is True


async def test_index_outline_warning() -> None:
    """outline + index=true → indexed=false + warning（不报错）。"""
    deps = _Deps(_project())
    deps.outline_service.generate = AsyncMock(return_value=_outline_result())
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.OUTLINE, prompt="双线", index=True))

    assert result.indexed is False
    assert "outline/timeline 类型不支持自动索引" in result.warnings
    deps.vector_store.index_batch.assert_not_awaited()


async def test_index_timeline_off_warning() -> None:
    """timeline 关闭 + index=true → indexed=false + warning。"""
    deps = _Deps(_project())
    deps.timeline_service.check_consistency = AsyncMock(return_value=_consistency_report())
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.TIMELINE, index=True))

    assert result.indexed is False
    assert "outline/timeline 类型不支持自动索引" in result.warnings
    deps.vector_store.index_batch.assert_not_awaited()


async def test_index_timeline_on_indexes_events() -> None:
    """timeline 开启 + index=true：提取事件索引为 timeline_event（metadata 含来源章）。"""
    deps = _Deps(_project(extra={"timeline_auto_extract": True}))
    deps.stub_chapter(_chapter(CH1, CONTENT_1))
    deps.timeline_extractor.extract = AsyncMock(return_value=_timeline_result(created=1, updated=1))
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.TIMELINE, chapter_ids=[CH1], index=True))

    assert result.indexed is True
    entities = deps.vector_store.index_batch.await_args.args[0]
    events = [e for e in entities if e.entity_type is EntityType.TIMELINE_EVENT]
    assert len(events) == 2
    for e in events:
        assert e.content.startswith("事件：")
        assert e.metadata["title"]
        assert e.metadata["chapter_id"] == str(CH1)  # source_chapter_id 投影
        assert e.metadata["project_id"] == str(PID)


async def test_index_without_vector_store_raises() -> None:
    """RAG 未装配（vector_store=None）+ index=true → RAGUnavailableError。"""
    deps = _Deps(_project())
    deps.character_service.extract = AsyncMock(return_value=_character_result())
    svc = deps.service(vector_store=None)

    with pytest.raises(RAGUnavailableError):
        await svc.extract(_req(ExtractionType.CHARACTER, text="文本", index=True))


# ── 结果归一 ────────────────────────────────────────────────────


async def test_detail_keeps_first_executed_source() -> None:
    """批量执行两章 → detail 保留首个执行源（CH1）的原始结果。"""
    deps = _Deps(_project())
    deps.chapter_repo.get_chapter = AsyncMock(side_effect=_chapter_by_id)
    first = _character_result(created=1)
    second = _character_result(created=3)
    deps.character_service.extract = AsyncMock(side_effect=[first, second])
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1, CH2]))

    assert result.detail == first.model_dump(mode="json")
    assert result.created == 4
    assert result.updated == 0


async def test_foreground_warnings_accumulate() -> None:
    """多源执行 → warnings 汇总全部源。"""
    deps = _Deps(_project())
    deps.chapter_repo.get_chapter = AsyncMock(side_effect=_chapter_by_id)
    deps.character_service.extract = AsyncMock(
        side_effect=[
            _character_result(warnings=["警告 A"]),
            _character_result(warnings=["警告 B"]),
        ]
    )
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1, CH2]))

    assert result.warnings == ["警告 A", "警告 B"]


# ── reindex 全量重建 ────────────────────────────────────────────


async def test_reindex_default_all_types() -> None:
    """reindex 缺省 entity_types → 全部 5 种实体类型拉档案并 index_batch。"""
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([_char("林晚")], 1))
    deps.world_repo.list = AsyncMock(return_value=([_setting("青云城")], 1))
    deps.foreshadowing_repo.list = AsyncMock(return_value=([_fs("铜镜的秘密")], 1))
    deps.timeline_repo.list_all = AsyncMock(return_value=[_event("林晚入宫")])
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([_chapter(CH1, CONTENT_1)], 1))
    svc = deps.service()

    result = await svc.reindex(PID)

    assert isinstance(result, ReindexResult)
    assert result.project_id == PID
    assert result.entity_types == list(EntityType)
    assert result.indexed == 5  # 1 角色 + 1 设定 + 1 伏笔 + 1 事件 + 1 章块
    assert result.warnings == []
    deps.character_repo.list.assert_awaited()
    deps.world_repo.list.assert_awaited()
    deps.foreshadowing_repo.list.assert_awaited()
    deps.timeline_repo.list_all.assert_awaited_once_with(PID.int)
    deps.chapter_repo.list_chapters.assert_awaited()
    # 收集全部 index_batch 入参，断言 5 种类型各 1 条
    indexed_types = [
        e.entity_type
        for call in deps.vector_store.index_batch.await_args_list
        for e in call.args[0]
    ]
    assert sorted(indexed_types, key=lambda t: t.value) == sorted(
        [
            EntityType.CHARACTER,
            EntityType.SETTING,
            EntityType.FORESHADOWING,
            EntityType.TIMELINE_EVENT,
            EntityType.CHAPTER_CHUNK,
        ],
        key=lambda t: t.value,
    )


async def test_reindex_pagination_loops() -> None:
    """reindex 分页循环（limit=100）直到拉完全部档案。"""
    deps = _Deps(_project())
    all_chars = [_char(f"角色{i}") for i in range(150)]
    deps.character_repo.list = AsyncMock(
        side_effect=lambda project_id, offset=0, limit=50, **kw: (
            all_chars[offset : offset + limit],
            len(all_chars),
        )
    )
    svc = deps.service()

    result = await svc.reindex(PID, entity_types=[EntityType.CHARACTER])

    assert result.indexed == 150
    offsets = [call.kwargs["offset"] for call in deps.character_repo.list.await_args_list]
    assert offsets == [0, 100]


async def test_reindex_filtered_types() -> None:
    """reindex 指定 entity_types → 只拉对应档案。"""
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([_char("林晚")], 1))
    svc = deps.service()

    result = await svc.reindex(PID, entity_types=[EntityType.CHARACTER])

    assert result.entity_types == [EntityType.CHARACTER]
    assert result.indexed == 1
    deps.character_repo.list.assert_awaited_once()
    deps.world_repo.list.assert_not_awaited()
    deps.timeline_repo.list_all.assert_not_awaited()


async def test_reindex_empty_project() -> None:
    """reindex 空项目 → indexed=0（正常路径）。"""
    deps = _Deps(_project())
    svc = deps.service()

    result = await svc.reindex(PID)

    assert result.indexed == 0
    assert result.entity_types == list(EntityType)


async def test_reindex_without_vector_store_raises() -> None:
    """RAG 未装配 + reindex → RAGUnavailableError。"""
    deps = _Deps(_project())
    svc = deps.service(vector_store=None)

    with pytest.raises(RAGUnavailableError):
        await svc.reindex(PID)


# ── retrieve ────────────────────────────────────────────────────
