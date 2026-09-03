# Agent Chains and Sessions (agent.md)

Agent usage: Agent pipeline execution and run records, draft confirm/reject, session lifecycle.
GUI counterparts: `/settings?cat=agent` (AgentChainCard four-role toggles — see projects.md for
direct config calls) + Agent run records + the `/writing` Agent chain card. Project-level Agent
configuration = `project config` (#251 P1).

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `agent run` | `--project-id` | `--chapter-id` `--pipeline`(default builtin:write_chapter) `--var`(repeatable key=value) `--override` `--watch` | Run an Agent pipeline |
| `agent status` | `--run-id` | — | Run record details |
| `agent validate` | `--file` | ⚠️ **Phase 1 placeholder** — only prints "will be implemented in Phase 2", no real validation (#251 P3) | Validate a pipeline YAML |
| `agent template` | — | `--json` | List built-in pipeline templates (not DB Agent templates; see templates.md) |
| `agent tools list` | — | `--json` | List read-only tools (local static enumeration of TOOL_REGISTRY) |
| `agent runs list` | `--project-id` | `--limit`(20) | Run record list |
| `agent runs show` | positional `run-id` | — | Run record details |
| `agent draft list` | `--project-id` | `--status`(draft\|confirmed\|rejected) | Draft list |
| `agent draft confirm` | positional `draft-id` | `--chapter-id`(when the draft is unbound) | Confirm a draft (same semantics as GUI "Apply") |
| `agent draft reject` | positional `draft-id` | — | Reject a draft |

## Sessions

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `session create` | `--type`(writing\|task) `--title` | `--project-id` `--description` `--context-json`/`--context-file`(mutually exclusive) | Create a session |
| `session list` | — | `--type` `--status` `--project-id` `--search` `--limit`(50) `--offset` | List sessions |
| `session get` | `--id` | — | Details |
| `session update` | `--id` | optional fields | Update a session |
| `session pause/resume` | `--id` | — | State machine active↔paused |
| `session complete` | `--id` | `--result-json` | Complete |
| `session fail` | `--id` `--error` | — | Fail |
| `session logs` | `--id` | `--limit/--offset` | Log list |
| `session log add` | `--id` `--message` | `--level`(info\|warning\|error) `--payload-json` | Append a log |
| `session delete` | `--id` | ⚠️ two levels: default archive is recoverable; `--force` hard deletes | Delete a session |
| `session restore` | `--id` | — | Unarchive |

## Error-prone points

- agent/session group positional params (run-id/draft-id) coexist with `--id`; check each command's form
- `agent validate` is a placeholder command (do not rely on its validation result)
- Session archiving semantics: delete is a soft delete by default (restore recovers), `--force` is a hard delete
