# 证据归档（Evidence Archive）

> 本目录存放**被 ADR / spec / 源码注释 / 测试 docstring 引用**的历史证据文件。
> 这些文件原本散落在 `.hermes/` 与 `.tmp/`（**未入库、随时可能被清理**），导致全仓出现大量悬空引用。
> 归档原则见文末「维护纪律」。

## 已归档

| 文件 | 原位置 | 引用方 |
|---|---|---|
| `audit-writing-chain-2026-09-15.md` | `.hermes/audit-writing-chain-20260915.md` | `backend/src/inkflow/domain/services/chapter_brief.py`、`test_book_service_brief_injection.py`、`test_book_agentic_audit_contract.py`、`test_book_pipeline_brief_injection.py` 等 |
| `contract-929-llm-failfast.md` | `.hermes/plans/contract-929.md` | `adr/llm/ADR-049.md`、`test_book_run_929.py`、`test_llm_resolver_929.py` 等 |
| `contract-975-976-980-writing-pane.md` | `.hermes/plans/contract-975-976-980-writing-pane.md` | `test_book_service.py`、`test_book_pipeline.py` |
| `red-contract-writer-factory-authorization.py` | `.hermes/pending-w2/tests/api/…` | `tests/api/test_writer_factory_authorization.py` |

## ⚠️ 已知悬空引用（原件已丢失）

全仓另有 **31 处**注释/文档引用的 `.hermes/` 或 `.tmp/` 路径，其**原件已不存在**（早前轮次清理时丢失，`.hermes/` 是 gitignored 所以无历史可追）。

典型如：

| 被引路径 | 引用方（示例） |
|---|---|
| `.hermes/plans/contract-902.md` | `usage_accounting.py`、`test_book_usage_902.py` 等 5 处 |
| `.hermes/plans/f44-stage3/4-contract.md` | `book_pipeline.py`、`test_book_service_stage4*.py` 等 11 处 |
| `.hermes/plans/task-618-contract.md` | `preference_supersede_errors.py`、`test_memory_supersede_wiring.py` 等 4 处 |
| `.hermes/plans/w9d3-design.md` | `test_character_repo.py`、`test_merge_character_relations_migration.py` 等 4 处 |
| `.hermes/tmp_repro_c.py` | `adr/llm/ADR-049.md`、`test_llm_resolver_929.py`、`test_empty_string_guard_929.py` |
| `.hermes/logs/inventory_pk.py`、`.hermes/plans/1134-design.md` | `adr/architecture/ADR-060.md` |
| 其余 20+ 处 | 见 `git grep -n "\.hermes/\|\.tmp/"` |

**这些引用不修**：指向的文件本就不存在，改注释不解决任何问题；且分散在 `backend/src` 与 `tests/`，
改动面大、语义可疑（历史注释记录了「当时的依据是什么」，保留原样反而更诚实）。

**若需追溯这些契约的内容**：优先查对应 issue（如 `contract-902` → `#902`）与 ADR。

## 维护纪律

🔴 **新写 ADR / spec / 源码注释 / 测试 docstring 时，不要引用 `.hermes/` 或 `.tmp/` 下的路径。**

- `.hermes/` / `.tmp/` 是 **gitignored 的工作区草稿目录**，不随仓库分发、**其他协作者拿不到**、且会被清理。
- 需要长期引用的证据 → 放 **`docs/evidence/`**（本目录）并在此登记。
- 临时探针/契约 → 引用对应 **GitHub issue**（`#NNN`）或 **ADR**，而不是本地文件路径。

这条纪律的由来：此前大量 RED 契约与审计汇总写在 `.hermes/plans/`，清理后全仓留下 **37 处引用、其中 31 处悬空**。
