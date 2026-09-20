# 契约：#975 + #976 + #980-2a 合并轨（写作链路 + 草稿常显 + 树布局）

> 分支 `feat/975-976-980-writing-pane`，worktree `D:\develop\projects\InkFlow-ft\976-drafts-always`（基线 b1d556c）。
> RED 子代理与 Codex GREEN 任务书**都引用本文件**；语义冲突以本文件为准。
> 【R】= 当前必 FAIL（修复锚点）；【G】= 当前可 PASS（回归守护，必保持绿）。

## 0. 根因与决策表（源码实证）

| # | 事实 | 证据 |
|---|------|------|
| 1 | book 轨兜底草稿无条件 create | `book_pipeline.py:478-483`、`book_service.py:856-863` |
| 2 | agentic 轨正确形态 = `if not self._history_has_tool_call(history,"save_draft")` | `agentic_writer_service.py:215` |
| 3 | 委托 `result` 含完整消息历史（deepagents invoke 返回 dict 含 "messages"；既有测试 fake 即 `{"messages":[...]}`） | `agentic_writer.py:104-121`、`test_book_pipeline.py:190-193` |
| 4 | `_extract_final_content` 取 messages[-1]（agent 已 save_draft 时 = 回执垃圾文本） | `book_service.py:879-890` |
| 5 | book 轨草稿绑定章 id 来自 `outline.chapter_id`——book 轨从不建章 → 恒 NULL → confirm 409 | `book_service.py:60-66`、`draft_service.py:164-166` |
| 6 | drafts 表无 volume 列；卷=INTEGER id，前端 Volume.id 是 `uuid.UUID(int=id)` 字符串 | `agent_run.py:135-201`、`chapter_repo.py:32-38` |
| 7 | confirm 写章仅 `update_chapter(content,status=FINAL)`；word_count 由 repo 层 count_words 重算 | `draft_service.py:167-171`、`chapter_repo.py:212-221` |
| 8 | 树渲染无 volume 头也支持（ungrouped 容器恒在） | `ProjectTree.tsx:148,258-270` |
| 9 | `writing.test.tsx:730-742` 反向锁定「无 rail-panel-drafts」——**裁定：保留不动**（新弹层挂顶栏不挂右栏，天然兼容） | 见 §8 |

### 已裁定设计决策（父侧拍板，勿再讨论）

- **D1 守卫形态**：新增共享纯函数 `draft_fallback_needed(result) -> bool`（`domain/services/usage_accounting.py` 底部，零框架依赖），镜像 `_history_has_tool_call` 语义：遍历 `result["messages"]` 的 AI 消息（`type=="ai"` 或对象 `.type=="ai"`），任一 `tool_calls` 含 `name=="save_draft"` → False（不需兜底）。两处委托点 `if draft_fallback_needed(result): draft = await create(...)`；**跳过时 execution_id 回退 agent 已存草稿 id**：`_find_saved_draft_id(result)` 从 AIMessage 工具消息（`type=="tool"` 且对应名为 save_draft 的 tool_call，或 content 含 `"save_draft"` 结果 JSON）提取 `draft_id`；提取失败回退 `""`（卷轨 results 值 = `str(draft.id)` 语义，plan.execution_refs 的进度键是 outline_id，results 值仅作 execution_refs 映射——回退 `""` 可接受，但必须保证不新建草稿）。
  - 简化裁定（GREEN 可执行形态）：`_extract_saved_draft_id(result)` = 反向扫 messages，找 `type=="tool"` 或 role=="tool" 的消息中 content 可 `json.loads` 且 `ok==True` 且含 `draft_id` 键 → 返回该 draft_id 字符串；否则 `""`。无需匹配 tool_call_id（每章委托 agent 只调一次 save_draft 是常态；多次取最后一个）。
- **D2 volume_id 形态**：`drafts.volume_id` = `String(36)` 可空无 FK（镜像 chapter_id 列）；语义存**卷 UUID 字符串**（= `str(uuid.UUID(int=volume_row_id))`，与前端 Volume.id 完全一致）。迁移幂等 no-op 惯例（PRAGMA 检缺列）。
- **D3 创建绑定**：save_draft 工具与两处委托点均经新注入 `volume_lookup: Callable[[project_id, chapter_id|None], str|None]` 解析卷；无映射 → None。book_pipeline 的 chapter dict 需带 `outline_id`（已有）。**（2026-09-06 用户拍板扩展）chat 轨同样归组**：`api/deps_chat_agent.py:179` SaveDraftToolDeps 构造注入 volume_lookup 闭包 = 按 expected_chapter_id 反查 `ChapterService.get_chapter(chapter_id).volume_id` → `str(uuid)`；chapter_id None/章不存在/章无卷 → None。（writer 轨闭包签名 `(project_id, outline_id)` 收章 outline id，books.py 装配里按 outline 节点父卷解析——两轨 volume_lookup 入参第二项语义不同但签名形状一致，均为 uuid|None→str|None。归组统一由 GREEN round-2 批落地，主批任务书白名单外。）
- **D4 confirm 自动建章**：target 皆无时，若注入了 `chapter_creator`（`create_chapter(project_id, title, volume_id=None, content="") -> Chapter` 鸭子签名）→ 建章 + `update_chapter(FINAL)` + `update_chapter_binding(draft_id, new_chapter_id)` + **回填 `outlines.chapter_id`**（`outline_bindder(chapter_outline_id, chapter_uuid_str)`，仅当调用方传 `source_outline_id` 非 None）。标题 = `(summary or content).strip()[:30] or "草稿章节"`（字符切片非词）。`chapter_creator` 未注入 → 保持旧 `DraftStateError("草稿未绑定目标章节")`（409 兼容，既有【G】断言零改动）。confirm 签名扩展为 `confirm(draft_id, chapter_id=None, *, source_outline_id=None, title=None)`。
- **D5 卷轨 outline_id 透传**：`ChapterDict`/`_outline_to_chapter_dict` 增 `volume_outline_id: uuid.UUID | None`（= 卷 outline 节点 id，来自 VolumeGroup 的卷节点）；`_delegate_chapter` 兜底/工具建草稿时 `volume_lookup(plan.project_id, outline_id)` 解析（卷 outline id → OutlineORM.volume_id → str(uuid.UUID(int=vid))）。无卷轨（VolumeGroup.volume_id=root）→ None。
- **D6 前端双轨**：树数据源 = chapters（正式章）+ pendingDrafts（status=draft）合成，**草稿不进 ChapterMeta**（新建 `DraftTreeNode { kind:'draft'; id; draftId; summary; content; volume_id; created_at }`）。store 增 `pendingDrafts: DraftTreeNode[]` + `loadPendingDrafts(projectId)`；`loadChapterTree` 之后由写作页再调 `loadPendingDrafts`（或 store 内部链式，契约取**store 内部链式**：loadChapterTree 末尾追加 `await get().loadPendingDrafts(projectId)`，失败静默不阻断树）。confirm/reject 成功 → `loadChapterTree(treeProjectId)`（树+草稿双刷新）。
- **D7 审批入口**：新建 `DraftApprovalDrawer` 组件（弹层，自含状态，复用 drafts.ts API；ConfirmDialog 风格遮罩），挂在 `writing.tsx` 顶层（与 AuditDialog 并列）。顶栏**左树右**新增按钮 `drafts-approval-button`（文案 `write.drafts.pending` 插值计数）。树 `draft-*` 节点**双击** → 打开弹层。右栏 rail-panel-drafts 永不复活（writing.test.tsx:730-742 零改动）。
- **D8 树草稿节点**：有 volume_id → 渲染在对应 `volumes.map` 卷容器内（章之后）；无 volume_id → ungrouped 容器末尾。testid=`draft-{draftId}`，含 badge 文案 `write.drafts.pendingBadge`。草稿节点无编辑/删除/拖拽/字数。
- **D9 OpenAPI 三联动**：Draft 模型新字段 → GREEN 收尾必跑 `uv run python ../ci_cd/export_openapi.py` + `pnpm --filter renderer gen:api` 同 commit（CI 双门禁 unit-api 快照对拍 + lint-frontend drift）。ConfirmRequest 新增可选字段 → 同联动。
- **D10 CLI**：`agent draft confirm` 增 `--title` 可选透传 body（与 chapter_id 并存互不强制）。
- **D11 #980-2a**：字数 span `ml-auto`（非 shrink-0）+ 标题 button 恒 `flex-1 min-w-0 truncate` + `title={ch.title}`；hover 钮组出现时字数 `-mr-14` 让位。

## 1. #975 后端契约

### 1.1 新纯函数（domain/services/usage_accounting.py 底部）
```python
def draft_fallback_needed(result: dict[str, Any]) -> bool: ...
def _extract_saved_draft_id(result: dict[str, Any]) -> str: ...  # 私有，返回 "" 表示提取失败
```
消息双形态（dict `{"type":"ai","tool_calls":[{"name":...}]}` / 对象 `.type` `.tool_calls`），镜像 agentic_writer_service.py:46-76 helper 语义（**勿 import** agentic_writer_service——放 usage_accounting 共享，零框架依赖）。

### 1.2 委托点改造
- `book_pipeline.py:_delegate_chapter`：invoke 后 `if draft_fallback_needed(result):` 才 create；else 分支 execution_id = `_extract_saved_draft_id(result)`（可 ""）。usage 事件恒发（token 采集不动，既有 #902【G】断言保持）。
- `book_service.py:_delegate_chapter` 同构（limits 计数段不动）。
- 构造增参：`BookVolumePipeline.__init__(..., volume_lookup: Callable | None = None)`、`BookService.__init__(..., volume_lookup: Callable | None = None)`——真实装配（api/deps.py / books router 装配点）注入查 OutlineORM.volume_id 的闭包；未注入 → 草稿 volume_id=None。create 调用增 `volume_id=` 形参（D3）。

### 1.3 RED 用例（backend/tests/unit/infrastructure/agent/test_book_pipeline.py 追加 + backend/tests/unit/domain/services/test_book_service.py 追加）
- 【R】B975-1 pipeline：fake agent invoke 返回含 `{"type":"ai","tool_calls":[{"name":"save_draft","id":"c1"}]}` + 工具消息 `{"type":"tool","content":'{"ok":true,"draft_id":"d-1"}'}` + 末尾回执 AIMessage → `draft_service.create` **await_count==0**，execute completed 且 results 值 == "d-1"。
- 【R】B975-2 pipeline：消息无任何 save_draft tool_call → create 恰 1 次（summary=="书级委托保存" 不变）。
- 【R】B975-3 book_service：同 B975-1（`_delegate_chapter` 直调，draft_service.create.await_count==0 + 返回值==fake 工具消息 draft_id）。
- 【R】B975-4 book_service：无 save_draft → create 恰 1 次（镜像既有 test_delegate_chapter_save_draft_recycle 形态，该既有用例 fake messages 为 SimpleNamespace(content="正文") 无 tool_calls → 属【G】保持绿）。
- 【G】既有委托测试全部零改动保持绿（usage/limits/brief 断言）。

## 2. #976 后端契约

### 2.1 Draft 域模型/ORM/迁移
- `domain/models/draft.py`：Draft 增 `volume_id: uuid.UUID | None = None`。
- `DraftORM` 增 `volume_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)`。
- `core/database.py`：`ensure_drafts_volume_id_column(conn)`（PRAGMA table_info(drafts) → 缺列 ALTER TABLE ADD COLUMN volume_id VARCHAR(36)；表不存在 no-op）；`api/app.py` lifespan 注册 `await conn.run_sync(ensure_drafts_volume_id_column)`（既有迁移行之后）。
- `draft_repo.py`：create 签名增 `volume_id: uuid.UUID | None = None`（orm 构造 + _orm_to_domain 透传）。

### 2.2 DraftService
- `create(*, project_id, chapter_id=None, content, summary="", agent_run_id=None, volume_id=None)`（向后兼容）。
- `confirm(draft_id, chapter_id=None, *, source_outline_id=None, title=None)`（D4）。
- 构造增 `chapter_creator: object | None = None`、`outline_bindder: Callable[[str, str], Awaitable[None]] | None = None`；deps 装配真实闭包（ChapterService.create_chapter + OutlineRepo 回填）。
- `save_draft_tool.py`：`SaveDraftToolDeps` 增 `volume_lookup: Callable[[uuid.UUID, uuid.UUID|None], str|None] | None = None`；工具内解析 `vol = deps.volume_lookup(pid, chid) if deps.volume_lookup else None`，`uuid.UUID(vol)` 容错传 create。

### 2.3 API
- `GET /api/v1/agent/drafts` 响应 items（Draft.model_dump）自动含 `volume_id`（无端点签名改动）。
- `ConfirmRequest` 增 `source_outline_id: uuid.UUID | None = None`、`title: str | None = None`。
- CLI `agent draft confirm` 增 `--title`（D10）。

### 2.4 装配点事实（父侧盘点，防 Codex 越权）
- SaveDraftToolDeps 构造点全仓 = ① `api/deps_chat_agent.py:179`（chat 轨——注入 volume_lookup 闭包：按 expected_chapter_id 反查 ChapterORM.volume_id → str(uuid.UUID(int=vid))，章无卷/未绑定 → None；**chat 轨草稿也带卷归组，用户已确认**）② `infrastructure/agent/agentic_writer.py:177`（book/MCP writer 轨——AgenticWriterDeps 增可选 volume_lookup 透传，装配点 books.py 注入 outline→卷闭包）。RED 须含 chat 轨直测（见 L 组）。
- DraftService 真实构造点 = `api/deps.py` get_draft_service + `api/routers/books.py:270`（两处注入 chapter_creator/outline_bindder）。

### 2.5 RED 用例落点（必对照 CI 收集面）
- `backend/tests/unit/infrastructure/database/test_draft_repo.py` 追加：【R】create(volume_id=uuid) → 读回 .volume_id 相等；【R】存量行 volume_id 列缺省 None（ORM 默认）；【G】既有 create/get/list/update 零改动。
- 新文件 `backend/tests/unit/core/test_drafts_volume_migration.py`：真同步 SQLite，镜像 `test_outline_908`/`test_volume_unify` R10 形态——缺列表 ALTER+幂等二跑+表不存在 no-op。【R】（ImportError）。
- `backend/tests/unit/domain/services/test_f27_service_gaps.py` 追加（镜像 `_make_draft_service` 形态）：【R】confirm 无目标 + 注入 chapter_creator → create_chapter(project_id, 标题=summary[:30]) + update_chapter FINAL + repo.update_chapter_binding（若断言 repo 方法不存在则改用 update_content？——**裁定**：DraftRepo 新方法 `update_chapter_binding(draft_id, chapter_id) -> Draft | None` 落 repo + 单测【R】）；【R】summary 空 → content 前 30 字；【R】恰 30 截断；【R】source_outline_id 传值 → outline_bindder 以 (str(outline_id), str(new_chapter_id)) await 一次；【G】chapter_creator 未注入 → 旧 DraftStateError 断言（test_draft_confirm_no_target_chapter 零改动）；【R】显式 title 参数优先于 summary 派生。
- `tests/api/test_f27_agentic_api.py` 追加：【R】confirm body 含 source_outline_id+title → 200 + svc.confirm 收到 kwargs；【G】既有 confirm 200/409/404 零改动（mock svc 未配 chapter_creator → 旧 409 语义仍由 side_effect 驱动，不依赖真实 service）。
- `tests/integration/` 新文件 `test_draft_confirm_auto_chapter_976.py`：真实 in-memory SQLite（镜像 test_book_run_953_bridge 的 db_session fixture）——建项目+卷+章 outline 点，落 volume_id 草稿（chapter_id=NULL），svc.confirm → 新章 FINAL + word_count>0 + draft.chapter_id 回填 + outlines.chapter_id 回填。【R】。
- `tests/cli/test_cli_agent_draft.py` 追加：【R】`--title "X"` → POST confirm body 含 title；【G】既有 chapter_id 透传/无 body 断言零改动。
- `backend/tests/unit/domain/services/test_draft_volume_976.py`（新）：save_draft 工具 volume_lookup 注入 → create 收 volume_id；未注入 → None。【R】（create 收 volume_id kwarg 现不存在）。

## 3. #976 前端契约

### 3.1 stores/chapter.ts
- 新导出 `export interface DraftTreeNode { kind: 'draft'; id: string; draftId: string; summary: string; content: string; volume_id: string | null; created_at: string }`。
- state 增 `pendingDrafts: DraftTreeNode[]`；actions 增 `loadPendingDrafts(projectId): Promise<void>`（GET `/api/v1/agent/drafts?project_id=<pid>&status=draft`，映射 items → DraftTreeNode，id=`draft-${d.id}`）与 `confirmDraft(draftId): Promise<void>` / `rejectDraft(draftId)` 封装（POST confirm 空 body / reject），成功 → `await get().loadChapterTree(treeProjectId)`（同项目 reload 保留当前章，#371 语义）。`loadChapterTree` 末尾链式 `void get().loadPendingDrafts(projectId)` 改为 **await**（同 set loading 窗内）。
- `resetTree()` 清 pendingDrafts（store 重置点镜像既有 volumes/chapters 清空处——若无独立 reset 则不新增）。

### 3.2 components/ProjectTree.tsx
- 订阅 `pendingDrafts`；卷容器内章之后 `pendingDrafts.filter(d => d.volume_id === v.id).map(renderDraft)`；ungrouped 容器同理（volume_id===null 的草稿）。
- `renderDraft(d)`：div `data-testid={`draft-${d.draftId}`}`，`onDoubleClick={() => openApprove(d.draftId)}`（经 store 新方法 `approvalRequest: string | null` + `requestApproval(draftId)` / `clearApprovalRequest()`，writing.tsx 消费该字段开关弹层——**跨组件不传 callback**，镜像 zustand 全局）。badge span `data-testid={`draft-badge-${d.draftId}`}` 文案 `t('write.drafts.pendingBadge')`；标题 span `truncate` + `title={d.summary}`；无字数/无编辑删除钮。
- #980-2a（同文件一次改）：:109 className → `min-w-0 flex-1 truncate text-left` + `title={ch.title}`；:114 → `ml-auto text-[11px] text-ink-3 group-hover:-mr-14 transition-all`（保留字数文本节点）。**若 group-hover 让位在 jsdom 不可测，按 §3.5 断言 className 字面量**。

### 3.3 components/DraftApprovalDrawer.tsx（新）
- props `{ open: boolean; onClose(): void }`，projectId 自 `useProjectStore` 当前项目。
- open 变化 → listDrafts(status='draft')；渲染遮罩 `drafts-overlay`、面板 `drafts-drawer`、每草稿 `drafts-drawer-item-{id}`（summary + 前 60 字展开钮复用 `write.drafts.expand/collapse`）、确认钮 `drafts-drawer-confirm-{id}` → confirmDraft API → 成功 toast + 关框 + `useChapterStore.getState().loadChapterTree(pid)`；失败 → 框内错误 `drafts-drawer-error`（409 文案透传）。Esc/遮罩外点击 = onClose（镜像 ConfirmDialog 焦点陷阱可简化，但 Esc 必测）。
- i18n 新键（§3.4）。

### 3.4 i18n（writing-ux.ts 拆分文件，勿动 zh.ts/en.ts 主文件——900 行护栏）
- `write.drafts.pending`：zh `草稿 ({count})` / en `Drafts ({count})`（⚠️ 本项目 interpolate = **单花括号** `{key}`，useI18n.ts:26，勿写 `{{count}}`）
- `write.drafts.pendingBadge`：zh `草稿/未审批` / en `Draft`
- `write.drafts.openApprove`：zh `审批草稿` / en `Approve draft`（title 属性/aria-label）
- `write.drafts.ungroupedDrafts` 不需要（草稿落 ungrouped 容器无独立头）。
- 新文件 `frontend/packages/renderer/src/components/DraftApprovalDrawer.test.tsx`：渲染/加载/确认闭环/Esc。
- `api/drafts.ts`：`listDrafts(projectId, status?)` 可选 status 透传（既有调用零破坏）+ `DraftDto.volume_id?: string | null`。
- 既有 `src/api/drafts.test.ts` 锁「无 status query」？——核实现文件（`?project_id=p1` 等值断言）：GREEN 保持 status 缺省时 URL 与既有完全一致（既有【G】）。
- `pages/writing.tsx`：顶栏区（ProjectTree aside 之后、editor main 之前**不可行**——按钮须属写作页顶部）→ 实际挂载点 = `<div className="flex h-full flex-col">` 内、三栏 div 之上**无顶栏**——裁定：新顶栏条 `data-testid="writing-topbar"`（h-9 flex items-center justify-end px-2 border-b border-line），内含 `drafts-approval-button`（`<FileText>` lucide + `t('write.drafts.pending', { count: pendingCount })` + pendingCount>0 时 badge 高亮）。pendingCount = `useChapterStore(s => s.pendingDrafts.length)`。
- writing.test.tsx 追加新 describe：【R】顶栏按钮存在且计数正确；【R】点按钮 → drafts-drawer 打开；【R】树内 `draft-{id}` 节点渲染 + badge；【R】双击 draft 节点 → 弹层打开；【G】:730-742 反向锁定零改动（天然绿，右栏无变化）。
- stores/chapter.test.ts 追加：【R】loadPendingDrafts 后 pendingDrafts 映射正确；【R】confirmDraft action 成功 → loadChapterTree 重拉；【G】既有树加载断言若因链式 loadPendingDrafts 多一次 fetch mock 计数变化——RED 子代理**先跑既有文件**标出受影响用例，迁移为「fetch 含 status=draft 请求」形态（属 §8 合法迁移，须对照本契约 §2/§3 确认后改，禁止放宽断言凑绿）。

### 3.5 #980-2a RED（ProjectTree.test.tsx 追加）
- 【R】章节行字数 span：`closest('div').querySelector('span.ml-auto')` 存在且不含 `shrink-0`（按 className 字面量断言）。
- 【R】标题 button className 含 `flex-1` 且元素有 `title` 属性 == ch.title。
- 【R】长标题（50 字）渲染不崩 + title 属性兜底（jsdom 无布局，truncate 靠类名字面量）。

## 4. 范围外（勿动）
- #980-2b 卷分组（大纲卷→写作卷映射）归 0.14.0，本批零代码。
- `outlines.chapter_id` 预建回填链路（confirm 回填是本批唯一触点，D4）。
- DraftApprovalPanel.tsx 旧组件：保留不动（弹层另起文件；死代码清理另行拍板，PR body 登记）。
- 右栏（right-rail）布局、rail-resize 系列。
- agentic_writer_service.py（参考实现，勿改）。

## 5. 测试命令（cwd=worktree backend/；单元与顶层不同 pytest）
```
uv run pytest tests/unit/ -q                      # 单元
uv run pytest ..\tests\api\ -q                    # API
uv run pytest ..\tests\integration\ -q            # 集成
uv run pytest ..\tests\cli\ -q                    # CLI（INKFLOW_DATA_DIR 隔离另设）
uv run python -m ruff check src/ tests/unit/ ..\tests\ ..\ci_cd\
uv run python -m mypy src/
uv run python ../ci_cd/check_file_length.py 900 src/ ../tests/ tests/unit/ ../frontend/packages/
uv run python ../ci_cd/check_noqa_reason.py src/ ../tests/ tests/unit/
# 前端（worktree frontend/）
pnpm --filter renderer test / typecheck / lint
```
RED 落盘预期失败面 = 后端 ~15-20 用例 + 前端新文件/新 describe collection error；既有【G】零红。
