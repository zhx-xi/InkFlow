# F20: MCP Server（mcp_service）— 功能规格
> **端**: backend

**Spec 版本**: 1.1
**日期**: 2026-08-16
**依据**: PRD §6.4 F20（≥15 工具）· ADR-023 v2（薄客户端经 HTTP，2026-08-07 D3=A 拍板）· ADR-030（本地内核服务化 ④）· Constitution P1-P6
**所属阶段**: 0.9.0（估算 5-8 人天；1.0.0 → 0.9.0 提前拍板 2026-08-12——1.0.0 定位改为「正式可用」不应再含大功能，MCP 提前实现、提前在实际使用中验证）
**关联 Issues**: [#49](https://github.com/zhx-xi/InkFlow/issues/49)（本模块）
**依赖**: ✅ F30（ensure_kernel + kernel.json 冷启动）· ✅ F38（`infrastructure/http/` 传输层 + 零 cli 依赖）· ✅ F26（ToolSpec 契约 + 工具注册表机制）· ✅ F7（JSON 信封/错误码契约）
**参考 ADR**: [ADR-023](../../adr/ADR-023.md)（MCP 设计 v2）· [ADR-030](../../adr/ADR-030.md)（内核服务化 ④）· [ADR-022](../../adr/ADR-022.md)（skills 双轨）· [ADR-021](../../adr/ADR-021.md)（内核并发契约）· [ADR-019](../../adr/ADR-019.md)（版本里程碑）
**状态**: ✅ 已实现（PR #400，2026-08-16）

> **Spec 变更**（v1.0 → v1.1，2026-08-16）：待澄清 Q1-Q3 全部拍板（用户拍板 A/A/A）。① Q1 工具粒度 = **聚合 `manage_*`（action 枚举）15 工具**（细粒度 50+ 否决）；② Q2「与 F26 同源」落地 = **契约同源**（复用 ToolSpec + 信封语义，新建 `mcp/tools/` HTTP 工具工厂，非复用 F26 `build_reader_tools`）；③ Q3 write 流式 = **同步返回拼接结果**（走非流式端点 `/writing/generate|continue|revise`，不走 SSE 透传）。联动修订：§2.2/§2.3/§10/§12/待澄清节。

> **模块类型声明**: 本模块为 **第 19 变体「MCP 表现层（薄客户端经 HTTP）型」**——InkFlow 第三表现层（与 `api/` REST、`cli/` 并列），对外部 agent 提供 MCP 行业标准 stdio 接口。编号依据 AGENTS.md 模块类型谱系（**F38=第 18 变体为最新无冲突基线**，接续编号）；⚠️ 历史变体编号存在漂移（f24/f27 均自述第 11、f30/f29 均自述第 13、f21/f36 均自述第 15），本 spec 以 F38=18 为基线声明第 19，冲突以 ADR-019 v5+ 为准。

---

## 1. 概述

F20 交付 InkFlow 的 **MCP Server**（Model Context Protocol）：外部 AI agent（Hermes / Claude Code / Cursor 等）通过 MCP 标准协议，结构化调用 InkFlow 的创作能力——建项目/章节/角色/世界观等设定实体、写作、审计、提取、导出、搜索、会话管理，共 **≥15 个工具**。

### 1.1 模块类型定位（第 19 变体「MCP 表现层（薄客户端经 HTTP）型」）

```
外部 agent（Hermes / Claude Code / ...）
        │  MCP 协议（JSON-RPC 2.0 / stdio 传输）
        ▼
  MCP Server 进程（agent 每次拉起，stdio 会话）
        │
        ├─ 启动时 ensure_kernel()（F30：读 kernel.json → 无/失效则互斥拉起 inkflow serve → 复用）
        │
        ├─ 工具经 InkFlowHTTPClient（F38 infrastructure/http/）访问本地内核 HTTP
        │     └─ http://127.0.0.1:{port}/api/v1/...（X-InkFlow-Token: {token}）
        │
        └─ tools/list 动态装配工具面（渐进式工具发现）
```

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ 无（纯表现层，复用内核全部数据面） |
| 新 REST 端点 | ❌ 无（消费内核既有 92 端点，F38 §3.1 消费清单同源） |
| 新 CLI 命令 | ❌ 无（MCP 是独立表现层，不经 CLI 命令树） |
| 核心机制 | ✅ MCP stdio server + 薄客户端经 HTTP（ensure_kernel + InkFlowHTTPClient）+ 工具面装配 |
| 跨模块 MODIFY | ✅ 可能 MODIFY `pyproject.toml`（新增 `mcp` 依赖 + `inkflow-mcp` entry point，§8）；F26/F38/F30 **零改动**（复用契约） |
| 错误面 | MCP 协议 `isError` + 错误码（对齐 F7 错误码 + F38 `map_http_error`） |

### 1.2 与样板差异

- 非 F9 实体 CRUD（无新增表/端点/命令）、非 F38 传输层改造（F38 改 CLI 调用路径，本模块新建表现层）、非 F26 工具定义（F26 为 deepagents 内部工具，本模块为 MCP 外部工具）。
- 本质是「**表现层适配器 + 工具面装配**」：把既有 REST 端点面（F38 §3.1 消费清单）按 PRD §6.4 F20 的 15 个工具语义重新装配为 MCP 工具，工具执行经 HTTP 转发到内核——**零领域逻辑、零新数据面**。

### 1.3 边界声明

- **不含**：云端 Streamable HTTP 传输（ADR-023 后移 P2 评估）；skills 包 mcp-setup.md 之外的技能内容（mcp-setup.md 由 #70 联动，见 §11）；GUI 集成；`inkflow skills install` 命令（F19-skills 已交付，本模块不扩展）。
- **复用不重定义**：ToolSpec 契约（F26）、HTTP 客户端层（F38）、冷启动协议（F30）、JSON 信封/错误码（F7）——全部引用既有实现，不复制签名、不重新定义协议。

---

## 2. 数据模型

**无新业务实体、无新 ORM 表**。新增数据面 = MCP 工具层的参数模型（Pydantic BaseModel，生成工具 input_schema）与工具返回信封。

### 2.1 复用 ToolSpec 契约（F26，零改动）

```python
# domain/models/agent_tools.py（F26 已交付，本模块引用不重定义）
@dataclass
class ToolSpec:
    name: str            # 工具名（snake_case，如 manage_character）
    description: str     # 工具用途描述（LLM 决定是否调用时阅读）
    input_schema: dict   # JSON Schema（Pydantic model_json_schema() 产物）
```

F20 的 MCP 工具沿用同一 `ToolSpec` 结构（`name`/`description`/`input_schema`），由 MCP 层将 `input_schema`（dict）映射为 MCP 协议的 `inputSchema`（JSON Schema）。**不复制 ToolSpec 定义，直接 import**（ADR-015 领域层零框架依赖不变）。

### 2.2 MCP 工具参数模型（`mcp/tools/` 新增）

15 个工具的参数模型采用 **「action 枚举 + 领域字段」聚合形态**（Q1 已拍板：选项 A，2026-08-16）：每个 `manage_*` 工具一个参数模型，`action: str`（枚举）路由子操作，领域字段按需可选（对某 action 无效的字段 LLM 不传）。

| 工具名 | action 枚举 | 关键参数（除 action 外） | 对应内核端点（复用，零新增） |
|--------|-------------|--------------------------|------------------------------|
| `manage_project` | create / list / get / update / delete / restore | name, genre, language, target_words, search, id, force, permanent | POST/GET `/projects` · GET/PATCH/DELETE `/projects/{id}` · POST `/projects/{id}/restore` |
| `manage_chapter` | create / list / get / update / delete / move | project_id, volume_id, title, content, status, id, to_volume | POST `/projects/{pid}/volumes` · POST/GET `/projects/{pid}/chapters` · GET/PATCH/DELETE `/chapters/{cid}` · POST `/chapters/{cid}/move` |
| `manage_character` | create / list / get / update / delete / restore | project_id, name, search, group_id, id | POST/GET `/projects/{pid}/characters` · GET/PATCH/DELETE `/characters/{id}` · POST `/characters/{id}/restore` · character-groups 端点 |
| `manage_relation` | create / list / get / update / delete | project_id, source_id, target_id, relation_type, id | relations 三端点（`/characters/{id}/relations` 等，F9） |
| `manage_timeline` | create / list / get / update / delete / check | project_id, event fields, id | POST/GET `/projects/{pid}/timeline/events` · GET `/projects/{pid}/timeline` · GET `/projects/{pid}/timeline/check` · GET/PATCH/DELETE `/timeline/events/{id}` |
| `manage_world` | create / list / get / update / delete / restore | project_id, category, name, id | POST/GET `/projects/{pid}/world-settings` · GET `/projects/{pid}/world-settings/categories` · GET/PATCH/DELETE `/world-settings/{id}` · POST `/world-settings/{id}/restore` |
| `manage_outline` | create / list / get / update / delete / generate | project_id, chapter_id, level, title, id | POST/GET `/projects/{pid}/outlines` · GET/PATCH/DELETE `/outlines/{id}` · plot-points / story-arcs 端点 · POST `/outlines/generate` |
| `manage_foreshadowing` | create / list / get / update / delete / resolve / reopen | project_id, content, status, id | POST/GET `/projects/{pid}/foreshadowings` · GET/PATCH/DELETE `/foreshadowings/{id}` · POST `/foreshadowings/{id}/resolve/reopen` |
| `write` | generate / continue / revise | project_id, chapter_id, instruction, target_words | POST `/writing/generate\|continue\|revise`（非流式，Q3 已拍板 A：同步返回拼接结果，不走 SSE 透传） |
| `audit` | project / chapter | project_id, chapter_id, include_static | GET `/projects/{pid}/audit`（F15）· POST `/projects/{pid}/chapter-audit`（F34） |
| `extract` | extract / reindex / retrieve | project_id, content, query | POST `/extract` · POST `/projects/{pid}/vector/reindex` · POST `/projects/{pid}/vector/retrieve` |
| `export` | export | project_id, format, output_path | POST `/export`（F21） |
| `search` | search | project_id, query, content_type | GET `/projects/{pid}/search`（F22） |
| `manage_session` | create / list / get / pause / resume / complete / fail | project_id, session_type, id, logs | POST/GET `/sessions` · GET/PATCH `/sessions/{id}` · POST `/sessions/{id}/pause\|resume\|complete\|fail` · POST/GET `/sessions/{id}/logs` |
| `tool_search` | list | （无；返回当前装配的工具面清单） | 本地装配结果（不经 HTTP，同 `inkflow agent tools list` 豁免先例） |

> **映射原则（同源引用）**：上表端点全部来自 F38 §3.1 消费清单（内核既有端点），**本模块零新增端点**。工具参数字段与对应 API DTO 字段一一对应（`--name`→`name`、`--target-words`→`target_words`），枚举转换在 MCP 工具层完成（对齐 F38 §3.2「CLI 参数 → 请求体映射」同源语义）。

### 2.3 决策论证表

| 决策 | 方案 | 理由 |
|------|------|------|
| ToolSpec 承载 | 复用 F26 `domain/models/agent_tools.py`（import，不复制） | 单一真相；工具契约（name/description/input_schema）与 agent 内部工具同源，避免双份漂移（ADR-023「与 CLI/F26 同源」） |
| 工具参数模型归属 | `mcp/tools/` 表现层内（不进 domain） | MCP 工具参数是表现层 DTO，非领域模型；领域层零 MCP 感知（ADR-015） |
| 工具粒度 | 聚合 `manage_*`（action 枚举）15 工具（Q1 已拍板 A） | PRD §6.4 F20 列 15 个聚合工具名；LLM 工具选择友好（15 vs 50+）；细粒度备选见 §12 |
| 工具返回形态 | MCP 协议 result（对齐 F26 `_ok`/`_fail` 信封：`{"ok": True, "data": ...}` / `{"ok": False, "error": ...}`） | agent 消费一致；成功/失败结构对称；MCP `isError` 标记失败（§3.2） |
| 工具执行路径 | `InkFlowHTTPClient`（F38）→ 内核 HTTP | ADR-023 v2 薄客户端：冷启动快、单数据源、复用冷启动协议（不直连 domain） |

## 3. API 契约（MCP 协议层）

本模块的「API 契约」= MCP 协议契约（JSON-RPC 2.0 over stdio），**非 REST 端点**（REST 端点是内核契约，本模块为消费方，端点清单见 §2.2 映射表）。

### 3.1 MCP 协议方法与 stdio 传输

官方 Python SDK（`mcp` 包，ADR-023 决策），实现 server 侧核心方法：

| MCP 方法 | 语义 | 本模块行为 |
|----------|------|-----------|
| `initialize` | 能力协商 | 返回 server 能力（tools + 协议版本）；对齐 MCP 规范版本 |
| `tools/list` | 工具发现 | 从工具注册表动态装配返回当前工具面（§4.2 渐进发现） |
| `tools/call` | 工具调用 | 校验参数（Pydantic schema）→ ensure_kernel（F30）→ InkFlowHTTPClient 转发（F38）→ 返回 result |
| `ping` | 保活 | 立即响应 |

- **stdio 传输**：`StdioServerTransport`——从 stdin 读 JSON-RPC、写 stdout。**stdout 只承载 MCP 协议帧**，任何日志/调试输出必须走 stderr（MCP 硬约束，污染 stdout = 协议帧损坏）。
- **进程生命周期**：MCP server 进程由 agent 拉起，stdio 会话结束即退出（**不常驻**）。常驻的是**内核**（ensure_kernel 拉起的 `inkflow serve`，F30 D2=A）。MCP server 自身是轻量短命进程（薄客户端无重组件 import），退出不清理内核。
- **启动形态**：新增 `inkflow-mcp` console_script（`pyproject.toml` entry point，§8），打包产物含 `inkflow-mcp.exe`（PyInstaller 随 CLI 产物，§13 发布验证四件套）。

### 3.2 工具返回信封

`tools/call` 的 `result` 结构（对齐 F26 `_ok`/`_fail` 信封，agent 消费一致）：

```json
// 成功（isError: false）
{"ok": true, "data": <序列化结果>}

// 失败（isError: true）
{"ok": false, "error": "<异常消息>"}
```

- `data` 为工具执行结果（Pydantic `model_dump(mode="json")` / 列表逐元素序列化，复用 F26 `_serialize_data` 语义）；`error` 为错误文本。
- `isError=true` 时 MCP 协议层标记失败（agent 据此感知工具调用失败，与 deepagents ToolMessage 回填语义同族）。
- 序列化 `ensure_ascii=False`（中文不转义）。

### 3.3 错误映射（MCP isError + F7 错误码 + F38 map_http_error 复用）

| 场景 | 行为 | 错误码（对齐 F7） |
|------|------|------------------|
| 内核未运行 | ensure_kernel 自动拉起（首次 ~4.7s，F30） | — |
| 内核拉起失败（超时/秒退） | KernelStartupError → `{"ok": false, "error": "内核启动失败: ..."}` + isError | `KERNEL_ERROR`（F38 新增码） |
| HTTP 非 2xx | HttpApiError → `map_http_error`（F38 §5.3 全表）→ result error | NOT_FOUND / VALIDATION_ERROR / CONFIG_ERROR / LLM_ERROR / INTERNAL_ERROR |
| 连接失败/超时 | F38 §5.1 单次重试（重新 ensure_kernel）→ 仍失败 → error | KERNEL_ERROR |
| 参数 schema 校验失败 | MCP SDK 层 Pydantic 校验 → isError | —（协议层，无业务码） |
| 工具内部异常 | 工具函数捕获 → `{"ok": false, "error": ...}`（F26 错误文本回填语义） | — |

> **不重定义错误码表**：MCP 工具错误码沿用 F7 表 + F38 `map_http_error` 复用。MCP 层 `error` 为纯文本（语义已含错误信息），结构化错误码字段本期不引入（云端 Streamable HTTP 需要时再扩展，登记 §10）。

> **空消息兜底（#634）**：detail 为空时 `map_http_error` 返回兜底诊断文案（F38 §5.3）；未知异常 `str(exc)` 为空时返回异常类型 + 「内核调用失败」，保证 `error` 永不为空。

---

## 4. 工具面清单与渐进式发现

### 4.1 工具面完整清单（≥15，PRD §6.4 F20）

| # | 工具名 | 一句话描述（LLM 工具选择依据） |
|---|--------|-------------------------------|
| 1 | `manage_project` | 项目管理：创建/列出/查看/更新/删除/恢复项目 |
| 2 | `manage_chapter` | 章节与卷管理：创建/列出/查看/更新/删除/移动章节 |
| 3 | `manage_character` | 角色管理：创建/列出/查看/更新/删除/恢复角色档案 |
| 4 | `manage_relation` | 角色关系管理：创建/列出/查看/更新/删除角色间关系 |
| 5 | `manage_timeline` | 时间线管理：创建/列出/查看/更新/删除时间线事件 + 一致性检查 |
| 6 | `manage_world` | 世界观管理：创建/列出/查看/更新/删除/恢复世界观设定 |
| 7 | `manage_outline` | 大纲管理：创建/列出/查看/更新/删除大纲 + 情节点/故事弧 + AI 生成 |
| 8 | `manage_foreshadowing` | 伏笔管理：创建/列出/查看/更新/删除伏笔 + 回收/重开 |
| 9 | `write` | 写作：续写下一章 / 续写指定章 / 按指令修订 |
| 10 | `audit` | 审计：项目级四维审计 / 单章一致性审计 |
| 11 | `extract` | 提取：从文本提取设定实体 / 向量重索引 / 语义检索 |
| 12 | `export` | 导出：项目导出为 EPUB/Markdown/TXT/DOCX |
| 13 | `search` | 搜索：跨内容类型全文搜索（关键词 + 语义） |
| 14 | `manage_session` | 会话管理：创建/列出/查看/暂停/恢复/完成/失败 agent 会话 |
| 15 | `tool_search` | 工具发现：列出当前 MCP 工具面（渐进式发现入口） |

> **≥15 工具**：上表为 PRD §6.4 F20 明确定义的工具面。实施时工具数**不得少于 15**；可在既有语义内**拆分**某 `manage_*` 为子工具（如 relation 并入 character 则须以拆分补偿），但不得**合并**减少。拆分须保持工具名与 CLI 命令语义对应（ADR-023「工具名与 CLI 命令语义一一对应」）。

### 4.2 渐进式工具发现（tools/list 动态装配）

- `tools/list` 返回**当前实际装配**的工具面（非硬编码常量）——装配逻辑读取 `mcp/tools/` 静态注册表（§8）动态生成，与 F26 `TOOL_REGISTRY` 同源机制。
- **装配时机**：server 启动时装配一次（15 工具全量）；`tools/list` 从装配结果返回。
- **动态性边界**：本期工具面**静态 15 工具**，不做按内核能力的运行时裁剪（如「某 provider 未配置 LLM → write 工具不可用」的探测裁剪）——**登记 §10**（0.9.0 静态面；云端 Streamable HTTP 时评估动态装配）。
- `tool_search` 工具 = 运行时「工具面自描述」入口，供 agent 在不依赖宿主 `tools/list` 的场景（如经 skills 文档描述）查询可用工具及各自 action 枚举——**与 `tools/list` 同源**（同一注册表），语义互补（协议级发现 vs 工具级查询）。

### 4.3 与 CLI 语义一一对应（ADR-023 契约）

- MCP 工具名与 CLI 命令语义**一一对应**：`manage_project` ↔ `inkflow project <action>`、`manage_character` ↔ `inkflow character <action>`、`write` ↔ `inkflow write next/continue/revise` 等。
- **不共享命令树代码**（ADR-023）：MCP 工具实现直接经 `InkFlowHTTPClient` 调端点，不 import `cli/commands/`——F38 §6.4「零 cli 依赖」约束延续到 MCP 层（§6.1）。
- 变更评审时对照 CLI 契约与端点清单（§11 维护项）。

## 5. 关键差异节：薄客户端经 HTTP + 冷启动 + 与 F26 同源

### 5.1 薄客户端经 HTTP（ADR-023 v2 D3=A 核心）

```
工具调用链路（tools/call → manage_character）:

agent → MCP server（stdio）
         │ 1. ensure_kernel()（F30）
         │    ├─ 读 kernel.json → pid 存活 + /health 200 → 复用 KernelHandle（~19ms）
         │    └─ 无/失效 → CreateMutexW 互斥 → spawn inkflow serve → 写 kernel.json（~4.7s 首次）
         │ 2. InkFlowHTTPClient(handle)（F38）
         │    └─ GET http://127.0.0.1:{port}/api/v1/projects/{pid}/characters
         │       （X-InkFlow-Token: {token}）
         │ 3. 序列化结果 → result {"ok": true, "data": [...]}
         ▼
      内核（inkflow serve，常驻，持有 chromadb/BGE/LLM client 内存态）
```

- **为什么不直连 domain**（ADR-023 v2 否决原案）：MCP stdio 进程每次由 agent 拉起 = 独立进程，若直连 domain 则每次冷加载 chromadb/BGE（秒级）+ 与内核双数据源（SQLite WAL 竞争）。薄客户端 = 启动快（import 面仅 `mcp` + `httpx` + `infrastructure.http/kernel`，无重组件）、单数据源、复用 F30 冷启动协议。
- **import 面纪律**（F38 §5.5 同族）：`mcp/` 层顶层 import 不得拖入 `domain/services` / `infrastructure/llm` / `infrastructure/database`——重组件全部在内核内存态，MCP server 自身只 import 协议/传输/工具装配（验收 §13 M1 用 `sys.modules` 断言）。

### 5.2 冷启动链路（ensure_kernel 复用，F30 零改动）

| 时序点 | 行为 | 归属 |
|--------|------|------|
| server 启动 | `ensure_kernel()`（惰性，首次 tools/call 前；亦可启动时调用） | F30 |
| 内核未运行 | 互斥拉起 → 等 INKFLOW_READY / 端口文件 → 写 kernel.json | F30 |
| 内核已运行 | pid 存活 + /health 200 → 复用（reused=True） | F30 |
| 复用失败（/health 非 200） | stale 清理 → 重新拉起 | F30 |
| 版本 major 不匹配 | 拒绝复用 → 清理 → 拉起匹配版本 | F30 |

> **MCP 层零冷启动逻辑**：ensure_kernel 三态判定/互斥/重试全部由 F30 承担，MCP server 只调用 `ensure_kernel()` 拿 `KernelHandle`——冷启动协议**复用不重实现**（ADR-030 ④）。

### 5.3 与 F26 工具的关系（同源引用，非实现复用）

| 维度 | F26 agent 内部工具 | F20 MCP 外部工具 |
|------|--------------------|------------------|
| 消费方 | deepagents 写作循环（F27/F42 管线） | 外部 agent（Hermes/Claude Code 等） |
| 传输 | 进程内直连 domain service（`build_reader_tools(deps)` 注入 service 实例） | 薄客户端经 HTTP（`InkFlowHTTPClient` → 内核） |
| 工具面 | 5 只读 + save_draft（精细，写作闭环专用） | 15 聚合（全能力 CRUD + 横切） |
| 共享 | **ToolSpec 契约**（`domain/models/agent_tools.py`）+ **信封语义**（`_ok`/`_fail`）+ **底层 service 语义**（同一 domain service，不同路径） | 同左 |

- **同源 = 契约同源，非实现同源**：F20 复用 F26 的 `ToolSpec` 数据结构与工具信封约定，但**不复用** `build_reader_tools` 的 func 实现（那些闭包直连 service）。F20 新建 HTTP 工具工厂（`mcp/tools/`，func = `InkFlowHTTPClient` 调端点）。
- **不重定义协议**：工具名/描述/参数 schema 的**语义**与 CLI 命令 + REST 端点对齐（§2.2/§4.3），但物理定义（Pydantic 参数模型 + 端点映射）在 `mcp/` 表现层新建——因为粒度不同（聚合 vs F26 精细）、路径不同（HTTP vs 直连）。

---

## 6. 组织规则

### 6.1 依赖方向

```text
✅ mcp/ → infrastructure/http/（InkFlowHTTPClient，F38）
✅ mcp/ → infrastructure/kernel/（ensure_kernel，F30）
✅ mcp/ → domain/models/agent_tools.py（ToolSpec，F26）
❌ mcp/ → cli/ 任何模块（F38 §6.4 零 cli 依赖约束延续）
❌ mcp/ → domain/services/、infrastructure/llm/、infrastructure/database/（import 面收敛，§5.1）
❌ infrastructure/http/、infrastructure/kernel/ → mcp/（零反向依赖）
```

### 6.2 stdio 生命周期与日志

- MCP server 进程短命（agent 拉起 → stdio 会话结束退出），**不持有常驻资源**（无连接池跨会话复用需求——每次 tools/call 内部 `async with InkFlowHTTPClient(handle)`，F38 §5.2 语义）。
- **stdout 协议纪律**：MCP 协议帧独占 stdout；`loguru`（ADR-016）日志输出重定向到 stderr（或 `%TEMP%\inkflow-mcp.log`），严禁日志污染 stdout。
- 内核侧日志照旧（`%TEMP%\inkflow-kernel.log`，F30 §6.2）。

### 6.3 token 传递与安全

- token 仅存在于 `KernelHandle`（ensure_kernel 返回）→ `InkFlowHTTPClient` 请求头，与 F38 §6.2 同源。
- MCP 层禁止直接读 `kernel.json` 拿 token（绕过 ensure_kernel = 绕过三态判定）。
- token 不落 MCP 日志、不进入 tools/list 或 tool_search 返回（工具面自描述不含运行时凭据）。

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 | 错误码 |
|---|------|------|--------|
| 1 | 内核未运行（kernel.json 不存在） | ensure_kernel 互斥拉起 → 正常调用（首次 ~4.7s） | — |
| 2 | 内核崩溃残留（pid 死） | F30 stale 判定 → 清理 → 重新拉起 | — |
| 3 | 冷启动超时 / 内核秒退 | KernelStartupError → result error | KERNEL_ERROR |
| 4 | 两个 agent 同时冷调用（双 MCP server） | F30 CreateMutexW 183 → 轮询 → 复用（F30 §5.3 已覆盖） | — |
| 5 | 请求时内核刚退出（连接拒绝） | F38 §5.1 单次重试 → 仍失败 → error | KERNEL_ERROR |
| 6 | 请求超时（30s） | httpx.TimeoutException → INTERNAL_ERROR | INTERNAL_ERROR |
| 7 | HTTP 404（实体不存在） | map_http_error → NOT_FOUND | NOT_FOUND |
| 8 | HTTP 422（参数校验） | map_http_error → VALIDATION_ERROR | VALIDATION_ERROR |
| 9 | HTTP 401（token 失效） | map_http_error → CONFIG_ERROR（提示重启内核） | CONFIG_ERROR |
| 10 | HTTP 500 + LLM_ERROR 头（write） | map_http_error → LLM_ERROR | LLM_ERROR |
| 11 | HTTP 500 无头 | map_http_error → INTERNAL_ERROR | INTERNAL_ERROR |
| 12 | 工具参数 action 非法值 | Pydantic 枚举校验 → MCP SDK 层 isError | —（协议层） |
| 13 | 工具函数抛未预期异常 | 工具捕获 → `{"ok": false, "error": ...}`（F26 错误文本回填） | — |
| 14 | tools/list 时内核未运行 | tools/list **不触发 ensure_kernel**（纯装配，无 HTTP）——与 `agent tools list` 豁免先例同族（工具面是静态资源，非内核运行时状态） | — |
| 15 | tool_search 调用 | 本地装配结果返回（不经 HTTP，同 #14） | — |

## 8. 文件结构（对照真实源码树）

遵循 ADR-007v2 包结构；F26/F38/F30 既有文件**零改动**（复用契约），本模块新增 `mcp/` 表现层：

```text
backend/src/inkflow/
├── mcp/                              ← CREATE: MCP 表现层（与 api/ cli/ 同级，ARCHITECTURE.md §2 已预留）
│   ├── __init__.py                   ← CREATE: 导出 run / build_mcp_server
│   ├── server.py                     ← CREATE: MCP server 装配（StdioServerTransport + 工具注册 + tools/list·tools/call handler）
│   ├── tools/
│   │   ├── __init__.py               ← CREATE: MCP_TOOL_REGISTRY（15 工具静态注册表）+ build_mcp_tools 工厂
│   │   ├── schemas.py                ← CREATE: 15 工具 Pydantic 参数模型（§2.2 action 枚举 + 领域字段）
│   │   ├── manage_tools.py           ← CREATE: 8 个 manage_* 工具工厂（action 路由 → InkFlowHTTPClient 端点）
│   │   ├── operation_tools.py        ← CREATE: write/audit/extract/export/search 工具工厂
│   │   └── session_tools.py          ← CREATE: manage_session + tool_search 工具工厂
│   └── __main__.py                   ← CREATE: python -m inkflow.mcp 入口（stdio 启动）
├── domain/models/agent_tools.py      ← 复用（F26，零改动：ToolSpec）
├── infrastructure/http/              ← 复用（F38，零改动：InkFlowHTTPClient/HttpApiError/map_http_error）
└── infrastructure/kernel/            ← 复用（F30，零改动：ensure_kernel/KernelHandle）

backend/pyproject.toml                ← MODIFY: 新增 `mcp` 依赖 + [project.scripts] inkflow-mcp = "inkflow.mcp.server:main"

backend/tests/unit/                   ← 扁平无子目录（源码核实：unit 目录扁平）
├── test_mcp_schemas.py               ← CREATE: 15 参数模型 schema 契约（action 枚举/字段/JSON Schema）
├── test_mcp_tools.py                 ← CREATE: 工具工厂端点映射（mock InkFlowHTTPClient，断言 method/path/body/序列化）
└── test_mcp_server.py                ← CREATE: server 装配 + tools/list 15 项 + tool_search + 错误映射

tests/cli/
└── test_cli_mcp.py                   ← CREATE: inkflow-mcp stdio 协议（真实内核轨，§9.2；显式加 ci.yml）
```

> **测试落点**：`backend/tests/unit/` 三个文件由 `unit-test-backend` job 自动覆盖（扁平目录）；`tests/cli/test_cli_mcp.py` 必须显式加入 ci.yml `integration-cli-backend` job 文件列表（Issue #59/#61 教训，Windows pytest 不展开 glob）。

---

## 9. 测试策略

### 测试层次

```text
单元测试（unit-test-backend 自动覆盖，mock 轨）:
  test_mcp_schemas.py    — 15 参数模型 schema（action 枚举合法值/可选字段/JSON Schema 生成）  ~30 cases
  test_mcp_tools.py      — 工具工厂端点映射（mock InkFlowHTTPClient：断言 method/path/body 透传、
                           响应序列化、错误映射、15 工具 func 各 1 正例 + 1 异常）            ~40 cases
  test_mcp_server.py     — server 装配（tools/list 返回 15 项 + name/description/inputSchema 非空）、
                           tool_search、错误映射（isError）、import 面收敛断言（sys.modules）  ~15 cases
CLI/集成测试（显式加 ci.yml integration-cli-backend，真实内核轨）:
  test_cli_mcp.py        — inkflow-mcp 启动 + stdio 协议帧（initialize → tools/list → tools/call
                          真实内核端到端）+ 冷启动链路（无内核 → 自动拉起 → 调用成功）         ~5 cases
```

### 关键测试场景

1. **参数模型**：15 工具各 schema 生成（action 枚举、字段名与端点 DTO 对齐）；非法 action → 校验失败
2. **端点映射**：mock `InkFlowHTTPClient`，断言 `manage_project create` → `POST /projects` + body 字段；`manage_character list` → `GET /projects/{pid}/characters` + params；错误响应 → 错误码映射（复用 `map_http_error`）
3. **工具面装配**：`tools/list` 返回**恰好 15 项**，name/description/inputSchema 非空；`tool_search` 返回同源工具面
4. **冷启动**：mock `ensure_kernel` 断言被调用且结果注入 client；真实内核轨验证「无内核 → 自动拉起」
5. **import 面收敛**：`import inkflow.mcp.server` 后 `sys.modules` 无 `inkflow.domain.services` / `inkflow.infrastructure.llm` / `inkflow.infrastructure.database`（§5.1 纪律，F38 §13 M1 同族断言）
6. **stdio 协议**：协议帧独占 stdout（mock 断言日志走 stderr）

### 覆盖率目标

模块行覆盖 ≥ 80%、全仓 ≥ 60%；**当前全仓门禁 ADR-027：后端 98.5/95.0**——新增代码必须同步补测维持门槛（QA 阶段主 agent 全仓跑 `uv run ruff check src/ tests/unit/ ../tests/` + `pytest` 两条命令 + `check_coverage.py 98.5 95.0`）。

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| 云端 Streamable HTTP 传输 | ADR-023 后移 P2 评估（2.0.0 云端随评估）；本期仅 stdio 本地传输 |
| 按内核能力的运行时工具裁剪（动态装配） | §4.2 边界——本期静态 15 工具面；云端时评估 |
| MCP 层结构化错误码字段 | §3.3——`error` 纯文本已够；云端需要时扩展（F38 §3.3「全量扩展」同族评估） |
| skills 包 mcp-setup.md | #70 联动（ADR-022「MCP 发布后补 mcp-setup.md」），非本模块代码 |
| GUI 内嵌 MCP / MCP 客户端 | 本模块是 server 侧；客户端（外部 agent）由用户生态提供 |
| `inkflow skills install` 命令扩展 | F19-skills 已交付（0.8.0），本模块不扩展 |
| MCP server 常驻（daemon 化） | ADR-030 语义：MCP server 短命（agent 拉起），常驻的是内核 |
| 写工具流式回传（SSE 透传 MCP） | Q3 已拍板（选项 A，2026-08-16）——write 工具同步返回拼接结果（走非流式端点）；SSE 流式透传 MCP 留 P2 评估 |

## 11. 依赖关系

```text
F20 依赖（全部 ✅ 已实现）:
  F30（kernel）           — ensure_kernel / KernelHandle / kernel.json 冷启动协议（复用，零改动）
  F38（http）             — InkFlowHTTPClient / HttpApiError / map_http_error 传输层（复用，零改动）
  F26（agent_tools）      — ToolSpec 契约（domain/models/agent_tools.py，复用，零改动）
  F7（cli 约定）          — JSON 信封 / 退出码 / 错误码语义（引用不重定义）
  内核 REST 端点          — F1/F2/F9-F16/F21/F22/F24/F34 全部既有端点（§2.2 映射表，零新增）
  ADR-022（skills 双轨）  — mcp-setup.md 补充（#70 联动，非本模块代码）

F20 被依赖:
  #70（skills 包）        — MCP 发布后补 mcp-setup.md（ADR-022 演进预留）
  1.0.0 发布验收           — CLI + GUI + skills + MCP 四界面齐备（本模块是第四界面）
  外部 agent 生态          — Hermes / Claude Code / Cursor 经 MCP 调用 InkFlow（ADR-030 愿景落地）
```

**编号口径声明**：F20 为 PRD §6.4 原编号（0.9.0 提前实现不改号）。变体编号第 19（§1 声明依据 F38=18 基线），冲突以 ADR-019 v5+ 为准。

**维护项（ADR-023 长期约束）**：① 工具名与 CLI 命令语义一一对应——变更评审时对照 CLI 契约 + 端点清单；② 工具面 ≥15 与内部注册表同源——工具增删改须同步 `mcp/tools/` 注册表 + §4.1 清单 + 发布验证同源核对。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|-------------|
| 1 | MCP 接入方式 | **薄客户端经 HTTP**（ADR-023 v2 D3=A，2026-08-07 拍板） | 冷启动快（重组件在内核）、单数据源（无 SQLite WAL 竞争）、复用 F30 冷启动协议 | 直连 domain（每次 stdio 冷加载 chromadb/BGE + 双数据源）；包装 CLI 子进程（进程启动开销 + stdout 解析脆弱）；经 REST 转发（多一跳） |
| 2 | MCP SDK | 官方 `mcp` 包（ADR-023） | 跟随 MCP 标准演进；未来 Streamable HTTP 只换传输层 | 自研 JSON-RPC 解析（重复造轮子） |
| 3 | 传输 | stdio 本地传输（ADR-023 + p0-11 MCPTransport） | 本地 agent 场景标准；零端口/鉴权依赖 | Streamable HTTP（云端 P2 评估，后移） |
| 4 | 工具粒度 | 聚合 `manage_*`（action 枚举）15 工具（Q1 已拍板 A） | PRD §6.4 F20 列 15 聚合名；LLM 工具选择友好 | 细粒度每命令一工具（50+，工具选择负担重） |
| 5 | 与 F26 同源 | 契约同源（复用 ToolSpec + 信封语义 + 底层 service 语义），非实现同源（新建 HTTP 工具工厂）（Q2 已拍板 A） | 粒度不同（聚合 vs 精细）、路径不同（HTTP vs 直连） | 直接复用 build_reader_tools（func 直连 service，违背薄客户端） |
| 6 | 冷启动 | 复用 F30 `ensure_kernel()`（MCP 层零冷启动逻辑） | ADR-030 ④ 明确 MCP 薄客户端冷启动复用 | MCP 层重实现拉起逻辑（重复 + 漂移） |
| 7 | 工具返回 | MCP `result` 对齐 F26 `_ok`/`_fail` 信封 + `isError` 标记失败 | agent 消费一致；与 deepagents ToolMessage 语义同族 | 返回裸数据（失败无结构化标记，agent 难感知） |
| 8 | 错误映射 | 复用 F38 `map_http_error`（HTTP 状态 → F7 错误码） | 不重定义错误码表；与 CLI 行为一致 | MCP 层自建错误码表（双份漂移） |
| 9 | 工具面装配 | 静态 15 工具（tools/list 从注册表动态生成，不做能力裁剪） | 0.9.0 面稳定；能力裁剪留云端评估 | 运行时能力探测裁剪（复杂度 + 本期无消费场景） |
| 10 | write 流式语义 | 同步返回拼接结果（走非流式端点 `/writing/generate\|continue\|revise`）（Q3 已拍板 A） | MCP 工具模型天然同步；agent 一次拿到全文；避免 stdio 会话内流式帧与 JSON-RPC 响应交织 | SSE 流式透传（MCP 协议层无法逐 delta 推送，对 agent 无协议级收益） |

---

## 13. 验收标准

### 实现验收（M1-M5）

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 15 参数模型 schema 契约 | `pytest tests/unit/test_mcp_schemas.py -v` 全绿（action 枚举/字段/JSON Schema） |
| M2 | 工具工厂端点映射 | `pytest tests/unit/test_mcp_tools.py -v` 全绿（mock InkFlowHTTPClient：method/path/body 透传 + 错误映射） |
| M3 | server 装配 + tools/list 15 项 | `pytest tests/unit/test_mcp_server.py -v` 全绿（tools/list 恰好 15 项 + import 面收敛断言） |
| M4 | stdio 协议 + 冷启动链路 | `pytest tests/cli/test_cli_mcp.py -v` 全绿（真实内核轨，**已登记 ci.yml integration-cli-backend**）——initialize → tools/list → tools/call 端到端 + 无内核自动拉起 |
| M5 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；覆盖率达 ADR-027 门槛（98.5/95.0）；`uv run ruff check` + mypy 通过 |

### 发布验证四件套（M6，rc/发布阶段，0.9.0 起生效，#49 body 拍板）

| # | 验证项 | 标准 |
|---|--------|------|
| M6-a | **打包版 stdio 真实启动** | `inkflow-mcp.exe`（PyInstaller 产物）真实启动，`initialize` + `tools/list` 返回 15 工具 |
| M6-b | **工具面完整（≥15 同源核对）** | 打包产物 tools/list 与源码 `mcp/tools/` 注册表逐项核对一致（≥15，ADR-023 v2 薄客户端经 HTTP） |
| M6-c | **冷启动链路** | 内核未运行 → MCP 工具调用 → 自动拉起内核 → 调用成功（ADR-030；复用 F30 M6 手工验证脚本模式） |
| M6-d | **外部 agent 端到端** | 真实外部 agent（Hermes 等）经 MCP 配置调用 InkFlow 工具，真实可用（非 mock） |
| M6-e | **mcp-setup.md 随 skills 包同步** | skills 包（#70）含 mcp-setup.md，引导 agent 平滑切换到 MCP（ADR-022 演进预留，与 #70 联动） |

> **Issue #49 验收标准映射**：≥15 工具 = M3/M6-b；stdio 传输 = M4/M6-a；渐进式工具发现 = M3（tools/list）；冷启动 = M4/M6-c。**spec-only PR 先行**（本 PR 仅 spec，`Part of #49` 不关 issue）；实现 PR 由后续会话承接（`Closes #49`）。

---

## 待澄清问题（≤3）

- **Q1（阻塞级）工具粒度**：15 工具采用「聚合 `manage_*`（action 枚举）」还是「细粒度（每 CLI 子命令一工具，50+）」？✅ 已确认（用户拍板：选项 A，2026-08-16）
  - A. **聚合 15 工具**（本稿方案）：`manage_character` 用 `action=create/list/get/update/delete` 区分；LLM 工具选择友好（15 vs 50+），input_schema 含全部 action 字段（部分字段对特定 action 无效）。与 PRD §6.4 F20 的 15 个工具名一一对应。
  - B. 细粒度 50+ 工具：`character_create`/`character_list`/... 每操作一工具；schema 精确但工具选择负担重、突破 PRD 15 工具口径（≥15 可超但心智变化大）。
  - 建议：A（PRD 口径一致 + LLM 工具选择友好；聚合 schema 的字段冗余可用「action 路由 + description 说明」缓解）。

- **Q2（阻塞级）「与 F26 同源」落地**：F20 工具实现采用「契约同源（复用 ToolSpec + 新建 HTTP 工具工厂）」还是「复用 F26 工具集」？✅ 已确认（用户拍板：选项 A，2026-08-16）
  - A. **契约同源**（本稿方案）：复用 `ToolSpec` 数据结构 + `_ok`/`_fail` 信封语义，新建 `mcp/tools/` HTTP 工具工厂（func = InkFlowHTTPClient 调端点）。理由：F26 工具粒度（5 只读）≠ F20（15 聚合）、路径（直连 service ≠ 经 HTTP）。
  - B. 复用 F26 `build_reader_tools`：直接暴露 F26 的 5 只读工具 + save_draft 为 MCP 工具。理由：零新工具代码；但工具面只有 6 个（<15，不满足 PRD）+ func 直连 service（违背薄客户端经 HTTP）。
  - 建议：A（满足 ≥15 + 薄客户端；「同源」= 契约/语义同源而非实现同源）。

- **Q3（设计决策级）write 工具流式语义**：MCP `tools/call` 是同步 request/response，但 write 走 SSE 流式（内核 `/writing/stream`）。✅ 已确认（用户拍板：选项 A，2026-08-16）
  - A. **同步返回拼接结果**（本稿方案）：write 工具调用非流式端点（`/writing/generate|continue|revise`），返回完整正文（拼接后）。理由：MCP 工具模型天然同步；agent 一次拿到全文；避免 stdio 会话内流式帧与 JSON-RPC 响应交织。
  - B. SSE 流式透传：write 工具内部消费 `/writing/stream`，逐 delta 拼接后一次性返回（结果仍是同步，但走流式端点拿实时进度）。理由：与 GUI/CLI 同源路径；但 MCP 协议层无法逐 delta 推送给 agent（stdio 单响应模型）。
  - 建议：A（简单可靠；B 的流式进度对 agent 无协议级收益，仅实现复杂度增加）。

> **拍板后修订（已完成 v1.1）**：Q1-Q3 全部拍板 A/A/A（2026-08-16），正文已按拍板结果联动修订——§2.2 工具表（Q1 聚合定稿 + write 行 Q3 定稿）、§2.3 决策表（Q1）、§10 范围（Q3）、§12 决策表（决策 4/5 标拍板 + 新增决策 10），本待澄清节三 Q 标 ✅ 留痕不删。

---

*本文档为 F20 功能规格（What），实施步骤（How）见后续 `specs/f20-mcp/plan.md`。所有里程碑验收以本节 M1-M6 为准。*


---

## 附录：f50-mcp-guidance（原独立 spec，容器化合并）

> 本章节由原 `specs/f50-mcp-guidance/spec.md` 合并而来（2026-08-29 spec 目录重构）。

# F50 MCP 分发引导 — 功能规格（Specify 阶段）

> **Spec 版本**: v1.0
> **日期**: 2026-08-23
> **依据**: PRD §6.4 / Constitution P1-P6 / 用户拍板文件 `design/inkflow-mcp-distribution-guidance-2026-08-21.md`（工作区 D:\develop\hermes-projects\InkFlow）
> **所属阶段**: 0.12.0（最后一个 feature 轨），Issue #563（Closes）＋收尾 #551
> **关联 Issues**: #563（MCP 分发引导落地）/ #49（F20 MCP server，0.9.0 已交付）/ #551（自动写作链路收尾）
> **依赖**: F20（mcp server 薄客户端已实现并随包分发）、ADR-022（skills 三通道分发，mcp-setup.md 演进预留）、ADR-023 v2（薄客户端经 HTTP）、ADR-030（本地内核服务化）
> **参考 ADR**: [ADR-022](../../adr/ADR-022.md) · [ADR-023](../../adr/ADR-023.md) · [ADR-030](../../adr/ADR-030.md)
> **状态**: 待实现 🔲

> **Spec 变更**: v1.0 初始版（承接 #563 拍板，落地 MCP 分发引导的可发现性缺口）

## 1. 概述

### 1.1 模块定位

F20（#49，0.9.0 已交付）让 InkFlow 通过 MCP 协议暴露 15 个工具（`inkflow-mcp` 薄客户端经 HTTP 直连常驻内核，ADR-030 D3=A / ADR-023 v2）。**但「可发现性为零」**——agent 与其他宿主不知道 InkFlow 有 MCP 能力、客户端在哪、怎么配置。本模块补齐分发引导，**不改 MCP 集成本身**，只补「可发现性/可配置性」面。

**不做的事**（见 §10）：不重写 CLI 为 MCP 函数、不写 GUI 一键写入宿主配置、不做云端 MCP、不发布 PyPI uvx 通道。

### 1.2 与样板差异图

本模块是「文档 + 只读端点 + GUI 面板 + 安装器 PATH」四件套，非实体 CRUD 型模块——**无新数据模型 / 无新领域实体**，无跨模块 MODIFY 风险面（仅 MODIFY `api/app.py` 注册路由 + `installer.nsh` PATH）。

### 1.3 边界声明

- 端点 `/api/v1/mcp/info` = **自发现通道**（agent 程序化查询），只读、无副作用、无鉴权豁免（天然带 TokenAuthMiddleware，见 §3）。
- MCP 集成本体（tools/list / tools/call / stdio）不在本模块范围。

## 2. 数据模型

**无新数据模型 / 无新 Pydantic 实体**。端点响应为一次性构造的 dict，字段契约见 §3。所需的「MCP 客户端路径」由纯函数 `locate_mcp_client()` 运行时计算（不持久化——不同形态（源码/便携/NSIS/CLI zip）路径不同，动态值最稳）。

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 说明 | 状态 |
|------|------|------|------|
| GET | `/api/v1/mcp/info` | MCP 自发现信息（客户端路径 + 版本 + 宿主配置模板） | 新增 |

### 3.2 请求 / 响应

**GET `/api/v1/mcp/info`** — 无请求体。

响应 200（`application/json`）：

```json
{
  "client_path": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe",
  "version": "0.12.0",
  "config_template": {
    "claude": {
      "mcpServers": {
        "inkflow": { "command": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe" }
      }
    },
    "cursor": {
      "mcpServers": {
        "inkflow": { "command": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe" }
      }
    },
    "hermes": {
      "mcpServers": {
        "inkflow": { "command": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe" }
      }
    }
  }
}
```

字段契约（**锁定**）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `client_path` | `str` | inkflow-mcp 可执行文件绝对路径（运行时动态解析，见 §3.4）；恒非空 |
| `version` | `str` | `inkflow.__version__`（动态读，不硬编码；与内核 /health 同源） |
| `config_template` | `dict[str, dict]` | 各宿主 mcpServers 配置模板，键 = `claude` / `cursor` / `hermes`，值 = 宿主配置文件 JSON（command 内已填 `client_path`） |

### 3.3 异常映射

| 情形 | 状态码 | body |
|------|--------|------|
| 未带 token / token 无效 | 401 | `{"detail": "..."}`（TokenAuthMiddleware 统一处理，非本路由） |
| 任何其他 | - | 不预期——本端点无 DB/LLM 依赖，500 不应发生 |

### 3.4 client_path 解析（`locate_mcp_client` 纯函数）

运行时按序取第一个存在的候选（均返回 `Path`）：

| # | 候选 | 形态 |
|---|------|------|
| 1 | `Path(sys.executable).parent / "mcp" / "inkflow-mcp.exe"` | NSIS 安装版 / 便携 zip：`resources\kernel\mcp\inkflow-mcp.exe` |
| 2 | `Path(sys.executable).parent / "inkflow-mcp.exe"` | dev venv `Scripts\` console script / onedir 兄弟 |
| 3 | `Path(sys.executable).parent.parent / "inkflow-mcp" / "inkflow-mcp.exe"` | CLI zip：`inkflow-mcp/` 与 `inkflow/` 兄弟目录 |

未命中 → 回退候选 1 的期望路径（`Path(sys.executable).parent / "mcp" / "inkflow-mcp.exe"`），保证恒非空。

## 4. CLI 命令签名

本模块**无新 CLI 命令**（MCP 自发现是 HTTP 面，不增 CLI；CLI 已由 F38/ADR-030 恒经 HTTP 覆盖）。

## 5. 关键差异节：分发引导四件套

### 5.1 P0 文档补全（mcp-setup.md + SKILL.md MCP 段）

`skills/inkflow/references/mcp-setup.md` 从占位 → 实操指引：

- **三形态 exe 路径**：CLI zip（`inkflow-mcp/inkflow-mcp.exe`）/ 便携 + NSIS（`resources\kernel\mcp\inkflow-mcp.exe`）/ dev venv（`<venv>\Scripts\inkflow-mcp.exe`）。
- **各宿主 mcpServers JSON 模板**：Claude Desktop / Cursor / Hermes，command 指向实际路径。
- **使用策略**：MCP 优先 / CLI 兜底；工具面以 `tool_search` 为准（**不写 15 工具函数清单**——tools/list 自描述，写 = 漂移源，F20 §4.2/§11）；信封语义（`{"ok":...,...}`）；冷启动说明（首次调用 ensure_kernel 拉起内核，秒级等待）。
- `skills/inkflow/SKILL.md` MCP 段从「发布后补充」改为摘要 + 指向 mcp-setup.md。

### 5.2 P1-A GUI 设置页「MCP 接入」面板

设置页 GeneralPanel 内新增 `McpSettingsCard` Card（零侵入，方案 A）：

- `data-testid="mcp-settings-panel"`（根）。
- 显示当前客户端 exe 路径（动态，来自 `/api/v1/mcp/info`）：`data-testid="mcp-client-path"`。
- 一键复制按钮：客户端路径 + Claude Desktop / Cursor / Hermes 配置 JSON（来自 `config_template`），用 `navigator.clipboard.writeText`；成功 → toast「已复制」。
- 明确**不写**外部宿主配置文件（方案 B 下版评估）。失败（内核未就绪 / 端点 4xx）→ 面板降级显示「暂不可用」+ 保留空路径，不阻断设置页。

### 5.3 P2 内核端点

见 §3（`GET /api/v1/mcp/info`），装配于 `api/routers/mcp.py` + `api/app.py` 注册。**打包版可用**（PyInstaller 冻结后 `inkflow.__version__` 经 copy_metadata 的 dist-info 读取，f19-packaging 已建立）。

### 5.4 附加 installer.nsh PATH 补 `resources\kernel\mcp`

现有 `AddKernelDirToPath` / `un.RemoveKernelDirFromPath` 只写/删 `resources\kernel`。**追加第二个条目 `resources\kernel\mcp`**（同幂等去重逻辑：按 `;` 分隔段大小写不敏感 + 尾部反斜杠归一化；1000 字符保护不变）。安装勾选 PATH 后 `inkflow-mcp` 命令可达，卸载按精确条目清理两目录。

## 6. 组织规则

无全局约定变更。新增路由 `backend/src/inkflow/api/routers/mcp.py` 遵循既有 router 模式（`APIRouter(prefix="/api/v1/mcp", tags=["MCP"])`），经 `api/app.py` `include_router(mcp.router)` 注册。辅助逻辑放 `inkflow/mcp/info.py`（纯函数，无 I/O），与既有 `mcp/server.py` / `mcp/tools/` 同包。

## 7. 边界情况与错误处理

| 情形 | 处理 |
|------|------|
| 内核未运行就调 `/api/v1/mcp/info` | 端点本身独立于运行态？——否：端点由内核进程服务，内核运行即可达；不触发 ensure_kernel（GUI 已拉起内核） |
| 打包版 mcp 客户端二进制缺失 | `locate_mcp_client` 回退期望路径（恒非空），GUI 显示该路径，文档解释三形态 |
| GUI 端点 4xx/网络失败 | 面板降级「暂不可用」，不抛错阻断 |
| 复制失败（clipboard 权限） | toast 失败提示 |
| PATH 超过 1000 字符 | 现有保护逻辑跳过写入并 DetailPrint 警告（不变） |

## 8. 文件结构

| 操作 | 文件 | 说明 |
|------|------|------|
| CREATE | `specs/f20-mcp/spec.md` | 本文件 |
| CREATE | `backend/src/inkflow/mcp/info.py` | `locate_mcp_client()` + `build_mcp_info()`（含 config_template 构造） |
| CREATE | `backend/src/inkflow/api/routers/mcp.py` | `GET /api/v1/mcp/info` router |
| MODIFY | `backend/src/inkflow/api/app.py` | import + `include_router(mcp.router)` |
| CREATE | `backend/tests/unit/test_mcp_info_api.py` | RED 契约：端点形状 + version 动态 + config_template 一致性 + locate 函数 |
| CREATE | `frontend/packages/renderer/src/components/McpSettingsCard.tsx` | GUI「MCP 接入」面板（方案 A） |
| MODIFY | `frontend/packages/renderer/src/pages/settings.tsx` | GeneralPanel 内挂载 `<McpSettingsCard />` |
| MODIFY | `frontend/packages/renderer/src/api/client.ts` | 新增 `fetchMcpInfo()` 类型化调用 |
| MODIFY | `frontend/packages/renderer/src/i18n/zh.ts` + `en.ts` | 新增 `set.mcp.*` 文案 |
| CREATE | `frontend/packages/renderer/src/components/McpSettingsCard.test.tsx` | RED 契约：面板展示 + 复制 JSON |
| MODIFY | `frontend/packages/electron/build/installer.nsh` | PATH 补 `resources\kernel\mcp`（幂等去重 + 卸载清理） |
| MODIFY | `skills/inkflow/references/mcp-setup.md` | 占位 → 实操指引 |
| MODIFY | `skills/inkflow/SKILL.md` | MCP 段非占位 |

> 说明：installer.nsh 无契约测试框架（NSIS），以打包脚本验证 + 人工核对幂等逻辑（§5.4）；不新增编译期测试。

## 9. 测试策略

| 层次 | 覆盖 | 命令 |
|------|------|------|
| backend/unit | `/api/v1/mcp/info` 端点形状 + version 动态 + config_template 三宿主键 + locate_mcp_client 三形态 | `cd backend; uv run pytest tests/unit/test_mcp_info_api.py` |
| frontend/vitest | McpSettingsCard 展示路径 + 一键复制（clipboard mock） | `pnpm vitest run McpSettingsCard` |

覆盖率：本模块为只读端点 + 展示面板，无新分支逻辑；端点形状与 resolve 逻辑为断言主体。全局 ≥60% 达标（新增逻辑面窄，不拉低）。

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| skills 里 CLI 调用改写为 MCP 函数 | ADR-022：工具由协议自描述，不重复实现逻辑 |
| GUI 一键写入宿主配置文件（方案 B） | 下版评估（#563 拍板方案 A） |
| 云端 Streamable HTTP / remote MCP | ADR-023 后移 2.0.0 云端里程碑 |
| PyPI `uvx inkflow-mcp` 通道 | 候选，随 2.0.0 云端版评估 |
| MCP 工具函数清单写入文档 | tools/list 自描述，F20 §4.2/§11（写 = 漂移源） |

## 11. 依赖关系

| 依赖 | 说明 |
|------|------|
| ✅ F20（mcp server） | 0.9.0 已交付，tools/list 自描述 |
| ✅ ADR-022 / ADR-023 v2 / ADR-030 | 架构定论沿用，不改 |
| ✅ f19-packaging（PyInstaller dist-info + `resources/kernel` 布局） | client_path 解析基础 |
| ⏳ f42 / f47（写作链路） | #551 收尾（本 PR 只关 #551，不依赖实现） |

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 | 备选否决 |
|------|------|------|----------|
| GUI 面板范围 | **方案 A**（显示路径 + 一键复制 JSON） | 零侵入，不写外部宿主配置 | B（一键写入宿主配置文件）：下版评估 |
| 自发现端点 | **做** `GET /api/v1/mcp/info` | agent 程序化查询，与 mcp-setup.md 联动 | 只写文档：agent 无法程序化获取 |
| client_path 解析 | 运行时动态 `locate_mcp_client()` 纯函数 | 多发行形态路径不同，动态最稳 | 硬编码：形态间漂移 |
| 归属版本 | **全部归 0.12.0** | 拍板 | - |

## 13. 验收标准

| # | 里程碑 | 验证 |
|---|--------|------|
| M1 | RED 契约 FAIL 确认 | 后端 `uv run pytest tests/unit/test_mcp_info_api.py` 全 FAIL（ModuleNotFoundError / 断言失败）；前端 `pnpm vitest run McpSettingsCard` FAIL（组件不存在 collection error） |
| M2 | GREEN | 后端 `cd backend; uv run pytest tests/unit/ ../tests/` + ruff + mypy 全绿；前端 `pnpm vitest run && pnpm tsc --noEmit` 全绿 |
| M3 | PR merged + CLOSED | `gh pr merge --squash --delete-branch`；#563 CLOSED；#551 CLOSED（收尾）；`git worktree remove` |

**手工验收（发布验证）**：打包版 `curl http://127.0.0.1:<port>/api/v1/mcp/info`（带 token）返回 `{client_path, version, config_template}`，`client_path` 指向 `resources\kernel\mcp\inkflow-mcp.exe`；mcp-setup.md 照做能配通；安装勾选 PATH 后 `inkflow-mcp` 可达。

## 待澄清问题（≤3）

1. ~~config_template 是否按宿主分键~~ ✅ 已确认（用户拍板：方案 A，三宿主 Claude/Cursor/Hermes 分键 `claude`/`cursor`/`hermes`，值 = 宿主 mcpServers JSON，command 填 client_path）——正文 §3.2 已按此定稿。
