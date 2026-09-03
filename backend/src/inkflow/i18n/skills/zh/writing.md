# 写作链路（writing.md）

agent 使用：AI 生成/续写/修订章节。GUI 对应：`/writing` 编辑器工具栏（生成/续写/修订，SSE 流式）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `write next` | `--project-id` `--chapter-id` `--outline` | `--context` `--min-words`(2000) `--style` `--count`(1) `--mode`(deterministic\|agentic，默认 deterministic) `--memory-learning` `--max-steps` `--token-budget` | 按大纲生成章节；deterministic 走 SSE `/writing/stream`；agentic 走非流式 `/writing/agentic/generate` |
| `write continue` | `--project-id` `--chapter-id` | `--target-words`(2000) `--context` | 续写；原文章节经 HTTP 取回；**existing_content ≥ 50 字符校验**（章节太短 → 422） |
| `write revise` | `--project-id` `--chapter-id` `--instruction` | `--range`(如"第3段") | 修订 |

## 关键点

- **模型显式指定**：请求须带 `"model": "provider/model_name"`（如 `deepseek/deepseek-chat`）；不传回退 `gpt-4o` → `Invalid model format` 500（0.6.0 记录）。CLI 命令无 `--model` 参数时靠项目 config 的 model 字段（`project create` 默认 gpt-4o）；或用 `INKFLOW_LLM_DEFAULT_MODEL` env 覆盖（AppConfig env_prefix=INKFLOW_）
- **成功判据**：响应含 `content`（真实生成正文）、`word_count`、`format_valid: true`、`token_usage`
- **`write continue` 只返回不写回章节**（GUI 点「应用」才合并）——章节 word_count 不变是设计行为，非缺陷
- **无 key 失败信封**（2026-08-11 记录）：`{"ok":false,"error":{"code":"INTERNAL_ERROR","message":""}}`——**message 为空**，无法从信封判断根因；诊断必须看内核 stderr（`serve --port 0` 前台 + `-RedirectStandardError`）
- 失败诊断三步：① openapi 确认路径 ② serve 前台拿 stderr traceback ③ 检查模型解析路径 + key 注入
- SSE 流式响应在 CLI 是聚合后输出（非逐 token）——判据看最终信封
