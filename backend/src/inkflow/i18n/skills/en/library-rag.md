# Library · RAG (library-rag.md)

Agent usage: vector index rebuild/retrieval + unified AI extraction records. GUI counterpart:
`/library?cat=rag` (RAG extraction records + retrieval; RAG categories have no create endpoint —
the GUI CTA jumps to /writing).

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `vector reindex` | `--project-id` | `--entity-types`(repeatable) | Rebuild the vector index (no GUI entry) |
| `vector retrieve` | `--project-id` `--query` | `--entity-types` `--top-k`(10) `--min-score`(0.0) | Vector retrieval |
| `extract run` | `--project-id` `--type`(character/setting/outline/timeline/foreshadowing/style) | `--text`/`--text-file`/`--chapters` **pick exactly one** `--prompt` `--num-chapters` `--save/--no-save` `--auto-extract` `--model` `--index` `--force` | Unified AI extraction (6 types) |
| `extract status` | `--project-id` | `--type` filter | Recent extraction records (maps to the GUI extractions/runs) |

## Error-prone points

- `extract run`'s `--text`/`--text-file`/`--chapters` are pick-exactly-one (one more form than
  character/world's `--text`/`--text-file`); `--chapters` takes comma-separated UUIDs
- Invalid `--type` → exit code 2 (verified with the typer 0.27 enum annotation)
- `vector retrieve`'s default min-score 0.0 = no filtering; run `vector reindex` before retrieval
  (new data is not auto-indexed unless extract passes `--index`)
