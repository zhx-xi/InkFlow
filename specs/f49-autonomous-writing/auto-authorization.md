# F49.1: 全自动授权与项目级开关（autonomous-authorization）功能规格

**Spec 版本**: 1.0（初稿，2026-08-23）
**日期**: 2026-08-23
**依据**: Issue #598（全自动写一卷/几章 + 首次显式授权 + 项目 config 开关 + 执行详情旁切换按钮）+ 用户拍板 2026-08-23（D9=A 落章前 HITL 确认；D9-a1 首次显式授权 + 开关存项目 config + 执行详情旁切换按钮）+ 既有源码核查（`BookAgenticPipeline` #551 / `AgenticBookConfig.hitl_points` / `ProjectConfig.supervisor` F29 / `VolumeHITLDialog` #337 / chat 系统级 Agent #597）+ 参考规格 `specs/f49-autonomous-writing/spec.md`
**所属阶段**: 0.12.0（AI 全自动写作授权门禁）
**关联 Issues**: [#598](https://github.com/zhx-xi/InkFlow/issues/598)（本模块，Part of #551，Closes #598）· 前置：✅ #551 后端编排核心（BookAgenticPipeline）· ✅ #597 chat 接入系统级 Agent（Part of #551）· ✅ F29 Supervisor HITL · ✅ F44 卷级编排/VolumeHITLDialog
**依赖**: ✅ #551（BookAgenticPipeline + write_book_agentic + AgenticBookConfig）· ✅ #597（chat deepagents 系统级 Agent）· ✅ F29（ProjectConfig.supervisor + hitl_roles interrupt）· ✅ F44（VolumeHITLDialog + confirm_run）
**参考 ADR**: adr/ADR-015（LangChain 隔离）· ADR-035（编排引擎=Deep Agents harness 0.7.5）
**状态**: ✍️ 起草中（本会话 Specify）

> **模块类型声明**: 本模块为 F49 的**授权门禁增量**（非独立变体）。F49 #551 已交付全自动写作**后端编排核心**（book_supervisor 动态路由 + write/audit/revise/mark_done/finish_book + `hitl_points` 白名单 + checkpoint 恢复）。**#598 在其上加「安全授权门禁」**：全自动属高风险动作，须**默认关闭、显式授权**（用户偏好：AI 自动化默认关闭），且写入边界需用户确认（checkpoint）。本 spec 不重做编排，只定义授权数据与 UI 契约。

> **范围声明（本会话）**: 本 v1.0 spec 定义 **#598 授权门禁**（后端 `ProjectConfig` 开关 + agentic 授权检查 + 前端首次授权弹框 + 执行详情旁切换按钮）。编排核心（BookAgenticPipeline）已由 #551 交付，本 spec 只加授权层。

---

## 1. 概述

### 1.1 现状缺口（2026-08-23 源码实证）

| # | 缺口 | 实证 | 归属 |
|---|------|------|------|
| ① | **无「全自动」项目开关**：`ProjectConfig` 只有 `supervisor.hitl_roles`（F29 HITL）与 `agent_*` 模型字段，无「是否全自动」布尔开关 | `domain/models/project.py` `ProjectConfig` | #598 |
| ② | **agentic 无授权检查**：`POST /runs mode=agentic` 直接 `write_book_agentic`，不检查用户是否显式授权全自动 | `books.py` `start_run` + `book_run_mixin.py` `write_book_agentic` | #598 |
| ③ | **前端无全自动开关入口**：写作页「查看 AI 执行详情」按钮（view-toggle）右侧无「是否全自动」切换按钮 | `EditorToolbar.tsx` `view-toggle` | #598 |
| ④ | **首次触发无授权弹框**：第一次触发全自动时无显式授权确认 | 前端无 `AutoAuthorizationDialog` | #598 |
| ⑤ | **agentic 默认无落章 HITL**：`AgenticBookConfig.hitl_points` 默认空（全自动无打断） | `agent_book.py` `AgenticBookConfig.hitl_points` default_factory=list | #598（D9=A 落章前 HITL 确认） |

### 1.2 目标

全自动写作（write_book_agentic / mode=agentic）为**高风险动作**，须：
- **默认关闭、显式授权**：未授权时不自动全自动；首次触发弹授权框（用户偏好）
- **项目级开关**：开关存 `Project.config`（每项目独立，与 supervisor 同层）；「查看 AI 执行详情」按钮右侧新增「是否全自动」切换按钮（D9-a1）
- **落章前 HITL 确认**：全自动执行时每章落库前 interrupt（复用 F29/F49 `hitl_points`），最坏只丢一章（D9=A）

### 1.3 与样板差异

非独立变体——是 F49 #551 的**授权门禁增量**。复用既有编排核心，只加「授权数据模型 + 授权检查 + UI 开关/弹框」。

---

## 2. 数据模型

### 2.1 `ProjectConfig` 加「全自动」开关（`domain/models/project.py` MODIFY）

```python
class ProjectConfig(BaseModel):
    # ... 既有字段 ...
    auto_write_enabled: bool = Field(
        default=False,
        description="项目级「是否全自动」开关（#598 D9-a1）：True=允许全自动写书（mode=agentic）；"
        "False=禁止（默认，AI 自动化默认关闭，首次触发弹授权框）。与 supervisor 同层。",
    )
```

**零迁移**：`ProjectConfig` 是嵌入 `Project.config` JSON 的 pydantic 模型，旧 config JSON 无该键 → 默认 `False`（`populate_by_name` 兼容旧数据）。既有 config roundtrip 测试不受影响（新字段默认值）。

> **载体决策**：与 `supervisor` 同层（`ProjectConfig` 直接字段），**不进 `extra`**——因为 issue 明示「与 supervisor 同层」，且 `extra` 已有 `book_max_*` 上限语义（Q2=C）。`auto_write_enabled` 是**开关**非**上限**，独立字段更清晰、更强类型。

### 2.2 授权语义（首次显式授权）

- **授权载体 = `ProjectConfig.auto_write_enabled` 本身**（True = 已授权/允许全自动）
- **首次触发流程**：前端检测 `currentProject.config.auto_write_enabled == False` 且用户触发全自动（mode=agentic）→ 弹「授权确认」框 → 用户确认 → `PATCH /api/v1/projects/{id}` body `{config: {auto_write_enabled: true}}` 持久化 → **授权后记住**（后续不再弹）
- 用户拒绝 → 不开启开关，不发起全自动运行
- 「执行详情旁切换按钮」= 直接翻转 `auto_write_enabled`（PATCH config），即时持久化，无需弹框（用户主动翻转 = 显式授权）

---

## 3. API 契约

### 3.1 无新增 REST 端点（复用既有）

| 操作 | 端点 | 说明 |
|------|------|------|
| 读取开关 | `GET /api/v1/projects/{id}`（返回 `config`） | 前端读 `config.auto_write_enabled` |
| 写开关 | `PATCH /api/v1/projects/{id}` body `{config: {auto_write_enabled: true/false}}` | 授权/取消授权，`project.ts` `updateConfig` 复用 |
| 启动全自动 | `POST /api/v1/agent/books/runs` body `{writing_plan_id, mode: "agentic", config}` | 后端检查授权 |

### 3.2 agentic 授权检查（后端门禁）

`POST /runs mode=agentic` 启动前，`BookService` / `prepare_run(mode="agentic")` 检查项目 `config.auto_write_enabled`：

- **True** → 放行（`write_book_agentic` 执行，含 `hitl_points`）
- **False** → **拒绝**，返回 403 `{"detail": "全自动写作未授权，请先在执行详情旁开启「是否全自动」开关"}`（或等效文案）

> **反射点**：授权检查放 `prepare_run`（POST /runs 同步预校验，错误立即 4xx），与 F44 既有预校验（计划存在 / 护栏 / 安全阀）同层。`write_book_agentic`（后台任务）本身不重复检查（后台不可回滚），由 `prepare_run` gate。

### 3.3 落章前 HITL（D9=A）

`mode=agentic` 时，`AgenticBookConfig.hitl_points` **默认含 `chapter_done`**（每章 mark_done 前 interrupt，最坏只丢一章）。前端复用 `VolumeHITLDialog`（waiting_hitl 时弹出 approve/reject）。

> **决策**：`chapter_done` 语义 = 「每章落库前确认」。F49 的 `hitl_points` 白名单已支持 `chapter_done`，#598 只需**默认开启**（agentic 启动时若 config 未显式传 hitl_points，则默认 `["chapter_done"]`）。

---

## 4. CLI 命令签名

**无新增**。复用 `inkflow book run <plan_id> --mode agentic`（F49 §4）。CLI 场景（非 GUI）由用户显式 `--mode agentic` 触发，属显式授权语义（CLI 用户主动指定 = 授权），后端 `prepare_run` 检查宽松处理或 CLI 透传授权。

> **边界**：CLI `--mode agentic` 视为显式授权（CLI 是命令行显式操作）。授权门禁主要约束 **GUI 触发**（写作页 AI 对话触发全自动 = 需首次授权弹框）。后端 `prepare_run` 检查以项目 `auto_write_enabled` 为准，但 CLI 可加 `--yes` 跳过（沿用 F7 全局约定）。**本 v1.0 范围 = GUI 授权门禁**，CLI 透传文档化即可。

---

## 5. 前端契约

### 5.1 「是否全自动」切换按钮（D9-a1，`EditorToolbar.tsx` MODIFY + `writing.tsx` MODIFY）

「查看 AI 执行详情」按钮（`view-toggle`）**右侧**新增「是否全自动」切换按钮：

- `aria-label` = `t('write.toolbar.autoToggle')`（如 "是否全自动"）
- `data-testid` = `auto-toggle`
- 状态 = `currentProject.config.auto_write_enabled`（`useProjectStore` 读）
- 点击 → `updateConfig(projectId, { config: { auto_write_enabled: !current } })` 持久化（`project.ts` `updateConfig` 复用）
- 开启态视觉（accent）/ 关闭态（ink-3），`aria-pressed`

### 5.2 首次授权弹框（`AutoAuthorizationDialog.tsx` CREATE）

**触发**：用户发起全自动写作（`mode="agentic"`）时，检测 `config.auto_write_enabled == False`：
- 写作页/书级页点「全自动写书」→ 若未授权 → 弹 `AutoAuthorizationDialog`
- 弹框内容：title + 说明（「全自动写作将自主规划→写作→自查→修订，属高风险动作」）+ 「确认授权」/「取消」按钮
- 确认 → `updateConfig(projectId, {config: {auto_write_enabled: true}})` → 授权后记住 → 继续发起全自动
- 取消 → 关闭，不发起

### 5.3 落章前 HITL（复用 `VolumeHITLDialog`）

全自动运行 `GET /runs/{id}` 返回 `waiting_hitl` + `hitl_payload` → `VolumeHITLDialog` 弹出（复用 F44 阶段3 既有对话框，零新增）。confirm → 继续/跳过。

---

## 6. 文件结构

### 后端（MODIFY）

| 文件 | 变更 |
|------|------|
| `backend/src/inkflow/domain/models/project.py` | `ProjectConfig` 加 `auto_write_enabled: bool = False`（§2.1） |
| `backend/src/inkflow/domain/services/book_run_mixin.py` | `prepare_run` mode=agentic 分支加授权检查（§3.2）；`write_book_agentic` 默认 hitl_points 含 chapter_done（§3.3） |
| `backend/src/inkflow/api/routers/books.py` | `start_run` 授权检查错误映射（403） |
| `backend/tests/unit/test_project_dtos.py`（或新建 test_project_auto.py） | `ProjectConfig.auto_write_enabled` 默认 False + roundtrip 契约 |
| `backend/tests/unit/test_book_agentic_service.py`（已有，追加） | `prepare_run(mode="agentic")` 未授权 → 403/ValueError 契约 |

### 前端（MODIFY / CREATE）

| 文件 | 变更 |
|------|------|
| `frontend/packages/renderer/src/components/EditorToolbar.tsx` | 加「是否全自动」切换按钮（§5.1，view-toggle 右侧） |
| `frontend/packages/renderer/src/pages/writing.tsx` | 传 `autoWriteEnabled` + `onToggleAuto` 给 EditorToolbar（§5.1）；首次授权弹框挂载（§5.2） |
| `frontend/packages/renderer/src/components/AutoAuthorizationDialog.tsx` | CREATE：首次授权弹框（§5.2） |
| `frontend/packages/renderer/src/components/__tests__/AutoAuthorizationDialog.test.tsx` | CREATE：授权弹框契约 |
| `frontend/packages/renderer/src/components/EditorToolbar.test.tsx` | 追加 auto-toggle 契约（§5.1） |
| `frontend/packages/renderer/src/pages/writing.test.tsx` | 追加首次授权弹框触发契约（§5.2） |
| `frontend/packages/renderer/src/i18n/zh.ts` / `en.ts` | `write.toolbar.autoToggle` + 授权弹框文案 |
| `frontend/packages/renderer/src/stores/project.ts` | `ProjectConfig` 加 `auto_write_enabled?: boolean`（§5.1 类型） |

---

## 7. 测试策略

| 层次 | 关键场景 | 目标 |
|------|---------|------|
| 模型 | `ProjectConfig(auto_write_enabled=True)` roundtrip；默认 False；旧 config JSON（无键）→ False | ≥90% |
| 服务 | `prepare_run(mode="agentic")` 未授权（config.auto_write_enabled=False）→ ValueError/拒绝；授权 → 放行 | ≥90% |
| API | `POST /runs mode=agentic` 未授权 → 403；授权 → 202 | ≥90% |
| 前端组件 | auto-toggle 点击 → `updateConfig` 调用 + aria-pressed 翻转；首次授权弹框显示/确认 → 授权 → 发起 | ≥90% |
| 回归 | mode 默认 static 时既有测试全绿（F49/F44 零回归） | 全仓 ≥60% |

**RED 形态**：
- `ProjectConfig.auto_write_enabled` 缺失 → AttributeError
- `prepare_run(mode="agentic")` 未授权不拒绝 → 契约断言失败
- `EditorToolbar` auto-toggle 不存在 → 找不到 testid
- `AutoAuthorizationDialog` 不存在 → ImportError（collection error）

---

## 8. 验收标准（对应 issue #598）

- **M0** spec 定稿合入 worktree
- **M1** RED 批全 FAIL（未授权不自动 / 首次弹框 / 开关持久化 / 落章前 interrupt）
- **M2** GREEN + vitest/tsc 全绿 + 后端 pytest/ruff/mypy
- **M3** PR merged + #598 CLOSED + worktree 清理

---

## 9. 关键架构决策记录

| 决策 | 方案 | 备选（否决理由） |
|------|------|-----------------|
| 开关载体 | `ProjectConfig.auto_write_enabled` 直接字段（与 supervisor 同层） | `extra`（与 book_max_* 上限语义混淆；issue 明示「与 supervisor 同层」）；全局 settings（F32 语义分道） |
| 授权载体 | `auto_write_enabled` 本身 = 已授权标志 | 独立 `authorized` 字段（冗余，一字段即可） |
| 授权检查层 | `prepare_run`（POST /runs 同步预校验，403 立即返回） | `write_book_agentic`（后台任务不可回滚，错误延迟）；router 层（绕过 service 校验） |
| 落章 HITL | `hitl_points` 默认含 `chapter_done` | 前端硬编码（绕过后端配置）；新 checkpoint（过度设计） |
| 首次弹框 | 前端 `AutoAuthorizationDialog` + PATCH config | 后端强制弹框（无 UI 载体）；CLI 同弹框（CLI 显式操作非 gate） |
