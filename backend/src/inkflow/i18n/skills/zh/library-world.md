# 资料库·世界观（library-world.md）

agent 使用：世界观条目 + 分类 + 树形结构 + 跨项目复制。GUI 对应：`/library?cat=world`（世界观条目 + 分类 + 树形）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `world create` | `--project-id` `--name` | `--category` `--content` `--parent`(父条目 UUID，缺省顶层) | 建条目 |
| `world list` | `--project-id` | `--search` `--category` `--sort` `--offset` `--limit` | 列条目 |
| `world categories` | `--project-id` | — | 类别聚合（JSON 输出 `[{category, count}]`） |
| `world get` | `--id` | — | 详情 |
| `world ancestors` | `--id` | — | 祖先链 |
| `world descendants` | `--id`（位置参数） | — | 子孙树 |
| `world copy` | 位置参数 `source-project-id` `target-project-id` | `--root`(复制起点，缺省整棵) | 跨项目复制条目树 |
| `world update` | `--id` | 可选字段；`--parent` 可改挂；`--category ""` = 普通字符串直接进 DTO（非清空语义） | 改条目 |
| `world delete` | `--id` | `--force/--permanent/--cascade/--reparent-to` | F35 子树语义 |
| `world restore` | `--id` | — | 恢复 |
| `world extract` | `--project-id` | `--text`/`--text-file` 互斥 `--model` | AI 提取世界观 |

## 易错点

- `world descendants` 的 id 是**位置参数**（非 `--id`）
- `--category ""` 与 `character --group-id ""` 语义不同（后者转 None 清除，前者透传字符串）——按 DTO 语义区分
- `world copy` 两个 project-id 都是位置参数
