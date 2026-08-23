# F1: 项目/书籍管理 (project_service) — 功能规格

> **Spec 版本**: 1.1 | **日期**: 2026-08-23 | **依据**: PRD v2.1 §6.1 F1, Constitution P1-P6
> **所属阶段**: Phase 1 — 核心引擎
> **关联 Issues**: [#1](https://github.com/zhx-xi/InkFlow/issues/1), [#595](https://github.com/zhx-xi/InkFlow/issues/595)
> **状态**: 已实现 (PR #8 merged) ✅（#595 破坏性重构：genre → tags，2026-08-23 拍板 D6=B/D7=A）
>
> **Spec 变更**（2026-08-23 @ v1.1，#595）：
> - 删除 `Genre` 枚举；`Project` 增加 `tags: list[str]`（多值标签）
> - 旧项目 `genre` 值迁移为 `tags` 的**初始数据**（`{genre_value}` → `tags=["{genre_value}"]`）
> - write_auto 题材变量 = `tags` 全拼串（不再读 `genre`）；输出/大纲的「类型」字段改从 `tags` 派生
> - tags 三处 GUI 入口：新建（多选+自定义新增）/ 项目设置页（编辑）/ 项目卡（展示）+ 轻量注册表（跨项目聚合已用 tags）

---

## 1. 概述

创建和管理小说项目，每个项目独立配置（AI 模型、Agent 角色、写作风格）。项目是 InkFlow 的顶级组织单元——卷、章节、写作配置均隶属于项目。

**核心价值**: 用户可以在 CLI 和 Web UI 中创建、搜索、排序和管理项目；每个项目拥有独立的 AI 写作配置，可导出/导入为 JSON；删除采用回收站模式（软删除），防止误操作。

---

## 2. 数据模型

### 2.1 标签（tags）— 多值项目标签（取代 genre 枚举，#595）

> **破坏性重构（v1.1，2026-08-23 拍板 D6=B）**：删除 `Genre` 枚举（原 11 种小说分类），改为自由多值标签 `tags: list[str]`。`write_auto` 题材不再读 `genre`，改从 `tags` 全拼串取。

**tags 语义**：
- `tags` 为 `list[str]`，每项是项目的一个标签（如 `["玄幻", "热血", "升级流"]`）
- **不限枚举**——用户可多选预设标签，也可自定义新增任意标签
- 每项校验：`str.strip()` 后非空；去重（保留首次出现顺序）；单标签长度上限 50
- **旧值迁移**：已存在项目的 `genre` 值映射为 tags 初始数据 `tags=["{genre_value}"]`（如原 `genre="玄幻"` → `tags=["玄幻"]`）；空/其他 值 → `tags=["其他"]`

**预设标签源（GUI 轻量注册表，D7=A）**：前端维护一个跨项目聚合的标签注册表，收集「本项目已用 tags ∪ 旧 genre 枚举值」作为新建对话框多选的建议项；仅作建议，不约束自定义输入。

### 2.2 Project（项目）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，数据库 int 自增映射 |
| name | str | NOT NULL, 1-100 字符, 去空白, 已索引 | 项目名称 |
| tags | list[str] | NOT NULL, DEFAULT [], JSON 列 | 项目标签（多值；由旧 genre 枚举值迁移而来，#595） |
| language | str | NOT NULL, DEFAULT "zh-CN" | 写作语言 |
| target_words | int | NOT NULL, DEFAULT 0 | 目标字数（0=不限） |
| config | ProjectConfig | NOT NULL, DEFAULT {} | AI 写作配置（JSON 序列化） |
| is_deleted | bool | NOT NULL, DEFAULT False, 已索引 | 软删除标记 |
| created_at | datetime | NOT NULL, AUTO | 创建时间 (UTC) |
| updated_at | datetime | NOT NULL, AUTO | 更新时间 (UTC) |

### 2.3 ProjectConfig（AI 写作配置）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| model | str | DEFAULT "gpt-4o" | 默认 AI 模型 |
| agent_architect | str? | NULLABLE | 架构师 Agent 模型（None=用默认） |
| agent_writer | str? | NULLABLE | 写手 Agent 模型 |
| agent_auditor | str? | NULLABLE | 审阅 Agent 模型 |
| agent_reviser | str? | NULLABLE | 修订 Agent 模型 |
| temperature | float | DEFAULT 0.7, [0.0, 2.0] | 生成温度 |
| writing_style | str | DEFAULT "" | 写作风格描述 |
| extra | dict[str, Any] | DEFAULT {} | 扩展配置字典（未来兼容） |

**业务规则**:
- 项目名称不能为空、不能全空白、不能超过 100 字符
- `config` 使用 Pydantic `ProjectConfig` 模型验证，存储为 JSON
- 软删除 (`is_deleted=True`) 后，列表和详情查询均不返回
- 删除需二次确认（CLI: `--force` 跳过确认）
- 支持回收站恢复 (`restore`)

### 2.4 ProjectCreate（创建 DTO）

| 字段 | 类型 | 默认值 | 验证 |
|------|------|--------|------|
| name | str | **必填** | 1-100 非空白 |
| tags | list[str] | [] | 多值；每项 strip 非空、去重、单标签 ≤50 |
| language | str | "zh-CN" | — |
| target_words | int | 0 | — |
| config | ProjectConfig | ProjectConfig() | — |

### 2.5 ProjectUpdate（更新 DTO — 所有字段可选）

| 字段 | 类型 | 默认值 | 验证 |
|------|------|--------|------|
| name | str? | None | 如果提供：1-100 非空白 |
| tags | list[str]? | None | 如果提供：整体替换（全量），每项 strip 非空、去重 |
| language | str? | None | — |
| target_words | int? | None | — |
| config | ProjectConfig? | None | — |
| is_deleted | bool? | None | — |

### 2.6 tags 消费方契约（#595）

**write_auto 题材变量（D6-a1 拍板）**: F3 写作管线 / 前端 `usePipeline` 的 `write_auto` 生成请求不再注入 `genre` 变量，改注入 `tags` 变量，值 = 项目 `tags` 的**全拼字符串**（`" ".join(tags)`，空格分隔；空 tags → 空串）。

- 前端 `usePipeline`：`write_auto` 分支 `vars.tags = options.tags.join(" ")`（`options.tags` 来自项目 `tags`）
- 后端内置模板：`pipeline_templates.py` 中 `_ARCHITECT_PROMPT` / `_AUTO_ARCHITECT_PROMPT` 的 `{genre}` 占位符改为 `{tags}`（`- 题材: {tags}`）
- **题材引导**：删 `genre` 字段后，若 `tags` 空，生成仍无题材引导（契约允许，但 D6=B 取舍：自由标签不强制单选）

**输出/大纲「类型」字段**（旧 `project.genre.value` 的消费者）:
- `output_service` 的 `BookMeta.genre`：改从 `tags` 派生（`" ".join(tags)`，空 → 空串）
- `outline_service` 的 `project_info`：「类型: {genre}」→「类型: {",".join(tags)}」

---

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/projects` | 创建项目 | `ProjectCreate` | 201 + Project JSON |
| GET | `/api/v1/projects` | 项目列表 | Query: `?search=&sort_by=&sort_desc=&offset=&limit=` | 200 + `{items, total, offset, limit}` |
| GET | `/api/v1/projects/{project_id}` | 项目详情 | — | 200 + Project JSON |
| PATCH | `/api/v1/projects/{project_id}` | 更新项目 | `ProjectUpdate` | 200 + Project JSON |
| DELETE | `/api/v1/projects/{project_id}` | 删除/硬删除 | Query: `?force=true` | 204 (默认软删除) |
| POST | `/api/v1/projects/{project_id}/restore` | 恢复项目 | — | 200 + Project JSON |

### 3.2 请求/响应示例

**创建项目**:
```http
POST /api/v1/projects
Content-Type: application/json

{
  "name": "星辰变",
  "tags": ["玄幻", "热血"],
  "language": "zh-CN",
  "target_words": 1000000,
  "config": {
    "model": "deepseek/deepseek-chat",
    "temperature": 0.8,
    "writing_style": "热血少年，轻快节奏"
  }
}
```
→ 201
```json
{
  "id": "3f2e1d4a-...",
  "name": "星辰变",
  "tags": ["玄幻", "热血"],
  "language": "zh-CN",
  "target_words": 1000000,
  "config": { "model": "deepseek/deepseek-chat", ... },
  "is_deleted": false,
  "created_at": "2026-07-31T10:00:00Z",
  "updated_at": "2026-07-31T10:00:00Z"
}
```

**列出项目（带搜索和分页）**:
```http
GET /api/v1/projects?search=星辰&sort_by=updated_at&sort_desc=true&offset=0&limit=20
```
→ 200
```json
{
  "items": [ ... ],
  "total": 1,
  "offset": 0,
  "limit": 20
}
```

**部分更新项目**:
```http
PATCH /api/v1/projects/3f2e1d4a-...
Content-Type: application/json

{ "name": "星辰变·改", "target_words": 2000000 }
```
→ 200 (更新后的 Project JSON)

**软删除项目**:
```http
DELETE /api/v1/projects/3f2e1d4a-...
```
→ 204

**硬删除项目**:
```http
DELETE /api/v1/projects/3f2e1d4a-...?force=true
```
→ 204

**恢复项目**:
```http
POST /api/v1/projects/3f2e1d4a-.../restore
```
→ 200
```json
{
  "id": "3f2e1d4a-...",
  "name": "星辰变",
  "is_deleted": false,
  ...
}
```

### 3.3 错误响应格式

```json
// 404 — 项目不存在
{"detail": "项目不存在"}

// 422 — Pydantic 验证失败 (自动生成)
{
  "detail": [{
    "loc": ["body", "name"],
    "msg": "项目名称不能为空",
    "type": "value_error"
  }]
}
```

---

## 4. CLI 命令签名

```bash
inkflow project create \
    --name "星辰变" \
    --tags 玄幻 --tags 热血 \
    --language zh-CN \
    --target-words 1000000 \
    [--json]

inkflow project list \
    [--search "星辰"] \
    [--sort name|updated_at|created_at] \
    [--json]

inkflow project get \
    --id <id> \
    [--json]

inkflow project delete \
    --id <id> \
    [--force]     # 跳过二次确认
    [--permanent] # 硬删除（永久删除，默认软删除）

inkflow project restore \
    --id <id>
```

### 4.1 --json 输出格式

```bash
# 默认人类可读
✅ 项目创建成功: [星辰变] (玄幻, 热血)

# --json 输出
inkflow project create --name "星辰变" --tags 玄幻 --tags 热血 --json
→ {"id": "3f2e1d4a-...", "name": "星辰变", ...}

inkflow project list --json
→ [{"id": "...", "name": "星辰变", ...}, ...]
```

### 4.2 二次确认交互

```bash
inkflow project delete --id 1
确定要删除项目 #1 吗？ [y/N]: y
✅ 项目 #1 已删除

inkflow project delete --id 1 --permanent
确定要永久删除项目 #1 吗？ [y/N]: y
✅ 项目 #1 永久删除

inkflow project delete --id 1 --force
# 跳过确认，直接删除
```

---

## 5. 软删除与回收站机制

### 5.1 删除流程

```
用户请求删除
  ├── force=false (默认)
  │   └── 二次确认 → 确认 → is_deleted=True
  │                → 取消 → 不操作
  └── force=true
      └── 直接 is_deleted=True
```

### 5.2 软删除的影响

| 操作 | 软删除后 |
|------|---------|
| GET /projects/{id} | 404（被排除） |
| GET /projects?search= | 不包含（被排除） |
| PATCH /projects/{id} | 404（被排除） |
| POST /projects/{id}/restore | ✅ 恢复（is_deleted=False） |
| DELETE /projects/{id}?force=true | ❌ 404（已软删除） |

### 5.3 硬删除

硬删除 (`?force=true`) 从数据库中物理删除记录。与软删除不同，硬删除**不可恢复**。

### 5.4 配置导出/导入

ProjectConfig 使用 Pydantic 模型验证，通过 `model_dump(mode="json")` 导出为 JSON。
用户可通过 API PATCH endpoint 替换整个 config 来实现导入。

```
导出: GET /api/v1/projects/{id} → config 字段即为可导出的 JSON
导入: PATCH /api/v1/projects/{id} {"config": {...}} → 替换配置
```

---

## 6. 搜索与排序

### 6.1 搜索
- `search` 参数对项目名称执行不区分大小写的子串匹配 (`icontains`)
- 空搜索或不传 `search` 不过滤
- 多个项目匹配时全部返回

### 6.2 排序
| 参数 | 可选值 | 说明 |
|------|--------|------|
| `sort_by` | `name`, `updated_at` (默认), `created_at` | 排序字段 |
| `sort_desc` | `true` (默认), `false` | 是否降序 |

示例:
- 按名称升序: `?sort_by=name&sort_desc=false`
- 按创建时间降序: `?sort_by=created_at&sort_desc=true`

### 6.3 分页
| 参数 | 默认值 | 约束 | 说明 |
|------|--------|------|------|
| `offset` | 0 | >= 0 | 跳过记录数 |
| `limit` | 50 | [1, 100] | 每页最大条数 |

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 创建项目名称为空 | 422: "项目名称不能为空" |
| 创建项目名称为空白 | 422: "项目名称不能为空" |
| 创建项目名称 > 100 字符 | 422: "项目名称不能超过 100 个字符" |
| 获取不存在的项目 | 404: "项目不存在" |
| 更新不存在的项目 | 404: "项目不存在" |
| 软删除不存在的项目 | 404: "项目不存在" |
| 硬删除已软删除的项目 | 404: "项目不存在" |
| 恢复不存在的项目 | 404: "项目不存在" |
| 恢复未被删除的项目 | 正常返回（重复操作无毒） |
| 软删除已软删除的项目 | 404: "项目不存在" |
| 创建项目不传 name | 422: "Field required" (FastAPI 自动) |
| 传 tags 含空白/空串项 | 422: "项目标签不能为空" |
| temperature 超出 [0, 2] 范围 | 422: "Input should be ..." |
| 搜索返回 0 结果 | 200: `{"items": [], "total": 0}` |
| 分页超出范围 | 200: `{"items": [], "total": N, "offset": M}` — 空列表 |
| limit 超过 100 | 422: FastAPI Query 验证拒绝 |
| 无效的 project_id 格式 | 404: "项目不存在" (UUID 解析失败统一处理) |

---

## 8. 文件结构

遵循 ADR-007 包结构，F1 已实现的文件：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── project.py           ← Project, ProjectConfig, ProjectCreate, ProjectUpdate (tags 取代 Genre)
│   │   └── __init__.py          ← 导出
│   ├── ports/
│   │   └── project_repository.py ← ProjectRepositoryProtocol (7 methods)
│   └── services/
│       ├── project_service.py   ← ProjectService (CRUD + search/sort/pagination)
│       └── __init__.py
├── infrastructure/database/
│   ├── models/
│   │   ├── project.py           ← ProjectORM (SQLAlchemy 2.0 async)
│   │   └── __init__.py
│   └── repositories/
│       ├── project_repo.py      ← SQLiteProjectRepository
│       └── __init__.py
├── api/
│   ├── routers/
│   │   ├── project.py           ← 7 个 REST 端点
│   │   └── __init__.py
│   ├── deps.py                  ← get_db, get_project_service
│   └── app.py                   ← lifespan + router 注册 + CORS
├── cli/
│   └── commands/
│       └── project.py           ← 5 个 CLI 命令 (create/list/get/delete/restore)
├── core/
│   ├── database.py              ← async engine, session factory, create_tables
│   ├── config.py                ← 应用配置
│   └── log.py                   ← 日志设置
└── __main__.py                  ← Typer 入口 + serve 命令

backend/tests/
├── conftest.py                  ← db_session, sample_project_data fixtures
├── test_project.py              ← 领域模型 + 仓储 + 服务测试 (14 tests)
├── test_project_api.py          ← API 集成测试 (8 tests)
└── test_health.py               ← 健康检查测试
```

---

## 9. 测试策略

### 9.1 领域模型测试 (Pydantic 验证)

| 测试 | 验证点 |
|------|--------|
| `test_create_with_valid_data` | 正常创建所有字段合法 |
| `test_create_empty_name_raises` | 空名称 → ValidationError |
| `test_create_whitespace_name_raises` | 纯空格 → ValidationError |
| `test_create_name_too_long_raises` | 超长 → ValidationError |
| `test_create_defaults` | 默认值正确 (tags=[], language=zh-CN, target_words=0, model=gpt-4o) |
| `test_update_partial` | 部分更新未设字段为 None |
| `test_update_empty_name_raises` | 更新空名称 → ValidationError |

### 9.2 仓储测试（集成 in-memory SQLite）

| 测试 | 验证点 |
|------|--------|
| `test_create_project` | 创建→get 返回带 ID 的 Project |
| `test_list_projects` | 2 项目 total=2, len=2 |
| `test_list_projects_with_search` | search="科幻" 返回 total=1 |
| `test_update_project` | 更新名称后 `result.name == "新名称"` |
| `test_soft_delete_project` | 软删除后 get 返回 None |

### 9.3 服务测试

| 测试 | 验证点 |
|------|--------|
| `test_create_project` | 返回完整 Project: id 不为空, is_deleted=False |
| `test_list_projects_with_sort` | 按 name 升序 A → B |
| `test_soft_delete_then_list_excludes` | 删除后列表不包含 |

### 9.4 API 集成测试（Mock Service）

| 测试 | 验证点 |
|------|--------|
| `test_create_project` | POST → 201 + name + id |
| `test_create_project_empty_name` | POST 空 name → 422 |
| `test_list_projects` | GET → 200 + items + total |
| `test_get_project` | GET by id → 200 + name + id |
| `test_get_project_not_found` | GET 不存在 → 404 |
| `test_update_project` | PATCH → 200 + 新名称 |
| `test_delete_project` | DELETE → 204 |
| `test_restore_project` | POST restore → 200 + Project JSON |

### 9.5 测试覆盖率目标

- 领域模型验证: 100% 覆盖所有 DTO 验证规则
- 仓储 CRUD: 覆盖全部 7 个方法 (add/get/list_all/update/soft_delete/restore/hard_delete)
- 服务业务逻辑: 覆盖创建、列表（含排序）、软删除排除三项核心
- API 端点: 覆盖全部 7 个端点 + 典型错误路径

---

## 10. 不在范围内

- ❌ 项目封面图/图标上传（Phase 2+ 媒体管理）
- ❌ 项目级权限/共享（Phase 4 云端功能）
- ❌ 项目的统计分析（写作速度、时间线 — Phase 3+）
- ❌ 项目模板（从模板创建 — Phase 2+）
- ❌ 回收站 GUI 界面（Phase 2 Web UI 负责）
- ❌ 批量删除/恢复（Phase 2+）
- ❌ 导入/导出项目为完整文件（Phase 2+）

---

## 11. 依赖关系

```text
F1 依赖:
  无（Phase 1 基础功能，不依赖其他 F 模块）

F1 被依赖:
  F2 (chapter_service)     — chapter.volume_id/project_id FK → projects.id
  F3 (writing_service)     — 写作需要项目配置 (project.config)
  F4 (agent_service)       — Agent 编排需要项目配置
  F5 (llm_service)         — LLM 调用需要项目配置中的 model
  F6 (context_service)     — 上下文管理需要项目信息
  F7 (CLI)                 — project 子命令
```

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| id 类型 | 领域层 UUID, DB int 自增 | 领域模型可移植性 + SQLite 性能 |
| 软删除 | `is_deleted` bool 标志 | 回收站功能的基础，Phase 1 简单实现 |
| config 存储 | JSON 列 + Pydantic 验证 | 灵活可扩展，无需为不同配置建多表 |
| Protocol | `typing.Protocol` 结构化子类型 | 轻量，无需抽象基类，测试即可 mock |
| ORM 映射 | `_orm_to_domain()` 手动转换 | 清理 ORM 与非 ORM 的边界，避免泄露 |
| Service 依赖 | 直接实例化 Repository | 单人开发，暂时不需要 IoC 容器 |
| UUID 解析 | 自定义 `_parse_project_id` | 统一处理无效格式为 404 |
| tags 取代 genre（#595，D6=B 拍板） | 删 `Genre` 枚举；`tags: list[str]`（JSON 列） | 单用户未上线，删枚举重建可接受；自由标签比 11 固定分类更贴合创作，write_auto 题材改从 tags 全拼取（D6-a1） |
