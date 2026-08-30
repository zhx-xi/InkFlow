# 设置页 — 交互规格

> 页面: settings | 路由: /settings（?cat=general|models|agent|templates|skills|account）| 组件: pages/settings.tsx
> 对应 design/GUI/settings/（官方简图 settings.html + settings-<state>.png，见后续补图）

## 1. 画面样式（简图/原型）

- 原型引用：design/GUI/settings/settings.html + settings-<state>.png（分类导航 / 常规面板 / 保存指示 / 模型分类 / 模板分类等状态截图）

> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：设置（页面标题）   主题 Select   语言 Select   窗口控制   │
├──────────┬───────────────────────────────────────────────────┤
│ 分类导航   │ 设置面板（滚动）                                 │
│ （192px） │ h1「设置」 + 保存指示器（保存中/已保存）           │
│ ▸ 常规    │ 外观卡片：主题三预览 / 背景 / 语言                │
│ ▸ 模型    │ 编辑器字体 / 关闭窗口时 / 首次托盘提示            │
│ ▸ Agent  │ 新章节默认字数 / 快捷键一览（5 组 kbd）            │
│ ▸ 模板    │ 知识图谱定时提取卡片（KnowledgeExtractCard）       │
│ ▸ 技能    │ MCP 接入面板（McpSettingsCard）                    │
│ ▸ 账户    │                                                   │
│ 激活项高亮│                                                   │
└──────────┴───────────────────────────────────────────────────┘
```
- 参考锚点（以真实组件为准：pages/settings.tsx + components/AppearanceCard、AgentChainCard、AgentList、GlobalDefaultModelCard、ModelsPanel、RagStatusCard、KnowledgeExtractCard、McpSettingsCard、SkillList、TemplateDialog；Agent/模板分类细节见 agent.md）：
  - 布局：全高 flex — 左 192px 分类导航（w-48，border-r，bg-surface-2，6 项带图标）+ 右滚动面板（标题 h1「设置」+ 面板内容，px-8）
  - 分类：常规（SlidersHorizontal）/ 模型（Cpu）/ Agent（Bot）/ 模板（FileText）/ 技能（BookOpen）/ 账户（UserRound）；激活项 bg-accent-weak + text-accent + aria-current=page，未激活 hover 高亮
  - URL 联动：分类切换写入 ?cat= 查询参数；外部进入 /settings?cat=agent 等直达对应分类（AppNav 快捷入口）
  - 保存指示器（#189）：面板顶部 h-4 文案行，idle 时 opacity-0 隐藏，保存中「保存中」text-ink-3，已保存「已保存」text-ok 约 2s 后自动隐藏
  - 常规面板（GeneralPanel）：AppearanceCard（三主题缩略预览 + 背景随主题过滤 + 语言切换）→ 编辑器字体 Select → 关闭窗口时 Select → 首次托盘提示 Switch → 新章节默认字数 number → 快捷键一览（5 组 kbd 只读）→ KnowledgeExtractCard → McpSettingsCard
  - 模型分类：GlobalDefaultModelCard + ModelsPanel（Provider 列表/模型表/角色绑定）+ RagStatusCard；技能分类：SkillList；账户分类：AccountPanel
  - 即改即存：所有设置项（Select/Switch/number）修改即触发保存，不经「保存按钮」；统一反馈走顶部保存指示器 + ok/err toast
- 布局说明：设置页为左导航右面板的标准设置布局，六分类经 URL cat 参数可直达。常规面板自上而下按「外观 → 编辑器 → 窗口行为 → 默认值 → 快捷键 → 扩展卡片」分组堆叠，每项独立即改即存，页面顶部提供全局保存状态指示。

## 2. 动作样式（按钮 × 状态表，逐控件）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 分类导航 | 6 项图标+文字列表，激活项高亮 | 切换分类 | — | 右侧面板切换 + URL ?cat= 同步 | — | URL cat 参数外部变化 → 同步激活分类；非法 cat → 回退 general |
| 保存指示器 | 隐藏（opacity-0） | 任意即改即存项触发 | 「保存中」text-ink-3 | 「已保存」text-ok 约 2s 后自动隐藏 | 回到隐藏，提示走 err toast | 多次保存重置 2s 计时器 |
| 外观卡片（主题） | 三主题缩略预览卡（paper/night/ink，底色+accent 圆点+文字标签） | 点选主题 | — | 主题直达生效（theme store 持久化） | — | 与顶栏主题 Select 双通道联动（改设置页后顶栏同步） |
| 外观卡片（背景） | Select，选项随主题过滤（BG_BY_THEME） | 选择背景 | — | 背景直达生效 | — | 切换主题后背景选项集刷新 |
| 外观卡片（语言） | Select（中/英） | 选择语言 | — | 语言直达生效（setLang） | — | 与顶栏语言 Select 双通道联动 |
| 编辑器字体 Select | serif/sans/mono 当前值 | 选择字体 | runImmediateSave saving | saved 指示 + 生效 | 回弹保持原值 + 提示 | setter 返回 Promise<boolean>，false 不回写 |
| 关闭窗口时 Select | tray（最小化到托盘）/ quit（退出） | 选择行为 | saving | saved 指示 + IPC 生效 | 回弹 + 提示 | 挂载时经 INKFLOW_API getCloseBehavior 回填 store |
| 首次托盘提示 Switch | checked=!trayHintDismissed（默认开） | 切换 | saving | saved 指示 + PATCH/IPC dismiss 链路 | 回弹 + 提示 | 关闭 = 不再提示托盘 |
| 新章节默认字数 | number 输入（项目级优先，无则全局/800000 兜底） | 输入停止 800ms 防抖自动保存；失焦 flush | 顶部保存指示 saving | saved 指示 + ok toast；项目级 → updateConfig PATCH，无当前项目 → PATCH 全局 settings | <1000 → err toast 不 PATCH；空/非法 → 静默不 PATCH；失败 err toast + dirty 保持 | 切项目重读并清 dirty（跨项目不保留草稿）；隐藏窗口/卸载时 flush；fetch 回写不覆盖用户输入中值 |
| 快捷键一览 | 只读列表（Ctrl+Z/Y/S/Enter/Shift+Enter 五组 kbd 样式） | — | — | — | — | 展示性控件，无交互 |
| 知识图谱定时提取卡片 | 三键回显数据源（全局设置快照 fetchSettings） | 修改定时配置 | saving | saved | 失败提示 | 数据源由常规面板单次 fetch 注入（避免卡片二次 GET） |
| MCP 接入面板 | MCP 服务配置列表 | 增删改配置 | 保存中 | 配置生效 | 失败 toast | 挂载于常规分类底部 |
| 模型分类（三卡） | GlobalDefaultModelCard + ModelsPanel + RagStatusCard | Provider CRUD / 模型多选批量测试 / 角色绑定 / RAG 状态查看 | 测试连接中 / 保存中 | 列表刷新 + 状态标记 | 测试失败行标红 + 原因 toast | 角色绑定区依赖 #107 agent-templates；API Key 加密存储 |
| 技能分类 | SkillList | 查看/启用技能 | — | — | — | 挂载于 skills 分类 |
| 账户分类 | AccountPanel | 账户信息查看/管理 | — | — | — | 挂载于 account 分类 |

## 3. 验收

- N1：六分类导航切换正确 + URL ?cat= 同步；外部 /settings?cat=agent 直达 Agent 分类；非法 cat 回退 general
- N2：即改即存项（字体/关闭行为/托盘提示/默认字数）修改即保存，顶部保存指示「保存中→已保存约 2s 隐藏」；失败回弹 + err toast
- N3：默认字数 <1000 → err toast 不 PATCH；无当前项目时走全局 settings PATCH；切项目重读并丢弃草稿
- N4：外观三主题/背景/语言直达生效，并与顶栏 Select 双通道联动
- N5：模型/技能/账户分类可正常进入与渲染（模型 CRUD 等细节按对应规格验收）
