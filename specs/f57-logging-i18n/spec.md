# F57 日志埋点 + 全链路 i18n（Spec 规格）

> **Spec 版本**: v1.0（2026-09-03）
> **日期**: 2026-09-03
> **依据**: Issue #888（用户拍板：全译 + L1/L2 综合 + 复用现成）+ #887（日志埋点）+ #496（日志页显示，本 spec 是前置）
> **所属阶段**: 0.13.0（横向基础设施加固；估算 X-Y 人天）
> **状态**: 🔲 待实现
> **类型定位**: 跨层横切平台能力（无新业务实体）——镜像 `specs/f19-packaging/spec.md`；**F57**（待 ADR-019 Feature 表登记录入，当前最大 F56）
> **关联 Issues**: #888（前置总）· #887（日志埋点细节）· #496（日志页显示，被前置）
> **依赖**: ✅ ADR-016(loguru)/ADR-044(debug) ⏳ F53(secret-redact)/#875(工具参数链脱敏)/ADR-021(内核 HTTP)
> **参考 ADR**: ADR-016 · ADR-044 · ADR-005v2(LLM) · ADR-021/030

> **快速导航**：§1 盘点 · §2 数据模型(i18n目录+日志结构) · §3 API契约 · §4 埋点矩阵 · §5 关键差异(i18n架构) · §6 文件结构 · §7 边界 · §8 不在范围 · §9 测试策略 · §10 依赖 · §11 决策 · §12 验收

---

## 1. 概述

**关键事实盘点**（现状源码位置 + 缺口）：
- 后端日志基座：`backend/src/inkflow/core/log.py`（loguru，`logger.add(level="DEBUG" if config.debug else config.log_level)` + `logger.bind` 结构化）——✅ 框架在，❌ **埋点不全**（非所有端点/agent/LLM/工具/CLI/MCP 都打日志）。
- 前端：**无统一 logger**，散落 `console.log/warn/error`（theme.ts 等）。
- i18n：前端已有 `frontend/packages/renderer/src/i18n/`（en.ts + extract-keys + 各域 ux.ts，`t(key,params)` 实时切换 + `header-lang-select` + localStorage `inkflow.ui`）；**后端无 i18n**（无 babel/gettext 依赖，仅 stdlib gettext；无 locale 目录）。
- LLM/工具/agent 提示词：`backend/src/inkflow/infrastructure/llm/templates/*.yaml` 硬编码中文，无 per-locale。
- 埋点广度：后端可埋点函数 ≈ **409**（API 路由端点 + agent 编排 + LLM 调用 + 工具 + CLI 命令 + MCP 工具，regex 实测）。

**1.3 边界声明**：本模块不新增业务实体；只加**日志埋点 + i18n 基础设施 + 前端桥接**。#496（日志页显示）消费本 spec 产出的结构化日志；#887 为日志埋点细节引用。前端 UI 文案全量 i18n 已有（前端已 i18n），本 spec 只加日志消息键 + 后端对齐。

---

## 2. 数据模型（配置字段 + 结构，非 ORM 表）

### 2.1 i18n 目录（语义域结构 + 双层）
**结构**（按"内容品种"语义域分目录，格式随品种）：
```
backend/src/inkflow/i18n/                    # 打包默认层（PyInstaller 冻结，随版本更新）
  messages/{zh,en}.json                      # 日志/API 错误消息 (key-value: log.event.*/api.error.*)
  functions/{zh,en}.json                     # 工具 description/参数 (key-value)  ← LLM function-calling
  prompts/{zh,en}/<name>.yaml                # LLM 提示词模板 (per-locale YAML)
  skills/{zh,en}/<name>.md                   # 内置 skill 文档 (per-locale markdown)
  resolver.py                                # resolve_locale(lang) + t(domain, msgid, params)
```
**双层（用户可改 + 打包默认）**：
- **打包默认层**（上表，权威基线，随版本更新）。
- **用户覆盖层** `%APPDATA%/InkFlow/i18n/<domain>/<locale>.override.json`（用户只写想改的键）。
- **运行时合并 fallback 链**：`用户覆盖(键级 merge) → 打包默认 → zh`；`t()` 缺键回退默认并 WARN 记录（防静默）。
- `resolve_locale` 优先级 **项目 language > 用户/全局 config.lang > OS locale > zh**；per-call 解析（勿缓存 boot 单例）。
- 前端 `renderer/src/i18n/` 已存在（domain-first，en.ts + 各域 ux.ts），新增 `log.ts` 与后端 messages 键**对齐**（同一 msgid）。

### 2.2 日志结构（结构化，对齐 OpenTelemetry 语义，2.0 cloud 前置）
```
timestamp(ISO8601) / level(DEBUG|INFO|WARN|ERROR) / logger(module名) /
caller_type(api|agent|llm|tool|cli|mcp|frontend) / caller_name / event /
message_key(msgid) / params(dict) / trace_id / correlation_id / span_id /
project_id / entity_id / duration_ms / error_code / stack?(仅ERROR)
```
- `caller_type` 枚举：`api`(路由端点)、`agent`(编排)、`llm`(LLM 调用)、`tool`(工具调用)、`cli`(CLI 命令)、`mcp`(MCP 工具)、`frontend`(前端页面操作)。
- `message_key` = i18n msgid（语言中立）；日志页用 `t(message_key, params)` 渲染 → **实时切换**。
- `correlation_id`：一次操作/对话/pipeline 贯穿前后端（前端生成 uuid → 请求头 `X-Correlation-Id` → 后端沿用；后端内部 `trace_id`/`span_id` 补充）。

---

## 3. API 契约

### 3.1 新增端点
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/logs` | GET | 日志页查询：`?level=&caller_type=&project_id=&from=&to=&correlation_id=&page=`，返回 `{items,total}`（结构化 JSON 列表，供 #496） |
| `/api/v1/logs` | POST | 前端桥接上报：前端 logger 上报结构化 log 记录，聚合进 loguru 同一流 |
| `/api/v1/i18n/messages` | GET | 日志页/prompt 前端取本地化消息目录：`?lng=` 返回对应 locale 的 msgid→text |

### 3.2 请求/响应（示例，F7 信封 `{ok,data}`）
- `POST /api/v1/logs` body（前端 bridge）：
  ```json
  {"level":"INFO","caller_type":"frontend","caller_name":"WritingPage.createChapter","event":"create_chapter","message_key":"log.event.create_chapter","params":{"title":"第一章"},"correlation_id":"<uuid>","project_id":123}
  ```
- `GET /api/v1/logs` 响应：`{"ok":true,"data":{"items":[...],"total":N,"offset":0,"limit":50}}`。

### 3.3 安全
- `/api/v1/logs` 需本地鉴权（token 401，同 ADR-021）；参数层机密脱敏（F53 redact，日志不泄 key/token）。

---

## 4. 埋点矩阵（对象 → 级别，DEBUG 默认关）

| 埋点对象 | DEBUG | INFO | WARN | ERROR |
|---------|-------|------|------|-------|
| API 路由端点（~130） | 入口调试 | 写操作数据变化 | 校验失败(422) | 未捕获异常 |
| agent 编排（~40） | 每步/工具选择 | 状态转换/产出 | 重试/降级/护栏触达 | 编排崩溃 |
| LLM 调用（~16） | 请求/响应摘要 | 完成 | 超时重试成功 | 未捕获/认证失败 |
| 工具调用（~80） | 工具名/参数摘要 | 落库成功 | 失败自愈 | 未捕获 |
| CLI 命令（~30） | 命令/参数摘要 | 数据变化 | 校验失败 | 未捕获/停摆 |
| MCP 工具（~30） | 工具调用 | 成功 | 参数错/结果异常(LLM 可续用) | 未捕获 |
| 前端页面操作 | 页面加载/导航 | 用户操作/数据变更 | 可恢复 UI/API 错 | 未捕获/白屏 |

> DEBUG 默认关（`config.debug`/`INKFLOW_DEBUG` env）；INFO 默认可见（数据变化）。DEBUG 只埋上下文中的 409 函数入口/步骤，**非每个内联 helper**（降噪）。

---

## 5. 关键差异（跨层联动行为：i18n 架构，全译，per-call 准实时，双层）

- **双层**：打包默认（`backend/src/inkflow/i18n/<domain>/{zh,en}.*`，随版本）+ 用户覆盖层（`%APPDATA%/InkFlow/i18n/<domain>/<locale>.override.json`，键级 merge）。
- **语义域**：messages/functions/prompts/skills（格式随品种：JSON/YAML/markdown）。
- `resolve_locale()`：per-call 解析（勿缓存 boot 单例）→ **准实时切换**（下次请求/生成/读取即新语言），无需重启；前端 UI 已实时。
- **提示词全译**：`i18n/prompts/{zh,en}/<name>.yaml`（原 `infrastructure/llm/templates/*.yaml` 迁入）；工具 description 走 `i18n/functions/{zh,en}.json`；skill 走 `i18n/skills/{zh,en}/<name>.md`。
- **抽取/校验**：后端消息键与前端 `extract-keys.ts` 对齐；`i18n.contract.test`（前端已有）扩展到后端各域键对称性 + 用户 override 键必须存在于打包默认（防孤儿键）。
- **prompt per-project 定制**：本期不做（scope 克制），`resolve_locale` 先按"项目 language → 用户覆盖 → 打包默认 → zh"；per-project 定制作后续扩展。

---

## 6. 文件结构（CREATE/MODIFY，对照真实树）

**CREATE**
- `backend/src/inkflow/i18n/messages/{zh,en}.json` / `functions/{zh,en}.json` / `prompts/{zh,en}/*.yaml` / `skills/{zh,en}/*.md`
- `backend/src/inkflow/i18n/resolver.py`（resolve_locale + t）
- `backend/src/inkflow/logging/`（结构化 logger 封装：mask_fields/bind_correlation/sink，基于 loguru）
- `backend/src/inkflow/api/routers/logs.py`（GET/POST /logs）
- `backend/src/inkflow/api/routers/i18n.py`（GET /i18n/messages）
- `frontend/packages/renderer/src/logger.ts`（4 级前端 logger + 上报 bridge）
- `frontend/packages/renderer/src/i18n/log.ts`（日志页 msgid）

**MODIFY**
- `backend/src/inkflow/core/log.py`（扩展结构化 sink + correlation/脱敏绑定）
- `backend/src/inkflow/core/config.py`（`lang`、`log_level` 扩展；`INKFLOW_LANG` env）
- `backend/src/inkflow/infrastructure/llm/templates/*.yaml`（迁入 i18n/prompts/{zh,en}/）
- `backend/src/inkflow/api/app.py`（挂载 logs/i18n router + lifespan i18n 目录校验）
- `frontend/packages/renderer/src/api/client.ts`（bridge：logger 上报 + correlation 头）
- `.github/workflows/ci.yml`（日志/i18n 契约 job + 覆盖口径）

---

## 7. 边界情况与错误处理

| 场景 | 处理 |
|------|------|
| DEBUG 全开（409 函数） | 只埋点上下文函数入口/步骤，非每个内联 helper（降噪）；日志页默认筛选 INFO+ |
| i18n 缺 msgid | `t()` 回退打包默认/zh 并 WARN 记录（防静默） |
| 用户 override 孤儿键 | 校验：override 键必须存在于打包默认，否则 WARN |
| 前端 bridge 失败 | 前端 logger 本地 console 兜底 + 重试/丢弃（非阻塞） |
| 参数含 key/secret | `mask_fields` 脱敏（F53 + #875） |
| 日志轮转 | loguru `rotation`（按天）+ 保留 N 份；`/logs` 读文件聚合 |

---

## 8. 不在范围

| 项 | 归属/原因 |
|----|----------|
| #496 日志页 UI 实现 | 本 spec 只产日志结构，页面另 issue |
| 2.0 cloud 可观测（OTEL exporter/远端收集） | 本 spec 预留字段，cloud 里程碑再做 |
| 前端 UI 文案全量 i18n（已有） | 前端已 i18n，本 spec 只加日志消息键 + 后端对齐 |
| prompt per-project 定制 | scope 克制，后续扩展 |

---

## 9. 测试策略

- 后端：`i18n` resolver/t() 单测（键存在/回退/插值）、`logging` 结构化 schema 契约、`/logs` GET/POST 契约、脱敏断言、「DEBUG 不开→无 DEBUG 日志」。
- 前端：`logger.ts` 4 级 + 上报、`i18n/log.ts` 键对称、bridge 契约。
- 契约 RED→GREEN；E2E 不计覆盖；后端覆盖计入 unit+api+cli+integration 综合（行98.5/分支95 + 函数覆盖门禁）。

---

## 10. 依赖关系

- 依赖：ADR-016(loguru)、ADR-044(debug)、F53(redact)、#875(工具脱敏)、ADR-021(内核 HTTP)。
- 被依赖：#496（日志页）、2.0 cloud（可观测 + 按用户 locale）。

---

## 11. 关键架构决策

| 决策 | 选择 | 理由 | 备选 |
|------|------|------|------|
| 日志框架 | **复用 loguru** | 已在用，不重复造轮子 | structlog/自建（否决：重复） |
| i18n 方案 | **自建轻量 JSON 目录**（resolve_locale + t） | 与前端 t(key,params) 同构、0 新增依赖、适合日志 msgid | gettext（.po/.mo 编译不适合 key+params）/Babel（加依赖） |
| 提示词翻译 | **全译**（先实现入口，质量不行回退中文，修好改回） | 用户拍板 | 半译只译用户可见（否决：用户要全译） |
| 切换 | **per-call 准实时**（勿缓存 boot 单例） | 无需重启，下次请求即新语言 | boot 单例（否决：需重启） |
| i18n 结构 | **语义域分目录**（messages/functions/prompts/skills，格式随品种） | "译的是什么"比"用在哪"更贴合；格式区分 | 单一大 JSON（否决：混格式不可维护） |
| i18n 位置 | **双层**：打包默认(权威) + 用户覆盖层(`%APPDATA%/InkFlow/i18n/`) 键级 merge | 用户可自定义翻译/提示词；不随版本覆盖定制；创作工具需可调 | 仅打包（否决：用户不能改）/仅用户目录（否决：无默认基线） |

---

## 12. 验收标准（M1-Mn）

| M | 验收 | 载体 |
|---|------|------|
| M1 | 后端 `logging` 结构化 schema（caller_type/correlation_id/message_key/params）+ 脱敏契约通过 | `backend/tests/unit/test_logging_schema.py` |
| M2 | `/api/v1/logs` GET/POST + `/api/v1/i18n/messages` 契约通过 | `tests/api/test_logs_api.py` / `test_i18n_api.py` |
| M3 | i18n resolver（优先级 + t 插值 + 缺键回退）+ zh/en 键对称（含后端各域 + 前端 log.ts）通过 | `backend/tests/unit/test_i18n_resolver.py` + 前端 `i18n.contract.test` |
| M4 | 后端 ~409 函数埋点 + 前端 logger/bridge implemented；DEBUG 默认关、INFO 数据变化可见 | `backend/tests/unit`（DEBUG 关闭断言）+ 前端 `logger.test` |
| M5 | 提示词/工具/skill 全译（zh/en）+ per-call 准实时切换生效 | `backend/tests/unit/test_i18n_prompts.py` |
| M6 | 零回归（backend 全测 + 前端 vitest/tsc/lint + ruff/mypy） | CI |

> 所有里程碑验收以本节 M1-M6 为准；#496 依赖 M1-M3（日志结构 + 消息目录就绪）后消费。
