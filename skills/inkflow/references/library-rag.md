# 资料库·RAG（library-rag.md）

agent 使用：向量索引重建/检索 + 统一 AI 提取记录。GUI 对应：`/library?cat=rag`（RAG 抽取记录 + 检索；RAG 分类无创建端点，GUI CTA 跳 /writing）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `vector reindex` | `--project-id` | `--entity-types`(可重复) | 重建向量索引（GUI 无此入口） |
| `vector retrieve` | `--project-id` `--query` | `--entity-types` `--top-k`(10) `--min-score`(0.0) | 向量检索 |
| `extract run` | `--project-id` `--type`(character/setting/outline/timeline/foreshadowing/style) | `--text`/`--text-file`/`--chapters` **三选一互斥** `--prompt` `--num-chapters` `--save/--no-save` `--auto-extract` `--model` `--index` `--force` | 统一 AI 提取（6 类型） |
| `extract status` | `--project-id` | `--type` 过滤 | 最近提取记录（GUI 的 extractions/runs 对应） |

## 易错点

- `extract run` 的 `--text`/`--text-file`/`--chapters` 是三选一互斥（比 character/world 的 --text/--text-file 多一个 --chapters 形态）；`--chapters` 逗号分隔 UUID
- 非法 `--type` → 退出码 2（typer 0.27 枚举注解实证）
- `vector retrieve` 的 min-score 0.0 默认 = 不过滤；检索前先 `vector reindex`（新数据默认不自动索引，除非 extract `--index`）
