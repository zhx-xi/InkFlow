# 内核并发专题（内核相关轨必读）

> 内核（kernel）相关的轨容易踩的坑集中在此。**非内核轨可跳过**。
> 背景：#1171 / #1188 / #1192 / #1237 是本专题的历史缺陷链。

---

## 1 · 核心语义（现状，勿凭直觉）

| 概念 | 事实 |
|---|---|
| **instance kind** | `dev` \| `rc` \| `prod`（`release` 是 `prod` 的**兼容别名**） |
| **互斥维度** | **`kind` + `data_dir`**（不是全局，也不是单独 kind） |
| **互斥名称** | `InkFlowKernel<Kind>-<hash(data_dir)>` |
| **dev 语义** | **同 `data_dir` 单内核**（历史上 dev 允许多开 → #1188 收紧） |
| **rc / prod 语义** | 全局单内核（各 1 个） |

## 2 · 统一入口：`ensure_kernel`

⚠️ **所有拉核路径必须走 `ensure_kernel`**（`infrastructure/kernel/bootstrap.py`）。

**不要新造第三条拉核路径** —— #1237 的根因就是 GUI 走了自己的路径（不写 state）。

### 2.1 准入判定（#1192 后的形态）

存活期互斥被占时的判定：

| 情形 | 行为 |
|---|---|
| `kernel.json` **已就绪** | **复用**（`reused=True`） |
| `kernel.json` **未就绪**（含等待超时） | 拒绝（`KernelStartupError`） |

⚠️ 等待窗口**对齐调用方 `timeout`**（**不要**自造固定常量 —— #1192 的教训：
`_LIFETIME_REUSE_WAIT = 5.0` 硬截断导致高负载下并发冷启动误报冲突）。

⚠️ 等待分支**不得传 `abort_probe`**（存活期互斥语义是「持锁至进程退出」，抢锁会破坏准入）。

---

## 3 · 已验证的坑（不要重犯）

| # | 坑 | 症状 | 正确做法 |
|---|---|---|---|
| **1** | 只修「互斥被占直接抛错」不加等待 | 并发第 2 调用直接 `KernelStartupError`（#1171） | 被占时轮询 `kernel.json` 就绪再复用 |
| **2** | 等待窗口硬编码 | 高负载下对端冷启动 >5s → 误报「既有实例冲突」（#1192） | 窗口对齐调用方 `timeout` |
| **3** | GUI 侧不走统一入口 | GUI 内核**不写 `kernel.json`** → CLI 看不到 → 各起一个（#1237） | 所有拉核路径走 `ensure_kernel` |
| **4** | 测试用 mock 覆盖，未覆盖真实 state | 测试绿但真实场景不通（#1188 → #1237） | 契约必须覆盖**真实 state 文件读写** |
| **5** | 按「shim 名」清理进程 | `uv` shim 会起两个 `python.exe` → 按名清理**孤儿化真内核** | 用 `kernel.json` 记录的**真解释器 pid** |

---

## 4 · 验证方法（**真实形态，不要只跑单测**）

### 4.1 内核数不泄漏（CLI 连跑）

```powershell
$env:INKFLOW_DATA_DIR = '<隔离路径>\InkFlow'   # ⚠️ 必须带 \InkFlow 后缀
$PY = '<worktree>\backend\.venv\Scripts\python.exe'
1..5 | ForEach-Object {
  & $PY -m inkflow project list 2>&1 | Out-Null
  $n = (Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match 'inkflow.*serve' } | Measure-Object).Count
  "第 $_ 条命令后内核数: $n"
}
```

**判据**：5 行全为 **1**，且**无** `KernelStartupError`。

### 4.2 双进程并发（M1 门禁语义）

**两个进程**同时冷调 `ensure_kernel` → **恰一 spawn + 一 reuse**。

⚠️ 该用例在本机**高负载下可能红**（窗口大小依赖负载）→ 已由 #1192 修复对齐 `timeout`。
若仍红 → 先查是否又有硬编码窗口。

### 4.3 GUI / CLI 共享（#1237 语义）

```powershell
# 1) 起 GUI 内核（真实）
# 2) 查 state 是否写入
Test-Path "$env:INKFLOW_DATA_DIR\kernel.json"
# 3) CLI 调用 → 应复用
& $PY -m inkflow project list
# 4) 内核数应为 1
```

**判据**：GUI 起后 `kernel.json` **存在**；CLI 调用后内核数 **仍为 1**。

### 4.4 不同 data_dir 互不阻塞

换一个 `data_dir` 再起 → **两个内核并存**（各自 `kernel.json` 独立）。

---

## 5 · 换 kind 时的兼容性

| 旧值 | 新值 | 处置 |
|---|---|---|
| `release` | `prod` | ✅ 别名兼容（env / registry 旧文件） |
| 旧 `release-<pid>.json` 注册文件 | — | 被判非法跳过（惰性 GC，升级期短暂） |

⚠️ 改 kind 语义时**必须同步**：
- `adr/kernel/ADR-059.md`（取值表 + 语义表 + 备选方案）
- `specs/f30-kernel/spec.md`（§5.1 分支 / §5.3 并发承诺 / §5.6 准入顺序）
- `specs/f31-gui-tray/spec.md`（GUI spawn 语义）

---

## 6 · 常用命令

```powershell
# 查内核进程（含命令行）
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'inkflow.*serve' } |
  Select-Object ProcessId,Name,CommandLine

# 查 state 文件
Get-Content "$env:INKFLOW_DATA_DIR\kernel.json" | ConvertFrom-Json

# 查注册表目录
Get-ChildItem "$env:INKFLOW_DATA_DIR\instances" -ErrorAction SilentlyContinue
```
