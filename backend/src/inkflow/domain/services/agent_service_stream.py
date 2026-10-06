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
from inkflow.domain.models.context import ContextOverride
from inkflow.domain.models.project import AgentRelation
from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineStage,
    PipelineStreamEvent,
)
from inkflow.domain.services.model_resolution import resolve_reasoning_effort

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
    ) -> AsyncGenerator[PipelineStreamEvent]:
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
        # #1349：注入明细落库（写回锚点紧跟 create_execution，注入先于 stage 流）
        injection_detail = await self._inject_context(
            context,
            continue_context=(
                request.pipeline == "builtin:write_continue" and request.chapter_id is not None
            ),
            override=request.override,
        )
        await self._persist_injection_detail(execution.id, injection_detail)
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
            _build_custom_stages,
            _project_role_models,
        )

        # 1. 验证项目存在（#1291：project_repo.get 入参为领域 UUID）
        project = await self._project_repo.get(request.project_id)
        if project is None:
            raise AgentServiceError("项目不存在")

        # F59-M4：step 1 后解析思考档位（项目 > 全局；全空 → "default" 恒非 None）
        from inkflow.core.config import config  # F59-M4: 全局兜底档位

        effort = resolve_reasoning_effort(
            None,
            project.config.reasoning_effort,
            config.llm_reasoning_effort,
        )

        # 2. 获取模板（#1475：仅内置通道查模板表；自定义 stage/YAML 通道的 pipeline
        #    是用户标识字符串（role 串 / 文件路径），查内置表必落空 → 不查）
        template: Any = None
        if request.pipeline_config is None and request.stages is None:
            template = self._get_template(request.pipeline)
            if template is None:
                raise AgentServiceError(f"未知管线模板: {request.pipeline}")

        # 3. 验证章节（如果提供）
        if request.chapter_id is not None:
            chapter = await self._chapter_repo.get_chapter(request.chapter_id)
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
        agents_by_role: dict[str, Any] = {}
        if request.mode == "supervisor":
            # supervisor 模式（spec §5.1）：角色池 = 模板 stages（装配模型/温度/prompt，不静态重排；
            # _apply_agent_order 只在 static 模式调用——supervisor 动态路由取代静态拓扑）
            # #1472/#1473：supervisor 路径同样取 Agent 真源以装配有效技能集（显式 ∪ 通用）
            agents_by_role, mounted_skill_names = await self._load_agents_by_role()
            if request.supervisor is None:
                raise AgentServiceError("supervisor 配置缺失")
            # 自定义通道 + supervisor 已被 DTO 拦掉（§5.8.1 约束 2）→ 此处 template 必非 None
            if template is None:
                raise AgentServiceError("自定义 stage 仅支持 static 模式")
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
            # #1472/#1473：同一真源同时携带 skill_ids，供下方 _attach_agent_skills 装配管线 stage；
            # mounted_skill_names = 全库挂载集（通用判据）
            agents_by_role, mounted_skill_names = await self._load_agents_by_role()
            # #1475（spec §5.8.2/§5.8.3）：自定义通道 = 用户显式给定拓扑 →
            # 旁路 agent_order / agent_relations（再重排会让点名的角色被静默摘除），
            # 拓扑先过真实引擎 validate（同步拒绝，不落注定失败的执行记录），
            # 再走既有 _merge_role_configs 装配链。
            if request.pipeline_config is not None or request.stages is not None:
                if request.pipeline_config is not None:
                    template_stages = list(request.pipeline_config.stages)
                else:
                    try:
                        template_stages = _build_custom_stages(request.stages or [], agents_by_role)
                    except ValueError as exc:
                        raise AgentServiceError(str(exc)) from exc
                errors = self._pipeline.validate(template_stages)
                if errors:
                    raise AgentServiceError("自定义管线配置无效: " + "; ".join(errors))
                stages = await self._merge_role_configs(
                    template_stages, project.config, request.role_overrides
                )
                pipeline_impl = self._pipeline
            else:
                agent_source = (
                    {
                        role: {"name": agent.name, "system_prompt": agent.system_prompt}
                        for role, agent in agents_by_role.items()
                    }
                    if agents_by_role
                    else None
                )
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
                stages = await self._merge_role_configs(
                    stages, project.config, request.role_overrides
                )
                pipeline_impl = self._pipeline

        # #1472/#1473：管线 stage prompt 装配有效技能集（显式 ∪ 通用，static/supervisor 共用）
        stages = self._attach_agent_skills(stages, agents_by_role, mounted_skill_names)
        context = PipelineContext(
            project_id=str(request.project_id),
            chapter_id=str(request.chapter_id) if request.chapter_id else None,
            variables=request.variables,
            reasoning_effort=effort,
        )
        return (
            stages,
            context,
            pipeline_impl,
            conditional_edges,
            project.config.agent_relations,
        )

    async def _load_agents_by_role(self) -> tuple[dict[str, Any], set[str]]:
        """加载 Agent 真源：role_key → Agent 领域对象（含 skill_ids）+ 全库挂载 skill 名集合。

        #484/#1472 真源供 static 占位 stage（`_apply_agent_order`）与管线 skill
        装配共用。**同时**返回全库（含无 `role_key` 的自定义 Agent）`skill_ids`
        并集——#1473 通用 skill 的判据（「未被**任何** Agent 挂载」= 通用）必须覆盖
        全部 Agent，而 role 映射只取带 `role_key` 者（无 role 者不会成为 stage）。
        未注入 `_agent_repo` 且持有 `_db_session` → `SQLiteAgentRepository` 兜底
        （镜像原 static 分支逻辑，getattr 防御 `__new__` 构造的测试实例）；
        加载失败 → warning + 空（降级模板装配，不阻断生成主链路）。
        """
        agent_repo = getattr(self, "_agent_repo", None)
        if agent_repo is None and getattr(self, "_db_session", None) is not None:
            from inkflow.infrastructure.database.repositories.agent_repo import (
                SQLiteAgentRepository,
            )

            agent_repo = SQLiteAgentRepository(self._db_session)
        if agent_repo is None:
            return {}, set()
        try:
            agents = await agent_repo.list()
        except Exception:
            logger.warning("Agent 真源加载失败，降级模板 roles 装配", exc_info=True)
            return {}, set()
        mounted_names = {
            str(skill_id)
            for agent in agents
            for skill_id in (getattr(agent, "skill_ids", None) or [])
        }
        return {a.role_key: a for a in agents if a.role_key}, mounted_names

    def _attach_agent_skills(
        self,
        stages: list[PipelineStage],
        agents_by_role: dict[str, Any],
        mounted_names: set[str],
    ) -> list[PipelineStage]:
        """把各 stage 的**有效技能集**拼到 stage.agent.system_prompt 之后（#1472 + #1473）。

        映射 = `stage.id == Agent.role_key`（内置 architect/writer/auditor/reviser/
        worldview/polisher）。有效技能集 = `agent.skill_ids`（**显式挂载**）∪
        `{skills_root 下未被任何 Agent 挂载的 skill}`（**通用**，对所有 Agent 生效）——
        显式优先（同名去重）；被**其他** Agent 显式挂载的 skill 不算通用（防串味）。
        `mounted_names`（全库 Agent `skill_ids` 并集）由 `_load_agents_by_role` 一次性
        聚合后传入（零额外查询）。Agent 真源缺失 / 无任何有效 skill / 库中无该目录
        → 跳过（prompt 逐字符不变，零回归）。
        """
        if not stages or not agents_by_role:
            return stages
        from inkflow.core.config import config
        from inkflow.domain.services.skill_assembly import (
            append_skills,
            file_skill_lookup,
            resolve_effective_skills,
        )

        skills_root = getattr(self, "_skills_root", None) or (config.data_dir / "skills")
        # 通用集与具体 Agent 无关 → 一次解析，循环复用（explicit_ids=[] ⇒ 只出 general）
        general_names = [
            entry.name
            for entry in resolve_effective_skills(
                skills_root=skills_root, explicit_ids=[], mounted_names=mounted_names
            )
        ]
        has_explicit = any(getattr(agent, "skill_ids", None) for agent in agents_by_role.values())
        if not has_explicit and not general_names:
            return stages

        lookup = file_skill_lookup(skills_root)
        for stage in stages:
            agent = agents_by_role.get(stage.id)
            explicit_ids = list(getattr(agent, "skill_ids", None) or []) if agent else []
            seen = set(explicit_ids)
            skill_ids = [*explicit_ids, *(g for g in general_names if g not in seen)]
            if not skill_ids:
                continue
            stage.agent.system_prompt = append_skills(stage.agent.system_prompt, skill_ids, lookup)
        return stages

    @staticmethod
    def _empty_injection_detail() -> dict[str, list[str]]:
        """#1349：注入明细骨架（三源各一 id 列表）。

        只收「三源」——大纲源无 override 面且非用户可选，不进回执面（issue §UI 语义
        要点只列角色/世界观/伏笔三类；面板勾选面亦只此三类）。
        """
        return {"character_ids": [], "world_ids": [], "foreshadowing_ids": []}

    async def _persist_injection_detail(
        self,
        execution_id: str,
        detail: dict[str, list[str]],
    ) -> None:
        """#1349：把「本次实际注入」明细落到执行记录（章级回执面取数源）。

        失败 → WARNING + 吞掉：回执面是**观测**能力，绝不因落库异常阻断生成主链路
        （镜像 _inject_context 的失败隔离语义）。store 可能无该方法（旧 fake/mock）
        → getattr 防御，保持既有单测零改动。
        """
        persist = getattr(self._store, "update_injected_context", None)
        if persist is None:
            return
        try:
            await persist(execution_id, detail)
        except Exception:
            logger.warning("注入明细落库失败（回执面降级，不影响生成）", exc_info=True)

    async def list_chapter_injections(self, chapter_id: str) -> dict:
        """#1349：章级注入记录回读 —— 最新一次**已有明细**的执行记录。

        取数规则：按 created_at 降序取该章执行记录，返回第一条 injected_context
        非 None 的（旧记录 / 非设定注入类管线无明细 → 继续往前找）。
        全无 → injected_context=None（前端据此回退 assemble 预览态）。
        """
        executions, _ = await self._store.list_chapter_executions(chapter_id)
        for execution in executions:
            if getattr(execution, "injected_context", None) is not None:
                return {
                    "chapter_id": chapter_id,
                    "execution_id": execution.id,
                    "injected_context": execution.injected_context,
                }
        return {"chapter_id": chapter_id, "execution_id": None, "injected_context": None}

    async def _inject_context(
        self,
        context: PipelineContext,
        *,
        continue_context: bool,
        override: ContextOverride | None = None,
    ) -> dict[str, list[str]]:
        """设定库/前文摘要注入（_run_pipeline 与 stream_pipeline 共用，#366 G1/#318）。

        #1319：override 透传至 _assemble_setting_context（勾选通道）；前文摘要无 override 面。
        #1349：回传「本次**实际**注入」的三源 id 明细（供调用方落库 → 章级回执面）。
        明细与 setting 实际产出同源；注入失败/无源装配 → 三键空列表（不是 None，
        调用方无需判空）。
        """
        detail = self._empty_injection_detail()
        # #366 G1 设定驱动写作：无条件注入设定库摘要（角色/世界观/大纲）
        try:
            context.variables = await self._assemble_setting_context(
                context.project_id, context.variables, override, detail
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
        return detail
