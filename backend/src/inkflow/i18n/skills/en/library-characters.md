# Library · Characters (library-characters.md)

Agent usage: character CRUD + relationships + groups + AI extraction. GUI counterpart:
`/library?cat=characters` (character list/create/relationships) + character groups.

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `character create` | `--project-id`(UUID) `--name` | `--group-id`(invalid UUID → NOT_FOUND envelope) | Create a character |
| `character list` | `--project-id` | `--search` `--group-id` `--sort` `--sort-desc` `--offset` `--limit` | List characters |
| `character get` | `--id`(UUID) | — | Details |
| `character update` | `--id` | `--group-id ""` = **clear the group** | Update a character |
| `character delete` | `--id` | `--force` `--permanent` | ⚠️ under `--json` without `--force` → VALIDATION_ERROR (service not called) |
| `character restore` | `--id` | — | Cascade-restore bidirectional relationships |
| `character relate` | `--id` `--to` `--type` | `--description` | Create a relationship |
| `character unrelate` | `--id` `--relation-id` | `--force` | Delete a relationship |
| `character relations` | `--id` | — | Bidirectional relationship list |
| `character extract` | `--project-id` | `--text`/`--text-file` mutually exclusive (both → exit 2) `--model` | AI-extract characters + relationships |
| `character group create/list/get/update/delete` | see below | `--group-id ""` semantics as above | Group management |

## Error-prone points

- All id params are UUIDs; `--group-id ""` (empty string) in update = clear the group (explicit
  None enters model_fields_set)
- `--text` and `--text-file` are mutually exclusive → exit 2; passing neither → empty text →
  VALIDATION_ERROR exit 1
- Delete has three states: `--force` = skip interactive confirmation (≠ service-level force);
  only `--permanent` maps to a hard delete; under `--json` without `--force` it short-circuits to
  VALIDATION_ERROR
