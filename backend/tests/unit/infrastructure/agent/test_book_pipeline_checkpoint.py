"""F44 阶段 4（#338）BookVolumePipeline checkpointer 持久化扩展 — TDD RED 契约测试。

被测模块（阶段 3 已实现——本文件为阶段 4 扩展定义 RED 契约）:
    from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline

RED 预期
--------
book_pipeline 模块已存在 → 本文件可正常收集（非 ModuleNotFoundError）；
RED 形态 = 用例体运行期 FAILED（TypeError/KeyError）:
    - 构造 checkpoint_path 参数未实现 → TypeError: __init__() got an
      unexpected keyword argument 'checkpoint_path'
    - execute/resume 的 thread_id 关键字参数未实现 → TypeError: ... got an
      unexpected keyword argument 'thread_id'
    - 返回 dict 缺 "thread_id" 键 → KeyError: 'thread_id'（守护用例 12-13）
模块顶部仅 import 存在模块（book_pipeline 主契约 + 标准库 + pytest）；
AsyncSqliteSaver/BookLimits/VolumeHITLInterrupt/InMemorySaver 全部用例体 lazy。

设计假设（父侧契约定稿 .hermes/plans/f44-stage4-contract.md §1；GREEN 按此实现）
----------------------------------------
1. 构造扩展: __init__(self, llm_client, *, writer_factory=None, draft_service=None,
   retry_limit=2, checkpointer=None, checkpoint_path: str | Path | None = None)
   - checkpoint_path 给定 → 每次 execute/resume 临时
     `async with AsyncSqliteSaver.from_conn_string(str(self._checkpoint_path)) as saver:`
     打开文件 saver 编译图再运行（文件持久化 = 跨实例/跨进程 resume 可行）；
     AsyncSqliteSaver 是 async context manager（from_conn_string 返回 async
     iterator，直接 async with 使用，langgraph-checkpoint 4.1.1 实证）。
   - checkpointer 显式传入（InMemorySaver）→ 优先，不打开文件（用例 2）。
   - checkpoint_path 接受 str 或 pathlib.Path（用例 1 用 Path）。

2. execute(plan, volumes, limits, *, thread_id: str | None = None) -> dict:
   - thread_id 给定 → 用之（BookService 传 str(plan.id)）；None → 内部 uuid4。
   - 给定 thread_id 必须实际用作图 config thread_id（用例 3：显式 thread_id
     后 get_checkpoint_state(thread_id) 可读状态——证明入图而非仅存实例属性）。
   - 返回 dict 增加 "thread_id" 键（= self._thread_id），{"run_id", "status"} 保持。

3. resume(interrupt_obj, *, approved=True, decision="", thread_id: str | None = None):
   - thread_id 给定 → 用之（跨重启从 plan.thread_id 读）；None → self._thread_id
     （向后兼容，用例 5 覆盖 execute→resume 隐式传递）。
   - 返回 dict 增加 "thread_id" 键（用例 7 覆盖 approved=False 中止路径）。

4. 跨重启 resume（M10「杀进程→重启→resume→无重复内容」单元级等价复刻，用例 8-10）:
   - 同 checkpoint_path 文件两个 pipeline 实例：P1.execute 跑至卷边界抛
     VolumeHITLInterrupt → async with 退出（saver 关闭）→ P2（新实例，同文件）
     resume(thread_id=...) → 从文件 checkpoint 续跑 → completed；
     无重复内容 = draft_service.create 调用次数 = 章数（已完成章不重跑）。
   - resume 的 thread_id 参数是语义必需：P2 实例内存无 self._thread_id，
     不传则找不到 checkpoint（用例 9/10 显式传 thread_id 才可续跑）。

5. get_checkpoint_state(run_id) 签名不变，但 checkpoint_path 模式下须能从文件
   读状态（用例 11，fresh 实例）：BookService.get_summary 的 next 数据源
   （contract §2）依赖它——GREEN 需在 checkpoint_path 装配时临时打开文件 aget_state。

6. 向后兼容（守护，用例 12-13）: 不传 checkpoint_path/thread_id 的既有调用形态
   照常工作（阶段 3 test_book_pipeline.py 10 用例保持 PASS）；execute/resume
   返回多键不破坏旧断言（dict 按存在键查询）。

用例 ↔ 契约映射
----------------
test_constructor_accepts_checkpoint_path_as_pathlib          → 假设 1（Path 装配）
test_explicit_checkpointer_takes_priority_no_file            → 假设 1（优先显式）
test_execute_explicit_thread_id_returned_and_used_in_graph   → 假设 2（thread_id 入图）
test_execute_thread_id_none_generates_uuid4_per_run          → 假设 2（None → uuid4）
test_execute_thread_id_persisted_for_resume                  → 假设 2/3（隐式传递）
test_resume_explicit_thread_id_plumbed                       → 假设 3（显式传递）
test_resume_returns_thread_id_key                            → 假设 3（返回键 + abort）
test_checkpoint_file_created_and_rows_persist                → 假设 1/4（持久化实证）
test_cross_restart_resume_no_duplicate_content               → 假设 4（M10 核心）
test_cross_restart_multi_boundary_three_volumes              → 假设 4（多次中断）
test_file_backed_get_checkpoint_state_fresh_instance         → 假设 5
test_execute_old_call_shape_adds_thread_id_key               → 假设 6（守护）
test_resume_old_call_shape_adds_thread_id_key                → 假设 6（守护）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline

pytestmark = pytest.mark.asyncio


def _chapter(**overrides) -> dict:
    """构造章 dict（镜像 test_book_pipeline.py 既有形态，本文件自带一份）。"""
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
    """构造 WritingPlan（镜像 test_book_pipeline.py _plan，含 thread_id 字段）。"""
    from inkflow.domain.models.writing_plan import WritingPlan

    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "title": "checkpointer 持久化测试",
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
    """构造 BookVolumePipeline 全部 mock 依赖（镜像 test_book_pipeline.py _make_deps）。

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


def _pipeline(deps: dict, *, checkpointer=None) -> BookVolumePipeline:
    """构造内存后端 BookVolumePipeline（显式 InMemorySaver——阶段 3 既有形态）。"""
    from langgraph.checkpoint.memory import InMemorySaver

    return BookVolumePipeline(
        deps["llm_client"],
        writer_factory=deps["writer_factory"],
        draft_service=deps["draft_service"],
        retry_limit=deps["retry_limit"],
        checkpointer=checkpointer or InMemorySaver(),
    )


def _file_pipeline(deps: dict, checkpoint_path) -> BookVolumePipeline:
    """构造文件后端 BookVolumePipeline（checkpoint_path 装配——阶段 4 新契约）。"""
    return BookVolumePipeline(
        deps["llm_client"],
        writer_factory=deps["writer_factory"],
        draft_service=deps["draft_service"],
        retry_limit=deps["retry_limit"],
        checkpoint_path=checkpoint_path,
    )


@pytest.mark.asyncio
class TestCheckpointPathConstruction:
    """checkpointer 装配（假设 1）: checkpoint_path 构造参数 + 显式 checkpointer 优先。"""

    async def test_constructor_accepts_checkpoint_path_as_pathlib(self, tmp_path) -> None:
        """用例 1: 构造接受 checkpoint_path（pathlib.Path），实例属性记录路径。"""
        ckpt = tmp_path / "ckpt.sqlite"
        deps = _make_deps()
        pipeline = _file_pipeline(deps, ckpt)
        assert isinstance(pipeline, BookVolumePipeline)
        # 路径被记录（str 归一化，容忍 str/Path 两种存储形态）
        assert str(pipeline._checkpoint_path) == str(ckpt)

    async def test_explicit_checkpointer_takes_priority_no_file(self, tmp_path) -> None:
        """用例 2: checkpointer 显式传入（InMemorySaver）→ 优先使用，不打开文件。"""
        from langgraph.checkpoint.memory import InMemorySaver

        from inkflow.domain.models.writing_plan import BookLimits

        ckpt = tmp_path / "should-not-exist.sqlite"
        deps = _make_deps()
        pipeline = BookVolumePipeline(
            deps["llm_client"],
            writer_factory=deps["writer_factory"],
            draft_service=deps["draft_service"],
            retry_limit=deps["retry_limit"],
            checkpointer=InMemorySaver(),
            checkpoint_path=ckpt,
        )
        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(2)]
        result = await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())
        assert result["status"] == "completed"
        # 显式 checkpointer 优先 → checkpoint 文件未被创建
        assert not ckpt.exists()


@pytest.mark.asyncio
class TestExecuteThreadIdSemantics:
    """execute thread_id 语义（假设 2）: 显式 thread_id 入图 + None → uuid4 + 隐式传递。"""

    async def test_execute_explicit_thread_id_returned_and_used_in_graph(self) -> None:
        """用例 3: execute(thread_id=\"tid-1\") → 返回 thread_id；且该值实际用作图
        config thread_id（get_checkpoint_state(\"tid-1\") 可读状态——证明入图）。"""
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(2)]
        deps = _make_deps()
        pipeline = _pipeline(deps)
        result = await pipeline.execute(
            _plan(), [_volume(chapters)], BookLimits(), thread_id="tid-1"
        )
        assert result["status"] == "completed"
        assert result["thread_id"] == "tid-1"
        # 显式 thread_id 入图：以该值可读到 checkpoint 状态（results = 2 章）
        state = await pipeline.get_checkpoint_state("tid-1")
        assert state is not None
        assert sorted(state["results"].keys()) == sorted(str(c["outline_id"]) for c in chapters)

    async def test_execute_thread_id_none_generates_uuid4_per_run(self) -> None:
        """用例 4: execute(thread_id=None) → 内部生成 uuid4；两次运行值不同。"""
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(2)]
        deps = _make_deps()
        pipeline = _pipeline(deps)
        plan = _plan()
        r1 = await pipeline.execute(plan, [_volume(chapters)], BookLimits(), thread_id=None)
        r2 = await pipeline.execute(plan, [_volume(chapters)], BookLimits(), thread_id=None)
        # uuid4 语义: 非空、可 round-trip、两次不同（每次运行新 thread）
        for r in (r1, r2):
            assert isinstance(r["thread_id"], str) and r["thread_id"]
            assert str(uuid.UUID(r["thread_id"])) == r["thread_id"]
        assert r1["thread_id"] != r2["thread_id"]

    async def test_execute_thread_id_persisted_for_resume(self) -> None:
        """用例 5: execute(thread_id=\"tid-x\") 抛 interrupt 后，resume 不传 thread_id
        → 沿用 self._thread_id（向后兼容）→ 续跑完成，返回 thread_id 一致。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1 = [_chapter(name=f"v1c{i}", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"v2c{i}", sort_order=i) for i in range(2)]
        deps = _make_deps()
        pipeline = _pipeline(deps)
        try:
            await pipeline.execute(
                _plan(), [_volume(vol1), _volume(vol2)], BookLimits(), thread_id="tid-x"
            )
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        # resume 不传 thread_id → 隐式沿用 execute 显式值（self._thread_id == "tid-x"）
        result = await pipeline.resume(interrupt, approved=True)
        assert result["status"] == "completed"
        assert result["thread_id"] == "tid-x"
        assert deps["writer_factory"].await_count == 4  # 卷 1 2 章 + 卷 2 2 章


@pytest.mark.asyncio
class TestResumeThreadIdSemantics:
    """resume thread_id 语义（假设 3）: 显式 thread_id 传递 + 返回 dict 新增键。"""

    async def test_resume_explicit_thread_id_plumbed(self) -> None:
        """用例 6: resume(thread_id=...) 显式传参被接受并返回（与 execute 同值
        → 内存后端下参数存在性由 TypeError 在 RED 期强制，语义由用例 9 文件后端强制）。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1 = [_chapter(name=f"v1c{i}", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"v2c{i}", sort_order=i) for i in range(2)]
        deps = _make_deps()
        pipeline = _pipeline(deps)
        try:
            await pipeline.execute(
                _plan(), [_volume(vol1), _volume(vol2)], BookLimits(), thread_id="tid-r"
            )
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        result = await pipeline.resume(interrupt, approved=True, thread_id="tid-r")
        assert result["status"] == "completed"
        assert result["thread_id"] == "tid-r"

    async def test_resume_returns_thread_id_key(self) -> None:
        """用例 7: resume 返回 dict 增加 \"thread_id\" 键；approved=False 中止路径
        （status=\"aborted\"，剩余卷不执行）。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1 = [_chapter(name=f"v1c{i}", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"v2c{i}", sort_order=i) for i in range(2)]
        deps = _make_deps()
        pipeline = _pipeline(deps)
        try:
            await pipeline.execute(
                _plan(), [_volume(vol1), _volume(vol2)], BookLimits(), thread_id="tid-k"
            )
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        result = await pipeline.resume(interrupt, approved=False)
        assert result["status"] == "aborted"
        assert result["thread_id"] == "tid-k"
        # 剩余卷（卷 2）未执行
        assert deps["writer_factory"].await_count == 2


@pytest.mark.asyncio
class TestFileBackedCrossRestart:
    """文件后端 + 跨重启 resume（假设 1/4/5）: M10「杀进程→重启→resume→无重复内容」
    的单元级等价复刻（同文件重开 saver = 跨重启语义）。"""

    async def test_checkpoint_file_created_and_rows_persist(self, tmp_path) -> None:
        """用例 8: checkpoint_path 装配 → execute 抛 interrupt 后文件已生成；
        用全新 AsyncSqliteSaver 实例重开同文件 → 能读到该 thread 的 checkpoint
        （持久化实证：async with 退出后数据不丢）。"""
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        ckpt = tmp_path / "persist.sqlite"
        vol1 = [_chapter(name=f"v1c{i}", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"v2c{i}", sort_order=i) for i in range(2)]
        deps = _make_deps()
        p1 = _file_pipeline(deps, ckpt)
        try:
            await p1.execute(
                _plan(), [_volume(vol1), _volume(vol2)], BookLimits(), thread_id="tid-file"
            )
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        assert interrupt.payload is not None
        assert interrupt.payload.get("volume_index") == 0
        # 文件已生成（非空）——async with 退出后 saver 已关闭
        assert ckpt.exists() and ckpt.stat().st_size > 0
        # 全新 saver 实例重开同文件 → checkpoint 行可读（跨实例持久化）
        async with AsyncSqliteSaver.from_conn_string(str(ckpt)) as saver:
            tup = await saver.aget_tuple({"configurable": {"thread_id": "tid-file"}})
            assert tup is not None
            assert tup.config["configurable"]["thread_id"] == "tid-file"

    async def test_cross_restart_resume_no_duplicate_content(self, tmp_path) -> None:
        """用例 9（M10 核心）: P1.execute 跑至卷边界抛 interrupt（卷 1 完成）
        → P1 关闭（async with 退出）→ P2（新实例，同 checkpoint_path）以显式
        thread_id resume → 从文件 checkpoint 续跑卷 2 → completed；
        无重复内容 = draft_service.create 调用次数 = 章数（已完成章不重跑）。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        ckpt = tmp_path / "m10.sqlite"
        vol1 = [_chapter(name=f"v1c{i}", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"v2c{i}", sort_order=i) for i in range(2)]
        all_oids = sorted(str(c["outline_id"]) for c in vol1 + vol2)
        plan = _plan()
        # P1 + P2 共享 writer_factory/draft_service（调用计数跨实例累计）
        deps = _make_deps()
        p1 = _file_pipeline(deps, ckpt)
        try:
            await p1.execute(
                plan, [_volume(vol1), _volume(vol2)], BookLimits(), thread_id="tid-m10"
            )
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        # P1 仅跑完卷 1（2 章）——之后 async with 退出，saver 关闭
        assert deps["draft_service"].create.await_count == 2
        assert deps["writer_factory"].await_count == 2
        # P2 = 新实例（同文件）→ 跨重启 resume，显式 thread_id 是唯一 checkpoint 定位依据
        p2 = _file_pipeline(deps, ckpt)
        result = await p2.resume(interrupt, approved=True, thread_id="tid-m10")
        assert result["status"] == "completed"
        assert result["thread_id"] == "tid-m10"
        # 无重复内容: 卷 1 章不重跑 → create 恰 4 次（卷 1 2 + 卷 2 2）
        assert deps["draft_service"].create.await_count == 4
        assert deps["writer_factory"].await_count == 4
        # 全 4 章结果落 checkpoint（results reducer 跨重启累计）
        state = await p2.get_checkpoint_state("tid-m10")
        assert state is not None
        assert sorted(state["results"].keys()) == all_oids
        assert all(state["results"][oid] == "draft-1" for oid in all_oids)

    async def test_cross_restart_multi_boundary_three_volumes(self, tmp_path) -> None:
        """用例 10: 3 卷 × 1 章 → P1.execute 抛边界 1 interrupt；P2.resume → 抛边界 2
        interrupt；P2 再次 resume → completed。跨重启多轮中断均从文件续跑，无重复。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        ckpt = tmp_path / "multi.sqlite"
        vols = [[_chapter(name=f"v{v}c{c}", sort_order=c) for c in range(1)] for v in range(1, 4)]
        plan = _plan()
        deps = _make_deps()
        p1 = _file_pipeline(deps, ckpt)
        try:
            await p1.execute(plan, [_volume(v) for v in vols], BookLimits(), thread_id="tid-multi")
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        assert deps["draft_service"].create.await_count == 1  # 仅卷 1
        p2 = _file_pipeline(deps, ckpt)
        try:
            await p2.resume(interrupt, approved=True, thread_id="tid-multi")
            raise AssertionError("应再抛 VolumeHITLInterrupt（卷 2 边界）")
        except VolumeHITLInterrupt as exc:
            interrupt2 = exc
        assert deps["draft_service"].create.await_count == 2  # 卷 2 完成
        result = await p2.resume(interrupt2, approved=True, thread_id="tid-multi")
        assert result["status"] == "completed"
        assert result["thread_id"] == "tid-multi"
        assert deps["draft_service"].create.await_count == 3  # 无重复内容
        assert deps["writer_factory"].await_count == 3

    async def test_file_backed_get_checkpoint_state_fresh_instance(self, tmp_path) -> None:
        """用例 11: checkpoint_path 模式下 get_checkpoint_state 能从文件读状态
        （fresh 实例，假设 5）：P1.execute 抛 interrupt 后，P2 以 thread_id 读到
        中断点的 volume_index/results/total_volumes（BookService.get_summary 数据源）。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        ckpt = tmp_path / "summary.sqlite"
        vol1 = [_chapter(name=f"v1c{i}", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"v2c{i}", sort_order=i) for i in range(2)]
        deps = _make_deps()
        p1 = _file_pipeline(deps, ckpt)
        try:
            await p1.execute(
                _plan(), [_volume(vol1), _volume(vol2)], BookLimits(), thread_id="tid-s"
            )
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt:
            pass
        # fresh 实例（同文件）读中断点 checkpoint 状态
        p2 = _file_pipeline(deps, ckpt)
        state = await p2.get_checkpoint_state("tid-s")
        assert state is not None
        assert state.get("volume_index") == 0
        assert state.get("total_volumes") == 2
        assert sorted(state["results"].keys()) == sorted(str(c["outline_id"]) for c in vol1)


@pytest.mark.asyncio
class TestBackwardCompatibility:
    """向后兼容守护（假设 6）: 不传 checkpoint_path/thread_id 的既有形态照常工作，
    仅新增 \"thread_id\" 返回键（RED 期 KeyError 强制该键存在）。"""

    async def test_execute_old_call_shape_adds_thread_id_key(self) -> None:
        """用例 12: execute(plan, volumes, limits) 旧形态（无 thread_id）→ completed；
        返回 dict 保持 run_id/status 且新增 \"thread_id\" 键（str）。"""
        from inkflow.domain.models.writing_plan import BookLimits

        chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(2)]
        deps = _make_deps()
        pipeline = _pipeline(deps)
        result = await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())
        assert result["status"] == "completed"
        assert isinstance(result["run_id"], str) and result["run_id"]
        # 阶段 4 新契约：返回 dict 增加 thread_id 键
        assert isinstance(result["thread_id"], str) and result["thread_id"]
        assert deps["writer_factory"].await_count == 2

    async def test_resume_old_call_shape_adds_thread_id_key(self) -> None:
        """用例 13: execute + resume 均用旧形态（无 thread_id 参数）→ 中止路径照常；
        resume 返回 dict 新增 \"thread_id\" 键（str）。"""
        from inkflow.domain.models.writing_plan import BookLimits
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        vol1 = [_chapter(name=f"v1c{i}", sort_order=i) for i in range(2)]
        vol2 = [_chapter(name=f"v2c{i}", sort_order=i) for i in range(2)]
        deps = _make_deps()
        pipeline = _pipeline(deps)
        try:
            await pipeline.execute(_plan(), [_volume(vol1), _volume(vol2)], BookLimits())
            raise AssertionError("应抛 VolumeHITLInterrupt")
        except VolumeHITLInterrupt as exc:
            interrupt = exc
        result = await pipeline.resume(interrupt, approved=False)
        assert result["status"] == "aborted"
        assert isinstance(result["run_id"], str) and result["run_id"]
        assert isinstance(result["thread_id"], str) and result["thread_id"]
