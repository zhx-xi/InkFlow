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
from inkflow.domain.models.project import ProjectConfig
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
    ):
        # 延迟导入避免循环依赖
        from inkflow.infrastructure.agent.execution_store import ExecutionStore
        from inkflow.infrastructure.agent.pipeline_templates import get_template, list_templates
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

        # 4. 合并角色配置
        stages = self._merge_role_configs(template.stages, project.config, request.role_overrides)

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
        asyncio.create_task(self._run_pipeline(execution.id, stages, context))

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

    def _merge_role_configs(
        self,
        stages: list[PipelineStage],
        project_config: ProjectConfig,
        role_overrides: dict[str, RoleOverride] | None,
    ) -> list[PipelineStage]:
        """合并角色配置: 模板默认 < 项目配置 < role_overrides。

        合并策略:
        1. 模板中定义的 AgentRole 是基础
        2. 项目配置中的 agent_architect/writer/auditor/reviser 覆盖对应角色的 model
        3. project_config.temperature 作为默认温度（如果角色未自定义温度）
        4. role_overrides 优先级最高，直接覆盖对应角色字段
        """
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

            # 项目配置覆盖 model
            project_model = project_role_models.get(stage.id)
            if project_model:
                new_agent.model = project_model

            # 项目默认 temperature（如果角色未设）
            if agent.temperature == 0.7:  # 使用模板默认值时替换
                new_agent.temperature = project_config.temperature

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
