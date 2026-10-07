# F10: 世界观管理 (world_service) — 功能规格

> **时间口径（ADR-055 / #1000）**：本模块时间字段（created_at/updated_at）**存储 / API / MCP / `--json` 一律 UTC ISO 原始值**；CLI 人类输出经 `cli/_time.format_local` 转**系统本地时区**显示（'YYYY-MM-DD HH:mm:ss'，naive 串=UTC 口径先补 tzinfo 再换算）。硬约束惯例，非可配置开关。
>
> **端**: cross

> **Spec 版本**: 1.7 | **日期**: 2026-10-07 | **依据**: PRD v2.1 §6.2 P1-02, Constitution P1-P6, ADR-019, ADR-027
> **所属阶段**: 0.9.0 里程碑（世界观分类 CRUD，issue #389，估算 2-4 人天）
> **关联 Issues**: [#40](https://github.com/zhx-xi/InkFlow/issues/40)（v1.0 本体）、[#211](https://github.com/zhx-xi/InkFlow/issues/211)（v1.1 删除语义统一）、[#389](https://github.com/zhx-xi/InkFlow/issues/389)（v1.2 分类实体 CRUD）、[#1334](https://github.com/zhx-xi/InkFlow/issues/1334)（v1.4 分类 kind 挂根设计定义 · 已拍板 ①C）、[#1483](https://github.com/zhx-xi/InkFlow/issues/1483)（v1.7 `--content-file`）
> **依赖**: F1 ✅, F5 ✅（前置）；F6 ✅（数据源集成点）；F9/F11/F12/F13 ✅（跨模块统一，§8.2）；F14/F15 ✅（连锁适配，§8.2）
> **参考 ADR**: [ADR-027](../../adr/test-ci/ADR-027.md)（覆盖率门禁）
> **状态**: ✅ 已实现 v1.0（PR #57）+ v1.1（PR #312）；🔨 v1.2 实施中（#389）

> **Spec 变更（v1.2 → v1.3，2026-09-17，#495）**: §8.3 迁移章节补注——`character_relations` 表已废弃并入 `knowledge_relations`（#495 新增幂等迁移 `ensure_character_relations_merged_into_knowledge`，接线于 `ensure_character_drop_is_deleted` **之后**）；该 helper 的 `character_relations` 分支与 #831「`DROP TABLE characters` FK CASCADE 清空 `character_relations`」说明自此**仅适用旧库升级路径**（新库/已迁移库该表不存在 → 持续 no-op）。正文其余表述（迁移机制、FK=OFF 独立连接语义）不变。
> **Spec 变更（v1.6 → v1.7，2026-10-07，#1483）**: `world create` / `world update` 新增 `--content-file <path>`（从 UTF-8 文件读取条目正文，解决内联 `--content` 受命令行长度限制（Windows ~32KB）且中文经 PowerShell 管道易 ANSI 误码）。语义与互斥规则 = F7 §4.0 通用约定：与 `--content` **不可同传**（同传 → 退出码 2 + stderr 文案，不发生写入）；文件缺失/不可读 → `VALIDATION_ERROR` + 退出码 1（不泄漏栈回溯）；文件内容**原样**落库（不 strip、不转码）。§4.1 签名与 §15.2 状态流同步；不传 `--content-file` 时行为不变。
> **Spec 变更（v1.5 → v1.6，2026-10-07，#1485）**: AI 提取写入策略收敛——**契约源在 F14 §5.8**，本节登记 F10 侧语义升级：① setting 类别归属改为「对项目已有分类做匹配」（LLM 给出项目分类之外的类别 → 落空串 + warning，不再原样落库）；② 条目匹配锚点从「精确同名」扩展为「同名 → 近义（归一化后互为子串且较短者 ≥ 较长者一半长）→ 新建」，近义条目合并进已有条目（`content` 追加）而非新建；③ 新增 `granularity`（fine/coarse 每源条目上限）/ `dry_run`（零写入预览）参数与 `batch_id` 批次标识（整批回滚见 F14 §5.8.5）；④ `WorldSetting` 新增 `batch_id` 字段 + `world_settings.batch_id` 列（可空 VARCHAR(64)，幂等迁移 `ensure_world_settings_batch_id_column`）。验收断言见 `backend/tests/unit/domain/ports/test_extract_dilution_1485.py`。
> **Spec 变更（v1.4 → v1.5，2026-10-06，#1481）**: 新增 §8.4「建项目自动建根 + 存量兜底（跨模块 MODIFY 清单）」——登记**默认根条目形态**（`name="世界观总纲"` / `parent_id=NULL` / `category=""` / `content=""`，常量 `DEFAULT_WORLD_ROOT_NAME`）+ 跨模块改动落点（`world_service.ensure_root_setting` / `project_service.create_project` 的 `root_initializer` 钩子 / `deps.py` 接线 / `core/database.py` 的 `ensure_world_root_for_projects` 幂等迁移 / `app.py` lifespan）。**根必存在不变量**（建项目即建根 + 存量补根）由本模块与 F35 共同定义——数据模型与端点契约（§2/§3）**无变化**，仅新增默认条目与启动期迁移。**前置核验**：issue 报的 `'NoneType' object is not subscriptable` 系用户脚本自身，服务端现状已是 422 校验提示（无 500 路径）。
> **Spec 变更（v1.3 → v1.4，2026-10-02，#1334 设计单）**: 新增 §16「分类 kind 与条目挂根语义（设计定义 · 已拍板 ①C）」——登记事实基线（#641 自动挂根 / #699 分类 kind / #721 地图树 kind 分流 / #834 一项目一根 / #1321 非根必填分类）+ ①abstract 条目父级三选项 (a)/(b)/(c) + ②geo 保持现状 + ③kind 判定权与无分类边界 + 迁移影响评估 + 原型 kind 表达自相矛盾收敛规则。**同步对齐 spec 漂移**：§2.6/§2.5 补 `WorldCategory.kind`（#699 已实现、此前未记）、§12 补登记 #699 决策。**本变更为设计定义，无实现**（① 已拍板 ①C，实施另起轨）。
> **Spec 变更（v1.1 → v1.2，2026-08-16，issue #389）**: 世界观分类从「条目平铺属性」升级为「独立受控词表实体」（反转 v1.0 §2.2「不建独立分组表」决策）。① 新增 `world_categories` 表 + `WorldCategory` 领域实体（§2.2/§2.6）；② 新增分类 CRUD 四端点（§3.1，10→14 端点）；③ 分类重命名/删除反向同步条目 `category` 字符串——删除置空、重命名改名（§6.1/§7，拍板 D2=A）；④ 前端分类 chips 来源改为分类实体（移除 `DEFAULT_WORLD_CATS=['地图']` 硬编码），世界观 tab 导航修正（进分类列表视图非地图工作台）+「地图视图」独立入口（§14）；⑤ 镜像 F9 CharacterGroup 模式（§12）。

> **Spec 变更（v1.0 → v1.1，2026-08-13，issue #211）**: 删除语义统一——普通实体软删→真删。① WorldSetting 移除 `is_deleted` 字段（§2.1/§2.5）；② partial unique → 全唯一索引（§2.4）；③ DELETE 默认真删（移除 `force` 软删路径），restore 端点/命令移除（§3/§4）；④ 提取合并移除「软删同名→新建+warning」分支（§5.4）；⑤ 跨模块 F9/F11/F12/F13/F14/F15 同步适配（§8.2 全量 MODIFY 清单）；⑥ `is_deleted` 列移除 + 存量软删数据迁移（§8.3）。**F1 项目（回收站）与 F24 会话（归档）保留软删语义，不在本次变更范围**（§10）。

>
> **快速导航**（2026-08-08 #201 + 2026-08-13 v1.1）：
> 1. 概述 · 2. 数据模型 · 3. API 契约 · 4. CLI 命令签名
> 5. AI 提取模式 · 6. 分类与查询规则 · 7. 边界情况与错误处理 · 8. 文件结构
> 8.2 跨模块 MODIFY 清单 · 8.3 数据库迁移 · 9. 测试策略 · 10. 不在范围内
> 11. 依赖关系 · 12. 关键架构决策记录 · 13. 验收标准 · 14. 影响面评估结论 · 待澄清问题
---

## 1. 概述

管理小说的**世界观条目**（创建/查询/更新/真删除），以**类别（category）**承载世界观层级设定（规则/设定/约束/组织/地理等），并支持**从章节文本用 LLM 自动提取世界观信息**（条目名/类别/内容）。

**核心价值**: 作者与 AI Agent 可以维护结构化世界观设定；AI 提取把「写在正文里的世界观信息」沉淀为可复用的设定档案，为 F6 上下文注入（世界观设定进 Prompt）、F16 一致性审计提供数据基础。

**样板模块定位**: F9（角色管理）已沉淀「**实体 + AI 提取**」模式；F10 是 0.2.0 创作工具链**第二个**应用该模式的模块，**完全复用 F9 骨架**：

```
实体模型(domain/models) → CRUD Port(domain/ports) → Repository(infrastructure) → Service(domain/services)
        → API Router + CLI（薄层）→ AI 提取管线（LLM 模板 + 解析 + 合并落库）
```

F9 spec 已明示「F10 实施时直接对照 F9 §5 与对应文件结构，不应重新发明」。本 spec §5/§8/§12 逐处标注「同 F9 §N」，实施时对照 F9 源码替换领域实体（WorldSetting ↔ Character）与模板名（world_extract ↔ character_extract）即可，**不重新设计管线**。

**边界声明**:
- F10 只做**单次、单章节文本**的基础提取（输入一段文本 → 输出世界观条目并合并落库）。增量提取、批量/全书提取、定时提取、指代消解归 **F14 统一提取服务**（Issue #44），见 §10
- F10 不实现 F6 上下文注入（`ContextSourceProtocol` 的 `world_setting` 数据源）；实体与查询能力为其预留，集成点见 §11
- F10 是世界观**条目/设定管理**，**不是复杂知识图谱**：不做条目间关系表、不做类别层级树（决策见 §2.2/§2.3，理由详见 §12）
- **删除语义（v1.1 变更）**: 条目删除 = 确认后**真删**（物理删除，不可恢复），不再有软删/restore 语义。这是全项目「普通实体软删→真删」统一（issue #211）的一部分，与 F9/F11/F12/F13 同族（§8.2）。**例外**：F1 项目（回收站）与 F24 会话（归档）保留软删语义（§10）。

---

## 2. 数据模型

遵循 F1 Project 的「领域 Pydantic 实体 + 请求/更新 DTO + ORM 双模型」模式（ADR-004）。领域层 id 为 UUID，数据库 int 自增映射（同 F1 §12）。

### 2.1 WorldSetting（世界观条目）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，DB int 自增映射 |
| project_id | UUID | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目 |
| name | str | NOT NULL, 1-50 字符, 去空白 | 条目名（如「灵气复苏」「宗门等级体系」）；**项目内同层级唯一**（全唯一，见 §2.4） |
| parent_id | UUID? | FK→world_settings.id (CASCADE), 可空=顶层 | 父地点（F35 树形结构） |
| category | str | NOT NULL, DEFAULT "", ≤ 50 字符, 去空白 | 类别（建议值：设定/规则/约束/组织/地理/种族/文化/科技/魔法体系；自由文本，受控词表归 F14）；空串 = 未分类 |
| content | str | NOT NULL, DEFAULT "", ≤ 20000 字符 | 条目内容/详细设定 |
| extra | dict[str, Any] | NOT NULL, DEFAULT {} | 扩展字典（来源章节、标签、别名等 Phase 2+ 字段预留） |
| ~~is_deleted~~ | ~~bool~~ | ~~NOT NULL, DEFAULT False~~ | **（v1.1 移除）** 原软删除标记，真删语义下无意义 |
| created_at | datetime | NOT NULL, AUTO | 创建时间 (UTC) |
| updated_at | datetime | NOT NULL, AUTO | 更新时间 (UTC) |

**业务规则**:
- `name` 项目内**同层级（project_id, parent_id）唯一** = 「同名 = 同一世界观条目」，这是 AI 提取合并策略的锚点（§5.4），也防止手误重复建档。**（v1.1）真删语义下，全唯一索引（无 `is_deleted` 条件）；删除即物理删除，重建同名条目天然合法（旧行已不存在）**
- `category` 是**条目属性**（平铺字段），不是独立实体（决策理由见 §2.2 与 §12）
- 类别**层级树**（category 父子关系）不在 F10 范围（§10）
- 条目间**不建立外键关联**：独立 `WorldRelation` 表属 Phase 2+（决策理由见 §2.3 与 §12）

### 2.2 分类设计决策（v1.2 反转：建独立分类表）

> **v1.2 变更（2026-08-16，issue #389，用户拍板 Q1=B）**：反转 v1.0「不建独立分组表」决策——分类升级为独立受控词表实体 `WorldCategory`。触发 = GUI 世界观页需要「新建分类」CRUD + 分类数据独立于地图（#389），v1.0「类别表只有在需要类别 CRUD 时才值得」的条件已满足（Phase 2+ 演进提前落地）。

| 考量 | v1.0 结论 | v1.2 结论 |
|------|----------|----------|
| PRD 语义 | 条目的类别属性，非容器关系 | **不变**：条目 `category` 字段保留（字符串快照），分类实体是「受控词表」而非「分组容器」 |
| 独立表的价值 | 仅类别 CRUD 时才值得 | **需要**：GUI「新建分类」+ 重命名/删除 + 分类独立于地图（#389） |
| LLM 提取兼容 | 字段可随条目一并提取 | **不变**：条目 `category` 仍为自由文本快照，提取不受影响 |
| 代价 | 字段→表低成本演进 | **落地**：新增 `world_categories` 表 + CRUD；条目表不改（零存量迁移） |

**受控词表语义（D1=B1）**：`WorldCategory` 是「预置分类词表」；条目 `category` 是「字符串快照」（创建/编辑条目时自由输入，不强制外键）。前端分类 chips 来源 = 分类实体列表；分类重命名/删除反向同步条目 `category`（§6.1）。**「地图」不是世界观分类**（地图归地图工作台 #378），不进入分类实体、不渲染为 chip。

> 「层级」一词在此解读为**条目的类型维度**（规则/设定/约束等），不是数据结构上的树/继承。真正的层级树归 Phase 2+（§10）。

### 2.3 条目关联设计决策（MVP 不建 WorldRelation 表）

对标 F9 `CharacterRelation` 的「关系图谱」位置，F10 评估后**MVP 不引入 WorldRelation 表**：

| 考量 | 结论 |
|------|------|
| 需求来源 | PRD P1-02 未要求条目间关系图谱；Issue #40 仅「层级设定 + 规则约束管理 + AI 提取」 |
| 与 F9 的差异 | 角色关系（师徒/敌对）是创作**核心结构**，需双向查询；世界观条目间引用是**增强语义**，MVP 用 content 自由文本即可表达 |
| 图谱代价 | 关系表需要两端校验、级联删除、图谱查询 API——一套 F9 §2.3/§6.1 的完整机制，收益在 MVP 阶段不成比例 |
| 演进路径 | F14 统一提取/ F16 一致性审计如需要「规则→设定」溯源，再引入 WorldRelation 表（Phase 2+） |

> 结论：**倾向简单，避免过度设计**（Constitution P5 YAGNI）。`extra` 字典可临时承载轻量引用标记（不保证图谱能力，不做查询承诺）。

### 2.4 唯一约束（全唯一索引，SQLite；v1.1 变更）

**v1.0** 用 partial unique index（`WHERE is_deleted = 0`）保证「软删除后可重建同名」；**v1.1 真删语义下改为全唯一索引**：

```python
# ORM __table_args__（SQLAlchemy 2.0 + SQLite 全唯一索引；v1.1 移除 sqlite_where）
__table_args__ = (
    Index(
        "uq_world_settings_name_parent",
        "project_id", "parent_id", "name",
        unique=True,
        # v1.1: 移除 sqlite_where=text("is_deleted = 0")
    ),
)
```

**为什么是全唯一索引（v1.1）**: 「同名 = 同一世界观条目」是 AI 提取合并策略的锚点（§5.4），活动条目名必须唯一。v1.0 的 partial index 是为「软删后可重建同名」服务的；真删后记录被物理删除，重建同名条目天然合法（旧行已不存在），无需 `is_deleted` 条件。服务层再做一次同名检查以给出友好 422 文案。

> ⚠️ **跨模块同类变更**：F9 角色名/分组名/关系、F11 大纲名/弧线名、F13 伏笔标题的 partial unique 索引同步改为全唯一（§8.2 清单 C4）。

### 2.5 领域模型（Pydantic v2 语法，参照 F9 `domain/models/character.py`）

```python
def _validate_name(v: str) -> str:
    """共享的条目名校验：去空白后非空且不超过 50 字符."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("条目名不能为空")
    if len(stripped) > 50:
        raise ValueError("条目名不能超过 50 个字符")
    return stripped


def _validate_category(v: str) -> str:
    """共享的类别校验：去空白且不超过 50 字符（空串 = 未分类，允许）."""
    stripped = v.strip()
    if len(stripped) > 50:
        raise ValueError("类别不能超过 50 个字符")
    return stripped


def _validate_content(v: str) -> str:
    """共享的内容校验：不超过 20000 字符（不强制去空白，正文可能含排版空白）."""
    if len(v) > 20000:
        raise ValueError("内容不能超过 20000 个字符")
    return v


class WorldSetting(BaseModel):
    """世界观条目领域实体. 对应 world_settings 表."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None  # ← F35：父地点；None = 顶层
    category: str = ""
    content: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    # v1.1: 移除 is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class WorldCreate(BaseModel):
    """创建世界观条目请求 DTO."""
    project_id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None  # ← F35（None = 顶层）
    category: str = ""
    content: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        return _validate_category(v)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        return _validate_content(v)


class WorldUpdate(BaseModel):
    """更新世界观条目请求 DTO — 所有字段均为可选项（exclude_unset 语义，同 F1）.
    category: None 表示不修改；"" 表示清除类别（置为未分类）.
    F35 parent_id 例外：出现即更新（service 用 model_fields_set 判断）."""
    name: str | None = None
    category: str | None = None
    content: str | None = None
    parent_id: uuid.UUID | None = None  # ← F35
```

### 2.6 WorldCategory（世界观分类，v1.2 新增）

镜像 F9 `CharacterGroup`（§12）：分类是**受控词表实体**，条目 `category` 是字符串快照（D1=B1）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，DB int 自增映射 |
| project_id | UUID | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目 |
| name | str | NOT NULL, 1-50 字符, 去空白 | 分类名；**项目内唯一**（`(project_id, name)` 全唯一索引） |
| kind | str | NOT NULL, DEFAULT `"geo"`，枚举 `geo` / `abstract`（`field_validator` 校验） | 分类类型（**新增**，对齐 #699 已实现）：`geo`=地理类可挂地图 / `abstract`=抽象类不可挂地图；条目挂根语义以此为准（§16） |
| created_at | datetime | NOT NULL, AUTO | 创建时间 (UTC) |
| updated_at | datetime | NOT NULL, AUTO | 更新时间 (UTC) |

**业务规则**：
- `name` 项目内唯一 = 同名分类冲突 422「同名世界观分类已存在」
- 分类实体**不存条目计数**（count 由 `GET` 时实时聚合条目 `category` 匹配数，同 v1.0 `list_categories` 语义）
- **反向同步（D2=A，§6.1）**：重命名分类 → 同名字符串条目 `category` 改新名；删除分类 → 同名字符串条目 `category` 置空（条目变「未分类」）

```python
class WorldCategory(BaseModel):
    """世界观分类领域实体 — 对应 world_categories 表（受控词表，v1.2）。"""
    model_config = {"from_attributes": True}
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    kind: str = "geo"  # 新增（#699 已实现）：geo=地理类可挂地图 / abstract=抽象类不可挂地图
    created_at: datetime
    updated_at: datetime
```

### 2.7 提取相关模型（§5 详述）

```python
class ExtractedWorldSetting(BaseModel):
    """LLM 提取出的单个世界观条目（schema 校验用）."""
    name: str                  # 1-50 去空白；非法 → 该条跳过 + warning
    category: str | None = None   # ≤ 50 去空白；None/空串 = 未分类
    content: str | None = None    # ≤ 20000；None/空串 = 无内容


class WorldExtractRequest(BaseModel):
    """世界观信息提取请求."""
    project_id: uuid.UUID
    text: str                  # 必填, 去空白非空, ≤ 50000 字符
    model: str | None = None   # 覆盖项目默认模型（格式 provider/model_name）


class WorldExtractionResult(BaseModel):
    """世界观提取结果 — 合并落库后的报告."""
    created: list[WorldSetting]
    updated: list[WorldSetting]
    warnings: list[str]
    model: str
```

---

## 3. API 契约

端点风格沿用 F2/F9：**创建/列表/类别汇总嵌套于项目路径**，**详情/更新/删除扁平**。错误响应格式沿用 F1/F2/F9（`{"detail": "..."}` 404 / 422）。

### 3.1 端点总览（14 个；v1.1 移除 restore，DELETE 真删；v1.2 新增分类 CRUD 四端点）

| 方法 | 路径 | 用途 | 请求体/参数 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/projects/{project_id}/world-settings` | 创建条目 | `WorldCreate` | 201 + WorldSetting |
| GET | `/api/v1/projects/{project_id}/world-settings` | 条目列表 | Query: `?search=&category=&parent_id=&sort_by=&sort_desc=&offset=&limit=` | 200 + `{items, total, offset, limit}` |
| GET | `/api/v1/projects/{project_id}/world-settings/categories` | 类别汇总（含条目数） | — | 200 + `{items, total}` |
| POST | `/api/v1/projects/{project_id}/world-categories` | 创建分类（v1.2） | `WorldCategoryCreate` | 201 + WorldCategory |
| GET | `/api/v1/projects/{project_id}/world-categories` | 分类列表（含条目数）（v1.2） | — | 200 + `{items, total}` |
| PATCH | `/api/v1/world-categories/{category_id}` | 重命名分类（v1.2，反向同步条目） | `WorldCategoryUpdate` | 200 + WorldCategory |
| DELETE | `/api/v1/world-categories/{category_id}` | 删除分类（v1.2，反向清空条目 category） | — | 204 |
| POST | `/api/v1/projects/{target_project_id}/world-settings/copy` | 跨书复制世界观（F35） | `WorldCopyRequest` | 200 + result |
| GET | `/api/v1/world-settings/{setting_id}` | 条目详情 | — | 200 + WorldSetting JSON |
| GET | `/api/v1/world-settings/{setting_id}/ancestors` | 祖先链（F35） | — | 200 + `{items, total}` |
| GET | `/api/v1/world-settings/{setting_id}/descendants` | 子树（F35） | — | 200 + `{items, total}` |
| PATCH | `/api/v1/world-settings/{setting_id}` | 更新条目 | `WorldUpdate` | 200 + WorldSetting |
| DELETE | `/api/v1/world-settings/{setting_id}` | **删除条目（真删）** | Query: `?cascade=true` / `?reparent_to=<id>` | 204 |
| POST | `/api/v1/world-settings/extract` | AI 提取世界观信息 | `WorldExtractRequest` | 200 + WorldExtractionResult |

> **v1.1 变更**：① `POST /world-settings/{id}/restore` 端点**移除**；② `DELETE` 的 `?force=true` 参数**移除**（默认即真删，无软删路径）；③ `?cascade=true`（级联真删整棵子树）与 `?reparent_to=<id>`（子改挂后真删自身）为 F35 树级删除语义，**保留**。
>
> `POST /world-settings/extract` 在 router 中注册于 `POST /world-settings/{setting_id}` 之前，避免路径歧义（同 F9 characters.py 做法）。

### 3.2 请求/响应示例 — 条目 CRUD 与删除

**创建条目**:
```http
POST /api/v1/projects/3f2e1d4a-.../world-settings
Content-Type: application/json

{ "name": "灵气复苏", "category": "设定", "content": "公元 2048 年全球灵气浓度回升，觉醒者出现。" }
```
→ 201
```json
{
  "id": "9b1c2d3e-...", "project_id": "3f2e1d4a-...", "name": "灵气复苏",
  "parent_id": null, "category": "设定", "content": "公元 2048 年全球灵气浓度回升，觉醒者出现。",
  "extra": {},
  "created_at": "2026-08-01T10:00:00Z", "updated_at": "2026-08-01T10:00:00Z"
}
```
> **v1.1 变更**：响应体移除 `is_deleted` 字段。

**同名冲突**:
```http
POST /api/v1/projects/3f2e1d4a-.../world-settings
{ "name": "灵气复苏" }
```
→ 422 `{"detail": "同名世界观条目已存在（条目名在项目内必须唯一）"}`

**删除条目（真删，v1.1）**:
```http
DELETE /api/v1/world-settings/9b1c2d3e-...            → 204（物理删除，不可恢复）
DELETE /api/v1/world-settings/9b1c2d3e-...?cascade=true → 204（级联真删整棵子树）
DELETE /api/v1/world-settings/9b1c2d3e-...?reparent_to=<id> → 204（子改挂后真删自身）
```
> **v1.1 变更**：删除后实体**不可恢复**（无 restore 端点）；再次删除同 id → 404。有子地点且未指定 cascade/reparent_to → 422「该条目包含子地点，须指定级联删除或改挂」（F35 语义，`WorldChildrenActionRequiredError`）。

### 3.3 请求/响应示例 — 类别汇总与提取

**类别汇总**（支持「层级设定」管理的只读视图）:
```http
GET /api/v1/projects/3f2e1d4a-.../world-settings/categories
```
→ 200 `{"items": [{"category": "设定", "count": 4}, ...], "total": 3}`
> 仅统计**活动条目**（真删后即全部条目）；空类别（未分类）条目不出现；按 count 降序、category 升序排列。

**AI 提取**:
```http
POST /api/v1/world-settings/extract
{ "project_id": "3f2e1d4a-...", "text": "第一章正文……" }
```
→ 200 `{"created": [...], "updated": [...], "warnings": [...], "model": "deepseek/deepseek-chat"}`

### 3.4 错误响应格式（沿用 F1/F2/F9/ADR-012）

```json
// 404 — 资源不存在
{"detail": "项目不存在"}
{"detail": "世界观条目不存在"}

// 422 — 业务校验失败 / 树级删除需指定动作
{"detail": "同名世界观条目已存在（条目名在项目内必须唯一）"}
{"detail": "该条目包含子地点，须指定级联删除或改挂"}

// 500 — LLM 提取失败
{"detail": "世界观提取失败: LLM 输出无法解析，请重试"}
{"detail": "LLM 调用失败，请稍后重试"}
```

**异常映射表**:

| 异常/场景 | 状态码 | 响应 |
|-----------|--------|------|
| 项目/条目不存在（Service 返回 None） | 404 | 见上 |
| 无效 UUID 格式 | 404 | 统一解析失败处理（同 F9 `_parse_id`） |
| 同名条目 | 422 | 服务层业务校验（`WorldNameConflictError`） |
| 有子地点未指定 cascade/reparent_to | 422 | `WorldChildrenActionRequiredError` |
| reparent 目标非法（不存在/跨项目/自身子树） | 422 | `WorldReparentTargetError` |
| Pydantic `ValidationError` | 422 | FastAPI 自动生成 |
| `WorldExtractionError` | 500 | `"世界观提取失败: LLM 输出无法解析，请重试"` |
| `LLMRequestError` | 500 | `"LLM 调用失败，请稍后重试"` |

> **v1.1 变更**：移除「恢复不存在的条目」「硬删除已软删除的条目」等软删相关错误场景（§7）。

---

## 4. CLI 命令签名

遵循 F7 §5 全局约定：`--json` 统一信封；退出码 0/1/2/130；错误码 NOT_FOUND / VALIDATION_ERROR / LLM_ERROR / DB_ERROR；删除类命令二次确认 + `--force`；`--json` + 无 `--force` 的删除 → `VALIDATION_ERROR`。`world` 组在 F10 落地时并入 F7 命令树。

### 4.1 world 组（委托 WorldService；无子组）

```bash
inkflow world create --project-id <uuid> --name <str> \
    [--category <str>] [--content <str>] [--content-file <path>] [--json]

inkflow world list --project-id <uuid> \
    [--search <str>] [--category <str>] [--parent-id <uuid|none>] \
    [--sort <name|category|updated_at|created_at>] [--sort-desc/--no-sort-desc] [--json]

inkflow world categories --project-id <uuid> [--json]   # 类别汇总

inkflow world get --id <uuid> [--json]

inkflow world update --id <uuid> \
    [--name <str>] [--category <str|"">] [--content <str>] [--content-file <path>] [--json]

inkflow world delete --id <uuid> [--force] [--cascade] [--reparent-to <uuid>] [--json]
# v1.1: 移除 [--permanent]（无软删/硬删之分，默认真删）；[--force] 仅作二次确认跳过

# v1.1: 移除 inkflow world restore --id <uuid>

inkflow world extract --project-id <uuid> \
    --text <str> | --text-file <path> [--model <str>] [--json]
```

> **v1.1 变更**：① 移除 `world restore` 子命令；② `world delete` 移除 `--permanent`（真删无软删/硬删之分）；`--force` 保留为「跳过交互确认」语义（沿用 F7 §7 删除确认约定）；`--cascade` / `--reparent-to` 保留（F35 树级删除）。

### 4.2 输出格式

```bash
# 默认人类可读
✅ 世界观条目创建成功: [灵气复苏] (设定)
✅ 条目已删除: [灵气复苏]
✅ 提取完成: 新增 3 个条目, 更新 1 个条目, 跳过 2 条, 警告 2 条

# --json 输出
inkflow world delete --id ... --json
→ {"ok": true, "data": null}   # 删除成功（真删，无返回体）

inkflow world get --id 00000000-0000-0000-0000-000000000000 --json
→ {"ok": false, "error": {"code": "NOT_FOUND", "message": "世界观条目不存在"}}   # 退出码 1
```

**`--text-file` 设计理由**（同 F9 §4.3）: 章节文本可达数千字，作为命令行参数在 Windows 下受 8191 字符限制；`--text` 与 `--text-file` 互斥（同时传入 → 退出码 2）。

---

## 5. AI 提取模式（样板核心，同 F9 §5）

> ⚠️ **本节与 F9 §5 一一对应，是 F9 骨架的直接复用**：提取管线（模板渲染 → LLM → JSON 解析 → 修复式重试 → 合并落库）的实现对照 F9 `_character_extractor.py`，仅替换领域实体与模板名。

### 5.1 模式总览（同 F9 §5.1 骨架，无 relations 步骤）

```
 ┌────────────────────────────────────────────────────────────┐
 │ 输入: WorldExtractRequest {project_id, text, model?}        │
 └──────────────────────────┬─────────────────────────────────┘
                            ▼
 ① 校验项目存在（F1 ProjectRepository）→ 404
 ② 渲染 world_extract.yaml（F5 PromptManager，变量: text）
 ③ LLMClient.chat(model or project.config.model, temperature=0.2)
 ④ 解析 JSON → Pydantic schema 校验（ExtractedWorldSetting）
    ├─ 失败 → 修复式重试（附错误信息）≤ 2 次 → 仍失败 → WorldExtractionError
 ⑤ 合并落库（单 DB session 事务）:
    └─ 条目: 按 (project_id, name) 匹配活动条目 → 存在=更新(非空覆盖) / 不存在=创建
 ⑥ 返回 WorldExtractionResult（created/updated/warnings + 实际模型）
```

### 5.2 LLM 模板（`world_extract.yaml`）

```yaml
name: world_extract
description: 从章节文本提取世界观信息条目（结构化 JSON 输出）
system_prompt: |
  你是小说世界观信息提取器。从给定的章节文本中提取明确出现或明确暗示的世界观信息条目，
  包括世界设定、规则、约束、组织、地理、种族、文化、科技、魔法体系等。
  只提取文本中直接出现的或明确暗示的信息，不要臆造。
  输出严格 JSON，不要输出任何其他文字，格式如下：
  {
    "world_settings": [
      {"name": "条目名", "category": "类别或空", "content": "内容描述或空"}
    ]
  }
  category 从以下建议值中选择最合适的：设定、规则、约束、组织、地理、种族、文化、科技、
  魔法体系；无法判断时留空。world_settings 中不要包含重复的条目名。
human_prompt: |
  章节文本：
  {text}
variables:
  - text
```

### 5.3 解析与重试（同 F9 §5.3）

| 场景 | 行为 |
|------|------|
| 输出为合法 JSON 且通过 schema 校验 | 进入合并 |
| 输出含代码块围栏/前后缀文字 | 提取首个 `{...}` 平衡片段（`_extract_json_fragment`），再解析 |
| 仍失败 | 构建修复 Prompt 重试 ≤ 2 次 |
| 3 次均失败 | `WorldExtractionError` |

### 5.4 合并策略（同名条目规则，v1.1 变更）

**条目合并（按项目内活动条目 name 精确匹配）**:

| 情况 | 行为 | 计入 |
|------|------|------|
| 项目内存在同名条目 | 非空提取字段**覆盖**对应字段（category/content 独立判断），更新 updated_at | `updated` |
| 不存在 | 创建新条目 | `created` |
| 提取字段非法（name 空/超长、category/content 超长） | 该条**跳过** | `warnings` |

> **v1.1 变更**：移除「存在但已软删除 → 视为不存在 → 新建 + warning『存在已删除的同名条目档案』」分支——真删语义下不存在软删记录，`_has_soft_deleted_same_name` 辅助方法移除（§8）。

**幂等性**: 对同一文本重复提取，第二次应产出空 `created`/`updated` 列表——这是合并策略正确性的关键验收点（同 F9）。

### 5.5 提取输入约束（同 F9 §5.5）

| 约束 | 值 | 说明 |
|------|-----|------|
| text | 去空白非空，≤ 50000 字符 | 空 → 422「章节文本不能为空」 |
| 默认模型 | `project.config.model` | F1 项目配置 |
| temperature | 固定 0.2 | 结构化输出低温稳定 |

---

## 6. 分类与查询规则

（对应 F9 §6「关系图谱与分组管理规则」的位置；F10 无图谱/分组，本节承载分类语义与查询规则）

### 6.1 分类语义（v1.2 更新：受控词表落地）

- `category` 是条目的**平铺属性**（一对一），字符串快照；`WorldCategory` 是**受控词表实体**（§2.2/§2.6，v1.2 反转）
- **建议值清单**（设定/规则/约束/组织/地理/种族/文化/科技/魔法体系）仅用于 LLM 模板引导与 CLI/UI 提示，**不做枚举校验**——条目 `category` 仍为自由文本，不强制外键（D1=B1）
- **空类别 = 未分类**，允许；`GET /world-settings/categories` 与 `GET /world-categories` 均不包含未分类条目
- **反向同步（D2=A）**：分类重命名 → 同名字符串条目 `category` 改新名；分类删除 → 同名字符串条目 `category` 置空。条目 `category` 与分类实体名保持一致（在实体存在时）
- **「地图」非世界观分类**：地图归地图工作台（#378），分类实体不建「地图」，前端 chips 不渲染「地图」
- 类别**层级树**不在 F10 范围（§10）
- 规则/约束类条目在 F6 上下文注入中的优先级排序归 F6 集成（§11）

### 6.2 搜索与排序（条目列表，沿用 F1 §6/F9 §6.3）

| 参数 | 默认值 | 约束 | 说明 |
|------|--------|------|------|
| `search` | — | — | 对 name 不区分大小写子串匹配（icontains） |
| `category` | — | 1-50 字符 | 类别**精确**过滤；`category=` 空串查询未分类条目 |
| `parent_id` | — | uuid / `none` | F35：`none` = 顶层；`<uuid>` = 直接子级；缺省 = 全量 |
| `sort_by` | `updated_at` | `name`/`category`/`updated_at`/`created_at` | 排序字段 |
| `sort_desc` | `true` | — | 降序 |
| `offset`/`limit` | 0/50 | offset ≥ 0, limit [1, 100] | 分页 |

> **v1.1 措辞**：真删语义下「活动条目」= 全部条目（无软删记录）；仓储查询不再带 `~is_deleted` 过滤（§8）。

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 创建条目名为空/全空白 | 422: "条目名不能为空" |
| 创建条目名 > 50 字符 | 422: "条目名不能超过 50 个字符" |
| 创建条目名与项目内同层级条目重复 | 422: "同名世界观条目已存在（条目名在项目内必须唯一）" |
| 创建条目时项目无根世界（非根条目带 parent_id） | 422: "请先创建根世界观后再创建条目"（`WorldRootMissingError`，#834 前置校验） |
| 创建根条目但项目已有根（parent_id=None + 已存在根） | 422: "根世界观已存在，无法重复创建根"（`WorldRootConflictError`，#567/#834 根单例） |
| 创建带 category 条目但分类未先建 | 422: "请先创建分类「<分类名>」后再创建条目"（`WorldCategoryMissingError`，#834 前置校验） |
| 删除后**再创建同名条目** | ✅ 成功（全唯一索引仅约束现存行；旧行已物理删除） |
| category > 50 字符 | 422: "类别不能超过 50 个字符" |
| content > 20000 字符 | 422: "内容不能超过 20000 个字符" |
| 更新条目把非根条目置顶（parent_id→null + 项目已有根） | 422: "根世界观已存在，无法重复创建根"（`WorldRootConflictError`，#847 更新守卫） |
| 更新条目把唯一根改挂他父 | 422: "请先创建根世界观后再创建条目"（`WorldRootMissingError`，#847 更新守卫） |
| 复制到已有根的目标项目（#1493 收敛） | **子树的顶节点改挂目标根下**（不再跳过——`#1491` 后目标恒有根，原「顶层一律跳过」会让跨项目复制恒 0 条）；仅**源项目自身的根**仍跳过 + warning（不制造第二根，#848 意图保留） |
| 复制带 category 条目到无该分类的目标 | 跳过 + warning（不落未建分类，#848 复制守卫） |
| 并发双建根（DB 层兜底） | 仅一个成功——`(project_id) WHERE parent_id IS NULL` 部分唯一索引拒绝第二个（#849） |
| 获取/更新/删除不存在的条目 | 404: "世界观条目不存在" |
| 删除有子地点的条目（未指定 cascade/reparent_to） | 422: "该条目包含子地点，须指定级联删除或改挂"（`WorldChildrenActionRequiredError`） |
| 级联真删（`?cascade=true`） | 整棵子树物理删除（含子地点），不可恢复 |
| 改挂真删（`?reparent_to=<id>`） | 直接子改挂新父 + 自身物理删除；目标非法 → 422 `WorldReparentTargetError` |
| 条目不存在 / 无效 UUID 格式 | 404: "世界观条目不存在"（统一 `_parse_id` 处理） |
| 提取 text 为空/全空白 | 422: "章节文本不能为空" |
| 提取 text > 50000 字符 | 422: "章节文本不能超过 50000 个字符" |
| 提取时项目不存在 | 404: "项目不存在" |
| LLM 返回非 JSON / 无法解析 | 修复重试 ≤ 2 → 仍失败 → 500 |
| LLM 返回空条目列表 | 200 + 空 created/updated + warning "未提取到世界观信息" |
| LLM 输出中个别条目非法（空名等） | 该条跳过 + warning，不影响其他条目落库 |
| 提取时 LLM 调用失败 | 500: "LLM 调用失败，请稍后重试" |
| 合并中途 DB 错误 | 整体回滚（单事务），无部分落库 |
| 条目列表搜索/类别过滤无结果 | 200: `{"items": [], "total": 0}` |
| 分页越界 | 200: 空 items（同 F1） |
| 类别汇总无条目 | 200: `{"items": [], "total": 0}` |
| 创建分类名为空/全空白（v1.2） | 422: "分类名不能为空" |
| 创建分类名 > 50 字符（v1.2） | 422: "分类名不能超过 50 个字符" |
| 创建/重命名分类与项目内同名分类重复（v1.2） | 422: "同名世界观分类已存在" |
| 重命名分类成功（v1.2） | 同名字符串条目 category 改新名 + 200 WorldCategory |
| 删除分类成功（v1.2） | 同名字符串条目 category 置空 + 204（D2=A） |
| 获取/重命名/删除不存在的分类（v1.2） | 404: "世界观分类不存在" |
| 项目删除 | 分类级联物理删除（FK CASCADE）+ 条目级联物理删除 |
| `--text` 与 `--text-file` 同时传入 | CLI 退出码 2 |
| 提取合并幂等性 | 同文本二次提取 → created/updated 为空 |

> **v1.1 变更**：移除「软删除后**再创建同名条目**（partial unique 排除）」「硬删除已软删除的条目」「恢复不存在的条目」「恢复未删除的条目」等软删相关条目；删除语义统一为「真删 + 不可恢复」。

---

## 8. 文件结构

遵循 ADR-007v2 包结构。**v1.1 变更面 = F10 本体 MODIFY（§8）+ 跨模块 MODIFY（§8.2）+ 数据库迁移（§8.3）**。F10 本体文件结构（对照 v1.0 §8 逐文件标注变更）：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── world.py             ← MODIFY: WorldSetting 移除 is_deleted 字段（§2.5）
│   │   └── __init__.py          （不变）
│   ├── ports/
│   │   ├── world_repository.py  ← MODIFY: 移除 soft_delete / restore 方法（§8.1）
│   │   ├── world_errors.py      （不变）
│   │   └── __init__.py          （不变）
│   └── services/
│       ├── world_service.py     ← MODIFY: delete_setting 移除 force 软删路径；restore_setting 移除
│       ├── _world_extractor.py  ← MODIFY: 移除 _has_soft_deleted_same_name + 软删同名分支
│       └── __init__.py          （不变）
├── infrastructure/
│   ├── llm/templates/
│   │   └── world_extract.yaml   （不变）
│   └── database/
│       ├── models/
│       │   ├── world.py         ← MODIFY: WorldSettingORM 移除 is_deleted 列；partial unique → 全唯一（§2.4）
│       │   └── __init__.py      （不变）
│       └── repositories/
│           ├── world_repo.py    ← MODIFY: 移除 soft_delete / restore；get/get_by_name/list 移除 ~is_deleted 过滤
│           └── __init__.py      （不变）
├── api/
│   ├── routers/
│   │   ├── world_settings.py    ← MODIFY: 移除 restore 端点；DELETE 移除 force 参数
│   │   └── __init__.py          （不变）
│   ├── deps.py                  （不变）
│   └── app.py                   （不变）
└── cli/
    ├── commands/
    │   ├── world.py             ← MODIFY: 移除 restore 子命令；delete 移除 --permanent
    │   └── __init__.py          （不变）
    └── app.py                   （不变）

backend/src/inkflow/core/
└── database.py                  ← MODIFY: 新增 ensure_world_drop_is_deleted 迁移函数（§8.3）

backend/tests/
├── unit/
│   ├── test_world_models.py     ← MODIFY: 移除 is_deleted 断言
│   ├── test_world_repo.py       ← MODIFY: 软删/恢复/partial unique 用例改写为真删/全唯一
│   ├── test_world_service.py    ← MODIFY: 软删/恢复用例改写
│   ├── test_world_extraction.py ← MODIFY: 软删同名分支用例移除
│   └── test_world_api.py        ← MODIFY: restore 端点用例移除；DELETE 真删断言
└── test_cli_world.py            ← MODIFY: restore 命令用例移除
```

### 8.1 WorldRepositoryProtocol（v1.1 移除软删方法）

```python
class WorldRepositoryProtocol(Protocol):
    """世界观条目仓储端口.
    按 spec §2.4: 项目内同层级条目 name 唯一（全唯一索引，v1.1）。
    v1.1 真删语义：无 soft_delete / restore 方法。
    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9）。"""

    # ── WorldSetting ──
    async def add(self, setting: WorldSetting) -> WorldSetting: ...
    async def get(self, setting_id: int) -> WorldSetting | None: ...
    async def get_by_name(self, project_id: int, name: str) -> WorldSetting | None: ...
    async def list(self, project_id: int, search: str | None = None,
                   category: str | None = None, sort_by: str = "updated_at",
                   sort_desc: bool = True, offset: int = 0,
                   limit: int = 50) -> tuple[builtins.list[WorldSetting], int]: ...
    async def list_categories(self, project_id: int) -> builtins.list[tuple[str, int]]: ...
    async def update(self, setting: WorldSetting) -> WorldSetting: ...
    async def hard_delete(self, setting_id: int) -> bool: ...
    async def hard_delete_many(self, setting_ids: builtins.list[int]) -> int: ...
    async def delete_with_reparent(self, setting_id: int, reparent_to: int) -> bool: ...
    # v1.1 移除: soft_delete / restore
```

> 仓储层方法入参用 int（与 F9 一致）；Service 负责 UUID ↔ int 转换。`hard_delete` / `hard_delete_many` / `delete_with_reparent` 为 F35 树级删除语义（保留）。

### 8.2 跨模块 MODIFY 清单（全量，v1.1 变更核心）

删除语义统一涉及 **F9/F11/F12/F13 同族真删 + F14 提取适配 + F15 审计适配**。总览：

| 维度 | F9 角色 | F10 世界观 | F11 大纲 | F12 时间线 | F13 伏笔 | F14 提取 | F15 审计 |
|------|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| is_deleted 列移除 | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| partial unique → 全唯一 | ✅×3 | ✅×1 | ✅×2 | ❌（无 unique） | ✅×1 | — | — |
| restore 端点/命令/方法移除 | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| DELETE force 参数移除 | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| 提取软删同名分支移除 | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| 软删集合查询/引用检查移除 | — | — | — | — | — | — | ✅ |

**F9 角色（character）**:
```text
domain/models/character.py                ← MODIFY: Character/CharacterGroup/CharacterRelation 移除 is_deleted
domain/ports/character_repository.py      ← MODIFY: 移除 soft_delete/restore/soft_delete_group/
                                              soft_delete_relations_of/restore_relations_of 等方法
infrastructure/database/models/character.py ← MODIFY: 3 个 partial unique → 全唯一；移除 is_deleted 列
infrastructure/database/repositories/character_repo.py ← MODIFY: 移除软删方法；查询移除 ~is_deleted
domain/services/character_service.py      ← MODIFY: delete_character/delete_group 移除 force（默认真删，关系 FK CASCADE）；
                                              restore_character 移除
domain/services/_character_extractor.py   ← MODIFY: 移除 _has_soft_deleted_same_name + 软删同名分支
api/routers/characters.py                 ← MODIFY: 移除 /restore 端点；DELETE 移除 force
cli/commands/character.py                 ← MODIFY: 移除 restore 子命令；delete 移除 --permanent
```

**F11 大纲（outline）**:
```text
domain/models/outline.py                  ← MODIFY: Outline/PlotPoint/StoryArc 移除 is_deleted
domain/ports/outline_repository.py        ← MODIFY: 移除 soft_delete/restore/soft_delete_points_of/
                                              restore_points_of 等方法
infrastructure/database/models/outline.py ← MODIFY: 2 个 partial unique → 全唯一；移除 is_deleted 列
infrastructure/database/repositories/outline_repo.py ← MODIFY: 移除软删方法；查询移除 ~is_deleted
domain/services/outline_service.py        ← MODIFY: delete_outline/delete_point/delete_arc 移除 force；
                                              restore_outline/restore_point/restore_arc 移除
domain/services/_outline_generator.py     ← MODIFY: 移除软删同名分支
api/routers/outlines.py                   ← MODIFY: 移除 3 个 /restore 端点；DELETE 移除 force
cli/commands/outline.py                   ← MODIFY: 移除 restore 子命令；delete 移除 --permanent
```

**F12 时间线（timeline）**:
```text
domain/models/timeline.py                 ← MODIFY: TimelineEvent 移除 is_deleted
domain/ports/timeline_repository.py       ← MODIFY: 移除 soft_delete/restore
infrastructure/database/models/timeline.py ← MODIFY: 移除 is_deleted 列（无 partial unique，§2.4 注）
infrastructure/database/repositories/timeline_repo.py ← MODIFY: 移除 soft_delete/restore；查询移除 ~is_deleted
domain/services/timeline_service.py       ← MODIFY: soft_delete_event/hard_delete_event → delete_event（真删）；
                                              restore_event 移除
domain/services/_timeline_extractor.py    ← MODIFY: 移除 _has_soft_deleted_same_title + 软删同名分支
api/routers/timeline.py                   ← MODIFY: 移除 /restore 端点；DELETE 移除 force
cli/commands/timeline.py                  ← MODIFY: 移除 restore 子命令；delete 移除 --permanent
```

**F13 伏笔（foreshadowing）**:
```text
domain/models/foreshadowing.py            ← MODIFY: Foreshadowing 移除 is_deleted
domain/ports/foreshadowing_repository.py  ← MODIFY: 移除 soft_delete/restore
infrastructure/database/models/foreshadowing.py ← MODIFY: partial unique → 全唯一；移除 is_deleted 列
infrastructure/database/repositories/foreshadowing_repo.py ← MODIFY: 移除 soft_delete/restore；查询移除 ~is_deleted
domain/services/foreshadowing_service.py  ← MODIFY: soft_delete/hard_delete → delete（真删）；restore 移除
domain/services/_foreshadowing_extractor.py ← MODIFY: 移除 _has_soft_deleted_same_title + 软删同名分支
api/routers/foreshadowings.py             ← MODIFY: 移除 /restore 端点；DELETE 移除 force
cli/commands/foreshadowing.py             ← MODIFY: 移除 restore 子命令；delete 移除 --permanent
```

**F14 提取（extraction）**: 各提取器的软删同名分支已并入各模块清单（_world/_character/_timeline/_foreshadowing/_outline 五处）；F14 提取服务本体（`extraction_service.py`）无软删实体、无独立变更（仅「F2 get 不含软删」注释措辞随 F2 语义不变而保留）。

**F15 审计（audit）**:
```text
domain/ports/audit_repository.py          ← MODIFY: AuditRepositoryProtocol 移除 list_deleted
infrastructure/database/repositories/audit_repo.py ← DELETE: 整文件移除（唯一职责 = 软删集合查询，真删后无意义）
domain/services/audit_service.py          ← MODIFY: 移除 list_deleted 调用 + _deleted_set；
                                              R-C1/R-C2/R-F1 软删 warning 分支移除，悬空（活动∪软删集合都不存在）→ error；
                                              软删集合参数从 _audit_character/_audit_foreshadowing 签名移除
domain/models/audit.py                    ← MODIFY: AuditSeverity.WARNING 移除「软删引用」语义（保留 run.status=error 等）
```

> ⚠️ **不纳入本次变更（明确排除）**：F1 项目（`project.py`/`project_repo.py`/`project_service.py`/`project` CLI 的 soft_delete/restore 保留，回收站模式）、F24 会话（`session.py` 系归档语义保留）、F16 风格（无软删实体）、F35/36/37 地图（已真删）。

### 8.3 数据库迁移（is_deleted 列移除 + 存量软删数据清理）

项目无 alembic，`create_all` 管理 schema + 幂等迁移函数（参照 `ensure_provider_builtin_key_column` / `ensure_world_parent_id_column` 先例，`core/database.py`）。v1.1 新增迁移函数，覆盖 **5 张表**（world_settings / characters+character_groups+character_relations / outlines+plot_points+story_arcs / timeline_events / foreshadowings）：

**迁移步骤（每张表，幂等）**:
1. **清理存量软删数据**：`DELETE FROM <表> WHERE is_deleted = 1`（Q3=A 拍板：存量软删记录物理删除，真删语义下本不该存在）
2. **DROP 依赖 is_deleted 的索引**：partial unique 索引（`sqlite_where="is_deleted = 0"`）+ is_deleted 的 `ix_*` 单列索引
3. **重建全唯一索引**：`CREATE UNIQUE INDEX ... ON <表>(...)`（无 `WHERE is_deleted = 0`）——partial unique → 全唯一（§2.4）
4. **DROP is_deleted 列**：`ALTER TABLE <表> DROP COLUMN is_deleted`（SQLite 3.35+ 支持；必须先 DROP 引用该列的索引，否则报错）

> ⚠️ **顺序约束（load-bearing）**：SQLite `DROP COLUMN` 不能删除「被索引/部分索引 WHERE 子句引用」的列，故步骤顺序必须是 ① 清数据 → ② 删索引 → ③ 建新索引 → ④ 删列。表不存在（全新环境）→ no-op，等 `create_all` 建新表（自动无 is_deleted 列 + 全唯一索引）。

**迁移函数签名（plan 阶段展开实现）**:
```python
def ensure_world_drop_is_deleted(conn) -> None: ...      # world_settings
def ensure_character_drop_is_deleted(conn) -> None: ... # characters/character_groups/character_relations
def ensure_outline_drop_is_deleted(conn) -> None: ...   # outlines/plot_points/story_arcs
def ensure_timeline_drop_is_deleted(conn) -> None: ...  # timeline_events
def ensure_foreshadowing_drop_is_deleted(conn) -> None: ... # foreshadowings
```

这些函数在应用启动（`create_tables` 后）与 CLI `ensure_kernel` 路径按序调用，幂等、可重复执行。

**角色分组 N:M 迁移（#701 + #831）**：`ensure_character_group_members_migration` 为旧库引入
`character_group_members` 关联表（角色/分组 N:M），并**移除旧 schema `characters.group_id` 单列**。
该列被 `FOREIGN KEY(group_id) REFERENCES character_groups(id) ON DELETE SET NULL` 引用，SQLite
`ALTER TABLE ... DROP COLUMN` **禁止删除被 FK 引用的列**，且 FK 不存于 `sqlite_master` 索引记录，
故必须在移除前**重建 characters 表**（新表无 group_id 列 + 无引用该列的 FK，拷贝其余列数据、
DROP 旧表、RENAME、重建 `uq_characters_active_name` 等索引）。

> ⚠️ **FK=ON 主事务内不可安全重建（#831）**：app lifespan 主迁移链在 `engine.begin()`（FK=ON）
> 事务内运行——`PRAGMA foreign_keys=OFF` 在同一事务内是 no-op，且主事务 DDL 已持写锁；此时
> `DROP TABLE characters` 会沿 FK CASCADE 清空 `character_relations` 与回填后的
> `character_group_members`（数据丢失）。故本迁移由 `run_character_group_members_migration`
> 在**独立 AUTOCOMMIT 连接 + FK=OFF** 上执行（主迁移事务提交后调用），规避 FK 拒止与级联清空。
>
> **#495 备注（2026-09-17）**：`character_relations` 表此后已被并入 `knowledge_relations`（新增幂等迁移
> `ensure_character_relations_merged_into_knowledge`，链上顺序在本段 helper **之后**）；本段为**旧库升级
> 路径**的历史语境——新库/已迁移库该表不存在，helper 的 `character_relations` 分支持续 no-op。

### 8.4 #1481 建项目自动建根 + 存量兜底（跨模块 MODIFY 清单）

**默认根条目形态**（f10 侧定义；根规则与树语义见 f35 §2.1 规则 7 / §5.7）：

| 字段 | 值 | 说明 |
|------|-----|------|
| `name` | `"世界观总纲"`（常量 `DEFAULT_WORLD_ROOT_NAME`，`domain/models/world.py`） | 条目名同级唯一 ⇒ 项目内顶层不再允许同名条目 |
| `parent_id` | `NULL` | 根（顶层），受 `uq_world_settings_root_per_project` 部分唯一索引兜底 |
| `category` | `""` | **根无分类**（#722 语义）⇒ 不触发 #834/#1321 分类前置校验 |
| `content` | `""` | 空内容（用户后续自行填写） |
| `extra` | `{}` | 无扩展属性 |

**跨模块 MODIFY 清单**：

```text
domain/models/world.py                    ← MODIFY: 新增常量 DEFAULT_WORLD_ROOT_NAME = "世界观总纲"
domain/services/world_service.py          ← MODIFY: 新增 ensure_root_setting(project_id)（幂等：有根返回既有根，
                                              无根以空分类建默认根；复用 create_setting 校验链与 data_change 事件）
domain/services/project_service.py        ← MODIFY: create_project 新增 root_initializer 钩子参数
                                              （Callable[[uuid.UUID], Awaitable[Any]] | None，镜像 map_cleanup），
                                              项目落库后调用——唯一项目创建入口，覆盖 API/CLI/agent 全部调用方
api/deps.py                               ← MODIFY: get_project_service 注入 root_initializer
                                              （延迟构造 WorldService，避免非创建端点承担构造开销）
core/migrations_world_root.py             ← CREATE: ensure_world_root_for_projects(conn)（幂等补根迁移；
                                              database.py 900 行护栏 → 拆模块 + re-export 进 __all__）
core/database.py                          ← MODIFY: re-export ensure_world_root_for_projects（+ __all__ 登记）
api/app.py                                ← MODIFY: lifespan 接线（ensure_world_root_unique_index 之后、
                                              ensure_entity_uuid_columns 之前）
```

⚠️ **不动**：`api/routers/world_settings.py` 的 #641 懒创建分支（无 `parent_id` → 有根挂根 / 无根建根）保持不变
——它是旧库与异常路径的兜底，且「无根建根」在「根必存在」后自然不可达（防御性保留）。

---

## 9. 测试策略

### 测试层次（沿用 ADR-018 三层目录 + pytest markers）

```text
单元测试: 领域模型/DTO 验证 + 提取 DTO schema
集成测试: SQLiteWorldRepository（in-memory SQLite，含全唯一索引）
服务测试: WorldService（Mock Repository）
提取测试: 提取管线（Mock LLM，全合并分支）
API 测试: 10 端点（Mock Service）
CLI 测试: world 组（Mock WorldService）
```

### 关键测试场景（v1.1 改写点）

**领域模型**: WorldSetting 无 is_deleted 字段（构造不接受、序列化不含）；其余 name/category/content 校验、WorldUpdate 部分更新、提取 DTO schema 不变

**仓储（真删/全唯一）**: 条目 CRUD 往返 / `get_by_name` 命中与未命中 / 同层级同名唯一（全唯一索引：插入第二个同名 → IntegrityError）/ **删除后重建同名 → 成功**（物理删除后唯一约束不拦）/ `hard_delete` 物理删除（删除后 get 返回 None）/ `list` 搜索与 category 过滤 / `list_categories` 聚合 / 分页 / FK 级联

**服务（真删）**: 创建/更新/删除全流程 / 同名条目 → 422 / 条目不存在 → 404 / delete_setting 无子地点真删、有子地点未指定动作 → 422、cascade 真删子树、reparent 改挂 / extract 入口编排

**提取（Mock LLM）**: 合法 JSON 落库 / 同名更新 + 幂等 / 非法条目跳过 + warning / 围栏提取 / 完全非法重试 → WorldExtractionError / LLMRequestError 透传 / 空列表 warning / Prompt 断言。**v1.1 移除**「软删同名 → 新建 + warning」用例

**API（Mock Service）**: 10 端点成功路径 / 404 全路径 / 422 业务校验 / extract 200 / LLM 失败 500 / categories 汇总 / 无效 UUID 404。**v1.1 移除** restore 端点用例；DELETE 断言真删（无 force）

**CLI**: 各子命令成功路径与透传 / 信封与退出码 / delete 二次确认 + `--force` / `--json` + delete 无 `--force` → VALIDATION_ERROR / `--text` 与 `--text-file` 互斥 / extract 摘要与 `--json`。**v1.1 移除** restore 子命令用例

### 跨模块测试改写面（§8.2 对应）

| 测试文件 | 改写内容 |
|---------|---------|
| test_character_{models,repo,service,extraction,api}.py / test_cli_character.py | 软删/恢复用例 → 真删；partial unique → 全唯一；提取软删同名分支移除 |
| test_outline_{models,repo,service,generation,api}.py / test_cli_outline.py | 同上（大纲/情节点/弧线三实体） |
| test_timeline_{models,repo,service,extractor,check,api}.py / test_cli_timeline.py | soft_delete_event/restore_event → delete_event |
| test_foreshadowing_{models,repo,service,extractor,api}.py / test_cli_foreshadowing.py | soft_delete/restore → delete |
| test_world_*.py / test_cli_world.py | 见上（F10 本体） |
| test_audit_{models,repo,service}.py | 软删集合/软删引用 warning 用例 → 悬空 error |
| test_map_*.py / test_session_*.py / test_project_*.py | **不改**（F35 已真删 / F24 归档 / F1 回收站保留） |

### 覆盖率目标（ADR-027）

- 变更模块行覆盖率 **≥ 98.5%**，分支覆盖率 **≥ 95.0%**（ADR-027 门禁）
- CI 门禁：ruff + mypy + pytest 全绿；单测试文件 ≤ 900 行护栏

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|----------|
| **F1 项目软删（回收站模式）** | **保留不改**（v1.1 明确排除）——项目是顶层容器，回收站防误操作是 PRD v2.1 明确设计，与「普通实体」本质不同 |
| **F24 会话归档语义** | **保留不改**（v1.1 明确排除）——会话是唯一保留「归档」语义的实体（可直删/可归档/归档可取消归档/归档可直删），拍板明确 |
| F16 风格软删 | 无软删实体（文本分析型模块），无变更 |
| 增量提取 / 批量章节提取 / 全书扫描 | F14 统一提取服务 |
| 指代消解 | F14 |
| 提取预览（dry-run） | F14 或 0.2.x 增强 |
| 受控类别词表 | F14 |
| 条目间关系/引用图谱（WorldRelation 表） | Phase 2+ |
| 类别层级树 | Phase 2+ |
| 规则/约束冲突检测 | F16 一致性审计 |
| F6 `world_setting` 数据源真实实现 | 集成点 |
| 世界观版本历史 / 变更审计日志 | F15 审计服务 |
| 条目内容全文检索 | F22 搜索服务 |
| 跨项目世界观共享/引用/合并 | Phase 4 云端 |
| 世界观可视化 / 导出 | F18 Web UI / F21 导出服务 |

---

## 11. 依赖关系

```text
F10 依赖:
  F1 (project_service) ✅ — 项目存在性校验；project.config.model 默认模型
  F5 (llm_service)     ✅ — LLMClientProtocol + PromptTemplateProtocol
  F2 (chapter_service) — 可选（extract --text-file 不做 F2 校验）

F10 被依赖（v1.1 删除语义变更的下游）:
  F6 (context_service) ✅ — world_setting 数据源
  F7 (CLI)             ✅ — world 命令组
  F9/F11/F12/F13       ✅ — 同族真删统一（§8.2 联动）
  F14 (统一提取)        ✅ — 提取合并的软删同名分支随 F10/F9/F11/F12/F13 真删同步移除
  F15 (审计)            ✅ — 软删集合查询/软删引用 warning 随真删移除（§8.2）
  F20 (MCP)             ⏳ — manage_world 工具
```

> **v1.1 变更**：F14 的「软删同名 → 新建 + warning」分支依赖各模块 `is_deleted` 语义，真删后该分支移除；F15 的软删集合（`audit_repo.list_deleted`）依赖 `is_deleted=1` 数据，真删后移除，审计软删引用 warning 退化为悬空 error。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| 删除语义 | **普通实体（F9/F10/F11/F12/F13）软删 → 真删**（v1.1） | 2026-08-09 世界观三连拍板「删除语义收敛：会话唯一保留归档，其他功能删除 = 确认后真删，restore 无使用情景」；Q1=A 全族统一 |
| F1 项目回收站保留 | **不改**（v1.1） | 项目是顶层容器，删除级联海量数据，回收站防误操作是 PRD 明确设计；issue 影响面未列 F1（Q2=A） |
| F24 会话归档保留 | **不改**（v1.1） | 会话是唯一归档语义实体，拍板明确 |
| is_deleted 列处置 | **移除列 + 存量软删记录物理删除**（v1.1） | 真删语义下列无意义；保留死列留下不可见死数据；Q3=A（最彻底） |
| partial unique → 全唯一 | `(project_id, parent_id, name)` 全唯一索引（v1.1） | 真删后无软删记录，重建同名天然合法；partial 的 `WHERE is_deleted=0` 失去意义 |
| 合并策略 | 非空字段覆盖；移除「软删同名 → 新建 + warning」分支 | 真删后不存在软删档案，分支无意义 |
| 树级删除语义 | cascade/reparent 保留；force 软删路径移除 | F35 树形结构仍需要级联真删/改挂；软删/硬删切换（force）真删后无意义 |
| 分类建模 / 条目关联 / 提取重试 / 温度 / 模板 / 端点布局 | 沿用 v1.0 决策 | 删除语义变更不影响这些决策 |
| 分类建模反转（v1.2） | **条目平铺属性 → 独立受控词表实体 `WorldCategory`**（D1=B1） | #389 GUI 需「新建分类」CRUD + 分类独立于地图；反转 §2.2 v1.0「不建表」决策；条目 `category` 保留字符串快照，零存量迁移 |
| 分类反向同步（v1.2） | **重命名改名 / 删除置空**（D2=A） | 受控词表一致性：条目 `category` 与分类实体名保持同步；删除后条目变「未分类」 |
| 分类类型 kind（#699，**新增补记**） | **`WorldCategory` 增 `kind ∈ {geo, abstract}`**（默认 geo） | 区分「地理类（可挂地图）」与「抽象类（纯标签）」——地图树 kind 分流（`MapDirectoryTree.tsx` 中 abstract 分类的条目不进树）+ 地图入口门控；条目挂根语义见 §16 |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | F10 spec v1.1 合入 main（删除语义 + 跨模块 MODIFY 清单 + 影响面 7 项结论） | spec v1.1 commit 合入 |
| M2 | RED 批全 FAIL 有实证（真删语义 / partial unique 变更 / F14 合并 / F15 审计 / restore 移除契约） | 测试输出存档，批全 FAIL |
| M3 | 后端测试全绿（本地运行输出实证） | `pytest -v` 全绿 |
| M4 | 真删语义生效（DELETE 后实体不可 restore）+ restore 端点/命令/方法移除 | 定向测试 + 手工验证 |
| M5 | partial unique 语义变更正确（真删后同名重建） | 仓储测试 + 迁移函数验证 |
| M6 | F14 提取合并 / F15 审计适配（无软删排除逻辑残留） | 提取/审计测试全绿 + grep 无 `is_deleted` 残留（F1/F24 除外） |
| M7 | GUI 删除确认框对齐（真删不可恢复提示）+ restore 入口处理 | GUI 删除确认框文案对齐（GUI 本无 restore 入口，仅确认文案） |
| M8 | 覆盖率门禁（ADR-027 98.5/95.0） | coverage.xml 对照 |
| M9 | PR 合入 + CI 全绿 | statusCheckRollup 对照 |
| M10 | issue #211 关闭；worktree 清理 | issue closed |
| M11 | 分类 CRUD 四端点 RED 全 FAIL 有实证（v1.2） | 后端测试输出存档，批全 FAIL |
| M12 | 分类 CRUD 后端测试全绿（v1.2） | pytest 定向全绿 |
| M13 | 分类反向同步生效（重命名改名 / 删除置空，v1.2） | 定向测试 + 手工验证 |
| M14 | 前端导航 + 分类 chips + 地图视图按钮（v1.2） | vitest 全绿 + 三契约正确 |
| M15 | issue #389 关闭；worktree 清理（v1.2） | issue closed |
| M16 | 世界观「先建根/先建分类」后端前置校验（#834）：无根时建非根条目拒绝、根单例、带未建分类条目拒绝 | 定向测试（service 单测 + API 422 断言）全绿 |

---

## 14. 影响面评估结论（对应 issue #211 影响面 1-7）

| # | 影响面 | 评估结论 | 落地 |
|---|--------|---------|------|
| 1 | F10 world_settings | `is_deleted` 列移除；DELETE 默认软删 → 真删（force 软删路径移除）；restore 端点/方法/命令移除 | §2/§3/§4/§8 |
| 2 | partial unique 索引 | 7 个 `(…, name) WHERE is_deleted=0` partial unique → 全唯一（F9×3、F10×1、F11×2、F13×1；F12 无 unique） | §2.4/§8.2/§8.3 |
| 3 | F14 提取合并 | `get_by_name` 软删排除逻辑（`~is_deleted`）移除；同名合并锚点的「软删同名 → 新建 + warning」分支移除 | §5.4/§8.2 |
| 4 | F15 审计 | 软删引用检查规则（`audit_repo.list_deleted` 数据源）移除；R-C1/R-C2/R-F1 软删 warning → 悬空 error；audit_repo 整文件删除 | §8.2 |
| 5 | F9-F13/F16 同族 | F9/F11/F12/F13 软删 → 真删（与 F10 同族）；**F16 无软删实体，无变更** | §8.2 |
| 6 | GUI | 删除确认框已统一（`ConfirmDialog`，F43）；**GUI 本无 restore 入口**（restore 仅后端 API + CLI），仅需确认文案对齐「真删不可恢复」 | §7 |
| 7 | 测试面 | 688 处软删匹配、~45 测试文件改写（F9-F15 + world）；F1/F24/session/map 测试不动 | §9 |

> **明确排除（拍板）**：F1 项目回收站、F24 会话归档——保留软删语义，不在本次变更范围。

---

## 待澄清问题（已拍板 ✅，2026-08-13）

| # | 问题 | 拍板 | 结论 |
|---|------|------|------|
| Q1 | 统一范围：F9/F11/F12/F13 是否一并真删？ | ✅ A（全部统一） | F9/F10/F11/F12/F13 一起真删，F14/F15 连锁适配（§8.2） |
| Q2 | F1 项目是否纳入？ | ✅ A（不改 F1） | 项目保留回收站（软删 + restore），PRD 防误操作设计（§10/§12） |
| Q3 | is_deleted 列处置 + 存量软删数据 | ✅ A（移除列 + 清存量） | 移除 is_deleted 列 + 存量软删记录物理删除（§8.3） |

> **补充拍板（用户 2026-08-13）**：F24 会话归档语义确认——会话可直删 / 可归档 / 归档可取消归档 / 归档可直删，**保持不变**（§10）。

---

## 15. 动作确认

> 基于 §3 API + §4 CLI + §7 边界事实的状态流表，不新增行为。

### 15.1 端点状态流

| 端点 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| POST /api/v1/projects/{project_id}/world-settings | 项目存在 | 校验 DTO → 同名检查 → 建条目 | 201 + WorldSetting | 404「项目不存在」；422「条目名不能为空」/「条目名不能超过 50 个字符」/「同名世界观条目已存在（条目名在项目内必须唯一）」 | parent_id 可空（F35） |
| GET /api/v1/projects/{project_id}/world-settings | 项目存在 | search/category/parent_id 过滤 + 排序分页 | 200 + {items,total,offset,limit} | — | 无结果 → 空 items；?parent_id=none = 顶层（F35） |
| GET /api/v1/projects/{project_id}/world-settings/categories | 项目存在 | 类别汇总（实时聚合条目数） | 200 + {items,total} | — | 仅活动条目；空类别不出现；无条目 → 空 |
| POST /api/v1/projects/{project_id}/world-categories | 项目存在 | 同名检查 → 建分类 | 201 + WorldCategory | 422「分类名不能为空」/「分类名不能超过 50 个字符」/「同名世界观分类已存在」 | v1.2 |
| GET /api/v1/projects/{project_id}/world-categories | 项目存在 | 分类列表（含条目数） | 200 + {items,total} | — | v1.2 |
| PATCH /api/v1/world-categories/{category_id} | 分类存在 | 重命名 + 反向同步同名字符串条目 category | 200 + WorldCategory | 404「世界观分类不存在」；422「同名世界观分类已存在」 | 条目 category 改新名（v1.2） |
| DELETE /api/v1/world-categories/{category_id} | 分类存在 | 删分类 + 条目 category 置空 | 204 | 404「世界观分类不存在」 | 条目变未分类（v1.2） |
| POST /api/v1/projects/{target_project_id}/world-settings/copy | 源/目标项目存在 | 跨书复制世界观 | 200 + result | 404（源/目标项目不存在） | 语义详见 F37 §14 |
| GET /api/v1/world-settings/{setting_id} | 条目存在 | 详情 | 200 + WorldSetting | 404「世界观条目不存在」 | 无效 UUID → 404 |
| GET /api/v1/world-settings/{setting_id}/ancestors | 条目存在 | 祖先链（含自身） | 200 + {items,total} | 404「世界观条目不存在」 | 语义详见 F35 §14 |
| GET /api/v1/world-settings/{setting_id}/descendants | 条目存在 | 子树（含自身） | 200 + {items,total} | 404「世界观条目不存在」 | 语义详见 F35 §14 |
| PATCH /api/v1/world-settings/{setting_id} | 条目存在 | 部分更新（exclude_unset） | 200 + WorldSetting | 404「世界观条目不存在」；422（业务校验） | parent_id 出现即更新（F35）；category "" = 清除类别 |
| DELETE /api/v1/world-settings/{setting_id} | 条目存在 | 真删（物理删除，不可恢复） | 204 | 404「世界观条目不存在」；422「该条目包含子地点，须指定级联删除或改挂」 | ?cascade=true 真删整棵子树 / ?reparent_to=<id> 子改挂后真删自身（F35）；无软删/restore 路径 |
| POST /api/v1/world-settings/extract | 项目存在·text 非空 | LLM 提取 → 解析重试 ≤2 → 合并落库（单事务） | 200 + WorldExtractionResult | 404「项目不存在」；422「章节文本不能为空」/「章节文本不能超过 50000 个字符」；500「世界观提取失败: LLM 输出无法解析，请重试」/「LLM 调用失败，请稍后重试」 | 空列表 → warning「未提取到世界观信息」；单条非法 → 跳过 + warning；幂等 |

### 15.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| world create | 项目存在 | 建条目 | ✅ 世界观条目创建成功: [灵气复苏] (设定)；--json 信封 | 422 VALIDATION_ERROR | --content-file <path> 从 UTF-8 文件读正文（与 --content 互斥 → 退出码 2；文件缺失 → VALIDATION_ERROR 退出码 1） |
| world list | 项目存在 | 列表 | 列表 / --json | — | --search/--category/--parent-id/--sort |
| world categories | 项目存在 | 类别汇总 | JSON | — | — |
| world get | 条目存在 | 查询 | JSON | NOT_FOUND「世界观条目不存在」退出码 1 | — |
| world update | 条目存在 | 部分更新 | ✅ / JSON | 404 NOT_FOUND；422 VALIDATION_ERROR | --category "" 清除类别；--content-file <path> 从 UTF-8 文件读正文（与 --content 互斥 → 退出码 2） |
| world delete | 条目存在 | 二次确认（--force 跳过）→ 真删 | ✅ 条目已删除: [灵气复苏]；--json data null | 404 NOT_FOUND；422 VALIDATION_ERROR（有子未指定）；--json 无 --force → VALIDATION_ERROR | --cascade 真删子树 / --reparent-to 改挂；无 --permanent（默认真删） |
| world extract | 项目存在 | LLM 提取 → 合并落库 | ✅ 提取完成: 新增 3 个条目, 更新 1 个条目, 跳过 2 条, 警告 2 条；--json 报告 | 404 项目不存在；422 空文本；500 LLM_ERROR | --text/--text-file 互斥（同时 → 退出码 2） |

### 15.3 验收锚点

- A1：删除有子地点的条目且未指定 cascade/reparent_to → 422「该条目包含子地点，须指定级联删除或改挂」
- A2：真删后 GET → 404「世界观条目不存在」（不可恢复，无 restore）
- A3：创建条目 name 空 → 422「条目名不能为空」；同名 → 422「同名世界观条目已存在（条目名在项目内必须唯一）」
- A4：extract text 空 → 422「章节文本不能为空」；LLM 解析失败重试 ≤2 仍失败 → 500「世界观提取失败: LLM 输出无法解析，请重试」
- A5：重命名分类 → 同名字符串条目 category 同步改新名；删除分类 → 条目 category 置空（D2=A）
- A6：extract 合并中途 DB 错误 → 单事务整体回滚（无部分落库）

---

## 16. 分类 kind 与条目挂根语义（设计定义 · 已拍板 ①C · #1334）

> **章节定位（#1334 设计单）**：本章是**设计定义**（选项 + 推荐 + 取舍 + 迁移影响），**不含实现**。**① 已于 2026-10-02 拍板 ①C**（用户「按照推荐」）；实施另起实现轨。
>
> **与既有章节的边界**：§6.1 定义「分类作为受控词表的语义」；本章只定义「分类 `kind` 如何影响**条目创建时的父级归属**」这一条推导链。**不改** §6.1 的分类重命名/删除反向同步，**不改** §5 提取合并语义，**不改** §2.4/§8.3 的索引与迁移机制（除非拍板 ①(a)/(b) 另开迁移）。
>
> **上游基线**：#641（自动挂根）/ #699（分类 kind + 地图树隔离）/ #721（地图树 kind 分流）/ #834（一项目一根）/ #1321（非根条目必填分类）/ #1322（树污染 + 地图树显示门控）。

### 16.1 事实基线（实测，2026-10-02，worktree 基于 main @ 8429c6aa）

**「按 kind 挂根」从未实现过**（git 实证）：`61f8b5de`（#641）引入自动挂根时**无 kind 概念**（一律挂根）；`0bb0ab8b`（#699）只给**分类**加 `kind` 字段 + 地图树隔离，**条目创建的挂根分支完全未动**。用户记忆中的设计实际是 #699 的**分类层门控**（不进地图树 / 隐藏地图入口）。

| # | 现状（已实现） | 位置 |
|---|---|---|
| F1 | **自动挂根（#641）**：`POST /world-settings` body 无 `parent_id` → 取项目根；有根 → 挂根下；无根 → 建根 | `api/routers/world_settings.py:221-238`、`world_service.py:290-292` |
| F2 | **一项目一根（#834）**：`parent_int is None and has_root → WorldRootConflictError`；有父但无根 → `WorldRootMissingError` | `world_service.py:160-168` |
| F3 | **非根条目必填分类（#1321）**：`parent_int is not None and not category_stripped → WorldCategoryMissingError` | `world_service.py:189-194` |
| F4 | **带 category 条目须先建分类（#834）**：分类实体不存在 → `WorldCategoryMissingError` | `world_service.py:174-179` |
| F5 | **根单例 DB 兜底（#849）**：`uq_world_settings_root_per_project (project_id) WHERE parent_id IS NULL` | `infrastructure/database/models/world.py:54-59` |
| F6 | **分类 kind（#699）**：`kind ∈ {geo, abstract}`，默认 geo；geo=可挂地图 / abstract=不可挂地图 | `domain/models/world.py:288`、ORM `world.py:173-178`、CLI `cli/commands/world.py:228` |
| F7 | **前端 kind 分流（#721）**：`kindByCategory.get(category) !== 'abstract'` —— abstract 分类的条目不进**地图树**；**空/未知分类按 geo 处理** | `MapDirectoryTree.tsx:651-660` |

**spec 漂移登记（已实现但本 spec 此前未记，本章同步对齐）**：

- §2.6 `WorldCategory` 表 / §2.5 pydantic 原**未含 `kind` 字段** → 已补（标「新增」）。
- §3.1/§3.2 原**未记载 #641 自动挂根**行为 → 本章 F1 补齐（§3 正文不动，以本章为登记面）。
- §12 决策表原**未登记 #699 kind 决策** → 已补一行。

**🔴 关键技术约束（决定选项可行性的根因）**：`kind` 是 `world_categories` 表的列，**`world_settings` 表没有 kind 列**。⇒ 任何「按 kind 分根」的 **DB 级约束**（#849 式部分唯一索引）**无法用现有表结构表达**——必须先在条目表冗余一列 kind（或由分类 kind 派生）。此约束使选项 (a) 的 DB 兜底成本显著高于 issue 正文估计（§16.5）。

**原型证据表（不支持「按 kind 挂根」，且原型内部自相矛盾）**：

| 项 | 实测 | 结论 |
|---|---|---|
| 树根数 | `design/GUI/world/world.html` 树视图 **多根森林**：**5 个节点皆 depth-0**（L430/470/476/482/488；原型示例条目名不复述） | 原型按「多根」画，但**不能证明**「按 kind 分根」——原型无 kind 表达 |
| kind 视觉表达（①A 新 chips） | `world.html:344-376`：**仅「地理」带 🗺**；城市 / 秘境 / 势力 / 功法 / 文化 / 科技 **不带** | ❌ |
| kind 视觉表达（legacy 对照 chips） | `world.html:381-385`：地理 / 城市 / 秘境 / 势力 / 功法 **全带 🗺** | ❌ 与上一行自相矛盾 |
| kind 视觉表达（library world 面板） | `design/GUI/library/library.html:384-388`：地理🗺 / 城市🗺 / 秘境🗺 **带**；势力 / 功法 **不带** | ❌ 与 world.html 新 chips 不一致（同为 geo 的城市/秘境，一处带一处不带） |
| 树行分类徽标 | `world.html:433/440/447/454/460/466/473/479/485/491` **全部无 🗺** | 与 chips 表达不一致 |
| 新建条目对话框 | ❌ 原型无 | 对「默认挂根 / 选父」**零表达** |
| 新建分类对话框 | ❌ 原型无（states 仅 main / cat-selected / cat-registered / btn-b / plan-b / plan-c / legacy / map / copy-dialog） | geo/abstract radio 是 **spec + 实现独有**（**规格领先原型**） |

> ⚠️ **任务书勘误**：「world.html 五个 chip 全带 🗺」仅对 **legacy 对照 chips** 成立；①A 已实现形态的新 chips 只有「地理」带 🗺。三处（library 面板 / world 新 chips / world legacy）对同一 kind 语义有三种表达 ⇒ **原型不构成 kind 视觉规范，反而需要收敛**（§16.7）。

### 16.2 ① abstract 条目的父是谁？

| 选项 | 机制 | 代价 / 迁移影响 |
|---|---|---|
| **(a) 建第二个根** | 一项目两根（geo 根 + abstract 根）；`create_setting` 的 `parent_int is None` 分支从「有无根」改为「本 kind 是否已有根」 | 🔴 **推翻 #834 根单例不变量**，牵动 **#567 / #834 / #847 / #849** 四条契约；DB 兜底索引 `uq_world_settings_root_per_project` **无法用现有结构表达**（kind 在分类表 ⇒ 须先在条目表冗余 kind 列）→ 索引须改为 `(project_id, kind) WHERE parent_id IS NULL`；`update_setting` 置顶/改挂守卫（#847）按 kind 重写；**存量数据迁移**（现有项目全部条目在单一根下 → 须决定是否拆根/如何补 kind）；前端须渲染双根；**原型须重新出图** |
| **(b) 挂固定「抽象根」** | 项目仍保持唯一根（`parent_id IS NULL`）；增设一个**约定节点**（如「抽象设定」）作为 abstract 类条目的父 | 🟡 **仍需区分「谁是约定根」**（约定节点是普通条目，须防用户误删/改挂，但无「不可删」语义）；**语义上仍「挂树」**——抽象条目依旧出现在树里，**不解决「树污染」诉求**（除非叠加 (c) 的树侧过滤）；后端改动中等（约定节点创建/查找/保护）+ 存量迁移 |
| **(c) 不挂树**（✅ **已拍板 ①C**，2026-10-02） | **后端挂根行为不变**（#641 照旧一律挂根）；abstract 条目由**前端渲染层**从树过滤（复用 #721 `MapDirectoryTree` 的 kind 分流模式，扩展到列表页 `WorldNodeView`），仅在**分类筛选视图**（选中 abstract 分类）可见 | 🟢 **零后端改动**（无 DB / 无契约 / 无迁移）；前端须在**所有树渲染点**落地过滤（列表页 `WorldNodeView` + 地图树已有）；**局限**：后端数据层 abstract 条目仍挂在根下（`parent_id` 指向根）——其他消费方（CLI / MCP / agent 工具 / AI 提取读树）仍会看到其混在根下 |

**①(c) 已拍板（2026-10-02，用户「按照推荐」）**：唯一「零后端改动 + 零迁移 + 与 #1322 前端树分区过渡方案同族」的选项；#1322 已合的「未挂图条目折叠区」是同一模式的延伸。

### 16.3 ② geo 条目

**保持现状（② 已拍板，2026-10-02）**（#641 自动挂根）：geo 类（及未分类 / 未知分类，见 §16.4）条目继续自动挂根。#641 行为**不变**，**无迁移**。

### 16.4 ③ 谁判定 kind？（含无分类 / 未注册分类）

- **判定源**：**条目的分类的 kind** —— 按条目 `category`（字符串快照）在 `world_categories` 中查同名分类，取 `kind`。
- **边界 1（无分类）**：`category=""`（未分类）**合法**（§6.1「空类别 = 未分类」）→ 无分类可查 ⇒ **按 geo 处理（挂根）**。
- **边界 2（有类别但未注册）**：`category` 有值但分类实体不存在（AI 提取管线豁免所致，见 `world_service.py:189-192` 注释；UI 表现为 #1375 ②A「待注册」chip）→ 同样**按 geo 处理**。
- **判据统一（load-bearing）**：包「空/未知分类视为 geo」的口径**已在前端 #721 落地**（`kindByCategory.get(category) !== 'abstract'`，未命中 → geo）。**若选 (c)**，前端过滤直接沿用该判据，后端不参与；**若选 (a)/(b)**，后端 service 层新增判定**必须与前端同一判据**（否则 UI 与数据不一致）。
- **判定位置**：唯一真相源随选项而定 —— (c) = 前端渲染层；(a)/(b) = 后端 service 层（`create_setting` / `update_setting`），因须与 DB 约束/守卫生效面一致。
- **「未分类 / 未注册」为何不按 abstract**：若按 abstract 处理，则「无分类条目」会被静默排除出树——与 #722「根无分类」守护及 #1321「非根条目必填分类」的语义冲突（非根条目本应必有分类，空分类只应出现在根或历史豁免数据中）。按 geo 处理保持「默认可见」。
- **③ 已拍板（2026-10-02，用户「按照推荐」）**：判定 = 条目的分类的 kind；`category=""` 或分类未注册 → 按 geo 处理。此为定论，实现轨按此执行。

### 16.5 迁移影响评估（①C 不涉及；仅被否决的 (a)/(b) 需要）

| 面 | (a) 建第二根 | (b) 约定节点 |
|---|---|---|
| 契约 #567（根单例） | 🔴 重写：由「一项目一根」→「一项目每 kind 一根」 | 🟡 不变（仍唯一根） |
| 契约 #834（先建根 + 前置校验） | 🔴 重写 `parent_int is None` 分支（按 kind 判定根）+「先建根」按 kind | 🟡 部分（新增约定节点前置） |
| 契约 #847（更新守卫：置顶/改挂） | 🔴 重写「变更后每 kind 仍恰有一根」不变量 | 🟡 扩展（禁改挂/删除约定节点） |
| 契约 #849（DB 兜底） | 🔴 索引 → `(project_id, kind) WHERE parent_id IS NULL`；**须先给 `world_settings` 加 kind 列**（冗余分类 kind） | 🟡 不变（唯一根兜底仍成立） |
| 端点 / CLI | `POST /world-settings` 自动挂根分支按 kind；CLI `world create` 增 kind 语义（或由分类派生） | 约定节点创建/查找（或惰性创建） |
| 存量数据迁移 | 迁移函数（`create_all` + `ensure_*` 幂等，参照 `ensure_world_parent_id_column` 先例）：补 kind 冗余列；决定存量条目是否拆根 | 迁移：为存量 abstract 分类条目补挂约定节点 |
| 原型重出图范围 | `design/GUI/world/`：树视图（双根）+ 新建条目对话框（选父/kind）+ 新建分类对话框（geo/abstract 与挂根联动）；两原型 kind 表达收敛（§16.7） | 同（约定节点须在原型可见 + 防误删表达） |
| 测试面 | `backend/tests/unit/api/routers/test_world_api.py` 的 `TestWorldRootSingletonAPI`、`test_world_category_1321.py`、`MapDirectoryTree.*.test.tsx`、`library-p1/p2.test.tsx`、旅程 `stage4/stage5` 产物结构 | 同（+ 约定节点守护用例） |

**规模估计**（父侧按 issue 正文 3-5 人天校准）：(a) 因 §16.1 的「kind 不在条目表」约束，**实际高于 3-5 人天**（须加列 + 索引重建 + 四条契约 + 迁移 + 原型）；(b) 中等（约定节点机制 + 守护 + 迁移）；(c) **小**（纯前端过滤 + 测试）。

### 16.6 与 #1322 / #834 的关系

- **#1322**（树污染 + 地图树显示门控，已合）：其「页面树污染」的**过渡解** = 地图工作台「未挂图条目折叠区」（前端分区）+ 地图树 #721 kind 分流。**#1334 是其完整解**——(c) 即把 #1322 的前端分区模式扩展到**列表页树**并覆盖 abstract 分类。**#1322 已声明**：「列表页 `WorldNodeView` 树不受影响（一项目一根 #834 + 后端 #641 自动挂根语义**不变**）」——(c) 顺此声明延伸，(a)/(b) 则**推翻**它。
- **#834**（一项目一根，已合）：其「根单例」不变量是**当前后端硬语义**。(a) 直接推翻该不变量（成本最高）；(b) 保留不变量但未解决诉求；(c) **完全不触碰** #834 不变量——这正是 (c) 的最大优势。

### 16.7 ①C 落地：原型统一规则（实现轨执行；本轨不产出原型）

`design/GUI/` 三处 kind 表达自相矛盾（§16.1），须在实现轨按**单一规则**收敛：

1. **分类 chip**（工具栏）：**geo 类带 🗺、abstract 类不带**（依 `kind`）⇒ `world.html` 新 chips 须给「城市 / 秘境」补 🗺（其语义为 geo）；`library.html` 已符合；`world.html` legacy chips（全带 🗺）**保留为「复刻旧现状」对照，不作目标态**。
2. **树行分类徽标**：**不表达 kind**（只显示分类名），或与 chip 一致加 🗺——**二选一须统一**（现状为「树行一律无 🗺」）。**推荐：树行不表达 kind**（badge 空间有限，kind 由 chip + 树分区表达）。
3. **树分区**：abstract 条目移出主树（折叠区 / 分类筛选视图）——与 #1322 折叠区形态对齐。

> 上述规则**仅供实现轨**；本轨**不修改任何原型文件**（边界）。

### 16.8 拍板结果（2026-10-02 · 用户确认「按照推荐」）

| # | 决策点 | 结论（已拍板） |
|---|---|---|
| **①** | abstract 条目的父是谁？ | **①C — 不挂树**（后端挂根行为不变；abstract 条目由前端渲染层从树过滤，仅在分类筛选视图可见）。**否决**：(a) 建第二根、(b) 挂固定「抽象根」 |
| **②** | geo 条目 | **保持现状**（#641 自动挂根不变，无迁移） |
| **③** | 谁判定 kind | **条目的分类的 kind；`category=""` 或分类未注册 → 按 geo 处理**（与前端 #721 判据一致） |

> 落地归属：①C 由**前端渲染层**实现（`WorldNodeView` 树侧过滤，复用 #721 kind 分流模式），**后端零改动**；③ 判据前端沿用 `kindByCategory.get(category) !== 'abstract'`。实施轨开工无需再确认。

### 16.9 验收锚点（设计级，本章无实现）

- D1：§16.2 三选项各含「机制 + 代价 + 迁移影响」，且已拍板项明示局限。
- D2：§16.4 覆盖「无分类」「未注册分类」两个边界，并给出与前端 #721 一致的判据。
- D3：§16.5 列出 (a)/(b) 须同步的四条契约（#567/#834/#847/#849）+ 唯一索引改动 + 存量迁移 + 原型重出图范围。
- D4：§16.1 原型证据表纳入三处 kind 表达的自相矛盾项，并说明 (c) 下的统一规则（§16.7）。
- D5：**①C 已拍板**（2026-10-02）——实现轨按 ①C 实施（前端树过滤），**后端零改动**，无需同步 §3.1/§7/§12/§13。

---

*本章为 #1334 设计定义。① 已于 2026-10-02 拍板 **①C**（不挂树，前端过滤）；实现轨可据此开工。*
