# 对话输入机密脱敏（#614）

> **Spec（0.12.0，2026-08-23）**：在 AI 对话（`/api/v1/chat/stream` 与 `/api/v1/chat/agent/stream`）把用户 prompt 发送到 LLM **之前**，对其中已知机密信息做 redact（模糊），避免用户粘贴 API 密钥等机密经 prompt 原样外泄给模型提供方。
>
> 依赖：`#597`（chat 接入 deepagents 系统级 Agent）已合入；本 spec 在其 chat 流式端点入口做安全加固，不改动消息/SSE 帧协议之外的行为。
>
> ## 拍板记录（2026-08-23，用户拍板）
>
> | 决策 | 结论 | 说明 |
> |------|------|------|
> | D1 脱敏组合 | **A+B 双兜底** | A=正则识别常见密钥形态；B=与 `APIKeyManager` 联动，把**已存储密钥**明文在 prompt 内做精确子串替换。A 兜底未存的新密钥格式；B 精确命中已存密钥（最高优先级，最可靠）。 |
> | D2 落点 | **chat 两条流式端点入口** | 仅在 `/stream`、`/agent/stream` 的 `prompt` 进入 LLM 前脱敏；不动存档/历史消息，避免污染既有一致性。 |

---

## 1. 现状与分析（代码实锤，2026-08-23）

| 链路 | 现状 | 端点 |
|------|------|------|
| chat 流式 | `chat_stream.py` L102：`prompt = (data.prompt or "").strip()` 原样传给 `svc.stream(prompt=prompt)` | `POST /api/v1/chat/stream` |
| chat agent 流式 | `chat_stream.py` L133：`prompt` 原样传给 `svc.stream_events(prompt=prompt)`；`chat_agent_service.py` L43-46 直接 `HumanMessage(prompt)` → `astream_events` | `POST /api/v1/chat/agent/stream` |

- **无过滤**：`langchain_client.py _to_langchain_messages` L207-220 直接把 `msg.content` 包进 HumanMessage，无脱敏。
- **项目现有保护（均不覆盖「prompt 内明文」）**：
  - `key_manager.py` AES-256-GCM 加密落盘（生产）/ 明文（dev）。
  - `provider_configs.py _to_response` 只返回 `key_saved` 布尔、不进响应体回显 key。
  - `cli/output.py mask_key()` 仅 CLI 展示（前缀3+后缀4）。
  - **没有任何「把 prompt 内明文密钥模糊后再发 LLM」的机制**——本 spec 填补。

## 2. 需求定义

- **目标**：用户 prompt 若包含已存/常见密钥形态，发送到 LLM 前被 `****` 替换；替换后的 prompt 用于 LLM 调用。
- **非目标**：
  - 不修改消息持久化（chat_messages 存档保留用户原文本，属用户自有数据）。
  - 不做「禁止用户输入密钥」的强硬拦截（仅脱敏，不阻止用户向 AI 描述密钥）。
  - 不涉前端展示（密钥展示属 #543/#565 已修的显示问题）。

## 3. 设计

### 3.1 脱敏函数 `redact_secrets(prompt, known_keys) -> str`

位置：`backend/src/inkflow/infrastructure/llm/redact.py`（与 `key_manager` 同域，API 层可直接 import）。

```python
def redact_secrets(prompt: str, known_keys: list[str] | None = None) -> str:
    """把 prompt 内常见密钥形态与已存密钥替换为 '****'。

    A（正则兜底）:
      - OpenAI 风格 sk- + [A-Za-z0-9_-]{12,}         -> 保留 'sk-' 前缀 + '****'
      - Authorization: Bearer <token>                 -> token 替换 '****'
      - 连续 >=24 位的 [A-Za-z0-9_-] 串（疑似 token）   -> '****'
    B（已存密钥精确子串替换）: known_keys 非空时，对每个 key 全量替换 '****'。
    """
```

- **A 正则**：`re.sub`，对 `sk-...`、`Bearer ...`、长 token 分别替换。`sk-` 保留 `sk-`（`sk-****`），`Bearer` 保留 `Bearer`（`Bearer ****`）。
- **B 已存密钥**：遍历 `known_keys`（明文），`prompt.replace(key, "****")`；`known_keys` 为空则跳过（纯 A）。
- **无匹配** → 原样返回。

### 3.2 端点接线

- `chat_stream.py` 的 `stream_chat`（L95）/ `stream_chat_agent`（L126）：`prompt = redact_secrets(prompt, known_keys)` 放在 `prompt` strip 校验之后、进入 `svc.stream/stream_events` 之前。
- `known_keys` 来源：`get_key_manager()` → `list_providers()` → 逐个 `load()` 取明文；加载失败（dev 明文/解密失败）跳过该 provider，不阻断对话。
  - 抽取 `_load_known_keys() -> list[str]` 工具函数（放 `redact.py` 或端点模块），供两条端点复用。

### 3.3 边界

| 边界 | 行为 |
|------|------|
| prompt 无密钥 | 原样返回 |
| 已存 key = 空（无任何 provider 存 key） | 仅走 A 正则 |
| key_manager 解密失败 | 跳过该 provider，不抛错（防御） |
| 同一 prompt 含多个 key | 全部替换 |
| `Bearer ` 后无 token | 不替换（防御，避免误伤） |

## 4. 测试策略（RED 契约 → GREEN）

### 4.1 单元测试（`backend/tests/unit/test_redact.py`，NEW）

- **A 正则**：
  - `sk-` 形态 → `sk-****`（key 部分被替换，前缀保留）。
  - `Bearer xyz...` → `Bearer ****`。
  - 长 token 串（>=24 位）→ `****`。
  - 普通文本 → 原样。非密钥高密串（如 URL、中文）不误伤。
- **B 已存 key 子串**：
  - `known_keys=["sk-abc..."]`，prompt 含该 key → 被 `****` 替换。
  - `known_keys=[]` → 仅 A。
- **无匹配** → 原样。
- **回调语义**（端点级，`test_chat_stream.py` 追加）：mock LLM 收到的 `messages[0].content` 不含密钥（已替换）。

## 5. 范围外声明

- **不改消息存储**：chat_messages 存档保留用户原文本。
- **不做密钥强拦截 / 禁止输入**。
- **不涉 CLI agentic 写作**（agentic 输入来自项目内容非用户贴的密钥，本 issue 聚焦 chat 对话流式端点）。
- **不处理「模型返回 leak 密钥」**（只脱敏用户→模型方向）。

## 6. 文件结构

| 文件 | 变更 |
|------|------|
| `backend/src/inkflow/infrastructure/llm/redact.py` | NEW（§3.1 `redact_secrets` + `load_known_keys`） |
| `backend/src/inkflow/api/routers/chat_stream.py` | MODIFY（§3.2 两条端点入口接线） |
| `backend/tests/unit/test_redact.py` | NEW（RED） |
| `backend/tests/unit/test_chat_stream.py` | MODIFY（追加端点级脱敏断言） |

## 7. 门禁

- **M0**：本 spec 定稿合入 + ADR-040 合入。
- **M1**：RED 契约 confirm FAIL。
- **M2**：GREEN + 后端 `pytest tests/unit/ ../tests/` + `ruff` + `mypy` 全绿。
- **M3**：PR merged（body `Closes #614`）+ #614 CLOSED + worktree 清理。
