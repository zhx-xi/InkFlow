"""#955 F58 大纲域层级化工具矩阵 RED 契约测试 — outline_tools 注册 + 执行信封 + 层级语义.

依据统一契约 .hermes/plans/contract-955.md §0/§1/§2/§6/§8(RED-A 行)/§9（作者：spec 上位真相）。
镜像 test_chat_setting_write_tools.py / test_setting_update_tools.py 形态（MagicMock/AsyncMock 鸭子
deps，工具经 build_outline_tools(deps) 取得，调用 func 后 json.loads 断言信封）。

本文件锁定契约摘要:
1. build_outline_tools(deps) 返回 10 工具，名字集合与顺序 = §1 编号 1-10 序。
2. N2 schema：create_overall/volume/chapter_outline 与 update_volume/chapter_outline 的
   spec.input_schema properties 不含 level/parent_id/chapter_id/volume_id（update 含 outline_id）；
   create_chapter_outline 按名定位（volume_outline_name 必填，无 outline_id 参数）。
3. 父级名解析三态（§2）：唯一匹配 → create_outline 收 resolved uuid；无匹配 → error 逐字；
   歧义 → error 含候选 "名称(id=UUID)"（「、」连接）。
4. create_overall_outline 前置检查（已有整本根 → 不调服务）。
5. create_volume_outline 父整本根三态 + volume_name 解析（同名卷取 order_index 最小）。
6. create_plot_point outline_id/chapter_outline_name 恰一互斥 + arc 名解析 + 包装调用形状。
7. update_volume/chapter_outline 层级守卫互指文案 + OutlineUpdate 仅含非 None 字段。
8. update_plot_point arc_id="" 透传 PlotPointUpdate；字段 None 不进 DTO。
9. 读工具：list_outlines parent_chain/volume_title 形状、get_outline include_plot_points、
   list_plot_points arc_name 序列化 + 读工具不落审计守护。
10. 信封/审计形状：写工具成功 "<tool>_created|updated" / 失败 "<tool>_create_failed|update_failed"，
    actor="agent:chat"，expected_project_id 绑定（LLM 不自报项目 ID）。

【R】= GREEN 前必 FAIL（全部因 build_outline_tools / OutlineToolDeps 模块尚不存在——所有
Green 符号 import 均置于用例函数体内，防收集 ERROR 吞掉守护用例，故收集期不报错、运行期
以 ModuleNotFoundError 红）。
【G】= 现实现正确时可直接 PASS 的守护（读工具不落审计）。
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
FOREIGN_PROJECT_ID = "00000000-0000-0000-0000-000000000000"


# ─── 私有构造辅助（GREEN 新符号 import 一律函数体内，防收集 ERROR） ───


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


def _spec(deps: object, name: str) -> object:
    """取指定工具 spec（用于 schema 契约断言）。"""
    return _tools(deps)[name].spec


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


# ─── 覆盖清单 1：注册面 ───


def test_registers_ten_tools_in_contract_order() -> None:
    """【R】build_outline_tools 返回 10 工具，顺序 = §1 编号 1-10 序。"""
    names = [t.spec.name for t in _ordered_tools(_deps())]
    assert names == [
        "list_outlines",
        "get_outline",
        "list_plot_points",
        "create_overall_outline",
        "create_volume_outline",
        "create_chapter_outline",
        "update_volume_outline",
        "update_chapter_outline",
        "create_plot_point",
        "update_plot_point",
    ]
    assert len(names) == 10
    assert len(set(names)) == 10


def test_outline_tool_names_are_stable() -> None:
    """【R】名字集合固定（防别名/大小写漂移）。"""
    names = {t.spec.name for t in _ordered_tools(_deps())}
    assert names == {
        "list_outlines",
        "get_outline",
        "list_plot_points",
        "create_overall_outline",
        "create_volume_outline",
        "create_chapter_outline",
        "update_volume_outline",
        "update_chapter_outline",
        "create_plot_point",
        "update_plot_point",
    }


# ─── 覆盖清单 2：N2 schema 无层级字段 ───


def test_create_tool_schemas_exclude_hierarchy_fields() -> None:
    """【R】三个 create_*_outline 的 properties 无 level/parent_id/chapter_id/volume_id。"""
    deps = _deps()
    for name in ("create_overall_outline", "create_volume_outline", "create_chapter_outline"):
        props = _spec(deps, name).input_schema["properties"]
        assert "level" not in props
        assert "parent_id" not in props
        assert "chapter_id" not in props
        assert "volume_id" not in props
        assert "name" in props  # 至少保留名称字段


def test_update_tool_schemas_exclude_hierarchy_fields_but_include_outline_id() -> None:
    """【R】update_volume/chapter_outline 含 outline_id、无 level/parent_id 等层级字段。"""
    deps = _deps()
    for name in ("update_volume_outline", "update_chapter_outline"):
        props = _spec(deps, name).input_schema["properties"]
        assert "outline_id" in props
        assert "level" not in props
        assert "parent_id" not in props
        assert "chapter_id" not in props
        assert "volume_id" not in props


def test_create_chapter_outline_positions_by_volume_name_not_outline_id() -> None:
    """【R】create_chapter_outline 按名定位：volume_outline_name 必填、无 outline_id 参数。"""
    schema = _spec(_deps(), "create_chapter_outline").input_schema
    props = schema["properties"]
    assert "outline_id" not in props
    assert "volume_outline_name" in props
    assert "volume_outline_name" in schema["required"]


# ─── 覆盖清单 4：create_overall_outline ───


@pytest.mark.asyncio
async def test_create_overall_outline_rejects_existing_root() -> None:
    """【R】已有整本根 → ok False error 含既有根名与 id，前置检查不调 create_outline。"""
    deps = _deps()
    root = _outline(name="整本大纲", level="overall", id=uuid.UUID(int=1))
    deps.outline_service.list_outlines = AsyncMock(return_value=([root], 1))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=10))
    )
    tools = _tools(deps)
    result = json.loads(await tools["create_overall_outline"].func(name="另一本", description="d"))
    assert result["ok"] is False
    assert "整体大纲已存在" in result["error"]
    assert "整本大纲" in result["error"]  # 既存根名
    assert str(uuid.UUID(int=1)) in result["error"]  # 既存根 id
    deps.outline_service.create_outline.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_overall_outline_creates_root() -> None:
    """【R】无根 → create_outline kwargs level="overall"、parent_id=None。"""
    deps = _deps()
    deps.outline_service.list_outlines = AsyncMock(return_value=([], 0))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=10))
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["create_overall_outline"].func(name="整本大纲", description="d")
    )
    assert result["ok"] is True
    assert result["level"] == "overall"
    deps.outline_service.create_outline.assert_awaited_once()
    _args, kwargs = deps.outline_service.create_outline.call_args
    assert kwargs["level"] == "overall"
    assert kwargs["parent_id"] is None
    assert kwargs["name"] == "整本大纲"


# ─── 覆盖清单 5：create_volume_outline（父整本根三态 + volume_name 解析） ───


@pytest.mark.asyncio
async def test_create_volume_outline_uses_unique_overall_root() -> None:
    """【R】整本根恰一 → kwargs level="volume"、parent_id=根id；未传 volume_name → 不挂卷。"""
    deps = _deps()
    root = _outline(name="整本大纲", level="overall", id=uuid.UUID(int=1))
    deps.outline_service.list_outlines = AsyncMock(return_value=([root], 1))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=20))
    )
    tools = _tools(deps)
    result = json.loads(await tools["create_volume_outline"].func(name="第一卷", description="d"))
    assert result["ok"] is True
    deps.outline_service.create_outline.assert_awaited_once()
    _args, kwargs = deps.outline_service.create_outline.call_args
    assert kwargs["level"] == "volume"
    assert kwargs["parent_id"] == uuid.UUID(int=1)
    assert kwargs["volume_id"] is None


@pytest.mark.asyncio
async def test_create_volume_outline_no_root_error() -> None:
    """【R】无整本根 → error 逐字，且不调 create_outline。"""
    deps = _deps()
    deps.outline_service.list_outlines = AsyncMock(return_value=([], 0))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=20))
    )
    tools = _tools(deps)
    result = json.loads(await tools["create_volume_outline"].func(name="第一卷"))
    assert result["ok"] is False
    assert result["error"] == "未找到整体大纲（整本根），请先用 create_overall_outline 创建"
    deps.outline_service.create_outline.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_volume_outline_multi_root_overall_disambiguates() -> None:
    """【R】多整本根且 overall 恰一命中 → 用该根 id。"""
    deps = _deps()
    r1 = _outline(name="整本甲", level="overall", id=uuid.UUID(int=1))
    r2 = _outline(name="整本乙", level="overall", id=uuid.UUID(int=2))
    deps.outline_service.list_outlines = AsyncMock(return_value=([r1, r2], 2))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=20))
    )
    tools = _tools(deps)
    result = json.loads(await tools["create_volume_outline"].func(name="第一卷", overall="整本乙"))
    assert result["ok"] is True
    _args, kwargs = deps.outline_service.create_outline.call_args
    assert kwargs["parent_id"] == uuid.UUID(int=2)


@pytest.mark.asyncio
async def test_create_volume_outline_multi_root_overall_miss_report() -> None:
    """【R】多整本根且 overall 未命中 → error 逐字候选（「、」连接）。"""
    deps = _deps()
    r1 = _outline(name="整本甲", level="overall", id=uuid.UUID(int=1))
    r2 = _outline(name="整本乙", level="overall", id=uuid.UUID(int=2))
    deps.outline_service.list_outlines = AsyncMock(return_value=([r1, r2], 2))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=20))
    )
    tools = _tools(deps)
    result = json.loads(await tools["create_volume_outline"].func(name="第一卷", overall="整本丙"))
    assert result["ok"] is False
    expected = f"整本大纲名称「整本丙」未找到，候选：整本甲(id={r1.id!s})、整本乙(id={r2.id!s})"
    assert result["error"] == expected
    deps.outline_service.create_outline.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_volume_outline_multi_root_without_overall_report() -> None:
    """【R】多整本根且未传 overall → error 逐字候选（防御性异常数据文案）。"""
    deps = _deps()
    r1 = _outline(name="整本甲", level="overall", id=uuid.UUID(int=1))
    r2 = _outline(name="整本乙", level="overall", id=uuid.UUID(int=2))
    deps.outline_service.list_outlines = AsyncMock(return_value=([r1, r2], 2))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=20))
    )
    tools = _tools(deps)
    result = json.loads(await tools["create_volume_outline"].func(name="第一卷"))
    assert result["ok"] is False
    expected = (
        "存在多个整体大纲（防御性异常数据），请用 overall 参数指定；候选："
        f"整本甲(id={r1.id!s})、整本乙(id={r2.id!s})"
    )
    assert result["error"] == expected
    deps.outline_service.create_outline.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_volume_outline_ambiguous_volume_name_takes_min_order_index() -> None:
    """【R】volume_name 同名多卷（写作卷无唯一约束）→ 取 order_index 最小并照传 volume_id。"""
    deps = _deps()
    root = _outline(name="整本大纲", level="overall", id=uuid.UUID(int=1))
    deps.outline_service.list_outlines = AsyncMock(return_value=([root], 1))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=20))
    )
    vol_a = SimpleNamespace(id=uuid.UUID(int=101), title="第一卷", order_index=2.0)
    vol_b = SimpleNamespace(id=uuid.UUID(int=102), title="第一卷", order_index=1.0)
    deps.chapter_service.list_volumes = AsyncMock(return_value=[vol_a, vol_b])
    tools = _tools(deps)
    result = json.loads(
        await tools["create_volume_outline"].func(name="第一卷", volume_name="第一卷")
    )
    assert result["ok"] is True
    _args, kwargs = deps.outline_service.create_outline.call_args
    assert kwargs["volume_id"] == uuid.UUID(int=102)  # order_index 最小（1.0）


@pytest.mark.asyncio
async def test_create_volume_outline_volume_name_not_found() -> None:
    """【R】写作卷名未命中 → error 逐字「写作卷「X」未找到」。"""
    deps = _deps()
    root = _outline(name="整本大纲", level="overall", id=uuid.UUID(int=1))
    deps.outline_service.list_outlines = AsyncMock(return_value=([root], 1))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=20))
    )
    deps.chapter_service.list_volumes = AsyncMock(return_value=[])
    tools = _tools(deps)
    result = json.loads(
        await tools["create_volume_outline"].func(name="第一卷", volume_name="不存在的卷")
    )
    assert result["ok"] is False
    assert result["error"] == "写作卷「不存在的卷」未找到"


# ─── 覆盖清单 3/6：create_chapter_outline（父按名解析三态 + 按名定位） ───


@pytest.mark.asyncio
async def test_create_chapter_outline_unique_volume_parent() -> None:
    """【R】卷纲名唯一匹配 → create_outline level="chapter"、parent_id=解析出的 UUID。"""
    deps = _deps()
    vol = _outline(name="第一卷", level="volume", id=uuid.UUID(int=101))
    deps.outline_service.list_outlines = AsyncMock(return_value=([vol], 1))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=30))
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["create_chapter_outline"].func(name="第一章", volume_outline_name="第一卷")
    )
    assert result["ok"] is True
    deps.outline_service.create_outline.assert_awaited_once()
    _args, kwargs = deps.outline_service.create_outline.call_args
    assert kwargs["level"] == "chapter"
    assert kwargs["parent_id"] == uuid.UUID(int=101)


@pytest.mark.asyncio
async def test_create_chapter_outline_no_volume_match_error() -> None:
    """【R】卷纲名无匹配 → error 逐字，且不调 create_outline。"""
    deps = _deps()
    deps.outline_service.list_outlines = AsyncMock(return_value=([], 0))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=30))
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["create_chapter_outline"].func(name="第一章", volume_outline_name="不存在卷纲")
    )
    assert result["ok"] is False
    assert (
        result["error"] == "卷大纲「不存在卷纲」不存在，请先创建卷大纲或用 list_outlines 确认名称"
    )
    deps.outline_service.create_outline.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_chapter_outline_ambiguous_volume_error() -> None:
    """【R】卷纲名歧义（两条同名 level=volume 防御数据）→ error 含两条候选「名称(id=UUID)」。"""
    deps = _deps()
    v1 = _outline(name="第一卷", level="volume", id=uuid.UUID(int=101))
    v2 = _outline(name="第一卷", level="volume", id=uuid.UUID(int=102))
    deps.outline_service.list_outlines = AsyncMock(return_value=([v1, v2], 2))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=30))
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["create_chapter_outline"].func(name="第一章", volume_outline_name="第一卷")
    )
    assert result["ok"] is False
    assert "卷大纲「第一卷」存在多个同名条目（异常数据）" in result["error"]
    assert f"第一卷(id={v1.id!s})" in result["error"]
    assert f"第一卷(id={v2.id!s})" in result["error"]


# ─── 覆盖清单 7：update_volume_outline / update_chapter_outline ───


@pytest.mark.asyncio
async def test_update_volume_outline_level_guard() -> None:
    """【R】目标层级为 chapter 用卷更新工具 → error 互指文案，不调 update_outline。"""
    deps = _deps()
    ch = _outline(name="第一章", level="chapter", id=uuid.UUID(int=30))
    deps.outline_service.get_outline = AsyncMock(return_value=ch)
    deps.outline_service.update_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=30), name="改")
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["update_volume_outline"].func(outline_id=str(uuid.UUID(int=30)), name="改")
    )
    assert result["ok"] is False
    assert result["error"] == "目标大纲层级为「chapter」，不是卷大纲，请改用 update_chapter_outline"
    deps.outline_service.update_outline.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_chapter_outline_level_guard() -> None:
    """【R】目标层级为 volume 用章更新工具 → error 互指文案，不调 update_outline。"""
    deps = _deps()
    vol = _outline(name="第一卷", level="volume", id=uuid.UUID(int=101))
    deps.outline_service.get_outline = AsyncMock(return_value=vol)
    deps.outline_service.update_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=101), name="改")
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["update_chapter_outline"].func(outline_id=str(uuid.UUID(int=101)), name="改")
    )
    assert result["ok"] is False
    assert result["error"] == "目标大纲层级为「volume」，不是章大纲，请改用 update_volume_outline"
    deps.outline_service.update_outline.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_volume_outline_not_found() -> None:
    """【R】get_outline 返回 None → error「大纲条目不存在」。"""
    deps = _deps()
    deps.outline_service.get_outline = AsyncMock(return_value=None)
    deps.outline_service.update_outline = AsyncMock(return_value=None)
    tools = _tools(deps)
    result = json.loads(
        await tools["update_volume_outline"].func(outline_id=str(uuid.UUID(int=30)), name="改")
    )
    assert result["ok"] is False
    assert result["error"] == "大纲条目不存在"


@pytest.mark.asyncio
async def test_update_volume_outline_passes_outline_update_with_set_fields() -> None:
    """【R】正常更新 → OutlineUpdate 仅含传入非 None 字段（第 2 参 model_fields_set）。"""
    deps = _deps()
    vol = _outline(name="第一卷", level="volume", id=uuid.UUID(int=101))
    deps.outline_service.get_outline = AsyncMock(return_value=vol)
    deps.outline_service.update_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=101), name="改")
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["update_volume_outline"].func(
            outline_id=str(uuid.UUID(int=101)), name="改", sort_order=None
        )
    )
    assert result["ok"] is True
    deps.outline_service.update_outline.assert_awaited_once()
    call = deps.outline_service.update_outline.call_args
    args, kwargs = call
    coerced_id = kwargs.get("outline_id") if kwargs else (args[0] if args else None)
    update = kwargs.get("update") if kwargs else (args[1] if len(args) > 1 else None)
    assert str(coerced_id) == str(uuid.UUID(int=101))
    assert update.model_fields_set == {"name"}  # sort_order=None 被过滤，未进 DTO


@pytest.mark.asyncio
async def test_update_chapter_outline_service_none_not_found() -> None:
    """【R】update_outline 服务返回 None → _require_found 语义「大纲条目不存在」。"""
    deps = _deps()
    ch = _outline(name="第一章", level="chapter", id=uuid.UUID(int=30))
    deps.outline_service.get_outline = AsyncMock(return_value=ch)
    deps.outline_service.update_outline = AsyncMock(return_value=None)
    tools = _tools(deps)
    result = json.loads(
        await tools["update_chapter_outline"].func(outline_id=str(uuid.UUID(int=30)), name="改")
    )
    assert result["ok"] is False
    assert result["error"] == "大纲条目不存在"


# ─── 覆盖清单 8/9：create_plot_point（Mutual-exclusion + arc 名解析 + 包装调用形状） ───


@pytest.mark.asyncio
async def test_create_plot_point_by_outline_id_passes_position_none() -> None:
    """【R】outline_id 定位 → create_point 收 position=None、arc_id=None 透传。"""
    deps = _deps()
    deps.outline_service.create_point = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid.UUID(int=40), name="高潮", outline_id=uuid.UUID(int=30), position=3
        )
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["create_plot_point"].func(outline_id=str(uuid.UUID(int=30)), name="高潮")
    )
    assert result["ok"] is True
    deps.outline_service.create_point.assert_awaited_once()
    _args, kwargs = deps.outline_service.create_point.call_args
    assert str(kwargs["outline_id"]) == str(uuid.UUID(int=30))
    assert kwargs["name"] == "高潮"
    assert kwargs["position"] is None
    assert kwargs["arc_id"] is None


@pytest.mark.asyncio
async def test_create_plot_point_mutex_both_provided() -> None:
    """【R】outline_id 与 chapter_outline_name 都给 → error 互斥逐字，不调 create_point。"""
    deps = _deps()
    deps.outline_service.create_point = AsyncMock()
    tools = _tools(deps)
    result = json.loads(
        await tools["create_plot_point"].func(
            outline_id=str(uuid.UUID(int=30)), chapter_outline_name="第一章", name="高潮"
        )
    )
    assert result["ok"] is False
    assert result["error"] == "outline_id 与 chapter_outline_name 必须恰好提供一个"
    deps.outline_service.create_point.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_plot_point_mutex_neither_provided() -> None:
    """【R】outline_id 与 chapter_outline_name 都缺 → error 互斥逐字，不调 create_point。"""
    deps = _deps()
    deps.outline_service.create_point = AsyncMock()
    tools = _tools(deps)
    result = json.loads(await tools["create_plot_point"].func(name="高潮"))
    assert result["ok"] is False
    assert result["error"] == "outline_id 与 chapter_outline_name 必须恰好提供一个"
    deps.outline_service.create_point.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_plot_point_by_chapter_name_resolves_outline() -> None:
    """【R】章纲名唯一匹配 → create_point 收解析出的 outline_id（任意层级按名匹配）。"""
    deps = _deps()
    ch = _outline(name="第一章", level="chapter", id=uuid.UUID(int=30))
    deps.outline_service.list_outlines = AsyncMock(return_value=([ch], 1))
    deps.outline_service.create_point = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid.UUID(int=40), name="高潮", outline_id=uuid.UUID(int=30), position=3
        )
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["create_plot_point"].func(chapter_outline_name="第一章", name="高潮")
    )
    assert result["ok"] is True
    _args, kwargs = deps.outline_service.create_point.call_args
    assert str(kwargs["outline_id"]) == str(uuid.UUID(int=30))


@pytest.mark.asyncio
async def test_create_plot_point_chapter_name_not_found() -> None:
    """【R】章纲名无匹配 → error 逐字「大纲「X」不存在，请先创建或用 list_outlines 确认名称」。"""
    deps = _deps()
    deps.outline_service.list_outlines = AsyncMock(return_value=([], 0))
    deps.outline_service.create_point = AsyncMock()
    tools = _tools(deps)
    result = json.loads(
        await tools["create_plot_point"].func(chapter_outline_name="不存在", name="高潮")
    )
    assert result["ok"] is False
    assert result["error"] == "大纲「不存在」不存在，请先创建或用 list_outlines 确认名称"


@pytest.mark.asyncio
async def test_create_plot_point_by_name_ambiguous_reports_candidates() -> None:
    """【R】章纲名歧义 → error 含「存在多个同名条目（异常数据）」与两条候选。"""
    deps = _deps()
    v1 = _outline(name="第一卷", level="volume", id=uuid.UUID(int=101))
    v2 = _outline(name="第一卷", level="chapter", id=uuid.UUID(int=102))
    deps.outline_service.list_outlines = AsyncMock(return_value=([v1, v2], 2))
    deps.outline_service.create_point = AsyncMock()
    tools = _tools(deps)
    result = json.loads(
        await tools["create_plot_point"].func(chapter_outline_name="第一卷", name="高潮")
    )
    assert result["ok"] is False
    assert "存在多个同名条目（异常数据）" in result["error"]
    assert f"第一卷(id={v1.id!s})" in result["error"]
    assert f"第一卷(id={v2.id!s})" in result["error"]


@pytest.mark.asyncio
async def test_create_plot_point_resolves_arc_name() -> None:
    """【R】arc 名解析命中 → create_point arc_id=UUID 透传服务。"""
    deps = _deps()
    deps.outline_service.create_point = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid.UUID(int=40), name="高潮", outline_id=uuid.UUID(int=30), position=3
        )
    )
    deps.outline_service.list_arcs = AsyncMock(
        return_value=[_arc(id=uuid.UUID(int=50), name="主线弧")]
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["create_plot_point"].func(
            outline_id=str(uuid.UUID(int=30)), name="高潮", arc="主线弧"
        )
    )
    assert result["ok"] is True
    _args, kwargs = deps.outline_service.create_point.call_args
    assert kwargs["arc_id"] == uuid.UUID(int=50)


@pytest.mark.asyncio
async def test_create_plot_point_arc_not_found() -> None:
    """【R】arc 名未命中 → error 逐字「故事弧线「X」不存在」。"""
    deps = _deps()
    deps.outline_service.create_point = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid.UUID(int=40), name="高潮", outline_id=uuid.UUID(int=30), position=3
        )
    )
    deps.outline_service.list_arcs = AsyncMock(return_value=[])
    tools = _tools(deps)
    result = json.loads(
        await tools["create_plot_point"].func(
            outline_id=str(uuid.UUID(int=30)), name="高潮", arc="不存在弧"
        )
    )
    assert result["ok"] is False
    assert result["error"] == "故事弧线「不存在弧」不存在"


# ─── 覆盖清单 9/8：update_plot_point（arc_id 透传 + 字段过滤） ───


@pytest.mark.asyncio
async def test_update_plot_point_arc_id_empty_passthrough() -> None:
    """【R】arc_id="" 透传 PlotPointUpdate（模型构造断言 arc_id == ""，工具不强转 UUID）。"""
    deps = _deps()
    deps.outline_service.update_point = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=60), name="改")
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["update_plot_point"].func(plot_point_id=str(uuid.UUID(int=60)), arc_id="")
    )
    assert result["ok"] is True
    deps.outline_service.update_point.assert_awaited_once()
    args, kwargs = deps.outline_service.update_point.call_args
    update = kwargs.get("update") if kwargs else (args[1] if len(args) > 1 else None)
    assert "arc_id" in update.model_fields_set
    assert update.arc_id == ""


@pytest.mark.asyncio
async def test_update_plot_point_only_non_none_fields_in_dto() -> None:
    """【R】字段 None 不进 PlotPointUpdate（model_fields_set 仅含传入非 None 字段）。"""
    deps = _deps()
    deps.outline_service.update_point = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=60), name="改")
    )
    tools = _tools(deps)
    result = json.loads(
        await tools["update_plot_point"].func(
            plot_point_id=str(uuid.UUID(int=60)), name="改", description=None, position=None
        )
    )
    assert result["ok"] is True
    args, kwargs = deps.outline_service.update_point.call_args
    update = kwargs.get("update") if kwargs else (args[1] if len(args) > 1 else None)
    assert "name" in update.model_fields_set
    assert "description" not in update.model_fields_set
    assert "position" not in update.model_fields_set


@pytest.mark.asyncio
async def test_update_plot_point_service_none() -> None:
    """【R】update_point 服务返回 None → error「情节点不存在」。"""
    deps = _deps()
    deps.outline_service.update_point = AsyncMock(return_value=None)
    tools = _tools(deps)
    result = json.loads(
        await tools["update_plot_point"].func(plot_point_id=str(uuid.UUID(int=60)), name="改")
    )
    assert result["ok"] is False
    assert result["error"] == "情节点不存在"


# ─── 覆盖清单 11：信封/审计形状 + expected_project_id 绑定 ───


@pytest.mark.asyncio
async def test_create_audit_severity_summary_created() -> None:
    """【R】写工具成功审计 severity_summary="<tool>_created"、actor="agent:chat"。"""
    deps = _deps()
    vol = _outline(name="第一卷", level="volume", id=uuid.UUID(int=101))
    deps.outline_service.list_outlines = AsyncMock(return_value=([vol], 1))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=30))
    )
    tools = _tools(deps)
    await tools["create_chapter_outline"].func(name="第一章", volume_outline_name="第一卷")
    deps.audit_service.record.assert_awaited_once()
    _args, kwargs = deps.audit_service.record.call_args
    assert kwargs["severity_summary"] == "create_chapter_outline_created"
    assert kwargs["actor"] == "agent:chat"


@pytest.mark.asyncio
async def test_update_audit_severity_summary_updated() -> None:
    """【R】更新工具成功审计 severity_summary="<tool>_updated"、actor="agent:chat"。"""
    deps = _deps()
    vol = _outline(name="第一卷", level="volume", id=uuid.UUID(int=101))
    deps.outline_service.get_outline = AsyncMock(return_value=vol)
    deps.outline_service.update_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=101), name="改")
    )
    tools = _tools(deps)
    await tools["update_volume_outline"].func(outline_id=str(uuid.UUID(int=101)), name="改")
    deps.audit_service.record.assert_awaited_once()
    _args, kwargs = deps.audit_service.record.call_args
    assert kwargs["severity_summary"] == "update_volume_outline_updated"
    assert kwargs["actor"] == "agent:chat"


@pytest.mark.asyncio
async def test_create_failure_audit_severity_summary_failed() -> None:
    """【R】写工具失败审计 severity_summary="<tool>_create_failed"。"""
    deps = _deps()
    vol = _outline(name="第一卷", level="volume", id=uuid.UUID(int=101))
    deps.outline_service.list_outlines = AsyncMock(return_value=([vol], 1))
    deps.outline_service.create_outline = AsyncMock(side_effect=ValueError("同名大纲已存在"))
    tools = _tools(deps)
    await tools["create_chapter_outline"].func(name="第一章", volume_outline_name="第一卷")
    deps.audit_service.record.assert_awaited_once()
    _args, kwargs = deps.audit_service.record.call_args
    assert kwargs["severity_summary"] == "create_chapter_outline_create_failed"


@pytest.mark.asyncio
async def test_write_tools_bind_expected_project_id() -> None:
    """【R】expected_project_id 绑定：caller 传入的 project_id 被忽略，恒用绑定值。"""
    deps = _deps()
    deps.outline_service.list_outlines = AsyncMock(return_value=([], 0))
    deps.outline_service.create_outline = AsyncMock(
        return_value=SimpleNamespace(id=uuid.UUID(int=10))
    )
    tools = _tools(deps)
    await tools["create_overall_outline"].func(
        name="整本大纲", project_id=FOREIGN_PROJECT_ID, description="d"
    )
    _args, kwargs = deps.outline_service.create_outline.call_args
    assert kwargs["project_id"] == PROJECT_ID
