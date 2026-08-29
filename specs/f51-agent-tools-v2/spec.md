# F51: AI 工具面全量注册（阶段① 读+写）功能规格

**Spec 版本**: 1.0
**日期**: 2026-08-29
**依据**: adr/ADR-043.md（工具面矩阵 §1 + 分阶段 §4）+ PRD §6.1 + 源码枚举（2026-08-29 核实）
**所属阶段**: 0.12.1（工具面扩展第一批）
**关联 Issues**: #766（0.12.1）
**依赖**: ✅ F26 agent-tools（ToolSpec/Tool 模型 + build_reader_tools）· ✅ #748 设定库写工具（build_setting_write_tools）· ✅ F32/F33（相关服务已合入）· ✅ ADR-043（已合入 main）
**参考 ADR**: adr/ADR-043.md（工具面矩阵 + 删除授权模型 + 分阶段）
**状态**: 待实现 🔲

> **模块类型声明**: 本 spec 为 ADR-043 落地细化的**增量契约**（非新变体），沿用 F26「deepagents 集成 + 工具定义型」的既有工具装配模式（Tool/ToolSpec/动态 deps 工厂），不加新实体表、不加新业务端点——只扩工具注册面与装配点。编号 F51 依据 ADR-019 Feature 表下一个空位（F49/F50 已占，F51 未被占）。

> **精简契约式**（2026-08-29 用户拍板）：本 spec 为既有模块（F26 工具面）的增量扩展，采精简契约结构（§1-§5），不套完整 13 节。

---

## 1. 工具面清单（ADR-043 §1 矩阵 + 源码枚举）

现状已注册工具（2026-08-29 源码核实）：`search_characters` / `check_foreshadowing` / `get_prior_summary` / `audit_chapter` / `count_words`（reader_tools `_TOOL_SPECS`）+ `save_draft`（save_draft_tool）+ `create_character` / `create_world_setting` / `create_outline`（setting_write_tools）。

| 域 | 工具 | 授权 | 状态 | 源码（service 方法核实） |
|---|---|---|---|---|
| 设定库·角色 | update_character | 写 | **新增** | character_service.update_character(character_id, CharacterUpdate) |
| 设定库·世界观 | update_world_setting | 写 | **新增** | world_service.update_setting(setting_id, WorldUpdate) |
| 设定库·大纲 | update_outline | 写 | **新增** | outline_service.update_outline(outline_id, OutlineUpdate) |
| 设定库·地图 | list_maps / create_map / update_map | 读/写 | **新增** | map_service.list_maps / create_map / update_map |
| 设定库·时间线 | list_timeline_events / create_timeline_event / update_timeline_event | 读/写 | **新增** | timeline_service.list_events / create_event / update_event |
| 设定库·伏笔 | create_foreshadowing / update_foreshadowing | 写 | **新增** | foreshadowing_service.create(ForeshadowingCreate) / update(id, ForeshadowingUpdate) |
| 记忆 | memory_list / memory_add / memory_update | 读/写 | **新增** | memory_service.list_preferences / create_preference / update_preference |
| 写作 | generate / continue / revise | 写 | **新增** | writing_service.generate_chapter / continue_writing / revise_content |
| agent 链 | agent_run / agent_call | 执行 | **新增** | agent_service.execute(PipelineExecuteRequest)（run）；call 语义见 §2.9 待拍板 |
| agent 链 | 修改 / 删除配置 | — | **❌ 不给**（D5） | 不在本期 |

> 🔒 删除授权工具（delete_* / memory_remove 等）一律**不注册、不实现**（阶段②，本批禁做）。
> 工具命名已核对与既有 `_TOOL_SPECS`（reader/save_draft/setting_write）无冲突。

---

## 2. 各新增工具 ToolSpec 契约

统一约定（镜像既有工具，见 references 下 reader_tools/setting_write_tools 注释）：
- 每个工具 = `ToolSpec(name, description, input_schema)` + async `func(*args) -> str`（JSON 信封）。
- `project_id` 一律**不出现在 schema**——装配期由 deps.expected_project_id 闭包绑定（#680/#748 先例，LLM 不自报，防编造全零 UUID 落孤儿数据）。
- 成功信封：`{"ok": true, ...}`；失败信封：`{"ok": false, "error": "<异常消息>"}`；工具内部捕获一切 Exception 不抛出。
- 写类工具**成功/失败均落审计**（audit_service.record，actor="agent:chat"，审计调用自身异常静默）。
- func 签名保留可选 `project_id` shim（镜像 #748），但 schema 不含该键。

### 2.1 设定库·角色
- **update_character**：`description`="更新项目内角色设置（部分更新，未传字段保持不变）"，args=CharacterUpdate 字段（name?/personality?/background?/goals?/group_ids?），成功 `{"ok": true, "character_id": "<id>", "name": "<name>"}`。

### 2.2 设定库·世界观
- **update_world_setting**：`description`="更新项目内世界观设定条目（部分更新）"，args=WorldUpdate 字段（name?/category?/content?/parent_id?），成功 `{"ok": true, "setting_id": "<id>", "name": "<name>"}`。

### 2.3 设定库·大纲
- **update_outline**：`description`="更新项目内大纲条目（部分更新）"，args=OutlineUpdate 字段（name?/description?/sort_order?/level?/parent_id?/chapter_id?），成功 `{"ok": true, "outline_id": "<id>", "name": "<name>"}`。

### 2.4 设定库·地图（读+写）
- **list_maps**：读；`description`="列出项目内地图（可按根位置过滤/仅顶层）"，args(root_location_id?/top_level_only?)，成功 `{"ok": true, "data": [...]}`。
- **create_map**：写；`description`="创建项目内地图并写入设定库，返回新地图 id；同名活动地图会失败"，args(name/description?/root_location_id?)，成功 `{"ok": true, "map_id": "<id>", "name": "<name>"}`。
- **update_map**：写；`description`="更新地图元数据（部分更新；不换图）"，args(map_id/name?/description?)，成功 `{"ok": true, "map_id": "<id>"}`。

### 2.5 设定库·时间线（读+写）
- **list_timeline_events**：读；`description`="列出项目内时间线事件（可按关键字搜索/排序）"，args(search?/sort_by?)，成功 `{"ok": true, "data": [...]}`。
- **create_timeline_event**：写；`description`="创建时间线事件并写入设定库，返回新事件 id"，args(title/description?/time_value?/narrative_position?/location_id?)，成功 `{"ok": true, "event_id": "<id>", "title": "<title>"}`。
- **update_timeline_event**：写；`description`="更新时间线事件（部分更新）"，args(event_id/title?/description?/time_value?/narrative_position?)，成功 `{"ok": true, "event_id": "<id>"}`。

### 2.6 设定库·伏笔（写；读已有 check_foreshadowing）
- **create_foreshadowing**：写；`description`="创建伏笔并写入设定库，返回新伏笔 id；创建即 open"，args(title?/content/status?/priority?/location_id?)，成功 `{"ok": true, "foreshadowing_id": "<id>"}`。
- **update_foreshadowing**：写；`description`="更新伏笔（部分更新）"，args(foreshadowing_id/content?/status?/priority?)，成功 `{"ok": true, "foreshadowing_id": "<id>"}`。

### 2.7 记忆（读+写）
- **memory_list**：读；`description`="列出项目内记忆偏好（可按分类过滤）"，args(category?)，成功 `{"ok": true, "data": [...]}`。
- **memory_add**：写；`description`="添加一条记忆偏好并写入记忆库，返回新偏好 id"，args(category/pattern/note?)，成功 `{"ok": true, "preference_id": "<id>"}`。
- **memory_update**：写；`description`="更新一条记忆偏好（部分更新）"，args(preference_id/category?/pattern?/note?)，成功 `{"ok": true, "preference_id": "<id>"}`。

### 2.8 写作（写）
- **generate**：写；`description`="根据章节上下文生成正文（写入章节内容）"，args(request 对应 WritingRequest 字段)，成功 `{"ok": true, "chapter_id": "<id>", "word_count": N}`。
- **continue**：写；`description`="续写正文"，args(ContinueWritingRequest 字段)，成功 `{"ok": true, "chapter_id": "<id>", "word_count": N}`。
- **revise**：写；`description`="润色/改写正文"，args(RevisionRequest 字段)，成功 `{"ok": true, "chapter_id": "<id>", "word_count": N}`。

### 2.9 agent 链（执行；修改/删除配置不给 —— D5）
- **agent_run**：`description`="启动一次 agent 链管线执行"；args=PipelineExecuteRequest 字段（project_id?/pipeline? 等，依 DTO）；成功 `{"ok": true, "execution_id": "<id>", "status": "pending"}`。
- **agent_call**：执行单 agent 调用。⚠️ **签名待拍板**（见「待拍板」节）——默认建议 wrapper 直接调用 `agent_entity_service.get(list)` + 触发单 agent 执行，或复用 chat agent 单次 invoke；实现前须确认语义（本 spec 暂记为「待拍板：单 agent 调用语义」，体先行 run）。

---

## 3. 装配点（工具注入位）

新增工具按域**各自独立模块**（`infrastructure/agent/tools/<域>_tools.py`），每模块含：Params Pydantic 模型、ToolSpec/常量、Deps dataclass、`build_<域>_tools(deps) -> list[Tool]` 工厂。装配点四处：

| 装配点 | 现状 | 本批注入 |
|---|---|---|
| `api/deps_chat_agent.py::get_chat_agent_service` | `tools=[*reader_tools, save_draft_tool, *setting_write_tools]` | 追加 `[*setting_update_tools, *world_rw_tools, *memory_tools, *writing_tools, *agent_tools]` |
| `api/deps.py`（re-export getters + build_*） | import build_reader_tools/build_save_draft_tool/build_setting_write_tools + 各 service getter | 追加新 build_* re-export + 确认 get_map_service/get_timeline_service/get_foreshadowing_service 存在 |
| `api/deps.py::get_agentic_writer_service` → `infrastructure/agent/agentic_writer.py::build_agentic_writer` | `build_reader_tools(include=tool_ids)` + save_draft | 追加新工具组（agentic writer 工具面同步扩） |
| `domain/models/agent_tools.py` | ToolSpec（无权限字段） | **本批零改动**（权限守卫见 §4，字段留阶段②） |

> 工具面装配原则：**chat 系统级 Agent 全量注入**；agentic writer 注入「设定库读+写+记忆读」为主，写作/agent链 工具视语义（写作类与 agentic writer 自身写正文重叠，**待拍板** §候选 C）。

## 4. 权限守卫接口（删除授权 → 阶段②，本批仅留接口声明）

删除授权模型（ADR-043 §2）本批**不实现**，仅在本 spec 声明接口契约，供阶段②（删除HITL）落地：

```python
# domain/models/agent_tools.py 阶段② 追加（本批禁实现）
@dataclass
class ToolAuth:
    permission: str  # "manual" | "ask_once" | "auto"  （ADR-043 §3 权限状态域）
```

- 阶段①所有新增工具均**非删除类**（读/写），`authorization=` 隐式全量放行，无删除守卫。
- 阶段②：删除类工具默认不注册；守卫读 per-conversation 授权状态决定挂载/触发 HITL（deepagents `__interrupt__`，复用 #456）。**本批禁实现 delete_* / memory_remove 等 + 分段控件**（brief 硬约束）。

## 5. 验收标准（M1-Mn）

- **M1** 各新工具契约测试全绿（注册 + 调用 ok 信封 + 落库断言 + 失败信封覆盖）——`pytest tests/unit/test_<域>_tools.py`；新增测试文件须登记 ci.yml 对应后端 job。
- **M2** 装配点注入测试：deps_chat_agent 新工具组进 `tools=[...]`（mock 断言 build_* 被调 + 返回 Tool 列表）；agentic_writer 同步注入。
- **M3** 回归：既有全仓测试零回归（unit + tests/cli 分命令跑）；覆盖率门禁（CI 口径 98.5/95.0，本地复刻不破线）；`ci_cd/check_file_length.py 900` 对 deps.py/agentic_writer.py/新模块全过（>900 才失败）。
- **M4** spec-only PR 合入后 #766 仍 OPEN（`Part of #766` 非 `Closes`）。

---

## 待拍板问题（≤3，入 PR body 同步）

- **Q1: agent_call 单 agent 调用语义**（agent 链 "call"，§2.9）——A. 复用 agent_entity_service.get/list（配置已存在）+ 触发单 agent 执行（推荐：语义最贴合「执行单 agent」）；B. 复用 chat agent 单次 invoke（轻量但非独立 agent 链）；C. 本批仅 agent_run，call 延迟。**建议 A**：本 spec 默认 A，正文按 A 定稿；实现须以拍板为准。
- **Q2: agentic writer 是否注入写作类工具（generate/continue/revise）**——写作类与 agentic writer 自身「写正文」能力重叠，注入会造成工具面冗余 + 诱发 agent 自我调用。A. agentic writer 只加「设定读+写+记忆读」，写作工具只给 chat 系统级 Agent（推荐）；B. 全量注入。**建议 A**。
- **Q3: 地图/时间线/伏笔 读工具命名与分页**——list_maps / list_timeline_events 沿用 reader_tools `_fetch_all_pages` 分页模式（limit=50 循环），不引新分页机制；**建议维持**（实现确认）。

> **关联**：ADR-043（工具面矩阵 + 分阶段）· Issue #766（0.12.1）· spec 依据 F26 agent-tools（装配模式复用）。
> **范围边界**：本 spec 只覆盖阶段① 读+写工具；删除授权（阶段②）与分段控件**不属本批**，勿实现。
