"""F14 统一提取 API 测试 — Mock ExtractionService（M7 RED→GREEN）。

测试范围 (spec §9 API 测试 + §3.4 异常映射表):
- 4 端点成功路径（extract 全字段透传 / runs 分页 / reindex 缺省全部 /
  retrieve 参数校验与透传；extract STYLE 成功路径——F16 已落地，
  200 + ExtractionResult 信封含 detail=StyleReport）
- 404 全路径（项目不存在、无效 UUID → 404）
- 422 全路径（text+chapter_ids 互斥、无效 type、
  top_k/min_score 越界、空白 query）
- 500 透传（LLM 调用失败 / 管线解析失败 / RAG 不可用 / run 记录读写失败）
- 信封序列化（ExtractionResult / ExtractionRun / ReindexResult /
  RetrievedEntity 的 JSON 形态，ExtractionResult.model_dump(mode="json")）

策略: @patch("inkflow.api.routers.extractions.get_extraction_service")
整体替换 Service 获取函数（router 模块级本地引用），每个被路由 await 的
服务方法显式赋 AsyncMock —— 未赋值的同步 MagicMock 子 mock 被 await 会
返回 coroutine 导致 500（F4 4.1 实测陷阱）。

依据: specs/f14-extraction-service/spec.md §3 + §7 + §9。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.extraction import (
    ExtractionResult,
    ExtractionRun,
    ExtractionStatus,
    ExtractionType,
    ReindexResult,
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import (
    ChapterNotFoundError,
    ChapterNotInProjectError,
    ExtractionRunError,
    ExtractionValidationError,
    RAGUnavailableError,
    UnsupportedExtractionTypeError,
)
from inkflow.domain.ports.foreshadowing_errors import ForeshadowingExtractionError
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.vector_store import EntityType, RetrievedEntity

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CH1 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000011")
CH2 = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000012")
TS = datetime(2026, 8, 2, 10, 0, 0, tzinfo=UTC)
TEXT = "第一章内容：林晚走进青云城，风尘仆仆。"


def _result(**overrides: object) -> ExtractionResult:
    """构造测试用统一提取结果信封（默认 character 成功态）。"""
    kwargs: dict[str, object] = {
        "type": ExtractionType.CHARACTER,
        "status": ExtractionStatus.SUCCESS,
        "skipped_reason": None,
        "processed_sources": 1,
        "skipped_sources": 0,
        "created": 2,
        "updated": 1,
        "warnings": [],
        "model": "openai/gpt-4o",
        "indexed": False,
        "detail": {"created": [{"id": "c1", "name": "林晚"}], "updated": []},
    }
    kwargs.update(overrides)
    return ExtractionResult(**kwargs)  # type: ignore[arg-type]


def _run(run_id: int = 1, **overrides: object) -> ExtractionRun:
    """构造测试用 run 记录（固定时间戳，便于断言 JSON 序列化）。"""
    kwargs: dict[str, object] = {
        "id": run_id,
        "project_id": PID,
        "type": ExtractionType.CHARACTER,
        "source_key": "manual",
        "content_hash": "a1b2c3d4e5f6",
        "status": ExtractionStatus.SUCCESS,
        "created_count": 2,
        "updated_count": 1,
        "warnings_json": "[]",
        "error": None,
        "model": "openai/gpt-4o",
        "indexed": True,
        "run_at": TS,
    }
    kwargs.update(overrides)
    return ExtractionRun(**kwargs)  # type: ignore[arg-type]


def _reindex(**overrides: object) -> ReindexResult:
    """构造测试用全量重建索引结果。"""
    kwargs: dict[str, object] = {
        "project_id": PID,
        "entity_types": [EntityType.CHARACTER, EntityType.SETTING],
        "indexed": 87,
        "warnings": [],
    }
    kwargs.update(overrides)
    return ReindexResult(**kwargs)  # type: ignore[arg-type]


def _retrieved(**overrides: object) -> RetrievedEntity:
    """构造测试用检索结果实体。"""
    kwargs: dict[str, object] = {
        "entity_id": "9b1c2d3e-0000-4000-8000-000000000021",
        "entity_type": EntityType.FORESHADOWING,
        "content": "伏笔：林晚的身世。林晚右肩的胎记与女主母亲的信物相同……",
        "relevance_score": 0.82,
        "metadata": {"project_id": str(PID), "name": "林晚的身世", "status": "open"},
    }
    kwargs.update(overrides)
    return RetrievedEntity(**kwargs)  # type: ignore[arg-type]


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock ExtractionService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestExtractAPI:
    """POST /api/v1/extract — 统一提取入口（扁平路径）。"""

    # ── 成功路径 ────────────────────────────────────────────

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_character_manual_success(self, mock_get_svc: MagicMock) -> None:
        """手动文本提取角色：全字段透传 + ExtractionResult 信封序列化。"""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(return_value=_result())

        response = client.post(
            "/api/v1/extract",
            json={
                "project_id": str(PID),
                "type": "character",
                "text": TEXT,
                "model": "anthropic/claude-3.5-sonnet",
                "index": True,
                "force": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "character"
        assert data["status"] == "success"
        assert data["skipped_reason"] is None
        assert data["processed_sources"] == 1
        assert data["skipped_sources"] == 0
        assert data["created"] == 2
        assert data["updated"] == 1
        assert data["warnings"] == []
        assert data["model"] == "openai/gpt-4o"
        assert data["indexed"] is False
        assert data["detail"] == {"created": [{"id": "c1", "name": "林晚"}], "updated": []}
        svc.extract.assert_awaited_once()
        args, _ = svc.extract.await_args
        req = args[0]
        assert req.project_id == PID
        assert req.type is ExtractionType.CHARACTER
        assert req.text == TEXT
        assert req.chapter_ids is None
        assert req.model == "anthropic/claude-3.5-sonnet"
        assert req.index is True
        assert req.force is True

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_chapter_mode_success(self, mock_get_svc: MagicMock) -> None:
        """章节模式提取：chapter_ids 透传为 UUID 列表。"""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(return_value=_result(type=ExtractionType.SETTING))

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "setting", "chapter_ids": [str(CH1), str(CH2)]},
        )
        assert response.status_code == 200
        assert response.json()["type"] == "setting"
        svc.extract.assert_awaited_once()
        args, _ = svc.extract.await_args
        req = args[0]
        assert req.chapter_ids == [CH1, CH2]
        assert req.text is None

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_outline_params_passthrough(self, mock_get_svc: MagicMock) -> None:
        """大纲生成：prompt/num_chapters/save 透传。"""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(return_value=_result(type=ExtractionType.OUTLINE, created=1))

        response = client.post(
            "/api/v1/extract",
            json={
                "project_id": str(PID),
                "type": "outline",
                "prompt": "复仇与救赎双线并进",
                "num_chapters": 30,
                "save": False,
            },
        )
        assert response.status_code == 200
        svc.extract.assert_awaited_once()
        args, _ = svc.extract.await_args
        req = args[0]
        assert req.prompt == "复仇与救赎双线并进"
        assert req.num_chapters == 30
        assert req.save is False

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_timeline_auto_extract_passthrough(self, mock_get_svc: MagicMock) -> None:
        """时间线提取：auto_extract 显式覆盖值透传。"""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(return_value=_result(type=ExtractionType.TIMELINE))

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "timeline", "chapter_ids": [str(CH1)]},
        )
        assert response.status_code == 200
        svc.extract.assert_awaited_once()
        args, _ = svc.extract.await_args
        req = args[0]
        assert req.auto_extract is None  # 缺省 None = 跟随项目配置
        assert req.include_flashbacks is True

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_skipped_envelope(self, mock_get_svc: MagicMock) -> None:
        """增量 skip：status=skipped 信封序列化（skipped_reason/model=null/detail={}）。"""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(
            return_value=_result(
                status=ExtractionStatus.SKIPPED,
                skipped_reason="内容未变更（源: chapter 7a4f2c91-0000-4000-8000-000000000011）",
                processed_sources=0,
                skipped_sources=1,
                created=0,
                updated=0,
                model=None,
                indexed=False,
                detail={},
            )
        )

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "character", "chapter_ids": [str(CH1)]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"
        assert data["skipped_reason"] == (
            "内容未变更（源: chapter 7a4f2c91-0000-4000-8000-000000000011）"
        )
        assert data["processed_sources"] == 0
        assert data["skipped_sources"] == 1
        assert data["model"] is None
        assert data["detail"] == {}

    # ── 404 ─────────────────────────────────────────────────

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """项目不存在（门面统一校验）返回 404「项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "character", "text": TEXT},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_extract_invalid_project_uuid_422(self) -> None:
        """body 内 project_id 非 UUID 格式 → Pydantic 422（spec §3.4）。"""
        response = client.post(
            "/api/v1/extract",
            json={"project_id": "not-a-uuid", "type": "character", "text": TEXT},
        )
        assert response.status_code == 422

    def test_extract_invalid_chapter_uuid_422(self) -> None:
        """chapter_ids 内非法 UUID → Pydantic 422（spec §3.4）。"""
        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "character", "chapter_ids": ["not-a-uuid"]},
        )
        assert response.status_code == 422

    # ── 422 业务校验 / 类型未实现 ───────────────────────────

    def test_extract_text_chapter_ids_conflict_422(self) -> None:
        """text 与 chapter_ids 互斥（spec §3.2 逐字文案，Pydantic model_validator）。"""
        response = client.post(
            "/api/v1/extract",
            json={
                "project_id": str(PID),
                "type": "character",
                "text": TEXT,
                "chapter_ids": [str(CH1)],
            },
        )
        assert response.status_code == 422
        assert "text 与 chapter_ids 不能同时使用" in response.text

    def test_extract_invalid_type_422(self) -> None:
        """type 非法值 → Pydantic 422（枚举校验）。"""
        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "poetry", "text": TEXT},
        )
        assert response.status_code == 422

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_style_success(self, mock_get_svc: MagicMock) -> None:
        """STYLE 成功路径（F16 已落地）：200 + ExtractionResult 信封含 detail=StyleReport。"""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(
            return_value=_result(
                type=ExtractionType.STYLE,
                created=0,
                updated=0,
                model=None,
                indexed=False,
                warnings=["style 类型不支持自动索引"],
                detail={
                    "project_id": str(PID),
                    "source": "manual",
                    "generated_at": "2026-08-02T10:00:00Z",
                    "fingerprint": {
                        "char_count": 48,
                        "sentence_count": 3,
                        "avg_sentence_length": 16.0,
                        "sentence_length_std": 9.9,
                        "paragraph_count": 1,
                        "avg_paragraph_length": 48.0,
                        "punctuation_density": 0.1667,
                        "exclamation_density": 0.0,
                        "ellipsis_density": 0.0417,
                        "dialogue_ratio": 0.2083,
                        "vocabulary_richness": 0.8235,
                        "top_words": [{"word": "林晚", "count": 1, "first_index": 0}],
                    },
                    "ai_trace": {
                        "ai_score": 0.26,
                        "verdict": "likely_human",
                        "features": [],
                        "evidence": [
                            "各特征得分均低于 0.5，无明显 AI 特征（综合得分 0.26 → likely_human）"
                        ],
                    },
                    "lexical": {
                        "total_words": 17,
                        "unique_words": 14,
                        "top_words": [{"word": "林晚", "count": 1, "first_index": 0}],
                        "avg_word_length": 2.1,
                        "stopword_ratio": 0.0588,
                        "jieba": None,
                    },
                    "llm_assessment": None,
                    "warnings": [],
                },
            )
        )

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "style", "text": TEXT},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "style"
        assert data["status"] == "success"
        assert data["created"] == 0
        assert data["updated"] == 0
        assert data["model"] is None
        assert data["indexed"] is False
        assert data["warnings"] == ["style 类型不支持自动索引"]
        assert data["detail"]["fingerprint"]["char_count"] == 48
        assert data["detail"]["ai_trace"]["verdict"] == "likely_human"
        assert data["detail"]["lexical"]["total_words"] == 17
        svc.extract.assert_awaited_once()
        args, _ = svc.extract.await_args
        req = args[0]
        assert req.type is ExtractionType.STYLE
        assert req.text == TEXT

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_unsupported_type_422(self, mock_get_svc: MagicMock) -> None:
        """服务层 UnsupportedExtractionTypeError → 422（消息即 detail）。"""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=UnsupportedExtractionTypeError())

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "character", "text": TEXT},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "不支持的提取类型"

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_validation_error_422(self, mock_get_svc: MagicMock) -> None:
        """服务层输入约束校验失败 → 422（消息即 detail）。"""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(
            side_effect=ExtractionValidationError(
                "character/setting/foreshadowing 类型必须提供 text 或 chapter_ids"
            )
        )

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "character"},
        )
        assert response.status_code == 422
        assert (
            response.json()["detail"]
            == "character/setting/foreshadowing 类型必须提供 text 或 chapter_ids"
        )

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_chapter_not_found_422(self, mock_get_svc: MagicMock) -> None:
        """chapter_ids 指向不存在章节 → 422「章节不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=ChapterNotFoundError())

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "character", "chapter_ids": [str(CH1)]},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "章节不存在"

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_chapter_not_in_project_422(self, mock_get_svc: MagicMock) -> None:
        """chapter_ids 指向其他项目章节 → 422「章节不属于该项目」."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=ChapterNotInProjectError())

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "character", "chapter_ids": [str(CH1)]},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "章节不属于该项目"

    # ── 500 透传（LLM / 管线 / RAG / run 记录）──────────────

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_llm_error_500(self, mock_get_svc: MagicMock) -> None:
        """LLM 调用失败 → 500「LLM 调用失败，请稍后重试」（同 F9-F11）。"""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=LLMRequestError("provider error"))

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "character", "text": TEXT},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "LLM 调用失败，请稍后重试"

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_pipeline_error_500(self, mock_get_svc: MagicMock) -> None:
        """管线解析失败（ForeshadowingExtractionError）→ 500（消息含失败原因）。"""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(
            side_effect=ForeshadowingExtractionError(detail="2 次修复重试后仍无法解析为合法 JSON")
        )

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "foreshadowing", "text": TEXT},
        )
        assert response.status_code == 500
        assert "伏笔提取失败" in response.json()["detail"]

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_rag_unavailable_500(self, mock_get_svc: MagicMock) -> None:
        """RAG 不可用（vector_store 未装配）→ 500「向量检索服务不可用」."""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=RAGUnavailableError())

        response = client.post(
            "/api/v1/extract",
            json={
                "project_id": str(PID),
                "type": "character",
                "text": TEXT,
                "index": True,
            },
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "向量检索服务不可用"

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_extract_run_error_500(self, mock_get_svc: MagicMock) -> None:
        """run 记录读写失败（ExtractionRunError）→ 500（消息即 detail）。"""
        svc = _mock_svc(mock_get_svc)
        svc.extract = AsyncMock(side_effect=ExtractionRunError())

        response = client.post(
            "/api/v1/extract",
            json={"project_id": str(PID), "type": "character", "text": TEXT},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "提取记录读写失败"


class TestExtractionRunsAPI:
    """GET /api/v1/projects/{project_id}/extractions/runs — 增量状态列表。"""

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_list_runs_success(self, mock_get_svc: MagicMock) -> None:
        """runs 分页查询：Query 参数透传 + {items, total, offset, limit} 信封。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_runs = AsyncMock(
            return_value=(
                [
                    _run(),
                    _run(
                        2,
                        type=ExtractionType.SETTING,
                        source_key=str(CH1),
                        status=ExtractionStatus.ERROR,
                        error="3 次尝试后仍无法解析为合法 JSON",
                        indexed=False,
                    ),
                ],
                2,
            )
        )

        response = client.get(
            f"/api/v1/projects/{PID}/extractions/runs",
            params={"type": "character", "offset": 10, "limit": 20},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["offset"] == 10
        assert data["limit"] == 20
        items = data["items"]
        assert len(items) == 2
        assert items[0]["id"] == 1
        assert items[0]["type"] == "character"
        assert items[0]["source_key"] == "manual"
        assert items[0]["status"] == "success"
        assert items[0]["created_count"] == 2
        assert items[0]["indexed"] is True
        assert items[0]["run_at"] == "2026-08-02T10:00:00Z"
        assert items[1]["status"] == "error"
        assert items[1]["error"] == "3 次尝试后仍无法解析为合法 JSON"
        svc.list_runs.assert_awaited_once_with(
            PID, type=ExtractionType.CHARACTER, offset=10, limit=20
        )

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_list_runs_default_params(self, mock_get_svc: MagicMock) -> None:
        """缺省 Query 参数：type=None / offset=0 / limit=50。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_runs = AsyncMock(return_value=([], 0))

        response = client.get(f"/api/v1/projects/{PID}/extractions/runs")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "offset": 0, "limit": 50}
        svc.list_runs.assert_awaited_once_with(PID, type=None, offset=0, limit=50)

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_list_runs_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """项目不存在返回 404「项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.list_runs = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.get(f"/api/v1/projects/{PID}/extractions/runs")
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_list_runs_invalid_uuid_404(self) -> None:
        """无效项目 UUID 格式返回 404「项目不存在」."""
        response = client.get("/api/v1/projects/not-a-uuid/extractions/runs")
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_list_runs_invalid_type_422(self) -> None:
        """type Query 参数非法值 → Pydantic 422。"""
        response = client.get(f"/api/v1/projects/{PID}/extractions/runs", params={"type": "poetry"})
        assert response.status_code == 422

    def test_list_runs_invalid_pagination_422(self) -> None:
        """分页参数越界（limit=0 / offset=-1）→ 422。"""
        response = client.get(f"/api/v1/projects/{PID}/extractions/runs", params={"limit": 0})
        assert response.status_code == 422
        response = client.get(f"/api/v1/projects/{PID}/extractions/runs", params={"offset": -1})
        assert response.status_code == 422


class TestVectorReindexAPI:
    """POST /api/v1/projects/{project_id}/vector/reindex — 全量重建索引。"""

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_reindex_success(self, mock_get_svc: MagicMock) -> None:
        """指定 entity_types 重建：透传 + ReindexResult 序列化。"""
        svc = _mock_svc(mock_get_svc)
        svc.reindex = AsyncMock(return_value=_reindex())

        response = client.post(
            f"/api/v1/projects/{PID}/vector/reindex",
            json={"entity_types": ["character", "setting"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == str(PID)
        assert data["entity_types"] == ["character", "setting"]
        assert data["indexed"] == 87
        assert data["warnings"] == []
        svc.reindex.assert_awaited_once_with(
            PID, entity_types=[EntityType.CHARACTER, EntityType.SETTING]
        )

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_reindex_default_all_types(self, mock_get_svc: MagicMock) -> None:
        """缺省 entity_types（无 body）→ None 透传（服务层 = 全部 5 种）。"""
        svc = _mock_svc(mock_get_svc)
        svc.reindex = AsyncMock(return_value=_reindex(entity_types=list(EntityType), indexed=120))

        response = client.post(f"/api/v1/projects/{PID}/vector/reindex")
        assert response.status_code == 200
        assert response.json()["indexed"] == 120
        svc.reindex.assert_awaited_once_with(PID, entity_types=None)

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_reindex_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """项目不存在返回 404「项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.reindex = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            f"/api/v1/projects/{PID}/vector/reindex",
            json={"entity_types": ["character"]},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_reindex_invalid_uuid_404(self) -> None:
        """无效项目 UUID 格式返回 404「项目不存在」."""
        response = client.post("/api/v1/projects/not-a-uuid/vector/reindex", json={})
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_reindex_invalid_entity_type_422(self) -> None:
        """entity_types 内非法枚举值 → Pydantic 422。"""
        response = client.post(
            f"/api/v1/projects/{PID}/vector/reindex",
            json={"entity_types": ["poetry"]},
        )
        assert response.status_code == 422

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_reindex_rag_unavailable_500(self, mock_get_svc: MagicMock) -> None:
        """RAG 不可用（未装配）→ 500「向量检索服务不可用」."""
        svc = _mock_svc(mock_get_svc)
        svc.reindex = AsyncMock(side_effect=RAGUnavailableError())

        response = client.post(f"/api/v1/projects/{PID}/vector/reindex", json={})
        assert response.status_code == 500
        assert response.json()["detail"] == "向量检索服务不可用"


class TestVectorRetrieveAPI:
    """POST /api/v1/projects/{project_id}/vector/retrieve — 语义检索。"""

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_retrieve_success(self, mock_get_svc: MagicMock) -> None:
        """检索成功：参数透传 + {items: [RetrievedEntity]} 信封序列化。"""
        svc = _mock_svc(mock_get_svc)
        svc.retrieve = AsyncMock(return_value=[_retrieved()])

        response = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={
                "query": "林晚右肩的胎记",
                "entity_types": ["foreshadowing"],
                "top_k": 5,
                "min_score": 0.3,
            },
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["entity_id"] == "9b1c2d3e-0000-4000-8000-000000000021"
        assert item["entity_type"] == "foreshadowing"
        assert item["content"] == "伏笔：林晚的身世。林晚右肩的胎记与女主母亲的信物相同……"
        assert item["relevance_score"] == 0.82
        assert item["metadata"] == {
            "project_id": str(PID),
            "name": "林晚的身世",
            "status": "open",
        }
        svc.retrieve.assert_awaited_once_with(
            "林晚右肩的胎记",
            project_id=PID,
            entity_types=[EntityType.FORESHADOWING],
            top_k=5,
            min_score=0.3,
        )

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_retrieve_default_params(self, mock_get_svc: MagicMock) -> None:
        """缺省参数：entity_types=None / top_k=10 / min_score=0.0。"""
        svc = _mock_svc(mock_get_svc)
        svc.retrieve = AsyncMock(return_value=[])

        response = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={"query": "林晚右肩的胎记"},
        )
        assert response.status_code == 200
        assert response.json() == {"items": []}
        svc.retrieve.assert_awaited_once_with(
            "林晚右肩的胎记", project_id=PID, entity_types=None, top_k=10, min_score=0.0
        )

    def test_retrieve_blank_query_422(self) -> None:
        """空白 query → 422「查询文本不能为空」."""
        response = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={"query": "   "},
        )
        assert response.status_code == 422
        assert "查询文本不能为空" in response.text

    def test_retrieve_missing_query_422(self) -> None:
        """缺少必填 query → Pydantic 422。"""
        response = client.post(f"/api/v1/projects/{PID}/vector/retrieve", json={})
        assert response.status_code == 422

    def test_retrieve_top_k_out_of_range_422(self) -> None:
        """top_k 越界（0 / 51）→ 422。"""
        response = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={"query": "q", "top_k": 0},
        )
        assert response.status_code == 422
        assert "top_k 必须在 1-50 之间" in response.text
        response = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={"query": "q", "top_k": 51},
        )
        assert response.status_code == 422

    def test_retrieve_min_score_out_of_range_422(self) -> None:
        """min_score 越界（>1.0）→ 422。"""
        response = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={"query": "q", "min_score": 1.5},
        )
        assert response.status_code == 422

    def test_retrieve_invalid_entity_type_422(self) -> None:
        """entity_types 内非法枚举值 → Pydantic 422。"""
        response = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={"query": "q", "entity_types": ["poetry"]},
        )
        assert response.status_code == 422

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_retrieve_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """项目不存在返回 404「项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.retrieve = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={"query": "q"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_retrieve_invalid_uuid_404(self) -> None:
        """无效项目 UUID 格式返回 404「项目不存在」."""
        response = client.post(
            "/api/v1/projects/not-a-uuid/vector/retrieve",
            json={"query": "q"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    @patch("inkflow.api.routers.extractions.get_extraction_service")
    def test_retrieve_rag_unavailable_500(self, mock_get_svc: MagicMock) -> None:
        """RAG 不可用（未装配）→ 500「向量检索服务不可用」."""
        svc = _mock_svc(mock_get_svc)
        svc.retrieve = AsyncMock(side_effect=RAGUnavailableError())

        response = client.post(
            f"/api/v1/projects/{PID}/vector/retrieve",
            json={"query": "q"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "向量检索服务不可用"
