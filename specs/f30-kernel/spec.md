# F30: 内核冷启动基建（kernel_bootstrap）— 功能规格
> **端**: backend

> **Spec 版本**: 1.1 | **日期**: 2026-08-07 | **依据**: ADR-030（本地内核服务化 ②）、ADR-021（内核进程化交付契约）、Constitution P1-P6
>
> **Spec 变更**（1.0 → 1.1）: Q1-Q3 全部拍板（2026-08-07 用户选 A/A/A）——Q1 冷启动超时默认 30s + env `INKFLOW_KERNEL_TIMEOUT` 覆盖；Q2 版本校验 major 相同即复用；Q3 保留 `inkflow kernel status` 调试命令（dev 标注）
>
> **所属阶段**: 0.5.0 Agent 集成（本地内核服务化三件套第 1 个模块，估算 3-4 人天）
>
> **关联 Issues**: #166（本模块）；#167（GUI 托盘，**依赖本模块**）；#168（CLI 产物，**依赖本模块**）；#169（CLI 恒 HTTP，**依赖本模块**）；#49（F20 MCP，**依赖本模块**）
>
> **依赖**: ✅ F19（serve 命令 + INKFLOW_READY 交付契约 + `--port-file` 原子写入）· ✅ F1（config.data_dir = %APPDATA%\InkFlow）· ⏳ 无
>
> **参考 ADR**: [ADR-030](../../adr/kernel/ADR-030.md)（本地内核服务化：kernel.json + ensure_kernel）· [ADR-021](../../adr/kernel/ADR-021.md)（内核进程化：INKFLOW_READY/端口文件/token）· [ADR-019](../../adr/packaging/ADR-019.md)（版本里程碑）
>
> **状态**: ✅ 已实现（PR #171，#166 2026-08-08）

---

## 1. 概述

F30 内核冷启动基建为 InkFlow 提供**统一的内核发现与拉起协议**：任何客户端（GUI 壳 / CLI 命令 / MCP server / skills 封装）在访问内核前调用 `ensure_kernel()`——读状态文件判断内核是否存活（复用）或互斥拉起新内核（冷启动），从而让「外部 agent 经 MCP/skills 调用 InkFlow 写作」（ADR-030 愿景）具备确定性交付形态。

### 1.1 模块类型定位（第 13 变体：客户端发现型）

按 AGENTS.md 模块类型谱系计数（f15=6 / f16=7 / f23=8 / f19=9 / f26=10 / f24=11 / f25=12(已移除)），本模块为 **第 13 变体「客户端发现型」**，特征：

```
F19 serve（内核交付契约）  ×  config.data_dir（%APPDATA%\InkFlow）  ×  Windows 进程控制（CreateMutexW）
        └──────────────────▶  kernel.json 状态文件 + ensure_kernel() 拉起器
```

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ **无**（状态文件 = 运行时发现协议，非业务实体） |
| 新 API 端点 | ❌ 无（纯客户端侧基建；/health 复用既有） |
| 新 CLI 命令 | ❌ 无（ensure_kernel 是内部库函数，被 CLI 顶层/MCP/GUI 消费） |
| 核心机制 | ✅ kernel.json 状态文件 + ensure_kernel()（复用/互斥拉起/stale 清理） |
| 跨模块 MODIFY | ✅ F19 serve 零改动（复用既有 --port-file/INKFLOW_READY）；本模块新增 `infrastructure/kernel/` 目录 |
| 错误面 | 无 HTTP 错误面（库函数返回 KernelHandle / 抛 KernelStartupError） |

### 1.2 边界声明

- 本模块**不做** CLI 恒 HTTP 路由改造（归 #169）——只提供「拿到 {port, token}」的基建
- 本模块**不做** GUI 托盘（归 #167）——托盘消费 ensure_kernel 但实现独立
- 本模块**不做** CLI 独立打包（归 #168）——打包复用本模块的 spawn 定位逻辑
- 本模块**不做**内核空闲回收/自动退出（ADR-030 D2=A：常驻到显式退出）

---

## 2. 数据模型

**无业务实体**。唯一新增的持久化数据 = **内核状态文件** `%APPDATA%\InkFlow\kernel.json`（config.data_dir 下，与 F19 端口文件同域）。

### 2.1 kernel.json 状态文件契约

| 字段 | 类型 | 必填 | 含义 |
|------|------|------|------|
| `port` | int | 是 | 内核监听端口（127.0.0.1） |
| `token` | str | 是 | 鉴权 token（X-InkFlow-Token 头） |
| `pid` | int | 是 | 内核进程 PID（存活校验用） |
| `version` | str | 是 | 内核版本（客户端版本兼容校验） |
| `started_at` | str | 是 | ISO8601 启动时间（UTC） |

**写入规则**：
- 原子写入（临时文件 + `os.replace`，复用 serve.py `_write_port_file` 模式）——防并发读半截 JSON
- 权限：`%APPDATA%` 用户私有目录（Windows 默认 ACL 仅当前用户可读）
- 仅**内核进程自身**写（serve 启动完成时）；客户端只读不写（防竞态）

**读取规则（客户端视角）**：
- 文件不存在 / JSON 解析失败 → 视为「无内核」
- 文件存在但 pid 不存在（进程已死）→ **stale** → 清理（重命名备份）→ 视为「无内核」
- 文件存在且 pid 存活 → 调 `/health`（带 token）→ 200 = 复用；非 200/超时 = stale 清理

### 2.2 KernelHandle（进程内返回对象）

```python
@dataclass(frozen=True)
class KernelHandle:
    port: int
    token: str
    pid: int
    version: str
    started_at: datetime
    reused: bool  # True=复用已有内核；False=本进程拉起
```

### 2.3 决策论证表

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **状态文件 %APPDATA%（选定）** | 与 config.data_dir 同域；用户私有；跨进程共享（任何客户端可读）；文本格式可调试 | 需处理并发写读竞态（原子写 + 只读方容忍） | ✅ 选定——端口/token 交付的持久化形态（F19 stdout 只对 spawn 方可见，无法跨客户端） |
| 固定端口 + 固定 token | 客户端零发现逻辑 | 端口冲突；token 固定 = 弱安全；多内核并存冲突 | ❌ 否决（F19 已定动态端口 + 随机 token） |
| 环境变量共享 | 简单 | 进程间不继承（新拉起的内核无法传回 CLI）；重启丢失 | ❌ 否决（跨进程语义缺失） |
| 每次 spawn 新内核 | 无状态管理 | 每次冷加载 chromadb（~4.7s）+ 多内核 SQLite 竞争 | ❌ 否决（ADR-030 D2=A 常驻语义） |

---

## 3. API 契约

**无新增 API 端点**。本模块消费既有 `/health`（F19 已实现，需 token 校验——ADR-021 契约定：env 未设置时直通，但内核运行中 token 必有效）。

### 3.1 消费的既有契约

| 方法 | 路径 | 用途 | 归属 |
|------|------|------|------|
| GET | `/health` | 内核存活探测（带 X-InkFlow-Token，200 = 活） | F19（已实现） |

### 3.2 库函数契约（ensure_kernel）

```python
async def ensure_kernel(
    *,
    spawn_cmd: list[str] | None = None,   # 覆盖 spawn 命令（测试注入 / 自定义内核路径）
    timeout: float = 30.0,                 # 冷启动等待超时（秒）
    health_timeout: float = 2.0,           # /health 探测超时（秒）
    state_file: Path | None = None,        # 覆盖状态文件路径（测试注入）
    version_check: bool = True,            # 版本兼容校验（CLI 与内核版本 major 不同 → 拒绝复用）
) -> KernelHandle:
    """确保内核运行并返回其访问句柄。"""
```

**行为**：
1. 读 kernel.json → 三态判定（§2.1 读取规则）
2. **复用**：pid 存活 + /health 200 + 版本兼容 → 返回 `KernelHandle(reused=True)`
3. **拉起**（无内核/stale）：
   - `CreateMutexW("InkFlowKernelBootstrap")` 获取互斥（错误码 183 = 已有实例在拉起 → 走等待路径）
   - 获取成功 → 定位 spawn 命令（§5.1）→ `subprocess.Popen`（无窗口 CREATE_NO_WINDOW，pythonw 语义）→ 读 stdout 解析 INKFLOW_READY → 校验 port/token → 写 kernel.json → 返回 `KernelHandle(reused=False)`
   - 获取失败（183）→ 轮询 kernel.json（≤ timeout）直至可用 → 返回复用
4. **stale 清理**：判定 stale 后先重命名 `kernel.json.stale-<ts>`（保留现场）再继续

**异常**：冷启动超时 / INKFLOW_READY 解析失败 / 内核秒退 → 抛 `KernelStartupError`（含日志指引 `%TEMP%\inkflow-kernel.log`）

---

## 4. CLI 命令签名

**无新增 CLI 命令**——ensure_kernel 由既有 CLI 顶层消费（#169 落地恒 HTTP 时接线）。本模块只交付库 + 一个内部调试命令（可选，dev 验证用）：

```bash
inkflow kernel status    # 调试命令：输出内核状态（运行中 PID/端口/版本 或 未运行）
```

> 该命令**非用户面**（帮助文本标注 dev），主要供集成测试与排障；`--json` 信封遵循 F7 约定（`{"ok": true, "data": {...}}`，未运行 = `{"ok": true, "data": {"running": false}}` 退出码 0——状态查询不因未运行而失败）。

---

## 5. 冷启动协议（关键差异：发现 + 互斥 + 拉起 + 生命周期）

### 5.1 模式总览

```
任何客户端（CLI/GUI/MCP/skills）
        │
        ▼
  ensure_kernel()
        │
        ├── 读 kernel.json ──▶ pid 存活 + /health 200 ──▶ 复用 KernelHandle
        │         │                    │
        │         │ stale              │ 失败/超时
        │         ▼                    ▼
        │   清理 stale           CreateMutexW 互斥
        │                          │
        │               ┌─────────┴─────────┐
        │               │ 183(已有)          │ 获取成功
        │               ▼                    ▼
        │        轮询 kernel.json     spawn 内核（serve --port 0）
        │        ≤ timeout 等待        │
        │               │            读 stdout → INKFLOW_READY
        │               │            校验 → 写 kernel.json
        │               └────────▶ 返回 KernelHandle
```

### 5.2 内核 spawn 命令定位（多形态）

| 形态 | 命令 | 判定 |
|------|------|------|
| 源码/venv 开发 | `python -m inkflow serve --port 0 --port-file <tmp>` | `sys.frozen == False` |
| CLI 打包产物 | `inkflow.exe serve --port 0 --port-file <tmp>` | `sys.frozen == True` + 可执行文件自身 |
| GUI 内置内核 | `resources/kernel/inkflow.exe serve --port 0 --port-file <tmp>` | GUI 壳传入 `spawn_cmd` 覆盖（kernel.ts isPackaged 分支复用） |

**关键点**：`--port-file` 由 ensure_kernel 传入临时路径——**不依赖 stdout 解析**（更稳：端口文件原子写入 + 无 stdout 缓冲问题）；INKFLOW_READY 解析作为双保险（等待任一先到）。

### 5.3 竞态防护（双客户端同时冷调用）

| 场景 | 防护 |
|------|------|
| 两个 CLI 同时 ensure_kernel（无内核） | CreateMutexW 互斥：一个获取成功拉起，另一个 183 → 轮询等待（≤ timeout）→ 复用 |
| 拉起中内核崩溃 | 轮询方超时 → KernelStartupError；拉起方捕获 spawn 失败 → 清理 → 重试（≤2 次） |
| 拉起方写完 kernel.json 前另一客户端读到旧文件 | stale 判定（pid 不存在）→ 等待互斥 → 复用新文件 |

### 5.4 版本兼容校验

- `kernel.json.version` 与客户端版本（`inkflow.__version__`）**major 相同** → 复用
- major 不同（内核旧/新于客户端）→ 视为 stale 清理 + 拉起匹配版本内核（仅当客户端能 spawn 自己版本的内核）
- 说明：minor/patch 差异容忍（API 向后兼容，ADR-019 契约冻结语义）

### 5.5 生命周期语义（ADR-030 D2=A）

- 内核**常驻到显式退出**：ensure_kernel 拉起的进程不随调用方退出（`Popen` 不 wait，detach 语义——Windows 上需 `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` + 父进程退出不影响子进程）
- 显式退出控制面：GUI 托盘「退出」（#167）/ 未来 `daemon stop` 语义——本模块不实现
- 不做空闲超时回收（ADR-030 否决项）

---

## 6. 组织规则

### 6.1 状态文件位置与生命周期

- 路径：`config.data_dir / "kernel.json"`（打包 = `%APPDATA%\InkFlow\kernel.json`；dev = 默认 data_dir）
- 生命周期：内核启动 → 写；内核退出 → **不主动删**（stale 判定由读取方处理——崩溃场景无清理方，读取方判定更可靠）
- 多内核并存：**禁止**（单实例语义，互斥锁 + 状态文件唯一路径保证）

### 6.2 日志

- ensure_kernel 操作日志：`%TEMP%\inkflow-kernel.log`（追加：启动/复用/stale 清理/失败，带时间戳）——与调度器日志（F25 已移除）无关，纯冷启动排障
- 内核自身日志：serve 输出重定向到该文件（`Popen(stdout=log_file, stderr=STDOUT)`）——冷启动失败可查死因

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| 1 | kernel.json 不存在 | 视为无内核 → 互斥拉起 |
| 2 | kernel.json 损坏（JSON 解析失败） | 视为无内核 → 重命名 `.stale-<ts>` → 拉起 |
| 3 | kernel.json 存在但 pid 不存在（崩溃残留） | stale → 清理 → 拉起 |
| 4 | pid 存在但 /health 超时/非 200 | stale → 清理 → 拉起（token 失效/端口被占场景） |
| 5 | 两个客户端同时冷调用 | 互斥 183 → 轮询等待 → 复用（§5.3） |
| 6 | 冷启动超时（> timeout） | KernelStartupError + 日志指引 |
| 7 | 内核秒退（spawn 后立即退出） | 捕获进程退出 → 清理 → 重试 ≤2 次 → 失败抛错 |
| 8 | INKFLOW_READY 与端口文件都未到达 | 超时抛错（双保险都失败 = 内核异常） |
| 9 | 版本 major 不匹配 | 拒绝复用 → 清理 → 拉起匹配版本 |
| 10 | spawn 命令不存在（CLI 打包缺 serve） | KernelStartupError（明确提示「CLI 产物缺失 serve 能力」） |
| 11 | %APPDATA% 不可写 | KernelStartupError（权限问题，日志记录路径） |
| 12 | 内核已运行但由其他进程拉起（非本模块） | 状态文件存在 + pid 存活 + /health 200 → 正常复用（不关心拉起方） |

---

## 8. 文件结构

遵循 ADR-007v2 包结构，与真实源码树一一对应：

```text
backend/src/inkflow/
├── infrastructure/
│   └── kernel/                        ← CREATE: 冷启动基建目录
│       ├── __init__.py                ← CREATE: 导出 ensure_kernel / KernelHandle / KernelStartupError
│       ├── state.py                   ← CREATE: kernel.json 读写（原子写/三态读取/stale 清理）
│       ├── bootstrap.py               ← CREATE: ensure_kernel 实现（互斥/拉起/轮询/版本校验）
│       └── kernel_errors.py           ← CREATE: KernelStartupError
├── cli/
│   └── commands/
│       ├── kernel.py                  ← CREATE: kernel status 调试命令（dev 标注）
│       └── __init__.py                ← MODIFY: 导出 kernel 命令
│   └── app.py                         ← MODIFY: 注册 kernel 命令组（dev 命令不影响用户面）
└── (api/ domain/ 零新增——纯客户端基建)

backend/tests/
├── unit/
│   ├── test_kernel_state.py           ← CREATE: kernel.json 读写三态（无/存活/stale）+ 原子写
│   ├── test_kernel_bootstrap.py       ← CREATE: ensure_kernel 复用/拉起/互斥 183/超时/重试（mock Popen）
│   └── test_kernel_version.py         ← CREATE: 版本校验（major 不匹配拒绝复用）
└── cli/
    └── test_cli_kernel.py             ← CREATE: kernel status 命令（信封/退出码）
```

> **CI 盲区防范**：`tests/cli/test_cli_kernel.py` 必须显式加入 ci.yml `integration-cli-backend` job 文件列表（Issue #59/#61 教训）；unit 测试由 `pytest tests/unit/` 自动覆盖。

---

## 9. 测试策略

### 测试层次

```text
单元测试: state.py 三态读写（原子写/损坏容忍/stale 判定）      ~8 cases
单元测试: bootstrap.py（mock Popen + mock 状态文件）          ~14 cases
   - ensure_kernel 复用（pid 活 + health 200 → 不 spawn）
   - ensure_kernel 拉起（无状态 → spawn → 端口文件 → 返回）
   - 互斥 183（已有实例 → 轮询 → 复用）
   - 超时抛 KernelStartupError / 秒退重试 ≤2 / 版本 major 不匹配
单元测试: 版本校验                                                      ~3 cases
CLI 测试: kernel status（信封/退出码/未运行语义）              ~4 cases
```

### 关键测试场景

1. **复用路径**：预置 kernel.json（pid 用当前进程 + 指向 mock health 200）→ ensure_kernel 返回 `reused=True` 且不调用 Popen
2. **拉起路径**：无 kernel.json → Popen mock 模拟 INKFLOW_READY → 断言 kernel.json 写入正确字段
3. **互斥路径**：mock CreateMutexW 返回 183 → 断言进入轮询（不放 Popen）→ 第二客户端读到首个客户端写入的状态 → 复用
4. **stale 清理**：pid 不存在 → 断言状态文件被重命名为 `.stale-<ts>` → 拉起新内核
5. **竞态**：并发调 ensure_kernel（asyncio.gather 2 个）→ 只 spawn 一次
6. **失败路径**：spawn 后立即退出（mock returncode）→ 重试 ≤2 → KernelStartupError
7. **版本**：kernel.json version 1.2.0 vs 客户端 2.0.0 → 拒绝复用

### 覆盖率目标

模块行覆盖 ≥ 80%、全仓 ≥ 60%；**当前全仓门禁 ADR-027：后端 98.5/95.0**——本模块新增代码必须同步补测维持门槛（QA 阶段主 agent 全仓跑 `uv run ruff check src/ tests/unit/ ../tests/` + `pytest` + `check_coverage.py 98.5 95.0`）。

---

## 10. 不在范围内

| 项 | 原因 | Phase 归属 |
|----|------|-----------|
| CLI 恒 HTTP 路由改造 | ensure_kernel 是基建；路由改造是消费方改造 | #169（0.6.0） |
| GUI 托盘常驻/关闭行为 | 独立前端模块 | #167（0.5.0） |
| CLI 独立发布产物 | 打包工程，复用本模块 spawn 定位 | #168（0.5.0） |
| MCP server 薄客户端 | 消费 ensure_kernel | F20（1.0.0） |
| 内核空闲回收/自动退出 | ADR-030 D2=A：常驻到显式退出 | 永不（除非用户反转拍板） |
| 开机自启 | 用户环境配置差异；发布包统一处理 | 发布包/1.0.0 |
| kernel.json 加密 | %APPDATA% 用户私有 ACL 已够（本地威胁模型） | 永不 |
| 多内核并存/负载均衡 | 单实例语义（互斥锁） | 永不 |

---

## 11. 依赖关系

```text
F30 依赖:
  F19（serve）       — INKFLOW_READY + --port-file 交付契约（复用，零改动）
  F1（config）       — data_dir 定位 kernel.json
  F7（CLI 约定）     — kernel status 信封/退出码

F30 被依赖:
  #167（GUI 托盘）   — 启动时复用内核（读 kernel.json 健康则直接连接）
  #169（CLI 恒 HTTP）— ensure_kernel 作为 CLI 顶层接线
  #168（CLI 产物）   — spawn 定位复用
  F20（MCP）         — MCP 薄客户端冷启动
```

**编号口径声明**：本模块为 ADR-030 落地拆分的基建 issue（#166），非 PRD F 系列业务模块——采用「F30」编号承接（F25 已移除不复用，F26-F29 为 Agent 化升级规划），模块类型谱系第 13 变体「客户端发现型」。若与未来编号冲突以 ADR-019 v5+ 为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|-------------|
| 1 | 状态文件存 %APPDATA%\InkFlow\kernel.json | config.data_dir 下，原子写 | 用户私有 + 与配置同域 + 跨进程共享；F19 stdout 契约只对 spawn 方可见 | 固定端口/token（冲突+弱安全）；环境变量（不跨进程） |
| 2 | 内核自己写状态文件，客户端只读 | serve 启动完成时写 | 写方唯一（防竞态）；客户端读失败 = stale 可判定 | 客户端写（多写方竞态复杂） |
| 3 | CreateMutexW 互斥拉起 | 183 → 轮询等待 | 防双 spawn（Windows 原生互斥，无文件锁残留问题） | 文件锁（崩溃残留锁文件需清理）；端口预占探测（竞态窗口） |
| 4 | --port-file 为主 + INKFLOW_READY 双保险 | 传临时端口文件路径 | 端口文件原子写比 stdout 解析稳（无缓冲/多行问题） | 仅 stdout（F19 壳实践但 CLI 解析更脆弱） |
| 5 | stale 由读取方判定 + 备份重命名 | `.stale-<ts>` | 崩溃场景无清理方，读取方判定可靠；备份保留现场可排障 | 内核退出时主动删（崩溃残留无法覆盖） |
| 6 | 版本 major 校验 | major 不同拒绝复用 | 契约冻结语义（ADR-019）：major 变更 = 破坏性 | 无条件复用（旧内核 + 新客户端 = 契约漂移） |
| 7 | 内核 detach（不随调用方退出） | CREATE_NEW_PROCESS_GROUP + 不 wait | ADR-030 D2=A 常驻语义；CLI 退出后内核保持供 agent 下次调用 | 随调用方退出（每次冷启动，违背服务化） |
| 8 | 无新 API/无新业务 CLI | 仅库 + dev 调试命令 | 纯基建（YAGNI）；消费方各自接线 | 独立 HTTP 控制面（无消费方） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | state.py 三态读写 + 原子写 | `pytest tests/unit/test_kernel_state.py -v` 全绿 |
| M2 | bootstrap.py 复用/拉起/互斥/超时/重试 | `pytest tests/unit/test_kernel_bootstrap.py -v` 全绿 |
| M3 | 版本校验 | `pytest tests/unit/test_kernel_version.py -v` 全绿 |
| M4 | CLI kernel status（信封/退出码） | `pytest ../tests/cli/test_cli_kernel.py -v` 全绿（且已追加 ci.yml integration-cli-backend job） |
| M5 | 手工验证：无内核 → ensure_kernel 拉起 → kernel.json 写入 → 二次调用复用（pid 不变） | 手工验证（`python -c "import asyncio; from inkflow.infrastructure.kernel import ensure_kernel; ..."` 两次调用比对 pid） |
| M6 | 手工验证：kill 内核 → 残留 kernel.json 被判定 stale → 重新拉起 | 手工验证（Start-Process 内核 → Stop-Process → ensure_kernel → 新 pid） |
| M7 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；覆盖率达 ADR-027 门槛（98.5/95.0）；`uv run ruff check src/ tests/unit/ ../tests/` + mypy 通过 |

> Issue #166 验收标准映射：kernel.json 写入正确 = M1/M5；复用不 spawn = M2/M5；双客户端只一个内核 = M2（互斥用例）；崩溃残留 stale 清理 = M1/M6。

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 结论 |
|---|------|------|------|
| Q1 | 冷启动**默认等待超时**取多少？spec 设计为 30s（内核冷启动含 chromadb/BGE 加载，实测 ~4.7s 但打包后可能更慢）；是否需要可配置（env `INKFLOW_KERNEL_TIMEOUT`）？ | 影响 agent 调用体验（超时 = 明确报错 vs 无限等待） | ✅ 已确认（用户拍板 2026-08-07：选项 A）——**默认 30s + env `INKFLOW_KERNEL_TIMEOUT` 覆盖**（§3.2 timeout 参数读取 env） |
| Q2 | **版本校验严格度**？spec 设计为 major 相同即复用（minor/patch 容忍）；是否要 `>=` 客户端版本（内核必须不旧于客户端）？ | 影响契约漂移风险 vs 复用率 | ✅ 已确认（用户拍板 2026-08-07：选项 A）——**major 相同即复用**（§5.4） |
| Q3 | `kernel status` 调试命令是否保留？spec 设计为保留（dev 标注）；或 MVP 不提供（纯库，靠测试验证）？ | 影响调试面 vs 最小面 | ✅ 已确认（用户拍板 2026-08-07：选项 A）——**保留**（§4，dev 标注） |

---

*本文档为 F30 功能规格（What），实施步骤（How）见后续 `specs/f30-kernel/plan.md`。所有里程碑验收以本节 M1-M7 为准。*

---

## 14. 动作确认

> 每个端点/命令/组件的完整状态流表（基于 §2 kernel.json 契约 + §3 ensure_kernel + §5 冷启动协议 + §7 边界事实，不重复）。

### 14.1 内核发现状态流（kernel.json 三态判定 + /health 复用）

| 状态场景 | 前置 | 动作/状态转换 | 成功 | 失败 | 边界 |
|----------|------|--------------|------|------|------|
| 文件不存在 | 无 kernel.json | 视为无内核 → 互斥拉起 | KernelHandle(reused=False) | KernelStartupError | 冷启动含 chromadb/BGE 加载（首次 ~4.7s） |
| JSON 解析失败 | 文件损坏 | 视为无内核 → 重命名 .stale-<ts> → 拉起 | KernelHandle(reused=False) | KernelStartupError | 备份保留现场可排障 |
| pid 不存在 | 崩溃残留 | stale 判定 → 清理（重命名备份）→ 拉起 | KernelHandle(reused=False) | KernelStartupError | 内核退出不主动删（stale 由读取方判定） |
| pid 存活 + /health 200 + 版本兼容 | 内核运行中 | 直接复用，不 spawn | KernelHandle(reused=True) | — | 复用 ~19ms |
| /health 非 200/超时 | pid 存在但 token 失效/端口被占 | stale 清理 → 重新拉起 | KernelHandle(reused=False) | KernelStartupError | health_timeout 默认 2s |
| 版本 major 不匹配 | kernel.json.version 与客户端 major 不同 | 拒绝复用 → 清理 → 拉起匹配版本 | 拉起客户端版本内核 | 仅当客户端能 spawn 自己版本时 | minor/patch 容忍（ADR-019 契约冻结） |

### 14.2 冷启动拉起状态流（互斥 + spawn + 生命周期）

| 场景 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| 互斥获取成功 | CreateMutexW 拿到 | spawn 内核（serve --port 0 --port-file <tmp>）→ INKFLOW_READY/端口文件双保险 → 校验 port/token → 写 kernel.json | KernelHandle(reused=False) | KernelStartupError（含日志指引 %TEMP%\inkflow-kernel.log） | --port-file 为主 + INKFLOW_READY 双保险（不依赖 stdout 解析） |
| 互斥 183（已有实例在拉起） | 另一客户端已持有互斥 | 轮询 kernel.json ≤ timeout | 复用新文件 KernelHandle | 轮询超时 → KernelStartupError | 双客户端同时冷调用只 spawn 一次（§5.3） |
| 内核秒退 | spawn 后立即退出 | 捕获进程退出 → 清理 → 重试 ≤2 次 | 重试内拉起成功 | 仍失败 → KernelStartupError | 日志可查死因 |
| 冷启动超时 | 等待 > timeout（默认 30s） | INKFLOW_READY/端口文件均未到达 | — | KernelStartupError | env INKFLOW_KERNEL_TIMEOUT 覆盖 |
| spawn 命令不存在 / %APPDATA% 不可写 | 打包缺 serve / 权限问题 | — | — | KernelStartupError（明确提示） | 日志记录路径 |
| 生命周期（detach） | 拉起成功 | CREATE_NEW_PROCESS_GROUP + CREATE_NO_WINDOW，Popen 不 wait | 内核常驻到显式退出（不随调用方退出） | — | 无空闲超时回收（ADR-030 D2=A）；显式退出控制面归 GUI 托盘/未来 daemon stop |
| 内核已由他方拉起 | 状态文件 + pid 存活 + /health 200 | 正常复用（不关心拉起方） | KernelHandle(reused=True) | — | 多内核并存禁止（互斥锁 + 唯一路径） |

### 14.3 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow kernel status | 无 | 读 kernel.json 输出内核状态 | 运行中：{ok:true, data:{running:true, pid, port, version}}；未运行：{ok:true, data:{running:false}} | — | dev 标注非用户面；绝不拉起内核（查询≠拉起）；退出码恒 0（状态查询不因未运行失败） |

### 14.4 验收锚点（写入 §13 验收标准）

- A1：无内核 → ensure_kernel 拉起 → kernel.json 写入 → 二次调用复用（pid 不变）→ M5
- A2：kill 内核 → 残留 kernel.json 判定 stale → 重新拉起（新 pid）→ M6
- A3：mock CreateMutexW 返回 183 → 进入轮询不放 Popen → 复用首个客户端写入状态 → M2
- A4：kernel.json version 1.2.0 vs 客户端 2.0.0 → 拒绝复用 → M3
- A5：冷启动超时 / 秒退重试 ≤2 后仍失败 → KernelStartupError → M2
