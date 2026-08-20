"""#479 知识图谱定时提取调度器契约测试 — KnowledgeExtractScheduler（RED 批）。

覆盖 spec f48-knowledge-graph §5.5.3 + §5.5.8:
- run_cycle: disabled 跳过 / enabled 逐项目执行 / 单项目异常不中断 / 每周期重读设置
- method 透传（settings.kg_extract_method → extract_for_project(method=...)）
- startup 补跑: extraction_run_repo=None 或无 run 记录 → 首启立即 run_cycle；
  有近期 run 记录 → 等待；距今 ≥ interval_hours → 立即补跑
- stop 幂等 + 后台任务不泄漏（F44 RED 陷阱，§5.5.8）

依据: specs/f48-knowledge-graph/spec.md §5.5.3/§5.5.5/§5.5.8。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

模块（本批新建，当前不存在 → 收集期 ModuleNotFoundError 即预期 RED 形态）:
``inkflow.infrastructure.scheduler.kg_extract_scheduler``，逐字实现 spec §5.5.3:

1. ``class KnowledgeExtractScheduler``（全 Keyword-only 构造）:
   - ``def __init__(self, *, settings_service, project_repository,
     relation_extraction_service, extraction_run_repo=None) -> None``
   - ``async def start(self) -> None``: lifespan startup 调用；spawn 常驻 loop task
     （F42 create_task 先例）；启动即执行 startup 补跑判定（见 3）
   - ``async def stop(self) -> None``: cancel loop task + await；幂等（未 start 也合法）
   - ``async def run_cycle(self) -> list[dict]``: ★ 单周期执行体（RED 单测直调）:
     1. ``settings_service.get_settings()`` 读设置；kg_extract_enabled=False → 返回 []
        且不调 extract
     2. ``project_repository.list_all()``（未删除项目）逐项目
        ``relation_extraction_service.extract_for_project(project_id,
        method=settings.kg_extract_method)``
     3. 单项目异常 → 捕获记入该项目结果 dict（status='error'，created=0），
        不中断其他项目
     4. 汇总返回 list[dict]：每项至少含 project_id/status/created；
        成功项 status='success'、created=result.created（§5.5.5 run 记录口径）

2. 设置形态: 调度器只读 settings 的 kg_extract_enabled / kg_extract_interval_hours /
   kg_extract_method 三个属性（测试用 SimpleNamespace 替身，鸭子形态）；
   **每周期重读设置**（热生效，改频率后下一周期按新值）。

3. startup 补跑（start() 时）:
   - extraction_run_repo is None → 视为无记录 → 立即 run_cycle()
   - 否则 ``extraction_run_repo.list(...)`` 取最近一次 knowledge_relation run
     （返回 (runs, total)；runs 按 run_at DESC 最新在前）:
     - 空列表（首启无记录）→ 立即 run_cycle()
     - 最近 run_at 距今 < kg_extract_interval_hours → 等待（不立即 run_cycle）
     - 最近 run_at 距今 ≥ kg_extract_interval_hours → 立即 run_cycle()（补跑）

4. loop task: ``while True: await asyncio.sleep(interval*3600); await run_cycle()``
   —— interval 每周期从 settings 重读（5.5.2 热生效）。

5. mock 形态（测试装配，GREEN 不得依赖）:
   - settings_service: AsyncMock，get_settings.return_value 由 _settings() 提供
   - project_repository: AsyncMock，list_all.return_value = [Project...]（SimpleNamespace
     id 即可）
   - relation_extraction_service: AsyncMock，extract_for_project.return_value =
     ExtractionResult（type 用既有枚举值即可，调度器不读 type）
   - extraction_run_repo: AsyncMock，list.return_value = ([run], total)；
     run 以 SimpleNamespace(run_at=..., type="knowledge_relation") 形态提供

6. 后台任务 RED 陷阱（§5.5.8）: start() 会 spawn loop task——凡调 start() 的用例
   teardown 必须 stop()（fixture 统一收尾）；断言后台行为前 ``await asyncio.sleep(0)``
   让出事件循环（本文件用 _let_tasks_run 多次让出，防 catch-up 多段 await 未推进）。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述签名实现后本文件应全绿。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.extraction import ExtractionResult, ExtractionStatus, ExtractionType
from inkflow.infrastructure.scheduler.kg_extract_scheduler import (  # RED ①：模块不存在
    KnowledgeExtractScheduler,
)

PID1 = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PID2 = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000002")


def _settings(**overrides) -> SimpleNamespace:
    """构造设置替身（鸭子形态: 调度器只读 kg_extract_* 三属性）。"""
    base = {
        "kg_extract_enabled": False,
        "kg_extract_interval_hours": 24,
        "kg_extract_method": "rule",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _project(pid: uuid.UUID) -> SimpleNamespace:
    """构造项目替身（调度器只读 id）。"""
    return SimpleNamespace(id=pid, name="项目", is_deleted=False)


def _result(*, created: int = 1) -> ExtractionResult:
    """构造 extract_for_project 返回信封（type 用既有枚举值，调度器不读 type）。"""
    return ExtractionResult(
        type=ExtractionType.CHARACTER,
        status=ExtractionStatus.SUCCESS,
        created=created,
    )


def _make_scheduler(**overrides) -> KnowledgeExtractScheduler:
    """按契约 §1 构造调度器；默认 disabled + 空项目表。"""
    settings_service = AsyncMock()
    settings_service.get_settings.return_value = _settings()
    project_repository = AsyncMock()
    project_repository.list_all.return_value = []
    relation_extraction_service = AsyncMock()
    relation_extraction_service.extract_for_project.return_value = _result()
    kwargs = {
        "settings_service": settings_service,
        "project_repository": project_repository,
        "relation_extraction_service": relation_extraction_service,
        "extraction_run_repo": None,
    }
    kwargs.update(overrides)
    return KnowledgeExtractScheduler(**kwargs)


async def _let_tasks_run(times: int = 5) -> None:
    """让出事件循环多次，使后台 loop task 推进到目标断言点（F44 RED 陷阱）。"""
    for _ in range(times):
        await asyncio.sleep(0)


@pytest.fixture
async def scheduler_harness():
    """装配调度器并登记；teardown 统一 stop() 防 pending task 泄漏（§5.5.8）。"""
    created: list[KnowledgeExtractScheduler] = []

    def _make(**overrides) -> KnowledgeExtractScheduler:
        sched = _make_scheduler(**overrides)
        created.append(sched)
        return sched

    yield _make
    for sched in created:
        await sched.stop()


class TestRunCycle:
    """run_cycle — 单周期执行体契约（RED 单测直调，不依赖 sleep）。"""

    async def test_disabled_returns_empty_and_skips_extract(self, scheduler_harness):
        """enabled=False → 返回 []，extract_for_project 不被调用（5.5.3 步骤 1）。"""
        settings_service = AsyncMock()
        settings_service.get_settings.return_value = _settings()  # enabled=False 默认
        project_repository = AsyncMock()
        project_repository.list_all.return_value = []
        relation_extraction_service = AsyncMock()
        relation_extraction_service.extract_for_project.return_value = _result(created=1)
        sched = scheduler_harness(
            settings_service=settings_service,
            project_repository=project_repository,
            relation_extraction_service=relation_extraction_service,
        )

        items = await sched.run_cycle()

        assert items == []
        settings_service.get_settings.assert_awaited_once()
        relation_extraction_service.extract_for_project.assert_not_awaited()

    async def test_enabled_extracts_each_project(self, scheduler_harness):
        """enabled=True → 逐项目提取，结果 dict 每项含 project_id/status/created。"""
        settings_service = AsyncMock()
        settings_service.get_settings.return_value = _settings(kg_extract_enabled=True)
        project_repository = AsyncMock()
        project_repository.list_all.return_value = [_project(PID1), _project(PID2)]
        relation_extraction_service = AsyncMock()
        relation_extraction_service.extract_for_project.return_value = _result(created=2)

        sched = scheduler_harness(
            settings_service=settings_service,
            project_repository=project_repository,
            relation_extraction_service=relation_extraction_service,
        )
        items = await sched.run_cycle()

        assert len(items) == 2
        for item in items:
            assert {"project_id", "status", "created"} <= set(item.keys())
        by_pid = {item["project_id"]: item for item in items}
        assert by_pid[PID1]["status"] == "success"
        assert by_pid[PID1]["created"] == 2
        assert by_pid[PID2]["status"] == "success"
        # 每项目一次 extract，method 来自 settings（关键字透传契约）
        calls = relation_extraction_service.extract_for_project.await_args_list
        assert len(calls) == 2
        assert calls[0].args[0] == PID1
        assert calls[1].args[0] == PID2
        for call in calls:
            method = call.kwargs.get("method", call.args[1] if len(call.args) > 1 else None)
            assert method == "rule"

    async def test_single_project_error_does_not_interrupt(self, scheduler_harness):
        """单项目抛异常 → 捕获记入结果 dict（status='error'），不中断其他项目。"""
        settings_service = AsyncMock()
        settings_service.get_settings.return_value = _settings(kg_extract_enabled=True)
        project_repository = AsyncMock()
        project_repository.list_all.return_value = [_project(PID1), _project(PID2)]
        relation_extraction_service = AsyncMock()

        async def _extract(pid, **kwargs):
            if pid == PID2:
                raise RuntimeError("LLM 调用失败")
            return _result(created=1)

        relation_extraction_service.extract_for_project.side_effect = _extract

        sched = scheduler_harness(
            settings_service=settings_service,
            project_repository=project_repository,
            relation_extraction_service=relation_extraction_service,
        )
        items = await sched.run_cycle()

        assert len(items) == 2  # 两个项目都尝试了，异常未中断循环
        by_pid = {item["project_id"]: item for item in items}
        assert by_pid[PID2]["status"] == "error"
        assert by_pid[PID2]["created"] == 0
        assert by_pid[PID1]["status"] == "success"
        assert by_pid[PID1]["created"] == 1

    async def test_rereads_settings_each_cycle(self, scheduler_harness):
        """每周期重读设置（热生效，5.5.2: 开关/频率/方式无需重启内核）。"""
        settings_service = AsyncMock()
        settings_service.get_settings.return_value = _settings(kg_extract_enabled=True)
        project_repository = AsyncMock()
        project_repository.list_all.return_value = [_project(PID1)]
        relation_extraction_service = AsyncMock()
        relation_extraction_service.extract_for_project.return_value = _result(created=1)

        sched = scheduler_harness(
            settings_service=settings_service,
            project_repository=project_repository,
            relation_extraction_service=relation_extraction_service,
        )
        await sched.run_cycle()
        await sched.run_cycle()

        assert settings_service.get_settings.await_count == 2
        assert relation_extraction_service.extract_for_project.await_count == 2

    async def test_method_passed_from_settings(self, scheduler_harness):
        """method 透传: settings.kg_extract_method='ai' → extract_for_project(method='ai')。"""
        settings_service = AsyncMock()
        settings_service.get_settings.return_value = _settings(
            kg_extract_enabled=True, kg_extract_method="ai"
        )
        project_repository = AsyncMock()
        project_repository.list_all.return_value = [_project(PID1)]
        relation_extraction_service = AsyncMock()
        relation_extraction_service.extract_for_project.return_value = _result(created=1)

        sched = scheduler_harness(
            settings_service=settings_service,
            project_repository=project_repository,
            relation_extraction_service=relation_extraction_service,
        )
        await sched.run_cycle()

        call = relation_extraction_service.extract_for_project.await_args
        method = call.kwargs.get("method", call.args[1] if len(call.args) > 1 else None)
        assert method == "ai"


class TestStartStop:
    """start/stop — 后台 loop task 生命周期 + startup 补跑（F44 RED 陷阱）。"""

    async def test_start_without_run_repo_runs_cycle_immediately(self, scheduler_harness):
        """startup 补跑①: extraction_run_repo=None（未注入）→ 首启立即 run_cycle。"""
        sched = scheduler_harness()  # extraction_run_repo=None 默认
        sched.run_cycle = AsyncMock(return_value=[])

        await sched.start()
        await _let_tasks_run()

        sched.run_cycle.assert_awaited()  # 后台任务已补跑
        # teardown 统一 stop()，无 pending task 泄漏

    async def test_start_with_no_run_records_runs_cycle_immediately(self, scheduler_harness):
        """startup 补跑②: 有 run repo 但无任何记录（首启）→ 立即 run_cycle。"""
        run_repo = AsyncMock()
        run_repo.list.return_value = ([], 0)
        sched = scheduler_harness(extraction_run_repo=run_repo)
        sched.run_cycle = AsyncMock(return_value=[])

        await sched.start()
        await _let_tasks_run()

        run_repo.list.assert_awaited()  # 补跑判定确实查询了 run 记录
        sched.run_cycle.assert_awaited()

    async def test_start_with_fresh_run_waits(self, scheduler_harness):
        """startup 补跑③: 最近 run 距今 < interval → 等待，不立即 run_cycle。"""
        run_repo = AsyncMock()
        recent = SimpleNamespace(run_at=datetime.now(UTC), type="knowledge_relation")
        run_repo.list.return_value = ([recent], 1)
        sched = scheduler_harness(extraction_run_repo=run_repo)
        sched.run_cycle = AsyncMock(return_value=[])

        await sched.start()
        await _let_tasks_run()

        run_repo.list.assert_awaited()
        sched.run_cycle.assert_not_awaited()  # 未到补跑条件

    async def test_start_with_stale_run_catches_up(self, scheduler_harness):
        """startup 补跑④: 最近 run 距今 ≥ interval_hours → 立即补跑。"""
        run_repo = AsyncMock()
        stale = SimpleNamespace(
            run_at=datetime.now(UTC) - timedelta(hours=48),  # 距今 48h ≥ interval 24h
            type="knowledge_relation",
        )
        run_repo.list.return_value = ([stale], 1)
        sched = scheduler_harness(extraction_run_repo=run_repo)
        sched.run_cycle = AsyncMock(return_value=[])

        await sched.start()
        await _let_tasks_run()

        sched.run_cycle.assert_awaited()

    async def test_stop_is_idempotent(self, scheduler_harness):
        """stop 幂等: 未 start 调用合法；start 后重复 stop 不抛错（lifespan shutdown 安全）。"""
        sched = scheduler_harness()

        await sched.stop()  # 未 start → 空操作
        assert sched._task is None  # 无 task 可停

        await sched.start()
        await _let_tasks_run()
        task_ref = sched._task
        assert task_ref is not None  # 后台 loop task 已 spawn

        await sched.stop()  # 取消 loop task
        assert task_ref.cancelled()  # ✅ 补强：loop task 确已被取消（stop 语义锚定）
        assert sched._task is None  # 引用已清
        await sched.stop()  # 重复 stop → 幂等（不抛）


class TestGuardEnv:
    """守护用例 — 当前应 PASS（仅验证 mock 装配形态，防假绿）。"""

    def test_guard_mock_env_shape(self):
        """守护: mock 装配（SimpleNamespace 设置 + AsyncMock repo + 信封构造）形态自检。"""
        ss = AsyncMock()
        ss.get_settings.return_value = _settings(kg_extract_enabled=True)
        assert ss.get_settings.return_value.kg_extract_enabled is True
        assert ss.get_settings.return_value.kg_extract_method == "rule"

        pr = AsyncMock()
        pr.list_all.return_value = [_project(PID1)]
        assert pr.list_all.return_value[0].id == PID1

        result = _result(created=2)
        assert result.created == 2
        assert result.updated == 0
