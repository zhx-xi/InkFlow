# 资料库·大纲（library-outline.md）

agent 使用：大纲 + 情节点 + 弧线 CRUD 与 AI 生成。GUI 对应：`/library?cat=outline`（大纲 + 情节点 + 弧线）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `outline create` | `--project-id` `--name` | `--description` `--sort-order` | 建大纲 |
| `outline list` | `--project-id` | `--search` `--sort` `--sort-desc` `--offset` `--limit` | 列大纲 |
| `outline get` | `--id` | — | 详情 |
| `outline update` | `--id` | 可选字段 | 改大纲 |
| `outline delete` | `--id` | `--force/--permanent` | 级联情节点 |
| `outline restore` | `--id` | — | 级联恢复情节点 |
| `outline generate` | `--project-id` | `--prompt`/`--prompt-file` 互斥 `--num-chapters`(1-100) `--save/--no-save`(默认 save) `--model` | AI 生成大纲；人类模式双形态摘要（保存/预览） |
| `outline point list` | `--outline-id` | — | 列情节点 |
| `outline point create` | `--outline-id` `--name` | `--type` `--description` `--position` `--arc-id` | 建情节点 |
| `outline point update` | `--id` | `--arc-id ""` = **清除弧线归属** | 改情节点 |
| `outline point delete` | `--id` | `--force`（软删；point 无 get/restore，#251 P3） | 删情节点 |
| `outline arc list` | `--project-id` | — | 列弧线 |
| `outline arc create` | `--project-id` `--name` | — | 建弧线 |
| `outline arc update` | `--id` | 可选字段 | 改弧线 |
| `outline arc delete` | `--id` | `--force`（成员点置 NULL；arc 无 get/restore，#251 P3） | 删弧线 |

## 易错点

- `point update --arc-id ""` 是透传字符串清除（区别于 character `--group-id ""` → None 的服务层判定）
- point/arc delete 无 `--permanent`（仅 outline 级有）——恒软删
- `outline generate` 无 `--save` 时人类模式输出预览摘要，JSON 输出全量 result
