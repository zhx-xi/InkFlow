# 契约源 → 断言面联保清单（#993）

> 目的：登记「全仓哪些测试硬编码了后端契约源的内容快照」，供**改契约源的 PR** 机械复核。
> 起始契约源：`backend/src/inkflow/infrastructure/agent/tools/registry.py`
> （`GRANT_TOOL_MAP` / `TOOL_REGISTRY` / `ALL_TOOL_SPECS` / `TOOL_NAME_TO_CELL`）。
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
