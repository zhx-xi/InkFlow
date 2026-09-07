"""F44 #995 planner 主角名短名化契约（TDD RED）。

权威来源：specs/f44-book-orchestrator/spec.md §5.1 产物质量护栏（#927 家族第 5
变体）+ Issue #995 D4 拍板修订：LLM 分析返回人名为主 + 服务端规则截断兜底。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约）
════════════════════════════════════════════════════════════════════

1. 【服务端短名化】`_protagonist_name` 对「主角」确定项 value / q3 提取片段统一
   短名化：取首顿号/逗号（、或，）前片段；结果仍超 50 字符（CharacterCreate name
   上限）→ [:20] 截断兜底（对齐 #927-2 [:30] 短化口径）；纯人名原样保留。
2. 【prompt 约束】访谈提取侧要求 LLM「主角」键 value 恒为纯人名：
   - i18n 模板 zh/en planner_interview.yaml system_prompt 含指令
     （zh「只填主角姓名」/ en "ONLY the protagonist name"）；
   - llm_client 装配 + prompt_manager 未装配的手工 prompt system 消息含同款指令。
3. 【RED 预期形态】当前实现 value 整句原样返回 → 短名化/prompt 类用例 FAIL；
   纯人名/40 字内无标点护栏用例现即 PASS（防误伤）。
"""

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

_LONG_PROTAGONIST_VALUE = "叶知秋，地球转世，十四岁觉醒前世记忆，十六岁继承师父为真子的蜀山掌门"
"""#995 实测脏数据形态：LLM 把整句生平塞进「主角」value（31+ 字，<50 校验放行）。"""


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


def _char_dummy() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _make_service(repo: AsyncMock, **kwargs) -> PlannerService:
    return PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())),
        **kwargs,
    )


# ── 契约 1：confirmed_items「主角」value 短名化 ──────────────────


@pytest.mark.asyncio
async def test_protagonist_long_value_splits_first_segment():
    """长句 value → 取首逗号前短名「叶知秋」（#995 主契约）。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        confirmed_items=[
            {"key": "主角", "value": _LONG_PROTAGONIST_VALUE, "source": "llm_inferred"}
        ],
    )
    repo.get_planner_session.return_value = session
    character_service = AsyncMock(return_value=_char_dummy())
    svc = _make_service(repo, character_service=character_service)

    await svc.respond(session.id, {"q4": "3 卷", "q5": "配角自定"})

    assert character_service.await_args.kwargs["name"] == "叶知秋"


@pytest.mark.asyncio
async def test_protagonist_long_value_splits_dun_comma():
    """长句 value 用顿号分隔 → 同样取首片段。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        confirmed_items=[{"key": "主角", "value": "玄明、破落宗门继承者", "source": "user"}],
    )
    repo.get_planner_session.return_value = session
    character_service = AsyncMock(return_value=_char_dummy())
    svc = _make_service(repo, character_service=character_service)

    await svc.respond(session.id, {"q4": "3 卷", "q5": "配角自定"})

    assert character_service.await_args.kwargs["name"] == "玄明"


@pytest.mark.asyncio
async def test_protagonist_pure_name_preserved():
    """纯人名 value（无标点短名）→ 原样保留（防误伤护栏）。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        confirmed_items=[{"key": "主角", "value": "叶知秋", "source": "user"}],
    )
    repo.get_planner_session.return_value = session
    character_service = AsyncMock(return_value=_char_dummy())
    svc = _make_service(repo, character_service=character_service)

    await svc.respond(session.id, {"q4": "3 卷", "q5": "配角自定"})

    assert character_service.await_args.kwargs["name"] == "叶知秋"


@pytest.mark.asyncio
async def test_protagonist_no_punctuation_within_50_preserved():
    """无标点且 ≤50 字符 → 原样（规则只在超限/含分隔符时介入）。"""
    value = "杰" * 40
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        confirmed_items=[{"key": "主角", "value": value, "source": "llm_inferred"}],
    )
    repo.get_planner_session.return_value = session
    character_service = AsyncMock(return_value=_char_dummy())
    svc = _make_service(repo, character_service=character_service)

    await svc.respond(session.id, {"q4": "3 卷", "q5": "配角自定"})

    assert character_service.await_args.kwargs["name"] == value


@pytest.mark.asyncio
async def test_protagonist_no_punctuation_over_50_truncated_20():
    """无标点且 >50 字符（含首片段仍超长的形态）→ [:20] 截断兜底。"""
    value = "名" * 55
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        confirmed_items=[{"key": "主角", "value": f"{value}，背景补充", "source": "llm_inferred"}],
    )
    repo.get_planner_session.return_value = session
    character_service = AsyncMock(return_value=_char_dummy())
    svc = _make_service(repo, character_service=character_service)

    await svc.respond(session.id, {"q4": "3 卷", "q5": "配角自定"})

    assert character_service.await_args.kwargs["name"] == value[:20]


# ── 契约 2：q3 回退路径同样短名化 ────────────────────────────────


@pytest.mark.asyncio
async def test_protagonist_q3_long_sentence_normalized():
    """无「主角」确定项、q3 回答含整句 → 提取片段同样短名化。"""
    repo = _make_repo()
    session = _session(
        round=2,
        asked_questions=list(ROUND2_QUESTIONS),
        answers={"q3": "主角是叶知秋，地球转世，少年承继蜀山掌门之位"},
    )
    repo.get_planner_session.return_value = session
    character_service = AsyncMock(return_value=_char_dummy())
    svc = _make_service(repo, character_service=character_service)

    await svc.respond(session.id, {"q4": "3 卷", "q5": "配角自定"})

    assert character_service.await_args.kwargs["name"] == "叶知秋"


# ── 契约 3：访谈 prompt 主角键值约束纯人名 ───────────────────────


@pytest.mark.parametrize(
    "lang,needle", [("zh", "只填主角姓名"), ("en", "ONLY the protagonist name")]
)
def test_planner_interview_yaml_constrains_protagonist_value(lang: str, needle: str):
    """i18n 模板（zh/en）system_prompt 必须含「主角 value=纯人名」约束（#995）。"""
    path = Path(inkflow.__file__).parent / "i18n" / "prompts" / lang / "planner_interview.yaml"
    content = path.read_text(encoding="utf-8")
    assert needle in content, f"{lang} planner_interview.yaml 缺少主角键纯人名约束（#995）"


@pytest.mark.asyncio
async def test_manual_prompt_constrains_protagonist_value():
    """手工 prompt（无 prompt_manager）system 必须含主角键纯人名约束。"""
    repo = _make_repo()
    payload = (
        '{"questions": ['
        '{"id": "q1", "text": "题材：武侠还是仙侠？", "template": "以 ___ 为主", "kind": "gen"},'
        '{"id": "q2", "text": "篇幅：全书多少字？", "template": "约 ___", "kind": "general"},'
        '{"id": "q3", "text": "主题：一句话主题？", "template": "主题是 ___", "kind": "general"}'
        '], "confirmed_items": [], "conflicts": []}'
    )
    llm = AsyncMock()
    llm.chat.return_value = ChatResponse(content=payload, model="test")
    svc = _make_service(repo, llm_client=llm, llm_default_model="test/model")

    await svc.start(_pid(), "写一本武侠仙侠门派经营小说")

    messages = llm.chat.await_args.args[0]
    system = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
    assert "只填主角姓名" in system, "手工 prompt 缺少主角键纯人名约束（#995）"
