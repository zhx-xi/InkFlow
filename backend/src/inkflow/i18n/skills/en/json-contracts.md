# JSON Contract Reference (json-contracts.md)

The InkFlow CLI's `--json` output is the **stable execution contract** between an agent and the
kernel. This document describes the envelope structure, exit codes, and return shapes of core
commands. Fields are authoritative per `tests/cli/` contract tests and real runs (check those
tests when reviewing changes).

## 1. Envelope structure

### Success

```json
{"ok": true, "data": <any JSON>}
```

### Failure

```json
{"ok": false, "error": {"code": "NOT_FOUND", "message": "Project not found: ..."}}
```

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | Business error (locate via error.code in the envelope) |
| 2 | Usage error (unknown param/missing param/mutually exclusive input, typer output) |
| 130 | Ctrl+C interrupt |

## 2. Common error codes

| code | Scenario |
|---|---|
| `NOT_FOUND` | Resource does not exist (invalid or missing project/chapter/entity ID) |
| `VALIDATION_ERROR` | Parameter validation failed (incl. delete commands missing `--force` under `--json`) |
| `DB_ERROR` | Database/internal error (incl. invalid UUIDs in the chapter/volume/write groups) |
| `KERNEL_ERROR` | Kernel startup failure |
| `LLM_ERROR` | LLM call failure |
| `RAG_ERROR` | Vector library error |
| `EXTRACTION_ERROR` | Extraction pipeline failure |
| `UNSUPPORTED_TYPE` | Unsupported enum type |
| `CONFIG_ERROR` | Configuration error |

## 3. Core command return shapes

### project list

```json
{
  "ok": true,
  "data": {
    "projects": [
      {"id": "00000000-0000-0000-0000-000000000001", "name": "我的小说", "genre": "玄幻",
       "language": "zh-CN", "target_words": 1000000, "status": "active", "created_at": "...", "updated_at": "..."}
    ],
    "total": 1
  }
}
```

> The `id` field feeds every downstream `--project-id`; never guess UUIDs.

### project create

```json
{"ok": true, "data": {"id": "...", "name": "我的小说", "genre": "玄幻", "language": "zh-CN", "status": "active"}}
```

### chapter list

```json
{
  "ok": true,
  "data": {
    "chapters": [
      {"id": 1, "project_id": "...", "title": "第一章", "status": "draft",
       "word_count": 3200, "summary": "...", "content": "..."}
    ],
    "total": 1
  }
}
```

> chapter id is an integer; omitting `--status` returns everything.

### write generate (SSE streaming)

`write generate` outputs an **SSE stream** (`text/event-stream`), not a single JSON:

```text
data: {"event": "chunk", "content": "夜色渐深，"}

data: {"event": "done", "chapter_id": 5, "word_count": 3400}
```

Event types: `chunk` (incremental text) / `done` (finished, with the persisted chapter ID) /
`error` (error info). An agent should consume chunks event by event and concatenate content;
after `done`, use `chapter get` to verify what was persisted.

### audit chapter

```json
{"ok": true, "data": {"report_id": 1, "issues": [{"type": "character_name", "severity": "warning", "message": "..."}], "score": 87}}
```

### extract run

```json
{"ok": true, "data": {"items": [{"type": "character", "name": "林晚", "summary": "...", "chapter_id": 3}], "skipped": 0}}
```

### Example error shape

```json
{"ok": false, "error": {"code": "NOT_FOUND", "message": "Project not found: 00000000-0000-0000-0000-0000000000ff"}}
```

## 4. Agent execution recommendations

1. **Always use `--json`**: human-readable output is unstable (tables/emoji); the JSON envelope
   is the contract.
2. **Failure means envelope**: when `ok: false`, read `error.code` to decide retry/fix
   (NOT_FOUND → list first to get a real ID; VALIDATION_ERROR → check params/--force).
3. **Query before delete**: delete commands under `--json` fail with VALIDATION_ERROR when
   `--force` is missing; after deleting, verify with list.
4. **Streaming commands**: the write group defaults to SSE; do not force-parse it with a plain
   JSON parser.
5. **Version contract**: JSON contracts are frozen from 1.0.0 (ADR-019); field changes would
   break the agent ecosystem. This file and tests/cli/ are maintained in sync.
