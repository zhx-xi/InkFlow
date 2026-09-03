# 内核生命周期（kernel.md）

agent 使用：InkFlow 内核 = 本地常驻 HTTP 服务（uvicorn/FastAPI），GUI/CLI 统一经 HTTP 访问（ADR-030）。操作 InkFlow 前先确认内核已运行，并从 kernel.json 拿到 port/token。

## kernel.json 发现协议

- 位置：`%APPDATA%\InkFlow\kernel.json`（Electron GUI 写真实 %APPDATA%；CLI ensure_kernel 写其 APPDATA 环境下的路径）
- 字段：`{port, token, pid, version, started_at}`（X-InkFlow-Token 用于 /health 及 API 鉴权头）
- 读法：`Get-Content $env:APPDATA\InkFlow\kernel.json | ConvertFrom-Json`

## ensure_kernel（CLI 首命令自动触发）

1. 读 kernel.json 状态
2. 健康复用：/health 200 + 版本匹配 → 直接用
3. 失效互斥拉起：CreateMutexW 防双 spawn → 拉起 `inkflow.exe serve`（--port 0 动态）→ 等 stdout `INKFLOW_READY` 行 → 写 kernel.json
4. **版本校验**：不匹配的旧版运行中内核会被新版本 ensure_kernel **杀掉并改写 kernel.json**（stale pid）——终止实例前先确认它不是用户正在使用的进程

## serve 诊断模式（拿 stderr 的可靠方式）

- `serve --port 0`：随机端口；就绪信息走 stdout `INKFLOW_READY {"port":..,"token":..,"pid":..,"version":..}`；**不写 kernel.json**（kernel.json 由 ensure_kernel 客户端路径写）
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

## 健康检查

- `GET /health`（带 `X-InkFlow-Token: <token>`）→ 200 + `{"status":"ok","version":...,"mode":"local"}` = 内核活 + 版本一致性判据
- 从 kernel.json 拿 port/token 后：`Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -Headers @{'X-InkFlow-Token'=$token}`
- `inkflow kernel status`：读 kernel.json + PID 存活检查（无参，输出 `running/pid/port/version`；绝不拉起内核）
