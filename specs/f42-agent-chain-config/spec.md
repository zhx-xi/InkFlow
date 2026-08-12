# F42: Agent 链配置驱动编排（agent-chain-config）功能规格

**Spec 版本**: 1.2（拍板补充：执行节点 10 槽 0-9 + 自定义 Agent 执行解锁，2026-08-12）
**日期**: 2026-08-12
**依据**: 0.8.0 路线图拍板记录 5-9（design/inkflow-0-8-0-roadmap-2026-08-12.md）+ Issue #268（Agent 链模型选择）+ Issue #269（Agent 执行顺序编辑）+ #225 三态语义（已合入）+ F26/F27 已合入实现源码核查 + 2026-08-12 用户拍板（待澄清 Q1-Q3 全部确认 + 执行节点 10 槽补充拍板）
**所属阶段**: 0.8.0（轨道 B Agent 编排：F42 spec → #268 → #269 → #161 F29），估算 5-9 人天（#268 前端 2-3 + #269 前后端 3-6，层级并行引擎改造纳入）
**关联 Issues**: #268（模型选择，W2 启动）、#269（执行顺序，W3，🔗#268）、#270（关联关系编辑，0.9.0 预留，不实现）
**依赖**: ✅ #225 三态语义（0.7.0 已合入）· ✅ F26 deepagents 集成层（PR #236 已合入）· ✅ F27 agentic writer（已合入）· ✅ F9/F13/F34 服务（工具包装对象）· ⏳ #251 CLI project update（0.8.0 P1，agent_order CLI 读写联动）· ⏳ #268 先于 #269（编排域串行）
**参考 ADR**: [adr/ADR-035.md](../adr/ADR-035.md)（编排引擎=Deep Agents harness 0.7.5，原字母 ADR-E，#283 已落盘）、ADR-015（LangChain 隔离）、ADR-019（编号口径）
**状态**: 待实现 🔲

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

### 1.2 与样板差异

非 F9 实体 CRUD（无新增表）、非 F26 集成型（无新基础设施包）、非 F27 闭环型（无新业务流程）——本模块是**配置面 + 编排面改造**：后端 ProjectConfig 扩展 1 字段 + 执行链拓扑重构（单链 → 分层并行）；前端 AgentChainCard 交互升级（模型选择 + 层级序号）。

### 1.3 边界声明

- **不含** #270 关联关系编辑（`agent_relations`，0.9.0）：本模块实现**层级顺序**（层间串行 + 层内并行 = DAG 拓扑层特化），关系增强语义（同层内条件/分支边）留给 0.9.0。配置模型与执行链设计**不得堵死** DAG 演进（§5.4 演进约束）。
- **不含** F29 Supervisor 自主编排（#161，0.8.0 W5）：supervisor 消费 deepagents subagent 机制，与本模块的 agent_order 管线编排不同域（§11 依赖关系）。
- **不含** F27 agentic 写作路径的多角色化：F27 AgenticWriterService 为 deepagents 单 agent（writer_agent）ReAct 循环，`model=config.llm_default_model`（全局默认，`api/deps.py` L220-240）——**不消费** `agent_*` 四角色字段与 `agent_order`（§5.5 兼容性结论）。
- **执行槽位 = 10 个编号（0-9，v1.2 拍板）**：执行节点**不再限 4 内置**——任意角色名可执行（通用节点 + upstream 从 input_from 推导，§5.3.2）；默认模板占槽 0-3（architect/writer/auditor/reviser），槽 4-9 预留自定义 Agent；自定义角色 prompt 由 AgentTemplate.roles 提供（§5.3.4）。多 Agent 能力差异化白名单（#257）仍归 0.9.0 F39-F41。

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
    - 角色名支持任意字符串（自定义 Agent，v1.2 执行解锁 §5.3.4）
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
| `null`（缺失） | **关闭（Q2 拍板：真禁用）** | **跳过该角色**——不执行；下游角色以空输入降级运行（复用 pipeline_nodes L55 空注入机制）；从执行拓扑摘除（§5.3.2） | Switch off |
| `"__default__"`（AGENT_DEFAULT_SENTINEL） | 跟随默认 | **修复点**：不覆盖模板角色模型（v1.0 缺陷会 ValueError，§5.1） | Switch on + Select 选中「跟随默认」 |
| `"<provider>/<model>"`（如 `"zhipu/glm-4.5"`） | 指定模型 | 覆盖模板角色模型（parse_model_string 剥离前缀后调用） | Switch on + Select 选中具体模型 |

> 存储格式说明（Q3 拍板）：`agent_*` 与 `config.model` 具体模型值**全链路强制 `provider/model` 格式**（与 `ProviderConfig.default_model` 同格式、与 `parse_model_string` 解析契约一致）——不允许存裸模型名/裸 provider 名（无 `/` 会在执行层 ValueError，实证：extraction_service L670/717 default_model 消费链）。

### 2.3 agent_order 校验（双层 + 启用角色口径）

| 层 | 行为 | 位置 |
|----|------|------|
| 存储层（Pydantic） | 结构 + 跨层去重 + 长度 ≤10（§2.1） | `domain/models/project.py` |
| API 层（PATCH） | 语义校验：非法 → **422**（detail 中文说明）；非法定义 = ① 跨层重复（存储层已拒，防御）② **不含全部启用角色**（Q2 拍板口径：启用 = agent_* 非 null；关闭角色可不出现在 agent_order）——**角色名任意**（内置 4 + 自定义均可，v1.2） | `api/routers/project.py`（或 `project_service.py`，实现确认） |
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

---

## 3. API 契约

**无新增 REST 端点**。所有变更走既有 `PATCH /api/v1/projects/{id}`（`api/routers/project.py` L97-109）config 部分合并语义（`project_service.py` L139-143：`model_dump(exclude_unset=True)` + `existing.config.model_copy(update=config_updates)`）——agent_order 作为 ProjectConfig 新字段自动纳入，前端 PATCH 传 `{config: {agent_order: [...]}}` 即可。

| 变更 | 端点 | 说明 |
|------|------|------|
| PATCH config 扩展 | `PATCH /api/v1/projects/{id}` | body `config.agent_order`（list[list[str]]）+ `config.agent_*`（三态值）按既有合并语义生效 |
| agent_order 非法 | 同端点 | 422，detail 中文（§2.3 API 层） |
| 模型存在性提示 | 无新端点 | **不校验存在性**（#268 方案 3：不存在允许保存）——前端标记（§5.2）；数据源 = `GET /api/v1/provider-configs` chat 模型列表 |

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

#### 5.3.1 `_apply_agent_order(stages, agent_order) -> list[PipelineStage]`（v1.1 核心，纯函数）

1. 输入：模板 stages（4 阶段链式）+ 项目 config.agent_order（层级嵌套角色字段名数组）
2. 空列表 → 原样返回（模板默认拓扑，零迁移）
3. 语义校验（执行层防御）：非法（缺启用角色/长度 >10/跨层重复）→ 记 warning + 原样返回（回退默认）；**角色名任意（内置 + 自定义均允许，v1.2）**；空槽（[]）正常跳过
4. **跳过过滤**（Q2 拍板）：agent_* = null 的角色先从集合摘除（无论是否在 agent_order 中；§2.3 关闭角色语义）
5. **层级映射**：`agent_xxx → xxx`（stage.id）；按层序重组 stages
6. **全连接边重建**：第 i 层每节点 `input_from` = **前序全部层所有角色**；`output_to` = **后序全部层所有角色**（跨层直连全连接 DAG——执行依赖传递闭包 + 变量注入自然全量；DAG 边多不影响 LangGraph 拓扑序）
7. 返回重排后的 stages，后续 `_run_pipeline` 不变

- **装配位置**：`_merge_role_configs` **之后**（模型装配与拓扑无关；但跳过过滤需在模型装配**前**获知启用集合——实际顺序：`execute` 中先读 agent_* 得启用集合 → `_apply_agent_order`（含跳过过滤 + 重排）→ `_merge_role_configs`（只装配存留角色）→ `_run_pipeline`——实现确认，测试锚点不变）。
- **默认拓扑**（空 agent_order）：`[[architect],[writer],[auditor],[reviser]]`——与现模板链等价（层间全连接退化为链，因每层单角色）。

#### 5.3.2 引擎放宽（`langgraph_pipeline.py` + `pipeline_nodes.py` MODIFY）

- **validate()**（L50-93）：「唯一入口」（L57-60）/「唯一终点」（L61-62）约束**放宽**为「至少一个入口/终点」——层级并行下第一层多角色（无 input_from）都是入口、最后一层多角色（无 output_to）都是终点；**环检测（Kahn）与引用存在性保留**（L64-93 不变）。
- **execute()**（L95-138）：入口连接从 `workflow.set_entry_point(entry.id)`（L120-121）改为**每个入口节点 `add_edge(START, entry_id)`**；终点从 `workflow.add_edge(terminal.id, END)`（L125-126）改为**每个终点节点 `add_edge(terminal_id, END)`**（LangGraph 1.x 支持多 START/END 边；实现时以实测为准，若 API 限制则用 conditional entry 兜底——标注实现确认）。
- **节点泛化（v1.2 拍板）**：`_NODE_MAP`（L33-38）从 4 具名节点白名单（architect_node/writer_node/auditor_node/reviser_node，pipeline_nodes.py L124-141）改为**通用节点映射**——任意 stage.id → `generic_node`：
  - 现状实证：4 具名节点只是 `_call_llm_node(state, stage_id, upstream_keys)` 的参数化包装，**upstream_keys 硬编码在具名节点里**（architect=[]/writer=["architect"]/auditor=["writer"]/reviser=["writer","auditor"]）——与 v1.1 重排拓扑（input_from 重建）**脱节**（重排后节点仍按硬编码 keys 注入，变量语义错乱）
  - 修复：`generic_node(state)` 从 `state["stages"][stage.id].input_from` **推导 upstream_keys**（不再硬编码）；`langgraph_pipeline.execute` L111-112 的「未知阶段类型」检查删除（任意 stage.id 可执行）
  - 自定义角色 prompt 来源：`stage.agent.system_prompt`（由 `_merge_role_configs` 从 AgentTemplate.roles 装配，§5.3.4）
- 并行层内节点执行顺序：LangGraph 同层并行调度（asyncio），**层间顺序确定、层内顺序不确定**——验收「按配置顺序执行」口径 = 层序确定（§13 M4）。

#### 5.3.3 prompt 变量注入改造（`pipeline_nodes.py` MODIFY——消除字面量残留）

- `_build_messages`（L47-68）：变量注入从「直接上游」扩展为「**input_from 全部**」（全连接后 = 前序全层），且**未执行角色输出给空串**：
  ```python
  for key in upstream_keys:
      sr = state["results"].get(key)          # ← .get 防未执行 KeyError
      variables[f"{key}_output"] = sr.output if sr else ""
  ```
- **效果**：任意引用前序角色的 `{xxx_output}` 都有值（实际输出或空串）；引用**未来层**角色（用户自由排序导致）→ 空串（软降级，用户自由排序的明确代价——UI 保存时提示「调整顺序后，后续角色的输入可能为空」）；`_render` L44 的「未知占位符原样保留」路径只对**拼写错误**的变量生效（兜底，不阻断）。
- user 消息 parts（L62-64）同源改造（`.get` 防御）。

#### 5.3.4 自定义角色执行（v1.2 拍板：执行解锁）

- `agent_order` **数据模型与校验支持任意角色字段名**（§2.1/§2.3）——内置 4 + 自定义 Agent 均可编排，UI 不限制；执行槽位 0-9（默认模板占 0-3，槽 4-9 预留自定义 Agent）。
- **执行层解锁**：`_NODE_MAP` 白名单删除 → 任意 stage.id 经通用节点执行（§5.3.2 节点泛化）。
- **自定义角色 prompt 装配**：`_merge_role_configs` 既有逻辑已支持任意 stage.id——`template.roles.get(stage.id, RoleTemplate())`（agent_service.py L212-213）从 AgentTemplate.roles 读取自定义角色的 system_prompt/model/temperature 覆盖；角色字段名映射 `agent_<自定义名>` → stage.id `<自定义名>`（§5.3.1 步骤 5 统一转换，无白名单）。
- **prompt 缺失防御**：自定义角色既非内置且当前模板 roles 未定义（system_prompt 为空）→ 执行层**跳过 + warning 日志**（§2.3/§7）——不中断其余角色；模板补定义后即恢复。
- **归属边界**：自定义 Agent 的创建/编辑 UI 复用既有 AgentTemplate（#107 TemplateDialog + agent_templates 路由）；多 Agent 能力差异化白名单（#257）归 0.9.0 F39-F41——本模块只解锁「模板定义角色 → 管线执行」链路。

### 5.4 #270 DAG 扩展预留（0.9.0，本模块不实现）

| 演进约束 | 本模块保证 |
|----------|-----------|
| 层级 = 拓扑层特化 | `agent_order` 层级嵌套是**分层并行 DAG** 的紧凑表示（层间全连接 + 层内并行）；#270 `agent_relations` 是同层内**条件/分支边**的增强语义——配置模型扩展 = 新增并集字段，执行链改造 = 在层间全连接基础上叠加条件边（既有 StateGraph 能力） |
| 执行链设计 | 引擎放宽后的 validate/execute（多入口/终点 + 全连接 DAG）即通用 DAG 引擎子集——#270 无需引擎重写，只需 `_apply_agent_relations`（或扩展 `_apply_agent_order`） |
| 配置模型兼容 | agent_order（list[list[str]]）+ agent_relations（0.9.0 新增）并存：agent_order 定义层基线，agent_relations 定义层内增强——冲突规则（关系优先）由 0.9.0 spec 定义，本模块在 §12 决策记录与 §10 边界声明留痕 |
| 真禁用（Q2） | 跳过 = 节点摘除 + 边重连（§5.3.1 步骤 4）——DAG 节点删除语义与 #270 一致，不破坏拓扑 |
| 并行语义 | 同层并行 = DAG 并行分支；#270 可在同层内加「并行 → 汇合」的汇点角色（如汇总审阅）——层级模型天然支持（汇点 = 后一层单角色） |

### 5.5 deepagents 兼容性结论（实证，已确认非拍板点）

- agent_order **仅消费方 = LangGraphAgentPipeline**（四角色链管线）——`POST /api/v1/agent/.../execute`（`api/routers/agent.py` L29-30 装配）。
- F27 agentic 路径（`AgenticWriterService` + `build_agentic_writer`）：deepagents **单 agent**（writer_agent）ReAct 循环 + 5 只读 + save_draft 工具，`model=config.llm_default_model`——**无多角色编排概念，不消费 agent_order/agent_***（`api/deps.py` L220-240 实证）。
- F29 Supervisor（#161，0.8.0 W5）：deepagents subagent 机制分层编排，与 agent_order 管线编排**不同抽象层**——#269 的「注意 deepagents harness 兼容」结论：**无冲突**，agent_order 不触碰 deepagents 装配；F29 spec 需单独定义 supervisor 与管线的衔接（同编排域串行：必须 #269 合入后 #161 再开，roadmap 风险表已声明）。
- 模型名剥离：agent_* 具体模型值（provider/model 格式）在 LLM 调用链既有剥离逻辑（F26 §5.5 `parse_model_string` 复用）——本模块不新增剥离代码。

---

## 6. 组织规则

- ProjectConfig 扩展遵循既有 Pydantic 模型约定（domain 层零框架依赖）；`AGENT_DEFAULT_SENTINEL` 保持 `domain/models/project.py` 定义（唯一真相源），前端 `stores/project.ts` L18 镜像常量（既有双份模式，注释互指）。
- `_apply_agent_order` 归属 domain 服务层（纯函数，不依赖 infrastructure）——放在 `agent_service.py` 模块级函数（非类方法），便于独立单测。
- 引擎放宽（validate/execute）与变量注入改造归属 infrastructure 层（langgraph_pipeline.py / pipeline_nodes.py）——domain 层不感知 LangGraph API。
- 前端模型选择数据源走既有 `stores/models.ts`（ProviderConfig/ProviderModel 接口已有）——不新建 provider store；AgentChainCard 保持「展示组件 + 回调」模式（onConfigChange 即改即存，`settings.tsx` persist 链路不变）。
- 执行层 `__default__` 解析在 `_merge_role_configs`（唯一模型装配点）——不在节点层（pipeline_nodes.py）做 sentinel 判断，保持节点纯净（节点只消费装配后的 AgentRole）。

---

## 7. 边界情况与错误处理

| 场景 | 行为 | 错误面 |
|------|------|--------|
| agent_* = `__default__`（v1.0 缺陷路径） | **修复后**：不覆盖模板模型，正常执行（§5.1） | 无（修复点；执行日志可查模型回退） |
| agent_* = 裸模型名（无 `/`） | 执行层 warning + 回退跟随默认（§5.1 兼容策略）；前端格式标记 | 无（存量零迁移；新数据 UI 引导） |
| agent_* = 未知模型名（如 `foo/bar`） | 允许保存（#268 方案 3）；前端「未注册模型」标记；执行时 provider 配置不存在 → LLM 调用失败走既有重试/失败语义 | 执行失败（既有 PipelineError 路径，非本模块新增） |
| agent_* = 空字符串 | 422（既有 validator L79-81） | 输入拒绝 |
| agent_* = null（Q2 真禁用） | 角色跳过执行；下游空输入降级（§5.3.1 步骤 4） | 无（设计语义；日志记跳过） |
| 全部角色关闭 | API 校验拒绝（至少 1 启用角色）；执行层回退默认拓扑 + warning | 输入拒绝 / 防御回退 |
| agent_order 缺省/空列表 | 模板默认拓扑执行（零迁移） | 无 |
| agent_order 含自定义角色名（非内置 4，v1.2 支持） | API 允许；执行层经通用节点执行（prompt 由模板 roles 装配，§5.3.4） | 无（v1.2 解锁） |
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

---

## 8. 文件结构

> 对照真实源码树（2026-08-12 实证）。文件路径以主仓根为基准。

### 后端

| 动作 | 文件 | 说明 |
|------|------|------|
| MODIFY | `backend/src/inkflow/domain/models/project.py` | ProjectConfig 新增 `agent_order: list[list[str]]` + validator（§2.1） |
| MODIFY | `backend/src/inkflow/domain/services/agent_service.py` | ① `_merge_role_configs` L232-234 sentinel 解析修复 + 裸名兼容（§5.1）；② 新增模块级 `_apply_agent_order`（层级重排 + 跳过过滤 + 全连接边，§5.3.1）；③ `execute` 装配顺序调整（启用集合 → 拓扑 → 模型装配） |
| MODIFY | `backend/src/inkflow/infrastructure/agent/langgraph_pipeline.py` | validate 放宽多入口/多终点（L57-62）；execute 多 START/END 边（L120-126）；**`_NODE_MAP` 白名单 → 通用节点映射 + 删除「未知阶段类型」检查（L33-38/L111-112，v1.2）** |
| MODIFY | `backend/src/inkflow/infrastructure/agent/pipeline_nodes.py` | **4 具名节点 → `generic_node`（upstream_keys 从 stage.input_from 推导，v1.2）**；`_build_messages` 变量注入 `.get` 防御 + 空注入（L58-64） |
| MODIFY | `backend/src/inkflow/api/routers/project.py`（或 `domain/services/project_service.py`，实现确认） | agent_order API 层语义校验 → 422（§2.3） |
| MODIFY | `backend/tests/unit/test_agent_service.py`（既有文件，追加） | ① sentinel 不覆盖断言（mock LLM 收 model 参数）；② 裸名回退；③ `_apply_agent_order` 层级重排/跳过/回退/全连接边契约 |
| MODIFY | `backend/tests/unit/test_langgraph_pipeline.py`（既有文件，追加） | 层级拓扑 validate 通过（多入口/多终点）；并行层 mock LLM 调用记录（层序确定、层内并行）；环检测回归 |
| CREATE | `backend/tests/unit/test_project_config_order.py`（若既有测试过厚则独立） | ProjectConfig.agent_order 存储层校验（结构/空层/跨层重复/非法元素） |
| MODIFY | `tests/cli/test_cli_project*.py`（既有，追加） | PATCH config.agent_order 经 CLI 读写契约（依赖 #251；未合入则降级 API 层测试，§4） |

### 前端

| 动作 | 文件 | 说明 |
|------|------|------|
| MODIFY | `frontend/packages/renderer/src/components/AgentChainCard.tsx` | 三态模型 Select 条件渲染 + 未注册/格式标记 + **层级序号编辑**（每行序号 1-N，同序号=并行组；上移/下移=跨层移动，issue #269 UI 语义保留为层级移动）（§5.2 + §5.3） |
| MODIFY | `frontend/packages/renderer/src/stores/models.ts` | chat 模型扁平化 selector（provider/model 选项列表） |
| MODIFY | `frontend/packages/renderer/src/stores/project.ts` | ProjectConfig 接口新增 `agent_order?: string[][]`（类型注释同步 §2.2 三态表） |
| MODIFY | `frontend/packages/renderer/src/pages/settings.tsx` | 默认模型 Select 硬编码 → provider-configs chat 模型列表（Q3 修复，L422-439） |
| CREATE | `frontend/packages/renderer/src/components/AgentChainCard.test.tsx` | **新建**（现状无此测试文件，2026-08-12 实证）：三态交互 + 模型 Select 数据源 mock + 未注册/格式标记 + 层级序号编辑契约 |
| MODIFY | `frontend/packages/renderer/src/pages/settings.test.tsx`（既有） | AgentPanel 交互回归（默认模型 Select 数据源变更 + 防回归） |

> 后端 API 校验落点（router 层 vs service 层）标注「实现确认」：router 层贴近 422 语义（既有 `_run_service` 异常映射模式），service 层贴近复用；两者皆可，实现时按测试可 mock 性选择。

---

## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 模型/契约（后端） | ProjectConfig.agent_order 默认空/结构/空层允许（空槽）/长度 >10 拒绝/跨层重复拒绝；agent_* 三态 validator 回归 | ≥90% |
| 服务（后端） | `_merge_role_configs` sentinel 不覆盖 + 裸名回退（mock LLM 断言 model 参数）；`_apply_agent_order` 层级重排（含并行层）/跳过过滤/空回退/非法回退/全连接边（input_from=前序全部、output_to=后序全部） | ≥90% |
| 集成（后端） | LangGraphAgentPipeline 层级拓扑 validate() 通过（多入口/多终点）；并行层 mock LLM 并发调用（层序确定、层内并行）；环检测回归；未执行角色空注入（`state["results"]` 缺 key 不炸）；**自定义角色执行（模板 roles 装配 prompt → 通用节点调用，mock LLM 断言 system_prompt/顺序，v1.2）** | ≥90% |
| 前端组件 | AgentChainCard 三态交互（Switch 开→Select 出现；「跟随默认」→ sentinel；选模型→模型名；off→null）；未注册/格式标记；层级序号编辑（改序号 → PATCH 结构正确）；Select 选项 = provider-configs chat 模型 mock | ≥90% |
| E2E（如扩） | 设置页 Agent 分类：开角色→选模型→PATCH 落库→重启保持（#268 验收）；调层级→PATCH→重启保持 + 写作按层序执行（#269 验收）——落点 `tests/e2e/e2e-settings.spec.ts` 追加 | 手工/E2E |
| 回归 | 既有全仓测试零回归（agentic 路径不动；extraction default_model 消费链回归） | 全仓 ≥60%（ADR-027 门禁） |

**RED 形态**：后端 `_apply_agent_order` 不存在 → ImportError；sentinel 修复 → 断言 `llm.chat(model)` 参数 ≠ `__default__` 失败；validate 放宽 → 并行层构造断言失败；前端 Select/序号缺失 → RTL 查询失败。

**测试无网络约束**：模型列表数据源一律 mock `apiFetch`（既有 `stores/models.test.ts` 模式）；管线执行 mock LLMClientProtocol（既有 test_agent_service 模式）；并行断言用 asyncio.gather 顺序记录。

---

## 10. 不在范围内

| 项 | 归属 |
|----|------|
| #270 关联关系编辑（agent_relations 语义/UI，同层条件/分支边） | 0.9.0（本模块仅预留演进约束，§5.4） |
| F29 Supervisor 自主编排 + HITL + subagent | #161（0.8.0 W5，🔗#269 合入后） |
| F27 agentic 路径多角色化 / 按 agent_order 编排 | 不规划（F27 为单 agent 闭环；如需「顺序多 agent」属新产品决策，另行拍板） |
| 自定义 Agent 能力差异化白名单（#257，角色能力声明/路由） | 0.9.0 F39-F41 多 Agent 域（本模块已解锁「模板定义角色 → 管线执行」链路，§5.3.4） |
| 拖拽排序 UI | 本期上移/下移（层级移动，§5.3）；拖拽标注 0.9.0 候选 |
| 模型存在性强制校验（不存在拒绝保存） | #268 方案 3 明确「不存在允许保存但标记」——强制校验不规划 |
| AgentTemplate 自定义拓扑按 agent_order 重排 | 不规划（模板拓扑 = 模板作者意图，§5.3.4 边界） |
| agent_order 与 F29 supervisor 编排衔接 | #161 spec 定义 |
| 全局默认模型选项进 agent_order | 无此语义（agent_order 是角色拓扑，非模型） |
| config.model 存量裸名数据迁移（DB 改写） | 不规划（执行层兼容回退零迁移，§5.1；新数据 UI 引导修正） |

---

## 11. 依赖关系

- **依赖**：#225 三态语义（✅ 0.7.0 已合入，本项目扩展执行层解析）、F26 deepagents 集成（✅ PR #236，模型名剥离复用）、F27 agentic writer（✅，兼容性边界 §5.5）、#251 CLI project update（⏳ 0.8.0 W2 P1——agent_order CLI 读写联动，§4）、F9/F13/F34 服务（✅，工具包装对象无关本项目）、`project.config.model` 消费链（✅ 实证：extraction_service L670/717 作为 default_model——Q3 格式统一的影响面，修复后需回归提取域）。
- **被依赖**：#269 🔗 #268（模型选择先于顺序编辑——roadmap 轨道 B 串行）；#161 F29 🔗 #269 合入后（同编排域串行，roadmap 风险表）；#270 🔗 #269（DAG 演进基线，§5.4）。
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
| CLI 归属 | #251 联动（已确认） | F42 内补 CLI（与 #251 同命令面双改冲突） |
| #270 预留 | 层级 = 拓扑基线、关系 = 增强语义；配置双字段并存关系优先 | 本模块实现 DAG（范围膨胀）；设计不预留（演进被堵死） |

---

## 13. 验收标准

> 合并 #268 + #269 issue 验收要点（v1.1 按拍板修订）；M1-M3 为 #268（W2），M4-M6 为 #269（W3），M7 收尾。实现 PR 按里程碑分批合入。

- **M1 三态执行修复（#268 后端）**: `pytest backend/tests/unit/test_agent_service.py` — `agent_* = "__default__"` 执行不抛 ValueError 且 mock LLM 收到模板角色模型（非 sentinel）；`agent_* = null` → 角色跳过（Q2 拍板）；裸模型名 → warning + 回退跟随默认
- **M2 模型选择 UI（#268 前端）**: `pnpm vitest run src/components/AgentChainCard.test.tsx`（新建）— 开关打开条件渲染 Select（数据源 mock provider-configs chat 模型）；选「跟随默认」→ PATCH sentinel；选具体模型 → PATCH provider/model；关闭 → PATCH null；未注册/格式不合规值显示标记且保存不阻塞；默认模型 Select（settings.tsx）数据源 = provider-configs chat 列表
- **M3 模型选择持久化 + 写作验证（#268 验收闭环，手工）**: GUI 打开角色→选模型→保存→重启保持；写作流程（write next / agentic）按指定模型执行（内核 stderr 可查模型名）；关闭 → 角色跳过（stderr 可查跳过日志）；config.agent_* 值均为 provider/model 或 sentinel 或 null
- **M4 层级拓扑 + 校验（#269 后端）**: `pytest backend/tests/unit/test_project_config_order.py` + `test_langgraph_pipeline.py` — agent_order 层级结构/空槽允许/长度 >10 拒绝/跨层重复拒绝；PATCH 语义校验 422（缺启用角色）；**任意角色名允许（内置 + 自定义，v1.2）**；存量项目零迁移；**并行层 mock LLM 并发调用（层序确定、层内并行、变量空注入防御）**；环检测回归
- **M5 执行拓扑重排（#269 集成）**: `pytest backend/tests/unit/test_agent_service.py` — `_apply_agent_order` 层级重排（含 `[["architect"],["writer","auditor"],["reviser"]]` 并行场景）/跳过过滤/空回退/非法回退；全连接边断言（input_from=前序全部、output_to=后序全部）；重排后 validate() 恒通过；**自定义角色执行（模板 roles 装配 → 通用节点，upstream 从 input_from 推导，v1.2）**
- **M6 层级编辑 UI + 持久化（#269 验收闭环）**: GUI 每角色槽位编号 0-9（同编号=并行组）→ PATCH agent_order 层级结构 → 重启保持；默认模板显示槽 0-3；写作流程按槽位序执行（内核 stderr / 执行日志可验证：层间串行、层内并行）；保存时对「未来层引用/同层互引」给出空输入提示
- **M7 CLI 读写 + 回归（#269 CLI + 全仓）**: 依赖 #251 合入后 `inkflow project get --id N` 输出含 agent_order、update 可写（#251 未合入则降级 API 层验证，PR 标注）；全仓测试零回归 + 覆盖率门禁（ADR-027）；spec §8 文件结构逐项核对

---

## 待澄清问题

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
