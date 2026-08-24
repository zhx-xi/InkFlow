# InkFlow 前端测试断言有效性审计报告

- 审计对象：`frontend/packages/renderer/src` + `frontend/packages/electron/src` 下 85+ 个 `*.test.ts(x)`
- 审计范围：`scan_front_v3_out.txt` 列出的 102 个「只有弱断言、无强断言」的 test 块（逐块读源码判定）
- 方法：对每个命中块读完整 `it()` 体，按 6 类标准判定（类型 1 弱断言无行为验证 / 2 仅调用断言 / 3 存在性断言 / 4 否定路径（有效） / 5 仅初始 state / 6 mock 回显）
- 日期：2026-08-20；只审计未改任何项目文件

## ⚠️ 扫描器方法论缺陷（影响整个清单的可信度）

`scan_front_v3.py` 存在两个系统性误报源，**102 个命中里绝大多数实际是有效测试**：

1. **STRONG 正则 `expect\([^)]*\)\.` 无法匹配 expect 参数含嵌套括号的断言**。项目大量断言形如
   `expect(useAgentStore.getState().config.agent_architect).toBe(AGENT_DEFAULT_SENTINEL)`——
   正则的 `[^)]*` 在 `getState()` 的 `)` 处截断，后面的 `.toBe(...)` 匹配不到 STRONG 集合，
   整块被误判为「只有弱断言」。AgentChainCard / book / project 等 store 背书的块几乎全部中招。
2. **`toBe(具体值)` 被归为弱断言**（WEAK 集合含 `toBe`）。`toBe('zhipu/glm-4.5')`、`toBe(8)`、
   `toBe('tray')` 这类具体值断言实为强断言。
3. 否定路径断言 `not.toHaveBeenCalled()` 被一律视为弱，但按任务标准（类型 4）它们是**有效**的守卫生效验证。

**结论：扫描清单应视为「候选名单」，不能直接作为弱断言证据；本报告以源码实读为准。**

---

## 汇总

| 层 | 命中块数 | 真实无效 | 合理弱断言 | 需人工复核 |
|---|---|---|---|---|
| api | 7 | 0 | 7 | 0 |
| components | 34 | 0 | 33 | 1 |
| pages | 22 | 0 | 22 | 0 |
| stores | 15 | 0 | 15 | 0 |
| hooks | 5 | 0 | 5 | 0 |
| electron | 19 | 0 | 16 | 3 |
| **合计** | **102** | **0** | **98** | **4** |

判定汇总：**真实无效 0 处 / 合理弱断言 98 处 / 需人工复核 4 处**。

---

## 一、api 层（7 命中，全部合理）

命中块的「弱断言行」均只是块内众多断言之一，且其余断言为强断言（toHaveBeenCalledWith / toBe 具体值 / URL 精确断言）；个别 toBeNull/toBeUndefined 是契约点本身的否定校验。

- `api/client.test.ts:49` GET 无 body：弱行 `init.body).toBeUndefined()`；同块有 `url).toBe(BASE+'/health')`、`headers.get('X-InkFlow-Token')).toBe('tok-1')`、`Content-Type).toBeNull()` → 合理
- `api/client.test.ts:98` 204 无 body：弱行 `jsonSpy).not.toHaveBeenCalled()`；同块 `resolves.toBeUndefined()`（若实现调 res.json() 则 jsonSpy 被调 → 该否定断言是真正拦截点，防 #140 回归）→ 合理（类型 4）
- `api/sessions.test.ts:249` planner 响应解析：弱行 `writing_plan_id).toBeNull()`；同块 `one_liner).toBe('仙侠长篇 80 万字')`、`status).toBe('drafting')`、`total).toBe(1)` → 合理
- `api/sse.test.ts:123` 无 token 不带头：弱行 `headers['X-InkFlow-Token']).toBeUndefined()`；同块 `Content-Type).toBe('application/json')`，且该断言正是「token 空时不带认证头」的契约点 → 合理
- `api/sse.test.ts:309` abort 静默：弱行 `onError/onDone).not.toHaveBeenCalled()`；同块 `signal?.aborted).toBe(true)` 等强断言 + 否定路径 → 合理（类型 4）
- `api/vector.test.ts:114` stale 解析：弱行 `indexed_fp).toBeNull()`；同块 `stale).toBe(true)`、`reason).toBe('unknown')` → 合理
- `api/vector.test.ts:152` 缺省 entityTypes：弱行 `body.entity_types).toBeNull()`；同块 `result.indexed).toBe(87)`，且 toBeNull 正是「缺省→null」契约点 → 合理

---

## 二、components 层（34 命中：33 合理 + 1 复核）

### 合理（33）

- `AddModelDialog.test.tsx:172` 全部行 ID 空 → no-op：`onAdd/onDone/onOpenChange).not.toHaveBeenCalled()` ×3 + 弹窗仍在（getByTestId）→ 类型 4 守卫，改逻辑（空行也保存）即红
- `AddModelDialog.test.tsx:274` 无 provider → no-op：同上，类型 4 守卫
- `AgentChainCard.test.tsx:170` 三态映射 1：弱行 `onConfigChange).toHaveBeenCalled()`；同块 `config.agent_architect).toBe(AGENT_DEFAULT_SENTINEL)`（嵌套括号致扫描器漏判）→ 合理
- `AgentChainCard.test.tsx:183` 三态映射 2：同块 `config.agent_writer).toBe('zhipu/glm-4.5')` → 合理
- `AgentChainCard.test.tsx:198` 三态映射 3：同块 `config.agent_architect).toBeNull()` + Select 消失（not.toBeInTheDocument）→ 合理
- `AgentChainCard.test.tsx:334` Writer 上移：同块 `agent_order).toEqual([...并行组])` → 合理
- `AgentChainCard.test.tsx:348` Writer 下移：同块 `agent_order).toEqual([...])` → 合理
- `AgentChainCard.test.tsx:416` 默认模式不写 order：同块 `agent_architect).toBe(SENTINEL)` + `agent_order).toBeUndefined()` → 合理
- `AgentChainCard.test.tsx:491` R3 自定义开关：同块 `agent_roles).toEqual({agent_researcher: SENTINEL})` → 合理
- `AgentChainCard.test.tsx:618` 依赖编辑即改即存：同块 `config.agent_relations).toEqual([...])` → 合理
- `AgentChainCard.v15.test.tsx:169` 添加世界观顾问：同块 `agent_worldview).toBe(SENTINEL)` + `agent_order).toEqual([...默认4层+末尾层])` → 合理
- `AgentEditDialog.test.tsx:227` 名称必填：弱行 `onCreate).not.toHaveBeenCalled()`；同块 `getByText('名称不能为空')).toBeInTheDocument()` → 合理（类型 4 + 强断言）
- `AgentRelationEditor.test.tsx:203` 自环预检：同块 `agent-relation-error).toHaveTextContent('不能自环')` + `config.agent_relations).toEqual([])` → 合理
- `AgentRelationEditor.test.tsx:219` 重复边预检：同块 `toHaveTextContent('已存在')` + `toHaveLength(3)` → 合理
- `AgentRelationEditor.test.tsx:336` 新角色落库：同块 `config.agent_relations).toEqual([{from:'agent_worldview',...}])` → 合理
- `BookPlannerPanel.test.tsx:459` 未配置模型不发 startPlanner：toast type=warn + message 含「配置」断言 + `startSpy).not.toHaveBeenCalled()` → 合理（类型 4 + toast 内容）
- `BookRunPanel.test.tsx:150` 无 runId 不发请求：`apiFetchMock).not.toHaveBeenCalled()`（挂载若乱发请求即红）+ 面板存在断言 → 类型 4 合理（注：「空态文案」实际未断言，仅面板存在，小缺口）
- `ChatPanel.test.tsx:178` chapterContent 空不注入：弱行 `chapter_context).toBeUndefined()`；同块 `prompt).toBe('你好')`，且 toBeUndefined 正是注入守卫契约点 → 合理
- `ChatPanel.test.tsx:292` 未配置（providers 空）：toast warn+配置 + `executeMock).not.toHaveBeenCalled()` → 合理（类型 4）
- `ChatPanel.test.tsx:311` 未配置（key_saved=false）：toast warn + 不发 execute → 合理（类型 4）
- `ChatPanel.test.tsx:344` Enter 键同守卫：toast warn + 不发 execute → 合理（类型 4）
- `ChatPanel.test.tsx:415` 拖动改高度：弱行 `before/after).toBeTruthy()`；同块 `Number(after)).toBeGreaterThan(Number(before))`（强）→ 合理
- `ExecutionDetailPanel.test.tsx:73` 无 executionId：`exec-detail-empty` 存在 + 不发请求 → 合理（类型 4）
- `NewProjectDialog.test.tsx:233` 遮罩不关闭：弱行 `backdrop).not.toBeNull()`（null 安全守卫）；同块遮罩点击后 `getByRole('dialog')).toBeInTheDocument()`（#195 保持打开）→ 合理
- `ProjectTree.test.tsx:169` Escape 取消：`+ 新建章节` 按钮回归 + `inputEl().value).toBe('')`（清空，强）+ 不调 createChapter → 合理
- `ProjectTree.test.tsx:185` 取消按钮：创建态关闭 + 不调 createChapter → 合理（类型 4）
- `ProjectTree.test.tsx:197` 无 currentProjectId：`inputEl().value).toBe('孤儿章节')`（输入保留，强）+ 不调 createChapter → 合理
- `ProviderDialog.test.tsx:393` 填 Key 保存：弱行 `onSaved).toHaveBeenCalled()`；同块 `apiFetchMock.mock.calls.some(...llm-keys POST)` + `some(...provider-configs POST)`（双端点落库验证）→ 合理
- `TemplateDialog.test.tsx:259` 遮罩不关闭（#349）：遮罩点击后 dialog 仍在 + onOpenChange 不调 → 合理（类型 4）
- `TemplateDialog.test.tsx:271` 输入框交互不关闭：dialog 仍在 + onOpenChange 不调 → 合理（类型 4）
- `TemplateDialog.test.tsx:323` 名称空：`getByText('模板名称不能为空')).toBeInTheDocument()` + onCreate 不调 + dialog 保持 → 合理
- `components/ui/toast.test.tsx:31` 空态：`live).not.toBeNull()` + `queryByRole('status')).not.toBeInTheDocument()`（组合断言）→ 合理
- `WindowControls.test.tsx:117` api-ready 补订：初始 not.toBeCalled（跳过订阅）+ 同块 `onMaximizedChange).toHaveBeenCalledTimes(1/2)`、`unsubscribe).toHaveBeenCalledTimes(1)`、aria-label 切换 → 合理

### 需人工复核（1）

- `BookPlannerPanel.test.tsx:305`「点 book-auto → store.respondAuto()」：**块内唯一断言 `autoSpy).toHaveBeenCalled()`**（类型 2 边缘）。
  证据：`expect(autoSpy).toHaveBeenCalled();`（L312，无参数、无 Times、无状态后继断言）。
  为什么偏弱：respondAuto 为零参方法，「传参错误」场景不适用；但若实现把调用点挪到挂载/其它触发器，测试仍绿；重复绑定两次也仍绿。
  建议：`toHaveBeenCalledTimes(1)` + 点击后可断言 store 状态（如 messages 构建）或按钮触发即完成态。**判定：可接受但不强，非「改逻辑必红」级别的无效。**

---

## 三、pages 层（22 命中，全部合理）

模式：`apiFetchMock.mock.calls.find((c) => URL && method && body谓词)` + `expect(call).toBeTruthy()`——
find 谓词本身编码了 URL/方法/请求体契约，toBeTruthy 是其最后一步；多数块还带 DOM 消失/回显强断言。

- `library-kg.test.tsx:302` 关系删除：`find(...DELETE knowledge-relations/9)` + `queryByText('属于')).not.toBeInTheDocument()`（行消失）→ 合理
- `library-p1.test.tsx:239` R2 等级保存：`postCall).toBeTruthy()` + `body.extra).toEqual(objectContaining({role_rank:'major'}))` → 合理
- `library-p2.test.tsx:440` M11 pin 删除：DELETE find + `toHaveLength(1)`（剩 1 行）+ `queryByText('标记一')).not.toBeInTheDocument()` + ok toast → 合理
- `library-p2.test.tsx:493` M13 shapes 删除：PATCH find（谓词含「shapes 不再含 s_1」）+ 形状消失 → 合理
- `library-p2.test.tsx:607` #368 地图名显示：弱行 `row).not.toBeNull()`（closest 守卫）；同块 `getByText('九州舆图')).toBeInTheDocument()` + w1a 无徽标 → 合理
- `library-p2.test.tsx:624` #368 树层级：弱行 `parentRow).not.toBeNull()`；同块 `getByText('中州细图'))` + `map-bc-current).toHaveTextContent('中州细图')` → 合理
- `library-p2.test.tsx:742` #388 简图改名：PATCH find + `s?.label).toBe('主城')` + 画布 `getByText('主城')` 回显 → 合理
- `library-p2.test.tsx:773` #389 分类新建：`body.name).toBe('势力')` + 新 chip 出现（findByTestId）→ 合理
- `library-p3.test.tsx:160` T2 拖拽重排：`body.parent_map_id).toBe('root2')` + 缩进变化（toBeGreaterThan）→ 合理
- `library-p3.test.tsx:194` T3 拖到根：`body.parent_map_id).toBeNull()` + 缩进回根层级 → 合理
- `library.test.tsx:728` L7 取消/遮罩：取消后 dialog 消失 + 遮罩点击后 dialog 仍在 → 合理（类型 4）
- `memory.test.tsx:263` 无项目引导：`memory-no-project` 存在 + `fetchMemorySummariesMock).not.toHaveBeenCalled()` + 导航后 `projects-probe` 出现 → 合理（类型 4）
- `search.test.tsx:118` 无项目空态：空态存在 + 无输入框 + 不发检索 → 合理（类型 4）
- `search.test.tsx:127` 有项目表单齐全：4 控件存在 + 初始无结果/空态/加载/错误（4 个 not.toBeInTheDocument）+ 不发检索 → 合理
- `search.test.tsx:194` q 全空白：`fetchSearchMock).not.toHaveBeenCalled()`（strip 守卫，输入全空格点检索若发起即红）→ 合理（类型 4）
- `settings-kg-extract.test.tsx:336` 契约5 i18n 键：`zh[key]).toBeTruthy()/en[key]).toBeTruthy()` 循环（键缺失/空串均会 FAIL）+ needModel 一条 `toBe('需先在模型设置中配置大模型')` 钉死 → 合理（键存在契约，toBeTruthy 对 undefined/'' 有效）
- `settings.autosave.test.tsx:504` 空值失焦：不发 PATCH + `toasts).toHaveLength(0)`（双否定路径）→ 合理（类型 4）
- `writing.test.tsx:411` 快捷键兜底 Ctrl+A：`execMock).not.toHaveBeenCalled()` + `patchCalls()).toHaveLength(0)` + `executeMock).not.toHaveBeenCalled()`（三路无副作用）→ 合理（类型 4）
- `writing.test.tsx:657` 未配置→续写：toast warn+配置 + 不发 execute → 合理（类型 4）
- `writing.test.tsx:669` 未配置→生成：同上 → 合理（类型 4）
- `writing.test.tsx:679` 未配置→Ctrl+Enter：同上 → 合理（类型 4）
- `writing.test.tsx:~685` 未配置→Ctrl+Shift+Enter：同上 → 合理（类型 4）

---

## 四、stores 层（15 命中，全部合理）

命中块多为「播种非默认态 → 触发 action → 断言回弹/清零」模式，toBeNull/not.toHaveBeenCalled 是行为验证本身；且同块普遍带 `toBe(具体值)`/`toEqual` 强断言（嵌套括号逃过扫描器）。

- `agent.test.ts:85` undefined 不再用于关闭：弱行 `cfg.agent_writer).toBeUndefined()`；同块 `JSON.stringify(cfg)).not.toContain('agent_writer')`（序列化契约）→ 合理
- `agent.test.ts:199` saveConfig 关闭态：`body.config.agent_writer).toBeNull()`（显式 null 非缺键）+ `body.config.model).toBe('gpt-4o')` → 合理
- `book.test.ts:412` 契约面 confirmRun：`typeof s.confirmRun).toBe('function')` + `waitingHitl).toBe(false)` + `confirming).toBe(false)`（初始态契约）→ 合理
- `book.test.ts:525` reset 清 3 字段：先播种非默认（waitingHitl:true/hitlPayload 有值/confirming:true）再 reset 断言清零 → 非假绿，合理
- `book.test.ts:572` 契约面 setDensity：`typeof ...).toBe('function')` ×3 + `density).toBe('dashboard')` → 合理
- `book.test.ts:584` setDensity 本地切换：`density).toBe('silent')`（强）+ 不发请求 → 合理
- `book.test.ts:718` reset 清 5 字段：播种非默认中间态（density:'silent'/interveneDiff 有值等）后清零断言 → 合理
- `chapter.test.ts:165` saveContent 未选中：`apiFetchMock).not.toHaveBeenCalled()`（无章节时若乱发 PATCH 即红）→ 合理（类型 4）
- `models.test.ts:379` addModel provider 不存在：`rejects.toThrow('Provider 不存在')` + `error).toContain(...)` + 不发 PATCH → 合理（类型 4 + 强断言）
- `project.test.ts:364` deleteProject 当前项目：弱行 `currentProjectId).toBeNull()`；同块 `projects.map(...)).toEqual(['p2'])` → 合理
- `skills.test.ts:181` copySkill 失败：`rejects.toThrow` + `skills.map(...)).toEqual([1,2])`（列表不变）+ error 设置 → 合理
- `theme.test.ts:317` 后端不可达：弱行 `warnSpy).toHaveBeenCalled()`；同块 `theme).toBe('paper')`、`font).toBe('sans')`（快照保持）+ `toasts).toHaveLength(0)` → 合理
- `theme.test.ts:441` setCloseBehavior PATCH reject：`rejected).toBe(false)`（不 rethrow）+ `closeBehavior).toBe('tray')`（回弹强断言）+ toast err + 不推 IPC → 合理
- `theme.test.ts:467` initFromBackend tray 提示：`dismissTrayHint).toHaveBeenCalledTimes(1)` + `trayHintDismissed).toBe(true)`；弱行 `setCloseBehavior).not.toHaveBeenCalled()` 是「不误推」守卫 → 合理
- `theme.test.ts:497` setTrayHintDismissed reject：`rejected).toBe(false)` + `trayHintDismissed).toBe(false)`（回弹）+ toast err → 合理

---

## 五、hooks 层（5 命中，全部合理）

- `useBookLimits.test.ts:80` setValue 本地更新：`values.max_chapters).toBe(8)`、`max_sessions).toBe(2)`（强）+ 不发请求 → 合理
- `useExecutionPoll.test.ts:88` 初始状态：`status).toBe('idle')` + `finalOutput).toBe('')` + `totalDurationMs).toBe(0)`（强），弱行 toBeNull 为 null 默认值契约 → 合理
- `useExecutionPoll.test.ts:237` confirm 无 executionId：`confirmMock).not.toHaveBeenCalled()` + `status).toBe('idle')` → 合理（类型 4）
- `usePipeline.test.ts:102` 初始状态：`status).toBe('idle')` + `finalOutput).toBe('')` + `totalDurationMs).toBe(0)` → 合理
- `useStream.test.ts:83` 初始状态：`status).toBe('idle')` + `text).toBe('')` + `wordCount).toBe(0)` → 合理

---

## 六、electron 层（19 命中：16 合理 + 3 复核）

### 合理（16）

- `main.tray.test.ts:298` second-instance：`win.show).toHaveBeenCalledTimes(1)` + `focus).toHaveBeenCalledTimes(1)`；弱行 `restore).not.toHaveBeenCalled()` 为「非最小化不 restore」守卫 → 合理
- `main.tray.test.ts:313` 单实例锁失败：`appMock.quit).toHaveBeenCalledTimes(1)` + 不建窗/不 spawn（双否定守卫）→ 合理（类型 4）
- `main.tray.test.ts:349` get-close-behavior 默认：`getCloseBehaviorHandler(null)).toBe('tray')`（强）；弱行 toBeDefined 为前置 → 合理
- `main.tray.test.ts:354` set 即改即生效：get→'quit'→'tray' 往返断言（强）→ 合理
- `main.tray.test.ts:369` 启动创建 Tray：`String(iconPath)).toContain('inkflow-icon-256.png')`（强）+ setContextMenu 被调 → 合理
- `main.tray.test.ts:388` 菜单打开主窗口：`win.show/focus).toHaveBeenCalledTimes(1)`；弱行 openItem.toBeDefined 为前置 → 合理
- `main.tray.test.ts:396` 图标 click：`win.show/focus).toHaveBeenCalledTimes(1)`；弱行 clickCallback.toBeDefined 为前置 → 合理
- `main.tray.test.ts:436` 菜单退出：`trayInstance.destroy).toHaveBeenCalledTimes(1)` + `kill).toHaveBeenCalledTimes(1)` + `appMock.exit).toHaveBeenCalledTimes(1)` → 合理
- `main.tray.test.ts:450` quit 模式：preventDefault 不调 + hide 不调 + `appMock.exit).toHaveBeenCalled()` → 合理
- `main.tray.test.ts:470` tray 模式 window-all-closed：`event.preventDefault).toHaveBeenCalledTimes(1)`（强）+ 不 exit/不 kill → 合理
- `main.window-controls.test.ts:243` toggle-maximize 还原分支：`isMaximized).toHaveBeenCalledTimes(1)` + `unmaximize).toHaveBeenCalledTimes(1)`；弱行 `maximize).not.toHaveBeenCalled()` 为分支互斥守卫 → 合理
- `main.window-controls.test.ts:251` toggle-maximize 最大化分支：`maximize).toHaveBeenCalledTimes(1)`；弱行 `unmaximize).not.toHaveBeenCalled()` 为分支互斥 → 合理
- `main.window-controls.test.ts:287` will-navigate file:// 不拦截：`preventDefault).not.toHaveBeenCalled()`（本地导航若被拦即红）→ 合理（类型 4）
- `main.window-controls.test.ts:376` 畸形行静默：`webContents.send).not.toHaveBeenCalled()`（垃圾行若触发推送即红）→ 合理（类型 4）
- `main.window-controls.test.ts:512` 连续 6 次失败：`kill.mock.calls.length).toBe(killBefore+6)` + `spawn).toBe(spawnBefore+6)`（强）；弱行 `app.exit).not.toHaveBeenCalled()` 为「重试分支不退出」守卫 → 合理
- `preload.test.ts:87` 就绪前无副作用：`dispatchMock).not.toHaveBeenCalled()` + `exposeInMainWorld).not.toHaveBeenCalled()`（若提前注入即红）→ 合理（类型 4）

### 需人工复核（3）

- `main.tray.test.ts:294`「启动时序：requestSingleInstanceLock 在 whenReady 启动回调内被调用」：**块内唯一断言 `expect(appMock.requestSingleInstanceLock).toHaveBeenCalled()`**（类型 2 边缘）。
  证据：L295 `expect(appMock.requestSingleInstanceLock).toHaveBeenCalled();`——裸调用断言。
  为什么偏弱：mock 里 `whenReady` 立即 resolve，import 即完整执行启动回调；若实现把锁调用挪到模块顶层（whenReady 之外），测试**仍绿**——声明的「§5.5 时序约束」实际不可验证，只能验证「启动时调用了锁」（删掉锁调用会红）。
  建议：让 whenReady 可控（手动 resolve）后断言锁调用发生在 resolve 之后，或接受其为冒烟并改测试名。
- `main.tray.test.ts:362`「dismiss-tray-hint 幂等可调用（置 trayHintDismissed）」：弱行 `expect(dismissTrayHintHandler).toBeDefined()`，随后 `await dismissTrayHintHandler(null)` **无任何状态/副作用断言**（类型 3/1 边缘）。
  证据：L363-364 仅 toBeDefined + 调用 handler。
  为什么偏弱：handler 变空实现（不置 trayHintDismissed）本块仍绿；该效果由同文件 L419「dismiss 后再 close 不再发 inkflow:tray-hint」用例间接覆盖（套件内互补，非完全无效）。
  建议：块内补 `getState` 侧状态断言，或合并进 L419 用例。
- `main.window-controls.test.ts:500`「健康检查 fetch 抛异常 → catch 分支（ok=false）不崩溃」：**块内唯一断言 `expect(failingFetch).toHaveBeenCalled()`**（类型 2 边缘）。
  证据：L507 `expect(failingFetch).toHaveBeenCalled();`——只证明健康检查发起了 fetch。
  为什么偏弱：catch 分支的失败计数/不崩溃语义未直接验证；若实现删掉 try/catch 或 catch 内静默吞掉不计失败，本块仍绿（「连续 3 次失败重启」用例走的是 ok:false 路径，不覆盖 reject 路径）。
  建议：断言 reject 后失败计数副作用（如 3 次 reject 后触发 kill/重启），或断言无 unhandledRejection（setup 层）。

---

## Top 3 最严重发现

1. **扫描工具系统性误报（影响整个 102 清单）**：STRONG 正则对 `expect(getState().config.x).toBe(...)` 类断言失效 + `toBe(具体值)` 被划为弱断言 + 否定路径一律计弱。导致 102 命中里约 98 个实际有效。**建议修 scan_front_v3.py 再复扫**（STRONG 正则改为容忍嵌套括号，如 `expect\((?:[^()]|\([^)]*\))*\)`；toBe 仅当参数为 null/undefined/boolean 时计弱；not.toHaveBeenCalled 单独归类）。
2. **`main.tray.test.ts:294` 时序契约不可验证**：声明的「锁调用在 whenReady 内」在现有 mock（立即 resolve）下无法区分调用阶段，测试名与断言能力不符——属「假契约名 + 冒烟断言」，改错位置仍绿。
3. **`main.tray.test.ts:362` / `main.window-controls.test.ts:500` 两个「空壳断言」块**：一个只验证 handler 注册后空调用，一个只验证 fetch 被调；块内均无行为/副作用断言，是 102 块中最接近「改逻辑仍绿」的两处（幸而套件内有互补用例）。

## 总体评级：**健康**（测试本体）

- 102 个命中块中 98 个为有效测试：绝大多数是「否定路径守卫（类型 4）」或「块内自带强断言（store 状态 toEqual/toBe、toast 内容、请求体值、DOM 回显/消失）」，符合 SDD 契约式测试惯例，`getByXxx` 存在性断言普遍与行为断言成对出现。
- 4 处需人工复核均为「可接受但可加强」级别，无一处达到「改被测逻辑后测试仍绿」的完全无效标准；真正的无效风险点不在这些块内，而在扫描器本身（误报淹没真实信号）。
- 建议动作：① 修复扫描脚本后复扫（预期命中数大幅下降）；② 按「需人工复核」4 处补强断言（均为一两行改动）；③ 将本结论登记入断言质量基线（可在 CI 中把扫描器作为弱断言候选提示器，而非门禁）。
