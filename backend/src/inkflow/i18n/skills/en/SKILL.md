---
name: inkflow
description: "Operate the InkFlow local AI novel-writing kernel and CLI: project/chapter/volume management, AI writing generation and continuation, chapter audit, character/worldbuilding/outline/timeline/foreshadowing/RAG libraries, LLM model configuration, agent chain orchestration, export and extraction. Trigger: when an agent needs to create or manage novel projects for InkFlow users, invoke AI writing, operate library data, view model configuration, or verify operation results."
version: 0.8.0
license: MIT
compatibility: InkFlow >= 0.8.0
metadata:
  hermes:
    source: https://github.com/zhx-xi/InkFlow/tree/main/skills/inkflow
---

# InkFlow Operation Guide (CLI / kernel)

InkFlow is a local AI-assisted novel-writing tool (a single-machine application). This skill is
the official InkFlow usage guide for external AI agents: an agent interacts with the InkFlow
kernel through the `inkflow` CLI to create projects, write chapters, maintain libraries, and so on.

**Execution contract**: every command supports `--json` output — `inkflow <cmd> --json` returns
a stable JSON envelope (see `json-contracts.md`), which is the reliable channel between an agent
and the kernel. Always run commands in the `--json` form and parse the envelope; never rely on
human-readable output.

## How to use after installation (three-step start)

1. **Probe**: `inkflow --version` confirms the CLI works; `inkflow --help` lists all command
   groups (23 groups)
2. **Discover**: `inkflow project list --json` lists the user's existing projects (get the real
   UUID — never guess UUIDs; under the seed convention the first project is
   `00000000-0000-0000-0000-000000000001`, but always trust what list returns)
3. **Walk through** (journey C: agent-assisted writing loop):
   - `inkflow project list --json` → pick a project UUID
   - `inkflow chapter list --project-id <uuid> --json` → discover chapters
   - `inkflow write generate --project-id <uuid> --chapter-id <cid> --json` → generate a chapter
   - `inkflow audit chapter --project <uuid> --json` → trigger an audit
   - Write results back: `inkflow write continue --project-id <uuid> --chapter-id <cid> --text "..." --json`

## Core execution discipline (read before every operation)

1. **`--json` position**: a root-level `--json` must come **before** the subcommand
   (`inkflow --json project list`); `--json` inside a subcommand follows each command's help.
2. **Envelope**: success is `{"ok": true, "data": ...}`; failure is
   `{"ok": false, "error": {"code", "message"}}`; exit codes 0 (success) / 1 (business error) /
   2 (usage error) / 130 (Ctrl+C).
3. **Project ID semantics**: the `character/world/outline/timeline/foreshadowing/chapter/volume/write`
   groups use `--project-id` and only accept **UUID strings**; `export`/`audit chapter --project`/
   `search --project` accept a name or a UUID.
4. **Data directory**: packaged builds store data under `%APPDATA%\InkFlow` (Windows); dev builds
   use `data` under the working directory. The first command automatically starts the local kernel
   (`ensure_kernel`); no manual startup is needed.
5. **Read-only first**: before mutating user data (delete/overwrite), list to confirm the target;
   watch the `--force` semantics on delete commands (without `--force` an interactive confirmation
   runs; under `--json` you must pass `--force` explicitly).

## Command surface overview (23 groups)

| Group | Purpose | Reference |
|---|---|---|
| `project` | Project creation/listing/deletion | `projects.md` |
| `chapter` / `volume` | Chapter and volume management | `chapters.md` |
| `write` | AI generate/continue/revise (SSE streaming) | `writing.md` |
| `audit` | Chapter audit/review | `audit.md` |
| `character` / `world` / `outline` / `timeline` / `foreshadowing` / `map` | Libraries | `library-*.md` |
| `vector` | RAG vector library | `library-rag.md` |
| `extract` | Unified extraction (characters/worldbuilding/outline) | `extract.md` |
| `export` | Book export | `cli-commands.md` §6 |
| `style` | Writing style management | `cli-commands.md` §6 |
| `agent` / `session` / `memory` | Agent chains/sessions/project memory | `agent.md` / `memory.md` |
| `models` / `config` / `llm` | Providers/models/configuration | `models.md` / `system.md` |
| `template` (agent templates) | Template management | `templates.md` |
| `search` | Full-text search | `system.md` |
| `kernel` / `serve` | Kernel lifecycle | `kernel.md` / `system.md` |

> Full signatures and examples for all 23 groups are in `cli-commands.md`; the JSON envelope
> contract is in `json-contracts.md`.

## File index

| Task | Read |
|---|---|
| How the kernel starts/is discovered/health checks | `references/kernel.md` |
| Create/query/delete projects | `references/projects.md` |
| Chapter/volume operations | `references/chapters.md` |
| Generate/continue/revise (SSE) | `references/writing.md` |
| Chapter audit/review | `references/audit.md` |
| Characters/worldbuilding/outline/timeline/foreshadowing/RAG | `references/library-*.md` |
| Provider/model/key configuration | `references/models.md` |
| Agent templates/chains/sessions/memory | `references/templates.md` / `agent.md` / `memory.md` |
| Export/style | `references/cli-commands.md` (§6) |
| serve/kernel/search/config/llm system commands | `references/system.md` |
| Full command reference and JSON contract | `references/cli-commands.md` / `json-contracts.md` |

## Common workflows

- **Create a project and write**: `project create --name <N> --genre <G>` → take the UUID →
  `write generate` to create the first chapter → `chapter list` to confirm
- **Library maintenance**: bulk-load library commands such as
  `character create --project-id <uuid> --name <N>`, keeping `world`/`outline` in sync
- **Batch extraction**: `extract characters --project-id <uuid> --chapter-id <cid>` extracts
  settings from a chapter
- **Export**: `export book --project-id <uuid> --format md` exports the whole book

## Version

This skill is aligned with the InkFlow version (frontmatter version = InkFlow version). If the
command surface differs, `inkflow --help` and real runs take precedence.

## MCP

InkFlow provides an MCP Server (`inkflow-mcp`, a thin client that connects to the resident kernel
over HTTP): when the host supports MCP, prefer structured calls; the tool set corresponds 1:1 to
CLI semantics. Integration guidance (three client forms + Claude/Cursor/Hermes config templates +
usage policy) is in `references/mcp-setup.md`; fall back to the CLI `--json` execution contract for
unsupported scenarios.
