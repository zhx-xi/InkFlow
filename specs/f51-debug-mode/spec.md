# F51: 打包产物 Debug 模式（debug-mode）— 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-27 | **依据**: 用户需求（打包产物难测试），Constitution P1-P6, ADR-008/016/020/021/030
> **所属阶段**: 0.13.0 里程碑（Issue #713/#714/#715，估算 4-7 人天）
> **关联 Issues**: [#713](https://github.com/zhx-xi/InkFlow/issues/713)（后端 debug 开关 + 详细日志）· [#714](https://github.com/zhx-xi/InkFlow/issues/714)（Electron GUI DevTools + dev 钩子）· [#715](https://github.com/zhx-xi/InkFlow/issues/715)（serve 可直达端点）
> **依赖**: 无硬前置（三条均为新增能力；#715 复用 #713 的 `INKFLOW_DEBUG` 语义，建议同批排期）
> **参考 ADR**: [ADR-044](../../adr/packaging/ADR-044.md)（打包产物 Debug 模式总决策）· [ADR-008](../../adr/service/ADR-008.md)（pydantic settings 配置）· [ADR-016](../../adr/service/ADR-016.md)（loguru 日志）· [ADR-020](../../adr/gui/ADR-020.md)（Electron 壳）· [ADR-021](../../adr/kernel/ADR-021.md)（内核进程化）· [ADR-030](../../adr/kernel/ADR-030.md)（本地内核服务化）
> **状态**: 待实现 🔲

---

## 1. 概述

### 1.1 模块定位

**打包产物 Debug 模式专项（横切平台能力，非业务模块变体）**：不新建业务实体、不新增业务 API 端点、不改业务面——为打包产物（便携 ZIP / NSIS 安装版）建立**跨三层的测试/调试能力**，解决「下载后不好测试」痛点。

| 层 | 痛点 | 本 spec 交付 |
|----|------|--------------|
| 后端日志 | 打包版日志丢失/不可查（`log.py` frozen 路径写死 bundle） | frozen 分支日志落点修正 + `log_level=DEBUG` |
| GUI 壳 | 打包版无 DevTools、无 dev 钩子（`main.ts` isPackaged 门控） | debug 模式注册 DevTools + 暴露诊断钩子 |
| serve 后端 | 动态端口 + 随机 token + 无 /docs，不可直达 | debug 可预测 token + 自动 /docs + uvicorn debug |

**统一开关**：`INKFLOW_DEBUG=1`（进程 env / instance.env / config.json），一个开关贯穿三层。

### 1.2 关键事实（现状盘点，2026-08-27 源码核实）

- ❌ **日志落点**：`core/log.py:resolve_log_dir()` = `Path(__file__).resolve().parents[3] / "logs"`——frozen 下 `__file__` 指向包内 `.../_internal/inkflow/core/log.pyc`，`parents[3]` 不再落到可写 backend 根 → 打包版日志丢失。文件 sink level 恒为 DEBUG，但落不到可靠位置。
- ❌ **日志级别**：`config.py:90` `log_level="INFO"`，仅 console sink 受控；`setup_logging()` console 用 `config.log_level`。
- ❌ **GUI DevTools**：`main.ts:setupAppMenu(isPackaged)` 仅 `isPackaged=false` 注册 F12 / Ctrl+Shift+I（`main.menu.test.ts` 契约）；打包版直接 `return`。
- ❌ **GUI dev 钩子**：`updateKernelInfoHook()` / `updateTrayInfoHook()` / `exposeTrayDevHooks()` 由 `app.isPackaged` 门控，打包版不暴露。
- ❌ **serve 可直达**：`serve.py`（`--port 0` + `secrets.token_urlsafe(32)` 随机 token，uvicorn `log_level="info"`），无 `/docs` 快速入口。
- ⚠️ **kernel 命令覆盖**：`kernel.ts:resolveKernelCommand` 分支①已支持 `INKFLOW_KERNEL_CMD` env 覆盖（最高优先级）——已有低层逃生口，但未文档化、不属 debug 触发。
- ⚠️ **数据目录**：`config.py` frozen 分支 → `%APPDATA%/InkFlow`（ADR-030/Q7=B 已实现）；日志落点可复用 `config.data_dir`。

### 1.3 边界声明

- **不含**：日志展示页（#496 统一日志页，挂 1.0.0，本 spec 只解决「日志落对位置 + verbose」）。
- **不含**：debug 专用安全防护强化（debug 仅测试环境用，安全权衡见 §12）。
- **不含**：`INKFLOW_KERNEL_CMD` 的低层入口改造（保留为既有逃生口，本 spec 不扩展）。
- **不含**：新增业务实体/API 端点/CLI 命令组（`serve` 是唯一被触达的 CLI）。
- **不含**：跨平台 / 非 Windows 打包（0.13.0 验收 = Windows）。

## 2. 数据模型

### 2.1 debug 配置字段（无新表）

**本 spec 不新增任何业务实体表 / ORM 列**——只增加一个**全局配置字段**（`InkFlowConfig`）。

```python
# backend/src/inkflow/core/config.py（实现以 TDD 为准）
class InkFlowConfig(BaseSettings):
    # ... 既有字段 ...
    debug: bool = False
    """Debug 模式：INI 级别贯穿三层（见 ADR-044）。
    触发源优先级：进程 env INKFLOW_DEBUG > instance.env INKFLOW_DEBUG > config.json debug。
    """
```

- **pydantic settings 自动映射**：`env_prefix="INKFLOW_"` → `INKFLOW_DEBUG` 环境变量（`true/1/on`）。
- **instance.env 触发**：`%APPDATA%/InkFlow/instance.env` 写 `INKFLOW_DEBUG=1`（`load_instance_env()` 已存在，复用）。
- **config.json 触发**：`{data_dir}/config.json` 写 `"debug": true`（`load_config_json()` 已存在，复用）。

### 2.2 读取优先级（D1 已拍板）

| 优先级 | 触发源 | 说明 |
|--------|--------|------|
| 1（最高） | 进程 env `INKFLOW_DEBUG` | pydantic-settings 直接读 |
| 2 | instance.env `INKFLOW_DEBUG` | `%APPDATA%/InkFlow/instance.env` |
| 3（最低） | config.json `debug` | `{data_dir}/config.json` |

> ⚠️ 实现注意：pydantic-settings 默认只读 os.environ，**不会**自动读 instance.env / config.json——instance.env 需显式并入（`_default_data_dir` 已有 `load_instance_env` 先例，`debug` 同理：model_validator 里读 instance.env / load_config_json 合并），config.json 同理。优先级判定建议在 `config` 实例化后统一解析。
>
> **🔴 读优先级实现判据（2026-08-31 技术审查补，防「env 显式 0」误判）**：判定「env 是否显式设置」必须用 `"debug" not in self.model_fields_set`——`if not self.debug: 读 instance.env` 会把「env 显式 INKFLOW_DEBUG=0」误判为「未设」→ 错误覆盖为 instance.env=1。正确：
> ```python
> # config 实例化后统一解析（伪代码，实现以 TDD 为准）
> if "debug" not in self.model_fields_set:          # env 未显式设
>     ie = load_instance_env()                        # instance.env
>     if "INKFLOW_DEBUG" in ie: self.debug = ie["INKFLOW_DEBUG"] == "1"
>     else:
>         cfg = load_config_json(self.data_dir)       # config.json
>         if "debug" in cfg: self.debug = bool(cfg["debug"])
> ```
> RDD 契约须锁定「env=0 显式关闭 > instance.env=1」（即 env 优先且 `0` 不被覆盖）。
> **⚠️ 空值边界**：`INKFLOW_DEBUG=`（空串）pydantic 解析会抛 ValidationError（同 `langsmith_enabled` 既有行为）——实现期按「未设置」处理，不崩（与 `langsmith_enabled` 语义对齐）。

### 2.3 决策论证（bool 字段 vs 枚举 / 独立配置对象）

| 决策 | 方案 | 理由 | 备选（否决） |
|------|------|------|--------------|
| debug 用 bool 单字段 | `debug: bool = False` | 只有「开/关」两态；无多档 debug 粒度需求 | 枚举 `debug_level`（DEBUG/INFO...）——过度设计，YAGNI |
| 触发源并入既有配置层 | env + instance.env + config.json | 复用既有 `INKFLOW_*` / `load_instance_env` / `load_config_json` | 独立 debug 配置文件——新增机制，成本高 |

## 3. API 契约

**本 spec 不新增业务 API 端点**。debug 模式只影响既有服务的**运行时行为**（不改变接口形状）：

| 端点 | debug 影响 | 不变 |
|------|-----------|------|
| `GET /health` | 无 | 返回 `{status, version}`（version 源不变） |
| `GET /openapi.json` / `/docs` | debug 时默认打开 `/docs`（FastAPI 交互式文档） | 端点本身不新增 |
| 既有业务端点 | 无（日志级别提升） | 请求/响应契约不变 |

- `server_host`：**默认保持 `127.0.0.1`**（D3 已拍板：不改 `0.0.0.0`，防局域网暴露）。debug 不改变监听地址。
- `INKFLOW_READY` 交付契约（`serve.py:103-109` 四字段 port/token/pid/version）**保持不变**——`kernel.ts` / renderer 消费侧零改动。

## 4. CLI 命令签名

`serve` 是唯一被触达的 CLI。debug 时：

```bash
# 触发方式一：设置 env（GUI 拉起内核自动继承）
set INKFLOW_DEBUG=1
inkflow serve --port 0 --port-file <kernel.json>

# 触发方式二：显式 --debug flag（等价 env，优先级见 D1——env 最高）
inkflow serve --port 0 --debug
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--debug` | bool | False | 等价 `INKFLOW_DEBUG=1`；显式 flag 优先级低于 env（D1） |
| `--open-browser` | bool | False | **既有**参数；debug 时默认打开 `/docs`（见 §5.4） |
| `--token` | str | None | **既有**参数；debug 且未显式传时用可预测 token（见 §5.4） |

> F7 全局 CLI 约定（`--json` 信封 / 退出码 0/1/2）不变——debug 不新增命令组、不改信封。

## 5. 关键差异节：Debug 模式三层联动（横切）

### 5.1 触发源与传播（D1 已拍板）

```
INKFLOW_DEBUG=1（用户设置）
   ├── Electron 主进程（main.ts）读取 → 决定 DevTools/钩子
   └── 子内核（inkflow.exe serve）自动继承 env → config.debug=True
          └── serve.py 判定 → token/docs/uvicorn debug
```

- **env 继承**（核心优势）：GUI `spawn` 内核时不显式传 env，但子进程默认继承父进程 env——设置一次 `INKFLOW_DEBUG=1`，壳 + 内核**同时**生效。
- **instance.env / config.json**：Python 内核经 `load_instance_env` / `load_config_json` 读（见 §2.1）；Electron 壳辅助读取（见 §5.3）。
- **🔴 config.json 三层不对称（2026-08-31 技术审查补，防「统一开关贯穿三层」断裂）**：D6 主张「一个开关贯穿三层」，但 **Electron 壳 `isDebugMode()` 只读 env + instance.env、不读 config.json**（GUI 无 data_dir 定位逻辑；仅 config.json 触发时内核 debug 开、GUI DevTools 不开）。**处置二选一（实现期按 TDD 定，spec 默认建议 A）**：
  - **A**：`isDebugMode()` 增加 config.json 读取——data_dir 定位 = instance.env `INKFLOW_DATA_DIR` 优先、缺省 `%APPDATA%/InkFlow/config.json`（与后端 `_default_data_dir` 同构），使 config.json 也贯穿三层。
  - **B**：显式声明「config.json 触发仅作用于内核层（日志/serve），不作用于 GUI 壳」——并在 §1.3 边界声明 + §7 边界表登记。
  - 无论 A/B，都须在 §7 边界表补「config.json 触发时 GUI 壳行为」一行。
- **🔴 tryReuseKernel 复用路径（2026-08-31 技术审查补）**：GUI `tryReuseKernel` 复用的是**先前无 debug 启动**的常驻内核（如 CLI 拉起）时，GUI 开了 DevTools 但内核无 debug token//docs，三层不一致。此边界须在 §7 边界表登记「复用既有内核 vs debug 一致性」。

### 5.2 后端日志：落点修正 + DEBUG 级别（#713）

`core/log.py`：

```python
def resolve_log_dir() -> Path:
    # dev：backend/logs（保持既有契约）——`parents[3]` 在 dev 下 = backend 根
    # frozen：config.data_dir / "logs"（稳定可写，默认 %APPDATA%/InkFlow/logs）
    if getattr(sys, "frozen", False):
        return config.data_dir / "logs"
    return Path(__file__).resolve().parents[3] / "logs"
```

- **落点修正**：frozen 分支改 `config.data_dir / "logs"`（D2 已拍板：`data_dir` 被 env 覆盖时日志随 `data_dir`）。
- **级别**：`setup_logging()` debug 开启时 console sink level=DEBUG（`config.log_level` 联动）。
- 文件 sink 恒为 DEBUG 不变；debug 时 console 也从 INFO 提为 DEBUG。
- **debug 专用日志面**（D3 已拍板 P1 一并做）：debug 时提升 uvicorn access log + LLM 调用链 debug 日志。

### 5.3 GUI 壳：DevTools + dev 钩子（#714）

`main.ts`：

- 新增 `isDebugMode()`：读 `process.env.INKFLOW_DEBUG`（env）或 `%APPDATA%/InkFlow/instance.env` 的 `INKFLOW_DEBUG`（或见 §5.1 config.json 边界处置）。
- `setupAppMenu(isPackaged, isDebug = false)`：**`isDebug` 带默认值 `false`**（⚠️ 保既有 `main.menu.test.ts` 6 个 `setupAppMenu(true/false)` 单参调用编译兼容；缺省 false = 现行为，既有契约零改动）。`isDebug || !isPackaged` 时注册 F12 / Ctrl+Shift+I 开 DevTools（保留 `isFreshRegistrationSession` 幂等去重）。
- `createMainWindow` 后：`if (isDebugMode()) win.webContents.openDevTools()`（D2 已拍板默认开）。
- dev 钩子门控：`updateKernelInfoHook` / `updateTrayInfoHook` / `exposeTrayDevHooks` 改为 `!app.isPackaged || isDebugMode()`（**4 处**——含 `whenReady` 调用点 `if (!app.isPackaged)`，spec 原列 3 个函数 + 该调用点）。
- 辅助读取 instance.env：新增小 helper（复用 `app.getPath('appData')` 定位 `%APPDATA%/InkFlow/`，与 kernel.json 同目录定位一致）。**GUI 侧解析规则与后端 `load_instance_env()` 对齐**（空值键跳过 / `#` 注释），防双份解析语义漂移。

### 5.4 serve 可直达端点（#715）

`serve.py` debug 时：

- **token**：debug 且未显式传 `--token` 时用可预测值——env `INKFLOW_DEBUG_TOKEN`，缺省固定字符串（D1 已拍板）。非 debug 保持 `secrets.token_urlsafe(32)` 随机。
- **/docs**：debug 时默认打开 `http://127.0.0.1:<actual_port>/docs`（D2 已拍板默认开，复用 `open_browser` 语义）。
  - **🔴 端口 bug（2026-08-31 技术审查补，不修则 M4 必失败）**：既有 `--open-browser` 用**请求端口** `port` 拼 URL（serve.py:95），`--port 0`（GUI 必走路径）时 = `http://127.0.0.1:0/docs` **死链**——debug 复用 `open_browser` 语义会继承此 bug。**必须**：自动打开 `/docs` 用 **`actual_port`**（`_run_server` 返回的实际监听端口），且安排在 `_run_server` 返回之后（顺带 `typer.echo` 的 `{port}` 展示也用 `actual_port`，修既有 `:0` 展示瑕疵）。
- **uvicorn**：`log_level="debug"`。
- **端口**：仍 `--port 0` 动态，经端口文件 / `INKFLOW_READY` / 日志可查。

> ⚠️ 安全权衡（§12）：固定 token + 自动 DevTools + verbose 仅 debug 生效，文档标注「勿在生产开启」。renderer 用 INKFLOW_READY 交付的 token，与固定值不冲突（见 §3）。

**S3f-T1 实现补注（2026-09-03，#869）**：/docs /redoc 可达性由 api 层中间件
`backend/src/inkflow/api/middleware/docs_gate.py`（DocsGateMiddleware）按 `config.debug`
每次请求运行时门控——非 debug 模式 404（默认关闭，spec 原文「debug 时默认打开」歧义消除：
打开由 debug 态驱动，非 FastAPI 恒注册）；`serve --debug` / `INKFLOW_DEBUG=1` 双路径均
在 `_run_server` 前回写 `config.debug=True` + 进程 env，三层一致。

### 5.5 vs 既有 `INKFLOW_KERNEL_CMD` 逃生口

| | `INKFLOW_KERNEL_CMD` | `INKFLOW_DEBUG` |
|--|---------------------|-----------------|
| 目的 | 覆盖内核**命令**（如指向 dev python） | 开启内置 debug **行为** |
| 优先级 | `kernel.ts` 分支①最高 | 贯穿三层 |
| 关系 | 正交；保留 | debug 在此基础上叠加行为 |

## 6. 组织规则

**不适用**——本 spec 为横切平台能力，无业务实体组织/聚合规则。

## 7. 边界情况与错误处理

| 场景 | 行为 |
|------|------|
| `INKFLOW_DEBUG=1` 但未配 LLM / embedding | 应用照常启动；debug 只影响日志/DevTools/serve 行为，不要求 LLM 就绪 |
| 打包版日志目录 `%APPDATA%/InkFlow/logs` 不可写 | 文件 sink 降级（loguru 容错），console 仍能诊断。**⚠️ 措辞修正（技术审查补）**：`catch=True` 只兜写入期异常；目录只读时 `logger.add` 在**启动期**直接抛错（非降级）——frozen 改 `%APPDATA%` 后可写，风险小，行为按「目录创建/写入失败时启动报错可见，console 仍可诊断」呈现 |
| instance.env 含 `INKFLOW_DEBUG=0` / `false` | 按 False 处理（不开 debug）；只在值为真（1/true/on）时开启 |
| env、instance.env、config.json 冲突 | 优先级 env > instance.env > config.json（D1）；**env 显式 `0` 用 `model_fields_set` 判定「已设」不被 instance.env/config.json 覆盖**（见 §2.2 实现判据） |
| `INKFLOW_DEBUG=`（空串） | 按「未设置」处理（不崩，与 `langsmith_enabled` 语义对齐） |
| **config.json 触发（仅内核层）** | 内核 debug 开（日志/serve）；**GUI 壳 `isDebugMode()` 是否读 config.json 依 §5.1 boundary 处置 A/B**——若选 B，GUI DevTools 不开（显式声明「仅作用于内核层」）；若选 A，三层贯穿 |
| **GUI 复用既有内核（tryReuseKernel）** | GUI `tryReuseKernel` 复用先前**无 debug**启动的常驻内核（如 CLI 拉起）时，GUI 开了 DevTools 但内核无 debug token//docs，三层不一致——**边界登记**：复用路径不强制重启内核，debug 一致性靠「复用对象本身是否 debug 启动」决定（实现期若需三层一致，可要求复用前检查内核 debug 标记或强制重启） |
| 非 debug 模式启动 | 行为零变化（随机 token / 不自动 /docs / info 级别 / 无 DevTools 钩子） |
| debug 时 `--token` 显式传入 | 尊重显式 token，不覆盖 |
| debug 时 `--open-browser`/自动 /docs | **用 `actual_port`**（`--port 0` 下不用请求端口 `port`，否则 `:0` 死链）——见 §5.4 |
| 非 debug 模式 /docs /redoc | 404（S3f-T1 G1：DocsGateMiddleware 按 `config.debug` 运行时门控，默认关闭） |

## 8. 文件结构

### 8.1 CREATE（新建）

| 文件 | 内容 |
|------|------|
| `specs/f51-debug-mode/spec.md` | 本 spec |
| `adr/packaging/ADR-044.md` | Debug 模式总决策（已随 spec 创建） |

> 注：测试为本 spec 的主要代码产出，**扩展既有测试文件**（见 §9），不新建独立测试文件（除非契约测试过多需拆）。

### 8.2 MODIFY（修改）

| 文件 | 变更 | 节 |
|------|------|-----|
| `backend/src/inkflow/core/config.py` | `InkFlowConfig` 加 `debug: bool = False`；instance.env / config.json 并入优先级判定 | §2 |
| `backend/src/inkflow/core/log.py` | `resolve_log_dir()` frozen 分支 → `config.data_dir / "logs"`；`setup_logging()` debug 时 console level=DEBUG | §5.2 |
| `backend/src/inkflow/cli/commands/serve.py` | `--debug` flag + debug 分支（token /docs / uvicorn log_level） | §5.4 |
| `frontend/packages/electron/src/main.ts` | `isDebugMode()`；`setupAppMenu(isPackaged, isDebug)`；auto-open DevTools；dev 钩子门控改 `!isPackaged \|\| isDebug` | §5.3 |
| `frontend/packages/electron/src/kernel.ts` | 无核心改动（`INKFLOW_KERNEL_CMD` 分支保留）；如新增 debug 辅助读取可扩展 | §5.5 |
| `adr/README.md` | 索引登记 ADR-044 | — |
| `AGENTS.md` / `FEATURES.md` | 里程碑收尾同步（0.13.0 五项同步，收尾 Phase） | — |

### 8.3 不修改（明确声明）

- `backend/src/inkflow/api/app.py`（/health 不变）
- 既有业务实体 / repo / service / router（零业务改动）
- `frontend/packages/renderer/`（渲染层不感知 debug 开关）

## 9. 测试策略

### 9.1 层次与载体

| 层 | 载体 | 覆盖 |
|----|------|------|
| unit（扩展） | `tests/unit/test_log.py` | frozen 日志目录解析（monkeypatch `sys.frozen`）/ debug 级别开关 |
| unit（扩展） | `tests/cli/test_cli_serve.py`（**仓库根 tests/，非 backend/tests/**——serve 契约测试在此，504 行既有） | serve debug 分支（token /docs / uvicorn log_level），`INKFLOW_READY` 契约不破。**⚠️ 该文件 L336-342 硬断言 `uvicorn.Config(..., log_level=\"info\")`——加 debug 分支后仅非 debug 态成立，须标注兼容策略**（debug 分支用 `if config.debug` 隔离，非 debug 断言不变） |
| unit（扩展） | `tests/unit/test_config_frozen.py`（已存在，非「（如存在）」）+ `tests/unit/test_config_instance_env.py`（204 行，instance.env 基础设施已测） | config.debug 读取优先级（env > instance.env > config.json，含 §7 冲突场景） |
| frontend unit | `main.menu.test.ts` | debug 门控注册 DevTools（打包版 + debug 也注册）；幂等去重保持。**⚠️ spec 改 `setupAppMenu(isPackaged, isDebug=false)` 带默认值，既有 6 个单参调用编译兼容（缺省 false=现行为）**；新增 `setupAppMenu(true, true)` 注册 / `(true, false)` 不注册 |
| frontend unit | `main.tray.test.ts` | dev 钩子门控改 `!isPackaged \|\| isDebug` 后打包版 debug 暴露。**⚠️ 该文件目前零钩子用例（grep kernelInfo/Hook 0 命中），正/负向均须新建** |
| CI | ci.yml 既有 job | 本 spec PR 全绿（coverage-backend 98.5/95.0 不变，ADR-027） |

> **🔴 既有测试破坏清单（QA 审查补，M6「既有测试全绿」成立条件）**：本 spec 改动会触碰的既有测试须预判兼容——① `main.menu.test.ts` 6 用例调 `setupAppMenu(true/false)` 单参 → 靠 `isDebug=false` 默认值零改动；② `tests/cli/test_cli_serve.py` L336-342 `log_level=\"info\"` 硬断言 → debug 分支用 `if config.debug` 隔离，非 debug 断言不变；③ `test_log.py` 既有「dev 分支 == backend/logs」断言 → dev 分支不改零影响。

### 9.2 关键场景

1. **frozen 日志落点**：打包版启动 → 日志落 `%APPDATA%/InkFlow/logs/inkflow_*.log`（不再写 bundle/安装目录）。
2. **debug 级别**：`INKFLOW_DEBUG=1` → console 出现 DEBUG 日志。
3. **GUI DevTools**：打包版 + debug → F12 / Ctrl+Shift+I 开 DevTools；`__kernelInfo`/`__trayInfo`/`__trayActions` 暴露。
4. **serve 可直达**：debug 起内核 → 可访问 `/docs`；已知 token + `X-InkFlow-Token` header curl 成功；uvicorn debug 日志。
5. **非 debug 回归**：随机 token / 不自动 /docs / info 级别 / 无 DevTools 钩子。

### 9.3 覆盖率

新增行为走单元测试；整体覆盖率门槛不变。`INKFLOW_DEBUG` 分支须全分支覆盖（debug 开/关两态）。

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| 统一日志展示页 | **#496**（挂 1.0.0）；本 spec 只解决「日志落对位置 + verbose」 |
| debug 安全防护强化 | debug 仅测试环境用；生产禁用靠文档标注 |
| `INKFLOW_KERNEL_CMD` 改造 | 既有逃生口保留，不扩展 |
| 新增业务实体 / API / CLI 命令组 | 无业务需求 |
| 跨平台打包 | 1.0.0 |
| debug 多档粒度 | YAGNI（见 §2.3） |

## 11. 依赖关系

### 11.1 依赖（本任务需要的既有交付）

| 依赖 | 交付 | 用途 |
|------|------|------|
| ADR-030 内核服务化 | ✅ | `INKFLOW_READY` / kernel.json / `config.data_dir` 定位 |
| ADR-008 pydantic settings | ✅ | `INKFLOW_*` env 配置机制 |
| ADR-016 loguru | ✅ | 日志 sink 改造 |
| ADR-020/021 Electron 壳 | ✅ | `main.ts` isPackaged / spawn 内核 / env 继承 |
| #629 LangSmith（F50） | 已交付 | `langsmith_enabled` 已有能力，debug 不影响（正交） |

### 11.2 被依赖（下游）

| 下游 | 依赖本任务的什么 |
|------|------------------|
| #496 统一日志页 | 日志落点修正后 `%APPDATA%/InkFlow/logs` 为准（展示页消费该路径） |
| 后续打包测试 / rc 验证 | debug 模式为验证提供可查日志 / DevTools / 直达后端 |

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| D1 | **debug 触发源优先级** | env `INKFLOW_DEBUG` > instance.env `INKFLOW_DEBUG` > config.json `debug` | 对齐现有 `INKFLOW_DATA_DIR` 的 instance.env 语义；env 最高便于临时启用 | 单一 env（配置文件触发缺失）；config.json 最高（与 instance.env 语义漂移） |
| D2 | **打包日志目录 + GUI/serve 默认开** | frozen 日志 → `config.data_dir/logs`（默认 `%APPDATA%/InkFlow/logs`）；debug 默认自动开 DevTools + /docs | 稳定可写可查；便于测试打包产物 | 固定 `%APPDATA%/InkFlow/logs` 绝对锚点（`data_dir` 被覆盖时不跟随）；默认关（手动快捷键，测试步骤多） |
| D3 | **debug 专用日志面** | P1 一并做（uvicorn access + LLM 调用 debug 日志） | debug 时完整可观测链路 | P2 拆独立 issue（延迟，首版 debug 不完整） |
| D4 | **serve debug token 来源** | env `INKFLOW_DEBUG_TOKEN`，缺省固定字符串 | 可预测 + 可配置；仅 debug 生效 | 仅固定字符串（不可配）；仅 instance.env（env 临时启用时无配置） |
| D5 | **server_host 保持 127.0.0.1** | debug 不改监听地址 | 防局域网暴露（安全） | 临时改 `0.0.0.0`（暴露风险，如需要单独拍板） |
| D6 | **统一开关贯穿三层** | 一个 `INKFLOW_DEBUG` 贯穿壳 + 内核 + serve | env 继承自动传播；成本低 | 每层独立开关（碎片化） |
| D7 | **config.json 触发源三层对称（2026-08-31 技术审查补）** | `isDebugMode()` 增加 config.json 读取（data_dir 定位 = instance.env `INKFLOW_DATA_DIR` 优先、缺省 `%APPDATA%/InkFlow/config.json`），使 config.json 也贯穿三层（方案 A，见 §5.1） | 补 D6「单开关贯穿三层」在 config.json 触发时的缺口 | 方案 B（config.json 仅内核层，GUI 不开）——三层不一致，否决 |
| D8 | **env=0 优先级判据（2026-08-31 技术审查补）** | 用 `model_fields_set` 判定「env 是否显式设置」，env 显式 `0` 不被 instance.env/config.json 覆盖 | 防「`if not debug` 误判 env=0 为未设」→ 错误覆盖 | 朴素 `if not self.debug`（判据缺失，TDD 易实现错） |
| D9 | **auto-open /docs 端口（2026-08-31 技术审查补）** | 自动打开 `/docs` 用 `actual_port` 且 `_run_server` 返回后；`typer.echo` 的 `{port}` 展示也用 `actual_port` | `--port 0` 下请求端口 = `:0` 死链，必须用实际监听端口 | 复用既有 `open_browser` 的请求端口 `port`（`--port 0` 下 M4 必失败） |

## 13. 验收标准

| # | 验收项（M 行） | 验证方式 | 载体 |
|---|---------------|----------|------|
| M1 | 打包版启动后日志落 `%APPDATA%/InkFlow/logs/inkflow_*.log`（#713） | 打包版实测（frozen）+ `tests/unit/test_log.py` frozen 分支 | 手动 + 单元 |
| M2 | `INKFLOW_DEBUG=1` 时 console + 文件日志均 DEBUG（#713） | 设 env 启动实测 + `tests/unit/test_log.py` debug 级别开关（断言 sink level）；**三路触发源（env/instance.env/config.json）各验一次** | 手动 + 单元 |
| M3 | 打包版 + debug：F12 / Ctrl+Shift+I 可开 DevTools；`__kernelInfo`/`__trayInfo`/`__trayActions` 暴露（#714） | `main.menu.test.ts`（isDebug 门控注册）+ `main.tray.test.ts`（钩子暴露，正/负向）+ 打包版实测 | 单元 + 手动 |
| M4 | debug 起内核可达 `/docs`（**用 actual_port** + 已知 token + `X-InkFlow-Token` header curl 成功）；uvicorn debug 日志（#715） | `tests/cli/test_cli_serve.py` debug 分支（token //docs actual_port / `uvicorn.Config` log_level）、`INKFLOW_READY` 四字段不破 | 单元 + 手动 |
| M5 | 非 debug 回归：随机 token / 不自动 /docs / info 级别 / 无 DevTools 钩子 | 契约测试（`test_serve_default_token_is_random_per_start`、`main.menu.test.ts` 生产零注册）+ **新增「缺省不注册 Timer / 不自动 /docs」负向用例** | 单元 + 手动 |
| M6 | 既有测试全绿（backend unit/api/cli + frontend main.menu/tray，见 §9.1 既有测试破坏清单）+ coverage 门槛 98.5/95.0 不变 | ci.yml PR 全绿 | CI |

> 完成标准映射：M1-M2 = #713（后端）；M3 = #714（GUI）；M4 = #715（serve）；M5-M6 = 回归 + 质量门禁。

## 待澄清问题（已拍板，留痕）

1. **Q1 debug 触发源优先级**：env > instance.env > config.json。**✅ 已确认（用户 2026-08-27 按建议拍板）**——正文 §2.2/§5.1/§12 D1 已按此修订。
2. **Q2 打包日志目录 + 默认开**：frozen → `config.data_dir/logs`；debug 默认自动开 DevTools + /docs。**✅ 已确认（用户 2026-08-27 按建议拍板）**——正文 §5.2/§5.3/§5.4/§12 D2。
3. **Q3 serve debug token 来源**：env `INKFLOW_DEBUG_TOKEN` 缺省固定字符串。**✅ 已确认（用户 2026-08-27 按建议拍板）**——正文 §5.4/§12 D4。

> 附：D3/D5（debug 日志面 P1 一并做、server_host 保持 127.0.0.1）也在 2026-08-27 用户按建议确认，正文已按此定稿。
