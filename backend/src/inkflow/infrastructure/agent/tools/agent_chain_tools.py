"""#766 阶段③ agent 链工具——2 工具（agent_run / agent_call），输出统一 JSON 信封.

镜像 setting_write_tools.py 形态：
- 动态 deps 构建（不进静态 TOOL_REGISTRY）
- agent_run: 包装 agent_service.execute(PipelineExecuteRequest)——成功
  {"ok": True, "execution_id": "<id>", "status": "pending"}；service 抛异常 →
  {"ok": False, "error": "<异常消息>"}（工具内部捕获一切 Exception 不抛出）
- project_id 由 deps.expected_project_id 装配期绑定（schema 不含——LLM 不自报，
  防编造孤儿执行）
- agent_call: agent_entity_service.get(agent_id) 读配置 → deps.run_agent(agent,
  input) 单 agent 执行（Q1=A 拍板）——成功 {"ok": True, "result": "<输出文本>"}
- D5: agent 链配置修改/删除工具（roles/order/relations CRUD）不给 AI——只注册
  agent_run + agent_call，不注册任何 CRUD 工具。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest
from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.tools.reader_tools import Tool


def _coerce_uuid(value: object) -> uuid.UUID:
    """规范化 uuid.UUID——deepagents 透传 LLM JSON 原值，参数恒为 str（#275）。"""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


# ─── 参数模型（用于生成 ToolSpec.input_schema；project_id 由装配期绑定，不在 schema） ───


class AgentRunParams(BaseModel):
    """agent_run 工具参数（project_id 由 deps 绑定）。"""

    pipeline: str = "builtin:write_chapter"
    chapter_id: uuid.UUID | str | None = None
    variables: dict[str, str] = {}
    mode: str = "static"


class AgentCallParams(BaseModel):
    """agent_call 工具参数。"""

    agent_id: str
    input: str


# ─── 工具 spec 静态常量（func 动态构建，镜像 setting_write_tools） ───


AGENT_RUN_SPEC = ToolSpec(
    name="agent_run",
    description="启动一次 agent 链管线执行",
    input_schema=AgentRunParams.model_json_schema(),
    group="project",
)

AGENT_CALL_SPEC = ToolSpec(
    name="agent_call",
    description="调用单个 agent 执行一次任务",
    input_schema=AgentCallParams.model_json_schema(),
    group="project",
)


@dataclass
class AgentChainToolDeps:
    """agent 链工具工厂依赖——service 实例注入（鸭子类型，镜像 SaveDraftToolDeps）。

    run_agent: 单 agent 执行钩子（Q1=A：读配置后独立执行），装配期注入。
    expected_project_id: #766 绑定项目——agent_run 恒用绑定值（LLM 不自报项目）。
    """

    agent_service: object  # 有 execute(request: PipelineExecuteRequest) -> dict
    agent_entity_service: object  # 有 get(agent_id) -> Agent（配置实体）
    run_agent: Callable[[object, str], Awaitable[str]]
    expected_project_id: uuid.UUID | None = None


def build_agent_chain_tools(deps: AgentChainToolDeps) -> list[Tool]:
    """构建 agent 链工具（顺序固定：agent_run → agent_call）。

    Args:
        deps: 工具依赖（agent 管线服务 + agent 实体服务 + 单 agent 执行钩子）。

    Returns:
        两个可执行 Tool；func 成功/失败均返回 JSON 信封且不抛异常。
    """

    async def _agent_run(
        pipeline: str = "builtin:write_chapter",
        chapter_id: uuid.UUID | str | None = None,
        variables: dict[str, str] | None = None,
        mode: str = "static",
    ) -> str:
        if deps.expected_project_id is None:
            return json.dumps({"ok": False, "error": "缺少项目上下文"}, ensure_ascii=False)
        try:
            chapter_uuid = None
            if chapter_id is not None:
                chapter_uuid = (
                    chapter_id
                    if isinstance(chapter_id, uuid.UUID)
                    else _coerce_uuid(chapter_id)
                )
            request = PipelineExecuteRequest.model_construct(
                project_id=deps.expected_project_id,
                pipeline=pipeline,
                chapter_id=chapter_uuid,
                variables=variables or {},
                mode=mode,
            )
            result = await deps.agent_service.execute(request)  # type: ignore[attr-defined]  # 鸭子类型：agent_service 按契约提供 execute
            return json.dumps(
                {
                    "ok": True,
                    "execution_id": result["execution_id"],
                    "status": result["status"],
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _agent_call(agent_id: str, input: str) -> str:
        try:
            agent = await deps.agent_entity_service.get(agent_id)  # type: ignore[attr-defined]  # 鸭子类型：agent_entity_service 按契约提供 get
            output = await deps.run_agent(agent, input)
            return json.dumps({"ok": True, "result": str(output)}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return [
        Tool(spec=AGENT_RUN_SPEC, func=_agent_run),
        Tool(spec=AGENT_CALL_SPEC, func=_agent_call),
    ]
