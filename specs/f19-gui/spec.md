# F19: GUI（内核进程化 + Electron 壳 + React 渲染层）— 功能规格

> **Spec 版本**: 1.0（草案，仅 §2 内核进程化章节；§3/§4 占位待对应子任务起草） | **日期**: 2026-08-03 | **依据**: PRD v2.1, Constitution P1-P6, ADR-003/004/011/019(v2)/020/021/025
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

## 3. Electron 壳（子任务 B，#78）— 占位

> 待 #77 合入后起草。依赖 §2.1 交付契约（INKFLOW_READY 行 + 端口文件 {port, token}）。
> 内容预告：主进程 spawn 内核 → 行缓冲解析 → 健康轮询（指数退避 1s→2s→4s→30s 封顶）→ 崩溃拉起 → 退出回收（child.kill + Job Object）；`contextIsolation:true` + `nodeIntegration:false` + preload 注入 token；ELECTRON_MIRROR=npmmirror。文件结构：`frontend/packages/electron/`（main/preload + electron-builder.yml 占位）。

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
| #78 Electron 壳 | ⏳ 下游 | 依赖 §2.1 交付格式（INKFLOW_READY + 端口文件） |
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
