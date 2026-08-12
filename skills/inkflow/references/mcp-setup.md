# MCP Server 接入（mcp-setup.md）

> **占位文件**：InkFlow MCP Server（Issue #49，0.9.0 里程碑）发布后填写本文档。

MCP（Model Context Protocol）接入方式将允许 agent 通过结构化 MCP 工具调用替代/补充 CLI 命令执行。发布后本文件将包含：

- MCP Server 启动方式与配置
- 工具清单与 CLI 命令映射
- 与 `--json` 执行契约的切换建议

**当前状态**：MCP 未发布，agent 请继续使用 `inkflow <cmd> --json` 执行契约（见 `json-contracts.md`）。
