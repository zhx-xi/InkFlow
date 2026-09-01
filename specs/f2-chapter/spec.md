# F2: 章节管理 (chapter_service) — 功能规格
> **端**: backend

> **Spec 版本**: 1.0 | **日期**: 2026-07-31 | **依据**: PRD v2.1 §6.1 F2, Constitution P1-P6
> **所属阶段**: Phase 1 — 核心引擎
> **关联 Issues**: [#2](https://github.com/zhx-xi/InkFlow/issues/2)
> **依赖**: F1 (project_service) 已完成 ✅
> **状态**: ✅ 已实现（PR #9）

---

## 1. 概述

实现卷（Volume）和章节（Chapter）的层级管理：卷是章节的逻辑分组容器，章节是实际写作内容的载体。系统自动追踪章节的写作状态流转和字数统计。

**核心价值**: 用户可以在项目中组织卷和章节结构，编辑章节内容，系统自动管理状态和字数——无需手动维护排序或统计。

---

## 2. 数据模型

### 2.1 ChapterStatus 枚举

```python
class ChapterStatus(StrEnum):
    DRAFT   = "draft"    # 草稿 — 新建章节的初始状态
    WRITING = "writing"  # 写作中 — 用户正在编辑
    REVIEW  = "review"   # 审阅中 — 等待审校
    FINAL   = "final"    # 定稿 — 内容已确认
```

### 2.2 Volume（卷）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，数据库 int 自增 |
| project_id | UUID | FK→projects.id, NOT NULL | 所属项目 |
| title | str | NOT NULL, 1-200 字符, 去空白 | 卷标题 |
| order_index | float | NOT NULL, DEFAULT 0.0 | 排序权重（浮点，支持任意位置插入） |

**业务规则**:
- 每项目卷数量不限
- 按 `order_index` 升序排列
- 删除卷时，其下章节的 `volume_id` 置为 NULL（变为"未分类"）

### 2.3 Chapter（章节）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，数据库 int 自增 |
| project_id | UUID | FK→projects.id, NOT NULL | 所属项目 |
| volume_id | UUID? | FK→volumes.id, NULLABLE | 所属卷（NULL=未分类） |
| title | str | NOT NULL, 1-500 字符, 去空白 | 章节标题 |
| content | str | NOT NULL, DEFAULT "" | Markdown 正文 |
| status | ChapterStatus | NOT NULL, DEFAULT DRAFT | 写作状态 |
| word_count | int | NOT NULL, DEFAULT 0 | 自动统计字数 |
| order_index | float | NOT NULL, DEFAULT 0.0 | 卷内排序权重 |
| status_history | list[StatusHistoryEntry] | NOT NULL, DEFAULT [] | 状态变更记录 |
| created_at | datetime | NOT NULL, AUTO | 创建时间（UTC） |
| updated_at | datetime | NOT NULL, AUTO | 更新时间（UTC） |

**业务规则**:
- 创建时自动计算 `word_count = count_words(content)`
- 更新 content 时重新计算 `word_count`
- 每次 status 变更时自动追加 `StatusHistoryEntry` 到 `status_history`
- 按 `order_index` 升序排列（卷内排序）
- 支持按 `volume_id` 筛选、按 `status` 筛选、分页

### 2.4 StatusHistoryEntry（状态变更记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| from_status | ChapterStatus | 变更前状态 |
| to_status | ChapterStatus | 变更后状态 |
| at | datetime | 变更时间（UTC ISO 格式） |

---

## 3. API 契约

### 3.1 Volume 端点

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/projects/{project_id}/volumes` | 创建卷 | `{title, order_index?}` | 201 + Volume |
| GET | `/api/v1/projects/{project_id}/volumes` | 列出卷 | — | 200 + `{items: [Volume]}` |
| GET | `/api/v1/volumes/{volume_id}` | 卷详情 | — | 200 + Volume |
| PATCH | `/api/v1/volumes/{volume_id}` | 更新卷 | `{title?, order_index?}` | 200 + Volume |
| DELETE | `/api/v1/volumes/{volume_id}` | 删除卷 | — | 204 (章节变未分类) |

### 3.2 Chapter 端点

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/projects/{project_id}/chapters` | 创建章节 | `{title, volume_id?, content?, order_index?}` | 201 + Chapter |
| GET | `/api/v1/projects/{project_id}/chapters` | 列出章节 | Query: `?volume_id=&status=&offset=&limit=` | 200 + `{items, total, offset, limit}` |
| GET | `/api/v1/chapters/{chapter_id}` | 章节详情 | — | 200 + Chapter |
| PATCH | `/api/v1/chapters/{chapter_id}` | 更新章节 | `{title?, volume_id?, content?, status?, order_index?}` | 200 + Chapter |
| DELETE | `/api/v1/chapters/{chapter_id}` | 硬删除 | — | 204 |
| POST | `/api/v1/chapters/{chapter_id}/move?target_volume_id=` | 跨卷移动 | — | 200 + Chapter |

### 3.3 错误响应格式

```json
// 404
{"detail": "卷不存在"}
{"detail": "章节不存在"}

// 422 (Pydantic 自动生成)
{"detail": [{"loc": ["body", "title"], "msg": "卷标题不能为空", "type": "value_error"}]}
```

---

## 4. CLI 命令签名

```bash
# Volume
inkflow volume create  --project-id <uuid> --title <str> [--order <float>] [--json]
inkflow volume list    --project-id <uuid> [--json]
inkflow volume delete  --id <uuid> [--force]

# Chapter
inkflow chapter create  --project-id <uuid> --title <str> [--volume-id <uuid>] [--content <str>] [--json]
inkflow chapter list    --project-id <uuid> [--volume-id <uuid>] [--status <str>] [--json]
inkflow chapter get     --id <uuid> [--json]
inkflow chapter update  --id <uuid> [--title <str>] [--content <str>] [--status <str>] [--json]
inkflow chapter move    --id <uuid> [--to-volume <uuid>] [--json]
inkflow chapter delete  --id <uuid> [--force]
```

---

## 5. 字数统计算法

```python
def count_words(content: str) -> int:
    """
    中英文混合字数统计：
    - 每个中文字符计 1 字
    - 每个英文单词计 1 字
    - 数字、标点、Markdown 语法不计入

    预处理：移除代码块、标题标记、粗斜体标记、链接语法等 Markdown 语法
    """
```

**示例**:
| 输入 | 输出 | 说明 |
|------|------|------|
| `"测试内容"` | 4 | 4 个中文字符 |
| `"hello world"` | 2 | 2 个英文单词 |
| `"你好world测试"` | 5 | 4 CJK + 1 EN |
| `"## 标题\n\n正文"` | 4 | "标题" 2 字 + "正文" 2 字 |
| `""` | 0 | 空字符串 |

---

## 6. 状态变更追踪

### 6.1 规则
- 创建章节时：无初始 history（空数组）
- 第一次状态变更：追加 `{from: "draft", to: "writing", at: "..."}`
- 后续变更：上次 `to` 变为下次 `from`
- 同一状态重复提交：无变更（不追加记录）

### 6.2 示例

```
创建: status="draft", history=[]
↓ update status="writing"
结果: status="writing", history=[{from:"draft", to:"writing", at:"2026-07-31T..."}]
↓ update status="review"
结果: status="review", history=[{...}, {from:"writing", to:"review", at:"..."}]
↓ update status="final"
结果: status="final", history=[{...}, {...}, {from:"review", to:"final", at:"..."}]
```

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 创建卷标题为空 | 422: "卷标题不能为空" |
| 创建卷标题全空白 | 422: "卷标题不能为空" |
| 创建卷标题 > 200 字符 | 422: "卷标题不能超过 200 个字符" |
| 创建章节标题为空 | 422: "章节标题不能为空" |
| 创建章节标题 > 500 字符 | 422: "章节标题不能超过 500 个字符" |
| 获取不存在的卷 | 404: "卷不存在" |
| 获取不存在的章节 | 404: "章节不存在" |
| 删除卷（有章节） | 章节的 volume_id → NULL，返回 204 |
| 删除卷（无章节） | 直接删除，返回 204 |
| 删除不存在的卷 | 404: "卷不存在" |
| 移动章节到不存在的卷 | 由 DB 外键约束拒绝（或 404） |
| 移动不存在的章节 | 404: "章节不存在" |
| 状态设为无效值 | 422: Pydantic 枚举验证拒绝 |
| 更新不存在的章节 | 404: "章节不存在" |
| order_index 不传 | 自动取当前最大值 + 1.0 |
| 空内容字数 | word_count = 0 |

---

## 8. 文件结构

遵循 ADR-007v2 包结构，新增/修改文件：

```
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── chapter.py          ← CREATE: Volume, Chapter, ChapterStatus, DTOs
│   │   └── __init__.py         ← MODIFY: 导出新模型
│   ├── ports/
│   │   └── chapter_repository.py ← CREATE: ChapterRepositoryProtocol
│   └── services/
│       ├── _word_count.py      ← CREATE: 字数统计工具函数
│       ├── chapter_service.py  ← CREATE: ChapterService
│       └── __init__.py         ← MODIFY
├── infrastructure/database/
│   ├── models/
│   │   ├── chapter.py          ← CREATE: VolumeORM, ChapterORM
│   │   └── __init__.py         ← MODIFY
│   └── repositories/
│       ├── chapter_repo.py     ← CREATE: SQLiteChapterRepository
│       └── __init__.py         ← MODIFY
├── api/
│   ├── routers/
│   │   └── chapter.py          ← CREATE: Volume + Chapter REST 端点
│   ├── deps.py                 ← MODIFY: 添加 get_chapter_service
│   └── app.py                  ← MODIFY: 注册 chapter.router
├── cli/
│   └── commands/
│       └── chapter.py          ← CREATE: volume + chapter CLI 命令
└── __main__.py                 ← MODIFY: 注册 volume/chapter 子命令

backend/tests/
├── conftest.py                 ← MODIFY: 添加 sample_project fixture
├── test_chapter.py             ← CREATE: 模型/仓储/服务测试
└── test_chapter_api.py         ← CREATE: API 集成测试
```

---

## 9. 测试策略

### 9.1 领域模型测试（TDD RED 起点）
- `test_chapter_status_enum` — 枚举值正确
- `test_volume_create_valid` — 正常创建 VolumeCreate
- `test_volume_create_empty_title` — 空标题抛 ValidationError
- `test_chapter_create_defaults` — 默认 status=DRAFT, word_count=0
- `test_chapter_update_partial` — 未设字段为 None

### 9.2 字数统计测试
- `test_count_chinese_only` — 纯中文计数
- `test_count_english_only` — 纯英文计数
- `test_count_mixed_cn_en` — 混合计数
- `test_count_empty` — 空内容 = 0
- `test_count_markdown_stripped` — Markdown 语法不计入

### 9.3 仓储测试（集成 in-memory SQLite）
- `test_add_volume` — 创建并查询卷
- `test_add_chapter_with_auto_word_count` — 创建章节自动计数
- `test_list_volumes_by_project` — 按项目列出卷
- `test_list_chapters_with_filters` — 按 volume/status 筛选
- `test_update_chapter_status_tracks_history` — 状态变更追加记录
- `test_move_chapter_between_volumes` — 跨卷移动
- `test_delete_volume_orphans_chapters` — 删卷后章节变孤儿
- `test_project_word_count` — 项目总字数聚合

### 9.4 服务测试（Mock Repository 可选）
- `test_create_volume_auto_order_index` — 不传 order 自动计算
- `test_create_chapter_auto_order_index` — 不传 order 自动计算
- `test_update_chapter_recomputes_word_count` — 改 content 重新计数
- `test_move_chapter_to_none` — 移出卷 (volume_id=None)

### 9.5 API 集成测试
- `test_create_and_list_volumes` — HTTP 创建→列表
- `test_chapter_lifecycle` — 创建→更新状态→删除完整流程
- `test_move_chapter_api` — HTTP 跨卷移动
- `test_list_chapters_with_status_filter` — query 参数筛选

---

## 10. 不在范围内

- ❌ 章节的富文本编辑器（Phase 2 Web UI 负责）
- ❌ 拖拽排序（Phase 2 Web UI 前端功能，后端只提供 order_index API）
- ❌ 章节版本历史（Phase 2+）
- ❌ 章节锁定/协作编辑（Phase 4+ 云端功能）
- ❌ 批量操作（批量删除/移动 — Phase 2 CLI 增强）

---

## 11. 依赖关系

```
F2 依赖:
  F1 (project_service) ✅ — project_id 外键引用 projects 表

F2 被依赖:
  F3 (writing_service) — 写作管道需要读写 Chapter.content
  F6 (context_service) — 上下文管理需要 Chapter.content 和 project 信息
  F7 (CLI) — chapter/volume 子命令
```
---

## 12. 动作确认

> 基于 §3 API + §4 CLI + §7 边界事实的状态流表。

### 12.1 Volume 端点状态流

| 端点 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| POST /projects/{id}/volumes | 项目存在 | 校验 title → 建 Volume | 201 + Volume | 422（title 空/>200） | title 必填；order_index 可省略 |
| GET /projects/{id}/volumes | 项目存在 | 列出 | 200 + {items} | — | — |
| GET /volumes/{id} | 卷存在 | 查询 | 200 + Volume | 404「卷不存在」 | — |
| PATCH /volumes/{id} | 卷存在 | 部分更新 | 200 + Volume | 404；422（title 非法） | 字段不传=不改 |
| DELETE /volumes/{id} | 卷存在 | 删卷 — 章节 volume_id 置 NULL | 204 | 404「卷不存在」 | 有章节→孤儿化；无章节→直接删 |

### 12.2 Chapter 端点状态流

| 端点 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| POST /projects/{id}/chapters | 项目存在 | 校验 title → 建 Chapter | 201 + Chapter | 422（title 空/>500） | title 必填；volume_id 可 NULL（未分类） |
| GET /projects/{id}/chapters | 项目存在 | 列表+过滤 | 200 + {items,total,offset,limit} | — | volume_id/status 过滤；分页 |
| GET /chapters/{id} | 章节存在 | 查询 | 200 + Chapter | 404「章节不存在」 | — |
| PATCH /chapters/{id} | 章节存在 | 部分更新（含 status） | 200 + Chapter | 404；422 | status 变更触发状态追踪（§6） |
| DELETE /chapters/{id} | 章节存在 | 硬删除 | 204 | 404 | — |
| POST /chapters/{id}/move?target_volume_id= | 章节存在 | 跨卷移动 | 200 + Chapter | 404 | 目标卷须存在 |

### 12.3 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| volume create/list/get/delete | 项目/卷存在 | CRUD | 人类可读/--json | 404/422 | delete 需 --force 确认 |
| chapter create/list/get/delete | 项目/章节存在 | CRUD | 人类可读/--json | 404/422 | — |

### 12.4 验收锚点

- A1：创建卷 title 空 → 422「卷标题不能为空」
- A2：删卷后章节 volume_id 置 NULL（孤儿），返回 204
- A3：/chapters/{id}/move 到不存在卷 → 404
- A4：空 content 字数 → word_count = 0
