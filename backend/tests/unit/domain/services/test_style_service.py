"""F16 风格检测服务编排单元测试 — Mock project_repo + chapter_repo + llm_analyzer + Mock 算法层.

覆盖 spec §5.1（模式总览/编排步骤 ①-⑥）/§7（边界与错误处理）/§8.1（构造注入）/
§9（服务编排测试场景）全部场景:
- 项目校验: project_repo.get → None → ProjectNotFoundError（404 语义）；项目校验先于输入校验
- 输入校验: text 与 chapter_ids 互斥 / 均缺 / text 空白 → StyleValidationError（422）
- 章节模式: 章节不存在 / 跨项目 / 内容超 50000 → 错误；单章 source 标记；多章按请求顺序
  合并（章间 "\\n\\n" 分隔）+「多章节合并分析」warning
- 手动模式: source="manual"、不读章节（Mock chapter_repo 未被调用断言）
- llm_analysis 三级判定（Q1=C，§2.8）: 请求显式 true/false / 缺省跟随项目配置
  extra["style_llm_analysis"] / 默认 false；llm_analysis=true 但分析器未装配 →
  StyleLLMUnavailableError
- warnings 组合 / 确定性快照断言（基础板块逐字段相等，llm_assessment=None）/
  失败传播（仓储异常透传，不产出部分报告）

设计假设（RED 阶段按 spec 口径记录，实现须满足）:
- 算法层（_style_analyzer 纯函数）在服务测试中整体 Mock（_analyze / _analyze_fingerprint /
  _analyze_ai_trace / _analyze_lexical）——编排测试隔离算法与 I/O，算法数值面由
  test_style_analyzer.py 单独覆盖（spec §9 分层；§5.7 伪代码中这些名字直接 import 进
  style_service 模块命名空间，patch 目标即 style_service._analyze 等）
- 错误类归属: ProjectNotFoundError 复用 F9 character_errors；ChapterNotFoundError /
  ChapterNotInProjectError 复用 F14 extraction_errors；StyleValidationError /
  StyleLLMUnavailableError 为 F16 新建 style_errors（spec §8）
- 章节内容上限 _MAX_CHAPTER_CHARS = 50000（spec §3.3/§7）; warnings 文案与顺序按
  spec §5.7 伪代码（多章 → 无完整句子 → 无有效词条）
- StyleLLMAnalyzer.analyze(project, text) 由服务层以关键字调用（§5.7）

依据: specs/f16-style-service/spec.md §5.1/§7/§8.1/§9。
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.models.style import (
    AITraceAssessment,
    LexicalAnalysis,
    StyleFingerprint,
    StyleLLMAssessment,
)
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError, ChapterNotInProjectError
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.style_errors import StyleLLMUnavailableError, StyleValidationError
from inkflow.domain.services.style_service import StyleService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OTHER_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000099")
CID_1 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000001")
CID_2 = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000002")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
DEFAULT_MODEL = "openai/gpt-4o"


def _project(*, style_llm_analysis: bool | None = None) -> Project:
    """构造测试项目（PID 所属；style_llm_analysis 注入 config.extra 可选）。"""
    extra: dict = {}
    if style_llm_analysis is not None:
        extra["style_llm_analysis"] = style_llm_analysis
    return Project(
        id=PID,
        name="测试项目",
        config=ProjectConfig(model=DEFAULT_MODEL, extra=extra),
        created_at=TS,
        updated_at=TS,
    )


def _chapter(cid: uuid.UUID, content: str, *, project_id: uuid.UUID = PID) -> Chapter:
    """构造测试章节实体（默认属于 PID）。"""
    return Chapter(
        id=cid,
        project_id=project_id,
        title=f"章节-{cid}",
        content=content,
        created_at=TS,
        updated_at=TS,
    )


def _assessment() -> StyleLLMAssessment:
    """构造 LLM 深度分析板块 Mock 返回值。"""
    return StyleLLMAssessment(
        llm_verdict="likely_ai",
        reasoning="句式整齐，词汇复用偏高。",
        model=DEFAULT_MODEL,
        generated_at=TS,
    )


@contextlib.contextmanager
def _patched_analyzer(*, sentence_count: int = 3, total_words: int = 10) -> MagicMock:
    """Mock 算法层四函数（§5.7 伪代码直接 import 进 style_service 命名空间）。

    stats 以 SimpleNamespace 提供 sentence_count / total_words（服务层 warnings
    组装只消费这两个字段，spec §5.7）；三板块返回默认模型实例。
    """
    stats = SimpleNamespace(sentence_count=sentence_count, total_words=total_words)
    with (
        patch("inkflow.domain.services.style_service._analyze", return_value=stats) as mock_analyze,
        patch(
            "inkflow.domain.services.style_service._analyze_fingerprint",
            return_value=StyleFingerprint(),
        ),
        patch(
            "inkflow.domain.services.style_service._analyze_ai_trace",
            return_value=AITraceAssessment(),
        ),
        patch(
            "inkflow.domain.services.style_service._analyze_lexical",
            return_value=LexicalAnalysis(),
        ),
    ):
        yield mock_analyze


class _Deps:
    """测试用依赖集合 — 全部 Mock，可逐项覆盖后装配 StyleService。"""

    def __init__(self) -> None:
        self.project_repo = MagicMock(spec=ProjectRepositoryProtocol)
        self.project_repo.get = AsyncMock()
        self.chapter_repo = MagicMock(spec=ChapterRepositoryProtocol)
        self.chapter_repo.get_chapter = AsyncMock()
        self.llm_analyzer = MagicMock()
        self.llm_analyzer.analyze = AsyncMock()

    def service(self, *, with_analyzer: bool = True) -> StyleService:
        """装配 StyleService（with_analyzer=False 模拟 LLM 分析器未装配）。"""
        return StyleService(
            project_repo=self.project_repo,
            chapter_repo=self.chapter_repo,
            llm_analyzer=self.llm_analyzer if with_analyzer else None,
        )


@pytest.fixture
def deps() -> _Deps:
    """返回一组全新 Mock 依赖。"""
    return _Deps()


class TestStyleService:
    (
        """服务编排测试 — 项目校验 / 输入校验 / 章节模式 / 手动模式"""
        """ / LLM 三级判定 / 快照 / 失败传播。"""
    )

    async def test_project_not_found_raises(self, deps: _Deps) -> None:
        """项目不存在（project_repo.get → None）→ ProjectNotFoundError（404 语义）。"""
        deps.project_repo.get.return_value = None
        service = deps.service()
        with pytest.raises(ProjectNotFoundError) as excinfo:
            await service.analyze(PID, text="林晚推开窗。")
        assert str(excinfo.value) == "项目不存在"
        deps.chapter_repo.get_chapter.assert_not_awaited()
        deps.llm_analyzer.analyze.assert_not_awaited()

    async def test_project_check_precedes_input_validation(self, deps: _Deps) -> None:
        """项目校验先于输入校验：项目为 None 且输入非法 → 仍抛 ProjectNotFoundError。"""
        deps.project_repo.get.return_value = None
        service = deps.service()
        with pytest.raises(ProjectNotFoundError):
            await service.analyze(PID, text="内容", chapter_ids=[CID_1])

    async def test_text_and_chapter_ids_mutually_exclusive(self, deps: _Deps) -> None:
        """text 与 chapter_ids 同时提供 → StyleValidationError「不能同时使用」（422）。"""
        deps.project_repo.get.return_value = _project()
        service = deps.service()
        with pytest.raises(StyleValidationError) as excinfo:
            await service.analyze(PID, text="内容", chapter_ids=[CID_1])
        assert str(excinfo.value) == "text 与 chapter_ids 不能同时使用"
        deps.chapter_repo.get_chapter.assert_not_awaited()

    async def test_neither_text_nor_chapter_ids(self, deps: _Deps) -> None:
        """text 与 chapter_ids 均未提供 → StyleValidationError「必须提供」（422）。"""
        deps.project_repo.get.return_value = _project()
        service = deps.service()
        with pytest.raises(StyleValidationError) as excinfo:
            await service.analyze(PID)
        assert str(excinfo.value) == "必须提供 text 或 chapter_ids"

    async def test_blank_text_rejected(self, deps: _Deps) -> None:
        """text 全空白 → StyleValidationError「文本不能为空」（422）。"""
        deps.project_repo.get.return_value = _project()
        service = deps.service()
        with pytest.raises(StyleValidationError) as excinfo:
            await service.analyze(PID, text="   \n\t ")
        assert str(excinfo.value) == "文本不能为空"

    async def test_chapter_not_found_raises(self, deps: _Deps) -> None:
        """章节不存在（get_chapter → None，含软删——F2 get 不含软删）→ ChapterNotFoundError。"""
        deps.project_repo.get.return_value = _project()
        deps.chapter_repo.get_chapter.return_value = None
        service = deps.service()
        with pytest.raises(ChapterNotFoundError) as excinfo:
            await service.analyze(PID, chapter_ids=[CID_1])
        assert str(excinfo.value) == "章节不存在"

    async def test_chapter_not_in_project_raises(self, deps: _Deps) -> None:
        """章节属于其他项目 → ChapterNotInProjectError（422「章节不属于该项目」）。"""
        deps.project_repo.get.return_value = _project()
        deps.chapter_repo.get_chapter.return_value = _chapter(CID_1, "内容", project_id=OTHER_PID)
        service = deps.service()
        with pytest.raises(ChapterNotInProjectError) as excinfo:
            await service.analyze(PID, chapter_ids=[CID_1])
        assert str(excinfo.value) == "章节不属于该项目"

    async def test_chapter_content_too_long(self, deps: _Deps) -> None:
        """章节内容超 50000 字符 → StyleValidationError「超过分析上限」（422）。"""
        deps.project_repo.get.return_value = _project()
        deps.chapter_repo.get_chapter.return_value = _chapter(CID_1, "长" * 50001)
        service = deps.service()
        with pytest.raises(StyleValidationError) as excinfo:
            await service.analyze(PID, chapter_ids=[CID_1])
        assert str(excinfo.value) == "章节内容超过分析上限（50000 字符）"

    async def test_single_chapter_source_and_content(self, deps: _Deps) -> None:
        """单章模式：source="chapter:<id>"、分析文本 = 章节内容、无 warnings。"""
        deps.project_repo.get.return_value = _project()
        deps.chapter_repo.get_chapter.return_value = _chapter(CID_1, "第一章内容。")
        service = deps.service()
        with _patched_analyzer() as mock_analyze:
            report = await service.analyze(PID, chapter_ids=[CID_1])
        assert report.project_id == PID
        assert report.source == f"chapter:{CID_1}"
        assert report.warnings == []
        assert report.llm_assessment is None
        mock_analyze.assert_called_once_with("第一章内容。")
        deps.chapter_repo.get_chapter.assert_awaited_once_with(CID_1.int)

    async def test_multi_chapter_merged_in_request_order(self, deps: _Deps) -> None:
        """多章模式：按请求顺序合并（章间 "\\n\\n"）、source="chapters:<ids>"、跨章 warning。"""
        deps.project_repo.get.return_value = _project()
        deps.chapter_repo.get_chapter.side_effect = [
            _chapter(CID_1, "第一章内容。"),
            _chapter(CID_2, "第二章内容。"),
        ]
        service = deps.service()
        with _patched_analyzer() as mock_analyze:
            report = await service.analyze(PID, chapter_ids=[CID_1, CID_2])
        assert report.source == f"chapters:{CID_1},{CID_2}"
        assert mock_analyze.call_args.args[0] == "第一章内容。\n\n第二章内容。"
        assert report.warnings == ["多章节合并分析（单章粒度分析归 Phase 2+）"]
        # 章节按请求顺序读取（仓储层 int id）
        assert deps.chapter_repo.get_chapter.await_args_list == [call(CID_1.int), call(CID_2.int)]

    async def test_manual_mode_source_and_no_chapter_reads(self, deps: _Deps) -> None:
        """手动模式：source="manual"、不读章节（Mock chapter_repo 未被调用断言）。"""
        deps.project_repo.get.return_value = _project()
        service = deps.service()
        with _patched_analyzer() as mock_analyze:
            report = await service.analyze(PID, text="手动文本内容。")
        assert report.project_id == PID
        assert report.source == "manual"
        assert report.llm_assessment is None
        mock_analyze.assert_called_once_with("手动文本内容。")
        deps.chapter_repo.get_chapter.assert_not_awaited()

    async def test_manual_text_is_stripped(self, deps: _Deps) -> None:
        """手动文本先 strip 再去空白（spec §5.7: stripped = text.strip()）。"""
        deps.project_repo.get.return_value = _project()
        service = deps.service()
        with _patched_analyzer() as mock_analyze:
            await service.analyze(PID, text="  手动文本内容。  ")
        mock_analyze.assert_called_once_with("手动文本内容。")

    async def test_llm_analysis_true_invokes_analyzer(self, deps: _Deps) -> None:
        """请求显式 llm_analysis=true → 调用 LLM 分析器并注入 llm_assessment 板块。"""
        project = _project()
        deps.project_repo.get.return_value = project
        assessment = _assessment()
        deps.llm_analyzer.analyze.return_value = assessment
        service = deps.service()
        with _patched_analyzer():
            report = await service.analyze(PID, text="手动文本内容。", llm_analysis=True)
        assert report.llm_assessment == assessment
        deps.llm_analyzer.analyze.assert_awaited_once_with(project=project, text="手动文本内容。")

    async def test_llm_analysis_false_skips_analyzer(self, deps: _Deps) -> None:
        """请求显式 llm_analysis=false → 不调用分析器（Mock 断言未调用），llm_assessment=None。"""
        deps.project_repo.get.return_value = _project()
        service = deps.service()
        with _patched_analyzer():
            report = await service.analyze(PID, text="手动文本内容。", llm_analysis=False)
        assert report.llm_assessment is None
        deps.llm_analyzer.analyze.assert_not_awaited()

    async def test_llm_analysis_none_follows_project_config(self, deps: _Deps) -> None:
        """缺省 None + 项目配置 extra["style_llm_analysis"]=true → 调用分析器。"""
        project = _project(style_llm_analysis=True)
        deps.project_repo.get.return_value = project
        assessment = _assessment()
        deps.llm_analyzer.analyze.return_value = assessment
        service = deps.service()
        with _patched_analyzer():
            report = await service.analyze(PID, text="手动文本内容。")
        assert report.llm_assessment == assessment
        deps.llm_analyzer.analyze.assert_awaited_once()

    async def test_llm_analysis_none_default_false_skips(self, deps: _Deps) -> None:
        """缺省 None + 无项目配置（默认 false）→ 不调用分析器，llm_assessment=None。"""
        deps.project_repo.get.return_value = _project()
        service = deps.service()
        with _patched_analyzer():
            report = await service.analyze(PID, text="手动文本内容。")
        assert report.llm_assessment is None
        deps.llm_analyzer.analyze.assert_not_awaited()

    async def test_llm_analysis_true_without_analyzer_raises(self, deps: _Deps) -> None:
        (
            """llm_analysis=true 但分析器未装配（构造传 None）"""
            """→ StyleLLMUnavailableError（500 语义）。"""
        )
        deps.project_repo.get.return_value = _project()
        service = deps.service(with_analyzer=False)
        with pytest.raises(StyleLLMUnavailableError) as excinfo:
            await service.analyze(PID, text="手动文本内容。", llm_analysis=True)
        assert str(excinfo.value) == "LLM 深度分析不可用"

    async def test_deterministic_snapshot_base_sections(self, deps: _Deps) -> None:
        """同一 Mock 输入两次 analyze → 报告基础板块逐字段相等（llm_assessment=None）。"""
        deps.project_repo.get.return_value = _project()
        deps.chapter_repo.get_chapter.return_value = _chapter(CID_1, "第一章内容。")
        service = deps.service()
        with _patched_analyzer():
            first = await service.analyze(PID, chapter_ids=[CID_1])
            second = await service.analyze(PID, chapter_ids=[CID_1])
        assert first.fingerprint == second.fingerprint
        assert first.ai_trace == second.ai_trace
        assert first.lexical == second.lexical
        assert first.source == second.source == f"chapter:{CID_1}"
        assert first.llm_assessment is None and second.llm_assessment is None
        # 除 generated_at 外全字段快照相等（确定性断言）
        assert first.model_dump(exclude={"generated_at"}) == second.model_dump(
            exclude={"generated_at"}
        )

    async def test_failure_propagation_from_chapter_repo(self, deps: _Deps) -> None:
        """章节仓储读取失败 → 异常透传（不产出部分报告，spec §5.1 要点 6）。"""
        deps.project_repo.get.return_value = _project()
        deps.chapter_repo.get_chapter.side_effect = RuntimeError("db down")
        service = deps.service()
        with pytest.raises(RuntimeError, match="db down"):
            await service.analyze(PID, chapter_ids=[CID_1])

    async def test_warnings_combination(self, deps: _Deps) -> None:
        """warnings 组合：多章 + 无完整句子 + 无有效词条 → 三条提示按 spec §5.7 顺序。"""
        deps.project_repo.get.return_value = _project()
        deps.chapter_repo.get_chapter.side_effect = [
            _chapter(CID_1, "第一章内容。"),
            _chapter(CID_2, "第二章内容。"),
        ]
        service = deps.service()
        with _patched_analyzer(sentence_count=0, total_words=0):
            report = await service.analyze(PID, chapter_ids=[CID_1, CID_2])
        assert report.warnings == [
            "多章节合并分析（单章粒度分析归 Phase 2+）",
            "未检测到完整句子（句尾符不足）——句子统计仅供参考",
            "文本无有效词条（仅标点/空白）——词汇统计为空",
        ]
