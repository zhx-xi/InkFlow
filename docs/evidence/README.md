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
| `m6-1494-world-first-open.png` | `.tmp/m6-first-open.png`（本轮生成） | PR #1499（#1494 世界观页首开 · M6 真实内核实证截图：新建项目 → 首开 = 1 个默认根 + 根下引导行） |
| `m6-1465-kg-default.png` 等 4 张 | `.verify-1465/`（本轮生成） | PR（#1465 知识图谱筛选语义与布局四改 · M6 实证：真实 React 渲染 4 态 —— 默认全选/等高、多选过滤随类别、折叠左侧竖条、实体列表内滚；脚本 = Vite dev + `page.route` mock，23 条几何/行为断言 ALL PASS） |
| `m6-1467-world-eras-tree.png` / `m6-1467-world-single-axis.png` | `.tmp/m6/`（本轮生成） | PR（#1467 时间线世界序纪元轴组头 + 时间刻度树状分层 · M6 实证：真实 React 渲染 2 态 —— 多纪元树状泳道（轴名组头一次 + 时间节点 + 缩进事件行）/ 无纪元单轴零变化；脚本 = Vite dev + `page.route` mock） |
| `m6-1526-world-order-time-display.png` | 本轮生成（临时探针目录） | PR（#1526 时间线提取不产出时间表达 · M6 实证：真实 React 渲染世界序 —— 3 条「time_display 非空 + time_value 空」事件显示**原文**（三月初二 / 同年腊月 / 次年开春），仅「两者皆空」事件显示「未知」；脚本 = Vite dev + `page.route` mock，含阴性对照——移掉 `time_display` 分支 → 断言 FAIL） |
| `m6-1529-multiselect-grey.png` / `m6-1529-sort-pagination.png` / `m6-1529-page2.png` | `.hermes/plans/m6/`（本轮生成） | PR #1543（#1529 知识图谱实体多选灰显 + 拼音排序 + 双块分页 · M6 实证：真实 React 渲染 3 态 —— ① 未勾选实体**灰显且节点不摘除**（列表 14、摘要「实体 10/14 · 显示 10 个」，画布上 4 个未勾选节点全灰、其余彩色）；② 实体列表**拼音序**（安平→白泽→赤水→东山→风谷）+ 分页条 `10 ▾ 上一页 1/2 下一页` 单行；③ 翻到 **2/2**、下一页置灰、列表换成拼音序后半（明堂/南岭/青丘/玄武）；脚本 = Vite dev + `page.route` mock（沿用 #1465 同页先例） |
| `m6-1566-default-*.png` 5 张 + `m6-1567-range-*.png` 3 张 | `.hermes/plans/m6/out/`（本轮生成） | PR（#1566 提取弹框默认类型随来源页 + #1567 按章范围块渲染/删除/校验 · M6 实证：真实 React 渲染 8 态 —— ① **5 个分类页**各打开一次弹框，默认单选 = 该页自身类型（角色 / 世界观 / 时间线 / 伏笔 / 知识图谱；同一 `AIExtractEntry` 实例跨分类切换后重开即重置）；② 按章添加 2 段 → 出现 2 个范围块 `第 1–2 章 ×` / `第 3–3 章 ×`；③ 删第 1 块 → 只剩 1 块；④ 非法输入 `9–5`（起 > 止）→ 就地红字提示且不入列；脚本 = Vite dev + `page.route` mock，10 条断言 ALL PASS） |
| `m6-1568-kg-three-state.png` / `m6-1568-kg-cancel-all.png` / `m6-1569-kg-page-size.png` | 本轮生成（Vite dev 直出） | PR（#1568 知识图谱筛选入口名实不符 + 实体定向三态 / #1569 改「显示项」后分页条消失 · M6 实证：真实 React 渲染 3 态，全**真实点击**（不注入记忆）—— ① 点「全部取消」→ 类别与实体全不选：43 节点全灰 + 筛选空态卡片 + 摘要「无 · 实体 0/43 · 显示 0 个实体」+ 记忆落 `{categories:[],entities:[]}`；② 勾回六类 → 翻页勾选 1 个实体 → **三态**：1 彩色 / 2 灰显保位 / 40 隐藏（`data-dim` / `data-hidden`），边只画两端在场者（2 条；两端皆隐藏的 1 条不画）；③ 点「全选」恢复（1/5）→ 改每页条数 **100**（池 43 ≤ 100）→ 分页条**仍在**（含每页条数选择器，info `1 / 1`），可改回；脚本 = Vite dev + `page.route` mock（沿用 #1465/#1529 同页先例），16 条断言 ALL PASS） |

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
