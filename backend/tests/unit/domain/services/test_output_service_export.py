"""F21 导出全管线集成测试 — mock 7 repo → 真实 ExportService → 真实 to_txt（RED 阶段）。

被测组合: ``inkflow.domain.services.output_service.ExportService.export`` →
``inkflow.domain.services._txt_exporter.to_txt``（§5.1 管线 ②-⑤）。

┌─ 契约（GREEN 实现者以此为准）──────────────────────────────────────────┐
│ 本文件不引入新契约——复用 test_output_service.py 的聚合契约与            │
│ test_txt_exporter.py 的序列化契约，验证二者串联（§9.1 集成形态）:       │
│ 1. 管线输出 = to_txt(await service.export(pid, include_settings))       │
│ 2. 完整项目（1 卷 2 章 + 5 类设定各 1 条）→ 文本非空，含书名/卷标题/    │
│    章标题/正文/附录标题/5 个分节标题                                    │
│ 3. include_settings=False → 文本不含「附录：设定档案」（M2 缺省不含）   │
│ 4. include_settings=True → 文本含「附录：设定档案」+ 5 个分节（M2/M6）  │
│ 5. 确定性: 同 fixture 两次导出文本逐字节相同（M3/§9.2 场景 1）          │
│ 6. 空项目（M6）→ 导出不报错，文本非空且含书名（§7 E4 标题+空正文）     │
└──────────────────────────────────────────────────────────────────────────┘

RED 预期（实现不存在，收集期失败属设计使然）:
    collected 0 items / 1 error
    ModuleNotFoundError: No module named 'inkflow.domain.services.output_service'
（顶部 import 缺失实现 → 收集期整文件 ModuleNotFoundError；GREEN 时
实现落地自动收集。import 顺序: output_service 首个 → 收集错误报告该
模块，models.output/_txt_exporter 缺失被其遮蔽。）

依据: specs/f21-export-service/spec.md §5.1/§7 E4/§9.2 场景 1+6/§13 M2/M3/M6。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from inkflow.domain.models.chapter import Chapter, Volume
from inkflow.domain.models.character import Character
from inkflow.domain.models.foreshadowing import Foreshadowing, ForeshadowingStatus
from inkflow.domain.models.outline import Outline, PlotPoint
from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.services._txt_exporter import to_txt
from inkflow.domain.services.output_service import ExportService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


# ── 实体构造 helpers（与 test_output_service.py 同形，文件独立）────────


def _project() -> Project:
    """构造项目「我的小说」。"""
    return Project(
        id=PID,
        name="我的小说",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100_000,
        created_at=TS,
        updated_at=TS,
    )


def _volume() -> Volume:
    """构造卷「第一卷：序章」。"""
    return Volume(id=uuid.uuid4(), project_id=PID, title="序章", order_index=1.0)


def _chapter(cid: uuid.UUID, title: str, volume_id: uuid.UUID, content: str) -> Chapter:
    """构造卷内章节。"""
    return Chapter(
        id=cid,
        project_id=PID,
        volume_id=volume_id,
        title=title,
        content=content,
        order_index=1.0,
        word_count=len(content),
        created_at=TS,
        updated_at=TS,
    )


def _char() -> Character:
    """构造角色「李青焰」。"""
    return Character(
        id=uuid.uuid4(),
        project_id=PID,
        name="李青焰",
        personality="冷峻",
        background="孤儿",
        goals="复仇",
        created_at=TS,
        updated_at=TS,
    )


def _world() -> WorldSetting:
    """构造世界观「灵气复苏」。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name="灵气复苏",
        category="设定",
        content="天地灵气回归",
        created_at=TS,
        updated_at=TS,
    )


def _outline() -> tuple[Outline, PlotPoint]:
    """构造大纲「主线」+ 情节点「开端」。"""
    oid = uuid.uuid4()
    outline = Outline(
        id=oid,
        project_id=PID,
        name="主线",
        description="主角成长",
        sort_order=1,
        created_at=TS,
        updated_at=TS,
    )
    point = PlotPoint(
        id=uuid.uuid4(),
        outline_id=oid,
        project_id=PID,
        name="开端",
        type="开篇",
        description="主角登场",
        position=1,
        created_at=TS,
        updated_at=TS,
    )
    return outline, point


def _event() -> TimelineEvent:
    """构造时间线事件「大战」。"""
    return TimelineEvent(
        id=uuid.uuid4(),
        project_id=PID,
        title="大战",
        description="两军对垒",
        time_display="青元历 317 年秋",
        narrative_position=1,
        created_at=TS,
        updated_at=TS,
    )


def _foreshadowing() -> Foreshadowing:
    """构造伏笔「林晚的身世」。"""
    return Foreshadowing(
        id=uuid.uuid4(),
        project_id=PID,
        title="林晚的身世",
        description="孤儿身世",
        status=ForeshadowingStatus.OPEN,
        location="第 3 章",
        created_at=TS,
        updated_at=TS,
    )


# ── 全管线 fixture ───────────────────────────────────────────────────


def _make_deps(project: Project | None = None) -> tuple[MagicMock, ...]:
    """装配完整项目 mock 依赖（1 卷 2 章 + 5 类设定各 1 条）。

    Returns:
        (project_repo, chapter_repo, character_repo, world_repo, outline_repo,
         timeline_repo, foreshadowing_repo) 元组，便于用例覆盖单 repo。
    """
    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=project if project is not None else _project())

    vol = _volume()
    chapter_repo = MagicMock()
    chapter_repo.list_volumes = AsyncMock(return_value=[vol])
    chapters = [
        _chapter(uuid.uuid4(), "开端", vol.id, "第一段。\n\n第二段。"),
        _chapter(uuid.uuid4(), "发展", vol.id, "第三段。"),
    ]
    chapter_repo.list_chapters = AsyncMock(return_value=(chapters, len(chapters)))

    outline, point = _outline()
    character_repo = MagicMock()
    character_repo.list = AsyncMock(return_value=([_char()], 1))
    world_repo = MagicMock()
    world_repo.list = AsyncMock(return_value=([_world()], 1))
    outline_repo = MagicMock()
    outline_repo.list = AsyncMock(return_value=([outline], 1))
    outline_repo.list_points = AsyncMock(return_value=[point])
    timeline_repo = MagicMock()
    timeline_repo.list_all = AsyncMock(return_value=[_event()])
    foreshadowing_repo = MagicMock()
    foreshadowing_repo.list = AsyncMock(return_value=([_foreshadowing()], 1))

    return (
        project_repo,
        chapter_repo,
        character_repo,
        world_repo,
        outline_repo,
        timeline_repo,
        foreshadowing_repo,
    )


def _service(repos: tuple[MagicMock, ...]) -> ExportService:
    """按 §8.2 构造签名装配真实 ExportService（7 repo 全 mock）。"""
    (
        project_repo,
        chapter_repo,
        character_repo,
        world_repo,
        outline_repo,
        timeline_repo,
        foreshadowing_repo,
    ) = repos
    return ExportService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        character_repo=character_repo,
        world_repo=world_repo,
        outline_repo=outline_repo,
        timeline_repo=timeline_repo,
        foreshadowing_repo=foreshadowing_repo,
    )


async def _export_txt(include_settings: bool = False) -> str:
    """全管线执行: export → to_txt（返回最终 TXT 文本）。"""
    doc = await _service(_make_deps()).export(PID, include_settings=include_settings)
    return to_txt(doc)


# ── 全管线用例 ───────────────────────────────────────────────────────


async def test_full_pipeline_produces_txt():
    """完整项目 → 文本非空 + 结构嗅探（书名/卷/章/正文/附录分节，§3.2 示例形态）。"""
    text = await _export_txt(include_settings=True)

    assert text
    assert text.splitlines()[0] == "我的小说"  # 首行书名
    assert "=" * 30 in text  # 书名分隔线
    assert "第 1 卷 序章" in text
    assert "-" * 30 in text  # 卷分隔线
    assert "第 1 章 开端" in text
    assert "第 2 章 发展" in text
    assert "第一段。\n\n第二段。" in text  # 正文原样含换行
    assert "附录：设定档案" in text
    for section in ("【角色】", "【世界观】", "【大纲】", "【时间线】", "【伏笔】"):
        assert section in text


async def test_full_pipeline_without_settings_no_appendix():
    """include_settings=False（默认）→ 正文结构完整但无「附录：设定档案」（M2）。"""
    text = await _export_txt(include_settings=False)

    assert text
    assert "第 1 章 开端" in text
    assert "附录：设定档案" not in text
    assert "【角色】" not in text


async def test_full_pipeline_with_settings_has_appendix():
    """include_settings=True → 附录标题 + 5 分节全部出现（M2）。"""
    text = await _export_txt(include_settings=True)

    assert "附录：设定档案" in text
    assert "【角色】" in text
    assert "【世界观】" in text
    assert "【大纲】" in text
    assert "【时间线】" in text
    assert "【伏笔】" in text
    # 附录条目内容（角色摘要 §6.3 拼接经全管线到达文本）
    assert "李青焰" in text
    assert "性格：冷峻\n背景：孤儿\n目标：复仇" in text


async def test_full_pipeline_deterministic():
    """同 fixture 两次全管线导出 → 文本逐字节相同（M3/§9.2 场景 1）。"""
    first = await _export_txt(include_settings=True)
    second = await _export_txt(include_settings=True)

    assert first == second
    assert first  # 非空


async def test_full_pipeline_empty_project():
    """空项目（E2/M6）→ 导出不报错，文本非空且含书名（标题 + 空正文，§7 E4）。"""
    (
        project_repo,
        chapter_repo,
        character_repo,
        world_repo,
        outline_repo,
        timeline_repo,
        foreshadowing_repo,
    ) = _make_deps()
    # 覆盖为空项目: 无卷无章无设定
    chapter_repo.list_volumes = AsyncMock(return_value=[])
    chapter_repo.list_chapters = AsyncMock(return_value=([], 0))
    character_repo.list = AsyncMock(return_value=([], 0))
    world_repo.list = AsyncMock(return_value=([], 0))
    outline_repo.list = AsyncMock(return_value=([], 0))
    timeline_repo.list_all = AsyncMock(return_value=[])
    foreshadowing_repo.list = AsyncMock(return_value=([], 0))
    service = ExportService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        character_repo=character_repo,
        world_repo=world_repo,
        outline_repo=outline_repo,
        timeline_repo=timeline_repo,
        foreshadowing_repo=foreshadowing_repo,
    )

    doc = await service.export(PID, include_settings=True)
    text = to_txt(doc)

    assert doc.volumes == []
    assert doc.settings == []
    assert text
    assert text.splitlines()[0] == "我的小说"
    assert "=" * 30 in text
