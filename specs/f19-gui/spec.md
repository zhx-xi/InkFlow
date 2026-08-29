# F19: GUI（内核进程化 + Electron 壳 + React 渲染层）— 功能规格
> **端**: cross

> **Spec 版本**: 1.6（§2-§5 ✅ / §6 交互反馈 ✅ 已合入 / §7 导航重构 ✅ 已合入 / §8 模型管理 ✅ 已合入 / §9 Agent 模板 ✅ 已合入） | **日期**: 2026-08-06 | **依据**: PRD v2.1, Constitution P1-P6, ADR-003/004/011/019(v2)/020/021/025
> **Spec 变更**: 1.1（2026-08-04）：§3 占位 → 完整起草（#77 合入后条件满足；契约实测 serve.py 已交付 INKFLOW_READY 行 + 端口文件）
> **Spec 变更**: 1.2（2026-08-05）：追加 §5 UI 打磨（#98，M8 补做）；原 §5-§8 顺延为 §6-§9；§3/§4 状态回写 ✅ 已合入
> **Spec 变更**: 1.3（2026-08-05）：追加 §6 交互反馈（#99，用户拍板：spec 完成后关闭 #99，实现并入 #105）+ §7 导航重构（#105，0.4.0）；原 §6-§9 顺延为 §8-§11
> **Spec 变更**: 1.4（2026-08-05）：追加 §8 模型管理（#106，前后端 Phase1=A+B 方案）+ §9 Agent 模板（#107，引用式）；原 §8-§11 顺延为 §10-§13
> **Spec 变更**: 1.5（2026-08-06）：§8 追加顶栏主题/语言 Select 下拉改造（#106 Issue 追加，Q4 方案 A 拍板）；§6/§7 状态回写 ✅ 已合入（#105 PR #120/#121）；§8 待评审后实现
> **Spec 变更**: 1.6（2026-08-06）：§8 状态回写 ✅ 已合入（#106 PR #122）；§9 状态回写 ✅ 已合入（#107，AgentTemplate 实体 + 引用式装配 + 角色独立温度链 + 风险确认）
> **所属阶段**: 0.3.0 里程碑（Issue #69 拆分 3 子任务：#77 内核进程化 / #78 Electron 壳 / #79 React 渲染层；#98 UI 打磨为 M8 补做）
> **关联 Issues**: [#69](https://github.com/zhx-xi/InkFlow/issues/69)（父）· [#77](https://github.com/zhx-xi/InkFlow/issues/77)（子任务 A，本章）· [#78](https://github.com/zhx-xi/InkFlow/issues/78)（子任务 B）· [#79](https://github.com/zhx-xi/InkFlow/issues/79)（子任务 C）· [#98](https://github.com/zhx-xi/InkFlow/issues/98)（子任务 D，本章）
> **依赖**: 无（#77 可独立开发验证，不需要 GUI）；#78 依赖本章交付格式（端口文件/token 契约）；#79 依赖 #50 ✅（F23 SSE，PR #83）与 #78；#98 依赖 #79 ✅（渲染层已合入，本任务在其上纯前端打磨）
> **参考 ADR**: [ADR-003](../../adr/ADR-003.md)（SQLite WAL 基础）、[ADR-004](../../adr/ADR-004.md)（Pydantic 契约）、[ADR-011](../../adr/ADR-011.md)（异步无阻塞）、[ADR-019](../../adr/ADR-019.md)（版本里程碑 v2）、[ADR-020](../../adr/ADR-020.md)（单机 GUI Electron）、[ADR-021](../../adr/ADR-021.md)（本地内核进程化）、[ADR-025](../../adr/ADR-025.md)（依赖锁定）
> **状态**: §2-§8 ✅ 已合入；§9 ✅ 已合入（#107）

>
> **快速导航**（2026-08-08 #201）：
> [1. 概述](L18) · [2. 内核进程化（子任务 A，#77）](L58) · [3. Electron 壳（子任务 B，#78）](L200) · [4. 渲染层（子任务 C，#79）](L390)
> [5. UI 打磨（子任务 D，#98）](L553) · [6. 交互反馈与产品化补全（#99）](L727) · [7. 导航重构：侧边栏 + 设定库项目上下文 + 设置页框架（子任务 E，#105）](L776) · [8. 模型管理页：多 Provider/Model 注册 + 角色绑定 + embedding（子任务 F，#106）](L902)
> [9. Agent 模板：引用式 + 角色独立温度 + 风险确认（子任务 G，#107）](L1001) · [10. 不在范围内](L1089) · [11. 依赖关系](L1102) · [12. 关键架构决策记录（#77）](L1115)
> [13. 待澄清问题（≤3）](L1125)
---

## 1. 概述

F19 = 桌面 GUI（Electron 壳 + React 渲染层 + 本地内核进程化）。本 spec **一份文件按三章划分**（与子任务 Issue 一一对应，各自独立 PR 验收）：

| 章 | 子任务 | 内容 | 估算 | 依赖 |
|----|--------|------|------|------|
| §2 内核进程化 | #77 | `inkflow serve` 强化：动态端口 + token 鉴权 + WAL + 端口文件交付 | 3-4 人天 | 无 |
| §3 Electron 壳 | #78 | 主进程生命周期管理：拉起/健康检查/崩溃拉起/回收 | 3-4 人天 | #77 交付格式 |
| §4 渲染层 | #79 | React 界面：写作/项目管理/Agent 配置 + SSE 渲染 + 2 工具端点（key 管理/连通测试） | 5-7 人天 | #50 + #78 |
| §5 UI 打磨 | #98 | 控件定制化 + 视觉层级 + 空态设计 + 品牌接入（M8 补做） | 2-3 人天 | #79 |
| §6 交互反馈 | #99 | toast/骨架/空态/ESC/快捷键提示/主题预览 + 评审遗留清理（**设计基准，实现并入 #105**） | — | #98 |
| §7 导航重构 | #105 | 侧边栏 + 设定库项目上下文 + 设置页框架 + 交互反馈实现 | 2-3 人天 | #99（spec） |
| §8 模型管理 | #106 | ProviderConfig 注册表实体 + 模型管理页 + key 回退（用户拍板完整方案） | 5-7 人天 | #105；**角色绑定区依赖 #107**（C3） |
| §9 Agent 模板 | #107 | AgentTemplate 实体（引用式）+ 角色独立温度 + 风险确认 | 3-5 人天 | #105 |

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
- CI 现状：ci.yml **无前端 job**（frontend-ci 技能约定 #79 交付时加 renderer job）；本章 E2E（Playwright `_electron`）按 electron-app-testing 技能**不进常规 CI**（Electron 启动重、拖慢 PR 门禁），本地/手动跑，0.4.0 再决定自动化节奏

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
连续 5 次失败 → 停止自动重拉，弹错误对话框（dialog.showErrorBox）
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
| NEW | `frontend/packages/electron/package.json` | name=inkflow-electron（private）；scripts：`build`（tsc 编译 main/preload 到 `out/`）、`dev`（dev 模式启动）、`test:e2e`（playwright）；devDeps：electron、typescript、@playwright/test（版本与 lock 对齐，ADR-025） |
| NEW | `frontend/packages/electron/tsconfig.json` | 编译 `src/main.ts` + `src/preload.ts` → `out/`（CommonJS，Electron 主进程模块格式） |
| NEW | `frontend/packages/electron/src/main.ts` | §3.2 生命周期全套：spawn/行缓冲/健康轮询/崩溃拉起/退出回收 + BrowserWindow（§3.3）+ 测试钩子 |
| NEW | `frontend/packages/electron/src/preload.ts` | contextBridge 注入 `{baseURL, token}`（§3.4） |
| NEW | `frontend/packages/electron/electron-builder.yml` | **占位**（0.4.0 #48 打包用；electron-shell-dev 技能模板：appId/NSIS/portable） |
| NEW | `tests/e2e/electron-smoke.spec.ts` | Playwright `_electron` 冒烟（§3.6；AGENTS.md §3 tests/e2e 预留目录启用） |
| MODIFY | `frontend/packages/renderer/vite.config.ts` | `base: './'`（file:// 加载兼容，§3.4 决策；**本行与 #79 骨架冲突面最小**，若 #79 已合入则在其上改） |
| MODIFY | `frontend/README.md` | 补 electron 包说明（可选，0.4.0 前薄文档） |
| （不改） | `pnpm-workspace.yaml` | `packages/*` 通配已覆盖 electron 包，零改动 |

> **合入顺序依赖（Q3 拍板 A 定稿）**：`frontend/package.json` + `pnpm-workspace.yaml` + `pnpm-lock.yaml` 由 **feat/f19-gui-ui（#79 前置落盘）** 提供——执行节奏：**先开 #79 前置落盘 PR（纯 workspace 骨架，无业务代码）→ 合入 main → #78 worktree 从 main 建**。若 #79 前置落盘 PR 被阻塞，本章才考虑自带最小子集（评审兜底，非默认路径）。

### 3.6 测试策略

| 层次 | 关键场景 |
|------|----------|
| 单元（vitest，主进程逻辑抽纯函数） | INKFLOW_READY 行解析（正常/畸形 JSON/多行流式）；退避序列计算（1→2→4→…→30 封顶）；连续失败计数清零逻辑；内核命令定位（dev/打包/env 覆盖三分支） |
| 集成（Playwright `_electron` 冒烟，tests/e2e/） | **启动**：`_electron.launch` → 窗口出现（title /InkFlow/）+ 内核进程存在（`__kernelInfo.pid` 定义）+ `/health` 带 token 200；**回收**：`app.close()` → 内核 pid 不再存活（进程探测）；**崩溃拉起**：`process.kill(pid)` 强杀 → 壳自动重拉（≤ 退避上限）→ 健康恢复 200 |
| 手动冒烟（Windows） | 关闭窗口后 `Get-Process inkflow*` 为空；错误 token 请求 `/health` → 401（安全基线生效） |

> 主进程测试钩子约定（electron-app-testing 技能）：`app.isPackaged === false` 时暴露 `globalThis.__kernelInfo = { pid, port, token }`——Playwright `app.evaluate` 断言必需，**写进实现**。
> E2E 不进常规 CI（frontend-ci 技能）；本地 `pnpm --filter electron test:e2e` 跑通为合入门禁。

### 3.7 验收标准（#78，Playwright `_electron` 冒烟闭环）

- **M1** 工程就绪：`frontend/packages/electron/` 可 `pnpm --filter electron build` 产出 `out/main.js` + `out/preload.js`；workspace 识别（`pnpm -r list` 含 inkflow-electron）
- **M2** 启动闭环：`_electron.launch` → BrowserWindow 出现（title 含 InkFlow）+ 内核进程存在（`__kernelInfo.pid` 有效）+ `GET /health`（带 token）200
- **M3** 崩溃拉起：手动 kill 内核 pid → 壳自动重拉（指数退避上限内）→ 健康检查恢复 200（新 pid）
- **M4** 退出回收：`app.close()` → 内核 pid 不再存活（`Get-Process inkflow*` 为空，无残留）
- **M5** 安全基线：`contextIsolation:true` + `nodeIntegration:false` 生效（webPreferences 断言）；preload 注入 `window.INKFLOW_API` 只含 `{baseURL, token}`；错误 token → 401
- **M6** 崩溃保护：连续失败 5 次 → 停止自动重拉 + 错误对话框出现（不再无限重启）
- **M7** renderer 集成（依赖 #79 合入）：生产模式 `file://` 加载 renderer `dist/` 全流程可用（CORS null origin 放行，§2.3.2 已含 `null`）；renderer 经注入 baseURL/token 读写内核成功（§4.8 M7 同源验收）

### 3.8 关键架构决策记录（#78）

| 决策 | 方案 | 理由 | 备选（否决） |
|------|------|------|--------------|
| 内核进程生命周期宿主 = Electron 主进程 | main.ts spawn + 轮询 + 回收 | ADR-021 明确「生命周期由壳负责」；主进程是唯一可靠宿主（renderer 可被销毁） | renderer 管（进程退出即失控）；独立 watchdog 进程（过度设计，YAGNI） |
| 端口/token 获取 = stdout 行缓冲为主 | 解析 INKFLOW_READY 行 | 端口与 token 同处一行、零轮询竞态（§2.1.3 Q2 论证）；token 免费副产品 | 仅端口文件（启动竞态：需轮询文件出现）；仅 stdout（崩溃拉起后信息不可重读——故保留端口文件为备选，但本章 stdio 直通已够） |
| 崩溃拉起 = 指数退避 + 封顶停止 | 1s→2s→4s→…→30s，连续 5 次弹错误框 | 防崩溃循环风暴（内核配置错误时会秒退无限重启）；退避给环境恢复时间 | 固定间隔重试（无退避，风暴风险）；无限重试（崩溃循环无出口） |
| 回收 = 优雅 kill → 超时强杀 → Job Object | 三级兜底（§3.2.5） | Windows 下 child.kill 对 Python 进程树可能杀不干净（孙进程）；验收硬指标无残留 | 仅 child.kill（僵尸风险，验收不过）；仅 taskkill（无优雅阶段，内核数据未 flush） |
| token 注入 = contextBridge 只读 | `window.INKFLOW_API = {baseURL, token}`（Object.freeze） | contextIsolation 下页面 JS 不可篡改；renderer 零 electron import（ADR-020） | ipcRenderer 逐请求取（renderer 需 electron API，破坏 ADR-020）；注入全局可写区（安全红线） |
| 测试钩子 = isPackaged 条件暴露 | `__kernelInfo` 仅 dev 暴露 | Playwright `app.evaluate` 断言必需；生产不泄露 | 生产也暴露（安全风险）；无钩子（E2E 无法断言内核状态） |

### 3.9 待澄清问题（≤3）

- **Q1 preload 注入命名**：A. `window.inkflow`（短名，contextBridge 习惯）；B. `window.INKFLOW_API`（spec §4.4 已用此语义命名）；C. 两者别名（冗余）。**✅ 已确认（用户拍板：选项 B，2026-08-04）**——§4.4 client.ts 已写 `window.INKFLOW_API = {baseURL, token}`（#78 preload 注入，契约 §3 待定），保持一致避免实现时两端命名漂移；contextBridge 暴露名与实际读法同名（`exposeInMainWorld('INKFLOW_API', …)`）。正文已按 B 修订（§3.3/§3.4/§3.7/§3.8）。
- **Q2 连续失败次数阈值**：A. 5 次（对应退避序列 1+2+4+8+16+30×N，约 1 分钟）；B. 3 次（更快弹错，约 7s）；C. 不限（仅退避封顶，永不弹错）。**✅ 已确认（用户拍板：选项 A，2026-08-04）**——5 次覆盖「环境瞬时故障」（端口占用短暂、杀毒扫描）后自愈窗口，又不至于无限重启。正文维持 A（§3.2.4/§3.7 M6/§3.8）。
- **Q3 workspace 前置落盘合入方式**：A. 等待 feat/f19-gui-ui（#79 前置落盘）先合入 main，再建 #78 worktree 开发（串行，依赖 #79 节奏）；B. #78 自带最小 workspace 三文件（package.json/pnpm-workspace.yaml/pnpm-lock.yaml）先合入，renderer 骨架留 #79（#78 先于 #79 落地，双包结构由 #78 立）；C. 两个 worktree 并行开发、谁先合入谁带 workspace 三文件（有冲突风险）。**✅ 已确认（用户拍板：选项 A，2026-08-04）**——#79 前置落盘分支已存在（feat/f19-gui-ui，1 提交「初始化前端 workspace + renderer 骨架」），先合入它（纯 workspace 骨架 PR）再开 #78 最干净。执行节奏：**先开 #79 前置落盘 PR（纯 workspace 骨架，无业务代码）→ 合入 main → #78 worktree 从 main 建**（§3.5 合入顺序依赖已按 A 定稿）。

## 4. 渲染层（子任务 C，#79）

### 4.1 本章定位

**前端渲染层**（F19 第三子任务）：React 19 + Vite 6 + shadcn/ui + Zustand 5 + Tailwind 4 的桌面 GUI 界面（ADR-020 一套两用：本地 GUI = 云 Web 的构建产物）。交付 = `frontend/packages/renderer/` 三页（写作/项目管理/Agent 配置）+ SSE 流式渲染（消费 #50 F23）+ 三主题设计系统 + i18n。

> **变体编号声明**：AGENTS.md 模块类型谱系（F9-F23）仅覆盖后端模块变体；渲染层为**前端栈首个变体**，不沿用「第 N 变体」编号（参照 §1.1 先例，编号依据 = AGENTS.md 谱系，f19 §4 为前端类型）。

**关键事实（现状盘点，2026-08-03 实测）**：
- `frontend/` **仅有 README.md**——pnpm workspace 双包结构（renderer + electron）未初始化，本子任务全量 CREATE
- `#50 F23 SSE` ✅ 已合入（PR #83）：`POST /api/v1/writing/stream`（mode 判别 generate/continue/revise）+ 帧协议（`data: {delta, done}` JSON 行，spec f23 §6）；**客户端必须 fetch + ReadableStream**（EventSource 不支持 POST/自定义头——ADR-021 token 要求）
- `#77 内核进程化`（本 spec §2，同文件同 PR 前序）：token 中间件 `X-InkFlow-Token`（§2.1.3/§2.3.1）、CORS 白名单已含 `null`（Electron file:// 生产模式）——renderer 消费契约 = baseURL + token 头
- API 业务面 94 端点全量就绪（projects/chapters/characters/world_settings/outlines/timeline/foreshadowings/extractions/style/audit/context/agent/writing）——渲染层零后端新增
- `ProjectConfig`（domain/models/project.py）已含 `agent_architect/agent_writer/agent_auditor/agent_reviser/temperature/writing_style`——**Agent 配置页数据落点 = `PATCH /api/v1/projects/{id}` 更新 config**，无独立配置端点
- `Genre` 枚举 11 种（玄幻/科幻/言情/仙侠/武侠/都市/历史/游戏/悬疑/奇幻/其他）；`ProjectCreate{name 必填 1-100, genre 默认其他, language 默认 zh-CN, target_words 默认 0 不限, config}`——新建项目对话框字段对齐
- `POST /api/v1/agent/pipelines/validate`（PipelineConfig）——仅管线配置校验，**非** LLM 连接测试（「测试连接」按钮语义见待澄清 Q3）

**边界声明（本章）**：
- **不 import electron 任何东西**（ADR-020）：API 走 fetch REST + SSE；浏览器调试（Vite dev）与 Electron 内加载同一份代码
- **不新增后端端点/实体**（F19 总声明 §1）：本章只消费既有 API——**例外（Q3 拍板）**：新增 2 个基础设施工具端点 `settings/llm-keys` + `settings/llm/test`（key 加密存储与 LLM 连通测试，不落业务库/不建实体，与 /health 同类，§4.9 决策行）
- **不做富文本/Markdown 渲染**（0.3.0）：编辑器 = **段落化纯文本**（Q1 拍板，§4.10）；Markdown 渲染/导出归 0.6.0 F21 联动
- **不做云端远程模式 UI**：base URL + JWT 属 2.0.0（ADR-024）；client 抽象预留 baseURL 注入位（§4.4）
- **SSE 无断点续传**（F23 契约）：断开/停止后重触发 = 从头重拉；不做自动重连
- **不做打包分发**：#48 0.4.0

### 4.2 页面规格（三页 + 路由）

**路由**：`react-router` **HashRouter**（file:// 与 Electron 生产加载兼容；BrowserRouter 在 file:// 下刷新 404）——`/writing`（写作）/ `/projects`（项目）/ `/agents`（Agent 配置）；默认 `/projects`（空态引导新建）。

**4.2.1 写作页**（全高 flex 三栏 + 状态栏）：

```text
┌ 工具栏（hover 弱化唤起: 撤销/重做/加粗/链接 · 修订/续写/生成） ┐
├ 项目树 208px ┬ 编辑器（弹性）                        ┬ 上下文 240px ┤
│ 项目名+印章   │ 章节标题/元信息                        │ 角色/世界观  │
│ 卷1          │ 正文（16px/行高1.85/首行缩进2em）       │ 大纲/伏笔   │
│  ·第1章 2,347│ ── SSE 流式区（delta 追加 + 状态）──    │ （可折叠）   │
│  ·第2章      │                                        │ 折叠→26px 条 │
├─────────────┴────────────────────────────────────────┴─────────────┤
└ 状态栏: 内核连接 · 模型 · 字数 · 自动保存 ┘
```

- 左：项目树（卷/章 + 各章字数；当前章高亮 accent-weak）；**项目印章**（所有主题常驻，颜色跟随 accent，文字取书名关键字——规则见 `design/gui-design-tokens-2026-08-03.md` 已知项 #3）；底部「新建章节」
- 中：工具栏默认 opacity 0.35、hover 编辑器区域全显（Q2 拍板 C：**快捷键 + hover 双通道**——`Ctrl+Z` 撤销 / `Ctrl+Y` 重做 / `Ctrl+S` 保存 / `Ctrl+Enter` 续写 / `Ctrl+Shift+Enter` 生成；纯文本无格式按钮）；正文区下方 SSE 流式区（生成中 live 标记 + 停止按钮 + 完成摘要行）
- 右：上下文面板 4 卡片（角色 tags/世界观/大纲/伏笔）；折叠按钮 → 26px 展开条恢复（原型评审已修复的交互闭环）
- 状态栏：内核地址/模型（done 帧回填）/实时字数/自动保存时间

**4.2.2 项目页**（滚动容器 + 卡片网格）：

- 卡片：书名（衬线标题）+ 题材/目标字数/章节进度（`第 n 章 / m 章`）+ 更新时间（相对时间）+ 进度条（章节数比）；**写作中标记**（accent 边框 + 角标）
- 双入口：右上「新建项目」主按钮 + 网格末位虚线卡片（保留——网格视觉收尾，Notion 同款模式）
- 新建对话框：书名（必填）/ 题材（Genre 11 枚举）/ 语言（zh-CN 等）/ 目标字数（默认 800000）；「创建」→ `POST /api/v1/projects` → 201 后跳转写作页

**4.2.3 Agent 配置页**（两卡片 + 外观卡片）：

- **模型接入**：服务商/模型/API Key/温度滑杆（0-2.0，对齐 ProjectConfig.temperature）/默认字数；**API Key 落点 = `POST /api/v1/settings/llm-keys`**（包装 APIKeyManager 加密存储，Q3 拍板新增工具端点）；**「测试连接」= `POST /api/v1/settings/llm/test`**（LLMClient 最小探测）；**保存流程（Q3 拍板）：测试通过 → 保存（主路径），同时保留直接保存**（用户自信场景）；保存动作本身 = `PATCH /api/v1/projects/{id}`（config 字段）
- **写作 Agent 链**：Architect/Writer/Auditor/Reviser 四行（角色首字方块 + 名称 + 描述 + 标签 + 开关）——开关映射 `config.agent_*`（`null` = 默认模型，开关关闭 = 从管线移除，语义见 F4 agent 管线）；温度/写作风格同卡片
- **外观**（评审控制栏产品化迁移）：主题（素笺/夜航/墨韵）、背景变体（随主题过滤）、语言（中文/EN）——持久化 localStorage（§4.3）

### 4.3 设计 token 与主题系统

**完整 token 表与机制见 `design/gui-design-tokens-2026-08-03.md`**（评审通过，2026-08-03），本章落点：

- **三主题**：素笺 paper（默认，墨蓝 #3B5B7C）/ 夜航 night（深色，暖金 #C9A24B，**跟随系统深色偏好**）/ 墨韵 ink（东方，朱砂 #A6402E 点缀，手动选择）+ 各 1 背景变体（羊皮纸/墨蓝黑/深褐纸）
- **实现**：CSS 变量 + `data-theme`/`data-bg` 属性（html 与 body 同步持有——原型踩坑教训）；Tailwind 4 CSS-first `@theme` 引用变量；shadcn CSS variables 映射同组 token
- **持久化**：localStorage `inkflow.ui` = `{theme, bg, lang}`；默认策略：首次素笺，用户未手动选择且系统 `prefers-color-scheme: dark` 时自动夜航；手动选择后以 localStorage 为准
- **i18n**：轻量自研（`useI18n` hook + `zh.ts`/`en.ts` 字典；文案 <100 key 不引入 i18next——YAGNI）；数字/时间单位随语言格式化（原型已验证数据文案 i18n）
- **品牌**：`assets/inkflow-{icon,icon-dark,logo,logo-dark}.svg`（墨滴 + 流线，浅/深双版本）——renderer 静态资源；深色主题自动切 `-dark` 版
- **字体跨平台降级**（已知项）：楷体（墨韵）Linux 无 → 降级衬线栈；内置 Noto 子集 0.4.0 打包时评估

### 4.4 API client（REST + SSE 封装）

**client.ts**（`src/api/client.ts`）：

- baseURL + token 注入：`window.INKFLOW_API = {baseURL, token}`（#78 preload 注入，契约 §3 待定）；Vite dev 模式回退 `import.meta.env.VITE_API_BASE` / `VITE_API_TOKEN`（开发连本地 serve）
- fetch 封装：自动带 `X-InkFlow-Token`；**401 → 统一「内核未就绪」提示**（壳拉起失败/内核退出，ADR-021）；404/422/500 → 统一错误模型（detail 展示）
- 端点面（0.3.0 渲染层消费面）：projects CRUD · chapters/volumes · outlines（列表）· writing stream · **settings/llm-keys + settings/llm/test（Q3 拍板新增工具端点）**· context 摘要（可选展示）；其余 94 端点按页面演进增量接入

**sse.ts**（`src/api/sse.ts`，消费 F23 契约）：

```typescript
// 调用: POST /api/v1/writing/stream
// body: {mode:'generate', project_id, chapter_id, outline, min_words}
//     | {mode:'continue', project_id, chapter_id, existing_content, target_words}
//     | {mode:'revise', project_id, chapter_id, content, feedback}
// 传输: fetch + ReadableStream + TextDecoder + 行缓冲（\n\n 分帧）+ JSON.parse
// 帧:   {delta, done:false} × N → {done:true, format_valid?, word_count?, model?, token_usage?, warnings?}
//       流中错误: {done:true, error}（F23 §7 E3）
// 停止: AbortController.abort() → 服务端 is_disconnected 终止生成器（F23 §5.3）
```

### 4.5 SSE 流式渲染（useStream hook）

**状态机**：`idle → generating → done | error | stopped`；`format_valid=false` 时展示 warnings + 手动「重试」（**不自动重试**，F23 §5.4 拍板）。

- **rAF 批渲染**：delta 帧进队列 → `requestAnimationFrame` 回调一次性追加 DOM（避免每 token 重排/React 重渲染；批量小 chunk 合帧）；生成中实时字数 = 客户端累积估算（count_words 近似），done 帧回填精确值
- **store 边界**：流式生命周期在组件/`useStream` hook 层持有（AbortController/reader），**Zustand store 不持有非序列化对象**（frontend-testing 约定）；流完成一次性 `chapterStore.setContent()` 提交
- **done 帧摘要**：`{word_count} 字 · {model} · 格式校验 {通过/未通过} + warnings 逐条`；error 帧：错误展示 + 保留已生成前文
- **停止**：按钮 → `abort()`；生成中工具栏禁用「续写/生成」（防并发流）

### 4.6 文件结构（#79 CREATE 清单，对照真实树 2026-08-03）

| 操作 | 文件 | 内容 |
|------|------|------|
| NEW | `frontend/package.json` + `pnpm-workspace.yaml` + `pnpm-lock.yaml` | workspace 根（packages/renderer + packages/electron 声明；ADR-025 锁定，lock 必须提交） |
| NEW | `frontend/packages/renderer/`（全量） | `package.json`（React19/Vite6/shadcn/Zustand5/Tailwind4 + vitest）· `vite.config.ts` · `vitest.config.ts`（jsdom + setup）· `tsconfig.json` · `index.html` |
| NEW | `.../src/main.tsx` + `App.tsx` | 入口 + HashRouter 布局（顶栏/路由出口/状态栏） |
| NEW | `.../src/api/client.ts` + `sse.ts` | §4.4（baseURL/token 注入 + 帧解析/批渲染） |
| NEW | `.../src/stores/project.ts` `chapter.ts` `agent.ts` `theme.ts` | Zustand stores（项目列表/当前项目、卷章树/正文、ProjectConfig 表单、主题/背景/语言持久化） |
| NEW | `.../src/pages/writing.tsx` `projects.tsx` `agents.tsx` | 三页（§4.2） |
| NEW | `.../src/components/` | 布局骨架/项目树/编辑器/SSE 流式区/上下文面板/项目卡片/新建对话框/Agent 行/开关/外观卡片（shadcn 为基础覆盖 token） |
| NEW | `.../src/theme/tokens.css` + `index.ts` | 三主题变量（token 文档 §3 全量）+ 切换/持久化 |
| NEW | `.../src/i18n/zh.ts` `en.ts` `useI18n.ts` | 字典 + hook |
| NEW | `.../src/lib/cn.ts` | shadcn 工具 |
| NEW | `.../src/assets/` | 品牌 logo（inkflow-*.svg 复制） |
| MODIFY | `backend/src/inkflow/api/routers/settings.py`（NEW）+ `api/app.py`（注册） | **Q3 拍板新增 2 工具端点**：`POST /settings/llm-keys`（包装 `APIKeyManager.store`，复用 `config.secret_key/data_dir`）+ `POST /settings/llm/test`（LLMClient 最小探测请求，`provider/model/api_key` → 连通/失败 + 错误消息）；基础设施端点，不落业务库 |
| MODIFY | `.github/workflows/ci.yml` | **新增 `frontend-renderer` job**：`pnpm install --frozen-lockfile` → `pnpm --filter renderer lint` → `tsc --noEmit` → `vitest run` → `pnpm --filter renderer build` |

### 4.7 测试策略（TDD 硬纪律延续，frontend-testing 技能）

| 层次 | 关键场景 |
|------|----------|
| Store（Zustand） | project/chapter/agent/theme 各 action + 持久化读写（`act()` 包裹）；主题默认策略（首次素笺/系统深色跟随/手动覆盖） |
| 组件（RTL + jsdom） | 项目页列表/新建对话框校验；写作页三栏渲染/上下文折叠展开闭环/印章常驻；Agent 配置开关 ↔ config 映射 + **测试连接流程（mock /settings/llm/test：成功→保存高亮、失败→原因展示、直接保存始终可用）**；**SSE 组件：mock fetch ReadableStream 或 mock API 模块，手动逐帧喂 `{delta}` 断言逐段渲染 + done 帧摘要 + error 帧 + 停止**（frontend-testing 模式：手动触发替代 fake timers） |
| 集成（后端 API） | settings/llm-keys 加密落盘回读（APIKeyManager）；settings/llm/test 成功/失败分支（Fake LLMClient 注入） |
| 集成（真实内核） | M4 冒烟：Vite dev + 本地 `inkflow serve --port 0`（带 token）全链路 |
| 视觉走查 | vision-auxiliary + ui-design-taste checklist（三主题截图对比，深色模式对比度） |

> 前端测试不测样式（Tailwind 类名），断言行为；jsdom 无 EventSource——本项目 SSE 走 fetch ReadableStream，mock 点 = fetch 流。

### 4.8 验收标准（#79，Vite dev + 真实内核闭环）

- **M1** 工程就绪：pnpm workspace 双包 + `pnpm --filter renderer build` 出产物 + `frontend-renderer` CI job 全绿
- **M2** 项目页联通：真实内核（serve + token）下列表/新建/打开项目（REST 往返）
- **M3** 写作页静态与交互：三栏布局 + 项目树 + 编辑器 + 上下文折叠/展开条 + 印章常驻（三主题）
- **M4** SSE 全链路：`POST /stream` 三 mode 逐 token 渲染（首 token ≤ 2s 内开始）+ done 帧摘要 + 停止/中断 + format_valid=false 提示重试
- **M5** Agent 配置：API Key 存储（`POST /settings/llm-keys` 加密落盘回读）+ **测试连接（`POST /settings/llm/test`：key 有效/网络/模型可达；失败展示原因）**+ 保存（`PATCH /projects/{id}` config 回读一致；**测试通过→保存主路径 + 直接保存并存**）；Agent 链开关映射四角色字段
- **M6** 主题/语言：三主题 + 背景变体切换 + localStorage 持久化 + 系统深色跟随 + 中英切换（UI 文案与数据文案）
- **M7** 接入 Electron 壳（#78 合入后）：生产构建经 file:// 加载全流程可用（CORS null origin）
- **M8** 回归与走查：前端测试全绿 + vision-auxiliary 三主题视觉走查（无模板感/对比度 AA）

### 4.9 关键架构决策记录（#79）

| 决策 | 方案 | 理由 | 备选（否决） |
|------|------|------|--------------|
| 路由 = HashRouter | react-router HashRouter，三路由 | file://（Electron 生产）与 Vite dev 兼容，刷新不 404；桌面应用无 SEO 需求 | BrowserRouter（file:// 下刷新 404，否决） |
| SSE 渲染 = rAF 批渲染 | delta 队列 + rAF 合帧追加 | 长文逐 token 每帧 setState 触发全树重渲染（千字级卡顿）；合帧 = 视觉连续 + 性能安全 | 每 token 直接 setState（实现简单但重渲染风暴）；双缓冲（复杂度不值） |
| 流式生命周期不入 store | useStream hook 持有 AbortController/reader，完成一次性提交 | store 可序列化（frontend-testing 约定）；测试可注入 mock 流 | store 持有流对象（测试困难、非序列化状态） |
| i18n = 轻量自研 | useI18n + 字典 + data-i18n 模式（原型验证） | 文案 <100 key；零依赖；与原型评审一致；学习价值 | i18next（0.3.0 场景过重，YAGNI） |
| 主题 = CSS 变量 + data-theme | 三主题 token 组 + 属性切换 + localStorage | 运行时切换零重载；Tailwind4 @theme 原生支持；背景变体随主题过滤 | 三套静态 CSS 文件（切换闪烁、无法持久化变体组合） |
| 印章常驻跟随 accent | 项目印章所有主题显示，颜色取 --accent | 原型评审修正（时有时无造成困惑）；单一强调色原则 | 仅墨韵显示（原设计，评审否决） |
| API 注入 = window.INKFLOW_API | #78 preload 注入 {baseURL, token}；dev 回退 env | renderer 零 electron import（ADR-020 硬约束）；dev/生产同代码 | import.meta.env 全量（生产无 env，需壳注入，二者并存双通道） |
| 工具端点例外（Q3 拍板） | settings/llm-keys + settings/llm/test 随 #79 交付 | 渲染层需要 key 管理/连通测试能力，而 APIKeyManager 仅 CLI 消费（源码核实）；工具端点 = 基础设施（与 /health 同类，不落业务库/不建实体），F19「不新增**业务**端点」不涵盖 | 前端直持 key（安全红线，否决）；复用 /pipelines/validate（语义不符——配置校验非连通性，评审否决）；不做测试（用户拍板否决：测试→保存是设置页标准 UX） |

### 4.10 待澄清问题（≤3，已全部拍板）

- **Q1 编辑器形态**：A. `textarea` 纯文本（样式可覆盖字体/行距，简单稳定，TDD 友好）；B. `contenteditable` 富文本（排版自由但光标/SSE 插入/格式清理复杂）；C. Markdown 双模式（编辑 textarea + 预览切换，自研轻量 md 渲染，为 0.6.0 F21 导出 MD 铺路，+0.5-1 人天）。**✅ 已确认（用户拍板：A 增强版——段落化纯文本，2026-08-03）**——按业界调查：中文网文平台（起点/阅文、晋江、番茄、飞卢）写作后台**高度一致为「纯文本段落」**（发布管线按段落解析，格式按钮基本被忽略），无 Markdown 分歧 → **不做切换功能**（用户预案「各网站不同则加切换」条件不成立，YAGNI；真遇差异后期可加，可逆）。落地 = textarea 增强：自动分段/首行缩进/字数统计/自动保存，**无格式按钮**。正文已按 A 修订（§4.2.1 工具栏移除加粗/链接）。
- **Q2 工具栏交互形态**：A. hover 编辑器区域唤起（原型现状，沉浸优先）；B. 常驻显示（发现性最好但占写作空间）；C. 快捷键 + hover 双通道。**✅ 已确认（用户拍板：选项 C，2026-08-03）**——快捷键提升长写效率、hover 保发现性。快捷键表按纯文本能力定义：`Ctrl+Z` 撤销 / `Ctrl+Y` 重做 / `Ctrl+S` 保存（Electron 内 preventDefault 接管）/ `Ctrl+Enter` AI 续写 / `Ctrl+Shift+Enter` 生成；**无格式快捷键**（纯文本无加粗/斜体）。正文已按 C 修订（§4.2.1）。
- **Q3 「测试连接」按钮语义**：A. 调用 `POST /api/v1/agent/pipelines/validate`（现有端点，但语义是管线配置校验而非 LLM 连通性）；B. 0.3.0 按钮禁用 + 提示「保存后于写作时验证」（无后端新增，语义诚实）；C. 新增后端连接测试端点（违背 F19「不新增业务端点」总声明）。**✅ 已确认（用户拍板：选项 A 修正——测试→保存主流程 + 保留直接保存，2026-08-03）**——评审翻转：设置页「先测试连接、通过后保存」是标准 UX（用户主路径），同时保留直接保存（用户自信场景）。原建议 B 存在认知偏差：「F19 不新增**业务**端点」≠「不新增任何端点」——key 管理与连通测试是**基础设施工具端点**（与 /health 同类，不落业务库/不建实体），不违背 F19 精神。前置事实（源码核实）：`APIKeyManager`（AES-256-GCM 加密，`data_dir/keys`）**唯一调用方为 CLI**（`cli/commands/llm.py`），后端无 key 管理端点、无 LLM 连通测试端点 → **#79 新增 2 个工具端点**（§4.4/§4.6）：`POST /api/v1/settings/llm-keys`（store）+ `POST /api/v1/settings/llm/test`（LLMClient 最小探测）。估算 4-6 → **5-7 人天**（+0.5-1）。正文已按 A 修正修订（§4.2.3/§4.4/§4.6/§4.8/§4.9/§8）。


---

## 5. UI 打磨（子任务 D，#98）

### 5.1 本章定位

**前端渲染层视觉打磨**（F19 第四子任务，M8 补做）：#79 渲染层（§4）已合入、功能完整，但视觉完成度约 60%——2026-08-05 三页实拍（vision-auxiliary 走查）确认 9 项差距；§4.8 M8「回归与走查」在 #79 交付时仅完成回归（91 测试绿），**视觉走查从未执行**。本任务 = 补执行 M8 + 按差距清单逐项打磨，交付 = **控件定制化 + 视觉层级 + 空态设计 + 品牌接入**四项打磨。

**关键事实（现状盘点，2026-08-05 源码 + 实拍核对）**：

- **token 已全量落地但 shadow 未接线**：`src/theme/tokens.css` 三主题色板/字体/圆角/`--shadow` 与 token 文档 §3 逐项一致；但 `src/index.css` `@theme` 仅映射色/字体/圆角，**未映射 shadow token**——卡片/对话框现用 Tailwind 默认 `shadow` 类（`ProjectCard.tsx`/`NewProjectDialog.tsx`），不随主题、无层级（差距 #5 平面化根因）
- **顶栏调试残留**：`App.tsx` L36-38 渲染 `{theme} / {lang}`（即「paper / zh」）；品牌 = 纯文本 `t('app.brand')`（'InkFlow'）；`src/assets/` 四个旧占位 svg（#94 骨架复制，墨滴概念）**全仓 0 组件引用**（grep 实测）——替换零引用风险
- **原生控件 5 处**：`AgentLlmCard.tsx`（select 服务商 + range 温度）、`AppearanceCard.tsx`（radio 主题 + select 背景/语言）、`NewProjectDialog.tsx`（select 题材/语言）、`AgentChainCard.tsx`（checkbox role=switch）——全部浏览器默认样式（差距 #2）
- **Agent 链字母方块**：`AgentChainCard.tsx` `AGENT_ROLES.glyph`（A/W/A/R，差距 #3）；`EditorToolbar` 为文字按钮（关联项）
- **状态栏空值半处理**：`StatusBar.tsx` 对 `null` 显示 `—`，但**空字符串未处理**（model 空串 → 渲染 `模型: `，差距 #8）；内核连接项仅 label 无状态值
- **空态简陋**：项目页空列表 = 网格仅剩虚线「+ 新建项目」卡片（差距 #4）；写作页无项目/无章节时仅 `write.stream.idle` placeholder 文案
- **状态色 token 已就位但应用稀疏**：`--ok/--warn/--err` 三主题已定义，仅测试连接结果等少数处使用（差距 #7 颜色单调）
- **依赖现状**：`package.json` 无 lucide-react（#79 骨架 6 个依赖）；引入需更新 `pnpm-lock.yaml`（ADR-025 锁定）
- **测试基线**：11 个测试文件 91 用例全绿（2026-08-05）；`data-testid` 契约密集（tree-chapter / new-project-btn / new-project-card / project-card / agent-llm-card / agent-chain-card / editor-toolbar / chapter-editor 等）——行为不变约束的回归锚点
- **CI 已就位**：`frontend-unit`（lint + typecheck + vitest）/ `frontend-integration`（真实内核）/ `frontend-e2e` 三 job 已落地（§4.6 声明兑现），本章**零 ci.yml 改动**

**边界声明（本章）**：
- **前端为主，壳层一处例外**：改动主要限 `frontend/packages/renderer/`（src/ + package.json + pnpm-lock.yaml）；**唯一壳层改动 = 移除 Electron 默认菜单栏**（`frontend/packages/electron/src/main.ts`，§5.2.9）——用户拍板（2026-08-05）；零后端改动、零 API 契约变更
- **行为不变（硬约束）**：不改变交互语义——快捷键（Ctrl+Z/Y/S/Enter/Shift+Enter）、上下文折叠/展开条、SSE 流式与停止、自动保存、路由与跳转全部保持；既有 `data-testid` 契约不删不改（新增锚点除外）
- **低动效**：token 文档 §1 五项约束（动效 ≤180ms 仅状态变化；`prefers-reduced-motion` 降级已就位 tokens.css）；SSE 逐 token 仍是唯一动态感
- **不含主题可视化预览卡片**：外观卡片 radio 仅做样式定制，预览卡片归 **#99**（范围外，本章 Q 亦不涉及）
- **不含位图/窗口图标接入**：favicon.ico、Electron 窗口/打包图标属 #48 0.4.0；本章只做 renderer 内 SVG 品牌接入

### 5.2 工作分解（issue 范围 8 项）

#### 5.2.1 M8 视觉走查（补执行 + 修正闭环）

- 基线：三页实拍差距清单 9 项（2026-08-05，见 §5.1）即 M8 走查基线；实施完成后用 **vision-auxiliary 三主题截图 + ui-design-taste checklist**（无模板感/无紫色渐变/无玻璃拟态/无 6 级排版/动效 ≤200ms/写作页密度最低档）复核，逐项关闭
- 输出：走查记录（三主题 × 背景变体截图 + checklist 勾选 + 残留项说明）随 PR 附上

#### 5.2.2 控件定制化（差距 #2/#9）

逐控件落点（去浏览器默认样式；形状一致性按 token 文档 §3.3：按钮/输入 6px、小控件 4px）：

| 控件 | 实例（文件） | 定制内容 |
|------|-------------|---------|
| select | AgentLlmCard 服务商 / AppearanceCard 背景+语言 / NewProjectDialog 题材+语言 | `appearance:none` + 自绘箭头（lucide ChevronDown）+ token 色板 + accent focus ring |
| radio | AppearanceCard 主题三选 | `appearance:none` + 自绘圆点选中态（accent）——**保持文字 radio，不做可视化预览卡片（#99）** |
| checkbox/switch | AgentChainCard 四行开关 | switch 形态（轨道 + 滑块，checked=accent；`role="switch"` 语义与 aria-label 保持） |
| range 滑杆 | AgentLlmCard 温度 0-2.0 | 轨道/滑块定制（accent 填充、`--radius-s`、hover 反馈、数值对齐） |

- 定制样式统一收敛（**决策 Q1 ✅ = A：shadcn 组件化**——引入 Radix Select/Switch/Slider/RadioGroup 依赖栈，组件收敛 `src/components/ui/`，用户拍板 2026-08-05）：select 用 shadcn Select（Radix，含自定义下拉面板/箭头/高亮）、radio 用 RadioGroup、开关用 Switch、温度用 Slider——全部覆盖 token 色板 + focus ring；**交互语义保持**（`role="switch"`、aria-label、onChange 契约不变）

#### 5.2.3 视觉层级（差距 #5/#7）

- **shadow 接线**：`index.css` `@theme` 补映射——`--shadow` → Tailwind 语义类（如 `shadow-card`），卡片/对话框阴影随主题（tokens.css 三主题 `--shadow` 已定义，零 token 值改动）
- 层级表（token 文档 §3.3 形状一致性）：卡片静止（border-line + shadow）→ hover（`--surface-3` 或浮起阴影 +1 档）→ 按压（轻微收缩）→ focus（accent focus ring，统一新增 `--ring` token）
- 卡片浮起感：ProjectCard hover 阴影加深 + 边框过渡（≤180ms）
- 按钮反馈：主按钮（accent）hover 加深/按压收缩；次按钮 hover `--surface-3`；禁用态统一 opacity
- **状态色体系应用**（差距 #7）：`--ok/--warn/--err` 用于状态展示（测试连接结果、自动保存、流式完成摘要等），不做装饰性彩色

#### 5.2.4 排版间距（差距 #6）

- 卡片内 padding 统一：Agent 卡片 `p-6` 与 ProjectCard `p-5` 对齐（按 token 密度：项目/配置页标准工具密度，写作页最低档）
- Label-Input 间距：`mb-1` → 统一 6-8px（表单布局 gap 化：NewProjectDialog / AgentLlmCard / AppearanceCard）
- 字重/字号层级收敛（≤3 级）：页面标题（26px 衬线 semibold）→ 卡片标题（17-18px）→ 正文（13-14px）→ 辅助（11-12px）；现状部分组件 12px 过小、字重全靠 semibold 堆叠
- 编辑器正文保持 16px / 行高 1.85 / 首行缩进 2em（token 文档 §3.3，**不改**）

#### 5.2.5 图标资产（差距 #3）

- 引入 **lucide-react**（决策 §5.6）：tree-shaking 按需；shadcn 生态同源（#79 骨架）
- 替换点：Agent 链「A/W/A/R」字母方块 → 角色图标（Architect→Compass / Writer→PenLine / Auditor→SearchCheck / Reviser→RefreshCw 等，实现按语义选型、走查确认）；EditorToolbar 文字按钮 → 图标按钮（Undo2/Redo2/Save/Wand2/Sparkles 等，**aria-label 保持现有 i18n 文案**）；项目树「新建章节」✓/× → 图标（Check/X）
- 图标化后 hover/focus/按压反馈随 §5.2.3；图标 stroke 宽度与 `--ink-2`/`--ink-3` 配色对齐

#### 5.2.6 空态设计（差距 #4）

- **项目页空列表**（`projects.tsx` 空列表分支）：虚线卡片 → 引导化空态——居中图标（lucide BookOpen）+ 主文案（「还没有项目」）+ 次文案（「创建你的第一个故事，从书名开始」）+ CTA 按钮（「新建项目」→ 复用 NewProjectDialog）；网格末位虚线卡片**保留**（有项目时）
- **写作页空态**：无项目 → 居中引导（图标 + 「选择或新建项目开始写作」+ 返回项目页按钮）；有项目无章节 → 项目树「新建章节」引导 + 编辑器 placeholder 文案增强
- 空态文案进 i18n（zh.ts / en.ts 双语，新增 key ≤6）

#### 5.2.7 调试残留清理（差距 #1/#8）

- 顶栏：移除 `{theme} / {lang}` 调试文本 → 品牌接入（§5.2.8）
- 状态栏：空字符串与 null 统一显示 `—`（model 空串场景）；内核连接项显示状态值（已连接/未就绪——i18n 已有 `sb.kernel` / `sb.kernelOffline` key）

#### 5.2.8 品牌接入（环流口，2026-08-05 定稿）

```text
现状: [InkFlow 文字]  导航…                      paper / zh    ← 调试残留
改造: [icon] InkFlow  导航…                      （移除）      ← 品牌 logo 接入
```

- 资产替换：`src/assets/` 四个旧占位 svg（墨滴概念，#94 复制）→ **环流口**新版（源 `logos/brand/`，2026-08-05 定稿「Ink 从环中 Flow 出」）：`inkflow-icon.svg`（素笺墨蓝）/ `inkflow-icon-dark.svg`（夜航暖金）/ `inkflow-icon-ink.svg`（墨韵朱砂）+ 横版 `inkflow-logo*.svg`（按决策 Q2 选型）
- 主题切换（**决策 Q2 ✅ = A：三主题精确**——paper→`inkflow-icon.svg`（墨蓝）/ night→`-dark.svg`（暖金）/ ink→`-ink.svg`（朱砂），用户拍板 2026-08-05）：随 `data-theme` 切换图标变体；实现方式（组件内按 theme store 选资源或 CSS url 切换）以 TDD 为准
- 旧占位 svg 全量删除（0 引用，安全）；品牌 README 落位指引中「frontend/assets/」路径以实际 `frontend/packages/renderer/src/assets/` 为准

#### 5.2.9 Electron 菜单栏移除（用户拍板 2026-08-05）

- **现状**：`frontend/packages/electron/src/main.ts` BrowserWindow 未配置菜单——Windows 默认显示 File/Edit/View/Window/Help 原生菜单栏（File/Edit/Window 等按钮 + 选择框），与沉浸式写作产品形态不符
- **方案**：`Menu.setApplicationMenu(null)` 彻底移除（含 Alt 唤出通道）；**开发模式保留调试通道**——`app.isPackaged === false` 时注册快捷键（F12 / Ctrl+Shift+I）调 `webContents.openDevTools()`（无菜单后默认加速键失效，需显式注册）
- 约束：不动 renderer；E2E 无菜单断言（实测），移除不破坏现有测试；macOS 差异（应用菜单系统惯例）记录待 2.0.0 云端/跨平台阶段，本章以 Windows 为准

### 5.3 文件结构（#98 CREATE/MODIFY 清单，对照真实树 2026-08-05）

| 操作 | 文件 | 内容 |
|------|------|------|
| MODIFY | `frontend/packages/renderer/package.json` | 新增依赖 `lucide-react`（版本与 pnpm 解析对齐，ADR-025） |
| MODIFY | `frontend/pnpm-lock.yaml` | lock 更新（lucide-react 及传递依赖；lock 必须提交） |
| MODIFY | `src/index.css` | `@theme` 补 shadow 映射（`--shadow` → `shadow-card` 语义类） |
| MODIFY | `src/theme/tokens.css` | 新增 `--ring`（focus ring 色，三主题按 accent 派生）等控件 token（§5.2.3） |
| MODIFY | `src/App.tsx` | 顶栏：品牌 logo + 移除 `{theme} / {lang}` 调试文本（§5.2.7/5.2.8） |
| MODIFY | `src/pages/projects.tsx` | 空列表引导化分支（§5.2.6） |
| MODIFY | `src/pages/writing.tsx` | 无项目/无章节空态（§5.2.6） |
| MODIFY | `src/components/AgentChainCard.tsx` | 字母方块 → lucide 图标；checkbox → 定制 switch（§5.2.2/5.2.5） |
| MODIFY | `src/components/AgentLlmCard.tsx` | select/range 定制 + Label-Input 间距（§5.2.2/5.2.4） |
| MODIFY | `src/components/AppearanceCard.tsx` | radio/select 定制（§5.2.2；**不做预览卡片，#99**） |
| MODIFY | `src/components/NewProjectDialog.tsx` | select 定制 + 表单间距（§5.2.2/5.2.4） |
| MODIFY | `src/components/ProjectCard.tsx` | shadow 层级 + hover 浮起 + padding（§5.2.3/5.2.4） |
| MODIFY | `src/components/EditorToolbar.tsx` | 文字按钮 → 图标按钮（aria-label 保持）（§5.2.5） |
| MODIFY | `src/components/StatusBar.tsx` | 空字符串空态 + 内核连接状态值（§5.2.7） |
| MODIFY | `src/components/ChapterEditor.tsx` | 无章节空态文案（§5.2.6） |
| MODIFY | `src/components/ProjectTree.tsx` | 新建章节 ✓/× → 图标（§5.2.5） |
| MODIFY | `src/components/ProjectSeal.tsx` `ContextPanel.tsx` `StreamArea.tsx` | 按走查清单微调（间距/反馈，§5.2.3/5.2.4） |
| MODIFY | `src/i18n/zh.ts` `en.ts` | 空态文案 + 新 aria-label key（§5.2.6，≤6 key 双语） |
| MODIFY | `src/assets/` | 旧占位 svg ×4 删除；环流口新版 svg 复制（`logos/brand/` 2026-08-05 定稿） |
| NEW | `src/components/ui/`（决策 Q1=A：shadcn 组件化） | Radix 封装组件收敛（Select/Switch/Slider/RadioGroup + 样式 token 覆盖，§5.2.2） |
| MODIFY | `frontend/packages/electron/src/main.ts` | 移除默认菜单栏：`Menu.setApplicationMenu(null)` + 开发模式 F12/Ctrl+Shift+I 开 DevTools（§5.2.9） |
| MODIFY | `frontend/packages/electron/src/main.test.ts` 或新增 | 菜单移除/DevTools 快捷键注册的单元断言（§5.4，如现有 kernel.test.ts 惯例） |
| NEW | 组件测试（同目录 `*.test.tsx` 惯例，如 `src/components/StatusBar.test.tsx`） | 空态/空值/图标 aria-label 断言（§5.4） |

> **要求 ↔ 清单映射核对**：§5.2 八项工作分解全部能映射到上表落点；M8 走查（§5.2.1）为过程性工作项，不产生独立文件（走查记录随 PR 附上）。

### 5.4 测试策略

| 层次 | 关键场景 |
|------|----------|
| 回归（自动，行为不变） | 现有 91 用例全量（`pnpm --filter renderer test`）——`data-testid` 契约与交互语义零变更；**本章零 MODIFY store / api / useStream**（三处测试不动） |
| 组件补充（自动，vitest + RTL） | 项目页空列表引导化分支（空态文案渲染 + CTA 打开新建对话框）；写作页无项目空态；StatusBar 空字符串/空值 → `—`；Agent 链图标替换后 `aria-label` 与开关切换语义不变（`getByRole('switch')` 断言保持）；顶栏 logo 渲染（img alt 或 aria-label） |
| 类型/门禁（自动） | `pnpm --filter renderer typecheck` + `lint` + `build`；CI `frontend-unit` job（已就位，零 ci.yml 改动） |
| 集成冒烟（自动，真实内核） | CI `frontend-integration`（renderer apiFetch ↔ 真实内核）保持绿——证明 API 面零回归 |
| 视觉走查（手动 + vision-auxiliary） | 三主题（素笺/夜航/墨韵）× 各背景变体截图 + ui-design-taste checklist 逐项勾选；对比度 AA（token 文档已知项 #4）；深色模式控件/logo 变体切换 |

> 前端测试不测样式（Tailwind 类名）约定延续：新增断言只测行为与可访问性（aria-label / role / 文案），不测视觉类名。

### 5.5 验收标准（#98）

- **M1**（手动 + vision）M8 走查闭环：vision-auxiliary 三主题 × 背景变体截图 + ui-design-taste checklist 全过（无模板感 / 对比度 AA / 低动效）——§4.8 M8 补执行
- **M2**（手动 + vision）差距清单 9 项逐项关闭（§5.1 基线 → §5.2 落点 → 截图对比确认）：1 顶栏残留 / 2 原生控件 / 3 字母方块 / 4 空态 / 5 平面化 / 6 排版间距 / 7 颜色单调 / 8 状态栏空值 / 9 radio 样式定制
- **M3**（自动）回归：现有 91 前端测试全绿 + 新增组件测试全绿（`vitest run`）；`typecheck` / `lint` / `build` 绿；CI `frontend-unit` / `frontend-integration` 绿
- **M4**（手动 + vision）品牌接入：环流口 logo 顶栏展示；夜航（深色）自动切换 `-dark` 变体、墨韵切换 `-ink`（按 Q2 拍板）；旧占位 svg 全量移除（`src/assets/` 仅剩新版）
- **M5**（手动 + vision）控件定制化：select / radio / checkbox / switch / range 无浏览器默认样式（三主题截图确认）；温度滑杆细节（轨道/滑块/数值对齐）
- **M6**（手动 + vision）视觉层级：卡片阴影随主题、hover / focus / 按压反馈、卡片浮起感（三主题截图 + 交互验证）
- **M7**（手动）行为不变冒烟：快捷键（Ctrl+S / Ctrl+Enter / Ctrl+Shift+Enter）、上下文折叠、SSE 流式（生成/停止）、自动保存——与打磨前一致
- **M8**（自动）调试残留清理断言：组件测试断言顶栏无 theme/lang 调试文本；StatusBar 空串显示 `—`
- **M9**（手动 + 自动）Electron 菜单栏移除：窗口无 File/Edit/View/Window 原生菜单栏（手动）；`Menu.setApplicationMenu(null)` 调用断言 + 开发模式 F12 快捷键注册断言（自动，electron 包单元测试）——`frontend-e2e` 回归绿

> M 行 ↔ 自动化载体映射：M1/M2/M4/M5/M6 视觉类（vision-auxiliary 截图 + 手动交互，走查记录随 PR 留档）；M3/M8 自动（vitest + CI）；M7 手动冒烟。视觉类验收以「截图 + checklist」留档，不引入自动化视觉回归（超出 0.3.0 范围，0.4.0 评估 visual-regression 技能）。

### 5.6 关键架构决策记录（#98）

| 决策 | 方案 | 理由 | 备选（否决） |
|------|------|------|--------------|
| 图标库 = lucide-react | tree-shaking 按需引入 | shadcn 生态同源（#79 骨架以 shadcn 为基础，后续 shadcn 组件可复用其图标）；线性 stroke 契合「安静克制」语言；React 19 兼容、零配置 | 自绘 SVG 集（维护成本、无统一 stroke 语义）；纯文本/Unicode 符号（差距 #3 现状，否决） |
| 控件定制路径（Q1 ✅ = A，2026-08-05 用户拍板） | **A. shadcn 组件化**（Radix Select/Switch/Slider/RadioGroup，+依赖栈） | 学习价值（项目第一动机）+ 还 #79 选型债（骨架以 shadcn 为基础但实现用了原生控件）；可访问性完备（Radix 键盘导航/ARIA 开箱即用）；与 lucide-react 同生态 | B. CSS 覆盖原生（零依赖但下拉面板/键盘导航受限，select 能力不足时反而更难）；C. 混合（两套路径并存，维护面分裂） |
| Electron 菜单栏 = 移除（用户拍板 2026-08-05） | `Menu.setApplicationMenu(null)` 彻底移除 + 开发模式显式注册 F12/Ctrl+Shift+I 开 DevTools | 沉浸式写作形态（Windows 默认 File/Edit/Window 菜单栏与产品气质冲突）；无菜单后默认加速键失效需显式补 dev 通道；E2E 无菜单断言不破坏 | `autoHideMenuBar: true`（Alt 仍可唤出，未彻底）；保留默认菜单（现状，验收不过） |
| 品牌图标主题切换（Q2 ✅ = A，2026-08-05 用户拍板） | **A. 三主题精确切换**（paper→icon / night→icon-dark / ink→icon-ink） | ink 版资产已定稿存在（`logos/brand/inkflow-icon-ink.svg`），三版按 `data-theme` 切换零额外成本；「深浅二分」在墨韵（浅底 + 朱砂 accent）下不成立——浅底配墨蓝 icon 会突兀 | B（token 文档 §4.5 表述，但文档早于品牌定稿，未考虑墨韵第三色） |
| 空态实现 = 组件内条件渲染 | 不新增路由/页面/抽象组件，`projects.tsx` / `writing.tsx` 分支内联 | 仅 2 处空态，独立 EmptyState 组件抽象价值低（YAGNI）；i18n 文案 key ≤6 | 独立 EmptyState 组件（可复用性当前为零）；新增引导路由（过度设计） |
| 顶栏调试文本 = 移除 | 品牌 logo 替代 `{theme} / {lang}` | 外观设置入口已在 Agent 配置页「外观」卡片（token 文档已知项 #5），顶栏重复指示冗余；主题/语言当前值非用户高频信息 | 产品化为主题名 label（视觉噪音、信息冗余，否决）；保留（调试残留，验收不过） |
| shadow 接线 = @theme 映射 | `index.css` 补 `--shadow` → Tailwind 语义类 | token 文档 §3.3 已定义三主题 `--shadow`，只差映射（现状卡片用默认 shadow 不随主题）；零 token 值改动 | 组件内联 shadow 样式（散落、不随主题）；重定义 shadow 值（token 文档已评审通过，YAGNI） |

### 5.7 待澄清问题（≤3）

- **Q1 控件定制路径**：A. shadcn 组件化（引入 Radix Select/Switch/Slider/RadioGroup 依赖栈，一致性最好、可访问性完备）；B. CSS 覆盖原生控件（`appearance-none` + `controls.css` 全局类，零新依赖）；C. 混合（select 走 shadcn、checkbox/radio 走 CSS）。**✅ 已确认（用户拍板：选项 A，2026-08-05）**——学习价值（项目第一动机）+ 还 #79 选型债（骨架以 shadcn 为基础但实现用了原生控件）；Radix 键盘导航/ARIA 开箱即用；与 lucide-react 同生态。正文已按 A 修订（§5.2.2/§5.3/§5.6）。
- **Q2 品牌图标主题切换粒度**：A. 三主题精确切换（paper→`inkflow-icon.svg` / night→`-dark.svg` / ink→`-ink.svg`，ink 版资产已定稿）；B. 深浅双版（素笺/墨韵共用浅色版、仅夜航切 `-dark`）。**✅ 已确认（用户拍板：选项 A，2026-08-05）**——墨韵为浅色底 + 朱砂 accent，共用墨蓝 icon 视觉突兀；三版资产均已存在，切换成本为零。正文已按 A 修订（§5.2.8/§5.6）。
- **Q3 顶栏品牌形态**：A. 仅图标；B. 图标 + 横版 logo（含副标题，顶栏高度内不可读）；C. 图标 + 文字「InkFlow」（复用 i18n `app.brand`）。**✅ 已确认（用户拍板：选项 C，2026-08-05）**——横版 logo 为 1000×320 比例副标题在顶栏（约 40px 高）内不可读；C 复用现有 i18n、零新增文案，横版 logo 留给后续页面。正文已按 C 修订（§5.2.8）。
- **Q4 Electron 菜单栏**（用户主动提出，2026-08-05）：彻底移除默认菜单栏（`Menu.setApplicationMenu(null)`）+ 开发模式 F12/Ctrl+Shift+I 显式注册开 DevTools。已并入正文（§5.2.9/§5.3/§5.5 M9/§5.6）。

（注：主题可视化预览卡片已明确划归 #99，本章全部 Q 与工作项均不涉及。）

---

## 6. 交互反馈与产品化补全（#99）

### 6.1 本章定位

**状态：✅ 设计基准（2026-08-05 用户拍板：#99 spec 完成后关闭，实现并入 #105 §7）**

- 背景：#99（0.3.0）定义渲染层交互反馈 6 大块；UI 原型（`prototypes/client-ui-v1/`，15 截图用户确认）评审期间全部交互已设计并验证
- **2026-08-05 用户拍板**：完成本章 spec 后关闭 #99；toast/骨架/空态/ESC/快捷键提示/主题预览的**实现并入 #105**（§7 范围第 5 项）；评审遗留清理随 #105 文件结构落点
- 本章 = 设计基准章节：验收标准并入 §7.8（#105 的 M 行），不单独验收

### 6.2 工作分解（#99 范围 6 块 → 实现落点）

| # | 范围项（#99） | 设计（原型已验证） | 实现落点 |
|---|--------------|-------------------|---------|
| 1 | 反馈体系 | 错误 toast（内核未就绪/保存失败/创建失败）+ 加载骨架屏；toast 三态（ok/err/warn）+ 2s 自动消失 + aria-live | §7.6（`stores/toast.ts` + `components/ui/toast.tsx` + skeleton 组件） |
| 2 | 空态引导 | 新手指引（创建首个项目 → 写作路径）；设定库未选择项目引导（「选择或新建项目开始构建设定」+ 前往项目页） | §7.3（设定库项目上下文） |
| 3 | 对话框交互 | ESC 关闭 + 遮罩点击关闭 + 过渡动效（≤180ms，reduced-motion 降级）+ 关闭后焦点归还触发按钮 | §7.6（NewProjectDialog 等模态） |
| 4 | 快捷键提示 | 工具栏 hover 提示（Ctrl+Z/Y/S/Enter/Shift+Enter）+ 设置页快捷键一览表 | §7.6（EditorToolbar title/浮层） |
| 5 | 主题可视化预览 | 外观卡片 radio → 三主题缩略预览卡片（纸张/深色/东方，accent ring 选中态） | §7.6（AppearanceCard → 设置页常规） |
| 6 | 评审遗留 6 项 | 见 §6.3 | §7.6 |

### 6.3 评审遗留清理（#97 non-load-bearing，实现并入 #105）

| # | 项 | 现状（2026-08-05 源码核实） | 处理 |
|---|-----|---------------------------|------|
| ① | defaultWords 不落字段 | `AgentLlmCard.tsx` L24 `useState(800000)` 本地 state，刷新丢失 | 接入 store config 字段（ProjectConfig 对应字段）+ 回读 |
| ② | 新建项目失败无错误展示 | `NewProjectDialog.tsx` `handleCreate` `await createProject` 无 try/catch | try/catch + 错误 toast/内联展示 |
| ③ | Agent 链 glyph 重复 | **✅ #98 已修复**（AgentChainCard 用 lucide 图标 Network/PenLine/ClipboardCheck/RefreshCw） | 仅验证 + 测试断言防回归 |
| ④ | i18n 冗余 key ×9 | zh.ts/en.ts 存在未用 key | 脚本定位删除 + lint 断言 |
| ⑤ | validBgs 重复维护 | `stores/theme.ts` L46-47 内联数组与 `theme/index.ts` `BG_BY_THEME` 重复 | 单一来源：store 引用 `BG_BY_THEME[theme]` |
| ⑥ | resolveInitialTheme 死代码 | `theme/index.ts` L26-38 全仓 0 引用（store 内 `initialTheme()` 为活实现） | 删除 + typecheck |

### 6.4 测试策略（并入 §7.7）

- toast store 行为（队列/自动消失）；ESC 关闭模态；快捷键提示可见性；主题预览 radio 选择行为不变
- defaultWords 持久化回读；theme 单一来源（validBgs 引用 BG_BY_THEME）；resolveInitialTheme 删除后 typecheck 绿
- i18n 冗余 key 清理后 lint 断言（无未用 key）

### 6.5 关键决策记录（#99）

| 决策 | 方案 | 理由 | 备选（否决） |
|------|------|------|--------------|
| #99 关闭方式 | spec 完成后关闭，实现并入 #105 | 原型阶段交互已设计验证；#105 承载实现避免 0.3.0 拖尾（用户拍板 2026-08-05） | #99 独立实现（0.3.0 再做一轮，与 #105 重复，否决） |
| toast 形态 | 轻量自研（Zustand store + 挂载点） | 文案 <20 key、三态、低动效；与 i18n 同源 | 引入 Sonner/toastify（0.3.0 场景过重，YAGNI） |
| 快捷键提示 | 工具栏 title/hover 浮层 + 设置页一览表 | 双通道发现性（#79 Q2 拍板延续） | 仅 hover 浮层（发现性不足） |
| 主题预览 | 三主题缩略预览卡片（CSS 色块模拟） | 可视化对比优于文字 radio（原型验证） | 保持文字 radio（#98 现状，用户要求升级） |

---

## 7. 导航重构：侧边栏 + 设定库项目上下文 + 设置页框架（子任务 E，#105）

### 7.1 本章定位

**F19 渲染层上位演进（0.4.0，纯前端）**：3 页（项目/写作/Agent）→ 4 页 + 左侧可折叠导航（写作/项目/设定库/设置），模型管理页由 #106 承接。

**关键事实（2026-08-05 原型评审定稿）**：

- UI 设计基准 = `design/client-ui-interaction-requirements-2026-08-05.md`（PM 文档，信息架构方案 A）+ `prototypes/client-ui-v1/index.html`（15 张截图用户确认）
- 现有 3 页组件齐备（pages/projects|writing|agents + components/*），`data-testid` 契约密集（91+ 用例全绿基线）
- 设定库 6 模块后端全部按 project_id 隔离（F9-F13）——UI 必须项目上下文
- 三主题 × 背景变体 × 中英双语机制已就位（tokens.css/theme store/i18n）；ci.yml 三前端 job 已就位（零 ci.yml 改动）

**边界声明（本章）**：
- 纯前端 `frontend/packages/renderer/`，零后端改动、零 API 契约变更
- 模型管理页（#106）与 Agent 模板（#107）不在本章实现（设置页「模型/模板」分类先放摘要/占位面板）
- 不改变现有交互语义（快捷键/折叠/SSE 流式/自动保存）；既有 data-testid 契约不删不改（新增锚点除外）

### 7.2 信息架构（PM 方案 A，用户确认）

```text
┌────────────┬──────────────────────────────────┐
│ [环流口]   │ 顶栏：页面标题 · 主题/语言 · 内核状态 │
│ InkFlow    │                                  │
├────────────┼──────────────────────────────────┤
│ ✎ 写作     │                                  │
│ ▦ 项目     │                                  │
│ ─────────  │          页面内容区               │
│ 设定库      │  写作 / 项目 / 设定库 / 设置       │
│  角色/世界观/大纲/时间线/伏笔/知识库RAG          │
│ ─────────  │                                  │
│ ⚙ 设置     │                                  │
│ ◈ Agent    │（Agent 快捷入口 → 设置-分类）      │
└────────────┴──────────────────────────────────┘
        ↕ 可折叠为 52px 图标窄条（写作沉浸）
```

- **侧边栏三分组**：写作区（写作/项目）/ 设定库（角色/世界观/大纲/时间线/伏笔/知识库 RAG）/ 系统（模型管理[#106 占位]/Agent 快捷入口/设置）
- **顶栏职责回归**：品牌（环流口 logo 三变体随主题）+ 页面标题 + 主题/语言/内核状态；不再承担导航
- **折叠**：52px 图标窄条 + 展开恢复（`prefers-reduced-motion` 降级）

### 7.3 设定库项目上下文

- **入口语义 = 当前项目的设定库**（数据按 project_id 隔离的事实驱动）
- **项目选择器**（设定库页顶部）：当前项目下拉（青云志/归墟记/…），切换 → 内容重载；面包屑「设定库 · 项目名 / 分类」
- **未选择项目空态**：「选择或新建项目开始构建设定」+ 前往项目页按钮（切换路由）
- 六个 tab（角色/世界观/大纲/时间线/伏笔/知识库 RAG）：列表视图 + 空态引导（「还没有角色，去创建」+ CTA）；RAG 页索引状态列表（已提取/提取中/待提取）+ 检索测试占位
- 写作页上下文面板「设定库速览」保留（与设定库页项目上下文一致）

### 7.4 设置页框架

- **左侧分类导航 + 右侧面板**：常规 / 模型 / Agent / 模板 / 账户 五分类（分类图标 + 文字，选中高亮）
- **分类内容**：
  - 常规：语言、主题（三 radio + 可视化预览卡片）、背景变体、编辑器字体、新章节默认字数、快捷键一览表
  - 模型：已配置 Provider 摘要 + 前往模型管理入口（#106 落地后联动；本期摘要+占位）
  - Agent：四角色开关 + 模型下拉（迁移自 AgentChainCard）
  - 模板：模板列表占位 + 新建入口（#107 落地）
  - 账户：数据目录 + 数据管理（导出/备份占位）+ 关于（版本/logo）
- **交互**：即改即存 + 轻量「已保存」toast（数字项失焦即存）；所有设置项三主题 × 中英双语
- **迁移**：`pages/agents.tsx` 拆分——AgentChainCard → 设置-Agent 分类；AppearanceCard → 设置-常规（含主题预览卡片）；AgentLlmCard 待 #106 迁移

### 7.5 交互反馈承接（#99 并入，见 §6）

toast 体系（三态/2s/aria-live）、骨架屏（项目列表/章节树加载态）、模态 ESC + 焦点归还、快捷键提示（工具栏 hover + 设置页一览）、主题可视化预览卡片、评审遗留 6 项清理——全部在本章实现（§6.2/§6.3 落点）。

### 7.6 文件结构（#105 CREATE/MODIFY 清单，对照真实树 2026-08-05）

| 操作 | 文件 | 内容 |
|------|------|------|
| MODIFY | `src/App.tsx` | 布局改造：顶栏（品牌/标题/全局状态）+ 侧边导航容器 + 路由出口；路由扩展（/writing /projects /library /settings，HashRouter） |
| NEW | `src/components/AppNav.tsx` | 侧边导航（三分组/折叠 52px/Agent 快捷入口/active 态） |
| NEW | `src/pages/settings.tsx` | 设置页（五分类导航 + 面板切换 + 即改即存） |
| NEW | `src/pages/library.tsx` | 设定库页（项目选择器/面包屑/六 tab/空态/未选择引导） |
| MODIFY | `src/pages/agents.tsx` | 拆分迁移：AgentChainCard → 设置-Agent；AppearanceCard → 设置-常规；页面删除或重定向 |
| MODIFY | `src/pages/projects.tsx` `writing.tsx` | 导航适配（路由/跳转联动）+ 骨架屏 |
| MODIFY | `src/components/NewProjectDialog.tsx` | ESC 关闭 + 过渡动效 + try/catch 错误展示（§6.3②）+ Agent 模板下拉占位（#107） |
| MODIFY | `src/components/EditorToolbar.tsx` | 快捷键提示（title/hover 浮层，Ctrl+Z/Y/S/Enter/Shift+Enter） |
| MODIFY | `src/components/AppearanceCard.tsx` | 主题可视化预览卡片（radio → 预览卡） |
| MODIFY | `src/components/AgentChainCard.tsx` | 迁移至设置页（行为不变） |
| MODIFY | `src/components/AgentLlmCard.tsx` | defaultWords 落字段（§6.3①，config 字段确认后） |
| MODIFY | `src/stores/theme.ts` + `src/theme/index.ts` | validBgs 单一来源（引用 BG_BY_THEME）+ resolveInitialTheme 死代码删除（§6.3⑤⑥） |
| NEW | `src/stores/toast.ts` + `src/components/ui/toast.tsx` | toast 体系（§6.2①） |
| NEW | `src/components/ui/skeleton.tsx` | 骨架屏组件 |
| MODIFY | `src/i18n/zh.ts` `en.ts` | 新增 key（导航/设置/空态/toast/快捷键）+ 冗余 key 清理（§6.3④） |

### 7.7 测试策略

| 层次 | 关键场景 |
|------|----------|
| 组件（vitest + RTL） | 侧边导航渲染/折叠/active 态；设定库项目选择器切换内容 + 未选择空态；设置页五分类切换 + 即改即存 toast；toast store 行为；ESC 关闭；快捷键提示可见；主题预览选择行为；defaultWords 持久化回读 |
| 集成（真实内核） | `frontend-integration` 保持绿（API 面零回归——路由/组件改造不触 API） |
| E2E | 导航流：写作 → 项目 → 设定库（选择项目）→ 设置（改主题/语言）闭环 |
| 视觉走查 | vision-auxiliary 三主题 × 新页面截图 + 低动效确认 |

> 零 ci.yml 改动（三前端 job 已就位）；既有 91+ 用例保持全绿（data-testid 契约不删不改）。

### 7.8 验收标准（#105）

- **M1**（自动）侧边导航：三分组入口齐全、折叠 52px 可恢复、active 态正确（vitest）
- **M2**（自动）设定库项目上下文：项目选择器切换内容正确；未选择项目空态 + 前往项目页
- **M3**（自动）设置页五分类切换 + 卡片迁移完成（AgentChainCard/AppearanceCard 行为不变断言）
- **M4**（自动）交互反馈：toast 三态/骨架屏/ESC/快捷键提示/主题预览（§6 承接项）
- **M5**（自动）评审遗留 6 项全部关闭（含 glyph 验证）
- **M6**（自动）三层测试全绿：frontend-unit/integration/e2e + 既有 91+ 用例零回归
- **M7**（手动 + vision）三主题 × 新页面截图走查（无模板感/对比度 AA/低动效）
- **M8**（手动）Electron 生产模式（file://）导航/设置/设定库全流程可用（#78 壳已就位）

### 7.9 关键架构决策记录（#105）

| 决策 | 方案 | 理由 | 备选（否决） |
|------|------|------|--------------|
| 导航形态 = 左侧可折叠 | 三分组侧边栏 + 52px 折叠 | 10+ 入口层级需分组表达；桌面创作客户端惯例（Scrivener/Obsidian）；写作沉浸可折叠（PM 方案 A，用户确认） | 顶栏扩展（层级扁平，否决）；汉堡抽屉（多一步点击，否决） |
| 设定库 = 项目上下文 | 项目选择器 + 面包屑 + 未选择空态 | F9-F13 数据按 project_id 隔离（用户反馈确认）；避免「全局设定库」误导 | 全局固定设定库（与数据模型矛盾，否决） |
| 设置页 = 分类框架 | 五分类（常规/模型/Agent/模板/账户） | 主流客户端惯例；Agent 配置拆分后功能不丢（用户确认）；模板分类为 #107 预位 | 单页长表单（分类增长后不可扩展，否决） |
| #99 并入 | 交互反馈在导航/设置框架中实现 | 原型已验证设计；避免 0.3.0 拖尾（用户拍板） | #99 独立实现（重复工作，否决） |
| 即改即存 | 设置项即时生效 + 轻量 toast | 本地优先客户端、设置项少、低动效符合定位（Obsidian/VS Code 同模式）；数字项失焦即存 | 显式保存按钮（表单密集型场景才需要，否决） |
| 设置页「模型/模板」分类 | 本期摘要/占位，#106/#107 落地后联动 | 依赖未实现时不做空壳交互（YAGNI） | 本期实现完整面板（依赖缺失，否决） |

### 7.10 待澄清问题（≤3）

- **Q1 旧路由 /agents 处理**：A. 删除（HashRouter 无刷新 404 问题，直接移除）；B. 保留重定向到 `/settings?cat=agent`（旧链接兼容）。**✅ 已确认（用户拍板：选项 A，2026-08-05）**——桌面应用无外部链接心智，YAGNI。正文已按 A 修订（§7.6 agents.tsx 删除或重定向 → 删除）。
- **Q2 主题预览卡片形态**：A. 三色块抽象缩略（原型现状：底色 + accent 圆点 + 文字标签）；B. 微缩布局（迷你窗口/卡片结构示意，更直观但实现量略增）。**✅ 已确认（用户拍板：选项 A，2026-08-05）**——原型已验证，低动效原则。正文已按 A 修订（§7.4/§7.6）。
- **Q3 toast 堆叠策略**：A. 单条替换（新 toast 顶替旧 toast）；B. 队列堆叠（最多 3 条，超出丢弃最早）。**✅ 已确认（用户拍板：选项 B，2026-08-05）**——失败/成功连续发生时用户需看到全部反馈；3 条上限防刷屏。正文已按 B 修订（§6.2/§7.6 stores/toast.ts 队列语义）。

---

## 8. 模型管理页：多 Provider/Model 注册 + 角色绑定 + embedding（子任务 F，#106）

### 8.1 本章定位

**F19 渲染层模型管理（0.4.0，前后端）**：多 Provider/Model 注册与配置界面 + 角色模型绑定 + embedding 模型管理。UI 设计基准 = PM 文档 §4.1 + 原型（`prototypes/client-ui-v1/` 模型管理页，用户确认）。

**关键事实（2026-08-05 后端盘点，源码核实）**：

- **多 provider = 模型字符串路由级**：`infrastructure/llm/provider_config.py` `LLMProviderConfig`（provider/api_key/base_url/default_model/models/max_retries/timeout）+ `_BUILTIN_PROVIDERS` 硬编码 4 个（**openai/deepseek/zhipu/ollama**——2026-08-06 源码核实，zhipu 仍在；anthropic 已按 ADR-005v2 移除）；`parse_model_string()` 统一 LiteLLM 格式 `provider/model`；**无持久化注册表、无 CRUD 端点**
- **⚠️ key 存储与调用链脱节（#106 必补缺口）**：`APIKeyManager`（`infrastructure/llm/key_manager.py`，AES-256-GCM，`data_dir/keys/{provider}.json`）仅被 settings 端点（store/探测）使用；`api/deps.py` 全部 `LangChainLLMClient()` 无参构造，key 只走环境变量——**存了 key 但环境变量未设 → 调用仍报 "API key not configured"**
- **每项目/每角色不同模型已天然支持**：model 为每次调用传入字符串（writing_service `request.model or project.config.model`；Agent 管线 `stage.agent.model` 每阶段独立）——唯一缺口是 api_key 来源
- **embedding 全局硬编码**：`core/config.py` `embedding_model="BAAI/bge-small-zh-v1.5"` + `deps.py` `get_vector_store()` 模块级单例；无项目级/用户级配置
- **PATCH 语义**：`PATCH /api/v1/projects/{project_id}`（`api/routers/project.py` L94）请求体 `ProjectUpdate`，config 字段整体替换（`project_service.update` `model_copy(update=exclude_unset)` 浅合并）

### 8.2 范围与设计（注册表实体方案，用户拍板 2026-08-05）

**用户拍板：Q1=B（完整注册表实体，不做轻量中间态）/ Q2=B（自定义 provider 持久化）/ Q3=A（embedding 本期仅注册展示）**——#106 直接落地持久化 ProviderConfig 注册表（原分级方案 C），与 §9 AgentTemplate 同为 0.4.0 配置域实体，架构一致。

**本章范围**：

1. **后端 ProviderConfig 实体**（按既有模块模式，7 NEW 文件 + 测试，参照 §9.2/§9.4 的 AgentTemplate 实体模式）：
   - `domain/models/provider_config.py`：`ProviderConfig = { id, name, base_url, default_model, models: [{id, type: chat|embedding, roles}], max_retries, timeout, created_at, updated_at }`（models 存 JSON 列，仿 ProjectORM.config）
   - `domain/ports/provider_config_repository.py` + `_errors.py` + `domain/services/provider_config_service.py` + `infrastructure/database/models/provider_config.py` + `infrastructure/database/repositories/provider_config_repo.py` + `api/routers/provider_configs.py`
   - **内置 seed**：建表时插入内置 4 provider（openai/deepseek/zhipu/ollama——2026-08-06 源码核实 `_BUILTIN_PROVIDERS` 实际 4 个，zhipu 仍在注册表；值来自 `_BUILTIN_PROVIDERS`）——注册表列表统一，无「内置 vs 自定义」双轨
   - MODIFY：`database/models/__init__.py`（导出）、`api/app.py`（注册 router）、`api/deps.py`（装配）
2. **provider 解析改造 + key 回退**（MODIFY `infrastructure/llm/provider_config.py`）：
   - `get_provider_config` 改为**先查注册表**（持久化 provider → base_url/default_model/models），注册表无则回退内置硬编码（兼容既有调用）
   - **APIKeyManager 已存 key 回退**：构造 LLM 客户端时若无环境变量 key，则查 `data_dir/keys/{provider}.json` 已存 key（打通「注册 → 调用」链路，盘点风险 1）
3. **前端模型管理页**（`pages/models.tsx`，原型落点）：Provider 列表（注册表数据 + 已存 key 徽标 + 模型数）；添加/编辑 Provider 弹窗（名称/预置模板/Base URL/API Key 加密存储/测试并保存）；删除（确认框，提示模型数）；模型表（ID/类型 chat-embedding/角色用途标记 + 多选一次性添加 + 行内/批量测试连接）；角色绑定区（默认模板：写作主模型 + 四角色 + RAG embedding）；设置页「模型」分类摘要 + 入口
4. **embedding（本章边界，Q3=A）**：模型管理页可注册/展示 embedding 模型（持久化）；**生效机制（项目级 embedding 配置）不在本章**（现为全局单例，改造 `get_vector_store` 注入链需 RAG 侧联动，标注「下一迭代」）
5. **顶栏主题/语言切换改造（2026-08-06 追加，方案 A 已拍板）**：右上角 `header-theme-toggle`/`header-lang` 循环按钮 → **Radix Select 下拉**（`header-theme-select`/`header-lang-select`，aria-label 沿用 `ap.theme`/`ap.lang`）。理由：循环按钮在选项增多时不可直达/不可扩展；下拉保留顶栏快捷切换能力（§7.2 顶栏职责不变），设置页常规分类 AppearanceCard 作为完整管理面（双通道）。**测试契约升级**：`App.header.test.tsx`（combobox 语义 + 选择触发 setTheme/setLang）+ E2E 顶栏断言检查（现有循环按钮断言升级为 Select 选择断言）

> 估算：3-5 → **5-7 人天**（注册表实体全链路：7 文件 + 解析改造 + key 回退 + 前端页 + 顶栏下拉改造）。

### 8.3 API 契约（新增）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/provider-configs` | GET/POST | Provider 注册表列表（含 key_saved + models）/新建（内置 seed 不可删） |
| `/api/v1/provider-configs/{id}` | GET/PATCH/DELETE | 详情（含 models）/更新/删除（删除确认由前端；被模型绑定引用时返回 used_by 提示） |
| `/api/v1/settings/llm-keys` | POST | 既有（#79），存 key 按 provider 名（复用） |
| `/api/v1/settings/llm/test` | POST | 既有（#79），连通探测（复用） |

> 本章不新增业务实体、不新增业务端点（与 F19 总声明一致；settings 为基础设施工具端点，先例 §4.9 Q3）。

### 8.4 文件结构（#106 CREATE/MODIFY）

| 操作 | 文件 | 内容 |
|------|------|------|
| NEW ×7 | 后端 ProviderConfig 实体（§8.2① 清单） | model/ports/errors/service/ORM/repo/router + 测试 + 内置 seed |
| MODIFY | `backend/src/inkflow/infrastructure/llm/provider_config.py` | `get_provider_config` 查注册表 + APIKeyManager 已存 key 回退 |
| MODIFY | `backend/src/inkflow/infrastructure/database/models/__init__.py` `api/app.py` `api/deps.py` | 导出/注册/装配 |
| NEW | `frontend/packages/renderer/src/pages/models.tsx` | 模型管理页（Provider 列表/模型表/角色绑定区） |
| NEW | `frontend/packages/renderer/src/components/ProviderDialog.tsx` | 添加/编辑 Provider 弹窗（预置模板/Base URL/Key/测试并保存） |
| MODIFY | `frontend/packages/renderer/src/stores/models.ts`（NEW）或 `stores/agent.ts` | provider/model 状态（内置列表 + 已存 key + 选中模型 + 角色绑定草稿） |
| MODIFY | `frontend/packages/renderer/src/App.tsx` | 路由 + 侧边栏「模型管理」入口（#105 导航接入）+ **顶栏主题/语言循环按钮 → Radix Select 下拉**（`header-theme-select`/`header-lang-select`，§8.2⑤） |
| MODIFY | `frontend/packages/renderer/src/App.header.test.tsx` | **测试契约升级**：循环按钮断言 → Select combobox 语义 + 选择触发 setTheme/setLang（§8.2⑤） |
| MODIFY | `tests/e2e/electron-pages.spec.ts` | E2E 顶栏断言升级：主题/语言选择交互（§8.2⑤） |
| MODIFY | `frontend/packages/renderer/src/i18n/zh.ts` `en.ts` | 模型管理文案（双语）+ 主题/语言选项 label（若 Select 需显式选项文案） |

### 8.5 测试策略

| 层次 | 关键场景 |
|------|----------|
| 后端单元 | ProviderConfig CRUD + 内置 seed；key 回退（环境变量缺失读 APIKeyManager）；`get_provider_config` 注册表优先 + 内置回退；被引用删除 used_by |
| 前端组件 | Provider 列表/添加弹窗（校验/测试连接成败 toast/保存）；模型多选 + 类型/角色标记；删除确认框；角色绑定下拉从已配置模型联动；**顶栏主题/语言 Select：combobox 语义（getByRole('combobox')）+ 选择触发 setTheme/setLang** |
| 集成（真实内核） | `POST /settings/llm-keys` 存 key → `GET /provider-configs` 回读 key_saved；`/settings/llm/test` 成败 |
| E2E | 顶栏主题/语言选择交互（升级现有循环按钮断言）；模型管理页导航入口可达 |
| 回归 | 既有前端 91+ 用例 + 后端全量测试零回归 |

### 8.6 验收标准（#106）

- **M1**（自动）后端：ProviderConfig CRUD + 内置 seed + key 回退链路（集成断言：无 env key 时 `LangChainLLMClient` 构造/调用解析 api_key == APIKeyManager 已存值，Fake LLMClient 注入，不依赖真实网络）+ `get_provider_config` 注册表优先
- **M2**（自动）Provider 增删改 + 测试连接成败 toast + 删除确认框
- **M3**（自动）模型多选保存 + chat/embedding 类型标记 + 角色用途去重徽标
- **M4**（自动）角色绑定 6 下拉（主模型/四角色/RAG embedding）从已配置模型联动
- **M4b**（依赖声明，评审 C3）角色绑定区保存依赖 #107 `PATCH /agent-templates/default`——**#107 先行或 #106/#107 同期合入**；若 #106 单独交付，绑定区只读展示 + 「保存需 Agent 模板功能」标注
- **M5**（自动）三层测试全绿（unit/integration/e2e）+ 既有用例零回归
- **M5b**（自动）顶栏主题/语言 Select：展开可见全部选项 + 选择直达生效 + 与设置页联动（改设置页后顶栏同步；combobox 语义断言 + setTheme/setLang 触发断言）
- **M6**（手动 + vision）模型管理页三主题截图走查 + Electron 生产模式可用

### 8.7 关键架构决策记录（#106）

| 决策 | 方案 | 理由 | 备选（否决） |
|------|------|------|--------------|
| 注册表实体（用户拍板 Q1=B/Q2=B） | ProviderConfig 实体 + CRUD + seed + 解析改造 | 自定义 provider 持久化（Q2=B 需求）；与 §9 AgentTemplate 同为 0.4.0 配置域实体，架构一致；注册 = 配置真源，刷新不丢 | 轻量 A+B（key 回退 + 只读端点，不满足自定义持久化，用户否决） |
| key 回退 = provider_config 层 | `get_provider_config` 无环境变量时查 APIKeyManager | 单一改造点覆盖全部调用链（deps 8 处无需改）；打通「注册→调用」链路 | 改 deps 每处构造（8+ 处散改，否决）；前端直持 key（安全红线，否决） |
| embedding 生效不在本章（Q3=A） | 本期仅注册/展示（持久化） | 全局单例改造（`get_vector_store` 注入链）需 RAG 侧联动；不阻塞模型管理主体 | 本期做项目级 embedding（RAG 注入链改造，超范围，否决） |
| 顶栏切换 = Select 下拉（2026-08-06 追加，方案 A 拍板） | `header-theme-toggle`/`header-lang` 循环按钮 → Radix Select（`header-theme-select`/`header-lang-select`） | 选项增多时循环按钮不可直达/不可扩展；下拉保留顶栏快捷切换（§7.2 顶栏职责不变）；设置页 AppearanceCard 为完整管理面（双通道）；Radix Select 已在 #98 引入（§5.6 Q1=A），零新依赖 | 保持循环按钮（现状，不可扩展）；顶栏只留指示、切换全移设置页（快捷能力丢失，否决） |

### 8.8 待澄清问题（≤3）

- **Q1 后端改动范围**：A. Phase 1 = key 回退 + GET /llm-providers（轻量，2 处小改）；B. 直接落地注册表实体（完整：ProviderConfig 表 + CRUD + 解析改造）。**✅ 已确认（用户拍板：选项 B，2026-08-05）**——完整注册表 = 自定义 provider 持久化（Q2）+ 模型管理闭环；与 §9 配置域实体架构一致；估算 5-7 人天。正文已按 B 修订（§8.2/§8.3/§8.4/§8.6/§8.7）。
- **Q2 自定义 provider（非内置）持久化**：A. 仅存 key（base_url/模型列表前端本地，刷新丢失）；B. 自定义 provider 配置持久化（注册表实体）。**✅ 已确认（用户拍板：选项 B，2026-08-05）**——自定义 provider（如本地 vLLM/Ollama 自定义端点）是真实场景；注册表持久化后刷新不丢。正文已按 B 修订（§8.2）。
- **Q3 embedding 模型来源**：A. 注册表可注册/展示 embedding 模型（本期不生效，标注「下一迭代接入」）；B. 本期打通项目级 embedding（RAG 注入链改造）。**✅ 已确认（用户拍板：选项 A，2026-08-05）**——注册持久化已包含；生效机制需 RAG 注入链联动，超本章。正文已按 A 修订（§8.2.4）。
- **Q4 顶栏主题/语言切换形态（2026-08-06 追加）**：A. Radix Select 下拉（`header-theme-select`/`header-lang-select`，展开可见全部选项、选择直达生效、与设置页联动）；B. 保持循环按钮（现状）；C. 顶栏移除切换、仅设置页管理。**✅ 已确认（用户拍板：选项 A，2026-08-06）**——循环按钮选项增多不可直达；下拉保留顶栏快捷能力，设置页为完整管理面（双通道）。正文已按 A 修订（§8.2⑤/§8.4/§8.5/§8.6/§8.7）。

---

## 9. Agent 模板：引用式 + 角色独立温度 + 风险确认（子任务 G，#107）

### 9.1 本章定位

**Agent/模型模板（0.4.0，前后端）**：命名模板 = 模型选择 + Agent 编排集合，项目引用模板（**引用式：模板修改 → 项目同步生效**），各 Agent 角色独立温度，保存/删除风险确认框。用户拍板（2026-08-05）：引用式（非快照）+ 保存风险确认 + 删除统一确认。为 F26+ 自定义 agent 工作流铺路。

**关键事实（2026-08-05 后端盘点，源码核实）**：

- **管线已有「模板 + 项目覆盖」两层结构**：`agent_service._merge_role_configs`（L154-212）以 `AgentRole` 管线模板为基础，`project_role_models` 非空即覆盖对应 stage 的 model——**AgentTemplate 实体 = 管线的可命名快照集合，与现有装配天然契合（引用式零额外机制）**
- `ProjectConfig.agent_*` 为 `str | None`（project.py L50-53）：null=未配置（用模板默认），字符串=模型名；**无「停用角色」语义**（管线固定 4 阶段不裁剪，前端开关只是 undefined/null 呈现差异）
- **PATCH config 浅合并**：`project_service.update` `exclude_unset` 顶层浅合并，config 字段整体替换——模板应用 = 快照整体 PATCH 可行
- **无 migration 工具**：`create_tables()` 仅 `Base.metadata.create_all`（新表直接建，旧表加列不 ALTER）→ **template_id 建议入 config JSON（零迁移）**
- **⚠️ 温度 0.7 哨兵 hack**：`agent_service` L188 `if agent.temperature == 0.7` 才用项目温度覆盖——角色独立温度必须重写此逻辑（盘点风险 3）
- **角色独立温度半具备**：`AgentRole.temperature`（`domain/ports/agent_pipeline.py` L50）已存在；缺口 = ProjectConfig 每角色温度字段 + 合并逻辑重写

### 9.2 范围与设计

1. **后端 AgentTemplate 实体**（按既有模块模式，7 NEW 文件 + 测试）：
   - `domain/models/agent_template.py`：`AgentTemplate = { id, name, description, main_model, default_temperature, roles: {arch/writer/auditor/reviser: {model, temperature, enabled}}, default_words, created_at, updated_at }`（roles 可仿 ProjectORM.config 存 JSON 列）
   - `domain/ports/agent_template_repository.py` + `_errors.py` + `domain/services/agent_template_service.py` + `infrastructure/database/models/agent_template.py` + `infrastructure/database/repositories/agent_template_repo.py` + `api/routers/agent_templates.py`
   - MODIFY：`database/models/__init__.py`（导出 ORM）、`api/app.py`（注册 router）、`api/deps.py`（装配）
2. **ProjectConfig 扩展**（MODIFY `domain/models/project.py`）：`template_id: str | None = None` + 每角色温度字段（`role_arch_temperature` 等或 `roles_temperature: dict`）——**入 config JSON，零迁移**
3. **引用式生效机制**：`agent_service` 装配时读项目 `template_id` → load 模板 → 模板 roles/模型/温度为基础 + 项目覆盖字段（model/temperature 非空即覆盖）——**运行时读模板 = 天然引用式（模板修改即生效）**；重写 0.7 哨兵 hack（`_merge_role_configs` 显式温度语义：None=跟随默认，非 None=独立温度）。**温度优先级链（评审 C1 定稿）**：内置模板值（pipeline_templates.py：architect=0.7/writer=0.8/auditor=0.5/reviser=0.6）→ 模板 roles[].temperature（None=跳过）→ 模板 default_temperature → 项目每角色温度（config 字段，非空即覆盖）→ 项目顶层 temperature（保底）。**旧项目（无 template_id）行为等价**：architect=项目顶层温度、其余=内置模板值（0.8/0.5/0.6）——即 §9.6 M3 回归对照物。AgentRole.temperature 类型 float → **float|None**（None=跟随默认；字段类型变更影响面 = `_merge_role_configs` + 管线模板定义）
4. **风险确认数据**：模板 CRUD 端点返回引用计数/项目列表（`GET /templates/{id}` 附 `used_by: [{id, name}]`，实现提示：SQLite `json_extract(config,'$.template_id')` 查询可行，§9.5 集成测试覆盖）；前端保存/删除被引用模板 → 确认框（原型已验证文案）。**删除落盘机制（评审 C2 定稿）**：删除被引用模板 = 确认后**级联清空引用项目 config.template_id**（一次写，回退默认模板装配）——不做 load 兜底（避免脏数据掩盖）
5. **前端**（#105 设置页「模板」分类落地）：模板列表（名称/描述/应用项目数徽标/设为默认）+ 新建/复制/编辑/删除 + 编辑弹窗（名称/描述/主模型/四角色行=模型下拉+独立温度滑杆+开关/默认温度）+ 新建项目对话框「Agent 模板」下拉（默认模板/已建模板）+ 项目设置显示应用模板（可切换）。**enabled 语义（评审建议 1 定稿）**：Phase 1 `enabled=False` = 该角色 model 不覆盖（用默认模型，呈现差异），编辑弹窗开关旁注明「关闭 = 该角色使用默认模型」；管线阶段裁剪语义明确留 Phase 2（与 §4.2.3 #79 开关呈现兼容，不引入裁剪能力）

### 9.3 API 契约（新增）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/agent-templates` | GET/POST | 模板列表/新建 |
| `/api/v1/agent-templates/{id}` | GET/PATCH/DELETE | 详情（含 `used_by` 引用列表）/更新/删除 |
| `/api/v1/agent-templates/{id}/duplicate` | POST | 复制（或前端读后 POST 新建） |
| `/api/v1/agent-templates/default` | GET/PATCH | 默认模板查询/设为默认 |

> 业务实体端点（非基础设施），走完整实体模式（deps 装配）；模板 CRUD 不触碰 F4 既有管线端点。

### 9.4 文件结构（#107 CREATE/MODIFY）

| 操作 | 文件 | 内容 |
|------|------|------|
| NEW ×7 | 后端 AgentTemplate 实体（§9.2.1 清单） | model/ports/errors/service/ORM/repo/router + 测试 |
| MODIFY | `domain/models/project.py` | ProjectConfig 加 `template_id` + 每角色温度字段（config JSON 零迁移） |
| MODIFY | `agent_service.py` | `_merge_role_configs` 重写（引用式装配 + 显式温度语义，移除 0.7 哨兵） |
| MODIFY | `database/models/__init__.py` `api/app.py` `api/deps.py` | 导出/注册/装配 |
| MODIFY | `frontend/.../pages/settings.tsx` | 模板分类面板（#105 框架上实现） |
| NEW | `frontend/.../components/TemplateDialog.tsx` | 模板编辑弹窗（角色独立温度滑杆等） |
| MODIFY | `frontend/.../components/NewProjectDialog.tsx` | Agent 模板下拉（#105 占位落地） |
| MODIFY | `frontend/.../stores/templates.ts`（NEW）+ `stores/project.ts` | 模板状态 + 项目 template_id 读写 |
| MODIFY | `frontend/.../i18n/zh.ts` `en.ts` | 模板文案（双语） |

### 9.5 测试策略

| 层次 | 关键场景 |
|------|----------|
| 后端单元 | 模板 CRUD + 设为默认；引用式装配（项目引用模板 → 管线 roles 来自模板）；项目覆盖优先；每角色独立温度生效（非 0.7 不被项目温度覆盖）；删除被引用模板返回 used_by |
| 前端组件 | 模板列表徽标/CRUD/弹窗（角色温度滑杆联动/保存）；被引用模板保存 → 风险确认框（列出项目名）确认/取消分支；删除确认统一；新建项目下拉 |
| 集成（真实内核） | 模板 CRUD 端点 + 项目 config template_id 回读 + used_by 引用计数 |
| 回归 | 既有后端全量（agent_service 重构影响面）+ 前端用例零回归 |

### 9.6 验收标准（#107）

- **M1**（自动）后端：模板 CRUD + 设为默认 + used_by 引用列表
- **M2**（自动）引用式：项目 template_id → 管线装配读模板；模板修改 → 项目生效（集成断言）
- **M3**（自动）角色独立温度：四角色各自温度生效；0.7 哨兵 hack 移除后无回归；**旧项目（无 template_id）装配行为等价**（architect=项目顶层温度、writer=0.8/auditor=0.5/reviser=0.6——评审建议 2）
- **M4**（自动）前端：模板列表徽标 + CRUD + 编辑弹窗（角色温度滑杆）+ 风险确认框（被引用保存/删除）确认/取消分支
- **M5**（自动）新建项目选模板 + 项目内切换
- **M6**（自动）三层测试全绿 + 既有用例零回归（尤其 agent_service 重构）
- **M7**（手动 + vision）设置-模板分类三主题截图走查

### 9.7 关键架构决策记录（#107）

| 决策 | 方案 | 理由 | 备选（否决） |
|------|------|------|--------------|
| 引用式（用户拍板） | 项目 config 存 template_id，运行时读模板装配 | 模板 = 配置真源，一次修改全局生效；为 F26+ 模板升级批量传播铺路；保存风险确认框显式暴露影响面 | 快照式（改模板不传播，与「配置真源」诉求不符，用户否决） |
| 生效机制 = 运行时读 | agent_service 装配时 load template | 天然引用式（改模板即生效）、无写放大、与现有 `_merge_role_configs` 两层结构契合 | 保存时批量写回项目 config（写放大 + 并发风险，否决） |
| template_id 入 config JSON | ProjectConfig.template_id 字段（JSON 列） | 无 migration 工具（create_all 不 ALTER 旧表），零迁移风险 | projects 表加列（需手工迁移，否决） |
| 角色独立温度 = 显式字段 | roles 温度非 None 即独立生效，None 跟随默认；重写 0.7 哨兵 | 0.7 哨兵 hack 使「恰为 0.7 的角色」无法独立配置（盘点风险 3）；显式语义清晰 | 保留哨兵 + 约定（脆弱，否决） |
| 默认模板 = 系统内置 | 内置模板不可删、可设为默认（跟随系统默认配置） | 新建项目零配置可用；防误删兜底 | 用户可删默认模板（新手路径风险，否决） |

### 9.8 待澄清问题（≤3）

- **Q1 项目级覆盖语义**：A. 模板应用后项目内仍可覆盖（model/temperature 非空即覆盖，灵活）；B. 引用后项目锁定模板（统一管理）。**✅ 已确认（用户拍板：选项 A，2026-08-05）**——与现有 `project_role_models` 覆盖结构一致，兼容既有 #79 行为。正文已按 A 修订（§9.2.3）。
- **Q2 默认模板实体化**：A. 默认模板 = 系统内置模板记录（模板表首行，不可删）；B. 默认模板 = 虚拟概念（无 template_id 时回退当前全局默认配置，不落表）。**✅ 已确认（用户拍板：选项 A，2026-08-05）**——实体化后「设为默认/应用项目数」统计统一。正文已按 A 修订（§9.2.5）。
- **Q3 模板删除被引用项目**：A. 允许删除但确认框提示（删除后项目回退默认模板）；B. 阻止删除（须先解除引用）。**✅ 已确认（用户拍板：选项 A，2026-08-05）**——提示 + 回退默认，避免死锁。正文已按 A 修订（§9.3 DELETE 语义）。

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|----------|
| 打包分发（PyInstaller exe / NSIS / 便携 ZIP） | #48，0.4.0（用户拍板维持 ADR-019 v2） |
| 云端远程模式（base URL + JWT） | 2.0.0，ADR-024（本章只做本地 token，契约预留 header 位） |
| SSE 后端端点 | F23 ✅ 已交付（PR #83）；本章只保证 token 中间件不破坏 SSE 流（校验在流开始前完成） |
| 内核生命周期管理（拉起/崩溃拉起/回收） | #78 Electron 壳（本章只保证内核侧能力：stdout/端口文件交付 + 可被 kill 回收） |
| 富文本/Markdown 渲染与导出 | 0.6.0 F21 导出联动（§4.1 边界声明；编辑器形态见 §4.10 Q1） |
| 云端远程模式 UI（base URL + JWT） | 2.0.0，ADR-024（§4.4 client 预留 baseURL 注入位） |
| LLM 连接测试端点 | ✅ #79 交付（Q3 拍板：settings/llm-keys + settings/llm/test 工具端点，§4.6） |
| 业务 API 新增/修改 | 无（F19 不新增业务端点） |

## 11. 依赖关系

| 依赖 | 状态 | 说明 |
|------|------|------|
| F23 SSE（#50） | ✅ PR #83 | token 中间件需放行带 `X-InkFlow-Token` 的 SSE POST 请求（校验在流开始前） |
| F1-F16 业务 API | ✅ | /api/v1/* 全部经 token 中间件；业务层零改动 |
| ADR-021 | ✅ | 本章交付口径 = serve 强化版 |
| #78 Electron 壳 | ✅ 已起草（§3，v1.1） | 依赖 §2.1 交付格式（INKFLOW_READY + 端口文件，PR #85 已合入）；依赖 frontend workspace 前置落盘（feat/f19-gui-ui） |
| #79 渲染层 | ✅ 已合入（§4） | 依赖 #50 ✅（F23 SSE PR #83）+ #77（token/CORS 契约）+ #78（INKFLOW_API 注入） |
| #98 UI 打磨 | ✅ 本章（§5） | 依赖 #79 ✅ 渲染层合入（在其上纯前端打磨，零后端依赖） |

**编号口径声明**：旧文档中指向「F19 桌面端」的 0.4.0 编号已按 ADR-019 v2 拆分为 0.3.0 GUI（#77/#78/#79）+ 0.4.0 打包（#48），本章以 ADR-019 v2 为准。

## 12. 关键架构决策记录（#77）

| 决策 | 方案 | 理由 | 备选（否决） |
|------|------|------|--------------|
| 交付契约 = stdout 行 + 端口文件双通道 | INKFLOW_READY JSON 行 + `--port-file` JSON 文件 | 壳可流式解析 stdout 立即获得端口；文件便于崩溃拉起后重读（幂等）；JSON 可扩展（ADR-021「stdout / 端口文件」双交付口径） | 仅端口文件（启动竞态：壳需轮询文件出现）；仅 stdout（壳重启/崩溃拉起后信息丢失） |
| token 校验 = 中间件 + env 注入，**无豁免端点（除静态文档）** | `INKFLOW_SERVER_TOKEN` env + `X-InkFlow-Token` 头，全部端点强制（Q2 评审翻转：/health 不豁免） | 中间件零侵入业务路由；env 注入绕开 config 单例启动时序；reload 子进程可继承；契约统一（壳轮询 token 零成本——端口与 token 同处 INKFLOW_READY 行）；封堵 DNS rebinding 端口探测通道 | config.py 字段（启动时序耦合、CLI 测试需改 config）；每路由 dependency（侵入式、易漏）；/health 豁免（契约例外 + 探测通道，评审否决） |
| WAL 位置 = 连接工厂统一处 | `core/database.py` connect 事件 PRAGMA | 所有进程（CLI/agent/GUI/MCP）一次生效；ADR-021 多客户端并发前提 | 仅 serve 启动时 PRAGMA（其他入口进程无 WAL，违背并发基线） |
| CORS = config 白名单 | `server_cors_origins` 默认本地源 + null | Electron file:// 生产模式 Origin=null；可配置化避免硬编码（现状 4 个硬编码） | 保持硬编码（Electron 生产模式会 CORS 失败） |
| reload 与交付契约互斥、token 保持启用 | reload 不输出 INKFLOW_READY/端口文件；token 校验不降级（Q3 评审修正） | reload 子进程端口漂移 → 交付契约无法消费；token 经 env 继承零成本，开发模式不降级安全基线 | reload 禁用 token 校验（安全基线无谓降级，评审否决）；reload 与 --port-file 互斥报错（开发模式过约束） |

## 13. 待澄清问题（≤3）

- **Q1 端口文件路径默认值**：A. 仅显式 `--port-file`（缺省不写文件，stdout 唯一默认通道）——壳必须传路径，契约最明确；B. 缺省写 `{data_dir}/serve.json`——壳零参数，但 data_dir 权限/并发（多实例）需处理；C. 缺省写系统临时目录 `{tempdir}/inkflow-serve.json`。**✅ 已确认（用户拍板：选项 A，2026-08-03）**——消费方唯一性论证：端口文件唯一消费方是 #78 壳，而壳自身 spawn 内核并传参，显式传路径零额外成本；B/C 的缺省路径引入多实例冲突与轮询竞态，收益为零。正文已按 A 修订（§2.1.2 缺省不写文件、仅 stdout）。
- **Q2 /health 是否豁免 token**：A. 豁免（健康检查无敏感数据，壳轮询/运维 curl 方便）；B. 全部强制（严格基线，壳先解析 INKFLOW_READY 拿 token 再轮询）。**✅ 已确认（用户拍板：选项 B，2026-08-03）**——原建议 A 存在认知偏差：「壳轮询方便」不成立——端口与 token 同在 INKFLOW_READY 行，壳解析该行是必经步骤，token 是免费副产品，轮询带 token 零成本；豁免收益仅剩「运维 curl 探测」（本地单机无真实运维场景），代价却是契约例外 + DNS rebinding 端口探测通道 + 测试双分支。/docs /redoc /openapi.json 为静态文档仍豁免，配全局 HTTPBearer scheme（Swagger UI Authorize 按钮，兼作 ADR-024 云端 JWT 前置）。正文已按 B 修订（§2.1.3/§2.3.1/§2.6/§2.7/§10）。
- **Q3 --reload 与 token 交付**：A. reload 模式下禁用 token 校验 + 不输出 INKFLOW_READY（开发热重载仅本机，语义最简）；B. reload 时 env 注入 token 让子进程继承（token 跨 reload 稳定）；C. `--reload` 与 `--port-file/--token` 互斥报错。**✅ 已确认（用户拍板：选项 A 修正，2026-08-03）**——交付契约与 reload 互斥（不输出 INKFLOW_READY、不写端口文件，reload 子进程端口漂移无法消费）成立，但「禁用 token 校验」是安全基线无谓降级：token 经 env 注入、reload 子进程天然继承，校验保持启用零成本。最终语义：**reload 与交付契约互斥 + token 校验保持启用**（§2.2 表格与 §10 决策表已同步）。
