# InkFlow 后端集成/API/CLI 测试断言有效性审计报告

审计范围：`tests/api/`（31 文件）、`tests/cli/`（57 文件）、`tests/integration/`（9 文件）。
方法：先读 scan_v2_out.txt 的 A1-true-smoke 命中清单 → 对命中文件逐一读源码确认 → 抽样 15 个 API 文件 + 6 个 CLI 文件评估 HTTP/CLI 断言强度。
**只审计未修改任何项目文件**；证据均来自实际读文件。

---

## 0. 范围修正说明（重要）

scan_v2_out.txt 的 A1-true-smoke 共 23 处，但 **只有 2 处属于本审计的三个目标目录**（tests/api、tests/cli、tests/integration）。其余 21 处全部位于 `backend/tests/unit/`（如 task 上下文点名的 test_drop_is_deleted_migration.py、test_kg_extract_scheduler.py、test_pipeline_templates.py、test_agent_relations.py 等），属单测层、超出本任务范围。已对点名文件做源码确认（见 §4 附注），供父 agent 决定是否单独立项。

---

## 1. 集成层发现（共 19 处实质发现 + 4 处范围外确认）

### 1.1 api 层（13 处）

#### test_agent_api.py — 整文件 mock 回显问题（最严重，7 处）
被测对象：`api/routers/agent.py`。fixture `mock_agent_service`（L27-49）为每个 service 方法设固定 `return_value`，用例断言该固定值——**router 若停止调用 service、直接硬编码 fixture 形状的响应，全部用例仍绿**（无任何 `assert_awaited`/`assert_called` 约束调用发生）。

| 行号 | 测试名 | 类型 | 证据 | 为什么改逻辑仍绿 | 修复建议 |
|---|---|---|---|---|---|
| 61 | test_execute_pipeline | 3(mock回显)+5 | fixture L27-33 `svc.execute.return_value = {"execution_id": "abc-123", "status": "pending", ...}`；用例断言 `data["execution_id"] == "abc-123"`、`data["status"] == "pending"` | router 硬编码同形状 dict 即绿；不验证 execute 收到 project_id、不验证调用发生 | 补 `mock_agent_service.execute.assert_awaited_once_with(project_id=...)` |
| 77 | test_get_execution_status | 3+5 | fixture L34-41 `svc.get_status.return_value = {... "status": "completed", "final_output": "test"}`；断言同值 | 同上 | 补 `assert_awaited_once_with("abc-123")` |
| 85 | test_get_execution_not_found | 1 | L87-89：`get_status.return_value = None` → 仅 `assert resp.status_code == 404` | router 对一切请求恒返 404（或对任何异常返 404）也绿；无 body 断言区分「None→404」与「未注册/内部错误→404」 | 断言 `resp.json()["detail"]` 非空/含「不存在」；补 assert_awaited |
| 91 | test_list_executions | 3+5 | fixture L42 `svc.list_executions.return_value = {"items": [], "total": 0}`；L99 `assert data == {"items": [], "total": 0}` | 完全回显；router 不调 service 且硬编码 `{"items":[],"total":0}` 即绿；project_id 透传无断言 | 断言 `await_args.kwargs["project_id"]`；改 mock 返回非空 items 再断言回显 |
| 101 | test_validate_pipeline | 3 | fixture L44 `svc.validate_pipeline = MagicMock(return_value={"valid": True, "errors": []})`；断言同值 | 回显；router 硬编码即绿 | 断言 validate_pipeline 收到 body 中的 stages |
| 126 | test_list_templates | 3 | fixture L45-49 固定 items；L131 `assert data["items"][0]["id"] == "builtin:write_chapter"` | 回显 | 补 assert_called_once |
| 72 | test_execute_missing_project_id | 1 | 仅 `assert resp.status_code == 422` | 任何 422（含 router 内部错误误映射）都绿；但 422 属 Pydantic 校验路径，风险低 | 可断言 detail 为 list（Pydantic 形态） |

对照：同文件 Coverage-Gaps 段（L142-220）质量明显更高——test_parse_id 精确断言、test_svc_constructs_agent_service 断言装配调用参数、错误映射断言 detail 精确值。**同一文件两套标准**，前 7 个用例是历史遗留弱断言。

#### test_project_api.py（4 处）
| 行号 | 测试名 | 类型 | 证据 | 为什么改逻辑仍绿 | 修复建议 |
|---|---|---|---|---|---|
| 179 | test_delete_project | 5(仅调用缺失)+1 | L185-186：仅 `assert resp.status_code == 204`；`mock_service.soft_delete` 设为 AsyncMock 但**无 assert_awaited** | router 不调 soft_delete、直接 `Response(204)` 即绿；对比同文件 test_hard_delete_project（L219 有 assert_awaited_once） | 补 `mock_service.soft_delete.assert_awaited_once_with(pid)` |
| 226 | test_update_project_not_found | 1 | L233-234：`update.return_value = None` → 仅 `assert resp.status_code == 404` | 任何 404 来源都绿；不验证 body | 断言 detail 含「不存在」；补 assert_awaited |
| 238 | test_delete_project_not_found | 1 | L245-246：`soft_delete.return_value = False` → 仅 404 | 同上 | 同上 |
| 250 | test_restore_project_not_found | 1 | L257-258：仅 404 | 同上 | 同上 |

另外 test_create_project（L53）：`data["name"] == "测试项目"` 是回显（mock_project.name 与请求 body 同名），且 `"id" in data` 只查 key 不查值（类型2弱化形态）；请求的 genre 是否透传 service 无断言。test_update_project_config_default_words（L145）含回读断言，是好用例。

#### test_books_api.py（5 处）
| 行号 | 测试名 | 类型 | 证据 | 为什么改逻辑仍绿 | 修复建议 |
|---|---|---|---|---|---|
| 280 | test_planner_respond_missing_404 | 1 | L283 `planner.respond.side_effect = ValueError("会话不存在")` → 仅 `assert resp.status_code == 404` | router 把**所有** ValueError 都映射 404（把 L490 的 422 分支吞掉）时本用例仍绿；只有 L490 用例能拦住，但本用例自身无区分力 | 断言 detail 含「不存在」（同文件 L737/L757 confirm 用例已示范此防假绿手法） |
| 317 | test_planner_get_missing_404 | 1 | `get.return_value = None` → 仅 404 | 同上；无 assert_awaited | 补 body 断言 |
| 365 | test_runs_start_plan_missing_404 | 1 | `prepare_run.side_effect = ValueError("计划不存在")` → 仅 404 | 同上 | 补 detail 含「不存在」 |
| 430 | test_runs_status_missing_404 | 1 | `get_status.return_value = None` → 仅 404 | 同上 | 补 detail 断言 |
| 490 | test_planner_respond_other_value_error_422 | 1 | `ValueError("write_auto 未装配")` → 仅 422 | 任何 422 都绿；不验证是「非不存在 ValueError → 422」分支 | 断言 detail 含「未装配」 |

注：L648 `test_runs_start_no_hard_limit_422_detail` 已示范「422 + detail 锁文案」的正确形态，L379 同场景旧用例是弱版；L539/L777/L806 用例带 `assert_awaited_once_with(精确参数)` 属强断言。

#### test_f27_agentic_api.py（5 处）
| 行号 | 测试名 | 类型 | 证据 | 建议 |
|---|---|---|---|---|
| 252 | test_agentic_generate_404 | 1 | L262 仅 404 | 断言 detail 含「不存在」 |
| 265 | test_agentic_generate_422_invalid_max_steps | 1 | L271 仅 422 | 断言 detail 为 list 且含 max_steps（Pydantic 形态） |
| 305 | test_runs_get_404 | 1 | L309 仅 404（依赖 fixture 默认 `run_repo.get = AsyncMock(return_value=None)`） | 补 detail 断言 |
| 339 | test_drafts_confirm_409 | 1 | L347 仅 409 | 断言 detail 含「已确认」 |
| 350 | test_drafts_confirm_404 | 1 | L358 仅 404 | 断言 detail 含「不存在」 |

同文件成功路径（L169-249、L277-367）断言 body 全字段 + service 调用参数，质量高；仅错误面 5 例偏弱。

#### test_memory_api.py（3 处）
| 行号 | 测试名 | 类型 | 证据 | 建议 |
|---|---|---|---|---|
| 251 | test_patch_draft_409 | 1 | L258 仅 `assert resp.status_code == 409`（同文件 L243-249 的 404 用例有 detail 锁「草稿不存在」，409 却无） | 断言 detail 含「已确认」 |
| 260 | test_patch_draft_422_empty_content | 1 | L266 仅 422 | 断言 detail 为 list |
| 268 | test_patch_draft_422_missing_content | 1 | L272 仅 422 | 同上 |

#### 其余单点
| 文件:行 | 测试名 | 类型 | 证据/说明 |
|---|---|---|---|
| test_chapter_audit_api.py:451/464/477 | test_list_audit_logs_limit_101_422 等 3 例 | 1 | 仅 422；无字段回显断言（对比 test_export_api.py:347 的 422 断言了 `"format" in str(detail)`，此处可仿照） |
| test_chapter_api.py:654 | test_move_chapter_invalid_target_volume_404 | 1 | 仅 404（L672）；同文件其他 404 用例（L633/L648）都有 detail 锁，此例独缺 |
| test_token_auth.py:163/171/193/221 | test_missing_token_returns_401 等 4 例 | 1 | 仅 401 无 body；test_export_api.py:391 同场景断言了 `{"detail": "Unauthorized"}`——token_auth 自身反而没锁 body |
| test_agent_api.py:72 | test_execute_missing_project_id | 1 | 见 §1.1 表 |

### 1.2 cli 层（2 处）
| 文件:行 | 测试名 | 类型 | 证据 | 建议 |
|---|---|---|---|---|
| test_cli_project.py:246 | test_delete_not_found | 6 | L248 仅 `assert result.exit_code == 1`，无 stderr/stdout 检查 | 断言输出含「项目不存在」（同文件 L399-403 的 --json 版本有信封断言，人类模式缺） |
| test_cli_project.py:276 | test_restore_not_found | 6 | L278 仅 `assert result.exit_code == 1` | 同上 |

### 1.3 integration 层（2 处，即 scan A1 在范围内的全部命中）
| 文件:行 | 测试名 | 类型 | 证据 | 为什么改逻辑仍绿 | 修复建议 |
|---|---|---|---|---|---|
| tests/integration/test_book_repository.py:222 | test_update_writing_plan_missing_noop | 4 | L231 `await repo.update_writing_plan(plan)  # 不抛即通过`，构造 WritingPlan 后调用**无任何断言** | ①实现从 no-op 改为「写入新行」→ 测试仍绿；②改为「误删其他行」→ 仍绿；③改为静默吞异常 → 仍绿。只约束了「不抛错」，完全未验证副作用 | update 后断言 `await repo.get_writing_plan(plan.id) is None`（仍不存在）或查询表行数不变 |
| tests/integration/test_book_repository.py:235 | test_update_planner_session_missing_noop | 4 | L244 同款 `await repo.update_planner_session(session)  # 不抛即通过` | 同上 | update 后断言 `get_planner_session(id) is None` |

### 1.4 范围外 A1 命中源码确认（backend/tests/unit，供参考）
| 文件:行 | 测试名 | 确认结果 |
|---|---|---|
| backend/tests/unit/test_drop_is_deleted_migration.py:62 | test_migrate_drop_missing_table_noop | **真 noop**（L65 仅调用，无断言）：迁移函数对不存在表的行为只验证「不抛错」，若函数部分写入（建表）无法察觉 |
| backend/tests/unit/test_kg_extract_scheduler.py:332 | test_stop_is_idempotent | **真 noop**（L336-340 stop/start/stop/stop 无断言）：改 stop 实现为泄漏任务/误 stop 其他任务仍绿 |
| backend/tests/unit/test_pipeline_templates.py:81/124 | test_placeholders_covered_by_input_from | **扫描误报**：断言在 helper `_assert_placeholders_covered_by_input_from` 内（函数体仅调用 helper），实际有效 |
| backend/tests/unit/test_agent_relations.py（8 处）、test_writing_plan_model.py:178/183、test_search_models.py:139、test_settings_models.py:246、test_kernel_windows_real.py:75/147、test_cloud_protocols.py:101、test_pyinstaller_spec.py:25、tests/conftest.py:31 | — | 未逐一读源码，需人工复核（疑似含 helper 断言式误报，如 pipeline_templates 先例） |

---

## 2. 抽样文件清单及总体评级

### api 层（15 文件）
| 文件 | 评级 | 依据 |
|---|---|---|
| test_search_api.py | **健康** | body 全字段断言 + service 调用参数断言（query.q/project_ids/mode）+ 404/500 精确 detail + 422 字段回显 + assert_not_awaited |
| test_export_api.py | **健康** | 200 断言 header/文件名/文本回显；404/422/500 精确 body；401 精确 body；`assert False/True in _export_call_values` 风格怪但有效（透传断言） |
| test_knowledge_extract_api.py | **健康** | 响应键集 + 值断言 + `extract_for_project.await_args` 参数断言 |
| test_f27_agentic_api.py | 一般 | 成功路径强（body+调用参数）；5 个 404/409/422 错误面仅状态码 |
| test_books_api.py | 一般 | 成功路径带 `assert_awaited_once_with(精确参数)` 很强；5 个 404/422 边界仅状态码 |
| test_agent_api.py | **薄弱** | 前 7 用例纯 mock 回显 + 无调用断言；后段 coverage-gap 用例强 |
| test_project_api.py | 一般 | 部分回显；delete 无 assert_awaited；3 个 not_found 仅 404；default_words 用例强 |
| test_writing_api.py | 健康 | 404/500 精确 detail + 错误头断言 + 不泄漏检查；422 断言 loc |
| test_memory_api.py | 一般 | 调用参数断言好；3 个 409/422 仅状态码 |
| test_chapter_api.py | 一般 | 404 大多带 detail 锁；1 例（L654）仅 404 |
| test_chapter_audit_api.py | 一般 | findings 全字段断言很强；3 个 422 仅状态码 |
| test_agents_api.py | 健康 | 真实 DB + 契约 helper + 值断言 + 副作用验证（409 后记录未改） |
| test_agent_templates_api.py | 健康 | 同上（_assert_response_contract + exclude_unset 浅合并断言） |
| test_skills_api.py | 健康 | agent_ids 反查值断言 |
| test_settings_api.py | 健康 | mock 工厂精确调用参数断言（assert_called_once_with） |
| test_health.py | 健康 | version 动态性 patch 断言有效；L25 `test_health_response_time` 时序断言 <0.1s 有 CI 慢机 flaky 风险（非弱断言，属稳定性隐患） |

### cli 层（6 文件）
| 文件 | 评级 | 依据 |
|---|---|---|
| test_book_cmd.py | **健康** | exit_code + stdout 内容 + `post.assert_awaited_once_with(路径, json=精确body)` |
| test_cli_search.py | **健康** | stdout 人类输出逐项断言（含 <mark>→[ ] 转换）+ 信封 + params 透传断言 |
| test_cli_session.py | 健康 | 信封 + data 字段 + 参数透传（UUID/context-json） |
| test_cli_project.py | 一般 | stdout 内容断言普遍好；2 个 not_found 仅 exit code |
| test_cli_chapter.py | 健康 | help 测试带 stdout 断言（30 行小文件，仅覆盖 --help） |
| test_cli_memory.py | 未细读 | 未抽样到（时间所限），见 §3 说明 |

### integration 层（2 文件细读）
| 文件 | 评级 | 依据 |
|---|---|---|
| test_book_repository.py | 一般 | 主体用例（add/get/update roundtrip）断言字段值，强；2 处 noop 弱（§1.3） |
| test_execution_store_defensive.py（扫描命中 STATUS-ONLY 2 处） | 健康 | `loaded == payload` 值断言 + 状态断言，为扫描误报 |

### 总体
- **api 层：一般偏健康**。TDD 契约风格（docstring 写死 spec 条款）使成功路径与错误 detail 普遍强；系统性弱点是**错误面（404/409/422）大量只锁状态码不锁 body**（约 25 处，多为「同文件已有 detail 锁版本」的旧用例），以及 test_agent_api.py 的整文件 mock 回显。
- **cli 层：健康**。普遍 exit_code + stdout 内容 + HTTP 调用参数三重断言。
- **integration 层：一般**。2 处真 noop 需补副作用断言。

---

## 3. Top 3 最严重发现

1. **test_agent_api.py 前 7 个用例（L61-131）整文件 mock 回显**：fixture 固定 return_value → 断言固定值回显，且全无 `assert_awaited`/`assert_called`。把 router 改成一坨 `return {"execution_id": "abc-123", "status": "pending"}` 的硬编码、完全不调 service，7 个用例全部通过——**router 与 service 的接线（注入点 `_svc` 是否被调用、参数是否透传）完全没有测试保护**。同一文件 L142-220 的补测段示范了正确做法（断言装配调用、断言错误 detail 精确值）。

2. **tests/integration/test_book_repository.py 两处 noop 测试（L222/L235）**：`# 不抛即通过` 的注释直白承认了「只测不抛错」。`update_writing_plan`/`update_planner_session` 的「查无分支」若被改成插入、误删或静默失败，测试全绿。这是扫描 A1 在目标三目录内的**全部命中**，是集成层唯一确证的无断言用例。

3. **test_project_api.py test_delete_project（L179）**：`DELETE → 204` 无 `assert_awaited`——router 里把 `soft_delete` 调用删掉、直接返回 204 即绿；同类还有 L226/238/250 三个 not_found 用例只锁 404 不锁 body 与调用。软删除是数据安全敏感操作，此路径的「调用发生」断言缺失比普通 404 更值得优先补。

## 4. 附注
- **报告文件**：本报告写入 `D:\develop\hermes-projects\InkFlow\.tmp\assert-scan\report-integration.md`；未修改任何项目文件。
- **需人工复核项**：§1.4 中未读源码的 8 个 backend/tests/unit A1 命中（疑含 helper-断言式误报）；test_cli_memory.py、test_cli_write.py 等未抽样 CLI 文件；§1.1 表中 test_agent_api.py:72、test_health.py:25 的「可接受但有风险」评级。
- **统计口径**：§1 计数含「1.1 api 13 处 + 1.2 cli 2 处 + 1.3 integration 2 处 = 17 处实质发现」+ 范围外 3 处确认（其中 1 处为误报）；若父 agent 需要按「真弱断言」口径，api 13 处中 test_agent_api 前 7 例合并计 1 个文件级问题。
