# 契约源 → 断言面联保清单（#993）

> 目的：登记「全仓哪些测试硬编码了后端契约源的内容快照」，供**改契约源的 PR** 机械复核。
> 起始契约源：`backend/src/inkflow/infrastructure/agent/tools/registry.py`
> （`GRANT_TOOL_MAP` / `TOOL_REGISTRY` / `ALL_TOOL_SPECS` / `TOOL_NAME_TO_CELL`）。
> 写作链契约源见 §「写作链契约源联保」。
> 关联：`AGENTS.md` §9 陷阱表、`ai-traps.md`、`.github/workflows/ci.yml` 的 `contract` filter。

## 为什么需要这张表（#985 教训）

改契约源（增删工具名、调整授权格值、改计数）→ 多处硬编码快照断言连锁过期。
若这些断言所在的 CI job 未被契约源变更触发，断裂会**静默入 main**：

- `unit-backend` / `unit-api-backend` / `unit-cli-backend` / `unit-integration-backend`
  恒跑（无 `if:` 门控）→ 后端侧消费方**任意 PR 已被覆盖**。
- `e2e-frontend-settings` 原仅由 `frontend` / `e2e` / `ci` 触发 → **纯后端契约源 PR 不跑**
  → `tests/e2e/e2e-settings-agents-scope.spec.ts` 的 `resolved` 硬编码清单零守卫
  （#972 断裂即由此静默入 main）。

**修复**：`ci.yml` 新增 `contract` paths-filter output，命中即触发 `e2e-frontend-settings`。

## 消费面登记表

改 `registry.py` 表内容前，必须逐条复核下列断言是否需要同步修改。

### e2e-frontend-settings job（由 `contract` filter 触发）

| 文件 | 行 | 硬编码形态 | 锁定符号 |
|------|----|-----------|----------|
| `tests/e2e/e2e-settings-agents-scope.spec.ts` | 252-258 | `resolved: ['create_character','get_character','memory_list','search_characters','update_character']` | `GRANT_TOOL_MAP` (CHARACTER,READ/WRITE) + (MEMORY,READ) |
| `tests/e2e/e2e-settings-agents-scope.spec.ts` | 314-324 | `resolved: [...]` 9 项（加 world·write → create/update_world_setting、create/update_map） | `GRANT_TOOL_MAP` (WORLD,WRITE) |

### unit-backend job（恒跑，无门控）

| 文件 | 行 | 硬编码形态 | 锁定符号 |
|------|----|-----------|----------|
| `backend/tests/unit/infrastructure/agent/test_grant_tool_map.py` | 57-75 | `EXPECTED_MAPPED_NAMES` 47 名清单 | `GRANT_TOOL_MAP` 全体值 |
| `backend/tests/unit/infrastructure/agent/test_grant_tool_map.py` | 107,114,123 | `len(mapped) == 47` / `len(names) == 47` / `len(non_core) == 39` | `GRANT_TOOL_MAP` + `ALL_TOOL_SPECS` 计数 |
| `backend/tests/unit/infrastructure/agent/test_grant_tool_map.py` | 132-137 | `delete_tools` 8 名集合 | `GRANT_TOOL_MAP` delete 格 |
| `backend/tests/unit/infrastructure/agent/test_outline_grant_migration.py` | 多处 | outline 格展开序 / 迁移反查 | `GRANT_TOOL_MAP` / `TOOL_NAME_TO_CELL` / `LEGACY_RENAMED_TOOL_NAMES` |
| `backend/tests/unit/infrastructure/agent/test_resolve_grants.py` | 多处 | grants 优先 / tool_ids 回退 | `resolve_grants` / `grants_from_tool_ids` |
| `backend/tests/unit/infrastructure/agent/test_build_tools_by_grants.py` | 多处 | 按 grants 物化工具集 | `build_tools_by_grants` |
| `backend/tests/unit/domain/models/test_tool_catalog.py` | 76- | `EXPECTED_CATALOG_NAMES` 39 名固定序 | `TOOL_REGISTRY` + `ALL_TOOL_SPECS` 过滤序 |
| `backend/tests/unit/domain/models/test_tool_catalog.py` | 220,226 | `len(TOOL_REGISTRY) == 39` / 名字序断言 | `TOOL_REGISTRY` |
| `backend/tests/unit/infrastructure/agent/test_agent_tool_registry.py` | 187,198 | `len(ALL_TOOL_SPECS) == 49` / `names == EXPECTED_ALL_NAMES` 全集 | `ALL_TOOL_SPECS` |
| `backend/tests/unit/infrastructure/agent/test_agent_tool_registry.py` | 214-216 | `CORE_NAMES.isdisjoint(registry_names)` / `len(TOOL_REGISTRY) == 39` | `TOOL_REGISTRY` + 核心集 |
| `backend/tests/unit/infrastructure/agent/test_reader_tools.py` | 48 | `EXPECTED_TOOL_NAMES` 读者工具名 | `TOOL_REGISTRY` reader 段 |
| `backend/tests/unit/api/deps/test_delete_assembly.py` | 39 | `DELETE_TOOL_NAMES` 8 名 | `ALL_TOOL_SPECS` delete 段 |
| `backend/tests/unit/i18n/test_tool_i18n_parity.py` | 20 | `ALL_TOOL_SPECS` name ↔ `tool.<name>` 双向 bijection | `ALL_TOOL_SPECS` + `i18n/functions/{zh,en}.json` |

### unit-api-backend job（恒跑，无门控）

| 文件 | 行 | 硬编码形态 | 锁定符号 |
|------|----|-----------|----------|
| `tests/api/test_agents_tools_api.py` | 33-87 | `ALL_TOOL_NAMES` 49 全集 + `CORE_TOOL_NAMES` 10 核心 | `ALL_TOOL_SPECS` / `is_core` |
| `tests/api/test_agents_tools_api.py` | 109- | `EXPECTED_DOMAIN_OP` 逐名域/操作映射 | `GRANT_TOOL_MAP` 格值 |
| `tests/api/test_agents_tools_api.py` | 185,203 | `len(items) == 39` / `len(CUSTOM_TOOL_NAMES) == 39` | `TOOL_REGISTRY` 计数 |
| `tests/api/test_agents_grants_api.py` | 51-55 | `WRITING_READ_TOOLS` / `WRITING_WRITE_TOOLS` 格值清单（contract §2.1 逐字派生，非 import） | `GRANT_TOOL_MAP` (WRITING,READ/WRITE) 插入序 |
| `tests/api/test_agents_grants_api.py` | 147,163,230-231 | `resolved_tool_names == (...)` 展开序断言（含 inline `["search_characters","get_character",*WRITING_READ_TOOLS]`） | `expand_grants` 按 `GRANT_TOOL_MAP` 展开序 |

### unit-cli-backend job（恒跑，无门控）

| 文件 | 行 | 硬编码形态 | 锁定符号 |
|------|----|-----------|----------|
| `tests/cli/test_cli_agent_tools.py` | 51- | `TOOL_NAMES` 39 名清单 + 固定序 | `TOOL_REGISTRY` |
| `tests/cli/test_cli_agent_tools.py` | 112,125 | `[item['name'] ...] == TOOL_NAMES` / `len(items) == 39` | `TOOL_REGISTRY` |

### e2e-frontend-writing job（由 `contract` filter 触发，2026-09-18 #1280 起）

| 契约源 | 锁定符号 | 硬编码断言 |
|--------|----------|-----------|
| `backend/src/inkflow/api/deps_chapter_audit.py` | 审计 LLM 装配（`resolve_credentials`） | `tests/e2e/e2e-audit.spec.ts:139/:186` 断言审计弹层出**报告**（200 + degraded）而非 `audit.errorTitle` 错误态；断言 `:160` 报告含章名 |
| `backend/src/inkflow/api/_llm_resolver.py` | `resolve_llm_credentials` / `_EMPTY_MODEL_DETAIL` | 同上（同一条装配链：无模型 → 降级，不得 422，spec §3.3/§5.3） |

> 背景（#1280）：纯后端改动改坏了审计装配（无模型 → 装配期 422），但该 job 仅由
> `frontend`/`e2e`/`ci` 触发 → skip → 断裂静默入 main（同 #972 形态）。
> 单元侧另有恒跑守卫 `unit-backend`（`test_chapter_audit_no_model_degrade_1280.py`）。

## 写作链契约源联保（#1184a）

写作链的 prompt 契约源（章 brief 变量 / writer system prompt / 上下文注入渲染）长期**不在**本清单，
导致「改契约源不触发联保测试」（#1184a 元级缺陷）。

改下列任一契约源前，**必须**跑对应联保测试（`contract` filter 命中即触发）：

| 契约源 | 锁定符号 | 联保测试 |
|--------|----------|----------|
| `backend/src/inkflow/infrastructure/agent/agentic_writer.py` | `_WRITER_READER_NAMES` / `build_writer_agent_system_prompt` | `backend/tests/unit/infrastructure/agent/test_agentic_whitelist.py` |
| `backend/src/inkflow/infrastructure/agent/book_agentic_pipeline.py` | `_build_chapter_brief` / `_delegate_audit` | `backend/tests/unit/infrastructure/agent/test_book_agentic_pipeline.py` |
| `backend/src/inkflow/domain/services/book_service.py` | 章 brief 构造 | `backend/tests/unit/domain/services/test_book_service.py` |
| `backend/src/inkflow/infrastructure/agent/book_pipeline.py` | 章 brief 构造 | `backend/tests/unit/infrastructure/agent/test_book_pipeline.py` |
| `backend/src/inkflow/domain/services/context_service.py` | `render_system_prompt` | `backend/tests/unit/domain/services/test_context_service.py` |
| `backend/src/inkflow/domain/services/writing_service.py` | 写作链编排 | `backend/tests/unit/domain/services/test_writing_service.py` |
| `backend/src/inkflow/api/routers/books.py` | writer factory 装配 | `tests/api/test_books_api.py`（另见 `test_books_api_v12.py` / `test_books_api_stage4.py` / `test_books_api_background.py` / `test_books_api_start_mode.py`） |

### ⚠️ 本门禁的覆盖边界（不要让「门禁全绿」冒充「契约完好」）

**能检测**：契约源被改动但未跑联保测试（`contract` filter 触发）。
**不能检测**：契约源**未改动**、但其行为**已空转**——消费方从未接线、参数收了不用、
依赖注入为 Null 实现（#1175 F6 三轨零调用 / #1176 `NullContextProvider` 产线运行 /
#1181 F39 白名单两条 factory 均未装配）。此类失效**只能靠测试断言取证**（#1185），
门禁对此零判别力——不要因门禁全绿而认为写作链契约完好。

## spec 状态标记证据要求（#1184a）

**spec 中任何 `✅ 已实现` 标记必须附可验证证据**，形式为以下之一：

- 测试名（`test_x.py::test_y`）
- PR 编号
- 断言位置（`文件:行号`）

无证据的 `✅ 已实现` 视为**待验证**，代码评审时必须要求补证或降级为 `⏳ 待补`。

> 背景：审计发现 `specs/f44-book-orchestrator/spec.md` 的 F6 上下文注入链与 F39 能力白名单
> 标 `✅ 已实现` 而源码零实现/未装配（#1175/#1181），同类另见 `specs/f6-context/spec.md` §11、
> `specs/f3-writing/spec.md` §11。上述 4 处已随 W1/W2 实现修复并于 #1184b（2026-09-16）补齐
> 可验证证据后闭环；本节证据要求自 #1184a 起对**所有新增/修改的 spec** 长期生效。
> 已知存量缺口（f19/f20/f23/f33 共 7 行历史无证据标记）另立 issue 跟踪，不在 #1184b 范围。

## 改表 PR checklist（机械引用）

改 `registry.py` 的表内容时：

1. 对照本清单**逐行**检查上表断言面是否需同步修改；
2. 若新增/改名/删工具 → 同步 `i18n/functions/{zh,en}.json` 的 `tool.<name>` 键
   （`test_tool_i18n_parity.py` 双向 bijection 会红）；
3. 若工具集变化 → 复核 `ci.yml` 的 `e2e` / `contract` filter 是否需追加文件；
4. 新增「被 e2e 硬编码锁定的契约源」→ 在 `ci.yml` 的 `contract` filter 追加 + 在本文件登记。

## 范围裁定

- 不改 CI 分层触发哲学（`dorny/paths-filter` 保留，#82/#142 设计有效）。
- 只补「契约源 ↔ 快照断言」联保缺口。
- main 定时全量 e2e（nightly）为**后续候选**，本单不做（#993 任务项 b 留设计）。
