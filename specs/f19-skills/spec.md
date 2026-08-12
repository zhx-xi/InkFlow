# F19-skills: skills 包（ADR-022）— 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-12 | **依据**: ADR-022（skills 包形态）、ADR-019 v6（版本里程碑：0.8.0 = 后续语义统一与技术债，2026-08-09 建）、Issue #65 决策 D4、Constitution P1-P6
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
| 核心机制 | 源码 `skills/inkflow/` 单一真相 + 三通道分发（GitHub 主 / 随安装包辅 / `skills install` 命令）+ SKILL.md（YAML frontmatter）+ references/ 子目录 |
| 跨模块 MODIFY | `backend/src/inkflow/cli/app.py`（注册 skills 子组）+ `backend/pyinstaller/inkflow.spec`（datas 收集 skills 资产）+ 可选 release.yml（Q3 拍板后定） |
| 错误面 | F7 信封契约沿用：`{"ok": true, "data": ...}` / `{"ok": false, "error": {"code", "message"}}`，退出码 0/1/2/130 |

**变体编号声明**：本模块为 F19 家族 0.8.0 子任务（F19 GUI 家族拆分条目：0.3.0 GUI 壳 / 0.4.0 打包分发 / 本任务 skills 包），按 AGENTS.md 模块类型谱系「F19 GUI」条目归类，**不占用业务模块变体编号**（f19-packaging「打包分发专项」同口径）。

### 1.2 关键事实（现状盘点，2026-08-12 实测）

- ❌ 主仓**无 `skills/` 目录**（`Test-Path D:\develop\projects\InkFlow\skills` = False）——源码单一真相为零起点新建
- ✅ CLI 组样板成熟：`backend/src/inkflow/cli/app.py`（23 组子命令注册，`app.add_typer(...)` 模式）+ `commands/*.py`（薄层）+ `context.py`/`output.py`（`print_result`/`print_error` 信封，F7 契约）
- ✅ **本地命令豁免先例（f38-cli-http §1.3）**：`config`/`llm`/`agent tools list` 因操作本地文件/静态资源被豁免 HTTP 改造——**skills 命令组同族**（本地文件操作，无对应 API 端点，不 ensure_kernel）
- ✅ 打包链：`backend/pyinstaller/inkflow.spec`（128 行）`collect_all("inkflow")` 只收集 **Python 包内**数据文件（LLM 模板 yaml 等）——**skills 包位于仓库根 `skills/`（非 Python 包），PyInstaller 静态分析不可见，必须显式 `datas` 条目**（Q3）
- ✅ release.yml（283 行，tag `v*` 触发）：package-backend job 已有「Packaged kernel smoke」step（#253 rc6 教训固化：打包产物冒烟，断言无 ModuleNotFoundError）——**skills 数据完整性冒烟同族接入**（漂移验证四件套 #1）
- ✅ 版本注入链：tag → pyproject → `copy_metadata('inkflow')` → INKFLOW_READY.version（f19-packaging §2.4）；`inkflow --version` = `importlib.metadata.version("inkflow")`
- ✅ F7 spec §5/§7：信封结构、退出码 0（成功）/1（业务错误）/2（用法错误）/130（Ctrl+C）
- ✅ f33-cli-dist：CLI zip 产物 `InkFlow-cli-<ver>-x64.zip`（PyInstaller onedir 整体打 zip，零新增构建）——**随安装包通道的 CLI 形态载体**
- ✅ Hermes 技能库先例（本环境）：SKILL.md = YAML frontmatter（name/description/version/触发条件）+ 正文使用说明 + `references/` 子目录分主题文档——skills 包结构对标此形态
- ✅ #49 MCP 挂 0.9.0（milestone #12），OPEN——mcp-setup.md 联动为远期预留（§10）

### 1.3 边界声明

- **不含** MCP Server 实现（#49，0.9.0）；本 spec 仅预留 skills 包内 `mcp-setup.md` 槽位（§10.1），MCP 发布后补写
- **不含** 任何业务 REST 端点 / ORM / 领域逻辑改动
- **不含** CLI 恒 HTTP 化改造（f38 已交付，本任务新命令组天然豁免——本地文件操作无内核依赖）
- **不含** skills 内容的大规模写作（首版内容范围 = Q1 拍板；journey C 子集起步，全量命令参考后续迭代）
- **不含** agent 侧安装引导（Hermes 等外部 agent 的 skills 安装机制由各 agent 自身实现；InkFlow 只交付资产 + 安装指引文档）

---

## 2. 数据模型与资产契约

### 2.1 skills 包目录结构（源码单一真相，ADR-022 决策）

```
skills/inkflow/
├── SKILL.md                        # 主入口：YAML frontmatter + 使用说明（必选）
└── references/                     # 分主题参考文档（必选子目录）
    ├── cli-commands.md             # CLI 命令参考（journey C 子集，Q1 拍板范围）
    ├── json-contracts.md           # --json 信封契约示例（各命令 data 结构）
    ├── workflows.md                # 使用指南（旅程 C：发现→读取→写作→审计→写回）
    └── mcp-setup.md                # 🚧 MCP 设置指南（#49 发布后补写，本任务仅占位说明）
```

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

### 2.3 references/ 文档契约

| 文件 | 内容 | 维护纪律 |
|------|------|----------|
| `cli-commands.md` | journey C 涉及命令的签名 + 参数 + 示例（`project list --json` 等）；命令语义描述，**不重复实现逻辑**（ADR-022「skills 文档只描述命令语义与 JSON 结构」） | 命令面变更评审时对照 tests/cli/ 契约测试（ADR-022 影响节） |
| `json-contracts.md` | 各命令 `--json` 信封的 data 结构示例（真实输出抓取，非手写臆造） | 与 tests/cli/ 断言同步更新 |
| `workflows.md` | 旅程 C 分步指南（含失败处理：内核未启动 → `ensure_kernel` 语义说明） | 随功能演进更新 |
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
inkflow skills list            # 列出可用 skills（内置来源 + 已安装位置）
inkflow skills install         # 安装 skills 包到目标目录（Q2 拍板语义）
inkflow skills update          # 更新已安装 skills 包（版本校验）
inkflow skills verify          # 校验安装完整性（frontmatter/版本/文件清单）
```

**注册方式**：`app.add_typer(skills.app, name="skills")`（app.py 既有模式）。

**执行模型**：**零后端代码**——纯本地文件操作（复制/校验/列表），**不 ensure_kernel、不拉 HTTP**（f38 豁免先例：config/llm/agent tools list 同族）。错误面沿用 F7：业务错误 → 退出码 1 + 错误信封；用法错误 → 退出码 2。

### 4.2 `skills list`

```text
inkflow skills list [--json]
```

- 成功信封：`{"ok": true, "data": {"bundled": {"version": "0.8.0", "path": "..."}, "installed": {"version": "0.8.0", "path": "...", "status": "up-to-date|outdated|missing"}}}`
- `bundled` = 随包/源码内置资产位置（打包版 `_internal/skills/inkflow/`，dev `skills/inkflow/`）；`installed` = Q2 拍板的目标目录
- 无 `--json`：人类可读列表

### 4.3 `skills install`

```text
inkflow skills install [--target PATH] [--source bundled|path] [--force] [--json]
```

- 从内置资产（默认）或显式路径复制 skills 包到目标目录（Q2 拍板；默认目标见 Q2 选项）
- `--force`：覆盖已安装（版本不一致时更新）；无 `--force` 且已存在同版本 → 退出码 1 `ALREADY_INSTALLED`（N4）
- 成功：`{"ok": true, "data": {"target": "...", "version": "0.8.0"}}`
- **GitHub 拉取形态不在首版**（Q2 选项权衡：网络依赖 + URL 维护成本 > 首版收益；GitHub 通道由外部 agent 直接 fetch 仓库 `skills/inkflow/` 覆盖，ADR-022 主通道语义）

### 4.4 `skills update`

```text
inkflow skills update [--target PATH] [--json]
```

- 已安装 version < 内置 version → 覆盖更新；已最新 → 退出码 0 + `{"updated": false, "reason": "up-to-date"}`
- 未安装 → 退出码 1 `NOT_INSTALLED`（N5）

### 4.5 `skills verify`

```text
inkflow skills verify [--target PATH] [--json]
```

- 校验指定（或默认）安装：frontmatter 必填字段齐全（N1）/ `version` SemVer 合法（N2）/ 与内置版本一致（N3）/ references/ 必需文件存在（N6）
- 成功：`{"ok": true, "data": {"target": "...", "checks": {"frontmatter": true, "version": "0.8.0", "files": 4}, "status": "ok"}}`
- 任一失败：退出码 1 + 错误信封（code 见 §7 表）

---

## 5. 关键差异节：分发型三通道 + 打包收集

### 5.1 三通道分发矩阵（ADR-022 决策落地）

| 通道 | 载体 | 消费方 | 版本对齐 | 验证（漂移四件套） |
|------|------|--------|----------|-------------------|
| **1. GitHub 源码 tap/URL（主）** | 仓库 `skills/inkflow/`（tag 对应版本，永远最新） | 外部 agent 直接 fetch | 源码 frontmatter version = tag | rc 验证：从 tag 拉取 → `verify` 通过 |
| **2. 随安装包内置（辅）** | PyInstaller onedir `_internal/skills/inkflow/`（Q3 拍板收集方式） | 离线/无网络环境；CLI zip 同源 | 打包构建期随源码进包 | rc 验证：打包产物内 skills 数据完整（无缺文件/无收集缺口） |
| **3. `inkflow skills install`（辅）** | 内置资产 → 目标目录复制（Q2） | 已装 InkFlow 的用户手动管理 | verify 对比内置版本 | rc 验证：install → verify → list 全链路 |

### 5.2 版本对齐机制

- **源码单一真相**：`skills/inkflow/SKILL.md` frontmatter `version` 字段 = InkFlow 当前版本（ADR-019 SemVer）
- **同步纪律**：发布/里程碑收尾时（五项同步流程，inkflow-governance）同步更新 frontmatter version；`skills verify` 在安装侧校验一致性（N3）
- **构建期注入**：不做（skills 包为纯 Markdown 资产，不经 Python 构建；手工同步 + verify 校验即闭环——「待实现确认」：若实现期发现手工同步易漂移，可加 CI 检查步骤，见 §9.1）

### 5.3 打包收集（Q3 拍板，两种候选）

**候选 A：PyInstaller `datas` 显式收集**（inkflow.spec 加条目）

```python
# backend/pyinstaller/inkflow.spec（增量示意）
datas += [
    (str(ROOT.parent / "skills" / "inkflow"), "skills/inkflow"),
]
```

- 产物：`_internal/skills/inkflow/` 随内核 exe 分发；CLI zip（f33 整体打 zip）**自动包含**——GUI 包与 CLI zip 双覆盖
- 运行时定位：`sys._MEIPASS` / `Path(sys.executable).parent / "_internal"` 分支（config.py `sys.frozen` 检测同族，f19-packaging Q7 先例）
- 风险：打包后冒烟必须断言 skills 文件存在（#253 tiktoken/chromadb 收集缺口教训同族）

**候选 B：electron extraResources 旁置**（`resources/skills/`）

- 产物：GUI 安装包内 `resources/skills/`（electron-builder.yml 增量）
- 风险：**CLI zip 不含**（CLI zip = 内核 onedir 直打，不经 electron 组装）——第三通道对纯 CLI 用户失效，需双处收集

**推荐：A（含 B 的替代效果）**——A 覆盖 GUI 包 + CLI zip 两产物，单点收集零双份漂移；与 0.7.0 tiktoken 教训修复方向一致（收集逻辑集中在 inkflow.spec）。

### 5.4 与 f33 CLI zip 的关系

- CLI zip = `backend/dist/inkflow/` 整体打 zip（release.yml「Package CLI zip」step，零新增构建）——若 Q3=A，skills 资产已随 onedir 进 zip，**release.yml 零改动**
- 若 Q3 拍板含 extraResources 旁置，release.yml 需增量（electron-builder.yml extraResources 加 skills 源）——Q3 决定 release.yml 改动面

---

## 6. 组织规则

### 6.1 skills 包内容组织

- `skills/inkflow/` 是**唯一维护源**（ADR-022）：任何分发形态（GitHub/安装包/install 命令）均从此复制，**不允许**在各分发位独立维护第二份
- `SKILL.md` 为 agent 入口：description 含触发关键词（§2.2），正文含「安装后如何用」三步起步（`inkflow --help` 探活 → `project list --json` 发现 → journey C 走查）
- `references/` 按主题拆分（命令/契约/工作流），**单文件 ≤ 300 行**（对标 Hermes 技能库 references 惯例，防 monster 文档）
- 文档与 CLI 契约同步纪律：`cli-commands.md`/`json-contracts.md` 的内容变更必须对照 `tests/cli/` 契约测试（ADR-022 影响节）；实现评审时 grep 文档示例与测试断言一致性

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
| N3 | 已安装版本 ≠ 内置版本 | verify 失败（提示 `skills update`） | `SKILLS_VERSION_MISMATCH` | 1 |
| N4 | install 目标已存在同版本且无 `--force` | 拒绝覆盖 | `ALREADY_INSTALLED` | 1 |
| N5 | update 时未安装 | 提示先 install | `NOT_INSTALLED` | 1 |
| N6 | references/ 必需文件缺失（cli-commands.md/json-contracts.md/workflows.md） | verify 失败，列出缺失文件 | `SKILLS_MISSING_FILES` | 1 |
| N7 | 打包版 `_internal/skills/` 缺失（收集缺口） | list/install 报内置资产缺失 | `SKILLS_BUNDLED_MISSING` | 1 |
| N8 | 目标目录不可写（权限/只读） | 复制失败 | `SKILLS_TARGET_UNWRITABLE` | 1 |
| N9 | 非法参数（未知子命令/缺参） | 用法错误 | （typer 默认） | 2 |
| N10 | Ctrl+C 中断 | 优雅退出 | — | 130 |

---

## 8. 文件结构

### 8.1 CREATE（新建）

| 文件 | 内容 |
|------|------|
| `skills/inkflow/SKILL.md` | 主入口：frontmatter（§2.2）+ 使用说明（§6.1） |
| `skills/inkflow/references/cli-commands.md` | journey C 命令参考（Q1 拍板范围） |
| `skills/inkflow/references/json-contracts.md` | `--json` 信封 data 结构示例（真实输出抓取） |
| `skills/inkflow/references/workflows.md` | 旅程 C 使用指南 |
| `skills/inkflow/references/mcp-setup.md` | 🚧 占位（#49 发布后补写） |
| `backend/src/inkflow/cli/commands/skills.py` | skills 命令组（§4） |
| `backend/tests/cli/test_cli_skills.py` | CLI 契约测试（RED 先行，§9） |
| `backend/tests/unit/test_skills_verify.py` | frontmatter/版本校验纯函数测试（§9） |

### 8.2 MODIFY（修改）

| 文件 | 变更 | 节 |
|------|------|-----|
| `backend/src/inkflow/cli/app.py` | 注册 `skills` 子组（`app.add_typer(skills.app, name="skills")`） | §4.1 |
| `backend/pyinstaller/inkflow.spec` | `datas` 增加 skills 收集条目（Q3=A 时） | §5.3 |
| `AGENTS.md` | 0.8.0 里程碑回写 + F19 家族条目补 skills 子任务（收尾，Phase 8） | — |
| `FEATURES.md` | skills 包功能登记（合入后五项同步） | — |
| `adr/ADR-019.md` | 0.8.0 行补 skills 交付记录（合入后） | — |

### 8.3 不修改（明确声明）

- `backend/src/inkflow/api/**`（REST 面零改动）
- `backend/src/inkflow/core/config.py`（skills 路径若走 config.data_dir 派生则只读引用，不改配置结构——Q2 拍板后确认）
- 既有 23 组 CLI 命令（`commands/*.py` 除新增 skills.py 外零改动）
- `.github/workflows/ci.yml`（本任务 PR CI 走既有 job；skills 资产无 Python 代码面 → 覆盖口径见 §9）
- `release.yml`（Q3=A 时零改动；Q3=B 才增量 electron-builder）

---

## 9. 测试策略

### 9.1 层次与载体

| 层 | 载体 | 覆盖 |
|----|------|------|
| unit | `backend/tests/unit/test_skills_verify.py`（新建） | frontmatter 校验（N1/N2）、版本比较（N3）、路径解析（frozen/dev 双分支，monkeypatch `sys.frozen`——f19-packaging `test_config_frozen.py` 同款模式） |
| CLI | `backend/tests/cli/test_cli_skills.py`（新建） | list/install/update/verify 成功路径 + 错误路径（N4-N8），Mock 文件操作（tmp_path 真实目录复制 + monkeypatch 内置资产路径），`--json` 信封断言（`json.loads(result.stdout)`） |
| 文档一致性 | 实现期人工 grep | `json-contracts.md` 示例字段 vs tests/cli/ 断言（ADR-022 同步纪律） |
| 打包冒烟 | release.yml「Packaged kernel smoke」增量 step（Q3=A） | 打包产物 `_internal/skills/inkflow/SKILL.md` 存在 + frontmatter version = tag（#253 教训同族：源码环境测不出收集缺口，只在打包产物验证） |
| rc 阶段手工 | 漂移验证四件套（§13 M4-M7） | 三通道各验一次 + 注入生效验证 |

### 9.2 关键场景

1. **三通道闭环**：GitHub tag 拉取 → verify 通过；安装包/CLI zip 内置 → list 显示 bundled；`skills install` → `skills verify` → `skills update` 全链路
2. **版本漂移检测**：手工改已安装 frontmatter version → verify 报 `SKILLS_VERSION_MISMATCH`
3. **收集缺口检测**：打包产物缺 `_internal/skills/` → list 报 `SKILLS_BUNDLED_MISSING`（N7 断言覆盖）
4. **frozen/dev 双路径**：`sys.frozen=True` → `_internal/skills/inkflow`；False → 仓库 `skills/inkflow`（§2.1 路径）

### 9.3 覆盖率

- 新增 CLI 薄层 + 校验函数走 pytest 覆盖率口径（CI coverage-backend 98.5/95.0 不变，ADR-027）
- skills Markdown 资产非代码面，不进覆盖率口径；其正确性由文档一致性 grep + rc 冒烟验证

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| MCP Server 实现 | **#49**（0.9.0）；ADR-023——本任务仅预留 `references/mcp-setup.md` 占位，**不实现** |
| mcp-setup.md 内容写作 | #49 发布后补（ADR-022 演进预留）；占位文件注明「MCP 发布后填写」 |
| skills 全量命令参考（23 组全写） | Q1 拍板：journey C 子集起步（1.0.0 前随使用迭代补全）；全量写作成本高且内容将随产品演化 |
| GitHub 在线拉取安装（`skills install --source github`） | Q2 权衡：首版不做（见 §4.3）；GitHub 主通道由 agent 直接 fetch 仓库覆盖 |
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
| D1 | **源码单一真相 `skills/inkflow/`** | 仓库根目录唯一维护源，三通道均从此复制 | ADR-022 决策承接；无双份漂移 | 各分发位独立维护（双份漂移，ADR-022 备选已否决） |
| D2 | **三通道分发** | GitHub（主）+ 随安装包（辅）+ install 命令（辅） | ADR-022 决策承接；在线/离线全覆盖 | 单通道（覆盖不足） |
| D3 | **skills 命令组零后端代码** | 纯本地文件操作，不 ensure_kernel/不 HTTP | f38 豁免先例同族；零常驻依赖（ADR-022「零后端代码可先行交付」）；离线可用 | 经内核 HTTP（需内核拉起，违背零后端；且无对应端点） |
| D4 | **首版内容 = journey C 子集** | cli-commands/json-contracts/workflows 三文件，覆盖「发现→读取→写作→审计→写回」 | 需求驱动（ADR-022 旅程 C 是唯一明确场景）；全量 23 组写作成本高且易随产品演化漂移（Q1） | 全量命令参考（成本高/漂移风险） |
| D5 | **安装语义 = 内置资产复制** | install/update/verify 操作本地资产与目标目录，不做 GitHub 拉取 | 首版无网络依赖、无 URL 维护成本；GitHub 主通道由 agent 直接 fetch 仓库（ADR-022 主通道语义） | GitHub 在线拉取（网络依赖/URL 维护/版本解析复杂度） |
| D6 | **打包收集 = PyInstaller datas**（Q3 推荐） | inkflow.spec 显式 `datas` 条目，随 onedir 进 `_internal/skills/` | 单点收集覆盖 GUI 包 + CLI zip 双产物；与 #253 tiktoken 修复方向一致 | electron extraResources 旁置（CLI zip 不含，双处收集风险） |

> Q1/Q2/Q3 拍板后，D4/D5/D6 更新为 ✅ 已确认（用户拍板：选项 X）并同步 §2/§4/§5/§8 正文。

---

## 13. 验收标准

| # | 验收项（M 行） | 验证方式 | 载体 |
|---|---------------|----------|------|
| M1 | `skills/inkflow/` 资产完整落盘：SKILL.md（frontmatter 四必填字段）+ references/ 四文件（含 mcp-setup.md 占位） | 源码树检查 + unit 校验测试 | 单元 |
| M2 | `inkflow skills list/install/update/verify` 真实可用：全命令 `--json` 信封正确、退出码 0/1/2 符合 F7；install→verify→update 闭环通过 | `backend/tests/cli/test_cli_skills.py` 全绿 + 手工 CLI 走查 | CLI 测试 + 手工 |
| M3 | 打包产物 skills 数据完整（漂移四件套 #1）：PyInstaller 产物 `_internal/skills/inkflow/SKILL.md` 存在 + frontmatter version = tag；release.yml 冒烟 step 断言 | 打包冒烟（本地 + CI release job） | 冒烟脚本 |
| M4 | CLI/API skill 命令真实可用（漂移四件套 #2）：打包 exe 内 `inkflow skills list --json` 返回 bundled 资产，无 ModuleNotFoundError | 打包产物实测 | 手工 + 脚本 |
| M5 | skill 注入生效（漂移四件套 #3）：外部 agent（Hermes/Codex 等）加载 skills 包后执行旅程 C 任务，**决策轨迹可见实际调用 `inkflow <cmd> --json`**（非静默忽略），命令参数符合 cli-commands.md | rc 阶段真实 agent 走查，决策轨迹截图/日志留档 | 手工 |
| M6 | 三通道分发各验一次（漂移四件套 #4）：① GitHub tag 拉取 `skills/inkflow/` → verify 通过；② 安装包/CLI zip 内置 → list 显示 bundled；③ `skills install` → verify 通过 | rc 阶段逐通道验证 | 手工 + 脚本 |
| M7 | 版本对齐：源码 frontmatter version = 当前版本 = tag；verify 对版本漂移报 `SKILLS_VERSION_MISMATCH` | N3 测试 + rc 检查 | 单元 + 手工 |
| M8 | 既有测试全绿：backend unit/integration/coverage（98.5/95.0）+ frontend 三层 | ci.yml PR 全绿 | CI |
| M9 | mcp-setup.md 占位存在且标注「MCP 发布后填写」（#49 联动预留，不实现内容） | 源码检查 | 静态 |

> 完成标准映射：M1-M2 = 资产 + 命令面；M3-M6 = 漂移验证四件套（2026-08-12 用户拍板 load-bearing，对应 #70 issue 发布验证要求清单）；M7 = 版本对齐（ADR-022）；M8 = 质量门禁；M9 = #49 联动预留。

---

## 待澄清问题（≤3，阻塞级）

1. **Q1 skills 包首版内容范围**：
   - A：journey C 子集（cli-commands.md 只写 project/chapter/write/audit/export 等旅程 C 命令 + json-contracts + workflows 三文件起步）
   - B：全量 23 CLI 组命令参考（写作成本高，内容将随产品演化漂移）
   - C：journey C 子集 + 预留全量骨架（references 目录含各命令占位节，后续迭代填充）
   - **建议：A**（需求驱动 + 最小可交付；ADR-022 旅程 C 是唯一明确场景；1.0.0 前随使用迭代补全）
   - 影响：§8.1 文件内容规模、估算（A/C 约 2-3 人天内容量，B 约 4-5 人天）

2. **Q2 `skills install` 语义与目标路径**：
   - A：复制到 `%APPDATA%\InkFlow\skills`（打包版）/ `data_dir\skills`（dev，随 config.data_dir 派生）——统一管理入口
   - B：复制到用户指定目录（`--target` 必填），默认不写系统目录
   - C：仅打印安装指引（SKILL.md 内容 + 建议目录），不做文件复制
   - **建议：A + `--target` 可选覆盖**（默认目录随 config.data_dir 派生，兼容打包版 %APPDATA% 路径——f19-packaging Q7 同族）
   - 影响：§4.3 命令签名、§8.1 skills.py 路径解析逻辑

3. **Q3 随安装包通道的收集方式**：
   - A：PyInstaller `datas` 显式收集进 `_internal/skills/`（推荐：GUI 包 + CLI zip 双覆盖，release.yml 零改动）
   - B：electron extraResources 旁置 `resources/skills/`（GUI 包专用，CLI zip 不含——纯 CLI 用户第三通道失效）
   - C：A + B 双放（覆盖最全，但双处收集 + 双处冒烟）
   - **建议：A**（单点收集零双份漂移；与 0.7.0 tiktoken 收集缺口教训修复方向一致）
   - 影响：§5.3/§8.2 MODIFY 面（A：仅 inkflow.spec；B：electron-builder.yml + release.yml）
