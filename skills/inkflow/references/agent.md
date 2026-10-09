# Agent 链与会话（agent.md）

agent 使用：Agent 管线执行与运行记录、草稿确认/拒绝、会话生命周期。GUI 对应：`/settings?cat=agent`（AgentChainCard 四角色开关——见 projects.md 的 config 直调）+ Agent 运行记录 + `/writing` Agent 链卡片。项目级 Agent 配置 = `project config`（#251 P1）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `agent run` | `--project-id` | `--chapter-id` `--pipeline`(默认 builtin:write_chapter) `--var`(可重复 key=value) `--override`(可重复 role.field=value) `--watch` `--watch-timeout`(秒) | 执行 Agent 管线 |
| `agent status` | `--run-id` | `--json` | 执行记录详情（`--json` 输出执行记录信封） |
| `agent validate` | `--file` | — | 校验管线 YAML（读 YAML → `POST /agent/pipelines/validate`；**已实装**，非占位） |
| `agent template` | — | `--json` | 列内置管线模板（非 DB Agent 模板，见 templates.md） |
| `agent tools list` | — | `--json` | 列只读工具（本地静态枚举 TOOL_REGISTRY） |
| `agent runs list` | `--project-id` | `--limit`(20) | 运行记录列表 |
| `agent runs show` | 位置参数 `run-id` | — | 运行记录详情 |
| `agent draft list` | `--project-id` | `--status`(draft\|confirmed\|rejected) | 草稿列表 |
| `agent draft confirm` | 位置参数 `draft-id` | `--chapter-id`(草稿未绑定时) | 确认草稿（GUI「应用」同语义） |
| `agent draft reject` | 位置参数 `draft-id` | — | 拒绝草稿 |
| `agent draft delete` | 位置参数 `draft-id` | — | **硬删**草稿（真删，不可恢复；#1479 清理出口） |
| `agent draft prune-orphans` | — | `--dry-run` | 清理孤儿草稿（所属项目不存在/已软删） |

### `agent run --watch`（#1478 已完整实现）

- `--watch`：阻塞轮询执行直到终态（**指数退避**），无需手动 `agent status` 轮询。
- `--watch-timeout <秒>`：`--watch` 总超时；超时 → `WATCH_TIMEOUT` 信封（消息含 execution_id 与后续查询指引），**不会**无限等待。

### `agent run --pipeline` 三形态（#1475）

| 取值形态 | 语义 |
|---|---|
| `builtin:<id>` | 内置模板 id（默认 `builtin:write_chapter`；请求体不带自定义载荷） |
| `<file>.yaml` / `.yml` / 存在的文件 | 本地读 YAML → `PipelineConfig`（本地校验，失败即退出 1） |
| 逗号分隔 role_key 序列 | 自定义 stages（如 `outline,write,review`） |

## 会话（session）

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `session create` | `--type`(writing\|task) `--title` | `--project-id` `--description` `--content-file` `--context-json`/`--context-file`(互斥) | 建会话 |
| `session list` | — | `--type` `--status` `--project-id` `--search` `--limit`(50) `--offset` | 列会话 |
| `session get` | `--id` | — | 详情 |
| `session update` | `--id` | 可选字段 | 改会话 |
| `session pause/resume` | `--id` | — | 状态机 active↔paused |
| `session complete` | `--id` | `--result-json` | 完成 |
| `session fail` | `--id` `--error` | — | 失败 |
| `session logs` | `--id` | `--limit/--offset` | 日志列表 |
| `session log add` | `--id` `--message` | `--level`(info\|warning\|error) `--payload-json` | 追加日志 |
| `session delete` | `--id` | ⚠️ 两级：默认归档可恢复；`--force` 直删 | 删会话 |
| `session restore` | `--id` | — | 解除归档 |

## 易错点

- agent/session 组位置参数（run-id/draft-id）与 `--id` 并存，看命令具体形态
- `agent run --watch` 已完整实现（指数退避 + `--watch-timeout`），不必再手写轮询循环
- 会话归档语义：delete 默认软删（restore 可恢复），`--force` 硬删
