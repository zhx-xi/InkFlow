"""Agent 管线服务 — 编排 Agent 管线执行流程。"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any

from inkflow.domain.models.agent_pipeline import (
    PipelineConfig,
    PipelineExecuteRequest,
    RoleOverride,
)
from inkflow.domain.models.agent_template import RoleTemplate
from inkflow.domain.models.project import AGENT_DEFAULT_SENTINEL, ProjectConfig
from inkflow.domain.ports.agent_pipeline import (
    AgentPipelineProtocol,
    PipelineContext,
    PipelineError,
    PipelineStage,
)

logger = logging.getLogger(__name__)


class AgentServiceError(Exception):
    """Agent 服务层异常。"""

    pass


class AgentService:
    """Agent 管线服务 — 执行管线、查询状态、校验配置。"""

    def __init__(
        self,
        pipeline: AgentPipelineProtocol,
        db_session,  # AsyncSession
        *,
        store: Any = None,
        project_repo: Any = None,
        chapter_repo: Any = None,
        template_repo: Any = None,
    ):
        # 延迟导入避免循环依赖
        from inkflow.infrastructure.agent.execution_store import ExecutionStore
        from inkflow.infrastructure.agent.pipeline_templates import get_template, list_templates
        from inkflow.infrastructure.database.repositories.agent_template_repo import (
            SQLiteAgentTemplateRepository,
        )
        from inkflow.infrastructure.database.repositories.chapter_repo import (
            SQLiteChapterRepository,
        )
        from inkflow.infrastructure.database.repositories.project_repo import (
            SQLiteProjectRepository,
        )

        self._pipeline = pipeline
        self._store = store or ExecutionStore(db_session)
        self._project_repo = project_repo or SQLiteProjectRepository(db_session)
        self._chapter_repo = chapter_repo or SQLiteChapterRepository(db_session)
        self._template_repo = template_repo or SQLiteAgentTemplateRepository(db_session)
        self._get_template = get_template
        self._list_templates = list_templates

    async def execute(self, request: PipelineExecuteRequest) -> dict:
        """创建并启动管线执行（异步后台任务）。

        Returns:
            {"execution_id": str, "pipeline": str, "project_id": str,
             "status": "pending", "created_at": str}
        """
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

        # 4. 合并角色配置（引用式模板装配 + 每角色独立温度链）
        stages = await self._merge_role_configs(
            template.stages, project.config, request.role_overrides
        )

        # 5. 创建执行记录
        execution = await self._store.create_execution(
            pipeline=request.pipeline,
            project_id=str(request.project_id),
            chapter_id=str(request.chapter_id) if request.chapter_id else None,
        )

        # 6. 启动后台异步执行（fire-and-forget）
        context = PipelineContext(
            project_id=str(request.project_id),
            chapter_id=str(request.chapter_id) if request.chapter_id else None,
            variables=request.variables,
        )
        task = asyncio.create_task(self._run_pipeline(execution.id, stages, context))
        # fire-and-forget: 持有引用防止任务被 GC 提前回收；异常在 _run_pipeline 内部捕获
        task.add_done_callback(lambda t: t.exception())

        return {
            "execution_id": execution.id,
            "pipeline": request.pipeline,
            "project_id": str(request.project_id),
            "status": "pending",
            "created_at": execution.created_at.isoformat() if execution.created_at else "",
        }

    async def get_status(self, execution_id: str) -> dict | None:
        """查询执行状态。"""
        execution = await self._store.get_execution(execution_id)
        if execution is None:
            return None
        return {
            "execution_id": execution.id,
            "pipeline": execution.pipeline,
            "project_id": execution.project_id,
            "status": execution.status,
            "stages": execution.stages,
            "final_output": execution.final_output,
            "total_duration_ms": execution.total_duration_ms,
            "error": execution.error,
        }

    async def list_executions(self, project_id: str, limit: int = 20) -> dict:
        """分页查询执行记录。"""
        items, total = await self._store.list_executions(project_id, limit)
        return {
            "items": [
                {
                    "execution_id": item.id,
                    "pipeline": item.pipeline,
                    "status": item.status,
                    "created_at": item.created_at.isoformat() if item.created_at else "",
                    "total_duration_ms": item.total_duration_ms,
                }
                for item in items
            ],
            "total": total,
        }

    def validate_pipeline(self, config: PipelineConfig) -> dict:
        """校验管线配置（转发 Protocol.validate）。"""
        errors = self._pipeline.validate(config.stages)
        return {"valid": len(errors) == 0, "errors": errors}

    def list_templates(self) -> dict:
        """列出所有内置模板。"""
        return {"items": self._list_templates()}

    async def _merge_role_configs(
        self,
        stages: list[PipelineStage],
        project_config: ProjectConfig,
        role_overrides: dict[str, RoleOverride] | None,
    ) -> list[PipelineStage]:
        """合并角色配置: 引用式模板装配 + 每角色独立温度链 + role_overrides 最高优先级。

        合并策略（spec §9.2.3 引用式生成机制）:
        1. 项目 config.template_id（str，JSON 存储）→ int 转换 → template_repo.get
           运行时读取 AgentTemplate；转换失败 / 模板不存在 → 跳过装配（回退内置
           管线模板，等价无 template_id 旧项目）
        2. 温度解析链（每角色独立，首个非 None 即止）:
           ① 项目 config 每角色温度字段 role_<role>_temperature（非 None 即覆盖）
           ② 模板 roles[role].temperature（缺省 key → RoleTemplate()，temperature
              None 不覆盖）
           ③ 模板 default_temperature（非 None，全角色兜底）
           ④ 内置管线模板 AgentRole.temperature（architect=None / writer=0.8 /
              auditor=0.5 / reviser=0.6）
           ⑤ 项目 config.temperature（保底；默认 0.7 恒非 None → 链 5 恒有值）
        3. 模型装配: 模板 role 的 model 仅当 enabled=True 且 model 非 None 时覆盖；
           随后项目 agent_* 非空仍覆盖（用户拍板 Q1=A，项目优先）；最后
           role_overrides 覆盖（优先级最高，既有语义不变）
        """
        # 引用式模板读取：template_id 为 str → int 转换；失败 / 不存在 → template=None
        template = None
        if project_config.template_id is not None:
            try:
                int_id = int(project_config.template_id)
            except ValueError:
                int_id = None
            if int_id is not None:
                template = await self._template_repo.get(int_id)

        # 项目配置的角色映射
        project_role_models = {
            "architect": project_config.agent_architect,
            "writer": project_config.agent_writer,
            "auditor": project_config.agent_auditor,
            "reviser": project_config.agent_reviser,
        }

        merged = []
        for stage in stages:
            agent = stage.agent
            # 浅拷贝 AgentRole（Pydantic BaseModel，copy.copy 走 __copy__ → model_copy）
            new_agent = copy.copy(agent)

            # 模板角色子模型（缺省 key → RoleTemplate() 默认，model/temperature 均不覆盖）
            role_template = RoleTemplate()
            if template is not None:
                role_template = template.roles.get(stage.id, RoleTemplate())

            # 温度链（每角色独立，首个非 None 即止；0.7 哨兵已移除）
            temperature = getattr(project_config, f"role_{stage.id}_temperature", None)
            if temperature is None:
                temperature = role_template.temperature
            if temperature is None and template is not None:
                temperature = template.default_temperature
            if temperature is None:
                temperature = agent.temperature
            if temperature is None:
                temperature = project_config.temperature
            new_agent.temperature = temperature

            # 模型装配：模板 role 仅 enabled=True 且 model 非 None 覆盖
            if role_template.enabled and role_template.model is not None:
                new_agent.model = role_template.model

            # 项目配置覆盖 model（用户拍板 Q1=A：项目 agent_* 非空仍覆盖模板）
            project_model = project_role_models.get(stage.id)
            # F42 #268（spec §5.1）：sentinel = 跟随默认 → 不覆盖（v1.0 缺陷：
            # 非空即覆盖 → model="__default__" → parse_model_string ValueError）；
            # 裸模型名（无 /）→ warning + 不覆盖（Q3 兼容策略，存量数据零迁移）
            if project_model and project_model != AGENT_DEFAULT_SENTINEL:
                if "/" not in project_model:
                    logger.warning(
                        "agent_%s 裸模型名 %r 格式不合规（应为 provider/model），回退跟随默认",
                        stage.id,
                        project_model,
                    )
                else:
                    new_agent.model = project_model

            # role_overrides 最高优先级
            if role_overrides and stage.id in role_overrides:
                override = role_overrides[stage.id]
                if override.prompt is not None:
                    new_agent.system_prompt = override.prompt
                if override.model is not None:
                    new_agent.model = override.model
                if override.temperature is not None:
                    new_agent.temperature = override.temperature

            merged.append(
                PipelineStage(
                    id=stage.id,
                    name=stage.name,
                    agent=new_agent,
                    input_from=stage.input_from,
                    output_to=stage.output_to,
                    max_retries=stage.max_retries,
                    required=stage.required,
                )
            )
        return merged

    async def _run_pipeline(
        self,
        execution_id: str,
        stages: list[PipelineStage],
        context: PipelineContext,
    ) -> None:
        """后台执行管线，更新 stages 快照到 ExecutionStore。"""
        try:
            result = await self._pipeline.execute(stages, context)
            stages_snapshot = [
                {
                    "stage_id": sr.stage_id,
                    "status": sr.status.value,
                    "output": sr.output,
                    "error": sr.error,
                    "retry_count": sr.retry_count,
                    "duration_ms": sr.duration_ms,
                }
                for sr in result.stages
            ]
            await self._store.update_stages(
                execution_id=execution_id,
                stages=stages_snapshot,
                status=result.status.value,
                final_output=result.final_output,
                total_duration_ms=result.total_duration_ms,
            )
        except PipelineError as e:
            await self._store.update_stages(
                execution_id=execution_id,
                stages=[],
                status="failed",
                error=str(e),
            )
        except Exception as e:
            logger.exception("管线执行未预期错误")
            await self._store.update_stages(
                execution_id=execution_id,
                stages=[],
                status="failed",
                error=f"执行异常: {e}",
            )
