# Agent 链与会话（agent.md）

agent 使用：Agent 管线执行与运行记录、草稿确认/拒绝、会话生命周期。GUI 对应：`/settings?cat=agent`（AgentChainCard 四角色开关——见 projects.md 的 config 直调）+ Agent 运行记录 + `/writing` Agent 链卡片。项目级 Agent 配置 = `project config`（#251 P1）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `agent run` | `--project-id` | `--chapter-id` `--pipeline`(默认 builtin:write_chapter) `--var`(可重复 key=value) `--override` `--watch` | 执行 Agent 管线 |
| `agent status` | `--run-id` | — | 执行记录详情 |
| `agent validate` | `--file` | ⚠️ **Phase 1 占位**——只打印"将在 Phase 2 实现"，无实际校验（#251 P3） | 校验管线 YAML |
| `agent template` | — | `--json` | 列内置管线模板（非 DB Agent 模板，见 templates.md） |
| `agent tools list` | — | `--json` | 列只读工具（本地静态枚举 TOOL_REGISTRY） |
| `agent runs list` | `--project-id` | `--limit`(20) | 运行记录列表 |
| `agent runs show` | 位置参数 `run-id` | — | 运行记录详情 |
| `agent draft list` | `--project-id` | `--status`(draft\|confirmed\|rejected) | 草稿列表 |
| `agent draft confirm` | 位置参数 `draft-id` | `--chapter-id`(草稿未绑定时) | 确认草稿（GUI「应用」同语义） |
| `agent draft reject` | 位置参数 `draft-id` | — | 拒绝草稿 |

## 会话（session）

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `session create` | `--type`(writing\|task) `--title` | `--project-id` `--description` `--context-json`/`--context-file`(互斥) | 建会话 |
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
- `agent validate` 是占位命令（不要依赖其校验结果）
- 会话归档语义：delete 默认软删（restore 可恢复），`--force` 硬删
