# F19: GUI（内核进程化 + Electron 壳 + React 渲染层）— 功能规格

> **Spec 版本**: 1.1（草案：§2 内核进程化 ✅ 已合入 / §3 Electron 壳 已起草 / §4 渲染层 已起草） | **日期**: 2026-08-04 | **依据**: PRD v2.1, Constitution P1-P6, ADR-003/004/011/019(v2)/020/021/025
> **Spec 变更**: 1.1（2026-08-04）：§3 占位 → 完整起草（#77 合入后条件满足；契约实测 serve.py 已交付 INKFLOW_READY 行 + 端口文件）
> **所属阶段**: 0.3.0 里程碑（Issue #69 拆分 3 子任务：#77 内核进程化 / #78 Electron 壳 / #79 React 渲染层）
> **关联 Issues**: [#69](https://github.com/zhx-xi/InkFlow/issues/69)（父）· [#77](https://github.com/zhx-xi/InkFlow/issues/77)（子任务 A，本章）· [#78](https://github.com/zhx-xi/InkFlow/issues/78)（子任务 B）· [#79](https://github.com/zhx-xi/InkFlow/issues/79)（子任务 C）
> **依赖**: 无（#77 可独立开发验证，不需要 GUI）；#78 依赖本章交付格式（端口文件/token 契约）；#79 依赖 #50 ✅（F23 SSE，PR #83）与 #78
> **参考 ADR**: [ADR-003](../../adr/ADR-003.md)（SQLite WAL 基础）、[ADR-004](../../adr/ADR-004.md)（Pydantic 契约）、[ADR-011](../../adr/ADR-011.md)（异步无阻塞）、[ADR-019](../../adr/ADR-019.md)（版本里程碑 v2）、[ADR-020](../../adr/ADR-020.md)（单机 GUI Electron）、[ADR-021](../../adr/ADR-021.md)（本地内核进程化）、[ADR-025](../../adr/ADR-025.md)（依赖锁定）
> **状态**: §2 内核进程化 ✅ 已实现（PR #85，#77）；§3/§4 待实现 🔲（#78/#79）

---

## 1. 概述

F19 = 桌面 GUI（Electron 壳 + React 渲染层 + 本地内核进程化）。本 spec **一份文件按三章划分**（与子任务 Issue 一一对应，各自独立 PR 验收）：

| 章 | 子任务 | 内容 | 估算 | 依赖 |
|----|--------|------|------|------|
| §2 内核进程化 | #77 | `inkflow serve` 强化：动态端口 + token 鉴权 + WAL + 端口文件交付 | 3-4 人天 | 无 |
| §3 Electron 壳 | #78 | 主进程生命周期管理：拉起/健康检查/崩溃拉起/回收 | 3-4 人天 | #77 交付格式 |
| §4 渲染层 | #79 | React 界面：写作/项目管理/Agent 配置 + SSE 渲染 | 4-6 人天 | #50 + #78 |

**边界声明**：
- F19 **不含打包分发**（PyInstaller exe / 安装包 / 便携 ZIP）——#48 留 0.4.0（用户拍板，ADR-019 v2）
- F19 前端走已拍板双包结构：`frontend/packages/renderer/`（React19+Vite6+shadcn+Zustand+Tailwind4，**永不 import electron**，走 REST+SSE）+ `frontend/packages/electron/`（薄壳，只做内核生命周期）——§3/§4 文件结构据此
- F19 **不新增业务实体、不新增业务 API 端点**：内核进程化只强化既有 serve 通道与本地安全基线；业务面（写作/角色/大纲等）全部复用既有 API

### 1.1 本章（§2 内核进程化）定位

**第八变体「本地服务强化型」**：不新建实体、不新增业务算法，为既有 FastAPI 内核增加**进程化交付契约**——动态端口、随机 token 鉴权、SQLite 多进程并发（WAL + busy_timeout）、健康检查契约。交付物 = 现有 `inkflow serve` 的强化版（ADR-021 交付口径：**不引入新命令、不新增抽象**）。

```text
现状:  inkflow serve --port 8000 → uvicorn.run（固定端口、无鉴权、SQLite 无 WAL）
强化:  inkflow serve [--port 0] [--port-file PATH] → 动态端口 + 随机 token + WAL
       交付: stdout 一行 JSON + 端口文件 {port, token} → GUI 壳（#78）消费
```

**关键事实（现状盘点，2026-08-03 实测）**：
- `cli/commands/serve.py`：仅 host/port/open_browser/reload，**无** token/端口文件/WAL——#77 全量待做
- `GET /health` **已存在**（api/app.py:75，返回 `{status, version, mode}`）——#77 直接复用，不新建
- `core/database.py`：`create_async_engine(config.database_url)` **无任何 WAL/busy_timeout PRAGMA**（全仓搜 0 匹配）——WAL 必须加在**连接工厂统一处**（CLI/agent/GUI 都要并发，不只 serve 路径）
- `api/app.py`：CORS 白名单已硬编码 4 个本地源（localhost/127.0.0.1 × 5173/8765），满足「仅放行本地来源」基线，需**配置化 + 补 Electron file:// (null origin)**
- `core/config.py`：已有 `server_host`/`server_port`（默认 127.0.0.1/8000）；无 token/WAL 相关配置
- `tests/cli/test_cli_serve.py`：mock `uvicorn.run` 断言 host/port——强化后 mock 目标变为 `uvicorn.Server`/交付逻辑，**需重写**

---

## 2. 内核进程化（子任务 A，#77）

### 2.1 交付契约（GUI 壳 ↔ 内核）

ADR-021 决策：内核 = 独立进程，由 GUI 壳管理生命周期；**动态端口经 stdout / 端口文件交付**；启动时生成**随机 token**，请求头校验。

**2.1.1 stdout 交付行**（供 #78 壳行缓冲解析，流式多次到达不依赖整行同步）

```
INKFLOW_READY {"port": 38291, "token": "aB3x...", "pid": 4821, "version": "0.3.0"}
```

- 前缀 `INKFLOW_READY ` + 单行 JSON，仅内核启动完成后输出**一次**
- `port`：实际监听端口（`--port 0` 时由系统分配）；`token`：本次启动生成的随机 token；`pid`：内核进程 PID（壳做健康监控/回收用）；`version`：内核版本号

**2.1.2 端口文件**（可选 `--port-file PATH`，与 stdout 交付并存）

```json
{
  "port": 38291,
  "token": "aB3x...",
  "pid": 4821,
  "version": "0.3.0"
}
```

- 写入时机：内核监听就绪后原子写入（先写临时文件再 `os.replace`，避免壳读到半截 JSON）
- 缺省不写文件（仅 stdout）；GUI 壳显式传 `--port-file` 指定路径
- 文件权限：Windows 本机默认即可；Linux/macOS 建议 0600（含 token）

**2.1.3 token 传递**（本地）

- 请求头：`X-InkFlow-Token: <token>`
- 校验范围：**所有 `/api/*` 请求**（含 SSE 流式端点——F23 端点为 POST/fetch，可带自定义头，不受 EventSource GET 限制）
- 校验范围（Q2 已评审修订）：**所有端点均需 token**，含 `/health`——豁免仅 `/docs` `/redoc` `/openapi.json`（静态文档，无数据面）
- 壳轮询 token 零成本：端口与 token 同在 `INKFLOW_READY` 行，壳解析该行是必经步骤，token 为免费副产品
- 云端远程模式（2.0.0，ADR-024）：换 `Authorization: Bearer <JWT>`，同一 API client 抽象——本章只实现本地 token

### 2.2 CLI 契约（serve 强化）

```
inkflow serve [--host HOST] [--port PORT] [--port-file PATH] [--token TOKEN]
              [--open-browser] [--reload]
```

| 参数 | 类型 | 默认 | 变更 |
|------|------|------|------|
| `--host` / `-H` | str | `127.0.0.1`（config.server_host） | 保留。**安全基线默认仅监听 127.0.0.1**；显式改非本地地址时仍强制 token 校验（token 与 host 无关） |
| `--port` / `-p` | int | `8000`（config.server_port） | 保留。`--port 0` = 系统动态分配（**新语义**，uvicorn 原生支持 port=0，实际端口从交付契约读取） |
| `--port-file` | Path | 无 | **新增**。交付端口文件的路径；缺省仅 stdout 交付 |
| `--token` | str | 随机生成 | **新增**。显式指定 token（调试/测试用）；缺省 `secrets.token_urlsafe(32)` 每次启动随机 |
| `--open-browser` | bool | False | 保留 |
| `--reload` | bool | False | 保留（开发热重载）。**与交付契约互斥**（Q3 评审修订）：reload 每次重启子进程、`--port 0` 端口漂移 → 不输出 INKFLOW_READY、不写端口文件；**token 校验保持启用**（`INKFLOW_SERVER_TOKEN` env 注入，reload 子进程天然继承） |

### 2.3 API 层变更（token 中间件 + CORS 配置化）

**2.3.1 token 中间件**（`api/middleware/token_auth.py` 新增）

```text
请求 → token 中间件
  ├─ 路径 /docs /redoc /openapi.json → 放行（静态文档，无数据面）
  ├─ 路径 /api/* 且带 X-InkFlow-Token 且匹配 → 放行
  ├─ 路径 /health 且带 token 且匹配         → 放行（Q2 评审：/health 不豁免）
  └─ 其余路径 token 缺失/不匹配             → 401 {"detail": "Unauthorized"}
```

- 中间件持有 token：从**环境变量 `INKFLOW_SERVER_TOKEN`** 读取（serve 启动时生成并注入进程环境；测试可设固定值）——避免 config 单例启动时序问题，也天然兼容 reload 子进程继承
- **env 未设置时中间件直通（无 token 模式）**：token 校验是 `serve` 命令的职责（serve 必设 env），不是 app 内置认证——TestClient 直连 app（不经 serve）、云端 JWT 路径（2.0.0）不受影响；既有 1667 测试零破坏
- 401 响应不携带内部细节（防探测）；无重定向、无 WWW-Authenticate 挑战（非 HTTP Basic 语义）
- API 文档加**全局 HTTPBearer security scheme**（Swagger UI Authorize 按钮，开发调 API 用；同时是 ADR-024 云端 JWT 前置）

**2.3.2 CORS 白名单配置化**（api/app.py）

- 白名单从 `config.server_cors_origins`（list[str]）读取，默认：
  - `http://localhost:5173` / `http://127.0.0.1:5173`（Vite dev server）
  - `http://localhost:8765` / `http://127.0.0.1:8765`（既有保留）
  - `null`（Electron 生产模式 file:// 加载，Origin 为 null——#78 消费方）
- 仅放行本地来源（ADR-021）；`allow_credentials=True` 保留

**2.3.3 /health**（api/app.py 既有端点，零语义变更）

```
GET /health → 200 {"status": "ok", "version": "0.3.0", "mode": "local"}
```

### 2.4 SQLite WAL + busy_timeout（core/database.py）

**位置：连接工厂统一处**（`create_async_engine`），不只 serve 路径——CLI/agent/GUI/MCP 全部进程并发访问同一 DB 文件（ADR-021 多客户端并发需求）。

```python
# core/database.py 变更示意（实现以 TDD 为准）
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={config.db_busy_timeout_ms}")
    cursor.close()
```

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `db_busy_timeout_ms` | `5000` | SQLite busy_timeout（毫秒），多进程写并发时等待锁 |
| （journal_mode） | `WAL` | 连接级 PRAGMA；WAL 模式持久化在 DB 文件头，跨连接生效 |

- WAL 生效验证：`PRAGMA journal_mode` 查询返回 `wal`（§2.6 M3）
- **回归风险**：既有 1589 个测试多为内存库（`sqlite+aiosqlite:///:memory:`）——内存库不支持 WAL（journal_mode 返回 memory），PRAGMA 执行不报错但无效果；需确认 PRAGMA 在内存库路径下幂等不抛错（`journal_mode=WAL` 对 memory 库返回 `memory` 而非 `wal`，测试断言须按连接类型分支）

### 2.5 文件结构（#77 CREATE/MODIFY 清单，对照真实树 2026-08-03）

| 操作 | 文件 | 内容 |
|------|------|------|
| MODIFY | `backend/src/inkflow/cli/commands/serve.py` | `--port 0` 语义、`--port-file`、`--token`；uvicorn 启动改为手动装配（`uvicorn.Server` + 启动就绪后读取实际端口 → 输出 INKFLOW_READY / 写端口文件）；`INKFLOW_SERVER_TOKEN` env 注入 |
| NEW | `backend/src/inkflow/api/middleware/token_auth.py` | token 校验中间件（`@app.middleware("http")` 或纯 ASGI 中间件，按测试契约定） |
| MODIFY | `backend/src/inkflow/api/app.py` | 注册 token 中间件；CORS 白名单改读 config |
| MODIFY | `backend/src/inkflow/core/config.py` | 新增 `server_cors_origins: list[str]`、`db_busy_timeout_ms: int = 5000`、`server_token: str = ""`（env `INKFLOW_SERVER_TOKEN` 映射，空=随机生成）；CONFIG_WHITELIST 同步（如适用） |
| MODIFY | `backend/src/inkflow/core/database.py` | connect 事件 PRAGMA（WAL + busy_timeout），**连接工厂统一处** |
| MODIFY | `tests/cli/test_cli_serve.py` | 重写：mock 目标从 `uvicorn.run` 变为交付逻辑/Server 装配；`--port 0`、`--port-file`、`--token` 断言 |
| NEW | `tests/api/test_token_auth.py` | 无 token → 401；错误 token → 401；正确 token → 200；/health 豁免（按 Q2） |
| NEW | `tests/unit/test_database_pragma.py`（或并入既有 database 测试） | 文件库连接 PRAGMA journal_mode=wal + busy_timeout 断言；内存库幂等断言 |
| MODIFY | `.github/workflows/ci.yml` | 新增 tests/api/test_token_auth.py 自动被 unit job 覆盖（tests/api/ 路径核对）；若新增 `tests/cli/` 文件必须显式追加 `integration-cli-backend` job（Issue #59 教训） |

### 2.6 测试策略

| 层次 | 关键场景 |
|------|----------|
| 单元（CLI） | serve 参数解析；`--port 0` 传入 uvicorn 装配；端口文件写入（原子性、JSON 结构）；token 缺省随机/显式指定；INKFLOW_READY stdout 格式 |
| 集成（API） | token 中间件：缺失/错误/正确 token 三分支（**/health 同规则**）；/docs /openapi.json 豁免；HTTPBearer scheme 注册；CORS 白名单（本地源放行、非本地源拒绝） |
| 集成（DB） | 文件库 `PRAGMA journal_mode` = wal；`PRAGMA busy_timeout` = 配置值；内存库不抛错 |
| 回归 | 既有 1589 测试全量（WAL 改动在连接工厂，**必须先全量回归再合入**） |
| 冒烟（curl，无 GUI 可验证） | `serve --port 0 --port-file X` → 读端口文件 → `curl /health` 无 token 401 / 带 token 200 → `curl -X GET /api/v1/projects` 无 token 401 / 带 token 200 → `PRAGMA journal_mode` 返回 wal → kill 进程 |

### 2.7 验收标准（#77，pytest + curl 冒烟闭环）

- **M1** `serve --port 0` 启动：stdout 出现 `INKFLOW_READY` 行，JSON 含 port/token/pid/version；`--port-file` 指定时文件内容一致
- **M2** token 校验：无 token / 错误 token 请求 `/api/v1/*` **与 `/health`** → 401；正确 token → 200；/docs /openapi.json 豁免
- **M3** WAL 生效：文件库 `PRAGMA journal_mode` 返回 `wal`；busy_timeout 为配置值；内存库（测试）不抛错
- **M4** CORS：白名单本地源放行；非白名单 Origin 拒绝（或按配置）
- **M5** 回归：既有全量测试通过（WAL 改动零破坏）
- **M6** 冒烟闭环：curl 全链路（端口文件 → token → 401/200 → WAL → kill）；无 GUI 依赖

---

## 3. Electron 壳（子任务 B，#78）

### 3.1 本章定位

**前端栈「壳层」变体**：Electron 主进程 + preload，交付物 = 内核进程生命周期管理（拉起 / 健康检查 / 崩溃拉起 / 退出回收）+ BrowserWindow 加载 renderer 构建产物（ADR-020：本地 GUI = 云 Web 的本地构建产物）。壳层保持**薄**：零业务逻辑、零业务 API 调用（ADR-020/021 硬约束），一切业务通信由 renderer 直接走 REST + SSE。

```text
Electron 主进程 (main.ts)
  ├── spawn 内核子进程 (inkflow serve --port 0 ...)     ← 生命周期管理（本章核心）
  │     └── 行缓冲解析 stdout → INKFLOW_READY {port, token, pid, version}
  ├── 健康检查轮询 (GET /health，带 X-InkFlow-Token)
  ├── 崩溃检测 → 重新拉起（指数退避 1s→2s→4s→…→30s 封顶）
  └── BrowserWindow (加载 renderer 构建产物)
        └── preload.ts (contextBridge 注入 api: {baseURL, token})
              └── renderer 通过 fetch 访问内核（§4.4 client.ts 消费）
```

**关键事实（现状盘点，2026-08-04 实测）**：
- **#77 已合入**（PR #85）：`backend/src/inkflow/cli/commands/serve.py` 已交付 `INKFLOW_READY {port, token, pid, version}` stdout 行 + `--port-file` 原子写入 + `--port 0` 动态端口 + `INKFLOW_SERVER_TOKEN` env 注入 + reload 互斥（§2 契约全部落地）——**壳直接消费，零后端改动**
- **frontend workspace 已初始化**（feat/f19-gui-ui 前置落盘，2026-08-04）：`frontend/package.json`（inkflow-frontend 0.3.0，scripts 已配 dev/build/test/lint → renderer）+ `pnpm-workspace.yaml`（`packages/*` 通配）+ `pnpm-lock.yaml`（已锁定）+ renderer 包（`packages/renderer/`，Vite 构建产物 `dist/` 已可产出）——**electron 包尚未创建，本章全量 CREATE**
- `packages/` 通配符已覆盖 → 新增 `packages/electron/` **零 workspace 配置改动**
- renderer 构建产物路径：`frontend/packages/renderer/dist/`（vite.config.ts `outDir: 'dist'`，base 需确认为相对路径——`base: './'`，否则 file:// 加载静态资源绝对路径失效，§3.4 决策）
- CI 现状（2026-08-05 更新）：前端已拆 3 个独立并行 job——`frontend-unit`（renderer lint/typecheck + 双包 vitest）/ `frontend-integration`（renderer apiFetch ↔ 真实内核）/ `frontend-e2e`（本章 E2E 冒烟，Playwright `_electron`，独立并行；用户拍板推翻「E2E 不进常规 CI」旧约定，改独立 job 以降总时长，时长超标再拆细）

**边界声明（本章）**：
- **壳层零业务逻辑**：不 import renderer 代码、不代理 API 请求、不承载业务状态；只做进程管理与窗口
- **通信一律 REST + SSE**（ADR-021）：renderer ↔ 内核直连（经 preload 注入的 baseURL/token），壳不中转
- **不引入 Node 侧业务依赖**：无 Express/Koa 等；仅 electron + child_process + fs
- **打包分发不在本章**：#48 0.4.0（ADR-019 v2）；electron-builder.yml 仅留占位（electron-shell-dev 技能已备好模板）
- **token 不落 renderer 全局可写区**：contextBridge 只读注入（§3.3）

### 3.2 生命周期管理（主进程核心）

**3.2.1 内核拉起（spawn）**

```typescript
// packages/electron/src/main.ts 骨架（实现以 TDD 为准，electron-shell-dev 技能）
const kernel = spawn(kernelCommand(), ['serve', '--port', '0'], {
  stdio: ['ignore', 'pipe', 'pipe'],
  windowsHide: true,
});
```

| 项 | 约定 |
|----|------|
| 内核命令定位 | dev = `backend\.venv\Scripts\python.exe -m inkflow serve`（backend venv，记忆：InkFlow 运行/测试必须用 backend\.venv）；打包后 = `resources/kernel/inkflow.exe`（0.4.0）；`app.isPackaged` 分支 + env 覆盖（`INKFLOW_KERNEL_CMD`，测试注入用） |
| 参数 | `serve --port 0`（动态端口，契约 §2.2）；不传 `--port-file`（stdout 通道即可，§2.1 双通道之一） |
| stdio | stdout 管道（行缓冲解析 INKFLOW_READY）；stderr 管道（日志转发，供排障） |
| 超时 | spawn 后 15s 内未收到 INKFLOW_READY → 判启动失败 → 走崩溃拉起流程（§3.2.3） |

**3.2.2 stdout 行缓冲解析**

- `readline.createInterface({ input: kernel.stdout })` + 正则匹配 `^INKFLOW_READY (\{.*\})$`
- JSON.parse → `{port, token, pid, version}`；解析失败 → 忽略该行继续等（不崩溃）
- 拿到 port/token 后即进入健康检查轮询（token 零成本副产品，§2.1.3 Q2 拍板依据）

**3.2.3 健康检查轮询**

```text
成功 INKFLOW_READY → 每 2s GET /health（带 X-InkFlow-Token）
  ├─ 200 → 内核健康（状态栏「内核连接 · 已连接」）
  ├─ 401/5xx/网络错误 ×N 连续 → 判内核异常 → 崩溃拉起流程
  └─ 进程 exit 事件 → 立即判崩溃 → 崩溃拉起流程
```

- 请求超时 3s（`AbortSignal.timeout`），超时计一次失败
- 连续 3 次健康检查失败 或 进程 exit → 进入重拉（§3.2.4）
- 内核就绪前窗口**不关闭**：窗口先创建（显示「正在启动内核…」占位），INKFLOW_READY 后 renderer 注入 baseURL/token 并刷新（或事件通知 renderer 重取——实现以 TDD 为准，§3.4 契约）

**3.2.4 崩溃拉起（指数退避）**

```text
第 1 次失败 → 1s 后重拉
第 2 次失败 → 2s 后重拉
第 3 次失败 → 4s 后重拉
… 每次 ×2，封顶 30s
连续 6 次失败 → 停止自动重拉，弹错误对话框（dialog.showErrorBox）
```

- 重拉 = kill 残留进程（如有）→ 重新 spawn（复用 §3.2.1）
- 连续失败计数在**成功 INKFLOW_READY + 健康 200 后清零**
- 错误对话框文案：内核启动失败，提示检查环境（venv/端口占用），提供「重试 / 退出」按钮

**3.2.5 退出回收（防僵尸）**

```text
app 退出（window-all-closed / before-quit / 崩溃退出）
  └─ stopKernel()
       ├─ 1. 优雅：child.kill()（SIGTERM 语义，Windows 上 TerminateProcess 兜底）
       ├─ 2. 超时 3s 未退出 → 强制杀进程树（taskkill /PID <pid> /T /F，Windows）
       └─ 3. Job Object 兜底（可选，0.4.0 打包评估；electron-shell-dev 技能记 Windows 防僵尸三保险）
```

- **验收硬指标：关闭窗口后 `Get-Process inkflow*` 为空**（#78 验收标准）
- 内核 pid 存于主进程状态（`__kernelInfo.pid`），供测试钩子与回收用

### 3.3 窗口与安全基线（Electron 硬性要求）

```typescript
new BrowserWindow({
  width: 1440, height: 900,
  webPreferences: {
    preload: path.join(__dirname, 'preload.js'),
    contextIsolation: true,   // 硬性
    nodeIntegration: false,   // 硬性
    sandbox: true,
  },
});
```

| 项 | 约定 |
|----|------|
| contextIsolation | `true`（renderer 与 preload 隔离，token 不可被页面 JS 覆盖） |
| nodeIntegration | `false`（renderer 无 Node 能力，REST+SSE 唯一通道） |
| sandbox | `true`（preload 受限但仍可用 contextBridge） |
| token 注入 | preload `contextBridge.exposeInMainWorld('INKFLOW_API', { baseURL, token })` —— 只读冻结对象（`Object.freeze`），**不暴露到全局可写区**（Q1 拍板 B） |
| CSP | renderer `index.html` 加 CSP meta：`default-src 'self'; connect-src http://127.0.0.1:* http://localhost:*`（仅本地内核；file:// 下 'self' 兼容性实现时验证） |
| 外链 | 禁用 `shell.openExternal`（防钓鱼）；窗口内 `will-navigate` 阻止外跳 |

### 3.4 renderer 契约（INKFLOW_API 注入位）

§4.4 client.ts 消费约定（契约**本章定稿**，§4.4 引用）：

```typescript
// preload.ts —— 生产（Electron 内）
contextBridge.exposeInMainWorld('INKFLOW_API', {
  baseURL: `http://127.0.0.1:${port}`,   // 内核实际端口
  token,                                  // INKFLOW_READY 行解析所得
});
// renderer 侧读取（§4.4）：window.INKFLOW_API?.baseURL ?? import.meta.env.VITE_API_BASE
```

- **命名对齐（Q1 拍板 B）**：preload 暴露 `window.INKFLOW_API = {baseURL, token}`——与 §4.4 client.ts 消费语义一致（`window.INKFLOW_API = {baseURL, token}`，#78 preload 注入），两端零漂移
- dev 模式（Vite dev server 5173 调试）：无 preload 注入 → renderer 回退 `import.meta.env.VITE_API_BASE` / `VITE_API_TOKEN`（§4.4 已定，不冲突）
- 生产模式：BrowserWindow 加载 `file://${rendererDist}/index.html`（renderer `dist/` 构建产物；**vite.config.ts 需 `base: './'`** 否则 file:// 下静态资源绝对路径 `/assets/...` 404——实现时必须核）

### 3.5 文件结构（#78 CREATE/MODIFY 清单，对照真实树 2026-08-04）

| 操作 | 文件 | 内容 |
|------|------|------|
| NEW | `frontend/packages/electron/package.json` | name=inkflow-electron（private）；scripts：`build`（tsc 编译 main/preload 到 `out/`）、`dev`（dev 模式启动）、`test`（vitest run）、`test:e2e`（playwright）；devDeps：electron、typescript、vitest、@playwright/test（版本与 lock 对齐，ADR-025） |
| NEW | `frontend/packages/electron/tsconfig.json` | 编译 `src/main.ts` + `src/preload.ts` → `out/`（CommonJS，Electron 主进程模块格式；exclude `src/**/*.test.ts`） |
| NEW | `frontend/packages/electron/vitest.config.ts` | 单元测试配置（node 环境，include `src/**/*.test.ts`） |
| NEW | `frontend/packages/electron/playwright.config.ts` | E2E 冒烟配置（testDir 指向 `../../tests/e2e`） |
| NEW | `frontend/packages/electron/src/kernel.ts` | 纯函数（parseReadyLine / nextBackoffDelayMs / resolveKernelCommand / MAX_CONSECUTIVE_FAILURES=6） |
| NEW | `frontend/packages/electron/src/main.ts` | §3.2 生命周期全套：spawn/行缓冲/健康轮询（in-flight 互斥）/崩溃拉起/退出回收 + BrowserWindow（§3.3）+ 测试钩子 |
| NEW | `frontend/packages/electron/src/preload.ts` | contextBridge 注入 `{baseURL, token}`（§3.4；就绪后仅暴露一次 + exposed 幂等，防 did-finish-load 兜底重发二次 expose 报错） |
| NEW | `frontend/packages/electron/electron-builder.yml` | **占位**（0.4.0 #48 打包用；electron-shell-dev 技能模板：appId/NSIS/portable） |
| NEW | `tests/e2e/electron-smoke.spec.ts` | Playwright `_electron` 冒烟（§3.6/§3.7 M2-M5；AGENTS.md §3 tests/e2e 预留目录启用） |
| MODIFY | `frontend/packages/renderer/vite.config.ts` | `base: './'`（file:// 加载兼容，§3.4 决策） |
| MODIFY | `frontend/packages/renderer/index.html` | 加 CSP meta（§3.3 安全基线：`default-src 'self'; connect-src http://127.0.0.1:* http://localhost:* ws://localhost:5173 ws://127.0.0.1:5173; script-src 'self'; style-src 'self' 'unsafe-inline'`；ws 放行供 Vite HMR，评审 MAJOR-1 拍板 A） |
| MODIFY | `frontend/.gitignore` | 加 `test-results/`、`*.db`、`*.db-shm`、`*.db-wal`（E2E/内核产物） |
| MODIFY | `frontend/pnpm-workspace.yaml` | 加 `allowBuilds: { esbuild: true }` + `onlyBuiltDependencies: [esbuild]`（pnpm 11 构建脚本白名单，评审 MINOR-6；§3.5 原「（不改）」改为 MODIFY） |

> **合入顺序依赖（Q3 拍板 A 定稿）**：`frontend/package.json` + `pnpm-workspace.yaml` + `pnpm-lock.yaml` 由 **feat/f19-gui-ui（#79 前置落盘）** 提供——执行节奏：**先开 #79 前置落盘 PR（纯 workspace 骨架，无业务代码）→ 合入 main → #78 worktree 从 main 建**。若 #79 前置落盘 PR 被阻塞，本章才考虑自带最小子集（评审兜底，非默认路径）。

### 3.6 测试策略

| 层次 | 关键场景 |
|------|----------|
| 单元（vitest，主进程逻辑抽纯函数） | INKFLOW_READY 行解析（正常/畸形 JSON/多行流式）；退避序列计算（1→2→4→…→30 封顶）；连续失败计数清零逻辑；内核命令定位（dev/打包/env 覆盖三分支） |
| 集成（Playwright `_electron` 冒烟，tests/e2e/） | **启动**：`_electron.launch` → 窗口出现（title /InkFlow/）+ 内核进程存在（`__kernelInfo.pid` 定义）+ `/health` 带 token 200；**回收**：`app.close()` → 内核 pid 不再存活（进程探测）；**崩溃拉起**：`process.kill(pid)` 强杀 → 壳自动重拉（≤ 退避上限）→ 健康恢复 200 |
| 手动冒烟（Windows） | 关闭窗口后 `Get-Process inkflow*` 为空；错误 token 请求 `/health` → 401（安全基线生效） |

> 主进程测试钩子约定（electron-app-testing 技能）：`app.isPackaged === false` 时暴露 `globalThis.__kernelInfo = { pid, port, token }`——Playwright `app.evaluate` 断言必需，**写进实现**。
> E2E 已入常规 CI（2026-08-05 用户拍板：`frontend-e2e` 独立并行 job，与 unit/integration 并行；本地 `pnpm --filter inkflow-electron test:e2e` 仍为开发期快捷通道）。

### 3.7 验收标准（#78，Playwright `_electron` 冒烟闭环）

- **M1** 工程就绪：`frontend/packages/electron/` 可 `pnpm --filter inkflow-electron build` 产出 `out/main.js` + `out/preload.js`；workspace 识别（`pnpm -r list` 含 inkflow-electron）
- **M2** 启动闭环：`_electron.launch` → BrowserWindow 出现（title 含 InkFlow）+ 内核进程存在（`__kernelInfo.pid` 有效）+ `GET /health`（带 token）200
- **M3** 崩溃拉起：手动 kill 内核 pid → 壳自动重拉（指数退避上限内）→ 健康检查恢复 200（新 pid）
- **M4** 退出回收：`app.close()` → 内核 pid 不再存活（`Get-Process inkflow*` 为空，无残留）
- **M5** 安全基线：`contextIsolation:true` + `nodeIntegration:false` 生效（webPreferences 断言）；preload 注入 `window.INKFLOW_API` 只含 `{baseURL, token}`；错误 token → 401
- **M6** 崩溃保护：连续失败 6 次 → 停止自动重拉 + 错误对话框出现（不再无限重启；退避序列 1+2+4+8+16+30s 封顶全生效，约 1 分钟自愈窗口，Q2 拍板 B）
- **M7** renderer 集成（依赖 #79 合入）：生产模式 `file://` 加载 renderer `dist/` 全流程可用（CORS null origin 放行，§2.3.2 已含 `null`）；renderer 经注入 baseURL/token 读写内核成功（§4.8 M7 同源验收）

### 3.8 关键架构决策记录（#78）

| 决策 | 方案 | 理由 | 备选（否决） |
|------|------|------|--------------|
| 内核进程生命周期宿主 = Electron 主进程 | main.ts spawn + 轮询 + 回收 | ADR-021 明确「生命周期由壳负责」；主进程是唯一可靠宿主（renderer 可被销毁） | renderer 管（进程退出即失控）；独立 watchdog 进程（过度设计，YAGNI） |
| 端口/token 获取 = stdout 行缓冲为主 | 解析 INKFLOW_READY 行 | 端口与 token 同处一行、零轮询竞态（§2.1.3 Q2 论证）；token 免费副产品 | 仅端口文件（启动竞态：需轮询文件出现）；仅 stdout（崩溃拉起后信息不可重读——故保留端口文件为备选，但本章 stdio 直通已够） |
| 崩溃拉起 = 指数退避 + 封顶停止 | 1s→2s→4s→…→30s，连续 6 次弹错误框 | 防崩溃循环风暴（内核配置错误时会秒退无限重启）；退避给环境恢复时间（约 1 分钟自愈窗口，Q2 拍板 B） | 固定间隔重试（无退避，风暴风险）；无限重试（崩溃循环无出口） |
| 回收 = 优雅 kill → 超时强杀 → Job Object | 三级兜底（§3.2.5） | Windows 下 child.kill 对 Python 进程树可能杀不干净（孙进程）；验收硬指标无残留 | 仅 child.kill（僵尸风险，验收不过）；仅 taskkill（无优雅阶段，内核数据未 flush） |
| token 注入 = contextBridge 只读 | `window.INKFLOW_API = {baseURL, token}`（Object.freeze） | contextIsolation 下页面 JS 不可篡改；renderer 零 electron import（ADR-020） | ipcRenderer 逐请求取（renderer 需 electron API，破坏 ADR-020）；注入全局可写区（安全红线） |
| 测试钩子 = isPackaged 条件暴露 | `__kernelInfo` 仅 dev 暴露 | Playwright `app.evaluate` 断言必需；生产不泄露 | 生产也暴露（安全风险）；无钩子（E2E 无法断言内核状态） |

### 3.9 待澄清问题（≤3）

- **Q1 preload 注入命名**：A. `window.inkflow`（短名，contextBridge 习惯）；B. `window.INKFLOW_API`（spec §4.4 已用此语义命名）；C. 两者别名（冗余）。**✅ 已确认（用户拍板：选项 B，2026-08-04）**——§4.4 client.ts 已写 `window.INKFLOW_API = {baseURL, token}`（#78 preload 注入，契约 §3 待定），保持一致避免实现时两端命名漂移；contextBridge 暴露名与实际读法同名（`exposeInMainWorld('INKFLOW_API', …)`）。正文已按 B 修订（§3.3/§3.4/§3.7/§3.8）。
- **Q2 连续失败次数阈值**：A. 5 次（对应退避序列 1+2+4+8+16+30×N，约 1 分钟）；B. 3 次（更快弹错，约 7s）；C. 不限（仅退避封顶，永不弹错）。**✅ 已确认（用户拍板：选项 A，2026-08-04）**——5 次覆盖「环境瞬时故障」（端口占用短暂、杀毒扫描）后自愈窗口，又不至于无限重启。正文维持 A（§3.2.4/§3.7 M6/§3.8）。**【评审修订 2026-08-05：用户拍板改 B=6 次（评审 MINOR-3）】**——评审发现原 A=5 次使 16s/30s 退避分支成为死代码（弹框在 15s 即触发），与 Q2 注释「约 1 分钟」不符；拍板 B=6 次使退避序列 1+2+4+8+16+30s 封顶全部生效，约 1 分钟自愈窗口兑现。正文已按 B 修订（§3.2.4/§3.7 M6/§3.8/kernel.ts MAX=6）。
- **Q3 workspace 前置落盘合入方式**：A. 等待 feat/f19-gui-ui（#79 前置落盘）先合入 main，再建 #78 worktree 开发（串行，依赖 #79 节奏）；B. #78 自带最小 workspace 三文件（package.json/pnpm-workspace.yaml/pnpm-lock.yaml）先合入，renderer 骨架留 #79（#78 先于 #79 落地，双包结构由 #78 立）；C. 两个 worktree 并行开发、谁先合入谁带 workspace 三文件（有冲突风险）。**✅ 已确认（用户拍板：选项 A，2026-08-04）**——#79 前置落盘分支已存在（feat/f19-gui-ui，1 提交「初始化前端 workspace + renderer 骨架」），先合入它（纯 workspace 骨架 PR）再开 #78 最干净。执行节奏：**先开 #79 前置落盘 PR（纯 workspace 骨架，无业务代码）→ 合入 main → #78 worktree 从 main 建**（§3.5 合入顺序依赖已按 A 定稿）。

## 4. 渲染层（子任务 C，#79）— 占位

> 待 #50 ✅（F23 SSE 已合入 PR #83）+ #78 起草。前置：UI 原型 + 设计 token（已补入 #69 task-list）。
> 内容预告：写作/项目管理/Agent 配置三页；SSE 消费（fetch + ReadableStream + Zustand + rAF 批渲染）；文件结构：`frontend/packages/renderer/`（React19+Vite6+shadcn+Zustand+Tailwind4，永不 import electron）；合入 PR 必须带 frontend-renderer CI job。

---

## 5. 不在范围内

| 项 | 归属/原因 |
|----|----------|
| 打包分发（PyInstaller exe / NSIS / 便携 ZIP） | #48，0.4.0（用户拍板维持 ADR-019 v2） |
| 云端远程模式（base URL + JWT） | 2.0.0，ADR-024（本章只做本地 token，契约预留 header 位） |
| SSE 后端端点 | F23 ✅ 已交付（PR #83）；本章只保证 token 中间件不破坏 SSE 流（校验在流开始前完成） |
| 内核生命周期管理（拉起/崩溃拉起/回收） | #78 Electron 壳（本章只保证内核侧能力：stdout/端口文件交付 + 可被 kill 回收） |
| React 界面与 SSE 前端消费 | #79 渲染层 |
| 业务 API 新增/修改 | 无（F19 不新增业务端点） |

## 6. 依赖关系

| 依赖 | 状态 | 说明 |
|------|------|------|
| F23 SSE（#50） | ✅ PR #83 | token 中间件需放行带 `X-InkFlow-Token` 的 SSE POST 请求（校验在流开始前） |
| F1-F16 业务 API | ✅ | /api/v1/* 全部经 token 中间件；业务层零改动 |
| ADR-021 | ✅ | 本章交付口径 = serve 强化版 |
| #78 Electron 壳 | ✅ 已起草（§3，v1.1） | 依赖 §2.1 交付格式（INKFLOW_READY + 端口文件，PR #85 已合入）；依赖 frontend workspace 前置落盘（feat/f19-gui-ui） |
| #79 渲染层 | ⏳ 下游 | 依赖 #50 + #78 |

**编号口径声明**：旧文档中指向「F19 桌面端」的 0.4.0 编号已按 ADR-019 v2 拆分为 0.3.0 GUI（#77/#78/#79）+ 0.4.0 打包（#48），本章以 ADR-019 v2 为准。

## 7. 关键架构决策记录（#77）

| 决策 | 方案 | 理由 | 备选（否决） |
|------|------|------|--------------|
| 交付契约 = stdout 行 + 端口文件双通道 | INKFLOW_READY JSON 行 + `--port-file` JSON 文件 | 壳可流式解析 stdout 立即获得端口；文件便于崩溃拉起后重读（幂等）；JSON 可扩展（ADR-021「stdout / 端口文件」双交付口径） | 仅端口文件（启动竞态：壳需轮询文件出现）；仅 stdout（壳重启/崩溃拉起后信息丢失） |
| token 校验 = 中间件 + env 注入，**无豁免端点（除静态文档）** | `INKFLOW_SERVER_TOKEN` env + `X-InkFlow-Token` 头，全部端点强制（Q2 评审翻转：/health 不豁免） | 中间件零侵入业务路由；env 注入绕开 config 单例启动时序；reload 子进程可继承；契约统一（壳轮询 token 零成本——端口与 token 同处 INKFLOW_READY 行）；封堵 DNS rebinding 端口探测通道 | config.py 字段（启动时序耦合、CLI 测试需改 config）；每路由 dependency（侵入式、易漏）；/health 豁免（契约例外 + 探测通道，评审否决） |
| WAL 位置 = 连接工厂统一处 | `core/database.py` connect 事件 PRAGMA | 所有进程（CLI/agent/GUI/MCP）一次生效；ADR-021 多客户端并发前提 | 仅 serve 启动时 PRAGMA（其他入口进程无 WAL，违背并发基线） |
| CORS = config 白名单 | `server_cors_origins` 默认本地源 + null | Electron file:// 生产模式 Origin=null；可配置化避免硬编码（现状 4 个硬编码） | 保持硬编码（Electron 生产模式会 CORS 失败） |
| reload 与交付契约互斥、token 保持启用 | reload 不输出 INKFLOW_READY/端口文件；token 校验不降级（Q3 评审修正） | reload 子进程端口漂移 → 交付契约无法消费；token 经 env 继承零成本，开发模式不降级安全基线 | reload 禁用 token 校验（安全基线无谓降级，评审否决）；reload 与 --port-file 互斥报错（开发模式过约束） |

## 8. 待澄清问题（≤3）

- **Q1 端口文件路径默认值**：A. 仅显式 `--port-file`（缺省不写文件，stdout 唯一默认通道）——壳必须传路径，契约最明确；B. 缺省写 `{data_dir}/serve.json`——壳零参数，但 data_dir 权限/并发（多实例）需处理；C. 缺省写系统临时目录 `{tempdir}/inkflow-serve.json`。**✅ 已确认（用户拍板：选项 A，2026-08-03）**——消费方唯一性论证：端口文件唯一消费方是 #78 壳，而壳自身 spawn 内核并传参，显式传路径零额外成本；B/C 的缺省路径引入多实例冲突与轮询竞态，收益为零。正文已按 A 修订（§2.1.2 缺省不写文件、仅 stdout）。
- **Q2 /health 是否豁免 token**：A. 豁免（健康检查无敏感数据，壳轮询/运维 curl 方便）；B. 全部强制（严格基线，壳先解析 INKFLOW_READY 拿 token 再轮询）。**✅ 已确认（用户拍板：选项 B，2026-08-03）**——原建议 A 存在认知偏差：「壳轮询方便」不成立——端口与 token 同在 INKFLOW_READY 行，壳解析该行是必经步骤，token 是免费副产品，轮询带 token 零成本；豁免收益仅剩「运维 curl 探测」（本地单机无真实运维场景），代价却是契约例外 + DNS rebinding 端口探测通道 + 测试双分支。/docs /redoc /openapi.json 为静态文档仍豁免，配全局 HTTPBearer scheme（Swagger UI Authorize 按钮，兼作 ADR-024 云端 JWT 前置）。正文已按 B 修订（§2.1.3/§2.3.1/§2.6/§2.7/§7）。
- **Q3 --reload 与 token 交付**：A. reload 模式下禁用 token 校验 + 不输出 INKFLOW_READY（开发热重载仅本机，语义最简）；B. reload 时 env 注入 token 让子进程继承（token 跨 reload 稳定）；C. `--reload` 与 `--port-file/--token` 互斥报错。**✅ 已确认（用户拍板：选项 A 修正，2026-08-03）**——交付契约与 reload 互斥（不输出 INKFLOW_READY、不写端口文件，reload 子进程端口漂移无法消费）成立，但「禁用 token 校验」是安全基线无谓降级：token 经 env 注入、reload 子进程天然继承，校验保持启用零成本。最终语义：**reload 与交付契约互斥 + token 校验保持启用**（§2.2 表格与 §7 决策表已同步）。
