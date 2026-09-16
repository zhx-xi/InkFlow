# 任务书模板（单轨）

> **用法**：复制本文件到 `.hermes/plans/<波次>-<轨>.md`，填充所有 `<...>` 占位符，
> **把全文贴到新会话**。
> ⚠️ **所有路径写绝对路径**（相对路径会导致新会话读不到前置）。
> ⚠️ 本模板内**不使用嵌套代码块**（避免粘贴到聊天时 Markdown 截断）。

---

# <波次>-<轨> · <一句话标题>（#<issue>）

> 独立会话提示词。前置：**先读 `D:\develop\projects\InkFlow\agents\CONVENTION.md`**（公共约定）。
> 本轨分支：`<branch>`，worktree：`D:\develop\projects\InkFlow-ft\<worktree-name>`
> <并行性说明：✅ 可与 <某轨> 并行（文件域不相交）／⚠️ 必须串行（与 <某轨> 同碰 <文件>）>

---

## 0 · 任务

你是 InkFlow 的**<角色>**（<如 后端工程师兼发布工程师>）。使用中文回复。

<1-2 句任务描述：修什么、为什么>

**端到端**：建 worktree → <写 RED 契约 / 恢复 RED 契约> → 实现 → 验收 → PR → 等 CI → **自动 merge** → 关 issue。

---

## 1 · 现象（可复现）

<可观测事实 + 复现命令 + 期望 vs 实际>

<给一张表或一段代码块，越具体越好>

---

## 2 · 根因（file:line）

⚠️ **已核实 / 待核实**（二选一，必须明确）

| # | 事实 | 位置 |
|---|---|---|
| 1 | <事实> | `<file>:<line>` |
| 2 | <事实> | `<file>:<line>` |

<若「待核实」→ 加一节「必做取证」，列 1-3 条具体取证命令>

---

## 3 · 目标设计

### 3.1 <子项>

<设计说明；若已有拍板方案，直接写「**用户已拍板方案 X**」+ 理由>

⚠️ **复用既有实现**（列出可复用的原语/模式）—— **不要新造抽象**。

### 3.2 <子项>

...

---

## 4 · 建 worktree

```powershell
cd D:\develop\projects\InkFlow
git fetch origin main; git checkout main; git pull origin main
git branch <branch> main
git worktree add D:\develop\projects\InkFlow-ft\<worktree-name> <branch>
cd D:\develop\projects\InkFlow-ft\<worktree-name>

cd backend; uv sync --frozen --extra dev; cd ..
New-Item -ItemType Directory -Force -Path .hermes\logs, .hermes\plans | Out-Null
```

<若前端轨 → 加：`cd frontend; pnpm install --frozen-lockfile; cd ..`>

**验证**：`git log --oneline -1` 应为最新 main 的 commit（**不得**指向旧 worktree 的 HEAD）。

---

## 5 · RED 契约

<二选一：>
<A. 已有契约 → 给恢复命令 + 「确认 RED」命令 + 期望失败数>
<B. 需新写 → 给落点 + 断言清单 + 可证伪要求>

**落点**：`<测试文件绝对/仓内路径>`

**断言清单**：
1. <断言描述>
2. <断言描述>
3. **反向断言**：<关键的反向/否证断言>

⚠️ **可证伪**：<如何证明该断言能因实现损坏而 FAIL>
⚠️ **行数护栏 900**：用 `..\ci_cd\check_file_length.py 900 <path>` 量（**禁用 `Measure-Object`**）。

---

## 6 · 验收

```powershell
cd D:\develop\projects\InkFlow-ft\<worktree-name>\backend

# ① 本轨目标断言
.\.venv\Scripts\python.exe -m pytest <目标路径> -q

# ② 回归
.\.venv\Scripts\python.exe -m pytest <回归路径> -q

# ③ 门禁
.\.venv\Scripts\python.exe -m ruff check src/ tests/ ../tests/ ../ci_cd/
.\.venv\Scripts\python.exe ..\ci_cd\check_file_length.py 900 src/ ../tests/ tests/unit/
.\.venv\Scripts\python.exe ..\ci_cd\check_noqa_reason.py src/ ../tests/ tests/unit/
```

**判据**：<目标全绿 + 回归无劣化 + 门禁全绿>

---

## 7 · 交付（含自动化）

```powershell
cd D:\develop\projects\InkFlow-ft\<worktree-name>
git add <本轨文件>
git commit -m "<type>(<scope>): #<issue> <描述>"
git push -u origin <branch>

gh pr create --title "<同 commit 标题>" --body-file D:\develop\projects\InkFlow\.hermes\plans\<波次>-<轨>-pr-body.md --base main
# body 必含：根因 + RED 先红后绿证据 + 验收真实输出 + Closes #<issue>

gh pr checks <N> --watch
gh pr merge <N> --squash
```

⚠️ `strict: true` → 若落后需 rebase 后**重等 CI**。
⚠️ `--delete-branch` 会失败（主仓占 main）→ 去掉该 flag。
⚠️ pre-commit 可能重排文件致 commit 未落地 → 重新 `git add` + commit。

---

## 8 · 预判裁定点（默认决策，⛔ 不要问人）

| 情形 | 默认决策 |
|---|---|
| <常见歧义 1> | <明确默认> |
| <常见歧义 2> | <明确默认> |
| Codex 报告测试有缺陷（测试侧） | 直接修测试（你是父侧） |
| Codex 报告实现缺 X（任务书外） | 验证前提：前提错 → 回退 + 修测试；前提对 → 收编 + 报告 |
| 既有测试因语义变更失效 | 语义升级 → 升级该测试 + 注释 |
| 已知 flaky | `gh run rerun --failed`；连续 2 次仍红 → **停**（S1） |
| 需改 `src/` 超出本轨范围 | **停**（S3） |
| CI 红且无法归因 | **停**（S1） |
| 发现新缺陷 | 建 issue 挂 `0.15.0`（不扩范围） |

---

## 9 · 交付报告

```markdown
# <波次>-<轨> 报告（#<issue>）

## 根因确认（file:line）
## 实现摘要（file:line）
## RED 契约先红后绿证据
## 验收结果（canonical 真实输出）
## PR / CI / merge commit
## 关闭的 issue
## 新建的 issue（若有）
## 自行处置记录
## 重大问题（若有 → 为何停）
## 未决问题
```

---

## 10 · 边界

- **不改** <本轨禁改的文件/范围>
- **不碰**其他轨的文件（`git status` 出现非本轨文件 → 不 commit）
- **不绕过**分支保护
- 结束清理 worktree（`git worktree remove <path> --force`）
