# JSON 契约参考（json-contracts.md）

InkFlow CLI 的 `--json` 输出是 agent 与内核之间的**稳定执行契约**。本文档描述信封结构、退出码与核心命令的返回形态。字段以 `tests/cli/` 契约测试与真实运行为准（变更评审时对照测试）。

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

## 2. 常见错误码

| code | 场景 |
|---|---|
| `NOT_FOUND` | 资源不存在（项目/章节/实体 ID 非法或缺失） |
| `VALIDATION_ERROR` | 参数校验失败（含 `--json` 下删除类命令缺 `--force`） |
| `DB_ERROR` | 数据库/内部错误（含 chapter/volume/write 组非法 UUID） |
| `KERNEL_ERROR` | 内核拉起失败 |
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
  "data": {
    "projects": [
      {"id": "00000000-0000-0000-0000-000000000001", "name": "我的小说", "genre": "玄幻",
       "language": "zh-CN", "target_words": 1000000, "status": "active", "created_at": "...", "updated_at": "..."}
    ],
    "total": 1
  }
}
```

> `id` 字段是下游所有 `--project-id` 参数的来源；不要猜测 UUID。

### project create

```json
{"ok": true, "data": {"id": "...", "name": "我的小说", "genre": "玄幻", "language": "zh-CN", "status": "active"}}
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

### write generate（SSE 流式）

`write generate` 以 **SSE 流**输出（`text/event-stream`），非单次 JSON：

```text
data: {"event": "chunk", "content": "夜色渐深，"}

data: {"event": "done", "chapter_id": 5, "word_count": 3400}
```

事件类型：`chunk`（增量文本）/ `done`（完成，含落库章节 ID）/ `error`（错误信息）。agent 应按事件流逐块消费并拼接 content，收到 `done` 后可用 `chapter get` 验证落库结果。

### audit chapter

```json
{"ok": true, "data": {"report_id": 1, "issues": [{"type": "character_name", "severity": "warning", "message": "..."}], "score": 87}}
```

### extract run

```json
{"ok": true, "data": {"items": [{"type": "character", "name": "林晚", "summary": "...", "chapter_id": 3}], "skipped": 0}}
```

### 错误形态示例

```json
{"ok": false, "error": {"code": "NOT_FOUND", "message": "项目不存在: 00000000-0000-0000-0000-0000000000ff"}}
```

## 4. agent 执行建议

1. **一律 `--json`**：人类可读输出不稳定（表格/emoji），JSON 信封是契约。
2. **失败即信封**：`ok: false` 时读 `error.code` 决定重试/纠正（NOT_FOUND → 先 list 拿真实 ID；VALIDATION_ERROR → 检查参数/--force）。
3. **删除前先查**：delete 类命令 `--json` 下缺 `--force` 直接 VALIDATION_ERROR；删除后可用 list 验证。
4. **流式命令**：write 组默认 SSE，勿用普通 JSON 解析器硬解。
5. **版本契约**：1.0.0 起 JSON 契约冻结（ADR-019）；字段变更会破坏 agent 生态，本文件与 tests/cli/ 同步维护。
