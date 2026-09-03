# Provider and Model Management (models.md) ★ version-sensitive

Agent usage: provider registry and model management. GUI counterpart: `/models` model management
page (provider CRUD + model add/delete + read-only role binding). **CLI gap** (#251 P1, use HTTP
directly until fixed in 0.8.0).

## Current CLI capability (key file only)

| Command | Purpose |
|---|---|
| `llm list` | List providers + key_status (reads the local encrypted key files under `data_dir/keys/`, **not** the provider-configs table) |
| `llm set-key` | Store an API key: `--provider <name> --key <sk-...>`; stdin piped input hangs; a plaintext `--key` risks shell history |

⚠️ Key difference from the GUI: `llm list` shows key-file status and does **not** include the
provider-configs registry (base_url/default_model/models list) — the GUI `/models` page and CLI
`llm list` see two different things.

## Direct HTTP fallback (before 0.8.0)

```powershell
# get port/token (kernel.json location in kernel.md: packaged build %APPDATA%\InkFlow\kernel.json)
$k = Get-Content "$env:APPDATA\InkFlow\kernel.json" | ConvertFrom-Json
$H = @{'X-InkFlow-Token'=$k.token; 'Content-Type'='application/json'}
$base = "http://127.0.0.1:$($k.port)/api/v1"

# list providers (incl. the model table)
Invoke-RestMethod -Uri "$base/provider-configs" -Headers $H

# add a provider (name required, regex ^[a-z0-9_-]{1,32}$; deleting a seeded openai/deepseek/zhipu/ollama → 409)
Invoke-RestMethod -Uri "$base/provider-configs" -Method Post -Headers $H -Body (@{name='my-provider'; base_url='https://api.example.com'} | ConvertTo-Json)

# model management: PATCH replaces the whole models list (GET existing models first, append, then submit the full list)
Invoke-RestMethod -Uri "$base/provider-configs/<id>" -Method Patch -Headers $H -Body (@{models=@(@{id='deepseek-chat'; type='chat'})} | ConvertTo-Json -Depth 5)

# LLM connection test (same as the GUI ProviderDialog)
Invoke-RestMethod -Uri "$base/settings/llm/test" -Method Post -Headers $H -Body (@{provider='deepseek'; api_key='sk-...'; model='deepseek/deepseek-chat'} | ConvertTo-Json)

# store key (POST /settings/llm-keys, body {provider, api_key})
```

## Error-prone points

- Keys are sensitive credentials: **always mask** (`sk-****0a68`); never write them into any
  doc/skill/log
- `data_dir/keys/` is where keys are stored on disk (plaintext credential files; `llm list`'s
  key_status reads this directory)
- PATCH models is a **whole-list replacement** (#125: the per-row non-stop semantics live in the
  GUI; direct HTTP calls must handle the merge themselves)
