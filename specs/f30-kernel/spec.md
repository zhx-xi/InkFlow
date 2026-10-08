# F30: 内核冷启动基建（kernel_bootstrap）— 功能规格
> **端**: backend

> **Spec 版本**: 1.8 | **日期**: 2026-08-07（1.4 修订 2026-10-06；1.5 修订 2026-10-06；1.6 修订 2026-10-07；1.7 修订 2026-10-08；1.8 修订 2026-10-08） | **依据**: ADR-030（本地内核服务化 ②）、ADR-059（实例类型化并发约束）、ADR-021（内核进程化交付契约）、**ADR-064（内核日志分片与自管理运行期轮转）**、**ADR-066（内核自持存活期互斥 + 可重置空闲回收 + 机器级实例可见性）**、Constitution P1-P6
>
> **Spec 变更**（1.0 → 1.1）: Q1-Q3 全部拍板（2026-08-07 用户选 A/A/A）——Q1 冷启动超时默认 30s + env `INKFLOW_KERNEL_TIMEOUT` 覆盖；Q2 版本校验 major 相同即复用；Q3 保留 `inkflow kernel status` 调试命令（dev 标注）
>
> **Spec 变更**（1.1 → 1.2，#1153 / ADR-059）:
> - §2.4 **新增**：实例类型（kind）契约 + 全量实例注册表
> - §5.6 **新增**：按实例类型的并发准入（rc/正式存活期互斥；dev 允许多开）
> - §6.1 **修订**：「多内核并存：禁止」→ **按 kind 分层**（rc/正式各限 1 个、dev 不限）
> - §10 **修订**：「多内核并存/负载均衡 ❌ 永不」→ dev 多开为**明确支持**语义（rc/正式仍禁）
>
> **Spec 变更**（1.2 → 1.3，#1380）:
> - §6.3 **新增**「日志启动期归档」——该日志为机器级共享且此前无 size cap / rotate / 清理，
>   实测累积 918MB / ≈421 万行；现按 50MB 阈值归档为 `.1`/`.2`（保留 2 份，最旧被删）
>
> **Spec 变更**（1.3 → 1.4，#1477 / ADR-064）:
> - §6.2 **修订**：日志拆三文件 —— **内核运行日志 / 客户端事件日志 / 引导日志**（程序日志与内核日志不再混装）
> - §6.3 **重写**：「日志启动期归档」→「**分片 + 自管理运行期轮转**」。1.3 的方案**实测不可行**：存活内核
>   以继承句柄常驻该文件（Windows 无 `FILE_SHARE_DELETE`）⇒ 任何进程（含内核自己）都无法重命名，
>   运行期与启动期兜底**双双静默失效**（实测 246.2MB 且目录下无任何归档）。改为内核自持句柄 + 现成日志库轮转
> - §5.6 **补注**：存活期互斥的持有者是**客户端进程**（非内核）⇒ 内核存活不受互斥约束；GUI(Electron) spawn
>   不参与互斥 ⇒ 跨数据目录的 prod 可并存（**遗留 → #1487**，不在本修订范围）
>
> **Spec 变更**（1.4 → 1.5，#1488）:
> - §9 **新增**测试场景 12「测试内核进程回收」——测试拉起的 `inkflow serve` 由 pytest **会话级**
>   autouse fixture 统一回收（归属判据：CommandLine 含会话临时根 / 亲缘链上溯到 pytest pid；
>   手工常驻内核与并行会话内核不在清理集；清理失败只记日志、不使测试 ERROR）
>
> **Spec 变更**（1.5 → 1.6，#1487 / ADR-066）:
> - §5.6 **重写**：存活期互斥的**持有者从「客户端进程」改为「内核进程自持」**（内核启动即取、
>   持有到自身退出；获取失败 → 打印 `INKFLOW_KERNEL_CONFLICT` + 退出码 3）。互斥名一字不变
>   （rc/prod 机器级、dev 含 data_dir 摘要）。客户端 `ensure_kernel` 不再取存活期互斥
> - §5.5 **重写**：生命周期语义修订——**内核侧可重置空闲回收**（每次 HTTP 请求刷新；阈值
>   `INKFLOW_KERNEL_IDLE_TIMEOUT` 秒，**未设置 = 关闭**；客户端拉起时注入默认 1800s）→
>   **推翻 ADR-030 ③ D2=A**（原「常驻到显式退出，无空闲回收」）
> - §2.4.2 **修订**：注册表**由内核自身写入/删除**（取代客户端权威路径）；目录按 kind 分域——
>   rc/prod → **机器级** `<标准数据目录>/running/`（不随 `INKFLOW_DATA_DIR` 变）、dev → 既有
>   `<data_dir>/running/`
> - §1.2 / §7 / §9 / §10 **同步**：边界表、错误表、测试场景 13/14、「不在范围内」相应改写
>
> **Spec 变更**（1.6 → 1.7，#1525）:
> - §5.7 **新增**「GUI 检测与托盘拉起探测链」：候选 2/4 改**精确大小写比对**（`os.scandir` 逐 entry 比对，
>   杜绝 Windows 大小写不敏感下把 CLI zip 的内核 `inkflow.exe` 假命中为 GUI）+ **新增候选 3 注册表**
>   `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\*\InstallLocation`（NSIS 写；覆盖自定义
>   安装路径；`winreg` stdlib 零新依赖；非 Windows 跳过）
> - §9 测试场景 15 **扩写**：新增 1a 大小写假命中回归 / 1b 注册表自定义路径 / 注册表负例 / 非 Windows 四类断言
>
> **Spec 变更**（1.7 → 1.8，#1537）:
> - §5.7 **新增候选「内核自登记 `gui.json`」**：GUI 内置内核（`<GUI>/resources\kernel\inkflow.exe`）
>   启动期把 GUI exe 绝对路径写进**机器级** `<标准数据目录>/gui.json`（= `%APPDATA%\InkFlow\gui.json`，
>   不随 `INKFLOW_DATA_DIR` 变）；CLI 探测链读它 → **便携版**（无注册表痕迹）与安装版**通吃**。
>   实测依据：产物验证机 GUI 为便携解压，`HKCU/HKLM/Wow6432Node` 共 185 个 Uninstall 键**零 InkFlow 痕迹**
>   ⇒ 1.7 的注册表候选对便携版无效（#1525 遗留）
> - §2.4.2 / §9 场景 15 **同步**：机器级文件族新增 `gui.json`；新增自登记/读取/负例断言
>
> **所属阶段**: 0.5.0 Agent 集成（本地内核服务化三件套第 1 个模块，估算 3-4 人天）；1.2 修订挂 0.14.0；**1.4 修订挂 0.17.0；1.6 修订挂 0.17.0；1.7 修订挂 0.17.0；1.8 修订挂 0.17.0**
>
> **关联 Issues**: #166（本模块）；#167（GUI 托盘，**依赖本模块**）；#168（CLI 产物，**依赖本模块**）；#169（CLI 恒 HTTP，**依赖本模块**）；#49（F20 MCP，**依赖本模块**）；**#1153（1.2 修订来源）**；**#1380（1.3 修订来源）**；**#1477（1.4 修订来源）**；#1487（内核单实例化补全——1.4 记录的遗留）；**#1525（1.7 修订来源：CLI 托盘探测两处缺陷）**；**#1537（1.8 修订来源：便携版 GUI 探测——内核自登记 `gui.json`）**
>
> **依赖**: ✅ F19（serve 命令 + INKFLOW_READY 交付契约 + `--port-file` 原子写入）· ✅ F1（config.data_dir = %APPDATA%\InkFlow）· ⏳ 无
>
> **参考 ADR**: [ADR-030](../../adr/kernel/ADR-030.md)（本地内核服务化：kernel.json + ensure_kernel）· [ADR-059](../../adr/kernel/ADR-059.md)（实例类型化并发约束——**修订 ADR-030 ②**）· [ADR-021](../../adr/kernel/ADR-021.md)（内核进程化：INKFLOW_READY/端口文件/token）· [ADR-064](../../adr/kernel/ADR-064.md)（内核日志分片与自管理运行期轮转）· [ADR-066](../../adr/kernel/ADR-066.md)（内核自持存活期互斥 + 可重置空闲回收 + 机器级实例可见性——**本 spec 1.6 修订来源，修订 ADR-030 ③ / ADR-059 ②③**）· [ADR-019](../../adr/packaging/ADR-019.md)（版本里程碑）
>
> **状态**: ✅ 已实现（PR #171，#166 2026-08-08）；1.2 修订实施中（#1153）；1.3 修订实施中（#1380）；1.4 修订实施中（#1477）；1.5 修订实施中（#1488）；**1.6 修订实施中（#1487）**；**1.7 修订实施中（#1525）**；**1.8 修订实施中（#1537）**

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
- **（1.6 修订 #1487/ADR-066）不做空闲回收的「有客户端时」打扰**：内核侧**可重置**空闲回收仅表达「无任何 HTTP 活动超阈值 → 自愈退出」；有客户端（含 GUI 的 2s `/health` 轮询）时永不回收——**ADR-030 ③ D2=A（「无空闲回收」）被 ADR-066 推翻**，但「常驻」语义对活跃客户端仍然成立
- **（1.6 修订）不做跨 data_dir 并存**（用户拍板 1B）：互斥保持机器级；换 data_dir 走「先停旧、起新」（GUI）/ 明确报错（CLI），见 ADR-066 ④

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

### 2.4 实例类型（kind）与全量注册表（#1153 / ADR-059）

> 1.2 新增。解决「多实例互相覆盖 kernel.json + 用户不知情堆叠进程」——ADR-059 ①③。

#### 2.4.1 实例类型判定

`INKFLOW_INSTANCE_KIND` 环境变量显式指定；缺省按下列优先级推断（纯函数 `resolve_instance_kind()`）：

| 优先级 | 条件 | 结果 |
|--------|------|------|
| 1 | env `INKFLOW_INSTANCE_KIND` ∈ {`dev`,`rc`,`prod`}（`release` 为 `prod` 的输入别名） | 该值 |
| 2 | `sys.frozen == True` | `prod` |
| 3 | `packaging.version.Version(__version__).is_prerelease` | `rc` |
| 4 | 其他 | `dev` |

- **传递路径**：GUI 壳按 `app.isPackaged` 判定后经 spawn `env` 显式传 `INKFLOW_INSTANCE_KIND`；CLI/MCP/skills 由 `ensure_kernel()` 自判
- **禁止**按 `cwd` / 路径形状猜测 kind（worktree、主仓、任意 cwd 都可能跑同一份 dev 代码）
- `release` 作为输入别名归一为 `prod`（旧脚本 / GUI spawn env 兼容）；其他非法值 → 回落推断（不抛错，宽松语义）

#### 2.4.2 全量实例注册表

> **1.6 修订（#1487 / ADR-066 ③）**：目录**按 kind 分域**（与 `_lifetime_mutex_name` 同构）——`rc`/`prod` 落**机器级固定目录**（不随 `INKFLOW_DATA_DIR` 变化；Windows = `%APPDATA%\InkFlow\running\`，经既有锚点 `core.config.get_instance_env_path().parent`），`dev` 保持既有 `<data_dir>/running/`。**写入方改为内核自身**（取代原「客户端 `ensure_kernel()` 权威路径」）——否则 GUI 自己 spawn 的内核（`main.ts` 只写 kernel.json）永不出现在注册表，托盘「全量可见」（ADR-059 ④）对它失效。

**位置**：`rc`/`prod` → `<标准数据目录>/running/`（打包 = `%APPDATA%\InkFlow\running\`；**机器级**，不受 `INKFLOW_DATA_DIR` 影响）；`dev` → `<config.data_dir>/running/`

**文件命名**：`<kind>-<pid>.json`（pid 保证唯一，kind 便于人眼排查）

**字段**（七字段 = kernel.json 五字段 + `kind` + `data_dir`）：

| 字段 | 类型 | 必填 | 含义 |
|------|------|------|------|
| `kind` | str | 是 | `dev` \| `rc` \| `prod` |
| `port` | int | 是 | 内核监听端口（127.0.0.1） |
| `token` | str | 是 | 鉴权 token |
| `pid` | int | 是 | 内核进程 PID |
| `version` | str | 是 | 内核版本 |
| `started_at` | str | 是 | ISO8601 启动时间（UTC） |
| `data_dir` | str | 是 | 该实例使用的数据目录绝对路径（多实例区分的关键） |

**写入时机**（1.6 修订 #1487/ADR-066）：**内核进程自身**在就绪（`INKFLOW_READY` 交付 + port file 落盘后）写入自己的条目；内核进程退出时删除。客户端**不再**写注册表（`bootstrap.py` 的 `registry.write_instance` 调用移除）。

**清理规则（惰性 GC，无守护进程）**：

- 内核进程自身退出 → `serve.py` finally 删除自己的注册文件
- 被 `taskkill /F` 强杀（不走 finally）→ 留僵尸文件，由**读取方**顺带清理：读注册表时对每个条目做 pid 存活探测，死则删

**向后兼容**：`kernel.json` 五字段契约**不变**，仍是「默认实例」的发现锚点。注册表是**增量**——既有 CLI/MCP/skills 读 kernel.json 的路径零改动。

> **为什么不用 kernel.json 加字段**：① 单文件无法承载「多实例」语义，加字段只是把覆盖问题挪个位置；② 五字段契约被 Python/TS/skills 文档/测试共 74+ 处引用，扩容代价大且无收益。

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

**异常**：冷启动超时 / INKFLOW_READY 解析失败 / 内核秒退 → 抛 `KernelStartupError`（含**分片后**的引导日志 + 内核运行日志指引，见 §6.2）

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

### 5.5 生命周期语义（1.6 修订：ADR-030 ③ **D2=A** → ADR-066 ②）

- 内核**常驻到显式退出**：ensure_kernel 拉起的进程不随调用方退出（`Popen` 不 wait，detach 语义——Windows 上需 `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` + 父进程退出不影响子进程）
- 显式退出控制面：GUI 托盘「退出」（#167）/ 未来 `daemon stop` 语义——本模块不实现
- **（1.6 新增）空闲回收 = 可重置倒计时**：内核侧记录「最近一次 HTTP 请求时刻」（纯 ASGI 中间件，每请求刷新），周期任务在空闲超阈值时置 `uvicorn.Server.should_exit = True`（优雅退出 → 互斥随进程退出释放、注册表条目删除）
  - 阈值来源：env `INKFLOW_KERNEL_IDLE_TIMEOUT`（秒，浮点）。`0` / `off` / 负数 → **关闭**；**未设置 = 关闭**（手工 `inkflow serve` 作长期服务不受影响，行为同 ADR-030 D2=A）
  - **客户端拉起时注入默认 1800s（30 min）**：`ensure_kernel` 与 GUI `spawnKernel` 均在 spawn `env` 显式写入该键
  - GUI 常驻期内核**不会**被回收（GUI 的 2s `/health` 轮询本身刷新倒计时）；GUI 崩溃/被强杀 → 内核在阈值内**自愈退出**（#1477 的 76 孤儿形态解药）
  - **无 GUI 的 CLI 场景即走此兜底**（用户方案 4 / 决策 3A）：CLI 拉起内核 → 无客户端再访问 → 30 min 后自退

### 5.6 按实例类型的并发准入（#1153 / ADR-059 ②）

> 1.2 新增。**修订 ADR-030 ②的互斥语义**：原「CreateMutexW 防双 spawn」只覆盖**拉起动作**，`finally` 即释放，不阻止多内核存活。

| kind | 并发策略 | 机制（1.6：持有者 = **内核进程**） | 互斥名（不变） |
|------|----------|------|--------|
| `rc` | **机器级存活期互斥**（同机限 1） | 内核进程启动即取，**持锁至自身退出**（不释放，由 OS 随进程回收）；获取失败 → 退出码 3 | `InkFlowKernelRc` |
| `prod` | **机器级存活期互斥**（同机限 1） | 同上 | `InkFlowKernelProd` |
| `dev` | **同 data_dir 单内核** | 同走存活期互斥，互斥名带 data_dir 摘要（不同 data_dir / worktree 互不阻塞） | `InkFlowKernelDev-<sha256(data_dir)[:16]>` |

> **1.3 修订（#1188）**：`dev` 从「允许多开（不获取互斥）」改为「同 data_dir 单内核」；`release` 重命名为 `prod`（输入别名 `release` 归一为 `prod`）。三 kind **统一走存活期互斥**，差异仅在互斥名——「data_dir 是否参与判定」由 `_lifetime_mutex_name(kind, state_file)` 单点决定。
>
> **1.6 修订（#1487 / ADR-066 ②——**持有者变更**）**：存活期互斥的持有者从「客户端进程」改为**内核进程自持**。内核 `serve` 启动即 `CreateMutexW(_lifetime_mutex_name(kind, state_file))` 并**持有到自身退出**；获取失败（183）→ stdout 打 `INKFLOW_KERNEL_CONFLICT` + **退出码 3**。`ensure_kernel` **不再**获取存活期互斥——其准入改为「复用判定 → 拉起动作互斥 → spawn → 轮询状态文件」，spawn 出的子进程以退出码 3 退出时读注册表报既有实例。⇒ 三处语义缺陷同时消解：① 上表「机器级限 1」**第一次真正约束内核存活**（而非客户端的拉起动作）；② 客户端退出**不再**释放互斥 → 内核受约束、孤儿不再产生（#1477 的 76 孤儿根因）；③ GUI(Electron) 自己 spawn 的内核**同样**受约束（互斥在内核进程内获取，与拉起方无关）。
>
> **保留的历史语义澄清**（1.4 #1477）：原文所述「持有者是客户端进程」是**修订前**的事实，本 1.6 已按 ADR-066 ② 改正。

**语义对照（本 1.2 修订的实质）**：

```
修订前（bootstrap.py:81 + :411-412）
  _acquire_mutex("InkFlowKernelBootstrap")   ← 「只允许一个拉起动作」
  finally: _release_mutex(mutex_handle)      ← 拉起完成即释放
  ⇒ 想表达「只允许一个内核存活」，实际只表达「防双 spawn」

1.2（rc/prod 路径）
  _acquire_lifetime_mutex(name)                    ← 「只允许一个内核存活」
  name = _lifetime_mutex_name(kind, state_file)    ← rc/prod 全局；dev 按 data_dir 摘要
  （不释放；随进程退出由 OS 自动回收）
  ⇒ 语义与意图一致
```

**准入顺序**（`ensure_kernel()` 内，**复用判定在前**）：

```
1. 复用判定（kernel.json + pid 存活 + /health 200 + 版本兼容）→ 命中即返回
2. kind = resolve_instance_kind()   # 仅用于判定注册表分域目录 + 错误消息（不再取互斥）
3. 拉起动作互斥（InkFlowKernelBootstrap；防双 spawn，finally 释放）→ spawn 内核
4. 轮询状态文件 ≤ timeout → 就绪则写 kernel.json 五字段 → 返回 KernelHandle
5. spawn 出的子进程以**退出码 3** 退出（= 内核侧自持互斥被占，见 §5.6 1.6 修订）
   → 注册表查同 kind 存活实例（rc/prod = 机器级目录；dev = 本 data_dir）
       命中 → 抛 KernelStartupError（消息含既有实例 kind / port / pid / data_dir）
       未命中 → 按普通秒退处理（重试 ≤2 次 → 超时/失败抛错）
```

> **顺序理由（#1171 / 1.6 修订）**：复用判定必须在最前（有可用内核就直接复用，不触碰任何互斥）。**存活期互斥已移入内核进程**，故客户端不再有「撞上自己持有的互斥」问题；并发冷启动由**拉起动作互斥**（`InkFlowKernelBootstrap`）+ `_await_mutex_holder` 兜住——第二个客户端等待并复用（#1192 的等待窗口语义保留在 `_await_mutex_holder` 路径）。**退出码 3 是内核拒绝准入的唯一信号**，客户端据此分流（报既有实例 vs 重试）。

- **dev 按 data_dir 分域**：同 data_dir 限 1 个；不同 data_dir（含各 worktree）互不阻塞——worktree 并行开发不受影响
- `_lifetime_mutex_name` 是「data_dir 是否参与」的**唯一判定点**：将来 rc/prod 若要按 data_dir 分域，改动面仅该函数
- `rc`/`prod`/`dev` 的互斥均在**内核进程内**持有并**不释放**，随内核进程退出由 OS 回收（1.6 修订；修订前为「随调用方进程退出回收」）
- **失败消息**（可感知，不静默）：`KernelStartupError` 含既有实例的 `kind` / `port` / `pid` / `data_dir`，指引用户处理既有实例；GUI 侧转为「先停旧、起新」（ADR-066 ④）
- **1B 落地（ADR-066 ④）**：既有实例与本次 `data_dir` **不同**时——GUI 先 `taskkill` 旧内核再起新内核；CLI 抛含完整实例信息的 `KernelStartupError`（不替用户杀他人内核）

### 5.7 GUI 检测与托盘拉起探测链（1.7 修订 #1525；**1.8 修订 #1537**）

> **修订来源**：0.17.0-rc1 产物验证实测——CLI zip 场景下托盘 **100% 不出现**（两处独立缺陷，见 #1525）。

CLI 会话在 `ensure_kernel` **本次真正拉起内核**（`reused=False`）后，按序探测「已安装 GUI」并以 `--tray-only` detach 拉起（ADR-066 ⑤ 决策 2A）：

| 序 | 候选 | 判据 |
|----|------|------|
| 1 | env `INKFLOW_GUI_EXE` | 路径存在（`is_file`）——操作者/测试逃生口，**优先级最高** |
| 2 | CLI 可执行文件**同目录** `InkFlow.exe` | **精确大小写比对**（`os.scandir` 逐 entry 比 `entry.name == "InkFlow.exe"`，返回磁盘真实名） |
| 3 | **内核自登记** `<标准数据目录>/gui.json`（1.8 新增 #1537） | GUI 内置内核启动期写入 GUI exe 绝对路径；读出后须 `is_file()` 且**精确名** `InkFlow.exe`；缺失 / 损坏 → **静默跳过** |
| 4 | 注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\*` 的 `InstallLocation` | 拼 `InstallLocation\InkFlow.exe` 后**精确比对**；注册表不可用 / 键缺失 / 权限异常 → **静默跳过**（不抛） |
| 5 | `%LOCALAPPDATA%\Programs\InkFlow\` · `%PROGRAMFILES%\InkFlow\` | **精确大小写比对** |

**两处根因（#1525 实测取证）**：

- **1a 大小写假命中**：CLI zip 布局 `inkflow/` 内含**小写 `inkflow.exe`（内核）**；Windows 文件系统大小写不敏感 → `Path(...) / "InkFlow.exe"` + `is_file()` **假命中内核** → 拉起 `…/InkFlow.exe --tray-only` → `Error: No such option: --tray-only` → 静默降级 → 托盘永不出现。**修法**：候选 2/4 一律改用**精确大小写比对**，不得用路径存在性判断。
- **1b 自定义安装路径不可见**：仅探标准位置时，用户装在 `D:\…\InkFlow\`（NSIS 自定义路径）→ 探测不到 → 不拉起。**修法**：**新增候选 3（注册表 `InstallLocation`）**，用 stdlib `winreg`（零新依赖）。

**1.8 修订（#1537）：候选 3「内核自登记 `gui.json`」**——1.7 的注册表候选只覆盖 **NSIS 安装版**；产物验证机实测 GUI 为**便携解压**（`HKCU`/`HKLM`/`Wow6432Node` 共 185 个 Uninstall 键**零 InkFlow 痕迹**）⇒ 便携版仍探测不到。故新增：**GUI 内置内核**（`<GUI>/resources/kernel/inkflow.exe`，spec §5.2 形态）**启动期**把自己反推出的 GUI exe 绝对路径**原子写入机器级** `<标准数据目录>/gui.json`（不随 `INKFLOW_DATA_DIR` 变，与 `running/` 的机器级分域同源，ADR-066 ③）。⇒ **不枚举进程**：内核自身 exe 路径已编码 GUI 位置；**便携/安装通吃**，零新依赖、零前端改动。

- 判定形态：exe 为 `<...>/resources/kernel/<name>` → GUI 根 = 上溯三层；否则（venv / CLI zip / 手工 serve）**不写**。
- **边界**：GUI 至少启动过一次（否则无 `gui.json` → 回落候选 4/5）；GUI 已卸载/移位 → 后续 `is_file()` 失效 → 静默跳过。

**平台兜底**：`sys.platform != "win32"` → **跳过**注册表探测（不 import `winreg`），保证非 Windows 平台/CI 不炸。

**失败语义不变**：任一候选探测失败静默跳过；全部未命中 → 不拉起（走 ② 内核空闲回收兜底）。`INKFLOW_NO_TRAY_GUI` 逃生口与 `reused=True` 不拉起两条既有约定不变。

---

## 6. 组织规则

### 6.1 状态文件位置与生命周期

- 路径：`config.data_dir / "kernel.json"`（打包 = `%APPDATA%\InkFlow\kernel.json`；dev = 默认 data_dir）
- 生命周期：内核启动 → 写；内核退出 → **不主动删**（stale 判定由读取方处理——崩溃场景无清理方，读取方判定更可靠）
- **多内核并存：按 kind 分层（1.2 修订，#1153/ADR-059；1.3 再修订 #1188）**
  - `dev` → **同 data_dir 限 1 个**（存活期互斥名含 data_dir 摘要；不同 data_dir / worktree 互不阻塞；各自 data_dir 下独立 kernel.json）
  - `rc` / `prod` → **同 kind 限 1 个**（机器级存活期互斥 §5.6）；跨 kind 互不阻塞（rc 与 prod 可各 1 个）
  - 注册表（§2.4.2）承载「有哪些实例」的可见性，kernel.json 仍只承载「默认实例」发现

### 6.2 日志文件布局（1.4 修订 #1477）

内核相关输出按**职责**拆三个文件（程序运行日志与内核日志不再混装，对齐 JVM 日志 / 应用日志分离惯例）：

| 文件 | 内容 | 写入方 | 轮转 |
|------|------|--------|------|
| `%TEMP%\inkflow-kernel-<kind>-<hash>.log` | **内核运行日志**：内核进程自身输出（uvicorn / `print` / traceback / 应用日志） | 内核进程（Loguru FileSink，**自己持有句柄**） | Loguru `rotation="10 MB"` + `retention`（10 份 **或** 30 天） |
| `%TEMP%\inkflow-kernel-events.log` | **客户端事件日志**：`ensure_kernel` 操作行（启动/复用/stale 清理/失败） | 客户端 `_log_kernel_event` | `_rotate_kernel_log`（10MB / 10 份） |
| `%TEMP%\inkflow-kernel-<kind>-<hash>.boot.log` | **引导日志**：spawn 到内核接管 stdout 之间的原始输出（**冷启动死因**） | `_spawn_kernel` 的 `Popen(stdout=…)`（继承句柄） | 启动期兜底（`_rotate_kernel_log`，内核退出后由下个启动者归档） |

- `<kind>` ∈ {`dev`,`rc`,`prod`}`；`<hash>` = `sha256(resolve(data_dir))[:8]`——**一律含 data_dir**
  （不复用 `_lifetime_mutex_name` 的「rc/prod 不含 data_dir」分支：互斥可以不区分数据目录，但**日志分片必须区分**，
  否则多数据目录并存的内核（见 #1487）会重新争抢同一文件）
- 事件日志与引导日志**不分片**：二者都没有「长期持有句柄的写者」（客户端 append 后即 close），
  故 `_rotate_kernel_log` 的「认领 + 归档链」多进程安全设计对它们**有效**

### 6.3 内核日志：分片 + 自管理运行期轮转（1.3 新增 #1380；1.4 重写 #1477）

**为什么必须重写**（#1477 实测矩阵）：Windows `MoveFileEx` / `os.replace` 要求目标文件**所有**句柄都带
`FILE_SHARE_DELETE`；存活内核以 `Popen(stdout=…)` 的**继承句柄**常驻该文件（Python `open()` 默认无此标志）

| 场景 | 结果 |
|------|------|
| 外部进程调 `_rotate_kernel_log` | ❌ 文件原样（`WinError 32`） |
| **持有者自己**调 | ❌ 同上 |
| 持有者 `dup2(devnull)` / `close(fd1)` 让位后调 | ❌ 同上（继承句柄另有持有来源，无法自释） |
| 改成 `FILE_SHARE_DELETE` 句柄 | ⚠️ rename 成功，但内核输出**继续写进归档件**（内容错位） |
| **进程自己 open 的句柄** + 库自管理轮转 | ✅ |

⇒ 唯一可行路径 = **日志文件由内核自己持有、由现成日志库负责轮转**（`rotation` 内部 close → rename → reopen）。
这正是 1.3「启动期兜底」失效的原因：只要内核存活，归档就不会发生（实测：246.2MB 且目录下无任何归档）。

- **轮转**：Loguru `rotation="10 MB"`；`retention=` **callable**（库不接受 `"N files"` 或 list，实测 0.7.3）
  —— 两个上限**同时生效**：「超出 10 份」**或**「超过 30 天」即清理（最多留 10 份、最老不超 30 天）；
  ⚠️ 该 callable 收到 `list[str]`（路径，时间升序）且**返回值被库忽略** ⇒ 必须**自行删除**
- **触发**：每次写入按大小判定 ⇒ **运行期天然覆盖**，无需周期任务
- **装配位置**：`serve` 只设 `INKFLOW_KERNEL_LOG_FILE`（分片路径**标记**）；sink 由
  `core.log.setup_logging` 的**内核分支**装配——该函数开头 `logger.remove()` 会清空全部 handler，
  提前装 sink 必被清掉（实测：分片文件只记到 uvicorn 前两行，其余全落回 stderr）
- 🔴 **内核分支不加 stderr sink**：内核 stderr 已被 `_spawn_kernel` 重定向到引导日志，
  全量日志再灌进去正是 #1477 的膨胀根因（实测 `%TEMP%\inkflow-kernel.log` 达 246MB～348MB）
- **uvicorn 桥接**：`uvicorn_log_config` 把 default/access handler 换成 `LoguruHandler`
  （uvicorn 的 logger `propagate=False`，不走既有的 root `InterceptHandler`）
- 🔴 **不替换 `sys.stdout` / `sys.stderr`**（实测：与 Typer CliRunner 的流隔离冲突 →
  `ValueError: I/O operation on closed file`，且会吞掉 GUI 依赖的 `INKFLOW_READY` 交付行）；
  未接入 logging 的原始 stdout（`typer.echo` / `print`）仍落**引导日志**，由启动期归档兜底
- **`_spawn_kernel`**：`stdout` 改为 **boot 文件**（不再指向内核日志）；boot 的启动期归档在 open **之前**调用
- **`_log_kernel_event`**：改写事件日志文件，继续 `_rotate_kernel_log`（**复用既有函数的并发安全实现**）
- **`_rotate_kernel_log` 常量**：`_KERNEL_LOG_MAX_BYTES` 50MB → **10MB**、`_KERNEL_LOG_BACKUPS` 2 → **10**
  （对齐「单文件 10MB / 保留 10 份」默认；**不含时间维度**——多进程安全的归档链用手写时间判断不划算，
  份数封顶已限制总量上界）
- ⚠️ **旧路径契约作废**：`%TEMP%\inkflow-kernel.log` 不再是唯一指引路径 → 错误消息 / 文档改为**动态指引**
  （`_log_hint()`：引导日志 + 内核运行日志两条分片路径）
- ⚠️ **不做**：给 `Popen` 换 `FILE_SHARE_DELETE` 句柄（rename 成功但输出错位，见上表第 4 行）
- ⚠️ **（1.6 修订）遗留已消解**：原文所述「存活期互斥的持有者是**客户端进程**、且 GUI（Electron）spawn 不参与互斥 → 内核存活不受互斥约束、跨数据目录的 prod 可并存」已由 **#1487 / ADR-066** 修复（互斥改为内核进程自持 + 机器级注册表）。日志分片仍**一律含 data_dir**（§6.2），与互斥名的 rc/prod 分支差异无关。

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
| 13 | **（1.4）内核日志 sink 装配失败**（日志目录不可写 / 磁盘满） | **静默降级**：无内核文件日志（其余 sink 照常），内核正常启动（`setup_logging` 内核分支内 `suppress`，不抛） |
| 14 | **（1.6）内核自持互斥已被占用**（同 kind 已有存活内核） | 内核 stdout 打 `INKFLOW_KERNEL_CONFLICT <json>` + **退出码 3**（不写状态文件、不进服务循环）；拉起方据退出码 3 读注册表报既有实例（含 `data_dir`）/ GUI 走「先停旧、起新」 |
| 15 | **（1.6）`INKFLOW_KERNEL_IDLE_TIMEOUT` 非法值**（非数字 / 空串） | 视为**未设置**（关闭空闲回收），不抛错（宽松语义，对齐 kind env 处理） |
| 16 | **（1.6）空闲回收与在途请求竞态** | 判定空闲只依据「最近请求时刻」；回收走 `should_exit`（优雅，等在途请求结束）——不会打断正在执行的请求（长任务期间必有请求活动） |

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
│       ├── instance_kind.py           ← CREATE: resolve_instance_kind（#1153）
│       ├── registry.py                ← CREATE: 实例注册表读写（#1153；1.6 修订：目录按 kind 分域）
│       ├── kernel_logging.py          ← CREATE: 内核日志 sink 装配（#1477）
│       ├── idle_reclaim.py            ← CREATE（1.6 #1487）：空闲回收——阈值解析 + 活动追踪器
│       │                                  （`parse_idle_timeout` / `ActivityTracker`）
│       └── kernel_errors.py           ← CREATE: KernelStartupError
├── api/
│   └── middleware/
│       └── idle_activity.py           ← CREATE（1.6 #1487）：每请求 `touch()` 的纯 ASGI 中间件
├── cli/
│   ├── commands/
│   │   ├── kernel.py                  ← CREATE: kernel status 调试命令（dev 标注）
│   │   └── serve.py                   ← MODIFY（1.6）：内核自持存活期互斥 + 注册表自写/自删 +
│   │                                    空闲回收看门狗线程
│   ├── tray_launch.py                 ← CREATE（1.6 #1487）：已安装 GUI 检测（`resolve_gui_exe`）
│   │                                    + tray-only 拉起（`maybe_launch_tray_gui`）
│   └── app.py                         ← MODIFY（1.6）：`tray_gui_sink()` 包装命令模块 ensure_kernel
└── (api/ domain/ 零新增业务面)

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
8. **kind 判定**（1.2 新增）：env 显式值优先 / frozen→release / 预发布版本→rc / 其余→dev；非法值回落推断
9. **存活期互斥**（1.2 新增）：kind=rc 且互斥被占 → 抛 KernelStartupError（消息含既有实例 port/pid/data_dir），不放 Popen；kind=dev → 不获取存活期互斥、两实例均正常拉起（多开）
10. **注册表**（1.2 新增）：拉起成功后写入 `<kind>-<pid>.json`（七字段）；读注册表时 pid 已死的条目被清理（惰性 GC）；跨 kind 条目并存互不干扰
11. **日志分片与自管理轮转**（1.4 新增 #1477）：① 运行期（**不重启**）超阈轮转 + 归档产生；② 两个上限 retention（超 10 份 **或** 超 30 天即清，含纯逻辑边界）；③ 分片路径随 kind/data_dir 变化；④ 事件日志与内核运行日志**分离**；⑤ uvicorn logging 桥接落日志文件；⑥ sink 装配失败**静默降级**不阻塞内核（`test_kernel_logging.py` + `test_kernel_log_rotation.py`）
12. **测试内核进程回收**（1.5 新增 #1488）：测试拉起的 `inkflow serve` 在 pytest **会话结束**按归属回收——判据两条（CommandLine 含本会话 pytest 临时根 `basetemp`；亲缘链上溯到本 pytest 进程 pid），且**不误杀**手工常驻内核与并行会话/其他 worktree 的内核；枚举/终止失败只记日志、绝不使测试 ERROR（载体：`tests/conftest.py` 会话级 autouse fixture `_reclaim_kernel_processes` + `tests/cli/test_kernel_cleanup_1488.py`；两套 pytest 根镜像，`backend/conftest.py` 同）
13. **内核自持互斥**（1.6 新增 #1487 / ADR-066 ②）：① 装配缝 `_acquire_lifetime_mutex` 由**内核侧**调用（`serve` 路径）——**真实双进程**用例：以同一 data_dir 连起两个 `inkflow serve` → 第二个**退出码 3** 且首个不受影响；② **客户端退出后内核仍持锁**（拉起方进程结束 → `/health` 仍 200、后续 spawn 仍被拒）；③ 拉起方 `ensure_kernel` 不再取存活期互斥（装配缝断言 `_acquire_lifetime_mutex` **未被客户端调用**）
14. **空闲回收**（1.6 新增 #1487 / ADR-066 ②）：① `parse_idle_timeout` 边界（未设置/`0`/`off`/负数 → `None`；正数 → 秒；非法 → `None`）；② 活动追踪器 `touch()` 刷新 → `idle_seconds` 归零；③ **真实内核**：`INKFLOW_KERNEL_IDLE_TIMEOUT=2` 拉起 → 无请求 → 内核自行退出（pid 不再存活）；④ 期间持续请求 → 不退出（可重置）
15. **CLI 拉起 tray-only GUI**（1.6 新增 #1487 / ADR-066 ⑤；**1.7 修订 #1525**，载体在 `tests/cli/`）：① 检测命中（env `INKFLOW_GUI_EXE` / 同目录 `InkFlow.exe`（**精确大小写**） / 注册表 `InstallLocation` / 标准安装位置）→ 以 `--tray-only` detach 拉起（`subprocess.Popen` 装配缝断言 argv）；② `handle.reused=True`（复用）时**不**拉起；③ 检测不到 GUI → 不拉起（负例）；④ **（1.7）大小写假命中回归**：同目录只有小写 `inkflow.exe`（内核）→ 返回 None、不拉起（杜绝 `No such option: --tray-only`）；⑤ **（1.7）注册表自定义路径**：`InstallLocation` 指向自定义目录 → 命中该 `InkFlow.exe`；⑥ **（1.7）注册表负例**：无键 / 读失败 / `InstallLocation` 缺失或空 → 不抛、继续下一候选；⑦ **（1.7）非 Windows** → 跳过注册表探测；⑧ **（1.8）内核自登记**：`gui.json` 记的 GUI exe 命中 → 返回该路径；⑨ **（1.8）负例**：`gui.json` 缺失 / 损坏 JSON / `exe` 非字符串或空 / 目标不存在 / 精确名不符 → 静默跳过、不抛；⑩ **（1.8）内核侧**：内置内核形态（`resources/kernel/`）就绪 → 写机器级 `gui.json`；非内置形态 → no-op

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
| 内核空闲回收/自动退出 | **1.6 修订（#1487 / ADR-066）**：ADR-030 ③ D2=A 被推翻——内核侧**可重置**空闲回收已落地（每次 HTTP 请求刷新、默认 30 min、仅客户端拉起时注入；有客户端时永不回收） | 反转拍板 ✅ 已实现（1.6） |
| 开机自启 | 用户环境配置差异；发布包统一处理 | 发布包/1.0.0 |
| kernel.json 加密 | %APPDATA% 用户私有 ACL 已够（本地威胁模型） | 永不 |
| ~~多内核并存/负载均衡~~ | **1.2 修订（#1153/ADR-059）；1.3 再修订（#1188）**：dev「同 data_dir 限 1 个」（§5.6/§6.1，不同 data_dir / worktree 并行不受限）；rc/正式仍限 1 个。负载均衡仍不做（本地单机无此需求） | 按 kind + data_dir 分域 ✅ 已实现；负载均衡 永不 |
| 守护进程监督内核生命周期 | ADR-029 已判定 daemon 为伪需求；注册表清理走惰性 GC（§2.4.2） | 永不 |

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
| M1 | state.py 三态读写 + 原子写 | `pytest backend/tests/unit/infrastructure/kernel/test_kernel_state.py -v` 全绿 |
| M2 | bootstrap.py 复用/拉起/互斥/超时/重试 | `pytest backend/tests/unit/infrastructure/kernel/test_kernel_bootstrap.py -v` 全绿 |
| M3 | 版本校验 | `pytest backend/tests/unit/infrastructure/kernel/test_kernel_version.py -v` 全绿 |
| M4 | CLI kernel status（信封/退出码） | `pytest ../tests/cli/test_cli_kernel.py -v` 全绿（且已追加 ci.yml integration-cli-backend job） |
| M5 | 手工验证：无内核 → ensure_kernel 拉起 → kernel.json 写入 → 二次调用复用（pid 不变） | 手工验证（`python -c "import asyncio; from inkflow.infrastructure.kernel import ensure_kernel; ..."` 两次调用比对 pid） |
| M6 | 手工验证：kill 内核 → 残留 kernel.json 被判定 stale → 重新拉起 | 手工验证（Start-Process 内核 → Stop-Process → ensure_kernel → 新 pid） |
| M7 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；覆盖率达 ADR-027 门槛（98.5/95.0）；`uv run ruff check src/ tests/unit/ ../tests/` + mypy 通过 |
| M8 | **（1.2 新增）实例类型判定 + 触发路径** | `pytest backend/tests/unit/infrastructure/kernel/test_kernel_instance_kind.py -v` 全绿（env 显式 / frozen / 预发布 / 缺省 / 非法值五路径） |
| M9 | **（1.2 新增）rc 存活期互斥 + dev 多开** | `pytest backend/tests/unit/infrastructure/kernel/test_kernel_concurrency_kind.py -v` 全绿（rc 第二个被拒且消息含既有实例信息；dev 两实例均放行） |
| M10 | **（1.2 新增）注册表读写 + 惰性 GC** | `pytest backend/tests/unit/infrastructure/kernel/test_kernel_registry.py -v` 全绿（写入七字段 / pid 死条目被清理 / 跨 kind 并存） |
| M11 | **（1.4 新增）日志分片 + 自管理运行期轮转** | `pytest backend/tests/unit/infrastructure/kernel/test_kernel_log_rotation.py -v` 全绿：① 分片路径随 kind/data_dir 变化 ② 运行期（不重启）超阈轮转 ③ 幂等（连续两次不产生额外归档） ④ 并发认领（两进程归档链不半截、不丢最新一代） ⑤ 未超阈不动任何文件 ⑥ stat 失败静默返回 False ⑦ 事件日志与内核日志分离 |
| M12 | **（1.4 新增）内核日志装配（`setup_logging` 内核分支）+ uvicorn 桥接** | `pytest backend/tests/unit/infrastructure/kernel/test_kernel_logging.py -v` 全绿：运行期轮转 / retention 两上限（含纯逻辑边界）/ `uvicorn_log_config` 指向 Loguru 桥 / 装配失败静默降级 |

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
