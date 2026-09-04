# Project Domain (projects.md)

Agent usage: project CRUD and project-level configuration. GUI counterparts: `/projects` project
list page + the top project picker in `/writing` + the agent panel on the settings page
(project-level configuration).

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `project create` | `--name` | `--tags`(repeatable) `--language`(zh-CN) `--target-words` | Create a project (tag-based since #595) |
| `project list` | — | `--search` `--sort`(name\|updated_at\|created_at) | Fixed limit=50; **the main way to get real project UUIDs** |
| `project get` | `--id` | — | Fetch by UUID (`--id <uuid>`; fixed under #251) |
| `project delete` | `--id` | `--force` `--permanent` | Interactive confirm without `--force` (under `--json` pass `--force` first); `--permanent` hard-deletes |
| `project restore` | `--id` | — | Restore a soft-deleted project |
| `project update` | `--id` | `--name` `--tags` `--language` `--target-words` `--config k=v` `--config-json <json>` | Update project fields/config (#251 P1 shipped) |

## Error-prone points

- **`project create/list` return UUIDs** (`id: 00000000-0000-0000-0000-000000000001` shape; seed
  convention: first project = ...0001); `get/delete/restore/update --id` accept UUIDs (the loop is
  closed since the #251 fix — no HTTP workaround needed)
- Downstream `chapter/character/...` need the project UUID: take the `id` field straight from
  `project create/list --json`

## Project config (CLI-editable since 0.8.0; HTTP fallback kept as a spare)

The GUI's project-level config (settings page agent panel: AgentChainCard four-role toggles +
default model; default word count on the writing page) goes through `PATCH /api/v1/projects/{id}`
(body `{"config": {...}}`); **the CLI has no project update command** (#251 P1, to be added in 0.8.0).

Direct HTTP form before 0.8.0:

```powershell
# get port/token
$k = Get-Content "$env:APPDATA\InkFlow\kernel.json" | ConvertFrom-Json
# read current config (GET /api/v1/projects/{id})
$p = Invoke-RestMethod -Uri "http://127.0.0.1:$($k.port)/api/v1/projects/<uuid>" -Headers @{'X-InkFlow-Token'=$k.token}
# change config (#225 tri-state semantics: null=off / "__default__"=follow default / string=specified model)
$body = @{ config = @{ default_model = 'deepseek/deepseek-chat'; agent_roles = @{ writer = '__default__'; auditor = $null } } } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "http://127.0.0.1:$($k.port)/api/v1/projects/<uuid>" -Method Patch -Headers @{'X-InkFlow-Token'=$k.token; 'Content-Type'='application/json'} -Body $body
```

⚠️ config field names (agent_roles/each role key) follow what `GET /api/v1/projects/{id}`
actually returns; PATCH uses exclude_unset merge semantics (keys not passed stay untouched).
