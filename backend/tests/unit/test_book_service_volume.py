"""F44 阶段3 BookService 卷级编排扩展单测（TDD RED 阶段，契约先行）。

权威来源：.hermes/plans/f44-stage3-contract.md §2（父侧契约定稿，语义冲突以它为准）、
specs/f44-book-orchestrator/spec.md §5.3（卷级编排 + Send map-reduce + 卷级 HITL）、
§12 D1-D3/D9（扇出形态/聚合通道/interrupt 落点/恢复策略树）、§13.3 M7-M9。
本文件为 `domain/services/book_service.py`（阶段 2 基座 + 阶段 3 扩展）定义契约。

════════════════════════════════════════════════════════════════════
设计假设（阶段 3 GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

0. 【用例编号 ↔ 测试映射】1=构造守护 2=有卷节点分组 3=无卷整本一卷
   4=安全阀零委托 5=waiting_hitl 落库 6=completed 落库
   7=confirm_run waiting_hitl→resume 8=confirm_run 非 waiting_hitl 拒绝
   9=confirm_run 计划不存在 10=get_status 扩展（10a 新键 / 10b counters 守护）。

1. 【构造扩展 · 用例 1】BookService 阶段 3 新增可选关键字参数
   volume_pipeline: object | None = None（放最后，默认 None，向后兼容）——
   卷级编排引擎鸭子（镜像 BookVolumePipeline：async execute(plan, volumes,
   limits) → dict 或抛 VolumeHITLInterrupt；async resume(interrupt_obj, *,
   approved: bool, decision: str = "") → dict）。
   用例 1 = 守护（RED 期 PASS 刻意）：不带新参数构造零影响（阶段 2 签名不变，
   既有 write_book 路径照常可用）。

2. 【write_book_volume(plan_id: uuid.UUID, limits: BookLimits | None = None)
   → dict · 用例 2-6】卷级编排入口：
   a. 安全阀预检（复用 _check_content_written，§5.2/D8 同语义）：任一目标章
      execution_refs[outline_id] done 或 content_checker True →
      ChapterAlreadyWrittenError（消息含「该章已有内容，拒绝重跑」），
      volume_pipeline 零调用（用例 4 用 execution_refs 形态锁「零委托」）。
   b. 卷 planner 拆章（_find_volumes）：outline 表取 level=volume 节点 + 其下
      level=chapter 子节点（parent_id=volume.id，sort_order 升序）→
      volumes = [{"volume_id": volume.id, "chapters": [章 dict...]}, ...]
      （章 dict = _outline_to_chapter_dict 产物：outline_id/chapter_id/name/
      description/sort_order——pipeline 契约消费 dict 非领域对象，真实冒烟实证）
      （用例 2：2 卷 × 各 2 章，按 parent_id/sort_order 确定性分组，
      与列表位置无关）；无 level=volume 节点 → 整本书作为一卷（用例 3：
      1 卷 × 全部章，回退卷的 volume_id 由实现决定，契约只锁章分组与顺序）。
   c. 委托：volume_pipeline.execute(plan, volumes, merged_limits) 恰一次
      （用例 2/3/6 mock 记录收到的 plan/volumes/limits 参数；limits 走阶段 2
      merge 链：请求显式 > 项目级 extra > 默认 BookLimits）。
   d. VolumeHITLInterrupt 捕获（用例 5，中断不传播）：plan.status="waiting_hitl"
      + plan.hitl_payload = interrupt.payload 落库（update_writing_plan），
      返回 {"run_id": str(plan.id), "status": "waiting_hitl"}。
      （hitl_payload 是 WritingPlan 新增顶层字段 `hitl_payload: dict[str, Any] | None = None`——
      model + ORM LenientJSON 列 + repo 转换/update 三处扩展；禁塞 plan.limits，
      limits 类型 dict[str, int | bool] 拒绝 dict 值，RED 复验实证）
   e. 正常返回（用例 6）：plan.status="completed" 落库（update_writing_plan），
      返回 {"run_id": str(plan.id), "status": "completed"}。
   f. ValueError：计划不存在 / 上限全无护栏（同 write_book 语义，复用阶段 2
      校验链，本文件不重复测）。

3. 【confirm_run(run_id: str, *, approved: bool, decision: str = "") → dict
   · 用例 7-9】卷级 HITL 确认：
   a. plan.status="waiting_hitl"（用例 7）→
      volume_pipeline.resume(interrupt_obj, approved=approved,
      decision=decision) 被调用；interrupt_obj 由 plan.hitl_payload
      重建（VolumeHITLInterrupt 形态，.payload == 存储 payload），返回 resume
      结果（{"run_id", "status": running | waiting_hitl | completed}）。
   b. 非 waiting_hitl（用例 8）→ ValueError（消息含「未处于等待确认状态」，
      API 映射 422），resume 零调用。
   c. plan 查无（用例 9）→ ValueError（消息含「不存在」，API 映射 404）。

4. 【get_status 扩展（向后兼容）· 用例 10】counters 既有 7 键
   （max_chapters/max_agent_calls/max_tokens/tokens_used/tokens_warning/
   agent_calls/chapters_written）不变（用例 10b = 守护，RED 期 PASS 刻意）；
   plan.status="waiting_hitl" 时新增顶层键 waiting_hitl: True +
   hitl_payload: dict（= interrupt payload，用例 10a）。

5. 【RED 预期形态】阶段 2 实现下本文件 ≈ 9 failed, 2 passed：
   - 用例 2-9：_service(volume_pipeline=...) 显式传新参数 → 阶段 2 构造不接受
     → TypeError: unexpected keyword argument 'volume_pipeline'（FAILED 在用例体，
     非收集期错误）；GREEN 实现后构造通过，若方法仍缺失 → AttributeError
     （write_book_volume/confirm_run 不存在），同为 FAILED 非 ERROR。
   - 用例 10a：get_status 无 waiting_hitl/hitl_payload 顶层键 → KeyError
     （FAILED 非 ERROR）。
   - 用例 5 的 VolumeHITLInterrupt 为 MockVolumePipeline.execute 用例体 lazy
     import（inkflow.infrastructure.agent.book_pipeline）→ 阶段 3 未实现前该模块
     不存在 → ImportError（FAILED 非收集期错误）；方法缺失时 TypeError 先触发。
   - 守护用例 1/10b：RED 期 PASS 刻意（docstring 注明，防父侧误判）。

【mock 策略】repo/outline_repo 用 AsyncMock；卷级引擎用有状态 MockVolumePipeline
（镜像 test_agent_service_supervisor.py MockPipeline 形态：记录 execute/resume
调用参数，execute 可配置抛 VolumeHITLInterrupt）。helper（_plan/_outline/
_chapters/_make_deps/_service）镜像 test_book_service.py 既有形态，本文件自带
一份（不 import 既有测试文件）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService, ChapterAlreadyWrittenError

pytestmark = pytest.mark.asyncio


# ── helpers（镜像 test_book_service.py 既有形态，本文件自带一份）─────


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _plan(**overrides) -> WritingPlan:
    base = dict(
        id=uuid.uuid4(),
        project_id=_pid(),
        title="测试计划",
        status="ready",
        root_outline_id=uuid.uuid4(),
        character_ids=[],
        limits={"max_chapters": 1, "max_agent_calls": 1},
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return WritingPlan(**base)


def _outline(**overrides) -> Outline:
    base = dict(
        id=uuid.uuid4(),
        project_id=_pid(),
        name="第一章",
        description="主角在时间旅途中发现悖论",
        sort_order=0,
        level="chapter",
        parent_id=None,
        chapter_id=None,
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return Outline(**base)


def _chapters(plan: WritingPlan, n: int, *, parent_id: uuid.UUID | None = None) -> list[Outline]:
    """构造 n 个章 outline（parent_id 默认挂 plan.root_outline_id；sort_order 0..n-1）。"""
    pid = plan.root_outline_id if parent_id is None else parent_id
    return [
        _outline(parent_id=pid, sort_order=i, chapter_id=uuid.uuid4(), name=f"第{i + 1}章")
        for i in range(n)
    ]


def _volume(**overrides) -> Outline:
    """构造 level=volume 大纲节点（F43 P3 三级结构）。"""
    base = dict(
        id=uuid.uuid4(),
        project_id=_pid(),
        name="第一卷",
        description="卷描述",
        sort_order=0,
        level="volume",
        parent_id=None,
        chapter_id=None,
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return Outline(**base)


def _volumed_outline(
    plan: WritingPlan, *, volumes: int = 2, chapters_per_volume: int = 2
) -> list[Outline]:
    """构造卷结构 outline 列表并刻意交错返回顺序（验证卷 planner 按
    parent_id/sort_order 确定性分组，而非按列表位置贪心归卷）。

    结构：volumes 个 level=volume 节点（挂 plan.root_outline_id，sort_order
    0..n-1）+ 每卷 chapters_per_volume 个 level=chapter 子节点
    （parent_id=volume.id，chapter_id 有值，sort_order 0..m-1）。
    返回顺序 = 卷1, 卷1章1, 卷2, 卷2章1, 卷1章2, 卷2章2, ...——任何
    「卷节点后连续章都归该卷」的贪心实现都会把卷 1 的第 2 章错分给卷 2 → 分组断言 FAIL。
    """
    vols = [
        _volume(name=f"第{v + 1}卷", sort_order=v, parent_id=plan.root_outline_id)
        for v in range(volumes)
    ]
    chapters: dict[uuid.UUID, list[Outline]] = {
        vol.id: [
            _outline(
                parent_id=vol.id,
                sort_order=c,
                chapter_id=uuid.uuid4(),
                name=f"{vol.name}-第{c + 1}章",
            )
            for c in range(chapters_per_volume)
        ]
        for vol in vols
    }
    outlines: list[Outline] = []
    for c in range(chapters_per_volume):
        for vol in vols:
            if c == 0:
                outlines.append(vol)
            outlines.append(chapters[vol.id][c])
    return outlines


def _make_deps(**overrides):
    """构造 BookService 全部 mock 依赖（可覆盖；阶段 3 新参数 volume_pipeline
    由用例显式传入——阶段 2 构造不接受 → TypeError → RED）。"""
    repo = AsyncMock()
    repo.get_writing_plan.return_value = None
    repo.update_writing_plan.return_value = None

    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="第一章正文内容", tool_calls=[])]
    }
    writer_factory = AsyncMock(return_value=fake_agent)

    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")

    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([], 0)

    deps = dict(
        repo=repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
    )
    deps.update(overrides)
    return deps


def _service(**overrides) -> BookService:
    return BookService(**_make_deps(**overrides))


class MockVolumePipeline:
    """卷级编排引擎 Mock（镜像 test_agent_service_supervisor.py MockPipeline 形态）。

    有状态：记录 execute/resume 调用参数；execute 可配置抛 VolumeHITLInterrupt
    （用例体 lazy import——阶段 3 未实现前该模块不存在 → ImportError FAILED）。
    """

    def __init__(
        self,
        *,
        execute_result: dict | None = None,
        execute_interrupt: dict | None = None,
        resume_result: dict | None = None,
    ) -> None:
        self.execute_calls: list[tuple] = []  # (plan, volumes, limits)
        self.resume_calls: list[tuple] = []  # (interrupt_obj, approved, decision)
        self.execute_result = execute_result or {"run_id": "run-1", "status": "completed"}
        self.execute_interrupt = execute_interrupt
        self.resume_result = resume_result or {"run_id": "run-1", "status": "completed"}

    async def execute(self, plan, volumes, limits):
        self.execute_calls.append((plan, volumes, limits))
        if self.execute_interrupt is not None:
            from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

            raise VolumeHITLInterrupt(self.execute_interrupt)
        return self.execute_result

    async def resume(self, interrupt_obj, *, approved: bool, decision: str = ""):
        self.resume_calls.append((interrupt_obj, approved, decision))
        return self.resume_result


# ── 用例 1：构造扩展（守护）──────────────────────────────────────


async def test_constructor_backward_compatible_without_volume_pipeline():
    """阶段 3 构造扩展向后兼容：不带 volume_pipeline 参数构造零影响，
    既有 write_book 路径照常可用。
    （守护用例 RED 期 PASS 刻意：阶段 2 签名已满足本断言，阶段 3 新参数
    默认 None 不破坏既有行为）"""
    svc = _service()
    assert isinstance(svc, BookService)

    repo = AsyncMock()
    plan = _plan()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([], 0)
    svc2 = _service(repo=repo, outline_repo=outline_repo)

    result = await svc2.write_book(plan.id)

    assert result["status"] == "completed"


# ── 用例 2-3：write_book_volume 卷 planner 拆章 ──────────────────


async def test_write_book_volume_groups_chapters_by_volume_nodes():
    """有卷节点 → 卷 planner 按卷分组委托：outline 含 2 个 level=volume 节点
    + 各 2 个 level=chapter 子节点（parent_id=volume.id）→ volume_pipeline.execute
    恰一次，收到 plan/volumes/limits 参数：
    volumes = [{"volume_id": vol1.id, "chapters": [c1a, c1b]},
               {"volume_id": vol2.id, "chapters": [c2a, c2b]}]（sort_order 升序，
    与列表交错位置无关）；limits = 默认 BookLimits（请求 None → 项目级 None）。
    GREEN 契约：write_book_volume 存在 + 构造接受 volume_pipeline + _find_volumes
    分组正确（RED：构造 TypeError / 方法 AttributeError 先行）。"""
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outlines = _volumed_outline(plan, volumes=2, chapters_per_volume=2)
    vol1, c1a, vol2, c2a, c1b, c2b = outlines  # 交错返回顺序（刻意）
    outline_repo.list.return_value = (outlines, 6)
    pipeline = MockVolumePipeline(execute_result={"run_id": str(plan.id), "status": "completed"})
    svc = _service(repo=repo, outline_repo=outline_repo, volume_pipeline=pipeline)

    result = await svc.write_book_volume(plan.id)

    assert result["run_id"] == str(plan.id)
    assert result["status"] == "completed"
    assert len(pipeline.execute_calls) == 1  # 恰一次委托
    plan_arg, volumes, limits_arg = pipeline.execute_calls[0]
    assert plan_arg is plan  # 同一 WritingPlan 对象透传
    assert len(volumes) == 2
    assert volumes[0]["volume_id"] == vol1.id
    assert [c["outline_id"] for c in volumes[0]["chapters"]] == [c1a.id, c1b.id]
    assert volumes[1]["volume_id"] == vol2.id
    assert [c["outline_id"] for c in volumes[1]["chapters"]] == [c2a.id, c2b.id]
    assert isinstance(limits_arg, BookLimits)
    assert limits_arg.max_chapters == 100  # 默认 BookLimits 透传


async def test_write_book_volume_no_volume_nodes_single_volume():
    """无 level=volume 节点 → 整本书作为一卷：outline 全 level=chapter
    （直挂 root，parent_id=root_outline_id）→ volume_pipeline.execute 收到
    volumes = 1 卷 × 全部章（sort_order 升序）。
    GREEN 契约：_find_volumes 回退分支（RED：构造 TypeError 先行）。"""
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapters = _chapters(plan, 3)
    outline_repo.list.return_value = (chapters, 3)
    pipeline = MockVolumePipeline(execute_result={"run_id": str(plan.id), "status": "completed"})
    svc = _service(repo=repo, outline_repo=outline_repo, volume_pipeline=pipeline)

    result = await svc.write_book_volume(plan.id)

    assert result["status"] == "completed"
    assert len(pipeline.execute_calls) == 1
    _plan_arg, volumes, _limits = pipeline.execute_calls[0]
    assert len(volumes) == 1  # 整本书作为一卷
    assert [c["outline_id"] for c in volumes[0]["chapters"]] == [c.id for c in chapters]


# ── 用例 4：安全阀零委托 ─────────────────────────────────────────


async def test_write_book_volume_safety_valve_blocks_zero_delegation():
    """卷级入口安全阀（§5.2/D8 同语义）：任一目标章 execution_refs done →
    ChapterAlreadyWrittenError（消息含「该章已有内容，拒绝重跑」），
    volume_pipeline 零调用（一个章都不委托）。
    GREEN 契约：write_book_volume 预检复用 _check_content_written（RED：
    构造 TypeError 先行）。"""
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    c1 = _outline(parent_id=plan.root_outline_id, chapter_id=uuid.uuid4(), name="第一章")
    c2 = _outline(parent_id=plan.root_outline_id, chapter_id=uuid.uuid4(), name="第二章")
    outline_repo.list.return_value = ([c1, c2], 2)
    # 预置：c1 已执行完成
    plan.progress[str(c1.id)] = "done"
    plan.execution_refs[str(c1.id)] = "exec-1"
    pipeline = MockVolumePipeline()
    svc = _service(repo=repo, outline_repo=outline_repo, volume_pipeline=pipeline)

    with pytest.raises(ChapterAlreadyWrittenError, match="该章已有内容，拒绝重跑"):
        await svc.write_book_volume(plan.id)

    assert pipeline.execute_calls == []  # 零委托


# ── 用例 5-6：write_book_volume 状态落库 ─────────────────────────


async def test_write_book_volume_hitl_interrupt_waiting_hitl_persisted():
    """volume_pipeline.execute 抛 VolumeHITLInterrupt → write_book_volume 捕获：
    plan.status="waiting_hitl" + plan.hitl_payload=interrupt.payload 落库
    （update_writing_plan 被调用），返回 {"run_id", "status": "waiting_hitl"}
    （中断不传播）。
    GREEN 契约：except VolumeHITLInterrupt 分支（RED：构造 TypeError 先行；
    模块未实现时 Mock 内 lazy import → ImportError FAILED）。"""
    payload = {
        "question": "确认继续下一卷？",
        "volume_index": 1,
        "total_volumes": 2,
        "progress": {"c1": "done"},
    }
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outlines = _volumed_outline(plan, volumes=2, chapters_per_volume=2)
    outline_repo.list.return_value = (outlines, 6)
    pipeline = MockVolumePipeline(execute_interrupt=payload)
    svc = _service(repo=repo, outline_repo=outline_repo, volume_pipeline=pipeline)

    result = await svc.write_book_volume(plan.id)

    assert result["run_id"] == str(plan.id)
    assert result["status"] == "waiting_hitl"
    assert plan.status == "waiting_hitl"  # waiting_hitl 落库
    assert plan.hitl_payload == payload
    repo.update_writing_plan.assert_awaited()


async def test_write_book_volume_completed_persisted():
    """volume_pipeline.execute 正常返回 → plan.status="completed" 落库
    （update_writing_plan 被调用），返回 {"run_id", "status": "completed"}。
    GREEN 契约：正常委托路径状态落库（RED：构造 TypeError 先行）。"""
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outlines = _volumed_outline(plan, volumes=1, chapters_per_volume=2)
    outline_repo.list.return_value = (outlines, 3)
    pipeline = MockVolumePipeline(execute_result={"run_id": str(plan.id), "status": "completed"})
    svc = _service(repo=repo, outline_repo=outline_repo, volume_pipeline=pipeline)

    result = await svc.write_book_volume(plan.id)

    assert result["run_id"] == str(plan.id)
    assert result["status"] == "completed"
    assert plan.status == "completed"
    repo.update_writing_plan.assert_awaited()


# ── 用例 7-9：confirm_run 卷级 HITL 确认 ─────────────────────────


async def test_confirm_run_waiting_hitl_resumes():
    """plan.status=waiting_hitl → confirm_run 调 volume_pipeline.resume：
    记录 (interrupt_obj, approved=True, decision="继续下一卷")；interrupt_obj 由
    plan.hitl_payload 重建（.payload == 存储 payload）；返回 resume
    结果状态。
    GREEN 契约：confirm_run 存在 + resume 委派（RED：构造 TypeError /
    方法 AttributeError 先行）。"""
    payload = {
        "question": "确认继续下一卷？",
        "volume_index": 1,
        "total_volumes": 2,
    }
    repo = AsyncMock()
    plan = _plan(
        status="waiting_hitl",
        limits={"max_chapters": 1, "max_agent_calls": 1},
        hitl_payload=payload,
    )
    repo.get_writing_plan.return_value = plan
    pipeline = MockVolumePipeline(resume_result={"run_id": str(plan.id), "status": "running"})
    svc = _service(repo=repo, volume_pipeline=pipeline)

    result = await svc.confirm_run(str(plan.id), approved=True, decision="继续下一卷")

    assert result["status"] in {"running", "waiting_hitl", "completed"}
    assert len(pipeline.resume_calls) == 1
    interrupt_obj, approved, decision = pipeline.resume_calls[0]
    assert approved is True
    assert decision == "继续下一卷"
    assert getattr(interrupt_obj, "payload", None) == payload  # 由 hitl_payload 重建


async def test_confirm_run_non_waiting_hitl_rejected():
    """plan.status=completed → confirm_run 抛 ValueError（消息含
    「未处于等待确认状态」，API 映射 422），resume 零调用。
    GREEN 契约：非 waiting_hitl 拒绝先于 resume（RED：构造 TypeError 先行）。"""
    payload = {
        "question": "确认继续下一卷？",
        "volume_index": 1,
        "total_volumes": 2,
    }
    repo = AsyncMock()
    plan = _plan(
        status="completed",
        limits={"max_chapters": 1, "max_agent_calls": 1},
        hitl_payload=payload,
    )
    repo.get_writing_plan.return_value = plan
    pipeline = MockVolumePipeline()
    svc = _service(repo=repo, volume_pipeline=pipeline)

    with pytest.raises(ValueError, match="未处于等待确认状态"):
        await svc.confirm_run(str(plan.id), approved=True)

    assert pipeline.resume_calls == []  # 拒绝，resume 零调用


async def test_confirm_run_missing_plan_raises():
    """plan 查无 → confirm_run 抛 ValueError（消息含「不存在」，API 映射 404），
    resume 零调用。
    GREEN 契约：查无分支（RED：构造 TypeError 先行）。"""
    repo = AsyncMock()
    repo.get_writing_plan.return_value = None
    pipeline = MockVolumePipeline()
    svc = _service(repo=repo, volume_pipeline=pipeline)

    with pytest.raises(ValueError, match="不存在"):
        await svc.confirm_run(str(uuid.uuid4()), approved=True)

    assert pipeline.resume_calls == []


# ── 用例 10：get_status 扩展 ─────────────────────────────────────


async def test_get_status_waiting_hitl_extended_keys():
    """get_status 扩展：plan.status=waiting_hitl → 返回顶层键
    waiting_hitl: True + hitl_payload: dict（= interrupt payload）。
    RED 预期：阶段 2 get_status 无这两个键 → KeyError（FAILED 非 ERROR）。"""
    payload = {
        "question": "确认继续下一卷？",
        "volume_index": 1,
        "total_volumes": 2,
    }
    repo = AsyncMock()
    plan = _plan(
        status="waiting_hitl",
        limits={"max_chapters": 1, "max_agent_calls": 1},
        hitl_payload=payload,
        progress={"c1": "done"},
        execution_refs={"c1": "exec-1"},
    )
    repo.get_writing_plan.return_value = plan
    svc = _service(repo=repo)

    status = await svc.get_status(str(plan.id))

    assert status is not None
    assert status["waiting_hitl"] is True
    assert status["hitl_payload"] == payload


async def test_get_status_counters_keys_unchanged():
    """get_status 扩展向后兼容：counters 既有 7 键
    （max_chapters/max_agent_calls/max_tokens/tokens_used/tokens_warning/
    agent_calls/chapters_written）不变——阶段 3 扩展只增顶层
    waiting_hitl/hitl_payload，不动 counters。
    （守护用例 RED 期 PASS 刻意：阶段 2 get_status 已返回 7 键）"""
    repo = AsyncMock()
    plan = _plan(
        limits={
            "max_chapters": 1,
            "max_agent_calls": 1,
            "max_tokens": 200_000,
            "tokens_used": 12_345,
            "tokens_warning": True,
        },
        progress={"c1": "done"},
        execution_refs={"c1": "exec-1"},
        status="completed",
    )
    repo.get_writing_plan.return_value = plan
    svc = _service(repo=repo)

    status = await svc.get_status(str(plan.id))

    assert status is not None
    assert set(status["counters"].keys()) == {
        "max_chapters",
        "max_agent_calls",
        "max_tokens",
        "tokens_used",
        "tokens_warning",
        "agent_calls",
        "chapters_written",
    }
# ════ F44 阶段3 coverage-gap 补测（规则 1j，2026-08-17：代码已存在直接通过）════
# CI coverage-backend TOTAL 98% < 98.5%（book_service.py 93% miss）——补防御分支。


class TestCoverageGapService:
    """book_service.py 阶段3 防御分支补测（规则 1j：直接通过，非 RED）。"""

    @pytest.mark.asyncio
    async def test_write_book_volume_pipeline_unconfigured_raises(self) -> None:
        """write_book_volume volume_pipeline 未配置 → ValueError（L246）。"""
        repo = AsyncMock()
        plan = _plan(root_outline_id=uuid.uuid4())
        repo.get_writing_plan.return_value = plan
        outline_repo = AsyncMock()
        outline_repo.list.return_value = (_chapters(plan, 1), 1)
        svc = _service(repo=repo, outline_repo=outline_repo)  # 不注入 volume_pipeline

        with pytest.raises(ValueError, match="volume_pipeline 未配置"):
            await svc.write_book_volume(plan.id)

    @pytest.mark.asyncio
    async def test_confirm_run_pipeline_unconfigured_raises(self) -> None:
        """confirm_run volume_pipeline 未配置 → ValueError（L295）。"""
        repo = AsyncMock()
        plan = _plan(status="waiting_hitl", hitl_payload={"question": "x"})
        repo.get_writing_plan.return_value = plan
        svc = _service(repo=repo)  # 不注入 volume_pipeline

        with pytest.raises(ValueError, match="volume_pipeline 未配置"):
            await svc.confirm_run(str(plan.id), approved=True)

    @pytest.mark.asyncio
    async def test_confirm_run_resume_second_interrupt_updates_payload(self) -> None:
        """confirm_run resume 再抛 VolumeHITLInterrupt → 更新 hitl_payload + waiting_hitl
        （L304-310）。"""
        payload2 = {"question": "下一卷边界", "volume_index": 2}
        repo = AsyncMock()
        plan = _plan(status="waiting_hitl", hitl_payload={"question": "第一卷"})
        repo.get_writing_plan.return_value = plan

        class _ResumePipeline:
            async def resume(self, interrupt_obj, *, approved, decision):
                from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

                raise VolumeHITLInterrupt(payload2)

        pipeline = _ResumePipeline()
        svc = _service(repo=repo, volume_pipeline=pipeline)

        result = await svc.confirm_run(str(plan.id), approved=True)
        assert result["status"] == "waiting_hitl"
        assert plan.hitl_payload == payload2
        repo.update_writing_plan.assert_awaited()

    @pytest.mark.asyncio
    async def test_check_content_written_content_checker_true(self) -> None:
        """_check_content_written content_checker 返回 True → 安全阀命中（L374/434）。"""

        repo = AsyncMock()
        plan = _plan(root_outline_id=uuid.uuid4())
        repo.get_writing_plan.return_value = plan
        outline_repo = AsyncMock()
        chapter = _outline(chapter_id=uuid.uuid4())
        outline_repo.list.return_value = ([chapter], 1)
        content_checker = AsyncMock(return_value=True)
        svc = _service(
            repo=repo,
            outline_repo=outline_repo,
            content_checker=content_checker,
            volume_pipeline=AsyncMock(),
        )

        with pytest.raises(ChapterAlreadyWrittenError, match="该章已有内容，拒绝重跑"):
            await svc.write_book_volume(plan.id)
        content_checker.assert_awaited_once_with(chapter.chapter_id)

    @pytest.mark.asyncio
    async def test_check_chapter_written_dict_content_checker_true(self) -> None:
        """_check_chapter_written dict 形态 content_checker True → 安全阀（L231-232）。"""

        repo = AsyncMock()
        plan = _plan(root_outline_id=uuid.uuid4())
        repo.get_writing_plan.return_value = plan
        outline_repo = AsyncMock()
        chapter = _outline(chapter_id=uuid.uuid4())
        outline_repo.list.return_value = ([chapter], 1)
        content_checker = AsyncMock(return_value=True)
        svc = _service(
            repo=repo,
            outline_repo=outline_repo,
            content_checker=content_checker,
            volume_pipeline=AsyncMock(),
        )

        with pytest.raises(ChapterAlreadyWrittenError, match="该章已有内容，拒绝重跑"):
            await svc.write_book_volume(plan.id)
        content_checker.assert_awaited_once_with(chapter.chapter_id)
class TestCoverageGapService2:
    """book_service.py 二轮补测：write_book_volume 防御分支。"""

    @pytest.mark.asyncio
    async def test_write_book_volume_plan_missing_raises(self) -> None:
        """write_book_volume 计划不存在 → ValueError（L228）。"""
        repo = AsyncMock()
        repo.get_writing_plan.return_value = None
        svc = _service(repo=repo, volume_pipeline=AsyncMock())

        with pytest.raises(ValueError, match="计划不存在"):
            await svc.write_book_volume(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_write_book_volume_project_extra_limits(self) -> None:
        """write_book_volume project_config_getter 分支：项目级上限生效（L231-232）。"""
        from types import SimpleNamespace

        repo = AsyncMock()
        plan = _plan(root_outline_id=uuid.uuid4())
        repo.get_writing_plan.return_value = plan
        outline_repo = AsyncMock()
        outline_repo.list.return_value = ([_outline(chapter_id=uuid.uuid4())], 1)
        project_config_getter = AsyncMock(
            return_value=SimpleNamespace(extra={"book_max_chapters": 7})
        )
        pipeline = MockVolumePipeline(
            execute_result={"run_id": str(plan.id), "status": "completed"}
        )
        svc = _service(
            repo=repo,
            outline_repo=outline_repo,
            project_config_getter=project_config_getter,
            volume_pipeline=pipeline,
        )

        result = await svc.write_book_volume(plan.id)
        assert result["status"] == "completed"
        assert plan.limits.get("max_chapters") == 7  # 项目级 extra 覆盖默认

    @pytest.mark.asyncio
    async def test_find_volumes_outline_repo_none_returns_empty(self) -> None:
        """_find_volumes outline_repo None → 空列表（L374，镜像 _find_chapters 防御）。"""
        repo = AsyncMock()
        plan = _plan(root_outline_id=uuid.uuid4())
        repo.get_writing_plan.return_value = plan
        svc = _service(  # outline_repo=None（覆盖默认 AsyncMock）
            repo=repo, outline_repo=None, volume_pipeline=AsyncMock()
        )

        volumes = await svc._find_volumes(plan)
        assert volumes == []
