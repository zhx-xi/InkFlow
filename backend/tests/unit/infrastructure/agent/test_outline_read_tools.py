"""F58 #955 RED-A（读工具分册）— outline_tools 三读工具契约测试。

被测模块（GREEN 才有）：inkflow.infrastructure.agent.tools.outline_tools
（OutlineToolDeps / build_outline_tools / list_outlines / get_outline / list_plot_points）。
GREEN 新符号 import 一律函数体内（防收集 ERROR 吞掉守护用例）。

契约：contract-955 §1（工具 1-3）/ §1.8 / §6 / §9。本文件自
test_outline_tools.py 拆出（#955 父侧拆分，monster-file 900 行护栏），
断言逐字未动。全部用例【R】（GREEN 前必红，ModuleNotFoundError 形态），
唯一【G】语义守护 = test_read_tools_do_not_record_audit（读工具不落审计，
依赖 build_outline_tools 存在故现亦红）。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# project_id 用小值 UUID（防 SQLite 溢出，硬条款④）。
PROJECT_ID = uuid.UUID(int=42)


# ─── 私有构造辅助（与 test_outline_tools.py 同源复制，GREEN 符号 import 函数体内） ───


def _now() -> datetime:
    """当前 UTC 时区感知时间（Outline/PlotPoint 必填字段用）。"""
    return datetime.now(UTC)


def _deps(**overrides: object) -> object:
    """构造 OutlineToolDeps（真 dataclass）或当模块缺失时体 import 抛错。

    鸭子兜底：outline_service/chapter_service 为 MagicMock，audit_service.record 为 AsyncMock。
    OutlineToolDeps 尚不存在时本函数体 import 即抛 ModuleNotFoundError（预期 RED 形态）。
    """
    from inkflow.infrastructure.agent.tools.outline_tools import OutlineToolDeps

    audit = MagicMock()
    audit.record = AsyncMock(return_value=None)
    deps = OutlineToolDeps(
        outline_service=MagicMock(),
        chapter_service=MagicMock(),
        audit_service=audit,
        expected_project_id=PROJECT_ID,
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


def _ordered_tools(deps: object) -> list[object]:
    """按 §1 编号序返回 build_outline_tools 全部 Tool（体 import，防收集 ERROR）。"""
    from inkflow.infrastructure.agent.tools.outline_tools import build_outline_tools

    return list(build_outline_tools(deps))


def _tools(deps: object) -> dict[str, object]:
    """以 {spec.name: Tool} 构建工具名→工具映射（体 import，防收集 ERROR）。"""
    return {t.spec.name: t for t in _ordered_tools(deps)}


def _outline(**overrides: object) -> object:
    """构造真实 Outline 领域实体（去 name 校验后的最小字段集）。"""
    from inkflow.domain.models.outline import Outline

    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        name="",
        description="",
        sort_order=0,
        level="chapter",
        parent_id=None,
        chapter_id=None,
        volume_id=None,
        extra={},
        created_at=_now(),
        updated_at=_now(),
    )
    defaults.update(overrides)
    return Outline(**defaults)  # type: ignore[arg-type]  # 鸭子：字段按契约动态提供，Pydantic 校验


def _point(**overrides: object) -> object:
    """构造真实 PlotPoint 领域实体。"""
    from inkflow.domain.models.outline import PlotPoint

    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        outline_id=uuid.uuid4(),
        project_id=PROJECT_ID,
        name="",
        type="",
        description="",
        position=0,
        arc_id=None,
        extra={},
        created_at=_now(),
        updated_at=_now(),
    )
    defaults.update(overrides)
    return PlotPoint(**defaults)  # type: ignore[arg-type]  # 鸭子：字段按契约动态提供，Pydantic 校验


def _arc(**overrides: object) -> object:
    """构造真实 StoryArc 领域实体（get_arc/list_arcs 返回项）。"""
    from inkflow.domain.models.outline import StoryArc

    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        name="",
        description="",
        created_at=_now(),
        updated_at=_now(),
    )
    defaults.update(overrides)
    return StoryArc(**defaults)  # type: ignore[arg-type]  # 鸭子：字段按契约动态提供，Pydantic 校验


# ─── 覆盖清单 10：读工具（list_outlines / get_outline / list_plot_points） ───


@pytest.mark.asyncio
async def test_list_outlines_builds_parent_chain_and_volume_title() -> None:
    """【R】list_outlines：level 过滤 + parent_chain（volume→overall 单链）+ volume_title 解析。"""
    deps = _deps()
    overall = _outline(name="整本大纲", level="overall", id=uuid.UUID(int=1))
    volume_id = uuid.UUID(int=200)
    volume = _outline(
        name="第一卷",
        level="volume",
        id=uuid.UUID(int=101),
        parent_id=overall.id,
        volume_id=volume_id,
    )
    deps.outline_service.list_outlines = AsyncMock(return_value=([volume, overall], 2))
    deps.chapter_service.get_volume = AsyncMock(
        return_value=SimpleNamespace(id=volume_id, title="第一卷")
    )
    tools = _tools(deps)
    result = json.loads(await tools["list_outlines"].func(level="volume"))
    assert result["ok"] is True
    assert len(result["data"]) == 1
    item = result["data"][0]
    assert {
        "id",
        "name",
        "level",
        "sort_order",
        "parent_chain",
        "volume_id",
        "volume_title",
    } <= set(item)
    assert item["name"] == "第一卷"
    assert item["level"] == "volume"
    assert item["volume_title"] == "第一卷"
    # parent_chain：volume 的父（overall）→ 唯一根，单链（仅锁 id/name/level 关系）
    chain = item["parent_chain"]
    assert len(chain) == 1
    assert chain[0]["id"] == str(overall.id)
    assert chain[0]["name"] == "整本大纲"
    assert chain[0]["level"] == "overall"


@pytest.mark.asyncio
async def test_list_outlines_volume_title_none_on_miss() -> None:
    """【R】get_volume 未命中 → volume_title=None，读操作不报错。"""
    deps = _deps()
    overall = _outline(name="整本大纲", level="overall", id=uuid.UUID(int=1))
    volume_id = uuid.UUID(int=200)
    volume = _outline(
        name="第一卷",
        level="volume",
        id=uuid.UUID(int=101),
        parent_id=overall.id,
        volume_id=volume_id,
    )
    deps.outline_service.list_outlines = AsyncMock(return_value=([volume, overall], 2))
    deps.chapter_service.get_volume = AsyncMock(return_value=None)
    tools = _tools(deps)
    result = json.loads(await tools["list_outlines"].func(level="volume"))
    assert result["ok"] is True
    item = result["data"][0]
    assert item["volume_title"] is None


@pytest.mark.asyncio
async def test_get_outline_not_found() -> None:
    """【R】get_outline 不存在 → error「大纲条目不存在」。"""
    deps = _deps()
    deps.outline_service.get_outline = AsyncMock(return_value=None)
    tools = _tools(deps)
    result = json.loads(await tools["get_outline"].func(outline_id=str(uuid.UUID(int=30))))
    assert result["ok"] is False
    assert result["error"] == "大纲条目不存在"


@pytest.mark.asyncio
async def test_get_outline_include_plot_points_with_arc_name() -> None:
    """【R】include_plot_points=True → plot_points 含 arc_name。"""
    deps = _deps()
    ch = _outline(name="第一章", level="chapter", id=uuid.UUID(int=30))
    point = _point(name="高潮", outline_id=ch.id, arc_id=uuid.UUID(int=50), position=1)
    deps.outline_service.get_outline = AsyncMock(return_value=ch)
    deps.outline_service.list_points = AsyncMock(return_value=[point])
    deps.outline_service.get_arc = AsyncMock(return_value=_arc(id=uuid.UUID(int=50), name="主线弧"))
    tools = _tools(deps)
    result = json.loads(
        await tools["get_outline"].func(outline_id=str(ch.id), include_plot_points=True)
    )
    assert result["ok"] is True
    assert "plot_points" in result["data"]
    matched = [p for p in result["data"]["plot_points"] if p["name"] == "高潮"]
    assert matched and matched[0]["arc_name"] == "主线弧"


@pytest.mark.asyncio
async def test_list_plot_points_resolves_arc_names_and_preserves_order() -> None:
    """【R】list_plot_points：arc_name 解析（get_arc 按 unique 缓存）+ position 透传序。"""
    deps = _deps()
    arc_50 = uuid.UUID(int=50)
    arc_51 = uuid.UUID(int=51)
    p1 = _point(name="起点", outline_id=uuid.UUID(int=30), arc_id=arc_50, position=1)
    p2 = _point(name="转折", outline_id=uuid.UUID(int=30), arc_id=None, position=2)
    p3 = _point(name="终局", outline_id=uuid.UUID(int=30), arc_id=arc_51, position=3)
    # 第 4 点与 p1 复挂同一弧线（arc_50）→ 缓存下 get_arc 只应查一次 50
    p4 = _point(name="尾声", outline_id=uuid.UUID(int=30), arc_id=arc_50, position=4)
    deps.outline_service.list_points = AsyncMock(return_value=[p1, p2, p3, p4])
    arc_names = {50: "主线弧", 51: "支线弧"}

    def _arc_by_id(aid: object) -> object:
        key = aid.int if isinstance(aid, uuid.UUID) else int(aid)
        return _arc(id=uuid.UUID(int=key), name=arc_names[key])

    deps.outline_service.get_arc = AsyncMock(side_effect=_arc_by_id)
    tools = _tools(deps)
    result = json.loads(await tools["list_plot_points"].func(outline_id=str(uuid.UUID(int=30))))
    assert result["ok"] is True
    data = result["data"]
    assert {
        "id",
        "outline_id",
        "name",
        "type",
        "description",
        "position",
        "arc_id",
        "arc_name",
    } <= set(data[0])
    assert [p["position"] for p in data] == [1, 2, 3, 4]  # 服务已保证升序，工具透传
    assert data[0]["arc_name"] == "主线弧"
    assert data[1]["arc_name"] is None
    assert data[2]["arc_name"] == "支线弧"
    assert data[3]["arc_name"] == "主线弧"
    # §1.8 局部 dict 缓存：弧线仅按 unique arc_id 解析一次（arc_50 出现两次只查一次 + arc_51 一次）
    assert deps.outline_service.get_arc.await_count == 2


# ─── 覆盖清单 11（读侧）：审计豁免守护 ───


@pytest.mark.asyncio
async def test_read_tools_do_not_record_audit() -> None:
    """【G】读工具不落审计（镜像 reader_tools）——audit_service.record assert_not_awaited。"""
    deps = _deps()
    deps.outline_service.list_points = AsyncMock(return_value=[])
    tools = _tools(deps)
    await tools["list_plot_points"].func(outline_id=str(uuid.UUID(int=30)))
    deps.audit_service.record.assert_not_awaited()
