# F31: GUI 托盘常驻 + 关闭行为设置（gui_tray）— 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-07 | **依据**: ADR-030（本地内核服务化 ③）、ADR-021（内核进程化交付契约）、F30 spec（内核冷启动基建）、Constitution P1-P6
>
> **所属阶段**: 0.5.0 Agent 集成（本地内核服务化三件套第 2 个模块，估算 2-3 人天）
>
> **关联 Issues**: #167（本模块）；#166（F30 内核冷启动，✅ 已合入 PR #171）；#168（CLI 产物，独立）；#169（CLI 恒 HTTP，独立）；#152（设置持久化，口径归口）
>
> **依赖**: ✅ F30（kernel.json 契约 + ensure_kernel 语义，PR #171 41013fb）· ✅ F19 #78（Electron 壳：spawn/健康检查/崩溃拉起/回收）· ✅ F19 #106（自绘窗口按钮 IPC：window:close 通道）· ⏳ #152（设置持久化——**归口依赖，本模块用临时内存态，合入后切换**）
>
> **参考 ADR**: [ADR-030](../../adr/ADR-030.md)（③ GUI 托盘常驻：关闭→托盘、托盘退出=真退出、单实例、复用内核）· [ADR-021](../../adr/ADR-021.md)（内核进程化：INKFLOW_READY/端口文件/token）· [ADR-019](../../adr/ADR-019.md)（版本里程碑）
>
> **状态**: ✅ 已实现（PR #172，#167 2026-08-08）

---

## 1. 概述

F31 为 InkFlow 桌面 GUI（Electron 壳）增加**托盘常驻能力**（ADR-030 ③）：窗口关闭默认最小化到系统托盘（内核保持运行），托盘菜单提供「打开主窗口 / 内核状态 / 退出」，托盘「退出」= 真退出（stopKernel + app.quit）；关闭行为可在设置页切换为「直接退出」；GUI 启动时复用已有内核（读 kernel.json，健康则直接连接不 spawn）；GUI 单实例（已运行再启动 → 聚焦已有窗口）。

本模块是 **ADR-030 本地内核服务化的 GUI 侧落地**：与 F30（内核冷启动基建）同属一个服务化愿景，F30 提供跨客户端发现协议（kernel.json + ensure_kernel），本模块让 GUI 成为该协议的**消费方 + 常驻宿主**——GUI 拉起的常驻内核同样写入 kernel.json，供 CLI/MCP/skills 复用（双向闭环）。

### 1.1 模块类型定位（前端壳层变体）

> **变体编号声明**：AGENTS.md 模块类型谱系（F9-F30）覆盖后端模块变体；本模块为 **Electron 主进程壳层功能**，沿用 f19 §4 先例（「前端栈变体，不沿用第 N 变体编号」），归属前端栈。编号承接 F30 之后（F31，若冲突以 ADR-019 v5+ 为准）。

**特征：纯前端 + 零后端新增**——不新建实体、不新增 API 端点、不新增 CLI 命令；全部改动落在 `frontend/packages/electron/`（主进程）+ `frontend/packages/renderer/`（设置页）+ `tests/e2e/`（集成测试）+ `.github/workflows/ci.yml`（E2E job 收集）。

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ **无**（关闭行为设置 = 主进程内存态，归口 #152 持久化） |
| 新 API 端点 | ❌ 无（复用既有 /health 探测） |
| 新 CLI 命令 | ❌ 无 |
| 核心机制 | ✅ Tray 生命周期 + 关闭拦截状态机 + 单实例锁 + Node 侧内核复用判定 + kernel.json 写入 |
| 跨模块 MODIFY | ✅ F30 零改动（纯消费）；F19 壳 main.ts/kernel.ts/preload.ts 扩展；renderer settings.tsx 加设置项 |

### 1.2 边界声明

- **不做持久化**：#152 未合入前关闭行为设置 = **主进程会话级内存态**（重启回默认「最小化到托盘」）；#152 合入后切换为 #152 的持久化机制（评论区拍板 2026-08-07：归口合并，同一设置库）
- **不做 CLI 恒 HTTP**（归 #169）——本模块只让 GUI 消费 kernel.json，不改造 CLI 调用路径
- **不做 CLI 独立打包**（归 #168）
- **不做内核空闲回收/自动退出**（ADR-030 D2=A：常驻到显式退出；托盘「退出」是唯一显式控制面）
- **不做开机自启 / 多显示器 / 系统级通知中心**（YAGNI，不在本 issue 验收范围）

---

## 2. 数据模型

**无业务实体、无数据库表**。两个数据面：

1. **kernel.json 状态文件**（F30 §2.1 契约，只读消费 + GUI spawn 成功后写入）——五字段 `{port, token, pid, version, started_at}`
2. **关闭行为设置**（进程内内存态，本模块新增）——`CloseBehavior = 'tray' | 'quit'`，默认 `'tray'`

### 2.1 kernel.json 消费契约（F30 §2.1 引用，本模块只读侧）

| 字段 | 类型 | 用途（GUI 侧） |
|------|------|----------------|
| `port` | int | 复用判定：/health 探测目标 |
| `token` | str | 复用判定：X-InkFlow-Token 头 |
| `pid` | int | 复用判定：进程存活探测 |
| `version` | str | 记录展示（内核状态菜单）+ 与 /health 返回 version 一致性 |
| `started_at` | str | 记录展示（内核状态菜单） |

**读取规则**（与 F30 一致）：文件不存在 / JSON 解析失败 → 视为无内核；pid 不存在 → stale（重命名备份 `kernel.json.stale-<ts>`）→ 视为无内核；pid 存活 + /health 200 → 复用。

### 2.2 关闭行为设置（内存态）

```typescript
/** 主进程持有（模块级变量，ipcMain 读写；#152 合入后改为读 #152 设置库） */
type CloseBehavior = 'tray' | 'quit';
let closeBehavior: CloseBehavior = 'tray';          // 默认：最小化到系统托盘
let trayHintDismissed = false;                       // 「仍在后台运行」提示不再显示
```

| 项 | 值 |
|----|-----|
| 默认值 | `'tray'`（最小化到系统托盘，ADR-030 ③ 拍板） |
| 作用域 | 会话级内存态——重启回默认；#152 合入后切换持久化 |
| 消费方 | 主进程 `win.on('close')` 拦截逻辑（§5.2） |
| 变更路径 | renderer 设置页 → preload IPC `settings.setCloseBehavior()` → 主进程内存变量 |

> **决策论证**（对照备选）：
> | 备选方案 | 优点 | 缺点 | 结论 |
> |----------|------|------|------|
> | **主进程内存态（选定）** | 与 #152 归口拍板一致；零持久化基建；关闭拦截在主进程天然可读 | 重启回默认（可接受的过渡语义） | ✅ 选定——#152 合入前唯一合规形态 |
> | renderer localStorage | 重启保留 | 绕过 #152 统一设置库 = 两套设置系统（拍板明确禁止）；主进程读不到（跨进程） | ❌ 否决 |
> | 本模块自带 config.json 后端化 | 重启保留 | 与 #152 重复建设；拍板明确「同一设置库，避免两套设置系统」 | ❌ 否决（#152 专责） |

### 2.3 IPC 契约（preload 扩展）

`window.INKFLOW_API` 新增 `settings` 命名空间（与既有 `windowControls` 并列，#106 先例）：

```typescript
// preload.ts 扩展（sandbox 下 contextBridge 可用，f19 §3.3）
settings: Object.freeze({
  getCloseBehavior: (): Promise<CloseBehavior> => ipcRenderer.invoke('settings:get-close-behavior'),
  setCloseBehavior: (value: CloseBehavior): Promise<void> => ipcRenderer.invoke('settings:set-close-behavior', value),
  // 首次托盘提示的「不再提示」勾选（内存态；toast 由 renderer 弹，勾选经此通道）
  dismissTrayHint: (): Promise<void> => ipcRenderer.invoke('settings:dismiss-tray-hint'),
})
```

| 通道 | 方向 | 语义 |
|------|------|------|
| `settings:get-close-behavior` | invoke（renderer→main） | 返回当前关闭行为（设置页 Select 初值） |
| `settings:set-close-behavior` | invoke | 更新主进程内存态（即改即生效，无需重启） |
| `settings:dismiss-tray-hint` | invoke | 置 `trayHintDismissed = true`（首次提示勾选「不再提示」） |
| `inkflow:tray-hint` | main→renderer（webContents.send） | 首次最小化到托盘时通知 renderer 弹 toast「InkFlow 仍在后台运行」 |

> **契约约束**：主进程所有 IPC handler 幂等注册（`ipcMain.handle` 在 `app.whenReady` 回调内注册一次）；renderer 无 `window.INKFLOW_API.settings` 时（Vite dev 浏览器模式）可选链吞掉调用（#106 WindowControls 先例）。

---

## 3. API 契约

**无新增 API 端点**。消费既有：

| 方法 | 路径 | 用途 | 归属 |
|------|------|------|------|
| GET | `/health` | 内核存活探测（带 X-InkFlow-Token，200 = 活） | F19（已实现） |

复用判定探测 = `fetch(http://127.0.0.1:${port}/health, { headers: { 'X-InkFlow-Token': token }, signal: AbortSignal.timeout(3_000) })`——与 main.ts 既有 `checkHealthOnce` 同构（复用常量 `HEALTH_TIMEOUT_MS`）。

---

## 4. CLI 命令签名

**无新增 CLI 命令**。F30 的 `inkflow kernel status`（dev 调试命令）作为排障手段继续存在，本模块不新增。

---

## 5. 托盘生命周期与内核复用（关键差异节）

### 5.1 模式总览

```
GUI 启动
   │
   ├─ 单实例锁（app.requestSingleInstanceLock）
   │    ├─ 获取失败 → 已有实例 → app.quit()（不 spawn、不开窗）
   │    └─ 获取成功 → 正常启动
   │
   ├─ 内核连接（启动时序：先复用判定，后回落 spawn）
   │    ├─ 读 kernel.json → pid 存活 + /health 200 → 复用（不 spawn，reused 语义）
   │    └─ 无/stale → spawnKernel()（#78 既有逻辑）→ INKFLOW_READY → **写 kernel.json**（新增）
   │
   ├─ 窗口关闭（自绘按钮 / Alt+F4 / 任务栏关闭 → win.on('close') 拦截）
   │    ├─ closeBehavior = 'tray'（默认）→ preventDefault + hide() + 首次托盘提示
   │    └─ closeBehavior = 'quit'      → 不拦截 → window-all-closed → shutdown()
   │
   └─ 托盘菜单
        ├─ 打开主窗口 → show() + focus()（窗口被销毁则重建）
        ├─ 内核状态 → 端口 + PID + 版本 + 健康（只读展示，随健康检查刷新）
        └─ 退出 → stopKernel() + app.quit()（复用 #78 shutdown() 逻辑，完整回收含超时兜底）
```

### 5.2 关闭拦截状态机（核心）

| 状态 | 触发 | 行为 |
|------|------|------|
| `tray`（默认） | 窗口 close 事件 | `event.preventDefault()` + `win.hide()`；内核**保持运行**（不触发 shutdown）；首次（`!trayHintDismissed`）→ `webContents.send('inkflow:tray-hint')` |
| `tray` | 托盘「打开」 | 窗口隐藏 → `win.show()` + `win.focus()`；窗口被销毁（异常）→ `createMainWindow()` 重建 |
| `tray` | 托盘「退出」 | `shutdown()`（复用 #78：stopKernel 优雅 kill → 3s 超时 taskkill 兜底 → app.exit(0)）；`tray.destroy()` |
| `quit` | 窗口 close 事件 | 不拦截 → 窗口销毁 → `window-all-closed` → `shutdown()`（#78 既有路径） |
| 任意 | `app.before-quit` | 幂等守卫（quitInProgress）维持 #78 现状 |
| 任意 | 窗口被外部销毁（win.destroy() 等，不触发 close） | `window-all-closed` 触发：**仅 `quit` 模式或 quitInProgress 时 shutdown**；`tray` 模式下不退出（托盘仍在，可经「打开」重建窗口） |

> **关键差异（#78 改造点）**：#78 的 `window-all-closed → 无条件 shutdown()` 在托盘模式下**必须改为条件退出**——否则窗口意外销毁会杀掉常驻内核，违背托盘语义。这是本模块对 #78 生命周期的**行为变更**，需同步更新 f19 §3 相关表述（或在本 spec §12 决策表留痕，实现 PR 不触碰 f19 spec 已合入章节——**以本 spec 为准，f19 §3 修订随 docs 收尾**）。

**首次托盘提示**（需求 3）：
- 触发条件：`closeBehavior === 'tray'` 且 `!trayHintDismissed` 且窗口首次 hide
- 流程：主进程 `webContents.send('inkflow:tray-hint')` → renderer 收到后弹 toast「InkFlow 仍在后台运行，已最小化到系统托盘」+ 勾选框「不再提示」（toast 组件支持操作区，#99 交互反馈既有）
- 勾选 → renderer 调 `window.INKFLOW_API.settings.dismissTrayHint()` → 主进程置 `trayHintDismissed = true`（内存态，重启后重新提示）

### 5.3 内核复用判定（Node 侧 ensure_kernel 等价逻辑）

**架构约束**：F30 的 `ensure_kernel()` 是 Python 库（`inkflow.infrastructure.kernel.bootstrap`），Electron 主进程（Node.js）**无法 import**。GUI 侧必须在 Node 实现等价的三态判定（kernel.json 读取 + 存活探测 + 健康探测），但**不复制** ensure_kernel 的互斥/轮询/秒退重试（那是拉起方逻辑，GUI spawn 仍走 #78 既有 spawnKernel 链路）。

```
Node 侧判定（kernel.ts 新增纯函数，vitest 可测）：
  readKernelStateFile(path) → KernelState | null      // 读 + JSON 解析 + 五字段校验
  isProcessAlive(pid) → boolean                        // process.kill(pid, 0) 捕获 ESRCH（Node 侧
                                                       // 可用——e2e-shell.spec.ts L56 已实证；
                                                       // WinError 87 是 Python os.kill 的坑，Node 无此问题）
  probeHealth(port, token, timeoutMs) → boolean        // fetch /health 200
  → 三者全真 = 复用（reused）
```

**复用路径**：判定成功 → `kernelInfo = {port, token, pid, version}`（version 以 kernel.json 为准，与 /health 返回一致校验）→ `sendReadyToRenderer()` + `startHealthCheck()` → **不 spawn**。

**版本校验（YAGNI 决策）**：GUI 不做 major 版本校验——GUI 与内核同仓库同发布（打包 = resources/kernel/inkflow.exe 同版本；dev = 同 repo venv），版本漂移场景不存在；kernel.json version 与 /health 返回 version 不一致视为 stale（防御性校验，无需引入 GUI 自身版本概念）。CLI 侧版本校验继续由 F30 ensure_kernel 负责。

**stale 处理**：判定 stale → 重命名 `kernel.json.stale-<ts>`（保留现场，F30 §5.1 分支 4 语义）→ 回落 spawnKernel()。

### 5.4 GUI spawn 内核后写 kernel.json（双向闭环，本模块新增）

**为什么必须**：ADR-030 ①「GUI 与 CLI 同内核」。若 GUI 拉起的常驻内核不写 kernel.json，则：
- CLI 调用（#169 后）→ ensure_kernel 读 kernel.json → 无记录 → 拉起**第二个**内核 → 双内核并存（端口不同、SQLite WAL 竞争）→ 违背单实例语义
- MCP/skills（F20）同样无法发现 GUI 常驻内核

**实现**：spawnKernel 收到 INKFLOW_READY（kernelInfo 就绪）后，原子写 `%APPDATA%\InkFlow\kernel.json`：

```typescript
// kernel.ts 新增 writeKernelStateFile（原子写：临时文件 + rename，F30 同模式）
// 五字段：{port, token, pid, version, started_at: new Date().toISOString()}
```

写入时机：`spawnKernel()` 内 INKFLOW_READY 解析成功 → `kernelInfo` 赋值后立即写（与 `startHealthCheck()` 并行）。**失败降级**：写入失败（%APPDATA% 不可写等）→ console.error 记录，不阻塞 GUI（GUI 仍可自用内核；仅影响其他客户端发现——F30 §7 边界 #11 同语义）。

> **路径一致性**：F30 的 state_file = `config.data_dir / "kernel.json"`（%APPDATA%\InkFlow\kernel.json，Windows）。GUI 侧路径 = `path.join(app.getPath('appData'), 'InkFlow', 'kernel.json')`（app.getPath('appData') = %APPDATA%，与 config.data_dir 对齐）。dev 模式下同样写 %APPDATA%（F30 dev 默认 data_dir 即 %APPDATA%\InkFlow，行为一致）。

### 5.5 单实例（需求 5）

```
app.whenReady 内：
  const gotLock = app.requestSingleInstanceLock();
  if (!gotLock) { app.quit(); return; }        // 已有实例 → 本进程立即退出（不 spawn 不建窗）
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show(); mainWindow.focus();   // 托盘隐藏态也恢复显示
    } else {
      createMainWindow();                       // 窗口被销毁但托盘仍在 → 重建
    }
  });
```

**时序**：单实例锁获取必须在 `createMainWindow()` / `spawnKernel()` **之前**（app.whenReady 回调首行）——否则第二个实例会短暂开窗/spawn。`app.quit()` 后进程退出，不触发 window-all-closed（无窗口）。

### 5.6 托盘实现（Tray + 菜单）

| 项 | 值 |
|----|-----|
| 图标 | `frontend/packages/electron/inkflow-icon-256.png`（#98 品牌资产已入库，nativeImage.createFromPath） |
| 创建时机 | `app.whenReady` 内（与窗口创建并行）；`app.isPackaged` 与否都创建（dev 也可见托盘，E2E 可断言） |
| 菜单项 | 「打开主窗口」（default）· 「内核状态」子菜单（端口 / PID / 版本 / 健康，只读 disabled）· 分隔 · 「退出」 |
| 内核状态刷新 | 复用既有 2s 健康检查：健康状态变化时 `tray.setContextMenu(重建菜单)`（防抖：仅状态翻转时重建，避免每 2s 重建） |
| 点击托盘图标 | Windows 惯例：单击/双击 → 打开主窗口（`tray.on('click', showWindow)`） |
| 退出流程 | 「退出」→ `shutdown()`（stopKernel 完整回收 + app.exit(0)）；先 `tray.destroy()` 防托盘残留 |
| 健康状态展示 | 菜单项 label：`内核状态: 运行中 (port 端口 · pid PID)` / `内核状态: 未运行`——跟随健康检查实时更新 |

**托盘与窗口生命周期**：
- 托盘持有期 = 应用生命周期（`tray` 模块级变量，`app.quit` 时自动销毁；显式 destroy 防 Windows 托盘残留图标）
- `window-all-closed` 在托盘模式下**不退出**（§5.2）——Electron 默认行为是窗口全关即退出，需显式 `event.preventDefault()`（在 window-all-closed handler 内，tray 模式）

---

## 6. 组织规则

### 6.1 代码组织

- **主进程纯函数**（无 electron import，vitest node 可测）→ `kernel.ts` 扩展：kernel.json 读写、进程存活判定、复用判定、菜单 label 格式化
- **主进程副作用**（electron API）→ `main.ts` 扩展：Tray 创建/菜单/销毁、关闭拦截、单实例锁、IPC handler
- **renderer 设置项** → `settings.tsx` GeneralPanel 增加「关闭窗口时」Select + 首次提示开关（可选展示，随 toast 勾选）

### 6.2 设置页 UI（renderer）

「关闭窗口时」设置项位置：**GeneralPanel（常规分类）**——与 AppearanceCard（主题/语言）同区，属应用级设置（非项目 config）。UI 形态：

| 项 | 值 |
|----|-----|
| 文案 | 「关闭窗口时」+ Select：`最小化到系统托盘`（默认）/ `直接退出` |
| i18n | `set.closeBehavior` / `set.closeBehavior.tray` / `set.closeBehavior.quit` |
| 交互 | 选择即生效：`setCloseBehavior(v)` invoke → 主进程内存态更新 →（无需重启，下一次关闭即按新行为） |
| 初值 | 挂载时 `getCloseBehavior()` 异步取主进程当前值（默认 'tray'） |

> 首次提示「不再提示」勾选在 toast 内（§5.2），**不**额外占设置页空间（YAGNI；#152 合入后如需持久化展示再加）。

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| 1 | kernel.json 不存在 | 视为无内核 → spawnKernel()（#78 既有） |
| 2 | kernel.json 损坏（JSON 解析失败） | 视为无内核 → 重命名 `.stale-<ts>` → spawnKernel() |
| 3 | kernel.json 存在但 pid 不存在（崩溃残留） | stale → 清理 → spawnKernel() |
| 4 | pid 存在但 /health 超时/非 200 | stale → 清理 → spawnKernel()（token 失效/端口被占） |
| 5 | kernel.json version 与 /health 返回 version 不一致 | stale → 清理 → spawnKernel()（防御性，理论上同版本） |
| 6 | GUI spawn 后 kernel.json 写入失败（%APPDATA% 只读） | console.error 记录 + 继续（GUI 自用不受影响；其他客户端无法发现——F30 边界 #11 同语义） |
| 7 | 单实例锁获取失败（已运行） | `app.quit()`——不 spawn、不开窗、不弹错（静默让位给已有实例） |
| 8 | second-instance 时窗口隐藏（托盘态） | restore/show/focus（用户感知 = 窗口弹出） |
| 9 | second-instance 时窗口被销毁（托盘残留） | `createMainWindow()` 重建（复用 #78 创建逻辑） |
| 10 | 托盘「退出」时内核 stopKernel 超时 | #78 三级兜底：优雅 kill → 3s 超时 taskkill → 硬上限；`app.exit(0)` 兜底不挂起 |
| 11 | 窗口被外部销毁（不触发 close 事件）且为 tray 模式 | `window-all-closed`：**不** shutdown（托盘仍在）；「打开」重建窗口 |
| 12 | closeBehavior='quit' 时窗口关闭 | 完整退出（shutdown + 内核回收）——用户显式选择 |
| 13 | 健康检查失败（内核崩溃）于托盘模式 | #78 既有崩溃拉起逻辑不变（自动重拉，退避 1s→30s，6 次弹错误框）；托盘菜单状态同步刷新 |
| 14 | E2E 中窗口关闭 | Playwright `app.close()` 触发 before-quit → 回收（#78 既有）——托盘测试用 `window.evaluate(() => window.close())` 或触发自绘按钮走 close 拦截路径 |

---

## 8. 文件结构

对照真实源码树（2026-08-07 实测）：

```text
frontend/packages/electron/
├── src/
│   ├── main.ts                       ← MODIFY: 单实例锁 + 关闭拦截状态机 + Tray 创建/菜单/销毁 +
│   │                                    window-all-closed 条件退出 + IPC handler（settings:*）+ tray-hint 发送
│   ├── kernel.ts                     ← MODIFY: readKernelStateFile / writeKernelStateFile /
│   │                                    isProcessAlive / probeHealth / tryReuseKernel /
│   │                                    内核状态菜单 label 格式化（纯函数，vitest node 可测）
│   ├── preload.ts                    ← MODIFY: INKFLOW_API.settings 命名空间（§2.3）
│   ├── main.window-controls.test.ts  ← MODIFY（或不改）: 既有契约保持
│   ├── main.tray.test.ts             ← CREATE: 托盘/关闭拦截/单实例/IPC 单测（mock electron，#106 先例）
│   ├── kernel.state.test.ts          ← CREATE: kernel.json 读写/复用判定纯函数单测
│   └── preload.test.ts               ← MODIFY: settings 命名空间契约断言
│
└── vitest.config.ts                  ← MODIFY: 覆盖率 thresholds 上调（新代码计入）
frontend/packages/renderer/src/
├── pages/settings.tsx                ← MODIFY: GeneralPanel 加「关闭窗口时」Select（§6.2）
├── pages/settings.test.tsx           ← MODIFY: 设置项渲染/交互契约
└── src/i18n/*                        ← MODIFY: set.closeBehavior 文案（zh/en）
tests/e2e/
├── e2e-tray.spec.ts                  ← CREATE: 托盘 E2E（§9）
└── e2e-shell.spec.ts                 ← MODIFY（仅当复用内核断言并入壳契约；否则不动）
.github/workflows/ci.yml              ← MODIFY: e2e-frontend-shell job 命令追加 e2e-tray 文件参数
```

> **E2E 收集机制**：playwright `testDir=../../../tests/e2e` 自动收集目录内全部 `*.spec.ts`；CI 的 e2e-frontend-* job 用 `pnpm --filter inkflow-electron test:e2e <文件名>` 按文件过滤——**新文件 e2e-tray.spec.ts 必须显式加入 e2e-frontend-shell job 的 run 命令参数**（托盘属壳域，恒跑 required 批次，ADR-028 语义）。

---

## 9. 测试策略

| 层次 | 关键场景 |
|------|----------|
| 单元（vitest node，electron 包） | kernel.json 读写（正常/损坏/缺字段/原子写）；进程存活判定（存在/不存在）；/health 探测（200/非 200/超时）；复用判定组合（三态 × 版本）；菜单 label 格式化；关闭拦截状态机（tray→hide / quit→放行 / tray 模式 window-all-closed 不退出）；单实例锁分支（获取失败→quit）；IPC handler（get/set/dismiss 幂等）；Tray 创建/菜单重建防抖/销毁 |
| 单元（vitest jsdom，renderer 包） | settings.tsx「关闭窗口时」Select 渲染默认 'tray'；切换 → `setCloseBehavior` 调用断言；无 API 时可选链安全 |
| 集成（Playwright `_electron`，tests/e2e/e2e-tray.spec.ts） | ① 关闭→窗口隐藏+内核存活：点自绘关闭按钮（或 `window.close()`）→ `app.evaluate(win.isVisible() === false)` + `__kernelInfo.pid` 存活 + /health 200 + 托盘已创建（`__trayInfo` 钩子）；② 托盘「打开」→ 窗口恢复可见；③ 托盘「退出」→ 内核 pid 不再存活 + 应用退出；④ 设置切换「直接退出」→ 关闭 = 完整退出（内核回收）；⑤ 单实例：二次启动 → 不双开不双内核（`__kernelInfo.pid` 唯一 + 窗口唯一）；⑥ 复用：先 `ensure_kernel()`（Python 侧拉起，写 kernel.json）→ GUI 启动 → `__kernelInfo.pid` === 预拉起 pid（不 spawn） |
| 手动冒烟（Windows） | 关闭 → 系统托盘出现 InkFlow 图标；托盘右键菜单三件齐全；「退出」后 `Get-Process inkflow*` 为空；重启 GUI 复用同一内核（pid 不变） |

**测试钩子扩展**（dev 模式，`app.isPackaged === false`）：
```typescript
// main.ts 追加（#78 __kernelInfo 同模式）
(globalThis as any).__trayInfo = { created: boolean, closeBehavior: string, windowVisible: boolean };
```
Playwright `app.evaluate` 断言托盘状态；托盘菜单项点击经 `app.evaluate` 直接调用主进程导出函数（`(globalThis as any).__trayActions?.quit()`），避免驱动真实系统托盘（CI 无托盘交互能力）。

**覆盖率门槛**：electron vitest.config.ts thresholds 上调（新文件计入后基线提升，实现时以 CI 实测为准）；renderer vitest.config.ts 保持既有门槛（设置页 3 个新断言计入 settings.test.tsx）。

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| 关闭行为设置持久化（重启保留） | #152 设置持久化（归口拍板：同一设置库；本模块仅临时内存态） |
| 内核空闲超时自动退出 | ADR-030 D2=A 否决（常驻到显式退出） |
| CLI 恒 HTTP 路由改造 | #169（F30 消费方，独立 issue） |
| CLI 独立打包发布 | #168 |
| MCP 薄客户端 | #49 / F20（1.0.0，ADR-023 v2） |
| 开机自启 / 登录时启动 | YAGNI（未拍板，用户可后续提） |
| 系统通知中心（Windows Toast Notification） | toast 走 renderer 既有系统（#99），不引入 OS 通知 |
| 多显示器 / 跨屏记忆窗口位置 | YAGNI（未拍板） |

---

## 11. 依赖关系

| 依赖方 | 依赖 | 说明 |
|--------|------|------|
| F31（本模块） | F30 #166 ✅（PR #171） | kernel.json 五字段契约 + ensure_kernel 语义（GUI 侧 Node 等价实现） |
| F31 | F19 #78 ✅ | Electron 壳既有 spawn/健康检查/崩溃拉起/stopKernel/shutdown 全链路复用 |
| F31 | F19 #106 ✅ | 自绘窗口按钮 IPC 通道（window:close → close 事件 → 拦截点） |
| F31 | #152 ⏳ | 设置持久化归口（本模块临时内存态，合入后切换） |
| #168（CLI 产物） | F31（语义依赖） | CLI 常驻语义依赖 GUI/CLI 同内核发现协议（kernel.json 双向写入） |
| #169（CLI 恒 HTTP） | F31 + F30 | CLI 经 ensure_kernel 复用 GUI 拉起的常驻内核（§5.4 闭环） |

**编号口径声明**：F25 移除后 F26-F29 为 Agent 化升级规划，F30 为内核冷启动基建（ADR-030 ②），本模块承接 **F31**（ADR-030 ③ GUI 侧落地）；若与 ADR-019 v5+ 冲突以 ADR-019 为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| D1 | 关闭行为设置持久化口径 | **临时内存态**（主进程模块级变量），#152 合入后切换 | 评论区拍板（2026-08-07）：归口 #152 同一设置库，避免两套设置系统；本 issue 只做托盘行为 + 设置项 UI | 自建 config.json 后端化（❌ 重复建设）；localStorage（❌ 两套系统 + 主进程读不到） |
| D2 | 内核复用 = Node 侧等价判定 | kernel.ts 纯函数（读 kernel.json + process.kill(pid,0) 存活 + /health 200），不 import Python ensure_kernel | Electron 主进程是 Node，无法调用 Python 库；三态判定逻辑简单（读文件 + 2 个探测），Node 复刻成本低；互斥/轮询/重试等拉起方逻辑不复制（GUI spawn 仍走 #78） | 主进程 spawn `python -m inkflow` 子进程代查（❌ 每次启动 ~4.4s import 全量栈，违背快速复用初衷）；不做复用（❌ 违背 ADR-030 ③ 需求 5） |
| D3 | GUI spawn 内核后写 kernel.json | INKFLOW_READY 后原子写五字段 | 双向闭环：CLI/MCP 才能发现 GUI 常驻内核（否则双内核，ADR-030 ① 单实例语义破坏） | 只复用不写（❌ CLI 侧 ensure_kernel 读到无记录 → 双 spawn）；写端口文件不写 kernel.json（❌ 端口文件是 F19 serve 契约，非跨客户端发现协议） |
| D4 | 版本校验 YAGNI | GUI 侧不做 major 校验，仅校验 kernel.json version 与 /health 一致 | GUI 与内核同仓库同发布，版本漂移不存在；CLI 侧校验由 F30 负责 | 引入 GUI 版本概念 + major 比较（❌ 多余抽象，打包场景版本恒一致） |
| D5 | window-all-closed 条件退出 | tray 模式下不退出（preventDefault），仅 quit 模式/quitInProgress 退出 | 窗口意外销毁不能杀常驻内核（托盘语义）；托盘「打开」可重建窗口 | 维持 #78 无条件 shutdown（❌ 托盘模式下窗口异常销毁 = 内核被杀，违背 ADR-030 ③） |
| D6 | 托盘 E2E 钩子 | `__trayInfo`/`__trayActions` dev 钩子 + app.evaluate 驱动 | CI 无法操作系统级托盘交互；钩子模式与 #78 `__kernelInfo` 一致 | 驱动真实托盘点击（❌ CI 无此能力）；仅手动冒烟（❌ 验收 5 条无法自动化） |
| D7 | 内核状态菜单刷新 | 复用健康检查 2s 周期，仅状态翻转时重建菜单 | 状态实时 + 避免每 2s 重建抖动 | 菜单静态（❌ 「健康」展示失真）；每 2s 重建（❌ 无谓 GC 压力） |
| D8 | e2e-tray 并入 shell job | ci.yml e2e-frontend-shell run 命令追加 `e2e-tray` 文件参数 | 托盘属壳域契约（ADR-028：壳第一批恒跑 required）；避免新增第 7 个 job 的触发/维护面 | 新 job e2e-frontend-tray（❌ 壳域测试拆两 job 无收益，ADR-028 按页面域拆分不适用主进程功能） |

---

## 13. 验收标准

| # | 验收（issue 映射） | 自动化载体 | 验证 |
|---|-------------------|-----------|------|
| M1 | 点击关闭按钮 → 窗口隐藏、内核进程存活、托盘图标出现 | E2E（e2e-tray） | `win.isVisible()===false` + `__kernelInfo.pid` 存活 + `/health` 200 + `__trayInfo.created===true` |
| M2 | 托盘菜单「打开」→ 窗口恢复；「退出」→ 内核回收 + 应用退出 | E2E | `__trayActions.show()` → visible；`__trayActions.quit()` → pid 不再存活 + 进程退出 |
| M3 | 设置改为「直接退出」→ 关闭按钮 = 完整退出 | E2E + 单元 | settings Select 切 'quit' → close → 内核回收（E2E）；IPC 契约单测（单元） |
| M4 | GUI 已运行再启动 → 聚焦已有窗口（无第二窗口/内核） | E2E | 二次 launch → `__kernelInfo.pid` 不变 + 窗口唯一 + 第二进程退出 |
| M5 | GUI 启动时内核已被 CLI 拉起 → 复用同一内核（pid 不变） | E2E | 先 `ensure_kernel()`（Python）→ GUI 启动 → `__kernelInfo.pid === 预拉起 pid` |
| M6 | 关闭行为设置内存态 + 默认 'tray' | 单元 | `settings:get-close-behavior` 默认 'tray'；set 后生效 |
| M7 | 首次托盘提示（toast + 不再提示勾选） | 单元 + 手动 | `inkflow:tray-hint` 事件发送断言（单元）；手动验证 toast 文案与勾选（手动） |
| M8 | GUI spawn 内核后写 kernel.json（五字段齐全） | 单元 | `writeKernelStateFile` 原子写 + 字段校验；E2E 冒烟后可读 %APPDATA%\InkFlow\kernel.json |

> 覆盖门禁：前端 vitest thresholds（electron 包新代码计入后上调基线）；全仓 CI 全绿（lint-frontend / unit-frontend / integration-frontend / e2e-frontend-shell+全部页面 job）后才 merge。

---

## 14. 待澄清问题（≤3）

- **Q1「不再提示」勾选的存储范围**：A. 主进程会话级内存态（重启后重新提示，与 #152 归口拍板严格一致——所有设置项同口径）；B. renderer localStorage 半持久（重启不提示，等 #152 合入迁后端）。**✅ 已确认（用户拍板：选项 A，2026-08-07）**——正文已按 A 定稿（§2.2 内存态 + §5.2 首次提示流程）。
- **Q2 e2e-tray 进 CI 的方式**：A. 并入 e2e-frontend-shell job（run 命令追加 `e2e-tray`，恒跑 required——壳域契约，ADR-028 第一批语义）；B. 新增独立 job e2e-frontend-tray（第二批按需触发）。**✅ 已确认（用户拍板：选项 A，2026-08-07）**——正文已按 A 定稿（§8 文件结构 ci.yml 行 + §12 D8）。
- **Q3 设置页首次提示开关是否展示**：A. 不展示（toast 内勾选即可，YAGNI；#152 合入后如需持久化再加）；B. GeneralPanel 额外加「首次托盘提示」开关（与关闭行为并列，显式可改）。**✅ 已确认（用户拍板：选项 A，2026-08-07）+ 设置页开关需求登记 #152**（2026-08-07 已在 #152 评论区留痕：作为 #152 设置持久化落地后的增强项）——正文已按 A 定稿（§6.2 不占设置页空间）。

> 说明：F167-SESSION-PROMPT §7 的「待拍板项」（#152 口径）已在 issue 评论区拍板（2026-08-07 归口合并），Q 表不再重复；本表 Q1-Q3 为起草阶段补充识别。
