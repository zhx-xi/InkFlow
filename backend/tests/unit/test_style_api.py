"""F16 风格检测 API 测试 — Mock StyleService（M7 RED→GREEN）。

测试范围 (spec §9 API 测试 + §3.2/§3.3 异常映射表):
- POST /api/v1/projects/{project_id}/style/analyze 成功路径（200 + 完整 StyleReport
  序列化，含 llm_assessment 有/无两态）
- 请求体校验（StyleAnalyzeRequest DTO，spec §2.8/§7）: text 超 50000 / chapter_ids
  空列表 / text+chapter_ids 同给 / 均未提供 → 422
- llm_analysis 透传（true → Service 收到 True；false → False；缺省 → None，spec §2.8）
- 404 项目不存在（ProjectNotFoundError）/ 无效 UUID（不进入服务层，spec §3.3）
- 422 输入校验（Service 抛 StyleValidationError → 422 消息即 detail）
- 500 透传（StyleLLMUnavailableError / StyleLLMAnalysisError / LLMRequestError / DB 错误）
- 幂等性（同输入两次 POST 响应体逐字段相等，spec §6.4）

策略: @patch("inkflow.api.routers.style.get_style_service") 整体替换服务获取函数
（router 模块级本地引用，同 F15 test_audit_api.py 模式）；被路由 await 的 analyze
显式赋 AsyncMock —— 未赋值的同步 MagicMock 子 mock 被 await 会返回 coroutine 导致
500（F4 4.1 实测陷阱）。

依据: specs/f16-style-service/spec.md §3 + §7 + §9。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.style import (
    AITraceAssessment,
    AITraceFeature,
    AITraceVerdict,
    JiebaAnalysis,
    LexicalAnalysis,
    StyleFingerprint,
    StyleLLMAssessment,
    StyleReport,
    WordFrequency,
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.style_errors import (
    StyleLLMAnalysisError,
    StyleLLMUnavailableError,
    StyleValidationError,
)

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CH1 = uuid.UUID("7a4f2c91-0000-4000-8000-000000000011")
CH2 = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000012")
TS = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)
TEXT = "林晚推开窗，夜色如墨。她低声说：「三年了，我终究还是回来了。」窗外传来更鼓声，一下，两下……"


def _report(**overrides: object) -> StyleReport:
    """构造完整 StyleReport（三大板块 + jieba + warnings；llm_assessment 默认 None，§2.6）。"""
    kwargs: dict[str, object] = {
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
            top_words=[
                WordFrequency(word="林晚", count=1, first_index=0),
                WordFrequency(word="窗外", count=1, first_index=9),
            ],
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
            jieba=JiebaAnalysis(
                jieba_total_words=19,
                jieba_unique_words=15,
                jieba_avg_word_length=1.9,
                jieba_top_words=[WordFrequency(word="林晚", count=1, first_index=0)],
            ),
        ),
        "llm_assessment": None,
        "warnings": ["未检测到完整句子（句尾符不足）——句子统计仅供参考"],
    }
    kwargs.update(overrides)
    return StyleReport(**kwargs)  # type: ignore[arg-type]


def _llm_assessment() -> StyleLLMAssessment:
    """构造 LLM 深度分析板块（spec §2.7，Q1=C：llm_verdict/reasoning/model/generated_at）。"""
    return StyleLLMAssessment(
        llm_verdict="likely_human",
        reasoning="句式长短错落、对话与叙述穿插自然——统计特征未显示明显 AI 生成模式。",
        model="gpt-4o",
        generated_at=TS,
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock StyleService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


def _analyze_kwargs(svc: MagicMock) -> dict[str, object]:
    """提取 svc.analyze 最近一次调用的参数（按签名位置合并 args/kwargs，兼容两种调用风格）。"""
    args, kwargs = svc.analyze.await_args
    merged: dict[str, object] = dict(kwargs)
    for name, value in zip(("project_id", "text", "chapter_ids", "llm_analysis"), args):
        merged[name] = value
    return merged


class TestStyleAnalyzeAPI:
    """POST /api/v1/projects/{project_id}/style/analyze 端点测试。"""

    @patch("inkflow.api.routers.style.get_style_service")
    def test_style_analyze_success_200(self, mock_get_svc: MagicMock) -> None:
        """手动文本分析成功 → 200 + 完整 StyleReport JSON（llm_assessment=null，spec §3.2）。"""
        svc = _mock_svc(mock_get_svc)
        svc.analyze = AsyncMock(return_value=_report())

        response = client.post(f"/api/v1/projects/{PID}/style/analyze", json={"text": TEXT})

        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == str(PID)
        assert data["source"] == "manual"
        assert data["generated_at"] == "2026-08-02T12:00:00Z"
        # 风格指纹（12 项抽样断言 + top_words 结构）
        fp = data["fingerprint"]
        assert fp["char_count"] == 48
        assert fp["sentence_count"] == 3
        assert fp["avg_sentence_length"] == 16.0
        assert fp["sentence_length_std"] == 9.9
        assert fp["paragraph_count"] == 1
        assert fp["avg_paragraph_length"] == 48.0
        assert fp["punctuation_density"] == 0.1667
        assert fp["exclamation_density"] == 0.0
        assert fp["ellipsis_density"] == 0.0417
        assert fp["dialogue_ratio"] == 0.2083
        assert fp["vocabulary_richness"] == 0.8235
        assert fp["top_words"] == [
            {"word": "林晚", "count": 1, "first_index": 0},
            {"word": "窗外", "count": 1, "first_index": 9},
        ]
        # AI 痕迹板块
        assert data["ai_trace"]["ai_score"] == 0.26
        assert data["ai_trace"]["verdict"] == "likely_human"
        assert data["ai_trace"]["features"][0]["feature"] == "sentence_uniformity"
        assert data["ai_trace"]["features"][0]["note"] == "句长变异系数 0.62——句式波动正常"
        assert data["ai_trace"]["evidence"][0].startswith("各特征得分均低于 0.5")
        # 词汇分析（含 jieba 增强板块，Q2=C）
        assert data["lexical"]["total_words"] == 17
        assert data["lexical"]["unique_words"] == 14
        assert data["lexical"]["avg_word_length"] == 2.1
        assert data["lexical"]["stopword_ratio"] == 0.0588
        assert data["lexical"]["jieba"]["jieba_total_words"] == 19
        # 可选板块两态之一: 未开启 LLM → null（spec §2.6/§3.2）
        assert data["llm_assessment"] is None
        assert data["warnings"] == ["未检测到完整句子（句尾符不足）——句子统计仅供参考"]
        kwargs = _analyze_kwargs(svc)
        assert kwargs["project_id"] == PID
        assert kwargs["text"] == TEXT
        assert kwargs["chapter_ids"] is None
        assert kwargs["llm_analysis"] is None

    @patch("inkflow.api.routers.style.get_style_service")
    def test_style_analyze_with_llm_assessment(self, mock_get_svc: MagicMock) -> None:
        """llm_analysis=true 且 LLM 可用 → 响应含 llm_assessment 板块（spec §2.7/§3.2）。"""
        svc = _mock_svc(mock_get_svc)
        svc.analyze = AsyncMock(return_value=_report(llm_assessment=_llm_assessment()))

        response = client.post(
            f"/api/v1/projects/{PID}/style/analyze", json={"text": TEXT, "llm_analysis": True}
        )

        assert response.status_code == 200
        llm = response.json()["llm_assessment"]
        assert llm["llm_verdict"] == "likely_human"
        assert "句式长短错落" in llm["reasoning"]
        assert llm["model"] == "gpt-4o"
        assert llm["generated_at"] == "2026-08-02T12:00:00Z"
        kwargs = _analyze_kwargs(svc)
        assert kwargs["llm_analysis"] is True

    @patch("inkflow.api.routers.style.get_style_service")
    def test_style_analyze_chapter_ids_mode(self, mock_get_svc: MagicMock) -> None:
        """章节模式多章合并 → Service 收到 chapter_ids（text=None）+ source=chapters:<ids>。"""
        svc = _mock_svc(mock_get_svc)
        svc.analyze = AsyncMock(
            return_value=_report(source=f"chapters:{CH1},{CH2}", warnings=["多章节合并分析"])
        )

        response = client.post(
            f"/api/v1/projects/{PID}/style/analyze",
            json={"chapter_ids": [str(CH1), str(CH2)]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["source"] == f"chapters:{CH1},{CH2}"
        assert data["warnings"] == ["多章节合并分析"]
        kwargs = _analyze_kwargs(svc)
        assert kwargs["project_id"] == PID
        assert kwargs["text"] is None
        assert kwargs["chapter_ids"] == [CH1, CH2]

    @patch("inkflow.api.routers.style.get_style_service")
    def test_style_llm_analysis_false_passthrough(self, mock_get_svc: MagicMock) -> None:
        """请求体显式 llm_analysis=false → Service 收到 False（覆盖项目配置，spec §2.8）。"""
        svc = _mock_svc(mock_get_svc)
        svc.analyze = AsyncMock(return_value=_report())

        response = client.post(
            f"/api/v1/projects/{PID}/style/analyze", json={"text": TEXT, "llm_analysis": False}
        )

        assert response.status_code == 200
        assert _analyze_kwargs(svc)["llm_analysis"] is False

    @pytest.mark.parametrize(
        "body",
        [
            {"text": "长" * 50001},
            {"chapter_ids": []},
            {"text": TEXT, "chapter_ids": [str(CH1)]},
            {},
        ],
        ids=[
            "text_too_long",
            "empty_chapter_ids",
            "text_and_chapter_ids_conflict",
            "missing_source",
        ],
    )
    @patch("inkflow.api.routers.style.get_style_service")
    def test_style_analyze_invalid_body_422(
        self, mock_get_svc: MagicMock, body: dict[str, object]
    ) -> None:
        """请求体校验（spec §7 边界表）: 超限/空列表/互斥冲突/均缺 → 422。"""
        svc = _mock_svc(mock_get_svc)
        svc.analyze = AsyncMock()

        response = client.post(f"/api/v1/projects/{PID}/style/analyze", json=body)

        assert response.status_code == 422
        svc.analyze.assert_not_awaited()

    @patch("inkflow.api.routers.style.get_style_service")
    def test_style_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """项目不存在 → 404「项目不存在」（spec §3.3/§7）。"""
        svc = _mock_svc(mock_get_svc)
        svc.analyze = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(f"/api/v1/projects/{PID}/style/analyze", json={"text": TEXT})

        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    @patch("inkflow.api.routers.style.get_style_service")
    def test_style_invalid_project_uuid_404(self, mock_get_svc: MagicMock) -> None:
        """无效项目 UUID → 404「项目不存在」（不进入服务层，spec §3.3）。"""
        svc = _mock_svc(mock_get_svc)
        svc.analyze = AsyncMock()

        response = client.post("/api/v1/projects/not-a-uuid/style/analyze", json={"text": TEXT})

        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"
        svc.analyze.assert_not_awaited()

    @patch("inkflow.api.routers.style.get_style_service")
    def test_style_validation_error_422(self, mock_get_svc: MagicMock) -> None:
        """Service 抛 StyleValidationError → 422 消息即 detail（spec §3.3 异常映射表）。"""
        svc = _mock_svc(mock_get_svc)
        svc.analyze = AsyncMock(side_effect=StyleValidationError("必须提供 text 或 chapter_ids"))

        response = client.post(f"/api/v1/projects/{PID}/style/analyze", json={"text": TEXT})

        assert response.status_code == 422
        assert response.json()["detail"] == "必须提供 text 或 chapter_ids"

    @pytest.mark.parametrize(
        "error",
        [
            StyleLLMUnavailableError("LLM 深度分析不可用"),
            StyleLLMAnalysisError("3 次尝试后仍无法解析为合法 JSON"),
            LLMRequestError("LLM 调用失败"),
        ],
        ids=["llm_unavailable", "llm_analysis_error", "llm_request_error"],
    )
    @patch("inkflow.api.routers.style.get_style_service")
    def test_style_llm_errors_500(self, mock_get_svc: MagicMock, error: Exception) -> None:
        """llm_analysis=true 相关错误 → 500 透传（spec §3.3: StyleLLMUnavailableError /
        StyleLLMAnalysisError / LLMRequestError）。"""
        svc = _mock_svc(mock_get_svc)
        svc.analyze = AsyncMock(side_effect=error)

        response = client.post(
            f"/api/v1/projects/{PID}/style/analyze", json={"text": TEXT, "llm_analysis": True}
        )

        assert response.status_code == 500

    @patch("inkflow.api.routers.style.get_style_service")
    def test_style_db_error_500(self, mock_get_svc: MagicMock) -> None:
        """项目仓储读取失败（DB 错误）→ 500「内部错误: ...」透传（spec §3.3/§7）。"""
        svc = _mock_svc(mock_get_svc)
        svc.analyze = AsyncMock(side_effect=RuntimeError("数据库读取失败"))

        response = client.post(f"/api/v1/projects/{PID}/style/analyze", json={"text": TEXT})

        assert response.status_code == 500
        assert "内部错误" in response.json()["detail"]

    @patch("inkflow.api.routers.style.get_style_service")
    def test_style_analyze_idempotent(self, mock_get_svc: MagicMock) -> None:
        """同一项目同一输入两次分析 → 响应体逐字段相等（严格幂等，spec §6.4）。"""
        svc = _mock_svc(mock_get_svc)
        svc.analyze = AsyncMock(return_value=_report())

        first = client.post(f"/api/v1/projects/{PID}/style/analyze", json={"text": TEXT})
        second = client.post(f"/api/v1/projects/{PID}/style/analyze", json={"text": TEXT})

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        assert svc.analyze.await_count == 2
