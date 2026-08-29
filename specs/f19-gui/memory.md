# 记忆页 — 交互规格

> 页面: memory | 路由: /memory | 组件: frontend/packages/renderer/src/pages/memory.tsx（MemoryPage，nav 项 memory，lucide Brain 图标）
> 对应 design/GUI/memory/（官方简图 memory.html + memory-<state>.png，见后续补图；当前目录仅 .gitkeep 占位）

## 1. 画面样式

- 原型引用：design/GUI/memory/memory.html + memory-<state>.png（后续补图，目录已建）
- 参考锚点（以真实组件 pages/memory.tsx 为准，#486 记忆页 + #521 手动添加/编辑 + #546 提取反馈 + #658 统计概览 + #F49 删除总结/被覆盖标记）：
  - 页面骨架：max-w-[1080px] 居中容器，标题「记忆」
  - 无项目空态：「请先创建或选择项目」+「前往项目页」按钮（跳 /projects），不发任何请求
  - 项目选择器：label「项目」+ Radix Select（w-56），切换项目重拉项目级数据
  - 统计概览（#658）：4 张数字卡（记忆总量/项目偏好/用户偏好/语义总结）+「Agent 行为」5 张卡（章节/直接确认/修改率/重写率/平均改动字数）；统计失败静默降级「概览暂不可用」
  - 动作行：主按钮「提取记忆」+ 次按钮「添加记忆」+ 提取中提示
  - 语义总结区块：项目级总结卡片（内容 + 展开/收起 + meta「model · updated_at」+ 删除按钮）+ 用户级总结块
  - 项目偏好 / 用户级偏好两个列表区块：行内 分类徽标 + count + confidence +（用户级 project_count）+ pattern → value + 被覆盖标记 + 编辑/删除按钮
  - 添加/编辑弹窗（memory-add-form）：作用域 Select（新增态）+ 分类 Select + 模式输入 + 偏好值输入 + 保存/取消
- 布局说明：
  - 顶部：h1「记忆」
  - 项目选择（mt-6）：label + Select
  - 统计概览（mt-8）：2/4/6 列响应式网格；Agent 行为子区
  - 动作行（mt-4）：提取记忆（accent）/ 添加记忆（outline）/ 提取中文案
  - 语义总结（mt-8）、项目偏好（mt-10）、用户级偏好（mt-10）三区块纵向排列
  - 弹窗：固定遮罩 bg-black/30 居中，w-[420px] 圆角卡片，aria-modal

## 2. 动作样式（按钮 × 状态表，逐控件）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 项目选择器（memory-project-select） | 当前项目（无则 placeholder「项目」） | 展开项目列表 | — | setPid → 重拉 总结/项目偏好/用户偏好/统计 | 加载失败 → err toast（统计除外） | 无项目态不发任何请求；统计 fetch 独立失败仅置「概览暂不可用」，不弹 toast 不阻断页面 |
| 提取记忆（memory-extract-btn） | accent「提取记忆」 | summarizeMemory(pid, force=true) | disabled（opacity-60）+ 旁显「提取中…」 | summarized=true → ok toast「记忆提取完成」；false → warn toast「暂无可提取的记忆内容」；两者都重拉总结 | 内联红块「提取失败，请检查模型配置：{原因}」（不走 toast） | extracting 期间防重复点击；失败后按钮恢复可点 |
| 添加记忆（memory-add-btn） | outline「添加记忆」 | 打开 memory-add-form 弹窗（新增态） | — | — | — | 弹窗打开期间重复点击无副作用 |
| 弹窗「保存」（memory-add-submit） | accent「保存」 | 新增：createProjectPreference / createUserPreference；编辑：updateProjectPreference / updateUserPreference | — | 关闭弹窗 + 清空表单 + 列表更新（新增追加行 / 编辑更新原行） | err toast「原因」，弹窗保持 | 编辑态作用域固定不可切换；项目级保存需 pid 已选 |
| 弹窗「取消」（memory-add-cancel） | outline「取消」 | 关闭弹窗 + 清空 pattern/value + 退出编辑态 | — | 无任何 API 调用 | — | Esc 键等效（document keydown，尊重 Radix Select 已 preventDefault 的 Escape）；遮罩点击不关闭 |
| 弹窗作用域 Select（memory-add-scope） | 默认「项目级」 | 切换「项目级/全局级」 | — | scope=全局级 → 显示提示「用户级偏好会影响所有项目的写作上下文」 | — | 仅新增态渲染；编辑态隐藏 |
| 弹窗分类 Select（memory-add-category） | 默认「称呼」 | 展开 称呼/用词/结构/其他 | — | 选择即生效 | — | category 四枚举：addressing/style_word/structure/other |
| 总结展开/收起（memory-summary-expand） | 仅内容 >200 字符时渲染「展开」 | toggle 展开 | — | 全文显示 / 收起回 line-clamp-3 | — | ≤200 字符不渲染按钮 |
| 总结删除（memory-summary-delete） | 仅项目级总结存在时渲染（outline hover 红） | removeMemorySummary(pid) | — | 重拉总结 → 卡片消失（project/user 均空 → 空态）+ ok toast「已删除语义总结」 | err toast，卡片仍在 | 删除用户级总结无入口（仅项目级） |
| 偏好编辑（memory-pref-edit / memory-userpref-edit） | 行内 outline「编辑」 | 打开弹窗并预填 category/pattern/value（编辑态） | — | 保存 → update 原行替换 | — | 编辑态下 scope Select 隐藏、作用域固定 |
| 偏好删除（memory-pref-del / memory-userpref-del） | 行内 outline「删除」（hover 红） | removeProjectPreference / removeUserPreference | — | 该行从列表移除（无确认框） | err toast，行仍在 | 无二次确认；删除后不可撤销 |
| 被覆盖标记 | superseded_by 非空时渲染「被覆盖」徽标 + 取代者 id | 只读展示 | — | — | — | superseded_by 为空串 → 不渲染 |

## 3. 验收

- N1：无项目态显示「请先创建或选择项目」+ 前往项目页按钮，且不发任何请求
- N2：有项目态并行加载 总结/项目偏好/用户偏好/统计；切换项目重拉项目级数据；统计失败仅降级「概览暂不可用」不弹 toast
- N3：提取记忆三态：成功（summarized=true → ok toast）/ 无内容（warn toast）/ 失败（内联错误块）；提取中按钮禁用防重复
- N4：添加/编辑偏好双作用域：新增走 create、编辑走 update 且作用域固定；保存成功关弹窗清表单，取消/Esc 关闭且不调 API
- N5：偏好删除无确认框直接移除行，失败 err toast 行保留；被覆盖标记（superseded_by）按数据渲染
- N6：语义总结卡片长文可展开/收起；删除总结直接执行，成功重拉至空态 + ok toast，失败卡片仍在
- N7：统计概览数字卡与 Agent 行为卡齐全（记忆总量/项目偏好/用户偏好/总结数/章节/直接确认/修改率/重写率/平均改动字数）
