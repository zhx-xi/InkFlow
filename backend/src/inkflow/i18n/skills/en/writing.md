# Writing Chain (writing.md)

Agent usage: AI generate/continue/revise chapters. GUI counterpart: the `/writing` editor toolbar
(generate/continue/revise, SSE streaming).

## Command quick reference

| Command | Required params | Optional/error-prone | Purpose |
|---|---|---|---|
| `write next` | `--project-id` `--chapter-id` `--outline` | `--context` `--min-words`(2000) `--style` `--count`(1) `--mode`(deterministic\|agentic, default deterministic) `--memory-learning` `--max-steps` `--token-budget` | Generate a chapter from the outline; deterministic goes through SSE `/writing/stream`; agentic through non-streaming `/writing/agentic/generate` |
| `write continue` | `--project-id` `--chapter-id` | `--target-words`(2000) `--context` | Continue writing; the original chapter is fetched over HTTP; **existing_content ≥ 50 characters validation** (chapter too short → 422) |
| `write revise` | `--project-id` `--chapter-id` `--instruction` | `--range`(e.g. "第3段") | Revise |

## Key points

- **Always specify the model**: requests must carry `"model": "provider/model_name"` (e.g.
  `deepseek/deepseek-chat`); without it the fallback `gpt-4o` → `Invalid model format` 500
  (recorded in 0.6.0). When a CLI command has no `--model` param, it relies on the project
  config's model field (`project create` defaults to gpt-4o); or override with the
  `INKFLOW_LLM_DEFAULT_MODEL` env (AppConfig env_prefix=INKFLOW_)
- **Success criteria**: the response contains `content` (real generated prose), `word_count`,
  `format_valid: true`, and `token_usage`
- **`write continue` only returns and does not write back** to the chapter (the GUI merges when
  "Apply" is clicked) — the chapter word_count staying unchanged is by design, not a defect
- **No-key failure envelope** (recorded 2026-08-11):
  `{"ok":false,"error":{"code":"INTERNAL_ERROR","message":""}}` — **message is empty**, so the
  envelope alone cannot identify the root cause; diagnosis must look at the kernel stderr
  (`serve --port 0` foreground + `-RedirectStandardError`)
- Failure diagnosis in three steps: ① confirm the path via openapi ② foreground serve to capture
  the stderr traceback ③ check the model resolution path + key injection
- SSE streaming output is aggregated by the CLI before printing (not token-by-token) — judge by
  the final envelope
