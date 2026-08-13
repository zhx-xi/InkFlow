"""F21 ExportService 聚合编排单元测试 — mock 7 个 repo（RED 阶段，仅测试不实现）。

被测模块: ``inkflow.domain.services.output_service.ExportService``（§5.1/§8.2）。

┌─ 模块契约（GREEN 实现者以此为准，docstring 即唯一契约）────────────────┐
│ 1. 构造签名（§8.2 逐字）:                                                │
│    ExportService(project_repo, chapter_repo, character_repo, world_repo, │
│    outline_repo, timeline_repo, foreshadowing_repo)                      │
│    全部为既有 Repository Protocol 注入（零跨模块 MODIFY）。              │
│ 2. 主方法（任务书拍板：返回 BookDocument，API/CLI 层再包装 ExportResult）│
│    async def export(self, project_id: int | uuid.UUID,                   │
│                     include_settings: bool = False) -> BookDocument      │
│ 3. id 转换（F15 _to_int_id 先例）: uuid.UUID → .int 传入 repo 层；       │
│    int 原样透传。                                                        │
│ 4. 正文聚合（§5.1 ②/§5.2）:                                             │
│    a. list_volumes(pid_int) 拉卷骨架                                     │
│    b. list_chapters(pid_int, offset=..., limit=50) 全量拉取（真实 repo   │
│       语义 volume_id=None=不过滤，2026-08-09 核实——未分组章无法用       │
│       volume_id 参数筛选，必须全量拉取后内存分组）                       │
│    c. 循环分页: while 累计 < total 继续拉（M1 兜底，绝不默认 50 条丢章） │
│    d. 软删过滤: Chapter 领域模型/表无 is_deleted 字段（2026-08-09 核实）│
│       → getattr(chapter, "is_deleted", False) 防御性过滤（M4）           │
│    e. 内存按 chapter.volume_id 分组: 卷内章挂对应卷；volume_id=None 的  │
│       章归「未分组」卷（title 常量 "未分组"），排在所有命名卷之后（M5， │
│       §6.1）；未分组卷 order_index 不锁具体值（只保证排最后）            │
│ 5. 排序键（§6.1，显式排序不依赖 repo）:                                  │
│    卷 order_index ASC；章（卷内）order_index ASC, created_at ASC；       │
│    角色/世界观/伏笔 created_at ASC；大纲 sort_order ASC, created_at ASC；│
│    情节点 position ASC；时间线 narrative_position ASC, created_at ASC    │
│ 6. include_settings 分支（Q3=C 拍板）:                                   │
│    a. False（默认）→ settings=[]，且 character/world/outline/timeline/  │
│       foreshadowing 五个 repo 方法均不得被调用（条件依赖，性能契约）     │
│    b. True → 5 类各聚合成 BookSetting，顺序固定 character → world →     │
│       outline → timeline → foreshadowing（§5.1 ③）                      │
│ 7. 附录摘要拼接（§6.3 逐字，BookSetting.content）:                       │
│    a. character: 行拼接 性格：{personality} / 背景：{background} /      │
│       目标：{goals}（空字段跳过；全空 → 空串）                           │
│    b. world: {category}：{content}（category 空 → 仅 {content}）         │
│    c. outline: {description} + 每情节点一行                             │
│       "- {point.name}（{point.type}）: {point.description}"（position    │
│       升序；description 与情节点行之间 \n 连接）                         │
│    d. timeline: {time_display}｜{description}（time_display 空 → 用      │
│       {title}）                                                          │
│    e. foreshadowing: 状态：{status.value}｜{description}（location 非空  │
│       追加 ｜埋设：{location}；status.value 即 StrEnum 值 "open"/        │
│       "resolved"）                                                       │
│ 8. 错误: project_repo.get → None → 抛 ProjectNotFoundError               │
│    （import 自 inkflow.domain.ports.character_errors，F9 既有模块，      │
│    §3.3 404 契约；本模块不重新导出该错误类）                             │
│ 9. 边界: 项目存在但无卷无章 → volumes=[] 不报错（E2）                    │
└──────────────────────────────────────────────────────────────────────────┘

RED 预期（实现不存在，收集期失败属设计使然）:
    collected 0 items / 1 error
    ModuleNotFoundError: No module named 'inkflow.domain.services.output_service'
（顶部 import 缺失实现 → 收集期整文件 ModuleNotFoundError；GREEN 时
实现落地自动收集。本文件 import 顺序: output_service 首个 → 收集错误
报告该模块，models.output 缺失被其遮蔽。）

依据: specs/f21-export-service/spec.md §5.1/§5.2/§6.1/§6.3/§7 E1-E2/§8.2/§9.2
场景 2-5 + 任务书拍板（返回 BookDocument）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.chapter import Chapter, Volume
from inkflow.domain.models.character import Character
from inkflow.domain.models.foreshadowing import Foreshadowing, ForeshadowingStatus
from inkflow.domain.models.outline import Outline, PlotPoint
from inkflow.domain.models.project import Genre, Project
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.services.output_service import ExportService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
TS_1 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
TS_2 = datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)
TS_3 = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)

# 未分组卷标题常量（契约：service 聚合常量，_txt_exporter 联动折叠）
UNGROUPED_TITLE = "未分组"

# 附录类型顺序（契约：§5.1 ③）
SETTING_TYPE_ORDER = ["character", "world", "outline", "timeline", "foreshadowing"]


# ── 实体构造 helpers（最小字段，既有测试惯例）─────────────────────────


def _project(
    name: str = "我的小说",
    *,
    genre: Genre = Genre.XUANHUAN,
    language: str = "zh-CN",
    target_words: int = 100_000,
) -> Project:
    """构造测试项目（属于 PID）。"""
    return Project(
        id=PID,
        name=name,
        genre=genre,
        language=language,
        target_words=target_words,
        created_at=TS,
        updated_at=TS,
    )


def _volume(vid: uuid.UUID, title: str, order_index: float) -> Volume:
    """构造测试卷（Volume 领域模型无 created_at，排序仅 order_index）。"""
    return Volume(id=vid, project_id=PID, title=title, order_index=order_index)


def _chapter(
    cid: uuid.UUID,
    title: str,
    *,
    volume_id: uuid.UUID | None = None,
    order_index: float = 0.0,
    content: str = "",
    word_count: int = 0,
    created_at: datetime = TS,
) -> Chapter:
    """构造测试章节。"""
    return Chapter(
        id=cid,
        project_id=PID,
        volume_id=volume_id,
        title=title,
        content=content,
        order_index=order_index,
        word_count=word_count,
        created_at=created_at,
        updated_at=created_at,
    )


def _char(
    cid: uuid.UUID,
    name: str,
    *,
    personality: str = "",
    background: str = "",
    goals: str = "",
    created_at: datetime = TS,
) -> Character:
    """构造测试角色。"""
    return Character(
        id=cid,
        project_id=PID,
        name=name,
        personality=personality,
        background=background,
        goals=goals,
        created_at=created_at,
        updated_at=created_at,
    )


def _world(
    wid: uuid.UUID,
    name: str,
    *,
    category: str = "",
    content: str = "",
    created_at: datetime = TS,
) -> WorldSetting:
    """构造测试世界观条目。"""
    return WorldSetting(
        id=wid,
        project_id=PID,
        name=name,
        category=category,
        content=content,
        created_at=created_at,
        updated_at=created_at,
    )


def _outline(
    oid: uuid.UUID,
    name: str,
    *,
    description: str = "",
    sort_order: int = 0,
    created_at: datetime = TS,
) -> Outline:
    """构造测试大纲。"""
    return Outline(
        id=oid,
        project_id=PID,
        name=name,
        description=description,
        sort_order=sort_order,
        created_at=created_at,
        updated_at=created_at,
    )


def _point(
    pid: uuid.UUID,
    outline_id: uuid.UUID,
    name: str,
    *,
    type_: str = "",
    description: str = "",
    position: int = 0,
) -> PlotPoint:
    """构造测试情节点。"""
    return PlotPoint(
        id=pid,
        outline_id=outline_id,
        project_id=PID,
        name=name,
        type=type_,
        description=description,
        position=position,
        created_at=TS,
        updated_at=TS,
    )


def _event(
    eid: uuid.UUID,
    title: str,
    *,
    description: str = "",
    time_display: str = "",
    narrative_position: int = 0,
    created_at: datetime = TS,
) -> TimelineEvent:
    """构造测试时间线事件。"""
    return TimelineEvent(
        id=eid,
        project_id=PID,
        title=title,
        description=description,
        time_display=time_display,
        narrative_position=narrative_position,
        created_at=created_at,
        updated_at=created_at,
    )


def _foreshadowing(
    fid: uuid.UUID,
    title: str,
    *,
    description: str = "",
    status: ForeshadowingStatus = ForeshadowingStatus.OPEN,
    location: str = "",
    created_at: datetime = TS,
) -> Foreshadowing:
    """构造测试伏笔。"""
    return Foreshadowing(
        id=fid,
        project_id=PID,
        title=title,
        description=description,
        status=status,
        location=location,
        created_at=created_at,
        updated_at=created_at,
    )


# ── 依赖装配（mock 7 repo，F15 _Deps 惯例）────────────────────────────


def _paged(items: list, page_size: int = 50):
    """构造分页 list Mock side_effect：按 offset 切片返回 (页, 总数)。"""

    async def _list(*args, **kwargs):
        offset = kwargs.get("offset", 0)
        return items[offset : offset + page_size], len(items)

    return _list


class _Deps:
    """测试用依赖集合 — 全部 Mock，可逐项覆盖后调用 service() 装配 ExportService。

    默认形态: 项目存在；无卷无章无设定；include_settings 分支默认不调用
    设定 repo（await_count=0）。
    """

    def __init__(
        self,
        project: Project | None = _project(),
        *,
        volumes: list[Volume] | None = None,
        chapters: list[Chapter] | None = None,
        characters: list[Character] | None = None,
        worlds: list[WorldSetting] | None = None,
        outlines: list[Outline] | None = None,
        points: list[PlotPoint] | None = None,
        events: list[TimelineEvent] | None = None,
        foreshadowings: list[Foreshadowing] | None = None,
    ) -> None:
        self.project_repo = MagicMock()
        self.project_repo.get = AsyncMock(return_value=project)
        self.chapter_repo = MagicMock()
        self.chapter_repo.list_volumes = AsyncMock(return_value=volumes or [])
        chapters = chapters or []
        self.chapter_repo.list_chapters = AsyncMock(return_value=(chapters, len(chapters)))
        self.character_repo = MagicMock()
        self.character_repo.list = AsyncMock(return_value=(characters or [], len(characters or [])))
        self.world_repo = MagicMock()
        self.world_repo.list = AsyncMock(return_value=(worlds or [], len(worlds or [])))
        self.outline_repo = MagicMock()
        self.outline_repo.list = AsyncMock(return_value=(outlines or [], len(outlines or [])))
        self.outline_repo.list_points = AsyncMock(return_value=points or [])
        self.timeline_repo = MagicMock()
        self.timeline_repo.list_all = AsyncMock(return_value=events or [])
        self.foreshadowing_repo = MagicMock()
        self.foreshadowing_repo.list = AsyncMock(
            return_value=(foreshadowings or [], len(foreshadowings or []))
        )

    def service(self) -> ExportService:
        """按 spec §8.2 构造签名装配导出服务（全部注入 Mock）。"""
        return ExportService(
            project_repo=self.project_repo,
            chapter_repo=self.chapter_repo,
            character_repo=self.character_repo,
            world_repo=self.world_repo,
            outline_repo=self.outline_repo,
            timeline_repo=self.timeline_repo,
            foreshadowing_repo=self.foreshadowing_repo,
        )


def _settings_by_type(doc, type_: str) -> list:
    """按 type 过滤 BookDocument.settings。"""
    return [s for s in doc.settings if s.type == type_]


# ── 项目校验（E1）────────────────────────────────────────────────────


async def test_export_project_not_found_raises():
    """project_repo.get → None → ProjectNotFoundError（§3.3 404 契约）。"""
    deps = _Deps(project=None)

    with pytest.raises(ProjectNotFoundError):
        await deps.service().export(PID)


async def test_export_project_id_converted_to_int_for_repo():
    """uuid.UUID → .int 传入 repo 层（F15 _to_int_id 契约）。"""
    deps = _Deps()

    await deps.service().export(PID)

    deps.project_repo.get.assert_awaited_once_with(PID.int)
    deps.chapter_repo.list_volumes.assert_awaited_once_with(PID.int)
    deps.chapter_repo.list_chapters.assert_awaited_once()


async def test_export_accepts_int_project_id():
    """int project_id 原样透传（不转换）。"""
    deps = _Deps()

    await deps.service().export(123)

    deps.project_repo.get.assert_awaited_once_with(123)
    deps.chapter_repo.list_volumes.assert_awaited_once_with(123)


# ── 正文聚合（§5.1 ②）───────────────────────────────────────────────


async def test_export_meta_mapping():
    """project 字段映射 BookMeta（title←name / genre / language / target_words / updated_at）。"""
    deps = _Deps(_project(name="星辰大海", genre=Genre.KEHUAN, target_words=500_000))

    doc = await deps.service().export(PID)

    assert doc.meta.title == "星辰大海"
    assert doc.meta.genre == "科幻"
    assert doc.meta.language == "zh-CN"
    assert doc.meta.target_words == 500_000
    assert doc.meta.updated_at == TS


async def test_export_aggregates_volumes_and_chapters():
    """卷/章聚合: 2 卷各 1 章 → BookVolume 树 + 字段映射（content/word_count/order_index）。"""
    v1 = _volume(uuid.uuid4(), "序章", 1.0)
    v2 = _volume(uuid.uuid4(), "终章", 2.0)
    ch1 = _chapter(
        uuid.uuid4(), "开端", volume_id=v1.id, order_index=1.0, content="正文甲", word_count=100
    )
    ch2 = _chapter(
        uuid.uuid4(), "结局", volume_id=v2.id, order_index=2.0, content="正文乙", word_count=200
    )
    deps = _Deps(volumes=[v1, v2], chapters=[ch1, ch2])

    doc = await deps.service().export(PID)

    assert len(doc.volumes) == 2
    assert doc.volumes[0].title == "序章"
    assert doc.volumes[0].chapters[0].title == "开端"
    assert doc.volumes[0].chapters[0].content == "正文甲"
    assert doc.volumes[0].chapters[0].word_count == 100
    assert doc.volumes[0].chapters[0].order_index == 1.0
    assert doc.volumes[1].chapters[0].title == "结局"


async def test_export_ungrouped_chapters_last():
    """volume_id=None 的章归「未分组」卷且排最后（M5/§6.1）。"""
    v1 = _volume(uuid.uuid4(), "序章", 1.0)
    named_ch = _chapter(uuid.uuid4(), "卷内章", volume_id=v1.id, order_index=1.0)
    orphan_ch = _chapter(uuid.uuid4(), "无卷章", volume_id=None, order_index=0.0)
    deps = _Deps(volumes=[v1], chapters=[named_ch, orphan_ch])

    doc = await deps.service().export(PID)

    assert [vol.title for vol in doc.volumes] == ["序章", UNGROUPED_TITLE]
    assert doc.volumes[-1].chapters[0].title == "无卷章"


async def test_export_ungrouped_only_single_volume():
    """全部章未分组 → 单个「未分组」卷（TXT 序列化折叠为「第 N 章」形态）。"""
    ch = _chapter(uuid.uuid4(), "第一章", volume_id=None, order_index=1.0)
    deps = _Deps(volumes=[], chapters=[ch])

    doc = await deps.service().export(PID)

    assert len(doc.volumes) == 1
    assert doc.volumes[0].title == UNGROUPED_TITLE
    assert doc.volumes[0].chapters[0].title == "第一章"


async def test_export_includes_all_chapters_no_soft_delete_filter():
    """v1.1 真删语义：无软删过滤，所有章节进入聚合（M4 契约反转）。"""
    live = _chapter(uuid.uuid4(), "存活章", volume_id=None, order_index=1.0)
    second = _chapter(uuid.uuid4(), "第二章", volume_id=None, order_index=2.0)
    deps = _Deps(volumes=[], chapters=[live, second])

    doc = await deps.service().export(PID)

    assert len(doc.volumes) == 1
    assert [c.title for c in doc.volumes[0].chapters] == ["存活章", "第二章"]


async def test_export_empty_project_no_volumes():
    """项目存在但无卷无章 → volumes=[] 不报错（E2）。"""
    deps = _Deps()

    doc = await deps.service().export(PID)

    assert doc.volumes == []
    assert doc.settings == []


# ── 排序键（§6.1）────────────────────────────────────────────────────


async def test_export_sorts_volumes_by_order_index():
    """卷按 order_index 升序（mock 返回乱序）。"""
    v_a = _volume(uuid.uuid4(), "卷乙", 2.0)
    v_b = _volume(uuid.uuid4(), "卷零", 0.0)
    v_c = _volume(uuid.uuid4(), "卷甲", 1.0)
    deps = _Deps(volumes=[v_a, v_b, v_c])

    doc = await deps.service().export(PID)

    assert [vol.title for vol in doc.volumes] == ["卷零", "卷甲", "卷乙"]


async def test_export_sorts_chapters_within_volume():
    """卷内章按 order_index 升序（mock 返回乱序）。"""
    v1 = _volume(uuid.uuid4(), "序章", 1.0)
    ch_a = _chapter(uuid.uuid4(), "章二", volume_id=v1.id, order_index=2.0)
    ch_b = _chapter(uuid.uuid4(), "章一", volume_id=v1.id, order_index=1.0)
    deps = _Deps(volumes=[v1], chapters=[ch_a, ch_b])

    doc = await deps.service().export(PID)

    assert [c.title for c in doc.volumes[0].chapters] == ["章一", "章二"]


async def test_export_sorts_characters_by_created_at_asc():
    """附录角色按 created_at 升序（§6.1 稳定 ASCII 键，不用 name 排序）。"""
    c_old = _char(uuid.uuid4(), "赵", created_at=TS_1)
    c_mid = _char(uuid.uuid4(), "钱", created_at=TS_2)
    c_new = _char(uuid.uuid4(), "孙", created_at=TS_3)
    deps = _Deps(characters=[c_new, c_old, c_mid])

    doc = await deps.service().export(PID, include_settings=True)

    assert [s.name for s in _settings_by_type(doc, "character")] == ["赵", "钱", "孙"]


async def test_export_sorts_timeline_by_narrative_position():
    """附录时间线按 narrative_position 升序（§6.1 叙事序）。"""
    e_1 = _event(uuid.uuid4(), "事件甲", narrative_position=3)
    e_2 = _event(uuid.uuid4(), "事件乙", narrative_position=1)
    e_3 = _event(uuid.uuid4(), "事件丙", narrative_position=2)
    deps = _Deps(events=[e_1, e_2, e_3])

    doc = await deps.service().export(PID, include_settings=True)

    assert [s.name for s in _settings_by_type(doc, "timeline")] == ["事件乙", "事件丙", "事件甲"]


async def test_export_sorts_outlines_by_sort_order():
    """附录大纲按 sort_order 升序（§6.1）。"""
    o_a = _outline(uuid.uuid4(), "大纲乙", sort_order=2)
    o_b = _outline(uuid.uuid4(), "大纲甲", sort_order=1)
    deps = _Deps(outlines=[o_a, o_b])

    doc = await deps.service().export(PID, include_settings=True)

    assert [s.name for s in _settings_by_type(doc, "outline")] == ["大纲甲", "大纲乙"]


async def test_export_sorts_world_and_foreshadowing_by_created_at():
    """世界观/伏笔按 created_at 升序（§6.1）。"""
    w_1 = _world(uuid.uuid4(), "条目乙", created_at=TS_2)
    w_2 = _world(uuid.uuid4(), "条目甲", created_at=TS_1)
    f_1 = _foreshadowing(uuid.uuid4(), "伏笔乙", created_at=TS_2)
    f_2 = _foreshadowing(uuid.uuid4(), "伏笔甲", created_at=TS_1)
    deps = _Deps(worlds=[w_1, w_2], foreshadowings=[f_1, f_2])

    doc = await deps.service().export(PID, include_settings=True)

    assert [s.name for s in _settings_by_type(doc, "world")] == ["条目甲", "条目乙"]
    assert [s.name for s in _settings_by_type(doc, "foreshadowing")] == ["伏笔甲", "伏笔乙"]


# ── include_settings 分支（M2/Q3=C）──────────────────────────────────


async def test_export_settings_empty_by_default():
    """include_settings=False（默认）→ settings=[] 且 5 个设定 repo 不被调用。"""
    deps = _Deps(characters=[_char(uuid.uuid4(), "李青焰")])

    doc = await deps.service().export(PID)

    assert doc.settings == []
    deps.character_repo.list.assert_not_awaited()
    deps.world_repo.list.assert_not_awaited()
    deps.outline_repo.list.assert_not_awaited()
    deps.timeline_repo.list_all.assert_not_awaited()
    deps.foreshadowing_repo.list.assert_not_awaited()


async def test_export_settings_true_aggregates_five_types():
    """include_settings=True → 5 类齐全且顺序固定

    （character→world→outline→timeline→foreshadowing，§5.1 ③）。
    """
    deps = _Deps(
        characters=[_char(uuid.uuid4(), "角色")],
        worlds=[_world(uuid.uuid4(), "世界")],
        outlines=[_outline(uuid.uuid4(), "大纲")],
        events=[_event(uuid.uuid4(), "时间线")],
        foreshadowings=[_foreshadowing(uuid.uuid4(), "伏笔")],
    )

    doc = await deps.service().export(PID, include_settings=True)

    assert [s.type for s in doc.settings] == SETTING_TYPE_ORDER
    assert [s.name for s in doc.settings] == ["角色", "世界", "大纲", "时间线", "伏笔"]
    # 条件依赖全部被调用（各一次——数据量 < 50 无分页）
    deps.character_repo.list.assert_awaited_once()
    deps.world_repo.list.assert_awaited_once()
    deps.outline_repo.list.assert_awaited_once()
    deps.timeline_repo.list_all.assert_awaited_once()
    deps.foreshadowing_repo.list.assert_awaited_once()


# ── 附录摘要拼接（§6.3）─────────────────────────────────────────────


async def test_export_character_summary_full_fields():
    """character 摘要: 性格/背景/目标 三行拼接（§6.3）。"""
    deps = _Deps(
        characters=[
            _char(uuid.uuid4(), "李青焰", personality="冷峻", background="孤儿", goals="复仇")
        ]
    )

    doc = await deps.service().export(PID, include_settings=True)

    s = _settings_by_type(doc, "character")[0]
    assert s.content == "性格：冷峻\n背景：孤儿\n目标：复仇"


async def test_export_character_summary_skips_empty_fields():
    """character 摘要空字段跳过（§6.3 注）。"""
    deps = _Deps(
        characters=[_char(uuid.uuid4(), "沈砚", personality="", background="世家子弟", goals="")]
    )

    doc = await deps.service().export(PID, include_settings=True)

    assert _settings_by_type(doc, "character")[0].content == "背景：世家子弟"


async def test_export_character_summary_all_empty_is_empty_string():
    """character 摘要全空字段 → 空串（不输出空行）。"""
    deps = _Deps(characters=[_char(uuid.uuid4(), "路人")])

    doc = await deps.service().export(PID, include_settings=True)

    assert _settings_by_type(doc, "character")[0].content == ""


async def test_export_world_summary_with_category():
    """world 摘要: {category}：{content}（category 非空）。"""
    deps = _Deps(worlds=[_world(uuid.uuid4(), "灵气复苏", category="设定", content="天地灵气回归")])

    doc = await deps.service().export(PID, include_settings=True)

    assert _settings_by_type(doc, "world")[0].content == "设定：天地灵气回归"


async def test_export_world_summary_without_category():
    """world 摘要: category 空 → 仅 {content}（§6.3「category 空则省略」）。"""
    deps = _Deps(worlds=[_world(uuid.uuid4(), "灵气复苏", category="", content="天地灵气回归")])

    doc = await deps.service().export(PID, include_settings=True)

    assert _settings_by_type(doc, "world")[0].content == "天地灵气回归"


async def test_export_outline_summary_with_points_sorted():
    """outline 摘要: description + 情节点列表（position 升序，§6.3）。"""
    oid = uuid.uuid4()
    outline = _outline(oid, "主线", description="主角成长")
    p_a = _point(uuid.uuid4(), oid, "开端", type_="开篇", description="主角登场", position=2)
    p_b = _point(uuid.uuid4(), oid, "转折", type_="转折", description="身世揭露", position=1)
    deps = _Deps(outlines=[outline], points=[p_a, p_b])

    doc = await deps.service().export(PID, include_settings=True)

    s = _settings_by_type(doc, "outline")[0]
    assert "主角成长" in s.content
    assert "- 转折（转折）: 身世揭露" in s.content
    assert "- 开端（开篇）: 主角登场" in s.content
    assert s.content.index("转折") < s.content.index("开端")  # position 升序


async def test_export_outline_summary_without_points():
    """outline 摘要: 无情节点 → 仅 description。"""
    deps = _Deps(outlines=[_outline(uuid.uuid4(), "主线", description="主角成长")])

    doc = await deps.service().export(PID, include_settings=True)

    assert _settings_by_type(doc, "outline")[0].content == "主角成长"


async def test_export_timeline_summary_with_time_display():
    """timeline 摘要: {time_display}｜{description}（§6.3）。"""
    deps = _Deps(
        events=[
            _event(uuid.uuid4(), "大战", time_display="青元历 317 年秋", description="两军对垒")
        ]
    )

    doc = await deps.service().export(PID, include_settings=True)

    assert _settings_by_type(doc, "timeline")[0].content == "青元历 317 年秋｜两军对垒"


async def test_export_timeline_summary_falls_back_to_title():
    """timeline 摘要: time_display 空 → 用 title。"""
    deps = _Deps(events=[_event(uuid.uuid4(), "大战", time_display="", description="两军对垒")])

    doc = await deps.service().export(PID, include_settings=True)

    assert _settings_by_type(doc, "timeline")[0].content == "大战｜两军对垒"


async def test_export_foreshadowing_summary_with_location():
    """foreshadowing 摘要: 状态：{status.value}｜{description}｜埋设：{location}（§6.3）。"""
    deps = _Deps(
        foreshadowings=[
            _foreshadowing(uuid.uuid4(), "林晚的身世", description="孤儿身世", location="第 3 章")
        ]
    )

    doc = await deps.service().export(PID, include_settings=True)

    content = _settings_by_type(doc, "foreshadowing")[0].content
    assert content == "状态：open｜孤儿身世｜埋设：第 3 章"


async def test_export_foreshadowing_summary_without_location():
    """foreshadowing 摘要: location 空 → 不追加「埋设：」。"""
    deps = _Deps(
        foreshadowings=[_foreshadowing(uuid.uuid4(), "林晚的身世", description="孤儿身世")]
    )

    doc = await deps.service().export(PID, include_settings=True)

    assert _settings_by_type(doc, "foreshadowing")[0].content == "状态：open｜孤儿身世"


# ── 循环分页（§5.2 / §9.2 场景 2，M1 兜底）───────────────────────────


async def test_export_pagination_loops_all_chapters():
    """list_chapters 50 条/页 + total=120 → 循环拉全 120 章（M1 分页兜底）。"""
    chapters = [
        _chapter(uuid.uuid4(), f"第{i}章", volume_id=None, order_index=float(i)) for i in range(120)
    ]
    deps = _Deps(volumes=[], chapters=[])
    deps.chapter_repo.list_chapters = AsyncMock(side_effect=_paged(chapters))

    doc = await deps.service().export(PID)

    total_chapters = sum(len(v.chapters) for v in doc.volumes)
    assert total_chapters == 120
    assert deps.chapter_repo.list_chapters.await_count == 3  # 50 + 50 + 20


async def test_export_character_pagination_loops_all():
    """character.list 50 条/页 + total=120 → 附录含全部 120 条角色（§8.2 同分页陷阱）。"""
    chars = [_char(uuid.uuid4(), f"角色{i}") for i in range(120)]
    deps = _Deps(characters=[])
    deps.character_repo.list = AsyncMock(side_effect=_paged(chars))

    doc = await deps.service().export(PID, include_settings=True)

    assert len(_settings_by_type(doc, "character")) == 120
    assert deps.character_repo.list.await_count == 3
