# F19-skills: skills 包（ADR-022）— 功能规格
> **端**: cross

> **Spec 版本**: 1.2（2026-08-12 拍板修订：Q2 语义反转 + 存储形态定稿） | **日期**: 2026-08-12 | **依据**: ADR-022（skills 包形态）、ADR-019 v6（版本里程碑：0.8.0 = 后续语义统一与技术债，2026-08-09 建）、Issue #65 决策 D4、Constitution P1-P6
> **Spec 变更**: v1.0 → v1.1（2026-08-12）：Q1=B / Q3=新决策 拍板；v1.1 → v1.2（2026-08-12）：**Q2 语义反转**——`skills install` 不是「下载官方 skills」（那是 agent 生态的事，CLI 不管官方包），而是**导入用户自定义 skills 到 InkFlow 本地**；**存储形态定稿 = 文件系统目录 `data_dir/skills/`（deepagents 0.7.5 SkillsMiddleware 现成实现即从文件读取，非数据库）**；范围收敛 = **只做导入+管理，agent 实际使用是其他 issue**；正文 §1/§2/§4/§5/§7/§8/§9/§10/§12/§13 联动修订
>
> **所属阶段**: 0.8.0 里程碑（Issue #70，估算 3-5 人天；2026-08-12 用户拍板从 1.0.0 提前——1.0.0 定位改为「正式可用」，skills 提前在实际使用中验证）
>
> **关联 Issues**: [#70](https://github.com/zhx-xi/InkFlow/issues/70)（本任务）· [#65](https://github.com/zhx-xi/InkFlow/issues/65)（决策 D4：AI agent 经 skills 包使用 InkFlow）· [#49](https://github.com/zhx-xi/InkFlow/issues/49)（F20 MCP，0.9.0——本 spec §10 预留 mcp-setup.md 联动，不实现）· [#251](https://github.com/zhx-xi/InkFlow/issues/251)（CLI 命令面缺口补全，0.8.0——CLI 域并行，merge 错开）
>
> **依赖**: ✅ ADR-022（skills 包形态决策）· ✅ F7 CLI 全局约定（`--json` 信封/退出码 0/1/2/130，f7-cli spec §5/§7）· ✅ f19-packaging（PyInstaller 打包链 + release.yml，0.4.0 已交付）· ✅ f33-cli-dist（CLI zip 产物，0.5.0 已交付）· ⚡ #251（CLI 域并行，无代码依赖，merge 错开——roadmap 2026-08-12 拍板）
>
> **参考 ADR**: [ADR-022](../../adr/ADR-022.md)（skills 包：源码单一真相 + 三通道分发）· [ADR-019](../../adr/ADR-019.md)（版本里程碑 v6：skills 后移至 1.0.0 后于 0.8.0 提前）· [ADR-021](../../adr/ADR-021.md)（本地内核进程化：CLI/skills/agent 共享同一内核）· [ADR-023](../../adr/ADR-023.md)（MCP Server：发布后补 mcp-setup.md）
>
> **状态**: ✅ 已实现（PR #304，2026-08-13）

## 1. 概述

### 1.1 模块类型定位（本地 skills 导入管理型，非业务模块变体）

**本地 skills 导入管理专项（非业务模块变体）**：为 InkFlow 用户提供 **用户自定义 skills 的导入与管理**——用户找到的或自己写的 skills（SKILL.md 目录包）经 CLI 导入到 InkFlow 本地 `data_dir/skills/`，供未来 agent 运行时使用（**本期只做导入+管理，agent 实际使用是其他 issue，用户拍板 2026-08-12**）。

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ 无（**存储 = 文件系统目录** `data_dir/skills/<name>/SKILL.md`，非数据库——deepagents 0.7.5 SkillsMiddleware 现成实现即从文件读取，§1.2 证据） |
| 新 API 端点 | ❌ 无（**REST 面零改动**；纯 CLI 本地文件操作） |
| 新 CLI 命令 | ✅ `inkflow skills` 子组（install / list / verify / remove，§4）——**零后端代码**：本地文件导入/校验/列表，不依赖内核拉起 |
| 核心机制 | **用户自定义 skills 导入**：源（本地路径/GitHub URL）→ 校验 frontmatter（Agent Skills 规范）→ 落盘 `data_dir/skills/<name>/`；**官方 inkflow 操作 skills 不经 CLI 管理**（agent 从 GitHub 自取，ADR-022 主通道语义） |
| 跨模块 MODIFY | `backend/src/inkflow/cli/app.py`（注册 skills 子组）——**inkflow.spec / release.yml / electron-builder 零改动**（Q3 拍板：不随安装包） |
| 错误面 | F7 信封契约沿用：`{"ok": true, "data": ...}` / `{"ok": false, "error": {"code", "message"}}`，退出码 0/1/2/130 |

**变体编号声明**：本模块为 F19 家族 0.8.0 子任务（F19 GUI 家族拆分条目：0.3.0 GUI 壳 / 0.4.0 打包分发 / 本任务 skills 包），按 AGENTS.md 模块类型谱系「F19 GUI」条目归类，**不占用业务模块变体编号**（f19-packaging「打包分发专项」同口径）。

### 1.2 关键事实（现状盘点，2026-08-12 实测）

- ❌ 主仓**无 `skills/` 目录**（`Test-Path D:\develop\projects\InkFlow\skills` = False）——官方 inkflow 操作 skills 资产零起点（Q1=B 蓝本复制，§2.4）
- ✅ **deepagents 0.7.5 SkillsMiddleware 实证（2026-08-12 实测 `middleware/skills.py` 1053 行）**：skills **从文件系统读取**——`SkillsMiddleware(backend=FilesystemBackend(root_dir=...), sources=[...])`，每个 skill = 目录 + `SKILL.md`（YAML frontmatter：name/description/license/compatibility/metadata/allowed-tools）；frontmatter 校验规则（name 1-64 小写字母数字+连字符且须与目录名一致、description 1-1024）；分层 sources（同名后者覆盖前者）；**渐进式披露**（元数据进 system prompt，全文按需 read_file）——**本任务导入的 skills 落盘形态与之完全兼容，未来 agent run 接入零改造**
- ✅ CLI 组样板成熟：`backend/src/inkflow/cli/app.py`（23 组子命令注册，`app.add_typer(...)` 模式）+ `commands/*.py`（薄层）+ `context.py`/`output.py`（`print_result`/`print_error` 信封，F7 契约）
- ✅ **本地命令豁免先例（f38-cli-http §1.3）**：`config`/`llm`/`agent tools list` 因操作本地文件/静态资源被豁免 HTTP 改造——**skills 命令组同族**（本地文件操作，无对应 API 端点，不 ensure_kernel）
- ✅ **Hermes 测试版 inkflow skill 蓝本（Q1=B 依据，2026-08-12 实测）**：本环境技能库已有 `inkflow` skill v0.1.0——SKILL.md（YAML frontmatter）+ **20 个 references**（kernel/projects/chapters/writing/audit/library-*/models/templates/agent/memory/export/style/extract/system/workflows-*）+ 2 scripts，**全量 23 CLI 组命令面已覆盖**——官方 `skills/inkflow/` 以**复制此蓝本再修改**为起点（去 Hermes 特有视角、改为通用 agent 使用指南），非从零写作
- ✅ 打包链现状（Q3 拍板后**不消费**）：`backend/pyinstaller/inkflow.spec`（128 行）`collect_all("inkflow")` 只收集 Python 包内数据文件——skills 包位于仓库根 `skills/`（非 Python 包）静态分析不可见，若未来随包需显式 `datas`（**本任务不做，Q3 拍板「当前不随安装包下载」；后续单独打包时另行评估**）
- ✅ release.yml（283 行，tag `v*` 触发）：package-backend job 已有「Packaged kernel smoke」step（#253 rc6 教训固化：打包产物冒烟，断言无 ModuleNotFoundError）——**本任务不消费**（Q3 拍板：不随安装包，release.yml 零改动）
- ✅ 版本注入链：tag → pyproject → `copy_metadata('inkflow')` → INKFLOW_READY.version（f19-packaging §2.4）；`inkflow --version` = `importlib.metadata.version("inkflow")`
- ✅ F7 spec §5/§7：信封结构、退出码 0（成功）/1（业务错误）/2（用法错误）/130（Ctrl+C）
- ✅ f33-cli-dist：CLI zip 产物 `InkFlow-cli-<ver>-x64.zip`（PyInstaller onedir 整体打 zip，零新增构建）——**背景事实**：skills 不进内核 onedir，CLI zip 不含 skills（与 Q3「不随安装包」一致）
- ✅ Hermes 技能库先例（本环境）：SKILL.md = YAML frontmatter（name/description/version/触发条件）+ 正文使用说明 + `references/` 子目录分主题文档——skills 包结构对标此形态
- ✅ #49 MCP 挂 0.9.0（milestone #12），OPEN——mcp-setup.md 联动为远期预留（§10）

### 1.3 边界声明

- **不含** MCP Server 实现（#49，0.9.0）；本 spec 仅预留官方 skills 包内 `mcp-setup.md` 槽位（§10.1），MCP 发布后补写
- **不含** 任何业务 REST 端点 / ORM / 领域逻辑改动
- **不含** CLI 恒 HTTP 化改造（f38 已交付，本任务新命令组天然豁免——本地文件操作无内核依赖）
- **不含随安装包分发**（Q3 拍板：当前不随安装包下载；后续可能单独打包，另行评估 PyInstaller datas / 独立包形态）
- **不含官方 inkflow skills 的 CLI 管理**（Q2 拍板 2026-08-12：官方 = inkflow 操作 skills，agent 从 GitHub 自取，**CLI 不管理**——本任务 CLI 只管用户自定义 skills 导入）
- **不含 agent 实际使用 skills**（用户拍板 2026-08-12：导入+管理是本期，agent run 注入/消费是其他 issue；deepagents SkillsMiddleware 已就绪，未来接入零改造）
- **不含** agent 侧安装引导（Hermes 等外部 agent 的 skills 安装机制由各 agent 自身实现；InkFlow 只交付官方资产 + 导入命令）

---

## 2. 数据模型与存储契约

### 2.1 存储形态（用户拍板定稿：文件系统目录，非数据库）

**导入目标 = `data_dir/skills/<skill-name>/`**（deepagents FilesystemBackend 可直接作为 root_dir 扫描）。

```
data_dir/skills/                    # 用户自定义 skills 根（config.data_dir 派生）
└── <skill-name>/                   # 目录名 = frontmatter name（Agent Skills 规范强制一致）
    ├── SKILL.md                    # 必选：YAML frontmatter + Markdown 正文
    ├── helper.py / scripts/        # 可选：辅助脚本/资源（原样保留）
    └── references/                 # 可选：子文档（Hermes 风格扩展，deepagents 渐进披露按需读）
```

> **兼容性保证**：此形态与 deepagents 0.7.5 `SkillsMiddleware`（`backend.ls` + `download_files` 扫描子目录找 SKILL.md）**逐字节兼容**——未来 agent run 只需 `SkillsMiddleware(backend=FilesystemBackend(root_dir=data_dir/skills), sources=["/"])` 即启用，**本任务不做任何 agent 侧改动**。

### 2.2 SKILL.md frontmatter 契约（Agent Skills 规范，deepagents 校验规则照搬）

```yaml
---
name: web-research          # 必选：1-64 字符，小写字母数字+单连字符，必须与目录名一致
description: "..."          # 必选：1-1024 字符，含触发关键词
license: MIT                # 可选
compatibility: Python 3.11  # 可选
metadata:                   # 可选：任意 key-value
  version: 1.0.0
allowed-tools:              # 可选（实验性）
  - read_file
---
# Skill 正文
...
```

**校验规则（import 时执行，deepagents `_parse_skill_metadata` 同规则）**：
- `name` 必填：1-64 字符、仅小写字母数字与单连字符（不可 `--`/首尾 `-`）、**必须等于目录名**——不满足则拒绝导入（N2）
- `description` 必填：1-1024 字符（超长截断警告）
- `license`/`compatibility`/`metadata`/`allowed-tools` 可选，格式错误忽略并警告（deepagents 宽容策略）

### 2.3 官方 skills 包（ADR-022 资产，CLI 不管理）

```
skills/inkflow/                     # 仓库根，官方 inkflow 操作 skills（agent 从 GitHub 自取）
├── SKILL.md                        # 主入口：YAML frontmatter + 使用说明
└── references/                     # 20 文件蓝本复制改造（Q1=B，§2.4）
```

> **CLI 与官方包的关系**（Q2 拍板）：`inkflow skills` 命令**只管理 `data_dir/skills/` 用户自定义 skills**；官方包 `skills/inkflow/` 是给外部 agent 用的分发资产，**不在 CLI 命令面内**（用户「如果是 inkflow，cli 中不应该管理这些」拍板）。

### 2.4 官方包内容（Q1=B：Hermes 蓝本复制改造）

- 源：Hermes 技能库 `inkflow` skill v0.1.0（20 references 全量命令面）
- 改造：① 去 Hermes 特有视角（操作手册/验证配方 → 通用 agent 使用指南）；② 命令示例按真实 `--help`/`--json` 核对（ADR-022 同步纪律）；③ version 对齐 InkFlow 版本；④ 增 `mcp-setup.md` 占位（#49 联动）
- **注意**：官方包 frontmatter 的 `name: inkflow` 与用户自定义 skill 校验无关（官方包不经 CLI 导入校验，agent 自取时由 agent 侧解析）

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
inkflow skills install <SOURCE>   # 导入用户自定义 skills 包到 data_dir/skills/（Q2 定稿语义）
inkflow skills list               # 列出已导入 skills（name/description/路径/校验状态）
inkflow skills verify [--name N]  # 校验已导入 skills frontmatter 合规（Agent Skills 规范）
inkflow skills remove <NAME>      # 删除已导入 skill（用户拍板：导入+管理）
```

**注册方式**：`app.add_typer(skills.app, name="skills")`（app.py 既有模式）。

**执行模型**：**零后端代码**——纯本地文件操作（复制目录/校验 frontmatter/列表/删除），**不 ensure_kernel、不拉 HTTP**（f38 豁免先例：config/llm/agent tools list 同族）。错误面沿用 F7：业务错误 → 退出码 1 + 错误信封；用法错误 → 退出码 2。

> **命令面边界**（Q2 拍板）：只管理**用户自定义 skills**（`data_dir/skills/`）；官方 inkflow 包（`skills/inkflow/`）不在命令面内——CLI 不做官方包的下载/管理（agent 从 GitHub 自取）。

### 4.2 `skills install`

```text
inkflow skills install <SOURCE> [--target PATH] [--force] [--json]
```

- `<SOURCE>`：本地目录路径（含 `SKILL.md` 的 skill 包）——**首版仅本地路径**（GitHub URL 下载留待后续，见 §10）
- 导入流程：读取源目录 → 校验 frontmatter（§2.2 规则）→ 复制整个目录到 `data_dir/skills/<name>/`（SKILL.md + 辅助文件 + references/ 原样保留）
- `--target`：覆盖默认目标根（默认 `data_dir/skills/`，dev 为 `cwd\data\skills`，打包版为 `%APPDATA%\InkFlow\skills`——f19-packaging Q7 数据目录同族）
- `--force`：覆盖已存在同名 skill；无 `--force` 且已存在 → 退出码 1 `ALREADY_INSTALLED`（N4）
- 成功：`{"ok": true, "data": {"name": "web-research", "target": "...", "files": 5}}`
- 校验失败（frontmatter 缺 name/description、name 不合规）→ 退出码 1 + 错误信封（N2）

### 4.3 `skills list`

```text
inkflow skills list [--json]
```

- 成功信封：`{"ok": true, "data": {"skills": [{"name": "web-research", "description": "...", "path": "...", "status": "ok|invalid"}]}}`
- `status` = frontmatter 校验结果（invalid 时附 N1/N2 错误信息）；无 `--json`：人类可读列表

### 4.4 `skills verify`

```text
inkflow skills verify [--name NAME] [--json]
```

- 校验全部（默认）或指定已导入 skill：frontmatter 必填字段（N1）/ name 合规且与目录名一致（N2）/ description 长度（N3）
- 成功：`{"ok": true, "data": {"name": "web-research", "checks": {"frontmatter": true, "name": true, "description": true}, "status": "ok"}}`
- 任一失败：退出码 1 + 错误信封（code 见 §7 表）

### 4.5 `skills remove`

```text
inkflow skills remove <NAME> [--json]
```

- 删除 `data_dir/skills/<NAME>/` 整个目录
- 不存在 → 退出码 1 `NOT_FOUND`（N5）
- 成功：`{"ok": true, "data": {"removed": "web-research"}}`

---

## 5. 关键差异节：官方分发 vs 用户自定义导入

### 5.1 双轨职责矩阵（2026-08-12 用户拍板定稿）

| 轨 | 对象 | 载体 | 管理方 | 消费方 | 本期动作 |
|----|------|------|--------|--------|----------|
| **官方轨** | `skills/inkflow/`（官方 inkflow 操作 skills） | GitHub 源码 `skills/inkflow/`（tag 版本） | **CLI 不管**（agent 从 GitHub 自取，ADR-022 主通道语义） | 外部 agent（Hermes/Claude Code 等） | **交付资产**（Q1=B 蓝本复制改造，§2.4）+ rc 漂移验证 |
| **用户自定义轨** | `data_dir/skills/<name>/`（用户找到/自写的 skills） | CLI `inkflow skills install` 从本地路径导入 | **CLI 管理**（install/list/verify/remove） | 未来 InkFlow agent run（**本期不接**，其他 issue；deepagents SkillsMiddleware 兼容就绪） | **实现命令组**（§4） |
| 随安装包 | — | — | — | — | **不做**（Q3 拍板：当前不随安装包，后续可能单独打包） |

### 5.2 与 deepagents SkillsMiddleware 的兼容契约（存储形态依据）

- 导入落盘形态 = deepagents `SkillsMiddleware` 期望形态（source 目录下 `<name>/SKILL.md` + 辅助文件）——**逐字节兼容**
- frontmatter 校验规则照搬 `_parse_skill_metadata`（name 1-64 小写字母数字单连字符且=目录名、description 1-1024、可选字段宽容处理）
- 未来 agent run 接入（其他 issue）：`SkillsMiddleware(backend=FilesystemBackend(root_dir=data_dir/skills), sources=["/"])` 即启用，**本任务零 agent 侧改动**

### 5.3 版本对齐（仅官方包适用）

- 官方包 `skills/inkflow/SKILL.md` frontmatter version = InkFlow 当前版本（ADR-019 SemVer），发布/里程碑收尾五项同步时更新
- 用户自定义 skills 无版本对齐义务（导入后由 verify 校验 frontmatter 合规即可，`metadata.version` 可选承载）

### 5.4 随安装包收集（Q3 拍板：当前不实施）

**❌ 已否决（2026-08-12 用户拍板）**：原候选 A（PyInstaller `datas` 显式收集进 `_internal/skills/`）与 B（electron extraResources 旁置 `resources/skills/`）**均不采用**——skills 当前**不随安装包下载**，主分发 = GitHub（仓库 `skills/inkflow/`）。

后续若单独打包（用户 2026-08-12 拍板提及「后续可能单独打包」），另行评估：
- 形态候选：独立 zip（类似 f33 CLI zip 流程）/ PyInstaller datas 进内核 onedir
- 收集缺口教训同族：0.7.0 tiktoken/chromadb（#253）——打包后必须冒烟断言 skills 文件存在
- 本 spec §8.2 不包含任何打包配置 MODIFY（Q3 拍板零改动）

### 5.5 与 f33 CLI zip / release.yml 的关系

- **release.yml 零改动**（Q3 拍板：不随安装包 → 无收集步骤、无冒烟增量）
- f33 CLI zip = `backend/dist/inkflow/` 整体打 zip（release.yml「Package CLI zip」step）——skills 不进内核 onedir，故 CLI zip 也不含 skills（与「当前不随安装包」一致）
- GitHub 官方轨 = 仓库源码树 `skills/inkflow/`（tag 版本即发布版本），**不需要任何发布流水线改动**——源码即资产

---

## 6. 组织规则

### 6.1 双轨组织规则

**用户自定义轨（`data_dir/skills/`）**：
- 导入时复制整个 skill 目录（SKILL.md + 辅助文件 + references/），**不改内容**——原样落盘，源目录与导入副本解耦（后续源更新需重新 install --force）
- 目录名 = frontmatter name（Agent Skills 规范强制）；同名导入需 `--force`
- verify 只读校验，不改文件

**官方轨（`skills/inkflow/`）**：
- `skills/inkflow/` 是官方资产**唯一维护源**（ADR-022）：GitHub 分发均从此目录；**不允许**在分发位独立维护第二份
- `SKILL.md` 为 agent 入口：description 含触发关键词，正文含「安装后如何用」三步起步（`inkflow --help` 探活 → `project list --json` 发现 → journey C 走查）
- `references/` 按主题拆分（命令/契约/工作流/功能域），**单文件 ≤ 300 行**（对标 Hermes 技能库 references 惯例，防 monster 文档）
- 文档与 CLI 契约同步纪律：`cli-commands.md`/`json-contracts.md` 的内容变更必须对照 `tests/cli/` 契约测试（ADR-022 影响节）
- **蓝本维护关系**：官方包与 Hermes 技能库 `inkflow` skill **互为镜像起点但独立演进**（Q1=B 一次性复制后，官方包成为权威——后续 Hermes 侧更新以官方包为准回灌，不在本任务范围）

### 6.2 CLI 组组织（skills.py）

- 薄层：参数解析/校验 + 本地文件操作，**不 import domain/infra 业务模块**（f38 豁免命令同族）
- `--json` 全局化由根 app callback 提供（`ctx.obj.json_output`），子命令读 `ctx.obj`（F7 约定，kernel.py 样板）
- 目标根路径 = `config.data_dir / "skills"`（dev `cwd\data\skills`；打包版 `%APPDATA%\InkFlow\skills`——f19-packaging Q7 sys.frozen 分支同族）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 | 错误码 | 退出码 |
|---|------|------|--------|--------|
| N1 | frontmatter 缺必填字段（name/description） | verify/install 失败，列出缺失字段 | `SKILLS_INVALID_FRONTMATTER` | 1 |
| N2 | name 不合规（长度/字符/与目录名不一致） | verify/install 失败 | `SKILLS_INVALID_NAME` | 1 |
| N3 | description 超 1024 字符 | 截断警告（deepagents 宽容策略），继续导入 | `SKILLS_DESCRIPTION_TRUNCATED`（警告） | 0 |
| N4 | install 目标已存在同名且无 `--force` | 拒绝覆盖 | `ALREADY_INSTALLED` | 1 |
| N5 | remove 指定 skill 不存在 | 删除失败 | `NOT_FOUND` | 1 |
| N6 | SOURCE 路径不存在 / 无 SKILL.md | install 失败 | `SKILLS_SOURCE_INVALID` | 1 |
| N7 | 目标根不可写（权限/只读） | install/remove 失败 | `SKILLS_TARGET_UNWRITABLE` | 1 |
| N8 | 非法参数（未知子命令/缺参） | 用法错误 | （typer 默认） | 2 |
| N9 | Ctrl+C 中断 | 优雅退出 | — | 130 |

---

## 8. 文件结构

### 8.1 CREATE（新建）

| 文件 | 内容 |
|------|------|
| `skills/inkflow/SKILL.md` | 官方包主入口：frontmatter + 使用说明（§2.4 蓝本复制改造） |
| `skills/inkflow/references/*.md` | 官方包 20 文件蓝本复制改造（cli-commands 全量 23 组 / json-contracts / workflows / kernel / projects / chapters / writing / audit / library-* / models / templates / agent / memory / export / style / extract / system / mcp-setup.md 占位）——按 §2.4 契约 |
| `backend/src/inkflow/cli/commands/skills.py` | skills 命令组（§4：install/list/verify/remove 本地文件操作） |
| `backend/src/inkflow/cli/skills_parser.py` | frontmatter 解析/校验纯函数（deepagents `_parse_skill_metadata` 规则镜像，供命令组与测试复用） |
| `backend/tests/cli/test_cli_skills.py` | CLI 契约测试（RED 先行，§9；tmp_path 真实目录导入） |
| `backend/tests/unit/test_skills_parser.py` | frontmatter 校验纯函数测试（§9，deepagents 规则逐条） |

### 8.2 MODIFY（修改）

| 文件 | 变更 | 节 |
|------|------|-----|
| `backend/src/inkflow/cli/app.py` | 注册 `skills` 子组（`app.add_typer(skills.app, name="skills")`） | §4.1 |
| `AGENTS.md` | 0.8.0 里程碑回写 + F19 家族条目补 skills 子任务（收尾，Phase 8） | — |
| `FEATURES.md` | skills 包功能登记（合入后五项同步） | — |
| `adr/ADR-019.md` | 0.8.0 行补 skills 交付记录（合入后） | — |

### 8.3 不修改（明确声明）

- `backend/src/inkflow/api/**`（REST 面零改动）
- `backend/src/inkflow/core/config.py`（skills 根 = `config.data_dir / "skills"` 只读引用，不改配置结构）
- 既有 23 组 CLI 命令（`commands/*.py` 除新增 skills.py 外零改动）
- `.github/workflows/ci.yml`（本任务 PR CI 走既有 job；skills 资产无 Python 代码面 → 覆盖口径见 §9）
- **`backend/pyinstaller/inkflow.spec` / `.github/workflows/release.yml` / `electron-builder.yml`（Q3 拍板：当前不随安装包，打包配置零改动）**
- **`backend/src/inkflow/infrastructure/agent/**`（F26 deepagents 装配零改动——本期不接 agent 使用）**

---

## 9. 测试策略

### 9.1 层次与载体

| 层 | 载体 | 覆盖 |
|----|------|------|
| unit | `backend/tests/unit/test_skills_parser.py`（新建） | frontmatter 解析/校验纯函数：必填字段（N1）、name 合规（N2：长度/字符/连字符/目录名一致）、description 截断（N3）、可选字段宽容（license/compatibility/metadata/allowed-tools 格式错误忽略）——**deepagents `_parse_skill_metadata` 规则逐条镜像测试** |
| CLI | `backend/tests/cli/test_cli_skills.py`（新建） | install/list/verify/remove 成功路径 + 错误路径（N4-N7），**tmp_path 真实目录导入**（构造含 SKILL.md 的临时 skill 包 → install → 断言落盘结构），`--json` 信封断言（`json.loads(result.stdout)`） |
| 官方包一致性 | 实现期人工核对 | 官方包 20 文件与 Hermes 蓝本 diff 核对（去 Hermes 视角残留）；`json-contracts.md` 示例字段 vs tests/cli/ 断言（ADR-022 同步纪律） |
| rc 阶段手工 | 漂移验证四件套（§13 M3-M6） | 官方轨 GitHub 资产完整 + 用户自定义轨 install/list/verify/remove 真实走查 + 注入生效验证 |

### 9.2 关键场景

1. **用户自定义轨闭环**：构造 skill 包（合法 frontmatter）→ `install` → 落盘 `data_dir/skills/<name>/` → `list` 显示 ok → `verify` 通过 → `remove` 删除
2. **校验失败检测**：缺 name/description → `SKILLS_INVALID_FRONTMATTER`；name 与目录名不一致 → `SKILLS_INVALID_NAME`（N2）
3. **覆盖保护**：同名已存在且无 `--force` → `ALREADY_INSTALLED`（N4）
4. **官方轨完整**：tag 上 `skills/inkflow/` 20 文件 + SKILL.md 齐备（rc 验证）

### 9.3 覆盖率

- 新增 CLI 薄层 + parser 纯函数走 pytest 覆盖率口径（CI coverage-backend 98.5/95.0 不变，ADR-027）
- skills Markdown 资产非代码面，不进覆盖率口径；其正确性由官方包一致性核对 + rc 冒烟验证
- **无打包冒烟**（Q3 拍板：当前不随安装包 → release.yml 无 skills 相关步骤，漂移验证 #1 调整为官方轨 GitHub 资产完整检查，见 §13 M3）

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| MCP Server 实现 | **#49**（0.9.0）；ADR-023——本任务仅预留官方包内 `mcp-setup.md` 占位，**不实现** |
| mcp-setup.md 内容写作 | #49 发布后补（ADR-022 演进预留）；占位文件注明「MCP 发布后填写」 |
| **agent 实际使用 skills** | **用户拍板 2026-08-12：本期只做导入+管理，agent run 注入/消费是其他 issue**；deepagents SkillsMiddleware 已就绪（§5.2 兼容契约），未来接入零改造 |
| **官方 inkflow skills 的 CLI 管理** | **Q2 拍板 2026-08-12**：官方 = inkflow 操作 skills，agent 从 GitHub 自取（ADR-022 主通道语义），**CLI 不管理** |
| **随安装包分发** | **Q3 拍板（2026-08-12）**：当前不随安装包下载；后续可能单独打包，另行评估（§5.4） |
| skills 内容从零写作 | Q1=B 拍板：以 Hermes 测试版 inkflow skill 蓝本复制改造（§2.4），非新写 |
| GitHub URL 导入（`skills install <https://...>`） | 首版仅本地路径导入；URL 下载留待后续（用户找到的 skills 若在 GitHub，先 clone 到本地再 install） |
| 用户自定义 skills 上传/发布（反向推送） | 未立项；本任务只做导入+管理（本地落盘），不涉及分享/市场 |
| agent 侧自动安装/注册（Hermes 等自动加载 skills） | 各 agent 自身机制；InkFlow 交付官方资产 + 导入命令 |
| REST 端点 / 业务实体 / LLM 管线 | 本任务零业务代码 |
| macOS/Linux 打包 | 沿用 f19-packaging §10（1.0.0 跨平台事项） |

---

## 11. 依赖关系

### 11.1 依赖（本任务需要的既有交付）

| 依赖 | 交付 | 用途 |
|------|------|------|
| ADR-022 | ✅ 已接受 | 形态决策（官方包单一真相 + 三通道分发基线 + CLI 契约；本任务按用户拍板演进为双轨） |
| F7 CLI 全局约定 | ✅ 已实现 | 信封/退出码/错误码契约（§4 全部命令） |
| f19-packaging | ✅ PR #144 | PyInstaller 链 + release.yml（§5.4 背景：本任务不消费） |
| f33-cli-dist | ✅ PR #181 | CLI zip 产物（§5.5 背景：本任务不消费） |
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
| D1 | **双轨架构（Q2 拍板定稿）** | 官方轨（`skills/inkflow/`，GitHub 分发，CLI 不管理）+ 用户自定义轨（`data_dir/skills/`，CLI 导入管理） | 官方包是 agent 生态资产（agent 自取，ADR-022 主通道）；用户自定义 skills 是 InkFlow 本地功能——职责分离 | 单轨 CLI 管官方包（用户「cli 中不应该管理这些」拍板否决）；无官方包（ADR-022 决策不可废） |
| D2 | **存储形态 = 文件系统目录（用户拍板定稿）** | `data_dir/skills/<name>/SKILL.md`，非数据库实体 | **deepagents 0.7.5 SkillsMiddleware 现成实现即从文件读取**（FilesystemBackend + frontmatter 扫描）——零自建、零改造对接；数据库 BLOB 反而不兼容 agent 生态 | SQLite 实体表（用户最初设想「本地数据库」，实证 deepagents 从文件读后放弃——§1.2 证据） |
| D3 | **skills 命令组零后端代码** | 纯本地文件操作（复制/校验/列表/删除），不 ensure_kernel/不 HTTP | f38 豁免先例同族；零常驻依赖（ADR-022「零后端代码可先行交付」） | 经内核 HTTP（需内核拉起，违背零后端；且无对应端点） |
| D4 | **官方包内容 = 全量命令面（Q1=B ✅ 已确认：用户拍板，2026-08-12）** | **复制 Hermes 测试版 inkflow skill（20 references）再修改符合实际** | 用户提供蓝本消解「全量写作成本高」顾虑；蓝本已覆盖 23 CLI 组，复制改造远快于从零写 | A journey C 子集（范围不足，蓝本已有全量）；C 子集+骨架（无意义，蓝本全量现成） |
| D5 | **install 语义 = 用户自定义 skills 导入（Q2 ✅ 已确认：用户拍板，2026-08-12）** | `skills install <本地路径>` → 校验 frontmatter（Agent Skills 规范）→ 落盘 `data_dir/skills/<name>/`；list/verify/remove 管理 | 用户拍板「这是导入用户自定义 skills 的命令」；下载官方 skills 是 agent 生态的事（Hermes 自取），CLI 不做 | v1.1 预修订「GitHub 下载官方」方向（用户否定：下载不是 CLI 职责） |
| D6 | **随安装包收集 = 当前不实施（Q3 ✅ 已确认：用户拍板，2026-08-12）** | skills 放 GitHub，后续可能单独打包（另行评估） | 用户拍板「当前不随安装包下载」；源码即资产零发布改动；0.7.0 收集缺口风险本期不存在 | A PyInstaller datas（用户否决）；B electron extraResources（用户否决）；C A+B 双放（用户否决） |
| D7 | **本期只做导入+管理（用户拍板，2026-08-12）** | agent 实际使用 skills 是其他 issue；deepagents SkillsMiddleware 兼容就绪 | 用户拍板范围收敛；避免本期范围膨胀（agent 注入涉及 F26 harness 改动） | 本期就接 agent run（范围大，用户否决） |

---

## 13. 验收标准

| # | 验收项（M 行） | 验证方式 | 载体 |
|---|---------------|----------|------|
| M1 | 官方包 `skills/inkflow/` 完整落盘：SKILL.md（frontmatter）+ references/ 20 文件（含 mcp-setup.md 占位）蓝本复制改造完成 | 源码树检查 + 与 Hermes 蓝本 diff 核对 | 单元 + 手工 |
| M2 | 用户自定义轨命令真实可用：`skills install/list/verify/remove` 全命令 `--json` 信封正确、退出码 0/1/2 符合 F7；install（tmp_path 真实导入）→list→verify→remove 闭环通过 | `backend/tests/cli/test_cli_skills.py` 全绿 + 手工 CLI 走查 | CLI 测试 + 手工 |
| M3 | 官方轨 GitHub 资产完整（漂移四件套 #1 调整版）：tag 上 `skills/inkflow/` 文件完整（20 references + SKILL.md），frontmatter 合规 | rc 阶段从 tag 拉取核对（原「打包产物数据完整」因 Q3 拍板不随安装包，调整为 GitHub 资产检查；后续单独打包时补验打包产物） | 手工 + 脚本 |
| M4 | CLI/API skill 命令真实可用（漂移四件套 #2）：`inkflow skills list --json` 返回已导入 skills，无 ModuleNotFoundError | 本地 + 打包 exe 实测 | 手工 + 脚本 |
| M5 | skill 注入生效（漂移四件套 #3）：**外部 agent（Hermes/Codex 等）加载官方包后执行旅程 C 任务，决策轨迹可见实际调用 `inkflow <cmd> --json`**（非静默忽略），命令参数符合 cli-commands.md——注：本期为官方包对 agent 的可用性验证，用户自定义轨的 agent 注入属其他 issue | rc 阶段真实 agent 走查，决策轨迹截图/日志留档 | 手工 |
| M6 | 双轨分发各验一次（漂移四件套 #4 调整版）：① 官方轨 GitHub tag 拉取 `skills/inkflow/` 完整；② 用户自定义轨 `install <本地路径>` → verify 通过 → remove 干净（原三通道验证因随安装包推迟改为双轨；单独打包通道启用时补验） | rc 阶段逐轨验证 | 手工 + 脚本 |
| M7 | 官方包版本对齐：frontmatter version = 当前版本（ADR-019 SemVer） | 源码检查 | 静态 |
| M8 | 既有测试全绿：backend unit/integration/coverage（98.5/95.0）+ frontend 三层 | ci.yml PR 全绿 | CI |
| M9 | mcp-setup.md 占位存在且标注「MCP 发布后填写」（#49 联动预留，不实现内容） | 源码检查 | 静态 |

> 完成标准映射：M1 = 官方包资产（Q1=B）；M2 = 用户自定义轨命令面（Q2）；M3-M6 = 漂移验证四件套（2026-08-12 用户拍板 load-bearing，因 Q2/Q3 拍板调整：官方轨 GitHub 资产 + 用户自定义轨命令走查 + 注入生效 + 双轨验证）；M7 = 官方包版本对齐；M8 = 质量门禁；M9 = #49 联动预留。

---

## 待澄清问题（≤3，阻塞级）

1. **Q1 skills 包首版内容范围**：
   - A：journey C 子集（cli-commands.md 只写 project/chapter/write/audit/export 等旅程 C 命令 + json-contracts + workflows 三文件起步）
   - B：全量 23 CLI 组命令参考（写作成本高，内容将随产品演化漂移）
   - C：journey C 子集 + 预留全量骨架（references 目录含各命令占位节，后续迭代填充）
   - **✅ 已确认（用户拍板：选项 B，2026-08-12）**——原建议 A 因「Hermes 已有测试版 inkflow skill 可直接复制修改」被推翻：以 Hermes 技能库 `inkflow` skill v0.1.0（20 references 全量命令面）为蓝本**整体复制再修改符合实际**，成本顾虑消解。正文 §2.4/§8.1 已按 B 修订（蓝本复制改造），D4 同步 ✅。
   - 影响：§8.1 文件内容规模、估算（复制改造 ≈ 2-3 人天，含逐文件核对）

2. **Q2 `skills install` 语义与目标路径**：
   - A：复制到 `%APPDATA%\InkFlow\skills`（打包版）/ `data_dir\skills`（dev，随 config.data_dir 派生）——统一管理入口
   - B：复制到用户指定目录（`--target` 必填），默认不写系统目录
   - C：仅打印安装指引（SKILL.md 内容 + 建议目录），不做文件复制
   - **✅ 已确认（用户拍板，2026-08-12）：`skills install` = 导入用户自定义 skills 到 InkFlow 本地**——用户澄清「下载 skills 应是 Hermes 等 agent 的事，CLI 不该做下载官方；install 是用户将找到的/自己写的 skills 上传到 InkFlow 本地的命令」。**存储形态定稿 = 文件系统目录 `data_dir/skills/<name>/`（非数据库）**——实证 deepagents 0.7.5 SkillsMiddleware 即从文件读取（FilesystemBackend + SKILL.md frontmatter 扫描），落盘形态与之逐字节兼容，未来 agent run 接入零改造。**范围收敛：本期只做导入+管理（install/list/verify/remove），agent 实际使用是其他 issue**。正文 §1/§2/§4/§5/§6/§8/§9/§10/§12/§13 已全量修订，D1/D2/D5/D7 同步 ✅。
   - 影响：§4 命令面（install/list/verify/remove）、§2.1 存储形态、§8.1 skills_parser.py、估算（纯文件操作 + parser，≈ 2-3 人天）

3. **Q3 随安装包通道的收集方式**：
   - A：PyInstaller `datas` 显式收集进 `_internal/skills/`（推荐：GUI 包 + CLI zip 双覆盖，release.yml 零改动）
   - B：electron extraResources 旁置 `resources/skills/`（GUI 包专用，CLI zip 不含——纯 CLI 用户第三通道失效）
   - C：A + B 双放（覆盖最全，但双处收集 + 双处冒烟）
   - **✅ 已确认（用户拍板：新决策，2026-08-12）——A/B/C 全部否决**：skills 放 GitHub 主通道 + **后续可能单独打包**，**当前不随安装包下载**。正文 §1.1/§1.2/§5.1/§5.4/§5.5/§8.2/§8.3/§9/§10/§13 已联动修订（双轨 + 打包配置零改动 + 漂移四件套 #1/#4 调整），D6 同步 ✅。
   - 影响：§5.4（不实施）、§8.2/§8.3（inkflow.spec/release.yml/electron-builder 零改动）、§13 M3/M6（漂移验证调整）
