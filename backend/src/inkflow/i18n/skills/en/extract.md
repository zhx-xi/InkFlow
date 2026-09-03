# Unified Extraction / Style / Export (extract.md)

Agent usage: consolidated scattered domains (none has a standalone GUI page; the GUI uses them
indirectly via the writing page / libraries).

## extract (unified AI extraction)

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `extract run` | `--project-id` `--type`(character/setting/outline/timeline/foreshadowing/style) | `--text`/`--text-file`/`--chapters` mutually exclusive; `--prompt` `--num-chapters` `--save/--no-save` `--auto-extract` `--model` `--index` `--force` | Extract the 6 types; `--index` also enters the vector library |
| `extract status` | `--project-id` | `--type` | Recent extraction records (same source as the GUI library RAG tab) |

## style (style detection)

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `style analyze` | `--project-id` | `--text`/`--text-file`/`--chapters`(comma-separated UUIDs) mutually exclusive; `--llm-analysis/--no-llm-analysis` | Style detection; **always exits 0** (an analysis result is not an error) |

## export

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `export export` | positional `project` (number/UUID/name tri-state resolution) | `--include-settings` `--output` | Export the project as TXT; ⚠️ false booleans **omit the key entirely** (httpx None → empty-string 422 defect pattern #247/#231) |

## Error-prone points

- `export`'s positional project param uses tri-state resolution (number/UUID/name) — different
  semantics from --project-id
- `style analyze`/`audit check` both treat "a result as not an error" — exit code 0 does not mean
  no issues; judge by the output content
- Omitting `export --include-settings` = omitting the param (**never pass False explicitly** —
  #247/#231 defect pattern: the common no-flag path once produced 422)
