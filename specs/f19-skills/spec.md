# F19-skills: skills 包（ADR-022）— 功能规格

> **Spec 版本**: 1.1（2026-08-12 拍板修订：Q1=B / Q3=新决策） | **日期**: 2026-08-12 | **依据**: ADR-022（skills 包形态）、ADR-019 v6（版本里程碑：0.8.0 = 后续语义统一与技术债，2026-08-09 建）、Issue #65 决策 D4、Constitution P1-P6
> **Spec 变更**: v1.0 → v1.1（2026-08-12）：Q1-Q3 用户拍板——Q1=B（全量 23 CLI 组命令参考，**直接复制 Hermes 测试版 inkflow skill 再修改符合实际**，成本顾虑消解）、Q2=🔲 待回执（用户反问 install 语义，正文 §4.3 按「从 GitHub 下载」预修订）、Q3=**新决策**（skills 放 GitHub 主通道 + **后续可能单独打包**，**当前不随安装包下载**——原 A/B/C 三选项全部否决）；正文 §1.1/§2.1/§4.3/§5/§8/§9/§10/§12/§13 联动修订
>
> **所属阶段**: 0.8.0 里程碑（Issue #70，估算 3-5 人天；2026-08-12 用户拍板从 1.0.0 提前——1.0.0 定位改为「正式可用」，skills 提前在实际使用中验证）
>
> **关联 Issues**: [#70](https://github.com/zhx-xi/InkFlow/issues/70)（本任务）· [#65](https://github.com/zhx-xi/InkFlow/issues/65)（决策 D4：AI agent 经 skills 包使用 InkFlow）· [#49](https://github.com/zhx-xi/InkFlow/issues/49)（F20 MCP，0.9.0——本 spec §10 预留 mcp-setup.md 联动，不实现）· [#251](https://github.com/zhx-xi/InkFlow/issues/251)（CLI 命令面缺口补全，0.8.0——CLI 域并行，merge 错开）
>
> **依赖**: ✅ ADR-022（skills 包形态决策）· ✅ F7 CLI 全局约定（`--json` 信封/退出码 0/1/2/130，f7-cli-interface spec §5/§7）· ✅ f19-packaging（PyInstaller 打包链 + release.yml，0.4.0 已交付）· ✅ f33-cli-dist（CLI zip 产物，0.5.0 已交付）· ⚡ #251（CLI 域并行，无代码依赖，merge 错开——roadmap 2026-08-12 拍板）
>
> **参考 ADR**: [ADR-022](../../adr/ADR-022.md)（skills 包：源码单一真相 + 三通道分发）· [ADR-019](../../adr/ADR-019.md)（版本里程碑 v6：skills 后移至 1.0.0 后于 0.8.0 提前）· [ADR-021](../../adr/ADR-021.md)（本地内核进程化：CLI/skills/agent 共享同一内核）· [ADR-023](../../adr/ADR-023.md)（MCP Server：发布后补 mcp-setup.md）
>
> **状态**: 待实现 🔲

## 1. 概述

### 1.1 模块类型定位（分发型基建专项，非业务模块变体）

**分发型基建专项（非业务模块变体）**：不新建业务实体、不新增业务 API 端点、不新增 LLM 管线，为外部 AI agent（Hermes / Claude Code / Codex 等）交付 **skills 包资产 + 管理命令 + 打包收集**，使 agent 经既有 CLI `--json` 契约使用 InkFlow（ADR-022 旅程 C：`project list --json` → 读取设定 → 调用 write 生成章节 → 触发审计 → 结果写回——全程 CLI + JSON，零常驻服务）。

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ 无（skills 包 = Markdown 资产 + YAML frontmatter，非 ORM 实体） |
| 新 API 端点 | ❌ 无（**REST 面零改动**；agent 经 CLI 直连本地内核，ADR-021） |
| 新 CLI 命令 | ✅ `inkflow skills` 子组（list / install / update / verify，§4）——**零后端代码**：本地文件操作 + 纯文档资产，不依赖内核拉起 |
| 核心机制 | 源码 `skills/inkflow/` 单一真相 + **两通道分发**（GitHub 主 / `skills install` 命令——随安装包通道**当前不实施**，后续可能单独打包，Q3 拍板）+ SKILL.md（YAML frontmatter）+ references/ 子目录 |
| 跨模块 MODIFY | `backend/src/inkflow/cli/app.py`（注册 skills 子组）——**inkflow.spec / release.yml / electron-builder 零改动**（Q3 拍板：当前不随安装包下载） |
| 错误面 | F7 信封契约沿用：`{"ok": true, "data": ...}` / `{"ok": false, "error": {"code", "message"}}`，退出码 0/1/2/130 |

**变体编号声明**：本模块为 F19 家族 0.8.0 子任务（F19 GUI 家族拆分条目：0.3.0 GUI 壳 / 0.4.0 打包分发 / 本任务 skills 包），按 AGENTS.md 模块类型谱系「F19 GUI」条目归类，**不占用业务模块变体编号**（f19-packaging「打包分发专项」同口径）。

### 1.2 关键事实（现状盘点，2026-08-12 实测）

- ❌ 主仓**无 `skills/` 目录**（`Test-Path D:\develop\projects\InkFlow\skills` = False）——源码单一真相为零起点新建
- ✅ CLI 组样板成熟：`backend/src/inkflow/cli/app.py`（23 组子命令注册，`app.add_typer(...)` 模式）+ `commands/*.py`（薄层）+ `context.py`/`output.py`（`print_result`/`print_error` 信封，F7 契约）
- ✅ **本地命令豁免先例（f38-cli-http §1.3）**：`config`/`llm`/`agent tools list` 因操作本地文件/静态资源被豁免 HTTP 改造——**skills 命令组同族**（本地文件操作 + GitHub 下载，无对应 API 端点，不 ensure_kernel）
- ✅ **Hermes 测试版 inkflow skill 蓝本（Q1=B 依据，2026-08-12 实测）**：本环境技能库已有 `inkflow` skill v0.1.0——SKILL.md（YAML frontmatter）+ **20 个 references**（kernel/projects/chapters/writing/audit/library-*/models/templates/agent/memory/export/style/extract/system/workflows-*）+ 2 scripts，**全量 23 CLI 组命令面已覆盖**——源码 `skills/inkflow/` 以**复制此蓝本再修改**为起点（去 Hermes 特有视角、改为通用 agent 使用指南），非从零写作
- ✅ 打包链现状（Q3 拍板后**不消费**）：`backend/pyinstaller/inkflow.spec`（128 行）`collect_all("inkflow")` 只收集 Python 包内数据文件——skills 包位于仓库根 `skills/`（非 Python 包）静态分析不可见，若未来随包需显式 `datas`（**本任务不做，Q3 拍板「当前不随安装包下载」；后续单独打包时另行评估**）
- ✅ release.yml（283 行，tag `v*` 触发）：package-backend job 已有「Packaged kernel smoke」step（#253 rc6 教训固化：打包产物冒烟，断言无 ModuleNotFoundError）——**skills 数据完整性冒烟同族接入**（漂移验证四件套 #1）
- ✅ 版本注入链：tag → pyproject → `copy_metadata('inkflow')` → INKFLOW_READY.version（f19-packaging §2.4）；`inkflow --version` = `importlib.metadata.version("inkflow")`
- ✅ F7 spec §5/§7：信封结构、退出码 0（成功）/1（业务错误）/2（用法错误）/130（Ctrl+C）
- ✅ f33-cli-dist：CLI zip 产物 `InkFlow-cli-<ver>-x64.zip`（PyInstaller onedir 整体打 zip，零新增构建）——**随安装包通道的 CLI 形态载体**
- ✅ Hermes 技能库先例（本环境）：SKILL.md = YAML frontmatter（name/description/version/触发条件）+ 正文使用说明 + `references/` 子目录分主题文档——skills 包结构对标此形态
- ✅ #49 MCP 挂 0.9.0（milestone #12），OPEN——mcp-setup.md 联动为远期预留（§10）

### 1.3 边界声明

- **不含** MCP Server 实现（#49，0.9.0）；本 spec 仅预留 skills 包内 `mcp-setup.md` 槽位（§10.1），MCP 发布后补写
- **不含** 任何业务 REST 端点 / ORM / 领域逻辑改动
- **不含** CLI 恒 HTTP 化改造（f38 已交付，本任务新命令组天然豁免——本地文件操作 + GitHub 下载无内核依赖）
- **不含随安装包分发**（Q3 拍板：当前不随安装包下载；后续可能单独打包，另行评估 PyInstaller datas / 独立包形态）
- **不含** skills 内容的大规模从零写作（Q1=B 拍板：以 Hermes 测试版 inkflow skill 为蓝本复制修改，非新写）
- **不含** agent 侧安装引导（Hermes 等外部 agent 的 skills 安装机制由各 agent 自身实现；InkFlow 只交付资产 + 安装指引文档）

---

## 2. 数据模型与资产契约

### 2.1 skills 包目录结构（源码单一真相，ADR-022 决策；Q1=B 以 Hermes 测试版蓝本复制改造）

```
skills/inkflow/
├── SKILL.md                        # 主入口：YAML frontmatter + 使用说明（必选）
└── references/                     # 分主题参考文档（必选子目录）
    ├── cli-commands.md             # CLI 命令参考（全量 23 组，Q1=B：蓝本复制后按实际命令面核对修改）
    ├── json-contracts.md           # --json 信封契约示例（各命令 data 结构）
    ├── workflows.md                # 使用指南（旅程 C：发现→读取→写作→审计→写回）
    ├── kernel.md                   # 内核生命周期（ensure_kernel/kernel.json/隔离）
    ├── projects.md / chapters.md / writing.md / audit.md   # 核心创作域（蓝本复制）
    ├── library-*.md                # 角色/世界观/大纲/时间线/伏笔/RAG（蓝本复制）
    ├── models.md / templates.md / agent.md / memory.md     # Agent 域（蓝本复制）
    ├── export.md / style.md / extract.md / system.md       # 工具域（蓝本复制）
    └── mcp-setup.md                # 🚧 MCP 设置指南（#49 发布后补写，本任务仅占位说明）
```

> **Q1=B 落地方式**：从 Hermes 技能库 `inkflow` skill（v0.1.0，20 references）**整体复制**到 `skills/inkflow/`，再逐文件修改：① 去除 Hermes 特有视角（「操作手册/验证配方」→ 通用 agent 使用指南）；② 命令示例按真实 `--help`/`--json` 输出核对（ADR-022 同步纪律）；③ version 字段对齐 InkFlow 版本。

### 2.2 SKILL.md frontmatter 契约

```yaml
---
name: inkflow
description: "InkFlow — AI 辅助小说创作：项目/章节/角色/世界观/大纲/时间线管理 + AI 写作与一致性审计。经 CLI --json 契约调用本地内核。"
version: 0.8.0            # 与 InkFlow 版本对齐（ADR-019 SemVer，§5.2 对齐机制）
trigger: "用户需要创作/管理长篇小说项目，或调用 InkFlow 能力时"
---
# InkFlow skill
...
```

**frontmatter 必填字段**：`name`（固定 `inkflow`）/ `description`（agent 触发判断用，须含关键词）/ `version`（SemVer，与 InkFlow 对齐）/ `trigger`（触发条件）。校验规则见 §7 N1-N3。

### 2.3 references/ 文档契约（Q1=B：蓝本 20 文件复制改造）

| 文件 | 内容 | 维护纪律 |
|------|------|----------|
| `cli-commands.md` | **全量 23 CLI 组**命令签名 + 参数 + 示例（蓝本已覆盖，逐条按真实 `--help` 核对）；命令语义描述，**不重复实现逻辑**（ADR-022「skills 文档只描述命令语义与 JSON 结构」） | 命令面变更评审时对照 tests/cli/ 契约测试（ADR-022 影响节） |
| `json-contracts.md` | 各命令 `--json` 信封的 data 结构示例（真实输出抓取，非手写臆造） | 与 tests/cli/ 断言同步更新 |
| `workflows.md` | 旅程 C 分步指南（含失败处理：内核未启动 → `ensure_kernel` 语义说明） | 随功能演进更新 |
| 其余 16 个 references（kernel/projects/chapters/writing/audit/library-*/models/templates/agent/memory/export/style/extract/system） | 蓝本复制后**去 Hermes 视角**（操作手册/验证配方语气 → 通用 agent 指南）+ 按 #251 状态核对 CLI 缺口段 | 同 cli-commands.md |
| `mcp-setup.md` | 🚧 占位：MCP 发布后补 mcp-setup 引导（#49 联动，ADR-023） | 本任务只建占位 + README 说明，不写内容 |

---

## 3. API 契约

**零新增 REST 端点**。skills 命令组操作本地文件系统与随包资产，不走 HTTP（f38 §1.3 本地命令豁免先例）。

| 端点面 | 变更 |
|--------|------|
| `/api/v1/**` 全部既有端点 | ❌ 零改动（本任务不触碰 router/deps/domain/infra） |
| 新增端点 | ❌ 无 |

> agent 执行契约 = CLI `--json`（ADR-022 决策）：skills 文档描述命令语义与 JSON 结构；agent 经 `inkflow <cmd> --json` 与内核交互（F7 信封）。

---

## 4. CLI 命令签名

### 4.1 `inkflow skills` 子组总览

```text
inkflow skills list            # 列出可用 skills（GitHub 官方版本 + 已安装位置）
inkflow skills install         # 从 GitHub 下载安装 skills 包到目标目录（Q2 待回执）
inkflow skills update          # 更新已安装 skills 包（版本校验）
inkflow skills verify          # 校验安装完整性（frontmatter/版本/文件清单）
```

**注册方式**：`app.add_typer(skills.app, name="skills")`（app.py 既有模式）。

**执行模型**：**零后端代码**——GitHub 下载（httpx）+ 本地文件操作（复制/校验/列表），**不 ensure_kernel**（f38 豁免先例：config/llm/agent tools list 同族——但注意：**install 需发 HTTP 到 GitHub**，与 f38 豁免组的「零网络」略有差异，属「下载型本地命令」新形态，Q2 回执确认）。错误面沿用 F7：业务错误 → 退出码 1 + 错误信封；用法错误 → 退出码 2。

### 4.2 `skills list`

```text
inkflow skills list [--json]
```

- 成功信封：`{"ok": true, "data": {"latest": {"version": "0.8.0", "source": "https://github.com/zhx-xi/InkFlow/tree/v0.8.0/skills/inkflow"}, "installed": {"version": "0.8.0", "path": "...", "status": "up-to-date|outdated|missing"}}}`
- `latest` = GitHub 官方最新版本（源 = 仓库 tag 对应路径）；`installed` = Q2 拍板的目标目录
- 无 `--json`：人类可读列表

### 4.3 `skills install`（Q2 预修订：GitHub 下载语义）

```text
inkflow skills install [--target PATH] [--version VERSION] [--force] [--json]
```

- **从 GitHub 官方仓库下载 skills 包**到目标目录（Q2 待回执；默认目标 = `%APPDATA%\InkFlow\skills` 打包版 / `data_dir\skills` dev，`--target` 可覆盖）
- `--version`：指定版本（默认 latest tag）；下载源 = `https://raw.githubusercontent.com/zhx-xi/InkFlow/<tag>/skills/inkflow/...`（官方固定 URL，Q2 确认）
- `--force`：覆盖已安装（版本不一致时更新）；无 `--force` 且已存在同版本 → 退出码 1 `ALREADY_INSTALLED`（N4）
- 成功：`{"ok": true, "data": {"target": "...", "version": "0.8.0"}}`
- **网络失败** → 退出码 1 `SKILLS_DOWNLOAD_FAILED`（N11）；**离线场景提示改用 GitHub 手动 fetch**（ADR-022 主通道语义）

### 4.4 `skills update`

```text
inkflow skills update [--target PATH] [--json]
```

- 已安装 version < GitHub latest → 重新下载覆盖更新；已最新 → 退出码 0 + `{"updated": false, "reason": "up-to-date"}`
- 未安装 → 退出码 1 `NOT_INSTALLED`（N5）

### 4.5 `skills verify`

```text
inkflow skills verify [--target PATH] [--json]
```

- 校验指定（或默认）安装：frontmatter 必填字段齐全（N1）/ `version` SemVer 合法（N2）/ 与 GitHub latest 一致（N3）/ references/ 必需文件存在（N6）
- 成功：`{"ok": true, "data": {"target": "...", "checks": {"frontmatter": true, "version": "0.8.0", "files": 20}, "status": "ok"}}`
- 任一失败：退出码 1 + 错误信封（code 见 §7 表）

---

## 5. 关键差异节：分发型分发矩阵 + 版本对齐

### 5.1 分发矩阵（ADR-022 决策落地；Q3 拍板后 = 两通道 + 后续单独打包预留）

| 通道 | 载体 | 消费方 | 版本对齐 | 验证（漂移四件套） |
|------|------|--------|----------|-------------------|
| **1. GitHub 源码 tap/URL（主）** | 仓库 `skills/inkflow/`（tag 对应版本，永远最新） | 外部 agent 直接 fetch；`skills install` 下载源 | 源码 frontmatter version = tag | rc 验证：从 tag 拉取 → `verify` 通过 |
| **2. `inkflow skills install`（辅）** | GitHub 官方仓库下载 → 目标目录（Q2 回执后定稿） | 已装 InkFlow 的用户/agent 手动管理 | verify 对比 GitHub latest | rc 验证：install → verify → list 全链路 |
| **3. 随安装包内置（⏳ 推迟）** | **Q3 拍板：当前不实施**——skills 放 GitHub，后续可能单独打包（PyInstaller datas / 独立包形态另行评估） | 离线/无网络环境（未来） | — | 后续单独打包时补验（漂移四件套 #1 调整，见 §13 M3 注） |

### 5.2 版本对齐机制

- **源码单一真相**：`skills/inkflow/SKILL.md` frontmatter `version` 字段 = InkFlow 当前版本（ADR-019 SemVer）
- **同步纪律**：发布/里程碑收尾时（五项同步流程，inkflow-governance）同步更新 frontmatter version；`skills verify` 在安装侧校验一致性（N3）
- **构建期注入**：不做（skills 包为纯 Markdown 资产，不经 Python 构建；手工同步 + verify 校验即闭环——「待实现确认」：若实现期发现手工同步易漂移，可加 CI 检查步骤，见 §9.1）

### 5.3 随安装包收集（Q3 拍板：当前不实施）

**❌ 已否决（2026-08-12 用户拍板）**：原候选 A（PyInstaller `datas` 显式收集进 `_internal/skills/`）与 B（electron extraResources 旁置 `resources/skills/`）**均不采用**——skills 当前**不随安装包下载**，主分发 = GitHub（仓库 `skills/inkflow/`）。

后续若单独打包（用户 2026-08-12 拍板提及「后续可能单独打包」），另行评估：
- 形态候选：独立 zip（类似 f33 CLI zip 流程）/ PyInstaller datas 进内核 onedir
- 收集缺口教训同族：0.7.0 tiktoken/chromadb（#253）——打包后必须冒烟断言 skills 文件存在
- 本 spec §8.2 不包含任何打包配置 MODIFY（Q3 拍板零改动）

### 5.4 与 f33 CLI zip / release.yml 的关系

- **release.yml 零改动**（Q3 拍板：不随安装包 → 无收集步骤、无冒烟增量）
- f33 CLI zip = `backend/dist/inkflow/` 整体打 zip（release.yml「Package CLI zip」step）——skills 不进内核 onedir，故 CLI zip 也不含 skills（与「当前不随安装包」一致）
- GitHub 主通道 = 仓库源码树 `skills/inkflow/`（tag 版本即发布版本），**不需要任何发布流水线改动**——源码即资产

---

## 6. 组织规则

### 6.1 skills 包内容组织

- `skills/inkflow/` 是**唯一维护源**（ADR-022）：GitHub 主通道 + install 下载均从此目录；**不允许**在各分发位独立维护第二份
- `SKILL.md` 为 agent 入口：description 含触发关键词（§2.2），正文含「安装后如何用」三步起步（`inkflow --help` 探活 → `project list --json` 发现 → journey C 走查）
- `references/` 按主题拆分（命令/契约/工作流/功能域），**单文件 ≤ 300 行**（对标 Hermes 技能库 references 惯例，防 monster 文档）
- 文档与 CLI 契约同步纪律：`cli-commands.md`/`json-contracts.md` 的内容变更必须对照 `tests/cli/` 契约测试（ADR-022 影响节）；实现评审时 grep 文档示例与测试断言一致性
- **蓝本维护关系**：源码 `skills/inkflow/` 与 Hermes 技能库 `inkflow` skill **互为镜像起点但独立演进**（Q1=B 一次性复制后，源码成为权威——后续 Hermes 侧更新以源码为准回灌，不在本任务范围）

### 6.2 CLI 组组织（skills.py）

- 薄层：参数解析/校验 + 本地文件操作，**不 import domain/infra 业务模块**（f38 豁免命令同族）
- `--json` 全局化由根 app callback 提供（`ctx.obj.json_output`），子命令读 `ctx.obj`（F7 约定，kernel.py 样板）
- 路径解析统一走 `config.data_dir` / `sys.frozen` 分支（Q2 拍板后定稿）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 | 错误码 | 退出码 |
|---|------|------|--------|--------|
| N1 | frontmatter 缺必填字段（name/description/version/trigger） | verify 失败，列出缺失字段 | `SKILLS_INVALID_FRONTMATTER` | 1 |
| N2 | version 非合法 SemVer | verify 失败 | `SKILLS_INVALID_VERSION` | 1 |
| N3 | 已安装版本 ≠ GitHub latest | verify 失败（提示 `skills update`） | `SKILLS_VERSION_MISMATCH` | 1 |
| N4 | install 目标已存在同版本且无 `--force` | 拒绝覆盖 | `ALREADY_INSTALLED` | 1 |
| N5 | update 时未安装 | 提示先 install | `NOT_INSTALLED` | 1 |
| N6 | references/ 必需文件缺失（cli-commands.md/json-contracts.md/workflows.md 等蓝本清单） | verify 失败，列出缺失文件 | `SKILLS_MISSING_FILES` | 1 |
| N7 | **GitHub 下载失败（网络/404/tag 不存在）** | install/update 失败 | `SKILLS_DOWNLOAD_FAILED` | 1 |
| N8 | 目标目录不可写（权限/只读） | 复制失败 | `SKILLS_TARGET_UNWRITABLE` | 1 |
| N9 | 非法参数（未知子命令/缺参） | 用法错误 | （typer 默认） | 2 |
| N10 | Ctrl+C 中断 | 优雅退出 | — | 130 |
| N11 | `--version` 指定 tag 不存在 | install 失败，列出可用 tag 提示 | `SKILLS_VERSION_NOT_FOUND` | 1 |

---

## 8. 文件结构

### 8.1 CREATE（新建）

| 文件 | 内容 |
|------|------|
| `skills/inkflow/SKILL.md` | 主入口：frontmatter（§2.2）+ 使用说明（§6.1）——蓝本复制改造 |
| `skills/inkflow/references/*.md` | **20 文件蓝本复制改造**：cli-commands.md（全量 23 组）/ json-contracts.md / workflows.md / kernel.md / projects.md / chapters.md / writing.md / audit.md / library-characters.md / library-world.md / library-outline.md / library-timeline.md / library-foreshadowing.md / library-rag.md / models.md / templates.md / agent.md / memory.md / export.md / style.md / extract.md / system.md / mcp-setup.md（占位）——按 §2.3 契约 |
| `backend/src/inkflow/cli/commands/skills.py` | skills 命令组（§4；GitHub 下载 + 本地管理） |
| `backend/tests/cli/test_cli_skills.py` | CLI 契约测试（RED 先行，§9；mock GitHub 下载） |
| `backend/tests/unit/test_skills_verify.py` | frontmatter/版本校验纯函数测试（§9） |

### 8.2 MODIFY（修改）

| 文件 | 变更 | 节 |
|------|------|-----|
| `backend/src/inkflow/cli/app.py` | 注册 `skills` 子组（`app.add_typer(skills.app, name="skills")`） | §4.1 |
| `AGENTS.md` | 0.8.0 里程碑回写 + F19 家族条目补 skills 子任务（收尾，Phase 8） | — |
| `FEATURES.md` | skills 包功能登记（合入后五项同步） | — |
| `adr/ADR-019.md` | 0.8.0 行补 skills 交付记录（合入后） | — |
| `backend/pyproject.toml` | httpx 已是运行时依赖（HTTP 下载复用，无需新增——待实现确认） | §4.3 |

### 8.3 不修改（明确声明）

- `backend/src/inkflow/api/**`（REST 面零改动）
- `backend/src/inkflow/core/config.py`（skills 路径若走 config.data_dir 派生则只读引用，不改配置结构——Q2 拍板后确认）
- 既有 23 组 CLI 命令（`commands/*.py` 除新增 skills.py 外零改动）
- `.github/workflows/ci.yml`（本任务 PR CI 走既有 job；skills 资产无 Python 代码面 → 覆盖口径见 §9）
- **`backend/pyinstaller/inkflow.spec` / `.github/workflows/release.yml` / `electron-builder.yml`（Q3 拍板：当前不随安装包，打包配置零改动）**

---

## 9. 测试策略

### 9.1 层次与载体

| 层 | 载体 | 覆盖 |
|----|------|------|
| unit | `backend/tests/unit/test_skills_verify.py`（新建） | frontmatter 校验（N1/N2）、版本比较（N3）、下载 URL 构建（tag → raw URL 映射）、路径解析（Q2 定稿后） |
| CLI | `backend/tests/cli/test_cli_skills.py`（新建） | list/install/update/verify 成功路径 + 错误路径（N4-N8/N11），**mock GitHub 下载**（monkeypatch httpx 返回固定包内容 + tmp_path 真实目录落盘），`--json` 信封断言（`json.loads(result.stdout)`） |
| 文档一致性 | 实现期人工 grep | `json-contracts.md` 示例字段 vs tests/cli/ 断言（ADR-022 同步纪律）；**蓝本 20 文件复制后逐文件核对**（去 Hermes 视角残留） |
| 真实下载冒烟 | 本地手工（有网环境） | `skills install` 从 GitHub 实际拉取成功 → `verify` 通过（Q2 回执后定稿） |
| rc 阶段手工 | 漂移验证四件套（§13 M3-M6） | 两通道各验一次 + 注入生效验证 |

### 9.2 关键场景

1. **两通道闭环**：GitHub tag 拉取 → verify 通过；`skills install`（mock 下载）→ `skills verify` → `skills update` 全链路
2. **版本漂移检测**：手工改已安装 frontmatter version → verify 报 `SKILLS_VERSION_MISMATCH`
3. **下载失败检测**：mock 网络异常/404 → `SKILLS_DOWNLOAD_FAILED`（N7）；指定不存在的 `--version` tag → `SKILLS_VERSION_NOT_FOUND`（N11）
4. **蓝本复制完整性**：20 个 references 文件全部落盘（N6 必需清单校验）

### 9.3 覆盖率

- 新增 CLI 薄层 + 校验函数走 pytest 覆盖率口径（CI coverage-backend 98.5/95.0 不变，ADR-027）
- skills Markdown 资产非代码面，不进覆盖率口径；其正确性由文档一致性 grep + rc 冒烟验证
- **无打包冒烟**（Q3 拍板：当前不随安装包 → release.yml 无 skills 相关步骤，漂移验证 #1 调整为 GitHub 资产完整检查，见 §13 M3）

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| MCP Server 实现 | **#49**（0.9.0）；ADR-023——本任务仅预留 `references/mcp-setup.md` 占位，**不实现** |
| mcp-setup.md 内容写作 | #49 发布后补（ADR-022 演进预留）；占位文件注明「MCP 发布后填写」 |
| **随安装包分发** | **Q3 拍板（2026-08-12）**：当前不随安装包下载；后续可能单独打包，另行评估（§5.3） |
| skills 内容从零写作 | Q1=B 拍板：以 Hermes 测试版 inkflow skill 蓝本复制改造（§2.1），非新写 |
| 自定义 skills 上传/发布（用户自写 skills 分发） | 未立项；本任务只交付官方 skills 包 + 下载安装（Q2 回执确认范围） |
| agent 侧自动安装/注册（Hermes 等自动加载 skills） | 各 agent 自身机制；InkFlow 交付资产 + 安装指引（SKILL.md 正文） |
| REST 端点 / 业务实体 / LLM 管线 | 本任务零业务代码 |
| macOS/Linux 打包 | 沿用 f19-packaging §10（1.0.0 跨平台事项） |

---

## 11. 依赖关系

### 11.1 依赖（本任务需要的既有交付）

| 依赖 | 交付 | 用途 |
|------|------|------|
| ADR-022 | ✅ 已接受 | 形态决策（单一真相 + 三通道 + CLI 契约） |
| F7 CLI 全局约定 | ✅ 已实现 | 信封/退出码/错误码契约（§4 全部命令） |
| f19-packaging | ✅ PR #144 | PyInstaller 链 + release.yml（§5.3 收集落点） |
| f33-cli-dist | ✅ PR #181 | CLI zip 产物（§5.4：随安装包通道 CLI 形态载体） |
| f38-cli-http | ✅ PR #213 | 本地命令豁免先例（§4.1 执行模型依据） |
| #251 CLI 缺口补全 | ⚡ 0.8.0 并行 | 无代码依赖；CLI 域同批 merge 错开（roadmap 拍板） |
| #49 MCP | ⏳ 0.9.0 | mcp-setup.md 联动（§10，本任务不阻塞） |

### 11.2 被依赖（下游）

| 下游 | 依赖本任务的什么 |
|------|------------------|
| 外部 AI agent 生态 | skills 包资产（ADR-022 旅程 C 落地） |
| release-verification 流程 | rc 阶段漂移验证四件套（§13 M4-M7，2026-08-12 用户拍板 load-bearing） |
| #49 MCP | 发布后 mcp-setup.md 槽位就绪（占位已建） |
| 1.0.0「正式可用」 | skills 提前 0.8.0 实测验证，1.0.0 只做收尾（#70 拍板记录） |

### 11.3 编号口径声明

F19 为拆分条目：GUI 壳（0.3.0）/ 打包分发（0.4.0）/ skills 包（0.8.0 本任务）——以 ADR-019 v6 与 2026-08-12 拍板记录为准（原 1.0.0 归属被提前拍板重排）。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| D1 | **源码单一真相 `skills/inkflow/`** | 仓库根目录唯一维护源，所有分发均从此复制 | ADR-022 决策承接；无双份漂移 | 各分发位独立维护（双份漂移，ADR-022 备选已否决） |
| D2 | **两通道分发** | GitHub（主）+ install 命令（辅）；随安装包推迟 | ADR-022 决策承接；Q3 拍板（2026-08-12）：当前不随安装包，后续可能单独打包 | 三通道原样（随安装包当前不实施）；单通道（覆盖不足） |
| D3 | **skills 命令组零后端代码** | GitHub 下载 + 本地文件操作，不 ensure_kernel/不走内核 HTTP | f38 豁免先例同族；零常驻依赖（ADR-022「零后端代码可先行交付」） | 经内核 HTTP（需内核拉起，违背零后端；且无对应端点） |
| D4 | **首版内容 = 全量命令面（Q1=B ✅ 已确认：用户拍板，2026-08-12）** | **复制 Hermes 测试版 inkflow skill（20 references）再修改符合实际** | 用户提供蓝本消解「全量写作成本高」顾虑；蓝本已覆盖 23 CLI 组，复制改造远快于从零写 | A journey C 子集（范围不足，蓝本已有全量）；C 子集+骨架（无意义，蓝本全量现成） |
| D5 | **安装语义 = GitHub 官方下载（Q2 预修订，待回执）** | install/update/verify 从 GitHub 官方仓库下载/比对，不做内置复制 | Q3 拍板后无内置资产来源；GitHub 主通道天然是唯一权威源（ADR-022 主通道语义） | 内置复制（随安装包已否决，无源可复）；仅打印指引（名不副实） |
| D6 | **随安装包收集 = 当前不实施（Q3 ✅ 已确认：用户拍板，2026-08-12）** | skills 放 GitHub，后续可能单独打包（另行评估） | 用户拍板「当前不随安装包下载」；源码即资产零发布改动；0.7.0 收集缺口风险本期不存在 | A PyInstaller datas（用户否决）；B electron extraResources（用户否决）；C A+B 双放（用户否决） |

> Q2 回执后，D5 更新为 ✅ 已确认（用户拍板：选项 X）并同步 §4.3/§5.1/§8 正文。

---

## 13. 验收标准

| # | 验收项（M 行） | 验证方式 | 载体 |
|---|---------------|----------|------|
| M1 | `skills/inkflow/` 资产完整落盘：SKILL.md（frontmatter 四必填字段）+ references/ 蓝本 20 文件（含 mcp-setup.md 占位）复制改造完成 | 源码树检查 + unit 校验测试 + 蓝本 diff 核对 | 单元 |
| M2 | `inkflow skills list/install/update/verify` 真实可用：全命令 `--json` 信封正确、退出码 0/1/2 符合 F7；install（mock 下载）→verify→update 闭环通过 | `backend/tests/cli/test_cli_skills.py` 全绿 + 手工 CLI 走查 | CLI 测试 + 手工 |
| M3 | GitHub 资产完整（漂移四件套 #1 调整版）：tag 上 `skills/inkflow/` 文件完整（20 references + SKILL.md），frontmatter version = tag；`skills list` 显示 latest 与 installed 状态 | rc 阶段从 tag 拉取核对（原「打包产物数据完整」因 Q3 拍板不随安装包，调整为 GitHub 资产检查；后续单独打包时补验打包产物） | 手工 + 脚本 |
| M4 | CLI/API skill 命令真实可用（漂移四件套 #2）：`inkflow skills list --json` 返回 latest/installed，无 ModuleNotFoundError | 本地 + 打包 exe 实测 | 手工 + 脚本 |
| M5 | skill 注入生效（漂移四件套 #3）：外部 agent（Hermes/Codex 等）加载 skills 包后执行旅程 C 任务，**决策轨迹可见实际调用 `inkflow <cmd> --json`**（非静默忽略），命令参数符合 cli-commands.md | rc 阶段真实 agent 走查，决策轨迹截图/日志留档 | 手工 |
| M6 | 两通道分发各验一次（漂移四件套 #4 调整版）：① GitHub tag 拉取 `skills/inkflow/` → verify 通过；② `skills install`（真实下载）→ verify 通过（原三通道验证因随安装包推迟改为两通道；单独打包通道启用时补验） | rc 阶段逐通道验证 | 手工 + 脚本 |
| M7 | 版本对齐：源码 frontmatter version = 当前版本 = tag；verify 对版本漂移报 `SKILLS_VERSION_MISMATCH` | N3 测试 + rc 检查 | 单元 + 手工 |
| M8 | 既有测试全绿：backend unit/integration/coverage（98.5/95.0）+ frontend 三层 | ci.yml PR 全绿 | CI |
| M9 | mcp-setup.md 占位存在且标注「MCP 发布后填写」（#49 联动预留，不实现内容） | 源码检查 | 静态 |

> 完成标准映射：M1-M2 = 资产 + 命令面；M3-M6 = 漂移验证四件套（2026-08-12 用户拍板 load-bearing，#1/#4 因 Q3「不随安装包」拍板调整——打包产物 → GitHub 资产、三通道 → 两通道）；M7 = 版本对齐（ADR-022）；M8 = 质量门禁；M9 = #49 联动预留。

---

## 待澄清问题（≤3，阻塞级）

1. **Q1 skills 包首版内容范围**：
   - A：journey C 子集（cli-commands.md 只写 project/chapter/write/audit/export 等旅程 C 命令 + json-contracts + workflows 三文件起步）
   - B：全量 23 CLI 组命令参考（写作成本高，内容将随产品演化漂移）
   - C：journey C 子集 + 预留全量骨架（references 目录含各命令占位节，后续迭代填充）
   - **✅ 已确认（用户拍板：选项 B，2026-08-12）**——原建议 A 因「Hermes 已有测试版 inkflow skill 可直接复制修改」被推翻：以 Hermes 技能库 `inkflow` skill v0.1.0（20 references 全量命令面）为蓝本**整体复制再修改符合实际**，成本顾虑消解。正文 §2.1/§2.3/§8.1 已按 B 修订（蓝本复制改造），D4 同步 ✅。
   - 影响：§8.1 文件内容规模、估算（复制改造 ≈ 2-3 人天，含逐文件核对）

2. **Q2 `skills install` 语义与目标路径**：
   - A：复制到 `%APPDATA%\InkFlow\skills`（打包版）/ `data_dir\skills`（dev，随 config.data_dir 派生）——统一管理入口
   - B：复制到用户指定目录（`--target` 必填），默认不写系统目录
   - C：仅打印安装指引（SKILL.md 内容 + 建议目录），不做文件复制
   - **🔲 待回执（2026-08-12 用户反问：「这是用户下载自定义skills的命令吗？」）**——原建议 A+`--target` 按 Q3 拍板联动修正：**install = 从 GitHub 官方仓库下载 skills 包到本地**（Q3 后无内置资产来源；GitHub 主通道即权威源）。正文 §4.3/§5.1/§12 D5 已按「GitHub 下载」预修订，待用户回执确认后补标 ✅。
   - 回执重点：① install 是否就是「从 GitHub 下载官方 skills」；② 默认目标路径（建议 A 的 `%APPDATA%\InkFlow\skills` / `data_dir\skills`）；③ 是否支持 `--version` 指定版本
   - 影响：§4.3 命令签名、§8.1 skills.py 下载逻辑、D5

3. **Q3 随安装包通道的收集方式**：
   - A：PyInstaller `datas` 显式收集进 `_internal/skills/`（推荐：GUI 包 + CLI zip 双覆盖，release.yml 零改动）
   - B：electron extraResources 旁置 `resources/skills/`（GUI 包专用，CLI zip 不含——纯 CLI 用户第三通道失效）
   - C：A + B 双放（覆盖最全，但双处收集 + 双处冒烟）
   - **✅ 已确认（用户拍板：新决策，2026-08-12）——A/B/C 全部否决**：skills 放 GitHub 主通道 + **后续可能单独打包**，**当前不随安装包下载**。正文 §1.1/§1.2/§5.1/§5.3/§5.4/§8.2/§8.3/§9/§10/§13 已联动修订（两通道 + 打包配置零改动 + 漂移四件套 #1/#4 调整），D6 同步 ✅。
   - 影响：§5.3（不实施）、§8.2/§8.3（inkflow.spec/release.yml/electron-builder 零改动）、§13 M3/M6（漂移验证调整）
