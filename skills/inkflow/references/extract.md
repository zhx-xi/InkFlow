# 统一提取 / 风格 / 导出（extract.md）

agent 使用：零散域合并（均无 GUI 独立页面，GUI 经写作页/资料库间接使用）。

## extract（统一 AI 提取）

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `extract run` | `--project-id` `--type`(character/setting/outline/timeline/foreshadowing/style/knowledge_relation) | `--text`/`--text-file`/`--chapters` 三选一互斥（knowledge_relation 为项目级提取，不接受源参数）；`--prompt` `--num-chapters` `--save/--no-save` `--auto-extract` `--model` `--index` `--force` `--granularity fine\|coarse` `--dry-run` | 提取 7 类型；`--index` 同时入向量库（knowledge_relation 零 LLM、不参与索引）；`--granularity`/`--dry-run` 仅 character/setting 生效（#1485）；返回信封带 `batch_id`（供回滚/暂存关联） |
| `extract status` | `--project-id` | `--type` | 最近提取记录（GUI 资料库 RAG tab 同源） |
| `extract rollback` | `--project-id` `--batch-id` | — | 按批次整批回滚**本批新建**条目（#1485，幂等）；`batch_id` 来自 `extract run` 返回。已被更新的条目未存快照 → 结果 `warnings` 明示不可回滚 |

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
- `extract run` 的 `batch_id` 是回滚与（只读）暂存的关联键；CLI 侧无暂存入口，暂存流程由 GUI/API 驱动（见 json-contracts.md）
- ⚠️ **未注册类别拒绝（#1570）**：setting（世界观）提取经 LLM 产出的类别若**不在项目已注册分类中**，整批**拒绝**并返回可读错误（`VALIDATION_ERROR` / HTTP 422，消息列出全部缺失分类名），**正式表零写入**；两段式暂存路径（`stage:true`）在落暂存前同样拒绝（暂存区零行）。恢复路径 = `world category add --project-id <pid> --name <缺失分类名>` 建类后**重试提取**；**禁止**自动建类（`world copy --auto-create-categories` 是复制路径的用户显式开关，与提取无关）。LLM 主动留空类别不拒绝（维持「未分类」语义）。
