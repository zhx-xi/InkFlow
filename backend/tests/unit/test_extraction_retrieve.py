"""retrieve / list_runs / 防御与投影杂项 — Mock 各模块 Service + Repo + VectorStore。

覆盖: retrieve / list_runs / 结果归一 + 防御分支与投影杂项。

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
    ExtractionValidationError,
    RAGUnavailableError,
)
from inkflow.domain.ports.vector_store import EntityType, RetrievedEntity
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


async def test_retrieve_passthrough() -> None:
    """retrieve → 参数透传 vector_store（project_id 转字符串）。"""
    deps = _Deps(_project())
    retrieved = [
        RetrievedEntity(
            entity_id=str(uuid.uuid4()),
            entity_type=EntityType.FORESHADOWING,
            content="伏笔：铜镜",
            relevance_score=0.82,
            metadata={"project_id": str(PID)},
        )
    ]
    deps.vector_store.retrieve = AsyncMock(return_value=retrieved)
    svc = deps.service()

    items = await svc.retrieve(
        "铜镜", project_id=PID, entity_types=[EntityType.FORESHADOWING], top_k=5, min_score=0.3
    )

    deps.vector_store.retrieve.assert_awaited_once_with(
        "铜镜",
        project_id=str(PID),
        entity_types=[EntityType.FORESHADOWING],
        top_k=5,
        min_score=0.3,
    )
    assert items == retrieved


async def test_retrieve_without_vector_store_raises() -> None:
    """RAG 未装配 + retrieve → RAGUnavailableError。"""
    deps = _Deps(_project())
    svc = deps.service(vector_store=None)

    with pytest.raises(RAGUnavailableError):
        await svc.retrieve("铜镜", project_id=PID)


# ── list_runs ───────────────────────────────────────────────────


async def test_list_runs_passthrough() -> None:
    """list_runs → 透传 run_repo.list（project_id 转 int，分页参数透传）。"""
    deps = _Deps(_project())
    runs = [_run(str(CH1), _sha(CONTENT_1))]
    deps.run_repo.list = AsyncMock(return_value=(runs, 1))
    svc = deps.service()

    items, total = await svc.list_runs(PID, type=ExtractionType.CHARACTER, offset=10, limit=20)

    deps.run_repo.list.assert_awaited_once_with(
        PID.int, type=ExtractionType.CHARACTER, offset=10, limit=20
    )
    assert items == runs
    assert total == 1


# ═══════════════════════════════════════════════════════════════════════════
# Issue #104 Phase 3 覆盖率补齐：防御分支 / None 路径 / 未达投影 / reindex 缺口
# ═══════════════════════════════════════════════════════════════════════════


def test_to_int_id_int_passthrough() -> None:
    """_to_int_id 输入已是 int → 原样返回（UUID 分支已覆盖）。"""
    from inkflow.domain.services.extraction_service import _to_int_id

    assert _to_int_id(42) == 42


def test_project_timeline_event_without_chapter_anchor() -> None:
    """_project_timeline_event 无 source_chapter_id → metadata 不含 chapter_id。"""
    from inkflow.domain.services.extraction_service import _project_timeline_event

    entity = _project_timeline_event(_event("无锚点事件", chapter_id=None), str(PID))
    assert entity.entity_type is EntityType.TIMELINE_EVENT
    assert entity.metadata["title"] == "无锚点事件"
    assert "chapter_id" not in entity.metadata


async def test_unregistered_handler_raises() -> None:
    """类型注册表槽位为 None（防御）→ UnsupportedExtractionTypeError（422 语义）。"""
    from inkflow.domain.ports.extraction_errors import UnsupportedExtractionTypeError

    deps = _Deps(_project())
    deps.character_service.extract = AsyncMock()
    svc = deps.service()
    svc._handlers[ExtractionType.CHARACTER] = None  # 模拟槽位未注册

    with pytest.raises(UnsupportedExtractionTypeError):
        await svc.extract(_req(ExtractionType.CHARACTER, text="文本"))

    deps.character_service.extract.assert_not_awaited()


async def test_index_true_all_skipped_not_indexed() -> None:
    """index=true 但全源 skip（status=SKIPPED）→ 不索引、indexed 保持 False（407→423 分支）。"""
    deps = _Deps(_project())
    deps.stub_runs({"manual": _run("manual", _sha("文本"))})
    deps.character_service.extract = AsyncMock(return_value=_character_result())
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, text="文本", index=True))

    assert result.status is ExtractionStatus.SKIPPED
    assert result.indexed is False
    deps.vector_store.index_batch.assert_not_awaited()
    deps.character_service.extract.assert_not_awaited()


async def test_index_true_no_entities_still_indexed() -> None:
    """index=true 成功但产物为空 → 不调 index_batch，indexed 仍置 True（411→413 分支）。"""
    deps = _Deps(_project())
    deps.character_service.extract = AsyncMock(return_value=_character_result(created=0, updated=0))
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, text="无实体文本", index=True))

    assert result.status is ExtractionStatus.SUCCESS
    assert result.indexed is True
    deps.vector_store.index_batch.assert_not_awaited()


async def test_timeline_on_missing_source_raises() -> None:
    """timeline 开启但 text/chapter_ids 均缺 → 422「timeline 类型必须提供 text 或 chapter_ids」。"""
    deps = _Deps(_project())
    svc = deps.service()

    with pytest.raises(ExtractionValidationError, match="timeline 类型必须提供"):
        await svc.extract(_req(ExtractionType.TIMELINE, auto_extract=True))

    deps.timeline_extractor.extract.assert_not_awaited()


async def test_timeline_dispatch_none_result_defensive() -> None:
    """check_consistency 返回 None（防御）→ 归一为空 _Normalized，不崩溃。"""
    deps = _Deps(_project())
    deps.timeline_service.check_consistency = AsyncMock(return_value=None)
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.TIMELINE))

    assert result.status is ExtractionStatus.SUCCESS
    assert result.created == 0
    assert result.updated == 0
    assert result.model is None
    assert result.detail == {}


async def test_dispatch_unknown_type_raises() -> None:
    """_dispatch 直接分发未注册类型（绕过 handler 查表）→ UnsupportedExtractionTypeError。"""
    from inkflow.domain.ports.extraction_errors import UnsupportedExtractionTypeError
    from inkflow.domain.services.extraction_service import _Source

    deps = _Deps(_project())
    svc = deps.service()
    # model_construct 跳过 Pydantic 枚举校验 → type 为非法字符串
    req = ExtractionRequest.model_construct(project_id=PID, type="bogus", text="x")
    source = _Source(key="manual", label="manual", hash="h", skip=False, text="x")

    with pytest.raises(UnsupportedExtractionTypeError):
        await svc._dispatch(req, source, _project())


async def test_timeline_handler_auto_on_without_chapter_anchor_raises() -> None:
    """_dispatch 直达：timeline 开启但源无 chapter_id 锚点 → 422（709 防御分支）。"""
    from inkflow.domain.services.extraction_service import _Source

    deps = _Deps(_project())
    svc = deps.service()
    req = _req(ExtractionType.TIMELINE, auto_extract=True)
    source = _Source(key="manual", label="manual", hash="h", skip=False, text="x")

    with pytest.raises(ExtractionValidationError, match="章节模式"):
        await svc._dispatch(req, source, _project())

    deps.timeline_extractor.extract.assert_not_awaited()


async def test_index_setting_entities_projected() -> None:
    """index=true + SETTING → 世界观条目投影为 SETTING 实体（770 分支）。"""
    deps = _Deps(_project())
    deps.world_service.extract = AsyncMock(return_value=_world_result(created=1, updated=1))
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.SETTING, text="设定文本", index=True))

    assert result.indexed is True
    entities = deps.vector_store.index_batch.await_args.args[0]
    settings = [e for e in entities if e.entity_type is EntityType.SETTING]
    assert len(settings) == 2
    for e in settings:
        assert e.content.startswith("名称：")
        assert "分类：" in e.content and "内容：" in e.content
        assert e.metadata["project_id"] == str(PID)


async def test_index_foreshadowing_entities_projected() -> None:
    """index=true + FORESHADOWING → 伏笔投影为 FORESHADOWING 实体（776 分支）。"""
    deps = _Deps(_project())
    deps.foreshadowing_extractor.extract = AsyncMock(return_value=_fs_result(created=1))
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.FORESHADOWING, text="伏笔文本", index=True))

    assert result.indexed is True
    entities = deps.vector_store.index_batch.await_args.args[0]
    foreshadowings = [e for e in entities if e.entity_type is EntityType.FORESHADOWING]
    assert len(foreshadowings) == 1
    assert foreshadowings[0].content.startswith("伏笔：")
    assert foreshadowings[0].metadata["status"] == ForeshadowingStatus.OPEN.value


async def test_index_manual_source_skips_chunk_projection() -> None:
    """index=true 手动模式（源无 chapter_id）→ 不投影 chapter_chunk（785→760 False 分支）。"""
    deps = _Deps(_project())
    deps.character_service.extract = AsyncMock(return_value=_character_result(created=1))
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, text="手动文本", index=True))

    assert result.indexed is True
    entities = deps.vector_store.index_batch.await_args.args[0]
    assert all(e.entity_type is EntityType.CHARACTER for e in entities)
    assert not any(e.entity_type is EntityType.CHAPTER_CHUNK for e in entities)


async def test_reindex_missing_repos_warns_and_skips() -> None:
    """reindex 未配置档案仓储 → 对应类型跳过 + warning（820/826/832/838 分支）。"""
    deps = _Deps(_project())
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([_chapter(CH1, CONTENT_1)], 1))
    svc = deps.service()
    svc._character_repo = None
    svc._world_repo = None
    svc._foreshadowing_repo = None
    svc._timeline_repo = None

    result = await svc.reindex(PID)

    assert result.indexed == 1  # 仅 chapter_chunk 可索引
    skipped = [w for w in result.warnings if "未配置仓储" in w]
    assert len(skipped) == 4
    assert any("character" in w for w in skipped)
    assert any("setting" in w for w in skipped)
    assert any("foreshadowing" in w for w in skipped)
    assert any("timeline_event" in w for w in skipped)
