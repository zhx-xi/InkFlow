"""F16 风格检测算法纯函数单元测试 — 数值断言，不 Mock（核心测试面）.

测试范围（spec §5.2-§5.5）：预处理（去空白/句子切分/段落切分/标点统计/对话检测）、
token 化、风格指纹 12 项、AI 痕迹 8 特征启发式评分（含 verdict 阈值与 evidence 规则）、
词汇分析（含停用词）、jieba 精确分词增强板块（Q2=C）。

依据: specs/f16-style-service/spec.md §5（§5.2-§5.5）+ §6.2/§6.3 + §9 测试策略。

契约说明（RED 阶段设计的纯函数签名假设，实现阶段按此测试契约实现）:
- ``_preprocess(text) -> PreprocessStats``：返回属性可访问的统计快照（具名元组/数据类），
  含 clean/sentences/paragraphs/punct_count/exclam_count/ellipsis_count/dialogue_chars。
- ``_tokenize(text) -> list[str]``：零依赖正则词块（CJK 连续串 + 拉丁/数字连续串）。
- ``_analyze(text) -> AnalyzeStats``：一次预处理 + token 化（§5.1 要点 3/§5.7 伪代码），
  在 PreprocessStats 基础上追加 tokens/total_words/unique_words/avg_word_length/
  stopword_ratio/top_words（list[WordFrequency]）及派生 char_count/sentence_count/
  paragraph_count；三块分析共享同一快照（§6.1 同源）。
- ``_analyze_fingerprint(stats) -> StyleFingerprint`` / ``_analyze_ai_trace(stats) ->
  AITraceAssessment`` / ``_analyze_lexical(stats) -> LexicalAnalysis``（§5.3-§5.5）。
- ``_analyze_jieba(clean_text) -> JiebaAnalysis | None``（§5.5）：jieba.lcut 精确模式，
  去除纯标点 token（与正则词块同构——标点不构成词条）；空文本/无有效词条 → None。
- ``_verdict_for(ai_score) -> AITraceVerdict``（§6.2 阈值语义的纯函数分解）。
- 口径约定：句子切分基于原始文本（\\n 是句尾符，§5.2），句长按去空白后计；
  对话检测扫描 clean（与 char_count 同口径）；停用词过滤对两板块的 top_words/
  unique_words 生效（§5.5「与基础板块同规则」），total_words/avg_word_length/
  stopword_ratio 用原始 token。
"""

from __future__ import annotations

import pytest

from inkflow.domain.models.style import (
    AITraceAssessment,
    AITraceFeature,
    AITraceVerdict,
)
from inkflow.domain.services._style_analyzer import (
    _analyze,
    _analyze_ai_trace,
    _analyze_fingerprint,
    _analyze_jieba,
    _analyze_lexical,
    _preprocess,
    _tokenize,
    _verdict_for,
)

# 固定快照文本（禁止随机文本——快照断言范式，§9）
F1_TEXT = '林晚推开窗，夜色如墨。她低声说："三年了，我终究还是回来了。"窗外传来更鼓声，一下，两下……'
HUMAN_TEXT = (
    "林晚推开窗，夜色如墨！她低声说：“三年了，我终究还是回来了。”\n"
    "窗外传来更鼓声，一下，两下……夜风卷起落叶，沙沙作响？她裹紧大衣，快步走过长街，拐进小巷。\n"
    "推开吱呀作响的木门，屋里灯火通明，炉火正旺。她轻轻呼出一口气，望着窗外的月亮，忽然觉得一切都值得。"
    "夜已经很深了，远处的山影模糊成一片，她想起多年前的那个夏天，也是这样安静的夜晚，也是这样温柔的月光。"
    "她关上门，风从窗缝里钻进来，带着田野的气息。"
)
AI_TEXT = "他走了。" * 30  # 句长完全整齐 + 词汇复用集中的典型 AI 形状（120 字符）

J3_TEXT = "他推开了门，走了出去。她看了看表，轻轻叹了口气。"


def _words(top_words: list[object]) -> list[tuple[str, int, int]]:
    """把 WordFrequency 列表压成 (word, count, first_index) 元组便于断言."""
    return [(w.word, w.count, w.first_index) for w in top_words]


def _feature(assessment: AITraceAssessment, name: str) -> AITraceFeature:
    """按 feature 名取单个特征（§5.4 特征表 8 个 ASCII 稳定键）."""
    return next(f for f in assessment.features if f.feature == name)


class TestPreprocess:
    """预处理纯函数 _preprocess（§5.2）."""

    def test_whitespace_all_variants_removed(self) -> None:
        """去空白：空格/\\t/\\n/\\r/全角空格 \\u3000 全部移除（char_count 口径）."""
        stats = _preprocess("林晚 推开窗\t夜色如墨\r\n第二段\u3000来了")
        assert stats.clean == "林晚推开窗夜色如墨第二段来了"
        assert _analyze("林晚 推开窗\t夜色如墨\r\n第二段\u3000来了").char_count == 14

    def test_sentence_split_all_terminators(self) -> None:
        """句子切分覆盖全部句尾符（。！？!?…；; 及换行），过滤空串."""
        stats = _preprocess("甲。乙！丙？丁!戊?己…庚；辛;壬\n癸")
        assert stats.sentences == ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]

    def test_consecutive_terminators_no_empty_sentences(self) -> None:
        """连续句尾符不产生空句子."""
        stats = _preprocess("甲。。乙！！丙")
        assert stats.sentences == ["甲", "乙", "丙"]

    def test_ellipsis_run_no_empty_sentence(self) -> None:
        """「……」连续省略号合并为一个句尾符位置——不产生空句子."""
        stats = _preprocess("甲……乙")
        assert stats.sentences == ["甲", "乙"]
        assert _preprocess("甲…乙…丙").sentences == ["甲", "乙", "丙"]

    def test_newline_terminates_sentence(self) -> None:
        """换行是句尾符：无其他句尾符时按 \\n 切句."""
        stats = _preprocess("甲\n乙")
        assert stats.sentences == ["甲", "乙"]

    def test_paragraph_split_filters_empty(self) -> None:
        """段落切分按 \\n，过滤空段落."""
        stats = _preprocess("第一段\n\n第二段\n\n\n第三段")
        assert stats.paragraphs == ["第一段", "第二段", "第三段"]

    def test_paragraph_split_filters_whitespace_only(self) -> None:
        """strip 后为空的段落（空格/\\t 行）被过滤."""
        stats = _preprocess("甲\n   \n乙\n\t\n丙")
        assert stats.paragraphs == ["甲", "乙", "丙"]

    def test_punctuation_count_chinese_and_english(self) -> None:
        """标点统计覆盖中英文标点集合；感叹号与省略号单独计数."""
        stats = _preprocess("你好，世界！Hello,world!《引》【括】——…·「注」")
        assert stats.punct_count == 14
        assert stats.exclam_count == 2  # ！ + !
        assert stats.ellipsis_count == 1

    def test_ellipsis_run_counts_two_chars(self) -> None:
        """「……」计 2 次省略号（每个 … 字符一次）."""
        stats = _preprocess("甲……乙")
        assert stats.ellipsis_count == 2

    def test_dialogue_curly_double_quotes(self) -> None:
        """对话检测：“”配对，累计引号内字符数（含内部标点）."""
        stats = _preprocess("她说：“你好。”")
        assert stats.dialogue_chars == 3  # 你好。

    def test_dialogue_corner_quotes(self) -> None:
        """对话检测：「」配对."""
        stats = _preprocess("他心想：「原来如此。」")
        assert stats.dialogue_chars == 5  # 原来如此。

    def test_dialogue_ascii_quotes(self) -> None:
        """对话检测：ASCII 双引号 \" 配对."""
        stats = _preprocess('他说"你好"他说"再见"')
        assert stats.dialogue_chars == 4  # 你好 + 再见

    def test_dialogue_unmatched_quotes_alternate(self) -> None:
        """引号未配对（奇数个）时按出现顺序交替切换对话态."""
        stats = _preprocess("他说“你好”又说“再见")
        assert stats.dialogue_chars == 4  # 你好 + 再见（末尾“未闭合不报错）

    def test_dialogue_inner_punct_no_interference(self) -> None:
        """对话内嵌套标点（，！）不干扰对话态."""
        stats = _preprocess("“你好，世界！”她说。")
        assert stats.dialogue_chars == 6  # 你好，世界！


class TestTokenize:
    """零依赖正则词块 _tokenize（§5.2）."""

    def test_chinese_runs(self) -> None:
        """连续 CJK 字符序列为一个 token（「林晚推开窗」= 1 词块——spec §5.5/§9 口径；
        §5.2 示例「["林晚","推开窗","夜色如墨"]」与规则自相矛盾，以规则与
        §5.5「正则 1 词块 vs jieba 3 词」为准）."""
        assert _tokenize("林晚推开窗，夜色如墨。") == ["林晚推开窗", "夜色如墨"]

    def test_english_words(self) -> None:
        """连续拉丁字符序列为一个 token（spec §5.2 示例）."""
        assert _tokenize("She said: hello world") == ["She", "said", "hello", "world"]

    def test_numbers(self) -> None:
        """连续数字序列为一个 token."""
        assert _tokenize("价格 100 元 2024 年") == ["价格", "100", "元", "2024", "年"]

    def test_mixed_chinese_english(self) -> None:
        """中英混排文本各自成 token."""
        assert _tokenize("他今年 25 岁，She is 18。") == ["他今年", "25", "岁", "She", "is", "18"]

    def test_punct_and_whitespace_no_tokens(self) -> None:
        """标点与空白不构成 token（纯分隔符）."""
        assert _tokenize("！？，。(){}[]") == []

    def test_empty_text(self) -> None:
        """空文本 → 空 token 列表."""
        assert _tokenize("") == []

    def test_pure_punct_text(self) -> None:
        """纯标点文本 → 空 token 列表."""
        assert _tokenize("。。。") == []

    def test_duplicates_keep_order_and_first_index(self) -> None:
        """重复词保序保留；first_index 为首次出现下标（§2.1）.
        注：token 化作用于去空白后的 clean，词间分隔须用标点（空格会被去空白移除）."""
        tokens = _tokenize("风，雨，风，雪。")
        assert tokens == ["风", "雨", "风", "雪"]
        stats = _analyze("风，雨，风，雪。")
        assert _words(stats.top_words) == [("风", 2, 0), ("雨", 1, 1), ("雪", 1, 3)]


class TestAnalyze:
    """组合快照 _analyze（§5.1 要点 3：一次预处理 + token 化供三块共享）."""

    def test_combined_stats_snapshot(self) -> None:
        """固定文本的统计快照：预处理计数 + token 统计一次给出，报告内部同源."""
        stats = _analyze(F1_TEXT)
        assert stats.char_count == 46
        assert stats.sentence_count == 3
        assert stats.paragraph_count == 1
        assert stats.punct_count == 11
        assert stats.exclam_count == 0
        assert stats.ellipsis_count == 2
        assert stats.dialogue_chars == 13
        assert stats.tokens == [
            "林晚推开窗",
            "夜色如墨",
            "她低声说",
            "三年了",
            "我终究还是回来了",
            "窗外传来更鼓声",
            "一下",
            "两下",
        ]
        assert stats.total_words == 8
        assert stats.unique_words == 8
        assert stats.avg_word_length == pytest.approx(4.38, abs=0.005)
        assert stats.stopword_ratio == 0.0
        assert _words(stats.top_words) == [
            ("林晚推开窗", 1, 0),
            ("夜色如墨", 1, 1),
            ("她低声说", 1, 2),
            ("三年了", 1, 3),
            ("我终究还是回来了", 1, 4),
            ("窗外传来更鼓声", 1, 5),
            ("一下", 1, 6),
            ("两下", 1, 7),
        ]


class TestFingerprint:
    """风格指纹 _analyze_fingerprint（§5.3：12 项统计，快照断言范式）."""

    def test_snapshot_all_twelve_fields(self) -> None:
        """固定文本 → 全部 12 项数值（固定输入固定输出，快照断言基线）."""
        fp = _analyze_fingerprint(_analyze(F1_TEXT))
        assert fp.char_count == 46
        assert fp.sentence_count == 3
        assert fp.avg_sentence_length == pytest.approx(15.33, abs=0.005)
        assert fp.sentence_length_std == pytest.approx(3.27, abs=0.005)
        assert fp.paragraph_count == 1
        assert fp.avg_paragraph_length == 46.0
        assert fp.punctuation_density == pytest.approx(0.2391, abs=0.00005)
        assert fp.exclamation_density == 0.0
        assert fp.ellipsis_density == pytest.approx(0.0435, abs=0.00005)
        assert fp.dialogue_ratio == pytest.approx(0.2826, abs=0.00005)
        assert fp.vocabulary_richness == 1.0
        assert len(fp.top_words) == 8
        assert fp.top_words[0].word == "林晚推开窗"
        assert fp.top_words[0].first_index == 0

    def test_no_sentence_terminators_zero_mean_std(self) -> None:
        """无句尾符 → sentence_count=0 且均值/标准差为 0（+ warning 归服务层）."""
        fp = _analyze_fingerprint(_analyze("没有句尾符的文本内容"))
        assert fp.sentence_count == 0
        assert fp.avg_sentence_length == 0.0
        assert fp.sentence_length_std == 0.0

    def test_single_sentence_std_zero(self) -> None:
        """单句（n < 2）→ sentence_length_std=0."""
        fp = _analyze_fingerprint(_analyze("只有一句话。"))
        assert fp.sentence_count == 1
        assert fp.sentence_length_std == 0.0
        assert fp.avg_sentence_length == 6.0

    def test_no_tokens_ttr_zero(self) -> None:
        """total_words=0 → vocabulary_richness=0 且 top_words 为空."""
        fp = _analyze_fingerprint(_analyze("！！！"))
        assert fp.vocabulary_richness == 0.0
        assert fp.top_words == []

    def test_empty_text_all_zero(self) -> None:
        """空文本 → 12 项全部为 0 / 空列表."""
        fp = _analyze_fingerprint(_analyze(""))
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

    def test_paragraph_stats(self) -> None:
        """段落计数与平均段落长度（char_count / paragraph_count）."""
        fp = _analyze_fingerprint(_analyze("第一段。\n\n第二段！\n\n第三段？"))
        assert fp.paragraph_count == 3
        assert fp.avg_paragraph_length == 4.0
        assert fp.sentence_count == 3


class TestAITraceFeatures:
    """AI 痕迹 8 特征评分边界（§5.4 特征表，表驱动断言）."""

    def test_sentence_uniformity_perfectly_uniform_score_one(self) -> None:
        """句长完全整齐（cv=0）→ sentence_uniformity score=1.0."""
        trace = _analyze_ai_trace(_analyze("甲乙丙。甲乙丙。甲乙丙。甲乙丙。甲乙丙。"))
        assert _feature(trace, "sentence_uniformity").score == 1.0

    def test_sentence_uniformity_cv_ge_one_score_zero(self) -> None:
        """句长变异系数 ≥ 1.0 → sentence_uniformity score=0."""
        trace = _analyze_ai_trace(_analyze("一。一。一二三四五六七八九十。"))
        assert _feature(trace, "sentence_uniformity").score == 0.0

    def test_paragraph_uniformity_uniform_score_one(self) -> None:
        """段落长度完全整齐 → paragraph_uniformity score=1.0."""
        trace = _analyze_ai_trace(_analyze("甲乙丙\n甲乙丙\n甲乙丙"))
        assert _feature(trace, "paragraph_uniformity").score == 1.0

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("你好。", 1.0),  # d_ex=0 → (0.005-0)/0.005 = 1.0
            ("啊！", 0.0),  # d_ex=0.5 ≥ 0.005 → 0
        ],
    )
    def test_exclamation_density_low(self, text: str, expected: float) -> None:
        """感叹号密度边界：缺失 → 1.0（偏 AI），密集 → 0."""
        trace = _analyze_ai_trace(_analyze(text))
        assert _feature(trace, "exclamation_density_low").score == pytest.approx(
            expected, abs=0.005
        )

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("你好。", 1.0),  # d_el=0 → 1.0
            ("你好……", 0.0),  # d_el=0.5 ≥ 0.004 → 0
        ],
    )
    def test_ellipsis_density_low(self, text: str, expected: float) -> None:
        """省略号密度边界：缺失 → 1.0，充足 → 0."""
        trace = _analyze_ai_trace(_analyze(text))
        assert _feature(trace, "ellipsis_density_low").score == pytest.approx(expected, abs=0.005)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ('她说："你好。"他点点头。', 0.0),  # r=0.2308 ∈ [0.05, 0.75] 中位区间 → 0
            ("你好，世界。", 1.0),  # r=0 → 1.0
            ('"abcdefg""hijklmn"', 0.5556),  # r=14/18=0.7778 → (r-0.75)/0.05
            ('"abcdefghijklmnop"', 1.0),  # r=0.8889 → 截断到 1.0
        ],
    )
    def test_dialogue_ratio_extreme(self, text: str, expected: float) -> None:
        """对话占比边界：中位区间 → 0，极低/极高 → 1（含截断）."""
        trace = _analyze_ai_trace(_analyze(text))
        assert _feature(trace, "dialogue_ratio_extreme").score == pytest.approx(expected, abs=0.005)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("风，风，风，雨，雨，雨，雨。", 1.0),  # TTR=2/7=0.2857 ≤ 0.30 → 1.0
            ("甲，乙，丙，丁，戊，己，庚，甲，乙，丙。", 0.0),  # TTR=0.7 ≥ 0.60 → 0
            ("甲，乙，丙，丁，甲，乙，丙，丁，甲，乙。", 0.3333),  # TTR=0.4 中间值
        ],
    )
    def test_vocabulary_richness_low(self, text: str, expected: float) -> None:
        """词汇丰富度边界：TTR 低 → 1.0，高 → 0，中间线性（clamp((0.45-v)/0.15)）."""
        trace = _analyze_ai_trace(_analyze(text))
        assert _feature(trace, "vocabulary_richness_low").score == pytest.approx(
            expected, abs=0.005
        )

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # c = 0.15 → 1.0；c = 1/17 ≈ 0.0588 → 0.0；c = 0.1 → 0.6667
            (
                "甲，乙，丙，丁，戊，己，庚，辛，壬，癸，甲，乙，丙，丁，戊，己，庚，辛，甲，壬。",
                1.0,
            ),
            ("甲，乙，丙，丁，戊，己，庚，辛，壬，癸，子，丑，寅，卯，辰，巳，午。", 0.0),
            (
                "甲，乙，甲，丙，丁，戊，己，庚，辛，壬，癸，子，丑，寅，卯，辰，巳，午，未，申。",
                0.6667,
            ),
        ],
    )
    def test_top_word_concentration(self, text: str, expected: float) -> None:
        """最高频词占比边界：≥12% → 1.0，≤6% → 0，中间线性（clamp((c-0.06)/0.06)）."""
        trace = _analyze_ai_trace(_analyze(text))
        assert _feature(trace, "top_word_concentration").score == pytest.approx(expected, abs=0.005)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("你好，世界！你好？", 0.625),  # 3 种标点 → (8-3)/8
            ("你好世界", 1.0),  # 0 种 → 1.0
            ('你好，世界！？；："《》【】', 0.0),  # 10 种 ≥ 8 → 0
        ],
    )
    def test_punctuation_variety_low(self, text: str, expected: float) -> None:
        """标点种类边界：种类少 → 高（单调），≥ 8 种 → 0."""
        trace = _analyze_ai_trace(_analyze(text))
        assert _feature(trace, "punctuation_variety_low").score == pytest.approx(
            expected, abs=0.005
        )

    def test_no_word_tokens_neutral_half(self) -> None:
        """total_words=0 → 词汇相关特征中性 0.5（纯标点文本不误判），note 标注无有效词条."""
        trace = _analyze_ai_trace(_analyze("！！！"))
        vocab = _feature(trace, "vocabulary_richness_low")
        conc = _feature(trace, "top_word_concentration")
        assert vocab.score == 0.5
        assert conc.score == 0.5
        assert "无有效词条" in vocab.note
        assert "无有效词条" in conc.note


class TestAITraceAggregation:
    """ai_score 等权均值 / verdict 三档阈值 / evidence 规则（§5.4/§6.2/§6.3）."""

    def test_ai_score_equal_weight_mean(self) -> None:
        """ai_score = 8 特征得分等权均值（保留 4 位）；F1 文本各特征逐一断言."""
        trace = _analyze_ai_trace(_analyze(F1_TEXT))
        assert _feature(trace, "sentence_uniformity").score == pytest.approx(0.7667, abs=0.01)
        assert _feature(trace, "paragraph_uniformity").score == 1.0
        assert _feature(trace, "exclamation_density_low").score == 1.0
        assert _feature(trace, "ellipsis_density_low").score == 0.0
        assert _feature(trace, "dialogue_ratio_extreme").score == 0.0
        assert _feature(trace, "vocabulary_richness_low").score == 0.0
        assert _feature(trace, "top_word_concentration").score == 1.0
        assert _feature(trace, "punctuation_variety_low").score == pytest.approx(0.375, abs=0.005)
        assert trace.ai_score == pytest.approx(0.5177, abs=0.005)

    def test_verdict_likely_ai(self) -> None:
        """句式整齐 + 词汇复用集中文本 → ai_score 高 → likely_ai（≥ 0.65）."""
        trace = _analyze_ai_trace(_analyze(AI_TEXT))
        assert trace.ai_score == pytest.approx(0.9844, abs=0.005)
        assert trace.verdict is AITraceVerdict.LIKELY_AI

    def test_verdict_uncertain(self) -> None:
        """特征混合文本 → ai_score 中位（0.35, 0.65）→ uncertain."""
        trace = _analyze_ai_trace(_analyze(F1_TEXT))
        assert trace.verdict is AITraceVerdict.UNCERTAIN

    def test_verdict_likely_human(self) -> None:
        """句式波动大 + 标点丰富文本 → ai_score 低 → likely_human（≤ 0.35）."""
        trace = _analyze_ai_trace(_analyze(HUMAN_TEXT))
        assert trace.ai_score == pytest.approx(0.0938, abs=0.005)
        assert trace.verdict is AITraceVerdict.LIKELY_HUMAN

    @pytest.mark.parametrize(
        ("ai_score", "expected"),
        [
            (0.35, AITraceVerdict.LIKELY_HUMAN),  # 边界：≤ 0.35 → likely_human
            (0.36, AITraceVerdict.UNCERTAIN),
            (0.5, AITraceVerdict.UNCERTAIN),
            (0.64, AITraceVerdict.UNCERTAIN),
            (0.65, AITraceVerdict.LIKELY_AI),  # 边界：≥ 0.65 → likely_ai
        ],
    )
    def test_verdict_for_threshold_boundaries(
        self, ai_score: float, expected: AITraceVerdict
    ) -> None:
        """verdict 阈值三档边界（§6.2：0.35/0.65 闭区间归属）."""
        assert _verdict_for(ai_score) is expected

    def test_features_eight_sorted_ascending(self) -> None:
        """features 恒为 8 个、按 feature ASC 稳定排序（§6.3），note 非空."""
        trace = _analyze_ai_trace(_analyze(F1_TEXT))
        names = [f.feature for f in trace.features]
        assert len(names) == 8
        assert names == sorted(names)
        assert set(names) == {
            "sentence_uniformity",
            "paragraph_uniformity",
            "exclamation_density_low",
            "ellipsis_density_low",
            "dialogue_ratio_extreme",
            "vocabulary_richness_low",
            "top_word_concentration",
            "punctuation_variety_low",
        }
        assert all(f.note for f in trace.features)

    def test_evidence_short_text_uniformity_excluded(self) -> None:
        """过短文本（char_count<100）：uniformity 特征不进 evidence（§6.2）；
        evidence 只列 score≥0.5 特征按 (score DESC, feature ASC) 排序 + 阈值说明行."""
        trace = _analyze_ai_trace(_analyze(F1_TEXT))
        assert len(trace.evidence) == 3  # 感叹号 + 最高频词 + 阈值行（uniformity 被排除）
        assert trace.evidence[0].startswith("感叹号密度")
        assert trace.evidence[1].startswith("最高频词占比")
        assert "综合得分 0.52" in trace.evidence[2]
        assert "特征不明显" in trace.evidence[2]

    def test_evidence_all_features_selected_with_threshold(self) -> None:
        """全部特征 score≥0.5 → evidence = 8 条特征 + 末尾阈值说明行."""
        trace = _analyze_ai_trace(_analyze(AI_TEXT))
        assert len(trace.evidence) == 9
        assert "综合得分 0.98" in trace.evidence[-1]
        assert "倾向 AI 生成" in trace.evidence[-1]

    def test_evidence_empty_single_message(self) -> None:
        """无特征 score≥0.5 → 单条说明「各特征得分均低于 0.5，无明显 AI 特征」."""
        trace = _analyze_ai_trace(_analyze(HUMAN_TEXT))
        assert len(trace.evidence) == 1
        assert trace.evidence[0].startswith("各特征得分均低于 0.5")
        assert "综合得分 0.09" in trace.evidence[0]
        assert "倾向人类创作" in trace.evidence[0]

    def test_short_text_uniformity_note_sample_insufficient(self) -> None:
        """过短文本 uniformity 特征 note 加「样本不足」后缀；长文本不加."""
        short = _analyze_ai_trace(_analyze(F1_TEXT))
        assert "样本不足" in _feature(short, "sentence_uniformity").note
        assert "样本不足" in _feature(short, "paragraph_uniformity").note
        long = _analyze_ai_trace(_analyze(HUMAN_TEXT))
        assert "样本不足" not in _feature(long, "sentence_uniformity").note
        assert "样本不足" not in _feature(long, "paragraph_uniformity").note


class TestLexical:
    """词汇分析基础板块 _analyze_lexical（§5.5：正则词块，始终计算）."""

    def test_lexical_snapshot(self) -> None:
        """固定文本 → total/unique/avg/stopword_ratio/top_words 数值断言."""
        lexical = _analyze_lexical(_analyze(F1_TEXT))
        assert lexical.total_words == 8
        assert lexical.unique_words == 8
        assert lexical.avg_word_length == pytest.approx(4.38, abs=0.005)
        assert lexical.stopword_ratio == 0.0
        assert _words(lexical.top_words)[:3] == [
            ("林晚推开窗", 1, 0),
            ("夜色如墨", 1, 1),
            ("她低声说", 1, 2),
        ]

    def test_top_words_sorting_count_desc_first_index_asc(self) -> None:
        """top_words 排序 (count DESC, first_index ASC)——同频词按首次出现顺序（§6.3）."""
        lexical = _analyze_lexical(_analyze("风来，雨来，风来，雪来，风来。"))
        assert _words(lexical.top_words) == [("风来", 3, 0), ("雨来", 1, 1), ("雪来", 1, 3)]

    def test_stopword_ratio_and_filtered_top_words(self) -> None:
        """停用词命中（「他」「的」「了」）计入 stopword_ratio；top_words 过滤停用词
        （§5.5「过滤后才统计 top_words/unique_words，与基础板块同规则」）."""
        lexical = _analyze_lexical(_analyze("他，的，了，风，雨。"))
        assert lexical.total_words == 5
        assert lexical.stopword_ratio == 0.6  # 3/5
        assert lexical.avg_word_length == 1.0
        assert [w.word for w in lexical.top_words] == ["风", "雨"]

    def test_empty_text_all_zero_jieba_none(self) -> None:
        """空文本 → 全 0、top_words 空、jieba=None（§2.4/§5.5）."""
        lexical = _analyze_lexical(_analyze(""))
        assert lexical.total_words == 0
        assert lexical.unique_words == 0
        assert lexical.avg_word_length == 0.0
        assert lexical.stopword_ratio == 0.0
        assert lexical.top_words == []
        assert lexical.jieba is None

    def test_pure_punct_text_zero_jieba_none(self) -> None:
        """纯标点文本 → total_words=0、top_words 空、jieba=None."""
        lexical = _analyze_lexical(_analyze("！！！"))
        assert lexical.total_words == 0
        assert lexical.top_words == []
        assert lexical.stopword_ratio == 0.0
        assert lexical.jieba is None


class TestJieba:
    """jieba 精确分词增强板块 _analyze_jieba（§5.5，Q2=C——jieba 0.42.1 快照断言）."""

    def test_jieba_snapshot(self) -> None:
        """固定中文文本 → jieba 统计断言（jieba_total/unique/avg/top_words 排序）."""
        jieba_stats = _analyze_jieba("林晚推开窗，夜色如墨。")
        assert jieba_stats is not None
        assert jieba_stats.jieba_total_words == 5
        assert jieba_stats.jieba_unique_words == 5
        assert jieba_stats.jieba_avg_word_length == pytest.approx(1.8, abs=0.005)
        assert _words(jieba_stats.jieba_top_words) == [
            ("林晚", 1, 0),
            ("推开", 1, 1),
            ("窗", 1, 2),
            ("夜色", 1, 3),
            ("如墨", 1, 4),
        ]

    def test_jieba_finer_granularity_than_regex_block(self) -> None:
        """「林晚推开窗」正则 1 词块 vs jieba 3 词（spec §5.5 对比断言）."""
        assert _tokenize("林晚推开窗") == ["林晚推开窗"]
        jieba_stats = _analyze_jieba("林晚推开窗")
        assert jieba_stats is not None
        assert jieba_stats.jieba_total_words == 3
        assert [w.word for w in jieba_stats.jieba_top_words] == ["林晚", "推开", "窗"]

    def test_jieba_segments_function_words_and_filters_stopwords(self) -> None:
        """jieba 可切出「了」「他」「她」等单字功能词（正则词块不产生）；
        这些词被 _STOPWORDS 过滤后不进 jieba_top_words（§5.5/§9）."""
        jieba_stats = _analyze_jieba(J3_TEXT)
        assert jieba_stats is not None
        assert jieba_stats.jieba_total_words == 15  # 含 了×4/他/她
        assert jieba_stats.jieba_avg_word_length == pytest.approx(1.33, abs=0.005)
        words = [w.word for w in jieba_stats.jieba_top_words]
        assert words == ["推开", "门", "走", "出去", "看", "看表", "轻轻", "叹", "口气"]
        assert "了" not in words
        assert "他" not in words
        assert "她" not in words
        # 同文本基础板块：4 个连续串词块（对比 jieba 15 词）
        assert _analyze_lexical(_analyze(J3_TEXT)).total_words == 4

    def test_jieba_top_words_sorting(self) -> None:
        """jieba_top_words 排序 (count DESC, first_index ASC)，first_index 为
        jieba token 序列首次出现序号（§2.5）."""
        jieba_stats = _analyze_jieba("风来，雨来，风来，雪来，风来。")
        assert jieba_stats is not None
        assert _words(jieba_stats.jieba_top_words) == [
            ("风来", 3, 0),
            ("雨来", 1, 1),
            ("雪来", 1, 3),
        ]

    def test_jieba_same_source_consistency(self) -> None:
        """jieba 板块与基础板块同源文本一致性（同一 clean_text，§9）：
        同一文本两套统计并存且数值不同（21 vs 8）；停用词不进 top."""
        stats = _analyze(F1_TEXT)
        lexical = _analyze_lexical(stats)
        assert lexical.total_words == 8
        assert lexical.jieba is not None
        assert lexical.jieba.jieba_total_words == 21
        assert lexical.jieba.jieba_avg_word_length == pytest.approx(1.67, abs=0.005)
        words = [w.word for w in lexical.jieba.jieba_top_words]
        assert len(words) == 10
        assert words[0] == "林晚"
        assert "了" not in words

    def test_jieba_empty_text_none(self) -> None:
        """空文本 → jieba=None（§5.5 空文本语义）."""
        assert _analyze_jieba("") is None

    def test_jieba_pure_punct_none(self) -> None:
        """纯标点文本（无有效词条）→ jieba=None（§9：纯标点文本 → jieba=None）."""
        assert _analyze_jieba("！！！") is None
