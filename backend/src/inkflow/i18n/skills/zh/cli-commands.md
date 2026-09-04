# CLI 命令全量参考（cli-commands.md）

InkFlow CLI 全量命令面速查（顶层 26 组 + 2 个压平命令 `serve`/`search`）。本文件是**索引级**参考：每条命令的签名、参数与语义；功能域细节见对应 `library-*.md` / `writing.md` 等功能文件。命令面以 `inkflow --help` 与真实运行为准（本表同步于 0.13.0，#864）。

**执行契约**：所有命令支持 `--json`（根级 `--json` 放在子命令前）；信封与退出码见 `json-contracts.md`。

## 0. 通用纪律（每次执行前必读）

| 主题 | 规则 |
|---|---|
| 项目 ID | 多数组 `--project-id`/`--id` 只收 **UUID**；非法 UUID → NOT_FOUND 信封（exit 1） |
| 三态解析 | `export export` 位置参数 / `audit chapter chapter --project` / `search --project` 接受数字/UUID/名称 |
| 例外 | `chapter`/`volume`/`write` 组非法 UUID → ValueError → **DB_ERROR** 信封（语义与其他组不一致） |
| 删除 | 删除类命令统一 `--force`（软删）/ `--permanent`（硬删，project 独有）+ 交互确认；`--json` 下必须显式 `--force` |
| 互斥输入 | `extract run` 的 `--text/--text-file/--chapters` 三选一（style/character extract/world extract 为 text/text-file 二选一）；`outline generate` 的 `--prompt/--prompt-file`；同用 → exit 2 |
| 状态过滤 | `chapter list` 无默认状态过滤——只看 draft 必须显式 `--status draft` |
| 数据目录 | 打包版 `%APPDATA%\InkFlow`；开发版 `data/`（相对运行目录） |
| 内核 | 首次命令自动 `ensure_kernel` 拉起本地内核；`kernel status` 只读不拉起 |

## 1. 系统与内核

| 命令 | 说明 |
|---|---|
| `inkflow serve [--port] [--host] [--token] [--port-file] [--reload] [--debug]` | 直接启动 Web 服务（uvicorn）；就绪行 `INKFLOW_READY {"port":..,"token":..}` |
| `inkflow kernel status` | 读 kernel.json + PID 存活检查；输出 running/pid/port/version（不拉起内核） |
| `inkflow config show` / `config set <key> <value>` | 系统配置查看/设置（本地 config.json；`config set data-dir <path>` 写 instance.env） |
| `inkflow llm list` | 列出 Provider 与 key 保存状态（本地加密文件） |
| `inkflow llm set-key --provider <p> [--key <k>]` / `llm key remove --provider <p>` | Provider key 写入/删除 |
| `inkflow llm test --provider <p> --api-key <k> [--model] [--base-url]` | 连接测试（key 仅本次请求，不落盘） |
| `inkflow llm provider list/get/create/update/delete/models` | Provider 注册表 CRUD（DB 存储；`--id` 收数据库 ID；models 用 `--add/--remove/--set-json`） |

## 2. 项目与章节

| 命令 | 关键参数 | 说明 |
|---|---|---|
| `project create` | `--name`（必填）`--tags`（可重复）`--language`（zh-CN）`--target-words` | 创建项目，返回 UUID（标签制：genre 已并入 tags，#595） |
| `project list` | `--search` `--sort`（name\|updated_at\|created_at） | 固定 limit=50；**取真实项目 UUID 的主途径** |
| `project get` / `delete` / `restore` / `update` | `--id`（UUID，#251 已修通） | delete 支持 `--force`/`--permanent`；update 支持 `--name/--tags/--language/--target-words/--config/--config-json` |
| `chapter list` | `--project-id <uuid>` `--status` | 无默认状态过滤 |
| `chapter get` / `create` / `update` / `delete` / `move` | `--project-id` + 章节参数 | delete 需 `--force`；move 用 `--to-volume` |
| `chapter summary get` / `summary refresh` | `--id <章节 uuid>` | 章节摘要查看/重生成 |
| `volume list` / `create` / `update` / `delete` | `--project-id` / `--id` | 卷管理（update 改 title/order） |

## 3. AI 写作（write 组 + book 长线编排）

| 命令 | 关键参数 | 说明 |
|---|---|---|
| `write next` | `--project-id` `--chapter-id` `--outline`（必填）`[--context] [--min-words] [--count] [--mode] [--style] [--show-context] [--max-steps] [--token-budget] [--memory-learning/--no-memory-learning]` | 生成下一章：deterministic 模式默认 SSE 流式；agentic 模式走非流式 agent 编排（**无 `write generate` 命令**） |
| `write continue` | `--project-id` `--chapter-id` `[--target-words] [--context]` | 续写当前章（读章节库内容，非 `--text`） |
| `write revise` | `--project-id` `--chapter-id` `--instruction`（必填）`[--range]` | 按指令修订 |
| `book plan start` / `auto` | `<one_liner>` `--project <uuid>` | 长线写作计划会话（start 交互式 / auto 直通） |
| `book plan show` / `respond` / `confirm` / `run` | `<session_id 或 plan_id>` | 计划会话推进 / 回答澄清 / 确认 / 执行计划 |
| `book run` | `<plan_id> [--limits k=v,k=v]` | 按写作计划批量生成卷/章 |
| `book status` / `summary` / `confirm` / `intervene` | `<run_id>` | 批次进度（`--density`）/ 总结（`--export`）/ HITL 审批（`--approved/--reject/--decision`）/ 干预（`--action/--target/--to/--brief`） |

> SSE 流式输出契约见 writing.md；`write` 组非法 UUID → DB_ERROR。

## 4. 审计与一致性

| 命令 | 说明 |
|---|---|
| `audit check --project-id <uuid>` | 一致性审计（角色/时间线/世界/伏笔/跨维度；`--include-static`） |
| `audit chapter chapter <chapter> --project <p> [--confirm <issue>] [--note] [--history]` | 章节审计/确认/查历史。⚠️ 命令形态为嵌套 `audit chapter chapter`（组名即命令名） |

## 5. 资料库（library）

| 组 | 命令形态 | 说明 |
|---|---|---|
| `character` | CRUD + `group` 子组 + `extract` / `relate` / `relations` / `unrelate` | 角色管理；create 必填 `--role-rank`；relate 用 `--id --to --type` |
| `world` | CRUD + `categories` / `ancestors <id>` / `descendants <id>` / `copy <src> <tgt> [--root]` / `extract` | 世界观管理（世界树层级导航/跨项目复制）；extract 为 text/text-file 二选一 |
| `map` | CRUD（create 必填 `--image`）+ `children <map_id>` / `image <map_id> --image` / `pin add/list/update/delete` | 地图与标记（pin 必填 `--x --y --label`；delete 支持 `--cascade/--reparent-to`） |
| `outline` | CRUD + `point` / `arc` 子组 + `generate` | 大纲树；`generate` 用 `--prompt/--prompt-file --num-chapters --save --model` |
| `timeline` | CRUD + `view` + `check [--include-flashbacks]` | 时间线与一致性检查 |
| `foreshadowing` | CRUD + `resolve --id` / `reopen --id` | 伏笔埋设与回收 |
| `knowledge` | `graph <project_id>` / `extract --project [--method]` / `relation add/list/get/update/delete` | 知识图谱（实体关系抽取与查询） |
| `vector` | `status --project-id` / `reindex --project-id [--type]` / `retrieve --project-id --query [--type --top-k --min-score]` | RAG 向量库（**无 index/search/rebuild**，对应形态是 reindex/retrieve） |

## 6. 提取、风格、导出

| 命令 | 说明 |
|---|---|
| `extract run --project-id <uuid> --type <character\|setting\|outline\|timeline\|foreshadowing\|style\|knowledge_relation>` | 统一提取入口（7 类型）；`--text/--text-file/--chapters` 三选一；`--save/--auto-extract/--index/--force/--model` |
| `extract status --project-id [--type]` | 提取记录查询 |
| `style analyze --project-id` | 风格检测（指纹/AI 痕迹/词汇）；`--text/--text-file/--chapters` 三选一，`--llm-analysis` 追加 AI 分析 |
| `export export <project> [--include-settings] [-o <path>]` | 导出全书（CLI 固定 TXT 格式，其余格式走 GUI/HTTP）；位置参数接受名称或 UUID（**无 `export book` 命令**） |

## 7. Agent 编排、会话、记忆

| 命令 | 说明 |
|---|---|
| `agent list` / `agent show --id` | Agent 链配置查看 |
| `agent run --project-id [--chapter-id] [--pipeline builtin:write_chapter] [--var k=v]... [--override] [--watch]` | 执行 Agent 管线（`--watch` Phase 2 完善中） |
| `agent status --run-id` | 运行状态查询 |
| `agent validate --file <yaml>` | 管线 YAML 校验（⚠️ Phase 1 占位，打印提示不实际校验，#251 P3） |
| `agent tools list` | 枚举可用工具（本地静态，无需内核） |
| `agent runs list --project-id [--limit]` / `runs show <run_id>` | Agent 运行记录 |
| `agent draft list --project-id [--status]` / `confirm <draft_id> [--chapter-id]` / `reject <draft_id>` / `prune-orphans [--dry-run]` | 草稿确认流 |
| `agent template list/get/create/update/delete/duplicate/set-default/get-default/pipelines` | DB Agent 模板全量 CRUD（create/update 用 `--roles-json` 四键 JSON） |
| `session create/list/get/update/pause/resume/complete/fail/logs/delete/restore` | 会话生命周期（create 必填 `--type --title`；`log add --id -m` 子组追加日志） |
| `memory list --project-id [--category]` / `remove <preference_id>` / `stats --project-id` / `summarize --project-id [--force|--remove]` / `user-list [--category]` / `user-remove <preference_id>` | Agent 记忆与偏好（项目级 + 用户级；无手工 add） |
| `context assemble --project-id --chapter-id --model --writing-requirements [--max-tokens]` | 上下文装配预览（四必选项） |
| `skills list/verify/install/remove` | 文件技能包管理（`skills install --builtin` 导入随包官方 skill；source 为含 SKILL.md 的目录） |
| `skill list` | F39 Skill 实体域查看（与复数 `skills` 文件导入域区分，共用 data_dir/skills/） |
| `inkflow search <query> [--project <p>] [--type] [--mode semantic] [--limit] [--offset] [--rebuild]` | 全文搜索（FTS5 词法 + AI 语义）；`--project` 名称或 UUID 可重复 |

## 8. 已知 CLI 差异备忘

- `audit chapter chapter` 组名即命令名的嵌套形态是历史遗留（click group + 同名 command），调用勿漏一层。
- `llm provider --id` 收**数据库数字 ID**（`llm provider list` 取），非 provider 名。
- `agent validate` 为 Phase 1 占位；`agent run --watch` 未完整实现。
- `write continue` 的续写素材来自章节库内容 + `--context`，没有 `--text` 参数（修订同理用 `--instruction` 而非 `--text`）。
- 旧文档中的 `write generate` / `export book` / `extract characters|world|outline` / `vector index|search|rebuild` / `project create --genre` 均已不存在（#864 对账），对应现形态见上文。
