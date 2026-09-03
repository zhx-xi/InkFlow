# MCP Server Integration (mcp-setup.md)

InkFlow ships an official MCP Server (`inkflow-mcp`): a stdio thin client that connects over
HTTP to the local resident kernel (ADR-023 v2 / ADR-030 D3=A). An agent calls InkFlow tools
structurally through the MCP protocol; the tool set maps 1:1 to CLI semantics. The whole tool
surface is self-described by tools/list (see "Usage policy").

## 1. Client executable (three forms)

`inkflow-mcp` is bundled with every release; the path varies by install form:

| Release form | Client path |
|---|---|
| CLI zip | `inkflow-mcp/inkflow-mcp.exe` (sibling of `inkflow/`) |
| Portable zip / NSIS installer | `<install dir>\resources\kernel\mcp\inkflow-mcp.exe` |
| dev venv | `<venv>\Scripts\inkflow-mcp.exe` |

**Programmatic self-discovery**: a running kernel exposes `GET /api/v1/mcp/info` (with
`X-InkFlow-Token`), returning `{client_path, version, config_template}` — `client_path` is the
actually usable client path for the current release form and `config_template` holds the three
host config templates; an agent can read and assemble the config directly.

## 2. Host config templates

Add an `mcpServers` entry to each host's MCP config file; `command` points to the actual client
path (`type: stdio` is the stdio default transport and may be omitted):

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "inkflow": {
      "command": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe"
    }
  }
}
```

### Cursor (`.cursor/mcp.json` or global MCP config)

```json
{
  "mcpServers": {
    "inkflow": {
      "command": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe"
    }
  }
}
```

### Hermes

```json
{
  "mcpServers": {
    "inkflow": {
      "command": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe"
    }
  }
}
```

> `command` must be replaced with the actual path on your machine (see the three-form table in
> §1). After checking "Add InkFlow CLI to PATH" in the installer, `resources\kernel\mcp` is also
> added to PATH, but MCP configs should always use absolute paths.

## 3. Usage policy

- **MCP first, CLI fallback**: when the host supports MCP, prefer structured tool calls; for
  unsupported scenarios fall back to the `inkflow <cmd> --json` execution contract (see
  `json-contracts.md`; that contract is unchanged).
- **Tool surface governed by `tool_search`**: this file does not list the tool functions —
  tools/list is protocol self-describing, and a hard-coded list is a drift source. When needed,
  first call `tool_search` for the current tool surface and parameters.
- **Envelope semantics**: tool return text is a JSON envelope
  `{"ok": true, "data": ...}` (success) / `{"ok": false, "error": {"code", "message"}}`
  (failure), isomorphic to the CLI `--json` envelope; on `ok: false`, handle by `error.code`.
- **Cold start**: the first call auto-starts the local kernel via ensure_kernel; wait about a
  second; once resident, subsequent calls respond immediately.
