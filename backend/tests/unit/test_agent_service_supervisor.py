"""F29 AgentService supervisor 模式扩展契约（spec §5.1 + §3，追加段独立文件）。

被测（MODIFY 既有 domain/services/agent_service.py，本文件专测 supervisor 扩展，
避免 test_agent_service.py 843 行超 900 护栏）：
1. AgentService.execute(request) mode 分派：
   - mode=static（默认）→ 既有路径（_apply_agent_order + LangGraphAgentPipeline）
   - mode=supervisor → 角色池装配（_merge_role_configs，**不执行 _apply_agent_order
     静态重排**）+ SupervisorPipeline
2. AgentService.confirm_execution(execution_id, approved) 新方法：
   - waiting_hitl → resume 继续 → status 更新 completed/failed
   - 非 waiting_hitl → AgentServiceError
   - 不存在 → None/AgentServiceError（实现确认，镜像 get_status 404 语义）

RED 预期：
- execute(mode="supervisor")：PipelineExecuteRequest 无 mode 字段 → 构造即失败
  （Pydantic extra 拒绝）→ 用例 FAILED（ValidationError 非预期）
- confirm_execution：方法不存在 → AttributeError（FAILED 非 ERROR）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest
from inkflow.domain.models.project import Genre, Project, ProjectConfig
from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineResult,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.services.agent_service import AgentService, AgentServiceError


def _make_project(
    project_id: uuid.UUID | None = None, config: ProjectConfig | None = None
) -> Project:
    """构造测试用 Project 领域对象（镜像 test_agent_service.py）。"""
    return Project(
        id=project_id or uuid.uuid4(),
        name="测试项目",
        genre=Genre.XUANHUAN,
        language="zh-CN",
        target_words=100000,
        config=config or ProjectConfig(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_request(**kw) -> PipelineExecuteRequest:
    """构造执行请求（默认 static；supervisor 用例显式传 mode）。"""
    return PipelineExecuteRequest(
        project_id=uuid.UUID(int=1),
        pipeline="builtin:write_chapter",
        **kw,
    )


class MockPipeline:
    """记录调用并返回预设结果的管线 Mock（supervisor 模式专用）。"""

    def __init__(self) -> None:
        self.executed_stages: list[PipelineStage] = []
        self.executed_context: PipelineContext | None = None
        self.supervisor_config = None
        self.resume_called_with: tuple | None = None
        self.result = PipelineResult(
            stages=[
                StageResult(stage_id="writer", status=StageStatus.COMPLETED, output="正文"),
                StageResult(stage_id="reviser", status=StageStatus.COMPLETED, output="定稿"),
            ],
            final_output="定稿",
            status=StageStatus.COMPLETED,
            total_duration_ms=10,
        )

    async def execute(self, stages, context, *, supervisor=None):
        self.executed_stages = list(stages)
        self.executed_context = context
        self.supervisor_config = supervisor
        return self.result

    async def resume(self, interrupt_obj, *, approved: bool = False) -> PipelineResult:
        """HITL resume：confirm 后继续执行（记录调用参数）。"""
        self.resume_called_with = (interrupt_obj, approved)
        return self.result

    def validate(self, stages) -> list[str]:
        return []


class MockExecution:
    """模拟 AgentExecutionORM（waiting_hitl 语义）。"""

    def __init__(self, execution_id: str, status: str = "pending") -> None:
        self.id = execution_id
        self.pipeline = "builtin:write_chapter"
        self.project_id = "1"
        self.chapter_id = None
        self.status = status
        self.stages: list[dict] = []
        self.final_output = ""
        self.error = ""
        self.total_duration_ms = 0
        self.created_at = datetime.now(UTC)
        self.hitl_payload: dict | None = None


class MockExecutionStore:
    """内存版 ExecutionStore（supervisor 扩展方法）。"""

    def __init__(self, executions: dict[str, MockExecution] | None = None) -> None:
        self.executions: dict[str, MockExecution] = executions or {}

    async def create_execution(self, pipeline, project_id, chapter_id=None):
        exec_ = MockExecution(str(uuid.uuid4()))
        self.executions[exec_.id] = exec_
        return exec_

    async def get_execution(self, execution_id: str):
        return self.executions.get(execution_id)

    async def update_status(self, execution_id: str, status: str, hitl_payload=None) -> None:
        exec_ = self.executions.get(execution_id)
        if exec_ is not None:
            exec_.status = status
            if hitl_payload is not None:
                exec_.hitl_payload = hitl_payload

    async def update_stages(
        self,
        execution_id: str,
        stages: list[dict],
        status: str,
        final_output: str = "",
        error: str = "",
        total_duration_ms: int = 0,
        relations: list | None = None,
    ) -> None:
        """镜像真实 ExecutionStore.update_stages 语义（#343 根因 6：confirm 落库完整成品）。"""
        exec_ = self.executions.get(execution_id)
        if exec_ is not None:
            exec_.stages = stages
            exec_.status = status
            exec_.final_output = final_output
            exec_.error = error
            exec_.total_duration_ms = total_duration_ms
            exec_.relations = relations if relations is not None else []

    async def get_hitl_payload(self, execution_id: str):
        exec_ = self.executions.get(execution_id)
        return exec_.hitl_payload if exec_ else None

    async def list_executions(self, project_id: str, limit: int = 20):
        return [], 0


def _make_service(
    pipeline: MockPipeline | None = None,
    store: MockExecutionStore | None = None,
) -> AgentService:
    """构造 AgentService（注入 mock pipeline + store，镜像既有惯例）。"""
    svc = AgentService.__new__(AgentService)  # 跳过 __init__（内部延迟 import 依赖真实 DB）
    pipeline = pipeline or MockPipeline()
    svc._pipeline = pipeline
    svc._supervisor_pipeline = pipeline  # supervisor 模式共用同一 mock（构造注入）
    svc._store = store or MockExecutionStore()
    # 项目仓库 mock（execute 第一步校验项目存在）

    svc._project_repo = AsyncMock()
    svc._project_repo.get = AsyncMock(return_value=_make_project())
    svc._chapter_repo = AsyncMock()
    svc._chapter_repo.get_chapter = AsyncMock(return_value=None)
    svc._template_repo = AsyncMock()
    svc._template_repo.get = AsyncMock(return_value=None)
    from inkflow.infrastructure.agent.pipeline_templates import get_template

    svc._get_template = get_template  # type: ignore[assignment]  # 既有模块级函数绑定（签名兼容测试 mock）
    svc._list_templates = lambda: {"items": []}  # type: ignore[assignment]  # 测试 stub 简化返回值
    svc._load_template = AsyncMock(return_value=None)
    return svc


class TestExecuteModeDispatch:
    """execute() mode 分派契约（spec §5.1）。"""

    @pytest.mark.asyncio
    async def test_mode_default_static(self) -> None:
        """缺省 mode → 既有路径（守护：RED 阶段即 PASS 或按既有断言，静态零回归）。"""
        pipeline = MockPipeline()
        svc = _make_service(pipeline=pipeline)
        result = await svc.execute(_make_request())
        assert result["status"] == "pending"
        # 既有 execute 正常走通（mock pipeline）
        assert pipeline.executed_stages is not None

    @pytest.mark.asyncio
    async def test_mode_supervisor_passes_config(self) -> None:
        """mode=supervisor → SupervisorPipeline 收到 supervisor 配置（RED：mode 字段缺失）。"""
        from inkflow.domain.models.agent_pipeline import SupervisorExecuteConfig

        pipeline = MockPipeline()
        svc = _make_service(pipeline=pipeline)
        cfg = SupervisorExecuteConfig(max_steps=10, hitl_roles=["reviser"])
        request = _make_request(mode="supervisor", supervisor=cfg)
        result = await svc.execute(request)
        assert result["status"] == "pending"
        assert pipeline.supervisor_config is not None
        assert pipeline.supervisor_config.max_steps == 10

    @pytest.mark.asyncio
    async def test_mode_supervisor_requires_config(self) -> None:
        """mode=supervisor 且 supervisor 配置缺失 → AgentServiceError（spec §3 异常表）。"""
        svc = _make_service()
        with pytest.raises(AgentServiceError):
            await svc.execute(_make_request(mode="supervisor", supervisor=None))


class TestConfirmExecution:
    """confirm_execution 新方法契约（spec §3）。"""

    @pytest.mark.asyncio
    async def test_confirm_waiting_hitl_resume(self) -> None:
        """waiting_hitl 执行记录 confirm approved → resume 继续（RED：方法缺失）。"""
        exec_id = str(uuid.uuid4())
        store = MockExecutionStore({exec_id: MockExecution(exec_id, status="waiting_hitl")})
        svc = _make_service(store=store)
        # 契约：confirm_execution(execution_id, approved=True) → 返回更新后的状态
        result = await svc.confirm_execution(exec_id, approved=True)
        assert result is not None
        assert result["status"] in ("completed", "failed", "running")

    @pytest.mark.asyncio
    async def test_confirm_non_hitl_rejected(self) -> None:
        """非 waiting_hitl 状态 → AgentServiceError（spec §3 异常表 422 语义）。"""
        exec_id = str(uuid.uuid4())
        store = MockExecutionStore({exec_id: MockExecution(exec_id, status="completed")})
        svc = _make_service(store=store)
        with pytest.raises(AgentServiceError):
            await svc.confirm_execution(exec_id, approved=True)

    @pytest.mark.asyncio
    async def test_confirm_not_found(self) -> None:
        """执行记录不存在 → AgentServiceError（404 语义）。"""
        svc = _make_service(store=MockExecutionStore())
        with pytest.raises(AgentServiceError):
            await svc.confirm_execution(str(uuid.uuid4()), approved=True)

    @pytest.mark.asyncio
    async def test_confirm_writes_final_output(self) -> None:
        """confirm 成功后成品（final_output/stages）必须落库（#343 E2E 实证根因 6）。

        HITL 链路：_run_pipeline 在 interrupt 处只 update_status(waiting_hitl)；
        confirm_execution resume 成功后若只 update_status(completed) → stages/final_output
        永不落库 → 前端 pollExecutionResult 等不到成品（E2E B1-5 三轮实证：
        DB status=completed 但 stages=0、final_output 空、duration=0）。

        契约：confirm 成功路径须调 update_stages（含 stages/final_output/total_duration_ms），
        不只 update_status。

        RED 预期：当前实现 resume 后仅 update_status → MockExecutionStore 的
        execution.final_output 仍空 → 断言 FAIL。
        """
        exec_id = str(uuid.uuid4())
        pipeline = MockPipeline()
        store = MockExecutionStore({exec_id: MockExecution(exec_id, status="waiting_hitl")})
        svc = _make_service(pipeline=pipeline, store=store)
        # MockPipeline.result 含 final_output="定稿" + stages [writer, reviser]
        result = await svc.confirm_execution(exec_id, approved=True)
        assert result["status"] == "completed"
        record = store.executions[exec_id]
        assert record.final_output == "定稿"
        assert record.total_duration_ms == 10


class _HitlRaisingPipeline(MockPipeline):
    """execute/resume 抛 HITLInterrupt 的管线 Mock（#343 后端缺口契约）。

    execute() 首次调用抛 HITLInterrupt（模拟真实 SupervisorPipeline 的
    `__interrupt__` 路径）；resume() 可配置二次 interrupt 语义。
    """

    def __init__(self, payload: dict | None = None, resume_interrupt: bool = False) -> None:
        super().__init__()
        self.payload = payload or {
            "question": "确认执行下一角色 reviser？",
            "role": "reviser",
            "route_history": ["reviser"],
        }
        self.resume_interrupt = resume_interrupt

    async def execute(self, stages, context, *, supervisor=None):
        from inkflow.infrastructure.agent.supervisor_pipeline import HITLInterrupt

        self.executed_stages = list(stages)
        self.executed_context = context
        self.supervisor_config = supervisor
        raise HITLInterrupt(self.payload)

    async def resume(self, interrupt_obj, *, approved: bool = False) -> PipelineResult:
        from inkflow.infrastructure.agent.supervisor_pipeline import HITLInterrupt

        self.resume_called_with = (interrupt_obj, approved)
        if self.resume_interrupt:
            raise HITLInterrupt(
                {
                    "question": "确认执行下一角色 writer？",
                    "role": "writer",
                    "route_history": ["reviser", "writer"],
                }
            )
        return self.result


class TestRunPipelineHitl:
    """#343：_run_pipeline 收到 HITLInterrupt → 写 waiting_hitl + payload（spec §5.6 缺口）。"""

    @pytest.mark.asyncio
    async def test_run_pipeline_hitl_interrupt_writes_waiting_hitl(self) -> None:
        """HITL interrupt → ExecutionStore status=waiting_hitl + hitl_payload 快照。

        RED 预期：_run_pipeline 无 except HITLInterrupt → 落入 except Exception →
        update_stages(status='failed') → 断言 FAIL（status 应为 waiting_hitl）。
        """
        from inkflow.domain.models.agent_pipeline import SupervisorExecuteConfig

        exec_id = str(uuid.uuid4())
        payload = {
            "question": "确认执行下一角色 reviser？",
            "role": "reviser",
            "route_history": ["reviser"],
        }
        pipeline = _HitlRaisingPipeline(payload=payload)
        store = MockExecutionStore({exec_id: MockExecution(exec_id, status="running")})
        svc = _make_service(pipeline=pipeline, store=store)
        cfg = SupervisorExecuteConfig(hitl_roles=["reviser"])

        ctx = PipelineContext(project_id="1", chapter_id=None, variables={})
        await svc._run_pipeline(
            exec_id,
            pipeline.executed_stages or [],
            ctx,
            pipeline=pipeline,
            supervisor_config=cfg,
        )
        record = store.executions[exec_id]
        assert record.status == "waiting_hitl"
        assert record.hitl_payload == payload

    @pytest.mark.asyncio
    async def test_confirm_resume_second_interrupt_returns_waiting_hitl(self) -> None:
        """confirm 后 resume 再次 interrupt → 再次写 waiting_hitl + 返回新 payload。

        RED 预期：confirm_execution 无 except HITLInterrupt → HITLInterrupt 传播
        → 用例 ERROR（非预期异常），断言 FAIL。
        """
        exec_id = str(uuid.uuid4())
        payload = {
            "question": "确认执行下一角色 reviser？",
            "role": "reviser",
            "route_history": ["reviser"],
        }
        pipeline = _HitlRaisingPipeline(payload=payload, resume_interrupt=True)
        store = MockExecutionStore({exec_id: MockExecution(exec_id, status="waiting_hitl")})
        store.executions[exec_id].hitl_payload = payload
        svc = _make_service(pipeline=pipeline, store=store)

        result = await svc.confirm_execution(exec_id, approved=True)
        assert result["status"] == "waiting_hitl"
        assert result["hitl_pending"]["role"] == "writer"
        record = store.executions[exec_id]
        assert record.status == "waiting_hitl"
        assert record.hitl_payload["role"] == "writer"
