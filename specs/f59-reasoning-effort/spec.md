# F59 思考模式（Reasoning Effort）+ LLM 出口统一 LiteLLM

> **Spec 版本**: v1.1
> **Spec 变更**: v1.1（2026-09-06）：待澄清 Q1/Q2/Q3 拍板并融入原节（Q1=A 软降级+WARNING 确认 §5.5/§3.3；Q2=B 前端 localStorage per-project §3.4/§12 D8；Q3=设定页控件文案直写「Agent思考强度设定」§3.4/§12 D9）；§12 D5 去「待澄清」挂账。
> **日期**: 2026-09-06
> **依据**: 用户需求（chat 页每轮可选思考档位 + 写作链/全自动设定页配置）+ 三轮实证调查（/models 探测、provider 专项包、LiteLLM SDK 源码核验）
> **模块类型**: 跨端（backend LLM 基建 + API + GUI），含既有模块（F5 LLM Provider / F23 SSE / F32 设置 / F47 chat 执行细节）增量——无新业务实体
> **关联 Issues**: 待创建（spec-only PR 合入后拆分实现 issue）
> **依赖**: ✅ ADR-051（本 spec 随 docs PR 同批交付）；✅ F5（provider 注册表）✅ F23（SSE 帧）✅ F32（设置持久化）✅ #727（reasoning 帧提取）✅ #735（resolve_model 三级链）
> **参考 ADR**: [ADR-051](../../adr/llm/ADR-051.md)（取代 ADR-005v2）、ADR-049（fail-fast 装配）、ADR-047（fake LLM）、ADR-015（LangChain 全家桶）
> **状态**: 待实现 🔲

---

## 1. 概述

### 1.1 功能定位

为 InkFlow 三个 LLM 消费面引入**思考模式**（模型在生成回复前进行链式推理，思考过程
实时展示给用户）：

| 消费面 | 决策入口 | 粒度 |
|--------|---------|------|
| chat 页（含全局会话页 + 章节内会话） | 输入框底部思考级别选择器（参考 Hermes） | 每轮请求 |
| 写作链（generate / continue / 管线角色） | 项目设定页「Agent思考强度设定」下拉 | 项目级 |
| 全自动写作（deepagents agentic 循环） | 项目设定页同一字段 | 项目级 |

同时**一次性偿还 LLM 出口架构债**：全部 `ChatOpenAI` / `OpenAIEmbeddings` 构造点迁移到
`ChatLiteLLM` / `LiteLLMEmbeddings`，provider 思考参数方言（DeepSeek `thinking` 对象、
智谱 `thinking`+`reasoning_effort`、Qwen `enable_thinking` 布尔、OpenAI `reasoning_effort`）
全部交给 litellm 翻译，InkFlow 不再维护任何映射表。

### 1.2 关键事实盘点（2026-09-06 源码实证）

| # | 现状 | 位置 |
|---|------|------|
| 1 | LLM 构造点 1：`ChatOpenAI(**kwargs)`，kwargs 仅 model/temperature/max_retries/request_timeout/api_key/base_url/max_tokens，无任何思考参数 | `infrastructure/llm/langchain_client.py::_get_chat_model()` |
| 2 | LLM 构造点 2：deepagents 编排，`ChatOpenAI(model, temperature=0.2, api_key, base_url)` 直传 `create_deep_agent` | `infrastructure/agent/deepagents/harness.py::build_deep_agent()` |
| 3 | embedding 装配点：`OpenAIEmbeddings(model, api_key, base_url)`（注册表 type=embedding 条目驱动） | `api/deps.py::_build_vector_store` 附近（≈L730） |
| 4 | 思考内容展示链路**已存在**：`_extract_reasoning_content()` 读 `additional_kwargs["reasoning_content"]` → SSE `reasoning` 帧 → 前端渲染（#727/#740） | `infrastructure/agent/chat_agent_service.py`、`api/routers/chat_stream.py` |
| 5 | 三级模型解析链已统一：`resolve_model(调用级, project.config.model, config.llm_default_model)` | `domain/services/model_resolution.py`（ADR-049） |
| 6 | 模型名已是 LiteLLM 语法 `provider/model_name`（如 `deepseek/deepseek-v4-flash`） | `infrastructure/llm/provider_config.py::parse_model_string` |
| 7 | ❌ 缺口：请求侧无思考参数入口（三处构造点、DTO、ProjectConfig、config 均无字段） | 本 spec §2-§3 补 |
| 8 | ❌ 缺口：GUI 无思考档位控件、无「模型是否支持思考」探测面 | 本 spec §3.4/§5.4 补 |
| 9 | 实证（litellm 1.99.0）：`ChatLiteLLM` 把 `reasoning_content` 规范进 `additional_kwargs`（与 #4 链路零改动兼容）；`supports_reasoning("deepseek/deepseek-v4-flash")=True`；`reasoning_effort: Literal["none","minimal","low","medium","high","xhigh","default"]`（litellm/main.py:419）；deepseek transformation 自带 `reasoning_effort→thinking.type` 翻译与多轮 `_fill_reasoning_content` 回传 | `.hermes/tmp/pkg-probe` 探测（docs PR 后清理） |

### 1.3 边界声明

- 本模块是**横切 LLM 基建 + 交互增量**，不建新表、不加新端点族；对项目配置/设置/会话请求是**加字段**。
- 「思考模式」≠ 新增 LLM 调用路径：思考是同一调用的参数开关，产出物（reasoning 帧）走既有 SSE 契约。
- ChatLiteLLM 迁移属于本模块交付（ADR-051 决策 D「一步到位」），与思考功能在实现 issue 上拆为**迁移先行 + 功能后续**两批（迁移是功能的依赖）。

---

## 2. 数据模型

无新 ORM 表、无迁移（全部落在既有 JSON 列 / config 文件，加键零迁移）。

### 2.1 领域枚举（新增，domain 层纯定义）

```python
# domain/models/reasoning.py（新建）
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "default"]
```

七档对齐 litellm 官方签名。语义：

| 值 | 语义 | GUI 中文文案 |
|----|------|-------------|
| `none` | 显式关闭思考 | 关闭 |
| `minimal` | 最低档 | 最低 |
| `low` / `medium` / `high` | 低 / 中 / 高 | 低 / 中 / 高 |
| `xhigh` | 极高 | 极高 |
| `default` | 不发任何思考参数，跟随模型/供应商默认行为 | 跟随模型默认 |

英文档名**不进 i18n 值域**（API/存储恒用英文枚举，GUI 展示经 `t()` 映射）——符合 F57 语言中立原则。

### 2.2 配置字段（MODIFY，全部可选、零迁移）

| 载体 | 新字段 | 类型/默认 | 语义 |
|------|--------|----------|------|
| `core/config.py`（全局） | `llm_reasoning_effort` | `ReasoningEffort`，默认 `"default"` | 全局兜底；config.json 白名单键 `default.reasoning_effort`（CLI `config set` 自动可用） |
| `domain/models/project.py::ProjectConfig` | `reasoning_effort` | `ReasoningEffort \| None`，默认 `None` | 项目级：写作链 + 全自动共用一档；`None`=跟随全局。旧 config JSON 无键→默认 None，零迁移 |
| `api/routers/chat_stream.py::ChatStreamRequest` | `reasoning_effort` | `ReasoningEffort \| None`，默认 `None` | 每轮请求级覆盖（chat 面专用）；`None`=按项目>全局解析。**不落任何 DB**（AgentRun 不新增列，运行时 model 字段已有） |
| provider 注册表 `models[]` 条目（`domain/models/provider_config.py`） | `supports_reasoning` | `bool \| None`，默认 `None` | 手动能力覆盖：`None`=自动探测（§5.4），`true/false`=用户强制。存 JSON 列，零迁移 |

**解析优先级链**（复用 #735 `resolve_model` 形态，新增 `resolve_reasoning_effort`）：

```
请求级 reasoning_effort（仅 chat）> ProjectConfig.reasoning_effort > config.llm_reasoning_effort
```

写作链/全自动无请求级，起点为项目级。

### 2.3 运行时参数流转

- `LangChainLLMClient.chat/chat_stream`、`ChatAgentService`、`harness.build_deep_agent`、
  supervisor/langgraph pipeline 各角色装配——均新增可选 `reasoning_effort` 参数，
  由调用方（router/service/deps）在装配 ChatLiteLLM 前解析好传入；构造函数不自行读配置
  （保持可测试性，与现有 model/temperature 注入形态一致）。
- `LLMClientProtocol`（domain/ports/llm_client.py）：`chat()/chat_stream()` kwargs 已
  `**kwargs` 透传，无签名破坏；仅补 `reasoning_effort` 的显式说明。

---

## 3. API 契约

### 3.1 端点总览（全部为既有端点的字段增量，无新端点）

| 端点 | 变更 | 修改履历 |
|------|------|---------|
| `POST /api/v1/chat/agent/stream` | 请求体 `ChatStreamRequest` 新增可选 `reasoning_effort`（非法值 422） | 新增 |
| `POST /api/v1/chat/stream`（legacy） | 同上（与 agent 轨对称，SSE 帧已含 reasoning 类型） | 新增 |
| `PATCH /api/v1/projects/{id}/config` | 接受 `reasoning_effort` 字段（pydantic Literal 校验，非法 422） | 新增 |
| `GET /api/v1/projects/{id}` | 响应 config 回显 `reasoning_effort` | 新增 |
| `PUT /api/v1/settings` / `GET /api/v1/settings` | 全局默认：新增 `default.reasoning_effort` 白名单键 | 新增 |
| `GET /api/v1/settings/providers`（models 列表面） | 响应 models[] 条目新增 `supports_reasoning: bool`（读取时探测填充，见 §5.4） | 新增 |
| 写作链端点（`/writing/*`、agentic、book） | **不新增请求字段**：档位恒从项目>全局解析 | — |

SSE 帧协议不变：`reasoning` 帧（#727 契约）在开了思考的模型上自然多产出；未开思考无该帧。

### 3.2 请求示例

```json
POST /api/v1/chat/agent/stream
{ "project_id": "...", "prompt": "...", "chapter_id": "...",
  "reasoning_effort": "high" }
```

响应帧序列（开思考后，DeepSeek V4 实测形态）：

```
run_started → reasoning(多次) → delta(多次) → tool 帧(如有) → done
```

### 3.3 异常映射表

| 场景 | HTTP/SSE | detail | 说明 |
|------|----------|--------|------|
| `reasoning_effort` 非七档枚举值 | 422 | i18n 自定义文案（禁 pydantic 原文泄漏，#759 先例） | 请求校验层 |
| 档位 > 模型能力（如 glm-4.5 传 high） | 200，思考参数被降级（§5.5） | SSE 正常，无 reasoning 帧 + 服务端 WARNING 日志 | 软降级，不断流 |
| litellm/provider 侧参数错误透传 | LLMRequestError → 既有 502/SSE error 帧映射 | 不变 | ChatLiteLLM 迁移不得回归此路径 |

### 3.4 GUI 契约（消费 §3.1；页级交互规格随实现 PR 按 f19-gui 拆页模式补，含双件套）

| 控件 | 位置 | 行为 |
|------|------|------|
| 思考级别选择器（7 档下拉/分段） | chat 输入框底部，模型选择器旁（参考 Hermes） | 默认「跟随模型默认」；仅作用于**下一轮发送**；档位记忆=前端 localStorage per-project（跨刷新保持，不落后端库，Q2 拍板 ✅）；当前模型 `supports_reasoning=false` → 控件整体禁用 + tooltip |
| 「Agent思考强度设定」下拉（7 档） | 项目设定页 AI 配置区（模型字段下方） | 控件标签即「Agent思考强度设定」（英文 "Agent Thinking Intensity"，Q3 拍板 ✅），不加两行说明文案；保存走 PATCH config |
| 全局默认思考级别 | 设置页 LLM 区（默认模型下方） | 走 PUT settings；`default.reasoning_effort` |
| 能力徽标 | 设置页 provider 模型列表 | `supports_reasoning` 真值显示「支持思考」徽标，假值不显示；手动覆盖项显示「手动」角标 |

---

## 4. CLI 命令签名

无新增子命令。继承 F32 既有机制：

- `inkflow config set default.reasoning_effort high`（白名单键自动生效，F7 全局约定：
  `--json` 信封 / 退出码 0/1/2）
- 项目级配置经 GUI/API 维护；CLI 项目命令不新增思考参数（§10 范围外）。

---

## 5. 关键差异节：LiteLLM 迁移 + 思考参数方言收敛

本节是本模块的核心工程差异点，按「构造点迁移 → 参数注入 → 探测 → 降级」四段。

### 5.1 ChatLiteLLM 迁移（三处，替换 ADR-005v2 路线）

| 构造点 | 现状 → 目标 | 参数映射 |
|--------|------------|---------|
| `langchain_client._get_chat_model()` | `ChatOpenAI(model, temperature, max_retries, request_timeout, openai_api_key, openai_api_base, max_tokens)` → `ChatLiteLLM(model=f"{provider}/{model_name}", api_key, api_base, temperature, max_retries/request_timeout→litellm 顶层参数, num_retries)` | ⚠️ `provider/model` 全名直接传 litellm（现状 parse_model_string 拆开传 ChatOpenAI 的形态回退为**不拆**）；`base_url` 覆盖语义经 `api_base` 保留（fake server / 自定义端点） |
| `harness.build_deep_agent()` | 同上（收 `model/api_key/base_url`，注入 `create_deep_agent`） | deepagents 零改动（BaseChatModel 契约）；`ensure_profile` 逻辑保留 |
| `deps.py` embedding 装配 | `OpenAIEmbeddings(...)` → langchain-litellm `LiteLLMEmbeddings(model, api_key, api_base)` | `Embeddings` Protocol 不变（FakeEmbeddings 测试注入零改动）；`probe_embedding_dimension` 保留 |

**fake provider（ADR-047 S0）**：`get_provider_config("fake")` 短接保留；fake 请求经
`api_base=INKFLOW_LLM_BASE_URL` + model 名直传 litellm `openai/<model>` 或 `chat/completions`
兼容形态——**fake server 兼容性列为迁移批第一 RED 项**（S0 全链路 E2E 必须过）。

**provider 名口径**：InkFlow 注册表 provider（`deepseek`/`zhipu`/`openai`/`ollama`/自定义）
→ litellm provider 前缀需一张**一次性口径映射**（`zhipu→zai`；其余同名）放
`provider_config.py`（这是唯一保留的「表」，10 行以内，替代的是全量方言表）。
自定义注册 provider（`fake`、OpenAI 兼容第三方）litellm 走 `openai/` 前缀 + `api_base`。

### 5.2 思考参数注入

- `ChatLiteLLM` 构造 kwargs 增加可选 `reasoning_effort=<解析结果>`。
- **不发**档位为 `default`（解析链终点为 `default` 时 kwargs 完全不加该键，等价现状）。
- `none`：litellm 对支持方翻译为关闭（deepseek transformation：`reasoning_effort="none"` → `thinking.type="disabled"`，实证源码 40-59 行）。
- 多轮思考回传（DeepSeek「reasoning_content 必须原样传回」约束）：**由 litellm
  `_fill_reasoning_content` 自动处理**，InkFlow 侧 messages 组装零改动（迁移批需用
  e2e-ai-backend 真实多轮用例验证该行为，§9）。

### 5.3 embedding / 非 chat 调用不受思考影响

embedding、风格分析单次调用（`_style_llm_analyzer`）等不注入 reasoning_effort（默认
`default`=不发），行为与现状一致。风格分析属「分析判断」场景，档位入口留 §10。

### 5.4 能力探测（三级链，GUI 置灰数据源）

```
注册表 models[].supports_reasoning 手动值（true/false）
  → 未设置：litellm.supports_reasoning(provider/model 全名)（模型级，本地表，无网络 IO）
  → 仍 False 且 provider 级能力存在：get_supported_openai_params() 含 thinking/reasoning_effort
  → 结果返回 GUI（不落库持久化；持久化仅手动覆盖值）
```

- 探测为纯本地 dict 查表（毫秒级），在 `GET /settings/providers` 响应装配时逐条计算。
- 探测逻辑封装 `infrastructure/llm/capability_probe.py`（新文件，≈30 行），
  domain 层经端口暴露给 settings 路由。

### 5.5 超出能力时的降级规则

| 情况 | 行为 |
|------|------|
| 模型不支持思考 + 请求/项目档位 ≠ default/none | **软降级**：剥离思考参数发起调用 + `loguru WARNING`（锚文本「思考模式降级」，message_key i18n）；SSE 正常无 reasoning 帧。理由：写作主流程不因参数偏好阻断（区别于 ADR-049 模型缺失的硬故障——模型缺失仍 422 fail-fast）。**Q1 拍板 ✅ 2026-09-06** |
| 模型恒思考不可关（如 glm-5.3 类） + 档位=none | 同上软降级 + WARNING（无法关闭，保持开）；GUI 选择器对该类模型锁定显示为不可关（能力值 `always_on` 表达，v1 由 `supports_reasoning=true` + 手动覆盖近似表达，不建第四态——§10） |

### 5.6 依赖方向检查

```
domain/models/reasoning.py（纯 Literal 枚举）← domain/services（resolve 链）← api/routers
infrastructure/llm/{langchain_client,capability_probe,provider_config}.py（唯一 litellm import 点）
❌ domain 层禁 import litellm（探测结果经端口协议返回 bool，不泄漏 litellm 类型）
```

litellm import 集中在 infrastructure（ADR-002 分层不破）。

---

## 6. 组织规则

- 思考档位**不新增关联字段/表**：会话不落档位（每轮无状态）、AgentRun 不新增列
  （用户轻量契约先例 #770/#929）。
- 项目级一档覆盖写作链+全自动两场景（用户拍板「设定页面决定」）；按角色分档列 §10。
- `default.reasoning_effort` 进 F32 config 白名单，与 `default.model` 同级管理。
- 中文文案 i18n 全量（chat 选择器/设定页/日志 message_key），英文档名不译（枚举值）。

---

## 7. 边界情况与错误处理

| # | 场景 | 处理 |
|---|------|------|
| 1 | 非法档位字符串（API 直调） | pydantic Literal → 422 自定义文案（不泄漏原文） |
| 2 | 模型未注册思考能力但实际支持（新模型） | 注册表手动覆盖 `supports_reasoning=true`（§2.2）；探测表由 litellm 升级跟进 |
| 3 | 探测表将模型判为支持、端点实际拒绝参数 | provider 400 → LLMRequestError 既有映射（错误信息含档位上下文）；记录 WARNING 供排查 |
| 4 | fake server（测试缝）收到 reasoning_effort | 忽略参数正常应答（litellm `openai/` 前缀透传，chat completions 兼容） |
| 5 | chat 流中途用户切换档位 | 只影响下一轮（无热切换契约）；当前轮不重发 |
| 6 | 思考输出为空（混合模型自行决定不思考） | 无 reasoning 帧，行为与档位 default 一致——SSE 契约已兼容（#727） |
| 7 | 思考 token 计入用量 | litellm usage 归一 `completion_tokens` 含 reasoning tokens → 既有 token_usage/AgentRun 统计自动覆盖；GUI 无需区分 |
| 8 | 多轮对话历史含 reasoning_content（DeepSeek 强制回传） | litellm `_fill_reasoning_content` 自动补齐（§5.2）；历史消息存储不变（会话 message 表是否落 reasoning 字段 → §10） |
| 9 | 主窗流式 `on_chat_model_end` 提取路径在 ChatLiteLLM 下 | additional_kwargs 键名一致（实证），#727 零改动；迁移批回归测试锁定 |
| 10 | litellm 升级破坏行为 | 版本 pin（`litellm==1.99.0` / `langchain-litellm==0.7.1`）；升级 = 独立 PR + 全量回归 + e2e-ai-backend 抽测 |
| 11 | ollama 本地模型 | litellm `ollama/` 原生支持；思考能力探测同链，无特殊分支 |
| 12 | zhipu `reasoning_effort:"max"`（智谱官方超出 litellm 枚举的档） | v1 不发该值（GUI 无 max 档，七档=litellm Literal）；如需对接智谱 max，走注册表 models 手动条目 + 后续迭代（§10） |

---

## 8. 文件结构

### 8.1 CREATE

| 文件 | 职责 |
|------|------|
| `backend/src/inkflow/domain/models/reasoning.py` | `ReasoningEffort` Literal + 中文文案键表引用说明 |
| `backend/src/inkflow/infrastructure/llm/capability_probe.py` | 三级探测链封装（litellm 唯一调用点之一） |
| `backend/tests/unit/domain/models/test_reasoning_model.py` | 枚举/解析链单测 |
| `backend/tests/unit/infrastructure/llm/test_capability_probe.py` | 探测三级链单测 |
| `backend/tests/unit/infrastructure/llm/test_litellm_migration.py` | 三构造点 kwargs 翻译契约（含 reasoning_effort 注入/不发/default 剥离） |
| `tests/api/test_reasoning_effort_api.py` | 请求校验/降级日志/API 契约（API 层在仓库根 tests/） |
| renderer：chat 输入区 `ThinkingLevelSelect` 组件 + 测试 | §3.4 控件（含「必须出现」断言） |

### 8.2 MODIFY（逐文件，对照真实树）

| 文件 | 变更 | 归属批 |
|------|------|--------|
| `backend/pyproject.toml` | +`litellm==1.99.0` +`langchain-litellm==0.7.1`（uv.lock 同步） | 迁移批 |
| `infrastructure/llm/langchain_client.py` | `_get_chat_model` → ChatLiteLLM；kwargs 增 reasoning_effort | 迁移批 / 功能批 |
| `infrastructure/agent/deepagents/harness.py` | `build_deep_agent` → ChatLiteLLM；签名增 reasoning_effort | 同上 |
| `infrastructure/llm/provider_config.py` | provider→litellm 前缀口径映射；models[] 增 supports_reasoning 透传 | 功能批 |
| `domain/models/provider_config.py` | ProviderModelEntry 增字段 | 功能批 |
| `api/deps.py` | embedding 装配 → LiteLLMEmbeddings；chat agent 装配链注入档位 | 迁移批 / 功能批 |
| `domain/models/project.py` | ProjectConfig.reasoning_effort | 功能批 |
| `core/config.py` | llm_reasoning_effort + 白名单键 `default.reasoning_effort` | 功能批 |
| `domain/services/model_resolution.py` | 增 `resolve_reasoning_effort`（同形态纯函数） | 功能批 |
| `api/routers/chat_stream.py` | ChatStreamRequest 字段 + 两轨 handler 解析传参 | 功能批 |
| `api/routers/settings.py`、`projects.py`（含 config PATCH 面） | 字段透传 | 功能批 |
| `infrastructure/agent/{supervisor_pipeline,langgraph_pipeline}.py` + `domain/services/agent_service.py` | 管线角色装配注入项目级档位 | 功能批 |
| renderer：`ChatPanel`（输入区）+ settings 页 + projects 设定页 + i18n（zh/en）+ store | §3.4 | GUI 批 |
| `specs/f5-llm-provider/spec.md`、`specs/f4-pipeline-engine/spec.md` | ChatOpenAI 表述 → ChatLiteLLM（融入原节 + 修改履历列） | 收尾 docs |
| `AGENTS.md` §1 功能表/§3/§8、`adr/llm/ADR-005v2.md` 标弃用、`adr/README.md` 索引 | 治理同步（ADR 索引已随本 docs PR；AGENTS.md 随实现 PR） | 收尾 |
| `ci.yml` | 无新 job；测试树登记核对（新测试文件在 backend/tests/unit 与 tests/api 既有 glob 内） | 功能批 |

**不修改**：SSE 帧协议（chat_stream.py 帧编码函数零改动）、会话/AgentRun schema、
deepagents 包（`_models.py` 收 BaseChatModel 即可）、`redact.py`（脱敏按通用字段遍历，
reasoning 已覆盖）。

---

## 9. 测试策略

### 9.1 层次

- **单元**（backend/tests/unit）：解析链、探测链、构造点 kwargs 契约（mock ChatLiteLLM
  构造断言 reasoning_effort/api_base 形态）、软降级剥离逻辑。
- **API**（tests/api）：422 校验、字段回显、SSE 帧回归（reasoning 帧既有契约不破）。
- **fake 全链路**（ADR-047）：fake server 下三消费面跑通（迁移不破）。
- **真实 AI**（e2e-ai-backend / e2e-ai-embedding 开关，CI 默认 skip）：
  ① deepseek-v4-flash 开 high → 收到非空 reasoning 帧；
  ② 多轮回传实证（第二轮请求带首轮 assistant reasoning_content 不报错——litellm 自动补）；
  ③ dashscope/qwen-plan `enable_thinking` 透传实测（ADR-051 实证清单唯一推断项，必测）；
  ④ embedding 迁移后维度探测一致。
- **前端**（Vitest）：选择器渲染/禁用态（`supports_reasoning=false` 置灰）/选中传参
  断言 + **UI 元素必须出现断言**（#793 纪律）。
- **E2E**（Playwright）：chat 页档位选择→发送→reasoning 区块出现（fake server 注入
  reasoning_content 帧）；设定页保存档位。

### 9.2 既有测试破坏清单（迁移冲击，GREEN 批必须逐项处置）

`rg -l "ChatOpenAI|OpenAIEmbeddings" backend/tests tests/` → **15 个测试文件**：迁移批
逐文件将 mock/patch/import 目标迁至 ChatLiteLLM/LiteLLMEmbeddings（或改 patch
`_get_chat_model` 等函数缝）；迁移后该清单必须清零（grep 断言）。

### 9.3 覆盖率

模块行覆盖 ≥80%（litellm 调用以 mock 断言契约，不打真实网络；真实行为归 e2e-ai-*）。

---

## 10. 不在范围内

| 项 | 原因/归属 |
|----|----------|
| 按管线角色分档思考级别（agent_architect 等各自档位） | 项目级一档已覆盖用户诉求；角色级待反馈再开（对齐 F42 角色模型面） |
| 思考档位第四态 `always_on` 建模 / 模型级档位支持集（xhigh/max 逐模型）探测精度 | v1 能力二分（可/不可）够用；litellm `supports_xhigh_reasoning_effort` 等字段跟进留 v2 |
| 智谱 `reasoning_effort:"max"` 对接 | 超出 litellm Literal（§7.12）；如需走手动条目后续迭代 |
| LiteLLM Proxy（sidecar） | 桌面单机自用不做重（ADR-051 备选 B'） |
| 会话消息表持久化 reasoning_content（重放含思考过程） | 现 AgentRun trace 已存（#615/#740）；会话级重放增强挂 #599 统一执行视图后续 |
| CLI `--reasoning-effort` 显式参数（write/chat 命令） | CLI 面走 F38 命令族增量，待需求（#251 CLI 缺口同轨） |
| 风格分析/记忆提取等单次调用接入思考档位 | 分析判断场景收益待验证，先保持 default 不注入 |
| thinking_budget / budget_tokens 类「按 token 限预算」参数 | 与七档正交（Qwen 特有），v1 不做预算粒度 |

---

## 11. 依赖关系

| 依赖 | 方向 | 说明 |
|------|------|------|
| F5 provider 注册表 | 被依赖 | models[] 条目扩展字段（向后兼容） |
| F23 SSE / #727 reasoning 帧 | 被依赖 | 展示链路零改动复用 |
| F32 设置持久化 | 被依赖 | 全局白名单键扩展 |
| #735/ADR-049 resolve 链、fail-fast | 被依赖 | 思考解析复用同形态；模型缺失仍 422 |
| ADR-047 fake LLM | 被依赖 | 迁移兼容性验收面 |
| deepagents（F29/F47） | 被依赖 | BaseChatModel 注入零改动；`ensure_profile` 保留 |
| F57 日志/i18n | 被依赖 | 降级 WARNING message_key、GUI 文案 |
| F53 脱敏 | 被依赖 | reasoning 帧内容经既有 redact 链（#740 AgentStep 路径覆盖） |

被依赖（消费本模块）：F47 chat 执行详情、F55 统一执行视图（trace 中 reasoning 已存）。

**编号口径声明**：本模块声明为第 23 变体（接续 F49=22；F50-F58 为后续增量不占变体号，
冲突以 ADR-019 v8+ 登记为准）。F59 经交叉核对空闲（specs/README、ADR body、issue 检索）。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选 |
|---|------|------|------|------|
| D1 | LLM 出口统一层 | litellm SDK（非 Proxy）+ ChatLiteLLM | 方言翻译/能力探测/多轮回传三项独有且实测无替代；模型名语法零转换 | 专项包组合 ❌（zhipu 无包仍自写）；自研映射 ❌（违背复用社区方案原则）；Proxy sidecar ❌（单机重） |
| D2 | 档位枚举 | litellm 七档直传（none…xhigh+default） | 用户拍板 B：不发明本地档位，零翻译损耗 | 六档自定义 ❌（被 B 否决） |
| D3 | 配置入口分层 | chat per-call / 写作+全自动项目级 / 全局兜底 | 用户拍板：决策面在交互层，注册表只存连接信息；能力标记可覆盖 | 档位进注册表 ❌（provider 属性 ≠ 调用偏好，评审共识） |
| D4 | 能力探测 | litellm 模型表 + 注册表手动覆盖三级链 | `/models` 端点实证无能力字段（四字段裸清单） | /models 自动探测 ❌（实证否决）；运行时试探测 ❌（费 token） |
| D5 | 超能力降级 | 软降级 + WARNING，不断流 | 思考是偏好非硬依赖；区别于 ADR-049 模型缺失 fail-fast；**Q1 拍板 ✅（用户：软降级+warn 日志）** | 422 拒绝 ❌（阻断写作主流程，用户否决） |
| D6 | embedding 一并迁移 | 一步到位 | 用户拍板 D；三个调用面单一出口，不留双轨 | chat 先行 embedding 缓 ❌（被否决） |
| D7 | 项目级一档覆盖两管线 | `ProjectConfig.reasoning_effort` 单字段 | 轻量契约偏好；两场景分档待真实反馈 | 两字段（writing/agentic 分开）暂缓 |
| D8 | chat 档位记忆载体 | 前端 localStorage per-project | **Q2 拍板 ✅（用户：确认前端记忆）**；跨刷新保持、零 schema、不落后端库（#770 轻量契约先例） | 纯前端会话态 ❌（刷新即忘）；后端持久化 ❌（加字段被否） |
| D9 | 设定页控件文案 | 标签直写「Agent思考强度设定」，不加说明文案 | **Q3 拍板 ✅（用户：不用两行说明，直接写此名）**；范围（写作链+全自动共用）由控件位置（AI 配置区）隐含 | 加注说明文案 ❌（用户否决） |

---

## 13. 验收标准

> 里程碑 → 实现 issue 拆分映射（spec 合入后建 issue）：M1=迁移批、M2-M5=功能批（后端/GUI 可并行）、M6=收尾治理。

| M | 验收 | 载体 |
|---|------|------|
| M1 迁移不破 | 三构造点 ChatLiteLLM 化后：既有全量测试绿（9.2 清单清零 grep 证据）+ fake 全链路 E2E（写作链+chat+embedding）绿 + `rg -c "ChatOpenAI\|OpenAIEmbeddings" src/` 仅剩注释（0 构造引用） | `uv run pytest tests/ -q`（backend）+ e2e fake |
| M2 解析链 | 三级优先级单测 + API 422 + `default` 不发参数断言 | 9.1 单元/API |
| M3 chat 闭环 | GUI 选择器出现且默认「跟随模型默认」；选 high 发送 → fake 注入 reasoning_content → 流式思考区块渲染；不支持模型（能力 false）控件置灰 | Playwright + Vitest（UI 必须出现断言） |
| M4 写作链/全自动闭环 | 设定页保存档位 → PATCH 回显；管线装配日志断言 kwargs 含档位；agentic AgentRun trace steps 含 reasoning（#740 路径） | tests/api + e2e-ai-backend 真实抽测（deepseek high） |
| M5 真实模型实证 | e2e-ai-backend：deepseek 思考帧非空 + 多轮回传 + dashscope enable_thinking 透传 + zhipu glm-4.5 软降级日志，四项各有 PASS 记录 | e2e-ai-*（本地开关模式） |
| M6 治理 | f5/f4-pipeline spec 修订融合（修改履历列）+ AGENTS.md 四处同步 + ADR-051 状态✅ + 设计双件套（chat/设定页 ASCII 线框 + design/GUI HTML/PNG） | docs 收尾 PR 审查 |

验收命令基线：`cd backend; uv run pytest tests/unit/ -q`、`uv run pytest ../tests/api/ -q`、
前端 `pnpm vitest run`；真实 AI 项手动开 `e2e-ai-backend`（用户本地 key）。

---

## 待澄清问题

**Q1 超能力请求的处理**：✅ 已确认（用户拍板 2026-09-06：选项 A —— 软降级 + WARNING 日志，不断流）
→ 正文落点 §5.5（拍板标注）、§3.3 异常表、§12 D5。B（422 fail-fast）否决。

**Q2 chat 页档位记忆的载体**：✅ 已确认（用户拍板 2026-09-06：选项 B —— 前端 localStorage per-project）
→ 正文落点 §3.4 选择器行为列、§12 D8。A（纯前端会话态）否决。

**Q3 写作链/全自动项目级字段的 GUI 文案**：✅ 已确认（用户拍板 2026-09-06：新决策 ——
不设两行说明，控件标签直接写「Agent思考强度设定」；A 选项「共用+说明」否决）
→ 正文落点 §1.1 表、§3.4、§12 D9。
