# F48: 知识图谱（knowledge-graph）— 功能规格

> **端**: cross
> **依据**: PRD v2.1 §6.2 P1-01/P1-06、[F9 角色](../f9-character/spec.md)、[F36 地图视图](../f36-world-map/spec.md)、Constitution P1-P6
> **依赖**: [F1 项目](../f1-project/spec.md) · [F9 角色](../f9-character/spec.md) · [F10 世界观](../f10-world-settings/spec.md) · [F11 大纲](../f11-outline/spec.md) · [F12 时间线](../f12-timeline/spec.md) · [F13 伏笔](../f13-foreshadowing/spec.md) · [F14 统一提取](../f14-extraction/spec.md) · [F36 地图视图](../f36-world-map/spec.md) · [F43 设定库 GUI](../f43-setting-library-gui/spec.md)
> **参考 ADR**: [ADR-019](../../adr/packaging/ADR-019.md)（版本里程碑）· [ADR-002](../../adr/architecture/ADR-002.md)（六边形分层）· [ADR-003](../../adr/database/ADR-003.md)（Repository）· [ADR-004](../../adr/database/ADR-004.md)（Pydantic v2）· [ADR-012](../../adr/architecture/ADR-012.md)（错误处理）· [ADR-030](../../adr/kernel/ADR-030.md)（本地内核服务）

---

## 1. 概述

为项目内六大设定实体（**角色 / 世界观条目 / 大纲 / 时间线事件 / 伏笔 / 地图 pin**）提供**跨实体关系图谱**：以通用关系表 `knowledge_relations`（实体-关系-实体）表达「角色↔世界观『属于』」「角色↔角色『关系』」「事件↔角色『参与』」等联系，在「知识图谱」tab 中以**图谱画布**可视化（节点=实体，边=关系），并支持**手动增删改关系**（CRUD 端点 + 前端 UI）。原「知识库 RAG」tab 改造为「知识图谱」；RAG 语义检索能力由独立检索页承接（不在本模块）。

**核心交付**：

```text
数据面:     knowledge_relations 表（通用跨实体关系，含 source 来源标记）
查询:       图谱聚合查询端点（单表读取：edges 全量来自 knowledge_relations）
写入:       关系 CRUD（API + CLI + 前端）
前端:       「知识图谱」tab（图谱画布：拖拽/缩放/点击详情/增删改）
交换:       drawio（mxGraph XML）导入 / 导出（§5.7）
预留:       关系提取的数据面 + 写入端口 + 契约（§5.5，提取实现属独立模块）
```

### 1.1 模块构成

| 维度 | 本模块 |
|------|--------|
| 新实体表 | 1 个：`knowledge_relations`（无 is_deleted——真删语义） |
| 新 API 端点 | 8 个（关系 CRUD 5 + 图谱聚合 1 + drawio 导出/导入 2） |
| 新 CLI 命令 | `inkflow knowledge` 组（graph 查询 + relation 子组 CRUD） |
| 核心机制 | 跨实体关系校验链（实体存在 + 同项目，服务层显式校验）+ 图谱聚合（**单表 `knowledge_relations`**）+ 图谱画布渲染 |
| 跨模块 MODIFY | F9 契约零改动（角色↔角色关系同表 `character↔character` 子空间，API/CLI/GUI 契约不变）；F10-F13/F36 实体校验只读复用（零改动）；前端 library.tsx rag tab 改造 |
| 错误面 | KnowledgeGraphServiceError 子类 422 / KnowledgeRelationNotFoundError 404 |

### 1.2 边界声明

- **不做关系之外的冗余**：关系只存 `knowledge_relations`，不在角色/世界观等实体表加关系字段（避免「JSON 嵌入 + 关系表」双份真相——F9 §1 同款原则）
- **角色关系数据面单表**：角色页关系管理（F9 `character_repo`）与图谱页角色↔角色关系**同写 `knowledge_relations` 的 `source_type='character' AND target_type='character'` 子空间**；图谱聚合 edges **单表读取**，无跨表合并/去重（§5.2）
- **不做定时/自动提取（本模块）**：提取任务属独立模块，本 spec 只定义其数据面 + 写入端口（`bulk_create_relations`）+ 提取契约（§5.5），不实现提取逻辑
- **不做检索页**：RAG 语义检索/向量检索 UI 由独立检索页承接
- **不做图谱布局算法自研**：渲染选型 @xyflow/react（§5.4/§12 决策 7）
- **不做实体详情编辑**：图谱节点点击详情 = 只读摘要 + 跳转对应实体页（角色/世界观/大纲/时间线/伏笔/地图编辑均在各自既有页面）
- **删除语义**：`knowledge_relations` 为**新表，无 is_deleted 列**——删除 = **真删**（同 F36 D1=B/D7；普通实体删除收敛真删，归档仅会话保留）

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
| relation_type | str | NOT NULL, 1-20 字符, 去空白 | 关系类型（自由文本，如「属于」「参与」「师徒」「伏笔指向」；受控词表归提取模块） |
| description | str | NOT NULL, DEFAULT "", ≤ 500 字符 | 关系说明（可空串） |
| source | str | NOT NULL, DEFAULT "manual", 枚举 | 关系来源：`manual`（手动创建）/ `ai`（关系提取写入，**预留值，当前不产生**） |
| created_at | datetime | NOT NULL | UTC |
| updated_at | datetime | NOT NULL | UTC，自动更新 |

**业务规则**：

1. **实体类型枚举**（EntityType）：`character`（characters 表）/ `world`（world_settings 表）/ `outline`（outlines 表）/ `timeline`（timeline_events 表）/ `foreshadow`（foreshadowings 表）/ `map_pin`（map_pins 表）——与六分类 tab 对齐（rag 除外，rag 是检索面非实体）
2. **跨实体无 DB FK**（决策 2）：source_id/target_id 无 ForeignKey 约束（跨 6 张表无法单列 FK）——实体存在性 + 同项目校验由**服务层显式执行**（§5.1 校验链），ORM FK 仅 project_id
3. **禁止自环**：`source_type == target_type AND source_id == target_id` → 422「关系两端不能是同一实体」（自环在图谱无意义且徒增噪音——F9 §2.3 同款规则）
3b. **允许角色↔角色**（决策 9）：`character→character` 是合法关系——图谱页与角色页同写本表 `character↔character` 子空间
4. **唯一约束**：`(project_id, source_type, source_id, target_type, target_id, relation_type)` 全唯一索引（手动创建防重复；同键重复创建 → 422「该关系已存在」；提取任务按此键做幂等去重）
5. **source 字段**：手动创建恒为 `manual`；`ai` 保留给关系提取写入（§5.5）——读取不限制 source（图谱聚合查询含全部 source）
6. **实体硬删 → 关系级联删除**（决策 3）：各实体真删后，其作为 source/target 的 knowledge_relations 行须删除——服务层/项目删除钩子显式清理（生产连接 FK 对跨表引用不生效，§5.3）
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
    """关系来源 — 手动创建；ai 值预留关系提取写入."""
    MANUAL = "manual"
    AI = "ai"          # 预留（关系提取写入），当前不产生 ai 行

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
        source: 关系来源（manual/ai，当前恒 manual）.
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
    """图谱边 — `knowledge_relations` 单表视图（无合并去重）.

    Attributes:
        id: 边 ID（恒 `"kr:<relation_uuid>"`）.
        source: 起点节点 ID（GraphNode.id 格式）.
        target: 终点节点 ID.
        label: 关系类型（relation_type）.
        description: 关系说明.
        source_table: 恒 `"knowledge_relations"`（单一来源）.
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

    设计约定（同 F9 角色关系表先例）:
    - DB 主键 int 自增；领域层 UUID 映射: domain_id = uuid.UUID(int=orm.id)
    - 全唯一索引 (project_id, source_type, source_id, target_type, target_id,
      relation_type) 保证「项目内同键关系唯一」
    - 跨实体无 DB FK（source_id/target_id 无 ForeignKey）——服务层显式校验
    - FK 级联: 项目删除 → 关系级联删除（生产连接 FK 语义见 §5.3）
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
> **FK 语义**：ORM 仅 project_id 声明 FK（供 create_all 建表）；跨实体 source_id/target_id 无 FK 可依赖——实体硬删 → 关系清理由 service 显式执行（§5.3），测试断言以 service 行为为准。

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/projects/{project_id}/knowledge-relations` | 创建图谱关系 → 201 |
| GET | `/api/v1/projects/{project_id}/knowledge-relations` | 关系列表（分页 + 过滤：`?source_type=&target_type=&relation_type=`；`?source=ai` 过滤（提取预留）） |
| GET | `/api/v1/projects/{project_id}/knowledge-graph` | **图谱聚合查询**（nodes + edges **单表 `knowledge_relations`**） |
| GET | `/api/v1/projects/{project_id}/knowledge-graph/export` | **导出 mxGraph XML**（`.drawio` 同构；`?format=mxgraph`，v1 唯一取值）→ `application/xml` 附件（§5.7） |
| POST | `/api/v1/projects/{project_id}/knowledge-graph/import` | **导入 mxGraph XML**（请求体 = 原始 XML；`?mode=merge\|replace`）→ 导入结果 JSON（§5.7） |
| GET | `/api/v1/knowledge-relations/{relation_id}` | 关系详情 |
| PATCH | `/api/v1/knowledge-relations/{relation_id}` | 更新关系（六元组可改 + description） |
| DELETE | `/api/v1/knowledge-relations/{relation_id}` | 真删关系（无 restore） |

> **无 restore 端点**（决策 5）：关系真删不可恢复——与 F9/F36 删除语义一致。
> **图谱聚合 vs 关系列表职责分离**：`knowledge-graph` 供画布渲染（节点+边，边**单一来源 `knowledge_relations`**）；`knowledge-relations` 供关系管理（列表/筛选/编辑——本表全部行，含角色↔角色关系行）。

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
    {"id": "kr:3", "source": "character:c0a8...", "target": "character:7b2d...",
     "label": "师徒", "description": "", "source_table": "knowledge_relations"}
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

**导出 mxGraph XML**：

```http
GET /api/v1/projects/1/knowledge-graph/export?format=mxgraph
→ 200
Content-Type: application/xml; charset=utf-8
Content-Disposition: attachment; filename*=UTF-8''<书名>-knowledge-graph.drawio

<mxfile host="InkFlow" ...> … <mxGraphModel>…</mxGraphModel> … </mxfile>
```

**导入 mxGraph XML**：

```http
POST /api/v1/projects/1/knowledge-graph/import?mode=merge
Content-Type: application/xml

<mxfile>…</mxfile>
→ 200
{"mode": "merge", "total": 3, "imported": 2, "skipped": 1, "failed": 0, "deleted": 0,
 "details": [{"kind": "skipped", "edge_id": "kr:…", "label": "师承",
              "reason": "该关系已存在（同键唯一）"}]}
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
| MxGraphImportError | 422 | 非法 mxGraph XML：<原因>（解析阶段失败——非合法 XML / 缺 `mxGraphModel` 根。**不 500**） |

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
                               --relation-type <text> [--description <text>] [--content-file <path>]
inkflow knowledge relation get <relation_id>
inkflow knowledge relation update <relation_id> [--relation-type <text>]
                                   [--description <text>] [--content-file <path>] [--source-id <UUID>] ...
inkflow knowledge relation delete <relation_id>                   # 真删
```

- F7 全局约定：`--json` 信封 / 退出码 0/1/2 / `VALIDATION_ERROR`/`NOT_FOUND`/`DB_ERROR` 映射
- 删除类命令二次确认（同 F9/F36）
- `graph` 输出 `nodes` + `edges` 两个数组（与 API 响应同构，`--json` 原样输出；文本模式打印 edges 摘要行 `source --label--> target`）

---

## 5. 关键差异：跨实体关系校验链 + 图谱聚合 + 手动 CRUD + 关系提取预留

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
                  ④ 落库（source 字段不可改——提取写入方才能置 ai）
delete_relation:  ① 关系存在 ② 真删单行
list_relations:   过滤（source_type/target_type/relation_type/source）+ 分页（offset/limit，created_at DESC）
```

### 5.2 图谱聚合查询（`graph(project_id, scope)`）

**数据源（单表）**：

```text
nodes:  = 六类实体节点（characters + world_settings + outlines + timeline_events
          + foreshadowings + map_pins，按项目过滤，**每表全量返回**——不走分页 list()）
          ——节点集范围由 scope 决定（见下）
edges:  = knowledge_relations（本项目全部，含 source=ai 预留；角色↔角色关系即
          source_type='character' AND target_type='character' 子空间行，同表）
去重:   —（单表 + 六元组全唯一索引，无跨表同键行）
```

**`scope` 节点集语义**：

```text
scope="related"（**默认**）:
  nodes = 参与至少一条 knowledge_relations 的实体
          （端点 ∈ 节点集者；即「有关系才上图」）
  ——无任何关系时**回退「角色全集」**（新项目首屏只看到角色块）
scope="all":
  nodes = 六类实体全量节点（完整体检视图；本地个人项目量级可达数百块）
端点级 scope: GET /projects/{pid}/knowledge-graph?scope=related|all（缺省 related）
```

> **设计动机**：全量节点灌进画布（数百块）时，用户预期是「默认只看到角色块，添加关系后才在线上与关联块显示地点/设定/伏笔」。
> `related` 让图谱随关系增长而展开；`all` 保留完整体检能力。
>
> ⚠️ **顺序约束（实现纪律）**：`related` 收窄必须发生在「孤立边过滤」**之前**，
> 且必须用**未过滤**的关系行计算关联集。否则「只在孤立边里出现的实体」会被自己从
> 节点集抹掉（例：`幽灵→乙` 与 `甲→乙`，若先用已过滤边集算，乙会因幽灵边被过滤而失联）。

**实现要点**：

- 节点 ID 格式 `"<entity_type>:<entity_uuid>"`（跨表唯一）；图谱边引用节点 ID（GraphNode.id）
- 查询 = 各实体 repo **全量方法**（`character_repo.list_all` / `world_repo.list_all_active` /
  `outline_repo.list_all` / `timeline_repo.list_all` / `foreshadow_repo.list_all`）
  + knowledge_relations repo `list_by_project`（**单表读取全部边**）；服务层组装 GraphNode/GraphEdge
- **性能**：单项目实体量级（本地个人项目，数百~数千条目）——列表查询即可，不做图数据库/缓存
  （F36 §2.2 同款「本地量级」论证）。`scope=all` 在数百块量级下由前端 React Flow 承担
  （暂不引入虚拟化）
- **孤立边防御**：knowledge_relations 中指向已不存在实体的行（实体硬删清理遗漏）——图谱查询时**跳过该边**（不 500），并记 loguru warning（与 F36 场景 6 同款容错）
- **不得走分页 `list()`**：默认 `limit=50` 会截断节点集（timeline / foreshadow 各 50 上限），
  并连带丢弃端点落在第 51+ 位的边——须走全量方法

### 5.3 实体硬删 → 关系级联清理（决策 3）

各实体真删后，其作为 source/target 的 knowledge_relations 行必须删除（否则图谱出现悬空边 + 唯一键残留）。**不修改各实体 service 契约**，采用 F36 钩子先例：

```text
接线（F36 §5.4 同款「可选回调」模式）:
  - knowledge_graph_service 暴露 cleanup_for_entity(entity_type, entity_id)（单事务 DELETE 相关行）
  - deps 装配时以可选回调注入各实体 service（character_service/world_service/outline_service/
    timeline_service/foreshadowing_service/map_service 的删除路径）
  - 各实体 service 删除成功后调用回调（默认 None 向后兼容，同 F36 决策 15）
  - 项目硬删：project_service hard_delete 加 knowledge_graph_cleanup 回调（同 F36 map_cleanup 模式）
```

> **⚠️ FK 不可依赖**：`knowledge_relations` 跨实体无 DB FK——即使全局 `PRAGMA foreign_keys=ON` 生效，实体硬删也不会 DB 级联删关系（无 FK 声明）——**清理必须由 service 显式执行**（与 F36/F43 P5 结论一致）。

### 5.4 手动增删改（前端交互，知识图谱 tab）

前端「知识图谱」tab（原 rag tab 改造）：

```text
tab 改造:   CATS 中 key='rag' → key='knowledge'（labelKey nav.lib.rag → nav.lib.knowledge）
            endpoint 从 /extractions/runs → 图谱画布组件（KnowledgeGraphCanvas）
            PATCH/DELETE_ENDPOINTS 继续排除 knowledge（图谱关系编辑走画布内交互，非列表行编辑）
            空态 CTA 从 navigate('/writing') → 图谱建关系引导（无实体时引导去各实体页创建）
图谱画布:   @xyflow/react（§12 决策 7）——节点=实体（类型着色 + 图标），边=关系（label=relation_type，有向箭头）
交互:       拖拽节点（布局自由排布 + 位置持久化）/ 滚轮缩放 / 点击节点 → 详情抽屉（只读摘要 + 「去编辑」跳转实体页）
            点击边 → 详情（关系类型/描述/来源）+ 编辑/删除按钮
            全量视图开关：「显示全部实体」→ `?scope=all`（缺省 related，见 §5.2）
            拉线建关系：从节点 Handle 拖到另一节点 → 本地即时成边 + 弹关系表单预填两端
            （落库走既有 POST /knowledge-relations；保存后随 graph 重拉收敛，失败不留幽灵边）
            画布提示（对齐 design/GUI/knowledge/knowledge.html）：「滚轮缩放 · 拖拽节点」
样式表:     `@xyflow/react/dist/style.css` 必须在 `src/main.tsx` 显式 import——
            库 CSS 提供 `.react-flow__node{position:absolute}`（缺 → 节点堆叠）、
            `.react-flow__edges{position:absolute}`、`.react-flow__edge-path{stroke:...}`
            （缺 → 边 stroke 无值 = SVG 默认 none = 边不可见）
Handle:     自定义节点 `KgNode` 必须渲染 `<Handle type="target" position={Position.Left}>` 与
            `<Handle type="source" position={Position.Right}>`——
            React Flow v12 无 Handle 会回退节点中心锚点（边仍可渲染），但 Handle 是
            **拉线建关系**的前置，不可省
            工具栏「新建关系」→ 表单（起点类型+搜索实体 / 关系类型 / 终点类型+搜索实体 / 描述）
关系列表:   tab 内可切换「图谱视图 / 关系列表」——列表模式复用 F9 角色关系管理交互（筛选/编辑/删除）
            分页：列表请求带 `?limit=&offset=`，下方渲染 Pagination（testIdPrefix
            `library-kg-page`）——不带分页参数会被后端默认 limit=50 截断，第 51 条起不可见
```

> **前端数据流**：图谱视图加载调 `GET /projects/{pid}/knowledge-graph`（一次拿 nodes+edges）；增删改后**局部刷新**（重拉 graph 或本地 patch 边列表——实现期定，测试契约见 §9）。

### 5.5 关系提取契约（数据面 + 提取契约；实现属独立模块）

> 定时任务设置放设置页；**必须配置大模型后才能用 AI 提取**。本模块交付本节数据面 + 写入端口（source 列 / 六元组唯一索引 / `bulk_create_relations`）；提取实现**零 schema 变更**，只补调度 + 提取服务 + 设置 + 端点/CLI/前端。

#### 5.5.1 范围与形态

- **调度形态**：进程内 asyncio 调度器（`KnowledgeExtractScheduler`），随内核 lifespan 启停——本地单机架构（§1.2），不引入 APScheduler/系统 cron 等外部依赖（可逆性：后续如需跨平台系统级调度，调度器接口不变只换驱动）
- **触发粒度**：小时级（`interval_hours`），每个周期遍历全部未删除项目各跑一次提取
- **提取方式**：`rule`（规则，确定性，无需模型）/ `ai`（LLM 模板提取，需已配置模型）/ `both`（先 rule 后 ai）
- **不做**：分钟级调度、分布式锁（单机无并发调度）、提取结果人工审核队列（ai 行直接落库，靠六元组幂等 + 图谱页手动删除兜底）、对角色关系行的改写——提取**只写 `knowledge_relations`**（`source='ai'`；角色关系行同表 `character↔character` 子空间，既有手动行靠幂等跳过保护）

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

- **lifespan 接线**（`api/app.py`）：startup `scheduler.start()` / shutdown `scheduler.stop()`；装配在 `api/deps.py`（`get_kg_extract_scheduler`）
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

- **前置门禁**：`provider_config_service.list()` 中**无任何 `key_saved=True` 的 provider** → 判定「未配置模型」→ 抛 `LLMNotConfiguredError`（新错误类，`domain/ports/knowledge_graph_errors.py` 追加）；端点映射 422；调度器 method=ai 时记 run error 并跳过该项目，method=both 时**降级为仅 rule**（warnings 记「AI 提取跳过：未配置模型」）
- **输入**：项目全部章节正文（chapter_repo，按 narrative 顺序拼接，截断上限 50000 字符——与 ExtractionRequest.text 上限一致）；无章节 → status=skipped（skipped_reason「无章节内容」）
- **LLM 契约**：复用 F14 extractor 模式（`_character_extractor.py` 先例：JSON 输出 + `_extract_json_fragment` 容错解析 + 校验失败重试一次）；prompt 模板内置于 `_kg_relation_extractor.py`（CREATE，私有模块同 F14 命名惯例），产出 `[{from_name, from_type, to_name, to_type, relation_type, description}]`；relation_type 1-20 字符约束同 §2.1
- **模型选择**：`config.llm_default_model` 唯一默认源（deps 注入），零硬编码
- **实体名称 → id 解析**：统一 `_resolve_entity(project_id, type, name)`——character/world/outline 走各 repo `get_by_name`；timeline 无 get_by_name → `list_all` 后 **title 精确匹配**（去首尾空白）；foreshadow 同 title 精确匹配；map_pin 不参与 AI 解析（AI 只产出五类：character/world/outline/timeline/foreshadow）。解析失败 → 该条关系丢弃 + warnings 汇总（F9 ExtractedRelation from_name/to_name 解析同款语义）
- **写入**：解析成功的关系统一走 `knowledge_graph_service.bulk_create_relations(project_id, relations, source=RelationSource.AI)`

**幂等语义（跳过不覆盖）**：六元组已存在 → 跳过，不更新 description——AI 重复提取不覆盖用户手动调整过的描述；`ExtractionResult.updated` 口径 = 0（ai 提取恒不更新），`created` = 实际新增行数，跳过数进 warnings（「N 条关系已存在，跳过」）。

#### 5.5.5 运行记录（复用 F14 extraction_runs）

- **不建自有表**：复用 `extraction_runs`——`ExtractionType` 新增第 7 值 `KNOWLEDGE_RELATION = "knowledge_relation"`（`backend/tests/unit/domain/models/test_extraction_models.py` 既有 `len(ExtractionType) == 6` 断言**同步改 7**）
- run 记录字段口径：`type=knowledge_relation`；`source_key=f"kg:{method}"`（rule/ai/both）；`status` success（created>0 或全幂等跳过）/ skipped（无章节/未启用）/ error（LLM 失败/未配模型走 error + error 文案）；手动触发与定时触发**同表同口径**（触发源不区分——运行记录不做 GUI 展示面，统一日志页承接）
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
- **未配置模型门禁**：前端以 models store `hasChatModel`（既有）判定——无已配置模型时「仅 AI」「规则+AI」选项 disabled + 提示文案「需先在模型设置中配置大模型」；已启用且 method 含 ai 时切走模型配置 → 设置卡片顶部 warning 条
- **900 行护栏**：settings.tsx 已接近上限，本卡片独立为 `components/knowledge-graph/KnowledgeExtractCard.tsx`（CREATE），settings.tsx 只挂载

#### 5.5.8 测试与 CI 登记

- **单测**：提取服务（规则集逐条 / 跨项目与已删跳过 / AI mock 解析与重试 / 未配模型抛错 / 名称解析失败 warnings / 幂等跳过 / both 降级）+ 调度器（disabled 跳过 / 逐项目执行 / 单项目异常不中断 / 每周期重读设置 / startup 补跑 / stop 幂等）
- **API**：extract 端点（200 / 404 / 422 未配模型 / 422 非法 method）+ status 端点
- **CLI**：extract 命令信封 / 退出码 / `--method` 透传——**新 CLI 测试文件须显式追加 ci.yml `integration-cli-backend` job 文件列表**（Windows pytest 不展开 glob）
- **前端**：设置卡片渲染（开关 / 频率 / 方式）+ AI 选项未配模型 disabled + 提示 + 立即运行按钮
- **覆盖率**：新模块行覆盖 ≥ 80%（ADR-027 同款）
- **后台任务 RED 陷阱**（F44 先例）：scheduler 测试不得泄漏 pending task（teardown cancel）；断言后台调用须 `await asyncio.sleep(0)`

#### 5.5.9 提取模块验收（本 spec 的 M 行不覆盖）

1. 设置页三键可读写（开关/频率/方式），PATCH 越界 422；调度器热生效（改频率后下一周期按新值）
2. 规则提取无需模型：mock 零 provider 配置 → rule 提取正常产出 R1/R2/R3 边（source=ai 列值恒 ai——规则与 AI 提取统一 source=ai 语义，区分靠 run 的 source_key）
3. 未配置模型：AI 提取禁用——端点 422 + 前端选项 disabled + 提示；both 降级 rule + warning
4. 幂等：重复运行 → created=0，关系数不增
5. 图谱聚合显示提取边 + 关系列表 `?source=ai` 可过滤（本模块既有能力，提取模块只验数据面打通）
6. 测试全绿 + ci.yml CLI 登记 + 900 行护栏合规

### 5.6 排序与确定性

- 关系列表：`created_at DESC`（新关系在前——F9/F10 同款）
- 图谱节点：按实体类型分组顺序返回（character → world → outline → timeline → foreshadow → map_pin，组内 `name ASC`）——画布布局稳定，非随机
- 图谱边：**单一来源 `knowledge_relations`**，组内 `created_at ASC`

### 5.7 drawio（mxGraph XML）导入 / 导出

> 形态选型与「为何不内嵌编辑器」见 **ADR-061**；本节只定义**交换格式 + 端点契约**。
> 铁律：只做**一次性格式转换**——`.drawio` 不落盘入库、不作第二真相源；导入复用既有校验链（§5.1）。

#### 5.7.1 交换格式（mxGraph XML v1）

三层固定结构（drawio 桌面版可原样打开）：

```xml
<mxfile host="InkFlow" type="device">
  <diagram id="inkflow-knowledge-graph" name="知识图谱">
    <mxGraphModel dx="800" dy="600" grid="1" gridSize="10" guides="1" tooltips="1"
                  connect="1" arrows="1" fold="1" page="1" pageScale="1"
                  pageWidth="850" pageHeight="1100" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <!-- 节点（六类实体）+ 边（knowledge_relations） -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

**节点**（`vertex="1"`，朴素 `mxCell`）：

```xml
<mxCell id="character:&lt;entity_uuid&gt;" value="角色甲"
        style="rounded=1;whiteSpace=wrap;html=1;fillColor=#…;strokeColor=#…;"
        vertex="1" parent="1">
  <mxGeometry x="40" y="40" width="140" height="40" as="geometry" />
</mxCell>
```

- `id` 恒 `<entity_type>:<entity_uuid>`（与 `GraphNode.id` 同构）——**导入解析实体的唯一锚点**
- `value` = `GraphNode.name`
- `style` / `mxGeometry` 仅服务 drawio 排版，**导入不读**

**边**（`edge="1"`，外层 `<object>` 包装）：

```xml
<object id="kr:&lt;relation_uuid&gt;" label="师承" tooltip="说明文本">
  <mxCell style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=classic;"
          edge="1" parent="1"
          source="character:&lt;uuid&gt;" target="world:&lt;uuid&gt;">
    <mxGeometry relative="1" as="geometry" />
  </mxCell>
</object>
```

- `id` 恒 `kr:<relation_uuid>`；`label` = `relation_type`
- `tooltip` = `description`（**描述为空则省略该属性**）——`<object>` 是 drawio 官方的「自定义元数据」载体（画布保存时保留），故描述在 drawio 里可读、可改、可回传
- `source` / `target` = 节点 `id`

**确定性（往返幂等的前提）**

| 维度 | 规则 |
|------|------|
| 节点集 | **仅「参与至少一条关系的实体」**（边的端点并集；无关系 → 空文件。**不含**无关系的孤立实体——文件表达的是关系图，不是实体清单） |
| 节点序 | 复用 §5.6 图谱节点序（六类组序 character→world→outline→timeline→foreshadow→map_pin，组内 `name ASC`） |
| 节点坐标 | 确定性网格：`x = 40 + col*200`、`y = 40 + row*60`（`col` = 类型序号 0-5，`row` = 该类型内序号）——**纯函数、零随机** |
| 边序 | `created_at ASC`（同 §5.6） |
| 端点缺失 | 关系指向的实体查不到（已被删）→ **跳过该边** + loguru warning（同 §7 边界 10 的孤立边口径，不生成悬空引用） |
| 文件名 | `<清洗后书名>-knowledge-graph.drawio`（Windows 禁符 `\ / : * ? " < > \|` → `_`；书名截断 60 字符；空书名 → `untitled`） |

#### 5.7.2 导出端点

```
GET /api/v1/projects/{project_id}/knowledge-graph/export?format=mxgraph
```

- `format: Literal["mxgraph"] = "mxgraph"`（v1 唯一取值；其它值 → FastAPI 422 短路，service 零调用）
- 成功 → `200`，`media_type="application/xml; charset=utf-8"`，
  `Content-Disposition: attachment; filename*=UTF-8''<URL 编码文件名>`（镜像 F21 export 的头部形态）
- 只读幂等：同数据两次导出 → **字节级一致**（含节点序/坐标/边序/时间戳均不出现在文件里）
- 项目不存在 → 404「项目不存在」

#### 5.7.3 导入端点

```
POST /api/v1/projects/{project_id}/knowledge-graph/import?mode=merge|replace
Content-Type: application/xml          请求体 = 原始 mxGraph XML 文本
```

**解析（`_mxgraph_codec.parse_mxgraph_xml`）**

1. XML 不可解析 / 根节点不是 `mxfile`/`mxGraphModel` / 找不到 `mxGraphModel` → **422 MxGraphImportError**（detail = `非法 mxGraph XML：<原因>`），**数据零变更**
   - 找不到 `mxGraphModel` 但存在**带非空文本的 `<diagram>`** → 说明是 drawio「导出为 XML 且勾选 Compressed」的 base64 压缩体，detail 须点明「压缩」（用户据此可取消勾选后重存）；空 `<diagram>` 不误报
2. 收集 cell：`mxCell` 与 `object`/`UserObject` 包装的 `mxCell` **都要认**（drawio 保存时两种形态都会出现）
   - 节点 cell = 带 `vertex="1"`（或带 `source`/`target` 之外的 `value` 且无 `edge`）——仅用于**端点解析**
   - 边 cell = 带 `edge="1"` **或**同时有 `source` + `target`
   - 可见文本：包装元素的 `label` 优先，否则 `mxCell` 的 `value`；描述：包装元素的 `tooltip`
3. 端点解析：`id` 按**第一个 `:`** 拆成 `<type>` / `<uuid>`；`type` 必须 ∈ `EntityType` 六值、`uuid` 必须可 `uuid.UUID(...)` 解析，否则该边计入 **failed**（reason「端点无法解析为 InkFlow 实体」）——**手工在 drawio 新画的节点属于此类**（文件里没有 InkFlow 实体标识）

**写入（复用 §5.1 校验链）**

- 每一条可解析的边 → 组装六元组 + description → 调 **`KnowledgeGraphService.create_relation`**（项目存在 → 自环 → 字段校验 → 实体存在且同项目 → 同键唯一 → 落库）
- `mode=merge`（默认）：不删除任何既有行；同键已存在（库内既有 **或** 文件内重复）→ `create_relation` 抛 `KnowledgeRelationConflictError` → 计入 **skipped**
- `mode=replace`：**先** `relation_repo.delete_by_project(pid)` 清空项目内既有关系（计数 → `deleted`），**再**逐边写入 —— 删除**只发生在解析成功之后**（非法 XML 不会造成数据丢失）
- 单行非法（自环 / 实体不存在或跨项目 / 字段非法）→ `KnowledgeGraphServiceError` 子类 → 计入 **failed** + reason（**不中断整批、不 500**）
- `source` 列恒 `manual`（导出/导入是用户动作，非 AI 提取）

**响应体（JSON）**

| 字段 | 类型 | 说明 |
|------|------|------|
| `mode` | `"merge" \| "replace"` | 回显 |
| `total` | int | 文件内**边 cell 总数**（含解析失败者） |
| `imported` | int | 实际落库行数 |
| `skipped` | int | 同键幂等跳过行数 |
| `failed` | int | 校验/解析拒绝行数 |
| `deleted` | int | `replace` 清空的既有行数（`merge` 恒 `0`） |
| `details` | `list[ImportIssue]` | 每条未导入边一条：`{kind: "skipped"\|"failed", edge_id, label, reason}` |

> **计数恒等式（测试锁定）**：`total == imported + skipped + failed`。

#### 5.7.4 交换格式的已知边界（诚实声明）

- **不创建实体**：导入只能在已存在实体之间建关系；drawio 里新画的节点无法映射
- **排版不回流**：节点坐标是视图态（GUI 存 `localStorage`），导入不读 `mxGeometry`
- **压缩保存的 drawio 不兼容**：drawio `.drawio` 默认保存为**未压缩** XML（官方文档：`compressXml` 默认 false），但只要用户走「File > Export as > XML」并保留默认勾选的 `Compressed`，`<diagram>` 内容就是 base64+deflate 压缩体 → 本 v1 不解析，返回 422 并**在错误信息中点明「压缩」**（真实压缩解码见 ADR-061「后续」栏，未承诺）
- **`replace` 具破坏性**：清空项目内既有关系（GUI 侧须**勾选确认**后才可提交）
- **XML 安全**：标准库 `xml.etree.ElementTree`（不解析外部实体）；本地单用户输入为用户自选文件。若未来暴露给远程调用方，需先引入 `defusedxml`（ADR-061 影响节）

---

## 6. 组织规则

- **目录归属**：新模块 `domain/models/knowledge_graph.py` + `domain/ports/knowledge_graph_errors.py` + `domain/ports/knowledge_relation_repository.py` + `domain/services/knowledge_graph_service.py` + `infrastructure/database/models|repositories/knowledge_graph*` + `api/routers/knowledge_graph.py` + `cli/commands/knowledge_graph.py` + 前端 `components/knowledge-graph/`——镜像 F9/F36 骨架（实体 + 仓储 + service + router + CLI + 前端组件）
- **deps 装配**：`api/deps.py` 新增 `get_knowledge_graph_service(db)`——注入 SQLiteKnowledgeRelationRepository + 六类实体 repo（只读校验）+ ProjectRepositoryProtocol（项目硬删钩子）；**不注入 CharacterRepositoryProtocol 读关系**（角色↔角色边同表）
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
| 7 | PATCH source 字段（试图改来源） | 422 KnowledgeRelationValidationError（source 不可改——提取写入方才能置 ai） |
| 8 | 关系不存在（get/update/delete） | 404 KnowledgeRelationNotFoundError |
| 9 | 项目不存在 | 404 ProjectNotFoundError（F10 复用） |
| 10 | 图谱查询遇孤立边（实体已被删但关系残留） | 跳过该边 + loguru warning（不 500） |
| 11 | 实体硬删 → 其关系行 | service 显式清理（cleanup_for_entity 回调，§5.3）——图谱无悬空边 |
| 12 | 项目硬删 → 关系行 | project_service hard_delete 钩子显式清理（§5.3） |
| 13 | map_pin 孤立（所属 map 已删） | pin 实体校验失败 → KnowledgeEntityNotFoundError；图谱查询节点生成时跳过孤立 pin + warning |
| 14 | 空项目图谱查询 | 200 `{"nodes": [], "edges": []}`（空图谱合法，前端显示空态引导） |
| 15 | 关系列表无匹配 | 200 `{"items": [], "total": 0}` |
| 16 | 六元组 source_type/target_type 非法枚举值 | 422 KnowledgeRelationValidationError（Pydantic Enum 校验） |
| 17 | 提取写入的 ai 行与 manual 行同键 | 唯一索引拒绝（写入方需幂等去重——§5.5） |
| 18 | 导出：`format` 传 `mxgraph` 之外的值 | 422（FastAPI Literal 短路，service 零调用） |
| 19 | 导出：项目内无任何关系 | 200 + 合法空 mxGraph XML（0 节点 0 边；前端提示「无可导出的关系」由 GUI 决定） |
| 20 | 导入：请求体非合法 XML / 缺 `mxGraphModel` | 422 MxGraphImportError（`非法 mxGraph XML：<原因>`）；**数据零变更**（`replace` 也不删） |
| 21 | 导入：边端点无法解析（手工在 drawio 新画的节点） | 该边计入 `failed` + reason「端点无法解析为 InkFlow 实体」；其余边照常导入 |
| 22 | 导入：文件内两条完全相同的边 | 第一条落库，第二条按同键幂等 → `skipped`（`total == imported + skipped + failed` 恒成立） |
| 23 | 导入：边指向跨项目实体 | `create_relation` 抛 KnowledgeEntityNotFoundError → 计入 `failed`（不 500、不中断整批） |
| 24 | 导入：`mode=replace` 且文件只有非法边 | 既有关系**已被清空**（`deleted` = 原行数），非法边全部计入 `failed`——GUI 侧须勾选确认（§5.7.4） |
| 25 | 导入：请求体 GBK/非 UTF-8 字节 | 422（解码失败归入 `非法 mxGraph XML`，不 500） |
| 26 | 导入：drawio「Export as XML + Compressed」产出的压缩体（`<diagram>` 内 base64，无 `mxGraphModel`） | 422 MxGraphImportError，detail 点明「压缩」（用户据此取消勾选后重存；本 v1 不解压，§5.7.4） |

---

## 9. 测试策略

### 层次

```text
单元（repo）:    knowledge_relations CRUD 往返 + 六元组唯一约束 + 过滤 + 真删 + delete_by_entity   ~14 cases
                实体全量方法（character/outline/foreshadowing list_all；world/timeline 既有）      ~6 cases
单元（service）: 校验链（实体不存在/跨项目/自环/同键冲突）+ 图谱聚合（单表全量，含角色↔角色子空间行）+ 清理回调
                + 孤立边防御 + bulk_create_relations 预留（提取面）                              ~20 cases
                + scope 节点集语义（related/all/回退角色全集/收窄先于孤立边过滤）               ~10 cases
API（集成）:     CRUD 端点 + 错误映射 + 图谱聚合响应形状 + ?scope= 透传                            ~13 cases
                 + drawio 导出/导入端点（XML 头/mode 透传/计数回报/非法 XML 422）                  ~10 cases
CLI:             knowledge 组命令 + graph 输出                                                      ~10 cases
前端:            图谱 tab 渲染/空态/建关系表单/边编辑删除（library-kg.test.tsx）                    ~8 cases
                + 画布契约（样式表 import/Handle/拖拽保持/持久化/拉线/scope 开关/提示）           ~9 cases
                + 关系列表分页（limit·offset/分页条/跨页可达/末页禁用）                            ~6 cases
                + drawio 工具栏/导入弹层（导出调用/选文件/mode 单选/replace 确认/结果回报）        ~7 cases
```

### 关键测试场景

1. **六元组校验闭环**：创建 character→world「属于」→ 201；实体不存在 → 422（detail 指明端）；跨项目实体 → 422
2. **自环拒绝**：同类型同 id → 422 KnowledgeRelationSelfLoopError
3. **同键唯一**：相同六元组重复创建 → 422 KnowledgeRelationConflictError
4. **图谱聚合（单表）**：knowledge_relations 含跨实体边 + 角色↔角色子空间边 → edges 一次全量返回，`source_table` 恒 `"knowledge_relations"`
5. **图谱边 ID 形态**：所有边 `id` 恒 `"kr:<uuid>"`
6. **孤立边防御**：关系指向已删实体 → graph 查询跳过该边 + 不 500（mock 实体 repo 返回 None）
7. **实体硬删清理回调**：mock 实体 service 删除路径 → cleanup_for_entity 被调用（DELETE 相关行）；默认 None 向后兼容
8. **项目硬删钩子**：project_service hard_delete → knowledge_graph_cleanup 被调用
9. **source 字段**：创建恒 manual；PATCH source → 422（不可改）；?source=ai 过滤返回空（当前无 ai 行）
10. **map_pin 校验链路**：pin 存在 + 所属 map 项目匹配 → 通过；pin 孤立 → 422
11. **Pydantic 边界**：relation_type 空白/21 字符 → 422；description 501 字符 → 422
12. **空图谱**：无实体无关系 → 200 `{"nodes": [], "edges": []}`
13. **前端图谱 tab**：mock graph API → 画布渲染节点/边；点击边 → 详情 + 删除；空态引导（RTL + vi.mock，同 library-p*.test.tsx 模式）
14. **scope 节点集**：`scope=all` → 六类全量且**分页 `list()` 一次都不被调用**；`scope=related`（默认）→ 只留参与关系的实体；无关系 → 回退角色全集；无关系且无角色 → 空；🔴 **收窄先于孤立边过滤**（`幽灵→乙` + `甲→乙` → 乙必须保留、幽灵边被跳过）
15. **画布契约**：`main.tsx` 含 `@xyflow/react/dist/style.css` import（可证伪：删则 FAIL）；每节点 source/target 两个 `.kg-handle`；拖拽后位置不被网格覆盖；拖拽结束写 `localStorage`；连线 → 关系表单预填两端；`library-kg-scope-all` 反映 scope
16. **关系列表分页**：首屏 `?limit=50&offset=0`；`library-kg-page-*` 三件套；next → `offset=50` 且第 51 条可见；首页 prev 禁用 / 末页 next 禁用
17. **自动化盲区**：jsdom 无真实指针几何与 SVG 布局测量 → **拖拽位移/缩放/边可见性/线条避让只能靠真实浏览器（人工或 Playwright）复验**；本层契约只证明「结构/接线/props」正确
18. **drawio 往返幂等**：真 DB 建「角色甲 --师承--> 角色乙」+「角色甲 --属于--> 世界观丙」→ 导出 `xml1` → 导入（merge，同项目）→ 全部命中同键 → `imported=0 / skipped=2` → 再导出 `xml2` → **`xml1 == xml2` 逐字节相等**（导出/导入→再导出 结果稳定）。反例守护：若导出含时间戳/随机坐标/随机 id，此用例必 FAIL
19. **drawio 冲突跳过与计数恒等**：文件含 1 条新边 + 1 条既有边 + 1 条自环边 → `imported=1 / skipped=1 / failed=1 / total=3`（`total == imported + skipped + failed`）
20. **drawio 非法 XML 不落库**：`<mxfile>` 截断 / 无 `mxGraphModel` → 422 + detail 含「非法 mxGraph XML」；**`mode=replace` 下亦不删除任何既有行**（先解析后删除）；非 UTF-8 字节同样 422 不 500
21. **drawio 端点解析拒绝**：手工新画节点（id 形如 `X1a2b`）参与的边 → `failed` + reason 含「端点无法解析」；指向**其它项目**实体的边 → 走既有校验链 → `failed`（reason = 实体不存在/不在同一项目），HTTP 仍 200
22. **drawio replace 语义**：项目内既有 2 条关系，导入只含 1 条新边的文件（`mode=replace`）→ `deleted=2 / imported=1`，库内最终恰 1 行；`merge` 同文件 → `deleted=0 / imported=1`，库内 3 行

### 覆盖率

模块行覆盖 ≥ 80%；全仓门禁 ADR-027（M8 验收前先跑 coverage-backend 等价命令实测，留补测 buffer——F36 同款）。

---

## 10. 不在范围内

| 项 | 原因 |
|----|------|
| 定时任务 AI/规则提取关系 | 独立模块（本模块仅预留数据面 + 写入端口 + 契约，§5.5） |
| 知识图谱检索页（RAG 语义检索/向量检索 UI） | 由独立检索页承接（原 rag tab 的检索能力） |
| 统一日志页（内核/GUI/AI 日志分类展示与查询） | 提取运行记录不保留在图谱 tab；统一日志页是独立功能 |
| F14 extraction_runs 列表展示 | 不保留在图谱 tab；是否并入统一日志页由日志页决定 |
| 实体详情编辑（图谱内直接改角色/世界观内容） | 各实体编辑在既有页面闭环（图谱节点详情 = 只读摘要 + 跳转） |
| 图谱布局算法自研/力导向自动布局调优 | 选型 @xyflow/react 自带布局；深度调优无场景 |
| 关系类型受控词表/规则引擎 | 自由文本可用；词表归提取模块 |
| 图谱分享（多渠道分发/云链接） | 本地单机架构（ADR-030）无分享场景；文件导出（drawio）见 §5.7 |
| 图谱节点隐藏/筛选（按类型过滤显示） | 实体量级小，全量显示；前端可后续加 |
| 多项目关系共享 | 本地单机 + 强 project_id 隔离（F9/F36 同款） |

---

## 11. 依赖关系

```text
F48 依赖:
  F1（projects 表 + ProjectRepositoryProtocol）— 项目存在性校验 + 项目硬删钩子
  F9（characters）— 实体校验（角色）；角色关系数据面与本表同源（character↔character 子空间，契约零变更）
  F10（world_settings）— 实体校验（世界观条目，只读复用）
  F11（outlines）— 实体校验（大纲，只读复用）
  F12（timeline_events）— 实体校验（时间线事件，只读复用）
  F13（foreshadowings）— 实体校验（伏笔，只读复用）
  F36/F43 P2（maps + map_pins）— 实体校验（地图 pin，经 map→project 链路，只读复用）
  F14（extractions/runs）— 原 rag tab 数据源（本模块改造展示面，不依赖其端点）
  F7（CLI 全局约定）— knowledge 组信封/退出码

F48 被依赖:
  关系提取模块 — 依赖 knowledge_relations 表结构 + source 列 + bulk 写入端口（§5.5）
  检索页 — 依赖 rag tab 改造后的定位
  统一日志页 — 可选依赖 F14 extraction_runs 数据（是否并入由日志页决定）
```

---

## 12. 决策表

全 spec 唯一决策落点，正文以「§12 决策 N」引用。

| 决策点 | 选择 | 理由 | 备选（否决） |
|--------|------|------|--------------|
| 1 关系数据模型 | 新建通用关系表 `knowledge_relations`：六元组（source_type+source_id / target_type+target_id）+ relation_type + description + source；project_id 冗余 | 表达六类实体任意对；图谱聚合单一查询面；F9 契约零改动（角色↔角色走同表子空间） | 扩展 `character_relations` 加 entity_type 列（破坏 F9 角色关系语义）；每对实体一张表 30 张（表爆炸 + N 次 JOIN）；实体表加 relations JSON 列（双份真相、无法索引/级联）；迁移合并进 character_relations（破坏既有 API/CLI/GUI 契约） |
| 2 跨实体引用完整性 | source_id/target_id 无 DB FK，实体存在 + 同项目由 `knowledge_graph_service` 分派各实体 repo 显式校验；各实体错误类转换为 `KnowledgeEntityNotFoundError` | 跨 6 张表无法单列 FK；服务层统一错误面（跨模块调用方只面对图谱契约）；F35/F36 同款 | 每实体对建 FK（不可行）；透传各实体错误类（错误面分散） |
| 3 实体硬删清理 | `cleanup_for_entity` 可选回调 + deps 注入各实体 service 删除路径 + project `hard_delete` 钩子 | 不修改各实体 service 公共契约（默认 None 向后兼容）；防悬空边 + 唯一键残留 | 各实体 service 硬编码清理（破坏 F9-F13 契约）；依赖 DB FK（跨表无 FK） |
| 4 图谱聚合 | nodes 范围由 `scope` 决定（`related` 默认 = 参与关系者，无关系回退角色全集 / `all` = 六类全量）+ edges 单一来源 `knowledge_relations` | 单一查询面（前端零二次聚合）；`related` 让图谱随关系增长展开，`all` 保留完整体检 | 全量节点恒显示（数百块裸奔可用性差）；edges 合并多表并去重（跨表同键维护成本） |
| 5 删除语义 | 无 `is_deleted`，DELETE 物理删除 | 普通实体删除收敛真删（F36 D1=B/D7）；新表零历史包袱 | 带 `is_deleted` 软删（与真删口径冲突、需 restore 面） |
| 6 source 列预留 | `manual`/`ai` 枚举 + 六元组唯一索引 = AI 幂等去重键；`bulk_create_relations(project_id, relations, source=ai)` 写入端口 | 数据面先行；提取实现零 schema 变更 | 提取落地时再加列（已发布后加列迁移成本） |
| 7 / 10 前端可视化选型 | @xyflow/react（React Flow v12，MIT，React 19 兼容） | 节点/边渲染 + 拖拽/缩放/自定义节点开箱即用；零布局自研；React 生态事实标准 | 手写 SVG/Canvas（拖拽/缩放/布局全自研，工作量翻倍）；antv G6（重依赖，非 React 原生）；d3-force（无现成交互） |
| 8 tab 改造 | CATS key `rag`→`knowledge`；图谱画布 + 关系列表；PATCH/DELETE 继续排除 | 检索面与图谱混放会 tab 膨胀；检索能力改由独立页承接 | 新增第 7 个 tab（六分类 + 图谱并存） |
| 9 角色↔角色关系 | 图谱页可建（写本表）；角色页关系管理同写本表 `character↔character` 子空间 | 图谱手动编辑闭环完整；F9 零破坏；个人项目可接受 | 图谱禁止角色关系（编辑流断裂）；F9 改写他表（破坏既有契约） |
| 11 提取运行记录去向 | 图谱 tab 不展示 `extractions/runs`；运行日志统一由独立日志页承接 | 图谱 tab 聚焦关系；runs 是过程日志非日常查看对象 | 图谱 tab 内嵌提取记录区（三视图拥挤）；等检索页一起决定（推迟交付） |
| 12 提取契约 | ① 进程内 asyncio 调度器（lifespan 启停 + 启动补跑 + 每周期重读设置），不引入 APScheduler/系统 cron；② run 记录复用 F14 `extraction_runs`（ExtractionType 第 7 值），不建自有表；③ 六元组幂等 = 跳过不覆盖（AI 不覆盖手动调整的 description）；④ 规则提取三规则集只读结构化字段（`WorldSetting.parent_id` / `Foreshadowing.event_id` / `MapPin.location_id+ref_id`），零 LLM；⑤ 提取只写 `knowledge_relations`（不碰角色关系既有行，同表子空间）；⑥ 未配置模型（provider_config 无 `key_saved=True`）→ AI 禁用：端点 422 + 前端选项 disabled + both 降级 rule | 本地单机架构进程内调度最简单可逆；复用 run 表面零新表零 GUI 面；跳过不覆盖保护用户手动编辑；规则集确定性可测试 | 系统 cron/schtasks（跨平台三套 + 内核外生命周期失控）；自建 kg_extraction_runs 表（无展示面纯冗余）；幂等覆盖更新（破坏用户手动编辑）；AI 提取写角色关系表（破坏 F9 契约） |
| 13 drawio 交换 | 导出/导入两个单向端点；`.drawio` 不落盘入库、不作第二真相源；导入逐行**复用既有校验链** `create_relation`（冲突按幂等跳过 + 计数回报）；格式由 `domain/services/_mxgraph_codec.py` 纯函数承担（标准库 XML） | 可离线、零体积、零第二真相源；不新增校验路径（导入与单条创建同一错误面）；渲染栈无关 | drawio iframe 内嵌（需外网，违 ADR-020）；drawio 桌面包内嵌（上百 MB + `.drawio` 成第二可编辑真相源，违 ADR-030）；自研私有 JSON（生态为零，用户诉求落空） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 数据模型 + 建表（create_all 自动，无 is_deleted） | `pytest backend/tests/unit/infrastructure/database/test_knowledge_relation_repo.py -v` 全绿；新库表存在（PRAGMA table_list）；knowledge_relations 无 is_deleted 列 |
| M2 | 服务校验链（六元组/实体存在/同项目/自环/同键冲突/角色↔角色合法） | `pytest backend/tests/unit/domain/services/test_knowledge_graph_service.py -v` 全绿（character→character 合法分支；角色↔角色行与其它边同为 knowledge_relations 行，无跨表去重用例） |
| M3 | API 契约（CRUD + 图谱聚合 + 错误映射） | `pytest backend/tests/unit/api/routers/test_knowledge_graph_api.py -v` 全绿 |
| M4 | 图谱聚合（**单表**）+ 孤立边防御 + 清理回调 | service 聚合测试全绿（edges 全量来自 knowledge_relations 含角色↔角色子空间/孤立边跳过/cleanup_for_entity 回调；无跨表合并去重用例） |
| M5 | CLI knowledge 组 | `pytest ../tests/cli/test_cli_knowledge_graph.py -v` 全绿（**且已追加 ci.yml integration-cli-backend job**） |
| M6 | 前端知识图谱 tab（画布/交互/增删改） | `frontend` vitest `library-kg.test.tsx` + `library-kg-canvas-1325.test.tsx` + `library-kg-page-1325.test.tsx` 全绿（@xyflow/react 渲染，§12 决策 7）；手工验证：切到知识图谱 tab → 画布渲染节点 + **连线可见** → 拖拽/缩放（位置保持）→ 从节点 Handle **拉线** → 关系表单预填两端 → 保存 → 边出现 → 点击边详情 → 删除 → 「显示全部实体」切 `scope=all` |
| M7 | 手工验证闭环 | 建角色+世界观 → 图谱建「属于」关系 → 图谱显示 → 角色页建角色关系 → 图谱页显示该边（**同表，无需合并**）→ 删关系 → 删实体 → 关系被清理（无悬空边） |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；ADR-027 门槛（先跑 coverage-backend 等价命令实测留 buffer）；`uv run ruff check src/ tests/unit/ ../tests/` + mypy 通过；前端 `pnpm lint` + `tsc --noEmit` |
| M9 | drawio（mxGraph XML）导入/导出 | 三层测试全绿：① `backend/tests/unit/domain/services/test_knowledge_graph_mxgraph_1360.py`（编解码纯函数 + service）；② `backend/tests/unit/api/routers/test_knowledge_graph_mxgraph_api_1360.py`（端点契约）；③ `tests/integration/test_knowledge_graph_mxgraph_roundtrip_1360.py`（**真 DB 往返幂等：导出→导入→再导出逐字节相等**）。手工验证：图谱 tab 点「导出 drawio」→ 得到 `.drawio` 文件（drawio 桌面版可打开、节点/边/关系类型标签正确）→ 在 drawio 里改一处标签 → 「导入 drawio」选文件 + `merge` → 回报 imported/skipped/failed 计数 → 画布刷新；`replace` 须勾选确认后方可提交。前端 vitest drawio 用例全绿；契约生成物（openapi 快照 + d.ts）已刷新；三件套（原型 HTML + PNG + `specs/f19-gui/knowledge.md`）同 PR 同步 |
