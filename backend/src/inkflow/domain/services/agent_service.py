"""Agent 管线服务 — 编排 Agent 管线执行流程。"""

from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from collections import deque
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from inkflow.domain.models.agent_pipeline import (
    PipelineConfig,
    PipelineExecuteRequest,
    RoleOverride,
    SupervisorExecuteConfig,
)
from inkflow.domain.models.agent_template import AgentTemplate, RoleTemplate
from inkflow.domain.models.project import AGENT_DEFAULT_SENTINEL, AgentRelation, ProjectConfig
from inkflow.domain.ports.agent_pipeline import (
    AgentPipelineProtocol,
    AgentRole,
    PipelineContext,
    PipelineError,
    PipelineResult,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.services.agent_service_stream import AgentServiceStreamMixin
from inkflow.domain.services.model_resolution import resolve_model
from inkflow.infrastructure.agent.supervisor_pipeline import HITLInterrupt
from inkflow.logging import log_structured

logger = logging.getLogger(__name__)


def _project_role_models(config: ProjectConfig) -> dict[str, str | None]:
    """内置 6 角色字段名 → 项目配置模型值映射（stage.id 不带 agent_ 前缀，v1.5 #484）。"""
    return {
        "architect": config.agent_architect,
        "writer": config.agent_writer,
        "auditor": config.agent_auditor,
        "reviser": config.agent_reviser,
        "worldview": config.agent_worldview,
        "polisher": config.agent_polisher,
    }


def _apply_agent_order(
    stages: list[PipelineStage],
    agent_order: list[list[str]],
    enabled_roles: set[str],
    template_roles: dict[str, RoleTemplate] | None = None,
    agent_source: dict[str, dict[str, str]] | None = None,
) -> list[PipelineStage]:
    """按 agent_order 层级拓扑重排管线阶段（spec §5.3.1 步骤 2-8 + 裁定 C1-C4）。

    双模式（B1）：agent_order 空 = 默认模板模式 → 原样返回（null 不触发跳过）；
    非空 = 配置驱动模式 → 防御校验 → 跳过过滤 → 层级映射 → 全连接边重建 → 终点角色校验。
    防御回退（warning + 原样返回）：长度 >10 / 跨层重复 / 缺启用角色（C1）/
    终点为 architect/auditor（C2 成品身份）。软降级（C3）：未来层/同层引用由 pipeline_nodes 空注入。
    占位 stage 三级来源（C4 + v1.5 #484，spec §5.7.4）：模板 roles prompt 非 None → 模板；
    agent_source（Agent 实体真源，role_key → {name, system_prompt}）→ 真源；两者皆无 → 跳过。
    """
    if not agent_order:
        return stages

    # 防御校验：长度上限（槽位 0-9）/ 跨层重复（执行层防御，存储层已拦的损坏数据）
    if len(agent_order) > 10:
        log_structured(
            level="WARN",
            caller_type="agent",
            caller_name="agent_service._apply_agent_order",
            event="agent_order_guardrail",
            message_key="log.check.agent_order_guardrail",
            message="agent_order 超过 10 层，回退默认拓扑",
            params={"self_healed": True, "depth": len(agent_order)},
            error_code="E_AGENT_ORDER_TOO_DEEP",
        )
        return stages
    flattened = [role for layer in agent_order for role in layer]
    if len(flattened) != len(set(flattened)):
        log_structured(
            level="WARN",
            caller_type="agent",
            caller_name="agent_service._apply_agent_order",
            event="agent_order_guardrail",
            message_key="log.check.agent_order_guardrail",
            message="agent_order 存在跨层重复角色，回退默认拓扑",
            params={"self_healed": True},
            error_code="E_AGENT_ORDER_DUPLICATE",
        )
        return stages

    # 缺启用角色校验（C1）：启用角色（去 agent_ 前缀）必须全部出现在 order 展开集
    order_roles = {role.removeprefix("agent_") for role in flattened}
    enabled_stage_ids = {role.removeprefix("agent_") for role in enabled_roles}
    missing = enabled_stage_ids - order_roles
    if missing:
        log_structured(
            level="WARN",
            caller_type="agent",
            caller_name="agent_service._apply_agent_order",
            event="agent_order_guardrail",
            message_key="log.check.agent_order_guardrail",
            message="agent_order 缺少启用角色，回退默认拓扑",
            params={"self_healed": True, "missing": sorted(missing)},
            error_code="E_AGENT_ORDER_MISSING_ROLE",
        )
        return stages

    # 跳过过滤（Q2+B1）：配置驱动模式下 null 角色从 order 摘除；空层保留（不影响前序全层集合）
    filtered_layers = [[role for role in layer if role in enabled_roles] for layer in agent_order]

    # 层级映射：agent_xxx → stage.id；模板无此 stage → 占位构造（模板/真源/跳过）
    stage_by_id = {s.id: s for s in stages}
    mapped_layers: list[list[str]] = []
    for layer in filtered_layers:
        mapped: list[str] = []
        for role in layer:
            stage_id = role.removeprefix("agent_")
            if stage_id not in stage_by_id:
                # v1.5 #484（spec §5.7.4）：占位角色三级来源——模板 roles prompt 非 None →
                # 模板装配；否则 agent_source 真源 → name/prompt 取实体；两者皆无 → 跳过
                role_template = (template_roles or {}).get(stage_id)
                source = (agent_source or {}).get(stage_id)
                if role_template is not None and role_template.prompt is not None:
                    placeholder_agent = AgentRole(
                        id=stage_id,
                        name=role_template.name or stage_id,
                        system_prompt=role_template.prompt,
                        model=role_template.model or "openai/gpt-4o",
                        temperature=role_template.temperature,
                    )
                    stage_by_id[stage_id] = PipelineStage(
                        id=stage_id,
                        name=role_template.name or stage_id,
                        agent=placeholder_agent,
                    )
                    mapped.append(stage_id)
                elif source is not None:
                    # model/temperature 不在此硬编码——_merge_role_configs 按默认链装配
                    placeholder_agent = AgentRole(
                        id=stage_id,
                        name=source["name"] or stage_id,
                        system_prompt=source["system_prompt"],
                        temperature=(
                            role_template.temperature if role_template is not None else None
                        ),
                    )
                    stage_by_id[stage_id] = PipelineStage(
                        id=stage_id,
                        name=source["name"] or stage_id,
                        agent=placeholder_agent,
                    )
                    mapped.append(stage_id)
                else:
                    logger.warning(
                        "agent_order 角色 %s 在模板 stages 中无对应阶段（prompt 缺失），跳过",
                        role,
                    )
                continue
            mapped.append(stage_id)
        mapped_layers.append(mapped)

    # 空槽与全部被过滤的层不参与拓扑（非空层计算）
    non_empty_layers = [layer for layer in mapped_layers if layer]
    if not non_empty_layers:
        # 配置驱动模式全部角色关闭/跳过 → 无可执行角色 → 空管线
        return []

    # 终点角色校验（C2 成品身份）：终点为 architect/auditor（非内容产出）→ 回退默认拓扑
    terminal_ids = non_empty_layers[-1]
    if any(sid in ("architect", "auditor") for sid in terminal_ids):
        log_structured(
            level="WARN",
            caller_type="agent",
            caller_name="agent_service._apply_agent_order",
            event="agent_order_guardrail",
            message_key="log.check.agent_order_guardrail",
            message="agent_order 终点角色非内容产出，回退默认拓扑",
            params={"self_healed": True, "terminal": sorted(terminal_ids)},
            error_code="E_AGENT_ORDER_TERMINAL_ROLE",
        )
        return stages

    # 全连接边重建：第 i 层节点 input_from = 前序全部非空层角色；output_to = 后序全部非空层角色
    result: list[PipelineStage] = []
    for i, layer in enumerate(non_empty_layers):
        prev_roles: list[str] = []
        for prev in non_empty_layers[:i]:
            prev_roles.extend(prev)
        next_roles: list[str] = []
        for nxt in non_empty_layers[i + 1 :]:
            next_roles.extend(nxt)
        for stage_id in layer:
            stage = stage_by_id[stage_id]
            result.append(
                PipelineStage(
                    id=stage.id,
                    name=stage.name,
                    agent=stage.agent,
                    input_from=list(prev_roles),
                    output_to=list(next_roles),
                    max_retries=stage.max_retries,
                    required=stage.required,
                )
            )
    return result


def _has_cycle(nodes: set[str], edges: Sequence[tuple[str, str]]) -> bool:
    """Kahn 拓扑排序环检测（spec §5.3.4，域层独立实现）。"""
    indegree = {node: 0 for node in nodes}
    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    for src, dst in edges:
        if src in indegree and dst in indegree:
            adjacency[src].append(dst)
            indegree[dst] += 1
    queue = deque(node for node, degree in indegree.items() if degree == 0)
    processed = 0
    while queue:
        node = queue.popleft()
        processed += 1
        for downstream in adjacency[node]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                queue.append(downstream)
    return processed != len(nodes)


def _transitive_upstream(target_id: str, stages: Sequence[PipelineStage]) -> set[str]:
    """target 在基线的 input_from 传递闭包（F46 #270 同层判定）。"""
    by_id = {s.id: s for s in stages}
    seen: set[str] = set()
    stack = list(by_id[target_id].input_from) if target_id in by_id else []
    while stack:
        stage_id = stack.pop()
        if stage_id in seen:
            continue
        seen.add(stage_id)
        stage = by_id.get(stage_id)
        if stage is not None:
            stack.extend(stage.input_from)
    return seen


def _append_unique(items: Sequence[str], value: str) -> list[str]:
    """追加去重（spec §5.3.1：input_from 已含时不重复）。"""
    result = list(items)
    if value not in result:
        result.append(value)
    return result


def _apply_agent_relations(
    stages: list[PipelineStage],
    agent_relations: Sequence[AgentRelation],
    enabled_roles: set[str],
) -> tuple[list[PipelineStage], list[tuple[str, str]]]:
    """在 agent_order 基线上叠加 agent_relations 显式边（spec §5.3.1，F46 #270）。

    返回 (叠加后 stages, conditional_edges)——conditional_edges 供引擎 add_conditional_edges
    构建条件路由。防御校验（warning + 忽略关系）：死角色引用 / 自身环 / conditional 多后继；
    合成后环检测 → 回退纯基线。
    """
    if not agent_relations:
        return stages, []

    enabled_ids = {role.removeprefix("agent_") for role in enabled_roles}
    stage_by_id = {s.id: s for s in stages}

    # 防御校验：死角色引用 / 自身环 / conditional 多后继（任一 → 忽略全部关系）
    for rel in agent_relations:
        from_id = rel.from_.removeprefix("agent_")
        if from_id not in enabled_ids or from_id not in stage_by_id:
            logger.warning("agent_relations 引用了未启用角色 %s，忽略全部关系", rel.from_)
            return stages, []
        to_id = rel.to.removeprefix("agent_")
        if to_id not in enabled_ids or to_id not in stage_by_id:
            logger.warning("agent_relations 引用了未启用角色 %s，忽略全部关系", rel.to)
            return stages, []

    relation_edges = [
        (rel.from_.removeprefix("agent_"), rel.to.removeprefix("agent_")) for rel in agent_relations
    ]
    relation_nodes = {src for src, _ in relation_edges} | {dst for _, dst in relation_edges}
    if _has_cycle(relation_nodes, relation_edges):
        logger.warning("agent_relations 自身存在循环依赖，忽略全部关系")
        return stages, []

    # conditional 边多后继（A 除 B 外还有其它出边 → 条件 fan-out 归远期）
    outgoing_counts: dict[str, int] = {}
    for rel in agent_relations:
        from_id = rel.from_.removeprefix("agent_")
        outgoing_counts[from_id] = outgoing_counts.get(from_id, 0) + 1
    for rel in agent_relations:
        if rel.type == "conditional":
            from_id = rel.from_.removeprefix("agent_")
            if outgoing_counts.get(from_id, 0) > 1:
                logger.warning(
                    "agent_relations conditional 边 %s 存在多后继，忽略全部关系",
                    rel.from_,
                )
                return stages, []

    # 逐边叠加（关系优先；PipelineStage 为 dataclass，改动需新建实例）
    result = list(stages)
    index_by_id = {s.id: i for i, s in enumerate(result)}
    result_by_id = dict(stage_by_id)

    def _replace_stage(
        stage_id: str,
        *,
        input_from: list[str] | None = None,
        output_to: list[str] | None = None,
    ) -> None:
        """用 dataclasses.replace 新建 PipelineStage 实例并回写列表。"""
        current = result_by_id[stage_id]
        updated = replace(
            current,
            input_from=input_from if input_from is not None else current.input_from,
            output_to=output_to if output_to is not None else current.output_to,
        )
        result_by_id[stage_id] = updated
        result[index_by_id[stage_id]] = updated

    conditional_edges: list[tuple[str, str]] = []
    for rel in agent_relations:
        from_id = rel.from_.removeprefix("agent_")
        to_id = rel.to.removeprefix("agent_")
        # 同层判定：基线中 A ∉ B 的传递前序 → 同层（打破并行）；否则跨层（基线已覆盖）
        same_layer = from_id not in _transitive_upstream(to_id, stages)
        if rel.type == "sequential":
            if not same_layer:
                continue  # 跨层：基线已覆盖时序，无引擎增量（跳过）
            current = result_by_id[from_id]
            _replace_stage(from_id, output_to=_append_unique(current.output_to, to_id))
        elif rel.type == "data":
            # data 边 = 时序 + 注入：双向幂等追加（跨层基线已含时无新效果）
            current_from = result_by_id[from_id]
            current_to = result_by_id[to_id]
            _replace_stage(from_id, output_to=_append_unique(current_from.output_to, to_id))
            _replace_stage(to_id, input_from=_append_unique(current_to.input_from, from_id))
        else:  # conditional
            current_to = result_by_id[to_id]
            _replace_stage(to_id, input_from=_append_unique(current_to.input_from, from_id))
            conditional_edges.append((from_id, to_id))

    # 合成后环检测：对最终 input_from/output_to 图（含条件边注入）Kahn → 有环回退纯基线
    synthesized_edges: list[tuple[str, str]] = []
    for stage in result:
        for upstream_id in stage.input_from:
            synthesized_edges.append((upstream_id, stage.id))
        for downstream_id in stage.output_to:
            synthesized_edges.append((stage.id, downstream_id))
    if _has_cycle({s.id for s in result}, synthesized_edges):
        logger.warning("agent_relations 与 agent_order 合成产生环，忽略关系")
        return stages, []

    return result, conditional_edges


def _stage_snapshots(stage_results: Sequence[StageResult]) -> list[dict]:
    """stages JSON 快照（confirm/_run_pipeline 共用）。"""
    return [
        {
            "stage_id": sr.stage_id,
            "status": sr.status.value,
            "output": sr.output,
            "error": sr.error,
            "retry_count": sr.retry_count,
            "duration_ms": sr.duration_ms,
        }
        for sr in stage_results
    ]


def _build_relations_snapshot(
    agent_relations: Sequence[AgentRelation], stage_results: Sequence[StageResult]
) -> list[dict]:
    """执行记录 relations 快照（spec §5.4）：{from, to, type, gate_result}；
    conditional 目标 COMPLETED 且有输出 → passed 否则 skipped；from/to 去 agent_ 前缀。"""
    result_by_id = {sr.stage_id: sr for sr in stage_results}
    snapshot: list[dict] = []
    for rel in agent_relations:
        from_id = rel.from_.removeprefix("agent_")
        to_id = rel.to.removeprefix("agent_")
        entry: dict[str, str] = {"from": from_id, "to": to_id, "type": rel.type}
        if rel.type == "conditional":
            sr = result_by_id.get(to_id)
            entry["gate_result"] = (
                "passed"
                if (sr is not None and sr.status == StageStatus.COMPLETED and sr.output)
                else "skipped"
            )
        snapshot.append(entry)
    return snapshot


class AgentServiceError(Exception):
    """Agent 服务层异常。"""

    pass


class AgentService(AgentServiceStreamMixin):
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
        supervisor_pipeline: Any = None,
        summary_service: Any = None,
        character_repo: Any = None,
        world_repo: Any = None,
        outline_repo: Any = None,
        agent_repo: Any = None,
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
        self._supervisor_pipeline = supervisor_pipeline
        self._summary_service = summary_service
        self._agent_repo = agent_repo
        self._db_session = db_session
        self._character_repo = character_repo
        self._world_repo = world_repo
        self._outline_repo = outline_repo
        self._store = store or ExecutionStore(db_session)
        self._project_repo = project_repo or SQLiteProjectRepository(db_session)
        self._chapter_repo = chapter_repo or SQLiteChapterRepository(db_session)
        self._template_repo = template_repo or SQLiteAgentTemplateRepository(db_session)
        self._get_template = get_template
        self._list_templates = list_templates

    async def execute(self, request: PipelineExecuteRequest) -> dict:
        """创建并启动管线执行（异步后台任务）。

        Returns: {"execution_id", "pipeline", "project_id", "status", "created_at"} 初始 pending。
        """
        stages, context, pipeline_impl, conditional_edges, agent_relations = (
            await self._build_pipeline_context(request)
        )
        supervisor_config = request.supervisor if request.mode == "supervisor" else None

        # 5. 创建执行记录
        execution = await self._store.create_execution(
            pipeline=request.pipeline,
            project_id=str(request.project_id),
            chapter_id=str(request.chapter_id) if request.chapter_id else None,
        )

        # 6. 启动后台异步执行（fire-and-forget）
        task = asyncio.create_task(
            self._run_pipeline(
                execution.id,
                stages,
                context,
                pipeline=pipeline_impl,
                supervisor_config=supervisor_config,
                continue_context=(
                    request.pipeline == "builtin:write_continue" and request.chapter_id is not None
                ),
                conditional_edges=conditional_edges if request.mode != "supervisor" else [],
                agent_relations=agent_relations,
            )
        )
        task.add_done_callback(lambda t: t.exception())
        if request.mode == "supervisor":
            # supervisor 模式：让出事件循环一次，确保动态路由管线在 execute 返回前启动
            # 并收到 supervisor 配置（HITL 中断时执行记录状态同步写入 waiting_hitl）
            await asyncio.sleep(0)

        return {
            "execution_id": execution.id,
            "pipeline": request.pipeline,
            "project_id": str(request.project_id),
            "status": "pending",
            "created_at": execution.created_at.isoformat() if execution.created_at else "",
            "mode": request.mode,
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
            "relations": getattr(execution, "relations", None) or [],
            "trace": getattr(execution, "trace", []) or [],
            "final_output": execution.final_output,
            "total_duration_ms": execution.total_duration_ms,
            "error": execution.error,
            "hitl_pending": (
                getattr(execution, "hitl_payload", None)
                if execution.status == "waiting_hitl"
                else None
            ),
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

    async def confirm_execution(self, execution_id: str, approved: bool) -> dict:
        """HITL 人工确认：waiting_hitl 执行记录 → resume 继续 / 拒绝回退。"""
        execution = await self._store.get_execution(execution_id)
        if execution is None:
            raise AgentServiceError("执行记录不存在")
        if execution.status != "waiting_hitl":
            raise AgentServiceError("执行记录不在等待确认状态")
        # resume：supervisor pipeline 从 checkpointer 恢复（mock 记录调用参数）
        try:
            result: PipelineResult = await self._supervisor_pipeline.resume(
                interrupt_obj=execution.hitl_payload or {},
                approved=approved,
            )
        except HITLInterrupt as e:
            # 二次中断：resume 命中下一个确认点 → 更新 waiting_hitl + 新 payload
            await self._store.update_status(
                execution_id=execution_id,
                status="waiting_hitl",
                hitl_payload=e.payload,
            )
            return {
                "execution_id": execution_id,
                "status": "waiting_hitl",
                "hitl_pending": e.payload,
                "final_output": "",
            }
        # 成功路径：写完整成品落库（#343 根因 6）；#379 trace 非空才透传
        trace = getattr(result, "trace", []) or []
        confirm_kwargs: dict[str, Any] = {
            "execution_id": execution_id,
            "stages": _stage_snapshots(result.stages),
            "status": result.status.value,
            "final_output": result.final_output,
            "total_duration_ms": result.total_duration_ms,
        }
        if trace:
            confirm_kwargs["trace"] = trace
        await self._store.update_stages(**confirm_kwargs)
        return {
            "execution_id": execution_id,
            "status": result.status.value,
            "final_output": result.final_output,
        }

    def validate_pipeline(self, config: PipelineConfig) -> dict:
        """校验管线配置（转发 Protocol.validate）。"""
        errors = self._pipeline.validate(config.stages)
        return {"valid": len(errors) == 0, "errors": errors}

    def list_templates(self) -> dict:
        """列出所有内置模板。"""
        return {"items": self._list_templates()}

    async def _load_template(self, project_config: ProjectConfig) -> AgentTemplate | None:
        """引用式模板读取：template_id str → int → repo.get；失败/缺失 → None（回退内置模板）。"""
        if project_config.template_id is None:
            return None
        try:
            int_id = int(project_config.template_id)
        except ValueError:
            return None
        return await self._template_repo.get(int_id)

    async def _merge_role_configs(
        self,
        stages: list[PipelineStage],
        project_config: ProjectConfig,
        role_overrides: dict[str, RoleOverride] | None,
    ) -> list[PipelineStage]:
        """合并角色配置（spec §9.2.3）：模板装配 + 温度链 + prompt + role_overrides 最高优先级。

        温度链（首个非 None 即止）：role_<role>_temperature → 模板 roles → 模板
        default_temperature → 内置 AgentRole.temperature → config.temperature。
        模型：模板 role model（enabled）→ 项目 agent_*（Q1=A 项目优先）→ overrides。
        """
        from inkflow.core.config import config  # #520: 项目 model=None 时回退全局默认

        # 引用式模板读取 + 项目配置角色映射（自定义角色三态字段并入，key 去前缀 = stage.id）
        template = await self._load_template(project_config)
        project_role_models = _project_role_models(project_config)
        for field, value in (project_config.agent_roles or {}).items():
            project_role_models[field.removeprefix("agent_")] = value

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

            # 项目配置覆盖 model（Q1=A 项目优先；#367 sentinel=跟随默认 → 回退项目 model）
            project_model = project_role_models.get(stage.id)
            if project_model == AGENT_DEFAULT_SENTINEL:
                new_agent.model = resolve_model(
                    None, project_config.model, config.llm_default_model
                ) or ""
            elif project_model:
                if "/" not in project_model:
                    logger.warning(
                        "agent_%s 裸模型名 %r 格式不合规（应为 provider/model），回退跟随默认",
                        stage.id,
                        project_model,
                    )
                else:
                    new_agent.model = project_model
            elif project_model is None and project_config.template_id is None:
                # #373（方案 B）：未配置角色且无模板引用 → 回退项目 model 驱动路由
                # （template_id 存在时保持既有模板装配语义，spec §9.2.5）
                new_agent.model = resolve_model(
                    None, project_config.model, config.llm_default_model
                ) or ""

            # prompt 覆盖（F42 #295，spec §5.3.4）：模板 roles 定义 prompt 时
            # 覆盖 system_prompt（role_overrides 仍为最高优先级，在下方覆盖）
            if role_template.prompt is not None:
                new_agent.system_prompt = role_template.prompt

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
        pipeline: Any = None,
        supervisor_config: SupervisorExecuteConfig | None = None,
        continue_context: bool = False,
        conditional_edges: list[tuple[str, str]] | None = None,
        agent_relations: Sequence[AgentRelation] | None = None,
    ) -> None:
        """后台执行管线，更新 stages/relations 快照到 ExecutionStore。"""
        pipeline = pipeline or self._pipeline
        await self._inject_context(context, continue_context=continue_context)
        try:
            if supervisor_config is not None:
                result: PipelineResult = await pipeline.execute(
                    stages, context, supervisor=supervisor_config
                )
            else:
                result = await pipeline.execute(
                    stages, context, conditional_edges=conditional_edges or []
                )
            relations_snapshot = _build_relations_snapshot(agent_relations or [], result.stages)
            stages_snapshot = _stage_snapshots(result.stages)
            # F47 #379：trace 非空才透传（空则 store 默认 []；兼容既有 Mock 签名）
            trace = getattr(result, "trace", []) or []
            run_kwargs: dict[str, Any] = {
                "execution_id": execution_id,
                "stages": stages_snapshot,
                "status": result.status.value,
                "final_output": result.final_output,
                "total_duration_ms": result.total_duration_ms,
                "relations": relations_snapshot,
            }
            if trace:
                run_kwargs["trace"] = trace
            await self._store.update_stages(**run_kwargs)
        except HITLInterrupt as e:
            # HITL 中断：落 waiting_hitl + payload 等待确认
            await self._store.update_status(
                execution_id=execution_id,
                status="waiting_hitl",
                hitl_payload=e.payload,
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

    async def _assemble_setting_context(
        self, project_id: str, variables: dict[str, str]
    ) -> dict[str, str]:
        """设定库摘要注入（#366 G1）：角色/世界观/大纲三源，非空注入 variables["setting"]。
        单源/整体异常 → WARNING + 回退（失败隔离，不阻断管线）。
        """
        if self._character_repo is None and self._world_repo is None and self._outline_repo is None:
            return variables
        try:
            project_int = uuid.UUID(project_id).int
            project = await self._project_repo.get(project_int)
            if project is None:
                return variables
            parts: list[str] = []
            if self._character_repo is not None:
                try:
                    characters, _ = await self._character_repo.list(project_int, limit=50)
                    for ch in characters:
                        content = ch.personality or ch.background or ch.goals
                        if content:
                            parts.append(f"【角色】{ch.name}：{content}")
                except Exception:
                    logger.warning("角色设定读取失败，跳过该源", exc_info=True)
            if self._world_repo is not None:
                try:
                    worlds, _ = await self._world_repo.list(project_int, limit=50)
                    for ws in worlds:
                        if ws.content:
                            parts.append(f"【世界观】{ws.name}：{ws.content}")
                except Exception:
                    logger.warning("世界观设定读取失败，跳过该源", exc_info=True)
            if self._outline_repo is not None:
                try:
                    outlines, _ = await self._outline_repo.list(project_int, limit=50)
                    for o in outlines:
                        if o.description:
                            parts.append(f"【大纲】{o.name}：{o.description}")
                except Exception:
                    logger.warning("大纲设定读取失败，跳过该源", exc_info=True)
            if parts:
                variables["setting"] = "\n\n".join(parts)
        except Exception:
            logger.warning("设定注入失败，回退请求变量", exc_info=True)
        return variables

    async def _assemble_continue_context(
        self,
        project_id: str,
        chapter_id: str | None,
        variables: dict[str, str],
    ) -> dict[str, str]:
        """write_continue 前文摘要注入（#318）：前序 ≤10 章 ensure_summary → variables["context"]；
        任一步失败 → WARNING + 回退（不阻断管线）。
        """
        if self._summary_service is None or not chapter_id:
            return variables
        try:
            project = await self._project_repo.get(uuid.UUID(project_id).int)
            if project is None:
                return variables
            current = await self._chapter_repo.get_chapter(uuid.UUID(chapter_id).int)
            if current is None:
                return variables
            chapters, _ = await self._chapter_repo.list_chapters(
                uuid.UUID(project_id).int, limit=1000
            )
            prev = sorted(
                (c for c in chapters if c.order_index < current.order_index),
                key=lambda c: c.order_index,
            )[-10:]
            parts: list[str] = []
            for ch in prev:
                try:
                    summary = await self._summary_service.ensure_summary(
                        ch.id, project.config.model
                    )
                except Exception:
                    logger.warning("章节 %s 摘要生成失败，跳过（F6 §4.6）", ch.id)
                    continue
                parts.append(f"{ch.title}：{summary}")
            if parts:
                variables["context"] = "\n\n".join(parts)
        except Exception:
            logger.warning("前文摘要组装失败，回退请求变量", exc_info=True)
        return variables
