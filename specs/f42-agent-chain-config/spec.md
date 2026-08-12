# F42: Agent 链配置驱动编排（agent-chain-config）功能规格

**Spec 版本**: 1.0
**日期**: 2026-08-12
**依据**: 0.8.0 路线图拍板记录 5-9（design/inkflow-0-8-0-roadmap-2026-08-12.md）+ Issue #268（Agent 链模型选择）+ Issue #269（Agent 执行顺序编辑）+ #225 三态语义（已合入）+ F26/F27 已合入实现源码核查
**所属阶段**: 0.8.0（轨道 B Agent 编排：F42 spec → #268 → #269 → #161 F29），估算 4-7 人天（#268 前端 2-3 + #269 前后端 2-4）
**关联 Issues**: #268（模型选择，W2 启动）、#269（执行顺序，W3，🔗#268）、#270（关联关系编辑，0.9.0 预留，不实现）
**依赖**: ✅ #225 三态语义（0.7.0 已合入）· ✅ F26 deepagents 集成层（PR #236 已合入）· ✅ F27 agentic writer（已合入）· ✅ F9/F13/F34 服务（工具包装对象）· ⏳ #251 CLI project update（0.8.0 P1，agent_order CLI 读写联动）· ⏳ #268 先于 #269（编排域串行）
**参考 ADR**: ADR-E（编排引擎=Deep Agents harness 0.7.5）、ADR-015（LangChain 隔离）、ADR-019（编号口径）
**状态**: 待实现 🔲

> **模块类型声明**: 本模块为「配置驱动编排型」变体——无新实体表、无新业务端点；在既有 Agent 管线（LangGraphAgentPipeline 四角色链）上增加**配置驱动**能力：① 三态模型选择补全 UI 与执行层解析（#268）；② 执行顺序由模板硬编码改为 `agent_order` 配置驱动（#269）；③ 预留 #270 DAG 关联关系扩展边界（0.9.0，不实现）。编号依据：AGENTS.md 模块类型谱系口径下，F42 为 Agent 化升级链（F26-F29）的配置面补全模块，与 F26（集成层）/F27（闭环）/F28（记忆）平行不冲突。

---

## 1. 概述

F42 合并覆盖 **#268（Agent 链模型选择）** 与 **#269（Agent 执行顺序编辑）** 两份 issue，作为两期实现的唯一真相来源。#270（关联关系编辑）仅作边界预留，不实现。

### 1.1 现状缺口（2026-08-12 源码实证）

| # | 缺口 | 实证 | 归属 |
|---|------|------|------|
| ① | AgentChainCard 打开角色**不能选择模型**——只能写入 sentinel `__default__`（跟随默认） | `frontend/packages/renderer/src/components/AgentChainCard.tsx` L66 注释「本期无模型选择 UI」；L59 打开恒写 `AGENT_DEFAULT_SENTINEL` | #268 |
| ② | 默认模型 Select 硬编码 `['openai','deepseek','ollama']`（provider 名，非模型名） | `pages/settings.tsx` L433-437 | #268 |
| ③ | **执行层 sentinel 缺陷**：`__default__` 会被当作模型名覆盖模板模型 → `llm.chat(model="__default__")` → `parse_model_string("__default__")` 无 `/` 抛 ValueError → 管线失败 | `agent_service.py` L232-234 `if project_model:`（非空即覆盖）+ `pipeline_nodes.py` L91 `model=stage.agent.model` + `provider_config.py` L207-211 | #268（必须修） |
| ④ | 执行顺序**模板硬编码**：builtin:write_chapter 四阶段链边 architect→writer→auditor→reviser，用户无法调整 | `infrastructure/agent/pipeline_templates.py` L65-89（stages 手写 input_from/output_to） | #269 |
| ⑤ | 无 `agent_order` 配置字段 | `domain/models/project.py` ProjectConfig（L58-71 无该字段） | #269 |
| ⑥ | CLI 无法读写项目 config（无 `project update` 命令） | `cli/commands/project.py` 仅 create/list/get/delete/restore | #269（#251 联动） |

### 1.2 与样板差异

非 F9 实体 CRUD（无新增表）、非 F26 集成型（无新基础设施包）、非 F27 闭环型（无新业务流程）——本模块是**配置面 + 编排面改造**：后端 ProjectConfig 扩展 1 字段 + 执行链重排逻辑；前端 AgentChainCard 交互升级。

### 1.3 边界声明

- **不含** #270 关联关系编辑（`agent_relations`，0.9.0）：本模块只实现**顺序**（链式拓扑基线），关系增强语义（并行/条件/分支 DAG）留给 0.9.0。配置模型与执行链设计**不得堵死** DAG 演进（§5.4 演进约束）。
- **不含** F29 Supervisor 自主编排（#161，0.8.0 W5）：supervisor 消费 deepagents subagent 机制，与本模块的 agent_order 管线编排不同域（§11 依赖关系）。
- **不含** F27 agentic 写作路径的多角色化：F27 AgenticWriterService 为 deepagents 单 agent（writer_agent）ReAct 循环，`model=config.llm_default_model`（全局默认，`api/deps.py` L220-240）——**不消费** `agent_*` 四角色字段与 `agent_order`（§5.3 兼容性结论）。

---

## 2. 数据模型

### 2.1 ProjectConfig 扩展（`domain/models/project.py` MODIFY）

```python
class ProjectConfig(BaseModel):
    # ...既有字段不变（model/agent_*/temperature/role_*_temperature/template_id/writing_style/default_words/extra）

    agent_order: list[str] = Field(default_factory=list)
    """Agent 链执行顺序 — 角色字段名数组（agent_architect/agent_writer/agent_auditor/agent_reviser）。

    - 空列表 = 未配置 → 执行使用模板默认顺序（零迁移，旧项目无感）
    - 非空 → 执行链按此顺序重建（§5.3）
    - 校验（API 层 + 执行层双层，§2.3）
    """

    @field_validator("agent_order")
    @classmethod
    def validate_agent_order(cls, v: list[str]) -> list[str]:
        """存储层类型校验：只做元素类型与去重（重复元素静默去重保留首个位置）。

        语义校验（角色集合一致性）在 API 层与执行层完成，见 §2.3——Pydantic 层
        不做跨字段校验（依赖 agent_* 启用状态，Q1 拍板后定口径）。
        """
        seen: set[str] = set()
        result: list[str] = []
        for item in v:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("agent_order 元素必须为非空字符串")
            if item not in seen:
                seen.add(item)
                result.append(item.strip())
        return result
```

- **字段命名口径**：`agent_order` 存**角色字段名**（`agent_architect` 等，带 `agent_` 前缀），与 issue #269 方案一致；内部 stage.id 为不带前缀的角色名（`architect` 等，`pipeline_templates.py` L36-63）——执行层转换映射：`agent_xxx → xxx`（§5.3）。
- **默认值**：`default_factory=list`（空 = 模板默认顺序）——**零迁移**：旧项目 config JSON 无此键 → Pydantic 默认空列表；GUI 上显示模板默认序（Architect→Writer→Auditor→Reviser）。

### 2.2 三态语义（#268，#225 既有语义不变，本模块补 UI + 执行层解析）

| agent_* 值 | 语义 | 执行层行为（§5.1 修复后） | UI |
|------------|------|--------------------------|-----|
| `null`（缺失） | 关闭（不指定项目模型） | 不覆盖模板角色模型 → 模板/全局默认执行（Q1 拍板后定是否跳过） | Switch off |
| `"__default__"`（AGENT_DEFAULT_SENTINEL） | 跟随默认 | **修复点**：不覆盖模板角色模型（现状缺陷会 ValueError，§5.1） | Switch on + Select 选中「跟随默认」 |
| `"<provider>/<model>"`（如 `"zhipu/glm-4.5"`） | 指定模型 | 覆盖模板角色模型（parse_model_string 剥离前缀后调用） | Switch on + Select 选中具体模型 |

> 存储格式说明：`agent_*` 具体模型值存 **provider/model 格式**（与 `ProviderConfig.default_model` 同格式、与 `parse_model_string` 解析契约一致）——不允许存裸模型名（无 `/` 会在执行层 ValueError）。

### 2.3 agent_order 校验（双层）

| 层 | 行为 | 位置 |
|----|------|------|
| 存储层（Pydantic） | 类型 + 去重（§2.1） | `domain/models/project.py` |
| API 层（PATCH） | 语义校验：非法 → **422**（detail 中文说明）；非法定义 = ① 含未知角色字段名（非 4 角色之一）② 重复（存储层已去重，防御）③ **不含全部角色（Q1 拍板后定口径：4 角色全含 vs 启用角色子集）** | `api/routers/project.py`（或 `project_service.py`，实现确认） |
| 执行层（防御） | 任何非法（含存量数据手工损坏）→ **回退模板默认顺序**，记 warning 日志；永不抛错中断管线 | `agent_service.py` |

> 验收锚点「agent_order 缺省/非法时回退默认顺序（零迁移）」（#269）由**执行层回退**保证——API 层 422 是输入卫生，执行层回退是数据防御，两层并存。

### 2.4 决策论证

| 决策 | 方案 | 理由 |
|------|------|------|
| agent_order 元素格式 | 角色字段名（`agent_architect`，带前缀） | issue #269 方案原文；与 ProjectConfig 字段名一一对应，前端/CLI 零映射；执行层内部再转 stage.id |
| agent_order 默认值 | 空列表 = 模板默认序 | 零迁移（旧 config 无键自动空）；语义清晰（未配置 = 跟随模板） |
| 校验双层 | API 422 + 执行层回退 | 输入卫生与数据防御分离；执行层永不因配置损坏而中断写作（验收「非法回退默认」） |
| agent_* 具体模型存储格式 | provider/model（带前缀） | 与 ProviderConfig.default_model / parse_model_string 契约一致；执行层既有剥离逻辑直接复用（F26 §5.5） |
| __default__ 执行解析 | 不覆盖模板模型（等价「未指定」） | #225 语义「跟随默认」= 跟随模板角色模型/全局默认；修复现状 ValueError 缺陷（§5.1） |

---

## 3. API 契约

**无新增 REST 端点**。所有变更走既有 `PATCH /api/v1/projects/{id}`（`api/routers/project.py` L97-109）config 部分合并语义（`project_service.py` L139-143：`model_dump(exclude_unset=True)` + `existing.config.model_copy(update=config_updates)`）——agent_order 作为 ProjectConfig 新字段自动纳入，前端 PATCH 传 `{config: {agent_order: [...]}}` 即可。

| 变更 | 端点 | 说明 |
|------|------|------|
| PATCH config 扩展 | `PATCH /api/v1/projects/{id}` | body `config.agent_order`（list[str]）+ `config.agent_*`（三态值）按既有合并语义生效 |
| agent_order 非法 | 同端点 | 422，detail 中文（§2.3 API 层） |
| 模型存在性提示 | 无新端点 | **不校验存在性**（#268 方案 3：不存在允许保存）——前端标记（§5.2）；可选增强（不在本模块范围）：provider-configs 已提供 `GET /api/v1/provider-configs` chat 模型列表作为前端数据源 |

**异常映射表**：

| 场景 | 状态码 | detail |
|------|--------|--------|
| agent_order 含未知角色字段名 | 422 | 「agent_order 包含未知角色: xxx」 |
| agent_order 缺角色（口径按 Q1） | 422 | 「agent_order 必须包含全部启用角色: xxx」 |
| agent_* 为空字符串 | 422（既有） | 「Agent 模型不能为空字符串」（project.py L73-82 既有 validator） |
| agent_* 为未知模型 | **200 允许保存** | 前端标记「未注册模型」提示（§5.2） |

---

## 4. CLI 命令签名

**本模块不新增 CLI 命令**。agent_order 的 CLI 读写依赖 **#251 CLI project update 修复**（0.8.0 W2 P1）——#251 落地后 `inkflow project update --id N --config-json '{"agent_order": [...]}'`（或等效形态，以 #251 spec 为准）经既有 PATCH 合并语义天然支持 agent_order。

- 本模块对 CLI 的约束：① ProjectConfig 字段扩展**不得破坏** #251 的 config 合并语义（agent_order 是普通可选字段，exclude_unset 兼容）；② `inkflow project get --id N --json` 的 config 输出自动包含 agent_order（F7 全局 JSON 信封约定，无需改动）。
- **验收联动**：M5（CLI 读写）依赖 #251 合入；若 #251 未在 #269 前合入，CLI 验收降级为 API 层验证（curl PATCH/GET agent_order），并在 PR 说明标注（Q3 待拍板确认此归属）。

---

## 5. 关键差异节：Agent 链配置驱动编排

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
- **跟随默认的完整解析链**（不覆盖后回退路径）：模板 role.model（builtin 恒 `openai/gpt-4o`）→ 自定义 AgentTemplate role.model（`RoleTemplate.model`，可 None）→ `None` → `langchain_client.chat(model=None)` → `self._default_model`（全局默认 `config.llm_default_model`，`langchain_client.py` L73）——三层兜底与既有温度链同构（§merge_role_configs 注释）。
- **测试锚点**：`agent_* = "__default__"` 时执行不再抛 ValueError，且模型回退模板角色模型（mock LLM 断言 model 参数）。

### 5.2 前端模型选择 UI（#268）

**AgentChainCard.tsx MODIFY**（`frontend/packages/renderer/src/components/AgentChainCard.tsx`）：

- 每行 Switch 打开 → **条件渲染**模型 Select（替换/补充当前 tag 展示）；关闭 → 不渲染（保持现状 UI 简洁）。
- Select 数据源（Q2 拍板后定形态，建议 A）：**provider-configs chat 模型列表**——`GET /api/v1/provider-configs` → `items[].models[type=chat].id`，扁平为 `<provider>/<model>` 选项（provider 名取 `items[].name`）；数据加载走既有 `stores/models.ts`（ProviderConfig/ProviderModel 接口已存在，`models.test.ts` 已覆盖列表加载）。
- Select 选项结构（建议 A 形态）：
  1. 「跟随默认」= `AGENT_DEFAULT_SENTINEL`（Switch 打开默认选中）
  2. 每 provider 的 chat 模型：`<provider>/<model>`
- 三态交互映射（§2.2 表）：Switch off → PATCH `null`；on + 「跟随默认」→ `__default__`；on + 具体模型 → `<provider>/<model>`。
- **未注册模型标记**（#268 方案 3）：config 中既有值不在选项列表（如手工写入/模型已删）→ tag 显示「未注册模型」警告样式（沿用现有 tag 展示位，L70），**不阻塞保存**——即改即存链路（settings.tsx AgentPanel `persist()` L395-415：in-flight 守卫 + 失败 toast）不变。
- 默认模型 Select（AgentPanel L422-439）：**本期不动**（硬编码 3 项是 #268 验收范围外的既有行为；统一到 provider-configs 数据源如需纳入，标注待确认——避免范围膨胀）。

**store 扩展**：`stores/agent.ts` 无需新方法（setConfig/saveConfig 既有）；模型列表加载复用 `stores/models.ts`（若尚无暴露的 chat 模型扁平化 selector，实现时在 models store 内新增——文件落点见 §8）。

### 5.3 执行顺序配置驱动（#269）

**消费链**：`AgentService.execute`（`domain/services/agent_service.py` L67-118）→ `get_template("builtin:write_chapter")` → `_merge_role_configs`（模型/温度装配）→ `_run_pipeline` → `LangGraphAgentPipeline.execute`（`infrastructure/agent/langgraph_pipeline.py` L95-138）。

**执行顺序事实**（实证，决定实现方式）：LangGraphAgentPipeline.execute **按 DAG 边（output_to/input_from）构建 StateGraph**——执行顺序 = LangGraph 拓扑调度，**非 stages 列表顺序**（L120-126：entry=无 input_from 阶段；edges=output_to 边；terminal=无 output_to 阶段）。因此「固定序」的真相来源 = 模板 stages 的**链式边**（pipeline_templates.py L65-81 硬编码）。

**实现方案**：新增纯函数 `_apply_agent_order(stages, agent_order) -> list[PipelineStage]`（放 `agent_service.py` 或 `pipeline_templates.py`，实现确认）：

1. 输入：模板 stages（4 阶段链式）+ 项目 config.agent_order（角色字段名数组）
2. 空列表 → 原样返回（模板默认序，零迁移）
3. 语义校验（执行层防御）：非法（未知角色/缺角色——口径按 Q1）→ 记 warning + 原样返回（回退默认）
4. 重排：按 agent_order 映射出 stage.id 序列 → **重建链式边**——`stages[0].input_from=[]`、`stages[i].input_from=[prev_id]`、`stages[i-1].output_to=[cur_id]`、末位 `output_to=[]`（保持唯一入口/唯一终点，满足 `validate()` L57-62 约束）
5. 返回重排后的 stages，后续 `_merge_role_configs` / `_run_pipeline` 不变

- **装配位置**：在 `_merge_role_configs` **之后**（模型装配与拓扑无关，重排只改边不改 agent 属性）；实际落点 `AgentService.execute` L91-93 处——`stages = await self._merge_role_configs(...)` 后接 `stages = _apply_agent_order(stages, project.config.agent_order)`。
- **验证**：`LangGraphAgentPipeline.validate()` 对重排后 stages 恒通过（链式天然唯一入口/终点/无环）；集成测试用 mock LLM 记录角色调用顺序（§9）。
- **与模板关系**：agent_order 只重排 builtin:write_chapter 四角色链；自定义 AgentTemplate（`template_id` 引用）的 stages 拓扑**不受 agent_order 影响**（模板自带拓扑，agent_order 仅作用于内置四角色链）——边界声明，若用户期望模板也按 agent_order 重排，标注待确认（默认不支持，模板拓扑是模板作者意图）。

### 5.4 #270 DAG 扩展预留（0.9.0，本模块不实现）

| 演进约束 | 本模块保证 |
|----------|-----------|
| 顺序 = 拓扑基线 | agent_order 是**链式拓扑**的一维投影；#270 agent_relations 是**通用 DAG 边**的增强语义——执行链设计以「重建边」为唯一操作，不引入顺序专属数据结构（如不新增「position 字段」硬编码在 stage 上，避免与 DAG 边冲突） |
| PipelineStage 已具备 DAG 能力 | input_from/output_to + Kahn 环检测（langgraph_pipeline.py L72-93）既有——#270 只需在 `_apply_agent_order` 同级新增 `_apply_agent_relations(stages, relations)`（或扩展同一函数），引擎零改动 |
| 配置模型兼容 | agent_order（list[str]）+ agent_relations（0.9.0 新增 dict/list）并存：agent_order 存在时链式重排；agent_relations 存在时**覆盖** agent_order 语义（关系优先，spec 届时定义冲突规则）——本模块在 §12 决策记录与 §10 边界声明留痕 |
| 启用角色子集（Q1=B 时） | 跳过逻辑不得破坏 DAG 拓扑（跳过 = 边重连而非节点删除，保持唯一入口/终点）——预留约束写入 §12 |

### 5.5 deepagents 兼容性结论（实证，非待拍板）

- agent_order **仅消费方 = LangGraphAgentPipeline**（四角色链管线）——`POST /api/v1/agent/.../execute`（`api/routers/agent.py` L29-30 装配）。
- F27 agentic 路径（`AgenticWriterService` + `build_agentic_writer`）：deepagents **单 agent**（writer_agent）ReAct 循环 + 5 只读 + save_draft 工具，`model=config.llm_default_model`——**无多角色编排概念，不消费 agent_order/agent_***（`api/deps.py` L220-240 实证）。
- F29 Supervisor（#161，0.8.0 W5）：deepagents subagent 机制分层编排，与 agent_order 管线编排**不同抽象层**——#269 的「注意 deepagents harness 兼容」结论：**无冲突**，agent_order 不触碰 deepagents 装配；F29 spec 需单独定义 supervisor 与管线的衔接（同编排域串行：必须 #269 合入后 #161 再开，roadmap 风险表已声明）。
- 模型名剥离：agent_* 具体模型值（provider/model 格式）在 LLM 调用链既有剥离逻辑（F26 §5.5 `parse_model_string` 复用）——本模块不新增剥离代码。

---

## 6. 组织规则

- ProjectConfig 扩展遵循既有 Pydantic 模型约定（domain 层零框架依赖）；`AGENT_DEFAULT_SENTINEL` 保持 `domain/models/project.py` 定义（唯一真相源），前端 `stores/project.ts` L18 镜像常量（既有双份模式，注释互指）。
- `_apply_agent_order` 归属 domain 服务层（纯函数，不依赖 infrastructure）——放在 `agent_service.py` 模块级函数（非类方法），便于独立单测。
- 前端模型选择数据源走既有 `stores/models.ts`（ProviderConfig/ProviderModel 接口已有）——不新建 provider store；AgentChainCard 保持「展示组件 + 回调」模式（onConfigChange 即改即存，`settings.tsx` persist 链路不变）。
- 执行层 `__default__` 解析在 `_merge_role_configs`（唯一模型装配点）——不在节点层（pipeline_nodes.py）做 sentinel 判断，保持节点纯净（节点只消费装配后的 AgentRole）。

---

## 7. 边界情况与错误处理

| 场景 | 行为 | 错误面 |
|------|------|--------|
| agent_* = `__default__`（现状缺陷路径） | **修复后**：不覆盖模板模型，正常执行（§5.1） | 无（修复点；执行日志可查模型回退） |
| agent_* = 未知模型名（如 `foo/bar`） | 允许保存（#268 方案 3）；前端「未注册模型」标记；执行时 provider 配置不存在 → LLM 调用失败走既有重试/失败语义 | 执行失败（既有 PipelineError 路径，非本模块新增） |
| agent_* = 空字符串 | 422（既有 validator L79-81） | 输入拒绝 |
| agent_order 缺省/空列表 | 模板默认顺序执行（零迁移） | 无 |
| agent_order 含未知角色名 | API 422；执行层回退默认 + warning 日志 | 输入拒绝 / 防御回退 |
| agent_order 缺角色（口径按 Q1） | API 422；执行层回退默认 | 输入拒绝 / 防御回退 |
| agent_order 重复元素 | 存储层静默去重保留首个位置 | 无（规范化） |
| 自定义 AgentTemplate 项目 | agent_order 不生效（模板自带拓扑，§5.3 边界） | 无（文档化行为） |
| 存量项目（无 agent_order 键） | Pydantic 默认空列表 → 模板默认序 | 无（零迁移） |
| GUI 重启 | config 持久化（PATCH 落库）→ 读回三态/顺序保持 | 无（#268/#269 验收项） |
| 模型在 provider 注册表被删 | 前端标记「未注册模型」；保存仍允许 | 提示不阻塞 |

---

## 8. 文件结构

> 对照真实源码树（2026-08-12 实证）。文件路径以主仓根为基准。

### 后端

| 动作 | 文件 | 说明 |
|------|------|------|
| MODIFY | `backend/src/inkflow/domain/models/project.py` | ProjectConfig 新增 `agent_order: list[str]` + validator（§2.1） |
| MODIFY | `backend/src/inkflow/domain/services/agent_service.py` | ① `_merge_role_configs` L232-234 sentinel 解析修复（§5.1）；② 新增模块级 `_apply_agent_order` 纯函数（§5.3）；③ `execute` L91-93 装配点调用 |
| MODIFY | `backend/src/inkflow/api/routers/project.py`（或 `domain/services/project_service.py`，实现确认） | agent_order API 层语义校验 → 422（§2.3） |
| MODIFY | `backend/tests/unit/test_agent_service.py`（既有文件，追加） | ① sentinel 不覆盖断言（mock LLM 收 model 参数）；② `_apply_agent_order` 重排/回退/空列表契约 |
| CREATE | `backend/tests/unit/test_project_config_order.py`（若 test_agent_service 过厚则独立） | ProjectConfig.agent_order 存储层校验（类型/去重/非法元素） |
| MODIFY | `tests/cli/test_cli_project*.py`（既有，追加） | PATCH config.agent_order 经 CLI 读写契约（依赖 #251；未合入则降级 API 层测试，§4） |

### 前端

| 动作 | 文件 | 说明 |
|------|------|------|
| MODIFY | `frontend/packages/renderer/src/components/AgentChainCard.tsx` | 三态模型 Select 条件渲染 + 「未注册模型」标记（§5.2） |
| MODIFY | `frontend/packages/renderer/src/stores/models.ts` | （如需）chat 模型扁平化 selector（provider/model 选项列表） |
| MODIFY | `frontend/packages/renderer/src/stores/project.ts` | ProjectConfig 接口新增 `agent_order?: string[]`（类型注释同步 §2.2 三态表） |
| CREATE | `frontend/packages/renderer/src/components/AgentChainCard.test.tsx` | **新建**（现状无此测试文件，2026-08-12 实证）：三态交互（off→null / on→sentinel / 选模型→模型名）+ 未注册模型标记 + 模型 Select 数据源 mock |
| MODIFY | `frontend/packages/renderer/src/pages/settings.test.tsx`（既有） | AgentPanel 交互回归（默认模型 Select 不动，仅防回归） |

> 后端 API 校验落点（router 层 vs service 层）标注「实现确认」：router 层贴近 422 语义（既有 `_run_service` 异常映射模式），service 层贴近复用；两者皆可，实现时按测试可 mock 性选择。

---

## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 模型/契约（后端） | ProjectConfig.agent_order 默认空/去重/非法元素拒绝；agent_* 三态 validator 回归 | ≥90% |
| 服务（后端） | `_merge_role_configs` sentinel 不覆盖（mock LLM 断言 model=模板模型）；`_apply_agent_order` 4 种排列重排 + 空回退 + 非法回退 + 唯一入口/终点不变量 | ≥90% |
| 集成（后端） | LangGraphAgentPipeline 重排后 stages validate() 通过；mock LLM 记录角色调用顺序 = agent_order | ≥90% |
| 前端组件 | AgentChainCard 三态交互（Switch 开→Select 出现；选「跟随默认」→ sentinel；选模型→模型名；off→null）；未注册模型标记；Select 选项 = provider-configs chat 模型 mock | ≥90% |
| E2E（如扩） | 设置页 Agent 分类：开角色→选模型→PATCH 落库→重启保持（#268 验收）；调顺序→PATCH→重启保持（#269 验收）——落点 `tests/e2e/e2e-settings.spec.ts` 追加 | 手工/E2E |
| 回归 | 既有全仓测试零回归（默认模型 Select 硬编码不动；agentic 路径不动） | 全仓 ≥60%（ADR-027 门禁） |

**RED 形态**：后端 `_apply_agent_order` 不存在 → ImportError；sentinel 修复 → 断言 `llm.chat(model)` 参数 ≠ `__default__` 失败；前端 Select 缺失 → RTL 查询失败。

**测试无网络约束**：模型列表数据源一律 mock `apiFetch`（既有 `stores/models.test.ts` 模式）；管线执行 mock LLMClientProtocol（既有 test_agent_service 模式）。

---

## 10. 不在范围内

| 项 | 归属 |
|----|------|
| #270 关联关系编辑（agent_relations 语义/UI） | 0.9.0（本模块仅预留演进约束，§5.4） |
| F29 Supervisor 自主编排 + HITL + subagent | #161（0.8.0 W5，🔗#269 合入后） |
| F27 agentic 路径多角色化 / 按 agent_order 编排 | 不规划（F27 为单 agent 闭环；如需「顺序多 agent」属新产品决策，另行拍板） |
| 拖拽排序 UI | 本期上移/下移按钮（#269 方案「先上下移——拖拽后续可加」）；拖拽标注 0.9.0 候选 |
| 模型存在性强制校验（不存在拒绝保存） | #268 方案 3 明确「不存在允许保存但标记」——强制校验不规划 |
| 默认模型 Select 数据源统一（settings.tsx L422-439 硬编码） | 标注待确认；本期不动（防范围膨胀），如用户期望统一纳入 provider-configs 数据源则追加 |
| AgentTemplate 自定义拓扑按 agent_order 重排 | 不规划（模板拓扑 = 模板作者意图，§5.3 边界） |
| agent_order 与 F29 supervisor 编排衔接 | #161 spec 定义 |
| 全局默认模型选项进 agent_order | 无此语义（agent_order 是角色顺序，非模型） |

---

## 11. 依赖关系

- **依赖**：#225 三态语义（✅ 0.7.0 已合入，本项目扩展执行层解析）、F26 deepagents 集成（✅ PR #236，模型名剥离复用）、F27 agentic writer（✅，兼容性边界 §5.5）、#251 CLI project update（⏳ 0.8.0 W2 P1——agent_order CLI 读写联动，§4）、F9/F13/F34 服务（✅，工具包装对象无关本项目）。
- **被依赖**：#269 🔗 #268（模型选择先于顺序编辑——roadmap 轨道 B 串行）；#161 F29 🔗 #269 合入后（同编排域串行，roadmap 风险表）；#270 🔗 #269（DAG 演进基线，§5.4）。
- 编号口径声明：F39/F40/F41 已分配给 0.9.0 多 Agent（#258/#259/#260），本模块 F42 编号依据 roadmap 拍板记录 9（2026-08-12）。
- deepagents 兼容性（Q3 确认边界）：agent_order 消费方仅 LangGraphAgentPipeline；deepagents 装配零改动（§5.5）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 备选（否决理由） |
|------|------|-----------------|
| #268+#269 合并一份 spec | **F42 单 spec 覆盖两 issue（roadmap 拍板记录 8/9）** | 两 spec 分开（两期配置面同一组件/同一文件域，分开会产生双份真相；用户拍板「正式 spec 合并一份」） |
| 执行顺序实现方式 | **重建链式边（`_apply_agent_order` 纯函数）** | ① 改 stages 列表顺序（无效——LangGraph 按 DAG 边调度，列表序不影响执行序，实证 L120-126）；② 节点层条件跳转（破坏引擎纯净性，且顺序逻辑散落） |
| 顺序配置存储 | `agent_order: list[str]` 角色字段名（ProjectConfig 顶层字段） | extra 字典（类型安全弱、无 validator、CLI 语义差）；position 字段硬编码在 stage（与 DAG 边冲突，堵死 #270） |
| 校验双层 | API 422 + 执行层回退 | 仅 API 校验（存量损坏数据会中断写作）；仅执行层回退（非法输入无即时反馈） |
| `__default__` 执行解析 | sentinel 不覆盖模板模型（`_merge_role_configs` 修复） | 保持现状（执行 ValueError 缺陷）；节点层判断（散落 + 节点不纯净） |
| 模型选择数据源 | provider-configs chat 模型列表（Q2 建议 A，待拍板） | 硬编码（用户自定义 provider 无法选）；ModelsPanel 六槽位先行（#106 是 provider 管理域，范围膨胀） |
| CLI 归属 | #251 联动（Q3 建议 A，待拍板） | F42 内补 CLI（与 #251 同命令面双改冲突） |
| #270 预留 | 顺序=链式基线、关系=增强语义；配置双字段并存关系优先 | 本模块实现 DAG（范围膨胀）；设计不预留（演进被堵死） |

---

## 13. 验收标准

> 合并 #268 + #269 issue 验收要点；M1-M3 为 #268（W2），M4-M6 为 #269（W3），M7 收尾。实现 PR 按里程碑分批合入。

- **M1 三态执行修复（#268 后端）**: `pytest backend/tests/unit/test_agent_service.py` — `agent_* = "__default__"` 执行不抛 ValueError 且 mock LLM 收到模板角色模型（非 sentinel）；`agent_* = null` 行为保持
- **M2 模型选择 UI（#268 前端）**: `pnpm vitest run src/components/AgentChainCard.test.tsx`（新建）— 开关打开条件渲染 Select（数据源 mock provider-configs chat 模型）；选「跟随默认」→ PATCH sentinel；选具体模型 → PATCH provider/model；关闭 → PATCH null；未注册模型值显示标记且保存不阻塞
- **M3 模型选择持久化 + 写作验证（#268 验收闭环，手工）**: GUI 打开角色→选模型→保存→重启保持；写作流程（write next / agentic）按指定模型执行（内核 stderr 可查模型名）；关闭 → config.agent_* = null
- **M4 agent_order 配置 + 校验（#269 后端）**: `pytest backend/tests/unit/test_project_config_order.py` + API 测试 — ProjectConfig.agent_order 默认空/去重/非法拒绝；PATCH 语义校验 422；存量项目零迁移（无键 → 模板默认序）
- **M5 执行顺序重排（#269 集成）**: mock LLM 角色调用顺序 = agent_order（Architect→Writer→Auditor→Reviser 的 4 种排列全验证）；非法/缺省回退默认顺序 + warning 日志；重排后 validate() 恒通过
- **M6 顺序编辑 UI + 持久化（#269 验收闭环）**: GUI 每行上移/下移 → PATCH agent_order → 重启保持；写作流程按新顺序执行（内核 stderr / 执行日志可验证调用顺序）
- **M7 CLI 读写 + 回归（#269 CLI + 全仓）**: 依赖 #251 合入后 `inkflow project get --id N` 输出含 agent_order、update 可写（#251 未合入则降级 API 层验证，PR 标注）；全仓测试零回归 + 覆盖率门禁（ADR-027）；spec §8 文件结构逐项核对

---

## 待澄清问题

- **Q1（阻塞级）：`null`=「关闭」角色的执行语义**（决定 §2.3 校验口径 + §5.3 重排逻辑）
  - **背景实证**：三态语义 null=关闭 / __default__=跟随默认（#225 已合入）；但执行层 `_merge_role_configs` **无跳过逻辑**——null 角色照常参与管线（用模板/默认模型执行），「关闭」与「跟随默认」执行层等价，仅 UI 文案区分（AgentChainCard tag「已禁用」vs「默认模型」）
  - A. **保持现状**：null 仅表示「不指定项目模型」，角色照常执行——agent_order 校验口径 = 必须含全部 4 角色；UI 文案对齐（「关闭」改「默认模型」或 tooltip 说明）；改动最小、零行为变化
  - B. **真禁用**：null → 管线跳过该角色（边重连，§5.4 预留约束）——agent_order 校验口径 = 必须含全部**启用**角色；「关闭」角色不再产出中间产物（如关 Writer → Auditor 输入为 Architect 输出，需定义透传语义）；改动大（执行链 + 校验 + 中间产物语义 + E2E 面）
  - 建议：A（现状实现零改动；真禁用是新产品行为，涉及中间产物语义设计，建议独立拍板/后续版本；但 UI 文案「禁用」需同步修正避免误导）
  - 估算影响：A 不增估算；B +2-3 人天

- **Q2（设计决策级）：模型选择数据源形态**（#268 §5.2）
  - A. **复用 `GET /api/v1/provider-configs` chat 模型列表**（provider 名 + models[type=chat] 扁平为 provider/model 选项）——数据源已存在、格式与 agent_* 存储一致、models store 接口已有；「跟随默认」选项固定置顶
  - B. #106 ModelsPanel 六槽位绑定 UI 先行落地后复用其选择器——ModelsPanel 是 provider 管理域（#276 也涉及 settings 域），范围膨胀且跨 issue 耦合
  - C. 硬编码模型名（现状默认模型 Select 做法）——用户自定义 provider 无法选择，不可接受
  - 建议：A（唯一自洽选项；B 视为 #106/#276 独立工作，本模块不依赖）

- **Q3（设计决策级）：agent_order CLI 读写归属 + deepagents 兼容边界确认**（§4 / §5.5）
  - CLI：A. **挂 #251 联动**（#251 project update 修复后经 PATCH 合并语义天然支持 agent_order；本模块仅保证字段扩展不破坏 exclude_unset；#251 未合入时 CLI 验收降级 API 层）／B. F42 内补 CLI project update（与 #251 同命令面双改，冲突风险）——建议 A
  - deepagents 兼容边界：A. **认可实证结论**（agent_order 仅驱动 LangGraphAgentPipeline；F27 agentic 单 agent 不消费；F29 衔接由 #161 spec 定义——§5.5 已写入正文）／B. 期望 agentic 路径也按 agent_order 多 agent 化（超本模块范围，需新拍板）——建议 A

> 已确认事实（非待澄清，实证留痕）：`__default__` 执行层 ValueError 缺陷必须修（§5.1）；执行顺序真相 = DAG 边非列表序（§5.3）；执行层无角色跳过逻辑（Q1 背景）；agentic 路径读全局默认模型（§5.5）。
