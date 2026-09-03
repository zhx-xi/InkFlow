# MCP Server 接入（mcp-setup.md）

InkFlow 提供官方 MCP Server（`inkflow-mcp`）：一个 stdio 薄客户端，经 HTTP 直连本地常驻内核（ADR-023 v2 / ADR-030 D3=A）。agent 通过 MCP 协议结构化调用 InkFlow 工具，工具集与 CLI 语义一一对应；全部工具面由 tools/list 自描述（见「使用策略」）。

## 1. 客户端可执行文件（三形态）

`inkflow-mcp` 随各发行产物内置，按安装形态路径不同：

| 发行形态 | 客户端路径 |
|---|---|
| CLI zip | `inkflow-mcp/inkflow-mcp.exe`（与 `inkflow/` 兄弟目录） |
| 便携 zip / NSIS 安装版 | `<安装目录>\resources\kernel\mcp\inkflow-mcp.exe` |
| dev venv | `<venv>\Scripts\inkflow-mcp.exe` |

**程序化自发现**：运行中的内核提供 `GET /api/v1/mcp/info`（带 `X-InkFlow-Token`），返回 `{client_path, version, config_template}`——`client_path` 为当前发行形态下实际可用的客户端路径，`config_template` 为三宿主配置模板，agent 可直接读取拼接配置。

## 2. 宿主配置模板

在各宿主的 MCP 配置文件中加入 `mcpServers` 条目，`command` 指向实际客户端路径（`type: stdio` 是 stdio 默认传输，可省略）：

### Claude Desktop（`claude_desktop_config.json`）

```json
{
  "mcpServers": {
    "inkflow": {
      "command": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe"
    }
  }
}
```

### Cursor（`.cursor/mcp.json` 或全局 MCP 配置）

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

> `command` 必须替换为你机器上的实际路径（见 §1 三形态表）。安装版勾选「添加 InkFlow CLI 到 PATH」后 `resources\kernel\mcp` 也会加入 PATH，但 MCP 配置建议始终写绝对路径。

## 3. 使用策略

- **MCP 优先，CLI 兜底**：宿主支持 MCP 时优先走结构化工具调用；不支持的场景回退 `inkflow <cmd> --json` 执行契约（见 `json-contracts.md`，该契约保持不变）。
- **工具面以 `tool_search` 为准**：本文件不列工具函数清单——tools/list 由协议自描述，写死清单即漂移源。需要时先调 `tool_search` 获取当前工具面与入参。
- **信封语义**：工具返回文本为 JSON 信封 `{"ok": true, "data": ...}`（成功）/ `{"ok": false, "error": {"code", "message"}}`（失败），与 CLI `--json` 信封同构；`ok: false` 时按 `error.code` 定位处理。
- **冷启动**：首次调用会经 ensure_kernel 自动拉起本地内核，秒级等待即可；内核常驻后后续调用即时响应。
