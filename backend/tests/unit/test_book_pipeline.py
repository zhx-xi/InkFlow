"""F44 阶段 3（#337）卷级编排图 BookVolumePipeline — TDD RED 契约测试（规则 1c 整模块 RED）。

被测模块（当前不存在，GREEN 才实现）:
    from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline

RED 预期
--------
收集期失败（1c 整模块 RED 形态: pytest exit 2 / collected 0 items / 1 error）:
    ModuleNotFoundError: No module named 'inkflow.infrastructure.agent.book_pipeline'
顶部仅 import 主契约模块（book_pipeline）；WritingPlan/BookLimits/VolumeHITLInterrupt/
langgraph（StateGraph/Send/Command/interrupt/InMemorySaver/UntrackedValue）全部用例体 lazy。

设计假设（父侧契约定稿 .hermes/plans/f44-stage3-contract.md §1 + spec §5.3/§12 D1-D3/D9/
§13.3 M7-M9 + Spike docs/f44-orchestrator-spike-2026-08-17.md ①-④；GREEN 按此实现）
----------------------------------------
1. 类与构造（§1.2 父侧定稿签名）:
   class BookVolumePipeline:
       def __init__(
           self, llm_client: object, *,
           writer_factory=None, draft_service=None,
           retry_limit: int = 2, checkpointer=None,
       ) -> None: ...
   - llm_client 仅 UntrackedValue 通道传递（镜像 F29 bootstrap 节点），不参与执行决策；
     只在卷级失败 decision="supervisor" 补救时调用 llm_client.chat(messages)（用例 8）。
   - checkpointer 默认 InMemorySaver（进程内）；真实图测试显式传 InMemorySaver。

2. execute（§1.2）:
   async def execute(self, plan: WritingPlan, volumes: list[dict],
                     limits: BookLimits) -> dict:
   - volumes = [{"volume_id": uuid, "chapters": [章 dict, ...]}, ...]
   - 章 dict = {"outline_id": uuid, "chapter_id": uuid|None, "name": str,
     "description": str, "sort_order": int}（镜像 Outline 消费字段；outline_id = 结果键）
   - 返回 {"run_id": str, "status": "completed"}（全部卷完成——最后一卷不 interrupt）
   - 抛 VolumeHITLInterrupt（非最后一卷的卷边界 / 卷级失败；payload 供 BookService 存
     waiting_hitl）；run_id = 本次运行 thread_id（execute 内部生成，测试从返回值取）

3. 图拓扑（Spike ①-④ 实证形态，§1.1）:
   START → bootstrap（UntrackedValue 注入 llm_client）
       → volume_fan_out（Command(goto=[Send("write_chapter", {"chapter": ch}) ...])，
         非 return [Send(...)]——Spike ①）
       → write_chapter 并行分支（节点内无 interrupt——Spike ④ 硬约束）
       → join（map-reduce 回收；results 通道必须 Annotated[dict, operator.or_]
         reducer——Spike ②）
       → join 判定顺序: ① 护栏（累计步数 >= max_agent_calls → END/aborted，用例 9）
         ② 卷级失败（该卷全部章 failed → goto volume_failure，用例 7-8）
         ③ 其余（全成功/部分失败）→ goto volume_boundary（或最后一卷 → END）
       → volume_boundary（interrupt 串行点）→ resume approved=True → 下一卷 / END；
         approved=False → 中止
       → volume_failure（interrupt）→ resume decision: continue / abort / supervisor

4. write_chapter 节点（章级失败恢复，§12 D9，用例 5-6）:
   - 执行 = writer_factory(system_prompt=章 brief, expected_project_id=plan.project_id,
     expected_chapter_id=ch["chapter_id"]) → agent.invoke([...]) →
     draft_service.create(project_id=plan.project_id, chapter_id=ch["chapter_id"],
     content=正文, summary="书级委托保存") → 返回
     {"results": {str(ch["outline_id"]): str(draft.id)}}
   - 失败（writer_factory / agent.invoke / draft_service.create 任一抛异常）→ 重试整章
     执行（重新调用 writer_factory），至多 retry_limit 次重试（总尝试 1 + retry_limit）；
     仍失败 → 返回 {"results": {str(outline_id): "failed"},
     "failed": [str(outline_id)]}（章级只报告，不阻塞其他章；分支内无 interrupt）
   - 卷级失败判定 = 该卷**全部**章 failed（任务书用例 7 语义）；部分失败不触发 volume_failure

5. volume_boundary（卷边界 HITL，§12 D3，用例 3-4）:
   - interrupt({"question": "确认继续下一卷？", "volume_index": <0 基当前卷>,
     "progress": {str(outline_id): "done"|"failed"}})
   - 最后一卷完成 → 不 interrupt → END（execute 返回 completed）。Spike ③ toy 图两卷
     都 interrupt；本契约按父侧 execute()「全部卷完成返回 completed」裁定最后一卷不打断
   - resume(interrupt_obj, *, approved=True) → 下一卷 / END；approved=False → 中止
     （返回 {"run_id": ..., "status": "aborted"}；finished=True；剩余卷章不执行）

6. volume_failure（卷级失败 HITL，§12 D9，用例 7-8）:
   - interrupt({"question": "卷执行失败，如何继续？", "failed": [str(outline_id), ...]})
   - resume(interrupt_obj, *, decision="continue") → 跳过 failed 卷，继续下一卷
   - decision="abort" → 中止（status="aborted"）
   - decision="supervisor" → 授权主 agent 补救：调用 llm_client.chat(messages)（决策
     消息含 failed 章列表）→ 解析 {action: continue|abort}（解析失败默认 continue）→ 继续

7. resume（§1.2；approved 默认 True 为测试契约补充——卷级失败恢复（decision 驱动）
   无需显式 approved；卷边界恢复（approved 驱动）显式传）:
   async def resume(self, interrupt_obj, *, approved: bool = True,
                    decision: str = "") -> dict:
   - 卷边界恢复用 approved（decision 忽略）；卷级失败恢复用 decision（approved 忽略）
   - 返回 {"run_id": str, "status": "completed"|"aborted"} 或再次抛 VolumeHITLInterrupt
   - checkpointer 实例跨调用持久保存图状态（F29 同构；thread_id 沿用 execute 生成值）

8. get_checkpoint_state（§1.2）:
   async def get_checkpoint_state(self, run_id: str) -> dict | None:
   - 查询图状态（results/failed/volume_index/finished 等 VolumeState 键）；不存在 → None

9. 护栏缩放（§5.3，用例 9，镜像 F29 _guard_triggered）:
   - 步数预算 = limits.max_agent_calls；每次章执行尝试（含重试）消耗 1 步
   - join 回收后累计步数 >= 预算 → 终止（goto END，status="aborted"，不抛 interrupt）

用例 ↔ 契约映射
----------------
test_m7_single_volume_send_fanout_three_chapters  → 用例 1（M7 一卷端到端 + reducer 聚合）
test_m7_three_chapters_all_invoked                → 用例 2（M7 并行性：全完成 + 3 结果）
test_m8_volume_boundary_interrupt_payload         → 用例 3（M8 interrupt payload + resume approved）
test_m8_resume_reject_aborts                      → 用例 4（M8 approved=False 中止）
test_m9_chapter_retry_then_success                → 用例 5（章级重试 N → done）
test_m9_chapter_failed_does_not_block_others      → 用例 6（1 章 failed 其余 done）
test_m9_volume_failure_continue                   → 用例 7a（decision=continue 跳过继续）
test_m9_volume_failure_abort                      → 用例 7b（decision=abort 中止）
test_m9_volume_failure_delegate_supervisor        → 用例 8（decision=supervisor 补救）
test_guardrail_max_agent_calls_terminates         → 用例 9（护栏缩放终止）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline

pytestmark = pytest.mark.asyncio


class FakeSupervisor:
    """卷级失败授权 supervisor 补救的 llm fake（镜像 F29 FakeLLM 决策通道，无决策队列）。

    卷级图 = 确定性编排：正常执行不调用 llm_client.chat（llm_client 仅 UntrackedValue
    通道传递）；仅 decision="supervisor" 补救时调用一次 chat（决策消息含 failed 章列表）。
    恒返回预置 JSON 决策（默认 {"action": "continue"}）；契约锁「调用发生 + failed 列表
    传入」，不锁解析细节（用例 8）。
    """

    def __init__(self, decision: str = '{"action": "continue"}') -> None:
        self.decision = decision
        self.calls: list[list] = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return SimpleNamespace(content=self.decision)


def _chapter(**overrides) -> dict:
    """构造章 dict（镜像 Outline 消费字段: outline_id/chapter_id/name/description/sort_order）。"""
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
    """构造卷 dict: {"volume_id": uuid, "chapters": [章 dict, ...]}。"""
    base = {"volume_id": uuid.uuid4(), "chapters": chapters}
    base.update(overrides)
    return base


def _plan(**overrides):
    """构造 WritingPlan（镜像 test_book_service.py _plan）。"""
    from inkflow.domain.models.writing_plan import WritingPlan

    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "title": "卷级编排测试",
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


def _make_deps(**overrides) -> dict:
    """构造 BookVolumePipeline 全部 mock 依赖（镜像 test_book_service.py _make_deps）。

    writer_factory 默认恒成功（返回共享 fake agent——invoke 返回正文 dict）；
    draft_service.create 返回 SimpleNamespace(id="draft-1")；retry_limit 默认 2。
    返回 dict 键: llm_client/writer_factory/draft_service/agent/retry_limit。
    """
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


def _pipeline(deps: dict, *, checkpointer=None):
    """构造 BookVolumePipeline（真实 LangGraph 图: 显式 InMemorySaver checkpointer）。"""
    from langgraph.checkpoint.memory import InMemorySaver

    return BookVolumePipeline(
        deps["llm_client"],
        writer_factory=deps["writer_factory"],
        draft_service=deps["draft_service"],
        retry_limit=deps["retry_limit"],
        checkpointer=checkpointer or InMemorySaver(),
    )


class TestM7VolumeEndToEnd:
    """M7（§13.3）: 一卷端到端 — Send map-reduce 并行扇出 + join 回收（用例 1-2）。"""

    @pytest.mark.asyncio
    async def test_m7_single_volume_send_fanout_three_chapters(self) -> None:
        """用例 1: 一卷 3 章 → 并行扇出 → join 回收 → completed；reducer 聚合生效。"""
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(3)]
        oids = sorted(str(c["outline_id"]) for c in chapters)
        deps = _make_deps()
        pipeline = _pipeline(deps)
        plan = _plan()
        result = await pipeline.execute(plan, [_volume(chapters)], BookLimits())
        assert result["status"] == "completed"
        # reducer 聚合（Spike ② 断言形态）: results 键 = 3 个 outline_id
        state = await pipeline.get_checkpoint_state(result["run_id"])
        assert state is not None
        assert sorted(state["results"].keys()) == oids
        # writer_factory 委托 3 次（每章一次），expected_project_id 传 plan.project_id
        assert deps["writer_factory"].await_count == 3
        calls = deps["writer_factory"].await_args_list
        assert all(call.kwargs.get("expected_project_id") == plan.project_id for call in calls)

    @pytest.mark.asyncio
    async def test_m7_three_chapters_all_invoked(self) -> None:
        """用例 2: 并行性 — 3 章全部执行完成（不锁执行顺序，锁「全部完成 + 3 结果」）。"""
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(3)]
        deps = _make_deps()
        pipeline = _pipeline(deps)
        result = await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())
        assert result["status"] == "completed"
        state = await pipeline.get_checkpoint_state(result["run_id"])
        assert state is not None
        assert sorted(state["results"].keys()) == sorted(str(c["outline_id"]) for c in chapters)
        # 3 个并行分支全部完成: 共享 fake agent 的 invoke 被 await 3 次
        assert deps["agent"].invoke.await_count == 3


class TestM8VolumeBoundaryHITL:
    """M8（§13.3）: 卷边界 interrupt 暂停确认（约束 8 卷级暂停、章级只报告；用例 3-4）。"""

    @pytest.mark.asyncio
    async def test_m8_volume_boundary_interrupt_payload(self) -> None:
        """用例 3: 两卷 → execute 跑完第一卷 3 章 → 抛 VolumeHITLInterrupt；
        resume(approved=True) → 续跑第二卷 → completed。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1_chapters = [_chapter(name=f"一卷{i + 1}章", sort_order=i) for i in range(3)]
        vol2_chapters = [_chapter(name=f"二卷{i + 1}章", sort_order=i) for i in range(2)]
        deps = _make_deps()
        pipeline = _pipeline(deps)
        try:
            await pipeline.execute(
                _plan(), [_volume(vol1_chapters), _volume(vol2_chapters)], BookLimits()
            )
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        payload = interrupt.payload
        assert payload is not None
        assert payload.get("question")
        assert payload.get("volume_index") == 0
        progress = payload.get("progress")
        assert progress is not None
        assert sorted(str(k) for k in progress) == sorted(
            str(c["outline_id"]) for c in vol1_chapters
        )
        assert all(v == "done" for v in progress.values())
        # resume approved=True → 续跑第二卷（最后一卷完成 → completed，不再打断）
        result = await pipeline.resume(interrupt, approved=True)
        assert result["status"] == "completed"
        assert deps["writer_factory"].await_count == 5  # 卷 1 3 章 + 卷 2 2 章

    @pytest.mark.asyncio
    async def test_m8_resume_reject_aborts(self) -> None:
        """用例 4: resume(approved=False) → 中止（finished=True，剩余卷章不执行）。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1_chapters = [_chapter(name=f"一卷{i + 1}章", sort_order=i) for i in range(3)]
        vol2_chapters = [_chapter(name=f"二卷{i + 1}章", sort_order=i) for i in range(2)]
        deps = _make_deps()
        pipeline = _pipeline(deps)
        try:
            await pipeline.execute(
                _plan(), [_volume(vol1_chapters), _volume(vol2_chapters)], BookLimits()
            )
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        result = await pipeline.resume(interrupt, approved=False)
        assert result["status"] == "aborted"
        # 剩余卷（卷 2）未执行: writer_factory 保持第一卷 3 次调用
        assert deps["writer_factory"].await_count == 3
        state = await pipeline.get_checkpoint_state(result["run_id"])
        assert state is not None
        assert state.get("finished") is True


class TestM9RecoveryStrategyTree:
    """M9（§13.3/D9）: 失败恢复策略树 — 章级重试/章级只报告/卷级 interrupt（用例 5-8）。"""

    @pytest.mark.asyncio
    async def test_m9_chapter_retry_then_success(self) -> None:
        """用例 5: 章级失败重试 N 次（默认 2）→ 第 N+1 次成功 → 章 done（重试生效）。"""
        from inkflow.domain.models.writing_plan import BookLimits

        chapter = _chapter()
        fake_agent = AsyncMock()
        fake_agent.invoke.return_value = {
            "messages": [SimpleNamespace(content="正文")],
            "usage": {"total_tokens": 100},
        }
        writer_factory = AsyncMock(
            side_effect=[RuntimeError("transient"), RuntimeError("transient"), fake_agent]
        )
        draft_service = AsyncMock()
        draft_service.create.return_value = SimpleNamespace(id="draft-1")
        deps = _make_deps(writer_factory=writer_factory, draft_service=draft_service)
        pipeline = _pipeline(deps)
        result = await pipeline.execute(_plan(), [_volume([chapter])], BookLimits())
        assert result["status"] == "completed"
        state = await pipeline.get_checkpoint_state(result["run_id"])
        assert state is not None
        # 重试生效: 章 done（results 值 = execution_id，非 "failed"）
        assert state["results"][str(chapter["outline_id"])] == "draft-1"
        assert writer_factory.await_count == 3  # 1 初始 + 2 重试

    @pytest.mark.asyncio
    async def test_m9_chapter_failed_does_not_block_others(self) -> None:
        """用例 6: 3 章中 1 章永久失败 → 该章 failed + 其余 2 章 done（章级只报告）。"""
        from inkflow.domain.models.writing_plan import BookLimits

        ch1 = _chapter(name="第一章")
        ch2 = _chapter(name="第二章")
        ch3 = _chapter(name="第三章")
        fake_agent = AsyncMock()
        fake_agent.invoke.return_value = {
            "messages": [SimpleNamespace(content="正文")],
            "usage": {"total_tokens": 100},
        }

        async def _wf(**kwargs):
            # 按 expected_chapter_id 判别: 第二章永久失败，其余成功（并行分支顺序无关）
            if kwargs.get("expected_chapter_id") == ch2["chapter_id"]:
                raise RuntimeError("permanent failure")
            return fake_agent

        writer_factory = AsyncMock(side_effect=_wf)
        deps = _make_deps(writer_factory=writer_factory, retry_limit=0)
        pipeline = _pipeline(deps)
        result = await pipeline.execute(_plan(), [_volume([ch1, ch2, ch3])], BookLimits())
        # 部分失败 ≠ 卷级失败 → 卷正常完成（章级只报告，不阻塞其他章）
        assert result["status"] == "completed"
        state = await pipeline.get_checkpoint_state(result["run_id"])
        assert state is not None
        assert state["results"][str(ch2["outline_id"])] == "failed"
        assert state["results"][str(ch1["outline_id"])] == "draft-1"
        assert state["results"][str(ch3["outline_id"])] == "draft-1"
        assert writer_factory.await_count == 3  # 3 章各 1 次尝试（retry_limit=0）

    @pytest.mark.asyncio
    async def test_m9_volume_failure_continue(self) -> None:
        """用例 7a: 卷级失败（全部章 failed）→ volume_failure interrupt →
        resume(decision="continue") → 跳过 failed 卷，继续下一卷。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1_chapters = [_chapter(name=f"一卷{i + 1}章", sort_order=i) for i in range(2)]
        vol2_chapters = [_chapter(name=f"二卷{i + 1}章", sort_order=i) for i in range(2)]
        vol1_cids = {c["chapter_id"] for c in vol1_chapters}
        fake_agent = AsyncMock()
        fake_agent.invoke.return_value = {
            "messages": [SimpleNamespace(content="正文")],
            "usage": {"total_tokens": 100},
        }

        async def _wf(**kwargs):
            if kwargs.get("expected_chapter_id") in vol1_cids:
                raise RuntimeError("vol1 always fails")
            return fake_agent

        writer_factory = AsyncMock(side_effect=_wf)
        deps = _make_deps(writer_factory=writer_factory, retry_limit=0)
        pipeline = _pipeline(deps)
        try:
            await pipeline.execute(
                _plan(), [_volume(vol1_chapters), _volume(vol2_chapters)], BookLimits()
            )
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        payload = interrupt.payload
        assert payload is not None
        assert payload.get("question")
        assert sorted(map(str, payload.get("failed", []))) == sorted(
            str(c["outline_id"]) for c in vol1_chapters
        )
        # decision=continue → 跳过 failed 卷，继续下一卷 → 完成
        result = await pipeline.resume(interrupt, decision="continue")
        assert result["status"] == "completed"
        state = await pipeline.get_checkpoint_state(result["run_id"])
        assert state is not None
        for c in vol2_chapters:
            assert state["results"][str(c["outline_id"])] == "draft-1"
        assert writer_factory.await_count == 4  # 卷 1 2 次失败 + 卷 2 2 次成功

    @pytest.mark.asyncio
    async def test_m9_volume_failure_abort(self) -> None:
        """用例 7b: 卷级失败 → resume(decision="abort") → 中止（不再执行剩余卷）。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1_chapters = [_chapter(name=f"一卷{i + 1}章", sort_order=i) for i in range(2)]
        vol2_chapters = [_chapter(name=f"二卷{i + 1}章", sort_order=i) for i in range(2)]
        writer_factory = AsyncMock(side_effect=RuntimeError("vol1 always fails"))
        deps = _make_deps(writer_factory=writer_factory, retry_limit=0)
        pipeline = _pipeline(deps)
        try:
            await pipeline.execute(
                _plan(), [_volume(vol1_chapters), _volume(vol2_chapters)], BookLimits()
            )
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        result = await pipeline.resume(interrupt, decision="abort")
        assert result["status"] == "aborted"
        # 剩余卷（卷 2）未执行: writer_factory 保持卷 1 的 2 次调用
        assert writer_factory.await_count == 2
        state = await pipeline.get_checkpoint_state(result["run_id"])
        assert state is not None
        assert state.get("finished") is True

    @pytest.mark.asyncio
    async def test_m9_volume_failure_delegate_supervisor(self) -> None:
        """用例 8: 卷级失败 → resume(decision="supervisor") → 授权主 agent 补救
        （FakeSupervisor 决策调用收到 failed 章列表）。"""
        from langgraph.checkpoint.memory import InMemorySaver

        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(2)]
        oids = sorted(str(c["outline_id"]) for c in chapters)
        writer_factory = AsyncMock(side_effect=RuntimeError("always fails"))
        draft_service = AsyncMock()
        draft_service.create.return_value = SimpleNamespace(id="draft-1")
        supervisor = FakeSupervisor()  # 兼作 llm_client（UntrackedValue 通道）
        pipeline = BookVolumePipeline(
            supervisor,
            writer_factory=writer_factory,
            draft_service=draft_service,
            retry_limit=0,
            checkpointer=InMemorySaver(),
        )
        try:
            await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        payload = interrupt.payload
        assert payload is not None
        assert payload.get("question")
        assert sorted(map(str, payload.get("failed", []))) == oids
        result = await pipeline.resume(interrupt, decision="supervisor")
        # 补救触发: llm_client.chat 决策调用收到 failed 章列表
        assert supervisor.calls, "supervisor 补救决策调用未发生"
        assert oids[0] in str(supervisor.calls[0])
        # 补救决策（默认 {"action": "continue"}）→ 继续 → 单卷跳过 → 完成
        assert result["status"] == "completed"


class TestGuardrailScaling:
    """护栏缩放（§5.3，用例 9，镜像 F29 _guard_triggered）。"""

    @pytest.mark.asyncio
    async def test_guardrail_max_agent_calls_terminates(self) -> None:
        """用例 9: 步数预算 = max_agent_calls；超预算 → 终止（aborted，不抛 interrupt）。"""
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(3)]
        writer_factory = AsyncMock(side_effect=RuntimeError("always fails"))
        deps = _make_deps(writer_factory=writer_factory, retry_limit=0)
        pipeline = _pipeline(deps)
        result = await pipeline.execute(
            _plan(),
            [_volume(chapters)],
            BookLimits(max_agent_calls=1, max_chapters=100),
        )
        # 护栏终止: 不抛 interrupt，返回 aborted（join 回收后步数 3 >= 预算 1）
        assert result["status"] == "aborted"
        state = await pipeline.get_checkpoint_state(result["run_id"])
        assert state is not None
        assert state.get("finished") is True
        assert writer_factory.await_count == 3  # 全部章已尝试（并行扇出）


# ════ F44 阶段3 coverage-gap 补测（规则 1j，2026-08-17：代码已存在直接通过）════
# CI coverage-backend TOTAL 98% < 98.5%（book_pipeline.py 87% miss）——补防御分支。


class TestCoverageGapPipeline:
    """book_pipeline.py 防御分支补测（规则 1j：直接通过，非 RED）。"""

    @pytest.mark.asyncio
    async def test_extract_final_content_defensive_branches(self) -> None:
        """_extract_final_content 防御：无 messages / 无 content → 空串（L66/70/72）。"""
        from inkflow.infrastructure.agent.book_pipeline import _extract_final_content

        assert _extract_final_content({}) == ""
        assert _extract_final_content({"messages": [{"content": None}]}) == ""
        assert _extract_final_content({"messages": [object()]}) == ""

    def test_parse_supervisor_decision_defensive(self) -> None:
        """_parse_supervisor_decision 防御：空/非 dict/未知 action → continue（L83-95）。"""
        from inkflow.infrastructure.agent.book_pipeline import _parse_supervisor_decision

        assert _parse_supervisor_decision("") == "continue"
        assert _parse_supervisor_decision("not json") == "continue"
        assert _parse_supervisor_decision("[1,2]") == "continue"
        assert _parse_supervisor_decision('{"action": "dance"}') == "continue"
        assert _parse_supervisor_decision('{"action": "abort"}') == "abort"

    @pytest.mark.asyncio
    async def test_empty_volume_fan_out_direct_to_join(self) -> None:
        """空卷 → volume_fan_out 直接 goto join 回收（L110），completed 无中断。"""
        from inkflow.domain.models.writing_plan import BookLimits

        pipeline = _pipeline(_make_deps())
        result = await pipeline.execute(_plan(), [], BookLimits())
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_resume_again_interrupts_on_next_boundary(self) -> None:
        """resume 命中下一卷边界 → 再抛 VolumeHITLInterrupt（L288，多卷连续中断）。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1 = [_chapter(name=f"v1c{i}", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"v2c{i}", sort_order=i) for i in range(2)]
        vol3 = [_chapter(name=f"v3c{i}", sort_order=i) for i in range(2)]
        deps = _make_deps()
        pipeline = _pipeline(deps)
        try:
            await pipeline.execute(
                _plan(), [_volume(vol1), _volume(vol2), _volume(vol3)], BookLimits()
            )
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        # resume 卷 1 → 卷 2 边界再次 interrupt（3 卷：两次暂停）
        try:
            await pipeline.resume(interrupt, approved=True)
            raise AssertionError("应再抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt:
            pass  # 预期：第二卷边界暂停
        assert deps["writer_factory"].await_count == 4  # 卷1 2 + 卷2 2

    @pytest.mark.asyncio
    async def test_delegate_chapter_unassembled_raises(self) -> None:
        """_delegate_chapter 未装配（plan/writer_factory None）→ ValueError（L316/318）。"""
        pipeline = BookVolumePipeline(
            AsyncMock(), writer_factory=None, draft_service=None, retry_limit=0
        )
        chapter = _chapter()
        with pytest.raises(ValueError, match="plan 未装配"):
            await pipeline._delegate_chapter(chapter)
        # 装配 plan 但无 writer_factory → writer_factory 未装配
        pipeline._plan = _plan()
        with pytest.raises(ValueError, match="writer_factory 未装配"):
            await pipeline._delegate_chapter(chapter)


class TestCoverageGapPipeline2:
    """book_pipeline.py 二轮补测：markdown 围栏决策解析（L90-93）。"""

    def test_parse_supervisor_decision_markdown_fence(self) -> None:
        """markdown 代码块围栏包裹的 JSON → 剥离解析（L90-93）。"""
        from inkflow.infrastructure.agent.book_pipeline import _parse_supervisor_decision

        assert _parse_supervisor_decision('```json\n{"action": "abort"}\n```') == "abort"
        assert _parse_supervisor_decision('```json\n{"action": "continue"}\n```') == "continue"

    def test_parse_supervisor_decision_fence_extract_still_invalid(self) -> None:
        """围栏提取后仍非法 JSON：```json 围栏内 {action: continue}（键未加引号）/
        {"action": }（值非法）→ 提取子串 json.loads 再失败 → data=None → 默认
        continue（覆盖 L103-104 二次解析失败分支）。"""
        from inkflow.infrastructure.agent.book_pipeline import _parse_supervisor_decision

        assert _parse_supervisor_decision("```json\n{action: continue}```") == "continue"
        assert _parse_supervisor_decision('```json\n{"action": }```') == "continue"
