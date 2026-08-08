# F22: 全文搜索（search_service）— 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-09 | **依据**: PRD v2.2 §6.4 P1-16, Issue #54, Constitution P1-P6（P2 解耦 / P5 YAGNI）
> **所属阶段**: 0.6.0（#54 全文搜索，估算 2-3 人天）
> **关联 Issues**: [#54](https://github.com/zhx-xi/InkFlow/issues/54)
> **依赖**: ✅ F1（项目校验）· ✅ F2（章节正文源）· ✅ F9（角色档案源）· ✅ F10（世界观条目源）· ✅ F11（大纲源）· ✅ F12（时间线源）· ✅ F13（伏笔源）· ✅ F16（jieba 分词依赖已锁定，直接复用）· ✅ F19 #77（token 中间件）· ✅ SQLite FTS5（实测 3.50.4 已启用，零新依赖）· ⏳ 无
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md)（模块化单体）· [ADR-002](../../adr/ADR-002.md)（六边形分层）· [ADR-003](../../adr/ADR-003.md)（Repository）· [ADR-004](../../adr/ADR-004.md)（Pydantic v2）· [ADR-012](../../adr/ADR-012.md)（错误处理）· [ADR-013](../../adr/ADR-013.md)（RAG：向量检索边界声明，§10）· [ADR-018](../../adr/ADR-018.md)（测试分层）· [ADR-019](../../adr/ADR-019.md)（版本里程碑 + 模块编号口径）· [ADR-021](../../adr/ADR-021.md)（内核进程化：token 契约）· [ADR-025](../../adr/ADR-025.md)（依赖锁定：零新增依赖）· [ADR-027](../../adr/ADR-027.md)（覆盖率门禁）
> **状态**: 待实现 🔲（0.6.0）

---

## 1. 概述

提供**跨内容类型的全文搜索**：对项目内的章节正文与设定档案（角色/世界观/大纲/时间线/伏笔）建立本地全文索引，支持**关键词搜索、类型筛选、结果高亮**（PRD P1-16 三要素），供作者快速定位「哪一章写过 X」「哪个角色提到 Y」——长篇创作的核心检索诉求。

**核心价值**: 小说项目数据量大（几十万字正文 + 数百档案条目）后，靠目录翻找/肉眼搜索不可行；F6 上下文注入（写作时取设定）解决的是「写作时自动带上下文」，F22 解决的是「作者主动检索」——两者互补，一个后台一个前台。

**变体定位（第 16 变体「索引检索型」）**: 本模块是 **F12 确定性算法 × F15 只读聚合 × F16 文本分析**谱系的检索变体——无 LLM、无业务实体表（FTS5 虚拟表是基础设施索引，不属于 `Base.metadata`）、确定性输出（同一索引 + 同一查询 → 同一结果集）。§5 核心是**「分词 → 索引 → MATCH 查询 → 高亮」**四段确定性管线，全部基于 SQLite 内置 FTS5（实测 3.50.4 `sqlite_compileoption_used('ENABLE_FTS5')=1`）+ 已锁定依赖 jieba（F16 引入），**零新增依赖**（ADR-025）。编号依据 AGENTS.md 模块类型谱系（F30=13 / F32=14 → 本模块第 16 变体），冲突以 ADR-019 v5+ 为准。

```
各模块档案（DB） ──只读聚合 + jieba 分词──▶ FTS5 虚拟表（search_index）
                                                │
查询词 ──jieba 分词 + MATCH 构造──▶ FTS5 查询 ──▶ 命中行 + snippet(<mark>) 高亮
```

**边界声明**:
- F22 是**词法全文搜索**，不是**语义搜索**：向量/embedding 检索归既有 RAG 能力（ADR-013 VectorStoreProtocol，F6 上下文注入消费），本模块不重复建向量索引（见 §10 与待澄清 Q1）
- F22 不新建业务实体表（FTS5 虚拟表 + 索引元数据归基础设施层，见 §2.4/§8）
- F22 不做**跨项目搜索**（MVP 项目内搜索，project_id 必填；跨项目归未来，见 §10 与待澄清 Q3）
- F22 是纯后端能力：API 端点 + CLI；GUI 搜索框接线属前端职责（消费本 API），不在本 spec 范围
- F22 不修改任何既有模块的 Repository/Service（零跨模块 MODIFY；索引数据读取走既有只读方法 + 自有补充端口，F15 audit_repo 先例，见 §8）

---

## 2. 数据模型

遵循「领域 Pydantic 实体 + DTO」模式（ADR-004），但 F22 **不新建持久化业务实体**——新增的是**查询 DTO / 结果 DTO**（瞬态）+ **基础设施索引结构**（FTS5 虚拟表 + 元数据表，非业务表，不进 `domain/models/` 业务模型文件，见 §2.4）。

### 2.1 SearchEntityType（可搜索内容类型枚举）

与 F21 附录类型集对齐（6 类；对齐既有 `EntityType`（vector_store.py）的设定类但语义不同——那是向量索引类型，本枚举是词法索引类型，见 §12 D1）：

| 值 | 数据源 | 索引内容（title / body） |
|----|--------|--------------------------|
| `chapter` | F2 Chapter | title / content（正文全文） |
| `character` | F9 Character | name / personality + background + goals |
| `world` | F10 WorldSetting | name / content |
| `outline` | F11 Outline + PlotPoint | name / description + 情节点名称与描述 |
| `timeline` | F12 TimelineEvent | title / description |
| `foreshadowing` | F13 Foreshadowing | title / description + location |

> 不含 `project`（项目名/简介太短无检索价值，且项目列表页已有搜索——PRD §6.2「项目列表支持搜索」；Q3 可复议）。

### 2.2 SearchQuery / SearchHit / SearchResponse（DTO）

```python
class SearchQuery(BaseModel):
    """查询参数（API query / CLI 选项统一语义）。"""
    q: str                                  # 查询词（必填，1-100 字符，空白 422）
    project_id: uuid.UUID                   # 必填：MVP 项目内搜索（Q3 待拍板）
    types: list[SearchEntityType] | None    # None = 全部类型（类型筛选）
    limit: int = 20                         # 1-100
    offset: int = 0

class SearchHit(BaseModel):
    """单条命中。"""
    entity_type: SearchEntityType
    entity_id: uuid.UUID
    title: str                  # 命中实体标题（如章节名/角色名）
    snippet: str                # 高亮片段（FTS5 snippet() 输出，含 <mark> 标记，见 §5.4）

class SearchResponse(BaseModel):
    total: int                  # 总命中数（不受 limit 影响）
    hits: list[SearchHit]
    query: str                  # 回显原始查询词
    types: list[SearchEntityType] | None  # 回显筛选
```

### 2.3 领域模型文件归属

`SearchQuery/SearchHit/SearchResponse/SearchEntityType` 放 `domain/models/search.py`（纯 DTO，无 ORM——F23 WritingStreamEvent 判别联合 DTO 先例）；**不建** `domain/ports/search_*.py` 业务端口（检索是基础设施能力，见 §12 D2）。

### 2.4 基础设施索引（非业务表）

| 结构 | 定义 | 说明 |
|------|------|------|
| FTS5 虚拟表 | `CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(title, body, entity_type UNINDEXED, entity_id UNINDEXED, project_id UNINDEXED)` | 词法索引；title/body 可搜，三个 UNINDEXED 列仅过滤；rowid = 自增无业务意义 |
| 元数据表 | `CREATE TABLE IF NOT EXISTS search_meta (key TEXT PRIMARY KEY, value TEXT)` | `last_rebuilt_at`（重建快照时间，ISO8601 UTC）——脏检测用，见 §5.3 |

- **建表方式**：`CREATE ... IF NOT EXISTS` 幂等语句，在索引初始化时执行（首次搜索懒初始化 / service 首次调用，见 §5.2）；**不依赖 `Base.metadata.create_all`**（FTS5 虚拟表不是 SQLAlchemy 映射表，符合「无 alembic：轻量幂等迁移」项目惯例，但这里是建表不是迁移）
- 删除语义：项目删除时索引残留由**按 project_id 过滤 + 全量重建**自然覆盖（重建只写活动项目行；残留行不影响查询，§7 E6）

---

## 3. API 契约

### 3.1 端点总览（1 个，GET 只读）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/search` | 全文搜索（query 参数见下） |

- query：`q`（必填）、`project_id`（必填 UUID）、`types`（可选，逗号分隔枚举，如 `chapter,character`）、`limit`（默认 20）、`offset`（默认 0）
- 响应：200 `SearchResponse` JSON；幂等只读

### 3.2 请求/响应示例

```http
GET /api/v1/search?q=龙&project_id=1&types=chapter,world&limit=5
→ 200
{
  "total": 3,
  "hits": [
    {
      "entity_type": "chapter",
      "entity_id": "00000000-0000-0000-0000-00000000000a",
      "title": "第 3 章 龙的苏醒",
      "snippet": "古井深处，<mark>龙</mark>瞳睁开。它沉睡千年……<mark>龙</mark>息如雷。"
    },
    {
      "entity_type": "world",
      "entity_id": "00000000-0000-0000-0000-00000000000b",
      "title": "龙族领地",
      "snippet": "<mark>龙</mark>族盘踞的北境荒原，终年冰雪……"
    }
  ],
  "query": "龙",
  "types": ["chapter", "world"]
}
```

### 3.3 异常映射表

| 场景 | HTTP 状态 | 错误 body（ADR-012 统一格式） | 抛出/捕获点 |
|------|-----------|-------------------------------|-------------|
| 项目不存在 / 已软删 | 404 | `{"detail": "Project not found"}` | service 校验（复用 F9 character_errors `ProjectNotFoundError`，陷阱 16：**不导出**到 `ports/__init__.py`，router 显式 except 映射） |
| `q` 缺失 / 空白 / 超长 | 422 | Pydantic 校验错误 | DTO 层（`Field(min_length=1, max_length=100)` + 空白 validator） |
| `types` 非法枚举 | 422 | Pydantic 校验错误 | DTO 层 |
| `limit` 越界（>100） | 422 | Pydantic 校验错误 | DTO 层 |
| 查询语法构造失败（分词空） | 200 | 空结果（`total: 0`）——分词后无有效词（如纯标点），返回空而非 422 | service（§5.3 注） |
| 索引尚未建立 | 200 | 懒初始化：首次查询自动全量重建后返回真实结果（非空结果） | service（§5.2） |
| 内部错误（DB 异常） | 500 | `{"detail": "Internal server error"}` | router `except Exception` → loguru（ADR-016） |

---

## 4. CLI 命令签名

F7 全局约定：`--json` 信封、退出码 0/1/2。F22 新增 `inkflow search` 命令（直接消费 service，不经 HTTP——六边形表现层适配器，F23/F21 先例）。

```text
inkflow search <query> --project <name|id> [--type TYPE]... [--limit N] [--offset N] [--json]

参数:
  query                    查询词（必填，1-100 字符）
  --project, -p            项目名称或 ID（必填；F1 约定：名称精确匹配，数字按 ID 解析）
  --type, -t               可搜索类型（可重复，如 -t chapter -t character；缺省 = 全部）
  --limit                  默认 20，最大 100
  --offset                 默认 0
  --json                   输出 JSON 信封

成功: 退出 0；非 --json 时打印人类可读结果（类型徽标 + 标题 + snippet）；--json 时信封 data = SearchResponse
失败: 项目不存在 → 退出 1，error = "项目不存在: <name>"
      query 空白 → 退出 2（Typer 自动）
```

示例：

```text
$ inkflow search 龙 -p 我的书 -t chapter
[chapter] 第 3 章 龙的苏醒
  古井深处，[龙]瞳睁开。它沉睡千年……[龙]息如雷。

$ inkflow search 龙 -p 我的书 --json
{"success": true, "data": {"total": 3, "hits": [...], "query": "龙", "types": null}}
```

> CLI 展示高亮用 `[...]` 方括号标记（终端无 HTML 语义）；`--json` 时 snippet 保留 `<mark>`（消费端自行渲染/剥离）。

---

## 5. 索引检索模式（关键差异：分词 → FTS5 → 高亮）

> ⚠️ **本节是 F22 与既有样板的核心差异点**：F12 §5 是「一致性检查算法」，F16 §5 是「文本统计特征」，F14 §5 是「提取门面」；本模块的 §5 是**确定性全文检索管线**——jieba 中文分词 + SQLite FTS5 倒排索引 + MATCH 查询 + snippet 高亮，无 LLM、零新增依赖。

### 5.1 模式总览

```text
 ┌─────────────────────────────────────────────────────────────┐
 │ SearchService.search(query)                                  │
 └──────────────────────────┬──────────────────────────────────┘
                            ▼
 ① 校验项目存在（F1 ProjectRepository.get）→ ProjectNotFoundError(404)
 ② 确保索引就绪（_ensure_index）:
    - CREATE VIRTUAL TABLE IF NOT EXISTS（幂等，§2.4）
    - 脏检测（_is_stale）: search_meta.last_rebuilt_at 缺失 / 任一数据源
      max(updated_at) > last_rebuilt_at → 全量重建（§5.3）
 ③ 查询词分词: jieba.cut_for_search(q) → 词序列（过滤空白/纯标点）
 ④ 构造 MATCH: 每词 `"<词>"`（FTS5 引号精确短语）+ 空格连接（隐式 AND）
 ⑤ 执行: SELECT entity_type, entity_id, title,
         snippet(search_index, 0, '<mark>', '</mark>', '…', 48) AS snippet
         FROM search_index WHERE search_index MATCH ? AND project_id = ?
         AND entity_type IN (?) ORDER BY rank LIMIT ? OFFSET ?
 ⑥ 组装 SearchResponse（total 用同条件 COUNT(*) 另查）
```

**模式要点**:
1. **确定性**：同一索引 + 同一查询 → 同一结果集（排序用 FTS5 `rank`（BM25），索引一致则结果一致；重建不改变排名——相同文档集 BM25 稳定，§5.6）
2. **中文分词是成败关键**：FTS5 默认 unicode61 分词器对中文按「连续 CJK 串」整体切分（"龙的苏醒" 被当作一个 token），直接 MATCH "龙" 无法命中——**必须 jieba 分词后空格连接入库 + 查询词同样分词**（F16 已锁定 jieba 0.42.1，零新依赖；中文检索标准做法）
3. **全量重建而非写时同步**（Q2 待拍板，建议 B）：MVP 不侵入 6 个模块的写路径（F15 零跨模块 MODIFY 先例）；重建成本 = 单项目全量数据重插 FTS5（几 MB 级 < 1s，量级论证见 §5.3）
4. **无副作用**：搜索不修改业务数据；重建只写本模块基础设施表

### 5.2 索引初始化与生命周期

- **懒初始化**：首次 `search` 调用时建表 + 全量重建（无独立初始化命令；`inkflow search` 首次运行即触发——用户可见行为一致，无隐式后台任务）
- **重建触发条件**（脏检测，`_is_stale`）：
  ① `search_meta` 无 `last_rebuilt_at`（首次）
  ② 任一数据源 `max(updated_at)` > `last_rebuilt_at`（跨 6 表各查一次 max，成本 ~6 个轻量 SQL）
  ③ 显式重建命令（`inkflow search --rebuild`，可选——见 §5.3 注）
- **数据源 max(updated_at) 查询**：走自有补充端口 `search_repo`（F15 audit_repo 先例：ORM 原生 SQL 只读，零跨模块 MODIFY），见 §8.2
- **并发**：单用户本地（F19 serve 单进程），重建用 `asyncio.Lock` 防并发重复重建（两个并发请求同时判脏 → 只允许一个重建，另一个等待后查询）

### 5.3 全量重建算法

```text
_ensure_index():
  CREATE VIRTUAL TABLE IF NOT EXISTS search_index ...（§2.4）
  if not _is_stale(): return
  async with _rebuild_lock:
    if not _is_stale(): return          # 双检锁（另一个协程已重建）
    DELETE FROM search_index            # 全量清空（FTS5 支持 DELETE）
    并行拉取 6 类数据源（只读，排除软删; ⚠️ 全部 `list` 默认 limit=50，须循环分页拉全——2026-08-09 源码核实）:
      chapter:      ChapterRepository.list_chapters(pid, ...) 分页循环 + 服务层过滤 is_deleted
      character:    CharacterRepository.list(pid, ...) 分页循环（repo 默认排除软删 ✓）
      world:        WorldRepository.list(pid, ...) 分页循环
      outline:      OutlineRepository.list(pid, ...) 分页循环 + list_points(oid)（无分页参数）
      timeline:     TimelineRepository.list_all(pid)（无分页参数）
      foreshadowing: ForeshadowingRepository.list(pid, ...) 分页循环
    每类逐条: body = jieba 分词(title + " " + body_text) 空格连接
              INSERT INTO search_index(title, body, entity_type, entity_id, project_id)
    upsert search_meta.last_rebuilt_at = now(UTC)
```

**量级论证（全量重建可行性的数学基础）**: 单项目上限——章节 1000 章 × 平均 3000 字 = 300 万字 ≈ 6 MB 文本；档案条目 ≤ 数千条。FTS5 插入吞吐 ≥ 1 MB/s（SQLite 本地文件，非内存热路径），全量重建 **< 10s 首建、增量变更后重建 < 2s**；单用户本地、重建仅在检测到变更后的**首次搜索**触发一次——可接受（Q2 拍板依据）。若未来数据量爆炸（多项目 1 亿字级），增量索引是演进路径（§10）。

> 注：`--rebuild` 显式命令为可选项（YAGNI 倾向不加——脏检测已覆盖所有变更路径；`search_meta` 被删/损坏时首次搜索自然重建）。**实现时按 Q2 拍板决定是否暴露**。

### 5.4 高亮（snippet 生成）

- 使用 FTS5 内置 `snippet()` 函数：`snippet(search_index, 0, '<mark>', '</mark>', '…', 48)`——第 0 列（title）不参与 snippet，第 1 列（body）取命中上下文 48 token，命中词前后缀 `<mark>`/`</mark>`（FTS5 原生支持自定义标记，零自研）
- **安全**：`<mark>` 是白名单标签；正文其他 HTML 特殊字符（`<` `>` `&`）在入库分词前**已按 XML 文本转义**（§5.5），snippet 输出天然安全（FTS5 片段来自转义后的 body）
- 语义：snippet 取「首个命中附近」而非「最相关片段」（FTS5 snippet() 行为），MVP 可接受（多命中场景下首个上下文已定位章节）
- title 命中：title 列**不**做 snippet（title 短，直接返回全名）

### 5.5 分词与索引内容预处理（确定性核心）

| 步骤 | 规则 |
|------|------|
| ① 文本转义 | `& < > "` → XML 实体（防 snippet 注入 + 防 FTS5 语法混淆） |
| ② 拼接 | title + " " + body_text（§2.1 各类型拼接规则，同 F21 §6.3 摘要口径但**含全文**：chapter 是 content 全文，档案是字段拼接） |
| ③ jieba 分词 | `jieba.cut_for_search(text)` → 词序列（搜索引擎模式：长词 + 子词，召回更全） |
| ④ 过滤 | 去空白、纯标点词、单字符无意义词（**保留单字符中文词**——"龙" 是有效查询，只过滤英文单字母/纯符号） |
| ⑤ 入库 | 分词结果空格连接写入 body 列 |

查询侧同管线（②-④），MATCH 构造：每词 `"词"`（双引号）空格连接——FTS5 引号 = 精确短语，双引号同时**转义 FTS5 语法保留字**（`AND OR NOT NEAR` 等作为词时被引号保护，防查询注入/语法错误）；多词 = 隐式 AND（全部词命中才返回）。

**边界**：查询词含引号本身 → 双引号包裹时 FTS5 内 `""` 转义为 `""""`（SQL 层再参数化）；分词后空词序列 → 返回空结果（§3.3）。

### 5.6 排序与确定性

- 排序键：FTS5 `rank`（BM25 默认），`ORDER BY rank`（低分在前 = 更相关）
- 确定性：相同文档集 → BM25 稳定（无随机种子）；`total` 与 `hits` 同一次查询内一致（先 COUNT 后 SELECT，两次独立查询之间数据变更不保证——快照语义同 F21 E11）

### 5.7 索引检索型 vs 既有样板：差异对照表

| 维度 | F12 一致性检查 | F16 文本分析 | **F22 全文搜索** |
|------|---------------|--------------|------------------|
| 数据源 | 单模块 | 章节文本 | 6 模块只读聚合 |
| 输出 | 内存报告 | 内存报告 | **FTS5 索引 + 查询命中** |
| 新业务表 | 无 | 无 | **无（FTS5 虚拟表 + meta 表，基础设施）** |
| 新增依赖 | 无 | jieba（0.2.0 引入） | **零（jieba/FTS5 均已有）** |
| 新 API | 8 端点 CRUD | 1 端点 | **1 只读端点** |
| 新 CLI | timeline 组 | style 组 | **search 命令** |
| 算法性质 | 相邻对扫描 | 统计特征 | **分词 + 倒排索引 + BM25** |
| 跨模块 MODIFY | 无 | 无 | **无（补充端口 search_repo）** |
| LLM | 无 | 可选 | **无** |

---

## 6. 索引内容组织规则

### 6.1 各类型索引内容拼接（title / body）

| type | title | body（jieba 分词后） |
|------|-------|----------------------|
| chapter | chapter.title | chapter.content 全文 |
| character | character.name | personality + background + goals |
| world | setting.name | setting.content |
| outline | outline.name | outline.description + 各情节点 `name: description` |
| timeline | event.title | event.description + time_display（非空时） |
| foreshadowing | foreshadowing.title | description + location（非空时） |

### 6.2 软删与重建

- 重建只读**活动数据**（各 repo `list` 的既有语义，默认排除软删——实现时逐 repo 核实，F21 §8.2 同款声明）
- 软删实体不会进索引（重建时不读）；若某 repo `list` 含软删，service 显式过滤 `is_deleted`（服务层责任）
- 已软删实体的旧索引行：全量重建自然清除（DELETE + 重插）

### 6.3 类型筛选语义

- `types=None` → 全部 6 类；`types=[...]` → SQL `entity_type IN (...)`（参数化）
- 空列表 `types=[]` → 视为 None（全部）还是 422？——**视为全部**（客户端省略参数的自然形态，Pydantic `list | None` 缺省 None；显式空列表语义模糊，按全部处理，测试锁定）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| E1 | 项目不存在 / 已软删 | 404（ProjectNotFoundError 复用，§3.3） |
| E2 | 查询词空白 / 仅标点 | 422（空白）/ 200 空结果（分词后无有效词） |
| E3 | 查询词超长（>100） | 422 |
| E4 | 无索引（首次搜索） | 懒初始化：建表 + 全量重建后返回真实结果（首次搜索有首建延迟 <10s，可接受） |
| E5 | 无命中 | 200 `{total: 0, hits: []}` |
| E6 | 项目已删除（硬删）后残留索引行 | 查询按 project_id 过滤 + 重建只写活动项目 → 残留行不返回（自然隔离） |
| E7 | 并发重建 | `asyncio.Lock` 双检锁，只允许一次重建（§5.3） |
| E8 | 重建中断（进程崩溃） | `last_rebuilt_at` 不更新 → 下次搜索重新判脏重建（幂等） |
| E9 | 查询词含 FTS5 保留字（AND/OR/NOT） | 引号包裹转义，按普通词处理（§5.5） |
| E10 | 正文含 HTML/XML 标签 | 入库前转义 → 按字面文本检索，不解析（§5.5 ①） |
| E11 | jieba 词典未加载 | jieba 默认词典随包分发（F16 已验证无网络依赖），加载失败 = 500（loguru） |

---

## 8. 文件结构

### 8.1 CREATE/MODIFY 清单（对照真实源码树 `backend/src/inkflow/`）

| 类型 | 路径 | 说明 |
|------|------|------|
| CREATE | `domain/models/search.py` | SearchEntityType / SearchQuery / SearchHit / SearchResponse（§2） |
| CREATE | `domain/services/search_service.py` | SearchService：`search()` 编排 + `_ensure_index/_is_stale/_rebuild`（§5.1-5.3） |
| CREATE | `domain/services/_search_tokenizer.py` | 分词与预处理纯函数（jieba 封装 + 转义 + 过滤 + MATCH 构造，§5.5）——`_word_count.py`/`_style_analyzer.py` 先例 |
| CREATE | `domain/services/_search_snippet.py` | snippet 生成封装（FTS5 snippet() 调用 + 空值兜底）——如逻辑简单可并入 service（YAGNI，实现时定） |
| CREATE | `domain/ports/search_repository.py` | **自有补充端口**（F15 audit_repository 先例）：`max_updated_at(table)` + FTS 读写（见 §8.2） |
| CREATE | `infrastructure/database/repositories/search_repo.py` | SQLiteSearchRepository：FTS5 建表/重建/查询原生 SQL + meta 读写 |
| CREATE | `api/routers/search.py` | GET `/api/v1/search`（§3） |
| CREATE | `cli/commands/search.py` | `inkflow search` 命令（§4） |
| CREATE | `backend/tests/unit/test_search_models.py` | DTO 校验（空白/超长/枚举） |
| CREATE | `backend/tests/unit/test_search_tokenizer.py` | 分词/转义/MATCH 构造（中文词、保留字、标点过滤） |
| CREATE | `backend/tests/unit/test_search_service.py` | 编排：mock repos + mock search_repo → 判脏/重建/查询/软删排除 |
| CREATE | `backend/tests/unit/test_search_index.py` | **真 SQLite 内存库 FTS5 集成**（§9.2 关键场景） |
| CREATE | `tests/cli/test_cli_search.py` | CLI 测试（仓库根 `tests/cli/`，Issue #61 约定；**新文件必须显式追加 integration-cli-backend job**——陷阱 13/15） |
| CREATE | `tests/api/test_search_api.py` | API 端点测试（仓库根 `tests/api/`，F21 同款落点） |
| MODIFY | `api/app.py` | `app.include_router(search.router)` + import（1 行） |
| MODIFY | `api/deps.py` | SearchService 装配（注入 6 个数据源 repository + search_repo + project_repo） |
| MODIFY | `cli/app.py` | import + `app.command()` 注册 search（1-2 行） |
| MODIFY | `.github/workflows/ci.yml` | 两处联动（陷阱 13/15，2026-08-09 核实）：① `tests/cli/test_cli_search.py` 显式追加 **integration-cli-backend** job 文件列表 ② `tests/api/test_search_api.py` 显式追加 **integration-project-backend** job 文件列表（既有先例 `../tests/api/test_project_api.py`）；coverage-backend 跑 `../tests/api/` 目录自动覆盖，无需追加 |

> ⚠️ 反向核对（F32 教训）：上表 CREATE 均已核实不存在、MODIFY 均已确认存在（2026-08-09）；ci.yml 中 `tests/api/` 的 job 覆盖实现时先核。

### 8.2 自有补充端口 search_repository（F15 audit_repo 先例）

F22 需要「跨 6 表查 max(updated_at)」与「FTS5 原生 SQL 读写」——既有 Protocol 均无此能力，且**不 MODIFY 任何既有 Protocol**（F15 §5.5 模式：只读横切模块缺数据时建自有补充端口）：

```python
class SearchRepositoryProtocol(Protocol):
    """搜索索引基础设施端口（FTS5 + 元数据；不触碰业务表）。"""
    async def ensure_index(self) -> None: ...
    async def is_stale(self, sources: list[tuple[str, datetime]]) -> bool: ...
    # 实现内部: 读 search_meta.last_rebuilt_at vs 各源 max(updated_at)
    async def rebuild(self, documents: Iterable[SearchDocument]) -> None: ...
    # 实现内部: DELETE FROM search_index + 批量 INSERT + upsert meta
    async def query(self, match: str, project_id: int, types: list[str] | None,
                    limit: int, offset: int) -> tuple[int, list[SearchHit]]: ...
    # 实现内部: SELECT + COUNT，FTS5 snippet() 高亮
```

- `SearchDocument`（基础设施 DTO，`dataclass`）：`entity_type / entity_id / project_id / title / body`（分词后文本）
- `max_updated_at` 归属：放 search_repo（对 6 张业务表各发一条 `SELECT max(updated_at) FROM <table> WHERE project_id=?`——**原生 SQL 只读**，不建 ORM 映射，F15 audit_repo 同款）
- 依赖方向合法：领域层依赖 `SearchRepositoryProtocol`，基础设施实现 `SQLiteSearchRepository`（六边形，ADR-002）

---

## 9. 测试策略

沿用 ADR-018 三层目录 + pytest markers；无 LLM → 无网络约束。

### 9.1 测试层次

| 层 | 文件 | 内容 |
|----|------|------|
| 单元 | `tests/unit/test_search_tokenizer.py` | 分词纯函数：中文词拆分、保留字转义、标点过滤、XML 转义 |
| 单元 | `tests/unit/test_search_service.py` | 编排：mock 数据源 repos + mock search_repo → 判脏逻辑（stale/新鲜/首次）、重建触发、软删排除、types 筛选透传 |
| 集成 | `tests/unit/test_search_index.py` | **真 SQLite 内存 FTS5**（`aiosqlite :memory:` + CREATE VIRTUAL TABLE）：索引→查询闭环、中文命中（"龙" 命中分词后文本）、snippet `<mark>` 断言、BM25 排序、分页 |
| API | `tests/api/test_search_api.py` | TestClient：200 命中/空结果、404、422（空白 q/坏枚举/limit 越界）、token 中间件 |
| CLI | `tests/cli/test_cli_search.py` | CliRunner：命中输出、`--json` 信封、404 错误、多 `-t` 筛选 |

### 9.2 关键场景（RED 批要点）

1. **中文分词命中**：内容「古井深处龙瞳睁开」+ 查询「龙」→ 命中（验证 jieba 空格分词入库 + 查询分词一致——FTS5 中文检索的 load-bearing 测试）
2. **跨类型**：同词命中 chapter + character + world 三类，types 筛选后只剩指定类
3. **高亮**：snippet 含 `<mark>龙</mark>` 且不含未转义 HTML（E10）
4. **保留字安全**：查询 `AND` → 命中含 "AND" 的正文（引号转义生效，不语法报错）
5. **判脏**：更新一章 → 下次搜索重建（mock 源 max updated_at 变化）；无变更 → 不重建（mock 断言 rebuild 未调用）
6. **软删排除**：软删角色不索引不命中
7. **空结果 / 纯标点查询**：200 空 / total 0
8. **确定性**：同数据同查询两次结果一致（BM25 稳定）

### 9.3 覆盖率

模块 ≥80%（ADR-027 口径）；FTS5 集成测试覆盖索引路径（mock 层覆盖不了 FTS5 行为，故 test_search_index.py 必须真库——不能只靠 mock，这是本模块区别于 F21 的测试结构要点）。

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| 语义/向量搜索（embedding） | 既有 RAG（ADR-013 VectorStoreProtocol，F6 上下文注入消费）+ F14 chromadb 已覆盖「语义相似」场景；F22 词法检索与向量检索互补，**不重复建向量索引**（Q1 拍板确认口径） |
| 跨项目搜索 | MVP 项目内（project_id 必填）；跨项目 = 全部项目建索引 + 聚合查询，独立场景（作者通常单项目写作），Q3 待拍板 |
| 写时同步索引（侵入 6 模块写路径） | Q2 候选 B 的否决对象：F15 零跨模块 MODIFY 纪律 + 6 模块改造面大；全量重建成本已论证（§5.3） |
| 增量索引（游标/事件驱动） | 演进路径：数据量达亿字级时按 updated_at 游标增量（§5.3 注）；当前 YAGNI |
| 索引常驻服务/后台进程 | 懒初始化 + 首次搜索重建，无守护进程（F25 教训：不为不存在的生命周期设计常驻） |
| 搜索历史/热搜/推荐 | 无场景，YAGNI |
| 模糊匹配/拼写纠错/同义词扩展 | FTS5 通配符支持有限；无明确需求，YAGNI |
| GUI 搜索框接线 | 前端消费本 API，归 GUI 演进 issue |
| F20 MCP tool_search | MCP 1.0.0 时经 API 复用本能力（PRD §6.4 F20 工具列表含 search） |

---

## 11. 依赖关系

### 依赖（本模块需要）

| 模块 | 依赖类型 | 用途 |
|------|----------|------|
| F1 Project | 硬依赖 | 项目校验 |
| F2/F9/F10/F11/F12/F13 | 硬依赖 | 6 类索引数据源（只读） |
| F16 jieba | 硬依赖 | 中文分词（0.42.1 已锁定，零新增） |
| SQLite FTS5 | 硬依赖 | 倒排索引（实测 3.50.4 已启用；Python 3.11+ 标准发行均启用，最低支持版本需 CI 3.11 验证） |
| F19 #77 | 硬依赖 | token 中间件（API 端点受保护） |
| F7 CLI | 硬依赖 | `--json` 信封/退出码约定 |

### 被依赖（谁依赖本模块）

| 消费方 | 方式 |
|--------|------|
| GUI（未来接线） | GET /api/v1/search 搜索框 |
| F20 MCP（1.0.0） | tool_search 复用 service/API（PRD §6.4 已列） |
| 外部生态 | CLI 搜索 |

### 编号口径声明

F22 编号 0.6.0 立项未改号（ADR-019 v5 口径）；变体编号声明依据 AGENTS.md 模块类型谱系（第 16 变体），冲突以 ADR-019 v5+ 为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| D1 | FTS5 词法索引（非向量） | SQLite 内置 FTS5 + jieba 分词 | 零新增依赖（ADR-025）；中文分词是 FTS5 唯一的坑，jieba 已锁定；词法检索满足「定位哪章写过 X」主场景；确定性可测 | 向量检索（chromadb 已有但 embedding 模型下载 + 语义检索是 F6 消费场景，F22 需求是精确词定位，方向不同）；LIKE 全扫（无索引，百万字级 O(n) 全扫，高亮/筛选全自研，FTS5 零成本更优） |
| D2 | 索引归基础设施层（非业务表） | FTS5 虚拟表 + search_meta，不进 `Base.metadata` | FTS5 不是 SQLAlchemy 映射表；`CREATE IF NOT EXISTS` 幂等符合「无 alembic 轻量建表」惯例；业务层不感知索引实现 | 建业务实体表镜像索引（双写 + 迁移成本，违反 YAGNI） |
| D3 | 全量重建 + 脏检测（非写时同步） | `max(updated_at)` 比较 + 首查重建 | 零跨模块 MODIFY（F15 纪律）；重建 <10s 已论证（§5.3）；单用户本地无并发写 | 写时同步（6 模块 MODIFY 侵入）；事件驱动（无事件总线，自建=过度设计）；增量游标（量级未到，YAGNI） |
| D4 | 自有补充端口 search_repo | 原生 SQL 只读（max updated_at + FTS5 读写） | F15 audit_repo 先例：零 MODIFY 既有 Protocol；FTS5 原生 SQL 无法走 ORM 抽象 | 扩展现有 repo Protocol（跨模块 MODIFY）；SQLAlchemy text() 直嵌 service（领域层泄漏基础设施细节） |
| D5 | snippet() 原生高亮 | FTS5 `snippet(..., '<mark>', '</mark>', ...)` | 零自研高亮算法；`<mark>` 白名单安全；API 直接输出消费端可渲染 | 自研上下文截取 + 命中定位（重复造轮子，边界处理多） |
| D6 | 懒初始化（首查重建） | 无独立初始化命令/守护任务 | 用户零配置；无后台常驻（F25 教训）；首查 <10s 延迟可接受 | 启动时后台预热（lifespan 钩子 + 常驻成本）；独立 CLI 重建命令（YAGNI，脏检测已覆盖） |
| D7 | API `/api/v1/search` 顶层查询端点 | 项目 ID 走 query 参数 | 搜索是跨资源查询（6 类型），非项目子资源（F21 `/export` 是项目视图，语义不同）；与 `/api/v1/audit`（F15 顶层只读）风格一致 | `/projects/{pid}/search`（误导为项目子资源，且 types 跨类语义被弱化） |

---

## 13. 验收标准

> 「自动化载体」列：单元/集成/API/CLI/手动。

| # | 验收标准 | 自动化载体 | 验证命令（backend 目录，uv run） |
|---|----------|------------|-------------------------------|
| M1 | 中文关键词跨类型搜索：`search 龙 -p <项目>` 命中章节正文 + 角色 + 世界观 | 集成+CLI | `pytest tests/unit/test_search_index.py tests/unit/test_search_service.py` |
| M2 | 类型筛选：`-t chapter` 只返回章节命中 | CLI+API | `pytest ../tests/cli/test_cli_search.py ../tests/api/test_search_api.py` |
| M3 | 高亮：snippet 含 `<mark>` 标记且位置正确 | 集成 | `pytest tests/unit/test_search_index.py -k snippet` |
| M4 | API `GET /api/v1/search` 200 命中/空结果/404/422 全矩阵 | API | `pytest ../tests/api/test_search_api.py` |
| M5 | 索引脏检测：内容变更后首查重建并命中新内容；无变更不重建 | 单元 | `pytest tests/unit/test_search_service.py -k stale` |
| M6 | 软删内容不命中 | 单元 | `pytest tests/unit/test_search_service.py -k deleted` |
| M7 | FTS5 保留字/特殊字符查询安全（`AND`、引号、XML 标签） | 单元+集成 | `pytest tests/unit/test_search_tokenizer.py tests/unit/test_search_index.py -k escape` |
| M8 | 确定性：同数据同查询两次结果一致 | 集成 | `pytest tests/unit/test_search_index.py -k deterministic` |
| M9 | 空查询 422 / 纯标点查询空结果 | API+单元 | `pytest ../tests/api/test_search_api.py tests/unit/test_search_tokenizer.py` |
| M10 | 全量门禁：lint/unit/integration/api/cli 绿 + 覆盖率达标 | CI | `uv run ruff check src/ tests/unit/ ../tests/` + 全量 pytest |
| M11 | 手工闭环：CLI 搜索真实项目中文词命中 + GUI 未来接线冒烟 | 手动 | 发布前冒烟 |

> Issue #54 验收标准映射：跨内容类型搜索=M1 · 类型筛选=M2 · 搜索高亮=M3。

---

## 待澄清问题（评审时确认）

| # | 问题 | 选项 | 建议 |
|---|------|------|------|
| Q1 | **搜索方案**：FTS5 词法 vs LIKE vs 向量？ | A. SQLite FTS5 + jieba 分词（零新依赖，词法精确，倒排索引快）<br>B. LIKE 全表扫描（零依赖最简单，但无索引 O(n)、无 BM25 排序、高亮自研）<br>C. 向量检索（复用 chromadb + BGE embedding：语义搜索，但 embedding 模型下载 ~100MB + 中文语义精度依赖模型 + 与 F6/F14 RAG 职责重叠） | **A**：需求是「定位哪章写过 X」（精确词），不是「找语义相近内容」（F6/F14 RAG 已覆盖）；FTS5 实测可用 + jieba 已锁定 = 零新增依赖；B 的性能与能力边界差且自研成本反而高；C 引入模型下载/体积成本且与既有 RAG 职责冲突 |
| Q2 | **索引维护策略**：全量重建 vs 写时同步 vs 增量？ | A. 写时同步（各模块写路径同步更新索引——侵入 F2/F9/F10/F11/F12/F13 六个 service，改造面大）<br>B. 全量重建 + 脏检测（`max(updated_at)` 比较，变更后首查重建 <10s）<br>C. 增量游标（按 updated_at 逐条补索引——需各表稳定时间戳 + 游标状态，复杂度最高） | **B**：零跨模块 MODIFY（F15 纪律）；单项目量级全量重建成本已论证（§5.3，<10s）；单用户本地无并发写，重建频率 = 每次变更后首次搜索一次；C 的量级收益在当前数据规模下不存在（YAGNI），是未来演进路径（§10） |
| Q3 | **搜索范围**：项目内 vs 跨项目？ | A. 项目内（project_id 必填，单项目索引）<br>B. 跨项目（全部项目建索引，project_id 可选——索引粒度变为全局 + 结果带项目标识）<br>C. A + 预留（API 契约 project_id 可选，MVP 必填校验，未来放宽） | **A**：作者单项目写作是主场景（PRD 用户故事均单项目）；跨项目搜索 = 全局索引重建成本 ×N + 结果聚合展示复杂度，无明确需求（Q3 用户拍板若选 B 则索引粒度改为全局，重建逻辑同步调整）；C 的「预留」违背 YAGNI（API 兼容性在 1.0.0 前可自由演进） |
