# Full CLI Command Reference (cli-commands.md)

A quick reference for the full InkFlow CLI command surface (top-level 23 groups + 2 flattened
commands). This file is an **index-level** reference: signatures, parameters, and semantics of
each command; functional-domain details live in the matching `library-*.md` / `writing.md` files.

**Execution contract**: every command supports `--json` (a root-level `--json` goes before the
subcommand); envelopes and exit codes are described in `json-contracts.md`.

## 0. General discipline (read before every run)

| Topic | Rule |
|---|---|
| Project ID | Most `--project-id`/`--id` params accept only **UUIDs**; invalid UUID → NOT_FOUND envelope (exit 1) |
| Tri-state resolution | `export` positional / `audit chapter --project` / `search --project` accept number/UUID/name |
| Exceptions | The `chapter`/`volume`/`write` groups turn invalid UUIDs into ValueError → **DB_ERROR** envelope (semantics differ from other groups) |
| Deletion | Delete commands uniformly support `--force` (soft) / `--permanent` (hard) + interactive confirmation; under `--json` you must pass `--force` explicitly |
| Mutually exclusive input | `--text/--text-file/--chapters` pick one of three (extract/style/character extract/world extract); `--prompt/--prompt-file` (outline generate); using both → exit 2 |
| Status filter | `chapter list` has no default status filter — pass `--status draft` explicitly to see drafts only |
| Data directory | Packaged build `%APPDATA%\InkFlow`; dev build `data/` (relative to the working directory) |
| Kernel | The first command auto-starts the local kernel via `ensure_kernel`; `kernel status` is read-only and does not start it |

## 1. System and kernel

| Command | Purpose |
|---|---|
| `inkflow serve [--port] [--host]` | Start the Web service directly (uvicorn); readiness line `INKFLOW_READY {"port":..,"token":..}` |
| `inkflow kernel status` | Read kernel.json + PID liveness check; prints running/pid/port/version (does not start the kernel) |
| `inkflow config show` / `config set <key> <value>` | View/set system configuration (local config.json; `config set data-dir <path>` writes instance.env) |
| `inkflow llm list` / `llm set-key --provider <p> --key <k>` | LLM provider and key management (local encrypted file) |

## 2. Projects and chapters

| Command | Key params | Purpose |
|---|---|---|
| `project create` | `--name` (required) `--genre` (default "其他") `--language` (zh-CN) `--target-words` | Create a project; returns a UUID |
| `project list` | `--search` `--sort` (name\|updated_at\|created_at) | Fixed limit=50; **the main way to get real project UUIDs** |
| `project get` / `delete` / `restore` | `--id` | ⚠️ `--id` is currently declared as int while the API only accepts UUIDs — unusable in practice; use `project list --json` + direct HTTP for details/deletion (see projects.md) |
| `chapter list` | `--project-id <uuid>` `--status` | No default status filter |
| `chapter get` / `create` / `update` / `delete` | `--project-id` + chapter params | delete needs `--force` |
| `volume list` / `create` / `delete` | `--project-id` | Volume management (no update/restore) |

## 3. AI writing

| Command | Key params | Purpose |
|---|---|---|
| `write generate` | `--project-id` `--chapter-id` `[--prompt]` `[--count]` | Generate a chapter (SSE streaming) |
| `write continue` | `--project-id` `--chapter-id` `--text` | Continue writing |
| `write revise` | `--project-id` `--chapter-id` `--text` | Revise |
| `write next` | `--project-id` `--chapter-id` `[--count]` | deterministic mode defaults to SSE streaming; agentic mode uses non-streaming agent orchestration |

> SSE streaming contract: see writing.md; invalid UUIDs in the `write` group → DB_ERROR.

## 4. Audit and consistency

| Command | Purpose |
|---|---|
| `audit chapter` | Chapter audit (`--project` accepts a name or UUID) |
| `audit check` | Consistency audit (characters/timeline/world/foreshadowing/cross-dimension, `--project-id` UUID) |

## 5. Libraries

| Group | Command shapes | Purpose |
|---|---|---|
| `character` | CRUD + `group` subgroup | Character management (incl. character groups); `character extract` pick-one-of-three |
| `world` | CRUD + `tree` | Worldbuilding management (world tree); `world extract` pick-one-of-three |
| `map` | `pin` subgroup | Map management (map markers) |
| `outline` | `point` + `arc` subgroups + `generate` | Outline management (points/arcs); `generate` uses `--prompt/--prompt-file` |
| `timeline` | CRUD | Timeline management |
| `foreshadowing` | CRUD | Foreshadowing management |
| `vector` | `index` / `status` / `search` / `rebuild` | RAG vector indexing and retrieval |

## 6. Extraction, style, export

| Command | Purpose |
|---|---|
| `extract run` / `extract characters` / `extract world` / `extract outline` etc. (6 types) | Unified extraction entry; `--text/--text-file/--chapters` pick one of three |
| `style analyze` | Style detection (text style fingerprint/AI traces/vocabulary analysis); pick-one-of-three |
| `export book <project>` | Export the project (TXT); positional accepts a name or UUID |

## 7. Agent orchestration

| Command | Purpose |
|---|---|
| `agent tools list` | Enumerate available tools (local static; no kernel needed) |
| `agent runs` | Agent run records |
| `agent draft` | Draft management |
| `agent template` | Agent templates (read-only) |
| `agent validate` | Template/config validation (Phase 1 placeholder) |
| `session list` / `session log` | Session management (`session log` is a subgroup) |
| `memory list` / `memory remove` / `memory stats` | Agent memory management (no manual add/update) |

## 8. Search

| Command | Purpose |
|---|---|
| `inkflow search <query>` | Full-text search (FTS5 lexical + AI semantic); `--project` restricts (name or UUID, repeatable); `--rebuild` manually rebuilds the whole index |

## 9. Known CLI gaps (#251, filling in 0.8.0)

The following have REST API/GUI support but no CLI command yet; use direct HTTP when needed
(fallback examples in system.md / projects.md):
- provider-configs CRUD (`llm` only reads/writes the local key file)
- settings/llm-keys storage, llm/test connection test
- chapters/{id}/summary summaries
- agent-templates write operations (CLI is read-only)
- `project get/delete/restore --id` currently broken
