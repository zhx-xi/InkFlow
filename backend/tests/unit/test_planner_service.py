"""F44 阶段1 访谈式 Planner 服务单测（TDD RED 阶段）。

权威来源：specs/f44-long-task-orchestrator/spec.md §2.2（PlannerSession）、
§5.1（访谈循环：≤5 问/轮、问题即模板、分批节奏、授权、auto 兜底）、§13.1 M1/M2。
本文件为 `domain/services/planner_service.py`（NEW）定义契约。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【模块契约】`inkflow.domain.services.planner_service` 必须暴露：
   - `ROUND1_QUESTIONS: list[dict]` — 第一轮问题（题材/体裁/篇幅 → q1 题材、
     q2 篇幅、q3 主角；每项含 id/text/template，≤5 问，问题即模板）
   - `ROUND2_QUESTIONS: list[dict]` — 第二轮问题（分卷+配角 → q4 分卷、q5 配角）
   - `PlannerRespondResult(BaseModel)`：session_id / round / completed /
     questions: list[dict] / writing_plan: WritingPlan | None
   - `PlannerService`，构造签名（关键字）：
       PlannerService(*, repo, write_auto=None, outline_service=None,
                     character_service=None)
     repo: BookRepositoryProtocol（鸭子类型，add/get/update planner_session
       + writing_plan）；write_auto: 可调用 async fn(project_id, one_liner)
       （F42 委托契约注入点，None = 未装配时 auto 路径报错）；
     outline_service/character_service: 鸭子对象（产出直写落库；
       None = 完成路径跳过落库，仅测试隔离用）
   - 方法：
     - `async start(project_id: uuid.UUID, one_liner: str) -> PlannerSession`
       创建 drafting 会话 + 返回第一轮问题（round=1）
     - `async respond(session_id: uuid.UUID, answers: dict[str, str],
       auto: bool = False) -> PlannerRespondResult`
       处理回答 → 下一轮问 / 完成返回 WritingPlan
     - `async get(session_id: uuid.UUID) -> PlannerSession | None`
       会话状态快照（asked_questions/answers，问题即模板复用）
     - `async auto(project_id: uuid.UUID, one_liner: str) -> WritingPlan`
       「全部你决定」= 拒访谈 → 跑 write_auto → WritingPlan 状态=auto

2. 【访谈循环契约】（§5.1 + spec §9.2 场景 3）
   - 每轮 ≤5 问（len(questions) <= 5）
   - 问题即模板：questions[i]["template"] 返回非空可复制模板
   - 分批节奏：ROUND1（题材/篇幅/主角）→ ROUND2（分卷/配角）
   - 大纲/主角 = 必须对话确认（q1-q3 必须回答才进下一轮）
   - 配角/细节 = 显式授权后自定（answers 含「配角自定」→ session.authorized
     记录「配角」等授权项）
   - 【宽容映射】CLI 单字符串回答（answers={"answer": text}，键固定 "answer"）
     视为对当前轮第一个未答必答问题的回答——记录进 session.answers（键=该
     问题 id）。CLI respond 契约依赖此语义（tests/cli/test_book_cmd.py 同源）。
   - 轮次超上限（>=5 轮）→ 自动完成（已获信息 + 其余自定授权，边界 2）
   - 完成后：创建 WritingPlan（status=ready，title=one_liner 或回答提炼），
     session.status=completed + writing_plan_id 关联
   - 【planner 产出直写 outline/character】（§2.1 决策论证表 + §5.1）：
     完成后经注入的 outline_service/character_service 落库——outline
     （level=overall，书级锚点）→ WritingPlan.root_outline_id 回填；主角
     character → WritingPlan.character_ids 回填。断言 mock service 被调用。

3. 【「全部你决定」契约】（§5.1 + §13.1 M2 + 边界 1）
   - `respond(auto=True)`：会话 status=declined → 调用注入的 write_auto
     （F42 委托）→ 创建 WritingPlan status=auto → completed=true
   - `auto()`：等价直接路径——declined 会话 + write_auto 调用 + WritingPlan
     status=auto
   - 断言 write_auto 被调用（AsyncMock）+ WritingPlan.status == "auto"

4. 【会话不存在】respond/get 对未知 session_id → 返回/抛出可识别信号：
   - get → None
   - respond → 抛 ValueError("会话不存在")（API 层映射 404）

5. 【mock 策略】repo 用 AsyncMock（方法 add_planner_session/get_planner_session/
   update_planner_session/add_writing_plan/get_writing_plan/update_writing_plan）；
   write_auto 用 AsyncMock(return_value=None)。GREEN 实现调 repo 方法断言
   记录在 mock 上。

6. 【RED 预期形态】模块不存在 → 本文件全用例 ImportError 收集期失败
   （ModuleNotFoundError）。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.services.planner_service import (
    ROUND1_QUESTIONS,
    ROUND2_QUESTIONS,
    PlannerService,
)


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


def _make_service(
    repo: AsyncMock | None = None,
    write_auto: AsyncMock | None = None,
    outline_service: AsyncMock | None = None,
    character_service: AsyncMock | None = None,
) -> PlannerService:
    return PlannerService(
        repo=repo or _make_repo(),
        write_auto=write_auto or AsyncMock(return_value=None),
        outline_service=outline_service or AsyncMock(return_value=_outline_dummy()),
        character_service=character_service or AsyncMock(return_value=_char_dummy()),
    )


def _outline_dummy():
    from types import SimpleNamespace

    return SimpleNamespace(id=uuid.uuid4())


def _char_dummy():
    from types import SimpleNamespace

    return SimpleNamespace(id=uuid.uuid4())


# ── 问题模板 ──────────────────────────────────────────────────────


def test_round1_questions_contract():
    """第一轮问题 ≤5 且问题即模板（id/text/template 三键 + template 非空）。"""
    assert len(ROUND1_QUESTIONS) <= 5
    assert ROUND1_QUESTIONS
    for q in ROUND1_QUESTIONS:
        assert "id" in q and "text" in q and "template" in q
        assert q["template"].strip()


def test_round2_questions_contract():
    """第二轮问题（分卷+配角）≤5 且问题即模板。"""
    assert len(ROUND2_QUESTIONS) <= 5
    for q in ROUND2_QUESTIONS:
        assert "id" in q and "text" in q and "template" in q
        assert q["template"].strip()


# ── start ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_creates_session_with_round1_questions():
    """start → 创建 drafting 会话 + 第一轮 ≤5 问（问题即模板）。"""
    repo = _make_repo()
    svc = _make_service(repo)
    project_id, one_liner = _pid(), "写一本关于时间旅者的悬疑小说"

    session = await svc.start(project_id, one_liner)

    assert session.status == "drafting"
    assert session.round == 1
    assert session.one_liner == one_liner
    assert len(session.asked_questions) <= 5
    assert [q["id"] for q in session.asked_questions] == [q["id"] for q in ROUND1_QUESTIONS]
    repo.add_planner_session.assert_awaited_once()


# ── respond：轮 1 → 轮 2 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_respond_round1_to_round2():
    """回答 q1-q3（大纲/主角必答）→ 下一轮 q4/q5（round=2, completed=False）。"""
    repo = _make_repo()
    session = _session(round=1, asked_questions=list(ROUND1_QUESTIONS))
    repo.get_planner_session.return_value = session
    svc = _make_service(repo)

    result = await svc.respond(
        session.id,
        {"q1": "悬疑为主，加入时间悖论", "q2": "约 8 万字", "q3": "主角是时间旅者"},
    )

    assert result.round == 2
    assert result.completed is False
    assert [q["id"] for q in result.questions] == [q["id"] for q in ROUND2_QUESTIONS]
    repo.update_planner_session.assert_awaited()


# ── respond：全部完成 → WritingPlan ───────────────────────────────


@pytest.mark.asyncio
async def test_respond_complete_creates_writing_plan():
    """回答全部轮次（含配角授权）→ completed + WritingPlan 落库 + 会话 completed。"""
    repo = _make_repo()
    session = _session(round=2, asked_questions=list(ROUND2_QUESTIONS), answers={})
    repo.get_planner_session.return_value = session
    svc = _make_service(repo)

    result = await svc.respond(
        session.id,
        {"q4": "3 卷", "q5": "配角自定"},
    )

    assert result.completed is True
    assert result.writing_plan is not None
    assert result.writing_plan.status == "ready"
    assert result.writing_plan.project_id == session.project_id
    assert result.writing_plan.title == session.one_liner
    # 授权项记录（§5.1：配角/细节显式授权后自定）
    assert session.authorized
    assert any("配角" in a for a in session.authorized)
    repo.add_writing_plan.assert_awaited_once()
    repo.update_planner_session.assert_awaited()


@pytest.mark.asyncio
async def test_respond_complete_writes_outline_and_character():
    """完成后 planner 产出直写 outline/character（§2.1 + §5.1）：
    outline(overall) → root_outline_id 回填；主角 character → character_ids 回填。"""
    repo = _make_repo()
    session = _session(round=2, asked_questions=list(ROUND2_QUESTIONS), answers={})
    repo.get_planner_session.return_value = session
    outline_service = AsyncMock(return_value=_outline_dummy())
    character_service = AsyncMock(return_value=_char_dummy())
    svc = _make_service(repo, outline_service=outline_service, character_service=character_service)

    result = await svc.respond(
        session.id,
        {"q4": "3 卷", "q5": "配角自定"},
    )

    assert result.completed is True
    assert result.writing_plan is not None
    assert result.writing_plan.root_outline_id is not None
    assert result.writing_plan.character_ids  # 主角 character 落库
    outline_service.assert_awaited_once()
    character_service.assert_awaited_once()


@pytest.mark.asyncio
async def test_respond_requires_must_answer_questions():
    """大纲/主角必须对话确认：缺 q1-q3 → 不完成、仍轮 1。"""
    repo = _make_repo()
    session = _session(round=1, asked_questions=list(ROUND1_QUESTIONS))
    repo.get_planner_session.return_value = session
    svc = _make_service(repo)

    result = await svc.respond(session.id, {"q1": "悬疑为主"})

    assert result.completed is False
    assert result.round == 1
    repo.add_writing_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_respond_free_answer_maps_to_first_must_answer():
    """宽容映射：CLI 单字符串回答（answers={"answer": text}）→ 记入第一个未答必答问题。"""
    repo = _make_repo()
    session = _session(round=1, asked_questions=list(ROUND1_QUESTIONS))
    repo.get_planner_session.return_value = session
    svc = _make_service(repo)

    result = await svc.respond(session.id, {"answer": "悬疑为主，加入时间悖论"})

    assert result.completed is False
    # 自由回答被记录到第一个必答问题 q1（键=问题 id）
    assert session.answers.get("q1") == "悬疑为主，加入时间悖论"
    repo.update_planner_session.assert_awaited()


# ── respond：auto 路径 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_respond_auto_runs_write_auto():
    """「全部你决定」（auto=True）→ 拒访谈（declined）→ 跑 F42 write_auto →
    WritingPlan 状态=auto（spec §5.1 + M2）。"""
    repo = _make_repo()
    session = _session(round=1, asked_questions=list(ROUND1_QUESTIONS))
    repo.get_planner_session.return_value = session
    write_auto = AsyncMock(return_value=None)
    svc = _make_service(repo, write_auto)

    result = await svc.respond(session.id, {}, auto=True)

    assert result.completed is True
    assert result.writing_plan is not None
    assert result.writing_plan.status == "auto"
    write_auto.assert_awaited_once()
    assert session.status == "declined"
    repo.update_planner_session.assert_awaited()


# ── auto：直接路径 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_creates_plan_with_status_auto():
    """auto() → 直接跑 F42 write_auto + WritingPlan 状态=auto（M2 验收）。"""
    repo = _make_repo()
    write_auto = AsyncMock(return_value=None)
    svc = _make_service(repo, write_auto)
    project_id, one_liner = _pid(), "写一本关于时间旅者的悬疑小说"

    plan = await svc.auto(project_id, one_liner)

    assert plan is not None
    assert plan.status == "auto"
    assert plan.project_id == project_id
    write_auto.assert_awaited_once_with(project_id, one_liner)
    repo.add_writing_plan.assert_awaited_once()


# ── get ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_session_snapshot():
    """get → 会话状态（asked_questions/answers 快照，问题即模板复用）。"""
    repo = _make_repo()
    session = _session(round=1, asked_questions=list(ROUND1_QUESTIONS))
    repo.get_planner_session.return_value = session
    svc = _make_service(repo)

    got = await svc.get(session.id)

    assert got is session
    repo.get_planner_session.assert_awaited_once_with(session.id)


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    """会话不存在 → get 返回 None。"""
    repo = _make_repo()
    repo.get_planner_session.return_value = None
    svc = _make_service(repo)

    assert await svc.get(uuid.uuid4()) is None


# ── respond：会话不存在 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_respond_missing_session_raises():
    """会话不存在 → respond 抛 ValueError（API 层映射 404）。"""
    repo = _make_repo()
    repo.get_planner_session.return_value = None
    svc = _make_service(repo)

    with pytest.raises(ValueError, match="会话不存在"):
        await svc.respond(uuid.uuid4(), {"q1": "x"})
