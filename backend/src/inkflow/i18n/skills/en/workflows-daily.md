# Daily Operation Workflow (workflows-daily.md)

Daily end-to-end flows for an agent operating data through the InkFlow CLI: create a project →
write → library maintenance → audit/memory → export. Principle: read when possible, write only
when needed; destructive operations first state a plan.

## Common prerequisites

1. Confirm the data directory: packaged build `%APPDATA%\InkFlow`, dev build `INKFLOW_DATA_DIR`;
   use a dedicated data directory for demos/verification, separate from production data
2. The writing chain needs an LLM key: `llm set-key --provider deepseek --key sk-...` (zhipu for
   embedding); always mask keys
3. Think through the impact before write operations (create/update/delete); confirm delete
   targets with `--json` first

## Create a project

```powershell
project create --name X --json          # returns the project id (UUID); reuse it in later commands
project list --json                     # view the real id/name of existing projects
```

## Writing

```powershell
chapter create --project-id <uuid> --title Chapter 1 --content <≥50 characters> --json
chapter list --project-id <uuid> --status draft
write next --project-id <uuid> --chapter-id <cid> --outline <topic> --min-words 300
write continue --project-id <uuid> --chapter-id <cid> --stream
write revise --project-id <uuid> --chapter-id <cid> --content <revised>
# full writing chain (SSE/draft confirm/agentic): see writing.md
```

## Library maintenance

```powershell
world create --project-id <uuid> --name Worldview --content <content>
character create --project-id <uuid> --name Protagonist --description <description>
map create --project-id <uuid> --name Map --content <description>
timeline create --project-id <uuid> --title Key event --date <time>
foreshadowing create --project-id <uuid> --title Foreshadowing A --content <planted>
outline create --project-id <uuid> --title Outline --content <content>
volume create --project-id <uuid> --name Volume 1
```

## Audit and memory

```powershell
audit check --project <name or UUID>
memory stats --project-id <uuid>        # memory-learning status
extract status --project-id <uuid>      # extraction records
```

## Export and search

```powershell
export export <project name or UUID> --output out.txt   # export the full text
search <keyword> --project <name or UUID>
search --mode semantic <query> --project <name or UUID>
```

## Destructive-operation discipline

- delete class: list to confirm first → `--force` (required in `--json` mode) → list to confirm
  afterwards
- Production data: report the plan first (what to clear, what to keep) before executing; never
  delete projects on your own
- Mask sensitive credentials (keys) at all times

## Common troubleshooting

- "Project not found"-style feedback usually means a guessed UUID (seed UUIDs are independent per
  table; get the real id with `project list --json`) or a soft-deleted project (recycle bin
  `restore`)
- `chapter list` requires an explicit `--status`; a root-level `--json` goes before the
  subcommand
