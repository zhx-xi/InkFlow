"""#642-1 管线 SSE 流式装配与执行 — AgentService 增量 mixin。

agent_service.py 已贴 900 行护栏，本批 stream_pipeline/_build_pipeline_context/
_inject_context 抽至本 mixin（AGENTS.md monster-file 纪律 + 任务书 §2.4「抽 mixin」）。
领域层约束不变：不 import langchain/langgraph；PipelineStreamEvent 来自 domain ports。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Sequence
from typing import Any

from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest
from inkflow.domain.models.project import AgentRelation
from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineStage,
    PipelineStreamEvent,
)

logger = logging.getLogger(__name__)


class AgentServiceStreamMixin:
    """AgentService 的 #642-1 增量方法（与主类同实例装配）。

    依赖（self._project_repo / _store / _pipeline ...）由 AgentService.__init__ 注入，
    此处声明仅为 mypy 可见性（mixin 单独检查时无 __init__ 定义）。
    """

    _project_repo: Any
    _chapter_repo: Any
    _get_template: Any
    _load_template: Any
    _merge_role_configs: Any
    _assemble_setting_context: Any
    _assemble_continue_context: Any
    _pipeline: Any
    _supervisor_pipeline: Any
    _store: Any
    _agent_repo: Any
    _db_session: Any
    execute: Any
    get_status: Any

    async def stream_pipeline(
        self, request: PipelineExecuteRequest
    ) -> AsyncGenerator[PipelineStreamEvent, None]:
        """#642-1：管线 SSE 流式执行（static → pipeline.stream 帧流；supervisor 降级轮询）。"""
        stages, context, pipeline_impl, conditional_edges, _ = await self._build_pipeline_context(
            request
        )
        stream_fn = getattr(pipeline_impl, "stream", None)
        if stream_fn is None:
            # supervisor 无 stream → 降级 execute 后台任务 + 轮询（本批不实现 supervisor 流式）
            execution_id = (await self.execute(request))["execution_id"]
            status = await self.get_status(execution_id)
            while status is None or status["status"] == "pending":
                await asyncio.sleep(0.05)
                status = await self.get_status(execution_id)
            yield PipelineStreamEvent(
                type="done",
                done=True,
                execution_id=execution_id,
                final_output=(status or {}).get("final_output", ""),
                intent="content",
            )
            return
        execution = await self._store.create_execution(
            pipeline=request.pipeline,
            project_id=str(request.project_id),
            chapter_id=str(request.chapter_id) if request.chapter_id else None,
        )
        await self._inject_context(
            context,
            continue_context=(
                request.pipeline == "builtin:write_continue" and request.chapter_id is not None
            ),
        )
        final_output = ""
        stage_snapshots: list[dict] = []
        try:
            async for ev in stream_fn(stages, context, conditional_edges=conditional_edges):
                if getattr(ev, "type", "") == "stage":
                    # #681：stage 帧 → 阶段快照（status=running，其余字段默认值；后端无总阶段数）
                    stage_snapshots.append(
                        {
                            "stage_id": ev.stage_id,
                            "status": "running",
                            "output": "",
                            "error": "",
                            "retry_count": 0,
                            "duration_ms": 0,
                        }
                    )
                    yield ev
                elif ev.done:
                    final_output = ev.final_output
                    ev.execution_id = execution.id
                    yield ev
                else:
                    yield ev
            await self._store.update_stages(
                execution_id=execution.id,
                stages=stage_snapshots,
                status="completed",
                final_output=final_output,
            )
        except Exception as e:
            await self._store.update_stages(
                execution_id=execution.id,
                stages=stage_snapshots,
                status="failed",
                error=str(e),
            )
            yield PipelineStreamEvent(type="done", done=True, error=str(e))

    async def _build_pipeline_context(
        self, request: PipelineExecuteRequest
    ) -> tuple[
        list[PipelineStage],
        PipelineContext,
        Any,
        list[tuple[str, str]],
        Sequence[AgentRelation],
    ]:
        """#642-1 公共装配：项目/模板/章节校验 + 拓扑 + context（execute/stream 共用）。"""
        from inkflow.domain.services.agent_service import (  # 延迟导入规避循环依赖
            AgentServiceError,
            _apply_agent_order,
            _apply_agent_relations,
            _project_role_models,
        )

        # 1. 验证项目存在（真实仓储 get 接收 ORM int id，UUID(int=orm_id) 可逆转换）
        project = await self._project_repo.get(request.project_id.int)
        if project is None:
            raise AgentServiceError("项目不存在")

        # 2. 获取模板
        template = self._get_template(request.pipeline)
        if template is None:
            raise AgentServiceError(f"未知管线模板: {request.pipeline}")

        # 3. 验证章节（如果提供）
        if request.chapter_id is not None:
            chapter = await self._chapter_repo.get_chapter(request.chapter_id.int)
            if chapter is None:
                raise AgentServiceError("章节不存在")

        # 4. 执行拓扑装配（F3 定稿）：读 agent_* 得启用集合 → _apply_agent_order
        #    （双模式/跳过过滤/自定义 stage 构造/重排/边重建/C2 终点校验）→ 合并角色配置
        project_role_models = _project_role_models(project.config)
        enabled_roles = {f"agent_{k}" for k, v in project_role_models.items() if v is not None}
        # F42 #295：启用角色口径 = 内置 agent_* 非 null ∪ agent_roles 非 null
        for field, value in (project.config.agent_roles or {}).items():
            if value is not None:
                enabled_roles.add(field)
        project_template = await self._load_template(project.config)
        # F46 #270（spec §5.1）：static 模式叠加 agent_relations 显式边并收集
        # conditional_edges；supervisor 模式不消费 agent_relations（§5.5，保持空）
        conditional_edges: list[tuple[str, str]] = []
        if request.mode == "supervisor":
            # supervisor 模式（spec §5.1）：角色池 = 模板 stages（装配模型/温度/prompt，不静态重排；
            # _apply_agent_order 只在 static 模式调用——supervisor 动态路由取代静态拓扑）
            if request.supervisor is None:
                raise AgentServiceError("supervisor 配置缺失")
            template_stages = list(template.stages)
            stages = await self._merge_role_configs(
                template_stages, project.config, request.role_overrides
            )
            pipeline_impl = self._supervisor_pipeline
            if pipeline_impl is None:
                raise AgentServiceError("supervisor 模式未装配")
        else:
            # v1.5 #484（spec §5.7.4）：装配 Agent 真源（role_key → {name, system_prompt}）
            # 供 _apply_agent_order 构造模板缺失角色占位 stage；未注入/加载失败 → 降级模板装配
            agent_source = None
            # getattr 防御：既有测试以 __new__ 构造（绕过 __init__）时属性缺省 → None
            agent_repo = getattr(self, "_agent_repo", None)
            if agent_repo is None and getattr(self, "_db_session", None) is not None:
                from inkflow.infrastructure.database.repositories.agent_repo import (
                    SQLiteAgentRepository,
                )

                agent_repo = SQLiteAgentRepository(self._db_session)
            if agent_repo is not None:
                try:
                    agent_source = {
                        a.role_key: {"name": a.name, "system_prompt": a.system_prompt}
                        for a in await agent_repo.list()
                        if a.role_key
                    }
                except Exception:
                    logger.warning("Agent 真源加载失败，降级模板 roles 装配", exc_info=True)
            stages = _apply_agent_order(
                template.stages,
                project.config.agent_order,
                enabled_roles,
                project_template.roles if project_template else None,
                agent_source,
            )
            stages, conditional_edges = _apply_agent_relations(
                stages, project.config.agent_relations, enabled_roles
            )
            stages = await self._merge_role_configs(stages, project.config, request.role_overrides)
            pipeline_impl = self._pipeline

        context = PipelineContext(
            project_id=str(request.project_id),
            chapter_id=str(request.chapter_id) if request.chapter_id else None,
            variables=request.variables,
        )
        return (
            stages,
            context,
            pipeline_impl,
            conditional_edges,
            project.config.agent_relations,
        )

    async def _inject_context(self, context: PipelineContext, *, continue_context: bool) -> None:
        """设定库/前文摘要注入（_run_pipeline 与 stream_pipeline 共用，#366 G1/#318）。"""
        # #366 G1 设定驱动写作：无条件注入设定库摘要（角色/世界观/大纲）
        try:
            context.variables = await self._assemble_setting_context(
                context.project_id, context.variables
            )
        except Exception:
            logger.warning("设定注入失败，回退请求变量", exc_info=True)
        if continue_context:
            try:
                context.variables = await self._assemble_continue_context(
                    context.project_id, context.chapter_id, context.variables
                )
            except Exception:
                logger.warning("前文摘要组装失败，回退请求变量", exc_info=True)
