## Phase 2：三层补测（PR-2）

> **Part of #104**（三阶段多 PR 的第二阶段；`Closes` 留给最终 PR）

### 变更内容

**前端薄弱点补测（行 95.37% → 99.11%，分支 87.5% → 92.51%，已超目标 99/90）**
- `frontend/packages/renderer/src/api/client.test.ts`（新建，14 用例）：apiFetch 网络失败/401/非 JSON 错误体/detail 对象/FormData/无 token、errorMessage 三分支、getApiConfig
- `frontend/packages/renderer/src/api/sse.test.ts`（新建，12 用例）：SSE 状态机全分支——delta/done/error 帧、非 ok、无 body、流中断无 done、分块到达、多帧一包、abort、JSON parse 异常
- `frontend/packages/renderer/src/theme/index.test.ts`（新建，12 用例）：applyTheme 双写、resolveInitialTheme 四分支、useThemeEffect
- `frontend/packages/renderer/src/components/ProjectTree.test.tsx`（新建，9 用例）：创建章节流程、Esc/取消、空标题回退、无项目 return、卷分组、当前章高亮
- `frontend/packages/renderer/src/stores/agent.test.ts`（追加 +6 用例）：testConnection 非 ok/reject、saveConfig 带 key 先落 key、submitApiKey 清空
- `frontend/packages/renderer/vitest.config.ts`：thresholds 上调至新基线（99.11/92.51/84.54）

**后端 API 端点补测（缺口 5 → 0，docs/api-coverage.md 登记 97 端点 100% 有测试）**
- `tests/api/test_chapter_api.py`（追加 +8 用例）：get_volume/update_volume/delete_volume（各含 404）、list_chapters（volume/status 过滤+分页）、get_chapter（含 404）
- `docs/api-coverage.md`（新建）：97 端点 × 测试覆盖清单（按模块分组 ✅/❌），附录 RAG 文件 coverage 冲突说明

**服务层补测（行覆盖 ≥90% 目标达成）**
- `backend/tests/unit/test_project_service.py`（新建）：update 方法 None 分支 + 合并更新 → project_service 行覆盖 **100%**
- `backend/tests/unit/test_context_service.py`（追加）：assemble 压缩分支 4 场景（压缩成功/压缩不足/异常/无压缩函数）+ _char_count → context_service 行覆盖 **96%**

**E2E 三页流程（新文件 `tests/e2e/electron-pages.spec.ts`，6 用例，真实内核 + 真实渲染）**
1. 项目页：新建项目 → 卡片出现（真实落库）
2. 项目 → 写作页导航（侧边栏往返）
3. 写作页：卷/章渲染 + 选章节 → 编辑器
4. 写作页：工具栏保存（真实 PATCH）
5. Agent 页：链卡片 + 模型接入卡片渲染
6. Agent 页：主题切换 + 链开关交互

### 验证

- 前端：`pnpm --filter renderer test --coverage` → 167 passed / 行 99.11% / 分支 92.51%（thresholds 全绿）
- 后端：`check_coverage.py 91.0 81.0` → 行 91.57% / 分支 81.68% PASS；服务层 project 100% / context 96%
- API 端点：97/97 有测试（docs/api-coverage.md 逐项打勾）
- E2E：`pnpm --filter inkflow-electron test:e2e electron-pages` → 6 passed (30.6s)；全量套件（smoke+pages）需 CI frontend-e2e 验证

### 后续

Phase 3（最终 PR）：CI 阈值上调至目标（后端 99/90 → 需补测后端剩余缺口；前端已达标）；覆盖率报告 artifacts；新增代码门槛常态化。
