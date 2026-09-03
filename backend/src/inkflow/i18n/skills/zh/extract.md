# 统一提取 / 风格 / 导出（extract.md）

agent 使用：零散域合并（均无 GUI 独立页面，GUI 经写作页/资料库间接使用）。

## extract（统一 AI 提取）

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `extract run` | `--project-id` `--type`(character/setting/outline/timeline/foreshadowing/style) | `--text`/`--text-file`/`--chapters` 三选一互斥；`--prompt` `--num-chapters` `--save/--no-save` `--auto-extract` `--model` `--index` `--force` | 提取 6 类型；`--index` 同时入向量库 |
| `extract status` | `--project-id` | `--type` | 最近提取记录（GUI 资料库 RAG tab 同源） |

## style（风格检测）

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `style analyze` | `--project-id` | `--text`/`--text-file`/`--chapters`(逗号分隔 UUID) 互斥；`--llm-analysis/--no-llm-analysis` | 风格检测；**结论恒退出 0**（分析结果非错误） |

## export（导出）

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `export export` | 位置参数 `project`（数字/UUID/名称三态解析） | `--include-settings` `--output` | 导出项目 TXT；⚠️ False 布尔参数**完全不含该键**（httpx None → 空串 422 缺陷模式 #247/#231） |

## 易错点

- `export` 的 project 位置参数三态解析（数字/UUID/名称）——与 --project-id 语义不同
- `style analyze`/`audit check` 都是「结果非错误」——退出码 0 不代表无问题，判据看输出内容
- `export --include-settings` 不传 = 不含该参数（**不要显式传 False**——#247/#231 缺陷模式：不加 flag 的最常见调用路径曾出 422）
