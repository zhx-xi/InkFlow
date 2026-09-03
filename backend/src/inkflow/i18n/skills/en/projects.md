# Project Domain (projects.md)

Agent usage: project CRUD and project-level configuration. GUI counterparts: `/projects` project
list page + the top project picker in `/writing` + the agent panel on the settings page
(project-level configuration).

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `project create` | `--name` | `--genre`(default "其他") `--language`(zh-CN) `--target-words` | Create a project |
| `project list` | — | `--search` `--sort`(name\|updated_at\|created_at) | Fixed limit=50; **the main way to get real project UUIDs** |
| `project get` | `--id` | — | ⚠️ **broken defect**: declared as int while the API only accepts UUIDs — `--id 1` → NOT_FOUND, a UUID → "not a valid int" (recorded 2026-08-11; #251 to fix) |
| `project delete` | `--id` | `--force` `--permanent` | Same breakage; interactive confirm without `--force` (under `--json` pass `--force` first) |
| `project restore` | `--id` | — | Same breakage |

## Error-prone points

- **`project create/list` return UUIDs** (`id: 00000000-0000-0000-0000-000000000001` shape; seed
  convention: first project = ...0001); but `get/delete/restore --id` are declared as int and
  **currently unusable** (int → API 404, UUID → Typer rejects) — for details/deletion use
  `--json project list` + direct HTTP (`DELETE /api/v1/projects/{uuid}` etc.)
- Downstream `chapter/character/...` need the project UUID: take the `id` field straight from
  `project create/list --json`

## Project config (★ version-sensitive: CLI gap before 0.8.0, direct HTTP fallback)

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
