# System Commands (system.md)

Agent usage: serve / kernel / search / config / llm — kernel and system-level operations.

## serve (core of diagnostic mode)

| Command | Params | Purpose |
|---|---|---|
| `serve` | `--host`(127.0.0.1) `--port`(8000; **0 = dynamic random**) `--port-file` `--token`(random by default) `--open-browser` `--reload` | Start the kernel in the foreground; readiness = stdout `INKFLOW_READY {"port","token","pid","version"}`; **does not write kernel.json** (in diagnostic scenarios parse the INKFLOW_READY line directly); `--reload` mode has no delivery contract |

- **The only reliable stderr source for 500 diagnostics**:
  `serve --port 0 --port-file <f>` + `-RedirectStandardError <err.log>` (a GUI-started kernel has
  no stderr capture)
- Scenarios: troubleshoot kernel 500s / confirm API paths (openapi) / observe request logs

## kernel

| Command | Purpose |
|---|---|
| `kernel status` | Read kernel.json + PID liveness check (no params; prints running/pid/port/version; **never starts the kernel**) |

## search (full-text search)

| Command | Params | Purpose |
|---|---|---|
| `search <query>` | positional query(1-100 chars; may be omitted in `--rebuild` mode); `--project`(repeatable, name or UUID) `--type` `--mode`(keyword\|semantic) `--limit`(20, ≤100) `--offset` `--rebuild`(⚠️ takes only the first project, #251 P3) | Full-text search |

- ⚠️ `search` is a flattened single command (no search search nesting); `--rebuild` supports only
  a single project

## config (local config file, NOT the settings table!)

| Command | Purpose |
|---|---|
| `config show` | Show the 7-key config (default_model/temperature/ratio/window/host/port/data_dir) |
| `config set <key> <value>` | Change config; key must be ∈ CONFIG_WHITELIST; unknown key → exit 2 |

⚠️ **The `config` group ≠ the GUI settings page**: it reads/writes `data_dir/config.json`
(server-side whitelisted config); GUI settings (theme/bg/lang/font/close behavior/tray hints) go
through the `/api/v1/settings` table (no CLI counterpart, exempt under #251 — pure UI
preferences).

## llm (key file management)

| Command | Purpose |
|---|---|
| `llm list` | List providers + key_status (local key files, **not** the provider-configs table) |
| `llm set-key` | `--provider <name> --key <sk-...>` (`--key` param mode; stdin hangs) |

See models.md (provider registry gap and direct HTTP).

## Error-prone points

- `serve --port 0` is a **foreground blocking** command (run it in a background session);
  readiness criterion = the INKFLOW_READY line
- Dev builds' `--version` shows the pyproject version (e.g. v0.1.0), **not the product version** —
  version criteria only apply to packaged artifacts (they show the tag version, PEP 440
  normalized)
