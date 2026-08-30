# F46: Agent 关联关系编辑——DAG 编排（dag-orchestration）功能规格
> **端**: cross

**Spec 版本**: 1.1（Q1-Q3 拍板 A：三类型全做 / 确定性 gate / 列表式编辑器，2026-08-16）
**日期**: 2026-08-16
**依据**: Issue #270（Agent 关联关系编辑——DAG 编排，编排完全体第 3 步）+ 2026-08-12 用户拍板「Agent 链编排完全体规划：#268 模型选择 → #269 执行顺序 → #270 关联关系（本模块，最终步）」+ F42 spec v1.3（§5.4 DAG 预留 + §5.3 层级拓扑 + §5.5 deepagents 兼容）+ F29 spec v1.0（supervisor 动态路由边界）+ Spike 验证报告 `docs/f46-dag-spike-2026-08-16.md`（M1 结论：自研 LangGraph 编排层 + `add_conditional_edges` 条件分支）
**所属阶段**: 0.9.0（多 Agent 能力里程碑，轨道 A Agent 编排：F42/#268/#269 ✅ → #161 F29 ✅ → **#270 F46**），估算 8-12 人天
**关联 Issues**: #270（本模块，唯一真相来源）
**依赖**: ✅ #269 agent_order 层级拓扑（PR #305，F42 §5.3.1 通用节点 + 多入口/终点引擎）· ✅ F42 配置驱动编排（已实现，#299/#305/#308/#309/#315/#314）· ✅ F29 supervisor 动态路由（PR #323，边界 §5.5）· ✅ F26 deepagents 集成层（PR #236）· ✅ F42 #295 自定义 Agent 数据面（RoleTemplate prompt/name + agent_roles 三态字段，agent_relations 引用面复用）· LangGraph 1.2.10（venv 已锁）
**参考 ADR**: [adr/ADR-035.md](../adr/ADR-035.md)（编排引擎=Deep Agents harness 0.7.5，原 ADR-E）、ADR-006v2（Agent 编排 LangGraph StateGraph）、ADR-015（LangChain 隔离）、ADR-019（编号口径）
**状态**: ✅ 已实现（PR #412，2026-08-16）

> **Spec 变更**（v1.0 → v1.1，2026-08-16，待澄清 Q1-Q3 拍板）：用户拍板「按照建议」——Q1=A 三类型全做（sequential + data + conditional）、Q2=A 确定性 gate（关键词匹配「通过/PASS」）、Q3=A 列表式编辑器 + 只读 DAG 预览。正文 §1.2.1/§2.1/§5.2/§5.3.2/§5.3.3 已按 A 方案起草（v1.0 即按建议默认落笔），本次修订仅留痕拍板结果（待澄清区标 ✅ 已确认），正文无实质改动。

> **模块类型声明**: 本模块为「**配置驱动编排型（DAG 增强）**」变体——无新实体表、无新业务端点；在既有 Agent 管线（LangGraphAgentPipeline 分层全连接 DAG）上增加**角色间显式有向边**（`agent_relations`）能力：① 依赖类型语义（顺序依赖 / 数据传递 / 条件分支，产品设计 §1.2）；② 执行拓扑从「分层全连接」升级为「基线 + 显式边叠加」（§5.3）；③ 条件分支经 `add_conditional_edges` gate 语义落地（Spike ②）；④ 前端 DAG 可视化编辑器（§5.2）。编号依据：F46 为 Agent 化升级链（F26-F29）+ 配置面（F42）之后的 DAG 编排模块；按「最新无冲突基线」接续——F29=第 13 变体、F38=第 18 变体为当前最新无冲突基线，本模块声明**第 19 变体**（冲突以 ADR-019 v5+ 为准）。

---

## 1. 概述

F46 实现 **#270（Agent 关联关系编辑——DAG 编排）**，是「Agent 链编排完全体」的最终步（#268 模型选择 → #269 执行顺序 → #270 关联关系）。在 F42 已交付的**分层全连接 DAG**（`agent_order` 层级拓扑）之上，新增**角色间显式关联关系**（`agent_relations`），把「线性/分层流水线」升级为「可显式定义依赖/数据流/条件分支的 DAG」。

### 1.1 现状缺口（2026-08-16 源码实证）

| # | 缺口 | 实证 | 归属 |
|---|------|------|------|
| ① | **拓扑只有「分层全连接」一种形态**：`agent_order` 层级嵌套 → `_apply_agent_order` 重建「层间全连接 + 层内并行」边，用户无法表达「同层打破并行」「非全连接的精确依赖」 | `agent_service.py` `_apply_agent_order` L136-158（全连接边重建） | #270 |
| ② | **无条件分支语义**：管线按静态 DAG 边执行，无「角色输出决定下游是否执行」的 gate 能力 | `langgraph_pipeline.py` L114-116（仅静态 `add_edge`，无 `add_conditional_edges`） | #270 |
| ③ | **无 `agent_relations` 配置字段**；数据传递依赖「全量注入」（前序全层输出注入后序全层）的隐式约定，用户无法精确声明「A 输出喂 B」或「B 等 A 但不读 A 输出」 | `domain/models/project.py` ProjectConfig（仅 agent_order，无 agent_relations）；`pipeline_nodes.py` `_build_messages` L62-88（注入键集 = input_from ∪ 占位符扫描） | #270 |
| ④ | **前端无依赖关系编辑 UI**：AgentChainCard 只有开关 + 模型 Select + 槽位号，无「角色间关系」编辑入口 | `frontend/packages/renderer/src/components/AgentChainCard.tsx`（F42 交付） | #270 |
| ⑤ | **执行轨迹无 DAG 关系信息**：执行记录/日志只记录 stages 列表，不记录「哪些边是条件边、gate 判定结果」 | `execution_store.py`（F29 交付） | #270 |

### 1.2 产品设计（#270 先决，定稿）

#### 1.2.1 依赖类型语义

角色间有向边 `{from, to, type}` 三类型，语义正交：

| 类型 | 语义 | 用户心智 | 与现状关系 |
|------|------|---------|-----------|
| `sequential`（顺序依赖） | **纯时序**：`to` 在 `from` 完成后才执行；`to` **不**读 `from` 输出 | 「Reviser 在 Auditor 之后执行，但只改自己的稿子」 | 跨层=基线已有时序（强化）；**同层=打破并行**（新增时序边） |
| `data`（数据传递） | **数据流**：`to` 读 `from` 输出（`{from_output}` 注入 prompt）；隐含时序 | 「Auditor 依赖 Writer 输出」 | 跨层=基线已注入（精确声明）；**同层=打破并行 + 注入**（新增） |
| `conditional`（条件分支） | **条件时序**：`to` 仅在 `from` 的 gate 判定通过后执行；不通过则 `to`（及其下游）跳过 | 「Reviser 在 Auditor 通过后才执行」 | 本期唯一真正新引擎能力（条件边，Spike ②） |

- **三类型正交性**：`sequential` 只控时序、不控数据；`data` 控数据（隐含时序）；`conditional` 控「条件时序」（gate 通过才执行）。三者引擎映射正交（§5.3.2）。
- **数据传递与全量注入的关系**（关键设计）：基线全连接（F42 `_apply_agent_order`）保持「全量注入」不变（零迁移、零破坏）；`data` 边在**同层**场景新增「打破并行 + 注入」，跨层场景为「精确声明」（语义文档化，为未来「非全连接精确数据流」铺路，归远期 §10）。

#### 1.2.2 可视化表达（DAG 图）

- **节点 = Agent 角色**（内置 4 + 自定义角色，即 `agent_order`/`agent_roles` 定义的角色集合）。
- **边 = 关系**（`agent_relations` 每条边），边样式区分类型：
  - `sequential`：实线箭头（纯时序）。
  - `data`：实线箭头 + 数据标记（如空心圆点/「数据」标签）。
  - `conditional`：菱形起点或虚线箭头 + 条件标记（gate 语义）。
- **层次底色**：`agent_order` 层序作为**纵向分层背景**（同层角色水平并排、层间纵向排布），显式边叠加其上——顺序为拓扑基线、关系为增强语义的直观表达。
- **编辑形态**（Q3）：本期为「列表式关系编辑 + 只读 DAG 预览」——角色列表每行「依赖选择器」（选上游角色 + 边类型）+ 独立「关系列表」增删改；DAG 图以只读 SVG/mermaid 预览渲染（不拖拽连线）。画布式拖拽编辑归远期。

#### 1.2.3 与 agent_order 关系（顺序为拓扑基线、关系为增强）

| 维度 | `agent_order`（基线，F42 已实现） | `agent_relations`（增强，本模块） |
|------|-----------------------------------|-----------------------------------|
| 表达 | 层级嵌套 `list[list[str]]`：层序 + 层内并行 | 显式边 `list[{from,to,type}]`：角色对间依赖 |
| 语义 | 拓扑基线（层间全序、层内并行、全连接注入） | 增强语义（显式依赖/数据流/条件分支） |
| 关系 | 基线 | 叠加（**关系优先**：显式边覆盖基线边，§5.3.1） |
| 空态 | 空 = 默认模板模式（线性链） | 空 = 纯基线（现状零迁移） |

- **拓扑合成规则（定稿）**：`agent_relations` 非空时，在 `_apply_agent_order` 基线 DAG 上**逐边叠加**（§5.3.1）。跨层边=强化基线；同层边=打破并行（新增时序边）；条件边=条件路由覆盖。
- **线性模式兼容**（验收硬约束）：`agent_order` 空 + `agent_relations` 空 = 默认模板线性链；`agent_relations` 空 = 现状分层全连接（零行为变化）。

### 1.3 边界声明

- **不含** deepagents harness 改造：F46 编排层 = 自研 LangGraph StateGraph（Spike ① 定稿）；deepagents 0.7.5 保持 F27 单 agent 闭环独立（F42 §5.5 兼容结论不变）。**不新增 deepagents 依赖**。
- **不含** F29 supervisor 动态路由改造：F46 是**静态显式 DAG**（边由用户配置），F29 是**动态路由**（边由 LLM 决策）——两者经 `PipelineExecuteRequest.mode`（static/supervisor）分派，正交共存（§5.5）。F46 的 `agent_relations` 仅作用于 static 模式；supervisor 模式不消费 `agent_relations`（动态路由取代静态边）。
- **不含** 非全连接的「精确数据流」（移除基线全量注入）：本期保持基线全连接 + 全量注入不变，`data` 边为「精确声明 + 同层打破并行」；「显式边完全取代全连接」的精确 DAG 归远期（§10）。
- **条件分支范围收敛**：本期 conditional 边语义 = **gate 门控**（from 通过 → to 执行；不通过 → to 及其下游跳过，§5.3.3）；多条件分叉（一条 from 边多条 conditional 出边）、条件表达式 DSL、独立 LLM gate 判定均归远期（§10）。
- **不含** 执行轨迹的可视化渲染 UI（DAG 执行轨迹图）：本期执行记录增加关系/判定元数据（§5.4 数据面），GUI 轨迹图归远期。

## 2. 数据模型

### 2.1 `AgentRelation` 实体（`domain/models/project.py` CREATE，同文件内联）

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

class AgentRelation(BaseModel):
    """角色间有向边（#270，spec §1.2.1 依赖类型语义）。"""

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from", description="源角色字段名（带 agent_ 前缀，如 agent_auditor）")
    to: str = Field(description="目标角色字段名（带 agent_ 前缀，如 agent_reviser）")
    type: Literal["sequential", "data", "conditional"] = Field(
        default="sequential", description="依赖类型：sequential=顺序依赖 / data=数据传递 / conditional=条件分支"
    )

    @field_validator("from_", "to")
    @classmethod
    def _validate_role_ref(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("agent_relations 的 from/to 不能为空")
        return stripped

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in ("sequential", "data", "conditional"):
            raise ValueError(f"agent_relations 类型非法: {v}（应为 sequential/data/conditional）")
        return v
```

- **字段命名口径**：`from`/`to` 存**角色字段名**（带 `agent_` 前缀，与 `agent_order` 口径一致，F42 §2.1）；Python 侧 `from` 是关键字 → 字段名 `from_` + `Field(alias="from")`，`populate_by_name=True` 保证 `model_dump(by_alias=True)` 序列化为 `{"from", "to", "type"}`（与 issue #270 方案一致）。
- **执行层转换**：`from_`/`to` 去 `agent_` 前缀 → stage.id（如 `agent_auditor` → `auditor`），复用 F42 `_apply_agent_order` 的 `removeprefix("agent_")` 模式。

### 2.2 `ProjectConfig.agent_relations` 扩展（`domain/models/project.py` MODIFY）

```python
class ProjectConfig(BaseModel):
    # ...既有字段不变（model/agent_*/agent_roles/temperature/role_*_temperature/
    #    template_id/writing_style/default_words/extra/agent_order）

    agent_relations: list[AgentRelation] = Field(default_factory=list)
    """角色间显式关联关系（#270，spec §1.2）。

    - 空列表 = 未配置 → 纯 agent_order 基线（现状零迁移，§1.2.3 线性兼容）
    - 非空 = 在基线 DAG 上叠加显式边（关系优先，§5.3.1）
    - 示例: [{"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"}]
            = reviser 在 auditor 通过后才执行
    """

    @field_validator("agent_relations", mode="before")
    @classmethod
    def validate_agent_relations(cls, v: Any) -> list[AgentRelation]:
        """存储层校验（spec §2.3）：结构 + 自环 + 重复边 + 类型（类型/非空在 AgentRelation 内校验）。

        - 非 list → ValueError；元素非 dict/AgentRelation → ValueError
        - 自环（from == to）→ ValueError
        - 重复边（相同 (from, to)）→ ValueError（不同 type 的重复声明歧义，拒绝）
        """
        if not isinstance(v, list):
            raise ValueError("agent_relations 必须为数组")
        relations: list[AgentRelation] = []
        seen: set[tuple[str, str]] = set()
        for item in v:
            rel = item if isinstance(item, AgentRelation) else AgentRelation.model_validate(item)
            key = (rel.from_, rel.to)
            if rel.from_ == rel.to:
                raise ValueError(f"agent_relations 自环非法: {rel.from_}")
            if key in seen:
                raise ValueError(f"agent_relations 重复边: {rel.from_} -> {rel.to}")
            seen.add(key)
            relations.append(rel)
        return relations
```

- **默认值**：`default_factory=list`（空 = 纯基线）——**零迁移**：旧项目 config JSON 无此键 → Pydantic 默认空列表。
- **与 `agent_order` 并存**：两字段独立（F42 §5.4 演进约束落实）；`agent_order` 定义层基线，`agent_relations` 定义显式边叠加，冲突规则「关系优先」（§5.3.1）。

### 2.3 `agent_relations` 校验（三层 + 死角色引用 / 环检测口径）

| 层 | 行为 | 位置 |
|----|------|------|
| 存储层（Pydantic） | 结构 + 自环 + 重复边 + 类型 + 非空（§2.1/§2.2） | `domain/models/project.py` |
| API 层（PATCH） | 语义校验 → **422**（detail 中文）：① **死角色引用**——from/to 去 `agent_` 前缀后必须 ∈ 已知角色集合（内置 4 + `agent_roles` 自定义角色）；引用**未知**角色 → 422；引用「存在但未启用」角色（agent_* = null）→ 允许保存 + 执行层忽略 + warning（§7）；② **agent_relations 自身环检测**（Kahn，§5.3.4 复用）——关系边自身有环 → 422；③ **conditional 边约束**——conditional 边 `A→B` 要求 B 是 A 的**唯一后继**（A 除 B 外无其它出边，含基线全连接出边；多后继需条件 fan-out，归远期 §10）→ 违反 422 | `api/routers/project.py`（或 `project_service.py`，实现确认，同 F42 §2.3 落点） |
| 执行层（防御） | **合成后环检测**（agent_relations 边 + agent_order 基线合成图）+ 任何非法（含存量手工损坏数据）→ **忽略 agent_relations，回退纯基线** + warning 日志；永不抛错中断管线 | `agent_service.py` `_apply_agent_relations`（§5.3） |

- **死角色引用口径**：`agent_relations` 引用**未知角色**（非内置 4 非 `agent_roles`）→ 422「agent_relations 引用了不存在的角色: xxx」；引用「**存在但未启用**」角色（agent_* = null）→ **允许保存**（前端提示「该角色未启用」）+ 执行层该边不生效（角色未参与执行）+ warning（§7）——区分「死引用」与「未启用引用」，后者不阻塞保存（用户可先配关系后启用角色）。
- **环检测双层**：API 层只检测 `agent_relations` 边**自身**无环（提前拦截常见错误）；执行层检测「合成后完整图」无环（`agent_relations` 的逆序边可能与 `agent_order` 层序冲突产生环，§5.3.1 步骤 4）——两层并存（输入卫生 + 数据防御，F42 §2.3 同款双层模式）。

### 2.4 决策论证

| 决策 | 方案 | 理由 |
|------|------|------|
| 数据模型 | `AgentRelation`（from/to/type 三字段 + Literal type） | issue #270 方案 `list[{from, to, type}]` 直译；类型安全（Literal 而非裸 str）；与 `agent_order` 同文件同口径 |
| from/to 存角色字段名（agent_ 前缀） | 与 `agent_order` 口径一致 | 复用 `removeprefix("agent_")` 转换；用户心智统一（「角色字段名」单一口径） |
| type 三值 | `sequential`/`data`/`conditional` | issue 产品设计三类型正交（§1.2.1）；Literal 编译期约束 + 运行时校验 |
| 默认 type | `sequential` | 顺序依赖是「至少支持」的底线（issue 验收）；显式声明时最常用语义 |
| 默认值空列表 | 零迁移（旧 config 无键 → 空 → 纯基线） | F42 `agent_order` 同款零迁移模式 |
| 环检测双层 | API 422（自身环）+ 执行层回退（合成环） | 输入卫生与数据防御分离（F42 同款）；合成环只能在执行层检测（依赖运行时启用集合） |
| conditional 唯一后继约束 | B 是 A 的唯一后继 | LangGraph `add_conditional_edges` 单值路由 + f29 spike ②「条件边/静态边互斥」教训；多后继条件 fan-out 归远期 |
| 同层显式边 | 允许（打破并行，§5.3.1） | 「同层打破并行」是 sequential/data 边在基线全连接下的**真实增量价值**（否则跨层边全部被基线覆盖，功能空转） |

---

## 3. API 契约

**无新增 REST 端点**。所有变更走既有 `PATCH /api/v1/projects/{id}`（`api/routers/project.py` L97-109）config 部分合并语义（`project_service.py`：`model_dump(exclude_unset=True)` + `existing.config.model_copy(update=config_updates)`）——`agent_relations` 作为 ProjectConfig 新字段自动纳入，前端 PATCH 传 `{config: {agent_relations: [...]}}` 即可。

| 变更 | 端点 | 说明 |
|------|------|------|
| PATCH config 扩展 | `PATCH /api/v1/projects/{id}` | body `config.agent_relations`（`list[{from,to,type}]`）按既有合并语义生效 |
| agent_relations 非法 | 同端点 | 422，detail 中文（§2.3 API 层） |

**异常映射表**：

| 场景 | 状态码 | detail |
|------|--------|--------|
| agent_relations 非数组 | 422 | 「agent_relations 必须为数组」 |
| 元素类型非法（type 非三值） | 422 | 「agent_relations 类型非法: xxx（应为 sequential/data/conditional）」 |
| 自环（from==to） | 422 | 「agent_relations 自环非法: xxx」 |
| 重复边（相同 from,to） | 422 | 「agent_relations 重复边: xxx -> yyy」 |
| 死角色引用（引用**未知**角色，非内置 4 非 agent_roles） | 422 | 「agent_relations 引用了不存在的角色: xxx」 |
| agent_relations 自身环 | 422 | 「agent_relations 存在循环依赖」 |
| conditional 边多后继（B 非 A 唯一后继） | 422 | 「conditional 边 xxx->yyy 要求 yyy 是 xxx 的唯一后继」 |

---

## 4. CLI 命令签名

**本模块不新增 CLI 命令**。`agent_relations` 的 CLI 读写依赖 **#251 CLI project update**（0.8.0 已合入）——`inkflow project update --id N --config-json '{"agent_relations": [{"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"}]}'` 经既有 PATCH 合并语义天然支持（`list[{from,to,type}]` 经 JSON 透传，无特殊处理）。

- **约束**：① ProjectConfig 字段扩展不得破坏 #251 的 config 合并语义（agent_relations 是普通可选字段，exclude_unset 兼容）；② `inkflow project get --id N --json` 的 config 输出自动包含 agent_relations（F7 全局 JSON 信封约定，无需改动）。
- **验收联动**：M7（CLI 读写）依赖 #251 已合入（0.8.0 已交付）；若 CLI 形态有变，降级为 API 层验证（curl PATCH/GET agent_relations），PR 标注。

## 5. 关键差异节：Agent 关联关系 DAG 编排（拓扑合成 + 条件分支 + 数据传递）

### 5.1 执行拓扑合成总览（基线 + 叠加 + 关系优先）

**消费链**（现状 + F46 增量）：`AgentService.execute`（`domain/services/agent_service.py` L204-296）→ mode 分派（static/supervisor）→ **static 模式**：

```
stages = _apply_agent_order(template.stages, agent_order, enabled_roles, template_roles)   # F42 基线（分层全连接）
stages = _apply_agent_relations(stages, agent_relations, enabled_roles)                     # F46 新增（显式边叠加）
stages = await _merge_role_configs(stages, config, role_overrides)                          # 模型/温度/prompt 装配
→ self._pipeline.execute(stages, context, conditional_edges=...)                            # 引擎（F46 增 conditional_edges 参数）
```

- **supervisor 模式不消费 `agent_relations`**（§5.5）：动态路由取代静态边，`_apply_agent_relations` 仅在 static 模式调用。
- **叠加模型**：`agent_order` 基线（层间全序 + 层内并行 + 全连接注入）**保持不变**；`agent_relations` 显式边在基线上**逐边叠加**，冲突规则「关系优先」（显式边覆盖基线边）。

### 5.2 前端 DAG 编辑器（`AgentChainCard` 扩展，列表式关系编辑 + 只读预览）

**编辑形态（Q3 建议 A：列表 + 连线）**：在既有 `AgentChainCard`（开关 + 模型 Select + 槽位号）基础上扩展，**不引入独立画布拖拽**：

- **每角色行扩展「依赖」入口**：行内新增「依赖」按钮 → 展开该角色的**上游依赖选择器**（下拉选上游角色 + 边类型 sequential/data/conditional + 删除按钮）——表达「本角色依赖哪些上游 + 何种类型」。
- **独立「关系列表」区**（AgentChainCard 下方或独立卡片）：列出当前项目全部 `agent_relations` 边（`from → to [type]`），支持增删改（复用上游依赖选择器同一套交互）。
- **只读 DAG 预览**：以轻量 SVG（或 mermaid）渲染节点-边图——节点 = 角色（按 `agent_order` 层序纵向排布），边 = `agent_relations`（`sequential` 实线 / `data` 实线+数据标记 / `conditional` 虚线+菱形）。**预览只读**，编辑走列表/选择器（画布拖拽连线归远期 §10）。
- **数据流**：`stores/project.ts` ProjectConfig 接口新增 `agent_relations?: {from: string; to: string; type: string}[]`；读取走既有 `setConfig`/`saveConfig`（即改即存 PATCH，复用 F42 链路）；角色数据源 = 内置 4 + `agent_roles`（F42 交付）。
- **校验前端镜像**：保存前前端做「自环/重复边」预检（与后端 422 语义一致的提示）；环检测/死引用/conditional 唯一后继由后端 422 反馈（toast 展示 detail）。
- **conditional 边约束提示**：选择 conditional 类型时，前端提示「conditional 边要求目标角色是源角色的唯一后继」（与后端 §2.3 约束一致）。
- **E2E 契约锚点**：保留 `data-testid=agent-chain-card`；新增 `data-testid=agent-relation-editor`（关系列表）与 `data-testid=agent-relation-add`（依赖选择器），供 E2E 断言。

#### 5.3.1 `_apply_agent_relations(stages, agent_relations, enabled_roles) -> list[PipelineStage]`（纯函数，F46 新增）

1. 输入：`_apply_agent_order` 输出的**基线 stages**（分层全连接 DAG）+ `config.agent_relations` + `enabled_roles`（启用角色字段名集合，同 F42 口径）。
2. **空 `agent_relations`** → 原样返回（纯基线，零迁移，§1.2.3 线性兼容）。
3. **防御校验**（warning + 原样返回，忽略关系）：① 死角色引用——from/to 去 `agent_` 前缀后 ∉ 启用角色集合；② `agent_relations` 自身环；③ conditional 边多后继（B 非 A 唯一后继，§2.3）。任何非法 → warning + 返回输入基线 stages。
4. **逐边叠加**（关系优先，边去前缀 = A/B）：
   - **同层判定**：A、B 同层 = 基线中 A 不是 B 的前序（B 不依赖 A，即 A ∉ B 的「传递前序」）。同层边 = **打破并行**（新增时序约束）。
   - `sequential` A→B：**同层** → A.output_to 追加 B、B.input_from **不加** A（纯时序不注入）；**跨层**（B 已在 A 后序）→ 基线已覆盖时序，无引擎增量（语义强化，跳过）。
   - `data` A→B：**同层** → A.output_to 追加 B、B.input_from 追加 A（打破并行 + 注入）；**跨层** → 基线全量注入已覆盖，幂等确保 A ∈ B.input_from（显式声明，无新效果）。
   - `conditional` A→B：B.input_from 追加 A；记录 `(A, B)` 进 `conditional_edges` 集合（供引擎条件路由，§5.3.2）。A 的出边不变（条件路由在引擎构建，`conditional_edges` 作为 `execute` 参数传递）。
5. **合成后环检测**（Kahn，对最终 input_from/output_to 图，§5.3.4 复用）——`agent_relations` 逆序边（如 B 在 A 前序层但关系定义 A→B 之外）可能引入环 → 有环 → warning + 回退纯基线（返回输入 stages）。
6. 返回叠加后的 stages + `conditional_edges`（`(from, to)` 列表，随 stages 一并传递到 `execute`）。

- **返回值形态**：`_apply_agent_relations` 返回 `(stages, conditional_edges)` 二元组（或独立计算 conditional_edges 集合后传入 execute，实现确认）；`execute` 签名扩展 `conditional_edges: Sequence[tuple[str, str]] | None = None`。
- **装配顺序（F46 定稿）**：`execute` 中 static 模式顺序 = ① 读 agent_* 得启用集合 → ② `_apply_agent_order`（基线）→ ③ `_apply_agent_relations`（叠加 + conditional_edges）→ ④ `_merge_role_configs`（模型/温度/prompt，只装配存留角色）→ ⑤ `_run_pipeline`（传入 conditional_edges）。supervisor 模式跳过 ②③。

#### 5.3.2 三类型引擎映射（`langgraph_pipeline.py` MODIFY）

| 类型 | 边构建 | 数据注入 | 引擎增量 |
|------|--------|---------|---------|
| `sequential` A→B | `add_edge(A, B)`（静态时序） | **不注入**（B.input_from 无 A；prompt 引用 `{a_output}` 时由占位符扫描空注入，F42 §5.3.3） | 同层打破并行（新增边）；跨层无增量 |
| `data` A→B | `add_edge(A, B)`（静态时序） | **注入**（B.input_from 含 A → `{a_output}` 实际输出） | 同层打破并行 + 注入；跨层幂等 |
| `conditional` A→B | `add_conditional_edges(A, gate_fn, {B: B, END: END})` | **注入**（B.input_from 含 A，gate 通过时实际输出） | **条件路由**（Spike ② 实证） |

**引擎 `execute` 边构建改造**（`langgraph_pipeline.py` L114-120 MODIFY）：

```python
# 静态边：跳过条件边（条件边改用 add_conditional_edges 单独构建）
conditional_pairs = {tuple(p) for p in (conditional_edges or [])}
for stage in stages:
    for downstream_id in stage.output_to:
        if (stage.id, downstream_id) in conditional_pairs:
            continue  # 条件边：不 add_edge，下方 add_conditional_edges 处理
        workflow.add_edge(stage.id, downstream_id)
# 条件边：gate 函数读上游 output，PASS → 目标，否则 → END（跳过目标及其下游）
for from_id, to_id in conditional_pairs:
    workflow.add_conditional_edges(from_id, _make_gate(from_id, to_id), {to_id: to_id, END: END})
```

- **⚠️ 条件边/静态边互斥（f29 spike ② 教训的静态变体）**：LangGraph 单节点不能同时有静态出边 + 条件出边（会产生 fan-out / 行为未定义）。因此 conditional 边 `A→B` 要求 **B 是 A 的唯一后继**（§2.3 约束），保证 A 的**全部出边**都由条件路由承载（无静态出边冲突）。多后继条件 fan-out 归远期（§10）。
- **条件边与入口/终点判断**：conditional 边的 `from`/`to` 仍参与 entry/terminal 判定（B 无其它出边 → B 是终点；A 有 conditional 出边 → A 非终点）。环检测（Kahn）对「静态边 + 条件边」统一处理（条件边视为普通有向边）。

#### 5.3.3 conditional gate 语义（确定性规则，零额外 LLM 调用）

```python
_PASS_MARKERS = ("通过", "pass", "通过审核", "合格")   # 通过标记（不区分大小写匹配）

def _make_gate(from_id: str, to_id: str):
    def gate(state: PipelineState) -> str:
        sr = state["results"].get(from_id)
        text = (sr.output if sr else "").lower()
        passed = any(m in text for m in _PASS_MARKERS)
        return to_id if passed else END   # 通过 → 目标；不通过 → END（跳过目标及其下游）
    return gate
```

- **gate 判定 = 关键词匹配**（确定性规则，Q2 建议 A）：from 角色输出包含通过标记 → 通过；否则不通过。零额外 LLM 调用、可预测、可断言。
- **内置角色 prompt 约定**（§8）：`auditor` 的模板 prompt 输出加「**审核结论：通过 / 不通过**」一行（`_AUDITOR_PROMPT`/`_AUTO_AUDITOR_PROMPT`/`_CONTINUE_AUDITOR_PROMPT` MODIFY），使 conditional 边 `auditor→reviser` 的 gate 可稳定判定；自定义角色 conditional 边由用户自行在 prompt 约定通过标记（文档化）。
- **不通过的语义**：目标角色 B 及其下游**跳过**（B 不可达，未执行）；若 B 是终点 → 管线提前结束。
- **成品身份回退（F42 §5.6 语义扩展）**：终点 B 被条件边跳过时，`final_output` = 最后执行的**内容角色**（writer）输出（architect/auditor 永不作为成品）；无内容角色执行 → 空串 + warning。引擎 `execute` L147-156 的 terminal/final_output 计算需感知「终点被跳过」（results 无该终点条目 → 回退内容角色）。
- **gate 判定结果落执行记录**（§5.4）：conditional 边判定（passed/skipped）写入执行记录 relations 元数据，供「DAG 执行轨迹」查询。
- **独立 LLM 判定 / 条件表达式 DSL / 多条件分叉**：归远期（§10）。

#### 5.3.4 环检测复用（Kahn 拓扑排序）

- 复用 `langgraph_pipeline._detect_cycle`（L68-88，Kahn 算法）——API 层检测 `agent_relations` 自身环、执行层检测合成后完整图环，同一算法（F42 既有实现，零新增）。
- `agent_relations` 边在环检测中视为有向边 `from → to`；合成后图 = 基线边 ∪ 显式边（含同层打破并行边）。
- 环检测报错口径：API 层「agent_relations 存在循环依赖」；执行层回退纯基线（warning「agent_relations 与 agent_order 合成产生环，忽略关系」）。

### 5.4 执行轨迹元数据（DAG 关系/判定记录）

- **执行记录扩展**（`execution_store.py` MODIFY）：执行记录增加 `relations` 元数据字段（JSON 快照）——本次执行的 `agent_relations` 边 + conditional 边判定结果（`{from, to, type, gate_result: passed|skipped}`）。用于「执行日志/可视化（DAG 执行轨迹）」（issue 技术要点）的数据面。
- **落点**：`AgentService._run_pipeline` 在执行完成后回填 `relations` 快照（含 gate 判定）；`GET /pipelines/executions/{id}` 响应透出（F29 既有端点扩展）。
- **GUI 轨迹图归远期**（§10）：本期只落数据面，可视化渲染 UI 后续 issue。

### 5.5 与 F29 supervisor 的边界（mode 分派正交）

- **`agent_relations` 仅 static 模式消费**：`PipelineExecuteRequest.mode` 分派不变（static 默认 / supervisor）；`_apply_agent_relations` 仅在 static 模式调用（§5.1 消费链）。supervisor 模式 = 动态路由（LLM 决策边），与静态显式边（用户配置边）正交——**不组合**（同一执行要么 static + agent_relations，要么 supervisor，不混用）。
- **deepagents 兼容性结论不变**（Spike ① + F42 §5.5）：`agent_relations` 消费方仅 LangGraphAgentPipeline；deepagents 0.7.5 不参与 DAG 编排（F27 单 agent 闭环独立）。
- **`agent_order` 与 `agent_relations` 的边界**：`agent_order` = 拓扑基线（层序 + 并行），`agent_relations` = 显式边增强（依赖/数据/条件）——两字段并存，关系优先（§1.2.3）。

## 6. 组织规则

- `AgentRelation` + `agent_relations` 归属 domain 层（`domain/models/project.py`，与 `agent_order` 同文件）——domain 层零框架依赖，Pydantic 校验存储层。
- `_apply_agent_relations` 归属 domain 服务层（`agent_service.py` 模块级纯函数，不依赖 infrastructure）——与 `_apply_agent_order` 同模式，便于独立单测。
- 条件边构建（`add_conditional_edges`）+ gate 判定（`_make_gate` + `_PASS_MARKERS`）归属 infrastructure 层（`langgraph_pipeline.py` 或 `pipeline_nodes.py`）——domain 层不感知 LangGraph API（ADR-015 保持）。
- 前端关系编辑器保持「展示组件 + 回调」模式（`AgentChainCard` onConfigChange 即改即存，复用 F42 `settings.tsx` persist 链路）；DAG 预览组件独立（`AgentChainDagPreview`，纯展示）。
- 执行记录 relations 元数据归属 infrastructure 层（`execution_store.py`）——domain 层不感知存储细节。

---

## 7. 边界情况与错误处理

| 场景 | 行为 | 错误面 |
|------|------|--------|
| `agent_relations` 空列表 | 纯 `agent_order` 基线（零迁移，§1.2.3） | 无 |
| `agent_order` 空 + `agent_relations` 空 | 默认模板模式（线性链，F42 B1 语义零迁移） | 无 |
| `agent_order` 空（默认模板模式）+ `agent_relations` 非空 | 显式边叠加在**默认模板拓扑**上（模板 stages 原样 + 关系边）；死引用校验用「模板角色集合」 | 无（文档化行为） |
| 死角色引用（from/to 引用**未知**角色，非内置 4 非 agent_roles） | API 422「agent_relations 引用了不存在的角色: xxx」 | 输入拒绝 |
| 引用**未启用**角色（角色存在但 agent_* = null） | API 允许保存（前端提示「该角色未启用」）；执行层该边不生效（角色未参与执行）+ warning | 无（软降级） |
| 自环（from==to） | 存储层 422「agent_relations 自环非法: xxx」 | 输入拒绝 |
| 重复边（相同 from,to） | 存储层 422「agent_relations 重复边: xxx -> yyy」 | 输入拒绝 |
| type 非法（非三值） | 存储层 422「agent_relations 类型非法: xxx」 | 输入拒绝 |
| `agent_relations` 自身环 | API 422「agent_relations 存在循环依赖」 | 输入拒绝 |
| 合成环（关系逆序边 + agent_order 层序冲突） | 执行层回退纯基线 + warning（忽略关系） | 防御回退 |
| conditional 边多后继（B 非 A 唯一后继） | API 422「conditional 边 xxx->yyy 要求 yyy 是 xxx 的唯一后继」 | 输入拒绝 |
| conditional gate 通过 | 目标角色 B 执行（成品 = B 输出） | 无 |
| conditional gate 不通过 | 目标角色 B 及其下游跳过；B 是终点 → 管线提前结束，成品回退最后执行的内容角色（writer） | 设计语义（非错误，落 relations 判定） |
| 终点被条件边跳过 | final_output 回退内容角色（F42 §5.6 扩展）；无内容角色 → 空串 + warning | 软降级 |
| supervisor 模式 + `agent_relations` 非空 | **忽略**（supervisor 动态路由不消费 agent_relations，§5.5） | 无（文档化边界） |
| 存量项目（无 agent_relations 键） | Pydantic 默认空列表 → 纯基线 | 无（零迁移） |
| 执行记录 relations 快照 | `_run_pipeline` 完成后回填（含 gate 判定）；`GET /executions/{id}` 透出 | 无 |

---

## 8. 文件结构

> 对照真实源码树（2026-08-16 实证）。文件路径以主仓根为基准。

### 后端

| 动作 | 文件 | 说明 |
|------|------|------|
| MODIFY | `backend/src/inkflow/domain/models/project.py` | 新增 `AgentRelation`（from_/to/type + validator）+ `ProjectConfig.agent_relations` 字段 + validator（§2.1/§2.2） |
| MODIFY | `backend/src/inkflow/domain/services/agent_service.py` | 新增模块级 `_apply_agent_relations(stages, agent_relations, enabled_roles)`（叠加 + 合成环检测 + conditional_edges 集合，§5.3.1）；`execute` static 模式装配顺序插入步骤 ③（§5.1）；`_run_pipeline` 回填 relations 快照（§5.4） |
| MODIFY | `backend/src/inkflow/infrastructure/agent/langgraph_pipeline.py` | `execute` 签名扩展 `conditional_edges` 参数 + 条件边构建（`add_conditional_edges`，§5.3.2）+ `_make_gate`/`_PASS_MARKERS`（§5.3.3）+ 终点被跳过的 final_output 回退（§5.3.3） |
| MODIFY | `backend/src/inkflow/infrastructure/agent/pipeline_templates.py` | `_AUDITOR_PROMPT`/`_AUTO_AUDITOR_PROMPT`/`_CONTINUE_AUDITOR_PROMPT` 输出加「审核结论：通过 / 不通过」约定（§5.3.3 gate 判定依据） |
| MODIFY | `backend/src/inkflow/api/routers/project.py`（或 `domain/services/project_service.py`，实现确认） | agent_relations API 层语义校验 → 422（死引用/自身环/conditional 唯一后继，§2.3） |
| MODIFY | `backend/src/inkflow/infrastructure/agent/execution_store.py` | 执行记录增加 `relations` 元数据字段（JSON 快照，§5.4） |
| MODIFY | `backend/src/inkflow/api/routers/agent.py` | `GET /pipelines/executions/{id}` 响应透出 relations（§5.4，F29 既有端点扩展） |
| MODIFY | `backend/tests/unit/test_agent_service.py`（既有，追加） | `_apply_agent_relations` 契约：空回退/死引用回退/自身环回退/合成环回退/sequential 同层打破并行/data 同层注入/conditional 边标记 + conditional_edges 集合 |
| CREATE | `backend/tests/unit/test_agent_relations.py`（若既有过厚则独立） | ProjectConfig.agent_relations 存储层校验（结构/自环/重复边/类型）+ API 层校验（死引用/自身环/conditional 唯一后继 422） |
| MODIFY | `backend/tests/unit/test_langgraph_pipeline.py`（既有，追加） | 条件边构建（add_conditional_edges 两路：gate 通过执行目标 / 不通过跳过）+ 终点被跳过 final_output 回退 + 环检测回归 |
| MODIFY | `tests/cli/test_cli_project*.py`（既有，追加） | PATCH config.agent_relations 经 CLI 读写契约（#251 已合入；形态有变则降级 API 层，§4） |

### 前端

| 动作 | 文件 | 说明 |
|------|------|------|
| MODIFY | `frontend/packages/renderer/src/components/AgentChainCard.tsx` | 每角色行「依赖」入口 + 上游依赖选择器（§5.2）；保留 `data-testid=agent-chain-card` |
| CREATE | `frontend/packages/renderer/src/components/AgentRelationEditor.tsx` | 关系列表（from→to[type] 增删改）+ 只读 DAG 预览（`AgentChainDagPreview` SVG）；`data-testid=agent-relation-editor`/`agent-relation-add` |
| MODIFY | `frontend/packages/renderer/src/stores/project.ts` | ProjectConfig 接口新增 `agent_relations?: {from: string; to: string; type: string}[]` |
| MODIFY | `frontend/packages/renderer/src/components/AgentChainCard.test.tsx`（既有） | 追加关系编辑契约（依赖选择器增删改 + PATCH 结构正确） |
| CREATE | `frontend/packages/renderer/src/components/AgentRelationEditor.test.tsx`（如独立） | 关系列表渲染/增删改 + DAG 预览节点/边渲染 + conditional 约束提示 |

> 后端 API 校验落点（router 层 vs service 层）标注「实现确认」：与 F42 §2.3 同款选择（router 层贴近 422 语义，service 层贴近复用），实现时按测试可 mock 性选择。

## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 模型/契约（后端） | `AgentRelation` validator（type 非法拒绝 / from-to 空拒绝）；`ProjectConfig.agent_relations`（结构非 list 拒绝 / 自环拒绝 / 重复边拒绝 / 默认空） | ≥90% |
| 服务（后端） | `_apply_agent_relations`：空回退（纯基线）/ 死引用回退 / 自身环回退 / 合成环回退 / `sequential` 同层打破并行（output_to 追加、input_from 不加）/ `data` 同层打破并行 + 注入 / `conditional` 边标记 + conditional_edges 集合 / 跨层幂等 | ≥90% |
| 集成（后端） | `LangGraphAgentPipeline` 条件边：`add_conditional_edges` 两路（gate 通过 → 目标执行 / 不通过 → 目标跳过）；终点被跳过 final_output 回退内容角色（writer）；环检测回归（条件边视为有向边）；多入口/终点回归 | ≥90% |
| API（后端） | PATCH config.agent_relations 422 契约（死引用/自身环/conditional 唯一后继/类型非法）；`GET /executions/{id}` 透出 relations | ≥90% |
| 前端组件 | `AgentRelationEditor` 关系列表渲染/增删改 → PATCH 结构正确；DAG 预览节点/边渲染（三类型边样式）；conditional 约束提示 | ≥90% |
| E2E（如扩） | 设置页关系编辑 → PATCH 落库 → 重启保持（#270 验收）；写作按关系执行（内核 stderr/执行记录 relations 可查 conditional 判定） | 手工/E2E |
| 回归 | **静态模式零回归**：`agent_relations` 空 = 纯基线，既有 test_agent_service/test_langgraph_pipeline 全绿；supervisor 模式零回归（不消费 agent_relations） | 全仓 ≥60%（ADR-027 门禁） |

**RED 形态**：`_apply_agent_relations` 不存在 → ImportError；`AgentRelation` 缺失 → 用例导入失败；`execute` 无 `conditional_edges` 参数 → 断言签名失败；条件边构建缺失 → 条件分支用例断言目标跳过失败。

**测试无网络约束**：管线执行 mock `LLMClientProtocol`（既有 test_agent_service 模式）；条件边 gate 判定用 mock 输出（PASS/FAIL 标记）驱动；前端 mock `apiFetch`（既有 stores/models.test 模式）。

---

## 10. 不在范围内

| 项 | 归属 |
|----|------|
| 非全连接「精确数据流」（显式边完全取代基线全量注入，`sequential` 边移除基线注入） | 远期（本期保持基线全连接 + 全量注入，§1.2.1） |
| 多条件分叉（一条 from 边多条 conditional 出边 / 条件 fan-out） | 远期（本期 conditional 唯一后继约束，§2.3） |
| 条件表达式 DSL（`condition` 字段自定义判定逻辑） | 远期（本期 gate = 关键词匹配，§5.3.3） |
| 独立 LLM gate 判定（结构化 pass/fail） | 远期（本期确定性规则，Q2 建议 A） |
| 画布拖拽连线编辑（React Flow 等独立画布） | 远期（本期列表式 + 只读预览，Q3 建议 A） |
| DAG 执行轨迹 GUI 图（关系/判定可视化渲染） | 后续 issue（本期只落 relations 数据面，§5.4） |
| supervisor 模式 + agent_relations 组合（动态路由 + 静态显式边混用） | 不规划（两模式正交，§5.5） |
| deepagents harness 改造（subagent DAG） | 不规划（Spike ① 定稿：自研 LangGraph；deepagents 保持 F27 独立） |
| `agent_order` 静态拓扑改造（F42 已实现） | 不规划（本模块只叠加 agent_relations） |
| 条件边跨模式（supervisor 条件路由） | 不规划（supervisor 路由 = LLM 决策，非用户配置边） |

---

## 11. 依赖关系

- **依赖**：#269 agent_order（✅ PR #305：通用节点 + 多入口/终点引擎，`_apply_agent_relations` 在其输出上叠加）、F42 配置驱动编排（✅ 已实现）、F29 supervisor（✅ PR #323，mode 分派边界 §5.5）、F26 deepagents（✅，模型名剥离复用）、F42 #295 自定义 Agent 数据面（✅，`agent_roles` 是 agent_relations 引用面）、LangGraph 1.2.10（✅ venv 锁定，`add_conditional_edges` Spike ② 实证）、#251 CLI project update（✅ 0.8.0 已合入，agent_relations 读写 §4）。
- **被依赖**：DAG 执行轨迹可视化（后续 issue，依赖本模块 relations 数据面 §5.4）；0.10.0 写作管线/记忆（若引用显式 DAG 语义，另行评估）。
- **编号口径声明**：F46 为 Agent 化升级链（F26-F29）+ 配置面（F42）之后的 DAG 编排模块；按「最新无冲突基线」接续——本模块声明**第 19 变体**（冲突以 ADR-019 v5+ 为准，头部模块类型声明）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 备选（否决理由） |
|------|------|-----------------|
| 编排引擎 | **自研 LangGraph StateGraph（扩展 `LangGraphAgentPipeline`）** | deepagents 0.7.5 无 DAG/条件边注入（Spike ①）；重写引擎（F42 通用 DAG 子集已实现，YAGNI） |
| 条件分支实现 | **`add_conditional_edges`（gate 语义）** | `Command(goto)` 动态路由（F29 supervisor 域，非用户配置静态边）；静态边 + 运行时跳过（无法表达「目标执行与否」的条件调度） |
| 依赖类型 | **三类型正交（sequential/data/conditional）** | 单一类型（无法表达条件分支，issue 验收落空）；类型用裸 str（失去编译期约束） |
| 拓扑合成模型 | **基线（agent_order）+ 叠加（agent_relations），关系优先** | 显式边完全取代基线（破坏线性兼容 + 存量行为）；关系与基线互斥（用户心智混乱） |
| gate 判定 | **确定性规则（关键词匹配「通过/PASS」）** | 独立 LLM 判定（额外调用成本 + 弱模型空 content 风险 F26 教训）；条件表达式 DSL（范围膨胀，远期） |
| conditional 唯一后继约束 | **B 是 A 唯一后继** | 多后继条件 fan-out（LangGraph 单条件边单值路由 + 条件边/静态边互斥 f29 spike ②，远期） |
| 数据注入 | **保持基线全量注入 + data 边幂等确保** | 显式边取代注入（「精确数据流」语义，破坏现状 + 范围膨胀，归远期） |
| 同层显式边 | **允许（打破并行）** | 拒绝同层边（sequential/data 边功能空转，只能靠 agent_order 分层表达） |
| 编辑器形态 | **列表式关系编辑 + 只读 DAG 预览** | 独立画布拖拽（大 UI 工程 +3-5 人天，超本期估算，归远期） |
| 执行轨迹 | **relations 元数据数据面（本期）** | GUI 轨迹图（本期只落数据，渲染归后续 issue） |

---

## 13. 验收标准

> 对应 issue #270 验收要点 + 本任务 M1-M8 门禁。实现 PR `Closes #270`（单一 spec + 实现同 PR，8-12 人天）。

- **M1 Spike 结论（已完成）**: `docs/f46-dag-spike-2026-08-16.md` — deepagents 0.7.5 无 DAG/条件边注入 → 自研 LangGraph 编排层 + `add_conditional_edges` 条件分支实证
- **M2 Spec 合入**: 本 spec v1.0 合入 worktree 分支（spec 与实现同 PR）
- **M3 RED 批全 FAIL**: `pytest backend/tests/unit/test_agent_relations.py` + 追加段（test_agent_service/test_langgraph_pipeline）— 收集期 ModuleNotFoundError/ImportError（`AgentRelation`/`_apply_agent_relations` 不存在）+ 422/条件边断言 FAIL
- **M4 线性兼容零回归（#270 验收「兼容线性模式」）**: `pytest backend/tests/unit/` — `agent_relations` 空 = 纯基线，既有 test_agent_service/test_langgraph_pipeline 全绿；supervisor 模式零回归
- **M5 数据面 + 校验（#270 验收「可配置依赖关系」）**: `test_agent_relations.py` + API — `agent_relations` 存储层校验（类型/自环/重复边）；API 422（死引用/自身环/conditional 唯一后继）；`_apply_agent_relations`（空回退/死引用回退/自身环回退/合成环回退/sequential 同层打破并行/data 同层注入/conditional 标记 + conditional_edges 集合）
- **M6 执行引擎 DAG（#270 验收「按 DAG 执行，含条件分支语义」）**: `test_langgraph_pipeline.py` + `test_agent_service.py` — `add_conditional_edges` 两路（gate 通过执行目标 / 不通过跳过目标及其下游）；终点跳过 final_output 回退内容角色（writer）；环检测回归；relations 快照回填（`GET /executions/{id}` 透出）
- **M7 CLI 读写 + 回归**: `inkflow project update --config-json '{"agent_relations": [...]}'` 经 #251 读写（形态有变降级 API 层验证 + PR 标注）；除 §8 预期修改清单外全仓零回归 + 覆盖率门禁（ADR-027）
- **M8 GUI 关系编辑 + 持久化（#270 验收「GUI 可视化编辑」）**: GUI 设置页关系编辑（依赖选择器增删改 + 只读 DAG 预览三类型边样式）→ PATCH agent_relations → 重启保持；写作按关系执行（内核 stderr / 执行记录 relations 可查 conditional 判定）；conditional 约束提示（B 非 A 唯一后继）

---

## 待澄清问题

> F46 起草自检后剩余设计决策点（Spike 已定项不占配额：编排引擎 = 自研 LangGraph、条件边 = add_conditional_edges，见 §12）：

> **v1.1 拍板（2026-08-16）**：用户拍板「按照建议」——Q1=A / Q2=A / Q3=A 全部确认。正文已按 A 方案起草（v1.0 即按建议默认落笔），条目保留留痕。

- **Q1（阻塞级）：依赖类型范围** ✅ 已确认（用户拍板：选项 A）
  - **A. 三类型全做（sequential + data + conditional）**（建议）——完整覆盖 issue 产品设计三类型；「Auditor 依赖 Writer 输出」= data、「Reviser 在 Auditor 通过后才执行」= conditional 均可达；data/sequential 引擎成本极低（都是 `add_edge`），conditional 是 issue 验收「含条件分支语义」核心
  - B. 只做顺序依赖（sequential）——最小范围，但「条件分支语义」验收落空，data 语义无法显式表达
  - C. sequential + conditional（不做 data）——data 已被基线全连接覆盖，砍掉减少一个类型；但「数据传递」作为独立语义（同层数据依赖打破并行）缺失
  - **影响**：Q1 决定 §1.2.1/§2.1 type 枚举/§5.3.2 引擎映射/§8 文件结构；估算 A 全做 +0 人天（conditional 本就在验收内），B/C 缩减 -0.5~1 人天
- **Q2（阻塞级）：conditional gate 判定语义** ✅ 已确认（用户拍板：选项 A）
  - **A. 确定性规则（关键词匹配「通过/PASS」）**（建议）——零额外 LLM 调用、可预测、可断言；内置 auditor prompt 约定输出「审核结论：通过 / 不通过」；自定义角色由用户自行约定标记
  - B. 独立 LLM 判定（结构化 pass/fail）——更智能但多一次 LLM 调用 + 成本 + 弱模型空 content 风险（F26 教训）
  - **影响**：Q2 决定 §5.3.3 gate 实现/§8 auditor prompt 约定/§9 测试策略；A 零成本，B 估算 +1-2 人天
- **Q3（设计决策级）：DAG 编辑器形态** ✅ 已确认（用户拍板：选项 A）
  - **A. 列表 + 连线（关系列表 + 依赖选择器 + 只读 DAG 预览）**（建议）——复用既有 AgentChainCard，MVP 可落地，成本可控
  - B. 独立画布（拖拽连线，React Flow 等）——交互直观但大 UI 工程（+3-5 人天），超本期估算
  - **影响**：Q3 决定 §5.2/§8 前端文件结构/§10 范围外；A 零增量（列表编辑在 8-12 人天内），B 估算 +3-5 人天

## 14. 动作确认

> 每个端点/命令的完整状态流表（基于 §3 + §4 + §5 + §7 事实，不重复）。F46 无新增 REST 端点（§3）——配置面经既有 PATCH /projects/{id}，执行面 = 基线 + 叠加装配链（§5.1）。

### 14.1 配置端点状态流

| 端点 | 前置条件 | 动作/状态转换 | 成功 | 失败 | 边界 |
|------|---------|--------------|------|------|------|
| PATCH /api/v1/projects/{id}（config.agent_relations） | 项目存在 | exclude_unset 合并 → agent_relations 语义校验（§2.3 API 层） | 200 + 更新后 Project | 404；422（非数组「agent_relations 必须为数组」/ type 非三值「agent_relations 类型非法: xxx（应为 sequential/data/conditional）」/ 自环「agent_relations 自环非法: xxx」/ 重复边「agent_relations 重复边: xxx -&gt; yyy」/ 死角色引用「agent_relations 引用了不存在的角色: xxx」/ 自身环「agent_relations 存在循环依赖」/ conditional 多后继「conditional 边 xxx-&gt;yyy 要求 yyy 是 xxx 的唯一后继」） | 引用未启用角色（存在但 agent_* = null）→ API 允许保存 + 前端提示；空列表零迁移 |
| POST /api/v1/agent/pipelines/execute（static 模式消费链） | 模板存在 | _apply_agent_order 基线 → _apply_agent_relations 叠加（关系优先，逐边叠加 + conditional_edges 集合）→ _merge_role_configs → _run_pipeline（传入 conditional_edges） | 202 + execution_id | 422 | agent_relations 非法（执行层防御：死引用/自身环/合成环）→ warning + 回退纯基线；supervisor 模式不消费 agent_relations |
| GET /pipelines/executions/{id} | 执行记录存在 | 状态查询 + relations 元数据透出 | 200 + relations（边 + gate_result: passed/skipped） | 404 | F29 既有端点扩展；relation 快照由 _run_pipeline 完成后回填 |

### 14.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow project update --id N --config-json '{"agent_relations": [{"from": "agent_auditor", "to": "agent_reviser", "type": "conditional"}]}' | #251 已合入 | 经既有 PATCH 合并语义写入（list[{from,to,type}] JSON 透传） | 退出码 0 | 422 → 退出码 1 | 形态有变 → 降级 API 层验证 + PR 标注 |
| inkflow project get --id N --json | — | config 输出自动含 agent_relations | 退出码 0 | — | F7 信封约定，无需改动 |

### 14.3 验收锚点

- A1：agent_relations 存储层校验（类型/自环/重复边）+ API 422（死引用/自身环/conditional 唯一后继）（M5）
- A2：_apply_agent_relations 叠加语义（空回退/死引用回退/自身环回退/合成环回退/sequential 同层打破并行/data 同层注入/conditional 标记 + conditional_edges 集合）（M5）
- A3：add_conditional_edges 两路（gate 通过执行目标 / 不通过跳过目标及其下游）（M6）
- A4：终点被条件边跳过 → final_output 回退最后执行的内容角色（writer）（M6）
- A5：relations 快照回填 + GET /executions/{id} 透出（M6）
- A6：线性兼容零回归（agent_relations 空 = 纯基线 + supervisor 模式零回归）（M4）
- A7：GUI 关系编辑（依赖选择器增删改 + 只读 DAG 预览）+ 重启保持 + 写作按关系执行（stderr/relations 可查 conditional 判定）（M8）
