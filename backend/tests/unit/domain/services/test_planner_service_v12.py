"""F44 v1.2 #475 访谈 LLM 动态提问契约（TDD RED 阶段，兄弟文件）。

权威来源：specs/f44-book-orchestrator/spec.md §2.2（PlannerSession 扩展
confirmed_items/conflicts/confirming）、§5.1「LLM 动态提问引擎」（PR-1 后端契约）、
§7 场景 15/16/17、§12 D13、§13.5 M13。本文件为
`domain/services/planner_service.py`（MODIFY）的 v1.2 扩展定义契约。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【PlannerSession v1.2 扩展】（§2.2）新增字段（默认值向后兼容）：
   - confirmed_items: list[dict] = []（{"key", "value", "source"}，
     source ∈ user | llm_inferred | auto）
   - conflicts: list[dict] = []（{"round", "question_id", "answer",
     "conflict_with", "resolution"}，resolution ∈ pending | resolved）
   - confirming: bool = False（末尾总体确认阶段标志）

2. 【构造扩展】PlannerService 构造新增可选参数（关键字，默认 None 向后兼容）：
   - llm_client: 鸭子对象（LLMClientProtocol 形态：async chat(messages, **kwargs)
     -> ChatResponse，content 为结构化 JSON 字符串）——None = 未装配 → 确定性兜底
   - project_context_getter: 可调用 async fn(project_id) -> str（项目设定摘要）；
     None = 空上下文
   - prompt_manager: 鸭子对象（PromptTemplateProtocol 形态：load(name) -> template、
     render(template, variables) -> RenderedPrompt(messages=[{role, content}])）；
     None = 不渲染模板（直接构造最小 prompt）——测试断言注入

3. 【LLM 动态提问契约】（§5.1 + §13.5 M13）
   - start：llm_client 装配 → 调用 chat 生成第一轮问题——questions 含 kind 字段
     （general 通用必答 + targeted 针对性并存），≤5 问，问题即模板（template 非空）
   - 服务端必答项强约束（§6 R11 ①）：通用必答项 = 题材/篇幅/主题；LLM 输出
     questions 未覆盖未确认必答项 → 重试 1 次（chat 调用 2 次）→ 仍缺失 →
     服务端补问（必答项问题进 questions，kind=general）
   - LLM 失败降级（§7 场景 15）：chat 异常 → 重试 1 次 → 仍失败 → 回退
     ROUND1/ROUND2 确定性常量（kind 补 general），访谈不阻塞
   - llm_client=None → 确定性兜底（ROUND1/ROUND2，向后兼容既有测试/CLI）

4. 【确定项提取契约】（§5.1 D1 需求 2 + R11 ②）
   - respond：合并回答后调 LLM → 提取 confirmed_items 落 session（key 去重：
     新 key 追加、已存在 key 覆盖 value）→ 下轮只问未确定项
   - 服务端去重过滤：LLM 输出 questions 的 text 含已确认 key → 过滤（不重复提问）

5. 【冲突回问契约】（§5.1 D1 需求 3 + §7 场景 16 + R11 ③）
   - LLM 输出 conflicts（conflict_with + resolution）→ 服务端补 round/question_id/
     answer（来自本轮回答）→ 追加 session.conflicts（resolution=pending）
   - 有冲突 → questions 含 kind=conflict 问题请用户重新确认（不得静默采纳）
   - 用户新回答 resolve → 对应 pending 记录更新 resolution=resolved

6. 【末尾总体确认契约】（§5.1 D1 需求 4 + §7 场景 17）
   - 必答项齐备（confirmed_items keys ⊇ 题材/篇幅/主题）+ 无 pending 冲突 →
     confirming=true + questions 空 + 列全部确定项（confirmed_items 全量）
   - confirm=true + confirming → 完成（创建 WritingPlan status=ready + 会话
     completed），confirm 路径不调 LLM
   - confirm=true + 非 confirming → ValueError（API 层映射 422，§3.5）

7. 【LLM 失败降级 respond】（§7 场景 15）
   - respond 时 chat 异常 → 重试 1 次 → 仍失败 → 回退确定性推进
     （ROUND1 已回答 q1-q3 → ROUND2，既有 v1.1 语义），访谈不阻塞

8. 【prompt 注入】（§5.1 prompt 输入）
   - chat 调用 messages 含 one_liner + 项目设定摘要（project_context_getter
     被调用）+ 会话历史（answers/confirmed_items 已确定 keys）

9. 【RED 预期形态】PlannerService 构造无 llm_client 参数 → 新用例 TypeError
   （既有实现）；PlannerSession 无 v1.2 字段 → Pydantic 校验失败；ROUND1 无 kind
   → 断言失败。既有 22 用例保持全绿（None 兜底向后兼容）。
"""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.domain.services.planner_service import (
    ROUND1_QUESTIONS,
    ROUND2_QUESTIONS,
    PlannerService,
)

_MUST_ANSWER_KEYS = ("题材", "篇幅", "主题")
"""通用必答项 key（服务端强约束，§6 R11 ①）。"""


def _sid() -> uuid.UUID:
    return uuid.uuid4()


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _session(**overrides) -> PlannerSession:
    base = dict(
        id=_sid(),
        project_id=_pid(),
        status="drafting",
        one_liner="写一本关于时间旅者的悬疑小说",
        round=1,
        asked_questions=list(ROUND1_QUESTIONS),
        answers={},
        authorized=[],
        writing_plan_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return PlannerSession(**base)


def _make_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_planner_session.return_value = None
    repo.get_writing_plan.return_value = None
    return repo


def _llm_json(questions=None, confirmed_items=None, conflicts=None) -> str:
    """构造 LLM 结构化 JSON 输出字符串（spec §5.1 prompt 输出形状）。"""
    return json.dumps(
        {
            "questions": questions or [],
            "confirmed_items": confirmed_items or [],
            "conflicts": conflicts or [],
        },
        ensure_ascii=False,
    )


def _make_llm_client(content: str) -> AsyncMock:
    llm = AsyncMock()
    llm.chat.return_value = ChatResponse(content=content, model="test")
    return llm


def _outline_dummy():
    from types import SimpleNamespace

    return SimpleNamespace(id=uuid.uuid4())


def _char_dummy():
    from types import SimpleNamespace

    return SimpleNamespace(id=uuid.uuid4())


def _make_service(
    repo: AsyncMock,
    llm_client: AsyncMock | None = None,
    project_context_getter: AsyncMock | None = None,
    prompt_manager: AsyncMock | None = None,
    llm_default_model: str = "test/model",
) -> PlannerService:
    """v1.2 装配：默认注入 llm_client（None 时走确定性兜底）。

    #977 迁移：透传 llm_default_model（默认非空），供 GREEN 后 model 解析链取全局默认。
    """
    return PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=AsyncMock(return_value=_outline_dummy()),
        character_service=AsyncMock(return_value=_char_dummy()),
        llm_client=llm_client,
        project_context_getter=project_context_getter
        or AsyncMock(return_value="设定摘要：时间旅者，悬疑基调"),
        prompt_manager=prompt_manager,
        llm_default_model=llm_default_model,
    )


# ── PlannerSession v1.2 字段默认值（§2.2）─────────────────────────


def test_planner_session_v12_fields_defaults():
    """PlannerSession 新字段默认值（confirmed_items/conflicts/confirming）。"""
    session = PlannerSession(id=_sid(), project_id=_pid(), one_liner="一句话")
    assert session.confirmed_items == []
    assert session.conflicts == []
    assert session.confirming is False


# ── start：LLM 动态提问（§5.1 + M13）──────────────────────────────


@pytest.mark.asyncio
async def test_start_llm_generates_mixed_kind_questions():
    """start 装配 llm_client → 通用必答 + 针对性并存（kind 字段断言，≤5 问）。"""
    repo = _make_repo()
    llm = _make_llm_client(
        _llm_json(
            questions=[
                {
                    "id": "q1",
                    "text": "题材：悬疑为主还是悬疑+科幻混合？",
                    "template": "悬疑为主，但加入 ___ 元素",
                    "kind": "general",
                },
                {
                    "id": "q2",
                    "text": "篇幅：预计多少字？",
                    "template": "约 ___ 字",
                    "kind": "general",
                },
                {
                    "id": "q3",
                    "text": "主题：能否一句话描述主题？",
                    "template": "主题是 ___",
                    "kind": "general",
                },
                {
                    "id": "q4",
                    "text": "时间旅者的穿越机制是设备还是能力？",
                    "template": "穿越通过 ___ 实现",
                    "kind": "targeted",
                },
            ]
        )
    )
    svc = _make_service(repo, llm_client=llm)

    session = await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    assert session.status == "drafting"
    assert len(session.asked_questions) <= 5
    kinds = {q["kind"] for q in session.asked_questions}
    assert "general" in kinds and "targeted" in kinds
    assert all(q.get("template", "").strip() for q in session.asked_questions)
    llm.chat.assert_awaited_once()
    repo.add_planner_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_llm_missing_must_answer_backfills():
    """服务端必答项强约束：LLM 输出缺必答项 → 重试 1 次 → 仍缺 → 补问。"""
    repo = _make_repo()
    payload = _llm_json(
        questions=[
            {
                "id": "q1",
                "text": "需要几个主要配角？",
                "template": "___ 个",
                "kind": "general",
            },
            {
                "id": "q2",
                "text": "时间旅者的穿越机制是设备还是能力？",
                "template": "穿越通过 ___ 实现",
                "kind": "targeted",
            },
        ]
    )
    llm = _make_llm_client(payload)
    svc = _make_service(repo, llm_client=llm)

    session = await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    texts = [q["text"] for q in session.asked_questions]
    for key in _MUST_ANSWER_KEYS:
        assert any(key in t for t in texts), f"必答项 {key} 缺失"
    assert llm.chat.await_count == 2  # 重试 1 次


@pytest.mark.asyncio
async def test_start_llm_failure_falls_back_round1():
    """LLM 调用失败 → 重试 1 次 → 仍失败 → ROUND1 确定性兜底（场景 15）。"""
    repo = _make_repo()
    llm = AsyncMock()
    llm.chat.side_effect = RuntimeError("llm down")
    svc = _make_service(repo, llm_client=llm)

    session = await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    assert [q["id"] for q in session.asked_questions] == [q["id"] for q in ROUND1_QUESTIONS]
    assert all(q.get("kind") == "general" for q in session.asked_questions)
    assert llm.chat.await_count == 2  # 重试 1 次


@pytest.mark.asyncio
async def test_start_no_llm_client_uses_round1():
    """llm_client=None（未装配）→ 确定性兜底 ROUND1（向后兼容）。"""
    repo = _make_repo()
    svc = PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=AsyncMock(return_value=_outline_dummy()),
        character_service=AsyncMock(return_value=_char_dummy()),
    )

    session = await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    assert [q["id"] for q in session.asked_questions] == [q["id"] for q in ROUND1_QUESTIONS]


# ── respond：确定项提取 + 只问未确定项（D1 需求 2）────────────────


@pytest.mark.asyncio
async def test_respond_llm_extracts_confirmed_and_filters_confirmed_question():
    """回答后 LLM 提取 confirmed_items 落库；下轮过滤已确定项问题。"""
    repo = _make_repo()
    session = _session(
        round=1,
        asked_questions=[
            {
                "id": "q1",
                "text": "题材：悬疑为主还是悬疑+科幻混合？",
                "template": "悬疑为主，但加入 ___ 元素",
                "kind": "general",
            }
        ],
    )
    repo.get_planner_session.return_value = session
    llm = _make_llm_client(
        _llm_json(
            questions=[
                {
                    "id": "q5",
                    "text": "配角：需要几个主要配角？",
                    "template": "___ 个",
                    "kind": "general",
                },
                {
                    "id": "q6",
                    "text": "题材：确认是悬疑+时间悖论混合？",
                    "template": "题材是 ___",
                    "kind": "general",
                },
            ],
            confirmed_items=[{"key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user"}],
        )
    )
    svc = _make_service(repo, llm_client=llm)

    result = await svc.respond(session.id, {"q1": "悬疑为主，加入时间悖论"})

    # 确定项落库
    assert session.confirmed_items == [
        {"key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user"}
    ]
    # 下轮只问未确定项：q6 题材已确定 → 过滤
    assert [q["id"] for q in result.questions] == ["q5"]
    assert result.completed is False
    llm.chat.assert_awaited_once()
    repo.update_planner_session.assert_awaited()


@pytest.mark.asyncio
async def test_respond_confirmed_items_merge_by_key():
    """确定项合并去重：已存在 key 覆盖 value，新 key 追加。"""
    repo = _make_repo()
    session = _session(
        round=1,
        asked_questions=[{"id": "q1", "text": "题材：？", "template": "___", "kind": "general"}],
        confirmed_items=[{"key": "题材", "value": "悬疑", "source": "llm_inferred"}],
    )
    repo.get_planner_session.return_value = session
    llm = _make_llm_client(
        _llm_json(
            questions=[],
            confirmed_items=[
                {"key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user"},
                {"key": "篇幅", "value": "10 万字", "source": "user"},
            ],
        )
    )
    svc = _make_service(repo, llm_client=llm)

    await svc.respond(session.id, {"q1": "悬疑为主，加入时间悖论"})

    by_key = {item["key"]: item["value"] for item in session.confirmed_items}
    assert by_key["题材"] == "悬疑 + 时间悖论科幻"  # 覆盖
    assert by_key["篇幅"] == "10 万字"  # 追加
    assert len(session.confirmed_items) == 2


# ── respond：冲突回问（D1 需求 3 + 场景 16）────────────────────────


@pytest.mark.asyncio
async def test_respond_llm_conflict_records_and_asks():
    """LLM 检测冲突 → conflicts 记录（pending）+ kind=conflict 回问。"""
    repo = _make_repo()
    session = _session(
        round=1,
        asked_questions=[
            {
                "id": "q5",
                "text": "配角：需要几个主要配角？",
                "template": "___ 个",
                "kind": "general",
            }
        ],
    )
    repo.get_planner_session.return_value = session
    llm = _make_llm_client(
        _llm_json(
            questions=[
                {
                    "id": "q6",
                    "text": "5 个配角对 10 万字篇幅偏多，建议 2-3 个——仍按 5 个？",
                    "template": "配角按 ___ 个",
                    "kind": "conflict",
                }
            ],
            conflicts=[{"conflict_with": "篇幅/复杂度合理性", "resolution": "pending"}],
        )
    )
    svc = _make_service(repo, llm_client=llm)

    result = await svc.respond(session.id, {"q5": "配角 5 个"})

    assert len(session.conflicts) == 1
    conflict = session.conflicts[0]
    assert conflict["conflict_with"] == "篇幅/复杂度合理性"
    assert conflict["resolution"] == "pending"
    assert conflict["question_id"] == "q5"
    assert conflict["answer"] == "配角 5 个"
    assert conflict["round"] == session.round
    assert any(q.get("kind") == "conflict" for q in result.questions)
    repo.update_planner_session.assert_awaited()


@pytest.mark.asyncio
async def test_respond_conflict_resolved_marks_resolution():
    """用户对冲突问题重新回答 → 对应 pending 记录 resolution=resolved。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=[
            {
                "id": "q6",
                "text": "5 个配角对 10 万字篇幅偏多，仍按 5 个？",
                "template": "配角按 ___ 个",
                "kind": "conflict",
            }
        ],
        answers={"q5": "配角 5 个"},
        confirmed_items=[
            {"key": "题材", "value": "悬疑", "source": "user"},
            {"key": "篇幅", "value": "10 万字", "source": "user"},
            {"key": "主题", "value": "自我救赎", "source": "user"},
        ],
        conflicts=[
            {
                "round": 1,
                "question_id": "q5",
                "answer": "配角 5 个",
                "conflict_with": "篇幅/复杂度合理性",
                "resolution": "pending",
            }
        ],
    )
    repo.get_planner_session.return_value = session
    llm = _make_llm_client(
        _llm_json(
            questions=[],
            confirmed_items=[{"key": "配角数", "value": "2 个", "source": "user"}],
            conflicts=[{"conflict_with": "篇幅/复杂度合理性", "resolution": "resolved"}],
        )
    )
    svc = _make_service(repo, llm_client=llm)

    result = await svc.respond(session.id, {"q6": "那配角 2 个"})

    assert session.conflicts[0]["resolution"] == "resolved"
    assert result.completed is False


# ── 末尾总体确认（D1 需求 4 + 场景 17）─────────────────────────────


@pytest.mark.asyncio
async def test_respond_all_must_answered_enters_confirming():
    """必答项齐备 + 无 pending 冲突 → confirming=true + questions 空 + 列全部确定项。"""
    repo = _make_repo()
    session = _session(
        round=1,
        asked_questions=[{"id": "q1", "text": "题材：？", "template": "___", "kind": "general"}],
        confirmed_items=[
            {"key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user"},
            {"key": "篇幅", "value": "10 万字", "source": "user"},
            {"key": "主题", "value": "时间旅者自我救赎", "source": "llm_inferred"},
        ],
    )
    repo.get_planner_session.return_value = session
    llm = _make_llm_client(_llm_json(questions=[], confirmed_items=[], conflicts=[]))
    svc = _make_service(repo, llm_client=llm)

    result = await svc.respond(session.id, {"q1": "悬疑为主"})

    assert result.confirming is True
    assert result.questions == []
    assert session.confirming is True
    keys = {item["key"] for item in result.confirmed_items}
    assert set(_MUST_ANSWER_KEYS) <= keys
    assert result.completed is False


@pytest.mark.asyncio
async def test_respond_confirm_true_completes_plan():
    """confirm=true + confirming → 完成（WritingPlan status=ready），不调 LLM。"""
    repo = _make_repo()
    session = _session(
        round=1,
        asked_questions=[],
        confirming=True,
        confirmed_items=[
            {"key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user"},
            {"key": "篇幅", "value": "10 万字", "source": "user"},
            {"key": "主题", "value": "时间旅者自我救赎", "source": "llm_inferred"},
        ],
    )
    repo.get_planner_session.return_value = session
    llm = _make_llm_client(_llm_json())
    svc = _make_service(repo, llm_client=llm)

    result = await svc.respond(session.id, {}, confirm=True)

    assert result.completed is True
    assert result.writing_plan is not None
    assert result.writing_plan.status == "ready"
    assert result.writing_plan.project_id == session.project_id
    assert session.status == "completed"
    assert session.writing_plan_id == result.writing_plan.id
    llm.chat.assert_not_awaited()  # confirm 路径不调 LLM
    repo.add_writing_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_respond_confirm_not_confirming_raises():
    """confirm=true + 非 confirming → ValueError（API 映射 422，§3.5）。"""
    repo = _make_repo()
    session = _session(round=1, asked_questions=list(ROUND1_QUESTIONS))
    repo.get_planner_session.return_value = session
    svc = _make_service(repo, llm_client=_make_llm_client(_llm_json()))

    with pytest.raises(ValueError, match="确认"):
        await svc.respond(session.id, {}, confirm=True)


# ── respond：LLM 失败降级（场景 15）───────────────────────────────


@pytest.mark.asyncio
async def test_respond_llm_failure_falls_back_deterministic():
    """respond 时 LLM 失败 → 重试 1 次 → 仍失败 → 确定性推进（ROUND1→ROUND2）。"""
    repo = _make_repo()
    session = _session(round=1, asked_questions=list(ROUND1_QUESTIONS))
    repo.get_planner_session.return_value = session
    llm = AsyncMock()
    llm.chat.side_effect = RuntimeError("llm down")
    svc = _make_service(repo, llm_client=llm)

    result = await svc.respond(
        session.id,
        {"q1": "悬疑为主，加入时间悖论", "q2": "约 8 万字", "q3": "主角是时间旅者"},
    )

    assert result.round == 2
    assert result.completed is False
    assert [q["id"] for q in result.questions] == [q["id"] for q in ROUND2_QUESTIONS]
    assert llm.chat.await_count == 2  # 重试 1 次


# ── prompt 注入（§5.1 prompt 输入）─────────────────────────────────


@pytest.mark.asyncio
async def test_respond_llm_prompt_includes_context():
    """chat 调用 messages 含 one_liner + 项目设定摘要 + 会话历史。"""
    repo = _make_repo()
    session = _session(
        round=1,
        asked_questions=[
            {
                "id": "q1",
                "text": "题材：悬疑为主还是悬疑+科幻混合？",
                "template": "悬疑为主，但加入 ___ 元素",
                "kind": "general",
            }
        ],
        confirmed_items=[{"key": "篇幅", "value": "10 万字", "source": "user"}],
    )
    repo.get_planner_session.return_value = session
    llm = _make_llm_client(_llm_json(questions=[], confirmed_items=[], conflicts=[]))
    context_getter = AsyncMock(return_value="设定摘要：时间旅者，悬疑基调")
    svc = _make_service(repo, llm_client=llm, project_context_getter=context_getter)

    await svc.respond(session.id, {"q1": "悬疑为主，加入时间悖论"})

    call_args = llm.chat.await_args
    assert call_args is not None
    messages = call_args.args[0]
    content = "\n".join(str(m.get("content", "")) for m in messages)
    assert "写一本关于时间旅者的悬疑小说" in content  # one_liner
    assert "设定摘要：时间旅者" in content  # project_context_getter 注入
    assert "篇幅" in content  # 会话历史（已确定项）
    context_getter.assert_awaited_once_with(session.project_id)


# ── Coverage-Gap 补测（2026-08-19 CI coverage-backend 98.34% 缺口）──
# 缺失行映射：418-420（主角从确定项提取）/ 490（无 llm_client 早退）/
# 506-511（垃圾 JSON 重试）/ 536（无 context getter）/ 540-554（模板路径）/
# 611/614-617/626/630/635（解析失败分支）/ 679-680（空 answers 冲突）/
# 686->685（resolved 无 pending 匹配）。


@pytest.mark.asyncio
async def test_protagonist_name_from_confirmed_items():
    """主角名提取：confirmed_items 含「主角」key → value 用之（418-420）。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={},
        confirmed_items=[{"key": "主角", "value": "时间旅者", "source": "user"}],
    )
    repo.get_planner_session.return_value = session
    character_service = AsyncMock(return_value=_char_dummy())
    svc = PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=AsyncMock(return_value=_outline_dummy()),
        character_service=character_service,
    )

    await svc.respond(session.id, {"q4": "3 卷", "q5": "配角自定"})

    call_kwargs = character_service.await_args.kwargs
    assert call_kwargs["name"] == "时间旅者"


@pytest.mark.asyncio
async def test_protagonist_name_confirmed_value_blank_falls_back():
    """主角 key 存在但 value 空白 → 回退 q3 提取（419->416 分支）。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={"q3": "主角是时间旅者"},
        confirmed_items=[{"key": "主角", "value": "   ", "source": "user"}],
    )
    repo.get_planner_session.return_value = session
    character_service = AsyncMock(return_value=_char_dummy())
    svc = PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=AsyncMock(return_value=_outline_dummy()),
        character_service=character_service,
    )

    await svc.respond(session.id, {"q4": "3 卷", "q5": "配角自定"})

    call_kwargs = character_service.await_args.kwargs
    assert call_kwargs["name"] == "时间旅者"


@pytest.mark.asyncio
async def test_llm_output_invalid_json_retries_then_fallback():
    """LLM 输出垃圾文本（无 JSON）→ 重试 1 次 → 仍失败 → ROUND1 兜底（506-511/611）。"""
    repo = _make_repo()
    llm = _make_llm_client("这不是 JSON，只是闲聊")
    svc = _make_service(repo, llm_client=llm)

    session = await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    assert [q["id"] for q in session.asked_questions] == [q["id"] for q in ROUND1_QUESTIONS]
    assert llm.chat.await_count == 2  # 输出不合格 → 重试 1 次


@pytest.mark.asyncio
async def test_llm_payload_unparsable_variants():
    """_parse_llm_payload 各失败分支（611/614-617/626/630/635）+ 成功路径。"""
    svc = PlannerService(repo=_make_repo())

    assert svc._parse_llm_payload("无花括号") is None  # 611 fragment None
    assert svc._parse_llm_payload('{"a": }') is None  # 614-615 JSONDecodeError
    assert svc._parse_llm_payload("[1, 2]") is None  # 617 非 dict（fragment None 路径）
    assert svc._parse_llm_payload('{"questions": {}}') is None  # 626 非 list
    bad_item = '{"questions": [1], "confirmed_items": [], "conflicts": []}'
    assert svc._parse_llm_payload(bad_item) is None  # 630 item 非 dict
    bad_fields = '{"questions": [{"id": "x"}], "confirmed_items": [], "conflicts": []}'
    assert svc._parse_llm_payload(bad_fields) is None  # 635 缺 text/kind

    ok = svc._parse_llm_payload(
        '{"questions": [{"id": "q1", "text": "题材？", "template": "___", "kind": "general"}], '
        '"confirmed_items": [{"key": "题材", "value": "悬疑", "source": "user"}], '
        '"conflicts": []}'
    )
    assert ok is not None
    assert ok[0][0]["id"] == "q1"
    assert ok[1][0]["key"] == "题材"


@pytest.mark.asyncio
async def test_start_llm_without_context_getter():
    """llm_client 装配 + project_context_getter=None → ctx 空串路径（536）。"""
    repo = _make_repo()
    llm = _make_llm_client(
        _llm_json(
            questions=[
                {
                    "id": "q1",
                    "text": "题材：悬疑为主还是悬疑+科幻混合？",
                    "template": "悬疑为主，但加入 ___ 元素",
                    "kind": "general",
                },
                {
                    "id": "q2",
                    "text": "篇幅：预计多少字？",
                    "template": "约 ___ 字",
                    "kind": "general",
                },
                {
                    "id": "q3",
                    "text": "主题：能否一句话描述主题？",
                    "template": "主题是 ___",
                    "kind": "general",
                },
            ]
        )
    )
    svc = PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        llm_client=llm,
        project_context_getter=None,  # 未装配
        prompt_manager=None,
        llm_default_model="test/model",  # #977 迁移：直构 LLM 用例透传全局默认
    )

    session = await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    assert session.status == "drafting"
    assert len(session.asked_questions) == 3
    llm.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_questions_no_llm_client_returns_none():
    """_generate_questions 私有方法：llm_client=None → None（490 防御早退）。"""
    repo = _make_repo()
    svc = PlannerService(repo=repo, write_auto=AsyncMock(return_value=None))
    session = _session(round=1, asked_questions=list(ROUND1_QUESTIONS))

    assert await svc._generate_questions(session) is None


@pytest.mark.asyncio
async def test_apply_conflicts_resolved_no_pending_match():
    """resolved 冲突但既有记录无 pending 匹配 → 686 内层 False 分支 + 仍追加。"""
    session = _session(
        round=2,
        answers={"q5": "配角 5 个"},
        conflicts=[
            {
                "round": 1,
                "question_id": "q5",
                "answer": "配角 5 个",
                "conflict_with": "篇幅/复杂度合理性",
                "resolution": "resolved",  # 已是 resolved，非 pending
            }
        ],
    )
    PlannerService._apply_conflicts(
        session,
        {"q6": "那配角 2 个"},
        [{"conflict_with": "篇幅/复杂度合理性", "resolution": "resolved"}],
    )

    assert session.conflicts[0]["resolution"] == "resolved"
    assert len(session.conflicts) == 2  # 新记录追加
    assert session.conflicts[1]["conflict_with"] == "篇幅/复杂度合理性"


@pytest.mark.asyncio
async def test_apply_conflicts_empty_answers():
    """answers 空 → first_qid/answer_text 空串分支（679-680）。"""
    session = _session(round=1)
    PlannerService._apply_conflicts(
        session,
        {},
        [{"conflict_with": "篇幅/复杂度合理性", "resolution": "pending"}],
    )

    assert session.conflicts[0]["question_id"] == ""
    assert session.conflicts[0]["answer"] == ""


# ── #517 英文 key 归一化（真实 LLM 输出英文 key → 必须能进入 confirming）──


@pytest.mark.asyncio
async def test_respond_english_keys_normalized_to_confirming():
    """#517 回归: LLM 输出英文 confirmed_items key（genre/length/theme）→
    归一化后必答项齐备 → confirming=true（真实 deepseek 实测英文 key，
    原实现与中文 _MUST_ANSWER_KEYS 永不匹配 → 访谈永不 confirming）。"""
    repo = _make_repo()
    session = _session(
        round=1,
        asked_questions=[{"id": "q1", "text": "题材：？", "template": "___", "kind": "general"}],
    )
    repo.get_planner_session.return_value = session
    llm = _make_llm_client(
        _llm_json(
            questions=[],
            confirmed_items=[
                {"key": "genre", "value": "悬疑 + 时间悖论科幻", "source": "user"},
                {"key": "length", "value": "10 万字", "source": "user"},
                {"key": "theme", "value": "时间旅者自我救赎", "source": "llm_inferred"},
            ],
            conflicts=[],
        )
    )
    svc = _make_service(repo, llm_client=llm)

    result = await svc.respond(session.id, {"q1": "悬疑为主"})

    assert result.confirming is True, (
        f"#517: 英文 key 未归一化，confirming 仍 false（keys="
        f"{[i.get('key') for i in result.confirmed_items]}）"
    )
    assert result.questions == []
    keys = {item["key"] for item in result.confirmed_items}
    assert set(_MUST_ANSWER_KEYS) <= keys


@pytest.mark.asyncio
async def test_respond_mixed_language_keys_normalized_to_confirming():
    """#517 回归: 混合语言 key（题材中文 + 其余英文）→ 归一化后 confirming。"""
    repo = _make_repo()
    session = _session(
        round=1,
        asked_questions=[{"id": "q1", "text": "题材：？", "template": "___", "kind": "general"}],
        confirmed_items=[{"key": "题材", "value": "悬疑", "source": "user"}],
    )
    repo.get_planner_session.return_value = session
    llm = _make_llm_client(
        _llm_json(
            questions=[],
            confirmed_items=[
                {"key": "length", "value": "8 万字", "source": "user"},
                {"key": "theme", "value": "救赎", "source": "llm_inferred"},
            ],
            conflicts=[],
        )
    )
    svc = _make_service(repo, llm_client=llm)

    result = await svc.respond(session.id, {"q1": "悬疑为主"})

    assert result.confirming is True
    keys = {item["key"] for item in result.confirmed_items}
    assert set(_MUST_ANSWER_KEYS) <= keys
