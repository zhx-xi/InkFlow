# 章节审计/评审（audit.md）

agent 使用：触发章节审计并处理 accept/reject。GUI 对应：`/writing` 工具栏「审计」弹层（AuditDialog accept/reject）。F34 功能。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `audit chapter chapter <章节>` | 位置参数 `chapter`（名称或 UUID） | `--project/-p`（名称或 ID，**非 --project-id**）`--include-static/--no-include-static` `--confirm(accept\|reject)` `--note` `--history` | 触发章节审计并输出结果；`--history` 可省（跳过历史） |
| `audit check` | `--project-id` | — | 4 维一致性审计（项目级）；**发现不一致是结果非错误，退出码恒 0** |

## 易错点

- `--note` 无 `--confirm`、`--confirm` 与 `--history` 同用、非法 confirm 值 → **exit 2**（usage error，不是信封）
- 命令形态是嵌套 `audit chapter chapter`（组名即命令名，历史遗留）；`--project` 参数名是 `--project` 不是 `--project-id`（接受名称或 ID）
- 审计结果 accept/reject 走 `POST /api/v1/projects/{pid}/chapters/{cid}/audit/confirm`（body `{action, note}`）——CLI 由 `--confirm` 触发
