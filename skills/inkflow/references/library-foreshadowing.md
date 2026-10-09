# 资料库·伏笔（library-foreshadowing.md）

agent 使用：伏笔 CRUD + 揭晓状态机。GUI 对应：`/library?cat=foreshadow`（伏笔 CRUD + 揭晓状态机）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `foreshadowing create` | `--project-id` `--title` | `--description` `--content-file` `--priority`(0-100) `--location` `--event-id` | 埋伏笔 |
| `foreshadowing list` | `--project-id` | `--status`(open\|resolved) `--search` `--sort` `--sort-desc` | 列伏笔 |
| `foreshadowing get` | `--id` | — | 详情 |
| `foreshadowing update` | `--id` | 可选字段；`--event-id ""` 可清除；`--content-file` | 改伏笔 |
| `foreshadowing delete` | `--id` | `--force` | **真删，不可恢复**（v1.1） |
| `foreshadowing resolve` | `--id` | — | 标记已揭晓（状态机 open→resolved） |
| `foreshadowing reopen` | `--id` | — | 重新打开（resolved→open） |

## 易错点

- `--priority` 0-100 范围校验；`--status` 只收 open/resolved
- resolve/reopen 是状态机命令（无 force）
- delete 只有 `--force`（**无 `--permanent`**——那是 project 独有）；**无 `restore` 命令**——真删不可恢复
- 长详情首选 `--content-file`（0.17.0+，显式 UTF-8）
