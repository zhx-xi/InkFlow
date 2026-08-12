---
name: inkflow
description: "操作 InkFlow 本地 AI 小说创作内核与 CLI：项目/章节/卷管理、AI 写作生成与续写、章节审计、角色/世界观/大纲/时间线/伏笔/RAG 资料库、LLM 模型配置、Agent 链编排、导出与提取。触发：agent 需要为 InkFlow 用户创建或管理小说项目、调用 AI 写作、操作资料库数据、查看模型配置或验证操作结果时。"
version: 0.8.0
license: MIT
compatibility: InkFlow >= 0.8.0
metadata:
  hermes:
    source: https://github.com/zhx-xi/InkFlow/tree/main/skills/inkflow
---

# InkFlow 操作指南（CLI / 内核）

InkFlow 是一个本地 AI 辅助小说创作工具（单机应用）。本 skill 是 InkFlow 官方提供的外部 AI agent 使用指南：agent 通过 `inkflow` CLI 与 InkFlow 内核交互，完成项目创建、章节写作、资料库维护等任务。

**执行契约**：所有命令支持 `--json` 输出——`inkflow <cmd> --json` 返回稳定 JSON 信封（详见 `json-contracts.md`），这是 agent 与内核之间的可靠交互通道。请始终使用 `--json` 形态执行命令并解析信封，不要依赖人类可读输出。

## 安装后如何用（三步起步）

1. **探活**：`inkflow --version` 确认 CLI 可用；`inkflow --help` 查看全部命令组（23 组）
2. **发现**：`inkflow project list --json` 列出用户现有项目（拿真实 UUID——不要猜测 UUID，seed 惯例下第一个项目是 `00000000-0000-0000-0000-000000000001`，但请以 list 返回为准）
3. **走查**（旅程 C：agent 辅助写作闭环）：
   - `inkflow project list --json` → 选择项目 UUID
   - `inkflow chapter list --project-id <uuid> --json` → 发现章节
   - `inkflow write generate --project-id <uuid> --chapter-id <cid> --json` → 生成章节
   - `inkflow audit chapter --project <uuid> --json` → 触发审计
   - 结果写回：`inkflow write continue --project-id <uuid> --chapter-id <cid> --text "..." --json`

## 核心执行纪律（每次操作前必读）

1. **`--json` 位置**：根级 `--json` 必须放在子命令**前**（`inkflow --json project list`）；子命令内的 `--json` 按各命令 help。
2. **信封**：成功 `{"ok": true, "data": ...}`；失败 `{"ok": false, "error": {"code", "message"}}`；退出码 0（成功）/ 1（业务错误）/ 2（用法错误）/ 130（Ctrl+C）。
3. **项目 ID 语义**：`character/world/outline/timeline/foreshadowing/chapter/volume/write` 组用 `--project-id` 且只收 **UUID 字符串**；`export`/`audit chapter --project`/`search --project` 接受名称或 UUID。
4. **数据目录**：打包版数据在 `%APPDATA%\InkFlow`（Windows）；开发版为运行目录下 `data`。首次命令自动拉起本地内核（`ensure_kernel`），无需手动启动。
5. **只读优先**：对用户数据的修改性操作（删除/覆盖）前先 list 确认目标，删除类命令注意 `--force` 语义（无 `--force` 会交互确认，`--json` 下必须显式 `--force`）。

## 命令面总览（23 组）

| 组 | 用途 | 参考文件 |
|---|---|---|
| `project` | 项目创建/列表/删除 | `projects.md` |
| `chapter` / `volume` | 章节与卷管理 | `chapters.md` |
| `write` | AI 生成/续写/修订（SSE 流式） | `writing.md` |
| `audit` | 章节审计/评审 | `audit.md` |
| `character` / `world` / `outline` / `timeline` / `foreshadowing` / `map` | 资料库 | `library-*.md` |
| `vector` | RAG 向量库 | `library-rag.md` |
| `extract` | 统一提取（角色/世界观/大纲） | `extract.md` |
| `export` | 书籍导出 | `cli-commands.md` §6 |
| `style` | 文风管理 | `cli-commands.md` §6 |
| `agent` / `session` / `memory` | Agent 链/会话/项目记忆 | `agent.md` / `memory.md` |
| `models` / `config` / `llm` | Provider/模型/配置 | `models.md` / `system.md` |
| `template`（agent 模板） | 模板管理 | `templates.md` |
| `search` | 全文搜索 | `system.md` |
| `kernel` / `serve` | 内核生命周期 | `kernel.md` / `system.md` |

> 全量 23 组命令签名与示例见 `cli-commands.md`；JSON 信封契约见 `json-contracts.md`。

## 文件索引

| 任务 | 读 |
|---|---|
| 内核如何拉起/发现/健康检查 | `references/kernel.md` |
| 创建/查询/删除项目 | `references/projects.md` |
| 章节/卷操作 | `references/chapters.md` |
| 生成/续写/修订（SSE） | `references/writing.md` |
| 章节审计/评审 | `references/audit.md` |
| 角色/世界观/大纲/时间线/伏笔/RAG | `references/library-*.md` |
| Provider/模型/key 配置 | `references/models.md` |
| Agent 模板/链/会话/记忆 | `references/templates.md` / `agent.md` / `memory.md` |
| 导出/风格 | `references/cli-commands.md`（§6） |
| serve/kernel/search/config/llm 系统命令 | `references/system.md` |
| 完整命令参考与 JSON 契约 | `references/cli-commands.md` / `json-contracts.md` |

## 常见工作流

- **创建项目并写作**：`project create --name <N> --genre <G>` → 取 UUID → `write generate` 生成首章 → `chapter list` 确认
- **资料库维护**：`character create --project-id <uuid> --name <N>` 等资料库命令批量录入 → `world`/`outline` 同步
- **批量提取**：`extract characters --project-id <uuid> --chapter-id <cid>` 从章节提取设定
- **导出**：`export book --project-id <uuid> --format md` 导出全书

## 版本

本 skill 随 InkFlow 版本对齐（frontmatter version = InkFlow 版本）。命令面若有出入，以 `inkflow --help` 与真实运行为准。

## MCP

InkFlow MCP Server 发布后，本文件将补充 MCP 接入指引（见 `references/mcp-setup.md` 占位）。
