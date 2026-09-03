# Project Memory (memory.md)

Agent usage: read/delete project memory-learning records. GUI counterpart: F28 project memory
(memory learning on the writing page's Agent chain; no standalone GUI management page — the CLI
is the management entry).

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `memory list` | `--project-id` | `--category`(addressing\|style_word\|structure\|other) | Learned preferences list |
| `memory remove` | positional `preference-id` | — | Delete a preference |
| `memory stats` | `--project-id` | — | Memory-learning statistics |

## Error-prone points

- `memory remove`'s id is a positional param
- memory has no manual add/modify (#251 P3 candidate) — the CLI can only read/delete; writes come
  from memory learning in the writing chain
- `memory stats` has a known defect (#249: API 500 traceback "list has no event_type") — on 5xx,
  first check the kernel stderr (`serve --port 0` foreground + `-RedirectStandardError`)
