"""#955 后续 coverage 缺口补测 — outline_tools 分支 + registry 物化组（非 RED）。

背景：CI coverage-backend（PR #971）branch 94.95% < 95.0%，主缺口为本批新模块
outline_tools.py（miss 37 / BrPart 17），次缺口 registry._build_all_tools 9 组
`is not None` 仅 delete 组 False 侧被 #954 既有测试覆盖。全部经公开接口
（build_outline_tools 返回的 func / build_tools_by_grants）触达真实分支，断言
编码契约行为（contract-955 §1/§2/§6），无凑数 smoke、无私有方法直调。

行号锚点（@f55695d）：57/60-61 _coerce_id；104-105 弧线歧义；138-139 防环 break；
143-145/157-161 _resolve_outline_by_id 兜底四形态；183-186 get_arc 防御；
397-402 _bind_project_id caller 回退；443-452 volume_title 分支；467-468/494-495/
508-509 异常 _fail 信封；488-493 include_plot_points=False；707-712/827-831
可选字段组合；registry 312-332 九组 False 分支。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from inkflow.domain.models.outline import Outline, PlotPoint
from inkflow.infrastructure.agent.tools import UnifiedToolDeps, build_tools_by_grants
from inkflow.infrastructure.agent.tools.outline_tools import (
    OutlineToolDeps,
    build_outline_tools,
)

PROJECT_ID = uuid.UUID(int=42)
VOL_ID = uuid.UUID(int=101)
ROOT_ID = uuid.UUID(int=1)
ARC_ID = uuid.UUID(int=50)


def _now() -> object:
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _outline(**overrides: object) -> Outline:
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
    return Outline(**defaults)  # type: ignore[arg-type]  # 鸭子：字段按契约动态提供


def _point(**overrides: object) -> PlotPoint:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        outline_id=uuid.UUID(int=30),
        project_id=PROJECT_ID,
        name="高潮",
        type="",
        description="",
        position=1,
        arc_id=ARC_ID,
        extra={},
        created_at=_now(),
        updated_at=_now(),
    )
    defaults.update(overrides)
    return PlotPoint(**defaults)  # type: ignore[arg-type]  # 鸭子：字段按契约动态提供


def _deps(
    *,
    outline_service: object | None = None,
    chapter_service: object | None = None,
    expected: uuid.UUID | None = PROJECT_ID,
) -> OutlineToolDeps:
    audit = MagicMock()
    audit.record = AsyncMock(return_value=None)
    return OutlineToolDeps(
        outline_service=outline_service
        if outline_service is not None
        else MagicMock(),  # MagicMock 属性恒可调用，缺失分支用例必须传真鸭子 stub
        chapter_service=chapter_service if chapter_service is not None else MagicMock(),
        audit_service=audit,
        expected_project_id=expected,
    )


def _tools(deps: OutlineToolDeps) -> dict[str, object]:
    return {t.spec.name: t for t in build_outline_tools(deps)}


# ── _coerce_id 两分支 + update 可选字段组合（57/60-61/707-712） ──────────


class TestCoerceIdAndFieldCombos:
    async def test_update_accepts_uuid_object_and_non_uuid_string(self) -> None:
        """outline_id 传 UUID 对象（57 直通）与非 UUID 串（60-61 原样透传）均成功。"""
        vol = _outline(id=VOL_ID, level="volume", name="第一卷")
        svc = MagicMock()
        svc.get_outline = AsyncMock(return_value=vol)
        svc.update_outline = AsyncMock(return_value=SimpleNamespace(id=VOL_ID, name="改"))
        tools = _tools(_deps(outline_service=svc))
        r1 = json.loads(await tools["update_volume_outline"].func(outline_id=VOL_ID, name="改"))
        assert r1["ok"] is True
        r2 = json.loads(
            await tools["update_volume_outline"].func(outline_id="vol-legacy", name="改2")
        )
        assert r2["ok"] is True
        # 非 UUID 串原样透传给服务（镜像 #766 RED 契约）
        assert svc.update_outline.call_args_list[1].args[0] == "vol-legacy"

    async def test_update_only_description_and_sort_order(self) -> None:
        """只传 description/sort_order（name 缺席）→ DTO fields 恰此两键（707-712）。"""
        vol = _outline(id=VOL_ID, level="volume")
        svc = MagicMock()
        svc.get_outline = AsyncMock(return_value=vol)
        svc.update_outline = AsyncMock(return_value=SimpleNamespace(id=VOL_ID, name="旧名"))
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(
            await tools["update_volume_outline"].func(
                outline_id=str(VOL_ID), description="d", sort_order=5
            )
        )
        assert r["ok"] is True
        dto = svc.update_outline.call_args.args[1]
        assert dto.model_fields_set == {"description", "sort_order"}
        # round-2 name 兜底：实体名优先
        assert r["name"] == "旧名"

    async def test_update_plot_point_optional_field_combo(self) -> None:
        """type/description/position 三可选字段进 DTO（827-831）。"""
        svc = MagicMock()
        p = _point()
        svc.update_point = AsyncMock(return_value=p)
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(
            await tools["update_plot_point"].func(
                plot_point_id=str(p.id), type="转折", description="d2", position=7
            )
        )
        assert r["ok"] is True
        dto = svc.update_point.call_args.args[1]
        assert dto.model_fields_set == {"type", "description", "position"}


# ── _bind_project_id caller 回退（397-402） ─────────────────────────────


class TestBindProjectIdFallback:
    async def test_unbound_expected_uses_caller_str(self) -> None:
        """expected=None + caller 合法 UUID 串 → 服务收到强转后的 UUID。"""
        svc = MagicMock()
        svc.list_outlines = AsyncMock(return_value=([], 0))
        svc.create_outline = AsyncMock(return_value=SimpleNamespace(id=uuid.UUID(int=9)))
        tools = _tools(_deps(outline_service=svc, expected=None))
        r = json.loads(
            await tools["create_overall_outline"].func(project_id=str(PROJECT_ID), name="整本")
        )
        assert r["ok"] is True
        assert svc.create_outline.call_args.kwargs["project_id"] == PROJECT_ID

    async def test_unbound_expected_invalid_str_binds_none(self) -> None:
        """expected=None + caller 垃圾串 → None 透传（397-401 异常分支）。"""
        svc = MagicMock()
        svc.list_outlines = AsyncMock(return_value=([], 0))
        svc.create_outline = AsyncMock(return_value=SimpleNamespace(id=uuid.UUID(int=9)))
        tools = _tools(_deps(outline_service=svc, expected=None))
        r = json.loads(
            await tools["create_overall_outline"].func(project_id="not-a-uuid", name="整本")
        )
        assert r["ok"] is True
        assert svc.create_outline.call_args.kwargs["project_id"] is None


# ── list_outlines volume_title 分支（443-452） ──────────────────────────


class TestListOutlinesVolumeTitle:
    async def test_overall_row_no_volume_and_chapter_missing_attr(self) -> None:
        """overall 行无 volume_id（443 False）；chapter_service 无 get_volume（446 False）。"""
        overall = _outline(id=ROOT_ID, level="overall", name="整本")
        svc = MagicMock()
        svc.list_outlines = AsyncMock(return_value=([overall], 1))
        tools = _tools(_deps(outline_service=svc, chapter_service=SimpleNamespace()))
        r = json.loads(await tools["list_outlines"].func())
        assert r["ok"] is True
        item = r["data"][0]
        assert item["volume_title"] is None and item["volume_id"] is None

    async def test_get_volume_raises_degrades_to_none(self) -> None:
        """get_volume 抛异常 → volume_title=None 不报错（450-451）。"""
        vol = _outline(id=VOL_ID, level="volume", name="卷一", volume_id=uuid.UUID(int=200))
        svc = MagicMock()
        svc.list_outlines = AsyncMock(return_value=([vol], 1))
        chapter = SimpleNamespace(get_volume=AsyncMock(side_effect=RuntimeError("db down")))
        tools = _tools(_deps(outline_service=svc, chapter_service=chapter))
        r = json.loads(await tools["list_outlines"].func())
        assert r["ok"] is True
        assert r["data"][0]["volume_title"] is None

    async def test_volume_row_without_get_volume_attr(self) -> None:
        """volume_id 非空但 chapter_service 无 get_volume → callable 假侧（446→452）。"""
        vol = _outline(id=VOL_ID, level="volume", name="卷一", volume_id=uuid.UUID(int=200))
        svc = MagicMock()
        svc.list_outlines = AsyncMock(return_value=([vol], 1))
        tools = _tools(_deps(outline_service=svc, chapter_service=SimpleNamespace()))
        r = json.loads(await tools["list_outlines"].func())
        assert r["data"][0]["volume_title"] is None
        assert r["data"][0]["volume_id"] == str(uuid.UUID(int=200))


# ── _build_parent_chain / _resolve_outline_by_id 兜底（138-145/157-163） ──


class TestParentChainFallbacks:
    async def test_parent_not_in_map_without_get_outline_breaks(self) -> None:
        """父不在页内且服务无 get_outline 属性 → 链截断（157-158 + 144-145）。"""
        child = _outline(id=uuid.UUID(int=7), level="chapter", parent_id=uuid.UUID(int=8))
        svc = SimpleNamespace(list_outlines=AsyncMock(return_value=([child], 1)))
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(await tools["list_outlines"].func())
        assert r["data"][0]["parent_chain"] == []

    async def test_sync_get_outline_non_coroutine_breaks(self) -> None:
        """get_outline 返回非 coroutine → 链截断（160-161 防御）。"""
        child = _outline(id=uuid.UUID(int=7), level="chapter", parent_id=uuid.UUID(int=8))
        svc = SimpleNamespace(
            list_outlines=AsyncMock(return_value=([child], 1)),
            get_outline=lambda _oid: "not-awaitable",
        )
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(await tools["list_outlines"].func())
        assert r["data"][0]["parent_chain"] == []

    async def test_resolver_returns_non_outline_breaks(self) -> None:
        """get_outline 异步但返回非 Outline → isinstance 拦截（163）→ 截断。"""
        child = _outline(id=uuid.UUID(int=7), level="chapter", parent_id=uuid.UUID(int=8))
        svc = SimpleNamespace(
            list_outlines=AsyncMock(return_value=([child], 1)),
            get_outline=AsyncMock(return_value=SimpleNamespace(name="x", level="volume")),
        )
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(await tools["list_outlines"].func())
        assert r["data"][0]["parent_chain"] == []

    async def test_self_parent_cycle_breaks_at_cap(self) -> None:
        """parent_id 指向自身（异常数据）→ seen 防环 break（138-139）。"""
        cyc = _outline(id=uuid.UUID(int=7), level="volume")
        cyc = cyc.model_copy(update={"parent_id": cyc.id})
        svc = MagicMock()
        svc.list_outlines = AsyncMock(return_value=([cyc], 1))
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(await tools["list_outlines"].func())
        chain = r["data"][0]["parent_chain"]
        assert len(chain) == 1  # 自身入链一次后 seen 命中 break

    async def test_get_outline_tool_resolves_missing_parent_via_service(self) -> None:
        """get_outline 工具面：父不在 map → resolver 命中（162-163）挂上父链。"""
        parent = _outline(id=ROOT_ID, level="overall", name="整本")
        child = _outline(id=uuid.UUID(int=7), level="volume", parent_id=ROOT_ID, name="卷一")

        async def _by_id(oid: object) -> object:
            return child if oid == child.id else parent if oid == parent.id else None

        svc = MagicMock()
        svc.get_outline = AsyncMock(side_effect=_by_id)
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(await tools["get_outline"].func(outline_id=str(child.id)))
        assert r["ok"] is True
        assert r["data"]["parent_chain"] == [
            {"id": str(ROOT_ID), "name": "整本", "level": "overall"}
        ]


# ── 异常信封（467-468/494-495/508-509）+ include=False（488-493） ────────


class TestExceptionEnvelopes:
    async def test_get_outline_service_raises_fails_envelope(self) -> None:
        svc = MagicMock()
        svc.get_outline = AsyncMock(side_effect=RuntimeError("boom"))
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(await tools["get_outline"].func(outline_id=str(VOL_ID)))
        assert r["ok"] is False and r["error"] == "boom"

    async def test_get_outline_without_plot_points_flag(self) -> None:
        """include_plot_points 默认 False → data 无 plot_points 键（488 False 侧）。"""
        ch = _outline(id=uuid.UUID(int=7), level="chapter")
        svc = MagicMock()
        svc.get_outline = AsyncMock(return_value=ch)
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(await tools["get_outline"].func(outline_id=str(ch.id)))
        assert r["ok"] is True
        assert "plot_points" not in r["data"]
        svc.list_points.assert_not_called()

    async def test_list_plot_points_service_raises(self) -> None:
        svc = MagicMock()
        svc.list_points = AsyncMock(side_effect=RuntimeError("read fail"))
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(await tools["list_plot_points"].func(outline_id=str(VOL_ID)))
        assert r["ok"] is False and r["error"] == "read fail"

    async def test_create_overall_fetch_raises_fails_with_audit(self) -> None:
        """前置检查 list 抛 → 失败信封 + 失败审计（508-509）。"""
        svc = MagicMock()
        svc.list_outlines = AsyncMock(side_effect=RuntimeError("db"))
        deps = _deps(outline_service=svc)
        tools = _tools(deps)
        r = json.loads(await tools["create_overall_outline"].func(name="整本"))
        assert r["ok"] is False and r["error"] == "db"
        kwargs = deps.audit_service.record.call_args.kwargs
        assert kwargs["severity_summary"] == "create_overall_outline_create_failed"

    async def test_list_outlines_service_raises_fails_envelope(self) -> None:
        """list_outlines 服务抛 → _fail 信封（467-468），工具永不外抛。"""
        svc = MagicMock()
        svc.list_outlines = AsyncMock(side_effect=RuntimeError("page fail"))
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(await tools["list_outlines"].func())
        assert r["ok"] is False and r["error"] == "page fail"


# ── arc 名歧义（104-105）+ _resolve_arc_names 防御（183-186） ────────────


class TestArcDefenseBranches:
    async def test_arc_name_ambiguous_lists_candidates(self) -> None:
        svc = MagicMock()
        svc.create_point = AsyncMock(return_value=_point())
        svc.list_arcs = AsyncMock(
            return_value=[
                SimpleNamespace(id=uuid.UUID(int=50), name="主线弧"),
                SimpleNamespace(id=uuid.UUID(int=51), name="主线弧"),
            ]
        )
        tools = _tools(_deps(outline_service=svc))
        r = json.loads(
            await tools["create_plot_point"].func(outline_id=str(VOL_ID), name="高潮", arc="主线弧")
        )
        assert r["ok"] is False
        assert "存在多个同名条目（异常数据）" in r["error"]
        assert "主线弧(id=" in r["error"]
        svc.create_point.assert_not_called()

    async def test_get_arc_missing_and_non_coroutine(self) -> None:
        """service 无 get_arc → arc_name None（185-186）；sync 返回非 coroutine → None。"""
        p = _point()
        svc1 = SimpleNamespace(list_points=AsyncMock(return_value=[p]))
        tools1 = _tools(_deps(outline_service=svc1))
        r1 = json.loads(await tools1["list_plot_points"].func(outline_id=str(p.outline_id)))
        assert r1["data"][0]["arc_name"] is None

        svc2 = SimpleNamespace(
            list_points=AsyncMock(return_value=[p]),
            get_arc=lambda _aid: "not-awaitable",
        )
        tools2 = _tools(_deps(outline_service=svc2))
        r2 = json.loads(await tools2["list_plot_points"].func(outline_id=str(p.outline_id)))
        assert r2["data"][0]["arc_name"] is None


# ── registry._build_all_tools 九组 False 分支（312-332） ─────────────────


class TestRegistryGroupSkipping:
    def test_only_outline_deps_materializes_outline_tools(self) -> None:
        """outline 子 deps 之外全 None → 九组 if False 分支 + 物化恰 outline 集。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp

        deps = UnifiedToolDeps(
            reader=None,
            save_draft=None,
            setting_write=None,
            setting_update=None,
            outline=MagicMock(),
            world_rw=None,
            memory=None,
            writing=None,
            delete=None,
            agent_chain=None,
        )
        grants = [GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.WRITE])]
        names = [t.spec.name for t in build_tools_by_grants(grants, deps)]
        assert names == [
            "create_overall_outline",
            "create_volume_outline",
            "create_chapter_outline",
            "update_volume_outline",
            "update_chapter_outline",
            "create_plot_point",
            "update_plot_point",
        ]

    def test_outline_deps_none_group_skipped(self) -> None:
        """outline 子 deps=None → 该组跳过（registry 320->322 False，镜像 #954 delete=None）。"""
        from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp

        deps = UnifiedToolDeps(
            reader=None,
            save_draft=None,
            setting_write=None,
            setting_update=None,
            outline=None,
            world_rw=None,
            memory=None,
            writing=None,
            delete=None,
            agent_chain=None,
        )
        grants = [
            GrantEntry(domain=ToolDomain.OUTLINE, ops=[ToolOp.READ, ToolOp.WRITE]),
        ]
        assert build_tools_by_grants(grants, deps) == []
