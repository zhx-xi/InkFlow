# F42: Agent 链配置驱动编排（agent-chain-config）功能规格

> **端**: cross
> **依据**: `design/inkflow-0-8-0-roadmap-2026-08-12.md`, [F26 Agent 工具](../f26-agent-tools/spec.md), [F27 Writer Agent](../f27-writer-agent/spec.md)
> **依赖**: [F9 角色](../f9-character/spec.md) · [F13 伏笔](../f13-foreshadowing/spec.md) · [F26 Agent 工具](../f26-agent-tools/spec.md) · [F27 Writer Agent](../f27-writer-agent/spec.md) · [F34 章节审计](../f34-chapter-audit/spec.md)
> **参考 ADR**: [ADR-035](../../adr/agent/ADR-035.md)（编排引擎 = Deep Agents harness）· [ADR-015](../../adr/llm/ADR-015.md)（LangChain 隔离）· [ADR-019](../../adr/packaging/ADR-019.md)（编号口径）

---

## 1. 概述

**模块类型声明**：本模块为「配置驱动编排型」变体——无新实体表、无新业务端点；在既有 Agent 管线（LangGraphAgentPipeline 四角色链）上增加**配置驱动**能力：① 三态模型选择补全 UI 与执行层解析；② 执行拓扑由模板硬编码改为 `agent_order` **层级配置驱动**（层级 = 拓扑层特化，为 DAG 关联关系铺路）；③ 预留 DAG 关联关系扩展边界（不实现）。编号依据：AGENTS.md 模块类型谱系口径下，F42 为 Agent 化升级链（F26-F29）的配置面补全模块，与 F26（集成层）/F27（闭环）/F28（记忆）平行不冲突。

本 spec 覆盖两期改造：**模型选择**（链配置可指定模型 + 执行层正确解析）与**执行顺序编辑**（层级拓扑配置驱动执行）；DAG 关联关系编辑不在本模块（由 F46 承接，§5.4）。

### 1.1 问题陈述

改造前存在六类缺陷，本 spec 的配置面与执行层变更即针对它们：

1. **模型不可选**：链配置只能写 sentinel（跟随默认），无模型选择 UI；默认模型下拉硬编码 provider 名（非 `provider/model`），违反 `parse_model_string` 硬契约。
2. **执行层 sentinel 误用**：sentinel 被当作模型名覆盖模板模型 → `parse_model_string` 抛错 → 管线失败。
3. **拓扑硬编码**：内置模板四阶段链边写死（architect→writer→auditor→reviser），用户无法调整；无 `agent_order` 配置字段，引擎为单链拓扑（validate 强制唯一入口/唯一终点），不支持并行层。
4. **无角色跳过语义**：配置为 `null`（关闭）的角色照常参与管线，「关闭」与「跟随默认」执行等价。
5. **变量注入不完整**：`_render` 对未知占位符原样保留、`_build_messages` 只注入直接上游输出——任意重排后非上游变量以字面量残留进 system prompt。
6. **角色池硬编码**：6 内置 Agent 仅 4 个有 `role_key`（世界观顾问/润色师缺失 → 进不了链）；前端三处固定 4 键（链/依赖编辑器/模板编辑），不随 Agent 管理增减；模板 `roles` 契约仍 4 键；`--pipeline` 只认内置模板 id，世界观顾问/润色师无管线可执行。

### 1.2 与样板差异

非 F9 实体 CRUD（无新增表）、非 F26 集成型（无新基础设施包）、非 F27 闭环型（无新业务流程）——本模块是**配置面 + 编排面改造**：后端 ProjectConfig 扩展 1 字段 + 执行链拓扑重构（单链 → 分层并行）；前端 AgentChainCard 交互升级（模型选择 + 层级序号）。

### 1.3 边界声明

- **不含** DAG 关联关系编辑（`agent_relations`，由 F46 承接）：本模块实现**层级顺序**（层间串行 + 层内并行 = DAG 拓扑层特化），关系增强语义（同层内条件/分支边）不在本模块。配置模型与执行链设计**不得堵死** DAG 演进（§5.4 演进约束）。
- **不含** F29 Supervisor 自主编排：supervisor 消费 deepagents subagent 机制，与本模块的 agent_order 管线编排不同域（§11 依赖关系）。
- **不含** F27 agentic 写作路径的多角色化：F27 AgenticWriterService 为 deepagents 单 agent（writer_agent）ReAct 循环，`model=config.llm_default_model`（全局默认，`api/deps.py` L220-240）——**不消费** `agent_*` 四角色字段与 `agent_order`（§5.5 兼容性结论）。
- **执行槽位 = 10 个编号（0-9）**：执行节点**不再限 4 内置**——任意角色名可执行（通用节点 + upstream 从 input_from 推导，§5.3.2）；默认模板占槽 0-3（architect/writer/auditor/reviser），槽 4-9 预留自定义 Agent；自定义角色 prompt 由 AgentTemplate.roles 提供（§5.3.4）。多 Agent 能力差异化白名单归 F39-F41。
- **链角色集合动态化**：链不再固定 4 位置——**6 内置角色（含世界观顾问/润色师）+ 自定义 Agent 皆可进链**；角色集合真源 = `/api/v1/agents`（Agent 管理，含 role_key 映射），前端从真源派生而非硬编码（§5.7）。默认拓扑仍为 4 角色链（architect→writer→auditor→reviser，零迁移），用户可增/删/改角色组成自定义链。
- **GUI 写作入口管线化**：GUI 写作「全自动生成 / 续写」入口切换到**多角色管线**（新增 `builtin:write_auto` / `builtin:write_continue` 两个默认模板，§5.6）——`agent_order`/`agent_*` 在 GUI 主路径生效，验收可达。**F27 agentic（工具型单 agent）保持独立入口**（能力不同：工具循环 vs 角色链），不在本模块改造范围；F3 writing_service 单模型路径逐步被管线模板替代（保留兼容，§5.6 边界）。
- **自定义管线拓扑通道**：`--pipeline` / `PipelineExecuteRequest` 可携带**用户显式给定的 stage 拓扑**（`stages` = role_key 序列，或 `pipeline_config` = 完整 YAML 形态）——该通道**不经** `agent_order` / `agent_relations` 修饰（显式拓扑优先，§5.8）。**不含**：内置 6 角色管线补齐（方案 A 不做，§10）、内置 Agent 编辑放开（`PATCH /agents/{id}` → 409 保持）、GUI 侧自定义管线入口（本期仅 CLI + API）。

---

## 2. 数据模型

### 2.1 ProjectConfig 扩展（`domain/models/project.py` MODIFY）

```python
class ProjectConfig(BaseModel):
 # ...既有字段不变（model/agent_*/temperature/role_*_temperature/template_id/writing_style/default_words/extra）

 agent_order: list[list[str]] = Field(default_factory=list)
 """Agent 链执行拓扑 — 层级嵌套数组（同层并行；槽位编号 0-9）。

 - **外层索引 = 槽位编号（0-9，共 10 个数字）**——索引 0 先执行，逐层串行
 - 内层 = 同槽位（同编号）并行角色字段名数组（agent_architect 等）
 - 示例: [["agent_architect"], ["agent_writer", "agent_auditor"], ["agent_reviser"]]
 = 槽 0 架构规划 → 槽 1 写作+审阅并行 → 槽 2 修订
 - **默认模板 = 槽 0-3**（architect=0/writer=1/auditor=2/reviser=3）；槽 4-9 预留自定义 Agent
 - 空层（[]）= 空槽（该编号无角色，跳过）——允许跳号（如只用 0/1/2/3/9）
 - 长度上限 10（编号 0-9）；空列表 = 未配置 → 默认拓扑 [[architect],[writer],[auditor],[reviser]]
 - **双模式**：空列表 = **默认模板模式**——`agent_*` null **不触发真禁用**（跟随模板默认，语义）；非空 = **配置驱动模式**——null 真禁用（§2.2）
 - 角色名支持任意字符串（自定义 Agent，执行解锁 + 数据面 §5.3.4）
 - **角色集合**：6 内置 role_key（architect/writer/auditor/reviser/worldview/polisher，§5.7.1）+ 自定义 Agent（Agent 管理创建，role_key 由服务分配，§5.7.2）——前端从 `/api/v1/agents` 真源派生，不硬编码
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

- **字段命名口径**：`agent_order` 存**角色字段名**（`agent_architect` 等，带 `agent_` 前缀）；内部 stage.id 为不带前缀的角色名（`architect` 等）——执行层转换映射：`agent_xxx → xxx`（§5.3）。
- **默认值**：`default_factory=list`（空 = 模板默认拓扑）——**零迁移**：旧项目 config JSON 无此键 → Pydantic 默认空列表；GUI 显示默认拓扑（Architect → Writer/Auditor/Reviser 四层链）。
- **结构变更**：`list[str]` → `list[list[str]]`（尚未实现，无存量数据兼容问题）。

### 2.2 三态语义（扩展既有三态）

| agent_* 值 | 语义 | 执行层行为 | UI |
|------------|------|-----------|-----|
| `null`（缺失） | **关闭** | **默认模板模式**（agent_order 空）：不覆盖模板模型，角色照常执行；**配置驱动模式**（agent_order 非空）：**跳过该角色**——不执行；下游角色以空输入降级运行（复用 pipeline_nodes L55 空注入机制）；从执行拓扑摘除（§5.3.1） | Switch off |
| `"__default__"`（AGENT_DEFAULT_SENTINEL） | 跟随默认 | **修复点**：不覆盖模板角色模型 | Switch on + Select 选中「跟随默认」 |
| `"<provider>/<model>"`（如 `"zhipu/glm-4.5"`） | 指定模型 | 覆盖模板角色模型（parse_model_string 剥离前缀后调用） | Switch on + Select 选中具体模型 |

> **双模式一致性规则**：前端关闭角色时**同步从 `agent_order` 移除**该角色（保持「配置驱动模式」与「开关」一致）——即关闭动作 = ① agent_* → null ② agent_order 剔除该角色；开启动作 = ① agent_* → sentinel/模型 ② agent_order 加入对应槽位。后端校验「必须含全部启用角色」在配置驱动模式下执行；默认模板模式下不校验（无 agent_order 语义）。

> 存储格式说明：`agent_*` 与 `config.model` 具体模型值**全链路强制 `provider/model` 格式**（与 `ProviderConfig.default_model` 同格式、与 `parse_model_string` 解析契约一致）——不允许存裸模型名/裸 provider 名（无 `/` 会在执行层 ValueError，实证：extraction_service L670/717 default_model 消费链）。

### 2.3 agent_order 校验（双层 + 启用角色口径）

| 层 | 行为 | 位置 |
|----|------|------|
| 存储层（Pydantic） | 结构 + 跨层去重 + 长度 ≤10（§2.1） | `domain/models/project.py` |
| API 层（PATCH） | 语义校验：非法 → **422**（detail 中文说明）；非法定义 = ① 跨层重复（存储层已拒，防御）② **不含全部启用角色**——**角色名任意**（内置 6 + 自定义均可） | `api/routers/project.py`（或 `project_service.py`，实现确认） |
| 执行层（防御） | 任何非法（含存量数据手工损坏）→ **回退默认拓扑**，记 warning 日志；自定义角色 system_prompt 缺失（非内置且模板 roles 未定义）→ 跳过 + warning（§5.3.4）；永不抛错中断管线 | `agent_service.py` |

> 验收锚点「agent_order 缺省/非法时回退默认顺序（零迁移）」由**执行层回退**保证——API 层 422 是输入卫生，执行层回退是数据防御，两层并存。
> **关闭角色语义**：关闭角色（null）**不要求**出现在 agent_order 中；若出现（用户调序时保留），执行层仍跳过（null 优先于拓扑）。

## 3. API 契约

**无新增 REST 端点**。所有变更走既有 `PATCH /api/v1/projects/{id}`（`api/routers/project.py` L97-109）config 部分合并语义（`project_service.py` L139-143：`model_dump(exclude_unset=True)` + `existing.config.model_copy(update=config_updates)`）——agent_order 作为 ProjectConfig 新字段自动纳入，前端 PATCH 传 `{config: {agent_order: [...]}}` 即可。

| 变更 | 端点 | 说明 |
|------|------|------|
| PATCH config 扩展 | `PATCH /api/v1/projects/{id}` | body `config.agent_order`（list[list[str]]）+ `config.agent_*`（三态值）按既有合并语义生效 |
| agent_order 非法 | 同端点 | 422，detail 中文（§2.3 API 层） |
| 模型存在性提示 | 无新端点 | **不校验存在性**——前端标记（§5.2）；数据源 = `GET /api/v1/provider-configs` chat 模型列表 |
| 角色集合数据源 | **既有 `GET /api/v1/agents`** | 6 内置 + 自定义 Agent 全量；前端 AgentChainCard/AgentRelationEditor/TemplateDialog 角色列表均从该端点派生（§5.7.2）——无新端点 |
| 自定义管线拓扑 | `POST /api/v1/agent/pipelines/execute` body 增 `stages` / `pipeline_config` | 两者互斥可选（新增）：`stages: list[str]`（role_key 序列 → 服务端按 Agent 真源展开为顺序链）；`pipeline_config`（完整管线配置对象，YAML 形态，含 stages[].agent prompt）。均**无新端点**（§5.8）；`pipeline` 字段保留（内置 id / 用户标识字符串，仅作执行记录显示） |
| 自定义管线校验 | **既有 `POST /api/v1/agent/pipelines/validate`** | YAML 管线配置校验格式已存在（`PipelineConfig` → `validate(stages)`），CLI `agent validate -f` 复用；自定义管线在本端点无新增语义 |

**异常映射表**：

| 场景 | 状态码 | detail |
|------|--------|--------|
| agent_order 长度 >10（槽位 0-9 超限） | 422 | 「agent_order 最多 10 层（槽位编号 0-9）」 |
| agent_order 缺启用角色 | 422 | 「agent_order 必须包含全部启用角色: xxx」 |
| agent_order 空槽/跨层重复 | 422 | 「agent_order 每层必须为数组」/「agent_order 角色重复: xxx」（空槽 [] 允许） |
| agent_* 为空字符串 | 422（既有） | 「Agent 模型不能为空字符串」（project.py L73-82 既有 validator） |
| agent_* 为未知模型 | **200 允许保存** | 前端标记「未注册模型」提示（§5.2） |
| agent_* 为裸模型名（无 `/`） | **200 允许保存 + 前端格式提示** | 提示不阻塞 |
| `stages` 与 `pipeline_config` 同时提供 | 422（Pydantic 模型校验） | 「stages 与 pipeline_config 互斥」 |
| 自定义管线 + `mode=supervisor` | 422（Pydantic 模型校验） | 「自定义 stage 仅支持 static 模式」 |
| `stages = []`（空序列） | 422（Pydantic 模型校验） | 「stages 不能为空」 |
| `stages` 含未知 role_key（Agent 真源无该角色） | 422（`AgentServiceError` → execute 端点映射） | 「未知 stage 角色: <role_key>」 |
| `stages` / `pipeline_config` 拓扑非法（重复 id / 无入口 / 无终点 / 环） | 422（`AgentServiceError` → execute 端点映射） | 「自定义管线配置无效: <errors 分号连接>」 |
| `pipeline` 值为既非内置 id 也非自定义形态（如 `nope`）且未提供 `stages`/`pipeline_config` | 422（既有） | 「未知管线模板: nope」 |

---

## 4. CLI 命令签名

**本模块不新增 CLI 命令**。**归属澄清**：`inkflow agent template <action>` 命令组（含 `create`/`update` 及其 `--content-file`）的 CLI 契约归属 **F4**（agent_service，「agent template 管理」）——本模块不列其签名，`--content-file` 支持见 `specs/f4-pipeline-engine/spec.md` §4/§13.2。agent_order 的 CLI 读写依赖**项目配置命令面**（`inkflow project update --id N --config-json '{"agent_order": [["agent_architect"], ...]}'`）——经既有 PATCH 合并语义天然支持（嵌套结构经 JSON 透传，无特殊处理）。

- 本模块对 CLI 的约束：① ProjectConfig 字段扩展**不得破坏**既有 config 合并语义（agent_order 是普通可选字段，exclude_unset 兼容）；② `inkflow project get --id N --json` 的 config 输出自动包含 agent_order（F7 全局 JSON 信封约定，无需改动）。
- **验收联动**：M6（CLI 读写）依赖项目配置命令面；若该命令面未就绪，CLI 验收降级为 API 层验证（curl PATCH/GET agent_order），并在 PR 说明标注。

### 4.1 `agent run --pipeline <值>` 取值形态

`--pipeline` 从「只认内置模板 id」扩展为**三形态**（判别顺序固定，见下表）；`--pipeline` 默认值仍 `builtin:write_chapter`（零回归）。

| # | 形态 | 判别 | 载荷 | 例 |
|---|------|------|------|-----|
| 1 | 内置模板 id | 值以 `builtin:` 开头 | `pipeline=<id>`，`stages`/`pipeline_config` 均不带 | `--pipeline builtin:write_auto` |
| 2 | 管线 YAML 文件 | 值以 `.yaml`/`.yml` 结尾**或**该路径文件存在 | CLI 本地读 YAML（`yaml.safe_load` → `source` 缺省补 `yaml`）→ 校验为 `PipelineConfig` → `pipeline_config=<对象>` | `--pipeline .\my-chain.yaml` |
| 3 | 自定义 stage 列表 | 其余（含逗号分隔的 role_key 序列；单个 role_key 亦属此形态） | `stages=[<role_key>...]`（去空白、去空段；空列表 → 报错退出码 1） | `--pipeline "worldview,polisher"` |

- **CLI 薄层边界**：形态 3 的 role_key → stage 展开**在服务端**（CLI 无 DB 访问，拿不到 Agent 真源）；CLI 只做 ① 形态判别 ② YAML 本地读取 + `PipelineConfig` 校验（复用 `agent validate -f` 同一读取器）③ 空列表拒绝。
- **失败面**（CLI 本地）：YAML 文件不存在 / 解析失败 / 非映射 / 非 `PipelineConfig` 结构 → `print_error("VALIDATION_ERROR", <原因>)` + 退出码 1；`stages`/`pipeline_config` 互斥与 supervisor 约束由 DTO 校验兜底（API 422）。
- **执行记录标识**：`pipeline` 字段原样存用户输入（如 `worldview,polisher` 或 YAML 路径），供 `agent status --run-id` / 运行记录显示区分。
- **`agent template pipelines` 不变**：自定义管线**不注册**到 `_BUILDERS`/`BUILTIN_TEMPLATES`（惰性映射按内置 4 条重建）——该命令输出仍恒等于 `list_templates()`（负向回归断言）。

---

## 5. 关键差异节：Agent 链配置驱动编排（层级拓扑 + 三态模型）

### 5.1 三态语义执行层解析

**现状缺陷**（实证）：`agent_service.py` `_merge_role_configs` L232-234：

```python
project_model = project_role_models.get(stage.id)
if project_model: # ← "__default__" 非空 → 覆盖！
 new_agent.model = project_model # → model="__default__" → parse_model_string ValueError
```

**修复**：

```python
if project_model and project_model != AGENT_DEFAULT_SENTINEL:
 new_agent.model = project_model # sentinel = 跟随默认 → 不覆盖（模板角色模型/全局默认）
```

- 依赖注入：`AGENT_DEFAULT_SENTINEL` 从 `domain/models/project.py` import（同模块域，无循环依赖风险）。
- **跟随默认的完整解析链**（不覆盖后回退路径）：模板 role.model（builtin 恒 `openai/gpt-4o`）→ 自定义 AgentTemplate role.model（`RoleTemplate.model`，可 None）→ `None` → `langchain_client.chat(model=None)` → `self._default_model`（全局默认 `config.llm_default_model`，`langchain_client.py` L73）——三层兜底与既有温度链同构。（⚠️ `AgentRole.model` 的字段默认值实为 `"openai/gpt-4o"` 而非 `None`——自定义 stage 未显式赋值时会落到该默认值并静默路由 openai；故 §5.8.2.1 在构造时显式赋全局默认，`model=None` 分支仅在显式传入 None 时可达。）
- **裸模型名兼容策略**：执行层 `_merge_role_configs` 对 project_model 做格式预检——无 `/` 且非 sentinel → 记 warning + 不覆盖（按跟随默认处理），不抛错（存量数据零迁移；新数据由前端格式标记引导修正，§2.2）。
- **测试锚点**：`agent_* = "__default__"` 时执行不再抛 ValueError，且模型回退模板角色模型（mock LLM 断言 model 参数）；`agent_* = "gpt-4o"`（裸名）→ warning + 回退跟随默认。

### 5.2 前端模型选择 UI

**AgentChainCard.tsx MODIFY**（`frontend/packages/renderer/src/components/AgentChainCard.tsx`）：

- 每行 Switch 打开 → **条件渲染**模型 Select（替换/补充当前 tag 展示）；关闭 → 不渲染（保持现状 UI 简洁）。
- Select 数据源：**provider-configs chat 模型列表**——`GET /api/v1/provider-configs` → `items[].models[type=chat].id`，扁平为 `<provider>/<model>` 选项（provider 名取 `items[].name`）；数据加载走既有 `stores/models.ts`（ProviderConfig/ProviderModel 接口已存在）。**「跟随默认」选项固定置顶**（值 = `AGENT_DEFAULT_SENTINEL`）。
- Select 选项结构：
 1. 「跟随默认」= `AGENT_DEFAULT_SENTINEL`（Switch 打开默认选中）
 2. 每 provider 的 chat 模型：`<provider>/<model>`
- 三态交互映射（§2.2 表）：Switch off → PATCH `null`；on + 「跟随默认」→ `__default__`；on + 具体模型 → `<provider>/<model>`。
- **未注册模型标记**：config 中既有值不在选项列表（如手工写入/模型已删）→ tag 显示「未注册模型」警告样式（沿用现有 tag 展示位，L70），**不阻塞保存**——即改即存链路（settings.tsx AgentPanel `persist()` L395-415：in-flight 守卫 + 失败 toast）不变。
- **格式不合规标记**：config 中既有值无 `/`（裸名）→ tag 显示「格式需修正（应为 provider/model）」提示；**修改默认模型 Select（AgentPanel L422-439）**：硬编码 `['openai','deepseek','ollama']` → 改为 provider-configs chat 模型列表（与 AgentChainCard 同数据源），存完整 `provider/model` 值——修复裸 provider 名写入问题。

**store 扩展**：`stores/agent.ts` 无需新方法（setConfig/saveConfig 既有）；`stores/models.ts` 新增 chat 模型扁平化 selector（provider/model 选项列表，供 AgentChainCard 与 AgentPanel 共用）。

### 5.3 执行拓扑：单链 → 层级并行

**消费链**：`AgentService.execute`（`domain/services/agent_service.py` L67-118）→ `get_template("builtin:write_chapter")` → `_merge_role_configs`（模型/温度装配 + 跳过过滤）→ `_apply_agent_order`（拓扑重排，新增）→ `_run_pipeline` → `LangGraphAgentPipeline.execute`（`infrastructure/agent/langgraph_pipeline.py` L95-138）。

**执行顺序事实**（实证，决定实现方式）：LangGraphAgentPipeline.execute **按 DAG 边（output_to/input_from）构建 StateGraph**——执行顺序 = LangGraph 拓扑调度，**非 stages 列表顺序**（L120-126：entry=无 input_from 阶段；edges=output_to 边；terminal=无 output_to 阶段）。「固定序」的真相来源 = 模板 stages 的**链式边**（pipeline_templates.py L65-81 硬编码）。

#### 5.3.1 `_apply_agent_order(stages, agent_order, enabled_roles) -> list[PipelineStage]`

1. 输入：模板 stages（4 阶段链式）+ 项目 config.agent_order（层级嵌套角色字段名数组）+ `enabled_roles`（启用角色集合，来自 agent_* 非 null 的角色；双模式下见步骤 4）
2. **双模式分派**：`agent_order` 空 = **默认模板模式**——原样返回（模板默认拓扑，null 不触发跳过，零迁移）；非空 = 配置驱动模式——继续步骤 3-7
3. 语义校验（执行层防御）：非法（缺启用角色/长度 >10/跨层重复）→ 记 warning + 原样返回（回退默认）；**角色名任意（内置 + 自定义均允许）**；空槽（[]）正常跳过
4. **跳过过滤**：**配置驱动模式下** agent_* = null 的角色从集合摘除（无论是否在 agent_order 中；§2.3 关闭角色语义）
5. **层级映射**：`agent_xxx → xxx`（stage.id）；按层序重组 stages；**自定义角色 stage 构造**
6. **全连接边重建**：第 i 层每节点 `input_from` = **前序全部层所有角色**；`output_to` = **后序全部层所有角色**（跨层直连全连接 DAG——执行依赖传递闭包 + 变量注入自然全量；DAG 边多不影响 LangGraph 拓扑序）；空槽不改变「前序全层」成员集合（按最近非空槽计算）
7. **拓扑-引用一致性校验**：静态扫描各角色 prompt 的 `{role}_output` 占位符（复用 `_VARIABLE_RE`），被引用角色必须位于该角色的**严格前序层**；违规 → 执行层回退默认拓扑 + warning（数据防御）/ API 层 422（输入卫生，实现确认落点）；同层互引在层内校验直接拒绝
8. 返回重排后的 stages，供 `_merge_role_configs` 装配

- **装配顺序**：`execute` 中顺序为 **① 读 agent_* 得启用集合 → ② `_apply_agent_order`（双模式分派 + 跳过过滤 + 自定义 stage 构造 + 重排 + 边重建 + 一致性校验）→ ③ `_merge_role_configs`（模型/温度装配，只装配存留角色）→ ④ `_run_pipeline`**——顺序为「先构造 stage 再 merge」（自定义角色 stage 必须先构造才能装配）。
- **默认拓扑**（空 agent_order）：`[[architect],[writer],[auditor],[reviser]]`——与现模板链**执行序等价**，但注意：全连接边重建后 auditor 的 `input_from` 从 `[writer]` 变为 `[architect, writer]`，user 消息会多注入 architect 输出段——默认路径也发生 user 消息内容变化，需负向回归断言（§9）。

#### 5.3.2 引擎放宽（`langgraph_pipeline.py` + `pipeline_nodes.py` MODIFY）

- **validate()**（L50-93）：「唯一入口」（L57-60）/「唯一终点」（L61-62）约束**放宽**为「至少一个入口/终点」——层级并行下第一层多角色（无 input_from）都是入口、最后一层多角色（无 output_to）都是终点；**环检测（Kahn）与引用存在性保留**（L64-93 不变）。
- **execute()**（L95-138）：入口连接从 `workflow.set_entry_point(entry.id)`（L120-121）改为**每个入口节点 `add_edge(START, entry_id)`**；终点从 `workflow.add_edge(terminal.id, END)`（L125-126）改为**每个终点节点 `add_edge(terminal_id, END)`**（LangGraph 1.x 支持多 START/END 边；实现时以实测为准，若 API 限制则用 conditional entry 兜底——标注实现确认）。
- **节点泛化**：`_NODE_MAP`（L33-38）从 4 具名节点白名单（architect_node/writer_node/auditor_node/reviser_node，pipeline_nodes.py L124-141）改为**通用节点映射**——任意 stage.id → `generic_node`：
 - 现状实证：4 具名节点只是 `_call_llm_node(state, stage_id, upstream_keys)` 的参数化包装，**upstream_keys 硬编码在具名节点里**（architect=[]/writer=["architect"]/auditor=["writer"]/reviser=["writer","auditor"]）
 - **⚠️ 模板数据不一致**：模板 `pipeline_templates.py` L81 的 `reviser.input_from=["auditor"]`（**缺 writer**）——现状由节点硬编码 `["writer","auditor"]` 补偿；测试 `test_langgraph_pipeline.py` L78-83 又写 `["writer","auditor"]`——**模板/节点/测试三者不一致**。通用节点直接推导 `input_from` 会让 reviser 丢 writer → `{writer_output}` 字面量残留
 - **修正**：① 修正模板 `reviser.input_from` 补 `"writer"`（真相来源收敛回模板数据）；② 增加模板层校验：`input_from` 必须覆盖 prompt 引用的全部 `{role}_output` 占位符（复用 `_VARIABLE_RE` 扫描，作为 `_apply_agent_order` 步骤 7 一致性的子集校验）
 - 修复：`generic_node(state)` 从 `state["stages"][stage.id].input_from` **推导 upstream_keys**（不再硬编码）；`langgraph_pipeline.execute` L111-112 的「未知阶段类型」检查删除（任意 stage.id 可执行）
 - 自定义角色 prompt 来源：`stage.agent.system_prompt`（由 `_merge_role_configs` 从 AgentTemplate.roles 装配，§5.3.4）
- 并行层内节点执行顺序：LangGraph 同层并行调度（asyncio），**层间顺序确定、层内顺序不确定**——验收「按配置顺序执行」口径 = 层序确定（§13 M4）。

#### 5.3.3 prompt 变量注入改造（`pipeline_nodes.py` MODIFY）

- `_build_messages`（L47-68）变量注入契约：
 ```python
 # 注入键集 = input_from 全部（前序全层）∪ 该角色 prompt 中扫描出的全部 {xxx_output} 占位符
 # （复用 _VARIABLE_RE——未来层引用/同层互引的占位符也进变量表 → 渲染为空串而非字面量残留）
 for key in inject_keys: # inject_keys = upstream_keys ∪ 占位符扫描集
 sr = state["results"].get(key) # ← .get 防御（未执行角色无条目 → 空串）
 variables[f"{key}_output"] = sr.output if sr else ""
 ```
- **同层不可见硬语义**：同槽位并行角色互相引用 → **一律注入空串**（即使调度上已执行也强制空——保证断言稳定，避免「先执行者读到值、后执行者读到空」的 flaky）；§7「同层互引空注入」按此语义修订。
- **效果**：① 前序层引用 → 实际输出；② 未来层/同层/未执行引用 → 空串（软降级，用户自由排序的明确代价——UI 保存时按角色级精确提示「XX 角色将看不到 YY 的输入」，静态依赖分析提示）；③ `_render` L44 的「未知占位符原样保留」路径只对**拼写错误**变量生效（兜底，不阻断）。
- user 消息 parts（L62-64）同源改造（`.get` 防御 + 同层空注入）。
- **防回归断言**：prompt/user 消息无 `None` 字面量注入。

#### 5.3.4 自定义角色

- `agent_order` **数据模型与校验支持任意角色字段名**（§2.1/§2.3）——内置 6 + 自定义 Agent 均可编排，UI 不限制；执行槽位 0-9（默认模板占 0-3，槽 4-9 预留自定义 Agent）。
- **执行层解锁**：`_NODE_MAP` 白名单删除 → 任意 stage.id 经通用节点执行（§5.3.2 节点泛化）。
- **⚠️ 数据面缺口**：现状 `RoleTemplate` 只有 `model/temperature/enabled` 三字段（`agent_template.py` L29-40）——**无 system_prompt/name**，自定义角色 prompt 与显示名无来源（「缺失→跳过」= 永远跳过 = 功能空转）；`ProjectConfig` 只有 4 个固定 `agent_*` 字段（自定义角色无项目级三态字段）；`AgentChainCard` 只渲染 4 固定角色（无自定义角色行 UI 入口）。
- **数据面设计**：
 1. `RoleTemplate` 扩展 `prompt: str | None` + `name: str | None`；`_merge_role_configs` 在 `role_template.prompt` 非 None 时覆盖 `new_agent.system_prompt`
 2. `ProjectConfig` 自定义角色三态字段：约定 `extra["agent_roles"]`（dict[自定义角色字段名, str|None]，与 agent_* 同三态语义）或独立字段（实现拆 issue 时定稿）——**自定义角色的启用/关闭/模型配置面**
 3. `AgentChainCard` 角色数据源 = 内置 4 + 当前模板 roles（自定义角色行：开关 + 模型 Select + 槽位号）——**升级**：角色数据源改为 Agent 管理全量真源派生（§5.7.2）
 4. 「启用角色」口径（配置驱动模式）= agent_* 非 null ∪ extra 自定义角色非 null
- **自定义 Agent 进链**：自定义角色数据源从「模板 roles 非四键」升级为「**Agent 管理全量（6 内置 + 自定义 Agent）真源派生**」——Agent 管理创建的自定义 Agent（`AgentEntity.builtin=false`）可进链：服务层为其分配稳定 role_key（§5.7.2），项目级三态字段写入 `config.agent_roles[agent_<role_key>]`（§5.7.3），执行层 prompt 从 `AgentEntity.system_prompt` 取（§5.7.4）。模板 roles 仍可提供 prompt/name/模型覆盖（既有装配，`_merge_role_configs` 不变）。
- **prompt 缺失防御（过渡期）**：自定义角色既非内置且模板 roles 未定义（system_prompt 为空）→ 执行层**跳过 + warning 日志**（§2.3/§7）——数据面 issue 落地后此路径仅剩存量损坏数据触发。
- **归属边界**：自定义 Agent 能力差异化白名单归 后续里程碑 F39-F41；本模块（含拆出 issue）解锁「模板定义角色 → 配置 → 编排 → 管线执行」全链路。

### 5.4 DAG 编排（由 F46 spec 承接，本模块不实现）

> **承接说明**：DAG 关联关系已由独立 spec `specs/f46-dag/spec.md` 承接（其唯一真相来源）。本模块只声明演进约束，不承担实现：
> - 层级 = 拓扑层特化 → F46 §1.2「`agent_order` = 拓扑基线，`agent_relations` = 增强语义」
> - 执行链设计 → F46 §5.3「自研 LangGraph StateGraph 扩展（基线 + 叠加 + 关系优先）」
> - 配置模型兼容 → F46 §2.2「`agent_relations: list[{from,to,type}]` 与 `agent_order` 并存」
> - 真禁用 / 并行语义 → F46 §5.3.1 叠加规则复用 F42 跳过 / 全连接语义

| 演进约束 | 本模块保证 | F46 承接 |
|----------|-----------|---------|
| 层级 = 拓扑层特化 | `agent_order` 层级嵌套是**分层并行 DAG** 的紧凑表示（层间全连接 + 层内并行） | F46 §1.2（agent_order 基线 + agent_relations 增强） |
| 执行链设计 | 引擎放宽后的 validate/execute（多入口/终点 + 全连接 DAG）即通用 DAG 引擎子集——DAG 无需引擎重写 | F46 §5.3（基线 + 叠加 + 条件边 `add_conditional_edges`，复用 F42 通用引擎） |
| 配置模型兼容 | agent_order（list[list[str]]）+ agent_relations（后续里程碑 新增）并存；冲突规则（关系优先） | F46 §2.2 / §5.3.1（关系优先定稿） |
| 真禁用 | 跳过 = 节点摘除 + 边重连（§5.3.1 步骤 4） | F46 §5.3.1（复用跳过 / 空注入语义） |
| 并行语义 | 同层并行 = DAG 并行分支；汇点 = 后一层单角色 | F46 §5.3.1（同层显式边打破并行；汇点 = 后一层单角色） |

### 5.5 deepagents 兼容性结论（实证，已确认非拍板点）

- agent_order **仅消费方 = LangGraphAgentPipeline**（角色链管线；角色集合 扩展为 6 内置 + 自定义）——`POST /api/v1/agent/.../execute`（`api/routers/agent.py` L29-30 装配）。
- F27 agentic 路径（`AgenticWriterService` + `build_agentic_writer`）：deepagents **单 agent**（writer_agent）ReAct 循环 + 5 只读 + save_draft 工具，`model=config.llm_default_model`——**无多角色编排概念，不消费 agent_order/agent_***（`api/deps.py` L220-240 实证）。
- F29 Supervisor：deepagents subagent 机制分层编排，与 agent_order 管线编排**不同抽象层**——兼容性结论：**无冲突**，agent_order 不触碰 deepagents 装配；F29 spec 需单独定义 supervisor 与管线的衔接（同编排域串行：本模块合入后再开 F29）。
- 模型名剥离：agent_* 具体模型值（provider/model 格式）在 LLM 调用链既有剥离逻辑（F26 §5.5 `parse_model_string` 复用）——本模块不新增剥离代码。

### 5.6 GUI 写作入口管线化

**背景**：GUI 写作现状走 `/stream`（writing_service 单模型，`model = request.model or project.config.model`）与 `/agentic/generate`（F27 单 agent，全局默认模型）——**两者都不消费 `agent_order`/`agent_*`**，「写作流程按指定模型/新顺序执行」在 GUI 主路径不可达。因此：**GUI 写作入口切换到多角色管线**。

**新增默认管线模板**（`pipeline_templates.py` 注册，prompt 按场景独立编写）：

| 模板 key | 名称 | 场景 | 角色链（初稿，实现可微调） | 说明 |
|----------|------|------|---------------------------|------|
| `builtin:write_auto` | 全自动 | 从零生成新章节（无前文或独立章节） | architect → writer → auditor → reviser（同 write_chapter 骨架，prompt 按「全自动新章节」重写） | 规划 → 正文 → 审校 → 修订全链 |
| `builtin:write_continue` | 续写 | 基于前文续写章节 | writer → auditor → reviser（无 architect——前文摘要注入上下文，F6 复用） | 续写 → 审校 → 修订；prompt 含前文摘要引导 |

- **模板注册**：`BUILTIN_TEMPLATES` 扩展两个 key；`get_template` 既有分发不变；CLI `agent pipelines list`（如存在）自动暴露。
- **GUI 入口接线**：写作页「全自动生成」按钮 → `POST /api/v1/agent/pipelines/execute`（pipeline=`builtin:write_auto`）；「续写」按钮 → execute（pipeline=`builtin:write_continue`）；执行状态/结果复用 agent 管线 execution 查询端点（`GET /api/v1/agent/pipelines/.../status` 或等效，实现确认）——写作页需接入执行状态展示（进行中/成功/失败 + 成品内容落章）。
- **`agent_order`/`agent_*` 生效**：两个模板执行同样经 `_apply_agent_order`（双模式）+ `_merge_role_configs`——GUI 主路径按配置的模型/顺序执行，验收可达。
- **边界**：F27 agentic（工具型单 agent）保持独立入口（能力不同：工具循环 vs 角色链，本模块不改造）；F3 writing_service 单模型路径保留兼容（既有 API 不断，逐步被管线模板替代——替代节奏另行拍板）。
- **成品身份**：`final_output` = **reviser 输出**；reviser 被禁用/未启用时 = 最后一个非 architect/auditor 内容角色输出（内置语义：writer；**worldview/polisher 也是内容角色，可作成品**，§5.7.4）；architect/auditor 永不作为成品——执行层在装配后校验终点角色类型，违规（如用户把 auditor 排最后）→ 回退默认拓扑 + warning（或 API 422，实现确认）；§13 M6 增加「调整顺序/关闭角色后成品类型不变」断言。
- **交付拆分**：① 模板注册 + prompt 编写；② GUI 写作页入口切换 + 执行状态 UI（§10）。

### 5.7 链动态化 + 模板联动

**背景**：后端 6 内置 Agent 已暴露 `role_key` 映射，前端 AgentChainCard 内置行已从 `/api/v1/agents` 真源派生。但链仍固定 4 位置：世界观顾问/润色师 `role_key=None` 无法渲染；AgentChainCard/AgentRelationEditor/TemplateDialog 三处 4 键硬编码；模板 roles 前端契约仍 4 键（§1.1 第 6 条）。本节把「链角色集合」从真源完全派生，并打通 Agent 管理 ↔ 链 ↔ 模板三域联动。

#### 5.7.1 role_key 全集扩展（6 内置稳定映射，后端真源）

| 内置 Agent（BUILTIN_AGENT_SPECS） | 现状 role_key | 扩展 | 链角色字段名 |
|-----------------------------------|----------------------|-----------|--------------|
| 架构师 | `architect` | 不变 | `agent_architect` |
| 写手 | `writer` | 不变 | `agent_writer` |
| 审校员 | `auditor` | 不变 | `agent_auditor` |
| 修订师 | `reviser` | 不变 | `agent_reviser` |
| 世界观顾问 | `None` | **`worldview`** | `agent_worldview` |
| 润色师 | `None` | **`polisher`** | `agent_polisher` |

- **落地**：`BUILTIN_AGENT_SPECS` 两处 `role_key: None` 改为 `"worldview"`/`"polisher"`（`agent_entity_service.py`）——role_key 是链角色**稳定标识**（语义固定、不随显示名变更），沿用既有契约（`GET /api/v1/agents` 透出，前端派生）。
- **seed 影响**：seed 幂等（按 name 判重），存量 DB 已 seed 的世界观顾问/润色师需一次迁移：role_key 列补值（`UPDATE agents SET role_key='worldview' WHERE name='世界观顾问'`）——实现 PR 提供迁移脚本或 seed 升级钩子（实现确认）。
- **默认拓扑不变**：默认 `[[architect],[writer],[auditor],[reviser]]`（4 角色链零迁移）；世界观顾问/润色师作为**可选角色**——用户通过「添加角色」进链（§5.7.3），默认不在链中。

#### 5.7.2 角色池 = Agent 管理全量（真源派生）

- **角色池定义**：可进链角色 = `GET /api/v1/agents` 全量（6 内置 `builtin=true` + 自定义 Agent `builtin=false`），按 `builtin` 分组展示（内置在前、自定义在后，均按 name 排序）。
- **自定义 Agent role_key 分配**：自定义 Agent 创建时（`POST /api/v1/agents`）服务层自动分配稳定 role_key——取 name 的 slug 化（小写字母/数字/下划线，如「校对助手」→ `proofreader` 或 `校对助手` 拼音/ASCII 归一化，实现确认）——冲突时追加后缀；role_key 一经分配不可变更（或允许显式指定，实现拆 issue 时定稿）。**role_key 是自定义 Agent 的链身份**，`config.agent_roles[agent_<role_key>]` 三态字段以此命名（§5.3.4）。
- **前端派生规则（三组件统一）**：
 1. `AgentChainCard`：内置行 = `agents.filter(a => a.builtin && a.role_key)`（不再 BUILTIN_ROLE_KEYS 4 键 map，§1.1 第 6 条）；自定义行 = `agents.filter(a => !a.builtin)`（不再只从模板 roles 非四键取，§5.3.4 扩展）——**模板 roles 键仍是链字段的补充来源**（模板自定义键但无 Agent 实体 → 仍渲染，兼容既有模板；§7）
 2. `AgentRelationEditor`：角色列表 = 同一派生规则（ROLE_FIELDS 4 键硬编码删除，F46 DAG 依赖编辑器联动 6+ 角色）
 3. `TemplateDialog`：角色编辑列表 = 同一派生规则（ROLES 4 键硬编码删除，模板可引用任意角色组合，§5.7.5）

#### 5.7.3 链增/删/改角色（UI 契约）

- **添加角色**：AgentChainCard 顶部「添加角色」按钮 → 弹出角色池选择器（未在链中的角色，内置 + 自定义）→ 选择后：① 写入三态字段（`agent_*` 或 `agent_roles[agent_<role_key>]` = sentinel「跟随默认」）；② 加入 `agent_order` 默认槽位（内置按 DEFAULT_SLOTS 既有映射；自定义/新角色追加到末尾槽，§5.7.2 分配）——即「配置驱动模式」显式化。
- **删除角色**：既有关闭开关即「移除」语义（agent_* → null + 从 agent_order 剔除，§2.2 双模式一致性规则）——UI 文案保持「关闭」；关闭后角色仍在角色池中可重新添加。
- **修改角色**：既有槽位号编辑（0-9）/上移下移/模型 Select 不变（M6 契约）；新增角色同样支持。
- **data-testid 契约**：既有 `agent-order-slot-<field>`/`agent-order-move-up-<field>`/`agent-model-select-<field>` 以 `field` 为键（field = `agent_<role_key>`），新角色自动满足；新增「添加角色」按钮 `data-testid="agent-chain-add-role"` + 角色池选项 `data-testid="agent-chain-role-option-<field>"`（E2E 契约）。

#### 5.7.4 执行层 stage 构造扩展（6 内置 prompt 真源）

- **现状局限**：内置模板（write_chapter/write_auto/write_continue）只含 4 角色 stage——世界观顾问/润色师进链后模板 stages 无对应 stage → `_apply_agent_order` 无法构造 PipelineStage。
- **扩展方案**：`_apply_agent_order`（或 `_merge_role_configs` 前置装配点）对 agent_order 中**模板 stages 缺失的角色**（6 内置新增 2 + 自定义 Agent）构造占位 stage：
 - **内置角色**：`system_prompt`/`name` 从 **AgentEntity 真源**取（`agent_entity_service` 已存 6 内置 prompt：世界观顾问「你是世界观顾问，负责校验角色与伏笔的世界观一致性。」、润色师「你是润色师，负责在前文基础上润色文笔。」）——`agent_service` 注入 AgentRepositoryProtocol 查询（或 `GET /api/v1/agents` 数据缓存，实现确认）
 - **自定义角色**：`system_prompt` 从 `AgentEntity.system_prompt` 取；模板 roles 同名键可覆盖（既有 `_merge_role_configs` prompt 覆盖逻辑）
 - `model`/`temperature`：`model` 取**当前**全局默认 `config.llm_default_model`；`temperature` 跟随默认链不变（§5.1 三层兜底）
- **与模板角色的关系**：模板 roles 键 = `agent_<role_key>` 对应键时，RoleTemplate 的 `model/temperature/prompt/name` 覆盖 Agent 真源（模板优先——模板是场景化覆盖层，Agent 是真源）；无模板键时纯 Agent 真源。
- **成品身份**：世界观顾问/润色师是**内容角色**（输出可作成品）——成品选择规则扩展为「reviser 输出 → 否则最后一个内容角色（writer/reviser/worldview/polisher）输出；architect/auditor 永不作为成品」（§5.6 成品身份 + §7 边界行同步）。
- **prompt 变量注入不变**：新角色 stage 沿用 `_build_messages` 占位符扫描 + 空注入契约（§5.3.3）——世界观顾问/润色师 prompt 若引用 `{writer_output}` 等，按前序层/空注入规则处理。

#### 5.7.5 模板引用任意角色组合（TemplateDialog 联动）

- **TemplateDialog 角色编辑列表**：`ROLES = ['architect','writer','auditor','reviser']` 4 键硬编码 → 从角色池派生（§5.7.2 派生规则）——模板可引用**任意角色组合**（6 内置 + 自定义 Agent），勾选启用/关闭 + 模型 Select + 温度 Slider（既有交互逐角色保留）。
- **roles 数据契约**：`AgentTemplateInput.roles` 类型从 4 键收紧改为 `Record<string, AgentTemplateRole>`（后端 `AgentTemplate.roles` 已是任意键——前端类型同步即通，§1.1 第 6 条）。
- **保存语义**：roles 全量替换（exclude_unset 合并，既有）；模板引用已删除自定义 Agent 的键 → 保留（模板是快照，§7 边界行）。
- **链-模板联动**：项目选模板后，AgentChainCard 自定义行 = Agent 管理真源（与模板 roles 无关的独立来源）；模板 roles 仅提供 prompt/模型/温度覆盖——「模板引用任意角色组合」不改变链角色集合本身（§5.3.4 归属边界，模板拓扑 ≠ 链拓扑）。

### 5.8 自定义管线：显式 stage 拓扑 / YAML

**背景**：内置 6 Agent 中世界观顾问（`worldview`）/ 润色师（`polisher`）**无任何内置管线可执行**（§1.1 第 6 条）；`AgentTemplate` 只覆盖角色模型/温度，**不改变阶段拓扑**（6 角色模板挂到项目后 `stages` 仍为 `architect/writer/auditor/reviser`）。故给 `--pipeline` / `PipelineExecuteRequest` 增加**用户显式给定拓扑**通道——不补内置 6 角色管线（方案 A 不做，§10）。

#### 5.8.1 契约（`domain/models/agent_pipeline.py` MODIFY）

| 字段 | 类型 | 语义 |
|------|------|------|
| `stages` | `list[str] \| None`（默认 `None`） | **自定义 stage 序列**：role_key 有序列表，服务端按 **Agent 真源**展开为**顺序单链**（§5.8.2） |
| `pipeline_config` | `PipelineConfig \| None`（默认 `None`） | **完整管线配置**（YAML 形态）：stages 内含各 stage 的 `agent`（`system_prompt` 等）——服务端**原样采用** |

约束（`model_validator(mode="after")`，违反 → **422**，detail 中文）：
1. `stages` 与 `pipeline_config` **互斥**（同时非 None → 「stages 与 pipeline_config 互斥」）；
2. 二者均**仅支持 `mode="static"`**（`mode="supervisor"` + 任一非 None → 「自定义 stage 仅支持 static 模式」）——supervisor 角色池来自模板 stages（§5.1），不做自定义池扩展；
3. `stages` 非 None 时必须**非空**（`[]` → 「stages 不能为空」）；元素须为非空字符串（去空白后判空）。

`pipeline` 字段（既有 `str`）**保留**：走自定义通道时它是**用户标识字符串**（`worldview,polisher` 或 YAML 路径），仅用于执行记录显示与 `agent run --pipeline` 回显；**不再**用于内置模板查找。

#### 5.8.2 服务端解析（`agent_service_stream.py` `_build_pipeline_context` MODIFY）

分派顺序（`_build_pipeline_context` 内，static 分支）：

1. **模板查找跳过**：`stages`/`pipeline_config` 任一非 None → **不调用** `self._get_template(request.pipeline)`（自定义取值不查内置表；`pipeline` 为路径/role 串时查不到会误报「未知管线模板」）。
2. **拓扑构造**（二选一）：
 - `pipeline_config` 非 None → `template_stages = _inherit_default_model(list(request.pipeline_config.stages), config.llm_default_model)`（用户显式 stage/agent 逐字段采用；**未显式写 `model` 的 stage 继承全局默认模型**）；
 - `stages` 非 None → `template_stages = _build_custom_stages(request.stages, agents_by_role)`（下 §5.8.2.1；`agents_by_role` 复用既有 `_load_agents_by_role()` 真源，含 `skill_ids`）。
3. **拓扑校验**（新增，仅自定义通道）：`self._pipeline.validate(template_stages)` → 非空 errors → `AgentServiceError("自定义管线配置无效: " + "; ".join(errors))` → API **422**（同步拒绝，不落一段注定失败的执行记录）。校验项 = 引擎既有 `validate`：非空 / id 不重复 / 至少一个入口 / 至少一个终点 / 上游引用存在 / 无环。
4. **模型·温度·prompt 装配**：`await self._merge_role_configs(template_stages, project.config, request.role_overrides)`（既有装配链不变——项目 `agent_<role_key>` / 模板 roles / 温度链 / `--override` 全部照常生效）。
5. **skill 装配**：`self._attach_agent_skills(stages, agents_by_role, mounted_skill_names)`——映射仍为 `stage.id == Agent.role_key`，故自定义 stage 的 role_key **必须**与 Agent 真源 `role_key` 一致（`_build_custom_stages` 保证）。
6. `pipeline_impl = self._pipeline`（LangGraph 静态引擎；自定义通道不进入 supervisor 分支）。

##### 5.8.2.1 `_build_custom_stages(role_keys, agents_by_role) -> list[PipelineStage]`（纯函数，`agent_service.py`）

- **顺序单链**：第 *i* 个 stage 的 `input_from = [第 i-1 个 id]`，`output_to = [第 i+1 个 id]`；首 stage `input_from=[]`，末 stage `output_to=[]`（即「一个入口 + 一个终点」，引擎 `validate` 直接通过）。
- **stage 字段来源**：`id = role_key`；`name = Agent 真源 name`（空则回退 role_key）；`agent = AgentRole(id=role_key, name=同上, system_prompt=Agent 真源 system_prompt, model=config.llm_default_model)`——`model` 取**当前**全局默认（`config.llm_default_model`，与内置模板 `pipeline_templates._current_default_model()` 同口径）；`temperature` 交给 §5.8.2 步骤 4 装配链（**不在本函数硬编码**，与 `_apply_agent_order` 占位构造同纪律）。
- **模型继承**：两种自定义形态的 stage 未**显式**指定 `model` 时，一律取**当前**全局默认模型 `config.llm_default_model`——role 序列形态在 `_build_custom_stages` 构造时赋值；YAML 形态经 `_inherit_default_model(stages, default_model)` 按 `model_fields_set` 判据补齐（YAML 里**写死** `model` 的 stage 不被覆盖，用户显式意图优先）。触发背景：`AgentRole.model` 的字段默认值 `"openai/gpt-4o"` 会把未赋值 stage 静默路由 provider=openai（未配 key 必失败）。优先级不变：`--override <role>.model=` > 项目 `agent_<role>` > 全局默认。
- **全局默认未配置（负例）**：`config.llm_default_model` 为空串时，stage `agent.model=""` → `parse_model_string("")` 抛 `Invalid model format`（**明确报错，不静默回落** openai 的 `API key not configured` 原始错误）。
- **未知 role_key** → `ValueError("未知 stage 角色: <key>")` → `AgentServiceError` → **422**（显式通道不静默跳过：用户点名的角色不可用必须报错，与 §5.7.4「占位构造失败则跳过」的链路径不同）。
- **重复 role_key** → 由 §5.8.2 步骤 3 拓扑校验拒绝（「阶段 id 不能重复」）。
- **为什么复用 Agent 真源**：6 内置 + 自定义 Agent 的 `system_prompt` 唯一真源是 `AgentEntity`（§5.7.2）；真源加载失败（仓库缺失/异常）时 `agents_by_role` 为空 → 任何 role_key 都报「未知 stage 角色」（诚实失败，不静默降级）。YAML 形态不受此限（prompt 随配置自带）。

#### 5.8.3 与既有拓扑机制的关系（⚠️ 显式拓扑优先）

| 机制 | 自定义通道下的行为 | 理由 |
|------|-------------------|------|
| `project.config.agent_order`（§5.3 配置驱动模式） | **旁路**（不调用 `_apply_agent_order`） | 用户显式给定的 stage 序列即最终拓扑；再按项目 `agent_order` 重排/过滤会让「点名的角色被静默摘除」 |
| `project.config.agent_relations`（F46 条件/显式边） | **旁路**（`conditional_edges` 保持 `[]`） | 同上：显式边集已由用户给定（YAML）或为顺序链（role_key 形态） |
| `project.config.agent_*` 三态（模型） | **照常生效**（步骤 4 装配链；未配置角色 → 继承全局默认模型） | 模型是「角色参数」而非拓扑；关掉 `agent_polisher` 不应使显式 `--pipeline polisher` 变成跳过 |
| 模板 roles（`template_id` 引用） | **照常作为覆盖层**（步骤 4） | 与 §5.7.4 同口径：模板 prompt/模型/温度可覆盖真源 |
| `_attach_agent_skills` | **照常生效** | 显式挂载 ∪ 通用 skill（未挂载即通用），自定义 stage 的 role_key 命中同一 Agent |
| 成品身份（§5.6/§5.7.4） | 由**用户给定的拓扑**决定：`final_output` = 终点 stage 输出 | 终端校验（C2 终点非 architect/auditor）**只在 `_apply_agent_order` 内**——自定义通道的终点由用户负责（`--pipeline "architect"` 合法但成品是规划文本） |
| 内置 4 条管线（`builtin:*`） | **零变化**（§5.8.2 步骤 1 仅对自定义通道跳过） | 回归锁定：stage 序列与执行等价逐条不变 |

#### 5.8.4 边界（本批不做）

- **不补内置 6 角色管线**（方案 A 不做）：「世界观顾问 / 润色师 可执行」由本通道覆盖；
- **不放开内置 Agent 编辑**：`PATCH /api/v1/agents/{id}` → **409** 保持（skill 挂载需求由通用 skill 机制绕开）；
- **不做 GUI 入口**：本期仅 CLI `agent run --pipeline` + REST（GUI 自定义管线编辑器不在本批）；
- **不注册自定义管线**：不入 `_BUILDERS`/`BUILTIN_TEMPLATES`（惰性映射语义不变），不进 `agent template pipelines` 列表；
- **不做 `agent validate -f` 之外的新校验命令**：YAML 校验复用既有端点/命令。

>

---

## 6. 组织规则

- ProjectConfig 扩展遵循既有 Pydantic 模型约定（domain 层零框架依赖）；`AGENT_DEFAULT_SENTINEL` 保持 `domain/models/project.py` 定义（唯一真相源），前端 `stores/project.ts` L18 镜像常量（既有双份模式，注释互指）。
- `_apply_agent_order` 归属 domain 服务层（纯函数，不依赖 infrastructure）——放在 `agent_service.py` 模块级函数（非类方法），便于独立单测。
- 引擎放宽（validate/execute）与变量注入改造归属 infrastructure 层（langgraph_pipeline.py / pipeline_nodes.py）——domain 层不感知 LangGraph API。
- 前端模型选择数据源走既有 `stores/models.ts`（ProviderConfig/ProviderModel 接口已有）——不新建 provider store；AgentChainCard 保持「展示组件 + 回调」模式（onConfigChange 即改即存，`settings.tsx` persist 链路不变）。
- 执行层 `__default__` 解析在 `_merge_role_configs`（唯一模型装配点）——不在节点层（pipeline_nodes.py）做 sentinel 判断，保持节点纯净（节点只消费装配后的 AgentRole）。
- **角色集合真源**：链/依赖编辑器/模板编辑的**角色列表一律从 `GET /api/v1/agents` 派生**（role_key 单一来源）——前端不维护第二份角色键白名单（BUILTIN_ROLE_KEYS/ROLE_FIELDS/ROLES 4 键硬编码全部移除）；自定义 Agent role_key 由服务层分配（§5.7.2），前端只消费。模板 roles 键（Record）是覆盖层，非角色集合来源（§5.7.5 链-模板联动边界）。

---

## 7. 边界情况与错误处理

| 场景 | 行为 | 错误面 |
|------|------|--------|
| agent_* = `__default__` | **修复后**：不覆盖模板模型，正常执行（§5.1） | 无（修复点；执行日志可查模型回退） |
| agent_* = 裸模型名（无 `/`） | 执行层 warning + 回退跟随默认（§5.1 兼容策略）；前端格式标记 | 无（存量零迁移；新数据 UI 引导） |
| agent_* = 未知模型名（如 `foo/bar`） | 允许保存；前端「未注册模型」标记；执行时 provider 配置不存在 → LLM 调用失败走既有重试/失败语义 | 执行失败（既有 PipelineError 路径，非本模块新增） |
| agent_* = 空字符串 | 422（既有 validator L79-81） | 输入拒绝 |
| agent_* = null | **默认模板模式**（agent_order 空）：不跳过，跟随模板默认；**配置驱动模式**（非空）：角色跳过执行，下游空输入降级（§5.3.1 步骤 4） | 无（设计语义；日志记跳过） |
| GUI 全自动/续写 | 写作页入口 → 管线 execute（builtin:write_auto / write_continue）→ 经 _apply_agent_order + _merge_role_configs，按 agent_order/agent_* 执行 | 无 |
| 终点角色非内容型 | 装配后校验终点角色类型（architect/auditor 非成品）→ 违规回退默认拓扑 + warning 或 API 422（实现确认） | 防御回退（评审 🔴-1） |
| 全部角色关闭 | API 校验拒绝（至少 1 启用角色）；执行层回退默认拓扑 + warning | 输入拒绝 / 防御回退 |
| agent_order 缺省/空列表 | 模板默认拓扑执行（零迁移） | 无 |
| agent_order 含自定义角色名（非内置，支持 + 扩展 6 内置皆可） | API 允许；执行层经通用节点执行（prompt 由模板 roles 装配 / Agent 真源，§5.3.4/§5.7.4） | 无 |
| 自定义角色 prompt 缺失（非内置且模板 roles 未定义） | 执行层跳过 + warning；模板补定义后恢复 | 防御跳过（§2.3） |
| agent_order 空槽（[]） | 该槽位无角色，跳过执行（跳号允许） | 无（规范化） |
| agent_order 缺启用角色 | API 422；执行层回退默认 | 输入拒绝 / 防御回退 |
| agent_order 跨层重复 | 存储层/API 422 | 输入拒绝 |
| 引用未来层角色变量（自由排序导致） | 空注入（§5.3.3）+ UI 保存时提示 | 无（软降级，用户自由排序代价） |
| 同层并行角色互相引用（如 writer/auditor 同层且 prompt 引用对方） | 空注入（同层未执行） | 无（软降级；UI 提示「同层角色并行，互相不可见」） |
| AgentTemplate 项目（含自定义角色） | agent_order 拓扑作用于全部启用角色（内置 + 模板自定义）；模板 roles 提供自定义角色 prompt/模型覆盖（§5.3.4）；模板不改变 agent_order 拓扑本身 | 无（文档化行为） |
| 存量项目（无 agent_order 键） | Pydantic 默认空列表 → 模板默认拓扑 | 无（零迁移） |
| GUI 重启 | config 持久化（PATCH 落库）→ 读回三态/拓扑保持 | 无 |
| 模型在 provider 注册表被删 | 前端标记「未注册模型」；保存仍允许 | 提示不阻塞 |
| 世界观顾问/润色师进链 | 默认不在链中；用户「添加角色」→ 进链执行（prompt 从 Agent 真源取，§5.7.1/§5.7.4） | 无（设计语义；seed 迁移后 role_key 非空） |
| 存量 DB 世界观顾问/润色师 role_key 为空 | 前端按 role_key 派生 → 该角色不渲染（现状）；迁移脚本补值后恢复渲染 | 无（一次性迁移，§5.7.1） |
| 自定义 Agent 进链 | Agent 管理创建 → role_key 分配 → 角色池出现 → 添加进链（agent_roles 三态）→ 执行（prompt = AgentEntity.system_prompt） | 无（设计语义；删除 Agent 后链引用清理见下） |
| 自定义 Agent 被删除 | 链中残留 `agent_roles` 键与 agent_order 引用 → 执行层跳过 + warning（prompt 缺失防御，§2.3）；UI 角色池不再显示该角色 | 防御跳过（§5.7.2） |
| 模板引用已删除自定义 Agent | 模板 roles 快照保留（模板是快照）；执行时模板键 → Agent 真源缺失 → prompt 缺失跳过 + warning | 防御跳过（§5.7.5） |
| 添加角色时角色池为空 | 「添加角色」按钮禁用/提示「全部角色已在链中」 | 无（UI 边界） |
| 模板自定义键无 Agent 实体 | 链仍渲染该模板自定义角色行（既有语义，模板 roles 是链字段补充来源，§5.7.2）——与 Agent 管理真源并行存在 | 无（兼容既有模板） |
| 自定义 stage 列表含未知 role_key | 服务端 `_build_custom_stages` → `ValueError` → `AgentServiceError` → API **422**「未知 stage 角色: xxx」（**不静默跳过**，§5.8.2.1） | 输入拒绝 |
| 自定义 stage 列表含重复 role_key | 拓扑校验「阶段 id 不能重复」→ 422「自定义管线配置无效: …」 | 输入拒绝 |
| `stages` 与 `pipeline_config` 同时提供 | DTO 校验 **422**「stages 与 pipeline_config 互斥」 | 输入拒绝 |
| 自定义管线 + `mode=supervisor` | DTO 校验 **422**「自定义 stage 仅支持 static 模式」 | 输入拒绝 |
| `stages = []` | DTO 校验 **422**「stages 不能为空」 | 输入拒绝 |
| 项目 `agent_order` 非空 + 显式自定义管线 | **显式拓扑优先**：不调用 `_apply_agent_order`（`agent_order` 被旁路，不报错；§5.8.3） | 无（文档化行为） |
| 项目关掉 `agent_polisher` 但显式 `--pipeline polisher` | 仍执行（三态是模型参数、不改显式拓扑；§5.8.3） | 无（设计语义） |
| 自定义管线 YAML 文件不存在 / 解析失败 / 非管线结构 | **CLI 本地** `VALIDATION_ERROR` + 退出码 1（不发起请求，§4.1） | 输入拒绝 |
| Agent 真源加载失败 + 自定义 `stages` | `agents_by_role` 为空 → 恒「未知 stage 角色」422（诚实失败，不静默降级；§5.8.2.1） | 输入拒绝 |
| 自定义管线含 `worldview` / `polisher` | **真实执行**并出现在执行记录 `stages` 结果中；skill 按既有语义装配（显式 ∪ 通用） | 无 |
| 内置 4 条管线 | **零变化**：stage 序列与既有完全一致（回归断言，§13 M10/M11） | 无 |

---

## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 模型/契约（后端） | ProjectConfig.agent_order 默认空/结构/空槽允许（空槽）/长度 >10 拒绝/跨层重复拒绝；agent_* 三态 validator 回归 | ≥90% |
| 服务（后端） | `_merge_role_configs` sentinel 不覆盖 + 裸名回退 + prompt 覆盖（mock LLM 断言 model/system_prompt 参数）；`_apply_agent_order` 双模式分派（空=默认模板模式 null 不跳过）/层级重排（含并行层）/跳过过滤/空回退/非法回退/全连接边（input_from=前序全部、output_to=后序全部）/一致性校验 | ≥90% |
| 集成（后端） | LangGraphAgentPipeline 层级拓扑 validate() 通过（多入口/多终点 + 可达性）；**并行层断言契约：mock 升级为 per-role 响应表（按 stage.id 分发非调用序）——「层间顺序确定」断言 = 调用序号单调（层 2 全部 > 层 1 全部）；「层内并行」降级为不变量「同层角色均被执行 + input_from 无同层引用」（不承诺调用序）**；环检测回归；未执行角色空注入（`.get` 防御）；**未来层引用/同层互引 → 空串（占位符扫描注入，B8）**；**自定义角色执行（模板 roles 装配 prompt → 通用节点）**；**终点角色类型校验（成品身份）**；**双模板（write_auto/write_continue）注册与执行契约** | ≥90% |
| 前端组件 | AgentChainCard 三态交互（Switch 开→Select 出现；「跟随默认」→ sentinel；选模型→模型名；off→null）；未注册/格式标记；槽位号编辑（0-9，改号 → PATCH 结构正确）；Select 选项 = provider-configs chat 模型 mock | ≥90% |
| E2E（如扩） | 设置页 Agent 分类：开角色→选模型→PATCH 落库→重启保持；调槽位→PATCH→重启保持 + 写作按槽位序执行；**写作页全自动/续写 → 管线执行（stderr 可查模型名/层序，B2）**——落点 `tests/e2e/e2e-settings.spec.ts` + `e2e-writing.spec.ts`（如存在）追加；**E3-1 switch 计数 4 与 E3-2 默认模型选项断言按 R1 清单修改** | 手工/E2E |
| E2E | **E4-1 链增删改**：添加世界观顾问 → 行渲染 + PATCH agent_worldview/agent_order → 重启保持；关闭 → 从 agent_order 移除（数据断言）；**E4-2 自定义 Agent 进链**：Agent 管理建自定义 Agent → 角色池出现 → 添加进链 → 执行（stderr 可查）；**E4-3 模板任意角色**：TemplateDialog 编辑含世界观顾问的模板 → 保存 → 回读保持 | 手工/E2E |
| 回归 | 全仓零回归（agentic 路径不动；extraction default_model 消费链回归 + 裸名兼容断言）；AgentChainCard/AgentRelationEditor/TemplateDialog 三组件派生改造后既有测试同步更新 | 全仓 ≥60%（ADR-027 门禁） |
| 自定义管线（后端） | `_build_custom_stages` 纯函数单测（顺序单链 / 真源 name+prompt / 未知 key → ValueError / 单元素链）；`_build_pipeline_context` 分派（`stages` 形态、`pipeline_config` 形态、模板查找跳过、互斥与 supervisor 由 DTO 拦、拓扑非法 → AgentServiceError）；**内置 4 条管线 stage 序列逐条零回归**；`list_templates()` 恒 4 条 | ≥90% |
| 配置契约（后端） | `PipelineExecuteRequest` validator（互斥 / static-only / 空序列 / 合法两形态放行） | ≥90% |
| CLI | `agent run --pipeline` 三形态判别（builtin → 无新字段；role 串 → `stages`；YAML 路径 → `pipeline_config`）；YAML 不存在/坏结构 → 退出码 1 + 不发请求；空 role 列表 → 退出码 1 | ≥90% |
| API | `POST /agent/pipelines/execute`：`stages`/`pipeline_config` 透传 → 202；互斥 / supervisor / 空序列 → 422（Pydantic 层）；未知 role_key / 拓扑非法 → 422（service 层，mock svc 模拟） | ≥90% |

**RED 形态**：后端 `_apply_agent_order` 不存在 → ImportError；sentinel 修复 → 断言 `llm.chat(model)` 参数 ≠ `__default__` 失败；validate 放宽 → 并行层构造断言失败；前端 Select/序号缺失 → RTL 查询失败。

**测试无网络约束**：模型列表数据源一律 mock `apiFetch`（既有 `stores/models.test.ts` 模式）；管线执行 mock LLMClientProtocol（既有 test_agent_service 模式）；并行断言用 asyncio.gather 顺序记录。

---

## 10. 不在范围内

| 项 | 归属 |
|----|------|
| DAG 关联关系编辑（agent_relations 语义/UI，同层条件/分支边） | 后续里程碑（本模块仅预留演进约束，§5.4） |
| F29 Supervisor 自主编排 + HITL + subagent | 后续里程碑（同编排域，本模块合入后） |
| F27 agentic 路径多角色化 / 按 agent_order 编排 | 不规划（F27 为单 agent 闭环；如需「顺序多 agent」属新产品决策，另行拍板） |
| 自定义 Agent 能力差异化白名单 | 后续里程碑 F39-F41（本模块已解锁「模板定义角色 → 管线执行」链路，§5.3.4） |
| **自定义 Agent 数据面**（RoleTemplate prompt/name + ProjectConfig 自定义字段 + AgentChainCard 自定义行） | **本里程碑实现，拆分多个交付项**：① RoleTemplate 扩展 + _merge_role_configs prompt 覆盖；② ProjectConfig extra 自定义角色三态字段 + API 校验口径；③ AgentChainCard 自定义角色行 UI。验收锚点 = 用户可在 UI 创建/编排/执行自定义 Agent 全链路 |
| **GUI 写作入口管线化**（write_auto/write_continue 模板 + 写作页接线） | **本里程碑实现，拆分 2 个交付项**：① 模板注册 + prompt 编写；② 写作页入口切换 + 执行状态 UI（§5.6） |
| 拖拽排序 UI | 本期上移/下移（层级移动，§5.3）；拖拽标注后续里程碑候选 |
| 模型存在性强制校验（不存在拒绝保存） | 既定口径「不存在允许保存但标记」——强制校验不规划 |
| AgentTemplate 自定义拓扑按 agent_order 重排 | 不规划（模板拓扑 = 模板作者意图，§5.3.4 边界） |
| agent_order 与 F29 supervisor 编排衔接 | F29 spec 定义 |
| 全局默认模型选项进 agent_order | 无此语义（agent_order 是角色拓扑，非模型） |
| config.model 存量裸名数据迁移（DB 改写） | 不规划（执行层兼容回退零迁移，§5.1；新数据 UI 引导修正） |
| Agent 管理 CRUD 本身（Agent 列表/创建/编辑/删除 UI） | 后续里程碑 F41 |
| 自定义 Agent role_key 手动指定 UI（创建时显式填） | 实现拆 issue 时定稿（§5.7.2 默认服务层自动分配；显式指定不阻塞） |
| 链角色拖拽重排 | 后续里程碑 候选（本期上移/下移，§5.3） |
| 模板角色「场景化 prompt 向导」（为世界观顾问/润色师自动生成场景 prompt） | 不规划（prompt 从 Agent 真源取，模板 roles 为可选覆盖，§5.7.4） |
| **内置 6 角色管线补齐**（方案 A：write_chapter 等扩到 6 角色 / 新增世界观·润色专用模板） | **不规划** |
| **GUI 自定义管线编辑器**（可视化编辑/保存自定义管线） | 不规划（本期仅 CLI `agent run --pipeline` + REST，§5.8.4） |
| **内置 Agent 编辑放开**（`PATCH /api/v1/agents/{id}` 允许改内置） | 不规划 |
| **自定义管线持久化注册**（存库后可被 id 引用 / 出现在 `agent template pipelines`） | 不规划（本期为「一次执行携带拓扑」，§5.8.4；后续如需固化再立项） |

---

## 11. 依赖关系

- **依赖**：三态语义（本项目扩展执行层解析）、F26 deepagents 集成（模型名剥离复用）、F27 agentic writer（兼容性边界 §5.5）、**Agent 真源（role_key 映射，链动态化前置，§5.7）**、F41 Agent 管理（角色池来源，§5.7.2 消费其 `GET /api/v1/agents`）、项目配置 CLI 命令面（agent_order CLI 读写联动，§4）、F9/F13/F34 服务（工具包装对象无关）、`project.config.model` 消费链（格式统一的影响面，修复后需回归提取域）。
- **被依赖**：执行顺序编辑依赖模型选择（同轨道串行）；F29 Supervisor 依赖本模块合入（同编排域串行）；F46 DAG 以本模块的 `agent_order` 为演进基线（§5.4）；链动态化依赖 Agent 真源的 role_key 单一来源；F46 关系编辑器依赖链动态化（`AgentRelationEditor` 角色列表随真源派生，§5.7.2——本模块修订影响其前端组件，实现时同步改）。
- 编号口径：F39/F40/F41 分配给多 Agent 模块，本模块为 F42。
- deepagents 兼容性（已确认）：agent_order 消费方仅 LangGraphAgentPipeline；deepagents 装配零改动（§5.5）。

---

## 12. 决策表

全 spec 唯一决策落点。

| 决策点 | 选择 | 理由 | 备选（否决） |
|--------|------|------|--------------|
| 1 spec 合并 | 单个 F42 spec 覆盖「模型选择」+「执行顺序编辑」两期配置面 | 两期改动落在同一组件、同一文件域，分开会产生双份真相 | 两份 spec（同一文件域双源） |
| 2 顺序配置存储 | `agent_order: list[list[str]]` 层级嵌套（外层 = 槽位 0-9，内层 = 并行组），默认模板占 0-3 | 用户心智「1、2、3、4 序号 + 同序并行」；层级 = DAG 拓扑层特化，为 F46 铺路；`list[str]` 无法表达并行 | `list[str]` 平铺（无并行）；extra 字典（无 validator）；把 position 写进 stage（与 DAG 边冲突） |
| 3 执行拓扑实现 | `_apply_agent_order` 纯函数按层级重建全连接边 | LangGraph 按 DAG 边调度，改 stages 列表顺序无效；全连接边使任意重排后 validate 恒通过 | 改列表顺序（无效）；自由任意序无约束（变量字面量残留）；形态预设（与模板域重叠） |
| 4 null 关闭语义 | 真禁用（跳过角色 + 下游空输入），且分双模式：`agent_order` 空 = 默认模板模式（null 不跳过）/ 非空 = 配置驱动模式（null 跳过） | 兑现 UI「关闭」承诺；双模式避免默认项目全空转 | 无条件真禁用（默认项目空转）；无条件跟随模板（「关闭」承诺落空） |
| 5 校验双层 | API 422（输入卫生）+ 执行层回退默认序（数据防御） | 两层职责分离；执行层永不因配置损坏中断写作 | 仅 API 校验（存量坏数据中断写作）；仅执行层（非法输入无即时反馈） |
| 6 sentinel 执行解析 | `__default__` 不覆盖模板模型（`_merge_role_configs` 修复） | 消除执行层 ValueError 缺陷；节点保持纯净 | 保持现状（执行失败）；在节点层判断（散落） |
| 7 模型格式 | 全链路 `provider/model`（`agent_*`、`config.model`、AgentPanel 选择器统一） | `parse_model_string` 是硬契约（无 `/` 抛错）；「跟随默认」回退链依赖格式合规；存量裸名执行层兼容回退 | 三种格式并存（定时炸弹） |
| 8 模型选择数据源 | 复用 `GET /api/v1/provider-configs` 的 chat 模型列表；不校验存在性（允许保存 + 前端标记） | 用户自定义 provider 也能选；模型可后续新增，硬校验阻断创作 | 硬编码 provider 名单；强制存在性校验 |
| 9 变量注入 | 前序全部层已执行角色输出注入；未执行层/同层 → 空串 | 消除未知占位符字面量残留，任意引用恒有值 | 只注入直接上游（重排后残留）；保留字面量（prompt 损坏） |
| 10 执行引擎 | 单链 → 分层并行：validate/execute 放宽多入口/多终点；4 具名节点 → 通用节点（upstream 从 `input_from` 推导） | 层级模型要求多入口/多终点；通用节点使任意角色名可执行 | 保持唯一入口/终点（并行不可表达）；每角色一份节点代码（无法扩展） |
| 11 执行节点容量 | 10 槽（0-9），默认模板占 0-3，槽 4-9 给自定义 Agent；空槽允许（跳号），长度 > 10 拒绝 | 容量与 UI 心智一致；为自定义角色预留 | 限 4 内置（自定义 Agent 无法执行）；无限槽位（校验失控） |
| 12 GUI 写作路径 | 入口管线化：新增 `builtin:write_auto` / `builtin:write_continue` 双默认模板，写作页「全自动/续写」走管线 | 否则配置面在 GUI 主路径不可达（验收无处落地）；双模板对应两种写作意图 | 仅 CLI/API 消费（GUI 主路径不可达）；把 agentic 路径多角色化（破坏 F27 闭环） |
| 13 自定义 Agent 数据面 | 本里程碑同步实现（`RoleTemplate` 补 `prompt`/`name` + `ProjectConfig` 自定义字段 + 链 UI 自定义行） | 槽 4-9 无数据面即为空承诺；自由排序的核心动机是可编排自定义角色 | 顺延（动机落空）；本期不做（空承诺） |
| 14 成品身份 | `final_output` = reviser 输出；reviser 被禁用/未启用时 = 最后一个非 architect/auditor 角色输出；违规终点回退 + warning | 调整顺序/禁用角色后成品类型不得静默漂移 | 不定义（成品类型漂移） |
| 15 CLI 归属 | 与 CLI 项目配置命令面联动（不另建 agent_order 命令） | 同一命令面双改会冲突 | 模块内补 CLI config 命令 |
| 16 DAG 预留 | 层级 = 拓扑基线；关系 = 增强语义；两配置字段并存时关系优先（由 F46 定义） | 演进路径不被堵死，且本模块不承担 DAG 实现 | 本模块实现 DAG（范围膨胀）；不预留（演进堵死） |
| 17 链角色集合来源 | 一律从 `GET /api/v1/agents` 真源派生（`role_key` 单一来源），三组件统一规则 | 前端硬编码 4 键不随 Agent 管理增减（漂移）；后端模板 stage 白名单同样过时 | 前端白名单；后端模板白名单 |
| 18 内置角色 role_key | 补 `worldview` / `polisher`（稳定标识） | 缺 role_key 的角色进不了链；显示名做键脆弱且 i18n 双份 | 保持 None；用显示名匹配 |
| 19 自定义 Agent 进链身份 | 服务层分配稳定 `role_key`（name slug 化 + 冲突后缀） | 链引用稳定、用户可读；改名不断链 | 用 Agent id（数字键不稳定）；用显示名（改名断裂） |
| 20 执行层内置 6 角色 stage 构造 | 模板 stages 缺失角色 → 占位 stage，prompt 从 `AgentEntity` 真源取 | 不扩内置模板（默认拓扑不变、模板数据不膨胀）即可执行任意内置角色 | 内置模板扩到 6 角色（默认拓扑变化）；拒绝进链 |
| 21 模板 roles 任意组合 | `TemplateDialog` 角色列表从真源派生，`roles` 存 `Record<string, RoleTemplate>` | 模板需能引用任意角色组合；固定 4 键使自定义 Agent 无入口 | 模板 4 角色硬编码；模板角色 = 链角色（拓扑与覆盖层混淆） |
| 22 无管线可执行角色 | 自定义 stage 通道（`--pipeline` role 序列 / YAML），不补内置管线 | 用户诉求是「能跑到世界观顾问/润色师」，自定义通道覆盖面更大且不改默认拓扑 | 补齐 6 角色内置管线（默认拓扑膨胀）；放开内置 Agent 编辑（内置只读语义） |
| 23 自定义拓扑载体 | 请求体 `stages`（role_key 序列，服务端按真源展开）与 `pipeline_config`（完整 YAML）双形态，互斥 | role 序列覆盖常用场景；YAML 覆盖自定义 prompt/边；两者语义不同 | 只支持 role 序列（YAML 能力闲置）；只支持 YAML（一句话链要写整份配置）；持久化注册管线（新表 + 生命周期） |
| 24 显式拓扑优先 | 显式拓扑旁路 `agent_order` / `agent_relations` | 「role 序列即拓扑」是显式意图，叠加重排会静默摘除用户点名角色 | 叠加项目 agent_order；报错要求二者一致（无谓约束） |
| 25 未知 role_key 处置 | 全部 `ValueError` → 422 | 显式意图必须被兑现；静默跳过会产生空管线/少一段 | 静默跳过；回退内置拓扑（跑用户没要的链） |
| 26 自定义 stage 的 skill 来源 | 复用既有 `_attach_agent_skills`（`stage.id == role_key`） | 单一装配路径，避免双份真相 | 另建装配路径；自定义管线不装配 skill |
| 27 role_key 生成与迁移 | 默认服务层自动分配；存量 DB 两个内置角色 role_key 补值（迁移脚本或 seed 升级钩子） | 存量项目也要能进链 | 手动改库（不可运维） |
| 28 执行层 Agent 真源注入 | 服务层注入 `AgentRepositoryProtocol`（非复用 API 数据缓存） | 执行层不应依赖 HTTP 层缓存；协议注入可测 | 复用 API 缓存（层间耦合） |

---

## 13. 验收标准

> M1-M3 = 模型选择（配置面 + 执行层解析）；M4-M6 = 执行顺序编辑；M7 = CLI 与全仓回归；M8-M12 = 写作入口管线化 / 链动态化 / 自定义管线。

- **M1 三态执行修复**: `pytest backend/tests/unit/domain/services/test_agent_service.py` — `agent_* = "__default__"` 执行不抛 ValueError 且 mock LLM 收到模板角色模型（非 sentinel）；`agent_* = null` → 角色跳过；裸模型名 → warning + 回退跟随默认
- **M2 模型选择 UI**: `pnpm vitest run src/components/AgentChainCard.test.tsx`（新建）— 开关打开条件渲染 Select（数据源 mock provider-configs chat 模型）；选「跟随默认」→ PATCH sentinel；选具体模型 → PATCH provider/model；关闭 → PATCH null；未注册/格式不合规值显示标记且保存不阻塞；默认模型 Select（settings.tsx）数据源 = provider-configs chat 列表
- **M3 模型选择持久化 + 写作验证**: GUI 打开角色→选模型→保存→重启保持；**写作流程（全自动/续写管线路径，B2）按指定模型执行（内核 stderr 可查模型名）**；关闭 → 角色跳过（配置驱动模式，stderr 可查跳过日志）；config.agent_* 值均为 provider/model 或 sentinel 或 null；**agentic 路径不在本验收范围（保持全局默认模型，§1.3 边界）**
- **M4 层级拓扑 + 校验**: `pytest backend/tests/unit/domain/models/test_project_config_order.py` + `test_langgraph_pipeline.py` — agent_order 层级结构/空槽允许/长度 >10 拒绝/跨层重复拒绝；PATCH 语义校验 422（缺启用角色）；**任意角色名允许（内置 + 自定义）**；存量项目零迁移；**并行层断言 = 层序单调（per-role 响应表 mock，R2）**；变量空注入防御（未来层/同层 → 空串）；环检测 + 可达性回归；**终点角色类型校验（成品身份）**
- **M5 执行拓扑重排**: `pytest backend/tests/unit/domain/services/test_agent_service.py` — `_apply_agent_order` **双模式分派（空=默认模板模式 null 不跳过）/层级重排（含 `[["architect"],["writer","auditor"],["reviser"]]` 并行场景）/跳过过滤（配置驱动模式）/空回退/非法回退/一致性校验**；全连接边断言（input_from=前序全部、output_to=后序全部）；重排后 validate() 恒通过；**自定义角色执行（模板 roles 装配 → 通用节点，upstream 从 input_from 推导）**
- **M6 槽位编辑 UI + 持久化**: GUI 每角色槽位编号 **0-9**（同编号=并行组）→ PATCH agent_order 层级结构 → 重启保持；默认模板显示槽 0-3；写作流程按槽位序执行（内核 stderr / 执行日志可验证：**层间串行可验证，层内并行不承诺 stderr 序**）；保存时角色级空输入提示（静态依赖分析）；**调整顺序/关闭角色后成品类型不变（reviser 输出）断言**
- **M7 CLI 读写 + 回归**: 依赖项目配置命令面——`inkflow project get --id N` 输出含 agent_order、update 可写；**全仓零回归** + 覆盖率门禁（ADR-027）
- **M8 GUI 写作管线化**: `pytest`（双模板注册/执行契约）+ 手工 — 写作页「全自动生成」→ 管线 execute（builtin:write_auto）按 agent_order/agent_* 执行（stderr 可查模型名/层序）；「续写」→ builtin:write_continue；执行状态展示（进行中/成功/失败 + 成品落章）；**「写作流程按指定模型/新顺序执行」在 GUI 主路径通过**
- **M9 链动态化 + 模板联动**: `pytest backend/tests/unit/domain/services/test_agent_entity_service.py` + `test_agent_service.py` + `pnpm vitest run src/components/AgentChainCard.test.tsx src/components/TemplateDialog.test.tsx` — ① role_key 全集 6（世界观顾问=worldview/润色师=polisher，存量 seed 迁移补值）；② 链增/删/改角色（添加角色 → 三态 + agent_order → 重启保持；关闭 → 从 agent_order 移除）；③ 自定义 Agent 进链（创建 → role_key 分配 → 角色池 → 进链执行，prompt = AgentEntity.system_prompt）；④ 模板引用任意角色组合（TemplateDialog 角色列表从真源派生，roles Record 保存/回读）；⑤ 执行层缺失角色 stage 构造 + 成品身份扩展（worldview 排最后 → 成品 = worldview 输出）；⑥ 三组件 4 键硬编码删除（AgentChainCard/AgentRelationEditor/TemplateDialog）+ 回归；⑦ GUI 手工闭环：设置页链添加世界观顾问 → 保存 → 重启保持 → 写作按新链执行（stderr 可查）
- **M10 自定义 stage 管线**: `pytest backend/tests/unit/domain/services/test_agent_service_custom_stages_1475.py` + `pytest ../tests/cli/test_cli_agent_custom_pipeline_1475.py ../tests/api/test_pipeline_custom_stages_1475.py` — ① `_build_custom_stages` 顺序单链 + 真源 name/prompt + 未知 role_key → `ValueError`；② `stages` 形态端到端：自定义序列（含 `worldview` / `polisher`）真实执行且出现在执行记录 `stages` 结果（M6 实证贴 PR body）；③ `pipeline_config`（YAML）形态端到端：`agent validate -f <yaml>` 通过 → `agent run --pipeline <yaml>` 跑通；④ 自定义 stage 的 Agent 携带其 `skill_ids` 命中的 skill（对齐既有 skill 装配语义）；⑤ 互斥 / `mode=supervisor` / 空序列 → 422；未知 role_key / 拓扑非法 → 422；⑥ **内置 4 条管线（write_chapter/write_auto/write_continue/chat）stage 序列逐条零回归**；`list_templates()` / `agent template pipelines` 恒 4 条；⑦ `PATCH /api/v1/agents/{id}` 对内置 Agent 仍 **409**（负例）
- **M11 自定义 stage 负例**: ① 显式管线 + 项目 `agent_order` 非空 → 拓扑仍为显式序列（`agent_order` 被旁路）；② Agent 真源为空 + 自定义 role_key → 422「未知 stage 角色」（不静默跳过）；③ YAML 文件不存在 → CLI 退出码 1 且不发请求
- **M12 自定义 stage 模型继承**: `pytest backend/tests/unit/domain/services/test_agent_service_custom_stages_1475.py::TestCustomStageInheritsGlobalDefaultModel` — ① role 序列 `_build_custom_stages` 产出 stage `agent.model == config.llm_default_model`（非 `openai/gpt-4o`）；② 引用模板项目中 role 序列 / YAML 两形态经 `_merge_role_configs` 后仍为全局默认；③ YAML **显式**写 `model` 不被覆盖；④ 优先级保持：`--override <role>.model=` > 项目 `agent_<role>` > 全局默认；⑤ 全局默认未配置（`""`）→ stage `model=""`（不落 `openai/gpt-4o`）；⑥ 内置 4 条管线 stage `agent.model` 仍为全局默认（零回归）；⑦ 同类路径：`_apply_agent_order` 占位 stage（模板 roles / agent_source 两分支）继承全局默认

---
