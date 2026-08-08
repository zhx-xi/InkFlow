# F32: 设置持久化（settings_persistence）— 功能规格

> **Spec 版本**: 1.1 | **日期**: 2026-08-08 | **依据**: Issue #152（2026-08-07 用户拍板范围 ①②③）+ #167 归口（2026-08-07 评论区：关闭行为设置持久化归口 + 首次托盘提示开关登记 #167 Q3=A）、ADR-030 ④、Constitution P1-P6（P2 解耦 / P5 YAGNI）
>
> **Spec 变更（v1.0 → v1.1）**: 评审有条件通过（2 🔴 + 4 🟡 已修订：theme 覆盖规则保留本地值 / flush 同步 project store / 测试文件 MODIFY 与路径修正 / F31 tray-hint 无消费端表述 / E2E 隔离 / ref 镜像）+ **用户拍板 Q1=A（theme 全局粒度）/ Q2=A（key-value app_settings 表）/ Q3=C（综合守卫：default_words 卸载 flush + 对话框显式语义）**（2026-08-08）；**实现偏差回写（GREEN 2026-08-08）**：SettingsKey 改 StrEnum（仓库惯例 RUFF UP042）、_merge 单字段校验改 strict=True（Pydantic lax bool 强转防御）——见 §2.2/§2.5 代码块留痕
>
> **所属阶段**: 0.5.0（#152 设置持久化，路线图估算 3.5-5 人天；theme 后端化 +2 人天已含）
>
> **关联 Issues**: #152（本模块）；#167 ✅（F31 托盘常驻，PR #172 squash 7bdf5d1——关闭行为设置内存态，**归口本模块切换持久化**）；#166 ✅（F30 内核冷启动，PR #171）
>
> **依赖**: ✅ F31 #167（settings:* IPC 三通道 + 托盘 + 关闭拦截状态机，PR #172）· ✅ F19 #105（设置页框架 + Agent 即改即存 + PATCH 直连模式）· ✅ F19 #106（ProviderConfig 注册表：设置类实体先例）· ✅ F19 #107（模板对话框显式保存语义）· ✅ F19 #78/#79（token 中间件 + 渲染层 + ensureApiReady）· ✅ F9（character_errors 通用错误类复用惯例）· ⏳ 无
>
> **参考 ADR**: [ADR-021](../../adr/ADR-021.md)（内核进程化：token 中间件 + 401 契约）· [ADR-027](../../adr/ADR-027.md)（覆盖率门禁：后端 98.5/95.0 + 前端 thresholds）· [ADR-030](../../adr/ADR-030.md)（④ 关闭行为持久化归口 #152）· [ADR-019](../../adr/ADR-019.md)（版本里程碑 + 模块编号口径）
>
> **状态**: ✅ 已实现（PR #176 + #197，#152 2026-08-08）

>
> **快速导航**（2026-08-08 #201）：
> [1. 概述](L19) · [2. 数据模型](L73) · [3. API 契约](L344) · [4. CLI 命令签名](L490)
> [5. 设置库 + 双轨加载 + 主进程桥接 + 表单守卫（关键差异节）](L503) · [6. 组织规则](L775) · [7. 边界情况与错误处理](L828) · [8. 文件结构](L851)
> [9. 测试策略](L917) · [10. 不在范围内](L988) · [11. 依赖关系](L1006) · [12. 关键架构决策记录](L1023)
> [13. 验收标准](L1039) · [14. 待澄清问题（≤3，评审时确认）](L1085)
---

## 1. 概述

F32 为 InkFlow 建立**统一的应用级设置库**：将散落在三处的设置持久化收敛为「后端 SQLite 单一权威」——

1. **前端视觉设置**（theme/bg/lang）现仅存 localStorage（`inkflow.ui`），跨设备/重装丢失；字体设置（font）连 localStorage 都没有，纯组件本地 state；
2. **关闭行为设置**（close_behavior）现为主进程会话级内存态（F31 #167 交付），重启回默认；
3. **首次托盘提示「不再提示」**（tray_hint_dismissed）同为 F31 内存态，且按 #167 Q3=A 登记，本 issue 落地后在设置页 GeneralPanel 提供显式开关（持久化语义成立后才值得做开关）。

同时修复 Issue #152 的触发项缺陷：**default_words 跳页丢失**（onBlur 隐式保存 + 无守卫），并统一评估「表单草稿守卫」的合理形态（Q3）。

### 1.1 需求追溯：用户说的 vs 根源问题

> requirements-analyst 工作法：先追问「为什么」，区分「需求表述」与「根源问题」，再评估投入产出比。

| # | 需求表述（Issue #152 body） | 根源问题 | 本模块处置 |
|---|------------------------------|----------|------------|
| R1 | 「修改 default_words 后直接跳转其他页面，返回发现修改丢失」 | 保存时机 = 组件卸载不可靠的 onBlur；**没有「保存成功」的确定性语义**（值先入本地 state，PATCH 是尽力而为） | 修复保存时机（卸载前 flush）+ dirty 跟踪 + 失败可见（§5.4）；**default_words 保持项目级 ProjectConfig 字段，不进全局设置库**（语义核实：它是「每项目新章节默认字数」，跟随项目 config，F1 契约；拍板范围③的「字体」才是全局设置） |
| R2 | 「主题/语言/字体纳入后端持久化（跨设备保留）」 | 视觉设置持久化在浏览器 localStorage，跨设备/重装即失；且**无后端权威**（未来云端/多客户端无共同真相源） | 新建 app_settings 设置库 + GET/PATCH /api/v1/settings（§2/§3）；前端改「localStorage 快照 + 后端覆盖」双轨（§5.2） |
| R3 | 「未保存草稿跳页有提示或自动保存」（agent/models/templates） | 表述泛化为「所有表单」；**逐个核实后真实存在草稿丢失风险的只有 default_words（无显式保存动作的隐式保存）**——Agent 面板已即改即存（#105 修复，无草稿可丢）；模板/模型对话框 = 显式保存/取消（关闭即取消是行业标准 UX）；AgentLlmCard 为未接线死代码（仅测试引用） | 守卫形态 = default_words 自动 flush + 保存失败可见；对话框保持显式语义（Q3 建议 C，§5.4） |
| R4 | 「关闭行为设置持久化」（#167 归口拍板） | 主进程内存态重启回默认「最小化到托盘」——用户选了「直接退出」重启后失效 | close_behavior 入设置库；renderer 启动时拉取并初始化主进程（§5.3） |
| R5 | 「首次托盘提示开关」（#167 Q3=A 登记增强项） | F31 中 tray_hint_dismissed 为内存态，**开关无持久语义则不可展示**（F31 拍板原文） | tray_hint_dismissed 入设置库 + GeneralPanel 开关（§6.2） |

**伪需求三问自检**（谁用/何时用/为何用）：设置持久化的消费方 = GUI 用户（设置页 + 顶栏）+ Electron 主进程（关闭拦截）；场景 = 重启应用、跨设备（本机数据目录迁移/多机拷贝）；为何 = 「我选的东西应该记住」。无无人值守/定时类伪需求成分。✅ 通过。

### 1.2 模块类型定位（第 14 变体：设置域横切型）

按 AGENTS.md 模块类型谱系计数（f15=6 / f16=7 / f23=8 / f19=9 / f26=10 / f24=11 / f25=12（已移除）/ f30=13），本模块为 **第 14 变体「设置域横切型」**：不新增业务算法、不新增业务实体（app_settings 为基础设施承载表），为**多消费方（renderer 设置页/顶栏 + Electron 主进程）提供统一的设置读写契约**，并横切改造前端加载时序与主进程桥接。

```
F31 主进程内存态（settings:* IPC） ×  theme store localStorage ×  default_words onBlur PATCH
        └──────────────────▶ app_settings 表 + GET/PATCH /api/v1/settings（单一权威）
                                └──▶ renderer 统一设置 store（快照 + 后端覆盖 + 缓存回写）
                                └──▶ 主进程运行时态（renderer 拉取后初始化，复用既有 IPC）
```

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ✅ **app_settings**（key-value 承载表，非业务实体；create_all 自动建，零迁移） |
| 新 API 端点 | ✅ 2 个：GET /api/v1/settings + PATCH /api/v1/settings（挂既有 settings router） |
| 新 CLI 命令 | ❌ 无（消费方 = GUI + 主进程，YAGNI 论证见 §4） |
| 核心机制 | 设置库（默认值补齐不落库）+ 前端双轨加载时序 + 主进程桥接（复用既有 IPC 通道）+ default_words 卸载 flush 守卫 |
| 跨模块 MODIFY | ✅ 前端 theme store 扩展（统一设置 store）+ settings.tsx + App.tsx + client.ts + i18n；后端 deps.py + settings router 扩展 + models/__init__ 注册；**Electron 主进程零改动**（复用 settings:* 三通道） |

### 1.3 边界声明

- **不做**云端同步（2.0.0，ADR-024：云存档/异地写作）——本模块只保证「同一数据目录内重启保留 + 数据目录迁移随身走」
- **不做**设置项 UI 迁移向导——旧 localStorage 值自动接管（§5.2 双轨加载），无迁移提示
- **不做** default_words 全局化——它语义上是项目级字段（ProjectConfig），保持 F1 契约不动
- **不做** 模板/模型对话框加保存确认——显式保存/取消是标准对话框 UX（Q3 建议 C）
- **不做** 主进程直连后端读设置——主进程保持无 HTTP 依赖（§5.3 职责分离）
- **不做** 设置加密——本库无敏感字段（API key 走既有 APIKeyManager 加密存储，不进本库）

---

## 2. 数据模型

**一个领域模型（AppSettings）+ 一个承载表（app_settings）**。AppSettings 是「全量设置」的不可变视图（Pydantic 领域模型，`from_attributes` 惯例）；app_settings 是 key-value 持久化表（JSON 编码 value）。设置项集合固定为 6 个（§2.1 表），**无自由扩展键**（新设置项 = 代码级枚举扩展，YAGNI 不建动态键机制）。

### 2.1 设置项全集（字段 → 默认值 → 现状对照）

| 设置项 | 类型 | 后端默认 | 前端现状默认（来源） | 消费方 | 说明 |
|--------|------|----------|----------------------|--------|------|
| `theme` | `'paper' \| 'night' \| 'ink'` | `'paper'` | paper / night（未手动选择且系统深色 → night，theme.ts `initialTheme()`） | 全局 UI（Q1=A 拍板：全局用户偏好） | **默认语义差异声明**：后端默认 `'paper'` = 「无显式选择」；系统深色跟随是**前端首帧策略**，见 §5.2 覆盖规则 |
| `bg` | `'default' \| 'parchment' \| 'navy' \| 'ochre'` | `'default'` | 'default'（theme.ts `readSaved()`） | 全局 UI | 合法性随 theme 过滤（BG_BY_THEME，theme/index.ts） |
| `lang` | `'zh' \| 'en'` | `'zh'` | 'zh'（theme.ts） | 全局 UI | |
| `font` | `'serif' \| 'sans' \| 'mono'` | `'sans'` | 'sans'（settings.tsx L69 组件本地 state 写死，**未持久化**） | 编辑器字体 | 本模块首次纳入持久化 |
| `close_behavior` | `'tray' \| 'quit'` | `'tray'` | 'tray'（Electron main.ts L83 内存态） | 主进程关闭拦截 | 与 F31 默认一致；F31 注释「#152 合入后切换持久化」 |
| `tray_hint_dismissed` | `bool` | `false` | false（main.ts L85 内存态） | 主进程首次托盘提示 | #167 Q3=A 登记：本模块落地后设置页提供开关（§6.2） |

### 2.2 领域模型（domain/models/settings.py）

```python
"""AppSettings 领域模型 — 应用级设置（全局用户偏好，settings 表承载）。

依据: specs/f32-settings-persistence/spec.md §2。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel

ThemeName = Literal["paper", "night", "ink"]
ThemeBg = Literal["default", "parchment", "navy", "ochre"]
Lang = Literal["zh", "en"]
FontKey = Literal["serif", "sans", "mono"]
CloseBehavior = Literal["tray", "quit"]


class SettingsKey(str, Enum):
    """设置键枚举 — app_settings 表 key 列的稳定标识（新增设置项在此扩展）。

    ⚠️ 实现偏差（Codex B1a 2026-08-08，父侧裁定）：GREEN 实现改为
    `enum.StrEnum`（仓库惯例：AGENTS.md §6.1 + Ruff UP042 启用规则，
    domain 层全部枚举均 StrEnum）——Python 3.11+ 下与 str, Enum 语义
    完全等价，测试契约不依赖继承形态。spec 保留原样留痕。
    """

    THEME = "theme"
    BG = "bg"
    LANG = "lang"
    FONT = "font"
    CLOSE_BEHAVIOR = "close_behavior"
    TRAY_HINT_DISMISSED = "tray_hint_dismissed"


class AppSettings(BaseModel):
    """全量设置对象（GET / PATCH 响应统一形态；字段缺省 = 默认值语义）。

    默认值与前端现状对齐（§2.1 表）：theme='paper' 是「无显式选择」的
    后端表示，系统深色跟随策略由前端首帧处理（§5.2），后端不感知。
    """

    model_config = {"from_attributes": True}

    theme: ThemeName = "paper"
    bg: ThemeBg = "default"
    lang: Lang = "zh"
    font: FontKey = "sans"
    close_behavior: CloseBehavior = "tray"
    tray_hint_dismissed: bool = False


class AppSettingsUpdate(BaseModel):
    """PATCH /settings 请求 DTO — 全字段可选（部分更新语义）。

    extra='forbid'：未知字段直接 422（#105 教训：extra='ignore' 静默吞掉
    前端拼写错误，接口无感知——设置接口是高频手写路径，必须显式报错）。
    空 body（无任何字段）→ 路由层 422「至少提供一个设置字段」。
    """

    model_config = {"extra": "forbid"}

    theme: ThemeName | None = None
    bg: ThemeBg | None = None
    lang: Lang | None = None
    font: FontKey | None = None
    close_behavior: CloseBehavior | None = None
    tray_hint_dismissed: bool | None = None
```

> **值域校验落点**：Pydantic Literal 类型本身完成枚举校验（非法值 → 422，detail 含字段名与允许值，FastAPI 默认 422 形态）。因此 **service 层无业务校验错误面，不新建 errors 文件**（对照 F9/F15 惯例：需要自定义错误类的场景才建；本模块校验全部收敛在 DTO 层，service 只做白名单过滤 + 默认补齐——YAGNI）。

### 2.3 持久化承载表（app_settings）

```python
"""SettingsORM — 应用级设置 key-value 承载表（infrastructure/database/models/settings.py）。"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


class SettingsORM(Base):
    """应用级设置表 — key 主键 + JSON 编码 value。

    设计：key-value 行承载（对照 provider_configs 列式表）——设置项集合小且
    演进频繁（0.5.0 起 6 项，后续按需加键），行式免 ALTER；value 统一 JSON
    编码（'\"night\"' / 'true' / '800000'），解析收敛在 repo 层。
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    """设置键（SettingsKey 枚举值，代码级白名单校验）。"""

    value: Mapped[str] = mapped_column(Text, nullable=False)
    """JSON 编码的值（json.dumps 写入 / json.loads 读取）。"""
```

**建表与迁移**：`app_settings` 为**全新表**，由 `create_tables()`（core/database.py L61-64，`Base.metadata.create_all`）在 lifespan 自动创建——**旧库升级时 create_all 只建缺失表，零迁移成本，不需要 PRAGMA+ALTER 迁移**（`ensure_provider_builtin_key_column` 先例仅适用于「既有表加列」场景，本模块不适用，决策见 §12 D8）。

**无 seed**：设置表不做启动 seed（对照 provider_configs 的 seed_builtin_providers 先例）——缺失 key 由 service 层默认值补齐（§2.4），**补齐不落库**（用户从未改过的设置不产生脏行；表保持「只含用户显式设置过的键」，行数 = 实际修改过的设置项数）。

### 2.4 仓储端口（domain/ports/settings_repository.py）

```python
"""Settings 仓储端口 — app_settings 表持久化契约。

只暴露「全量读 + 批量写」两个操作：设置域没有按单键查询/删除的需求
（消费方永远读全量、写部分），YAGNI 不建 get(key)/delete(key)。
"""

from __future__ import annotations

from typing import Protocol


class SettingsRepositoryProtocol(Protocol):
    async def get_all(self) -> dict[str, str]:
        """返回全部已持久化键值对 {key: JSON 编码 value}；空表返回 {}。"""
        ...

    async def set_many(self, values: dict[str, str]) -> None:
        """批量 upsert（INSERT OR REPLACE）；values 为 {key: JSON 编码 value}。"""
        ...
```

**仓储实现骨架**（infrastructure/database/repositories/settings_repo.py，镜像 provider_config_repo 模式）：

```python
"""SQLite 设置仓储 — app_settings 表实现。"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.ports.settings_repository import SettingsRepositoryProtocol


class SQLiteSettingsRepository(SettingsRepositoryProtocol):
    """app_settings 表读写（INSERT OR REPLACE 幂等 upsert）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> dict[str, str]:
        rows = await self._session.execute(text("SELECT key, value FROM app_settings"))
        return {key: value for key, value in rows.all()}

    async def set_many(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            await self._session.execute(
                text(
                    "INSERT INTO app_settings (key, value) VALUES (:key, :value) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                ),
                {"key": key, "value": value},
            )
        await self._session.commit()

    # 注（评审 🟢 修订）：provider_config_repo 实际为 ORM select + 转换函数形态，
    # 非 text SQL——ORM 映射或 text SQL 皆可实现本契约（语义等价），
    # 具体形态以 TDD 契约为准，spec 不锁定。
```

### 2.5 服务层（domain/services/settings_service.py）

```python
"""SettingsService — 设置读写服务（默认值补齐 + 白名单过滤）。

职责边界：
- get_settings(): 读全量已持久化键 → 与 AppSettings 默认值合并 → 返回全量对象
  （缺失键用默认值，不落库）
- update_settings(): 接收已通过 DTO 校验的部分更新 → 过滤出非 None 字段 →
  白名单（SettingsKey 枚举）→ JSON 编码批量落库 → 返回合并后的全量对象
"""

from __future__ import annotations

import json

from inkflow.domain.models.settings import (
    AppSettings,
    AppSettingsUpdate,
    SettingsKey,
)
from inkflow.domain.ports.settings_repository import SettingsRepositoryProtocol


class SettingsService:
    def __init__(self, repository: SettingsRepositoryProtocol) -> None:
        self._repository = repository

    async def get_settings(self) -> AppSettings:
        """全量设置（缺失键默认值补齐，不落库）。"""
        stored = await self._repository.get_all()
        return self._merge(stored)

    async def update_settings(self, updates: AppSettingsUpdate) -> AppSettings:
        """部分更新（白名单 + JSON 编码落库）→ 返回全量设置。

        注意：updates 已由 DTO（extra='forbid' + Literal 枚举）完成值域校验，
        本方法只负责「非 None 字段」筛选与编码，不重复校验。
        """
        payload: dict[str, str] = {}
        for field, value in updates.model_dump(exclude_none=True).items():
            key = SettingsKey(field)          # 白名单：字段名 = SettingsKey 值
            payload[key.value] = json.dumps(value)
        if payload:
            await self._repository.set_many(payload)
        return await self.get_settings()

    @staticmethod
    def _merge(stored: dict[str, str]) -> AppSettings:
        """已持久化键值 + 默认值合并（非法 JSON/未知键防御性忽略，仅记录）。"""
        merged: dict[str, object] = {}
        for key, raw in stored.items():
            try:
                parsed = json.loads(raw)
                # 评审 🟢 修订：合法 JSON 但类型不匹配（手改库 theme:'true'）也会使
                # 最终 AppSettings 构造失败 → 单字段校验防御（与脏 JSON 同级忽略）
                # ⚠️ 实现偏差（Codex B1a 2026-08-08，父侧裁定）：Pydantic v2 lax 模式
                # 会把字符串 'yes' 强转 True（bool 宽松强制）→ 单字段校验改为
                # `AppSettings.model_validate({key: parsed}, strict=True)`——strict 模式
                # 禁止宽松转换，类型不匹配即忽略（测试契约 test_valid_json_wrong_type_ignored
                # 强制此语义；spec 保留原样留痕）
                AppSettings(**{key: parsed})
                merged[key] = parsed
            except Exception:
                continue                     # 防御：脏数据不阻塞读（§7 边界 #6）
        current = AppSettings().model_dump()
        current.update({k: v for k, v in merged.items() if k in current})
        return AppSettings(**current)
```

### 2.6 决策论证表

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **key-value 行表 app_settings（选定）** | 设置项演进免 ALTER（加行不加列）；create_all 零迁移；JSON 编码通用（str/bool 一视同仁）；与「设置库统一承载」拍板语义一致 | 值无类型约束（依赖 service 层解析）；不适合关系查询（设置域无此需求） | ✅ 选定——设置域典型形态（对比 provider_configs 列式表：那是「注册表实体」需要按 name 查询/唯一约束，设置库是纯键值，行式最简） |
| 单行 JSON 表（一整行存全部设置） | 读一次全拿 | 部分更新 = 整行重写（并发写互相覆盖风险大于行式 upsert）；演进字段 = 解析整行 | ❌ 否决（Q2 选项 B） |
| 复用 project config.extra + 主进程本地文件 | 零新表 | 全局设置混入项目 config（语义错位：theme 不是项目属性）；主进程文件 = 第二套持久化（F31 拍板明确禁止两套设置系统） | ❌ 否决（Q2 选项 C） |
| 列式表（每个设置项一列） | 类型天然约束 | 每加一个设置项 = ALTER TABLE（无 alembic，迁移成本高）；6 列起步的表对 6 行数据的场景是浪费 | ❌ 否决（provider_configs 是实体表先例，不适用纯键值场景） |
| 启动 seed 全部默认键 | 表内容自解释 | 用户没改过的设置也产生行；seed 逻辑 + 幂等判断都是无谓复杂度（get 缺失键补默认已覆盖语义） | ❌ 否决（§2.3 无 seed 决策） |

---

## 3. API 契约

两个新端点挂载到**既有 settings router**（`api/routers/settings.py`，前缀 `/api/v1/settings`，与 llm-keys / llm/test 工具端点同文件——F19 #79 已注册，app.py 零改动）。

### 3.1 端点总览

| 方法 | 路径 | 请求体 | 成功响应 | 归属 |
|------|------|--------|----------|------|
| GET | `/api/v1/settings` | 无 | 200 全量设置对象（缺失键默认值补齐） | 本模块 |
| PATCH | `/api/v1/settings` | AppSettingsUpdate（部分字段） | 200 合并后的全量设置对象 | 本模块 |
| POST | `/api/v1/settings/llm-keys` | provider/api_key | 201 {provider, status} | F19 #79（既有） |
| POST | `/api/v1/settings/llm/test` | provider/model/base_url/api_key | 200 {ok, ...} | F19 #79（既有） |

> 全站契约（F19）：除 /health 外全部经 `TokenAuthMiddleware`——GET/PATCH /settings 同样要求 `X-InkFlow-Token`，缺失/错误 → 401（ADR-021）。

### 3.2 GET /api/v1/settings

首次调用（空表）响应：

```json
{
  "theme": "paper",
  "bg": "default",
  "lang": "zh",
  "font": "sans",
  "close_behavior": "tray",
  "tray_hint_dismissed": false
}
```

已持久化部分键（如用户改过 theme/font）响应：

```json
{
  "theme": "night",
  "bg": "default",
  "lang": "zh",
  "font": "serif",
  "close_behavior": "tray",
  "tray_hint_dismissed": false
}
```

### 3.3 PATCH /api/v1/settings

请求（部分更新，任意字段组合）：

```json
{ "theme": "night", "font": "serif", "close_behavior": "quit" }
```

响应（200，合并后全量）：

```json
{
  "theme": "night",
  "bg": "default",
  "lang": "zh",
  "font": "serif",
  "close_behavior": "quit",
  "tray_hint_dismissed": false
}
```

**幂等性**：PATCH 为幂等 upsert（同 payload 重复提交结果一致）；响应恒为全量对象（客户端无需二次 GET，前端可直接用响应覆盖 store）。

### 3.4 异常映射

| 场景 | 状态码 | 响应 detail（示例） | 触发层 |
|------|--------|---------------------|--------|
| token 缺失/无效 | 401 | `Unauthorized` | TokenAuthMiddleware（F19，全站） |
| 枚举值非法 | 422 | FastAPI 默认校验体（字段 + 允许值；如 `theme: Input should be 'paper', 'night' or 'ink'`） | Pydantic Literal（DTO 层） |
| 未知字段 | 422 | `Extra inputs are not permitted`（字段名在 body 中回显） | `extra='forbid'`（DTO 层） |
| 空 body `{}` | 422 | `至少提供一个设置字段` | 路由层显式校验 |
| 设置表脏数据（非法 JSON） | 200 | 忽略脏键，返回其余默认补齐（防御，§7 边界 #6） | service `_merge` |
| DB 异常（磁盘/锁） | 500 | 通用文案（ADR-012 风格，不泄漏内部细节） | 路由层 except → HTTPException |

> **422 契约要点**：本接口的 422 是「前端拼写/值域错误的显式信号」（#105 教训：`extra='ignore'` 静默吞字段导致前端 bug 无感知）。前端 apiFetch 已统一把 422 detail 映射为 ApiError（client.ts L128-136），设置 store 的失败分支直接 toast。

### 3.5 路由层实现骨架（api/routers/settings.py 追加）

既有文件头（工具端点）+ 追加两段：

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_settings_service
from inkflow.domain.models.settings import AppSettings, AppSettingsUpdate
from inkflow.domain.services.settings_service import SettingsService

router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])   # 既有


@router.get("", response_model=AppSettings)
async def get_settings(
    service: SettingsService = Depends(get_settings_service),
) -> AppSettings:
    """全量设置（缺失键默认值补齐，不落库）。"""
    return await service.get_settings()


@router.patch("", response_model=AppSettings)
async def patch_settings(
    updates: AppSettingsUpdate,
    service: SettingsService = Depends(get_settings_service),
) -> AppSettings:
    """部分更新（白名单 + JSON 编码落库）→ 合并后全量。

    空 body 显式 422：全部字段为 None 的 PATCH 无意义，静默成功会掩盖
    客户端 bug（§3.4 异常映射）。
    """
    if updates.model_dump(exclude_none=True) == {}:
        raise HTTPException(status_code=422, detail="至少提供一个设置字段")
    return await service.update_settings(updates)
```

> 路径形态说明：`@router.get("")`（空路径）——prefix 已含 `/api/v1/settings`，空串路径与既有 `llm-keys` 子路径同 router 无冲突（FastAPI 空串 = 根路径；若实现选用 `"/"` 需注意 redirect_slashes 行为，以 TDD 契约为准）。

### 3.6 完整交互时序（启动 + 修改）

```
启动（renderer）：
  GET /api/v1/settings  ←─ 200 全量（可能全默认）
   → store 覆盖（theme 三分支规则）→ localStorage 回写
   → close_behavior 非 'tray' → IPC settings:set-close-behavior('quit')
   → tray_hint_dismissed=true → IPC settings:dismiss-tray-hint

用户切换主题为 night（顶栏/设置页）：
  store.setTheme('night') → 立即生效 + localStorage 回写
   → PATCH /api/v1/settings {theme:'night'} ←─ 200 全量
   → （视觉设置：成功无动作；失败 err toast，本地保留）

用户切换关闭行为为 quit（设置页）：
  PATCH /api/v1/settings {close_behavior:'quit'} ←─ 200
   → IPC settings:set-close-behavior('quit') → 主进程内存态更新
   → store 更新 + localStorage 回写
  （PATCH 失败 → err toast + Select 回弹，不推送 IPC）

用户勾选首次提示「不再提示」（设置页开关；评审 🟡 修订——F31 的 `inkflow:tray-hint` 提示事件经源码核实**无 renderer 消费端**，toast 未接线，设置页开关 = 本模块交付的唯一入口）：
  PATCH /api/v1/settings {tray_hint_dismissed:true} ←─ 200
   → IPC settings:dismiss-tray-hint → 主进程置位（本次会话不再提示）
```

---

## 4. CLI 命令签名

**无新增 CLI 命令**（YAGNI 论证）：

| 候选 | 否决理由 |
|------|----------|
| `inkflow settings get/set` | 设置库的唯一消费方 = GUI renderer（设置页/顶栏）+ Electron 主进程（经 renderer 桥接）。CLI 消费设置 = 无场景（CLI 无「主题/字体/关闭行为」概念；default_words 属项目 config，已有 `inkflow project` 面）。多一个命令 = 多一份测试/文档维护面，P5 YAGNI |
| `inkflow settings export/import` | 数据目录整体拷贝已覆盖（设置随 inkflow.db 迁移），导出工具属 2.0.0 云同步范畴 |

> 若未来 CLI 需要读设置（如 `inkflow serve` 输出主题色），走 service 层调用即可，无需 CLI 面——本 spec 不预建。

---

## 5. 设置库 + 双轨加载 + 主进程桥接 + 表单守卫（关键差异节）

### 5.1 设置库（key-value + 默认值补齐）

```
消费方（renderer store / 未来其他客户端）
        │  GET /api/v1/settings（全量，默认补齐）
        ▼
┌─────────────────────┐
│ SettingsService     │  白名单：SettingsKey 枚举
│  _merge(默认+持久化) │  缺失键 → 默认值（不落库）
└──────────┬──────────┘
           │  get_all / set_many
┌──────────▼──────────┐
│ app_settings 表      │  key TEXT PK, value TEXT(JSON)
└─────────────────────┘
```

**三条语义规则**：

1. **读恒全量**：GET 返回 6 字段完整对象——客户端不需要知道「哪些键被显式设置过」就能渲染；「显式设置过与否」的信息由 §5.2 前端覆盖规则另行处理（仅 theme 需要）。
2. **写只部分**：PATCH 只接受用户改动的字段；未涉及的字段保持原值（service 合并）。
3. **默认值不落库**：表行数 = 用户显式修改过的设置项数；无 seed、无清理任务（设置项生命周期 = 代码枚举生命周期，删除设置项 = 删除枚举 + 遗留行无害）。

### 5.2 前端加载时序（双轨：localStorage 快照 → 后端覆盖 → 缓存回写）

**目标**：① 首帧零闪烁（同步快照）② 后端为权威（异步覆盖）③ 后端不可达不阻塞（localStorage 兜底）。

```
renderer 启动
  ① store 创建（同步）：localStorage 'inkflow.ui' 快照（theme/bg/lang）+
     font/close_behavior/tray_hint_dismissed 默认值 → 首帧即正确渲染
     （含既有系统深色策略：无快照且系统深色 → night）
  ② AppLayout 挂载 useEffect（异步）：ensureApiReady()（Electron 等 preload 注入，
     15s 兜底）→ GET /api/v1/settings
  ③ 成功 → 覆盖 store（theme 特殊规则见下）→ 回写 localStorage 'inkflow.ui'
     （缓存层：下次启动快照直接可用，免首帧等待）
  ④ 失败（KernelOfflineError / 网络 / 401）→ 保持 ① 的值继续运行，
     console.warn 记录，不弹 toast 不阻塞 UI（§7 边界 #2/#3）
  ⑤ close_behavior / tray_hint_dismissed 桥接主进程（§5.3）
```

**theme 覆盖规则**（后端默认 `'paper'` 与前端系统深色策略的差异收敛）：

| 条件 | 行为 |
|------|------|
| 后端 `theme != 'paper'`（用户显式选过） | 后端值覆盖（跨设备/重启保留） |
| 后端 `theme == 'paper'`（默认，后端无显式选择记录）且 localStorage 有 `inkflow.ui` 记录 | **保留本地记录值**（本地 = 用户最近显式选择；后端 'paper' 只表示「无显式选择记录」，覆盖会静默翻回 paper 丢用户选择） |
| 后端 `theme == 'paper'` 且本地无任何记录（新用户，从未选择） | **不覆盖**，保留 ① 的系统深色策略结果（首次启动跟随系统 = F19 §4.3 既有拍板语义） |

**setter 流程**（setTheme/setBg/setLang/setFont——用户选择后）：

```
用户选择 → store set（立即生效，乐观更新）
        → 回写 localStorage（缓存层）
        → 异步 PATCH /api/v1/settings（fire-and-forget）
        → 成功：无动作（响应全量对象可顺手校验，不强制覆盖本地）
        → 失败：err toast「保存失败」（本地值保留——视觉设置回滚 = 反直觉；
          下次启动以后端为准兜底，§7 边界 #7）
```

> 视觉设置（theme/bg/lang/font）不做「PATCH 成功才生效」——那是行为设置（close_behavior）的语义，见 §5.3。乐观更新 + 失败可见 + 下次启动收敛，是视觉设置的合理一致性模型。

**store 扩展形态**（stores/theme.ts，§12 D4——导出名保持 `useThemeStore`）：

```typescript
// 现状（2026-08-08）：theme/bg/lang + localStorage 'inkflow.ui' + 系统深色策略
// 扩展后新增字段与动作：
interface ThemeState {
  theme: ThemeName;              // 既有
  bg: ThemeBg;                   // 既有
  lang: Lang;                    // 既有
  font: FontKey;                 // 新增：从 localStorage（扩展 inkflow.ui）或后端初始化，默认 'sans'
  closeBehavior: CloseBehavior;  // 新增：默认 'tray'（浏览器 dev 无 IPC 时语义完整）
  trayHintDismissed: boolean;    // 新增：默认 false

  setTheme: (t: ThemeName) => void;   // 既有 setter 扩展：乐观更新 + 回写 + PATCH
  setBg: (b: ThemeBg) => void;        // 同上
  setLang: (l: Lang) => void;         // 同上
  setFont: (f: FontKey) => void;      // 新增：同上（首次持久化）
  setCloseBehavior: (b: CloseBehavior) => Promise<void>;  // 新增：PATCH 成功 → IPC → 更新（§5.3）
  setTrayHintDismissed: (v: boolean) => Promise<void>;    // 新增：同上（IPC dismiss 单向）

  initFromBackend: () => Promise<void>;  // 新增：§5.2 步骤 ②③④⑤（AppLayout 挂载调用一次）
}

// 缓存层：localStorage 'inkflow.ui' 扩展为 {theme, bg, lang, font}；
// closeBehavior / trayHintDismissed 不写 localStorage（无首帧语义，避免陈旧值误导——启动后由后端覆盖）
```

**initFromBackend 流程骨架**：

```typescript
async function initFromBackend(): Promise<void> {
  await ensureApiReady();                       // Electron 等 preload 注入（15s 兜底）；浏览器 dev 立即返回
  try {
    const s = await fetchSettings();            // GET /api/v1/settings（client.ts 新增）
    const saved = readSaved();                  // localStorage 快照（现状 readSaved()）
    const nextTheme = s.theme !== 'paper' ? s.theme : (saved?.theme ?? get().theme);
    set({ theme: nextTheme, bg: s.bg, lang: s.lang, font: s.font,
          closeBehavior: s.close_behavior, trayHintDismissed: s.tray_hint_dismissed });
    writeCache({ theme: nextTheme, bg: s.bg, lang: s.lang, font: s.font });  // 回写缓存层
    // ⑤ 主进程桥接（§5.3）：
    const ipc = window.INKFLOW_API?.settings;
    if (ipc) {
      if (s.close_behavior !== 'tray') void ipc.setCloseBehavior(s.close_behavior);
      if (s.tray_hint_dismissed) void ipc.dismissTrayHint();
    }
  } catch (err) {
    console.warn('[settings] 后端设置加载失败，使用本地缓存:', err);   // 兜底不阻塞（§7 边界 #2）
  }
}
```

> 测试注入点：`fetchSettings` 与 `window.INKFLOW_API.settings` 均可在 vitest 中 mock——theme.test.ts 直接断言三分支覆盖规则与 IPC 推送（§9.1）。

### 5.3 主进程桥接（close_behavior / tray_hint_dismissed）

**双权威职责声明**：

| 权威 | 持有者 | 职责 |
|------|--------|------|
| **持久化权威** | 后端 app_settings 表 | 设置「应该是什么」（重启/跨设备后的真相源） |
| **运行时权威** | Electron 主进程内存态（main.ts L83/L85） | 关闭拦截/托盘提示「此刻按什么行为」（close 事件同步读取，不能跨进程查询） |

**桥接路径（renderer 单向驱动，主进程零新增 IPC 通道）**：

```
启动初始化（⑤ 接 §5.2）：
  GET /settings 返回 close_behavior / tray_hint_dismissed
    → 若与主进程当前内存态不同 → IPC settings:set-close-behavior / settings:dismiss-tray-hint
    → 主进程内存态对齐持久化值（含重启后恢复用户上次选择）

用户修改（设置页 Select / 首次提示开关）：
  PATCH /api/v1/settings（持久化先行）
    → 成功 → IPC 推送主进程（运行时生效）→ store 更新 + localStorage 回写
    → 失败 → err toast + store 保持原值（Select 回弹）——主进程行为不变，
      与「持久化失败」诚实一致（§7 边界 #8）
```

**复用既有通道**（关键决策，§12 D5）：`settings:set-close-behavior`（main.ts L505，含 tray|quit 校验）+ `settings:dismiss-tray-hint`（L512）语义与持久化后的「初始化/更新内存态」完全吻合——主进程 handler 无需任何改动。**dismissTrayHint 场景注意**：用户勾选「不再提示」→ PATCH `tray_hint_dismissed: true` → IPC dismiss → 主进程置位（本次会话不再提示）。**入口说明（评审 🟡 修订）**：F31 现状只发 `inkflow:tray-hint` 事件、renderer 全仓无消费端（2026-08-08 源码核实：无 toast 接线）——本模块交付设置页开关为唯一入口；将来若补 toast 内勾选，走同一 PATCH + IPC 路径即可。

**IPC 通道契约（F31 已交付，本模块消费声明）**：

| 通道 | 方向 | 本模块消费语义 | 调用方（本模块） |
|------|------|----------------|------------------|
| `settings:get-close-behavior` | invoke（renderer→main） | 保留 F31 挂载初值用途（settings.tsx L86 现状可迁移到 store 或保留组件级——**推荐迁移到 store 一次性读取**，与 initFromBackend 对齐；两处并存亦可，幂等） | store 初始化（可选） |
| `settings:set-close-behavior` | invoke | **启动初始化**（GET 值非默认时推送）+ **修改后推送**（PATCH 成功后） | initFromBackend / setCloseBehavior |
| `settings:dismiss-tray-hint` | invoke | **启动初始化**（tray_hint_dismissed=true 时推送）+ **勾选/开关后推送**（PATCH 成功后） | initFromBackend / setTrayHintDismissed |
| `inkflow:tray-hint` | main→renderer（send） | 只读消费（toast 弹提示），无改动 | 既有 toast 逻辑 |

**启动窗口期语义**：renderer 拉取 + IPC 初始化完成前，主进程按默认 'tray' 拦截——窗口期 < 1s（本地 PATCH/GET），用户在此窗口关闭窗口按默认行为（可接受；若用户上次选了 'quit' 且恰在此窗口关闭 → 最小化到托盘而非退出，语义偏差仅此一次且无数据损失）。

**主进程为什么不直连后端**：主进程无 HTTP 客户端依赖（F31 只做 /health 探测）；内核可能晚于窗口创建（spawn 时序），renderer 的 ensureApiReady 天然同步了「内核就绪」；主进程直连 = 重复实现 token/端口管理 = 破坏 ADR-021 消费方分层。

### 5.4 表单草稿守卫（default_words 卸载 flush + dirty 跟踪）

**现状缺陷链**（settings.tsx L63-110，2026-08-08 源码核实）：

| # | 缺陷 | 根因 |
|---|------|------|
| 1 | 跳页丢修改（本 issue 触发项） | 保存 = onBlur；跳页 = 组件卸载，blur 不保证触发 → PATCH 未发 |
| 2 | 切换项目不重读输入框 | `useState` 惰性初始化只跑一次，`currentProjectId` 变化后 state 不刷新（显示旧项目字数） |
| 3 | 非法值（<1000）不保存且值残留 | 校验失败 return，输入框保留非法值，用户无「为什么没保存」的提示（只有 err toast 一闪） |
| 4 | PATCH 失败值残留本地 | `setConfig` 在 PATCH 之前同步执行——失败后 store 与后端不一致，重进设置页显示未保存值 |

**守卫设计（Q3 建议 C：文本输入自动 flush + 对话框保持显式语义）**：

```
default_words 输入流：
  onChange → 本地 state + dirty 标记（dirty = 当前值 != 已保存值）
  onBlur  → flushDefaultWords()（校验 + PATCH）—— 保留现状即时保存语义
  导航离开 / 切分类 / 组件卸载（useEffect cleanup）→ 若 dirty → flushDefaultWords()
  currentProjectId 变化 → 重读项目 config.default_words 初始化 state + 清 dirty

flushDefaultWords() 契约（抽成单一函数，blur/卸载/切项目共用）：
  1. 空值 / 非法数字 → 不 PATCH，dirty 保持（不弹 toast，静默——现状语义）
  2. n < 1000 → 不 PATCH，err toast「保存失败」（与后端 ge=1000 对齐，现状语义）
  3. 合法 → PATCH /api/v1/projects/{id} {config: {..., default_words: n}}
       → 成功：setConfig 同步 + 清 dirty + ok toast
       → 失败：err toast「保存失败」+ dirty 保持 + **不 setConfig**（缺陷 #4 修复：
         值只在输入框本地，不污染 agent store；用户可看到输入框值并重试）
```

**时序细节**：卸载路径的 flush 是 fire-and-forget（cleanup 不能 await）——PATCH 已发出、请求体含完整新值，本地内核 PATCH 通常 <50ms 成功；失败 → 全局 toast store 仍可弹（toast 是全局 store，不随页面卸载）。「跳页 + PATCH 失败」的极端场景 = 输入值随组件卸载丢失 + toast 告知保存失败（可接受的最终兜底，§7 边界 #9）。

**flushDefaultWords 实现骨架**（settings.tsx GeneralPanel，抽成组件内稳定函数）：

```typescript
// ref 镜像形态（评审 🟡-7 修订：dirty 置位 + 最新值捕获——cleanup 闭包若直接引用
// state 会捕获陈旧值；ref 镜像保证卸载 flush 携带最新输入）
const valueRef = useRef<string>(String(project?.config.default_words ?? 800000));
const dirtyRef = useRef(false);
const [defaultWords, setDefaultWords] = useState<string>(valueRef.current);
const [dirty, setDirty] = useState(false);          // 同步镜像 dirtyRef（渲染用）

const markDirty = (v: string) => {
  valueRef.current = v;
  dirtyRef.current = true;
  setDirty(true);
};

// 切项目重读（缺陷 #2 修复）：currentProjectId 变化 → 重新初始化 + 清 dirty
//（dirty 编辑被丢弃是有意行为——项目切换 = 上下文切换，跨项目保留草稿无场景）
useEffect(() => {
  const p = useProjectStore.getState().projects.find(
    (x) => x.id === useProjectStore.getState().currentProjectId,
  );
  const v = String(p?.config.default_words ?? 800000);
  valueRef.current = v;
  dirtyRef.current = false;
  setDefaultWords(v);
  setDirty(false);
}, [currentProjectId]);

// 卸载守卫（缺陷 #1 修复）：跳页/切分类时若 dirty → flush（fire-and-forget）
useEffect(() => () => { if (dirtyRef.current) flushDefaultWords(); }, []);

function flushDefaultWords(): void {
  const n = Number(valueRef.current);
  if (valueRef.current === '' || !Number.isFinite(n)) return;   // 空/非法：静默（现状语义）
  if (n < 1000) { pushToast('err', t('toast.saveFailed')); return; }  // 与后端 ge=1000 对齐
  const project = useProjectStore.getState().projects.find(
    (p) => p.id === useProjectStore.getState().currentProjectId,
  );
  if (!project) return;                                          // 无项目：不保存（评审 🟢 修订）
  const current = useAgentStore.getState().config;               // 合并源 = agent store（#105 🔴-B 教训）
  // 评审 🔴-2 修订：复用 project store updateConfig——单次 PATCH 完整 config
  //（{...current, default_words} 含 agent_* 字段，后端 config 整体替换语义必须发全量）
  // + 本地 config 合并同步 project store（remount 懒初始化重读新值）
  void useProjectStore
    .getState()
    .updateConfig(project.id, { ...current, default_words: n })
    .then(() => {
      useAgentStore.getState().setConfig({ ...current, default_words: n });  // agent store 同步（后续保存的合并源）
      valueRef.current = String(n);
      dirtyRef.current = false;
      setDirty(false);
      pushToast('ok', t('toast.saved'));
    })
    .catch(() => pushToast('err', t('toast.saveFailed')));       // 缺陷 #4 修复：失败不 setConfig、dirty 保持
}
```

> 实现注意：卸载 cleanup 闭包依赖数组为 `[]`（不随 dirty 重注册），内部经 `valueRef`/`dirtyRef` 读最新值——**「卸载 flush 必须携带最新输入值」是 RED 契约断言**（§9.4）。`updateConfig` 为既有 project store 方法（PATCH `{config: patch}` + 本地 config 合并，project.ts L126-132）——flush 不再自写 apiFetch，单请求 + 双 store 同步闭环。

**守卫范围声明（逐表单核实结论）**：

| 表单 | 现状（2026-08-08 源码核实） | 处置 |
|------|----------------------------|------|
| default_words（GeneralPanel） | 本地 state + onBlur PATCH | **本模块守卫落点**（上述设计） |
| Agent 面板（AgentChainCard + 默认模型 Select） | 即改即存 + in-flight 并发守卫（#105 🔴-2 修复） | 无需守卫（无草稿可丢）——issue 横展开 #2「agent 表单草稿」是 #105 合入前的旧表述 |
| AgentLlmCard | 未接线死代码（仅测试文件 import，无页面引用） | 不处理（YAGNI；删除属另案） |
| 模板对话框（TemplateDialog） | 显式保存/取消；关闭即卸载 | 保持显式语义（关闭即取消 = 行业标准对话框 UX；加确认框 = 打扰） |
| 模型对话框（AddModelDialog/ProviderDialog，/models 页） | 显式保存/取消 | 同上，保持 |
| 顶栏主题/语言 Select | 即改即存（#105） | 本模块升级为后端持久化（§5.2 setter） |

> **否决 useBlocker 导航拦截**（react-router v7 `useBlocker`）：① HashRouter 下数据路由 API 可用性存疑（v7 声明式路由的 blocker 支持未在项目内验证，引入即风险）② 对单个数字输入框弹「确认离开」是过度打扰（用户可能只是路过设置页）③ 卸载 flush 已覆盖「丢修改」根源（保存动作与导航解耦）。完整论证见 §12 D7。

### 5.5 与既有模块差异对照表

| 维度 | F31（#167，已合入） | F19 #79/#105（既有） | 本模块（F32） |
|------|---------------------|----------------------|---------------|
| 关闭行为设置 | 主进程内存态，重启回默认 | — | 后端持久化 + renderer 启动初始化主进程（§5.3） |
| theme/bg/lang | — | localStorage 单轨（#79 §4.3）/ 顶栏 Select（#105） | localStorage 快照 + 后端覆盖双轨（§5.2） |
| font | — | 组件本地 state（未持久化） | 入设置库 + theme store（§6.1） |
| 首次托盘提示 | toast 内勾选，内存态（Q3=A 拍板） | — | tray_hint_dismissed 持久化 + GeneralPanel 开关（§6.2） |
| default_words | — | onBlur 隐式 PATCH（缺陷链 §5.4） | 卸载 flush + dirty 跟踪 + 切项目重读 |
| 设置 API | 无（纯 IPC） | llm-keys / llm/test 工具端点（#79） | GET/PATCH /api/v1/settings（§3） |

---

## 6. 组织规则

### 6.1 代码组织

**后端**（镜像 provider_config 先例，#106）：

| 层 | 落点 | 内容 |
|----|------|------|
| domain/models | `settings.py`（CREATE） | AppSettings / AppSettingsUpdate / SettingsKey（§2.2） |
| domain/ports | `settings_repository.py`（CREATE） | SettingsRepositoryProtocol（§2.4）——**无独立 errors 文件**（校验收敛 DTO 层，§2.2 注） |
| domain/services | `settings_service.py`（CREATE） | SettingsService（§2.5） |
| infrastructure/database/models | `settings.py`（CREATE）+ `models/__init__.py`（MODIFY 注册） | SettingsORM（§2.3）——注册即被 create_all 建表 |
| infrastructure/database/repositories | `settings_repo.py`（CREATE） | SQLiteSettingsRepository（get_all / set_many，JSON 编解码收敛于此） |
| api | `routers/settings.py`（MODIFY 加两端点）+ `deps.py`（MODIFY 加 get_settings_service） | §3 契约 |

**前端**（扩展 theme store 为统一设置 store，§12 D4）：

| 层 | 落点 | 内容 |
|----|------|------|
| stores/theme.ts（MODIFY） | 扩展为设置 store | 新增 font / closeBehavior / trayHintDismissed 字段 + `initFromBackend()`（§5.2 加载）+ setter 后端同步（§5.2/§5.3）+ 导出名保持 `useThemeStore`（零破坏既有 import：App.tsx / AppearanceCard / settings.tsx / models 页 / 测试） |
| theme/index.ts（MODIFY） | `FontKey` 类型移入 | 与 ThemeName/ThemeBg/Lang 并列（settings.tsx 本地定义 L25 移出，settings.tsx import） |
| api/client.ts（MODIFY） | fetchSettings / patchSettings + SettingsApi 补 `dismissTrayHint` | SettingsApi interface 现缺 dismissTrayHint（preload 运行时已有，类型补全）；新增 `AppSettings`/`AppSettingsUpdate` 前端类型（字段 snake_case 对齐后端 JSON） |
| pages/settings.tsx（MODIFY） | GeneralPanel | font 从 store 读；closeBehavior 从 store 读 + setter 经 store；新增「首次托盘提示」开关（§6.2）；default_words 守卫（§5.4） |
| App.tsx（MODIFY） | AppLayout 挂载 useEffect | `initFromBackend()` 触发（§5.2 步骤 ②） |
| i18n（MODIFY） | zh.ts / en.ts | `set.trayHint` 开关文案 |

**Electron 主进程与 preload：零改动**（复用 settings:* 三通道，§5.3；实现 PR 需跑既有 main.tray.test.ts / preload.test.ts 验证契约不回归）。

### 6.2 设置页 UI（renderer GeneralPanel）

新增/改造控件：

| 控件 | 位置 | 交互 | i18n 键 |
|------|------|------|---------|
| 编辑器字体 Select | 现状（L118-129） | 值从 store 读（font）；onValueChange → store setter（乐观更新 + PATCH） | `set.font.*`（既有） |
| 关闭窗口时 Select | 现状（L134-152） | 值从 store 读（closeBehavior）；onValueChange → store setter（**PATCH 成功才 IPC + 更新**，失败回弹 + toast） | `set.closeBehavior.*`（既有） |
| 首次托盘提示 Switch | 新增（与关闭行为并列，#167 Q3=A 登记兑现） | 默认开（提示）；关闭 → PATCH `tray_hint_dismissed: true` + IPC dismiss；打开 → PATCH `false`——主进程内存态无需复位（tray_hint_dismissed 只影响「本次会话是否发提示」，保持 true 无害；重启后由 §5.3 启动初始化按后端值对齐） | `set.trayHint`（新增） |

> 入口说明（评审 🟡 修订）：F31 现状 `inkflow:tray-hint` 事件无 renderer 消费端（无 toast 接线，2026-08-08 源码核实）——本模块设置页开关 = 唯一入口；将来若补 toast 内勾选（快捷路径），与开关最终一致（都写 tray_hint_dismissed）。

### 6.3 GeneralPanel 现状 → 改造对照（2026-08-08 源码核实）

| 区块 | 现状 | 改造 |
|------|------|------|
| AppearanceCard（语言/主题/背景） | 经 theme store（localStorage 单轨） | store setter 升级为乐观更新 + PATCH（§5.2）；组件零改动 |
| 编辑器字体 Select（L118-129） | `useState<FontKey>('sans')` 本地 state | state 移除，改 store 读 + store setter |
| 关闭窗口时 Select（L134-152） | 本地 state + 挂载 IPC 读 + 切换 IPC 写（内存态） | state 移除，改 store 读 + store setter（PATCH 成功才 IPC） |
| 新章节默认字数（L63-68/L89-110） | 本地 state + onBlur PATCH（缺陷链 §5.4） | dirty 跟踪 + 卸载 flush + 切项目重读（§5.4） |
| 快捷键一览（L167-179） | 纯展示 | 不动 |
| 首次托盘提示开关 | 不存在 | 新增（紧邻关闭行为 Select） |

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| 1 | 首次启动（空表）GET /settings | 全默认值响应；前端按 §5.2 规则保留系统深色策略 |
| 2 | 后端不可达（内核未起/崩溃，fetch 网络层失败） | 前端保持 localStorage 快照继续运行；console.warn；不弹 toast（启动期静默兜底，F19 §4.4 KernelOfflineError 语义） |
| 3 | GET /settings 401（token 未注入竞态） | ensureApiReady 已消除 Electron 生产竞态（#98 修复）；仍出现 → 按失败兜底（同 #2） |
| 4 | PATCH 值域非法（如 theme: "dark"） | 后端 422 + detail；前端 store setter catch → err toast（视觉设置值保留，行为设置值回弹，§5.2/§5.3） |
| 5 | PATCH 未知字段（前端拼写错误） | 后端 422 `Extra inputs are not permitted`——显式暴露前端 bug（#105 教训）；前端 toast 展示 detail |
| 6 | app_settings 表脏数据（value 非合法 JSON） | service `_merge` 防御性忽略该键，其余正常返回（不 500）——脏数据仅可能来自手工改库 |
| 7 | 视觉设置 PATCH 失败（后端临时故障） | 本地值保留 + err toast；下次启动 GET 以后端为准（本地与后端不一致窗口期 = 本次会话） |
| 8 | close_behavior PATCH 失败 | Select 回弹原值 + err toast；主进程行为不变（持久化失败 = 行为不切换，诚实一致） |
| 9 | default_words 跳页 + flush PATCH 失败 | err toast（全局 toast store，卸载后仍可弹）；输入值随组件卸载丢失（极端场景最终兜底，无数据损坏） |
| 10 | 切换当前项目 | default_words 输入框重读新项目 config.default_words + 清 dirty（缺陷 #2 修复）；设置库字段（theme 等）不受项目影响（Q1 建议 A 全局语义） |
| 11 | 并发写（双窗口/快速连续 PATCH） | last-write-wins（SQLite upsert）；单用户本地场景无冲突面（busy_timeout=5000 已覆盖锁等待，F19 §2.4） |
| 12 | 旧库升级（无 app_settings 表） | create_all 建缺失表，零迁移（§2.3）；旧 localStorage 值由 §5.2 双轨加载自动接管 |
| 13 | 浏览器 dev 模式（无 Electron/无 preload） | `window.INKFLOW_API?.settings?.` 可选链吞掉（F31 先例）；close_behavior 显示 store 默认 'tray'；后端 API 走 Vite env（getApiConfig 回退） |
| 14 | 主进程启动窗口期（renderer 未完成初始化） | 主进程按默认 'tray' 拦截；<1s 窗口期语义偏差可接受（§5.3） |
| 15 | 设置页关闭行为 Select 在非 Electron 环境切换 | store setter PATCH 后端成功但 IPC 无对象（可选链）→ 仅持久化，运行时行为无从生效（dev 浏览器无主进程，语义完整） |
| 16 | tray_hint_dismissed 开关打开（复位 false） | 仅写后端；主进程内存态保持 true 无害（本会话不再提示；重启后 §5.3 初始化对齐 false → 重新提示） |

---

## 8. 文件结构

对照真实源码树（2026-08-08 实测，main @ 7bdf5d1）：

### 8.1 后端 CREATE

```text
backend/src/inkflow/domain/models/settings.py                          ← CREATE: AppSettings/AppSettingsUpdate/SettingsKey（§2.2）
backend/src/inkflow/domain/ports/settings_repository.py                ← CREATE: SettingsRepositoryProtocol（§2.4）
backend/src/inkflow/domain/services/settings_service.py                ← CREATE: SettingsService（§2.5）
backend/src/inkflow/infrastructure/database/models/settings.py         ← CREATE: SettingsORM（§2.3）
backend/src/inkflow/infrastructure/database/repositories/settings_repo.py ← CREATE: SQLiteSettingsRepository（get_all/set_many）
backend/tests/unit/test_settings_models.py                             ← CREATE: DTO 枚举/未知字段/默认值（§9）
backend/tests/unit/test_settings_repo.py                               ← CREATE: repo upsert/编解码（§9）
backend/tests/unit/test_settings_service.py                            ← CREATE: 默认补齐/部分更新/白名单/脏数据（§9）
tests/api/test_settings_api.py                                         ← MODIFY（评审 🟡 修订：文件已存在——F19 #79 llm-keys/llm-test 契约 563 行）：**追加** F32 段（GET/PATCH /settings），严禁覆盖既有契约；沿用文件头模式（TestClient 直连 app + monkeypatch.delenv INKFLOW_SERVER_TOKEN 无 token 直通，§9.1 详）
```

### 8.2 后端 MODIFY

```text
backend/src/inkflow/domain/models/__init__.py                          ← MODIFY: 导出 AppSettings/AppSettingsUpdate/SettingsKey
backend/src/inkflow/domain/ports/__init__.py                           ← MODIFY: 导出 SettingsRepositoryProtocol
backend/src/inkflow/domain/services/__init__.py                        ← MODIFY: 导出 SettingsService
backend/src/inkflow/infrastructure/database/models/__init__.py         ← MODIFY: 注册 SettingsORM（create_all 建表前提，import 触发 metadata）
backend/src/inkflow/infrastructure/database/repositories/__init__.py   ← MODIFY: 导出 SQLiteSettingsRepository
backend/src/inkflow/api/deps.py                                        ← MODIFY: get_settings_service（镜像 get_provider_config_service）
backend/src/inkflow/api/routers/settings.py                            ← MODIFY: 加 GET /settings + PATCH /settings（§3；既有 llm-keys/llm/test 不动）
backend/src/inkflow/api/app.py                                         ← 无需改动（settings.router 已注册 L125；create_tables 经 models/__init__ import 链建表）
```

### 8.3 前端 MODIFY

```text
frontend/packages/renderer/src/stores/theme.ts                        ← MODIFY: 扩展为统一设置 store（font/closeBehavior/trayHintDismissed +
                                                                          initFromBackend + setter 后端同步；导出名 useThemeStore 保持）
frontend/packages/renderer/src/theme/index.ts                         ← MODIFY: FontKey 类型移入（与 ThemeName 并列）
frontend/packages/renderer/src/api/client.ts                          ← MODIFY: fetchSettings/patchSettings + AppSettings 类型 + SettingsApi 补
                                                                          dismissTrayHint（interface L20-23）
frontend/packages/renderer/src/pages/settings.tsx                     ← MODIFY: GeneralPanel（font/closeBehavior 从 store 读；首次提示开关；
                                                                          default_words 守卫 §5.4；FontKey import 来源改 theme/index）
frontend/packages/renderer/src/App.tsx                                ← MODIFY: AppLayout 挂载 initFromBackend()（§5.2 步骤 ②）
frontend/packages/renderer/src/i18n/zh.ts + en.ts                     ← MODIFY: set.trayHint 开关文案
frontend/packages/renderer/src/stores/theme.test.ts                   ← MODIFY: 加载时序/缓存回写/默认策略/失败兜底契约（§9）
frontend/packages/renderer/src/pages/settings.test.tsx                ← MODIFY: font/closeBehavior 读 store、开关、default_words 守卫契约（§9）
frontend/packages/renderer/src/App.test.tsx                           ← MODIFY: AppLayout 挂载 → initFromBackend 调用断言（§9.1 App 加载）
frontend/packages/renderer/src/api/__integration__/client.integration.test.ts ← MODIFY: GET/PATCH /settings 真实内核往返冒烟（§9.1 集成层；vitest.integration.config.ts include 只收集 src/api/__integration__/**）
frontend/packages/renderer/vitest.config.ts                           ← MODIFY: thresholds 随新代码上调（renderer 99.11/92.51/84.54/99.11 基线，ADR-027）
```

### 8.4 Electron 与 E2E

```text
frontend/packages/electron/src/main.ts                                 ← 无需改动（复用 settings:* 三通道；跑既有测试验证不回归）
frontend/packages/electron/src/preload.ts                              ← 无需改动（settings 命名空间已含三方法，L67-74）
frontend/packages/electron/vitest.config.ts                            ← MODIFY: thresholds 随实现实测上调（2026-08-08 基线 88/90/80/88，
                                                                          实测 90.43/93.98/82.97/90.43）
tests/e2e/e2e-settings.spec.ts                                         ← MODIFY: default_words 跳页保留断言 + theme 持久化冒烟（§9）
tests/e2e/e2e-tray.spec.ts                                             ← MODIFY: 关闭行为持久化契约（重启保留场景，若 E2E 支持重启；否则手动兜底）
.github/workflows/ci.yml                                               ← 无需改动（e2e-settings / e2e-shell e2e-tray job 已存在；PYTHONUTF8=1 既有）
```

> **ci.yml 说明**：前端三层 job（lint-frontend / unit-frontend / integration-frontend）+ e2e-frontend-* 已存在（#79/#139）；本模块无新 job、无新测试文件收集问题（vitest glob 自动收集，unit 测试无需显式注册——#59/#61 教训仅针对后端 CLI 测试文件）。

---

## 9. 测试策略

### 9.1 层次与关键场景

| 层次 | 关键场景 |
|------|----------|
| 后端单元（backend/tests/unit/，pytest） | **test_settings_models.py**：AppSettingsUpdate 枚举校验（theme='dark' → ValidationError）；未知字段 → ValidationError（extra='forbid'）；空更新对象（全 None）合法；AppSettings 默认值齐全。**test_settings_repo.py**：get_all 空表 {} / 多行 JSON 编解码往返；set_many upsert（同 key 覆盖）；mock AsyncSession（test_provider_config_repo.py 先例）。**test_settings_service.py**：get_settings 空表 → 全默认；部分持久化键 → 合并；update_settings 白名单过滤（DTO 已校验，service 只筛非 None）；脏 JSON 防御忽略；set_many 不被调用当 payload 为空 |
| 后端 API（tests/api/test_settings_api.py **追加段**——评审 🟡 修订：文件已存在，TestClient 直连 app + 文件头 monkeypatch.delenv 无 token 直通模式，**沿用**而非 ASGITransport；401 用例另设 env-set fixture（test_token_auth.py 式：`INKFLOW_SERVER_TOKEN` 设值 + TestClient 带 X-InkFlow-Token 头）） | GET 空表全默认 200；GET 含持久化键；PATCH theme → 200 全量 + 落库回读；PATCH 未知字段 → 422；PATCH 非法枚举 → 422；PATCH 空 body → 422；PATCH 无 token → 401（token 中间件契约，F19）；PATCH 后 GET 一致性 |
| 前端单元（vitest jsdom，renderer） | **stores/theme.test.ts 升级**：initFromBackend 成功 → store 覆盖 + localStorage 回写（断言 inkflow.ui 新值）；后端全默认 + 本地无记录 → theme 不覆盖（系统深色策略保留）；后端不可达 → 保持快照不抛错；setter → PATCH 调用断言 + 失败 err toast；closeBehavior setter → PATCH 成功后才 IPC 推送、失败回弹；font/trayHintDismissed 状态管理。**settings.test.tsx 契约升级**：font Select 值来自 store（非本地 state）；closeBehavior Select 值来自 store；首次提示开关渲染 + 切换 → PATCH tray_hint_dismissed；default_words dirty 跟踪 + 卸载 flush（fire-and-forget PATCH 断言）；切项目重读。**App 加载**：AppLayout 挂载 → initFromBackend 调用断言（App.test.tsx 扩展） |
| 前端单元（vitest node，electron） | **既有契约回归**：main.tray.test.ts（settings:get/set/dismiss handler 行为不变）、preload.test.ts（settings 命名空间三方法）——本模块主进程零改动，测试仅验证不回归；若实现时需上调 thresholds 则按实测补测 |
| 集成（vitest.integration.config.ts） | 真实内核往返冒烟：GET/PATCH /settings 经 apiFetch（含 token 注入） |
| E2E（Playwright _electron，tests/e2e/） | **e2e-settings.spec.ts 扩展**：① default_words 修改后直接切导航 → 返回设置页值保留（跳页不丢，issue 验收 1）；② 主题切 night → 重启应用 → 仍为 night（持久化验收；重启 = 二次 launch 复用同一数据目录）；③ 后端不可达降级冒烟（可选，时序敏感）。**e2e-tray.spec.ts 扩展**：关闭行为设「直接退出」→ 重启 → 关闭窗口 = 完整退出（持久化验收，issue 隐性验收 4）；若 E2E 重启场景成本高 → 该断言降级手动（M6 标注）。**隔离策略（评审 🟡 修订）**：F32 后主题持久化在后端（app_settings）——既有「清 localStorage 保证文案确定性」不再充分；重启用例显式声明独立数据目录（launch 传 `--user-data-dir` 临时目录），普通用例与重启用例分文件/分 describe 隔离，跨用例后端残留由独立目录根治 |
| 手动冒烟（Windows） | 设置页改 font/theme/语言 → 重启 GUI 保留；关闭行为 'quit' → 重启 → 关闭直接退出；首次提示开关关 → 重启 → 最小化不弹提示；旧版 localStorage 用户升级 → 主题自动接管不闪烁 |

### 9.2 覆盖率门禁（硬约束，ADR-027）

| 面 | 门槛 | 说明 |
|----|------|------|
| 后端 | 行 98.5% / 分支 95.0% | 全仓合并口径（unit + 顶层 tests/ 合并后由 ci_cd/check_coverage.py 断言）；新代码（settings 域 4 文件 + API 端点）必须内嵌补测，QA 全仓复验 |
| 前端 renderer | vitest.config.ts 内嵌 thresholds：99.11 / 92.51 / 84.54 / 99.11 | theme store 重构 + settings.tsx 改动是**高风险覆盖率面**——store 新分支（加载/失败/回弹）必须逐条断言，跌破基线禁止 merge（#104 纪律：thresholds 逐 PR 上调不下降） |
| 前端 electron | 88 / 90 / 80 / 88（2026-08-08 实测基线 90.43/93.98/82.97/90.43） | 主进程零改动 → 理论不降；若实现触碰 main.ts 则按实测上调 |
| E2E | e2e-settings / e2e-shell+e2e-tray job 全绿 | PYTHONUTF8=1 + 先 build renderer dist（既有约定）；e2e 不进常规 merge 门禁外的额外门槛（ADR-028 现状） |

### 9.3 TDD 顺序建议

RED 批 1（后端契约）：test_settings_models → test_settings_repo → test_settings_service → test_settings_api（api-test-engineer）→ Codex GREEN。RED 批 2（前端契约）：theme.test.ts 升级 → settings.test.tsx 升级 → App.test.tsx（frontend-test-engineer）→ Codex GREEN。E2E 契约批 3：e2e-settings/e2e-tray 扩展。

### 9.4 关键测试用例明细（契约断言清单）

| 测试文件 | 用例 | 断言要点 |
|----------|------|----------|
| test_settings_models.py | 默认值齐全 | AppSettings().model_dump() == 6 字段默认字典 |
| | 枚举校验 | AppSettingsUpdate(theme='dark') → ValidationError（Literal 拒绝） |
| | 未知字段 | AppSettingsUpdate(themee='night') → ValidationError（extra='forbid'） |
| | 空更新合法 | AppSettingsUpdate()（全 None）不抛错——路由层负责空 body 422 |
| test_settings_repo.py | 空表 | get_all() == {} |
| | 编解码往返 | set_many({'theme': '"night"'}) → get_all() 原样返回（repo 不解析，解析在 service） |
| | upsert 覆盖 | 同 key 两次 set_many → 单行 + 新值（commit 断言） |
| test_settings_service.py | 空表默认补齐 | get_settings() == 全默认 |
| | 部分持久化合并 | 表含 theme → get_settings().theme=='night' 其余默认 |
| | 部分更新 | update_settings(theme='night') → repo.set_many 收到 {'theme': '"night"'}（JSON 编码断言）+ 返回全量 |
| | 空 payload 不写库 | update_settings(全 None) → repo.set_many 不被调用 |
| | 脏 JSON 防御 | 表含非法 JSON 键 → 忽略该键，其余正常 |
| test_settings_api.py | GET 全默认 | 200 + 6 字段默认值（无 token → 401 对照用例） |
| | PATCH → GET 一致 | PATCH theme=night → 200 全量 → GET 回读一致 |
| | 三路 422 | 未知字段 / 非法枚举 / 空 body 各 422 + detail 断言 |
| | 多字段组合 | PATCH {theme, font, close_behavior} → 全量响应含三新值 |
| theme.test.ts（升级） | 加载三分支 | 后端 night → 覆盖；后端默认 paper + 本地有记录（本地 night）→ **保留本地 night**（评审 🔴-1 修订：后端 'paper' = 无显式选择记录，不覆盖本地显式选择）；后端默认 paper + 本地无记录 → 保留系统深色策略 |
| | 缓存回写 | initFromBackend 成功后 localStorage 'inkflow.ui' 含 font（新字段） |
| | 后端不可达 | fetchSettings reject → store 保持快照 + console.warn 调用断言 |
| | 视觉 setter | setTheme → PATCH body {theme} + localStorage 回写；PATCH reject → err toast + 本地值保留 |
| | 行为 setter | setCloseBehavior → PATCH 成功后才 IPC 推送（mock window.INKFLOW_API.settings）+ store 更新；PATCH reject → 不推送 + Select 值回弹 |
| | IPC 初始化 | initFromBackend 遇 close_behavior='quit' → setCloseBehavior('quit') 被调用；tray_hint_dismissed=true → dismissTrayHint 被调用 |
| settings.test.tsx（升级） | font 读 store | 渲染初值 = store.font（非本地 state 写死） |
| | 关闭行为读 store | 渲染初值 = store.closeBehavior（现状 L86 IPC 挂载读可迁移或并存） |
| | 首次提示开关 | 渲染 + 切换 → store.setTrayHintDismissed 调用断言 |
| | default_words 卸载 flush | 输入 5000 → 切分类 → PATCH 已发出（mock apiFetch/updateConfig 断言）→ 返回后值保留 |
| | default_words 卸载 flush 最新值 | 输入 5000 → 再改 6000 → 立即切分类 → PATCH body 携带 6000（评审 🟡-7：ref 镜像契约） |
| | default_words flush 成功同步 | flush PATCH 成功 → project store 本地 config.default_words 已更新（评审 🔴-2：remount 懒初始化读新值的前提） |
| | default_words 失败 | 卸载 flush PATCH reject → err toast + agent store.config.default_words 未被污染 |
| | 切项目重读 | currentProjectId 变化 → 输入框显示新项目值 |
| | 空项目不保存 | 无当前项目时输入 → 卸载 → PATCH 未发出（评审 🟢） |
| test_settings_api.py（追加段） | DB 异常 | mock repo raise → 500（评审 🟢：§3.4 异常映射补齐） |
| e2e-settings.spec.ts | 跳页保留 | 改 default_words → 切导航 → 返回 → 输入框值保留（issue 验收 1） |
| | 重启保留 | 切 night → 重启（二次 launch 同数据目录）→ data-theme=night |
| e2e-tray.spec.ts | 关闭行为持久化 | 设 quit → 重启 → 点关闭 → 内核回收 + 应用退出（M6） |

> 表格为 RED 契约下限（实现必须覆盖的断言面），非上限——实现阶段按 TDD 惯例补充分支用例，覆盖率门禁为最终裁决（§9.2）。

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| 云端设置同步（多设备在线同步） | 2.0.0 云里程碑（ADR-024）；本模块只做「同一数据目录内重启保留 + 目录迁移随身走」 |
| 设置迁移 UI/导入导出工具 | 旧 localStorage 自动接管（§5.2 双轨），无用户可见迁移动作；导出导入属云同步范畴 |
| default_words 全局化（移出项目 config） | 语义上它是项目级字段（F1 ProjectConfig），保持现状；本模块只修保存时机 |
| 模板/模型对话框保存确认（守卫） | 显式保存/取消是标准对话框 UX（Q3 建议 C）；加确认框 = 打扰 |
| AgentLlmCard 死代码清理 | 未接线组件（仅测试引用），删除属另案（YAGNI，不随本模块） |
| 主进程直连后端读设置 | 职责分离（§5.3）：主进程保持无 HTTP 依赖，renderer 单向桥接 |
| CLI 设置命令 | YAGNI（§4）：消费方 = GUI + 主进程，CLI 无设置概念 |
| 设置加密 | 本库无敏感字段；API key 走既有 APIKeyManager（AES-256-GCM，F19 #79） |
| 新增设置项（开机自启/自动保存间隔等） | YAGNI（未拍板）；本模块建库 + 6 项首批，新设置项后续按枚举扩展 |
| 多用户/多 profile 设置隔离 | 单用户本地应用（ADR-019 本地优先），无此场景 |
| 视觉设置失败回滚（PATCH 失败 → UI 回弹） | 乐观更新 + 失败 toast + 下次启动收敛（§5.2）；回弹只用于行为设置（close_behavior） |

---

## 11. 依赖关系

| 依赖方 | 依赖 | 说明 |
|--------|------|------|
| F32（本模块） | F31 #167 ✅（PR #172） | settings:* IPC 三通道（get/set-close-behavior + dismiss-tray-hint）+ 托盘 + 关闭拦截状态机——本模块复用通道做持久化桥接，主进程零改动 |
| F32 | F19 #105 ✅ | 设置页框架（五分类导航 + GeneralPanel）+ Agent 即改即存模式（persist + in-flight 守卫先例） |
| F32 | F19 #79 ✅ | 渲染层基建（apiFetch/ensureApiReady/isElectronEnv + token 注入）+ settings router 既有端点 |
| F32 | F19 #106 ✅ | ProviderConfig 设置类实体先例（domain/ORM/repo/service/deps 五件套镜像） |
| F32 | F19 #78 ✅ | Electron 壳 + preload（INKFLOW_API 注入时序，#98 修复的 ensureApiReady） |
| F32 | F9 ✅ | 错误类复用惯例（本模块无自定义错误类，校验收敛 DTO 层） |
| #167（F31） | F32（归口依赖，倒置） | F31 关闭行为设置/首次提示为内存态，**合入 F32 后切换持久化**（f31 spec §2.2 注释「#152 合入后切换」兑现） |
| 未来客户端（MCP/skills/CLI） | F32（潜在） | 设置库 API 是通用契约，未来消费方走 GET/PATCH /settings 即可（§4 不预建 CLI 面） |

**编号口径声明**：F25 移除后 F26-F29 为 Agent 化升级规划，F30 = 内核冷启动基建（第 13 变体），F31 = GUI 托盘（前端壳层变体，未入谱系计数），本模块承接 **F32**（第 14 变体「设置域横切型」）；若与 ADR-019 v5+ 冲突以 ADR-019 为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| D1 | 持久化载体 | **key-value 行表 app_settings**（key PK + JSON value） | 设置项演进免 ALTER；create_all 零迁移；通用编码；与「统一设置库」拍板语义一致（§2.6 论证表） | 单行 JSON 表（❌ 部分更新整行重写，并发覆盖面大）；project config.extra + 主进程文件（❌ 语义错位 + 两套设置系统，F31 拍板明确禁止） |
| D2 | 默认值补齐 | service 层合并默认值，**不落库、无 seed** | 表行数 = 实际修改项；无 seed 逻辑；「读缺失 → 默认」语义天然（对照 provider_configs seed 先例：注册表需要显式行，设置库不需要） | 启动 seed 全键（❌ 无谓行 + 幂等复杂度） |
| D3 | theme 默认值语义 | 后端默认 'paper' = 「无显式选择」；系统深色跟随 = 前端首帧策略（§5.2 覆盖规则三分支） | 后端无法感知 `prefers-color-scheme`（无头内核）；首帧快照保留前端既有拍板语义（F19 §4.3）；后端只存用户显式选择 | 后端存 night（❌ 深色用户被钉死，无「跟随系统」表达）；后端存 null 可空（❌ 六字段一个可空 = 接口不对称） |
| D4 | 前端 store 方案 | **扩展 stores/theme.ts 为统一设置 store**（导出名 useThemeStore 保持），不新建 settings store | 零破坏：App.tsx/AppearanceCard/settings.tsx/顶栏/测试全部既有 import 不动；theme store 语义本就是「全局 UI 设置」，font 同域；避免双 store 镜像同步（双真相源） | 新建 stores/settings.ts + theme store 派生（❌ 双 store 同步复杂度 + 全量 import 重构，收益为零）；theme store 改名 settings store（❌ 破坏性重构，无必要） |
| D5 | 主进程桥接 | **复用既有 settings:* 三通道**，renderer 单向驱动（启动初始化 + PATCH 成功后推送）；主进程零改动；双权威声明（后端持久化 / 主进程运行时） | 通道语义与持久化后的「初始化/更新内存态」完全吻合（main.ts L505 含值域校验）；零新 IPC = 零新测试面；主进程无 HTTP 依赖（ADR-021 分层） | 新增通用 settings:apply 通道（❌ 与既有通道功能重叠，双通道并存 = 主进程状态机两入口）；主进程直连后端（❌ 重复 token/端口管理 + 时序耦合） |
| D6 | API 契约 | GET 全量 + PATCH 部分更新（响应恒全量）；**extra='forbid' 未知字段 422**；空 body 422；幂等 upsert | 部分更新 = 前端只发改动字段（最小写面）；未知字段 422 是前端拼写错误的显式信号（#105 extra='ignore' 静默吞字段教训）；全量响应免二次 GET | extra='ignore'（❌ #105 实测教训）；PATCH 空 body no-op 200（❌ 静默成功掩盖客户端 bug）；只返回改动字段（❌ 客户端要多一次 GET 或自行合并） |
| D7 | 表单守卫形态 | default_words 卸载 flush + dirty 跟踪 + 切项目重读；对话框保持显式语义（Q3 建议 C） | 保存动作与导航解耦（卸载 cleanup fire-and-forget PATCH）——「跳页丢修改」根源 = 保存时机依赖组件生命周期事件（blur），改为依赖卸载路径即修复；对话框显式保存 = 行业标准；agent 面板已即改即存无草稿 | useBlocker 导航拦截（❌ HashRouter 数据路由 API 可用性未验证 + 单输入框弹确认过打扰）；全局草稿持久化（❌ 复杂度不值：数字输入框草稿恢复场景不存在）；全部表单自动保存（❌ 对话框半截输入被自动提交 = 数据污染） |
| D8 | 迁移策略 | **零迁移**：新表由 create_all 自动建（旧库升级只建缺失表）；不引入 PRAGMA+ALTER | app_settings 是全新表（非既有表加列）——`ensure_provider_builtin_key_column` 先例仅适用于加列场景，本模块不适用；create_all 幂等语义已覆盖 | 预写 ALTER 迁移（❌ 表不存在时 ALTER 报错，需 no-op 分支——为不存在的问题写代码）；PRAGMA 判表（❌ 多此一举，create_all 天然只建缺失） |
| D9 | close_behavior 写入顺序 | PATCH 持久化成功 → 才 IPC 推送主进程；失败 → Select 回弹 + toast | 「持久化失败 = 行为不切换」诚实一致——避免 UI 显示新行为但主进程/重启后行为是旧的（双不一致） | 先 IPC 后 PATCH（❌ 运行时生效但持久化失败 → 重启回退，用户困惑）；乐观更新不回弹（❌ UI 与主进程行为不一致） |

---

## 13. 验收标准

| # | 验收（issue 映射） | 自动化载体 | 验证 |
|---|-------------------|-----------|------|
| M1 | 修改 default_words 后直接跳页 → 返回仍保留修改（issue 验收 1） | 单元 + E2E | 卸载 flush PATCH 断言 + **project store 同步断言**（评审 🔴-2：updateConfig 本地合并 → remount 懒初始化读新值，settings.test.tsx）；e2e-settings：输入 → 切导航 → 返回输入框值保留 |
| M2 | default_words 非法值（<1000）跳页 → 不保存 + err toast；切项目 → 输入框重读新项目值 | 单元 | flush 分支断言（<1000 / 空值 / 合法三路）；currentProjectId 变化重读断言 |
| M3 | theme/语言/字体后端持久化：PATCH 落库 + GET 回读 + 重启保留（issue 验收 2） | API 集成 + E2E + 手动 | tests/api/test_settings_api.py PATCH→GET 一致性；e2e-settings 重启保留断言（M6 同法）；手动跨重启冒烟 |
| M4 | 启动加载时序：localStorage 快照 → 后端覆盖 → 缓存回写；新用户系统深色策略保留 | 单元 | theme.test.ts：三分支覆盖规则断言（§5.2） |
| M5 | 后端不可达 → localStorage 兜底，UI 不阻塞不崩 | 单元 | theme.test.ts：GET reject → store 保持快照 + console.warn |
| M6 | 关闭行为「直接退出」持久化：设置 → 重启 → 关闭窗口 = 完整退出（issue 隐性验收 4） | E2E（或手动降级）+ 单元 | e2e-tray 重启保留断言（若 E2E 重启成本高 → 手动冒烟 + 单元断言 PATCH 成功后才 IPC）；启动初始化 IPC 推送断言（theme.test.ts mock IPC） |
| M7 | 首次托盘提示开关：GeneralPanel 开关渲染 + 切换 → PATCH tray_hint_dismissed + 关闭后重启不提示 | 单元 + 手动 | settings.test.tsx 开关契约；手动：关 → 重启 → 最小化无 toast |
| M8 | 非法值域/未知字段/空 body → 422；无 token → 401 | API 集成 | tests/api/test_settings_api.py 异常映射断言（§3.4 表逐行） |
| M9 | 覆盖率门禁复验 | CI | 后端全仓 98.5 行 / 95.0 分支（check_coverage.py）；renderer thresholds 不降且按实测上调；electron 88/90/80/88 保持 |
| M10 | 回归：F31 托盘行为不回归（settings:* IPC 契约不变）；#105 Agent 即改即存不回归；F19 设置页功能不回归 | 单元 + E2E | main.tray.test.ts / preload.test.ts 既有契约全绿；settings.test.tsx 既有 describe 块全绿；e2e-shell / e2e-settings 全绿 |

> 覆盖门禁：全仓 CI 全绿（lint / unit / integration / e2e-frontend-*）后才 merge；E2E 需 PYTHONUTF8=1 + 先 build renderer dist（既有约定）。手工验证闭环：打包冒烟（win-unpacked）走 M3/M6/M7 三场景。

**验收命令清单**（实现/QA 阶段直接可跑）：

```powershell
# 后端单元 + API（从仓库根；unit 与顶层 tests 分开跑——#61 教训）
uv run --project backend pytest backend/tests/unit/test_settings_models.py backend/tests/unit/test_settings_repo.py backend/tests/unit/test_settings_service.py -q
uv run --project backend pytest tests/api/test_settings_api.py -q
# 全仓覆盖率复验（ADR-027：行 98.5 / 分支 95.0，ci_cd/check_coverage.py 断言）
uv run --project backend pytest backend/tests/unit tests/api tests/integration tests/cli --cov=inkflow --cov-branch --cov-report=term-missing -q

# 前端 renderer（覆盖率内嵌 thresholds 99.11/92.51/84.54/99.11）
pnpm --filter renderer vitest run --coverage
# 前端 electron（88/90/80/88）
pnpm --filter electron vitest run --coverage

# E2E（先 build renderer dist + PYTHONUTF8=1，既有约定）
$env:PYTHONUTF8 = "1"
pnpm --filter renderer build
pnpm --filter inkflow-electron test:e2e e2e-settings
pnpm --filter inkflow-electron test:e2e e2e-shell e2e-tray

# 手工冒烟（打包态）
# 1) 设置页改字体/主题 → 重启 GUI → 保留（M3）
# 2) 关闭行为改「直接退出」→ 重启 → 关闭窗口直接退出（M6）
# 3) 首次提示开关关闭 → 重启 → 最小化到托盘不弹提示（M7）
# 4) 旧版本 localStorage 用户升级 → 主题自动接管无闪烁（§5.2 双轨）
```

---

## 14. 待澄清问题（≤3，评审时确认）

- **Q1 theme 持久化粒度**：A. **全局用户偏好**（建议——与「跨设备保留」语义一致：主题是个人审美不是项目属性；切项目不跳主题；实现 = 本 spec 全局设置库，最简）；B. 按项目（与「设定库」语义一致：不同书不同氛围——但 ProjectConfig 是写作内容配置，混入 UI 主题 = 内容/外观耦合；且「跨设备保留」按项目粒度 = 每项目都要重设）；C. 综合（全局默认 + 项目覆盖——两套真相源 + 覆盖规则复杂度，单用户本地场景收益为零）。**建议 A**：B 的「按项目主题」场景（不同书不同氛围）可用「写作时手动切主题」覆盖，不值得为此引入项目级 UI 设置字段。**✅ 已确认（用户拍板：选项 A，2026-08-08）**——正文按全局语义（§2.1 消费方标注 + §10 按项目主题归不在范围）。

- **Q2 持久化载体**：A. **新 key-value app_settings 表**（建议——设置库统一承载、create_all 零迁移、future-proof 加键免 ALTER；§2.6 论证表）；B. 单行 JSON 表（一个 row 存全部设置——读简单但部分更新 = 整行重写，并发覆盖面大）；C. 复用 project config.extra + 主进程本地文件（零新表但全局设置混入项目 config 语义错位 + 主进程文件 = 第二套持久化，F31 拍板明确禁止两套设置系统）。**建议 A**。**✅ 已确认（用户拍板：选项 A，2026-08-08）**——正文即按 key-value 表设计（§2.3/§12 D1）。

- **Q3 表单草稿守卫形态**：A. 自动保存（导航前 flush 全部未提交修改，失败 toast）；B. 跳页提示（dirty 时 confirm 对话框拦截导航）；C. **综合（建议）**：default_words 类文本输入自动 flush（卸载路径，保存动作与导航解耦）+ 保存失败 toast 可见；对话框表单（模板/模型）保持显式保存/取消语义（关闭即取消是标准对话框 UX，半截输入被自动提交反而是数据污染）；Agent 面板已是即改即存无需守卫。**建议 C**——B 的「弹确认框」对单个数字输入框是过度打扰（用户可能只是路过设置页），且 useBlocker 在 HashRouter 的可用性未验证（§12 D7）。**✅ 已确认（用户拍板：选项 C，2026-08-08）**——正文即按综合守卫设计（§5.4/§12 D7）。

> 说明：Issue #152 评论区已拍板范围 ①②③ + 归口 ④⑤（2026-08-07），本表 Q1-Q3 为 spec 起草阶段补充识别的设计决策点；拍板后正文按结论修订并留痕。
