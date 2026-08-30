# F21: 导出服务（output_service）— 功能规格
> **端**: cross

> **Spec 版本**: 1.3 | **日期**: 2026-08-09 | **依据**: PRD v2.2 §6.4 P1-15, Issue #53, Constitution P1-P6（P2 解耦 / P5 YAGNI）
> **所属阶段**: 0.6.0（#53 导出服务，估算 1.5-2 人天——v1.1 拍板范围收敛）
>
> **Spec 变更（v1.2 → v1.3）**: **评审修复吸收（2026-08-09，评审 PASS with minor 后父侧修订）**——① §3.3 异常映射表措辞漂移修正（404「项目不存在」/500「内部错误: <e>」，与实现/F15 audit 先例/ADR-012 中文文案一致）；② §6.1 卷排序键修正（`order_index ASC` 仅——`Volume` 实体无 `created_at` 字段）；③ §5.1 要点 2「asyncio.gather 并行拉取」在实现中落实（B4 修复批），正文与设定聚合并行、设定 5 源并行，include_settings=False 零调用契约不变。
> **Spec 变更（v1.1 → v1.2）**: **实现期父侧裁定（2026-08-09）**——CLI 传输路径改为**恒经 HTTP**（`ensure_kernel()` + `InkFlowHTTPClient.get_raw` 下载，F38 #169 全仓改造后的一致模式；v1.1 的「直接消费 service 不经 HTTP」是未同步 F38 的陈旧措辞，§4/§8.1/§12 D 表修订）；CLI 信封按 F7 实际契约 `{"ok": ...}`（v1.1 示例 success 键为过时措辞，§4 修订）；人类模式成功文案码点锁定为 `✅ 导出成功: {name} → {path} ({bytes:,} bytes)`（§4 修订）。
> **Spec 变更（v1.0 → v1.1）**: **用户拍板（2026-08-09）**——Q1=A 仅 TXT 格式（国内网文发布生态 TXT 为主流，EPUB/Markdown/DOCX 无发布场景，YAGNI 收敛）；Q2 自解（TXT 纯文本零依赖，不引入任何导出库）；Q3=C `include_settings` 参数切换（默认不含）。§1/§2/§3/§4/§5/§7/§8/§9/§10/§12/§13 全面修订为单格式管线；Issue #53 验收标准同步（gh comment 留痕 2026-08-09）。
>
> **关联 Issues**: [#53](https://github.com/zhx-xi/InkFlow/issues/53)
> **依赖**: ✅ F1（项目校验 + Project 读取）· ✅ F2（卷/章读取）· ✅ F9（角色档案读取）· ✅ F10（世界观条目读取）· ✅ F11（大纲/情节点读取）· ✅ F12（时间线事件读取）· ✅ F13（伏笔档案读取）· ✅ F19 #77（token 中间件：导出端点同样受保护）· ⏳ 无
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md)（模块化单体）· [ADR-002](../../adr/ADR-002.md)（六边形分层）· [ADR-003](../../adr/ADR-003.md)（Repository）· [ADR-004](../../adr/ADR-004.md)（Pydantic v2）· [ADR-012](../../adr/ADR-012.md)（错误处理）· [ADR-018](../../adr/ADR-018.md)（测试分层）· [ADR-019](../../adr/ADR-019.md)（版本里程碑 + 模块编号口径）· [ADR-021](../../adr/ADR-021.md)（内核进程化：token 契约）· [ADR-025](../../adr/ADR-025.md)（依赖锁定：本模块零新增依赖）· [ADR-027](../../adr/ADR-027.md)（覆盖率门禁）
> **状态**: ✅ 已实现（PR #214，#53 2026-08-09）

---

## 1. 概述

提供**项目内容导出**能力：把项目内的正文（卷/章）与设定档案（角色/世界观/大纲/时间线/伏笔）聚合为统一中间表示（BookDocument），再序列化为 **TXT** 纯文本（UTF-8），供作者**备份、分享、发布**到外部平台。

**核心价值**: 创作数据不锁定在 InkFlow 内——作者可以随时把作品带走（发布到网文平台、给编辑审稿、本地归档），这是「本地完全可用」的最后一环（ADR-019 v5：1.0.0 = CLI+GUI+skills+MCP 四界面齐备，导出是 CLI/API 的天然交付物）。

**v1.1 范围收敛（用户拍板）**: v1.0 设计为 EPUB/Markdown/TXT/DOCX 四格式，评审拍板后**收敛为仅 TXT**——理由：国内网文发布生态（起点/番茄/晋江等上传通道）TXT 为绝对主流，作者「导出」主场景是**把书带走发布**；EPUB/DOCX 是出版向格式，对网文作者无发布场景（YAGNI）；Markdown 无消费端。备份/审稿场景 TXT + 设定附录（`include_settings`）完整覆盖。**后续若出现出版/电子书需求，格式扩展是序列化器层增量**（§5.5 注），不推倒管线。

**变体定位（第 15 变体「导出聚合型」）**: 本模块是 **F15 横切只读聚合模式 × F12 确定性算法模式**的产物变体——它像 F15 一样只读聚合多模块档案（零跨模块 MODIFY，F15 先例 §5.5），但输出不是审计报告而是**可交付文件字节**；它像 F12 一样无 LLM、纯确定性（同一项目 → 同一字节流，快照可测）。编号依据 AGENTS.md 模块类型谱系（F30=第 13 变体 / F32=第 14 变体，F21/F22 立项于 0.6.0，编号按 ADR-019 口径，冲突以 ADR-019 v5+ 为准）。

```
输入: 项目各模块档案（DB） ──只读聚合──▶ BookDocument（统一中间表示）
                                        ──TXT 序列化器──▶ UTF-8 纯文本
                                        （纯函数，无状态）
```

**边界声明**:
- F21 只做**导出（读 + 序列化）**，不做**导入**（导入/还原归未来模块，见 §10）
- F21 不新建实体表、无数据库迁移（schema 由 `Base.metadata.create_all` 管理，本模块零新表）
- F21 不含 **EPUB/Markdown/DOCX/PDF**（v1.1 拍板：无发布场景，见 §10）
- F21 是**纯后端能力**：API 端点（下载）+ CLI（写文件）；GUI 导出按钮消费 API，属前端接线不在本 spec 范围
- F21 不修改任何既有模块的 Repository/Service（零跨模块 MODIFY，读取全部走既有只读方法，见 §8）

---

## 2. 数据模型

遵循本项目「领域 Pydantic 实体 + DTO」模式（ADR-004），但 F21 **不新建持久化实体**——所有输入来自既有模块实体（F1 Project / F2 Volume+Chapter / F9 Character / F10 WorldSetting / F11 Outline+PlotPoint / F12 TimelineEvent / F13 Foreshadowing，字段见各模块 spec，本 spec 不重复定义）。F21 新增的是**传输/中间表示 DTO**，均为瞬态计算产物。

### 2.1 ExportFormat（导出格式枚举）

v1.1 单值枚举（保留枚举类型为未来格式扩展留点，YAGNI 但零成本）：

```python
class ExportFormat(StrEnum):
    """导出格式（v1.1 拍板：仅 TXT）。"""
    TXT = "txt"
    # 未来扩展（当前无场景，YAGNI）：EPUB/Markdown/DOCX
```

### 2.2 BookDocument（统一中间表示，瞬态）

导出管线第一步把各模块实体聚合为**单一文档树**，序列化器只消费它——聚合逻辑与文本拼装解耦（聚合可独立测试、格式扩展只需加序列化器）。

```python
class BookMeta(BaseModel):
    """项目元信息（导出文件头部使用）。"""
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
    format: ExportFormat = ExportFormat.TXT   # v1.1 唯一值 txt
    include_settings: bool = False            # 是否含设定档案附录（Q3=C 拍板）

class ExportResult(BaseModel):
    """CLI --json 信封的 payload（API 直接返回字节流，不用此模型）。"""
    format: ExportFormat
    filename: str        # 建议文件名（含 .txt 扩展名）
    bytes: int           # 字节数
    path: str            # CLI 实际写入路径（API 侧为空）
```

> **决策论证表**：中间表示选「树 + 平铺附录」而非「完整镜像各模块模型」——导出只消费展示级字段（标题/正文/名称/内容），镜像完整实体会把 `status_history`、`extra`、`is_deleted` 等内部状态带进交付物，且任一模块加字段都迫使本模块跟进（耦合）。「平铺附录」不做角色分组/伏笔-事件关联的层级重建（YAGNI：导出是快照不是导航，见 §12 D3）。v1.1 保留 BookDocument（不因单格式退化）——聚合与拼装解耦 + 未来格式扩展的接缝。

---

## 3. API 契约

### 3.1 端点总览（1 个，GET 下载）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/projects/{project_id}/export` | 导出项目 TXT（query 参数见下） |

- query：`format`（可选，v1.1 仅接受 `txt`，缺省 `txt`——保留参数为未来扩展）、`include_settings`（可选，默认 `false`）
- 响应：**200 文本流**（`Content-Type: text/plain; charset=utf-8`）+ `Content-Disposition: attachment; filename="<书名>-txt.txt"`（文件名 URL 编码，防中文/空格破坏头）
- 实现：FastAPI `Response`（字节已在内存，无需 StreamingResponse——导出产物一次性组装；见 §12 D5）
- 幂等：GET 只读、无副作用；同一参数重复调用产出相同字节（确定性，§5.5）

### 3.2 请求/响应示例

```http
GET /api/v1/projects/1/export?include_settings=true
→ 200
Content-Type: text/plain; charset=utf-8
Content-Disposition: attachment; filename="mybook-txt.txt"

我的小说
================================

第一卷：序章
--------------------------------

第 1 章 开端

（正文……）

================================

附录：设定档案

【角色】李青焰
性格：……
```

### 3.3 异常映射表

| 场景 | HTTP 状态 | 错误 body（ADR-012 统一格式） | 抛出/捕获点 |
|------|-----------|-------------------------------|-------------|
| 项目不存在 / 已软删 | 404 | `{"detail": "项目不存在"}`（v1.3 修订：与实现/F15 audit 先例/ADR-012 中文文案一致，v1.1 表格的英文 "Project not found" 为漂移措辞） | service 校验（复用 F9 character_errors `ProjectNotFoundError`，陷阱 16：**不导出**到 `ports/__init__.py`，router 显式 except 映射） |
| `format` 非 txt（v1.1 不支持的其他值） | 422 | Pydantic `Literal["txt"]` 校验错误 | DTO 层（FastAPI 自动） |
| `include_settings` 非法 | 422 | Pydantic 校验错误 | DTO 层 |
| 项目存在但无任何内容 | 200 | 空文档（标题 + 空正文，见 §7 E4） | 不视为错误 |
| 内部错误（序列化异常） | 500 | `{"detail": "内部错误: <e>"}`（v1.3 修订：与实现/F15 audit 先例/ADR-012 一致，v1.1 表格的英文 "Internal server error" 为漂移措辞） | router `except Exception` → loguru（ADR-016） |

---

## 4. CLI 命令签名

F7 全局约定：`--json` 信封（`{"ok": true, "data": ..., "error": ...}`——v1.2 按 F7 实际契约修订，v1.1 示例的 success 键为过时措辞）、退出码 0 成功 / 1 业务错误 / 2 用法错误。F21 新增 `inkflow export` 组（1 个命令，**恒经 HTTP**：`ensure_kernel()` + `InkFlowHTTPClient`，F38 #169 全仓一致模式——v1.2 实现期父侧裁定，见 §12 D10）。CLI 经 `InkFlowHTTPClient.get_raw` 下载 TXT 原始文本（`infrastructure/http/client.py` 新增方法，§8.1），不经 HTTP 打自己的服务层直连已随 #169 废弃。

```text
inkflow export <project> [--include-settings] [--output PATH]

参数:
  project                 项目名称或 ID（F1 约定：名称精确匹配，数字按 ID 解析——
                          CLI 先经 GET /projects?search=<name> 精确匹配名称取 id；
                          数字/UUID 直通 GET /projects/{pid} 取项目对象）
  --include-settings      包含设定档案附录（默认不含）
  --output, -o            输出路径。目录 → 用建议文件名写入；文件路径 → 直接写入。
                          默认当前工作目录 + 建议文件名
  --json                  输出 JSON 信封

成功: 退出 0；信封 data = ExportResult {format, filename, bytes, path}
失败: 项目不存在 → 退出 1，error = "项目不存在: <name>"
      写文件失败（权限/磁盘）→ 退出 1，error = "写文件失败: <系统错误>"
```

示例：

```text
$ inkflow export 我的书 -o ./out/
✅ 导出成功: 我的书 → ./out/我的书-txt.txt (1,234,567 bytes)

$ inkflow export 我的书 --include-settings --json
{"ok": true, "data": {"format": "txt", "filename": "我的书-txt.txt", "bytes": 2048, "path": "我的书-txt.txt"}}
```

> v1.1 移除 `--format` 选项（唯一格式 txt，选项无意义）；未来格式扩展时恢复 `-f/--format`（§5.5 注）。v1.2 修订：人类模式成功文案码点锁定 `✅ 导出成功: {name} → {path} ({bytes:,} bytes)`（✅ U+2705 无变体、ASCII 冒号、箭头 U+2192、bytes 千分位逗号）。

---

## 5. 导出管线模式（关键差异：聚合 + 确定性序列化）

> ⚠️ **本节是 F21 与既有样板的核心差异点**：F9/F10 §5 是「AI 提取管线」，F12 §5 是「一致性检查算法」，F15 §5 是「审计规则引擎」；本模块的 §5 是**「只读聚合 → 中间表示 → TXT 序列化」三阶段管线**——无 LLM、无模板、无重试，纯确定性。

### 5.1 模式总览

```text
 ┌─────────────────────────────────────────────────────────────────┐
 │ ExportService.export(project_id, include_settings)               │
 └──────────────────────────┬──────────────────────────────────────┘
                            ▼
 ① 校验项目存在（F1 ProjectRepository.get）→ ProjectNotFoundError(404)
 ② 聚合正文树（只读，全部并行拉取）:
    - ProjectRepository.get                       → meta
    - ChapterRepository.list_volumes(pid)         → volumes 骨架
    - ChapterRepository.list_chapters(pid, 循环分页拉全) → 每卷 chapters
      （排除 is_deleted；volume_id=None → 「未分组」卷；⚠️ 分页陷阱见 §8.2）
 ③ 若 include_settings: 聚合附录（只读，并行）:
    - CharacterRepository.list(pid, 循环分页)     → character 条目
    - WorldRepository.list(pid)                   → world 条目
    - OutlineRepository.list(pid) + list_points   → outline 条目
    - TimelineRepository.list_all(pid)            → timeline 条目
    - ForeshadowingRepository.list(pid)           → foreshadowing 条目
 ④ 组装 BookDocument（统一中间表示，§2.2）
 ⑤ TXT 序列化: _txt_exporter.to_txt(book) -> str（纯函数，§5.3）
 ⑥ 返回 ExportResult（API: Response 字节流；CLI: 写文件 + 信封）
```

**模式要点**:
1. **只读聚合**：全部走既有 Repository Protocol 只读方法（方法名见 §8.2），零跨模块 MODIFY（F15 §5.5 先例）
2. **并行拉取**：正文/附录各数据源相互独立，`asyncio.gather` 并行
3. **确定性**：同一项目 + 同一参数 → 同一字节流（所有排序键稳定，§6.1；无时间戳/随机量入文件）
4. **无副作用**：导出不修改任何数据；字节流内存组装，不落临时文件（API 场景）；CLI 落盘是用户显式行为
5. **可独立测试**：给 BookDocument fixture → 断言文本结构，不依赖 DB

### 5.2 聚合与分页（v1.1 保留完整细节——load-bearing）

- **循环分页拉全**：`list_chapters` 默认 `limit=50`（2026-08-09 源码核实），导出必须循环分页（`while len(chapters) < total`）——**绝不默认 50 条静默丢章**（M1 验收兜底）；character/world/outline/foreshadowing 的 `list` 同样默认 limit=50
- **软删过滤**：`list_chapters` WHERE **不含 is_deleted**（2026-08-09 源码核实），service 聚合层显式过滤；character/world/outline/foreshadowing 的 `list` docstring 确认默认排除软删 ✓

### 5.3 TXT 序列化器（_txt_exporter）

零依赖，纯文本（UTF-8）：

```text
{书名}
{分隔线：= 重复 30 个}

第 {N} 卷 {volume.title}
{分隔线：- 重复 30 个}

第 {M} 章 {chapter.title}

{chapter.content}

（附录，include_settings=true 时）---

附录：设定档案

【角色】
{name}
{personality / background / goals 摘要}

【世界观】/【大纲】/【时间线】/【伏笔】
（同构分节）
```

- 章节编号 = **卷内序号 + 卷前缀**（「第 1 卷 · 第 3 章」），符合中文网文惯例；TXT 单卷（无卷）项目退化为「第 N 章」
- 正文原样保留（不转义、不清理）
- 文件名：`{书名}-txt.txt`（非法字符清洗见 §7 E5）
- `ExportFormat.TXT` 是唯一格式；序列化器签名 `to_txt(book: BookDocument) -> str`（未来加格式 = 加同签名函数，§12 D1）

### 5.4 确定性声明

| 输入 | 输出 |
|------|------|
| 同一项目 + 同一参数 | 同一字节流（无时间戳/随机量；updated_at 仅入 meta 展示行） |

### 5.5 格式扩展接缝（v1.1 保留）

未来若出现出版/电子书需求：新增 `to_epub/to_markdown/to_docx` 同签名函数 + `ExportFormat` 加枚举值 + API `format` 参数放开 Literal——**聚合器/BookDocument/API/CLI 骨架零改动**（CLI 恢复 `-f` 选项一行）。当前 YAGNI，不预建。

### 5.6 导出聚合型 vs 既有样板：差异对照表

| 维度 | F12 一致性检查 | F15 审计 | **F21 导出** |
|------|---------------|----------|--------------|
| 数据源 | 单模块（时间线） | 4+ 模块只读聚合 | 7 模块只读聚合（正文 2 + 附录 5） |
| 输出 | 内存报告 | 内存报告 | **TXT 文本流（v1.1 单格式）** |
| 新实体表 | 无 | 无（AuditReport 瞬态） | **无（BookDocument 瞬态）** |
| 新 API | 8 端点 CRUD | 1 只读端点 | **1 下载端点** |
| 新 CLI | timeline 组 | audit 组 | **export 组** |
| 算法性质 | 相邻对扫描 | 规则引擎 | **聚合 + 文本序列化** |
| 跨模块 MODIFY | 无 | 无（audit_repo 补充端口） | **无（全走既有只读方法）** |
| LLM | 无 | 无 | **无** |

---

## 6. 导出内容组织规则

### 6.1 排序键（确定性第一原则）

| 层级 | 排序键 | 说明 |
|------|--------|------|
| 卷 | `order_index ASC`（v1.3 修订：`Volume` 实体无 `created_at` 字段——F2 卷仅 title/order_index，repo `list_volumes` 已按 order_index 升序，stable sort 保序） | F2 语义 |
| 章（卷内） | `order_index ASC, created_at ASC` | F2 语义 |
| 未分组章 | 单独「未分组」卷，排在所有命名卷之后 | `volume_id IS NULL` |
| 附录-角色 | `created_at ASC`（稳定 ASCII 键；**不用 name 排序**——中文码点序与直觉不符，F15 教训） |
| 附录-世界观 | 同上 | |
| 附录-大纲 | outline `sort_order ASC, created_at ASC`；其 PlotPoint 按 `position ASC` | |
| 附录-时间线 | `narrative_position ASC, created_at ASC` | F12 叙事序 |
| 附录-伏笔 | `created_at ASC` | |

### 6.2 章编号显示

- 卷内「第 N 章」（N = 卷内序号从 1 计数），卷前缀「第 X 卷」；无卷项目省略卷前缀
- 卷标题为空时用「第 X 卷」占位（F2 卷 title 可空）

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
| E2 | 项目无卷无章 | 200：空文档（书名 + 附录如有）；不报错 |
| E3 | 章节正文含特殊字符 | TXT 原样保留（纯文本无转义需求——v1.1 单格式天然免疫 XML 转义问题） |
| E4 | 仅设定了无正文 | 同 E2：正文空 + 附录完整（include_settings=true 时） |
| E5 | 文件名非法字符（Windows：`\ / : * ? " < > |`） | 清洗为 `_`；文件名取书名前 60 字符（超长截断） |
| E6 | 正文超长（单章 MB 级） | 正常导出（字符串拼接，TXT 无结构上限） |
| E7 | 空书名 | 书名占位 `untitled` |
| E8 | CLI 输出路径为已存在文件 | 直接覆盖（CLI 语义，不做确认——导出是低风险操作） |
| E9 | 并行拉取单源失败（DB 异常） | 整体 500（无部分导出——导出是原子快照，不接受半成品；loguru 记录） |
| E10 | `format` 传非 txt（v1.1） | 422（Pydantic Literal） |
| E11 | 导出期间数据变更 | 快照语义：以聚合时刻数据为准，不保证与导出完成后数据一致（无锁，单用户本地场景可接受，§12 D5） |

---

## 8. 文件结构

### 8.1 CREATE/MODIFY 清单（对照真实源码树 `backend/src/inkflow/`）

| 类型 | 路径 | 说明 |
|------|------|------|
| CREATE | `domain/models/output.py` | ExportFormat（单值 txt）/ BookMeta / BookChapter / BookVolume / BookSetting / BookDocument / ExportRequest / ExportResult（§2） |
| CREATE | `domain/services/output_service.py` | ExportService：聚合编排（§5.1 ①-④⑥） |
| CREATE | `domain/services/_txt_exporter.py` | `to_txt(book) -> str`（§5.3）——`_word_count.py`/`_style_analyzer.py` 先例（v1.1 由 `_exporters/` 包收敛为单文件，单一格式无包必要） |
| CREATE | `domain/services/_export_filename.py` | `suggest_filename(title, fmt)`（§7 E5/E7） |
| CREATE | `api/routers/export.py` | GET `/api/v1/projects/{pid}/export`（§3） |
| CREATE | `cli/commands/export.py` | `inkflow export` 组（§4） |
| CREATE | `backend/tests/unit/test_output_models.py` | DTO/枚举测试（§9） |
| CREATE | `backend/tests/unit/test_output_service.py` | 聚合编排测试（§9） |
| CREATE | `backend/tests/unit/test_txt_exporter.py` | TXT 序列化器（结构/编号/附录/确定性） |
| CREATE | `backend/tests/unit/test_output_service_export.py` | 全管线集成（mock repos → 文本非空 + 结构嗅探） |
| CREATE | `tests/cli/test_cli_export.py` | CLI 测试（仓库根 `tests/cli/`，Issue #61 约定；**新文件必须显式追加 integration-cli-backend job**——陷阱 13/15） |
| CREATE | `tests/api/test_export_api.py` | API 端点测试（仓库根 `tests/api/`，F32 先例 `test_settings_api.py` 同处） |
| MODIFY | `api/app.py` | `app.include_router(export.router)` + import（1 行） |
| MODIFY | `api/deps.py` | ExportService 装配（注入 7 个 repository；见 §8.2） |
| MODIFY | `cli/app.py` | import + `app.add_typer(export.app)`（注册 export 组，1-2 行） |
| MODIFY | `infrastructure/http/client.py` | `InkFlowHTTPClient.get_raw(path, *, params=None) -> str`（v1.2 新增：原始文本下载，F21 CLI 消费；`_request` 强制 JSON 解析无法处理 text/plain） |
| MODIFY | `.github/workflows/ci.yml` | 两处联动（陷阱 13/15，2026-08-09 核实）：① `tests/cli/test_cli_export.py` 显式追加 **integration-cli-backend** job 文件列表（Windows pytest 不展开 glob）② `tests/api/test_export_api.py` 显式追加 **integration-project-backend** job 文件列表（既有先例 `../tests/api/test_project_api.py`）；coverage-backend 跑 `../tests/api/` 目录自动覆盖，无需追加 |

> ⚠️ 文件清单反向核对（F32 评审教训）：上表每个 CREATE 已核实不存在（2026-08-09），每个 MODIFY 已确认存在；ci.yml 联动已按真实 job 结构写明。**v1.1 删除** v1.0 的 `_exporters/` 包 4 序列化器 + 对应 4 测试文件（EPUB/DOCX/Markdown 无场景）。

### 8.2 注入依赖（ExportService 构造签名）

零跨模块 MODIFY 的关键：全部注入**既有 Protocol**（F15 §5.5 先例——不建自有补充端口，因为所需方法全部已存在）：

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

只读方法使用清单（已对照真实实现核实存在，2026-08-09）：

| 数据源 | 方法 | 备注 |
|--------|------|------|
| project | `get(project_id)` | 404 校验 + meta |
| chapter | `list_volumes(project_id)` / `list_chapters(project_id, volume_id=None, status=None, offset=0, limit=50)` | 卷 + 章。⚠️ **分页陷阱**：`list_chapters` 默认 `limit=50`（源码核实），导出必须循环分页拉全（`while len < total`）——**绝不默认 50 条静默丢章**（M1 验收兜底） |
| character | `list(project_id, search=None, group_id=None, sort_by=..., offset=0, limit=50)` | 默认排除软删 ✓（docstring 核实）。⚠️ **同分页陷阱**：limit=50 需循环分页 |
| world | `list(project_id, ...)` | 同上（默认排除软删 ✓ + 分页陷阱） |
| outline | `list(project_id, ...)` / `list_points(outline_id)` | 大纲默认排除软删 ✓ + 分页陷阱；情节点 `list_points` 无分页参数（全量） |
| timeline | `list_all(project_id)` | F12 全量读取（无分页参数），软删行为以实现为准 |
| foreshadowing | `list(project_id, ...)` | 默认排除软删 ✓（docstring 核实）+ 分页陷阱 |

> ⚠️ 软删语义（2026-08-09 源码核实）：character/world/outline/foreshadowing 的 `list` docstring 明确「不含已软删除」✓，但 `ChapterRepository.list_chapters` 的 WHERE **不含 `is_deleted` 过滤**（需服务层显式过滤）；**全部 `list` 默认 `limit=50`，聚合必须循环分页拉全**——测试覆盖软删排除 + 分页拉全。

---

## 9. 测试策略

沿用 ADR-018 三层目录 + pytest markers；本模块无 LLM → 无模型下载约束，全部门禁内可跑。

### 9.1 测试层次

| 层 | 文件 | 内容 |
|----|------|------|
| 单元 | `tests/unit/test_txt_exporter.py` | TXT 序列化器纯函数：给定 BookDocument fixture → 断言结构（书名/分隔线/卷章编号/附录分节） |
| 单元 | `tests/unit/test_output_service.py` | 聚合编排：mock 7 个 repo → 断言 BookDocument 组装（排序/软删排除/include_settings 分支/循环分页） |
| API | `tests/api/test_export_api.py` | TestClient：200 下载（Content-Type/Content-Disposition 头 + 文本非空）、404 项目不存在、422 非法 format、token 中间件生效（F19 契约） |
| CLI | `tests/cli/test_cli_export.py` | CliRunner：写文件成功（文本落盘 + 信封）、`--json`、404 错误、目录 vs 文件路径语义 |

### 9.2 关键场景

1. **确定性快照**：同一 fixture 两次 `to_txt` 文本完全相同
2. **循环分页**：mock `list_chapters` 返回 50 条 + total=120 → 断言聚合拉全 120（分页陷阱回归）
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
| EPUB / Markdown / DOCX 导出 | **v1.1 拍板（2026-08-09）**：国内网文发布生态 TXT 为主流，其余格式无发布场景（YAGNI）；未来出版需求走 §5.5 扩展接缝 |
| PDF 导出 | YAGNI：排版引擎（weasyprint/reportlab）重量级 + 中文 PDF 字体配置复杂；需求方无明确场景（PRD 未列） |
| 导入/还原（导出文件 → 项目） | 未来模块（Issue 未立项）。导出是单向带走，导入涉及实体重建 + id 映射，独立设计 |
| 批量/定时/多项目导出 | 无场景（F25 教训：无「无人值守导出」需求）；CLI 循环可自行实现 |
| 导出历史记录/审计表 | YAGNI：导出是纯计算，不落库（F15 AuditReport 瞬态先例） |
| 压缩打包（zip 多格式合集） | YAGNI：单 TXT 单文件即满足备份/分享 |
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
| D1 | 统一中间表示 BookDocument | 聚合层产出单一文档树，序列化器只消费它 | 聚合与拼装解耦；v1.1 单格式仍保留（格式扩展接缝 §5.5）；序列化器可纯函数单测（§2.2/§5.1） | 每格式独立读 DB（重复聚合逻辑）；直接序列化领域实体（内部状态泄漏） |
| D2 | 零新实体表 | 不建导出记录/任务表 | YAGNI：导出是纯计算无状态；F15 AuditReport 瞬态先例 | 导出任务表（无异步长任务场景） |
| D3 | 附录平铺摘要，不做层级重建 | 角色分组/伏笔-事件关联不重建 | 导出是快照不是导航；重建增加复杂度且与 UI 树重复 | 镜像完整实体图（过度设计） |
| D4 | **v1.1：仅 TXT 格式** | 单格式管线，ExportFormat 单值 | 用户拍板（2026-08-09）：国内网文发布生态 TXT 主流，EPUB/Markdown/DOCX 无发布场景（YAGNI）；备份/审稿场景 TXT + 附录覆盖 | v1.0 四格式（EPUB/DOCX 出版向，对网文作者无消费端；引入 lxml C 扩展依赖 + 打包成本，与 ADR-025 供应链加固、体积敏感（#48）冲突） |
| D5 | **v1.1：零新增依赖（TXT 纯文本）** | 标准库字符串拼接 | TXT 是纯文本 UTF-8，无库可引（ebooklib/python-docx 均为 EPUB/DOCX 而生，v1.1 无此需求）；uv.lock 零变更（ADR-025） | 引入 ebooklib/python-docx（lxml C 扩展：打包 hiddenimports + 体积 +10~20MB，为不存在的格式付成本） |
| D6 | API 一次性返回 Response（非流式） | 字节内存组装 | 导出产物一次成型（快照），无流式必要 | StreamingResponse（无收益） |
| D7 | 序列化器单文件 `_txt_exporter.py` | 私有模块不进 ports | v1.1 单格式，`_exporters/` 包无必要（Rule of Three：单一实现不建包）；与 `_word_count.py` 先例一致 | 独立包/独立 infrastructure 层（过度分层） |
| D8 | API 路径 `/export` 挂在项目下 | `GET /api/v1/projects/{pid}/export` | 资源语义：导出是项目的一个视图；与既有 `/projects/{pid}/...` 风格一致 | `/api/v1/export?project_id=`（顶层动作，破坏资源嵌套惯例） |
| D9 | `format` 参数保留（仅 txt） | API 接受 `format=txt`，CLI 无 `-f` | 为未来格式扩展留契约接缝（§5.5）零成本；CLI 单格式选项是噪音 | 完全删除 format 参数（未来扩展要改 API 契约）；CLI 保留 `-f`（单选项噪音） |
| D10 | **v1.2：CLI 恒经 HTTP（`ensure_kernel()` + `InkFlowHTTPClient.get_raw`）** | CLI 传输层与 F38 #169 全仓一致（`infrastructure/http/client.py` 新增 `get_raw(path, *, params=None) -> str` 原始文本下载） | v1.1 写「直接消费 service 不经 HTTP（F23 先例）」——但 F38 #169 已把全部 CLI 改为恒经 HTTP（豁免仅 serve/kernel status/config/llm），新命令绕过 HTTP 是架构倒退；导出端点返回 text/plain，`_request` 的 `response.json()` 无法解析，需 raw 下载方法；CLI 测试沿用 F38 mock 范式（test_cli_audit.py 同款） | 直连 service（#169 后无先例、测试范式自创、与 ADR-030 冲突）；CLI 复用 `_request` 传 text/plain（JSONDecodeError 必炸） |

---

## 13. 验收标准

> 状态行：M1-Mn 为里程碑顺序；「自动化载体」列：单元/API/CLI/手动。

| # | 验收标准 | 自动化载体 | 验证命令（backend 目录，uv run） |
|---|----------|------------|-------------------------------|
| M1 | `inkflow export <项目>` 产出 TXT（书名/分隔线/卷/章/正文结构），**>50 章项目不丢章（分页拉全）** | CLI+单元 | `pytest ../tests/cli/test_cli_export.py tests/unit/test_output_service.py`（+ 手工跑命令） |
| M2 | `--include-settings` 含 5 类设定档案附录；缺省不含 | 单元+CLI | `pytest tests/unit/test_txt_exporter.py tests/unit/test_output_service.py` |
| M3 | 确定性：同项目同参数两次导出字节相同 | 单元 | `pytest tests/unit/test_txt_exporter.py -k deterministic` |
| M4 | 软删内容不导出（卷/章/角色/世界观/大纲/时间线/伏笔） | 单元 | `pytest tests/unit/test_output_service.py -k deleted` |
| M5 | 未分组章进入「未分组」卷且排最后 | 单元 | `pytest tests/unit/test_output_service.py -k ungrouped` |
| M6 | 空项目导出 200 空文档（不报错） | API+CLI | `pytest tests/unit/test_output_service_export.py` |
| M7 | API `GET /api/v1/projects/{pid}/export` 200 + Content-Type/Content-Disposition；404 项目不存在；422 非 txt format | API | `pytest ../tests/api/test_export_api.py` |
| M8 | 文件名非法字符清洗 + 空书名占位 | 单元 | `pytest tests/unit/test_output_models.py -k filename` |
| M9 | 全量门禁：lint/unit/integration/api/cli 绿 + 覆盖率达标 | CI | `uv run ruff check src/ tests/unit/ ../tests/` + 全量 pytest |
| M10 | 手工闭环：CLI 导出 TXT → 记事本/网文平台打开验证可读（中文无乱码） | 手动 | 发布前冒烟（rc 门禁复用，f19-packaging 先例） |

> Issue #53 验收标准（v1.1 拍板同步 2026-08-09）：原「EPUB/Markdown/TXT/DOCX ≥3 种」修订为「TXT 导出（v1.1 用户拍板仅 TXT，EPUB/Markdown/DOCX 延后无场景）」——M1-M10 全绿即满足；Issue body 已 gh comment 留痕。

---

## 待澄清问题（评审时确认）

| # | 问题 | 选项 | 建议 |
|---|------|------|------|
| Q1 | 导出格式集 | A. 4 种全做（EPUB/Markdown/TXT/DOCX）<br>B. 3 种 MVP（Markdown/TXT/EPUB，DOCX 延后）<br>C. 仅 TXT（国内网文发布生态主流，其余无场景） | ✅ 已确认（用户拍板 2026-08-09：C）——正文已按仅 TXT 修订（§1/§5/§8/§10/§12 D4），格式扩展接缝保留（§5.5） |
| Q2 | 依赖库选型 | A. ebooklib + python-docx（+lxml）<br>B. 纯标准库手写（zipfile + xml.etree）<br>C. 混合 | ✅ 已确认（用户拍板 2026-08-09：随 Q1=C 自解，TXT 纯文本零依赖）——正文已按零依赖修订（§5.3/§12 D5），pyproject/uv.lock 零变更 |
| Q3 | 导出内容范围 | A. 仅正文（卷/章）<br>B. 正文 + 设定档案固定包含<br>C. `include_settings` 参数切换（默认不含） | ✅ 已确认（用户拍板 2026-08-09：C）——正文已按参数切换修订（§2.3/§5.1/§6.3） |
## 14. 动作确认

> 每个端点/命令的完整状态流表（基于 §3 API + §4 CLI + §7 边界事实，不重复、不新增行为）。

### 14.1 端点状态流

| 端点 | 前置条件 | 动作/状态转换 | 成功 | 失败 | 边界 |
|------|---------|--------------|------|------|------|
| GET /api/v1/projects/{project_id}/export | 项目存在且未软删（E1） | 只读聚合 7 模块（§5.1 ①-④）→ BookDocument → TXT 序列化（§5.3）→ 字节流响应 | 200 text/plain; charset=utf-8 + Content-Disposition attachment（文件名 URL 编码）；幂等、确定性（同参数同字节） | 404「项目不存在」（复用 ProjectNotFoundError）；422 format 非 txt（Pydantic Literal，E10）；422 include_settings 非法；500「内部错误: <e>」（并行拉取单源失败，E9） | 项目无内容 → 200 空文档（E2/E4）；文件名非法字符清洗为 _（E5）；空书名占位 untitled（E7）；正文超长正常导出（E6）；快照语义以聚合时刻为准（E11） |

### 14.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow export <project> [--include-settings] [--output PATH] [--json] | 项目存在（名称精确匹配 / 数字或 UUID 直通；恒经 ensure_kernel + HTTP get_raw） | 下载 TXT 原始文本 → 写文件（目录 → 建议文件名；文件路径 → 直接写入；默认 cwd + 建议文件名） | 退出 0；人类模式「✅ 导出成功: {name} → {path} ({bytes:,} bytes)」；--json 信封 data = ExportResult {format, filename, bytes, path} | 项目不存在 → 退出 1「项目不存在: <name>」；写文件失败（权限/磁盘）→ 退出 1「写文件失败: <系统错误>」 | --output 为已存在文件 → 直接覆盖不确认（E8）；无 --format 选项（v1.1 单格式，未来扩展恢复 -f） |

### 14.3 验收锚点（写入 §14）

- A1：项目不存在 → 404「项目不存在」（非 500、非英文文案泄漏）
- A2：format=epub → 422（Literal["txt"] 校验，非 200）
- A3：include_settings=true → 附录含 5 类档案；false → settings 空列表（§6.3 摘要拼接）
- A4：并行拉取单源 DB 失败 → 500「内部错误: ...」（无部分导出，原子快照，E9）
- A5：空项目（无卷无章）→ 200 空文档（标题 + 分隔线，不报错，E2）
- A6：软删内容（卷/章/角色/世界观/大纲/时间线/伏笔）不出现于导出
- A7：>50 章项目不丢章（循环分页拉全，§5.2 分页陷阱回归）

### 14.4 漂移标注

- 无关键漂移：实现 `api/routers/export.py` 与 spec §3.1/§3.3 一致（1 端点、404/500 detail 文案、format Literal["txt"]、include_settings 默认 false）；Content-Disposition 实现为 filename*=UTF-8''（RFC 5987）形式，与 spec「文件名 URL 编码」语义一致，属表述差异。
