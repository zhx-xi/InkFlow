# CLI 命令全量参考（cli-commands.md）

InkFlow CLI 全量命令面速查（顶层 23 组 + 2 个压平命令）。本文件是**索引级**参考：每条命令的签名、参数与语义；功能域细节见对应 `library-*.md` / `writing.md` 等功能文件。

**执行契约**：所有命令支持 `--json`（根级 `--json` 放在子命令前）；信封与退出码见 `json-contracts.md`。

## 0. 通用纪律（每次执行前必读）

| 主题 | 规则 |
|---|---|
| 项目 ID | 多数组 `--project-id`/`--id` 只收 **UUID**；非法 UUID → NOT_FOUND 信封（exit 1） |
| 三态解析 | `export` 位置参数 / `audit chapter --project` / `search --project` 接受数字/UUID/名称 |
| 例外 | `chapter`/`volume`/`write` 组非法 UUID → ValueError → **DB_ERROR** 信封（语义与其他组不一致） |
| 删除 | 删除类命令统一 `--force`（软删）/ `--permanent`（硬删）+ 交互确认；`--json` 下必须显式 `--force` |
| 互斥输入 | `--text/--text-file/--chapters` 三选一（extract/style/character extract/world extract）；`--prompt/--prompt-file`（outline generate）；同用 → exit 2 |
| 状态过滤 | `chapter list` 无默认状态过滤——只看 draft 必须显式 `--status draft` |
| 数据目录 | 打包版 `%APPDATA%\InkFlow`；开发版 `data/`（相对运行目录） |
| 内核 | 首次命令自动 `ensure_kernel` 拉起本地内核；`kernel status` 只读不拉起 |

## 1. 系统与内核

| 命令 | 说明 |
|---|---|
| `inkflow serve [--port] [--host]` | 直接启动 Web 服务（uvicorn）；就绪行 `INKFLOW_READY {"port":..,"token":..}` |
| `inkflow kernel status` | 读 kernel.json + PID 存活检查；输出 running/pid/port/version（不拉起内核） |
| `inkflow config show` / `config set <key> <value>` | 系统配置查看/设置（本地 config.json；`config set data-dir <path>` 写 instance.env） |
| `inkflow llm list` / `llm set-key --provider <p> --key <k>` | LLM Provider 与 key 管理（本地加密文件） |

## 2. 项目与章节

| 命令 | 关键参数 | 说明 |
|---|---|---|
| `project create` | `--name`（必填）`--genre`（默认"其他"）`--language`（zh-CN）`--target-words` | 创建项目，返回 UUID |
| `project list` | `--search` `--sort`（name\|updated_at\|created_at） | 固定 limit=50；**取真实项目 UUID 的主途径** |
| `project get` / `delete` / `restore` | `--id` | ⚠️ 当前 `--id` 声明 int 但 API 只收 UUID，实测不可用——项目详情/删除用 `project list --json` + HTTP 直调（见 projects.md） |
| `chapter list` | `--project-id <uuid>` `--status` | 无默认状态过滤 |
| `chapter get` / `create` / `update` / `delete` | `--project-id` + 章节参数 | delete 需 `--force` |
| `volume list` / `create` / `delete` | `--project-id` | 卷管理（无 update/restore） |

## 3. AI 写作

| 命令 | 关键参数 | 说明 |
|---|---|---|
| `write generate` | `--project-id` `--chapter-id` `[--prompt]` `[--count]` | 生成章节（SSE 流式输出） |
| `write continue` | `--project-id` `--chapter-id` `--text` | 续写 |
| `write revise` | `--project-id` `--chapter-id` `--text` | 修订 |
| `write next` | `--project-id` `--chapter-id` `[--count]` | deterministic 模式默认 SSE 流式；agentic 模式走非流式 agent 编排 |

> SSE 流式输出契约见 writing.md；`write` 组非法 UUID → DB_ERROR。

## 4. 审计与一致性

| 命令 | 说明 |
|---|---|
| `audit chapter` | 章节审计（`--project` 接受名称或 UUID） |
| `audit check` | 一致性审计（角色/时间线/世界/伏笔/跨维度，`--project-id` UUID） |

## 5. 资料库（library）

| 组 | 命令形态 | 说明 |
|---|---|---|
| `character` | CRUD + `group` 子组 | 角色管理（含角色分组）；`character extract` 互斥三选一 |
| `world` | CRUD + `tree` | 世界观管理（世界树）；`world extract` 互斥三选一 |
| `map` | `pin` 子组 | 地图管理（地图标记） |
| `outline` | `point` + `arc` 子组 + `generate` | 大纲管理（点/弧线）；`generate` 用 `--prompt/--prompt-file` |
| `timeline` | CRUD | 时间线管理 |
| `foreshadowing` | CRUD | 伏笔管理 |
| `vector` | `index` / `status` / `search` / `rebuild` | RAG 向量索引与检索 |

## 6. 提取、风格、导出

| 命令 | 说明 |
|---|---|
| `extract run` / `extract characters` / `extract world` / `extract outline` 等（6 类型） | 统一提取入口；`--text/--text-file/--chapters` 三选一 |
| `style analyze` | 风格检测（文本风格指纹/AI 痕迹/词汇分析）；互斥三选一 |
| `export book <project>` | 导出项目（TXT），位置参数接受名称或 UUID |

## 7. Agent 编排

| 命令 | 说明 |
|---|---|
| `agent tools list` | 枚举可用工具（本地静态，无需内核） |
| `agent runs` | Agent 运行记录 |
| `agent draft` | 草稿管理 |
| `agent template` | Agent 模板（只读） |
| `agent validate` | 模板/配置校验（Phase 1 占位） |
| `session list` / `session log` | 会话管理（`session log` 为子组） |
| `memory list` / `memory remove` / `memory stats` | Agent 记忆管理（无手工 add/update） |

## 8. 搜索

| 命令 | 说明 |
|---|---|
| `inkflow search <query>` | 全文搜索（FTS5 词法 + AI 语义）；`--project` 限定（名称或 UUID，可重复）；`--rebuild` 手动全量重建索引 |

## 9. 已知 CLI 缺口（#251，0.8.0 补全中）

以下面有 REST API/GUI 但 CLI 暂缺，需要时走 HTTP 直调（见 system.md / projects.md 兜底示例）：
- provider-configs CRUD（`llm` 只读写本地 key 文件）
- settings/llm-keys 存储、llm/test 连接测试
- chapters/{id}/summary 摘要
- agent-templates 写操作（CLI 只读）
- `project get/delete/restore --id` 当前断裂
