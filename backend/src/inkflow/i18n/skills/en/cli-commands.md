# Full CLI Command Reference (cli-commands.md)

A quick reference for the full InkFlow CLI command surface (top-level 26 groups + 2 flattened
commands `serve`/`search`). This file is an **index-level** reference: signatures, parameters, and
semantics of each command; functional-domain details live in the matching `library-*.md` /
`writing.md` files. The command surface is authoritative from `inkflow --help` and real runs
(this table synced at 0.13.0, #864).

**Execution contract**: every command supports `--json` (a root-level `--json` goes before the
subcommand); envelopes and exit codes are described in `json-contracts.md`.

## 0. General discipline (read before every run)

| Topic | Rule |
|---|---|
| Project ID | Most `--project-id`/`--id` params accept only **UUIDs**; invalid UUID → NOT_FOUND envelope (exit 1) |
| Tri-state resolution | `export export` positional / `audit chapter chapter --project` / `search --project` accept number/UUID/name |
| Exceptions | The `chapter`/`volume`/`write` groups turn invalid UUIDs into ValueError → **DB_ERROR** envelope (semantics differ from other groups) |
| Deletion | Delete commands uniformly support `--force` (soft) / `--permanent` (hard, project only) + interactive confirmation; under `--json` you must pass `--force` explicitly |
| Mutually exclusive input | `extract run`: `--text/--text-file/--chapters` pick one of three (style/character extract/world extract: text/text-file pick one); `outline generate`: `--prompt/--prompt-file`; using both → exit 2 |
| Status filter | `chapter list` has no default status filter — pass `--status draft` explicitly to see drafts only |
| Data directory | Packaged build `%APPDATA%\InkFlow`; dev build `data/` (relative to the working directory) |
| Kernel | The first command auto-starts the local kernel via `ensure_kernel`; `kernel status` is read-only and does not start it |

## 1. System and kernel

| Command | Purpose |
|---|---|
| `inkflow serve [--port] [--host] [--token] [--port-file] [--reload] [--debug]` | Start the Web service directly (uvicorn); readiness line `INKFLOW_READY {"port":..,"token":..}` |
| `inkflow kernel status` | Read kernel.json + PID liveness check; prints running/pid/port/version (does not start the kernel) |
| `inkflow config show` / `config set <key> <value>` | View/set system configuration (local config.json; `config set data-dir <path>` writes instance.env) |
| `inkflow llm list` | List providers and key-saved status (local encrypted file) |
| `inkflow llm set-key --provider <p> [--key <k>]` / `llm key remove --provider <p>` | Write/remove a provider key |
| `inkflow llm test --provider <p> --api-key <k> [--model] [--base-url]` | Connection test (key used for this request only, never persisted) |
| `inkflow llm provider list/get/create/update/delete/models` | Provider registry CRUD (stored in DB; `--id` takes the numeric DB id; models via `--add/--remove/--set-json`) |

## 2. Projects and chapters

| Command | Key params | Purpose |
|---|---|---|
| `project create` | `--name` (required) `--tags` (repeatable) `--language` (zh-CN) `--target-words` | Create a project, returns a UUID (tag-based: genre merged into tags, #595) |
| `project list` | `--search` `--sort` (name\|updated_at\|created_at) | Fixed limit=50; **the primary way to obtain real project UUIDs** |
| `project get` / `delete` / `restore` / `update` | `--id` (UUID, fixed in #251) | delete supports `--force`/`--permanent`; update supports `--name/--tags/--language/--target-words/--config/--config-json` |
| `chapter list` | `--project-id <uuid>` `--status` | No default status filter |
| `chapter get` / `create` / `update` / `delete` / `move` | `--project-id` + chapter params | delete needs `--force`; move uses `--to-volume` |
| `chapter summary get` / `summary refresh` | `--id <chapter uuid>` | View / regenerate chapter summary |
| `volume list` / `create` / `update` / `delete` | `--project-id` / `--id` | Volume management (update changes title/order) |

## 3. AI writing (write group + book long-range orchestration)

| Command | Key params | Purpose |
|---|---|---|
| `write next` | `--project-id` `--chapter-id` `--outline` (required) `[--context] [--min-words] [--count] [--mode] [--style] [--show-context] [--max-steps] [--token-budget] [--memory-learning/--no-memory-learning]` | Generate the next chapter: deterministic mode streams SSE by default; agentic mode runs the non-streaming agent orchestration (**there is no `write generate` command**) |
| `write continue` | `--project-id` `--chapter-id` `[--target-words] [--context]` | Continue the current chapter (reads stored chapter content, not `--text`) |
| `write revise` | `--project-id` `--chapter-id` `--instruction` (required) `[--range]` | Revise per instruction |
| `book plan start` / `auto` | `<one_liner>` `--project <uuid>` | Long-range writing-plan session (start = interactive / auto = straight-through) |
| `book plan show` / `respond` / `confirm` / `run` | `<session_id or plan_id>` | Advance plan session / answer clarification / confirm / execute plan |
| `book run` | `<plan_id> [--limits k=v,k=v]` | Batch-generate volumes/chapters from a writing plan |
| `book status` / `summary` / `confirm` / `intervene` | `<run_id>` | Batch progress (`--density`) / summary (`--export`) / HITL approval (`--approved/--reject/--decision`) / intervention (`--action/--target/--to/--brief`) |

> SSE streaming contract: see writing.md; invalid UUID in `write` group → DB_ERROR.

## 4. Audit and consistency

| Command | Purpose |
|---|---|
| `audit check --project-id <uuid>` | Consistency audit (character/timeline/world/foreshadowing/cross-dimension; `--include-static`) |
| `audit chapter chapter <chapter> --project <p> [--confirm <issue>] [--note] [--history]` | Chapter audit / confirm / history. ⚠️ the form is nested `audit chapter chapter` (group name equals command name) |

## 5. Library

| Group | Command forms | Purpose |
|---|---|---|
| `character` | CRUD + `group` subgroup + `extract` / `relate` / `relations` / `unrelate` | Character management; create requires `--role-rank`; relate uses `--id --to --type` |
| `world` | CRUD + `categories` / `ancestors <id>` / `descendants <id>` / `copy <src> <tgt> [--root]` / `extract` | Worldbuilding (tree navigation / cross-project copy); extract is text/text-file pick-one |
| `map` | CRUD (create requires `--image`) + `children <map_id>` / `image <map_id> --image` / `pin add/list/update/delete` | Maps & pins (pin requires `--x --y --label`; delete supports `--cascade/--reparent-to`) |
| `outline` | CRUD + `point` / `arc` subgroups + `generate` | Outline tree; `generate` uses `--prompt/--prompt-file --num-chapters --save --model` |
| `timeline` | CRUD + `view` + `check [--include-flashbacks]` | Timeline management and consistency check |
| `foreshadowing` | CRUD + `resolve --id` / `reopen --id` | Foreshadow planting and payoff |
| `knowledge` | `graph <project_id>` / `extract --project [--method]` / `relation add/list/get/update/delete` | Knowledge graph (entity-relation extraction and query) |
| `vector` | `status --project-id` / `reindex --project-id [--type]` / `retrieve --project-id --query [--type --top-k --min-score]` | RAG vector store (**no index/search/rebuild**; the counterparts are reindex/retrieve) |

## 6. Extraction, style, export

| Command | Purpose |
|---|---|
| `extract run --project-id <uuid> --type <character\|setting\|outline\|timeline\|foreshadowing\|style\|knowledge_relation>` | Unified extraction entry (7 types); `--text/--text-file/--chapters` pick one; `--save/--auto-extract/--index/--force/--model` |
| `extract status --project-id [--type]` | Query extraction records |
| `style analyze --project-id` | Style detection (fingerprint / AI traces / vocabulary); `--text/--text-file/--chapters` pick one; `--llm-analysis` adds AI analysis |
| `export export <project> [--include-settings] [-o <path>]` | Export the whole book (CLI is fixed TXT format; other formats via GUI/HTTP); positional accepts name or UUID (**there is no `export book` command**) |

## 7. Agent orchestration, sessions, memory

| Command | Purpose |
|---|---|
| `agent list` / `agent show --id` | Inspect agent chain configuration |
| `agent run --project-id [--chapter-id] [--pipeline builtin:write_chapter] [--var k=v]... [--override] [--watch]` | Execute an agent pipeline (`--watch` still maturing in Phase 2) |
| `agent status --run-id` | Query run status |
| `agent validate --file <yaml>` | Validate a pipeline YAML (⚠️ Phase 1 placeholder — prints a notice, no real validation, #251 P3) |
| `agent tools list` | Enumerate available tools (local static, no kernel needed) |
| `agent runs list --project-id [--limit]` / `runs show <run_id>` | Agent run records |
| `agent draft list --project-id [--status]` / `confirm <draft_id> [--chapter-id]` / `reject <draft_id>` / `prune-orphans [--dry-run]` | Draft confirmation flow |
| `agent template list/get/create/update/delete/duplicate/set-default/get-default/pipelines` | Full DB agent-template CRUD (create/update take `--roles-json` four-key JSON) |
| `session create/list/get/update/pause/resume/complete/fail/logs/delete/restore` | Session lifecycle (create requires `--type --title`; `log add --id -m` subgroup appends logs) |
| `memory list --project-id [--category]` / `remove <preference_id>` / `stats --project-id` / `summarize --project-id [--force|--remove]` / `user-list [--category]` / `user-remove <preference_id>` | Agent memory & preferences (project-level + user-level; no manual add) |
| `context assemble --project-id --chapter-id --model --writing-requirements [--max-tokens]` | Context-assembly preview (four required options) |
| `skills list/verify/install/remove` | File skill-package management (`skills install --builtin` imports the official bundled skill; source is a directory containing SKILL.md) |
| `skill list` | F39 Skill entity view (distinct from the plural `skills` file-import domain; both share data_dir/skills/) |
| `inkflow search <query> [--project <p>] [--type] [--mode semantic] [--limit] [--offset] [--rebuild]` | Full-text search (FTS5 lexical + AI semantic); `--project` name or UUID, repeatable |

## 8. Known CLI discrepancy notes

- The nested `audit chapter chapter` form (group name equals command name) is a historical artifact — do not drop a level when invoking.
- `llm provider --id` takes the **numeric DB id** (from `llm provider list`), not the provider name.
- `agent validate` is a Phase 1 placeholder; `agent run --watch` is not fully implemented.
- `write continue` draws its material from stored chapter content + `--context`; there is no `--text` option (same for `write revise`, which uses `--instruction`).
- Older docs mentioning `write generate` / `export book` / `extract characters|world|outline` / `vector index|search|rebuild` / `project create --genre` are outdated (#864 reconciliation); see the tables above for current forms.
