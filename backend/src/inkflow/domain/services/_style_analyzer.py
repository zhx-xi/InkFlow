"""F16 风格检测算法纯函数层（spec §5.2-§5.5）— 预处理 / token 化 / 风格指纹 /
AI 痕迹 8 特征启发式评分 / 词汇分析（含 jieba 精确分词增强，Q2=C）.

镜像 _chunking.py 先例：全部为模块级纯函数，无 I/O、无副作用、严格幂等
（同文本同输出，快照断言友好）；仅依赖标准库（re / statistics）与 jieba
（Q2=C 新增运行时依赖，词典版本由 uv.lock 锁定保证确定性），不 import
任何框架 / infrastructure（ADR-002/015：domain 层零框架 import）。

函数契约以 tests/unit/test_style_analyzer.py 为准（RED 测试即契约）:
- _preprocess(text) -> PreprocessStats：预处理统计快照（去空白 / 句子切分 /
  段落切分 / 标点统计 / 对话检测）
- _tokenize(text) -> list[str]：零依赖正则词块（CJK 连续串 + 拉丁/数字串）
- _analyze(text) -> AnalyzeStats：一次预处理 + token 化，三块分析共享同一快照
- _analyze_fingerprint(stats) -> StyleFingerprint：风格指纹 12 项统计（§5.3）
- _analyze_ai_trace(stats) -> AITraceAssessment：AI 痕迹 8 特征评分（§5.4）
- _analyze_lexical(stats) -> LexicalAnalysis：词汇分析基础板块（§5.5）
- _analyze_jieba(clean_text) -> JiebaAnalysis | None：jieba 精确分词增强板块
- _verdict_for(ai_score) -> AITraceVerdict：三档判定阈值（§6.2）

数值精度统一由本层四舍五入保证（保留位数见 spec §5.3/§5.4 表）。
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

import jieba

from inkflow.domain.models.style import (
    AITraceAssessment,
    AITraceFeature,
    AITraceVerdict,
    JiebaAnalysis,
    LexicalAnalysis,
    StyleFingerprint,
    WordFrequency,
)

# ---------------------------------------------------------------------------
# 代码常量（spec §5.2/§5.4/§5.5 —— 阈值/停用词表/高频词 N 均为代码常量，YAGNI）
# ---------------------------------------------------------------------------

# 去空白字符集合（空格 / 制表 / 换行 / 回车 / 全角空格 \u3000，spec §5.2）
_WHITESPACE_RE = re.compile(r"[ \t\n\r\u3000]+")

# 句尾符集合：。！？!?…；; 及换行（spec §5.2 句子切分）
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?…；;\n]+")

# token 化正则（spec §5.2）: 连续 CJK 字符序列 或 连续拉丁/数字序列
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+")

# 标点字符集合（中文 + 英文，spec §5.2 标点统计）——「——」为两个 — 字符
_CHINESE_PUNCT = "，。！？；：、“”‘’（）《》【】—…·「」"
_ENGLISH_PUNCT = ",.;:!?\"'()[]{}"
_PUNCT_CHARS = frozenset(_CHINESE_PUNCT + _ENGLISH_PUNCT)

# 对话引号集合（“ ” 「 」 "）——遇引号切换对话态，未配对时交替切换（§5.2）
_QUOTE_CHARS = frozenset('“”「」"')

# 高频词 Top-N（spec §5.3/§5.5，N=10 代码常量）
_TOP_WORDS_N = 10

# AI 痕迹评分阈值（spec §5.4 特征表经验常量）
_EXCLAM_THRESHOLD = 0.005  # 感叹号密度阈值
_ELLIPSIS_THRESHOLD = 0.004  # 省略号密度阈值
_DIALOGUE_LOW = 0.05  # 对话占比中位区间下界
_DIALOGUE_HIGH = 0.75  # 对话占比中位区间上界
_TTR_THRESHOLD = 0.45  # 词汇丰富度阈值
_TTR_RANGE = 0.15  # 词汇丰富度线性区间
_CONCENTRATION_THRESHOLD = 0.06  # 最高频词占比阈值
_CONCENTRATION_RANGE = 0.06  # 最高频词占比线性区间
_PUNCT_VARIETY_TARGET = 8  # 标点种类目标值

# verdict 三档阈值（spec §6.2）——0.35/0.65 闭区间归属
_VERDICT_THRESHOLD_LOW = 0.35
_VERDICT_THRESHOLD_HIGH = 0.65

# evidence 规则（spec §2.3/§5.4）——score ≥ 0.5 的特征入选
_EVIDENCE_SCORE_THRESHOLD = 0.5

# 过短文本阈值（spec §6.2）——char_count < 100 时 uniformity 特征失真
_SHORT_TEXT_CHARS = 100

# 过短文本时失真且不进 evidence 的特征（spec §5.4 边界语义/§6.2）
_UNIFORMITY_FEATURES = ("sentence_uniformity", "paragraph_uniformity")

# verdict 中文映射（spec §4.3/§6.2）
_VERDICT_CN: dict[AITraceVerdict, str] = {
    AITraceVerdict.LIKELY_HUMAN: "倾向人类创作",
    AITraceVerdict.UNCERTAIN: "特征不明显",
    AITraceVerdict.LIKELY_AI: "倾向 AI 生成",
}

# 停用词表（spec §5.5 代码常量——常用中文虚词/高频功能词）
_STOPWORDS: frozenset[str] = frozenset(
    {
        "的",
        "了",
        "是",
        "在",
        "我",
        "你",
        "他",
        "她",
        "它",
        "我们",
        "你们",
        "他们",
        "着",
        "过",
        "不",
        "也",
        "都",
        "就",
        "说",
        "道",
        "啊",
        "呢",
        "吧",
        "吗",
        "很",
        "太",
        "又",
        "这",
        "那",
        "个",
        "与",
        "和",
        "及",
        "或",
        "但",
        "而",
        "却",
        "还",
        "再",
        "只",
        "被",
        "把",
        "让",
        "对",
        "向",
        "从",
        "到",
        "于",
        "以",
        "之",
        "其",
        "等",
        "有",
        "为",
        "已经",
        "没有",
        "一个",
        "自己",
        "时候",
        "现在",
    }
)


# ---------------------------------------------------------------------------
# 统计快照（数据类，属性可访问）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreprocessStats:
    """预处理统计快照（spec §5.2）— _preprocess 输出.

    Attributes:
        clean: 去空白文本（char_count 口径 = len(clean)）.
        sentences: 句子列表（按句尾符切分，过滤空串，不含句尾符）.
        sentence_lengths: 各句子去空白后的字符长度（与 sentences 一一对应，
            供句长标准差/变异系数计算，spec §5.3 #4）.
        paragraphs: 段落列表（按 \\n 切分，过滤空段落）.
        punct_count: 标点字符数（中文 + 英文标点集合）.
        exclam_count: 感叹号数（！!）.
        ellipsis_count: 省略号数（…，每个 … 字符计 1 次）.
        dialogue_chars: 对话引号内字符数（引号配对扫描）.
    """

    clean: str
    sentences: list[str]
    sentence_lengths: list[int]
    paragraphs: list[str]
    punct_count: int
    exclam_count: int
    ellipsis_count: int
    dialogue_chars: int


@dataclass(frozen=True)
class AnalyzeStats(PreprocessStats):
    """组合统计快照（spec §5.1 要点 3）— 一次预处理 + token 化供三块共享.

    在 PreprocessStats 基础上追加 token 统计（tokens/total_words/unique_words/
    avg_word_length/stopword_ratio/top_words）及派生计数（char_count/
    sentence_count/paragraph_count）。
    """

    char_count: int
    sentence_count: int
    paragraph_count: int
    tokens: list[str]
    total_words: int
    unique_words: int
    avg_word_length: float
    stopword_ratio: float
    top_words: list[WordFrequency]


# ---------------------------------------------------------------------------
# 预处理（spec §5.2）
# ---------------------------------------------------------------------------


def _strip_whitespace(text: str) -> str:
    """移除全部空白字符（空格/\\t/\\n/\\r/全角空格 \\u3000）."""
    return _WHITESPACE_RE.sub("", text)


def _split_sentences(text: str) -> tuple[list[str], list[int]]:
    """按句尾符集合切分句子，返回（句子列表，去空白句长列表）.

    句尾符: 。！？!?…；; 及换行；连续句尾符合并为一个句尾符位置
    （「……」不产生空句子），空串过滤。
    """
    sentences: list[str] = []
    lengths: list[int] = []
    pos = 0
    matched = False
    for match in _SENTENCE_SPLIT_RE.finditer(text):
        matched = True
        segment = text[pos : match.start()]
        if segment:
            sentences.append(segment)
            lengths.append(len(_strip_whitespace(segment)))
        pos = match.end()
    if matched:
        # 仅当文本含至少一个句尾符时，末尾无句尾符的残余才计为句子；
        # 全文无句尾符 → sentence_count = 0（spec §7 边界表）
        tail = text[pos:]
        if tail:
            sentences.append(tail)
            lengths.append(len(_strip_whitespace(tail)))
    return sentences, lengths


def _count_dialogue_chars(text: str) -> int:
    """累计对话引号内的字符数（spec §5.2 对话检测）.

    引号集合: “ ” 「 」 "；遇引号切换对话态，未配对（奇数个）时按出现顺序
    交替切换（不报错）；引号本身与对话外字符不计入；对话内嵌套标点不干扰。
    """
    in_dialogue = False
    count = 0
    for ch in text:
        if ch in _QUOTE_CHARS:
            in_dialogue = not in_dialogue
        elif in_dialogue:
            count += 1
    return count


def _preprocess(text: str) -> PreprocessStats:
    """文本预处理（spec §5.2）— 去空白 / 句子切分 / 段落切分 / 标点统计 / 对话检测.

    Args:
        text: 原始文本（可含空白与换行）.

    Returns:
        PreprocessStats 统计快照（clean 为去空白文本，char_count 口径）.
    """
    clean = _strip_whitespace(text)
    sentences, sentence_lengths = _split_sentences(text)
    paragraphs = [p for p in text.split("\n") if _strip_whitespace(p)]
    punct_count = sum(1 for ch in clean if ch in _PUNCT_CHARS)
    exclam_count = clean.count("！") + clean.count("!")
    ellipsis_count = clean.count("…")
    dialogue_chars = _count_dialogue_chars(clean)
    return PreprocessStats(
        clean=clean,
        sentences=sentences,
        sentence_lengths=sentence_lengths,
        paragraphs=paragraphs,
        punct_count=punct_count,
        exclam_count=exclam_count,
        ellipsis_count=ellipsis_count,
        dialogue_chars=dialogue_chars,
    )


# ---------------------------------------------------------------------------
# token 化与高频词（spec §5.2/§5.5）
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """零依赖正则词块 token 化（spec §5.2）.

    规则: 连续 CJK 字符序列 [\\u4e00-\\u9fff]+ 或连续拉丁/数字序列
    [A-Za-z0-9]+ 各为一个 token；标点、空白、其他字符为分隔符不构成 token。

    Args:
        text: 待切分文本（通常为去空白后的 clean）.

    Returns:
        token 列表（保序含重复，first_index 由列表下标确定）.
    """
    return _TOKEN_RE.findall(text)


def _build_top_words(
    tokens: list[str], stopwords: frozenset[str], top_n: int
) -> list[WordFrequency]:
    """高频词 Top-N（spec §2.1/§6.3）.

    停用词过滤后才统计（§5.5「与基础板块同规则」）；排序 (count DESC,
    first_index ASC)——first_index 为 token 在原始序列中的首次出现序号
    （过滤前的下标，§2.1/§2.5 语义）.
    """
    counts: dict[str, int] = {}
    first: dict[str, int] = {}
    for index, token in enumerate(tokens):
        if token in stopwords:
            continue
        counts[token] = counts.get(token, 0) + 1
        first.setdefault(token, index)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], first[item[0]]))
    return [
        WordFrequency(word=word, count=count, first_index=first[word])
        for word, count in ranked[:top_n]
    ]


def _analyze(text: str) -> AnalyzeStats:
    """组合统计快照（spec §5.1 要点 3/§5.7）— 一次预处理 + token 化.

    fingerprint / ai_trace / lexical 三块共享同一快照（§6.1 内部自洽）；
    停用词过滤对 top_words/unique_words 生效，total_words/avg_word_length/
    stopword_ratio 用原始 token（测试契约口径）.
    """
    pre = _preprocess(text)
    tokens = _tokenize(pre.clean)
    total_words = len(tokens)
    unique_words = len({t for t in tokens if t not in _STOPWORDS})
    avg_word_length = round(sum(len(t) for t in tokens) / total_words, 2) if total_words else 0.0
    stopword_ratio = (
        round(sum(1 for t in tokens if t in _STOPWORDS) / total_words, 4) if total_words else 0.0
    )
    top_words = _build_top_words(tokens, _STOPWORDS, _TOP_WORDS_N)
    return AnalyzeStats(
        clean=pre.clean,
        sentences=pre.sentences,
        sentence_lengths=pre.sentence_lengths,
        paragraphs=pre.paragraphs,
        punct_count=pre.punct_count,
        exclam_count=pre.exclam_count,
        ellipsis_count=pre.ellipsis_count,
        dialogue_chars=pre.dialogue_chars,
        char_count=len(pre.clean),
        sentence_count=len(pre.sentences),
        paragraph_count=len(pre.paragraphs),
        tokens=tokens,
        total_words=total_words,
        unique_words=unique_words,
        avg_word_length=avg_word_length,
        stopword_ratio=stopword_ratio,
        top_words=top_words,
    )


# ---------------------------------------------------------------------------
# 风格指纹（spec §5.3 — 12 项结构性统计）
# ---------------------------------------------------------------------------


def _analyze_fingerprint(stats: AnalyzeStats) -> StyleFingerprint:
    """风格指纹 12 项统计（spec §5.3 表）.

    口径: 均值/密度分母为 char_count（去空白字符数）；句长标准差为总体
    标准差（n 分母，statistics.pstdev）；sentence_count < 2 → std 0；
    除数为 0 时对应项取 0.0；全部数值保留 spec 指定位数。
    """
    char_count = stats.char_count
    sentence_count = stats.sentence_count
    paragraph_count = stats.paragraph_count
    total_words = stats.total_words
    avg_sentence_length = round(char_count / sentence_count, 2) if sentence_count else 0.0
    sentence_length_std = (
        round(statistics.pstdev(stats.sentence_lengths), 2) if sentence_count >= 2 else 0.0
    )
    avg_paragraph_length = round(char_count / paragraph_count, 2) if paragraph_count else 0.0
    punctuation_density = round(stats.punct_count / char_count, 4) if char_count else 0.0
    exclamation_density = round(stats.exclam_count / char_count, 4) if char_count else 0.0
    ellipsis_density = round(stats.ellipsis_count / char_count, 4) if char_count else 0.0
    dialogue_ratio = round(stats.dialogue_chars / char_count, 4) if char_count else 0.0
    vocabulary_richness = round(stats.unique_words / total_words, 4) if total_words else 0.0
    return StyleFingerprint(
        char_count=char_count,
        sentence_count=sentence_count,
        avg_sentence_length=avg_sentence_length,
        sentence_length_std=sentence_length_std,
        paragraph_count=paragraph_count,
        avg_paragraph_length=avg_paragraph_length,
        punctuation_density=punctuation_density,
        exclamation_density=exclamation_density,
        ellipsis_density=ellipsis_density,
        dialogue_ratio=dialogue_ratio,
        vocabulary_richness=vocabulary_richness,
        top_words=stats.top_words,
    )


# ---------------------------------------------------------------------------
# AI 痕迹检测（spec §5.4 — 8 特征启发式评分）
# ---------------------------------------------------------------------------


def _clamp01(value: float) -> float:
    """将数值截断到 [0, 1] 区间."""
    return max(0.0, min(1.0, value))


def _sentence_uniformity(stats: AnalyzeStats, short: bool) -> AITraceFeature:
    """句长整齐度特征（§5.4）— cv = 句长变异系数，score = 1 - min(cv, 1)."""
    if stats.sentence_count >= 2:
        mean_len = statistics.fmean(stats.sentence_lengths)
        cv = statistics.pstdev(stats.sentence_lengths) / mean_len if mean_len > 0 else 0.0
    else:
        cv = 0.0
    score = 1.0 - min(cv, 1.0)
    label = "低" if cv < 0.5 else "正常"
    shape = "偏整齐" if cv < 0.5 else "波动正常"
    note = f"句长变异系数 {cv:.2f}（{label}）——句式{shape}"
    if short:
        note += "（样本不足）"
    return AITraceFeature(feature="sentence_uniformity", value=cv, score=score, note=note)


def _paragraph_uniformity(stats: AnalyzeStats, short: bool) -> AITraceFeature:
    """段落整齐度特征（§5.4）— cv_p = 段落长度变异系数."""
    lengths = [len(_strip_whitespace(p)) for p in stats.paragraphs]
    if len(lengths) >= 2:
        mean_len = statistics.fmean(lengths)
        cv = statistics.pstdev(lengths) / mean_len if mean_len > 0 else 0.0
    else:
        cv = 0.0
    score = 1.0 - min(cv, 1.0)
    shape = "偏均匀" if cv < 0.5 else "长短有致"
    note = f"段落长度变异系数 {cv:.2f}——段落{shape}"
    if short:
        note += "（样本不足）"
    return AITraceFeature(feature="paragraph_uniformity", value=cv, score=score, note=note)


def _exclamation_density_low(stats: AnalyzeStats) -> AITraceFeature:
    """感叹号缺失特征（§5.4）— d_ex 低于 0.005 偏 AI."""
    d_ex = stats.exclam_count / stats.char_count if stats.char_count else 0.0
    score = _clamp01((_EXCLAM_THRESHOLD - d_ex) / _EXCLAM_THRESHOLD)
    low = d_ex < _EXCLAM_THRESHOLD
    note = (
        f"感叹号密度 {d_ex:.4f}（{'低于' if low else '达到'} {_EXCLAM_THRESHOLD}）"
        f"——{'缺少情绪标点' if low else '情绪表达正常'}"
    )
    return AITraceFeature(feature="exclamation_density_low", value=d_ex, score=score, note=note)


def _ellipsis_density_low(stats: AnalyzeStats) -> AITraceFeature:
    """省略号缺失特征（§5.4）— d_el 低于 0.004 偏 AI."""
    d_el = stats.ellipsis_count / stats.char_count if stats.char_count else 0.0
    score = _clamp01((_ELLIPSIS_THRESHOLD - d_el) / _ELLIPSIS_THRESHOLD)
    low = d_el < _ELLIPSIS_THRESHOLD
    note = (
        f"省略号密度 {d_el:.4f}（{'低于' if low else '达到'} {_ELLIPSIS_THRESHOLD}）"
        f"——{'缺少省略号' if low else '省略号使用正常'}"
    )
    return AITraceFeature(feature="ellipsis_density_low", value=d_el, score=score, note=note)


def _dialogue_ratio_extreme(stats: AnalyzeStats) -> AITraceFeature:
    """对话占比极端特征（§5.4）— r ∈ [0.05, 0.75] 中位区间 → 0."""
    r = stats.dialogue_chars / stats.char_count if stats.char_count else 0.0
    score = _clamp01(
        max((_DIALOGUE_LOW - r) / _DIALOGUE_LOW, (r - _DIALOGUE_HIGH) / _DIALOGUE_LOW, 0.0)
    )
    if _DIALOGUE_LOW <= r <= _DIALOGUE_HIGH:
        state, effect = "位于中位区间", "无明显特征"
    else:
        state, effect = ("过低" if r < _DIALOGUE_LOW else "过高"), "对话分布异常"
    note = f"对话占比 {r:.4f}（{state}）——{effect}"
    return AITraceFeature(feature="dialogue_ratio_extreme", value=r, score=score, note=note)


def _vocabulary_richness_low(stats: AnalyzeStats) -> AITraceFeature:
    """词汇丰富度低特征（§5.4）— TTR 低于 0.45 偏 AI；无有效词条中性 0.5."""
    if stats.total_words == 0:
        return AITraceFeature(
            feature="vocabulary_richness_low",
            value=0.0,
            score=0.5,
            note="词汇丰富度 0.0000（无有效词条）——特征中性",
        )
    v = stats.unique_words / stats.total_words
    score = _clamp01((_TTR_THRESHOLD - v) / _TTR_RANGE)
    low = v < _TTR_THRESHOLD
    note = (
        f"词汇丰富度 {v:.4f}（{'低于' if low else '达到'} {_TTR_THRESHOLD}）"
        f"——{'词汇复用偏高' if low else '词汇多样'}"
    )
    return AITraceFeature(feature="vocabulary_richness_low", value=v, score=score, note=note)


def _top_word_concentration(stats: AnalyzeStats) -> AITraceFeature:
    """最高频词集中特征（§5.4）— c = top1/total 超过 0.06 偏 AI."""
    if stats.total_words == 0:
        return AITraceFeature(
            feature="top_word_concentration",
            value=0.0,
            score=0.5,
            note="最高频词占比 0.0000（无有效词条）——特征中性",
        )
    top1_count = stats.top_words[0].count if stats.top_words else 0
    c = top1_count / stats.total_words
    score = _clamp01((c - _CONCENTRATION_THRESHOLD) / _CONCENTRATION_RANGE)
    over = c > _CONCENTRATION_THRESHOLD
    note = (
        f"最高频词占比 {c:.4f}（{'超过' if over else '低于'} {_CONCENTRATION_THRESHOLD}）"
        f"——{'集中于单一词汇' if over else '高频词分布均匀'}"
    )
    return AITraceFeature(feature="top_word_concentration", value=c, score=score, note=note)


def _punctuation_variety_low(stats: AnalyzeStats) -> AITraceFeature:
    """标点种类少特征（§5.4）— n_p 少于 8 种偏 AI."""
    n_p = len({ch for ch in stats.clean if ch in _PUNCT_CHARS})
    score = _clamp01((_PUNCT_VARIETY_TARGET - n_p) / _PUNCT_VARIETY_TARGET)
    low = n_p < _PUNCT_VARIETY_TARGET
    note = (
        f"标点种类 {n_p}（{'少于' if low else '达到'} {_PUNCT_VARIETY_TARGET} 种）"
        f"——{'标点单调' if low else '标点丰富'}"
    )
    return AITraceFeature(
        feature="punctuation_variety_low", value=float(n_p), score=score, note=note
    )


def _verdict_for(ai_score: float) -> AITraceVerdict:
    """verdict 三档阈值（spec §6.2）— ≤0.35 likely_human / (0.35,0.65) uncertain / ≥0.65 likely_ai.

    Args:
        ai_score: 综合 AI 得分（0-1）.

    Returns:
        对应判定结论（边界值 0.35/0.65 分别归属 human/ai 闭区间）.
    """
    if ai_score <= _VERDICT_THRESHOLD_LOW:
        return AITraceVerdict.LIKELY_HUMAN
    if ai_score < _VERDICT_THRESHOLD_HIGH:
        return AITraceVerdict.UNCERTAIN
    return AITraceVerdict.LIKELY_AI


def _analyze_ai_trace(stats: AnalyzeStats) -> AITraceAssessment:
    """AI 痕迹综合评估（spec §5.4/§6.2/§6.3）.

    - ai_score = 8 特征得分等权均值（保留 4 位）
    - features 恒 8 个、按 feature ASC 稳定排序
    - evidence: score ≥ 0.5 的特征 note 按 (score DESC, feature ASC) 排序 +
      末尾阈值说明行；过短文本 uniformity 特征不进 evidence；无入选 → 单条说明
    """
    short = stats.char_count < _SHORT_TEXT_CHARS
    features = [
        _sentence_uniformity(stats, short),
        _paragraph_uniformity(stats, short),
        _exclamation_density_low(stats),
        _ellipsis_density_low(stats),
        _dialogue_ratio_extreme(stats),
        _vocabulary_richness_low(stats),
        _top_word_concentration(stats),
        _punctuation_variety_low(stats),
    ]
    features.sort(key=lambda f: f.feature)
    ai_score = round(statistics.fmean(f.score for f in features), 4)
    verdict = _verdict_for(ai_score)
    selected = [f for f in features if f.score >= _EVIDENCE_SCORE_THRESHOLD]
    if short:
        selected = [f for f in selected if f.feature not in _UNIFORMITY_FEATURES]
    selected.sort(key=lambda f: (-f.score, f.feature))
    verdict_cn = _VERDICT_CN[verdict]
    if selected:
        evidence = [f.note for f in selected] + [f"（综合得分 {ai_score:.2f} → {verdict_cn}）"]
    else:
        evidence = [
            f"各特征得分均低于 0.5，无明显 AI 特征（综合得分 {ai_score:.2f} → {verdict_cn}）"
        ]
    return AITraceAssessment(
        ai_score=ai_score,
        verdict=verdict,
        features=features,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# 词汇分析（spec §5.5 — 基础板块 + jieba 增强板块 Q2=C）
# ---------------------------------------------------------------------------


def _analyze_lexical(stats: AnalyzeStats) -> LexicalAnalysis:
    """词汇分析基础板块（spec §5.5）— 正则词块统计，始终计算.

    jieba 增强板块与基础板块同源（同一 clean_text）；空文本/无有效词条时
    jieba=None（spec §2.4/§5.5）.
    """
    return LexicalAnalysis(
        total_words=stats.total_words,
        unique_words=stats.unique_words,
        top_words=stats.top_words,
        avg_word_length=stats.avg_word_length,
        stopword_ratio=stats.stopword_ratio,
        jieba=_analyze_jieba(stats.clean),
    )


def _analyze_jieba(clean_text: str) -> JiebaAnalysis | None:
    """jieba 精确分词增强板块（spec §5.5，Q2=C）— 与正则词块同构统计.

    规则: jieba.lcut 精确模式（默认词典，无网络依赖）；去除纯标点 token
    （与正则词块同构——标点不构成词条）；停用词过滤对 jieba_top_words/
    jieba_unique_words 生效；first_index 为 jieba token 序列首次出现序号；
    空文本/无有效词条 → None。jieba 首次调用构建词典缓存（约 0.4s，正常）。

    Args:
        clean_text: 去空白后的文本（与基础板块同一 clean_text）.

    Returns:
        JiebaAnalysis 统计；空文本/无有效词条返回 None.
    """
    tokens = [t for t in jieba.lcut(clean_text) if _TOKEN_RE.fullmatch(t)]
    if not tokens:
        return None
    total = len(tokens)
    unique = len({t for t in tokens if t not in _STOPWORDS})
    avg = round(sum(len(t) for t in tokens) / total, 2)
    top = _build_top_words(tokens, _STOPWORDS, _TOP_WORDS_N)
    return JiebaAnalysis(
        jieba_total_words=total,
        jieba_unique_words=unique,
        jieba_avg_word_length=avg,
        jieba_top_words=top,
    )
