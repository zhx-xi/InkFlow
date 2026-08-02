"""F16 风格检测领域模型 — 风格报告与各分析板块（纯 Pydantic 输出模型）.

WordFrequency 是高频词条目（first_index 为排序次级键）；StyleFingerprint
是风格指纹 12 项结构性统计；AITraceVerdict / AITraceFeature /
AITraceAssessment 构成 AI 痕迹检测板块（启发式评分 + 三档判定）；
LexicalAnalysis / JiebaAnalysis 构成词汇分析板块（零依赖正则词块基础
统计 + jieba 精确分词增强，Q2=C）；StyleLLMAssessment 是可选 LLM 深度
分析板块（Q1=C，默认关闭）；StyleReport 是编排输出报告。

F16 不新建业务实体表——报告是文本内容的瞬态只读计算结果，全部为纯
Pydantic 输出模型，model_dump(mode="json") 直接进 API/CLI 信封
（spec §2）。

依据: specs/f16-style-service/spec.md §2（§2.1-§2.7、§2.9 领域模型代码）。
领域层保持纯净：仅依赖 Pydantic v2 与标准库，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class WordFrequency(BaseModel):
    """高频词条目（spec §2.1）— first_index 为首次出现 token 序号（排序次级键）.

    Attributes:
        word: 词条文本（token，中文连续汉字串或英文单词）.
        count: 出现次数（≥ 1）.
        first_index: 首次出现的 token 序号（0 起，扫描顺序）——排序次级键，
            保证同频词顺序确定性（spec §6.3）.
    """

    word: str
    count: int
    first_index: int


class StyleFingerprint(BaseModel):
    """风格指纹（spec §2.2）— 12 项结构性统计，全部确定性计算.

    Attributes:
        char_count: 字符总数（去除空白字符后）.
        sentence_count: 句子数（按句尾符切分）.
        avg_sentence_length: 平均句长（char_count / sentence_count，保留 2 位）.
        sentence_length_std: 句长标准差（总体标准差，n 分母，保留 2 位；
            sentence_count < 2 时为 0）.
        paragraph_count: 段落数（非空段落）.
        avg_paragraph_length: 平均段落长度（保留 2 位）.
        punctuation_density: 标点密度（保留 4 位）.
        exclamation_density: 感叹号密度（保留 4 位）.
        ellipsis_density: 省略号密度（保留 4 位）.
        dialogue_ratio: 对话占比（引号内字符数 / char_count，保留 4 位）.
        vocabulary_richness: 词汇丰富度（TTR = unique_words / total_words，
            保留 4 位，与词汇分析同源数据）.
        top_words: 高频词 Top-N（N=10，按 (count DESC, first_index ASC) 排序）.
    """

    char_count: int = 0
    sentence_count: int = 0
    avg_sentence_length: float = 0.0
    sentence_length_std: float = 0.0
    paragraph_count: int = 0
    avg_paragraph_length: float = 0.0
    punctuation_density: float = 0.0
    exclamation_density: float = 0.0
    ellipsis_density: float = 0.0
    dialogue_ratio: float = 0.0
    vocabulary_richness: float = 0.0
    top_words: list[WordFrequency] = Field(default_factory=list)


class AITraceVerdict(StrEnum):
    """AI 痕迹判定结论（spec §6.2 阈值语义）.

    Attributes:
        LIKELY_HUMAN: ai_score ≤ 0.35 — 统计形状更接近人类写作.
        UNCERTAIN: 0.35 < ai_score < 0.65 — 特征不明显，无法倾向.
        LIKELY_AI: ai_score ≥ 0.65 — 统计形状更接近常见 AI 生成文本.
    """

    LIKELY_HUMAN = "likely_human"  # ai_score ≤ 0.35 — 统计形状更接近人类写作
    UNCERTAIN = "uncertain"  # 0.35 < ai_score < 0.65 — 特征不明显，无法倾向
    LIKELY_AI = "likely_ai"  # ai_score ≥ 0.65 — 统计形状更接近常见 AI 生成文本


class AITraceFeature(BaseModel):
    """单个启发式特征（spec §5.4 特征表）— feature 为 ASCII 稳定键，score 1 = 更像 AI.

    Attributes:
        feature: 特征名（稳定 ASCII 键，如 "sentence_uniformity"——排序/断言用）.
        value: 观测值（原始统计量）.
        score: 启发式评分 0-1（1 = 更像 AI）.
        note: 人类可读解释（中文，含观测值与参考方向）.
    """

    feature: str
    value: float
    score: float
    note: str


class AITraceAssessment(BaseModel):
    """AI 痕迹综合评估（spec §5.4/§6.2）.

    Attributes:
        ai_score: 综合得分 = 特征得分均值（等权，保留 4 位）.
        verdict: 判定结论（阈值语义见 spec §6.2）.
        features: 全部特征（按 feature ASC 稳定排序）.
        evidence: 判定依据（score ≥ 0.5 的特征 note + 阈值说明；无则单条说明）.
    """

    ai_score: float = 0.0
    verdict: AITraceVerdict = AITraceVerdict.UNCERTAIN
    features: list[AITraceFeature] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class LexicalAnalysis(BaseModel):
    """词汇分析（spec §2.4）— 零依赖正则词块统计（基础板块，始终计算）.

    Attributes:
        total_words: 词条总数（token 数）.
        unique_words: 不同词条数（去重后）.
        top_words: 高频词 Top-N（N=10，同 fingerprint.top_words 同源数据）.
        avg_word_length: 平均词长（总 token 字符数 / total_words，保留 2 位）.
        stopword_ratio: 停用词占比（保留 4 位）.
        jieba: jieba 精确分词增强板块（Q2=C）——None = jieba 未装配（防御性）
            或空文本.
    """

    total_words: int = 0
    unique_words: int = 0
    top_words: list[WordFrequency] = Field(default_factory=list)
    avg_word_length: float = 0.0
    stopword_ratio: float = 0.0
    jieba: JiebaAnalysis | None = None  # jieba 精确分词增强板块（§2.5，Q2=C）


class JiebaAnalysis(BaseModel):
    """jieba 精确分词统计（spec §2.5）— jieba.lcut 精确模式，与正则词块同构.

    Attributes:
        jieba_total_words: jieba 分词词条总数（jieba.lcut 精确模式）.
        jieba_unique_words: 不同词条数（去重后）.
        jieba_avg_word_length: 平均词长（保留 2 位）.
        jieba_top_words: 高频词 Top-N（N=10，first_index 为 jieba token 序列
            中的首次出现序号；排序 (count DESC, first_index ASC)）.
    """

    jieba_total_words: int = 0
    jieba_unique_words: int = 0
    jieba_avg_word_length: float = 0.0
    jieba_top_words: list[WordFrequency] = Field(default_factory=list)


class StyleLLMAssessment(BaseModel):
    """LLM 深度分析板块（spec §2.7，Q1=C 可选）— LLM 判定 + 理由.

    Attributes:
        llm_verdict: LLM 输出的判定：likely_human / uncertain / likely_ai
            三值之一（与 AITraceVerdict 同值域；解析层校验）.
        reasoning: LLM 给出的判断理由（中文，截断 ≤ 2000 字符）.
        model: 实际使用的 LLM 模型.
        generated_at: LLM 判定生成时间（UTC）.
    """

    llm_verdict: str  # likely_human / uncertain / likely_ai（解析层校验）
    reasoning: str  # LLM 理由（截断 ≤ 2000 字符）
    model: str  # 实际使用的 LLM 模型
    generated_at: datetime  # UTC


class StyleReport(BaseModel):
    """风格检测报告（spec §2.6）— 只读计算的瞬态结果，不落库.

    Attributes:
        project_id: 所属项目 UUID.
        source: 输入来源标记: "manual" / "chapter:<id>" / "chapters:<id1>,<id2>".
        generated_at: 生成时间（UTC）.
        fingerprint: 风格指纹（12 项结构性统计）.
        ai_trace: AI 痕迹综合评估.
        lexical: 词汇分析（含 jieba 增强板块，Q2=C）.
        llm_assessment: 可选 LLM 深度分析板块（Q1=C）——未开启或 LLM 不可用
            时为 None（spec §2.7）.
        warnings: 分析过程中的可观测提示（不阻塞）.
    """

    project_id: uuid.UUID
    source: str  # 输入来源标记: "manual" / "chapter:<id>" / "chapters:<id1>,<id2>"
    generated_at: datetime  # UTC
    fingerprint: StyleFingerprint = Field(default_factory=StyleFingerprint)
    ai_trace: AITraceAssessment = Field(default_factory=AITraceAssessment)
    lexical: LexicalAnalysis = Field(default_factory=LexicalAnalysis)
    llm_assessment: StyleLLMAssessment | None = None  # 可选（Q1=C）: 未开启/不可用 → None（§2.7）
    warnings: list[str] = Field(default_factory=list)
