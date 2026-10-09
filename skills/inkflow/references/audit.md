# 章节审计/评审（audit.md）

agent 使用：触发章节审计并处理 accept/reject。GUI 对应：`/writing` 工具栏「审计」弹层（AuditDialog accept/reject）。F34 功能。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `audit chapter chapter <章节>` | 位置参数 `chapter`（名称或 UUID） | `--project/-p`（名称或 ID，**非 --project-id**）`--include-static/--no-include-static` `--wait/--no-wait` `--confirm(accept\|reject)` `--note` `--history` `--log <log_id>` | 触发章节审计 / 确认 / 查历史 / 按记录 ID 取明细。**202 异步受理**（详见下） |
| `audit check` | `--project-id` | — | 4 维一致性审计（项目级）；**发现不一致是结果非错误，退出码恒 0** |
| `audit batch` | `--project-id/-p` | `--chapters <区间>` `--resume` `--concurrency <n>` `--out <path>` | 批量章节审计（#1484）；见下 |

## 异步语义（#1425）

`audit chapter` 触发走 `POST /api/v1/projects/{pid}/chapters/{cid}/audit` → **202** 返回 `{log_id, status}`（**不是**完整报告）。

- 默认 `--wait`：CLI 阻塞轮询 `GET /api/v1/audit-logs/{log_id}/status`（`run_status`：running/completed/failed）直到终态，再取回明细输出；超总预算 → `TIMEOUT` 信封 + 退出 1。
- `--no-wait`：立即返回 `{log_id, status}`，由调用方自行稍后 `--log <log_id>` 取回。
- 取明细：`--log <log_id>`（`GET /api/v1/audit-logs/{log_id}`，含 findings）。

> ⚠️ 旧版文档写「`audit chapter` 直接返回完整报告 `{report_id, issues, score}`」——**已过期**，现为 202 受理 + 轮询（见 json-contracts.md §audit）。

## 批量审计（audit batch，#1484）

| 参数 | 语义 |
|---|---|
| `--chapters <区间>` | **1-based 序号区间**（如 `1-520` / `1-5,8,10-12`；省略 = 全部章节） |
| `--resume` | 断点续跑：跳过 audit_logs 中 `run_status=completed` 的章节 |
| `--concurrency <n>` | 并发章数（默认 1 = 串行，LLM 限流友好；< 1 → exit 2） |
| `--out <path>` | 报告落点（Markdown；JSON 写同主名 `.json`；省略 = 只打印 stdout） |

单章失败**不中断整批**（记入报告失败清单，退出码仍 0）；批次级错误退出 1；用法错误退出 2。

## 易错点

- `--note` 无 `--confirm`、`--confirm` 与 `--history` 同用、非法 confirm 值 → **exit 2**（usage error，不是信封）
- `--log` 不能与 章节参数 / `--confirm` / `--history` 同用（exit 2）
- 命令形态是嵌套 `audit chapter chapter`（组名即命令名，历史遗留）；`--project` 参数名是 `--project` 不是 `--project-id`（接受名称或 ID）
- 审计结果 accept/reject 走 `POST /api/v1/projects/{pid}/chapters/{cid}/audit/confirm`（body `{action, note}`）——CLI 由 `--confirm` 触发
