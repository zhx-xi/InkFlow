# 项目域（projects.md）

agent 使用：项目 CRUD 与项目级配置。GUI 对应：`/projects` 项目列表页 + `/writing` 顶部项目选择 + 设置页 agent 面板（项目级配置）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `project create` | `--name` | `--genre`(默认"其他") `--language`(zh-CN) `--target-words` | 创建项目 |
| `project list` | — | `--search` `--sort`(name\|updated_at\|created_at) | 固定 limit=50；**取真实项目 UUID 的主途径** |
| `project get` | `--id` | — | ⚠️ **断裂缺陷**：声明 int，API 只收 UUID——`--id 1` → NOT_FOUND，传 UUID → "not a valid int"（2026-08-11 记录；#251 待修） |
| `project delete` | `--id` | `--force` `--permanent` | 同上断裂；无 --force 交互确认（--json 下必须先 --force） |
| `project restore` | `--id` | — | 同上断裂 |

## 易错点

- **`project create/list` 返回 UUID**（`id: 00000000-0000-0000-0000-000000000001` 形态，seed 惯例：第一个项目 = ...0001）；但 `get/delete/restore --id` 声明 int 且**当前不可用**（int → API 404，UUID → Typer 拒绝）——需要项目详情/删除时用 `--json project list` + HTTP 直调（`DELETE /api/v1/projects/{uuid}` 等）
- 下游 `chapter/character/...` 需要项目 UUID：直接取 `project create/list --json` 的 `id` 字段

## 项目 config（★版本敏感：0.8.0 前 CLI 缺口，HTTP 直调兜底）

GUI 的项目级配置（设置页 agent 面板：AgentChainCard 四角色开关 + 默认模型；写作页默认字数）走 `PATCH /api/v1/projects/{id}`（body `{"config": {...}}`），**CLI 无 project update 命令**（#251 P1，0.8.0 补）。

0.8.0 前 HTTP 直调形态：

```powershell
# 拿 port/token
$k = Get-Content "$env:APPDATA\InkFlow\kernel.json" | ConvertFrom-Json
# 读当前 config（GET /api/v1/projects/{id}）
$p = Invoke-RestMethod -Uri "http://127.0.0.1:$($k.port)/api/v1/projects/<uuid>" -Headers @{'X-InkFlow-Token'=$k.token}
# 改 config（#225 三态语义：null=关闭 / "__default__"=跟随默认 / 字符串=指定模型）
$body = @{ config = @{ default_model = 'deepseek/deepseek-chat'; agent_roles = @{ writer = '__default__'; auditor = $null } } } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "http://127.0.0.1:$($k.port)/api/v1/projects/<uuid>" -Method Patch -Headers @{'X-InkFlow-Token'=$k.token; 'Content-Type'='application/json'} -Body $body
```

⚠️ config 字段名（agent_roles/各角色键）以 `GET /api/v1/projects/{id}` 实际返回为准；PATCH 走 exclude_unset 合并语义（不传的键不动）。
