# 卷数据模型统一 — Volume 分组与卷纲(level=volume)显式关联
> **端**: backend

> **Spec 版本**: 1.0 | **日期**: 2026-08-23 | **依据**: 0.12.0 多需求分析 D2=A（用户拍板 2026-08-23），PRD §6.1 F2/F11
> **所属阶段**: 0.12.0 — P0「卷概念统一」
> **关联 Issues**: [#592](https://github.com/zhx-xi/InkFlow/issues/592)
> **依赖**: F2 (chapter_service，Volume CRUD) ✅；F11 (outline_service，Outline level=volume) ✅；F43 P3（大纲三级 structure）✅
> **状态**: 📝 草案

---

## 1. 概述

项目里存在**两个不同的「卷」**，二者职责不同、必须**并存且显式对齐**（决策 D2=A，勿合并成一实体）：

1. **`Volume` 实体**（`chapter.volume_id` 分组、`order_index` 排序）——管**章节归属**。
2. **`Outline.level=volume`（卷纲）**——管**大纲叙事层级**（三级大纲 overall/volume/chapter 的中层）。

本 spec 为二者建立**显式关联字段**：一个卷至多挂一个卷纲（一一对应），并提供「当前卷 → 关联卷纲」解析链。

**核心价值**: 用户可以在「章节分组卷」与「大纲叙事卷纲」之间建立可往返的显式映射，为 F6 上下文注入（总纲+所在卷纲+当前章细纲三级链）与 GUI 卷/章树渲染提供权威数据面——不再依赖 `project.config.extra` 字符串或猜测关联。

**方向裁定**: 关联字段落在 **`Outline` 上（`volume_id`）**，镜像既有 `chapter_id`（仅 level=chapter 可设）——叙事层（大纲）引用写作层实体（Volume/Chapter）的既有惯例。`Outline.level=volume` 的卷纲持有 `volume_id` 指向它对应的 `Volume`。

---

## 2. 数据模型

### 2.1 Outline 实体新增 `volume_id`（F43 P3 §2.8 基础上）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，DB int 自增 |
| project_id | UUID | FK→projects.id, NOT NULL | 所属项目 |
| name | str | NOT NULL, 1-50, 去空白 | 大纲名 |
| description | str | NOT NULL, DEFAULT "" | 大纲描述 |
| sort_order | int | NOT NULL, DEFAULT 0, ≥0 | 排序权重 |
| level | str | NOT NULL, DEFAULT "chapter" | 枚举 `overall`/`volume`/`chapter` |
| parent_id | UUID? | NULLABLE, FK→outlines.id SET NULL | 父大纲（level 链） |
| chapter_id | UUID? | NULLABLE, FK→chapters.id SET NULL | **仅 level=chapter 可设**（F43 P3） |
| **volume_id** | **UUID?** | **NULLABLE, FK→volumes.id SET NULL** | **仅 level=volume 可设（本 spec）** |
| extra | dict | NOT NULL, DEFAULT {} | 扩展字段 |
| created_at / updated_at | datetime | NOT NULL, AUTO | UTC |

**`volume_id` 业务规则**:
- 仅 `level=volume` 的 Outline 可设 `volume_id`（对应「卷纲」）；其他 level 设了 → 422。
- `volume_id` 指向的 Volume 必须存在且与 Outline 同项目；不存在/跨项目 → 422。
- **一个 Volume 至多关联一个卷纲**（一一对应）：DB 层对 `outlines.volume_id` 建唯一索引（见 §7 迁移），服务层在写入前校验重复 → 422。
- `Update` 传 `""` = 清除（置 None，对齐 `chapter_id`/`parent_id` 先例）。

### 2.2 DTO 扩展

```python
class OutlineCreate(BaseModel):
    ...
    volume_id: uuid.UUID | None = None  # 仅 level=volume 可设

class OutlineUpdate(BaseModel):
    ...
    volume_id: uuid.UUID | str | None = None  # str "" = 清除卷关联
```

---

## 3. 关联与校验规则（双向校验）

| # | 规则 | 触发 | 结果 |
|---|------|------|------|
| V1 | `volume_id` 非空且 `level != "volume"` | create/update outline | 422（`OutlineVolumeRefError`） |
| V2 | `volume_id` 非空且指向 Volume 不存在 / 跨项目 | create/update outline | 422（`OutlineVolumeRefError`） |
| V3 | 同项目已有一条 `level=volume` 且 `volume_id=X` 的卷纲（排除自身） | create/update outline | 422（`OutlineVolumeRefError`，卷已关联卷纲） |
| V4 | 未设 `volume_id` 的 `level=volume` 卷纲 | create/update outline | 合法（卷纲可暂不关联写作分组卷） |

**实现要点**:
- `OutlineService._validate_outline_hierarchy` 扩展 `volume_id` 分支，镜像 `chapter_id` 校验；复用已注入的 `chapter_repo`（`ChapterRepositoryProtocol.get_volume`）做 Volume 存在性/同项目校验（不新增构造参数，向后兼容）。
- 新增错误类 `OutlineVolumeRefError(OutlineServiceError)`，API 层映射 422（消息即 detail）。
- **解析链**：`OutlineService.get_volume_outline(volume_id) -> Outline | None` —— 按 `level=volume AND volume_id=X` 返回关联卷纲，无则返回 None（「返空并提示」）。

---

## 4. API 契约

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/projects/{project_id}/outlines` | 创建大纲（含卷纲） | 增 `volume_id?: UUID` 透传 | 201 + Outline |
| PATCH | `/api/v1/outlines/{outline_id}` | 更新大纲（`volume_id=""` 清除） | `OutlineUpdate`（含 volume_id） | 200 + Outline |
| GET | `/api/v1/outlines/by-volume/{volume_id}` | 解析「当前卷 → 关联卷纲」 | — | 200 + Outline；无关联 → 404 |

**错误**:
- `volume_id` 规则违反 → 422（`OutlineVolumeRefError` 消息）。
- 解析 `by-volume` 无关联卷纲 → 404「卷纲不存在」。

---

## 5. 删除联动语义

| 删除动作 | 对关联影响 | 实现 |
|---------|-----------|------|
| 删除 **Volume** | 其关联卷纲的 `volume_id` 置 NULL（卷纲保留，解绑） | `chapter_repo.delete_volume` 显式 `UPDATE outlines SET volume_id=NULL WHERE volume_id=X`（镜像 `delete_chapter` 清 `chapter_id` 先例；DB FK SET NULL 兜底） |
| 删除 **卷纲**（level=volume Outline） | Volume 保留，关联消失 | outline 删除自然解绑，Volume 侧无残留字段 |

---

## 6. 文件结构

```
backend/src/inkflow/
├── domain/
│   ├── models/outline.py              ← MODIFY: Outline/OutlineCreate/OutlineUpdate 加 volume_id
│   ├── ports/outline_errors.py        ← MODIFY: 新增 OutlineVolumeRefError
│   └── services/outline_service.py    ← MODIFY: _validate_outline_hierarchy 加 volume_id 分支 + get_volume_outline
├── infrastructure/database/
│   ├── models/outline.py              ← MODIFY: OutlineORM 加 volume_id 列 + 唯一索引
│   └── repositories/outline_repo.py   ← MODIFY: 双向映射透传 volume_id + get_outline_by_volume
├── infrastructure/database/.../chapter_repo.py ← MODIFY: delete_volume 清 outlines.volume_id
├── api/routers/outlines.py            ← MODIFY: OutlineCreateBody 加 volume_id 透传 + by-volume 端点
└── core/database.py                   ← MODIFY: ensure_outline_volume_id_column 迁移
```

---

## 7. 迁移（轻量幂等）

项目无 alembic 基建（`create_all` 管理 schema）。新增 `ensure_outline_volume_id_column(conn)`（镜像 `ensure_outline_columns`）:

1. `PRAGMA table_info(outlines)` → 无 `volume_id` → `ALTER TABLE outlines ADD COLUMN volume_id INTEGER`。
2. `CREATE UNIQUE INDEX IF NOT EXISTS uq_outlines_volume_id ON outlines(volume_id)`（SQLite 唯一索引允许多个 NULL，实现「一券一纲」兜底）。
3. 表不存在（全新环境）→ no-op，等 `create_all` 建新表（ORM 已含列 + 索引）。

接线点: `api/app.py` 在 `ensure_outline_columns` 之后追加 `await conn.run_sync(ensure_outline_volume_id_column)`。

---

## 8. 测试策略（TDD RED 起点）

R 系列（本 spec）——镜像 `test_outline_p3.py` 四层失败形态:

- **Models**（R1/R2）: `Outline`/`OutlineCreate`/`OutlineUpdate` 含 `volume_id` 字段（默认 None）；`OutlineUpdate` `level="volume"` 合法；`volume_id` 非法设置经 service 校验。
- **Service**（R3-R6）: `volume_id` 非空且 level≠volume → `OutlineVolumeRefError`；指向不存在 Volume → 422；同项目已有卷纲引用同一 Volume → 422；未设 volume_id 的卷纲 → 合法创建。
- **Repo**（R7）: ORM↔领域往返含 `volume_id`；`get_outline_by_volume` 解析。
- **API**（R8）: POST 透传 `volume_id`；PATCH 透传 `volume_id=""` 清除；`GET by-volume` 解析。
- **联动**（R9）: `delete_volume` 后卷纲 `volume_id` 置空；`delete_outline` 后 Volume 保留。
- **DB 迁移**（R10）: `ensure_outline_volume_id_column` 加列 + 建索引 + 幂等 + 表不存在 no-op。

---

## 9. 不在范围内

- ❌ 合并 Volume 与卷纲成一实体（D2=A 明确否决）。
- ❌ F6 上下文注入的三级链消费（属 #568/F6，消费本 spec 的解析链）。
- ❌ GUI 卷/章树渲染改造（前端职责，本 spec 仅数据面）。
- ❌ `project.config.extra["outline"]` 旧字段迁移（读旧 config 的 F6 Source 单独处理）。

---

## 10. 依赖关系

```
卷概念统一（f56-volume-outline-link）依赖:
  F2 (chapter_service) ✅ — Volume 实体 + delete_volume 联动
  F11 (outline_service) ✅ — Outline.level=volume + _validate_outline_hierarchy
  F43 P3 ✅ — 大纲三级结构 + chapter_id 先例（volume_id 镜像其语义）

卷概念统一（f56-volume-outline-link）被依赖:
  F6 (context_service) — 上下文注入三级链（总纲/卷纲/章细纲）
  F0.12.0 GUI 卷/章树 — 按 volume_id 分组渲染 + 卷纲入口
```
