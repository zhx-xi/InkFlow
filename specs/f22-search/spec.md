# F22: 全文搜索（search_service）— 功能规格
> **端**: cross

> **Spec 版本**: 1.2 | **日期**: 2026-08-09 | **依据**: PRD v2.2 §6.4 P1-16, Issue #54, Constitution P1-P6（P2 解耦 / P5 YAGNI）
> **所属阶段**: 0.6.0（#54 全文搜索，估算 2.5-3.5 人天——v1.1 拍板含 AI 检索增强 + 跨项目选择器；v1.2 拍板含 CLI 恒 HTTP）
>
> **Spec 变更（v1.0 → v1.1）**: **用户拍板（2026-08-09）**——Q1=A FTS5+jieba（词法主检索）+ **AI 语义检索增强**（接入既有 RAG VectorStoreProtocol，`mode=semantic`）；Q2=用户自定义方案（默认用户自维护 + 设置项开启 AI 自动维护 + 写完一章审计确认后增量同步 + 手动全量重建——**章节审计拆出单独立项 #208/F34**，F22 不阻塞等待；同步触发用内容变更 + REVIEW/FINAL 状态，审计确认作为 F34 落地后的增强触发点）；Q3=默认单项目 + **同世界观项目选择器跨项目检索**（`project_ids` 数组，会话级选择不持久化）。§2/§3/§5/§6/§7/§8/§11/§12/§13 同步修订；Issue #54 验收标准 + #208 立项已 gh comment 留痕。
> **Spec 变更（v1.1 → v1.2）**: **用户拍板（2026-08-09，方案 A）**——CLI 恒经 HTTP（ADR-030/F38 对齐，Issue #169）：`inkflow search` 查询经 `GET /api/v1/search`、`--rebuild` 经**新增 `POST /api/v1/search/rebuild` 端点**（v1.1 的「直接消费 service，不经 HTTP」废弃——F23/F21 直连先例已被 F38 推翻）。§3/§4/§5/§8/§9/§12/§13 同步修订。
>
> **关联 Issues**: [#54](https://github.com/zhx-xi/InkFlow/issues/54)；[#208](https://github.com/zhx-xi/InkFlow/issues/208)（F34 章节审计——AI 维护增强触发，非阻塞）
> **依赖**: ✅ F1（项目校验）· ✅ F2（章节正文源）· ✅ F9（角色档案源）· ✅ F10（世界观条目源）· ✅ F11（大纲源）· ✅ F12（时间线源）· ✅ F13（伏笔源）· ✅ F16（jieba 分词依赖已锁定，直接复用）· ✅ F14（RAG VectorStoreProtocol + chromadb + BGE——semantic 模式复用，零新增依赖）· ✅ F19 #77（token 中间件）· ✅ F38（CLI 恒经 HTTP 已合入，本模块 CLI 从第一天走 HTTP）· ✅ SQLite FTS5（实测 3.50.4 已启用，零新依赖）· ⏳ #208 F34 章节审计（增强触发点，**非阻塞**，见 §5.3 注）
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md)（模块化单体）· [ADR-002](../../adr/ADR-002.md)（六边形分层）· [ADR-003](../../adr/ADR-003.md)（Repository）· [ADR-004](../../adr/ADR-004.md)（Pydantic v2）· [ADR-012](../../adr/ADR-012.md)（错误处理）· [ADR-013](../../adr/ADR-013.md)（RAG：向量检索边界声明，§5.8）· [ADR-018](../../adr/ADR-018.md)（测试分层）· [ADR-019](../../adr/ADR-019.md)（版本里程碑 + 模块编号口径）· [ADR-021](../../adr/ADR-021.md)（内核进程化：token 契约）· [ADR-025](../../adr/ADR-025.md)（依赖锁定：零新增依赖）· [ADR-027](../../adr/ADR-027.md)（覆盖率门禁）· [ADR-030](../../adr/ADR-030.md)（本地内核服务化：CLI 恒经 HTTP，§4）
> **状态**: ✅ 已实现（PR #216，#54 2026-08-09）

---

## 1. 概述

提供**跨内容类型的全文搜索**：对项目内的章节正文与设定档案（角色/世界观/大纲/时间线/伏笔）建立本地全文索引，支持**关键词搜索（FTS5）、类型筛选、结果高亮**（PRD P1-16 三要素），并支持 **AI 语义检索增强（mode=semantic，复用 RAG）** 与 **同世界观多项目检索（project_ids 选择器）**，供作者快速定位「哪一章写过 X」「哪个角色提到 Y」——长篇创作的核心检索诉求。

**核心价值**: 小说项目数据量大（几十万字正文 + 数百档案条目）后，靠目录翻找/肉眼搜索不可行；F6 上下文注入（写作时取设定）解决的是「写作时自动带上下文」，F22 解决的是「作者主动检索」——两者互补，一个后台一个前台。

**v1.1 变更要点（用户拍板 2026-08-09）**:
1. **词法检索主体 = FTS5 + jieba**（Q1=A 确认）；**AI 检索 = semantic 模式**（复用 F14 RAG，作者可切换「关键词/语义」两种检索心智）
2. **索引维护 = 用户可控**（Q2）：默认用户自维护（手动全量重建 + 搜索时脏检测懒重建）；设置项开启 **AI 自动维护**后，写完一章（章节状态 REVIEW/FINAL 触发）自动增量同步；**章节审计确认（#208 F34）是 F34 落地后的增强触发点，F22 不阻塞等待**
3. **跨项目检索 = 同世界观选择器**（Q3）：默认单项目；搜索请求可带 `project_ids` 数组（GUI 选择器勾选同世界观项目），会话级选择、不持久化（持久化归 #175 世界观跨书复用）

**变体定位（第 16 变体「索引检索型」）**: 本模块是 **F12 确定性算法 × F15 只读聚合 × F16 文本分析**谱系的检索变体——无 LLM（词法检索确定性；semantic 模式复用既有 RAG 不新增 LLM 管线）、无业务实体表（FTS5 虚拟表是基础设施索引，不属于 `Base.metadata`）。§5 核心是**「分词 → 索引 → MATCH 查询 → 高亮」**四段确定性管线 + semantic 增强，全部基于 SQLite 内置 FTS5（实测 3.50.4 `sqlite_compileoption_used('ENABLE_FTS5')=1`）+ 已锁定依赖 jieba（F16 引入）+ 既有 RAG（F14），**零新增依赖**（ADR-025）。编号依据 AGENTS.md 模块类型谱系（F30=13 / F32=14 / F21=15 → 本模块第 16 变体），冲突以 ADR-019 v5+ 为准。

```
各模块档案（DB） ──只读聚合 + jieba 分词──▶ FTS5 虚拟表（search_index）
                                                │
查询词 ──jieba 分词 + MATCH 构造──▶ FTS5 查询 ──▶ 命中行 + snippet(<mark>) 高亮
（mode=semantic 时: 查询词 ──embedding──▶ VectorStore.retrieve ──▶ 语义命中）
```

**边界声明**:
- F22 词法检索是**确定性**（同一索引 + 同一查询 → 同一结果）；semantic 模式是**非确定**（embedding 模型输出 + 向量相似度排序），两者模式独立、互不污染
- F22 不新建业务实体表（FTS5 虚拟表 + 索引元数据归基础设施层，见 §2.4/§8）
- F22 默认**项目内搜索**；跨项目通过显式 `project_ids` 选择器（同世界观项目），**不做无差别全局搜索**（Q3 拍板）
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

> 不含 `project`（项目名/简介太短无检索价值，且项目列表页已有搜索——PRD §6.2「项目列表支持搜索」）。

### 2.2 SearchQuery / SearchHit / SearchResponse（DTO，v1.1 修订）

```python
class SearchMode(StrEnum):
    """检索模式（v1.1 拍板：词法默认 + 语义增强）。"""
    KEYWORD = "keyword"     # FTS5 词法（默认）
    SEMANTIC = "semantic"   # 向量语义（复用 F14 RAG）

class SearchQuery(BaseModel):
    """查询参数（API query / CLI 选项统一语义）。"""
    q: str                                  # 查询词（必填，1-100 字符，空白 422）
    project_ids: list[uuid.UUID]            # 必填：默认单项目；数组 = 同世界观选择器（Q3 拍板）
    types: list[SearchEntityType] | None    # None = 全部类型（类型筛选）
    mode: SearchMode = SearchMode.KEYWORD   # v1.1：keyword 默认 / semantic 增强
    limit: int = 20                         # 1-100
    offset: int = 0

class SearchHit(BaseModel):
    """单条命中。"""
    entity_type: SearchEntityType
    entity_id: uuid.UUID
    project_id: uuid.UUID       # v1.1：跨项目检索时标识来源项目
    title: str                  # 命中实体标题（如章节名/角色名）
    snippet: str                # 高亮片段（keyword: FTS5 snippet() 含 <mark>；semantic: chunk 上下文，见 §5.8）
    score: float = 0.0          # 相关度（keyword: BM25 rank；semantic: 余弦相似度）

class SearchResponse(BaseModel):
    total: int                  # 总命中数（不受 limit 影响）
    hits: list[SearchHit]
    query: str                  # 回显原始查询词
    types: list[SearchEntityType] | None  # 回显筛选
    mode: SearchMode            # 回显模式
    project_ids: list[uuid.UUID]          # 回显项目集合
```

### 2.3 领域模型文件归属

`SearchQuery/SearchHit/SearchResponse/SearchEntityType/SearchMode` 放 `domain/models/search.py`（纯 DTO，无 ORM——F23 WritingStreamEvent 判别联合 DTO 先例）；**不建** `domain/ports/search_*.py` 业务端口（检索是基础设施能力，见 §12 D2）；semantic 模式经既有 `VectorStoreProtocol`（F14）访问，不新建端口。

### 2.4 基础设施索引（非业务表）

| 结构 | 定义 | 说明 |
|------|------|------|
| FTS5 虚拟表 | `CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(title, body, entity_type UNINDEXED, entity_id UNINDEXED, project_id UNINDEXED)` | 词法索引；title/body 可搜，三个 UNINDEXED 列仅过滤；rowid = 自增无业务意义 |
| 元数据表 | `CREATE TABLE IF NOT EXISTS search_meta (key TEXT PRIMARY KEY, value TEXT)` | `last_rebuilt_at`（重建快照时间，ISO8601 UTC）+ `ai_maintenance`（AI 自动维护设置，见 §5.3）——脏检测用 |

- **建表方式**：`CREATE ... IF NOT EXISTS` 幂等语句，索引初始化时执行（首次搜索懒初始化，§5.2）；**不依赖 `Base.metadata.create_all`**（FTS5 虚拟表不是 SQLAlchemy 映射表）
- **semantic 索引**：复用 F14 RAG 既有 chroma collection（`VectorStoreProtocol.index_batch` 写入 CHAPTER_CHUNK 等实体），**不新建向量库**（§5.8）
- 删除语义：项目删除时 FTS 索引残留由**按 project_id 过滤 + 全量重建**自然覆盖（§7 E6）；向量库由 F14 `delete_project` 既有能力清理

---

## 3. API 契约

### 3.1 端点总览（2 个：GET 只读 + POST 重建）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/search` | 全文搜索（query 参数见下） |
| POST | `/api/v1/search/rebuild` | **手动全量重建索引**（v1.2 新增：承接 CLI `--rebuild`，ADR-030/F38 恒 HTTP） |

- GET query：`q`（必填）、`project_id` **或** `project_ids`（必填其一；`project_ids` 逗号分隔 UUID 数组 = 同世界观选择器，v1.1）、`types`（可选，逗号分隔枚举）、`mode`（可选，`keyword`/`semantic`，默认 keyword）、`limit`（默认 20）、`offset`（默认 0）
- GET 响应：200 `SearchResponse` JSON；幂等只读
- POST rebuild：query 参数 `project_id`（可选 UUID）——**缺省 = 重建全部项目索引**；传 = 仅重建指定项目。响应 200 `{"rebuilt_at": "<ISO8601 UTC>", "project_id": "<uuid>" | null}`；有副作用（写 FTS 索引），**用 POST 非 GET**（F12 check 只读先例不适用）

### 3.2 请求/响应示例

```http
GET /api/v1/search?q=龙&project_ids=1,2&types=chapter,world&mode=keyword&limit=5
→ 200
{
  "total": 3,
  "hits": [
    {
      "entity_type": "chapter",
      "entity_id": "00000000-0000-0000-0000-00000000000a",
      "project_id": "00000000-0000-0000-0000-000000000001",
      "title": "第 3 章 龙的苏醒",
      "snippet": "古井深处，<mark>龙</mark>瞳睁开。它沉睡千年……<mark>龙</mark>息如雷。",
      "score": 3.2
    },
    {
      "entity_type": "world",
      "entity_id": "00000000-0000-0000-0000-00000000000b",
      "project_id": "00000000-0000-0000-0000-000000000002",
      "title": "龙族领地",
      "snippet": "<mark>龙</mark>族盘踞的北境荒原，终年冰雪……",
      "score": 2.8
    }
  ],
  "query": "龙",
  "types": ["chapter", "world"],
  "mode": "keyword",
  "project_ids": ["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"]
}
```

```http
POST /api/v1/search/rebuild?project_id=00000000-0000-0000-0000-000000000001
→ 200
{
  "rebuilt_at": "2026-08-09T12:00:00Z",
  "project_id": "00000000-0000-0000-0000-000000000001"
}

POST /api/v1/search/rebuild   # 缺省 = 全部项目
→ 200
{
  "rebuilt_at": "2026-08-09T12:00:00Z",
  "project_id": null
}
```

### 3.3 异常映射表

| 场景 | HTTP 状态 | 错误 body（ADR-012 统一格式） | 抛出/捕获点 |
|------|-----------|-------------------------------|-------------|
| 任一 project_id 不存在 / 已软删 | 404 | `{"detail": "Project not found: <id>"}` | service 校验（复用 F9 character_errors `ProjectNotFoundError`，陷阱 16：**不导出**到 `ports/__init__.py`，router 显式 except 映射；数组逐个校验，第一个失败即 404） |
| `q` 缺失 / 空白 / 超长 | 422 | Pydantic 校验错误 | DTO 层（`Field(min_length=1, max_length=100)` + 空白 validator） |
| `types` 非法枚举 / `mode` 非法 | 422 | Pydantic 校验错误 | DTO 层 |
| `limit` 越界（>100） | 422 | Pydantic 校验错误 | DTO 层 |
| `project_id` 与 `project_ids` 同时缺省 | 422 | `{"detail": "project_id or project_ids required"}` | DTO validator（v1.1） |
| 查询语法构造失败（分词空） | 200 | 空结果（`total: 0`）——分词后无有效词（如纯标点），返回空而非 422 | service（§5.3 注） |
| 索引尚未建立 | 200 | 懒初始化：首次查询自动全量重建后返回真实结果 | service（§5.2） |
| semantic 模式但向量库为空 | 200 | 空结果 + `mode=semantic` 回显（向量库未建/未提取内容，无命中不报错） | service（§5.8 注） |
| rebuild 传了不存在的 project_id | 404 | `{"detail": "Project not found: <id>"}` | service 校验（同 GET，逐个校验） |
| 内部错误（DB 异常） | 500 | `{"detail": "Internal server error"}` | router `except Exception` → loguru（ADR-016） |

---

## 4. CLI 命令签名

F7 全局约定：`--json` 信封、退出码 0/1/2。F22 新增 `inkflow search` 命令，**经 ensure_kernel() + InkFlowHTTPClient 调用内核 REST API**（v1.2 拍板方案 A：ADR-030/F38「CLI 恒经 HTTP」——不直接消费 domain service；与 F38 改造后的 style/audit 等命令同一模式）。

```text
inkflow search <query> --project <name|id> [--project <name|id>]... [--type TYPE]... [--mode keyword|semantic] [--limit N] [--offset N] [--json]
inkflow search --rebuild [--project <name|id>]

参数:
  query                    查询词（必填，1-100 字符；--rebuild 模式不适用）
  --project, -p            项目名称或 ID（**可重复**：多个 = 同世界观选择器，v1.1；必填 ≥1）
  --type, -t               可搜索类型（可重复，如 -t chapter -t character；缺省 = 全部）
  --mode                   检索模式（默认 keyword；semantic = AI 语义检索，v1.1）
  --limit                  默认 20，最大 100
  --offset                 默认 0
  --rebuild                手动全量重建索引（v1.1 用户自维护入口；不传 --project 重建全部项目索引，传则单项目）
  --json                   输出 JSON 信封

成功: 退出 0；非 --json 时打印人类可读结果（类型徽标 + 项目名 + 标题 + snippet）；--json 时信封 data = SearchResponse（--rebuild 时 data = {"rebuilt_at", "project_id"}）
失败: 项目不存在 → 退出 1，error = "项目不存在: <name>"（HttpApiError 404 → NOT_FOUND，F38 错误码映射）
      query 空白 → 退出 2（Typer 自动）
      内核未运行 → ensure_kernel 拉起（KernelStartupError → KERNEL_ERROR，F38 模式）
```

HTTP 端点映射（v1.2）：
- `inkflow search <query> -p X` → `GET /api/v1/search?q=...&project_ids=...`（--mode/--type/--limit/--offset 透传）
- `inkflow search --rebuild [-p X]` → `POST /api/v1/search/rebuild[?project_id=...]`

示例：

```text
$ inkflow search 龙 -p 我的书 -t chapter
[chapter] 我的书 · 第 3 章 龙的苏醒
  古井深处，[龙]瞳睁开。它沉睡千年……[龙]息如雷。

$ inkflow search 龙 -p 我的书 -p 系列前传 --mode semantic --json
{"success": true, "data": {"total": 2, "hits": [...], "query": "龙", "types": null, "mode": "semantic", "project_ids": [...]}}
```

> CLI 展示高亮用 `[...]` 方括号标记（终端无 HTML 语义）；`--json` 时 snippet 保留 `<mark>`（消费端自行渲染/剥离）。

---

## 5. 索引检索模式（关键差异：分词 → FTS5 → 高亮）

> ⚠️ **本节是 F22 与既有样板的核心差异点**：F12 §5 是「一致性检查算法」，F16 §5 是「文本统计特征」，F14 §5 是「提取门面」；本模块的 §5 是**确定性全文检索管线**（jieba 中文分词 + SQLite FTS5 倒排索引 + MATCH 查询 + snippet 高亮）+ **semantic 增强**（复用 RAG），无新增 LLM、零新增依赖。

### 5.1 模式总览

```text
 ┌─────────────────────────────────────────────────────────────┐
 │ SearchService.search(query)                                  │
 └──────────────────────────┬──────────────────────────────────┘
                            ▼
 ① 校验项目存在（逐个 project_id，F1 ProjectRepository.get）→ ProjectNotFoundError(404)
 ② 确保词法索引就绪（_ensure_index）:
    - CREATE VIRTUAL TABLE IF NOT EXISTS（幂等，§2.4）
    - 脏检测（_is_stale）: search_meta.last_rebuilt_at 缺失 / 任一数据源
      max(updated_at) > last_rebuilt_at → 全量重建（§5.3）
 ③ 查询词分词: jieba.cut_for_search(q) → 词序列（过滤空白/纯标点）
 ④ 构造 MATCH: 每词 `"<词>"`（FTS5 引号精确短语）+ 空格连接（隐式 AND）
 ⑤ 执行: SELECT entity_type, entity_id, project_id, title,
         snippet(search_index, 0, '<mark>', '</mark>', '…', 48) AS snippet,
         rank AS score
         FROM search_index WHERE search_index MATCH ? AND project_id IN (?)
         AND entity_type IN (?) ORDER BY rank LIMIT ? OFFSET ?
 ⑥ 组装 SearchResponse（total 用同条件 COUNT(*) 另查）
 ── mode=semantic 分支（§5.8）──
 ⑤' VectorStoreProtocol.retrieve(query, project_ids) → 命中实体 → 映射 SearchHit
```

**模式要点**:
1. **确定性**：keyword 模式同一索引 + 同一查询 → 同一结果集（BM25 稳定，§5.6）；semantic 模式**不承诺确定性**（模式独立标注，§1 边界）
2. **中文分词是成败关键**：FTS5 默认 unicode61 分词器对中文按「连续 CJK 串」整体切分——**必须 jieba 分词后空格连接入库 + 查询词同样分词**（F16 已锁定 jieba 0.42.1，零新依赖）
3. **v1.1 索引维护 = 用户可控**（Q2 拍板，§5.3）：默认懒重建（用户自维护心智）+ 设置项 AI 自动维护 + 手动全量重建命令
4. **无副作用**：搜索不修改业务数据；重建只写本模块基础设施表

### 5.2 索引初始化与生命周期

- **懒初始化**：首次 `search` 调用时建表 + 全量重建（无独立初始化命令；`inkflow search` 首次运行即触发）
- **重建触发条件**（脏检测，`_is_stale`）：
  ① `search_meta` 无 `last_rebuilt_at`（首次）
  ② 任一数据源 `max(updated_at)` > `last_rebuilt_at`（跨 6 表各查一次 max，成本 ~6 个轻量 SQL）
  ③ **手动全量重建**：`inkflow search --rebuild`（v1.1 用户自维护入口，§4 增补——见下注）
  ④ **AI 自动维护**（设置开启时）：章节状态进入 REVIEW/FINAL 或内容变更后增量同步（§5.3）
- **数据源 max(updated_at) 查询**：走自有补充端口 `search_repo`（F15 audit_repo 先例：ORM 原生 SQL 只读，零跨模块 MODIFY），见 §8.2
- **并发**：单用户本地（F19 serve 单进程），重建用 `asyncio.Lock` 防并发重复重建

> **v1.1/v1.2 CLI 增补**：`inkflow search --rebuild [--project <id>]` 手动全量重建（用户自维护默认路径；不传 project 重建全部项目索引，传则单项目）。对应 §4 命令签名补 `--rebuild` 标志；v1.2 起 `--rebuild` 经 `POST /api/v1/search/rebuild` 端点（ADR-030/F38 恒 HTTP）。

### 5.3 索引维护策略（v1.1 用户拍板方案）

**Q2 拍板（2026-08-09）**：默认用户自维护 + 设置项开启 AI 自动维护 + 写完一章审计确认后增量同步 + 手动全量重建。落地设计：

| 层级 | 行为 | 说明 |
|------|------|------|
| 默认（用户自维护） | 懒重建（搜索时脏检测触发全量重建）+ 手动 `--rebuild` | 索引永远正确（脏检测兜底），用户可手动强制重建 |
| AI 自动维护（设置项） | `search_meta.ai_maintenance=true` 时启用增量同步 | 设置项存 F32 app_settings（`ai_maintenance_enabled`）或 search_meta（Q 拍板口径：**存 search_meta**，搜索模块自管，不扩 F32 设置面） |
| 增量触发点 | ① 章节状态 → REVIEW/FINAL（F2 四态既有）② 内容变更（updated_at 增量）③ **审计确认（#208 F34 落地后增强）** | ①② 本模块实现；③ 非阻塞增强（F34 完成前用 ①② 覆盖「写完一章」语义） |
| 手动全量重建 | `--rebuild` 始终可用 | 用户显式控制兜底 |

**章节审计关联（v1.1 声明）**：用户设想「写完一章 → 审计确认 → 增量同步」中的**审计确认**由 **#208 F34 章节审计**承接（2026-08-09 已立项，spec 起草中）。F22 **不阻塞等待 F34**——用「章节状态 REVIEW/FINAL + 内容变更」实现同一语义（写完一章 = 状态变更），F34 落地后审计确认（accept）作为**增强触发点**接入（§5.3 注 + §10 演进，端口不变）。

**全量重建算法**：

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

**增量同步算法（AI 自动维护）**：

```text
_ensure_index():
  ...
  elif search_meta.ai_maintenance == "true" and _has_pending_changes():
    # _has_pending_changes: 任一源 max(updated_at) > last_rebuilt_at（同 _is_stale）
    # 增量 = 拉取 updated_at > last_rebuilt_at 的变更行（各源分页），
    #         DELETE 对应 (entity_type, entity_id) 旧索引行 + INSERT 新分词行
    # 触发点: 搜索时惰性执行（同懒重建）; 审计确认增强触发 = F34 落地后
    _incremental_sync()
```

> ⚠️ **增量 vs 全量取舍**：单项目量级（≤300 万字）下全量重建 <10s、增量 <2s——**v1.1 默认懒重建已满足性能**；增量同步是 AI 自动维护开启时的优化（减少每次变更后全量重建的 I/O），实现优先级低于全量（RED 批序：全量重建 → 手动 rebuild → AI 增量）。若实现时间不足，AI 自动维护可先退化为「懒重建 + REVIEW/FINAL 触发全量」，增量作为后续优化（§10 演进）。

### 5.4 高亮（snippet 生成）

- keyword 模式：FTS5 内置 `snippet()` 函数——`snippet(search_index, 0, '<mark>', '</mark>', '…', 48)`（第 0 列 title 不参与，第 1 列 body 取命中上下文 48 token，命中词前后缀 `<mark>`/`</mark>`）
- **安全**：`<mark>` 是白名单标签；正文其他 HTML 特殊字符在入库分词前**已按 XML 文本转义**（§5.5），snippet 输出天然安全
- semantic 模式：高亮降级为 **chunk 上下文**（向量命中返回内容片段，无词级 `<mark>` 标记——向量检索无词位置信息；§5.8）
- title 命中：title 列**不**做 snippet（title 短，直接返回全名）

### 5.5 分词与索引内容预处理（确定性核心）

| 步骤 | 规则 |
|------|------|
| ① 文本转义 | `& < > "` → XML 实体（防 snippet 注入 + 防 FTS5 语法混淆） |
| ② 拼接 | title + " " + body_text（§2.1 各类型拼接规则，同 F21 §6.3 摘要口径但**含全文**：chapter 是 content 全文，档案是字段拼接） |
| ③ jieba 分词 | `jieba.cut_for_search(text)` → 词序列（搜索引擎模式：长词 + 子词，召回更全） |
| ④ 过滤 | 去空白、纯标点词、单字符无意义词（**保留单字符中文词**——"龙" 是有效查询，只过滤英文单字母/纯符号） |
| ⑤ 入库 | 分词结果空格连接写入 body 列 |

查询侧同管线（②-④），MATCH 构造：每词 `"词"`（双引号）空格连接——FTS5 引号 = 精确短语，双引号同时**转义 FTS5 语法保留字**（`AND OR NOT NEAR` 等作为词时被引号保护）；多词 = 隐式 AND。查询词含引号本身 → 双引号包裹时 FTS5 内 `""` 转义为 `""""`（SQL 层再参数化）；分词后空词序列 → 返回空结果（§3.3）。

### 5.6 排序与确定性

- keyword：FTS5 `rank`（BM25 默认），`ORDER BY rank`（低分在前 = 更相关）；API score 字段 = rank 值（float）
- semantic：余弦相似度降序（F14 retrieve 排序，score = 相似度）
- 确定性：keyword 相同文档集 → BM25 稳定（无随机种子）；`total` 与 `hits` 同一次查询内一致（快照语义同 F21 E11）

### 5.7 跨项目检索语义（v1.1 Q3 拍板）

- `project_ids` 数组 → SQL `project_id IN (...)`（参数化）；多项目命中同 entity 语义：不同项目的实体是独立行（项目隔离，不合并）
- 排序：**跨项目不重排 BM25**——各项目文档在同一 FTS5 表内，rank 天然全局可比（同一表同一语料空间）；semantic 同理（同一向量库）
- GUI 选择器（前端职责）：项目列表页提供「同世界观」多选，会话级状态（不持久化到后端；持久化归 #175 世界观跨书复用）

### 5.8 semantic 模式（AI 检索增强，v1.1 Q1 拍板）

**复用 F14 RAG，零新增依赖**：

```text
mode=semantic:
 ① 校验项目（同 keyword）
 ② 查询 embedding: 复用 F14 embedding 装配（VectorStoreProtocol 实现内 BGE 模型）
    - 不新起 LLM 管线; VectorStoreProtocol.retrieve(query, ...) 内部完成 embedding
 ③ VectorStoreProtocol.retrieve(query, project_ids=..., limit=...) → RetrievedEntity[]
    - 复用既有端口（domain/ports/vector_store.py，F14 已实现）
 ④ 映射: RetrievedEntity → SearchHit
    - entity_type: 映射（vector 的 EntityType ↔ search 的 SearchEntityType，对齐表见下）
    - entity_id / project_id / title: 从 RetrievedEntity.metadata 取
    - snippet: 取 RetrievedEntity.content 截断 200 字符（无词级高亮，§5.4）
    - score: 相似度
```

**EntityType 映射表（vector ↔ search）**：

| F14 EntityType（vector_store） | F22 SearchEntityType | 备注 |
|--------------------------------|----------------------|------|
| CHAPTER_CHUNK | chapter | 章节块 → 章节命中 |
| CHARACTER | character | |
| SETTING | world | |
| FORESHADOWING | foreshadowing | |
| TIMELINE_EVENT | timeline | |
| （无） | outline | ⚠️ **F14 无 outline 类型**——向量库不索引大纲，semantic 模式 outline 恒无命中（覆盖缺口，见下） |

> ⚠️ **覆盖缺口声明（v1.1 load-bearing）**：RAG 向量库（F14）只索引**提取管线产出**——章节块（提取过的）+ 提取出的角色/世界/伏笔/时间线。**手动创建的档案条目、未走提取的章节不在向量库** → semantic 模式对「手动内容」召回不全、outline 恒无命中。这是**模式差异而非缺陷**（keyword 全量覆盖、semantic 语义补充），spec 明确声明：semantic 结果集 ⊆ keyword 语义近似，GUI 可标注「AI 检索」徽标提示召回范围。F14 后续若扩展索引全量（不在本 spec），semantic 覆盖自动提升。

**semantic 失败语义**：embedding 模型不可用（未部署/加载失败）→ 200 + 空结果 + loguru（不降级为 keyword——模式显式请求，失败空结果比静默换模式诚实）；测试用 FakeEmbeddings（F14 先例，size=384 + 临时 chroma 目录）。

### 5.9 索引检索型 vs 既有样板：差异对照表

| 维度 | F12 一致性检查 | F16 文本分析 | **F22 全文搜索** |
|------|---------------|--------------|------------------|
| 数据源 | 单模块 | 章节文本 | 6 模块只读聚合 |
| 输出 | 内存报告 | 内存报告 | **FTS5 索引 + 查询命中（+semantic RAG）** |
| 新业务表 | 无 | 无 | **无（FTS5 虚拟表 + meta 表，基础设施）** |
| 新增依赖 | 无 | jieba（0.2.0 引入） | **零（jieba/FTS5/RAG 均已有）** |
| 新 API | 8 端点 CRUD | 1 端点 | **1 只读端点（mode 双模式）** |
| 新 CLI | timeline 组 | style 组 | **search 命令** |
| 算法性质 | 相邻对扫描 | 统计特征 | **分词 + 倒排索引 + BM25（+向量相似度）** |
| 跨模块 MODIFY | 无 | 无 | **无（补充端口 search_repo）** |
| LLM | 无 | 可选 | **无新增（semantic 复用既有 embedding）** |

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

- 重建只读**活动数据**（各 repo `list` 的既有语义——character/world/outline/foreshadowing docstring 确认排除软删；chapter 需服务层显式过滤，2026-08-09 源码核实）
- 已软删实体的旧索引行：全量重建自然清除（DELETE + 重插）

### 6.3 类型筛选语义

- `types=None` → 全部 6 类；`types=[...]` → SQL `entity_type IN (...)`（参数化）
- 空列表 `types=[]` → 视为 None（全部）——客户端省略参数的自然形态，测试锁定
- semantic 模式：types 筛选映射到向量库 metadata 过滤（F14 retrieve 支持 metadata filter，若端口不支持则 service 侧后过滤——实现时核实 VectorStoreProtocol.retrieve 签名）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| E1 | 任一项目不存在 / 已软删 | 404（ProjectNotFoundError 复用，§3.3；多项目逐个校验） |
| E2 | 查询词空白 / 仅标点 | 422（空白）/ 200 空结果（分词后无有效词） |
| E3 | 查询词超长（>100） | 422 |
| E4 | 无索引（首次搜索） | 懒初始化：建表 + 全量重建后返回真实结果（首建延迟 <10s，可接受） |
| E5 | 无命中 | 200 `{total: 0, hits: []}` |
| E6 | 项目已删除（硬删）后残留索引行 | 查询按 project_id 过滤 + 重建只写活动项目 → 残留行不返回（自然隔离） |
| E7 | 并发重建 | `asyncio.Lock` 双检锁，只允许一次重建（§5.3） |
| E8 | 重建中断（进程崩溃） | `last_rebuilt_at` 不更新 → 下次搜索重新判脏重建（幂等） |
| E9 | 查询词含 FTS5 保留字（AND/OR/NOT） | 引号包裹转义，按普通词处理（§5.5） |
| E10 | 正文含 HTML/XML 标签 | 入库前转义 → 按字面文本检索，不解析（§5.5 ①） |
| E11 | jieba 词典未加载 | jieba 默认词典随包分发（F16 已验证无网络依赖），加载失败 = 500（loguru） |
| E12 | semantic 模式向量库为空 / embedding 不可用 | 200 空结果 + loguru（不降级 keyword，§5.8） |
| E13 | AI 自动维护设置开启但增量同步失败 | 回退懒重建（_is_stale 兜底——增量失败不阻塞搜索，下次判脏全量重建） |
| E14 | 跨项目检索其中一项目无索引内容 | 该项目自然无命中（不报错，total 计数其余项目） |

---

## 8. 文件结构

### 8.1 CREATE/MODIFY 清单（对照真实源码树 `backend/src/inkflow/`）

| 类型 | 路径 | 说明 |
|------|------|------|
| CREATE | `domain/models/search.py` | SearchEntityType / SearchMode / SearchQuery / SearchHit / SearchResponse（§2） |
| CREATE | `domain/services/search_service.py` | SearchService：`search()` 编排 + `_ensure_index/_is_stale/_rebuild/_incremental_sync` + semantic 分支（§5.1-5.3/5.8） |
| CREATE | `domain/services/_search_tokenizer.py` | 分词与预处理纯函数（jieba 封装 + 转义 + 过滤 + MATCH 构造，§5.5）——`_word_count.py`/`_style_analyzer.py` 先例 |
| CREATE | `domain/ports/search_repository.py` | **自有补充端口**（F15 audit_repository 先例）：`max_updated_at(table)` + FTS 读写（见 §8.2） |
| CREATE | `infrastructure/database/repositories/search_repo.py` | SQLiteSearchRepository：FTS5 建表/重建/查询原生 SQL + meta 读写（含 ai_maintenance 设置） |
| CREATE | `api/routers/search.py` | GET `/api/v1/search` + POST `/api/v1/search/rebuild`（§3） |
| CREATE | `cli/commands/search.py` | `inkflow search` 命令 + `--rebuild`（§4；ensure_kernel + InkFlowHTTPClient，F38 模式） |
| CREATE | `backend/tests/unit/test_search_models.py` | DTO 校验（空白/超长/枚举/project_ids 必填） |
| CREATE | `backend/tests/unit/test_search_tokenizer.py` | 分词/转义/MATCH 构造（中文词、保留字、标点过滤） |
| CREATE | `backend/tests/unit/test_search_service.py` | 编排：mock repos + mock search_repo → 判脏/重建/增量/软删排除/多项目 |
| CREATE | `backend/tests/unit/test_search_index.py` | **真 SQLite 内存库 FTS5 集成**（§9.2 关键场景） |
| CREATE | `backend/tests/unit/test_search_semantic.py` | semantic 模式：FakeEmbeddings + 临时 chroma（F14 先例）→ 映射/覆盖缺口/空库降级 |
| CREATE | `tests/cli/test_cli_search.py` | CLI 测试（仓库根 `tests/cli/`，Issue #61 约定；**新文件必须显式追加 integration-cli-backend job**——陷阱 13/15） |
| CREATE | `tests/api/test_search_api.py` | API 端点测试（仓库根 `tests/api/`，F21 同款落点） |
| MODIFY | `api/app.py` | `app.include_router(search.router)` + import（1 行） |
| MODIFY | `api/deps.py` | SearchService 装配（注入 6 个数据源 repository + search_repo + project_repo + 可选 VectorStoreProtocol） |
| MODIFY | `cli/app.py` | import + `app.command()` 注册 search（1-2 行） |
| MODIFY | `.github/workflows/ci.yml` | 两处联动（陷阱 13/15，2026-08-09 核实）：① `tests/cli/test_cli_search.py` 显式追加 **integration-cli-backend** job 文件列表 ② `tests/api/test_search_api.py` 显式追加 **integration-project-backend** job 文件列表（既有先例 `../tests/api/test_project_api.py`）；coverage-backend 跑 `../tests/api/` 目录自动覆盖，无需追加 |

> ⚠️ 反向核对（F32 教训）：上表 CREATE 均已核实不存在、MODIFY 均已确认存在（2026-08-09）；ci.yml 联动已按真实 job 结构写明。

### 8.2 自有补充端口 search_repository（F15 audit_repo 先例）

F22 需要「跨 6 表查 max(updated_at)」与「FTS5 原生 SQL 读写」——既有 Protocol 均无此能力，且**不 MODIFY 任何既有 Protocol**（F15 §5.5 模式）：

```python
class SearchRepositoryProtocol(Protocol):
    """搜索索引基础设施端口（FTS5 + 元数据；不触碰业务表）。"""
    async def ensure_index(self) -> None: ...
    async def is_stale(self, sources: list[tuple[str, datetime]]) -> bool: ...
    # 实现内部: 读 search_meta.last_rebuilt_at vs 各源 max(updated_at)
    async def rebuild(self, documents: Iterable[SearchDocument]) -> None: ...
    # 实现内部: DELETE FROM search_index + 批量 INSERT + upsert meta
    async def incremental_sync(self, documents: Iterable[SearchDocument],
                               deleted: Iterable[tuple[str, int]]) -> None: ...
    # 实现内部: DELETE 旧行 + INSERT 新行 + upsert meta（AI 自动维护）
    async def query(self, match: str, project_ids: list[int], types: list[str] | None,
                    limit: int, offset: int) -> tuple[int, list[SearchHit]]: ...
    # 实现内部: SELECT + COUNT，FTS5 snippet() 高亮
    async def get_setting(self, key: str) -> str | None: ...
    async def set_setting(self, key: str, value: str) -> None: ...
    # ai_maintenance 设置读写（§5.3）
```

- `SearchDocument`（基础设施 DTO，`dataclass`）：`entity_type / entity_id / project_id / title / body`（分词后文本）
- `max_updated_at` 归属：放 search_repo（对 6 张业务表各发一条 `SELECT max(updated_at) FROM <table> WHERE project_id=?`——**原生 SQL 只读**，不建 ORM 映射，F15 audit_repo 同款）
- semantic 模式经既有 `VectorStoreProtocol`（F14），**不新增端口**（§5.8）
- 依赖方向合法：领域层依赖 `SearchRepositoryProtocol`，基础设施实现 `SQLiteSearchRepository`（六边形，ADR-002）

---

## 9. 测试策略

沿用 ADR-018 三层目录 + pytest markers；无 LLM 下载（semantic 用 FakeEmbeddings，F14 先例）。

### 9.1 测试层次

| 层 | 文件 | 内容 |
|----|------|------|
| 单元 | `tests/unit/test_search_tokenizer.py` | 分词纯函数：中文词拆分、保留字转义、标点过滤、XML 转义 |
| 单元 | `tests/unit/test_search_service.py` | 编排：mock 数据源 repos + mock search_repo → 判脏（stale/新鲜/首次）、重建触发、增量触发、软删排除、多项目校验、types 筛选透传 |
| 集成 | `tests/unit/test_search_index.py` | **真 SQLite 内存 FTS5**（`aiosqlite :memory:` + CREATE VIRTUAL TABLE）：索引→查询闭环、中文命中、snippet `<mark>` 断言、BM25 排序、多项目过滤、分页 |
| 单元 | `tests/unit/test_search_semantic.py` | semantic：**mock VectorStoreProtocol**（父侧裁定 2026-08-09：F22 是 RAG 消费方，mock retrieve 返回固定 RetrievedEntity 等价 FakeEmbeddings 固定向量；真 chroma 集成已由 F14 test_langchain_vector_store.py 覆盖且避免 chromadb/coverage 同进程冲突，ci.yml 无需新增 --ignore）→ EntityType 映射、outline 恒空（覆盖缺口）、空库空结果、失败不降级 |
| API | `tests/api/test_search_api.py` | TestClient：200 命中/空结果/404/422（含 project_id+project_ids 双缺 422）、mode 参数、token 中间件、POST rebuild（200 全量/单项目、404 项目不存在） |
| CLI | `tests/cli/test_cli_search.py` | CliRunner + F38 mock 轨（patch ensure_kernel + InkFlowHTTPClient）：命中输出、`--json` 信封、404 错误、多 `-p` 多 `-t`、`--rebuild`、`--mode` |

### 9.2 关键场景（RED 批要点）

1. **中文分词命中**：内容「古井深处龙瞳睁开」+ 查询「龙」→ 命中（jieba 空格分词入库 + 查询分词一致——load-bearing）
2. **跨类型**：同词命中 chapter + character + world 三类，types 筛选后只剩指定类
3. **高亮**：snippet 含 `<mark>龙</mark>` 且不含未转义 HTML（E10）
4. **保留字安全**：查询 `AND` → 命中含 "AND" 的正文（引号转义生效）
5. **判脏**：更新一章 → 下次搜索重建（mock 源 max updated_at 变化）；无变更 → 不重建（mock 断言 rebuild 未调用）
6. **AI 增量（v1.1）**：ai_maintenance=true + 变更 → incremental_sync 调用（mock 断言）；增量失败 → 回退懒重建（E13）
7. **多项目（v1.1）**：project_ids=[1,2] → 两个项目命中；project_id 不存在 → 404
8. **semantic（v1.1）**：FakeEmbeddings 返回固定向量 → retrieve 命中映射 SearchHit；outline 类型恒空；embedding 异常 → 200 空
9. **软删排除**：软删角色不索引不命中
10. **空结果 / 纯标点查询**：200 空 / total 0
11. **确定性**：同数据同查询两次结果一致（BM25 稳定）

### 9.3 覆盖率

模块 ≥80%（ADR-027 口径）；FTS5 集成测试覆盖索引路径（mock 层覆盖不了 FTS5 行为，test_search_index.py 必须真库）；semantic 用 FakeEmbeddings（F14 先例，不进真实模型）。

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| 语义/向量检索独立实现 | 复用 F14 RAG（VectorStoreProtocol + chromadb + BGE）——F22 semantic 模式是**消费方**，不新建向量基础设施（ADR-013 边界） |
| 无差别全局搜索（所有项目） | Q3 拍板：默认项目内 + 显式同世界观选择器；全局搜索无场景 |
| 索引常驻服务/后台进程 | 懒初始化 + 懒重建 + 手动 rebuild；无守护进程（F25 教训） |
| 写时同步索引（侵入 6 模块写路径） | Q2 否决：F15 零跨模块 MODIFY 纪律；懒重建/增量已覆盖 |
| 审计确认联动（#208 F34） | F34 立项承接「审计确认后同步」增强触发（§5.3）；F22 用 REVIEW/FINAL 状态覆盖「写完一章」语义，不阻塞 |
| 同世界观项目组持久化 | 会话级选择器（Q3）；持久化归 #175 世界观跨书复用 |
| 搜索历史/热搜/推荐 | 无场景，YAGNI |
| 模糊匹配/拼写纠错/同义词扩展 | FTS5 通配符支持有限；无明确需求，YAGNI |
| GUI 搜索框接线 | 前端消费本 API（含多项目选择器 UI），归 GUI 演进 issue |
| F20 MCP tool_search | MCP 1.0.0 时经 API 复用本能力（PRD §6.4 F20 工具列表含 search） |

---

## 11. 依赖关系

### 依赖（本模块需要）

| 模块 | 依赖类型 | 用途 |
|------|----------|------|
| F1 Project | 硬依赖 | 项目校验（单/多） |
| F2/F9/F10/F11/F12/F13 | 硬依赖 | 6 类索引数据源（只读） |
| F16 jieba | 硬依赖 | 中文分词（0.42.1 已锁定，零新增） |
| F14 RAG | 条件依赖（mode=semantic 时） | VectorStoreProtocol + chromadb + BGE（复用，零新增） |
| SQLite FTS5 | 硬依赖 | 倒排索引（实测 3.50.4 已启用；CI 3.11 验证） |
| F19 #77 | 硬依赖 | token 中间件（API 端点受保护） |
| F7 CLI | 硬依赖 | `--json` 信封/退出码约定 |
| #208 F34 章节审计 | **非阻塞关联** | 增强触发点（审计确认 → 增量），落地后接入；F22 不等待 |

### 被依赖（谁依赖本模块）

| 消费方 | 方式 |
|--------|------|
| GUI（未来接线） | GET /api/v1/search 搜索框 + 同世界观选择器 |
| F20 MCP（1.0.0） | tool_search 复用 service/API（PRD §6.4 已列） |
| 外部生态 | CLI 搜索 |

### 编号口径声明

F22 编号 0.6.0 立项未改号（ADR-019 v5 口径）；变体编号声明依据 AGENTS.md 模块类型谱系（第 16 变体），冲突以 ADR-019 v5+ 为准；F34 章节审计（#208）为 0.6.0 新增编号（F33 之后）。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| D1 | FTS5 词法索引（主）+ RAG 语义（增强） | SQLite FTS5 + jieba 分词（keyword）+ 复用 F14 VectorStore（semantic） | Q1 拍板（2026-08-09）：词法满足「定位哪章写过 X」主场景（零新增依赖、确定性可测）；语义作为增强模式复用既有 RAG（零新依赖），两模式互补 | 纯向量（embedding 模型下载 + 精确词漂移 + 与 F6/F14 职责重叠）；LIKE 全扫（无索引、无 BM25、高亮自研） |
| D2 | 索引归基础设施层（非业务表） | FTS5 虚拟表 + search_meta，不进 `Base.metadata` | FTS5 不是 SQLAlchemy 映射表；`CREATE IF NOT EXISTS` 幂等符合轻量建表惯例；业务层不感知索引实现 | 业务实体表镜像索引（双写 + 迁移成本） |
| D3 | **v1.1：懒重建（默认）+ AI 增量（设置项）+ 手动 rebuild** | 默认脏检测懒重建；`ai_maintenance=true` 增量；`--rebuild` 显式 | Q2 拍板（2026-08-09）：用户自维护默认（可控）+ 开关 AI 自动维护（写完一章 REVIEW/FINAL 触发）+ 手动兜底；零跨模块 MODIFY；审计确认（#208）为增强触发点 | 写时同步（6 模块 MODIFY）；纯懒重建（无 AI 自动维护，用户设想不满足）；纯增量（复杂度高，量级未到） |
| D4 | 自有补充端口 search_repo | 原生 SQL 只读（max updated_at + FTS5 读写 + ai_maintenance 设置） | F15 audit_repo 先例：零 MODIFY 既有 Protocol；FTS5 原生 SQL 无法走 ORM 抽象 | 扩展现有 repo Protocol（跨模块 MODIFY）；SQLAlchemy text() 直嵌 service（基础设施泄漏） |
| D5 | snippet() 原生高亮 | FTS5 `snippet(..., '<mark>', '</mark>', ...)` | 零自研高亮算法；`<mark>` 白名单安全 | 自研上下文截取（重复造轮子）；semantic 词级高亮（向量无词位置，降级 chunk 上下文） |
| D6 | 懒初始化（首查重建） | 无独立初始化命令/守护任务 | 用户零配置；无后台常驻（F25 教训）；首查 <10s 可接受 | 启动时后台预热（lifespan 钩子 + 常驻成本） |
| D7 | API `/api/v1/search` 顶层查询端点 | project_ids 走 query 参数 | 搜索是跨资源查询（6 类型 + 多项目），非项目子资源；与 `/api/v1/audit`（F15）风格一致 | `/projects/{pid}/search`（误导为项目子资源，且多项目语义被弱化） |
| D8 | **v1.1：project_ids 数组（默认单项目）** | `project_id` 或 `project_ids` 必填其一 | Q3 拍板（2026-08-09）：默认单项目 + 同世界观选择器显式跨项目；会话级不持久化（#175 承接持久化） | 无差别全局搜索（无场景）；持久化项目组实体表（超范围 + 与 #175 重复） |
| D9 | **v1.1：semantic 复用 RAG 不新建** | mode=semantic → VectorStoreProtocol.retrieve | Q1 拍板 AI 检索增强；零新增依赖（F14 已有）；覆盖缺口显式声明（§5.8） | 独立向量检索实现（重复基建）；新增 embedding 模型（体积 + 供应链成本） |
| D10 | **v1.2：CLI 恒经 HTTP + rebuild 端点** | `inkflow search` 走 ensure_kernel + InkFlowHTTPClient；`--rebuild` 经新增 `POST /api/v1/search/rebuild` | 方案 A 拍板（2026-08-09）：ADR-030/F38「CLI 恒经 HTTP」全局架构（Issue #169 已合入）；v1.1 直连先例（F23/F21）已被 F38 推翻；rebuild 是写操作 → 显式 POST 端点（F12 check 只读 GET 先例不适用） | v1.1 字面「直接消费 service」（违背 ADR-030 + F38 豁免判据——search 有对应端点不满足豁免）；查询走 HTTP + rebuild 直连（同命令双路径，最别扭） |

---

## 13. 验收标准

> 「自动化载体」列：单元/集成/API/CLI/手动。

| # | 验收标准 | 自动化载体 | 验证命令（backend 目录，uv run） |
|---|----------|------------|-------------------------------|
| M1 | 中文关键词跨类型搜索：`search 龙 -p <项目>` 命中章节正文 + 角色 + 世界观 | 集成+CLI | `pytest tests/unit/test_search_index.py tests/unit/test_search_service.py` |
| M2 | 类型筛选：`-t chapter` 只返回章节命中 | CLI+API | `pytest ../tests/cli/test_cli_search.py ../tests/api/test_search_api.py` |
| M3 | 高亮：snippet 含 `<mark>` 标记且位置正确 | 集成 | `pytest tests/unit/test_search_index.py -k snippet` |
| M4 | API `GET /api/v1/search` 200 命中/空结果/404/422 全矩阵（含双参数缺省 422）+ POST rebuild（200/404） | API | `pytest ../tests/api/test_search_api.py` |
| M5 | 索引脏检测：内容变更后首查重建并命中新内容；无变更不重建 | 单元 | `pytest tests/unit/test_search_service.py -k stale` |
| M6 | 软删内容不命中 | 单元 | `pytest tests/unit/test_search_service.py -k deleted` |
| M7 | FTS5 保留字/特殊字符查询安全（`AND`、引号、XML 标签） | 单元+集成 | `pytest tests/unit/test_search_tokenizer.py tests/unit/test_search_index.py -k escape` |
| M8 | 确定性：同数据同查询两次结果一致 | 集成 | `pytest tests/unit/test_search_index.py -k deterministic` |
| M9 | 空查询 422 / 纯标点查询空结果 | API+单元 | `pytest ../tests/api/test_search_api.py tests/unit/test_search_tokenizer.py` |
| M10 | **v1.1：多项目检索** `project_ids=1,2` 两项目命中 + 404 单项目失败 | 集成+API | `pytest tests/unit/test_search_index.py -k multi tests/unit/test_search_service.py -k multi` |
| M11 | **v1.1：AI 自动维护** `ai_maintenance=true` + 变更 → 增量同步；增量失败回退懒重建 | 单元 | `pytest tests/unit/test_search_service.py -k incremental` |
| M12 | **v1.1：semantic 模式** FakeEmbeddings 命中映射 + outline 恒空（覆盖缺口）+ embedding 异常 200 空 | 单元 | `pytest tests/unit/test_search_semantic.py` |
| M13 | **v1.1/v1.2：手动 rebuild** `inkflow search --rebuild` 强制全量重建（经 POST rebuild 端点） | CLI+单元 | `pytest ../tests/cli/test_cli_search.py tests/unit/test_search_service.py -k rebuild` |
| M14 | 全量门禁：lint/unit/integration/api/cli 绿 + 覆盖率达标 | CI | `uv run ruff check src/ tests/unit/ ../tests/` + 全量 pytest |
| M15 | 手工闭环：CLI 搜索真实项目中文词命中 + GUI 未来接线冒烟 | 手动 | 发布前冒烟 |

> Issue #54 验收标准映射：跨内容类型搜索=M1 · 类型筛选=M2 · 搜索高亮=M3；v1.1 新增（用户拍板 2026-08-09）：AI 检索=M12 · 同世界观跨项目=M10 · AI 自动维护=M11。

---

## 待澄清问题（评审时确认）

| # | 问题 | 选项 | 建议 |
|---|------|------|------|
| Q1 | 搜索方案 | A. FTS5 + jieba 分词（零新依赖，词法精确）+ 可接入既有 RAG 做 AI 语义检索<br>B. LIKE 全表扫描<br>C. 纯向量检索（复用 chromadb + BGE） | ✅ 已确认（用户拍板 2026-08-09：A + AI 检索增强）——正文已按「keyword 默认 + semantic 增强（复用 F14 RAG）」修订（§1/§5.8/§12 D1/D9），semantic 覆盖缺口显式声明 |
| Q2 | 索引维护策略 | A. 写时同步（6 模块 MODIFY）<br>B. 全量重建 + 脏检测<br>C. 增量游标 | ✅ 已确认（用户拍板 2026-08-09：自定义综合方案）——默认用户自维护（懒重建 + 手动 rebuild）+ 设置项 AI 自动维护（写完一章 REVIEW/FINAL 触发增量）+ 手动全量重建；**章节审计拆出 #208/F34 单独立项**，审计确认作为增强触发点非阻塞（§5.3/§10） |
| Q3 | 搜索范围 | A. 项目内（project_id 必填）<br>B. 跨项目（无差别全局）<br>C. A + 预留 | ✅ 已确认（用户拍板 2026-08-09：默认单项目 + 同世界观选择器）——`project_ids` 数组显式跨项目（会话级不持久化，持久化归 #175）；正文已修订（§2.2/§3.1/§5.7/§12 D8） |
