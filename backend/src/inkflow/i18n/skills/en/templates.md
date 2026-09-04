# Agent Template Management (templates.md) ★ version-sensitive

Agent usage: Agent template CRUD + default template setting. GUI counterpart:
`/settings?cat=templates` (TemplatesPanel: Agent template CRUD + default template). The CLI
covers it fully (#251 P1, shipped in 0.8.0). Note: these are **Agent templates** (#107: main model +
four role rows = model/temperature/enabled toggle + default temperature/default word count),
**not chapter templates**.

## CLI capability (full DB agent-template CRUD)

| Command | Purpose |
|---|---|
| `agent template list/get/create/update/delete/duplicate` | DB agent-template CRUD (create/update take `--roles-json` four-key JSON; delete `--force`) |
| `agent template set-default/get-default` | Default-template set/query |
| `agent template pipelines` | List **built-in pipeline templates** (`GET /agent/pipelines/templates`) — **unrelated** to the DB agent_template table |

⚠️ Only the `pipelines` subcommand lists built-in pipeline templates (YAML definitions); the
other subcommands operate on the DB Agent templates users create in the GUI.

## Direct HTTP (spare)

```powershell
# get port/token (kernel.json location in kernel.md: packaged build %APPDATA%\InkFlow\kernel.json)
$k = Get-Content "$env:APPDATA\InkFlow\kernel.json" | ConvertFrom-Json
$H = @{'X-InkFlow-Token'=$k.token; 'Content-Type'='application/json'}
$base = "http://127.0.0.1:$($k.port)/api/v1"

# list (incl. reference counts)
Invoke-RestMethod -Uri "$base/agent-templates" -Headers $H

# create (roles has four keys architect/writer/auditor/reviser; each role {model_id, temperature, enabled})
Invoke-RestMethod -Uri "$base/agent-templates" -Method Post -Headers $H -Body (@{
  name='Template A'; description='';
  roles=@{ writer=@{model_id='deepseek/deepseek-chat'; temperature=0.7; enabled=$true} };
  default_temperature=0.7; default_words=2000
} | ConvertTo-Json -Depth 5)

# set default (body {id: String(id)} — the contract requires a string)
Invoke-RestMethod -Uri "$base/agent-templates/default" -Method Patch -Headers $H -Body (@{id='<uuid>'}|ConvertTo-Json)

# duplicate / update / delete (duplicate endpoint POST .../duplicate; deleting the default template → 409)
```

## Error-prone points

- `PATCH /default`'s body is `{id: "..."}` with a **string id** (explicit contract)
- Deleting a referenced template has a risky confirmation in the GUI; direct HTTP has no
  confirmation — check the reference count before deleting
- Deleting the default template → 409 (protection semantics)
