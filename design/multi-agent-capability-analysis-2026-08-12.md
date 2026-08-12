# InkFlow 多 Agent 能力分析（Agent 差异化能力白名单）

**日期**: 2026-08-12
**状态**: 已分析（docs 登记），待拍板 Q0/Q1 后进入 spec 阶段
**依据**: 用户需求（2026-08-12）+ 代码现状核查（backend/src/inkflow）+ 既有拍板（Agent 模板引用式 F19、AI 自动化默认关闭显式开启、设定库随项目走）
**关联**: 功能 issue **F39（#258）/ F40（#259）/ F41（#260）**（0.9.0，多 Agent 能力一期拆 3 issue：后端核心 / skill 上传绑定 / 自定义 Agent 编辑）；升级路径 design/agent-upgrade-path-2026-08-03.md（F26-F30）

---

## 0. 结论摘要（TL;DR）

多 Agent 体系的**行为差异化不能只靠 system prompt 的概率性请求，必须靠"能力白名单"的确定性强制**——工具（function call）和 skill 按 Agent 过滤后再交付给 LLM。待决策点推荐：

| # | 决策点 | 推荐 | 理由 |
|---|--------|------|------|
| D1 | skill 绑定时机 | **上传时显式指定（默认不启用）+ 编辑页可改 + 「应用到全部 Agent」一键** | 上传动作当下是意图最清晰时刻；不违反「显式开启」铁律；杜绝幽灵注入 |
| D2 | 函数选择 UI | **分组 checkbox 列表**（描述 + 领域分组，>10 个加搜索） | 白名单是多选语义；内置 Agent 函数集锁定只读，自定义 Agent 可编辑 |
| D3 | 自定义函数 | ✅ **不做**（已确认） | 心智负担 > 收益；函数注册表是产品资产 |
| Q0 | Agent/skill 归属 | **全局定义（应用级）+ 项目引用**（待拍板） | 方法论跨项目复用；与「设定库随项目走」分层不冲突 |
| Q1 | 与现有模板关系 | **本期独立，二期 roles 扩展为 Agent 引用**（待拍板） | 避免一次大改双配置源 |

---

## 1. 问题与根源

**表面需求**：内置多 Agent 需要不同 function call 和 skills；用户上传 skill 可指定哪些 Agent 可用；自定义 Agent 可指定 skills 和 function call。

**根源问题**（三层）：
1. **行为一致性**（硬）— 只换 system prompt，LLM 工具调用会漂移：写作 Agent 可能去调审计工具、审校 Agent 可能想写正文。能力白名单把差异从「概率」变「确定」。
2. **可解释性**（软）— 用户上传 skill 后必须知道"它影响了谁"。默认全部可用 = 幽灵注入（Agent 行为莫名改变，用户无法归因）。
3. **心智负担控制**（硬约束，已拍板）— 不做自定义函数；UI 呈现必须「选配」而非「编程」。

## 2. 现状核查（2026-08-12 实证代码）

| 维度 | 现状 | 与本需求的差距 |
|------|------|----------------|
| 角色体系 | F4 四角色固定链（architect/writer/auditor/reviser），system prompt 代码内置（`pipeline_templates.py`） | 用户不可自定义 Agent、不可改 prompt |
| 模板 | F19 `AgentTemplate`：main_model / default_temperature / roles 四角色（仅 model/temperature/enabled 可配），项目引用式 | 模板管「用什么模型跑」，不管「Agent 是什么」 |
| 工具 | F26/F27：5 只读工具 + `save_draft`，deepagents harness 硬编码装配（`api/deps.py` → `build_agentic_writer`） | 工具集代码写死，无按 Agent 过滤 |
| skill | 代码仓 0 命中 | 全新概念 |
| 记忆 | F28 偏好学习（已交付） | 正交，不冲突 |

**关键结论**：F27 writer agent 的工具装配是硬编码的。多 Agent 化后，「装配逻辑」必须从代码变成**数据**（Agent 实体 + 白名单）。F26 工具注册表语义 + F27 agent_run 决策轨迹是零成本地基。

## 3. 需求拆解（产品角度）

**产品定位**：从「单 Agent 写作工具」向「多角色创作团队」演进。现有四角色链是**固定流水线**（F4），目标是**用户可调用的角色库**。

**功能形态三层递进**：

| 层 | 形态 | 价值 |
|----|------|------|
| L1 内置 Agent | 出厂 4-6 个（架构师/写手/审校员/修订师/世界观顾问/润色师…），每个带出厂工具白名单 + 出厂 skill | 开箱即用，差异化由产品保证 |
| L2 自定义 Agent | 从内置复制或空白创建：改 prompt + 选工具 + 选 skill | 高级用户个性化工作流 |
| L3 skill 上传 | 用户沉淀方法论，绑定到 Agent | 用户资产沉淀，产品护城河 |

**与现有模板的关系（Q1）**：模板管「模型/温度」（F19 引用式已拍板），Agent 管「能力边界」——两个正交维度。最佳演进：模板 `roles` 从「固定四角色」扩展为「任意 Agent 引用 + 模型/温度覆盖」。**本期解耦，二期扩展**，避免一次大改双配置源。

**D1 绑定时机的三个候选 + 推荐方案**：
- 默认全部可用 → 违反「AI 自动化默认关闭、显式开启」铁律（F13 timeline、F28 memory_learning 先例）；上传即污染所有 Agent，行为漂移无法归因
- 创建 Agent 时指定 → 创建时用户往往还不知道需要什么 skill，空列表 = 决策瘫痪
- 编辑页指定 → 灵活但可发现性差
- **推荐：上传 skill 时显式指定（默认不自动启用）+ 编辑页可改 + 「应用到全部」一键**。上传动作的当下是意图最清晰的时刻；「应用到全部」照顾全局诉求。

**D2 函数选择 UI**：函数是**多选白名单**，非单选。F26 现有 6 个工具时，**分组 checkbox 列表**（写作/检索/审计/项目分组 + 描述）比下拉直观；>10 个再加搜索。内置 Agent 函数集**出厂锁定（只读展示）**，自定义 Agent 才可编辑——避免「改坏了怎么恢复」的二次负担。

**D3 自定义函数：确认不做**。用户要的是「选配」不是「编程」；开放自定义函数会制造大量不可维护的残缺函数。

## 4. 用户角度分析

**三类用户 × 绑定时机体验**：

| 用户 | 画像 | 体验 |
|------|------|------|
| 新手创作者 | 不碰配置，直接用内置 Agent | 默认不启用 + 内置出厂配置齐全 = 零感知（正确） |
| 进阶用户 | 上传 skill、想差异化 | 上传时一步绑定，一次选择，比事后去编辑页找入口清晰 |
| 高级用户 | 精细调教 Agent | 编辑页双向视图：Agent 页看「我有哪些工具/skill」，skill 页看「被哪些 Agent 引用」 |

**心智负担审计**：
- ✅ 不做自定义函数——正确
- ⚠️ 上传 skill 的绑定 UI 不能是空表单——默认预选「常用 Agent」快捷勾选 + 可搜索列表
- ⚠️ 删除 skill 级联：被 N 个 Agent 引用 → 确认框（对齐模板删除确认拍板先例）
- **可解释性承诺**：任何 Agent 运行都应可见「本次用了哪些工具 + 哪些 skill」（复用 F27 agent_run 决策轨迹）

## 5. 架构师角度分析

### 5.1 数据模型（entity 归属先定）

```
Agent {                       # 全局定义（应用级），项目/模板引用
  id, name, description, icon,
  system_prompt,              # 内置 Agent 只读；自定义 Agent 可编辑
  tool_ids: [str],            # ← 能力白名单（引用内置函数注册表）
  skill_ids: [str],           # ← 能力白名单（引用 Skill 表）
  model_override, temperature_override,   # 与 RoleTemplate 语义对齐
  builtin: bool, source: str
}
Skill {
  id, name, description, content(md),     # frontmatter + markdown
  source: builtin | user_upload,
  agent_ids: [str]                        # 反查用（删除保护）
}
```

**归属决策（Q0）**：Agent 全局（应用级，跨项目复用——「我的润色 Agent」不该每个项目重建）；skill 建议也全局——skill 是「方法论」而非「项目数据」，与「设定库随项目走」（角色/世界观=项目数据）不同层不冲突。项目差异通过项目配置选择 Agent 实现。

### 5.2 能力边界强制（核心架构不变式）

```
运行时装配（deps.py 现行逻辑的升级版）：
1. 按 agent.tool_ids 过滤工具注册表 → 只 bind 白名单内工具到 harness
2. 按 agent.skill_ids 过滤 skill 库 → 只拼白名单 skill 内容进 system prompt
3. 白名单外的一切对 LLM 不可见 → 行为差异 = 确定性，非概率
```

不是「请求 LLM 遵守」，是「只给 LLM 白名单内的东西」——与 deepagents harness 的 `tools` 参数天然契合（现有 `build_agentic_writer` 装配点即改造位）。

### 5.3 风险与边界

| 风险 | 等级 | 缓解 |
|------|------|------|
| skill 上传 = prompt injection 面扩大 | 🟡 中 | 本地单用户工具（风险自担）；skill 内容 UI 可预览；内置 Agent 出厂 prompt 与用户 skill 优先级明确（skill 追加在用户 prompt 之后） |
| skill 删除 → 引用 Agent 悬空 | 🟡 中 | 删除保护：被引用 → 确认框 + 列出影响 Agent（模板删除先例）；或软删除 |
| 白名单语义漂移（工具改名/下线） | 🟢 低 | 工具注册表唯一真源，Agent 存 id 引用；下线工具在编辑页置灰提示 |
| 模板 × Agent 双配置源混乱 | 🟡 中 | 阶段化：本期 Agent 独立于模板，模板扩展放二期 |

## 6. 演进路径

```
阶段 1（F39-F41 一期，拆 3 issue）：Agent 实体 + Skill 实体落库（全局）
              ├─ 内置 Agent 出厂配置（prompt + 工具白名单 + 出厂 skill）
              ├─ 工具注册表 → 按 Agent 白名单装配（改造 deps.py 装配点）
              ├─ skill 上传（frontmatter + markdown）+ 绑定 UI（上传时指定）
              └─ 自定义 Agent 创建/编辑（prompt 编辑 + 工具 checkbox + skill 绑定）
阶段 2：AgentTemplate.roles 扩展为任意 Agent 引用（模型/温度覆盖保留）→ 模板 = 「选哪些 Agent + 用什么模型跑」
阶段 3：F29 Supervisor 按 Agent 库自主调度（远期，与记忆系统联动）
```

## 7. 待拍板项（进入 spec 前）

- Q0：Agent / skill 归属 = 全局定义 + 项目引用？（推荐：是）
- Q1：本期与 AgentTemplate 解耦、二期 roles 扩展？（推荐：是）
- D1/D2/D3 按推荐方案确认（D3 已确认不做）

## 8. 依赖与估算（F39-F41 一期）

- 依赖：F26（工具注册表，已交付 ✅）、F27（agent_run 轨迹，已交付 ✅）、F19（模板实体模式参照，已交付 ✅）
- 拆分（2026-08-12 用户确认拆 3 issue）：F39 后端核心 5-7 人天（无 UI，CLI 验证）→ F40 skill 上传绑定 2-3 人天、F41 自定义 Agent 编辑 3-5 人天（均依赖 F39，可并行）
- 里程碑：0.9.0（0.8.0 已有 F29 #161 / CLI 补全 #251 / 删除语义 #211，一期放不下）
