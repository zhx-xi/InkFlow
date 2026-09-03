# Library · Worldbuilding (library-world.md)

Agent usage: worldbuilding entries + categories + tree structure + cross-project copy. GUI
counterpart: `/library?cat=world` (worldbuilding entries + categories + tree).

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `world create` | `--project-id` `--name` | `--category` `--content` `--parent`(parent entry UUID; omitted = top level) | Create an entry |
| `world list` | `--project-id` | `--search` `--category` `--sort` `--offset` `--limit` | List entries |
| `world categories` | `--project-id` | — | Category aggregation (JSON output `[{category, count}]`) |
| `world get` | `--id` | — | Details |
| `world ancestors` | `--id` | — | Ancestor chain |
| `world descendants` | `--id`(positional) | — | Descendant tree |
| `world copy` | positional `source-project-id` `target-project-id` | `--root`(copy start; omitted = the whole tree) | Copy an entry tree across projects |
| `world update` | `--id` | optional fields; `--parent` can re-hang; `--category ""` = plain string straight into the DTO (not a clear semantic) | Update an entry |
| `world delete` | `--id` | `--force/--permanent/--cascade/--reparent-to` | F35 subtree semantics |
| `world restore` | `--id` | — | Restore |
| `world extract` | `--project-id` | `--text`/`--text-file` mutually exclusive `--model` | AI-extract worldbuilding |

## Error-prone points

- `world descendants`'s id is a **positional param** (not `--id`)
- `--category ""` differs from `character --group-id ""` (the latter turns None/clears; the
  former passes through the string) — distinguish by DTO semantics
- `world copy` takes both project-ids as positional params
