# F21: 导出服务（output_service）— 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-09 | **依据**: PRD v2.2 §6.4 P1-15, Issue #53, Constitution P1-P6（P2 解耦 / P5 YAGNI）
> **所属阶段**: 0.6.0（#53 导出服务，估算 3-4 人天）
> **关联 Issues**: [#53](https://github.com/zhx-xi/InkFlow/issues/53)
> **依赖**: ✅ F1（项目校验 + Project 读取）· ✅ F2（卷/章读取）· ✅ F9（角色档案读取）· ✅ F10（世界观条目读取）· ✅ F11（大纲/情节点读取）· ✅ F12（时间线事件读取）· ✅ F13（伏笔档案读取）· ✅ F19 #77（token 中间件：导出端点同样受保护）· ⏳ 无
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md)（模块化单体）· [ADR-002](../../adr/ADR-002.md)（六边形分层）· [ADR-003](../../adr/ADR-003.md)（Repository）· [ADR-004](../../adr/ADR-004.md)（Pydantic v2）· [ADR-012](../../adr/ADR-012.md)（错误处理）· [ADR-018](../../adr/ADR-018.md)（测试分层）· [ADR-019](../../adr/ADR-019.md)（版本里程碑 + 模块编号口径）· [ADR-021](../../adr/ADR-021.md)（内核进程化：token 契约）· [ADR-025](../../adr/ADR-025.md)（依赖锁定：新依赖须入 uv.lock）· [ADR-027](../../adr/ADR-027.md)（覆盖率门禁）
> **状态**: 待实现 🔲（0.6.0）

---

## 1. 概述

提供**项目内容导出**能力：把项目内的正文（卷/章）与设定档案（角色/世界观/大纲/时间线/伏笔）聚合为统一中间表示（BookDocument），再序列化为 **EPUB / Markdown / TXT / DOCX** 四种格式（≥3 种，满足 PRD P1-15 与 Issue #53 验收标准），供作者**备份、分享、发布**到外部平台。

**核心价值**: 创作数据不锁定在 InkFlow 内——作者可以随时把作品带走（发布到起点/晋江、给编辑审稿、本地归档），这是「本地完全可用」的最后一环（ADR-019 v5：1.0.0 = CLI+GUI+skills+MCP 四界面齐备，导出是 CLI/API 的天然交付物）。

**变体定位（第 15 变体「导出聚合型」）**: 本模块是 **F15 横切只读聚合模式 × F12 确定性算法模式**的产物变体——它像 F15 一样只读聚合多模块档案（零跨模块 MODIFY，F15 先例 §5.5），但输出不是审计报告而是**可交付文件字节**；它像 F12 一样无 LLM、纯确定性（同一项目 → 同一字节流，快照可测），但 §5 核心不是检查算法而是**聚合 + 序列化管线**。编号依据 AGENTS.md 模块类型谱系（F30=第 13 变体 / F32=第 14 变体，F21/F22 立项于 0.6.0，编号按 ADR-019 口径，冲突以 ADR-019 v5+ 为准）。

```
输入: 项目各模块档案（DB） ──只读聚合──▶ BookDocument（统一中间表示）
                                        ──序列化器──▶ EPUB / Markdown / TXT / DOCX 字节流
                                        （纯函数，无状态）
```

**边界声明**:
- F21 只做**导出（读 + 序列化）**，不做**导入**（导入/还原归未来模块，见 §10）
- F21 不新建实体表、无数据库迁移（schema 由 `Base.metadata.create_all` 管理，本模块零新表）
- F21 不含 **PDF**（排版引擎太重，YAGNI，见 §10）与**批量/定时导出**（无场景，见 §10）
- F21 是**纯后端能力**：API 端点（下载）+ CLI（写文件）；GUI 导出按钮消费 API，属前端接线不在本 spec 范围
- F21 不修改任何既有模块的 Repository/Service（零跨模块 MODIFY，读取全部走既有只读方法，见 §8）

---

## 2. 数据模型

遵循本项目「领域 Pydantic 实体 + DTO」模式（ADR-004），但 F21 **不新建持久化实体**——所有输入来自既有模块实体（F1 Project / F2 Volume+Chapter / F9 Character / F10 WorldSetting / F11 Outline+PlotPoint / F12 TimelineEvent / F13 Foreshadowing，字段见各模块 spec，本 spec 不重复定义）。F21 新增的是**传输/中间表示 DTO**，均为瞬态计算产物。

### 2.1 ExportFormat（导出格式枚举）

| 值 | 说明 | 序列化器 |
|----|------|----------|
| `epub` | EPUB 3 电子书（zip 容器 + XHTML + OPF + NCX） | `_epub_exporter` |
| `markdown` | Markdown 文档（卷/章标题 + 正文 + 附录） | `_markdown_exporter` |
| `txt` | 纯文本（UTF-8，标题线 + 正文 + 附录） | `_txt_exporter` |
| `docx` | Word 文档（OOXML zip 容器） | `_docx_exporter` |

### 2.2 BookDocument（统一中间表示，瞬态）

导出管线第一步把各模块实体聚合为**单一文档树**，序列化器只消费它——格式差异与数据源完全解耦（新增格式 = 新增序列化器，不动聚合器）。

```python
class BookMeta(BaseModel):
    """项目元信息（导出文件头部/封面页使用）。"""
    title: str          # project.name
    genre: str          # project.genre（中文字面量）
    language: str       # project.language（默认 zh-CN）
    target_words: int   # project.target_words
    updated_at: datetime

class BookChapter(BaseModel):
    """单章（正文树节点）。"""
    title: str
    content: str        # 原样正文（含换行），不做格式清洗
    order_index: float  # 卷内排序
    word_count: int     # 展示用

class BookVolume(BaseModel):
    """卷（正文树一层；无卷章节挂 volume_id=None 的「未分组」卷下）。"""
    title: str
    order_index: float
    chapters: list[BookChapter]

class BookSetting(BaseModel):
    """设定档案条目（附录；type 对应各模块）。"""
    type: str           # character / world / outline / timeline / foreshadowing
    name: str
    content: str        # 各模块摘要拼接（见 §6.3）

class BookDocument(BaseModel):
    meta: BookMeta
    volumes: list[BookVolume]
    settings: list[BookSetting]   # include_settings=false 时为空列表
```

### 2.3 ExportRequest / ExportResult（传输 DTO）

```python
class ExportRequest(BaseModel):
    """导出参数（API query / CLI 选项统一语义）。"""
    format: ExportFormat
    include_settings: bool = False   # 是否含设定档案附录（Q3 拍板）

class ExportResult(BaseModel):
    """CLI --json 信封的 payload（API 直接返回字节流，不用此模型）。"""
    format: ExportFormat
    filename: str        # 建议文件名（含扩展名）
    bytes: int           # 字节数
    path: str            # CLI 实际写入路径（API 侧为空）
```

> **决策论证表**：中间表示选「树 + 平铺附录」而非「完整镜像各模块模型」——导出只消费展示级字段（标题/正文/名称/内容），镜像完整实体会把 `status_history`、`extra`、`is_deleted` 等内部状态带进交付物，且任一模块加字段都迫使本模块跟进（耦合）。「平铺附录」不做角色分组/伏笔-事件关联的层级重建（YAGNI：导出是快照不是导航，见 §12 D3）。

---

## 3. API 契约

### 3.1 端点总览（1 个，GET 下载）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/projects/{project_id}/export` | 导出项目（query 参数见下） |

- query：`format`（必填，枚举 `epub`/`markdown`/`txt`/`docx`）、`include_settings`（可选，默认 `false`）
- 响应：**200 二进制文件流**（`Content-Type` 按格式：`application/epub+zip` / `text/markdown; charset=utf-8` / `text/plain; charset=utf-8` / `application/vnd.openxmlformats-officedocument.wordprocessingml.document`）+ `Content-Disposition: attachment; filename="<书名>-<格式>.<ext>"`（文件名 URL 编码，防中文/空格破坏头）
- 实现：FastAPI `Response`（字节已在内存，无需 StreamingResponse 流式——导出产物一次性组装；见 §12 D5）
- 幂等：GET 只读、无副作用；同一参数重复调用产出相同字节（确定性，§5.5）

### 3.2 请求/响应示例

```http
GET /api/v1/projects/1/export?format=markdown&include_settings=true
→ 200
Content-Type: text/markdown; charset=utf-8
Content-Disposition: attachment; filename="mybook-markdown.md"

# 我的小说

## 第一卷：序章

### 第 1 章 开端
...
```

### 3.3 异常映射表

| 场景 | HTTP 状态 | 错误 body（ADR-012 统一格式） | 抛出/捕获点 |
|------|-----------|-------------------------------|-------------|
| 项目不存在 / 已软删 | 404 | `{"detail": "Project not found"}` | service 校验（复用 F9 character_errors `ProjectNotFoundError`，陷阱 16：**不导出**到 `ports/__init__.py`，router 显式 except 映射） |
| `format` 非法 | 422 | Pydantic `Literal` 校验错误 | DTO 层（FastAPI 自动） |
| `include_settings` 非法 | 422 | Pydantic 校验错误 | DTO 层 |
| 项目存在但无任何内容 | 200 | 空文档（标题 + 空正文，见 §7 E4） | 不视为错误 |
| 内部错误（序列化异常） | 500 | `{"detail": "Internal server error"}` | router `except Exception` → loguru（ADR-016） |

---

## 4. CLI 命令签名

F7 全局约定：`--json` 信封（`{"success": bool, "data": ..., "error": ...}`）、退出码 0 成功 / 1 业务错误 / 2 用法错误。F21 新增 `inkflow export` 组（1 个命令，直接消费 service，不经 HTTP——六边形表现层适配器，F23 先例）。

```text
inkflow export <project> [--format epub|markdown|txt|docx] [--include-settings] [--output PATH]

参数:
  project                 项目名称或 ID（F1 约定：名称精确匹配，数字按 ID 解析）
  --format, -f            导出格式（默认 markdown）
  --include-settings      包含设定档案附录（默认不含）
  --output, -o            输出路径。目录 → 用建议文件名写入；文件路径 → 直接写入。
                          默认当前工作目录 + 建议文件名
  --json                  输出 JSON 信封

成功: 退出 0；信封 data = ExportResult {format, filename, bytes, path}
失败: 项目不存在 → 退出 1，error = "项目不存在: <name>"
      格式非法 → 退出 2（Typer 自动）
      写文件失败（权限/磁盘）→ 退出 1，error = 系统错误消息
```

示例：

```text
$ inkflow export 我的书 -f epub -o ./out/
Exporting 我的书 → ./out/我的书-epub.epub (1,234,567 bytes)

$ inkflow export 我的书 --format markdown --include-settings --json
{"success": true, "data": {"format": "markdown", "filename": "我的书-markdown.md", "bytes": 2048, "path": "我的书-markdown.md"}}
```

---

## 5. 导出管线模式（关键差异：聚合 + 确定性序列化）

> ⚠️ **本节是 F21 与既有样板的核心差异点**：F9/F10 §5 是「AI 提取管线」，F12 §5 是「一致性检查算法」，F15 §5 是「审计规则引擎」；本模块的 §5 是**「只读聚合 → 中间表示 → 格式序列化」三阶段管线**——无 LLM、无模板、无重试，纯确定性。

### 5.1 模式总览

```text
 ┌─────────────────────────────────────────────────────────────────┐
 │ ExportService.export(project_id, format, include_settings)       │
 └──────────────────────────┬──────────────────────────────────────┘
                            ▼
 ① 校验项目存在（F1 ProjectRepository.get）→ ProjectNotFoundError(404)
 ② 聚合正文树（只读，全部并行拉取）:
    - ProjectRepository.get                       → meta
    - ChapterRepository.list_volumes(pid)         → volumes 骨架
    - ChapterRepository.list_chapters(pid, 含卷分组) → 每卷 chapters（volume_id=None → 「未分组」）
      （排除 is_deleted；按 order_index 升序，F2 语义）
 ③ 若 include_settings: 聚合附录（只读，并行）:
    - CharacterRepository.list(pid, 排除软删)     → character 条目
    - WorldRepository.list(pid)                   → world 条目
    - OutlineRepository.list(pid)                 → outline 条目（含 PlotPoint 摘要）
    - TimelineRepository.list_all(pid)            → timeline 条目
    - ForeshadowingRepository.list(pid)           → foreshadowing 条目
 ④ 组装 BookDocument（统一中间表示，§2.2）
 ⑤ 分发序列化器: _epub_exporter / _markdown_exporter / _txt_exporter / _docx_exporter
    （纯函数: BookDocument → bytes，无状态无 I/O）
 ⑥ 返回 ExportResult（API: Response 字节流；CLI: 写文件 + 信封）
```

**模式要点**:
1. **只读聚合**：全部走既有 Repository Protocol 只读方法（方法名见 §8.2），零跨模块 MODIFY（F15 §5.5 先例）
2. **并行拉取**：正文/附录各数据源相互独立，`asyncio.gather` 并行（单项目量级下收益有限但零成本，F15 编排先例）
3. **确定性**：同一项目 + 同一参数 → 同一字节流（所有排序键稳定，见 §6.1；无时间戳/随机量入文件——EPUB 的 dc:date 除外，见 §5.6 注）
4. **无副作用**：导出不修改任何数据；字节流内存组装，不落临时文件（API 场景）；CLI 落盘是用户显式行为
5. **序列化器可独立测试**：给 BookDocument fixture → 断言字节/文本结构，不依赖 DB

### 5.2 Markdown 序列化器（_markdown_exporter）

零依赖，字符串拼接：

```text
# {meta.title}

> 类型：{genre} · 语言：{language} · 目标字数：{target_words} · 更新于：{updated_at}

## {volume.title}

### {chapter.title}

{chapter.content}

（附录，include_settings=true 时）---

## 附录：设定档案

### 角色

#### {name}

{personality / background / goals 摘要}

### 世界观 / 大纲 / 时间线 / 伏笔
（同构分节）
```

- 标题层级：`#` 书名 → `##` 卷 → `###` 章 → `####` 附录条目名
- 正文原样保留（不转义、不清理；作者可能已含 Markdown 语法）
- 文件名：`{书名}-markdown.md`（非法字符清洗见 §7 E5）

### 5.3 TXT 序列化器（_txt_exporter）

零依赖，纯文本（UTF-8）：

```text
{书名}
{分隔线：= 重复 30 个}

第 {N} 卷 {volume.title}
{分隔线：- 重复 30 个}

第 {M} 章 {chapter.title}

{chapter.content}

（附录同理：类型标题 + 条目名 + 摘要，用 = 分隔）
```

- 章节编号 = 全局顺序（跨卷连续计数）还是卷内序号？**卷内序号 + 卷前缀**（「第 1 卷 · 第 3 章」），符合中文网文惯例（§6.2）

### 5.4 EPUB 序列化器（_epub_exporter）

EPUB 3 最小实现（zipfile + xml.etree，标准库，零新依赖——Q2 拍板候选 B/C）：

```text
mimetype                    (application/epub+zip，必须首项且无压缩)
META-INF/container.xml      (rootfile → OEBPS/content.opf)
OEBPS/content.opf           (metadata + manifest + spine)
OEBPS/toc.ncx               (NCX 导航，兼容旧阅读器)
OEBPS/title.xhtml           (封面页：书名 + 元信息)
OEBPS/chapter-{i}.xhtml     (每卷每章一页：<h1>卷名</h1><h2>章名</h2><p>正文</p>)
OEBPS/setting-{i}.xhtml     (附录页，include_settings=true 时)
```

- 正文换行 → `<p>` 分段；正文内既有 Markdown 语法**原样文本化**（EPUB 不做 Markdown 渲染，见 §12 D4）
- `dc:identifier` 用项目 id 稳定值（非随机 UUID——确定性要求；`dc:date` 用项目 `updated_at`，**不用当前时间**，保证确定性）
- `content.opf` 的 spine/manifest 顺序 = 卷/章排序（§6.1），阅读器按序翻页

### 5.5 DOCX 序列化器（_docx_exporter）

OOXML 最小实现（zipfile + xml.etree）或 python-docx（Q2 拍板候选 A）：

```text
[Content_Types].xml        (document + styles 类型声明)
_rels/.rels                (根关系 → word/document.xml)
word/document.xml          (标题段落 Heading1/2 + 正文段落 Normal)
word/styles.xml            (最小样式集：Normal/Heading1/Heading2——缺少 styles.xml 部分 Word 版本打开异常，见 Q2)
```

- 段落映射：书名 → Heading1、卷 → Heading2、章 → Heading3、正文按 `\n` 分段 → Normal
- 附录条目 → Heading3 + 正文段落

### 5.6 确定性声明

| 输入 | 输出 |
|------|------|
| 同一项目 + 同一参数 | 同一字节流（EPUB/DOCX 内 zip 条目的时间戳统一固定为项目 `updated_at`，否则 zip 头含当前时间破坏字节级确定性——实现注意项） |

zipfile 默认写当前时间戳到条目头 → 序列化器必须 `ZipInfo(date_time=...)` 固定时间（用 `updated_at`），否则快照测试不稳定。这是实现 RED 测试会先暴露的坑，spec 先行声明。

### 5.7 导出聚合型 vs 既有样板：差异对照表

| 维度 | F12 一致性检查 | F15 审计 | **F21 导出** |
|------|---------------|----------|--------------|
| 数据源 | 单模块（时间线） | 4+ 模块只读聚合 | 7 模块只读聚合（正文 2 + 附录 5） |
| 输出 | 内存报告 | 内存报告 | **文件字节流（4 格式）** |
| 新实体表 | 无 | 无（AuditReport 瞬态） | **无（BookDocument 瞬态）** |
| 新 API | 8 端点 CRUD | 1 只读端点 | **1 下载端点** |
| 新 CLI | timeline 组 | audit 组 | **export 组** |
| 算法性质 | 相邻对扫描 | 规则引擎 | **聚合 + 序列化** |
| 跨模块 MODIFY | 无 | 无（audit_repo 补充端口） | **无（全走既有只读方法）** |
| LLM | 无 | 无 | **无** |

---

## 6. 导出内容组织规则

### 6.1 排序键（确定性第一原则）

| 层级 | 排序键 | 说明 |
|------|--------|------|
| 卷 | `order_index ASC, created_at ASC` | F2 语义 |
| 章（卷内） | `order_index ASC, created_at ASC` | F2 语义 |
| 未分组章 | 单独「未分组」卷，排在所有命名卷之后 | `volume_id IS NULL` |
| 附录-角色 | `created_at ASC`（稳定 ASCII 键为 created_at；**不用 name 排序**——中文码点序与直觉不符，F15 教训） |
| 附录-世界观 | 同上 | |
| 附录-大纲 | outline `sort_order ASC, created_at ASC`；其 PlotPoint 按 `position ASC` | |
| 附录-时间线 | `narrative_position ASC, created_at ASC` | F12 叙事序 |
| 附录-伏笔 | `created_at ASC` | |

### 6.2 章编号显示

- Markdown/TXT：卷内「第 N 章」（N = 卷内序号从 1 计数）；EPUB/DOCX：章节标题原样（`<h2>{chapter.title}</h2>`），不加编号前缀（阅读器自带导航）
- TXT 全卷场景：全局「第 N 章」更常见？——**统一用卷内序号 + 卷前缀**（「第一卷 · 第 3 章」），TXT 单卷项目自然退化为「第 3 章」（TXT 无卷时省略卷前缀，仅显示「第 N 章」）

### 6.3 附录条目摘要拼接（BookSetting.content）

| type | 拼接内容 |
|------|----------|
| character | `性格：{personality}\n背景：{background}\n目标：{goals}`（空字段跳过） |
| world | `{content}`（category 空则省略） |
| outline | `{description}` + 情节点列表 `- {point.name}（{point.type}）: {point.description}` |
| timeline | `{time_display}｜{description}`（time_display 空则用 title） |
| foreshadowing | `状态：{status}｜{description}`（location 非空追加 `｜埋设：{location}`） |

> 附录是**摘要快照**不是全量迁移（不含 extra/状态历史/分组关系），导出主场景是「带走可读内容」而非「无损备份」——无损备份是导入模块的未来职责（§10）。

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| E1 | 项目不存在 / 已软删 | 404（ProjectNotFoundError 复用，§3.3） |
| E2 | 项目无卷无章 | 200：空文档（书名 + 附录如有）；TXT/MD 输出标题即可，不报错 |
| E3 | 章节正文含特殊字符 | Markdown/TXT 原样；EPUB/DOCX 必须 XML 转义（`& < >` 等）——**序列化器各自负责转义**，BookDocument 层不转义 |
| E4 | 仅设定了无正文 | 同 E2：正文空 + 附录完整（include_settings=true 时） |
| E5 | 文件名非法字符（Windows：`\ / : * ? " < > |`） | 清洗为 `_`；文件名取书名前 60 字符（超长截断） |
| E6 | 正文超长（单章 MB 级） | 正常导出（字节流内存组装；EPUB/DOCX 分页按章，无全量字符串拼接） |
| E7 | 空书名 | 书名占位 `untitled` |
| E8 | CLI 输出路径为已存在文件 | 直接覆盖（CLI 语义，不做确认——导出是低风险操作；F24 删除才需确认框） |
| E9 | 并行拉取单源失败（DB 异常） | 整体 500（无部分导出——导出是原子快照，不接受半成品；loguru 记录） |
| E10 | 格式枚举非法（API） | 422（Pydantic Literal） |
| E11 | 导出期间数据变更 | 快照语义：以聚合时刻数据为准，不保证与导出完成后数据一致（无锁，单用户本地场景可接受，§12 D5） |

---

## 8. 文件结构

### 8.1 CREATE/MODIFY 清单（对照真实源码树 `backend/src/inkflow/`）

| 类型 | 路径 | 说明 |
|------|------|------|
| CREATE | `domain/models/output.py` | ExportFormat / BookMeta / BookChapter / BookVolume / BookSetting / BookDocument / ExportRequest / ExportResult（§2） |
| CREATE | `domain/ports/output_errors.py` | 模块专属错误（见下）；`ProjectNotFoundError` **不在此定义**（复用 F9 character_errors，陷阱 16） |
| CREATE | `domain/services/output_service.py` | ExportService：聚合编排（§5.1 ①-④⑥） |
| CREATE | `domain/services/_exporters/__init__.py` | 序列化器包（导出内部实现，不进 `ports/__init__.py`） |
| CREATE | `domain/services/_exporters/markdown_exporter.py` | `to_markdown(book) -> str`（§5.2） |
| CREATE | `domain/services/_exporters/txt_exporter.py` | `to_txt(book) -> str`（§5.3） |
| CREATE | `domain/services/_exporters/epub_exporter.py` | `to_epub(book) -> bytes`（§5.4；Q2 若选 A 则改调 ebooklib） |
| CREATE | `domain/services/_exporters/docx_exporter.py` | `to_docx(book) -> bytes`（§5.5；Q2 若选 A 则改调 python-docx） |
| CREATE | `domain/services/_exporters/filename.py` | `suggest_filename(title, fmt)`（§7 E5/E7） |
| CREATE | `api/routers/export.py` | GET `/api/v1/projects/{pid}/export`（§3） |
| CREATE | `cli/commands/export.py` | `inkflow export` 组（§4） |
| CREATE | `backend/tests/unit/test_output_models.py` | DTO/枚举测试（§9） |
| CREATE | `backend/tests/unit/test_output_service.py` | 聚合编排测试（§9） |
| CREATE | `backend/tests/unit/test_exporters_markdown.py` | MD 序列化器（§9） |
| CREATE | `backend/tests/unit/test_exporters_txt.py` | TXT 序列化器 |
| CREATE | `backend/tests/unit/test_exporters_epub.py` | EPUB 结构断言（zip 条目清单 + OPF XML 解析） |
| CREATE | `backend/tests/unit/test_exporters_docx.py` | DOCX 结构断言（zip 条目 + document.xml 解析） |
| CREATE | `backend/tests/unit/test_output_service_export.py` | 全管线集成（mock repos → 字节非空 + 格式嗅探） |
| CREATE | `tests/cli/test_cli_export.py` | CLI 测试（仓库根 `tests/cli/`，Issue #61 约定；**新文件必须显式追加 integration-cli-backend job**——陷阱 13/15） |
| CREATE | `tests/api/test_export_api.py` | API 端点测试（仓库根 `tests/api/`，F32 先例 `test_settings_api.py` 同处） |
| MODIFY | `api/app.py` | `app.include_router(export.router)` + import（1 行） |
| MODIFY | `api/deps.py` | ExportService 装配（注入 7 个 repository；见 §8.2） |
| MODIFY | `cli/app.py` | import + `app.add_typer(export.app)`（注册 export 组，1-2 行） |
| MODIFY | `backend/pyproject.toml` | **仅当 Q2 选 A（ebooklib/python-docx）**：dependencies 增加 + uv.lock 更新（ADR-025）；B/C 零改动 |
| MODIFY | `.github/workflows/ci.yml` | 两处联动（陷阱 13/15，2026-08-09 核实）：① `tests/cli/test_cli_export.py` 显式追加 **integration-cli-backend** job 文件列表（Windows pytest 不展开 glob）② `tests/api/test_export_api.py` 显式追加 **integration-project-backend** job 文件列表（API 测试按模块显式列出，既有先例 `../tests/api/test_project_api.py`）；coverage-backend 跑 `../tests/api/` 目录自动覆盖，无需追加 |

> ⚠️ 文件清单反向核对（F32 评审教训）：上表每个 CREATE 已核实不存在（2026-08-09），每个 MODIFY 已确认存在；ci.yml 联动已按真实 job 结构写明（integration-cli-backend + integration-project-backend 显式列表）。

### 8.2 注入依赖（ExportService 构造签名）

零跨模块 MODIFY 的关键：全部注入**既有 Protocol**（F15 §5.5 先例——不建自有补充端口，因为所需方法全部已存在，见下方清单）：

```python
class ExportService:
    def __init__(
        self,
        project_repo: ProjectRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        character_repo: CharacterRepositoryProtocol,
        world_repo: WorldRepositoryProtocol,
        outline_repo: OutlineRepositoryProtocol,
        timeline_repo: TimelineRepositoryProtocol,
        foreshadowing_repo: ForeshadowingRepositoryProtocol,
    ) -> None: ...
```

只读方法使用清单（已对照真实实现核实存在）：

| 数据源 | 方法 | 备注 |
|--------|------|------|
| project | `get(project_id)` | 404 校验 + meta |
| chapter | `list_volumes(project_id)` / `list_chapters(project_id, volume_id=None, status=None, offset=0, limit=50)` | 卷 + 章。⚠️ **分页陷阱**：`list_chapters` 默认 `limit=50`（2026-08-09 源码核实），导出必须循环分页拉全（`while len < total`）或传足够大 limit——**绝不默认 50 条静默丢章**（M1 验收兜底） |
| character | `list(project_id, search=None, group_id=None, sort_by=..., offset=0, limit=50)` | 默认排除软删 ✓（docstring 核实 2026-08-09）。⚠️ **同分页陷阱**：limit=50 需循环分页 |
| world | `list(project_id, ...)` | 同上（默认排除软删 ✓ + 分页陷阱） |
| outline | `list(project_id, ...)` / `list_points(outline_id)` | 大纲默认排除软删 ✓ + 分页陷阱；情节点 `list_points` 无分页参数（全量） |
| timeline | `list_all(project_id)` | F12 全量读取（无分页参数），软删行为以实现为准 |
| foreshadowing | `list(project_id, ...)` | 默认排除软删 ✓（docstring 核实）+ 分页陷阱 |

> ⚠️ 各 repo `list` 是否默认排除软删**以实现为准**：2026-08-09 源码核实——character/world/outline/foreshadowing 的 `list` docstring 明确「不含已软删除」✓，但 `ChapterRepository.list_chapters` 的 WHERE **不含 `is_deleted` 过滤**（需服务层显式过滤）；**全部 `list` 默认 `limit=50`，聚合必须循环分页拉全**（§8.2 表格逐行标注）——测试覆盖软删排除 + 分页拉全。

---

## 9. 测试策略

沿用 ADR-018 三层目录 + pytest markers；本模块无 LLM → 无模型下载约束，全部门禁内可跑。

### 9.1 测试层次

| 层 | 文件 | 内容 |
|----|------|------|
| 单元 | `tests/unit/test_exporters_*.py` | **序列化器纯函数**：给定 BookDocument fixture → 断言结构（MD/TXT 字符串、EPUB/DOCX zip 条目 + XML 内容）；确定性（两次调用字节相同，zip 时间戳固定） |
| 单元 | `tests/unit/test_output_service.py` | 聚合编排：mock 7 个 repo → 断言 BookDocument 组装（排序/软删排除/include_settings 分支） |
| API | `tests/api/test_export_api.py` | TestClient：200 下载（Content-Type/Content-Disposition 头 + 字节非空）、404 项目不存在、422 非法 format、token 中间件生效（F19 契约） |
| CLI | `tests/cli/test_cli_export.py` | CliRunner：写文件成功（字节落盘 + 信封）、`--json`、404 错误、目录 vs 文件路径语义 |

### 9.2 关键场景

1. **确定性快照**：同一 fixture 两次 `to_epub` 字节完全相同（zip 时间戳用 updated_at 固定——§5.6）
2. **XML 转义**：章节正文含 `& < > "` → EPUB/DOCX 解析后内容一致（E3）
3. **软删排除**：软删角色/卷/章不出现（§8.2 注）
4. **未分组章**：volume_id=None 的章进入「未分组」卷且排最后（§6.1）
5. **include_settings 分支**：false → settings 空列表；true → 5 类齐全且按 §6.3 摘要拼接
6. **空项目**：E2 行为（200 空文档）
7. **文件名清洗**：非法字符 → `_`、超长截断（E5/E7）

### 9.3 覆盖率

模块 ≥80%（ADR-027 口径：全仓 98.5/95.0 门禁下新模块测试齐全——序列化器纯函数易达 100% 分支；聚合编排 mock 全覆盖）。**注意 coverage-backend 合并口径**（F24 教训：新 CLI 测试覆盖不足会拖低全仓线，测试文件要写足）。

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| 导入/还原（导出文件 → 项目） | 未来模块（Issue 未立项）。导出是单向带走，导入涉及实体重建 + id 映射，独立设计 |
| PDF 导出 | YAGNI：排版引擎（weasyprint/reportlab）重量级 + 中文 PDF 字体配置复杂；需求方无明确场景（PRD 未列） |
| 批量/定时/多项目导出 | 无场景（F25 教训：无「无人值守导出」需求）；CLI 循环可自行实现 |
| 导出历史记录/审计表 | YAGNI：导出是纯计算，不落库（F15 AuditReport 瞬态先例） |
| EPUB 内嵌封面图/字体/复杂排版 | 最小实现（文本 + 结构）；图片素材管理是 #174 世界观地图的未来职责 |
| Markdown → HTML 渲染 | 序列化是文本输出；渲染是消费端职责 |
| 压缩打包（zip 多格式合集） | YAGNI：单格式单文件即满足备份/分享 |
| GUI 导出按钮 | 前端接线（消费本 API），归 GUI 演进 issue |
| F20 MCP export 工具 | MCP 1.0.0 时经 API 复用本能力，不另建 |

---

## 11. 依赖关系

### 依赖（本模块需要）

| 模块 | 依赖类型 | 用途 |
|------|----------|------|
| F1 Project | 硬依赖 | 项目校验 + meta |
| F2 Chapter | 硬依赖 | 卷/章正文树 |
| F9 Character | 条件依赖（include_settings=true 时） | 角色附录 |
| F10 World | 条件依赖 | 世界观附录 |
| F11 Outline | 条件依赖 | 大纲附录 |
| F12 Timeline | 条件依赖 | 时间线附录 |
| F13 Foreshadowing | 条件依赖 | 伏笔附录 |
| F19 #77 | 硬依赖 | token 中间件（API 端点受保护，F19 契约） |
| F7 CLI | 硬依赖 | `--json` 信封/退出码约定 |

### 被依赖（谁依赖本模块）

| 消费方 | 方式 |
|--------|------|
| GUI（未来接线） | GET /api/v1/projects/{pid}/export 下载 |
| F20 MCP（1.0.0） | export 工具复用 service/API |
| 外部生态 | CLI 导出（备份/分享/发布） |

### 编号口径声明

旧文档中指向导出服务的「F21」编号在 ADR-019 后仍为 F21（0.6.0 立项未改号）；本 spec §1 变体编号声明依据 AGENTS.md 模块类型谱系（F30=13 / F32=14 → 本模块第 15 变体），如与 ADR-019 v5+ 冲突以后者为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| D1 | 统一中间表示 BookDocument | 聚合层产出单一文档树，序列化器只消费它 | 格式差异与数据源解耦；新增格式只写序列化器；序列化器可纯函数单测（§2.2/§5.1） | 每格式独立读 DB（各序列化器重复聚合逻辑 + 测试要 mock DB）；直接序列化领域实体（内部状态泄漏 + 耦合） |
| D2 | 零新实体表 | 不建导出记录/任务表 | YAGNI：导出是纯计算无状态；F15 AuditReport 瞬态先例 | 导出任务表（进度/历史）——无异步长任务场景 |
| D3 | 附录平铺摘要，不做层级重建 | 角色分组/伏笔-事件关联不重建 | 导出是快照不是导航；重建增加复杂度且与 UI 树重复（#173 世界观树是未来职责） | 镜像完整实体图（过度设计） |
| D4 | EPUB 正文不做 Markdown 渲染 | 正文原样文本化（`<p>` 分段） | Markdown 渲染引入解析器 + 渲染器依赖；作者正文未必是合法 MD；「原样带走」是导出基线 | 引入 markdown 库渲染（依赖 + 语义转换风险） |
| D5 | API 一次性返回 Response（非流式） | 字节内存组装 | 导出产物一次成型（快照），无流式必要；流式增加复杂度（F23 是 LLM 逐 token 场景，此处不适用） | StreamingResponse（无收益） |
| D6 | 序列化器放 `domain/services/_exporters/` | 内部包不进 ports | 与 `_style_analyzer.py`/`_word_count.py` 先例一致：确定性纯函数工具放 services 私有模块 | 独立 infrastructure 包（过度分层） |
| D7 | API 路径 `/export` 挂在项目下 | `GET /api/v1/projects/{pid}/export` | 资源语义：导出是项目的一个视图；与既有 `/projects/{pid}/...` 风格一致 | `/api/v1/export?project_id=`（顶层动作，破坏资源嵌套惯例） |

---

## 13. 验收标准

> 状态行：M1-Mn 为里程碑顺序；「自动化载体」列：单元/API/CLI/手动。

| # | 验收标准 | 自动化载体 | 验证命令（backend 目录，uv run） |
|---|----------|------------|-------------------------------|
| M1 | `inkflow export <项目> -f markdown` 产出正确 Markdown（书名/卷/章/正文结构） | CLI | `pytest ../tests/cli/test_cli_export.py`（+ 手工跑命令） |
| M2 | `-f txt` 产出纯文本（卷内章编号 + 分隔线） | CLI | `pytest ../tests/cli/test_cli_export.py` |
| M3 | `-f epub` 产出合法 EPUB3（zip 条目 mimetype/container.xml/content.opf/toc.ncx + 章节 xhtml） | 单元 | `pytest tests/unit/test_exporters_epub.py` |
| M4 | `-f docx` 产出合法 DOCX（zip 条目 + document.xml 可解析） | 单元 | `pytest tests/unit/test_exporters_docx.py` |
| M5 | `--include-settings` 含 5 类设定档案附录；缺省不含 | 单元+CLI | `pytest tests/unit/test_output_service_export.py tests/unit/test_exporters_markdown.py` |
| M6 | API `GET /api/v1/projects/{pid}/export?format=markdown` 200 + 正确 Content-Type/Content-Disposition；404 项目不存在；422 非法 format | API | `pytest ../tests/api/test_export_api.py` |
| M7 | 确定性：同项目同参数两次导出字节相同 | 单元 | `pytest tests/unit/test_exporters_epub.py -k deterministic` |
| M8 | 软删内容不导出（卷/章/角色/世界观/大纲/时间线/伏笔） | 单元 | `pytest tests/unit/test_output_service.py -k deleted` |
| M9 | 空项目导出 200 空文档（不报错） | API+CLI | `pytest tests/unit/test_output_service_export.py` |
| M10 | 全量门禁：lint/unit/integration/api/cli 绿 + 覆盖率达标 | CI | `uv run ruff check src/ tests/unit/ ../tests/` + 全量 pytest |
| M11 | 手工闭环：CLI 导出 4 格式 → EPUB 用阅读器（Calibre/Edge）/ DOCX 用 Word 打开验证可读 | 手动 | 发布前冒烟（rc 门禁复用，f19-packaging 先例） |

> Issue #53 验收标准映射：EPUB 导出=M3/M11 · Markdown/TXT=M1/M2 · DOCX=M4/M11 · ≥3 种格式=M1-M4 全绿即满足（若 Q1 拍板 3 格式则对应子集）。

---

## 待澄清问题（评审时确认）

| # | 问题 | 选项 | 建议 |
|---|------|------|------|
| Q1 | **导出格式集**：Issue 验收列了 4 种（EPUB/Markdown/TXT/DOCX），PRD 要求 ≥3 种。4 种全做还是 MVP 3 种？ | A. 4 种全做（满足验收全项）<br>B. 3 种 MVP（Markdown/TXT/EPUB，DOCX 延后到后续版本）<br>C. 4 种但 DOCX 最小实现（无样式/表格） | **A**：DOCX 最小实现成本可控（§5.5 已给出 OOXML 骨架），4 种全做一步到位满足 Issue 验收；Q2 若选库则成本更低 |
| Q2 | **依赖库选型**：EPUB/DOCX 用成熟库还是标准库手写？（影响体积/锁定/打包） | A. ebooklib + python-docx（成熟稳定，+lxml 依赖链，PyInstaller 打包需 hiddenimports 跟进）<br>B. 纯标准库手写（zipfile + xml.etree，零新依赖，EPUB3/OOXML 最小实现自管）<br>C. 混合：EPUB 手写 + DOCX 用 python-docx | **B**：项目体积敏感（#48 瘦身先例）+ ADR-025 依赖供应链加固 + 导出是单向文本输出，标准库完全可承担；lxml 是 C 扩展（打包 + 平台差异成本）；EPUB3/DOCX 最小实现规范公开，测试断言结构即可 |
| Q3 | **导出内容范围**：是否含设定档案附录？ | A. 仅正文（卷/章）<br>B. 正文 + 设定档案固定包含<br>C. `include_settings` 参数可切换（默认不含） | **C**：备份/分享/发布三场景需求不同（发布不要附录，备份要）；参数切换成本低（聚合器已有注入），默认不含保持「导出=作品」的干净语义 |
