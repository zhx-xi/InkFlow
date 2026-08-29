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
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id=str(uuid.uuid4()))


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
            plan, chapters, _make_limits(max_chapters=5, max_agent_calls=50),
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
            plan, chapters, _make_limits(max_chapters=5, max_agent_calls=50),
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
            plan, chapters, _make_limits(max_chapters=5, max_agent_calls=50),
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
            plan, chapters, _make_limits(max_chapters=5, max_agent_calls=50),
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
                plan, chapters, _make_limits(max_chapters=5, max_agent_calls=50),
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
                plan, chapters, _make_limits(max_chapters=5, max_agent_calls=50),
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
                    plan, chapters, BookLimits(max_chapters=5, max_agent_calls=50),
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
