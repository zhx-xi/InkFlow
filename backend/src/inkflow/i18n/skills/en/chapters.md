# Chapters and Volumes (chapters.md)

Agent usage: chapter/volume CRUD. GUI counterpart: the volume/chapter tree in `/writing` plus
the editor (chapter CRUD lives in this domain).

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `chapter create` | `--project-id/-p`(UUID) `--title/-t` | `--volume-id/-v` `--content/-c` | ⚠️ invalid UUID → ValueError → **DB_ERROR envelope** (not NOT_FOUND); a successful create returns the full chapter (with id) |
| `chapter list` | `--project-id` | `--volume-id` `--status` | ⚠️ **no default status filter**: omitting status returns everything; pass `--status draft` to filter; invalid status → DB_ERROR envelope |
| `chapter get` | `--id` | — | Returns full chapter text + word_count + status_history |
| `chapter update` | `--id` | `--title` `--content` `--status` | Update prose/title/status |
| `chapter move` | `--id` | `--to-volume` | Move to another volume |
| `chapter delete` | `--id` | `--force` | Soft delete (no restore command; recovery goes through GUI or API) |
| `volume create` | `--project-id` `--title` | `--order` | Create a volume |
| `volume list` | `--project-id` | — | List volumes |
| `volume delete` | `--id` | `--force` | Chapters under it become uncategorized (volumes have no update/restore, #251 P3) |

## Error-prone points

- The first chapter seed UUID is `00000000-0000-0000-0000-000000000001` (independent per table,
  not 002!); the correct way to get it is `chapter list --project-id <uuid> --status draft --json`
- Passing `--content` with Chinese text inline in PowerShell carries a GBK risk — for long content,
  write a UTF-8 file with write_file, then read it with
  `Get-Content -Raw -Encoding UTF8` and pass the value
- word_count counts characters (a 44-character chapter → word_count 44, recorded 2026-08-11)
- **Writing-chain prerequisite**: chapter content must be ≥ 50 characters (business validation on
  `write continue`'s existing_content; otherwise 422) — run `chapter update` to lengthen the
  chapter before generating/continuing
