# 资料库·大纲（library-outline.md）

agent 使用：大纲 + 情节点 + 弧线 CRUD 与 AI 生成。GUI 对应：`/library?cat=outline`（大纲 + 情节点 + 弧线）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `outline create` | `--project-id` `--name` | `--description` `--content-file` `--sort-order` | 建大纲 |
| `outline list` | `--project-id` | `--search` `--sort` `--sort-desc` `--offset` `--limit` | 列大纲 |
| `outline get` | `--id` | — | 详情 |
| `outline update` | `--id` | 可选字段；`--content-file` | 改大纲 |
| `outline delete` | `--id` | `--force` | **真删，不可恢复**（v1.1，情节点级联删除） |
| `outline generate` | `--project-id` | `--prompt`/`--prompt-file` 互斥 `--num-chapters`(1-100) `--save/--no-save`(默认 save) `--model` | AI 生成大纲；人类模式双形态摘要（保存/预览） |
| `outline point list` | `--outline-id` | — | 列情节点 |
| `outline point get` | `--id` | — | 情节点详情 |
| `outline point create` | `--outline-id` `--name` | `--type` `--description` `--content-file` `--position` `--arc-id` | 建情节点 |
| `outline point update` | `--id` | `--arc-id ""` = **清除弧线归属**；`--content-file` | 改情节点 |
| `outline point delete` | `--id` | `--force` | **软删**（默认软删除；point 无 restore CLI） |
| `outline arc list` | `--project-id` | — | 列弧线 |
| `outline arc get` | `--id` | — | 弧线详情 |
| `outline arc create` | `--project-id` `--name` | — | 建弧线 |
| `outline arc update` | `--id` | 可选字段 | 改弧线 |
| `outline arc delete` | `--id` | `--force` | 删弧线（成员情节点 `arc_id` 置 NULL，情节点保留） |

## 易错点

- `point update --arc-id ""` 是透传字符串清除（区别于 character `--group-id ""` → None 的服务层判定）
- **所有 delete 只有 `--force`**（无 `--permanent`——那是 project 独有）；**无 `restore` 命令**。`outline delete` 为真删（级联情节点），`point delete` 为默认软删
- `outline generate` 无 `--save` 时人类模式输出预览摘要，JSON 输出全量 result
- 长描述首选 `--content-file`（0.17.0+，显式 UTF-8）
