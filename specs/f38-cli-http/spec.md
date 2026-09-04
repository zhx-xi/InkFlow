# F38: CLI 恒经 HTTP 路由改造（cli_http）— 功能规格
> **端**: backend

> **Spec 版本**: 1.0 | **日期**: 2026-08-09 | **依据**: ADR-030 ② D1=A（CLI 恒经 HTTP）、ADR-021（内核并发契约）、F30 spec（ensure_kernel 消费方）、Constitution P1-P6
>
> **Spec 变更**（0.1 骨架 → 1.0）：Q1-Q2 已拍板（2026-08-09 用户选 A/A）——Q1=HTTP 客户端层放 `infrastructure/http/`（供 F20 MCP 复用）；Q2=测试双轨（mock httpx 主轨 + 少量真实内核集成）。**编号冲突修正（用户拍板方案 A，2026-08-09）**：目录 `f34-cli-http` → `f38-cli-http`（f34 已由 #208 章节审计占用并登记），头部/引用/变体编号同步更新；f35/f36/f37 spec 的「F34=#169」引用同步修正。**变体编号修正（评审 S4 + 谱系复核）**：本模块为 **第 18 变体「CLI 传输层改造型」**（编号依据 AGENTS.md 模块类型谱系：F30=13 / F32=14 / F21=15 / F22=16 / F34 章节审计=17 → 本模块 18）；**零 cli 依赖约束（评审 S8）**：http/ 层不 import cli 任何模块（MCP 复用前提）；M 行明细补齐（评审 🔴-3）。
>
> **所属阶段**: 0.6.0（估算 3-4 人天 → 评审复核建议 **4-5 人天**，含既有 CLI 测试改造）
>
> **关联 Issues**: #169（本模块）；#166（F30 ensure_kernel，✅ 已实现 PR #171）；#168（CLI 产物，✅ 已实现 PR #181）
>
> **依赖**: ✅ F30（ensure_kernel + kernel.json 契约）· ✅ F33（CLI 独立产物，spawn 定位复用）· ✅ F7（CLI 全局约定：JSON 信封/退出码/错误码）
>
> **参考 ADR**: [ADR-030](../../adr/kernel/ADR-030.md)（② D1=A 恒经 HTTP）· [ADR-021](../../adr/kernel/ADR-021.md)（内核交付契约）· [ADR-019](../../adr/packaging/ADR-019.md)（版本里程碑）
>
> **状态**: ✅ 已实现（PR #213，#169 2026-08-09）

> **快速导航**（2026-08-09 #169）：[§1 概述](L21) · [§2 数据模型](L82) · [§3 API 契约](L163) · [§4 CLI 签名](L218) · [§5 关键差异](L264) · [§6 组织规则](L358) · [§7 边界与错误](L388) · [§8 文件结构](L410) · [§9 测试策略](L465) · [§10 不在范围](L526) · [§11 依赖](L542) · [§12 决策记录](L564) · [§13 验收](L579) · [待澄清](L594)

---

## 1. 概述

### 1.1 模块类型定位（第 18 变体「CLI 传输层改造型」）

F38 是 ADR-030 ② D1=A 的消费方改造：**所有业务 `inkflow <cmd>` 先 `ensure_kernel()` 再经 HTTP 调用内核**，移除 CLI 直连 domain 的隐含双路径（ADR-030 已拍板，非本 spec 决策点）。

```
现状:  inkflow <cmd> → 直连 domain（asyncio.run + repo/service 全量 import，~4.7s 冷启动）
改造:  inkflow <cmd> → ensure_kernel() → httpx → http://127.0.0.1:{port}/api/v1/...（~214ms 热调用）
       输出契约不变（F7 JSON 信封 / 退出码 0/1/2 / 错误码）
```

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ 无 |
| 新 API 端点 | ❌ 无（消费既有全部端点，含 F23 SSE；仅 1 处响应头微调，见 §3.3） |
| 新 CLI 命令 | ❌ 无（改造既有命令的调用路径） |
| 核心机制 | ✅ CLI 命令级 ensure_kernel 接线 + HTTP 客户端层（`infrastructure/http/`，Q1=A）+ 错误映射（HTTP 状态 → F7 错误码） |
| 跨模块 MODIFY | ✅ 14 个既有 CLI 命令文件（`cli/commands/*.py`）调用路径改造 + 22 个 CLI 测试文件（tests/cli/，分布 5 个 ci.yml job）；**4 个命令豁免**（serve/kernel status/config/llm，§1.3） |
| 错误面 | CLI 错误码/信封不变；新增内核拉起失败路径（KernelStartupError → CLI 明确报错）；新增 INTERNAL_ERROR 错误码（§5.3） |

### 1.2 边界声明

- **不做**：内核生命周期管理（F30 已交付）；CLI 打包（F33 已交付）；MCP 薄客户端（F20，1.0.0）
- **不变**：JSON 信封契约、退出码、错误码（F7 契约冻结，INTERNAL_ERROR 为**新增**错误码——F7 表补充行，向后兼容）；CLI 命令签名与参数；**serve / kernel status / config / llm 四组命令的行为（豁免，§1.3）**
- **变**：业务命令数据来源（domain 直连 → HTTP）、import 面（全量 → httpx 轻量）
- **⚠️ 零 cli 依赖约束（评审 S8）**：`infrastructure/http/` 必须是**纯基础设施层，不 import `cli/` 任何模块**——否则 F20 MCP 复用即形成反向依赖（MCP 引用 CLI 层）。此约束写入 §6 组织规则。

### 1.3 豁免命令清单（源码核实，2026-08-09）

骨架 §8 原稿列「19 个命令文件全改」——**逐文件源码核实后修正为 14 改 + 4 豁免**（cli/commands/ 实际 18 个命令模块）：

| 命令模块 | 处理 | 理由（源码事实） |
|----------|------|------------------|
| `serve` | **豁免** | 内核启动者本身——恒 HTTP 自指（serve 不存在则无可 ensure_kernel 的对象）；F19 契约（INKFLOW_READY/--port-file/token）零改动 |
| `kernel status` | **豁免** | F30 已实现为「**绝不拉起内核**」的纯状态查询（spec §4：非用户面 dev 命令）；走 HTTP 会破坏「查询 ≠ 拉起」语义 |
| `config show/set` | **豁免** | 操作本地 `config.json`（CONFIG_WHITELIST 键集合）；**API 无对应端点**——F32 `/api/v1/settings` 是 AppSettings 键集合（theme/language 等），与 CONFIG_WHITELIST（default.model/context.max_ratio 等）**完全不同**；config.json 与内核共享同一 data_dir（无数据漂移） |
| `llm list/set-key` | **豁免** | 操作本地 `keys/`（APIKeyManager AES-256-GCM 文件）；API 仅 POST /settings/llm-keys（写入），**无 key 状态读取端点**（llm list 需 provider→key 状态→掩码）；keys/ 与内核共享同一 data_dir |
| `agent tools list`（F26 新增，登记 2026-08-10） | **豁免** | 本地静态枚举（工具注册表 `infrastructure/agent/tools/` 是代码内静态资源，非内核运行时状态）；**API 无对应端点**（F26 纯内部基础设施）；不启动内核、不发 HTTP——F38 恒 HTTP 改造不适用于无端点命令 |
| 其余 14 个（project/chapter/character/world/outline/timeline/foreshadowing/extract/audit/style/vector/agent/session/write） | **改造** | 全部有对应 API 端点（§3.1 消费清单）；domain 数据经 HTTP 单一路径 |

> **豁免的代价**：config/llm 走本地文件（非 HTTP）——与 ADR-030「恒经 HTTP」字面有偏差，但**数据仍与内核一致**（共享 data_dir），且无「双路径漂移」风险（配置/密钥非领域数据、无内存态）。若未来云端模式（F18）需要远程配置，再为 config/llm 补端点（登记 §10）。

### 1.4 改造全景（调用路径变化）

```text
改造前（每个业务命令）:
  cli/commands/<cmd>.py
    → import domain.services.* / infrastructure.database.* / infrastructure.llm.*（全量 import ~4.4s）
    → create_tables() + async_session_factory() + Service(session)（直连 SQLite）

改造后（每个业务命令）:
  cli/commands/<cmd>.py
    → import infrastructure.kernel（ensure_kernel）+ infrastructure.http（InkFlowHTTPClient）
    → handle = await ensure_kernel()          # 复用/互斥拉起（F30，~19ms 复用）
    → async with InkFlowHTTPClient(handle) as client:
        data = await client.get("/api/v1/...")  # httpx，base_url/token 由 handle 构造
    → print_result/print_error（F7 信封不变）
```

---

## 2. 数据模型

**无新业务实体、无新 ORM 表**（纯传输层基建）。新增数据面 = HTTP 客户端配置与错误映射 DTO。

### 2.1 HTTP 客户端配置（InkFlowHTTPClient）

```python
# infrastructure/http/client.py — CREATE（Q1=A）

@dataclass(frozen=True)
class HttpApiError(Exception):
    """API 错误响应（非 2xx）——status_code + detail 文本 + 错误码（响应头或映射）。"""

    status_code: int
    detail: str
    code: str | None = None      # X-InkFlow-Error-Code 响应头（§3.3）；None = 未提供
```

```python
class InkFlowHTTPClient:
    """httpx.AsyncClient 封装 — base_url/token 头/超时/SSE 流式支持（spec §2.1）。"""

    def __init__(
        self,
        handle: KernelHandle,          # F30 KernelHandle（port/token/pid/version/started_at/reused）
        timeout: float = 30.0,         # 请求超时（秒）；SSE 流式用流式超时（§5.4）
    ) -> None: ...
```

| 配置项 | 值 | 说明 |
|--------|----|------|
| `base_url` | `http://127.0.0.1:{handle.port}/api/v1` | 内核动态端口（F19 契约） |
| 请求头 | `X-InkFlow-Token: {handle.token}` | ADR-021 本地 token 校验 |
| 超时 | 默认 30s；SSE 流式 `timeout=None`（流式超时由帧间隙控制，§5.4） | 冷启动拉起由 ensure_kernel 处理（不占请求超时） |

**方法契约**（client 层 API，供 CLI 与 F20 MCP 复用）：

```python
async def request(
    self, method: str, path: str, *,
    params: dict | None = None, json: dict | None = None,
) -> dict:
    """发送请求，2xx 返回 JSON body（dict）；非 2xx 抛 HttpApiError（§5.3 映射）。"""

async def get(self, path: str, *, params: dict | None = None) -> dict: ...
async def post(self, path: str, *, json: dict | None = None) -> dict: ...
async def patch(self, path: str, *, json: dict | None = None) -> dict: ...
async def delete(self, path: str, *, params: dict | None = None) -> dict: ...

async def stream_sse(
    self, path: str, *, json: dict | None = None,
) -> AsyncGenerator[dict, None]:
    """SSE 流式消费（F23 §6 帧协议）：逐帧 yield 解析后的 dict；流中断抛 HttpApiError。"""
```

> **响应解析**：FastAPI 响应体 = `{"ok": true, "data": ...}`（CLI 信封）或裸数据？——**实测核实**：API 端点返回**裸数据**（如 `POST /projects` 返回项目对象 JSON，非信封）；CLI 侧 `print_result` 负责包信封。client 层 `request` 返回解析后的 JSON（dict/list），不做信封包装（信封是 CLI 表现层职责，F20 MCP 不需要信封）。

### 2.2 错误映射 DTO（HttpErrorMapper）

```python
# infrastructure/http/errors.py — CREATE

def map_http_error(status_code: int, detail: str, header_code: str | None) -> tuple[str, str]:
    """HTTP 状态 + detail 文本 + 响应头错误码 → (F7 错误码, 展示消息)。

    确定性映射（§5.3 表）：404→NOT_FOUND / 422→VALIDATION_ERROR / 401→CONFIG_ERROR
    500 + X-InkFlow-Error-Code 响应头 → 该码（LLM_ERROR 等）
    500 无响应头 → INTERNAL_ERROR（新增，§5.3）
    """
```

### 2.3 决策论证表

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **独立 `infrastructure/http/` 层（Q1=A，选定）** | 跨 CLI/MCP/skills 复用；依赖方向合法（cli → http，http 不依赖 cli）；F20 MCP 薄客户端直接复用 | 多一层抽象 | ✅ 用户拍板 Q1=A |
| `cli/` 内私有 HTTP 模块 | 改动面最小 | MCP 引用 CLI 层 = 反向依赖；复用需跨层 import | ❌ 否决（S8 约束） |
| CLI 继续直连 + 新增 MCP 薄客户端 | 既有测试零改造 | 双路径漂移；违背 ADR-030 D1=A | ❌ 否决（ADR-030 已拍板） |

---

## 3. API 契约

### 3.1 消费端点清单（源码核实，2026-08-09）

CLI 改造后消费的既有端点（**全部既有，零新增**；路径前缀 `/api/v1`）：

| CLI 命令组 | 消费端点（方法 + 路径） | 归属模块 |
|-----------|------------------------|----------|
| `project` | POST /projects · GET /projects · GET/PATCH/DELETE /projects/{id} · POST /projects/{id}/restore | F1 |
| `chapter` | POST /projects/{pid}/volumes · GET/PATCH/DELETE /volumes/{vid} · POST /projects/{pid}/chapters · GET /projects/{pid}/chapters · GET/PATCH/DELETE /chapters/{cid} · POST /chapters/{cid}/move | F2 |
| `character` | POST/GET /projects/{pid}/characters · GET/PATCH/DELETE /characters/{id} · POST /characters/{id}/restore · relations 三端点 · character-groups 五端点 · POST /characters/extract | F9/F14 |
| `world` | POST/GET /projects/{pid}/world-settings · GET /projects/{pid}/world-settings/categories · GET/PATCH/DELETE /world-settings/{id} · POST /world-settings/{id}/restore · POST /world-settings/extract | F10/f35-f37 |
| `outline` | POST/GET /projects/{pid}/outlines · GET/PATCH/DELETE /outlines/{id} · POST /outlines/{id}/restore · plot-points 五端点 · story-arcs 五端点 · POST /outlines/generate | F11 |
| `timeline` | POST/GET /projects/{pid}/timeline/events · GET /projects/{pid}/timeline · GET /projects/{pid}/timeline/check · GET/PATCH/DELETE /timeline/events/{id} · POST /timeline/events/{id}/restore | F12 |
| `foreshadowing` | POST/GET /projects/{pid}/foreshadowings · GET/PATCH/DELETE /foreshadowings/{id} · POST /foreshadowings/{id}/restore/resolve/reopen | F13 |
| `extract` | POST /extract · GET /projects/{pid}/extractions/runs · POST /projects/{pid}/vector/reindex · POST /projects/{pid}/vector/retrieve | F14 |
| `audit` | GET /projects/{pid}/audit | F15 |
| `style` | POST /projects/{pid}/style/analyze | F16 |
| `vector` | POST /projects/{pid}/vector/retrieve · POST /projects/{pid}/vector/reindex | F14 |
| `agent` | POST /pipelines/execute · POST /pipelines/validate · GET /pipelines/executions · GET /pipelines/executions/{id} | F4/F26 |
| `session` | POST/GET /sessions · GET/PATCH /sessions/{id} · POST /sessions/{id}/pause|resume|complete|fail · POST/GET /sessions/{id}/logs · DELETE /sessions/{id} · POST /sessions/{id}/restore | F24 |
| `write` | POST /writing/stream（SSE，默认流式，§5.4）· POST /writing/generate|continue|revise（非流式兜底） | F3/F23 |

### 3.2 请求/响应示例（project create）

```http
POST http://127.0.0.1:{port}/api/v1/projects
X-InkFlow-Token: {token}
Content-Type: application/json

{"name": "星辰变", "genre": "玄幻", "language": "zh-CN", "target_words": 0}

→ 200 {"id": "3f2e1d4a-...", "name": "星辰变", "genre": "玄幻", ...}
```

> **CLI 参数 → 请求体映射**：命令签名零变化，参数名语义与 API DTO 字段一一对应（如 `--name`→`name`、`--genre`→`genre`、`--target-words`→`target_words`）。枚举转换（`Genre(genre)` 等）在 CLI 侧保持（F7 现状），序列化后入 JSON body。

### 3.3 错误响应契约（🟡-4 缺口修复：响应头扩展）

**现状（源码核实）**：所有 router 以 `HTTPException(status_code, detail=<中文文本>)` 表达错误——detail 是纯文本，**无结构化错误码**。CLI 直连时代错误码来自 domain 异常类型（LLMRequestError → LLM_ERROR 等）；恒 HTTP 后 CLI 只能看到状态码 + detail 文本，**HTTP 500 无法区分 LLM_ERROR/DB_ERROR/其他内部错误**（骨架 🟡-4）。

**方案（本 spec 拍板）**：**轻量 API 错误码响应头扩展——仅 writing router（LLM 管线核心）**：

| 变更 | 内容 |
|------|------|
| MODIFY `api/routers/writing.py` | `_map_service_error` 的 500 LLM 分支加 `headers={"X-InkFlow-Error-Code": "LLM_ERROR"}`（约 1 行）；其余分支不变 |
| 语义 | writing 是 CLI 最高频 LLM 命令（`inkflow write`）——LLM_ERROR 语义必须保留；**其余 router 不扩展**（500 兜底 INTERNAL_ERROR + detail 文本透传，message 仍可读） |
| 影响面 | 1 个 API 文件 + 该文件测试（tests/api/test_writing_*.py 补响应头断言）；**不新增端点、不改既有响应体** |

**CLI 侧映射规则（§5.3 全表）**：优先读 `X-InkFlow-Error-Code` 响应头（LLM_ERROR）；无响应头时按状态码确定性映射（404/422/401）；500 兜底 → `INTERNAL_ERROR`（F7 表新增行，message = detail 文本透传）。

> **为什么不全量扩展所有 router**：影响面 = 17 个 router + tests/api 全部错误断言（数百处），远超本模块「CLI 传输层改造」范围；且多数命令（project/chapter 等）的错误语义由状态码完全决定（404/422），无需错误码。write 是唯一需要区分「内部错误 vs LLM 失败」的高频路径。若未来需要（如 F20 MCP 全量错误码），再统一扩展（登记 §10）。

---

## 4. CLI 命令签名

**命令签名零变化**（F7 契约冻结 + 本模块边界声明）——`--json` 全局选项、各子命令参数、退出码 0/1/2/130 全部保持。

### 4.1 顶层接线位置（app.py）

```python
# cli/app.py — MODIFY（仅 import 面，命令注册零变化）
# ⚠️ 技术约束（2026-08-09 源码核实）：ensure_kernel 不能在 app callback 顶层接线——
#   callback 在参数解析前执行，`inkflow --help` / `--version` / `serve` 都会误触发内核拉起。
#   正确接线点 = 各命令函数内部（惰性，§5.1），app.py 仅确保命令模块 import 面收敛。
```

> **app.py 的 MODIFY 内容**：若现有 `from inkflow.cli.commands import ...` 全量导入导致 import 面未缩小，需确认**命令模块顶层不再 import 重组件**（§5.5）。实测 app.py 本身 import 面已轻（typer + commands），重组件在命令模块内（write.py 顶层 import LangChainLLMClient 等）——**关键改造点**。

### 4.2 命令函数内部接线模式（全部 14 个业务命令统一）

```python
# cli/commands/project.py — MODIFY（示例模式）

@app.command()
def create(ctx: typer.Context, name: str = ..., ...) -> None:
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()                    # F30：复用/互斥拉起
        async with InkFlowHTTPClient(handle) as client:   # 惰性创建，请求完关闭
            return await client.post("/projects", json={  # 参数 → JSON body
                "name": name, "genre": Genre(genre).value,
                "language": language, "target_words": target_words,
            })

    try:
        data = asyncio.run(_impl())
    except HttpApiError as exc:
        code, message = map_http_error(exc.status_code, exc.detail, exc.code)
        print_error(cli_ctx, code, message)               # F7 信封 + 退出码 1
    except KernelStartupError as exc:
        print_error(cli_ctx, "KERNEL_ERROR", f"内核启动失败: {exc}")   # 新增错误码
    print_result(cli_ctx, data)                           # 人类/JSON 双模式（F7 不变）
```

> **契约要点**：① `ensure_kernel` 每次命令调用执行一次（复用路径 ~19ms，可接受）；② `InkFlowHTTPClient` 作为 async 上下文管理器（`aclose` 关闭连接池）；③ `HttpApiError` / `KernelStartupError` 捕获后走 `print_error`（信封 + 退出码 1）；④ 命令内**不再** `create_tables()` / `async_session_factory()` / 构造 Service——这些全部由内核承担。

---

## 5. 关键差异：CLI 传输层改造

### 5.1 ensure_kernel 接线时序

```text
inkflow write next --project-id ... --outline ...
  │
  ├─ typer 参数解析（命令签名零变化）
  ├─ ensure_kernel()                      ← 惰性接线（§4.1 技术约束）
  │    ├─ 读 kernel.json → pid 存活 + /health 200 → 复用 KernelHandle（~19ms）
  │    └─ 无/失效 → CreateMutexW 互斥 → spawn 内核 → 写 kernel.json（~4.7s 首次）
  ├─ InkFlowHTTPClient(handle)            ← base_url/token 从 handle 构造
  ├─ POST /api/v1/writing/stream          ← SSE 流式（§5.4）
  └─ print_result / print_error           ← F7 信封不变
```

| 时序点 | 行为 | 异常处理 |
|--------|------|----------|
| ensure_kernel 复用失败（/health 非 200） | F30 stale 清理 → 重新拉起 | 拉起失败 → KernelStartupError |
| ensure_kernel 版本 major 不匹配 | 拒绝复用 → 清理 → 拉起匹配版本 | — |
| 请求超时（30s 默认） | httpx.TimeoutException → HttpApiError 映射 INTERNAL_ERROR（消息含「请求超时」） | §7 #6 |
| 连接拒绝（内核刚死） | httpx.ConnectError → 建议「内核可能已退出，重试将自动拉起」→ 重新 ensure_kernel 一次（**单次重试**，防抖） | §7 #5 |

### 5.2 httpx 客户端生命周期

- **每命令创建、请求后关闭**（`async with InkFlowHTTPClient(handle)`）：CLI 命令是一次性进程，连接池无跨命令复用价值；显式 `aclose` 防 fd 泄漏
- **连接复用**：单命令内多次调用（如 `write next --count 3` 循环 3 次 stream）共享同一 client 实例（`async with` 块内）
- 不设全局单例（YAGNI；F20 MCP 常驻场景由 MCP server 自行管理生命周期）

### 5.3 错误映射表（HTTP 状态 → F7 错误码）

| HTTP 状态 | 映射错误码 | 消息来源 | 场景 |
|-----------|-----------|----------|------|
| 404 | `NOT_FOUND` | detail 文本透传 | 项目/章节/实体不存在 |
| 422 | `VALIDATION_ERROR` | detail 文本透传（FastAPI 校验） | 参数非法/枚举错误/缺失字段 |
| 401 | `CONFIG_ERROR` | detail 文本透传 | token 失效（内核重启后旧 token 场景，罕见——ensure_kernel 已校验） |
| 传输层超时（header_code=`TIMEOUT`，#926） | `TIMEOUT` | 超时文案（per-request 值，缺省 30s） | httpx 超时（connect/read/write/pool）统一转 TIMEOUT，不再误归 DB_ERROR/INTERNAL_ERROR 空消息 |
| 500 + `X-InkFlow-Error-Code: LLM_ERROR` | `LLM_ERROR` | detail 文本透传 | write 流式/非流式 LLM 失败（writing.py 响应头） |
| 500（无响应头） | `INTERNAL_ERROR`（**新增**） | detail 文本透传 | 其余内部错误（DB/未知异常） |
| 连接失败/超时 | `KERNEL_ERROR`（**新增**） | 明确文案 + 日志指引 | 内核不可达（§5.1 单次重试后仍失败） |
| ensure_kernel 失败 | `KERNEL_ERROR`（**新增**） | KernelStartupError 文案 + `%TEMP%\inkflow-kernel.log` 指引 | 冷启动超时/秒退/spawn 失败 |

**LLM 长任务 per-request timeout + TIMEOUT 错误码（#926）**：LLM 长任务端点（outline
generate / extract / summarize / analyze / writing 流式等 21 处 CLI 调用点 + 7 处 MCP
调用点 + 3 处 stream_sse）统一加 `timeout=LLM_TASK_TIMEOUT`（`infrastructure/http/__init__.py`
共享常量 `300.0`，对齐 #274 write `_AGENTIC_TIMEOUT`）；纯 CRUD/GET 调用保持客户端默认
30s。传输层 `InkFlowHTTPClient` 捕获 `httpx.TimeoutException` → `HttpApiError(status_code=0,
code="TIMEOUT", detail=超时文案)`；`map_http_error` 识别 `header_code == "TIMEOUT"` →
`("TIMEOUT", detail or "请求超时")`。非流式文案 = `请求超时（{timeout:g}s）：服务端任务可能
仍在进行，请稍后用 list/get 查询结果，勿直接重试`；流式（stream_sse）前缀 =
`流式响应空闲超时（{timeout:g}s）：生成可能仍在进行，…`；流中断（非超时）语义保持
STREAM_INTERRUPTED 不变。

> **F7 错误码表扩展说明**：`INTERNAL_ERROR`/`KERNEL_ERROR` 为 HTTP 化**新增**错误码（F7 原表：NOT_FOUND/VALIDATION_ERROR/LLM_ERROR/CONTEXT_BUDGET_EXCEEDED/CONFIG_ERROR/DB_ERROR）。**DB_ERROR 在恒 HTTP 后不再由 CLI 产生**（DB 访问全部在内核侧，CLI 只见 500）——F7 表保留 DB_ERROR 行（向后兼容文档），标注「恒 HTTP 后由 INTERNAL_ERROR 替代」。CONTEXT_BUDGET_EXCEEDED 同理（write 命令经 HTTP 后由内核校验，500 兜底）。

> **兜底文案（#634）**：detail 为空时按场景返回诊断文案——401→「鉴权失败」、403→「无权限」、404→「资源不存在」、422→「参数校验失败」、500/其余→「内部错误（无详情）」，避免 CLI/MCP 暴露 `INTERNAL_ERROR: ` 空消息。

### 5.4 SSE 流式转发（write 命令，F23 §6 帧协议）

```python
# cli/commands/write.py — MODIFY（核心改造：直连 service 流 → HTTP SSE 流）

async def _run() -> None:
    try:
        handle = await ensure_kernel()
        async with InkFlowHTTPClient(handle) as client:
            parts: list[str] = []
            done_ev: dict | None = None
            async for ev in client.stream_sse(
                "/writing/stream",
                json={**request_body, "mode": "generate"},   # F23 判别联合
            ):
                if ev.get("delta"):
                    parts.append(ev["delta"])
                    if not cli_ctx.json_output:
                        typer.echo(ev["delta"], nl=False)
                elif ev.get("done"):
                    done_ev = ev
            # 帧 → WritingResult（镜像 _collect_stream 语义，§4.2 F23）
            result = _frame_to_result(parts, done_ev, WritingMode.GENERATE)
    except HttpApiError as exc:
        code, message = map_http_error(exc.status_code, exc.detail, exc.code)
        print_error(cli_ctx, code, message)
    except LLMRequestError as exc:        # 仅流中 error 帧路径（§5.4 注）
        print_error(cli_ctx, "LLM_ERROR", f"LLM 调用失败: {exc}")
```

| 帧字段（F23 §6.2） | CLI 处理 |
|---------------------|----------|
| `delta` 帧（0-N 个） | 拼接 parts；人类模式逐 delta 打印（`nl=False`） |
| `done` 帧（恰好 1 个） | `format_valid`/`word_count`/`model`/`token_usage`/`warnings` → WritingResult |
| `error` 字段（done 帧携带） | → LLM_ERROR（F23 §7 E3：流中 LLM 失败） |
| 流中断（连接断开） | HttpApiError → INTERNAL_ERROR（message 含「流中断」） |

> **流式超时**：SSE 流式请求 `timeout=None`（httpx 流式读），帧间隙由内核心跳语义保证（F23 首 token ≤2s 验收）；客户端 Ctrl+C → `KeyboardInterrupt` 终止 `async for`（httpx 流式上下文自动关闭，退出码 130 Typer 默认）。

### 5.5 import 面收敛（性能本质，ADR-030 ②）

| 命令模块 | 改造前顶层 import（重组件） | 改造后 |
|----------|---------------------------|--------|
| write.py | `LangChainLLMClient` / `LangChainPromptManager` / `SQLiteChapterRepository` / `SQLiteProjectRepository` / `WritingService` / `NullContextProvider` | 仅 `ensure_kernel` + `InkFlowHTTPClient` + 少量 DTO（WritingRequest 可保留用于参数校验，**不 import 服务层/仓储/LLM**） |
| project.py | `ProjectService` / `async_session_factory` / `create_tables` / `Genre` | `ensure_kernel` + `InkFlowHTTPClient` + `Genre`（枚举转换保留） |
| 其余 12 个 | 各自 Service / Repository / session 工厂 | 同上模式 |

> **验收判据（import 面）**：改造后 `python -c "import inkflow.cli.commands.project"` 不触发 `inkflow.domain.services` / `inkflow.infrastructure.llm` / `inkflow.infrastructure.database` 导入（§13 M1 用 sys.modules 断言）。这是 ADR-030「~214ms 热调用」的机制保障——**import 面缩小是本质，不是可选项**。

---

## 6. 组织规则

### 6.1 依赖方向

```text
✅ cli/commands/*.py → infrastructure/http/ → (构造) infrastructure/kernel KernelHandle
✅ cli/commands/*.py → infrastructure/kernel（ensure_kernel）
❌ infrastructure/http/ → cli/ 任何模块（S8 约束，零反向依赖）
❌ cli/commands/*.py → domain/services/、infrastructure/database/、infrastructure/llm/（import 面收敛）
```

### 6.2 token 传递

- token 仅存在于 `KernelHandle`（ensure_kernel 返回）→ `InkFlowHTTPClient` 请求头
- **禁止** CLI 命令层直接读 kernel.json 拿 token（绕过 ensure_kernel = 绕过三态判定）
- token 不落 CLI 日志、不输出到 stdout/stderr（F19/F30 安全基线延续）

### 6.3 日志

- 命令层：无新增日志（CLI 一次性进程，错误走 print_error）
- `InkFlowHTTPClient`：可选 `logger.debug`（请求方法/路径/状态码），默认不输出（避免污染 --json 输出）
- 内核侧日志照旧（`%TEMP%\inkflow-kernel.log`，F30 §6.2）

### 6.4 零 cli 依赖约束（S8）

- `infrastructure/http/` 的 `__init__.py` / `client.py` / `errors.py` **不得出现 `inkflow.cli` import**
- 验证：§13 M1 测试断言 `import inkflow.infrastructure.http` 后 `sys.modules` 无 `inkflow.cli` 键；CI lint 可加 grep 检查（可选）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 | 错误码 |
|---|------|------|--------|
| 1 | 内核未运行（kernel.json 不存在） | ensure_kernel 互斥拉起 → 正常调用（首次 ~4.7s） | — |
| 2 | 内核崩溃残留（pid 死） | F30 stale 判定 → 清理 → 重新拉起 | — |
| 3 | 冷启动超时 / 内核秒退 | KernelStartupError → `KERNEL_ERROR` + 日志指引 | KERNEL_ERROR |
| 4 | 两个 CLI 同时冷调用 | F30 CreateMutexW 183 → 轮询 → 复用（F30 §5.3 已覆盖） | — |
| 5 | 请求时内核刚退出（连接拒绝） | 单次重试：重新 ensure_kernel → 复用新内核或拉起 → 重发请求；仍失败 → `KERNEL_ERROR` | KERNEL_ERROR |
| 6 | 请求超时（30s） | httpx.TimeoutException → INTERNAL_ERROR（message 含「请求超时」） | INTERNAL_ERROR |
| 7 | HTTP 404 | → NOT_FOUND（detail 透传） | NOT_FOUND |
| 8 | HTTP 422（参数校验） | → VALIDATION_ERROR（detail 透传） | VALIDATION_ERROR |
| 9 | HTTP 401（token 失效） | → CONFIG_ERROR（提示重启内核；罕见——ensure_kernel 已校验健康） | CONFIG_ERROR |
| 10 | HTTP 500 + LLM_ERROR 头 | → LLM_ERROR（write 流式/非流式） | LLM_ERROR |
| 11 | HTTP 500 无头 | → INTERNAL_ERROR（message = detail 文本） | INTERNAL_ERROR |
| 12 | SSE 流中 error 帧 | → LLM_ERROR（F23 §7 E3） | LLM_ERROR |
| 13 | SSE 流中断（网络/内核退出） | HttpApiError → INTERNAL_ERROR（message 含「流中断」） | INTERNAL_ERROR |
| 14 | Ctrl+C（写命令流式中） | KeyboardInterrupt → 流式上下文关闭 → 退出码 130 | — |
| 15 | `inkflow --help` / `--version` / 未知命令 | **不触发 ensure_kernel**（惰性接线，§4.1） | exit 2（用法错误） |

---

## 8. 文件结构（源码核实，2026-08-09）

```text
backend/src/inkflow/
├── infrastructure/
│   ├── kernel/                       ← F30 既有（ensure_kernel/KernelHandle/kernel.json）
│   └── http/                         ← CREATE: 传输层（Q1=A）
│       ├── __init__.py               ← CREATE: 导出 InkFlowHTTPClient / HttpApiError / map_http_error
│       ├── client.py                 ← CREATE: httpx.AsyncClient 封装（base_url/token/超时/SSE 流式）
│       └── errors.py                 ← CREATE: HTTP 状态 → F7 错误码映射（§5.3 表）
├── api/
│   └── routers/
│       └── writing.py                ← MODIFY: _map_service_error 500 LLM 分支加 X-InkFlow-Error-Code 头（1 行）
├── cli/
│   ├── app.py                        ← MODIFY: 命令注册不变；确认 import 面收敛（§4.1/§5.5）
│   └── commands/
│       ├── project.py                ← MODIFY: 数据源替换（HTTP），签名不变
│       ├── chapter.py                ← MODIFY: 同上
│       ├── character.py              ← MODIFY: 同上
│       ├── world.py                  ← MODIFY: 同上（f35-f37 端点）
│       ├── outline.py                ← MODIFY: 同上
│       ├── timeline.py               ← MODIFY: 同上
│       ├── foreshadowing.py          ← MODIFY: 同上
│       ├── extract.py                ← MODIFY: 同上
│       ├── audit.py                  ← MODIFY: 同上
│       ├── style.py                  ← MODIFY: 同上
│       ├── vector.py                 ← MODIFY: 同上
│       ├── agent_cmd.py              ← MODIFY: 同上
│       ├── session.py                ← MODIFY: 同上
│       ├── write.py                  ← MODIFY: 核心改造（SSE 流式，§5.4）
│       ├── serve.py                  ← 豁免（§1.3）零改动
│       ├── kernel.py                 ← 豁免（§1.3）零改动
│       ├── config_cmd.py             ← 豁免（§1.3）零改动
│       └── llm.py                    ← 豁免（§1.3）零改动
backend/tests/
├── unit/
│   └── test_http_client.py           ← CREATE: mock httpx 轨（base_url/token 注入、错误映射表、
│                                        SSE 流式转发、零 cli import 断言）——自动覆盖，无需改 ci.yml
└── cli/
    ├── test_cli_*.py（22 个改造）     ← MODIFY: 直连 mock → HTTP mock 轨（§9.1）
    ├── test_cli_config.py            ← 豁免（§1.3）零改动
    ├── test_cli_llm.py               ← 豁免（§1.3）零改动
    ├── test_cli_kernel.py            ← 豁免（§1.3）零改动
    ├── test_cli_serve.py             ← 豁免（§1.3）零改动
    └── test_cli_http_kernel.py       ← CREATE: 真实内核轨（M5；显式加入 ci.yml integration-cli-backend）
tests/api/
    └── test_writing_api.py 等        ← MODIFY: writing 响应头断言补充（§3.3）
```

> **测试文件改造清单（22 个，源码核实）**：test_cli_project / project_mock / chapter / chapter_mock / writing / write / agent / output（不改？——test_cli_output 测信封函数，不涉数据源，**豁免**）/ character_crud / character_relations / character_errors / world / outline / timeline_crud / timeline_ops / foreshadowing / extraction_crud / extraction_errors / vector / audit / style / session / session_coverage——逐文件核对数据源 mock 方式后改造（§9.1 双轨）。

> **⚠️ CI 落点（QA 评审 🟡-6）**：`tests/cli/test_cli_http_kernel.py`（真实内核轨）**必须显式加入 ci.yml `integration-cli-backend` job 文件列表**（Windows pytest 不展开 glob，Issue #59/#61 教训）；22 个改造文件仍在原 job 列表（路径不变，无需改 ci.yml 列表本身，但需确认改造后仍被收集）。

---

## 9. 测试策略（Q2=A 双轨）

### 9.1 mock 轨（主轨，自动覆盖）

```text
单元测试（unit-test-backend 自动覆盖）:
  test_http_client.py（~14 cases）
    - base_url = http://127.0.0.1:{port}/api/v1（KernelHandle port 注入）
    - X-InkFlow-Token 请求头（KernelHandle token 注入）
    - 2xx → 返回 JSON body（dict/list，不做信封包装）
    - 404/422/401 → HttpApiError(status_code, detail)
    - 500 + X-InkFlow-Error-Code: LLM_ERROR → HttpApiError(code="LLM_ERROR")
    - 500 无头 → HttpApiError(code=None)
    - map_http_error 全表（§5.3）：404→NOT_FOUND / 422→VALIDATION_ERROR / 401→CONFIG_ERROR /
      500+LLM_ERROR 头→LLM_ERROR / 500 无头→INTERNAL_ERROR
    - stream_sse：SSE 帧解析（delta 帧拼接、done 帧字段、error 帧）
    - 零 cli import 断言（import inkflow.infrastructure.http 后 sys.modules 无 inkflow.cli）

CLI 测试（22 个既有文件改造，mock ensure_kernel + InkFlowHTTPClient）:
  - patch "inkflow.infrastructure.kernel.ensure_kernel" → fake KernelHandle
  - patch "inkflow.infrastructure.http.client.InkFlowHTTPClient" → fake client（预置响应 JSON / 抛 HttpApiError）
  - 断言：参数 → 请求 body 映射 / 响应 → 信封 / 错误 → 错误码 + 退出码 1
  - 改造示例见 test_cli_project_mock.py 既有模式（服务 mock → 客户端 mock）
```

> **⚠️ 既有 CLI 测试的 mock 目标迁移**：22 个文件当前 patch 的是 domain Service/Repository（如 `ProjectService.create_project`）——改造后命令不再 import 服务层，**patch 目标整体更换为 ensure_kernel + InkFlowHTTPClient**（F19 #77 全文件重写先例：同根因失败 = 测试自身无缺陷判据适用）。豁免的 5 个测试文件（config/llm/kernel/serve/output）零改动。

### 9.2 真实内核轨（少量集成）

```text
test_cli_http_kernel.py（~4 cases，显式加入 ci.yml integration-cli-backend job）:
  - 无内核 → CLI 命令（真实 ensure_kernel）→ 自动拉起 → 调用成功（M5 自动拉起）
  - 复用路径：预置健康内核 → 二次调用 pid 不变（M5 复用）
  - 真实内核 fixture 先例：tests/cli/test_cli_kernel.py（F30，但该文件不拉起内核）——
    本文件使用 F30 M5 手工验证脚本模式（backend/tests 或临时脚本）的自动化形态
```

> **真实内核轨的启动成本**：每次起真实内核 ~4.7s——控制在 4 cases 内（CI 时长预算）；测试串行（mutex 防并发双内核）。
>
> **⚠️ CI 环境 skip（PR #213 实测修正）**：GitHub Actions Windows runner 沙箱
> （Session 0）中 `sys.executable -m inkflow serve` 拉起后秒退（KernelStartupError
> 「内核启动后立即退出」×3 次重试；本机 Windows 11 3.11/3.13 均正常）。真实内核
> 轨 3 用例（TestEnsureKernelReal ×2 + TestHttpClientReal ×1）加
> `skipif(CI=true)`——对齐 §9.3「M5 延迟验证不入常规 CI」；mock 轨
> （TestNoSpawn ×2）留 CI。M5 验收由本机运行本文件全绿 + §9.3 手工基准承担。

### 9.3 延迟验证（M5，不入常规 CI）

```text
热调用 ≤100ms 手工基准（governance 实测方法论）:
  - 进程内 httpx 测（curl.exe 是外部进程，混入 20-50ms 启动开销——禁止）
  - 步骤: 内核常驻 → uv run python 脚本（httpx 进程内 GET /api/v1/projects ×10）→ 中位数 ≤100ms
  - 环境抖动会假红 → 手工基准不入 CI（骨架 Q2=A 已确认）
```

### 9.4 契约断言行（评审要求）

- 零 cli 依赖：`import inkflow.infrastructure.http` → `"inkflow.cli" not in sys.modules`（M1）
- import 面收敛：`import inkflow.cli.commands.project` → `sys.modules` 无 `inkflow.domain.services` / `inkflow.infrastructure.llm` / `inkflow.infrastructure.database`（M1）
- 豁免命令零改动：serve/kernel/config/llm 模块与测试文件 `git diff` 为空（M4 核查）
- 错误码表：§5.3 每行一个断言（unit 层 map_http_error 参数化）

### 覆盖率目标

新增代码（http/ 层 + 改造命令）行覆盖 ≥ 80%；全仓门禁 ADR-027：后端 98.5/95.0——改造后既有 CLI 测试全绿维持门槛（QA 阶段主 agent 全仓跑 `uv run ruff check src/ tests/unit/ ../tests/` + `pytest` + `check_coverage.py 98.5 95.0`）。

---

## 10. 不在范围内

| 项 | 原因 | 归属 |
|----|------|------|
| 内核生命周期管理 | F30 已交付 | #166 ✅ |
| GUI 托盘/常驻 | 独立前端模块 | #167（0.5.0） |
| CLI 独立打包产物 | F33 已交付 | #168 ✅ |
| MCP 薄客户端 | 消费 ensure_kernel + 本模块 http/ 层 | F20（1.0.0） |
| config/llm 命令 HTTP 化 | 无对应端点 + 本地文件语义（§1.3） | 云端模式（F18）时再评估 |
| 全量 API 错误码响应头 | 影响面过大；仅 writing 扩展（§3.3） | 未来按需（F20 MCP 需求驱动） |
| API 层错误响应体结构化（detail → {code, message}） | 契约变更影响全部 API 测试 | 未来统一（登记 #169 评审 🟡-4 后续） |
| CLI 连接池/常驻会话 | 一次性进程无复用价值 | 永不（YAGNI） |
| 断点续传/流式重连 | F23 §10 已声明 MVP 不做 | F23 远期 |

---

## 11. 依赖关系

```text
F38 依赖:
  F30（kernel bootstrap） — ensure_kernel/KernelHandle（复用，零改动）
  F19（serve）            — 内核进程 + INKFLOW_READY/端口文件/token（消费，零改动）
  F7（CLI 约定）          — 信封/退出码/错误码（契约冻结；INTERNAL_ERROR/KERNEL_ERROR 为新增行）
  F23（SSE 流式）         — /writing/stream 帧协议（消费，零改动）
  F32（settings）         — 消费 GET/PATCH /api/v1/settings（若 CLI 将来需要）——当前 config 豁免，仅声明

F38 被依赖:
  F20（MCP）              — 复用 infrastructure/http/ 客户端层（Q1=A 设计目标，1.0.0）
  ADR-022（skills）       — skills 冷启动说明可复用本模块接线模式

编号口径声明：本模块为 ADR-030 落地拆分 issue（#169），非 PRD F 系列新业务模块——「F38」编号承接
（f34 已由 #208 章节审计占用，用户拍板方案 A 改号；f35-f37 世界观三连引用已同步）。模块类型谱系
第 18 变体「CLI 传输层改造型」（编号依据 AGENTS.md 谱系：F30=13/F32=14/F21=15/F22=16/F34章节审计=17）。
若与未来编号冲突以 ADR-019 v5+ 为准。
```

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|-------------|
| D1 | HTTP 客户端层位置 | `infrastructure/http/`（Q1=A） | 跨 CLI/MCP/skills 复用；依赖方向合法；MCP 薄客户端直接复用 | `cli/` 内私有模块（反向依赖）；直连（ADR-030 否决） |
| D2 | 测试双轨 | mock httpx 主轨 + 少量真实内核（Q2=A） | 快/稳/隔离 + M5 真实验证；27 文件改造可控 | 全真实内核（慢、CI 时长）；纯 mock（无真实验证） |
| D3 | 零 cli 依赖 | http/ 不 import cli（S8） | MCP 复用前提；分层正确性 | 无约束（复用即坏） |
| D4 | 错误码缺口 | writing router 加 `X-InkFlow-Error-Code` 头（仅 LLM_ERROR）+ 500 兜底 INTERNAL_ERROR | write 是高频 LLM 路径需保留 LLM_ERROR；全量扩展影响 17 router 数百断言；INTERNAL_ERROR 兜底语义正确 | 全量响应头（影响面过大）；CLI 侧文本匹配（脆弱，骨架否决）；detail 结构化（契约全变） |
| D5 | 豁免命令 | serve/kernel status/config/llm 四组豁免（§1.3） | serve 自指；kernel status 查询≠拉起；config/llm 无对应端点 + 本地文件共享 data_dir | 全命令强制 HTTP（config/llm 需新增端点，超范围） |
| D6 | ensure_kernel 接线点 | 命令函数内惰性接线（§4.1/§5.1） | `--help`/`--version`/serve 不应触发拉起；callback 顶层接线在参数解析前执行会误触发 | app callback 顶层接线（help 误拉起内核） |
| D7 | 连接失败单次重试 | 请求连接拒绝 → 重新 ensure_kernel → 重发（1 次） | 内核退出与请求竞态（F19 崩溃拉起同族）；单次防抖 | 无限重试（卡死）；不重试（体验差） |
| D8 | 命令 import 面收敛 | 命令模块移除服务层/仓储/LLM import | ADR-030 性能本质（4.7s→214ms 的机制保障） | 保留 import（性能收益归零） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | HTTP 客户端层（`infrastructure/http/`） | `pytest backend/tests/unit/test_http_client.py -v` 全绿（base_url/token 注入、错误映射表、SSE 流式转发、**零 cli import 断言**、**命令 import 面收敛断言**） |
| M2 | 顶层接线 + 14 个命令改造 | mock 轨：改造后 22 个 CLI 测试文件全绿（分布 5 个 job 逐个验证）；**serve/kernel/config/llm 4 个豁免命令模块与测试 git diff 为空**；真实轨：M5 |
| M3 | 错误映射（HTTP 状态 → F7 错误码） | unit 测试全绿（404→NOT_FOUND、422→VALIDATION_ERROR、401→CONFIG_ERROR、500+LLM_ERROR 头→LLM_ERROR、500 无头→INTERNAL_ERROR、连接失败→KERNEL_ERROR、内核拉起失败→KERNEL_ERROR） |
| M4 | 既有 CLI 测试改造 + writing 响应头 | 22 个改造文件全绿（mock 轨）+ `tests/api/test_writing_*.py` 响应头断言补测全绿；豁免文件零改动 |
| M5 | 真实内核集成 + 自动拉起 + 热调用延迟 | `tests/cli/test_cli_http_kernel.py` 全绿（无内核 → 自动拉起 → 调用成功；复用路径 pid 不变）且**已显式加入 ci.yml integration-cli-backend**；热调用 ≤100ms 手工基准（进程内 httpx，中位数） |
| M6 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；ADR-027 门槛（98.5/95.0）；`uv run ruff check src/ tests/unit/ ../tests/ --no-cache` + mypy 通过；CI 全绿（含 integration-cli-backend 改造后 job） |

> Issue #169 验收标准映射：信封一致 = M1/M4；自动拉起 = M5；错误码/退出码映射 = M3；既有 CLI 测试通过 = M4；热调用 ≤100ms = M5。

---

## 待澄清问题

| # | 问题 | 影响 | 结论 |
|---|------|------|------|
| Q1 | HTTP 客户端层放哪？`infrastructure/http/`（跨 CLI/MCP/skills 复用）vs `cli/` 内私有模块？ | 影响 F20 MCP 薄客户端复用面 | ✅ 已确认（2026-08-09 拍板：**选项 A**）——**infrastructure/http/**（§8/§12 D1） |
| Q2 | 既有 CLI 测试改造策略？mock httpx（快、隔离）vs 起真实内核集成（真、慢）？ | 影响 27 个测试文件的改造量与 CI 时长 | ✅ 已确认（2026-08-09 拍板：**选项 A**）——**双轨：单元 mock + 少量真实内核集成（M5）**（§9/§12 D2） |
| Q3 | 豁免命令范围？serve/kernel status/config/llm 四组豁免（§1.3 源码论证）vs 全命令强制 HTTP？ | 影响 ADR-030 字面一致性 vs 端点现实 | **按 §1.3 执行**（spec 补全时裁决，非待拍板项）：serve 自指/query≠拉起/config-llm 无端点三项硬约束；若用户要求全强制，config/llm 需新增端点（另立 issue） |

---

*本文件为 F38 功能规格（What），实施步骤（How）见 `.hermes/plans/` 执行计划。所有里程碑验收以本节 M1-M6 为准。*

---

## 14. 动作确认

> 每个命令/错误路径的完整状态流表（基于 §3 API 契约 + §4 CLI 接线 + §5 传输层 + §7 边界事实，不重复）。

### 14.1 CLI 命令状态流（14 个业务命令统一接线）

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow <业务命令>（14 个：project/chapter/character/world/outline/timeline/foreshadowing/extract/audit/style/vector/agent/session/write） | 无 | ensure_kernel（复用/互斥拉起）→ InkFlowHTTPClient → HTTP → print_result | 人类/JSON 双模式（F7 信封不变） | HttpApiError → print_error（信封 + 退出码 1）；KernelStartupError → KERNEL_ERROR | 命令签名零变化；参数→请求体映射（--name→name、--target-words→target_words）；命令内不再 create_tables/async_session_factory/构造 Service |
| inkflow write（SSE 流式） | 同上 | POST /writing/stream：delta 帧拼接（人类模式逐 delta 打印）→ done 帧 → WritingResult | 完整正文 + done 帧字段（format_valid/word_count/model/token_usage/warnings） | 流中 error 字段 → LLM_ERROR；流中断 → INTERNAL_ERROR（message 含「流中断」） | 流式超时 timeout=None（帧间隙由内核心跳保证）；Ctrl+C → 退出码 130；非流式端点 generate/continue/revise 兜底 |
| inkflow serve | — | 豁免（内核启动者本身） | — | — | F19 契约（INKFLOW_READY/--port-file/token）零改动 |
| inkflow kernel status | — | 豁免（绝不拉起内核的纯状态查询） | — | — | 查询≠拉起语义（走 HTTP 会破坏） |
| inkflow config show/set | — | 豁免（操作本地 config.json，API 无对应端点） | — | — | CONFIG_WHITELIST 与 /settings 的 AppSettings 键集合完全不同；与内核共享 data_dir |
| inkflow llm list/set-key | — | 豁免（操作本地 keys/，无 key 状态读取端点） | — | — | APIKeyManager AES-256-GCM；共享 data_dir |
| inkflow agent tools list | — | 豁免（本地静态枚举，API 无对应端点） | — | — | 不启动内核、不发 HTTP |
| inkflow --help / --version / 未知命令 | — | 不触发 ensure_kernel（惰性接线） | — | exit 2（用法错误） | 接线点在命令函数内部（app callback 顶层在参数解析前执行会误触发拉起） |

### 14.2 错误映射状态流（HTTP 状态 → F7 错误码）

| 场景 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| HTTP 404 | 实体不存在 | map_http_error | — | NOT_FOUND | detail 文本透传；兜底「资源不存在」 |
| HTTP 422 | 参数非法/枚举错误/缺失字段 | map_http_error | — | VALIDATION_ERROR | 兜底「参数校验失败」 |
| HTTP 401 | token 失效 | map_http_error | — | CONFIG_ERROR（提示重启内核） | 罕见（ensure_kernel 已校验健康）；兜底「鉴权失败」 |
| HTTP 500 + X-InkFlow-Error-Code: LLM_ERROR | write LLM 失败 | map_http_error | — | LLM_ERROR | 仅 writing router 响应头（约 1 行扩展） |
| HTTP 500 无头 | DB/未知内部错误 | map_http_error | — | INTERNAL_ERROR（新增码） | 兜底「内部错误（无详情）」；DB_ERROR/CONTEXT_BUDGET_EXCEEDED 恒 HTTP 后由 INTERNAL_ERROR 兜底 |
| 连接拒绝（内核刚退出） | 请求时内核退出 | 单次重试：重新 ensure_kernel → 重发请求 | 重试成功 | KERNEL_ERROR | 单次防抖；建议「内核可能已退出，重试将自动拉起」 |
| 请求超时（30s 默认） | — | httpx.TimeoutException → HttpApiError | — | INTERNAL_ERROR | message 含「请求超时」 |
| ensure_kernel 失败 | 冷启动超时/秒退/spawn 失败 | KernelStartupError | — | KERNEL_ERROR | 文案 + %TEMP%\inkflow-kernel.log 指引 |
| 内核未运行（首次调用） | 无 kernel.json | ensure_kernel 互斥拉起 | 正常调用（首次 ~4.7s；复用 ~19ms；热调用 ≤100ms 基准） | — | 双 CLI 同时冷调用 → F30 互斥 183 → 轮询复用 |

### 14.3 验收锚点（写入 §13 验收标准）

- A1：改造后 import inkflow.cli.commands.project 不触发 domain.services / llm / database（sys.modules 断言）→ M1
- A2：错误映射表 §5.3 每行一个断言（map_http_error 参数化）→ M3
- A3：无内核 → CLI 命令自动拉起 → 调用成功；预置健康内核 → 二次调用 pid 不变 → M5
- A4：serve/kernel/config/llm 四组豁免命令模块与测试文件 git diff 为空 → M4
- A5：热调用 ≤100ms 手工基准（进程内 httpx 中位数，不入 CI）→ M5
- A6：write 流中 error 帧 → LLM_ERROR；流中断 → INTERNAL_ERROR（含「流中断」）→ M3
