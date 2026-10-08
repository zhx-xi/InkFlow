# F12: 时间线管理 (timeline_service) — 功能规格

> **时间口径（ADR-055 / #1000）**：本模块时间字段（created_at/updated_at；**例外**：time_value/time_unit/time_display = 世界内语义时间，不转换）**存储 / API / MCP / `--json` 一律 UTC ISO 原始值**；CLI 人类输出经 `cli/_time.format_local` 转**系统本地时区**显示（'YYYY-MM-DD HH:mm:ss'，naive 串=UTC 口径先补 tzinfo 再换算）。硬约束惯例，非可配置开关。
>
> **端**: backend

> **Spec 变更（v1.1，2026-09-18，#211 文档同步补齐）**: 删除语义统一——普通实体软删→真删（原变更日期 2026-08-13，#211 落地时仅 f10/f35/f36/f37/f43/f48 同步，本 spec 属**文档同步滞后**，本次补齐）。① TimelineEvent 移除 `is_deleted` 字段（§2.1）；② DELETE 默认真删（移除 `force` 软删路径与 `--permanent`），`POST /timeline/events/{id}/restore` 端点与 `timeline restore` 命令移除（§3/§4/§14）；③ 双线视图与一致性检查基于物理存在的事件（§5）。**F1 项目（回收站）与 F24 会话（归档）保留软删语义，不在本次变更范围**。
>
> **Spec 变更（v1.2，2026-10-01，#1409）**: **`time_value` 终局语义**确立（§2.7）——`time_value` 是「相对项目时基的累计时长」，其物理尺度由 `time_unit` 给定；一致性检查与事件时间线排序**一律在按单位归一到「日」的尺度上**进行（年 365 / 月 30 / 周 7 / 日 1；`时/时辰` 为当天时刻，锚定叙事序上最近日锚点，**不是累计量**）。① `time_unit` 由「仅语义、不参与排序」改为**参与归一排序**（§2.1/§2.2 表述作废，§5.2/§5.3 算法同步）；② 新增项目级归一/重锚工具 `inkflow timeline normalize`（§4.1/§4.2 CLI 契约 + §5.7 算法）；③ 提取 prompt 同步要求「单位固定 + 项目内累计时基 + 不确定即 null」（§5.5，F14 §5.5 契约由本 spec 统一声明）；④ 冲突/提示消息同时给出原始表达与当前 `time_value`（§5.4）。**本语义是 #1353（多纪元最小落地）与 #1410/#1411（完整历法引擎）的共同前置**——多纪元轴族必须建立在本节「单时基 + 单位归一」之上，不得绕过。
>
>
> **Spec 变更（v1.3，2026-10-02，#1353）**: **多纪元最小承载**（0.16.0，方案 A）——① §2.2 论证表中原「纪元 + 序号复合键 ❌ 否决」**改写为「0.16.0 `extra` 承载 / 0.17.0 正式化」**（重新论证见 §2.8）；② 新增 §2.8「多纪元最小承载」：承载键约定（`extra.era` 轴名 / `extra.era_value` 轴内值）、写入成对语义、**边界声明**（单时基不变 / 纪元只作轴标签 / 不跨纪元比较）；③ 请求面新增 `era` / `era_value`（§3.2 请求体 + §4.1 CLI `--era` / `--era-value`，含清除语义）；④ **一致性检查算法与 `seq` 不变**（不按 `era` 分桶、不跨纪元换算 → 归 #1411）。**硬边界**：零 DDL（不新增列、不新增 `ensure_*`、不改既有数据），且 §2.7 的 S1-S10 逐条不变。
>
> **Spec 变更（v1.4，2026-10-06，#1410）**: **多纪元正式化**（0.17.0，ADR-065）——落地 v1.3 §2.2 论证表所指「0.17.0 正式化」第二期：① §2.1 数据模型新增三列 `era`（轴名）/ `era_value`（轴内值）/ `era_scale`（流速比，默认 1.0）；② §2.8 承载键由 `extra.era` / `extra.era_value` **改为正式列**（旧键降为 **v1.3 遗留快照**：迁移一次性投影进正式列后**不再读写**，且**不删除**以保可逆）；③ 请求面 `era` / `era_value` 成对语义（§2.8 E4）**完全不变**，仅落点由 `extra` 改为正式列；④ **零 DDL 硬边界到期解除**——新增幂等迁移 `ensure_timeline_era_columns`（三列 ADD COLUMN + 一次性回填）；⑤ 前端读取来源**同 PR** 切正式列（消除中间态漂移）。**硬边界不变**：`time_value` 仍是**跨轴全局标量**（§2.7 S1-S10 逐条不变）；**不换算 / 不按 `era` 分桶 / 不跨纪元比较**（换算规则归 T2 #1411）。
>
> **Spec 变更（v1.5，2026-10-06，#1411）**：**跨纪元流速换算引擎 + 一致性检查按轴分桶**（0.17.0，ADR-065 §2.1 承接）——**T2 落地**：① 新建 `domain/services/era_conversion.py`（`to_global(era, era_value, scale) = era_value / scale`，唯一实现点）；② `era_scale` 进**读写面**（请求体 / CLI `--era-scale`）；③ §5.3 检查算法由「单一归一日尺度」升级为「**先按 `era` 分桶、桶内按归一日尺度、跨桶按换算后全局标量**比较」；④ §2.8 **E6 立场收束**：T1 的「不跨纪元比较」硬验收（§14.3 A9）**作用域回到 T1**，T2 起跨纪元**经换算**比较（**R6-5 裁定 = 不降级**）。**不变**：`time_value` 仍是全局标量（§2.7 S1-S10 逐条不变）；默认轴（`era=""`）行为逐字段不变。
>
> **Spec 版本**: 1.7 | **日期**: 2026-10-08 | **依据**: PRD v2.1 §6.2 P1-04, Constitution P1-P6, ADR-019
>
> **Spec 变更（v1.6，2026-10-07，#1520）**: `timeline create` / `timeline update` 新增 `--content-file <path>`（从 UTF-8 文件读取正文=**事件描述**，叙事型长文本）。语义同 F7 §4.0 通用约定：与 `--description` **不可同传**（同传 → 退出码 2 + stderr 文案，不发生写入）；文件缺失/不可读 → `VALIDATION_ERROR` + 退出码 1（不泄漏栈回溯）；原样落库（不 strip、不转码）。§4.1 签名与 §14 状态流同步；`time_value`/`era` 等既有语义逐条不变。
> **Spec 变更（v1.7，2026-10-08，#1526）**: §2.7 S10 提取侧契约**补齐 `time_display`**——提取侧必须给出原文时间表达（如「三月初二」），解析不出累计天数时 `time_value` 为 `null` 但**原文表达必须保留**；`time_unit` 仅在解析出 `time_value` 时写入（防「假非空」，rc1 实测 `'日' ×182`）。**S1-S9 逐条不变**，本补充只加「原文表达不得丢」的展示面要求。实现契约与提示词改动见 [F14 §5.5](../f14-extraction/spec.md) v1.4（0.17.0 rc1 数据质量：183 事件 `time_display` 空 182 → 世界序满屏「未知」）。
> **所属阶段**: Phase 2 — 创作工具链（0.2.0 里程碑第四个模块，估算 3-4 人天）
> **关联 Issues**: [#42](https://github.com/zhx-xi/InkFlow/issues/42)
> **依赖**: F1 ✅（前置）；F2（边界声明，非硬依赖，见 §11）；F5 — **不依赖**（F12 无 LLM，见 §1/§5）
> **参考 ADR**: [ADR-001](../../adr/architecture/ADR-001.md) (模块化单体), [ADR-002](../../adr/architecture/ADR-002.md) (六边形分层), [ADR-003](../../adr/database/ADR-003.md) (Repository), [ADR-004](../../adr/database/ADR-004.md) (Pydantic v2), [ADR-007v2](../../adr/architecture/ADR-007v2.md) (包结构), [ADR-010](../../adr/llm/ADR-010.md) (上下文分层), [ADR-012](../../adr/architecture/ADR-012.md) (错误处理), [ADR-016](../../adr/service/ADR-016.md) (loguru), [ADR-017](../../adr/test-ci/ADR-017.md) (CI 门禁), [ADR-018](../../adr/test-ci/ADR-018.md) (测试分层), [ADR-019](../../adr/packaging/ADR-019.md) (版本里程碑)
> **状态**: ✅ 已实现（PR #63）

>
> **快速导航**（2026-08-08 #201）：
> 1. 概述 · 2. 数据模型 · 3. API 契约 · 4. CLI 命令签名
> 5. 一致性检查模式（关键差异：确定性算法而非 AI） · 6. 时间线组织规则 · 7. 边界情况与错误处理 · 8. 文件结构
> 9. 测试策略 · 10. 不在范围内 · 11. 依赖关系 · 12. 关键架构决策记录
> 13. 验收标准 · 待澄清问题（≤ 3 个，评审时确认）
---

## 1. 概述

管理小说的**时间线事件**（创建/查询/更新/真删）。每个事件同时携带两个时间维度：**世界内时间**（故事世界内「事件发生在何时」，构成**事件时间线**）与**叙事位置**（小说叙述中「该事件在第几个被讲」，构成**叙事时间线**），并支持**双线一致性检查**——对比两条时间线的顺序，输出冲突报告（未声明的倒叙/插叙被识别为「时间倒流」冲突，显式声明的倒叙/插叙被识别为合法）。

**核心价值**: 作者与 AI Agent 可以维护「故事世界发生了什么（按世界内时间）」与「小说叙述了什么（按叙事顺序）」两条线；一致性检查把时间线硬伤（如叙事顺序矛盾、忘记标注的倒叙）显式化、可修正，为 F3 写作（按时间线推进）、F6 上下文注入（时间线事件进 Prompt）、F15 审计、F16 一致性审计提供数据基础。

**与 F9/F10/F11 样板的关系（关键差异）**: F9/F10 沉淀「**实体 + AI 提取**」模式，F11 演进为「**实体 + AI 生成**」模式；F12 是 0.2.0 创作工具链**第四个**应用该骨架的模块，但 AI 场景彻底移除——本模块的增值能力（一致性检查）是**确定性算法**，**无 LLM**：

```text
F9/F10 提取:  章节文本(text) ──LLM──▶ 结构化实体 ──合并落库──▶ 实体档案
F11  生成:    项目设定/约束(prompt) ──LLM──▶ 结构化大纲 ──新建落库──▶ 大纲规划
F12  检查:    事件档案(双时间维度) ──确定性算法──▶ 双线视图 + 冲突报告
```

**复用** F9/F10/F11 的骨架部分：实体模型（domain/models）→ CRUD Port（domain/ports）→ Repository（infrastructure）→ Service（domain/services）→ API Router + CLI（薄层）。**不同**的部分：无 LLM 模板/解析/重试管线（无 `infrastructure/llm/templates/` 目录）；§5 从 F11 的「AI 生成模式」变为「**一致性检查模式**」（确定性算法，可测试、可快照断言）。

**边界声明**:
- F12 不做**事件 AI 提取/生成**：章节文本 → 事件、LLM 生成事件序列归 **F14 统一提取服务**（P1-06，Issue #44），见 §10
- F12 不做**跨模块全维度一致性审计**（角色/世界观/大纲/时间线/伏笔联动审计）：归 **F15 审计服务**（P1-07），见 §10
- F12 不做**事件-章节强绑定**：叙事位置用单一序号表达，不绑定 F2 卷/章实体（同 F11 边界声明，见 §2.2/§11）
- F12 不做**树形/平行时间线**：MVP 单线（世界内时间全序 + 叙事顺序全序），见 §2.2/§10

---

## 2. 数据模型

遵循 F1 Project 的「领域 Pydantic 实体 + 请求/更新 DTO + ORM 双模型」模式（ADR-004）。领域层 id 为 UUID，数据库 int 自增映射（同 F1 §12）。

### 2.1 TimelineEvent（时间线事件）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，DB int 自增映射 |
| project_id | UUID | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目 |
| title | str | NOT NULL, 1-100 字符, 去空白 | 事件标题（如「林尘觉醒金手指」「宗门大比」） |
| description | str | NOT NULL, DEFAULT "", ≤ 5000 字符 | 事件描述（该时刻发生了什么） |
| time_value | float? | NULLABLE, 已索引 | **世界内时间数值键**（可排序、可比较）——**语义 = 相对项目时基的累计时长，尺度由 `time_unit` 给定**（终局定义见 §2.7）；None = 世界内时间未知（事件时间线排末尾、不参与一致性检查，见 §5）；约束：有限数值，\|v\| ≤ 10^12（允许负数 = 纪元前） |
| time_unit | str | NOT NULL, DEFAULT "", ≤ 20 字符, 去空白 | 时间单位标签，**`time_value` 的物理尺度**（可知单位：年/岁=365 日、月=30 日、周/星期=7 日、日/天=1 日；`时/时辰`=当天时刻；未列举/空串 = 视同时基裸值，因子 1）。**参与归一排序**（§2.7/§5.2）。同一项目内应统一单位（提取默认「日」） |
| time_display | str | NOT NULL, DEFAULT "", ≤ 100 字符 | 原始时间表达（如「示例历 317 年秋」），time_value 的人工可读镜像；不参与排序 |
| narrative_position | int | NOT NULL, DEFAULT 0, ≥ 0, 已索引 | **叙事位置**（单一线性序号，小者在前 = 先被叙述）；创建缺省 = 项目内 max+1（叙事末尾追加）；允许重复（排序按 `(narrative_position ASC, created_at ASC)` 稳定输出） |
| timeline_flag | str | NOT NULL, DEFAULT "", ≤ 20 字符, 去空白 | 时间线标记（建议值：`""` = 正叙、`flashback` = 倒叙、`flashforward` = 插叙/预叙；自由文本，未在建议词表中的值等同未标记，见 §6.2） |
| extra | dict[str, Any] | NOT NULL, DEFAULT {} | 扩展字典（参与角色、地点、标签等 Phase 2+ 字段预留）；**v1.4 起不再承载纪元**——`extra.era` / `extra.era_value` 降为 **v1.3 遗留快照**（迁移一次性投影进正式列后不再读写，§2.8） |
| era | str | NOT NULL, DEFAULT "" | **纪元轴名**（≤ 50 字符，去空白；`""` = **默认轴** = 旧的单标量时间线，R6-4）——多纪元正式列（v1.4，ADR-065 §2.8） |
| era_value | float? | NULLABLE | **纪元轴内值**（有限数值；仅在 `era` 非空时有意义）——用于**轴内排序与轴内标签**；**v1.5 起经 `to_global` 换算后参与**全局排序与一致性检查（§2.8 E11 / §5.3）；**不经换算不得直接参与**全局比较（跨纪元不直比轴内值） |
| era_scale | float | NOT NULL, DEFAULT 1.0 | **流速比**（该纪元相对项目时基的时间流速；1.0 = 同速）——**v1.5 起进读写面**（请求体 / CLI `--era-scale`）+ 换算输入（`to_global`，§2.8 E11） |
| ~~is_deleted~~ | ~~bool~~ | ~~NOT NULL, DEFAULT False, 已索引~~ | **（v1.1 移除）** 原软删除标记，真删语义下无意义 |
| created_at | datetime | NOT NULL, AUTO | 创建时间 (UTC) |
| updated_at | datetime | NOT NULL, AUTO | 更新时间 (UTC) |

**业务规则**:
- `title` **允许重复**：不同事件可有相同标题（如多个「回忆」事件），事件无自然业务唯一键（同 F11 PlotPoint 处理，见 §2.4）
- `time_value` 与 `narrative_position` **独立可编辑**：改世界内时间不影响叙事顺序，反之亦然——双线相对独立正是需要一致性检查的原因（§5）
- `time_value = None`（时间未知）是合法状态：事件仍属于叙事时间线，但在事件时间线排末尾、不参与一致性检查（计入 `skipped`，不报冲突）
- 删除的事件（v1.1 真删）**物理不存在**，不进入双线视图与一致性检查
- **多纪元三列（v1.4；v1.5 起换算参与检查）**：`era` 为空 = **默认轴**；`era_value` 仅在 `era` 非空时有意义；`time_value` 仍是**跨轴唯一排序键**（三列**不进**全局排序）；**一致性检查**自 v1.5 起**按 `era` 分桶**（桶内归一日尺度、跨桶按 `to_global` 换算后的全局标量，§5.3）；`extra.era` / `extra.era_value` 为 v1.3 **遗留快照**（不再读写，§2.8 E9）

### 2.2 双时间线设计决策（时间表示法）

**世界内时间**用「数值键 + 单位标签 + 原始表达」三字段表达（`time_value` / `time_unit` / `time_display`）：

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **数值键 + 标签 + 原始表达（选定）** | time_value 提供全序（可排序/可比较/可做一致性检查）；time_display 保留作者原始表达；time_unit 提供单位语义 | 数值键由作者/提取器维护，需约定单位 | ✅ MVP——一致性检查必须以「可比较的数值」为前提，三字段同时保留机器可算性与作者可读性。**v1.3 补充**：多纪元的**轴标签**由 `extra` 承载（§2.8），本行三字段的**单一排序键**语义不变 |
| 纯自由文本时间（仅 time_display） | 零约束，作者最自由 | **不可排序、不可比较**——事件时间线无法排序、一致性检查没有依据 | ❌ 否决（无法支撑本模块核心验收标准） |
| **纪元轴：正式列 `era` / `era_value` / `era_scale`（0.17.0 选定，v1.4 / ADR-065）** | `time_value` 仍是**跨轴全局标量**（单一排序键与既有检查能力不变）；`era`（轴名）+ `era_value`（轴内值）承载纪元轴族，`era_scale`（流速比）承载 T2 换算输入 | 需 `ensure_*` 迁移三件套（v1.4 已交付）；跨纪元换算/分桶仍归 #1411 | ✅ **原「❌ 否决」经两次改写**：v1.3（#1353）改为「0.16.0 `extra` 承载 / 0.17.0 正式化」，本行（v1.4 / #1410）落地**第二期**。否决理由（跨纪元换算复杂、双字段参与排序逻辑复杂）**仍然成立**——故**不引入复合键**（全局排序仍靠单一 `time_value`）、**不做换算/分桶**（归 #1411）；正式化收益 = DDL 级类型/长度约束 + T2 的 `era_scale` 落点（重新论证见 §2.8） |
| 公历 datetime | 现成类型 | 小说世界时间通常非公历（纪元/历法/季节制），强转 datetime 是错误抽象 | ❌ 否决 |

**叙事时间**用单一整数序号（`narrative_position`）表达：

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **单一整数序号（选定）** | 零依赖、线性全序、排序/比较简单 | 不携带「第几章第几段」的章节语义 | ✅ MVP——同 F11 边界声明（大纲情节点不绑定实际章节），F12 事件同样不绑定 F2 卷/章；章节级位置（卷→章→段）归 Phase 2+（§10） |
| 章节序 + 段序（chapter_index + segment_index） | 携带章节语义 | 需 F2 集成与章节存在性校验（跨模块硬依赖）；章节重排时需级联修正 | ❌ 否决（F11 边界声明先例：规划层与章节层不互相绑定） |

### 2.3 事件归属与级联

- 事件是**项目级**实体（`project_id` 直接归属项目，无父实体——单实体模块，同 F10 WorldSetting）
- 事件无子实体：**无级联语义**；项目硬删除 → 事件级联物理删除（DB FK CASCADE）

### 2.4 唯一约束说明（不设 partial unique index）

与 F11 PlotPoint / F9 sort_order 的结论一致，**timeline_events 不设任何唯一约束**：

- `title` 允许重复（「回忆」「战斗」类标题可多次出现，无「同名 = 同一事件」语义——时间线事件是**实例**而非**档案**，与 F9/F10 的「同名 = 同一实体」合并锚点语义根本不同）
- `narrative_position` 允许重复（展示排序权重而非业务键）
- `time_value` 允许重复（多事件可同时刻发生，同刻事件按叙事顺序排列，一致性检查中相等时间不冲突）

服务层因此**无同名冲突检查**，错误类型少于 F9/F10/F11（见 §3.4 异常映射表）。

### 2.5 领域模型（Pydantic v2 语法，参照 F10 `domain/models/world.py`）

```python
import math
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

TIME_VALUE_LIMIT = 1e12


def _validate_title(v: str) -> str:
    """共享的标题校验：去空白后非空且不超过 100 字符."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("事件标题不能为空")
    if len(stripped) > 100:
        raise ValueError("事件标题不能超过 100 个字符")
    return stripped


def _validate_short_text(v: str, field: str, max_len: int) -> str:
    """共享的短文本校验：去空白且不超过 max_len 字符（空串 = 无，允许）."""
    stripped = v.strip()
    if len(stripped) > max_len:
        raise ValueError(f"{field}不能超过 {max_len} 个字符")
    return stripped


def _validate_description(v: str) -> str:
    """共享的描述校验：不超过 5000 字符（不强制去空白）."""
    if len(v) > 5000:
        raise ValueError("事件描述不能超过 5000 个字符")
    return v


def _validate_time_value(v: float | None) -> float | None:
    """共享的世界内时间校验：有限数值且 |v| ≤ 1e12；None = 时间未知（允许）."""
    if v is None:
        return None
    if not math.isfinite(v):
        raise ValueError("世界内时间必须是有限数值")
    if abs(v) > TIME_VALUE_LIMIT:
        raise ValueError("世界内时间超出允许范围（[-10^12, 10^12]）")
    return v


class TimelineEvent(BaseModel):
    """时间线事件领域实体. 对应 timeline_events 表."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str = ""
    time_value: float | None = None      # None = 世界内时间未知
    time_unit: str = ""                  # time_value 的尺度（年/月/周/日/时），参与归一排序（§2.7）
    time_display: str = ""               # 原始时间表达（如「示例历 317 年秋」）
    narrative_position: int = 0
    timeline_flag: str = ""              # ""/flashback/flashforward（建议值，自由文本）
    era: str = ""                        # 纪元轴名（""=默认轴；v1.4 正式列，§2.8）
    era_value: float | None = None       # 纪元轴内值（None=未知；仅 era 非空时有意义）
    era_scale: float = 1.0               # 流速比（默认 1.0；换算归 T2 #1411）
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class TimelineEventCreate(BaseModel):
    """创建时间线事件请求 DTO."""
    project_id: uuid.UUID
    title: str
    description: str = ""
    time_value: float | None = None      # None = 时间未知
    time_unit: str = ""
    time_display: str = ""
    narrative_position: int | None = None   # None = 追加到叙事末尾（max+1）
    timeline_flag: str = ""
    era: str = ""                           # 纪元轴名（v1.4；成对语义 §2.8 E4）
    era_value: float | str | None = None    # 轴内值（数值=写入；""=不设/清除；None=不设）

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        return _validate_title(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _validate_description(v)

    @field_validator("time_value")
    @classmethod
    def validate_time_value(cls, v: float | None) -> float | None:
        return _validate_time_value(v)

    @field_validator("time_unit")
    @classmethod
    def validate_time_unit(cls, v: str) -> str:
        return _validate_short_text(v, "时间单位", 20)

    @field_validator("time_display")
    @classmethod
    def validate_time_display(cls, v: str) -> str:
        return _validate_short_text(v, "时间显示文本", 100)

    @field_validator("narrative_position")
    @classmethod
    def validate_narrative_position(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("叙事位置不能为负数")
        return v

    @field_validator("timeline_flag")
    @classmethod
    def validate_timeline_flag(cls, v: str) -> str:
        return _validate_short_text(v, "时间线标记", 20)


class TimelineEventUpdate(BaseModel):
    """更新时间线事件请求 DTO — 所有字段可选（exclude_unset 语义，同 F1）.

    time_value: None 表示不修改；"" 表示清除世界内时间（置为未知）.
    timeline_flag: None 表示不修改；"" 表示清除标记（置为正叙）.
    time_unit/time_display: None 表示不修改；"" 表示清除（置空串）.
    只有传入的字段会被更新，未传入的字段保持不变.
    """
    title: str | None = None
    description: str | None = None
    time_value: float | str | None = None   # str "" = 清除世界内时间
    time_unit: str | None = None
    time_display: str | None = None
    narrative_position: int | None = None
    timeline_flag: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        return _validate_title(v) if v is not None else None

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        return _validate_description(v) if v is not None else None

    @field_validator("time_value")
    @classmethod
    def validate_time_value(cls, v: float | str | None) -> float | str | None:
        if isinstance(v, str):
            if v != "":
                raise ValueError("清除世界内时间请传空字符串")
            return v
        return _validate_time_value(v)

    @field_validator("time_unit")
    @classmethod
    def validate_time_unit(cls, v: str | None) -> str | None:
        return _validate_short_text(v, "时间单位", 20) if v is not None else None

    @field_validator("time_display")
    @classmethod
    def validate_time_display(cls, v: str | None) -> str | None:
        return _validate_short_text(v, "时间显示文本", 100) if v is not None else None

    @field_validator("narrative_position")
    @classmethod
    def validate_narrative_position(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("叙事位置不能为负数")
        return v

    @field_validator("timeline_flag")
    @classmethod
    def validate_timeline_flag(cls, v: str | None) -> str | None:
        return _validate_short_text(v, "时间线标记", 20) if v is not None else None
```

> `time_value` 的「None = 不修改，"" = 清除」双语义与 F11 `PlotPointUpdate.arc_id`（`uuid | str`，"" = 清除弧线）、F10 `WorldUpdate.category`（"" = 清除类别）同构，是既有项目约定。

### 2.6 检查相关模型（§5 详述）

```python
class TimelineEventRef(BaseModel):
    """一致性检查中的事件引用（轻量快照，避免整表序列化）."""
    id: uuid.UUID
    title: str
    time_value: float | None
    time_display: str
    narrative_position: int
    timeline_flag: str


class TimelineConflict(BaseModel):
    """单条时间线冲突/倒叙记录.

    conflict_type:
      - order_conflict: 未标记的逆序对（叙事顺序与世界内时间矛盾，需修正）
      - flashback: 逆序对且 next 事件声明了 flashback（合法倒叙）
      - flashforward: 逆序对且 prev 事件声明了 flashforward（合法插叙/预叙）
    """
    conflict_type: Literal["order_conflict", "flashback", "flashforward"]
    prev: TimelineEventRef    # 叙事顺序中靠前的事件（世界内时间较晚）
    next: TimelineEventRef    # 叙事顺序中靠后的事件（世界内时间较早）
    message: str              # 人类可读描述（含修正建议）


class ConsistencyReport(BaseModel):
    """时间线一致性检查报告（§5）."""
    project_id: uuid.UUID
    checked: int                         # 参与比较的事件数（time_value 非 None）
    skipped: int                         # 时间未知被跳过的事件数
    consistent: bool                     # conflicts 为空
    conflicts: list[TimelineConflict] = []     # 需修正的冲突（order_conflict）
    flashbacks: list[TimelineConflict] = []    # 已声明的倒叙/插叙（include_flashbacks=false 时为空列表）
    event_timeline: list[TimelineEvent] = []   # 事件时间线视图（time_value 升序，未知排末尾）
    narrative_order: list[TimelineEvent] = []  # 叙事顺序视图（narrative_position 升序）


class TimelineView(BaseModel):
    """双时间线总览（事件时间线 + 叙事时间线）."""
    project_id: uuid.UUID
    total: int
    event_timeline: list[TimelineEvent]   # 事件时间线（世界内时间升序，未知排末尾）
    narrative_order: list[TimelineEvent]  # 叙事时间线（叙事位置升序）
```

### 2.7 time_value 终局语义（#1409，0.16.0 起；#1353/#1410 的共同前置）

**背景（#1409 实证）**：原契约把 `time_unit` 声明为「仅语义、不参与排序」，却在排序/一致性检查里直接比较裸 `time_value`。于是「多单位共用一个数值键」这件事**在契约里无人负责**：写入侧随便填单位，校验侧只能裸比较 → 跨单位误判（实测：30 章正文、382 事件，`日 186 / 时·时辰 61 / 月 18 / 年 16 / 空 101`，`audit check` 报 7 条「未声明的倒叙」，其中 3 条是 `8 日 vs 3 月` 这类**纯跨单位误判**）。本节把该语义定死。

**终局语义（规范文本）**：

| # | 规则 |
|---|------|
| S1 | **累计时基**：`time_value` 是「相对**项目时基**（epoch，项目内唯一）的累计时长」；其**物理尺度由 `time_unit` 声明**——如 `3.5` + `年` ⇔ 距时基 3.5×365 日。历史/手工数据允许其他单位，但语义一律按本条解释 |
| S2 | **单位归一表**（比较与排序前必须归一）：`年/岁` = 365 日、`月` = 30 日、`周/星期` = 7 日、`日/天` = 1 日。归一值 `days = time_value × factor(unit)` |
| S3 | **同一项目内应统一单位**（新建/提取默认 `日`）；跨单位数据依赖 S2 归一后才可比。**禁止**把不同单位的裸 `time_value` 直接比大小 |
| S4 | **`时 / 时辰` = 当天时刻，不是累计量**：归一值 = **叙事序上最近一个「日级」事件的归一值（日锚点）** + `(time_value mod 24) / 24`；无前置日锚点时锚点取 0。**禁止**把它当累计值（`/24` 直接比、或与裸日值直接比） |
| S5 | **未知/未列举单位（含空串）= 时基裸值**（因子 1）——保留既有行为，向后兼容（反例守护：`time_unit` 为空的项目其比较结论与 #1409 之前完全一致） |
| S6 | **归一用于比较/排序，不回写库**：库内仍存原始 `time_value`/`time_unit`；归一是**只读投影**（判定层），非数据迁移。`time_value` 需要的**数据层归一/重锚**由 S7 的一次性工具承担 |
| S7 | **项目级归一/重锚（一次性，显式）**：`inkflow timeline normalize --project-id <id>`（默认 dry-run，`--apply` 落库，§5.7）把**段内计数器型**历史数据投影到项目时基：按叙事顺序走带值且**未声明**倒叙/插叙的事件，**数值回落 = 新叙事段**，新段起点接在上一段末尾，**段内保留原有相对天数**；单位一并归一到「日」。**禁止**用「抬平到前一条」（`g = prev`）——那会级联抹平整卷的相对信息 |
| S8 | **确定性 & 幂等**：归一与重锚均为纯函数（同输入同输出）；对已归一的单调序列运行重锚 → **0 处改动**（幂等） |
| S9 | **`time_value = None` 语义不变**：时间未知 → 事件时间线排末尾、一致性检查计入 `skipped`（不参与比较、不报冲突） |
| S10 | **提取侧契约**：LLM 提取的 `time_value` 必须**单位固定**、且为**项目内累计时基**；**无法确定时输出 `null`**，不得输出「本段第几天」这类段内相对计数器（§5.5）；历史段内计数器数据由 S7 工具修复。**#1526 补充**：提取侧还**必须给出 `time_display`（原文时间表达，如「三月初二」）**——解析不出累计天数时 `time_value` 为 `null` 但**原文表达必须保留**（展示面不得丢）；`time_unit` 仅在解析出 `time_value` 时写入（防「假非空」）。实现契约见 [F14 §5.5](../f14-extraction/spec.md) |

**与后续里程碑的关系**：`#1353`（0.16.0 多纪元最小落地）在本节「单时基 + 单位归一」之上叠加**纪元轴族**（`extra.era` / `extra.era_value`），**不推翻** S1-S5；`#1410/#1411`（0.17.0 完整历法引擎）把 S2/S4 的固定换算表替换为**可配置纪元流速比 + 历法换算**，届时 S2/S4 由「常量表」升级为「历法函数」，S7 的段续接语义保留。**三个里程碑共用本节词汇**（时基 / 单位 / 日锚点 / 段续接），不得各造一套。

### 2.8 多纪元承载（#1353 起；v1.4 / #1410 正式化为三列，ADR-065 决策记录）

**背景（需求侧）**：作者的世界里同时存在多套纪年（例：某王朝年号、某修真界的界历、上界的历法），而世界序只能按「±N 日」这类**相对标量**显示，无法**按纪元分轴显示与选择**。用户 2026-10-01 拍板：最终做**完整历法换算引擎**（正式列 + 流速换算 + 跨轴一致性判定），整体量大 → **拆两个里程碑**：**0.16.0（#1353）只做「多轴共存 + 可选择性显示」**（`extra` 承载，零 DDL）；**0.17.0（#1410 = 本版 v1.4）做正式化（三列 + 幂等迁移 + 存量回填）**，**跨纪元换算（T2）归 #1411**。

**承载约定（v1.4 规范文本；承载位 = 正式列）**：

| # | 规则 |
|---|------|
| E1 | **轴名**：`era` 列（str，≤ 50 字符，去空白；**`""` = 该事件不属于任何纪元轴**，归**默认轴**）。**v1.4 起为正式列**（v1.3 的 `extra.era` 为遗留快照，见 E9） |
| E2 | **轴内值**：`era_value` 列（float，有限，NULLABLE；**仅在该事件 `era` 非空时有意义**）——用于**轴内排序与轴内标签**（如某纪元轴内 `317.5`） |
| E3 | **全局标量不变**：`time_value` / `time_unit` 语义**完全不变**（§2.7 S1-S5）——它仍是**跨轴全局标量**，**排序**只消费它；**v1.5 起一致性检查**在**默认轴**上消费它，**纪元轴**上消费 `to_global` 换算的全局标量（E6/E11） |
| E4 | **写入成对**：请求面 `era` / `era_value` 是**成对**语义（§3.2 / §4.1）——① `era` 未传（None）⇒ **不修改**（此时 `era_value` 被**忽略**）；② `era = ""` ⇒ **清空** `era` 与 `era_value`（回到默认轴）；③ `era` 非空 ⇒ 写 `era`，且 `era_value` 为数值 ⇒ 写 `era_value`、`era_value = ""` ⇒ 清空 `era_value`、`era_value` 未传 ⇒ **保留原值**。**落点 = 正式列**（v1.3 的 `extra.era` / `extra.era_value` 不再写入） |
| E5 | **默认轴（R6-4 拍板）**：`era` 为空的事件属于**默认轴**（= 旧的「单标量时间线」）——它与纪元轴**并列**存在于轴族中，**事件不因此丢失或改判**；只有一条轴时（项目无任何纪元数据）**不出现轴选择器**，渲染与 v1.2 **完全一致**（反例守护） |
| E6 | **~~不换算、不跨纪元比较（R6-5 的立场）~~ → v1.5 起：跨纪元经换算比较（R6-5 裁定 = 不降级）**：T1（v1.4）里程碑不做跨纪元换算/比较/分桶（当时的立场）；**T2（#1411）起** `check_consistency` **先按 `era` 分桶**——默认轴沿用 §2.7 归一日尺度，纪元轴用 `to_global` 换算的全局标量，**跨桶按换算后全局标量比较**（§5.3）；「不跨纪元比较」硬验收（§14.3 A9）**作用域收束回 T1**（ADR-065 §2.1） |
| E7 | **正式列 + 幂等迁移（v1.4 到期解除 v1.3 的「零 DDL」）**：三列 `era` / `era_value` / `era_scale` 落 `timeline_events`（§2.1）；迁移 `ensure_timeline_era_columns` 幂等（空表 / 缺列 / 有列三形态）；**存量回填**把 `extra.era` / `extra.era_value` **一次性投影**进正式列 |
| E8 | **`era_scale`（流速比，v1.5 进读写面）**：float，`NOT NULL DEFAULT 1.0`。**T2（#1411）起**请求面（`TimelineEventCreate` / `TimelineEventUpdate`）与 CLI（`--era-scale`）**接受**该值；换算输入 = `to_global(era, era_value, era_scale)`（E11） |
| E9 | **旧承载处置（遗留快照，不删除）**：`extra.era` / `extra.era_value` 为 **v1.3 遗留快照**——迁移后**不再读写**、**不删除**（保可逆：回退 0.16.0 时纪元信息仍在；且不违反「迁移不得删改既有数据」）。两者与正式列分歧时**以正式列为准** |
| E10 | **提取侧（F14）暂不带纪元**：本里程碑不改提取 prompt 与 `ExtractedTimelineEvent`；纪元数据来源仍是**手工/客户端写入**（API / CLI / GUI 对话框） |
| E11 | **换算规则（新增，v1.5 #1411）**：`to_global(era, era_value, scale) = era_value / scale`（`era_scale` = 该纪元相对项目时基的流速比；`1.0` = 同速、越大越快）。`era` 为空或 `era_value` 为 None → **None**（无全局标量，该事件在检查中按未知时间处置）；`scale <= 0` → 按 `1.0` 处置（防御，流速比非正无意义）。**唯一实现点 = `domain/services/era_conversion.py`**（service / 写入路径 / 视图不得各写一份）。检查按此值**跨桶**比较（§5.3） |

**重新论证（原否决理由 vs 现在接受的部分）**：

| 原否决理由（§2.2） | 0.16.0 的处置 | 0.17.0（v1.4）的处置 |
|---|---|---|
| 「跨纪元比较需要额外换算规则」 | **理由成立 → 因此不做换算**（E6）：0.16.0 的验收标准里**没有**跨纪元比较项，故不构成实现阻力 | **仍然不做**：换算归 T2（#1411）；本版不设跨纪元验收项 |
| 「两个字段参与排序逻辑复杂」 | **理由成立 → 因此不引入双排序字段**：全局排序键仍是单一 `time_value`（E3）；`extra.era_value` 只用于**轴内**排序与标签，不参与全局排序，也不进入一致性检查 | **仍然成立 → 不引入复合键**：`era_value` 只用于**轴内**排序与标签，不进全局排序、不进一致性检查 |
| （隐含）「数值键 + time_display 已覆盖同等表达能力」 | **被需求推翻**：`time_display` 是**被动展示字符串**，无法据以**按轴筛选/分轴显示**；#1353 明确要求「选择同时显示哪几条轴」→ 需要**结构化轴键**（`extra.era`），而非自由文本 | 同左；且正式列提供 **DDL 级类型/长度约束** 与 T2 换算所需的 `era_scale` 落点 |

**边界声明（不得越过的三条线）**：

1. **单时基不变**：`time_value` 仍是项目唯一时基上的累计量（§2.7 S1/S3）；纪元**不改变**它的物理尺度，也不引入第二套时基
2. **纪元只作轴标签**：`era` / `era_value` 仅用于**轴族派生、轴选择、轴内排序/标签**（GUI 层投影）；**不进入**一致性检查、全局排序、审计判定
3. **跨纪元比较（v1.5 起）**：~~本版不做~~ → **T2（#1411）已落地**：跨轴自洽性判定**经换算执行**（先按 `era` 分桶 + 跨桶按 `to_global` 全局标量比较，§5.3）。T1（v1.4）的**硬验收**「同一项目加不加纪元，`check` 结论逐字段一致」**作用域收束回 T1**（ADR-065 §2.1）

**与 T2（#1411）的移交面**：`extra.era` / `extra.era_value` → 正式列的**一次性投影迁移**已由 **#1410（v1.4）** 完成；跨纪元**换算**（`to_global(era, era_value, era_scale)`，E11）、`check_consistency` 的**按轴分桶比较**、以及 `era_scale` 的**读写面**（请求体 / CLI `--era-scale`）**已由 #1411（v1.5）落地**；轴族枚举若需服务端化（供 CLI/MCP 复用）仍归 #1411 后续。**跨里程碑共用本节词汇**（轴名 / 轴内值 / 默认轴 / 全局标量 / 流速比），不得各造一套。


---

## 3. API 契约

端点风格沿用 F2/F9/F10/F11：**创建/列表/双线视图/一致性检查嵌套于项目路径**，**详情/更新/删除扁平**。错误响应格式沿用 F1/F2/F9/F10/F11（`{"detail": "..."}` 404 / 422）。

### 3.1 端点总览（8 个，镜像 F10 §3.1 布局；单实体 + 双线视图 + 检查）

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/projects/{project_id}/timeline/events` | 创建事件 | `TimelineEventCreate` | 201 + TimelineEvent |
| GET | `/api/v1/projects/{project_id}/timeline/events` | 事件列表 | Query: `?search=&sort_by=&sort_desc=&offset=&limit=` | 200 + `{items, total, offset, limit}` |
| GET | `/api/v1/projects/{project_id}/timeline` | 双线总览（事件时间线 + 叙事顺序） | — | 200 + TimelineView |
| GET | `/api/v1/projects/{project_id}/timeline/check` | 一致性检查 | Query: `?include_flashbacks=` | 200 + ConsistencyReport |
| GET | `/api/v1/timeline/events/{event_id}` | 事件详情 | — | 200 + TimelineEvent JSON |
| PATCH | `/api/v1/timeline/events/{event_id}` | 更新事件 | `TimelineEventUpdate` | 200 + TimelineEvent |
| DELETE | `/api/v1/timeline/events/{event_id}` | 删除事件（**v1.1 真删**） | — | 204 |
| ~~POST~~ | ~~`/api/v1/timeline/events/{event_id}/restore`~~ | **（v1.1 移除）** 端点已不存在 | — | — |

> `/timeline`、`/timeline/events`、`/timeline/check` 均为**静态路径段**（无 `{event_id}` 动态段冲突），无需注册顺序注意（F11 的 generate 路径歧义处理在此不适用）。

### 3.2 请求/响应示例 — 事件 CRUD

**创建事件**（narrative_position 缺省 = 叙事末尾追加）:
```http
POST /api/v1/projects/3f2e1d4a-.../timeline/events
Content-Type: application/json

{
  "title": "林尘觉醒金手指",
  "description": "外门考核夜，林尘丹田中的古鼎第一次亮起。",
  "time_value": 317.5,
  "time_unit": "年",
  "time_display": "示例历 317 年秋",
  "timeline_flag": "",
  "era": "示例历",
  "era_value": 317.5
}
```
→ 201
```json
{
  "id": "9b1c2d3e-...", "project_id": "3f2e1d4a-...", "title": "林尘觉醒金手指",
  "description": "外门考核夜，林尘丹田中的古鼎第一次亮起。",
  "time_value": 317.5, "time_unit": "年", "time_display": "示例历 317 年秋",
  "narrative_position": 3, "timeline_flag": "",
  "era": "示例历", "era_value": 317.5, "era_scale": 1.0,
  "extra": {},
  "created_at": "2026-08-01T10:00:00Z", "updated_at": "2026-08-01T10:00:00Z"
}
```

> **v1.3（#1353）**：请求体的 `era` / `era_value` 写入 `extra.era` / `extra.era_value`（成对语义见 §2.8 E4）；不带纪元时两字段可省略，`extra` 保持 `{}`（既有行为**零变化**）。
> **v1.4（#1410）**：`era` / `era_value` 改落**正式列**——响应顶层新增 `era` / `era_value` / `era_scale`；`extra` **不再承载纪元**（不带纪元时为 `{}`）。**请求体形态与成对语义不变**（仅落点改正式列）。

**事件详情**（响应结构同创建响应，完整 TimelineEvent JSON）:
```http
GET /api/v1/timeline/events/9b1c2d3e-...
```
→ 200（TimelineEvent JSON，同创建响应；404 语义见 §3.4）

**列出事件（搜索 + 排序 + 分页）**:
```http
GET /api/v1/projects/3f2e1d4a-.../timeline/events?search=金手指&sort_by=time_value&sort_desc=false&offset=0&limit=20
```
→ 200
```json
{
  "items": [
    {"id": "9b1c2d3e-...", "title": "林尘觉醒金手指", "time_value": 317.5,
     "time_display": "示例历 317 年秋", "narrative_position": 3, ...}
  ],
  "total": 1, "offset": 0, "limit": 20
}
```

**更新事件（清除世界内时间、声明倒叙）**:
```http
PATCH /api/v1/timeline/events/9b1c2d3e-...
{ "time_value": "", "timeline_flag": "flashback" }
```
→ 200（更新后 TimelineEvent JSON，time_value 为 null，timeline_flag 为 "flashback"）

**删除事件（v1.1 真删语义）**:
```http
DELETE /api/v1/timeline/events/9b1c2d3e-...   → 204（物理删除，不可恢复）
```
> **v1.1（#211）变更**：原 `DELETE` 默认软删 + `?force=true` 物理删双路径**收敛为真删单路径**；原 `POST /timeline/events/{id}/restore` 端点**移除**。

### 3.3 请求/响应示例 — 双线总览与一致性检查

**双线总览**（事件时间线 + 叙事时间线两种投影，同一批事件）:
```http
GET /api/v1/projects/3f2e1d4a-.../timeline
```
→ 200
```json
{
  "project_id": "3f2e1d4a-...",
  "total": 3,
  "event_timeline": [
    {"id": "...", "title": "林尘拜入门派甲", "time_value": 315.0, "time_display": "示例历 315 年春", "narrative_position": 1},
    {"id": "...", "title": "林尘觉醒金手指", "time_value": 317.5, "time_display": "示例历 317 年秋", "narrative_position": 2},
    {"id": "...", "title": "宗门大比夺冠", "time_value": 319.0, "time_display": "示例历 319 年夏", "narrative_position": 4}
  ],
  "narrative_order": [
    {"id": "...", "title": "林尘拜入门派甲", "time_value": 315.0, "narrative_position": 1},
    {"id": "...", "title": "林尘觉醒金手指", "time_value": 317.5, "narrative_position": 2},
    {"id": "...", "title": "宗门大比夺冠", "time_value": 319.0, "narrative_position": 4}
  ]
}
```
> 两条视图均为**活动事件**全量（无分页，事件数通常 ≤ 数百，YAGNI）；`event_timeline` 按 `(time_value ASC NULLS LAST, narrative_position ASC)` 排序，`narrative_order` 按 `(narrative_position ASC, created_at ASC)` 排序。

**一致性检查（发现冲突）**:
```http
GET /api/v1/projects/3f2e1d4a-.../timeline/check?include_flashbacks=true
```
→ 200
```json
{
  "project_id": "3f2e1d4a-...",
  "checked": 4, "skipped": 1, "consistent": false,
  "conflicts": [
    {
      "conflict_type": "order_conflict",
      "prev": {"id": "...", "title": "林尘觉醒金手指", "time_value": 317.5,
               "time_display": "示例历 317 年秋", "narrative_position": 2, "timeline_flag": ""},
      "next": {"id": "...", "title": "外门往事", "time_value": 312.0,
               "time_display": "示例历 312 年", "narrative_position": 3, "timeline_flag": ""},
      "message": "叙事第 2 位事件「林尘觉醒金手指」（示例历 317 年秋）晚于叙事第 3 位事件「外门往事」（示例历 312 年）：叙事顺序与世界内时间矛盾。若为倒叙/插叙请给后叙事件标记 timeline_flag=flashback（或前叙事件标记 flashforward）；否则请修正事件时间或叙事位置。"
    }
  ],
  "flashbacks": [],
  "event_timeline": [ ... ],
  "narrative_order": [ ... ]
}
```

**一致性检查（合法倒叙，consistent=true）**:
```http
GET /api/v1/projects/3f2e1d4a-.../timeline/check
```
→ 200
```json
{
  "project_id": "3f2e1d4a-...",
  "checked": 4, "skipped": 0, "consistent": true,
  "conflicts": [],
  "flashbacks": [
    {
      "conflict_type": "flashback",
      "prev": {"id": "...", "title": "宗门大比夺冠", "time_value": 319.0,
               "time_display": "示例历 319 年夏", "narrative_position": 4, "timeline_flag": ""},
      "next": {"id": "...", "title": "外门往事", "time_value": 312.0,
               "time_display": "示例历 312 年", "narrative_position": 5, "timeline_flag": "flashback"},
      "message": "叙事第 5 位事件「外门往事」声明为倒叙（flashback）：其世界内时间（示例历 312 年）早于前叙事件（示例历 319 年夏），已标记，判定合法。"
    }
  ],
  "event_timeline": [ ... ],
  "narrative_order": [ ... ]
}
```

### 3.4 错误响应格式（沿用 F1/F2/F9/F10/F11/ADR-012）

```json
// 404 — 资源不存在
{"detail": "项目不存在"}
{"detail": "事件不存在"}

// 422 — 业务校验失败 / Pydantic 验证失败
{"detail": "事件标题不能为空"}
{"detail": "事件标题不能超过 100 个字符"}
{"detail": "事件描述不能超过 5000 个字符"}
{"detail": "世界内时间必须是有限数值"}
{"detail": "世界内时间超出允许范围（[-10^12, 10^12]）"}
{"detail": "纪元轴名不能超过 50 个字符"}
{"detail": "纪元轴内值必须是有限数值"}
{"detail": "清除纪元轴内值请传空字符串"}
{"detail": "叙事位置不能为负数"}
```

**异常映射表**:

| 异常/场景 | 状态码 | 响应 |
|-----------|--------|------|
| 项目/事件不存在（Service 返回 None） | 404 | 见上 |
| 无效 UUID 格式 | 404 | 统一解析失败处理（同 F9/F10/F11 `_parse_id`） |
| Pydantic `ValidationError`（含 time_value 清除传非空字符串） | 422 | FastAPI 自动生成 |
| DB 错误 | 500 | 全局处理器（loguru 记录，ADR-012/016） |

> **与 F9/F10/F11 的差异**：无 LLM 相关错误（无 `LLMRequestError`/生成/提取错误）；无同名冲突错误（无唯一约束，见 §2.4）——F12 的错误面是既有模块中最小的。

---

## 4. CLI 命令签名

遵循 F7 §5 全局约定：`--json` 统一信封 `{"ok": true, "data": ...}` / `{"ok": false, "error": {"code", "message"}}`；退出码 0/1/2/130；错误码 NOT_FOUND / VALIDATION_ERROR / **DB_ERROR**（**无 LLM_ERROR**——F12 无 LLM）；删除类命令二次确认 + `--force`；`--json` + 无 `--force` 的删除 → `VALIDATION_ERROR`（沿用 F7 §7）。`timeline` 组在 F12 落地时并入 F7 命令树（`cli/app.py` 注册，同 F9 character 组 / F10 world 组 / F11 outline 组）。

### 4.1 timeline 组（委托 TimelineService；无子组——F12 单实体，同 F10 world 组布局）

```bash
inkflow timeline create --project-id <uuid> --title <str> \
    [--description <str>] [--content-file <path>] [--time-value <float>] [--time-unit <str>] \
    [--time-display <str>] [--narrative-position <int>] [--timeline-flag <str>] \
    [--era <str>] [--era-value <float|"">] [--json]
    # --time-value 缺省 = 时间未知（None）；--narrative-position 缺省 = 叙事末尾追加
    # --era / --era-value: 纪元轴（#1353 §2.8）——轴名 + 轴内值（落 extra，零 DDL）；
    #   缺省（不传 --era）= 不设纪元；仅传 --era 时 body 不含 era_value 键（成对语义 E4）

inkflow timeline list --project-id <uuid> \
    [--search <str>] \
    [--sort <narrative_position|time_value|title|updated_at|created_at>] \
    [--sort-desc/--no-sort-desc] [--json]

inkflow timeline view --project-id <uuid> [--json]        # 双线总览（事件时间线 + 叙事顺序）

inkflow timeline check --project-id <uuid> \
    [--include-flashbacks/--no-include-flashbacks] [--json]   # 一致性检查（默认包含倒叙/插叙项）

inkflow timeline get --id <uuid> [--json]

inkflow timeline update --id <uuid> \
    [--title <str>] [--description <str>] [--content-file <path>] [--time-value <float|"">] [--time-unit <str>] \
    [--time-display <str>] [--narrative-position <int>] [--timeline-flag <str|"">] \
    [--era <str|"">] [--era-value <float|"">] [--json]
    # --time-value "" 表示清除世界内时间（置为未知）；--timeline-flag "" 表示清除标记（置为正叙）
    # --era "" 清除纪元（清空正式列 era / era_value，回到默认轴）
    # 未传 --era 时 --era-value 被忽略（成对语义，§2.8 E4）

inkflow timeline delete --id <uuid> [--force] [--json]     # v1.1 真删（--permanent 已移除）
# v1.1 移除: inkflow timeline restore --id <uuid> [--json]

inkflow timeline normalize --project-id <uuid> [--apply] [--json]   # #1409 项目级归一/重锚
    # 默认 dry-run（只报计划不写库）；--apply 落库（逐事件 PATCH，复用既有端点）
    # 报告: applied/segments/changed/total_valued/conflicts_before/conflicts_after/changes[]
```

> 命令名 `check` / `view` 与 Python 内置无关键字冲突（`check` 非保留字），Typer 命令注册正常。

### 4.2 输出格式

```bash
# 默认人类可读
✅ 事件创建成功: [林尘觉醒金手指]（示例历 317 年秋，叙事第 3 位）
✅ 事件已删除: [林尘觉醒金手指]
📋 双线总览: 共 5 个事件 — 事件时间线（世界内时间升序）: 1. 林尘拜入门派甲(315.0) 2. ...；叙事顺序: 1. 林尘拜入门派甲 2. ...
🔍 一致性检查: ✅ 一致（检查 4 个事件，跳过 1 个时间未知）
🔍 一致性检查: ⚠️ 发现 2 个冲突（检查 5 个事件，跳过 0 个）
   [冲突] 叙事第 2 位「林尘觉醒金手指」(示例历 317 年秋) 晚于叙事第 3 位「外门往事」(示例历 312 年) —— 未标记的倒叙/插叙
🔍 一致性检查: 💡 1 个已声明倒叙/插叙（不视为冲突）: 叙事第 5 位「外门往事」(flashback)

# --json 输出
inkflow timeline create --project-id ... --title "林尘觉醒金手指" --time-value 317.5 --json
→ {"ok": true, "data": {"id": "...", "title": "林尘觉醒金手指", "time_value": 317.5, ...}}

inkflow timeline check --project-id ... --json
→ {"ok": true, "data": {"project_id": "...", "checked": 5, "skipped": 0,
     "consistent": false, "conflicts": [...], "flashbacks": [...],
     "event_timeline": [...], "narrative_order": [...]}}

inkflow timeline get --id 00000000-0000-0000-0000-000000000000 --json
→ {"ok": false, "error": {"code": "NOT_FOUND", "message": "事件不存在"}}   # 退出码 1

inkflow timeline delete --id ... --json
→ {"ok": false, "error": {"code": "VALIDATION_ERROR", "message": "删除需 --force 或交互确认"}}  # 退出码 1

inkflow timeline normalize --project-id ... --json          # 默认 dry-run
→ {"ok": true, "data": {"applied": false, "segments": 7, "changed": 70, "total_valued": 82,
      "conflicts_before": 7, "conflicts_after": 0, "changes": [{"id": "...", "title": "...",
      "time_value": 3.0, "time_unit": "月", "new_time_value": 90.0, "new_time_unit": "日"}]}}
inkflow timeline normalize --project-id ... --apply --json  # 落库（applied=true）
```

---

## 5. 一致性检查模式（关键差异：确定性算法而非 AI）

> ⚠️ **本节是 F12 与 F9/F10/F11 样板的核心差异点**：F9/F10 的 §5 是「AI 提取管线」，F11 的 §5 是「AI 生成管线」，本模块的 §5 是**纯确定性的一致性检查算法**——**无 LLM、无模板、无重试、无合并**。输入是事件档案（双时间维度），输出是双线视图 + 冲突报告。算法性质（§5.3）保证其完全可测试：同一数据永远得到同一结果（快照断言友好）。

### 5.1 模式总览

```text
 ┌────────────────────────────────────────────────────────────┐
 │ 输入: TimelineService.check_consistency(project_id,         │
 │       include_flashbacks: bool = True)                      │
 └──────────────────────────┬─────────────────────────────────┘
                            ▼
 ① 校验项目存在（F1 ProjectRepository）→ 404
 ② 拉取项目全部活动事件（TimelineRepository.list_all，无分页）
 ③ 事件时间线视图: 按 (全局标量 ASC NULLS LAST, narrative_position ASC) 排序（全局标量按 era 分桶求，§5.2）
 ④ 叙事顺序视图:   按 (narrative_position ASC, created_at ASC) 排序
 ⑤ 相邻对扫描（在叙事顺序上相邻、且**比较键**均非 None 的事件对；键按 era 分桶求，§5.3）:
    对 (A, B)，若 全局标量(A) > 全局标量(B) → 逆序对:
      ├─ B.timeline_flag == "flashback"      → 记为 flashback（合法倒叙）
      ├─ A.timeline_flag == "flashforward"   → 记为 flashforward（合法插叙/预叙）
      └─ 否则                                → 记为 order_conflict（需修正）
    time_value(A) == time_value(B) → 同刻事件，不冲突
    time_value(A) 或 time_value(B) 为 None → 不参与比较（计入 skipped）
 ⑥ 返回 ConsistencyReport {checked, skipped, consistent,
    conflicts, flashbacks, event_timeline, narrative_order}
```

**模式要点**:
1. **纯内存确定性计算**：不调用任何 LLM/外部服务；同一事件集合 → 同一报告（可快照测试）
2. **O(n log n) 复杂度**：两次排序 + 一趟线性扫描；单项目事件量级（≤ 数百）下无性能压力
3. **增量友好**：报告基于当前全量活动事件计算，任何事件增删改后重跑即可；无增量状态需要维护（YAGNI）
4. **无副作用**：检查不修改任何数据；修正动作（改时间/改叙事位置/加标记）由作者通过 CRUD 端点执行后重查

### 5.2 双时间线定义与排序规则

| 时间线 | 排序键 | 排序规则 | 说明 |
|--------|--------|----------|------|
| **事件时间线**（世界内时间轴） | **全局标量**（默认轴 = `time_value` 归一日尺度，§2.7 S2/S4；纪元轴 = `to_global` 换算，§2.8 E11） | `(全局标量 ASC NULLS LAST, narrative_position ASC)` | 故事世界内事件发生的先后；**排序前按 `era` 分桶求全局标量**——默认轴按 `time_unit` 归一到「日」（`时/时辰` 按日锚点投影，未知/空单位 = 裸值）；纪元轴用 `to_global(era, era_value, era_scale)`；标量为 None 的事件排末尾（按叙事位置兜底） |
| **叙事时间线**（叙事顺序） | `narrative_position` | `(narrative_position ASC, created_at ASC)` | 小说叙述中事件被讲述的先后；单一整数序号，稳定排序 |

两条线是**同一批事件的两种投影**（非两份数据）：改 `time_value` 只移动事件时间线中的位置，改 `narrative_position` 只移动叙事时间线中的位置——这正是双线可能矛盾、需要一致性检查的原因。

### 5.3 检查算法（相邻对扫描）

**算法（v1.5：按 `era` 分桶 + 跨桶按换算后全局标量）**: 对叙事顺序（过滤比较键为 None 的事件后）的相邻事件对 `(A, B)` 逐一比较**比较键** `keys[e]`（**先按 `era` 分桶求键**，§2.8 E11）：
- **默认轴（`era == ""`）**：`keys[e] = 归一(单位, time_value, 日锚点)`（§2.7 S2/S4，**与 v1.4 逐字段相同**）；
- **纪元轴（`era != ""`）**：`keys[e] = to_global(era, era_value, era_scale)`（E11 换算后的**全局标量**；`era_value` 为 None → 键为 None）。

若 `keys[A] > keys[B]` 则为逆序对，按 §5.4 分类。**同桶**（`era` 相同）按上述统一口径比较；**跨桶**（`era` 不同）按双方**换算后的全局标量**比较（两侧都已是全局量纲）——即「跨纪元**经换算**比较」（ADR-065 §2.1，R6-5 裁定 = 不降级）。

**完备性论证（可测试性的数学基础）**: 序列单调非降 ⟺ 序列不存在相邻逆序对。因此「修正所有报告出的 order_conflict」等价于「使叙事顺序与世界内时间顺序一致」——相邻对扫描**不会漏报任何需要修正的矛盾**，且报告天然按叙事顺序排列、逐条可执行。**归一不改变该论证**：归一是对全序列施加的**同一单调映射的前半部**（单位换算 + 日锚点投影），比较仍在归一后的全序上进行。

**复杂度**: 排序 O(n log n) + 扫描 O(n)。

**伪代码**:
```text
events = list_all(project_id)                     # 叙事序（narrative_position ASC, created_at ASC）
keys   = normalized_days(events)                  # §2.7 S2/S4：单位归一 + 时/时辰 日锚点投影（None 保持 None）
P      = [e for e in events if keys[e] is not None]   # 参与比较集合
skipped = len(events) - len(P)
conflicts, flashbacks = [], []
for i in range(len(P) - 1):
    A, B = P[i], P[i + 1]
    if keys[A] > keys[B]:                          # ← 比较归一值，不是裸 time_value
        if B.timeline_flag 命中倒叙词表:
            flashbacks.append(TimelineConflict("flashback", A, B, ...))
        elif A.timeline_flag 命中插叙词表:
            flashbacks.append(TimelineConflict("flashforward", A, B, ...))
        else:
            conflicts.append(TimelineConflict("order_conflict", A, B, ...))
consistent = (len(conflicts) == 0)
```

### 5.4 冲突分类与合法性定义

**核心定义**：叙事顺序与世界内时间顺序一致 = 正叙（合法）；不一致 = 逆序对，其合法性**由作者显式声明**决定——声明制（详见 §12 决策记录）：

| 类型 | 判定条件 | 语义 | 计入 | 处理 |
|------|----------|------|------|------|
| `order_conflict` | 逆序对且 `next` 未标记 flashback、`prev` 未标记 flashforward | **未声明的倒叙/插叙**（时间倒流硬伤） | `conflicts`（consistent=false） | 作者修正：调整时间/叙事位置，或显式加标记 |
| `flashback` | 逆序对且 `next.timeline_flag == "flashback"` | **合法倒叙**（先叙现在、后补过去，如「外门往事」回忆） | `flashbacks`（不影响 consistent） | 无需处理（提示信息） |
| `flashforward` | 逆序对且 `prev.timeline_flag == "flashforward"` | **合法插叙/预叙**（先叙未来、再回现在，如开篇「三日后」场景） | `flashbacks`（不影响 consistent） | 无需处理（提示信息） |

**规则要点**:
- `consistent` **仅由 `conflicts` 决定**：已声明的倒叙/插叙不影响一致性子（它们是合法的叙事手法，不是错误）
- 未在建议词表中的 `timeline_flag` 值（如拼写错误 `flshback`）**等同未标记**：逆序对仍报 `order_conflict`（声明不生效）
- `time_value` 相等（同刻事件）：**不冲突**——同时发生的事件叙事顺序可任意排列（**比较的是归一值**：`8 日` 与 `3 月` 归一为 `8` 与 `90`，**不相等**）
- **跨单位不误判（§2.7 S2/S3）**：`8 日` 后接 `3 月` → 归一 `8 < 90` → 正序，**不报**倒叙；反向 `3 月` → `8 日`（`90 > 8`）→ 报 `order_conflict`（真实倒退）
- **跨纪元经换算比较（v1.5，§2.8 E11）**：不同 `era` 的事件**不直比 `era_value`**，而按 `to_global` 换算后的**全局标量**比较——例：甲纪元 `scale=1`、乙纪元 `scale=2`，「甲 1 单位 = 乙 2 单位」（换算后同值）→ **不报**冲突；`era_scale` 缺省 `1.0`（未填）时退化为「直比轴内值」，与 T1 行为一致（**不误报也不多报**）
- **`时/时辰` 不参与累计（§2.7 S4）**：`第 8 日` 后的 `3 时` 归一为 `8 + 3/24 = 8.125`（**不是** `0.125`，也不是 `/24` 累计）；同一日内的 `3 时 → 5 时` 仍保序
- **未知/空单位不变（§2.7 S5）**：`time_unit` 为空或未列举 → 因子 1，比较结论与本 spec v1.1 完全一致（反例守护）
- `time_value` 为 None（时间未知）：**跳过**（计入 `skipped`，不参与比较、不报冲突）——未知时间没有「错误」可言
- `include_flashbacks=false` 时 `flashbacks` 返回空列表（服务层不收集），`conflicts` 与 `consistent` 不受影响
- **冲突消息同时给出原始表达与当前数值（#1409）**：`_time_label` 输出形如 `示例历 317 年秋（time_value=317.5）`、`3.0月（time_value=3.0），归一=90日`；无 `time_display`/`time_unit` 时保持裸数值（向后兼容）。**避免「改了数据看不出变化」**——消息必须显示**当前** `time_value`，而不是仅显示原始表达

### 5.5 输入约束与边界

| 约束 | 值 | 说明 |
|------|-----|------|
| 检查范围 | 项目内全部事件（v1.1 真删后无软删态） | 无分页/过滤参数（YAGNI） |
| include_flashbacks | 默认 true | false = 报告不含已声明的倒叙/插叙项 |
| 0 / 1 个事件 | consistent=true，checked=0/1 | 空时间线无矛盾可言 |
| 全部时间未知 | checked=0, skipped=n, consistent=true | 未定时间不产生矛盾 |
| 全逆序（完整倒叙长线，未标记） | n-1 条 order_conflict | 每条都是独立可修正项 |
| 混合序列（如 [10, 5, 8]） | 1 条冲突（10,5） | 相邻对报告；修正后重查即收敛（完备性 §5.3） |
| **跨单位混合**（如 [8日, 3月]） | **0 条冲突** | 归一后 `8 < 90`（§2.7 S2）；反向 `[3月, 8日]` → 1 条 order_conflict |
| **`时/时辰` 参与**（如 [8日, 3时, 9日]） | 0 条冲突 | `3时` → `8 + 0.125`（当天时刻锚定，§2.7 S4）；若写成累计 `/24` 则 `0.125 < 8` 会误报倒叙 |
| **空/未知单位** | 与本 spec v1.1 结论一致 | 因子 1（§2.7 S5 反例守护） |
| **纪元轴（`era` 非空）** | **参与**（v1.5：按 `to_global` 换算后比较） | 检查按 `era` **分桶**：默认轴用归一日尺度、纪元轴用换算后全局标量（§2.8 E11 / §5.3）；`era_value` 为 None 的纪元事件 → 键为 None → 计入 `skipped`（不报冲突） |
| **段内计数器型历史数据**（同单位但跨段重置，如 `…30日 → 3日…`） | 报 order_conflict（**不是误报**：该数据在同一时基上确实自相矛盾） | 由 §5.7 `timeline normalize` 一次性重锚修复；归一本身**无法**修（无基准信息，任何自动猜测都会抹平真实逆序） |

### 5.6 一致性检查 vs 提取/生成：差异对照表

| 维度 | F9/F10 提取（样板） | F11 生成（样板） | F12 一致性检查（本模块） |
|------|--------------------|--------------------|--------------------------|
| 输入 | 章节文本 `text`（必填） | 项目信息 + 可选 prompt/num_chapters | 事件档案（双时间维度，库内已有） |
| 方向 | 文本 → 实体（沉淀既有信息） | 设定 → 规划（创作新内容） | 双线 → 报告（验证一致性） |
| 引擎 | LLM（模板 + 解析 + 修复重试） | LLM（模板 + 解析 + 修复重试） | **确定性算法（无 LLM）** |
| 模板 | `{module}_extract.yaml` | `outline_generate.yaml` | **无模板**（无 `infrastructure/llm/templates/`） |
| 副作用 | 合并落库（单事务） | 新建落库（单事务，save 可跳过） | **无副作用**（只读计算） |
| 幂等性 | 同文本二次提取 → 空 diff | 不承诺幂等 | **严格幂等**（同数据同报告） |
| 失败模式 | LLMRequestError / 解析重试耗尽 | 同左 | 无（纯内存计算，仅 DB 读取） |
| 测试方式 | Mock LLM 分支覆盖 | 同左 | **快照断言 + 序列构造用例**（最易测试的一代） |

### 5.7 项目级归一/重锚（`timeline normalize`，#1409 §2.7 S7）

**问题**：`#1323` 之前的提取器把 LLM 的**段内计数器**（「本段第几天」）直接落库 → 同一项目内 `time_value` 不在同一坐标系（实测：修屋顶段 `1→8`、年货段 `28→30`、夜袭段 `7→7.99`、另有一段 `3.0 月`）。段与段之间不可比 ⇒ 校验层无论怎么归一都无法还原真实顺序（归一只能修「跨单位」，修不了「同单位跨段重置」）。

**定位**：一次性、**显式**、**用户裁决**的数据修复工具（**不是**自动迁移、**不是**判定层逻辑）：

| 维度 | 规定 |
|------|------|
| 命令 | `inkflow timeline normalize --project-id <uuid> [--apply]`（**默认 dry-run**，只报计划不写库；`--json` 输出完整计划） |
| 算法 | ① 单位归一（§2.7 S2，`时/时辰` 用日锚点，§2.7 S4）；② 按**叙事顺序**遍历**带值且未声明**倒叙/插叙的事件；③ **数值回落 = 新叙事段**，新段起点接在**上一段末尾**（`offset = prev_global`），**段内保留原有相对天数**（`g = offset + (v − 段内最小)`）；④ 单位统一写「日」；⑤ `time_display` 为空时归档**原表达式**（`f"{原值}{原单位}"`） |
| 豁免 | `time_value = None` 与**任一** `timeline_flag` 非空（已声明倒叙/插叙）的事件**完全不改**（其合法性由声明制保证，§5.4） |
| 幂等 | 对已归一/单调数据运行 → **0 处改动**（§2.7 S8）；重复 `--apply` 不产生漂移 |
| 报告（dry-run 与 apply 同构） | `applied: bool`、`segments: int`（识别出的叙事段数）、`changed: int` / `total_valued: int`、`conflicts_before: int`、`conflicts_after: int`、`changes: [{id, title, time_value, time_unit, new_time_value, new_time_unit}]` |
| ⚠️ 风险声明 | 重锚是**单调投影**：对未声明事件，它按构造消除全部逆序（`conflicts_after = 0`）。因此它是「**让历史数据自洽**」的工具，**不是**「修故事时间线」的工具——真实叙事错误（该报冲突的）会被一并吸收。故 **dry-run 默认 + 显式 `--apply`**，作者须先看 `conflicts_before` 报告再决定 |
| 边界 | 无事件 / 全部时间未知 → 计划为空；单段单调序列 → `segments=1, changed=0`；`source_chapter_id` 为 NULL 的手工事件同样参与（按叙事序） |
| 面 | CLI（HTTP）：`GET /projects/{id}/timeline`（全量双线总览，无分页）+ 逐事件 `PATCH /timeline/events/{id}` 复用**既有端点**——**不新增 API 契约**（无 OpenAPI 快照变更）；GUI 接线归后续（#1353/#1410 时基工作） |
| 与归一的关系 | 归一（§5.2/§5.3，只读投影）= **判定层**；重锚（本节，写库）= **数据层**。二者互补：归一让跨单位数据可比；重锚让段内计数器型历史数据落回同一时基 |

> **为什么不用「抬平到前一条」（`g = max(g, prev)`）**：抬平会把整卷的相对天数压成一条平线（级联丢失段内信息），实测虽也能到 0 冲突，但**代价是抹平数据**——违反 S7 的「保留段内相对天数」。实测对比见 #1409 报告。

---

## 6. 时间线组织规则

（对应 F9 §6「关系图谱与分组管理规则」/ F10 §6「分类与查询规则」/ F11 §6「大纲/弧线/情节点组织规则」的位置；F12 单实体，本节承载双时间线语义、标记语义与查询规则）

### 6.1 事件与双线语义

- **事件 = 故事世界中的一个时刻/片段**（项目级实体，无父实体、无子实体）
- 每个事件**同时属于两条时间线**（同一批数据的两种投影）：
  - **事件时间线**（世界内时间轴）：`time_value` 升序；时间未知排末尾
  - **叙事时间线**（叙事顺序）：`narrative_position` 升序（created_at ASC 稳定）
- 双线**独立可编辑**：改世界内时间不影响叙事位置，反之亦然；双线矛盾由一致性检查（§5）揭示并给出可执行修正项
- 已删除的事件物理不存在，不进入任何视图与检查

### 6.2 timeline_flag 语义

- 建议值：`""`（正叙，默认）、`flashback`（倒叙）、`flashforward`（插叙/预叙）
- 标记是**作者声明**：声明后对应的逆序对不再报 `order_conflict`（§5.4）
- `timeline_flag` 是自由文本（≤ 20 字符），**受控词表归 F14**（同 F9 relation_type / F11 type 处理）；未在建议词表中的值等同未标记

### 6.3 搜索与排序（事件列表，沿用 F1 §6/F9 §6.3/F10 §6.2/F11 §6.3）

| 参数 | 默认值 | 约束 | 说明 |
|------|--------|------|------|
| `search` | — | — | 对 title 不区分大小写子串匹配（icontains） |
| `sort_by` | `narrative_position` | `narrative_position` / `time_value` / `title` / `updated_at` / `created_at` | 排序字段（时间线语境下叙事顺序为自然默认） |
| `sort_desc` | `false` | — | 降序（`time_value` 排序时未知时间始终排末尾，NULLS LAST） |
| `offset` / `limit` | 0 / 50 | offset ≥ 0, limit [1, 100] | 分页 |

- **双线总览与一致性检查**：全量返回，无分页/过滤参数（事件数通常 ≤ 数百，YAGNI）
- 事件**内容全文检索**不在 F12 范围（F22 搜索服务，§10）

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 创建事件标题为空/全空白 | 422: "事件标题不能为空" |
| 创建事件标题 > 100 字符 | 422: "事件标题不能超过 100 个字符" |
| 事件 description > 5000 字符 | 422: "事件描述不能超过 5000 个字符" |
| time_value 为 NaN / ±Inf | 422: "世界内时间必须是有限数值" |
| time_value 超出 [-10^12, 10^12] | 422: "世界内时间超出允许范围（[-10^12, 10^12]）" |
| time_unit > 20 / time_display > 100 / timeline_flag > 20 字符 | 422（字段校验） |
| narrative_position < 0 | 422: "叙事位置不能为负数" |
| 创建事件时项目不存在 | 404: "项目不存在" |
| 获取/更新/删除不存在的事件 | 404: "事件不存在" |
| 重复删除同一事件 | 404: "事件不存在"（不可恢复） |
| 恢复不存在的事件 | **（v1.1 移除）** restore 端点/命令已不存在（真删语义无恢复场景） |
| 更新 time_value 传 ""（清除时间） | ✅ 成功，time_value 置 None（时间未知） |
| 更新 time_value 传非空字符串（如 "abc"） | 422（清除时间只接受空字符串） |
| 更新 timeline_flag 传 ""（清除标记） | ✅ 成功，timeline_flag 置 ""（正叙） |
| 创建/更新传入 `era`（未带 `era_value`） | ✅ 成功；`extra.era` 写入，`extra.era_value` **不存在**（轴内值未知） |
| 更新 `era=""` | ✅ 成功；`extra` 的 `era` / `era_value` 两键**删除**（事件回到默认轴） |
| 更新只传 `era_value`（未传 `era`） | ✅ 成功但 `era_value` **被忽略**（成对语义，§2.8 E4）；`extra` 不变 |
| `era` > 50 字符 / `era_value` 为 NaN、±Inf | 422（字段校验） |
| 事件带纪元（`era` 非空）参与一致性检查 | **v1.5 起参与**：按 `era` 分桶，纪元轴用 `to_global` 换算后全局标量比较（§2.8 E11 / §5.3）；`era_value` 为 None → 计入 `skipped`。**默认轴（`era=""`）结论与 v1.4 逐字段相同**（反例守护） |
| 创建/更新 time_value 为 None（时间未知） | ✅ 成功；事件时间线排末尾，一致性检查计入 skipped |
| 一致性检查：0 / 1 个活动事件 | 200，consistent=true，checked=0/1 |
| 一致性检查：全部事件时间未知 | 200，checked=0, skipped=n, consistent=true |
| 一致性检查：逆序对且 next 标记 flashback | 200，flashbacks 含该项，**不算冲突**，consistent 不受影响 |
| 一致性检查：逆序对且 prev 标记 flashforward | 200，flashbacks 含该项，**不算冲突** |
| 一致性检查：逆序对且无标记 / 标记为未知值（如 "flshback"） | 200，conflicts 含该 order_conflict，consistent=false |
| 一致性检查：同刻事件（time_value 相等） | 不冲突（叙事顺序可任意） |
| 一致性检查：跨单位相邻事件（如 `8 日` → `3 月`） | 200，**不冲突**（归一后 `8 < 90`，§2.7 S2）；反向（`3 月` → `8 日`）→ order_conflict |
| 一致性检查：`time_unit` 为空 / 未列举（如 `纪元`） | 行为与本 spec v1.1 **完全一致**（因子 1，裸值比较，§2.7 S5 反例守护） |
| 一致性检查：`时/时辰` 且无前置日级事件 | 日锚点取 0（归一值 ∈ `[0, 1)`）；报/不报与本 spec v1.1 一致（不产生新假阳性） |
| 一致性检查：段内计数器型数据（跨段回落） | 报 order_conflict（数据在同一时基上确实矛盾）→ 由 `timeline normalize` 修复（§5.7） |
| `timeline normalize` 默认（无 `--apply`） | 200，报告 `applied=false`，**不写库**（dry-run 为默认） |
| `timeline normalize --apply` | 逐事件 PATCH；报告 `applied=true` 且 `changed` == 实写条数 |
| `timeline normalize` 对已归一/单调数据 | `changed=0`（幂等，§2.7 S8） |
| `timeline normalize` 无带值事件 | `segments=0, changed=0`，不报错 |
| `timeline normalize`：已声明倒叙/插叙 / 时间未知 | 该事件不出现在 `changes`（完全不改） |
| 一致性检查：include_flashbacks=false | flashbacks 返回空列表；conflicts/consistent 不变 |
| 一致性检查：项目不存在 | 404: "项目不存在" |
| 删除事件（v1.1 真删） | 204；不进入双线视图与一致性检查（物理不存在） |
| 项目硬删除 | 事件级联物理删除（FK CASCADE） |
| 事件列表搜索无结果 / 分页越界 | 200: 空 items（同 F1） |
| 双线总览无活动事件 | 200: `{"project_id": "...", "total": 0, "event_timeline": [], "narrative_order": []}` |
| CLI 删除类命令无 `--force` | 二次确认；`--json` 下 → VALIDATION_ERROR（沿用 F7 §7） |

---

## 8. 文件结构

遵循 ADR-007v2 包结构，与 F9/F10/F11 真实源码树一一对应。新增/修改文件：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── timeline.py             ← CREATE: TimelineEvent, TimelineEventCreate,
│   │   │                               TimelineEventUpdate, TimelineView,
│   │   │                               ConsistencyReport, TimelineConflict,
│   │   │                               TimelineEventRef
│   │   └── __init__.py             ← MODIFY: 导出新模型
│   ├── ports/
│   │   ├── timeline_repository.py  ← CREATE: TimelineRepositoryProtocol
│   │   ├── timeline_errors.py      ← CREATE: TimelineServiceError / TimelineNotFoundError /
│   │   │                               ProjectNotFoundError（无冲突类错误——无唯一约束，见 §2.4）
│   │   └── __init__.py             ← MODIFY: 导出
│   └── services/
│       ├── timeline_service.py     ← CREATE: TimelineService（事件 CRUD + view + check_consistency）
│       └── __init__.py             ← MODIFY
├── infrastructure/
│   └── database/
│       ├── models/
│       │   ├── timeline.py         ← CREATE: TimelineEventORM（索引: project_id /
│       │   │                           (project_id, narrative_position) / (project_id, time_value)，
│       │   │                           v1.1 真删语义无软删除标记）
│       │   └── __init__.py         ← MODIFY: 注册 ORM（create_tables 依赖）
│       └── repositories/
│           ├── timeline_repo.py    ← CREATE: SQLiteTimelineRepository
│           └── __init__.py         ← MODIFY
├── api/
│   ├── routers/
│   │   ├── timeline.py             ← CREATE: 8 个端点（事件 CRUD + 双线视图 + 一致性检查）
│   │   └── __init__.py             ← MODIFY
│   ├── deps.py                     ← MODIFY: get_timeline_service
│   └── app.py                      ← MODIFY: 注册 timeline.router
└── cli/
    ├── commands/
    │   ├── timeline.py             ← CREATE: timeline 组（create/list/view/check/get/update/
    │   │                               delete 7 命令；【v1.1 移除 restore】）
    │   └── __init__.py             ← MODIFY
    └── app.py                      ← MODIFY: 注册 timeline 命令组

backend/tests/
├── unit/
│   ├── test_timeline_models.py     ← CREATE: 领域模型/DTO 验证（含 time_value 清除语义）
│   ├── test_timeline_repo.py       ← CREATE: 仓储集成测试（in-memory SQLite，含双索引/真删）
│   ├── test_timeline_service.py    ← CREATE: 服务测试（事件 CRUD + next_position + 业务校验）
│   ├── test_timeline_check.py      ← CREATE: 一致性检查算法专项（构造序列用例 + 快照断言，§5）
│   └── test_timeline_api.py        ← CREATE: API 集成测试（Mock Service）
└── test_cli_timeline.py            ← CREATE: CLI 测试（Mock TimelineService，信封/退出码）
```

> **与 F11 §8 的差异**：无 `infrastructure/llm/templates/` 目录（F12 无 LLM，§5 为确定性算法）；无生成管线文件（无 `_outline_generator.py` 对应物）。测试文件位置与现有树一致（仓储/API 集成测试放 `tests/unit/`，CLI 测试放 `tests/` 根，同 F9/F10/F11）。

### 8.1 TimelineRepositoryProtocol（参照 F10 `world_repository.py` Protocol 风格）

```python
class TimelineRepositoryProtocol(Protocol):
    """时间线事件仓储端口.

    按 spec §2: 单实体（无子实体、无唯一约束）；事件列表默认按
    narrative_position ASC 排序；双线视图/一致性检查需要全量事件
    （list_all）。v1.1 真删语义：删除即物理删除，已删事件不存在。

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9/F10/F11）。
    """

    # ── TimelineEvent ──
    async def add(self, event: TimelineEvent) -> TimelineEvent: ...
    async def get(self, event_id: int) -> TimelineEvent | None: ...
    async def list(self, project_id: int, search: str | None = None,
                   sort_by: str = "narrative_position", sort_desc: bool = False,
                   offset: int = 0, limit: int = 50) -> tuple[builtins.list[TimelineEvent], int]: ...
    async def list_all(self, project_id: int) -> builtins.list[TimelineEvent]: ...  # 双线/检查用全量事件
    async def next_position(self, project_id: int) -> int: ...   # 项目内 max(narrative_position)+1（无事件时 = 1）
    async def update(self, event: TimelineEvent) -> TimelineEvent: ...
    async def hard_delete(self, event_id: int) -> bool: ...   # v1.1 真删（唯一删除路径）
    # v1.1 移除: soft_delete / restore（#211）
```

> 仓储层方法入参用 int（与 F9/F10/F11 RepositoryProtocol 一致）；Service 负责 UUID ↔ int 转换（沿用 F1 `_to_int_id` 模式）。`next_position` 在 `add` 前调用（narrative_position=None 时）。`list_all` 按 `(narrative_position ASC, created_at ASC)` 返回（叙事顺序），检查算法直接消费。

---

## 9. 测试策略

### 测试层次（沿用 ADR-018 三层目录 + pytest markers；六层结构同 F9/F10/F11 §9）

```text
单元测试: 领域模型/DTO 验证（含 time_value 清除语义）       ~12 cases
集成测试: SQLiteTimelineRepository（in-memory SQLite）      ~14 cases
服务测试: TimelineService（Mock Repository）                ~12 cases
检查算法: 一致性检查专项（构造序列 + 快照断言）               ~14 cases
API 测试: 8 端点（Mock Service）                           ~10 cases
CLI 测试: timeline 组（Mock TimelineService）              ~14 cases
```

### 关键测试场景

**领域模型**: 事件 title 空/空白/超长 → ValidationError / time_value 为 None 合法（时间未知）/ NaN、±Inf → ValidationError / time_value 越界（±1e12 之外）→ ValidationError / time_unit/time_display/timeline_flag 超长 → ValidationError / narrative_position 负数 → ValidationError / TimelineEventUpdate 部分更新语义（time_value None 不修改、"" 清除、非空字符串 → 422；timeline_flag "" 清除）/ TimelineEventCreate narrative_position=None 合法 / 检查模型 schema（TimelineConflict conflict_type 三值、ConsistencyReport 默认空列表）

**仓储**: 事件 CRUD 往返 / `list` 搜索与分页 / `list` 各 sort_by 排序（narrative_position 默认升序；time_value 排序 NULLS LAST）/ `list_all` 全量事件 / `next_position`（空项目 → 1、追加 → max+1）/ 真删后 get 返回 None / 项目硬删除 → 事件级联（FK CASCADE）/ narrative_position 重复时 created_at ASC 稳定排序

**服务**: 事件创建/更新/真删全流程 / next_position 编排（position=None 时先查后建）/ era 成对语义编排（§2.8 E4：未传=不变、`""`=删两键、非空=写入且保留未传的 `era_value`）/ 项目不存在各操作 → None → 404 / 事件不存在各操作 → None → 404 / 更新 time_value "" → 置 None 编排 / view 编排（两种排序视图）/ check_consistency 编排（项目不存在 → 404；repo 未注入 → 配置错误）

**一致性检查（专项，构造序列用例 + 快照断言）**:
- 正叙序列（如 [1,2,3,4]）→ 无冲突，consistent=true，checked=4
- 单逆序对（[1,3,2,4]）→ 1 条 order_conflict（相邻对 3,2）
- 混合序列（[10,5,8]）→ 1 条冲突（10,5）——验证相邻对报告与完备性
- 全逆序（[4,3,2,1]，未标记）→ 3 条 order_conflict
- 逆序对 next 标记 flashback → flashbacks 含该项，conflicts 为空，consistent=true
- 逆序对 prev 标记 flashforward → flashbacks 含该项（flashforward 类型）
- 未知标记值（"flshback"）→ 等同未标记 → order_conflict
- 未标记逆序 + 已标记逆序混合 → 只报未标记为冲突
- 同刻事件（[3,3,4]）→ 不冲突
- 时间未知事件 → 计入 skipped，不参与比较（[None, 5, 3] → checked=2, skipped=1, 1 条冲突）
- 全部时间未知 → checked=0, skipped=n, consistent=true
- 0 / 1 个事件 → consistent=true
- include_flashbacks=false → flashbacks 为空列表，conflicts/consistent 不变
- 已删除事件不参与检查（物理不存在）
- **确定性/快照**：同一事件集合两次检查 → 逐字段相等（快照断言）
- 报告视图正确性：event_timeline 按 time_value 升序（未知排末尾）、narrative_order 按叙事位置升序
- **#1353 纪元承载（§2.8）**：`era` / `era_value` → `extra.era` / `extra.era_value` 往返一致；`era=""` 删除两键；只传 `era_value`（未传 `era`）→ `extra` 不变；`era` 超 50 字符 / `era_value` 非有限 → ValidationError；**反例守护**：未设纪元事件的 CRUD / 双线视图 / `check` 结论与本 spec v1.2 **逐字段相等**（纪元不进检查）
- **#1409 单位归一**：`[8日, 3月]` → 0 冲突（反向 `[3月, 8日]` → 1 冲突）；真逆序（同单位 `[10, 5]`）仍报；`时/时辰` 锚定（`[8日, 3时]` → 0 冲突，且 `3时` 归一 = 8.125，**不是** 0.125）；空/未知单位结论与 v1.1 一致（反例守护）；`event_timeline` 视图按归一日尺度排序
- **#1411 跨纪元换算（v1.5）**：`to_global` 边界（`scale` 非 1 换算正确；`era_value` 为 None / 负数 / 0；`era` 为空 → None；`scale <= 0` → 按 1.0）；**甲纪元 1 单位 = 乙纪元 2 单位**（甲 `scale=1` `era_value=1`、乙 `scale=2` `era_value=2` → 换算后同为 1）→ **0 冲突**；反向（甲 `scale=1` `era_value=5` vs 乙 `scale=2` `era_value=2` → 全局 5 vs 1）→ 1 条 order_conflict；**假阳性归零**（对照 #1409 的 7 → 0 口径）：跨纪元数据不再产生「未声明的倒叙」误报；**默认轴零变化**：`era=""` 事件的 `check` 结论与 v1.4 **逐字段一致**（反例守护）；`check_event` 与 F34 审计规则在分桶后与 `check_consistency` 同口径（各一条断言）

**项目级归一/重锚（#1409 §5.7 专项）**：跨段回落序列（如 `[1,8] → [28,30] → [7,7.99]`）→ 续接为单调序列、段内相对差不丢；已声明倒叙/插叙事件**完全不改**；`time_value=None` 不改；单位一并归一到「日」；`time_display` 为空时归档原表达式；**幂等**（对已归一序列再跑 → `changed=0`）；dry-run 不写库（`applied=false`）；`--apply` 逐事件 PATCH 且改写条数 == `changed`

**API**: 8 端点成功路径 / 404 全路径（项目/事件）/ 422 字段校验（标题空/超长、time_value 非有限/越界、清除传非空字符串）/ 无效 UUID → 404 / 双线总览 200 / check 200（include_flashbacks 两态）/ check 冲突示例与合法倒叙示例响应结构

**CLI**: 各命令成功路径与参数透传（含 `--era` / `--era-value`，`--era ""` 清除）/ 信封格式与退出码 0/1/2 / delete 二次确认 + `--force` / `--json` + delete 无 `--force` → VALIDATION_ERROR / check 人类可读摘要（一致 vs 冲突 vs 已声明倒叙）与 `--json` 完整报告 / NOT_FOUND 错误信封 / `--time-value ""` 清除语义透传

### 覆盖率目标

- F12 模块行覆盖率 **≥ 80%**（DTO 验证 100%、检查算法全分支、双线排序路径，同 F9/F10/F11）
- 全仓覆盖率 **≥ 60%**（0.2.0 DoD，ADR-019）
- CI 门禁：ruff + mypy + pytest 全绿（ADR-017/018）；domain/ 零 FastAPI/Typer/SQLAlchemy/LangChain import（全局约束，ADR-002/015——F12 无 LLM，天然满足）

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|----------|
| 事件 AI 提取/生成（章节文本 → 事件、LLM 生成事件序列、自然语言时间解析「三年前」→ 数值） | **F14 统一提取服务**（P1-06，Issue #44）——F12 一致性检查为确定性算法，无 LLM；F14 落地时复用本模块实体/字段约定（time_value 数值化是 F14 提取难点，见待澄清 Q1） |
| 跨模块全维度一致性审计（角色/世界观/大纲/时间线/伏笔联动审计） | **F15 审计服务**（P1-07，Issue 待创建）——F12 只做时间线**内部**双线一致性 |
| 事件 ↔ 实际章节强绑定（chapter_id、叙事位置 = 章节序 + 段序） | Phase 2+——同 F11 边界声明：F12 管「时间线数据」，F2 管「已创建卷/章」，互不绑定；章节级叙事位置归 Phase 2+ |
| 树形时间线 / 平行时间线（多线分支、平行世界合并） | Phase 2+——MVP 单线（世界内时间全序 + 叙事顺序全序），多线/分支归 Phase 2+（决策见 §2.2/§12） |
| ~~时间单位换算（纪元→年 自动换算、季节偏移）~~ | **（v1.2 部分纳入）** 单位→「日」归一（年 365/月 30/周 7/日 1）+ `时/时辰` 日锚点投影 + 段续接重锚**已做**（§2.7 S2/S4/S7，判定层 + `timeline normalize` 工具）；**仍不做**：纪元/历法换算与季节偏移（可配置纪元流速比、闰月、多历法并存）→ 归 **#1353（0.16.0 多纪元最小落地）/ #1410+#1411（0.17.0 完整历法引擎）**。原「收益不成比例（YAGNI）」结论**被 #1409 实测推翻**：不做归一的代价是审计假阳性（7 条）。**（v1.3 再部分纳入）** 多纪元的**承载 + 轴选择器**已做（§2.8：`extra.era` / `extra.era_value`，零 DDL）；**仍不做**：纪元流速换算、跨纪元比较与分桶、`era` 正式列 → 归 #1410 / #1411 / #1412 |
| 时间区间事件（起止时间、区间重叠检测） | Phase 2+——MVP 单点时间（待澄清 Q1） |
| 事件参与角色多对多（participants 表，供 F14 提取直接落库） | Phase 2+——MVP 经 extra 预留（待澄清 Q2） |
| 最小修正建议（LIS 算法给出最少调整事件集） | Phase 2+——MVP 相邻对报告 + 双线视图，人工修正（待澄清 Q3） |
| 事件向量索引 / 语义检索（ADR-013 `timeline_event` 实体类型：写作涉及时间跳跃时检索） | F14/RAG 集成（Phase 2）——索引内容来自本模块事件档案，见 §11 |
| 拖拽排序 UI / 批量重排（narrative_position 自动重排算法） | F18 Web UI（0.3.0）；MVP 支持手动设置 position |
| 事件全文检索 | F22 搜索服务（Phase 3） |
| 时间线可视化（时间轴渲染）/ 导出 | F18 Web UI（0.3.0）/ F21 导出服务（0.6.0） |
| 事件变更审计日志 | F15 审计服务（Phase 2） |

---

## 11. 依赖关系

与 F1 §11 / F9 §11 / F10 §11 / F11 §11 已声明依赖保持一致（F12 在其上调整——**移除 LLM 依赖，保持单实体依赖面**）：

```text
F12 依赖:
  F1 (project_service) ✅ — 项目存在性校验（404）；双线视图/一致性检查的项目归属校验
  F2 (chapter_service) — 边界声明（非硬依赖）：叙事位置用单一序号，不绑定 F2 卷/章；
                           章节级位置映射归 Phase 2+（§10）
  F5 (llm_service)     — 不依赖：F12 无 LLM（一致性检查为确定性算法，§5）；
                           domain/ 零 LangChain import 门禁天然满足

F12 被依赖:
  F7 (CLI)             ✅ — timeline 命令组并入 F7 命令树（cli/app.py 注册）
  F13 (伏笔)            ⏳ — (#43) 潜在集成点：事件可作为伏笔的落点/回收锚点（伏笔挂事件），
                            F13 实施时确认（本 spec 不预设）
  F14 (统一提取)        ⏳ — (#44) 事件 AI 提取（章节文本 → 事件，含自然语言时间数值化）归 F14；
                            复用本模块实体/字段约定（time_value/time_display/timeline_flag/extra）
  F15 (审计)            ⏳ — (Issue 待创建) 事件变更与一致性检查结果作为审计数据源
  F16 (风格/一致性)      ⏳ — (Phase 2) 双时间线一致性检查作为跨模块一致性审计的输入之一
  F20 (MCP)             ⏳ — (Phase 3) manage_timeline 工具基于本模块 API
  ADR-013 (RAG)         ⏳ — (Phase 2) timeline_event 作为向量索引实体类型（写作涉及时间跳跃时检索），
                            索引内容来自本模块事件档案
```

> 与 F9/F10/F11 的依赖面差异：F11 依赖 F1+F5（生成需要 LLM）；F12 **仅依赖 F1**——是创作工具链中依赖面最小的模块。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| 单实体建模 | TimelineEvent（项目级）+ 双时间线视图/报告模型；**无第二张实体表** | PRD P1-04「事件/叙事双时间线」是**同一批事件的两种投影**而非两类实体——双表会造成双份真相同步问题；单表双字段（time_value + narrative_position）即可表达双线（备选「事件表 + 叙事位置表」被否决） |
| 世界内时间表示 | `time_value`（float 数值键）+ `time_unit`（单位标签）+ `time_display`（原始表达）三字段 | 一致性检查必须以「可比较的数值」为前提（纯文本时间无法排序/比较，否决）；小说世界时间非公历（datetime 是错误抽象，否决）；数值键 + 自由文本展示兼顾机器可算与作者可读（v1.3 #1353：纪元轴改由 `extra` 承载、正式列归 0.17.0）——详见 §2.2 论证表 / §2.8 |
| time_value 可空 | None = 世界内时间未知：事件时间线排末尾、检查计入 skipped | 「先记事件、后补时间」是真实创作流（时间未定事件仍属叙事时间线）；强制必填会阻塞事件建档（备选「必填」被否决）；未知时间不参与比较，不会误报冲突 |
| 叙事位置表示 | 单一整数序号 `narrative_position` | 不绑定 F2 章节（F11 边界声明先例）；线性全序、排序/比较简单；章节级位置（卷→章→段）归 Phase 2+（备选「章节序+段序」需 F2 跨模块硬依赖，被否决）——详见 §2.2 论证表 |
| 无唯一约束 | title/narrative_position/time_value 均允许重复 | 事件是**实例**而非**档案**：「同名 = 同一事件」的合并锚点语义（F9/F10）在此不成立；同刻/同题事件合法；无自然业务唯一键（同 F11 PlotPoint 处理） |
| 一致性检查算法 | **相邻对扫描**（O(n log n) 排序 + O(n) 扫描） | 完备性有数学保证（序列单调非降 ⟺ 无相邻逆序对），报告按叙事顺序逐条可执行；备选 LIS 最小修正集算法（O(n log n)）报告难理解、实现复杂，MVP 收益不成比例（P5 YAGNI，备选归 Phase 2+，见 §10/Q3） |
| 倒叙/插叙合法性 | **显式声明制**：逆序对 + next 标记 `flashback`（或 prev 标记 `flashforward`）= 合法；未声明 = order_conflict | 备选「所有逆序都报冲突」会误报合法倒叙（小说倒叙/插叙是常用手法）；备选「所有逆序都不报」使检查失去意义；声明制两者兼得——作者不声明就是硬伤，声明了就是手法（§5.4） |
| 检查实现 | **纯确定性内存计算，无 LLM** | 本模块核心价值是「可验证的一致性」：LLM 判断非确定性、不可测试、有成本（备选被否决）；确定性算法可快照断言、CI 可回归 |
| 检查端点 | `GET /api/v1/projects/{project_id}/timeline/check`（幂等只读计算） | F9/F10/F11 的动作型端点（extract/generate）均有落库副作用故用 POST；check **无副作用**，GET 语义正确且可缓存（备选 POST 被否决） |
| 双线总览端点 | `GET /api/v1/projects/{project_id}/timeline`（一次性返回两条视图） | 「双线管理」验收标准的直接表达；两条线是同一批事件的投影，拆两个端点徒增往返（备选拆分被否决）；全量返回（事件数 ≤ 数百，无分页，YAGNI） |
| 端点布局 | 创建/列表/视图/检查嵌套项目路径，详情/更新/删除扁平（同 F2/F9/F10/F11） | 与既有端点风格一致，OpenAPI 分组清晰；`/timeline`、`/timeline/events`、`/timeline/check` 全静态段无路径歧义 |
| 删除语义 | 单实体真删（v1.1 / #211），无级联 | 单实体模块无级联语义（无子实体）；真删后事件物理不存在，不进入视图与检查 |
| CLI 布局 | `inkflow timeline` 顶级组 8 个扁平命令（无子组） | 单实体模块（同 F10 world 组布局）；避免顶级命令膨胀；`check`/`view` 为只读命令，人类可读摘要 + `--json` 完整报告 |
| 更新清除语义 | `time_value`/`timeline_flag` 用 `""` 清除（None = 不修改） | 与 F10 category、F11 arc_id 的既有约定同构；None 与 "" 双语义解决「可空字段无法表达清除」的 Pydantic 更新难题 |
| **time_value 语义 = 单位化累计时基**（#1409） | `time_value` × `time_unit` = 相对项目时基的累计时长；比较/排序**一律归一到「日」**（§2.7 S1-S5） | 原「time_unit 仅语义、不参与排序」使「多单位共用一个数值键」无人负责 → 真数据实测 7 条审计假阳性（3 条纯跨单位误判）。**备选：让 `time_value` 自带单位（如字符串「3月」）** → 破坏可排序数值键、需全链路类型改造（否决）；**备选：强制写入侧单一时基（拒绝非「日」单位）** → 破坏既有手工数据与 #1353 多纪元方向（否决）。选「归一到日 + 归一表」，代价是 365/30 取近似值（历法引擎 #1410 修正） |
| **判定层归一 vs 数据层重锚分离**（#1409） | 比较/排序用**只读归一投影**；数据修复用**显式 `timeline normalize`**（dry-run 默认） | 归一修不了「同单位跨段重置」（无基准信息）；而自动重锚是**单调投影**（按构造消除全部逆序）→ 静默执行会把审计永久刷绿、吸收真实错误（违反「degraded ≠ 通过」）。故分层：判定层只做无副作用投影；数据层必须**用户显式裁决** |
| **重锚用「回落=新段 + 段内续接」而非「抬平到前一条」**（#1409） | 段起点接上一段末尾，段内保留相对天数 | 抬平（`g = prev`）会把整卷压成平线、级联抹平相对信息（#1409 实测：两者都能到 0 冲突，但抬平的信息损失不可接受）；回落分段与「段内计数器」的真实成因一致（LLM 逐章提取，段落边界即计数器重置点） |
| **多纪元 = `extra` 承载 + 轴选择器**（v1.3 #1353） | 0.16.0：`extra.era` / `extra.era_value`（零 DDL）+ 前端轴族/轴选择器（GUI 层投影） | 需求真问题是「多轴共存 + 可选择性显示」，不是「纪年内换算」；`extra` 是 v1.0 起既有扩展列 → 零迁移、可逆、既有数据零改动（R6-4）。**备选：0.16.0 就加正式列** → 需 `ensure_*` 三件套 + 旧库升级面，且流速比未定时列语义也定不下来（否决，归 #1410）；**备选：维持否决多纪元** → 需求已验真（#1323 P2 / #1353），且原否决只反对「复合键 + 双排序字段」，不反对「轴标签」 |
| **多纪元 = 正式列 `era` / `era_value` / `era_scale`**（v1.4 #1410 / ADR-065） | 正式列取代 `extra` 承载；`time_value` 仍是**跨轴全局标量**；迁移幂等（ADD COLUMN + 一次性回填，`extra` 旧键留作快照）；`era_scale` 落列但读写面/换算归 T2 | 0.16.0 的 `extra` 承载是**弱约束**（JSON 无类型/长度/索引），且 T2 换算无 `era_scale` 落点 → 正式化必要（推迟不消除）。**备选：维持 `extra`** → 无法写 schema 级漂移门禁、T2 无落点（否决）；**备选：`era`+`era_value` 复合业务键** → 全局排序仍靠 `time_value`，多一套键且约束了本该可重复的「同刻多事件」（否决，原否决理由仍成立）；**备选：独立 `timeline_eras` 轴表** → 轴本期只是事件属性标签，无独立生命周期（过度设计，否决并记入 T2） |
| **跨纪元换算 + 按轴分桶比较**（v1.5 #1411 / ADR-065 §2.1） | 新建 `domain/services/era_conversion.py::to_global`（`era_value / era_scale`，**唯一实现点**）；检查先按 `era` **分桶**——默认轴沿用归一日尺度、纪元轴用换算后全局标量，跨桶按全局标量比较 | ADR-065 定死「跨纪元比较**必须经换算**」；T1 的边界③「不跨纪元比较」是**里程碑作用域**，T2（#1411）起由换算后比较取代（**R6-5 裁定 = 不降级**）。**备选：降级为「跨纪元不比较」** → 会少报跨纪元冲突（假阴性），而需求侧要的是「分轴后仍能判自洽」（否决）；**备选：写入路径回写 `time_value`** → 静默改写作者数值、与本节「判定层归一 vs 数据层重锚分离」冲突（否决——换算只在**判定层只读投影**） |
| **归一/重锚不做自动启动迁移**（#1409） | 不随 `create_all` / lifespan 自动执行（对比 #1323 叙事序回填） | #1323 是**位置语义**修正（不改业务数值）；本项是**数值**改写（实测改动 85% 带值事件）且会消除冲突信号 → 必须显式触发（§5.7）。**备选：扩展 `core/migrations_*` 自动回填** → 静默改写用户数据 + 审计失真（否决） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 领域模型 + DTO 验证（双时间维度字段 + 清除语义 + 检查报告模型） | `pytest backend/tests/unit/domain/models/test_timeline_models.py -v` 全绿 |
| M2 | 仓储层全部方法（单实体 CRUD + 双索引 + next_position + 真删） | `pytest backend/tests/unit/infrastructure/database/test_timeline_repo.py -v` 全绿 |
| M3 | 服务层 CRUD + 业务校验（next_position 编排/更新清除编排/404 全路径） | `pytest backend/tests/unit/domain/services/test_timeline_service.py -v` 全绿 |
| M4 | 一致性检查算法（相邻对扫描/倒叙声明/未知时间/同刻/快照断言） | `pytest backend/tests/unit/domain/services/test_timeline_check.py -v` 全绿 |
| M5 | API 端点 + 错误路径全绿 | `pytest backend/tests/unit/api/routers/test_timeline_api.py -v` 全绿 |
| M6 | CLI timeline 组（信封/退出码/确认交互/check 摘要） | `pytest tests/test_cli_timeline.py -v` 全绿 |
| M7 | 手工验证：真实项目建事件 → 双线总览 → 检查 → 修正闭环 | 手工验证（`inkflow timeline create` 建 3+ 事件制造逆序 → `inkflow timeline check` 看到冲突 → 加 flashback 标记 → 重查 consistent=true；`inkflow timeline view` 双线正确） |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest -v` 全绿；F12 模块行覆盖 ≥ 80%、全仓 ≥ 60%（0.2.0 DoD）；ruff + mypy 通过（CI 门禁 ADR-017）；domain/ 零框架 import（ADR-002/015） |
| M9 | **（v1.2 #1409）单位归一 + 项目级重锚** | `pytest backend/tests/unit/domain/services/test_timeline_check.py tests/unit/domain/services/test_timeline_timebase.py -v` 全绿；`pytest tests/cli/test_cli_timeline_ops.py -v` 全绿；`inkflow timeline normalize --project-id <真实项目>` dry-run 报告 `conflicts_before → conflicts_after` |
| M10 | **（v1.3 #1353）多纪元最小承载（零 DDL）** | `pytest backend/tests/unit/domain/models/test_timeline_models.py tests/unit/domain/services/test_timeline_era.py -v` 全绿；`pytest tests/cli/test_cli_timeline_ops.py -v` 全绿；**零 DDL**：diff 无新增列 / 无新增 `ensure_*`（`git diff --stat` 仅服务/路由/CLI/前端/文档面）；**反例守护**：未设纪元事件行为与 v1.2 逐字段一致；手工：`inkflow timeline create --era <轴名> --era-value <值> --json` → `extra` 回读一致，`timeline update --era ""` → 两键消失 |
| M11 | **（v1.4 #1410）多纪元正式化（三列 + 幂等迁移 + 回填）** | `pytest backend/tests/unit/core/test_timeline_era_migration_1410.py tests/unit/domain/models/test_timeline_era_1353.py tests/unit/domain/services/test_timeline_era_1353.py -v` 全绿；迁移**三形态**（空表 / 有表缺列 / 有表有列）+ 幂等 + 回填不覆盖已有正式列值；前端 `pnpm vitest run timeline-era-axes TimelineView.era-axes-1353 LibraryCreateDialog.era-1353` 全绿；`ci_cd/openapi_snapshot.json` 与 `openapi.d.ts` 已同步 |
| M12 | **（v1.5 #1411）跨纪元流速换算 + 按轴分桶** | `pytest backend/tests/unit/domain/services/test_era_conversion_1411.py tests/unit/domain/services/test_timeline_check.py tests/unit/domain/services/test_timeline_era_1411.py -v` 全绿；`pytest tests/cli/test_cli_timeline_ops.py tests/unit/api/routers/test_timeline_api.py -v` 全绿（`--era-scale` 透传）；真实项目造跨纪元数据 → `check` **分桶前后冲突数**对比贴 PR body |

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | 世界内时间是否只需要**单点**（time_value 一个数值，本 spec 设计）？是否需要支持**时间区间**（事件起止时间，如「宗门大比持续 3 天」）？若需要，一致性检查需扩展「区间重叠/包含」判定（time_value 单点比较 → start/end 区间比较），数据模型与检查算法都要变 | 影响数据模型字段与一致性检查算法（§2.2/§5） | 建议：MVP 单点时间（区间归 Phase 2+，PRD 未要求）；F14 提取事件时若遇到「持续事件」可先落单点（起始时间）+ extra 备注 |
| Q2 | 事件与角色的关联（参与角色）用 `extra` 预留（本 spec 设计）；是否需要**正式 participant 字段/表**（角色多对多，供 F14 提取直接落库、供 F9 角色档案反查「该角色参与哪些事件」）？ | 影响数据模型与 API（事件字段或关联表 + 反查端点） | 建议：MVP extra 预留；F14 落地时若角色-事件关联成为提取目标再实体化（届时对照 F9 CharacterRelation 模式实现） |
| Q3 | 一致性检查报告粒度：MVP 输出**相邻逆序对 + 双线视图**（本 spec 设计），由作者逐条修正；是否需要**最小修正建议**（LIS 算法给出「最少调整哪几个事件即可恢复一致」）？ | 影响检查算法复杂度与报告模型（§5.3） | 建议：MVP 不做（相邻对报告已完备：修正全部报告项 ⟺ 序列一致，§5.3 论证）；LIS 最小修正集归 Phase 2+，作者可借助双线视图手工判断 |

---

## 14. 动作确认

> 每个端点/命令的完整状态流表（基于 §3 API + §4 CLI + §7 边界事实，不重复）。

### 14.1 端点状态流（8 端点，§3.1）

| 端点 | 前置条件 | 动作/状态转换 | 成功 | 失败 | 边界 |
|------|---------|--------------|------|------|------|
| POST /projects/{project_id}/timeline/events | 项目存在 | 校验（标题/时间/叙事位置）→ 创建（narrative_position 缺省=叙事末尾追加） | 201 + TimelineEvent | 404「项目不存在」；422「事件标题不能为空」/「事件标题不能超过 100 个字符」/「事件描述不能超过 5000 个字符」/「世界内时间必须是有限数值」/「世界内时间超出允许范围（[-10^12, 10^12]）」/「叙事位置不能为负数」 | time_value 缺省=时间未知（None）；time_unit/time_display/timeline_flag 超长 → 422；`era`/`era_value` 成对语义（§2.8 E4：`era=""` 不设纪元；未传 `era` 时 `era_value` 忽略）；`era_scale`（v1.5 #1411）须为正数、缺省 1.0 |
| GET /projects/{project_id}/timeline/events | 项目存在 | 搜索/排序/分页 → 活动事件 | 200 + {items,total,offset,limit} | 404「项目不存在」 | search 空不过滤；分页越界 → 空 items |
| GET /projects/{project_id}/timeline | 项目存在 | 双线投影（活动事件全量，无分页） | 200 + TimelineView（event_timeline + narrative_order） | 404「项目不存在」 | event_timeline 按 (**全局标量** ASC NULLS LAST, narrative_position ASC)（默认轴 = 归一 `time_value`，纪元轴 = `to_global` 换算，§5.2）；narrative_order 按 (narrative_position ASC, created_at ASC)；无活动事件 → total=0 + 空数组 |
| GET /projects/{project_id}/timeline/check | 项目存在 | 相邻对扫描（确定性算法，无 LLM） | 200 + ConsistencyReport（checked/skipped/consistent/conflicts/flashbacks + 双线视图） | 404「项目不存在」 | include_flashbacks 查询参数（默认含）；0/1 事件 → consistent=true；全未知时间 → checked=0 skipped=n；逆序对 next 标记 flashback / prev 标记 flashforward → 不算冲突；未知标记（如 "flshback"）→ order_conflict；同刻事件不冲突 |
| GET /timeline/events/{event_id} | 事件存在 | 查询 | 200 + TimelineEvent | 404「事件不存在」 | 无效 UUID → 404 |
| PATCH /timeline/events/{event_id} | 事件存在 | 部分更新（时间/标记清除语义） | 200 + TimelineEvent | 404「事件不存在」；422（time_value 清除只接受空字符串） | time_value="" → 置 None（时间未知）；timeline_flag="" → 置 ""（正叙）；time_value 传 "abc" → 422；`era=""` → **清空**正式列 `era`/`era_value`（v1.4）；未传 `era` 时 `era_value` 忽略；`era_scale`（v1.5 #1411）须为正数、未传 = 不修改 |
| DELETE /timeline/events/{event_id} | 事件存在 | **真删**（不进入双线视图与一致性检查） | 204 | 404「事件不存在」 | **v1.1**：无软删路径、无 `force` 参数；重复删除 → 404 |
| ~~POST /timeline/events/{event_id}/restore~~ | — | **（v1.1 移除）** 端点已不存在 | — | 请求该路径 → 404 | — |

### 14.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| timeline create | 项目存在 | 创建（--time-value 缺省=未知；--narrative-position 缺省=末尾追加；--era/--era-value/--era-scale 可选） | 「✅ 事件创建成功: [林尘觉醒金手指]（示例历 317 年秋，叙事第 3 位）」/ --json（含正式列 `era`/`era_value`/`era_scale`） | 404 NOT_FOUND；422 VALIDATION_ERROR（`era` 超长 / `era_value` 非有限 / `era_scale` 非正数） | --content-file <path> 从 UTF-8 文件读正文=事件描述（与 --description 互斥 → 退出码 2；文件缺失 → VALIDATION_ERROR 退出码 1） |
| timeline list | 项目存在 | 列表（--sort 5 种） | 列表 / JSON | 404 | — |
| timeline view | 项目存在 | 双线总览 | 「📋 双线总览: 共 5 个事件 — ...」 | 404 | — |
| timeline check | 项目存在 | 一致性检查（--include-flashbacks 默认开） | 「🔍 一致性检查: ✅ 一致（检查 4 个事件，跳过 1 个时间未知）」/「⚠️ 发现 2 个冲突」/「💡 1 个已声明倒叙/插叙」 | 404 | 发现冲突退出码仍 0 |
| timeline get | 事件存在 | 查询 | JSON | 404「事件不存在」 | — |
| timeline update | 事件存在 | 更新（--time-value ""/--timeline-flag "" 清除；--era "" 清除纪元；--era-scale 改流速比） | JSON（含正式列 `era`/`era_value`/`era_scale`） | 404；422 | 未传 --era 时 --era-value 忽略（§2.8 E4）；未传 --era-scale = 不修改；--content-file <path> 从 UTF-8 文件读正文=事件描述（与 --description 互斥 → 退出码 2） |
| timeline delete | 事件存在 | 二次确认（--force 跳过）→ **真删** | 204 | 404；--json 无 --force → VALIDATION_ERROR「删除需 --force 或交互确认」（退出码 1） | **v1.1**：`--permanent` 移除 |
| timeline normalize | 项目存在 | `GET /projects/{id}/timeline` 取全量事件 → 计算归一/重锚计划（dry-run 默认）→ `--apply` 时逐事件 `PATCH /timeline/events/{id}` | 「🧭 时间线归一: 识别 N 个叙事段，将改写 M/K 条事件（冲突 7 → 0）；dry-run 未写入，加 --apply 执行」/ `--json` 完整计划 | 404 NOT_FOUND（项目不存在）；VALIDATION_ERROR（无效 UUID）；DB_ERROR | 无带值事件 → `segments=0, changed=0`；已归一 → `changed=0`（幂等）；已声明倒叙/时间未知不改 |
| ~~timeline restore~~ | — | **（v1.1 移除）** 命令已不存在 | — | 调用 → UsageError | — |

> 错误码：NOT_FOUND / VALIDATION_ERROR / DB_ERROR（**无 LLM_ERROR**——F12 无 LLM）。

### 14.3 验收锚点（写入 §14）

- A1：POST 事件 time_value=NaN/±Inf → 422「世界内时间必须是有限数值」；越界 → 422「世界内时间超出允许范围（[-10^12, 10^12]）」
- A2：PATCH time_value 传 "abc" → 422；传 "" → 200 且 time_value=null（时间未知，一致性检查计入 skipped）
- A3：逆序对未标记 → check 200 的 conflicts 含 order_conflict、consistent=false；给后叙事件加 timeline_flag=flashback 重查 → flashbacks 含该项、consistent=true
- A4：删除事件 → 双线总览与 check 均不含该事件（物理不存在，不可恢复）
- A5：0/1 个活动事件 → 200 consistent=true（checked=0/1）；全部事件时间未知 → checked=0、skipped=n、consistent=true
- A6：include_flashbacks=false → flashbacks 返回空列表；conflicts/consistent 不变
- A7（#1409）：`8 日` → `3 月` 相邻**不报**冲突；`3 月` → `8 日` **报** order_conflict；`时/时辰` 归一到「日锚点 + 时/24」（非 `/24`）；`time_unit` 为空时结论与 v1.1 一致
- A8（#1409）：`timeline normalize` 默认 dry-run **不改库**；`--apply` 后 `audit/check` 的 order_conflict 收敛（真实项目实测 7 → 0）；重复运行 `changed=0`
- A9（#1353，v1.4 升级承载位）：`timeline create --era <轴名> --era-value <值> --json` → 响应**顶层** `era` = <轴名>、`era_value` = <值>、`era_scale` = 1.0；`timeline update --era ""` → `era` = `""`、`era_value` = null（清空）；不带纪元的同一项目 `check` 结论与 v1.2 **逐字段一致**（**默认轴**，v1.5 起仍逐字段不变；**v1.5 变更**：纪元事件**经换算参与**检查，见 A11——A9 的「纪元不进检查」硬验收**作用域收束回 T1**，ADR-065 §2.1）
- A10（#1410）：空库启动 → `PRAGMA table_info(timeline_events)` 含 `era` / `era_value` / `era_scale`；旧库（无列）启动 → `ensure_timeline_era_columns` 补列且**行数零丢失**、`extra.era` / `extra.era_value` 一次性回填进正式列（`era_scale` = 1.0）；连续两次启动**幂等**（不报错、不重复写、不覆盖已有正式列值）
- A11（#1411，v1.5）：`check` 对跨纪元数据**按轴分桶比较**——① 甲纪元 `scale=1`（`era_value=1`）与乙纪元 `scale=2`（`era_value=2`）相邻 → 换算后同为 `1` → **不报**冲突；② `era_scale` 缺省 `1.0` 时等价「直比轴内值」；③ `era_value` 为 None 的纪元事件计入 `skipped`；④ 默认轴（无纪元）项目结论与 v1.4 **逐字段一致**；⑤ `timeline create/update --era-scale <x> --json` → 响应 `era_scale = <x>`

### 14.4 Spec 漂移标注（追加时核对实现 routers/timeline.py）

- **restore 端点（v1.1 已移除，非实现缺口）**：§3.1/§4.1 原声明的 `POST /timeline/events/{event_id}/restore` 与 CLI `timeline restore` 在 routers/timeline.py / services / CLI 中**均不存在**——这是 #211「普通实体软删→真删」的**有意结果**（非未落地）：v1.1 删除即物理删除，无恢复场景。本节曾据实现缺失记为漂移，现更正定性（2026-09-18 文档同步补齐）。
- **实现侧新增端点**：`GET /timeline/events/{event_id}/check`（单事件一致性检查）为 spec §3.1 未声明端点——实现路由 8 条 vs spec 枚举 8 端点，构成不同（缺 restore、多单事件 check）。
