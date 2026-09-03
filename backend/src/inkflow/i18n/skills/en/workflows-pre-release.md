# Functional Validation Scenario Guide (workflows-pre-release.md)

End-to-end functional validation of a new CLI artifact (stable/rc). Green unit tests/CI ≠ truly
usable — validation must run real CLI command chains against user scenarios.

## Validation layering

The CLI and GUI share the same kernel HTTP API (GUI = thin shell + rendering layer; all business
logic lives in the backend): **everything the GUI has the CLI has too, but not vice versa**.
Validating the CLI covers the core functionality; the GUI gate only checks start/health/version,
and interactive operations are left to user re-verification.

## Prerequisites

- New artifact ready (CLI zip extracted)
- **Dedicated data directory**: `%APPDATA%` (packaged) or `INKFLOW_DATA_DIR` (dev) pointing to a
  temp dir = fresh DB; last validation's projects/chapters do not exist — don't misjudge them as
  defects; don't pollute production data
- LLM keys: `llm set-key --provider deepseek --key sk-...`,
  `llm set-key --provider zhipu --key ...` (embedding); always mask

## Assertion norms

Scenario scripts assert each step automatically — no manual walk-through:

1. **JSON envelope**: `--json` output contains `"ok":true` (failure = exit 1 + `ok:false` →
   mark FAIL immediately and stop)
2. **Key fields**: create returns a non-empty UUID; list contains the just-created entry; update
   reads back consistently; after delete, list no longer contains it
3. **LLM chain**: content non-empty, `word_count > 0`, `format_valid: true`, `token_usage`
   present; agentic returns an agent_run record (steps/tool_calls)
4. **SSE**: first frame <2s, frame shape (data: JSON), no mid-stream error frames
5. **Fail-fast + snapshot**: on FAIL, save that step's full output to a log file and report the
   root-cause direction
6. **Idempotency**: clean up before rerunning (new data dir or delete created projects)

## Scenario matrix (must run A/B/C/D before release)

| Scenario | Type | Journey | Domains covered | Data dependency |
|------|------|------|--------|----------|
| **A New author starts a book** | user thinking | create project→configure AI→settings library (world/character/map/timeline/foreshadowing)→outline→volume/chapter→generate/continue/revise→agentic→draft confirm→extract→audit→style→export/search | F1-F3,F5,F6,F9-F16,F21-F23,F26,F27,F30,F32,RAG | isolated (seed scenario) |
| **B Veteran author continues and maintains** | user thinking | chapter status flow→continue/revise→fix audit contradictions→timeline/foreshadowing maintenance→session delete→recycle-bin restore→audit log→export backup | F1,F2,F12-F15,F21,F24,F27,F28 | **inherits A's project** |
| **C Full-domain sweep** | engineering backstop | shortest-path CRUD for every command group + system commands + HTTP direct calls for gap domains | all domains + system surface | isolated project (no pollution of A/B/D data) |
| **D AI deep workflow** | product thinking | agentic tool chain→draft confirm→preference learning (N≥2)→semantic RAG→context injection→memory remove takes effect immediately | F26-F28,RAG,F6 | **reuses A's project** |

Run order **A → B → C → D** (serial, sharing one data dir; A/B/D data flow onward, C isolated).

## Scenario A "New author starts a new book" (full journey)

```powershell
# 1. project + AI config
project create --name verify --json
llm set-key --provider deepseek --key sk-****
llm set-key --provider zhipu --key 8a31****ZG3M   # embedding
# 2. settings library groundwork
world create --project-id <uuid> --name Worldview --content <content>
character create --project-id <uuid> --name Protagonist --description <description>
character create --project-id <uuid> --name Side character --description <description>
map create --project-id <uuid> --name Map --content <description>
timeline create --project-id <uuid> --title Key event --date <time>
foreshadowing create --project-id <uuid> --title Foreshadowing A --content <planted>
# 3. outline → volume/chapter
outline create --project-id <uuid> --title Outline --content <content>
volume create --project-id <uuid> --name Volume 1
chapter create --project-id <uuid> --title Chapter 1 --content <≥50 chars>
# 4. writing chain (generate→SSE→revise)
write next --project-id <uuid> --chapter-id <cid> --outline <topic> --min-words 300
write continue --project-id <uuid> --chapter-id <cid> --stream   # SSE frames, first token ≤2s
write revise --project-id <uuid> --chapter-id <cid> --content <revised> --model deepseek/deepseek-v4-flash
# 5. agentic + draft confirm
write next --mode agentic --project-id <uuid> --chapter-id <cid> --outline <topic> --min-words 300
#   draft confirm flow → chapter final (contract in writing.md)
# 6. extraction (real AI)
extract run --project-id <uuid> --types character,world
extract status --run-id <id>
# 7. audit + style
audit check --project <name or UUID>
style analyze --project-id <uuid>
# 8. export + search (keyword + semantic)
export export <name or UUID>
search <keyword> --project <name or UUID>
search --mode semantic <query> --project <name or UUID>   # real embedding call
# 9. memory stats
memory stats --project-id <uuid>
```

## Scenario B "Veteran author continues and maintains"

```powershell
# 1. project/chapter status flow
project list
chapter list --project-id <uuid> --status draft   # explicit --status
chapter update --id <cid> --status writing
# 2. continue + revise (explicit model)
write continue --project-id <uuid> --chapter-id <cid>
write revise --project-id <uuid> --chapter-id <cid> --model deepseek/deepseek-v4-flash
# 3. audit contradictions → fixes (timeline/foreshadowing maintenance)
audit check --project <name or UUID>
timeline update --id <tid> --title corrected
foreshadowing resolve --id <fsid>     # pay off
foreshadowing reopen --id <fsid>      # reopen
# 4. session deletion
session list --project-id <uuid>
session archive --id <sid> / session delete --id <sid>
# 5. recycle-bin restore regression
character delete --id <cid>
character restore --id <cid>
# 6. export backup
export export <name or UUID>
```

## Scenario C "Full-domain sweep"

Every command group's shortest path **create → list/get → update → delete → restore** succeeds in
one pass (world/character/outline/timeline/foreshadowing/map/chapter/volume/project), plus system
commands: `serve --port 0 --port-file`, `config`, `llm list`, `agent validate` + `agent run/status`,
`audit chapter`, `vector reindex|retrieve` (embedding), `memory add` (direct HTTP),
`POST /api/v1/context/assemble` (direct HTTP). **The default-parameter path must run** (the most
common no-flag calls break most easily).

## Scenario D "AI deep workflow"

```powershell
# 1. agentic writing (tool chain: search_characters/check_foreshadowing/get_prior_summary/audit_chapter/count_words)
write next --mode agentic --project-id <uuid> --chapter-id <cid> --outline <topic> --min-words 300 --json
#   criterion: agent_run record (steps/tool_calls/token); explicit model
# 2. draft confirm flow → final
# 3. preference learning: revise the same kind repeatedly (N≥2) → memory list shows the preference → learned_preferences>0
memory list --project-id <uuid>
memory stats --project-id <uuid>
# 4. semantic RAG: search the library → context injection (write requests auto-assemble preferences + context)
search --mode semantic <query> --project <name or UUID>
# 5. memory remove takes effect immediately (delete preference → injection stops)
memory remove --id <pid> --project-id <uuid>
memory list --project-id <uuid>   # the preference is gone
```

## Regression trimming

After iterative fixes, **do not rerun everything**: fix the affected domain → rerun the related
scenarios (e.g. memory-module fixes → only scenario D's memory section + the memory command
groups in B/C); **full A-D runs once only in the final pre-release validation**; only after the
trimmed rerun passes may the next release tag be cut.

## Data upgrade compatibility (new version opens old-version data)

Start the new kernel on a data dir generated by the previous version (auto migration) and
assert: `project list` still shows old projects (same id), `chapter list` content intact,
`search` index readable, `memory stats` table compatible, updating one entry reads back
consistently (old data writable), kernel stderr has no migration errors. Any data loss/migration
error → blocking defect.

## The 5 defect patterns to re-check (every validation round)

1. `GET /openapi.json` confirms the target endpoint exists (don't trust green tests)
2. Actually run every new command once (**including the default-parameter path**)
3. For any 500, always foreground-serve + redirect stderr to capture the traceback
4. For LLM chains, first confirm the model resolution path (DTO fields/config default/env) + key
   injection
5. Use a dedicated data dir throughout; compare production data before/after

## Error-prone points

- `--project-id` only accepts UUIDs; `chapter create` with an invalid UUID → DB_ERROR envelope
  (not NOT_FOUND)
- `chapter list` needs an explicit `--status`; a root-level `--json` goes before the subcommand
- Seed UUIDs are independent per table and cannot be guessed — get real UUIDs via `list --json`
- Mask sensitive credentials at all times (`sk-****0a68`)

## Version-sensitive points

- Artifact URL/tag criteria:
  `https://github.com/zhx-xi/InkFlow/releases/download/<tag>/InkFlow-CLI-<tag>-x64.zip` (trust the
  release assets' actual naming)
- Keep the scenario matrix incrementally in sync with FEATURES.md for new versions (fold new
  feature domains into the closest scenario or add a scenario)
