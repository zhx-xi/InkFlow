# F58: Chat Agent 层级化工具矩阵 + 域×CRUD Scope 授权（agent-tool-scope）功能规格

> **端**: backend + frontend（GUI Agent 编辑对话框）

**Spec 版本**: 1.0
**日期**: 2026-09-06
**依据**: 2026-09-06 架构讨论拍板（方案 D 分阶段混合）+ ADR-043（工具面分级授权）+ ADR-035（deepagents harness）+ #838（自定义 agent tool_ids 白名单）+ F43 P3（大纲三级层级不变量）
**所属阶段**: 0.13.0（Phase 1 = 工具矩阵 + scope 授权 + GUI；Phase 2 = A2 动态重绑定，触发条件见 §7，本期不做）
**关联 ADR**: [ADR-050](../../adr/agent/ADR-050.md)（本 feature 的决策记录）
**参考**: `specs/f26-agent-tools/spec.md`（工具基础设施 v1.1）、`specs/f19-gui/agent.md`（Agent 编辑页交互）
**状态**: 📝 草案（spec/ADR 先行合入，实现批次另行排期）

---

## 1. 概述

### 1.1 问题

Chat agent 工具面（`infrastructure/agent/tools/`）现状三个结构性缺陷：

1. **大纲层级被压成参数**：`create_outline` 用 `level` 参数区分整本/卷/章（`setting_write_tools.py:69`，默认 `"overall"` 是陷阱值），且 `level=chapter` 要求 LLM 先持有卷纲 UUID 作 `parent_id`——但工具面**没有任何大纲读工具**，LLM 拿不到父 id，层级写入实际不可达。
2. **情节点工具面空白**：章情节点（plot points）有完整 REST API（`api/routers/outlines.py` 17 端点）与 CLI（`inkflow outline point`），但 agent 工具面无任何对应工具，只能靠 generate 一次性落库，无法精细维护。
3. **授权粒度与工具名绑死**：自定义 agent 的 `tool_ids` 白名单（#838）按工具名逐个勾选，26 个工具平铺，无"按功能域 × 操作类型"授权表达；工具扩到 40+ 后 GUI 勾选列表与白名单校验都不可维护。

### 1.2 交付（Phase 1）

- **大纲域层级化工具矩阵**：写工具按层拆（消除 `level` 参数陷阱 + 父级按名解析），补大纲读工具与情节点 CRUD。
- **其他域补真实读缺口**（list/get），不机械对齐大纲矩阵（见 ADR-050 §2 决策 4）。
- **grants 授权模型**：`域 × {read, write, delete}` 矩阵替代 `tool_ids`，经映射表物化为具体工具列表；存量数据一次性迁移。
- **GUI scope 勾选矩阵**：AgentEditDialog 工具勾选改为 GitHub API-key 式权限矩阵。
- **保持双闸**：delete scope 只控制工具暴露；运行时 ask_once 会话确认（ADR-043）叠加不变。

### 1.3 边界声明

- **不含** Phase 2（A2 发现式动态重绑定），仅写入触发条件（§7）。
- **不含** dispatcher 式元工具（A1，ADR-050 明确否决：丢失 per-tool input_schema 校验）。
- **不含** MCP 工具面改动（MCP 已是 `manage_*` 聚合形态，与本 feature 解耦）。
- **不含** REST API / CLI 改动（层级与情点能力已在 F11/F43 P3 存在，本 feature 是工具面镜像）。

---

## 2. 数据模型

### 2.1 grants 授权模型（`domain/models/agent_grants.py` 新增）

```python
class ToolDomain(StrEnum):
    """功能域枚举（scope 矩阵行）。"""
    OUTLINE = "outline"
    CHARACTER = "character"
    WORLD = "world"          # 世界观条目 + 地图
    TIMELINE = "timeline"
    FORESHADOWING = "foreshadowing"
    MEMORY = "memory"
    WRITING = "writing"      # generate/continue/revise/save_draft
    AGENT_CHAIN = "agent_chain"

class ToolOp(StrEnum):
    """操作类型（scope 矩阵列）。"""
    READ = "read"
    WRITE = "write"
    DELETE = "delete"

class GrantEntry(BaseModel):
    domain: ToolDomain
    ops: list[ToolOp] = []   # 空列表 = 该域无授权
```

Agent 实体变更（`agent_entity_service.py` 现 `tool_ids: list[str]`）：

- 新增 `grants: list[GrantEntry]`（序列化存 JSON 列，镜像 `tool_ids` 的 LenientJSON 形态）。
- **迁移语义**（ADR-050 §3）：`tool_ids` 列保留为兼容读取口，读取时若 `grants` 为空且 `tool_ids` 非空 → 按反查表推断 grants；写入路径只写 `grants`。

### 2.2 GRANT_TOOL_MAP 映射表（`infrastructure/agent/tools/registry.py` 新增，唯一真相源）

`(domain, op) -> [tool_name]`，物化时展开。工具命名规范：`{动词}_{对象}`，对象名承载层级/子资源（`create_volume_outline`、`create_plot_point`），**不使用点号**（OpenAI 函数名仅 `[a-zA-Z0-9_-]`）。

### 2.3 大纲域工具矩阵（Phase 1 形态，替代现 create/update/delete_outline）

| 工具 | 域·操作 | 关键参数 | 说明 |
|------|--------|---------|------|
| `list_outlines` | outline·read | `level?`, `search?` | 返回 id/名/层级/父链摘要（volume 附关联卷标识），解决父 id 发现 |
| `get_outline` | outline·read | `outline_id` | 详情（含情节点/弧线摘要可选） |
| `create_overall_outline` | outline·write | `name`, `description?` | 无 level/parent 参数；已有整本根 → 422 语义透传 |
| `create_volume_outline` | outline·write | `name`, `volume_name?`/`overall?` | 父=整本根，服务层自动挂链（复用 outline_service 层级校验） |
| `create_chapter_outline` | outline·write | `name`, `volume_outline_name` | **父按卷纲名解析**（内部查 UUID；重名 → 报错列出候选），不再要求 LLM 持有 UUID |
| `update_volume_outline` / `update_chapter_outline` | outline·write | `outline_id` + 可改字段 | 不提供 overall update（整本根名称改动走 GUI；LLM 改根属误操作高发区） |
| `delete_outline` | outline·delete | `outline_id` | 保持现有通用形态（id 唯一定位，层级无关）+ ask_once 不变 |
| `list_plot_points` | outline·read | `outline_id` | position 升序 + arc_name |
| `create_plot_point` | outline·write | `outline_id` 或 `chapter_outline_name`, `name`, `type?`, `description?`, `arc?` | 支持章纲名解析定位 |
| `update_plot_point` | outline·write | `plot_point_id` + 可改字段 | 镜像 PATCH 语义（arc_id "" 清归属） |
| `delete_plot_point` | outline·delete | `plot_point_id` | ask_once 确认（入核心删除工具形态，is_core=True） |

> 包装对象均为既有服务：`OutlineService.create_outline/update/delete`（含 P3 层级校验 `outline_service.py:172-184`）、`PlotPointService`（F11 §3.3）。**零新增领域服务方法**；父级名解析是工具层薄逻辑（list + 唯一匹配），同名歧义报错交还 LLM 消歧。

### 2.4 其他域读缺口补齐（Phase 1，只补真实洞）

| 工具 | 域·操作 | 现状 |
|------|--------|------|
| `get_character` | character·read | 缺（现只有 search_characters） |
| `list_world_settings` / `get_world_setting` | world·read | 缺（现无世界观读工具） |
| `list_foreshadowing` | foreshadowing·read | 半缺（check_foreshadowing 只覆盖未回收视角） |
| `get_foreshadowing` | foreshadowing·read | 缺 |
| 时间线/地图/记忆读 | timeline/map/memory·read | 已有（list_timeline_events、list_maps、memory_list）——**不重复造** |

> 写/删面维持现状（create/update × character/world/timeline/foreshadowing/map + memory add/update + delete 7 核心）。「层级/子资源 × CRUD」全矩阵**不对其他域展开**——角色/时间线/伏笔/记忆是平面实体，硬凑产生空格子（ADR-050 §2）。

### 2.5 不变项

- `ToolSpec` 三字段模型（F26 §2.1）不变；`is_core`/`allow_custom_agent` 标志语义不变（核心删除工具仍不进 scope 矩阵勾选，由 delete op 授权控制挂载）。
- 删除类运行时 ask_once 会话授权（ADR-043）叠加不变 = 双闸。
- `search_characters` 等既有读工具名**不改名**（存量白名单兼容成本最小化）。

---

## 3. API 契约

### 3.1 Agent CRUD 端点（扩展，无新端点）

`POST/PUT /agents`（F42 自定义 Agent 数据面）：

- 请求体新增 `grants: list[{domain, ops}] | None`；`tool_ids` 保留为弃用别名（同传 → 422）。
- 校验：grants 的 domain ∈ ToolDomain、ops ∈ ToolOp（非法 → 422 `AgentToolIdsError` 复用或新 `GrantValidationError`）。
- 响应：`grants` + 派生字段 `resolved_tool_names: list[str]`（映射表展开结果，GUI 详情展示用）。

### 3.2 工具目录端点

`GET /agents/tools/catalog`（现挂载）响应升级：平铺列表 → 按 `{domain, op, name, description}` 结构化返回（GUI 矩阵渲染数据源；`is_core=True` 条目不进目录）。

### 3.3 物化路径

`build_tools_by_ids` → 新签名 `build_tools_by_grants(grants, deps, project_id)`：GRANT_TOOL_MAP 展开 → 目录过滤 → 与现有按名过滤拼接逻辑复用。**旧 `build_tools_by_ids` 保留至迁移完成**（内部先反查 grants 再走新路径）。

---

## 4. GUI 契约（f19-gui/agent.md 增量）

AgentEditDialog 表单「工具 checkbox 分组」替换为 **scope 矩阵**：

```
            读     写     删
大纲        ☑     ☑     ☐
角色        ☑     ☐     ☐
世界观      ☑     ☑     ☐
...
```

- 行 = ToolDomain（i18n 词条：`agent.scope.domain.outline` 等，F57 双层键体系）；列 = read/write/delete。
- 列头 tooltip 说明删除列语义（"暴露删除工具；每次删除仍需会话确认"）。
- 详情弹窗展示勾选矩阵回显 + resolved 工具数（不展示展开后的工具名清单，防噪声；可展开查看）。
- 内置 Agent 卡片沿用现状，但其 `tool_ids` 定义同步改 grants（内置模板 `agent_entity_service.py:79-154`）。
- 旧数据兼容：grants 缺失但 tool_ids 存在 → 反查推断后渲染。

---

## 5. 迁移契约（⚠️ 关键，存量数据资产保护）

1. **DB**：`agents.tool_ids` 列保留（不删），新增 `grants` JSON 列（默认 `[]`/NULL）。轻量幂等迁移（create_all + 幂等 ALTER 先例）：新列存在即跳过。
2. **推断规则**（反查表 = GRANT_TOOL_MAP 的逆映射 + 改名映射）：
   - `create_outline`/`update_outline` → outline·write（含全部新写工具，层级由 LLM 按需选择，授权不区分层）
   - `delete_outline` 等核心删除工具：不在白名单语义内（is_core），不受迁移影响
   - 未识别名 → 忽略 + 诊断日志（不阻塞）
3. **读取路径统一入口**：`resolve_grants(agent) -> list[str]`（grants 优先，缺失时按 tool_ids 推断），API/GUI/物化三处同源，避免双真相。
4. **校验路径**：`_validate_tool_ids`（`agent_entity_service.py:173`）→ `_validate_grants`；旧 API 请求仍接受 tool_ids 时先转换再校验。

---

## 6. 测试策略（TDD，各层 RED）

| 层 | 内容 |
|----|------|
| 单元 | GRANT_TOOL_MAP 完整性（每工具恰属一个 (domain,op)，孤儿/重复 → fail）；grants 模型校验；`resolve_grants` 推断规则（含 create_outline→三新工具的改名映射）；层级包装器参数 schema（无 level/parent 字段）；父级名解析（唯一/无匹配/重名歧义三态） |
| 集成 | Agent CRUD grants 读写 + 旧 tool_ids 兼容转换 + 422 路径；catalog 端点结构；build_tools_by_grants 物化矩阵（含 scope 未授予 → 工具不在列） |
| 契约 | 情节点工具包装 PlotPointService 调用形状；delete 双闸（scope 授予 + ask_once 未确认 → 拒绝） |
| 前端 | 矩阵渲染/勾选/回显/旧数据反查渲染；详情弹窗 resolved 数 |
| E2E | agent 页 scope 勾选保存 → 新会话生效（fake LLM，ADR-047） |

覆盖率门禁按 ADR-027 口径不特殊化。

---

## 7. Phase 2 触发条件（本期不做，ADR-050 §4 预备案）

满足任一即启动评审：① 某 agent 常驻工具面 > ~45 个；② 本地小上下文模型（BYOK）出现 schema 挤占导致选错/漏调实测；③ 工具面 > 8k prompt tokens 实测。

Phase 2 形态 = **A2 发现式动态重绑定**：暴露域元工具（`outline_tools()` 返回该域 scope 展开清单）→ 模型调用后 agent loop **下一轮注入该域真实 schema**（`harness.py` 静态装配环改造）。**明确否决 A1**（元工具 + 通用 dispatcher：args 退化为自由 JSON，丢失 per-tool Pydantic 校验与 F57 按工具归因埋点）。

---

## 8. 验收标准（Phase 1）

- N1: LLM 不持有任何 UUID 的前提下，可完成"为《X》第三卷卷纲下新建章纲+3 个情节点"全链路（chat agent 实测，父级名解析）。
- N2: `level` 参数从大纲写工具 schema 中消失；整本根默认陷阱不复存在（工具形态天然无该字段）。
- N3: 自定义 agent 保存 grants 矩阵 → 新会话工具面 = 映射表展开结果（多 agent 交叉验证 read/write/delete 三列）。
- N4: 存量自定义 agent（仅 tool_ids）不迁移即可正常使用，GUI 打开即见反查后的矩阵。
- N5: delete 列勾选后 ask_once 确认流仍触发（双闸）。
- N6: MCP 工具面、REST/CLI 行为零 diff。

---

## 9. 快速导航

- §2.3 大纲矩阵 ↔ issue：工具矩阵批次
- §2.4 其他域读缺口 ↔ issue：读缺口批次
- §2.1/§5 grants+迁移 ↔ issue：grants 数据面批次
- §4 GUI ↔ issue：scope 矩阵 UI 批次
- §7 Phase 2 ↔ issue：预备案（无排期）
</content>
