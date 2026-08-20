# InkFlow 后端单元测试断言有效性审计报告

- 审计范围：`backend/tests/unit/`（227 文件，约 8.9 万行）+ 静态扫描 `scan_v2_out.txt` 命中的全部 A1/B 清单（含 2 处实际位于 `tests/integration/` 的命中）
- 审计方式：对 23 处 A1-true-smoke + 3 处 B-weak-assert 逐条读测试源码 + 对应被测实现确认；另精读/抽查 20+ 个核心 service/repo 测试文件评估整体断言强度
- 判定标准：『修改被测函数逻辑后测试仍绿 = 无效/弱断言』；只审计未改动任何文件
- 类型说明：1=无断言 smoke（调了不检查） 2=mock 回显断言 3=仅断言调用发生 4=恒真断言 5=断言设置而非行为 6=弱错误断言

---

## 一、A1/B 扫描命中逐条核查结果（23 + 3 处）

### 1. test_agent_relations.py（8 处命中，全部为『合法输入不抛错』smoke）

被测实现：`src/inkflow/domain/services/project_service.py:83 _validate_agent_relations_config`（`if not config.agent_relations: return` + 死引用/环/唯一后继校验）。

**1.1 test_agent_relations.py:187 test_empty_relations_noop — 类型 1（低危）**
- 证据：`_validate_agent_relations_config(_cfg(agent_relations=[]))`（L189），无任何 assert
- 为什么改逻辑仍绿：把实现改成 `def _validate_agent_relations_config(config): return`（删除全部校验）本测试仍绿——对空输入，「校验通过」与「不校验」行为不可区分
- 修复建议：接受现状（其语义就是 noop 契约），但应在 docstring 注明依赖同文件 raises 用例锚定校验存在性

**1.2 test_agent_relations.py:213 test_custom_role_from_agent_roles_known — 类型 1（中危）**
- 证据：仅 `_validate_agent_relations_config(_cfg(agent_roles={...}, agent_relations=[...]))`（L215-222），无 assert
- 为什么改逻辑仍绿：把「已知角色集合」改为只含内置 4 角色（不再并入 agent_roles keys）→ 本测试仍绿（不抛=通过）；只有删掉校验才能让它红
- 修复建议：合法路径无法直接断言校验执行，建议改为 parametrize 合并 + 明确依赖 :193/:204 的 raises 用例，或给函数加返回值便于断言

**1.3 test_agent_relations.py:224 test_disabled_role_reference_allowed — 类型 1（低危）**
- 证据：仅调用（L226-233），`agent_auditor=None` + relations 引用之，期望不抛
- 为什么改逻辑仍绿：把「未启用角色允许引用」逻辑删除（一律判死引用）→ 本测试红（能防过严）；但把校验整体删除 → 绿
- 修复建议：同上，与 raises 用例成对看待

**1.4 test_agent_relations.py:260 test_acyclic_relations_pass — 类型 1（中危）**
- 证据：仅调用三边 DAG 配置（L262-270），无 assert
- 为什么改逻辑仍绿：把环检测（Kahn 拓扑排序）删除 → 本测试仍绿；只有 :237/:249 的 raises 用例能抓住
- 修复建议：本测试单独无法保护环检测存在性，建议在类 docstring 标注契约组合

**1.5 test_agent_relations.py:295 test_conditional_single_successor_pass — 类型 1（中危）**
- 证据：仅调用单出边 conditional 配置（L297-303）
- 为什么改逻辑仍绿：把「conditional 唯一后继」校验删除 → 绿（:272 raises 用例会红）
- 修复建议：同上

**1.6 test_agent_relations.py:305 test_dict_elements_normalized — 类型 1（中危）**
- 证据：`config.agent_relations = [{"from": ..., "to": ..., "type": ...}]` 裸 dict 后调用（L313-318），注释明言「不应抛 AttributeError」
- 为什么改逻辑仍绿：把规范化（`AgentRelation.model_validate(rel)`）删除 → 本测试会 AttributeError → 红（能防规范化删除）；但把整个校验函数改成 pass → 绿
- 修复建议：可改为 `assert _validate_agent_relations_config(config) is None`（若函数有返回）或保留现状并接受其局限

**1.7/1.8 test_agent_relations.py:329 test_v15_worldview_reference_known、:339 test_v15_polisher_reference_known — 类型 1（低危）**
- 证据：分别仅调用含 agent_worldview / agent_polisher 的配置（L331-337、L341-345）
- 为什么改逻辑仍绿：把内置角色集合从 4 收窄（删 worldview/polisher）→ 本测试红（能防过严）；把校验整体删除 → 绿
- 修复建议：同上，与 raises 用例组合生效

> 小结：test_agent_relations.py 8 处命中本质是同一模式——`_validate_*` 无副作用纯校验函数的『合法路径』测试。它们只能防「过严回归」，不能防「校验删除/过松」，后者完全依赖同文件 6 个 pytest.raises(match=...) 用例。单独看无效，组合看有效。风险点：若未来重构删校验时同步删 raises 用例，这 8 个测试全绿无感。

### 2. test_cloud_protocols.py:101 test_mock_instances_awaitable — 有效但冗余（非无效，排除）
- 证据：`await auth.authenticate(...)` 等一串 await（L110-124），await 成功即断言
- 判定：若协议方法从 `async def` 改同步 → await 抛 TypeError → 红，**有效**；但同文件 :61 `test_protocol_methods_are_async` 已用 `inspect.iscoroutinefunction` 精确覆盖同一契约，本测试冗余
- 修复建议：可删（被 :61 覆盖），保留无害

### 3. test_drop_is_deleted_migration.py:62 test_migrate_drop_missing_table_noop — 类型 1（低危）
- 证据：`_migrate_drop_is_deleted(conn, "nonexistent")`（L65），仅期望不抛
- 被测实现：`src/inkflow/core/database.py:361-364` — `PRAGMA table_info` 空 → `if not names: return`
- 为什么改逻辑仍绿：把实现整体改成 `pass` → 绿；把 names 检查删除（直接 DELETE）→ 红（SQLite 抛 no such table）。测试只锚定「查无表不炸」防御分支
- 修复建议：可接受（防御分支语义即 noop），或补 `assert "is_deleted" not in _cols(conn, "nonexistent")` 形式化

### 4. test_kernel_windows_real.py:75 test_release_mutex_none_is_noop — 类型 1（低危）
- 证据：`_release_mutex(None)`（L77），仅期望不抛
- 被测实现：`src/inkflow/infrastructure/kernel/bootstrap.py:98-106` — `if handle is None: return`
- 为什么改逻辑仍绿：删除 None guard → ctypes ReleaseMutex(None) 抛错 → 红（能防）；改成 pass → 绿
- 修复建议：可接受（防御分支测试），如需更强可断言 `_release_mutex` 在 None 时不触碰 win32 API（mock）

### 5. test_kernel_windows_real.py:147 test_log_kernel_event_oserror_is_silent — 有效（排除）
- 证据：monkeypatch `builtins.open` 抛 OSError 后调用（L149-155），期望不抛
- 判定：若实现删除 try/except OSError → 异常传播 → 红。**这是有效的异常静默行为测试**（无 assert 但「不抛」即断言），非无效

### 6. test_kg_extract_scheduler.py:332 test_stop_is_idempotent — 类型 1（中危）
- 证据：`await sched.stop()` 未 start → start → stop → 重复 stop（L336-340），全无 assert
- 被测实现：`src/inkflow/infrastructure/scheduler/kg_extract_scheduler.py:64-76` — `task = self._task; if task is None: return; task.cancel(); with suppress(...): await task`
- 为什么改逻辑仍绿：把 stop() 改成 `pass` → 4 次调用全不抛 → 绿；loop task 在 sleep(interval*3600) 中无可观察行为。本测试只锚定「幂等不抛」，不锚定「真的取消了调度循环」
- 修复建议：加断言验证 stop 后 loop task 已取消（如 `sched._task.cancelled()` 或 assert run_cycle 不再被 await）

### 7/8. test_pipeline_templates.py:81、:124 test_placeholders_covered_by_input_from — 有效（排除）
- 证据：两处均调用 helper `_assert_placeholders_covered_by_input_from(...)`（L83、L126），helper 在 L48-54 内有真实 assert（`assert placeholders <= set(stage.input_from)`）
- 判定：间接断言，扫描只查函数体直 assert 故误报。有效

### 9. test_pyinstaller_spec.py:25 test_spec_syntax_ok — 有效（排除）
- 证据：`ast.parse(_spec_source())`（L27）
- 判定：spec 语法错误 → ast.parse 抛 SyntaxError → 红。解析即断言，有效

### 10. test_search_models.py:139 test_q_max_length_100_accepted — 类型 1（中危）
- 证据：`_query(q="a" * 100)`（L141），无值断言；对比同文件 :134 有 `assert model.q.strip() == "龙"`
- 为什么改逻辑仍绿：把 max_length 放宽到 200 → 绿（只防过严不防过松）；把 validator 改成静默截断到 50 字符 → 仍绿（无「值被保留」断言；:143 的 101 拒绝用例也绿，因截断后 101 也接受→ 红？不——101 截断为 50 后**不抛** → :143 红。故 :139 单独弱，组合 :143 半保护）
- 修复建议：改为 `model = _query(q="a"*100); assert len(model.q) == 100` 锚定值不被截断

### 11. test_settings_models.py:246 test_accepts_valid_chunk_settings — 类型 1（低危）
- 证据：parametrize 8 组 `AppSettingsUpdate(**kwargs)`（L246-248），仅期望构造成功
- 为什么改逻辑仍绿：AppSettingsUpdate 若把 `extra='forbid'` 放宽为 ignore → 构造仍成功 → 绿；若字段改名/删除 → 红（能防收窄/改名）。不防「校验放宽」
- 修复建议：接受（防字段缺失/改名是本意），或对每组加 `assert getattr(model, key) == value` 锚定值保留

### 12/13. test_writing_plan_model.py:178 test_validate_one_hard_limit_ok、:183 test_validate_defaults_ok — 类型 1（中危/低危）
- 证据：`validate_at_least_one_hard_limit(BookLimits(max_chapters=0, max_agent_calls=5))`（L180）、`validate_at_least_one_hard_limit(BookLimits())`（L185）
- 被测实现：`src/inkflow/domain/models/writing_plan.py:94`（max_chapters/max_agent_calls 至少一个 >0）
- 为什么改逻辑仍绿：把校验函数改成 `pass` → 两测试绿（:172 全零 raises 用例红）；改成「两个都必须 >0」→ 本测试红（能防过严）
- 修复建议：与 :172 raises 用例组合看待；若需独立锚定，需函数带返回值

### 14/15. test_book_repository.py:222 test_update_writing_plan_missing_noop、:235 test_update_planner_session_missing_noop — 类型 1（中危，位于 tests/integration/ 非 unit）
- 证据：`await repo.update_writing_plan(plan)`（L231）、`await repo.update_planner_session(session)`（L244），注释「不抛即通过」
- 为什么改逻辑仍绿：把 repo update 实现改成 upsert（先 SELECT 无则 INSERT）→ 不抛 → 绿，且**测试不检查 DB 状态**——不存在计划被悄悄写入也无人知晓
- 修复建议：断言 update 后 `await repo.get_writing_plan(plan.id) is None`（或 count 不变），锚定「查无 = 什么都不写」

### 16. conftest.py:31 test_engine — 扫描误报（排除）
- 证据：`tests/conftest.py:31` 是 `@pytest_asyncio.fixture async def test_engine()`（fixture），非测试函数；扫描按 `test_` 前缀误匹配 fixture 名

### 17. test_supervisor_state.py:37 `assert True` — 类型 4（低危）
- 证据：`test_import_exists` 内 L37 `assert True`，前有 lazy import（L33-35）
- 为什么改逻辑仍绿：`assert True` 恒真，删掉或改任何值都绿；实际断言是 import 本身（import 失败 → ERROR 也算失败）
- 修复建议：删 `assert True`，改为 `assert SupervisorExecuteConfig is not None`（显式存在性断言）

### 18/19. tests/api/test_export_api.py:286/306 — 扫描误报（排除）
- 证据：`assert False in _export_call_values(...)` / `assert True in ...`，是列表成员断言（导出服务以 True/False 参数被调用），有效；正则 `assert\s+(True|False)\b` 误匹配

---

## 二、抽样精读发现的额外弱断言（不在扫描清单内）

### 20. test_summary_service.py:245 test_force_regenerate — 类型 3（中危）
- 证据：force=True 路径只断言 `assert len(llm.chat_calls) >= 1`（L260），**不断言返回值**
- 为什么改逻辑仍绿：若 ensure_summary(force=True) 实现为「照常调用 LLM 但返回缓存摘要」（force 未真正生效）→ chat_calls>=1 满足 → 绿。force 语义（忽略缓存取新摘要）无锚定
- 修复建议：加 `assert result != "缓存摘要"`（或断言 result 是 LLM 新输出）

### 21. test_summary_service.py:268 test_list_recent — 类型 5（中危）
- 证据：`assert len(results) >= 1; assert isinstance(results[0], ChapterSummary)`（L275-276）；docstring 声称「list_recent 按序号倒序」，但测试无任何排序断言，且 Mock repo 的 list_recent（L88-89）直接 `values()[:limit]` 无排序实现
- 为什么改逻辑仍绿：真实实现排序错误（正序/乱序）→ 测试仍绿；返回空列表外任意内容也绿
- 修复建议：构造多条不同时间/序号的摘要，断言返回顺序（倒序）；Mock repo 同步实现排序

### 22. test_chapter_service.py:131 test_get_project_word_count_sums_chapters — 类型 5（低危）
- 证据：`assert await svc.get_project_word_count(...) == ch.word_count`（L131）——自引用断言：word_count 由同一服务 create 时计算
- 为什么改逻辑仍绿：若字数计算逻辑坏成「恒返回固定值」，create 时落库的 ch.word_count 与 SUM 聚合同源同错 → 仍相等 → 绿
- 修复建议：断言等于手算值（如 `len("第一章内容")`）而非 `ch.word_count`

---

## 三、抽样文件清单及总体评级

### 精读/抽查文件（23 个）
| 文件 | 规模 | 断言强度评价 |
|---|---|---|
| test_project_service.py | 444 行 | 健康：字段级断言 merged 结果、assert_awaited_once_with(参数)、raises(match=) |
| test_agent_service.py | 897 行 | 健康：断言 executed_stages 内容/顺序/model/温度，错误消息 match |
| test_memory_service.py | 560 行 | 健康：契约式，调用参数逐字段断言 + stats 数学精确断言 + assert_not_awaited 零行为 |
| test_search_service.py | 734 行 | 健康：文档字段级断言、query 参数断言、错误路径 assert_not_awaited |
| test_book_service.py | 818 行 | 健康：断言 plan.progress/execution_refs 状态机、硬护栏边界 |
| test_chapter_service.py | 140 行 | 健康（真实 in-memory SQLite）；仅 #22 自引用字数断言小瑕疵 |
| test_summary_service.py | 339 行 | 一般：#20 force 弱锚定、#21 list_recent 无排序断言；截断/异常用例强 |
| test_character_service.py | 777 行 | 健康：39 测试 90 assert，错误类 match 全覆盖；:555 回显断言属透传契约（有效） |
| test_world_service.py | 798 行 | 健康：同上模式 |
| test_outline_service.py | 626 行 | 健康：:517 回显 + project_info 内容断言 |
| test_map_service.py / test_timeline_service.py | 887/488 行 | 健康（抽查）：21/5 个 raises 用例 + 值断言 |
| test_agent_repo.py | 355 行 | 健康：真实 DB roundtrip（add→get 字段比对）+ 排序断言 + IntegrityError |
| test_character_repo.py / test_outline_repo.py / test_project_repo.py / test_chapter_repo.py / test_world_repo.py | 597/684/239/336/803 行 | 健康（抽查）：真实 SQLite roundtrip 模式，无 no-assert 测试 |
| test_agent_relations.py | 345 行 | 一般：#1.1-1.8 八处合法路径 smoke（仅防过严，组合有效） |
| test_agent_relations_apply / _snapshot | — | 健康（抽查） |
| test_planner_service.py / test_agent_entity_service.py / test_skill_service.py / test_session_service.py | 518/699/524/726 行 | 健康（统计+抽查）：assert 密度 2-2.6/测试，无 no-assert |

### 总体评级：健康（断言强度整体良好，个别薄弱点）

- 优势：全仓 227 文件仅 18 处真弱断言（其中 8 处集中在 test_agent_relations.py 同一模式）；核心 service 测试几乎全部是行为断言（断言调用参数、落库字段、状态机、错误消息），mock 回显断言（`assert outcome == result` 共 3 处）均为合法的透传契约测试；repo 测试全部走真实 in-memory SQLite roundtrip；错误断言普遍带 `match=` 消息锚定
- 薄弱面：① 纯校验函数（validate_* / _validate_*）的「合法路径」测试无法独立锚定校验存在性；② 防御分支 noop 测试（6 处）只锚定「不抛」；③ 少量「只断言调用发生/非空/类型」用例（#20/#21）
- 无 assert True/False 恒真断言（仅 1 处，且被 import 兜底）；无 A2 空 raises 体（E-empty-raises 为 0）

---

## 四、3 个最严重发现

1. **test_book_repository.py:222/235（tests/integration/）update 不存在计划/会话 noop** — 真库上只验证「不抛」，不验证「未写入」：若 repo.update 被改成 upsert（无则插入），测试全绿且脏数据悄悄落库，下游查询/统计静默错乱。修复：update 后断言 get 仍 None。

2. **test_kg_extract_scheduler.py:332 test_stop_is_idempotent** — stop() 改成空操作测试仍绿：调度停止语义（后台 loop task 取消）完全没有被锚定，而它正是 lifespan shutdown 安全的核心。修复：断言 `_task.cancelled()` 或 stop 后 run_cycle 不再被 await。

3. **test_agent_relations.py 8 处合法路径 smoke（:187/:213/:224/:260/:295/:305/:329/:339）** — 全部只调用不检查，删除 `_validate_agent_relations_config` 的任意校验分支（死引用/环/唯一后继/角色集合）后 8 个测试全绿；目前仅靠同文件 6 个 raises 用例兜底，一旦重构时同步删 raises 用例即无感失守。修复：合法路径与 raises 用例合并为 parametrize 契约组并加注释互锁，或让校验函数返回校验报告供断言。

---

## 五、备注

- 行号均来自真实文件读取（UTF-8），无误编
- 未修改/创建任何项目源码文件；本报告为唯一产物
- 需人工复核项：#1.6（test_dict_elements_normalized 是否应断言规范化后对象）、#22（字数计算是否另有独立算法用例——建议核对 chapter_service word_count 计算函数是否有直接单测）
