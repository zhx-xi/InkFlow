"""F16 风格检测服务报告模型单元测试 — 无 I/O，纯 Pydantic 验证.

测试范围：WordFrequency 三字段 / StyleFingerprint 12 字段默认值与嵌套 /
AITraceVerdict 三值枚举 / AITraceFeature / AITraceAssessment 默认值与嵌套 /
LexicalAnalysis（含 jieba 板块 None 默认）/ JiebaAnalysis 四字段 /
StyleLLMAssessment 四字段 / StyleReport 完整序列化（llm_assessment 两态）。

依据: specs/f16-style-service/spec.md §2 数据模型（§2.1-§2.7、§2.9 领域模型代码）。
StyleAnalyzeRequest（§2.8）定义在 API 层 api/routers/style.py（同 F9-F15 DTO 先例），
不属于领域模型测试范围——由 test_style_api.py 覆盖（本 RED 阶段不测）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

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

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 2, 12, 0, 0)


def make_fingerprint(**overrides: Any) -> StyleFingerprint:
    """构造一份完整风格指纹（默认值与 spec §3.2 示例同形态，可覆盖任意字段）."""
    base = {
        "char_count": 46,
        "sentence_count": 3,
        "avg_sentence_length": 15.33,
        "sentence_length_std": 3.27,
        "paragraph_count": 1,
        "avg_paragraph_length": 46.0,
        "punctuation_density": 0.2391,
        "exclamation_density": 0.0,
        "ellipsis_density": 0.0435,
        "dialogue_ratio": 0.2826,
        "vocabulary_richness": 1.0,
        "top_words": [
            WordFrequency(word="林晚推开窗", count=1, first_index=0),
            WordFrequency(word="夜色如墨", count=1, first_index=1),
        ],
    }
    base.update(overrides)
    return StyleFingerprint(**base)


def make_ai_trace(**overrides: Any) -> AITraceAssessment:
    """构造一份完整 AI 痕迹评估（默认含 1 条特征与 1 条证据）."""
    base = {
        "ai_score": 0.5177,
        "verdict": AITraceVerdict.UNCERTAIN,
        "features": [
            AITraceFeature(
                feature="sentence_uniformity",
                value=0.23,
                score=0.77,
                note="句长变异系数 0.23（低）——句式偏整齐",
            )
        ],
        "evidence": ["测试依据"],
    }
    base.update(overrides)
    return AITraceAssessment(**base)


def make_lexical(**overrides: Any) -> LexicalAnalysis:
    """构造一份完整词汇分析（默认含 jieba 增强板块）."""
    base = {
        "total_words": 17,
        "unique_words": 14,
        "top_words": [WordFrequency(word="林晚", count=2, first_index=0)],
        "avg_word_length": 2.1,
        "stopword_ratio": 0.0588,
        "jieba": JiebaAnalysis(
            jieba_total_words=19,
            jieba_unique_words=15,
            jieba_avg_word_length=1.9,
            jieba_top_words=[WordFrequency(word="林晚", count=2, first_index=0)],
        ),
    }
    base.update(overrides)
    return LexicalAnalysis(**base)


def make_report(**overrides: Any) -> StyleReport:
    """构造一份完整风格报告（默认 llm_assessment=None，可覆盖任意字段）."""
    base = {
        "project_id": PID,
        "source": "manual",
        "generated_at": TS,
        "fingerprint": make_fingerprint(),
        "ai_trace": make_ai_trace(),
        "lexical": make_lexical(),
        "warnings": ["测试警告"],
    }
    base.update(overrides)
    return StyleReport(**base)


class TestWordFrequency:
    """WordFrequency 高频词条目（§2.1：word/count/first_index）."""

    def test_fields_roundtrip(self) -> None:
        """三字段构造后原样保留，类型正确（count/first_index 为 int）."""
        wf = WordFrequency(word="林晚", count=3, first_index=0)
        assert wf.word == "林晚"
        assert wf.count == 3
        assert wf.first_index == 0
        assert isinstance(wf.count, int)
        assert isinstance(wf.first_index, int)

    def test_required_fields_missing_raises(self) -> None:
        """缺少必填字段（word/count/first_index 任一）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            WordFrequency(word="林晚")  # 缺 count/first_index
        with pytest.raises(ValidationError):
            WordFrequency(count=1, first_index=0)  # 缺 word


class TestStyleFingerprint:
    """StyleFingerprint 风格指纹（§2.2：12 项结构性统计）."""

    def test_defaults_all_zero_and_empty(self) -> None:
        """缺省构造时 11 项数值均为 0、top_words 为空列表（空文本报告形态）."""
        fp = StyleFingerprint()
        assert fp.char_count == 0
        assert fp.sentence_count == 0
        assert fp.avg_sentence_length == 0.0
        assert fp.sentence_length_std == 0.0
        assert fp.paragraph_count == 0
        assert fp.avg_paragraph_length == 0.0
        assert fp.punctuation_density == 0.0
        assert fp.exclamation_density == 0.0
        assert fp.ellipsis_density == 0.0
        assert fp.dialogue_ratio == 0.0
        assert fp.vocabulary_richness == 0.0
        assert fp.top_words == []

    def test_explicit_values_roundtrip_with_nested_top_words(self) -> None:
        """显式构造 12 字段原样保留，top_words 嵌套 WordFrequency 列表."""
        fp = make_fingerprint()
        assert fp.char_count == 46
        assert fp.avg_sentence_length == 15.33
        assert isinstance(fp.avg_sentence_length, float)
        assert fp.sentence_length_std == 3.27
        assert fp.punctuation_density == 0.2391
        assert fp.vocabulary_richness == 1.0
        assert [wf.word for wf in fp.top_words] == ["林晚推开窗", "夜色如墨"]
        assert isinstance(fp.top_words[0], WordFrequency)
        assert fp.top_words[0].first_index == 0


class TestAITraceVerdict:
    """AITraceVerdict 判定结论枚举（§2.3：三值）."""

    def test_has_exactly_three_members(self) -> None:
        """枚举成员数恰为 3（likely_human/uncertain/likely_ai）."""
        assert len(AITraceVerdict) == 3

    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            ("LIKELY_HUMAN", "likely_human"),
            ("UNCERTAIN", "uncertain"),
            ("LIKELY_AI", "likely_ai"),
        ],
    )
    def test_members_and_values(self, member: str, expected: str) -> None:
        """各成员的值与 spec §2.3 定义一致."""
        assert getattr(AITraceVerdict, member).value == expected

    def test_is_str_enum(self) -> None:
        """AITraceVerdict 是 StrEnum：成员即字符串，可直接作 JSON 值."""
        assert isinstance(AITraceVerdict.LIKELY_HUMAN, str)
        assert AITraceVerdict("likely_human") is AITraceVerdict.LIKELY_HUMAN

    def test_invalid_value_raises(self) -> None:
        """未知判定值应抛出 ValueError."""
        with pytest.raises(ValueError):
            AITraceVerdict("definitely_ai")


class TestAITraceFeature:
    """AITraceFeature 单个启发式特征（§2.3：feature/value/score/note）."""

    def test_fields_roundtrip(self) -> None:
        """四字段构造后原样保留，value/score 为 float."""
        f = AITraceFeature(
            feature="sentence_uniformity",
            value=0.62,
            score=0.38,
            note="句长变异系数 0.62——句式波动正常",
        )
        assert f.feature == "sentence_uniformity"
        assert f.value == 0.62
        assert f.score == 0.38
        assert isinstance(f.score, float)
        assert f.note == "句长变异系数 0.62——句式波动正常"


class TestAITraceAssessment:
    """AITraceAssessment 综合评估（§2.3：ai_score/verdict/features/evidence）."""

    def test_defaults(self) -> None:
        """缺省构造：ai_score=0.0、verdict=uncertain、features/evidence 为空."""
        assessment = AITraceAssessment()
        assert assessment.ai_score == 0.0
        assert assessment.verdict is AITraceVerdict.UNCERTAIN
        assert assessment.features == []
        assert assessment.evidence == []

    def test_nested_features_and_verdict_string_coercion(self) -> None:
        """features 嵌套 AITraceFeature；verdict 接受字符串值并转为枚举."""
        feature = AITraceFeature(
            feature="exclamation_density_low",
            value=0.0,
            score=1.0,
            note="感叹号密度 0.0000（低于 0.005）——缺少情绪标点",
        )
        assessment = AITraceAssessment(
            ai_score=0.61,
            verdict="likely_ai",
            features=[feature],
            evidence=["最高频词占比 0.1250（超过 0.06）——集中于单一词汇"],
        )
        assert assessment.verdict is AITraceVerdict.LIKELY_AI
        assert assessment.features == [feature]
        assert isinstance(assessment.features[0], AITraceFeature)
        assert assessment.evidence == ["最高频词占比 0.1250（超过 0.06）——集中于单一词汇"]


class TestLexicalAnalysis:
    """LexicalAnalysis 词汇分析（§2.4：含 jieba 增强板块）."""

    def test_defaults_jieba_none(self) -> None:
        """缺省构造：数值全 0、top_words 空、jieba 为 None（空文本/未装配）."""
        lexical = LexicalAnalysis()
        assert lexical.total_words == 0
        assert lexical.unique_words == 0
        assert lexical.top_words == []
        assert lexical.avg_word_length == 0.0
        assert lexical.stopword_ratio == 0.0
        assert lexical.jieba is None

    def test_jieba_nested_roundtrip(self) -> None:
        """jieba 字段嵌套 JiebaAnalysis 实例并原样保留."""
        lexical = make_lexical()
        assert lexical.total_words == 17
        assert lexical.unique_words == 14
        assert lexical.avg_word_length == 2.1
        assert lexical.stopword_ratio == 0.0588
        assert lexical.jieba is not None
        assert isinstance(lexical.jieba, JiebaAnalysis)
        assert lexical.jieba.jieba_total_words == 19


class TestJiebaAnalysis:
    """JiebaAnalysis jieba 精确分词增强板块（§2.5：四字段）."""

    def test_fields_roundtrip(self) -> None:
        """四字段构造后原样保留，jieba_top_words 嵌套 WordFrequency."""
        ja = JiebaAnalysis(
            jieba_total_words=19,
            jieba_unique_words=15,
            jieba_avg_word_length=1.9,
            jieba_top_words=[WordFrequency(word="林晚", count=2, first_index=0)],
        )
        assert ja.jieba_total_words == 19
        assert ja.jieba_unique_words == 15
        assert ja.jieba_avg_word_length == 1.9
        assert isinstance(ja.jieba_avg_word_length, float)
        assert [wf.word for wf in ja.jieba_top_words] == ["林晚"]
        assert ja.jieba_top_words[0].first_index == 0

    def test_defaults(self) -> None:
        """缺省构造：数值全 0、jieba_top_words 为空."""
        ja = JiebaAnalysis()
        assert ja.jieba_total_words == 0
        assert ja.jieba_unique_words == 0
        assert ja.jieba_avg_word_length == 0.0
        assert ja.jieba_top_words == []


class TestStyleLLMAssessment:
    """StyleLLMAssessment LLM 深度分析板块（§2.7：四字段）."""

    def test_fields_roundtrip(self) -> None:
        """四字段构造后原样保留，generated_at 为 datetime."""
        assessment = StyleLLMAssessment(
            llm_verdict="likely_human",
            reasoning="句式长短错落、对话自然",
            model="gpt-4o",
            generated_at=TS,
        )
        assert assessment.llm_verdict == "likely_human"
        assert assessment.reasoning == "句式长短错落、对话自然"
        assert assessment.model == "gpt-4o"
        assert assessment.generated_at == TS
        assert isinstance(assessment.generated_at, datetime)


class TestStyleReport:
    """StyleReport 风格检测报告（§2.6：完整序列化 + llm_assessment 两态）."""

    def test_required_fields_missing_raises(self) -> None:
        """缺少必填字段（project_id/source/generated_at）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            StyleReport(source="manual", generated_at=TS)  # 缺 project_id
        with pytest.raises(ValidationError):
            StyleReport(project_id=PID, generated_at=TS)  # 缺 source
        with pytest.raises(ValidationError):
            StyleReport(project_id=PID, source="manual")  # 缺 generated_at

    def test_defaults_nested_factories(self) -> None:
        """缺省构造：fingerprint/ai_trace/lexical 为默认工厂、llm_assessment=None、
        warnings 为空列表."""
        report = StyleReport(project_id=PID, source="manual", generated_at=TS)
        assert report.fingerprint == StyleFingerprint()
        assert report.ai_trace == AITraceAssessment()
        assert report.lexical == LexicalAnalysis()
        assert report.llm_assessment is None
        assert report.warnings == []

    def test_json_serialization_llm_none(self) -> None:
        """model_dump(mode='json')：UUID→str、datetime→ISO8601、枚举→str、
        嵌套板块一并序列化；llm_assessment=None 序列化为 null（Q1=C 可选板块）."""
        dumped = make_report().model_dump(mode="json")
        assert dumped["project_id"] == str(PID)
        assert dumped["source"] == "manual"
        assert dumped["generated_at"] == "2026-08-02T12:00:00"
        assert dumped["fingerprint"]["char_count"] == 46
        assert dumped["fingerprint"]["avg_sentence_length"] == 15.33
        assert dumped["fingerprint"]["top_words"][0] == {
            "word": "林晚推开窗",
            "count": 1,
            "first_index": 0,
        }
        assert dumped["ai_trace"]["ai_score"] == 0.5177
        assert dumped["ai_trace"]["verdict"] == "uncertain"
        assert dumped["ai_trace"]["features"][0]["feature"] == "sentence_uniformity"
        assert dumped["ai_trace"]["evidence"] == ["测试依据"]
        assert dumped["lexical"]["total_words"] == 17
        assert dumped["lexical"]["jieba"]["jieba_total_words"] == 19
        assert dumped["lexical"]["jieba"]["jieba_top_words"][0]["first_index"] == 0
        assert dumped["llm_assessment"] is None
        assert dumped["warnings"] == ["测试警告"]

    def test_json_serialization_llm_filled(self) -> None:
        """llm_assessment 填充时序列化为完整对象（verdict/reasoning/model/generated_at）."""
        report = make_report(
            llm_assessment=StyleLLMAssessment(
                llm_verdict="likely_human",
                reasoning="句式长短错落、对话与叙述穿插自然",
                model="gpt-4o",
                generated_at=TS,
            )
        )
        dumped = report.model_dump(mode="json")
        assert dumped["llm_assessment"] == {
            "llm_verdict": "likely_human",
            "reasoning": "句式长短错落、对话与叙述穿插自然",
            "model": "gpt-4o",
            "generated_at": "2026-08-02T12:00:00",
        }

    def test_json_roundtrip_both_states(self) -> None:
        """model_dump_json → model_validate_json 保真（快照断言基线）；
        llm_assessment None 与填充两态均可往返."""
        for report in (
            make_report(),
            make_report(
                llm_assessment=StyleLLMAssessment(
                    llm_verdict="likely_ai",
                    reasoning="句式整齐、标点单调",
                    model="gpt-4o",
                    generated_at=TS,
                )
            ),
        ):
            restored = StyleReport.model_validate_json(report.model_dump_json())
            assert restored == report
