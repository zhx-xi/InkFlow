"""分发正确性 + 增量判定 + batch/resume/outline 细节 — Mock 各模块 Service + Repo + VectorStore。

覆盖: 分发正确性 / 项目校验 / 增量判定（skip/force/手动/批量/断点续跑）/ outline 冲突透传。

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
    CharacterExtractRequest,
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
    ForeshadowingExtractRequest,
    ForeshadowingStatus,
)
from inkflow.domain.models.outline import (
    OutlineGenerateRequest,
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
    WorldExtractRequest,
    WorldSetting,
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import (
    ChapterNotFoundError,
    ChapterNotInProjectError,
    ExtractionValidationError,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.outline_errors import OutlineNameConflictError
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


def _project(*, extra: dict[str, Any] | None = None, model: str | None = DEFAULT_MODEL) -> Project:
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

    def service(
        self, *, vector_store: Any = _NO_VECTOR, llm_default_model: str | None = None
    ) -> ExtractionService:
        """装配门面；vector_store 传 None 模拟 RAG 未装配。"""
        vs = self.vector_store if vector_store is _NO_VECTOR else vector_store
        extra_kwargs: dict[str, Any] = {}
        if llm_default_model is not None:
            extra_kwargs["llm_default_model"] = llm_default_model
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
            **extra_kwargs,
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


async def test_character_text_dispatches_to_character_service() -> None:
    """手动文本 → CharacterService.extract（text/model 透传）+ 结果归一 + run 落库。"""
    deps = _Deps(_project())
    deps.character_service.extract = AsyncMock(return_value=_character_result(created=2, updated=1))
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, text="文本", model=CUSTOM_MODEL))

    deps.character_service.extract.assert_awaited_once()
    req = deps.character_service.extract.await_args.args[0]
    assert isinstance(req, CharacterExtractRequest)
    assert req.project_id == PID
    assert req.text == "文本"
    assert req.model == CUSTOM_MODEL
    assert result.status is ExtractionStatus.SUCCESS
    assert result.processed_sources == 1
    assert result.skipped_sources == 0
    assert result.created == 2
    assert result.updated == 1
    assert result.model == DEFAULT_MODEL
    assert result.indexed is False
    runs = _upserted_runs(deps)
    assert len(runs) == 1
    assert runs[0].source_key == "manual"
    assert runs[0].content_hash == _sha("文本")
    assert runs[0].status is ExtractionStatus.SUCCESS
    assert runs[0].created_count == 2
    assert runs[0].updated_count == 1
    assert runs[0].model == DEFAULT_MODEL


async def test_setting_text_dispatches_to_world_service() -> None:
    """手动文本 → WorldService.extract（参数透传）。"""
    deps = _Deps(_project())
    deps.world_service.extract = AsyncMock(return_value=_world_result(created=1, updated=1))
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.SETTING, text="青云城坐落于群山之间"))

    deps.world_service.extract.assert_awaited_once()
    req = deps.world_service.extract.await_args.args[0]
    assert isinstance(req, WorldExtractRequest)
    assert req.project_id == PID
    assert req.text == "青云城坐落于群山之间"
    assert result.created == 1
    assert result.updated == 1


async def test_outline_dispatches_with_prompt_num_chapters_save() -> None:
    """OUTLINE → OutlineService.generate（prompt/num_chapters/save/model 透传），每次执行。"""
    deps = _Deps(_project())
    deps.outline_service.generate = AsyncMock(return_value=_outline_result(saved=False))
    svc = deps.service()

    result = await svc.extract(
        _req(
            ExtractionType.OUTLINE,
            prompt="复仇与救赎双线并进",
            num_chapters=30,
            save=False,
            model=CUSTOM_MODEL,
        )
    )

    deps.outline_service.generate.assert_awaited_once()
    req = deps.outline_service.generate.await_args.args[0]
    assert isinstance(req, OutlineGenerateRequest)
    assert req.project_id == PID
    assert req.prompt == "复仇与救赎双线并进"
    assert req.num_chapters == 30
    assert req.save is False
    assert req.model == CUSTOM_MODEL
    # 预览模式: created=0；每次执行（无增量 skip）
    assert result.created == 0
    assert result.processed_sources == 1
    runs = _upserted_runs(deps)
    assert runs[0].source_key == "full"
    assert runs[0].status is ExtractionStatus.SUCCESS


async def test_outline_saved_created_counts_one() -> None:
    """OUTLINE save=true 且新建 → created=1（§5.3 口径）。"""
    deps = _Deps(_project())
    deps.outline_service.generate = AsyncMock(return_value=_outline_result(saved=True))
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.OUTLINE, prompt="双线"))

    assert result.created == 1
    assert result.updated == 0


async def test_foreshadowing_dispatches_to_extractor() -> None:
    """FORESHADOWING → ForeshadowingExtractor.extract（default_model=项目模型透传）。"""
    deps = _Deps(_project())
    deps.foreshadowing_extractor.extract = AsyncMock(return_value=_fs_result(created=2, updated=1))
    svc = deps.service()

    result = await svc.extract(
        _req(ExtractionType.FORESHADOWING, text="铜镜在烛光下泛着微光", model=CUSTOM_MODEL)
    )

    deps.foreshadowing_extractor.extract.assert_awaited_once()
    req, kwargs = (
        deps.foreshadowing_extractor.extract.await_args.args[0],
        (deps.foreshadowing_extractor.extract.await_args.kwargs),
    )
    assert isinstance(req, ForeshadowingExtractRequest)
    assert req.project_id == PID
    assert req.text == "铜镜在烛光下泛着微光"
    assert req.model == CUSTOM_MODEL
    assert kwargs["default_model"] == DEFAULT_MODEL
    assert result.created == 2
    assert result.updated == 1


async def test_foreshadowing_project_model_none_falls_back_to_llm_default_model() -> None:
    """#520 D1=C：项目 model=None → foreshadowing extractor 收到注入的全局默认模型。"""
    deps = _Deps(_project(model=None))
    deps.foreshadowing_extractor.extract = AsyncMock(return_value=_fs_result(created=1))
    fallback = "deepseek/deepseek-v4-flash"
    svc = deps.service(llm_default_model=fallback)

    result = await svc.extract(_req(ExtractionType.FORESHADOWING, text="铜镜在烛光下泛着微光"))

    deps.foreshadowing_extractor.extract.assert_awaited_once()
    kwargs = deps.foreshadowing_extractor.extract.await_args.kwargs
    assert kwargs["default_model"] == fallback
    assert result.created == 1


async def test_character_chapter_mode_passes_chapter_text() -> None:
    """章节模式 → 读章节内容后按章透传 text 给 CharacterService.extract。"""
    deps = _Deps(_project())
    deps.stub_chapter(_chapter(CH1, CONTENT_1))
    deps.character_service.extract = AsyncMock(return_value=_character_result())
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1]))

    deps.chapter_repo.get_chapter.assert_awaited_once_with(CH1.int)
    req = deps.character_service.extract.await_args.args[0]
    assert req.text == CONTENT_1
    assert result.processed_sources == 1
    runs = _upserted_runs(deps)
    assert runs[0].source_key == str(CH1)
    assert runs[0].content_hash == _sha(CONTENT_1)


# ── 项目校验 ────────────────────────────────────────────────────


async def test_project_not_found_raises() -> None:
    """project_repo.get → None → ProjectNotFoundError（所有类型统一，handler 不调用）。"""
    deps = _Deps(project=None)
    svc = deps.service()

    with pytest.raises(ProjectNotFoundError):
        await svc.extract(_req(ExtractionType.CHARACTER, text="文本"))

    deps.character_service.extract.assert_not_awaited()


# ── 增量判定 ────────────────────────────────────────────────────


async def test_same_hash_skips_without_calling_handler() -> None:
    """章节 hash 相同 + not force → skip（零 LLM 调用，首个源落 skipped run）。"""
    deps = _Deps(_project())
    deps.stub_chapter(_chapter(CH1, CONTENT_1))
    deps.stub_runs({str(CH1): _run(str(CH1), _sha(CONTENT_1))})
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1]))

    assert result.status is ExtractionStatus.SKIPPED
    assert result.processed_sources == 0
    assert result.skipped_sources == 1
    assert result.skipped_reason == f"内容未变更（源: chapter {CH1}）"
    assert result.created == 0
    assert result.updated == 0
    deps.character_service.extract.assert_not_awaited()  # Mock handler 未被调用
    runs = _upserted_runs(deps)
    assert len(runs) == 1
    assert runs[0].source_key == str(CH1)
    assert runs[0].status is ExtractionStatus.SKIPPED


async def test_different_hash_executes() -> None:
    """章节 hash 不同 → 执行。"""
    deps = _Deps(_project())
    deps.stub_chapter(_chapter(CH1, CONTENT_1))
    deps.stub_runs({str(CH1): _run(str(CH1), _sha("旧内容"))})
    deps.character_service.extract = AsyncMock(return_value=_character_result())
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1]))

    deps.character_service.extract.assert_awaited_once()
    assert result.status is ExtractionStatus.SUCCESS
    assert result.processed_sources == 1
    assert result.skipped_sources == 0


async def test_no_run_executes() -> None:
    """无 run 行 → 执行（首次提取）。"""
    deps = _Deps(_project())
    deps.stub_chapter(_chapter(CH1, CONTENT_1))
    deps.character_service.extract = AsyncMock(return_value=_character_result())
    svc = deps.service()

    await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1]))

    deps.character_service.extract.assert_awaited_once()


async def test_force_true_executes_despite_same_hash() -> None:
    """force=true → 忽略相同 hash 强制执行。"""
    deps = _Deps(_project())
    deps.stub_chapter(_chapter(CH1, CONTENT_1))
    deps.stub_runs({str(CH1): _run(str(CH1), _sha(CONTENT_1))})
    deps.character_service.extract = AsyncMock(return_value=_character_result())
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1], force=True))

    deps.character_service.extract.assert_awaited_once()
    assert result.status is ExtractionStatus.SUCCESS
    assert result.processed_sources == 1


# ── 手动模式 ────────────────────────────────────────────────────


async def test_manual_same_text_skips() -> None:
    """手动模式 source_key=manual：同文本重复提交 → skip。"""
    deps = _Deps(_project())
    deps.character_service.extract = AsyncMock(return_value=_character_result())
    svc = deps.service()
    request = _req(ExtractionType.CHARACTER, text="同一段文本")

    first = await svc.extract(request)
    assert first.status is ExtractionStatus.SUCCESS

    deps.stub_runs({"manual": _run("manual", _sha("同一段文本"))})
    deps.character_service.extract.reset_mock()
    second = await svc.extract(request)

    assert second.status is ExtractionStatus.SKIPPED
    assert second.skipped_sources == 1
    assert second.skipped_reason == "内容未变更（源: manual）"
    deps.character_service.extract.assert_not_awaited()


async def test_manual_different_text_executes() -> None:
    """手动模式：不同文本 → 执行。"""
    deps = _Deps(_project())
    deps.stub_runs({"manual": _run("manual", _sha("旧文本"))})
    deps.character_service.extract = AsyncMock(return_value=_character_result())
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, text="新文本"))

    deps.character_service.extract.assert_awaited_once()
    assert result.status is ExtractionStatus.SUCCESS


# ── 批量章节 ────────────────────────────────────────────────────


async def test_batch_partial_skip_counts() -> None:
    """批量章节：部分 skip 部分执行 → success + 计数正确 + detail 保留首个执行源。"""
    deps = _Deps(_project())
    deps.chapter_repo.get_chapter = AsyncMock(side_effect=_chapter_by_id)
    deps.stub_runs({str(CH1): _run(str(CH1), _sha(CONTENT_1))})
    executed = _character_result(created=2, updated=1, warnings=["跳过非法条目"])
    deps.character_service.extract = AsyncMock(return_value=executed)
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1, CH2]))

    assert result.status is ExtractionStatus.SUCCESS
    assert result.processed_sources == 1
    assert result.skipped_sources == 1
    assert result.created == 2
    assert result.updated == 1
    assert result.warnings == ["跳过非法条目"]
    assert result.detail == executed.model_dump(mode="json")
    runs = _upserted_runs(deps)
    assert [r.source_key for r in runs] == [str(CH2)]  # 仅执行源落 run
    assert runs[0].content_hash == _sha(CONTENT_2)


async def test_batch_chapter_not_found_raises() -> None:
    """章节不存在（含软删）→ ChapterNotFoundError。"""
    deps = _Deps(_project())
    deps.stub_chapter(None)
    svc = deps.service()

    with pytest.raises(ChapterNotFoundError):
        await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1]))

    deps.character_service.extract.assert_not_awaited()


async def test_batch_cross_project_chapter_raises() -> None:
    """跨项目章节 → ChapterNotInProjectError。"""
    deps = _Deps(_project())
    deps.stub_chapter(_chapter(CH1, CONTENT_1, project_id=OTHER_PID))
    svc = deps.service()

    with pytest.raises(ChapterNotInProjectError):
        await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1]))

    deps.character_service.extract.assert_not_awaited()


async def test_batch_chapter_too_long_raises() -> None:
    """章节内容超 50000 字符 → ExtractionValidationError（422 语义）。"""
    deps = _Deps(_project())
    deps.stub_chapter(_chapter(CH1, "长" * 50001))
    svc = deps.service()

    with pytest.raises(ExtractionValidationError, match="50000"):
        await svc.extract(_req(ExtractionType.CHARACTER, chapter_ids=[CH1]))


# ── 断点续跑（核心）─────────────────────────────────────────────


async def test_resume_after_mid_batch_failure() -> None:
    """第 2 章失败 → 抛异常且第 1 章 run 已落库；重跑 → 第 1 章 skip、第 2 章执行。"""
    deps = _Deps(_project())
    deps.chapter_repo.get_chapter = AsyncMock(side_effect=_chapter_by_id)
    runs: dict[str, ExtractionRun] = {}
    deps.stub_runs(runs)
    deps.character_service.extract = AsyncMock(
        side_effect=[_character_result(created=1), LLMRequestError("LLM 调用失败")]
    )
    svc = deps.service()
    request = _req(ExtractionType.CHARACTER, chapter_ids=[CH1, CH2])

    # 第一次：第 2 章失败 → 门面抛异常；第 1 章 run 已 upsert
    with pytest.raises(LLMRequestError):
        await svc.extract(request)
    runs_after_failure = _upserted_runs(deps)
    assert [r.source_key for r in runs_after_failure] == [str(CH1)]
    assert runs_after_failure[0].status is ExtractionStatus.SUCCESS
    assert runs_after_failure[0].content_hash == _sha(CONTENT_1)

    # 模拟持久化后重跑：第 1 章 hash 相同 → skip，第 2 章执行
    runs[str(CH1)] = runs_after_failure[0]
    deps.character_service.extract.reset_mock()
    deps.character_service.extract = AsyncMock(return_value=_character_result(created=1))
    result = await svc.extract(request)

    assert result.status is ExtractionStatus.SUCCESS
    assert result.processed_sources == 1
    assert result.skipped_sources == 1
    calls = deps.character_service.extract.await_args_list
    assert len(calls) == 1
    assert calls[0].args[0].text == CONTENT_2  # 只处理失败章


# ── outline 语义 ────────────────────────────────────────────────


async def test_outline_always_executes_with_existing_run() -> None:
    """OUTLINE 每次执行：即使存在 full run 也重新生成。"""
    deps = _Deps(_project())
    deps.stub_runs({"full": _run("full", _sha(""), type_=ExtractionType.OUTLINE)})
    deps.outline_service.generate = AsyncMock(return_value=_outline_result())
    svc = deps.service()

    result = await svc.extract(_req(ExtractionType.OUTLINE, prompt="双线"))

    deps.outline_service.generate.assert_awaited_once()
    assert result.status is ExtractionStatus.SUCCESS


async def test_outline_name_conflict_passthrough() -> None:
    """OUTLINE 同名冲突 → 透传 F11 OutlineNameConflictError。"""
    deps = _Deps(_project())
    deps.outline_service.generate = AsyncMock(side_effect=OutlineNameConflictError())
    svc = deps.service()

    with pytest.raises(OutlineNameConflictError):
        await svc.extract(_req(ExtractionType.OUTLINE, prompt="双线"))


async def test_outline_with_text_raises() -> None:
    """OUTLINE 携带 text → 422（类型不匹配字段显式报错）。"""
    deps = _Deps(_project())
    svc = deps.service()

    with pytest.raises(ExtractionValidationError, match="outline 类型不支持"):
        await svc.extract(_req(ExtractionType.OUTLINE, text="文本"))


async def test_character_missing_source_raises() -> None:
    """character 无 text 且无 chapter_ids → 422。"""
    deps = _Deps(_project())
    svc = deps.service()

    with pytest.raises(ExtractionValidationError, match="必须提供 text 或 chapter_ids"):
        await svc.extract(_req(ExtractionType.CHARACTER))


# ── TIMELINE 双语义 ─────────────────────────────────────────────
