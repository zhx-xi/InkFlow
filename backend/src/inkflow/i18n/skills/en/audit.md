# Chapter Audit/Review (audit.md)

Agent usage: trigger a chapter audit and handle accept/reject. GUI counterpart: the "Audit"
dialog in the `/writing` toolbar (AuditDialog accept/reject). F34 feature.

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `audit chapter <chapter>` | positional `chapter` (name or UUID) | `--project/-p` (name or ID, **not --project-id**) `--include-static/--no-include-static` `--confirm(accept\|reject)` `--note` `--history` | Trigger a chapter audit and print the result; omit `--history` (skips history) |
| `audit check` | `--project-id` | — | 4-dimension consistency audit (project level); **finding inconsistencies is a result, not an error — exit code is always 0** |

## Error-prone points

- `--note` without `--confirm`, `--confirm` together with `--history`, or an invalid confirm value → **exit 2** (usage error, not an envelope)
- The `--project` param is named `--project`, not `--project-id` (accepts a name or ID)
- Audit accept/reject goes through `POST /api/v1/projects/{pid}/chapters/{cid}/audit/confirm` (body `{action, note}`) — the CLI triggers it via `--confirm`
