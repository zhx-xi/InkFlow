# F7: CLI 命令行接口 (cli_interface) — 功能规格
> **端**: backend

> **Spec 版本**: 1.0 | **日期**: 2026-07-31 | **依据**: PRD v2.1 §6.1 F7, Constitution P1-P6
> **所属阶段**: Phase 1 — 核心引擎
> **关联 Issues**: [#7](https://github.com/zhx-xi/InkFlow/issues/7)
> **依赖**: F1-F6 全部（对外统一入口）
> **参考 ADR**: [ADR-007v2](../../adr/architecture/ADR-007v2.md) (包结构), [ADR-012](../../adr/architecture/ADR-012.md) (错误处理), [ADR-016](../../adr/service/ADR-016.md) (loguru 日志), [ADR-017](../../adr/test-ci/ADR-017.md) (CI 门禁)
> **状态**: ✅ 已实现（PR #28）

---

## 1. 概述

基于 **Typer** 的命令行入口 `inkflow`：嵌套子命令树（serve / project / chapter / write / llm / config），全命令支持 `--json` 结构化输出，原生 Shell 补全（Bash / Zsh / Fish / PowerShell）与逐级 `--help`。

**核心价值**: 用户在终端完成「建项目 → 建章节 → 写作 → 配置模型」全流程；脚本化集成（`--json`）与交互式使用（人类可读输出）双模式并存；命令层是**薄封装**，业务逻辑全部委托 F1-F6 领域服务，不复制业务规则。

**命令结构约定**（PRD §6.1 F7）: `inkflow <subcommand> <action> [options]`。

---

## 2. 命令树总览

```
inkflow
├── serve                          # 启动 Web 服务器（uvicorn）
├── project                        # 项目/书籍管理（委托 F1）
│   ├── create  ─ list ─ get ─ update ─ delete
├── chapter                        # 卷/章节管理（委托 F2）
│   ├── create  ─ list ─ get ─ update ─ delete ─ move
├── write                          # 写作（委托 F3，内部调用 F6 上下文）
│   ├── next ─ continue ─ revise
├── llm                            # LLM Provider / API Key（委托 F5）
│   ├── list ─ set-key
├── config                         # 应用配置
│   ├── show ─ set
└── 全局: --json · --version · --install-completion · --show-completion · --help
```

> `project restore`（回收站恢复）由 F1 spec §4 定义，F7 落地时并入 `project` 组。

### 2.1 各命令组职责与依赖映射

| 命令组 | 职责 | 委托服务 | 对应模块 |
|--------|------|----------|----------|
| `serve` | 启动 FastAPI Web 服务 | uvicorn + `api/app.py` | F1-F6 聚合 |
| `project` | 项目 CRUD | `ProjectService` | F1 |
| `chapter` | 卷/章节 CRUD + 移动 | `ChapterService` | F2 |
| `write` | next/continue/revise 写作 | `WritingService`（内部经 F6 组装上下文） | F3 + F6 |
| `llm` | Provider 列表、API Key 管理 | `APIKeyManager` / provider 配置 | F5 |
| `config` | 应用配置查看/设置 | `core/config.py` | 基础设施 |

---

## 3. 全局选项

| 选项 | 说明 |
|------|------|
| `--json` | 所有命令输出 JSON 信封（§5）。挂在根 app，子命令自动继承 |
| `--version`, `-V` | 打印版本号（来自 `pyproject.toml`）并退出 |
| `--install-completion [bash\|zsh\|fish\|powershell]` | 安装 Shell 补全脚本（Typer/Click 原生） |
| `--show-completion [bash\|zsh\|fish\|powershell]` | 显示补全脚本内容 |
| `--help` | 每级命令自动生成帮助（Typer 原生，含选项/参数说明） |

**实现要点**（Typer）:

```python
app = typer.Typer(
    name="inkflow",
    help="InkFlow — AI 长篇小说创作工具",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# 全局 --json：挂在根 app 的 callback，存入 Context 供各命令读取
@app.callback()
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="输出 JSON 信封格式"),
    version: bool = typer.Option(False, "--version", "-V", help="显示版本号"),
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()
    ctx.obj = CliContext(json_output=json_output)
```

---

## 4. 各命令组详细签名

### 4.1 serve

```bash
inkflow serve [--host <str>] [--port <int>] [--open-browser] [--reload]
```

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `127.0.0.1` | 监听地址 |
| `--port` | `8000` | 监听端口 |
| `--open-browser` | False | 启动成功后自动打开浏览器（PRD 可选） |
| `--reload` | False | 开发模式热重载（uvicorn --reload） |

**行为**: 阻塞式启动 uvicorn（`uvicorn.run("inkflow.api.app:app", ...)`）；启动成功日志经 loguru 输出（ADR-016）。`--json` 模式下打印一次启动信封后进入服务循环。

### 4.2 project（委托 F1）

```bash
inkflow project create --name <str> [--genre <str>] [--language <str>] [--target-words <int>] [--json]
inkflow project list   [--search <str>] [--sort <name|updated_at|created_at>] [--sort-desc/--no-sort-desc] [--json]
inkflow project get    --id <uuid> [--json]
inkflow project update --id <uuid> [--name <str>] [--genre <str>] [--language <str>] [--target-words <int>] [--json]
inkflow project delete --id <uuid> [--force] [--permanent] [--json]
```

参数语义、验证规则与 F1 spec §4 一致（软删除默认、`--force` 跳过二次确认、`--permanent` 硬删除）。

### 4.3 chapter（委托 F2）

```bash
inkflow chapter create --project-id <uuid> --title <str> [--volume-id <uuid>] [--content <str>] [--json]
inkflow chapter list   --project-id <uuid> [--volume-id <uuid>] [--status <draft|writing|review|final>] [--json]
inkflow chapter get    --id <uuid> [--json]
inkflow chapter update --id <uuid> [--title <str>] [--content <str>] [--status <str>] [--volume-id <uuid>] [--json]
inkflow chapter delete --id <uuid> [--force] [--json]
inkflow chapter move   --id <uuid> [--to-volume <uuid>] [--json]
```

参数语义与 F2 spec §4 一致。

### 4.4 write（委托 F3，内部调用 F6）

```bash
inkflow write next     --project-id <uuid> [--count <int>] [--target-words <int>] [--show-context] [--json]
inkflow write continue --project-id <uuid> --chapter-id <uuid> [--target-words <int>] [--show-context] [--json]
inkflow write revise   --chapter-id <uuid> --instruction <str> [--json]
```

| 子命令 | 语义 | 输出 |
|--------|------|------|
| `next` | 按大纲/前文续写下一章（`--count` 默认 1） | 每章 `{chapter_id, title, word_count}`；`--json` 时含正文 |
| `continue` | 续写指定章节 | 章节全文 + `{chapter_id, word_count}` |
| `revise` | 基于 `--instruction` 修订指定章节 | 修订后章节全文 |

**`--show-context`**: 打印本次 F6 组装的上下文（每层块标题/token/压缩标记 + 预算 + 丢弃项），人类可读或随 `--json` 输出 `context` 字段 —— F6 联调与调试入口（见 F6 spec §6）。

**交互确认**: 无 `--json` 时，`write next --count N` 输出写作进度摘要；写作失败（LLM 错误）输出错误信息并退出码 1。

### 4.5 llm（委托 F5）

```bash
inkflow llm list    [--json]
inkflow llm set-key --provider <str> [--key <str>]
```

| 子命令 | 说明 |
|--------|------|
| `list` | 列出已配置 Provider：`provider`、`default_model`、`key 状态`（已配置/未配置，Key 仅显示掩码 `sk-****abc`） |
| `set-key` | 设置 Provider API Key。不传 `--key` 时交互式输入（`getpass`，**不回显**）；传 `--key` 时打印 WARNING（提示 shell history 泄露风险） |

**存储**: 经 F5 `APIKeyManager` AES-256-GCM 加密落盘（`{data_dir}/keys/{provider}.enc`），明文不落盘、不输出。

### 4.6 config

```bash
inkflow config show [--json]
inkflow config set <key> <value> [--json]
```

**可设置 key 白名单**（其余拒绝，退出码 2）:

| key | 说明 | 示例值 |
|-----|------|--------|
| `default.model` | 默认模型 | `deepseek/deepseek-chat` |
| `default.temperature` | 默认温度 [0,2] | `0.7` |
| `context.max_ratio` | 上下文预算比例 (0,1] | `0.8` |
| `context.default_window` | 未知模型兜底窗口 | `128000` |
| `server.host` | serve 默认 host | `127.0.0.1` |
| `server.port` | serve 默认 port | `8000` |

**持久化**: `{data_dir}/config.json`；优先级 `环境变量 > config.json > 内置默认值`（config set 写入 config.json）。`config show` 同时展示三层来源与生效值。

---

## 5. --json 输出格式（统一信封）

所有命令（含 serve）在 `--json` 下输出**统一信封**，成功/失败结构一致：

```json
// 成功
{"ok": true, "data": <payload>}

// 失败（退出码 1）
{"ok": false, "error": {"code": "NOT_FOUND", "message": "项目不存在"}}
```

**约定**:
- 信封输出到 **stdout**；人类可读模式下的错误信息输出到 **stderr**
- `data` payload 语义由各命令定义：单对象 / 对象数组 / `{items, total}` 分页结构（沿用 F1/F2 既有 payload 结构）
- `write` 命令额外约定 `data` 含 `context` 字段（当 `--show-context` 时）
- 人类可读模式使用 emoji 前缀（✅/❌）与简洁文案（沿用 F1/F2 既有风格）
- 敏感信息（API Key）在任何模式下都只输出掩码
- 现有 F1/F2 `project`/`chapter` 命令输出为裸对象，**F7 落地时统一迁移为信封格式**（`data` 即原裸对象），并同步更新 F1/F2 对应 CLI 测试

**示例**:

```bash
inkflow project create --name "星辰变" --genre 玄幻 --json
→ {"ok": true, "data": {"id": "3f2e1d4a-...", "name": "星辰变", "genre": "玄幻", ...}}

inkflow write next --project-id 3f2e1d4a-... --count 1 --show-context --json
→ {"ok": true, "data": {"chapters": [{"chapter_id": "...", "title": "第 6 章", "word_count": 3120}],
                        "context": {"budget_tokens": 51200, "total_tokens": 6420,
                                    "blocks": [...], "dropped": [...]}}}

inkflow project get --id 00000000-0000-0000-0000-000000000000 --json
→ {"ok": false, "error": {"code": "NOT_FOUND", "message": "项目不存在"}}   # 退出码 1
```

---

## 6. Shell 补全

**方案**: Typer/Click 原生补全（`click.shell_completion`），不引入额外依赖。

```bash
inkflow --install-completion bash          # 写入 ~/.bashrc
inkflow --install-completion zsh           # 写入 ~/.zshrc
inkflow --install-completion fish          # 写入 ~/.config/fish/completions
inkflow --install-completion powershell    # 写入 $PROFILE
```

| 验收项 | 标准 |
|--------|------|
| 补全覆盖 | 命令组、子命令、选项名全部可补全（`inkflow write <TAB>` → next/continue/revise） |
| 参数提示 | 选项的 value hint（如 `--genre <玄幻|科幻|...>`、`--status <draft|writing|review|final>`） |
| 四种 Shell | Bash / Zsh / Fish / PowerShell 安装脚本无报错 |
| 动态性 | 命令树变更后重新安装即生效（Click 动态生成脚本，无需手动维护） |

**验收测试**: 四种 shell 各执行一次 `--show-completion <shell>` 输出非空且包含子命令名；CI 中至少验证 bash/zsh 脚本生成。

---

## 7. 错误处理与退出码

| 退出码 | 场景 | 输出 |
|--------|------|------|
| 0 | 成功 | 正常输出 |
| 1 | 业务/运行时错误（404/422 业务校验、LLM 失败、DB 错误、config key 非法值） | 人类模式 → stderr 错误文案；`--json` → 错误信封（stdout） |
| 2 | 用法错误（缺失必填参数、未知命令/选项、非法枚举值、config set 白名单外 key） | Typer/Click 默认 usage 信息 |
| 130 | Ctrl+C（含 serve 优雅退出） | — |

**错误分类映射**（ADR-012）:

| 异常 | 错误码 | 人类文案示例 |
|------|--------|-------------|
| 资源不存在（F1/F2 404） | `NOT_FOUND` | 项目不存在 / 章节不存在 |
| 业务校验失败 | `VALIDATION_ERROR` | 项目名称不能为空 |
| LLM 调用失败（F5） | `LLM_ERROR` | LLM 调用失败: API key not configured for provider: deepseek |
| 上下文预算超限（F6） | `CONTEXT_BUDGET_EXCEEDED` | 上下文预算超限: protected 层需要 20000 tokens, 预算 15360 |
| 配置非法 | `CONFIG_ERROR` | 未知配置项: foo.bar |
| 数据库错误 | `DB_ERROR` | 数据库操作失败（不泄漏堆栈，loguru 记录详情） |

**二次确认**（project delete 等）: 非 `--json` 且无 `--force` 时交互确认（沿用 F1 spec §4.2）；`--json` 模式下二次确认**跳过**（脚本化场景不可交互），等效 `--force` 语义但仅在明确传入 `--force` 时执行删除 —— 即 `--json` + 无 `--force` 时删除操作报错 `VALIDATION_ERROR: 删除需 --force 或交互确认`。

---

## 8. 文件结构

遵循 ADR-007v2 包结构，新增/修改文件：

```text
backend/src/inkflow/
├── cli/
│   ├── __init__.py               ← MODIFY
│   ├── app.py                    ← CREATE: 根 Typer app + 全局 callback（--json/--version）
│   ├── output.py                 ← CREATE: 人类/JSON 双模式格式化 + 错误信封 + 退出码
│   ├── context.py                ← CREATE: CliContext（共享 --json 状态等）
│   └── commands/
│       ├── __init__.py           ← MODIFY
│       ├── serve.py              ← CREATE: serve 命令（uvicorn 启动）
│       ├── project.py            ← MODIFY: 信封化迁移 + --json 全局化（F1 已有）
│       ├── chapter.py            ← MODIFY: 信封化迁移 + --json 全局化（F2 已有）
│       ├── write.py              ← CREATE: write 组（委托 F3，--show-context 经 F6）
│       ├── llm.py                ← CREATE: llm 组（list / set-key，委托 F5 APIKeyManager）
│       └── config.py             ← CREATE: config 组（show / set）
├── __main__.py                   ← MODIFY: 瘦身为入口（python -m inkflow → cli.app），serve 逻辑迁出
└── core/
    └── config.py                 ← MODIFY: 支持 config.json 读写 + 环境变量覆盖

backend/pyproject.toml            ← MODIFY: [project.scripts] inkflow = "inkflow.cli.app:main"

backend/tests/
├── conftest.py                   ← MODIFY: cli_runner fixture（Typer CliRunner, isolate_filesystem）
├── test_cli_output.py            ← CREATE: 信封格式/退出码/掩码规则
├── test_cli_project.py           ← CREATE: project 组（Mock ProjectService）
├── test_cli_chapter.py           ← CREATE: chapter 组（Mock ChapterService）
├── test_cli_write.py             ← CREATE: write 组（Mock F3 + F6，含 --show-context）
├── test_cli_llm.py               ← CREATE: llm 组（Mock APIKeyManager）
├── test_cli_config.py            ← CREATE: config 组（临时 data_dir）
└── test_cli_serve.py             ← CREATE: serve 组（Mock uvicorn.run）
```

---

## 9. 测试策略

### 测试层次

```
单元测试: 输出格式化（信封/人类模式/掩码）       ~8 cases
命令组测试: Typer CliRunner + Mock Service        ~30 cases
集成测试: config.json 读写（临时目录）            ~4 cases
```

### 关键测试场景

**全局**: `--json` 全局生效 / `--version` 输出 / 无参数时显示 help 且退出码 2 / 未知命令退出码 2 / 每级 `--help` 非空

**project/chapter**: 各子命令成功路径（Mock Service 断言参数透传）/ 404 错误 → 退出码 1 + 错误信封 / 缺参 → 退出码 2 / delete 无 `--force` 交互确认 / `--json` + delete 无 `--force` → VALIDATION_ERROR

**write**: next/continue/revise 成功路径 / `--show-context` 输出 context 字段 / LLM 失败 → LLM_ERROR 信封 / 参数透传（count/target-words/instruction）

**llm**: list 输出掩码 Key / set-key 交互输入（mock getpass）不回显 / set-key 写盘加密（Mock APIKeyManager 断言调用）/ `--key` 明文参数输出 WARNING

**config**: show 三层来源 / set 合法 key 写入 / set 未知 key 退出码 2 / set 非法值（temperature=3.0）退出码 1

**serve**: Mock uvicorn.run 断言 host/port/reload 透传 / `--open-browser` 触发 webbrowser.open（Mock）

---

## 10. 不在范围内

| 项 | 原因 |
|----|------|
| character / world / outline / audit / export 命令组 | 对应模块 F8-F17 为 Phase 2；命令树按 PRD F7 限定 Phase 1 六组 |
| 交互式 TUI / 富终端界面 | Phase 2 Web UI |
| 命令历史 / 会话恢复 | Phase 2+ |
| 自定义补全逻辑（动态值补全） | 依赖模块 Phase 2 落地后按需增强 |
| 多语言 CLI 文案 | Phase 1 固定中文文案 |
| 遥测 / 用量统计 | Phase 4 云端 |

---

## 11. 依赖关系

```text
F7 依赖:
  F1 (project_service) — project 命令组
  F2 (chapter_service) — chapter 命令组（含 volume）
  F3 (writing_service) — write 命令组（next/continue/revise）
  F5 (llm_service)     — llm 命令组（APIKeyManager / provider 配置）
  F6 (context_service) — write --show-context 调试输出
  F1-F6 聚合           — serve 命令（启动 api/app.py）

F7 被依赖:
  无（对外统一入口）
```

> ⚠️ F7 依赖 F3（writing_service）。若 F3 未就绪，write 命令组可先行以 `NotImplementedError` 占位并输出 `FEATURE_NOT_READY` 错误，其余命令组不受阻塞。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| CLI 框架 | Typer（Click 之上） | PRD 指定；原生嵌套子命令、补全、帮助、rich 支持 |
| 补全 | Typer 原生 `--install-completion` | 零额外依赖，四 shell 覆盖（PRD 验收项） |
| `--json` 实现 | 根 app callback 全局选项 + `ctx.obj` 传递 | 一处声明全局生效，避免每个命令重复定义 |
| 输出格式 | 统一信封 `{"ok", "data"/"error"}` | 脚本化解析稳定；成功/失败结构对称（PRD「JSON Schema 定义输出格式」） |
| 命令层职责 | 薄封装：参数解析 → 委托 domain service → 格式化 | 业务规则不复制进 CLI（Constitution 分层约束）；F1/F2 命令仅做信封迁移 |
| 错误映射 | domain 异常 → 错误码 + 退出码（ADR-012） | 人类可读文案与机器可读信封分离 |
| `--json` + 删除确认 | 跳过交互，强制 `--force` | 脚本场景不可交互，宁缺勿隐式删除 |
| config 持久化 | `{data_dir}/config.json` + env 覆盖 | 简单可靠；与 F5 Key 存储分离（Key 加密、config 明文） |
| 入口 | `inkflow` console_script + `python -m inkflow` | 打包与源码运行双通道 |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 命令树完整：六组命令全部可调用且 `--help` 正常 | `inkflow --help` / 各组 `--help` 手工验证 |
| M2 | 全命令 `--json` 信封输出 + 退出码约定 | `pytest tests/test_cli_output.py -v` 全绿 |
| M3 | project/chapter 信封迁移完成（F1/F2 CLI 测试同步更新） | `pytest tests/test_cli_project.py tests/test_cli_chapter.py -v` 全绿 |
| M4 | write 组联调 F3+F6（含 `--show-context`） | `pytest tests/test_cli_write.py -v` 全绿 + 手工联调 |
| M5 | llm / config 组功能完整（Key 加密、白名单） | `pytest tests/test_cli_llm.py tests/test_cli_config.py -v` 全绿 |
| M6 | Shell 补全四 shell 安装无报错 | 手工验证 + CI 脚本生成检查 |
| M7 | 全量测试 + lint + type check 通过 | CI 门禁（ADR-017）全绿 |
## 14. 动作确认

> 基于 §4 命令签名 + §5 信封 + §7 退出码/错误分类事实的状态流表，不新增行为。

### 14.1 全局选项状态流

| 选项 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| --json | 任意命令 | 输出统一信封 {ok, data/error}（stdout） | {"ok": true, "data": ...} | {"ok": false, "error": {code, message}} → 退出码 1 | 挂在根 app 全局继承；人类模式错误信息 → stderr |
| --version / -V | — | 打印版本号（pyproject.toml）并退出 | 版本号 | — | — |
| --help | 每级命令 | Typer 原生帮助 | 帮助文本（含选项/参数说明） | — | no_args_is_help |
| --install-completion / --show-completion [bash/zsh/fish/powershell] | — | 安装/显示补全脚本 | 写入 rc 文件 / 脚本内容 | — | 四种 Shell 覆盖 |
| 无参数 | — | — | — | 显示 help，退出码 2 | no_args_is_help=True |

### 14.2 命令组状态流

| 命令组 | 前置 | 动作 | 成功 | 失败 | 边界 |
|--------|------|------|------|------|------|
| serve [--host --port --open-browser --reload] | — | uvicorn 启动（阻塞） | 服务运行；--json 打印一次启动信封后进入服务循环 | 启动失败 → 退出码 1 | host 127.0.0.1 / port 8000 默认；Ctrl+C → 130 优雅退出 |
| project create/list/get/update/delete | 委托 F1 | 参数透传 → ProjectService | 人类可读 / 信封 | 404 → NOT_FOUND；422 → VALIDATION_ERROR（退出码 1） | delete 需二次确认；--json + 无 --force → VALIDATION_ERROR「删除需 --force 或交互确认」；--permanent 硬删 |
| chapter create/list/get/update/delete/move | 委托 F2 | 参数透传 → ChapterService | 人类可读 / 信封 | 404 → NOT_FOUND；422 → VALIDATION_ERROR（退出码 1） | — |
| write next/continue/revise | 委托 F3 + F6 | 写作；--show-context 附上下文 | 每章 {chapter_id, title, word_count} / 章节全文；--json 含正文 + context 字段 | LLM 失败 → LLM_ERROR（退出码 1） | next --count 默认 1；revise 用 --instruction |
| llm list / set-key | 委托 F5 | Provider 列表 / API Key 设置 | list 输出掩码 sk-****abc；set-key 成功 | — | set-key 无 --key → getpass 交互输入不回显；传 --key → WARNING（shell history 泄露风险）；Key 密文落盘，明文不落盘不输出 |
| config show / set | — | 配置查看/设置 | show 展示三层来源与生效值；set 合法 key 写入 config.json | set 白名单外 key → 退出码 2；set 非法值（temperature=3.0）→ 退出码 1 | key 白名单 6 项；优先级 环境变量 > config.json > 内置默认 |

### 14.3 错误分类与退出码状态流

| 异常 | 错误码 | 人类文案示例 | 退出码 |
|------|--------|-------------|--------|
| 资源不存在（F1/F2 404） | NOT_FOUND | 项目不存在 / 章节不存在 | 1 |
| 业务校验失败 | VALIDATION_ERROR | 项目名称不能为空 | 1 |
| LLM 调用失败（F5） | LLM_ERROR | LLM 调用失败: API key not configured for provider: deepseek | 1 |
| 上下文预算超限（F6） | CONTEXT_BUDGET_EXCEEDED | 上下文预算超限: protected 层需要 20000 tokens, 预算 15360 | 1 |
| 配置非法 | CONFIG_ERROR | 未知配置项: foo.bar | 1（非法值）/ 2（白名单外 key，见 §4.6） |
| 数据库错误 | DB_ERROR | 数据库操作失败（不泄漏堆栈，loguru 记录详情） | 1 |
| 用法错误（缺失必填参数、未知命令/选项、非法枚举值） | — | Typer/Click 默认 usage 信息 | 2 |
| Ctrl+C（含 serve 优雅退出） | — | — | 130 |

### 14.4 验收锚点

- A1：未知命令 / 缺失必填参数 → 退出码 2 + usage（非业务错误信封）
- A2：project get 不存在 → 退出码 1 + {"ok": false, "error": {"code": "NOT_FOUND", "message": "项目不存在"}}（信封输出 stdout）
- A3：--json + project delete 无 --force → VALIDATION_ERROR「删除需 --force 或交互确认」（脚本场景不隐式删除）
- A4：llm set-key 交互输入不回显；任何模式 Key 只输出掩码（明文不落盘不输出）
- A5：config set 白名单外 key → 退出码 2；set 非法值（temperature=3.0）→ 退出码 1
- A6：write 命令 LLM 失败 → LLM_ERROR 信封 + 退出码 1（人类模式错误 → stderr）
