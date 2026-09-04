# F496 统一日志页（内核/GUI/AI 日志分类展示与查询）— 功能规格

> **状态**: 🔲 待实现
> **日期**: 2026-09-04
> **关联 Issues**: #496（本 spec 对应）· #888（F57 前置：日志埋点 + i18n）· #892（Electron kernel_ready 上报）
> **上游 spec**: `specs/f57-logging-i18n/spec.md`（§2.2 结构 / §3 API / §12「#496 日志页 UI 页面另 issue」）
> **类型定位**: 消费型前端页面 + 数据侧最小补强（不新增业务实体）

---

## 1. 背景与目标

F57（#888）交付了结构化日志 schema、`GET/POST /api/v1/logs`、i18n messages 目录与前端 logger bridge，
但**日志的"查看面"缺失**：内核日志只进 loguru 文件/stderr（不进 store），GUI 上报进了 store 却无处可看。
#496 交付统一日志页：内核 / GUI / AI 三类日志同页分类展示与查询，无需 DevTools/翻文件。

**验收锚点**（issue #496）：
1. 日志页可分类展示三类日志（内核=api/agent/tool/cli/mcp，GUI=frontend，AI=llm）。
2. 支持按时间范围 / 级别 / 关键字（q/correlation_id/project_id）过滤查询。
3. message 用 `t(message_key, params)` 渲染，语言切换实时生效（非硬编码）。

## 2. 数据源契约（消费 F57 + 本 spec 最小补强）

### 2.1 GET /api/v1/logs（既有契约，§3 扩展）

响应 F7 信封：`{"ok": true, "data": {"items": [StructuredLogRecord dict...], "total": N, "offset": page*limit, "limit": limit}}`。
items 按 timestamp 降序；字段见 F57 spec §2.2（level/caller_type/caller_name/event/message_key/params/correlation_id/project_id/duration_ms/error_code/stack）。

### 2.2 后端补强（本批实现，理由=验收 1/2/3 的数据前提）

| # | 补强 | 现状缺口 | 决策 |
|---|------|----------|------|
| B1 | **结构化 sink 入库** | `log_structured`/`@instrument` 只发布到 loguru（文件/stderr），不进 `StructuredLogStore` → 内核/AI 日志在 GET /logs 不可见 | `setup_logging()` 追加第三个 sink：`logger.add(_structured_sink, level=<同 console 切级>, filter=带 caller_type 的 record)` → `StructuredLogStore(config.data_dir/"logs"/"structured").append()`。sink 内部异常自吞（日志故障不带崩业务）。既有 `handlers[0]`（console）顺序不变 |
| B2 | **level/caller_type 多值过滤** | store 查询只支持单值等值 → 无法表达「INFO+」「内核=api,agent,tool,cli,mcp」 | `level`/`caller_type` 查询参数支持**逗号分隔多值**（大小写不敏感；单值向后兼容，`tests/api/test_logs_api.py` 既有断言零破坏） |
| B3 | **project_id 接受 UUID** | 参数是 int；前端项目 id 是 UUID 串 | 查询参数 `project_id: str \| None`；解析：纯数字→int，合法 UUID→`uuid.UUID(s).int`，非法→422 |
| B4 | **X-Correlation-Id 沿用** | 前端 bridge 已发头，后端埋点从不消费 → correlation_id 查询只能命中 GUI 记录 | 纯 ASGI 中间件（镜像 `token_auth` 目录）读 `X-Correlation-Id` → `ContextVar`；`log_structured` correlation_id 显式参数 > contextvar > `""`（无 contextvar 时行为与现状逐字一致，零翻转） |
| B5 | **Electron 消息键补齐** | `log.event.kernel_ready/kernel_failure/kernel_exit/kernel_spawn_error/kernel_crash` 后端 messages 与前端 log.ts 均未定义 → 页上渲染生键 | zh/en messages + 前端 `i18n/log.ts` 同步补 5 键（zh/en 对称；`i18n.contract.test.ts` 对齐枚举扩 kernel_ready） |

**不做**（记 2.3 边界）：service 埋点调用点的 project_id 归属补齐、GUI 上报 record 携带 project_id、AI 日志并入 extraction_runs 表。

## 3. 日志页 UI 规格（renderer）

### 3.1 入口与路由

- 新路由 `/logs` → `pages/logs.tsx` 命名导出 `LogsPage`（App.tsx Routes 注册；`TITLE_BY_PATH['/logs'] = 'logs.title'`）。
- 侧边导航：`AppNav` SYSTEM 分组新增 `nav-item-logs`（NavLink to=/logs，icon ScrollText，labelKey `nav.logs`='日志'）。

### 3.2 控件与 testid 契约

| testid | 控件 | 行为 |
|--------|------|------|
| `logs-page` | 根容器 | — |
| `log-tab-all` / `log-tab-kernel` / `log-tab-gui` / `log-tab-ai` | 分类 tab（role=tab） | 默认 all。all→不传 caller_type；kernel→`api,agent,tool,cli,mcp`；gui→`frontend`；ai→`llm`。切换立即重查（page 归 0） |
| `log-level-select` | 级别下拉（Radix Select） | 默认 **INFO**（DEBUG 默认关）。DEBUG→不传 level；INFO→`INFO,WARN,ERROR`；WARN→`WARN,ERROR`；ERROR→`ERROR`。切换立即重查 |
| `log-project-select` | 项目下拉 | 选项=useProjectStore.projects +「全部项目」；选中→`project_id=<UUID>`；立即重查 |
| `log-q-input` | 关键字输入 | q（后端整条 JSON 匹配）；strip 空→不传 |
| `log-correlation-input` | 关联 ID 输入 | correlation_id；随查询按钮提交 |
| `log-from-input` / `log-to-input` | datetime-local | from/to（ISO 串提交）；空→不传 |
| `log-search-btn` | 查询按钮 | 提交 q/correlation/from/to（page 归 0）并查询 |
| `log-reset-btn` | 重置按钮 | 全部筛选回默认（tab all/level INFO/项目全部/输入清空）并重查 |
| `log-list` | 日志列表容器 | — |
| `log-row` | 单条记录行 | 含：`log-level-badge`（level 文本）、timestamp（本地化 `toLocaleString()`）、caller_type、caller_name、**渲染后 message**、duration_ms（有则显）、error_code（有则显）、correlation_id（有则显，可截断展示） |
| `log-empty` | 空态（total=0） | 文案 `logs.empty` |
| `log-loading` | 加载态 | 请求进行中 |
| `log-error` | 错误态 | 含失败信息（errorMessage） |
| `log-page-prev` / `log-page-next` | 翻页 | page±1（0 起，越界禁用：首页 prev disabled，末页 next disabled） |
| `log-page-info` | 分页信息 | `logs.page.info`='第 {page} / {pages} 页 · 共 {total} 条'（pages=ceil(total/limit)，limit 固定 50） |
| `log-refresh-btn` | 刷新 | 按当前条件重查 |

**状态机**：挂载即查询（默认 tab all + level INFO，不自动带 DEBUG）；查询失败→error 态（列表清空）；空结果→empty 态；任何筛选变更→page 归 0 重查；并发防护：后发请求结果覆盖先发（按请求序号丢弃过期响应）。

### 3.3 message 渲染（i18n 实时）

优先级：**远端目录 > 本地 t() > 生 key**：
1. 页面按当前语言拉 `GET /api/v1/i18n/messages?lng=<lang>`（挂载 + lang 切换时重拉；失败静默回退本地字典——离线可用）。
2. 渲染 = `interpolate(remote[message_key] ?? 本地 t(message_key, params), params)`；remote 命中时用远端模板插值，未命中回退 `t()`（t 缺 key 回退 zh → 生 key，同 useI18n 语义）。
3. 语言切换（顶栏 lang Select，theme store）→ `useI18n` 重渲染 + 重拉远端目录 → 列表文案实时切换（无刷新按钮要求）。

## 4. 前端模块清单

| 文件 | 动作 | 内容 |
|------|------|------|
| `renderer/src/api/logs.ts` | CREATE | `fetchLogs(params)` / `fetchLogMessages(lng)`（apiFetch，镜像 api/search.ts 形态）+ DTO 类型 |
| `renderer/src/api/logs.test.ts` | CREATE(RED) | URL 组装/参数序列化/F7 信封/缺参不携带 契约 |
| `renderer/src/pages/logs.tsx` | CREATE | `LogsPage`（§3 全契约；单文件 ≤400 行） |
| `renderer/src/pages/logs.test.tsx` | CREATE(RED) | 组件契约（镜像 search.test.tsx 形态：vi.mock api/logs） |
| `renderer/src/i18n/logs-ux.ts` | CREATE | `logsUxZh/logsUxEn`（§3 全部 UI 键 + `nav.logs`；**勿内联 zh.ts/en.ts——900 行护栏**） |
| `renderer/src/i18n/useI18n.ts` | MODIFY | dicts 合并 logs-ux |
| `renderer/src/i18n/log.ts` | MODIFY | 补 5 个 `log.event.kernel_*` 键（B5） |
| `renderer/src/App.tsx` | MODIFY | 路由 + TITLE_BY_PATH |
| `renderer/src/components/AppNav.tsx` | MODIFY | SYSTEM_ITEMS 加 logs 项 |
| `renderer/src/i18n/i18n.contract.test.ts` | MODIFY(RED) | combo 加 logsUx；log.event 对齐枚举扩 kernel_* |
| `renderer/src/components/AppNav.test.tsx` / `App.routing.test.tsx` | MODIFY(RED) | nav-item-logs 存在性 + /logs 路由断言 |
| `tests/e2e/e2e-logs.spec.ts` | CREATE | 真实内核旅程（§6） |
| `.github/workflows/ci.yml` | MODIFY | `e2e-frontend-logs` job（镜像 e2e-frontend-models，第二批按需触发，非 required） |

## 5. 后端模块清单

| 文件 | 动作 | 内容 |
|------|------|------|
| `core/log.py` | MODIFY | B1 `_structured_sink`（record→StructuredLogRecord 映射 + 异常自吞） |
| `logging/store.py` | MODIFY | B2 `_text_eq`→多值集合匹配（level/caller_type 逗号拆分；None 单值语义不变） |
| `api/routers/logs.py` | MODIFY | B3 `project_id: str \| None` + 归一化（非法→HTTPException 422） |
| `api/middleware/correlation.py` | CREATE | B4 纯 ASGI 中间件：X-Correlation-Id → ContextVar（`inkflow.logging` 导出 get/set） |
| `logging/schema.py` | MODIFY | B4 `log_structured` correlation_id=None 时取 contextvar |
| `api/app.py` | MODIFY | 挂载 CorrelationMiddleware（先于/后于 TokenAuth 均可——无鉴权依赖，纯 ASGI） |
| `i18n/messages/zh.json` + `en.json` | MODIFY | B5 补 5 键（zh/en 对称） |

## 6. 测试策略（SDD+TDD）

- **RED 契约**（先行全 FAIL 才实现）：
  - `tests/api/test_logs_query_contract.py`（新建）：B2 多值（level=INFO,WARN / caller_type=api,agent）、B3 UUID（含 422）、B4 埋点记录沿用请求头 correlation_id（TestClient 发头→GET 回查）。
  - `backend/tests/unit/test_logging_structured_sink.py`（新建）：B1 setup_logging 后 log_structured INFO 落 store 目录（data_dir/resolve tmp 隔离）；debug=False 时 DEBUG 不落；非 bind 记录不落；sink 异常不带崩。
  - `renderer/src/api/logs.test.ts` + `pages/logs.test.tsx`（新建）：§3/§4 契约。
  - 既有文件迁移批：AppNav.test / App.routing.test / i18n.contract.test（MODIFY，RED 期落盘）。
- **E2E**（`e2e-logs.spec.ts`，CI 裁判，不计覆盖）：launch→等内核→POST /api/v1/logs（kernelFetch 造前端记录）或触发真实操作→导航 #/logs→断言 `log-row` 出现与 t() 渲染文案→切分类 tab→断言过滤生效。
- 覆盖率：新增后端函数走 GET/POST + 直调双保障（func-cov 先例 `test_logs_i18n_direct.py` 形态——B1 sink/B4 中间件同线程直测）。

## 7. 边界与待拍板

- **导出**（issue 标可选）：不做，另 issue。
- **自动刷新/实时流**：不做（按需查询 + 刷新按钮）。
- **service 埋点 project_id 归属密度**：现仅少数调用点带 project_id → 「按项目查询」命中面有限；GUI record 不携带 project_id。是否补数据面（log_structured 调用点扩 project_id）→ PR body 待拍板，本批不动。
- **DEBUG 埋点落库量**：B1 sink 与 console 同级切分——config.debug=True 时 DEBUG 全量入库（store 为 JSONL 按天文件，量可控；30 天 retention 由 loguru 文件 sink 承担，store 侧暂不清理→另记运维观察项）。
