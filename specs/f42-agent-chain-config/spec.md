# F42: Agent 链配置驱动编排（agent-chain-config）功能规格

**Spec 版本**: 1.5（#484 链动态化 + 模板联动，2026-08-19）
**日期**: 2026-08-12
**依据**: 0.8.0 路线图拍板记录 5-9（design/inkflow-0-8-0-roadmap-2026-08-12.md）+ Issue #268（Agent 链模型选择）+ Issue #269（Agent 执行顺序编辑）+ #225 三态语义（已合入）+ F26/F27 已合入实现源码核查 + 2026-08-12 用户拍板（Q1-Q3 + 执行节点 10 槽 + 评审修正 B1/B2/自定义 Agent 0.8.0）+ #484（Agent 链动态化 + 模板联动，D5，2026-08-19 拍板）+ #473 角色单一来源（PR #492 已合入）
**所属阶段**: 0.8.0（轨道 B Agent 编排：F42 spec → #268 → #269 → #161 F29），估算 8-14 人天（#268 前端 2-3 + #269 前后端 3-6 + GUI 写作管线化与自定义 Agent 数据面 3-5，拆 issue）；#484 链动态化为 0.10.1 增量（估算 5-8 人天，S2 实现轨）
**关联 Issues**: #268（模型选择，W2 启动）、#269（执行顺序，W3，🔗#268）、#270（关联关系编辑，0.9.0 预留，不实现）、#484（Agent 链动态化 + 模板联动，0.10.1，本 v1.5 修订）
**依赖**: ✅ #225 三态语义（0.7.0 已合入）· ✅ F26 deepagents 集成层（PR #236 已合入）· ✅ F27 agentic writer（已合入）· ✅ F9/F13/F34 服务（工具包装对象）· ✅ #473 角色单一来源（PR #492 已合入，role_key 映射真源）· ⏳ #251 CLI project update（0.8.0 P1，agent_order CLI 读写联动）· ⏳ #268 先于 #269（编排域串行）
**参考 ADR**: [adr/ADR-035.md](../adr/ADR-035.md)（编排引擎=Deep Agents harness 0.7.5，原字母 ADR-E，#283 已落盘）、ADR-015（LangChain 隔离）、ADR-019（编号口径）
**状态**: ✅ 已实现（PR #299/#305/#308/#309/#315/#314，2026-08-13）

> **Spec 变更**（v1.4 → v1.5，2026-08-19，#484 链动态化 + 模板联动）：Agent 链从「固定 4 位置」动态化为「6 内置皆可进链 + 自定义 Agent 可进链 + 模板引用任意角色组合」。修订背景：#473 角色单一来源（PR #492）已合入——后端 6 内置 Agent 暴露 `role_key` 映射（架构师=architect/写手=writer/审校员=auditor/修订师=reviser；世界观顾问/润色师=null），前端 AgentChainCard 内置行已从 `/api/v1/agents` 真源派生。本修订在此之上把「链角色集合」从真源完全派生：① **role_key 全集 4→6**（世界观顾问=`worldview`、润色师=`polisher`，§5.7.1）；② **链增/删/改角色**（不再固定 4 位置，UI 从角色池选择进链/移除，§5.7.3）；③ **自定义 Agent 进链**（Agent 管理创建的自定义角色可进链，prompt 真源 = AgentEntity.system_prompt，§5.7.2/§5.7.4）；④ **模板引用任意角色组合**（TemplateDialog 4 键硬编码 → 从真源派生角色列表，§5.7.5）；⑤ 执行层 stage 构造扩展（6 内置 prompt 从 Agent 真源取，不再只依赖内置模板 4 角色 stage，§5.7.4）。正文修订位置：§1.1/§1.3/§2.1/§2.3/§5.3.4/§5.7（新增）/§7/§8/§9/§10/§11/§12/§13。

> **Spec 变更**（v1.3 → v1.4，2026-08-16，#270 DAG 预留承接）：§5.4 从「#270 DAG 扩展预留（本模块不实现）」改为「#270 由 F46 DAG 编排 spec 承接（0.9.0）」，引用 `specs/f46-dag-orchestration/spec.md`。修订背景：F46 spec v1.0 已起草（2026-08-16，#270 唯一真相来源），原预留的演进约束（层级=拓扑层特化 / 执行链设计 / 配置模型兼容 / 真禁用 / 并行语义）已由 F46 spec 落地为 `agent_relations`（`list[{from,to,type}]`）+ 三类型语义（sequential/data/conditional）+ 拓扑合成（基线 + 叠加，关系优先）+ 条件分支（`add_conditional_edges` gate）。本模块 §5.4 不再承担「预留」职责，改为「承接引用」，避免双份真相漂移。

> **Spec 变更**（v1.2 → v1.3，2026-08-12，三角色评审修正）：基于 code-reviewer/QA/requirements-analyst 三角色评审（2026-08-12 委派，findings 见待澄清区），用户拍板三项修正。① **B1 默认模板兼容模式**（评审 F1）：`agent_order` 空 = 默认模板模式——`agent_*` null **不触发真禁用**（跟随模板默认，v1.0 语义，解决默认项目全空转矛盾）；`agent_order` 非空 = 配置驱动模式——null 真禁用；前端关闭角色时同步从 `agent_order` 移除（§2.1/§2.2/§5.3.1）。② **B2 GUI 写作管线化**（评审 🔴-3/R5）：GUI 写作入口切换到多角色管线，新增两个默认管线模板——`builtin:write_auto`（全自动新章节）与 `builtin:write_continue`（续写），提示词按场景独立编写（§5.6）；#268/#269 验收「写作流程按指定模型/新顺序执行」在 GUI 主路径可达；F27 agentic 保持独立入口（§1.3 边界）。③ **自定义 Agent 链路 0.8.0 实现**（评审 F2/🔴-2）：RoleTemplate 扩展 prompt/name + ProjectConfig 自定义角色字段 + UI 入口，里程碑内拆多个 issue（§5.3.4/§10/§13）。④ 评审实现契约修正：装配顺序统一（F3/R6）、reviser 模板数据修正 + 占位符全集校验（F4）、`.get` 防御 + 注入键集=占位符扫描（F5/R3）、存量裸名迁移策略（F6）、成品身份定义（🔴-1）、既有测试变更清单（R1）、并行断言 mock 契约（R2）、槽位 UI 口径统一 0-9（R4/🟡-4）、估算 5-9 → **8-14 人天**（B2 模板+入口改造 +3-5）。

> **Spec 变更**（v1.1 → v1.2，2026-08-12）：用户补充拍板「执行节点仍限 4 内置，这个修改一下——默认有 10 个数字从 0-9，默认模板中 agent 就是 0-3」。① **执行槽位 = 10 个编号（0-9）**：`agent_order` 层级索引即编号（长度 ≤10，空层=空槽允许），默认模板占槽 0-3（architect=0/writer=1/auditor=2/reviser=3），槽 4-9 预留自定义 Agent；② **自定义 Agent 执行解锁**：执行节点从 4 具名白名单（_NODE_MAP）改为**通用节点**（任意 stage.id 可执行，upstream_keys 从 `stage.input_from` 推导——顺带修复 v1.1 漏洞：具名节点硬编码 upstream 与重排拓扑脱节）；自定义角色 prompt 由 AgentTemplate.roles 提供（_merge_role_configs 既有装配，§5.3.4）；③ 边界声明与 §10 同步更新（「执行节点限 4」→「执行槽位 0-9」；自定义 Agent 执行从 0.9.0 提前入本模块）。

> **Spec 变更**（v1.0 → v1.1，2026-08-12）：待澄清 Q1-Q3 全部拍板确认，正文按拍板结果修订。① **Q1 = 层级自由排序**：`agent_order` 从 `list[str]` 升级为**层级嵌套 `list[list[str]]`**（层 = 序号，同层角色**并行执行**，层间串行）——用户拍板「1、2、3、4 顺序 + 相同顺序可并行」；执行引擎从单链升级为**分层并行拓扑**（validate/execute 放宽多入口/多终点，§5.3）；prompt 变量注入改为**前序全层 + 未执行空注入**（消除字面量残留，§5.3.3）；agent_order 数据模型支持任意角色名（自定义 Agent 铺路，执行节点限 4 内置，§5.3.4）。② **Q2 = 真禁用**：null → 管线跳过该角色（边重连），下游空输入降级运行；agent_order 校验口径 = 必须含全部**启用**角色（§2.3）；成本修正 +1-2 人天（空注入机制既有，pipeline_nodes L55 实证）。③ **Q3 = 格式统一**：`agent_*`/`config.model` 全链路强制 `provider/model` 格式；修复 `config.model` 默认裸名（"gpt-4o"）与 AgentPanel 硬编码 Select 两个不合规消费点；模型选择数据源 = provider-configs chat 模型列表（§5.2）；`config.model` 消费链实证：extraction_service L670/717 作为 default_model 消费（§11）。④ 参考 ADR-E → 正式路径 adr/ADR-035.md（#283 收尾，#289 已落盘）。

> **模块类型声明**: 本模块为「配置驱动编排型」变体——无新实体表、无新业务端点；在既有 Agent 管线（LangGraphAgentPipeline 四角色链）上增加**配置驱动**能力：① 三态模型选择补全 UI 与执行层解析（#268）；② 执行拓扑由模板硬编码改为 `agent_order` **层级配置驱动**（#269，层级=拓扑层特化，为 #270 DAG 铺路）；③ 预留 #270 DAG 关联关系扩展边界（0.9.0，不实现）。编号依据：AGENTS.md 模块类型谱系口径下，F42 为 Agent 化升级链（F26-F29）的配置面补全模块，与 F26（集成层）/F27（闭环）/F28（记忆）平行不冲突。

---

## 1. 概述

F42 合并覆盖 **#268（Agent 链模型选择）** 与 **#269（Agent 执行顺序编辑）** 两份 issue，作为两期实现的唯一真相来源。#270（关联关系编辑）仅作边界预留，不实现。

### 1.1 现状缺口（2026-08-12 源码实证）

| # | 缺口 | 实证 | 归属 |
|---|------|------|------|
| ① | AgentChainCard 打开角色**不能选择模型**——只能写入 sentinel `__default__`（跟随默认） | `frontend/packages/renderer/src/components/AgentChainCard.tsx` L66 注释「本期无模型选择 UI」；L59 打开恒写 `AGENT_DEFAULT_SENTINEL` | #268 |
| ② | 默认模型 Select 硬编码 `['openai','deepseek','ollama']`（provider 名，非模型名）→ 写入 `config.model` 的 `'openai'` 无 `/`，**违反 parse_model_string 硬契约** | `pages/settings.tsx` L433-437 + `provider_config.py` L207-211（无 `/` 抛 ValueError）+ `config.model` 消费链实证（extraction_service L670/717 default_model） | #268 |
| ③ | **执行层 sentinel 缺陷**：`__default__` 会被当作模型名覆盖模板模型 → `llm.chat(model="__default__")` → `parse_model_string("__default__")` 无 `/` 抛 ValueError → 管线失败 | `agent_service.py` L232-234 `if project_model:`（非空即覆盖）+ `pipeline_nodes.py` L91 `model=stage.agent.model` + `provider_config.py` L207-211 | #268（必须修） |
| ④ | 执行拓扑**模板硬编码**：builtin:write_chapter 四阶段链边 architect→writer→auditor→reviser，用户无法调整 | `infrastructure/agent/pipeline_templates.py` L65-89（stages 手写 input_from/output_to） | #269 |
| ⑤ | 无 `agent_order` 配置字段；执行引擎为**单链拓扑**（validate 强制唯一入口/唯一终点，L57-62）——不支持并行层 | `domain/models/project.py` ProjectConfig + `langgraph_pipeline.py` L57-62 | #269 |
| ⑥ | **执行层无角色跳过逻辑**：「关闭」（null）角色照常参与管线，「关闭」与「跟随默认」执行等价 | `agent_service.py` `_merge_role_configs` 无过滤 + 模板恒 4 阶段 | #269（Q2 拍板后修） |
| ⑦ | **prompt 变量字面量残留风险**：`_render` 对未知占位符原样保留（L44）；`_build_messages` 只注入直接上游输出（L58-59）——任意重排后非上游变量以字面量残留进 system prompt | `pipeline_nodes.py` L39-68 | #269（Q1 拍板后修） |
| ⑧ | CLI 无法读写项目 config（无 `project update` 命令） | `cli/commands/project.py` 仅 create/list/get/delete/restore | #269（#251 联动） |
| ⑨ | **6 内置仅 4 个有 role_key**：世界观顾问/润色师 role_key=None → 前端按 role_key 派生时这两角色**无行可渲染**，进不了链 | `agent_entity_service.py` BUILTIN_AGENT_SPECS（世界观顾问/润色师 `role_key: None`，L65-119）+ `AgentChainCard.tsx` L127-135（`agents.find(a => a.builtin && a.role_key === roleKey)`，None 找不到 → filter 掉） | #484（v1.5） |
| ⑩ | **前端 3 处 4 角色硬编码**（与 #473 真源派生并存）：链、依赖关系编辑器、模板编辑均固定 4 键，不随 Agent 管理增减 | `AgentChainCard.tsx` L19/L21 `BUILTIN_ROLE_KEYS`/`BUILTIN_FIELDS`（4 键）+ `AgentRelationEditor.tsx` L16 `ROLE_FIELDS`（4 键）+ `TemplateDialog.tsx` L10 `ROLES = ['architect','writer','auditor','reviser']`（4 键） | #484（v1.5） |
| ⑪ | **模板 roles 前端契约仍 4 键**：AgentTemplateInput.roles 类型 4 键（architect/writer/auditor/reviser）——自定义键虽可追加但无 UI 入口，模板无法引用任意角色组合 | `stores/templates.ts` `AgentTemplateInput.roles`（4 键契约注释）+ `TemplateDialog.tsx` L10-24（roles state 固定 4 键初始化） | #484（v1.5） |

### 1.2 与样板差异

非 F9 实体 CRUD（无新增表）、非 F26 集成型（无新基础设施包）、非 F27 闭环型（无新业务流程）——本模块是**配置面 + 编排面改造**：后端 ProjectConfig 扩展 1 字段 + 执行链拓扑重构（单链 → 分层并行）；前端 AgentChainCard 交互升级（模型选择 + 层级序号）。

### 1.3 边界声明

- **不含** #270 关联关系编辑（`agent_relations`，0.9.0）：本模块实现**层级顺序**（层间串行 + 层内并行 = DAG 拓扑层特化），关系增强语义（同层内条件/分支边）留给 0.9.0。配置模型与执行链设计**不得堵死** DAG 演进（§5.4 演进约束）。
- **不含** F29 Supervisor 自主编排（#161，0.8.0 W5）：supervisor 消费 deepagents subagent 机制，与本模块的 agent_order 管线编排不同域（§11 依赖关系）。
- **不含** F27 agentic 写作路径的多角色化：F27 AgenticWriterService 为 deepagents 单 agent（writer_agent）ReAct 循环，`model=config.llm_default_model`（全局默认，`api/deps.py` L220-240）——**不消费** `agent_*` 四角色字段与 `agent_order`（§5.5 兼容性结论）。
- **执行槽位 = 10 个编号（0-9，v1.2 拍板）**：执行节点**不再限 4 内置**——任意角色名可执行（通用节点 + upstream 从 input_from 推导，§5.3.2）；默认模板占槽 0-3（architect/writer/auditor/reviser），槽 4-9 预留自定义 Agent；自定义角色 prompt 由 AgentTemplate.roles 提供（§5.3.4）。多 Agent 能力差异化白名单（#257）仍归 0.9.0 F39-F41。
- **链角色集合动态化（v1.5 #484 拍板）**：链不再固定 4 位置——**6 内置角色（含世界观顾问/润色师）+ 自定义 Agent 皆可进链**；角色集合真源 = `/api/v1/agents`（Agent 管理，含 role_key 映射），前端从真源派生而非硬编码（§5.7）。默认拓扑仍为 4 角色链（architect→writer→auditor→reviser，零迁移），用户可增/删/改角色组成自定义链。
- **GUI 写作入口管线化（v1.3 拍板 B2）**：GUI 写作「全自动生成 / 续写」入口切换到**多角色管线**（新增 `builtin:write_auto` / `builtin:write_continue` 两个默认模板，§5.6）——`agent_order`/`agent_*` 在 GUI 主路径生效，#268/#269 验收可达。**F27 agentic（工具型单 agent）保持独立入口**（能力不同：工具循环 vs 角色链），不在本模块改造范围；F3 writing_service 单模型路径逐步被管线模板替代（保留兼容，§5.6 边界）。

---

## 2. 数据模型

### 2.1 ProjectConfig 扩展（`domain/models/project.py` MODIFY）

```python
class ProjectConfig(BaseModel):
    # ...既有字段不变（model/agent_*/temperature/role_*_temperature/template_id/writing_style/default_words/extra）

    agent_order: list[list[str]] = Field(default_factory=list)
    """Agent 链执行拓扑 — 层级嵌套数组（v1.1 拍板：同层并行；v1.2 拍板：槽位编号 0-9）。

    - **外层索引 = 槽位编号（0-9，共 10 个数字，v1.2 拍板）**——索引 0 先执行，逐层串行
    - 内层 = 同槽位（同编号）并行角色字段名数组（agent_architect 等）
    - 示例: [["agent_architect"], ["agent_writer", "agent_auditor"], ["agent_reviser"]]
            = 槽 0 架构规划 → 槽 1 写作+审阅并行 → 槽 2 修订
    - **默认模板 = 槽 0-3**（architect=0/writer=1/auditor=2/reviser=3）；槽 4-9 预留自定义 Agent
    - 空层（[]）= 空槽（该编号无角色，跳过）——允许跳号（如只用 0/1/2/3/9）
    - 长度上限 10（编号 0-9）；空列表 = 未配置 → 默认拓扑 [[architect],[writer],[auditor],[reviser]]
    - **双模式（v1.3 拍板 B1）**：空列表 = **默认模板模式**——`agent_*` null **不触发真禁用**（跟随模板默认，v1.0 语义）；非空 = **配置驱动模式**——null 真禁用（§2.2）
    - 角色名支持任意字符串（自定义 Agent，v1.2 执行解锁 + v1.3 数据面 §5.3.4）
    - **角色集合（v1.5 #484）**：6 内置 role_key（architect/writer/auditor/reviser/worldview/polisher，§5.7.1）+ 自定义 Agent（Agent 管理创建，role_key 由服务分配，§5.7.2）——前端从 `/api/v1/agents` 真源派生，不硬编码
    """

    @field_validator("agent_order")
    @classmethod
    def validate_agent_order(cls, v: list[list[str]]) -> list[list[str]]:
        """存储层校验：结构 + 去重 + 长度上限（语义校验在 API 层与执行层，§2.3）。

        - 长度 ≤ 10（槽位编号 0-9）
        - 每层为非空字符串列表；空层（[]）= 空槽，允许
        - 元素跨层全局去重（同角色出现两次拒绝，防歧义）
        """
        if len(v) > 10:
            raise ValueError("agent_order 最多 10 层（槽位编号 0-9）")
        seen: set[str] = set()
        result: list[list[str]] = []
        for layer in v:
            if not isinstance(layer, list):
                raise ValueError("agent_order 每层必须为数组")
            layer_items: list[str] = []
            for item in layer:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError("agent_order 元素必须为非空字符串")
                stripped = item.strip()
                if stripped in seen:
                    raise ValueError(f"agent_order 角色重复: {stripped}")
                seen.add(stripped)
                layer_items.append(stripped)
            result.append(layer_items)
        return result
```

- **字段命名口径**：`agent_order` 存**角色字段名**（`agent_architect` 等，带 `agent_` 前缀），与 issue #269 方案一致；内部 stage.id 为不带前缀的角色名（`architect` 等）——执行层转换映射：`agent_xxx → xxx`（§5.3）。
- **默认值**：`default_factory=list`（空 = 模板默认拓扑）——**零迁移**：旧项目 config JSON 无此键 → Pydantic 默认空列表；GUI 显示默认拓扑（Architect → Writer/Auditor/Reviser 四层链）。
- **v1.0 → v1.1 结构变更**：`list[str]` → `list[list[str]]`（Q1 拍板：层级 = 序号 + 同层并行）。尚未实现（v1.0 无代码合入），无存量数据兼容问题。

### 2.2 三态语义（#268，#225 语义 + Q2 拍板扩展）

| agent_* 值 | 语义 | 执行层行为 | UI |
|------------|------|-----------|-----|
| `null`（缺失） | **关闭（Q2 拍板：真禁用；v1.3 B1 双模式限定）** | **默认模板模式**（agent_order 空）：不覆盖模板模型，角色照常执行（v1.0 语义）；**配置驱动模式**（agent_order 非空）：**跳过该角色**——不执行；下游角色以空输入降级运行（复用 pipeline_nodes L55 空注入机制）；从执行拓扑摘除（§5.3.1） | Switch off |
| `"__default__"`（AGENT_DEFAULT_SENTINEL） | 跟随默认 | **修复点**：不覆盖模板角色模型（v1.0 缺陷会 ValueError，§5.1） | Switch on + Select 选中「跟随默认」 |
| `"<provider>/<model>"`（如 `"zhipu/glm-4.5"`） | 指定模型 | 覆盖模板角色模型（parse_model_string 剥离前缀后调用） | Switch on + Select 选中具体模型 |

> **双模式一致性规则（v1.3 B1）**：前端关闭角色时**同步从 `agent_order` 移除**该角色（保持「配置驱动模式」与「开关」一致）——即关闭动作 = ① agent_* → null ② agent_order 剔除该角色；开启动作 = ① agent_* → sentinel/模型 ② agent_order 加入对应槽位。后端校验「必须含全部启用角色」在配置驱动模式下执行；默认模板模式下不校验（无 agent_order 语义）。

> 存储格式说明（Q3 拍板）：`agent_*` 与 `config.model` 具体模型值**全链路强制 `provider/model` 格式**（与 `ProviderConfig.default_model` 同格式、与 `parse_model_string` 解析契约一致）——不允许存裸模型名/裸 provider 名（无 `/` 会在执行层 ValueError，实证：extraction_service L670/717 default_model 消费链）。

### 2.3 agent_order 校验（双层 + 启用角色口径）

| 层 | 行为 | 位置 |
|----|------|------|
| 存储层（Pydantic） | 结构 + 跨层去重 + 长度 ≤10（§2.1） | `domain/models/project.py` |
| API 层（PATCH） | 语义校验：非法 → **422**（detail 中文说明）；非法定义 = ① 跨层重复（存储层已拒，防御）② **不含全部启用角色**（Q2 拍板口径：启用 = agent_* 非 null；关闭角色可不出现在 agent_order）——**角色名任意**（内置 6 + 自定义均可，v1.2 + v1.5） | `api/routers/project.py`（或 `project_service.py`，实现确认） |
| 执行层（防御） | 任何非法（含存量数据手工损坏）→ **回退默认拓扑**，记 warning 日志；自定义角色 system_prompt 缺失（非内置且模板 roles 未定义）→ 跳过 + warning（§5.3.4）；永不抛错中断管线 | `agent_service.py` |

> 验收锚点「agent_order 缺省/非法时回退默认顺序（零迁移）」（#269）由**执行层回退**保证——API 层 422 是输入卫生，执行层回退是数据防御，两层并存。
> **关闭角色语义**（Q2 拍板）：关闭角色（null）**不要求**出现在 agent_order 中；若出现（用户调序时保留），执行层仍跳过（null 优先于拓扑）。

### 2.4 决策论证

| 决策 | 方案 | 理由 |
|------|------|------|
| agent_order 结构 | **层级嵌套 `list[list[str]]`（Q1 拍板）** | 用户拍板「1、2、3、4 序号 + 同序并行」；外层=层序、内层=并行组，与心智一致；层级 = DAG 拓扑层特化，为 #270 铺路；`list[str]` 无法表达并行 |
| 槽位编号 | **索引 = 0-9（v1.2 拍板：10 个数字，默认模板 0-3）** | 用户拍板「默认有 10 个数字从 0-9，默认模板中 agent 就是 0-3」；长度 ≤10 + 空槽允许（跳号）；槽 4-9 预留自定义 Agent |
| null 关闭语义 | **真禁用（Q2 拍板）** | 兑现 UI「关闭」承诺（v1.0 执行层照跑是 #225 遗留语义缺口）；三态在真禁用下才有区分；跳过 = DAG 节点摘除（#270 子集）；成本修正 +1-2 人天（空注入机制既有） |
| 模型格式 | **全链路 provider/model（Q3 拍板）** | parse_model_string 硬契约（无 `/` ValueError）；config.model 消费链实证（extraction_service default_model）；「跟随默认」回退链依赖格式合规 |
| 变量注入 | 前序全层注入 + 未执行空注入（§5.3.3） | 消除字面量残留（_render L44 实证）；任意引用有值（空或实际）；软降级 = 用户自由排序的代价 |
| 执行引擎 | 单链 → **分层并行拓扑**（validate/execute 放宽） | 层级模型要求多入口/多终点；LangGraph StateGraph 支持多 START/END 边；环检测/引用存在性校验保留 |
| agent_order 默认值 | 空 = 默认拓扑（四层链） | 零迁移（旧 config 无键自动空）；语义清晰（未配置 = 跟随模板） |
| 校验双层 | API 422 + 执行层回退 | 输入卫生与数据防御分离；执行层永不因配置损坏而中断写作（验收「非法回退默认」） |
| 角色集合来源（v1.5 #484） | **从 `/api/v1/agents` 真源派生（role_key 单一来源，#473 承接）** | 硬编码 4 键（不随 Agent 管理增减，⑩ 实证）；前端与后端双份维护（漂移） |

---

## 3. API 契约

**无新增 REST 端点**。所有变更走既有 `PATCH /api/v1/projects/{id}`（`api/routers/project.py` L97-109）config 部分合并语义（`project_service.py` L139-143：`model_dump(exclude_unset=True)` + `existing.config.model_copy(update=config_updates)`）——agent_order 作为 ProjectConfig 新字段自动纳入，前端 PATCH 传 `{config: {agent_order: [...]}}` 即可。

| 变更 | 端点 | 说明 |
|------|------|------|
| PATCH config 扩展 | `PATCH /api/v1/projects/{id}` | body `config.agent_order`（list[list[str]]）+ `config.agent_*`（三态值）按既有合并语义生效 |
| agent_order 非法 | 同端点 | 422，detail 中文（§2.3 API 层） |
| 模型存在性提示 | 无新端点 | **不校验存在性**（#268 方案 3：不存在允许保存）——前端标记（§5.2）；数据源 = `GET /api/v1/provider-configs` chat 模型列表 |
| 角色集合数据源（v1.5 #484） | **既有 `GET /api/v1/agents`** | 6 内置 + 自定义 Agent 全量（#473 已透出 role_key）；前端 AgentChainCard/AgentRelationEditor/TemplateDialog 角色列表均从该端点派生（§5.7.2）——无新端点 |

**异常映射表**：

| 场景 | 状态码 | detail |
|------|--------|--------|
| agent_order 长度 >10（槽位 0-9 超限） | 422 | 「agent_order 最多 10 层（槽位编号 0-9）」 |
| agent_order 缺启用角色（Q2 口径） | 422 | 「agent_order 必须包含全部启用角色: xxx」 |
| agent_order 空槽/跨层重复 | 422 | 「agent_order 每层必须为数组」/「agent_order 角色重复: xxx」（空槽 [] 允许，v1.2） |
| agent_* 为空字符串 | 422（既有） | 「Agent 模型不能为空字符串」（project.py L73-82 既有 validator） |
| agent_* 为未知模型 | **200 允许保存** | 前端标记「未注册模型」提示（§5.2） |
| agent_* 为裸模型名（无 `/`） | **200 允许保存 + 前端格式提示**（Q3：格式不合规标记，不阻塞；执行时按 §5.1 兼容策略回退） | 提示不阻塞 |

---

## 4. CLI 命令签名

**本模块不新增 CLI 命令**。agent_order 的 CLI 读写依赖 **#251 CLI project update 修复**（0.8.0 W2 P1）——#251 落地后 `inkflow project update --id N --config-json '{"agent_order": [["agent_architect"], ...]}'`（或等效形态，以 #251 spec 为准）经既有 PATCH 合并语义天然支持 agent_order（嵌套结构经 JSON 透传，无特殊处理）。

- 本模块对 CLI 的约束：① ProjectConfig 字段扩展**不得破坏** #251 的 config 合并语义（agent_order 是普通可选字段，exclude_unset 兼容）；② `inkflow project get --id N --json` 的 config 输出自动包含 agent_order（F7 全局 JSON 信封约定，无需改动）。
- **验收联动**：M6（CLI 读写）依赖 #251 合入；若 #251 未在 #269 前合入，CLI 验收降级为 API 层验证（curl PATCH/GET agent_order），并在 PR 说明标注（已确认：CLI 归属 #251，不占拍板配额）。

---

## 5. 关键差异节：Agent 链配置驱动编排（层级拓扑 + 三态模型）

### 5.1 三态语义执行层解析（#268 核心修复）

**现状缺陷**（实证）：`agent_service.py` `_merge_role_configs` L232-234：

```python
project_model = project_role_models.get(stage.id)
if project_model:                        # ← "__default__" 非空 → 覆盖！
    new_agent.model = project_model      # → model="__default__" → parse_model_string ValueError
```

**修复**：

```python
if project_model and project_model != AGENT_DEFAULT_SENTINEL:
    new_agent.model = project_model      # sentinel = 跟随默认 → 不覆盖（模板角色模型/全局默认）
```

- 依赖注入：`AGENT_DEFAULT_SENTINEL` 从 `domain/models/project.py` import（同模块域，无循环依赖风险）。
- **跟随默认的完整解析链**（不覆盖后回退路径）：模板 role.model（builtin 恒 `openai/gpt-4o`）→ 自定义 AgentTemplate role.model（`RoleTemplate.model`，可 None）→ `None` → `langchain_client.chat(model=None)` → `self._default_model`（全局默认 `config.llm_default_model`，`langchain_client.py` L73）——三层兜底与既有温度链同构。
- **裸模型名兼容策略**（Q3 拍板，防御性）：执行层 `_merge_role_configs` 对 project_model 做格式预检——无 `/` 且非 sentinel → 记 warning + 不覆盖（按跟随默认处理），不抛错（存量数据零迁移；新数据由前端格式标记引导修正，§2.2）。
- **测试锚点**：`agent_* = "__default__"` 时执行不再抛 ValueError，且模型回退模板角色模型（mock LLM 断言 model 参数）；`agent_* = "gpt-4o"`（裸名）→ warning + 回退跟随默认。

### 5.2 前端模型选择 UI（#268 + Q3 格式统一）

**AgentChainCard.tsx MODIFY**（`frontend/packages/renderer/src/components/AgentChainCard.tsx`）：

- 每行 Switch 打开 → **条件渲染**模型 Select（替换/补充当前 tag 展示）；关闭 → 不渲染（保持现状 UI 简洁）。
- Select 数据源（Q3 拍板：格式统一后数据源自然成立）：**provider-configs chat 模型列表**——`GET /api/v1/provider-configs` → `items[].models[type=chat].id`，扁平为 `<provider>/<model>` 选项（provider 名取 `items[].name`）；数据加载走既有 `stores/models.ts`（ProviderConfig/ProviderModel 接口已存在）。**「跟随默认」选项固定置顶**（值 = `AGENT_DEFAULT_SENTINEL`）。
- Select 选项结构：
  1. 「跟随默认」= `AGENT_DEFAULT_SENTINEL`（Switch 打开默认选中）
  2. 每 provider 的 chat 模型：`<provider>/<model>`
- 三态交互映射（§2.2 表）：Switch off → PATCH `null`；on + 「跟随默认」→ `__default__`；on + 具体模型 → `<provider>/<model>`。
- **未注册模型标记**（#268 方案 3）：config 中既有值不在选项列表（如手工写入/模型已删）→ tag 显示「未注册模型」警告样式（沿用现有 tag 展示位，L70），**不阻塞保存**——即改即存链路（settings.tsx AgentPanel `persist()` L395-415：in-flight 守卫 + 失败 toast）不变。
- **格式不合规标记**（Q3）：config 中既有值无 `/`（裸名）→ tag 显示「格式需修正（应为 provider/model）」提示；**修改默认模型 Select（AgentPanel L422-439）**：硬编码 `['openai','deepseek','ollama']` → 改为 provider-configs chat 模型列表（与 AgentChainCard 同数据源），存完整 `provider/model` 值——修复 v1.0 的裸 provider 名写入问题。

**store 扩展**：`stores/agent.ts` 无需新方法（setConfig/saveConfig 既有）；`stores/models.ts` 新增 chat 模型扁平化 selector（provider/model 选项列表，供 AgentChainCard 与 AgentPanel 共用）。

### 5.3 执行拓扑：单链 → 层级并行（#269 + Q1 拍板）

**消费链**：`AgentService.execute`（`domain/services/agent_service.py` L67-118）→ `get_template("builtin:write_chapter")` → `_merge_role_configs`（模型/温度装配 + 跳过过滤）→ `_apply_agent_order`（拓扑重排，v1.1 新增）→ `_run_pipeline` → `LangGraphAgentPipeline.execute`（`infrastructure/agent/langgraph_pipeline.py` L95-138）。

**执行顺序事实**（实证，决定实现方式）：LangGraphAgentPipeline.execute **按 DAG 边（output_to/input_from）构建 StateGraph**——执行顺序 = LangGraph 拓扑调度，**非 stages 列表顺序**（L120-126：entry=无 input_from 阶段；edges=output_to 边；terminal=无 output_to 阶段）。「固定序」的真相来源 = 模板 stages 的**链式边**（pipeline_templates.py L65-81 硬编码）。

#### 5.3.1 `_apply_agent_order(stages, agent_order, enabled_roles) -> list[PipelineStage]`（v1.3 签名定稿，纯函数）

1. 输入：模板 stages（4 阶段链式）+ 项目 config.agent_order（层级嵌套角色字段名数组）+ `enabled_roles`（启用角色集合，来自 agent_* 非 null 的角色；双模式下见步骤 4）
2. **双模式分派（v1.3 B1）**：`agent_order` 空 = **默认模板模式**——原样返回（模板默认拓扑，null 不触发跳过，v1.0 语义零迁移）；非空 = 配置驱动模式——继续步骤 3-7
3. 语义校验（执行层防御）：非法（缺启用角色/长度 >10/跨层重复）→ 记 warning + 原样返回（回退默认）；**角色名任意（内置 + 自定义均允许，v1.2）**；空槽（[]）正常跳过
4. **跳过过滤**（Q2 拍板 + B1 限定）：**配置驱动模式下** agent_* = null 的角色从集合摘除（无论是否在 agent_order 中；§2.3 关闭角色语义）
5. **层级映射**：`agent_xxx → xxx`（stage.id）；按层序重组 stages；**自定义角色 stage 构造**（v1.3：从 AgentTemplate.roles 装配占位 AgentRole，§5.3.4）
6. **全连接边重建**：第 i 层每节点 `input_from` = **前序全部层所有角色**；`output_to` = **后序全部层所有角色**（跨层直连全连接 DAG——执行依赖传递闭包 + 变量注入自然全量；DAG 边多不影响 LangGraph 拓扑序）；空槽不改变「前序全层」成员集合（按最近非空槽计算，v1.3 F7 钉死）
7. **拓扑-引用一致性校验**（v1.3 F4/F5 修正）：静态扫描各角色 prompt 的 `{role}_output` 占位符（复用 `_VARIABLE_RE`），被引用角色必须位于该角色的**严格前序层**；违规 → 执行层回退默认拓扑 + warning（数据防御）/ API 层 422（输入卫生，实现确认落点）；同层互引在层内校验直接拒绝
8. 返回重排后的 stages，供 `_merge_role_configs` 装配

- **装配顺序（v1.3 F3 定稿）**：`execute` 中顺序为 **① 读 agent_* 得启用集合 → ② `_apply_agent_order`（双模式分派 + 跳过过滤 + 自定义 stage 构造 + 重排 + 边重建 + 一致性校验）→ ③ `_merge_role_configs`（模型/温度装配，只装配存留角色）→ ④ `_run_pipeline`**——v1.2 的「merge 之后 apply」作废（自定义角色 stage 必须先构造才能装配；§5.3 消费链同步更新）。
- **默认拓扑**（空 agent_order）：`[[architect],[writer],[auditor],[reviser]]`——与现模板链**执行序等价**，但注意：全连接边重建后 auditor 的 `input_from` 从 `[writer]` 变为 `[architect, writer]`，user 消息会多注入 architect 输出段（v1.3 Y3 修正声明）——默认路径也发生 user 消息内容变化，需负向回归断言（§9）。

#### 5.3.2 引擎放宽（`langgraph_pipeline.py` + `pipeline_nodes.py` MODIFY）

- **validate()**（L50-93）：「唯一入口」（L57-60）/「唯一终点」（L61-62）约束**放宽**为「至少一个入口/终点」——层级并行下第一层多角色（无 input_from）都是入口、最后一层多角色（无 output_to）都是终点；**环检测（Kahn）与引用存在性保留**（L64-93 不变）。
- **execute()**（L95-138）：入口连接从 `workflow.set_entry_point(entry.id)`（L120-121）改为**每个入口节点 `add_edge(START, entry_id)`**；终点从 `workflow.add_edge(terminal.id, END)`（L125-126）改为**每个终点节点 `add_edge(terminal_id, END)`**（LangGraph 1.x 支持多 START/END 边；实现时以实测为准，若 API 限制则用 conditional entry 兜底——标注实现确认）。
- **节点泛化（v1.2 拍板 + v1.3 F4 修正）**：`_NODE_MAP`（L33-38）从 4 具名节点白名单（architect_node/writer_node/auditor_node/reviser_node，pipeline_nodes.py L124-141）改为**通用节点映射**——任意 stage.id → `generic_node`：
  - 现状实证：4 具名节点只是 `_call_llm_node(state, stage_id, upstream_keys)` 的参数化包装，**upstream_keys 硬编码在具名节点里**（architect=[]/writer=["architect"]/auditor=["writer"]/reviser=["writer","auditor"]）
  - **⚠️ 模板数据不一致（v1.3 F4 实证）**：模板 `pipeline_templates.py` L81 的 `reviser.input_from=["auditor"]`（**缺 writer**）——现状由节点硬编码 `["writer","auditor"]` 补偿；测试 `test_langgraph_pipeline.py` L78-83 又写 `["writer","auditor"]`——**模板/节点/测试三者不一致**。通用节点直接推导 `input_from` 会让 reviser 丢 writer → `{writer_output}` 字面量残留
  - **修正（v1.3 F4）**：① 修正模板 `reviser.input_from` 补 `"writer"`（真相来源收敛回模板数据）；② 增加模板层校验：`input_from` 必须覆盖 prompt 引用的全部 `{role}_output` 占位符（复用 `_VARIABLE_RE` 扫描，作为 `_apply_agent_order` 步骤 7 一致性的子集校验）
  - 修复：`generic_node(state)` 从 `state["stages"][stage.id].input_from` **推导 upstream_keys**（不再硬编码）；`langgraph_pipeline.execute` L111-112 的「未知阶段类型」检查删除（任意 stage.id 可执行）
  - 自定义角色 prompt 来源：`stage.agent.system_prompt`（由 `_merge_role_configs` 从 AgentTemplate.roles 装配，§5.3.4）
- 并行层内节点执行顺序：LangGraph 同层并行调度（asyncio），**层间顺序确定、层内顺序不确定**——验收「按配置顺序执行」口径 = 层序确定（§13 M4）。

#### 5.3.3 prompt 变量注入改造（`pipeline_nodes.py` MODIFY——v1.3 B8 定稿）

- `_build_messages`（L47-68）变量注入契约（v1.3 修正，评审 R3/F5）：
  ```python
  # 注入键集 = input_from 全部（前序全层）∪ 该角色 prompt 中扫描出的全部 {xxx_output} 占位符
  # （复用 _VARIABLE_RE——未来层引用/同层互引的占位符也进变量表 → 渲染为空串而非字面量残留）
  for key in inject_keys:                     # inject_keys = upstream_keys ∪ 占位符扫描集
      sr = state["results"].get(key)          # ← .get 防御（未执行角色无条目 → 空串）
      variables[f"{key}_output"] = sr.output if sr else ""
  ```
- **同层不可见硬语义（v1.3）**：同槽位并行角色互相引用 → **一律注入空串**（即使调度上已执行也强制空——保证断言稳定，避免「先执行者读到值、后执行者读到空」的 flaky）；§7「同层互引空注入」按此语义修订。
- **效果**：① 前序层引用 → 实际输出；② 未来层/同层/未执行引用 → 空串（软降级，用户自由排序的明确代价——UI 保存时按角色级精确提示「XX 角色将看不到 YY 的输入」，v1.3 从通用文案升级为静态依赖分析提示）；③ `_render` L44 的「未知占位符原样保留」路径只对**拼写错误**变量生效（兜底，不阻断）。
- user 消息 parts（L62-64）同源改造（`.get` 防御 + 同层空注入）。
- **防回归断言**：prompt/user 消息无 `None` 字面量注入（评审 O4，低成本高价值）。

#### 5.3.4 自定义角色（v1.2 执行解锁 + v1.3 数据面 0.8.0 + v1.5 链动态化）

- `agent_order` **数据模型与校验支持任意角色字段名**（§2.1/§2.3）——内置 6 + 自定义 Agent 均可编排，UI 不限制；执行槽位 0-9（默认模板占 0-3，槽 4-9 预留自定义 Agent）。
- **执行层解锁**：`_NODE_MAP` 白名单删除 → 任意 stage.id 经通用节点执行（§5.3.2 节点泛化）。
- **⚠️ 数据面缺口（v1.3 评审 F2/🔴-2 实证，用户拍板 0.8.0 实现）**：现状 `RoleTemplate` 只有 `model/temperature/enabled` 三字段（`agent_template.py` L29-40）——**无 system_prompt/name**，自定义角色 prompt 与显示名无来源（「缺失→跳过」= 永远跳过 = 功能空转）；`ProjectConfig` 只有 4 个固定 `agent_*` 字段（自定义角色无项目级三态字段）；`AgentChainCard` 只渲染 4 固定角色（无自定义角色行 UI 入口）。
- **数据面设计（v1.3，拆 issue 实现，见 §10）**：
  1. `RoleTemplate` 扩展 `prompt: str | None` + `name: str | None`；`_merge_role_configs` 在 `role_template.prompt` 非 None 时覆盖 `new_agent.system_prompt`
  2. `ProjectConfig` 自定义角色三态字段：约定 `extra["agent_roles"]`（dict[自定义角色字段名, str|None]，与 agent_* 同三态语义）或独立字段（实现拆 issue 时定稿）——**自定义角色的启用/关闭/模型配置面**
  3. `AgentChainCard` 角色数据源 = 内置 4 + 当前模板 roles（自定义角色行：开关 + 模型 Select + 槽位号）——**v1.5 #484 升级**：角色数据源改为 Agent 管理全量真源派生（§5.7.2），本点 v1.3 语义被取代
  4. 「启用角色」口径（配置驱动模式）= agent_* 非 null ∪ extra 自定义角色非 null
- **v1.5 #484 扩展（自定义 Agent 进链）**：自定义角色数据源从「模板 roles 非四键」升级为「**Agent 管理全量（6 内置 + 自定义 Agent）真源派生**」——Agent 管理创建的自定义 Agent（`AgentEntity.builtin=false`）可进链：服务层为其分配稳定 role_key（§5.7.2），项目级三态字段写入 `config.agent_roles[agent_<role_key>]`（§5.7.3），执行层 prompt 从 `AgentEntity.system_prompt` 取（§5.7.4）。模板 roles 仍可提供 prompt/name/模型覆盖（既有装配，`_merge_role_configs` 不变）。
- **prompt 缺失防御（过渡期）**：自定义角色既非内置且模板 roles 未定义（system_prompt 为空）→ 执行层**跳过 + warning 日志**（§2.3/§7）——数据面 issue 落地后此路径仅剩存量损坏数据触发。
- **归属边界**：自定义 Agent 能力差异化白名单（#257）归 0.9.0 F39-F41；本模块（含拆出 issue）解锁「模板定义角色 → 配置 → 编排 → 管线执行」全链路。

### 5.4 #270 DAG 编排（0.9.0 由 F46 spec 承接，本模块不实现）

> **2026-08-16 承接说明（v1.4）**：#270 已由独立 spec `specs/f46-dag-orchestration/spec.md` 承接（0.9.0，作为其唯一真相来源）。本模块的演进约束已全部落地，不再承担「预留」职责：
> - 层级 = 拓扑层特化 → F46 §1.2.3「`agent_order` = 拓扑基线，`agent_relations` = 增强语义」
> - 执行链设计 → F46 §5.3「自研 LangGraph StateGraph 扩展（基线 + 叠加 + 关系优先）」
> - 配置模型兼容 → F46 §2.2「`agent_relations: list[{from,to,type}]` 与 `agent_order` 并存」
> - 真禁用 / 并行语义 → F46 §5.3.1 叠加规则复用 F42 跳过 / 全连接语义

| 演进约束 | 本模块保证 | F46 承接 |
|----------|-----------|---------|
| 层级 = 拓扑层特化 | `agent_order` 层级嵌套是**分层并行 DAG** 的紧凑表示（层间全连接 + 层内并行） | F46 §1.2.3（agent_order 基线 + agent_relations 增强） |
| 执行链设计 | 引擎放宽后的 validate/execute（多入口/终点 + 全连接 DAG）即通用 DAG 引擎子集——#270 无需引擎重写 | F46 §5.3（基线 + 叠加 + 条件边 `add_conditional_edges`，复用 F42 通用引擎） |
| 配置模型兼容 | agent_order（list[list[str]]）+ agent_relations（0.9.0 新增）并存；冲突规则（关系优先） | F46 §2.2 / §5.3.1（关系优先定稿） |
| 真禁用（Q2） | 跳过 = 节点摘除 + 边重连（§5.3.1 步骤 4） | F46 §5.3.1（复用跳过 / 空注入语义） |
| 并行语义 | 同层并行 = DAG 并行分支；汇点 = 后一层单角色 | F46 §5.3.1（同层显式边打破并行；汇点 = 后一层单角色） |

### 5.5 deepagents 兼容性结论（实证，已确认非拍板点）

- agent_order **仅消费方 = LangGraphAgentPipeline**（角色链管线；角色集合 v1.5 扩展为 6 内置 + 自定义）——`POST /api/v1/agent/.../execute`（`api/routers/agent.py` L29-30 装配）。
- F27 agentic 路径（`AgenticWriterService` + `build_agentic_writer`）：deepagents **单 agent**（writer_agent）ReAct 循环 + 5 只读 + save_draft 工具，`model=config.llm_default_model`——**无多角色编排概念，不消费 agent_order/agent_***（`api/deps.py` L220-240 实证）。
- F29 Supervisor（#161，0.8.0 W5）：deepagents subagent 机制分层编排，与 agent_order 管线编排**不同抽象层**——#269 的「注意 deepagents harness 兼容」结论：**无冲突**，agent_order 不触碰 deepagents 装配；F29 spec 需单独定义 supervisor 与管线的衔接（同编排域串行：必须 #269 合入后 #161 再开，roadmap 风险表已声明）。
- 模型名剥离：agent_* 具体模型值（provider/model 格式）在 LLM 调用链既有剥离逻辑（F26 §5.5 `parse_model_string` 复用）——本模块不新增剥离代码。

### 5.6 GUI 写作入口管线化（v1.3 拍板 B2：全自动 / 续写双模板）

**背景**（评审 🔴-3/R5 实证）：GUI 写作现状走 `/stream`（writing_service 单模型，`model = request.model or project.config.model`）与 `/agentic/generate`（F27 单 agent，全局默认模型）——**两者都不消费 `agent_order`/`agent_*`**，#268/#269 验收「写作流程按指定模型/新顺序执行」在 GUI 主路径不可达。用户拍板：**GUI 写作入口切换到多角色管线**。

**新增默认管线模板**（`pipeline_templates.py` 注册，prompt 按场景独立编写）：

| 模板 key | 名称 | 场景 | 角色链（初稿，实现可微调） | 说明 |
|----------|------|------|---------------------------|------|
| `builtin:write_auto` | 全自动 | 从零生成新章节（无前文或独立章节） | architect → writer → auditor → reviser（同 write_chapter 骨架，prompt 按「全自动新章节」重写） | 规划 → 正文 → 审校 → 修订全链 |
| `builtin:write_continue` | 续写 | 基于前文续写章节 | writer → auditor → reviser（无 architect——前文摘要注入上下文，F6 复用） | 续写 → 审校 → 修订；prompt 含前文摘要引导 |

- **模板注册**：`BUILTIN_TEMPLATES` 扩展两个 key；`get_template` 既有分发不变；CLI `agent pipelines list`（如存在）自动暴露。
- **GUI 入口接线**：写作页「全自动生成」按钮 → `POST /api/v1/agent/pipelines/execute`（pipeline=`builtin:write_auto`）；「续写」按钮 → execute（pipeline=`builtin:write_continue`）；执行状态/结果复用 agent 管线 execution 查询端点（`GET /api/v1/agent/pipelines/.../status` 或等效，实现确认）——写作页需接入执行状态展示（进行中/成功/失败 + 成品内容落章）。
- **`agent_order`/`agent_*` 生效**：两个模板执行同样经 `_apply_agent_order`（双模式）+ `_merge_role_configs`——GUI 主路径按配置的模型/顺序执行，#268/#269 验收可达。
- **边界**：F27 agentic（工具型单 agent）保持独立入口（能力不同：工具循环 vs 角色链，本模块不改造）；F3 writing_service 单模型路径保留兼容（既有 API 不断，逐步被管线模板替代——替代节奏另行拍板）。
- **成品身份（v1.3 评审 🔴-1 定义 + v1.5 扩展）**：`final_output` = **reviser 输出**；reviser 被禁用/未启用时 = 最后一个非 architect/auditor 内容角色输出（内置语义：writer；**v1.5 #484 扩展：worldview/polisher 也是内容角色，可作成品**，§5.7.4）；architect/auditor 永不作为成品——执行层在装配后校验终点角色类型，违规（如用户把 auditor 排最后）→ 回退默认拓扑 + warning（或 API 422，实现确认）；§13 M6 增加「调整顺序/关闭角色后成品类型不变」断言。
- **拆 issue**：本小节实现拆 2 个 issue（① 模板注册 + prompt 编写；② GUI 写作页入口切换 + 执行状态 UI），见 §10。

### 5.7 链动态化 + 模板联动（v1.5 #484：6 内置皆可进链 + 自定义 Agent 进链 + 模板任意角色组合）

**背景**（2026-08-19 源码实证）：#473 已合入（PR #492）——后端 6 内置 Agent 暴露 `role_key` 映射，前端 AgentChainCard 内置行已从 `/api/v1/agents` 真源派生。但链仍固定 4 位置：世界观顾问/润色师 `role_key=None` 无法渲染（§1.1 ⑨）；AgentChainCard/AgentRelationEditor/TemplateDialog 三处 4 键硬编码（§1.1 ⑩）；模板 roles 前端契约仍 4 键（§1.1 ⑪）。本小节把「链角色集合」从真源完全派生，并打通 Agent 管理 ↔ 链 ↔ 模板三域联动。

#### 5.7.1 role_key 全集扩展（6 内置稳定映射，后端真源）

| 内置 Agent（BUILTIN_AGENT_SPECS） | 现状 role_key（#473） | v1.5 扩展 | 链角色字段名 |
|-----------------------------------|----------------------|-----------|--------------|
| 架构师 | `architect` | 不变 | `agent_architect` |
| 写手 | `writer` | 不变 | `agent_writer` |
| 审校员 | `auditor` | 不变 | `agent_auditor` |
| 修订师 | `reviser` | 不变 | `agent_reviser` |
| 世界观顾问 | `None` | **`worldview`** | `agent_worldview` |
| 润色师 | `None` | **`polisher`** | `agent_polisher` |

- **落地**：`BUILTIN_AGENT_SPECS` 两处 `role_key: None` 改为 `"worldview"`/`"polisher"`（`agent_entity_service.py`）——role_key 是链角色**稳定标识**（语义固定、不随显示名变更），沿用 #473 契约（`GET /api/v1/agents` 透出，前端派生）。
- **seed 影响**：seed 幂等（按 name 判重），存量 DB 已 seed 的世界观顾问/润色师需一次迁移：role_key 列补值（`UPDATE agents SET role_key='worldview' WHERE name='世界观顾问'`）——实现 PR 提供迁移脚本或 seed 升级钩子（实现确认）。
- **默认拓扑不变**：默认 `[[architect],[writer],[auditor],[reviser]]`（4 角色链零迁移）；世界观顾问/润色师作为**可选角色**——用户通过「添加角色」进链（§5.7.3），默认不在链中。

#### 5.7.2 角色池 = Agent 管理全量（真源派生）

- **角色池定义**：可进链角色 = `GET /api/v1/agents` 全量（6 内置 `builtin=true` + 自定义 Agent `builtin=false`），按 `builtin` 分组展示（内置在前、自定义在后，均按 name 排序）。
- **自定义 Agent role_key 分配**：自定义 Agent 创建时（`POST /api/v1/agents`）服务层自动分配稳定 role_key——取 name 的 slug 化（小写字母/数字/下划线，如「校对助手」→ `proofreader` 或 `校对助手` 拼音/ASCII 归一化，实现确认）——冲突时追加后缀；role_key 一经分配不可变更（或允许显式指定，实现拆 issue 时定稿）。**role_key 是自定义 Agent 的链身份**，`config.agent_roles[agent_<role_key>]` 三态字段以此命名（§5.3.4）。
- **前端派生规则（三组件统一）**：
  1. `AgentChainCard`：内置行 = `agents.filter(a => a.builtin && a.role_key)`（不再 BUILTIN_ROLE_KEYS 4 键 map，§1.1 ⑩ 修复）；自定义行 = `agents.filter(a => !a.builtin)`（不再只从模板 roles 非四键取，§5.3.4 v1.5 扩展）——**模板 roles 键仍是链字段的补充来源**（模板自定义键但无 Agent 实体 → 仍渲染，兼容既有模板；§7）
  2. `AgentRelationEditor`：角色列表 = 同一派生规则（ROLE_FIELDS 4 键硬编码删除，F46 #270 依赖编辑器联动 6+ 角色）
  3. `TemplateDialog`：角色编辑列表 = 同一派生规则（ROLES 4 键硬编码删除，模板可引用任意角色组合，§5.7.5）

#### 5.7.3 链增/删/改角色（UI 契约）

- **添加角色**：AgentChainCard 顶部「添加角色」按钮 → 弹出角色池选择器（未在链中的角色，内置 + 自定义）→ 选择后：① 写入三态字段（`agent_*` 或 `agent_roles[agent_<role_key>]` = sentinel「跟随默认」）；② 加入 `agent_order` 默认槽位（内置按 DEFAULT_SLOTS 既有映射；自定义/新角色追加到末尾槽，§5.7.2 分配）——即「配置驱动模式」显式化（v1.3 B1 双模式语义不变）。
- **删除角色**：既有关闭开关即「移除」语义（agent_* → null + 从 agent_order 剔除，§2.2 双模式一致性规则）——UI 文案保持「关闭」；关闭后角色仍在角色池中可重新添加。
- **修改角色**：既有槽位号编辑（0-9）/上移下移/模型 Select 不变（M6 契约）；新增角色同样支持。
- **data-testid 契约**：既有 `agent-order-slot-<field>`/`agent-order-move-up-<field>`/`agent-model-select-<field>` 以 `field` 为键（field = `agent_<role_key>`），新角色自动满足；新增「添加角色」按钮 `data-testid="agent-chain-add-role"` + 角色池选项 `data-testid="agent-chain-role-option-<field>"`（E2E 契约）。

#### 5.7.4 执行层 stage 构造扩展（6 内置 prompt 真源）

- **现状局限**：内置模板（write_chapter/write_auto/write_continue）只含 4 角色 stage——世界观顾问/润色师进链后模板 stages 无对应 stage → `_apply_agent_order` 无法构造 PipelineStage。
- **扩展方案**：`_apply_agent_order`（或 `_merge_role_configs` 前置装配点）对 agent_order 中**模板 stages 缺失的角色**（6 内置新增 2 + 自定义 Agent）构造占位 stage：
  - **内置角色**：`system_prompt`/`name` 从 **AgentEntity 真源**取（`agent_entity_service` 已存 6 内置 prompt：世界观顾问「你是世界观顾问，负责校验角色与伏笔的世界观一致性。」、润色师「你是润色师，负责在前文基础上润色文笔。」）——`agent_service` 注入 AgentRepositoryProtocol 查询（或 `GET /api/v1/agents` 数据缓存，实现确认）
  - **自定义角色**：`system_prompt` 从 `AgentEntity.system_prompt` 取；模板 roles 同名键可覆盖（既有 `_merge_role_configs` prompt 覆盖逻辑）
  - `model`/`temperature`：跟随默认链不变（§5.1 三层兜底）
- **与模板角色的关系**：模板 roles 键 = `agent_<role_key>` 对应键时，RoleTemplate 的 `model/temperature/prompt/name` 覆盖 Agent 真源（模板优先——模板是场景化覆盖层，Agent 是真源）；无模板键时纯 Agent 真源。
- **成品身份（v1.3 语义扩展）**：世界观顾问/润色师是**内容角色**（输出可作成品）——成品选择规则扩展为「reviser 输出 → 否则最后一个内容角色（writer/reviser/worldview/polisher）输出；architect/auditor 永不作为成品」（§5.6 成品身份 + §7 边界行同步）。
- **prompt 变量注入不变**：新角色 stage 沿用 `_build_messages` 占位符扫描 + 空注入契约（§5.3.3）——世界观顾问/润色师 prompt 若引用 `{writer_output}` 等，按前序层/空注入规则处理。

#### 5.7.5 模板引用任意角色组合（TemplateDialog 联动）

- **TemplateDialog 角色编辑列表**：`ROLES = ['architect','writer','auditor','reviser']` 4 键硬编码 → 从角色池派生（§5.7.2 派生规则）——模板可引用**任意角色组合**（6 内置 + 自定义 Agent），勾选启用/关闭 + 模型 Select + 温度 Slider（既有交互逐角色保留）。
- **roles 数据契约**：`AgentTemplateInput.roles` 类型从 4 键收紧改为 `Record<string, AgentTemplateRole>`（后端 `AgentTemplate.roles: dict[str, RoleTemplate]` 已是任意键，F42 #295 已放宽——前端类型同步即通，§1.1 ⑪ 修复）。
- **保存语义**：roles 全量替换（exclude_unset 合并，既有）；模板引用已删除自定义 Agent 的键 → 保留（模板是快照，§7 边界行）。
- **链-模板联动**：项目选模板后，AgentChainCard 自定义行 = Agent 管理真源（与模板 roles 无关的独立来源）；模板 roles 仅提供 prompt/模型/温度覆盖——「模板引用任意角色组合」不改变链角色集合本身（§5.3.4 归属边界，模板拓扑 ≠ 链拓扑）。

---

## 6. 组织规则

- ProjectConfig 扩展遵循既有 Pydantic 模型约定（domain 层零框架依赖）；`AGENT_DEFAULT_SENTINEL` 保持 `domain/models/project.py` 定义（唯一真相源），前端 `stores/project.ts` L18 镜像常量（既有双份模式，注释互指）。
- `_apply_agent_order` 归属 domain 服务层（纯函数，不依赖 infrastructure）——放在 `agent_service.py` 模块级函数（非类方法），便于独立单测。
- 引擎放宽（validate/execute）与变量注入改造归属 infrastructure 层（langgraph_pipeline.py / pipeline_nodes.py）——domain 层不感知 LangGraph API。
- 前端模型选择数据源走既有 `stores/models.ts`（ProviderConfig/ProviderModel 接口已有）——不新建 provider store；AgentChainCard 保持「展示组件 + 回调」模式（onConfigChange 即改即存，`settings.tsx` persist 链路不变）。
- 执行层 `__default__` 解析在 `_merge_role_configs`（唯一模型装配点）——不在节点层（pipeline_nodes.py）做 sentinel 判断，保持节点纯净（节点只消费装配后的 AgentRole）。
- **角色集合真源（v1.5 #484）**：链/依赖编辑器/模板编辑的**角色列表一律从 `GET /api/v1/agents` 派生**（role_key 单一来源，#473 承接）——前端不维护第二份角色键白名单（BUILTIN_ROLE_KEYS/ROLE_FIELDS/ROLES 4 键硬编码全部移除）；自定义 Agent role_key 由服务层分配（§5.7.2），前端只消费。模板 roles 键（Record）是覆盖层，非角色集合来源（§5.7.5 链-模板联动边界）。

---

## 7. 边界情况与错误处理

| 场景 | 行为 | 错误面 |
|------|------|--------|
| agent_* = `__default__`（v1.0 缺陷路径） | **修复后**：不覆盖模板模型，正常执行（§5.1） | 无（修复点；执行日志可查模型回退） |
| agent_* = 裸模型名（无 `/`） | 执行层 warning + 回退跟随默认（§5.1 兼容策略）；前端格式标记 | 无（存量零迁移；新数据 UI 引导） |
| agent_* = 未知模型名（如 `foo/bar`） | 允许保存（#268 方案 3）；前端「未注册模型」标记；执行时 provider 配置不存在 → LLM 调用失败走既有重试/失败语义 | 执行失败（既有 PipelineError 路径，非本模块新增） |
| agent_* = 空字符串 | 422（既有 validator L79-81） | 输入拒绝 |
| agent_* = null（Q2 真禁用 + v1.3 B1 双模式） | **默认模板模式**（agent_order 空）：不跳过，跟随模板默认（v1.0 语义）；**配置驱动模式**（非空）：角色跳过执行，下游空输入降级（§5.3.1 步骤 4） | 无（设计语义；日志记跳过） |
| GUI 全自动/续写（v1.3 B2） | 写作页入口 → 管线 execute（builtin:write_auto / write_continue）→ 经 _apply_agent_order + _merge_role_configs，按 agent_order/agent_* 执行 | 无（#268/#269 验收主路径） |
| 终点角色非内容型（v1.3 成品身份） | 装配后校验终点角色类型（architect/auditor 非成品）→ 违规回退默认拓扑 + warning 或 API 422（实现确认） | 防御回退（评审 🔴-1） |
| 全部角色关闭 | API 校验拒绝（至少 1 启用角色）；执行层回退默认拓扑 + warning | 输入拒绝 / 防御回退 |
| agent_order 缺省/空列表 | 模板默认拓扑执行（零迁移） | 无 |
| agent_order 含自定义角色名（非内置，v1.2 支持 + v1.5 扩展 6 内置皆可） | API 允许；执行层经通用节点执行（prompt 由模板 roles 装配 / Agent 真源，§5.3.4/§5.7.4） | 无（v1.2 解锁） |
| 自定义角色 prompt 缺失（非内置且模板 roles 未定义） | 执行层跳过 + warning；模板补定义后恢复 | 防御跳过（§2.3） |
| agent_order 空槽（[]） | 该槽位无角色，跳过执行（跳号允许） | 无（规范化） |
| agent_order 缺启用角色（Q2 口径） | API 422；执行层回退默认 | 输入拒绝 / 防御回退 |
| agent_order 跨层重复 | 存储层/API 422 | 输入拒绝 |
| 引用未来层角色变量（自由排序导致） | 空注入（§5.3.3）+ UI 保存时提示 | 无（软降级，用户自由排序代价） |
| 同层并行角色互相引用（如 writer/auditor 同层且 prompt 引用对方） | 空注入（同层未执行） | 无（软降级；UI 提示「同层角色并行，互相不可见」） |
| AgentTemplate 项目（含自定义角色，v1.2） | agent_order 拓扑作用于全部启用角色（内置 + 模板自定义）；模板 roles 提供自定义角色 prompt/模型覆盖（§5.3.4）；模板不改变 agent_order 拓扑本身 | 无（文档化行为） |
| 存量项目（无 agent_order 键） | Pydantic 默认空列表 → 模板默认拓扑 | 无（零迁移） |
| GUI 重启 | config 持久化（PATCH 落库）→ 读回三态/拓扑保持 | 无（#268/#269 验收项） |
| 模型在 provider 注册表被删 | 前端标记「未注册模型」；保存仍允许 | 提示不阻塞 |
| 世界观顾问/润色师进链（v1.5） | 默认不在链中；用户「添加角色」→ 进链执行（prompt 从 Agent 真源取，§5.7.1/§5.7.4） | 无（设计语义；seed 迁移后 role_key 非空） |
| 存量 DB 世界观顾问/润色师 role_key 为空（v1.5 迁移前） | 前端按 role_key 派生 → 该角色不渲染（现状）；迁移脚本补值后恢复渲染 | 无（一次性迁移，§5.7.1） |
| 自定义 Agent 进链（v1.5） | Agent 管理创建 → role_key 分配 → 角色池出现 → 添加进链（agent_roles 三态）→ 执行（prompt = AgentEntity.system_prompt） | 无（设计语义；删除 Agent 后链引用清理见下） |
| 自定义 Agent 被删除（v1.5） | 链中残留 `agent_roles` 键与 agent_order 引用 → 执行层跳过 + warning（prompt 缺失防御，§2.3）；UI 角色池不再显示该角色 | 防御跳过（§5.7.2） |
| 模板引用已删除自定义 Agent（v1.5） | 模板 roles 快照保留（模板是快照）；执行时模板键 → Agent 真源缺失 → prompt 缺失跳过 + warning | 防御跳过（§5.7.5） |
| 添加角色时角色池为空（v1.5） | 「添加角色」按钮禁用/提示「全部角色已在链中」 | 无（UI 边界） |
| 模板自定义键无 Agent 实体（v1.5 兼容） | 链仍渲染该模板自定义角色行（既有语义，模板 roles 是链字段补充来源，§5.7.2）——与 Agent 管理真源并行存在 | 无（兼容既有模板） |

---

## 8. 文件结构

> 对照真实源码树（2026-08-12 实证）。文件路径以主仓根为基准。

### 后端

| 动作 | 文件 | 说明 |
|------|------|------|
| MODIFY | `backend/src/inkflow/domain/models/project.py` | ProjectConfig 新增 `agent_order: list[list[str]]` + validator（§2.1） |
| MODIFY | `backend/src/inkflow/infrastructure/agent/pipeline_templates.py` | ① **修正 reviser.input_from 补 "writer"（v1.3 F4）**；② 注册 `builtin:write_auto` / `builtin:write_continue` 两个新模板（§5.6，prompt 按场景编写） |
| MODIFY | `backend/src/inkflow/domain/models/agent_template.py` | RoleTemplate 扩展 `prompt: str|None` + `name: str|None`（v1.3 数据面，拆 issue） |
| MODIFY | `backend/src/inkflow/domain/services/agent_service.py` | ① `_merge_role_configs` L232-234 sentinel 解析修复 + 裸名兼容（§5.1）+ prompt 覆盖（role_template.prompt 非 None 时）；② 新增模块级 `_apply_agent_order(stages, agent_order, enabled_roles)`（双模式分派 + 跳过过滤 + 自定义 stage 构造 + 层级重排 + 全连接边 + 一致性校验，§5.3.1）；③ `execute` 装配顺序定稿（启用集合 → apply → merge → run，F3） |
| MODIFY | `backend/src/inkflow/infrastructure/agent/langgraph_pipeline.py` | validate 放宽多入口/多终点（L57-62）+ 可达性检查（O2）；execute 多 START/END 边（L120-126）；`_NODE_MAP` 白名单 → 通用节点映射 + 删除「未知阶段类型」检查（L33-38/L111-112，v1.2）；终点角色类型校验（v1.3 成品身份） |
| MODIFY | `backend/src/inkflow/infrastructure/agent/pipeline_nodes.py` | **4 具名节点 → `generic_node`（upstream_keys 从 stage.input_from 推导，v1.2）**；`_build_messages` 注入键集 = input_from ∪ 占位符扫描 + `.get` 防御 + 同层强制空（L58-64，v1.3 B8） |
| MODIFY | `backend/src/inkflow/api/routers/project.py`（或 `domain/services/project_service.py`，实现确认） | agent_order API 层语义校验 → 422（§2.3）；存量裸名规范化钩子（F6，拆 issue） |
| MODIFY | `backend/src/inkflow/api/routers/writing.py`（或 agent.py） | GUI 写作入口 → 管线 execute 接线（§5.6，拆 issue） |
| MODIFY | `backend/tests/unit/test_agent_service.py`（既有文件，追加） | ① sentinel 不覆盖断言（mock LLM 收 model 参数）；② 裸名回退；③ `_apply_agent_order` 双模式/层级重排/跳过/回退/全连接边/一致性校验契约 |
| MODIFY | `backend/tests/unit/test_langgraph_pipeline.py`（既有文件，**预期修改清单 R1**） | ① `test_validate_multiple_entries`/`test_validate_no_terminal`/`test_execute_invalid_config_raises`：断言反转（放宽后合法）；② `test_execute_unknown_stage_type_raises`：删除（守卫移除）；③ `test_execute_node_pipeline_error_propagates`/`test_execute_node_generic_exception_wrapped`：monkeypatch 目标改通用节点；④ 追加层级拓扑/并行层/终点角色校验/可达性测试 |
| CREATE | `backend/tests/unit/test_project_config_order.py`（若既有测试过厚则独立） | ProjectConfig.agent_order 存储层校验（结构/空槽/长度 >10/跨层重复） |
| MODIFY | `tests/cli/test_cli_project*.py`（既有，追加） | PATCH config.agent_order 经 CLI 读写契约（依赖 #251；未合入则降级 API 层测试，§4） |
| MODIFY | `backend/src/inkflow/domain/services/agent_entity_service.py`（v1.5） | `BUILTIN_AGENT_SPECS` 世界观顾问/润色师 `role_key: None` → `"worldview"`/`"polisher"`（§5.7.1）+ 自定义 Agent 创建时 role_key 分配（slug 化 + 冲突后缀，§5.7.2） |
| MODIFY | `backend/src/inkflow/domain/services/agent_service.py`（v1.5） | `_apply_agent_order`/装配点扩展：模板 stages 缺失角色（6 内置新增 2 + 自定义 Agent）构造占位 stage，prompt/name 从 AgentEntity 真源取（注入 AgentRepositoryProtocol 或数据缓存，§5.7.4）；成品身份规则扩展（worldview/polisher 为内容角色） |
| MODIFY | `backend/src/inkflow/api/routers/agents.py`（或 agent_entity 服务，v1.5） | `POST /api/v1/agents` 响应含分配后 role_key；`GET /api/v1/agents` 透出（#473 既有，无契约破坏） |
| CREATE/MODIFY | `backend/tests/unit/test_agent_entity_service.py`（v1.5，追加） | ① role_key 全集 6 契约（内置 4+2）；② 自定义 Agent role_key 分配（slug/冲突后缀/不可变）；③ seed 迁移（存量 role_key 补值） |
| MODIFY | `backend/tests/unit/test_agent_service.py`（v1.5，追加） | 模板 stages 缺失角色 stage 构造（worldview/polisher/自定义，prompt 真源断言）；成品身份扩展断言（worldview 排最后 → 成品 = worldview 输出） |

### 前端

| 动作 | 文件 | 说明 |
|------|------|------|
| MODIFY | `frontend/packages/renderer/src/components/AgentChainCard.tsx` | 三态模型 Select 条件渲染 + 未注册/格式标记 + **槽位号编辑（0-9，同号=并行组；上移/下移=跨槽快捷操作，v1.3 口径统一）** + **自定义角色行（数据源 = 内置 4 + 当前模板 roles，v1.3 拆 issue；v1.5 #484 升级为 Agent 管理全量真源派生 + 添加角色入口，见下 v1.5 行）**（§5.2 + §5.3 + §5.3.4 + §5.7）；保留 switch aria-label 与 data-testid=agent-chain-card（E2E 契约 O1） |
| MODIFY | `frontend/packages/renderer/src/stores/models.ts` | chat 模型扁平化 selector（provider/model 选项列表） |
| MODIFY | `frontend/packages/renderer/src/stores/project.ts` | ProjectConfig 接口新增 `agent_order?: string[][]`（类型注释同步 §2.2 三态表） |
| MODIFY | `frontend/packages/renderer/src/pages/settings.tsx` | 默认模型 Select 硬编码 → provider-configs chat 模型列表（Q3 修复，L422-439） |
| MODIFY | `frontend/packages/renderer/src/pages/writing.tsx`（或等效写作页） | 「全自动生成/续写」按钮 → 管线 execute + 执行状态展示（§5.6，拆 issue） |
| CREATE | `frontend/packages/renderer/src/components/AgentChainCard.test.tsx` | **新建**（现状无此测试文件，2026-08-12 实证）：三态交互 + 模型 Select 数据源 mock + 未注册/格式标记 + 槽位号编辑契约 |
| MODIFY | `frontend/packages/renderer/src/pages/settings.test.tsx`（既有，**预期修改清单 R1**） | ① L776-781 默认模型下拉选项断言（openai/deepseek/ollama → provider-configs chat 列表）；② L1233-1252 回读/选择断言改 provider/model；③ L666-668 fixture 裸名 agent_* 改 provider/model（O2） |
| MODIFY | `frontend/packages/renderer/src/components/AgentChainCard.tsx`（v1.5） | `BUILTIN_ROLE_KEYS`/`BUILTIN_FIELDS` 4 键硬编码删除 → 内置行/自定义行均从 `GET /api/v1/agents` 派生（§5.7.2）；新增「添加角色」按钮 + 角色池选择器（§5.7.3，data-testid=agent-chain-add-role） |
| MODIFY | `frontend/packages/renderer/src/components/AgentRelationEditor.tsx`（v1.5） | `ROLE_FIELDS` 4 键硬编码删除 → 角色列表从 `GET /api/v1/agents` 派生（§5.7.2，F46 #270 依赖编辑器联动） |
| MODIFY | `frontend/packages/renderer/src/components/TemplateDialog.tsx`（v1.5） | `ROLES` 4 键硬编码删除 → 角色编辑列表从 `GET /api/v1/agents` 派生（任意角色组合，§5.7.5） |
| MODIFY | `frontend/packages/renderer/src/stores/templates.ts`（v1.5） | `AgentTemplateInput.roles` 4 键契约 → `Record<string, AgentTemplateRole>`（后端已任意键，§5.7.5） |
| MODIFY | `frontend/packages/renderer/src/components/AgentChainCard.test.tsx`（v1.5，追加） | ① role_key 6 派生（世界观顾问/润色师行渲染）；② 添加角色交互（角色池 → 三态 + agent_order）；③ 自定义 Agent 行（Agent 管理真源） |
| MODIFY | `frontend/packages/renderer/src/components/TemplateDialog.test.tsx`（v1.5，追加） | 任意角色组合（6 内置 + 自定义，roles Record 保存） |

> 后端 API 校验落点（router 层 vs service 层）标注「实现确认」：router 层贴近 422 语义（既有 `_run_service` 异常映射模式），service 层贴近复用；两者皆可，实现时按测试可 mock 性选择。

---

## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 模型/契约（后端） | ProjectConfig.agent_order 默认空/结构/空槽允许（空槽）/长度 >10 拒绝/跨层重复拒绝；agent_* 三态 validator 回归 | ≥90% |
| 服务（后端） | `_merge_role_configs` sentinel 不覆盖 + 裸名回退 + prompt 覆盖（mock LLM 断言 model/system_prompt 参数）；`_apply_agent_order` 双模式分派（空=默认模板模式 null 不跳过）/层级重排（含并行层）/跳过过滤/空回退/非法回退/全连接边（input_from=前序全部、output_to=后序全部）/一致性校验 | ≥90% |
| 集成（后端） | LangGraphAgentPipeline 层级拓扑 validate() 通过（多入口/多终点 + 可达性）；**并行层断言契约（v1.3 R2）：mock 升级为 per-role 响应表（按 stage.id 分发非调用序）——「层间顺序确定」断言 = 调用序号单调（层 2 全部 > 层 1 全部）；「层内并行」降级为不变量「同层角色均被执行 + input_from 无同层引用」（不承诺调用序）**；环检测回归；未执行角色空注入（`.get` 防御）；**未来层引用/同层互引 → 空串（占位符扫描注入，B8）**；**自定义角色执行（模板 roles 装配 prompt → 通用节点，v1.2/v1.3）**；**终点角色类型校验（成品身份）**；**双模板（write_auto/write_continue）注册与执行契约（v1.3 B2）** | ≥90% |
| 前端组件 | AgentChainCard 三态交互（Switch 开→Select 出现；「跟随默认」→ sentinel；选模型→模型名；off→null）；未注册/格式标记；槽位号编辑（0-9，改号 → PATCH 结构正确）；Select 选项 = provider-configs chat 模型 mock | ≥90% |
| E2E（如扩） | 设置页 Agent 分类：开角色→选模型→PATCH 落库→重启保持（#268 验收）；调槽位→PATCH→重启保持 + 写作按槽位序执行（#269 验收）；**写作页全自动/续写 → 管线执行（stderr 可查模型名/层序，v1.3 B2）**——落点 `tests/e2e/e2e-settings.spec.ts` + `e2e-writing.spec.ts`（如存在）追加；**E3-1 switch 计数 4 与 E3-2 默认模型选项断言按 R1 清单修改** | 手工/E2E |
| E2E（v1.5 #484，如扩） | **E4-1 链增删改**：添加世界观顾问 → 行渲染 + PATCH agent_worldview/agent_order → 重启保持；关闭 → 从 agent_order 移除（数据断言）；**E4-2 自定义 Agent 进链**：Agent 管理建自定义 Agent → 角色池出现 → 添加进链 → 执行（stderr 可查）；**E4-3 模板任意角色**：TemplateDialog 编辑含世界观顾问的模板 → 保存 → 回读保持 | 手工/E2E |
| 回归 | 除 §8 R1 预期修改清单外全仓零回归（agentic 路径不动；extraction default_model 消费链回归 + 裸名兼容断言）；v1.5 回归面：AgentChainCard/AgentRelationEditor/TemplateDialog 三组件派生改造后既有测试更新（R1 清单追加 v1.5 修改文件） | 全仓 ≥60%（ADR-027 门禁） |

**RED 形态**：后端 `_apply_agent_order` 不存在 → ImportError；sentinel 修复 → 断言 `llm.chat(model)` 参数 ≠ `__default__` 失败；validate 放宽 → 并行层构造断言失败；前端 Select/序号缺失 → RTL 查询失败。

**测试无网络约束**：模型列表数据源一律 mock `apiFetch`（既有 `stores/models.test.ts` 模式）；管线执行 mock LLMClientProtocol（既有 test_agent_service 模式）；并行断言用 asyncio.gather 顺序记录。

---

## 10. 不在范围内

| 项 | 归属 |
|----|------|
| #270 关联关系编辑（agent_relations 语义/UI，同层条件/分支边） | 0.9.0（本模块仅预留演进约束，§5.4） |
| F29 Supervisor 自主编排 + HITL + subagent | #161（0.8.0 W5，🔗#269 合入后） |
| F27 agentic 路径多角色化 / 按 agent_order 编排 | 不规划（F27 为单 agent 闭环；如需「顺序多 agent」属新产品决策，另行拍板） |
| 自定义 Agent 能力差异化白名单（#257，角色能力声明/路由） | 0.9.0 F39-F41（本模块已解锁「模板定义角色 → 管线执行」链路，§5.3.4） |
| **自定义 Agent 数据面**（RoleTemplate prompt/name + ProjectConfig 自定义字段 + AgentChainCard 自定义行） | **0.8.0 实现，拆 2-3 个 issue**（v1.3 用户拍板）：① RoleTemplate 扩展 + _merge_role_configs prompt 覆盖；② ProjectConfig extra 自定义角色三态字段 + API 校验口径；③ AgentChainCard 自定义角色行 UI。验收锚点 = 用户可在 UI 创建/编排/执行自定义 Agent 全链路 |
| **GUI 写作入口管线化**（write_auto/write_continue 模板 + 写作页接线） | **0.8.0 实现，拆 2 个 issue**（v1.3 用户拍板）：① 模板注册 + prompt 编写；② 写作页入口切换 + 执行状态 UI（§5.6） |
| 拖拽排序 UI | 本期上移/下移（层级移动，§5.3）；拖拽标注 0.9.0 候选 |
| 模型存在性强制校验（不存在拒绝保存） | #268 方案 3 明确「不存在允许保存但标记」——强制校验不规划 |
| AgentTemplate 自定义拓扑按 agent_order 重排 | 不规划（模板拓扑 = 模板作者意图，§5.3.4 边界） |
| agent_order 与 F29 supervisor 编排衔接 | #161 spec 定义 |
| 全局默认模型选项进 agent_order | 无此语义（agent_order 是角色拓扑，非模型） |
| config.model 存量裸名数据迁移（DB 改写） | 不规划（执行层兼容回退零迁移，§5.1；新数据 UI 引导修正） |
| Agent 管理 CRUD 本身（Agent 列表/创建/编辑/删除 UI） | 0.9.0 F41（#260 已实现，本模块只消费其角色池，§5.7.2 不重复实现） |
| 自定义 Agent role_key 手动指定 UI（创建时显式填） | 实现拆 issue 时定稿（§5.7.2 默认服务层自动分配；显式指定不阻塞） |
| 链角色拖拽重排 | 0.9.0 候选（本期上移/下移，§5.3） |
| 模板角色「场景化 prompt 向导」（为世界观顾问/润色师自动生成场景 prompt） | 不规划（prompt 从 Agent 真源取，模板 roles 为可选覆盖，§5.7.4） |

---

## 11. 依赖关系

- **依赖**：#225 三态语义（✅ 0.7.0 已合入，本项目扩展执行层解析）、F26 deepagents 集成（✅ PR #236，模型名剥离复用）、F27 agentic writer（✅，兼容性边界 §5.5）、**#473 角色单一来源（✅ PR #492 已合入——role_key 映射真源，v1.5 链动态化前置，§5.7）**、F41 Agent 管理（✅ #260 已实现——角色池来源，§5.7.2 消费其 `GET /api/v1/agents`）、#251 CLI project update（⏳ 0.8.0 W2 P1——agent_order CLI 读写联动，§4）、F9/F13/F34 服务（✅，工具包装对象无关本项目）、`project.config.model` 消费链（✅ 实证：extraction_service L670/717 作为 default_model——Q3 格式统一的影响面，修复后需回归提取域）。
- **被依赖**：#269 🔗 #268（模型选择先于顺序编辑——roadmap 轨道 B 串行）；#161 F29 🔗 #269 合入后（同编排域串行，roadmap 风险表）；#270 🔗 #269（DAG 演进基线，§5.4）；**#484 🔗 #473（链动态化前置 role_key 单一来源，v1.5）**；F46 #270 关系编辑器 🔗 链动态化（AgentRelationEditor 角色列表随真源派生，§5.7.2——F46 实现 PR #412 已合入，v1.5 修订影响其前端组件，S2 实现时同步改）。
- 编号口径声明：F39/F40/F41 已分配给 0.9.0 多 Agent（#258/#259/#260），本模块 F42 编号依据 roadmap 拍板记录 9（2026-08-12）。
- deepagents 兼容性（已确认）：agent_order 消费方仅 LangGraphAgentPipeline；deepagents 装配零改动（§5.5）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 备选（否决理由） |
|------|------|-----------------|
| #268+#269 合并一份 spec | **F42 单 spec 覆盖两 issue（roadmap 拍板记录 8/9）** | 两 spec 分开（两期配置面同一组件/同一文件域，分开会产生双份真相；用户拍板「正式 spec 合并一份」） |
| 执行拓扑实现方式 | **`_apply_agent_order` 纯函数重建全连接边（层级模型，Q1 拍板）** | ① 改 stages 列表顺序（无效——LangGraph 按 DAG 边调度，实证 L120-126）；② 自由任意序无约束（字面量残留 + 无意义输出，反思实证 `_render` L44）；③ 形态预设（与 AgentTemplate 域重叠，范围膨胀） |
| 顺序配置存储 | **`agent_order: list[list[str]]` 层级嵌套（Q1 拍板升级）** | v1.0 `list[str]`（无法表达并行）；extra 字典（类型安全弱、无 validator）；position 字段硬编码在 stage（与 DAG 边冲突，堵死 #270） |
| null 关闭语义 | **真禁用——跳过 + 下游空输入（Q2 拍板）** | 保持现状（UI「关闭」承诺不兑现，#225 语义缺口遗留）；成本修正 +1-2 人天（空注入机制既有 pipeline_nodes L55） |
| 校验双层 | API 422 + 执行层回退 | 仅 API 校验（存量损坏数据会中断写作）；仅执行层回退（非法输入无即时反馈） |
| `__default__` 执行解析 | sentinel 不覆盖模板模型（`_merge_role_configs` 修复） | 保持现状（执行 ValueError 缺陷）；节点层判断（散落 + 节点不纯净） |
| 模型格式 | **全链路 provider/model（Q3 拍板）** | 保持现状三种格式并存（config.model 裸名 + AgentPanel 裸 provider 名 + 模板合规名——parse_model_string 硬契约下是定时炸弹，extraction 消费链实证） |
| 模型选择数据源 | provider-configs chat 模型列表（Q3 拍板后自然成立） | 硬编码（用户自定义 provider 无法选）；ModelsPanel 六槽位先行（#106 是 provider 管理域，范围膨胀） |
| 变量注入 | 前序全层注入 + 未执行空注入（§5.3.3） | 只注入直接上游（重排后字面量残留）；字面量保留（prompt 损坏，不可接受） |
| 引擎 | 单链 → 分层并行（validate/execute 放宽） | 保持唯一入口/终点（层级并行不可表达）；重写为通用 DAG 引擎（#270 才需要完整度，YAGNI） |
| 执行节点容量 | **10 槽（编号 0-9），默认模板 0-3（v1.2 拍板）** | 限 4 内置（自定义 Agent 无法执行，与模板 roles 既有装配能力脱节）；无限槽位（无上限约束，UI/校验失控） |
| 节点实现 | **4 具名节点 → 通用节点（upstream 从 input_from 推导，v1.2）** | 保留具名 + 新增自定义节点（每角色一份节点代码，无法扩展）；具名节点硬编码 upstream 保持（与重排拓扑脱节，v1.1 漏洞实证） |
| null 生效范围 | **双模式（v1.3 B1 拍板：默认模板模式不跳过 / 配置驱动模式真禁用）** | 无条件真禁用（默认项目全空转，评审 F1 实证）；无条件跟随模板（Q2 真禁用承诺落空） |
| GUI 写作路径 | **入口管线化 + 双模板 write_auto/write_continue（v1.3 B2 拍板）** | 仅 CLI/API 消费（#268/#269 验收在 GUI 主路径不可达，评审 🔴-3 实证）；agentic 路径多角色化（F27 单 agent 闭环被破坏，超范围） |
| 自定义 Agent 数据面 | **0.8.0 拆 issue 实现（v1.3 拍板：RoleTemplate prompt/name + ProjectConfig 自定义字段 + UI）** | 0.9.0 顺延（自由排序核心动机落空，评审 🔴-2 实证）；本期不做（槽 4-9 是空承诺） |
| 成品身份 | **reviser 输出；违规终点回退 + warning（v1.3 评审 🔴-1 修正）** | 不定义（调整顺序/禁用后成品类型静默漂移） |
| CLI 归属 | #251 联动（已确认） | F42 内补 CLI（与 #251 同命令面双改冲突） |
| #270 预留 | 层级 = 拓扑基线、关系 = 增强语义；配置双字段并存关系优先 | 本模块实现 DAG（范围膨胀）；设计不预留（演进被堵死） |
| 链角色集合来源（v1.5 #484） | **真源派生（/api/v1/agents，role_key 单一来源）**——三组件统一规则 | 前端维护角色键白名单（硬编码不随 Agent 管理增减，⑩ 实证——BUILTIN_ROLE_KEYS/ROLE_FIELDS/ROLES 三处 4 键）；后端按模板 stage 白名单（内置模板只 4 角色，世界观顾问/润色师进链无 stage） |
| 世界观顾问/润色师 role_key（v1.5 #484） | **补 `worldview`/`polisher`（稳定标识）** | 保持 None（进不了链，需求 1 落空）；用显示名匹配（中文名做键，脆弱 + i18n 双份） |
| 自定义 Agent 进链身份（v1.5 #484） | **服务层分配稳定 role_key（slug 化 + 冲突后缀）** | 用 Agent id（数字键不稳定，用户不可读）；用显示名（改名后链引用断裂） |
| 执行层 6 内置 stage 构造（v1.5 #484） | **模板 stages 缺失角色 → 占位 stage，prompt 从 AgentEntity 真源取** | 内置模板扩 6 角色（write_chapter 等全扩 → 默认拓扑变化 + 模板数据膨胀）；拒绝进链（需求 1 落空） |
| 模板 roles 任意组合（v1.5 #484） | **TemplateDialog 从真源派生角色列表，roles 存 Record** | 模板 4 角色硬编码（需求 3 落空，自定义 Agent 模板无入口）；模板角色 = 链角色（拓扑与覆盖层混为一谈） |

---

## 13. 验收标准

> 合并 #268 + #269 issue 验收要点（v1.1 按拍板修订）；M1-M3 为 #268（W2），M4-M6 为 #269（W3），M7 收尾。实现 PR 按里程碑分批合入。

- **M1 三态执行修复（#268 后端）**: `pytest backend/tests/unit/test_agent_service.py` — `agent_* = "__default__"` 执行不抛 ValueError 且 mock LLM 收到模板角色模型（非 sentinel）；`agent_* = null` → 角色跳过（Q2 拍板）；裸模型名 → warning + 回退跟随默认
- **M2 模型选择 UI（#268 前端）**: `pnpm vitest run src/components/AgentChainCard.test.tsx`（新建）— 开关打开条件渲染 Select（数据源 mock provider-configs chat 模型）；选「跟随默认」→ PATCH sentinel；选具体模型 → PATCH provider/model；关闭 → PATCH null；未注册/格式不合规值显示标记且保存不阻塞；默认模型 Select（settings.tsx）数据源 = provider-configs chat 列表
- **M3 模型选择持久化 + 写作验证（#268 验收闭环，v1.3 口径修订）**: GUI 打开角色→选模型→保存→重启保持；**写作流程（全自动/续写管线路径，v1.3 B2）按指定模型执行（内核 stderr 可查模型名）**；关闭 → 角色跳过（配置驱动模式，stderr 可查跳过日志）；config.agent_* 值均为 provider/model 或 sentinel 或 null；**agentic 路径不在本验收范围（保持全局默认模型，§1.3 边界）**
- **M4 层级拓扑 + 校验（#269 后端，v1.3 断言契约修订）**: `pytest backend/tests/unit/test_project_config_order.py` + `test_langgraph_pipeline.py` — agent_order 层级结构/空槽允许/长度 >10 拒绝/跨层重复拒绝；PATCH 语义校验 422（缺启用角色）；**任意角色名允许（内置 + 自定义，v1.2）**；存量项目零迁移；**并行层断言 = 层序单调（per-role 响应表 mock，v1.3 R2）**；变量空注入防御（未来层/同层 → 空串）；环检测 + 可达性回归；**终点角色类型校验（成品身份）**
- **M5 执行拓扑重排（#269 集成）**: `pytest backend/tests/unit/test_agent_service.py` — `_apply_agent_order` **双模式分派（空=默认模板模式 null 不跳过）/层级重排（含 `[["architect"],["writer","auditor"],["reviser"]]` 并行场景）/跳过过滤（配置驱动模式）/空回退/非法回退/一致性校验**；全连接边断言（input_from=前序全部、output_to=后序全部）；重排后 validate() 恒通过；**自定义角色执行（模板 roles 装配 → 通用节点，upstream 从 input_from 推导，v1.2/v1.3）**
- **M6 槽位编辑 UI + 持久化（#269 验收闭环，v1.3 口径修订）**: GUI 每角色槽位编号 **0-9**（同编号=并行组）→ PATCH agent_order 层级结构 → 重启保持；默认模板显示槽 0-3；写作流程按槽位序执行（内核 stderr / 执行日志可验证：**层间串行可验证，层内并行不承诺 stderr 序**）；保存时角色级空输入提示（静态依赖分析）；**调整顺序/关闭角色后成品类型不变（reviser 输出）断言**
- **M7 CLI 读写 + 回归（#269 CLI + 全仓）**: 依赖 #251 合入后 `inkflow project get --id N` 输出含 agent_order、update 可写（#251 未合入则降级 API 层验证，PR 标注）；**除 §8 R1 预期修改清单外全仓零回归** + 覆盖率门禁（ADR-027）；spec §8 文件结构逐项核对
- **M8 GUI 写作管线化（v1.3 B2，拆 issue 实现）**: `pytest`（双模板注册/执行契约）+ 手工 — 写作页「全自动生成」→ 管线 execute（builtin:write_auto）按 agent_order/agent_* 执行（stderr 可查模型名/层序）；「续写」→ builtin:write_continue；执行状态展示（进行中/成功/失败 + 成品落章）；**#268/#269 验收原文「写作流程按指定模型/新顺序执行」在 GUI 主路径通过**
- **M9 链动态化 + 模板联动（v1.5 #484，S2 实现轨）**: `pytest backend/tests/unit/test_agent_entity_service.py` + `test_agent_service.py` + `pnpm vitest run src/components/AgentChainCard.test.tsx src/components/TemplateDialog.test.tsx` — ① role_key 全集 6（世界观顾问=worldview/润色师=polisher，存量 seed 迁移补值）；② 链增/删/改角色（添加角色 → 三态 + agent_order → 重启保持；关闭 → 从 agent_order 移除）；③ 自定义 Agent 进链（创建 → role_key 分配 → 角色池 → 进链执行，prompt = AgentEntity.system_prompt）；④ 模板引用任意角色组合（TemplateDialog 角色列表从真源派生，roles Record 保存/回读）；⑤ 执行层缺失角色 stage 构造 + 成品身份扩展（worldview 排最后 → 成品 = worldview 输出）；⑥ 三组件 4 键硬编码删除（AgentChainCard/AgentRelationEditor/TemplateDialog）+ 回归；⑦ GUI 手工闭环：设置页链添加世界观顾问 → 保存 → 重启保持 → 写作按新链执行（stderr 可查）

---

## 待澄清问题

> v1.5 新增（2026-08-19，#484 链动态化 + 模板联动）——用户拍板 D5「本期开发」，需求方向已确认；以下为**实现拆 issue 时定稿的设计细节**，不阻塞 spec 合入：
> - **自定义 Agent role_key 生成规则**（§5.7.2）：默认服务层自动分配（name slug 化 + 冲突后缀）；是否提供创建时显式指定，拆 issue 时定稿（本期至少自动分配可用）。
> - **role_key 迁移形态**（§5.7.1）：存量 DB 世界观顾问/润色师 role_key 补值——迁移脚本 or seed 升级钩子，拆 issue 时定稿。
> - **执行层 Agent 真源注入方式**（§5.7.4）：`agent_service` 注入 AgentRepositoryProtocol vs 复用 `GET /api/v1/agents` 数据缓存，拆 issue 时定稿。

> v1.3 拍板（2026-08-12，三角色评审 findings 处理）—— ✅ 全部已确认：
> - **B1 默认模板兼容**（评审 F1 阻塞）：✅ 用户拍板「不是有默认 agent 模板吗」——`agent_order` 空 = 默认模板模式（null 不真禁用，跟随模板）；非空 = 配置驱动模式（null 真禁用）；前端关闭同步从 agent_order 移除（§2.1/§2.2/§5.3.1）
> - **B2 GUI 写作管线化**（评审 🔴-3/R5 阻塞）：✅ 用户拍板「GUI 写作入口也要切换到多角色管线，相关提示词肯定不一样，所以添加一个默认 agent 管线模板，一个是全自动，另一个是续写」——新增 `builtin:write_auto` / `builtin:write_continue` 双模板 + 写作页入口切换（§5.6/§10/§13 M8）
> - **自定义 Agent 数据面**（评审 F2/🔴-2 阻塞）：✅ 用户拍板「在 0.8.0 里程碑实现，可以在里程碑内拆分多个 issue」——RoleTemplate prompt/name + ProjectConfig 自定义字段 + UI 入口，拆 2-3 个 issue（§5.3.4/§10）
> - 评审实现契约修正（F3-F7/R1-R6/Y1-Y8/O1-O5）已并入正文：装配顺序定稿（§5.3.1）、reviser 模板数据修正 + 占位符校验（§5.3.2）、注入键集=占位符扫描 + 同层强制空（§5.3.3）、成品身份（§5.6）、既有测试变更清单 R1（§8）、并行断言契约 R2（§9）、槽位 UI 口径统一 0-9（§8/M6）、存量裸名策略（§5.1/§11）、估算 8-14 人天。

> v1.2 补充拍板（2026-08-12）：执行节点容量 —— ✅ 已确认（用户拍板：「执行节点仍限 4 内置。这个修改一下，默认有 10 个数字，从 0-9，默认的模板中，agent 就是从 0-3」）——执行槽位 = 10 个编号（0-9），默认模板占 0-3，槽 4-9 预留自定义 Agent；执行节点白名单删除 → 通用节点（§5.3.2/§5.3.4）。正文修订位置：§1.3/§2.1/§2.3/§5.3.2/§5.3.4/§7/§8/§9/§10/§12/§13。

> v1.1 全部 ✅ 已确认（用户拍板 2026-08-12）。条目保留留痕，正文已按拍板结果修订。

- **Q1（阻塞级）：重排语义约束** ✅ 已确认（用户拍板：**自由排序 + 层级序号**，自创方案）
  - 原选项：A. 软降级任意序（字面量残留 → 空注入）／B. 限制依赖序（四角色链下 ≈ 原序，功能空转）／A'. 依赖序约束的参与编辑（建议）
  - **用户拍板（2026-08-12）**：「我还是想自由排序，不然的话用户添加的自定义 Agent 很多的话，启用/关闭列表太长了。或者定义执行顺序，比如 1、2、3、4 所有 agent 都放到这个顺序里，相同顺序的可以并行？」
  - **落地**：`agent_order` 升级为**层级嵌套 `list[list[str]]`**（层=序号、同层并行）；自由排序 + 软降级（未来层引用空注入，§5.3.3）；自定义 Agent 数据层铺路（§5.3.4）；引擎放宽多入口/多终点（§5.3.2）。正文修订位置：§2.1/§2.3/§5.3/§5.4/§8/§9/§12/§13。
- **Q2（阻塞级）：null=「关闭」执行语义** ✅ 已确认（用户拍板：**B 真禁用**，与建议一致）
  - A. 保持现状（null=不指定模型，照常执行；零改动）
  - B. **真禁用**（已拍板——null → 跳过角色，下游空输入降级；agent_order 校验 = 必须含全部启用角色；成本 +1-2 人天，空注入机制既有）
  - 正文修订位置：§2.2/§2.3/§5.1/§5.3.1/§7/§12/§13。
- **Q3（设计决策级）：模型标识格式统一 + 数据源** ✅ 已确认（用户拍板：**A 全链路 provider/model**，与建议一致）
  - A. **全链路强制 provider/model**（已拍板——agent_* + config.model 消费链修复；config.model 裸名默认值与 AgentPanel 硬编码 Select 修复；数据源复用 provider-configs chat 列表；存量裸名执行层兼容回退）
  - B. 保持现状格式混乱 + 仅数据源复用（风险：跟随默认回退踩雷）
  - 正文修订位置：§2.2/§3/§5.1/§5.2/§7/§8/§11/§12。
- **降级项（不占拍板配额，正文已定）**：CLI agent_order 读写归属 = #251 联动（§4）；deepagents 兼容边界 = 实证结论（§5.5）；数据源形态 = Q3 随附（§5.2）。

> 已确认事实（实证留痕）：`__default__` 执行层 ValueError 缺陷必须修（§5.1）；执行顺序真相 = DAG 边非列表序（§5.3）；执行层无角色跳过逻辑（Q2 背景）；agentic 路径读全局默认模型（§5.5）；`config.model` 消费链 = extraction_service default_model（§11）；`_render` 未知占位符字面量残留（Q1 背景，§1.1⑦）。
