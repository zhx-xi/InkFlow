# F60: 首次启动模型配置引导（first_run_guide）— 功能规格

> **端**: cross（后端 readiness 判据 + GUI 引导向导 + CLI 状态提示行）

> **Spec 版本**: 1.0 | **日期**: 2026-09-10 | **依据**: Issue #934（0.14.0 milestone）

> **所属阶段**: 0.14.0（#934，W8-S2）

> **关联 Issues**: #934（本模块）；#929（技术兜底：删静默 fallback + 422 引导，已 closed）；#474（模型未配置前置校验 `ensureModelReady`/`hasChatModel` 先例）；#770（轻量契约先例：能用既有机制作锚点就不新增字段）；#936（技术面一致性，同碰 provider_config_service.py，须与本单串行）

> **依赖**: ✅ F19 #106（ProviderConfig 注册表 + ModelsPanel/ProviderDialog）· ✅ F19 #79（settings/llm-keys + settings/llm/test 工具端点）· ✅ F32 #152（设置持久化，本模块复用 settings 域不新增设置键）· ✅ #474（`hasChatModel` 判据 + `ensureModelReady` 前置校验）· ⏳ 无

> **参考 ADR**: [ADR-030](../../adr/kernel/ADR-030.md)（内核进程化）· [ADR-021](../../adr/kernel/ADR-021.md)（token 中间件 401 契约）· [ADR-049](../../adr/llm/ADR-049.md)（LLM 装配 fail-fast 原则）· [ADR-051](../../adr/llm/ADR-051.md)（litellm 统一出口）· [ADR-027](../../adr/test-ci/ADR-027.md)（覆盖率门禁）

> **状态**: 🚧 实施中（#934）

---

## 1. 概述

#929 实证：book run「开始写作」被阻断的根因是 LLM 模型装配走了错误的静默 fallback（全局默认为空 → 遍历注册表取 `models[0]` 不筛 type → zhipu `embedding-3` 被当 chat 装配 → 400 裸串直达用户）。#929 已修（删 final fallback + 422 引导），**但 fail-fast 只是兜底，不是产品体验**——新装用户 / 修改数据目录后第一次启动，依然面对「配置在哪、必须配什么、不配会怎样」零指引。

F60 从**流程面**根治：让「配置模型」成为首启必经步骤，而非等主路径炸出来。

### 1.1 需求追溯：用户说的 vs 根源问题

| # | 需求表述（Issue #934 body） | 根源问题 | 本模块处置 |
|---|------------------------------|----------|------------|
| R1 | 新装 / 改数据目录后首启应出现引导 | **没有「配置就绪」的可查询判据**——就绪状态只存在于用户脑子里，主路径靠运行时炸出来 | 新增后端 `GET /api/v1/settings/model-readiness`，把「是否已具备可解析 chat 模型 + key」变成**可查询的唯一判据**（§3.1）；GUI 以此驱动引导门控 |
| R2 | 引导内容：Provider + Key → chat 模型 → embedding 模型 | 用户有 `ProviderDialog`/`ModelsPanel` 全套能力，但**入口散落在设置页深处**，首启无路径指引进不去 | 引导向导复用既有 ProviderDialog/注册表端点（不重造配置能力），把三步串成首启最小闭环（§5） |
| R3 | embedding 可跳过，跳过后 RAG 置灰 | 现状 embedding 缺失时 RAG 静默失败/无提示 | 引导显式声明「可跳过」；跳过 → 语义检索入口**置灰 + 标注**（不阻断写作主路径）（§5.4 N2） |
| R4 | 已有配置升级启动不弹引导 | 若引入「已完成首启」标志位，**升级用户 = 无标志位 = 被误弹**（且需要 schema 迁移） | **不引入标志位**：判据恒为「当前是否具备可解析 chat 模型 + key」——升级用户天然满足 → 零打扰（§3.2，参照 #770 轻量契约先例） |
| R5 | 主路径给可操作错误而非 422 裸文案 | 422 detail 是给开发者看的，用户看到「未配置默认模型」**无跳转无动作** | 前端 LLM 主路径（书运行/发送）已捕获 422 → 升级为「请先完成模型配置」+ 跳转引导入口（§5.5 N1） |
| R6 | CLI `config show` 输出引导状态提示行 | CLI 用户看不到就绪状态 | `inkflow config show` 增加 `model_ready` + 提示行（非强制向导，GUI 是主路径）（§4） |

**伪需求三问自检**（谁用/何时用/为何用）：消费方 = 首启 GUI 用户（主要）+ CLI 用户（状态可见性）；场景 = 全新安装第一次启动、`config set data-dir` 切换到空目录后第一次启动；为何 = 「我装了工具，第一次打开该告诉我必须先配模型，而不是等我写书时炸」。无无人值守/定时类伪需求成分。✅ 通过。

### 1.2 模块类型定位（第 15 变体：首启门控型）

按 AGENTS.md 模块类型谱系计数（f15=6 / f16=7 / f23=8 / f19=9 / f26=10 / f24=11 / f25=12（已移除）/ f30=13 / f32=14），本模块为 **第 15 变体「首启门控型」**：不新增业务实体、不新增设置键，提供**单一就绪判据端点** + **GUI 首启门控向导**，横切改造 GUI 启动时序。

```
provider_configs（既有注册表） + APIKeyManager（既有 key 存储）
        └──▶ GET /api/v1/settings/model-readiness（单一就绪判据，只读）
                ├──▶ App.tsx 启动门控（!ready 且未跳过 → SetupGuide）
                ├──▶ 语义检索入口置灰（embedding 未配 → 提示）
                └──▶ CLI config show 状态行
```

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ 无（零 schema 变更——就绪判据是派生计算，不落库） |
| 新 API 端点 | ✅ 1 个：GET /api/v1/settings/model-readiness（挂既有 settings router） |
| 新 CLI 命令 | ❌ 无（仅 `config show` 加字段 + 提示行） |
| 核心机制 | 派生就绪判据（chat 模型存在性 + key 存在性）+ GUI 首启门控 + 嵌入能力降级标注 |
| 跨模块 MODIFY | ✅ 后端 settings router + `_llm_resolver.py`（错误文案）+ CLI config_cmd；前端 App.tsx + 新 SetupGuide 组件 + 语义检索入口 + i18n |

### 1.3 边界声明

- **不做** CLI 交互式引导向导——GUI 是主路径（issue 原文），CLI 只给状态提示行
- **不做**「已完成首启」标志位 / 设置键——判据恒为实时派生（§3.2 R4 论证）
- **不做**数据目录迁移时的配置复制——旧数据不迁移是既有拍板（#266 方案 A）
- **不做** provider 保存前的连通性门禁——那是 #936 C 项（技术面），须与本单串行
- **不做**引导内的模型连通自动重试策略——失败留在当前步骤可手动重试（N5）
- **不做** embeddings 的自动探测/自动配置——embedding 明确为「可跳过」

---

## 2. 数据模型

**零新实体、零新表、零新设置键。** 就绪判据是**派生计算**，数据源为既有两处：

| 数据源 | 用途 | 证据 |
|--------|------|------|
| `provider_configs` 注册表 | 是否存在 `type == "chat"` 的模型条目 | `ProviderConfig.models[].type`（`domain/models/provider_config.py:48`） |
| `APIKeyManager.list_providers()` | 该 provider 是否已存 key | `routers/provider_configs.py:129`（`key_saved` 计算同源） |

> **为什么派生而不落库**（#770 轻量契约先例对齐）：若落库为 `first_run_completed` 标志位，则「用户后来删光了 provider / 清了 key」时标志位仍为 true → 引导永不出现，主路径继续炸。派生判据天然自愈。代价 = 每次启动多一次注册表读（SQLite 本地，可忽略）。

### 2.1 就绪判据定义（唯一真相）

```python
def is_model_ready(providers: list[ProviderConfig], saved_provider_names: set[str]) -> bool:
    """是否已具备可解析 chat 模型 + 有效 key（#934 唯一判据）。

    成立条件：存在 provider 同时满足
      (1) 该 provider 名在已存 key 集合中（key_saved 语义）
      (2) 该 provider 的 models 中存在至少一个 type == "chat" 的条目
    """
```

> **#1129 修订（阻断级修复，2026-09-12）**：上面的单源判据只查 `models[]`，与写作链
> 真实可用性（`resolve_model(None, project.config.model, config.llm_default_model)`，
> `api/_llm_resolver.py:37`）脱节。正常路径（`llm set-key` 只写 key；`#735 D2` 自动设默认
> 只写内存单例 + config.json，**从不回写 models[]**，`provider_config_service.py:226-233`）
> 会拿不到 chat 条目 → 判据恒 false → GUI 引导页锁死且无出路。
> **判据收敛为多源 OR（任一命中即可用）**，与写作链同真相：

```python
def is_chat_model_resolvable(
    model: str | None,
    providers: list[ProviderConfig],
    saved_provider_names: set[str],
    *,
    builtin_providers: dict[str, str | None] | None = None,
) -> bool:
    """#1129：唯一「可解析 chat 模型」谓词 —— readiness 与下拉/写作链共用。

    (1) model 非空白且形如 provider/model（按首个 "/" 切分）
    (2) 该 provider 有可用凭据（saved_provider_names ∪ builtin_providers）
    (3) 注册表**确知**该模型 type=="embedding" → False（#929 R1 不得回归）；
        注册表未登记 = 未知 = 放行（镜像 _llm_resolver 误伤防御）
    """

# compute_readiness(providers, saved, *, project_models, global_default, builtin_providers)
#   数据源（任一可解析即 ready=True）：
#     src1 注册表 chat 条目（#934 既有语义）
#     src2 project_models（各项目 config.model）
#     src3 global_default（config.llm_default_model）
```

**判据的边界语义**（显式声明，防静默歧义）：

| 场景 | ready | 论证 |
|------|-------|------|
| 无任何 provider | False | 真·全新安装 |
| 有 provider 含 chat 模型但无 key | False | 缺凭据 = 主路径必炸（#821 空 key 守卫语义） |
| 有 provider 有 key 但只配了 embedding 模型 | **False** | **#929 精确缺陷形态**——embedding 模型不能当 chat 消费（`ProviderDefault.type` 注释 `provider_config.py:65`） |
| 有 provider 有 key + chat 模型 | True | 可解析（连通性由引导内 llm/test 显式验证，不在判据内做网络探测——判据须无 I/O、可缓存、可单测） |
| 全局默认模型为空但注册表有可用 chat 模型 | **True** | #735 D2 自动设默认已在 `provider_config_service.create` 保证「首个含 chat 的 provider 新增且全局默认为空 → 自动设为该模型」（`provider_config_service.py:226-233`），故注册表可用 = 可解析 |
| **仅 provider.default_model / 全局默认可解析 + 有 key（models[] 空）** | **True**（#1129） | 写作链真实可跑（`resolve_llm_credentials` 只依赖模型名 + key），判据必须同真相 |
| **仅 project.config.model 可解析 + 有 key（models[] 空）** | **True**（#1129） | 项目级模型是写作链最高优先级（#735 project > global） |
| **project/global 模型名指向注册表确知 embedding** | **False**（#1129 反例） | 不得从 readiness 侧重开 #929 的 embedding 误装配通道 |
| **有可用模型名但该 provider 无任何 key 来源** | **False**（#1129 反例） | 「可解析」= 模型名可解析 **且** 凭据可用 |

> **判据不含网络探测**的设计理由：readiness 是高频查询（GUI 启动 + 门控），探测是低频显式动作（引导步骤内 + ProviderDialog 手动）。混在一起会让启动依赖外网可达性 → 离线用户被误挡在引导里。**连通性验证发生在引导流程内**（步骤 2 完成判据之一，§5.3）。

---

## 3. API 契约

### 3.1 GET /api/v1/settings/model-readiness

**归属**：本模块（挂既有 settings router，`api/routers/settings.py`，与 llm-keys/llm/test 同文件）。

| 项 | 值 |
|----|-----|
| 方法 | GET |
| 路径 | `/api/v1/settings/model-readiness` |
| 请求体 | 无 |
| 成功响应 | 200 `ModelReadiness`（下） |
| 异常 | 401（token 缺失/无效，全站中间件 ADR-021）；500（DB 异常通用文案，ADR-012 风格） |

**响应体（Pydantic 模型 `ModelReadiness`，`domain/models/model_readiness.py`）**：

```json
{
  "ready": false,
  "has_chat_model": false,
  "has_embedding_model": false,
  "reason": "no_chat_model"
}
```

| 字段 | 类型 | 语义 |
|------|------|------|
| `ready` | `bool` | 是否可进入写作主流程（§2.1 判据） |
| `has_chat_model` | `bool` | 是否存在「有 key 且有 chat 模型」的 provider（= `ready` 的分量，GUI 步骤 2 完成判据） |
| `has_embedding_model` | `bool` | 是否存在「有 key 且有 embedding 模型」的 provider（GUI 步骤 3 / RAG 置灰判据） |
| `reason` | `Literal["ready","no_provider","no_chat_model","no_key"] \| null` | 未就绪原因（`ready=true` 时为 `"ready"`；供 GUI 定位引导起始步骤 + 诊断） |

`reason` 取值语义（**互斥，按优先级降级**）：

| reason | 触发条件 | GUI 行为 |
|--------|----------|----------|
| `"ready"` | `ready=true` | 不弹引导 |
| `"no_provider"` | 注册表无任何 provider | 从步骤 1 开始 |
| `"no_chat_model"` | 注册表**全无** chat 模型条目（不论 key） | 从步骤 1（配置模型）开始 |
| `"no_key"` | 存在 chat 模型条目，但无任一 provider「有 chat 模型 + 有 key」 | 从步骤 1（录入 key）开始 |

> **优先级判据的精确定义**：`no_chat_model` 只看「注册表里**有没有** chat 条目」（与 key 无关）——只要某处配了 chat 模型，缺的就是 key（`no_key`）。GREEN 阶段实测校正：先前草稿误表述为「no_chat_model 优先于 no_key」，正确语义见 `test_reason_priority_no_chat_model_over_no_key` 与 `test_reason_priority_no_key_when_chat_exists_elsewhere` 两条互斥用例。

> **单一端点而非三端点**：`ready` / `has_chat_model` / `has_embedding_model` 三值同源（同一份注册表 + key 集合的一次读取），拆三个端点 = 三次 DB 读 + 竞态窗口。一次返回全量，GUI 按需取用。

### 3.2 为什么没有「首启完成」写入端点

**本模块零写入端点**。引导「完成」不是一个状态迁移动作，而是**判据自然变真**：

```
用户完成引导步骤 2（Provider + chat 模型 + key 落库）
   → 下一次 GET /model-readiness 返回 ready=true
   → GUI 门控放行 + 引导不再出现（N4）
```

**升级路径零打扰的机理**（N3）：升级用户已有 `provider_configs` 行 + 已有 key → 首次调用 readiness 即 `ready=true` → 不弹引导。**无需任何「上次版本」比较、无需标志位、无需迁移**。

### 3.3 异常映射

| 场景 | 状态码 | 响应 detail | 触发层 |
|------|--------|-------------|--------|
| token 缺失/无效 | 401 | `Unauthorized` | TokenAuthMiddleware（全站） |
| DB 异常（磁盘/锁） | 500 | `就绪状态查询失败，请稍后重试`（ADR-012 通用文案，不泄漏内部细节） | 路由层 except |
| 注册表脏行（models JSON 损坏） | 200 | 该行按「无可用模型」参与判据（防御，不阻塞） | service 层 |

### 3.4 路由层实现骨架

```python
@router.get("/model-readiness", response_model=ModelReadiness)
@instrument(caller_type="api")
async def get_model_readiness(
    db: AsyncSession = Depends(get_db),
) -> ModelReadiness:
    """首启模型就绪判据（#934 §3.1）——只读派生，不落库。"""
    try:
        return await compute_model_readiness(db)
    except Exception as exc:
        logger.exception("就绪状态查询失败")
        raise HTTPException(status_code=500, detail="就绪状态查询失败，请稍后重试") from exc
```

> 路径形态：`/model-readiness` 子路径挂 `prefix="/api/v1/settings"` 之下，与 `llm-keys` / `data-dir` 同 router 无冲突。**注意**：必须在 `@router.get("")` 之前或之后均可（FastAPI 按精确路径匹配，无歧义）。

---

## 4. CLI 命令签名变更

**无新命令**。仅扩展既有 `inkflow config show` 输出（`cli/commands/config_cmd.py:25`）：

```python
result = {
    "default_model": config.llm_default_model,
    # ... 既有 7 键不变 ...
    "model_ready": <bool>,                    # ← 新增（#934 R6）
    "model_ready_hint": <str | None>,         # ← 新增：未就绪时的可操作提示行；就绪 = None
}
```

**输出形态**（非 JSON 模式，`cli_ctx.json_output == False` 时追加一行）：

```
default_model: -
...
未就绪提示行（model_ready=False 时）：
⚠ 模型未配置：请启动 GUI（inkflow serve --open）完成首启引导，
  或执行 inkflow llm provider create + inkflow config set default.model provider/model
```

| 键 | 就绪 | 未就绪 |
|----|------|--------|
| `model_ready` | `true` | `false` |
| `model_ready_hint` | `null`（JSON）/ 不输出行（文本） | `"请先完成模型配置：..."` |

> **判据同源**：CLI 侧复用与 HTTP 端点同一 helper（`domain/services/model_readiness.py::compute_readiness`），避免两处判据漂移（#415 单一默认源先例）。

---

## 5. GUI 交互（关键差异节）

### 5.1 触发与门控时序

```
App 挂载
  → BootGate 放行（booted=true，F19 既有）
  → [F60 新增] GET /api/v1/settings/model-readiness
       ├─ ready=true  → 正常渲染路由（零打扰，N3/N4）
       └─ ready=false → 渲染 SetupGuide 全屏（覆盖主 UI，不可 ESC 关闭）
                         用户完成步骤 1+2 → 重新 GET readiness → ready=true → 放行
```

**门控实现位置**：`App.tsx::AppLayout`，在 `!booted → BootGate` 判断之后、主 UI 渲染之前插入 `!modelReady → SetupGuide`（与 BootGate 同构的**前置封面**模式，非路由）。

**门控状态源**：新增 store `useModelReadinessStore`（`stores/modelReadiness.ts`）——单一真相，`SetupGuide` 与语义检索置灰共用。

### 5.2 步骤 1：Provider + API Key

复用 `ProviderDialog`（不重造）：预置模板 openai/deepseek/zhipu/ollama + 自定义 base_url + API Key。

- 步骤 1 完成判据：至少一个 provider 已注册**且**已存 key
- 引导内的 ProviderDialog 复用既有组件；差异 = `SetupGuide` 包裹层提供「下一步」而非「保存关闭」

### 5.3 步骤 2：chat 模型（必填）

- 从已配置 provider 的模型列表中选 chat 模型，或手工录入 `provider/model`
- 落 `provider_configs.default_model`（PATCH `/api/v1/provider-configs/{id}`）
- **连通探测**：复用 `POST /api/v1/settings/llm/test`，探测通过才允许「完成」
- N5：探测失败 → **留在步骤 2**，展示可读错误（`message` 字段）+ 可重试（不跳步、不关窗）

### 5.4 步骤 3：embedding 模型（可跳过）

- 「跳过」按钮显式存在 → 不写任何配置，直接完成引导
- 跳过后：`has_embedding_model == false` → **语义检索入口置灰 + 标注**（N2）
  - 置灰点：检索页（`pages/search.tsx`）语义检索区 + 设置页 `RagStatusCard` 能力标注
  - 标注文案：`语义检索需要 embedding 模型，可在设置→模型管理中配置`
  - **不阻断**写作主路径（issue 原文约束）

> **判据三态与既有行为兼容（GREEN 阶段实测校正）**：检索页置灰以 `readiness` 的**三态**驱动，而非二态：
>
> | readiness | `semanticBlocked` | 语义项 | 默认模式 |
> |-----------|-------------------|--------|----------|
> | `null`（未查询/查询失败） | `false` | 可选 | `semantic`（**保持既有默认，零行为变更**） |
> | 已查询且 `has_embedding_model=false` | `true` | disabled + 提示 | 回落 `keyword` |
> | 已查询且 `has_embedding_model=true` | `false` | 可选 | `semantic` |
>
> **为什么 `null` 不置灰**：既有契约测试 `search.test.tsx`「点检索 → fetchSearch(mode=semantic)」断言默认模式为 semantic。把「未知」当作「不可用」会破坏该契约（且在判据尚未返回的瞬时窗口内造成模式跳变）。置灰只在**确知**无 embedding 时生效——服务端仍为主路径守卫。

### 5.5 主路径可操作错误（R5 / N1）

引导未完成前，LLM 主路径（书运行访谈、chat 发送）的 422 处理升级：

| 现状 | F60 后 |
|------|--------|
| 422 detail 裸文案 toast（`common.modelNotConfigured` 静态提示） | toast/内联提示 + **「前往配置」动作**（跳 `#/settings` 模型管理分类） |

**后端 422 detail 文案不变**（逐字保持 `"未配置默认模型，请在设置中配置 LLM Provider 和默认模型"`）：

> **实现校正（GREEN 阶段）**：草稿曾计划在 detail 追加「（首启引导：设置 → 模型管理）」——实测 `backend/tests/unit/infrastructure/llm/test_llm_resolver_929.py:81` 对该 detail 做**精确相等断言**（#821 契约兼容）。InkFlow 铁律「实现不得改测试」+ #934 明确「非 422 裸文案」的诉求本质是**用户可见层**（GUI 提示含入口跳转），故：**后端契约零变更**，可操作化全部落在前端消费层（提示文案 + 「前往配置」跳转动作）。这样既满足 R5，又零破坏既有契约。

**前端实现点**：`stores/modelReadiness.ts` 导出 `MODEL_NOT_CONFIGURED_HINT` 与跳转目标；LLM 主路径的 422/未就绪分支调用统一 helper 渲染「请先完成模型配置」+「前往配置」按钮（不再只弹静态 toast）。

### 5.6 组件清单

| 组件/模块 | 路径 | 职责 |
|-----------|------|------|
| `SetupGuide` | `components/SetupGuide.tsx` | 全屏引导（三步 + 步骤指示 + 跳过/完成） |
| `useModelReadinessStore` | `stores/modelReadiness.ts` | readiness 单一真相 + 刷新动作 |
| `canUseSemanticSearch` | 上述 store 导出选择器 | 语义检索置灰判据 |

---

## 6. 组织规则

- 后端：`domain/models/model_readiness.py`（Pydantic 模型，纯领域）+ `domain/services/model_readiness.py`（纯函数 `compute_readiness`，零 I/O 便于单测）+ `api/routers/settings.py` 端点（注入式 DB 读）
- 前端：`components/SetupGuide.tsx` + `stores/modelReadiness.ts`；**复用** ProviderDialog、apiFetch、i18n、toast，不重造配置能力
- i18n：全部新增文案走 `zh.ts`/`en.ts`（`setup.*` 前缀），禁硬编码中文（F57 惯例）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| 1 | registrar 为空（全新安装） | `ready=false, reason="no_provider"` → 引导从步骤 1 开始 |
| 2 | 只有 embedding 模型 + key（**#929 缺陷形态**） | `ready=false, reason="no_chat_model"` → 引导（判据显式筛 type） |
| 3 | 有 chat 模型无 key | `ready=false, reason="no_key"` |
| 4 | LLM 主路径被 422 拦（引导未完成） | 可操作提示 + 跳转入口（不静默、不裸文案） |
| 5 | 引导中 llm/test 失败 | 留在步骤 2，错误可读，可重试（N5） |
| 6 | readiness 端点 DB 异常 | 500 通用文案（不阻塞 GUI：前端 fetch 失败按「未就绪」处理并允许重试） |
| 7 | 引导中途关窗/重启 | 无状态残留——下次启动 readiness 仍 false → 引导重现（无需持久化中断点） |
| 8 | 升级用户（已有配置） | readiness 首次即 true → 零打扰（N3） |
| 9 | 用户后来删空 provider | readiness 回落 false → 引导重现（派生判据自愈，§2.1） |
| 10 | embedding 跳过 | `has_embedding_model=false` → 语义检索置灰（不阻断，N2） |

---

## 8. 文件结构

```
backend/src/inkflow/
├── domain/models/model_readiness.py            [新增] ModelReadiness Pydantic 模型
├── domain/services/model_readiness.py          [新增] compute_readiness 纯函数
├── api/routers/settings.py                     [MODIFY] +GET /model-readiness
├── api/_llm_resolver.py                        [MODIFY] 422 detail 加动作语义（保前缀）
└── cli/commands/config_cmd.py                  [MODIFY] config show +2 键 + 提示行

backend/tests/unit/
├── test_model_readiness.py                     [新增] 纯函数判据全分支
└── ...（既有 test_llm_resolver_929 扩展：文案前缀兼容）

tests/api/
└── test_settings_model_readiness.py            [新增] 端点契约（含 401/500/信封）

frontend/packages/renderer/src/
├── components/SetupGuide.tsx                   [新增] 三步引导向导
├── components/SetupGuide.test.tsx              [新增] RED 契约
├── stores/modelReadiness.ts                    [新增] readiness store + 选择器
├── stores/modelReadiness.test.ts               [新增] store/选择器 RED
├── App.tsx                                     [MODIFY] 门控插入
├── pages/search.tsx                            [MODIFY] 语义检索置灰
├── i18n/zh.ts / en.ts                          [MODIFY] setup.* 文案
└── api/client.ts                               [MODIFY] fetchModelReadiness
```

---

## 9. 测试策略

### 9.1 单元（`backend/tests/unit/test_model_readiness.py`）

纯函数 `compute_readiness(providers, saved_names)` 全分支：
- 空注册表 → `ready=False, reason="no_provider"`
- 有 provider 无 chat（只 embedding）→ `ready=False, reason="no_chat_model"`（**#929 回归锚**）
- 有 chat 无 key → `ready=False, reason="no_key"`
- 有 chat + key → `ready=True, reason="ready"`
- 多 provider 混合（一个不全 + 一个全）→ True（存在即就绪）
- `has_embedding_model` 独立于 `has_chat_model` 判定

### 9.2 API（`tests/api/test_settings_model_readiness.py`）

- 200 + 信封字段全集（四条 reason 分支各一）
- 401（无 token）
- DB 异常 → 500 通用文案（不泄漏）
- 就绪后重复调用幂等

### 9.3 前端单元（vitest）

- `modelReadiness.test.ts`：store 加载成功/失败（失败按未就绪）/ 选择器
- `SetupGuide.test.tsx`：
  - N1：`ready=false` 渲染引导；完成后（mock readiness 转 true）不再渲染
  - N2：步骤 3 有「跳过」；跳过 → 完成且不写 embedding 配置
  - N5：llm/test 返回 `ok:false` → 留在步骤 2 + 展示 message + 可重试
  - N3/N4：`ready=true` 首帧即不渲染引导

### 9.4 CLI（`tests/cli/`）

- `config show` 就绪 → `model_ready=true`, `model_ready_hint=null`
- 未就绪 → `model_ready=false` + 提示行出现

### 9.5 E2E 适配（#934 实测需求）

**问题**：E2E 均以 `mkdtempSync` 隔离数据目录启动内核 = **全新安装态**。F60 门控下 App 渲染 `SetupGuide` 覆盖主 UI，导致所有测「其它功能」的 spec 找不到 `app-nav`/页面元素而误红（CI 首轮 `e2e-frontend-*` 4 个 job 全红，非产品缺陷）。

**处置**：新增共享 helper `tests/e2e/e2e-model-ready.ts::ensureModelConfigured(kernel)` —— 经内核 API 幂等预置「含 chat 模型的 provider + key」（复用内置 seed 的 `deepseek` 行），使 `GET /settings/model-readiness` 返回 `ready=true`，等价「用户已完成首启引导」的安装态。已在 22 个 spec 的 launch helper 中于 `waitKernelInfo` 之后调用。

**技术债声明（后续优化方向）**：当前是「每个 spec 的 launch helper 各调一次」，属 N 处样板。更优形态是 **Playwright `test.extend` 自定义 fixture**（或 global setup）集中包装 `electron.launch`，让 seed 成为 fixture 的组成部分而非 22 处调用点。本次未做：改动面涉及所有 spec 的 fixture 签名，风险大于收益；登记为后续重构候选。

**不 seed 的 spec**（不依赖主 UI 内容，仅断言内核/托盘生命周期）：`e2e-debug-triad` · `e2e-tray` · `e2e-packaged`。

N1-N4 的 GUI 全链路（真实内核 + 清数据目录 + 真实完成引导交互）仍未覆盖，登记为 gap issue。

---

## 10. 不在范围内

- CLI 交互式向导（GUI 是主路径）
- 「首启已完成」持久化标志位（§3.2 论证）
- provider 保存前连通门禁（#936 C 项，本单串行）
- embedding 自动配置/自动探测
- 引导内多 Provider 批量配置（一次一个，最小闭环）

---

## 11. 依赖关系

| 类型 | 内容 |
|------|------|
| 前置（已具备） | F19 #106 ProviderConfig 注册表 + ProviderDialog；#79 llm-keys/llm/test；F32 settings 域；#474 hasChatModel 判据 |
| 后置 | #936（技术面一致性，同碰 provider_config_service.py——**须串行，不同批**） |
| 功能互补 | #929（技术兜底 fail-fast）↔ F60（流程面入口正确） |

---

## 12. 关键架构决策记录

| 决策 | 选择 | 否决方案 | 理由 |
|------|------|----------|------|
| 就绪判据形态 | **派生计算（零落库）** | 「first_run_completed」标志位 / 设置键 | 标志位无法自愈（用户删空 provider 后引导永不重现）；需 schema 迁移；升级用户需回填。派生判据天然正确（#770 轻量契约先例） |
| 端点数量 | **单端点返回三值** | 三个独立端点 | 三值同源（一次注册表读），拆开 = 三倍 DB 读 + 竞态窗口 |
| 判据是否含网络探测 | **不含** | 判据内做真实 LLM 探测 | 启动路径不能依赖外网可达性（离线用户会被误挡）；探测在引导步骤内显式执行 |
| 门控位置 | **AppLayout 前置封面**（同 BootGate 模式） | 路由级 guard / 路由重定向 | 与既有内核门控同构，用户不可 ESC 绕过，无需改路由表 |
| 复用 vs 重造配置能力 | **复用 ProviderDialog + 注册表端点** | 引导内重写一套 Provider 表单 | 双份表单 = 双份维护 + 双份 bug（Rule of Three 反面）；引导只需新包裹层 |

---

## 13. 验收标准

| # | 锚点 | 验收方式 |
|---|------|----------|
| N1 | 新装首启（清数据目录）→ GUI 出现设置引导，完成配置前无法进入写作主流程 | 前端单测（门控渲染）+ E2E 锚（可选） |
| N2 | 引导中 chat 必填、embedding 可跳过；跳过后语义检索入口置灰有提示 | 前端单测（跳过路径 + 置灰选择器） |
| N3 | 已有配置升级启动 → 不弹引导（零打扰） | store/组件单测（ready=true 首帧不渲染）+ 后端判据单测 |
| N4 | 引导完成后重启 → 不再弹出 | 组件单测（完成后再查询 ready=true → 不渲染） |
| N5 | 配置过程中 llm test 失败 → 留在引导步骤可重试，错误可读 | 组件单测（llm/test ok:false → 留在步骤 2 + message 展示 + 可重试） |

---

## 14. 待澄清问题（≤3，评审时确认）

| # | 问题 | 本 spec 默认取值 | 状态 |
|---|------|------------------|------|
| Q1 | 引导是否允许「稍后配置」退出（带主路径受限）？ | **否**——全屏门控不可绕过，但语义检索/写作入口在完成后自然开放；无「稍后」按钮（issue 要求必经步骤） | 默认执行 |
| Q2 | 步骤 2 是否强制连通探测通过才放行？ | **是**——issue 原文「连通探测通过才放行」 | 默认执行 |
| Q3 | E2E 全链路是否本 PR 交付？ | **否**——登记 gap issue，本 PR 交付单测 + 手动验证锚 | 默认执行 |
