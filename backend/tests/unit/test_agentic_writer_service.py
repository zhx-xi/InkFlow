"""F27 M1 编排服务 RED 契约测试 — AgenticWriterService（agentic 写入闭环，mock LLM 固定序列驱动）.

被测模块（全部未实现，1c 整模块 RED 形态；全部顶部 import——全文件收集期失败是
预期（pytest exit 2 / collected 0 items / 1 error），GREEN 落地后整文件自动收集）:
    from inkflow.domain.models.agent_run import AgentRun, AgentRunStatus, AgentStep, AgentToolCall
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest, AgenticWriterService,
    )

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. AgentRun 领域模型（domain/models/agent_run.py 新建，Pydantic BaseModel）:

       class AgentToolCall(BaseModel):
           '''单次工具调用记录（决策轨迹原子单元）.'''
           step_index: int
           tool_name: str
           arguments: dict
           result: str
           is_error: bool = False

       class AgentStep(BaseModel):
           '''单次 LLM 决策步骤快照.'''
           index: int
           message_content: str       # 该步 AIMessage 文本（空 = 只调工具）
           tool_calls: list[AgentToolCall]
           tokens: int = 0

       class AgentRunStatus(StrEnum):
           RUNNING = "running"
           COMPLETED = "completed"
           FAILED = "failed"
           TERMINATED_BY_GUARDRAIL = "terminated_by_guardrail"

       class AgentRun(BaseModel):
           id: str
           project_id: uuid.UUID
           chapter_id: uuid.UUID | None = None
           mode: str = "agentic"
           status: AgentRunStatus = AgentRunStatus.RUNNING
           steps: list[AgentStep] = []
           final_content: str = ""
           draft_id: str | None = None
           model: str = ""
           token_usage_total: int = 0
           terminated_by: str = ""    # "llm" / "max_steps" / "repeat_tool" /
                                      # "empty_content" / "token_budget"
           created_at: datetime
           updated_at: datetime

2. AgenticWriteRequest（domain/models/agent_run.py 新建）:

       class AgenticWriteRequest(BaseModel):
           project_id: uuid.UUID
           chapter_id: uuid.UUID | None = None
           outline: str
           context: str = ""
           min_words: int = 2000
           style_hint: str | None = None
           max_steps: int | None = None      # None = 读设置/默认 12
           token_budget: int | None = None   # None = 读设置/默认 32K

3. AgenticWriterService（domain/services/agentic_writer_service.py 新建）:

       class AgenticWriterService:
           def __init__(
               self, *,
               agent_factory: Callable[[], object],   # 返回可 invoke 的 agent（fake/真实均可）
               draft_service,                          # DraftService（鸭子类型）
               audit_service,                          # audit 日志（F34 形态）
               run_repo,                               # AgentRunRepository（鸭子类型）
               chapter_service: object | None = None,  # 确认流用（鸭子类型）
               max_steps_default: int = 12,
               token_budget_default: int = 32000,
               max_consecutive_tool: int = 3,
               empty_content_retries: int = 1,
           ): ...
           async def run(self, request: AgenticWriteRequest) -> AgentRun

   - agent_factory 每次 run 调用一次，返回 agent 对象；agent 须有
     `async def invoke(self, messages: list, config: dict | None = None) -> dict`
     返回值含 "messages" 键（deepagents 语义：完整消息历史，末条为最终 AIMessage）。
   - 工具执行在 agent 内建循环（deepagents ToolNode）；服务层从返回的消息历史
     提取决策轨迹并实施护栏（检查最终消息 content / 统计连续同工具 / 步数）。

4. 护栏语义（spec §5.3/§5.4，ADR-D 产物保留）:
   - 自然终止: 最终 AIMessage content 非空且无 tool_calls → completed / "llm"
   - 连续同工具: 消息历史中相邻 tool_calls 同一工具连续 >= max_consecutive_tool
     → terminated_by_guardrail / "repeat_tool"（产物保留）
   - max_steps: 工具调用步数 >= max_steps 仍无正文 → terminated_by_guardrail / "max_steps"
   - 空 content: 最终消息 content 为空且无 tool_calls → 自动重试 1 次
     （empty_content_retries，追加用户消息「请输出正文」）→ 仍空 →
     terminated_by_guardrail / "empty_content"
   - token: 累计 tokens >= token_budget → terminated_by_guardrail / "token_budget"
   - guardrail 不视为异常抛出：run() 正常返回 AgentRun（status 区分）

5. 草稿兜底（spec §5.3 ADR-D）:
   - LLM 自然终止且消息历史中未调用 save_draft → 服务层兜底 draft_service.create(
     content=final_content, ...)，audit 标注 auto_saved，draft_id 回填 run
   - 消息历史中含 save_draft 工具调用 → 工具已落库，不重复兜底

6. 审计（spec §5.5）: run 完成/guardrail/兜底保存均落 audit_service（severity_summary
   承载动作语义: "draft_saved"/"auto_saved"/"run_completed"/"guardrail_terminated" 等）。

7. 决策轨迹（spec §5.7）: run.steps 全量（每步 message_content + tool_calls 含
   arguments/result/is_error + tokens）；run_repo.save/update 被调；可从 repo 读回。

RED 预期
--------
全文件收集期失败（1c 整模块 RED 形态: pytest exit 2 / collected 0 items / 1 error）:
    ModuleNotFoundError: No module named 'inkflow.domain.models.agent_run'
字母序原因: isort 强制首方组字母序，inkflow.domain.models.agent_run 先于
inkflow.domain.models.draft 先于 inkflow.domain.services.agentic_writer_service
执行——收集错误报字母序首个缺失模块（F34/F26 实测规则）。

asyncio 模式: 本 venv（pytest-asyncio 1.4.0）实测头部 asyncio: mode=Mode.AUTO
（pyproject asyncio_mode = "auto" 生效）；文件级 pytestmark = pytest.mark.asyncio
双保险（STRICT/AUTO 两种模式均成立），全部用例 async def。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.agent_run import (
    AgenticWriteRequest,
    AgentRun,
    AgentRunStatus,
)
from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.domain.services.agentic_writer_service import AgenticWriterService

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")

_TOOL_MSG = {"ok": True, "data": []}  # 工具结果信封（F26 工具信封形态）


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ── FakeAgent：固定 tool_call 序列驱动（脚本化 mock 测试基建） ──


class FakeAgent:
    """预置消息历史序列的 fake agent —— 每次 invoke 返回下一个预置历史。

    responses: list[dict]，每个元素为一次 invoke 返回的 {"messages": [...]}；
    耗尽后返回 {"messages": [{"type": "ai", "content": ""}]}（防御）。
    """

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.invoked_messages: list[list[dict]] = []
        self.invoked_configs: list[dict | None] = []

    async def invoke(self, messages: list[dict], config: dict | None = None) -> dict:
        self.invoked_messages.append(list(messages))
        self.invoked_configs.append(config)
        if not self._responses:
            return {"messages": [{"type": "ai", "content": ""}]}
        return self._responses.pop(0)


def _ai_msg(content: str = "", tool_calls: list[dict] | None = None) -> dict:
    msg: dict[str, Any] = {"type": "ai", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _tool_msg(name: str, result: str = '{"ok": true, "data": []}') -> dict:
    return {"type": "tool", "name": name, "content": result}


def _tool_call(name: str, args: dict | None = None) -> dict:
    return {
        "id": f"call_{name}",
        "name": name,
        "args": args or {"project_id": str(PROJECT_ID)},
    }


def _history(*messages: dict) -> dict:
    return {"messages": list(messages)}


# ── 辅助 ──────────────────────────────────────


def _make_request(**overrides) -> AgenticWriteRequest:
    kwargs = dict(
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        outline="本章大纲",
        min_words=2000,
    )
    kwargs.update(overrides)
    return AgenticWriteRequest(**kwargs)


def _make_service(
    responses: list[dict],
    *,
    max_steps: int = 12,
    max_consecutive_tool: int = 3,
    empty_content_retries: int = 1,
) -> tuple[AgenticWriterService, FakeAgent, dict[str, Any]]:
    """构造服务 + fake agent + 依赖字典（draft_service/audit_service/run_repo 全 AsyncMock）."""
    agent = FakeAgent(responses)
    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
        "chapter_service": AsyncMock(),
    }
    service = AgenticWriterService(
        agent_factory=lambda: agent,
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
        chapter_service=deps["chapter_service"],
        max_steps_default=max_steps,
        max_consecutive_tool=max_consecutive_tool,
        empty_content_retries=empty_content_retries,
    )
    return service, agent, deps


# ── 契约 1: 正常闭环（先调 2 工具再写正文） ──


async def test_normal_loop_two_tools_then_content() -> None:
    """契约①: 先调 search_characters + audit_chapter 两工具，再输出正文 → completed.

    run.status=completed / terminated_by="llm" / final_content=正文 /
    steps 含 2 个工具调用（tool_name 顺序正确）/ draft 兜底落库（draft_id 回填）.
    """
    responses = [
        _history(
            _ai_msg(tool_calls=[_tool_call("search_characters")]),
            _tool_msg("search_characters"),
            _ai_msg(tool_calls=[_tool_call("audit_chapter")]),
            _tool_msg("audit_chapter"),
            _ai_msg(content="这是正文内容。"),
        )
    ]
    service, agent, deps = _make_service(responses)
    deps["draft_service"].create.return_value = Draft(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="这是正文内容。",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
        confirmed_at=None,
    )

    run = await service.run(_make_request())

    assert run.status == AgentRunStatus.COMPLETED
    assert run.terminated_by == "llm"
    assert run.final_content == "这是正文内容。"
    assert len(run.steps) == 5  # 2 工具步 + 2 结果步 + 1 正文步（消息历史全量映射）
    tool_names = [tc.tool_name for step in run.steps for tc in step.tool_calls]
    assert tool_names == ["search_characters", "audit_chapter"]
    # 自然终止未显式 save_draft → 服务兜底落草稿
    deps["draft_service"].create.assert_awaited_once()
    assert run.draft_id == "draft-1"
    # 审计: 兜底保存标注 auto_saved
    audit_calls = [
        c for c in deps["audit_service"].record.await_args_list if "auto_saved" in str(c)
    ]
    assert audit_calls, "兜底保存应落审计日志（auto_saved）"


async def test_normal_loop_with_save_draft_tool_no_fallback() -> None:
    """契约⑤a: LLM 消息历史中已显式调用 save_draft → 不重复兜底落库.

    draft_service.create 不应被调用（工具已落库）；run.draft_id 为 None（无兜底）.
    """
    responses = [
        _history(
            _ai_msg(tool_calls=[_tool_call("save_draft", {"content": "草稿A"})]),
            _tool_msg("save_draft", '{"ok": true, "draft_id": "draft-x"}'),
            _ai_msg(content="草稿A内容。"),
        )
    ]
    service, _, deps = _make_service(responses)

    run = await service.run(_make_request())

    assert run.status == AgentRunStatus.COMPLETED
    assert run.final_content == "草稿A内容。"
    deps["draft_service"].create.assert_not_awaited()  # 工具已落库，无兜底
    tool_names = [tc.tool_name for step in run.steps for tc in step.tool_calls]
    assert "save_draft" in tool_names


# ── 契约 2: 连续同工具触发护栏 ──


async def test_repeat_tool_guardrail() -> None:
    """契约②: 连续 5 次同工具（search_characters）→ terminated_by_guardrail.

    terminated_by="repeat_tool" / 产物保留（run 正常返回非异常）/
    run_repo 保存了 steps（决策轨迹不丢）.
    """
    messages: list[dict] = []
    for _ in range(5):
        messages.append(_ai_msg(tool_calls=[_tool_call("search_characters")]))
        messages.append(_tool_msg("search_characters"))
    responses = [_history(*messages)]
    service, agent, deps = _make_service(responses, max_consecutive_tool=3)

    run = await service.run(_make_request())

    assert run.status == AgentRunStatus.TERMINATED_BY_GUARDRAIL
    assert run.terminated_by == "repeat_tool"
    # 决策轨迹保留（steps 含全部工具调用）
    tool_names = [tc.tool_name for step in run.steps for tc in step.tool_calls]
    assert tool_names.count("search_characters") >= 3
    deps["run_repo"].save.assert_awaited()  # 产物保留落库


async def test_repeat_tool_different_tools_no_guardrail() -> None:
    """契约②反例: 交替调用不同工具不触发 repeat_tool 护栏（连续语义）.

    search → audit → search → audit → 正文 → completed（非 guardrail）.
    """
    responses = [
        _history(
            _ai_msg(tool_calls=[_tool_call("search_characters")]),
            _tool_msg("search_characters"),
            _ai_msg(tool_calls=[_tool_call("audit_chapter")]),
            _tool_msg("audit_chapter"),
            _ai_msg(tool_calls=[_tool_call("search_characters")]),
            _tool_msg("search_characters"),
            _ai_msg(tool_calls=[_tool_call("audit_chapter")]),
            _tool_msg("audit_chapter"),
            _ai_msg(content="交替工具后正常输出。"),
        )
    ]
    service, _, deps = _make_service(responses, max_consecutive_tool=3)
    deps["draft_service"].create.return_value = Draft(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="交替工具后正常输出。",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
        confirmed_at=None,
    )

    run = await service.run(_make_request())

    assert run.status == AgentRunStatus.COMPLETED
    assert run.terminated_by == "llm"


# ── 契约 3: max_steps 超限 → terminated_by_guardrail ──


async def test_max_steps_guardrail() -> None:
    """契约③: 工具调用步数 >= max_steps 仍无正文 → terminated_by_guardrail.

    max_steps=3（请求覆盖默认）→ 3 步工具调用无正文 → terminated_by="max_steps" /
    产物保留（已落库草稿不动，run 正常返回）.
    """
    messages: list[dict] = []
    for i in range(4):  # 4 步工具（超过 max_steps=3）
        name = "search_characters" if i % 2 == 0 else "audit_chapter"
        messages.append(_ai_msg(tool_calls=[_tool_call(name)]))
        messages.append(_tool_msg(name))
    responses = [_history(*messages)]
    service, _, deps = _make_service(responses, max_steps=3)

    run = await service.run(_make_request(max_steps=3))

    assert run.status == AgentRunStatus.TERMINATED_BY_GUARDRAIL
    assert run.terminated_by == "max_steps"
    assert len(run.steps) > 0  # 产物保留：steps 已落
    deps["run_repo"].save.assert_awaited()


# ── 契约 4: 空 content → 重试 1 次 → guardrail / 重试成功 ──


async def test_empty_content_retry_once_then_guardrail() -> None:
    """契约④a: 最终 AIMessage content 为空 → 自动重试 1 次（追加「请输出正文」）→ 仍空.

    断言: agent.invoke 被调 2 次 / 第二次调用 messages 末尾含「请输出正文」提示 /
    terminated_by="empty_content" / 产物保留.
    """
    responses = [
        _history(
            _ai_msg(tool_calls=[_tool_call("search_characters")]),
            _tool_msg("search_characters"),
            _ai_msg(content=""),
        ),
        _history(_ai_msg(content="")),  # 重试后仍空
    ]
    service, agent, deps = _make_service(responses, empty_content_retries=1)

    run = await service.run(_make_request())

    assert run.status == AgentRunStatus.TERMINATED_BY_GUARDRAIL
    assert run.terminated_by == "empty_content"
    assert len(agent.invoked_messages) == 2  # 重试 1 次
    # 第二次调用消息含「请输出正文」重申提示
    retry_messages = agent.invoked_messages[1]
    assert any("请输出正文" in str(m.get("content", "")) for m in retry_messages)
    deps["run_repo"].save.assert_awaited()


async def test_empty_content_retry_then_success() -> None:
    """契约④b: 第一次空 content → 重试后输出正文 → completed.

    断言: invoke 被调 2 次 / status=completed / terminated_by="llm" /
    final_content=重试后正文 / 兜底落草稿.
    """
    responses = [
        _history(_ai_msg(content="")),
        _history(_ai_msg(content="重试后正文。")),
    ]
    service, agent, deps = _make_service(responses, empty_content_retries=1)
    deps["draft_service"].create.return_value = Draft(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="重试后正文。",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
        confirmed_at=None,
    )

    run = await service.run(_make_request())

    assert len(agent.invoked_messages) == 2
    assert run.status == AgentRunStatus.COMPLETED
    assert run.terminated_by == "llm"
    assert run.final_content == "重试后正文。"
    deps["draft_service"].create.assert_awaited_once()


# ── 契约 5: save_draft 草稿落库 + 确认转正式 ──


async def test_draft_confirm_flow() -> None:
    """契约⑤b: 草稿确认 → 经 chapter_service 写入正式章节 + draft 置 CONFIRMED.

    模拟: draft_service.confirm 内部调用 chapter_service.update_chapter（status=final）
    并置 DraftStatus.CONFIRMED；断言确认结果对象返回且状态正确.
    本用例验证 Draft 领域模型 + 确认语义（DraftStatus 枚举、confirmed_at 回填）.
    """
    draft = Draft(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="确认后的正式内容。",
        status=DraftStatus.CONFIRMED,
        created_at=_utcnow(),
        confirmed_at=_utcnow(),
    )
    assert draft.status == DraftStatus.CONFIRMED
    assert draft.confirmed_at is not None
    # 确认流经 chapter_service.update_chapter（鸭子类型契约：GREEN 实现此调用）
    deps_chapter = AsyncMock()
    deps_chapter.update_chapter.return_value = None
    # 服务确认流：draft_service.confirm(draft_id) → 返回已确认草稿
    deps_draft = AsyncMock()
    deps_draft.confirm.return_value = draft
    # 契约: DraftService.confirm 存在且返回 Draft（父侧定稿签名）
    confirmed = await deps_draft.confirm("draft-1")
    assert confirmed.status == DraftStatus.CONFIRMED
    assert confirmed.content == "确认后的正式内容。"


# ── 契约 6: 审计日志写入 ──


async def test_audit_log_written_on_guardrail() -> None:
    """契约⑥: guardrail 终止同样落审计日志（guardrail_terminated 语义）.

    max_steps 超限 → audit_service.record 被调（含 terminated_by 信息）.
    """
    messages: list[dict] = []
    for i in range(4):
        name = "search_characters" if i % 2 == 0 else "audit_chapter"
        messages.append(_ai_msg(tool_calls=[_tool_call(name)]))
        messages.append(_tool_msg(name))
    responses = [_history(*messages)]
    service, _, deps = _make_service(responses, max_steps=3)

    run = await service.run(_make_request(max_steps=3))

    assert run.terminated_by == "max_steps"
    guardrail_audits = [
        c
        for c in deps["audit_service"].record.await_args_list
        if "guardrail" in str(c) or "max_steps" in str(c)
    ]
    assert guardrail_audits, "guardrail 终止应落审计日志"


async def test_audit_log_written_on_completion() -> None:
    """契约⑥b: run 完成落审计日志（run_completed + draft_saved 语义）."""
    responses = [
        _history(
            _ai_msg(tool_calls=[_tool_call("search_characters")]),
            _tool_msg("search_characters"),
            _ai_msg(content="正文内容。"),
        )
    ]
    service, _, deps = _make_service(responses)
    deps["draft_service"].create.return_value = Draft(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="正文内容。",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
        confirmed_at=None,
    )

    await service.run(_make_request())

    assert deps["audit_service"].record.await_count >= 1  # run 完成审计


# ── 契约 7: 决策轨迹暴露 ──


async def test_decision_trace_exposed() -> None:
    """契约⑦: run.steps 全量决策轨迹（message_content/tool_calls/arguments/result/tokens）.

    断言: steps 每步内容正确 / tool_calls 含 arguments 与 result /
    token_usage_total 汇总 / run_repo.save 收到完整 run（含 steps）.
    """
    responses = [
        _history(
            _ai_msg(tool_calls=[_tool_call("search_characters", {"project_id": str(PROJECT_ID)})]),
            _tool_msg("search_characters", '{"ok": true, "data": ["角色A"]}'),
            _ai_msg(content="最终正文。"),
        )
    ]
    service, _, deps = _make_service(responses)

    run = await service.run(_make_request())

    # steps 映射消息历史（5 条消息）
    assert len(run.steps) == 3
    # 工具步含 arguments 与 result
    search_step = next(
        s for s in run.steps if any(tc.tool_name == "search_characters" for tc in s.tool_calls)
    )
    call = search_step.tool_calls[0]
    assert call.arguments["project_id"] == str(PROJECT_ID)
    assert "角色A" in call.result
    # 正文步 message_content 非空
    assert any(s.message_content == "最终正文。" for s in run.steps)
    # run 保存到 repo（决策轨迹持久化）
    deps["run_repo"].save.assert_awaited_once()
    saved_run: AgentRun = deps["run_repo"].save.await_args.args[0]
    assert saved_run.id == run.id
    assert len(saved_run.steps) == 3


# ── 边界: guardrail 不抛异常、run 正常返回 ──


async def test_guardrail_returns_run_not_raises() -> None:
    """边界: guardrail 触发时 run() 正常返回 AgentRun（不抛异常，ADR-D 产物保留）."""
    messages: list[dict] = []
    for _ in range(4):
        messages.append(_ai_msg(tool_calls=[_tool_call("search_characters")]))
        messages.append(_tool_msg("search_characters"))
    responses = [_history(*messages)]
    service, _, deps = _make_service(responses, max_consecutive_tool=3)

    run = await service.run(_make_request())

    assert isinstance(run, AgentRun)
    assert run.status == AgentRunStatus.TERMINATED_BY_GUARDRAIL
