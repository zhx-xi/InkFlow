# 项目域（projects.md）

agent 使用：项目 CRUD 与项目级配置。GUI 对应：`/projects` 项目列表页 + `/writing` 顶部项目选择 + 设置页 agent 面板（项目级配置）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `project create` | `--name` | `--tags`(可重复) `--language`(zh-CN) `--target-words` | 创建项目（标签制，#595 起 genre 并入 tags） |
| `project list` | — | `--search` `--sort`(name\|updated_at\|created_at) | 固定 limit=50；**取真实项目 UUID 的主途径** |
| `project get` | `--id` | — | 按 UUID 查详情（`--id <uuid>`；#251 已修通） |
| `project delete` | `--id` | `--force` `--permanent` | 无 --force 交互确认（--json 下必须先 --force）；--permanent 硬删 |
| `project restore` | `--id` | — | 恢复软删项目 |
| `project update` | `--id` | `--name` `--tags` `--language` `--target-words` `--config k=v` `--config-json <json>` | 项目字段/配置更新（#251 P1 已补） |

## 易错点

- **`project create/list` 返回 UUID**（`id: 00000000-0000-0000-0000-000000000001` 形态，seed 惯例：第一个项目 = ...0001）；`get/delete/restore/update --id` 收 UUID（#251 修复后闭环，无需 HTTP 兜底）
- 下游 `chapter/character/...` 需要项目 UUID：直接取 `project create/list --json` 的 `id` 字段

## 项目 config（0.8.0 起 CLI 直改；HTTP 兜底保留备用）

GUI 的项目级配置（设置页 agent 面板：AgentChainCard 四角色开关 + 默认模型；写作页默认字数）走 `PATCH /api/v1/projects/{id}`（body `{"config": {...}}`）；CLI 侧 `project update --id <uuid> --config k=v` 或 `--config-json '<json>'`（#251 P1 已补）。

HTTP 直调形态（备用）：

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
