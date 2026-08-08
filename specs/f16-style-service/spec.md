# F16: 风格检测服务 (style_service) — 功能规格

> **Spec 版本**: 1.1 | **日期**: 2026-08-02 | **依据**: PRD v2.1 §6.2 P1-08, Constitution P1-P6, ADR-012/015/018/019/025
> **Spec 变更**: v1.1 — 用户拍板 Q1=选项 C（综合：确定性 8 特征为主 + LLM 深度分析可选，报告加 llm_assessment 板块）/ Q2=选项 C（综合：零依赖正则词块为主 + jieba 精确分词增强，jieba 新增运行时依赖）/ Q3=选项 B（门面 + 独立入口，v1.0 已按此设计，仅标记确认）
> **所属阶段**: Phase 2 — 创作工具链（0.2.0 里程碑**第八个**模块，估算 4.5-6.5 人天（Q1 LLM 深度分析 +2-2.5 + Q2 jieba 增强 +0.5-1；v1.0 的 2-3 已含 Q3=B））
> **关联 Issues**: [#46](https://github.com/zhx-xi/InkFlow/issues/46)
> **依赖**: F1 ✅（项目存在性校验）；F2 ✅（章节读取——chapter_ids 模式）；F14 ✅（**STYLE 槽位注册 handler**：接口零变更，F14 §12 已承诺「F16 落地后仅需注册 handler」——本 spec 兑现该承诺并同步修订 F14 spec 的 STYLE 占位表述，见 §8.2）；F5 ✅（LLM 深度分析装配——**可选依赖**：LLMClientProtocol + PromptManager 构造注入，仅 llm_analysis=true 时调用；主体确定性分析不依赖 F5）
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md) (模块化单体), [ADR-002](../../adr/ADR-002.md) (六边形分层), [ADR-003](../../adr/ADR-003.md) (Repository), [ADR-004](../../adr/ADR-004.md) (Pydantic v2), [ADR-007v2](../../adr/ADR-007v2.md) (包结构), [ADR-012](../../adr/ADR-012.md) (错误处理), [ADR-015](../../adr/ADR-015.md) (LangChain 隔离), [ADR-016](../../adr/ADR-016.md) (loguru), [ADR-017](../../adr/ADR-017.md) (CI 门禁), [ADR-018](../../adr/ADR-018.md) (测试分层), [ADR-019](../../adr/ADR-019.md) (版本里程碑), [ADR-025](../../adr/ADR-025.md) (依赖锁定)
> **状态**: ✅ 已实现（PR #75）

>
> **快速导航**（2026-08-08 #201）：
> [1. 概述](L13) · [2. 数据模型](L49) · [3. API 契约](L334) · [4. CLI 命令签名](L533)
> [5. 风格检测算法（确定性文本分析核心）](L596) · [6. 风格报告组织规则](L926) · [7. 边界情况与错误处理](L964) · [8. 文件结构](L1003)
> [9. 测试策略](L1219) · [10. 不在范围内](L1282) · [11. 依赖关系](L1303) · [12. 关键架构决策记录](L1343)
> [13. 验收标准](L1371) · [待澄清问题（≤ 3 个，已全部拍板 ✅）](L1392)
---

## 1. 概述

对**文本内容**（手动文本 / 项目章节）做**确定性文本分析**，输出一份 **StyleReport 风格报告**，包含三大板块：**风格指纹**（句子/段落/标点/词汇的结构性统计特征）、**AI 痕迹检测**（启发式规则评分，给出 0-1 AI 得分与倾向结论 + 可选 LLM 深度分析板块）、**词汇分析**（分词统计、高频词、停用词占比 + jieba 精确分词增强板块）。风格检测是**文本内容的只读计算**——不落库、不修改任何数据（验收标准 ①「风格指纹」+ ②「AI 痕迹检测」+ ③「词汇分析」的直接表达）。

**核心价值**: 长篇小说创作中，作者与 AI Agent 需要「文本体检」入口：写完一章想知道「这章的句子节奏如何、对话占比是否合理、词汇是否贫乏」，更想知道「这段文本像不像 AI 写的」（AI 辅助写作场景下的自查与审查需求，PRD P1-08 原文「风格指纹/AI 痕迹检测/词汇分析」三项）。**与 F15 审计的差异**: F15 分析**档案数据**（跨模块只读聚合 4 维档案的一致性），F16 分析**文本内容**（text / chapter_ids 输入）；F15 无输入校验错误面（唯一参数是路径 project_id），F16 有请求体（text/chapter_ids 互斥）——错误面为 404 + 422 + 500。

**与 F9-F15 样板的关系（关键差异——本模块是「确定性文本分析型」：F12 确定性检查与 F15 只读分析的谱系延伸，分析对象从「档案」变为「文本」）**: F9/F10 沉淀「实体 + AI 提取」，F11 演进为「实体 + AI 生成」，F12 演进为「实体 + 确定性检查（无 LLM）」，F13 演进为「实体 + 状态追踪 + F6 注入（无 LLM）」，F14 演进为「横切收敛门面（无新实体 + 增量 + RAG）」，F15 演进为「横切审计（无 LLM + 只读聚合档案）」；**F16 不新建任何业务实体表**——主体是**纯文本的确定性计算**：继承 F12/F15 的「纯内存确定性、严格幂等、无副作用、可快照断言」（§5），继承 F14 的「门面式依赖注入」（§5.1/§8.1），叠加出「对文本内容做结构统计与启发式评分」的分析能力；LLM 深度分析（Q1=C 拍板）与 jieba 精确分词增强（Q2=C 拍板）是**可选/增强板块**（默认关闭 / 与基础统计并存，§5.5/§5.6）：

```text
F9/F10 提取:  章节文本(text) ──LLM──▶ 结构化实体 ──合并落库──▶ 实体档案
F11  生成:    项目设定/约束(prompt) ──LLM──▶ 结构化大纲 ──新建落库──▶ 大纲规划
F12  检查:    事件档案(双时间维度) ──确定性算法──▶ 双线视图 + 冲突报告
F13  追踪:    伏笔档案(状态机) ──确定性追踪──▶ 状态流转
F14  门面:    6 种类型 ──分发──▶ 既有管线 + 增量提取 + RAG 索引（不建新档案）
F15  审计:    4 维档案(角色/时间线/世界/伏笔) + 跨模块引用 ──确定性规则──▶ AuditReport

F16  分析:    文本内容(text / chapter_ids) ──确定性统计 + 启发式评分──▶ StyleReport
               ├─ 风格指纹: 句子/段落/标点/对话/词汇 12 项结构性统计（§5.3）
               ├─ AI 痕迹:  8 个启发式特征 → ai_score(0-1) → verdict（§5.4）
               ├─ 词汇分析: 零依赖词块 token 统计 + 高频词 + 停用词占比 + jieba 精确分词增强（§5.5）
               └─ LLM 深度分析（可选）: 模板 style_llm_analysis.yaml → LLM 判定
                  （默认关闭，style analyze --llm-analysis；§5.6）
```

**复用** F14 门面的既有编排能力：`ExtractionType.STYLE` 槽位（枚举/API/CLI 已全量支持，F14 §6.1 注册占位）——F16 落地 = 在 `ExtractionService._handlers` 注册 `StyleService` 委托（§8.2），**接口零变更**（F14 Q1 ✅ 已拍板选项 A）；章节读取复用 F2 `ChapterRepositoryProtocol.get_chapter`（同 F14 章节模式先例：不含软删、校验不存在/跨项目/超长）；项目校验复用 F1 `ProjectRepositoryProtocol.get`。**依赖面（Q2=C 拍板）**：基础词块统计用标准库 `re` / `statistics` / `math` 实现（§5.2）；jieba 精确分词增强**新增运行时依赖 jieba**（pyproject + uv.lock 变更 + ADR-025 流程，版本锁定保证快照断言确定性，§5.5/§11）。

**边界声明**:
- F16 **不建新实体表**（无 style_reports 表）：风格报告是「文本内容的瞬态计算产物」，输出内存中的 StyleReport（同 F15 AuditReport 先例）；报告历史落库/多版本风格对比归 Phase 2+（见 §10）
- F16 **无 RAG**（style 不在向量索引范围，F14 §2.4）；**LLM 深度分析可选**（默认关闭，`style_llm_analysis` 设置项 + 请求/CLI 覆盖，Q1=C 拍板——LLM 分析是**只读无副作用**的文本判断（不写/改内容），但按 AI 自动化偏好**默认关闭**，用户显式开启才调用 LLM）；domain/ 零 LangChain import 门禁天然满足（ADR-015）
- F16 **新增运行时依赖 jieba**（Q2=C 拍板——pyproject + uv.lock 变更，ADR-025 流程随 F16 PR 合入；jieba 词典版本由 uv.lock 锁定，保证快照断言确定性，§5.5/§11）
- F16 **不修改文本**：分析是纯只读计算，不提供「按风格改写/润色」能力（改写归 F3 写作服务；风格**应用**——如按风格指纹生成约束——归 Phase 2+，见 §10）
- F16 的 **AI 痕迹检测是启发式参考而非科学结论**：统计特征评分（§5.4）反映「文本的统计形状与常见 AI 生成文本的相似度」，不是作者身份鉴定；报告明确标注「仅供参考」，verdict 三档（likely_human / uncertain / likely_ai）避免绝对断言（§6.2）
- F16 的 **F14 门面落点**是既定承诺（F14 §12 STYLE 占位决策）：STYLE 在统一接口中从「422 未实现」变为「正常执行」（每次执行、无增量 skip、无 RAG 索引——style 不在向量索引范围，F14 §2.4 已声明），并同步修订 F14 spec 的 STYLE 占位表述与占位测试（§8.2/§12）

---

## 2. 数据模型

F16 是确定性文本分析型模块：**不新建任何业务实体表、不新建任何 ORM 模型**（YAGNI——风格报告是瞬态计算结果，不落库，同 F15 §2 先例）；领域层新增一组**纯 Pydantic 报告模型**（WordFrequency / StyleFingerprint / AITraceVerdict / AITraceFeature / AITraceAssessment / LexicalAnalysis / JiebaAnalysis / StyleLLMAssessment / StyleReport），全部可序列化（`model_dump(mode="json")` 直接进 API/CLI 信封）。领域层 id 为 UUID，数据库 int 自增映射的约定对本模块不适用（无表）。**不引用**任何既有模块的模型（F16 是文本分析的纯消费者，输入是原始文本字符串，与 F9-F13 档案模型无交集——唯一例外：章节内容经 F2 Chapter 领域模型读取后只取 `content`/`title` 字段，不引入模型依赖到报告结构）。独立入口请求 DTO `StyleAnalyzeRequest`（§2.8）定义在 API 层（同 F9-F15 DTO 先例）。

### 2.1 WordFrequency（高频词条目）

| 字段 | 类型 | 说明 |
|------|------|------|
| word | str | 词条文本（token，§5.2 token 化规则；中文连续汉字串或英文单词） |
| count | int | 出现次数（≥ 1） |
| first_index | int | **首次出现的 token 序号**（0 起，扫描顺序）——排序次级键，保证同频词顺序确定性（§6.3，F15 教训：排序键避免中文文本字段） |

> **为什么暴露 first_index**: top_words 按 `(count DESC, first_index ASC)` 排序——主键 count 是数字（确定），次级键用首次出现序号（ASCII 数值、稳定）而非词条文本（中文 Unicode 码点序与作者直觉不符，且测试断言易与实现冲突——F15 实测教训，见 §6.3）。`first_index` 作为观测字段保留在模型中，供快照断言精确复现排序。

### 2.2 StyleFingerprint（风格指纹 — 12 项结构性统计）

| 字段 | 类型 | 说明 |
|------|------|------|
| char_count | int | 字符总数（去除空白字符后，§5.2 口径） |
| sentence_count | int | 句子数（按句尾符切分，§5.2） |
| avg_sentence_length | float | 平均句长（char_count / sentence_count，保留 2 位） |
| sentence_length_std | float | 句长标准差（总体标准差，n 分母，保留 2 位；sentence_count < 2 时为 0） |
| paragraph_count | int | 段落数（非空段落，§5.2） |
| avg_paragraph_length | float | 平均段落长度（char_count / paragraph_count，保留 2 位） |
| punctuation_density | float | 标点密度（标点字符数 / char_count，保留 4 位，§5.3） |
| exclamation_density | float | 感叹号密度（！! 数量 / char_count，保留 4 位） |
| ellipsis_density | float | 省略号密度（… 字符数量 / char_count，保留 4 位） |
| dialogue_ratio | float | 对话占比（引号内字符数 / char_count，保留 4 位，§5.3 对话检测规则） |
| vocabulary_richness | float | 词汇丰富度（TTR = unique_words / total_words，保留 4 位，与 §5.5 同源数据） |
| top_words | list[WordFrequency] | 高频词 Top-N（N=10 代码常量，§5.5/§6.3 排序） |

> **fingerprint 与 lexical 的数据同源性**: `vocabulary_richness` 与 `top_words` 直接复用词汇分析的 token 统计结果（§5.5）——指纹与词汇分析共享**同一次 token 化**（不重复计算），保证报告内部自洽（同 F15 §2.3 counts「共享同一次全量读取」的先例）。

### 2.3 AITraceVerdict / AITraceFeature / AITraceAssessment（AI 痕迹检测）

```python
class AITraceVerdict(StrEnum):
    """AI 痕迹判定结论（§6.2 阈值语义）."""

    LIKELY_HUMAN = "likely_human"   # ai_score ≤ 0.35 — 统计形状更接近人类写作
    UNCERTAIN = "uncertain"         # 0.35 < ai_score < 0.65 — 特征不明显，无法倾向
    LIKELY_AI = "likely_ai"         # ai_score ≥ 0.65 — 统计形状更接近常见 AI 生成文本


class AITraceFeature(BaseModel):
    """单个启发式特征（§5.4 特征表）.

    value 为观测值（原始统计量），score ∈ [0, 1]（1 = 更像 AI），
    note 为人类可读解释（中文，含观测值与参考方向）。
    """

    feature: str        # 特征名（稳定 ASCII 键，如 "sentence_uniformity"——排序/断言用）
    value: float        # 观测值（原始统计量）
    score: float        # 启发式评分 0-1（1 = 更像 AI）
    note: str           # 人类可读解释（中文）
```

| 字段 | 类型 | 说明 |
|------|------|------|
| feature | str | 特征名（ASCII 稳定键，§5.4 特征表 8 个；**不做排序键的替代——排序键即 feature 字符串本身**，ASCII 稳定，§6.3） |
| value | float | 观测值（原始统计量，如句长变异系数 0.62） |
| score | float | 启发式评分 0-1（1 = 更像 AI；评分函数见 §5.4 特征表） |
| note | str | 人类可读解释（中文，如「句长变异系数 0.62（偏低）——句式偏整齐」） |

```python
class AITraceAssessment(BaseModel):
    """AI 痕迹综合评估（§5.4/§6.2）."""

    ai_score: float                    # 综合得分 = 特征得分均值（等权，保留 4 位）
    verdict: AITraceVerdict            # 判定结论（阈值 §6.2）
    features: list[AITraceFeature]     # 全部特征（按 feature ASC 稳定排序，§6.3）
    evidence: list[str]                # 判定依据（score ≥ 0.5 的特征 note + 阈值说明；无则单条说明）
```

> **evidence 语义**: 报告不只给结论，还给「为什么」——`evidence` 列出得分 ≥ 0.5（倾向 AI）的特征说明（按 score DESC，同分按 feature ASC），供作者对照文本自检；若所有特征得分 < 0.5，则为单条「各特征得分均低于 0.5，无明显 AI 特征」。结论的「仅供参考」定位见 §1 边界声明/§6.2。

### 2.4 LexicalAnalysis（词汇分析）

| 字段 | 类型 | 说明 |
|------|------|------|
| total_words | int | 词条总数（token 数，§5.2 token 化——零依赖正则词块，**基础板块，始终计算**，Q2=C） |
| unique_words | int | 不同词条数（去重后） |
| top_words | list[WordFrequency] | 高频词 Top-N（N=10，同 §2.2 top_words 同源数据） |
| avg_word_length | float | 平均词长（总 token 字符数 / total_words，保留 2 位；CJK 序列按字符数计） |
| stopword_ratio | float | 停用词占比（停用词 token 数 / total_words，保留 4 位；停用词表为代码常量，§5.5） |
| jieba | JiebaAnalysis \| None | **jieba 精确分词增强板块（Q2=C）**——None = jieba 未装配（理论不可达，jieba 是必装运行时依赖，防御性）或空文本（§5.5） |

### 2.5 JiebaAnalysis（jieba 精确分词增强板块 — Q2=C）

| 字段 | 类型 | 说明 |
|------|------|------|
| jieba_total_words | int | jieba 分词词条总数（`jieba.lcut` 精确模式，§5.5） |
| jieba_unique_words | int | 不同词条数（去重后） |
| jieba_avg_word_length | float | 平均词长（总 token 字符数 / jieba_total_words，保留 2 位） |
| jieba_top_words | list[WordFrequency] | 高频词 Top-N（N=10，同 §2.1 WordFrequency 结构——`first_index` 语义同 §2.1：jieba token 序列中的首次出现序号；排序 `(count DESC, first_index ASC)`，§6.3） |

> **jieba 板块与基础板块的关系**: 两套 token 化并存、统计同构（total/unique/avg/top_words），互为补充——正则词块给出「连续汉字串」粒度的确定性统计（快照断言基线），jieba 给出词典级精确词频（可切出「的」「了」等单字功能词）；停用词过滤对两套都生效（§5.5）。

### 2.6 StyleReport（风格报告 — 编排输出）

```python
class StyleReport(BaseModel):
    """风格检测报告（§2.6）— 只读计算的瞬态结果，不落库."""

    project_id: uuid.UUID
    source: str                 # 输入来源标记: "manual" / "chapter:<id>" / "chapters:<id1>,<id2>"
    generated_at: datetime      # UTC
    fingerprint: StyleFingerprint
    ai_trace: AITraceAssessment
    lexical: LexicalAnalysis    # 含 jieba 增强板块（Q2=C，§2.4/§2.5）
    llm_assessment: StyleLLMAssessment | None = None   # 可选（Q1=C）: 未开启 LLM 深度分析或 LLM 不可用 → None（§2.7）
    warnings: list[str] = Field(default_factory=list)
```

**报告模型全字段梳理（v1.1）**: `StyleReport = project_id / source / generated_at / fingerprint / ai_trace / lexical（含 jieba）/ llm_assessment（可选）/ warnings`——基础板块（fingerprint/ai_trace/lexical）**始终计算**（确定性，快照断言基线）；`llm_assessment` 是**可选板块**（仅 `llm_analysis=true` 且 LLM 可用时填充，默认 None——门面 STYLE 恒确定性，§8.2）。

**source 语义表**:

| 输入模式 | source 值 | 说明 |
|----------|-----------|------|
| 手动文本（text） | `manual` | 单一手动文本（无章节语境） |
| 单章（chapter_ids=[id]） | `chapter:<uuid>` | 单章节分析 |
| 多章（chapter_ids=[id1, id2, ...]） | `chapters:<uuid1>,<uuid2>` | 多章节**合并为整体**分析（逗号分隔、请求顺序；风格是文本整体属性，§5.1 要点 5） |

> **warnings 语义**: 分析过程中的可观测提示（多章合并提示「跨章合并分析」、无有效词条提示、无完整句子提示等，§7 表），与 F14 `ExtractionResult.warnings` 的「提示不阻塞」语义一致（门面路径透传，§8.2）。

### 2.7 StyleLLMAssessment（LLM 深度分析板块 — Q1=C，可选）

| 字段 | 类型 | 说明 |
|------|------|------|
| llm_verdict | str | LLM 输出的判定：`likely_human` / `uncertain` / `likely_ai` 三值之一（与 §2.3 AITraceVerdict 同值域；解析层校验，§5.6） |
| reasoning | str | LLM 给出的判断理由（中文，**截断 ≤ 2000 字符**——超长截断在分析层，§5.6） |
| model | str | 实际使用的 LLM 模型（`model or project.config.model`，§5.6） |
| generated_at | datetime | LLM 判定生成时间（UTC） |

> **板块语义**: `llm_assessment` 是 **AI 痕迹检测的可选增强板块**——确定性 8 特征评分（§5.4）始终计算，LLM 判定是**附加参考**（非确定性、不可快照断言——测试用 Mock LLM 分支断言解析/重试逻辑，不对 LLM 输出内容断言，§9）；`StyleReport.llm_assessment = None` 表示「未开启 LLM 深度分析」或「LLM 不可用」（§5.6/§7）。

### 2.8 StyleAnalyzeRequest（独立入口请求 DTO — Q1=C 设置项三级覆盖）

定义在 API 层（`api/routers/style.py`，同 F9-F15 DTO 先例；§2 序言）：

| 字段 | 类型 | 说明 |
|------|------|------|
| project_id | uuid.UUID | 所属项目（路径参数） |
| text | str \| None = None | 手动文本（≤ 50000 字符，与 chapter_ids 互斥） |
| chapter_ids | list[uuid.UUID] \| None = None | 章节模式（≤ 100 个、非空、与 text 互斥） |
| llm_analysis | bool \| None = None | **LLM 深度分析开关（Q1=C）**：None = 跟随项目配置 `extra["style_llm_analysis"]` → 默认 **false**（镜像 F14 `timeline_auto_extract` 三级覆盖模式，F14 §2.6）；显式 true/false 覆盖项目配置 |

**设置项三级覆盖表（`style_llm_analysis`，F1 `ProjectConfig.extra` 模式——项目级扩展字典，无需 F1 schema 变更）**:

| 层级 | 键/参数 | 默认 | 说明 |
|------|---------|------|------|
| 项目配置 | `project.config.extra["style_llm_analysis"]` | **false** | 是否开启 LLM 深度分析（AI 自动化默认关闭——LLM 只读无副作用，但按 AI 自动化偏好需用户显式开启，§1 边界声明/§12） |
| 请求 | `StyleAnalyzeRequest.llm_analysis` | None = 跟随项目配置 | 单次覆盖（true/false） |
| CLI | `--llm-analysis` / `--no-llm-analysis` | None = 跟随项目配置 | 单次覆盖（§4.2） |

> **门面恒确定性声明**: F14 `ExtractionRequest` **无 `llm_analysis` 字段**（F14 接口零变更，Q3=B 拍板）——门面 STYLE 路径恒确定性（不调用 LLM，`llm_assessment` 恒 None）；LLM 深度分析**仅独立入口可开启**（`style analyze --llm-analysis` / 请求体 `llm_analysis=true`）（§5.1 要点 8/§8.2）。

### 2.9 领域模型代码（Pydantic v2 语法）

```python
# domain/models/style.py
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class WordFrequency(BaseModel):
    """高频词条目（§2.1）— first_index 为首次出现 token 序号（排序次级键）."""

    word: str
    count: int
    first_index: int


class StyleFingerprint(BaseModel):
    """风格指纹（§2.2）— 12 项结构性统计，全部确定性计算."""

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
    """AI 痕迹判定结论（§6.2 阈值语义）."""

    LIKELY_HUMAN = "likely_human"
    UNCERTAIN = "uncertain"
    LIKELY_AI = "likely_ai"


class AITraceFeature(BaseModel):
    """单个启发式特征（§5.4）— feature 为 ASCII 稳定键，score 1 = 更像 AI."""

    feature: str
    value: float
    score: float
    note: str


class AITraceAssessment(BaseModel):
    """AI 痕迹综合评估（§5.4/§6.2）."""

    ai_score: float = 0.0
    verdict: AITraceVerdict = AITraceVerdict.UNCERTAIN
    features: list[AITraceFeature] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class LexicalAnalysis(BaseModel):
    """词汇分析（§2.4）— 零依赖正则词块统计（基础板块，始终计算）."""

    total_words: int = 0
    unique_words: int = 0
    top_words: list[WordFrequency] = Field(default_factory=list)
    avg_word_length: float = 0.0
    stopword_ratio: float = 0.0
    jieba: JiebaAnalysis | None = None   # jieba 精确分词增强板块（§2.5，Q2=C）


class JiebaAnalysis(BaseModel):
    """jieba 精确分词统计（§2.5）— jieba.lcut 精确模式，与正则词块同构."""

    jieba_total_words: int = 0
    jieba_unique_words: int = 0
    jieba_avg_word_length: float = 0.0
    jieba_top_words: list[WordFrequency] = Field(default_factory=list)


class StyleLLMAssessment(BaseModel):
    """LLM 深度分析板块（§2.7，Q1=C 可选）— LLM 判定 + 理由."""

    llm_verdict: str            # likely_human / uncertain / likely_ai（解析层校验）
    reasoning: str              # LLM 理由（截断 ≤ 2000 字符）
    model: str                  # 实际使用的 LLM 模型
    generated_at: datetime      # UTC


class StyleReport(BaseModel):
    """风格检测报告（§2.6）— 只读计算的瞬态结果，不落库."""

    project_id: uuid.UUID
    source: str
    generated_at: datetime
    fingerprint: StyleFingerprint = Field(default_factory=StyleFingerprint)
    ai_trace: AITraceAssessment = Field(default_factory=AITraceAssessment)
    lexical: LexicalAnalysis = Field(default_factory=LexicalAnalysis)
    llm_assessment: StyleLLMAssessment | None = None
    warnings: list[str] = Field(default_factory=list)
```

> 报告模型全部为纯 Pydantic 输出模型（无 `from_attributes` 需求——不映射 ORM）；`model_dump(mode="json")` 直接进 API 响应与 CLI `--json` 信封（同 F12 ConsistencyReport / F15 AuditReport 序列化先例）。数值精度（保留位数）由分析层四舍五入保证（§5.3/§5.4），模型层不重复处理。

### 2.10 报告模型决策论证表

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **纯内存瞬态报告 + 三大板块嵌套（选定）** | 报告由文本即时推导，永不「过期」；无存储/查询/清理逻辑；快照断言直接对返回值；fingerprint/ai_trace/lexical 三板块对应 PRD 三项验收（§1） | 无历史轨迹（多版本风格对比需自己存 JSON） | ✅ MVP（风格分析是快照计算，§1/§12） |
| 落库 style_reports 表（报告 + 快照 JSON） | 有历史可回溯 | 报告过期问题（文本变报告旧）；表结构/查询/清理三块设计；超出 4.5-6.5 人天估算 | ❌ 否决（归 Phase 2+，§10） |
| **ai_score 连续值 + verdict 三档枚举（选定）** | 连续值供脚本阈值判断（可调），枚举供人类可读结论；avoid 绝对断言（「不是人写的」） | 阈值语义需文档化（§6.2） | ✅ 选定（§6.2/§12） |
| 仅 ai_score 连续值（无 verdict） | 模型更简 | 人类读者无法直接理解 0.63 的含义；CLI 摘要无结论可展示 | ❌ 否决（验收 ②「AI 痕迹检测」需可读结论） |
| **top_words 排序键 (count DESC, first_index ASC)（选定）** | 主键数字确定；次级键 ASCII 序号稳定；同频词按首次出现顺序（自然语感） | 模型多一个观测字段 first_index | ✅ 选定（§6.3，F15 教训：避免中文文本作排序键） |
| top_words 排序键 (count DESC, word ASC) | 模型更简 | word 为中文文本 → Unicode 码点序与作者直觉不符，测试断言与实现易冲突（F15 实测教训） | ❌ 否决（§6.3） |
| **source 字符串标记（manual/chapter:<id>/chapters:<ids>）（选定）** | 单源/多源可区分；与 F14 run.source_key 语义同构（manual/章节 id） | 多章串为逗号连接（可解析，非结构化字段） | ✅ 选定（§2.6/§12） |
| source 结构化（source_type 枚举 + chapter_ids 列表） | 更规范 | 单字段可表达，YAGNI；报告消费者按字符串解析即可 | ❌ 否决（P5 YAGNI） |
| **llm_assessment 可选板块（None=未开启/不可用）（选定，Q1=C）** | 报告默认结构零变化（None 兼容旧消费者）；确定性验收基线（快照断言）不受 LLM 影响；LLM 板块可独立演进 | 报告多一个可空字段（序列化时 null） | ✅ 选定（§2.6/§2.7/§12——LLM 深度分析仅独立入口可开启，门面恒 None） |
| llm_assessment 必填（LLM 失败则整报告失败） | 报告结构恒定 | LLM 不可用时整份确定性报告不可用（错误面扩大）；与「可选增强」定位冲突 | ❌ 否决（Q1=C 拍板：LLM 是可选增强非基础板块） |
| **jieba 板块（JiebaAnalysis 嵌套在 LexicalAnalysis.jieba）（选定，Q2=C）** | 与基础词汇统计同构、同报告序列化；None=未装配/空文本（防御性） | 依赖面 +1（jieba 运行时依赖，uv.lock 锁定） | ✅ 选定（§2.4/§2.5/§12——零依赖词块保持基础板块，jieba 提供词典级精确词频） |
| jieba 替换正则词块（单一 jieba 统计） | 依赖面单一 | 词典版本变化破坏快照断言基线；丢失确定性基础板块（Q2 方案 B 否决点） | ❌ 否决（Q2=C 拍板：两套并存、正则词块为快照断言基线） |

---

## 3. API 契约

端点风格沿用既有约定：**F14 门面入口保留**（`POST /api/v1/extract`，type=style 从「422 未实现」变为正常执行，接口零变更——F14 §6.1/§12 承诺）；**独立入口嵌套项目路径**（`POST /api/v1/projects/{project_id}/style/analyze`——报告型产物独立入口，镜像 F15 `GET .../audit` 的项目级嵌套风格；**用 POST 而非 GET**——有请求体（text/chapter_ids 互斥输入），镜像 F9 `/characters/extract` 与 F14 `/extract` 的 POST 先例；幂等性由确定性计算保证，同输入同输出）。错误响应格式沿用 F1/F2/F9-F15（`{"detail": "..."}` 404/422/500）。

### 3.1 端点总览（2 个）

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/extract` | 统一提取（**已有端点**——F16 落地后 type=style 从 422 变为 200，接口零变更，§8.2） | `ExtractionRequest`（type=style） | 200 + ExtractionResult（detail=StyleReport） |
| POST | `/api/v1/projects/{project_id}/style/analyze` | 风格分析（独立入口，报告型产物） | `StyleAnalyzeRequest`（text \| chapter_ids 互斥 + `llm_analysis` 可选，§2.8） | 200 + StyleReport |

> **为什么保留 F14 门面 + 新增独立入口（Q3 ✅ 已确认选项 B）**: ① F14 Q1 已拍板 STYLE 槽位必须落地（门面是「一键沉淀」的统一心智，Agent 脚本走统一接口）；② 风格报告是**报告型产物**（同 F15 审计报告），作者与 Agent 需要「直接拿报告」的独立入口（`style analyze` 命令 + `/style/analyze` 端点），不必套统一提取信封；③ 两条路径共享同一个 `StyleService`（零重复逻辑，§8.1）；独立入口估算 +0.5-1 人天（已含在 4.5-6.5 人天总估算）。方案 A（仅门面）与方案 C（仅独立入口）的权衡见 §12/待澄清 Q3 ✅。

### 3.2 请求/响应示例

**独立入口 — 手动文本分析（LLM 深度分析关闭）**:
```http
POST /api/v1/projects/3f2e1d4a-.../style/analyze
Content-Type: application/json

{
  "text": "林晚推开窗，夜色如墨。她低声说：\"三年了，我终究还是回来了。\"窗外传来更鼓声，一下，两下……",
  "llm_analysis": false
}
```
→ 200
```json
{
  "project_id": "3f2e1d4a-...",
  "source": "manual",
  "generated_at": "2026-08-02T12:00:00Z",
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
    "top_words": [
      {"word": "林晚", "count": 1, "first_index": 0},
      {"word": "窗外", "count": 1, "first_index": 9}
    ]
  },
  "ai_trace": {
    "ai_score": 0.26,
    "verdict": "likely_human",
    "features": [
      {"feature": "dialogue_ratio_extreme", "value": 0.2083, "score": 0.0, "note": "对话占比 0.2083（位于 0.05-0.75 中位区间）——无明显特征"},
      {"feature": "ellipsis_density_low", "value": 0.0417, "score": 0.0, "note": "省略号密度 0.0417（≥ 0.004）——省略号使用正常"},
      {"feature": "sentence_uniformity", "value": 0.62, "score": 0.38, "note": "句长变异系数 0.62——句式波动正常"}
    ],
    "evidence": ["各特征得分均低于 0.5，无明显 AI 特征（综合得分 0.26 ≤ 0.35 → likely_human）"]
  },
  "lexical": {
    "total_words": 17,
    "unique_words": 14,
    "top_words": [
      {"word": "林晚", "count": 1, "first_index": 0},
      {"word": "窗外", "count": 1, "first_index": 9}
    ],
    "avg_word_length": 2.1,
    "stopword_ratio": 0.0588,
    "jieba": {
      "jieba_total_words": 19,
      "jieba_unique_words": 15,
      "jieba_avg_word_length": 1.9,
      "jieba_top_words": [
        {"word": "林晚", "count": 1, "first_index": 0},
        {"word": "的", "count": 1, "first_index": 4}
      ]
    }
  },
  "llm_assessment": null,
  "warnings": ["未检测到完整句子（句尾符不足）——句子统计仅供参考"]
}
```
（示例文本极短仅为示意；真实分析对 ≥ 100 字符文本更有意义——见 §7 边界表「文本过短」行；`llm_analysis: false` 显式关闭 → `llm_assessment: null`）

**独立入口 — LLM 深度分析开启（可选板块，Q1=C）**:
```http
POST /api/v1/projects/3f2e1d4a-.../style/analyze
{
  "chapter_ids": ["7a4f2c91-..."],
  "llm_analysis": true
}
```
→ 200（确定性板块同前例；新增可选板块）
```json
{
  "llm_assessment": {
    "llm_verdict": "likely_human",
    "reasoning": "句式长短错落、对话与叙述穿插自然、省略号使用克制——统计特征未显示明显 AI 生成模式。",
    "model": "gpt-4o",
    "generated_at": "2026-08-02T12:00:01Z"
  }
}
```
（`llm_analysis` 缺省 None → 跟随项目配置 `extra["style_llm_analysis"]`（默认 false）；LLM 判定不可快照断言——测试用 Mock LLM 分支断言解析/重试逻辑（§9）；`llm_analysis=true` 但 LLM 不可用 → 500（§3.3/§7））

**独立入口 — 章节模式（多章合并）**:
```http
POST /api/v1/projects/3f2e1d4a-.../style/analyze
{
  "chapter_ids": ["7a4f2c91-...", "9b1c2d3e-..."]
}
```
→ 200（source=`chapters:7a4f2c91-...,9b1c2d3e-...`；多章按请求顺序合并为整体分析；warnings 含「多章节合并分析」提示）

**F14 门面入口 — type=style（F16 落地后）**:
```http
POST /api/v1/extract
{"project_id": "3f2e1d4a-...", "type": "style", "chapter_ids": ["7a4f2c91-..."]}
```
→ 200
```json
{
  "type": "style",
  "status": "success",
  "skipped_reason": null,
  "processed_sources": 1,
  "skipped_sources": 0,
  "created": 0,
  "updated": 0,
  "warnings": ["多章节合并分析（单章粒度分析归 Phase 2+）"],
  "model": null,
  "indexed": false,
  "detail": {
    "project_id": "3f2e1d4a-...",
    "source": "chapter:7a4f2c91-...",
    "generated_at": "2026-08-02T12:00:00Z",
    "fingerprint": {...},
    "ai_trace": {...},
    "lexical": {...},
    "warnings": ["多章节合并分析（单章粒度分析归 Phase 2+）"]
  }
}
```
（STYLE 结果归一：created=0/updated=0、model=None、indexed=false + warning「style 类型不支持自动索引」——镜像 F14 timeline 关闭语义先例，§5.3/§8.2）

**输入冲突与缺失（独立入口）**:
```http
POST /api/v1/projects/3f2e1d4a-.../style/analyze
{"text": "……", "chapter_ids": ["7a4f2c91-..."]}
→ 422 {"detail": "text 与 chapter_ids 不能同时使用"}

POST /api/v1/projects/3f2e1d4a-.../style/analyze
{}
→ 422 {"detail": "必须提供 text 或 chapter_ids"}

POST /api/v1/projects/3f2e1d4a-.../style/analyze
{"chapter_ids": ["11111111-1111-1111-1111-111111111111"]}
→ 422 {"detail": "章节不存在"}

POST /api/v1/projects/00000000-0000-0000-0000-000000000000/style/analyze
{"text": "……"}
→ 404 {"detail": "项目不存在"}
```

### 3.3 错误响应格式（沿用 F1/F2/F9-F15/ADR-012）

```json
// 404 — 资源不存在
{"detail": "项目不存在"}

// 422 — 业务校验失败（输入互斥/缺失/章节校验）
{"detail": "text 与 chapter_ids 不能同时使用"}
{"detail": "必须提供 text 或 chapter_ids"}
{"detail": "章节不存在"}

// 500 — DB 读取失败（loguru 记录）
{"detail": "内部错误: ..."}
```

**异常映射表**:

| 异常/场景 | 状态码 | 响应 |
|-----------|--------|------|
| 项目不存在（`ProjectRepositoryProtocol.get` → None，服务层统一校验） | 404 | `{"detail": "项目不存在"}` |
| 无效 UUID 格式（project_id 路径参数） | 404 | 统一解析失败处理（同 F9-F15 `_parse_id`） |
| text 与 chapter_ids 同时提供 / 均未提供 / text 为空（独立入口 `StyleAnalyzeRequest` 或服务层校验） | 422 | `StyleValidationError`（消息即 detail） |
| chapter_ids 指向不存在章节（含软删——F2 get 不含软删） | 422 | 复用 F14 `ChapterNotFoundError`（「章节不存在」，同 F14 章节模式语义） |
| chapter_ids 指向其他项目章节 | 422 | 复用 F14 `ChapterNotInProjectError`（「章节不属于该项目」） |
| 章节内容超 50000 字符（分析上限，同 F14 提取上限） | 422 | `StyleValidationError`（「章节内容超过分析上限（50000 字符）」） |
| llm_analysis=true 且 LLM 分析器未装配（deps 层可选装配，§8.1） | 500 | `StyleLLMUnavailableError`（「LLM 深度分析不可用」，消息即 detail——镜像 F14 `RAGUnavailableError` 先例，§7） |
| llm_analysis=true 且 LLM 调用失败（网络/超时/Provider 错误） | 500 | 透传 `LLMRequestError`（F5 错误类，同 F9-F11——不消耗解析重试，§5.6） |
| llm_analysis=true 且解析重试耗尽（修复式重试 ≤2 仍失败） | 500 | `StyleLLMAnalysisError`（透传，同 F14 `TimelineExtractionError` 语义，§5.6） |
| 项目仓储 / 章节仓储读取失败（DB 错误） | 500 | 全局处理器（loguru，ADR-012/016） |

> **与 F14 门面路径的错误映射一致性**: 门面路径（`POST /extract` type=style）的错误由 extractions router 既有映射处理——`ExtractionValidationError`（F14，门面输入约束）/ `ChapterNotFoundError` / `ChapterNotInProjectError`（F14，章节校验）→ 422、`ProjectNotFoundError`（F9）→ 404；**StyleService 抛出的 `StyleValidationError` 需在 extractions router `_run_service` 与 extract CLI `_run` 增加显式映射**（§8.2，F16 声明的 F14 文件 MODIFY——错误类归属 style_errors 自洽，不继承 F14 错误类，避免跨模块错误继承耦合；映射是表现层一行级改动）。
>
> **与 F15 的差异**: F15 是**无输入校验错误面**的模块（唯一参数是路径 project_id，无请求体）；F16 有请求体（text/chapter_ids）——错误面为 404 + **422 业务校验** + 500（同 F12/F14 有输入字段模块的错误面形态）。LLM 相关错误（`StyleLLMUnavailableError` / `LLMRequestError` / `StyleLLMAnalysisError`）**仅 llm_analysis=true 时可达**（默认关闭，§5.6/§7）。

---

## 4. CLI 命令签名

遵循 F7 §5 全局约定：`--json` 统一信封 `{"ok": true, "data": ...}` / `{"ok": false, "error": {"code", "message"}}`；退出码 0/1/2/130。**错误码**：NOT_FOUND / **VALIDATION_ERROR**（输入校验）/ **LLM_ERROR**（可选——仅 LLM 深度分析开启时可达：LLM 调用失败/解析重试耗尽/分析器未装配 → LLM_ERROR 信封，退出码 1，同 F9-F11 先例；默认关闭时不可达）/ **DB_ERROR**（**无 UNSUPPORTED_TYPE**——F16 落地后 STYLE 不再是「未实现类型」，extract CLI 的 UNSUPPORTED_TYPE 分支删除 StyleNotImplementedError，§8.2）。`style` 组在 F16 落地时并入 F7 命令树（`cli/app.py` 注册，同 F15 audit 组 / F14 extract 组先例）。

### 4.1 extract 组（F14 门面入口 — 保留，行为变化声明）

```bash
inkflow extract run --project-id <uuid> --type style \
    [--text <str> | --text-file <path> | --chapters <uuid,uuid,...>] [--json]
    # F16 落地前: --type style → 退出码 1 + UNSUPPORTED_TYPE 信封（F14 占位）
    # F16 落地后: --type style 正常执行 → 退出码 0（每次执行、无增量 skip、无 RAG 索引）
    # 输入约束（F14 §6.4 style 行修订）: 必须提供 --text/--text-file/--chapters 其一（互斥）
    # 输出: 统一 ExtractionResult 信封（人类可读摘要见 §4.3；--json 完整 detail=StyleReport）
```

### 4.2 style 组（独立入口 — 报告型产物，镜像 F15 audit 组风格）

```bash
inkflow style analyze --project-id <uuid> \
    [--text <str> | --text-file <path> | --chapters <uuid,uuid,...>] \
    [--llm-analysis | --no-llm-analysis] [--json]
    # --text/--text-file/--chapters 三选一（互斥，同 F9 character extract / F14 extract run 先例）
    # --llm-analysis/--no-llm-analysis（Q1=C 拍板）: 显式开启/关闭 LLM 深度分析；
    #   缺省 None = 跟随项目配置 extra["style_llm_analysis"]（默认 false，§2.8）
    # 只读幂等: 不修改任何数据，可重复执行（同 F15 audit check / F12 timeline check）
    # 退出码恒 0（成功执行；分析结论是「结果」而非「执行错误」——同 F15 Q1 拍板语义）
    # 缺参（三选一均未提供）→ 退出码 2（Typer 参数校验，同 F14 先例）
    # --json 输出完整 StyleReport（model_dump(mode="json")，含可选 llm_assessment 板块）
```

### 4.3 输出格式

```bash
# style analyze 默认人类可读
📊 风格分析 (project 3f2e1d4a-...):
  【风格指纹】字数 2850 · 句子 62 · 平均句长 45.9 · 段落 18 · 平均段落 158.3
  标点密度 0.1213 · 感叹号 0.0164 · 省略号 0.0088 · 对话占比 0.3251
  词汇丰富度 0.6102 · 高频词: 林晚(12) 她(9) 说(8) 夜(7) …
  【AI 痕迹】AI 得分 0.23 → ✅ 倾向人类创作
  [sentence_uniformity] 句长变异系数 0.62——句式波动正常
  [exclamation_density_low] 感叹号密度 0.0164（≥ 0.005）——感叹号使用正常
  【词汇分析】总词数 1520 · 唯一词 927 · 平均词长 2.42 · 停用词占比 0.2812
  【jieba 增强】总词数 1631 · 唯一词 1012 · 平均词长 2.18（--json 含完整 jieba_top_words）
  【LLM 深度分析】✅ 倾向人类创作（gpt-4o）——句式长短错落、对话自然（--llm-analysis 开启时）
  ⚠ 多章节合并分析（单章粒度分析归 Phase 2+）

# extract run --type style 默认人类可读（门面统一摘要，§8.2 归一）
✅ 提取完成: style 处理 1 个源（跳过 0），新增 0 更新 0，警告 1 条

# --json 输出（完整 StyleReport 信封）
inkflow style analyze --project-id 3f2e1d4a-... --chapters 7a4f2c91-...,9b1c2d3e-... --json
→ {"ok": true, "data": {"project_id": "3f2e1d4a-...", "source": "chapters:7a4f2c91-...,9b1c2d3e-...",
   "generated_at": "...", "fingerprint": {...}, "ai_trace": {...}, "lexical": {...}, "warnings": [...]}}

inkflow style analyze --project-id 00000000-0000-0000-0000-000000000000 --text "……" --json
→ {"ok": false, "error": {"code": "NOT_FOUND", "message": "项目不存在"}}  # 退出码 1

inkflow style analyze --project-id 3f2e1d4a-... --json
→ 退出码 2（Typer 缺 --text/--text-file/--chapters 必选参数校验，§7 边界表）
```

> **人类可读摘要规则**: 三大板块各一行摘要（风格指纹行含 12 项中 8 项关键指标 + 高频词前 5；AI 痕迹行给 ai_score + verdict 中文结论，倾向特征逐条列出（`[特征名] note`）；词汇分析行含 5 项指标）；jieba 增强开启（jieba 板块非 None）时追加一行 jieba 摘要；LLM 深度分析开启（llm_assessment 非 None）时追加一行 LLM 判定摘要（verdict 中文 + model + reasoning 摘要）；有 warnings 时逐条列出；最后提示 `--json` 获取完整报告。verdict 中文映射: likely_human→「倾向人类创作」、uncertain→「特征不明显」、likely_ai→「倾向 AI 生成」。

## 5. 风格检测算法（确定性文本分析核心）

> ⚠️ **本节是 F16 与 F9-F15 样板的核心差异点**：F9/F10 的 §5 是「AI 提取管线」，F11 的 §5 是「AI 生成管线」，F12 的 §5 是「单一档案一致性检查算法」，F13 的 §5 是「状态机 + F6 注入」，F14 的 §5 是「门面分发 + 增量 + RAG」，F15 的 §5 是「跨档案规则引擎」；本模块的 §5 是**文本内容的三块确定性算法**——风格指纹（结构性统计）、AI 痕迹检测（启发式评分）、词汇分析（零依赖分词）。算法性质完全继承 F12/F15：纯内存、严格幂等、无副作用、可快照断言（§5.1 要点）。全部算法拆到纯函数模块 `domain/services/_style_analyzer.py`（镜像 `_chunking.py` 先例——纯函数、无 I/O、可单测），`StyleService` 只做编排（读章节、拼装文本、组装报告）。

### 5.1 模式总览（编排）

```text
 ┌──────────────────────────────────────────────────────────────────────┐
 │ 输入: StyleService.analyze(project_id, text|chapter_ids, llm_analysis=None)  │
 └───────────────────────────┬──────────────────────────────────────────┘
                             ▼
 ① 校验项目存在（ProjectRepositoryProtocol.get → None → 404「项目不存在」）
 ② 解析输入源（§5.1 要点 4）:
    ├─ text 模式 → 文本去空白校验（空 → StyleValidationError 422）
    └─ chapter_ids 模式 → 逐章读取（F2 get_chapter: 不存在/跨项目/超长 → 422）
                          → 按请求顺序合并（章间插入 "\n\n"）→ 记录 source 标记
 ③ 文本预处理 + token 化（§5.2，纯函数，一次完成供三块共享）:
    ├─ 去空白文本（char_count 口径） / 句子切分 / 段落切分 / 标点统计
    ├─ token 序列（零依赖正则词块: CJK 连续串 + 拉丁/数字连续串——基础板块；jieba.lcut 增强在 §5.5）
    └─ 对话检测（引号配对扫描）
 ④ 三块分析（全部纯函数，共享 ③ 的统计快照）:
    ├─ 风格指纹 StyleFingerprint（§5.3: 12 项结构性统计）
    ├─ AI 痕迹 AITraceAssessment（§5.4: 8 特征启发式评分 → ai_score → verdict——基础板块，始终计算）
    └─ 词汇分析 LexicalAnalysis（§5.5: 正则词块 token 统计 + 高频词 + 停用词 + jieba 增强板块）
 ⑤ 组装 StyleReport（source/generated_at/warnings）+ 确定性排序（§6.3）
 ⑥ LLM 深度分析（可选，Q1=C）: llm_analysis 三级判定（请求 → 项目配置 → 默认 false）→
    true 时调用 StyleLLMAnalyzer（§5.6）→ 报告注入 llm_assessment（默认 None）
```

**模式要点**:
1. **纯函数算法层**：token 化、句子/段落切分、全部统计与评分是 `_style_analyzer.py` 的纯函数（输入 = 文本字符串，输出 = 各板块数据）——单测直接喂文本断言数值（同 `_chunking.py` 先例）；`StyleService` 只做编排（项目校验、章节读取、组装报告）
2. **项目校验单一入口**：服务层统一校验一次（404）；门面路径（F14）委托前已校验（幂等，成本可忽略——保持 F14 不感知 F16 内部，同 F15 要点 2）
3. **算法全确定性**：同一文本永远得到同一报告（快照断言友好，同 F12 §5 要点 1）；数值精度由分析层统一四舍五入（§5.3 表）
4. **输入源解析在服务层**：text 与 chapter_ids 互斥/必填校验在服务层（`StyleValidationError`，422）；章节校验复用 F14 错误类（`ChapterNotFoundError` / `ChapterNotInProjectError`，422）——门面与独立入口共用同一套校验语义（F14 §6.4 style 行修订的落地）
5. **多章合并为整体**：风格是**文本整体属性**（句子节奏/词汇分布需要足够样本量），多章合并分析比逐章分析更有意义；合并时按请求顺序拼接（章间 `\n\n` 分隔，避免章节边界句粘连），source 记录全部章节 id（§2.6）；**单章粒度分析归 Phase 2+**（§10/待澄清 Q3 ✅）
6. **失败即异常（ADR-012）**：项目/章节仓储读取失败 → 抛异常（router 转 404/422/500）；不吞错、不产出「部分报告」（报告必须完整，同 F15 要点 6）
7. **无副作用**：分析不修改任何数据、不写任何内容；重复执行幂等（同 F12/F15 要点）
8. **LLM 深度分析可选（Q1=C 拍板）**：默认关闭——`llm_analysis` 三级覆盖（请求显式 → 项目配置 `extra["style_llm_analysis"]` → 默认 false，§2.8）；**仅独立入口可开启**（门面 STYLE 恒确定性：F14 `ExtractionRequest` 无 `llm_analysis` 字段，接口零变更，§8.2）；开启时 `llm_assessment` 注入报告（§5.6），确定性板块不受影响
9. **jieba 增强（Q2=C 拍板）**：词汇分析双板块——正则词块（基础，始终计算）+ jieba 精确分词（增强，与基础同构统计）；jieba 词典版本由 uv.lock 锁定（ADR-025），快照断言确定性不受影响（§5.5）

### 5.2 文本预处理与 token 化（零依赖词块 — Q2=C 基础板块）

> 本节为词汇分析的**基础板块（零依赖正则词块）**——Q2=C 拍板后：正则词块统计始终计算（快照断言基线），jieba 精确分词作为**增强板块**与基础同构统计（§5.5）；jieba 为**新增运行时依赖**（pyproject + uv.lock 变更 + ADR-025 流程，§11）。

**预处理（`_preprocess` 纯函数）**:

| 步骤 | 规则 | 输出 |
|------|------|------|
| 去空白 | 移除全部空白字符（空格 ` `、`\t`、`\n`、`\r`、`\u3000`） | `clean`（char_count 口径 = len(clean)） |
| 句子切分 | 按句尾符 `。！？!?…；;\n` 切分，过滤空串（`…` 连续出现合并为一个句尾符位置——「……」不产生空句子） | `sentences: list[str]` |
| 段落切分 | 按 `\n` 切分，过滤空段落（strip 后为空） | `paragraphs: list[str]` |
| 标点统计 | 对 clean 扫描：标点字符集合（中文 `，。！？；：、“”‘’（）《》【】——…·「」` + 英文 `,.;:!?"'()[]{}`）计数；感叹号 `！!` 计数；省略号 `…` 计数（「……」计 2 次） | `punct_count / exclam_count / ellipsis_count` |
| 对话检测 | 引号配对扫描（`“ ”`、`「 」`、`" "`）：遇开始引号进对话态、遇结束引号出对话态（未配对时按出现顺序交替切换），累计对话态内字符数 | `dialogue_chars` |

**token 化（`_tokenize` 纯函数 — 零依赖词块）**:

```python
# 规则: 连续 CJK 字符序列 [\u4e00-\u9fff]+ 或 连续拉丁/数字序列 [A-Za-z0-9]+ 各为一个 token；
# 标点、空白、其他字符不构成 token（分隔符）。
# 示例: "林晚推开窗，夜色如墨。" → ["林晚", "推开窗", "夜色如墨"]
#       "She said: hello world" → ["She", "said", "hello", "world"]
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+")
```

| 输出 | 定义 |
|------|------|
| `tokens: list[str]` | 全部 token（保序，含重复——`first_index` 由列表下标确定，§2.1） |
| `total_words` | len(tokens) |
| `unique_words` | len(set(tokens)) |
| `avg_word_length` | 总 token 字符数 / total_words（CJK 序列按字符数计，保留 2 位） |
| `top_words` | Counter 统计 → Top-N（N=10 代码常量），按 `(count DESC, first_index ASC)` 排序（§6.3） |
| `stopword_ratio` | 停用词 token 数 / total_words（停用词表为代码常量 `_STOPWORDS`，§5.5） |

> **零依赖论证（Q2=C 拍板后修订）**: ① 中文「词」的边界本身有歧义（「推开窗」是词还是词组？），正则词块（连续汉字串）提供**确定性的近似词粒度**——作为基础板块保证快照断言基线（jieba 词典版本变化会改变分词结果 → 若作为唯一统计源会破坏快照断言）；② **jieba 增强板块的确定性由 uv.lock 锁定保证**（ADR-025：CI `uv sync --frozen` 固定词典版本，测试文本固定 → 输出确定，§5.5）；③ 词汇分析的价值定位是「词汇多样性/复用度的近似观测」（TTR、高频词、停用词占比），不依赖精确分词边界（§5.5 论证）——两套统计并存、互为补充。

### 5.3 风格指纹算法（12 项统计）

全部基于 §5.2 预处理输出（`clean` / `sentences` / `paragraphs` / 各计数），纯函数 `_analyze_fingerprint`:

| # | 字段 | 公式 | 边界 |
|---|------|------|------|
| 1 | char_count | len(clean) | — |
| 2 | sentence_count | len(sentences) | 0 个句子 → 下方均值/标准差全部为 0（+ warning「未检测到完整句子」，§7） |
| 3 | avg_sentence_length | char_count / sentence_count（保留 2 位） | sentence_count = 0 → 0.0 |
| 4 | sentence_length_std | 句子字符长度（去空白后）总体标准差 `sqrt(sum((len(s)-mean)²)/n)`（保留 2 位） | n < 2 → 0.0 |
| 5 | paragraph_count | len(paragraphs) | — |
| 6 | avg_paragraph_length | char_count / paragraph_count（保留 2 位） | paragraph_count = 0 → 0.0 |
| 7 | punctuation_density | punct_count / char_count（保留 4 位） | char_count = 0 → 0.0 |
| 8 | exclamation_density | exclam_count / char_count（保留 4 位） | 同上 |
| 9 | ellipsis_density | ellipsis_count / char_count（保留 4 位） | 同上 |
| 10 | dialogue_ratio | dialogue_chars / char_count（保留 4 位） | 同上 |
| 11 | vocabulary_richness | unique_words / total_words（TTR，保留 4 位） | total_words = 0 → 0.0 |
| 12 | top_words | §5.2 token 统计 Top-10 | 无 token → 空列表 |

> **口径声明（与 F2 word_count 的差异）**: F2 章节 `word_count` 是章节模块自己的字数口径；F16 的 char_count 是**分析口径**（去空白字符数）——两者数值可能不同，spec 不承诺对齐（F16 只读消费章节 content 文本，不读 word_count 字段）。报告内所有密度/均值基于同一 char_count 口径，内部自洽（§6.1）。

### 5.4 AI 痕迹检测（8 特征启发式评分）

> ⚠️ **本节是 AI 痕迹检测的基础板块（确定性 8 特征评分，始终计算）——Q1=C 拍板**：确定性启发式为主 + LLM 深度分析可选（默认关闭，§5.6）。AI 痕迹检测是**只读无副作用的文本判断**（不写/改任何内容）；LLM 深度分析同样只读无副作用，但按 AI 自动化偏好**默认关闭**（`style_llm_analysis` 设置项，用户显式开启才调用 LLM，§1 边界声明/§2.8）。

**评分模型**: 每个特征 = 纯函数（观测统计量 → score ∈ [0, 1]，**1 = 更像 AI**）；`ai_score` = 特征得分**等权均值**（无先验数据支撑差异化权重——YAGNI，权重校准归 Phase 2+，§6.2）；`verdict` 由阈值决定（§6.2）。

**特征表（8 个，feature 名 = ASCII 稳定键）**:

| feature | 观测值 value | 评分函数（score = 1 更像 AI） | note 模板（中文） |
|---------|-------------|------------------------------|-------------------|
| `sentence_uniformity` | 句长变异系数 cv = std / mean | `1 - min(cv / 1.0, 1.0)`（cv → 0 句式完全整齐 → 1.0；cv ≥ 1.0 → 0） | 「句长变异系数 {cv:.2f}（{低/正常}）——句式{偏整齐/波动正常}」 |
| `paragraph_uniformity` | 段落长度变异系数 cv_p | `1 - min(cv_p / 1.0, 1.0)` | 「段落长度变异系数 {cv_p:.2f}——段落{偏均匀/长短有致}」 |
| `exclamation_density_low` | 感叹号密度 d_ex | `clamp((0.005 - d_ex) / 0.005, 0, 1)`（d_ex < 0.5% → 偏 AI；≥ 1% → 0） | 「感叹号密度 {d_ex:.4f}（{低于/达到} 0.005）——{缺少情绪标点/情绪表达正常}」 |
| `ellipsis_density_low` | 省略号密度 d_el | `clamp((0.004 - d_el) / 0.004, 0, 1)` | 「省略号密度 {d_el:.4f}（{低于/达到} 0.004）——{缺少省略号/省略号使用正常}」 |
| `dialogue_ratio_extreme` | 对话占比 r | `max((0.05 - r)/0.05, (r - 0.75)/0.05, 0)` 截断到 [0, 1]（r ∈ [0.05, 0.75] 中位区间 → 0；r=0 或 r=1 → 1） | 「对话占比 {r:.4f}（{位于中位区间/过低/过高}）——{无明显特征/对话分布异常}」 |
| `vocabulary_richness_low` | TTR v | `clamp((0.45 - v) / 0.15, 0, 1)`（v ≥ 0.60 → 0；v ≤ 0.30 → 1） | 「词汇丰富度 {v:.4f}（{低于/达到} 0.45）——{词汇复用偏高/词汇多样}」 |
| `top_word_concentration` | 最高频词占比 c = top1_count / total_words | `clamp((c - 0.06) / 0.06, 0, 1)`（c ≤ 6% → 0；≥ 12% → 1） | 「最高频词占比 {c:.4f}（{低于/超过} 0.06）——{高频词分布均匀/集中于单一词汇}」 |
| `punctuation_variety_low` | 标点种类数 n_p（§5.2 标点集合中出现过的种类） | `clamp((8 - n_p) / 8, 0, 1)`（n_p ≥ 8 → 0；n_p = 0 → 1） | 「标点种类 {n_p}（{少于/达到} 8 种）——{标点单调/标点丰富}」 |

**边界语义**: 文本过短（char_count < 100）→ ai_trace 仍计算但报告标注（§7 边界表）；sentence_count < 2 → `sentence_uniformity` 的 std=0 → cv 取 0 → score=1.0（**过短文本的句长特征失真**——note 加「样本不足」后缀，且该特征在文本过短时不进 evidence，§6.2 证据规则）；total_words = 0 → `vocabulary_richness_low` / `top_word_concentration` score 取 0.5（中性，避免纯标点文本误判，note「无有效词条——特征中性」）。

**evidence 构建规则**（§2.3）: `[f.note for f in features if f.score >= 0.5]` 按 `(score DESC, feature ASC)` 排序；为空 → `["各特征得分均低于 0.5，无明显 AI 特征（综合得分 {ai_score:.2f} → {verdict 中文}）"]`；非空 → 末尾追加阈值说明行 `（综合得分 {ai_score:.2f} → {verdict 中文}）`。

> **启发式定位声明**: 上述阈值（cv=1.0、d_ex=0.005、d_el=0.004、r∈[0.05,0.75]、TTR=0.45、c=0.06、n_p=8、verdict 0.35/0.65）是基于常见中文小说文本形态的**经验常量**（代码常量，不配置化——YAGNI）；评分是「统计形状相似度」而非身份鉴定（§1 边界声明）；阈值校准（用标注数据集回归）归 Phase 2+（§10）。

### 5.5 词汇分析（零依赖词块基础板块 + jieba 精确分词增强 — Q2=C）

基于 §5.2 token 化输出，纯函数 `_analyze_lexical`（基础板块，始终计算）:

| 字段 | 计算 | 说明 |
|------|------|------|
| total_words | len(tokens) | token 总数（连续汉字串/英文单词 = 1 token） |
| unique_words | len(set(tokens)) | 不同 token 数 |
| top_words | Counter 统计 Top-10，`(count DESC, first_index ASC)` 排序 | 高频词观测（「说」「她」「林晚」等叙事高频词） |
| avg_word_length | 总 token 字符数 / total_words（保留 2 位） | 中文词块平均长度 ~2-3 字符 |
| stopword_ratio | 停用词 token 数 / total_words（保留 4 位） | 停用词占比（叙事填充度观测） |
| jieba | `_analyze_jieba`（jieba 增强板块） | 见下方「jieba 增强」小节 |

**停用词表（代码常量 `_STOPWORDS`，§12 论证规模）**:

```python
# 常用中文虚词/高频功能词（叙事文本观测；表为代码常量，不配置化——YAGNI）
_STOPWORDS: frozenset[str] = frozenset({
    "的", "了", "是", "在", "我", "你", "他", "她", "它", "我们", "你们", "他们",
    "着", "过", "不", "也", "都", "就", "说", "道", "啊", "呢", "吧", "吗",
    "很", "太", "又", "这", "那", "个", "与", "和", "及", "或", "但", "而",
    "却", "还", "再", "只", "被", "把", "让", "对", "向", "从", "到", "于",
    "以", "之", "其", "等", "已经", "没有", "一个", "自己", "时候", "现在",
})
```

**jieba 精确分词增强（Q2=C 拍板）**:

纯函数 `_analyze_jieba(clean_text)` → `JiebaAnalysis`（§2.5）:

| 步骤 | 规则 |
|------|------|
| 分词 | `jieba.lcut(clean_text, cut_all=False)`（**精确模式**——默认词典，无网络依赖） |
| 统计 | 与正则词块**同构统计**：`jieba_total_words = len(tokens)` / `jieba_unique_words = len(set(tokens))` / `jieba_avg_word_length`（保留 2 位）/ `jieba_top_words`（Top-10，`(count DESC, first_index ASC)` 排序，`first_index` = jieba token 序列首次出现序号，§2.5） |
| 停用词过滤 | **对 jieba 板块同样生效**（`_STOPWORDS` 过滤后才统计 top_words/unique_words，与基础板块同规则） |
| 空文本 | `clean_text` 为空 → `jieba=None`（§2.4） |

> **快照断言确定性论证（Q2=C）**: ① **词典版本锁定**——jieba 词典随包分发，版本由 `backend/uv.lock` 锁定（ADR-025），CI `uv sync --frozen` 保证环境一致 → 同一文本同一 jieba 版本 → 分词结果确定；② **测试文本固定**——测试用例喂固定中文字符串，快照断言对 jieba 板块同样成立（§9）；③ **首次调用词典缓存**——jieba 首次 `lcut` 构建词典缓存（约 1s，测试可接受，不构成 CI 瓶颈）；④ **本地词典无网络依赖**——jieba 词典随 wheel 分发，测试/CI 不触发下载（与 F14 BGE 模型下载场景不同，§9 CI 无网络约束）。

> **token 化规则差异（正则词块 vs jieba）**: 正则 = 连续 CJK 串/拉丁串（「林晚推开窗」= 1 个词块）；jieba = 词典分词（「林晚」「推开」「窗」多词，且可切出「的」「了」「是」等单字功能词）——因此两套统计的 total/unique/avg/top_words 数值**通常不同**（§3.2 示例：正则 17 词 vs jieba 19 词），这是**预期差异**而非缺陷：基础板块给出「连续串粒度」观测，jieba 给出「词典粒度」观测；停用词过滤对两套都生效（单字功能词被过滤后不进 top_words）。

> **词汇分析的价值定位**: 不追求语言学意义的精确分词（§5.2 注），而是提供**可复现的多样性/复用度观测**——TTR 与高频词分布是「词汇贫乏」的可靠信号（AI 生成文本常见高频词集中），停用词占比反映叙事填充度。这些指标对分词边界不敏感（正则词块与 jieba 的统计在「连续汉字串」粒度上高度一致）；jieba 增强提供词典级精确词频（词云可视化等下游消费友好），确定性由 uv.lock 锁定词典版本保证（ADR-025）。

### 5.6 LLM 深度分析（可选 — Q1=C 拍板）

> AI 痕迹检测的**可选增强板块**（镜像 F14 `_timeline_extractor.py` 管线骨架——模板渲染 → LLM → JSON 解析 → 修复重试；domain/ 零 LangChain import 门禁不变：`StyleLLMAnalyzer` 在 `domain/services/` 内通过 ports Protocol 注入，同 `_timeline_extractor.py` 先例，ADR-015）。**默认关闭**：`llm_analysis` 三级覆盖（请求显式 → 项目配置 `extra["style_llm_analysis"]` → 默认 false，§2.8）；**仅独立入口可开启**——门面 STYLE 恒确定性（F14 `ExtractionRequest` 无 `llm_analysis` 字段，§8.2）。确定性 8 特征评分（§5.4）**始终计算**，LLM 板块是**附加参考**（`StyleReport.llm_assessment`，§2.7）。

**管线步骤（`StyleLLMAnalyzer.analyze(project, text) -> StyleLLMAssessment`）**:

| 步骤 | 说明 |
|------|------|
| ① 模板 | `PromptManager.load("style_llm_analysis")`（模板 `style_llm_analysis.yaml`，变量 `{text}`；system_prompt 要求 LLM 输出**严格 JSON**：`{"verdict": "likely_human\|uncertain\|likely_ai", "reasoning": "..."}`——格式镜像 `timeline_extract.yaml`） |
| ② 调用 | `LLMClient.chat(model or project.config.model, temperature=0.2)`——低温固定常量（同 F14 timeline 提取，F14 §5.5 先例）；`model` 来自请求/CLI 覆盖或项目配置 |
| ③ 解析 | 提取 JSON 片段（容忍代码块围栏/前后缀文字，同 `_timeline_extractor._extract_json_fragment` 逻辑）→ `json.loads` → 校验：`verdict ∈ {likely_human, uncertain, likely_ai}` 三值之一 + `reasoning` 非空字符串 |
| ④ 修复重试 | 解析/校验失败 → 修复式重试（附错误信息）**≤ 2 次** → 仍失败 → `StyleLLMAnalysisError`（500，§3.3/§7） |
| ⑤ 截断 | `reasoning` 超长截断 **≤ 2000 字符**（§2.7） |
| ⑥ 返回 | `StyleLLMAssessment(llm_verdict, reasoning, model, generated_at=now(UTC))` |

> **LLM 调用失败语义**: `LLMClient.chat` 抛 `LLMRequestError`（F5，网络/超时/Provider 错误）→ **透传**（不消耗解析重试，同 F14 timeline 提取要点 4）→ router 转 500（§3.3）。分析器未装配（deps 层 `llm_analyzer=None`，§8.1）→ `StyleLLMUnavailableError`（500「LLM 深度分析不可用」——镜像 F14 `RAGUnavailableError` 语义：可选能力未装配时显式报错而非静默降级，§7）。

> **非确定性声明（镜像 F14 测试模式）**: LLM 判断**不可快照断言**（模型输出随版本/温度波动）——测试一律用 **Mock LLM** 分支断言解析/重试/校验/截断逻辑，**不对 LLM 输出内容断言**（§9 test_style_llm_analyzer.py）；确定性验收基线（M1-M11 快照断言）只覆盖基础板块（§13）。空文本/未开启 → 不调用 LLM（`llm_assessment=None`，§7 边界表——Mock 分析器「未调用」断言，§9）。

### 5.7 编排伪代码（StyleService + 门面委托）

```python
# domain/services/style_service.py
class StyleService:
    """风格检测服务（spec §5）— 只读文本分析编排.

    依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:
    - F1 ProjectRepositoryProtocol.get 项目校验（§5.1 步骤 ①）
    - F2 ChapterRepositoryProtocol.get_chapter 章节读取（chapter_ids 模式，§5.1 步骤 ②）
    - llm_analyzer: StyleLLMAnalyzer | None = None（可选，Q1=C——LLM 深度分析器，
      仅 llm_analysis=true 时调用；None = 未装配 → llm_analysis=true 抛
      StyleLLMUnavailableError，§5.6/§8.1）
    （纯算法在 _style_analyzer.py 纯函数层，本类无算法逻辑）

    只依赖 domain/ports/ 与 domain/models/，不依赖任何 infrastructure 实现——
    domain/ 零框架 import 门禁天然满足（ADR-002/015）。
    """

    def __init__(
        self,
        *,
        project_repo: ProjectRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        llm_analyzer: StyleLLMAnalyzer | None = None,
    ) -> None: ...

    async def analyze(
        self,
        project_id: uuid.UUID,
        *,
        text: str | None = None,
        chapter_ids: list[uuid.UUID] | None = None,
        llm_analysis: bool | None = None,
    ) -> StyleReport:
        """风格分析编排（spec §5.1 步骤 ①-⑥）.

        Args:
            project_id: 所属项目 UUID.
            text: 手动文本（与 chapter_ids 互斥）.
            chapter_ids: 章节模式（从 F2 读取，按请求顺序合并为整体分析）.
            llm_analysis: LLM 深度分析开关（Q1=C，§2.8）——None = 跟随项目配置
                extra["style_llm_analysis"]（默认 false）; 门面路径显式传 False
                （恒确定性，§8.2）.

        Returns:
            StyleReport（source 标记 manual/chapter:<id>/chapters:<ids>，§2.6;
            含可选 llm_assessment 板块，§2.7）.

        Raises:
            ProjectNotFoundError: 项目不存在（404）.
            StyleValidationError: 输入校验失败（互斥/缺失/空文本/章节超长，422）.
            ChapterNotFoundError / ChapterNotInProjectError: 章节校验失败（422，F14 错误类）.
            StyleLLMUnavailableError: llm_analysis=true 且分析器未装配（500，§5.6）.
            LLMRequestError / StyleLLMAnalysisError: LLM 调用失败/解析重试耗尽（500，§5.6）.
        """
        project = await self._project_repo.get(_to_int_id(project_id))
        if project is None:
            raise ProjectNotFoundError()                       # ① 项目校验（404）
        if text is not None and chapter_ids is not None:
            raise StyleValidationError("text 与 chapter_ids 不能同时使用")
        if text is None and chapter_ids is None:
            raise StyleValidationError("必须提供 text 或 chapter_ids")
        if text is not None:                                   # ② 输入源解析（text 模式）
            stripped = text.strip()
            if not stripped:
                raise StyleValidationError("文本不能为空")
            clean_text, source = stripped, "manual"
        else:                                                  # ② 输入源解析（章节模式）
            chunks: list[str] = []
            for cid in chapter_ids or []:
                chapter = await self._chapter_repo.get_chapter(_to_int_id(cid))
                if chapter is None:
                    raise ChapterNotFoundError()               # F2 get 不含软删
                if chapter.project_id != project_id:
                    raise ChapterNotInProjectError()
                if len(chapter.content) > _MAX_CHAPTER_CHARS:
                    raise StyleValidationError("章节内容超过分析上限（50000 字符）")
                chunks.append(chapter.content)
            clean_text = "\n\n".join(chunks)                   # 章间 "\n\n" 分隔（§5.1 要点 5）
            source = f"chapter:{chapter_ids[0]}" if len(chapter_ids) == 1 \
                else f"chapters:{','.join(str(i) for i in chapter_ids)}"
        # ③④⑤ 预处理 → 三块分析 → 组装（§5.2-§5.5，全部纯函数）
        stats = _analyze(clean_text)                           # 一次预处理 + token 化（共享快照）
        warnings: list[str] = []
        if len(chapter_ids or []) > 1:
            warnings.append("多章节合并分析（单章粒度分析归 Phase 2+）")
        if stats.sentence_count == 0:
            warnings.append("未检测到完整句子（句尾符不足）——句子统计仅供参考")
        if stats.total_words == 0:
            warnings.append("文本无有效词条（仅标点/空白）——词汇统计为空")
        report = StyleReport(
            project_id=project_id, source=source,
            generated_at=datetime.now(UTC),
            fingerprint=_analyze_fingerprint(stats),
            ai_trace=_analyze_ai_trace(stats),
            lexical=_analyze_lexical(stats),
            warnings=warnings,
        )
        # ⑥ LLM 深度分析（可选，Q1=C）——三级判定 + 仅独立入口
        if _resolve_llm_analysis(llm_analysis, project):       # 请求显式 → extra["style_llm_analysis"] → false
            if self._llm_analyzer is None:
                raise StyleLLMUnavailableError("LLM 深度分析不可用")
            report.llm_assessment = await self._llm_analyzer.analyze(
                project=project, text=clean_text,
            )
        return report
```

```python
# domain/services/extraction_service.py — F16 声明的 MODIFY（§8.2，门面 STYLE 委托）
async def _dispatch(self, request, source, project) -> _Normalized:
    ...
    elif request.type is ExtractionType.STYLE:
        result = await self._style_service.analyze(
            project_id=request.project_id,
            text=request.text if request.chapter_ids is None else None,
            chapter_ids=request.chapter_ids,
            llm_analysis=False,                # 门面恒确定性（Q1=C/§8.2）: ExtractionRequest
        )                                        # 无 llm_analysis 字段——LLM 深度分析仅独立入口
        return _Normalized(
            created=0, updated=0,                # style 无实体产物（§5.3 归一）
            warnings=list(result.warnings),      # StyleReport.warnings 透传顶层（§8.2）
            model=None,                          # 门面路径不调用 LLM（恒确定性）
            detail=result.model_dump(mode="json"),
            raw=result,
        )
```

### 5.8 确定性文本分析 vs 既有样板：差异对照表

| 维度 | F12 检查（样板） | F15 审计（样板） | F16 分析（本模块） |
|------|------------------|------------------|------------------|
| 建模对象 | 新实体档案（事件） | 无新实体（纯报告模型） | **无新实体表（纯报告模型）** |
| 输入 | 事件档案（库内） | 5 套档案快照（库内） | **文本内容（text / chapter_ids，二选一）** |
| 引擎 | 确定性算法（单档案） | 确定性规则引擎（跨档案） | **确定性统计 + 启发式评分（文本）+ LLM 深度分析可选（默认关闭，§5.6）** |
| 新增管线 | 0 | 0 | **1 条可选（LLM 深度分析——默认关闭，仅独立入口可开启，§5.6）** |
| 副作用 | 无副作用 | 无副作用 | **无副作用（只读）** |
| 幂等性 | 严格幂等 | 严格幂等 | **严格幂等（同文本同报告，快照断言）** |
| 落库 | 无 | 无 | **无（风格报告不落库，§10）** |
| 错误面 | 无 LLM | 仅 NOT_FOUND / DB_ERROR | **NOT_FOUND + VALIDATION_ERROR(422) + DB_ERROR + LLM 相关 500（仅 llm_analysis=true 时可达）** |
| 测试方式 | 快照断言 | Mock 各模块仓储 + 快照断言 | **纯函数数值断言（算法）+ Mock 仓储（服务）+ Mock LLM（LLM 分析器，§9）** |
| 跨模块 | 无 | 读取 6 模块 + 委托 F12，零 MODIFY | **读取 F1/F2 + MODIFY F14 注册表（既定落点，§8.2）** |
| 入口 | GET check | GET /audit | **F14 门面（保留）+ POST /style/analyze（独立）** |

---

## 6. 风格报告组织规则

（对应 F12 §6「事件与双线语义」、F14 §6「类型注册表」、F15 §6「维度组织」的位置；F16 无实体，本节承载报告板块组织、verdict 阈值语义、排序与证据规则）

### 6.1 报告板块组织与内部一致性

- **三大板块**（验收标准 ① 风格指纹 / ② AI 痕迹 / ③ 词汇分析 的直接表达）固定为 `StyleReport.fingerprint / ai_trace / lexical`——板块封闭（不随文本变化增删）；**`llm_assessment` 是可选板块**（仅 `llm_analysis=true` 且 LLM 可用时出现，否则 None——Q1=C 拍板，§2.6/§2.7）；`lexical` 内含 jieba 增强子板块（Q2=C，§2.4/§2.5）
- **单次共享统计快照**：三板块共享同一次预处理 + token 化（§5.1 要点 3/§5.2）——`vocabulary_richness`（指纹）与 `lexical` 同源（§2.2 注），报告内部数值自洽（同一文本两个板块不会出现矛盾的词汇计数）
- **口径统一**：所有密度/均值的分母是同一 `char_count`（去空白字符数，§5.2）；报告内不混用其他字数口径（与 F2 word_count 的差异声明见 §5.3 注）

### 6.2 verdict 阈值语义

| ai_score 区间 | verdict | 中文结论（CLI 摘要） | 语义 |
|---------------|---------|----------------------|------|
| ≤ 0.35 | `likely_human` | 「倾向人类创作」 | 统计形状更接近人类写作（句式波动大、情绪/省略标点丰富、词汇多样） |
| (0.35, 0.65) | `uncertain` | 「特征不明显」 | 无明显倾向——文本过短、风格中性或混合创作，**不作断言** |
| ≥ 0.65 | `likely_ai` | 「倾向 AI 生成」 | 统计形状更接近常见 AI 生成文本（句式整齐、标点单调、词汇复用集中） |

- `ai_score` = 特征得分**等权均值**（§5.4）；权重差异化需标注数据回归校准，归 Phase 2+（§10）——等权可预测、可测试（表驱动断言）
- verdict 是**报告数据**而非进程状态：CLI 退出码恒 0（成功执行，同 F15 Q1 拍板语义——「发现问题」是结果非执行错误；脚本用 `--json` 的 `data.ai_trace.verdict` 判断）
- **过短文本（char_count < 100）**: 报告照常输出但 `warnings` 加「文本过短（< 100 字符）——统计特征仅供参考」；`sentence_uniformity` / `paragraph_uniformity` 的失真特征 note 加「样本不足」后缀且**不进 evidence**（§5.4 边界语义）
- **证据规则**（§2.3/§5.4）: evidence 只列 score ≥ 0.5 的特征（倾向 AI 的依据）；「倾向人类」不逐条列证据（人类特征是默认态，反证才值得看）

### 6.3 报告排序与去重

- **top_words 排序**: `(count DESC, first_index ASC)`——主键数字确定、次级键 ASCII 序号稳定；**不用词条文本作排序键**（中文 Unicode 码点序与作者直觉不符、测试断言易与实现冲突——F15 实测教训，§2.1/§2.10 论证）
- **features 排序**: `feature ASC`（ASCII 稳定键字典序）——完全确定性，快照断言友好
- **evidence 排序**: `(score DESC, feature ASC)`
- **去重**: top_words 由 Counter 统计天然无重复词条（同一 token 只出现一次）；features 由固定特征表生成天然无重复（8 个恒定）；报告内无「同词多次」问题

### 6.4 重复执行与幂等

- 风格分析是**手动触发**的只读计算（API/CLI），无自动触发/定时任务（F25 daemon 已移除，ADR-029——自动触发由外部 agent 经 F20 MCP / skills 调用，§10）
- **重复执行幂等**: 同一项目同一输入两次分析 → 报告**基础板块**（fingerprint/ai_trace/lexical，含 jieba）逐字段相等（快照断言可证）；文本变更后重跑即反映新状态（无增量状态需要维护——同 F12/F15 要点）。**LLM 板块（llm_assessment）不可快照断言**——LLM 输出非确定性，重复执行可能不同；确定性验收基线只覆盖基础板块（§5.6/§9/§13）
- 分析**不感知** F14 的增量提取机制（`extraction_runs`）：STYLE 在门面中**每次执行**（同 timeline 关闭语义——确定性只读计算廉价，无 skip 价值，§8.2/F14 §5.2 先例）

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 项目不存在 | 404: "项目不存在"（服务层统一校验，§5.1 步骤 ①） |
| 无效 UUID 格式（project_id） | 404（统一 `_parse_id` 处理，同 F9-F15） |
| text 与 chapter_ids 同时提供 | 422: "text 与 chapter_ids 不能同时使用"（服务层校验；门面路径由 F14 `ExtractionRequest` model_validator 先拦截，同文案） |
| text 与 chapter_ids 均未提供 | 422: "必须提供 text 或 chapter_ids" |
| text 为空 / 全空白 | 422: "文本不能为空"（strip 后空串；Pydantic 与服务层双重校验） |
| text 超 50000 字符 | 422（Pydantic `StyleAnalyzeRequest` 校验，同 F14 text 约束） |
| chapter_ids 空列表 | 422（Pydantic：不能为空列表，同 F14） |
| chapter_ids 指向不存在/软删章节 | 422: "章节不存在"（F2 get 不含软删；复用 F14 `ChapterNotFoundError`） |
| chapter_ids 指向其他项目章节 | 422: "章节不属于该项目"（复用 F14 `ChapterNotInProjectError`） |
| 章节内容超 50000 字符 | 422: "章节内容超过分析上限（50000 字符）"（同 F14 提取上限口径） |
| 多章合并（≥ 2 章） | 200：按请求顺序合并为整体分析；source=`chapters:<ids>`；warnings 含「多章节合并分析」提示 |
| 空文本项目（无章节内容/纯空白章节） | 200：fingerprint/lexical 全 0、ai_trace 中性（features score 按 §5.4 边界规则，total_words=0 特征取 0.5）；warnings 含「文本无有效词条」 |
| 文本过短（char_count < 100） | 200：报告照常输出 + warning「文本过短——统计特征仅供参考」；sentence/paragraph uniformity 特征 note 加「样本不足」且不进 evidence（§6.2） |
| 无句尾符文本（sentence_count = 0） | 200：avg_sentence_length/sentence_length_std 为 0；warning「未检测到完整句子——句子统计仅供参考」 |
| 无有效词条文本（纯标点/数字） | 200：total_words=0、top_words 空、stopword_ratio=0；warning「文本无有效词条」；ai_trace 中性特征处理（§5.4 边界） |
| 对话引号未配对（奇数个引号） | 200：按出现顺序交替切换对话态（§5.2 规则）——对话统计是近似值，不报错 |
| llm_analysis=true 且 LLM 分析器未装配（deps 层可选装配，§8.1） | **500: "LLM 深度分析不可用"**（`StyleLLMUnavailableError` 透传，消息即 detail——镜像 F14 `RAGUnavailableError` 语义：可选能力未装配显式报错而非静默降级；分析器装配在 deps 层，测试 Mock） |
| llm_analysis=true 且 LLM 调用失败（网络/超时/Provider 错误） | 500（`LLMRequestError` 透传，F5 错误类——不消耗解析重试，§5.6） |
| llm_analysis=true 且解析重试耗尽（修复式重试 ≤2 仍失败） | 500（`StyleLLMAnalysisError` 透传，同 F14 `TimelineExtractionError` 语义，§5.6） |
| llm_analysis 缺省 None（请求/CLI 均未指定） | 跟随项目配置 `extra["style_llm_analysis"]`（默认 **false**，不调用 LLM → `llm_assessment=None`）——三级覆盖判定在服务层（§2.8/§5.6） |
| jieba 未装配（理论不可达——jieba 是必装运行时依赖，防御性） | 200：`lexical.jieba=None` + warning「jieba 增强板块不可用」——不阻塞基础词汇统计（§2.4/§5.5） |
| 项目仓储 / 章节仓储读取失败（DB 错误） | 抛异常 → 500（全局处理器，loguru；不产出部分报告，§5.1 要点 6） |
| F14 门面 type=style + index=true | 200 + indexed=false + warning "style 类型不支持自动索引"（style 不在 RAG 范围——F14 §2.4 已声明；`_indexing_enabled` STYLE 恒 False，§8.2） |
| F14 门面 type=style + force=true | 200（force 对 STYLE 无意义——每次执行无增量 skip；参数照常接受不报错，同 outline 先例） |
| F14 门面 type=style 携带 outline/timeline 专属参数（prompt/num_chapters/auto_extract 等） | 422（F14 `_validate_input` style 行修订：类型不匹配字段一律 422 显式报错，§8.2） |
| CLI style analyze 三选一均未提供 | 退出码 2（Typer 必选参数校验） |
| CLI style analyze --text 与 --text-file 同时使用 | 退出码 2（同 F9/F14 先例） |
| CLI style analyze --chapters 含非法 UUID | 退出码 1 + NOT_FOUND 信封（`_parse_uuid` 同 F14） |
| CLI 项目不存在 / 无效 UUID | 退出码 1 + NOT_FOUND 信封（同 F12/F15 先例） |
| CLI 分析发现 likely_ai | 退出码 **0**（成功执行；结论是「结果」而非「执行错误」——同 F15 Q1 语义）；人类可读摘要显示「⚠ 倾向 AI 生成」 |
| CLI --json 输出 | 完整 StyleReport（model_dump(mode="json")），信封 {"ok": true, "data": ...} |
| 删除 StyleNotImplementedError 后的占位测试同步 | `test_extraction_service.py` 的 `test_style_raises_not_implemented` / `test_style_project_not_found_first` 与 `test_cli_extraction.py` 的 `test_run_style_unsupported` **必须同步更新**为 style 成功路径用例——这是 F16 落地后的预期行为（§8.2/§12 声明） |

---

## 8. 文件结构

遵循 ADR-007v2 包结构，与真实源码树一一对应。新增/修改文件（**对照主仓 `backend/src/inkflow/` 真实树逐文件核对**——F9-F15 已合入 main，本节声明全部基于现行树；F16 除 F14 注册表（既定落点）与占位测试同步外**零跨模块 MODIFY**，§12）：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── style.py            ← CREATE: WordFrequency, StyleFingerprint, AITraceVerdict,
│   │   │                             AITraceFeature, AITraceAssessment, LexicalAnalysis,
│   │   │                             JiebaAnalysis, StyleLLMAssessment, StyleReport（§2）
│   │   └── __init__.py         ← MODIFY: 导出新模型
│   ├── ports/
│   │   ├── style_errors.py     ← CREATE: StyleServiceError / StyleValidationError（422）；
│   │   │                             StyleLLMUnavailableError / StyleLLMAnalysisError（500 家族，
│   │   │                             Q1=C——LLM 深度分析错误，§3.3/§7）；
│   │   │                             ProjectNotFoundError 复用 F9 character_errors、
│   │   │                             章节错误复用 F14 extraction_errors（§3.3 注——
│   │   │                             F14 先例: 通用名错误类不重复定义，避免遮蔽既有 router）
│   │   └── __init__.py         ← MODIFY: 导出
│   └── services/
│       ├── _style_analyzer.py  ← CREATE: 纯函数算法层（§5.2-§5.5）——_preprocess /
│       │                             _tokenize / _analyze_fingerprint / _analyze_ai_trace /
│       │                             _analyze_lexical / _analyze_jieba（Q2=C）/ 常量
│       │                             （_TOKEN_RE / _STOPWORDS / N=10 / 阈值），镜像
│       │                             _chunking.py 先例（纯函数、无 I/O）
│       ├── _style_llm_analyzer.py ← CREATE（Q1=C）: StyleLLMAnalyzer——LLM 深度分析管线
│       │                             （模板渲染 → LLM → JSON 解析 → 修复重试 ≤2 → 截断），
│       │                             镜像 _timeline_extractor.py 骨架；构造注入 llm_client
│       │                             （LLMClientProtocol）+ prompt_manager（PromptTemplateProtocol）
│       │                             + 模板名常量 _TEMPLATE_NAME = "style_llm_analysis"
│       ├── style_service.py    ← CREATE: StyleService（analyze 编排：项目校验 + 章节
│       │                             读取合并 + 组装 StyleReport + 可选 LLM 深度分析；
│       │                             构造注入 project_repo + chapter_repo +
│       │                             llm_analyzer=None（可选），§8.1）
│       └── __init__.py         ← MODIFY
├── infrastructure/
│   └── llm/templates/
│       └── style_llm_analysis.yaml ← CREATE（Q1=C）: LLM 深度分析模板（name/description/
│                                       system_prompt/human_prompt/variables{text}——
│                                       格式镜像 timeline_extract.yaml；system_prompt 要求
│                                       严格 JSON: {"verdict": "likely_human|uncertain|likely_ai",
│                                       "reasoning": "..."}，§5.6）
├── api/
│   ├── routers/
│   │   ├── style.py            ← CREATE: POST /api/v1/projects/{project_id}/style/analyze
│   │   │                             （StyleAnalyzeRequest DTO: text|chapter_ids 互斥 +
│   │   │                             llm_analysis 可选 + 空文本/超限/空列表校验；§2.8/§3）
│   │   └── __init__.py         ← MODIFY
│   ├── deps.py                 ← MODIFY: get_style_service（复用 SQLiteProjectRepository +
│   │                                SQLiteChapterRepository 装配 + 可选 StyleLLMAnalyzer
│   │                                （LangChainLLMClient + LangChainPromptManager），见 §8.1）
│   └── app.py                  ← MODIFY: 注册 style.router
└── cli/
    ├── commands/
    │   ├── style.py            ← CREATE: style 组（analyze 1 命令，人类可读摘要 + --json +
    │   │                             --llm-analysis/--no-llm-analysis，镜像 F15 audit 组风格，§4）
    │   └── __init__.py         ← MODIFY
    └── app.py                  ← MODIFY: 注册 style 命令组
```

```text
backend/tests/unit/
├── test_style_models.py        ← CREATE: 报告模型/DTO 校验（枚举/字段默认值/序列化/互斥；
│                                    含 JiebaAnalysis / StyleLLMAssessment / llm_assessment=None 默认）
├── test_style_analyzer.py      ← CREATE: 算法纯函数（§9：预处理/token 化/指纹/AI 痕迹/词汇
│                                     全分支数值断言——核心测试面，不 Mock；含 jieba 增强用例，Q2=C）
├── test_style_llm_analyzer.py  ← CREATE（Q1=C）: LLM 深度分析器（Mock LLM——合法 JSON / 围栏提取 /
│                                     修复重试 ≤2 / verdict 非法 / reasoning 截断 / 空文本不调用）
├── test_style_service.py       ← CREATE: 服务编排（Mock project_repo + chapter_repo + llm_analyzer：
│                                     项目校验/输入互斥/章节校验/合并/source 标记/warnings/
│                                     确定性快照断言 + llm_analysis 三级判定/未装配错误）
└── test_style_api.py           ← CREATE: API 集成（Mock StyleService，POST /style/analyze +
                                     llm_analysis 透传 + 500 透传）

tests/cli/
└── test_cli_style.py           ← CREATE: CLI 测试（Mock StyleService，信封/退出码/摘要 +
                                     --llm-analysis 透传）
```

**F16 声明的 F14 文件 MODIFY（既定落点 + 占位同步）**:

```text
backend/src/inkflow/
├── domain/
│   ├── services/extraction_service.py ← MODIFY F14: ① _handlers[STYLE] = self._style_service.analyze
│   │                                        （注册 handler，§8.2）；② _validate_input 加 STYLE 分支
│   │                                        （style 必须提供 text 或 chapter_ids——§6.4 style 行
│   │                                        修订的落地）；③ _resolve_sources 加 STYLE 分支
│   │                                        （返回固定 "full" 源、每次执行，§8.2）；④ _dispatch 加
│   │                                        STYLE 分支（委托 StyleService + 归一，§5.7）；⑤
│   │                                        _indexing_enabled STYLE 恒 False + warning 文案
│   │                                        「outline/timeline/style 类型不支持自动索引」
│   ├── ports/extraction_errors.py ← MODIFY F14: 删除 StyleNotImplementedError（F16 落地后
│   │                                        占位错误无意义，§12 论证）
│   └── __init__.py            ← MODIFY（如导出受影响）
├── api/routers/extractions.py ← MODIFY F14: _run_service 增加 except StyleValidationError → 422
│                                   （§3.3 注；docstring 同步）
└── cli/commands/extract.py    ← MODIFY F14: ① 删除 StyleNotImplementedError import 与
                                        UNSUPPORTED_TYPE 分支中该异常的捕获；② _run 增加
                                        except StyleValidationError → VALIDATION_ERROR；
                                        （--type style 现在正常执行，§4.1）
```

```text
backend/tests/unit/test_extraction_service.py ← MODIFY F14: test_style_raises_not_implemented →
                                                    style 成功路径用例（Mock StyleService 委托 +
                                                    归一断言）；test_style_project_not_found_first 保留
                                                    （项目校验先于 handler 的语义不变，断言改为
                                                    StyleService 未被调用）
tests/cli/test_cli_extraction.py               ← MODIFY F14: test_run_style_unsupported →
                                                    style 成功执行用例（退出码 0 + success 摘要/信封）
.github/workflows/ci.yml                       ← MODIFY: integration-cli-backend job 文件列表
                                                    显式加入 ../tests/cli/test_cli_style.py
specs/f14-extraction-service/spec.md           ← MODIFY（spec 同步修订，§8.2）
```

**F16 新增运行时依赖（Q2=C 拍板）**:

```text
backend/pyproject.toml  ← MODIFY: [project.dependencies] 增加 "jieba>=0.42"（精确分词增强，
                           Q2=C——版本区间由 ADR-025 流程评估；uv lock 更新）
backend/uv.lock         ← MODIFY: uv lock 更新（**实现阶段执行**——uv lock 命令随实现 PR
                           执行并提交，CI `uv sync --frozen` 依赖此变更才能通过；jieba 词典
                           版本由此锁定，保证快照断言确定性，§5.5）
```

> ⚠️ **CI 依赖声明（Q2=C）**: `backend/uv.lock` 的更新**必须先于**任何引用 jieba 的代码合入——CI 各 job 均以 `uv sync --frozen --extra dev` 安装依赖（ci.yml 实测），uv.lock 不含 jieba 时 `uv sync --frozen` 直接失败。实施顺序：① pyproject 加 jieba → ② `uv lock`（本地）→ ③ 实现 jieba 板块与测试 → ④ 提交（pyproject + uv.lock + 代码同 PR）。

> **与 F15 §8 的差异（测试布局）**: CLI 测试放顶层 `tests/cli/test_cli_style.py`（Issue #61 后的现行布局，同 F13/F14/F15）。**infrastructure/ 仅新增 LLM 模板文件**（`style_llm_analysis.yaml`，Q1=C）——无新表、无新仓储；唯一新增实现类 = 无（StyleService 只依赖既有 SQLite 仓储；StyleLLMAnalyzer 在 domain/services/ 内经 Protocol 注入，不依赖 infrastructure 具体类）。
>
> ⚠️ **CI 覆盖盲区防范（Issue #59/#61 教训）**: `tests/cli/test_cli_style.py` **默认不被任何 CI job 收集**——实施时必须将其**显式加入 ci.yml `integration-cli-backend` job 的 pytest 文件列表**（与现有 15 个 `../tests/cli/test_cli_*.py` 并列，当前列表: project_mock/chapter_mock/write/output/serve/config/llm/character/world/outline/timeline/foreshadowing/extraction/vector/audit；PowerShell 反引号续行、Windows 下 pytest 不展开 glob，须显式文件名——见 §9/§12）。`backend/tests/unit/` 新文件由 `unit-test-backend` job 的 `pytest tests/unit/` 自动覆盖（无需改 ci.yml）。

### 8.1 StyleService 构造与装配（镜像 F15 注入模式）

```python
# domain/services/style_service.py
class StyleService:
    """风格检测服务（spec §5）— 只读文本分析编排.

    依赖全部通过构造函数注入（ADR-015/ADR-009，测试注入 Mock）:
    - F1 ProjectRepositoryProtocol.get 项目校验（§5.1 步骤 ①）
    - F2 ChapterRepositoryProtocol.get_chapter 章节读取（chapter_ids 模式，§5.1 步骤 ②）
    - llm_analyzer: StyleLLMAnalyzer | None = None（可选，Q1=C——LLM 深度分析器；
      仅 llm_analysis=true 时调用；None=未装配 → llm_analysis=true 抛
      StyleLLMUnavailableError，§5.6/§7）

    只依赖 domain/ports/ 与 domain/models/（Protocol 与纯 Pydantic 模型），
    不依赖任何 infrastructure 实现——domain/ 零框架 import 门禁天然满足（ADR-002/015）。
    算法全部在 _style_analyzer.py 纯函数层（§5.2-§5.5），本类无算法逻辑。
    """

    def __init__(
        self,
        *,
        project_repo: ProjectRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        llm_analyzer: StyleLLMAnalyzer | None = None,
    ) -> None: ...

    async def analyze(
        self,
        project_id: uuid.UUID,
        *,
        text: str | None = None,
        chapter_ids: list[uuid.UUID] | None = None,
        llm_analysis: bool | None = None,
    ) -> StyleReport: ...
```

```python
# api/deps.py — MODIFY: 装配（复用既有 SQLite 仓储；F16 无新实现类）
def get_style_service(db: AsyncSession) -> StyleService:
    """获取 StyleService 实例（F16 风格检测服务，spec §5/§8）.

    装配: 复用 F1 SQLiteProjectRepository + F2 SQLiteChapterRepository——全部为既有实现，
    F16 无新增基础设施（§8）；LLM 深度分析器（Q1=C）为**可选装配**:
    StyleLLMAnalyzer(llm_client=LangChainLLMClient(), prompt_manager=LangChainPromptManager())
    ——复用 F5 基础设施（同 F14 TimelineExtractor 装配先例），llm_analysis=true 时才被调用；
    未装配（或构造失败降级为 None）→ llm_analysis=true 抛 StyleLLMUnavailableError（§5.6）。
    """
    return StyleService(
        project_repo=SQLiteProjectRepository(db),
        chapter_repo=SQLiteChapterRepository(db),
        llm_analyzer=StyleLLMAnalyzer(
            llm_client=LangChainLLMClient(),
            prompt_manager=LangChainPromptManager(),
        ),
    )
```

### 8.2 F14 门面 STYLE 槽位落地（F16 的既定落点 — 接口零变更）

**F14 spec §12 承诺的兑现**: 「STYLE 槽位 handler=None → 422，F16 落地后仅需注册 handler」。F16 在 `ExtractionService._handlers` 注册 `ExtractionType.STYLE: self._style_service.analyze`（构造注入 StyleService，§8.1）——**枚举/API/CLI 接口零变更**（F14 Q1 ✅ 选项 A）。配套改动（均为 F16 声明的 F14 修订）：

| # | F14 位置 | 现状（占位） | F16 落地后 | 说明 |
|---|----------|-------------|-----------|------|
| 1 | `_handlers` 注册表（§6.1） | `STYLE: None` | `STYLE: self._style_service.analyze` | 注册 handler（F14 §12 承诺兑现） |
| 2 | `extract()` 步骤 ② | handler=None → `StyleNotImplementedError`（422） | handler 命中 → 继续执行 | 占位错误不再抛出 |
| 3 | `_validate_input`（§6.4 style 行） | 「无效（422 未实现优先）」 | **必须提供 text 或 chapter_ids 其一**（互斥由 ExtractionRequest model_validator 保证） | 注册 handler 的必然结果（§12 论证） |
| 4 | `_resolve_sources` | —（不可达） | STYLE 分支返回 `[_Source(key="full", label="full", hash=_content_hash(""), skip=False)]` | **每次执行**（同 outline / timeline 关闭语义——确定性只读计算廉价，无 skip 价值，F14 §5.2 先例） |
| 5 | `_run_sources` | — | 照常 upsert run 记录（source_key="full"） | 增量状态可观测（`extract status` 可见 style 最近分析时间） |
| 6 | `_dispatch`（§5.3 归一） | —（不可达） | 委托 `StyleService.analyze` → `_Normalized(created=0, updated=0, warnings=result.warnings, model=None, detail=StyleReport.model_dump, raw=result)` | 结果归一（镜像 timeline 关闭 ConsistencyReport 先例；created/updated=0——无实体产物） |
| 7 | `_indexing_enabled` / index warning（§5.3） | — | STYLE 恒 False + warning「style 类型不支持自动索引」 | style 不在 RAG 范围（F14 §2.4 已声明 outline/style 不在向量索引范围） |
| 8 | `extraction_errors.py` | `StyleNotImplementedError` | **删除该类** | F16 落地后占位错误无意义（§12 论证）；同步更新 extract CLI 的 UNSUPPORTED_TYPE 分支与占位测试 |
| 9 | extractions router / extract CLI | 异常映射含 StyleNotImplementedError | 删除该异常引用 + 增加 `StyleValidationError` → 422 / VALIDATION_ERROR 映射 | §3.3 注/§8 |
| 10 | F14 spec 同步修订 | §1 边界声明 / §6.1 注册表 / §6.4 / §7 / §11 / §12 STYLE 占位表述 | 改为「F16 ✅ 已注册 handler」 | spec 修订与实现同 PR 合入（§12） |

> **错误面替换声明**: F16 落地后 STYLE 的错误面从「422 未实现」变为 F16 标准错误面 = `ProjectNotFoundError`(404) + `StyleValidationError`(422) + F14 章节校验错误(422) + DB 错误(500) + **LLM 相关 500（仅独立入口 llm_analysis=true 时可达）**（§3.3 异常映射表）——**StyleNotImplementedError 不再被抛出**（删除该类，§12 论证：占位错误随占位 handler 一起退役，接口层 `UNSUPPORTED_TYPE` 错误码对 style 不再可达）。
>
> **门面恒确定性重申（Q1=C/Q3=B）**: 门面路径委托 `StyleService.analyze` 时**显式传 `llm_analysis=False`**（§5.7 编排伪代码）——F14 `ExtractionRequest` **无 `llm_analysis` 字段**（接口零变更，F14 Q1 ✅ 选项 A 承诺），LLM 深度分析**仅独立入口可开启**（`style analyze --llm-analysis` / `StyleAnalyzeRequest.llm_analysis`）；门面 STYLE 的 `model=None`、`llm_assessment` 恒 None（§2.8/§5.1 要点 8）。
>
> **依赖与配置变更（v1.1）**: F16 无 RAG、无新表；**新增运行时依赖 jieba**（Q2=C——`backend/pyproject.toml` + `backend/uv.lock` 变更，ADR-025 流程，§8/§11）；**`core/config.py` 零变更**——设置项 `style_llm_analysis` 走 F1 `ProjectConfig.extra` 模式（项目级扩展字典，无需全局 schema 变更，§2.8）；LLM 深度分析模板 `style_llm_analysis.yaml` 为 infrastructure 新增文件（§8）。阈值/停用词表/高频词 N 仍为代码常量（YAGNI）。

---

## 9. 测试策略

### 测试层次（沿用 ADR-018 三层目录 + pytest markers；层次结构同 F12/F13/F15 §9）

```text
单元测试: 报告模型/DTO 校验（枚举、字段、序列化、互斥）        ~12 cases
算法测试: _style_analyzer 纯函数（数值断言，不 Mock——核心面）   ~45 cases（含 jieba 增强，Q2=C）
LLM 分析器: _style_llm_analyzer（Mock LLM——解析/重试/校验/截断） ~8 cases（Q1=C）
服务测试: StyleService 编排（Mock project_repo + chapter_repo + llm_analyzer） ~20 cases
API 测试: POST /style/analyze（Mock StyleService）             ~12 cases
CLI 测试: style 组（Mock StyleService）                        ~12 cases
```

### 关键测试场景

**报告模型（test_style_models.py）**: WordFrequency 三字段 / StyleFingerprint 默认值（全 0 与空列表）/ AITraceVerdict 三值 / AITraceAssessment 默认值（ai_score=0.0、verdict=uncertain）/ LexicalAnalysis 默认值（jieba=None）/ JiebaAnalysis 四字段 / StyleLLMAssessment 四字段 / StyleReport 完整序列化（model_dump(mode="json") 全字段，llm_assessment=None 序列化为 null）/ StyleAnalyzeRequest llm_analysis 缺省 None / 数值类型约束（score 越界 422——Pydantic ge/le 校验，若实现加约束）

**算法纯函数（test_style_analyzer.py — 核心测试面，~40 cases）**:
- **预处理**: 去空白（含全角空格 \u3000）/ 句子切分（。！？!?…；; 及换行全句尾符、连续句尾符不产生空句子、「……」不产生空句子）/ 段落切分（空段落过滤）/ 标点计数（中文+英文标点集合、感叹号、省略号「……」计 2 次）/ 对话检测（“”配对、「」配对、""配对、未配对交替切换、对话内嵌套标点不干扰）
- **token 化**: 中文连续串 / 英文单词 / 数字 / 混合文本（中英混排）/ 标点与空白不构成 token / 空文本 → 空 tokens / 纯标点文本 → 空 tokens / first_index 正确（重复词取首次出现下标）
- **风格指纹**: 构造固定文本 → 断言全部 12 项数值（char_count/句子数/均值/标准差/密度/对话占比/TTR/top_words）——**快照断言范式**（固定输入固定输出）/ 无句尾符 → sentence_count=0 且均值/标准差为 0 / 单句 → std=0 / total_words=0 → TTR=0 / 空文本 → 全 0
- **AI 痕迹**: 8 特征逐一断言评分函数边界（score=0 / score=1 / 中间值，表驱动）/ 句长完全整齐（cv=0）→ sentence_uniformity score=1.0 / 感叹号密集 → exclamation_density_low score=0 / 对话占比 0.4 → dialogue_ratio_extreme score=0、占比 0.0 → score=1.0 / TTR 0.3 → vocabulary_richness_low score=1.0、0.7 → 0 / top1 占比 15% → top_word_concentration score=1.0 / 标点 3 种 → punctuation_variety_low score=0.625 / total_words=0 → 相关特征中性 0.5 / ai_score 等权均值断言 / verdict 阈值三档断言（0.35 边界、0.65 边界）/ evidence 规则（score≥0.5 入选、排序、空证据单条说明、过短文本 uniformity 不进 evidence）
- **词汇分析（基础板块）**: total_words/unique_words/avg_word_length/stopword_ratio 数值断言 / top_words 排序（count DESC、同频 first_index ASC）/ 停用词命中（「的」「了」等）/ 空文本 → 全 0
- **词汇分析（jieba 增强板块，Q2=C）**: 固定中文文本 → `jieba.lcut` 分词统计断言（jieba_total_words/jieba_unique_words/jieba_avg_word_length/jieba_top_words 排序/停用词过滤——与正则词块对比断言「jieba 切出单字词」：如「林晚推开窗」正则 1 词块 vs jieba 3 词，且「的」「了」等单字功能词被 `_STOPWORDS` 过滤后不进 jieba_top_words）/ jieba 板块与基础板块同源文本一致性（同一 clean_text）/ 空文本 → jieba=None / 纯标点文本 → jieba=None（或全 0 语义按实现，与 §2.4 一致）

**LLM 深度分析器（test_style_llm_analyzer.py，Mock LLM — 镜像 test_timeline_extractor.py 模式，Q1=C）**:
- 合法 JSON 输出 → StyleLLMAssessment（verdict/reasoning/model/generated_at 断言）
- 代码块围栏包裹的 JSON → 提取成功（`_extract_json_fragment` 逻辑）
- 非法 JSON（语法错误/非对象/缺字段）→ 修复式重试，重试后合法 → 成功；**修复重试 ≤2 次耗尽仍失败 → StyleLLMAnalysisError**
- verdict 非法值（非三值之一）→ 重试；reasoning 为空 → 重试
- reasoning 超长（>2000 字符）→ 截断 ≤2000 字符
- 空文本 → **不调用 LLM**（Mock 断言 chat 未被调用）
- LLMRequestError 透传（不消耗解析重试——chat 抛错 → 直接透传）
- 模板渲染（PromptManager.load("style_llm_analysis") + render {text}）断言

**服务编排（test_style_service.py，Mock project_repo + chapter_repo + llm_analyzer）**:
- 项目校验：project_repo.get → None → ProjectNotFoundError（404 语义）；**项目校验先于输入校验**（project 为 None 且输入非法 → 仍抛 ProjectNotFoundError，同 F14 占位测试保留语义）
- 输入校验：text 与 chapter_ids 同给 → StyleValidationError「不能同时使用」/ 均缺 → 「必须提供」/ text 空白 → 「文本不能为空」
- 章节模式：章节不存在 → ChapterNotFoundError / 跨项目 → ChapterNotInProjectError / 内容超 50000 → StyleValidationError / 单章 → source="chapter:<id>" / 多章 → 按请求顺序合并（断言合并文本 = 章 1 + "\n\n" + 章 2）且 source="chapters:<ids>" + warning「多章节合并分析」
- 手动模式：source="manual"、无章节读取（Mock chapter_repo 未被调用断言）
- warnings 组合：多章 + 无句尾符 + 无词条三条件组合断言
- 确定性/快照：同一 Mock 输入两次 analyze → 报告**基础板块**逐字段相等
- 失败传播：chapter_repo.get 抛异常 → analyze 抛异常（不产出部分报告）
- **llm_analysis 三级判定（Q1=C）**：① 请求显式 `llm_analysis=True` → 调用 llm_analyzer（Mock 断言被调用）且 llm_assessment 注入报告；② 请求显式 `llm_analysis=False` → 不调用（Mock 断言未调用）；③ 请求 None + 项目配置 `extra["style_llm_analysis"]=True` → 调用；④ 请求 None + 无配置（默认 false）→ 不调用（Mock 断言未调用）
- **llm_analysis=True 且 llm_analyzer=None（未装配）→ StyleLLMUnavailableError**（500 语义）
- 开启 LLM 时报告含 llm_assessment 板块；关闭时 llm_assessment=None（快照断言）

**API（test_style_api.py，Mock StyleService）**: POST /style/analyze 成功路径（完整 StyleReport 序列化）/ 404 项目不存在（Service 抛 ProjectNotFoundError）/ 422 输入校验（Pydantic：text 超 50000、chapter_ids 空列表、text+chapter_ids 同给）/ 无效 UUID → 404 / 500 透传（仓储 DB 错误）/ 幂等性（两次 POST 相同响应体）/ **llm_analysis 透传**（请求体 `llm_analysis: true` → Mock 断言 Service 收到 True；`false` → False；缺省 → None）/ **500 透传（LLM 相关）**：Service 抛 StyleLLMUnavailableError / LLMRequestError / StyleLLMAnalysisError → 500 响应

**CLI（test_cli_style.py，Mock StyleService）**: analyze 人类可读输出（三大板块摘要 + jieba 行 + LLM 行（开启时）+ verdict 中文映射 + 高频词前 5 + warnings 逐条）/ --json 完整报告信封 / 三选一缺参 → 退出码 2（Typer）/ --text 与 --text-file 同时 → 退出码 2 / 项目不存在 → NOT_FOUND 信封退出码 1 / VALIDATION_ERROR 信封（Service 抛 StyleValidationError）/ DB_ERROR 信封 / LLM_ERROR 信封（Service 抛 StyleLLMUnavailableError / StyleLLMAnalysisError，Q1=C）/ 发现 likely_ai → 退出码 0（结论是结果非错误）/ **--llm-analysis 透传**（Mock 断言 Service 收到 True；--no-llm-analysis → False；缺省 → None）

**F14 占位测试同步（MODIFY）**: `test_extraction_service.py` 的 `test_style_raises_not_implemented` → 改为 style 成功路径（Mock StyleService：_dispatch 委托调用断言 + 归一断言 created=0/updated=0/model=None/detail=StyleReport.dump/warnings 透传）；`test_style_project_not_found_first` 保留（项目校验先于 handler 的语义不变，断言 StyleService.analyze 未被调用）；新增 `_resolve_sources` STYLE 分支用例（固定 full 源、skip=False）与 `_indexing_enabled` STYLE 用例（恒 False + warning 文案）。`test_cli_extraction.py` 的 `test_run_style_unsupported` → 改为 style 成功执行用例（Mock extract 返回 success 结果 → 退出码 0 + 摘要/信封断言）。

### 覆盖率目标

- F16 模块行覆盖率 **≥ 80%**（算法纯函数全分支、服务编排全路径、API/CLI 全端点——同 F9-F15）
- 全仓覆盖率 **≥ 60%**（0.2.0 DoD，ADR-019）
- CI 门禁：ruff + mypy + pytest 全绿（ADR-017/018）；domain/ 零 FastAPI/Typer/SQLAlchemy/LangChain import（ADR-002/015——`_style_analyzer.py` 纯函数只用标准库，天然满足）
- **CI 覆盖盲区防范**: `tests/cli/test_cli_style.py` 必须显式加入 ci.yml `integration-cli-backend` job（Issue #59/#61 教训，见 §8 注记）——实施 PR 中 ci.yml 修改与测试文件同时合入；`test_style_llm_analyzer.py` 属 unit 测试（`pytest tests/unit/` 自动覆盖，无需改 ci.yml）
- **CI 无网络约束**: jieba 是 **PyPI 依赖**（CI `uv sync --frozen` 安装，词典随 wheel 分发——测试不触发任何下载，§5.5 确定性论证）；LLM 深度分析器测试**一律 Mock**（无真实 LLM 调用、无网络）；F16 无 RAG、无模型下载——确定性算法测试（除 LLM 分析器外）纯本地执行

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|----------|
| 风格报告落库（style_reports 表、历史归档、多次分析对比） | Phase 2+——本 spec 决策：风格分析是「文本内容的只读计算」，报告瞬态返回（§1/§12）；历史归档需报告存储/查询/对比三块设计，超出 4.5-6.5 人天估算（YAGNI） |
| 风格应用（按风格指纹生成写作约束、风格迁移/模仿、文本改写） | Phase 2+——F16 只做「检测」不做「应用」；改写/润色归 F3 写作服务；「按风格约束生成」需 F11/F3 联调（§1 边界声明） |
| 单章粒度分析（多章逐章独立报告） | Phase 2+——MVP 多章合并为整体（风格是整体属性，§5.1 要点 5）；逐章报告需「批量分析 + 多报告返回」形态设计 |
| AI 痕迹阈值校准（标注数据集回归、差异化特征权重） | Phase 2+——MVP 等权 + 经验阈值（§5.4/§6.2）；校准需标注数据与评测流程 |
| jieba 词性标注 / 命名实体（posseg / NER） | Phase 2+——Q2=C 拍板 jieba 仅 `lcut` 精确分词（增强板块，§5.5），不 posseg、不 NER |
| LLM 深度分析的高级形态（多轮追问、按特征逐条解释、阈值与 LLM 判定融合评分） | Phase 2+——MVP LLM 深度分析是单轮只读判定（§5.6，Q1=C）；融合评分需评测数据支撑 |
| 语言风格学派别分类（网文风/出版风/古风等风格类型识别） | Phase 2+——需风格类型标注数据与分类器；MVP 只输出结构性统计（§5.3） |
| 跨章节风格漂移检测（卷间风格一致性、合作写作风格差异） | Phase 2+——需多报告对比基础设施（与「报告落库」同口径，§10 首行） |
| 风格分析接入 F6 上下文 / F3 写作链路 | Phase 2+ 联调——分析是「作者主动体检」工具，不自动干预写作（同 F15 §10 先例） |
| 分析定时任务 / daemon 自动分析 | 已移除（F25 daemon，ADR-029）——自动触发由外部 agent 经 F20 MCP / skills 调用；MVP 手动触发（API/CLI，§6.4） |
| 风格可视化（雷达图、趋势图、词云） | F18 Web UI（0.3.0）/ F19 GUI——MVP 报告为结构化 JSON + 人类可读摘要 |
| 报告导出 / 分享 | F21 导出服务（0.6.0）——MVP 经 API/CLI 瞬态获取 |
| F14 门面的 STYLE 增量提取（内容 hash skip） | 本 spec 决策：STYLE 每次执行（确定性只读计算廉价，无 skip 价值——同 timeline 关闭语义，F14 §5.2 先例，§8.2） |
| style 类型向量索引（RAG） | F14 §2.4 已声明 outline/style 不在向量索引范围（风格是文本属性，无检索价值）——F16 不推翻 |

---

## 11. 依赖关系

与 F1 §11 / F9-F15 §11 已声明依赖保持一致（F16 在其上调整——**确定性文本分析型依赖面：读取 F1/F2 + 注册进 F14 门面，无新实体；新增运行时依赖 jieba（Q2=C）+ LLM 深度分析可选装配（F5，Q1=C）**）：

```text
F16 依赖:
  F1 (project_service) ✅ — 项目存在性校验（ProjectRepositoryProtocol.get，404，§5.1 步骤 ①）
  F2 (chapter_service) ✅ — 章节读取（ChapterRepositoryProtocol.get_chapter——chapter_ids 模式：
                           不存在/跨项目/超长校验 + 按请求顺序合并为整体分析，§5.1 步骤 ②；
                           章节为硬删除语义，get 不含软删——同 F14 章节模式先例）
  F14 (extraction_service) ✅ — STYLE 槽位注册 handler（_handlers[STYLE] = StyleService.analyze，
                           接口零变更——F14 §12 承诺兑现，§8.2）；输入约束修订（F14 §6.4
                           style 行「无效（422 未实现优先）」→「必须提供其一」）；错误面替换
                           （删除 StyleNotImplementedError，§8.2）；占位测试同步
  F5 (llm_service)     ✅ 可选依赖：LLM 深度分析装配（Q1=C——LLMClientProtocol +
                           PromptManager 构造注入 StyleLLMAnalyzer，仅 llm_analysis=true
                           时调用；主体确定性分析不依赖 F5）；domain/ 零 LangChain import
                           门禁不变——StyleLLMAnalyzer 在 domain/services/ 内通过 ports
                           Protocol 注入，同 _timeline_extractor.py 先例
  jieba (PyPI)          ✅ 新增运行时依赖（Q2=C——pyproject + uv.lock 变更，ADR-025 流程；
                           词典版本由 uv.lock 锁定保证快照断言确定性，§5.5/§8）
  F6 (context_service) — 不依赖：分析不注入上下文、不感知 F6 分层
  F9-F13              — 不依赖：F16 分析的是文本内容而非各模块档案（与 F15 审计的档案
                           聚合不同——F16 是文本消费者，唯一结构数据源是 F2 章节）
  F15 (audit_service)  — 不依赖：审计与风格分析无交集（F15 spec §11 已声明「F16 与审计无交集」）

F16 被依赖:
  F7 (CLI)             ✅ — style 命令组并入 F7 命令树（cli/app.py 注册，§4.2）
  F14 (extraction_service) ✅ — STYLE 槽位由 F16 实现填充（F14 §11「F16 ⏳」→ ✅）
  F18 (Web UI)         ⏳ — (0.3.0) 风格报告可视化消费本模块 API（POST /style/analyze）
  F20 (MCP)            ⏳ — (Phase 3) style 工具基于本模块 API（PRD §6.4 工具列表）
  F3 (writing_service) ⏳ — (Phase 2+ 联调) 风格检测结果作为写作自查的可选环节（§10）
```

> **跨模块 MODIFY 声明（与 F15 的差异）**: F15 是**零跨模块 MODIFY** 的纯消费者；F16 唯一的跨模块改动是 **F14 注册表注册 handler**（F14 §12 已承诺的既定落点，接口零变更）+ **F14 占位测试同步更新**（`test_extraction_service.py` / `test_cli_extraction.py` 的 STYLE 占位用例——这是占位机制退役的预期行为，§8.2/§12 声明）+ **F14 spec 同步修订**（§1/§6.1/§6.4/§7/§11/§12 的 STYLE 占位表述）。除此之外**零跨模块 MODIFY**：不给 F1/F2 加任何方法（项目校验走既有 `get`、章节读取走既有 `get_chapter`），不新增任何字段/表到既有模块。
>
> **编号口径**: F16 = 风格检测（ADR-019 现行口径）；旧文档中指向一致性审计的「F16」编号均为 ADR-019 之前旧编号（实际 = F15），本 spec 及后续一律以 ADR-019 为准（同 F9/F10/F12/F13/F14/F15 spec §11 声明）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| 模块类型 | **确定性文本分析型**（F12 确定性检查 × F15 只读分析的谱系延伸，分析对象从「档案」变为「文本」）：主体确定性、LLM 深度分析可选（默认关闭）、只读、不建实体表 | PRD P1-08 三项（风格指纹/AI 痕迹检测/词汇分析）都是**文本统计特征计算**——确定性算法即可表达主体能力（快照断言基线）；LLM 深度分析（Q1=C 拍板）与 jieba 增强（Q2=C 拍板）是可选/增强板块，不改变主体确定性定位；F12/F15 已证明确定性只读模式（无 LLM、幂等、可快照）；F16 是创作工具链收尾模块（4.5-6.5 人天估算，v1.1） |
| 不建实体表 | StyleReport 为纯内存瞬态报告模型，无 style_reports 表/ORM | 风格报告是「文本内容的只读计算」——报告由文本即时推导，落库即引入「报告过期」问题（文本变报告旧）；历史归档是独立需求，归 Phase 2+（§10）；P5 YAGNI（同 F15 决策） |
| F14 门面落点 | **注册 handler**（`_handlers[STYLE] = StyleService.analyze`），枚举/API/CLI 接口零变更 | F14 Q1 ✅ 已拍板选项 A + F14 §12 承诺「F16 落地后仅需注册 handler」——接口零变更保证 6 类型统一接口契约稳定（验收 ① 不回归）；F16 兑现承诺并同步修订 F14 spec 占位表述（§8.2） |
| STYLE 输入约束修订 | F14 §6.4 style 行从「无效（422 未实现优先）」改为「**必须提供 text 或 chapter_ids 其一**」 | 注册 handler 的必然结果：STYLE 从「未实现类型」变为「正常执行类型」，输入约束进入与其他文本类型（character/setting/foreshadowing）相同的语义（§8.2 表 #3）；这是 F16 声明的 F14 spec 修订，随 F16 PR 合入 |
| 增量语义 | **每次执行**（_resolve_sources 返回固定 "full" 源），不做内容 hash skip | 确定性只读计算成本毫秒级（纯内存统计），skip 判定（读 run 表 + 算 hash）本身不省任何昂贵资源——同 outline / timeline 关闭语义先例（F14 §5.2）；run 记录照常 upsert（`extract status` 可观测最近分析时间，§8.2 表 #5） |
| 结果归一 | created=0/updated=0、model=None、detail=StyleReport.model_dump、index 忽略 + warning「style 类型不支持自动索引」 | 镜像 F14 timeline 关闭语义（ConsistencyReport）先例——「无实体产物」类型的统一归一口径（§5.3/§8.2 表 #6/#7）；style 不在 RAG 范围（F14 §2.4 已声明 outline/style 不在向量索引范围） |
| 删除 StyleNotImplementedError | **删除该类** + 同步更新 extractions router imports / extract CLI UNSUPPORTED_TYPE 分支 / 占位测试 | 占位错误随占位 handler 一起退役：F16 落地后 STYLE 错误面 = ProjectNotFoundError(404) + StyleValidationError(422) + F14 章节校验错误(422) + DB 错误(500)；保留一个不可达的「未实现」错误类违背 YAGNI 且误导读者（§8.2/§12 声明「预期行为」） |
| 错误类归属 | style_errors.py 定义 StyleServiceError / StyleValidationError；ProjectNotFoundError 复用 F9 character_errors、章节错误复用 F14 extraction_errors | F14 先例：「通用名错误类不在本模块重复定义/导出（F9 character_errors 已有同名导出，避免遮蔽既有 router）」（F14 extraction_errors.py docstring）；F16 双入口（extractions router + style router）都调 StyleService——复用既有错误类保证两个 router 的既有 except 分支直接生效；StyleValidationError 独立于 F14 错误家族（表现层显式映射，§3.3 注） |
| API 形态 | F14 门面保留（POST /extract，type=style）+ **独立入口** POST /api/v1/projects/{project_id}/style/analyze（text\|chapter_ids 互斥请求体 + `llm_analysis` 可选，§2.8） | 待澄清 Q3 ✅ 已确认选项 B：门面是「一键沉淀」统一心智（Agent 脚本走统一接口），独立入口是「报告型产物」心智（同 F15 audit 端点嵌套项目路径）；用 POST 而非 GET——有请求体（镜像 F9/F14 POST 先例，区别于 F15 无请求体的 GET）；两条路径共享同一 StyleService（零重复逻辑，§8.1） |
| CLI 形态 | F14 门面保留（extract run --type style）+ `inkflow style analyze --project-id <uuid> [--text\|--text-file\|--chapters] [--llm-analysis\|--no-llm-analysis] [--json]` | 待澄清 Q3 ✅ 已确认选项 B：镜像 F15 audit 组风格（薄层 + 人类可读摘要 + --json 完整报告）；报告型产物独立命令符合用户心智（「我要分析风格」而不是「我要提取」）；三选一互斥同 F9/F14 先例；--llm-analysis/--no-llm-analysis（Q1=C）缺省 None=跟随项目配置 style_llm_analysis（§2.8/§4.2） |
| CLI 退出码 | **恒 0**（成功执行；likely_ai 结论是「结果」而非「执行错误」） | 与 F15 Q1 拍板语义一致：退出码 1 = 执行错误（NOT_FOUND/DB_ERROR/VALIDATION_ERROR），分析结论 ≠ 命令失败；脚本消费 `data.ai_trace.verdict` 判断（--json 信封） |
| AI 痕迹路线 | **纯确定性启发式**（8 特征统计评分 + 等权均值 + 三档 verdict 阈值） | 待澄清 Q1 推荐方案 A：① 确定性 → 快照断言可测（同 F12/F15 验收基线）；② 零依赖零成本（无 LLM token 消耗、无模板/重试/解析）；③ PRD 未要求「AI 判定准确率」——统计形状参考即可；LLM 判断（B/C）不可复现且 +1-1.5 人天（§5.4/待澄清 Q1）。**（v1.1 修订：Q1=C 拍板后本行升级为「AI 痕迹综合路线」——确定性 8 特征保留为基础板块（始终计算），LLM 深度分析以可选板块纳入 MVP，见下方新增行）** |
| 分词方案 | **零依赖正则词块**（CJK 连续串 + 拉丁/数字连续串） | 待澄清 Q2 推荐方案 A：① 确定性（jieba 词典版本变化破坏快照断言）；② 零新依赖（jieba 需 pyproject + uv.lock 变更 + ADR-025 流程）；③ 词汇指标（TTR/高频词/停用词占比）对分词边界不敏感（§5.2 论证）。**（v1.1 修订：Q2=C 拍板后本行升级为「jieba 增强」——零依赖正则词块保留为基础板块（始终计算），jieba 精确分词以增强板块纳入 MVP（新增运行时依赖，uv.lock 锁定保确定性），见下方新增行）** |
| top_words 排序键 | **(count DESC, first_index ASC)**——模型暴露 first_index 观测字段 | F15 实测教训：排序键用中文文本字段 → Unicode 码点序与直觉不符、测试断言与实现冲突；主键数字 + 次级键 ASCII 序号完全确定性（§2.1/§6.3） |
| verdict 阈值与权重 | ai_score 等权均值；verdict 三档（≤0.35 human / (0.35,0.65) uncertain / ≥0.65 ai）；经验阈值写代码常量 | 无标注数据支撑差异化权重（YAGNI）；三档避免绝对断言（「不是人写的」）；阈值校准归 Phase 2+（§5.4/§6.2） |
| 多章合并语义 | chapter_ids 多章按请求顺序合并为整体分析（章间 "\n\n" 分隔），source 记录全部章节 id | 风格是文本整体属性（句子节奏/词汇分布需样本量）；逐章独立报告归 Phase 2+（§5.1 要点 5/§10） |
| 算法分层 | 纯函数 `_style_analyzer.py`（镜像 `_chunking.py` 先例）+ StyleService 只编排 | 算法纯函数可独立单测（数值断言、无 Mock——核心测试面）；服务层只做 I/O 编排（Mock 仓储）；domain 零框架门禁天然满足（§5.1 要点 1/§8） |
| CLI 测试归属 | `tests/cli/test_cli_style.py`（顶层 tests/cli/）+ ci.yml `integration-cli-backend` job 显式列出 | 新增 CLI 测试文件默认是 CI 盲区（Issue #59 实测）；显式文件列表是既有 job 风格（Windows 下 pytest 不展开 glob）；unit 新文件由 `pytest tests/unit/` 自动覆盖（§8/§9） |
| AI 痕迹综合路线（Q1=C 拍板，v1.1） | **确定性 8 特征为基础板块（始终计算）** + **LLM 深度分析可选**（`style_llm_analysis` 设置项默认 false + 请求/CLI 覆盖；模板 `style_llm_analysis.yaml` + `StyleLLMAnalyzer`；报告加 `llm_assessment` 可选板块；仅独立入口可开启） | 用户拍板 Q1=选项 C（综合）——确定性保住快照断言验收基线（基础板块不变），LLM 增强路径保留（AI 能力可演进）；LLM 分析是**只读无副作用**的文本判断，但按 AI 自动化偏好**默认关闭**（F14 `timeline_auto_extract` 先例——AI 自动化需用户显式开启）；估算 +2-2.5 人天（§5.4/§5.6/§2.7/§2.8） |
| jieba 增强（Q2=C 拍板，v1.1） | **零依赖正则词块为基础板块（始终计算）** + **jieba 精确分词增强**（`jieba.lcut` 精确模式 → 与基础同构统计；`LexicalAnalysis.jieba` 板块；jieba 进 `backend/pyproject.toml` dependencies + `backend/uv.lock` 锁定） | 用户拍板 Q2=选项 C（综合）——正则词块保住快照断言基线（零依赖统计），jieba 提供词典级精确词频增强词汇分析价值；**确定性由 uv.lock 锁定词典版本保证**（ADR-025：CI `uv sync --frozen` 固定版本，测试文本固定 → 输出确定，§5.5）；jieba 是必装运行时依赖（非可选），首次打破 F14/F15 零新依赖惯例；估算 +0.5-1 人天（§5.5/§8/§11） |
| LLM 深度分析仅独立入口（v1.1） | 门面 STYLE **恒确定性**——`ExtractionRequest` 无 `llm_analysis` 字段（F14 接口零变更），门面委托显式 `llm_analysis=False`；LLM 板块仅 `style analyze --llm-analysis` / `StyleAnalyzeRequest.llm_analysis=true` 触发 | F14 接口零变更是已拍板硬约束（F14 Q1 ✅ 选项 A：STYLE 槽位落地不扩展请求契约）；LLM 板块是「主动深查」心智（作者显式要求 LLM 意见），门面「一键沉淀」路径保持纯确定性（`model=None`、`llm_assessment` 恒 None）；两条路径共享 StyleService（§2.8/§5.7/§8.2） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 报告模型 + DTO 校验（WordFrequency / StyleFingerprint 12 字段 / AITraceVerdict 三值 / AITraceFeature / AITraceAssessment / LexicalAnalysis / StyleReport 序列化 + StyleAnalyzeRequest 互斥与边界校验） | `pytest tests/unit/test_style_models.py -v` 全绿 |
| M2 | 算法·预处理与 token 化（去空白 / 句子切分 / 段落切分 / 标点统计 / 对话检测 / 零依赖 token 化全分支 + **jieba.lcut 精确模式分词断言（Q2=C）**） | `pytest tests/unit/test_style_analyzer.py -v` 全绿（预处理/token 用例） |
| M3 | 算法·风格指纹（12 项统计数值断言 + 空文本/无句尾符/单句边界 + **指纹与基础 lexical 同源、jieba 板块不影响指纹数值（Q2=C）**） | `pytest tests/unit/test_style_analyzer.py -v` 全绿（指纹用例） |
| M4 | 算法·AI 痕迹（8 特征评分函数边界表驱动 + ai_score 等权均值 + verdict 三档阈值 + evidence 规则 + 过短/无词条边界） | `pytest tests/unit/test_style_analyzer.py -v` 全绿（AI 痕迹用例） |
| M5 | 算法·词汇分析（total/unique/avg/top_words 排序/停用词占比 + 停用词表命中 + **jieba 增强板块：jieba_total/unique/avg/top_words 排序/停用词过滤/与正则词块对比「单字词切分」断言（Q2=C）**） | `pytest tests/unit/test_style_analyzer.py -v` 全绿（词汇用例） |
| M5b | **LLM 深度分析管线（Q1=C）**：`style_llm_analysis.yaml` 模板 + `StyleLLMAnalyzer`（合法 JSON→StyleLLMAssessment / 围栏提取 / 修复重试 ≤2→StyleLLMAnalysisError / verdict 非法值 / reasoning 超长截断 ≤2000 / 空文本不调用 LLM）+ 设置项三级判定（请求显式 true/false / 项目配置 `extra["style_llm_analysis"]` / 默认 false）+ llm_analysis=true 但未装配 → `StyleLLMUnavailableError` | `pytest tests/unit/test_style_llm_analyzer.py tests/unit/test_style_service.py -v` 全绿 |
| M6 | 服务编排（项目校验 404 / 输入互斥与缺失 422 / 章节校验 / 多章合并与 source 标记 / warnings 组合 / 确定性快照断言 / 失败传播 + **llm_analysis 三级判定与 llm_assessment 注入（Q1=C）**） | `pytest tests/unit/test_style_service.py -v` 全绿 |
| M7 | API POST /style/analyze（成功路径 / 404 / 422 全路径 / 无效 UUID / 500 透传 / 幂等 + **llm_analysis 透传与 LLM 相关 500 透传（Q1=C）**） | `pytest tests/unit/test_style_api.py -v` 全绿 |
| M8 | CLI style 组（三大板块摘要 / jieba 行 / LLM 行 / verdict 中文映射 / --json 完整报告 / 缺参退出码 2 / NOT_FOUND / VALIDATION_ERROR / LLM_ERROR / DB_ERROR / likely_ai 退出码 0 + **--llm-analysis/--no-llm-analysis 透传（Q1=C）**）；**ci.yml `integration-cli-backend` job 显式列出 `tests/cli/test_cli_style.py`** | `pytest tests/cli/test_cli_style.py -v` 全绿 + CI job 覆盖确认（Issue #59/#61 教训） |
| M9 | F14 门面 STYLE 落地（_handlers 注册 / _validate_input style 行 / _resolve_sources full 源 / _dispatch 委托与归一 / _indexing_enabled 恒 False / **删除 StyleNotImplementedError** / extractions router 与 extract CLI 异常映射 / 占位测试同步更新） | `pytest tests/unit/test_extraction_service.py tests/cli/test_cli_extraction.py -v` 全绿（style 相关用例全部通过；含 F14 全量回归） |
| M10 | 手工验证闭环：真实项目全流程 | 手工验证（`inkflow project create` 建项目 → `chapter create` 建 2 章（内容含对话/感叹/省略号）→ `inkflow style analyze --project-id <uuid> --chapters <id1>,<id2>` 输出三大板块摘要 + 「多章节合并分析」warning → `--json` 信封含 fingerprint/ai_trace/lexical 全字段（lexical 含 jieba 板块）→ `inkflow style analyze --text "……"` 手动模式 source=manual → **jieba 增强（Q2=C）**：`--json` 检查 `lexical.jieba` 板块数值与基础板块并存 → **LLM 深度分析（Q1=C）**：项目配置 `config.extra["style_llm_analysis"]=true`（或单次 `--llm-analysis` 覆盖）后 `inkflow style analyze --chapters <id1> --llm-analysis --json` → 报告含 `llm_assessment` 板块（真实 LLM，需网络）；不开启时 `llm_assessment=null` → **F14 门面**：`inkflow extract run --type style --chapters <id1> --json` 返回 success 信封（created=0/updated=0、detail=StyleReport、**无 llm_assessment——门面恒确定性**）→ 再次执行同命令（run 记录 upsert、仍 success——每次执行）→ `inkflow extract status` 可见 style 的 run 行 → `inkflow style analyze --project-id <uuid>`（缺参）退出码 2 → `inkflow style analyze --project-id 00000000-0000-0000-0000-000000000000 --text "……"` 退出码 1 NOT_FOUND → 修改章节内容后重分析 → 报告数值变化（指纹反映新文本）） |
| M11 | 全量回归 + 覆盖率 + lint/type | `pytest -v` 全绿；F16 模块行覆盖 ≥ 80%、全仓 ≥ 60%（0.2.0 DoD）；ruff + mypy 通过（CI 门禁 ADR-017）；domain/ 零框架 import（ADR-002/015，含 `_style_analyzer.py` 与 `_style_llm_analyzer.py`——后者仅 ports Protocol import）；**pyproject + uv.lock 变更（jieba，Q2=C——uv lock 更新在实现阶段执行，CI `uv sync --frozen` 依赖此变更，§8）** |

> **验收标准 ↔ Issue #46 映射**: ①「风格指纹」→ M2/M3/M10（12 项结构性统计 + 手工闭环数值变化实证）；②「AI 痕迹检测」→ M4/M10（8 特征评分 + verdict 三档 + 手工闭环摘要结论）；③「词汇分析」→ M5/M10（token 统计 + 高频词 + 停用词占比 + jieba 增强板块）；**F14 STYLE 槽位落地（F14 承诺兑现）** → M9/M10（注册 handler + 输入约束修订 + 错误面替换 + 占位测试同步）；**Q1=C/Q2=C 拍板范围** → M5b/M10（LLM 深度分析管线 + 设置项三级判定 + jieba 增强板块，§5.5/§5.6）。

---

## 待澄清问题（≤ 3 个，已全部拍板 ✅）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | **AI 痕迹检测的实现路线？** 选项 A：纯确定性启发式——统计特征 + 规则评分（8 特征等权均值 + 三档阈值，无 LLM，§5.4 本 spec 设计，零成本、可快照断言）；选项 B：LLM 判断——模板 + LLM 输出 verdict（F14 交接清单假设的「提供模板」路径；LLM 判断不可复现 → 破坏快照断言基线；需新模板 + 提取器 + 解析重试，估算 +1-1.5 人天；LLM 分析是只读无副作用，不触发「AI 自动化默认关闭」约束）；选项 C：综合——确定性为主 + LLM 深度分析可选（两者并存，报告增加 llm_assessment 可选板块，估算 +2-2.5 人天） | 估算（2-3 → 4.5-6.5 人天）；确定性验收基线（快照断言）是否保留；LLM 模板/重试/解析三件套是否引入 | **✅ 已确认（用户拍板：选项 C）**：正文已按拍板结果修订——确定性 8 特征保留为基础板块（§5.4，始终计算）+ LLM 深度分析可选（§5.6 新增小节；设置项 `style_llm_analysis` 默认 false + 请求/CLI 三级覆盖，§2.8；`StyleLLMAssessment`/`llm_assessment` 可选板块，§2.6/§2.7；异常映射与 500 错误类，§3.3/§7；`_style_llm_analyzer.py` + `style_llm_analysis.yaml` + test_style_llm_analyzer.py，§8/§9；决策记录，§12；验收 M5b/M10，§13） |
| Q2 | **词汇分析的分词方案？** 选项 A：零依赖词块统计——正则切分连续汉字/英文单词 + 字符级特征（§5.2 本 spec 设计；确定性可复现、零新依赖——F14/F15 零新依赖先例）；选项 B：引入 jieba 分词——精确词频（新增运行时依赖 → pyproject + uv.lock 变更 + ADR-025 流程；jieba 词典版本变化改变分词结果 → 破坏快照断言；估算 +0.5-1 人天）；选项 C：综合——零依赖为主 + jieba 可选增强（两套 token 化并存，报告增加 jieba 板块） | 依赖面（pyproject/uv.lock 变更）；快照断言确定性；词汇指标口径 | **✅ 已确认（用户拍板：选项 C）**：正文已按拍板结果修订——零依赖正则词块保留为基础板块（§5.2/§5.5，始终计算）+ jieba 精确分词增强（§5.5 jieba 小节；`JiebaAnalysis` 板块嵌套 `LexicalAnalysis.jieba`，§2.4/§2.5；jieba 进 pyproject + uv.lock（ADR-025，uv.lock 锁定词典版本保确定性），§8/§11；决策记录，§12；验收 M2/M3/M5/M10，§13） |
| Q3 | **入口形态？** 选项 A：仅走 F14 门面——`extract run --type style` / POST /extract（最小改动，无独立入口；风格报告需在统一提取信封 detail 中取）；选项 B：门面 + 独立入口——`style analyze` 命令 + POST /projects/{pid}/style/analyze（§3/§4 本 spec 设计；报告型产物独立入口更符合用户心智，镜像 F15 audit 组；两条路径共享同一 StyleService；估算 +0.5-1 人天）；选项 C：仅独立入口——否决（F14 Q1 已拍板 STYLE 槽位必须落地，门面是「一键沉淀」统一心智与 Agent 脚本契约） | 估算（已含在 4.5-6.5 人天总估算——v1.0 的 2-3 已含 Q3=B 的 +0.5-1）；F14 门面承诺的兑现口径；报告型产物的用户心智 | **✅ 已确认（用户拍板：选项 B）**：v1.0 已按此设计，仅标记确认——正文无需改动（§3/§4/§12 保持门面 + 独立入口双形态；门面恒确定性重申见 §2.8/§5.7/§8.2——LLM 深度分析仅独立入口提供，F14 `ExtractionRequest` 零变更） |

---

*本文档为 F16 功能规格（What），实施步骤（How）见后续 `specs/f16-style-service/plan.md`。所有里程碑验收以本节 M1-M11 为准。*
