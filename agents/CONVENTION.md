# 公共约定（所有派轨会话必读）

> ⚠️ **读之前先确认本项目根路径**：本文所有路径以 `D:\develop\projects\InkFlow`（主仓）为基准。
> 若你的会话工作目录不同，**先 `cd` 到主仓**再执行。

---

## 0 · 授权边界

### ✅ 可自行（无需询问）

- `commit` / `push` / 建 PR
- 等 CI / **CI 全绿后自动 squash merge**
- 关闭本轨对应的 issue
- 发现新缺陷 → **建 issue 并挂对应里程碑**（用 `gh issue create --milestone "<里程碑名>"`）

### ❌ 必须停（见 §4「重大问题」）

---

## 1 · 里程碑

**当前活跃里程碑：`0.15.0`**（number `19`）

```powershell
gh issue create --title "<type>(<scope>): <描述>" --body-file <绝对路径> --milestone "0.15.0"
```

⚠️ 用**标题名**（`0.15.0`）而非 number，`gh` 会自动解析。
⚠️ **不要**给 issue 加其他里程碑（除非用户明确指定）。

---

## 2 · CI 门禁事实

### 2.1 main 分支保护

| 项 | 值 | 影响 |
|---|---|---|
| required approvals | **0** | ✅ **可自动 merge，无需人工 review** |
| **`strict: true`** | ⚠️ 分支须 up-to-date | **落后需 rebase，旧绿灯作废须重等** |
| `enforce_admins` | false | **禁止用于绕过**（未授权） |

### 2.2 required status checks（10 个）

```
lint-backend
unit-backend
unit-api-backend
unit-cli-backend
unit-integration-backend
lint-frontend
unit-frontend
build
e2e-frontend-shell
PR title check
```

⚠️ `coverage-backend` / `coverage-function` / `coverage-frontend` **不在 required 列表**，
但**仍建议等全部 job 完成**再 merge（避免 main 变红）。

### 2.3 PR 标题规范

```
^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^)]+\))?!?: [^A-Z]
```

⚠️ **description 首字符不得为大写**（`test(agent): W0+W1 ...` 会 FAIL）。

---

## 3 · 标准执行循环

```
1. 建 worktree（基于最新 main）→ 自包含初始化
2. 写/恢复 RED 契约 → 确认 FAIL
3. 实现（自己 or 派 Codex）
4. 父侧验收（canonical 命令，真实输出）
5. commit（Conventional Commits，description 首字符小写）
6. push
7. 建 PR（--body-file，标题合规）
8. gh pr checks <N> --watch
9. CI 全绿 → gh pr merge <N> --squash
10. 关 issue（带 commit/PR 引用）
11. gh run list --branch main --limit 3   ← 防「PR 绿 / main 红」
```

### 3.1 worktree 自包含初始化（**铁律**）

```powershell
cd D:\develop\projects\InkFlow
git fetch origin main; git checkout main; git pull origin main
git branch <branch> main
git worktree add D:\develop\projects\InkFlow-ft\<name> <branch>
cd D:\develop\projects\InkFlow-ft\<name>

cd backend; uv sync --frozen --extra dev; cd ..
New-Item -ItemType Directory -Force -Path .hermes\logs, .hermes\plans | Out-Null
```

⚠️ **venv 必须自建**（禁软链主仓 —— editable `.pth` 会解析到主仓源码）。
⚠️ **先建 `.hermes\logs`**（否则 Codex 派发的 `*>` 重定向 DirectoryNotFound，**零执行**）。
⚠️ 前端轨：`cd frontend; pnpm install --frozen-lockfile`。

### 3.2 Codex 派发（Windows）

```powershell
C:\PROGRA~1\nodejs\node.exe "C:\Users\<用户>\AppData\Roaming\npm\node_modules\@openai\codex\bin\codex.js" exec --json --dangerously-bypass-approvals-and-sandbox "Read the task brief at <绝对路径> and execute it completely." *> '.hermes\logs\<name>.log'
```

| 坑 | 处置 |
|---|---|
| 路径含空格 | **必须 8.3 短路径**（`C:\PROGRA~1\nodejs\node.exe`） |
| log 目录不存在 | **派发前先建** |
| 日志编码 | PS `*>` 落盘是 **UTF-16LE** → `io.open(log, encoding='utf-16')` |
| exit code 不可信 | 判「真在执行」以 **`git status` 落盘** + 日志字节增长为准 |
| 前台命令含 `&` | 会被拒 → 一律 `terminal(background=true)` |

### 3.3 `strict: true` 的 rebase

```powershell
git fetch origin main
git rebase origin/main
# 冲突 → 解决 → git add → git rebase --continue
git push --force-with-lease
gh pr checks <N> --watch   # ⚠️ 旧绿灯作废，必须重等
```

### 3.4 merge 失败排查

| 报错 | 处置 |
|---|---|
| `BLOCKED` | `gh pr view <N> --json mergeStateStatus`；多为 strict 落后 → rebase |
| `--delete-branch` 失败 | 主仓处于 main 时必失败 → 去掉该 flag，merge 后手工删分支 |
| `already merged` | 已成功，勿重复 |

---

## 4 · 🔴 重大问题（**必须停止并报告**）

| # | 情形 | 为什么停 |
|---|---|---|
| **S1** | CI 红且**无法归因**（连续 2 轮排查仍不明） | 可能是真回归 |
| **S2** | merge 后 **main 变红** | 基线破坏，影响所有在途 PR |
| **S3** | 需改 `src/` 才能让 CI 绿，但**超出本轨范围** | 越界风险 |
| **S4** | 需**绕过分支保护**（`--admin` / `enforce_admins`） | 未授权 |
| **S5** | 既有缺陷修复面 **> 本轨 3 倍工作量** | 应拆 issue |
| **S6** | **数据丢失 / 安全** 相关发现 | 高风险 |
| **S7** | 契约与实现**语义冲突**且无法判定哪边对 | 需设计决策 |
| **S8** | 与**已拍板决策矛盾**的新证据 | 需重新拍板 |

### 4.1 非「重大问题」的常见情形（**自行处理 + 报告记录**）

| 情形 | 处置 |
|---|---|
| Codex 报告「测试 mock 缺方法」 | 直接补 mock（镜像真实依赖语义） |
| Codex 报告「断言与实现语义冲突」 | 判定：契约错 → 改契约；实现缺 → 改实现 |
| 既有测试因语义变更失效 | 升级该测试 + 注释说明 |
| flaky（已知族） | `gh run rerun --failed`，记录 |
| rebase 冲突 | 解决（保留双方语义） |
| coverage 门禁红且是本轨新函数 | 补覆盖测试（**真实调用路径 + 可证伪**） |
| PR title check 红 | 改标题（description 小写起头） |
| 行数护栏触线（900） | 拆兄弟文件 |

---

## 5 · 环境陷阱（Windows 本机实测）

| 项 | 事实 | 处置 |
|---|---|---|
| **git proxy** | 本机 Clash 转发故障（7890 监听但返 `000`），**直连通** | push 前临时注释 `.gitconfig` + 主仓 `.git/config` 的 `proxy` 行 → push → 恢复 |
| **PowerShell 重定向** | `>` 会写 **UTF-16** | 用 `git diff --output=<file>` 或 `*>` + 读时指定 `encoding='utf-16'` |
| **`gh --jq` / `--template` 含特殊字符** | PS 会拆参 | 落盘 JSON 再解析（`encoding='utf-8-sig'` 处理 BOM） |
| **`gh run view --log-failed`** | 多 job 的 run 无输出 | 用 `gh api .../actions/jobs/<id>/logs` 直取 |
| **裸 `python`** | 本机是 Microsoft Store 存根（零输出 exit 1） | 一律用 `backend\.venv\Scripts\python.exe` |
| **行数计量** | `Measure-Object` 口径与护栏不一致（少计） | 用 `ci_cd/check_file_length.py 900 <path>` |
| **pre-commit** | 可能重排文件致 commit 未落地 | 重新 `git add` + commit；判据 `git log --oneline -1` 有新 hash |
| **ruff 版本** | 已统一（#1148）；CI 与 pre-commit 同版本 | 无需特殊处理 |
| **中文 Windows (936)** | 本机代码页 936 → stdout 编码相关 | 见 #1240 |

---

## 6 · 验收命令（后端通用）

```powershell
cd <worktree>\backend

# 本轨目标断言
.\.venv\Scripts\python.exe -m pytest <目标测试路径> -q

# 回归（按轨范围选）
.\.venv\Scripts\python.exe -m pytest tests/unit/<子域>/ -q

# 快门禁（必跑）
.\.venv\Scripts\python.exe -m ruff check src/ tests/ ../tests/ ../ci_cd/
.\.venv\Scripts\python.exe ..\ci_cd\check_file_length.py 900 src/ ../tests/ tests/unit/
.\.venv\Scripts\python.exe ..\ci_cd\check_noqa_reason.py src/ ../tests/ tests/unit/
```

⚠️ **不要求**跑全量 pytest（各轨并行会争资源；全量由收尾/CI 统一跑）。

## 7 · 前端通用

```powershell
cd <worktree>\frontend\packages\renderer    # 或 electron
node node_modules/vitest/vitest.mjs run
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js .
```

---

## 8 · 交付报告格式

```markdown
# <波次>-<轨> 报告（#<issue>）

## 实现摘要（file:line）
## RED 契约先红后绿证据
## 验收结果（canonical 命令 + 真实输出）
## PR 与 CI
- PR: #<N>
- CI: （逐 required check）
- Merge: squash commit <hash>
## 关闭的 issue
## 新建的 issue（若有，附里程碑确认）
## 自行处置记录（§4.1 类）
## 重大问题（若有 → 说明为何停）
## 未决问题
```
