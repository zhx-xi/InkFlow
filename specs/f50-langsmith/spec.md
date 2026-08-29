# Spec: F50 LangSmith 可观测性追踪接入
> **端**: backend

> **Spec 版本**: 1.0
> **关联 Issue**: #629
> **Feature 编号**: F50（0.12.0）
> **状态**: 待实现 🔲
> **依赖**: 无（langsmith 0.10.15 已传递安装；LangChain 1.3.14 + LangGraph 1.2.10 + deepagents 0.7.5）

---

## 1. 概述

为 InkFlow 的 LLM/Agent 运行引入 **LangSmith 可观测性追踪**，用于调试 deepagents 完整执行链路（工具调用、模型交互、决策点、子 agent）。LangChain 1.x 的 LangSmith 追踪为**纯环境变量驱动**：设置 `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` 即启用，deepagents（构建于 LangGraph）自动捕获完整 trace，**零业务代码改动**。

本 feature 把当前 `config.py` 中**空壳声明**的 `langsmith_*` 字段完成真实接线：启动时按 config 注入 LangSmith 环境变量。

**用户拍板（2026-08-24）**：方案 C = 默认关闭 + 先 SaaS（`smith.langchain.com`），后续可切自托管。核心原则：
- **默认关**：`langsmith_enabled=False` 保留现状；仅显式开启才注入 env
- **按需开**：调试 agent 行为时手动开启，日常写作不追踪（内容不上云）
- **key 不落盘明文**：经 env `INKFLOW_LANGSMITH_API_KEY` / config.json 注入；全程 mask

---

## 2. 范围外声明（Out of Scope）

| 项 | 说明 | 后续 |
|----|------|------|
| LangSmith **evaluation/evals**（数据集/评分器） | 仅接入 trace 运行，不做评测 | 挂后续 |
| LangSmith **feedback/annotation** 回传 | 不采集人工反馈 | 挂后续 |
| **自托管**部署（docker LangSmith OSS） | 本批通过 `langsmith_endpoint` 字段**预留**配置位，不提供部署编排 | 用户后续自建 |
| `APIKeyManager` 加密存储 key | key 本批走 config 字段（env 注入），不走加密 key 库 | 用户后续如偏好可切换 |
| 历史运行补 trace / flight recorder | 不追溯既有 runs | 挂后续 |
| 追踪采样率 / 流量控制 | 全量追踪，不做采样 | 挂后续 |

---

## 3. 配置项（数据模型）

均为 `inkflow.core.config.InkFlowConfig` 字段，经 env `INKFLOW_*` 或 `.env` / `config.json` 覆盖。

| 字段 | 类型 | 默认值 | env 变量 | 说明 |
|------|------|--------|----------|------|
| `langsmith_enabled` | `bool` | `False` | `INKFLOW_LANGSMITH_ENABLED` | 是否启用 LangSmith 追踪。**默认关** |
| `langsmith_api_key` | `str` | `""` | `INKFLOW_LANGSMITH_API_KEY` | LangSmith API Key（`lsv2-...`）。为空时不注入 |
| `langsmith_project` | `str` | `"inkflow"` | `INKFLOW_LANGSMITH_PROJECT` | LangSmith 项目名（默认 `default`，显式指定为 `inkflow`） |
| `langsmith_endpoint` | `str` | `""` | `INKFLOW_LANGSMITH_ENDPOINT` | 自托管端点。空 = SaaS `smith.langchain.com`（本批新增字段） |

---

## 4. 行为契约

### 4.1 LangSmith env 解析（纯函数）

新增模块级纯函数 `resolve_langsmith_trace_env(cfg: InkFlowConfig) -> dict[str, str]`：

- `cfg.langsmith_enabled == False` → 返回空 dict `{}`（不注入）
- `cfg.langsmith_enabled == True` 且 `cfg.langsmith_api_key == ""` → 返回空 dict `{}` + `logger.warning`（提示 key 缺失）
- `cfg.langsmith_enabled == True` 且 key 非空 → 返回：
  ```python
  {
      "LANGSMITH_TRACING": "true",
      "LANGSMITH_API_KEY": cfg.langsmith_api_key,
      "LANGSMITH_PROJECT": cfg.langsmith_project or "inkflow",
  }
  ```
  若 `cfg.langsmith_endpoint` 非空 → 追加 `"LANGSMITH_ENDPOINT": cfg.langsmith_endpoint`
- **幂等**：同一 cfg 多次调用返回相同结果（无外部副作用）

### 4.2 LangSmith env 应用（有副作用）

新增模块级函数 `apply_langsmith_tracing() -> None`：

1. 先无条件 `os.environ.pop` 以下 4 键（清除残留，保证测试/重启幂等）：`LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` / `LANGSMITH_ENDPOINT`
2. 调用 `resolve_langsmith_trace_env(config)`（全局单例）
3. 结果非空 → `os.environ.update(result)` + `logger.info("LangSmith 追踪已启用 → project=%s", cfg.langsmith_project)`

### 4.3 注入点

在 `api/app.py` 的 `lifespan()` 顶段（`setup_logging()` 之前）调用 `apply_langsmith_tracing()`。理由：
- 内核所有 LLM/Agent 调用（REST API / CLI / MCP）均经内核 FastAPI 进程 → 单一注入点覆盖全部入口
- 首次注入早于任何 `ChatOpenAI` 实例化（agent 按 request 懒创建），保证 trace 生效
- CLI（`inkflow` / `inkflow-mcp`）经 HTTP 委托内核，无需单独注入

### 4.4 追踪范围

- 覆盖所有经内核的 LLM 调用：writer agent、chat agent、supervisor 决策、RAG embedding（如走 langchain）
- 不覆盖：非 LangChain 的直接上游 HTTP 调用（无 trace 语义）

---

## 5. 边界与错误表

| 场景 | 行为 | 严重度 |
|------|------|--------|
| `langsmith_enabled=False`（默认） | 不注入任何 `LANGSMITH_*`，无副作用 | 无 |
| `langsmith_enabled=True` + key 空 | 不注入 + `logger.warning`（非致命，不阻断启动） | 低 |
| `langsmith_enabled=True` + key 非空 | 注入 3-4 个 env | 无 |
| `langsmith_project` 空串 | 回退默认 `"inkflow"` | 无 |
| `langsmith_endpoint` 非空 | 追加 `LANGSMITH_ENDPOINT` | 无 |
| key 含异常字符 / 格 | 原样注入（LangSmith SDK 处理），不校验 | 无 |
| 重复调用 `apply_langsmith_tracing` | 幂等（先 pop 再 update） | 无 |

---

## 6. 测试策略

### 6.1 单元测试（`backend/tests/unit/test_langsmith_tracing.py`）

纯函数为主（不依赖真实 os.environ 残留）：

| 用例 | 断言 |
|------|------|
| `enabled=False` → `resolve` 返回 `{}` | `== {}` |
| `enabled=False` → `apply` 后 `LANGSMITH_TRACING` 不在 env | `os.environ.get()` is None |
| `enabled=True` + key → `resolve` 返回 4 键精确值 | dict 逐项相等；`TRACING=="true"` / `PROJECT=="inkflow"` |
| `enabled=True` + key 空 → `resolve` 返回 `{}` | `== {}` |
| `enabled=True` + key + endpoint → 含 `LANGSMITH_ENDPOINT` | `env["LANGSMITH_ENDPOINT"] == endpoint` |
| `enabled=True` + project 空串 → PROJECT 回退 `"inkflow"` | `== "inkflow"` |
| 幂等：连续两次 `apply` → 结果一致 | env 状态一致 |
| `apply` 在「上次已注入、本次 disabled」→ 清除 4 键 | 全部 `is None` |

### 6.2 集成（本地手动，不进 CI）

启动 kernel → 设 `INKFLOW_LANGSMITH_ENABLED=true` + key → 真实 LLM 调用 → 在 smith.langchain.com 项目 `inkflow` 下看到 trace。

**CI / E2E 隔离**：单元/集成测试默认 `langsmith_enabled=False` → 不污染 CI；`LANGSMITH_*` 不在测试环境残留。

---

## 7. 文件结构

### NEW

| 路径 | 职责 |
|------|------|
| `backend/src/inkflow/core/langsmith_tracing.py` | `resolve_langsmith_trace_env` / `apply_langsmith_tracing` + `_LANGSMITH_ENV_KEYS` 常量 |
| `backend/tests/unit/test_langsmith_tracing.py` | 单元测试（§6.1） |

### MODIFY

| 路径 | 变更 |
|------|------|
| `backend/src/inkflow/core/config.py` | 新增 `langsmith_endpoint` 字段（§3） |
| `backend/src/inkflow/api/app.py` | `lifespan()` 顶段调用 `apply_langsmith_tracing()`（§4.3） |

> ⚠️ `config.py` 现有 `langsmith_api_key` / `langsmith_project` / `langsmith_enabled` 三字段保留不动（已存在），仅新增 `langsmith_endpoint`。

---

## 8. 决策记录

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| 默认状态 | 关闭（`enabled=False`） | 默认开 | 内容不上云；调试时手动开（用户拍板 C） |
| 云 vs 自托管 | 先 SaaS + `endpoint` 预留 | 直接自托管 | SaaS 零部署成本；key 免费；自托管后续可切（endpoint 字段已留） |
| key 存储 | config 字段（env 注入） | APIKeyManager 加密库 | LangSmith key 非 LLM provider key；v1 最小化（范围外声明 §2） |
| env 注入点 | `lifespan()` 单点 | 每 request / CLI 注入 | 内核单进程覆盖全部入口；早于首次 ChatOpenAI |

---

## 9. ADR 关联

新增 **ADR-042**（决策先于代码）：LangSmith 可观测性接入——默认关 + SaaS 优先。ADR-019 版本表在 0.12.0 收尾时补登记 F49/F50 行。

> **注意**：本 spec 为 config 驱动横切类型，无独立数据表 / API / CLI 命令面（§2/§3/§5 明确）。

---

## 10. 动作确认

> 每个组件方法流的完整状态流表（基于 §3 配置项 + §4 行为契约 + §5 边界事实，不重复）。

### 10.1 组件方法流（resolve_langsmith_trace_env 纯函数）

| 输入组合 | 前置 | 动作 | 成功 | 失败 | 边界 |
|---------|------|------|------|------|------|
| enabled=False | 无 | 直接返回空 dict，不注入 | {} | — | 无副作用；默认关（用户拍板方案 C） |
| enabled=True + key 空 | — | 返回 {} + logger.warning | {} | warning（非致命，不阻断启动） | 提示 key 缺失 |
| enabled=True + key 非空 | — | 构造 3 键 env | LANGSMITH_TRACING=true + LANGSMITH_API_KEY + LANGSMITH_PROJECT | — | PROJECT 空串回退 "inkflow" |
| enabled=True + key 非空 + endpoint 非空 | — | 追加 LANGSMITH_ENDPOINT | 4 键 env | — | 自托管端点预留（§2 范围外声明） |
| 任意组合重复调用 | — | 纯函数多次求值 | 结果一致（幂等） | — | 无外部副作用 |

### 10.2 组件方法流（apply_langsmith_tracing 副作用）

| 输入组合 | 前置 | 动作 | 成功 | 失败 | 边界 |
|---------|------|------|------|------|------|
| disabled（enabled=False） | 无 | 先无条件 pop 4 键 → resolve 返回 {} → 不 update | 4 键不在 env（清除残留） | — | 先 pop 再 update，幂等 |
| enabled=True + key 非空 | — | pop 4 键 → resolve 非空 → os.environ.update + logger.info | env 注入 + info 日志（project=%s） | — | 注入点 = api/app.py lifespan() 顶段（setup_logging 之前，早于首次 ChatOpenAI 实例化）；REST/CLI/MCP 全入口单点覆盖 |
| 上次已注入、本次 disabled | — | pop 4 键 | LANGSMITH_TRACING / API_KEY / PROJECT / ENDPOINT 全部 is None | — | 测试/重启幂等（§6.1 断言） |
| key 含异常字符/格式 | — | 原样注入 | 透传 | — | 不校验（LangSmith SDK 处理） |
| 重复调用 | — | 先 pop 再 update | 幂等 | — | 无脏残留 |

### 10.3 验收锚点（写入 §6 测试策略）

- A1：enabled=False → resolve 返回 {} 且 apply 后 LANGSMITH_TRACING 不在 env → §6.1 用例 1-2
- A2：enabled=True + key → resolve 返回 4 键精确值（TRACING=="true" / PROJECT=="inkflow"）→ §6.1 用例 3
- A3：enabled=True + key 空 → resolve 返回 {} + warning，启动不被阻断 → §6.1 用例 4
- A4：endpoint 非空 → 含 LANGSMITH_ENDPOINT；project 空串 → 回退 "inkflow" → §6.1 用例 5-6
- A5：连续两次 apply → env 状态一致；disabled 后 4 键全部清除 → §6.1 用例 7-8
