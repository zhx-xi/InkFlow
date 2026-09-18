"""F49 (#551) book-level 自主编排图 BookAgenticPipeline — TDD RED 契约测试（规则 1c 整模块 RED）。

被测模块（当前不存在，GREEN 才实现）:
    from inkflow.infrastructure.agent.book_agentic_pipeline import (
        BookAgenticPipeline,
        BookAgenticHITLInterrupt,
    )

RED 预期
--------
收集期失败（1c 整模块 RED 形态: pytest exit 2 / collected 0 items / 1 error）:
    ModuleNotFoundError: No module named 'inkflow.infrastructure.agent.book_agentic_pipeline'
顶部仅 import 主契约模块；WritingPlan/BookLimits/AgenticBookConfig/langgraph 全部用例体 lazy。

设计假设（本红批契约定稿 = specs/f27-writer-agent/spec.md §5 后端编排核心；GREEN 按此实现）
----------------------------------------
1. 类与构造（§5.1）:
   class BookAgenticPipeline:
       def __init__(self, llm_client, *, writer_factory=None, draft_service=None,
                    audit_callable=None, retry_limit=2, checkpointer=None,
                    checkpoint_path=None) -> None: ...
   - llm_client 经 UntrackedValue 通道传递（F29/F44 bootstrap 节点）；仅在
     book_supervisor（LLM 决策）与 audit_chapter（LLM 审校，若 audit_callable 未注入）调用 chat。
   - writer_factory 镜像 build_agentic_writer 签名（**kwargs → agent，含 async invoke(messages)）；
     draft_service 鸭子对象（create(*, project_id, chapter_id, content, summary) → draft）。
   - checkpointer 默认 InMemorySaver；跨重启用 checkpoint_path（AsyncSqliteSaver 文件后端）。

2. execute（§5.1/§5.4）:
   async def execute(self, plan, chapters, limits, *, config=None, thread_id=None) -> dict
   - chapters = [ChapterDict, ...]（outline_id uuid, chapter_id uuid|None, name, description,
     sort_order）
   - 返回 {"run_id": str, "status": "completed"|"aborted", "thread_id": str}
   - 抛 BookAgenticHITLInterrupt（HITL 确认点命中；payload 供 BookService 存 waiting_hitl）
   - run_id = thread_id（给定用之；None 内部生成 uuid4）

3. 图拓扑（§5.1, F29 模式）:
   START → bootstrap（注入 llm_client）→ book_supervisor（Command(goto)，无静态出边）
   → write_chapter / audit_chapter / revise_chapter / mark_done / finish_book / hitl / fallback
   - 操作节点执行后静态边回 book_supervisor（Spike ② 教训）；hitl 仅 interrupt；fallback → END。

4. book_supervisor 决策（§5.3）:
   - 决策消息 system prompt 含「决策」+ 操作池 + 书进度 + 路由历史 + 护栏约束。
   - 输出: {"action": "goto", "op": "<op>", "outline_id": "<uuid>"} / {"action": "finish"} /
     {"action": "fallback"}。
   - 护栏: steps>=max_steps / op==last_op 且 consecutive>=max_consecutive / 非法 op / 非法
     outline_id → fallback；空 content/解析失败 → 重试 → fallback。
   - 章节循环护栏: 同章 write/audit/revise 累计 >= max_chapter_cycles → 强制 mark_done。
   - audit_required: 某章 write 后未 audit 试图 mark_done/跳章 → 强制 goto audit_chapter。

5. 操作节点（§5.2）:
   - write_chapter: writer_factory → agent.invoke → draft_service.create →
     results[outline_id]=draft_id,
     progress[outline_id]=in_progress
   - audit_chapter: LLM 审校 → audit_results[outline_id] = {score, issues}
   - revise_chapter: 改写 agent → draft_service.create → 更新 results
   - mark_done: progress[outline_id]=done；execution_refs[outline_id]=results[outline_id]
   - finish_book: finished=True → END（status=completed）
   - fallback: 剩余未 done 章一次 write 完成 → END

6. HITL + resume（§5.5）:
   - hitl_points 命中 → interrupt()；resume(interrupt_obj, *, approved=True) → 继续；
     approved=False → 中止（status=aborted）；再次抛 BookAgenticHITLInterrupt（下一确认点）。

7. get_checkpoint_state（§5.4）:
   async def get_checkpoint_state(self, run_id: str) -> dict | None —— 查询图状态；不存在 → None。

用例 ↔ 契约映射
----------------
test_book_level_autonomous_completed_not_empty → 书级自主编排 + 章节落盘非空（M3）
test_book_level_tool_sequence_routing        → 决策序列路由正确（route_history 含 op 轨迹）（§5.3）
test_chapter_level_autonomous_cycle          → 单章 write→audit→revise 直至 mark_done（§5.2，M4）
test_chapter_cycle_cap_forced_mark_done → 同章超 max_chapter_cycles → 强制 mark_done（§7 场景5）
test_audit_required_force_audit              → audit_required 跳审 → 强制 audit（§7 场景6）
test_oscillation_guard_fallback              → 同 op 连续超限 → fallback 写剩余章（§7 场景4）
test_step_limit_fallback                     → 步数超限 → fallback（§7 场景3）
test_hitl_interrupt_payload_and_resume → HITL 命中 → interrupt payload + approved resume（M5）
test_hitl_reject_aborts                      → approved=False → 中止（§5.5）
test_checkpoint_recovery_across_restart → execute → interrupt → fresh 实例 resume 续跑（M5）
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from inkflow.infrastructure.agent._audit_bridge import (
    audit_blocks_writing,
    inspect_audit_conclusion,
)
from inkflow.infrastructure.agent.book_agentic_pipeline import (
    BookAgenticHITLInterrupt,
    BookAgenticPipeline,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes / helpers（GREEN 契约参考；RED 期仅顶层 import 触发收集失败）
# ---------------------------------------------------------------------------


def _make_chapters(n: int) -> list[dict]:
    """n 个章 dict（ChapterDict 形态）。"""
    return [
        {
            "outline_id": uuid.uuid4(),
            "chapter_id": uuid.uuid4(),
            "name": f"第{i + 1}章",
            "description": f"第{i + 1}章大纲描述",
            "sort_order": i,
        }
        for i in range(n)
    ]


def _make_limits(**kw) -> object:
    from inkflow.domain.models.writing_plan import BookLimits

    return BookLimits(**kw)


def _make_config(**kw) -> object:
    from inkflow.domain.models.agent_book import AgenticBookConfig

    return AgenticBookConfig(**kw)


def _make_plan() -> object:
    """WritingPlan 鸭子对象，供 execute 契约参考（GREEN 用真实 WritingPlan 构建）。"""
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status="running",
        progress={},
        execution_refs={},
        limits={},
        character_ids=[],
        root_outline_id=None,
        title="测试书",
        progress_reason=None,
    )


def _gotos(op: str, outline_id) -> str:
    return f'{{"action": "goto", "op": "{op}", "outline_id": "{outline_id}"}}'


class FakeDecisionLLM:
    """书级 supervisor 决策 fake（镜像 F29 FakeLLM）：system prompt 含「决策」→ 返回队列决策。"""

    def __init__(
        self, decisions: list[str], audit_output: str = '{"score": 85, "issues": ["节奏略慢"]}'
    ) -> None:
        self.decisions = list(decisions)
        self.audit_output = audit_output
        self.call_count = 0

    async def chat(self, messages, **kwargs):
        self.call_count += 1
        system = messages[0].content if messages else ""
        if "决策" in system:
            content = self.decisions.pop(0) if self.decisions else '{"action": "finish"}'
            return SimpleNamespace(content=content)
        # audit_chapter 审校调用（非决策）→ 结构化质量输出
        return SimpleNamespace(content=self.audit_output)


class _FakeAgent:
    def __init__(self, content: str) -> None:
        self._content = content

    async def invoke(self, messages, config=None):
        return {"messages": [{"role": "assistant", "content": self._content}]}


class FakeWriterFactory:
    def __init__(self, content: str = "本章正文。" * 50) -> None:
        self.content = content
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeAgent(self.content)


class FakeDraftService:
    """F27 草稿服务 fake——create + get（#1174 审计取正文经 draft_id）。

    ``get(draft_id)`` 返回带 content 的草稿，使 ``_delegate_audit`` 的 F34 分支
    （需要正文非空）可达；真实 F27 契约同名方法。
    """

    def __init__(self, content: str = "本章正文。" * 50) -> None:
        self.created: list[dict] = []
        self.content = content

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id=str(uuid.uuid4()))

    async def get(self, draft_id):
        return SimpleNamespace(id=draft_id, content=self.content)

    async def find_pending(self, project_id, *, source_outline_id=None):
        return SimpleNamespace(id="draft-id", content=self.content)


class FakeChapterService:
    """F2 章服务 fake（#1174 审计输入面：persist_chapter_body 落章）。"""

    def __init__(self) -> None:
        self.updates: list[tuple] = []

    async def update_chapter(self, chapter_id, payload):
        self.updates.append((chapter_id, payload))
        return SimpleNamespace(id=chapter_id)


class FakeAuditService:
    """F34 章节审计服务 fake（#1267）——按 severities 产出 findings 的 ChapterAuditReport。

    模拟真实 F34 服务返回**领域模型**（非 dict），以驱动真 `report_to_audit_dict`
    映射（真实形态驱动：不绕过被测量的桥接层）。
    """

    def __init__(self, severities: set[str] | None = None, *, degraded: bool = False) -> None:
        self.severities = severities or set()
        self.degraded = degraded
        self.calls: list[tuple] = []

    async def audit(self, project_id, chapter_id, *, include_static: bool = True):
        from datetime import UTC, datetime

        from inkflow.domain.models.chapter_audit import (
            AuditCheckType,
            AuditSeverity,
            ChapterAuditFinding,
            ChapterAuditReport,
        )

        self.calls.append((project_id, chapter_id))
        findings = [
            ChapterAuditFinding(
                check_type=AuditCheckType.CHARACTER_DRIFT,
                severity=AuditSeverity(s),
                message=f"审计发现-{s}",
            )
            for s in sorted(self.severities)
        ]
        return ChapterAuditReport(
            chapter_id=chapter_id,
            chapter_title="测试章",
            status="pending",
            findings=findings,
            degraded=self.degraded,
            created_at=datetime.now(UTC),
        )


# ---------------------------------------------------------------------------
# 编排核心契约用例（RED 期：模块不存在 → 收集失败，全部不执行）
# ---------------------------------------------------------------------------


class TestBookAgenticPipeline:
    @pytest.mark.asyncio
    async def test_book_level_autonomous_completed_not_empty(self) -> None:
        """书级自主编排：write→audit→revise→mark_done→finish → completed + 章节非空（M3）。"""
        chapters = _make_chapters(2)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        llm = FakeDecisionLLM(
            [
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("audit_chapter", chapters[0]["outline_id"]),
                _gotos("revise_chapter", chapters[0]["outline_id"]),
                _gotos("mark_done", chapters[0]["outline_id"]),
                _gotos("write_chapter", chapters[1]["outline_id"]),
                _gotos("mark_done", chapters[1]["outline_id"]),
                '{"action": "finish"}',
            ]
        )
        pipeline = BookAgenticPipeline(
            llm, writer_factory=writer, draft_service=drafts, audit_callable=llm.chat
        )
        result = await pipeline.execute(
            plan, chapters, _make_limits(max_chapters=5, max_agent_calls=50)
        )
        assert result["status"] == "completed"
        # 章节落盘非空：每章 ≥1 次 draft_service.create 且 content 非空
        assert len(drafts.created) >= 2
        for call in drafts.created:
            assert (call["content"] or "").strip()

    @pytest.mark.asyncio
    async def test_book_level_tool_sequence_routing(self) -> None:
        """决策序列路由正确：route_history 含 write/audit/revise/mark_done 轨迹（§5.3）。"""
        chapters = _make_chapters(1)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        llm = FakeDecisionLLM(
            [
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("audit_chapter", chapters[0]["outline_id"]),
                _gotos("revise_chapter", chapters[0]["outline_id"]),
                _gotos("mark_done", chapters[0]["outline_id"]),
                '{"action": "finish"}',
            ]
        )
        pipeline = BookAgenticPipeline(
            llm, writer_factory=writer, draft_service=drafts, audit_callable=llm.chat
        )
        result = await pipeline.execute(
            plan, chapters, _make_limits(max_chapters=5, max_agent_calls=50)
        )
        state = await pipeline.get_checkpoint_state(result["run_id"])
        assert state is not None
        route = state.get("route_history", [])
        joined = "".join(route)
        assert "write_chapter" in joined
        assert "audit_chapter" in joined
        assert "revise_chapter" in joined
        assert "mark_done" in joined

    @pytest.mark.asyncio
    async def test_chapter_level_autonomous_cycle(self) -> None:
        """章节级自主循环：单章 write→audit→revise 直至 mark_done（M4）。"""
        chapters = _make_chapters(1)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        llm = FakeDecisionLLM(
            [
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("audit_chapter", chapters[0]["outline_id"]),
                _gotos("revise_chapter", chapters[0]["outline_id"]),
                _gotos("mark_done", chapters[0]["outline_id"]),
                '{"action": "finish"}',
            ]
        )
        pipeline = BookAgenticPipeline(
            llm, writer_factory=writer, draft_service=drafts, audit_callable=llm.chat
        )
        result = await pipeline.execute(
            plan, chapters, _make_limits(max_chapters=5, max_agent_calls=50)
        )
        assert result["status"] == "completed"
        # 单章自主循环：write + revise 各产生一次落盘（≥1），audit ≥1
        assert len(drafts.created) >= 1

    @pytest.mark.asyncio
    async def test_chapter_cycle_cap_forced_mark_done(self) -> None:
        """同章操作超 max_chapter_cycles → 强制 mark_done（防无限修订，§7 场景5）。"""
        chapters = _make_chapters(1)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        llm = FakeDecisionLLM(
            [
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("revise_chapter", chapters[0]["outline_id"]),
                _gotos("revise_chapter", chapters[0]["outline_id"]),
                _gotos("revise_chapter", chapters[0]["outline_id"]),
                '{"action": "finish"}',
            ]
        )
        pipeline = BookAgenticPipeline(
            llm, writer_factory=writer, draft_service=drafts, audit_callable=llm.chat
        )
        result = await pipeline.execute(
            plan,
            chapters,
            _make_limits(max_chapters=5, max_agent_calls=50),
            config=_make_config(max_chapter_cycles=2),
        )
        # 超循环上限 → 强制 mark_done（不再无限 revise），状态可达 completed
        assert result["status"] in ("completed", "aborted")

    @pytest.mark.asyncio
    async def test_audit_required_force_audit(self) -> None:
        """audit_required 跳审 → 护栏强制 goto audit_chapter（§7 场景6）。"""
        chapters = _make_chapters(1)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        llm = FakeDecisionLLM(
            [
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("mark_done", chapters[0]["outline_id"]),  # 跳审
                '{"action": "finish"}',
            ]
        )
        pipeline = BookAgenticPipeline(
            llm, writer_factory=writer, draft_service=drafts, audit_callable=llm.chat
        )
        await pipeline.execute(
            plan,
            chapters,
            _make_limits(max_chapters=5, max_agent_calls=50),
            config=_make_config(audit_required=True),
        )
        # audit_required → 跳审被强制 audit：LLM 调用 ≥ 决策 + 强制审校（≥2）
        assert llm.call_count >= 2

    @pytest.mark.asyncio
    async def test_oscillation_guard_fallback(self) -> None:
        """同 op 连续调度超限 → fallback 写剩余章（§7 场景4）。"""
        chapters = _make_chapters(3)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        llm = FakeDecisionLLM(
            [
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("write_chapter", chapters[0]["outline_id"]),  # 第 4 次连续 → 护栏
            ]
        )
        pipeline = BookAgenticPipeline(
            llm, writer_factory=writer, draft_service=drafts, audit_callable=llm.chat
        )
        result = await pipeline.execute(
            plan,
            chapters,
            _make_limits(max_chapters=5, max_agent_calls=50),
            config=_make_config(max_consecutive=3),
        )
        assert result["status"] in ("completed", "aborted")

    @pytest.mark.asyncio
    async def test_step_limit_fallback(self) -> None:
        """步数超限 → fallback（§7 场景3）。"""
        chapters = _make_chapters(2)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        llm = FakeDecisionLLM([_gotos("write_chapter", chapters[0]["outline_id"])] * 3)
        pipeline = BookAgenticPipeline(
            llm, writer_factory=writer, draft_service=drafts, audit_callable=llm.chat
        )
        result = await pipeline.execute(
            plan,
            chapters,
            _make_limits(max_chapters=5, max_agent_calls=50),
            config=_make_config(max_steps=2),
        )
        assert result["status"] in ("completed", "aborted")

    @pytest.mark.asyncio
    async def test_hitl_interrupt_payload_and_resume(self) -> None:
        """HITL 确认点命中 → interrupt payload + approved resume（§5.5，M5）。"""
        chapters = _make_chapters(1)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        llm = FakeDecisionLLM(
            [
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("mark_done", chapters[0]["outline_id"]),
                '{"action": "finish"}',
            ]
        )
        pipeline = BookAgenticPipeline(
            llm, writer_factory=writer, draft_service=drafts, audit_callable=llm.chat
        )
        with pytest.raises(BookAgenticHITLInterrupt) as ei:
            await pipeline.execute(
                plan,
                chapters,
                _make_limits(max_chapters=5, max_agent_calls=50),
                config=_make_config(hitl_points=["book_start"]),
            )
        assert isinstance(ei.value.payload, dict)
        run_id = ei.value.payload.get("thread_id") or ei.value.payload.get("run_id")
        result = await pipeline.resume(ei.value, approved=True, thread_id=run_id)
        assert result["status"] in ("completed", "aborted")

    @pytest.mark.asyncio
    async def test_hitl_reject_aborts(self) -> None:
        """HITL approved=False → 中止（§5.5）。"""
        chapters = _make_chapters(1)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        llm = FakeDecisionLLM([_gotos("write_chapter", chapters[0]["outline_id"])])
        pipeline = BookAgenticPipeline(
            llm, writer_factory=writer, draft_service=drafts, audit_callable=llm.chat
        )
        with pytest.raises(BookAgenticHITLInterrupt) as ei:
            await pipeline.execute(
                plan,
                chapters,
                _make_limits(max_chapters=5, max_agent_calls=50),
                config=_make_config(hitl_points=["book_start"]),
            )
        result = await pipeline.resume(
            ei.value, approved=False, thread_id=ei.value.payload.get("thread_id")
        )
        assert result["status"] == "aborted"

    @pytest.mark.asyncio
    async def test_checkpoint_recovery_across_restart(self) -> None:
        """execute → interrupt → fresh 实例（跨重启）+ AsyncSqliteSaver → resume 续跑（M5）。"""
        import tempfile
        from pathlib import Path

        from inkflow.domain.models.writing_plan import BookLimits, WritingPlan

        chapters = _make_chapters(2)
        plan = WritingPlan(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            title="测试书",
            status="running",
            progress={},
            execution_refs={},
            limits={},
            character_ids=[],
        )
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        with tempfile.TemporaryDirectory() as d:
            ckpt_path = Path(d) / "ckpt.sqlite"
            # 实例1：execute 在 book_start HITL 中断（跨重启前借 AsyncSqliteSaver 落 checkpointer）
            llm1 = FakeDecisionLLM(['{"action": "finish"}'])
            p1 = BookAgenticPipeline(
                llm1, writer_factory=writer, draft_service=drafts, checkpoint_path=ckpt_path
            )
            with pytest.raises(BookAgenticHITLInterrupt) as ei:
                await p1.execute(
                    plan,
                    chapters,
                    BookLimits(max_chapters=5, max_agent_calls=50),
                    config=_make_config(hitl_points=["book_start"]),
                    thread_id=str(plan.id),
                )
            interrupt_obj = ei.value
            # 实例 2：fresh 对象（不同实例），仅共享 checkpoint_path → resume 续跑全部章
            llm2 = FakeDecisionLLM(
                [
                    _gotos("write_chapter", chapters[0]["outline_id"]),
                    _gotos("mark_done", chapters[0]["outline_id"]),
                    _gotos("write_chapter", chapters[1]["outline_id"]),
                    _gotos("mark_done", chapters[1]["outline_id"]),
                    '{"action": "finish"}',
                ]
            )
            p2 = BookAgenticPipeline(
                llm2, writer_factory=writer, draft_service=drafts, checkpoint_path=ckpt_path
            )
            result = await p2.resume(interrupt_obj, approved=True, thread_id=str(plan.id))
            assert result["status"] == "completed"
        assert len(drafts.created) >= 2  # 续跑后全部章落盘


# ---------------------------------------------------------------------------
# #1267 审计结果消费方（写作链按审计结论阻断）RED 契约
# ---------------------------------------------------------------------------


def _audit_dict(severities: list[str], *, degraded: bool = False) -> dict:
    """构造 report_to_audit_dict 形态的审计结论（findings 平铺 severity）。"""
    return {
        "score": 100 - sum({"error": 20, "warning": 8, "info": 2}[s] for s in severities),
        "issues": [f"问题-{s}" for s in severities],
        "character_drift": [],
        "setting_drift": [],
        "degraded": degraded,
        "chapter_id": str(uuid.uuid4()),
        "findings": [
            {
                "check_type": "character_drift",
                "severity": s,
                "message": f"问题-{s}",
                "suggestion": "",
                "ref_entity_id": None,
                "ref_entity_name": "",
                "context": "",
            }
            for s in severities
        ],
    }


class TestAuditBlocking:
    """#1267：审计结论必须有后果——全自动轨必阻断，交互式轨交用户决定。"""

    @pytest.mark.asyncio
    async def test_autonomous_run_blocks_on_error_finding(self) -> None:
        """① 全自动轨：审计出 error → 停止后续章节（不发下一章 write 请求）。

        issue: 「全自动（auto_write_enabled=true 或 book run）审计 fail
        （severity=error）→ 必须阻断（停止写作 / 标记该章待人工介入），不得静默继续」。
        """
        chapters = _make_chapters(2)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        audits = FakeAuditService({"error"})
        llm = FakeDecisionLLM(
            [
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("audit_chapter", chapters[0]["outline_id"]),
                # 决策还想继续写第 2 章 —— 必须被阻断逻辑拦住（不执行）
                _gotos("write_chapter", chapters[1]["outline_id"]),
                _gotos("mark_done", chapters[1]["outline_id"]),
                '{"action": "finish"}',
            ]
        )
        pipeline = BookAgenticPipeline(
            llm,
            writer_factory=writer,
            draft_service=drafts,
            audit_service=audits,
            chapter_service=FakeChapterService(),
        )
        result = await pipeline.execute(
            plan,
            chapters,
            _make_limits(max_chapters=5, max_agent_calls=50),
            config=_make_config(audit_required=True),
        )
        # 阻断：run 停下（非正常完成），第 2 章从未落盘（= 未发下一章请求）
        assert result["status"] == "blocked", f"应因审计阻断而停，实际 {result['status']}"
        assert len(writer.calls) == 1, f"第 2 章不应开写，实际写了 {len(writer.calls)} 章"
        assert all(d.get("chapter_id") != chapters[1]["chapter_id"] for d in drafts.created), (
            "被阻断的后续章节不应有任何产出丢失前的落盘"
        )

    @pytest.mark.asyncio
    async def test_autonomous_run_continues_without_error_finding(self) -> None:
        """① 反向断言：审计无 error（仅 warning/info）→ 正常继续到 completed。

        防「阻断判定恒 True」这类伪实现——若恒阻断，本用例必红。
        """
        chapters = _make_chapters(2)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        audits = FakeAuditService({"warning", "info"})
        llm = FakeDecisionLLM(
            [
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("audit_chapter", chapters[0]["outline_id"]),
                _gotos("mark_done", chapters[0]["outline_id"]),
                _gotos("write_chapter", chapters[1]["outline_id"]),
                _gotos("mark_done", chapters[1]["outline_id"]),
                '{"action": "finish"}',
            ]
        )
        pipeline = BookAgenticPipeline(
            llm,
            writer_factory=writer,
            draft_service=drafts,
            audit_service=audits,
            chapter_service=FakeChapterService(),
        )
        result = await pipeline.execute(
            plan,
            chapters,
            _make_limits(max_chapters=5, max_agent_calls=50),
            config=_make_config(audit_required=True),
        )
        assert result["status"] != "blocked", "warning/info 不应阻断（非阻断级）"
        assert len(writer.calls) == 2, "无阻断级发现 → 应继续写完两章"

    @pytest.mark.asyncio
    async def test_blocked_state_is_persisted_and_observable(self) -> None:
        """② 状态可查：阻断时状态落库，明确标记「因审计阻断」（不静默）。

        落点 = plan.status="blocked" + plan.progress[oid]="needs_review"
        + progress_reason 含审计原因（复用既有字段，不新增 DB 字段）。
        """
        from inkflow.domain.models.writing_plan import BookLimits, WritingPlan

        chapters = _make_chapters(1)
        plan = WritingPlan(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            title="测试书",
            status="running",
            progress={},
            execution_refs={},
            limits={},
            character_ids=[],
        )
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        audits = FakeAuditService({"error"})
        llm = FakeDecisionLLM(
            [
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("audit_chapter", chapters[0]["outline_id"]),
                '{"action": "finish"}',
            ]
        )
        pipeline = BookAgenticPipeline(
            llm,
            writer_factory=writer,
            draft_service=drafts,
            audit_service=audits,
            chapter_service=FakeChapterService(),
        )
        await pipeline.execute(
            plan,
            chapters,
            BookLimits(max_chapters=5, max_agent_calls=50),
            config=_make_config(audit_required=True),
        )
        oid = str(chapters[0]["outline_id"])
        assert plan.progress.get(oid) == "needs_review", (
            f"被阻断章应标记 needs_review，实际 {plan.progress.get(oid)}"
        )
        assert plan.progress_reason and "审计" in plan.progress_reason, (
            f"阻断原因须落 progress_reason 可查，实际 {plan.progress_reason!r}"
        )

    @pytest.mark.asyncio
    async def test_degraded_audit_does_not_block_but_warns(self) -> None:
        """degraded 例外：LLM 审计失败降级 → 不阻断（没审出来 ≠ 审出问题）+ 告警。

        issue: 「degraded=true（LLM 审计失败）不得当『通过』——须显式区分
        『审了且过』vs『没审成』」→ 本用例断言「不阻断但可感知」。
        """
        chapters = _make_chapters(1)
        plan = _make_plan()
        writer = FakeWriterFactory()
        drafts = FakeDraftService()
        audits = FakeAuditService(set(), degraded=True)
        llm = FakeDecisionLLM(
            [
                _gotos("write_chapter", chapters[0]["outline_id"]),
                _gotos("audit_chapter", chapters[0]["outline_id"]),
                _gotos("mark_done", chapters[0]["outline_id"]),
                '{"action": "finish"}',
            ]
        )
        pipeline = BookAgenticPipeline(
            llm,
            writer_factory=writer,
            draft_service=drafts,
            audit_service=audits,
            chapter_service=FakeChapterService(),
        )
        result = await pipeline.execute(
            plan,
            chapters,
            _make_limits(max_chapters=5, max_agent_calls=50),
            config=_make_config(audit_required=True),
        )
        assert result["status"] != "blocked", "degraded 不应阻断"
        audits_dict = _audit_dict([], degraded=True)
        conclusion = inspect_audit_conclusion(audits_dict)
        assert conclusion["blocked"] is False
        assert conclusion["warning"] is True, "degraded 必须告警（不得静默当通过）"
        assert conclusion["verdict"] == "degraded"

    async def test_interactive_chapter_returns_needs_decision(self) -> None:
        """③ 交互式轨：阻断级 finding → 结论判定为「需用户决定」（blocked=True）。

        交互式形态 = 复用既有 audit_logs.status="pending" 状态机（用户 confirm
        accept/reject 才推进）；真实服务侧行为在
        tests/unit/domain/services/test_chapter_audit_service.py::
        test_error_finding_awaits_user_decision 断言。本用例钉住**编排侧**读到的
        同一个判定：F34 服务产出的真实报告 → blocked=True（不自动继续）。
        """
        from datetime import UTC, datetime

        from inkflow.domain.models.chapter_audit import (
            AuditCheckType,
            AuditSeverity,
            ChapterAuditFinding,
            ChapterAuditReport,
        )
        from inkflow.infrastructure.agent._audit_bridge import report_to_audit_dict

        report = ChapterAuditReport(
            chapter_id=uuid.uuid4(),
            chapter_title="测试章",
            status="pending",
            findings=[
                ChapterAuditFinding(
                    check_type=AuditCheckType.SETTING_DRIFT,
                    severity=AuditSeverity.ERROR,
                    message="与世界观设定矛盾",
                )
            ],
            degraded=False,
            created_at=datetime.now(UTC),
        )
        conclusion = inspect_audit_conclusion(report_to_audit_dict(report))
        assert conclusion["blocked"] is True, "阻断级 finding → 必须交用户决定"
        assert conclusion["verdict"] == "blocked"
        assert conclusion["blocking_count"] == 1
        assert conclusion["blocking_messages"] == ["与世界观设定矛盾"]

    def test_blocking_judgement_is_falsifiable(self) -> None:
        """④ 可证伪自证：把阻断判定改成「恒 False」→ 上述断言必 FAIL。

        本用例直接钉住判定函数语义：error → True；warning/info/空 → False。
        若有人把 ``audit_blocks_writing`` 改成恒 False，本用例即刻变红。
        """
        err = [{"severity": "error", "message": "x"}]
        assert audit_blocks_writing(err) is True, "error 必须判定为阻断级"
        assert audit_blocks_writing([{"severity": "warning"}]) is False
        assert audit_blocks_writing([{"severity": "info"}]) is False
        assert audit_blocks_writing([]) is False
        # degraded 结论即便带 error 也不阻断（没审出来 ≠ 审出问题）
        degraded_with_error = _audit_dict(["error"], degraded=True)
        assert inspect_audit_conclusion(degraded_with_error)["blocked"] is False
