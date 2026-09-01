# F37: 世界观跨书复制（world-copy）— 功能规格
> **端**: backend

> **Spec 版本**: 1.2 | **日期**: 2026-08-10 | **依据**: 设计书 `design/world-geo-hierarchy-2026-08-08.md` §6（workspace）、PRD v2.1 §6.2 P1-02、F35 spec v1.1（地点树）+ F36 spec v1.1（地图）、Constitution P1-P6
>
> **Spec 变更**（1.1 → 1.2，2026-08-10 实现期修订）：§8 文件结构对照真实源码树修正——`map_asset_store.py` 的 `copy` 方法**已由 F36 合入实现**（#174）改为「无变更」；`map_repository.py`/`map_repo.py` 的 `list_by_root_locations` 改为「F36 已实现基础签名，F37 加 `include_global` 参数」；CLI 测试因 900 行护栏拆分新文件 `tests/cli/test_cli_world_copy.py`（需登记 ci.yml）；API 端点路径修正为 `/projects/{target_project_id}/world-settings/copy`（spec §3.1 一致）；`deps.py` 为新增 `get_copy_service(db)`；补列 test_world_repo.py/test_map_repo.py MODIFY。
>
> **所属阶段**: 0.6.0 世界观三连 Step 3（复用层，估算 2-3 人天）
>
> **关联 Issues**: [#175](https://github.com/zhx-xi/InkFlow/issues/175)（本模块）· #173（地点树，**前置依赖**）· #174（地图视图，**地图复制前置依赖**）· #211（删除语义统一，关联登记）
>
> **依赖**: ✅ F10（world_settings 表）· ✅ F35（#173 地点树：list_descendants 子树查询）· ✅ F36（#174 地图：maps/map_pins 表 + MapAssetStoreProtocol + list_by_root_locations）· ✅ F1（项目 FK）
>
> **参考 ADR**: [ADR-019](../../adr/packaging/ADR-019.md)（版本里程碑）· [ADR-002](../../adr/architecture/ADR-002.md)（六边形分层）· [ADR-012](../../adr/architecture/ADR-012.md)（错误处理）
>
> **状态**: ✅ 已实现（PR #223，#175 2026-08-09）

---

## 1. 概述

世界观条目强绑定 `project_id`（FK 非空 + 级联删除），系列小说/同宇宙作品无法共享设定，手动复制必然漂移。本模块提供**复制/导出**：把源项目的地点层级树（含地图资产）**递归复制**到目标项目——产品语言「设为模板 / 复制到新项目」。

设计书 §2.1 诉求拆解：本模块满足 **B（个人设定资产沉淀）100% + A（系列书）70%**；**引用共享**（project_id 可空 + 关联表）是后置路径，**本期不排期**（真实系列书需求触发再立项，设计书 §6.2）。

**核心交付**：

```text
F35/F36 现状:  地点树（parent_id + list_descendants）+ 地图（maps/map_pins + 本地资产）
F37 增量:      POST /projects/{target}/world-settings/copy（递归子树复制）
               + CLI `inkflow world copy`
               + 地图资产文件复制 + pin 重挂（依赖 F36）
               + 全局图复制（Q3=B）+ pin 转纯注释（评审修订）
               + 名称冲突跳过 + 结果报告
               零 schema 变更（复用既有表结构）
```

### 1.1 模块类型定位（F10 扩展型：复制操作，非新变体）

同 F35：**不新增实体表**，是 F10 世界观域的操作层扩展（在既有 F35/F36 数据之上新增一个跨项目复制编排）。特征：

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ 无（复用 world_settings/maps/map_pins） |
| 新 API 端点 | ✅ 1 个（POST copy） |
| 新 CLI 命令 | ✅ 1 个（`world copy`） |
| 核心机制 | ✅ 递归子树复制（list_descendants）+ id 映射重挂 + 地图资产复制 + 全局图复制 + 同名跳过 |
| 跨模块 MODIFY | ✅ F36 资产层加 `copy` 方法（MapAssetStoreProtocol 扩展，F36 v1.1 §5.1 已含） |
| 错误面 | CopySourceNotFoundError（404）/ CopyNameConflictError 不入错（跳过+warning） |

### 1.2 边界声明

- **不做引用共享**（project_id 可空 + project_world_refs 关联表）——设计书 §6.2 后置路径，真实系列书需求触发再立项（§10）
- **不做协作宇宙**（多作者共享）——本地单机架构冲突，设计书 §6.1 明确砍掉（D6）
- **复制是「值复制」**：源与目标完全独立，后续修改互不影响（与引用共享的本质区别，spec 显式声明）
- **零 schema 变更**：复用既有表结构，无迁移
- **删除语义联动（F35/F36 拍板）**：源项目世界观/地图为真删语义（无 is_deleted）；复制只读源、写目标——复制时源侧软删条目（F10 既有语义残留，见 F35 §1.2 边界 X）仍不复制（只复制活动条目）

---

## 2. 数据模型

**无新实体**。复制编排在既有表上执行，唯一新增的是**请求/报告 DTO**（`domain/models/copy.py`）：

```python
class WorldCopyRequest(BaseModel):
    """跨书复制请求 DTO.

    source_project_id: 源项目（世界观设定从哪来）.
    root_setting_id:   复制起点（指定子树）；None = 复制源项目全部活动世界观条目.
    """
    source_project_id: uuid.UUID
    root_setting_id: uuid.UUID | None = None


class WorldCopyResult(BaseModel):
    """复制结果报告 — 镜像 F10 WorldExtractionResult 风格（created/updated/warnings）.

    created:      复制到目标项目的世界观条目（新 id）.
    skipped:      目标项目同名冲突被跳过的源条目名.
    maps_created: 复制的地图（新 id + 新 image_path）.
    pins_created: 复制的 pin 数.
    warnings:     复制过程中的警告（冲突/文件复制失败/全局图 pin 转纯注释）.
    """
    created: list[WorldSetting]
    skipped: list[str]
    maps_created: list[WorldMap]
    pins_created: int
    warnings: list[str]
```

**复制语义规则**：

1. **活动条目**：只复制活动条目（F35/F36 真删语义下无软删行；F10 既有软删残留条目不复制）
2. **id 重映射**：全部新 UUID（不保留源 id）；`parent_id` 按 `old_id → new_id` 映射重建树结构；顶层保持 NULL
3. **字段全复制**：name/category/content/extra（含 `extra.scale`）原样复制
4. **名称冲突**：目标项目已有同名活动条目（`get_by_parent_and_name`——F35 v1.1 协议）→ **跳过该条 + warning**（不覆盖目标项目既有数据——安全默认，§12 决策 4）
5. **子树起点**：`root_setting_id` 提供 → 复制 `list_descendants(root)`（含自身）；缺省 → 复制源项目全部活动条目（整棵，Q2=A）
6. **地图复制**（依赖 F36）：源项目**与被复制地点关联**的地图（`root_location_id ∈ 复制地点 id 集合`）**+ 全局图（Q3=B）**→ 复制到目标项目；`root_location_id` 重映射（关联图）/ 保持 NULL（全局图）；图片文件复制；pins 复制（map_id + location_id 重映射；location 不在复制集合 → **转纯注释**，评审修订）
7. **全局图（root_location_id IS NULL，Q3=B）**：**复制**——与具体地点无关的世界观资产（总览图等）随世界观走；复制后 `root_location_id` 保持 NULL（目标项目全局图）
8. **事务性**：整个复制在**单事务**内（SQLite 事务包裹全部写）——中途失败回滚，不产生半复制状态

---

## 3. API 契约

### 3.1 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/projects/{target_project_id}/world-settings/copy` | 复制源项目世界观到目标项目 → 200 WorldCopyResult |

> ⚠️ **路由注册顺序**：`/world-settings/copy` 注册在 `/world-settings/{setting_id}` **之前**（F10 extract 端点同款先例——避免路径歧义，`copy` 被 `{setting_id}` 吞掉）。

### 3.2 请求/响应示例

```http
POST /api/v1/projects/2/world-settings/copy
Content-Type: application/json

{"source_project_id": "1", "root_setting_id": null}
```

```json
200
{"created": [{"id": "51", "project_id": "2", "name": "大越国", ...},
             {"id": "52", "project_id": "2", "name": "青州", "parent_id": "51", ...},
             {"id": "53", "project_id": "2", "name": "清河县城", "parent_id": "52", ...}],
 "skipped": [],
 "maps_created": [{"id": "30", "project_id": "2", "name": "清河县城图", ...},
                  {"id": "31", "project_id": "2", "name": "世界观总览图", "root_location_id": null, ...}],
 "pins_created": 7,
 "warnings": ["全局图「世界观总览图」的 2 个 pin 关联地点不在复制集合，已转为纯注释"]}
```

### 3.3 异常映射表

| 异常 | 状态码 | detail |
|------|--------|--------|
| CopySourceNotFoundError（新增） | 404 | 源项目不存在 |
| ProjectNotFoundError（F10 world_errors 复用） | 404 | 目标项目不存在 |
| CopyRootNotFoundError（新增） | 404 | 复制起点条目不存在/不在源项目 |
| 目标同名冲突 | **不入错** | 跳过 + warning（结果报告承载） |

> 错误类放 `world_errors.py`（F10 域内，COPY 类前缀）——不新建 errors 文件（单端点、错误面极小）。

---

## 4. CLI 命令签名

```bash
inkflow world copy <source_project_id> <target_project_id>
                  [--root <UUID>]              # 复制起点（缺省 = 整棵）
```

- F7 信封：`{"ok": true, "data": {"created": [...], "skipped": [...], "maps_created": [...], "warnings": [...]}}`
- 退出码：源/目标项目不存在 → 1 + `NOT_FOUND`；复制成功 → 0
- 目标项目已存在同名条目 → 跳过 + warning（**不失败**——复制是「尽量复制」，部分冲突可接受）
- 产品语言：「复制到新项目」（帮助文本）

---

## 5. 关键差异：递归子树复制编排

### 5.1 复制算法（`domain/services/copy_service.py`）

```text
copy(source_pid, target_pid, root_id=None):
  ① 目标项目存在（ProjectNotFoundError）；源项目存在（CopySourceNotFoundError）
  ② root_id 提供 → 校验在源项目活动条目内（CopyRootNotFoundError）
  ③ 取复制集合: root_id ? list_descendants(root_id) : repo.list_all_active(source_pid)
     （F35 list_descendants 复用——层序，父先于子）
  ④ 名称冲突预筛: 对每个源条目 get_by_parent_and_name(target_pid, parent_mapped, name)
     → 命中即入 skipped，不入复制集合（不参与 id 映射——其子条目 parent 指向被跳过
     条目时 → 顶层 + warning）
  ⑤ 落库: 逐个 add（新 UUID，parent_id 经 old→new 映射）
     → 复制集合按层序（父先），映射表 old_id → new_id 顺序建立
  ⑥ 地图复制（F36 v1.1）:
     查询: maps where project=source AND
           (root_location_id ∈ 复制地点 id 集合 OR root_location_id IS NULL)   # Q3=B 含全局图
     → 每个地图: asset_store.copy（§5.3）→ add（关联图 root_location_id 重映射 / 全局图保持 NULL）
     → pins 复制: map_id 映射 + location_id 映射
        - location ∈ 复制集合 → 重映射
        - location ∉ 复制集合（或 NULL 纯注释）→ 转纯注释（location=NULL，label/坐标保留）
          + warning 汇总
  ⑦ 单事务提交（失败回滚全部）
  ⑧ 返回 WorldCopyResult
```

### 5.2 层序依赖（load-bearing）

复制顺序**必须父先于子**（`list_descendants` 已保证层序）——子条目的 `parent_id` 映射依赖父条目的 `new_id` 已生成。若④中父条目被跳过（目标同名），其子孙条目的 parent 无处映射 → **置顶层 + warning**（不阻断复制——孤儿子树顶层化，目标项目内仍完整可导航）。

### 5.3 地图资产复制（依赖 F36 的 MapAssetStoreProtocol.copy）

```python
# F36 v1.1 MapAssetStoreProtocol 扩展:
async def copy(self, relative_path: str, *, map_id: uuid.UUID) -> str:
    """复制源图片到新地图目录 → 返回新相对路径（maps/<new_uuid>/main.<ext>）.

    源文件缺失（data_dir 被手动清理）→ 抛 MapAssetError → 该地图跳过 + warning
    （DB 行不复制——目标项目不产生缺文件地图）。
    """
```

- 复制失败（源文件缺失/IO 错误）→ **该地图跳过 + warning**（不阻断条目复制——条目是主交付，地图是附属资产）
- 文件复制是「字节复制」（`Path.read_bytes()` → save 同款写路径），不共享文件句柄

### 5.4 与 #169 的关系（⚠️ 边界声明）

**#169 CLI 恒 HTTP 已合入**（F38，2026-08-09）——本模块实现直接按「CLI 恒经 HTTP」落地：`world copy` 走 `ensure_kernel()` + `InkFlowHTTPClient` 调 POST `/projects/{target}/world-settings/copy` 端点（F38 豁免判据不适用：API 有对应端点 → 必须走 HTTP）。服务层/API 端点契约与 §5.1/§3 一致，不受传输层影响。

---

## 6. 组织规则

- **目录归属**：新文件 `domain/services/copy_service.py`（WorldCopyService）；DTO 放 `domain/models/copy.py`；错误类放 `world_errors.py`（COPY 前缀）；API 端点挂 `api/routers/world_settings.py`（复用既有 router，不新建 router——单端点）
- **依赖注入**：WorldCopyService(repository=WorldRepositoryProtocol, project_repo=ProjectRepositoryProtocol, map_repo=MapRepositoryProtocol, asset_store=MapAssetStoreProtocol)——map/asset 参数在 F36 未合入时**可选**（None → 地图复制跳过，条目复制照常；deps 装配按 F36 实际状态接线）
- **日志**：loguru——复制开始/完成/跳过/文件失败均记（含源/目标项目 id）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| 1 | 目标项目不存在 | 404 ProjectNotFoundError |
| 2 | 源项目不存在 | 404 CopySourceNotFoundError |
| 3 | root_setting_id 不在源项目/非活动 | 404 CopyRootNotFoundError |
| 4 | 目标项目同名条目 | 跳过 + warning（不覆盖） |
| 5 | 父条目被跳过，子条目无父映射 | 子条目置顶层 + warning（不阻断） |
| 6 | 源条目为空（源项目无世界观） | 200 空报告（created=[], warnings=[]）——非错误 |
| 7 | 地图源文件缺失 | 该地图跳过 + warning（条目复制照常） |
| 8 | **pin 关联地点不在复制集合** | **转纯注释**（location=NULL，label/坐标保留）+ warning（评审 R3/S3 修订——非跳过） |
| 9 | 复制中途 DB 失败 | 单事务回滚（零半复制） |
| 10 | **全局图（root NULL，Q3=B）** | **复制**：root_location_id 保持 NULL（目标项目全局图）；名称冲突（目标已有同名图）→ 该图跳过 + warning；pin 按规则 8 处理 |
| 11 | 复制结果目标项目同名条目列表为空但部分复制成功 | 200 正常（部分成功语义，warnings 说明） |
| 12 | F36 未合入（map_repo=None） | 条目复制照常，地图复制静默跳过（依赖声明：实现排期保证 F36 先合入，此分支仅防御） |

---

## 8. 文件结构（对照真实源码树）

| 文件 | 变更 | 内容 |
|------|------|------|
| `backend/src/inkflow/domain/models/copy.py` | **CREATE** | WorldCopyRequest / WorldCopyResult |
| `backend/src/inkflow/domain/services/copy_service.py` | **CREATE** | WorldCopyService（§5.1 编排） |
| `backend/src/inkflow/domain/ports/world_errors.py` | **MODIFY** | 新增 CopySourceNotFoundError / CopyRootNotFoundError |
| `backend/src/inkflow/domain/ports/world_repository.py` | **MODIFY** | 新增 `list_all_active(project_id) -> list[WorldSetting]`（全量活动条目，copy 缺省起点用；F35 v1.1 已加 get_by_parent_and_name 冲突预筛复用） |
| `backend/src/inkflow/infrastructure/database/repositories/world_repo.py` | **MODIFY** | 实现 `list_all_active`（活动条目全量，created_at ASC 稳定排序） |
| `backend/src/inkflow/infrastructure/assets/map_asset_store.py` | **无变更** | `copy` 方法**已由 F36 合入实现**（#174，spec v1.1 §8 扩展点已兑现）——F37 仅复用 |
| `backend/src/inkflow/domain/ports/map_repository.py` | **MODIFY** | `list_by_root_locations` 签名扩展 `include_global: bool = True`（F36 已实现基础签名（project_id, location_ids）；F37 加全局图参数 Q3=B） |
| `backend/src/inkflow/infrastructure/database/repositories/map_repo.py` | **MODIFY** | 实现 `include_global`（WHERE `root_location_id IN (:ids) OR (include_global AND root_location_id IS NULL)`；空列表 + False → 空） |
| `backend/src/inkflow/api/routers/world_settings.py` | **MODIFY** | 新增 POST `/projects/{target_project_id}/world-settings/copy` 端点（**注册在 `{setting_id}` 之前**，F10 extract 先例）；`_get_copy_svc` 装配 copy service；`_run_service` 加 CopySource/CopyRoot 两个 404 分支 |
| `backend/src/inkflow/cli/commands/world.py` | **MODIFY** | 新增 `copy` 子命令（位置参数 `<source> <target>` + `--root`；CLI 恒 HTTP——POST copy 端点，F38 后形态） |
| `backend/src/inkflow/api/deps.py` | **MODIFY** | 新增 `get_copy_service(db)` 装配 WorldCopyService（repository/project_repo/map_repo/asset_store 全量接线） |
| `backend/tests/unit/test_copy_service.py` | **CREATE** | 复制编排（层序/映射/冲突/回滚/地图复制/全局图/pin 转纯注释） |
| `backend/tests/unit/test_copy_api.py` | **CREATE** | API 契约（copy 端点/错误映射/路由顺序） |
| `tests/cli/test_cli_world_copy.py` | **CREATE** | `world copy` 命令用例（信封/退出码/跳过；F37 拆分——test_cli_world.py 追加后超 900 行护栏，F35/F36 先例） |
| `backend/tests/unit/test_world_repo.py` | **MODIFY** | 追加 `list_all_active` 契约（3 用例：软删过滤/created_at ASC 排序/空项目） |
| `backend/tests/unit/test_map_repo.py` | **MODIFY** | 升级 `test_list_by_root_locations`（显式 include_global=False 保持原语义）+ 追加 include_global 契约（4 用例） |

> **CI 盲区防范**：`tests/cli/test_cli_world_copy.py` 为 F37 新文件——已追加进 ci.yml `integration-cli-backend` job 文件列表（**必须登记，否则 CI 盲区绿**；F35/F36 拆分先例同款）。`backend/tests/unit/` 新文件由 unit-test-backend 自动收集无需登记。

---

## 9. 测试策略

### 层次

```text
单元（service）: 复制编排（层序/映射/冲突跳过/父跳子置顶/空源/单事务回滚）   ~12 cases
单元（service）: 地图复制（关联图/全局图/文件缺失跳过/pin 重挂/pin 转纯注释） ~10 cases
单元（repo）:    list_all_active（过滤软删残留/稳定排序）                     ~3 cases
API（集成）:     copy 端点（200 报告/404 源与目标/路由顺序 copy 不被 {id} 吞） ~5 cases
CLI:            world copy（信封/退出码/NOT_FOUND）                          ~4 cases
```

### 关键测试场景

1. **整棵复制**：源 3 层树（国→州→县）→ 目标空项目 → created 3 条、parent_id 映射正确、树结构完整
2. **子树复制**：root=州 → 复制州+县（国不复制）
3. **名称冲突**：目标已有「青州」→ skipped=[青州]、其余复制、无覆盖（目标青州内容不变）
4. **父跳子置顶**：目标已有「州」→ 州 skipped，县复制但 parent_id=None（顶层）+ warning
5. **地图复制**：源图 root=县（在复制集合）→ 目标图 root 重映射；图 pin 关联复制地点 → pin 复制重挂；纯注释 pin → location 保持 NULL
6. **全局图复制（Q3=B）**：源全局图（root NULL）+ pin 关联复制集合内地点 → 目标 root NULL、pin 重挂；**pin 关联复制集合外地点 → 转纯注释（location=NULL，label/坐标保留）+ warning**；目标已有同名图 → 该图跳过 + warning
7. **地图文件缺失**：mock asset_store.copy 抛 MapAssetError → 该图跳过 + warning、条目复制照常
8. **单事务回滚**：复制中途 mock add 抛错 → 目标项目零新增（回滚断言）
9. **空源**：源项目无世界观 → 200 空报告
10. **路由顺序**：POST /world-settings/copy 命中 copy 端点而非 404/路径歧义（F10 extract 先例）
11. **F36 未合入防御**：map_repo=None → 条目复制照常

### 覆盖率

模块行覆盖 ≥ 80%；全仓门禁 ADR-027：98.5/95.0。

---

## 10. 不在范围内

| 项 | 原因 | 归属 |
|----|------|------|
| 引用共享（project_id 可空 + project_world_refs） | 设计书 §6.2 后置路径：真实系列书需求触发再立项 | 未排期 |
| 协作宇宙/多作者共享 | 本地单机架构冲突（设计书 D6） | 永不 |
| 复制后自动同步/双向同步 | 引用共享的后置能力；复制是值复制（§1.2） | 未排期 |
| 模板管理（命名模板/模板列表/模板市场） | 「设为模板」当前 = 复制到新项目（产品语言）；独立模板库后续 | 未来 |
| 导出为外部文件（JSON/zip 档案） | 跨书复用最小闭环 = 项目内复制；外部导出后续 | 未来 |
| 引用式复制（目标引用源条目） | 与值复制语义相反，属引用共享路径 | 未排期 |
| GUI 复制按钮 | Q1 拍板：CLI 先行，GUI 后补 | 后续 GUI 任务 |
| 源项目删除语义（真删 #211 联动） | 复制只读源；删除语义统一属 #211 | #211（0.8.0） |

---

## 11. 依赖关系

```text
F37 依赖:
  F35（#173 地点树）— list_descendants 子树查询（复制起点/层序）+ get_by_parent_and_name（冲突预筛）
  F36（#174 地图）— maps/map_pins 表 + MapAssetStoreProtocol.copy + list_by_root_locations（地图复制；F36 先合入）
  F10（world_settings 表）— 落库
  F1（projects 表）— 源/目标项目校验

F37 被依赖:
  无（世界观三连末端；#169 CLI 恒 HTTP 合入后 CLI 调用路径换，服务不变）
```

**编号口径声明**：本模块为 0.6.0 世界观三连 Step 3（#175），非 PRD F 系列新业务模块——「F37」编号承接（F38=#169 / F35=#173 / F36=#174）。若与未来编号冲突以 ADR-019 v5+ 为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|-------------|
| 1 | 复制先行、引用后置 | 值复制（零 schema 变更） | 满足诉求 B 100% + A 70%；引用共享等真实需求（设计书 D5） | 引用共享先行（schema 变更 + 唯一索引粒度连锁，无场景买单） |
| 2 | 复制集合 = 子树或整棵（Q2=A） | root_setting_id 可选 | 「设为模板」全量 + 「复制某分支」子树兼顾 | 仅全量（无法只带走系列书部分设定）；仅子树（模板场景繁琐） |
| 3 | id 全新建 + 映射重挂 | old→new 映射表 | 目标项目独立（值复制语义）；避免与目标既有 id 冲突 | 保留源 id（跨项目 id 冲突） |
| 4 | 同名冲突跳过不覆盖 | get_by_parent_and_name 预筛 | 目标项目数据优先（安全默认）——复制不应破坏既有设定 | 覆盖（破坏目标数据）；报错中止（复制可用性差） |
| 5 | 父跳过 → 子置顶层 | 孤儿子树顶层化 + warning | 不阻断复制；目标项目内树仍完整可导航 | 级联跳过整棵（丢失大量设定）；报错中止 |
| 6 | 单事务全复制 | 一个事务 | 零半复制状态（中途失败回滚） | 逐条提交（失败留半树） |
| 7 | 地图复制失败跳过 | asset_store.copy 异常 → warning | 条目是主交付，地图是附属资产 | 整体失败（丢条目复制） |
| 8 | **复制全局图（Q3=B 拍板）** | root NULL 地图一并复制，root 保持 NULL | 全局图是世界观资产（总览图随世界观走）；用户拍板 | 跳过全局图（原 spec 建议——被用户翻转） |
| 9 | **pin 不在复制集合 → 转纯注释（评审 R3/S3 修订）** | location=NULL，label/坐标保留 + warning | 复用 F36「硬删地点 → pin SET NULL」先例；图资产完整、用户可手动重新关联 | 跳过 pin（图信息丢失）；整体失败（不可用） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | copy_service 整棵/子树复制 + 层序映射 | `pytest backend/tests/unit/test_copy_service.py -k tree` 全绿 |
| M2 | 冲突语义（跳过/父跳子置顶/不覆盖） | `pytest backend/tests/unit/test_copy_service.py -k conflict` 全绿 |
| M3 | 地图复制（关联图/全局图/文件复制/pin 重挂/pin 转纯注释/文件缺失跳过） | `pytest backend/tests/unit/test_copy_service.py -k map` 全绿（含 Q3=B 全局图用例 + 转纯注释用例） |
| M4 | 单事务回滚 + 空源 | `pytest backend/tests/unit/test_copy_service.py -k rollback` 全绿 |
| M5 | API copy 端点（含路由顺序） | `pytest backend/tests/unit/test_copy_api.py -v` 全绿 |
| M6 | CLI world copy | `pytest ../tests/cli/test_cli_world.py -v` 全绿 |
| M7 | 手工验证 | 源项目建 3 层树 + 1 关联图 + 1 全局图（含跨集合 pin）→ `world copy` 到新项目 → 目标树结构/图/pin 完整、全局图 root NULL、跨集合 pin 转纯注释 → 再复制同名项目 → 跳过 + warning |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；ADR-027 门槛（98.5/95.0）；`uv run ruff check src/ tests/unit/ ../tests/` + mypy 通过 |

> Issue #175 验收标准映射：递归子树复制 = M1；地图资产复制 + pin 重挂 = M3；全局图复制 = M3/M7；产品入口 = M5/M6/M7；引用共享后置 = §10 登记。

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 结论 |
|---|------|------|------|
| Q1 | 复制入口：CLI 先行 + API 同步？ | API 面与 GUI 排期 | ✅ 已确认（2026-08-09 拍板：**选项 A**）——**CLI 先行 + API 同步提供**（§3/§4） |
| Q2 | 复制范围：整棵 + 子树可选？ | copy 请求模型与算法 | ✅ 已确认（2026-08-09 拍板：**选项 A**）——**root_setting_id 可选，缺省整棵**（§2 规则 5） |
| Q3 | 全局图处理：跳过 or 复制？ | 地图复制语义 | ✅ 已确认（2026-08-09 拍板：**选项 B**，暂定→固化）——**复制全部全局图，root 保持 NULL；pin 不在复制集合转纯注释**（§2 规则 7/§5.1 ⑥/§7 场景 10/§12 决策 8-9） |

---

*本文档为 F37 功能规格（What），实施步骤（How）见后续 `specs/f37-world-copy/plan.md`。所有里程碑验收以本节 M1-M8 为准。*
## 14. 动作确认

> 基于 §3 API + §4 CLI + §7 边界事实的状态流表，不新增行为。

### 14.1 端点状态流

| 端点 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| POST /api/v1/projects/{target_project_id}/world-settings/copy | 源/目标项目存在·root 在源项目 | 递归复制子树（层序）→ 条目/地图/pin 合并落库（单事务） | 200 + WorldCopyResult（created/skipped/maps_created/pins_created/warnings） | 404 CopySourceNotFoundError（源项目不存在）；404 ProjectNotFoundError（目标项目不存在）；404 CopyRootNotFoundError（复制起点条目不存在/不在源项目） | 注册于 /world-settings/{setting_id} 之前（防路径歧义）；目标同名 → 跳过 + warning 不失败；父被跳过 → 子置顶层 + warning；地图源文件缺失 → 该图跳过 + warning；pin 关联地点不在复制集合 → 转纯注释（location=NULL）；源为空 → 200 空报告；DB 失败 → 单事务回滚 |

### 14.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| world copy <source_project_id> <target_project_id> | 源/目标项目存在 | 同端点语义（CLI 恒 HTTP，POST copy 端点） | 0 + {ok:true, data:{created,skipped,maps_created,warnings}} | 源/目标项目不存在 → 1 + NOT_FOUND | --root <UUID> 复制起点（缺省 = 整棵）；目标同名 → 跳过 + warning（不失败） |

### 14.3 验收锚点

- A1：目标项目同名条目 → 跳过 + warning（不覆盖、不失败——复制是「尽量复制」）
- A2：root_setting_id 不在源项目/非活动 → 404 CopyRootNotFoundError
- A3：父条目被跳过 → 子条目置顶层 + warning（不阻断）
- A4：pin 关联地点不在复制集合 → 转纯注释（location=NULL，label/坐标保留）+ warning
- A5：复制中途 DB 失败 → 单事务回滚（零半复制）
- A6：源项目无世界观条目 → 200 空报告（created=[], warnings=[]，非错误）
