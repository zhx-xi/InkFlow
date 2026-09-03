# Library · Timeline (library-timeline.md)

Agent usage: timeline event CRUD + views/consistency checks. GUI counterpart:
`/library?cat=timeline` (timeline events + views/consistency checks).

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `timeline create` | `--project-id` `--title` | `--description` `--time-value` `--time-unit` `--time-display` `--narrative-position` `--timeline-flag` | Create an event (create's `--time-value` is `float\|None`; Typer converts automatically, garbage input → exit 2) |
| `timeline list` | `--project-id` | `--search` `--sort` `--sort-desc` | List events (no --offset/--limit) |
| `timeline view` | `--project-id` | — | Linear view |
| `timeline check` | `--project-id` | `--include-flashbacks` | Consistency check |
| `timeline get` | `--id` | — | Details |
| `timeline update` | `--id` | `--time-value`/`--timeline-flag` are `str\|None` (`""` = clear semantics; non-empty values convert manually to float, ValueError → VALIDATION_ERROR exit 1) | Update an event |
| `timeline delete` | `--id` | `--force/--permanent` | Delete an event |
| `timeline restore` | `--id` | — | Restore |

## Error-prone points

- **create and update have different `--time-value` types**: create is `float|None` (Typer
  conversion), update is `str|None` (manual float(); failure → VALIDATION_ERROR envelope exit 1)
  — F12-generation design
- list has no --offset/--limit (not in spec)
- GUI timeline responses go through the `event_timeline` field special case (API layer); CLI
  parsing is handled client-side
