# F36: 世界观地图视图（world-map）— 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-09 | **依据**: 设计书 `design/world-geo-hierarchy-2026-08-08.md` §5（workspace）、PRD v2.1 §6.2 P1-02、F10 spec + F35 spec（地点树，本模块数据基础）、Constitution P1-P6
>
> **所属阶段**: 0.6.0 世界观三连 Step 2（呈现层，估算 5-8 人天）
>
> **关联 Issues**: [#174](https://github.com/zhx-xi/InkFlow/issues/174)（本模块）· #173（地点树，**前置依赖**）· #175（跨书复制，**依赖本模块**的地图资产复制）
>
> **依赖**: ✅ F10（world_settings + WorldRepositoryProtocol——pin 关联地点校验）· ✅ F35（#173 地点树：root_location_id 挂地点树 + ancestors/descendants 导航）· ✅ F1（项目 FK）
>
> **参考 ADR**: [ADR-019](../../adr/ADR-019.md)（版本里程碑）· [ADR-002](../../adr/ADR-002.md)（六边形分层）· [ADR-003](../../adr/ADR-003.md)（Repository）· [ADR-004](../../adr/ADR-004.md)（Pydantic v2）· [ADR-012](../../adr/ADR-012.md)（错误处理）
>
> **状态**: 待实现 🔲（0.6.0）

---

## 1. 概述

为世界观地点提供**地图视图**：上传本地图片 + pin 标记 + 关联地点条目。行业成熟形态（WorldAnvil 验证，设计书 §2.2 认知纠偏）：**地图 = 图片 + pin + 关联条目**，**不做内置绘图引擎**（与 Procreate/Inkarnate 竞争是金锤子）。

**核心交付**：

```text
F35 现状:  地点树（parent_id + ancestors/descendants 导航能力）
F36 增量:  新表 maps（图片地图）+ map_pins（标记）
           + 本地图片资产存储（内核数据目录，DB 存相对路径）
           + 地图树 drill-down（点 pin 进入子地图，叙事层级缩放，Q1 拍板）
           + 面包屑导航（复用 F35 ancestors）
```

### 1.1 模块类型定位（第 15 变体「地图实体 + 本地资产型」）

按 AGENTS.md 模块类型谱系计数（f15=6 / f16=7 / f23=8 / f19=9 / f26=10 / f24=11 / f25=12(移除) / f30=13 / f32=14），本模块为 **第 15 变体「地图实体 + 本地资产型」**：F9/F10 实体 CRUD 骨架 × F19 本地内核资产（数据目录文件系统）——新实体表 + 本地文件资产存储 + pin 关联既有实体。

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ✅ 2 个：`maps` + `map_pins` |
| 新 API 端点 | ✅ ~12 个（地图 CRUD + pin CRUD + 图片上传/下载 + children） |
| 新 CLI 命令 | ✅ `inkflow map` 组（create/list/get/update/delete/pin 子组/children） |
| 核心机制 | ✅ 本地图片资产（相对路径 + FileResponse）+ 相对百分比坐标 + 两级删除（F24 语义） |
| 跨模块 MODIFY | ✅ F10 world_repo 只读复用（location 校验，零改动）；F35 树查询复用 |
| 错误面 | MapServiceError 子类 422 / MapNotFoundError 404 / 文件层错误 500 |

### 1.2 边界声明

- **不做绘图引擎**（设计书 §5.3：金锤子规避，Phase 3+）
- **不做 LLM 自动生成地图**（质量不可控；底图素材 AI 辅助独立立项，§10）
- **不做相邻关系**（neighbors：树是叙事高频，图是低频补充，extra 预留，Phase 3+）
- **不做图片云上传/服务**（本地单机架构既定，ADR-030；文件存内核数据目录）
- **依赖 #173 地点树先合入**：pin 关联地点需要地点树存在（issue body 显式依赖声明）

---

## 2. 数据模型

### 2.1 maps 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK 自增 | 领域层 UUID 映射（F1 惯例） |
| project_id | int | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目（D4：地图归属世界观，复用随世界观走） |
| name | str | NOT NULL, 1-50 字符, 去空白 | 地图名（如「东大陆全图」「清河县城图」）；项目内活动地图名唯一 |
| image_path | str | NOT NULL | 本地图片相对路径（相对 config.data_dir，如 `maps/1f2a.../main.png`） |
| description | str | NOT NULL, DEFAULT "", ≤ 500 字符 | 地图描述/备注 |
| root_location_id | int \| NULL | FK→world_settings.id (SET NULL), 可空, 已索引 | 本图对应的父地点；NULL = 全局图 |
| is_deleted | bool | NOT NULL, DEFAULT False, 已索引 | 软删除标记 |
| created_at | datetime | NOT NULL | UTC |
| updated_at | datetime | NOT NULL | UTC，自动更新 |

**业务规则**：

1. **一个地点最多一张图**：partial unique `(project_id, root_location_id) WHERE is_deleted = 0 AND root_location_id IS NOT NULL`（设计书 §5.1「每个父地点可挂一张图」）；全局图（NULL）允许多张（不同主题/用途）
2. **name 项目内活动唯一**：partial unique `(project_id, name) WHERE is_deleted = 0`（F10 同款惯例）
3. **root_location_id 校验**：必须指向**同项目活动地点**（F35 校验链复用）——跨项目/软删地点 422
4. **root_location_id 变更**（PATCH）：允许改挂（换父地点/改全局）；改挂后地图树导航自动跟随（导航是查询不是快照）
5. **懒构建**：任何层可断——父地点无图/地点无父节点均合法（设计书 §5.2）；`children` 查询空列表不是错误

### 2.2 map_pins 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK 自增 | 领域层 UUID 映射 |
| map_id | int | NOT NULL, FK→maps.id (CASCADE), 已索引 | 所属地图 |
| location_id | int \| NULL | FK→world_settings.id (SET NULL), 可空, 已索引 | 关联地点条目；NULL = 纯注释 pin |
| x | float | NOT NULL, 0-100 | 相对图片宽度百分比坐标 |
| y | float | NOT NULL, 0-100 | 相对图片高度百分比坐标 |
| label | str | NOT NULL, 1-50 字符, 去空白 | pin 显示文本（关联地点 pin 也显式提供——前端默认填地点名，后端不自动取） |
| is_deleted | bool | NOT NULL, DEFAULT False, 已索引 | 软删除标记 |
| created_at | datetime | NOT NULL | UTC |
| updated_at | datetime | NOT NULL | UTC，自动更新 |

**业务规则**：

1. **坐标相对百分比**：0-100 浮点（Pydantic `ge=0, le=100`）——与图片分辨率解耦（设计书 §5.1），图片换图不失效
2. **location_id 校验**：指向**同项目活动地点**；NULL = 纯注释 pin（设计书 §5.1）
3. **label 必填**（纯注释 pin 与关联 pin 均有）；换图后 pin 保留（坐标百分比语义）
4. **无 pin 数量上限**（本地量级，列表查询即可）

### 2.3 领域模型（`domain/models/map.py`，镜像 F10 风格）

```python
class WorldMap(BaseModel):
    """地图领域实体 — 对应 maps 表."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    image_path: str                # 相对 config.data_dir 的路径（如 maps/<uuid>/main.png）
    description: str = ""
    root_location_id: uuid.UUID | None = None
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class WorldMapCreate(BaseModel):
    """创建地图请求 DTO — 图片文件走 multipart，不在 body."""
    project_id: uuid.UUID
    name: str
    description: str = ""
    root_location_id: uuid.UUID | None = None


class WorldMapUpdate(BaseModel):
    """更新地图元数据请求 DTO（不换图；换图走 PUT /maps/{id}/image）.

    root_location_id: None 表示不修改；出现且为 null = 改为全局图（与 F35 parent_id 同款
    exclude_unset 语义）.
    """
    name: str | None = None
    description: str | None = None
    root_location_id: uuid.UUID | None = None


class MapPin(BaseModel):
    """地图 pin 领域实体 — 对应 map_pins 表."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    map_id: uuid.UUID
    location_id: uuid.UUID | None = None
    x: float
    y: float
    label: str
    is_deleted: bool = False
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
    """地图 ORM — 映射到 maps 表."""

    __tablename__ = "maps"

    __table_args__ = (
        Index("uq_maps_active_name", "project_id", "name",
              unique=True, sqlite_where=text("is_deleted = 0")),
        Index("uq_maps_active_root_location", "project_id", "root_location_id",
              unique=True,
              sqlite_where=text("is_deleted = 0 AND root_location_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    image_path: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    root_location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_settings.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )


class MapPinORM(Base):
    """地图 pin ORM — 映射到 map_pins 表."""

    __tablename__ = "map_pins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    map_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("maps.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_settings.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )
```

> **迁移（零迁移声明）**：`maps`/`map_pins` 是**新表**——由 `Base.metadata.create_all` 自动创建（无 alembic 基建，F1 惯例），**无需幂等迁移**（区别于 F35 的加列迁移）。既有库升级：lifespan `create_tables()` 自动建新表。

### 2.5 决策论证表

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **图片存本地文件系统 + DB 相对路径（选定）** | 与本地单机架构一致；DB 不膨胀；FileResponse 直出 | 跨设备/备份需复制数据目录（既定成本） | ✅ 设计书 D3/D4 |
| 图片存 DB BLOB | 单文件备份 | SQLite 膨胀、读写大文件低效、无直接文件路径 | ❌ 否决 |
| 坐标存像素绝对值 | 简单 | 换图失效；分辨率耦合 | ❌ 否决（相对百分比 0-100，设计书 §5.1） |
| root_location_id 硬编码层级跳转 | 实现简单 | 地图树与地点树脱钩，drill-down 断链 | ❌ 否决（地图树与地点树同构，D4） |

---

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/projects/{project_id}/maps` | 创建地图（**multipart/form-data**：file + name + description? + root_location_id?）→ 201 |
| GET | `/api/v1/projects/{project_id}/maps` | 地图列表（`?root_location_id=<id>` 过滤；缺省全量） |
| GET | `/api/v1/maps/{map_id}` | 地图详情 |
| GET | `/api/v1/maps/{map_id}/image` | 图片文件（FileResponse，Content-Type 按扩展名；404 = 文件缺失） |
| GET | `/api/v1/maps/{map_id}/children` | 子地图列表（drill-down：本图 pins 关联地点下挂的地图，Q1） |
| PATCH | `/api/v1/maps/{map_id}` | 更新元数据（name/description/root_location_id） |
| PUT | `/api/v1/maps/{map_id}/image` | 换图（multipart file；旧文件删除，新文件写入） |
| DELETE | `/api/v1/maps/{map_id}` | 两级删除：首次 = 归档（pins 级联归档）；已归档再删/`?force=true` = 真删（pins 级联真删 + 图片文件删除） |
| POST | `/api/v1/maps/{map_id}/restore` | 恢复归档地图（pins 级联恢复） |
| POST | `/api/v1/maps/{map_id}/pins` | 创建 pin → 201 |
| GET | `/api/v1/maps/{map_id}/pins` | pin 列表（活动 pin；`?location_id=<id>` 过滤可选） |
| PATCH | `/api/v1/map-pins/{pin_id}` | 更新 pin |
| DELETE | `/api/v1/map-pins/{pin_id}` | 两级删除：首次归档；再删/force 真删 |
| POST | `/api/v1/map-pins/{pin_id}/restore` | 恢复 pin |

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
 "root_location_id": "5", "is_deleted": false, "created_at": "...", "updated_at": "..."}
```

**创建 pin**：

```json
POST /api/v1/maps/9/pins
{"location_id": "7", "x": 42.5, "y": 68.0, "label": "清河县城"}
→ 201 {"id": "11", "map_id": "9", "location_id": "7", "x": 42.5, "y": 68.0,
       "label": "清河县城", "is_deleted": false, "created_at": "...", "updated_at": "..."}
```

**子地图（drill-down）**：

```http
GET /api/v1/maps/9/children
→ {"items": [{"id": "12", "name": "清河县城坊市图", ...}], "total": 1}
```

### 3.3 异常映射表

| 异常 | 状态码 | detail |
|------|--------|--------|
| MapNameConflictError | 422 | 同名地图已存在（项目内） |
| MapRootLocationConflictError | 422 | 该地点已挂有一张地图 |
| MapRootLocationNotFoundError | 422 | 父地点不存在或不在同一项目 |
| MapPinLocationNotFoundError | 422 | pin 关联地点不存在或不在同一项目 |
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
inkflow map list <project_id> [--root-location <UUID>]              # 地图列表（含 root_location_id）
inkflow map get <map_id> [--image-output <path>]                    # 详情；--image-output 下载图片
inkflow map update <map_id> [--name] [--description] [--root-location <UUID>|none]
inkflow map image <map_id> --image <path>                           # 换图
inkflow map delete <map_id> [--force]                               # 两级删除（归档→真删）
inkflow map restore <map_id>                                        # 恢复
inkflow map children <map_id>                                       # 子地图（drill-down）
inkflow map pin add <map_id> --x <0-100> --y <0-100> --label <text> [--location <UUID>]
inkflow map pin list <map_id>
inkflow map pin update <pin_id> [--x] [--y] [--label] [--location <UUID>|none]
inkflow map pin delete <pin_id> [--force]
inkflow map pin restore <pin_id>
```

- F7 全局约定：`--json` 信封 / 退出码 0/1/2 / `VALIDATION_ERROR`/`NOT_FOUND`/`DB_ERROR` 映射
- 删除类命令二次确认 + `--force`（F7 既有约定）；`--json` + 无 force 的删除 → `VALIDATION_ERROR`
- 图片上传失败（文件不存在/类型不支持）→ `VALIDATION_ERROR`

---

## 5. 关键差异：本地资产 + 地图树 drill-down

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
    def resolve(self, relative_path: str) -> Path:
        """相对路径 → 绝对路径（FileResponse 用）."""
```

**校验**（save 入口）：

| 项 | 规则 |
|----|------|
| 文件类型 | 白名单：png / jpg / jpeg / webp（魔数校验 + 扩展名） |
| 大小上限 | ≤ 10 MB（`content-length` 超限 → MapAssetError） |
| 路径安全 | `resolve` 拒绝 `..` 穿越（相对路径规范化后必须位于 data_dir 内）——本地威胁模型（同 ADR-021） |

**生命周期**（Q2 拍板，建议 A）：

| 操作 | 文件处理 |
|------|----------|
| 创建/换图 | 写新文件；换图删旧文件（成功写入后再删——防换图失败丢旧图） |
| 归档地图 | **保留文件**（可恢复；恢复后图片直接可用） |
| 真删地图（级联/force） | **物理删除文件**（与数据一致，防孤儿文件堆积） |
| 项目硬删 | maps 级联真删 → 图片文件删除（repository 级联后 service 遍历删文件） |

### 5.2 地图树 drill-down（Q1 拍板，建议 B）

**语义**：地图树与地点树**同构**（设计书 §5.1）——地图 M（root=A）的 pin 关联地点 B，若 B 下挂有子地图 M'（root=B），则点击 M 上 B 的 pin 进入 M'。这是**叙事层级缩放**（非像素缩放）：县城图 → 坊市图。

**查询实现**（`children` 端点，repo 单 SQL）：

```sql
-- GET /maps/{id}/children：本图 pins 关联地点下挂的活动地图
SELECT DISTINCT m2.* FROM maps m2
JOIN map_pins p ON p.map_id = :map_id AND p.is_deleted = 0 AND p.location_id IS NOT NULL
WHERE m2.root_location_id = p.location_id
  AND m2.is_deleted = 0
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

### 5.3 两级删除语义（F24 语义在 map/pin 上的落地）

| 操作 | maps | map_pins |
|------|------|----------|
| 首次 DELETE | 归档（is_deleted=1）+ **pins 级联归档** | 归档自身 |
| 已归档再 DELETE | 真删 + pins 级联真删 + **图片文件删除** | 真删自身 |
| `?force=true` | 同真删 | 同真删 |
| restore | 恢复 + **pins 级联恢复** | 恢复自身 |

> 级联用单语句（`UPDATE ... WHERE map_id IN (...)` / `DELETE ...`）——原子性由 SQLite 事务保证（F35 §5.5 同款）。
> 注意：map_pins 的 `location_id` FK 是 `ON DELETE SET NULL`（F2 章节硬删 → pin 保留为纯注释）——**硬删地点不级联删 pin**（F15 跨模块语义核对先例：以真实 FK 语义为准）。

### 5.4 服务层编排（`domain/services/map_service.py`）

```text
create_map:  ① 项目存在（ProjectNotFoundError）
             ② root_location_id 若提供 → 同项目活动地点（F35 校验复用，MapRootLocationNotFoundError）
             ③ name 同级唯一（MapNameConflictError）+ root_location 唯一（MapRootLocationConflictError）
             ④ asset_store.save（写文件失败 → MapAssetError，不落库）
             ⑤ 落库（DB 失败 → 删已写文件，防孤儿）
create_pin:  ① map 存在（MapNotFoundError）② location_id 若提供 → 同项目活动地点
             ③ x/y 范围 Pydantic 校验 ④ 落库
update_map:  改名校验 + root_location 改挂校验（同 ②③）；换图走 PUT /image（save → 删旧）
delete_map:  两级语义（§5.3）；真删时遍历子树地图文件删除（asset_store.delete）
children:    repo.children(map_id)（单 SQL JOIN）
```

### 5.5 排序与确定性

- maps 列表：`created_at DESC`（F10 list 默认 updated_at DESC 同款）
- pins 列表：`created_at ASC`（创建顺序稳定，展示层级确定性）
- children：`created_at ASC`（drill-down 顺序稳定）

---

## 6. 组织规则

- **目录归属**：新模块 `domain/models/map.py` + `domain/ports/map_*` + `domain/services/map_service.py` + `infrastructure/database/models|repositories/map*` + `infrastructure/assets/map_asset_store.py` + `api/routers/maps.py` + `cli/commands/map.py`——镜像 F9/F10 骨架（实体 + 仓储 + service + router + CLI）
- **资产目录**：`infrastructure/assets/`（新目录，本地文件资产统一落点；F30 kernel 已有 `infrastructure/kernel/` 同层先例）
- **deps 装配**：`api/deps.py` 新增 `get_map_service(db)`——注入 SQLiteMapRepository + LocalMapAssetStore + WorldRepositoryProtocol（location 校验）
- **日志**：loguru（创建/删除/换图/资产失败均记，F10 风格）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| 1 | root_location_id 指向不存在/软删/跨项目地点 | 422 MapRootLocationNotFoundError |
| 2 | 同一地点挂第二张图 | 422 MapRootLocationConflictError（partial unique 兜底） |
| 3 | pin location_id 指向不存在/软删/跨项目地点 | 422 MapPinLocationNotFoundError |
| 4 | 图片类型不在白名单（.exe/.svg…） | 422/500 MapAssetError（魔数校验拒绝） |
| 5 | 图片 > 10 MB | 422 MapAssetError |
| 6 | 图片文件缺失（data_dir 被手动删） | GET /image → 404「图片文件缺失」（DB 行仍在，可换图恢复） |
| 7 | 归档地图后访问 | 列表不可见、详情 200 可读（F24 语义）、pins 列表空（级联归档） |
| 8 | 归档地图 restore | 恢复 + pins 级联恢复 + 图片文件未删（直接可用） |
| 9 | 真删地图文件删除失败（占用/只读） | 记录 warning，DB 行删除成功（孤儿文件后续手动清理——不阻断删除） |
| 10 | 换图失败（新文件写失败） | 旧文件保留，DB 不变，抛 MapAssetError（不丢旧图） |
| 11 | 硬删地点 → 该地点 pin | FK SET NULL：pin 保留为纯注释（label 不变） |
| 12 | 硬删地图（级联）→ pins | CASCADE：pins 真删 + 文件删除 |
| 13 | 项目硬删 → maps/pins | CASCADE 全删 + 文件删除（service 级联） |
| 14 | children 查询无子地图 | 200 空列表（懒构建合法态） |
| 15 | 全局图（root NULL） | 允许多张；children 不可达（无父地点链路）——全局图是起点不是层级节点 |

---

## 8. 文件结构（对照真实源码树）

| 文件 | 变更 | 内容 |
|------|------|------|
| `backend/src/inkflow/domain/models/map.py` | **CREATE** | WorldMap/WorldMapCreate/WorldMapUpdate/MapPin/MapPinCreate/MapPinUpdate |
| `backend/src/inkflow/domain/ports/map_repository.py` | **CREATE** | MapRepositoryProtocol（add/get/get_by_name/list/update/soft_delete/hard_delete/restore + list_pins/add_pin/update_pin/soft_delete_pin/hard_delete_pin/restore_pin/children） |
| `backend/src/inkflow/domain/ports/map_errors.py` | **CREATE** | MapServiceError/MapNameConflictError/MapRootLocationConflictError/MapRootLocationNotFoundError/MapPinLocationNotFoundError/MapNotFoundError/MapPinNotFoundError/MapAssetError |
| `backend/src/inkflow/domain/services/map_service.py` | **CREATE** | 编排（§5.4）；依赖注入：MapRepositoryProtocol + MapAssetStoreProtocol + WorldRepositoryProtocol |
| `backend/src/inkflow/infrastructure/assets/__init__.py` | **CREATE** | 导出 MapAssetStoreProtocol/LocalMapAssetStore |
| `backend/src/inkflow/infrastructure/assets/map_asset_store.py` | **CREATE** | LocalMapAssetStore（save/delete/resolve + 魔数/大小校验 + 路径安全） |
| `backend/src/inkflow/infrastructure/database/models/map.py` | **CREATE** | MapORM/MapPinORM（§2.4） |
| `backend/src/inkflow/infrastructure/database/repositories/map_repo.py` | **CREATE** | SQLiteMapRepository（含 children JOIN、两级删除、级联语句） |
| `backend/src/inkflow/api/routers/maps.py` | **CREATE** | 14 端点（§3.1）；multipart 用 UploadFile |
| `backend/src/inkflow/api/app.py` | **MODIFY** | 注册 maps router（`include_router(maps.router)`） |
| `backend/src/inkflow/api/deps.py` | **MODIFY** | 新增 `get_map_service` 装配 |
| `backend/src/inkflow/cli/commands/map.py` | **CREATE** | `inkflow map` 组（§4） |
| `backend/src/inkflow/cli/app.py` | **MODIFY** | 注册 map 命令组 |
| `backend/tests/unit/test_map_repo.py` | **CREATE** | 仓储层（CRUD/级联/children JOIN/唯一约束） |
| `backend/tests/unit/test_map_service.py` | **CREATE** | 服务层（校验链/两级删除/文件生命周期编排） |
| `backend/tests/unit/test_map_asset_store.py` | **CREATE** | 资产层（save/delete/魔数/大小/路径穿越） |
| `backend/tests/unit/test_map_api.py` | **CREATE** | API 契约（multipart 上传/下载/错误映射） |
| `tests/cli/test_cli_map.py` | **CREATE** | CLI 命令（信封/退出码/图片上传） |

> **⚠️ CI 盲区防范（Issue #59/#61 教训）**：`tests/cli/test_cli_map.py` 是**新文件**，必须显式加入 ci.yml `integration-cli-backend` job 文件列表（Windows pytest 不展开 glob）——**本模块唯一需改 ci.yml 的项**。

---

## 9. 测试策略

### 层次

```text
单元（repo）:    maps/pins CRUD 往返 + 级联归档/真删 + children JOIN + 双唯一约束   ~14 cases
单元（service）: 校验链（地点不存在/跨项目/同名/重复 root）+ 两级删除 + 文件生命周期   ~16 cases
单元（asset）:   save 魔数白名单/大小上限/路径穿越拒绝/delete 幂等                    ~8 cases
API（集成）:     multipart 上传 201 → image 下载 → PATCH 元数据 → PUT 换图 → 错误映射 ~12 cases
CLI:             map 组命令 + pin 子组 + 图片上传/下载                                  ~10 cases
```

### 关键测试场景

1. **multipart 上传闭环**：TestClient `files={"file": (name, content, "image/png")}` → 201 → `GET /image` 返回同字节 → 相对路径存 DB
2. **children JOIN**：图 A pin→地点 B，地点 B 挂图 C → `children(A)` 含 C；无 pin 关联 = 空列表
3. **双唯一约束**：同名地图 422；同地点第二张图 422；全局图多张 200
4. **两级删除**：归档地图 → pins 级联归档 + 文件保留；再删 → pins 真删 + 文件物理删除（临时目录断言文件不存在）
5. **换图原子性**：新文件写失败（mock save 抛错）→ 旧文件与 DB 不变
6. **文件缺失**：删 data_dir 图片 → GET /image 404（DB 行在）
7. **FK SET NULL**：硬删地点 → pin 保留 location_id=None（纯注释）
8. **路径穿越**：`resolve("../../etc/passwd")` → 拒绝（ValueError/MapAssetError）
9. **Pydantic 坐标**：x=101/y=-1 → 422（字段校验）
10. **错误类复用**：ProjectNotFoundError 来自 world_errors（import 断言，防 F16 遮蔽回归）

### 覆盖率

模块行覆盖 ≥ 80%；全仓门禁 ADR-027：98.5/95.0（新表/新服务需足量测试维持——设计书 §8 风险表）。

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
| F6 上下文注入地点位置 | 数据地基先行（F35 §10 同） | 后续 |
| GUI 前端地图页 | 本 spec 只交付后端 API/CLI；前端随 GUI 迭代 | 后续 GUI 任务 |

---

## 11. 依赖关系

```text
F36 依赖:
  F10（world_settings + WorldRepositoryProtocol）— pin/root 地点校验（只读复用，零改动）
  F35（#173 地点树）— root_location_id 挂地点树；面包屑用 ancestors；drill-down 依赖地点关联
  F1（projects 表 + ProjectRepositoryProtocol）— 项目存在性校验
  F7（CLI 全局约定）— map 组信封/退出码

F36 被依赖:
  #175（跨书复制）— 地图资产复制 + pin 重挂（依赖 maps/map_pins 表结构）
```

**编号口径声明**：本模块为 0.6.0 世界观三连 Step 2（#174），非 PRD F 系列新业务模块——「F36」编号承接（F35=#173 地点树，F34=#169 CLI 恒 HTTP）。若与未来编号冲突以 ADR-019 v5+ 为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|-------------|
| 1 | 图片本地文件 + DB 相对路径 | data_dir/maps/<uuid>/main.<ext> | 本地单机架构、DB 不膨胀、FileResponse 直出（D3/D4） | BLOB（SQLite 膨胀）；云（架构冲突） |
| 2 | 坐标相对百分比 0-100 | Pydantic ge/le 校验 | 与分辨率解耦，换图不失效（设计书 §5.1） | 像素绝对坐标（换图失效） |
| 3 | 地图树与地点树同构 | root_location_id + children JOIN | drill-down 是叙事层级缩放；懒构建任何层可断 | 独立层级字段（与地点树脱钩） |
| 4 | 一个地点最多一张图 | partial unique (project, root_location) | 设计书「每个父地点可挂一张图」；全局图多张 | 多图/地点（导航歧义） |
| 5 | 两级删除 + 文件生命周期 | 归档留文件/真删删文件 | F24 语义延续；归档可恢复（文件在）；真删防孤儿 | 归档即删文件（恢复后图丢失） |
| 6 | 换图先写新后删旧 | save 成功才删旧文件 | 换图失败不丢旧图（原子性） | 先删旧（失败丢图） |
| 7 | root_location FK SET NULL | 地点硬删 → 图保留为全局图 | 地图是资产不该随地点消失；SET NULL 语义（F2 先例） | CASCADE（图随地点消失，资产损失） |
| 8 | pin location FK SET NULL | 地点硬删 → pin 保留为纯注释 | 硬删地点不级联删 pin（F15 跨模块语义核对先例） | CASCADE（删除 pin 注释） |
| 9 | 项目硬删 → 文件级联删 | service 遍历删除 | 防孤儿文件堆积；级联语义一致 | 文件残留（孤儿堆积） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 数据模型 + 建表（create_all 自动） | `pytest backend/tests/unit/test_map_repo.py -v` 全绿；新库表存在（PRAGMA table_list） |
| M2 | 资产存储（save/delete/resolve/校验） | `pytest backend/tests/unit/test_map_asset_store.py -v` 全绿（魔数/大小/路径穿越） |
| M3 | 服务编排（校验链/两级删除/文件生命周期） | `pytest backend/tests/unit/test_map_service.py -v` 全绿 |
| M4 | API 契约（multipart 上传/下载/换图/错误映射） | `pytest backend/tests/unit/test_map_api.py -v` 全绿 |
| M5 | children drill-down + 面包屑导航链路 | children JOIN 测试全绿；手工验证：图 A pin→B，B 挂图 C → children(A)=[C] |
| M6 | CLI map 组 | `pytest ../tests/cli/test_cli_map.py -v` 全绿（**且已追加 ci.yml integration-cli-backend job**） |
| M7 | 手工验证 | 上传图片建图 → pin 关联地点 → 换图 → 归档 → 恢复 → 真删（文件消失）→ 地点硬删 pin 转纯注释 |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；ADR-027 门槛（98.5/95.0）；`uv run ruff check src/ tests/unit/ ../tests/` + mypy 通过 |

> Issue #174 验收标准映射：上传图片+pin+关联地点 = M1-M4；地图树 drill-down = M5；懒构建 = M5/M7；面包屑 = M5（F35 ancestors 复用）；本地图片资产 = M2/M7。

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | **地图 MVP 范围**：只做「单图 + pin」还是连「地图树 drill-down + 面包屑导航」一起（设计书 Q3，建议：**一起**——children JOIN 成本差异小，且 drill-down 是设计书 §5.2 交互核心，拆开 = 二次返工）？ | 影响 API 面（children 端点）与估算 | B：一起（含 children + 面包屑导航链路） |
| Q2 | **图片文件生命周期**：真删地图时物理删除文件（建议 A）vs 保留文件避免误删？ | 影响磁盘占用与恢复语义 | A：归档保留、真删删除（与数据一致；§5.1 表） |
| Q3 | **地图列表的 root_location 过滤**：`GET /projects/{pid}/maps?root_location_id=<id>` 是否本轮提供（地图树前端渲染 + #175 复制需要）？ | 影响 API 面 | A：提供（简单过滤参数，向后兼容） |

---

*本文档为 F36 功能规格（What），实施步骤（How）见后续 `specs/f36-world-map/plan.md`。所有里程碑验收以本节 M1-M8 为准。*
