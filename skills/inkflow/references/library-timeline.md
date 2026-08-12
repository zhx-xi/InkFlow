# 资料库·时间线（library-timeline.md）

agent 使用：时间线事件 CRUD + 视图/一致性检查。GUI 对应：`/library?cat=timeline`（时间线事件 + 视图/一致性检查）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `timeline create` | `--project-id` `--title` | `--description` `--time-value` `--time-unit` `--time-display` `--narrative-position` `--timeline-flag` | 建事件（create 的 `--time-value` 是 `float\|None`，Typer 自动转换，垃圾输入 exit 2） |
| `timeline list` | `--project-id` | `--search` `--sort` `--sort-desc` | 列事件（无 --offset/--limit） |
| `timeline view` | `--project-id` | — | 线性视图 |
| `timeline check` | `--project-id` | `--include-flashbacks` | 一致性检查 |
| `timeline get` | `--id` | — | 详情 |
| `timeline update` | `--id` | `--time-value`/`--timeline-flag` 是 `str\|None`（`""` = 清除语义，非空值手动 float 转换，ValueError → VALIDATION_ERROR exit 1） | 改事件 |
| `timeline delete` | `--id` | `--force/--permanent` | 删事件 |
| `timeline restore` | `--id` | — | 恢复 |

## 易错点

- **create 与 update 的 `--time-value` 类型不同**：create 是 `float|None`（Typer 转换），update 是 `str|None`（手动 float()，失败 → VALIDATION_ERROR 信封 exit 1）——F12 世代设计
- list 无 --offset/--limit（spec 未列）
- GUI timeline 响应走 `event_timeline` 字段特例（API 层），CLI 解析由客户端处理
