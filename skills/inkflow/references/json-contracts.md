# JSON 契约参考（json-contracts.md）

InkFlow CLI 的 `--json` 输出是 agent 与内核之间的**稳定执行契约**。本文档描述信封结构、退出码与核心命令的返回形态。字段以 `tests/cli/` 契约测试、`ci_cd/openapi_snapshot.json`（权威契约快照）与真实运行为准（变更评审时对照）。

## 1. 信封结构

### 成功

```json
{"ok": true, "data": <任意 JSON>}
```

### 失败

```json
{"ok": false, "error": {"code": "NOT_FOUND", "message": "项目不存在: ..."}}
```

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 业务错误（信封内 error.code 定位） |
| 2 | 用法错误（未知参数/缺参/互斥输入，typer 输出） |
| 130 | Ctrl+C 中断 |

> `3` 是**内核子进程**的准入拒绝码（`INKFLOW_KERNEL_CONFLICT`，见 kernel.md），非 CLI 顶层退出码；CLI 捕获后映射为 `KERNEL_ERROR` 信封（exit 1）。

## 2. 常见错误码

| code | 场景 |
|---|---|
| `NOT_FOUND` | 资源不存在（项目/章节/实体 ID 非法或缺失） |
| `VALIDATION_ERROR` | 参数校验失败（含 `--json` 下删除类命令缺 `--force`） |
| `DB_ERROR` | 数据库/内部错误（含 chapter/volume/write 组非法 UUID） |
| `KERNEL_ERROR` | 内核拉起失败 / 内核拒绝准入（已有同 kind 实例，消息含 kind/port/pid/data_dir） |
| `LLM_ERROR` | LLM 调用失败 |
| `RAG_ERROR` | 向量库错误 |
| `EXTRACTION_ERROR` | 提取管线失败 |
| `UNSUPPORTED_TYPE` | 不支持的枚举类型 |
| `CONFIG_ERROR` | 配置错误 |

## 3. 核心命令返回形态

### project list

```json
{
  "ok": true,
  "data": [
    {"id": "00000000-0000-0000-0000-000000000001", "name": "我的小说", "tags": ["玄幻"],
     "language": "zh-CN", "target_words": 1000000, "created_at": "...", "updated_at": "..."}
  ]
}
```

> ⚠️ `data` 是**项目对象数组**（非 `{projects, total}` 对象）；`id` 是下游所有 `--project-id` 的来源，不要猜测 UUID。（#595 起 `genre` 已并入 `tags`；不再有 `genre` / `status` 字段。）

### project create

```json
{"ok": true, "data": {"id": "...", "name": "我的小说", "tags": ["玄幻"], "language": "zh-CN", "target_words": 0}}
```

### chapter list

```json
{
  "ok": true,
  "data": {
    "chapters": [
      {"id": 1, "project_id": "...", "title": "第一章", "status": "draft",
       "word_count": 3200, "summary": "...", "content": "..."}
    ],
    "total": 1
  }
}
```

> chapter id 为整数；`--status` 不传 = 全量返回。

### write next（SSE 流式）

`write next`（deterministic 模式）底层走 **SSE 流**端点（`text/event-stream`），CLI 聚合后输出最终信封（writing.md）；原始帧协议：

```text
data: {"event": "chunk", "content": "夜色渐深，"}

data: {"event": "done", "chapter_id": 5, "word_count": 3400}
```

事件类型：`chunk`（增量文本）/ `done`（完成，含落库章节 ID）/ `error`（错误信息）。agent 应按事件流逐块消费并拼接 content，收到 `done` 后可用 `chapter get` 验证落库结果。

### audit chapter（202 异步受理，**非**直接报告）

⚠️ 旧文档写「`audit chapter` 直接返回完整报告 `{report_id, issues, score}`」——**已过期**。现形态（#1425）：

触发 `POST /api/v1/projects/{pid}/chapters/{cid}/audit` → **HTTP 202**，返回受理信封：

```json
{"ok": true, "data": {"log_id": "12", "status": "running"}}
```

`status` = 受理瞬间的任务执行态（running/completed）。要拿到结果须轮询：

`GET /api/v1/audit-logs/{log_id}/status`（轻量，无 findings）→

```json
{"ok": true, "data": {"log_id": "12", "run_status": "completed", "status": "accepted",
  "degraded": false, "error": null, "chapter_id": "5"}}
```

`run_status` 枚举：**running / completed / failed**；失败原因在 `error`。

执行完成取 findings 明细走 `GET /api/v1/audit-logs/{log_id}`（v1.4 读口，含记录元信息 + findings 快照）。

> CLI 侧：`audit chapter chapter ...` 默认 `--wait` 自动轮询到终态；`--no-wait` 立即返回 `{log_id, status}`；`--log <log_id>` 直接取明细。批量走 `audit batch`（逐章派发 + 轮询聚合）。

### extract run

```json
{
  "ok": true,
  "data": {
    "type": "character", "status": "success",
    "processed_sources": 3, "skipped_sources": 0,
    "created": 5, "updated": 1,
    "warnings": [], "model": "deepseek/deepseek-chat",
    "indexed": false,
    "batch_id": "ext-1a2b3c4d5e6f7a8b",
    "detail": {"...": "各类型原始结果"}
  }
}
```

字段：`status` = success / skipped（error 走异常 + run 记录）；`skipped_reason`（skipped 时）；`processed_sources`/`skipped_sources`；`created`/`updated`；`warnings`；`model`；`indexed`；`detail`（各类型原始 model_dump）。

**`batch_id`**（#1485）：非 `dry_run` 时形如 `ext-<16 位 hex>`，作为本批**新建**条目的批次标识落库——是回滚与暂存流程的关联键；`dry_run`（预览）恒为 `null`。

### extract rollback（#1485）

`POST /api/v1/projects/{pid}/extractions/rollback`（body `{"batch_id": "ext-..."}`）→ 按批次整批回滚**本批新建**的条目（幂等）：

```json
{"ok": true, "data": {"batch_id": "ext-...", "deleted": 6, "warnings": ["被更新的条目不可回滚（未存快照）"]}}
```

被**更新**的条目未存快照 → 结果 `warnings` 明示不可回滚；项目不存在 → 404。CLI：`extract rollback --project-id <uuid> --batch-id <id>`。

### 暂存（staging）三端点 —— **API / GUI 载体**

> ⚠️ **归属说明**：两段式暂存由 **GUI / HTTP API 驱动**——CLI / MCP **无入口**（`cli/commands/*.py` 无 `stage` 命令，已实证）。§ 以下三端点供 GUI / 直调 HTTP 使用；agent 若在响应里遇到 `staging/{batch_id}` 端点，应知它**不是 CLI 命令**。

| 端点 | 语义 | 返回 |
|---|---|---|
| `GET /api/v1/projects/{pid}/extractions/staging/{batch_id}` | 读取本批暂存条目（空批 → items 空列表，幂等） | `{batch_id, items[]}`，元素含 `entity_type` / `action` / `name` / `payload` |
| `POST /api/v1/projects/{pid}/extractions/staging/{batch_id}/confirm` | 逐行物化进正式表后清空本批暂存（幂等） | `{batch_id, created, updated}` |
| `POST /api/v1/projects/{pid}/extractions/staging/{batch_id}/cancel` | 仅清空暂存行，零物化（幂等） | `{batch_id, deleted}` |

以上三者：项目不存在 → 404（同 rollback 口径）。

### 错误形态示例

```json
{"ok": false, "error": {"code": "NOT_FOUND", "message": "项目不存在: 00000000-0000-0000-0000-0000000000ff"}}
```

## 4. agent 执行建议

1. **一律 `--json`**：人类可读输出不稳定（表格/emoji），JSON 信封是契约。
2. **失败即信封**：`ok: false` 时读 `error.code` 决定重试/纠正（NOT_FOUND → 先 list 拿真实 ID；VALIDATION_ERROR → 检查参数/--force）。
3. **删除前先查**：delete 类命令 `--json` 下缺 `--force` 直接 VALIDATION_ERROR；删除后可用 list 验证。
4. **流式命令**：write 组默认 SSE，勿用普通 JSON 解析器硬解。
5. **异步命令**：audit 触发先拿 `log_id`，再轮询 status / 取明细，勿把 202 受理信封当最终结果。
6. **版本契约**：1.0.0 起 JSON 契约冻结（ADR-019）；字段变更会破坏 agent 生态，本文件与 tests/cli/ 同步维护。
