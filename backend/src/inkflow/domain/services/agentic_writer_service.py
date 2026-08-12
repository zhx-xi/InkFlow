"""F27 Agentic 编排服务 — deepagents ReAct 循环驱动 + 护栏 + 兜底 + 审计 + 决策轨迹.

AgenticWriterService 是 agentic 写入闭环的领域编排层（spec §5.1/§5.3/§5.7，ADR-D 产物保留）:
- 每次 run 调一次 agent_factory 获取可 invoke 的 agent（deepagents CompiledStateGraph，
  由 infrastructure 装配层注入——ADR-015: domain 层不感知 deepagents/langchain）
- invoke 返回完整消息历史（末条为最终 AIMessage）；服务层从历史提取决策轨迹
  （steps 全量快照）并实施护栏: repeat_tool / max_steps / empty_content（重试）/
  token_budget
- 自然终止且 LLM 未显式调用 save_draft → 服务层兜底落草稿（auto_saved 审计）
- 全部终态经 run_repo.save 一次写回（崩溃可见性: create 先行落 running 记录）

依赖注入（鸭子类型）:
- agent_factory: Callable[[AgenticWriteRequest], object]——每次 run 调用一次，
  传入当前请求（#275: 装配层按请求注入 project_id/chapter_id 上下文——系统提示
  渲染与 save_draft 工具期望上下文同源）
- draft_service: DraftService（create 兜底落草稿）
- audit_service: AuditLogService（record）
- run_repo: AgentRunRepository（create/save）
- chapter_service: 确认流预留（本批 run() 不使用）
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import pairwise

from inkflow.domain.models.agent_run import (
    AgenticWriteRequest,
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentToolCall,
)
from inkflow.domain.services._word_count import count_words

# 空 content 重试提示（必须含「请输出正文」——测试契约码点断言）
_EMPTY_RETRY_PROMPT = "工具结果已回填。请基于以上工具结果直接输出章节正文（Markdown），请输出正文。"


def _utcnow() -> datetime:
    """当前 UTC 时间."""
    return datetime.now(UTC)


def _msg_type(message: object) -> str:
    """提取消息类型（dict 或 langchain BaseMessage 双形态）."""
    if isinstance(message, dict):
        return str(message.get("type", ""))
    return str(getattr(message, "type", ""))


def _msg_name(message: object) -> str:
    """提取 tool 消息名称（dict 或 ToolMessage.name 双形态）."""
    if isinstance(message, dict):
        return str(message.get("name", ""))
    return str(getattr(message, "name", ""))


def _msg_content(message: object) -> str:
    """提取消息文本内容."""
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(getattr(message, "content", ""))


def _tool_calls_of(message: object) -> list[dict]:
    """提取 AI 消息的 tool_calls（dict 或 AIMessage.tool_calls 双形态）."""
    if isinstance(message, dict):
        calls = message.get("tool_calls") or []
    else:
        calls = getattr(message, "tool_calls", None) or []
    return [c for c in calls if isinstance(c, dict)]


def _response_metadata(message: object) -> dict:
    """提取消息 response_metadata（usage/model 来源）."""
    if isinstance(message, dict):
        meta = message.get("response_metadata") or {}
    else:
        meta = getattr(message, "response_metadata", None) or {}
    return meta if isinstance(meta, dict) else {}


def _tokens_of(message: object) -> int:
    """提取单条消息 token 消耗（response_metadata.usage.total_tokens；无 → 0）."""
    usage = _response_metadata(message).get("usage") or {}
    if not isinstance(usage, dict):
        return 0
    try:
        return int(usage.get("total_tokens", 0) or 0)
    except (TypeError, ValueError):
        return 0


class AgenticWriteNotFoundError(Exception):
    """项目/章节不存在（API 映射 404；service run 校验前置语义）."""

    def __init__(self, message: str = "章节不存在") -> None:
        super().__init__(message)


class AgenticWriterService:
    """agentic 编排服务——deepagents ReAct 循环驱动 + 护栏 + 兜底 + 审计 + 决策轨迹。"""

    def __init__(
        self,
        *,
        agent_factory: Callable[[AgenticWriteRequest], object],  # 每次 run 调用一次，传入当前请求
        draft_service,  # DraftService（鸭子类型）
        audit_service,  # AuditLogService（鸭子类型）
        run_repo,  # AgentRunRepository（鸭子类型，有 create/save）
        chapter_service: object | None = None,  # 确认流用（可空）
        max_steps_default: int = 12,
        token_budget_default: int = 32000,
        max_consecutive_tool: int = 3,
        empty_content_retries: int = 1,
    ) -> None:
        self._agent_factory = agent_factory
        self._draft_service = draft_service
        self._audit_service = audit_service
        self._run_repo = run_repo
        self._chapter_service = chapter_service
        self._max_steps_default = max_steps_default
        self._token_budget_default = token_budget_default
        self._max_consecutive_tool = max_consecutive_tool
        self._empty_content_retries = empty_content_retries

    async def run(self, request: AgenticWriteRequest) -> AgentRun:
        """执行一次 agentic 写作 run（guardrail 不抛异常，ADR-D 产物保留）.

        Args:
            request: agentic 写作请求（outline 必填，预算参数可空=读默认）.

        Returns:
            终态 AgentRun（completed/failed/terminated_by_guardrail）.
        """
        max_steps = request.max_steps or self._max_steps_default
        token_budget = request.token_budget or self._token_budget_default
        now = _utcnow()
        # 崩溃可见性（spec §7）：先落 running 记录，终态一次写回
        created = await self._run_repo.create(
            project_id=request.project_id,
            chapter_id=request.chapter_id,
            mode="agentic",
        )
        # 测试 run_repo 为 AsyncMock（id 为 Mock）——str() 兜底保证 str 字段合法
        run_id = str(created.id)
        run = AgentRun(
            id=run_id,
            project_id=request.project_id,
            chapter_id=request.chapter_id,
            mode="agentic",
            status=AgentRunStatus.RUNNING,
            steps=[],
            model="",
            created_at=now,
            updated_at=now,
        )

        agent = self._agent_factory(request)
        history: list[object] = []
        try:
            history = await self._invoke_agent(agent, [self._build_initial_message(request)])
            # 空 content 重试循环（保留完整历史，追加用户消息再次 invoke）
            retries = 0
            while self._is_empty_final(history) and retries < self._empty_content_retries:
                retries += 1
                retry_message = {"type": "user", "content": _EMPTY_RETRY_PROMPT}
                history = await self._invoke_agent(agent, [*history, retry_message])
        except Exception as exc:
            # 防御：invoke 抛错 → FAILED 落库返回（不吞进程级错误导致挂起）
            run.status = AgentRunStatus.FAILED
            run.updated_at = _utcnow()
            await self._audit(
                project_id=request.project_id,
                chapter_id=request.chapter_id,
                severity_summary="run_failed",
                summary=str(exc),
            )
            await self._run_repo.save(run)
            return run

        # 决策轨迹全量映射（消息历史 → steps）+ 汇总字段
        run.steps = self._build_steps(history)
        run.token_usage_total = self._token_usage_total(history)
        run.model = self._extract_model(history)

        guardrail = self._evaluate_guardrail(
            history, max_steps=max_steps, token_budget=token_budget
        )
        if guardrail is not None:
            run.status = AgentRunStatus.TERMINATED_BY_GUARDRAIL
            run.terminated_by = guardrail
            run.final_content = ""  # 产物保留：已保存草稿不动，未保存则不兜底
            await self._audit(
                project_id=request.project_id,
                chapter_id=request.chapter_id,
                severity_summary="guardrail_terminated",
                summary=f"terminated_by={guardrail}",
            )
        else:
            run.status = AgentRunStatus.COMPLETED
            run.terminated_by = "llm"
            run.final_content = self._final_content(history)
            # 草稿兜底（ADR-D）：历史未显式调用 save_draft → 服务层保存
            if not self._history_has_tool_call(history, "save_draft"):
                draft = await self._draft_service.create(
                    project_id=request.project_id,
                    chapter_id=request.chapter_id,
                    content=run.final_content,
                    summary="agentic 自动保存",
                    agent_run_id=run.id,
                )
                run.draft_id = draft.id
                await self._audit(
                    project_id=request.project_id,
                    chapter_id=request.chapter_id,
                    severity_summary="auto_saved",
                    summary=f"兜底保存草稿 {count_words(run.final_content)} 字",
                )
            await self._audit(
                project_id=request.project_id,
                chapter_id=request.chapter_id,
                severity_summary="run_completed",
                summary=f"run {run.id} 完成",
            )

        run.updated_at = _utcnow()
        await self._run_repo.save(run)
        return run

    async def _invoke_agent(self, agent: object, messages: list[object]) -> list[object]:
        """调 agent（deepagents invoke 语义：返回含完整消息历史的 dict）."""
        result = await agent.invoke(messages)  # type: ignore[attr-defined]  # 鸭子类型：agent 按契约提供 async invoke
        if isinstance(result, dict):
            history = result.get("messages") or []
            return list(history)
        return []

    def _build_initial_message(self, request: AgenticWriteRequest) -> dict[str, str]:
        """装配初始用户消息（outline/context/min_words/style_hint 拼入，必须含 outline 文本）."""
        parts = ["请为当前章节撰写正文。", "", "## 本章大纲", request.outline]
        if request.context:
            parts.extend(["", "## 前文上下文", request.context])
        parts.extend(["", "## 写作要求", f"- 目标字数：{request.min_words} 字"])
        if request.style_hint:
            parts.append(f"- 风格提示：{request.style_hint}")
        return {"type": "user", "content": "\n".join(parts)}

    def _is_empty_final(self, history: list[object]) -> bool:
        """空 content 判定：最终 AI 消息 content 为空且无 tool_calls."""
        ai_messages = [m for m in history if _msg_type(m) == "ai"]
        if not ai_messages:
            return True  # 历史无 AI 消息 → 无正文产物
        last = ai_messages[-1]
        return _msg_content(last) == "" and not _tool_calls_of(last)

    def _final_content(self, history: list[object]) -> str:
        """最终 AI 消息正文."""
        for message in reversed(history):
            if _msg_type(message) == "ai":
                return _msg_content(message)
        return ""

    def _history_has_tool_call(self, history: list[object], tool_name: str) -> bool:
        """消息历史中是否出现指定工具调用（save_draft 兜底判定）."""
        for message in history:
            if _msg_type(message) != "ai":
                continue
            if any(tc.get("name") == tool_name for tc in _tool_calls_of(message)):
                return True
        return False

    def _build_steps(self, history: list[object]) -> list[AgentStep]:
        """消息历史 → 决策轨迹全量快照（每条消息一个 AgentStep）.

        AI 消息: message_content + tool_calls（result 向后回填同名 tool 消息）+ tokens；
        tool/其他消息: 空 content、无 tool_calls、tokens=0。
        """
        steps: list[AgentStep] = []
        for index, message in enumerate(history):
            if _msg_type(message) != "ai":
                steps.append(
                    AgentStep(
                        index=index,
                        message_content=_msg_content(message),
                        tool_calls=[],
                        tokens=0,
                    )
                )
                continue
            calls: list[AgentToolCall] = []
            for tool_call in _tool_calls_of(message):
                name = str(tool_call.get("name", ""))
                result = self._tool_result_of(history, index, name)
                calls.append(
                    AgentToolCall(
                        step_index=index,
                        tool_name=name,
                        arguments=dict(tool_call.get("args") or {}),
                        result=result,
                        is_error='"ok": false' in result,
                    )
                )
            steps.append(
                AgentStep(
                    index=index,
                    message_content=_msg_content(message),
                    tool_calls=calls,
                    tokens=_tokens_of(message),
                )
            )
        return steps

    def _tool_result_of(self, history: list[object], ai_index: int, tool_name: str) -> str:
        """AI 消息 tool_call 结果回填：向后找下一个 type==tool 且 name 匹配的消息的 content."""
        for message in history[ai_index + 1 :]:
            if _msg_type(message) == "tool" and _msg_name(message) == tool_name:
                return _msg_content(message)
        return ""

    def _token_usage_total(self, history: list[object]) -> int:
        """累计 token 消耗（各 AI 消息 response_metadata.usage.total_tokens 求和）."""
        return sum(_tokens_of(m) for m in history if _msg_type(m) == "ai")

    def _extract_model(self, history: list[object]) -> str:
        """从消息 response_metadata 提取模型标识（无 → 留空，测试不锁）."""
        for message in history:
            if _msg_type(message) != "ai":
                continue
            meta = _response_metadata(message)
            model = meta.get("model", "")
            if not model and isinstance(message, dict):
                model = message.get("model", "")
            if not model and not isinstance(message, dict):
                model = getattr(message, "model", "") or ""
            if model:
                return str(model)
        return ""

    def _evaluate_guardrail(
        self,
        history: list[object],
        *,
        max_steps: int,
        token_budget: int,
    ) -> str | None:
        """护栏判定（顺序: repeat_tool → max_steps → empty_content → token_budget）.

        Returns:
            触发原因字符串；None = 自然终止（completed / "llm"）。
        """
        ai_messages = [m for m in history if _msg_type(m) == "ai"]
        last_ai = ai_messages[-1] if ai_messages else None
        last_content = _msg_content(last_ai) if last_ai is not None else ""
        last_tool_calls = _tool_calls_of(last_ai) if last_ai is not None else []

        # a. 同工具连续调用 >= max_consecutive_tool（相邻 AI 消息的 tool_calls 连续同名）
        tool_sequence = [str(tc.get("name", "")) for m in ai_messages for tc in _tool_calls_of(m)]
        consecutive = 1
        for previous, current in pairwise(tool_sequence):
            consecutive = consecutive + 1 if current == previous else 1
            if consecutive >= self._max_consecutive_tool:
                return "repeat_tool"

        # b. max_steps：工具调用步数 >= max_steps 且最终无正文
        tool_steps = sum(1 for m in ai_messages if _tool_calls_of(m))
        if tool_steps >= max_steps and last_content == "":
            return "max_steps"

        # c. empty_content：重试后最终 AI 消息仍空且无 tool_calls
        if last_content == "" and not last_tool_calls:
            return "empty_content"

        # d. token_budget：累计 tokens 超预算（fake 无 usage 恒 0 不触发，防御实现）
        if self._token_usage_total(history) >= token_budget:
            return "token_budget"

        # e. 自然终止：最终 AI 消息 content 非空且无 tool_calls
        if last_content != "" and not last_tool_calls:
            return None

        # 防御：最终消息仍含 tool_calls 且无正文（工具循环未产出终态）→ max_steps 护栏
        return "max_steps"

    async def _audit(
        self,
        *,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None,
        severity_summary: str,
        summary: str = "",
    ) -> None:
        """落审计日志（F34 形态，actor/degraded 固定为 agent 语义）."""
        await self._audit_service.record(
            project_id=project_id,
            chapter_id=chapter_id,
            severity_summary=severity_summary,
            summary=summary,
            degraded=True,
            actor="agent:writer",
        )
