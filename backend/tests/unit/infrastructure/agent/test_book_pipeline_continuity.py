"""F44 卷级轨承接（#1187）— B+C 综合 RED 契约测试。

B 阶段：写前定「承接点 + 章末钩子」（不依赖正文，扇出前确定）。
C 阶段：写后卷级审计（复用 F34 ChapterAuditService + #1267 阻断语义）。

被测新增面（当前不存在，GREEN 才实现）:
    book_pipeline.VolumeState["continuity"]         — 承接表通道
    book_pipeline._prepare_continuity               — B 阶段节点
    book_pipeline._volume_audit                     — C 阶段节点

RED 预期（本文件首跑必须 FAIL）：
    - B/C 断言组全部 FAIL（节点/通道/注入尚不存在）
    - 反向断言组（build_continuity_brief）FAIL（函数不存在）

设计假设（依据 issue #1187 用户拍板「B+C 综合」+ 任务书 §2）:
----------------------------------------
B 阶段（写前定承接）:
  - 位置：`volume_fan_out` **之前**（图拓扑 START → bootstrap → prepare_continuity
    → volume_fan_out），保证承接信息在扇出前已就位（不依赖任何章正文）。
  - 生成：**一次 LLM 调用生成整卷承接表**（控成本，非每章一次）。
    输入 = 卷纲（若有）+ 各章章纲 + 前一章章纲；输出 = 每章「承接点」+「章末钩子」。
  - 通道：`VolumeState["continuity"]: dict[str, dict]`（键 = str(outline_id)，
    值 = {"carry": str, "hook": str}）；由 Send payload 带进各章分支。
  - 注入：复用既有 `_build_chapter_brief` / `resolve_brief_setting` 通道
    （B 阶段产出作为 brief 附加段，**不新造注入路径**）。

C 阶段（写后卷级审计）:
  - 位置：`join` **之后**、`volume_boundary` **之前**
    （join → volume_audit → volume_boundary），`write_chapter → join` 保持直连。
  - 实现：**复用 F34 `ChapterAuditService.audit`**（不新造审计实现），
    经 `_audit_bridge.report_to_audit_dict` 扁平化 → `blocking_update` 判定阻断
    （**复用 #1267 语义**：severity >= ERROR 且非 degraded → 阻断）。
  - 阻断：产出阻断级 finding → **不进入 volume_boundary**（goto END / status=blocked）。
  - 反向：承接完好输入 → 不产连贯性 finding（审计 node 不阻断）。

可证伪（可证伪自证）:
  - 去掉承接注入 → test_b_continuity_injected_into_brief 必须 FAIL
  - 去掉审计节点 → test_c_volume_audit_node_exists / test_c_blocking_skips_boundary 必须 FAIL
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline

pytestmark = pytest.mark.asyncio


# ─── 夹具（镜像 test_book_pipeline.py 既有形态，避免新造）────────────────────


def _chapter(**overrides) -> dict:
    """章 dict（镜像 Outline 消费字段）。"""
    base = {
        "outline_id": uuid.uuid4(),
        "chapter_id": uuid.uuid4(),
        "name": "第一章",
        "description": "主角在时间旅途中发现悖论",
        "sort_order": 0,
    }
    base.update(overrides)
    return base


def _volume(chapters, **overrides) -> dict:
    """卷 dict: {"volume_id": uuid, "chapters": [...], "description": str}。"""
    base = {
        "volume_id": uuid.uuid4(),
        "chapters": chapters,
        "description": "第一卷：启程",
    }
    base.update(overrides)
    return base


def _plan(**overrides):
    """WritingPlan（镜像 test_book_pipeline.py _plan）。"""
    from inkflow.domain.models.writing_plan import WritingPlan

    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "title": "卷级承接测试",
        "status": "running",
        "root_outline_id": uuid.uuid4(),
        "character_ids": [],
        "limits": {"max_chapters": 100, "max_agent_calls": 200},
        "progress": {},
        "execution_refs": {},
        "thread_id": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return WritingPlan(**base)


class FakeContinuityLLM:
    """承接表生成 fake LLM（B 阶段专用通道）——记录调用次数 + 返回预置承接表。"""

    def __init__(self, table: dict | None = None) -> None:
        self.table = table or {}
        self.calls: list[list] = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return SimpleNamespace(content=json.dumps(self.table, ensure_ascii=False))


class FakeAuditService:
    """F34 ChapterAuditService 鸭子替身——记录 audit 调用 + 返回可控报告。

    契约锁「C 阶段调 F34 的 audit(project_id, chapter_id)」（断言非裸 LLM）。
    """

    def __init__(self, findings: list | None = None, degraded: bool = False) -> None:
        self.findings = findings or []
        self.degraded = degraded
        self.calls: list[tuple] = []

    async def audit(self, project_id, chapter_id, *, include_static: bool = True):
        self.calls.append((project_id, chapter_id))
        return SimpleNamespace(
            chapter_id=chapter_id,
            findings=list(self.findings),
            degraded=self.degraded,
        )


def _finding(
    severity: str = "error", message: str = "第 2 章未承接第 1 章结尾悬念"
) -> SimpleNamespace:
    """F34 finding 鸭子对象（severity 用带 value 的枚举形态）。"""
    return SimpleNamespace(
        severity=SimpleNamespace(value=severity),
        check_type=SimpleNamespace(value="cross_chapter"),
        message=message,
        ref_entity_name="",
    )


def _make_deps(**overrides) -> dict:
    """BookVolumePipeline 全部 mock 依赖（镜像 test_book_pipeline.py）。"""
    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="正文")],
        "usage": {"total_tokens": 100},
    }
    writer_factory = AsyncMock(return_value=fake_agent)
    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")
    deps = {
        "llm_client": AsyncMock(),
        "writer_factory": writer_factory,
        "draft_service": draft_service,
        "agent": fake_agent,
        "retry_limit": 2,
    }
    deps.update(overrides)
    return deps


def _pipeline(deps: dict, *, checkpointer=None, **extra):
    """构造 BookVolumePipeline（真实 LangGraph 图 + InMemorySaver）。"""
    from langgraph.checkpoint.memory import InMemorySaver

    return BookVolumePipeline(
        deps["llm_client"],
        writer_factory=deps["writer_factory"],
        draft_service=deps["draft_service"],
        retry_limit=deps["retry_limit"],
        checkpointer=checkpointer or InMemorySaver(),
        **extra,
    )


# ═══ B 阶段：写前定「承接点 + 钩子」 ═══════════════════════════════════════


class TestBPrepareContinuity:
    """B 阶段契约（#1187）：承接信息在扇出前确定 + 注入各章 brief。"""

    @pytest.mark.asyncio
    async def test_b_continuity_generated_into_state(self) -> None:
        """断言 1: 跑卷级图 → VolumeState 含每章的承接点/钩子。"""
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(3)]
        table = {
            str(c["outline_id"]): {
                "carry": f"承接{c['name']}" if i else "开篇无前文",
                "hook": f"{c['name']}悬念",
            }
            for i, c in enumerate(chapters)
        }
        deps = _make_deps(llm_client=FakeContinuityLLM(table))
        pipeline = _pipeline(deps)
        result = await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())
        assert result["status"] == "completed"
        state = await pipeline.get_checkpoint_state(result["run_id"])
        assert state is not None
        # 承接表通道存在，且含每章条目
        assert "continuity" in state, "VolumeState 缺 continuity 通道（B 阶段未落地）"
        continuity = state["continuity"]
        for c in chapters:
            assert str(c["outline_id"]) in continuity, f"章 {c['name']} 无承接条目"
            entry = continuity[str(c["outline_id"])]
            assert entry.get("carry") is not None
            assert entry.get("hook") is not None

    @pytest.mark.asyncio
    async def test_b_continuity_injected_into_brief(self) -> None:
        """断言 2: 各章 brief 含其承接点（不是其它章的）。

        可证伪：去掉承接注入 → 本断言必须 FAIL。
        """
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(3)]
        table = {
            str(c["outline_id"]): {
                "carry": f"独一无二承接标记{c['name']}",
                "hook": f"独一无二钩子标记{c['name']}",
            }
            for c in chapters
        }
        deps = _make_deps(llm_client=FakeContinuityLLM(table))
        pipeline = _pipeline(deps)
        await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())

        # writer_factory 收到的 system_prompt 应含各章专属承接标记
        calls = deps["writer_factory"].await_args_list
        assert len(calls) == 3
        prompts = [str(c.kwargs.get("system_prompt", "")) for c in calls]
        for c in chapters:
            marker = f"独一无二承接标记{c['name']}"
            own = [p for p in prompts if marker in p]
            assert own, f"章 {c['name']} 的 brief 未含其承接点（注入缺失）"
            # 隔离性：该章 brief 不应含其它章的承接标记
            others = [f"独一无二承接标记{o['name']}" for o in chapters if o is not c]
            for other in others:
                assert other not in own[0], f"章 {c['name']} 的 brief 串入了 {other}"

    @pytest.mark.asyncio
    async def test_b_continuity_before_fanout_no_content_dependency(self) -> None:
        """断言 3: 承接信息在扇出前已确定（不依赖正文）。

        可证伪手法：让所有章正文生成直接失败（writer_factory 恒抛），
        承接表仍须已在 state 中就位 —— 证明承接不依赖任何正文。
        """
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(2)]
        table = {
            str(c["outline_id"]): {"carry": f"承接{c['name']}", "hook": f"{c['name']}钩子"}
            for c in chapters
        }
        deps = _make_deps(llm_client=FakeContinuityLLM(table))
        # writer_factory 恒抛 → 正文永不生成
        deps["writer_factory"].side_effect = RuntimeError("正文生成失败")
        pipeline = _pipeline(deps)
        result = await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())
        state = await pipeline.get_checkpoint_state(result["run_id"])
        assert state is not None
        # 正文未生成（全部 failed）但承接仍在
        assert all(v == "failed" for v in state["results"].values())
        assert state.get("continuity"), "承接信息依赖了正文（扇出前未就位）"

    @pytest.mark.asyncio
    async def test_b_single_llm_call_per_volume(self) -> None:
        """断言（成本）: 一次 LLM 调用生成整卷承接表（非每章一次）。"""
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(5)]
        table = {str(c["outline_id"]): {"carry": "c", "hook": "h"} for c in chapters}
        fake_llm = FakeContinuityLLM(table)
        deps = _make_deps(llm_client=fake_llm)
        pipeline = _pipeline(deps)
        await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())
        # 5 章 → 承接生成调用次数必须为 1（整卷一次）
        assert len(fake_llm.calls) == 1, (
            f"承接生成调用了 {len(fake_llm.calls)} 次（应 1 次整卷）— 成本失控"
        )


# ═══ C 阶段：写后卷级审计（复用 F34 + #1267 阻断） ════════════════════════


class TestCVolumeAudit:
    """C 阶段契约（#1187）：join 后卷级审计节点 + F34 复用 + 阻断语义。"""

    @pytest.mark.asyncio
    async def test_c_volume_audit_node_exists_after_join(self) -> None:
        """断言 4: join 之后有卷级审计节点（图结构断言）。

        可证伪：去掉审计节点 → 本断言必须 FAIL。
        """
        from langgraph.checkpoint.memory import InMemorySaver

        pipeline = _pipeline(_make_deps())
        graph = pipeline._build_graph(InMemorySaver())
        nodes = set(graph.get_graph().nodes.keys())
        edges = {(e.source, e.target) for e in graph.get_graph().edges}
        assert "volume_audit" in nodes, "图缺卷级审计节点（C 阶段未落地）"
        # write_chapter → join 保持直连（不破坏既有拓扑）
        assert ("write_chapter", "join") in edges, "write_chapter→join 直连被破坏"
        # join → volume_audit（审计在 join 之后）
        assert ("join", "volume_audit") in edges, "join 未接 volume_audit"
        # volume_audit 在 volume_boundary 之前
        assert ("volume_audit", "volume_boundary") in edges, "volume_audit 未接 volume_boundary"

    @pytest.mark.asyncio
    async def test_c_audit_uses_f34_service(self) -> None:
        """断言 5: 审计走 F34 ChapterAuditService（非裸 LLM）。"""
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(2)]
        audit = FakeAuditService()  # 无 findings → 不阻断
        deps = _make_deps()
        pipeline = _pipeline(deps, audit_service=audit)
        result = await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())
        assert result["status"] == "completed"
        # 每章都过了一次 F34 audit（project_id, chapter_id）
        assert len(audit.calls) == 2, f"F34 audit 调用 {len(audit.calls)} 次（应 2 章各一次）"
        for project_id, chapter_id in audit.calls:
            assert project_id is not None and chapter_id is not None

    @pytest.mark.asyncio
    async def test_c_blocking_finding_skips_boundary(self) -> None:
        """断言 6: 审计产出阻断级 finding → 不进入 volume_boundary。

        复用 #1267 语义（全自动必阻断）。
        可证伪：去掉审计节点 → 本断言必须 FAIL（会正常走到 boundary）。
        """
        from inkflow.domain.models.writing_plan import BookLimits

        # 两卷 → 正常情况第一卷后必抛 VolumeHITLInterrupt（volume_boundary）
        vol1 = [_chapter(name=f"一卷{i + 1}章", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"二卷{i + 1}章", sort_order=i) for i in range(2)]
        audit = FakeAuditService(findings=[_finding("error")])  # 阻断级
        deps = _make_deps()
        pipeline = _pipeline(deps, audit_service=audit)
        # 阻断 → 不 interrupt，直接 blocked 收尾
        result = await pipeline.execute(_plan(), [_volume(vol1), _volume(vol2)], BookLimits())
        assert result["status"] == "blocked", f"阻断级 finding 未生效（status={result['status']}）"

    @pytest.mark.asyncio
    async def test_c_warning_finding_does_not_block(self) -> None:
        """反向断言（关键）: 非阻断级（warning）→ 照常进入 volume_boundary。

        防「无脑全塞阻断」——只有 severity >= ERROR 才阻断（#1267 口径）。
        """
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1 = [_chapter(name=f"一卷{i + 1}章", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"二卷{i + 1}章", sort_order=i) for i in range(2)]
        audit = FakeAuditService(findings=[_finding("warning", "轻微承接提示")])
        deps = _make_deps()
        pipeline = _pipeline(deps, audit_service=audit)
        with pytest.raises(VolumeHITLInterrupt):
            await pipeline.execute(_plan(), [_volume(vol1), _volume(vol2)], BookLimits())

    @pytest.mark.asyncio
    async def test_c_clean_input_produces_no_blocking(self) -> None:
        """断言 7（反向，关键）: 承接完好输入 → 不产连贯性 finding → 不阻断。

        与 test_c_blocking_finding_skips_boundary 成对，区分「精准实现」与
        「无脑全塞阻断」。
        """
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1 = [_chapter(name=f"一卷{i + 1}章", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"二卷{i + 1}章", sort_order=i) for i in range(2)]
        audit = FakeAuditService(findings=[])  # 承接完好 → 无 finding
        deps = _make_deps()
        pipeline = _pipeline(deps, audit_service=audit)
        with pytest.raises(VolumeHITLInterrupt):
            await pipeline.execute(_plan(), [_volume(vol1), _volume(vol2)], BookLimits())

    @pytest.mark.asyncio
    async def test_c_degraded_does_not_block(self) -> None:
        """反向断言: degraded=True（没审成）→ 不当「通过」也不阻断（#1267 语义）。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1 = [_chapter(name=f"一卷{i + 1}章", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"二卷{i + 1}章", sort_order=i) for i in range(2)]
        # degraded + 有 error finding → 依 #1267：degraded 不阻断
        audit = FakeAuditService(findings=[_finding("error")], degraded=True)
        deps = _make_deps()
        pipeline = _pipeline(deps, audit_service=audit)
        with pytest.raises(VolumeHITLInterrupt):
            await pipeline.execute(_plan(), [_volume(vol1), _volume(vol2)], BookLimits())


# ═══ 边界：单章轨（F49）不受本轨影响 ═════════════════════════════════════


class TestBoundary:
    """边界契约：无审计服务装配时卷级轨行为不变（向后兼容）。"""

    @pytest.mark.asyncio
    async def test_no_audit_service_pipeline_still_completes(self) -> None:
        """未装配 audit_service → 卷级轨既有行为不变（completed）。"""
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(3)]
        deps = _make_deps()
        pipeline = _pipeline(deps)  # 不传 audit_service
        result = await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())
        assert result["status"] == "completed"
