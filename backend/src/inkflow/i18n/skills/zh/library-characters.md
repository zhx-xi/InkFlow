# 资料库·角色（library-characters.md）

agent 使用：角色 CRUD + 关系 + 分组 + AI 提取。GUI 对应：`/library?cat=characters`（角色列表/创建/关系）+ 角色分组。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `character create` | `--project-id`(UUID) `--name` | `--group-id`(非法 UUID → NOT_FOUND 信封) | 建角色 |
| `character list` | `--project-id` | `--search` `--group-id` `--sort` `--sort-desc` `--offset` `--limit` | 列角色 |
| `character get` | `--id`(UUID) | — | 详情 |
| `character update` | `--id` | `--group-id ""` = **清除分组** | 改角色 |
| `character delete` | `--id` | `--force` `--permanent` | ⚠️ `--json` 无 `--force` → VALIDATION_ERROR（服务不被调用） |
| `character restore` | `--id` | — | 级联恢复双向关系 |
| `character relate` | `--id` `--to` `--type` | `--description` | 建关系 |
| `character unrelate` | `--id` `--relation-id` | `--force` | 删关系 |
| `character relations` | `--id` | — | 双向关系列表 |
| `character extract` | `--project-id` | `--text`/`--text-file` 互斥（同用 exit 2）`--model` | AI 提取角色+关系 |
| `character group create/list/get/update/delete` | 见下 | `--group-id ""` 语义同上 | 分组管理 |

## 易错点

- 所有 id 参数是 UUID；`--group-id ""`（空串）在 update 里 = 清除分组（显式 None 进 model_fields_set）
- `--text` 与 `--text-file` 互斥 → exit 2；都不传 → 空文本 → VALIDATION_ERROR exit 1
- delete 三态：`--force` = 跳过交互确认（≠ 服务层 force）；`--permanent` 才映射硬删；`--json` 无 `--force` 直接短路 VALIDATION_ERROR
