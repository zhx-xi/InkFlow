# 资料库·时间线（library-timeline.md）

agent 使用：时间线事件 CRUD + 视图/一致性检查。GUI 对应：`/library?cat=timeline`（时间线事件 + 视图/一致性检查）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `timeline create` | `--project-id` `--title` | `--description` `--content-file` `--time-value` `--time-unit` `--time-display` `--narrative-position` `--timeline-flag` `--era` `--era-value` `--era-scale` | 建事件（create 的 `--time-value` 是 `float\|None`，Typer 自动转换，垃圾输入 exit 2） |
| `timeline list` | `--project-id` | `--search` `--sort` `--sort-desc` | 列事件（无 --offset/--limit） |
| `timeline view` | `--project-id` | — | 线性视图 |
| `timeline check` | `--project-id` | `--include-flashbacks` | 一致性检查 |
| `timeline normalize` | `--project-id` | `--apply`（缺省 dry-run 只报计划） | 归一/重锚（段内计数器型历史数据 → 项目时基） |
| `timeline get` | `--id` | — | 详情 |
| `timeline update` | `--id` | `--time-value`/`--timeline-flag` 是 `str\|None`（`""` = 清除语义，非空值手动 float 转换，ValueError → VALIDATION_ERROR exit 1）；`--content-file`；`--era`/`--era-value`/`--era-scale` | 改事件 |
| `timeline delete` | `--id` | `--force` | **真删，不可恢复**（v1.1） |

## 纪元轴（#1353 / #1411）

`create`/`update` 支持三列：

| 参数 | 语义 |
|---|---|
| `--era <名>` | 纪元轴名（缺省不设；`""` = 清除） |
| `--era-value <值>` | 纪元轴内值（数值；`""` = 清除轴内值） |
| `--era-scale <比>` | 流速比（#1411 §2.8 E11；默认 1.0 = 与项目时基同速，须为正数） |

## 易错点

- **create 与 update 的 `--time-value` 类型不同**：create 是 `float|None`（Typer 转换），update 是 `str|None`（手动 float()，失败 → VALIDATION_ERROR 信封 exit 1）——F12 世代设计
- list 无 --offset/--limit（spec 未列）
- **无 `restore` 命令**：`timeline delete` 是真删（不可恢复），无 `--permanent` 之分
- GUI timeline 响应走 `event_timeline` 字段特例（API 层），CLI 解析由客户端处理
