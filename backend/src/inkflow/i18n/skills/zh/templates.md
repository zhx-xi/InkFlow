# Agent 模板管理（templates.md）★版本敏感

agent 使用：Agent 模板 CRUD + 默认模板设置。GUI 对应：`/settings?cat=templates`（TemplatesPanel：Agent 模板 CRUD + 默认模板）。CLI 已全覆盖（#251 P1，0.8.0 补全）。注意：模板是 **Agent 模板**（#107：主模型 + 四角色行=模型/温度/启用开关 + 默认温度/默认字数），**不是章节模板**。

## CLI 能力（DB Agent 模板全量 CRUD）

| 命令 | 说明 |
|---|---|
| `agent template list/get/create/update/delete/duplicate` | DB Agent 模板 CRUD（create/update 用 `--roles-json` 四键 JSON；delete `--force`） |
| `agent template set-default/get-default` | 默认模板设置/查询 |
| `agent template pipelines` | 列**内置 pipeline 模板**（`GET /agent/pipelines/templates`）——与 DB 的 agent_template 表**无关** |

⚠️ 仅 `pipelines` 子命令列管线内置模板（YAML 定义）；其余子命令操作用户在 GUI 创建的 DB Agent 模板。

## HTTP 直调（备用）

```powershell
# 拿 port/token（kernel.json 位置见 kernel.md：打包版 %APPDATA%\InkFlow\kernel.json）
$k = Get-Content "$env:APPDATA\InkFlow\kernel.json" | ConvertFrom-Json
$H = @{'X-InkFlow-Token'=$k.token; 'Content-Type'='application/json'}
$base = "http://127.0.0.1:$($k.port)/api/v1"

# 列表（含被引用数）
Invoke-RestMethod -Uri "$base/agent-templates" -Headers $H

# 创建（roles 四键 architect/writer/auditor/reviser；每角色 {model_id, temperature, enabled}）
Invoke-RestMethod -Uri "$base/agent-templates" -Method Post -Headers $H -Body (@{
  name='模板A'; description='';
  roles=@{ writer=@{model_id='deepseek/deepseek-chat'; temperature=0.7; enabled=$true} };
  default_temperature=0.7; default_words=2000
} | ConvertTo-Json -Depth 5)

# 设默认（body {id: String(id)}——契约要求字符串）
Invoke-RestMethod -Uri "$base/agent-templates/default" -Method Patch -Headers $H -Body (@{id='<uuid>'}|ConvertTo-Json)

# 复制 / 更新 / 删除（duplicate 端点 POST .../duplicate；默认模板删除 → 409）
```

## 易错点

- `PATCH /default` 的 body 是 `{id: "..."}` **字符串 id**（契约明确）
- 被引用模板删除有风险确认（GUI 弹框）；HTTP 直调无确认——删前先看引用数
- 默认模板删除 → 409（保护语义）
