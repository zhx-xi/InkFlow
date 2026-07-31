# F5: LLM Provider 适配层 (llm_service) — 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-07-31 | **依据**: PRD v2.1 §6.1 F5, Constitution P1-P6
> **所属阶段**: Phase 1 — Sprint 1.2（数据层+LLM 适配）
> **依赖**: 无（F5 是 F3/F4/F6 的前置依赖）
> **参考 ADR**: [ADR-005v2](../../docs/adr/ADR-005v2.md) (LangChain ChatLiteLLM), [ADR-014](../../docs/adr/ADR-014.md) (ChatPromptTemplate), [ADR-015](../../docs/adr/ADR-015.md) (LangChain 隔离规则)

---

## 1. 概述

实现 LLM Provider 抽象层的**基础设施侧**：`LangChainLLMClient`（基于 ChatLiteLLM）、`LangChainPromptManager`（基于 ChatPromptTemplate + YAML）、和 `APIKeyManager`（AES-256-GCM 加密）。

**核心价值**: 领域层通过 `LLMClientProtocol` / `PromptTemplateProtocol` 使用 LLM，但不感知 LangChain。新增 Provider 只需环境变量注入 API Key，零代码改动。

> **领域层 Ports 已定义** — `domain/ports/llm_client.py` 和 `domain/ports/prompt_template.py` 已存在，本次只实现基础设施层。

---

## 2. 架构依赖方向检查

```
 api/routers/ → domain/services/ → domain/ports/LLMClientProtocol
                                        ↑ (依赖倒置)
                                 infrastructure/llm/LangChainLLMClient
                                        ↓ (内部使用)
                                 langchain_community.ChatLiteLLM

 domain/ 不 import langchain（CI 强制检查）
 domain/ 不 import infrastructure/
```

---

## 3. 数据模型

### 3.1 领域层模型（已存在，本次不修改）

| 类型 | 文件 | 说明 |
|------|------|------|
| `ChatMessage` | `domain/ports/llm_client.py` | 聊天消息（role + content） |
| `ChatResponse` | `domain/ports/llm_client.py` | LLM 响应（content + model + token_usage + finish_reason） |
| `StreamEvent` | `domain/ports/llm_client.py` | 流式事件（content + is_final + token_usage） |
| `TokenUsage` | `domain/ports/llm_client.py` | Token 统计（prompt/completion/total） |
| `PromptTemplate` | `domain/ports/prompt_template.py` | 模板（name + system_prompt + human_prompt + variables） |
| `RenderedPrompt` | `domain/ports/prompt_template.py` | 渲染结果（messages + token_estimate） |

### 3.2 基础设施层新增模型

**LLMProviderConfig** — 单个 Provider 的配置，从环境变量加载：
- `provider: str` — 如 "openai", "deepseek"
- `api_key: str` — 运行时从 KeyManager 解密或环境变量读取
- `base_url: str | None` — 自定义端点（如 Ollama: http://localhost:11434）
- `default_model: str` — 默认模型名
- `max_retries: int = 3`, `timeout: int = 120`

**EncryptedKey** — 加密后的 API Key 存储格式：
- `provider: str`, `encrypted_key: bytes`, `nonce: bytes` (GCM 12 bytes)

---

## 4. 基础设施实现组件

### 4.1 LangChainLLMClient (`infrastructure/llm/langchain_client.py`)

实现 `LLMClientProtocol`，内部使用 `ChatLiteLLM`。

| 方法 | 说明 |
|------|------|
| `chat(messages, *, model, temperature, max_tokens)` → `ChatResponse` | 异步获取完整响应 |
| `chat_stream(messages, *, model, temperature, max_tokens)` → `AsyncGenerator[StreamEvent]` | 流式逐 token |
| `count_tokens(messages, *, model)` → `int` | tiktoken 估算，回退字符数/4 |

**内部流程**: `ChatMessage(domain)` → `HumanMessage/SystemMessage(LangChain)` → `ChatLiteLLM.ainvoke` → `AIMessage` → `ChatResponse(domain)`

**Provider 路由**: `model` 参数格式 `provider/model_name`（如 `openai/gpt-4o`），解析 provider → 查 API Key → 注入 ChatLiteLLM。

**重试**: LangChain 内置 `with_retry()` + 指数退避，max_retries 默认 3，超时 120s。耗尽后抛出 `LLMRequestError`。401 认证错误不重试。

> **YAGNI 决策**: 不显式维护 `ProviderManager` 类。Provider 配置通过 Pydantic Settings 环境变量注入，`LangChainLLMClient` 在调用时按需解析。

### 4.2 LangChainPromptManager (`infrastructure/llm/prompt_manager.py`)

实现 `PromptTemplateProtocol`，YAML 模板 + ChatPromptTemplate 渲染。

| 方法 | 说明 |
|------|------|
| `load(template_name)` → `PromptTemplate` | 从 `templates/{name}.yaml` 加载 |
| `render(template, variables)` → `RenderedPrompt` | 渲染变量 |
| `validate(template, variables)` → `list[str]` | 返回缺失变量 |
| `list_templates()` → `list[str]` | 列出所有模板 |

**Phase 1 模板（4 个）**: writer / architect / auditor / reviser，每个含 system_prompt + human_prompt + variables。

### 4.3 APIKeyManager (`infrastructure/llm/key_manager.py`)

API Key 的 AES-256-GCM 加密存储。不定义 Protocol（基础设施内部实现）。

| 方法 | 说明 |
|------|------|
| `encrypt(provider, api_key)` → dict | AES-256-GCM 加密 |
| `decrypt(provider, encrypted_data)` → str | 解密 |
| `store / load / delete / list_providers` | 持久化 CRUD |

**安全约束**: secret_key 通过环境变量注入不落盘；密文存 `{data_dir}/keys/{provider}.enc`；空 secret_key 时明文模式 + WARNING。

### 4.4 错误类型 (`domain/ports/llm_errors.py`)

- `LLMRequestError` — provider/model/retries_exhausted
- `TemplateNotFoundError` — template_name
- `TemplateRenderError` — template_name/missing_variables

> 错误定义在 domain/ports/：领域层 Service 需捕获做业务决策，且错误本身零框架依赖。

---

## 5. 文件结构

```
backend/src/inkflow/
├── domain/ports/
│   ├── llm_client.py            #  已存在 — LLMClientProtocol + 数据类
│   ├── prompt_template.py       #  已存在 — PromptTemplateProtocol + 数据类
│   ├── llm_errors.py            #  新增 — LLMRequestError 等
│   └── __init__.py              #  修改 — 导出新错误类型
│
├── infrastructure/llm/          #  新增目录
│   ├── __init__.py              #  新增 — 模块导出
│   ├── langchain_client.py      #  新增 — LangChainLLMClient
│   ├── prompt_manager.py        #  新增 — LangChainPromptManager
│   ├── key_manager.py           #  新增 — APIKeyManager
│   ├── provider_config.py       #  新增 — Provider 配置加载
│   └── templates/               #  新增 — YAML 模板目录
│       ├── writer.yaml
│       ├── architect.yaml
│       ├── auditor.yaml
│       └── reviser.yaml

backend/tests/
├── test_llm_client.py           #  新增
├── test_prompt_manager.py       #  新增
├── test_key_manager.py          #  新增
└── conftest.py                  #  修改 — 添加 temp_keys_dir fixture
```

---

## 6. 边界情况与错误处理

| 场景 | 行为 | 错误类型 |
|------|------|---------|
| API Key 未配置 | `LLMRequestError("API key not configured for provider: X")` | `LLMRequestError` |
| API Key 无效 (401/403) | 不重试，直接抛异常 | `LLMRequestError(retries_exhausted=False)` |
| 网络超时 | 指数退避重试 ≤ 3 次 | `LLMRequestError(retries_exhausted=True)` |
| 模型不支持 | `LLMRequestError(f"Model X not available")` | `LLMRequestError` |
| 模板文件不存在 | `TemplateNotFoundError` | — |
| 模板缺少变量 | `TemplateRenderError` + missing_variables | — |
| YAML 格式错误 | `TemplateRenderError` | — |
| stream 中断 | AsyncGenerator 抛异常 | `LLMRequestError` |
| 空消息列表 chat([]) | `ValueError("messages cannot be empty")` | `ValueError` |
| 无 tokenizer 模型 | 回退字符数/4 + WARNING | — |
| secret_key 为空 | 明文模式 + WARNING | — |

---

## 7. 测试策略

### 测试层次

```
集成测试: langchain_client + real LLM (手动触发)  ≤ 1
单元测试: Mock ChatLiteLLM → LangChainLLMClient      7 cases
单元测试: LangChainPromptManager (虚拟模板)           7 cases
单元测试: APIKeyManager (加解密往返)                  10 cases
```

### 关键测试场景 (24 个)

**LangChainLLMClient (Mock)**: chat 正常/指定 model/缺 Key/stream 流式/最终 chunk/网络重试耗尽/401 不重试/count_tokens 正常/空消息=0/空消息抛 ValueError

**LangChainPromptManager**: load 存在/不存在/Render 完整/缺少变量/Validate 满足/缺失/list/最小模板

**APIKeyManager**: 加解密往返/持久化往返/不同 Provider 独立/删除/list 有/list 空/不存在抛异常/明文模式/不同密钥解密失败

---

## 8. 不在范围内

| 项 | 原因 |
|----|------|
| 模型路由业务逻辑 | F3/F4 职责 |
| LangSmith 追踪集成 | Phase 2 |
| SSE API 端点 | F3/F4 API 层 |
| Ollama 本地模型管理 CLI | Phase 2 |
| Provider 配置 Web UI | Phase 2 |
| tiktoken 以外的 tokenizer | Phase 1 |

---

## 9. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | LangChainLLMClient 全部 Mock 测试通过 | `pytest tests/test_llm_client.py -v` 全绿 |
| M2 | LangChainPromptManager 全部测试通过 | `pytest tests/test_prompt_manager.py -v` 全绿 |
| M3 | APIKeyManager 全部测试通过 | `pytest tests/test_key_manager.py -v` 全绿 |
| M4 | domain/ 零 LangChain import | CI 强制检查通过 |
