"""#642-1 管线 SSE 流式服务层补测 — AgentServiceStreamMixin (coverage-gap #645)。

agent_service_stream.py 覆盖率缺口补测（非 RED——功能已实现，补测即过）：
- stream_pipeline 主路径（mock pipeline.stream 产 delta/done）→ 落库 completed + final_output
- stream_pipeline 异常路径 → error 帧 + 落库 failed
- supervisor 无 stream → 降级 execute + get_status 轮询 → done
- _build_pipeline_context 校验分支（项目/模板/章节不存在、supervisor 缺配置/未装配）
- _build_pipeline_context static 路径 agent_repo 兜底 + 加载失败 warning 回退
- _inject_context：设定注入 + continue_context 前文摘要 + 各自失败回退

镜像 tests/unit/test_agent_service.py 的 Mock 仓储/Store 构造风格。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inkflow.domain.models.agent_pipeline import (
    PipelineExecuteRequest,
    SupervisorExecuteConfig,
)
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.ports.agent_pipeline import PipelineContext, PipelineStage
from inkflow.domain.services.agent_service import AgentService, AgentServiceError

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
CHAPTER_ID = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


# ── 测试替身 ──────────────────────────────────────


def _make_project(config: ProjectConfig | None = None) -> Project:
    """构造测试用 Project 领域对象（默认空配置）。"""
    return Project(
        id=PROJECT_ID,
        name="测试项目",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
        config=config or ProjectConfig(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_template() -> SimpleNamespace:
    """构造最小 pipeline 模板替身（.stages 供 supervisor/static 装配读取）。"""
    return SimpleNamespace(stages=[])


def _make_stage(stage_id: str = "writer") -> PipelineStage:
    """构造单阶段 PipelineStage（agent_order 空时 _apply_agent_order 原样返回）。"""
    return PipelineStage(
        id=stage_id,
        name=stage_id,
        agent=SimpleNamespace(
            id=stage_id, name=stage_id, system_prompt="", model="", temperature=None
        ),
    )


class MockStreamPipeline:
    """记录 stream 调用；events 为预置事件列表；error 可选。

    has_stream=False 时无 .stream（supervisor 降级路径）；有 stream 时按预置事件 yield。
    """

    def __init__(self, events=None, error=None):
        self._events = list(events or [])
        self._error = error
        self.calls: list[dict] = []

    async def stream(self, stages, context, conditional_edges=None):
        self.calls.append(
            {"stages": stages, "context": context, "conditional_edges": conditional_edges}
        )
        if self._error is not None:
            raise self._error
        for ev in self._events:
            yield ev


class FakeStreamExecution:
    """模拟 AgentExecutionORM —— 仅暴露 stream_pipeline 读取的字段。"""

    def __init__(self, pipeline: str, project_id: str, chapter_id: str | None):
        self.id = str(uuid.uuid4())
        self.pipeline = pipeline
        self.project_id = project_id
        self.chapter_id = chapter_id
        self.status = "pending"
        self.stages: list[dict] = []
        self.final_output = ""
        self.error = ""


class MockStreamStore:
    """内存版 ExecutionStore —— 记录 create/update 调用并返回替身执行记录。"""

    def __init__(self):
        self.executions: dict[str, FakeStreamExecution] = {}
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []

    async def create_execution(
        self, pipeline: str, project_id: str, chapter_id: str | None = None
    ) -> FakeStreamExecution:
        execution = FakeStreamExecution(pipeline, project_id, chapter_id)
        self.executions[execution.id] = execution
        self.create_calls.append(
            {"pipeline": pipeline, "project_id": project_id, "chapter_id": chapter_id}
        )
        return execution

    async def update_stages(
        self,
        execution_id: str,
        stages: list[dict],
        status: str,
        final_output: str = "",
        error: str = "",
    ) -> None:
        self.update_calls.append(
            {
                "execution_id": execution_id,
                "stages": stages,
                "status": status,
                "final_output": final_output,
                "error": error,
            }
        )


class MockProjectRepo:
    """固定返回预设 Project 或 None 的项目仓储 Mock。"""

    def __init__(self, project: Project | None = None):
        self.project = project

    async def get(self, project_id: int) -> Project | None:
        return self.project


class MockChapterRepo:
    """固定返回预设 Chapter 或 None 的章节仓储 Mock。"""

    def __init__(self, chapter=None):
        self.chapter = chapter

    async def get_chapter(self, chapter_id: int):
        return self.chapter


def _build_svc(
    pipeline=None,
    project: Project | None = None,
    chapter=None,
    store: MockStreamStore | None = None,
    db_session=None,
    supervisor_pipeline=None,
    agent_repo=None,
) -> tuple[AgentService, MockStreamStore, MockProjectRepo, MockChapterRepo]:
    """装配 AgentService，注入 Mock 依赖（不触碰真实 DB / LangGraph）。

    db_session 默认 None；设为 MagicMock 时走 _build_pipeline_context 的
    SQLiteAgentRepository 兜底分支（覆盖 L164-169）。
    """
    pipeline = pipeline if pipeline is not None else MockStreamPipeline(events=[])
    store = store or MockStreamStore()
    project_repo = MockProjectRepo(project)
    chapter_repo = MockChapterRepo(chapter)
    service = AgentService(
        pipeline,
        db_session=db_session,
        store=store,
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        supervisor_pipeline=supervisor_pipeline,
        agent_repo=agent_repo,
    )
    return service, store, project_repo, chapter_repo


def _request(pipeline: str = "builtin:write_auto", **kwargs) -> PipelineExecuteRequest:
    return PipelineExecuteRequest(project_id=PROJECT_ID, pipeline=pipeline, **kwargs)


# ── TestStreamPipeline: 主路径 + 异常 ──


class TestStreamPipeline:
    """stream_pipeline 主路径：mock _build_pipeline_context/_inject_context，锁定帧序 + 落库。"""

    async def test_stream_pipeline_delta_and_done_saves_completed(self):
        """delta 逐帧产生 + done 帧携带 final_output/intent/execution_id；落库 completed。"""
        events = [
            SimpleNamespace(
                type="delta",
                done=False,
                delta="风起",
                final_output="",
                intent=None,
                error="",
                execution_id="",
            ),
            SimpleNamespace(
                type="delta",
                done=False,
                delta="云涌",
                final_output="",
                intent=None,
                error="",
                execution_id="",
            ),
            SimpleNamespace(
                type="done",
                done=True,
                delta="",
                final_output="风起云涌",
                intent="content",
                error="",
                execution_id="",
            ),
        ]
        pipeline_impl = MockStreamPipeline(events=events)
        svc, store, _, _ = _build_svc(pipeline=pipeline_impl)
        svc._build_pipeline_context = AsyncMock(
            return_value=([], PipelineContext(project_id=str(PROJECT_ID)), pipeline_impl, [], [])
        )
        svc._inject_context = AsyncMock()

        frames = [ev async for ev in svc.stream_pipeline(_request())]

        assert [ev.type for ev in frames] == ["delta", "delta", "done"]
        assert "".join(ev.delta for ev in frames[:2]) == "风起云涌"
        assert frames[2].done is True
        assert frames[2].final_output == "风起云涌"
        assert frames[2].intent == "content"
        # done 帧 execution_id 回填为执行记录 id
        assert frames[2].execution_id == next(iter(store.executions))
        # 落库 completed + final_output
        assert store.update_calls[-1]["status"] == "completed"
        assert store.update_calls[-1]["final_output"] == "风起云涌"
        assert svc._inject_context.await_count == 1

    async def test_stream_pipeline_exception_yields_error_and_saves_failed(self):
        """stream 中途抛异常 → error done 帧 + 落库 failed（error 透传）。"""
        pipeline_impl = MockStreamPipeline(events=[], error=RuntimeError("boom"))
        svc, store, _, _ = _build_svc(pipeline=pipeline_impl)
        svc._build_pipeline_context = AsyncMock(
            return_value=([], PipelineContext(project_id=str(PROJECT_ID)), pipeline_impl, [], [])
        )
        svc._inject_context = AsyncMock()

        frames = [ev async for ev in svc.stream_pipeline(_request())]

        assert len(frames) == 1
        assert frames[0].done is True
        assert frames[0].error == "boom"
        assert store.update_calls[-1]["status"] == "failed"
        assert store.update_calls[-1]["error"] == "boom"


class TestStreamPipelineSupervisor:
    """supervisor 无 stream → 降级 execute 后台任务 + get_status 轮询 → done。"""

    async def test_supervisor_no_stream_falls_back_to_execute_polling(self):
        """pipeline_impl 无 .stream → execute 产 execution_id；轮询 pending→completed。"""
        pipeline_impl = SimpleNamespace()  # 无 stream 方法
        svc, _, _, _ = _build_svc(pipeline=pipeline_impl)
        svc._build_pipeline_context = AsyncMock(
            return_value=([], PipelineContext(project_id=str(PROJECT_ID)), pipeline_impl, [], [])
        )
        svc.execute = AsyncMock(return_value={"execution_id": "exec-9"})
        svc.get_status = AsyncMock(
            side_effect=[
                {"status": "pending", "final_output": ""},
                {"status": "completed", "final_output": "正文", "execution_id": "exec-9"},
            ]
        )

        frames = [
            ev
            async for ev in svc.stream_pipeline(
                _request(mode="supervisor", supervisor=SupervisorExecuteConfig())
            )
        ]

        assert len(frames) == 1
        assert frames[0].type == "done"
        assert frames[0].done is True
        assert frames[0].execution_id == "exec-9"
        assert frames[0].final_output == "正文"
        assert frames[0].intent == "content"
        svc.execute.assert_awaited_once()
        assert svc.get_status.await_count == 2


# ── TestBuildPipelineContext: 校验分支 + static 路径 ──


class TestBuildPipelineContextValidation:
    """_build_pipeline_context 前置校验分支 → AgentServiceError。"""

    async def test_project_not_found_raises(self):
        """项目不存在 → AgentServiceError('项目不存在')。"""
        svc, _, _, _ = _build_svc(project=None)
        with pytest.raises(AgentServiceError, match="项目不存在"):
            await svc._build_pipeline_context(_request())

    async def test_unknown_template_raises(self):
        """模板不存在 → AgentServiceError('未知管线模板')。"""
        svc, _, _, _ = _build_svc(project=_make_project())
        svc._get_template = lambda name: None
        with pytest.raises(AgentServiceError, match="未知管线模板"):
            await svc._build_pipeline_context(_request(pipeline="unknown:xxx"))

    async def test_chapter_not_found_raises(self):
        """章节不存在 → AgentServiceError('章节不存在')。"""
        svc, _, _, _ = _build_svc(project=_make_project(), chapter=None)
        with pytest.raises(AgentServiceError, match="章节不存在"):
            await svc._build_pipeline_context(_request(chapter_id=CHAPTER_ID))

    async def test_supervisor_missing_config_raises(self):
        """mode=supervisor 但无 supervisor 配置 → AgentServiceError('supervisor 配置缺失')。"""
        svc, _, _, _ = _build_svc(project=_make_project())
        svc._get_template = lambda name: _make_template()
        with pytest.raises(AgentServiceError, match="supervisor 配置缺失"):
            await svc._build_pipeline_context(_request(mode="supervisor"))

    async def test_supervisor_not_assembled_raises(self):
        """mode=supervisor 且配置完备但 _supervisor_pipeline 未装配 → AgentServiceError。"""
        svc, _, _, _ = _build_svc(project=_make_project(), supervisor_pipeline=None)
        svc._get_template = lambda name: _make_template()
        svc._merge_role_configs = AsyncMock(return_value=[_make_stage()])
        with pytest.raises(AgentServiceError, match="supervisor 模式未装配"):
            await svc._build_pipeline_context(
                _request(mode="supervisor", supervisor=SupervisorExecuteConfig())
            )

    async def test_supervisor_assembled_returns_pipeline_and_stages(self):
        """mode=supervisor 且 _supervisor_pipeline 已装配 → 返回装配元组（stages/context 等）。

        coverage 缺口 #645：_build_pipeline_context L156 else 分支（pipeline_impl 非 None 时
        落入 L192 return）未覆盖——supervisor 缺配置/未装配之外的成功装配路径。
        """
        supervisor_pipeline = MockStreamPipeline()
        svc, _, _, _ = _build_svc(project=_make_project(), supervisor_pipeline=supervisor_pipeline)
        svc._get_template = lambda name: _make_template()
        svc._merge_role_configs = AsyncMock(return_value=[_make_stage()])

        stages, context, pipeline_impl, conditional_edges, _ = await svc._build_pipeline_context(
            _request(mode="supervisor", supervisor=SupervisorExecuteConfig())
        )

        assert pipeline_impl is supervisor_pipeline
        assert len(stages) == 1
        assert conditional_edges == []
        assert context.project_id == str(PROJECT_ID)


class TestBuildPipelineContextStatic:
    """static 路径：_agent_repo=None 时 SQLiteAgentRepository 兜底 + 加载失败 warning 回退。"""

    async def test_static_agent_repo_fallback_loading_error_degrades(self):
        """_agent_repo=None + _db_session 设置 → 用 SQLiteAgentRepository 兜底；
        其 list() 抛异常 → warning 回退模板装配（装配继续，不阻断）。"""
        stage = _make_stage()
        svc, _, _, _ = _build_svc(project=_make_project(), db_session=MagicMock(), agent_repo=None)
        svc._get_template = lambda name: _make_template()
        svc._load_template = AsyncMock(return_value=None)
        svc._merge_role_configs = AsyncMock(return_value=[stage])
        with (
            patch("inkflow.domain.services.agent_service._apply_agent_order", return_value=[stage]),
            patch(
                "inkflow.domain.services.agent_service._apply_agent_relations",
                return_value=([stage], []),
            ),
            patch(
                "inkflow.infrastructure.database.repositories.agent_repo.SQLiteAgentRepository"
            ) as m_repo_cls,
        ):
            m_repo_cls.return_value.list = AsyncMock(side_effect=RuntimeError("db down"))

            _, context, pipeline_impl, _, _ = await svc._build_pipeline_context(_request())

        assert pipeline_impl is svc._pipeline
        assert context.project_id == str(PROJECT_ID)
        assert m_repo_cls.call_count == 1  # 兜底分支（L164-169）被触发
        assert m_repo_cls.return_value.list.await_count == 1  # 加载失败 → except（L177-178）

    async def test_static_agent_repo_provided_filters_role_keys(self):
        """_agent_repo 已注入（非 None）→ 不走 SQLiteAgentRepository 兜底（L164 else 分支）；
        list() 成功产 agent_source，按 role_key 过滤（role_key 空的不入表）。"""
        agent_repo = MagicMock()
        agent_repo.list = AsyncMock(
            return_value=[
                SimpleNamespace(role_key="writer", name="写手", system_prompt="p"),
                SimpleNamespace(role_key=None, name="无名", system_prompt="p"),
            ]
        )
        svc, _, _, _ = _build_svc(
            project=_make_project(config=ProjectConfig(agent_roles={"custom_editor": "x"})),
            db_session=None,
            agent_repo=agent_repo,
        )
        svc._get_template = lambda name: _make_template()
        svc._load_template = AsyncMock(return_value=None)
        svc._merge_role_configs = AsyncMock(return_value=[_make_stage()])
        with (
            patch(
                "inkflow.domain.services.agent_service._apply_agent_order",
                return_value=[_make_stage()],
            ),
            patch(
                "inkflow.domain.services.agent_service._apply_agent_relations",
                return_value=([_make_stage()], []),
            ),
        ):
            stages, _, pipeline_impl, _, _ = await svc._build_pipeline_context(_request())

        assert pipeline_impl is svc._pipeline
        assert len(stages) == 1
        assert agent_repo.list.await_count == 1  # 已注入 repo → 走 L170 分支

    async def test_static_happy_path_skips_agent_repo_when_all_none(self):
        """全 None 静态装配：chapter 存在（L131 else）、agent_roles 含 None 值（L140 else）、
        _agent_repo=None 且 _db_session=None（L164 else → L170 else 跳过 agent_source）。"""
        config = ProjectConfig(agent_roles={"custom_editor": "x", "empty_role": None})
        svc, _, _, _ = _build_svc(
            project=_make_project(config=config),
            chapter=SimpleNamespace(id=CHAPTER_ID, title="第一章"),
        )
        svc._get_template = lambda name: _make_template()
        svc._load_template = AsyncMock(return_value=None)
        svc._merge_role_configs = AsyncMock(return_value=[_make_stage()])
        with (
            patch(
                "inkflow.domain.services.agent_service._apply_agent_order",
                return_value=[_make_stage()],
            ),
            patch(
                "inkflow.domain.services.agent_service._apply_agent_relations",
                return_value=([_make_stage()], []),
            ),
        ):
            (
                stages,
                context,
                pipeline_impl,
                conditional_edges,
                _,
            ) = await svc._build_pipeline_context(_request(chapter_id=CHAPTER_ID))

        assert pipeline_impl is svc._pipeline
        assert len(stages) == 1
        assert context.chapter_id == str(CHAPTER_ID)
        assert conditional_edges == []


# ── TestInjectContext: 设定注入 + 前文摘要 + 回退 ──


class TestInjectContext:
    """_inject_context：setting_context/continue_context 合并与各自失败回退。"""

    async def test_inject_setting_and_continue_context(self):
        """设定注入 + continue_context 前文摘要 → variables 合并更新。"""
        svc, _, _, _ = _build_svc()
        svc._assemble_setting_context = AsyncMock(return_value={"x": "1", "setting": "世界观"})
        svc._assemble_continue_context = AsyncMock(
            return_value={"x": "1", "setting": "世界观", "context": "第一章摘要"}
        )
        context = PipelineContext(project_id="proj", chapter_id="chap", variables={"x": "1"})

        await svc._inject_context(context, continue_context=True)

        assert context.variables["setting"] == "世界观"
        assert context.variables["context"] == "第一章摘要"
        svc._assemble_setting_context.assert_awaited_once()
        svc._assemble_continue_context.assert_awaited_once()

    async def test_inject_setting_failure_keeps_request_vars(self):
        """设定注入失败 → warning 回退请求变量（不抛异常）。"""
        svc, _, _, _ = _build_svc()
        svc._assemble_setting_context = AsyncMock(side_effect=RuntimeError("设定读取失败"))
        svc._assemble_continue_context = AsyncMock(return_value={"x": "1"})
        context = PipelineContext(project_id="proj", variables={"x": "1"})

        await svc._inject_context(context, continue_context=False)

        assert context.variables["x"] == "1"
        assert svc._assemble_continue_context.await_count == 0

    async def test_inject_continue_assembly_failure_falls_back(self):
        """前文摘要组装失败 → warning 回退（不抛异常）；continue_context=True 时触发。"""
        svc, _, _, _ = _build_svc()
        svc._assemble_setting_context = AsyncMock(return_value={"x": "1"})
        svc._assemble_continue_context = AsyncMock(side_effect=RuntimeError("摘要失败"))
        context = PipelineContext(project_id="proj", chapter_id="chap", variables={"x": "1"})

        await svc._inject_context(context, continue_context=True)  # 不抛异常

        assert context.variables["x"] == "1"
        svc._assemble_continue_context.assert_awaited_once()


# ── #681 流式进度：update_stages 写真实 stage 快照（agent_service_stream.py:89-94）─────
#
# G5a 实锤：stream_pipeline 内 `update_stages(..., stages=[], ...)` 恒写空 stages（:89-94），
# 前端 PipelineStatus 无阶段数据可渲染。RED 锁定：pipeline stream 产出 type='stage' 帧时，
# update_stages 应收到真实 stage 快照（非空，stage_id 保留）。无 stage 帧（纯 delta/done）
# 的既有用例保持 stages=[] 兼容（GREEN 用 getattr 防御收集）。


class TestStreamPipelineStageSnapshot:
    """#681：stream_pipeline 收集 stage 帧 → update_stages 写真实 stage 快照。"""

    def _stage_ev(self, stage_id: str, stage_name: str):
        return SimpleNamespace(
            type="stage",
            done=False,
            delta="",
            final_output="",
            intent=None,
            error="",
            execution_id="",
            stage_id=stage_id,
            stage_name=stage_name,
        )

    def _delta_ev(self, delta: str):
        return SimpleNamespace(
            type="delta",
            done=False,
            delta=delta,
            final_output="",
            intent=None,
            error="",
            execution_id="",
        )

    def _done_ev(self, final_output: str):
        return SimpleNamespace(
            type="done",
            done=True,
            delta="",
            final_output=final_output,
            intent="content",
            error="",
            execution_id="",
        )

    async def test_update_stages_collects_stage_frames_to_snapshot(self) -> None:
        """stream 产出 stage 帧 → update_stages 的 stages 非空且 stage_id 按序保留。"""
        events = [
            self._stage_ev("architect", "架构师"),
            self._delta_ev("架构大纲"),
            self._stage_ev("writer", "写手"),
            self._delta_ev("章节正文"),
            self._done_ev("修订稿"),
        ]
        pipeline_impl = MockStreamPipeline(events=events)
        svc, store, _, _ = _build_svc(pipeline=pipeline_impl)
        svc._build_pipeline_context = AsyncMock(
            return_value=([], PipelineContext(project_id=str(PROJECT_ID)), pipeline_impl, [], [])
        )
        svc._inject_context = AsyncMock()

        frames = [ev async for ev in svc.stream_pipeline(_request())]

        # RED：当前实现 update_stages(stages=[]) → store.update_calls[-1]['stages'] 为空
        assert store.update_calls[-1]["status"] == "completed"
        stages = store.update_calls[-1]["stages"]
        assert stages != []
        assert [s["stage_id"] for s in stages] == ["architect", "writer"]
        # 每个 stage 快照含 status 字段（running/complete 语义由 GREEN 定，此处锁字段存在）
        assert all("status" in s for s in stages)
        # 帧序保留（stage/delta 均透传前端）
        assert [ev.type for ev in frames if ev.type in ("stage", "delta")] == [
            "stage",
            "delta",
            "stage",
            "delta",
        ]

    async def test_update_stages_no_stage_frames_keeps_empty(self) -> None:
        """无 stage 帧（纯 delta/done）→ stages 保持 []（既有路径兼容，不破坏）。"""
        events = [
            self._delta_ev("你好"),
            self._done_ev("你好"),
        ]
        pipeline_impl = MockStreamPipeline(events=events)
        svc, store, _, _ = _build_svc(pipeline=pipeline_impl)
        svc._build_pipeline_context = AsyncMock(
            return_value=([], PipelineContext(project_id=str(PROJECT_ID)), pipeline_impl, [], [])
        )
        svc._inject_context = AsyncMock()

        _ = [ev async for ev in svc.stream_pipeline(_request())]

        assert store.update_calls[-1]["status"] == "completed"
        assert store.update_calls[-1]["stages"] == []
