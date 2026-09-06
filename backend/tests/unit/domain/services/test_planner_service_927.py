"""F44 #927 planner 产物质量契约（TDD RED）。

覆盖四点：出题消费语境 / 标题短化 / 主角 role_rank / limits 提取。

权威来源：specs/f44-book-orchestrator/spec.md §5.1（LLM 动态提问按 one_liner 针对性
生成）、§2.1（WritingPlan.title）、§2.4（limits 多维上限）+ Issue #927 四缺陷。
本文件为 `domain/services/planner_service.py` 的 #927 修复定义契约。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约）
════════════════════════════════════════════════════════════════════

1. 【出题消费 one_liner 语境】
   - ROUND1_QUESTIONS 兜底题材题：text 含「题材」（必答项服务端校验依赖）但
     text 与 template 均不含「悬疑」等具体题材预设（#927 现象 1）；
   - llm_client 装配 + prompt_manager 未装配的手工 prompt：system 消息必须含
     「一句话构思」（既有）+ 指令「不相矛盾」——要求 LLM 基于 one_liner 针对性
     提问，one_liner 已明确的要素不得提出与之矛盾的问题；
   - i18n 模板 zh/en planner_interview.yaml system_prompt 含同款指令
     （zh「不相矛盾」/ en "not contradict"）。

2. 【标题短化】（#927 现象 2）
   - _complete / auto / _run_auto 路径：WritingPlan.title = one_liner.strip()
     前 30 字（对齐会话自动命名 30 字先例）；≤30 字时保持原文（向后兼容）；
   - outline name = plan.title + 「（书级大纲）」（总长 ≤40）；
     description 保留完整 one_liner。

3. 【主角 role_rank】（#927 现象 3）
   - _complete 调用 character_service 时传 extra={"role_rank": "protagonist"}
     （装配层经 CharacterCreate DTO 校验，见 test_planner_assembly_927.py）。

4. 【limits 从访谈 answers 提取】（#927 现象 4，拍板）
   - _complete：扫描 session.answers 全部 value + session.confirmed_items 全部
     value 的文本，正则 `\\d+` 紧跟「章」（忽略空白/换行；排除「第N章」章序引用；
     仅阿拉伯数字，中文数字范围外）；
   - 提取到 n → limits.max_chapters = n，max_agent_calls = 2n
     （卷轨 planner 拆章 + 逐章委托余量；保持 STAGE1「章:调用 = 1:2」精神）；
   - 提取不到 → 保守兜底 STAGE1_LIMITS（max_chapters=1, max_agent_calls=1，
     向后兼容既有行为）；多处命中取最大值。

5. 【RED 预期形态】当前实现：兜底题含悬疑预设 / title=one_liner 直赋 /
   character_service 无 extra / limits 写死 STAGE1 → 提取类/语境类/短化类/
   role_rank 类用例 FAIL；保守兜底与「第N章」防误抽用例现即 PASS（护栏）。
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import inkflow
from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.domain.services.planner_service import (
    ROUND1_QUESTIONS,
    ROUND2_QUESTIONS,
    PlannerService,
)

_LONG_ONE_LINER = (
    "写一本武侠仙侠门派经营小说，主角玄明继承破落宗门，"
    "带领师弟师妹在修真世界崛起，重振山门威名远扬天下"
)
"""49 字 one_liner（>30 字触发短化契约；模拟 #927 用户实测输入形态）。"""


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


def _outline_dummy() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _char_dummy() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _make_service(
    repo: AsyncMock,
    *,
    outline_service: AsyncMock | None = None,
    character_service: AsyncMock | None = None,
    llm_client: AsyncMock | None = None,
    llm_default_model: str = "test/model",
) -> PlannerService:
    # #977 迁移：透传 llm_default_model（默认非空），供 GREEN 后 model 解析链取全局默认。
    return PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=outline_service or AsyncMock(return_value=_outline_dummy()),
        character_service=character_service or AsyncMock(return_value=_char_dummy()),
        llm_client=llm_client,
        llm_default_model=llm_default_model,
    )


async def _complete_round2(
    svc: PlannerService,
    session: PlannerSession,
    round2_answers: dict[str, str],
):
    """round=2 会话答完 q4/q5 → 确定性完成（llm_client=None 路径）。"""
    return await svc.respond(session.id, round2_answers)


# ── 契约 1：出题消费 one_liner 语境（#927 现象 1）────────────────


def test_round1_genre_question_has_no_genre_preset():
    """兜底题材题不得自带「悬疑」预设（不消费 one_liner 的通用题模板缺陷）。"""
    q1 = ROUND1_QUESTIONS[0]
    assert "题材" in q1["text"]  # 必答项关键词强约束保留
    assert "悬疑" not in q1["text"], f"题面自带题材预设: {q1['text']}"
    assert "悬疑" not in q1["template"], f"模板自带题材预设: {q1['template']}"


@pytest.mark.asyncio
async def test_manual_prompt_directs_questions_at_one_liner():
    """手工 prompt（无 prompt_manager）system 必须含 one_liner 针对性指令。"""
    repo = _make_repo()
    payload = json.dumps(
        {
            "questions": [
                {
                    "id": "q1",
                    "text": "题材：武侠为主还是仙侠为主？",
                    "template": "以 ___ 为主",
                    "kind": "targeted",
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
            ],
            "confirmed_items": [],
            "conflicts": [],
        },
        ensure_ascii=False,
    )
    llm = AsyncMock()
    llm.chat.return_value = ChatResponse(content=payload, model="test")
    svc = _make_service(repo, llm_client=llm)

    await svc.start(_pid(), _LONG_ONE_LINER)

    call = llm.chat.await_args
    assert call is not None
    messages = call.args[0]
    system = "\n".join(
        str(m.get("content", "")) for m in messages if m.get("role") == "system"
    )
    assert "一句话构思" in system  # 既有：one_liner 注入
    assert "不相矛盾" in system, "prompt 缺少「针对一句话构思、不相矛盾」出题指令（#927）"


@pytest.mark.parametrize("lang,needle", [("zh", "不相矛盾"), ("en", "not contradict")])
def test_planner_interview_yaml_directs_one_liner(lang: str, needle: str):
    """i18n 出题模板（zh/en）system_prompt 必须含 one_liner 针对性指令。"""
    path = Path(inkflow.__file__).parent / "i18n" / "prompts" / lang / "planner_interview.yaml"
    content = path.read_text(encoding="utf-8")
    assert needle in content, f"{lang} planner_interview.yaml 缺少针对性出题指令（#927）"


# ── 契约 2：标题短化（#927 现象 2）───────────────────────────────


@pytest.mark.asyncio
async def test_complete_title_shortened_and_outline_aligned():
    """长 one_liner → title 取前 30 字；outline name=短标题+后缀；description 保全文。"""
    repo = _make_repo()
    session = _session(
        one_liner=_LONG_ONE_LINER,
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={"q1": "武侠为主融合仙侠", "q2": "约 300 万字", "q3": "主角是玄明"},
    )
    repo.get_planner_session.return_value = session
    outline_service = AsyncMock(return_value=_outline_dummy())
    svc = _make_service(repo, outline_service=outline_service)

    result = await _complete_round2(svc, session, {"q4": "3 卷", "q5": "配角自定"})

    plan = result.writing_plan
    assert plan is not None
    assert plan.title != _LONG_ONE_LINER, "title 仍是 one_liner 整句直赋"
    assert len(plan.title) <= 30, f"title 未短化: len={len(plan.title)}"
    assert _LONG_ONE_LINER.startswith(plan.title)  # 前缀截取而非改写
    kwargs = outline_service.await_args.kwargs
    assert kwargs["description"] == _LONG_ONE_LINER  # 完整构思进 description
    assert kwargs["name"].startswith(plan.title)
    assert "（书级大纲）" in kwargs["name"]
    assert len(kwargs["name"]) <= 40


@pytest.mark.asyncio
async def test_complete_short_one_liner_title_unchanged():
    """≤30 字 one_liner：title 保持原文（向后兼容既有契约）。"""
    one_liner = "写一本关于时间旅者的悬疑小说"  # 15 字
    repo = _make_repo()
    session = _session(
        one_liner=one_liner,
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={"q1": "悬疑", "q2": "8 万字", "q3": "主角是时间旅者"},
    )
    repo.get_planner_session.return_value = session
    svc = _make_service(repo)

    result = await _complete_round2(svc, session, {"q4": "1 卷", "q5": "配角自定"})

    assert result.writing_plan is not None
    assert result.writing_plan.title == one_liner


@pytest.mark.asyncio
async def test_auto_paths_title_shortened():
    """auto() 与 respond(auto=True) 路径同规则短化（现象 2 同源缺口）。"""
    repo = _make_repo()
    svc = _make_service(repo)
    plan = await svc.auto(_pid(), _LONG_ONE_LINER)
    assert len(plan.title) <= 30
    assert _LONG_ONE_LINER.startswith(plan.title)

    session = _session(one_liner=_LONG_ONE_LINER)
    repo.get_planner_session.return_value = session
    result = await svc.respond(session.id, {}, auto=True)
    assert result.writing_plan is not None
    assert len(result.writing_plan.title) <= 30


# ── 契约 3：主角 role_rank（#927 现象 3）─────────────────────────


@pytest.mark.asyncio
async def test_complete_character_extra_has_role_rank():
    """_complete 建主角必须传 extra={'role_rank': 'protagonist'}（#833 契约）。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={"q1": "悬疑", "q2": "8 万字", "q3": "主角是叶知秋"},
    )
    repo.get_planner_session.return_value = session
    character_service = AsyncMock(return_value=_char_dummy())
    svc = _make_service(repo, character_service=character_service)

    result = await _complete_round2(svc, session, {"q4": "1 卷", "q5": "配角自定"})

    assert result.completed is True
    call = character_service.await_args
    assert call is not None
    extra = call.kwargs.get("extra")
    assert extra is not None, "主角创建未传 extra（绕过 role_rank 校验，#927）"
    assert extra.get("role_rank") == "protagonist"


# ── 契约 4：limits 从访谈 answers 提取（#927 现象 4，拍板）───────


@pytest.mark.asyncio
async def test_limits_extracted_from_answers():
    """回答含「前 10 章」→ max_chapters=10 / max_agent_calls=20（卷轨委托余量）。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={"q1": "悬疑", "q2": "约 10 万字", "q3": "主角是时间旅者"},
    )
    repo.get_planner_session.return_value = session
    svc = _make_service(repo)

    result = await _complete_round2(svc, session, {"q4": "第一阶段前 10 章", "q5": "配角自定"})

    plan = result.writing_plan
    assert plan is not None
    assert plan.limits["max_chapters"] == 10, f"limits 未从 answers 提取: {plan.limits}"
    assert plan.limits["max_agent_calls"] == 20


@pytest.mark.asyncio
async def test_limits_takes_max_across_answers():
    """多处命中取最大值（30 章 vs 10 章 → 30）。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={"q1": "悬疑", "q2": "30 章完结", "q3": "主角是时间旅者"},
    )
    repo.get_planner_session.return_value = session
    svc = _make_service(repo)

    result = await _complete_round2(svc, session, {"q4": "分 3 卷共 30 章", "q5": "配角自定"})

    assert result.writing_plan is not None
    assert result.writing_plan.limits["max_chapters"] == 30
    assert result.writing_plan.limits["max_agent_calls"] == 60


@pytest.mark.asyncio
async def test_limits_extracted_from_confirmed_items():
    """confirmed_items 的 value 同为提取源（LLM 路径确定项「章节数=10 章」）。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={"q1": "悬疑", "q2": "中篇", "q3": "主角是时间旅者"},
        confirmed_items=[{"key": "章节数", "value": "10 章", "source": "user"}],
    )
    repo.get_planner_session.return_value = session
    svc = _make_service(repo)

    result = await _complete_round2(svc, session, {"q4": "1 卷", "q5": "配角自定"})

    assert result.writing_plan is not None
    assert result.writing_plan.limits["max_chapters"] == 10


@pytest.mark.asyncio
async def test_limits_ignores_chapter_reference():
    """「第 5 章」是章序引用非章数——不得误提取（防误抽护栏）。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={"q1": "悬疑", "q2": "8 万字", "q3": "主角是时间旅者"},
    )
    repo.get_planner_session.return_value = session
    svc = _make_service(repo)

    result = await _complete_round2(svc, session, {"q4": "从第 5 章开始续", "q5": "配角自定"})

    assert result.writing_plan is not None
    assert result.writing_plan.limits["max_chapters"] == 1  # 保守兜底不变


@pytest.mark.asyncio
async def test_limits_conservative_default_without_number():
    """无章数信息 → STAGE1 保守兜底（1/1，向后兼容既有行为）。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={"q1": "悬疑", "q2": "几万字吧", "q3": "主角是时间旅者"},
    )
    repo.get_planner_session.return_value = session
    svc = _make_service(repo)

    result = await _complete_round2(svc, session, {"q4": "随意", "q5": "配角自定"})

    assert result.writing_plan is not None
    assert result.writing_plan.limits["max_chapters"] == 1
    assert result.writing_plan.limits["max_agent_calls"] == 1
