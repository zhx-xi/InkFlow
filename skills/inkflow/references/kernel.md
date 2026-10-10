# 内核生命周期（kernel.md）

agent 使用：InkFlow 内核 = 本地常驻 HTTP 服务（uvicorn/FastAPI），GUI/CLI 统一经 HTTP 访问（ADR-030）。操作 InkFlow 前先确认内核已运行，并从 kernel.json 拿到 port/token。

## kernel.json 发现协议

- 位置：`%APPDATA%\InkFlow\kernel.json`（Electron GUI 写真实 %APPDATA%；CLI ensure_kernel 写其 APPDATA 环境下的路径）
- 字段：`{port, token, pid, version, started_at}`（X-InkFlow-Token 用于 /health 及 API 鉴权头）
- 读法：`Get-Content $env:APPDATA\InkFlow\kernel.json | ConvertFrom-Json`
- kernel.json 五字段契约**不变**，仍是「默认实例」的发现锚点；本文件另述的注册表/`gui.json` 是**增量可见性层**（#1487/ADR-066、#1537）

## 内核生命周期三件（#1487 / ADR-066，0.17.0）

0.17.0 起「机器级限 1」的语义由**内核自身**落实，不再是客户端行为：

### ① 存活期互斥 —— 内核进程自持（拿不到 → 退出码 3）

- **内核进程启动即获取** `CreateMutexW(_lifetime_mutex_name(kind, state_file))` 并**持有到自身退出**（绝不释放，随进程退出由 OS 回收）。互斥名：`rc` → `InkFlowKernelRc`、`prod` → `InkFlowKernelProd`（机器级、data_dir 不参与）、`dev` → `InkFlowKernelDev-<sha256(data_dir)[:16]>`（同 data_dir 单内核）。
- 获取失败（已有同 kind 内核存活）→ 内核 stdout 打一行 `INKFLOW_KERNEL_CONFLICT {"kind":...,"data_dir":...}` 并**以退出码 3 退出**。
- ⇒ **任何路径**（GUI spawn / CLI / MCP / 手工 `inkflow serve`）拉起的同 kind 内核都撞同一互斥；客户端退出不再释放互斥（旧「客户端持锁」语义已被 ADR-066 推翻）。
- 客户端（`ensure_kernel`）不再持锁：spawn 出的子进程以退出码 3 退出 → 读注册表列出既有同 kind 实例并抛 `KernelStartupError`（消息含 kind/port/pid/data_dir；CLI 映射为 `KERNEL_ERROR` 信封）。

> ⚠️ **过期语义修正**：旧版文档写「失效互斥拉起：**客户端侧** `CreateMutexW` 防双 spawn」——已过期。现为**内核进程自持**（拿不到 → 退出码 3）。把退出码 3 当异常是误判，它是「已有实例，正常退出」。

### ② 可重置空闲回收（推翻 ADR-030 D2=A）

- 内核维护**可重置倒计时**：**每次 HTTP 请求刷新**；空闲超阈值 → 内核自行优雅退出（`uvicorn.Server.should_exit = True`）→ 互斥随进程退出自动释放。
- 阈值：env `INKFLOW_KERNEL_IDLE_TIMEOUT`（秒，浮点）；`0` / `off` / 负数 → **关闭**。
- **未设置 = 关闭**（手工 `inkflow serve` 作长期服务跑时不受影响）。**客户端拉起时注入默认 1800s（30 min）**（`ensure_kernel` 与 GUI `spawnKernel` 在 spawn env 写该键）。
- GUI 常驻期内核不会被回收（GUI 主进程 2s `/health` 轮询即 HTTP 请求）；GUI 崩溃/被强杀 → 内核在阈值内自愈退出（#1477 的 76 个孤儿内核的解药）。

### ③ 机器级实例可见性 —— 内核自登记注册表 + `gui.json`

- **注册表目录按 kind 分域**：`rc`/`prod` → **机器级** `<标准数据目录>/running/`（Windows = `%APPDATA%\InkFlow\running\`，不随 `INKFLOW_DATA_DIR` 变化）；`dev` → `<data_dir>/running/`。
- **写入方 = 内核自身**：内核就绪后原子写 `running/<kind>-<pid>.json`（七字段，不含 token），退出时自删。⇒ GUI spawn 的内核也进注册表（托盘/发现可见）。客户端不再写注册表。
- **`gui.json`（#1537）**：GUI **内置内核**形态（exe 位于 `<GUI>/resources/kernel/`）启动期把自己反推出的 GUI exe 绝对路径原子写入机器级 `<标准数据目录>/gui.json`（`{"exe": "<abs>"}`）——供 CLI 探测**便携版** GUI（便携版在注册表 `Uninstall` 键无痕迹）。CLI zip / venv / 手工 serve 不在该路径 → no-op（测试环境零副作用）。

## ensure_kernel（CLI 首命令自动触发）

1. 读 kernel.json 状态
2. 健康复用：/health 200 + 版本匹配 → 直接用
3. 拉起：拉起动作互斥 + spawn `inkflow.exe serve`（--port 0 动态）→ 等 stdout `INKFLOW_READY` 行 → 写 kernel.json；**存活期互斥由内核侧获取**（见 ①）——子进程以退出码 3 退出 → 读注册表列出既有实例并报 `KERNEL_ERROR`
4. **版本校验**：不匹配的旧版运行中内核会被新版本 ensure_kernel **杀掉并改写 kernel.json**（stale pid）——终止实例前先确认它不是用户正在使用的进程

## serve 诊断模式（拿 stderr 的可靠方式）

- `serve --port 0`：随机端口；就绪信息走 stdout `INKFLOW_READY {"port":..,"token":..,"pid":..,"version":..}`；**不写 kernel.json**（kernel.json 由 ensure_kernel 客户端路径写）
- `serve --debug`：Debug 模式（等价 `INKFLOW_DEBUG=1`，env 优先）→ uvicorn 日志 debug 级别 + 自动打开 `/docs`；逃生门 `INKFLOW_DEBUG_NO_BROWSER=1/true/on`（#949，trim+lowercase 判真）→ debug 态**不**自动弹浏览器打开 `/docs`（默认仍未设即弹；`--open-browser` 显式路径不受影响；e2e / 无头 / 批量验证注入该键消噪）
- 500 错误排查：`serve --port 0 --port-file <f>` 前台 + `-RedirectStandardError` 重定向 → traceback 在 stderr；stdout 只有 INKFLOW_READY + 请求行
- GUI 拉起的内核无 stderr 捕获——排查用 serve 前台，不用 GUI 内核

## 数据目录

`config.py _default_data_dir()` 按打包状态分流：

| 运行形态 | data_dir | 覆盖变量 |
|---|---|---|
| 打包 CLI/GUI（PyInstaller frozen） | `%APPDATA%\InkFlow` | `$env:APPDATA`（内核侧生效；Electron appData 不走 env，是契约行为） |
| **dev venv（开发版）** | **`./data`（相对 cwd）——不读 APPDATA！** | `$env:INKFLOW_DATA_DIR`（pydantic-settings env_prefix=INKFLOW_ 覆盖） |

- dev 模式在别的 cwd 跑 → 数据落 `cwd\data`——需要固定数据位置时必须显式设 INKFLOW_DATA_DIR
- kernel.json 随数据目录走：先确认内核运行形态，再决定读 `%APPDATA%\InkFlow\kernel.json` 还是 `$env:INKFLOW_DATA_DIR\kernel.json`
- ⚠️ 但 rc/prod 的**注册表目录是机器级**（`%APPDATA%\InkFlow\running\`），不随 data_dir 变化

## 健康检查

- `GET /health`（带 `X-InkFlow-Token: <token>`）→ 200 + `{"status":"ok","version":...,"mode":"local"}` = 内核活 + 版本一致性判据
- 从 kernel.json 拿 port/token 后：`Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -Headers @{'X-InkFlow-Token'=$token}`
- `inkflow kernel status`：读 kernel.json + PID 存活检查（无参，输出 `running/pid/port/version`；绝不拉起内核）
