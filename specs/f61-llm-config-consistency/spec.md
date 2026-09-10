# F61: LLM 配置域一致性治理 — 功能规格

> **端**: backend（+ CLI 补全）

> **Spec 版本**: 1.0 | **日期**: 2026-09-10 | **依据**: Issue #936（0.14.0 milestone）

> **所属阶段**: 0.14.0（#936，W9-S1）

> **关联 Issues**: #936（本模块）；#929 / PR #935（只读评审遗留：NIT-2 装配旁路、MINOR-3 类型校验）；#934（首启引导，已 merge——流程面，与本单技术面互补）；#821（空 key 守卫）；#328（embed 占位探测先例）；#415（单一默认源）；#735 D2（自动设默认——C 项门禁保护该路径）

> **参考 ADR**: [ADR-049](../../adr/llm/ADR-049.md)（LLM 装配 fail-fast）· [ADR-051](../../adr/llm/ADR-051.md)（litellm 统一出口）· [ADR-015](../../adr/core/ADR-015.md)（依赖注入）· [ADR-012](../../adr/api/ADR-012.md)（错误不泄漏内部细节）

> **状态**: 🚧 实施中（#936）

---

## 1. 概述

#929（PR #935）把 `resolve_llm_credentials` 的 4 个调用方收敛为 fail-fast（空默认 → 422 + 诊断日志），但只读对抗评审留下三项治理发现，三项同属「LLM 配置域一致性」：

| 项 | 来源 | 本质 |
|----|------|------|
| **A. chat 装配旁路收敛** | 评审 NIT-2 | 「模型装配 fail-fast」只罩住 resolver 的 4 个调用方；全仓另有 **30+ 处**直接读 `config.llm_default_model` 当 chat 模型消费、不经 resolver → fail-fast 收益碎片化，错误呈现不一致 |
| **B. 显式 embedding 误配类型校验** | 评审 MINOR-3 | 用户**显式**配置 `default.model=zhipu/embedding-3` → 解析链全程不看 type 原样接受 → 同款 zhipu 400 1213。#929 封死的是「系统静默误捡」，「用户显式误配」未罩 |
| **C. 保存前探测门禁** | 用户提议 2026-09-05 | `POST /settings/llm/test` 已有 chat 最小连通探测（手动触发），但**保存路径零门禁**：`provider_config_service.create/update` 直接落库，且 L78-85 会把首个 chat 模型**自动设为全局默认**——未验证过的模型即刻进主路径 |

### 1.1 侦察实证：A 项的真实缺陷面（比 Issue 描述更严重）

**Issue 将 A 项定性为「错误呈现不一致、不计入回归」。实测推翻该定性**——「import 快照、运行期改配置不生效」不是 `agent_templates.py:62` 的孤例，而是 **3 个模块族**：

探针（先 import → 再改 `config.llm_default_model` → 读消费点）：

```
import 后   = ('ORIGINAL/before-import', 'ORIGINAL/before-import', 'ORIGINAL/before-import')
改配置后   = ('ORIGINAL/before-import', 'ORIGINAL/before-import', 'ORIGINAL/before-import')
快照缺陷(不生效) = True
```

| 缺陷点 | Issue 描述 | 实测 |
|--------|-----------|------|
| `infrastructure/agent/pipeline_templates.py` | 「×6 处旁路」 | **12 处** `model=config.llm_default_model`，全部在模块级 `BUILTIN_TEMPLATES`（L324-329）**import 时构造求值** → 运行期改配置，chat/写作模板角色模型全部不生效 |
| `api/routers/agent_templates.py:62` | 「import 快照（独立缺陷形态）」 | ✅ 属实（`BUILTIN_DEFAULT_MODEL = config.llm_default_model`） |
| `character/outline/world/extraction_service.py` | 「各域服务构造默认参」 | 实测 `__init__(llm_default_model: str = config.llm_default_model)` = **同样的 import 快照**，非「构造期传入」 |
| `api/deps.py` 8 处注入 | 「各域服务构造默认参」 | 注入的是**冻结值**——表面「有注入」掩盖「注入的是快照」 |

**用户可见后果**：用户在设置页改默认模型 → 写作链路的角色模型（architect/writer/auditor/reviser）与各域服务仍用**旧模型**，直到重启内核并重载模块。这不是「错误呈现不一致」，而是**功能缺陷**。

### 1.2 模块类型定位（第 16 变体：配置面一致性治理型）

按 AGENTS.md 模块类型谱系计数（f32=14 / f60=15），本模块为 **第 16 变体「配置面一致性治理型」**：不新增业务实体、不新增设置键、不新增 API 端点（除 CLI 补全），提供**单一解析守卫 helper** + **类型校验** + **保存前探测门禁**，横切改造 LLM 配置的消费面与保存面。

```
config.llm_default_model（启动源，单一默认源 #415）
        │
        ├── [A] 消费面：30+ 旁路点 ──收敛──▶ resolve_chat_model() 守卫 helper
        │                                        └── 空 → 422 + 锚文本「LLM 模型解析失败」
        │
        ├── [B] 解析面：named model ──▶ 注册表 type 查询
        │                                └── type=embedding → 422（锚「类型不符」）
        │                                └── type 未知 → 放行（误伤防御）
        │
        └── [C] 保存面：provider_config_service.create/update
                 └── 新增/改动模型条目 → type-aware 最小探测
                        ├── chat → 1-token completion（复用 settings.py:175）
                        ├── embedding → embed_query("0") 校验维度 > 0（#328 先例）
                        └── 失败 → 422 拒绝落库（detail 含模型 id + 摘要）
                            └── force=true → 跳过门禁（落库 + warning）
```

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ 无（零 schema 变更） |
| 新 API 端点 | ❌ 无（A/B 均为既有端点行为修正；C 为既有端点保存路径加门禁） |
| 新 CLI 命令 | ✅ 1 个：`inkflow vector set-embedding`（补既有 `PUT /vector/embedding-model` 的 CLI 暴露缺口） |
| 核心机制 | 统一解析守卫 helper + 注册表 type 校验 + type-aware 保存前探测门禁 |
| 跨模块 MODIFY | ✅ 后端 20+ 文件（infrastructure/agent、domain/services、api/routers、api/deps*、cli/commands） |

### 1.3 边界声明

- **不做** 前端 GUI 发短信改动——`ProviderDialog` 的 GUI 确认框属**消费**既有 422/force 契约；本 PR 后端 + CLI 落地，GUI 交互（确认框）由前端消费方按契约实现（除非用户另行要求）
- **不做** 探测并发优化——串行探测即可（配置操作低频，Issue 权衡点 3）
- **不做** provider 连通性缓存——每次保存都探测（配置写路径低频，缓存引入失效逻辑）
- **不做** `_llm_resolver` 422 detail 文案变更——`test_llm_resolver_929.py:81` 对其做**精确相等断言**（#821 契约兼容）；B 项用**新锚文本**，不复用旧 detail 字符串
- **不做** `langchain_client.py:48` 与 `provider_config.py` 回退链的改造——属装配内部兜底（`default_model or config.llm_default_model`），非「旁路消费」，改动会破坏既有注册表优先语义
- **不做** #934 首启引导的任何改动（已 merge，本单只在其技术面上加守卫）

---

## 2. 数据模型

**零新实体、零新表、零新设置键。** C 项探测结果不落库（每次保存实时探测）。

| 数据源 | 用途 | 证据 |
|--------|------|------|
| `config.llm_default_model` | A 项守卫 helper 的全局默认入参 | `core/config.py:258` |
| `provider_configs` 注册表 `models[].type` | B 项类型校验 | `domain/models/provider_config.py:48`（`Literal["chat","embedding"]`） |
| `provider_configs` 注册表 `models[]` | C 项「新增/改动条目」判定 | `domain/models/provider_config.py:37-57` |
| `APIKeyManager.get_key(provider)` | C 项探测凭据 | `infrastructure/llm/key_manager.py` |

### 2.1 唯一解析守卫定义（A 项真相源）

```python
def resolve_chat_model(
    global_default: str,
    *,
    project_model: str | None = None,
) -> str:
    """解析 chat 模型（project > global），无解 → 422 + 诊断日志（#936 A 项唯一守卫）。

    project_model > global_default（#735 agent>项目>全局链，镜像 resolve_llm_credentials）。
    空 → loguru ERROR 锚文本「LLM 模型解析失败」+ HTTPException 422
    detail 逐字保留「未配置默认模型，请在设置中配置 LLM Provider 和默认模型」
    （#821/#929 契约兼容）。
    """
```

**与 `resolve_llm_credentials` 的关系**：后者返回 `(model, api_key, base_url)` 三元组（装配用）；前者只返回 `model` 字符串（**只消费模型名的旁路点**用）。两者共享同一条解析链与同一 422 契约——`resolve_llm_credentials` 改为**内部调用** `resolve_chat_model`（单一真相，禁第二份解析逻辑）。

**放行语义（Q2 拍板）**：`pipeline_templates` / `agent_templates` 等**数据构造点不抛错**——模板是数据不是装配点；抛在这里会让 `GET /agent-templates` 列表端点也 422，违背 NIT-2「错误呈现一致」初衷。它们只改为**惰性读取**（运行期取当前配置值），空值由装配期 resolver 统一 422。

### 2.2 C 项「受影响模型条目」定义

`create`：`data.models` 全量（新 provider 全部条目都是新增）。

`update`：`data.models` 中**新出现或内容有变**的条目（对比 `existing.models`，按 `id` 匹配）：

| 场景 | 受影响 | 论证 |
|------|--------|------|
| 新增 provider + N 个模型 | 全部 N 个 | 全新条目 |
| update 新增 1 个模型 | 该 1 个 | `id` 不在 existing |
| update 改某模型的 `type`（chat↔embedding） | 该 1 个 | 语义变更，须按新 type 重探 |
| update 改某模型的 `supports_reasoning` | 该 1 个 | 复用同一「条目有变」判据，避免分叉（用户偏好「全路径统一」） |
| update 完全未传 `models` | 0 个 | 无受影响条目 → 零探测 |
| update 传的 models 与 existing 全等 | 0 个 | 幂等保存零探测 |
| update 仅改 `base_url`/`timeout` | 0 个 | 无模型条目变更 |

---

## 3. API 契约

**本模块零新增端点。** 三处为既有端点的行为修正：

### 3.1 A 项：旁路点的 422 契约（行为变更）

| 端点/消费点 | 现状 | F61 后 |
|---|---|---|
| `chat_stream.py` 落库 model 字段 | `config.llm_default_model`（可能空串落库） | `resolve_chat_model(config.llm_default_model)` → 空则 422 |
| `context.py` 摘要生成 model | `app_config.llm_default_model`（可能空串） | 同上 → 空则 422「未配置默认模型…」 |
| `deps_kg_extract.py` 提取客户端 | 构造期读快照 | 惰性 + 守卫 |
| `pipeline_templates.py` ×12 | import 快照 | **惰性读取**（模板构造改为函数调用时取当前值） |
| `agent_templates.py:62` | import 快照 | **惰性读取**（`BUILTIN_DEFAULT_MODEL` → 函数或运行期求值） |
| `character/outline/world/extraction_service.py` | `__init__` 默认参 = import 快照 | 默认参改 `None` + 构造期回退 `resolve_chat_model(...)` |
| `summary_service.py:130` | `config.llm_default_model` 无守卫 | 守卫 |
| `settings.py:148-158` 回退链 | 返回可能空的 `config.llm_default_model` | 保持（探测端点回退链语义，非装配点） |

**422 detail 文案**：逐字 = `"未配置默认模型，请在设置中配置 LLM Provider 和默认模型"`（#821/#929 契约兼容）。

**日志锚**：`"LLM 模型解析失败"`（同 ADR-049 锚文本）。

### 3.2 B 项：`resolve_llm_credentials` 类型校验（行为变更）

在 `parse_model_string` + `get_provider_config` **之后**新增类型校验：

| 场景 | 行为 |
|------|------|
| named model 在注册表**查到**且该条目 `type == "embedding"` | **422** + ERROR 日志锚 `"LLM 模型解析失败（类型不符）"` |
| named model 在注册表查到且 `type == "chat"` | 放行（正常路径） |
| named model 在注册表**查不到**该条目 | **放行**（误伤防御——自定义 provider/手工 config.json 不受影响） |
| 注册表查询异常 / 无注册表 | **放行**（探针语义：查询失败绝不冒泡，镜像 `resolve_reasoning_manual` 先例） |
| 裸名（无 `provider/` 前缀）| 放行（`parse_model_string` ValueError 路径已有既有处理） |

**422 detail 文案（新锚，不复用旧 detail）**：

```
模型 {model_id} 是 embedding 模型，不能作为对话模型使用，请在设置中改选 chat 模型
```

> **为什么不复用旧 detail**：`test_llm_resolver_929.py:81` 对旧 detail 做精确相等断言（#821 契约兼容）。B 项是**新错误类别**（类型不符 ≠ 未配置），新文案让用户可区分两类故障，且零破坏既有契约。

### 3.3 C 项：保存路径探测门禁（行为变更）

**`POST /api/v1/provider-configs`**（create）：query 参数 `force: bool = False`

**`PATCH /api/v1/provider-configs/{id}`**（update）：query 参数 `force: bool = False`

**`PUT /api/v1/vector/embedding-model`**（唯一激活）：query 参数 `force: bool = False`（激活路径同样过 embedding 探测门禁，与 C 同一函数）

| 场景 | 状态码 | detail |
|------|--------|--------|
| 全部受影响条目探测通过 | 201/200 | 正常响应 |
| chat 条目探测失败 | **422** | `模型 {provider}/{model_id} 连接失败：{失败摘要}；如需强制保存请使用 force=true` |
| embedding 条目探测失败（维度 ≤ 0 / 调用异常） | **422** | `embedding 模型 {provider}/{model_id} 探测失败：{失败摘要}；如需强制保存请使用 force=true` |
| 凭据缺失（provider 无 key） | **422** | `模型 {provider}/{model_id} 缺少 API Key，无法探测；如需强制保存请使用 force=true` |
| `force=true` + 探测失败 | 201/200 | **正常落库** + WARNING 日志 `"跳过模型探测门禁（force=true）: provider={} models={}"` |
| 无受影响条目（update 未改 models） | 200 | 零探测，正常响应（**不要求 key**） |

**error 摘要不泄漏凭据**（ADR-012）：detail 含模型 id + 异常类型/摘要，**绝不回显 api_key**。

**探测失败不落库**：门禁在 `repo.add`/`repo.update` **之前**执行 → 失败时零副作用（含 #735 D2 自动设默认也不触发——这正是门禁要保护的路径）。

### 3.4 依赖方向（Q4 拍板：domain 定 Protocol + infrastructure 实现 + router 注入）

```
domain/ports/llm_probe.py          [新增] LLMProbeProtocol（probe_chat / probe_embedding）
        ▲                                    ▲
        │ 依赖倒置                            │ 实现
infrastructure/llm/probe.py        [新增] InfrastructureLLMProbe
        ▲
        │ 注入（api/deps.py 或 router 内构造）
api/routers/provider_configs.py    [MODIFY] 保存前调 probe
```

**service 层签名**：`ProviderConfigService.__init__(*, repository, config=..., probe: LLMProbeProtocol | None = None)`
- `probe=None` → **零门禁**（向后兼容既有测试与 CLI 内部调用；显式优于隐式）
- `probe` 非 None → 保存前探测

`set_embedding_model` 同签名收 `probe` + `force`。

---

## 4. CLI 命令签名

### 4.1 新增：`inkflow vector set-embedding`（Q7 拍板）

补既有 `PUT /api/v1/vector/embedding-model` 端点（`extractions.py:184`）的 CLI 暴露缺口。

```
inkflow vector set-embedding --provider <name> --model-id <id> [--force] [--json]
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--provider` | ✅ | provider 名（如 `zhipu`） |
| `--model-id` | ✅ | 模型 id（如 `embedding-3`） |
| `--force` | ❌ | 跳过探测门禁（透传 query `force=true`） |
| `--json` | ❌ | 全局 flag（F7 §5 信封） |

**输出**：成功 → `✅ 已切换 embedding 模型: {provider}/{model_id}`；JSON 模式 `{"ok":true,"data":{...}}`。
**错误映射**：404 → `NOT_FOUND`、422 → `VALIDATION_ERROR`（复用既有 `_run` + `map_http_error`）。

### 4.2 既有 `inkflow llm provider create/update` 加 `--force`

`cli/commands/llm.py` 的 provider 子命令加 `--force` flag → 透传 query `force=true`。

---

## 5. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| 1 | 全局默认空 + 项目模型空 → 装配 | 422「未配置默认模型…」+ ERROR 锚「LLM 模型解析失败」 |
| 2 | 全局默认空 + 项目模型有值 | 项目模型生效（#735 链） |
| 3 | 运行期改 `config.llm_default_model` → 读模板 | **新值生效**（修 import 快照缺陷） |
| 4 | 显式配 `zhipu/embedding-3` 当默认 | 422「是 embedding 模型，不能作为对话模型使用」+ 锚「类型不符」 |
| 5 | 显式配自定义 provider 模型（注册表查不到） | **放行**（误伤防御） |
| 6 | 保存 provider 含 1 个新 chat 模型 + 探测失败 | 422「连接失败…force=true」+ **零落库** |
| 7 | 保存时 `force=true` + 探测失败 | 落库 + WARNING 日志 |
| 8 | 保存 provider **未改 models** | 零探测（不因缺 key 被拒） |
| 9 | 保存 provider **无 key** + 新增模型 | 422「缺少 API Key，无法探测」 |
| 10 | embedding 探测返回零维向量 | 422「探测失败：维度为 0」 |
| 11 | 注册表查询异常（DB 未初始化） | B 项放行；C 项探测按失败处理（422） |
| 12 | 批量 `--set-json` 加 N 模型 | 串行探测（低频操作，Issue 权衡点 3） |
| 13 | `force` 语义 | 透传 query；CLI `--force`；GUI 确认框由前端消费方实现 |

---

## 6. 文件结构

```
backend/src/inkflow/
├── api/_llm_resolver.py                        [MODIFY] +resolve_chat_model() 守卫 helper；
│                                                         resolve_llm_credentials 内部复用它；
│                                                         +B 项类型校验
├── domain/ports/llm_probe.py                   [新增] LLMProbeProtocol（probe_chat/probe_embedding）
├── infrastructure/llm/probe.py                 [新增] InfrastructureLLMProbe（chat 1-token + embed_query("0")）
├── domain/services/provider_config_service.py  [MODIFY] +probe/force 参数；保存前门禁；惰性默认参
├── domain/services/character_service.py        [MODIFY] __init__ 默认参 → None + 构造期回退守卫
├── domain/services/outline_service.py          [MODIFY] 同上
├── domain/services/world_service.py            [MODIFY] 同上
├── domain/services/extraction_service.py       [MODIFY] 同上
├── domain/services/_style_llm_analyzer.py      [MODIFY] 同上（任务书清单外，实测同族）
├── domain/services/planner_service.py          [MODIFY] 同上（任务书清单外，实测同族）
├── domain/services/summary_service.py          [MODIFY] L130 加守卫
├── infrastructure/agent/pipeline_templates.py  [MODIFY] ×12 import 快照 → 惰性读取
├── api/routers/agent_templates.py              [MODIFY] L62 快照 → 惰性读取
├── api/routers/chat_stream.py                  [MODIFY] ×3 model 字段走守卫
├── api/routers/context.py                      [MODIFY] ×2 model 走守卫
├── api/routers/provider_configs.py             [MODIFY] +force 参数 +probe 注入
├── api/routers/extractions.py                  [MODIFY] PUT embedding-model +force
├── api/deps.py                                 [MODIFY] probe 注入装配
├── api/deps_kg_extract.py                      [MODIFY] 惰性读取 + 守卫
└── cli/commands/vector.py                      [MODIFY] +set-embedding 命令
└── cli/commands/llm.py                         [MODIFY] provider create/update +--force

backend/tests/unit/
├── test_llm_config_consistency_a.py            [新增] A 项：快照缺陷 + 守卫 helper 契约
├── infrastructure/llm/test_llm_resolver_type_936.py    [新增] B 项：类型校验契约
├── domain/services/test_provider_probe_gate_936.py     [新增] C 项：门禁契约
├── cli/test_vector_cli_set_embedding_936.py            [新增] CLI 契约
└── api/routers/test_provider_probe_gate_api_936.py     [新增] C 项端点契约（force 透传 / 422 detail）
```

> **测试树位置实测**：本仓无 `backend/tests/api/` 目录（实测 `Test-Path tests/api` = False）；API 层测试统一在 `tests/unit/api/routers/`，CLI 在 `tests/unit/cli/`，infrastructure 在 `tests/unit/infrastructure/llm/`。新增文件按所在域归位，**两棵测试树禁止同次 pytest**（既有 CI 纪律）。

---

## 7. 测试策略

### 7.1 A 项（`test_llm_config_consistency_a.py`）

**快照缺陷回归锚**（核心，实测可判）：
- 先 import 目标模块 → 改 `config.llm_default_model` → 读消费点 → **必须等于新值**
- 覆盖：`pipeline_templates`（chat/写作模板角色 model）、`agent_templates` 回填值、4 个域服务的构造默认
- 反例（护栏）：未改配置时读到的值 = 当前配置值（防过度修正为常量）

**守卫 helper 契约**：
- `resolve_chat_model("")` → 422 + detail 逐字 = 旧文案 + ERROR 锚「LLM 模型解析失败」
- `resolve_chat_model("", project_model="zhipu/glm-4.5")` → 返回项目模型
- `resolve_chat_model("deepseek/deepseek-v4-flash")` → 返回该值
- `resolve_llm_credentials` 与 `resolve_chat_model` **同源**（同一 422 契约，禁第二份逻辑）

**旁路收敛锚**：`chat_stream` / `context` 落库 model 字段在空默认时 → 422（而非空串落库）。

### 7.2 B 项（`test_llm_resolver_type_936.py`）

- 注入 `get_provider_config` 返回 + 注册表 stub `[{id, type: embedding}]` → 422 + 锚「类型不符」
- `type: chat` → 放行（返回三元组）
- 注册表查不到该条目 → **放行**
- 注册表查询异常 → **放行**
- 新 detail **≠** 旧 detail（两类错误可区分）
- 护栏：正常 named chat model 路径零回归（既有 `test_llm_resolver_929.py` 全绿）

### 7.3 C 项（`test_provider_probe_gate_936.py`）

- mock 探测失败 → 422 + **`repo.add` 未被调用**（零落库）
- `force=true` → 落库成功 + WARNING 日志含「跳过模型探测门禁」
- chat 型探测用例 ×1（1-token completion）；embedding 型 ×1（`embed_query("0")` 维度 > 0）
- 无受影响条目（update 未传 models）→ 零探测，**不调 probe**
- `probe=None`（未注入）→ 零门禁（向后兼容既有测试）
- 唯一激活 + 门禁组合：`set_embedding_model` 探测失败 → 422 且不 update
- 凭据缺失 → 422「缺少 API Key」
- detail 含模型 id + 摘要；**不含 api_key**（安全断言）

### 7.4 API 层（`test_provider_probe_gate_api_936.py`）

- `POST /provider-configs` 探测失败 → 422 + detail 文案 + 零落库
- `POST /provider-configs?force=true` 探测失败 → 201 落库
- `PATCH /provider-configs/{id}` 同双态
- `PUT /vector/embedding-model?force=true` 透传

### 7.5 CLI（`test_vector_cli_set_embedding_936.py`）

- 成功 → 退出码 0 + 输出文案
- `--force` → URL 含 `force=true`
- 404/422 → 错误码映射 `NOT_FOUND`/`VALIDATION_ERROR`
- `--json` 信封形态

### 7.6 回归护栏

- `test_llm_resolver_929.py` 全绿（422 文案精确断言零破坏）
- `test_provider_config_auto_default.py` 全绿（#735 D2 路径）
- `test_provider_config_service.py` / `test_provider_config_set_embedding.py` 全绿（`probe=None` 兼容）
- `test_embedding_model_api.py` 全绿

---

## 8. 不在范围内

- GUI 确认框实现（消费方，按 422/force 契约）
- 探测并发优化（串行即可）
- provider 连通性缓存
- `langchain_client.py:48` / `provider_config.py` 回退链改造（装配内部兜底，非旁路）
- `_llm_resolver` 旧 422 detail 文案变更（#821 契约）
- #934 首启引导改动

---

## 9. 依赖关系

| 类型 | 内容 |
|------|------|
| 前置（已具备） | #929 / PR #935（fail-fast 基础）；#934（已 merge）；#328（embed 探测先例）；#821（空 key 守卫）；F32 settings 域 |
| 功能互补 | #929（技术兜底）↔ #934（流程面）↔ #936（消费/保存一致） |
| 冲突声明 | 同碰 `provider_config_service.py`，但 #934 **已 merge** → 本单基于最新 main，无并发 |

---

## 10. 关键架构决策记录

| 决策 | 选择 | 否决方案 | 理由 |
|------|------|----------|------|
| A 项守卫形态 | **新增 `resolve_chat_model()` 单值 helper**，`resolve_llm_credentials` 内部复用它 | 各点内联判空；或全部改用三元组 resolver | 三元组 resolver 返回 api_key/base_url，只消费模型名的旁路点用不上（多余耦合）；单值 helper 单一职责，且两函数同源零分叉 |
| A 项模板层空值 | **模板不抛**（只改惰性读取） | 模板构造时抛 422 | 模板是数据非装配点；抛在 `BUILTIN_TEMPLATES` 会让 `GET /agent-templates` 也 422 |
| B 项 type 数据源 | **新增 `_lookup_registry_model_type()` helper** | 扩展 `LLMProviderConfig` 加字段 | 既有 dataclass 有鸭子类型契约测试（`test_provider_config_resolution.py`），扩展字段有破坏风险；helper 可单测 |
| B 项查不到时 | **放行** | 拒绝 | 误伤防御——自定义 provider / 手工 config.json 不在注册表；Issue 原文拍板 |
| B 项 detail | **新锚文本** | 复用旧 detail | 旧 detail 有精确相等断言；两类错误应可区分 |
| C 项依赖方向 | **domain 定 Protocol + infrastructure 实现 + router 注入** | service 直接 import infrastructure（破戒）；探测放 router 层（service 无门禁语义） | 保依赖方向（ADR-015）；service 保持可测（`probe=None` 零门禁） |
| C 项门禁位置 | **`repo.add`/`repo.update` 之前** | 落库后校验并回滚 | 零副作用优于补偿事务；且要拦住 #735 D2 自动设默认（落库后已晚） |
| C 项 force 默认 | **默认必过，显式 force 才跳过** | 默认放行 + 显式严格 | 用户 fail-fast 价值观（#929 拍板②「不静默」）；显式优于隐式 |
| C 项探测并发 | **串行** | 组内并发上限 3 | 配置写路径低频，串行实现简单、错误定位清晰 |

---

## 11. 验收标准

| # | 锚点 | 验收方式 |
|---|------|----------|
| N1 | 运行期改全局默认模型 → 模板/服务构造取到**新值**（快照缺陷修复） | 单测（先 import 后改配置读消费点） |
| N2 | 全局默认空 → 装配点 422「未配置默认模型…」+ 锚「LLM 模型解析失败」 | 单测（helper 契约 + 旁路点） |
| N3 | 显式配 embedding 模型当 chat → 422「是 embedding 模型…」+ 锚「类型不符」 | 单测（registry 注入） |
| N4 | 注册表查不到 type → 放行（不误伤自定义 provider） | 单测 |
| N5 | 保存含新模型 + 探测失败 → 422 + 零落库 | 单测（`repo.add` 断言 + API 契约） |
| N6 | `force=true` + 探测失败 → 落库 + WARNING | 单测 + API 契约 |
| N7 | chat/embedding 双型探测各自正确路径 | 单测（双型各一） |
| N8 | `inkflow vector set-embedding` 可用 + `--force` 透传 | CLI 单测 |
| N9 | 既有契约零破坏（929/735 D2/set_embedding/resolution 全绿） | 全量回归 |

---

## 12. 待澄清问题（≤3）

| # | 问题 | 本 spec 默认取值 | 状态 |
|---|------|------------------|------|
| Q1 | B 项类型校验是否也覆盖 `project_model`？ | **是**——`resolve_model` 结果统一校验，项目级误配同款风险 | 已拍板（按建议） |
| Q2 | C 项 update 改了 `supports_reasoning` 是否也探测？ | **是**——走同一「条目有变」判据，避免同族路径分叉（用户偏好全路径统一） | 已拍板（按建议） |
| Q3 | 拆 PR 粒度？ | **三项一个 PR**——同域互补，拆开易留半修状态（A 项缺陷面比 Issue 描述大） | 已拍板（按建议） |
