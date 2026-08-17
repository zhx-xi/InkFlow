"""F44 阶段4 BookService 干预/续跑/摘要扩展单测（TDD RED 阶段，契约先行）。

权威来源：.hermes/plans/f44-stage4-contract.md §2（BookService 扩展）/§3.2
（resume 裁定锁定）/§5/§6（thread_id 列 + create_execution 扩展 execution_id/
thread_id）、spec §13.3 M10/M12（跨重启 resume / 回归摘要）。被测模块 =
domain/services/book_service.py（阶段 3 基座 + 阶段 4 扩展），只写测试不写实现
（RED 阶段）。

════════════════════════════════════════════════════════════════════
设计假设（阶段 4 GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

0. 【用例编号 ↔ 测试映射】1=构造守护 2=write_book_volume thread_id 传参+写回
   3=execution_store book:volume 记录 4=interrupt 分支 thread_id 写回
   5=无 execution_store 防御 6=intervene 运行不存在 7=非法 action
   8=pause running→paused 9=pause 非 running 拒绝 10=redirect skip
   11=redirect retry 12=redirect mark_failed 13=redirect done 拒绝
   14=redirect 非法 to 15=redirect target None 16=redirect target 未知
   17=intervene resume（§3.2 裁定） 18=edit brief 必填 19=edit done 拒绝
   20=edit outline_updater 未装配 21=edit 成功 22=resume_run 运行不存在
   23=resume_run 非 paused 拒绝 24=resume_run __interrupt__ → resume
   25=resume_run 再 interrupt → waiting_hitl 落库 26=resume_run 无 interrupt
   → execute 同 thread_id 续跑 27=get_summary 运行不存在→None 28=get_summary
   全量形态 29=checkpoint None 30=volume_pipeline None 31=confirm_run
   thread_id+update_status 32=confirm_run thread_id 兜底。

1. 【构造扩展 · 用例 1】新增可选关键字参数 execution_store: object | None = None
   （放最后，默认 None 向后兼容）——执行记录仓储鸭子（镜像 ExecutionStore：
   async create_execution(pipeline, project_id, *, thread_id, execution_id) /
   async update_status(execution_id, status)）。用例 1 = 守护（RED 期 PASS 刻意）。

2. 【write_book_volume 扩展 · 用例 2-5】：
   a. execute 前生成 thread_id = str(plan.id)（书级运行 ↔ 图 checkpoint 一一
      映射）；execute(plan, volumes, merged, thread_id=thread_id)。
   b. execution_store 落库（None 则跳过防御）：create_execution(pipeline=
      "book:volume", project_id=str(plan.project_id), thread_id=str(plan.id),
      execution_id=str(plan.id))（§6：书级运行执行记录 id 固定 = str(plan.id)）。
   c. 写回 plan.thread_id + 落库（VolumeHITLInterrupt 捕获分支与正常分支都写，
      用例 4/2 分别锁）。
   d. 返回 {"run_id": str(plan.id), "status": ...} 不变（兼容阶段 3 契约）。

3. 【intervene(run_id, *, action, target=None, to=None, payload=None) → dict
   · 用例 6-21】读 plan 不存在 → ValueError("运行不存在")（先于 action 校验）；
   action 非法（非 pause/resume/redirect/edit）→ ValueError("非法干预动作")。
   pause：仅 running 可暂停（waiting_hitl/completed → ValueError(
   "运行未处于可暂停状态")，用例 9 参数化）；paused + 落库 + 返回 {"run_id",
   "status": "paused"}（用例 8）。resume：§3.2 裁定锁定 = 状态校验（paused）+
   running + 落库 + 返回 {"run_id", "status": "running"}（用例 17；续跑逻辑在
   resume_run）。redirect（用例 10-16）：target 必填；to ∈ {skip, retry,
   mark_failed}（非法 → "非法干预动作"）；progress[target]=="done" → "已完成章
   不可干预"；skip → "skipped"+删 execution_refs；retry → "pending"+pop
   execution_refs；mark_failed → "failed"；返回含 diff {"target", "from", "to"}；
   target 不在 progress 且不在 outline → "干预目标不存在"（target=None 仅锁
   ValueError 类型，文案未定稿）。edit（用例 18-21）：payload.brief 必填（仅锁
   ValueError）；progress[target]=="done" → "已完成章不可干预"；outline_updater
   None → "大纲更新器未装配"；成功 → outline_updater(uuid.UUID(target), brief) +
   diff {"target", "before", "after", "diff"}（difflib.unified_diff 字符串；
   before 从 outline_repo.list 取节点 description）。

4. 【resume_run(run_id) → dict · 用例 22-26】跨重启续跑（§2 + §3.2 最终裁定：
   resume_run 承载完整续跑逻辑，可单测）：plan 查无 → "运行不存在"；
   plan.status != "paused" → "运行未处于可暂停状态"；thread_id 从 plan.thread_id
   读（跨重启）；get_checkpoint_state(thread_id) → 有 __interrupt__ →
   resume(VolumeHITLInterrupt(__interrupt__[0].value), approved=True,
   thread_id=thread_id)；resume 再抛 interrupt → waiting_hitl + hitl_payload
   落库（update_writing_plan）；无 __interrupt__ → 重新 _find_volumes +
   execute(plan, volumes, merged, thread_id=thread_id) 同 thread_id 续跑
   （Spike ⑥）。

5. 【get_summary(run_id) → dict | None · 用例 27-30】plan 查无 → None（API 404）；
   steps = [{index, outline_id, status, execution_id}] 从 progress/execution_refs
   派生（不含章名——渲染层补充）；counters = get_status 同构 7 键；返回 {run_id,
   status, progress, counters, steps, next}；next：有 get_checkpoint_state →
   {volume_index, total_volumes, finished, status}；checkpoint None /
   volume_pipeline None → {"finished": True}（防御分支）。

6. 【confirm_run 扩展 · 用例 31-32】resume 调用传 thread_id（读 plan.thread_id
   兜底 str(plan.id)）；成功后 execution_store.update_status(execution_id=
   str(plan.id), status=result.status)。

7. 【RED 预期形态】阶段 3 实现下本文件 = 34 failed, 1 passed（守护用例 1 PASS
   刻意）。失败形态地图 = TypeError×9（构造新参 execution_store/outline_updater
   未实现，deps-helper 显式传 → 落用例执行点非收集期）+ AttributeError×24
   （intervene/resume_run/get_summary 方法缺失）+ AssertionError×1（用例 5
   plan.thread_id 写回契约，阶段 3 不写 thread_id）。

【mock 策略】repo/outline_repo/execution_store/outline_updater 用 AsyncMock；
volume_pipeline 用 AsyncMock（execute/resume/get_checkpoint_state；返回必须带
"thread_id" 键——阶段 4 契约，陷阱③）；plan 用真实 WritingPlan（uuid.UUID(int=n)
小整数背书）；宽松取参 helper _call_arg（kwargs 优先位置回退）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService
from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

# ── helpers（镜像 test_book_service_volume.py 既有形态，本文件自带一份）─────

_PLAN_ID_ITER = iter(range(1000, 2000))


def _next_plan_id() -> uuid.UUID:
    """小整数背书的确定性计划 id（uuid.UUID(int=n)，避免真实 DB 轨 128 位溢出）。"""
    return uuid.UUID(int=next(_PLAN_ID_ITER))


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _plan(**overrides) -> WritingPlan:
    base = dict(
        id=_next_plan_id(),
        project_id=_pid(),
        title="测试计划",
        status="ready",
        root_outline_id=uuid.uuid4(),
        character_ids=[],
        # limits 类型 dict[str, int | bool]——给全 5 键避免缺键（陷阱②）
        limits={
            "max_chapters": 1,
            "max_agent_calls": 1,
            "max_tokens": 200_000,
            "tokens_used": 0,
            "tokens_warning": False,
        },
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return WritingPlan(**base)


def _plan_repo(**overrides) -> tuple[AsyncMock, WritingPlan]:
    """构造 plan + 预置 get_writing_plan 的 repo（一步到位，压缩用例样板）。"""
    repo = AsyncMock()
    plan = _plan(**overrides)
    repo.get_writing_plan.return_value = plan
    return repo, plan


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
    """卷结构 outline 列表，刻意交错返回（卷 planner 按 parent_id/sort_order 分组）。"""
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
    """构造 BookService 全部 mock 依赖（可覆盖；阶段 4 新参数 execution_store /
    outline_updater 由用例显式传入 → 阶段 3 构造不接受 → TypeError → RED）。"""
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


def _call_arg(call, name: str, names: list[str], default=None):
    """宽松取参：kwargs 优先、位置回退（镜像契约 helper 惯例，防位置传参破坏断言）。"""
    if name in call.kwargs:
        return call.kwargs[name]
    try:
        idx = names.index(name)
    except ValueError:
        return default
    if len(call.args) > idx:
        return call.args[idx]
    return default


# ── 用例 1：构造扩展（守护）──────────────────────────────────────


@pytest.mark.asyncio
class TestConstructorGuard:
    async def test_constructor_backward_compatible_without_execution_store(self):
        """构造向后兼容守护：不带 execution_store 参数构造零影响（RED 期 PASS 刻意，
        阶段 3 签名已满足；GREEN 契约 = 新参数默认 None 不破坏既有行为）。"""
        svc = _service()
        assert isinstance(svc, BookService)

        repo, plan = _plan_repo()
        outline_repo = AsyncMock()
        outline_repo.list.return_value = ([], 0)
        svc2 = _service(repo=repo, outline_repo=outline_repo)

        result = await svc2.write_book(plan.id)

        assert result["status"] == "completed"


# ── 用例 2-5：write_book_volume thread_id / execution_store 落库 ──


@pytest.mark.asyncio
class TestWriteBookVolumeStage4:
    async def test_write_book_volume_executes_with_thread_id_and_persists(self):
        """正常分支：execute 收到 thread_id=str(plan.id)；plan.thread_id 写回
        落库；返回形态不变。GREEN：execute(..., thread_id=...)（RED：构造
        execution_store TypeError 先行）。"""
        repo, plan = _plan_repo(root_outline_id=uuid.uuid4())
        outline_repo = AsyncMock()
        outlines = _volumed_outline(plan, volumes=2, chapters_per_volume=2)
        outline_repo.list.return_value = (outlines, 6)
        pipeline = AsyncMock()
        pipeline.execute.return_value = {
            "run_id": str(plan.id),
            "status": "completed",
            "thread_id": str(plan.id),  # 阶段 4 契约：execute 返回带 thread_id 键
        }
        execution_store = AsyncMock()
        svc = _service(
            repo=repo,
            outline_repo=outline_repo,
            volume_pipeline=pipeline,
            execution_store=execution_store,
        )

        result = await svc.write_book_volume(plan.id)

        assert result["run_id"] == str(plan.id)
        assert result["status"] == "completed"
        pipeline.execute.assert_awaited_once()
        call = pipeline.execute.await_args
        assert call.args[0] is plan  # 同一 WritingPlan 对象透传
        assert isinstance(call.args[2], BookLimits)
        assert call.kwargs.get("thread_id") == str(plan.id)
        assert plan.thread_id == str(plan.id)  # thread_id 写回
        repo.update_writing_plan.assert_awaited()

    async def test_write_book_volume_create_execution_record(self):
        """execution_store 落库（§6 裁定）：create_execution(pipeline="book:volume",
        project_id=str(plan.project_id), thread_id=str(plan.id),
        execution_id=str(plan.id)) 恰一次——书级运行执行记录 id 固定 = str(plan.id)。
        RED：构造 execution_store TypeError 先行。"""
        repo, plan = _plan_repo(root_outline_id=uuid.uuid4())
        outline_repo = AsyncMock()
        outlines = _volumed_outline(plan, volumes=1, chapters_per_volume=2)
        outline_repo.list.return_value = (outlines, 3)
        pipeline = AsyncMock()
        pipeline.execute.return_value = {
            "run_id": str(plan.id),
            "status": "completed",
            "thread_id": str(plan.id),
        }
        execution_store = AsyncMock()
        svc = _service(
            repo=repo,
            outline_repo=outline_repo,
            volume_pipeline=pipeline,
            execution_store=execution_store,
        )

        await svc.write_book_volume(plan.id)

        execution_store.create_execution.assert_awaited_once()
        call = execution_store.create_execution.await_args
        assert (
            _call_arg(call, "pipeline", ["pipeline", "project_id", "chapter_id"]) == "book:volume"
        )
        assert _call_arg(call, "project_id", ["pipeline", "project_id", "chapter_id"]) == str(
            plan.project_id
        )
        assert call.kwargs.get("thread_id") == str(plan.id)
        assert call.kwargs.get("execution_id") == str(plan.id)

    async def test_write_book_volume_interrupt_branch_persists_thread_id(self):
        """interrupt 捕获分支同样写回 plan.thread_id + execution_store 记录：
        execute 抛 interrupt → waiting_hitl + hitl_payload 落库 + thread_id 写回。
        RED：构造 execution_store TypeError 先行。"""
        payload = {"question": "确认继续下一卷？", "volume_index": 1, "total_volumes": 2}
        repo, plan = _plan_repo(root_outline_id=uuid.uuid4())
        outline_repo = AsyncMock()
        outlines = _volumed_outline(plan, volumes=2, chapters_per_volume=2)
        outline_repo.list.return_value = (outlines, 6)
        pipeline = AsyncMock()
        pipeline.execute.side_effect = VolumeHITLInterrupt(payload)
        execution_store = AsyncMock()
        svc = _service(
            repo=repo,
            outline_repo=outline_repo,
            volume_pipeline=pipeline,
            execution_store=execution_store,
        )

        result = await svc.write_book_volume(plan.id)

        assert result["status"] == "waiting_hitl"
        assert plan.status == "waiting_hitl"
        assert plan.hitl_payload == payload
        assert plan.thread_id == str(plan.id)  # interrupt 分支也写回
        repo.update_writing_plan.assert_awaited()
        execution_store.create_execution.assert_awaited_once()

    async def test_write_book_volume_thread_id_without_execution_store(self):
        """execution_store 缺省（None）防御：create_execution 跳过不崩溃，
        thread_id 写回照常。RED：阶段 3 不写 → AssertionError（thread_id None）。"""
        repo, plan = _plan_repo(root_outline_id=uuid.uuid4())
        outline_repo = AsyncMock()
        outlines = _volumed_outline(plan, volumes=1, chapters_per_volume=2)
        outline_repo.list.return_value = (outlines, 3)
        pipeline = AsyncMock()
        pipeline.execute.return_value = {
            "run_id": str(plan.id),
            "status": "completed",
            "thread_id": str(plan.id),
        }
        svc = _service(repo=repo, outline_repo=outline_repo, volume_pipeline=pipeline)

        result = await svc.write_book_volume(plan.id)

        assert result["status"] == "completed"
        assert plan.thread_id == str(plan.id)


# ── 用例 6-21：intervene 干预 API ────────────────────────────────


@pytest.mark.asyncio
class TestIntervene:
    async def test_intervene_run_not_found_raises(self):
        """读 plan → 不存在 → ValueError("运行不存在")（先于 action 校验；API 404）。
        RED：intervene 方法缺失 AttributeError 先行。"""
        repo = AsyncMock()
        repo.get_writing_plan.return_value = None
        svc = _service(repo=repo)

        with pytest.raises(ValueError, match="运行不存在"):
            await svc.intervene(str(uuid.uuid4()), action="pause")

    async def test_intervene_invalid_action_raises(self):
        """action 非法（非 pause/resume/redirect/edit）→ ValueError("非法干预动作")
        （API 422）。RED：intervene 方法缺失 AttributeError 先行。"""
        repo, plan = _plan_repo(status="running")
        svc = _service(repo=repo)

        with pytest.raises(ValueError, match="非法干预动作"):
            await svc.intervene(str(plan.id), action="bogus")

    async def test_intervene_pause_marks_paused(self):
        """pause：running → plan.status="paused" + 落库（update_writing_plan），
        返回 {"run_id", "status": "paused"}（恰 2 键）。"""
        repo, plan = _plan_repo(status="running")
        svc = _service(repo=repo)

        result = await svc.intervene(str(plan.id), action="pause")

        assert set(result.keys()) == {"run_id", "status"}
        assert result["run_id"] == str(plan.id)
        assert result["status"] == "paused"
        assert plan.status == "paused"
        repo.update_writing_plan.assert_awaited()

    @pytest.mark.parametrize("status", ["waiting_hitl", "completed"])
    async def test_intervene_pause_non_running_rejected(self, status):
        """pause：非 running（waiting_hitl/completed）→ ValueError(
        "运行未处于可暂停状态")，零落库（waiting_hitl 走 confirm 通道）。"""
        repo, plan = _plan_repo(status=status)
        svc = _service(repo=repo)

        with pytest.raises(ValueError, match="运行未处于可暂停状态"):
            await svc.intervene(str(plan.id), action="pause")

        repo.update_writing_plan.assert_not_awaited()

    async def test_intervene_redirect_skip(self):
        """redirect skip：progress[target]="skipped" + execution_refs 删该章 +
        落库；diff {"target", "from": 原 status, "to": "skipped"}。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(
            status="running", progress={target: "in_progress"}, execution_refs={target: "exec-1"}
        )
        svc = _service(repo=repo)

        result = await svc.intervene(str(plan.id), action="redirect", target=target, to="skip")

        assert plan.progress[target] == "skipped"
        assert target not in plan.execution_refs
        assert result["status"] == "running"
        assert result["diff"] == {"target": target, "from": "in_progress", "to": "skipped"}
        repo.update_writing_plan.assert_awaited()

    async def test_intervene_redirect_retry(self):
        """redirect retry：progress[target]="pending" + execution_refs.pop 该章 +
        落库；diff from 原 status。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(
            status="running", progress={target: "failed"}, execution_refs={target: "exec-1"}
        )
        svc = _service(repo=repo)

        result = await svc.intervene(str(plan.id), action="redirect", target=target, to="retry")

        assert plan.progress[target] == "pending"
        assert target not in plan.execution_refs
        assert result["diff"] == {"target": target, "from": "failed", "to": "pending"}
        repo.update_writing_plan.assert_awaited()

    async def test_intervene_redirect_mark_failed(self):
        """redirect mark_failed：progress[target]="failed" + 落库；
        diff {"target", "from", "to": "failed"}。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={target: "in_progress"})
        svc = _service(repo=repo)

        result = await svc.intervene(
            str(plan.id), action="redirect", target=target, to="mark_failed"
        )

        assert plan.progress[target] == "failed"
        assert result["diff"] == {"target": target, "from": "in_progress", "to": "failed"}
        repo.update_writing_plan.assert_awaited()

    async def test_intervene_redirect_done_rejected(self):
        """redirect：目标章 progress=="done" → ValueError("已完成章不可干预")
        （spec §7 边界 12，API 422），零落库。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={target: "done"})
        svc = _service(repo=repo)

        with pytest.raises(ValueError, match="已完成章不可干预"):
            await svc.intervene(str(plan.id), action="redirect", target=target, to="skip")

        repo.update_writing_plan.assert_not_awaited()

    @pytest.mark.parametrize("to", ["nuke", None])
    async def test_intervene_redirect_invalid_to_rejected(self, to):
        """redirect：to 非法（∉ {skip, retry, mark_failed}，含 None）→
        ValueError("非法干预动作")，零落库。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={target: "in_progress"})
        svc = _service(repo=repo)

        with pytest.raises(ValueError, match="非法干预动作"):
            await svc.intervene(str(plan.id), action="redirect", target=target, to=to)

        repo.update_writing_plan.assert_not_awaited()

    async def test_intervene_redirect_target_none_rejected(self):
        """redirect：target 缺省（None）→ 拒绝（仅锁 ValueError 类型；具体文案
        父侧未定稿——target 必填与「干预目标不存在」判定域重叠）。"""
        repo, plan = _plan_repo(status="running", progress={"c1": "in_progress"})
        svc = _service(repo=repo)

        with pytest.raises(ValueError):
            await svc.intervene(str(plan.id), action="redirect", to="skip")

        repo.update_writing_plan.assert_not_awaited()

    async def test_intervene_redirect_target_unknown_rejected(self):
        """redirect：target 不在 progress 且不在 outline（outline_repo.list 无该
        节点）→ ValueError("干预目标不存在")（API 422），零落库。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={"c1": "in_progress"})
        outline_repo = AsyncMock()
        outline_repo.list.return_value = ([_outline(name="另一章")], 1)  # 无 target 节点
        svc = _service(repo=repo, outline_repo=outline_repo)

        with pytest.raises(ValueError, match="干预目标不存在"):
            await svc.intervene(str(plan.id), action="redirect", target=target, to="skip")

        repo.update_writing_plan.assert_not_awaited()

    async def test_intervene_resume_paused_marks_running(self):
        """intervene(resume)：§3.2 裁定锁定 = 状态校验（paused）+ running + 落库 +
        返回 {"run_id", "status": "running"}——续跑逻辑在 resume_run（用例 22-26）。"""
        repo, plan = _plan_repo(status="paused")
        svc = _service(repo=repo)

        result = await svc.intervene(str(plan.id), action="resume")

        assert set(result.keys()) == {"run_id", "status"}
        assert result["run_id"] == str(plan.id)
        assert result["status"] == "running"
        assert plan.status == "running"
        repo.update_writing_plan.assert_awaited()

    @pytest.mark.parametrize("payload", [None, {}])
    async def test_intervene_edit_requires_brief(self, payload):
        """edit：payload.brief 必填（缺失/空 payload）→ ValueError（仅锁类型，
        文案父侧未定稿），outline_updater 零调用。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={target: "in_progress"})
        outline_updater = AsyncMock()
        svc = _service(repo=repo, outline_updater=outline_updater)

        with pytest.raises(ValueError):
            await svc.intervene(str(plan.id), action="edit", target=target, payload=payload)

        outline_updater.assert_not_awaited()

    async def test_intervene_edit_done_rejected(self):
        """edit：目标章 progress=="done" → ValueError("已完成章不可干预")
        （API 422），outline_updater 零调用。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={target: "done"})
        outline_updater = AsyncMock()
        svc = _service(repo=repo, outline_updater=outline_updater)

        with pytest.raises(ValueError, match="已完成章不可干预"):
            await svc.intervene(
                str(plan.id), action="edit", target=target, payload={"brief": "新梗概"}
            )

        outline_updater.assert_not_awaited()

    async def test_intervene_edit_without_outline_updater_rejected(self):
        """edit：outline_updater 未装配（默认 None）→ ValueError("大纲更新器未装配")
        ——父侧裁定避免改 outline_repo 协议面，domain 层零框架。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={target: "in_progress"})
        svc = _service(repo=repo)  # 不注入 outline_updater

        with pytest.raises(ValueError, match="大纲更新器未装配"):
            await svc.intervene(
                str(plan.id), action="edit", target=target, payload={"brief": "新梗概"}
            )

    async def test_intervene_edit_success_updates_outline(self):
        """edit 成功：outline_updater(uuid.UUID(target), "新梗概") 被调；diff
        {"target", "before"（outline_repo.list 取旧 description）, "after",
        "diff"（unified_diff 字符串）}；status 不变。RED：构造 outline_updater
        TypeError 先行。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={target: "in_progress"})
        outline_repo = AsyncMock()
        outline_repo.list.return_value = ([_outline(id=uuid.UUID(target), description="旧梗概")], 1)
        outline_updater = AsyncMock(return_value=None)
        svc = _service(repo=repo, outline_repo=outline_repo, outline_updater=outline_updater)

        result = await svc.intervene(
            str(plan.id), action="edit", target=target, payload={"brief": "新梗概"}
        )

        outline_updater.assert_awaited_once()
        call = outline_updater.await_args
        assert _call_arg(call, "outline_id", ["outline_id", "description"]) == uuid.UUID(target)
        assert _call_arg(call, "description", ["outline_id", "description"]) == "新梗概"
        assert set(result["diff"].keys()) == {"target", "before", "after", "diff"}
        assert result["diff"]["target"] == target
        assert result["diff"]["before"] == "旧梗概"
        assert result["diff"]["after"] == "新梗概"
        assert isinstance(result["diff"]["diff"], str)
        assert "旧梗概" in result["diff"]["diff"]  # unified_diff 含 -旧行 +新行
        assert "新梗概" in result["diff"]["diff"]
        assert result["status"] == "running"


# ── 用例 22-26：resume_run 跨重启续跑 ─────────────────────────────


@pytest.mark.asyncio
class TestResumeRun:
    async def test_resume_run_plan_missing_raises(self):
        """plan 查无 → ValueError("运行不存在")（镜像 confirm_run 语义；API 404）。
        RED：resume_run 方法缺失 AttributeError 先行。"""
        repo = AsyncMock()
        repo.get_writing_plan.return_value = None
        svc = _service(repo=repo)

        with pytest.raises(ValueError, match="运行不存在"):
            await svc.resume_run(str(uuid.uuid4()))

    async def test_resume_run_non_paused_rejected(self):
        """plan.status != "paused" → ValueError("运行未处于可暂停状态")，
        pipeline.execute/resume 零调用。"""
        repo, plan = _plan_repo(status="completed")
        pipeline = AsyncMock()
        svc = _service(repo=repo, volume_pipeline=pipeline)

        with pytest.raises(ValueError, match="运行未处于可暂停状态"):
            await svc.resume_run(str(plan.id))

        pipeline.execute.assert_not_awaited()
        pipeline.resume.assert_not_awaited()

    async def test_resume_run_pending_interrupt_resumes(self):
        """有 pending __interrupt__：get_checkpoint_state(plan.thread_id) → 非空 →
        pipeline.resume(VolumeHITLInterrupt(__interrupt__[0].value), approved=True,
        thread_id=plan.thread_id)——thread_id 从 plan.thread_id 读（跨重启）。
        RED：resume_run 方法缺失 AttributeError 先行。"""
        payload = {"question": "确认继续下一卷？", "volume_index": 1, "total_volumes": 2}
        repo, plan = _plan_repo(status="paused", thread_id="t-restart-1")
        pipeline = AsyncMock()
        pipeline.get_checkpoint_state.return_value = {
            "__interrupt__": [SimpleNamespace(value=payload)]
        }
        pipeline.resume.return_value = {
            "run_id": str(plan.id),
            "status": "completed",
            "thread_id": "t-restart-1",
        }
        svc = _service(repo=repo, volume_pipeline=pipeline)

        result = await svc.resume_run(str(plan.id))

        pipeline.get_checkpoint_state.assert_awaited_once_with("t-restart-1")
        pipeline.resume.assert_awaited_once()
        call = pipeline.resume.await_args
        assert isinstance(call.args[0], VolumeHITLInterrupt)
        assert call.args[0].payload == payload  # 由 checkpoint __interrupt__ 值重建
        assert call.kwargs.get("approved") is True
        assert call.kwargs.get("thread_id") == "t-restart-1"
        assert result["status"] == "completed"

    async def test_resume_run_resume_interrupt_again_persists_waiting_hitl(self):
        """resume 再抛 VolumeHITLInterrupt → waiting_hitl + hitl_payload 落库
        （update_writing_plan），返回 {"run_id", "status": "waiting_hitl"}。
        RED：resume_run 方法缺失 AttributeError 先行。"""
        payload = {"question": "确认继续下一卷？", "volume_index": 1, "total_volumes": 2}
        payload2 = {"question": "下一卷边界", "volume_index": 2, "total_volumes": 2}
        repo, plan = _plan_repo(status="paused", thread_id="t-restart-1")
        pipeline = AsyncMock()
        pipeline.get_checkpoint_state.return_value = {
            "__interrupt__": [SimpleNamespace(value=payload)]
        }
        pipeline.resume.side_effect = VolumeHITLInterrupt(payload2)
        svc = _service(repo=repo, volume_pipeline=pipeline)

        result = await svc.resume_run(str(plan.id))

        assert result["status"] == "waiting_hitl"
        assert result.get("run_id") == str(plan.id)
        assert plan.status == "waiting_hitl"
        assert plan.hitl_payload == payload2
        repo.update_writing_plan.assert_awaited()

    async def test_resume_run_no_interrupt_re_executes(self):
        """无 __interrupt__（task 被 cancel 停在普通 superstep）→ 重新 _find_volumes
        + pipeline.execute(plan, volumes, merged, thread_id=plan.thread_id) 同
        thread_id 续跑（Spike ⑥）。RED：resume_run 方法缺失 AttributeError 先行。"""
        repo, plan = _plan_repo(
            status="paused", thread_id="t-restart-2", root_outline_id=uuid.uuid4()
        )
        outline_repo = AsyncMock()
        chapters = _chapters(plan, 2)
        outline_repo.list.return_value = (chapters, 2)
        pipeline = AsyncMock()
        pipeline.get_checkpoint_state.return_value = {
            "volume_index": 1,
            "total_volumes": 2,
            "finished": False,
            "status": "running",
        }
        pipeline.execute.return_value = {
            "run_id": str(plan.id),
            "status": "completed",
            "thread_id": "t-restart-2",
        }
        svc = _service(repo=repo, outline_repo=outline_repo, volume_pipeline=pipeline)

        result = await svc.resume_run(str(plan.id))

        pipeline.get_checkpoint_state.assert_awaited_once_with("t-restart-2")
        pipeline.execute.assert_awaited_once()
        call = pipeline.execute.await_args
        assert call.args[0] is plan
        assert len(call.args[1]) == 1  # 无卷节点 → 整本书一卷
        assert isinstance(call.args[2], BookLimits)
        assert call.kwargs.get("thread_id") == "t-restart-2"
        assert result["status"] == "completed"


# ── 用例 27-30：get_summary 回归摘要 ──────────────────────────────


@pytest.mark.asyncio
class TestGetSummary:
    async def test_get_summary_plan_missing_returns_none(self):
        """plan 查无 → None（API 404）。
        RED：get_summary 方法缺失 AttributeError 先行。"""
        repo = AsyncMock()
        repo.get_writing_plan.return_value = None
        svc = _service(repo=repo)

        result = await svc.get_summary(str(uuid.uuid4()))

        assert result is None

    async def test_get_summary_full_shape(self):
        """全量形态：{run_id, status, progress, counters(7 键同构), steps(
        [{index, outline_id, status, execution_id}] 派生), next(checkpoint 状态)}；
        get_checkpoint_state 用 plan.thread_id。RED：get_summary 缺失先行。"""
        oid1, oid2 = str(uuid.uuid4()), str(uuid.uuid4())
        repo, plan = _plan_repo(
            status="waiting_hitl",
            thread_id="t-summary-1",
            limits={
                "max_chapters": 1,
                "max_agent_calls": 1,
                "max_tokens": 200_000,
                "tokens_used": 12_345,
                "tokens_warning": True,
            },
            progress={oid1: "done", oid2: "in_progress"},
            execution_refs={oid1: "exec-1"},
        )
        pipeline = AsyncMock()
        pipeline.get_checkpoint_state.return_value = {
            "volume_index": 1,
            "total_volumes": 2,
            "finished": False,
            "status": "running",
        }
        svc = _service(repo=repo, volume_pipeline=pipeline)

        result = await svc.get_summary(str(plan.id))

        assert result is not None
        assert result["run_id"] == str(plan.id)
        assert result["status"] == "waiting_hitl"
        assert result["progress"] == plan.progress
        assert set(result["counters"].keys()) == {
            "max_chapters",
            "max_agent_calls",
            "max_tokens",
            "tokens_used",
            "tokens_warning",
            "agent_calls",
            "chapters_written",
        }
        assert result["counters"]["agent_calls"] == 1
        assert result["counters"]["chapters_written"] == 1
        assert result["counters"]["tokens_used"] == 12_345
        assert result["steps"] == [
            {"index": 0, "outline_id": oid1, "status": "done", "execution_id": "exec-1"},
            {"index": 1, "outline_id": oid2, "status": "in_progress", "execution_id": None},
        ]
        assert result["next"]["volume_index"] == 1
        assert result["next"]["total_volumes"] == 2
        assert result["next"]["finished"] is False
        pipeline.get_checkpoint_state.assert_awaited_once_with("t-summary-1")

    async def test_get_summary_checkpoint_none_next_finished(self):
        """get_checkpoint_state 返回 None（无 checkpoint）→ next ==
        {"finished": True}。RED：get_summary 方法缺失 AttributeError 先行。"""
        repo, plan = _plan_repo(
            status="paused",
            thread_id="t-summary-2",
            progress={"c1": "done"},
            execution_refs={"c1": "exec-1"},
        )
        pipeline = AsyncMock()
        pipeline.get_checkpoint_state.return_value = None
        svc = _service(repo=repo, volume_pipeline=pipeline)

        result = await svc.get_summary(str(plan.id))

        assert result is not None
        assert result["next"] == {"finished": True}

    async def test_get_summary_pipeline_none_next_finished(self):
        """volume_pipeline 未配置（None，防御分支）→ next == {"finished": True}，
        不崩溃。RED：get_summary 方法缺失 AttributeError 先行。"""
        repo, plan = _plan_repo(status="completed", progress={}, execution_refs={})
        svc = _service(repo=repo)  # 不注入 volume_pipeline

        result = await svc.get_summary(str(plan.id))

        assert result is not None
        assert result["next"] == {"finished": True}


# ── 用例 31-32：confirm_run thread_id / execution_store 状态同步 ──


@pytest.mark.asyncio
class TestConfirmRunStage4:
    async def test_confirm_run_passes_thread_id_and_updates_execution_status(self):
        """confirm_run 阶段 4 扩展：resume 调用传 thread_id=plan.thread_id（跨重启
        从 plan.thread_id 读）；成功后 update_status(execution_id=str(plan.id),
        status=result.status)。RED：构造 execution_store TypeError 先行。"""
        payload = {"question": "确认继续下一卷？", "volume_index": 1, "total_volumes": 2}
        repo, plan = _plan_repo(
            status="waiting_hitl", thread_id="t-confirm-1", hitl_payload=payload
        )
        pipeline = AsyncMock()
        pipeline.resume.return_value = {
            "run_id": str(plan.id),
            "status": "running",
            "thread_id": "t-confirm-1",
        }
        execution_store = AsyncMock()
        svc = _service(repo=repo, volume_pipeline=pipeline, execution_store=execution_store)

        result = await svc.confirm_run(str(plan.id), approved=True, decision="继续下一卷")

        assert result["status"] == "running"
        pipeline.resume.assert_awaited_once()
        call = pipeline.resume.await_args
        assert isinstance(call.args[0], VolumeHITLInterrupt)
        assert call.kwargs.get("approved") is True
        assert call.kwargs.get("thread_id") == "t-confirm-1"
        execution_store.update_status.assert_awaited_once()
        ucall = execution_store.update_status.await_args
        assert _call_arg(ucall, "execution_id", ["execution_id", "status", "hitl_payload"]) == str(
            plan.id
        )
        assert _call_arg(ucall, "status", ["execution_id", "status", "hitl_payload"]) == "running"

    async def test_confirm_run_thread_id_fallback_to_plan_id(self):
        """confirm_run thread_id 兜底：plan.thread_id 为空 → 传 str(plan.id)
        （读 plan.thread_id 兜底裁定）。RED：构造 execution_store TypeError 先行。"""
        payload = {"question": "确认继续下一卷？", "volume_index": 1, "total_volumes": 2}
        repo, plan = _plan_repo(status="waiting_hitl", thread_id=None, hitl_payload=payload)
        pipeline = AsyncMock()
        pipeline.resume.return_value = {
            "run_id": str(plan.id),
            "status": "completed",
            "thread_id": str(plan.id),
        }
        execution_store = AsyncMock()
        svc = _service(repo=repo, volume_pipeline=pipeline, execution_store=execution_store)

        result = await svc.confirm_run(str(plan.id), approved=True)

        assert result["status"] == "completed"
        pipeline.resume.assert_awaited_once()
        call = pipeline.resume.await_args
        assert call.kwargs.get("thread_id") == str(plan.id)


# ── 覆盖率门禁补测（F44 阶段4）：intervene/resume_run/_find_outline_node 防御分支 ──


@pytest.mark.asyncio
class TestCoverageGapStage4:
    async def test_intervene_resume_non_paused_rejected(self):
        """intervene(resume) 非 paused（completed）→ ValueError("运行未处于可暂停状态")，
        零落库（覆盖 book_service L421-422 resume 状态校验分支）。"""
        repo, plan = _plan_repo(status="completed")
        svc = _service(repo=repo)

        with pytest.raises(ValueError, match="运行未处于可暂停状态"):
            await svc.intervene(str(plan.id), action="resume")

        repo.update_writing_plan.assert_not_awaited()

    async def test_intervene_edit_target_none_rejected(self):
        """edit：target 缺失（None）→ ValueError（仅锁类型，覆盖 L460-461 target
        必填分支），outline_updater 零调用。"""
        repo, plan = _plan_repo(status="running", progress={"c1": "in_progress"})
        outline_updater = AsyncMock()
        svc = _service(repo=repo, outline_updater=outline_updater)

        with pytest.raises(ValueError):
            await svc.intervene(str(plan.id), action="edit", payload={"brief": "新梗概"})

        outline_updater.assert_not_awaited()

    async def test_intervene_edit_target_unknown_rejected(self):
        """edit：target 不在 progress 且 outline_repo.list 无该节点 → ValueError(
        "干预目标不存在")（覆盖 L465-468「不在 progress 且 outline 查无」分支），
        outline_updater 零调用。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={"c1": "in_progress"})
        outline_repo = AsyncMock()
        outline_repo.list.return_value = ([_outline(name="另一章")], 1)  # 无 target 节点
        outline_updater = AsyncMock()
        svc = _service(repo=repo, outline_repo=outline_repo, outline_updater=outline_updater)

        with pytest.raises(ValueError, match="干预目标不存在"):
            await svc.intervene(
                str(plan.id), action="edit", target=target, payload={"brief": "新梗概"}
            )

        outline_updater.assert_not_awaited()

    async def test_intervene_edit_target_not_in_progress_outline_hit(self):
        """edit 成功且 target 不在 progress：outline_repo.list 含 id==uuid.UUID(target)
        → 正常更新 + diff 四键（覆盖 L465-468「不在 progress」走 outline 判定分支；
        before 从 outline 节点 description 取）。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={"c1": "in_progress"})
        outline_repo = AsyncMock()
        outline_repo.list.return_value = ([_outline(id=uuid.UUID(target), description="旧梗概")], 1)
        outline_updater = AsyncMock(return_value=None)
        svc = _service(repo=repo, outline_repo=outline_repo, outline_updater=outline_updater)

        result = await svc.intervene(
            str(plan.id), action="edit", target=target, payload={"brief": "新梗概"}
        )

        outline_updater.assert_awaited_once()
        call = outline_updater.await_args
        assert _call_arg(call, "outline_id", ["outline_id", "description"]) == uuid.UUID(target)
        assert _call_arg(call, "description", ["outline_id", "description"]) == "新梗概"
        assert set(result["diff"].keys()) == {"target", "before", "after", "diff"}
        assert result["diff"]["before"] == "旧梗概"
        assert result["diff"]["after"] == "新梗概"
        assert result["status"] == "running"

    async def test_intervene_edit_target_in_progress_outline_missing(self):
        """edit：target 在 progress（L465 不触发）但 outline_repo.list 无该节点 →
        二次 _find_outline_node 返回 None → ValueError("干预目标不存在")（覆盖
        L473-475 node None 分支），outline_updater 零调用。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={target: "in_progress"})
        outline_repo = AsyncMock()
        outline_repo.list.return_value = ([_outline(name="另一章")], 1)  # 无 target 节点
        outline_updater = AsyncMock()
        svc = _service(repo=repo, outline_repo=outline_repo, outline_updater=outline_updater)

        with pytest.raises(ValueError, match="干预目标不存在"):
            await svc.intervene(
                str(plan.id), action="edit", target=target, payload={"brief": "新梗概"}
            )

        outline_updater.assert_not_awaited()

    async def test_resume_run_no_interrupt_execute_interrupt_persists_waiting_hitl(self):
        """resume_run 无 __interrupt__ 且 execute 再抛 VolumeHITLInterrupt →
        waiting_hitl + hitl_payload 落库（覆盖 L544-550 续跑再中断分支）。"""
        payload = {"question": "确认继续下一卷？", "volume_index": 2, "total_volumes": 2}
        repo, plan = _plan_repo(
            status="paused", thread_id="t-restart-gap", root_outline_id=uuid.uuid4()
        )
        outline_repo = AsyncMock()
        chapters = _chapters(plan, 2)
        outline_repo.list.return_value = (chapters, 2)
        pipeline = AsyncMock()
        # 无 __interrupt__ 键（task 被 cancel 停在普通 superstep）
        pipeline.get_checkpoint_state.return_value = {
            "volume_index": 1,
            "total_volumes": 2,
            "finished": False,
            "status": "running",
        }
        pipeline.execute.side_effect = VolumeHITLInterrupt(payload)
        svc = _service(repo=repo, outline_repo=outline_repo, volume_pipeline=pipeline)

        result = await svc.resume_run(str(plan.id))

        assert result["status"] == "waiting_hitl"
        assert result.get("run_id") == str(plan.id)
        assert plan.status == "waiting_hitl"
        assert plan.hitl_payload == payload
        repo.update_writing_plan.assert_awaited()

    async def test_intervene_redirect_outline_repo_none_rejected(self):
        """_find_outline_node：outline_repo 未装配（None）→ 返回 None → redirect
        抛 ValueError("干预目标不存在")（覆盖 L672-673 防御分支）。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={"c1": "in_progress"})
        svc = _service(repo=repo, outline_repo=None)  # 显式 None：_make_deps 默认注入 AsyncMock

        with pytest.raises(ValueError, match="干预目标不存在"):
            await svc.intervene(str(plan.id), action="redirect", target=target, to="skip")

        repo.update_writing_plan.assert_not_awaited()

    async def test_intervene_redirect_target_invalid_uuid_rejected(self):
        """_find_outline_node：target 非合法 UUID（"not-a-uuid"）→ uuid.UUID 抛
        ValueError → 返回 None → redirect 抛 ValueError("干预目标不存在")（覆盖
        L678-681 UUID 解析失败分支）。"""
        repo, plan = _plan_repo(status="running", progress={"c1": "in_progress"})
        outline_repo = AsyncMock()
        outline_repo.list.return_value = ([_outline(name="另一章")], 1)
        svc = _service(repo=repo, outline_repo=outline_repo)

        with pytest.raises(ValueError, match="干预目标不存在"):
            await svc.intervene(str(plan.id), action="redirect", target="not-a-uuid", to="skip")

        repo.update_writing_plan.assert_not_awaited()

    async def test_pipeline_accepts_thread_id_uninspectable_returns_true(self):
        """_pipeline_accepts_thread_id 异常路径：inspect.signature 对 builtin 类型
        抛 ValueError → 返回 True（新契约透传，覆盖 L718-721 except 分支）。"""
        assert BookService._pipeline_accepts_thread_id(int) is True


# ── 覆盖率最后收口补测（TestCoverageGapStage4b：line 98.47% → ≥98.5%）──────


@pytest.mark.asyncio
class TestCoverageGapStage4b:
    async def test_intervene_redirect_target_not_in_progress_outline_hit(self):
        """redirect：target 不在 progress 但 outline_repo.list 含该节点（level=chapter，
        id==uuid.UUID(target)）→ 正常执行 from_status="pending" + progress[target]=新状态
        + diff.from="pending"（覆盖 L436-439「不在 progress 走 outline 判定成功」分支，
        L439 from_status="pending"）。"""
        target = str(uuid.uuid4())
        repo, plan = _plan_repo(status="running", progress={"c1": "in_progress"})
        outline_repo = AsyncMock()
        outline_repo.list.return_value = ([_outline(id=uuid.UUID(target), level="chapter")], 1)
        svc = _service(repo=repo, outline_repo=outline_repo)

        result = await svc.intervene(str(plan.id), action="redirect", target=target, to="skip")

        assert result["diff"] == {"target": target, "from": "pending", "to": "skipped"}
        assert result["status"] == "running"
        assert plan.progress[target] == "skipped"
        repo.update_writing_plan.assert_awaited()

    async def test_resume_run_volume_pipeline_none_rejected(self):
        """resume_run：plan.status=="paused" 且 volume_pipeline 未装配（None）→
        ValueError("volume_pipeline 未配置")（覆盖 L511-512 防御分支），零落库。"""
        repo, plan = _plan_repo(status="paused")
        svc = _service(repo=repo)  # 不注入 volume_pipeline → 默认 None

        with pytest.raises(ValueError, match="volume_pipeline 未配置"):
            await svc.resume_run(str(plan.id))

        repo.update_writing_plan.assert_not_awaited()
