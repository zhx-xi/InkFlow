# Library · Outline (library-outline.md)

Agent usage: outline + plot points + arcs CRUD and AI generation. GUI counterpart:
`/library?cat=outline` (outline + plot points + arcs).

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `outline create` | `--project-id` `--name` | `--description` `--sort-order` | Create an outline |
| `outline list` | `--project-id` | `--search` `--sort` `--sort-desc` `--offset` `--limit` | List outlines |
| `outline get` | `--id` | — | Details |
| `outline update` | `--id` | optional fields | Update an outline |
| `outline delete` | `--id` | `--force/--permanent` | Cascade-delete plot points |
| `outline restore` | `--id` | — | Cascade-restore plot points |
| `outline generate` | `--project-id` | `--prompt`/`--prompt-file` mutually exclusive `--num-chapters`(1-100) `--save/--no-save`(default save) `--model` | AI-generate an outline; human mode shows a two-form summary (save/preview) |
| `outline point list` | `--outline-id` | — | List plot points |
| `outline point create` | `--outline-id` `--name` | `--type` `--description` `--position` `--arc-id` | Create a plot point |
| `outline point update` | `--id` | `--arc-id ""` = **clear arc membership** | Update a plot point |
| `outline point delete` | `--id` | `--force` (soft delete; points have no get/restore, #251 P3) | Delete a plot point |
| `outline arc list` | `--project-id` | — | List arcs |
| `outline arc create` | `--project-id` `--name` | — | Create an arc |
| `outline arc update` | `--id` | optional fields | Update an arc |
| `outline arc delete` | `--id` | `--force` (member points set to NULL; arcs have no get/restore, #251 P3) | Delete an arc |

## Error-prone points

- `point update --arc-id ""` passes through a string clear (unlike character `--group-id ""` →
  None, which the service layer decides)
- point/arc delete has no `--permanent` (only outline level does) — always soft deletes
- `outline generate` without `--save` prints a preview summary in human mode; JSON output
  contains the full result
