# F51: 打包产物 Debug 模式（debug-mode）— 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-27 | **依据**: 用户需求（打包产物难测试），Constitution P1-P6, ADR-008/016/020/021/030
> **所属阶段**: 0.13.0 里程碑（Issue #713/#714/#715，估算 4-7 人天）
> **关联 Issues**: [#713](https://github.com/zhx-xi/InkFlow/issues/713)（后端 debug 开关 + 详细日志）· [#714](https://github.com/zhx-xi/InkFlow/issues/714)（Electron GUI DevTools + dev 钩子）· [#715](https://github.com/zhx-xi/InkFlow/issues/715)（serve 可直达端点）
> **依赖**: 无硬前置（三条均为新增能力；#715 复用 #713 的 `INKFLOW_DEBUG` 语义，建议同批排期）
> **参考 ADR**: [ADR-043](../../adr/ADR-043.md)（打包产物 Debug 模式总决策）· [ADR-008](../../adr/ADR-008.md)（pydantic settings 配置）· [ADR-016](../../adr/ADR-016.md)（loguru 日志）· [ADR-020](../../adr/ADR-020.md)（Electron 壳）· [ADR-021](../../adr/ADR-021.md)（内核进程化）· [ADR-030](../../adr/ADR-030.md)（本地内核服务化）
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
    """Debug 模式：INI 级别贯穿三层（见 ADR-043）。
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

- 新增 `isDebugMode()`：读 `process.env.INKFLOW_DEBUG`（env）或 `%APPDATA%/InkFlow/instance.env` 的 `INKFLOW_DEBUG`。
- `setupAppMenu(isPackaged, isDebug)`：`isDebug || !isPackaged` 时注册 F12 / Ctrl+Shift+I 开 DevTools（保留 `isFreshRegistrationSession` 幂等去重）。
- `createMainWindow` 后：`if (isDebugMode()) win.webContents.openDevTools()`（D2 已拍板默认开）。
- dev 钩子门控：`updateKernelInfoHook` / `updateTrayInfoHook` / `exposeTrayDevHooks` 改为 `!app.isPackaged || isDebugMode()`。
- 辅助读取 instance.env：新增小 helper（复用 `app.getPath('appData')` 定位 `%APPDATA%/InkFlow/`，与 kernel.json 同目录定位一致）。

### 5.4 serve 可直达端点（#715）

`serve.py` debug 时：

- **token**：debug 且未显式传 `--token` 时用可预测值——env `INKFLOW_DEBUG_TOKEN`，缺省固定字符串（D1 已拍板）。非 debug 保持 `secrets.token_urlsafe(32)` 随机。
- **/docs**：debug 时默认打开 `http://127.0.0.1:<port>/docs`（D2 已拍板默认开，复用 `open_browser` 语义）。
- **uvicorn**：`log_level="debug"`。
- **端口**：仍 `--port 0` 动态，经端口文件 / `INKFLOW_READY` / 日志可查。

> ⚠️ 安全权衡（§12）：固定 token + 自动 DevTools + verbose 仅 debug 生效，文档标注「勿在生产开启」。renderer 用 INKFLOW_READY 交付的 token，与固定值不冲突（见 §3）。

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
| 打包版日志目录 `%APPDATA%/InkFlow/logs` 不可写 | 文件 sink 降级（loguru 容错），console 仍能诊断 |
| instance.env 含 `INKFLOW_DEBUG=0` / `false` | 按 False 处理（不开 debug）；只在值为真（1/true/on）时开启 |
| env、instance.env、config.json 冲突 | 优先级 env > instance.env > config.json（D1） |
| 非 debug 模式启动 | 行为零变化（随机 token / 不自动 /docs / info 级别 / 无 DevTools 钩子） |
| debug 时 `--token` 显式传入 | 尊重显式 token，不覆盖 |

## 8. 文件结构

### 8.1 CREATE（新建）

| 文件 | 内容 |
|------|------|
| `specs/f51-debug-mode/spec.md` | 本 spec |
| `adr/ADR-043.md` | Debug 模式总决策（已随 spec 创建） |

> 注：测试为本 spec 的主要代码产出，**扩展既有测试文件**（见 §9），不新建独立测试文件（除非契约测试过多需拆）。

### 8.2 MODIFY（修改）

| 文件 | 变更 | 节 |
|------|------|-----|
| `backend/src/inkflow/core/config.py` | `InkFlowConfig` 加 `debug: bool = False`；instance.env / config.json 并入优先级判定 | §2 |
| `backend/src/inkflow/core/log.py` | `resolve_log_dir()` frozen 分支 → `config.data_dir / "logs"`；`setup_logging()` debug 时 console level=DEBUG | §5.2 |
| `backend/src/inkflow/cli/commands/serve.py` | `--debug` flag + debug 分支（token /docs / uvicorn log_level） | §5.4 |
| `frontend/packages/electron/src/main.ts` | `isDebugMode()`；`setupAppMenu(isPackaged, isDebug)`；auto-open DevTools；dev 钩子门控改 `!isPackaged \|\| isDebug` | §5.3 |
| `frontend/packages/electron/src/kernel.ts` | 无核心改动（`INKFLOW_KERNEL_CMD` 分支保留）；如新增 debug 辅助读取可扩展 | §5.5 |
| `adr/README.md` | 索引登记 ADR-043 | — |
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
| unit（扩展） | `tests/api` / `tests/cli` serve 契约 | serve debug 分支（token /docs / uvicorn log_level），`INKFLOW_READY` 契约不破 |
| unit（扩展） | `tests/unit/test_config_frozen*`（如存在） | config.debug 读取优先级（env > instance.env > config.json） |
| frontend unit | `main.menu.test.ts` | debug 门控注册 DevTools（打包版 + debug 也注册）；幂等去重保持 |
| frontend unit | `main.tray.test.ts` | dev 钩子门控改 `!isPackaged \|\| isDebug` 后打包版 debug 暴露 |
| CI | ci.yml 既有 job | 本 spec PR 全绿（coverage-backend 98.5/95.0 不变，ADR-027） |

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

## 13. 验收标准

| # | 验收项（M 行） | 验证方式 | 载体 |
|---|---------------|----------|------|
| M1 | 打包版启动后日志落 `%APPDATA%/InkFlow/logs/inkflow_*.log`（#713） | 打包版实测（frozen）+ `tests/unit/test_log.py` frozen 分支 | 手动 + 单元 |
| M2 | `INKFLOW_DEBUG=1` 时 console + 文件日志均 DEBUG（#713） | 设 env 启动实测 | 手动 |
| M3 | 打包版 + debug：F12 / Ctrl+Shift+I 可开 DevTools；`__kernelInfo`/`__trayInfo`/`__trayActions` 暴露（#714） | `main.menu.test.ts` + 打包版实测 | 单元 + 手动 |
| M4 | debug 起内核可达 `/docs`；已知 token + `X-InkFlow-Token` header curl 成功；uvicorn debug 日志（#715） | serve 契约 + 实测 | 单元 + 手动 |
| M5 | 非 debug 回归：随机 token / 不自动 /docs / info 级别 / 无 DevTools 钩子 | 契约测试 + 对比实测 | 单元 + 手动 |
| M6 | 既有测试全绿（backend unit/api/cli + frontend main.menu/tray）+ coverage 门槛 98.5/95.0 不变 | ci.yml PR 全绿 | CI |

> 完成标准映射：M1-M2 = #713（后端）；M3 = #714（GUI）；M4 = #715（serve）；M5-M6 = 回归 + 质量门禁。

## 待澄清问题（已拍板，留痕）

1. **Q1 debug 触发源优先级**：env > instance.env > config.json。**✅ 已确认（用户 2026-08-27 按建议拍板）**——正文 §2.2/§5.1/§12 D1 已按此修订。
2. **Q2 打包日志目录 + 默认开**：frozen → `config.data_dir/logs`；debug 默认自动开 DevTools + /docs。**✅ 已确认（用户 2026-08-27 按建议拍板）**——正文 §5.2/§5.3/§5.4/§12 D2。
3. **Q3 serve debug token 来源**：env `INKFLOW_DEBUG_TOKEN` 缺省固定字符串。**✅ 已确认（用户 2026-08-27 按建议拍板）**——正文 §5.4/§12 D4。

> 附：D3/D5（debug 日志面 P1 一并做、server_host 保持 127.0.0.1）也在 2026-08-27 用户按建议确认，正文已按此定稿。





