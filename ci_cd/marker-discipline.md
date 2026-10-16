# 历史标记纪律（marker discipline）

> 本文是**策略**；规则本体与豁免白名单以 `AGENTS.md §12` 为准。检查脚本
> `ci_cd/check_marker_discipline.py` 由**本地 / agent** 在提交前跑，**不挂 CI**（其单测随既有
> `lint-backend` job 运行，只验证脚本自身正确性）。

## 1. 规则

文档与代码**不记录** issue/PR 号、日期、项目版本号。

理由：这些内容的正确归属是 **git 履历 + ADR + issue 页**。写在文档与代码里只产生两类成本——
① 对 AI agent 是纯噪音（跳转线索而非可执行信息，稀释上下文注意力）；② 随时间腐烂
（issue 会关闭、日期会误导、版本会过时）。

## 2. 豁免面（这些位置的标记是文件用途本身）

| 位置 | 允许内容 |
|------|----------|
| `CHANGELOG.md` | 版本 + 发布日期（Keep a Changelog 节标题骨架） |
| `FEATURES.md` / `README.md` | 版本→功能映射表、版本进度表 |
| `adr/README.md` | 决策日期列 |
| ADR 头部 | `> **日期**` / `> **状态**` / `> **依据**`（Nygard 格式） |
| spec 头部 | `**Spec 版本**` / `**依据**` |
| 生成物 | `ci_cd/openapi_snapshot.json`、`frontend/packages/renderer/src/api/schema/openapi.d.ts` |
| 检出器自身的契约测试 | `ci_cd/tests/test_check_marker_discipline.py`（**测试样本即该文件的用途**；精确单文件，不豁免整个 `ci_cd/` 或 `ci_cd/tests/`） |
| **文档标识** | `ADR-0NN`、`PRD vX.Y`、`Constitution P1-P6`、`spec §N`、`python 3.13`、`ruff vX.Y.Z` |

> 「文档标识」指**指向文档/规范/依赖的标识符**，不是时间线标记——删除会失去指向。
> 判据：它指向**一个仍然存在的文档/依赖**（而非「某次改动发生在何时」）。

## 3. 替代写法

| 禁止 | 允许 |
|------|------|
| `（#NNNN 实测）` | `（实测）` |
| `#NNNN A 项：默认参惰性化` | `默认参惰性化` |
| `YYYY-MM-DD 拍板` | `已拍板` / 直接删除 |
| `X.Y.Z 起生效` | `自本版起` / 直接删除 |
| `spec §N.N.N` | 保留（章节号，非标记） |

## 4. 怎么检查（本地，不挂 CI）

```powershell
# 只查本次**新增的行**（默认基准 origin/main）——存量脏文件可正常编辑，只拦新写进去的标记
python ci_cd/check_marker_discipline.py --diff
python ci_cd/check_marker_discipline.py --diff --base <ref>

# 全仓整文件（收尾/验收用；豁免面外应清零）
python ci_cd/check_marker_discipline.py --all
```

退出码：`0` 无命中 / `1` 有命中 / `2` 参数错误。可从任意 cwd 调用（脚本自寻 git 根）。

> `--diff` 取 `git diff` 的 `+` 行（含已提交改动 ∪ 工作区）。**不**扫整文件——否则治理
> 期间对存量脏文件的任何编辑都会让门禁恒红，门禁将不可用。

命中后处置：删除标记，或**改写为规范陈述**（若该行承载的是规范内容而非历史叙述）。

## 5. 不校验什么（能力边界，务必知晓）

- **短号** `#` 后 1-2 位：实测约 345 处是本地枚举（`spec §7 #8`、`测试契约 #3`、`设计假设 #2`），
  混着真实短号 → **只能人工判**，不进自动检出。
- **spec 元叙述**（`用户拍板`/`已合入`/`已实现`）与**实现代码块**：属一次性治理（判据需语义理解，
  非正则可覆盖），不做常规门禁。
- **`.gitignore` 等无后缀文件**：不在扫描面。
- **豁免面内的一切**（见 §2）。
- **改了标记但没有新建/修改对应记录**：本脚本查「新出现的标记」，查不出「该留的痕迹没留」。

## 6. 假阳性族（人工判时别误伤）

自动抑制已覆盖：URL、ISO 时间戳（`YYYY-MM-DDThh:mm:ssZ`）、依赖/工具版本、版本键值形态
（`version: "X.Y.Z"`）、IPv4、CSS 十六进制色值、`§N.N.N` 章节号、SVG path。

下列**不是**标记，不得清理：

| 形态 | 例 |
|------|-----|
| 测试 mock 数据 | `created_at: 'YYYY-MM-DDThh:mm:ssZ'`、`{ version: 'X.Y.Z' }` |
| 版本解析 fixture | `normalize_version("vX.Y.Z-rc.1")` |
| 第三方钉版 | `chromadb X.Y.Z`、`ruff vX.Y.Z`、action `version: "X.Y.Z"` |
| 资源版本号 | URL 内的 `vX.Y.Z` 路径段 |

## 7. 与生成物的联动

backend 的 Pydantic 模型 / DTO docstring 会被 `app.openapi()` 搬进 `description` → 落到
`ci_cd/openapi_snapshot.json`，再被 `pnpm gen:api` 搬进 `openapi.d.ts`。

**清理 docstring 里的标记时，必须同 commit 重生成两件**，否则快照对拍与前端类型漂移检查双红：

```powershell
# ① 后端快照（cwd = backend/）
uv run python ../ci_cd/export_openapi.py

# ② 前端类型（cwd = frontend/packages/renderer/）
pnpm gen:api
```

## 8. 查历史（取代「修改履历」记录）

```bash
git log -p --follow -- specs/fXX-<name>/spec.md   # 每次改动一个 commit（squash merge 后为 PR 级粒度）
git log -S"<被删的原文>" -- specs/                # 反查某段文字何时消失
```
