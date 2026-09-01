# F39: 多 Agent 能力（multi-agent）功能规格
> **端**: cross

**Spec 版本**: 1.2
**日期**: 2026-08-16（v1.2 修订 2026-08-20）
**依据**: 多 Agent 能力分析文档（`design/multi-agent-capability-analysis-2026-08-12.md`，已合入主仓）+ Issue #258（F39 后端核心）/ #259（F40 skill 上传绑定）/ #260（F41 自定义 Agent 编辑）+ 0.9.0 路线图拍板 Q1（`design/inkflow-0-9-0-roadmap-2026-08-15.md`：三 issue 合并一份 spec）
**所属阶段**: 0.9.0（多 Agent 能力一期），估算 10-15 人天（F39 后端 5-7 + F40 前端 2-3 + F41 前端 3-5，F40/F41 依赖 F39 可并行）
**关联 Issues**: [#258](https://github.com/zhx-xi/InkFlow/issues/258)（F39 后端核心，W2 启动）· [#259](https://github.com/zhx-xi/InkFlow/issues/259)（F40 skill 上传绑定，W3，🔗#258）· [#260](https://github.com/zhx-xi/InkFlow/issues/260)（F41 自定义 Agent 编辑，W3，🔗#258）
**依赖**: ✅ F26 工具注册表（已交付）· ✅ F27 agentic writer（已交付）· ✅ F19 AgentTemplate 实体模式（已交付）· ✅ #327 SQLite foreign_keys=ON（生产级联生效）
**参考 ADR**: [ADR-015](../../adr/llm/ADR-015.md)（LangChain 隔离）· [ADR-019](../../adr/packaging/ADR-019.md)（编号口径）· [adr/agent/ADR-035.md](../../adr/agent/ADR-035.md)（编排引擎=Deep Agents harness 0.7.5）· [ADR-022](../../adr/memory-skills/ADR-022.md)（skills 包分发型，与本 spec Skill 实体不同域，见 §1.3）
**状态**: ✅ 已实现（F39 后端 PR #403；F40 PR #408；F41 PR #407，2026-08-16）

> **Spec 变更**（v1.1 → v1.2，2026-08-20，#522 skill 存储架构重构去表）：① Skill 存储从 SQLite 表改为文件系统真源 `data_dir/skills/<name>/SKILL.md`（ADR-039）——§2.2/§3/§8/§10/§12 同步；② seed 语义改为 `ensure_builtin_skills(skills_root)`（同步回补）+ `migrate_skills_from_db(session, skills_root)`（一次性迁移）+ `seed_builtin_agents`（skill_ids=目录名）；③ 内置 6 skill 出厂名改英文 slug（N2 合规，§5.3 表）。

> **Spec 变更**（v1.0 → v1.1，2026-08-16，用户拍板 Q0=A / Q1=A）：① **Q0 定稿**「Agent/Skill 全局定义（应用级）+ 项目引用」——§2 实体无 project_id 字段，项目引用经 project config 留阶段 2 落地；② **Q1 定稿**「本期与 AgentTemplate 解耦」——本期无 AgentTemplate MODIFY，Agent 暂无运行时消费（能力以单元测试验证），roles 扩展为 Agent 引用留二期。§6 组织规则标注已拍板、§12 新增 D9/D10、待澄清 Q0/Q1 标记 ✅ 已确认（选项 A）。

> **模块类型声明**: 本模块为「**能力白名单强制型**」变体——新建 Agent/Skill 两张实体表（全局应用级）+ 工具目录分组扩展 + 装配点白名单过滤改造 + 前端上传/编辑两套 UI。编号依据：AGENTS.md 模块类型谱系口径下，F39 为 Agent 化升级链（F26 集成层 → F27 闭环 → F28 记忆 → **F39 多 Agent 能力** → F29 Supervisor）的能力差异化模块。核心不变式：**多 Agent 行为差异化 = 工具 + skill 白名单的确定性强制，而非 system prompt 概率性请求**（分析文档 §0）。

---

## 1. 概述

F39 合并覆盖 **#258（F39 后端核心）/ #259（F40 skill 上传绑定）/ #260（F41 自定义 Agent 编辑）** 三份 issue，作为三期实现的唯一真相来源。按章节划分子验收（§13 M1-Mn 标注子域归属）。

### 1.1 现状缺口（2026-08-16 源码实证）

| # | 缺口 | 实证 | 归属 |
|---|------|------|------|
| ① | 角色体系四角色固定（architect/writer/auditor/reviser），system prompt 代码内置，用户不可自定义 Agent | `infrastructure/agent/pipeline_templates.py` + `domain/models/agent_template.py` RoleTemplate（无 system_prompt 可编辑面，仅 prompt 字段 F42 扩展） | #258/#260 |
| ② | 工具装配硬编码：`build_agentic_writer` 无条件 `build_reader_tools`（5 只读）+ `build_save_draft_tool`，无按 Agent 过滤 | `infrastructure/agent/agentic_writer.py` L119-129 | #258 |
| ③ | 工具注册表 `TOOL_REGISTRY` 仅 5 只读 ToolSpec，**save_draft 动态构建不进注册表**、无分组（group）字段、无稳定目录给 UI 勾选 | `infrastructure/agent/tools/__init__.py` L18 + `reader_tools.py` `_TOOL_SPECS` + `save_draft_tool.py`（动态） | #258/#260 |
| ④ | **skill 概念零命中**（多 Agent 能力维度）——无 Skill 实体、无 skill 装配、无上传/绑定 UI | 代码仓 grep `skill` 仅 F19-skills 分发型 CLI（文件系统 `data_dir/skills/`，与本 spec 不同域） | #258/#259 |
| ⑤ | 无「Agent 管理列表 / 创建编辑页」——设置页「Agent」分类当前只挂 AgentChainCard（F42 编排配置），无 Agent 实体 CRUD 入口 | `pages/settings.tsx` L506-580 | #260 |
| ⑥ | 无「skill 上传/绑定/管理列表」UI | 前端无对应 store/组件 | #259 |

### 1.2 与样板差异

非 F9 实体 CRUD（有新增表但含**白名单装配改造**，非纯 CRUD）、非 F26 纯基础设施（有业务端点 + UI）、非 F27 闭环型（无新业务流程）——本模块是 **F9 实体 CRUD 变体 + 装配点改造 + 前端两套 UI** 的混合：后端新增 Agent/Skill 两实体（镜像 F19 AgentTemplate CRUD 模式）+ 工具目录分组扩展（F26 ToolSpec MODIFY）+ 装配点白名单过滤（deps.py/agentic_writer.py MODIFY）+ 前端上传/编辑两套 UI（镜像 settings.tsx 模板分类模式）。

### 1.3 边界声明

- **不含** 自定义函数（D3 已拍板不做）：函数注册表是产品资产，用户只「选配」不「编程」。
- **不含** 本期对 AgentTemplate 的改动（Q1 拍板：本期解耦；AgentTemplate.roles 扩展为 Agent 引用放二期）。
- **不含** 写作侧 Agent 选择入口（二期，F29 Supervisor 联动时设计）。
- **不含** Agent 实体的运行时消费接线（阶段 1 只交付「实体 + 装配能力」，装配点改造以单元测试验证白名单过滤；「哪个 Agent 跑哪个任务」的接线在阶段 2/3——分析文档 §6 演进路径）。F27 agentic writer 路径保持独立入口（工具型单 agent，`system_prompt=writer_agent.yaml`），不在本模块改造（F42 §1.3 同口径）。
- **与 F19-skills（ADR-022）的关系（#522 修订）**：F19-skills 是**分发型**基建（`inkflow skills` CLI 把用户自定义 SKILL.md 导入 `data_dir/skills/` 文件系统，供**外部 agent**（Hermes 等）学会操作 InkFlow）；#522 后本 spec 的 **Skill 实体同样以 `data_dir/skills/<name>/SKILL.md` 为文件系统真源**（ADR-039 去表）——两者**共用同一目录**（F19-skills 向该目录写入、F39 从该目录读取消费）。CLI 命名区分保留：本 spec `inkflow skill`（单数，REST 实体域）vs F19-skills `inkflow skills`（复数，文件系统导入）。
- **不含** 项目配置层对 Agent 的引用字段（Q0 的「项目引用」部分，二期 AgentTemplate.roles 扩展时一并落地；本期 Agent/Skill 均为全局应用级实体，项目差异留待阶段 2）。

---

## 2. 数据模型

### 2.1 Agent 实体（`domain/models/agent.py` CREATE）

```python
class Agent(BaseModel):
    model_config = {"from_attributes": True}

    id: int | None = None            # 主键（None = 未落库；repo.add 后 DB 自增分配）
    name: str                        # Agent 名（唯一，去空白非空）
    description: str = ""            # 描述
    icon: str = ""                   # 图标（emoji 字符或图标键；空串 = 默认图标）
    system_prompt: str = ""          # system prompt（内置 Agent 只读；自定义 Agent 可编辑）
    tool_ids: list[str] = Field(default_factory=list)      # 能力白名单：工具目录 name 列表
    skill_ids: list[str] = Field(default_factory=list)     # 能力白名单：skill 目录名列表（#522）
    model_override: str | None = None        # 模型覆盖（provider/model 格式，None = 跟随默认）
    temperature_override: float | None = Field(default=None, ge=0.0, le=2.0)  # 温度覆盖
    builtin: bool = False            # 是否内置（True = 只读，出厂 seed；False = 用户自定义）
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

- **`tool_ids` 存工具 `name`（snake_case 稳定标识）**——工具注册表唯一真源（§5.1），Agent 存 id 引用；下线工具在编辑页置灰提示（§5.5）。
- **`skill_ids` 存 skill 目录名列表（#522）**——与文件系统真源目录名（= frontmatter name，N2 规则）精确相等匹配（`agent_repository.list_agents_by_skill(skill_name)` 反查同语义）；不再存 DB 主键字符串化（ADR-039 D5 修订，§12）。
- **`model_override` 强制 `provider/model` 格式**（与 `parse_model_string` 硬契约一致，F42 Q3 同口径）——不存裸模型名/裸 provider 名。
- **`builtin` 折叠分析文档的 `source` 字段**（issue #258 字段清单仅列 `builtin`）：`builtin=True` 等价 `source="builtin"`，`builtin=False` 等价 `source="custom"`；内置 Agent 只读（PATCH/DELETE → 409）。

### 2.2 Skill 实体（`domain/models/skill.py` CREATE）

```python
class Skill(BaseModel):
    model_config = {"from_attributes": True}

    name: str                        # skill 目录名（唯一，= frontmatter name，N2 规则）
    description: str = ""            # 描述（frontmatter description 提取）
    content: str = ""                # 完整 SKILL.md 内容（frontmatter + markdown 正文，原样）
    source: str = "user_upload"      # 来源："builtin" | "user_upload"（由目录名判定）
    created_at: str | None = None    # 创建时间（文件 mtime ISO 字符串或 None）
    updated_at: str | None = None    # 最后更新时间（文件 mtime ISO 字符串或 None）
```

- **文件系统真源（#522 ADR-039）**：Skill 实体 = `data_dir/skills/<name>/SKILL.md`，**不再落 DB 表**；`content` 为文件内容原样（提示词注入面的「真相源 blob」），`name` = 目录名（= frontmatter name，N2 规则），`description` 为 frontmatter 解析元数据（列表展示用），上传时从 content 解析填充（§3/§5.4）。
- **`source` 由目录名判定（#522）**：目录名 ∈ `BUILTIN_SKILL_NAMES`（6 英文 slug）→ `"builtin"`，只读（PATCH/DELETE → 409「内置 skill 只读」）；否则 `"user_upload"`，可编辑/删除。不再有 DB source 列。
- **`agent_ids` 反查（非存储字段）**：由「哪些 Agent.skill_ids 精确含该目录名」反查计算（`agent_repository.list_agents_by_skill(skill_name)`，镜像 AgentTemplate `list_projects_by_template` 反查），删除保护用（§5.6）。
- **frontmatter 契约**（F40 上传解析，§5.4）：`name`（必选，1-64 小写字母数字+单连字符，N2 规则 `^[a-z0-9]+(-[a-z0-9]+)*$`，须与目录名一致）、`description`（必选）、`tags`（可选，列表，本 spec 不落列、保留在 content frontmatter 内）。

### 2.3 工具目录分组扩展（`domain/models/agent_tools.py` MODIFY）

```python
@dataclass
class ToolSpec:
    name: str                 # 工具名（snake_case，稳定 id）
    description: str          # 用途描述（LLM 调用决策 + UI 勾选说明）
    input_schema: dict        # JSON Schema（Pydantic model_json_schema() 产物）
    group: str = "project"    # 新增：分组键（writing/retrieval/audit/project，D2 勾选 UI 用）
```

- **分组键与 UI 标签映射**：`writing`→写作 / `retrieval`→检索 / `audit`→审计 / `project`→项目。
- **完整工具目录（6 工具，§5.1 静态注册）**：

| name | group | description | 现状 |
|------|-------|-------------|------|
| `save_draft` | `writing` | 保存章节草稿（agent 唯一写面） | ⚠️ 现为动态构建（`save_draft_tool.py`），**需补入静态注册表** |
| `search_characters` | `retrieval` | 搜索项目内角色档案 | ✅ 已在 `_TOOL_SPECS` |
| `check_foreshadowing` | `retrieval` | 列出未回收伏笔 | ✅ 已在 `_TOOL_SPECS` |
| `get_prior_summary` | `retrieval` | 获取前文摘要 | ✅ 已在 `_TOOL_SPECS` |
| `audit_chapter` | `audit` | 单章一致性审计 | ✅ 已在 `_TOOL_SPECS` |
| `count_words` | `audit` | 中英文混合字数统计 | ✅ 已在 `_TOOL_SPECS` |

- `project` 组本期为空（预留未来项目域工具）；分组字段随 `ToolSpec` 扩展一次性补齐，save_draft 的 ToolSpec 静态化（name/description/input_schema/group）但其 `func` 仍动态构建（依赖 draft_service/audit_service 注入）。

### 2.4 决策论证表

| 决策 | 方案 | 理由 |
|------|------|------|
| Agent 主键 / Skill 标识 | Agent 主键 int 自增（镜像 AgentTemplate）；Skill 无主键，标识 = 目录名（#522） | 项目全局惯例（F1-F19 全 int 自增）；Skill 去表后目录名即唯一标识（N2 规则） |
| skill_ids 引用形态 | `list[str]` 存 skill 目录名（英文 slug，N2） | 与文件系统真源目录名对齐（deepagents 原生 name 引用，#522 ADR-039 D5）；删除级联按目录名精确清理 |
| tool_ids 引用形态 | `list[str]` 存工具 `name` | 工具 name 是代码内稳定标识（snake_case），无独立工具表；`ToolSpec` 无 int id |
| Skill.content 语义 | 文件内容原样（frontmatter + 正文，文件系统真源 #522） | content 是注入真相源（原样可预览/可追溯）；name/description 由 frontmatter 解析供列表展示 + 唯一性校验 |
| 内置只读保护 | `builtin`(Agent) 字段 + `source`(Skill，由目录名判定) + 服务层 409 | 镜像 AgentTemplate `is_default` → 409 保护模式；「改坏了怎么恢复」的二次负担免于维护 |
| 工具目录分组 | `ToolSpec.group` 字段扩展（非独立分组表） | 6 工具规模小，字段扩展最小改动；分组表过度设计 |
| 装配能力 vs 消费接线 | 阶段 1 只交付装配能力（单元测试验证），不接运行时消费 | 分析文档 §6 演进路径（阶段 2 模板 roles 扩展、阶段 3 Supervisor 调度）；避免阶段 1 大改双配置源（Q1） |

---

## 3. API 契约

端点风格沿用既有扁平路由（镜像 `agent_templates.py`）：前缀 `/api/v1/agents` 与 `/api/v1/skills`，`Depends(get_db)` 注入 session。Agent 侧 `_parse_id`（非法 id → 404）；Skill 侧路径标识 = `skill_name`（目录名，#522，不存在/非法 → 404「Skill 不存在」，非 422）；`_run_service`（业务异常 → HTTP）、`_to_response`（实体 → 响应字典，Skill 兼容层 id=name）三层惯例。

### 3.1 端点总览

| 方法 | 路径 | 语义 | 响应 | 归属 |
|------|------|------|------|------|
| GET | `/api/v1/agents` | Agent 列表 | 200 `{items, total}` | #258/#260 |
| GET | `/api/v1/agents/tools` | 工具目录（勾选 UI 数据源） | 200 `{items:[{name,description,group,input_schema}]}` | #258/#260 |
| POST | `/api/v1/agents` | 创建自定义 Agent | 201 完整实体 | #258/#260 |
| GET | `/api/v1/agents/{agent_id}` | Agent 详情 | 200 完整实体 | #258 |
| PATCH | `/api/v1/agents/{agent_id}` | 部分更新（exclude_unset） | 200 完整实体 | #260 |
| DELETE | `/api/v1/agents/{agent_id}` | 删除自定义 Agent | 204 | #260 |
| GET | `/api/v1/skills` | Skill 列表（含反查） | 200 `{items, total}` | #258/#259 |
| POST | `/api/v1/skills` | 上传/创建 Skill（frontmatter 解析） | 201 完整实体 | #259 |
| GET | `/api/v1/skills/{skill_name}` | Skill 详情（含反查；id=name 兼容层，#522） | 200 完整实体 | #259 |
| PATCH | `/api/v1/skills/{skill_name}` | 部分更新（content 写回文件；内置 → 409） | 200 完整实体 | #258 |
| DELETE | `/api/v1/skills/{skill_name}` | 删除 Skill（被引用 → 级联清目录名引用） | 204 | #259 |
| POST | `/api/v1/skills/{skill_name}/duplicate` | 复制 Skill（新名 f"{name}-copy"） | 201 完整实体 | #485/#259 |

> 路由顺序约束：`GET /agents/tools` 必须声明在 `GET /agents/{agent_id}` 之前（FastAPI 顺序匹配，否则 "tools" 被吞进 path 参数 404——镜像 `agent_templates` `/default` 契约 #3）。

### 3.2 请求/响应示例

**POST /api/v1/agents**（创建自定义 Agent）：

```json
{
  "name": "我的润色师",
  "description": "专注文笔润色的自定义角色",
  "icon": "✨",
  "system_prompt": "你是润色师……",
  "tool_ids": ["count_words", "get_prior_summary", "save_draft"],
  "skill_ids": ["writing-methodology", "polishing-methodology"],
  "model_override": "zhipu/glm-4.5",
  "temperature_override": 0.6
}
```

**POST /api/v1/skills**（上传 Skill，frontmatter 后端解析）：

```json
{
  "content": "---\nname: web-research\ndescription: 网络调研方法论\n---\n# 调研流程\n1. ..."
}
```

> 响应 201 返回解析后的完整实体（#522 兼容层：`id` 字段值 = `name`）：`{id: "web-research", name: "web-research", description: "网络调研方法论", content: "<原样>", source: "user_upload", ...}`。

**GET /api/v1/skills**（列表，含反查）：

```json
{
  "items": [
    {
      "id": "web-research",
      "name": "web-research",
      "description": "网络调研方法论",
      "source": "user_upload",
      "agent_ids": [{"id": 2, "name": "写手"}, {"id": 6, "name": "架构师"}]
    }
  ],
  "total": 1
}
```

### 3.3 异常映射表

| 业务异常 | HTTP | 触发 |
|----------|------|------|
| `AgentNotFoundError` / `SkillNotFoundError` | 404 | Agent id 不存在 / 非法格式（`_parse_id` 404 语义）；skill_name 不存在 / 非法（404「Skill 不存在」） |
| `AgentNameConflictError` / `SkillNameConflictError` | 422 | 同名（Agent 名唯一 / skill 目录名唯一；422「同名 skill 已存在」） |
| `AgentBuiltinError` / `SkillBuiltinError` | 409 | PATCH/DELETE 内置实体（`builtin=True` / 目录名 ∈ BUILTIN slug；409「内置 skill 只读」） |
| `SkillFrontmatterError` | 422 | frontmatter 缺失 name/description 或 name 格式非法（422「frontmatter 不合法」） |
| `ToolReferenceError` / `SkillReferenceError` | 422 | `tool_ids` 含目录外工具名 / `skill_ids` 含不存在 skill 目录名 |

> 服务层异常定义在 `domain/ports/agent_errors.py` + `domain/ports/skill_errors.py`（镜像 `agent_template_errors.py`），router 层 `_run_service` 统一映射。

---

## 4. CLI 命令签名

**对齐 CLI 恒经 HTTP 架构**（F38）：三条命令均为 `ensure_kernel() + InkFlowHTTPClient` 薄层，非本地静态枚举（区别于 F26 `inkflow agent tools list` 本地豁免）。签名遵循 F7 全局约定（`--json` 信封 / 退出码 0/1/2）。

```
inkflow agent list [--json]
  列出全部 Agent（name + description + builtin 标记）
  --json: 信封 {"ok": true, "data": {items, total}}
  退出码: 0 成功 / 1 运行错误（内核启动失败/HTTP 错误）/ 2 参数错误

inkflow agent show --id <N> [--json]
  查看单个 Agent 详情（system_prompt + tool_ids + skill_ids + model/temperature 覆盖）
  退出码: 0 成功 / 1 运行错误（含 404 不存在）/ 2 参数错误

inkflow skill list [--json]
  列出全部 Skill（name + source + 被引用 Agent 数）
  退出码: 0 成功 / 1 运行错误 / 2 参数错误
```

- 实现位置：MODIFY `backend/src/inkflow/cli/commands/agent_cmd.py`（`agent` 组新增 `list`/`show` 子命令）+ CREATE `backend/src/inkflow/cli/commands/skill_cmd.py`（`skill` 组）+ MODIFY `backend/src/inkflow/cli/app.py`（注册 `skill` 子组）。
- **命名区分（防撞）**：`inkflow agent list`（本 spec，列 Agent 实体）≠ `inkflow agent template list`（F19，列模板）≠ `inkflow agent tools list`（F26，本地枚举工具）；`inkflow skill list`（本 spec，单数，REST 实体域，文件系统真源 #522）≠ `inkflow skills list`（F19-skills，复数，文件系统导入）。

---

## 5. 关键差异节：能力白名单装配

核心不变式（分析文档 §5.2）：**多 Agent 行为差异化 = 工具 + skill 白名单的确定性强制**——「只给 LLM 白名单内的东西」，非「请求 LLM 遵守」。

```
运行时装配（deps.py 现行逻辑的升级版）：
1. 按 agent.tool_ids 过滤工具目录 → 只 build 白名单内工具的 func 到 harness
2. 按 agent.skill_ids 过滤 skill 库 → 只拼白名单 skill 内容进 system prompt
3. 白名单外的一切对 LLM 不可见 → 行为差异 = 确定性，非概率
```

### 5.1 工具目录与分组（`infrastructure/agent/tools/` MODIFY）

- `ToolSpec` 增加 `group: str` 字段（§2.3 四分组键）。
- `save_draft` 的 ToolSpec **静态化入 `TOOL_REGISTRY`**（name/description/input_schema/group 常量），其 `func` 仍由 `build_save_draft_tool` 动态构建（依赖 draft_service/audit_service 注入）——`TOOL_REGISTRY` 由「5 只读」升级为「完整 6 工具目录」。
- 目录排序固定：先 5 只读（`_TOOL_SPECS` 原序）后 `save_draft`；`GET /agents/tools` 按此序返回，前端按 `group` 聚合为 checkbox 分组。

### 5.2 装配点改造（`infrastructure/agent/agentic_writer.py` + `api/deps.py` MODIFY）

`build_agentic_writer` 签名扩展白名单参数：

```python
def build_agentic_writer(
    *,
    model: str, api_key: str, base_url: str,
    deps: AgenticWriterDeps,
    system_prompt: str,
    tool_ids: list[str] | None = None,   # 新增：白名单工具名（None = 全部，向后兼容）
    skill_ids: list[str] | None = None,  # 新增：白名单 skill 目录名（None = 不拼 skill）
    ...
):
    # ① 工具过滤：None → 全量（现行为）；[...] → 只 build 白名单内工具
    reader_deps = ReaderToolDeps(...)
    tools = build_reader_tools(reader_deps, include=tool_ids)  # include=None → 5 只读全量
    if tool_ids is None or "save_draft" in tool_ids:
        tools.append(build_save_draft_tool(SaveDraftToolDeps(...)))
    # ② skill 拼接：None → 不拼；[...] → 只拼白名单 skill content 进 system_prompt
    system_prompt = _append_skills(system_prompt, skill_ids, skill_lookup)
    ...
```

- **`build_reader_tools` 增加 `include: list[str] | None = None` 参数**：None → 返回 5 只读全量（现行为不变）；`[...]` → 只返回白名单命中项（按目录序）。`save_draft` 因依赖不同 deps 独立判断是否追加。
- **skill 拼接函数 `_append_skills(base_prompt, skill_ids, skill_lookup)`**：对每个白名单 skill 目录名，追加 `\n\n# 技能：<name>\n\n<content>\n\n---\n`（base prompt 在前、skill 在后——分析文档 §5.3「skill 追加在用户 prompt 之后」优先级）。`skill_lookup` 由装配层注入（从 `data_dir/skills/` 文件系统按目录名取 content，#522）。
- **向后兼容**：`tool_ids=None, skill_ids=None` = 现 F27 行为（全工具 + writer_agent.yaml prompt，无 skill）。**阶段 1 不改动 F27 调用点**（`get_agentic_writer_service._build_agent` 不传白名单），白名单过滤能力由单元测试验证（§9），运行时消费接线留阶段 2/3（§1.3 边界）。

### 5.3 内置出厂配置 seed / 启动回补（`app.py` lifespan MODIFY，#522 修订）

#522（ADR-039）后 skill 不再落 DB：启动在 `create_tables()` 后、provider seed 同点依次调用：
- `ensure_builtin_skills(config.data_dir / "skills")`（**同步**纯文件操作）：目录缺失/内置缺失 → 幂等写出 6 个内置 SKILL.md（frontmatter name=英文 slug，删了回补），返回本次写入数
- `await migrate_skills_from_db(session, config.data_dir / "skills")`（**async**，raw SQL）：旧 skills 表 `source='user_upload'` 行 → 写出 `<name>/SKILL.md` → 清表（DELETE/DROP；表不存在 → 0，不重建、不依赖 SkillORM）
- `await seed_builtin_agents(session)`（保留）：`skill_ids=[spec.skill_name]`（目录名，不再按 BUILTIN_SKILL_NAMES.index 预测主键）

**内置 Agent 出厂配置（6 个，`builtin=True` 只读）**：

| Agent | 定位 | 出厂工具白名单（tool_ids） | 出厂 skill（skill_ids = 目录名 slug） |
|-------|------|---------------------------|--------------------------------------|
| 架构师 | 章节结构/大纲规划 | search_characters, check_foreshadowing, get_prior_summary | architecture-methodology |
| 写手 | 正文生成 | 检索全 3 + save_draft | writing-methodology |
| 审校员 | 一致性审计 | audit_chapter, count_words, search_characters | audit-methodology |
| 修订师 | 修订打磨 | get_prior_summary, count_words, save_draft | revision-methodology |
| 世界观顾问 | 世界观一致 | search_characters, check_foreshadowing | worldview-methodology |
| 润色师 | 文笔润色 | count_words, get_prior_summary | polishing-methodology |

**内置 Skill 出厂配置（6 个，目录名 ∈ BUILTIN_SKILL_NAMES → `source="builtin"` 只读）**：与上表「出厂 skill」一一对应（架构/写作/审校/修订/世界观/润色六份方法论 SKILL.md，content 含 frontmatter name=slug + 中文正文，须通过 `parse_skill_metadata` 校验）。出厂 prompt 与 skill 正文为 ensure 内容（实现期编写，非契约字段），契约只定「6 Agent + 6 Skill slug + 上表白名单映射」。

### 5.4 F40 skill 上传与绑定（前端交互，#259）

| 步骤 | 交互 | 契约锚点 |
|------|------|----------|
| 上传 | 选文件/粘贴 SKILL.md → **frontmatter 解析（name/description/tags）+ 预览**（正文可查——skill 是提示词注入面，透明可查） | 客户端解析预览 + 后端 POST /skills 权威解析（`SkillFrontmatterError` 422） |
| 绑定 | **上传时显式指定可用 Agent（默认不勾选 + 可搜索列表 + 「应用到全部 Agent」快捷按钮）** | D1 拍板：默认不启用（AI 自动化默认关闭铁律）+ 上传时指定 + 编辑页可改 + 应用全部 |
| 管理列表 | name/description/来源（内置/用户上传）/被哪些 Agent 引用（反查视图） | GET /skills 的 `source` + `agent_ids` |
| 删除保护 | 被 N 个 Agent 引用 → 确认框列出影响面（对齐模板删除确认拍板先例）；内置 skill 只读不可删 | 前端确认框 + 后端 409（builtin）/ 级联清引用（user_upload） |

**D1 绑定时机（已拍板，固化）**：上传动作当下是意图最清晰时刻；默认不启用杜绝「幽灵注入」（行为莫名改变无法归因）；「应用到全部」照顾全局诉求。绑定产物 = 更新目标 Agent 的 `skill_ids`（PATCH /agents/{id}）。

### 5.5 F41 自定义 Agent 编辑（前端交互，#260）

| 步骤 | 交互 | 契约锚点 |
|------|------|----------|
| 管理列表 | 设置页「Agent」分类：内置 Agent（只读展示：prompt 预览 + 出厂能力清单）/ 自定义 Agent（可编辑） | GET /agents 的 `builtin` 字段分流 |
| 创建/编辑页 | ① 基本信息（名称/描述/图标）② system prompt（内置只读/自定义可编辑）③ 函数选择（**分组 checkbox**：writing/检索/审计/项目 + 描述，>10 加搜索）④ skill 绑定（可搜索 skill 列表，与 F40 互通）⑤ 模型/温度覆盖 | D2 拍板：分组 checkbox；内置函数集锁定只读、自定义可编辑 |
| 双向视图 | Agent 页看「我有哪些工具/skill」；skill 页（F40）看「被哪些 Agent 引用」 | GET /agents/{id} 的 tool_ids/skill_ids + GET /skills 的 agent_ids |
| 删除保护 | 删除自定义 Agent → 确认框；内置不可删 | 后端 409（builtin）；本期无 project/template 引用（Q1 解耦），影响面仅「确认删除」 |

**D2 函数选择 UI（已拍板，固化）**：函数是**多选白名单**语义（非单选），分组 checkbox 比下拉直观；内置 Agent 函数集**出厂锁定（只读展示）**避免「改坏了怎么恢复」的二次负担，自定义 Agent 才可编辑。

### 5.6 删除保护语义（service 层）

| 对象 | 保护 | 行为 |
|------|------|------|
| 内置 Agent（`builtin=True`） | 只读 | PATCH/DELETE → `AgentBuiltinError` 409 |
| 内置 Skill（`source="builtin"`） | 只读 | PATCH/DELETE → `SkillBuiltinError` 409 |
| 用户 Skill（被 N 个 Agent 引用） | 级联清引用 | DELETE → 服务层先移除所有 Agent.skill_ids 中的该目录名（`agent_repository.list_agents_by_skill(skill_name)` 反查 + 批量 update，#522 目录名语义）再删目录（镜像 AgentTemplate `delete` 级联清 `config.template_id`）；前端删除前经 `agent_ids` 反查列影响面确认 |
| 自定义 Agent | 无引用面（本期） | DELETE → 直接删；二期引入 project/template 引用时扩展影响面确认（Q0/Q1） |

> **级联清引用 + `foreign_keys=ON` 双保险**：`PRAGMA foreign_keys=ON` 已启用（#327），若引入 skill/agent 中间表需声明 `ondelete`；本 spec 用 JSON 列（`Agent.skill_ids`）存引用，无 FK 约束，级联清引用由**服务层显式**完成（不可依赖 repo 注释「FK CASCADE」——F43 P5 假绿教训）。

---

## 6. 组织规则

- **全局定义 + 项目引用（Q0 已拍板 A）**：Agent/Skill 是**全局应用级**实体（跨项目复用——「我的润色 Agent」不该每项目重建）；skill 是「方法论」而非「项目数据」，与「设定库随项目走」（角色/世界观=项目数据）不同层不冲突。项目差异通过阶段 2 的项目配置选择 Agent 实现（本 spec 不落地 project config 字段）。
- **与 AgentTemplate 解耦（Q1 已拍板 A）**：Agent 管「能力边界」（白名单），AgentTemplate 管「模型/温度」（F19 引用式）——两个正交维度；本期独立，二期 AgentTemplate.roles 扩展为任意 Agent 引用（模型/温度覆盖保留）时打通。
- **白名单确定性强制**：任何 Agent 运行，工具与 skill 均按 `tool_ids`/`skill_ids` 白名单过滤后交付 LLM——白名单外对 LLM 不可见（确定性，非概率）。
- **内置只读**：出厂 Agent/Skill 只读（409），用户只能「复制后改」或「新建自定义」；内置清单 = 产品资产，禁止运行时增删改。
- **能力引用唯一真源**：工具以 `ToolSpec.name` 为唯一标识、skill 以目录名（= frontmatter name）为唯一标识（#522）；下线工具在编辑页置灰提示（不硬删，避免存量 Agent 白名单悬空）。

---

## 7. 边界情况与错误处理

| # | 边界 | 处理 |
|---|------|------|
| ① | 创建 Agent 同名 | `AgentNameConflictError` → 422 |
| ② | 上传 skill frontmatter 缺失 name/description 或 name 格式非法 | `SkillFrontmatterError` → 422（frontend 预览阶段提示） |
| ③ | 上传 skill 同名 | `SkillNameConflictError` → 422 |
| ④ | `tool_ids` 含目录外工具名 | `ToolReferenceError` → 422 |
| ⑤ | `skill_ids` 含不存在 skill 目录名（无 `<name>/SKILL.md` 文件） | `SkillReferenceError` → 422 |
| ⑥ | PATCH/DELETE 内置实体 | 409（`builtin=True` / `source="builtin"`） |
| ⑦ | 删除被引用 user skill | 服务层级联清所有 Agent.skill_ids 引用后删（前端先确认影响面） |
| ⑧ | 删除自定义 Agent | 直接删（本期无引用面） |
| ⑨ | 非法 id 格式（非整数）/ 非法 skill_name（N2 违规或不存在） | 404（`_parse_id` 语义，不 422；skill_name 404「Skill 不存在」） |
| ⑩ | skill 上传 = prompt injection 面扩大 | 本地单用户工具（风险自担）+ skill 内容 UI 可预览 + skill 追加在用户 prompt 之后（优先级明确） |
| ⑪ | 工具下线/改名漂移 | 工具注册表唯一真源；Agent 存 name 引用；下线工具编辑页置灰 |
| ⑫ | 存量库升级（无 alembic，#522） | `agents` 表由 `create_all` 自动建；旧 `skills` 表由 `migrate_skills_from_db` 一次性迁移 user_upload 行 → 文件后清表（表不存在 → 0）；内置 Skill 由 `ensure_builtin_skills` 回补文件 |

---

## 8. 文件结构

> 对照真实源码树（2026-08-16 origin/main 4e6be5f 核查）。后端 `backend/src/inkflow/`，前端 `frontend/packages/renderer/src/`。

### 8.1 后端 CREATE

| 文件 | 内容 |
|------|------|
| `domain/models/agent.py` | `Agent` / `AgentCreate` / `AgentUpdate`（镜像 `agent_template.py`） |
| `domain/models/skill.py` | `Skill` / `SkillCreate` / `SkillUpdate` |
| `domain/ports/agent_repository.py` | `AgentRepositoryProtocol`（add/get/get_by_name/list/update/delete + `list_agents_by_skill`） |
| `domain/ports/agent_errors.py` | `AgentNotFoundError`/`AgentNameConflictError`/`AgentBuiltinError`/`ToolReferenceError`/`SkillReferenceError` |
| `domain/ports/skill_errors.py` | `SkillNotFoundError`/`SkillNameConflictError`/`SkillBuiltinError`/`SkillFrontmatterError` |
| `domain/services/agent_entity_service.py` | Agent CRUD + 白名单引用校验（skill_ids 目录名存在性）+ builtin 只读保护 |
| `domain/services/skill_service.py` | Skill CRUD（文件系统真源内联操作）+ frontmatter 解析校验 + 删除级联清引用 + `ensure_builtin_skills`/`migrate_skills_from_db` |
| `infrastructure/database/models/agent.py` | `AgentORM`（`agents` 表；tool_ids/skill_ids 存 LenientJSON） |
| `infrastructure/database/repositories/agent_repo.py` | `SQLiteAgentRepository`（转换函数 + `list_agents_by_skill` 反查） |
| `api/routers/agents.py` | `/api/v1/agents` 路由（`/tools` 声明在 `/{agent_id}` 前） |
| `api/routers/skills.py` | `/api/v1/skills` 路由 |
| `cli/commands/skill_cmd.py` | `skill list` 子命令（HTTP 薄层） |

> #522 删除：`domain/ports/skill_repository.py`（SkillRepositoryProtocol）、`infrastructure/database/models/skill.py`（SkillORM）、`infrastructure/database/repositories/skill_repo.py`（SQLiteSkillRepository）——skills 表相关 DB 路径整体退役（ADR-039 D3a=B）。

### 8.2 后端 MODIFY

| 文件 | 改动 |
|------|------|
| `domain/models/agent_tools.py` | `ToolSpec` 增加 `group` 字段 |
| `infrastructure/agent/tools/__init__.py` | `TOOL_REGISTRY` 升级为完整 6 工具目录（含 save_draft 静态 spec） |
| `infrastructure/agent/tools/reader_tools.py` | `build_reader_tools` 增加 `include` 参数（白名单过滤） |
| `infrastructure/agent/tools/save_draft_tool.py` | save_draft `ToolSpec` 静态化（常量提取，供目录注册） |
| `infrastructure/agent/agentic_writer.py` | `build_agentic_writer` 增加 `tool_ids`/`skill_ids` 参数 + `_append_skills` |
| `infrastructure/database/models/__init__.py` | import 注册 `AgentORM`（触发 Base.metadata；#522 移除 SkillORM 注册） |
| `api/app.py` | `include_router(agents.router, skills.router)` + lifespan `ensure_builtin_skills()` → `migrate_skills_from_db()` → `seed_builtin_agents()`（#522 顺序） |
| `cli/commands/agent_cmd.py` | `agent` 组新增 `list`/`show` 子命令 |
| `cli/app.py` | 注册 `skill` 子组 |

### 8.3 前端 CREATE / MODIFY

| 文件 | 改动 | 归属 |
|------|------|------|
| `stores/agents.ts` | CREATE：`useAgentsStore`（loadAgents/createAgent/updateAgent/deleteAgent/loadToolCatalog，镜像 `stores/templates.ts` apiFetch 模式） | #260 |
| `stores/skills.ts` | CREATE：`useSkillsStore`（loadSkills/uploadSkill/deleteSkill + agent_ids 反查） | #259 |
| `components/AgentList.tsx` | CREATE：Agent 管理列表（内置只读展示 / 自定义可编辑） | #260 |
| `components/AgentEditDialog.tsx` | CREATE：创建/编辑页（基本信息 + prompt + 分组 checkbox + skill 绑定 + 模型/温度覆盖） | #260 |
| `components/SkillUploadDialog.tsx` | CREATE：上传（frontmatter 解析预览 + 上传时绑定 Agent） | #259 |
| `components/SkillList.tsx` | CREATE：skill 管理列表（来源/反查/删除确认） | #259 |
| `pages/settings.tsx` | MODIFY：五分类导航新增「Agent 管理」「Skill 管理」（或并入既有「Agent」分类 + 新增「Skill」分类，实现确认） | #259/#260 |

### 8.4 测试文件

| 文件 | 内容 |
|------|------|
| `backend/tests/unit/test_agent_service.py` | Agent 服务 CRUD + 白名单校验 + builtin 保护 |
| `backend/tests/unit/test_skill_service.py` | Skill 服务 CRUD + frontmatter 解析 + 级联清引用 |
| `backend/tests/unit/test_tool_catalog.py` | 6 工具目录 + group 分组 + save_draft 静态 spec |
| `backend/tests/unit/test_agentic_whitelist.py` | `build_agentic_writer` 白名单过滤（工具 + skill 拼接） |
| `backend/tests/integration/test_agents_api.py` | `/api/v1/agents` 端点契约（含 `/tools` 路由顺序） |
| `backend/tests/integration/test_skills_api.py` | `/api/v1/skills` 端点契约（frontmatter 校验 + 反查） |
| `backend/tests/integration/test_builtin_seed.py` | seed 幂等（6 Agent + 6 Skill + 重复启动不重复插入） |
| `frontend/.../agents.test.tsx` + `skills.test.tsx` | store 单测 + 组件测试（Vitest + RTL） |
| `frontend/.../e2e/*.spec.ts` | 上传→绑定→引用视图→删除确认 全流程（F40）+ 创建→编辑→白名单展示→删除确认（F41） |

---

## 9. 测试策略

| 层 | 覆盖 | 关键场景 |
|----|------|----------|
| 单元（pytest） | Agent/Skill 服务 + 工具目录 + 白名单装配 | 白名单过滤确定性（tool_ids 只 build 命中项）；`include=None` 向后兼容；skill 拼接顺序（base 前 skill 后）；builtin 只读 409；frontmatter 解析（合法/缺失/格式非法）；级联清引用 |
| 集成（pytest） | `/agents` + `/skills` 端点契约 | `/agents/tools` 路由顺序（不被 `/{agent_id}` 吞）；`_parse_id` 404；422/409 映射；seed 幂等 |
| 前端（Vitest + RTL） | store + 组件 | 分组 checkbox 渲染与勾选语义；内置只读 vs 自定义可编辑分流；上传时绑定默认不勾选；删除确认框列影响面 |
| E2E（Playwright） | 全流程 | F40：上传→绑定→引用视图→删除确认；F41：创建→编辑→函数/skill 白名单展示→删除确认 |

- 覆盖率：模块 ≥80%、全仓 ≥60%（AGENTS.md 质量护栏）。新增测试文件须登记 `ci.yml` 对应 job。
- 白名单过滤是**纯确定性逻辑**（非 LLM 依赖），单元测试无需真实 API key；LLM 依赖测试走 `e2e-ai-backend` 开关模式（CI 默认 skip）。

---

## 10. 不在范围内

| 项 | 归属 | 原因 |
|----|------|------|
| 自定义函数（用户定义新工具） | 不做（D3 已拍板） | 心智负担 > 收益；函数注册表是产品资产 |
| AgentTemplate 改动（roles 扩展为 Agent 引用） | 二期 | Q1 解耦，避免一次大改双配置源 |
| 写作侧 Agent 选择入口 | 二期 | F29 Supervisor 联动时设计 |
| Agent 实体运行时消费接线（哪个 Agent 跑哪个任务） | 阶段 2/3 | 分析文档 §6 演进路径；F27 路径保持独立入口 |
| 项目配置层 Agent 引用字段 | 二期 | Q0「项目引用」随 AgentTemplate.roles 扩展一并落地 |
| F19-skills 文件系统 skill（`data_dir/skills/`）消费 | 共用目录（#522） | #522 后本 spec Skill 实体与 F19-skills **共用 `data_dir/skills/` 文件系统真源**（ADR-039 去表）：F19-skills 导入写入、F39 读取消费同一目录 |
| MCP Server（#49） | 0.9.0 独立 | F20 独立域 |
| DAG 编排（#270） | 0.9.0 独立 | F46 独立域 |

---

## 11. 依赖关系

**依赖（本模块消费）**：

| 依赖 | 关系 | 说明 |
|------|------|------|
| F26 工具注册表（✅ 已交付） | MODIFY | `ToolSpec` 加 group + `build_reader_tools` 加 include |
| F27 agentic writer（✅ 已交付） | MODIFY | `build_agentic_writer` 加白名单参数（向后兼容，F27 调用点不改） |
| F19 AgentTemplate（✅ 已交付） | 参照 | CRUD/ORM/repo/service/router 模式照搬 |
| F9/F13/F34/F6/F3 服务 | 消费 | 工具包装对象（reader_tools 既有，不变） |

**被依赖（消费本模块）**：

| 消费方 | 说明 |
|--------|------|
| #259 F40 skill 上传绑定 | 依赖本 spec §2/§3 的 Skill 实体 + API + §5.4 交互 |
| #260 F41 自定义 Agent 编辑 | 依赖本 spec §2/§3 的 Agent 实体 + API + §5.5 交互 |
| 阶段 2 AgentTemplate.roles 扩展 | 依赖 Agent 实体（引用式） |
| 阶段 3 F29 Supervisor 调度 | 依赖 Agent 库（按能力调度） |

**编号口径声明**：F39 为 Agent 化升级链新增模块（F26→F27→F28→F39→F29），不占用既有业务模块变体编号。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由（含备选否决） |
|---|------|------|-------------------|
| D1 | skill 绑定时机 | 上传时显式指定（默认不启用）+ 编辑页可改 + 「应用到全部」 | 上传当下意图最清晰；默认不启用符合「AI 自动化默认关闭」铁律，杜绝幽灵注入。否决：默认全部可用（违反铁律）/创建 Agent 时指定（决策瘫痪）/仅编辑页指定（可发现性差） |
| D2 | 函数选择 UI | 分组 checkbox 列表（writing/检索/审计/项目 + 描述，>10 加搜索）；内置只读、自定义可编辑 | 白名单是多选语义；分组 checkbox 比下拉直观；内置锁定避免「改坏了怎么恢复」二次负担 |
| D3 | 自定义函数 | 不做 | 心智负担 > 收益；注册表是产品资产 |
| D4 | 白名单确定性强制 | 装配层按 tool_ids/skill_ids 过滤后交付 LLM | 行为差异化从「概率」变「确定」；与 deepagents harness `tools` 参数天然契合 |
| D5 | skill 引用形态 | `skill_ids` 存 **skill 目录名**（英文 slug，N2 规则，#522 修订） | 与文件系统真源目录名（= frontmatter name）对齐，deepagents 原生 name 引用；删除级联按目录名精确清理（ADR-039）。否决：DB 主键字符串化（去表后无主键） |
| D6 | 装配能力 vs 消费接线 | 阶段 1 只交付能力（单元测试验证），不接运行时消费 | 分析文档 §6 演进路径分阶段；避免阶段 1 大改 F27 路径与双配置源 |
| D7 | 内置只读 | builtin/source 字段 + service 409 | 镜像 AgentTemplate is_default 保护；内置清单 = 产品资产 |
| D8 | Skill 存储形态 | **文件系统真源** `data_dir/skills/<name>/SKILL.md`（#522 修订） | 与 F19-skills **共用同一目录**：启动 `ensure_builtin_skills` 回补 + `migrate_skills_from_db` 一次性迁移旧表（ADR-039）；反查经 Agent.skill_ids 目录名过滤 |
| D9 | Agent/Skill 归属 | 全局定义（应用级）+ 项目引用（阶段 2 经 project config 落地） | Q0 拍板 A：方法论跨项目复用、与「设定库随项目走」分层不冲突；§2 实体无 project_id。否决：项目级定义（每项目重建，改动面大） |
| D10 | 与 AgentTemplate 关系 | 本期解耦，二期 roles 扩展为 Agent 引用 | Q1 拍板 A：避免一次大改双配置源。否决：本期打通（+3-5 人天改造模板 + 管线，F42 已证执行层复杂度） |

---

## 13. 验收标准

> 验收锚点 = 三 issue 验收要点合并，按子域划分。命令以 `backend\.venv\Scripts\python.exe -m pytest`（或 `uv run python -m pytest`）执行。

### F39 后端核心（#258）

| M | 验收 | 验证 |
|---|------|------|
| M1 | Agent/Skill 实体 CRUD（列表/详情/创建/更新/删除）API 契约全绿；同名 422、非法 id 404 | `pytest tests/unit/test_agent_service.py tests/unit/test_skill_service.py tests/integration/test_agents_api.py tests/integration/test_skills_api.py` |
| M2 | 工具目录 = 完整 6 工具（含 save_draft）+ group 分组；`GET /agents/tools` 不被 `/{agent_id}` 吞 | `pytest tests/unit/test_tool_catalog.py tests/integration/test_agents_api.py -k tools` |
| M3 | 白名单装配确定性：`tool_ids` 只 build 命中工具、`skill_ids` 只拼命中 skill（base 前 skill 后）；`None` 向后兼容 | `pytest tests/unit/test_agentic_whitelist.py` |
| M4 | 内置 seed 幂等：启动后 6 Agent 落库 + 6 Skill 文件回补就绪，重复启动不重复插入/写入 | `pytest tests/integration/test_builtin_seed.py` + 手工 `inkflow agent list`/`inkflow skill list` |
| M5 | 内置只读（PATCH/DELETE 409）；被引用 user skill 删除级联清引用 | `pytest` 服务层 + 端点契约用例 |

### F40 skill 上传绑定（#259）

| M | 验收 | 验证 |
|---|------|------|
| M6 | 上传：frontmatter 解析（name/description/tags）+ 内容预览；格式非法/同名 422 提示 | `pytest tests/integration/test_skills_api.py` + 前端 store/组件测试 |
| M7 | 上传时绑定：显式指定 Agent（默认不勾选 + 可搜索 + 「应用到全部」）；管理列表（来源/反查）；删除确认列影响面 | 前端组件测试 + E2E `上传→绑定→引用视图→删除确认` |

### F41 自定义 Agent 编辑（#260）

| M | 验收 | 验证 |
|---|------|------|
| M8 | Agent 管理列表（内置只读/自定义可编辑）+ 创建/编辑页（基本信息 + prompt + 分组 checkbox + skill 绑定 + 模型/温度覆盖） | 前端 store/组件测试 + 手工 `inkflow agent show` |
| M9 | 双向视图（Agent 看工具/skill、skill 看引用 Agent）+ 删除确认 | E2E `创建→编辑→函数/skill 白名单展示→删除确认` |

### 完成门禁

- 三层测试全绿（unit/integration/e2e 独立 job）+ 覆盖率达标（模块 ≥80%）
- CLI 手工验证闭环：`inkflow agent list`/`inkflow agent show --id N`/`inkflow skill list` 三命令输出正确
- #258/#259/#260 在各自 PR 合入时关闭（F39 后端 `Closes #258`；F40 `Closes #259`；F41 `Closes #260`——分 issue 分别 close，非合并 close）

---

## 待澄清问题（≤3，留给用户拍板）

### Q0：Agent/Skill 是否全局定义 + 项目引用？　✅ 已确认（用户拍板：选项 A，2026-08-16）

**用途**：决定 Agent/Skill 实体的归属粒度——是「应用级全局」（跨项目复用，「我的润色师」不每项目重建）还是「项目级」（每项目独立配置）。影响数据模型的 scope 字段与阶段 2 的项目引用设计。

| 选项 | 说明 |
|------|------|
| A（推荐） | **全局定义（应用级）+ 项目引用**：Agent/Skill 全局唯一，项目经 config 选择 Agent（阶段 2 落地项目引用字段）；skill 是「方法论」非「项目数据」，与「设定库随项目走」不同层不冲突 |
| B | 项目级定义：Agent/Skill 随项目走，每项目独立重建（与设定库同层） |

**建议**：A。分析文档 §5.1 与 §6 演进路径均按全局定义设计；「设定库随项目走」是已拍板先例，但 skill=方法论、角色/世界观=项目数据，分层不冲突。**影响**：A 方案 §2 实体无 project_id 字段、阶段 2 项目引用走 config；B 方案需加 project_id 列 + 全部 CRUD 挂项目上下文，改动面大。

### Q1：本期是否与 AgentTemplate 解耦？　✅ 已确认（用户拍板：选项 A，2026-08-16）

**用途**：决定本期是否改造 AgentTemplate（roles 四角色 → 任意 Agent 引用）。影响 F39-F41 的边界与阶段 2 排期。

| 选项 | 说明 |
|------|------|
| A（推荐） | **本期解耦**：F39-F41 只做 Agent/Skill 实体 + 装配能力，不动 AgentTemplate；二期 AgentTemplate.roles 扩展为 Agent 引用（模型/温度覆盖保留） |
| B | 本期打通：AgentTemplate.roles 直接引用 Agent 实体，一次性改造双配置源 |

**建议**：A。分析文档 §3「本期解耦、二期扩展，避免一次大改双配置源」；Agent 管「能力边界」与模板管「模型/温度」是两个正交维度，一次打通风险高（F42 已证执行层改造的复杂度）。**影响**：A 方案本期无 AgentTemplate MODIFY、Agent 暂无运行时消费（能力以单元测试验证）；B 方案需 +3-5 人天改造 AgentTemplate + 管线装配。

---

> **Spec 变更记录**：v1.0 初稿（2026-08-16）→ v1.1（2026-08-16，Q0=A / Q1=A 拍板定稿，留痕见头部 Spec 变更行 + §12 D9/D10）→ v1.2（2026-08-20，#522 skill 存储架构重构去表，留痕见头部 Spec 变更行 + §12 D5/D8）。

## 14. 动作确认

> 每个端点/命令的完整状态流表（基于 §3 + §4 + §5 + §7 事实，不重复）。

### 14.1 端点状态流

| 端点 | 前置条件 | 动作/状态转换 | 成功 | 失败 | 边界 |
|------|---------|--------------|------|------|------|
| GET /api/v1/agents | — | Agent 列表 | 200 {items, total} | — | builtin 标记（内置/自定义分流） |
| GET /api/v1/agents/tools | — | 工具目录（勾选 UI 数据源） | 200 {items: [{name, description, group, input_schema}]} | — | 路由须声明在 /agents/{agent_id} 之前（顺序匹配，否则 tools 被吞进 path 404） |
| POST /api/v1/agents | 名称唯一 | 创建自定义 Agent + 白名单引用校验（tool_ids 目录内/skill_ids 目录名存在） | 201 完整实体 | 422（同名 AgentNameConflictError / ToolReferenceError / SkillReferenceError） | 自定义 Agent role_key 服务层分配（v1.5，name slug 化 + 冲突后缀） |
| GET /api/v1/agents/{agent_id} | Agent 存在 | 详情 | 200 完整实体 | 404（不存在/非法 id，_parse_id 语义） | — |
| PATCH /api/v1/agents/{agent_id} | Agent 存在 | 部分更新（exclude_unset） | 200 完整实体 | 404；409（内置 AgentBuiltinError）；422 | 内置只读 |
| DELETE /api/v1/agents/{agent_id} | Agent 存在 | 删除自定义 Agent | 204 | 404；409（内置） | 本期无 project/template 引用面 |
| GET /api/v1/skills | — | Skill 列表（含反查 agent_ids） | 200 {items, total} | — | — |
| POST /api/v1/skills | content frontmatter 合法 | frontmatter 后端解析 + 写文件（data_dir/skills/） | 201 完整实体（id=name 兼容层） | 422（frontmatter 缺失 name/description 或 name 格式非法 / 同名 SkillNameConflictError） | 上传时显式绑定 Agent（D1 默认不勾选） |
| GET /api/v1/skills/{skill_name} | skill 存在 | 详情（含反查） | 200 完整实体 | 404「Skill 不存在」（不存在/非法，非 422） | — |
| PATCH /api/v1/skills/{skill_name} | skill 存在 | 部分更新（content 写回文件） | 200 完整实体 | 404；409（内置 SkillBuiltinError「内置 skill 只读」） | source=builtin 只读 |
| DELETE /api/v1/skills/{skill_name} | skill 存在 | 被引用 → 服务层先清所有 Agent.skill_ids 引用（list_agents_by_skill 反查 + 批量 update）→ 删目录 | 204 | 404；409（内置） | 级联清引用由服务层显式（JSON 列无 FK，不依赖 FK CASCADE）；前端先经 agent_ids 确认影响面 |
| POST /api/v1/skills/{skill_name}/duplicate | skill 存在 | 复制（新名 f"{name}-copy"） | 201 完整实体 | 404；422（同名冲突） | — |

### 14.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow agent list [--json] | 内核就绪 | 列 Agent（name + description + builtin 标记） | 退出码 0 + 信封 {items, total} | 退出码 1（内核启动失败/HTTP 错误） | 恒经 HTTP（F38，区别于 F26 tools list 本地豁免）；≠ agent template list / tools list |
| inkflow agent show --id N [--json] | Agent 存在 | 详情（system_prompt + tool_ids + skill_ids + 模型/温度覆盖） | 退出码 0 | 404 → 退出码 1 | — |
| inkflow skill list [--json] | 内核就绪 | 列 Skill（name + source + 被引用 Agent 数） | 退出码 0 | 退出码 1 | 单数（区别于 F19-skills 复数，文件系统导入） |

### 14.3 验收锚点

- A1：Agent/Skill 实体 CRUD 契约全绿（同名 422、非法 id 404，M1）
- A2：工具目录 = 完整 6 工具（含 save_draft）+ group 分组；GET /agents/tools 不被 /{agent_id} 吞（M2）
- A3：白名单装配确定性：tool_ids 只 build 命中工具、skill_ids 只拼命中 skill（base 前 skill 后）；None 向后兼容（M3）
- A4：内置 seed 幂等：6 Agent 落库 + 6 Skill 文件回补，重复启动不重复插入/写入（M4）
- A5：内置只读（PATCH/DELETE 409）；被引用 user skill 删除级联清引用（M5）
- A6：CLI 三命令手工验证闭环（完成门禁）
