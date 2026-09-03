# Library · Foreshadowing (library-foreshadowing.md)

Agent usage: foreshadowing CRUD + reveal state machine. GUI counterpart:
`/library?cat=foreshadow` (foreshadowing CRUD + reveal state machine).

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `foreshadowing create` | `--project-id` `--title` | `--description` `--priority`(0-100) `--location` `--event-id` | Plant foreshadowing |
| `foreshadowing list` | `--project-id` | `--status`(open\|resolved) `--search` `--sort` `--sort-desc` | List foreshadowing |
| `foreshadowing get` | `--id` | — | Details |
| `foreshadowing update` | `--id` | optional fields; `--event-id ""` clears | Update foreshadowing |
| `foreshadowing delete` | `--id` | `--force/--permanent` | Delete foreshadowing |
| `foreshadowing restore` | `--id` | — | Restore |
| `foreshadowing resolve` | `--id` | — | Mark as revealed (state machine open→resolved) |
| `foreshadowing reopen` | `--id` | — | Reopen (resolved→open) |

## Error-prone points

- `--priority` validates the 0-100 range; `--status` only accepts open/resolved
- resolve/reopen are state-machine commands (no force)
