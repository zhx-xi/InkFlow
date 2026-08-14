# F36: 世界观地图视图（world-map）— 功能规格

> **Spec 版本**: 1.3 | **日期**: 2026-08-14 | **依据**: 设计书 `design/world-geo-hierarchy-2026-08-08.md` §5（workspace）、PRD v2.1 §6.2 P1-02、F10 spec + F35 spec v1.1（地点树，本模块数据基础）、Constitution P1-P6
>
> **Spec 变更**（1.2 → 1.3，2026-08-14 #368 拍板）：新增**图挂图层级**（maps 表加 `parent_map_id`）——语义区分 `root_location_id`（图关联世界观条目，保留）+ `parent_map_id`（图挂父图，新增）；一父多子（1:N）+ 子单父（N:1）+ 层级深度不限；根图 parent_map_id=null，子图 parent_map_id=父图 id；前端「创建子图」传父图 id（parent_map_id）而非条目 id；后端校验父图存在 + 同项目（422 新错误 `MapParentMapNotFoundError`）。同步：§2.1 maps 表 + 业务规则、§2.3 领域模型、§2.4 ORM、§3.1 端点总览、§5.4 服务层校验链、§7 错误表、§12 决策 16、§13 M3/M4 验收。
>
> **Spec 变更**（1.1 → 1.2，2026-08-09 实现期修订）：① §8 补 5 行 MODIFY（world_service/project_service 钩子接线、http client post_file/put_file/get_bytes、pyproject python-multipart、ci.yml 登记）；② §12 补决策 13-15（get_pin 新增裁定、python-multipart 依赖、钩子接线形态）。
>
> **Spec 变更**（1.0 → 1.1，2026-08-09 拍板）：Q1-Q3 全拍板——**Q1=B（drill-down + 面包屑一起）**；**Q2=A（真删删文件——删除语义收敛为真删，无归档窗口）**；Q3=A（root_location 过滤）。**删除语义重设计（D1-D7）**：maps/map_pins **新表无 is_deleted 列**（真删，无恢复）；地图删除 = 确认后真删 + **有子地图时强制选择**（`?cascade=true` 级联删 / `?reparent_to=<map_id>` 子地图改挂新父——目标父地图自动补 pin，D3）；**FK 运行时由 service 显式级联（D10=b，生产连接未开 foreign_keys=ON）**；children 查询补地点软删过滤（评审 F2）；地图树 drill-down 与 #175 复制共用地点→地图查询（评审 S10）。
>
> **所属阶段**: 0.6.0 世界观三连 Step 2（呈现层，估算 5-8 人天）
>
> **关联 Issues**: [#174](https://github.com/zhx-xi/InkFlow/issues/174)（本模块）· #173（地点树，**前置依赖**）· #175（跨书复制，**依赖本模块**的地图资产复制）· #211（删除语义统一，**关联登记**）
>
> **依赖**: ✅ F10（world_settings + WorldRepositoryProtocol——pin 关联地点校验）· ✅ F35（#173 地点树：root_location_id 挂地点树 + ancestors/descendants 导航）· ✅ F1（项目 FK）
>
> **参考 ADR**: [ADR-019](../../adr/ADR-019.md)（版本里程碑）· [ADR-002](../../adr/ADR-002.md)（六边形分层）· [ADR-003](../../adr/ADR-003.md)（Repository）· [ADR-004](../../adr/ADR-004.md)（Pydantic v2）· [ADR-012](../../adr/ADR-012.md)（错误处理）
>
> **状态**: ✅ 已实现（PR #220，#174 2026-08-09）

---

## 1. 概述

为世界观地点提供**地图视图**：上传本地图片 + pin 标记 + 关联地点条目。行业成熟形态（WorldAnvil 验证，设计书 §2.2 认知纠偏）：**地图 = 图片 + pin + 关联条目**，**不做内置绘图引擎**（与 Procreate/Inkarnate 竞争是金锤子）。

**核心交付**：

```text
F35 现状:  地点树（parent_id + ancestors/descendants 导航能力）
F36 增量:  新表 maps（图片地图）+ map_pins（标记）——【无 is_deleted，真删语义】
           + 本地图片资产存储（内核数据目录，DB 存相对路径）
           + 地图树 drill-down（点 pin 进入子地图，叙事层级缩放，Q1=B）
           + 面包屑导航（复用 F35 ancestors）
           + 删除：确认后真删 + 子地图级联/reparent（D1-D7）
```

### 1.1 模块类型定位（第 15 变体「地图实体 + 本地资产型」）

按 AGENTS.md 模块类型谱系计数（f15=6 / f16=7 / f23=8 / f19=9 / f26=10 / f24=11 / f25=12(移除) / f30=13 / f32=14），本模块为 **第 15 变体「地图实体 + 本地资产型」**：F9/F10 实体 CRUD 骨架 × F19 本地内核资产（数据目录文件系统）——新实体表 + 本地文件资产存储 + pin 关联既有实体。

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ✅ 2 个：`maps` + `map_pins`（**均无 is_deleted——真删语义**） |
| 新 API 端点 | ✅ ~13 个（地图 CRUD + pin CRUD + 图片上传/下载 + children；**无 restore**） |
| 新 CLI 命令 | ✅ `inkflow map` 组（create/list/get/update/image/delete/pin 子组/children；**无 restore**） |
| 核心机制 | ✅ 本地图片资产（相对路径 + FileResponse）+ 相对百分比坐标 + **真删 + 子地图级联/reparent** |
| 跨模块 MODIFY | ✅ F10/F35 只读复用（location 校验，零改动）；#175 复制复用地点→地图查询 |
| 错误面 | MapServiceError 子类 422 / MapNotFoundError 404 / 文件层错误 500 |

### 1.2 边界声明

- **不做绘图引擎**（设计书 §5.3：金锤子规避，Phase 3+）
- **不做 LLM 自动生成地图**（质量不可控；底图素材 AI 辅助独立立项，§10）
- **不做相邻关系**（neighbors：树是叙事高频，图是低频补充，extra 预留，Phase 3+）
- **不做图片云上传/服务**（本地单机架构既定，ADR-030；文件存内核数据目录）
- **删除语义（2026-08-09 拍板）**：maps/map_pins 为**新表，无 is_deleted 列**——删除 = **真删**（物理删除 + 图片文件删除，无恢复）；与 F10 既有软删语义的差异与统一登记见 #211（0.8.0）
- **依赖 #173 地点树先合入**：pin 关联地点需要地点树存在（issue body 显式依赖声明）

---

## 2. 数据模型

### 2.1 maps 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK 自增 | 领域层 UUID 映射（F1 惯例） |
| project_id | int | NOT NULL, FK→projects.id, 已索引 | 所属项目（D4：地图归属世界观，复用随世界观走） |
| name | str | NOT NULL, 1-50 字符, 去空白 | 地图名（如「东大陆全图」「清河县城图」）；项目内地图名唯一 |
| image_path | str | NOT NULL | 本地图片相对路径（相对 config.data_dir，如 `maps/1f2a.../main.png`） |
| description | str | NOT NULL, DEFAULT "", ≤ 500 字符 | 地图描述/备注 |
| root_location_id | int \| NULL | FK→world_settings.id, 可空, 已索引 | 本图对应的父地点；NULL = 全局图（v1.3：与 parent_map_id 语义独立——图关联世界观条目） |
| parent_map_id | int \| NULL | FK→maps.id, 可空, 已索引 | **v1.3 #368 新增**：本图的父图（图挂图层级）；NULL = 根图；子图 parent_map_id=父图 id |
| created_at | datetime | NOT NULL | UTC |
| updated_at | datetime | NOT NULL | UTC，自动更新 |

**业务规则**：

1. **一个地点最多一张图**：unique `(project_id, root_location_id) WHERE root_location_id IS NOT NULL`（设计书 §5.1「每个父地点可挂一张图」）；全局图（NULL）允许多张（不同主题/用途）——**无 is_deleted，普通 unique 即可**（真删语义下无软删行参与唯一性）
2. **name 项目内唯一**：unique `(project_id, name)`（真删语义下直接唯一）
3. **root_location_id 校验**：必须指向**同项目活动地点**（F35 校验链复用）——跨项目/软删地点 422
4. **parent_map_id 校验（v1.3 #368）**：必须指向**同项目存在的地图**（图挂图层级）——父图不存在/跨项目 422（`MapParentMapNotFoundError`）；**层级深度不做限制**（不做最大深度校验）；根图 parent_map_id=null
5. **root_location_id 变更**（PATCH）：允许改挂（换父地点/改全局）；改挂后地图树导航自动跟随（导航是查询不是快照）
6. **懒构建**：任何层可断——父地点无图/地点无父节点均合法（设计书 §5.2）；`children` 查询空列表不是错误

### 2.2 map_pins 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK 自增 | 领域层 UUID 映射 |
| map_id | int | NOT NULL, FK→maps.id, 已索引 | 所属地图 |
| location_id | int \| NULL | FK→world_settings.id, 可空, 已索引 | 关联地点条目；NULL = 纯注释 pin |
| x | float | NOT NULL, 0-100 | 相对图片宽度百分比坐标 |
| y | float | NOT NULL, 0-100 | 相对图片高度百分比坐标 |
| label | str | NOT NULL, 1-50 字符, 去空白 | pin 显示文本（关联地点 pin 也显式提供——前端默认填地点名，后端不自动取） |
| created_at | datetime | NOT NULL | UTC |
| updated_at | datetime | NOT NULL | UTC，自动更新 |

**业务规则**：

1. **坐标相对百分比**：0-100 浮点（Pydantic `ge=0, le=100`）——与图片分辨率解耦（设计书 §5.1），图片换图不失效
2. **location_id 校验**：指向**同项目活动地点**；NULL = 纯注释 pin（设计书 §5.1）
3. **label 必填**（纯注释 pin 与关联 pin 均有）；换图后 pin 保留（坐标百分比语义）
4. **无 pin 数量上限**（本地量级，列表查询即可）
5. **FK 由 service 显式维护（D10=b）**：生产连接未开 `PRAGMA foreign_keys=ON`——硬删地点/地图/项目时，级联与 SET NULL 由 service 单事务显式执行（§5.4），**不依赖 DB FK 动作**

### 2.3 领域模型（`domain/models/map.py`，镜像 F10 风格）

```python
class WorldMap(BaseModel):
    """地图领域实体 — 对应 maps 表（无 is_deleted——真删语义）."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    image_path: str                # 相对 config.data_dir 的路径（如 maps/<uuid>/main.png）
    description: str = ""
    root_location_id: uuid.UUID | None = None
    parent_map_id: uuid.UUID | None = None   # v1.3 #368：图挂父图；None=根图（必须带默认值，兼容既有构造）
    created_at: datetime
    updated_at: datetime


class WorldMapCreate(BaseModel):
    """创建地图请求 DTO — 图片文件走 multipart，不在 body."""
    project_id: uuid.UUID
    name: str
    description: str = ""
    root_location_id: uuid.UUID | None = None
    parent_map_id: uuid.UUID | None = None   # v1.3 #368：图挂父图；None=根图


class WorldMapUpdate(BaseModel):
    """更新地图元数据请求 DTO（不换图；换图走 PUT /maps/{id}/image）.

    root_location_id: None 表示不修改；出现且为 null = 改为全局图（与 F35 parent_id 同款
    exclude_unset 语义）.
    """
    name: str | None = None
    description: str | None = None
    root_location_id: uuid.UUID | None = None


class MapPin(BaseModel):
    """地图 pin 领域实体 — 对应 map_pins 表（无 is_deleted——真删语义）."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    map_id: uuid.UUID
    location_id: uuid.UUID | None = None
    x: float
    y: float
    label: str
    created_at: datetime
    updated_at: datetime


class MapPinCreate(BaseModel):
    """创建 pin 请求 DTO."""
    location_id: uuid.UUID | None = None
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    label: str = ""


class MapPinUpdate(BaseModel):
    """更新 pin 请求 DTO — 全可选，exclude_unset 语义.

    location_id: None = 不修改；出现且为 null = 转为纯注释 pin.
    """
    location_id: uuid.UUID | None = None
    x: float | None = None
    y: float | None = None
    label: str | None = None
```

### 2.4 ORM（`infrastructure/database/models/map.py`）

```python
class MapORM(Base):
    """地图 ORM — 映射到 maps 表（无 is_deleted，真删语义）."""

    __tablename__ = "maps"

    __table_args__ = (
        Index("uq_maps_name", "project_id", "name", unique=True),
        Index("uq_maps_root_location", "project_id", "root_location_id",
              unique=True, sqlite_where=text("root_location_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    image_path: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    root_location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_settings.id"), nullable=True, index=True,
    )
    parent_map_id: Mapped[int | None] = mapped_column(  # v1.3 #368：图挂父图（自引用 FK）
        Integer, ForeignKey("maps.id"), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )


class MapPinORM(Base):
    """地图 pin ORM — 映射到 map_pins 表（无 is_deleted，真删语义）."""

    __tablename__ = "map_pins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    map_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("maps.id"), nullable=False, index=True,
    )
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_settings.id"), nullable=True, index=True,
    )
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )
```

> **迁移（零迁移声明）**：`maps`/`map_pins` 是**新表**——由 `Base.metadata.create_all` 自动创建（无 alembic 基建，F1 惯例），**无需幂等迁移**（区别于 F35 的加列迁移）。既有库升级：lifespan `create_tables()` 自动建新表。
> **⚠️ FK 语义说明（D10=b）**：ORM 声明 FK 约束（供 create_all 建表），但**生产连接未开 `PRAGMA foreign_keys=ON`**——运行时级联/SET NULL 一律由 service 显式执行（§5.4），测试断言以 service 行为为准（不依赖 DB FK 动作；测试 fixture 若开 FK，行为与 service 显式一致）。

### 2.5 决策论证表

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **图片存本地文件系统 + DB 相对路径（选定）** | 与本地单机架构一致；DB 不膨胀；FileResponse 直出 | 跨设备/备份需复制数据目录（既定成本） | ✅ 设计书 D3/D4 |
| 图片存 DB BLOB | 单文件备份 | SQLite 膨胀、读写大文件低效、无直接文件路径 | ❌ 否决 |
| 坐标存像素绝对值 | 简单 | 换图失效；分辨率耦合 | ❌ 否决（相对百分比 0-100，设计书 §5.1） |
| root_location_id 硬编码层级跳转 | 实现简单 | 地图树与地点树脱钩，drill-down 断链 | ❌ 否决（地图树与地点树同构，D4） |
| **新表带 is_deleted（F10 同款软删）** | 与既有实体一致 | 用户拍板：普通实体删除=真删（D1=B）；归档仅会话保留 | ❌ 否决（新表无软删，真删语义） |

---

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/projects/{project_id}/maps` | 创建地图（**multipart/form-data**：file + name + description? + root_location_id? + parent_map_id?）→ 201（v1.3 #368：parent_map_id=父图 id，None=根图） |
| GET | `/api/v1/projects/{project_id}/maps` | 地图列表（`?root_location_id=<id>` 过滤，Q3=A；`?root_location_id=none` = 全局图） |
| GET | `/api/v1/maps/{map_id}` | 地图详情 |
| GET | `/api/v1/maps/{map_id}/image` | 图片文件（FileResponse，Content-Type 按扩展名；404 = 文件缺失） |
| GET | `/api/v1/maps/{map_id}/children` | 子地图列表（drill-down：本图 pins 关联地点下挂的地图，Q1=B；**过滤地点软删**——评审 F2） |
| PATCH | `/api/v1/maps/{map_id}` | 更新元数据（name/description/root_location_id） |
| PUT | `/api/v1/maps/{map_id}/image` | 换图（multipart file；新文件写入成功后才删旧文件） |
| DELETE | `/api/v1/maps/{map_id}` | **D6 参数**：`?cascade=true` = 真删 + 级联删全部子地图（递归）+ pins + 文件 \| `?reparent_to=<map_id>` = 真删自身 + 子地图改挂新父（目标父地图自动补 pin，D3）+ 文件删除；**有子地图且未指定 → 422** |
| POST | `/api/v1/maps/{map_id}/pins` | 创建 pin → 201 |
| GET | `/api/v1/maps/{map_id}/pins` | pin 列表（`?location_id=<id>` 过滤可选） |
| PATCH | `/api/v1/map-pins/{pin_id}` | 更新 pin |
| DELETE | `/api/v1/map-pins/{pin_id}` | 真删 pin（无归档） |

> **⚠️ 无 restore 端点（D7 拍板）**：地图/pin 真删不可恢复，无 restore/归档端点——与 F10 既有 restore 的差异与统一登记 #211（0.8.0）。

### 3.2 请求/响应示例

**创建地图（multipart）**：

```http
POST /api/v1/projects/1/maps
Content-Type: multipart/form-data

file: <binary image>
name: 清河县城图
root_location_id: 5
description: 县城坊市布局
```

```json
201
{"id": "9", "project_id": "1", "name": "清河县城图",
 "image_path": "maps/c0a8.../main.png", "description": "县城坊市布局",
 "root_location_id": "5", "created_at": "...", "updated_at": "..."}
```

**创建 pin**：

```json
POST /api/v1/maps/9/pins
{"location_id": "7", "x": 42.5, "y": 68.0, "label": "清河县城"}
→ 201 {"id": "11", "map_id": "9", "location_id": "7", "x": 42.5, "y": 68.0,
       "label": "清河县城", "created_at": "...", "updated_at": "..."}
```

**子地图（drill-down）**：

```http
GET /api/v1/maps/9/children
→ {"items": [{"id": "12", "name": "清河县城坊市图", ...}], "total": 1}
```

**级联真删**（有子地图必须显式选择）：

```http
DELETE /api/v1/maps/9?cascade=true
→ 204（子地图递归删 + pins + 图片文件删）

DELETE /api/v1/maps/9
→ 422 {"detail": "该地图存在子地图，必须指定 cascade=true（级联删除）或 reparent_to=<map_id>（子地图改挂新父）"}
```

### 3.3 异常映射表

| 异常 | 状态码 | detail |
|------|--------|--------|
| MapNameConflictError | 422 | 同名地图已存在（项目内） |
| MapRootLocationConflictError | 422 | 该地点已挂有一张地图（#368：detail 引导「如需层级请用创建子图」） |
| MapRootLocationNotFoundError | 422 | 父地点不存在或不在同一项目（#368：detail 引导「根地点应为世界观条目 id（而非地图 id）」） |
| MapParentMapNotFoundError | 422 | **v1.3 #368 新增**：父地图不存在或不在同一项目 |
| MapPinLocationNotFoundError | 422 | pin 关联地点不存在或不在同一项目 |
| MapChildrenActionRequiredError | 422 | 该地图存在子地图，必须指定 cascade 或 reparent_to |
| MapReparentTargetError | 422 | reparent 目标地图不存在/不在同一项目/是自身子孙地图 |
| MapNotFoundError | 404 | 地图不存在 |
| MapPinNotFoundError | 404 | pin 不存在 |
| ProjectNotFoundError（F10 world_errors 复用） | 404 | 项目不存在 |
| MapAssetError | 500 | 图片文件读写失败/类型不支持/超限 |

> **错误类归属**：`map_errors.py` 只定义模块专属错误；`ProjectNotFoundError` **复用 F10 world_errors 既有类**（F16 双入口教训：不重定义通用名错误类，避免遮蔽既有 router）；router 单入口（maps.py）`_run_service` catch 链照 F10 模式。

---

## 4. CLI 命令签名

`inkflow map` 组（镜像 F10 world 组薄层风格）：

```bash
inkflow map create <project_id> --name <name> --image <path>
                [--root-location <UUID>] [--description <text>]     # 上传本地图片创建地图
inkflow map list <project_id> [--root-location <UUID>|none]          # 地图列表（含 root_location_id）
inkflow map get <map_id> [--image-output <path>]                    # 详情；--image-output 下载图片
inkflow map update <map_id> [--name] [--description] [--root-location <UUID>|none]
inkflow map image <map_id> --image <path>                           # 换图
inkflow map delete <map_id> [--cascade] [--reparent-to <map_id>]    # 真删；有子地图必须显式选择
inkflow map children <map_id>                                       # 子地图（drill-down）
inkflow map pin add <map_id> --x <0-100> --y <0-100> --label <text> [--location <UUID>]
inkflow map pin list <map_id>
inkflow map pin update <pin_id> [--x] [--y] [--label] [--location <UUID>|none]
inkflow map pin delete <pin_id>                                     # 真删 pin
```

- F7 全局约定：`--json` 信封 / 退出码 0/1/2 / `VALIDATION_ERROR`/`NOT_FOUND`/`DB_ERROR` 映射
- 删除类命令二次确认 + 有子地图未指定参数 → `VALIDATION_ERROR`（与 API 422 一致）
- 图片上传失败（文件不存在/类型不支持）→ `VALIDATION_ERROR`

---

## 5. 关键差异：本地资产 + 地图树 drill-down + 真删语义

### 5.1 图片资产存储（`infrastructure/assets/map_asset_store.py`）

```text
存储根:  config.data_dir / "maps" / <map_uuid> / "main.<ext>"
         （%APPDATA%\InkFlow\maps\<uuid>\main.png；dev = 默认 data_dir）
DB 存:  相对路径 "maps/<uuid>/main.<ext>"（相对 config.data_dir）——备份/迁移只复制 data_dir
```

**MapAssetStoreProtocol**（纯基础设施端口，域层不感知文件系统）：

```python
class MapAssetStoreProtocol(Protocol):
    async def save(self, *, map_id: uuid.UUID, filename: str, content: bytes) -> str:
        """保存图片 → 返回相对路径（maps/<uuid>/main.<ext>）."""
    async def delete(self, relative_path: str) -> None:
        """删除图片文件（真删地图时调用；不存在静默）."""
    async def copy(self, relative_path: str, *, map_id: uuid.UUID) -> str:
        """复制图片到新地图目录 → 返回新相对路径（#175 复制用；源缺失抛 MapAssetError）."""
    def resolve(self, relative_path: str) -> Path:
        """相对路径 → 绝对路径（FileResponse 用）."""
```

**校验**（save 入口）：

| 项 | 规则 |
|----|------|
| 文件类型 | 白名单：png / jpg / jpeg / webp（魔数校验 + 扩展名一致） |
| 大小上限 | ≤ 10 MB（`content-length` 超限 → MapAssetError） |
| 路径安全 | `resolve` 拒绝 `..` 穿越（相对路径规范化后必须位于 data_dir 内）——本地威胁模型（同 ADR-021） |

**生命周期（D5 拍板：删除即删文件）**：

| 操作 | 文件处理 |
|------|----------|
| 创建/换图 | 写新文件；换图**先写新成功后删旧**（防换图失败丢旧图） |
| 真删地图（cascade / reparent_to / 无子直接删） | **物理删除文件**（与数据一致，无归档窗口——D5） |
| 项目硬删 | maps 真删级联 → 图片文件删除（service 遍历删，D10=b） |

### 5.2 地图树 drill-down（Q1=B 拍板）

**语义**：地图树与地点树**同构**（设计书 §5.1）——地图 M（root=A）的 pin 关联地点 B，若 B 下挂有子地图 M'（root=B），则点击 M 上 B 的 pin 进入 M'。这是**叙事层级缩放**（非像素缩放）：县城图 → 坊市图。

**查询实现**（`children` 端点，repo 单 SQL——**含地点软删过滤，评审 F2**）：

```sql
-- GET /maps/{id}/children：本图 pins 关联地点下挂的活动地图
-- （地点软删 → 该地点下地图不出现在 children——软删地点不可导航）
SELECT DISTINCT m2.* FROM maps m2
JOIN map_pins p ON p.map_id = :map_id AND p.location_id IS NOT NULL
JOIN world_settings w ON w.id = p.location_id AND w.is_deleted = 0   -- 地点软删过滤
WHERE m2.root_location_id = p.location_id
ORDER BY m2.created_at ASC;
```

**导航链路**（#174 交互，设计书 §5.2）：

```text
面包屑（顶）:  地点祖先链（F35 ancestors 复用）「清河县城 ← 青州 ← 大越国」
地图视图:      图片 + pins 悬浮（x/y 百分比定位）
点击 pin:      关联地点 → 跳转地点条目；该地点有子地图 → drill-down 进入
地点条目回跳:  「查看地图」→ 该地点 root 的地图（get by root_location_id）
```

**懒构建**：父地点无图 = children 空（合法）；地点无父节点 = 全局图（合法）——任何层可断。

> **⚠️ 归档地点与地图（评审 F2 补充声明）**：F10 软删地点（is_deleted=1）后，其下地图**仍存在**（地图是独立资产，不随地点软删）——但 children 导航**不显示**（JOIN 过滤），面包屑断链规避；用户需先将地点 restore 或改挂地图 root_location。

### 5.3 删除语义（D1-D7 拍板，load-bearing）

| 操作 | 无子地图 | 有子地图 |
|------|----------|----------|
| `DELETE`（无参数） | **真删**（地图 + pins + 图片文件） | **422 MapChildrenActionRequiredError**（强制显式选择） |
| `DELETE ?cascade=true` | 真删 | **递归真删全部子孙地图**（D4=A：整棵子树）+ pins + 图片文件 |
| `DELETE ?reparent_to=<map_id>` | 真删 | **真删自身 + 全部直接子地图改挂新父**（D2=A；**目标父地图自动补 pin** 指向子地图的 root_location，D3=A；目标非法 → 422） |

**reparent 实现（D3=A：目标父地图自动补 pin）**：

```text
reparent_to = M_N:
  ① 校验 M_N 存在/同项目/非自身子孙地图（MapReparentTargetError）
  ② 对每个直接子地图 M_child（root=B）:
     - 若 M_N 已有 pin 关联 B → 复用（不重复创建）
     - 否则自动创建 pin: {location_id: B, x: 50, y: 50, label: B.name}
       （默认居中 + 地点名——用户后续可微调；pin 使 M_child 出现在 M_N.children）
  ③ 单事务: DELETE 自身 maps 行 + 删自身 pins + 删图片文件
  ④ 子孙层级不变（孙地图继续挂 M_child——树整体平移）
```

> **⚠️ 无缺省置顶选项**：与 F35 一致——「子地图变孤儿」不隐式发生；显式选择 cascade 或 reparent_to（防误删/防静默断链）。

### 5.4 服务层编排（`domain/services/map_service.py`）——FK 显式级联（D10=b）

```text
create_map:  ① 项目存在（ProjectNotFoundError）
             ② root_location_id 若提供 → 同项目活动地点（F35 校验复用，MapRootLocationNotFoundError）
             ③ name 唯一（MapNameConflictError）+ root_location 唯一（MapRootLocationConflictError）
             ④ parent_map_id 若提供（v1.3 #368）→ 同项目存在的地图（repo.get 非 None + 同项目；
                不存在/跨项目 → MapParentMapNotFoundError）；层级深度不限
             ⑤ asset_store.save（写文件失败 → MapAssetError，不落库）
             ⑥ 落库（DB 失败 → 删已写文件，防孤儿）
create_pin:  ① map 存在（MapNotFoundError）② location_id 若提供 → 同项目活动地点
             ③ x/y 范围 Pydantic 校验 ④ 落库
update_map:  改名校验 + root_location 改挂校验（同 ②③）；换图走 PUT /image（save → 删旧）
delete_map:  D6 参数（cascade/reparent_to）；真删编排：
             - 无子: 单事务 DELETE map + DELETE pins + asset_store.delete(image_path)
             - cascade: 子树集合（递归 children）→ 单事务 DELETE 全部 + 删全部图片文件
             - reparent_to: 自动补 pin（§5.3）→ 单事务 DELETE 自身 + pins + 文件
delete_pin:  真删单行（无级联）
children:    repo.children(map_id)（单 SQL JOIN + 地点软删过滤，§5.2）
```

**⚠️ 项目硬删的显式级联（D10=b）**：生产连接 FK 不生效——项目硬删时 maps/pins 不会被 DB 级联删除。**f36 需在 service 或 repo 提供「项目删除钩子」**：删除项目时显式查该项目 maps → 删 pins → 删图片文件 → 删 maps（或依赖 #211 统一改造时开 FK；本模块先显式处理，防孤儿数据）。

### 5.5 排序与确定性

- maps 列表：`created_at DESC`（自有定义；区别于 F10 的 updated_at DESC——评审 🟡-7 修正表述）
- pins 列表：`created_at ASC`（创建顺序稳定，展示层级确定性）
- children：`created_at ASC`（drill-down 顺序稳定）

---

## 6. 组织规则

- **目录归属**：新模块 `domain/models/map.py` + `domain/ports/map_*` + `domain/services/map_service.py` + `infrastructure/database/models|repositories/map*` + `infrastructure/assets/map_asset_store.py` + `api/routers/maps.py` + `cli/commands/map.py`——镜像 F9/F10 骨架（实体 + 仓储 + service + router + CLI）
- **资产目录**：`infrastructure/assets/`（新目录，本地文件资产统一落点；F30 kernel 已有 `infrastructure/kernel/` 同层先例）
- **deps 装配**：`api/deps.py` 新增 `get_map_service(db)`——注入 SQLiteMapRepository + LocalMapAssetStore + WorldRepositoryProtocol（location 校验）+ ProjectRepositoryProtocol（项目硬删钩子）
- **日志**：loguru（创建/删除/换图/资产失败均记，F10 风格）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| 1 | root_location_id 指向不存在/软删/跨项目地点 | 422 MapRootLocationNotFoundError |
| 2 | 同一地点挂第二张图 | 422 MapRootLocationConflictError（unique 兜底） |
| 3 | pin location_id 指向不存在/软删/跨项目地点 | 422 MapPinLocationNotFoundError |
| 4 | 图片类型不在白名单（.exe/.svg…） | MapAssetError（魔数校验拒绝） |
| 5 | 图片 > 10 MB | MapAssetError |
| 6 | 图片文件缺失（data_dir 被手动删） | GET /image → 404「图片文件缺失」（DB 行仍在，可换图恢复） |
| 7 | DELETE 无参数 + 无子地图 | 真删（地图 + pins + 文件） |
| 8 | DELETE 无参数 + 有子地图 | 422 MapChildrenActionRequiredError（强制选择） |
| 9 | DELETE ?cascade=true | 递归真删子孙地图 + pins + 文件（单事务原子） |
| 10 | DELETE ?reparent_to 目标非法 | 422 MapReparentTargetError（不存在/跨项目/自身子孙地图） |
| 11 | reparent 自动补 pin | 目标已有同地点 pin → 复用；否则创建默认 pin（居中 + 地点名） |
| 12 | 换图失败（新文件写失败） | 旧文件保留，DB 不变，抛 MapAssetError（不丢旧图） |
| 13 | 真删地图文件删除失败（占用/只读） | 记录 warning，DB 行删除成功（孤儿文件后续手动清理——不阻断删除） |
| 14 | 软删地点 → 其下地图 | 地图保留（独立资产）；children 不显示（地点软删过滤）；breadcrumb 断链规避 |
| 15 | 硬删地点（F35 cascade）→ pin | **service 显式 SET NULL**（D10=b：UPDATE pins SET location_id=NULL WHERE location_id=该地点）——pin 保留为纯注释（label 不变） |
| 16 | 项目硬删 → maps/pins | **service 显式级联**（D10=b：查 maps → 删 pins → 删文件 → 删 maps） |
| 17 | children 查询无子地图 | 200 空列表（懒构建合法态） |
| 18 | 全局图（root NULL） | 允许多张；children 不可达（无父地点链路）——全局图是起点不是层级节点 |
| 19 | 归档地图的 GET /image（边界 X 兼容） | **不存在归档态**（无 is_deleted）——真删即 404（若 F10 软删地点下地图仍存在，其 /image 正常 200） |
| 20 | **parent_map_id 指向不存在/跨项目地图（v1.3 #368）** | 422 MapParentMapNotFoundError（detail「父地图不存在或不在同一项目」） |
| 21 | **root_location_id 误传地图 id（v1.3 #368 引导）** | 422 MapRootLocationNotFoundError（detail 引导「根地点应为世界观条目 id（而非地图 id）」） |

---

## 8. 文件结构（对照真实源码树）

| 文件 | 变更 | 内容 |
|------|------|------|
| `backend/src/inkflow/domain/models/map.py` | **CREATE** | WorldMap/WorldMapCreate/WorldMapUpdate/MapPin/MapPinCreate/MapPinUpdate（**无 is_deleted**） |
| `backend/src/inkflow/domain/ports/map_repository.py` | **CREATE** | MapRepositoryProtocol（add/get/get_by_name/list/update/delete + list_pins/add_pin/update_pin/delete_pin + children + list_by_root_locations——#175 复制共用，评审 S10） |
| `backend/src/inkflow/domain/ports/map_errors.py` | **CREATE** | MapServiceError/MapNameConflictError/MapRootLocationConflictError/MapRootLocationNotFoundError/MapPinLocationNotFoundError/MapChildrenActionRequiredError/MapReparentTargetError/MapNotFoundError/MapPinNotFoundError/MapAssetError |
| `backend/src/inkflow/domain/services/map_service.py` | **CREATE** | 编排（§5.4）；依赖注入：MapRepositoryProtocol + MapAssetStoreProtocol + WorldRepositoryProtocol + ProjectRepositoryProtocol |
| `backend/src/inkflow/infrastructure/assets/__init__.py` | **CREATE** | 导出 MapAssetStoreProtocol/LocalMapAssetStore |
| `backend/src/inkflow/infrastructure/assets/map_asset_store.py` | **CREATE** | LocalMapAssetStore（save/delete/copy/resolve + 魔数/大小校验 + 路径安全） |
| `backend/src/inkflow/infrastructure/database/models/map.py` | **CREATE** | MapORM/MapPinORM（§2.4，无 is_deleted） |
| `backend/src/inkflow/infrastructure/database/repositories/map_repo.py` | **CREATE** | SQLiteMapRepository（含 children JOIN + 地点软删过滤、list_by_root_locations、真删语句） |
| `backend/src/inkflow/api/routers/maps.py` | **CREATE** | 13 端点（§3.1）；multipart 用 UploadFile |
| `backend/src/inkflow/api/app.py` | **MODIFY** | 注册 maps router（`include_router(maps.router)`） |
| `backend/src/inkflow/api/deps.py` | **MODIFY** | 新增 `get_map_service` 装配 |
| `backend/src/inkflow/cli/commands/map.py` | **CREATE** | `inkflow map` 组（§4） |
| `backend/src/inkflow/cli/app.py` | **MODIFY** | 注册 map 命令组 |
| `backend/tests/unit/test_map_repo.py` | **CREATE** | 仓储层（CRUD/children JOIN/唯一约束/真删） |
| `backend/tests/unit/test_map_service.py` | **CREATE** | 服务层（校验链/真删级联/reparent/文件生命周期编排/项目硬删钩子） |
| `backend/tests/unit/test_map_asset_store.py` | **CREATE** | 资产层（save/delete/copy/魔数/大小/路径穿越） |
| `backend/tests/unit/test_map_api.py` | **CREATE** | API 契约（multipart 上传/下载/删除参数/错误映射） |
| `tests/cli/test_cli_map.py` | **CREATE** | CLI 命令（信封/退出码/图片上传/删除参数） |

| `backend/src/inkflow/domain/services/world_service.py` | **MODIFY** | delete_setting 加 location_cleanup 可选回调（cascade/force 硬删分支调用，D10=b 接线；v1.2 补） |
| `backend/src/inkflow/domain/services/project_service.py` | **MODIFY** | hard_delete 加 map_cleanup 可选回调（成功后调用，D10=b 接线；v1.2 补） |
| `backend/src/inkflow/infrastructure/http/client.py` | **MODIFY** | 新增 post_file/put_file/get_bytes（multipart 上传 + 原始字节下载，CLI map create/image/get 用；v1.2 补） |
| `backend/pyproject.toml` | **MODIFY** | HTTP 组加 python-multipart>=0.0.9（multipart 端点必需；v1.2 补） |
| `.github/workflows/ci.yml` | **MODIFY** | integration-cli-backend job 追加 test_cli_map.py（v1.2 补） |

> **⚠️ CI 盲区防范（Issue #59/#61 教训）**：`tests/cli/test_cli_map.py` 是**新文件**，已显式加入 ci.yml `integration-cli-backend` job 文件列表（Windows pytest 不展开 glob）。

---

## 9. 测试策略

### 层次

```text
单元（repo）:    maps/pins CRUD 往返 + children JOIN（含地点软删过滤）+ 双唯一约束   ~14 cases
单元（service）: 校验链（地点不存在/跨项目/同名/重复 root）+ 真删矩阵 + reparent     ~18 cases
单元（asset）:   save 魔数白名单/大小上限/路径穿越拒绝/delete 幂等/copy              ~9 cases
API（集成）:     multipart 上传 201 → image 下载 → PATCH 元数据 → PUT 换图 → 删除参数 ~14 cases
CLI:             map 组命令 + pin 子组 + 图片上传/下载                                 ~10 cases
```

### 关键测试场景

1. **multipart 上传闭环**：TestClient `files={"file": (name, content, "image/png")}` → 201 → `GET /image` 返回同字节 → 相对路径存 DB
2. **children JOIN + 地点软删过滤**：图 A pin→地点 B，地点 B 挂图 C → `children(A)` 含 C；**B 软删后 children(A) 不含 C**（评审 F2）；无 pin 关联 = 空列表
3. **双唯一约束**：同名地图 422；同地点第二张图 422；全局图多张 200
4. **删除矩阵**：无子 DELETE → 真删（断言行消失 + 文件删除）；有子 DELETE 无参 → 422；`?cascade=true` → 子孙地图递归删 + pins + 文件全删；`?reparent_to` → 自身删 + 子地图改挂 + **目标自动补 pin（复用/新建两分支）** + 文件删
5. **reparent 目标校验**：目标不存在/跨项目/是自身子孙地图 → 422
6. **换图原子性**：新文件写失败（mock save 抛错）→ 旧文件与 DB 不变
7. **文件缺失**：删 data_dir 图片 → GET /image 404（DB 行在）
8. **硬删地点 → pin SET NULL（D10=b 显式）**：mock WorldRepositoryProtocol 硬删场景 → service 显式 UPDATE pins SET location_id=NULL → pin 保留纯注释（label 不变）
9. **项目硬删钩子（D10=b）**：service 显式删该项目 maps → pins → 文件（临时目录断言文件不存在）
10. **路径穿越**：`resolve("../../etc/passwd")` → 拒绝（ValueError/MapAssetError）
11. **Pydantic 坐标**：x=101/y=-1 → 422（字段校验）
12. **错误类复用**：ProjectNotFoundError 来自 world_errors（import 断言，防 F16 遮蔽回归）

### 覆盖率

模块行覆盖 ≥ 80%；全仓门禁 ADR-027：98.5/95.0（新表/新服务需足量测试维持——设计书 §8 风险表；M8 验收前先跑 coverage-backend 等价命令实测，留补测 buffer——QA 评审 🟡-7）。

---

## 10. 不在范围内

| 项 | 原因 | 归属 |
|----|------|------|
| 内置绘图引擎（画布/笔刷/图层） | 金锤子（设计书 §5.3） | Phase 3+ |
| LLM 自动生成地图 | 质量不可控；底图素材 AI 辅助独立立项 | 未来独立立项 |
| 相邻关系（neighbors） | 图（相邻）是低频补充，extra 预留 | Phase 3+ |
| 图片云上传/服务 | 本地单机架构（ADR-030） | 永不 |
| 像素缩放/多分辨率图 | 叙事层级缩放（drill-down）是核心，非像素级 | 未来 |
| 地图导出为图片（合成 pin 到图） | 无场景（本地查看）；#175 复制是数据复制非渲染 | 未来 |
| 地图 restore/归档（is_deleted） | D7 拍板：真删不可恢复；归档仅会话保留（#211 关联） | 永不 |
| 全局开 PRAGMA foreign_keys=ON | D10=b：本模块 service 显式级联；全局 FK 开启是独立后续优化 | #211 或独立（0.8.0） |
| F6 上下文注入地点位置 | 数据地基先行（F35 §10 同） | 后续 |
| GUI 前端地图页 | 本 spec 只交付后端 API/CLI；前端随 GUI 迭代 | 后续 GUI 任务 |

---

## 11. 依赖关系

```text
F36 依赖:
  F10（world_settings + WorldRepositoryProtocol）— pin/root 地点校验（只读复用，零改动）
  F35（#173 地点树）— root_location_id 挂地点树；面包屑用 ancestors；drill-down 依赖地点关联
  F1（projects 表 + ProjectRepositoryProtocol）— 项目存在性校验 + 项目硬删钩子
  F7（CLI 全局约定）— map 组信封/退出码

F36 被依赖:
  #175（跨书复制）— 地图资产复制 + pin 重挂（依赖 maps/map_pins 表结构 + list_by_root_locations + asset_store.copy）
```

**编号口径声明**：本模块为 0.6.0 世界观三连 Step 2（#174），非 PRD F 系列新业务模块——「F36」编号承接（F35=#173 地点树，F38=#169 CLI 恒 HTTP）。模块类型谱系 **第 15 变体**（f38 为第 18 变体，编号不冲突——评审 S4 修正 + 谱系复核）。若与未来编号冲突以 ADR-019 v5+ 为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|-------------|
| 1 | 图片本地文件 + DB 相对路径 | data_dir/maps/<uuid>/main.<ext> | 本地单机架构、DB 不膨胀、FileResponse 直出（D3/D4） | BLOB（SQLite 膨胀）；云（架构冲突） |
| 2 | 坐标相对百分比 0-100 | Pydantic ge/le 校验 | 与分辨率解耦，换图不失效（设计书 §5.1） | 像素绝对坐标（换图失效） |
| 3 | 地图树与地点树同构 | root_location_id + children JOIN | drill-down 是叙事层级缩放；懒构建任何层可断 | 独立层级字段（与地点树脱钩） |
| 4 | 一个地点最多一张图 | unique (project, root_location) WHERE root_location IS NOT NULL | 设计书「每个父地点可挂一张图」；全局图多张 | 多图/地点（导航歧义） |
| 5 | **新表无 is_deleted（D1=B/D7 拍板）** | maps/map_pins 无软删列，真删 | 删除=删除（用户拍板，归档仅会话保留）；新表零历史包袱 | 带 is_deleted（F10 同款——被否决） |
| 6 | **删除 = 真删 + 级联/reparent（D1-D6）** | DELETE 无参真删 / cascade 递归 / reparent_to 补 pin；有子 422 | 防误删整棵子树；子地图处理显式选择（用户方案） | 归档两级（否决）；静默默认级联（误删风险） |
| 7 | **换图先写新后删旧** | save 成功才删旧文件 | 换图失败不丢旧图（原子性） | 先删旧（失败丢图） |
| 8 | **FK 运行时由 service 显式维护（D10=b）** | 级联/SET NULL 全 service 单事务；ORM FK 仅建表声明 | 生产连接未开 foreign_keys=ON，测试开——依赖 DB FK = 测试绿生产挂 | 全局开 FK pragma（回归 F1-F16，独立后续项 #211） |
| 9 | **children 过滤地点软删（评审 F2）** | JOIN world_settings 过滤 is_deleted=0 | 软删地点不可导航（面包屑断链规避）；地图保留为独立资产 | 不过滤（导航断链） |
| 10 | **children 与 #175 共用地点→地图查询（评审 S10）** | repo 提供 `list_by_root_locations(project_id, location_ids)` | 单一来源（children 服务层 = list_pins 提取 locations → 调共用查询）；#175 复制直接复用 | 两套查询（实现重复） |
| 11 | 项目硬删显式级联 | service 查 maps → 删 pins → 删文件 → 删 maps | D10=b 推论：FK 不生效时防孤儿数据 | 依赖 DB CASCADE（不生效） |
| 12 | 无缺省置顶选项 | reparent_to 必填（显式目标） | 「变孤儿」不隐式发生（与 F35 一致） | 缺省置顶（隐式断链） |
| 13 | **repo 补 get_pin（实现期裁定 2026-08-09）** | update_pin 保持单参全对象 + 新增 get_pin(pin_id)（Protocol 16→17 方法） | service 需现有 pin 合并部分更新（update_map 同款 get→model_copy 模式）；并行 RED 批契约分歧以源头 repo 契约为准（F30 先例） | 两参 (pin_id, update) 透传（无法表达部分更新） |
| 14 | **python-multipart 依赖（实现期发现）** | pyproject HTTP 组加 python-multipart>=0.0.9 | FastAPI multipart/form-data 端点必需（实测缺失 ImportError） | 手写 multipart 解析（复杂度高） |
| 15 | **钩子接线形态（实现期裁定）** | WorldService/ProjectService 加可选回调（location_cleanup/map_cleanup）+ deps 装配 MapService 方法 | 不碰 F1/F35 service 公共契约（默认 None 向后兼容）；CLI/API 全路径经 deps 覆盖 | router 层双 service 编排（脏） |
| 16 | **图挂图层级（v1.3 #368 拍板）** | maps 表加 `parent_map_id`（自引用 FK，可空，索引）；一父多子 + 子单父 + 层级深度不限；root_location_id（图↔条目）保留 | GUI「创建子图」心智 = 图挂图（根图→子图→孙图）；与 F35 地点树脱钩不冲突（两套层级并存）；无最大深度校验（本地量级递归安全） | 选项 A：允许一地点挂多图（去唯一约束——破坏 F36 既有「一个地点最多一张图」语义，导航歧义）；root_location_id 传父图挂载条目 id（语义错位：子图本应挂图） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 数据模型 + 建表（create_all 自动，无 is_deleted） | `pytest backend/tests/unit/test_map_repo.py -v` 全绿；新库表存在（PRAGMA table_list）；maps 无 is_deleted 列 |
| M2 | 资产存储（save/delete/copy/resolve/校验） | `pytest backend/tests/unit/test_map_asset_store.py -v` 全绿（魔数/大小/路径穿越/copy） |
| M3 | 服务编排（校验链/真删矩阵/reparent/文件生命周期/项目硬删钩子） | `pytest backend/tests/unit/test_map_service.py -v` 全绿（v1.3 #368：create_map parent_map_id 校验链——父图不存在/跨项目 422 MapParentMapNotFoundError；层级深度不限） |
| M4 | API 契约（multipart 上传/下载/换图/删除参数/错误映射） | `pytest backend/tests/unit/test_map_api.py -v` 全绿（v1.3 #368：POST parent_map_id Form 透传 + 422 映射） |
| M5 | children drill-down + 面包屑导航链路（含地点软删过滤） | children JOIN 测试全绿（含 B 软删后 C 消失用例）；手工验证：图 A pin→B，B 挂图 C → children(A)=[C]；B 归档 → children(A)=[] |
| M6 | CLI map 组 | `pytest ../tests/cli/test_cli_map.py -v` 全绿（**且已追加 ci.yml integration-cli-backend job**） |
| M7 | 手工验证 | 上传图片建图 → pin 关联地点 → 换图 → 有子图删除（422）→ cascade 真删（文件消失）→ 重建后 reparent（子图改挂 + 目标补 pin）→ 硬删地点 pin 转纯注释 |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；ADR-027 门槛（98.5/95.0，先跑 coverage-backend 等价命令实测留 buffer）；`uv run ruff check src/ tests/unit/ ../tests/` + mypy 通过 |

> Issue #174 验收标准映射：上传图片+pin+关联地点 = M1-M4；地图树 drill-down = M5；懒构建 = M5/M7；面包屑 = M5（F35 ancestors 复用）；本地图片资产 = M2/M7；真删语义 = M3/M7。

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 结论 |
|---|------|------|------|
| Q1 | 地图 MVP 范围：单图+pin vs 含地图树 drill-down + 面包屑？ | API 面（children 端点）与估算 | ✅ 已确认（2026-08-09 拍板：**选项 B**）——**drill-down + 面包屑一起做**（§5.2/§13 M5） |
| Q2 | 图片文件生命周期：真删删文件 vs 保留？ | 磁盘占用与恢复语义 | ✅ 已确认（2026-08-09 拍板：**A**，且删除语义收敛为真删 D5）——**删除即删文件，无归档窗口**（§5.1/§7 场景 13） |
| Q3 | 地图列表的 root_location 过滤是否本轮提供？ | API 面 | ✅ 已确认（2026-08-09 拍板：**选项 A**）——**提供 `?root_location_id=<id>\|none`**（§3.1/§5.5） |

---

*本文档为 F36 功能规格（What），实施步骤（How）见后续 `specs/f36-world-map/plan.md`。所有里程碑验收以本节 M1-M8 为准。*
