# InkFlow Phase 1 Gate 评审报告

- **日期**: 2026-08-01
- **评审方式**: 全部实证（实测运行测试 / 启动服务 / 源码核查 / Issue 统计），非文档预设勾选
- **评审人**: Hermes 软件架构师 + 用户拍板
- **结论**: **有条件通过（CONDITIONAL PASS）** — 6/7 项通过，G4 缺失为唯一拦截项

---

## 1. Gate 判定总览

| # | Gate 标准 | 判定 | 实证依据 |
|---|-----------|------|----------|
| G1 | CLI 完整 AI 写作流程（建书→写章节→审校） | ✅ 通过 | `tests/cli/` 实测 29 passed（project/chapter/writing/agent 全链路，mock LLM）；命令齐全：`project / chapter / volume / write / agent / llm / config / serve` + `--json` 信封 |
| G2 | ≥ 3 个 LLM Provider 可用 | ⚠️ 有条件通过 | 注册 4 个：openai / deepseek / anthropic / ollama；OpenAI 兼容 endpoint 实际可用 3 个（openai、deepseek、ollama）；anthropic 走 ChatOpenAI 端点实际不可用（见 §3.2） |
| G3 | `inkflow serve` 可启动 Web 服务 | ✅ 通过（实测） | 实际启动成功（127.0.0.1:8765）；`/health` → `{"status":"ok","version":"0.1.0","mode":"local"}`；OpenAPI 20 个端点全部注册 |
| G4 | 云端 Protocol 接口定义完毕 | ❌ **不通过** | PRD §6.5 要求 6 个云端接口（Auth/Database/Storage/User/Sync/MCPTransport），代码中 0 个；`domain/ports/__init__.py` 仅含内部端口 |
| G5 | 测试覆盖率 ≥ 50% | ✅ 通过（实测） | 76.00%（门槛 50%）；263 passed / 0 failed（含 1 例环境误报，见 §3.3） |
| G6 | Bug-to-Feature ≤ 1.0:1 | ✅ 通过 | Bug 1（#11）: Feature 10 → 0.1:1 |
| G7 | 本地部署 ≤ 3 步 | ✅ 通过 | `pip install`（`[project.scripts] inkflow` 入口）→ 配置 API key → `inkflow serve`；实测链路成立（G3 联动） |

## 2. 决议

- **Phase 1 Gate：有条件通过**
- 前置条件（拦截项）：补齐 G4 — 定义 6 个云端 Protocol（P0-11 补漏）
- 附带修正：ADR-005v2 漂移（§3.2）、test_log 测试隔离缺陷（§3.3）、AGENTS.md 过期（§3.4）
- 决议后行动：修复项完成 → 正式关闭 Phase 1 → 启动 Phase 2（F9 角色管理）

## 3. 评审发现的问题

### 3.1 🔴 P1 — G4 云端 Protocol 缺失（唯一 Gate 拦截项）

- PRD P0-11 要求"云端接口 Protocol 定义完毕"，§6.5 明确列出 6 个接口：
  `AuthProtocol`（LocalTrust → JWTAuth）、`DatabaseProtocol`（SQLiteAdapter → PostgreSQLAdapter）、
  `StorageProtocol`（LocalFileStorage → CloudObjectStorage）、`UserProtocol`（SingleUser → MultiTenant）、
  `SyncProtocol`（无同步 → CloudSync）、`MCPTransport`（stdio → Streamable HTTP）
- 实测：`domain/ports/` 下搜索 0 结果；现有 9 个 Protocol 均为内部出站端口（LLM/Repo/Context/Agent/VectorStore/PromptTemplate/Summary）
- 影响：Phase 1 唯一未交付 P0；不阻碍本地功能，但云端演进契约缺失
- 处置：新建 Issue + spec（走 worktree 流程），纯接口定义 + 测试，无实现

### 3.2 🟠 P2 — ADR-005v2 漂移（ChatLiteLLM vs ChatOpenAI）

- ADR-005v2 决策为"LangChain ChatLiteLLM"；实现为 `langchain_openai.ChatOpenAI` + custom base_url（`infrastructure/llm/langchain_client.py:11-12`）
- `provider_config.py` 注册 anthropic，但实现仅支持 OpenAI 兼容端点 → anthropic 虚假注册
- 处置（用户拍板 ②A）：**改 ADR 认可 ChatOpenAI + base_url 实际路线**；anthropic 从注册表移除/标注；ADR 更新与代码变更同 PR（治理规则：决策变更先改 ADR 再改代码，PR 引用 ADR）

### 3.3 🟡 P3 — test_log 回归测试隔离缺陷

- `tests/unit/test_log.py::test_setup_logging_creates_log_in_backend_logs_from_other_cwd` 假设 `backend/logs/` 无现存日志文件
- 实测复现：serve 进程占用 `inkflow_2026-08-01.log` 时测试误报 1 fail；清理后 3 passed
- 根因：测试依赖全局环境状态（真实 logs 目录），非代码 bug；CI 干净环境掩盖
- 处置：测试改用 `tmp_path` 隔离，不触碰真实 `backend/logs`

### 3.4 🟡 P3 — 文档过期

- `AGENTS.md` 仍写"当前 Phase 1，F1-F7 在研"
- 处置：更新 Phase 状态

## 4. 环境备注

- 本地 `.venv`（`backend/.venv`）补装完整依赖（langchain 全家桶 / langgraph 1.2.10 / chromadb 1.5.9 / sentence-transformers 5.6.1）后全量测试通过
- 系统 python 未安装 inkflow 包；**所有测试/命令必须使用 `backend\.venv\Scripts\python.exe`**

## 5. Phase 1 交付回顾

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| F1-F7 | 项目/章节/写作管道/Agent 编排/LLM Provider/上下文/CLI | ✅ (PRs #8/#9/#21/#22/#16/#27/#28) |
| F8 | 测试三层分层 + CI 并行 | ✅ (PRs #24/#25, ADR-018) |
| CI 杂项 | pip 缓存 / Node 24 | ✅ (#30-#33) |
| ADR | 18 条有效 | ✅ |

*来源：实测评审 2026-08-01；关联 PRD §8-9（Phase Gate Criteria）*
