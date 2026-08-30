# F48: 知识图谱（knowledge-graph）— 功能规格
> **端**: cross

> **Spec 版本**: 1.2 | **日期**: 2026-08-19 | **依据**: Issue #478（用户拍板 D3）、PRD v2.1 §6.2 P1-01/P1-06、F9 spec（角色关系图谱）+ F36 spec（地图实体，第 15 变体范例）、Constitution P1-P6
>
> **Spec 变更**（1.1 → 1.2，2026-08-19 #479 契约定稿）：§5.5 由占位升级为具体契约——定时任务形态（进程内 asyncio loop + lifespan 启停 + 启动补跑）、设置三键（`kg_extract_enabled`/`kg_extract_interval_hours`/`kg_extract_method`，F32 settings 扩展）、RelationExtractionService（规则三规则集 + AI 模板提取 + 名称解析）、KnowledgeExtractScheduler（run_cycle 可单测 + 每周期重读设置）、extract 端点 + CLI + 设置页 KnowledgeExtractCard 契约、运行记录复用 extraction_runs（ExtractionType 第 7 值 KNOWLEDGE_RELATION，F14 既有 6 值断言同步改 7）。同步：§1.2 边界、§10 不在范围、§12 决策 12。**#479 实现以 §5.5 为唯一真相**；F48（本模块）交付范围不变。
>
> **Spec 变更**（1.0 → 1.1，2026-08-19 拍板）：Q1-Q3 全拍板——**Q1=A**（图谱页允许建角色↔角色关系写 knowledge_relations，聚合去重；C 迁移合并建 #495 挂 1.0.0）；**Q2=A**（图谱渲染定稿 @xyflow/react）；**Q3=A**（提取运行记录不保留；追加需求「统一日志页」建 #496 挂 1.0.0）。同步：§1.2 边界、§2.1 业务规则、§5.2 聚合、§5.4 前端、§8 文件结构、§10 不在范围、§11 依赖、§12 决策表（新增决策 9-11）、§13 验收、待澄清节全标 ✅。
>
> **所属阶段**: 0.10.1（UI/产品修复批，D3 前半「知识图谱：关系模型 + 可视化 + 手动修改」，估算 5-8 人天）
>
> **关联 Issues**: [#478](https://github.com/zhx-xi/InkFlow/issues/478)（本模块）· #480（知识图谱检索页，**另 issue，依赖本模块**）· #479（定时任务 AI/规则提取，**本 spec §5.5 契约（v1.2 定稿），挂靠方**）· #495（character_relations 迁移合并，**Q1-C 后续重构，1.0.0**）· #496（统一日志页，**Q3 追加需求，1.0.0**）· #174（F36 地图，实体来源之一）· #389（世界观分类，关联登记）
>
> **依赖**: ✅ F1（projects 表 + ProjectRepositoryProtocol）· ✅ F9（characters + character_relations，图谱合并来源 + 实体校验）· ✅ F10（world_settings 实体校验）· ✅ F11（outlines 实体校验）· ✅ F12（timeline_events 实体校验）· ✅ F13（foreshadowings 实体校验）· ✅ F36/F43 P2（maps + map_pins 实体校验）· ✅ F14（extractions/runs，原 rag tab 数据源——本模块改造其展示面；#479 定时提取挂靠 F14 提取服务）
>
> **参考 ADR**: [ADR-019](../../adr/ADR-019.md)（版本里程碑）· [ADR-002](../../adr/ADR-002.md)（六边形分层）· [ADR-003](../../adr/ADR-003.md)（Repository）· [ADR-004](../../adr/ADR-004.md)（Pydantic v2）· [ADR-012](../../adr/ADR-012.md)（错误处理）· [ADR-030](../../adr/ADR-030.md)（本地内核服务）
>
> **状态**: ✅ 已实现（PR #502 图谱 + #511 定时提取，2026-08-19）

---

## 1. 概述

为项目内六大设定实体（**角色 / 世界观条目 / 大纲 / 时间线事件 / 伏笔 / 地图 pin**）提供**跨实体关系图谱**：以通用关系表 `knowledge_relations`（实体-关系-实体）表达「角色↔世界观『属于』」「角色↔角色『关系』」「事件↔角色『参与』」等联系，在「知识图谱」tab 中以**图谱画布**可视化（节点=实体，边=关系），并支持**手动增删改关系**（CRUD 端点 + 前端 UI）。原「知识库 RAG」tab 改造为「知识图谱」（用户拍板 D3-2）；RAG 语义检索能力由新增检索页承接（#480，另 issue）。

**核心交付**：

```text
F9 现状:     character_relations 表（角色↔角色有向边）+ 角色 tab 关系管理
F48 增量:    新表 knowledge_relations（通用跨实体关系，含 source 来源标记）
             + 图谱聚合查询端点（合并 character_relations，去重显示）
             + 关系 CRUD（API + CLI + 前端）
             + 前端「知识图谱」tab（图谱画布：拖拽/缩放/点击详情/增删改）
             + 原「知识库 RAG」tab 改造（#480 检索页承接检索）
             + §5.5 #479 契约（v1.2 定稿：定时任务 + 规则/AI 提取；F48 只交付数据面与写入端口）
```

### 1.1 模块类型定位（第 21 变体「实体关系图谱型」）

按 AGENTS.md 模块类型谱系计数（F38=第 18 变体为最新无冲突基线；F20/F46 双占第 19；F44/F45 双占第 20），本模块为 **第 21 变体「实体关系图谱型」**：F9 CharacterRelation（单实体对关系表）的**泛化升级**——通用关系表 + 跨实体校验链 + 图谱聚合查询 + 图谱可视化表现层。与 F9 差异：F9 只表达角色↔角色（专用表 + 角色域内 CRUD），本模块表达**六类实体任意对**（通用表 + 图谱域 CRUD）并**只读合并** F9 角色边。

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ✅ 1 个：`knowledge_relations`（无 is_deleted——真删语义） |
| 新 API 端点 | ✅ 6 个（关系 CRUD + 图谱聚合查询） |
| 新 CLI 命令 | ✅ `inkflow knowledge` 组（graph 查询 + relation 子组 CRUD） |
| 核心机制 | ✅ 跨实体关系校验链（实体存在 + 同项目，服务层显式校验）+ 图谱聚合（合并 character_relations 去重）+ 图谱画布渲染 |
| 跨模块 MODIFY | ✅ F9 只读合并（character_relations 零改动）；F10-F13/F36 实体校验只读复用（零改动）；前端 library.tsx rag tab 改造 |
| 错误面 | KnowledgeGraphServiceError 子类 422 / KnowledgeRelationNotFoundError 404 |

### 1.2 边界声明

- **不做 entity_relations 之外的冗余**：关系只存 `knowledge_relations`（+ 既有 `character_relations` 只读合并），不在角色/世界观等实体表加关系字段（避免「JSON 嵌入 + 关系表」双份真相——F9 §1 同款原则）
- **character_relations 保留不动，双轨写入（Q1=A 拍板）**：角色页关系管理继续写 character_relations；图谱页也可建角色↔角色关系（写 knowledge_relations）；图谱聚合合并两表 + 同键去重（§5.2）；长期迁移合并建 #495（1.0.0，Q1-C 后续重构）
- **不做定时/自动提取（本模块）**：#479 另 issue——v1.2 已在 §5.5 定稿具体契约（定时任务 + 规则/AI 提取 + 设置页）；F48 只实现其数据面 + 写入端口（`bulk_create_relations`），不实现提取逻辑
- **不做检索页**：#480 另 issue（RAG 语义检索/向量检索 UI 承接）
- **不做图谱布局算法自研**：渲染选型 @xyflow/react（Q2=A 拍板，§5.4/§12 决策 7）
- **不做实体详情编辑**：图谱节点点击详情 = 只读摘要 + 跳转对应实体页（角色/世界观/大纲/时间线/伏笔/地图编辑均在各自既有页面）
- **删除语义**：`knowledge_relations` 为**新表，无 is_deleted 列**——删除 = **真删**（同 F36 拍板 D1=B/D7；普通实体删除收敛真删，归档仅会话保留，#211 关联登记）

---

## 2. 数据模型

### 2.1 knowledge_relations 表（实体-关系-实体）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK 自增 | 领域层 UUID 映射（F1 惯例） |
| project_id | int | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目（冗余存储，便于项目隔离；项目删除级联删除） |
| source_type | str | NOT NULL, 枚举 | 关系起点实体类型（EntityType 枚举：character/world/outline/timeline/foreshadow/map_pin） |
| source_id | int | NOT NULL, 已索引 | 关系起点实体主键（对应实体表 PK，**无 DB FK**——跨实体类型无法单列 FK，服务层显式校验） |
| target_type | str | NOT NULL, 枚举 | 关系终点实体类型（同上） |
| target_id | int | NOT NULL, 已索引 | 关系终点实体主键（同上） |
| relation_type | str | NOT NULL, 1-20 字符, 去空白 | 关系类型（自由文本，如「属于」「参与」「师徒」「伏笔指向」；受控词表归 #479 规则提取） |
| description | str | NOT NULL, DEFAULT "", ≤ 500 字符 | 关系说明（可空串） |
| source | str | NOT NULL, DEFAULT "manual", 枚举 | 关系来源：`manual`（手动创建，本模块）/ `ai`（#479 定时任务 AI/规则提取，**预留值，v1.0 不产生**） |
| created_at | datetime | NOT NULL | UTC |
| updated_at | datetime | NOT NULL | UTC，自动更新 |

**业务规则**：

1. **实体类型枚举**（EntityType）：`character`（characters 表）/ `world`（world_settings 表）/ `outline`（outlines 表）/ `timeline`（timeline_events 表）/ `foreshadow`（foreshadowings 表）/ `map_pin`（map_pins 表）——与六分类 tab 对齐（rag 除外，rag 是检索面非实体）
2. **跨实体无 DB FK（D2）**：source_id/target_id 无 ForeignKey 约束（跨 6 张表无法单列 FK）——实体存在性 + 同项目校验由**服务层显式执行**（§5.1 校验链），ORM FK 仅 project_id
3. **禁止自环**：`source_type == target_type AND source_id == target_id` → 422「关系两端不能是同一实体」（自环在图谱无意义且徒增噪音——F9 §2.3 同款规则）
3b. **允许角色↔角色（Q1=A 拍板）**：`character→character` 是合法关系（图谱页可建，写 knowledge_relations）——与 F9 character_relations 并存为双轨写入，图谱聚合去重收敛（§5.2）；长期迁移合并见 #495
4. **唯一约束**：`(project_id, source_type, source_id, target_type, target_id, relation_type)` 全唯一索引（v1.0 手动创建防重复；同键重复创建 → 422「该关系已存在」；#479 AI 提取将按此键做幂等去重）
5. **source 字段（#479 预留）**：v1.0 手动创建恒为 `manual`；`ai` 值保留给 #479 定时提取写入（§5.5）——v1.0 不限制读取（图谱聚合查询含全部 source）
6. **实体硬删 → 关系级联删除（D3）**：各实体真删（#211 语义）后，其作为 source/target 的 knowledge_relations 行须删除——服务层/项目删除钩子显式清理（生产连接 FK 不生效，D10=b 先例，§5.3）
7. **真删语义**：关系删除 = 物理删除，无 is_deleted、无 restore（F36 D1=B/D7 同款）

### 2.2 实体引用映射表（source_type/target_type → 实体表 + 校验 repo）

| EntityType | 实体表 | 校验来源（只读复用） | 图谱节点显示名 |
|------------|--------|----------------------|----------------|
| character | characters | F9 CharacterRepositoryProtocol（get 校验 + 项目归属） | Character.name |
| world | world_settings | F10 WorldRepositoryProtocol（get 校验 + 项目归属） | WorldSetting.name |
| outline | outlines | F11 OutlineRepositoryProtocol（get 校验 + 项目归属） | Outline.name |
| timeline | timeline_events | F12 TimelineRepositoryProtocol（get 校验 + 项目归属） | TimelineEvent.title |
| foreshadow | foreshadowings | F13 ForeshadowingRepositoryProtocol（get 校验 + 项目归属） | Foreshadowing.title |
| map_pin | map_pins | F36 MapRepositoryProtocol（get_pin 校验 + 项目归属，**经 pin→map→project 链路**） | MapPin.label |

> **⚠️ map_pin 校验链路（F43 P2 事实）**：map_pins 表本身无 project_id 列（所属项目经 map_id → maps.project_id 推导）——map_pin 实体校验 = `repo.get_pin(pin_id)` 非 None + 该 pin 所属 map 的 project_id == 目标项目（MapRepositoryProtocol 需暴露 pin 所属项目查询，实现期核对 F36 repo 现有方法，缺口则按 F15 补充端口先例扩展）。map_pin 节点也校验 map 存在（pin 孤儿 = map 硬删后未清理，404）。

### 2.3 领域模型（`domain/models/knowledge_graph.py`）

```python
class EntityType(str, Enum):
    """图谱实体类型枚举 — 六类设定实体（与 library.tsx 六分类 tab 对齐，rag 除外）."""
    CHARACTER = "character"
    WORLD = "world"
    OUTLINE = "outline"
    TIMELINE = "timeline"
    FORESHADOW = "foreshadow"
    MAP_PIN = "map_pin"


class RelationSource(str, Enum):
    """关系来源 — v1.0 手动创建；ai 值预留 #479 定时提取."""
    MANUAL = "manual"
    AI = "ai"          # 预留（#479），v1.0 不产生 ai 行


class KnowledgeRelation(BaseModel):
    """图谱关系领域实体 — 对应 knowledge_relations 表（有向边）.

    Attributes:
        id: 主键 UUID.
        project_id: 所属项目 UUID.
        source_type: 起点实体类型（EntityType）.
        source_id: 起点实体 UUID.
        target_type: 终点实体类型（EntityType）.
        target_id: 终点实体 UUID.
        relation_type: 关系类型（1-20 字符，去空白，自由文本）.
        description: 关系说明（≤ 500 字符）.
        source: 关系来源（manual/ai，v1.0 恒 manual）.
        created_at: 创建时间.
        updated_at: 最后更新时间.
    """
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    source_type: EntityType
    source_id: uuid.UUID
    target_type: EntityType
    target_id: uuid.UUID
    relation_type: str
    description: str = ""
    source: RelationSource = RelationSource.MANUAL
    created_at: datetime
    updated_at: datetime


class KnowledgeRelationCreate(BaseModel):
    """创建图谱关系请求 DTO — 六元组 + 可选描述.

    Attributes:
        source_type: 起点实体类型，必填.
        source_id: 起点实体 UUID，必填.
        target_type: 终点实体类型，必填.
        target_id: 终点实体 UUID，必填.
        relation_type: 关系类型，必填，1-20 字符，去空白.
        description: 关系说明，可选，≤ 500 字符.
    """
    source_type: EntityType
    source_id: uuid.UUID
    target_type: EntityType
    target_id: uuid.UUID
    relation_type: str
    description: str = ""

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("关系类型不能为空")
        if len(stripped) > 20:
            raise ValueError("关系类型不能超过 20 个字符")
        return stripped


class KnowledgeRelationUpdate(BaseModel):
    """更新图谱关系请求 DTO — 全可选，exclude_unset 语义（同 F1）.

    说明: 关系键（六元组）允许修改（改终点/改类型）；description 传空串 = 清空.
    """
    source_type: EntityType | None = None
    source_id: uuid.UUID | None = None
    target_type: EntityType | None = None
    target_id: uuid.UUID | None = None
    relation_type: str | None = None
    description: str | None = None
```

### 2.4 图谱查询 DTO（`domain/models/knowledge_graph.py` 续）

图谱聚合查询返回**节点 + 边**两个列表（前端画布直接消费，不做前端二次聚合）：

```python
class GraphNode(BaseModel):
    """图谱节点 — 六类实体统一视图.

    Attributes:
        id: 节点 ID（"<entity_type>:<entity_uuid>"，跨表唯一——图谱边引用键）.
        type: 实体类型（EntityType）.
        entity_id: 实体 UUID（源实体表主键）.
        name: 节点显示名（实体 name/title/label 按表映射，§2.2）.
    """
    id: str                    # f"{entity_type}:{entity_id}"
    type: EntityType
    entity_id: uuid.UUID
    name: str


class GraphEdge(BaseModel):
    """图谱边 — knowledge_relations + character_relations 合并去重后视图.

    Attributes:
        id: 边 ID（"kr:<relation_uuid>" 或 "cr:<relation_uuid>"，来源区分）.
        source: 起点节点 ID（GraphNode.id 格式）.
        target: 终点节点 ID.
        label: 关系类型（relation_type）.
        description: 关系说明.
        source_table: "knowledge_relations" | "character_relations"（合并来源）.
    """
    id: str
    source: str
    target: str
    label: str
    description: str = ""
    source_table: str


class KnowledgeGraphView(BaseModel):
    """图谱聚合响应 — GET /projects/{pid}/knowledge-graph."""
    nodes: list[GraphNode]
    edges: list[GraphEdge]
```

### 2.5 ORM（`infrastructure/database/models/knowledge_graph.py`）

```python
class KnowledgeRelationORM(Base):
    """图谱关系 ORM — 映射到 knowledge_relations 表（无 is_deleted，真删语义）.

    设计约定（同 F9 character_relations 先例）:
    - DB 主键 int 自增；领域层 UUID 映射: domain_id = uuid.UUID(int=orm.id)
    - 全唯一索引 (project_id, source_type, source_id, target_type, target_id,
      relation_type) 保证「项目内同键关系唯一」
    - 跨实体无 DB FK（source_id/target_id 无 ForeignKey）——服务层显式校验
    - FK 级联: 项目删除 → 关系级联删除（生产连接 FK 语义见 §5.3 D10=b）
    """

    __tablename__ = "knowledge_relations"

    __table_args__ = (
        Index(
            "uq_knowledge_relations_key",
            "project_id", "source_type", "source_id",
            "target_type", "target_id", "relation_type",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )
```

> **迁移（零迁移声明）**：`knowledge_relations` 是**新表**——由 `Base.metadata.create_all` 自动创建（无 alembic 基建，F1 惯例），**无需幂等迁移**。既有库升级：lifespan `create_tables()` 自动建新表（F36 §2.4 同款）。
> **⚠️ FK 语义说明（D10=b 先例）**：ORM 仅 project_id 声明 FK（供 create_all 建表），生产连接是否开 `PRAGMA foreign_keys=ON` 以合入时 `core/database.py` 实际状态为准（#327 已启用全局 FK——2026-08-16 起生产 FK 级联生效）；实体硬删 → 关系清理由 service 显式执行（§5.3），测试断言以 service 行为为准。

### 2.6 决策论证表

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **新建通用表 knowledge_relations（选定）** | 表达六类实体任意对；与 F9 character_relations 并存零破坏；图谱聚合单一查询面 | 跨实体无 DB FK，校验在服务层（既定成本，F35/F36 同款） | ✅ 本模块 |
| 扩展 character_relations 加 entity_type 列 | 复用既有表 | 破坏 F9 角色关系语义（角色 tab 契约全变）；混合两种粒度混乱 | ❌ 否决 |
| 每对实体类型一张关系表（6×5=30 张） | 强类型 | 表爆炸；图谱查询 N 次 JOIN | ❌ 否决 |
| 实体表加 relations JSON 列 | 实现简单 | JSON 嵌入 + 关系表双份真相（F9 §1 教训）；无法索引/级联 | ❌ 否决 |
| 关系迁移合并进 character_relations | 单一数据面 | 破坏 F9 已交付 API/CLI/GUI；迁移成本高 | ❌ 否决（Q1 备选 C） |

---

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/projects/{project_id}/knowledge-relations` | 创建图谱关系 → 201 |
| GET | `/api/v1/projects/{project_id}/knowledge-relations` | 关系列表（分页 + 过滤：`?source_type=&target_type=&relation_type=`；`?source=ai` 过滤 #479 预留） |
| GET | `/api/v1/projects/{project_id}/knowledge-graph` | **图谱聚合查询**（nodes + edges 合并 knowledge_relations + character_relations，去重） |
| GET | `/api/v1/knowledge-relations/{relation_id}` | 关系详情 |
| PATCH | `/api/v1/knowledge-relations/{relation_id}` | 更新关系（六元组可改 + description） |
| DELETE | `/api/v1/knowledge-relations/{relation_id}` | 真删关系（无 restore） |

> **⚠️ 无 restore 端点（D7 拍板）**：关系真删不可恢复——与 F9/F36 删除语义一致（#211 统一登记）。
> **图谱聚合 vs 关系列表职责分离**：`knowledge-graph` 供画布渲染（节点+边，合并 character_relations）；`knowledge-relations` 供关系管理（列表/筛选/编辑——只含 knowledge_relations 本表，不含 character_relations 行）。

### 3.2 请求/响应示例

**创建关系**：

```json
POST /api/v1/projects/1/knowledge-relations
{"source_type": "character", "source_id": "c0a8...",
 "target_type": "world", "target_id": "5f3e...",
 "relation_type": "属于", "description": "林尘出身清河县"}

201
{"id": "9", "project_id": "1", "source_type": "character", "source_id": "c0a8...",
 "target_type": "world", "target_id": "5f3e...", "relation_type": "属于",
 "description": "林尘出身清河县", "source": "manual", "created_at": "...", "updated_at": "..."}
```

**图谱聚合查询**：

```json
GET /api/v1/projects/1/knowledge-graph
{
  "nodes": [
    {"id": "character:c0a8...", "type": "character", "entity_id": "c0a8...", "name": "林尘"},
    {"id": "world:5f3e...", "type": "world", "entity_id": "5f3e...", "name": "清河县"}
  ],
  "edges": [
    {"id": "kr:9", "source": "character:c0a8...", "target": "world:5f3e...",
     "label": "属于", "description": "林尘出身清河县", "source_table": "knowledge_relations"},
    {"id": "cr:3", "source": "character:c0a8...", "target": "character:7b2d...",
     "label": "师徒", "description": "", "source_table": "character_relations"}
  ]
}
```

**更新关系**（改终点/改类型）：

```json
PATCH /api/v1/knowledge-relations/9
{"relation_type": "出身"}
→ 200 {"id": "9", ..., "relation_type": "出身", ...}
```

**删除关系**：

```http
DELETE /api/v1/knowledge-relations/9
→ 204
```

### 3.3 异常映射表

| 异常 | 状态码 | detail |
|------|--------|--------|
| KnowledgeRelationConflictError | 422 | 该关系已存在（同键唯一） |
| KnowledgeRelationSelfLoopError | 422 | 关系两端不能是同一实体（自环） |
| KnowledgeEntityNotFoundError | 422 | 起点/终点实体不存在或不在同一项目（detail 指明哪端：source/target + 类型） |
| KnowledgeRelationNotFoundError | 404 | 关系不存在 |
| ProjectNotFoundError（F10 world_errors 复用） | 404 | 项目不存在 |
| KnowledgeRelationValidationError | 422 | 六元组非法（字段校验） |

> **错误类归属**：`knowledge_graph_errors.py` 只定义模块专属错误；`ProjectNotFoundError` **复用 F10 world_errors 既有类**（F16 双入口教训：不重定义通用名错误类，避免遮蔽既有 router）；router 单入口（knowledge_graph.py）`_run_service` catch 链照 F10/F36 模式。
> **实体校验错误复用**：各实体 repo 的「不存在」错误（CharacterNotFoundError 等）在服务层**转换**为 `KnowledgeEntityNotFoundError`（图谱域统一错误面，不泄漏 F9-F13 各错误类——跨模块调用方只面对图谱错误契约）。

---

## 4. CLI 命令签名

`inkflow knowledge` 组（镜像 F9/F36 CLI 薄层风格）：

```bash
inkflow knowledge graph <project_id> [--json]                     # 图谱聚合查询（nodes + edges）
inkflow knowledge relation list <project_id> [--source-type <type>]
                                [--target-type <type>] [--relation-type <text>]
inkflow knowledge relation add <project_id> --source-type <type> --source-id <UUID>
                               --target-type <type> --target-id <UUID>
                               --relation-type <text> [--description <text>]
inkflow knowledge relation get <relation_id>
inkflow knowledge relation update <relation_id> [--relation-type <text>]
                                   [--description <text>] [--source-id <UUID>] ...
inkflow knowledge relation delete <relation_id>                   # 真删
```

- F7 全局约定：`--json` 信封 / 退出码 0/1/2 / `VALIDATION_ERROR`/`NOT_FOUND`/`DB_ERROR` 映射
- 删除类命令二次确认（同 F9/F36）
- `graph` 输出 `nodes` + `edges` 两个数组（与 API 响应同构，`--json` 原样输出；文本模式打印 edges 摘要行 `source --label--> target`）

---

## 5. 关键差异：跨实体关系校验链 + 图谱聚合 + 手动 CRUD + #479 预留

### 5.1 跨实体校验链（`domain/services/knowledge_graph_service.py`）

```text
create_relation:  ① 项目存在（ProjectNotFoundError）
                  ② 自环检查：source_type==target_type AND source_id==target_id → 422
                  ③ 六元组字段校验（Pydantic：relation_type 去空白非空 ≤20；description ≤500）
                  ④ source/target 实体存在 + 同项目（按 EntityType 分派各实体 repo 只读校验；
                     CharacterNotFoundError 等 → KnowledgeEntityNotFoundError，detail 指明 source/target 端）
                  ⑤ 同键唯一（repo.get_by_key；重复 → KnowledgeRelationConflictError；unique 兜底）
                  ⑥ 落库（source 恒 manual）
update_relation:  ① 关系存在（KnowledgeRelationNotFoundError）
                  ② 变更字段校验（同 ②③④——只有传入字段重新校验，未传字段不动）
                  ③ 同键唯一（改键后与另一行冲突 → KnowledgeRelationConflictError）
                  ④ 落库（source 字段不可改——#479 写入方才能置 ai）
delete_relation:  ① 关系存在 ② 真删单行
list_relations:   过滤（source_type/target_type/relation_type/source）+ 分页（offset/limit，created_at DESC）
```

### 5.2 图谱聚合查询（`graph(project_id)`）

**数据源合并**：

```text
nodes:  = 六类实体全部条目（characters + world_settings + outlines + timeline_events
          + foreshadowings + map_pins，按项目过滤，每表全量返回）
          ——实体条目即使无边也作为节点显示（图谱完整视图，用户可从此建关系）
edges:  = knowledge_relations（本项目全部，含 source=ai 预留）
        ∪ character_relations（本项目全部，角色间边只读合并——Q1=A 拍板定稿）
去重:   同键（source_type+source_id+target_type+target_id+relation_type）在两表都出现时
        → 显示 knowledge_relations 行（source_table="knowledge_relations"），character_relations 行折叠
        （Q1=A 定稿：character_relations 键转成 entity 六元组（type 恒 character）后比对去重）
```

**实现要点**：

- 节点 ID 格式 `"<entity_type>:<entity_uuid>"`（跨表唯一）；图谱边引用节点 ID（GraphNode.id）
- 查询 = 各实体 repo `list_by_project`（F9-F13/F36 既有方法，只读复用）+ knowledge_relations repo `list_by_project` + character_relations repo `list_by_project`（Q1=A 定稿：deps 注入 CharacterRepositoryProtocol 合并读取）；服务层组装 GraphNode/GraphEdge
- **性能**：单项目实体量级（本地个人项目，数百~数千条目）——列表查询即可，不做图数据库/缓存（F36 §2.2 同款「本地量级」论证）
- **孤立边防御**：knowledge_relations 中指向已不存在实体的行（实体硬删清理遗漏）——图谱查询时**跳过该边**（不 500），并记 loguru warning（与 F36 场景 6 同款容错）

### 5.3 实体硬删 → 关系级联清理（D3）

各实体真删（#211 语义）后，其作为 source/target 的 knowledge_relations 行必须删除（否则图谱出现悬空边 + 唯一键残留）。**不修改各实体 service 契约**，采用 F36 钩子先例：

```text
方案（F36 §5.4 同款「可选回调」模式）:
  - knowledge_graph_service 暴露 cleanup_for_entity(entity_type, entity_id)（单事务 DELETE 相关行）
  - deps 装配时以可选回调注入各实体 service（character_service/world_service/outline_service/
    timeline_service/foreshadowing_service/map_service 的删除路径）
  - 各实体 service 删除成功后调用回调（默认 None 向后兼容，同 F36 决策 15）
  - 项目硬删：project_service hard_delete 加 knowledge_graph_cleanup 回调（同 F36 map_cleanup 模式）
```

> **⚠️ 与 #327 的关系**：`knowledge_relations` 跨实体无 DB FK——即使全局 `PRAGMA foreign_keys=ON` 生效，实体硬删也不会 DB 级联删关系（无 FK 声明）——**清理必须由 service 显式执行**（D10=b 先例，与 F36/F43 P5 结论一致）。

### 5.4 手动增删改（前端交互，知识图谱 tab）

前端「知识图谱」tab（原 rag tab 改造）：

```text
tab 改造:   CATS 中 key='rag' → key='knowledge'（labelKey nav.lib.rag → nav.lib.knowledge）
            endpoint 从 /extractions/runs → 图谱画布组件（KnowledgeGraphCanvas）
            PATCH/DELETE_ENDPOINTS 继续排除 knowledge（图谱关系编辑走画布内交互，非列表行编辑）
            空态 CTA 从 navigate('/writing') → 图谱建关系引导（无实体时引导去各实体页创建）
图谱画布:   @xyflow/react（Q2=A 拍板定稿）——节点=实体（类型着色 + 图标），边=关系（label=relation_type，有向箭头）
交互:       拖拽节点（布局自由排布）/ 滚轮缩放 / 点击节点 → 详情抽屉（只读摘要 + 「去编辑」跳转实体页）
            点击边 → 详情（关系类型/描述/来源）+ 编辑/删除按钮
            工具栏「新建关系」→ 表单（起点类型+搜索实体 / 关系类型 / 终点类型+搜索实体 / 描述）
关系列表:   tab 内可切换「图谱视图 / 关系列表」——列表模式复用 F9 角色关系管理交互（筛选/编辑/删除）
```

> **前端数据流**：图谱视图加载调 `GET /projects/{pid}/knowledge-graph`（一次拿 nodes+edges）；增删改后**局部刷新**（重拉 graph 或本地 patch 边列表——实现期定，测试契约见 §9）。

### 5.5 #479 定时任务 + 规则/AI 关系提取（v1.2 定稿契约，#479 实现唯一真相）

> 用户拍板 D3：定时任务设置放设置页；**用户必须设置大模型后才能用 AI 提取**。F48 已交付本节数据面 + 写入端口（source 列/六元组唯一索引/bulk_create_relations）；#479 实现时**零 schema 变更**，只补调度 + 提取服务 + 设置 + 端点/CLI/前端。

#### 5.5.1 范围与形态

- **调度形态**：进程内 asyncio 调度器（`KnowledgeExtractScheduler`），随内核 lifespan 启停——本地单机架构（§1.2），不引入 APScheduler/系统 cron 等外部依赖（可逆性：后续如需跨平台系统级调度，调度器接口不变只换驱动）
- **触发粒度**：小时级（`interval_hours`），每个周期遍历全部未删除项目各跑一次提取
- **提取方式**：`rule`（规则，确定性，无需模型）/ `ai`（LLM 模板提取，需已配置模型）/ `both`（先 rule 后 ai）
- **不做**：分钟级调度、分布式锁（单机无并发调度）、提取结果人工审核队列（ai 行直接落库，靠六元组幂等 + 图谱页手动删除兜底）、对 `character_relations`（F9 双轨）的写入——AI/规则提取**只写 `knowledge_relations`**

#### 5.5.2 设置契约（F32 settings 扩展，三键）

`SettingsKey` 枚举 + `AppSettings` 字段 + `AppSettingsUpdate` 同步新增：

| 键 | 类型 | 默认 | 约束 |
|----|------|------|------|
| `kg_extract_enabled` | `bool` | `False` | 总开关；默认关闭（用户显式开启才调度） |
| `kg_extract_interval_hours` | `int` | `24` | 1 ≤ v ≤ 168（1 小时 ~ 7 天），越界 PATCH → 422 |
| `kg_extract_method` | `Literal["rule","ai","both"]` | `"rule"` | 提取方式；非法值 → 422 |

- 设置经既有 `GET/PATCH /api/v1/settings` 读写（零新端点）；调度器**每周期重读设置**（开关/频率/方式热生效，无需重启内核）
- 默认 `enabled=False` + `method=rule`：开箱零成本零风险（不调 LLM、不产生意外数据）

#### 5.5.3 调度器契约（`infrastructure/scheduler/kg_extract_scheduler.py` CREATE）

```text
class KnowledgeExtractScheduler:
    __init__(*, settings_service, project_repository, relation_extraction_service,
             session_factory)     # 调度器自持 session 生命周期（F45 M2 先例，不绑请求 session）
    async start()                 # lifespan startup 调用：spawn loop task（F42 create_task + done_callback 先例）
    async stop()                  # lifespan shutdown 调用：cancel + await（幂等）
    async run_cycle() -> list[dict]   # ★ 单周期执行体（RED 单测直调，不依赖 sleep）：
                                  #   1. 读 settings；enabled=False → 返回 [] 不执行
                                  #   2. project_repository.list_all()（未删除项目）
                                  #   3. 逐项目 relation_extraction_service.extract_for_project(
                                  #        project_id, method=kg_extract_method)
                                  #   4. 单项目异常捕获记入结果（不中断其他项目），汇总返回
    loop:                         # while True: await asyncio.sleep(interval*3600); await run_cycle()
                                  #   interval 每周期从 settings 重读（5.5.2）
    startup catch-up:             # start() 时查 extraction_runs 最近一次 knowledge_relation run：
                                  #   距今 ≥ interval_hours → 立即 run_cycle()（补跑）；否则等待
                                  #   无任何 run 记录（首启）→ 立即 run_cycle()
```

- **lifespan 接线**（`api/app.py` MODIFY）：startup `scheduler.start()` / shutdown `scheduler.stop()`；装配在 `api/deps.py`（`get_kg_extract_scheduler`）
- 防重：同一周期内用 F44 `spawn_background_task` key 注册表语义——`run_cycle` 进行中再次触发（手动端点并发）→ 跳过并返回 skipped 语义（不抛错）

#### 5.5.4 提取服务契约（`domain/services/relation_extraction_service.py` CREATE）

```text
class RelationExtractionService:
    __init__(*, knowledge_graph_service, character_repo, world_repo, outline_repo,
             timeline_repo, foreshadow_repo, map_pin_repo, chapter_repo,
             provider_config_service, llm_client_factory=None,
             llm_default_model=None, extraction_run_repo=None)
    async extract_for_project(project_id, method) -> ExtractionResult
    # method=None 时由调用方读 settings 传入（服务不读设置，保持纯领域）
```

**规则提取（method 含 rule）——确定性三规则集，零 LLM，只读结构化字段**：

| # | 信号（真实字段） | 产出关系 | relation_type |
|---|-----------------|---------|---------------|
| R1 | `WorldSetting.parent_id` 非空 | world(child) → world(parent) | 「属于」 |
| R2 | `Foreshadowing.event_id` 非空 | foreshadow → timeline | 「锚定于」 |
| R3 | `MapPin.location_id` 非空 | map_pin → world | 「位于」 |
| R3b | `MapPin.ref_id` 非空且 `type=role` | map_pin → character | 「出现于地图」 |
| R3c | `MapPin.ref_id` 非空且 `type=event` | map_pin → timeline | 「出现于地图」 |

- 实体跨项目/已删（repo 查不到）→ 该条跳过 + warnings 汇总（不报错）
- 规则集封闭枚举：新增规则必须改本表 + 测试断言（防自由发挥）；测试断言规则集数量 = 3（R1/R2/R3，R3b/R3c 属 R3 分支）

**AI 提取（method 含 ai）——模板 LLM 提取，需已配置模型**：

- **前置门禁（D3 拍板核心）**：`provider_config_service.list()` 中**无任何 `key_saved=True` 的 provider** → 判定「未配置模型」→ 抛 `LLMNotConfiguredError`（新错误类，`domain/ports/knowledge_graph_errors.py` 追加）；端点映射 422；调度器 method=ai 时记 run error 并跳过该项目，method=both 时**降级为仅 rule**（warnings 记「AI 提取跳过：未配置模型」）
- **输入**：项目全部章节正文（chapter_repo，按 narrative 顺序拼接，截断上限 50000 字符——与 ExtractionRequest.text 上限一致）；无章节 → status=skipped（skipped_reason「无章节内容」）
- **LLM 契约**：复用 F14 extractor 模式（`_character_extractor.py` 先例：JSON 输出 + `_extract_json_fragment` 容错解析 + 校验失败重试一次）；prompt 模板内置于 `_kg_relation_extractor.py`（CREATE，私有模块同 F14 命名惯例），产出 `[{from_name, from_type, to_name, to_type, relation_type, description}]`；relation_type 1-20 字符约束同 §2.1
- **模型选择**：`config.llm_default_model` 唯一默认源（#415 先例，deps 注入），零硬编码
- **实体名称 → id 解析**（占位节预留的解析辅助，本节定稿）：统一 `_resolve_entity(project_id, type, name)`——character/world/outline 走各 repo `get_by_name`；timeline 无 get_by_name → `list_all` 后 **title 精确匹配**（去首尾空白）；foreshadow 同 title 精确匹配；map_pin 不参与 AI 解析（AI 只产出五类：character/world/outline/timeline/foreshadow）。解析失败 → 该条关系丢弃 + warnings 汇总（F9 ExtractedRelation from_name/to_name 解析同款语义）
- **写入**：解析成功的关系统一走 `knowledge_graph_service.bulk_create_relations(project_id, relations, source=RelationSource.AI)`

**幂等语义（占位节待拍板项，本节定稿：跳过不覆盖）**：六元组已存在 → 跳过，不更新 description——AI 重复提取不覆盖用户手动调整过的描述；`ExtractionResult.updated` 口径 = 0（ai 提取恒不更新），`created` = 实际新增行数，跳过数进 warnings（「N 条关系已存在，跳过」）。

#### 5.5.5 运行记录（复用 F14 extraction_runs，占位节拍板项定稿）

- **不建自有表**：复用 `extraction_runs`——`ExtractionType` 新增第 7 值 `KNOWLEDGE_RELATION = "knowledge_relation"`（`backend/tests/unit/test_extraction_models.py` 既有 `len(ExtractionType) == 6` 断言**同步改 7**，RED 第一批）
- run 记录字段口径：`type=knowledge_relation`；`source_key=f"kg:{method}"`（rule/ai/both）；`status` success（created>0 或全幂等跳过）/ skipped（无章节/未启用）/ error（LLM 失败/未配模型走 error + error 文案）；手动触发与定时触发**同表同口径**（触发源不区分——Q3=A 拍板运行记录不做 GUI 展示面，#496 统一日志页承接）
- 定时触发每项目一条 run；手动触发同（project + method 一条）

#### 5.5.6 API + CLI 契约

```text
POST /api/v1/knowledge/extract            # knowledge_graph.py router 追加（tags 不变）
  body: { project_id: UUID, method?: "rule"|"ai"|"both" }   # method 缺省 = 跟随 settings
  200 → ExtractionResult 信封（同 POST /extract 形态：type/status/created/updated/warnings/model）
  404 项目不存在｜422 未配置模型（method 含 ai，detail 指明）｜422 method 非法
GET /api/v1/knowledge/extract/status      # 设置页「立即运行」按钮状态 + 最近一次 run 摘要
  200 → { running: bool, last_run: { status, created, run_at } | null }
```

- 手动触发端点与调度器共用 `run_cycle`/`extract_for_project`（单一执行体）；运行中再次 POST → 422「提取正在进行」（F44 prepare_run 守卫同款语义）
- CLI：`inkflow knowledge extract --project <uuid> [--method rule|ai|both]`（`cli/commands/knowledge_graph.py` 追加，信封/退出码同既有 knowledge 组；--method 缺省跟随 settings）

#### 5.5.7 前端设置页契约（`pages/settings.tsx` MODIFY）

- 新增「知识图谱提取」设置卡片（i18n `settings.kgExtract.*`，zh 主 en 同步）：
  1. **启用开关**（kg_extract_enabled，Switch）
  2. **提取频率**（kg_extract_interval_hours，Select：1/6/12/24/72/168 小时）
  3. **提取方式**（kg_extract_method，Radio：仅规则 / 仅 AI / 规则+AI）
  4. **「立即运行」按钮** → POST /knowledge/extract（当前无「当前项目」上下文时按全部项目跑一轮同调度周期语义；运行中禁用 + loading 态，轮询 extract/status）
- **未配置模型门禁（D3）**：前端以 models store `hasChatModel`（既有）判定——无已配置模型时「仅 AI」「规则+AI」选项 disabled + 提示文案「需先在模型设置中配置大模型」；已启用且 method 含 ai 时切走模型配置 → 设置卡片顶部 warning 条
- **900 行护栏（#88）**：settings.tsx 现 752 行，本卡片独立为 `components/knowledge-graph/KnowledgeExtractCard.tsx`（CREATE），settings.tsx 只挂载——防贴线

#### 5.5.8 测试与 CI 登记契约

| 测试文件 | 层 | 覆盖 | CI 登记 |
|---------|-----|------|---------|
| `backend/tests/unit/test_relation_extraction_service.py` | unit | 规则三规则集逐条 + 跨项目/已删跳过 + AI mock LLM 解析/重试 + 未配模型 LLMNotConfiguredError + 名称解析失败 warnings + 幂等跳过 + both 降级 | tests/unit/ glob 自动收集（零登记） |
| `backend/tests/unit/test_kg_extract_scheduler.py` | unit | run_cycle：disabled 跳过/逐项目执行/单项目异常不中断 + 每周期重读设置 + startup 补跑/首启立跑 + stop 幂等 | 同上 |
| `backend/tests/unit/test_extraction_models.py`（MODIFY） | unit | `len(ExtractionType) == 7` + KNOWLEDGE_RELATION 值断言 | 既有文件零登记 |
| `tests/api/test_knowledge_extract_api.py` | api | extract 端点契约（200/404/422 未配模型/422 非法 method）+ status 端点 | tests/api/ glob 自动收集（零登记） |
| `tests/cli/test_cli_knowledge_extract.py` | cli | extract 命令信封/退出码/--method 透传 | ⚠️ **显式追加 ci.yml `integration-cli-backend` job 文件列表**（Windows pytest 不展开 glob，§8 CI 盲区防范同款） |
| `frontend/.../settings-kg-extract.test.tsx` | 前端 vitest | 开关/频率/方式渲染 + AI 选项未配模型 disabled+提示 + 立即运行按钮（vi.mock API，同 library-p*.test.tsx 模式） | renderer 目录通配自动收集（实现期核对） |
| `frontend/.../components/knowledge-graph/KnowledgeExtractCard.tsx` | 组件 | 见 5.5.7 | — |

- 覆盖率：新模块行覆盖 ≥ 80%，全仓门禁 ADR-027 同款
- 后台任务 RED 陷阱（F44 先例）：scheduler 测试不得泄漏 pending task（teardown cancel）；断言后台调用须 `await asyncio.sleep(0)`

#### 5.5.9 #479 验收（本 spec 的 M 行不覆盖，映射 #479 自身门禁）

1. 设置页三键可读写（开关/频率/方式），PATCH 越界 422；调度器热生效（改频率后下一周期按新值）
2. 规则提取无需模型：mock 零 provider 配置 → rule 提取正常产出 R1/R2/R3 边（source=ai 列值恒 ai——规则与 AI 提取统一 source=ai 语义，区分靠 run 的 source_key）
3. 未配置模型：AI 提取禁用——端点 422 + 前端选项 disabled + 提示；both 降级 rule + warning
4. 幂等：重复运行 → created=0，关系数不增
5. 图谱聚合显示提取边 + 关系列表 `?source=ai` 可过滤（F48 既有能力，#479 只验数据面打通）
6. 测试全绿 + ci.yml CLI 登记 + 900 行护栏合规

### 5.6 排序与确定性

- 关系列表：`created_at DESC`（新关系在前——F9/F10 同款）
- 图谱节点：按实体类型分组顺序返回（character → world → outline → timeline → foreshadow → map_pin，组内 `name ASC`）——画布布局稳定，非随机
- 图谱边：`knowledge_relations` 在前、`character_relations` 在后（去重优先权一致），组内 `created_at ASC`

---

## 6. 组织规则

- **目录归属**：新模块 `domain/models/knowledge_graph.py` + `domain/ports/knowledge_graph_errors.py` + `domain/ports/knowledge_relation_repository.py` + `domain/services/knowledge_graph_service.py` + `infrastructure/database/models|repositories/knowledge_graph*` + `api/routers/knowledge_graph.py` + `cli/commands/knowledge_graph.py` + 前端 `components/knowledge-graph/`——镜像 F9/F36 骨架（实体 + 仓储 + service + router + CLI + 前端组件）
- **deps 装配**：`api/deps.py` 新增 `get_knowledge_graph_service(db)`——注入 SQLiteKnowledgeRelationRepository + 六类实体 repo（只读校验）+ ProjectRepositoryProtocol（项目硬删钩子）+ CharacterRepositoryProtocol（character_relations 合并读取，Q1=A 拍板定稿）
- **跨实体校验复用**：实体 repo 只读调用（`get` 方法），**不 import 各实体 service**（防循环依赖——knowledge_graph_service 只依赖 repository 协议层）
- **日志**：loguru（创建/删除/孤立边 warning/清理回调均记，F9/F10 风格）
- **前端组件归属**：`components/knowledge-graph/` 新目录（KnowledgeGraphCanvas/RelationForm/RelationList/EntityPicker）；library.tsx rag tab 改造 MODIFY；i18n 文案 `nav.lib.knowledge` + `lib.knowledge.*`

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| 1 | source/target 实体不存在（任意类型） | 422 KnowledgeEntityNotFoundError（detail 指明 source/target 端 + 类型） |
| 2 | source/target 实体属于其他项目 | 422 KnowledgeEntityNotFoundError（跨项目视为不存在——实体校验 repo 按项目过滤） |
| 3 | 自环（同类型同 id） | 422 KnowledgeRelationSelfLoopError |
| 4 | 同键关系重复创建 | 422 KnowledgeRelationConflictError（unique 兜底） |
| 5 | relation_type 空白/超长 | 422 KnowledgeRelationValidationError（Pydantic 字段校验） |
| 6 | PATCH 改键后与现有行冲突 | 422 KnowledgeRelationConflictError |
| 7 | PATCH source 字段（试图改来源） | 422 KnowledgeRelationValidationError（source 不可改——#479 写入方才能置 ai） |
| 8 | 关系不存在（get/update/delete） | 404 KnowledgeRelationNotFoundError |
| 9 | 项目不存在 | 404 ProjectNotFoundError（F10 复用） |
| 10 | 图谱查询遇孤立边（实体已被删但关系残留） | 跳过该边 + loguru warning（不 500） |
| 11 | 实体硬删 → 其关系行 | service 显式清理（cleanup_for_entity 回调，§5.3）——图谱无悬空边 |
| 12 | 项目硬删 → 关系行 | project_service hard_delete 钩子显式清理（§5.3） |
| 13 | map_pin 孤立（所属 map 已删） | pin 实体校验失败 → KnowledgeEntityNotFoundError；图谱查询节点生成时跳过孤立 pin + warning |
| 14 | 空项目图谱查询 | 200 `{"nodes": [], "edges": []}`（空图谱合法，前端显示空态引导） |
| 15 | 关系列表无匹配 | 200 `{"items": [], "total": 0}` |
| 16 | 六元组 source_type/target_type 非法枚举值 | 422 KnowledgeRelationValidationError（Pydantic Enum 校验） |
| 17 | #479 ai 行（未来）与 manual 行同键 | 唯一索引拒绝（ai 写入方需幂等去重——§5.5 预留） |

---

## 8. 文件结构（对照真实源码树）

| 文件 | 变更 | 内容 |
|------|------|------|
| `backend/src/inkflow/domain/models/knowledge_graph.py` | **CREATE** | EntityType/RelationSource/KnowledgeRelation/KnowledgeRelationCreate/KnowledgeRelationUpdate/GraphNode/GraphEdge/KnowledgeGraphView（§2.3-§2.4） |
| `backend/src/inkflow/domain/ports/knowledge_graph_errors.py` | **CREATE** | KnowledgeGraphServiceError/KnowledgeRelationConflictError/KnowledgeRelationSelfLoopError/KnowledgeEntityNotFoundError/KnowledgeRelationNotFoundError/KnowledgeRelationValidationError |
| `backend/src/inkflow/domain/ports/knowledge_relation_repository.py` | **CREATE** | KnowledgeRelationRepositoryProtocol（add/get/get_by_key/list/filter/update/delete/list_by_project/delete_by_entity/cleanup_for_entity） |
| `backend/src/inkflow/domain/services/knowledge_graph_service.py` | **CREATE** | 编排（§5.1 校验链 + §5.2 图谱聚合 + §5.3 清理回调 + §5.5 bulk_create_relations 预留）；依赖注入：KnowledgeRelationRepositoryProtocol + 六类实体 repo + ProjectRepositoryProtocol |
| `backend/src/inkflow/infrastructure/database/models/knowledge_graph.py` | **CREATE** | KnowledgeRelationORM（§2.5，无 is_deleted） |
| `backend/src/inkflow/infrastructure/database/repositories/knowledge_relation_repo.py` | **CREATE** | SQLiteKnowledgeRelationRepository（CRUD/过滤/唯一约束/真删/delete_by_entity） |
| `backend/src/inkflow/api/routers/knowledge_graph.py` | **CREATE** | 6 端点（§3.1） |
| `backend/src/inkflow/api/app.py` | **MODIFY** | 注册 knowledge_graph router（`include_router(knowledge_graph.router)`） |
| `backend/src/inkflow/api/deps.py` | **MODIFY** | 新增 `get_knowledge_graph_service` 装配 |
| `backend/src/inkflow/cli/commands/knowledge_graph.py` | **CREATE** | `inkflow knowledge` 组（§4） |
| `backend/src/inkflow/cli/app.py` | **MODIFY** | 注册 knowledge 命令组 |
| `backend/tests/unit/test_knowledge_relation_repo.py` | **CREATE** | 仓储层（CRUD/唯一约束/过滤/真删/delete_by_entity） |
| `backend/tests/unit/test_knowledge_graph_service.py` | **CREATE** | 服务层（校验链/聚合合并/去重/清理回调/孤立边防御） |
| `backend/tests/unit/test_knowledge_graph_api.py` | **CREATE** | API 契约（CRUD/错误映射/图谱聚合响应形状） |
| `tests/cli/test_cli_knowledge_graph.py` | **CREATE** | CLI 命令（信封/退出码/graph 输出） |
| `frontend/packages/renderer/src/components/knowledge-graph/KnowledgeGraphCanvas.tsx` | **CREATE** | 图谱画布（@xyflow/react 节点/边渲染 + 拖拽/缩放/点击交互） |
| `frontend/packages/renderer/src/components/knowledge-graph/RelationForm.tsx` | **CREATE** | 新建/编辑关系表单（EntityPicker 起点/终点搜索选择） |
| `frontend/packages/renderer/src/components/knowledge-graph/RelationList.tsx` | **CREATE** | 关系列表视图（筛选/编辑/删除） |
| `frontend/packages/renderer/src/api/knowledge-graph.ts` | **CREATE** | API 客户端（graph/relation CRUD，apiFetch 封装同 client.ts 模式） |
| `frontend/packages/renderer/src/pages/library.tsx` | **MODIFY** | rag tab → knowledge tab（CATS key/labelKey/endpoint + 图谱视图挂载 + 空态引导） |
| `frontend/packages/renderer/src/i18n/*` | **MODIFY** | `nav.lib.knowledge` + `lib.knowledge.*` 文案（zh 主，en 同步） |
| `frontend/packages/renderer/src/pages/library-kg.test.tsx` | **CREATE** | 前端测试（图谱 tab 渲染/空态/建关系交互——测试文件命名同既有 library-p*.test.tsx 惯例） |
| `frontend/package.json`（或 renderer package） | **MODIFY** | 新增 `@xyflow/react` 依赖（Q2=A 拍板定稿） |

> **⚠️ CI 盲区防范（Issue #59/#61 教训）**：`tests/cli/test_cli_knowledge_graph.py` 是**新文件**，需显式加入 ci.yml `integration-cli-backend` job 文件列表（Windows pytest 不展开 glob）；前端新测试文件确认被现有 vitest 收集（renderer 目录通配，实现期核对）。
> **⚠️ 900 行护栏（#88）**：`test_knowledge_graph_service.py` 若超 900 行按 class 拆分（F43 P2 先例）。
> **ℹ️ #479 文件不在本表**：定时任务/提取服务/设置扩展/前端设置卡片的文件结构与 CI 登记见 §5.5.8（v1.2 定稿），由 #479 实现期交付，F48 不涉及。

---

## 9. 测试策略

### 层次

```text
单元（repo）:    knowledge_relations CRUD 往返 + 六元组唯一约束 + 过滤 + 真删 + delete_by_entity   ~14 cases
单元（service）: 校验链（实体不存在/跨项目/自环/同键冲突）+ 图谱聚合合并/去重 + 清理回调
                + 孤立边防御 + bulk_create_relations 预留（#479 面）                              ~20 cases
API（集成）:     CRUD 端点 + 错误映射 + 图谱聚合响应形状                                           ~12 cases
CLI:             knowledge 组命令 + graph 输出                                                      ~10 cases
前端:            图谱 tab 渲染/空态/建关系表单/边编辑删除（library-kg.test.tsx）                    ~8 cases
```

### 关键测试场景

1. **六元组校验闭环**：创建 character→world「属于」→ 201；实体不存在 → 422（detail 指明端）；跨项目实体 → 422
2. **自环拒绝**：同类型同 id → 422 KnowledgeRelationSelfLoopError
3. **同键唯一**：相同六元组重复创建 → 422 KnowledgeRelationConflictError
4. **图谱聚合合并**：knowledge_relations + character_relations 同时存在 → edges 两来源都有，`source_table` 正确
5. **图谱去重**：同键关系两表都出现 → 只显示 knowledge_relations 行（Q1=A 时）
6. **孤立边防御**：关系指向已删实体 → graph 查询跳过该边 + 不 500（mock 实体 repo 返回 None）
7. **实体硬删清理回调**：mock 实体 service 删除路径 → cleanup_for_entity 被调用（DELETE 相关行）；默认 None 向后兼容
8. **项目硬删钩子**：project_service hard_delete → knowledge_graph_cleanup 被调用
9. **source 字段**：创建恒 manual；PATCH source → 422（不可改）；?source=ai 过滤返回空（v1.0 无 ai 行）
10. **map_pin 校验链路**：pin 存在 + 所属 map 项目匹配 → 通过；pin 孤立 → 422
11. **Pydantic 边界**：relation_type 空白/21 字符 → 422；description 501 字符 → 422
12. **空图谱**：无实体无关系 → 200 `{"nodes": [], "edges": []}`
13. **前端图谱 tab**：mock graph API → 画布渲染节点/边；点击边 → 详情 + 删除；空态引导（RTL + vi.mock，同 library-p*.test.tsx 模式）

### 覆盖率

模块行覆盖 ≥ 80%；全仓门禁 ADR-027（M8 验收前先跑 coverage-backend 等价命令实测，留补测 buffer——F36 同款）。

---

## 10. 不在范围内

| 项 | 原因 | 归属 |
|----|------|------|
| 定时任务 AI/规则提取关系 | 用户拍板 #479 另 issue（本模块仅预留数据面 + 写入端口，§5.5） | #479（0.10.1） |
| 知识图谱检索页（RAG 语义检索/向量检索 UI） | 用户拍板 #480 另 issue（原 rag tab 检索能力承接） | #480（0.10.1） |
| character_relations 迁移/合并进 knowledge_relations | Q1=A 拍板先双轨 + 聚合去重；迁移是破坏性重构 | **#495**（1.0.0，Q1-C 后续重构） |
| 统一日志页（内核/GUI/AI 日志分类展示与查询） | Q3=A 追加需求：提取运行记录不保留在图谱 tab；运行日志统一日志页是独立功能 | **#496**（1.0.0） |
| 实体详情编辑（图谱内直接改角色/世界观内容） | 各实体编辑在既有页面闭环（图谱节点详情 = 只读摘要 + 跳转） | 后续 |
| 图谱布局算法自研/力导向自动布局调优 | 选型 @xyflow/react 自带布局；深度调优无场景 | 后续 |
| 关系类型受控词表/规则引擎 | 自由文本 v1.0 可用；词表归 #479 规则提取 | #479 |
| 图谱导出/分享 | 本地单机架构（ADR-030）无分享场景 | 永不 |
| 图谱节点隐藏/筛选（按类型过滤显示） | 实体量级小，v1.0 全量显示；前端可后续加 | 后续 |
| F14 extraction_runs 列表展示 | Q3=A 拍板不保留在图谱 tab；是否并入统一日志页由 #496 决定 | #496（1.0.0） |
| 多项目关系共享 | 本地单机 + 强 project_id 隔离（F9/F36 同款） | 永不 |

---

## 11. 依赖关系

```text
F48 依赖:
  F1（projects 表 + ProjectRepositoryProtocol）— 项目存在性校验 + 项目硬删钩子
  F9（characters + character_relations）— 实体校验（角色）+ 图谱合并读取（只读复用，零改动）
  F10（world_settings）— 实体校验（世界观条目，只读复用）
  F11（outlines）— 实体校验（大纲，只读复用）
  F12（timeline_events）— 实体校验（时间线事件，只读复用）
  F13（foreshadowings）— 实体校验（伏笔，只读复用）
  F36/F43 P2（maps + map_pins）— 实体校验（地图 pin，经 map→project 链路，只读复用）
  F14（extractions/runs）— 原 rag tab 数据源（本模块改造展示面，不依赖其端点）
  F7（CLI 全局约定）— knowledge 组信封/退出码

F48 被依赖:
  #479（定时任务 AI/规则提取）— 依赖 knowledge_relations 表结构 + source 列 + bulk 写入端口（§5.5）
  #480（检索页）— 依赖 rag tab 改造后的定位（#480 承接检索 UI）
  #495（Q1-C 迁移合并）— 依赖 knowledge_relations 表 + 聚合去重逻辑（合入稳定后动 F9 写入面）
  #496（统一日志页）— 可选依赖 F14 extraction_runs 数据（#496 决定是否并入）
```

**编号口径声明**：本模块为 0.10.1 UI/产品修复批 D3 前半（#478），「F48」编号承接（本地 specs/ 最高 f47，F48 未占用——2026-08-19 核对）。模块类型谱系 **第 21 变体「实体关系图谱型」**（F38=第 18 变体最新无冲突基线；F20/F46 双占第 19、F44/F45 双占第 20——冲突以 ADR-019 v7+ 重排为准）。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|-------------|
| 1 | **新建通用关系表 knowledge_relations** | 六元组（source_type+source_id / target_type+target_id）+ relation_type + description + source；project_id 冗余 | 表达六类实体任意对；与 F9 character_relations 并存零破坏；图谱聚合单一查询面 | 扩展 character_relations（破坏 F9）；每对实体一张表（表爆炸）；实体加 JSON 列（双份真相）；迁移合并（破坏已交付） |
| 2 | **跨实体无 DB FK，服务层显式校验** | source_id/target_id 无 ForeignKey；实体存在 + 同项目由 knowledge_graph_service 分派各实体 repo 校验；各实体错误类转换 KnowledgeEntityNotFoundError | 跨 6 张表无法单列 FK；服务层统一错误面（跨模块调用方只面对图谱契约）；F35/F36 同款 | 每实体对建 FK（不可行）；透传各实体错误类（错误面分散） |
| 3 | **实体硬删 → 关系清理走可选回调（F36 钩子先例）** | knowledge_graph_service.cleanup_for_entity + deps 注入各实体 service 删除路径 + project hard_delete 钩子 | 不修改各实体 service 公共契约（默认 None 向后兼容）；防悬空边 + 唯一键残留 | 修改各实体 service 硬编码清理（破坏 F9-F13 契约）；依赖 DB FK（跨表无 FK） |
| 4 | **图谱聚合 = 合并两表 + 去重** | graph 端点 nodes（六类实体全量）+ edges（knowledge_relations ∪ character_relations，同键去重，knowledge 优先） | 图谱显示完整（含 F9 既有角色边）；单一图谱查询面（前端零二次聚合）；角色页与图谱页展示一致 | 图谱只显示 knowledge_relations（既有角色边不可见——信息缺失） |
| 5 | **真删语义（无 is_deleted）** | knowledge_relations 新表无软删列；DELETE 物理删除 | 普通实体删除收敛真删（F36 D1=B/D7、#211 统一登记）；新表零历史包袱 | 带 is_deleted（F10 同款——被否决） |
| 6 | **source 列预留 #479** | manual/ai 枚举 + 唯一索引 = AI 幂等去重键；bulk_create_relations(project_id, relations, source=ai) 写入端口 | 数据面先行（用户拍板「关系来源：手动创建 + 预留 #479」）；#479 实现零 schema 变更 | #479 时再加列（F48 已发布，加列迁移成本） |
| 7 | **图谱可视化选型 @xyflow/react** | React Flow v12（37.9K stars，MIT，React 19 兼容）——节点/边渲染 + 拖拽/缩放/自定义节点开箱即用 | 最成熟 React 图可视化库；零布局自研；社区活跃（xyflow 官方维护） | 手写 SVG/Canvas（拖拽/缩放/布局全自研，工作量翻倍）；antv G6（重依赖，非 React 原生）；d3-force（无现成交互） |
| 8 | **rag tab 改造为知识图谱 tab** | CATS key rag→knowledge；图谱画布 + 关系列表；PATCH/DELETE 继续排除 | 用户拍板 D3-2「知识库 RAG → 知识图谱」；RAG 检索能力 #480 承接 | 新增第 7 个 tab（六分类 + 图谱并存——tab 膨胀，且 rag 检索面与图谱混放） |
| 9 | **Q1=A 拍板：允许图谱建角色↔角色关系（2026-08-19）** | character→character 合法（写 knowledge_relations）；角色页 F9 保留（写 character_relations）；图谱聚合合并 + 同键去重（§5.2） | 图谱手动编辑闭环完整；F9 零破坏；个人项目可接受双轨 | 方案 B（图谱禁止角色关系——编辑流断裂，**用户否决**）；方案 C（迁移合并——破坏性重构，**用户否决**，建 #495 挂 1.0.0 后续做） |
| 10 | **Q2=A 拍板：图谱渲染定稿 @xyflow/react（2026-08-19）** | React Flow v12（37.9K stars，MIT，React 19 兼容）；拖拽/缩放/自定义节点开箱即用 | 工程化最小；React 生态图可视化事实标准 | 手写 SVG/Canvas（+2-3 人天，**用户否决**）；antv G6/d3-force（**用户否决**） |
| 11 | **Q3=A 拍板：提取运行记录不保留 + 统一日志页（2026-08-19）** | 图谱 tab 不保留 extractions/runs 展示；运行日志（内核/GUI/AI）统一日志页建 #496 挂 1.0.0 | 图谱 tab 聚焦关系；runs 是过程日志非日常查看对象；日志页独立功能后续排期 | 方案 B（图谱 tab 内嵌提取记录区——三视图拥挤，**用户否决**）；方案 C（等 #480——推迟 D3 落地，**用户否决**） |
| 12 | **#479 契约定稿（v1.2，2026-08-19）：进程内调度 + 复用 extraction_runs + 幂等跳过** | ① 进程内 asyncio 调度器（lifespan 启停 + 启动补跑 + 每周期重读设置），不引入 APScheduler/系统 cron；② run 记录复用 F14 extraction_runs（ExtractionType 第 7 值），不建自有表；③ 六元组幂等 = 跳过不覆盖（AI 不覆盖手动调整的 description）；④ 规则提取三规则集只读结构化字段（WorldSetting.parent_id / Foreshadowing.event_id / MapPin.location_id+ref_id），零 LLM；⑤ AI/规则提取只写 knowledge_relations（不碰 F9 双轨）；⑥ 未配置模型（provider_config 无 key_saved=True）→ AI 禁用：端点 422 + 前端选项 disabled + both 降级 rule | 本地单机架构进程内调度最简单可逆；复用 run 表面零新表零 GUI 面（Q3=A 已拍 runs 无展示面）；跳过不覆盖保护用户手动编辑；规则集确定性可测试 | 系统 cron/schtasks（跨平台三套 + 内核外生命周期失控）；自建 kg_extraction_runs 表（无展示面纯属冗余）；幂等覆盖更新（破坏用户手动编辑）；AI 提取写 character_relations（破坏 F9 契约 + 双轨污染） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 数据模型 + 建表（create_all 自动，无 is_deleted） | `pytest backend/tests/unit/test_knowledge_relation_repo.py -v` 全绿；新库表存在（PRAGMA table_list）；knowledge_relations 无 is_deleted 列 |
| M2 | 服务校验链（六元组/实体存在/同项目/自环/同键冲突/角色↔角色合法） | `pytest backend/tests/unit/test_knowledge_graph_service.py -v` 全绿（Q1=A 定稿：character→character 合法分支 + 双轨聚合去重用例） |
| M3 | API 契约（CRUD + 图谱聚合 + 错误映射） | `pytest backend/tests/unit/test_knowledge_graph_api.py -v` 全绿 |
| M4 | 图谱聚合合并 + 去重 + 孤立边防御 + 清理回调 | service 聚合测试全绿（合并 character_relations/去重/孤立边跳过/cleanup_for_entity 回调） |
| M5 | CLI knowledge 组 | `pytest ../tests/cli/test_cli_knowledge_graph.py -v` 全绿（**且已追加 ci.yml integration-cli-backend job**） |
| M6 | 前端知识图谱 tab（画布/交互/增删改） | `frontend` vitest library-kg.test.tsx 全绿（@xyflow/react 渲染，Q2=A 定稿）；手工验证：切到知识图谱 tab → 画布渲染节点/边 → 拖拽/缩放 → 点击边详情 → 新建关系 → 删除 |
| M7 | 手工验证闭环 | 建角色+世界观 → 图谱建「属于」关系 → 图谱显示 → 角色页建角色关系 → 图谱合并显示 → 删关系 → 删实体 → 关系被清理（无悬空边） |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；ADR-027 门槛（先跑 coverage-backend 等价命令实测留 buffer）；`uv run ruff check src/ tests/unit/ ../tests/` + mypy 通过；前端 `pnpm lint` + `tsc --noEmit` |

> Issue #478 验收标准映射：关系数据模型 = M1-M2；可视化 = M4/M6；手动增删改 = M3/M6；前端测试全绿 = M6/M8；#479 预留 = §5.5 数据面（M 行不覆盖——由 #479 验收，见 §5.5.9）。

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 结论 |
|---|------|------|------|
| Q1 | **角色↔角色关系的图谱写入归属**：图谱页是否允许创建角色间关系（写 knowledge_relations）？选项 A（推荐）：允许——图谱页建角色间关系写 knowledge_relations，图谱聚合去重显示（与 F9 character_relations 同键时 knowledge 优先），角色页 F9 关系管理保留不变；选项 B：禁止——图谱页角色间关系只读（详情引导去角色页管理），knowledge_relations 校验拒绝 character→character；选项 C：迁移——F9 写入改为 knowledge_relations（破坏性） | API 校验规则 + 图谱聚合去重逻辑 + F9 边界 | ✅ 已确认（2026-08-19 用户拍板：**选项 A**）——§2.1 规则 3b / §5.2 聚合 / §8 deps 已定稿；C 建 **#495**（1.0.0）后续重构 |
| Q2 | **图谱前端渲染方案**：选项 A（推荐）：引入 `@xyflow/react`（React Flow v12，37.9K stars，MIT，React 19 兼容）——节点/边渲染 + 拖拽/缩放/自定义节点开箱即用，工作量最小；选项 B：手写 SVG/Canvas 图渲染（零新依赖，但拖拽/缩放/布局全自研，估算 +2-3 人天）；选项 C：antv G6 / d3-force 等其他库 | 依赖面 + 工作量 + 交互完整度 | ✅ 已确认（2026-08-19 用户拍板：**选项 A**）——§5.4 画布 / §8 package.json / §13 M6 已定稿 |
| Q3 | **原 rag tab 的提取运行记录列表去向**：改造为知识图谱 tab 后，extractions/runs 列表不再有独立展示面。选项 A（推荐）：不保留——提取运行记录仅 CLI/API 可见（#480 检索页承接检索，不承接 runs 列表）；选项 B：图谱 tab 内保留折叠式「提取记录」区（tab 内双视图：图谱/关系列表/提取记录）；选项 C：等 #480 检索页一起决定 | 前端 tab 结构 + 原 rag 数据可见性 | ✅ 已确认（2026-08-19 用户拍板：**选项 A** + 追加「统一日志页」需求）——§5.4 / §10 已定稿；统一日志页（内核/GUI/AI 日志分类展示查询）建 **#496**（1.0.0） |

---

> **所有里程碑验收以本节 M1-M8 为准**；Q1-Q3 已全拍板（2026-08-19，✅ 留痕），正文已按拍板结果修订（§2.1 规则 3b / §5.2 聚合 / §5.4 前端 / §8 文件结构 / §10 / §11 / §12 决策 9-11 / §13）——F48 实现以 v1.1 为唯一真相来源。v1.2（2026-08-19）补定 §5.5 #479 具体契约（决策 12），#479 实现以 §5.5 为唯一真相。

## 14. 动作确认

> 每个端点/命令的完整状态流表（基于 §3 + §4 + §5 + §7 事实，不重复）。#479 提取端点（§5.5.6）不在本表——由 #479 实现交付，本 spec 仅预留数据面。

### 14.1 端点状态流

| 端点 | 前置条件 | 动作/状态转换 | 成功 | 失败 | 边界 |
|------|---------|--------------|------|------|------|
| POST /api/v1/projects/{project_id}/knowledge-relations | 项目存在 | 校验链（项目存在 → 自环 → 六元组字段 → source/target 实体存在 + 同项目 → 同键唯一）→ 落库（source 恒 manual） | 201 完整实体 | 404（项目不存在）；422（自环/实体不存在/同键冲突/字段非法） | character→character 合法（Q1=A）；六元组唯一索引兜底 |
| GET /api/v1/projects/{project_id}/knowledge-relations | 项目存在 | 过滤（source_type/target_type/relation_type/source）+ 分页（offset/limit，created_at DESC） | 200 {items, total} | 404 | 只含 knowledge_relations 本表（不含 character_relations 行） |
| GET /api/v1/projects/{project_id}/knowledge-graph | 项目存在 | 聚合：六类实体全量 nodes + knowledge_relations ∪ character_relations edges（同键去重，knowledge 优先） | 200 {nodes, edges} | 404 | 空图谱 → 200 空数组（前端空态引导）；孤立边跳过 + loguru warning（不 500）；节点 ID 格式 entity_type:entity_uuid |
| GET /api/v1/knowledge-relations/{relation_id} | 关系存在 | 详情 | 200 完整实体 | 404（关系不存在） | — |
| PATCH /api/v1/knowledge-relations/{relation_id} | 关系存在 | 变更字段重新校验（自环/实体存在/同项目/同键唯一）→ 落库 | 200 完整实体 | 404；422（改键后冲突/字段非法） | source 字段不可改（#479 写入方才能置 ai）；未传字段不动 |
| DELETE /api/v1/knowledge-relations/{relation_id} | 关系存在 | 真删单行（无 restore） | 204 | 404 | 与 F9/F36 删除语义一致（#211 统一登记） |

### 14.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow knowledge graph &lt;project_id&gt; [--json] | 项目存在 | 图谱聚合查询（nodes + edges） | 退出码 0（文本模式 edges 摘要行 source --label--&gt; target；--json 原样输出） | 404 → 退出码 1 | — |
| inkflow knowledge relation list &lt;project_id&gt; [--source-type/--target-type/--relation-type] | — | 关系列表 | 退出码 0 + 信封 | 退出码 1 | — |
| inkflow knowledge relation add &lt;project_id&gt; --source-type --source-id --target-type --target-id --relation-type [--description] | 实体存在 + 同项目 | 创建 | 退出码 0 + 实体 | 422 → 退出码 1 | — |
| inkflow knowledge relation get &lt;relation_id&gt; | 关系存在 | 详情 | 退出码 0 | 404 → 退出码 1 | — |
| inkflow knowledge relation update &lt;relation_id&gt; [--relation-type/--description/--source-id ...] | 关系存在 | 更新 | 退出码 0 | 404/422 → 退出码 1 | — |
| inkflow knowledge relation delete &lt;relation_id&gt; | 关系存在 | 真删（二次确认） | 退出码 0 | 404 → 退出码 1 | 删除类命令二次确认（同 F9/F36） |

### 14.3 验收锚点

- A1：数据模型 + 建表（create_all 自动，无 is_deleted 列）（M1）
- A2：服务校验链（六元组/实体存在/同项目/自环/同键冲突/角色↔角色合法）（M2）
- A3：API 契约（CRUD + 图谱聚合 + 错误映射）（M3）
- A4：图谱聚合合并 + 去重 + 孤立边防御 + 清理回调（M4）
- A5：CLI knowledge 组全绿（含 ci.yml integration-cli-backend 登记）（M5）
- A6：前端知识图谱 tab（画布/交互/增删改）+ 手工验证闭环（删实体 → 关系被清理无悬空边）（M6/M7）
